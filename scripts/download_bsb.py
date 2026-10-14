#!/usr/bin/env python3
"""Download the Berean Standard Bible text (bsb.txt), verified against its pinned SHA-256.

The file is unversioned, so ``BSB_SHA256`` in study_bible_mcp/parsers/bsb.py
pins its exact contents. Until that pin is set this script refuses to run;
build_database.py then imports data/bsb/bsb.txt into bsb_verses.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click
import httpx
from rich.console import Console

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from study_bible_mcp.parsers import bsb

console = Console()


def download_bsb(client: httpx.Client, target: Path, force: bool) -> dict:
    """Install bsb.txt in ``target`` once it matches the pin; return its manifest entry.

    Refuses, before any request, while the pin is unset. An existing file is
    verified rather than replaced unless ``force`` is set, and a file that does
    not verify is never written.
    """
    if not bsb.BSB_SHA256:
        raise RuntimeError(
            "BSB_SHA256 is not set in src/study_bible_mcp/parsers/bsb.py. Review "
            f"{bsb.BSB_SOURCE_URL}, then pin its SHA-256 before downloading it."
        )
    destination = target / bsb.BSB_FILENAME
    if destination.exists() and not force:
        content = destination.read_bytes()
        try:
            bsb.verify_bsb_checksum(content)
        except ValueError as error:
            raise RuntimeError(
                f"{error} The existing {destination} was left in place; rerun with "
                "--force to replace it with a verified download."
            ) from error
    else:
        response = client.get(bsb.BSB_SOURCE_URL)
        response.raise_for_status()
        content = response.content
        try:
            bsb.verify_bsb_checksum(content)
        except ValueError as error:
            raise RuntimeError(f"{error} Nothing was written.") from error
        target.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
    return {
        "source_url": bsb.BSB_SOURCE_URL,
        "sha256": bsb.BSB_SHA256,
        "bytes": len(content),
        "license": bsb.BSB_LICENSE,
    }


@click.command()
@click.option(
    "--data-dir",
    type=click.Path(path_type=Path),
    default=PROJECT_ROOT / "data" / "bsb",
    show_default=True,
)
@click.option("--force", is_flag=True, help="Redownload a file already present")
def main(data_dir: Path, force: bool) -> None:
    """Download bsb.txt into DATA_DIR and write its source manifest."""
    headers = {"User-Agent": "studybible-mcp/1.0"}
    with httpx.Client(
        timeout=httpx.Timeout(180.0, connect=30.0), follow_redirects=True, headers=headers
    ) as client:
        try:
            manifest = download_bsb(client, data_dir, force)
        except RuntimeError as error:
            raise click.ClickException(str(error)) from error
    (data_dir / "source_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    console.print(f"[green]✓[/green] {bsb.BSB_FILENAME} verified in {data_dir}")


if __name__ == "__main__":
    main()
