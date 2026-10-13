#!/usr/bin/env python3
"""
Study Bible MCP Server

Main server implementation providing Bible study tools via MCP protocol.
Supports stdio, SSE, and Streamable HTTP transports for local and remote deployment.
"""

import asyncio
import contextlib
import logging
import os
import re
import sys
import time
from collections import defaultdict
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

import json

from .database import (
    BOOK_ABBREV_MAP,
    INTERPRETIVE_CASE_KEYS,
    StudyBibleDB,
    expand_single_chapter_reference,
)

# Purple book with gold cross icon (32x32 PNG, base64 encoded)
ICON_BASE64 = "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAAtklEQVR42mNgGOmAEZtgQ9TV/7SwrGGZNiNeB9DKYnwOYcGl6MajG1S1VENOA6s4E4yxounvfw0NDZpYjm4mckgz0drnhMxmIdew5bO3M9w+twfOr5veS5Y5TAOdDUcdMOAOYCE2wWEDqkYueNVEpnpSxwHIqR3ZcmziqMBzNA1QJwqwFTLocT5aEI06YNQBow6gaUGEDUAqGk/qhwCu1iutWsY4+wW0bJYT1S+gZUgMqq7ZKAAA/oE/8EmGTpMAAAAASUVORK5CYII="
from .tools import (
    TOOLS, _truncate, format_lexicon_entry, format_verse, format_name_entry,
    format_genealogy, format_person_events, format_place_history,
    format_passage_entities, format_connection_path,
    format_enriched_verse, format_biblical_version_comparison,
    format_ancient_source_results, format_textual_variant_cases,
    mermaid_genealogy, mermaid_connection_path, mermaid_person_timeline,
    mermaid_place_network,
    format_study_notes, format_dictionary_article, format_key_terms,
    format_ane_context, format_ane_dimensions,
    format_theology_context, format_theology_themes,
    format_torah_weave,
    RESEARCH_SOURCES_DEFAULT_LIMIT, RESEARCH_SOURCES_MAX_LIMIT,
    find_research_sources, format_research_sources,
)
from .hermeneutics import (
    get_genre,
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


def text(msg: str) -> list[TextContent]:
    """Wrap a string in a single-element TextContent list."""
    return [TextContent(type="text", text=msg)]


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


# Tool arguments that hold a Bible reference.
_REFERENCE_ARGUMENTS = ("reference", "biblical_reference")


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle tool calls."""
    global db

    if db is None:
        db_path = get_db_path()
        if not db_path.exists():
            return text(f"Database not found at {db_path}. Please run 'python scripts/build_database.py' first.")
        db = StudyBibleDB(db_path)
        await db.connect()

    handler = _TOOL_HANDLERS.get(name)
    if not handler:
        return text(f"Unknown tool: {name}")

    # Single-chapter books are cited by verse alone ("Jude 3"); every tool
    # parses chapter:verse, so rewrite those citations once at the boundary.
    arguments = dict(arguments or {})
    for key in _REFERENCE_ARGUMENTS:
        if isinstance(arguments.get(key), str):
            arguments[key] = expand_single_chapter_reference(arguments[key])

    try:
        return await handler(arguments)
    except Exception as e:
        logger.exception(f"Error in tool {name}")
        return text(f"Error: {str(e)}")


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
        return text("Please provide either 'strongs' number or 'word' to study.")

    if not entry:
        return text("No entry found for the given word/Strong's number.")

    # Get verses where this word appears
    verses = await db.get_verses_with_strongs(entry["strongs"], limit=5)

    result = format_lexicon_entry(entry)

    if verses:
        result += "\n\n## Example Passages\n"
        for v in verses:
            result += f"\n**{v['reference']}**: {v['text_english']}\n"

    return text(result)


# Upper bound on verses returned by one lookup_verse call; longer passages
# (e.g. Psalm 119) are cut with a note naming the continuation reference.
LOOKUP_VERSE_MAX_VERSES = 50

_LOOKUP_VERSE_FORMS = (
    "a verse ('John 3:16'), a verse range ('Luke 19:1-3'), a cross-chapter "
    "range ('Luke 19:45-20:2'), or a whole chapter ('Psalm 23')"
)


def _passage_label(book_name: str, start: tuple[int, int], end: tuple[int, int]) -> str:
    """Render an English-numbered span as 'Luke 19:1-3' or 'Luke 19:45-20:2'."""
    (sc, sv), (ec, ev) = start, end
    if (sc, sv) == (ec, ev):
        return f"{book_name} {sc}:{sv}"
    if sc == ec:
        return f"{book_name} {sc}:{sv}-{ev}"
    return f"{book_name} {sc}:{sv}-{ec}:{ev}"


async def handle_lookup_verse(args: dict[str, Any]) -> list[TextContent]:
    """Handle lookup_verse tool - get scripture text with optional Greek/Hebrew.

    Accepts single verses, verse ranges, cross-chapter ranges, and whole
    chapters. Verses are matched on English numbering, so OT rows stored with
    split English(Hebrew) references are found too.
    """
    reference = args.get("reference", "").strip()
    include_original = args.get("include_original", True)
    include_morphology = args.get("include_morphology", False)

    if not reference:
        return text("Please provide a verse reference (e.g., 'John 3:16').")

    parsed = db.parse_passage_reference(reference)
    if parsed is None:
        return text(
            f"Could not read '{reference}' as a Bible reference. "
            f"Supported forms: {_LOOKUP_VERSE_FORMS}."
        )
    book, book_name = parsed["book"], parsed["book_name"]

    bounds = await db.get_chapter_verse_bounds(book)
    if not bounds:
        if not await db._table_has_rows("verses"):
            return text(
                "The verses table is missing or empty. "
                "Run 'python scripts/build_database.py' to build it."
            )
        return text(
            f"Unknown book '{book_name}' in '{reference}'. Use a book name or "
            "abbreviation such as 'John', 'Gen', or '1 Corinthians'."
        )

    start_chapter, end_chapter = parsed["start_chapter"], parsed["end_chapter"]
    for chapter in (start_chapter, end_chapter):
        if chapter not in bounds:
            return text(
                f"{book_name} has no chapter {chapter} "
                f"(chapters {min(bounds)}–{max(bounds)})."
            )
    start_verse = parsed["start_verse"]
    if start_verse is None:
        start_verse = bounds[start_chapter][0]
    end_verse = parsed["end_verse"]
    if end_verse is None:
        end_verse = bounds[end_chapter][1]

    first, last = bounds[start_chapter]
    if not first <= start_verse <= last:
        return text(
            f"{book_name} {start_chapter} has no verse {start_verse} "
            f"(verses {first}–{last})."
        )
    if (end_chapter, end_verse) < (start_chapter, start_verse):
        return text(f"Invalid range '{reference}': the end comes before the start.")

    notes = []
    chapter_end = bounds[end_chapter][1]
    if end_verse > chapter_end:
        notes.append(
            f"{book_name} {end_chapter} ends at verse {chapter_end}; "
            f"showing through {end_chapter}:{chapter_end}."
        )
        end_verse = chapter_end

    rows = await db.get_passage(book, start_chapter, start_verse, end_chapter, end_verse)
    if not rows:
        return text(f"No verse text on file for {reference}.")

    # A verse may be stored as several rows; cap on distinct numbered verses
    # (a verse-0 psalm superscription is shown but not counted).
    verse_keys = list(dict.fromkeys((row["chapter"], row["verse"]) for row in rows))
    numbered = [key for key in verse_keys if key[1] > 0]
    if len(numbered) > LOOKUP_VERSE_MAX_VERSES:
        last_shown = numbered[LOOKUP_VERSE_MAX_VERSES - 1]
        rows = [row for row in rows if (row["chapter"], row["verse"]) <= last_shown]
        rest = _passage_label(book_name, numbered[LOOKUP_VERSE_MAX_VERSES], numbered[-1])
        notes.append(
            f"Showing the first {LOOKUP_VERSE_MAX_VERSES} of {len(numbered)} "
            f"verses. Continue with reference='{rest}'."
        )
        verse_keys = [key for key in verse_keys if key <= last_shown]
    shown_start, shown_end = verse_keys[0], verse_keys[-1]
    single = shown_start == shown_end
    if shown_start[1] == 0 and len(verse_keys) > 1:
        shown_start = verse_keys[1]

    # A passage omits the per-word Strong's list (most of its size) unless
    # morphology is requested; a single verse keeps it.
    include_words = single or include_morphology
    verse_text = "\n".join(
        format_verse(row, include_original, include_morphology, include_words)
        for row in rows
    )
    whole_chapters = parsed["start_verse"] is None and parsed["end_verse"] is None
    if single and not notes:
        result = verse_text
    else:
        if whole_chapters and not notes:
            label = f"{book_name} {start_chapter}"
            if end_chapter != start_chapter:
                label += f"-{end_chapter}"
        else:
            label = _passage_label(book_name, shown_start, shown_end)
        header = f"# {label}\n\n"
        if notes:
            header += "".join(f"*{note}*\n" for note in notes) + "\n"
        result = header + verse_text

    # Hints below are emitted once for the whole passage. Their target tools
    # take one verse, so a passage points them at its first numbered verse
    # (skipping a verse-0 psalm title).
    if single and not notes:
        hint_reference = reference
    else:
        first_numbered = next((key for key in verse_keys if key[1] > 0), shown_start)
        hint_reference = _passage_label(book_name, first_numbered, first_numbered)

    genre = get_genre(book)
    if genre:
        result += f"\n\n---\n{format_genre_guidance(genre)}"

    # Hint: Torah Weave structural partners are available for Gen–Deu verses.
    # Kept as a one-line nudge so the agent can follow up with get_torah_weave
    # only when the structural reading is relevant.
    if book in ("Gen", "Exo", "Lev", "Num", "Deu"):
        if await db.has_torah_weave_data():
            if single:
                result += (
                    f"\n\n---\n*Torah Weave structural partners available for this verse "
                    f"via `get_torah_weave` (reference='{hint_reference}') — returns the cells "
                    f"this verse is deliberately paired with under Moshe Kline's Woven "
                    f"Torah hypothesis.*"
                )
            else:
                result += (
                    f"\n\n---\n*Torah Weave structural partners are available per verse "
                    f"via `get_torah_weave` (e.g. reference='{hint_reference}') — returns "
                    f"the cells a verse is deliberately paired with under Moshe Kline's "
                    f"Woven Torah hypothesis.*"
                )

    # Hint: catalogued manuscript-variant or interpretive cases inside the
    # displayed span. The target tool takes one verse, so in a passage each
    # case is cued with its own verse.
    cases = await db.get_textual_variant_cases_in_span(
        book, shown_start[0], shown_start[1], shown_end[0], shown_end[1]
    )
    variant_cases = [case for case in cases if case["case_key"] not in INTERPRETIVE_CASE_KEYS]
    interpretive_cases = [case for case in cases if case["case_key"] in INTERPRETIVE_CASE_KEYS]

    def cued(found: list[dict]) -> str:
        return ", ".join(
            f"{_passage_label(book_name, (case['chapter'], case['verse']), (case['chapter'], case['verse']))}"
            f" ({case['case_key']})"
            for case in found
        )

    if single:
        if variant_cases:
            keys = ", ".join(case["case_key"] for case in variant_cases)
            result += (
                f"\n\n---\n*Textual variant catalogued for this verse ({keys}): "
                f"readings, witnesses, and attributed analysis via "
                f"`get_textual_variant` (reference='{hint_reference}').*"
            )
        elif interpretive_cases:
            result += (
                f"\n\n---\n*Translation and interpretation notes catalogued for this "
                f"verse (no manuscript variant): translation decisions and attributed "
                f"analysis via `get_textual_variant` (reference='{hint_reference}').*"
            )
    else:
        if variant_cases:
            result += (
                f"\n\n---\n*Textual variants catalogued in this passage: {cued(variant_cases)}. "
                f"Readings, witnesses, and attributed analysis via "
                f"`get_textual_variant` with one of those verses as the reference.*"
            )
        if interpretive_cases:
            result += (
                f"\n\n---\n*Translation and interpretation notes (no manuscript variant) "
                f"catalogued in this passage: {cued(interpretive_cases)}. Translation "
                f"decisions and attributed analysis via `get_textual_variant` with one "
                f"of those verses as the reference.*"
            )

    # Hint: NT↔OT LXX-form quotation. Surfaces in both directions — looking up
    # the OT verse mentions the NT quotation, while looking up the NT verse
    # mentions the OT source.
    lxx_hints = await db.get_lxx_quote_hints_for_passage(
        book, shown_start[0], shown_start[1], shown_end[0], shown_end[1]
    )
    if lxx_hints:
        # Show at most 2 hints inline — keep the cue terse.
        cues = []
        for h in lxx_hints[:2]:
            if h["passage_side"] == "ot":
                cue = f"quoted in **{h['nt_display']}** ({h['divergence_type']})"
                own = h["ot_display"]
            else:
                cue = f"quotes **{h['ot_display']}** in its LXX form ({h['divergence_type']})"
                own = h["nt_display"]
            cues.append(cue if single else f"{own} {cue}")
        if len(lxx_hints) > 2:
            cues.append(f"{len(lxx_hints) - 2} more")
        target = (
            f"(reference='{hint_reference}')" if single
            else "with the quoting or quoted verse as the reference"
        )
        result += (
            f"\n\n---\n*NT↔OT LXX-form quotation: " + "; ".join(cues) + ". "
            f"Separated manuscript evidence and attributed analysis via "
            f"`get_textual_variant` {target}.*"
        )

    # Hint: cross-references are nearly always relevant when handling a verse.
    # One-line nudge so the agent reaches for get_cross_references after a
    # bare lookup_verse, and a specialised aside for John/Rev (where Gage's
    # typological pairings are particularly rich).
    if single:
        xref_hint = (
            f"\n\n---\n*Cross-references for this verse are available via "
            f"`get_cross_references` (reference='{hint_reference}') — returns the "
            f"strongest verses traditionally read alongside this one across the "
            f"CH curated set, Burnett's deification chain, and the TSK topical "
            f"index"
        )
    else:
        xref_hint = (
            f"\n\n---\n*Cross-references are indexed per verse: call "
            f"`get_cross_references` with one verse of this passage (e.g. "
            f"reference='{hint_reference}') — returns the strongest verses "
            f"traditionally read alongside it across the CH curated set, "
            f"Burnett's deification chain, and the TSK topical index"
        )
    if book in ("Jhn", "Rev"):
        xref_hint += (
            ", including Gage/Bradley John↔Revelation typological parallels"
        )
    xref_hint += ".*"
    result += xref_hint

    return text(result)


# compare_biblical_versions returns at most this many verses per call.
MAX_COMPARISON_VERSES = 10
_REFERENCE_BOOK = re.compile(r"^\s*(.*?\D)\s*\d+(?:\s*:\s*\d+)?(?:\s*[-–—]\s*\d+(?:\s*:\s*\d+)?)?\s*$")


def _cap_comparison_rows(
    reference: str, rows: list[dict], numbering: str
) -> tuple[list[dict], str]:
    """Keep the first MAX_COMPARISON_VERSES verse groups; say where to resume."""
    def group(row: dict) -> str:
        return row.get("canonical_reference") or f"LXX-only {row['edition_reference']}"

    groups = list(dict.fromkeys(group(row) for row in rows))
    if len(groups) <= MAX_COMPARISON_VERSES:
        return rows, ""
    kept = set(groups[:MAX_COMPARISON_VERSES])
    resume_rows = [row for row in rows if group(row) == groups[MAX_COMPARISON_VERSES]]
    # Greek numbering resumes from the LXX row's own edition reference.
    resume_row = next((row for row in resume_rows if row["version"] == "LXX"), resume_rows[0])
    book = _REFERENCE_BOOK.match(reference)
    if numbering == "canonical" and book and resume_row.get("canonical_chapter"):
        resume = (
            f"'{book.group(1).strip()} {resume_row['canonical_chapter']}:"
            f"{resume_row['canonical_verse']}'"
        )
    else:
        resume = f"{resume_row['edition_reference']} (numbering='lxx')"
    note = (
        f"Showing the first {MAX_COMPARISON_VERSES} of {len(groups)} verses. "
        f"Continue from {resume} in another call."
    )
    return [row for row in rows if group(row) in kept], note


async def handle_compare_biblical_versions(args: dict[str, Any]) -> list[TextContent]:
    """Compare MT/LXX rows with explicit per-verse provenance."""
    reference = args.get("reference", "").strip()
    if not reference:
        return text("Please provide a verse reference (e.g., 'Psalm 24:1').")

    requested = args.get("versions", ["MT", "LXX"])
    if not isinstance(requested, list) or not requested:
        return text("'versions' must be a non-empty list containing MT and/or LXX.")
    versions = list(dict.fromkeys(str(version).upper() for version in requested))
    unsupported = [version for version in versions if version not in {"MT", "LXX"}]
    if unsupported:
        return text(f"Unsupported biblical version(s): {', '.join(unsupported)}. Use MT and/or LXX.")
    numbering = str(args.get("numbering", "canonical")).lower()
    if numbering not in {"canonical", "lxx"}:
        return text(f"Unsupported numbering '{numbering}'. Use 'canonical' (MT/English) or 'lxx' (Greek edition).")

    result = await db.compare_biblical_versions(reference, versions, numbering)
    status = result["status"]
    if status == "invalid_reference":
        return text(
            f"Could not parse '{reference}'. Use 'Book chapter:verse' (e.g. 'Psalm 82:6'), "
            "a range within or across chapters ('Psalm 82:1-8', 'Psalm 81:6-82:1'), "
            "or a whole chapter ('Psalm 82')."
        )
    if status == "new_testament":
        return text(
            f"{reference} is a New Testament reference. compare_biblical_versions covers "
            "Old Testament and Septuagint books only; use lookup_verse for New Testament text."
        )
    if status == "unsupported_book":
        return text(
            f"'{result['book']}' is not a book covered by compare_biblical_versions. Supported: "
            "the Old Testament books (MT and LXX) and the Septuagint-only books Tobit, Judith, "
            "Wisdom, Sirach, Baruch, Letter of Jeremiah, 1-4 Maccabees, 1-2 Esdras, Greek Esther, "
            "Susanna, Bel and the Dragon, Odes, and Psalms of Solomon."
        )
    if status == "missing_data":
        return text(
            "Septuagint comparison data is not in this database (table "
            "biblical_version_verses is missing or empty). Run "
            "`python scripts/upgrade_database.py` to add it."
        )
    lxx_only_note = ""
    if result["lxx_only"]:
        listed = ", ".join(
            f"{row['edition_reference']} ({row['edition']})" for row in result["lxx_only"]
        )
        lxx_only_note = (
            "LXX-only verses with no MT counterpart occupy this position in Greek edition "
            f"numbering: {listed}. Request numbering='lxx' to view them."
        )
    if status == "no_match":
        if result["lxx_only_book"] and "LXX" not in versions:
            return text(
                f"{reference} is in a Septuagint-only book with no Masoretic Text; "
                "include 'LXX' in versions."
            )
        scheme = "Greek edition" if result["numbering"] == "lxx" else "canonical MT/English"
        message = f"No {' or '.join(versions)} text found for {reference} ({scheme} numbering)."
        return text(f"{message}\n\n{lxx_only_note}" if lxx_only_note else message)

    rows, cap_note = _cap_comparison_rows(reference, result["rows"], result["numbering"])
    return text(
        format_biblical_version_comparison(
            reference,
            rows,
            include_original=args.get("include_original", True),
            include_morphology=args.get("include_morphology", False),
            numbering=result["numbering"],
            note=" ".join(part for part in (cap_note, lxx_only_note) if part),
        )
    )


async def handle_search_ancient_sources(args: dict[str, Any]) -> list[TextContent]:
    """Search Josephus with explicit corpus, period, and biblical-link filters."""
    query = args.get("query", "").strip()
    if not query:
        return text("Please provide words to search in the ancient source text.")

    corpus = str(args.get("corpus", "josephus")).lower()
    if corpus != "josephus":
        return text("Unsupported ancient-source corpus. Available corpus: josephus.")
    period = args.get("period")
    periods = {
        "biblical", "persian", "second_temple", "hellenistic",
        "hasmonean", "herodian", "roman", "first_jewish_revolt",
    }
    if period and period not in periods:
        return text(f"Unsupported period: {period}.")
    try:
        limit = int(args.get("limit", 4))
    except (TypeError, ValueError):
        return text("'limit' must be an integer from 1 to 20.")
    if not 1 <= limit <= 20:
        return text("'limit' must be an integer from 1 to 20.")

    biblical_reference = (args.get("biblical_reference") or "").strip() or None
    result = await db.search_ancient_sources(
        query,
        corpus=corpus,
        biblical_reference=biblical_reference,
        period=period,
        limit=limit,
    )
    status = result["status"]
    if status == "invalid_query":
        return text(
            "Please provide words to search in the ancient source text. "
            "Search operators (AND, OR, NOT, NEAR) are ignored."
        )
    if status == "invalid_reference":
        return text(
            f"Unsupported biblical_reference '{biblical_reference}'. Use a book "
            "name with a chapter, verse, or verse range, e.g. 'Luke 21', "
            "'Luke 21:5', or 'Luke 21:5-6'."
        )
    if status == "corpus_missing":
        return text(
            "The Josephus corpus is not in this database (the "
            "ancient_source_passages table is missing or empty). Run "
            "`python scripts/upgrade_database.py` to add it."
        )
    if status == "no_link":
        return text(
            f"No Josephus passage has an editorial biblical link covering "
            f"{biblical_reference}. Biblical links are curated narrative "
            f"overlaps, never inferred from wording; {result['link_count']} "
            f"links currently cover {result['linked_passage_count']} Josephus "
            "passages. Search without biblical_reference to find passages by "
            "wording."
        )
    if status == "no_match":
        filters = [f"biblical_reference={biblical_reference}"] if biblical_reference else []
        if period:
            filters.append(f"period={period}")
        scope = f" with filters {', '.join(filters)}" if filters else ""
        return text(
            "No Josephus passage contains any of the search terms "
            f"({', '.join(result['terms'])}){scope}."
        )
    return text(
        format_ancient_source_results(
            query,
            result["rows"],
            corpus,
            biblical_reference=biblical_reference,
            period=period,
            match=result["match"],
        )
    )


async def handle_search_lexicon(args: dict[str, Any]) -> list[TextContent]:
    """Handle search_lexicon tool - search across lexicon entries."""
    query = args.get("query", "")
    language = args.get("language")  # None means both
    limit = args.get("limit", 10)

    if not query:
        return text("Please provide a search query.")

    entries = await db.search_lexicon(query, language=language, limit=limit)

    if not entries:
        return text(f"No entries found for '{query}'.")

    result = f"## Lexicon Search: '{query}'\n\nFound {len(entries)} entries:\n\n"

    for entry in entries:
        result += f"### {entry['strongs']} - {entry['word']} ({entry['transliteration']})\n"
        result += f"{entry['short_definition']}\n\n"

    return text(result)


_XREF_SOURCE_LABEL = {
    "ch": "Harrison/Romhild",
    "tsk": "TSK",
}


def _format_xref_target(raw: str) -> str:
    """Pretty-print 'Jhn.3.16' as 'Jhn 3:16' for human-friendly output."""
    parts = raw.split(".")
    if len(parts) == 3:
        return f"{parts[0]} {parts[1]}:{parts[2]}"
    return raw


async def handle_get_cross_references(args: dict[str, Any]) -> list[TextContent]:
    """Handle get_cross_references tool - find related passages."""
    reference = args.get("reference")
    theme = args.get("theme")
    source_filter = args.get("source")
    limit_raw = args.get("limit")
    limit = int(limit_raw) if limit_raw is not None else 8
    min_strength_raw = args.get("min_strength")
    min_strength = int(min_strength_raw) if min_strength_raw is not None else None

    if theme:
        refs = await db.get_thematic_references(theme)
        if not refs:
            return text(f"No cross-references found for theme '{theme}'.")

        result = f"## Cross-References: {theme}\n\n"
        for ref in refs:
            result += f"- **{ref['reference']}**: {ref['note']}\n"
        return text(result)

    elif reference:
        refs = await db.get_cross_references(
            reference,
            source_filter=source_filter,
            limit=limit,
            min_strength=min_strength,
        )
        if not refs:
            return text(
                f"No cross-references found for {reference}."
                + (f" (source filter: {source_filter})" if source_filter else "")
            )

        ch_refs = [r for r in refs if r.get("type") == "ch"]
        gage_refs = [r for r in refs if r.get("type") == "gage"]
        burnett_refs = [r for r in refs if r.get("type") == "burnett"]
        tsk_refs = [r for r in refs if r.get("type") == "tsk"]

        result = f"## Cross-References for {reference}\n\n"
        result += (
            f"_{len(refs)} reference(s) returned (cap limit={limit}; "
            f"actual count may be smaller when verse is signal-poor — by design). "
            f"Sources: CH = Harrison/Romhild curated; Gage = Bradley/Gage John↔Rev typology; "
            f"Burnett = JSPL 5.2 (2015) deification chain; TSK = Treasury of Scripture Knowledge._\n\n"
        )

        def fmt_target_with_meta(ref, *, show_tier=True):
            tier = ref.get("tier")
            ss = ref.get("strength_score")
            tier_tag = f" *t{tier}/ss{ss}*" if (show_tier and tier is not None) else ""
            return f"{_format_xref_target(ref['target'])}{tier_tag}"

        if ch_refs:
            result += f"### Curated (CH) — {len(ch_refs)}\n"
            for ref in ch_refs:
                tag = ""
                if ref.get("relevance", 0) >= 2:
                    tag = "  *(canonical direction)*"
                elif ref.get("relevance", 0) == 1:
                    tag = "  *(circle)*"
                tsk_v = ref.get("tsk_votes")
                v_tag = f"  *(also TSK: {tsk_v} votes)*" if tsk_v else ""
                result += f"- {_format_xref_target(ref['target'])}{tag}{v_tag}\n"
            result += "\n"

        if gage_refs:
            result += f"### Gage / Bradley (John↔Rev typology) — {len(gage_refs)}\n"
            for ref in gage_refs:
                rel = ref.get("relevance", 0)
                tier_tag = "parallel" if rel >= 3 else "chiastic (looser)"
                note = ref.get("note") or ""
                result += f"- {_format_xref_target(ref['target'])}  *({tier_tag})*"
                if note:
                    result += f" — {note}"
                result += "\n"
            result += "\n"

        if burnett_refs:
            result += f"### Burnett (JSPL 5.2 (2015) — argued chain) — {len(burnett_refs)}\n"
            for ref in burnett_refs:
                note = ref.get("note") or ""
                result += f"- {_format_xref_target(ref['target'])}"
                if note:
                    result += f" — {note}"
                result += "\n"
            result += "\n"

        if tsk_refs:
            result += f"### TSK — {len(tsk_refs)}\n"
            for ref in tsk_refs:
                votes = ref.get("relevance", 0)
                vote_tag = f"  *(votes: {votes})*" if votes else ""
                result += f"- {_format_xref_target(ref['target'])}{vote_tag}\n"
            result += "\n"

        return text(result)

    else:
        return text("Please provide either 'reference' or 'theme'.")


async def handle_lookup_name(args: dict[str, Any]) -> list[TextContent]:
    """Handle lookup_name tool - get info about biblical names, enriched with ACAI data."""
    name = args.get("name", "")
    name_type = args.get("type")  # person, place, thing

    if not name:
        return text("Please provide a name to look up.")

    entries = await db.lookup_name(name, name_type=name_type)

    if not entries:
        return text(f"No entries found for '{name}'.")

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

    return text(result)


async def handle_parse_morphology(args: dict[str, Any]) -> list[TextContent]:
    """Handle parse_morphology tool - explain grammatical codes."""
    code = args.get("code", "")
    language = args.get("language", "greek")

    if not code:
        return text("Please provide a morphology code to parse.")

    parsing = await db.get_morphology(code, language)

    if not parsing:
        return text(f"Unknown morphology code: {code}")

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

    return text(result)


async def handle_search_by_strongs(args: dict[str, Any]) -> list[TextContent]:
    """Handle search_by_strongs tool - find all verses with a Strong's number."""
    strongs = args.get("strongs", "")
    limit = args.get("limit", 20)

    if not strongs:
        return text("Please provide a Strong's number (e.g., 'G26' or 'H3068').")

    # Get lexicon entry first
    entry = await db.get_lexicon_entry(strongs)
    if not entry:
        return text(f"Unknown Strong's number: {strongs}")

    # Get verses
    verses = await db.get_verses_with_strongs(strongs, limit=limit)

    result = f"## Verses with {strongs} ({entry['word']} - {entry['transliteration']})\n\n"
    result += f"*{entry['short_definition']}*\n\n"

    if verses:
        for v in verses:
            result += f"**{v['reference']}**: {v['text_english']}\n\n"
    else:
        result += "No verses found with this Strong's number in the database.\n"

    return text(result)


async def handle_find_similar_passages(args: dict[str, Any]) -> list[TextContent]:
    """Handle find_similar_passages tool - find semantically similar passages."""
    reference = args.get("reference", "")
    limit = args.get("limit", 10)

    if not reference:
        return text("Please provide a verse reference (e.g., 'John 3:16').")

    # Check if vector search is available
    if not db._vec_loaded:
        error_detail = db._vec_error or "sqlite-vec extension not available"
        return text(f"Vector search unavailable: {error_detail}")

    has_vectors = await db.has_vector_tables()
    if not has_vectors:
        return text("Vector embeddings have not been generated yet. "
                 "Run 'python scripts/generate_embeddings.py' to create them (~$0.01 via OpenAI API).")

    # Find similar passages
    similar = await db.find_similar_passages(reference, limit=limit)

    if not similar:
        return text(f"No similar passages found for {reference}. "
                 "The verse may not exist or embeddings may not be generated.")

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
        passage_text = _truncate(passage['text_combined'], 500, "...")
        result += f"{passage_text}\n\n"

        # Add verse count info
        if passage['verse_count'] > 1:
            result += f"*({passage['verse_count']} verses in this passage)*\n\n"

    return text(result)


# =========================================================================
# Aquifer content handlers
# =========================================================================

async def _check_aquifer_data() -> list[TextContent] | None:
    """Check if Aquifer data is available. Returns error response or None."""
    has_data = await db.has_aquifer_data()
    if not has_data:
        return text("Aquifer data not available. Run 'python scripts/download_stepbible.py --aquifer' and rebuild the database.")
    return None


async def handle_get_study_notes(args: dict[str, Any]) -> list[TextContent]:
    """Handle get_study_notes tool - get study notes for a verse or chapter."""
    reference = args.get("reference", "")
    chapter_only = args.get("chapter_only", False)

    if not reference:
        return text("Please provide a Bible reference (e.g., 'John 3:16' or 'Genesis 1').")

    if err := await _check_aquifer_data():
        return err

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
        return text(f"No study notes found for {reference}.")

    result = f"## Study Notes: {reference}\n\n"
    result += format_study_notes(notes)

    return text(result)


async def handle_get_bible_dictionary(args: dict[str, Any]) -> list[TextContent]:
    """Handle get_bible_dictionary tool - search dictionary articles."""
    topic = args.get("topic", "")

    if not topic:
        return text("Please provide a topic to look up.")

    if err := await _check_aquifer_data():
        return err

    articles = await db.get_bible_dictionary(topic)

    if not articles:
        return text(f"No dictionary article found for '{topic}'.")

    result = format_dictionary_article(articles)

    return text(result)


async def handle_get_key_terms(args: dict[str, Any]) -> list[TextContent]:
    """Handle get_key_terms tool - search FIA Key Terms."""
    term = args.get("term", "")

    if not term:
        return text("Please provide a term to look up.")

    if err := await _check_aquifer_data():
        return err

    terms = await db.get_key_terms(term)

    if not terms:
        return text(f"No key term found for '{term}'.")

    result = format_key_terms(terms)

    return text(result)


# =========================================================================
# ANE context handler
# =========================================================================

_KEY_REF_PATTERN = re.compile(r'(\d?\s*[A-Za-z]+)\s+(\d+)')

def _parse_key_ref_books_chapters(key_refs_json: str | list) -> set[tuple[str, int]]:
    """Parse key_references JSON into {(book_abbr, chapter)} tuples.

    Handles: "Gen 38:6-26", "1 Cor 12:12-27", "Gen 1:1-2:3", "Psalm 104:2-3"
    Returns: {("Gen", 38), ("1Co", 12), ("Gen", 1), ("Psa", 104)}
    """
    refs = json.loads(key_refs_json) if isinstance(key_refs_json, str) else key_refs_json
    if not refs:
        return set()

    result = set()
    for ref in refs:
        m = _KEY_REF_PATTERN.match(ref.strip())
        if m:
            book_raw, chapter_str = m.groups()
            book_key = book_raw.lower().strip()
            book_abbr = BOOK_ABBREV_MAP.get(book_key)
            if not book_abbr:
                book_abbr = book_raw.strip()[:3].title()
            result.add((book_abbr, int(chapter_str)))
    return result

def _refine_broad_entries(entries: list[dict], book_abbr: str, chapter: int | None) -> list[dict]:
    """Promote broad entries with matching key_references; filter zero-overlap.

    For each entry with match_type='broad':
    - If any key_reference matches (book_abbr, chapter) -> promote to 'direct', relevance_score=500
    - Elif no key_reference mentions book_abbr at all -> drop entry
    - Else -> keep as 'broad' (book mentioned but different chapter)
    """
    refined = []
    for entry in entries:
        if entry.get("match_type") != "broad":
            refined.append(entry)
            continue

        key_refs = entry.get("key_references", "[]")
        parsed = _parse_key_ref_books_chapters(key_refs)

        if not parsed:
            refined.append(entry)
            continue

        books_mentioned = {b for b, c in parsed}

        if chapter is not None and (book_abbr, chapter) in parsed:
            entry = dict(entry)
            entry["match_type"] = "direct"
            entry["relevance_score"] = 500
            refined.append(entry)
        elif book_abbr not in books_mentioned:
            continue
        else:
            refined.append(entry)

    return refined

async def handle_get_ane_context(args: dict[str, Any]) -> list[TextContent]:
    """Handle get_ane_context tool - get Ancient Near East background."""
    reference = args.get("reference")
    dimension = args.get("dimension")
    period = args.get("period")
    detail_level = args.get("detail_level", "standard")

    has_data = await db.has_ane_data()
    if not has_data:
        return text("ANE context data not available. Rebuild the database with ANE data files in data/ane_context/.")

    # If no arguments provided, list available dimensions
    if not reference and not dimension and not period:
        dimensions = await db.get_ane_dimensions()
        result = format_ane_dimensions(dimensions)
        return text(result)

    entries = await db.get_ane_context(
        reference=reference,
        dimension=dimension,
        period=period,
    )

    # Post-query: promote/filter broad entries using key_references
    if reference and entries:
        normalized = db._normalize_reference(reference)
        parts = normalized.split(".")
        book_abbr = parts[0] if parts else ""
        chapter = int(parts[1]) if len(parts) > 1 else None
        entries = _refine_broad_entries(entries, book_abbr, chapter)

    if not entries:
        parts = []
        if reference:
            parts.append(f"reference={reference}")
        if dimension:
            parts.append(f"dimension={dimension}")
        if period:
            parts.append(f"period={period}")
        return text(f"No ANE context entries found for {', '.join(parts)}.")

    header = "## Ancient Near East Context"
    if reference:
        header += f" for {reference}"
    header += "\n\n"

    result = header + format_ane_context(entries, detail_level=detail_level)
    return text(result)


# =========================================================================
# Graph tool handlers (Theographic Bible Metadata)
# =========================================================================

async def _check_graph_data() -> list[TextContent] | None:
    """Check if graph data is available. Returns error response or None."""
    has_data = await db.graph_has_data()
    if not has_data:
        return text("Graph data not available. Run 'python scripts/import_theographic.py' to import Theographic Bible Metadata.")
    return None


async def handle_explore_genealogy(args: dict[str, Any]) -> list[TextContent]:
    """Handle explore_genealogy tool - trace family tree."""
    if err := await _check_graph_data():
        return err

    person_name = args.get("person", "")
    direction = args.get("direction", "both")
    generations = args.get("generations", 5)

    if not person_name:
        return text("Please provide a person's name.")

    matches = await db.graph_find_person(person_name)
    if not matches:
        return text(f"No person found matching '{person_name}' in the Theographic database.")

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

    return text(result)


async def handle_people_in_passage(args: dict[str, Any]) -> list[TextContent]:
    """Handle people_in_passage tool - find entities in a verse or chapter."""
    if err := await _check_graph_data():
        return err

    reference = args.get("reference", "")
    if not reference:
        return text("Please provide a Bible reference (e.g., 'Romans 8' or 'Genesis 22:1').")

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
            return text(f"Could not parse reference: {reference}. Use 'Romans 8' or 'Genesis 22:1' format.")

    result = format_passage_entities(reference, entities)
    return text(result)


async def handle_explore_person_events(args: dict[str, Any]) -> list[TextContent]:
    """Handle explore_person_events tool - timeline of a person's life."""
    if err := await _check_graph_data():
        return err

    person_name = args.get("person", "")
    if not person_name:
        return text("Please provide a person's name.")

    matches = await db.graph_find_person(person_name)
    if not matches:
        return text(f"No person found matching '{person_name}' in the Theographic database.")

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

    return text(result)


async def handle_explore_place(args: dict[str, Any]) -> list[TextContent]:
    """Handle explore_place tool - biblical history of a location."""
    if err := await _check_graph_data():
        return err

    place_name = args.get("place", "")
    if not place_name:
        return text("Please provide a place name.")

    matches = await db.graph_find_place(place_name)
    if not matches:
        return text(f"No place found matching '{place_name}' in the Theographic database.")

    place = matches[0]
    events = await db.graph_get_place_events(place["id"])
    people = await db.graph_get_place_people(place["id"])

    result = format_place_history(place, events, people)

    # Append Mermaid place network
    diagram = mermaid_place_network(place, events, people)
    if diagram:
        result += f"\n### Place Network Diagram\n{diagram}\n"

    return text(result)


async def handle_find_connection(args: dict[str, Any]) -> list[TextContent]:
    """Handle find_connection tool - path between two people."""
    if err := await _check_graph_data():
        return err

    name1 = args.get("person1", "")
    name2 = args.get("person2", "")
    if not name1 or not name2:
        return text("Please provide both person1 and person2 names.")

    matches1 = await db.graph_find_person(name1)
    matches2 = await db.graph_find_person(name2)

    if not matches1:
        return text(f"No person found matching '{name1}'.")
    if not matches2:
        return text(f"No person found matching '{name2}'.")

    person1 = matches1[0]
    person2 = matches2[0]

    path = await db.graph_find_path(person1["id"], person2["id"])
    result = format_connection_path(person1["name"], person2["name"], path)

    # Append Mermaid path diagram
    diagram = mermaid_connection_path(person1["name"], person2["name"], path)
    if diagram:
        result += f"\n### Relationship Diagram\n{diagram}\n"

    return text(result)


async def handle_graph_enriched_search(args: dict[str, Any]) -> list[TextContent]:
    """Handle graph_enriched_search tool - verse text + graph context."""
    if err := await _check_graph_data():
        return err

    reference = args.get("reference", "")
    if not reference:
        return text("Please provide a verse reference (e.g., 'Genesis 22:1').")

    # Get the verse text
    verse = await db.get_verse(reference)
    normalized = db._normalize_reference(reference)
    entities = await db.graph_get_verse_entities(normalized)

    # Build family data for each person mentioned
    family_data = {}
    for p in entities.get("people", []):
        name = p.get("entity_name", p.get("entity_id"))
        person_matches = await db.graph_find_person(name)
        if person_matches:
            family_data[name] = await db.graph_get_family(person_matches[0]["id"])

    result = format_enriched_verse(reference, verse, entities, family_data)
    return text(result)


# =========================================================================
# Theological scholarship tool handler
# =========================================================================

async def handle_get_theology_context(args: dict[str, Any]) -> list[TextContent]:
    """Handle get_theology_context tool — theological scholarship by reference, theme, and/or author."""
    author = args.get("author")
    has_data = await db.has_theology_data(author=author)
    if not has_data:
        if author:
            return text(f"No scholarship data found for author '{author}'. Run the import script first.")
        return text("Theological scholarship data not available. Run 'python scripts/import_heiser_content.py' first.")

    reference = args.get("reference")
    theme = args.get("theme")
    limit = args.get("limit", 10)

    # If neither provided, list themes
    if not reference and not theme:
        themes = await db.get_theology_themes(author=author)
        return text(format_theology_themes(themes))

    entries = []
    if theme:
        entries = await db.get_theology_context_by_theme(theme, author=author, limit=limit)
    elif reference:
        entries = await db.get_theology_context_by_reference(reference, author=author, limit=limit)

    if not entries:
        query_desc = f"theme='{theme}'" if theme else f"reference='{reference}'"
        if author:
            query_desc += f" (author='{author}')"
        return text(f"No theological scholarship found for {query_desc}.")

    author_label = author.capitalize() if author else "Theological"
    header = f"## {author_label} Scholarship Context"
    if reference:
        header += f" for {reference}"
    if theme:
        header += f" — theme: {theme}"
    header += "\n\n"

    result = header + format_theology_context(entries)
    return text(result)


async def handle_get_torah_weave(args: dict[str, Any]) -> list[TextContent]:
    """Handle get_torah_weave tool — Moshe Kline's Woven Torah structural partners."""
    reference = args.get("reference", "")
    if not reference:
        return text("Please provide a Bible reference in Genesis–Deuteronomy.")

    has_data = await db.has_torah_weave_data()
    if not has_data:
        return text(
            "Torah Weave data not available. Run "
            "'python scripts/import_torah_weave.py' to import it."
        )

    matches = await db.get_torah_weave_cells_for_reference(reference)
    if not matches:
        return text(
            f"No Torah Weave unit contains {reference}. "
            "Torah Weave data covers Genesis–Deuteronomy only."
        )

    # Fetch full cell sets for each unique unit (needed to compute partners)
    unit_ids = {m["unit_id"] for m in matches}
    unit_cells_by_unit: dict[int, list[dict]] = {}
    for unit_id in unit_ids:
        unit_cells_by_unit[unit_id] = await db.get_torah_weave_unit_cells(unit_id)

    result = format_torah_weave(reference, matches, unit_cells_by_unit)
    return text(result)


_SINGLE_VERSE_REFERENCE = re.compile(r"^[1-3]?[A-Za-z]{2,3}\.\d+\.\d+[a-z]?$")


async def handle_get_textual_variant(args: dict[str, Any]) -> list[TextContent]:
    """Return textual evidence and separately attributed interpretive layers."""
    reference = args.get("reference", "").strip()
    if not reference:
        return text("Please provide a verse reference (OT or NT).")

    status = await db.textual_variant_schema_status()
    if status != "ready":
        reason = {
            "legacy": "still uses the legacy textual-variant schema",
            "missing": "has no textual-variant tables",
            "empty": "has no textual-variant cases loaded",
        }[status]
        return text(
            f"Textual-variant data is unavailable: this database {reason}. "
            "Run `python scripts/upgrade_database.py` to migrate it and import "
            "the bundled variant cases."
        )

    normalized = db._normalize_reference(reference)
    if not _SINGLE_VERSE_REFERENCE.match(normalized):
        return text(
            f"'{reference}' is not a single-verse reference. get_textual_variant "
            "takes one verse, e.g. 'Deuteronomy 32:8' or 'Hebrews 10:5'."
        )

    hints = await db.get_nt_ot_lxx_quote_hints(reference)
    cases = await db.get_textual_variant_cases(reference)

    # A query may use the NT side of a quotation alignment. Resolve its OT
    # variant case without merging the alignment note into manuscript evidence.
    if hints and not cases:
        seen_case_ids: set[int] = set()
        for hint in hints:
            for case in await db.get_textual_variant_cases(hint["ot_reference"]):
                if case["id"] not in seen_case_ids:
                    cases.append(case)
                    seen_case_ids.add(case["id"])

    if not hints and not cases:
        return text(
            f"No textual-variant case or NT quotation alignment is catalogued "
            f"for {reference}."
        )

    return text(format_textual_variant_cases(reference, cases, hints))


async def handle_list_research_sources(args: dict[str, Any]) -> list[TextContent]:
    """Handle list_research_sources tool — curated open repositories to consult."""
    topic = (args.get("topic") or "").strip() or None
    query = (args.get("query") or "").strip() or None
    perspective = (args.get("perspective") or "").strip() or None
    limit = args.get("limit") or RESEARCH_SOURCES_DEFAULT_LIMIT
    limit = max(1, min(int(limit), RESEARCH_SOURCES_MAX_LIMIT))

    matches = find_research_sources(topic=topic, perspective=perspective)
    return text(format_research_sources(
        matches[:limit], total=len(matches), topic=topic, query=query, perspective=perspective,
    ))



_TOOL_HANDLERS = {
    "word_study": handle_word_study,
    "lookup_verse": handle_lookup_verse,
    "compare_biblical_versions": handle_compare_biblical_versions,
    "search_ancient_sources": handle_search_ancient_sources,
    "search_lexicon": handle_search_lexicon,
    "get_cross_references": handle_get_cross_references,
    "lookup_name": handle_lookup_name,
    "parse_morphology": handle_parse_morphology,
    "search_by_strongs": handle_search_by_strongs,
    "find_similar_passages": handle_find_similar_passages,
    "explore_genealogy": handle_explore_genealogy,
    "people_in_passage": handle_people_in_passage,
    "explore_person_events": handle_explore_person_events,
    "explore_place": handle_explore_place,
    "find_connection": handle_find_connection,
    "graph_enriched_search": handle_graph_enriched_search,
    "get_study_notes": handle_get_study_notes,
    "get_bible_dictionary": handle_get_bible_dictionary,
    "get_key_terms": handle_get_key_terms,
    "get_ane_context": handle_get_ane_context,
    "get_theology_context": handle_get_theology_context,
    "get_torah_weave": handle_get_torah_weave,
    "get_textual_variant": handle_get_textual_variant,
    "list_research_sources": handle_list_research_sources,
}


async def run_server():
    """Run the MCP server with stdio transport."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )


# =========================================================================
# Rate limiting middleware
# =========================================================================

class RateLimitMiddleware:
    """Simple in-memory per-IP sliding window rate limiter."""

    def __init__(self, app, max_requests: int = 100, window_seconds: int = 60):
        self.app = app
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)
        # per-IP static-asset counters: [count since last log, last log time]
        self._static_hits: dict[str, list[float]] = defaultdict(lambda: [0, 0.0])

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Extract client IP — behind Fly's proxy scope["client"] is the edge
        # proxy, so prefer the real-client headers it sets
        headers = {k.decode("latin-1").lower(): v.decode("latin-1")
                   for k, v in scope.get("headers", [])}
        client = scope.get("client")
        ip = (headers.get("fly-client-ip")
              or (headers.get("x-forwarded-for") or "").split(",")[0].strip()
              or (client[0] if client else "unknown"))

        # Skip rate limiting for health checks and static assets
        path = scope.get("path", "")
        if path.startswith("/static/"):
            # Log real client IPs hitting static assets (throttled to one
            # line per IP per minute) to identify icon-flooding clients
            hits = self._static_hits[ip]
            hits[0] += 1
            now = time.monotonic()
            if now - hits[1] >= 60:
                logger.info(
                    f"static: {int(hits[0])} request(s) for {path} from {ip} "
                    f"(ua={headers.get('user-agent', '?')[:80]})"
                )
                self._static_hits[ip] = [0, now]
            await self.app(scope, receive, send)
            return
        if path in ("/health", "/"):
            await self.app(scope, receive, send)
            return

        now = time.monotonic()
        window_start = now - self.window_seconds

        # Prune old entries and check count
        timestamps = self._requests[ip]
        self._requests[ip] = [t for t in timestamps if t > window_start]

        if len(self._requests[ip]) >= self.max_requests:
            from starlette.responses import JSONResponse
            response = JSONResponse(
                {"error": "Rate limit exceeded. Max 100 requests per minute."},
                status_code=429,
                headers={"Retry-After": str(self.window_seconds)},
            )
            await response(scope, receive, send)
            return

        self._requests[ip].append(now)
        await self.app(scope, receive, send)


# =========================================================================
# Shared HTTP endpoint handlers
# =========================================================================

def _get_privacy_text() -> str:
    """Read the PRIVACY.md file and return its contents."""
    privacy_path = Path(__file__).parent.parent.parent / "PRIVACY.md"
    if not privacy_path.exists():
        # Fallback for Docker deployments
        privacy_path = Path("/app/PRIVACY.md")
    if privacy_path.exists():
        return privacy_path.read_text()
    return "Privacy policy not found. See https://github.com/djayatillake/studybible-mcp/blob/main/PRIVACY.md"


def _make_shared_routes():
    """Create route handler functions and routes shared by SSE and HTTP transports."""
    from starlette.routing import Route
    from starlette.responses import JSONResponse, Response

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

    async def privacy_policy(request):
        """Serve the privacy policy."""
        return Response(content=_get_privacy_text(), media_type="text/plain; charset=utf-8")

    return [
        Route("/health", endpoint=health_check, methods=["GET"]),
        Route("/static/icon.png", endpoint=serve_icon, methods=["GET"]),
        Route("/download/study_bible.db", endpoint=serve_database, methods=["GET"]),
        Route("/privacy", endpoint=privacy_policy, methods=["GET"]),
    ]


async def run_sse_server(host: str, port: int):
    """Run the MCP server with SSE transport only (legacy)."""
    try:
        from mcp.server.sse import SseServerTransport
        from starlette.applications import Starlette
        from starlette.routing import Route
        from starlette.responses import JSONResponse
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
        async with sse.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await server.run(
                streams[0], streams[1],
                server.create_initialization_options()
            )

    async def handle_messages(request):
        await sse.handle_post_message(request.scope, request.receive, request._send)

    async def root(request):
        return JSONResponse({
            "name": "Study Bible MCP Server",
            "version": "1.0.0",
            "description": "Bible study tools with Greek/Hebrew lexicons via MCP",
            "transport": "sse",
            "endpoints": {
                "/sse": "SSE connection endpoint",
                "/messages": "Message POST endpoint",
                "/health": "Health check",
                "/privacy": "Privacy policy",
            },
            "tools": [tool.name for tool in TOOLS],
        })

    app = Starlette(
        routes=[
            Route("/", endpoint=root, methods=["GET"]),
            *_make_shared_routes(),
            Route("/sse", endpoint=handle_sse),
            Route("/messages", endpoint=handle_messages, methods=["POST"]),
        ],
        middleware=[
            Middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])
        ],
    )

    rate_limited_app = RateLimitMiddleware(app)
    logger.info(f"Starting SSE server on {host}:{port}")

    config = uvicorn.Config(rate_limited_app, host=host, port=port, log_level="info", access_log=True)
    await uvicorn.Server(config).serve()


async def run_http_server(host: str, port: int):
    """Run the MCP server with both Streamable HTTP and SSE transports.

    Serves Streamable HTTP at /mcp and SSE at /sse for backwards compatibility.
    """
    try:
        from mcp.server.sse import SseServerTransport
        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
        from starlette.applications import Starlette
        from starlette.routing import Route, Mount
        from starlette.responses import JSONResponse
        from starlette.middleware import Middleware
        from starlette.middleware.cors import CORSMiddleware
        from collections.abc import AsyncIterator
        import uvicorn
    except ImportError:
        logger.error(
            "HTTP transport requires additional dependencies. "
            "Install with: pip install 'study-bible-mcp[sse]' or pip install starlette uvicorn"
        )
        sys.exit(1)

    # Streamable HTTP session manager. Stateless: no server-side session table,
    # so a machine suspend/restart can never invalidate a client's session id
    # (this server is pure request/response — no server-initiated messages).
    session_manager = StreamableHTTPSessionManager(app=server, stateless=True)

    # SSE transport for backwards compatibility
    sse = SseServerTransport("/messages")

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        async with session_manager.run():
            yield

    async def handle_sse(request):
        async with sse.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await server.run(
                streams[0], streams[1],
                server.create_initialization_options()
            )

    async def handle_messages(request):
        await sse.handle_post_message(request.scope, request.receive, request._send)

    async def root(request):
        return JSONResponse({
            "name": "Study Bible MCP Server",
            "version": "1.0.0",
            "description": "Bible study tools with Greek/Hebrew lexicons via MCP",
            "transports": ["streamable-http", "sse"],
            "endpoints": {
                "/mcp": "Streamable HTTP MCP endpoint (recommended)",
                "/sse": "SSE connection endpoint (legacy)",
                "/messages": "SSE message POST endpoint",
                "/health": "Health check",
                "/privacy": "Privacy policy",
                "/static/icon.png": "Server icon",
                "/download/study_bible.db": "Download pre-built database (~600MB)",
            },
            "tools": [tool.name for tool in TOOLS],
        })

    app = Starlette(
        lifespan=lifespan,
        routes=[
            Route("/", endpoint=root, methods=["GET"]),
            *_make_shared_routes(),
            Mount("/mcp", app=session_manager.handle_request),
            Route("/sse", endpoint=handle_sse),
            Route("/messages", endpoint=handle_messages, methods=["POST"]),
        ],
        middleware=[
            Middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])
        ],
    )

    rate_limited_app = RateLimitMiddleware(app)
    logger.info(f"Starting server on {host}:{port}")
    logger.info(f"  Streamable HTTP: http://{host}:{port}/mcp")
    logger.info(f"  SSE (legacy):    http://{host}:{port}/sse")

    config = uvicorn.Config(rate_limited_app, host=host, port=port, log_level="info", access_log=True)
    await uvicorn.Server(config).serve()


@click.command()
@click.option(
    "--transport",
    type=click.Choice(["stdio", "sse", "http"]),
    default="stdio",
    envvar="TRANSPORT",
    help="Transport protocol to use (http serves both Streamable HTTP and SSE)",
)
@click.option("--host", default="0.0.0.0", help="Host for SSE/HTTP transport")
@click.option("--port", default=8080, type=int, envvar="PORT",
              help="Port for SSE/HTTP transport (default: 8080, or PORT env var)")
@click.option("--db-path", type=click.Path(), envvar="STUDY_BIBLE_DB",
              help="Path to SQLite database")
def main(transport: str, host: str, port: int, db_path: str | None):
    """Run the Study Bible MCP server."""
    if db_path:
        os.environ["STUDY_BIBLE_DB"] = db_path

    logger.info(f"Starting Study Bible MCP server (transport: {transport})")

    if transport == "stdio":
        asyncio.run(run_server())
    elif transport == "sse":
        asyncio.run(run_sse_server(host, port))
    elif transport == "http":
        asyncio.run(run_http_server(host, port))


if __name__ == "__main__":
    main()
