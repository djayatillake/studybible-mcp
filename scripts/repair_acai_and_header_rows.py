#!/usr/bin/env python3
"""Re-import the ACAI entities and delete the header rows imported as data.

These importer bugs left an existing database out of line with a fresh build:

- acai_entities: the downloader listed each ACAI directory through GitHub's
  contents API, which stops at 1,000 files, so people ended at Ezra.2 and
  places at Nohah; and the parser missed the files' English label and
  description, so every name was the key ('person:David') and no entity had a
  description.
- verses: TAGNT/TAHOT column headers ("Word & Type", "Eng (Heb) Ref & Type")
  and the "Types of words" table were imported as verses, each with a
  one-verse passage of its own.
- names: TIPNR notes containing "Name@Ref" ("(?) indicates ... Jahdai@1Ch.2.47",
  "SEPARATED ... Judith@Gen.26.34/...") were imported as people, and place
  records were read with the person columns, so their map links became a
  spouse and children.
- acai_entities had no tipnr_keys, the TIPNR entries each entity is, so
  lookup_name matched by name and gave namesakes each other's data.

The parsers are fixed; this script brings an existing database into line
without rebuilding it. It touches acai_entities (adding tipnr_keys if
missing), those rows, and the relationships of names rows only.

Two modes, both idempotent:

  repair_acai_and_header_rows.py DB [--data-dir data] [--write-patch PATCH]
      Re-parse data/acai/ and TIPNR.txt, replace acai_entities with the parsed
      entities, delete the header rows and correct the names relationships.
      --write-patch also saves the changes, so a copy of the same database
      elsewhere (the Fly volume) can be repaired without the sources.

  repair_acai_and_header_rows.py DB --apply-patch PATCH
      Apply a saved patch. Needs only the standard library, so it runs on the
      server from a copy of this script.

acai_entities is replaced only while it holds exactly the rows the patch was
made from (when it already holds the new rows there is nothing to do), and a
row is deleted or updated only while it still holds what the patch expects;
otherwise nothing is changed, the added column included. The deleted rows'
embeddings in verse_vectors and passage_vectors (sqlite-vec tables, which
need the extension to edit) are left: every vector query joins verses or
passages, so they are never returned, and the ids are AUTOINCREMENT, so they
are never reused.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ACAI_TYPES = ("people", "places", "groups", "keyterms")
ACAI_COLUMNS = (
    "id", "entity_type", "name", "gender", "description", "roles",
    "father_id", "mother_id", "partners", "offspring", "siblings",
    "referred_to_as", "key_references", "reference_count", "speeches_count", "tipnr_keys",
)
# Rows to delete, by table: the columns a row must still hold to be deleted.
DELETE_KEYS = {
    "verses": ("id", "reference"),
    "passages": ("id", "reference_start", "reference_end", "start_verse_id", "end_verse_id"),
    "names": ("id", "name"),
}
NAMES_COLUMNS = ("name", "name_original", "type", "description", "refs", "relationships")
GITHUB_LISTING_CAP = 1000


def digest(rows: list[list]) -> str:
    """A fingerprint of acai_entities rows, independent of their order."""
    canonical = json.dumps(sorted(rows, key=lambda row: row[0]), ensure_ascii=False,
                           separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def acai_columns(conn: sqlite3.Connection) -> tuple[str, ...]:
    """The table's columns: ACAI_COLUMNS, or all but tipnr_keys before this repair."""
    columns = tuple(row[1] for row in conn.execute("PRAGMA table_info(acai_entities)"))
    if columns not in (ACAI_COLUMNS, ACAI_COLUMNS[:-1]):
        raise SystemExit(f"acai_entities has columns {list(columns)}, expected {list(ACAI_COLUMNS)}")
    return columns


def stored_acai_rows(conn: sqlite3.Connection) -> list[list]:
    columns = ", ".join(acai_columns(conn))
    return [list(row) for row in conn.execute(f"SELECT {columns} FROM acai_entities")]


def parse_acai(acai_dir: Path) -> list[list]:
    """The rows a fresh build imports, in its order (a later duplicate id wins),
    with the curated corrections of graph_curated.json applied."""
    from study_bible_mcp.parsers.acai import apply_acai_corrections, parse_acai_dir
    from study_bible_mcp.parsers.theographic import load_curated

    for entity_type in ACAI_TYPES:
        if len(list((acai_dir / entity_type).glob("*.json"))) == GITHUB_LISTING_CAP:
            print(
                f"WARNING: {acai_dir / entity_type} has exactly {GITHUB_LISTING_CAP} files, the old "
                "downloader's cap; run scripts/download_stepbible.py --aquifer to fetch the rest",
                file=sys.stderr,
            )
    entities = apply_acai_corrections(parse_acai_dir(acai_dir), load_curated()["acai"])
    return [[entity.get(column) for column in ACAI_COLUMNS] for entity in entities.values()]


def names_changes(conn: sqlite3.Connection, tipnr: Path) -> tuple[list[list], list[list]]:
    """Names rows the TIPNR parser no longer yields, as [id, name], and rows whose
    relationships it now reads differently, as [id, name, old, new]."""
    from study_bible_mcp.parsers.proper_names import apply_tipnr_corrections, parse_tipnr
    from study_bible_mcp.parsers.theographic import load_curated

    expected: dict[tuple, list[str]] = defaultdict(list)
    # As build_database.py imports them, curated corrections included
    for e in apply_tipnr_corrections(parse_tipnr(tipnr), load_curated()["tipnr"]):
        key = (e["name"], e["name_original"], e["type"], e["description"], e["references"])
        expected[key].append(e["relationships"])
    junk = []
    updates = []
    for row_id, *entry, relationships in conn.execute(
        f"SELECT id, {', '.join(NAMES_COLUMNS)} FROM names ORDER BY id"
    ):
        parsed = expected.get(tuple(entry))
        if not parsed:
            junk.append([row_id, entry[0]])
        elif (new := parsed.pop(0)) != relationships:
            updates.append([row_id, entry[0], relationships, new])
    missing = sum(len(rest) for rest in expected.values())
    if missing:
        raise SystemExit(
            f"{missing} TIPNR entries are not in the names table, so it was not built from "
            f"{tipnr}; nothing was changed"
        )
    return junk, updates


def compute_changes(conn: sqlite3.Connection, data_dir: Path) -> dict:
    """The patch that brings this database into line with the sources in data_dir."""
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
    from study_bible_mcp.parsers.tagged_text import VERSE_REFERENCE

    tipnr = data_dir / "TIPNR.txt"
    if not tipnr.exists():
        raise SystemExit(f"Missing TIPNR source file: {tipnr}")
    new_rows = parse_acai(data_dir / "acai")
    if not new_rows:
        raise SystemExit(f"No ACAI entity files under {data_dir / 'acai'}")

    old_rows = stored_acai_rows(conn)
    dropped = {row[0] for row in old_rows} - {row[0] for row in new_rows}
    if dropped:
        raise SystemExit(
            f"The ACAI source lacks {len(dropped)} entities the database has "
            f"(first: {', '.join(sorted(dropped)[:5])}); nothing was changed"
        )

    verses = [
        [verse_id, reference]
        for verse_id, reference in conn.execute("SELECT id, reference FROM verses ORDER BY id")
        if not VERSE_REFERENCE.match(reference)
    ]
    verse_ids = [verse_id for verse_id, _ in verses]
    placeholders = ", ".join("?" for _ in verse_ids)
    passages = [
        list(row)
        for row in conn.execute(
            f"SELECT {', '.join(DELETE_KEYS['passages'])} FROM passages "
            f"WHERE start_verse_id IN ({placeholders}) OR end_verse_id IN ({placeholders}) "
            "ORDER BY id",
            (*verse_ids, *verse_ids),
        )
    ]
    spanning = [row[0] for row in passages if row[3] != row[4]]
    if spanning:
        raise SystemExit(
            f"Passages {spanning} include real verses as well as header rows; nothing was changed"
        )

    junk_names, relationships = names_changes(conn, tipnr)
    return {
        "acai_entities": {
            "columns": list(ACAI_COLUMNS),
            "before": digest(old_rows),
            "after": digest(new_rows),
            "rows": new_rows,
        },
        "verses": verses,
        "passages": passages,
        "names": junk_names,
        "names_relationships": relationships,
    }


def replace_acai(conn: sqlite3.Connection, acai: dict) -> int | None:
    """Install the patch's entities; return rows written, or None if the table differs."""
    if tuple(acai["columns"]) != ACAI_COLUMNS:
        raise SystemExit(f"The patch has ACAI columns {acai['columns']}, expected {list(ACAI_COLUMNS)}")
    current = digest(stored_acai_rows(conn))
    if current == acai["after"]:
        return 0
    if current != acai["before"]:
        return None
    if "tipnr_keys" not in acai_columns(conn):
        conn.execute("ALTER TABLE acai_entities ADD COLUMN tipnr_keys TEXT")
    conn.execute("DELETE FROM acai_entities")
    conn.executemany(
        f"INSERT INTO acai_entities ({', '.join(ACAI_COLUMNS)}) "
        f"VALUES ({', '.join('?' for _ in ACAI_COLUMNS)})",
        acai["rows"],
    )
    if digest(stored_acai_rows(conn)) != acai["after"]:
        return None
    return len(acai["rows"])


def delete_rows(conn: sqlite3.Connection, table: str, rows: list[list]) -> tuple[int, list]:
    """Delete rows still holding the expected values; return (deleted, conflicting ids)."""
    columns = DELETE_KEYS[table]
    deleted = 0
    conflicts = []
    for expected in rows:
        current = conn.execute(
            f"SELECT {', '.join(columns)} FROM {table} WHERE id = ?", (expected[0],)
        ).fetchone()
        if current is None:
            continue
        if list(current) != list(expected):
            conflicts.append(expected[0])
            continue
        conn.execute(f"DELETE FROM {table} WHERE id = ?", (expected[0],))
        deleted += 1
    return deleted, conflicts


def update_relationships(conn: sqlite3.Connection, rows: list[list]) -> tuple[int, list]:
    """Set names relationships where they still hold the old value; return (updated, conflicts)."""
    updated = 0
    conflicts = []
    for row_id, name, old, new in rows:
        current = conn.execute(
            "SELECT name, relationships FROM names WHERE id = ?", (row_id,)
        ).fetchone()
        if current == (name, new):
            continue
        if current != (name, old):
            conflicts.append(row_id)
            continue
        conn.execute("UPDATE names SET relationships = ? WHERE id = ?", (new, row_id))
        updated += 1
    return updated, conflicts


def apply_changes(conn: sqlite3.Connection, changes: dict) -> tuple[dict, list[str]]:
    """Apply a patch in one transaction; return (rows written per table, conflicts)."""
    if not conn.in_transaction:
        conn.execute("BEGIN")  # so that ALTER TABLE rolls back with the rest
    written = {}
    conflicts = []
    acai = replace_acai(conn, changes["acai_entities"])
    if acai is None:
        conflicts.append("acai_entities holds neither the rows the patch replaces nor its rows")
    written["acai_entities"] = acai or 0
    for table in DELETE_KEYS:
        deleted, conflicting = delete_rows(conn, table, changes[table])
        written[table] = deleted
        if conflicting:
            conflicts.append(
                f"{len(conflicting)} {table} rows no longer hold the expected values "
                f"(first ids: {', '.join(map(str, conflicting[:5]))})"
            )
    updated, conflicting = update_relationships(conn, changes["names_relationships"])
    written["names_relationships"] = updated
    if conflicting:
        conflicts.append(
            f"{len(conflicting)} names rows no longer hold the expected relationships "
            f"(first ids: {', '.join(map(str, conflicting[:5]))})"
        )
    return written, conflicts


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
            for conflict in conflicts:
                print(f"ERROR: {conflict}", file=sys.stderr)
            print("Nothing was changed", file=sys.stderr)
            return 1
        conn.commit()
    finally:
        conn.close()

    source = f"the patch {args.apply_patch}" if args.apply_patch else f"the sources in {args.data_dir}"
    rows = changes["acai_entities"]["rows"]
    by_type = Counter(row[1] for row in rows)
    print(
        f"{args.db}, from {source}: {len(rows)} ACAI entities "
        f"({', '.join(f'{count} {kind}' for kind, count in sorted(by_type.items()))}), "
        f"{sum(len(changes[table]) for table in DELETE_KEYS)} header rows to delete and "
        f"{len(changes['names_relationships'])} names relationships to correct"
    )
    if written["acai_entities"]:
        print(f"   replaced acai_entities with {written['acai_entities']} rows")
    else:
        print("   acai_entities already held them")
    print(
        "   deleted "
        + ", ".join(f"{written[table]} of {len(changes[table])} {table} rows" for table in DELETE_KEYS)
        + "; the rest were already gone"
    )
    print(
        f"   corrected the relationships of {written['names_relationships']} of "
        f"{len(changes['names_relationships'])} names rows; the rest already held them"
    )
    if args.write_patch:
        print(f"   patch written to {args.write_patch}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
