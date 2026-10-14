#!/usr/bin/env python3
"""Apply the curated ACAI corrections to an existing database's acai_entities.

ACAI attaches some annotations to the wrong entity, and lookup_name showed
them: the Ramahs of Benjamin, Asher and Naphtali carried each other's labels
and descriptions (Benjamin's Ramah, Samuel's and Jeremiah's, was 'a town in
the territory of Simeon'), the patriarch Judah was 'also known as' David and
Jehoiakim as Zedekiah (English renderings that TIPNR lists under them), and
roles went to the wrong people (the priest John of Acts 4:6 and Peter's father
as disciples, Aiah with his daughter Rizpah's 'Concubine'). The corrections
are curated in src/study_bible_mcp/parsers/graph_curated.json ("acai"), each
with the source value it replaces and its reason, and a fresh build applies
them (scripts/build_database.py). This script brings an existing database
into line, changing only the corrected fields of those acai_entities rows.

Two modes, both idempotent:

  repair_acai_corrections.py DB [--data-dir data] [--write-patch PATCH]
      Re-parse data/acai/, check every correction against it, and update the
      rows. --write-patch also saves the changes, so a copy of the same
      database elsewhere (the Fly volume) can be repaired without the sources.

  repair_acai_corrections.py DB --apply-patch PATCH
      Apply a saved patch. Needs only the standard library, so it runs on the
      server from a copy of this script.

A row is updated only while the corrected fields still hold the values the
source gives them; a row already corrected is skipped. If any row holds
something else, or is missing, nothing is changed and the conflicts are
listed.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PATCH_VERSION = 1
TABLE = "acai_entities"


def compute_changes(data_dir: Path) -> dict:
    """The patch of graph_curated.json's ACAI corrections, checked against the sources."""
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
    from study_bible_mcp.parsers.acai import (
        CuratedAcaiError,
        apply_acai_corrections,
        parse_acai_dir,
    )
    from study_bible_mcp.parsers.theographic import load_curated

    acai_dir = data_dir / "acai"
    source = parse_acai_dir(acai_dir)
    if not source:
        raise SystemExit(f"No ACAI entity files under {acai_dir}")
    corrections = load_curated()["acai"]
    try:
        corrected = apply_acai_corrections(source, corrections, require_all=True)
    except CuratedAcaiError as error:
        raise SystemExit(f"{error}; nothing was changed") from None

    updates: dict[str, dict] = {}
    for fix in corrections:
        entity_id, field = fix["id"], fix["field"]
        old, new = source[entity_id][field], corrected[entity_id][field]
        update = updates.setdefault(entity_id, {"key": [entity_id], "set": {}, "reasons": []})
        update["set"][field] = [old, new]
        update["reasons"].append(f"{field}: {fix['reason']}")
    return {"version": PATCH_VERSION, "table": TABLE, "key": ["id"], "update": list(updates.values())}


def apply_changes(conn: sqlite3.Connection, changes: dict) -> tuple[int, list[str]]:
    """Apply a patch in one transaction; return (rows updated, conflicts)."""
    if changes.get("version") != PATCH_VERSION or changes.get("table") != TABLE:
        raise SystemExit(f"Not a {TABLE} corrections patch (version {changes.get('version')!r})")
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({TABLE})")}
    if not columns:
        return 0, [f"the database has no {TABLE} table"]
    if not conn.in_transaction:
        conn.execute("BEGIN")
    updated = 0
    conflicts = []
    for change in changes["update"]:
        (entity_id,) = change["key"]
        fields = list(change["set"])
        missing = [field for field in fields if field not in columns]
        if missing:
            conflicts.append(f"{TABLE} lacks columns {missing}")
            continue
        found = conn.execute(
            f"SELECT {', '.join(fields)} FROM {TABLE} WHERE id = ?", (entity_id,)
        ).fetchall()
        if len(found) != 1:
            conflicts.append(f"{entity_id}: row missing")
            continue
        values = list(found[0])
        old = [change["set"][field][0] for field in fields]
        new = [change["set"][field][1] for field in fields]
        if values == new:
            continue
        if values != old:
            changed = [f for f, value, expected in zip(fields, values, old) if value != expected]
            conflicts.append(f"{entity_id}: {', '.join(changed)} changed since the patch was made")
            continue
        conn.execute(
            f"UPDATE {TABLE} SET {', '.join(f'{field} = ?' for field in fields)} WHERE id = ?",
            [*new, entity_id],
        )
        updated += 1
    return updated, conflicts


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
        else:
            changes = compute_changes(args.data_dir)
            if args.write_patch:
                with gzip.open(args.write_patch, "wt", encoding="utf-8") as handle:
                    json.dump(changes, handle, ensure_ascii=False, separators=(",", ":"))

        updated, conflicts = apply_changes(conn, changes)
        if conflicts:
            conn.rollback()
            for conflict in conflicts:
                print(f"ERROR: {conflict}", file=sys.stderr)
            print("Nothing was changed", file=sys.stderr)
            return 1
        conn.commit()
    finally:
        conn.close()

    source = f"the patch {args.apply_patch}" if args.apply_patch else f"the sources in {args.data_dir}"
    rows = changes["update"]
    fields = sum(len(change["set"]) for change in rows)
    print(f"{args.db}, from {source}: {fields} corrected fields in {len(rows)} {TABLE} rows")
    if not updated:
        print("   the database already held every correction")
    elif updated < len(rows):
        print(f"   updated {updated} rows; the rest already held the corrections")
    else:
        print(f"   updated {updated} rows")
    if args.write_patch:
        print(f"   patch written to {args.write_patch}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
