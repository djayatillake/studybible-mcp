#!/usr/bin/env python3
"""Import Bradley theological scholarship content into the unified theology tables.

Re-runnable: rows already present (same source_work, chapter_or_episode, title) are
not duplicated; only their url is refreshed from the data files.

Usage: python scripts/import_bradley_content.py [db_path]
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from study_bible_mcp.database import link_theology_theme, upsert_theology_content
from study_bible_mcp.parsers.heiser import parse_heiser_content_file, parse_themes_file


def get_db_path() -> Path:
    if len(sys.argv) > 1:
        return Path(sys.argv[1])
    return Path(__file__).resolve().parent.parent / "db" / "study_bible.db"


def main():
    db_path = get_db_path()
    if not db_path.exists():
        print(f"Database not found at {db_path}")
        sys.exit(1)

    data_dir = Path(__file__).resolve().parent.parent / "data" / "bradley"
    conn = sqlite3.connect(str(db_path))

    print("=" * 60)
    print("Importing Bradley Theological Content")
    print("=" * 60)

    # 1. Import themes
    themes_path = data_dir / "themes.json"
    if themes_path.exists():
        themes = parse_themes_file(themes_path)
        count = 0
        for theme in themes:
            try:
                conn.execute(
                    """INSERT OR REPLACE INTO theology_themes
                       (theme_key, theme_label, description, parent_theme, key_works)
                       VALUES (?, ?, ?, ?, ?)""",
                    (theme["theme_key"], theme["theme_label"], theme["description"],
                     theme["parent_theme"], theme["key_works"]),
                )
                count += 1
            except sqlite3.Error as e:
                print(f"  Warning: Failed to insert theme {theme['theme_key']}: {e}")
        conn.commit()
        print(f"\n[Themes] Imported {count} themes")

    # 2. Import content files
    content_dir = data_dir / "content"
    total_entries = 0
    total_urls = 0
    total_refs = 0
    total_themes = 0
    json_files = sorted(content_dir.glob("*.json"))
    print(f"\n[Content] Found {len(json_files)} content files")

    for filepath in json_files:
        entries = 0
        urls = 0
        refs = 0
        themes = 0

        for content_entry, verse_refs, theme_keys in parse_heiser_content_file(filepath):
            try:
                content_id, status = upsert_theology_content(conn, content_entry)
                if status == "inserted":
                    entries += 1
                elif status == "url_updated":
                    urls += 1

                for vref in verse_refs:
                    try:
                        conn.execute(
                            """INSERT OR IGNORE INTO theology_verse_index
                               (content_id, reference, book, chapter, verse, relevance)
                               VALUES (?, ?, ?, ?, ?, ?)""",
                            (content_id, vref["reference"], vref["book"],
                             vref["chapter"], vref["verse"], vref["relevance"]),
                        )
                        refs += 1
                    except sqlite3.Error:
                        pass

                for theme_key in theme_keys:
                    try:
                        link_theology_theme(conn, theme_key, content_id)
                        themes += 1
                    except sqlite3.Error:
                        pass

            except sqlite3.Error as e:
                print(f"  Warning: Failed to insert entry '{content_entry.get('title', '?')}': {e}")

        conn.commit()
        total_entries += entries
        total_urls += urls
        total_refs += refs
        total_themes += themes
        print(f"  {filepath.name}: {entries} entries, {urls} urls updated, "
              f"{refs} verse refs, {themes} theme links")

    print(f"\n[Totals] {total_entries} entries, {total_urls} urls updated, "
          f"{total_refs} verse refs, {total_themes} theme links")

    # Summary
    print("\n" + "=" * 60)
    for table in ["theology_themes", "theology_content", "theology_verse_index", "theology_theme_index"]:
        row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        print(f"  {table}: {row[0]} rows")

    # Show per-author breakdown
    print("\nPer-author breakdown:")
    for row in conn.execute("SELECT source_author, COUNT(*) FROM theology_content GROUP BY source_author").fetchall():
        print(f"  {row[0]}: {row[1]} entries")
    print("=" * 60)

    conn.close()
    print("\nDone!")


if __name__ == "__main__":
    main()
