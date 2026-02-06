#!/usr/bin/env python3
"""
Generate embeddings for Bible verses and passages using OpenAI API.

This script:
1. Reads verses and passages from the SQLite database
2. Generates embeddings using OpenAI's text-embedding-3-small model
3. Stores embeddings in sqlite-vec virtual tables for similarity search

Prerequisites:
- Database must be built first (run build_database.py)
- OPENAI_API_KEY environment variable must be set
- sqlite-vec extension must be available

Cost estimate: ~$0.01 for 31K verses + 10K passages (~500K tokens total)
"""

import os
import sqlite3
import struct
import sys
import time
from pathlib import Path

import click
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

console = Console()

# Embedding model configuration
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536
BATCH_SIZE = 100  # OpenAI allows up to 2048 inputs per request


def get_paths():
    """Get database path."""
    script_dir = Path(__file__).parent
    project_dir = script_dir.parent
    db_dir = project_dir / "db"
    return db_dir / "study_bible.db"


def load_sqlite_vec(conn: sqlite3.Connection):
    """Load the sqlite-vec extension."""
    try:
        # Try different extension names/paths
        for ext_name in ['sqlite_vec', 'vec0', 'sqlite-vec']:
            try:
                conn.enable_load_extension(True)
                conn.load_extension(ext_name)
                console.print(f"  [green]✓[/green] Loaded sqlite-vec extension")
                return True
            except sqlite3.OperationalError:
                continue

        # Try loading from common paths
        import sqlite_vec
        sqlite_vec.load(conn)
        console.print(f"  [green]✓[/green] Loaded sqlite-vec via Python package")
        return True

    except Exception as e:
        console.print(f"[red]Error loading sqlite-vec: {e}[/red]")
        console.print("Install with: pip install sqlite-vec")
        return False


def create_vector_tables(conn: sqlite3.Connection):
    """Create the vector tables for embeddings."""
    conn.executescript("""
        -- Drop existing tables to rebuild
        DROP TABLE IF EXISTS verse_vectors;
        DROP TABLE IF EXISTS passage_vectors;

        -- Vector table for verse embeddings (1536 dimensions for OpenAI)
        CREATE VIRTUAL TABLE verse_vectors USING vec0(
            verse_id INTEGER PRIMARY KEY,
            embedding FLOAT[1536]
        );

        -- Vector table for passage embeddings
        CREATE VIRTUAL TABLE passage_vectors USING vec0(
            passage_id INTEGER PRIMARY KEY,
            embedding FLOAT[1536]
        );
    """)
    conn.commit()
    console.print("  [green]✓[/green] Created vector tables")


def get_openai_client():
    """Initialize OpenAI client."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        console.print("[red]Error: OPENAI_API_KEY environment variable not set[/red]")
        sys.exit(1)

    try:
        from openai import OpenAI
        return OpenAI(api_key=api_key)
    except ImportError:
        console.print("[red]Error: openai package not installed[/red]")
        console.print("Install with: pip install openai")
        sys.exit(1)


def generate_embeddings_batch(client, texts: list[str]) -> list[list[float]]:
    """Generate embeddings for a batch of texts."""
    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=texts
    )
    return [item.embedding for item in response.data]


def embedding_to_bytes(embedding: list[float]) -> bytes:
    """Convert embedding list to bytes for sqlite-vec."""
    return struct.pack(f'{len(embedding)}f', *embedding)


def process_verses(conn: sqlite3.Connection, client, limit: int | None = None):
    """Generate and store embeddings for all verses."""
    console.print("\n[bold]Processing verse embeddings...[/bold]")

    # Get verses that need embeddings
    sql = "SELECT id, reference, text_english FROM verses WHERE text_english IS NOT NULL AND text_english != ''"
    if limit:
        sql += f" LIMIT {limit}"

    cursor = conn.execute(sql)
    verses = cursor.fetchall()

    if not verses:
        console.print("  [yellow]No verses found[/yellow]")
        return

    total = len(verses)
    console.print(f"  Found {total:,} verses to embed")

    # Process in batches
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        console=console,
    ) as progress:
        task = progress.add_task("Generating embeddings", total=total)

        for i in range(0, total, BATCH_SIZE):
            batch = verses[i:i + BATCH_SIZE]
            verse_ids = [v[0] for v in batch]
            texts = [v[2] for v in batch]  # text_english

            # Generate embeddings
            try:
                embeddings = generate_embeddings_batch(client, texts)
            except Exception as e:
                console.print(f"\n[red]Error generating embeddings: {e}[/red]")
                # Retry with exponential backoff
                time.sleep(2)
                try:
                    embeddings = generate_embeddings_batch(client, texts)
                except Exception as e2:
                    console.print(f"[red]Retry failed: {e2}[/red]")
                    continue

            # Store in database
            for verse_id, embedding in zip(verse_ids, embeddings):
                embedding_bytes = embedding_to_bytes(embedding)
                conn.execute(
                    "INSERT INTO verse_vectors (verse_id, embedding) VALUES (?, ?)",
                    (verse_id, embedding_bytes)
                )

            conn.commit()
            progress.update(task, advance=len(batch))

            # Rate limiting - be gentle with API
            if i + BATCH_SIZE < total:
                time.sleep(0.1)

    console.print(f"  [green]✓[/green] Generated embeddings for {total:,} verses")


def process_passages(conn: sqlite3.Connection, client, limit: int | None = None):
    """Generate and store embeddings for all passages."""
    console.print("\n[bold]Processing passage embeddings...[/bold]")

    # Get passages that need embeddings
    sql = "SELECT id, reference_start, reference_end, text_combined FROM passages WHERE text_combined IS NOT NULL AND text_combined != ''"
    if limit:
        sql += f" LIMIT {limit}"

    cursor = conn.execute(sql)
    passages = cursor.fetchall()

    if not passages:
        console.print("  [yellow]No passages found[/yellow]")
        return

    total = len(passages)
    console.print(f"  Found {total:,} passages to embed")

    # Process in batches
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        console=console,
    ) as progress:
        task = progress.add_task("Generating embeddings", total=total)

        for i in range(0, total, BATCH_SIZE):
            batch = passages[i:i + BATCH_SIZE]
            passage_ids = [p[0] for p in batch]

            # Truncate long passages to fit token limits (~8K tokens max)
            # Roughly 4 chars per token, so ~32K chars max
            texts = []
            for p in batch:
                text = p[3]  # text_combined
                if len(text) > 30000:
                    text = text[:30000] + "..."
                texts.append(text)

            # Generate embeddings
            try:
                embeddings = generate_embeddings_batch(client, texts)
            except Exception as e:
                console.print(f"\n[red]Error generating embeddings: {e}[/red]")
                time.sleep(2)
                try:
                    embeddings = generate_embeddings_batch(client, texts)
                except Exception as e2:
                    console.print(f"[red]Retry failed: {e2}[/red]")
                    continue

            # Store in database
            for passage_id, embedding in zip(passage_ids, embeddings):
                embedding_bytes = embedding_to_bytes(embedding)
                conn.execute(
                    "INSERT INTO passage_vectors (passage_id, embedding) VALUES (?, ?)",
                    (passage_id, embedding_bytes)
                )

            conn.commit()
            progress.update(task, advance=len(batch))

            # Rate limiting
            if i + BATCH_SIZE < total:
                time.sleep(0.1)

    console.print(f"  [green]✓[/green] Generated embeddings for {total:,} passages")


def show_stats(conn: sqlite3.Connection):
    """Show embedding statistics."""
    console.print("\n[bold]Embedding Statistics:[/bold]")

    # Verse vectors
    cursor = conn.execute("SELECT COUNT(*) FROM verse_vectors")
    verse_count = cursor.fetchone()[0]
    console.print(f"  Verse embeddings: {verse_count:,}")

    # Passage vectors
    cursor = conn.execute("SELECT COUNT(*) FROM passage_vectors")
    passage_count = cursor.fetchone()[0]
    console.print(f"  Passage embeddings: {passage_count:,}")

    # Estimated storage
    # Each embedding is 1536 floats * 4 bytes = 6144 bytes
    storage_mb = (verse_count + passage_count) * 6144 / (1024 * 1024)
    console.print(f"  Estimated vector storage: {storage_mb:.1f} MB")


@click.command()
@click.option("--db-path", "-d", type=click.Path(exists=True), help="Database path")
@click.option("--verses-only", is_flag=True, help="Only generate verse embeddings")
@click.option("--passages-only", is_flag=True, help="Only generate passage embeddings")
@click.option("--limit", "-l", type=int, help="Limit number of items to process (for testing)")
@click.option("--rebuild", "-r", is_flag=True, help="Rebuild vector tables from scratch")
def main(db_path: str | None, verses_only: bool, passages_only: bool, limit: int | None, rebuild: bool):
    """Generate embeddings for Bible verses and passages."""
    console.print("[bold blue]Study Bible MCP - Embedding Generator[/bold blue]")

    # Get database path
    db_file = Path(db_path) if db_path else get_paths()

    if not db_file.exists():
        console.print(f"[red]Error: Database not found at {db_file}[/red]")
        console.print("Run [bold]python scripts/build_database.py[/bold] first.")
        sys.exit(1)

    console.print(f"\nDatabase: {db_file}")

    # Connect to database
    conn = sqlite3.connect(db_file)

    # Load sqlite-vec extension
    if not load_sqlite_vec(conn):
        sys.exit(1)

    # Create or rebuild vector tables
    if rebuild:
        console.print("\nRebuilding vector tables...")
        create_vector_tables(conn)
    else:
        # Check if tables exist
        try:
            conn.execute("SELECT COUNT(*) FROM verse_vectors")
        except sqlite3.OperationalError:
            console.print("\nVector tables don't exist, creating...")
            create_vector_tables(conn)

    # Initialize OpenAI client
    client = get_openai_client()

    # Generate embeddings
    if not passages_only:
        process_verses(conn, client, limit)

    if not verses_only:
        process_passages(conn, client, limit)

    # Optimize
    console.print("\nOptimizing database...")
    conn.execute("ANALYZE")
    conn.commit()

    # Show stats
    show_stats(conn)

    conn.close()
    console.print("\n[bold green]✓ Embedding generation complete![/bold green]")


if __name__ == "__main__":
    main()
