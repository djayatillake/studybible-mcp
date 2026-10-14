"""Ordering of get_theology_context results by verse reference."""

import sqlite3

import pytest

from study_bible_mcp.database import StudyBibleDB, create_schema

# (id, title, [(reference, verse, relevance)], [theme keys])
ENTRIES = [
    (1, "Supporting entry", [("Psa.82.6", 6, "supporting")], ["divine_council"]),
    (2, "Primary entry A", [("Psa.82.6", 6, "primary")], ["sons_of_god", "divine_council", "elohim"]),
    (3, "Primary entry B", [("Psa.82.6", 6, "primary")], []),
    (4, "Secondary entry", [("Psa.82.6", 6, "secondary")], []),
    # Chapter fallback: one entry matched by two verses at different tiers.
    (5, "Mixed chapter entry", [("Psa.82.1", 1, "supporting"), ("Psa.82.8", 8, "primary")], []),
    (6, "Supporting chapter entry", [("Psa.82.2", 2, "supporting")], []),
]


@pytest.fixture
async def theology_db(tmp_path):
    db_path = tmp_path / "theology.db"
    conn = sqlite3.connect(db_path)
    create_schema(conn)
    for key in ("divine_council", "elohim", "sons_of_god"):
        conn.execute(
            "INSERT INTO theology_themes (theme_key, theme_label, description) VALUES (?, ?, ?)",
            (key, key, key),
        )
    for content_id, title, refs, themes in ENTRIES:
        conn.execute(
            """INSERT INTO theology_content
               (id, source_work, source_author, source_type, title, content_summary)
               VALUES (?, 'Work', 'heiser', 'book', ?, 'summary')""",
            (content_id, title),
        )
        for reference, verse, relevance in refs:
            conn.execute(
                """INSERT INTO theology_verse_index
                   (content_id, reference, book, chapter, verse, relevance)
                   VALUES (?, ?, 'Psa', 82, ?, ?)""",
                (content_id, reference, verse, relevance),
            )
        for key in themes:
            conn.execute(
                "INSERT INTO theology_theme_index (theme_key, content_id) VALUES (?, ?)",
                (key, content_id),
            )
    conn.commit()
    conn.close()
    db = StudyBibleDB(db_path)
    await db.connect()
    yield db
    await db.close()


async def test_primary_entries_rank_before_supporting_with_stable_ties(theology_db):
    rows = await theology_db.get_theology_context_by_reference("Psalm 82:6")
    assert [row["id"] for row in rows] == [2, 3, 1, 4]
    assert [row["relevance"] for row in rows] == ["primary", "primary", "supporting", "secondary"]


async def test_theme_lists_are_sorted(theology_db):
    rows = await theology_db.get_theology_context_by_reference("Psalm 82:6")
    assert rows[0]["themes"] == "divine_council,elohim,sons_of_god"


async def test_chapter_fallback_uses_each_entrys_best_match(theology_db):
    rows = await theology_db.get_theology_context_by_reference("Psalm 82:4")
    mixed = next(row for row in rows if row["id"] == 5)
    assert (mixed["matched_ref"], mixed["relevance"]) == ("Psa.82.8", "primary")
    assert [row["id"] for row in rows].index(5) < [row["id"] for row in rows].index(6)
