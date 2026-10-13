"""The public database download carries the licence notice for its NC and SA texts."""

from starlette.applications import Starlette
from starlette.testclient import TestClient

from study_bible_mcp import server


def test_download_route_sends_the_data_licence_notice(tmp_path, monkeypatch):
    database = tmp_path / "study_bible.db"
    database.write_bytes(b"SQLite format 3\x00")
    monkeypatch.setattr(server, "get_db_path", lambda: database)
    client = TestClient(Starlette(routes=server._make_shared_routes()))

    response = client.get("/download/study_bible.db")

    assert response.status_code == 200
    notice = response.headers["x-data-license-notice"]
    assert notice == server.DATABASE_LICENSE_NOTICE
    for source in ("CC BY-NC", "ETCBC", "Metsudah", "CC BY-SA", "Perseus Josephus",
                   "First1KGreek Philo", "Latin Wikisource"):
        assert source in notice
    assert notice.isascii()


def test_root_description_states_the_notice():
    assert server.ROOT_DESCRIPTION.startswith("Bible study tools")
    assert server.DATABASE_LICENSE_NOTICE in server.ROOT_DESCRIPTION
    assert len(server.DATABASE_LICENSE_NOTICE) < 300
