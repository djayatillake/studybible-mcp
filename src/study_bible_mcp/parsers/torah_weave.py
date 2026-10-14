"""
Parser for the Torah Weave dataset (Moshe Kline, chaver.com).

Reads torah-units.json (86 literary units of the Torah with 2D cell mappings)
and yields normalized unit + cell records ready for database insertion.

Each unit is a self-contained 2D literary composition. Cell labels like "2Ba"
encode row=2, column=B, subdivision=a. Horizontal partners (same row, same
subdivision, different column) are parallel correspondences; vertical partners
(same column, same subdivision, different row) are progressions through
divine-name registers along a thematic track.

Provenance: version 1.1 of the dataset (corrections dated 2026-09-15), fetched
from TORAH_WEAVE_SOURCE_URL on 2026-10-14 and committed as
data/torah_weave/torah-units.json. The file is not versioned in its URL, so it
is pinned by SHA-256 (TORAH_WEAVE_SHA256) and the import fails on any other
file. Licence: CC BY 4.0, as the file's own "license" field states;
attribution to Moshe Kline (chaver.com) is required. Version 1.1 fills the cell
maps of twelve units that skipped verses in 1.0 and corrects five units'
verse_range. Its 86 units hold 600 cells, 1,019 counting subdivisions (one
torah_weave_cells row each).

Verse numbers follow the Hebrew Bible (Leviticus 5:20-26 is English 6:1-7,
Deuteronomy 28:69 is English 29:1); the database layer converts them.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Iterator
from pathlib import Path

TORAH_WEAVE_SOURCE_URL = "https://chaver.com/torah-weave/data/torah-units.json"
TORAH_WEAVE_FILENAME = "torah-units.json"
TORAH_WEAVE_VERSION = "1.1"
TORAH_WEAVE_RETRIEVED = "2026-10-14"
TORAH_WEAVE_LICENSE = "CC BY 4.0 (Moshe Kline, chaver.com)"
# SHA-256 of the reviewed version 1.1 file (56,335 bytes). When Kline publishes
# a new version, review the changes before updating this.
TORAH_WEAVE_SHA256: str | None = (
    "60ea3c92120a57180ea371ac5fdc577a993ac0839cbc8e1208717e74368a93af"
)
# Rows a full import writes; a different count means the file or parser changed.
TORAH_WEAVE_EXPECTED_UNITS = 86
TORAH_WEAVE_EXPECTED_CELLS = 1019

# Torah books only — the weave data covers Genesis through Deuteronomy
BOOK_NAME_TO_ABBREV = {
    "Genesis": "Gen",
    "Exodus": "Exo",
    "Leviticus": "Lev",
    "Numbers": "Num",
    "Deuteronomy": "Deu",
}

# Cell label pattern: digits + optional uppercase letter(s) + optional lowercase
# subdivision. Examples: "1A", "2B", "2Ba", "1Bb", "10Ac", and "1"/"5" for
# single-column rows inside irregular units (format strings like "12221").
_CELL_LABEL_RE = re.compile(r"^(\d+)([A-Z]*)([a-z]?)$")

# Verse range pattern: "C:V" or "C:V-C:V" or "C:V-V"
_VERSE_RANGE_RE = re.compile(
    r"^(\d+):(\d+)(?:-(?:(\d+):)?(\d+))?$"
)

UNIT_COLUMNS = (
    "id", "book", "book_full", "unit_number", "title", "verses", "verse_range",
    "format", "irregular", "is_unique", "cell_count", "type",
    "cell_count_with_subdivisions",
)
CELL_COLUMNS = (
    "id", "unit_id", "cell_label", "row_num", "column_letter", "subdivision",
    "book", "verse_range", "chapter_start", "verse_start", "chapter_end",
    "verse_end", "sort_start", "sort_end",
)


def _parse_cell_label(label: str) -> tuple[int, str, str | None]:
    """Parse a cell label into (row, column, subdivision).

    "2Ba" → (2, "B", "a")
    "1A"  → (1, "A", None)
    "1"   → (1, "",  None)   — single-column row in an irregular unit
    """
    m = _CELL_LABEL_RE.match(label.strip())
    if not m:
        raise ValueError(f"Invalid cell label: {label!r}")
    row_str, col, sub = m.groups()
    return int(row_str), col, (sub or None)


def _parse_verse_range(verse_str: str) -> tuple[int, int, int, int]:
    """Parse a verse range string into (c_start, v_start, c_end, v_end).

    "6:1"        → (6, 1, 6, 1)
    "6:1-6:4"    → (6, 1, 6, 4)
    "6:1-4"      → (6, 1, 6, 4)
    "1:17-2:3"   → (1, 17, 2, 3)
    """
    m = _VERSE_RANGE_RE.match(verse_str.strip())
    if not m:
        raise ValueError(f"Invalid verse range: {verse_str!r}")
    c1, v1, c2, v2 = m.groups()
    c_start = int(c1)
    v_start = int(v1)
    if v2 is None:
        # Single verse: "6:1"
        c_end, v_end = c_start, v_start
    elif c2 is None:
        # "6:1-4" — same chapter
        c_end, v_end = c_start, int(v2)
    else:
        # "1:17-2:3"
        c_end, v_end = int(c2), int(v2)
    if (c_end, v_end) < (c_start, v_start):
        raise ValueError(f"Verse range runs backwards: {verse_str!r}")
    return c_start, v_start, c_end, v_end


def _sort_key(chapter: int, verse: int) -> int:
    """Encode (chapter, verse) as a sortable integer for range queries."""
    return chapter * 1000 + verse


def verify_torah_weave_checksum(content: bytes) -> None:
    """Raise ValueError unless ``content`` matches the pinned TORAH_WEAVE_SHA256."""
    if not TORAH_WEAVE_SHA256:
        raise ValueError(
            f"TORAH_WEAVE_SHA256 is not set in {__name__}. Review "
            f"{TORAH_WEAVE_SOURCE_URL} and pin its SHA-256 before importing it."
        )
    actual = hashlib.sha256(content).hexdigest()
    if actual != TORAH_WEAVE_SHA256:
        raise ValueError(
            f"Checksum mismatch for {TORAH_WEAVE_FILENAME}: {actual} != pinned "
            f"{TORAH_WEAVE_SHA256} (version {TORAH_WEAVE_VERSION}). Review the upstream "
            "changes before updating TORAH_WEAVE_SHA256."
        )


def _no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    """json object hook: a repeated key (two cells with one label) is an error."""
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Key {key!r} appears twice in one object")
        result[key] = value
    return result


def parse_torah_weave(data: dict) -> Iterator[tuple[dict, list[dict]]]:
    """Yield (unit_dict, cells_list) for each unit of a loaded torah-units.json.

    Each unit_dict has fields for torah_weave_units; each cell in cells_list
    has fields for torah_weave_cells (without its row id). Raises ValueError
    on a cell label or verse range it cannot read, so no cell is dropped.
    """
    for unit_data in data.get("units", []):
        book_full = unit_data["book"]
        book_abbr = BOOK_NAME_TO_ABBREV.get(book_full)
        if book_abbr is None:
            continue  # Skip non-Torah entries, if any

        unit = {
            "id": int(unit_data["serial_number"]),
            "book": book_abbr,
            "book_full": book_full,
            "unit_number": int(unit_data["unit_number"]),
            "title": unit_data["title"],
            "verses": unit_data.get("verses", ""),
            "verse_range": unit_data.get("verse_range", ""),
            "format": unit_data.get("format", ""),
            "irregular": 1 if unit_data.get("irregular") else 0,
            "is_unique": 1 if unit_data.get("unique") else 0,
            "cell_count": int(unit_data.get("cells", 0)),
            "type": unit_data.get("type"),
            "cell_count_with_subdivisions": int(
                unit_data.get("cell_count_with_subdivisions") or 0
            ),
        }

        cells = []
        cells_detail = unit_data.get("cells_detail", {})
        for label, verse_range in cells_detail.items():
            try:
                row, col, sub = _parse_cell_label(label)
                c_start, v_start, c_end, v_end = _parse_verse_range(verse_range)
            except ValueError as exc:
                raise ValueError(f"{book_full} unit {unit['id']} cell {label}: {exc}") from exc

            cells.append({
                "unit_id": unit["id"],
                "cell_label": label,
                "row_num": row,
                "column_letter": col,
                "subdivision": sub,
                "book": book_abbr,
                "verse_range": verse_range,
                "chapter_start": c_start,
                "verse_start": v_start,
                "chapter_end": c_end,
                "verse_end": v_end,
                "sort_start": _sort_key(c_start, v_start),
                "sort_end": _sort_key(c_end, v_end),
            })

        yield unit, cells


def load_torah_weave(content: bytes) -> dict:
    """Verify ``content`` against the pinned checksum and load it as JSON."""
    verify_torah_weave_checksum(content)
    return json.loads(content.decode("utf-8"), object_pairs_hook=_no_duplicate_keys)


def parse_torah_weave_file(filepath: Path) -> Iterator[tuple[dict, list[dict]]]:
    """Parse the pinned torah-units.json; see ``parse_torah_weave``.

    Raises ValueError if the file does not match TORAH_WEAVE_SHA256.
    """
    yield from parse_torah_weave(load_torah_weave(Path(filepath).read_bytes()))


def torah_weave_rows(filepath: Path) -> tuple[list[tuple], list[tuple]]:
    """(unit rows, cell rows) for torah_weave_units and torah_weave_cells.

    Rows are tuples in UNIT_COLUMNS / CELL_COLUMNS order. Cells are numbered
    1..N in file order, the ids a fresh import into an empty table gives.
    Raises ValueError on a checksum mismatch or an unexpected row count.
    """
    units: list[tuple] = []
    cells: list[tuple] = []
    for unit, unit_cells in parse_torah_weave_file(filepath):
        units.append(tuple(unit[column] for column in UNIT_COLUMNS))
        for cell in unit_cells:
            row = {"id": len(cells) + 1, **cell}
            cells.append(tuple(row[column] for column in CELL_COLUMNS))
    if (len(units), len(cells)) != (TORAH_WEAVE_EXPECTED_UNITS, TORAH_WEAVE_EXPECTED_CELLS):
        raise ValueError(
            f"{TORAH_WEAVE_FILENAME} gives {len(units)} units and {len(cells)} cells; expected "
            f"{TORAH_WEAVE_EXPECTED_UNITS} and {TORAH_WEAVE_EXPECTED_CELLS}."
        )
    return units, cells


def import_torah_weave(conn: sqlite3.Connection, filepath: Path) -> tuple[int, int]:
    """Replace both Torah Weave tables with the pinned file's rows.

    Verifies the file first (see ``torah_weave_rows``); on any failure nothing is
    changed. Re-running gives the same tables as a fresh import, cell ids
    included. Returns (units, cells).
    """
    units, cells = torah_weave_rows(filepath)
    with conn:
        conn.execute("DELETE FROM torah_weave_cells")
        conn.execute("DELETE FROM torah_weave_units")
        conn.execute("DELETE FROM sqlite_sequence WHERE name = 'torah_weave_cells'")
        conn.executemany(
            f"INSERT INTO torah_weave_units ({', '.join(UNIT_COLUMNS)}) "
            f"VALUES ({', '.join('?' * len(UNIT_COLUMNS))})",
            units,
        )
        conn.executemany(
            f"INSERT INTO torah_weave_cells ({', '.join(CELL_COLUMNS)}) "
            f"VALUES ({', '.join('?' * len(CELL_COLUMNS))})",
            cells,
        )
    return len(units), len(cells)
