#!/usr/bin/env python3
"""Bring an existing database's lexicon and morphology tables into line with the importers.

Lexicon (brief definitions and the Greek sense rows):
- Hebrew brief definitions were the first bold phrase of each BDB entry,
  often a grammar label ("noun masculine plural" for elohim, "verb Pi`el" for
  kaphar, "proper name, masculine" for 1,227 names) or the wrong homonym
  ("mouth" for midbar). They become STEPBible's TBESH glosses, most-used
  sense first ("wilderness; mouth"), and the Hebrew pronunciation becomes
  STEPBible's transliteration ("che.sed"), which search_lexicon matches.
- Greek entries with several TFLSJ rows kept the last row: G2570 kalos was
  "Fair (Havens)", G4074 Peter "[mother-in-law of Peter]" with the word
  "[unnamed]", G2424 Jesus carried the Joses article. They take the main row's
  word and definition, and the combined glosses ("good"; "Peter").
  See study_bible_mcp.lexicon_glosses. usage_count is not touched.

Morphology (study_bible_mcp.parsers.tagged_text.parse_morphology_codes):
- the columns come from each expansion's Key=Value fields, so V-2ADS-3S's
  voice is "Middle Deponent" (not "Active") and Hebrew codes have a part of
  speech (not "H"); brief codes ("H:N-M", "Ps1c") keep their meaning, and
  TEGMC's closing "KJV" list no longer overwrites 13 Greek expansions.

Two modes, both idempotent:

  repair_lexicon_and_morphology.py DB [--data-dir data] [--write-patch PATCH]
      Read the STEPBible files in data/ (TBESH, TBESG, TFLSJ, DictBDB.json,
      TEGMC, TEHMC) and update the changed rows in place. --write-patch also
      saves the changes for another copy of the same database (the Fly
      volume), which has no data/ directory.

  repair_lexicon_and_morphology.py DB --apply-patch PATCH
      Apply a saved patch. Needs only the standard library, so it runs on the
      server from a copy of this script.

A value is changed only while it still holds what the patch expects to
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

LEXICON_COLUMNS = (
    "word", "transliteration", "pronunciation", "short_definition", "full_definition",
)
MORPHOLOGY_COLUMNS = (
    "parsing", "part_of_speech", "person", "number", "tense", "voice", "mood",
    "case_value", "gender",
)


def _lexicon_changes(conn: sqlite3.Connection, data_dir: Path) -> dict:
    """{strongs: {column: [old, new]}} for lexicon rows that differ from a fresh import."""
    from study_bible_mcp.lexicon_glosses import compute_brief_definitions
    from study_bible_mcp.parsers.lexicon import parse_bdb_lexicon, parse_tflsj_lexicon

    wanted: dict[str, dict] = {}
    tflsj = [data_dir / "TFLSJ_0-5624.txt", data_dir / "TFLSJ_extra.txt"]
    for path in tflsj:
        if path.exists():
            for entry in parse_tflsj_lexicon(path):
                wanted[entry["strongs"]] = {
                    column: entry[column]
                    for column in ("word", "transliteration", "pronunciation", "full_definition")
                }
    bdb = data_dir / "DictBDB.json"
    if bdb.exists():
        for entry in parse_bdb_lexicon(bdb):
            wanted.setdefault(entry["strongs"], {})["short_definition"] = entry["short_definition"]
    for strongs, values in compute_brief_definitions(conn, data_dir).items():
        wanted.setdefault(strongs, {}).update(values)

    changes: dict[str, dict] = {}
    columns = ", ".join(LEXICON_COLUMNS)
    for row in conn.execute(f"SELECT strongs, {columns} FROM lexicon"):
        strongs, current = row[0], dict(zip(LEXICON_COLUMNS, row[1:]))
        diff = {
            column: [current[column], value]
            for column, value in wanted.get(strongs, {}).items()
            if current[column] != value
        }
        if diff:
            changes[strongs] = diff
    return changes


def _morphology_key(code: str, language: str) -> str:
    return f"{language}\t{code}"


def _morphology_changes(conn: sqlite3.Connection, data_dir: Path) -> dict:
    """{"update": {key: {column: [old, new]}}, "insert": {key: row}, "delete": {key: row}}."""
    from study_bible_mcp.parsers.tagged_text import parse_morphology_codes

    wanted: dict[str, dict] = {}
    for name, language in (("TEGMC.txt", "greek"), ("TEHMC.txt", "hebrew")):
        path = data_dir / name
        if not path.exists():
            raise SystemExit(f"No {path}; run scripts/download_stepbible.py first")
        for entry in parse_morphology_codes(path, language):
            wanted[_morphology_key(entry["code"], language)] = {
                column: entry.get(column, "") for column in MORPHOLOGY_COLUMNS
            }
    current = _current_morphology(conn)
    return {
        "update": {
            key: {
                column: [current[key][column], value]
                for column, value in row.items()
                if current[key][column] != value
            }
            for key, row in wanted.items()
            if key in current and current[key] != row
        },
        "insert": {key: row for key, row in wanted.items() if key not in current},
        "delete": {key: row for key, row in current.items() if key not in wanted},
    }


def _current_morphology(conn: sqlite3.Connection) -> dict[str, dict]:
    columns = ", ".join(MORPHOLOGY_COLUMNS)
    return {
        _morphology_key(row[0], row[1]): dict(zip(MORPHOLOGY_COLUMNS, row[2:]))
        for row in conn.execute(f"SELECT code, language, {columns} FROM morphology")
    }


def compute_changes(conn: sqlite3.Connection, data_dir: Path) -> dict:
    """Everything a fresh import would set differently, as old/new pairs."""
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
    for name in ("TBESH.txt", "DictBDB.json"):
        if not (data_dir / name).exists():
            raise SystemExit(f"No {data_dir / name}; run scripts/download_stepbible.py first")
    return {
        "lexicon": _lexicon_changes(conn, data_dir),
        "morphology": _morphology_changes(conn, data_dir),
    }


def apply_changes(conn: sqlite3.Connection, changes: dict) -> tuple[dict[str, int], list[str]]:
    """Apply changes in one transaction; return (counts applied, conflicting keys)."""
    applied = {"lexicon": 0, "morphology update": 0, "morphology insert": 0, "morphology delete": 0}
    conflicts: list[str] = []

    columns = ", ".join(LEXICON_COLUMNS)
    lexicon = {
        row[0]: dict(zip(LEXICON_COLUMNS, row[1:]))
        for row in conn.execute(f"SELECT strongs, {columns} FROM lexicon")
    }
    for strongs, diff in changes["lexicon"].items():
        current = lexicon.get(strongs)
        if current is None or any(
            current[column] not in (old, new) for column, (old, new) in diff.items()
        ):
            conflicts.append(strongs)
            continue
        todo = {column: new for column, (old, new) in diff.items() if current[column] != new}
        if todo:
            assignments = ", ".join(f"{column} = ?" for column in todo)
            conn.execute(
                f"UPDATE lexicon SET {assignments} WHERE strongs = ?", (*todo.values(), strongs)
            )
            applied["lexicon"] += 1

    morphology = changes["morphology"]
    current = _current_morphology(conn)
    for key, diff in morphology["update"].items():
        row = current.get(key)
        if row is None or any(row[column] not in (old, new) for column, (old, new) in diff.items()):
            conflicts.append(key)
            continue
        todo = {column: new for column, (old, new) in diff.items() if row[column] != new}
        if todo:
            language, code = key.split("\t", 1)
            assignments = ", ".join(f"{column} = ?" for column in todo)
            conn.execute(
                f"UPDATE morphology SET {assignments} WHERE code = ? AND language = ?",
                (*todo.values(), code, language),
            )
            applied["morphology update"] += 1
    for key, row in morphology["insert"].items():
        if key in current:
            if current[key] != row:
                conflicts.append(key)
            continue
        language, code = key.split("\t", 1)
        conn.execute(
            f"INSERT INTO morphology (code, language, {', '.join(MORPHOLOGY_COLUMNS)}) "
            f"VALUES (?, ?, {', '.join('?' * len(MORPHOLOGY_COLUMNS))})",
            (code, language, *(row[column] for column in MORPHOLOGY_COLUMNS)),
        )
        applied["morphology insert"] += 1
    for key, row in morphology["delete"].items():
        if key not in current:
            continue
        if current[key] != row:
            conflicts.append(key)
            continue
        language, code = key.split("\t", 1)
        conn.execute("DELETE FROM morphology WHERE code = ? AND language = ?", (code, language))
        applied["morphology delete"] += 1
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
            source = f"the STEPBible files in {args.data_dir}"
            if args.write_patch:
                with gzip.open(args.write_patch, "wt", encoding="utf-8") as handle:
                    json.dump(changes, handle, ensure_ascii=False, separators=(",", ":"))

        applied, conflicts = apply_changes(conn, changes)
        if conflicts:
            conn.rollback()
            print(
                f"ERROR: {len(conflicts)} rows hold neither the old nor the new values "
                f"(first: {', '.join(conflicts[:5])}); nothing was changed",
                file=sys.stderr,
            )
            return 1
        conn.commit()
    finally:
        conn.close()

    morphology = changes["morphology"]
    print(
        f"{args.db}: {source} has {len(changes['lexicon'])} lexicon rows to update; "
        f"morphology {len(morphology['update'])} to update, {len(morphology['insert'])} to insert, "
        f"{len(morphology['delete'])} to delete"
    )
    print("   " + ", ".join(f"{count} {kind}" for kind, count in applied.items())
          + " applied; the rest already matched")
    if args.write_patch:
        print(f"   patch written to {args.write_patch}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
