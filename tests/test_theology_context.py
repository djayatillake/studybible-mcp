"""Ordering of get_theology_context results by verse reference and by theme."""

import re
import sqlite3

import pytest

import study_bible_mcp.server as server
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


async def test_theme_results_alternate_between_authors(tmp_path, monkeypatch):
    # Alphabetical author order would fill the default four with one scholar.
    db_path = tmp_path / "themes.db"
    conn = sqlite3.connect(db_path)
    create_schema(conn)
    conn.execute(
        "INSERT INTO theology_themes (theme_key, theme_label, description) "
        "VALUES ('atonement_models', 'Atonement models', 'Models')"
    )
    for content_id, author in [(1, "stott"), (2, "stott"), (3, "stott"), (4, "synthesis"), (5, "synthesis")]:
        conn.execute(
            """INSERT INTO theology_content
               (id, source_work, source_author, source_type, title, content_summary)
               VALUES (?, 'Work', ?, 'book', ?, 'summary')""",
            (content_id, author, f"Entry {content_id}"),
        )
        conn.execute(
            "INSERT INTO theology_theme_index (theme_key, content_id) VALUES ('atonement_models', ?)",
            (content_id,),
        )
    conn.commit()
    conn.close()
    db = StudyBibleDB(db_path)
    await db.connect()
    monkeypatch.setattr(server, "db", db)
    try:
        async def titles(**arguments):
            output = (await server.call_tool("get_theology_context", arguments))[0].text
            return re.findall(r"^### Entry (\d)$", output, re.MULTILINE)

        assert await titles(theme="atonement_models") == ["1", "4", "2", "5"]
        assert await titles(theme="atonement_models", limit=10) == ["1", "4", "2", "5", "3"]
        assert await titles(theme="atonement_models", author="stott") == ["1", "2", "3"]
    finally:
        await db.close()


async def test_chapter_reference_returns_the_chapters_entries(theology_db, monkeypatch):
    # 'Psalm 82' has no verse: every entry indexed to the chapter, ranked as the
    # chapter fallback ranks them (primary first, then by verse).
    rows = await theology_db.get_theology_context_by_reference("Psalm 82", limit=10)
    assert [row["id"] for row in rows] == [2, 3, 5, 6, 1, 4]
    assert await theology_db.get_theology_context_by_reference("Psalm 83") == []
    monkeypatch.setattr(server, "db", theology_db)
    output = (await server.call_tool("get_theology_context", {"reference": "Psalm 82"}))[0].text
    assert output.startswith("## Theological Scholarship Context for Psalm 82")
    assert re.findall(r"^### (.+)$", output, re.MULTILINE) == [
        "Primary entry A", "Primary entry B", "Mixed chapter entry", "Supporting chapter entry",
    ]


async def test_unknown_author_lists_the_authors(theology_db, monkeypatch):
    monkeypatch.setattr(server, "db", theology_db)
    output = (await server.call_tool(
        "get_theology_context", {"reference": "Psalm 82:6", "author": "calvin"}
    ))[0].text
    assert output == "No scholarship by author 'calvin'. Authors: heiser."
    # Author keys are matched case-insensitively.
    named = (await server.call_tool(
        "get_theology_context", {"reference": "Psalm 82:6", "author": "Heiser"}
    ))[0].text
    assert named.startswith("## Heiser Scholarship Context for Psalm 82:6")


async def test_unknown_theme_points_to_the_theme_list(theology_db, monkeypatch):
    monkeypatch.setattr(server, "db", theology_db)
    output = (await server.call_tool("get_theology_context", {"theme": "covenant_theology"}))[0].text
    assert output == (
        "No theological scholarship found for theme='covenant_theology'. No theme has that "
        "key; call with no arguments to list the themes."
    )
