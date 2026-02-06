#!/usr/bin/env python3
"""
Build the Study Bible SQLite database from STEPBible data files.

This script:
1. Reads downloaded STEPBible data files
2. Parses them using the appropriate parsers
3. Inserts the data into a SQLite database
4. Creates indexes for fast lookups
"""

import json
import sqlite3
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from study_bible_mcp.database import create_schema
from study_bible_mcp.parsers.lexicon import parse_greek_lexicon, parse_hebrew_lexicon
from study_bible_mcp.parsers.tagged_text import parse_tagnt, parse_tahot, parse_morphology_codes
from study_bible_mcp.parsers.proper_names import parse_tipnr

console = Console()


def get_paths():
    """Get data and db directory paths."""
    script_dir = Path(__file__).parent
    project_dir = script_dir.parent

    data_dir = project_dir / "data"
    db_dir = project_dir / "db"

    return data_dir, db_dir


def find_tagnt_files(data_dir: Path) -> list[Path]:
    """Find all TAGNT files (may be split into parts)."""
    files = []
    # Check for single file first
    single = data_dir / "TAGNT.txt"
    if single.exists():
        return [single]
    # Check for split files
    for pattern in ["TAGNT_Mat-Jhn.txt", "TAGNT_Act-Rev.txt"]:
        path = data_dir / pattern
        if path.exists():
            files.append(path)
    return files


def find_tahot_files(data_dir: Path) -> list[Path]:
    """Find all TAHOT files (may be split into parts)."""
    files = []
    # Check for single file first
    single = data_dir / "TAHOT.txt"
    if single.exists():
        return [single]
    # Check for split files
    for pattern in ["TAHOT_Gen-Deu.txt", "TAHOT_Jos-Est.txt", "TAHOT_Job-Sng.txt", "TAHOT_Isa-Mal.txt"]:
        path = data_dir / pattern
        if path.exists():
            files.append(path)
    return files


def build_database(data_dir: Path, db_path: Path, rebuild: bool = False):
    """Build the complete database from STEPBible files."""

    # Check if data files exist
    required_files = ["TBESG.txt", "TBESH.txt"]  # Minimum required

    missing_required = [f for f in required_files if not (data_dir / f).exists()]
    if missing_required:
        console.print(f"[red]Error: Missing required files: {missing_required}[/red]")
        console.print("Run [bold]python scripts/download_stepbible.py[/bold] first.")
        return False

    # Create or recreate database
    if db_path.exists():
        if rebuild:
            console.print(f"[yellow]Removing existing database: {db_path}[/yellow]")
            db_path.unlink()
        else:
            console.print(f"[yellow]Database exists. Use --rebuild to recreate.[/yellow]")
            return True

    db_path.parent.mkdir(parents=True, exist_ok=True)

    console.print(f"\n[bold]Building database: {db_path}[/bold]\n")

    conn = sqlite3.connect(db_path)

    try:
        # Create schema
        console.print("Creating schema...")
        create_schema(conn)

        # Import Greek lexicon
        tbesg_path = data_dir / "TBESG.txt"
        if tbesg_path.exists():
            import_lexicon(conn, tbesg_path, "greek", "TBESG")

        # Import Hebrew lexicon
        tbesh_path = data_dir / "TBESH.txt"
        if tbesh_path.exists():
            import_lexicon(conn, tbesh_path, "hebrew", "TBESH")

        # Import Greek NT (may be split into multiple files)
        tagnt_files = find_tagnt_files(data_dir)
        for tagnt_path in tagnt_files:
            import_verses(conn, tagnt_path, "tagnt", tagnt_path.stem)

        # Import Hebrew OT (may be split into multiple files)
        tahot_files = find_tahot_files(data_dir)
        for tahot_path in tahot_files:
            import_verses(conn, tahot_path, "tahot", tahot_path.stem)

        # Import proper names
        tipnr_path = data_dir / "TIPNR.txt"
        if tipnr_path.exists():
            import_names(conn, tipnr_path, "TIPNR")

        # Import morphology codes
        tegmc_path = data_dir / "TEGMC.txt"
        if tegmc_path.exists():
            import_morphology(conn, tegmc_path, "greek", "TEGMC")

        tehmc_path = data_dir / "TEHMC.txt"
        if tehmc_path.exists():
            import_morphology(conn, tehmc_path, "hebrew", "TEHMC")

        # Build passages from section markers
        build_passages(conn)

        # Add built-in cross-references
        import_builtin_crossrefs(conn)

        # Optimize
        console.print("\nOptimizing database...")
        conn.execute("ANALYZE")
        conn.execute("VACUUM")
        conn.commit()

        # Show stats
        show_stats(conn)

        console.print("\n[bold green]✓ Database built successfully![/bold green]")
        return True

    except Exception as e:
        console.print(f"[red]Error building database: {e}[/red]")
        import traceback
        traceback.print_exc()
        return False

    finally:
        conn.close()


def import_lexicon(conn: sqlite3.Connection, filepath: Path, language: str, name: str):
    """Import a lexicon file into the database."""
    console.print(f"Importing {name} ({language} lexicon)...")

    if language == "greek":
        parser = parse_greek_lexicon
    else:
        parser = parse_hebrew_lexicon

    count = 0
    batch = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed} entries"),
        console=console,
    ) as progress:
        task = progress.add_task(f"  {name}", total=None)

        for entry in parser(filepath):
            batch.append((
                entry['strongs'],
                entry['language'],
                entry['word'],
                entry['transliteration'],
                entry.get('pronunciation', ''),
                entry['short_definition'],
                entry.get('full_definition', ''),
                entry.get('etymology', ''),
                entry.get('usage_count', 0),
                entry.get('semantic_domain', '[]'),
                entry.get('related_words', '[]'),
            ))

            count += 1

            if len(batch) >= 1000:
                conn.executemany("""
                    INSERT OR REPLACE INTO lexicon
                    (strongs, language, word, transliteration, pronunciation,
                     short_definition, full_definition, etymology, usage_count,
                     semantic_domain, related_words)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, batch)
                conn.commit()
                batch = []
                progress.update(task, completed=count)

        # Insert remaining
        if batch:
            conn.executemany("""
                INSERT OR REPLACE INTO lexicon
                (strongs, language, word, transliteration, pronunciation,
                 short_definition, full_definition, etymology, usage_count,
                 semantic_domain, related_words)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, batch)
            conn.commit()

        progress.update(task, completed=count)

    console.print(f"  [green]✓[/green] Imported {count} entries")


def import_verses(conn: sqlite3.Connection, filepath: Path, parser_type: str, name: str):
    """Import tagged Bible text into the database."""
    console.print(f"Importing {name} (tagged text)...")

    if parser_type == "tagnt":
        parser = parse_tagnt
    else:
        parser = parse_tahot

    count = 0
    batch = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed} verses"),
        console=console,
    ) as progress:
        task = progress.add_task(f"  {name}", total=None)

        for verse in parser(filepath):
            batch.append((
                verse['reference'],
                verse['book'],
                verse['chapter'],
                verse['verse'],
                verse['text_english'],
                verse['text_original'],
                verse['word_data'],
                verse.get('section_end'),  # New column for section markers
            ))

            count += 1

            if len(batch) >= 500:
                conn.executemany("""
                    INSERT OR REPLACE INTO verses
                    (reference, book, chapter, verse, text_english, text_original, word_data, section_end)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, batch)
                conn.commit()
                batch = []
                progress.update(task, completed=count)

        if batch:
            conn.executemany("""
                INSERT OR REPLACE INTO verses
                (reference, book, chapter, verse, text_english, text_original, word_data, section_end)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, batch)
            conn.commit()

        progress.update(task, completed=count)

    console.print(f"  [green]✓[/green] Imported {count} verses")


def import_names(conn: sqlite3.Connection, filepath: Path, name: str):
    """Import proper names into the database."""
    console.print(f"Importing {name} (proper names)...")

    count = 0
    batch = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed} names"),
        console=console,
    ) as progress:
        task = progress.add_task(f"  {name}", total=None)

        for entry in parse_tipnr(filepath):
            batch.append((
                entry['name'],
                entry['name_original'],
                entry['type'],
                entry['description'],
                entry.get('references', '[]'),
                entry.get('relationships', '{}'),
            ))

            count += 1

            if len(batch) >= 500:
                conn.executemany("""
                    INSERT INTO names
                    (name, name_original, type, description, refs, relationships)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, batch)
                conn.commit()
                batch = []
                progress.update(task, completed=count)

        if batch:
            conn.executemany("""
                INSERT INTO names
                (name, name_original, type, description, refs, relationships)
                VALUES (?, ?, ?, ?, ?, ?)
            """, batch)
            conn.commit()

        progress.update(task, completed=count)

    console.print(f"  [green]✓[/green] Imported {count} names")


def import_morphology(conn: sqlite3.Connection, filepath: Path, language: str, name: str):
    """Import morphology code expansions."""
    console.print(f"Importing {name} (morphology codes)...")

    count = 0
    batch = []

    for entry in parse_morphology_codes(filepath, language):
        batch.append((
            entry['code'],
            entry['language'],
            entry['parsing'],
            entry['part_of_speech'],
            entry.get('person', ''),
            entry.get('number', ''),
            entry.get('tense', ''),
            entry.get('voice', ''),
            entry.get('mood', ''),
            entry.get('case_value', ''),
            entry.get('gender', ''),
        ))
        count += 1

    if batch:
        conn.executemany("""
            INSERT OR REPLACE INTO morphology
            (code, language, parsing, part_of_speech, person, number,
             tense, voice, mood, case_value, gender)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, batch)
        conn.commit()

    console.print(f"  [green]✓[/green] Imported {count} codes")


def build_passages(conn: sqlite3.Connection):
    """Build passages table by grouping verses based on section markers."""
    console.print("Building passages from section markers...")

    # Get all verses ordered by book order, chapter, verse
    # We need to maintain book order (Gen-Mal for OT, Mat-Rev for NT)
    cursor = conn.execute("""
        SELECT id, reference, book, chapter, verse, text_english, section_end
        FROM verses
        ORDER BY id
    """)
    verses = cursor.fetchall()

    if not verses:
        console.print("  [yellow]No verses found[/yellow]")
        return

    passages = []
    current_passage_start = None
    current_passage_verses = []
    current_book = None

    for verse in verses:
        verse_id, reference, book, chapter, verse_num, text_english, section_end = verse

        # If we're starting a new book, close the previous passage
        if current_book is not None and book != current_book:
            if current_passage_verses:
                passages.append(build_passage_entry(current_passage_verses, None))
            current_passage_verses = []
            current_passage_start = None

        current_book = book

        # Add verse to current passage
        current_passage_verses.append({
            'id': verse_id,
            'reference': reference,
            'book': book,
            'chapter': chapter,
            'verse': verse_num,
            'text_english': text_english,
            'section_end': section_end,
        })

        # If this verse ends a section, close the passage
        if section_end:
            if current_passage_verses:
                passages.append(build_passage_entry(current_passage_verses, section_end))
            current_passage_verses = []

    # Don't forget the last passage if it didn't end with a marker
    if current_passage_verses:
        passages.append(build_passage_entry(current_passage_verses, None))

    # Insert passages
    count = 0
    batch = []
    for p in passages:
        batch.append((
            p['reference_start'],
            p['reference_end'],
            p['book'],
            p['start_verse_id'],
            p['end_verse_id'],
            p['text_combined'],
            p['verse_count'],
            p['section_type'],
        ))
        count += 1

        if len(batch) >= 500:
            conn.executemany("""
                INSERT INTO passages
                (reference_start, reference_end, book, start_verse_id, end_verse_id,
                 text_combined, verse_count, section_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, batch)
            conn.commit()
            batch = []

    if batch:
        conn.executemany("""
            INSERT INTO passages
            (reference_start, reference_end, book, start_verse_id, end_verse_id,
             text_combined, verse_count, section_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, batch)
        conn.commit()

    console.print(f"  [green]✓[/green] Built {count} passages")


def build_passage_entry(verses: list[dict], section_type: str | None) -> dict:
    """Build a passage entry from a list of verses."""
    if not verses:
        raise ValueError("Cannot build passage from empty verse list")

    first = verses[0]
    last = verses[-1]

    # Combine all verse texts
    text_combined = ' '.join(v['text_english'] for v in verses if v.get('text_english'))

    return {
        'reference_start': first['reference'],
        'reference_end': last['reference'],
        'book': first['book'],
        'start_verse_id': first['id'],
        'end_verse_id': last['id'],
        'text_combined': text_combined,
        'verse_count': len(verses),
        'section_type': section_type,
    }


def import_builtin_crossrefs(conn: sqlite3.Connection):
    """Import built-in thematic cross-references."""
    console.print("Adding thematic cross-references...")

    # These are the key theological themes with their reference chains
    themes = {
        "salvation_by_grace": [
            ("Genesis 15:6", "Abraham believed, credited as righteousness"),
            ("Romans 3:21-26", "Righteousness through faith in Christ"),
            ("Ephesians 2:8-9", "Saved by grace through faith"),
            ("Titus 3:5-7", "Not by works of righteousness"),
        ],
        "deity_of_christ": [
            ("John 1:1-3", "The Word was God"),
            ("John 8:58", "Before Abraham was, I AM"),
            ("Colossians 2:9", "Fullness of deity bodily"),
            ("Hebrews 1:3", "Exact imprint of His nature"),
        ],
        "atonement": [
            ("Isaiah 53:4-6", "He bore our griefs"),
            ("Romans 3:25", "Propitiation by His blood"),
            ("2 Corinthians 5:21", "Made sin for us"),
            ("1 Peter 2:24", "Bore our sins in His body"),
        ],
        "resurrection": [
            ("Psalm 16:10", "Will not abandon soul to Sheol"),
            ("1 Corinthians 15:3-8", "He was raised, appearances"),
            ("1 Corinthians 15:20-23", "Firstfruits of those who sleep"),
        ],
        "holy_spirit": [
            ("Joel 2:28-29", "Pour out Spirit on all flesh"),
            ("John 14:16-17", "Another Helper, Spirit of truth"),
            ("Romans 8:9-11", "Spirit dwells in you"),
            ("Galatians 5:22-23", "Fruit of the Spirit"),
        ],
        "justification": [
            ("Romans 3:24-26", "Justified freely by grace"),
            ("Romans 5:1", "Justified by faith, peace with God"),
            ("Galatians 2:16", "Justified by faith in Christ"),
        ],
    }

    count = 0
    for theme, refs in themes.items():
        for ref, note in refs:
            conn.execute("""
                INSERT INTO thematic_references (theme, reference, note)
                VALUES (?, ?, ?)
            """, (theme, ref, note))
            count += 1

    conn.commit()
    console.print(f"  [green]✓[/green] Added {count} thematic references")


def show_stats(conn: sqlite3.Connection):
    """Show database statistics."""
    console.print("\n[bold]Database Statistics:[/bold]")

    tables = ["lexicon", "verses", "passages", "names", "morphology", "thematic_references"]

    for table in tables:
        cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")
        count = cursor.fetchone()[0]
        console.print(f"  {table}: {count:,} rows")

    # Database size
    cursor = conn.execute("SELECT page_count * page_size FROM pragma_page_count(), pragma_page_size()")
    size = cursor.fetchone()[0]
    console.print(f"\n  Total size: {size / (1024*1024):.1f} MB")


@click.command()
@click.option("--rebuild", "-r", is_flag=True, help="Rebuild database from scratch")
@click.option("--data-dir", "-d", type=click.Path(exists=True), help="Data directory")
@click.option("--db-path", "-o", type=click.Path(), help="Output database path")
def main(rebuild: bool, data_dir: str | None, db_path: str | None):
    """Build the Study Bible database from STEPBible data."""
    console.print("[bold blue]Study Bible MCP - Database Builder[/bold blue]")

    default_data_dir, default_db_dir = get_paths()

    data_path = Path(data_dir) if data_dir else default_data_dir
    output_path = Path(db_path) if db_path else (default_db_dir / "study_bible.db")

    success = build_database(data_path, output_path, rebuild)

    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
