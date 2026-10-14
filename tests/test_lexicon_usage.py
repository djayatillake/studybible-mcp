"""Lexicon usage counts from the tagged text, and search_lexicon's ranking."""

from __future__ import annotations

import json
import sqlite3

import pytest

from study_bible_mcp import lexicon_usage
from study_bible_mcp.database import StudyBibleDB, create_schema


def _words(*numbers: str) -> str:
    return json.dumps([{"word": "w", "strongs": n} for n in numbers])


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "usage.db"
    conn = sqlite3.connect(path)
    create_schema(conn)
    conn.executemany(
        "INSERT INTO lexicon (strongs, language, word, transliteration, short_definition,"
        " full_definition) VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("H0430", "hebrew", "אֱלֹהִים", "elohim", "God, gods", "God; gods."),
            ("H0157", "hebrew", "אָהַב", "ahav", "to love", "To love."),
            ("G0026", "greek", "ἀγάπη", "agapē", "love, goodwill", "Love."),
            ("G0072", "greek", "ἀγωγή", "agōgē", "conduct", "Manner of life, as in love of learning."),
            ("G9999", "greek", "x", "x", "unused", "Never tagged."),
        ],
    )
    conn.executemany(
        "INSERT INTO verses (reference, book, chapter, verse, word_data) VALUES (?, ?, ?, ?, ?)",
        [
            ("Gen.1.1", "Gen", 1, 1, _words("H9003", "H0430G", "H0430")),
            ("Gen.22.2", "Gen", 22, 2, _words("H0157", "H0430H")),
            ("Jhn.3.16", "Jhn", 3, 16, _words("G0026", "G26", "G0072", "G0072", "G0072")),
            ("Hdr.0.0", "Hdr", 0, 0, _words("dStrongs", "")),
            ("Bad.0.1", "Bad", 0, 1, "not json"),
            ("Emp.0.2", "Emp", 0, 2, None),
        ],
    )
    conn.commit()
    conn.close()
    return path


def _usage(path) -> dict[str, int]:
    conn = sqlite3.connect(path)
    rows = dict(conn.execute("SELECT strongs, usage_count FROM lexicon"))
    conn.close()
    return rows


def test_counts_drop_sense_suffixes_and_skip_junk(db_path):
    conn = sqlite3.connect(db_path)
    counts = lexicon_usage.count_strongs_usage(conn)
    conn.close()
    assert counts["H0430"] == 3
    assert counts["G0026"] == 2
    assert counts["H9003"] == 1
    assert "dStrongs" not in counts and "" not in counts


def test_update_is_idempotent_and_runs_as_a_module(db_path, capsys):
    assert lexicon_usage.main([str(db_path)]) == 0
    assert _usage(db_path) == {"H0430": 3, "H0157": 1, "G0026": 2, "G0072": 3, "G9999": 0}
    assert "updated 4 lexicon entries; 4 now have a usage count" in capsys.readouterr().out
    assert lexicon_usage.main([str(db_path)]) == 0
    assert "updated 0 lexicon entries" in capsys.readouterr().out


async def test_search_lexicon_ranks_gloss_matches_before_definition_matches(db_path):
    lexicon_usage.main([str(db_path)])
    database = StudyBibleDB(db_path)
    await database.connect()
    try:
        results = await database.search_lexicon("love")
    finally:
        await database.close()
    # G0072 is the most frequent match, but "love" is only in its definition.
    assert [row["strongs"] for row in results] == ["G0026", "H0157", "G0072"]
