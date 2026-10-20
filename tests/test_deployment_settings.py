"""Settings for deployments other than the Fly one: the database download can be turned off."""

from starlette.applications import Starlette
from starlette.testclient import TestClient

from study_bible_mcp import server


def test_download_route_can_be_turned_off(monkeypatch):
    monkeypatch.setattr(server, "DATABASE_DOWNLOAD", False)
    client = TestClient(Starlette(routes=server._make_shared_routes()))
    assert client.get("/download/study_bible.db").status_code == 404
