#!/usr/bin/env python3
"""Renumber an existing database's cross-references and LXX rows to English versification.

The tools take English (BSB) verse numbers, but the deployed tables were built
from sources numbered otherwise:

* cross_references: the CH set numbers the Old Testament like the Hebrew Bible
  ('Psalm 40:6' held the links of English 40:5, 'Joel 3:1' those of English
  2:28), and TSK swaps Philippians 1:16 and 1:17. The importer now renumbers
  both (study_bible_mcp.parsers.cross_references); here the CH and TSK rows
  that differ from a fresh import are deleted and the missing ones inserted.
* biblical_version_verses: Greek Psalm superscriptions were paired with
  English verse 1 instead of verse 0, and where Brenton numbers verses
  differently from Rahlfs (Sirach 1:1, the Letter of Jeremiah, Proverbs 30)
  his English stood beside the wrong Greek verse. The rows that differ from a
  fresh import (study_bible_mcp.parsers.biblical_versions) are updated in place.

Two modes, both idempotent:

  repair_versification.py DB [--data-dir data] [--write-patch PATCH]
      Read the sources under data/ (cross_references/, lxx/) and the
      database's own verses and bsb_verses tables, and change the rows that
      differ. --write-patch also saves the changes for another copy of the same
      database (the Fly volume), which has no data/ directory.

  repair_versification.py DB --apply-patch PATCH
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

XREF_TYPES = ("ch", "tsk")
# biblical_version_verses columns a fresh import may change.
LXX_COLUMNS = (
    "canonical_reference", "canonical_book", "canonical_chapter", "canonical_verse",
    "canonical_verse_suffix", "translation", "mapping_method",
    "brenton_greek_differs", "brenton_greek", "brenton_greek_difference",
)
# Positions of the columns above, and of the edition and its verse, in the
# tuples parsers.biblical_versions.iter_lxx_rows yields.
_LXX_ROW_FIELDS = (
    "edition", "canonical_reference", "canonical_book", "canonical_chapter", "canonical_verse",
    "canonical_verse_suffix", "edition_reference", "edition_book", "edition_chapter",
    "edition_verse", "edition_verse_suffix", "text", "translation", "morphology",
    "mapping_method", "brenton_greek_differs", "brenton_greek", "brenton_greek_difference",
)


def _lxx_key(edition: str, edition_reference: str, index: int) -> str:
    """A row of biblical_version_verses: its edition verse and its place among that verse's rows."""
    return f"{edition}\t{edition_reference}\t{index}"


def _cross_reference_changes(conn: sqlite3.Connection, data_dir: Path) -> dict:
    from study_bible_mcp.parsers.cross_references import (
        EnglishNumbering,
        parse_ch_xlsx,
        parse_tsk_tsv,
        renumber_pairs,
    )

    ch_path = data_dir / "cross_references" / "CH-CrossReference.xlsx"
    tsk_path = data_dir / "cross_references" / "cross_references.txt"
    for path in (ch_path, tsk_path):
        if not path.exists():
            raise SystemExit(f"No {path}")
    references = [ref for (ref,) in conn.execute("SELECT reference FROM verses ORDER BY id")]
    if not references:
        raise SystemExit("The verses table is empty; it is needed to renumber the CH set")
    numbering = EnglishNumbering(references)
    wanted: dict[tuple[str, str, str], int] = {}
    for kind, pairs in (
        ("ch", renumber_pairs(parse_ch_xlsx(ch_path), numbering.from_hebrew)),
        ("tsk", renumber_pairs(parse_tsk_tsv(tsk_path), lambda ref: ref)),
    ):
        for source, target, relevance in pairs:
            wanted[(source, target, kind)] = relevance

    current: dict[tuple[str, str, str], tuple[int, int]] = {}
    for row_id, source, target, kind, relevance in conn.execute(
        "SELECT id, source, target, type, relevance FROM cross_references "
        f"WHERE type IN ({','.join('?' * len(XREF_TYPES))}) ORDER BY id",
        XREF_TYPES,
    ):
        current[(source, target, kind)] = (row_id, relevance)
    return {
        "delete": {
            str(row_id): [*key, relevance]
            for key, (row_id, relevance) in current.items()
            if wanted.get(key) != relevance
        },
        "insert": [
            [*key, relevance]
            for key, relevance in wanted.items()
            if key not in current or current[key][1] != relevance
        ],
    }


def _lxx_changes(conn: sqlite3.Connection, data_dir: Path) -> dict:
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
    rows = iter_lxx_rows(
        lxx_dir / "morphology",
        load_lxx_pairings(lxx_dir / "verse_pairs.jsonl"),
        parse_brenton_usfm(lxx_dir / "brenton"),
        parse_brenton_usfm(lxx_dir / "brenton-greek"),
        bsb_by_reference(conn),
    )
    wanted: dict[str, dict] = {}
    counts: dict[tuple[str, str], int] = {}
    for values in rows:
        row = dict(zip(_LXX_ROW_FIELDS, values))
        verse = (row["edition"], row["edition_reference"])
        counts[verse] = counts.get(verse, 0) + 1
        wanted[_lxx_key(*verse, counts[verse] - 1)] = {column: row[column] for column in LXX_COLUMNS}

    current = _current_lxx_rows(conn)
    if set(current) != set(wanted):
        raise SystemExit(
            "biblical_version_verses does not hold the rows of these LXX sources "
            f"({len(current)} rows, {len(wanted)} expected); rebuild it with build_database.py"
        )
    update: dict[str, dict[str, list]] = {}
    for key, new in wanted.items():
        old = current[key][1]
        changed = {column: [old[column], new[column]] for column in LXX_COLUMNS if old[column] != new[column]}
        if changed:
            update[key] = changed
    return {"update": update}


def _current_lxx_rows(conn: sqlite3.Connection) -> dict[str, tuple[int, dict]]:
    """Every biblical_version_verses row as {key: (id, {column: value})}."""
    rows: dict[str, tuple[int, dict]] = {}
    counts: dict[tuple[str, str], int] = {}
    for row_id, edition, edition_reference, *values in conn.execute(
        f"SELECT id, edition, edition_reference, {', '.join(LXX_COLUMNS)} "
        "FROM biblical_version_verses ORDER BY id"
    ):
        verse = (edition, edition_reference)
        counts[verse] = counts.get(verse, 0) + 1
        rows[_lxx_key(*verse, counts[verse] - 1)] = (row_id, dict(zip(LXX_COLUMNS, values)))
    return rows


def compute_changes(conn: sqlite3.Connection, data_dir: Path) -> dict:
    """Return {"cross_references": {"delete", "insert"}, "biblical_version_verses": {"update"}}."""
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
    return {
        "cross_references": _cross_reference_changes(conn, data_dir),
        "biblical_version_verses": _lxx_changes(conn, data_dir),
    }


def apply_changes(conn: sqlite3.Connection, changes: dict) -> tuple[dict[str, int], list[str]]:
    """Apply changes in one transaction; return (counts applied, conflicting rows)."""
    applied = {"delete": 0, "insert": 0, "update": 0}
    conflicts: list[str] = []
    xrefs = changes["cross_references"]
    for row_id, old in xrefs["delete"].items():
        row = conn.execute(
            "SELECT source, target, type, relevance FROM cross_references WHERE id = ?", (int(row_id),)
        ).fetchone()
        if row is None:
            continue
        if list(row) != old:
            conflicts.append(f"cross_references id {row_id}")
            continue
        conn.execute("DELETE FROM cross_references WHERE id = ?", (int(row_id),))
        applied["delete"] += 1
    for source, target, kind, relevance in xrefs["insert"]:
        held = conn.execute(
            "SELECT relevance FROM cross_references WHERE source = ? AND target = ? AND type = ?",
            (source, target, kind),
        ).fetchall()
        if held:
            if held != [(relevance,)]:
                conflicts.append(f"cross_references {kind} {source} -> {target}")
            continue
        conn.execute(
            "INSERT INTO cross_references (source, target, type, relevance) VALUES (?, ?, ?, ?)",
            (source, target, kind, relevance),
        )
        applied["insert"] += 1

    updates = changes["biblical_version_verses"]["update"]
    if updates:
        current = _current_lxx_rows(conn)
        for key, columns in updates.items():
            if key not in current:
                conflicts.append(f"biblical_version_verses {key!r}")
                continue
            row_id, held = current[key]
            if all(held[column] == new for column, (_, new) in columns.items()):
                continue
            if any(held[column] != old for column, (old, _) in columns.items()):
                conflicts.append(f"biblical_version_verses {key!r}")
                continue
            assignments = ", ".join(f"{column} = ?" for column in columns)
            conn.execute(
                f"UPDATE biblical_version_verses SET {assignments} WHERE id = ?",
                (*(new for _, new in columns.values()), row_id),
            )
            applied["update"] += 1
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
            source = f"the sources in {args.data_dir}"
            if args.write_patch:
                with gzip.open(args.write_patch, "wt", encoding="utf-8") as handle:
                    json.dump(changes, handle, ensure_ascii=False, separators=(",", ":"))

        applied, conflicts = apply_changes(conn, changes)
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

    xrefs = changes["cross_references"]
    print(f"{args.db}: {source} has")
    print(
        f"   cross_references: {len(xrefs['delete'])} to delete, {len(xrefs['insert'])} to insert "
        f"({applied['delete']} deleted, {applied['insert']} inserted)"
    )
    print(
        f"   biblical_version_verses: {len(changes['biblical_version_verses']['update'])} to update "
        f"({applied['update']} updated)"
    )
    print("   the rest already matched")
    if args.write_patch:
        print(f"   patch written to {args.write_patch}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
