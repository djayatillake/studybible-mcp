"""
Parsers for cross-reference datasets.

Two sources, both normalised to (source_ref, target_ref, relevance) tuples
using our internal `Book.Chapter.Verse` reference format (e.g. "Gen.1.1"):

* CH — Harrison & Romhild's curated cross-reference dataset (xlsx).
  Columns: Book1, Chapter1, Verse1, Book2, Chapter2, Verse2, Orig, Circ.
  Books are 1..66 in canonical Protestant order. We encode
  relevance = Orig*2 + Circ so flagged "original direction" pairs and
  "circle" members rank above plain pairs.

* TSK — Treasury of Scripture Knowledge via openbible.info (TSV).
  Columns: From Verse, To Verse, Votes. Verse refs use long-form book
  abbreviations (Mark, Eccl, Ps, ...) which we map to our short codes.
  Relevance = raw vote count.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

# Canonical book ordinal (CH numeric codes) → our internal abbrev.
CH_BOOKS = {
    1: "Gen", 2: "Exo", 3: "Lev", 4: "Num", 5: "Deu",
    6: "Jos", 7: "Jdg", 8: "Rut", 9: "1Sa", 10: "2Sa",
    11: "1Ki", 12: "2Ki", 13: "1Ch", 14: "2Ch",
    15: "Ezr", 16: "Neh", 17: "Est", 18: "Job", 19: "Psa",
    20: "Pro", 21: "Ecc", 22: "Sng", 23: "Isa", 24: "Jer",
    25: "Lam", 26: "Ezk", 27: "Dan", 28: "Hos", 29: "Jol",
    30: "Amo", 31: "Oba", 32: "Jon", 33: "Mic", 34: "Nam",
    35: "Hab", 36: "Zep", 37: "Hag", 38: "Zec", 39: "Mal",
    40: "Mat", 41: "Mrk", 42: "Luk", 43: "Jhn", 44: "Act",
    45: "Rom", 46: "1Co", 47: "2Co", 48: "Gal", 49: "Eph",
    50: "Php", 51: "Col", 52: "1Th", 53: "2Th", 54: "1Ti",
    55: "2Ti", 56: "Tit", 57: "Phm", 58: "Heb", 59: "Jas",
    60: "1Pe", 61: "2Pe", 62: "1Jn", 63: "2Jn", 64: "3Jn",
    65: "Jud", 66: "Rev",
}

# TSK long-form abbrev → our internal abbrev. Anything missing here is
# silently dropped (and counted as a warning by the importer).
TSK_BOOK_MAP = {
    "Gen": "Gen", "Exod": "Exo", "Lev": "Lev", "Num": "Num", "Deut": "Deu",
    "Josh": "Jos", "Judg": "Jdg", "Ruth": "Rut",
    "1Sam": "1Sa", "2Sam": "2Sa", "1Kgs": "1Ki", "2Kgs": "2Ki",
    "1Chr": "1Ch", "2Chr": "2Ch", "Ezra": "Ezr", "Neh": "Neh",
    "Esth": "Est", "Job": "Job", "Ps": "Psa", "Prov": "Pro",
    "Eccl": "Ecc", "Song": "Sng", "Isa": "Isa", "Jer": "Jer",
    "Lam": "Lam", "Ezek": "Ezk", "Dan": "Dan", "Hos": "Hos",
    "Joel": "Jol", "Amos": "Amo", "Obad": "Oba", "Jonah": "Jon",
    "Mic": "Mic", "Nah": "Nam", "Hab": "Hab", "Zeph": "Zep",
    "Hag": "Hag", "Zech": "Zec", "Mal": "Mal",
    "Matt": "Mat", "Mark": "Mrk", "Luke": "Luk", "John": "Jhn",
    "Acts": "Act", "Rom": "Rom", "1Cor": "1Co", "2Cor": "2Co",
    "Gal": "Gal", "Eph": "Eph", "Phil": "Php", "Col": "Col",
    "1Thess": "1Th", "2Thess": "2Th", "1Tim": "1Ti", "2Tim": "2Ti",
    "Titus": "Tit", "Phlm": "Phm", "Heb": "Heb", "Jas": "Jas",
    "1Pet": "1Pe", "2Pet": "2Pe", "1John": "1Jn", "2John": "2Jn",
    "3John": "3Jn", "Jude": "Jud", "Rev": "Rev",
}


def parse_ch_xlsx(filepath: Path) -> Iterator[tuple[str, str, int]]:
    """Yield (source_ref, target_ref, relevance) tuples from the CH xlsx.

    Skips the header row and any row whose book code falls outside 1..66.
    """
    import openpyxl

    wb = openpyxl.load_workbook(str(filepath), read_only=True, data_only=True)
    ws = wb.active

    rows = ws.iter_rows(values_only=True)
    header = next(rows, None)
    if not header or header[0] != "Book1":
        raise ValueError(
            f"Unexpected CH xlsx header: {header!r} "
            f"(expected first column 'Book1')"
        )

    for row in rows:
        if row is None or len(row) < 8:
            continue
        try:
            b1, c1, v1, b2, c2, v2, orig, circ = row[:8]
        except ValueError:
            continue
        if None in (b1, c1, v1, b2, c2, v2):
            continue

        src_book = CH_BOOKS.get(int(b1))
        tgt_book = CH_BOOKS.get(int(b2))
        if not src_book or not tgt_book:
            continue

        source = f"{src_book}.{int(c1)}.{int(v1)}"
        target = f"{tgt_book}.{int(c2)}.{int(v2)}"
        relevance = (int(orig or 0) * 2) + int(circ or 0)
        yield source, target, relevance

    wb.close()


def parse_tsk_tsv(filepath: Path) -> Iterator[tuple[str, str, int]]:
    """Yield (source_ref, target_ref, relevance) tuples from the TSK tsv.

    Drops rows whose book abbrev isn't in TSK_BOOK_MAP and rows with
    multi-verse targets (e.g. "Ps.1.1-Ps.1.3") — for those we keep the
    starting verse only, which mirrors how MCP clients ask for refs.
    """
    with open(filepath, "r", encoding="utf-8") as f:
        first = f.readline()
        if not first.startswith("From Verse\tTo Verse\tVotes"):
            raise ValueError(
                f"Unexpected TSK header: {first!r} (expected 'From Verse...')"
            )

        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            src_raw, tgt_raw, votes_raw = parts[0], parts[1], parts[2]
            try:
                votes = int(votes_raw)
            except ValueError:
                continue

            source = _normalise_tsk_ref(src_raw)
            target = _normalise_tsk_ref(tgt_raw)
            if source is None or target is None:
                continue
            yield source, target, votes


def _normalise_tsk_ref(raw: str) -> str | None:
    """'Mark.13.19' -> 'Mrk.13.19'; '1Cor.13.4-1Cor.13.7' -> '1Co.13.4'.

    Returns None if the book abbrev isn't recognised.
    """
    head = raw.split("-", 1)[0]  # ranges: keep the start verse
    parts = head.split(".")
    if len(parts) != 3:
        return None
    book_long, chapter, verse = parts
    book = TSK_BOOK_MAP.get(book_long)
    if not book:
        return None
    if not chapter.isdigit() or not verse.isdigit():
        return None
    return f"{book}.{int(chapter)}.{int(verse)}"
