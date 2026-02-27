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
from study_bible_mcp.parsers.lexicon import (
    parse_greek_lexicon, parse_hebrew_lexicon,
    parse_tflsj_lexicon, parse_bdb_lexicon,
    parse_abbott_smith,
)
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

    # Check if data files exist - need at least one Greek and one Hebrew lexicon
    has_greek = (data_dir / "TFLSJ_0-5624.txt").exists() or (data_dir / "TBESG.txt").exists()
    has_hebrew = (data_dir / "DictBDB.json").exists() or (data_dir / "TBESH.txt").exists()

    if not has_greek or not has_hebrew:
        missing = []
        if not has_greek:
            missing.append("Greek lexicon (TFLSJ or TBESG)")
        if not has_hebrew:
            missing.append("Hebrew lexicon (BDB or TBESH)")
        console.print(f"[red]Error: Missing required files: {missing}[/red]")
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

        # Import Greek lexicon: prefer TFLSJ (Full LSJ), fall back to TBESG
        tflsj_path = data_dir / "TFLSJ_0-5624.txt"
        tflsj_extra_path = data_dir / "TFLSJ_extra.txt"
        tbesg_path = data_dir / "TBESG.txt"

        if tflsj_path.exists():
            import_lexicon_tflsj(conn, tflsj_path, "TFLSJ (0-5624)")
            if tflsj_extra_path.exists():
                import_lexicon_tflsj(conn, tflsj_extra_path, "TFLSJ (extra)")
        elif tbesg_path.exists():
            import_lexicon(conn, tbesg_path, "greek", "TBESG")

        # Import Hebrew lexicon: prefer BDB, fall back to TBESH
        bdb_path = data_dir / "DictBDB.json"
        tbesh_path = data_dir / "TBESH.txt"

        if bdb_path.exists():
            import_lexicon_bdb(conn, bdb_path, "BDB")
        elif tbesh_path.exists():
            import_lexicon(conn, tbesh_path, "hebrew", "TBESH")

        # Import Abbott-Smith Greek lexicon (enriches existing Greek entries)
        abbott_smith_path = data_dir / "abbott-smith.tei.xml"
        if abbott_smith_path.exists():
            import_lexicon_abbott_smith(conn, abbott_smith_path, "Abbott-Smith")

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

        # Import Aquifer content (study notes, dictionary, translation notes, key terms)
        aquifer_dir = data_dir / "aquifer"
        if aquifer_dir.exists():
            import_aquifer_content(conn, aquifer_dir)

        # Import ACAI entity annotations
        acai_dir = data_dir / "acai"
        if acai_dir.exists():
            import_acai_entities(conn, acai_dir)

        # Import ANE context data
        ane_dir = data_dir / "ane_context"
        if ane_dir.exists():
            import_ane_context(conn, ane_dir)

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


def import_lexicon_tflsj(conn: sqlite3.Connection, filepath: Path, name: str):
    """Import a TFLSJ (Full LSJ) Greek lexicon file into the database."""
    console.print(f"Importing {name} (Full LSJ Greek lexicon)...")

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

        for entry in parse_tflsj_lexicon(filepath):
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


def import_lexicon_bdb(conn: sqlite3.Connection, filepath: Path, name: str):
    """Import the BDB Hebrew lexicon JSON file into the database."""
    console.print(f"Importing {name} (Full BDB Hebrew lexicon)...")

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

        for entry in parse_bdb_lexicon(filepath):
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


def import_lexicon_abbott_smith(conn: sqlite3.Connection, filepath: Path, name: str):
    """Import Abbott-Smith Greek Lexicon (TEI XML) as enrichment of existing entries.

    Phase 1: UPDATE existing rows (entries with Strong's numbers) to add
    Abbott-Smith columns without overwriting LSJ data.
    Phase 2: INSERT new entries for words without Strong's numbers using
    synthetic AS_ keys.
    """
    console.print(f"Importing {name} (Abbott-Smith Greek Lexicon)...")

    updated = 0
    inserted = 0
    skipped = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed} entries"),
        console=console,
    ) as progress:
        task = progress.add_task(f"  {name}", total=None)

        for entry in parse_abbott_smith(filepath):
            strongs = entry["strongs"]

            if strongs.startswith("AS_"):
                # Phase 2: INSERT entries without Strong's numbers
                conn.execute("""
                    INSERT OR REPLACE INTO lexicon
                    (strongs, language, word, short_definition, full_definition,
                     abbott_smith_def, nt_occurrences, lxx_hebrew, synonyms, sense_hierarchy)
                    VALUES (?, 'greek', ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    strongs,
                    entry["word"],
                    entry["short_definition"],
                    entry["abbott_smith_def"],  # Use AS def as full_definition too
                    entry["abbott_smith_def"],
                    entry["nt_occurrences"],
                    entry["lxx_hebrew"],
                    entry["synonyms"],
                    entry["sense_hierarchy"],
                ))
                inserted += 1
            else:
                # Phase 1: UPDATE existing rows to add Abbott-Smith data
                cursor = conn.execute("""
                    UPDATE lexicon SET
                        abbott_smith_def = ?,
                        nt_occurrences = ?,
                        lxx_hebrew = ?,
                        synonyms = ?,
                        sense_hierarchy = ?
                    WHERE strongs = ?
                """, (
                    entry["abbott_smith_def"],
                    entry["nt_occurrences"],
                    entry["lxx_hebrew"],
                    entry["synonyms"],
                    entry["sense_hierarchy"],
                    strongs,
                ))
                if cursor.rowcount > 0:
                    updated += 1
                else:
                    skipped += 1

            total = updated + inserted + skipped
            if total % 500 == 0:
                conn.commit()
                progress.update(task, completed=total)

        conn.commit()
        progress.update(task, completed=updated + inserted + skipped)

    console.print(f"  [green]✓[/green] Updated {updated} existing entries, inserted {inserted} new entries"
                  + (f", skipped {skipped} unmatched" if skipped else ""))


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


def import_aquifer_content(conn: sqlite3.Connection, aquifer_dir: Path):
    """Import all BibleAquifer content (study notes, dictionary, etc.)."""
    from study_bible_mcp.parsers.aquifer import parse_aquifer_content_file

    resource_types = {
        "study_notes": "study_notes",
        "dictionary": "dictionary",
        "translation_notes_uw": "translation_notes_uw",
        "translation_notes_sil": "translation_notes_sil",
        "key_terms": "key_terms",
    }

    for subdir, resource_type in resource_types.items():
        dir_path = aquifer_dir / subdir
        if not dir_path.exists():
            continue

        json_files = sorted(dir_path.glob("*.json"))
        if not json_files:
            continue

        console.print(f"Importing Aquifer {subdir} ({len(json_files)} files)...")
        count = 0
        batch = []

        for json_file in json_files:
            # Extract book number from filename if applicable (e.g., "01.content.json" -> 1)
            book_num = None
            name_parts = json_file.stem.split(".")
            if name_parts[0].isdigit():
                book_num = int(name_parts[0])

            try:
                for entry in parse_aquifer_content_file(json_file, resource_type, book_num):
                    batch.append((
                        entry['content_id'],
                        entry['resource_type'],
                        entry['title'],
                        entry.get('book'),
                        entry.get('book_num'),
                        entry.get('start_ref'),
                        entry.get('end_ref'),
                        entry.get('chapter_start'),
                        entry.get('verse_start'),
                        entry.get('chapter_end'),
                        entry.get('verse_end'),
                        entry['content'],
                        entry['content_plain'],
                        entry.get('is_range', 0),
                    ))
                    count += 1

                    if len(batch) >= 500:
                        conn.executemany("""
                            INSERT OR REPLACE INTO aquifer_content
                            (content_id, resource_type, title, book, book_num,
                             start_ref, end_ref, chapter_start, verse_start,
                             chapter_end, verse_end, content, content_plain, is_range)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, batch)
                        conn.commit()
                        batch = []
            except Exception as e:
                console.print(f"  [yellow]Warning: {json_file.name}: {e}[/yellow]")

        if batch:
            conn.executemany("""
                INSERT OR REPLACE INTO aquifer_content
                (content_id, resource_type, title, book, book_num,
                 start_ref, end_ref, chapter_start, verse_start,
                 chapter_end, verse_end, content, content_plain, is_range)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, batch)
            conn.commit()

        console.print(f"  [green]✓[/green] Imported {count} {subdir} entries")


def import_acai_entities(conn: sqlite3.Connection, acai_dir: Path):
    """Import ACAI entity annotation files."""
    from study_bible_mcp.parsers.acai import parse_acai_entities

    entity_types = ["people", "places", "groups", "keyterms"]
    total_count = 0

    for entity_type in entity_types:
        type_dir = acai_dir / entity_type
        if not type_dir.exists():
            continue

        json_files = sorted(type_dir.glob("*.json"))
        if not json_files:
            continue

        console.print(f"Importing ACAI {entity_type} ({len(json_files)} files)...")
        count = 0
        batch = []

        for json_file in json_files:
            try:
                for entity in parse_acai_entities(json_file, entity_type):
                    batch.append((
                        entity['id'],
                        entity['entity_type'],
                        entity['name'],
                        entity.get('gender'),
                        entity.get('description'),
                        entity.get('roles'),
                        entity.get('father_id'),
                        entity.get('mother_id'),
                        entity.get('partners'),
                        entity.get('offspring'),
                        entity.get('siblings'),
                        entity.get('referred_to_as'),
                        entity.get('key_references'),
                        entity.get('reference_count', 0),
                        entity.get('speeches_count', 0),
                    ))
                    count += 1

                    if len(batch) >= 500:
                        conn.executemany("""
                            INSERT OR REPLACE INTO acai_entities
                            (id, entity_type, name, gender, description, roles,
                             father_id, mother_id, partners, offspring, siblings,
                             referred_to_as, key_references, reference_count, speeches_count)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, batch)
                        conn.commit()
                        batch = []
            except Exception as e:
                console.print(f"  [yellow]Warning: {json_file.name}: {e}[/yellow]")

        if batch:
            conn.executemany("""
                INSERT OR REPLACE INTO acai_entities
                (id, entity_type, name, gender, description, roles,
                 father_id, mother_id, partners, offspring, siblings,
                 referred_to_as, key_references, reference_count, speeches_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, batch)
            conn.commit()

        console.print(f"  [green]✓[/green] Imported {count} {entity_type}")
        total_count += count

    if total_count:
        console.print(f"  [green]✓[/green] Total ACAI entities: {total_count}")


def import_ane_context(conn: sqlite3.Connection, ane_dir: Path):
    """Import ANE (Ancient Near East) context data files."""
    from study_bible_mcp.parsers.ane_context import parse_ane_context_file

    json_files = sorted(ane_dir.glob("*.json"))
    if not json_files:
        console.print("  [yellow]No ANE context files found[/yellow]")
        return

    console.print(f"Importing ANE context ({len(json_files)} dimension files)...")
    entry_count = 0
    mapping_count = 0

    for json_file in json_files:
        try:
            for entry, book_mappings in parse_ane_context_file(json_file):
                conn.execute("""
                    INSERT OR REPLACE INTO ane_entries
                    (id, dimension, dimension_label, title, summary, detail,
                     ane_parallels, interpretive_significance, period, period_label,
                     key_references, scholarly_sources)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    entry['id'], entry['dimension'], entry['dimension_label'],
                    entry['title'], entry['summary'], entry.get('detail'),
                    entry.get('ane_parallels'), entry.get('interpretive_significance'),
                    entry.get('period'), entry.get('period_label'),
                    entry.get('key_references'), entry.get('scholarly_sources'),
                ))
                entry_count += 1

                for bm in book_mappings:
                    conn.execute("""
                        INSERT OR REPLACE INTO ane_book_mappings
                        (entry_id, book, chapter_start, chapter_end)
                        VALUES (?, ?, ?, ?)
                    """, (
                        bm['entry_id'], bm['book'],
                        bm.get('chapter_start'), bm.get('chapter_end'),
                    ))
                    mapping_count += 1
        except Exception as e:
            console.print(f"  [yellow]Warning: {json_file.name}: {e}[/yellow]")

    conn.commit()
    console.print(f"  [green]✓[/green] Imported {entry_count} ANE entries with {mapping_count} book mappings")


def show_stats(conn: sqlite3.Connection):
    """Show database statistics."""
    console.print("\n[bold]Database Statistics:[/bold]")

    tables = ["lexicon", "verses", "passages", "names", "morphology", "thematic_references"]

    # Check for optional tables
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    existing_tables = {row[0] for row in cursor.fetchall()}
    if "aquifer_content" in existing_tables:
        tables.append("aquifer_content")
    if "acai_entities" in existing_tables:
        tables.append("acai_entities")
    if "ane_entries" in existing_tables:
        tables.append("ane_entries")
    if "ane_book_mappings" in existing_tables:
        tables.append("ane_book_mappings")

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
