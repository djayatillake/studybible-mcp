#!/usr/bin/env python3
"""Exercise every registered MCP tool against a full local database.

This is an integration smoke runner, not a pytest module. Whether a tool is
skipped is decided before calling it, from the row counts of the tables it
needs; a tool whose data is present must then return a real result. Handler
errors, empty or no-match results with data present, and registry drift fail
the run.

External links are checked separately by scripts/check_links.py.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from study_bible_mcp.database import StudyBibleDB
from study_bible_mcp.tools import TOOLS
import study_bible_mcp.server as server_module


# tool name -> (arguments, tables that must have rows for the tool to run)
TOOL_CASES: dict[str, tuple[dict, tuple[str, ...]]] = {
    "word_study": ({"strongs": "G26"}, ("lexicon", "verses")),
    "lookup_verse": ({"reference": "John 3:16"}, ("verses",)),
    "search_lexicon": ({"query": "love", "language": "greek"}, ("lexicon",)),
    "get_cross_references": ({"reference": "John 3:16"}, ("cross_references",)),
    "lookup_name": ({"name": "David", "type": "person"}, ("names",)),
    "compare_biblical_versions": (
        {"reference": "Psalm 24:1"},
        ("biblical_version_verses",),
    ),
    "search_ancient_sources": (
        {"query": "John Baptist", "corpus": "josephus", "limit": 3},
        ("ancient_source_passages",),
    ),
    "parse_morphology": ({"code": "V-AAI-3S", "language": "greek"}, ("morphology",)),
    "search_by_strongs": ({"strongs": "G26", "limit": 5}, ("lexicon", "verses")),
    "find_similar_passages": (
        {"reference": "John 3:16", "limit": 5},
        ("verses", "verse_vectors"),
    ),
    "explore_genealogy": (
        {"person": "David", "direction": "ancestors", "generations": 3},
        ("graph_people", "graph_family_edges"),
    ),
    "people_in_passage": ({"reference": "Genesis 22"}, ("graph_verse_mentions",)),
    "explore_person_events": (
        {"person": "Moses"},
        ("graph_people", "graph_person_event_edges"),
    ),
    "explore_place": ({"place": "Jerusalem"}, ("graph_places",)),
    "find_connection": (
        {"person1": "Abraham", "person2": "David"},
        ("graph_people", "graph_family_edges"),
    ),
    "graph_enriched_search": (
        {"reference": "Genesis 22:1"},
        ("verses", "graph_verse_mentions"),
    ),
    "get_study_notes": ({"reference": "John 3:16"}, ("aquifer_content",)),
    "get_bible_dictionary": ({"topic": "covenant"}, ("aquifer_content",)),
    "get_key_terms": ({"term": "atonement"}, ("aquifer_content",)),
    "get_ane_context": ({"reference": "Genesis 15:1"}, ("ane_entries",)),
    "get_theology_context": (
        {"reference": "Psalm 82:1", "limit": 3},
        ("theology_content",),
    ),
    "get_torah_weave": (
        {"reference": "Genesis 1:1"},
        ("torah_weave_units", "torah_weave_cells"),
    ),
    "get_textual_variant": (
        {"reference": "Deuteronomy 32:8"},
        ("textual_variant_cases",),
    ),
    # The catalogue ships with the package, so no table is required.
    "list_research_sources": ({"topic": "rabbinic", "query": "Psalm 82"}, ()),
}

# Matched against the first line of a response only, so words such as
# "not available" inside a normal multi-section result cannot trigger it.
_EMPTY_RESULT = re.compile(
    r"^(no |verse not found|unknown |could not|please provide|unsupported|error:)"
    r"|not available|unavailable|have not been generated"
    r"|upgrade_database\.py|build_database\.py|rebuild the database",
    re.IGNORECASE,
)


async def _missing_tables(database: StudyBibleDB, tables: tuple[str, ...]) -> list[str]:
    return [table for table in tables if not await database._table_has_rows(table)]


async def run(db_path: Path) -> bool:
    registered = {tool.name for tool in TOOLS}
    covered = set(TOOL_CASES)
    if registered != covered:
        print(f"Registry mismatch: missing={sorted(registered - covered)}, extra={sorted(covered - registered)}")
        return False
    if not db_path.is_file():
        print(f"Database not found: {db_path}")
        return False

    database = StudyBibleDB(db_path)
    await database.connect()
    server_module.db = database
    failures = 0
    skips = 0
    try:
        for name, (arguments, tables) in TOOL_CASES.items():
            missing = await _missing_tables(database, tables)
            if missing:
                skips += 1
                print(f"SKIP {name}: no rows in {', '.join(missing)}")
                continue
            response = await server_module.call_tool(name, arguments)
            result = (response[0].text if response else "").strip()
            first_line = result.splitlines()[0] if result else ""
            if not result or _EMPTY_RESULT.search(first_line):
                failures += 1
                print(f"FAIL {name}: data present but got: {result[:200]!r}")
            else:
                print(f"OK   {name}: {len(result)} characters")
    finally:
        server_module.db = None
        await database.close()

    print(f"\n{len(TOOL_CASES) - failures - skips} passed, {skips} skipped, {failures} failed")
    return failures == 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "db" / "study_bible.db",
        help="Path to the full study_bible.db",
    )
    args = parser.parse_args()
    raise SystemExit(0 if asyncio.run(run(args.db)) else 1)


if __name__ == "__main__":
    main()
