"""Count how often each Strong's number occurs and store it in lexicon.usage_count.

The lexicon sources carry no frequencies, so the importers left usage_count at 0:
search_lexicon could not rank by it and word_study never showed it. The counts
come from the tagged verse text: each word's Strong's number, with STEPBible's
sense suffix dropped (H0430G counts for H0430).

build_database.py runs this after importing verses. For an existing database,
including the deployed one, run it directly (idempotent):

    python -m study_bible_mcp.lexicon_usage /data/study_bible.db
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from collections import Counter

_STRONGS = re.compile(r"([GH])(\d{1,4})[A-Za-z]?")


def count_strongs_usage(conn: sqlite3.Connection) -> Counter:
    """Occurrences of each Strong's number (G0026, H0430) across all verses."""
    counts: Counter = Counter()
    for (word_data,) in conn.execute(
        "SELECT word_data FROM verses WHERE word_data IS NOT NULL AND word_data != ''"
    ):
        try:
            words = json.loads(word_data)
        except ValueError:
            continue
        for word in words:
            match = _STRONGS.fullmatch(word.get("strongs") or "") if isinstance(word, dict) else None
            if match:
                counts[f"{match[1]}{int(match[2]):04d}"] += 1
    return counts


def update_usage_counts(conn: sqlite3.Connection) -> tuple[int, int]:
    """Set every lexicon entry's usage_count; return (entries changed, entries counted)."""
    counts = count_strongs_usage(conn)
    changed = 0
    for strongs, current in conn.execute("SELECT strongs, usage_count FROM lexicon").fetchall():
        count = counts.get(strongs, 0)
        if current != count:
            conn.execute("UPDATE lexicon SET usage_count = ? WHERE strongs = ?", (count, strongs))
            changed += 1
    conn.commit()
    counted = conn.execute("SELECT COUNT(*) FROM lexicon WHERE usage_count > 0").fetchone()[0]
    return changed, counted


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("Usage: python -m study_bible_mcp.lexicon_usage DB_PATH", file=sys.stderr)
        return 2
    conn = sqlite3.connect(argv[0])
    try:
        changed, counted = update_usage_counts(conn)
    finally:
        conn.close()
    print(f"{argv[0]}: updated {changed} lexicon entries; {counted} now have a usage count")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
