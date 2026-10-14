"""Parse and import the Berean Standard Bible plain-text edition (``bsb.txt``).

The verse tools show the BSB as their English text. Its publisher dedicated the
text to the public domain and says so at the head of the file; the import
refuses a file that does not. The file is not versioned, so it is pinned by
SHA-256 (``BSB_SHA256``) and the import fails on any mismatch.

Expected layout: UTF-8, tab-separated, one verse per line on the KJV verse
grid, after a preamble (the publisher's statement and a column header)::

    ... This text of God's Word has been dedicated to the public domain. ...
    Verse<TAB>Berean Standard Bible
    Genesis 1:1<TAB>In the beginning God created the heavens and the earth.

Verses the BSB leaves out of its text (Matthew 17:21 and the like) have no
text there and are skipped. The file prints each Psalm's heading at the start of
verse 1; the import moves the 116 headings (bsb_psalm_headings.json) into verse
0 rows, matching the superscription rows of the verses table, so verse 1 is the
verse alone. Rows are ``('Gen.1.1', 'Gen', 1, 1, text)`` in file (canonical) order.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path

BSB_SOURCE_URL = "https://bereanbible.com/bsb.txt"
BSB_FILENAME = "bsb.txt"
# SHA-256 of the reviewed bsb.txt (4,331,393 bytes, downloaded 2026-10-14).
# scripts/download_bsb.py and import_bsb refuse any other file; when the
# publisher revises the text, review the changes before updating this.
BSB_SHA256: str | None = "2ac3af1de52d4e68261cba91d85c320b7eadc6560e830d99e591767b8ff5ca96"
# Verse rows in the production bsb_verses table (31,102 KJV-grid verses less
# the 16 the BSB omits); a different count means the file or parser changed.
BSB_EXPECTED_VERSES = 31_086
# Psalm number -> the heading the file prints at the start of verse 1.
BSB_PSALM_HEADINGS_PATH = Path(__file__).with_name("bsb_psalm_headings.json")
BSB_LICENSE = "Public domain (dedicated by the publisher; statement at the head of bsb.txt)"

# Book names as the BSB prints them, mapped to the database's book codes.
BSB_BOOKS = {
    "Genesis": "Gen", "Exodus": "Exo", "Leviticus": "Lev", "Numbers": "Num",
    "Deuteronomy": "Deu", "Joshua": "Jos", "Judges": "Jdg", "Ruth": "Rut",
    "1 Samuel": "1Sa", "2 Samuel": "2Sa", "1 Kings": "1Ki", "2 Kings": "2Ki",
    "1 Chronicles": "1Ch", "2 Chronicles": "2Ch", "Ezra": "Ezr", "Nehemiah": "Neh",
    "Esther": "Est", "Job": "Job", "Psalm": "Psa", "Psalms": "Psa", "Proverbs": "Pro",
    "Ecclesiastes": "Ecc", "Song of Solomon": "Sng", "Song of Songs": "Sng",
    "Isaiah": "Isa", "Jeremiah": "Jer", "Lamentations": "Lam", "Ezekiel": "Ezk",
    "Daniel": "Dan", "Hosea": "Hos", "Joel": "Jol", "Amos": "Amo", "Obadiah": "Oba",
    "Jonah": "Jon", "Micah": "Mic", "Nahum": "Nam", "Habakkuk": "Hab",
    "Zephaniah": "Zep", "Haggai": "Hag", "Zechariah": "Zec", "Malachi": "Mal",
    "Matthew": "Mat", "Mark": "Mrk", "Luke": "Luk", "John": "Jhn", "Acts": "Act",
    "Romans": "Rom", "1 Corinthians": "1Co", "2 Corinthians": "2Co",
    "Galatians": "Gal", "Ephesians": "Eph", "Philippians": "Php", "Colossians": "Col",
    "1 Thessalonians": "1Th", "2 Thessalonians": "2Th", "1 Timothy": "1Ti",
    "2 Timothy": "2Ti", "Titus": "Tit", "Philemon": "Phm", "Hebrews": "Heb",
    "James": "Jas", "1 Peter": "1Pe", "2 Peter": "2Pe", "1 John": "1Jn",
    "2 John": "2Jn", "3 John": "3Jn", "Jude": "Jud", "Revelation": "Rev",
}

_VERSE_RE = re.compile(r"(?P<book>[1-3]? ?[A-Z][A-Za-z ]*?) (?P<chapter>\d+):(?P<verse>\d+)")

BsbRow = tuple[str, str, int, int, str]


def sha256_hex(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def verify_bsb_checksum(content: bytes) -> None:
    """Raise ValueError unless ``content`` matches the pinned BSB_SHA256."""
    if not BSB_SHA256:
        raise ValueError(
            f"BSB_SHA256 is not set in {__name__}. Review {BSB_SOURCE_URL} and pin its "
            "SHA-256 before downloading or importing it."
        )
    actual = sha256_hex(content)
    if actual != BSB_SHA256:
        raise ValueError(
            f"Checksum mismatch for {BSB_FILENAME}: {actual} != pinned {BSB_SHA256}. "
            "Review the upstream changes before updating BSB_SHA256."
        )


def parse_bsb_text(text: str) -> tuple[list[str], list[BsbRow]]:
    """Split ``bsb.txt`` into its preamble lines and its verse rows.

    Raises ValueError on an unknown book, a repeated verse, or a non-verse
    line after the verses begin.
    """
    preamble: list[str] = []
    rows: list[BsbRow] = []
    seen: set[str] = set()
    for number, line in enumerate(text.lstrip("﻿").splitlines(), 1):
        if not line.strip():
            continue
        label, _, verse_text = line.partition("\t")
        match = _VERSE_RE.fullmatch(label.strip())
        if not match:
            if rows:
                raise ValueError(f"Line {number} is not a verse: {line[:80]!r}")
            preamble.append(line.strip())
            continue
        book = BSB_BOOKS.get(match["book"])
        if book is None:
            raise ValueError(f"Line {number}: unknown book {match['book']!r}")
        chapter, verse = int(match["chapter"]), int(match["verse"])
        reference = f"{book}.{chapter}.{verse}"
        if reference in seen:
            raise ValueError(f"Line {number}: {reference} appears twice")
        seen.add(reference)
        verse_text = verse_text.strip()
        if verse_text:
            rows.append((reference, book, chapter, verse, verse_text))
    return preamble, rows


def split_psalm_headings(rows: list[BsbRow], headings: dict[int, str]) -> list[BsbRow]:
    """Move each listed Psalm heading out of verse 1 into a verse 0 row before it.

    Raises ValueError if a listed Psalm's verse 1 does not start with its heading.
    """
    result: list[BsbRow] = []
    for reference, book, chapter, verse, text in rows:
        heading = headings.get(chapter) if book == "Psa" and verse == 1 else None
        if heading:
            if not text.startswith(heading + " "):
                raise ValueError(f"{reference} does not start with its heading {heading!r}")
            result.append((f"Psa.{chapter}.0", book, chapter, 0, heading))
            text = text[len(heading):].strip()
        result.append((reference, book, chapter, verse, text))
    moved = len(result) - len(rows)
    if moved != len(headings):
        raise ValueError(f"Moved {moved} Psalm headings; expected {len(headings)}.")
    return result


def load_psalm_headings(path: Path | None = None) -> dict[int, str]:
    text = (path or BSB_PSALM_HEADINGS_PATH).read_text("utf-8")
    return {int(psalm): heading for psalm, heading in json.loads(text).items()}


def bsb_rows(content: bytes) -> list[BsbRow]:
    """The bsb_verses rows for the pinned ``bsb.txt`` content.

    Verifies the checksum, the publisher's public-domain statement, the verse
    count and every Psalm heading; raises ValueError on any failure.
    """
    verify_bsb_checksum(content)
    preamble, rows = parse_bsb_text(content.decode("utf-8"))
    if not any("public domain" in line.lower() for line in preamble):
        raise ValueError(
            f"{BSB_FILENAME} does not open with the publisher's public-domain dedication; "
            "do not import it without checking its licence."
        )
    if len(rows) != BSB_EXPECTED_VERSES:
        raise ValueError(
            f"{BSB_FILENAME} has {len(rows)} verses; expected {BSB_EXPECTED_VERSES}."
        )
    return split_psalm_headings(rows, load_psalm_headings())


def import_bsb(conn: sqlite3.Connection, path: Path) -> int:
    """Replace the bsb_verses rows with the pinned ``bsb.txt`` at ``path``.

    Verifies the file first (see ``bsb_rows``); on any failure nothing is changed.
    Returns the number of rows: the verses plus the Psalm headings.
    """
    rows = bsb_rows(path.read_bytes())
    with conn:
        conn.execute("DELETE FROM bsb_verses")
        conn.executemany(
            "INSERT INTO bsb_verses (reference, book, chapter, verse, text) VALUES (?, ?, ?, ?, ?)",
            rows,
        )
    return len(rows)
