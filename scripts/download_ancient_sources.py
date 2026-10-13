#!/usr/bin/env python3
"""Download every registered ancient-source corpus, checksum-verified against its pin."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click
import httpx
from rich.console import Console

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from study_bible_mcp.corpora import CORPORA

console = Console()


@click.command()
@click.option(
    "--data-dir",
    type=click.Path(path_type=Path),
    default=PROJECT_ROOT / "data" / "ancient_sources",
)
@click.option("--force", is_flag=True, help="Redownload files already present")
def main(data_dir: Path, force: bool) -> None:
    """Download each corpus into <data-dir>/<corpus data_dir> and write the manifest."""
    headers = {"User-Agent": "studybible-mcp/1.0"}
    manifest: dict[str, dict] = {}
    with httpx.Client(
        timeout=httpx.Timeout(180.0, connect=30.0), follow_redirects=True, headers=headers
    ) as client:
        for key, corpus in CORPORA.items():
            target = data_dir / corpus.data_dir
            target.mkdir(parents=True, exist_ok=True)
            manifest[key] = corpus.download(client, target, force)
            corpus.require_files(target)
            console.print(f"[green]✓[/green] {corpus.label}: {target}")
    (data_dir / "source_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    console.print(f"\n[bold green]Ancient sources verified in {data_dir}[/bold green]")


if __name__ == "__main__":
    main()
