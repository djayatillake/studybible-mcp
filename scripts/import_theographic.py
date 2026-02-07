#!/usr/bin/env python3
"""
Import Theographic Bible Metadata into the Study Bible database.

Downloads CSV files from https://github.com/robertrouse/theographic-bible-metadata
and populates graph tables for people, places, events, and their relationships.
"""

import csv
import io
import sqlite3
import sys
from pathlib import Path

import click
import httpx
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

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


def parse_csv(filepath: Path) -> list[dict]:
    """Parse a CSV file into a list of dicts."""
    with open(filepath, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return list(reader)


def split_field(value: str) -> list[str]:
    """Split a comma-separated field into a list, filtering empties."""
    if not value or not value.strip():
        return []
    return [v.strip() for v in value.split(",") if v.strip()]


def safe_int(value: str) -> int | None:
    """Convert string to int, returning None on failure."""
    if not value or not value.strip():
        return None
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None


def safe_float(value: str) -> float | None:
    """Convert string to float, returning None on failure."""
    if not value or not value.strip():
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def import_people(conn: sqlite3.Connection, filepath: Path) -> int:
    """Import people from People.csv."""
    rows = parse_csv(filepath)
    count = 0
    batch = []

    for row in rows:
        person_id = row.get("personLookup", "").strip()
        if not person_id:
            continue

        name = row.get("name", "").strip() or row.get("displayTitle", "").strip()
        if not name:
            continue

        batch.append((
            person_id,
            name,
            row.get("alsoCalled", "").strip() or None,
            row.get("gender", "").strip() or None,
            safe_int(row.get("birthYear", "")),
            safe_int(row.get("deathYear", "")),
            row.get("birthPlace", "").strip() or None,
            row.get("deathPlace", "").strip() or None,
            row.get("dictText", "").strip() or None,
        ))
        count += 1

    if batch:
        conn.executemany("""
            INSERT OR REPLACE INTO graph_people
            (id, name, also_called, gender, birth_year, death_year,
             birth_place_id, death_place_id, description)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, batch)
        conn.commit()

    return count


def import_family_edges(conn: sqlite3.Connection, filepath: Path) -> int:
    """Import family relationships from People.csv."""
    rows = parse_csv(filepath)
    count = 0
    batch = []

    for row in rows:
        person_id = row.get("personLookup", "").strip()
        if not person_id:
            continue

        # Father relationship: father column contains father's ID
        father = row.get("father", "").strip()
        if father:
            for fid in split_field(father):
                batch.append((fid, person_id, "father_of"))
                count += 1

        # Mother relationship
        mother = row.get("mother", "").strip()
        if mother:
            for mid in split_field(mother):
                batch.append((mid, person_id, "mother_of"))
                count += 1

        # Partner relationships
        for partner_id in split_field(row.get("partners", "")):
            batch.append((person_id, partner_id, "partner_of"))
            count += 1

        # Sibling relationships
        for sibling_id in split_field(row.get("siblings", "")):
            # Only add one direction to avoid duplicates
            if person_id < sibling_id:
                batch.append((person_id, sibling_id, "sibling_of"))
                count += 1

        if len(batch) >= 1000:
            conn.executemany("""
                INSERT OR IGNORE INTO graph_family_edges
                (from_person_id, to_person_id, relationship_type)
                VALUES (?, ?, ?)
            """, batch)
            conn.commit()
            batch = []

    if batch:
        conn.executemany("""
            INSERT OR IGNORE INTO graph_family_edges
            (from_person_id, to_person_id, relationship_type)
            VALUES (?, ?, ?)
        """, batch)
        conn.commit()

    return count


def import_places(conn: sqlite3.Connection, filepath: Path) -> int:
    """Import places from Places.csv."""
    rows = parse_csv(filepath)
    count = 0
    batch = []

    for row in rows:
        place_id = row.get("placeLookup", "").strip()
        if not place_id:
            continue

        name = row.get("displayTitle", "").strip() or row.get("kjvName", "").strip()
        if not name:
            continue

        # Prefer openBible coords, fall back to recogito
        lat = safe_float(row.get("openBibleLat", "")) or safe_float(row.get("latitude", ""))
        lon = safe_float(row.get("openBibleLong", "")) or safe_float(row.get("longitude", ""))

        batch.append((
            place_id,
            name,
            lat,
            lon,
            row.get("featureType", "").strip() or None,
        ))
        count += 1

    if batch:
        conn.executemany("""
            INSERT OR REPLACE INTO graph_places
            (id, name, latitude, longitude, feature_type)
            VALUES (?, ?, ?, ?, ?)
        """, batch)
        conn.commit()

    return count


def import_events(conn: sqlite3.Connection, filepath: Path) -> int:
    """Import events from Events.csv."""
    rows = parse_csv(filepath)
    count = 0
    batch = []

    for row in rows:
        event_id = row.get("eventID", "").strip()
        if not event_id:
            continue

        title = row.get("title", "").strip()
        if not title:
            continue

        batch.append((
            event_id,
            title,
            safe_int(row.get("startDate", "")),
            row.get("duration", "").strip() or None,
            safe_float(row.get("sortKey", "")),
        ))
        count += 1

    if batch:
        conn.executemany("""
            INSERT OR REPLACE INTO graph_events
            (id, title, start_year, duration, sort_key)
            VALUES (?, ?, ?, ?, ?)
        """, batch)
        conn.commit()

    return count


def import_event_edges(conn: sqlite3.Connection, filepath: Path) -> tuple[int, int]:
    """Import event-person and event-place edges from Events.csv."""
    rows = parse_csv(filepath)
    person_count = 0
    place_count = 0
    person_batch = []
    place_batch = []

    for row in rows:
        event_id = row.get("eventID", "").strip()
        if not event_id:
            continue

        # Person-event edges
        for person_id in split_field(row.get("participants", "")):
            person_batch.append((person_id, event_id))
            person_count += 1

        # Event-place edges
        for place_id in split_field(row.get("locations", "")):
            place_batch.append((event_id, place_id))
            place_count += 1

        if len(person_batch) >= 1000:
            conn.executemany(
                "INSERT OR IGNORE INTO graph_person_event_edges (person_id, event_id) VALUES (?, ?)",
                person_batch
            )
            conn.commit()
            person_batch = []

        if len(place_batch) >= 1000:
            conn.executemany(
                "INSERT OR IGNORE INTO graph_event_place_edges (event_id, place_id) VALUES (?, ?)",
                place_batch
            )
            conn.commit()
            place_batch = []

    if person_batch:
        conn.executemany(
            "INSERT OR IGNORE INTO graph_person_event_edges (person_id, event_id) VALUES (?, ?)",
            person_batch
        )
        conn.commit()

    if place_batch:
        conn.executemany(
            "INSERT OR IGNORE INTO graph_event_place_edges (event_id, place_id) VALUES (?, ?)",
            place_batch
        )
        conn.commit()

    return person_count, place_count


def import_verse_mentions(
    conn: sqlite3.Connection,
    people_path: Path,
    events_path: Path,
    places_path: Path,
) -> int:
    """Build verse-entity mention links from all CSV sources."""
    count = 0
    batch = []

    # Person mentions from People.csv
    for row in parse_csv(people_path):
        person_id = row.get("personLookup", "").strip()
        if not person_id:
            continue
        for verse_ref in split_field(row.get("verses", "")):
            batch.append((verse_ref, "person", person_id))
            count += 1

    # Event mentions from Events.csv
    for row in parse_csv(events_path):
        event_id = row.get("eventID", "").strip()
        if not event_id:
            continue
        for verse_ref in split_field(row.get("verses", "")):
            batch.append((verse_ref, "event", event_id))
            count += 1

    # Place mentions from Places.csv
    for row in parse_csv(places_path):
        place_id = row.get("placeLookup", "").strip()
        if not place_id:
            continue
        for verse_ref in split_field(row.get("verses", "")):
            batch.append((verse_ref, "place", place_id))
            count += 1

    # Batch insert
    chunk_size = 5000
    for i in range(0, len(batch), chunk_size):
        chunk = batch[i:i + chunk_size]
        conn.executemany("""
            INSERT OR IGNORE INTO graph_verse_mentions
            (verse_ref, entity_type, entity_id)
            VALUES (?, ?, ?)
        """, chunk)
        conn.commit()

    return count


def import_people_groups(conn: sqlite3.Connection, filepath: Path) -> int:
    """Import people groups and membership edges."""
    rows = parse_csv(filepath)
    count = 0
    group_batch = []
    member_batch = []

    for row in rows:
        group_name = row.get("groupName", "").strip()
        if not group_name:
            continue

        members_str = row.get("members", "").strip()
        group_batch.append((group_name, members_str))

        for member_id in split_field(members_str):
            member_batch.append((member_id, group_name))
            count += 1

    if group_batch:
        conn.executemany(
            "INSERT OR REPLACE INTO graph_people_groups (name, members) VALUES (?, ?)",
            group_batch
        )

    if member_batch:
        conn.executemany(
            "INSERT OR IGNORE INTO graph_person_group_edges (person_id, group_name) VALUES (?, ?)",
            member_batch
        )

    conn.commit()
    return count


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
        people_path = csv_dir / "People.csv"
        places_path = csv_dir / "Places.csv"
        events_path = csv_dir / "Events.csv"
        groups_path = csv_dir / "PeopleGroups.csv"

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Importing people...", total=None)
            count = import_people(conn, people_path)
            progress.update(task, description=f"[green]✓[/green] Imported {count} people")

            task = progress.add_task("Importing family relationships...", total=None)
            count = import_family_edges(conn, people_path)
            progress.update(task, description=f"[green]✓[/green] Imported {count} family edges")

            task = progress.add_task("Importing places...", total=None)
            count = import_places(conn, places_path)
            progress.update(task, description=f"[green]✓[/green] Imported {count} places")

            task = progress.add_task("Importing events...", total=None)
            count = import_events(conn, events_path)
            progress.update(task, description=f"[green]✓[/green] Imported {count} events")

            task = progress.add_task("Importing event edges...", total=None)
            person_edges, place_edges = import_event_edges(conn, events_path)
            progress.update(task, description=f"[green]✓[/green] Imported {person_edges} person-event + {place_edges} event-place edges")

            task = progress.add_task("Building verse mentions...", total=None)
            count = import_verse_mentions(conn, people_path, events_path, places_path)
            progress.update(task, description=f"[green]✓[/green] Built {count} verse-entity mentions")

            task = progress.add_task("Importing people groups...", total=None)
            count = import_people_groups(conn, groups_path)
            progress.update(task, description=f"[green]✓[/green] Imported {count} group memberships")

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
