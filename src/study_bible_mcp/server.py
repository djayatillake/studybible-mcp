#!/usr/bin/env python3
"""
Study Bible MCP Server

Main server implementation providing Bible study tools via MCP protocol.
Supports both stdio and SSE transports for local and remote deployment.
"""

import asyncio
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

import click
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    Icon,
    TextContent,
    Tool,
)

from .database import StudyBibleDB

# Purple book with gold cross icon (32x32 PNG, base64 encoded)
ICON_BASE64 = "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAAtklEQVR42mNgGOmAEZtgQ9TV/7SwrGGZNiNeB9DKYnwOYcGl6MajG1S1VENOA6s4E4yxounvfw0NDZpYjm4mckgz0drnhMxmIdew5bO3M9w+twfOr5veS5Y5TAOdDUcdMOAOYCE2wWEDqkYueNVEpnpSxwHIqR3ZcmziqMBzNA1QJwqwFTLocT5aEI06YNQBow6gaUGEDUAqGk/qhwCu1iutWsY4+wW0bJYT1S+gZUgMqq7ZKAAA/oE/8EmGTpMAAAAASUVORK5CYII="
from .tools import (
    TOOLS, format_lexicon_entry, format_verse, format_name_entry,
    format_genealogy, format_person_events, format_place_history,
    format_passage_entities, format_connection_path,
    mermaid_genealogy, mermaid_connection_path, mermaid_person_timeline,
    mermaid_place_network,
    format_study_notes, format_dictionary_article, format_key_terms,
    format_ane_context, format_ane_dimensions,
)
from .hermeneutics import (
    get_genre_from_reference,
    format_genre_guidance,
    get_reasoning_pattern,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("study-bible-mcp")

# Initialize server with purple cross icon
# Use URL-based icon for better compatibility with Claude Desktop
ICON_URL = "https://studybible-mcp.fly.dev/static/icon.png"
server = Server(
    "study-bible",
    version="1.0.0",
    icons=[
        Icon(
            src=ICON_URL,
            mimeType="image/png",
            sizes=["32x32"]
        )
    ]
)

# Database connection (initialized on startup)
db: StudyBibleDB | None = None


def get_db_path() -> Path:
    """Get the database path, checking common locations."""
    # Check environment variable first
    if env_path := os.environ.get("STUDY_BIBLE_DB"):
        return Path(env_path)

    # Check relative to this file (for development)
    pkg_dir = Path(__file__).parent
    local_db = pkg_dir.parent.parent / "db" / "study_bible.db"
    if local_db.exists():
        return local_db

    # Check current working directory
    cwd_db = Path.cwd() / "db" / "study_bible.db"
    if cwd_db.exists():
        return cwd_db

    # Check /app/db for Docker deployments
    docker_db = Path("/app/db/study_bible.db")
    if docker_db.exists():
        return docker_db

    # Check Fly.io volume mount
    fly_db = Path("/data/study_bible.db")
    if fly_db.exists():
        return fly_db

    # Default path (may not exist yet)
    return local_db


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List all available Bible study tools."""
    return TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle tool calls."""
    global db

    if db is None:
        db_path = get_db_path()
        if not db_path.exists():
            return [TextContent(
                type="text",
                text=f"Database not found at {db_path}. Please run 'python scripts/build_database.py' first."
            )]
        db = StudyBibleDB(db_path)
        await db.connect()

    try:
        if name == "word_study":
            return await handle_word_study(arguments)
        elif name == "lookup_verse":
            return await handle_lookup_verse(arguments)
        elif name == "search_lexicon":
            return await handle_search_lexicon(arguments)
        elif name == "get_cross_references":
            return await handle_get_cross_references(arguments)
        elif name == "lookup_name":
            return await handle_lookup_name(arguments)
        elif name == "parse_morphology":
            return await handle_parse_morphology(arguments)
        elif name == "search_by_strongs":
            return await handle_search_by_strongs(arguments)
        elif name == "find_similar_passages":
            return await handle_find_similar_passages(arguments)
        elif name == "explore_genealogy":
            return await handle_explore_genealogy(arguments)
        elif name == "people_in_passage":
            return await handle_people_in_passage(arguments)
        elif name == "explore_person_events":
            return await handle_explore_person_events(arguments)
        elif name == "explore_place":
            return await handle_explore_place(arguments)
        elif name == "find_connection":
            return await handle_find_connection(arguments)
        elif name == "graph_enriched_search":
            return await handle_graph_enriched_search(arguments)
        elif name == "get_study_notes":
            return await handle_get_study_notes(arguments)
        elif name == "get_bible_dictionary":
            return await handle_get_bible_dictionary(arguments)
        elif name == "get_key_terms":
            return await handle_get_key_terms(arguments)
        elif name == "get_ane_context":
            return await handle_get_ane_context(arguments)
        else:
            return [TextContent(
                type="text",
                text=f"Unknown tool: {name}"
            )]
    except Exception as e:
        logger.exception(f"Error in tool {name}")
        return [TextContent(
            type="text",
            text=f"Error: {str(e)}"
        )]


async def handle_word_study(args: dict[str, Any]) -> list[TextContent]:
    """Handle word_study tool - deep dive into a Greek or Hebrew word."""
    strongs = args.get("strongs")
    word = args.get("word")
    language = args.get("language", "greek")

    if strongs:
        entry = await db.get_lexicon_entry(strongs)
    elif word:
        entries = await db.search_lexicon(word, language=language, limit=1)
        entry = entries[0] if entries else None
    else:
        return [TextContent(type="text", text="Please provide either 'strongs' number or 'word' to study.")]

    if not entry:
        return [TextContent(type="text", text="No entry found for the given word/Strong's number.")]

    # Get verses where this word appears
    verses = await db.get_verses_with_strongs(entry["strongs"], limit=5)

    result = format_lexicon_entry(entry)

    if verses:
        result += "\n\n## Example Passages\n"
        for v in verses:
            result += f"\n**{v['reference']}**: {v['text_english']}\n"

    return [TextContent(type="text", text=result)]


async def handle_lookup_verse(args: dict[str, Any]) -> list[TextContent]:
    """Handle lookup_verse tool - get scripture text with optional Greek/Hebrew."""
    reference = args.get("reference", "")
    include_original = args.get("include_original", True)
    include_morphology = args.get("include_morphology", False)

    if not reference:
        return [TextContent(type="text", text="Please provide a verse reference (e.g., 'John 3:16').")]

    verse = await db.get_verse(reference)

    if not verse:
        return [TextContent(type="text", text=f"Verse not found: {reference}")]

    result = format_verse(verse, include_original, include_morphology)

    # Add genre guidance if available
    genre = get_genre_from_reference(reference)
    if genre:
        result += f"\n\n---\n{format_genre_guidance(genre)}"

    return [TextContent(type="text", text=result)]


async def handle_search_lexicon(args: dict[str, Any]) -> list[TextContent]:
    """Handle search_lexicon tool - search across lexicon entries."""
    query = args.get("query", "")
    language = args.get("language")  # None means both
    limit = args.get("limit", 10)

    if not query:
        return [TextContent(type="text", text="Please provide a search query.")]

    entries = await db.search_lexicon(query, language=language, limit=limit)

    if not entries:
        return [TextContent(type="text", text=f"No entries found for '{query}'.")]

    result = f"## Lexicon Search: '{query}'\n\nFound {len(entries)} entries:\n\n"

    for entry in entries:
        result += f"### {entry['strongs']} - {entry['word']} ({entry['transliteration']})\n"
        result += f"{entry['short_definition']}\n\n"

    return [TextContent(type="text", text=result)]


async def handle_get_cross_references(args: dict[str, Any]) -> list[TextContent]:
    """Handle get_cross_references tool - find related passages."""
    reference = args.get("reference")
    theme = args.get("theme")

    if theme:
        refs = await db.get_thematic_references(theme)
        if not refs:
            return [TextContent(type="text", text=f"No cross-references found for theme '{theme}'.")]

        result = f"## Cross-References: {theme}\n\n"
        for ref in refs:
            result += f"- **{ref['reference']}**: {ref['note']}\n"
        return [TextContent(type="text", text=result)]

    elif reference:
        refs = await db.get_cross_references(reference)
        if not refs:
            return [TextContent(type="text", text=f"No cross-references found for {reference}.")]

        result = f"## Cross-References for {reference}\n\n"
        for ref in refs:
            result += f"- {ref['target']}\n"
        return [TextContent(type="text", text=result)]

    else:
        return [TextContent(type="text", text="Please provide either 'reference' or 'theme'.")]


async def handle_lookup_name(args: dict[str, Any]) -> list[TextContent]:
    """Handle lookup_name tool - get info about biblical names, enriched with ACAI data."""
    name = args.get("name", "")
    name_type = args.get("type")  # person, place, thing

    if not name:
        return [TextContent(type="text", text="Please provide a name to look up.")]

    entries = await db.lookup_name(name, name_type=name_type)

    if not entries:
        return [TextContent(type="text", text=f"No entries found for '{name}'.")]

    # Try to get ACAI enrichment data
    acai_data = None
    try:
        has_acai = await db.has_acai_data()
        if has_acai:
            acai_data = await db.get_acai_entity(name)
    except Exception:
        pass

    result = f"## Biblical Names: {name}\n\n"

    for entry in entries:
        result += format_name_entry(entry, acai_data=acai_data)
        result += "\n---\n\n"

    return [TextContent(type="text", text=result)]


async def handle_parse_morphology(args: dict[str, Any]) -> list[TextContent]:
    """Handle parse_morphology tool - explain grammatical codes."""
    code = args.get("code", "")
    language = args.get("language", "greek")

    if not code:
        return [TextContent(type="text", text="Please provide a morphology code to parse.")]

    parsing = await db.get_morphology(code, language)

    if not parsing:
        return [TextContent(type="text", text=f"Unknown morphology code: {code}")]

    result = f"## Morphology: {code}\n\n"
    result += f"**Language**: {parsing['language'].title()}\n"
    result += f"**Part of Speech**: {parsing['part_of_speech']}\n"

    if parsing.get('person'):
        result += f"**Person**: {parsing['person']}\n"
    if parsing.get('number'):
        result += f"**Number**: {parsing['number']}\n"
    if parsing.get('tense'):
        result += f"**Tense**: {parsing['tense']}\n"
    if parsing.get('voice'):
        result += f"**Voice**: {parsing['voice']}\n"
    if parsing.get('mood'):
        result += f"**Mood**: {parsing['mood']}\n"
    if parsing.get('case_value'):
        result += f"**Case**: {parsing['case_value']}\n"
    if parsing.get('gender'):
        result += f"**Gender**: {parsing['gender']}\n"

    result += f"\n**Full Parsing**: {parsing['parsing']}\n"

    return [TextContent(type="text", text=result)]


async def handle_search_by_strongs(args: dict[str, Any]) -> list[TextContent]:
    """Handle search_by_strongs tool - find all verses with a Strong's number."""
    strongs = args.get("strongs", "")
    limit = args.get("limit", 20)

    if not strongs:
        return [TextContent(type="text", text="Please provide a Strong's number (e.g., 'G26' or 'H3068').")]

    # Get lexicon entry first
    entry = await db.get_lexicon_entry(strongs)
    if not entry:
        return [TextContent(type="text", text=f"Unknown Strong's number: {strongs}")]

    # Get verses
    verses = await db.get_verses_with_strongs(strongs, limit=limit)

    result = f"## Verses with {strongs} ({entry['word']} - {entry['transliteration']})\n\n"
    result += f"*{entry['short_definition']}*\n\n"

    if verses:
        for v in verses:
            result += f"**{v['reference']}**: {v['text_english']}\n\n"
    else:
        result += "No verses found with this Strong's number in the database.\n"

    return [TextContent(type="text", text=result)]


async def handle_find_similar_passages(args: dict[str, Any]) -> list[TextContent]:
    """Handle find_similar_passages tool - find semantically similar passages."""
    reference = args.get("reference", "")
    limit = args.get("limit", 10)

    if not reference:
        return [TextContent(type="text", text="Please provide a verse reference (e.g., 'John 3:16').")]

    # Check if vector search is available
    if not db._vec_loaded:
        error_detail = db._vec_error or "sqlite-vec extension not available"
        return [TextContent(
            type="text",
            text=f"Vector search unavailable: {error_detail}"
        )]

    has_vectors = await db.has_vector_tables()
    if not has_vectors:
        return [TextContent(
            type="text",
            text="Vector embeddings have not been generated yet. "
                 "Run 'python scripts/generate_embeddings.py' to create them (~$0.01 via OpenAI API)."
        )]

    # Find similar passages
    similar = await db.find_similar_passages(reference, limit=limit)

    if not similar:
        return [TextContent(
            type="text",
            text=f"No similar passages found for {reference}. "
                 "The verse may not exist or embeddings may not be generated."
        )]

    # Get the source verse for context
    source_verse = await db.get_verse(reference)
    source_genre = get_genre_from_reference(reference) if source_verse else None

    result = f"## Passages Similar to {reference}\n\n"

    if source_verse:
        result += f"**Source**: {source_verse['text_english']}\n\n"

    result += "---\n\n"
    result += "⚠️ **Hermeneutical Caution**: Semantic similarity indicates shared vocabulary "
    result += "and concepts, but does NOT establish theological connection. Before using any "
    result += "passage below, verify:\n"
    result += "1. Genre compatibility with the source passage\n"
    result += "2. Whether the author intended an allusion/quotation\n"
    result += "3. Historical and literary context of each passage\n"
    result += "4. What each text meant to its original audience\n\n"
    result += "---\n\n"

    for i, passage in enumerate(similar, 1):
        similarity_pct = passage['similarity'] * 100
        ref_display = passage['reference']
        passage_genre = get_genre_from_reference(passage['reference_start'])

        result += f"### {i}. {ref_display} ({similarity_pct:.1f}% similar)\n\n"

        # Show genre if different from source
        if passage_genre and source_genre and passage_genre != source_genre:
            result += f"⚡ **Genre**: {passage_genre} (source is {source_genre})\n\n"

        # Show passage text (truncated if very long)
        text = passage['text_combined']
        if len(text) > 500:
            text = text[:500] + "..."
        result += f"{text}\n\n"

        # Add verse count info
        if passage['verse_count'] > 1:
            result += f"*({passage['verse_count']} verses in this passage)*\n\n"

    return [TextContent(type="text", text=result)]


# =========================================================================
# Aquifer content handlers
# =========================================================================

async def handle_get_study_notes(args: dict[str, Any]) -> list[TextContent]:
    """Handle get_study_notes tool - get study notes for a verse or chapter."""
    reference = args.get("reference", "")
    chapter_only = args.get("chapter_only", False)

    if not reference:
        return [TextContent(type="text", text="Please provide a Bible reference (e.g., 'John 3:16' or 'Genesis 1').")]

    has_data = await db.has_aquifer_data()
    if not has_data:
        return [TextContent(
            type="text",
            text="Study notes not available. Run 'python scripts/download_stepbible.py --aquifer' and rebuild the database."
        )]

    if chapter_only or ':' not in reference.strip():
        # Chapter-level: parse book and chapter
        ref_stripped = reference.strip()
        match = re.match(r'^(\d?\s*[a-zA-Z]+)\s+(\d+)$', ref_stripped)
        if match:
            book_str, chapter_str = match.groups()
            dummy_ref = f"{book_str} {chapter_str}:1"
            normalized = db._normalize_reference(dummy_ref)
            book_abbr = normalized.split(".")[0]
            notes = await db.get_chapter_study_notes(book_abbr, int(chapter_str))
        else:
            # Try as verse reference
            notes = await db.get_study_notes(reference)
    else:
        notes = await db.get_study_notes(reference)

    if not notes:
        return [TextContent(type="text", text=f"No study notes found for {reference}.")]

    result = f"## Study Notes: {reference}\n\n"
    result += format_study_notes(notes)

    return [TextContent(type="text", text=result)]


async def handle_get_bible_dictionary(args: dict[str, Any]) -> list[TextContent]:
    """Handle get_bible_dictionary tool - search dictionary articles."""
    topic = args.get("topic", "")

    if not topic:
        return [TextContent(type="text", text="Please provide a topic to look up.")]

    has_data = await db.has_aquifer_data()
    if not has_data:
        return [TextContent(
            type="text",
            text="Bible dictionary not available. Run 'python scripts/download_stepbible.py --aquifer' and rebuild the database."
        )]

    articles = await db.get_bible_dictionary(topic)

    if not articles:
        return [TextContent(type="text", text=f"No dictionary article found for '{topic}'.")]

    result = format_dictionary_article(articles)

    return [TextContent(type="text", text=result)]


async def handle_get_key_terms(args: dict[str, Any]) -> list[TextContent]:
    """Handle get_key_terms tool - search FIA Key Terms."""
    term = args.get("term", "")

    if not term:
        return [TextContent(type="text", text="Please provide a term to look up.")]

    has_data = await db.has_aquifer_data()
    if not has_data:
        return [TextContent(
            type="text",
            text="Key terms not available. Run 'python scripts/download_stepbible.py --aquifer' and rebuild the database."
        )]

    terms = await db.get_key_terms(term)

    if not terms:
        return [TextContent(type="text", text=f"No key term found for '{term}'.")]

    result = format_key_terms(terms)

    return [TextContent(type="text", text=result)]


# =========================================================================
# ANE context handler
# =========================================================================

async def handle_get_ane_context(args: dict[str, Any]) -> list[TextContent]:
    """Handle get_ane_context tool - get Ancient Near East background."""
    reference = args.get("reference")
    dimension = args.get("dimension")
    period = args.get("period")

    has_data = await db.has_ane_data()
    if not has_data:
        return [TextContent(
            type="text",
            text="ANE context data not available. Rebuild the database with ANE data files in data/ane_context/."
        )]

    # If no arguments provided, list available dimensions
    if not reference and not dimension and not period:
        dimensions = await db.get_ane_dimensions()
        result = format_ane_dimensions(dimensions)
        return [TextContent(type="text", text=result)]

    entries = await db.get_ane_context(
        reference=reference,
        dimension=dimension,
        period=period,
    )

    if not entries:
        parts = []
        if reference:
            parts.append(f"reference={reference}")
        if dimension:
            parts.append(f"dimension={dimension}")
        if period:
            parts.append(f"period={period}")
        return [TextContent(
            type="text",
            text=f"No ANE context entries found for {', '.join(parts)}."
        )]

    header = "## Ancient Near East Context"
    if reference:
        header += f" for {reference}"
    header += "\n\n"

    result = header + format_ane_context(entries)
    return [TextContent(type="text", text=result)]


# =========================================================================
# Graph tool handlers (Theographic Bible Metadata)
# =========================================================================

async def _check_graph_data() -> list[TextContent] | None:
    """Check if graph data is available. Returns error response or None."""
    has_data = await db.graph_has_data()
    if not has_data:
        return [TextContent(
            type="text",
            text="Graph data not available. Run 'python scripts/import_theographic.py' to import Theographic Bible Metadata."
        )]
    return None


async def handle_explore_genealogy(args: dict[str, Any]) -> list[TextContent]:
    """Handle explore_genealogy tool - trace family tree."""
    if err := await _check_graph_data():
        return err

    person_name = args.get("person", "")
    direction = args.get("direction", "both")
    generations = args.get("generations", 5)

    if not person_name:
        return [TextContent(type="text", text="Please provide a person's name.")]

    matches = await db.graph_find_person(person_name)
    if not matches:
        return [TextContent(type="text", text=f"No person found matching '{person_name}' in the Theographic database.")]

    person = matches[0]
    ancestors = []
    descendants = []

    if direction in ("ancestors", "both"):
        ancestors = await db.graph_get_ancestors(person["id"], generations)

    if direction in ("descendants", "both"):
        descendants = await db.graph_get_descendants(person["id"], generations)

    result = format_genealogy(person["name"], ancestors, descendants)

    # Add immediate family context
    family = await db.graph_get_family(person["id"])
    family_lines = []
    if family["partners"]:
        names = ", ".join(p["name"] for p in family["partners"])
        family_lines.append(f"**Spouse(s)**: {names}")
    if family["siblings"]:
        names = ", ".join(p["name"] for p in family["siblings"])
        family_lines.append(f"**Siblings**: {names}")

    if family_lines:
        result += "\n### Immediate Family\n" + "\n".join(family_lines) + "\n"

    if person.get("description"):
        result += f"\n### About\n{person['description']}\n"

    # Append Mermaid diagram
    diagram = mermaid_genealogy(person["name"], ancestors, descendants, family)
    if diagram:
        result += f"\n### Family Tree Diagram\n{diagram}\n"

    return [TextContent(type="text", text=result)]


async def handle_people_in_passage(args: dict[str, Any]) -> list[TextContent]:
    """Handle people_in_passage tool - find entities in a verse or chapter."""
    if err := await _check_graph_data():
        return err

    reference = args.get("reference", "")
    if not reference:
        return [TextContent(type="text", text="Please provide a Bible reference (e.g., 'Romans 8' or 'Genesis 22:1').")]

    # Determine if this is a chapter or verse reference
    ref_stripped = reference.strip()
    has_verse = ":" in ref_stripped

    if has_verse:
        # Verse-level: normalize and query
        normalized = db._normalize_reference(ref_stripped)
        entities = await db.graph_get_verse_entities(normalized)
    else:
        # Chapter-level: parse book and chapter
        match = re.match(r'^(\d?\s*[a-zA-Z]+)\s+(\d+)$', ref_stripped)
        if match:
            book_str, chapter_str = match.groups()
            # Normalize the book name using the same reference normalizer
            dummy_ref = f"{book_str} {chapter_str}:1"
            normalized = db._normalize_reference(dummy_ref)
            book_abbr = normalized.split(".")[0]
            entities = await db.graph_get_chapter_entities(book_abbr, int(chapter_str))
        else:
            return [TextContent(type="text", text=f"Could not parse reference: {reference}. Use 'Romans 8' or 'Genesis 22:1' format.")]

    result = format_passage_entities(reference, entities)
    return [TextContent(type="text", text=result)]


async def handle_explore_person_events(args: dict[str, Any]) -> list[TextContent]:
    """Handle explore_person_events tool - timeline of a person's life."""
    if err := await _check_graph_data():
        return err

    person_name = args.get("person", "")
    if not person_name:
        return [TextContent(type="text", text="Please provide a person's name.")]

    matches = await db.graph_find_person(person_name)
    if not matches:
        return [TextContent(type="text", text=f"No person found matching '{person_name}' in the Theographic database.")]

    person = matches[0]
    events = await db.graph_get_person_events(person["id"])

    # Get places for each event
    event_places = {}
    for evt in events:
        places = await db.graph_get_event_places(evt["id"])
        if places:
            event_places[evt["id"]] = places

    result = format_person_events(person["name"], events, event_places)

    # Append Mermaid timeline
    diagram = mermaid_person_timeline(person["name"], events, event_places)
    if diagram:
        result += f"\n### Timeline Diagram\n{diagram}\n"

    return [TextContent(type="text", text=result)]


async def handle_explore_place(args: dict[str, Any]) -> list[TextContent]:
    """Handle explore_place tool - biblical history of a location."""
    if err := await _check_graph_data():
        return err

    place_name = args.get("place", "")
    if not place_name:
        return [TextContent(type="text", text="Please provide a place name.")]

    matches = await db.graph_find_place(place_name)
    if not matches:
        return [TextContent(type="text", text=f"No place found matching '{place_name}' in the Theographic database.")]

    place = matches[0]
    events = await db.graph_get_place_events(place["id"])
    people = await db.graph_get_place_people(place["id"])

    result = format_place_history(place, events, people)

    # Append Mermaid place network
    diagram = mermaid_place_network(place, events, people)
    if diagram:
        result += f"\n### Place Network Diagram\n{diagram}\n"

    return [TextContent(type="text", text=result)]


async def handle_find_connection(args: dict[str, Any]) -> list[TextContent]:
    """Handle find_connection tool - path between two people."""
    if err := await _check_graph_data():
        return err

    name1 = args.get("person1", "")
    name2 = args.get("person2", "")
    if not name1 or not name2:
        return [TextContent(type="text", text="Please provide both person1 and person2 names.")]

    matches1 = await db.graph_find_person(name1)
    matches2 = await db.graph_find_person(name2)

    if not matches1:
        return [TextContent(type="text", text=f"No person found matching '{name1}'.")]
    if not matches2:
        return [TextContent(type="text", text=f"No person found matching '{name2}'.")]

    person1 = matches1[0]
    person2 = matches2[0]

    path = await db.graph_find_path(person1["id"], person2["id"])
    result = format_connection_path(person1["name"], person2["name"], path)

    # Append Mermaid path diagram
    diagram = mermaid_connection_path(person1["name"], person2["name"], path)
    if diagram:
        result += f"\n### Relationship Diagram\n{diagram}\n"

    return [TextContent(type="text", text=result)]


async def handle_graph_enriched_search(args: dict[str, Any]) -> list[TextContent]:
    """Handle graph_enriched_search tool - verse text + graph context."""
    if err := await _check_graph_data():
        return err

    reference = args.get("reference", "")
    if not reference:
        return [TextContent(type="text", text="Please provide a verse reference (e.g., 'Genesis 22:1').")]

    # Get the verse text
    verse = await db.get_verse(reference)
    normalized = db._normalize_reference(reference)
    entities = await db.graph_get_verse_entities(normalized)

    lines = [f"## {reference}\n"]

    if verse:
        lines.append(verse.get("text_english", ""))
        lines.append("")
        if verse.get("text_original"):
            lines.append(f"**Original**: {verse['text_original']}")
            lines.append("")

    # Add entity context
    people = entities.get("people", [])
    places = entities.get("places", [])
    events = entities.get("events", [])

    if people:
        lines.append("### People Mentioned")
        for p in people:
            name = p.get("entity_name", p.get("entity_id"))
            lines.append(f"\n**{name}**")
            # Get family context for each person
            person_matches = await db.graph_find_person(name)
            if person_matches:
                family = await db.graph_get_family(person_matches[0]["id"])
                parts = []
                if family["parents"]:
                    parent_names = ", ".join(pr["name"] for pr in family["parents"])
                    parts.append(f"Parents: {parent_names}")
                if family["partners"]:
                    partner_names = ", ".join(pr["name"] for pr in family["partners"])
                    parts.append(f"Spouse: {partner_names}")
                if family["children"]:
                    child_names = ", ".join(c["name"] for c in family["children"][:5])
                    suffix = f" (+{len(family['children'])-5} more)" if len(family["children"]) > 5 else ""
                    parts.append(f"Children: {child_names}{suffix}")
                if parts:
                    lines.append("  " + " | ".join(parts))
        lines.append("")

    if places:
        lines.append("### Places Mentioned")
        for p in places:
            lines.append(f"- **{p.get('entity_name', p.get('entity_id'))}**")
        lines.append("")

    if events:
        lines.append("### Events")
        for e in events:
            lines.append(f"- **{e.get('entity_name', e.get('entity_id'))}**")
        lines.append("")

    if not people and not places and not events:
        lines.append("*No entity data available for this verse in the Theographic database.*\n")

    return [TextContent(type="text", text="\n".join(lines))]


async def run_server():
    """Run the MCP server with stdio transport."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )


async def run_sse_server(host: str, port: int):
    """Run the MCP server with SSE transport for remote connections."""
    try:
        from mcp.server.sse import SseServerTransport
        from starlette.applications import Starlette
        from starlette.routing import Route, Mount
        from starlette.responses import JSONResponse, Response
        from starlette.middleware import Middleware
        from starlette.middleware.cors import CORSMiddleware
        import uvicorn
    except ImportError:
        logger.error(
            "SSE transport requires additional dependencies. "
            "Install with: pip install 'study-bible-mcp[sse]' or pip install starlette uvicorn"
        )
        sys.exit(1)

    sse = SseServerTransport("/messages")

    async def handle_sse(request):
        """Handle SSE connection for MCP protocol."""
        async with sse.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await server.run(
                streams[0], streams[1],
                server.create_initialization_options()
            )

    async def handle_messages(request):
        """Handle POST messages for SSE transport."""
        await sse.handle_post_message(request.scope, request.receive, request._send)

    async def health_check(request):
        """Health check endpoint for load balancers and monitoring."""
        db_path = get_db_path()
        db_exists = db_path.exists()

        return JSONResponse({
            "status": "healthy" if db_exists else "degraded",
            "database": str(db_path),
            "database_exists": db_exists,
            "version": "1.0.0",
        })

    async def root(request):
        """Root endpoint with service information."""
        return JSONResponse({
            "name": "Study Bible MCP Server",
            "version": "1.0.0",
            "description": "Bible study tools with Greek/Hebrew lexicons via MCP",
            "endpoints": {
                "/sse": "SSE connection endpoint",
                "/messages": "Message POST endpoint",
                "/health": "Health check endpoint",
                "/static/icon.png": "Server icon",
                "/download/study_bible.db": "Download pre-built database (~600MB)",
            },
            "tools": [tool.name for tool in TOOLS],
        })

    async def serve_icon(request):
        """Serve the server icon as a PNG file."""
        import base64
        icon_bytes = base64.b64decode(ICON_BASE64)
        return Response(content=icon_bytes, media_type="image/png")

    async def serve_database(request):
        """Serve the database file for download."""
        from starlette.responses import FileResponse
        db_path = get_db_path()
        if not db_path.exists():
            return JSONResponse({"error": "Database not found"}, status_code=404)
        return FileResponse(
            path=str(db_path),
            filename="study_bible.db",
            media_type="application/x-sqlite3",
        )

    # Create Starlette app with CORS middleware
    app = Starlette(
        routes=[
            Route("/", endpoint=root, methods=["GET"]),
            Route("/health", endpoint=health_check, methods=["GET"]),
            Route("/static/icon.png", endpoint=serve_icon, methods=["GET"]),
            Route("/download/study_bible.db", endpoint=serve_database, methods=["GET"]),
            Route("/sse", endpoint=handle_sse),
            Route("/messages", endpoint=handle_messages, methods=["POST"]),
        ],
        middleware=[
            Middleware(
                CORSMiddleware,
                allow_origins=["*"],
                allow_credentials=True,
                allow_methods=["*"],
                allow_headers=["*"],
            )
        ],
    )

    logger.info(f"Starting SSE server on {host}:{port}")
    logger.info(f"SSE endpoint: http://{host}:{port}/sse")
    logger.info(f"Health check: http://{host}:{port}/health")

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="info",
        access_log=True,
    )
    server_instance = uvicorn.Server(config)
    await server_instance.serve()


@click.command()
@click.option(
    "--transport",
    type=click.Choice(["stdio", "sse"]),
    default="stdio",
    help="Transport protocol to use",
)
@click.option(
    "--host",
    default="0.0.0.0",
    help="Host for SSE transport",
)
@click.option(
    "--port",
    default=8080,
    type=int,
    envvar="PORT",
    help="Port for SSE transport (default: 8080, or PORT env var)",
)
@click.option(
    "--db-path",
    type=click.Path(),
    envvar="STUDY_BIBLE_DB",
    help="Path to SQLite database",
)
def main(transport: str, host: str, port: int, db_path: str | None):
    """Run the Study Bible MCP server."""
    if db_path:
        os.environ["STUDY_BIBLE_DB"] = db_path

    logger.info(f"Starting Study Bible MCP server (transport: {transport})")

    if transport == "stdio":
        asyncio.run(run_server())
    else:
        asyncio.run(run_sse_server(host, port))


if __name__ == "__main__":
    main()
