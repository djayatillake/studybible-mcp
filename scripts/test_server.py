#!/usr/bin/env python3
"""
Test the Study Bible MCP server.

This script runs basic tests to verify the server and database are working.
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rich.console import Console
from rich.table import Table

from study_bible_mcp.database import StudyBibleDB

console = Console()


async def test_database():
    """Test database connectivity and basic queries."""
    console.print("\n[bold]Testing Database Connection[/bold]\n")
    
    # Find database
    db_paths = [
        Path(__file__).parent.parent / "db" / "study_bible.db",
        Path.cwd() / "db" / "study_bible.db",
    ]
    
    db_path = None
    for path in db_paths:
        if path.exists():
            db_path = path
            break
    
    if not db_path:
        console.print("[red]Error: Database not found![/red]")
        console.print("Run [bold]python scripts/build_database.py[/bold] first.")
        return False
    
    console.print(f"Database: {db_path}")
    
    async with StudyBibleDB(db_path) as db:
        # Test 1: Lexicon lookup
        console.print("\n[bold]Test 1:[/bold] Lexicon Lookup (G26 - agapē)")
        entry = await db.get_lexicon_entry("G26")
        if entry:
            console.print(f"  [green]✓[/green] Found: {entry['word']} ({entry['transliteration']})")
            console.print(f"    Definition: {entry['short_definition'][:80]}...")
        else:
            console.print("  [red]✗[/red] Entry not found")
        
        # Test 2: Hebrew lexicon
        console.print("\n[bold]Test 2:[/bold] Hebrew Lexicon (H3068 - YHWH)")
        entry = await db.get_lexicon_entry("H3068")
        if entry:
            console.print(f"  [green]✓[/green] Found: {entry['word']} ({entry['transliteration']})")
        else:
            console.print("  [yellow]![/yellow] Entry not found (may not be in brief lexicon)")
        
        # Test 3: Search lexicon
        console.print("\n[bold]Test 3:[/bold] Search Lexicon ('love')")
        entries = await db.search_lexicon("love", language="greek", limit=3)
        if entries:
            console.print(f"  [green]✓[/green] Found {len(entries)} entries:")
            for e in entries:
                console.print(f"    - {e['strongs']}: {e['word']} ({e['transliteration']})")
        else:
            console.print("  [red]✗[/red] No entries found")
        
        # Test 4: Verse lookup (if TAGNT was imported)
        console.print("\n[bold]Test 4:[/bold] Verse Lookup (John 3:16)")
        verse = await db.get_verse("John 3:16")
        if verse:
            console.print(f"  [green]✓[/green] Found verse")
            if verse.get('text_english'):
                console.print(f"    English: {verse['text_english'][:80]}...")
            if verse.get('text_original'):
                console.print(f"    Greek: {verse['text_original'][:50]}...")
        else:
            console.print("  [yellow]![/yellow] Verse not found (TAGNT may not be imported)")
        
        # Test 5: Name lookup (if TIPNR was imported)
        console.print("\n[bold]Test 5:[/bold] Name Lookup ('David')")
        names = await db.lookup_name("David", name_type="person")
        if names:
            console.print(f"  [green]✓[/green] Found {len(names)} entries")
            for n in names[:2]:
                console.print(f"    - {n['name']} ({n['type']})")
        else:
            console.print("  [yellow]![/yellow] Name not found (TIPNR may not be imported)")
        
        # Test 6: Thematic references
        console.print("\n[bold]Test 6:[/bold] Thematic References ('salvation')")
        refs = await db.get_thematic_references("salvation")
        if refs:
            console.print(f"  [green]✓[/green] Found {len(refs)} references")
        else:
            console.print("  [yellow]![/yellow] No thematic references found")
    
    console.print("\n[bold green]✓ Database tests completed![/bold green]")
    return True


async def test_tools():
    """Test MCP tool implementations."""
    console.print("\n[bold]Testing MCP Tools[/bold]\n")
    
    # Import server module
    try:
        from study_bible_mcp import server
        from study_bible_mcp.tools import TOOLS
        
        console.print(f"Available tools: {len(TOOLS)}")
        
        table = Table(title="MCP Tools")
        table.add_column("Name", style="cyan")
        table.add_column("Description", style="green")
        
        for tool in TOOLS:
            desc = tool.description.split('\n')[0][:60] + "..."
            table.add_row(tool.name, desc)
        
        console.print(table)
        
        console.print("\n[bold green]✓ Tools loaded successfully![/bold green]")
        return True
        
    except Exception as e:
        console.print(f"[red]Error loading tools: {e}[/red]")
        return False


async def main():
    """Run all tests."""
    console.print("[bold blue]Study Bible MCP - Test Suite[/bold blue]")
    
    results = []
    
    # Test database
    results.append(("Database", await test_database()))
    
    # Test tools
    results.append(("Tools", await test_tools()))
    
    # Summary
    console.print("\n[bold]Summary[/bold]")
    all_passed = True
    for name, passed in results:
        status = "[green]PASS[/green]" if passed else "[red]FAIL[/red]"
        console.print(f"  {name}: {status}")
        if not passed:
            all_passed = False
    
    if all_passed:
        console.print("\n[bold green]All tests passed![/bold green]")
        console.print("\nYour Study Bible MCP server is ready to use.")
        console.print("See README.md for Claude Desktop configuration.")
    else:
        console.print("\n[bold yellow]Some tests failed.[/bold yellow]")
        console.print("Check the output above for details.")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
