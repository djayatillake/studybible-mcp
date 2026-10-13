"""Checksum-verified download helpers shared by corpus ``download`` functions."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import httpx

GITHUB_API = "https://api.github.com/repos"
_GITHUB_HEADERS = {"Accept": "application/vnd.github+json"}


def git_blob_sha1(content: bytes) -> str:
    """Git's blob hash, which GitHub's contents API reports for every file."""
    return hashlib.sha1(f"blob {len(content)}\0".encode() + content).hexdigest()


def sha256_hex(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def fetch_verified(
    client: httpx.Client,
    url: str,
    destination: Path,
    expected: str,
    force: bool = False,
    digest: Callable[[bytes], str] = sha256_hex,
) -> bytes:
    """Return the verified bytes of ``destination``, downloading ``url`` if needed.

    An existing file is reused unless ``force``. A download is written only
    after it verifies; an existing file that fails verification is deleted.
    Either failure raises ``RuntimeError``.
    """
    if destination.exists() and not force:
        content = destination.read_bytes()
        downloaded = False
    else:
        response = client.get(url)
        response.raise_for_status()
        content = response.content
        downloaded = True
    actual = digest(content)
    if actual != expected:
        if not downloaded:
            destination.unlink(missing_ok=True)
        raise RuntimeError(f"Checksum mismatch for {destination.name}: {actual} != {expected}")
    if downloaded:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
    return content


def fetch_github_directory(
    client: httpx.Client,
    repo: str,
    commit: str,
    path: str,
    target: Path,
    select: Callable[[str], str | None],
    force: bool = False,
    validate: Callable[[str, bytes], None] | None = None,
) -> dict[str, dict]:
    """Download selected files of ``repo``/``path`` at ``commit``, verified by Git blob hash.

    ``select(name)`` returns the local filename for a wanted file or None to
    skip it; ``validate(filename, content)`` may raise to reject a file (e.g. a
    missing licence declaration). Returns manifest entries per local filename.
    """
    response = client.get(
        f"{GITHUB_API}/{repo}/contents/{path}", params={"ref": commit}, headers=_GITHUB_HEADERS
    )
    response.raise_for_status()
    manifest: dict[str, dict] = {}
    for item in response.json():
        filename = select(item["name"]) if item["type"] == "file" else None
        if filename is None:
            continue
        content = fetch_verified(
            client, item["download_url"], target / filename, item["sha"], force, git_blob_sha1
        )
        if validate is not None:
            validate(filename, content)
        manifest[filename] = {
            "git_blob_sha1": item["sha"],
            "bytes": len(content),
            "source_url": item["html_url"],
        }
    return manifest
