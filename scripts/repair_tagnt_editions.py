#!/usr/bin/env python3
"""Mark New Testament words that are not in the NA28 text, in an existing database.

TAGNT tags every word with the kinds of Greek edition that have it; about
4,450 words in 2,088 verses are missing from NA27/28, the text the BSB
translates (the "and fasting" of Mark 9:29 and 1 Cor 7:5 is only in
Tyn+Treg+TR+Byz). The importer dropped that marker, so search_by_strongs
listed those verses as if the BSB text shown had the word. The importer now
keeps it as "editions": "Tyn+Treg+TR+Byz" on such words in verses.word_data
(study_bible_mcp.parsers.tagged_text.parse_greek_word), and search_by_strongs
notes the verse. This script adds the same key to an existing database.

Two modes, both idempotent:

  repair_tagnt_editions.py DB [--data-dir data] [--write-patch PATCH]
      Read the TAGNT files in data/ and update the affected verses in place.
      --write-patch also saves the changes for another copy of the same
      database (the Fly volume), which has no data/ directory.

  repair_tagnt_editions.py DB --apply-patch PATCH
      Apply a saved patch. Needs only the standard library, so it runs on the
      server from a copy of this script.

A verse is changed only while its word_data is exactly what the patch was
made from (checked by SHA-256), and the result must match the patch's
SHA-256; anything else rolls back the whole run, so nothing is changed.
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


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _with_editions(word_data: str, additions: list[list]) -> str:
    """word_data with 'editions' set on the words at the given positions."""
    words = json.loads(word_data)
    for index, editions in additions:
        words[index]["editions"] = editions
    return json.dumps(words, ensure_ascii=False)


def compute_changes(conn: sqlite3.Connection, data_dir: Path) -> dict:
    """{reference: {"old": sha, "new": sha, "add": [[word index, editions], ...]}}."""
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
    from study_bible_mcp.parsers.tagged_text import parse_tagnt

    paths = sorted(data_dir.glob("TAGNT*.txt"))
    if not paths:
        raise SystemExit(f"No TAGNT files in {data_dir}; run scripts/download_stepbible.py first")
    changes: dict[str, dict] = {}
    mismatched: list[str] = []
    for path in paths:
        for verse in parse_tagnt(path):
            fresh = json.loads(verse["word_data"])
            additions = [
                [index, word["editions"]] for index, word in enumerate(fresh) if "editions" in word
            ]
            if not additions:
                continue
            row = conn.execute(
                "SELECT word_data FROM verses WHERE reference = ?", (verse["reference"],)
            ).fetchone()
            unmarked = [{k: v for k, v in word.items() if k != "editions"} for word in fresh]
            if row is None or [
                {k: v for k, v in word.items() if k != "editions"} for word in json.loads(row[0])
            ] != unmarked:
                mismatched.append(verse["reference"])
                continue
            changes[verse["reference"]] = {
                "old": _sha(json.dumps(unmarked, ensure_ascii=False)),
                "new": _sha(verse["word_data"]),
                "add": additions,
            }
    if mismatched:
        raise SystemExit(
            f"{len(mismatched)} verses differ from TAGNT in more than the edition markers "
            f"(first: {', '.join(mismatched[:5])}); nothing was changed"
        )
    return changes


def apply_changes(conn: sqlite3.Connection, changes: dict) -> tuple[int, list[str]]:
    """Apply changes in one transaction; return (verses updated, conflicting references)."""
    applied = 0
    conflicts: list[str] = []
    for reference, change in changes.items():
        rows = conn.execute(
            "SELECT id, word_data FROM verses WHERE reference = ?", (reference,)
        ).fetchall()
        if len(rows) != 1:
            conflicts.append(reference)
            continue
        verse_id, current = rows[0]
        digest = _sha(current)
        if digest == change["new"]:
            continue
        if digest != change["old"]:
            conflicts.append(reference)
            continue
        updated = _with_editions(current, change["add"])
        if _sha(updated) != change["new"]:
            conflicts.append(reference)
            continue
        conn.execute("UPDATE verses SET word_data = ? WHERE id = ?", (updated, verse_id))
        applied += 1
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
            source = f"the TAGNT files in {args.data_dir}"
            if args.write_patch:
                with gzip.open(args.write_patch, "wt", encoding="utf-8") as handle:
                    json.dump(changes, handle, ensure_ascii=False, separators=(",", ":"))

        applied, conflicts = apply_changes(conn, changes)
        if conflicts:
            conn.rollback()
            print(
                f"ERROR: {len(conflicts)} verses hold neither the expected nor the marked "
                f"word data (first: {', '.join(conflicts[:5])}); nothing was changed",
                file=sys.stderr,
            )
            return 1
        conn.commit()
    finally:
        conn.close()

    words = sum(len(change["add"]) for change in changes.values())
    print(f"{args.db}: {source} marks {words} words in {len(changes)} verses")
    print(f"   {applied} verses updated; the rest already matched")
    if args.write_patch:
        print(f"   patch written to {args.write_patch}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
