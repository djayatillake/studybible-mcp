#!/usr/bin/env python3
"""Repair the Strong's numbers of Hebrew words in verses.word_data.

STEPBible's TAHOT tags a word with prefixes as, e.g., H9003/{H7225G}
(בְּ/רֵאשִׁ֖ית, "in/ beginning"): the braces mark the root. The importer used to
keep the first number, so 116,321 of 305,638 Hebrew words were stored under
their prefix (H9003 "in", H9001 "and", H9009 "the") instead of their root, and
search_by_strongs and word_study never found them. The parser now keeps the
braced root; this script brings an existing database into line with a fresh
build without rebuilding it.

Two modes, both idempotent:

  repair_hebrew_word_strongs.py DB [--data-dir data] [--write-patch PATCH]
      Re-parse the TAHOT files and rewrite each changed word's "strongs" in
      place. --write-patch also saves the changes, so a copy of the same
      database elsewhere (the Fly volume) can be repaired without the sources.

  repair_hebrew_word_strongs.py DB --apply-patch PATCH
      Apply a saved patch. Needs only the standard library, so it runs on the
      server from a copy of this script.

A word is rewritten only where it still holds the number the patch expects to
replace; a verse whose words do not line up with the source is skipped and
reported, never guessed at.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from study_bible_mcp.database import build_strongs_index, table_exists

TAHOT_FILES = ("TAHOT_Gen-Deu.txt", "TAHOT_Jos-Est.txt", "TAHOT_Job-Sng.txt", "TAHOT_Isa-Mal.txt")


def compute_changes(conn: sqlite3.Connection, data_dir: Path) -> tuple[dict, list[str]]:
    """Return ({reference: {word_index: [old, new]}}, misaligned references)."""
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
    from study_bible_mcp.parsers.tagged_text import parse_tahot

    files = [data_dir / name for name in TAHOT_FILES]
    missing = [str(path) for path in files if not path.exists()]
    if missing:
        raise SystemExit(f"Missing TAHOT source files: {', '.join(missing)}")

    changes: dict[str, dict[str, list[str]]] = {}
    misaligned: list[str] = []
    for path in files:
        for verse in parse_tahot(path):
            row = conn.execute(
                "SELECT word_data FROM verses WHERE reference = ?", (verse["reference"],)
            ).fetchone()
            if row is None or not row[0]:
                continue
            stored = json.loads(row[0])
            parsed = json.loads(verse["word_data"])
            if [w.get("word") for w in stored] != [w.get("word") for w in parsed]:
                misaligned.append(verse["reference"])
                continue
            changed = {
                str(index): [old.get("strongs", ""), new["strongs"]]
                for index, (old, new) in enumerate(zip(stored, parsed))
                if old.get("strongs", "") != new["strongs"]
            }
            if changed:
                changes[verse["reference"]] = changed
    return changes, misaligned


def apply_changes(conn: sqlite3.Connection, changes: dict) -> tuple[int, int, list[str]]:
    """Apply changes; return (verses updated, words updated, conflicting references)."""
    verses_updated = words_updated = 0
    conflicts: list[str] = []
    for reference, changed in changes.items():
        row = conn.execute(
            "SELECT word_data FROM verses WHERE reference = ?", (reference,)
        ).fetchone()
        if row is None or not row[0]:
            conflicts.append(reference)
            continue
        words = json.loads(row[0])
        pending = []
        for index, (old, new) in changed.items():
            position = int(index)
            current = words[position].get("strongs", "") if position < len(words) else None
            if current == new:
                continue
            if current != old:
                pending = None
                break
            pending.append((position, new))
        if pending is None:
            conflicts.append(reference)
            continue
        if not pending:
            continue
        for position, new in pending:
            words[position]["strongs"] = new
        conn.execute(
            "UPDATE verses SET word_data = ? WHERE reference = ?",
            (json.dumps(words, ensure_ascii=False), reference),
        )
        verses_updated += 1
        words_updated += len(pending)
    return verses_updated, words_updated, conflicts


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
            misaligned: list[str] = []
        else:
            changes, misaligned = compute_changes(conn, args.data_dir)
            if args.write_patch:
                with gzip.open(args.write_patch, "wt", encoding="utf-8") as handle:
                    json.dump(changes, handle, ensure_ascii=False, separators=(",", ":"))

        verses, words, conflicts = apply_changes(conn, changes)
        if conflicts:
            conn.rollback()
            print(
                f"ERROR: {len(conflicts)} verses no longer match the expected word data "
                f"(first: {', '.join(conflicts[:5])}); nothing was changed",
                file=sys.stderr,
            )
            return 1
        if verses and table_exists(conn, "verse_strongs"):
            build_strongs_index(conn)
        conn.commit()
    finally:
        conn.close()

    total = sum(len(changed) for changed in changes.values())
    source = f"the patch {args.apply_patch}" if args.apply_patch else "the TAHOT source"
    print(f"{args.db}: {source} corrects {total} Hebrew words in {len(changes)} verses")
    print(f"   updated {words} words in {verses} verses; the rest already matched")
    if misaligned:
        print(
            f"   skipped {len(misaligned)} verses whose words do not line up with the source "
            f"(first: {', '.join(misaligned[:5])})"
        )
    if args.write_patch:
        print(f"   patch written to {args.write_patch}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
