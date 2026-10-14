#!/usr/bin/env python3
"""Bring an existing bsb_verses table into line with the pinned bsb.txt.

The deployed table was built ad hoc from an older, messier copy of the BSB:
stray spaces around closing quotes, brackets and dashes (524 verses), speaker
headings inside Song of Songs verses (5), older wording in 8 verses, and no
Psalm headings. The importer now builds the table from the publisher's pinned
bsb.txt (study_bible_mcp.parsers.bsb), so this script changes only the rows that
differ from a fresh import, and adds the 116 Psalm heading rows (verse 0).

Two modes, both idempotent:

  repair_bsb_verses.py DB [--data-dir data] [--write-patch PATCH]
      Read data/bsb/bsb.txt (checksum-verified), and update the changed rows in
      place. --write-patch also saves the changes for another copy of the same
      database (the Fly volume), which has no data/ directory.

  repair_bsb_verses.py DB --apply-patch PATCH
      Apply a saved patch. Needs only the standard library, so it runs on the
      server from a copy of this script.

A row is changed only while it still holds the text the patch expects to
replace; anything else rolls back the whole run, so nothing is changed.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def compute_changes(conn: sqlite3.Connection, data_dir: Path) -> dict:
    """Return {"update": {ref: [old, new]}, "insert": {ref: row}, "delete": {ref: old}}."""
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
    from study_bible_mcp.parsers.bsb import BSB_FILENAME, bsb_rows

    path = data_dir / "bsb" / BSB_FILENAME
    if not path.exists():
        raise SystemExit(f"No {path}; run scripts/download_bsb.py first")
    rows = bsb_rows(path.read_bytes())
    current = dict(conn.execute("SELECT reference, text FROM bsb_verses"))
    wanted = {row[0]: row for row in rows}
    return {
        "update": {
            ref: [current[ref], row[4]]
            for ref, row in wanted.items()
            if ref in current and current[ref] != row[4]
        },
        "insert": {ref: list(row[1:]) for ref, row in wanted.items() if ref not in current},
        "delete": {ref: text for ref, text in current.items() if ref not in wanted},
    }


def apply_changes(conn: sqlite3.Connection, changes: dict) -> tuple[dict[str, int], list[str]]:
    """Apply changes in one transaction; return (counts applied, conflicting references)."""
    applied = {"update": 0, "insert": 0, "delete": 0}
    conflicts: list[str] = []
    current = dict(conn.execute("SELECT reference, text FROM bsb_verses"))
    for ref, (old, new) in changes["update"].items():
        if current.get(ref) == new:
            continue
        if current.get(ref) != old:
            conflicts.append(ref)
            continue
        conn.execute("UPDATE bsb_verses SET text = ? WHERE reference = ?", (new, ref))
        applied["update"] += 1
    for ref, (book, chapter, verse, text) in changes["insert"].items():
        if ref in current:
            if current[ref] != text:
                conflicts.append(ref)
            continue
        conn.execute(
            "INSERT INTO bsb_verses (reference, book, chapter, verse, text) VALUES (?, ?, ?, ?, ?)",
            (ref, book, chapter, verse, text),
        )
        applied["insert"] += 1
    for ref, old in changes["delete"].items():
        if ref not in current:
            continue
        if current[ref] != old:
            conflicts.append(ref)
            continue
        conn.execute("DELETE FROM bsb_verses WHERE reference = ?", (ref,))
        applied["delete"] += 1
    return applied, conflicts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("db", type=Path)
    parser.add_argument("--data-dir", type=Path, default=PROJECT_ROOT / "data")
    parser.add_argument("--write-patch", type=Path)
    parser.add_argument("--apply-patch", type=Path)
    args = parser.parse_args()
    if not args.db.exists():
        raise SystemExit(f"No database at {args.db}")

    conn = sqlite3.connect(args.db)
    try:
        if args.apply_patch:
            with gzip.open(args.apply_patch, "rt", encoding="utf-8") as handle:
                changes = json.load(handle)
            source = f"the patch {args.apply_patch}"
        else:
            changes = compute_changes(conn, args.data_dir)
            source = "the pinned bsb.txt"
            if args.write_patch:
                with gzip.open(args.write_patch, "wt", encoding="utf-8") as handle:
                    json.dump(changes, handle, ensure_ascii=False, separators=(",", ":"))

        applied, conflicts = apply_changes(conn, changes)
        if conflicts:
            conn.rollback()
            print(
                f"ERROR: {len(conflicts)} bsb_verses rows hold neither the old nor the new "
                f"text (first: {', '.join(conflicts[:5])}); nothing was changed",
                file=sys.stderr,
            )
            return 1
        conn.commit()
    finally:
        conn.close()

    counts = ", ".join(f"{len(changes[kind])} to {kind}" for kind in ("update", "insert", "delete"))
    done = ", ".join(
        f"{applied[kind]} {verb}"
        for kind, verb in (("update", "updated"), ("insert", "inserted"), ("delete", "deleted"))
    )
    print(f"{args.db}: {source} has {counts}")
    print(f"   {done}; the rest already matched")
    if args.write_patch:
        print(f"   patch written to {args.write_patch}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
