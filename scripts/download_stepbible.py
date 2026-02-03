#!/usr/bin/env python3
"""
Download STEPBible data files from GitHub.

This script downloads the following datasets:
- TBESG: Greek lexicon (Extended Strong's)
- TBESH: Hebrew lexicon (Extended Strong's)
- TAGNT: Tagged Greek NT (morphology + Strong's) - split into 2 parts
- TAHOT: Tagged Hebrew OT (morphology + Strong's) - split into 4 parts
- TIPNR: Proper names with references
- TEGMC: Greek morphology code expansions
- TEHMC: Hebrew morphology code expansions
"""

import sys
from pathlib import Path

import click
import httpx
from rich.console import Console

console = Console()

# STEPBible GitHub raw URLs - updated to match current repo structure
BASE_URL = "https://raw.githubusercontent.com/STEPBible/STEPBible-Data/master"

FILES = {
    # Lexicons - note: "lexicon" not "lexance"
    "TBESG": {
        "url": f"{BASE_URL}/Lexicons/TBESG%20-%20Translators%20Brief%20lexicon%20of%20Extended%20Strongs%20for%20Greek%20-%20STEPBible.org%20CC%20BY.txt",
        "filename": "TBESG.txt",
        "description": "Greek Lexicon (Extended Strong's)",
        "required": True,
    },
    "TBESH": {
        "url": f"{BASE_URL}/Lexicons/TBESH%20-%20Translators%20Brief%20lexicon%20of%20Extended%20Strongs%20for%20Hebrew%20-%20STEPBible.org%20CC%20BY.txt",
        "filename": "TBESH.txt",
        "description": "Hebrew Lexicon (Extended Strong's)",
        "required": True,
    },

    # Tagged texts - Greek NT (split into 2 parts)
    "TAGNT_1": {
        "url": f"{BASE_URL}/Translators%20Amalgamated%20OT%2BNT/TAGNT%20Mat-Jhn%20-%20Translators%20Amalgamated%20Greek%20NT%20-%20STEPBible.org%20CC-BY.txt",
        "filename": "TAGNT_Mat-Jhn.txt",
        "description": "Tagged Greek NT (Matthew-John)",
        "required": False,
    },
    "TAGNT_2": {
        "url": f"{BASE_URL}/Translators%20Amalgamated%20OT%2BNT/TAGNT%20Act-Rev%20-%20Translators%20Amalgamated%20Greek%20NT%20-%20STEPBible.org%20CC-BY.txt",
        "filename": "TAGNT_Act-Rev.txt",
        "description": "Tagged Greek NT (Acts-Revelation)",
        "required": False,
    },

    # Tagged texts - Hebrew OT (split into 4 parts)
    "TAHOT_1": {
        "url": f"{BASE_URL}/Translators%20Amalgamated%20OT%2BNT/TAHOT%20Gen-Deu%20-%20Translators%20Amalgamated%20Hebrew%20OT%20-%20STEPBible.org%20CC%20BY.txt",
        "filename": "TAHOT_Gen-Deu.txt",
        "description": "Tagged Hebrew OT (Genesis-Deuteronomy)",
        "required": False,
    },
    "TAHOT_2": {
        "url": f"{BASE_URL}/Translators%20Amalgamated%20OT%2BNT/TAHOT%20Jos-Est%20-%20Translators%20Amalgamated%20Hebrew%20OT%20-%20STEPBible.org%20CC%20BY.txt",
        "filename": "TAHOT_Jos-Est.txt",
        "description": "Tagged Hebrew OT (Joshua-Esther)",
        "required": False,
    },
    "TAHOT_3": {
        "url": f"{BASE_URL}/Translators%20Amalgamated%20OT%2BNT/TAHOT%20Job-Sng%20-%20Translators%20Amalgamated%20Hebrew%20OT%20-%20STEPBible.org%20CC%20BY.txt",
        "filename": "TAHOT_Job-Sng.txt",
        "description": "Tagged Hebrew OT (Job-Song of Solomon)",
        "required": False,
    },
    "TAHOT_4": {
        "url": f"{BASE_URL}/Translators%20Amalgamated%20OT%2BNT/TAHOT%20Isa-Mal%20-%20Translators%20Amalgamated%20Hebrew%20OT%20-%20STEPBible.org%20CC%20BY.txt",
        "filename": "TAHOT_Isa-Mal.txt",
        "description": "Tagged Hebrew OT (Isaiah-Malachi)",
        "required": False,
    },

    # Proper names
    "TIPNR": {
        "url": f"{BASE_URL}/TIPNR%20-%20Translators%20Individualised%20Proper%20Names%20with%20all%20References%20-%20STEPBible.org%20CC%20BY.txt",
        "filename": "TIPNR.txt",
        "description": "Proper Names Database",
        "required": False,
    },

    # Morphology codes
    "TEGMC": {
        "url": f"{BASE_URL}/TEGMC%20-%20Translators%20Expansion%20of%20Greek%20Morphhology%20Codes%20-%20STEPBible.org%20CC%20BY.txt",
        "filename": "TEGMC.txt",
        "description": "Greek Morphology Codes",
        "required": False,
    },
    "TEHMC": {
        "url": f"{BASE_URL}/TEHMC%20-%20Translators%20Expansion%20of%20Hebrew%20Morphology%20Codes%20-%20STEPBible.org%20CC%20BY.txt",
        "filename": "TEHMC.txt",
        "description": "Hebrew Morphology Codes",
        "required": False,
    },
}


def get_data_dir() -> Path:
    """Get the data directory."""
    pkg_dir = Path(__file__).parent.parent
    data_dir = pkg_dir / "data"

    if not data_dir.exists():
        data_dir = Path.cwd() / "data"

    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def download_sync(data_dir: Path, force: bool = False) -> bool:
    """Synchronous download of STEPBible data files."""
    console.print("\n[bold]Downloading STEPBible Data[/bold]")
    console.print(f"Target directory: {data_dir}\n")

    timeout = httpx.Timeout(120.0, connect=30.0)
    success_count = 0
    required_failed = []

    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        for key, file_info in FILES.items():
            console.print(f"[bold]{key}[/bold]: {file_info['description']}")

            filepath = data_dir / file_info["filename"]

            if filepath.exists() and not force:
                console.print(f"  [dim]Skipping {file_info['filename']} (already exists)[/dim]")
                success_count += 1
                continue

            try:
                response = client.get(file_info["url"])

                if response.status_code == 200:
                    content = response.content
                    filepath.write_bytes(content)
                    size_mb = len(content) / (1024 * 1024)
                    console.print(f"  [green]✓[/green] {file_info['filename']} ({size_mb:.1f} MB)")
                    success_count += 1
                else:
                    console.print(f"  [red]✗[/red] HTTP {response.status_code}")
                    if file_info.get("required"):
                        required_failed.append(key)

            except Exception as e:
                console.print(f"  [red]✗[/red] Error: {e}")
                if file_info.get("required"):
                    required_failed.append(key)

    console.print(f"\n[bold]Downloaded {success_count}/{len(FILES)} files[/bold]")

    if required_failed:
        console.print(f"\n[red]Required files failed: {required_failed}[/red]")
        return False

    return True


@click.command()
@click.option("--force", "-f", is_flag=True, help="Re-download even if files exist")
@click.option("--data-dir", "-d", type=click.Path(), help="Data directory (default: ./data)")
def main(force: bool, data_dir: str | None):
    """Download STEPBible data files."""
    if data_dir:
        target_dir = Path(data_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
    else:
        target_dir = get_data_dir()

    console.print("[bold blue]Study Bible MCP - Data Downloader[/bold blue]")
    console.print("Data source: STEPBible.org (CC BY 4.0)\n")

    success = download_sync(target_dir, force)

    if success:
        console.print("\n[bold green]✓ Download complete![/bold green]")
        console.print(f"\nNext step: Run [bold]python scripts/build_database.py[/bold]")
    else:
        console.print("\n[yellow]Some files failed. Check the URLs or download manually.[/yellow]")
        sys.exit(1)


if __name__ == "__main__":
    main()
