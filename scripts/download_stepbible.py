#!/usr/bin/env python3
"""
Download STEPBible data files and supplementary resources from GitHub.

This script downloads the following datasets:
- TFLSJ: Full LSJ Greek lexicon (preferred) / TBESG fallback
- BDB: Full Brown-Driver-Briggs Hebrew lexicon (preferred) / TBESH fallback
- TAGNT: Tagged Greek NT (morphology + Strong's) - split into 2 parts
- TAHOT: Tagged Hebrew OT (morphology + Strong's) - split into 4 parts
- TIPNR: Proper names with references
- TEGMC: Greek morphology code expansions
- TEHMC: Hebrew morphology code expansions
- BibleAquifer: Study notes, dictionary, translation notes, key terms (--aquifer)
- ACAI: Entity annotations (--aquifer)
"""

import sys
from pathlib import Path

import click
import httpx
from rich.console import Console

console = Console()

# STEPBible GitHub raw URLs - updated to match current repo structure
BASE_URL = "https://raw.githubusercontent.com/STEPBible/STEPBible-Data/master"

# BDB Hebrew lexicon from eliranwong (note: master branch, not main)
BDB_URL = "https://raw.githubusercontent.com/eliranwong/unabridged-BDB-Hebrew-lexicon/master/DictBDB.json"

# BibleAquifer base URLs
AQUIFER_BASE = "https://raw.githubusercontent.com/BibleAquifer"

FILES = {
    # Full LSJ Greek lexicon (preferred over TBESG)
    "TFLSJ_1": {
        "url": f"{BASE_URL}/Lexicons/TFLSJ%20%200-5624%20-%20Translators%20Formatted%20full%20LSJ%20Bible%20lexicon%20-%20STEPBible.org%20CC%20BY.txt",
        "filename": "TFLSJ_0-5624.txt",
        "description": "Full LSJ Greek Lexicon (Strong's 0-5624)",
        "required": True,
    },
    "TFLSJ_2": {
        "url": f"{BASE_URL}/Lexicons/TFLSJ%20extra%20-%20Translators%20Formatted%20full%20LSJ%20Bible%20lexicon%20-%20STEPBible.org%20CC%20BY.txt",
        "filename": "TFLSJ_extra.txt",
        "description": "Full LSJ Greek Lexicon (extra entries)",
        "required": False,
    },
    # Brief Greek lexicon (fallback)
    "TBESG": {
        "url": f"{BASE_URL}/Lexicons/TBESG%20-%20Translators%20Brief%20lexicon%20of%20Extended%20Strongs%20for%20Greek%20-%20STEPBible.org%20CC%20BY.txt",
        "filename": "TBESG.txt",
        "description": "Greek Lexicon - Brief (Extended Strong's)",
        "required": False,
    },
    # Full BDB Hebrew lexicon
    "BDB": {
        "url": BDB_URL,
        "filename": "DictBDB.json",
        "description": "Full BDB Hebrew Lexicon (Brown-Driver-Briggs)",
        "required": True,
    },
    # Brief Hebrew lexicon (fallback)
    "TBESH": {
        "url": f"{BASE_URL}/Lexicons/TBESH%20-%20Translators%20Brief%20lexicon%20of%20Extended%20Strongs%20for%20Hebrew%20-%20STEPBible.org%20CC%20BY.txt",
        "filename": "TBESH.txt",
        "description": "Hebrew Lexicon - Brief (Extended Strong's)",
        "required": False,
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


# =========================================================================
# BibleAquifer resource downloads
# =========================================================================

# Book number to filename mapping for Aquifer per-book resources
AQUIFER_BOOK_NUMS = list(range(1, 67))  # 01-66

AQUIFER_RESOURCES = {
    "study_notes": {
        "base": f"{AQUIFER_BASE}/AquiferOpenStudyNotes/main/eng/json",
        "dest": "aquifer/study_notes",
        "description": "Tyndale Study Notes",
        "files": [f"{n:02d}.content.json" for n in AQUIFER_BOOK_NUMS],
    },
    "dictionary": {
        "base": f"{AQUIFER_BASE}/AquiferOpenBibleDictionary/main/eng/json",
        "dest": "aquifer/dictionary",
        "description": "Tyndale Bible Dictionary",
        "files": [f"{n:03d}.content.json" for n in range(1, 27)],
    },
    "translation_notes_uw": {
        "base": f"{AQUIFER_BASE}/UWTranslationNotes/main/eng/json",
        "dest": "aquifer/translation_notes_uw",
        "description": "UW Translation Notes",
        "files": [f"{n:02d}.content.json" for n in AQUIFER_BOOK_NUMS],
    },
    "translation_notes_sil": {
        "base": f"{AQUIFER_BASE}/SILOpenTranslatorsNotes/main/eng/json",
        "dest": "aquifer/translation_notes_sil",
        "description": "SIL Translator Notes",
        "files": [f"{n:02d}.content.json" for n in AQUIFER_BOOK_NUMS],
    },
    "key_terms": {
        "base": f"{AQUIFER_BASE}/FIAKeyTerms/main/eng/json",
        "dest": "aquifer/key_terms",
        "description": "FIA Key Terms",
        "files": [f"{n:03d}.content.json" for n in range(1, 23)],
    },
}

ACAI_ENTITY_TYPES = ["people", "places", "groups", "keyterms"]
ACAI_REPO = "BibleAquifer/ACAI"


def download_aquifer(data_dir: Path, force: bool = False) -> bool:
    """Download all BibleAquifer resources."""
    console.print("\n[bold]Downloading BibleAquifer Resources[/bold]")

    timeout = httpx.Timeout(120.0, connect=30.0)
    total_count = 0

    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        for resource_type, info in AQUIFER_RESOURCES.items():
            dest_dir = data_dir / info["dest"]
            dest_dir.mkdir(parents=True, exist_ok=True)

            console.print(f"\n[bold]{info['description']}[/bold] ({resource_type})")

            downloaded = 0
            skipped = 0
            failed = 0

            for filename in info["files"]:
                filepath = dest_dir / filename
                if filepath.exists() and not force:
                    skipped += 1
                    continue

                url = f"{info['base']}/{filename}"
                try:
                    response = client.get(url)
                    if response.status_code == 200:
                        filepath.write_bytes(response.content)
                        downloaded += 1
                    elif response.status_code == 404:
                        # Some books may not be available for all resources
                        pass
                    else:
                        failed += 1
                except Exception:
                    failed += 1

            total_count += downloaded + skipped
            parts = []
            if downloaded:
                parts.append(f"[green]{downloaded} downloaded[/green]")
            if skipped:
                parts.append(f"[dim]{skipped} cached[/dim]")
            if failed:
                parts.append(f"[red]{failed} failed[/red]")
            console.print(f"  {', '.join(parts)}")

    console.print(f"\n[bold]Total Aquifer files: {total_count}[/bold]")
    return True


def download_acai(data_dir: Path, force: bool = False) -> bool:
    """Download ACAI entity annotation files.

    ACAI repo structure: BibleAquifer/ACAI/{entity_type}/json/{EntityName}.json
    """
    console.print("\n[bold]Downloading ACAI Entity Annotations[/bold]")

    timeout = httpx.Timeout(120.0, connect=30.0)
    total_count = 0

    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        for entity_type in ACAI_ENTITY_TYPES:
            dest_dir = data_dir / "acai" / entity_type
            dest_dir.mkdir(parents=True, exist_ok=True)

            console.print(f"\n[bold]{entity_type.title()}[/bold]")

            downloaded = 0
            skipped = 0

            try:
                # GitHub API to list JSON files in {entity_type}/json/
                api_url = f"https://api.github.com/repos/{ACAI_REPO}/contents/{entity_type}/json"
                response = client.get(api_url)
                if response.status_code == 200:
                    files = response.json()
                    json_files = [f for f in files if f["name"].endswith(".json")]
                    for file_info in json_files:
                        filepath = dest_dir / file_info["name"]
                        if filepath.exists() and not force:
                            skipped += 1
                            continue

                        try:
                            dl_url = file_info["download_url"]
                            dl_response = client.get(dl_url)
                            if dl_response.status_code == 200:
                                filepath.write_bytes(dl_response.content)
                                downloaded += 1
                        except Exception:
                            pass

                    total_count += downloaded + skipped
                else:
                    console.print(f"  [yellow]Could not list {entity_type} (HTTP {response.status_code})[/yellow]")
            except Exception as e:
                console.print(f"  [yellow]Error listing {entity_type}: {e}[/yellow]")

            parts = []
            if downloaded:
                parts.append(f"[green]{downloaded} downloaded[/green]")
            if skipped:
                parts.append(f"[dim]{skipped} cached[/dim]")
            if parts:
                console.print(f"  {', '.join(parts)}")

    console.print(f"\n[bold]Total ACAI files: {total_count}[/bold]")
    return True


@click.command()
@click.option("--force", "-f", is_flag=True, help="Re-download even if files exist")
@click.option("--data-dir", "-d", type=click.Path(), help="Data directory (default: ./data)")
@click.option("--aquifer", is_flag=True, help="Also download BibleAquifer and ACAI resources")
def main(force: bool, data_dir: str | None, aquifer: bool):
    """Download STEPBible data files and optional supplementary resources."""
    if data_dir:
        target_dir = Path(data_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
    else:
        target_dir = get_data_dir()

    console.print("[bold blue]Study Bible MCP - Data Downloader[/bold blue]")
    console.print("Data source: STEPBible.org (CC BY 4.0)\n")

    success = download_sync(target_dir, force)

    if aquifer:
        console.print("\nData source: BibleAquifer (CC BY-SA 4.0)")
        aq_success = download_aquifer(target_dir, force)
        acai_success = download_acai(target_dir, force)
        success = success and aq_success and acai_success

    if success:
        console.print("\n[bold green]✓ Download complete![/bold green]")
        console.print(f"\nNext step: Run [bold]python scripts/build_database.py[/bold]")
    else:
        console.print("\n[yellow]Some files failed. Check the URLs or download manually.[/yellow]")
        sys.exit(1)


if __name__ == "__main__":
    main()
