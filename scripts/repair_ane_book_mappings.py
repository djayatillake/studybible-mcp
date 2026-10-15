#!/usr/bin/env python3
"""Give each book of a multi-book ANE entry its own chapter range in an existing database.

Twenty-one ANE entries listed several books with one entry-level chapter range,
and the parser copied that range to every book: the temple-as-cosmos entry,
written for Exodus 25-40, was also mapped to 1 Kings 25-40, Ezekiel 25-40 and
Revelation 25-40, so get_ane_context(reference=...) ranked it on chapters it
never cites and missed the ones it does (1 Kings 6, Ezekiel 40-48, Revelation
21). The data files now give each book its own ranges, taken from the entry's
key references, with the original range kept for the book it was written for;
the parser refuses the old shape. This script swaps the ane_book_mappings rows
for exactly what a fresh import of data/ane_context/*.json writes.

Two modes, both idempotent:

  repair_ane_book_mappings.py DB [--data-dir data] [--write-patch PATCH]
      Read data/ane_context/*.json and replace the table in place. --write-patch
      also saves the rows for another copy of the same database (the Fly
      volume), which has no data/ directory.

  repair_ane_book_mappings.py DB --apply-patch PATCH
      Apply a saved patch. Needs only the standard library, so it runs on the
      server from a copy of this script.

The table is replaced only while it holds exactly the rows the old parser
wrote (its fingerprint, below, equals BEFORE_FINGERPRINT). A table that already
holds the corrected rows is left alone; anything else is refused. The check
and the swap run in one transaction, so on any failure nothing is changed.
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

# Columns written, in order (scripts/build_database.py import_ane_context;
# repeated here so --apply-patch needs only the stdlib).
COLUMNS = ("entry_id", "book", "chapter_start", "chapter_end")
# fingerprint() of the table the old parser wrote: the master database's rows,
# which equal a fresh import of data/ane_context at git 2a572c3 (478 rows).
BEFORE_FINGERPRINT = "249104bb257cd029e7e14c0359c5e8efb6587a46890edbba49d4810054db6bc2"


def rows_fingerprint(rows: list) -> str:
    """SHA-256 of the mapping rows (COLUMNS), independent of their order."""
    canonical = json.dumps(
        sorted((list(row) for row in rows), key=lambda row: json.dumps(row)),
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def fingerprint(conn: sqlite3.Connection) -> str:
    """rows_fingerprint of the database's current ane_book_mappings table."""
    return rows_fingerprint(
        conn.execute(f"SELECT {', '.join(COLUMNS)} FROM ane_book_mappings").fetchall()
    )


def build_patch(data_dir: Path) -> dict:
    """The mapping rows a fresh import writes, with the fingerprints to check."""
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
    from study_bible_mcp.parsers.ane_context import parse_ane_context_file

    files = sorted((data_dir / "ane_context").glob("*.json"))
    if not files:
        raise SystemExit(f"No ANE context files in {data_dir / 'ane_context'}")
    rows, keys = [], set()
    for path in files:
        try:
            for _entry, mappings in parse_ane_context_file(path):
                for mapping in mappings:
                    row = [mapping[column] for column in COLUMNS]
                    key = tuple(row[:3])
                    # The table's primary key; a repeat would be replaced, not added.
                    if row[2] is not None and key in keys:
                        raise SystemExit(f"{path.name}: mapping {key} appears twice")
                    keys.add(key)
                    rows.append(row)
        except ValueError as exc:
            raise SystemExit(f"ERROR: {path.name}: {exc}") from exc
    return {
        "table": "ane_book_mappings",
        "from": BEFORE_FINGERPRINT,
        "to": rows_fingerprint(rows),
        "columns": list(COLUMNS),
        "rows": rows,
    }


class RefusedError(Exception):
    """The table is not in a state the patch may replace."""


def apply_patch(conn: sqlite3.Connection, patch: dict) -> int | None:
    """Swap the table for the patch rows; return the number of rows replaced.

    Returns None when the table already holds the patch rows. Raises
    RefusedError, having changed nothing, when it holds anything other than
    the rows the patch replaces, or when the patch is inconsistent.
    """
    if patch.get("columns") != list(COLUMNS):
        raise RefusedError("the patch's column list differs from this script's")
    rows = patch["rows"]
    if rows_fingerprint(rows) != patch["to"]:
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
                "ane_book_mappings holds neither the old parser's rows nor the "
                f"corrected ones (fingerprint {current})"
            )
        replaced = conn.execute("SELECT COUNT(*) FROM ane_book_mappings").fetchone()[0]
        conn.execute("DELETE FROM ane_book_mappings")
        conn.executemany(
            f"INSERT INTO ane_book_mappings ({', '.join(COLUMNS)}) "
            f"VALUES ({', '.join('?' * len(COLUMNS))})",
            rows,
        )
        if fingerprint(conn) != patch["to"]:
            raise RefusedError("the replaced table does not match the patch")
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
        source = "data/ane_context"
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

    print(f"{args.db}: {source} has {len(patch['rows'])} ANE book mappings")
    if replaced is None:
        print("   the table already holds them; nothing changed")
    else:
        print(f"   replaced {replaced} mappings written by the old parser")
    if args.write_patch:
        print(f"   patch written to {args.write_patch}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
