"""
Parser for the Torah Weave dataset (Moshe Kline, chaver.com).

Reads torah-units.json (86 literary units of the Torah with 2D cell mappings)
and yields normalized unit + cell records ready for database insertion.

Each unit is a self-contained 2D literary composition. Cell labels like "2Ba"
encode row=2, column=B, subdivision=a. Horizontal partners (same row, same
subdivision, different column) are parallel correspondences; vertical partners
(same column, same subdivision, different row) are progressions through
divine-name registers along a thematic track.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterator

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
    return c_start, v_start, c_end, v_end


def _sort_key(chapter: int, verse: int) -> int:
    """Encode (chapter, verse) as a sortable integer for range queries."""
    return chapter * 1000 + verse


def parse_torah_weave_file(filepath: Path) -> Iterator[tuple[dict, list[dict]]]:
    """Parse the torah-units.json file.

    Yields tuples of (unit_dict, cells_list) — one per literary unit.
    Each unit_dict has fields for torah_weave_units.
    Each cell in cells_list has fields for torah_weave_cells.
    """
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

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
                # Skip malformed cells but keep importing the rest
                print(f"  Warning: {book_full} unit {unit['id']} cell {label}: {exc}")
                continue

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
