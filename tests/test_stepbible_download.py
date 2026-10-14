"""scripts/download_stepbible.py: pinned sources and checksum checks (issue #2)."""

from __future__ import annotations

import hashlib
import importlib.util
import re
from pathlib import Path

import httpx
import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "download_stepbible.py"


@pytest.fixture
def downloader():
    spec = importlib.util.spec_from_file_location("download_stepbible_pins", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_source_is_pinned_to_a_commit_with_a_checksum(downloader):
    for key, info in downloader.FILES.items():
        assert re.search(r"/[0-9a-f]{40}/", info["url"]), f"{key} is not pinned: {info['url']}"
        assert "/master/" not in info["url"] and "/main/" not in info["url"], key
        assert re.fullmatch(r"[0-9a-f]{64}", info["sha256"]), key


def _serve(downloader, monkeypatch, body_for):
    """Route download_sync's client to a mock that serves body_for(filename)."""
    names = {info["url"]: info["filename"] for info in downloader.FILES.values()}

    def handler(request: httpx.Request) -> httpx.Response:
        body = body_for(names[str(request.url)])
        return httpx.Response(200, content=body) if body is not None else httpx.Response(404)

    real_client = httpx.Client
    monkeypatch.setattr(
        downloader.httpx,
        "Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler)),
    )


def _pin(downloader, monkeypatch, contents: dict[str, bytes]):
    """Give every file a checksum: the given content's, or one nothing matches."""
    for info in downloader.FILES.values():
        body = contents.get(info["filename"])
        sha = hashlib.sha256(body).hexdigest() if body is not None else "0" * 64
        monkeypatch.setitem(info, "sha256", sha)


def test_download_saves_files_matching_their_checksum(downloader, monkeypatch, tmp_path):
    contents = {info["filename"]: info["filename"].encode() for info in downloader.FILES.values()}
    _pin(downloader, monkeypatch, contents)
    _serve(downloader, monkeypatch, contents.get)

    assert downloader.download_sync(tmp_path) is True
    for name, body in contents.items():
        assert (tmp_path / name).read_bytes() == body


def test_a_changed_upstream_file_is_refused_not_saved(downloader, monkeypatch, tmp_path):
    contents = {info["filename"]: b"pinned" for info in downloader.FILES.values()}
    _pin(downloader, monkeypatch, contents)
    _serve(downloader, monkeypatch, lambda name: b"changed upstream")

    # TFLSJ_0-5624.txt and DictBDB.json are required, so the download fails.
    assert downloader.download_sync(tmp_path) is False
    assert not list(tmp_path.iterdir())


def test_a_cached_file_that_differs_is_kept_with_a_warning(downloader, monkeypatch, tmp_path, capsys):
    contents = {info["filename"]: b"pinned" for info in downloader.FILES.values()}
    _pin(downloader, monkeypatch, contents)
    _serve(downloader, monkeypatch, contents.get)
    stale = tmp_path / "TIPNR.txt"
    stale.write_bytes(b"an older download")

    assert downloader.download_sync(tmp_path) is True
    assert stale.read_bytes() == b"an older download"
    assert "differs from the pinned version" in capsys.readouterr().out
