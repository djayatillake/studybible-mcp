"""The verse_strongs index: same verses as the word_data scan, kept current by the repair."""

import sqlite3

from study_bible_mcp.database import StudyBibleDB, build_strongs_index

from .tool_handler_fixture import build_fixture_db

CODES = ["G26", "G0026", "H430", "H0430G", "G9999"]


async def _results(path):
    database = StudyBibleDB(path)
    await database.connect()
    try:
        found = {
            code: (
                [v["reference"] for v in await database.get_verses_with_strongs(code, limit=50)],
                await database.count_verses_with_strongs(code),
            )
            for code in CODES
        }
        return found, database._has_strongs_index
    finally:
        await database.close()


async def test_index_finds_the_same_verses_as_the_scan(tmp_path):
    path = tmp_path / "fixture.db"
    build_fixture_db(path)
    scanned, indexed_before = await _results(path)
    assert indexed_before is False

    conn = sqlite3.connect(path)
    first = build_strongs_index(conn)
    second = build_strongs_index(conn)  # rebuilding replaces, never duplicates
    conn.commit()
    conn.close()
    assert first == second > 0

    indexed, indexed_after = await _results(path)
    assert indexed_after is True
    assert indexed == scanned
    assert scanned["G26"][1] > 0
