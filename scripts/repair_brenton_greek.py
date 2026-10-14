#!/usr/bin/env python3
"""Recompute Brenton's English and Greek beside the Rahlfs rows of an existing database.

compare_biblical_versions shows Brenton's English beside the Rahlfs Septuagint
and flags "Brenton's Greek differs" where the Greek his English translates
differs from Rahlfs. Both come from eBible's Brenton USFM files at import time
(study_bible_mcp.parsers.biblical_versions), and three faults put the wrong
text beside some verses:

* eBible's Greek repeats a few verses by mistake (Numbers 34:10 is a copy of
  34:11; Job 3:14 and 3 Kingdoms 8:58 begin with the verse before; 1
  Chronicles 11:24 ends with the verse after), which raised false
  differences in those verses and their neighbours.
* Where Brenton numbers a passage differently, a Rahlfs verse whose own
  number went to another verse kept that verse's English and Greek
  (4 Maccabees 8:1 showed 8:2's), instead of the Brenton verse that holds it.
* Section headings with a level number (\\s1) were read as verse text.

The rows that differ from a fresh import of the pinned sources are updated
in place: only their translation, brenton_greek_differs, brenton_greek and
brenton_greek_difference columns.

Two modes, both idempotent:

  repair_brenton_greek.py DB [--data-dir data] [--write-patch PATCH]
      Read the sources under data/lxx/ and the database's own bsb_verses
      table, and update the rows that differ. --write-patch also saves the
      changes for another copy of the same database (the Fly volume), which
      has no data/ directory.

  repair_brenton_greek.py DB --apply-patch PATCH
      Apply a saved patch. Needs only the standard library, so it runs on the
      server from a copy of this script.

A row is changed only while it still holds what the patch expects to replace
(or already holds the result); anything else rolls back the whole run, so
nothing is changed.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# biblical_version_verses columns this repair may change.
COLUMNS = ("translation", "brenton_greek_differs", "brenton_greek", "brenton_greek_difference")
# A row: its edition verse and MT position (unique together), and its Rahlfs text.
IDENTITY = ("edition", "edition_reference", "canonical_reference", "text")
# Field order of the tuples parsers.biblical_versions.iter_lxx_rows yields.
_ROW_FIELDS = (
    "edition", "canonical_reference", "canonical_book", "canonical_chapter", "canonical_verse",
    "canonical_verse_suffix", "edition_reference", "edition_book", "edition_chapter",
    "edition_verse", "edition_verse_suffix", "text", "translation", "morphology",
    "mapping_method", "brenton_greek_differs", "brenton_greek", "brenton_greek_difference",
)


def _current_rows(conn: sqlite3.Connection) -> dict[tuple, tuple[int, dict]]:
    """Every biblical_version_verses row as {(edition, edition_reference, canonical_reference): (id, row)}."""
    rows: dict[tuple, tuple[int, dict]] = {}
    for row_id, *values in conn.execute(
        f"SELECT id, {', '.join(IDENTITY + COLUMNS)} FROM biblical_version_verses ORDER BY id"
    ):
        row = dict(zip(IDENTITY + COLUMNS, values))
        key = tuple(row[column] for column in IDENTITY[:3])
        if key in rows:
            raise SystemExit(f"biblical_version_verses holds {key} twice; rebuild it with build_database.py")
        rows[key] = (row_id, row)
    return rows


def compute_changes(conn: sqlite3.Connection, data_dir: Path) -> dict:
    """Return {"update": {id: {"row": [edition, edition_reference, canonical_reference],
    "columns": {column: [old, new]}}}} for the rows a fresh import would change."""
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
    from study_bible_mcp.parsers.biblical_versions import (
        bsb_by_reference,
        iter_lxx_rows,
        load_lxx_pairings,
        missing_lxx_sources,
        parse_brenton_usfm,
    )

    lxx_dir = data_dir / "lxx"
    missing = missing_lxx_sources(lxx_dir)
    if missing:
        raise SystemExit(f"Incomplete LXX sources in {lxx_dir}: missing {', '.join(missing)}")
    wanted: dict[tuple, dict] = {}
    for values in iter_lxx_rows(
        lxx_dir / "morphology",
        load_lxx_pairings(lxx_dir / "verse_pairs.jsonl"),
        parse_brenton_usfm(lxx_dir / "brenton"),
        parse_brenton_usfm(lxx_dir / "brenton-greek"),
        bsb_by_reference(conn),
    ):
        row = dict(zip(_ROW_FIELDS, values))
        wanted[tuple(row[column] for column in IDENTITY[:3])] = row

    current = _current_rows(conn)
    if set(current) != set(wanted) or any(current[key][1]["text"] != row["text"] for key, row in wanted.items()):
        raise SystemExit(
            "biblical_version_verses does not hold the rows of these LXX sources "
            f"({len(current)} rows, {len(wanted)} expected); rebuild it with build_database.py"
        )
    update: dict[str, dict] = {}
    for key, new in wanted.items():
        row_id, old = current[key]
        changed = {column: [old[column], new[column]] for column in COLUMNS if old[column] != new[column]}
        if changed:
            update[str(row_id)] = {"row": list(key), "columns": changed}
    return {"update": update}


def apply_changes(conn: sqlite3.Connection, changes: dict) -> tuple[int, list[str]]:
    """Apply changes in one transaction; return (rows updated, conflicting rows)."""
    updated = 0
    conflicts: list[str] = []
    for row_id, change in changes["update"].items():
        held = conn.execute(
            f"SELECT {', '.join(IDENTITY[:3] + COLUMNS)} FROM biblical_version_verses WHERE id = ?",
            (int(row_id),),
        ).fetchone()
        if held is None or list(held[:3]) != change["row"]:
            conflicts.append(f"id {row_id} {change['row']}")
            continue
        values = dict(zip(COLUMNS, held[3:]))
        columns = change["columns"]
        if all(values[column] == new for column, (_, new) in columns.items()):
            continue
        if any(values[column] != old for column, (old, _) in columns.items()):
            conflicts.append(f"id {row_id} {change['row']}")
            continue
        conn.execute(
            f"UPDATE biblical_version_verses SET {', '.join(f'{column} = ?' for column in columns)} WHERE id = ?",
            (*(new for _, new in columns.values()), int(row_id)),
        )
        updated += 1
    return updated, conflicts


def _summary(changes: dict) -> str:
    counts = {column: 0 for column in COLUMNS}
    for change in changes["update"].values():
        for column in change["columns"]:
            counts[column] += 1
    return ", ".join(f"{column} {count}" for column, count in counts.items())


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
            source = f"the sources in {args.data_dir}"
            if args.write_patch:
                with gzip.open(args.write_patch, "wt", encoding="utf-8") as handle:
                    json.dump(changes, handle, ensure_ascii=False, separators=(",", ":"))

        updated, conflicts = apply_changes(conn, changes)
        if conflicts:
            conn.rollback()
            print(
                f"ERROR: {len(conflicts)} rows hold neither the old nor the new values "
                f"(first: {'; '.join(conflicts[:5])}); nothing was changed",
                file=sys.stderr,
            )
            return 1
        conn.commit()
    finally:
        conn.close()

    print(f"{args.db}: {source} has")
    print(f"   biblical_version_verses: {len(changes['update'])} to update ({updated} updated)")
    if changes["update"]:
        print(f"   changed columns: {_summary(changes)}")
    print("   the rest already matched")
    if args.write_patch:
        print(f"   patch written to {args.write_patch}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
