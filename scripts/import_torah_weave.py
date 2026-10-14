#!/usr/bin/env python3
"""Import the Torah Weave dataset (Moshe Kline) into the study_bible database.

Reads data/torah_weave/torah-units.json and replaces:
  - torah_weave_units  (86 literary units)
  - torah_weave_cells  (1,019 rows: Kline's 600 cells, counting each
                        subdivision separately, with row/column/subdivision
                        and verse range)

Source: version 1.1 of https://chaver.com/torah-weave/data/torah-units.json,
retrieved 2026-10-14, CC BY 4.0 (Moshe Kline, chaver.com). The file is pinned by
SHA-256 (TORAH_WEAVE_SHA256 in src/study_bible_mcp/parsers/torah_weave.py) and
the import changes nothing unless the file matches it. Re-running the import
gives the same tables as a fresh build. To bring an existing database from
version 1.0 to 1.1, or the Fly volume, use scripts/repair_torah_weave.py.

Usage: import_torah_weave.py [DB]   (default: db/study_bible.db)
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from study_bible_mcp.database import create_schema
from study_bible_mcp.parsers.torah_weave import (
    TORAH_WEAVE_SOURCE_URL,
    TORAH_WEAVE_VERSION,
    import_torah_weave,
)


def get_db_path() -> Path:
    return PROJECT_ROOT / "db" / "study_bible.db"


def get_data_path() -> Path:
    return PROJECT_ROOT / "data" / "torah_weave" / "torah-units.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("db", type=Path, nargs="?", default=get_db_path())
    args = parser.parse_args()

    db_path = args.db
    if not db_path.exists():
        print(f"Database not found at {db_path}")
        print("Run build_database.py first to create the base database.")
        return 1

    data_path = get_data_path()
    if not data_path.exists():
        print(f"Torah Weave data not found at {data_path}")
        print(f"It ships with the repository; version {TORAH_WEAVE_VERSION} is {TORAH_WEAVE_SOURCE_URL}")
        return 1

    conn = sqlite3.connect(str(db_path))
    try:
        create_schema(conn)

        print("=" * 60)
        print(f"Importing Torah Weave {TORAH_WEAVE_VERSION} (Moshe Kline)")
        print("=" * 60)

        try:
            units, cells = import_torah_weave(conn, data_path)
        except ValueError as exc:
            print(f"ERROR: {exc}; nothing was changed", file=sys.stderr)
            return 1
        print(f"\n[Units] Imported {units} units")
        print(f"[Cells] Imported {cells} cells")

        print("\n" + "=" * 60)
        for table in ["torah_weave_units", "torah_weave_cells"]:
            row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            print(f"  {table}: {row[0]} rows")
        print("=" * 60)
    finally:
        conn.close()
    print("\nDone!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
