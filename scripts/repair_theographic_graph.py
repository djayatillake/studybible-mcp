#!/usr/bin/env python3
"""Bring the people/places/events graph and the names table into line with the fixed importers.

A QA of the graph tools found errors that came from the importers and from
the sources, now fixed in scripts/import_theographic.py (through
src/study_bible_mcp/parsers/theographic.py), the TIPNR parser, the ACAI
parser and the curated file src/study_bible_mcp/parsers/graph_curated.json:

- graph_people gains display_title ('Simon Peter', 'Jacob (Israel)') and
  surname ('Peter', 'Pilate'), which the tools use to find people by the
  names Scripture uses and to tell namesakes apart; impossible life dates
  and Joseph's birthplace are corrected.
- graph_events: ISO-dated events ('0030-04-07') get their year; each
  event's sort_key becomes a chronological rank (year, then Theographic's
  predecessor chain, then Scripture order) instead of year plus book order;
  a few titles and one year are corrected; twenty curated events are added
  (the binding of Isaac, the burning bush, the fall of Jerusalem ...), with
  their people, places and verses.
- graph_event_place_edges, graph_verse_mentions, graph_places: misplaced
  events moved, mis-tagged verses removed, 'Straight Gate' renamed.
- names: TIPNR's OTHER records (Passover, the pillar Boaz, deities, months)
  become type 'thing' instead of 'person', and disputed relationships are
  labelled or dropped (David's 'parent' Nahash, Mary daughter of Heli,
  Matthew son of Mary).
- acai_entities: alternate labels that are textual notes ('Ketiv. Qere')
  are dropped from referred_to_as.

Two modes, both idempotent:

  repair_theographic_graph.py DB [--data-dir data] [--write-patch PATCH]
      Rebuild the graph rows from data/theographic/*.csv (as a fresh import
      would), re-parse data/TIPNR.txt, and change the database to match.
      --write-patch also saves the changes, so a copy of the same database
      elsewhere (the Fly volume) can be repaired without the sources.

  repair_theographic_graph.py DB --apply-patch PATCH
      Apply a saved patch. Needs only the standard library, so it runs on
      the server from a copy of this script.

Every row is changed only while it still holds what the patch expects: a row
to delete must still hold its old values, a row to update its old values in
the changed columns, a row to insert must not exist with other values. A row
already in its new state is skipped. If any row has drifted, nothing is
changed (the added columns included) and the conflicts are listed.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PATCH_VERSION = 1
NEW_COLUMNS = [("graph_people", "display_title", "TEXT"), ("graph_people", "surname", "TEXT")]
NAMES_COLUMNS = ("type", "description", "relationships")


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]


def _stored_rows(conn: sqlite3.Connection, table: str, columns: tuple[str, ...]) -> list[tuple]:
    """A table's rows in ``columns`` order; a column the table lacks reads as NULL."""
    present = set(_columns(conn, table))
    if not present:
        raise SystemExit(f"The database has no {table} table")
    select = ", ".join(c if c in present else "NULL" for c in columns)
    return [tuple(row) for row in conn.execute(f"SELECT {select} FROM {table}")]


def diff_table(old_rows: list[tuple], new_rows: list[tuple], columns, key) -> dict:
    """The inserts, deletes and updates that turn old_rows into new_rows."""
    key_index = [columns.index(c) for c in key]
    table = {"columns": list(columns), "key": list(key), "insert": [], "delete": [], "update": []}
    if len(key) == len(columns):  # a link table: its rows are its keys
        old, new = set(old_rows), set(new_rows)
        table["insert"] = [list(r) for r in new_rows if r not in old]
        table["delete"] = [list(r) for r in old_rows if r not in new]
        return table
    old = {tuple(r[i] for i in key_index): r for r in old_rows}
    new = {tuple(r[i] for i in key_index): r for r in new_rows}
    for k, row in new.items():
        if k not in old:
            table["insert"].append(list(row))
            continue
        changed = {
            c: [old[k][i], row[i]] for i, c in enumerate(columns)
            if i not in key_index and old[k][i] != row[i]
        }
        if changed:
            table["update"].append({"key": list(k), "set": changed})
    table["delete"] = [list(row) for k, row in old.items() if k not in new]
    return table


def names_changes(conn: sqlite3.Connection, tipnr: Path) -> dict:
    """Updates to names rows' type, description and relationships, by id."""
    from study_bible_mcp.parsers.proper_names import apply_tipnr_corrections, parse_tipnr
    from study_bible_mcp.parsers.theographic import load_curated

    expected: dict[tuple, list[tuple]] = defaultdict(list)
    entries = apply_tipnr_corrections(parse_tipnr(tipnr), load_curated()["tipnr"], require_all=True)
    for e in entries:
        expected[(e["name"], e["name_original"], e["references"])].append(
            (e["type"], e["description"], e["relationships"])
        )
    updates = []
    unknown = []
    for row_id, name, original, refs, *current in conn.execute(
        f"SELECT id, name, name_original, refs, {', '.join(NAMES_COLUMNS)} FROM names ORDER BY id"
    ):
        queue = expected.get((name, original, refs))
        if not queue:
            unknown.append(row_id)
            continue
        new = queue.pop(0)
        changed = {c: [current[i], new[i]] for i, c in enumerate(NAMES_COLUMNS) if current[i] != new[i]}
        if changed:
            updates.append({"key": [row_id], "set": changed})
    missing = sum(len(rest) for rest in expected.values())
    if unknown or missing:
        raise SystemExit(
            f"The names table does not match {tipnr} ({len(unknown)} rows not in TIPNR, "
            f"{missing} TIPNR entries not in the table; run repair_acai_and_header_rows.py "
            "first); nothing was changed"
        )
    return {"columns": ["id", *NAMES_COLUMNS], "key": ["id"], "insert": [], "delete": [], "update": updates}


def acai_changes(conn: sqlite3.Connection) -> dict:
    """referred_to_as without the labels that are not names, as a fresh ACAI import has it."""
    from study_bible_mcp.parsers.acai import is_name_label

    updates = []
    for entity_id, stored in conn.execute(
        "SELECT id, referred_to_as FROM acai_entities WHERE referred_to_as IS NOT NULL ORDER BY id"
    ):
        try:
            labels = json.loads(stored)
        except ValueError:
            continue
        if not isinstance(labels, list):
            continue
        kept = [label for label in labels if is_name_label(str(label))]
        if kept != labels:
            updates.append({"key": [entity_id], "set": {"referred_to_as": [stored, json.dumps(kept)]}})
    return {"columns": ["id", "referred_to_as"], "key": ["id"], "insert": [], "delete": [], "update": updates}


def compute_changes(conn: sqlite3.Connection, data_dir: Path) -> dict:
    """The patch that brings this database into line with the sources in data_dir."""
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
    from study_bible_mcp.parsers.theographic import TABLE_COLUMNS, TABLE_KEYS, build_graph

    csv_dir = data_dir / "theographic"
    tipnr = data_dir / "TIPNR.txt"
    for path in (csv_dir / "People.csv", csv_dir / "Events.csv", tipnr):
        if not path.exists():
            raise SystemExit(f"Missing source file: {path}")
    fresh = build_graph(csv_dir)
    tables = {}
    for table, rows in fresh.items():
        columns = TABLE_COLUMNS[table]
        stored = _stored_rows(conn, table, columns)
        tables[table] = diff_table(stored, [tuple(r) for r in rows], columns, TABLE_KEYS[table])
    tables["names"] = names_changes(conn, tipnr)
    tables["acai_entities"] = acai_changes(conn)
    return {"version": PATCH_VERSION, "add_columns": [list(c) for c in NEW_COLUMNS], "tables": tables}


def _where(columns) -> str:
    return " AND ".join(f"{c} IS ?" for c in columns)


def apply_table(conn: sqlite3.Connection, name: str, table: dict) -> tuple[dict, list[str]]:
    """Apply one table's changes; return (rows written per kind, conflicts)."""
    columns, key = table["columns"], table["key"]
    key_index = [columns.index(c) for c in key]
    present = set(_columns(conn, name))
    if not present:
        return {}, [f"the database has no {name} table"]
    missing = [c for c in columns if c not in present]
    if missing:
        return {}, [f"{name} lacks columns {missing}"]
    written = {"insert": 0, "delete": 0, "update": 0}
    conflicts = []

    def current(row_key):
        return conn.execute(
            f"SELECT {', '.join(columns)} FROM {name} WHERE {_where(key)}", row_key
        ).fetchall()

    for row in table["delete"]:
        found = current([row[i] for i in key_index])
        if not found:
            continue
        if [list(r) for r in found] != [row]:
            conflicts.append(f"{name} {[row[i] for i in key_index]}: changed since the patch was made")
            continue
        conn.execute(f"DELETE FROM {name} WHERE {_where(columns)}", row)
        written["delete"] += 1
    for row in table["insert"]:
        found = current([row[i] for i in key_index])
        if found:
            if [list(r) for r in found] != [row]:
                conflicts.append(f"{name} {[row[i] for i in key_index]}: exists with other values")
            continue
        conn.execute(
            f"INSERT INTO {name} ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})", row
        )
        written["insert"] += 1
    for change in table["update"]:
        sets = change["set"]
        found = conn.execute(
            f"SELECT {', '.join(sets)} FROM {name} WHERE {_where(key)}", change["key"]
        ).fetchall()
        if len(found) != 1:
            conflicts.append(f"{name} {change['key']}: row missing")
            continue
        values = list(found[0])
        if values == [new for _, new in sets.values()]:
            continue
        if values != [old for old, _ in sets.values()]:
            conflicts.append(f"{name} {change['key']}: {', '.join(sets)} changed since the patch was made")
            continue
        conn.execute(
            f"UPDATE {name} SET {', '.join(f'{c} = ?' for c in sets)} WHERE {_where(key)}",
            [new for _, new in sets.values()] + change["key"],
        )
        written["update"] += 1
    return written, conflicts


def apply_changes(conn: sqlite3.Connection, changes: dict) -> tuple[dict, list[str]]:
    """Apply a patch in one transaction; return (rows written per table, conflicts)."""
    if changes.get("version") != PATCH_VERSION:
        raise SystemExit(f"Unknown patch version {changes.get('version')!r}")
    if not conn.in_transaction:
        conn.execute("BEGIN")  # so that ALTER TABLE rolls back with the rest
    for table, column, kind in changes["add_columns"]:
        if column not in _columns(conn, table):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
    written = {}
    conflicts = []
    for name, table in changes["tables"].items():
        written[name], table_conflicts = apply_table(conn, name, table)
        conflicts.extend(table_conflicts)
    return written, conflicts


def summary(changes: dict) -> str:
    parts = []
    for name, table in changes["tables"].items():
        counts = [f"{len(table[kind])} {kind}s" for kind in ("insert", "delete", "update") if table[kind]]
        if counts:
            parts.append(f"{name}: {', '.join(counts)}")
    return "; ".join(parts) or "no changes"


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
            changes = compute_changes(conn, args.data_dir)
            if args.write_patch:
                with gzip.open(args.write_patch, "wt", encoding="utf-8") as handle:
                    json.dump(changes, handle, ensure_ascii=False, separators=(",", ":"))

        written, conflicts = apply_changes(conn, changes)
        if conflicts:
            conn.rollback()
            for conflict in conflicts[:20]:
                print(f"ERROR: {conflict}", file=sys.stderr)
            if len(conflicts) > 20:
                print(f"ERROR: ... and {len(conflicts) - 20} more", file=sys.stderr)
            print("Nothing was changed", file=sys.stderr)
            return 1
        conn.commit()
    finally:
        conn.close()

    source = f"the patch {args.apply_patch}" if args.apply_patch else f"the sources in {args.data_dir}"
    print(f"{args.db}, from {source}: {summary(changes)}")
    done = {name: counts for name, counts in written.items() if any(counts.values())}
    if done:
        print("   wrote " + "; ".join(
            f"{name} " + ", ".join(f"{n} {kind}s" for kind, n in counts.items() if n)
            for name, counts in done.items()
        ))
    else:
        print("   the database already held every change")
    if args.write_patch:
        print(f"   patch written to {args.write_patch}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
