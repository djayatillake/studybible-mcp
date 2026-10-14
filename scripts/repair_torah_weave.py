#!/usr/bin/env python3
"""Replace an existing database's Torah Weave tables (version 1.0) with version 1.1.

The deployed torah_weave_units and torah_weave_cells tables hold Moshe Kline's
version 1.0 dataset (imported April 2026: 86 units, 952 cells), whose cell maps
skip 344 verses in fourteen units, so get_torah_weave gave those verses no
partners. Version 1.1 (data/torah_weave/torah-units.json, pinned by SHA-256 in
study_bible_mcp.parsers.torah_weave) fills twelve of those maps and corrects
five units' verse ranges: 86 units, 1,019 cells. This script swaps the rows of
both tables for exactly what a fresh import of 1.1 writes, cell ids included.

Two modes, both idempotent:

  repair_torah_weave.py DB [--data-dir data] [--write-patch PATCH]
      Read data/torah_weave/torah-units.json (checksum-verified) and replace the
      tables in place. --write-patch also saves the rows for another copy of the
      same database (the Fly volume), which has no data/ directory.

  repair_torah_weave.py DB --apply-patch PATCH
      Apply a saved patch. Needs only the standard library, so it runs on the
      server from a copy of this script.

The tables are replaced only while they hold exactly the version 1.0 rows (their
fingerprint, below, equals V1_0_FINGERPRINT). Tables that already hold 1.1 are
left alone; anything else is refused. The check and the swap run in one
transaction, so on any failure nothing is changed.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Columns written, in order (study_bible_mcp.parsers.torah_weave UNIT_COLUMNS
# and CELL_COLUMNS; repeated here so --apply-patch needs only the stdlib).
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
# fingerprint() of the version 1.0 tables. The production database's rows equal
# a fresh import of the 1.0 file (git 14c35bd, SHA-256
# 7d95de4355d71bd96606b44ddc457763eef22f35ce8c61810fb17359ce76ada5) apart from
# their cell ids (940-1891 there), which the fingerprint ignores.
V1_0_FINGERPRINT = "c1ca85f1ea69189e7946baf1a4b260c57c51fe4bad42340e0fcdc8a6c499e8af"


def rows_fingerprint(units: list, cells: list) -> str:
    """SHA-256 of unit rows (UNIT_COLUMNS) and cell rows (CELL_COLUMNS less id).

    Units are taken in id order and cells in (unit_id, cell_label) order, so the
    value depends only on the content, not on insertion order or cell ids.
    """
    canonical = json.dumps(
        [sorted(map(list, units), key=lambda unit: unit[0]),
         sorted(map(list, cells), key=lambda cell: (cell[0], cell[1]))],
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def fingerprint(conn: sqlite3.Connection) -> str:
    """rows_fingerprint of the database's current Torah Weave tables."""
    units = conn.execute(f"SELECT {', '.join(UNIT_COLUMNS)} FROM torah_weave_units").fetchall()
    cells = conn.execute(f"SELECT {', '.join(CELL_COLUMNS[1:])} FROM torah_weave_cells").fetchall()
    return rows_fingerprint(units, cells)


def build_patch(data_dir: Path) -> dict:
    """The version 1.1 rows from the pinned file, with the fingerprints to check."""
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
    from study_bible_mcp.parsers import torah_weave

    if (torah_weave.UNIT_COLUMNS, torah_weave.CELL_COLUMNS) != (UNIT_COLUMNS, CELL_COLUMNS):
        raise SystemExit("Column lists differ from study_bible_mcp.parsers.torah_weave")
    path = data_dir / "torah_weave" / torah_weave.TORAH_WEAVE_FILENAME
    if not path.exists():
        raise SystemExit(f"No {path}")
    try:
        units, cells = torah_weave.torah_weave_rows(path)
    except ValueError as exc:
        raise SystemExit(f"ERROR: {exc}") from exc
    return {
        "dataset": "Torah Weave (Moshe Kline, chaver.com, CC BY 4.0)",
        "version": torah_weave.TORAH_WEAVE_VERSION,
        "source_url": torah_weave.TORAH_WEAVE_SOURCE_URL,
        "source_sha256": torah_weave.TORAH_WEAVE_SHA256,
        "from": V1_0_FINGERPRINT,
        "to": rows_fingerprint(units, [cell[1:] for cell in cells]),
        "unit_columns": list(UNIT_COLUMNS),
        "cell_columns": list(CELL_COLUMNS),
        "units": [list(unit) for unit in units],
        "cells": [list(cell) for cell in cells],
    }


class RefusedError(Exception):
    """The tables are not in a state the patch may replace."""


def apply_patch(conn: sqlite3.Connection, patch: dict) -> tuple[int, int] | None:
    """Swap the tables for the patch rows; return the (units, cells) replaced.

    Returns None when the tables already hold the patch rows. Raises
    RefusedError, having changed nothing, when they hold anything other than
    the rows the patch replaces, or when the patch is inconsistent.
    """
    if (patch.get("unit_columns"), patch.get("cell_columns")) != (
        list(UNIT_COLUMNS), list(CELL_COLUMNS)
    ):
        raise RefusedError("the patch's column lists differ from this script's")
    units, cells = patch["units"], patch["cells"]
    if rows_fingerprint(units, [cell[1:] for cell in cells]) != patch["to"]:
        raise RefusedError("the patch rows do not match its own 'to' fingerprint")

    conn.isolation_level = None  # explicit transaction below
    conn.execute("BEGIN IMMEDIATE")
    try:
        current = fingerprint(conn)
        if current == patch["to"]:
            conn.execute("ROLLBACK")
            return None
        if current != patch["from"]:
            raise RefusedError(
                f"torah_weave tables hold neither version 1.0 nor {patch['version']} "
                f"(fingerprint {current})"
            )
        replaced = (
            conn.execute("SELECT COUNT(*) FROM torah_weave_units").fetchone()[0],
            conn.execute("SELECT COUNT(*) FROM torah_weave_cells").fetchone()[0],
        )
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
        if fingerprint(conn) != patch["to"]:
            raise RefusedError("the replaced tables do not match the patch")
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return replaced


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("db", type=Path)
    parser.add_argument("--data-dir", type=Path, default=PROJECT_ROOT / "data")
    parser.add_argument("--write-patch", type=Path)
    parser.add_argument("--apply-patch", type=Path)
    args = parser.parse_args()
    if not args.db.exists():
        raise SystemExit(f"No database at {args.db}")
    if args.apply_patch and args.write_patch:
        raise SystemExit("Use --write-patch or --apply-patch, not both")

    if args.apply_patch:
        with gzip.open(args.apply_patch, "rt", encoding="utf-8") as handle:
            patch = json.load(handle)
        source = f"the patch {args.apply_patch}"
    else:
        patch = build_patch(args.data_dir)
        source = "the pinned torah-units.json"
        if args.write_patch:
            with gzip.open(args.write_patch, "wt", encoding="utf-8") as handle:
                json.dump(patch, handle, ensure_ascii=False, separators=(",", ":"))

    conn = sqlite3.connect(args.db)
    try:
        replaced = apply_patch(conn, patch)
    except (RefusedError, sqlite3.Error) as exc:
        print(f"ERROR: {exc}; nothing was changed", file=sys.stderr)
        return 1
    finally:
        conn.close()

    print(
        f"{args.db}: {source} has Torah Weave {patch['version']}: "
        f"{len(patch['units'])} units, {len(patch['cells'])} cells"
    )
    if replaced is None:
        print(f"   the tables already hold version {patch['version']}; nothing changed")
    else:
        print(
            f"   replaced {replaced[0]} units and {replaced[1]} cells (version 1.0) "
            f"with version {patch['version']}"
        )
    if args.write_patch:
        print(f"   patch written to {args.write_patch}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
