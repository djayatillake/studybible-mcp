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

The tools take English (BSB) references, so both sets are stored in English
numbering. CH numbers the Old Testament like the Hebrew Bible (Psalm titles
are verse 1, Joel 3:1 is English 2:28, Malachi 3:19 is English 4:1):
``EnglishNumbering`` renumbers it from the STEPBible `verses` table's
English(Hebrew) pairs. TSK uses English numbering; ``TSK_RENUMBER`` fixes the
few verses where its numbering is not the BSB's.
"""

from __future__ import annotations

import re
import zipfile
from collections.abc import Iterable, Iterator
from pathlib import Path
from xml.etree import ElementTree

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

# TSK verses numbered differently in the BSB. TSK's Philippians 1:16 and 1:17
# are the KJV's (contention, then defence of the gospel), which the BSB, like
# the Greek, prints in the other order; openbible.info's 3 John 1:15 is the end
# of the BSB's 1:14.
TSK_RENUMBER = {"Php.1.16": "Php.1.17", "Php.1.17": "Php.1.16", "3Jn.1.15": "3Jn.1.14"}

# A `verses` reference: plain ('Gen.1.1') or English(Hebrew) ('Psa.40.6(40.7)').
_PLAIN_RE = re.compile(r"^[^.]+\.\d+\.\d+$")
_ENGLISH_HEBREW_RE = re.compile(r"^([^.]+)\.(\d+)\.(\d+)\((\d+)\.(\d+)\)$")


class EnglishNumbering:
    """Renumber Hebrew-numbered verse references into English numbering.

    Built from the `verses` table's references, in table order: a plain
    reference ('Gen.1.1') is numbered alike in both, and an English(Hebrew)
    one ('Psa.40.6(40.7)') pairs the English verse with its Hebrew verse.
    """

    def __init__(self, verse_references: Iterable[str]):
        plain: set[str] = set()
        english: set[str] = set()
        split: dict[str, str] = {}
        for reference in verse_references:
            match = _ENGLISH_HEBREW_RE.match(reference)
            if match:
                book, chapter, verse, hebrew_chapter, hebrew_verse = match.groups()
                english_ref = f"{book}.{chapter}.{verse}"
                english.add(english_ref)
                # A Hebrew verse split over two English verses ('Psa.11.0(11.1)'
                # beside 'Psa.11.1') keeps its first English verse here and
                # its own number below, where a plain row has it.
                split.setdefault(f"{book}.{hebrew_chapter}.{hebrew_verse}", english_ref)
            elif _PLAIN_RE.match(reference):
                plain.add(reference)
                english.add(reference)
        self._plain = frozenset(plain)
        self._english = frozenset(english)
        self._split = split

    def from_hebrew(self, reference: str) -> str | None:
        """English reference for a Hebrew-numbered one, or None if neither has it.

        A Hebrew verse that is also a plain row keeps its number ('Psa.11.1':
        the psalm's opening words; its title is English verse 0). A reference
        only English numbering has (Malachi 4:1, which the Hebrew calls 3:19)
        is kept: the data already used English numbering there.
        """
        if reference in self._plain:
            return reference
        if reference in self._split:
            return self._split[reference]
        if reference in self._english:
            return reference
        return None


def renumber_pairs(
    pairs: Iterable[tuple[str, str, int]],
    renumber,
) -> Iterator[tuple[str, str, int]]:
    """Yield (source, target, relevance) with both references renumbered.

    ``renumber`` maps a reference to its new reference, or None to drop the
    pair (a verse in neither numbering). A pair that renumbers onto one verse
    (two Hebrew superscription verses both English verse 0) is dropped, and
    pairs that renumber onto the same pair are kept once, with the highest
    relevance, at the first one's position.
    """
    kept: dict[tuple[str, str], int] = {}
    for source, target, relevance in pairs:
        new_source, new_target = renumber(source), renumber(target)
        if new_source is None or new_target is None or new_source == new_target:
            continue
        key = (new_source, new_target)
        kept[key] = max(relevance, kept.get(key, relevance))
    for (source, target), relevance in kept.items():
        yield source, target, relevance


_XLSX_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def _xlsx_column(cell_ref: str) -> int:
    """0-based column index of a cell reference ('C12' -> 2)."""
    index = 0
    for char in cell_ref:
        if not char.isalpha():
            break
        index = index * 26 + ord(char.upper()) - 64
    return index - 1


def _xlsx_value(cell, shared: list[str]):
    kind = cell.get("t")
    if kind == "inlineStr":
        return "".join(text.text or "" for text in cell.iter(f"{_XLSX_NS}t"))
    value = cell.find(f"{_XLSX_NS}v")
    if value is None or value.text is None:
        return None
    if kind == "s":
        return shared[int(value.text)]
    if kind in ("str", "e"):
        return value.text
    if kind == "b":
        return value.text == "1"
    number = float(value.text)
    return int(number) if number.is_integer() else number


def read_xlsx_rows(filepath: Path) -> Iterator[tuple]:
    """Yield the first worksheet's rows as value tuples, with the standard library.

    Empty cells are None; every row is padded to the widest row seen so far,
    so a row's trailing empty cells still read as None.
    """
    with zipfile.ZipFile(filepath) as archive:
        names = archive.namelist()
        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            for item in ElementTree.fromstring(archive.read("xl/sharedStrings.xml")):
                shared.append("".join(text.text or "" for text in item.iter(f"{_XLSX_NS}t")))
        sheets = sorted(
            (name for name in names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name)),
            key=lambda name: int(re.search(r"(\d+)\.xml$", name).group(1)),
        )
        width = 0
        with archive.open(sheets[0]) as sheet:
            for _, element in ElementTree.iterparse(sheet):
                if element.tag != f"{_XLSX_NS}row":
                    continue
                values: dict[int, object] = {}
                for cell in element.iter(f"{_XLSX_NS}c"):
                    values[_xlsx_column(cell.get("r", "A"))] = _xlsx_value(cell, shared)
                element.clear()
                width = max(width, max(values, default=-1) + 1)
                yield tuple(values.get(column) for column in range(width))


def parse_ch_xlsx(filepath: Path) -> Iterator[tuple[str, str, int]]:
    """Yield (source_ref, target_ref, relevance) tuples from the CH xlsx.

    Skips the header row and any row whose book code falls outside 1..66.
    References keep the file's Hebrew numbering; see ``EnglishNumbering``.
    """
    rows = read_xlsx_rows(filepath)
    header = next(rows, None)
    if not header or header[0] != "Book1":
        raise ValueError(
            f"Unexpected CH xlsx header: {header!r} "
            f"(expected first column 'Book1')"
        )

    for row in rows:
        row = tuple(row) + (None,) * (8 - len(row))
        b1, c1, v1, b2, c2, v2, orig, circ = row[:8]
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


def parse_tsk_tsv(filepath: Path) -> Iterator[tuple[str, str, int]]:
    """Yield (source_ref, target_ref, relevance) tuples from the TSK tsv.

    Drops rows whose book abbrev isn't in TSK_BOOK_MAP and rows with
    multi-verse targets (e.g. "Ps.1.1-Ps.1.3") — for those we keep the
    starting verse only, which mirrors how MCP clients ask for refs.
    """
    with open(filepath, encoding="utf-8") as f:
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

    Returns None if the book abbrev isn't recognised. Verses the BSB numbers
    differently are renumbered (``TSK_RENUMBER``).
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
    reference = f"{book}.{int(chapter)}.{int(verse)}"
    return TSK_RENUMBER.get(reference, reference)
