#!/usr/bin/env python3
"""
Import Theographic Bible Metadata into the Study Bible database.

Downloads CSV files from https://github.com/robertrouse/theographic-bible-metadata
and populates graph tables for people, places, events, and their relationships.
"""

import sqlite3
import sys
from pathlib import Path

import click
import httpx
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from study_bible_mcp.parsers.theographic import TABLE_COLUMNS, build_graph  # noqa: E402

console = Console()

BASE_URL = "https://raw.githubusercontent.com/robertrouse/theographic-bible-metadata/master/CSV"

CSV_FILES = [
    "People.csv",
    "Places.csv",
    "Events.csv",
    "PeopleGroups.csv",
]


def download_csv(filename: str, data_dir: Path) -> Path:
    """Download a CSV file from the Theographic repository."""
    url = f"{BASE_URL}/{filename}"
    dest = data_dir / filename

    if dest.exists():
        console.print(f"  [dim]Using cached {filename}[/dim]")
        return dest

    console.print(f"  Downloading {filename}...")
    response = httpx.get(url, follow_redirects=True, timeout=60)
    response.raise_for_status()
    dest.write_bytes(response.content)
    return dest


def ensure_graph_columns(conn: sqlite3.Connection) -> None:
    """Add the graph_people columns that databases built before them lack."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(graph_people)")}
    for column in ("display_title", "surname"):
        if column not in columns:
            conn.execute(f"ALTER TABLE graph_people ADD COLUMN {column} TEXT")


def import_graph(conn: sqlite3.Connection, csv_dir: Path) -> dict[str, int]:
    """Replace every graph table's rows with those built from the CSVs in csv_dir.

    build_graph applies the curated corrections and supplementary events of
    src/study_bible_mcp/parsers/graph_curated.json and computes each event's
    chronological sort_key. Returns the rows written per table.
    """
    tables = build_graph(csv_dir)
    ensure_graph_columns(conn)
    for table, rows in tables.items():
        columns = TABLE_COLUMNS[table]
        conn.execute(f"DELETE FROM {table}")
        conn.executemany(
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
            rows,
        )
    conn.commit()
    return {table: len(rows) for table, rows in tables.items()}


def show_graph_stats(conn: sqlite3.Connection):
    """Show graph data statistics."""
    console.print("\n[bold]Graph Data Statistics:[/bold]")

    tables = {
        "graph_people": "People",
        "graph_places": "Places",
        "graph_events": "Events",
        "graph_family_edges": "Family relationships",
        "graph_person_event_edges": "Person-event links",
        "graph_event_place_edges": "Event-place links",
        "graph_verse_mentions": "Verse mentions",
        "graph_person_group_edges": "Group memberships",
    }

    for table, label in tables.items():
        try:
            cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")
            row_count = cursor.fetchone()[0]
            console.print(f"  {label}: {row_count:,}")
        except Exception:
            console.print(f"  {label}: [dim]table not found[/dim]")


@click.command()
@click.option("--db-path", "-d", type=click.Path(), help="Path to database")
@click.option("--data-dir", type=click.Path(), help="Directory for downloaded CSVs")
@click.option("--skip-download", is_flag=True, help="Skip downloading (use cached)")
def main(db_path: str | None, data_dir: str | None, skip_download: bool):
    """Import Theographic Bible Metadata into the Study Bible database."""
    console.print("[bold blue]Study Bible MCP - Theographic Graph Import[/bold blue]\n")

    # Resolve paths
    script_dir = Path(__file__).parent
    project_dir = script_dir.parent

    db_file = Path(db_path) if db_path else (project_dir / "db" / "study_bible.db")
    csv_dir = Path(data_dir) if data_dir else (project_dir / "data" / "theographic")
    csv_dir.mkdir(parents=True, exist_ok=True)

    if not db_file.exists():
        console.print(f"[red]Database not found: {db_file}[/red]")
        console.print("Run [bold]python scripts/build_database.py[/bold] first.")
        sys.exit(1)

    # Download CSV files
    if not skip_download:
        console.print("Downloading Theographic CSV files...")
        for filename in CSV_FILES:
            download_csv(filename, csv_dir)
        console.print()

    # Verify files exist
    for filename in CSV_FILES:
        if not (csv_dir / filename).exists():
            console.print(f"[red]Missing: {csv_dir / filename}[/red]")
            sys.exit(1)

    conn = sqlite3.connect(db_file)

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Importing people, places and events...", total=None)
            counts = import_graph(conn, csv_dir)
            progress.update(
                task,
                description="[green]✓[/green] Imported "
                + ", ".join(f"{count} {table}" for table, count in counts.items()),
            )

        # Optimize
        console.print("\nOptimizing...")
        conn.execute("ANALYZE")
        conn.commit()

        show_graph_stats(conn)
        console.print("\n[bold green]✓ Theographic import complete![/bold green]")

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    finally:
        conn.close()


if __name__ == "__main__":
    main()
