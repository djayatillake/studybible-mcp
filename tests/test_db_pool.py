"""StudyBibleDB's read-only connection pool.

With one aiosqlite connection every query waits for the one before it, so a
client's parallel tool calls queued behind the slowest (a 2 s vector scan held
up five quick calls for 2 s each). Inside ``db.reading()`` a task queries on a
pooled read-only connection of its own.
"""

import asyncio
import sqlite3
import time

import aiosqlite
import pytest

from study_bible_mcp import server
from study_bible_mcp.database import StudyBibleDB

NAP = 0.3


def _make_db(path) -> None:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")  # as the deployed database
    conn.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT)")
    conn.execute("CREATE VIRTUAL TABLE notes_fts USING fts5(body)")
    conn.execute("INSERT INTO notes_fts (body) VALUES ('melchizedek priest of salem')")
    conn.execute("INSERT INTO notes (body) VALUES ('a note')")
    conn.commit()
    conn.close()


async def _open(path, readers: int) -> StudyBibleDB:
    database = StudyBibleDB(path, readers=readers)
    await database.connect()
    # nap(s): a query that takes s seconds (time.sleep releases the GIL, as
    # SQLite does while it steps through a real slow query).
    for conn in [database._conn, *database._reader_conns]:
        await conn.create_function("nap", 1, lambda seconds: time.sleep(seconds) or 1)
    return database


async def _slow_query(database: StudyBibleDB) -> None:
    async with database.reading():
        await database._fetchone("SELECT nap(?) AS done", (NAP,))


@pytest.fixture
def db_file(tmp_path):
    path = tmp_path / "pool.db"
    _make_db(path)
    return path


async def test_pooled_reads_overlap(db_file):
    database = await _open(db_file, readers=2)
    try:
        assert database.reader_count == 2
        start = time.perf_counter()
        await asyncio.gather(_slow_query(database), _slow_query(database))
        elapsed = time.perf_counter() - start
    finally:
        await database.close()
    assert elapsed < 1.6 * NAP, f"two {NAP}s queries took {elapsed:.2f}s: they did not overlap"


async def test_without_readers_queries_still_queue_on_one_connection(db_file):
    database = await _open(db_file, readers=0)
    try:
        assert database.reader_count == 0
        start = time.perf_counter()
        await asyncio.gather(_slow_query(database), _slow_query(database))
        elapsed = time.perf_counter() - start
    finally:
        await database.close()
    assert elapsed >= 2 * NAP * 0.95


async def test_a_busy_pool_makes_the_next_call_wait(db_file):
    database = await _open(db_file, readers=2)
    try:
        start = time.perf_counter()
        await asyncio.gather(*(_slow_query(database) for _ in range(3)))
        elapsed = time.perf_counter() - start
    finally:
        await database.close()
    assert elapsed >= 2 * NAP * 0.95  # the third waited for a free reader


async def test_reading_binds_a_read_only_connection_to_the_task(db_file):
    database = await _open(db_file, readers=1)
    try:
        assert database.conn is database._conn
        async with database.reading():
            reader = database.conn
            assert reader is database._reader_conns[0]
            # Nested reading() keeps the same connection instead of waiting on the pool.
            async with database.reading():
                assert database.conn is reader
            with pytest.raises(sqlite3.OperationalError, match="readonly"):
                await reader.execute("INSERT INTO notes (body) VALUES ('no')")
            # Temporary tables still work (search_ancient_sources' fts5vocab lookup).
            await reader.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS temp.vocab USING fts5vocab(main, 'notes_fts', 'row')"
            )
            rows = await database._fetchall("SELECT term FROM temp.vocab WHERE term = 'salem'")
            assert rows == [{"term": "salem"}]
        assert database.conn is database._conn
        # The read-write connection still writes.
        await database.conn.execute("INSERT INTO notes (body) VALUES ('yes')")
        await database.conn.commit()
    finally:
        await database.close()


async def test_concurrent_tasks_get_different_readers(db_file):
    database = await _open(db_file, readers=2)
    seen: list[aiosqlite.Connection] = []
    both_in = asyncio.Event()

    async def hold():
        async with database.reading():
            seen.append(database.conn)
            if len(seen) == 2:
                both_in.set()
            await both_in.wait()  # each holds its reader until both have one

    try:
        await asyncio.wait_for(asyncio.gather(hold(), hold()), timeout=5)
    finally:
        await database.close()
    assert len({id(conn) for conn in seen}) == 2


async def test_call_tool_opens_one_database_for_concurrent_first_calls(db_file, monkeypatch):
    monkeypatch.setattr(server, "db", None)
    monkeypatch.setenv("STUDY_BIBLE_DB", str(db_file))
    monkeypatch.setenv("STUDY_BIBLE_DB_READERS", "2")
    opened = []
    real_connect = StudyBibleDB.connect

    async def counting_connect(self):
        opened.append(self)
        await real_connect(self)

    monkeypatch.setattr(StudyBibleDB, "connect", counting_connect)
    try:
        await asyncio.gather(*(server.call_tool("no_such_tool", {}) for _ in range(5)))
        assert len(opened) == 1
        assert server.db is opened[0]
        assert server.db.reader_count == 2
    finally:
        if server.db is not None:
            await server.db.close()
