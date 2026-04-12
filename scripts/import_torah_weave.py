#!/usr/bin/env python3
"""Import the Torah Weave dataset (Moshe Kline) into the study_bible database.

Reads data/torah_weave/torah-units.json and populates:
  - torah_weave_units  (86 literary units)
  - torah_weave_cells  (~950 cells with row/column/subdivision + verse ranges)
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from study_bible_mcp.parsers.torah_weave import parse_torah_weave_file


def get_db_path() -> Path:
    return Path(__file__).resolve().parent.parent / "db" / "study_bible.db"


def get_data_path() -> Path:
    return (
        Path(__file__).resolve().parent.parent
        / "data"
        / "torah_weave"
        / "torah-units.json"
    )


def import_units(conn: sqlite3.Connection, filepath: Path) -> tuple[int, int]:
    """Import all units and cells. Returns (units_imported, cells_imported)."""
    unit_count = 0
    cell_count = 0

    for unit, cells in parse_torah_weave_file(filepath):
        try:
            conn.execute(
                """INSERT OR REPLACE INTO torah_weave_units
                   (id, book, book_full, unit_number, title, verses, verse_range,
                    format, irregular, is_unique, cell_count, type,
                    cell_count_with_subdivisions)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    unit["id"],
                    unit["book"],
                    unit["book_full"],
                    unit["unit_number"],
                    unit["title"],
                    unit["verses"],
                    unit["verse_range"],
                    unit["format"],
                    unit["irregular"],
                    unit["is_unique"],
                    unit["cell_count"],
                    unit["type"],
                    unit["cell_count_with_subdivisions"],
                ),
            )
            unit_count += 1
        except sqlite3.Error as e:
            print(f"  Warning: failed to insert unit {unit['id']} ({unit['title']}): {e}")
            continue

        # Clear any existing cells for this unit (supports re-import)
        conn.execute("DELETE FROM torah_weave_cells WHERE unit_id = ?", (unit["id"],))

        for cell in cells:
            try:
                conn.execute(
                    """INSERT INTO torah_weave_cells
                       (unit_id, cell_label, row_num, column_letter, subdivision,
                        book, verse_range, chapter_start, verse_start,
                        chapter_end, verse_end, sort_start, sort_end)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        cell["unit_id"],
                        cell["cell_label"],
                        cell["row_num"],
                        cell["column_letter"],
                        cell["subdivision"],
                        cell["book"],
                        cell["verse_range"],
                        cell["chapter_start"],
                        cell["verse_start"],
                        cell["chapter_end"],
                        cell["verse_end"],
                        cell["sort_start"],
                        cell["sort_end"],
                    ),
                )
                cell_count += 1
            except sqlite3.Error as e:
                print(
                    f"  Warning: failed to insert cell {cell['cell_label']} "
                    f"in unit {cell['unit_id']}: {e}"
                )

    conn.commit()
    return unit_count, cell_count


def main():
    db_path = get_db_path()
    if not db_path.exists():
        print(f"Database not found at {db_path}")
        print("Run build_database.py first to create the base database.")
        sys.exit(1)

    data_path = get_data_path()
    if not data_path.exists():
        print(f"Torah Weave data not found at {data_path}")
        print(
            "Download it from https://chaver.com/torah-weave/data/torah-units.json "
            "and place it there."
        )
        sys.exit(1)

    conn = sqlite3.connect(str(db_path))

    # Ensure schema exists
    from study_bible_mcp.database import create_schema
    create_schema(conn)

    print("=" * 60)
    print("Importing Torah Weave (Moshe Kline)")
    print("=" * 60)

    units, cells = import_units(conn, data_path)
    print(f"\n[Units] Imported {units} units")
    print(f"[Cells] Imported {cells} cells")

    # Summary
    print("\n" + "=" * 60)
    for table in ["torah_weave_units", "torah_weave_cells"]:
        row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        print(f"  {table}: {row[0]} rows")
    print("=" * 60)

    conn.close()
    print("\nDone!")


if __name__ == "__main__":
    main()
