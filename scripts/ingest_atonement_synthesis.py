#!/usr/bin/env python3
"""
Ingest the atonement substitution-vs-representation synthesis into the study-bible DB.

Two targets, both idempotent:
  1. theology tables  <- data/synthesis/ (themes.json + content/atonement_models.json)
     A neutral "synthesis" author cell that NAMES the substitution/representation
     distinction and locates penal substitution (representation as frame, PSA inside).
     Tagged under theme atonement_models AND corporate_headship; verse-anchored to the
     ransom sayings (Mt 20:28; Mk 10:45) and their juridical neighbours.
  2. ane_entries / ane_book_mappings  <- data/ane_context/13_methodology.json (method_008)
     The prescriptive "representation-frame read-order" protocol, complementing the
     existing Rillera/Milgrom non-penal corpus (method_005-007, relig_012-021, death_008).

Re-runnable: theology inserts use INSERT OR IGNORE / OR REPLACE; the ANE load uses
INSERT OR REPLACE + delete-then-insert for book mappings (NULL chapter_start safe).
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from study_bible_mcp.parsers.heiser import parse_themes_file, parse_heiser_content_file
from study_bible_mcp.parsers.ane_context import parse_ane_context_file

DB_PATH = ROOT / "db" / "study_bible.db"
SYNTH_DIR = ROOT / "data" / "synthesis"
METHOD_FILE = ROOT / "data" / "ane_context" / "13_methodology.json"
ANE_ENTRY_IDS = {"method_008"}  # which ane entries this script owns / (re)loads


def import_theology(conn: sqlite3.Connection) -> None:
    # 1. themes
    for theme in parse_themes_file(SYNTH_DIR / "themes.json"):
        conn.execute(
            """INSERT OR REPLACE INTO theology_themes
               (theme_key, theme_label, description, parent_theme, key_works)
               VALUES (?, ?, ?, ?, ?)""",
            (theme["theme_key"], theme["theme_label"], theme["description"],
             theme["parent_theme"], theme["key_works"]),
        )

    # 2. content + verse index + theme index
    n_entries = n_refs = n_themes = 0
    for filepath in sorted((SYNTH_DIR / "content").glob("*.json")):
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
                conn.execute(
                    """INSERT OR IGNORE INTO theology_theme_index
                       (theme_key, content_id, reference) VALUES (?, ?, NULL)""",
                    (theme_key, content_id),
                )
                n_themes += 1
    print(f"  [theology] {n_entries} new content entries, {n_refs} verse refs, {n_themes} theme links")


def import_method_008(conn: sqlite3.Connection) -> None:
    n_entries = n_maps = 0
    for entry, book_mappings in parse_ane_context_file(METHOD_FILE):
        if entry["id"] not in ANE_ENTRY_IDS:
            continue
        conn.execute(
            """INSERT OR REPLACE INTO ane_entries
               (id, dimension, dimension_label, title, summary, detail,
                ane_parallels, interpretive_significance, period, period_label,
                key_references, scholarly_sources)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (entry["id"], entry["dimension"], entry["dimension_label"], entry["title"],
             entry["summary"], entry.get("detail"), entry.get("ane_parallels"),
             entry.get("interpretive_significance"), entry.get("period"),
             entry.get("period_label"), entry.get("key_references"),
             entry.get("scholarly_sources")),
        )
        n_entries += 1
        conn.execute("DELETE FROM ane_book_mappings WHERE entry_id=?", (entry["id"],))
        for bm in book_mappings:
            conn.execute(
                """INSERT OR REPLACE INTO ane_book_mappings
                   (entry_id, book, chapter_start, chapter_end) VALUES (?,?,?,?)""",
                (bm["entry_id"], bm["book"], bm.get("chapter_start"), bm.get("chapter_end")),
            )
            n_maps += 1
    print(f"  [ane] loaded {n_entries} entry / {n_maps} book mappings (method_008)")


def main() -> None:
    if not DB_PATH.exists():
        print(f"Database not found at {DB_PATH}")
        sys.exit(1)
    print("=" * 60)
    print("Ingesting atonement synthesis (substitution vs representation)")
    print("=" * 60)
    conn = sqlite3.connect(str(DB_PATH))
    import_theology(conn)
    import_method_008(conn)
    conn.commit()

    # Summary
    print("\nVerification:")
    for r in conn.execute(
        "SELECT source_author, COUNT(*) FROM theology_content GROUP BY source_author ORDER BY source_author"
    ):
        print(f"  theology author {r[0]}: {r[1]}")
    print("  atonement_models theme rows:",
          conn.execute("SELECT COUNT(*) FROM theology_theme_index WHERE theme_key='atonement_models'").fetchone()[0])
    print("  method_008 present:",
          conn.execute("SELECT COUNT(*) FROM ane_entries WHERE id='method_008'").fetchone()[0])
    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
