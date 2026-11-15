#!/usr/bin/env python3
"""Shorten the Gage/Bradley cross-reference notes in an existing database.

Columns B and D of data/bradley_gage_john_rev.xlsx quote each side of a pair,
and some quotes are whole passages: notes ran to 2,078 characters (734 on
average per row), and get_cross_references printed them in full.
scripts/ingest_burnett_gage.py now keeps, for a side over 160 characters, only
the sentences that share the most words with the other side and the
commentary. This script rewrites the note of every gage row to exactly what a
fresh ingest now writes; sources, targets and relevances are unchanged.

Two modes, both idempotent:

  repair_gage_notes.py DB [--xlsx data/bradley_gage_john_rev.xlsx] [--write-patch PATCH]
      Rebuild the notes from the spreadsheet (needs openpyxl) and rewrite them
      in place. --write-patch also saves them for another copy of the same
      database (the Fly volume), which has no spreadsheet.

  repair_gage_notes.py DB --apply-patch PATCH
      Apply a saved patch. Needs only the standard library, so it runs on the
      server from a copy of this script.

The notes are rewritten only while the gage rows are exactly the ones the old
ingest wrote (their fingerprint equals BEFORE_FINGERPRINT). Rows that already
hold the new notes are left alone; anything else is refused. The check and the
rewrite run in one transaction, so on any failure nothing is changed.
"""

from __future__ import annotations

import argparse
import contextlib
import gzip
import hashlib
import io
import json
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
COLUMNS = ("source", "target", "relevance", "note")
# fingerprint() of the gage rows the old ingest wrote: the master database's
# 2,030 rows, equal to a fresh ingest at git f8a2793.
BEFORE_FINGERPRINT = "863fbeea6a05a9ebdb6dc23cfeb0f38383abace1a6f3c2113dfa34b3fa43e2ac"


def rows_fingerprint(rows: list) -> str:
    """SHA-256 of the gage rows (COLUMNS), independent of their order."""
    canonical = json.dumps(sorted(list(row) for row in rows), ensure_ascii=False,
                           separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def fingerprint(conn: sqlite3.Connection) -> str:
    """rows_fingerprint of the database's current gage rows."""
    return rows_fingerprint(conn.execute(
        f"SELECT {', '.join(COLUMNS)} FROM cross_references WHERE type = 'gage'"
    ).fetchall())


def patch_from_rows(rows: list) -> dict:
    """A patch that rewrites the gage rows to `rows` (COLUMNS order)."""
    rows = [list(row) for row in rows]
    return {
        "table": "cross_references",
        "type": "gage",
        "from": BEFORE_FINGERPRINT,
        "to": rows_fingerprint(rows),
        "columns": list(COLUMNS),
        "rows": rows,
    }


def build_patch(xlsx: Path) -> dict:
    """The gage rows a fresh ingest of the spreadsheet writes."""
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    import ingest_burnett_gage as ingest

    if not xlsx.exists():
        raise SystemExit(f"No spreadsheet at {xlsx}")
    ingest.XLSX_PATH = xlsx
    with contextlib.redirect_stdout(io.StringIO()):
        pairs = ingest.collect_gage_pairs()
    rows, _ = ingest.gage_rows(pairs)
    return patch_from_rows(rows)


class RefusedError(Exception):
    """The rows are not in a state the patch may rewrite."""


def apply_patch(conn: sqlite3.Connection, patch: dict) -> int | None:
    """Rewrite the gage notes to the patch's; return the number of notes changed.

    Returns None when the rows already hold the patch's notes. Raises
    RefusedError, having changed nothing, when they hold anything other than
    the rows the patch rewrites, or when the patch is inconsistent.
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
                "the gage rows hold neither the old ingest's notes nor the new "
                f"ones (fingerprint {current})"
            )
        changed = 0
        for source, target, relevance, note in rows:
            cursor = conn.execute(
                "UPDATE cross_references SET note = ? WHERE type = 'gage' "
                "AND source = ? AND target = ? AND relevance = ? AND note IS NOT ?",
                (note, source, target, relevance, note),
            )
            changed += cursor.rowcount
        if fingerprint(conn) != patch["to"]:
            raise RefusedError("the rewritten rows do not match the patch")
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("db", type=Path)
    parser.add_argument("--xlsx", type=Path,
                        default=PROJECT_ROOT / "data" / "bradley_gage_john_rev.xlsx")
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
        patch = build_patch(args.xlsx)
        source = args.xlsx.name
        if args.write_patch:
            with gzip.open(args.write_patch, "wt", encoding="utf-8") as handle:
                json.dump(patch, handle, ensure_ascii=False, separators=(",", ":"))

    conn = sqlite3.connect(args.db)
    try:
        changed = apply_patch(conn, patch)
    except (RefusedError, sqlite3.Error) as exc:
        print(f"ERROR: {exc}; nothing was changed", file=sys.stderr)
        return 1
    finally:
        conn.close()

    print(f"{args.db}: {source} has {len(patch['rows'])} gage rows")
    if changed is None:
        print("   they already hold the new notes; nothing changed")
    else:
        print(f"   rewrote {changed} notes written by the old ingest")
    if args.write_patch:
        print(f"   patch written to {args.write_patch}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
