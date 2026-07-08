#!/usr/bin/env python3
"""
Ingest the Reformed-evangelical author corpus (Owen, Stott, Lennox) into the
study-bible theology tables.

Sources (all verse-anchored study-note cells authored as original summaries):
  data/owen/content/*.json     -- John Owen  (public domain)
  data/stott/content/*.json    -- John Stott (in copyright; summaries only)
  data/lennox/content/*.json   -- John Lennox (in copyright; summaries only)
  data/reformed_evangelical/themes.json   -- shared theme taxonomy

Targets theology_content + theology_verse_index + theology_theme_index, exactly
like scripts/ingest_atonement_synthesis.py. Fully re-runnable: content uses
INSERT OR IGNORE keyed on UNIQUE(source_work, chapter_or_episode, title); themes
use INSERT OR REPLACE; verse/theme index rows use INSERT OR IGNORE.

Does NOT deploy. After a clean local run, deploy to Fly separately (deploy-db).
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from study_bible_mcp.parsers.heiser import parse_themes_file, parse_heiser_content_file

DB_PATH = ROOT / "db" / "study_bible.db"
THEMES_FILE = ROOT / "data" / "reformed_evangelical" / "themes.json"
CONTENT_DIRS = [
    ROOT / "data" / "owen" / "content",
    ROOT / "data" / "stott" / "content",
    ROOT / "data" / "lennox" / "content",
]


def import_themes(conn: sqlite3.Connection) -> int:
    if not THEMES_FILE.exists():
        print(f"  [themes] {THEMES_FILE} not found -- skipping theme taxonomy load")
        return 0
    n = 0
    for theme in parse_themes_file(THEMES_FILE):
        conn.execute(
            """INSERT OR REPLACE INTO theology_themes
               (theme_key, theme_label, description, parent_theme, key_works)
               VALUES (?, ?, ?, ?, ?)""",
            (theme["theme_key"], theme["theme_label"], theme["description"],
             theme["parent_theme"], theme["key_works"]),
        )
        n += 1
    print(f"  [themes] {n} theme rows upserted")
    return n


def import_content(conn: sqlite3.Connection) -> None:
    n_entries = n_refs = n_themes = n_files = 0
    missing_themes: set[str] = set()
    known_themes = {r[0] for r in conn.execute("SELECT theme_key FROM theology_themes")}

    for content_dir in CONTENT_DIRS:
        if not content_dir.exists():
            print(f"  [content] {content_dir} not found -- skipping")
            continue
        for filepath in sorted(content_dir.glob("*.json")):
            n_files += 1
            for content_entry, verse_refs, theme_keys in parse_heiser_content_file(filepath):
                cursor = conn.execute(
                    """INSERT OR IGNORE INTO theology_content
                       (source_work, source_author, source_type, chapter_or_episode,
                        title, content_summary, content_detail, page_range, url)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (content_entry["source_work"], content_entry["source_author"],
                     content_entry["source_type"], content_entry["chapter_or_episode"],
                     content_entry["title"], content_entry["content_summary"],
                     content_entry["content_detail"], content_entry["page_range"],
                     content_entry["url"]),
                )
                if cursor.rowcount == 0:
                    row = conn.execute(
                        """SELECT id FROM theology_content
                           WHERE source_work = ? AND chapter_or_episode IS ? AND title = ?""",
                        (content_entry["source_work"], content_entry["chapter_or_episode"],
                         content_entry["title"]),
                    ).fetchone()
                    content_id = row[0] if row else None
                else:
                    content_id = cursor.lastrowid
                    n_entries += 1
                if content_id is None:
                    continue
                for vref in verse_refs:
                    conn.execute(
                        """INSERT OR IGNORE INTO theology_verse_index
                           (content_id, reference, book, chapter, verse, relevance)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (content_id, vref["reference"], vref["book"],
                         vref["chapter"], vref["verse"], vref["relevance"]),
                    )
                    n_refs += 1
                for theme_key in theme_keys:
                    if theme_key not in known_themes:
                        missing_themes.add(theme_key)
                    conn.execute(
                        """INSERT OR IGNORE INTO theology_theme_index
                           (theme_key, content_id, reference) VALUES (?, ?, NULL)""",
                        (theme_key, content_id),
                    )
                    n_themes += 1

    print(f"  [content] {n_files} files, {n_entries} new content entries, "
          f"{n_refs} verse refs, {n_themes} theme links")
    if missing_themes:
        print("  [WARN] theme keys used by cells but absent from theology_themes:")
        for k in sorted(missing_themes):
            print(f"           - {k}")
        print("         (add them to themes.json; theme_index rows still inserted)")


def main() -> None:
    if not DB_PATH.exists():
        print(f"Database not found at {DB_PATH}")
        sys.exit(1)
    print("=" * 60)
    print("Ingesting Reformed-evangelical corpus (Owen / Stott / Lennox)")
    print("=" * 60)
    conn = sqlite3.connect(str(DB_PATH))
    import_themes(conn)
    import_content(conn)
    conn.commit()

    print("\nVerification:")
    for r in conn.execute(
        "SELECT source_author, COUNT(*) FROM theology_content GROUP BY source_author ORDER BY source_author"
    ):
        print(f"  author {r[0]:<10} {r[1]} cells")
    for author in ("owen", "stott", "lennox"):
        works = conn.execute(
            "SELECT DISTINCT source_work FROM theology_content WHERE source_author = ? ORDER BY source_work",
            (author,),
        ).fetchall()
        if works:
            print(f"  {author} works: " + ", ".join(w[0] for w in works))
    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
