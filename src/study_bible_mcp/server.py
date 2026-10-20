#!/usr/bin/env python3
"""
Study Bible MCP Server

Main server implementation providing Bible study tools via MCP protocol.
Supports stdio, SSE, and Streamable HTTP transports for local and remote deployment.
"""

import asyncio
import contextlib
import difflib
import functools
import json
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

from .corpora import CORPORA, all_periods, resolve_citation
from .database import (
    BOOK_ABBREV_MAP,
    INTERPRETIVE_CASE_KEYS,
    StudyBibleDB,
    expand_single_chapter_reference,
    fold_ancient_search_text,
    merge_english_verses,
)
from .hermeneutics import (
    format_genre_guidance,
    genre_name,
    get_genre,
    get_genre_from_reference,
)
from .morphology import parse_fields
from .observability import (
    RequestLogMiddleware,
    client_tag,
    configure_logging,
    log_tool_call,
    request_ip,
    stats,
    watch_event_loop,
)
from .tools import (
    ANCIENT_LINE_CONTEXT,
    ANCIENT_LOOKUP_DEFAULT,
    ANCIENT_LOOKUP_LIMIT,
    RESEARCH_SOURCES_DEFAULT_LIMIT,
    RESEARCH_SOURCES_MAX_LIMIT,
    TOOLS,
    _truncate,
    bsb_label,
    eponym_ids,
    find_research_sources,
    format_ancient_source_lookup,
    format_ancient_source_results,
    format_ane_context,
    format_ane_dimensions,
    format_biblical_version_comparison,
    format_connection_path,
    format_dictionary_article,
    format_enriched_verse,
    format_genealogy,
    format_key_terms,
    format_lexicon_entry,
    format_name_entry,
    format_passage_entities,
    format_passage_study_notes,
    format_person_choice,
    format_person_events,
    format_place_history,
    format_research_sources,
    format_study_notes,
    format_textual_variant_cases,
    format_theology_context,
    format_theology_themes,
    format_torah_weave,
    format_verse,
    is_nation_mention,
    mermaid_connection_path,
    mermaid_genealogy,
    mermaid_place_network,
    person_label,
    strongs_verse_note,
    verse_english,
    verse_reference,
)

# Purple book with gold cross icon (32x32 PNG, base64 encoded)
ICON_BASE64 = "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAAtklEQVR42mNgGOmAEZtgQ9TV/7SwrGGZNiNeB9DKYnwOYcGl6MajG1S1VENOA6s4E4yxounvfw0NDZpYjm4mckgz0drnhMxmIdew5bO3M9w+twfOr5veS5Y5TAOdDUcdMOAOYCE2wWEDqkYueNVEpnpSxwHIqR3ZcmziqMBzNA1QJwqwFTLocT5aEI06YNQBow6gaUGEDUAqGk/qhwCu1iutWsY4+wW0bJYT1S+gZUgMqq7ZKAAA/oE/8EmGTpMAAAAASUVORK5CYII="

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
_db_lock: asyncio.Lock | None = None

# Read-only connections tool calls run on, so parallel calls (a client often
# sends several at once) do not queue behind one slow query. Override with
# STUDY_BIBLE_DB_READERS; 0 runs every query on the one read-write connection.
DB_READERS = 4


def text(msg: str) -> list[TextContent]:
    """Wrap a string in a single-element TextContent list."""
    return [TextContent(type="text", text=msg)]


class ToolInputError(ValueError):
    """An argument a handler cannot use; call_tool returns the message as the result."""


def bounded_limit(value: Any, maximum: int) -> int:
    """A ``limit`` argument as an int from 1 to ``maximum``, else ToolInputError.

    Handlers call it as ``limit = bounded_limit(args.get("limit", N), MAX)`` before
    touching the database, so the contract test can read the default N and a bad
    value (0, -1, 'many', 2.5, null) gets one clear message naming the range.
    """
    limit = None
    if not isinstance(value, bool):
        if isinstance(value, int):
            limit = value
        elif isinstance(value, float) and value.is_integer():
            limit = int(value)
        elif isinstance(value, str) and value.strip().isdecimal():
            limit = int(value)
    if limit is None or not 1 <= limit <= maximum:
        raise ToolInputError(f"'limit' must be an integer from 1 to {maximum}.")
    return limit


def bounded_offset(value: Any) -> int:
    """An ``offset`` argument (results to skip, for the next page) as an int >= 0."""
    if value is None:
        return 0
    if not isinstance(value, bool):
        if isinstance(value, int) and value >= 0:
            return value
        if isinstance(value, float) and value.is_integer() and value >= 0:
            return int(value)
        if isinstance(value, str) and value.strip().isdecimal():
            return int(value)
    raise ToolInputError("'offset' must be a whole number of results to skip (0 or more).")


def page_window(offset: int, shown: int) -> str:
    """'4' on the first page, else '5–8': the results a 'Showing … of N' note covers."""
    return f"{offset + 1}–{offset + shown}" if offset else str(shown)


def next_page_note(offset: int, shown: int, more: bool) -> str:
    """The note naming the offset that continues a paged list, when more remain."""
    return f"*Next page: offset={offset + shown}.*\n\n" if more else ""


def returns_input_errors(handler):
    """Return a ToolInputError's message as the result, also when the handler is called directly."""
    @functools.wraps(handler)
    async def wrapper(args: dict[str, Any]) -> list[TextContent]:
        try:
            return await handler(args)
        except ToolInputError as error:
            return text(str(error))
    return wrapper


# The largest ``limit`` each list tool accepts (defaults stay at most 4).
ANCIENT_SEARCH_MAX = 20
LEXICON_SEARCH_MAX = 20
CROSS_REFERENCE_MAX = 50
NAME_LOOKUP_MAX = 20
STRONGS_SEARCH_MAX = 50
SIMILAR_PASSAGES_MAX = 20
THEOLOGY_MAX = 20
ANE_CONTEXT_MAX = 30
# Rows get_ane_context reads before choosing `limit` (more than any passage has).
ANE_CONTEXT_FETCH = 500
# get_key_terms prints at most this many full entries.
KEY_TERMS_SHOWN = 2


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


def _db_readers() -> int:
    try:
        return max(0, int(os.environ.get("STUDY_BIBLE_DB_READERS", DB_READERS)))
    except ValueError:
        return DB_READERS


async def open_database() -> StudyBibleDB | None:
    """The shared database, opened once on first use; None if the file is missing."""
    global db, _db_lock
    if db is not None:
        return db
    if _db_lock is None:
        _db_lock = asyncio.Lock()
    # Concurrent first calls must not each open (and leak) their own pool.
    async with _db_lock:
        if db is None:
            db_path = get_db_path()
            if not db_path.exists():
                return None
            database = StudyBibleDB(db_path, readers=_db_readers())
            await database.connect()
            db = database
    return db


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List all available Bible study tools."""
    return TOOLS


# Tool arguments that hold a Bible reference.
_REFERENCE_ARGUMENTS = ("reference", "biblical_reference")


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle tool calls, logging each one (outcome, duration, size, arguments)."""
    start = time.monotonic()
    requested = arguments
    result: list[TextContent] = []
    outcome, wait, failure = "ok", 0.0, None
    try:
        if await open_database() is None:
            outcome = "no-database"
            result = text(
                f"Database not found at {get_db_path()}. "
                "Please run 'python scripts/build_database.py' first."
            )
            return result

        handler = _TOOL_HANDLERS.get(name)
        if not handler:
            outcome = "unknown-tool"
            result = text(f"Unknown tool: {name}")
            return result

        # Single-chapter books are cited by verse alone ("Jude 3"); every tool
        # parses chapter:verse, so rewrite those citations once at the boundary.
        arguments = dict(arguments or {})
        for key in _REFERENCE_ARGUMENTS:
            if isinstance(arguments.get(key), str):
                arguments[key] = expand_single_chapter_reference(arguments[key])

        # A read connection of its own, so parallel calls query in parallel (a
        # stand-in database without a pool, as some tests use, runs as is).
        reading = getattr(db, "reading", None)
        try:
            async with reading() if reading else contextlib.nullcontext():
                wait = time.monotonic() - start
                result = await handler(arguments)
        except ToolInputError as e:
            outcome = "bad-input"
            result = text(str(e))
        except Exception as e:
            outcome, failure = "error", e
            result = text(f"Error: {str(e)}")
        return result
    except asyncio.CancelledError:
        outcome = "cancelled"
        raise
    finally:
        log_tool_call(
            name, requested, time.monotonic() - start,
            sum(len(getattr(item, "text", "")) for item in result), outcome, wait, failure,
        )


# word_study shows this many example passages (search_by_strongs lists more).
WORD_STUDY_EXAMPLES = 4


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
    verses = await db.get_verses_with_strongs(entry["strongs"], limit=WORD_STUDY_EXAMPLES)

    result = format_lexicon_entry(entry)

    if verses:
        result += f"\n\n## Example Passages{bsb_label(verses)}\n"
        for v in verses:
            result += f"\n**{verse_reference(v)}**: {verse_english(v)}\n"

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
        message = f"{book_name} {start_chapter} has no verse {start_verse} (verses {first}–{last})."
        # 3 John 1:15 in Greek-numbered editions is part of the BSB's 1:14.
        english = await db.english_verse_of_greek(book, start_chapter, start_verse)
        if english:
            message += (
                f" The Greek text's {start_chapter}:{start_verse} is counted with "
                f"{book_name} {english[0]}:{english[1]} here."
            )
        return text(message)
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

    # One block per English verse: a verse stored as several rows (two Hebrew
    # superscription verses, a Greek fragment) shows its BSB text once.
    rows = merge_english_verses(
        await db.get_passage(book, start_chapter, start_verse, end_chapter, end_verse)
    )
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
    # morphology is requested; a single verse keeps it. The BSB label goes on
    # the response's first heading.
    include_words = single or include_morphology
    bsb = bsb_label(rows)
    verse_text = "\n".join(
        format_verse(
            row, include_original, include_morphology, include_words,
            heading_note=bsb if single and not notes and index == 0 else "",
        )
        for index, row in enumerate(rows)
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
        header = f"# {label}{bsb}\n\n"
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

    # One line names the genre; the guidance itself (~1 KB) only on request.
    genre = get_genre(book, shown_start[0])
    if genre:
        if args.get("include_genre", False):
            result += f"\n\n---\n{format_genre_guidance(genre)}"
        else:
            result += (
                f"\n\n---\n*Genre: {genre_name(genre)}. "
                f"Interpretive guidance: include_genre=true.*"
            )

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
    # A verse with a variant is cued once, as a variant: get_textual_variant
    # returns its interpretation notes with it, and they are not "no variant".
    variant_verses = {(case["chapter"], case["verse"]) for case in variant_cases}
    interpretive_cases = [
        case for case in cases
        if case["case_key"] in INTERPRETIVE_CASE_KEYS
        and (case["chapter"], case["verse"]) not in variant_verses
    ]

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
                f"verse (no manuscript variant): attributed analysis via "
                f"`get_textual_variant` (reference='{hint_reference}').*"
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
                f"catalogued in this passage: {cued(interpretive_cases)}. Attributed "
                f"analysis via `get_textual_variant` with one of those verses as the "
                f"reference.*"
            )

    # Hint: NT↔OT quotation alignment, usually an LXX-form quotation. Surfaces
    # in both directions — looking up the OT verse mentions the NT quotation,
    # while looking up the NT verse mentions the OT source. A quotation that
    # agrees with the MT (follows_lxx = 0) is not called an LXX form.
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
                form = " in its LXX form" if h["follows_lxx"] else ""
                cue = f"quotes **{h['ot_display']}**{form} ({h['divergence_type']})"
                own = h["nt_display"]
            cues.append(cue if single else f"{own} {cue}")
        if len(lxx_hints) > 2:
            cues.append(f"{len(lxx_hints) - 2} more")
        target = (
            f"(reference='{hint_reference}')" if single
            else "with the quoting or quoted verse as the reference"
        )
        label = (
            "NT↔OT LXX-form quotation" if all(h["follows_lxx"] for h in lxx_hints)
            else "NT↔OT quotation"
        )
        result += (
            f"\n\n---\n*{label}: " + "; ".join(cues) + ". "
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


def _ancient_scope_label(corpus: str | None) -> str:
    return CORPORA[corpus].label if corpus else "ancient-source"


ANCIENT_UPGRADE_MESSAGE = (
    "This database's ancient-source tables predate the current schema (typed biblical "
    "links, editorial notes, and the search index). Run `python scripts/upgrade_database.py` "
    "to upgrade it."
)


@returns_input_errors
async def handle_search_ancient_sources(args: dict[str, Any]) -> list[TextContent]:
    """Search registered ancient-source corpora with period and biblical-link filters."""
    query = args.get("query", "").strip()
    if not query:
        return text("Please provide words to search in the ancient source text.")

    corpus_arg = str(args.get("corpus", "josephus")).lower()
    if corpus_arg != "all" and corpus_arg not in CORPORA:
        return text(
            f"Unsupported ancient-source corpus '{corpus_arg}'. Available corpora: "
            f"{', '.join(CORPORA)}, or 'all'."
        )
    corpus = None if corpus_arg == "all" else corpus_arg
    period = args.get("period")
    periods = CORPORA[corpus].periods if corpus else all_periods()
    if period and period not in periods:
        return text(f"Unsupported period: {period}. Periods: {', '.join(periods)}.")
    limit = bounded_limit(args.get("limit", 4), ANCIENT_SEARCH_MAX)

    biblical_reference = (args.get("biblical_reference") or "").strip() or None
    result = await db.search_ancient_sources(
        query,
        corpus=corpus,
        biblical_reference=biblical_reference,
        period=period,
        limit=limit,
    )
    status = result["status"]
    label = _ancient_scope_label(corpus)
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
    if status == "outdated_schema":
        return text(ANCIENT_UPGRADE_MESSAGE)
    if status == "corpus_missing":
        scope = f"The {label} corpus is" if corpus else "No ancient-source corpus is"
        return text(
            f"{scope} not in this database (the ancient_source_passages table "
            "is missing or empty). Run `python scripts/upgrade_database.py` to add it."
        )
    if status == "no_link":
        return text(
            f"No {label} passage has an editorial biblical link covering "
            f"{biblical_reference}. Biblical links are curated narrative "
            f"overlaps, never inferred from wording; {result['link_count']} "
            f"links currently cover {result['linked_passage_count']} {label} "
            "passages. Search without biblical_reference to find passages by "
            "wording."
        )
    if status == "no_match":
        filters = [f"biblical_reference={biblical_reference}"] if biblical_reference else []
        if period:
            filters.append(f"period={period}")
        scope = f" with filters {', '.join(filters)}" if filters else ""
        message = (
            f"No {label} passage contains any of the search terms "
            f"({', '.join(result['terms'])}){scope}."
        )
        if (
            corpus and not _ORIGINAL_LETTERS.search(query)
            and not await db.ancient_corpus_has_english(corpus)
        ):
            message += " " + await _original_script_hint(corpus, query)
        elif corpus:
            message += await _other_corpora_hint(query, corpus, biblical_reference, period)
        return text(message)
    return text(
        format_ancient_source_results(
            query,
            result["rows"],
            corpus_arg,
            biblical_reference=biblical_reference,
            period=period,
            match=result["match"],
            prefix_match=result["prefix_match"],
            variants=result.get("variants"),
        )
    )


_HINT_STOP = frozenset({"the", "and", "for", "with", "who", "his", "her", "from", "that", "this"})
# Greek or Hebrew letters: a query in an original script.
_ORIGINAL_LETTERS = re.compile(r"[\u0370-\u03ff\u1f00-\u1fff\u0590-\u05ff]")


async def _original_script_hint(corpus: str, query: str) -> str:
    """Why an English query finds nothing in an untranslated corpus, with Hebrew words to try."""
    registered = CORPORA[corpus]
    suggestions = []
    words = [word for word in re.findall(r"[A-Za-z]{3,}", query) if word.lower() not in _HINT_STOP]
    for word in words[:3]:
        # The commonest entry glossed by the word itself ('righteousness' -> צדקה).
        gloss = re.compile(rf"\b{re.escape(word.lower())}\b", re.IGNORECASE)
        glossed = [
            entry for entry in await db.search_lexicon(word, language="hebrew", limit=10)
            if gloss.search(entry.get("short_definition") or "")
        ]
        if glossed:
            entry = max(glossed, key=lambda entry: entry.get("usage_count") or 0)
            hebrew = fold_ancient_search_text(entry["word"])
            suggestions.append(f"{hebrew} ({entry['strongs']}, '{entry['short_definition']}')")
    if not suggestions:
        suggestions.append(f"'{registered.example_query}'")
    return (
        f"The {registered.label} corpus has no English translation: search it in "
        f"{registered.original_language} script, e.g. {'; '.join(suggestions)}."
    )


async def _other_corpora_hint(
    query: str, corpus: str, biblical_reference: str | None, period: str | None
) -> str:
    """' Other corpora match: …' when the same search finds passages outside ``corpus``."""
    if period and period not in all_periods():
        return ""
    found = await db.search_ancient_sources(
        query, corpus=None, biblical_reference=biblical_reference, period=period, limit=20
    )
    if found["status"] != "ok":
        return ""
    others = list(dict.fromkeys(
        row["corpus"] for row in found["rows"] if row.get("corpus") != corpus
    ))
    if not others:
        return ""
    return f" Other corpora match ({', '.join(others)}): retry with corpus='all'."


def _citable_works() -> str:
    """A short summary of the citable works: names for small corpora, a count and example otherwise."""
    parts = []
    for corpus in CORPORA.values():
        works = corpus.works
        if len(works) <= 4:
            names = ", ".join(work.display_title for work in works)
        else:
            collections = {work.collection.title for work in works if work.collection}
            prefix = f"{collections.pop()}, " if len(collections) == 1 else ""
            names = f"{prefix}{len(works)} works"
        parts.append(f"{corpus.label} ({names}; e.g. '{corpus.example_citation}')")
    return "; ".join(parts)


# A locator at the end of a citation ('18.116', '3:13-4:2', 'vi 11'), dropped
# before suggesting a work name for an unknown citation.
_TRAILING_LOCATOR = re.compile(r"[\s.,]+[\divxlc][\divxlc\s.:,\-–]*$", re.IGNORECASE)


def _similar_works(citation: str) -> list[str]:
    """Work names close to an unrecognised citation's name ('Antiquites' -> 'Antiquities')."""
    name = _TRAILING_LOCATOR.sub("", citation).strip().lower()
    titles = {
        title.lower(): work.display_title
        for corpus in CORPORA.values()
        for work in corpus.works
        for title in (*work.names, work.display_title)
    }
    matches = difflib.get_close_matches(name, titles, n=3, cutoff=0.75)
    return list(dict.fromkeys(titles[match] for match in matches))


def _candidate(match) -> str:
    locator = match.work.locator
    books = getattr(locator, "books", None)
    grammar = f"{locator.name}, books 1–{books}" if books else locator.name
    return f"{match.work.display_title} ({match.corpus.label}, cited by {grammar})"


async def _work_example(match) -> str:
    """A citation of the first imported passage of the matched work, else its grammar example."""
    work = match.work
    first = await db.first_ancient_passage(match.corpus.key, work.key)
    if first:
        return f"'{work.display_title} {work.locator.format_range(first['sort_start'], first['sort_start'])}'"
    return f"'{work.display_title} {work.locator.example}'"


def _line_window(corpus, work, start: int, end: int) -> tuple[int, int] | None:
    """For a line-numbered corpus, the cited lines ±ANCIENT_LINE_CONTEXT (a whole-column citation gets None)."""
    scale = getattr(work.locator, "scale", None)
    if not corpus.line_numbered or scale is None:
        return None
    if start % scale == 0 and end % scale == scale - 1:
        return None
    return start - ANCIENT_LINE_CONTEXT, end + ANCIENT_LINE_CONTEXT


@returns_input_errors
async def handle_lookup_ancient_source(args: dict[str, Any]) -> list[TextContent]:
    """Resolve an ancient-source citation and return the overlapping passages."""
    citation = str(args.get("citation") or "").strip()
    if not citation:
        return text(
            "Please provide a citation such as 'Antiquities 18.116'. Citable works: "
            f"{_citable_works()}."
        )
    corpus_key = args.get("corpus")
    if corpus_key and corpus_key not in CORPORA:
        return text(
            f"Unsupported ancient-source corpus '{corpus_key}'. Available corpora: "
            f"{', '.join(CORPORA)}."
        )
    limit = bounded_limit(args.get("limit", ANCIENT_LOOKUP_DEFAULT), ANCIENT_LOOKUP_LIMIT)
    corpora = [CORPORA[corpus_key]] if corpus_key else list(CORPORA.values())
    resolution = resolve_citation(citation, corpora)
    if resolution.status == "unknown_work":
        similar = _similar_works(citation)
        hint = f" Did you mean {' or '.join(similar)}?" if similar else ""
        return text(
            f"Unknown work in citation '{citation}'.{hint} Citable works: {_citable_works()}."
        )
    if resolution.status == "ambiguous":
        return text(
            f"Ambiguous citation '{citation}': it matches "
            + "; ".join(_candidate(match) for match in resolution.candidates)
            + ". Add a collection or work name to choose one."
        )
    if resolution.status == "bad_locator":
        locator = resolution.candidates[0].locator_text
        problem = f"Could not read the locator '{locator}'" if locator else "No locator"
        examples = ", ".join(dict.fromkeys(
            [await _work_example(match) for match in resolution.candidates]
        ))
        return text(
            f"{problem} in '{citation}'. Expected: "
            + "; ".join(_candidate(match) for match in resolution.candidates)
            + f"; e.g. {examples}."
        )

    match = resolution.match
    work, corpus = match.work, match.corpus
    start, end = match.sort_range
    result = await db.lookup_ancient_passages(corpus.key, work.key, start, end, limit)
    if result["status"] == "outdated_schema":
        return text(ANCIENT_UPGRADE_MESSAGE)
    if result["status"] == "corpus_missing":
        return text(
            f"The {corpus.label} corpus is not in this database (or was imported "
            "before citation lookup existed). Run `python scripts/upgrade_database.py` "
            "to add it."
        )
    if result["status"] == "out_of_range":
        if result["first"] is None:
            return text(f"No {work.display_title} passages are imported in this database.")
        nearest = [
            f"{side} {result[key]}"
            for side, key in (("preceding", "before"), ("following", "after"))
            if result[key]
        ]
        gaps = "".join(
            f" ⚠ {note['citation']}: {note['note']}" for note in result.get("gap_notes") or ()
        )
        return text(
            f"No passage covers {match.heading}. Imported {work.display_title} runs "
            f"{work.display_title} {work.locator.format_range(result['first'], result['last'])}"
            + (f"; nearest passages: {', '.join(nearest)}." if nearest else ".")
            + (f" {work.coverage_note}" if work.coverage_note else "")
            + gaps
        )
    count = result["total"]
    note = (
        f"{corpus.label}, {work.title} ({work.locator.name} "
        f"{work.locator.format_range(start, end)}): {count} overlapping "
        f"passage{'s' if count != 1 else ''}"
    )
    return text(
        format_ancient_source_lookup(
            match.heading,
            note,
            result["rows"],
            count,
            include_original=args.get("include_original", True),
            full_text=bool(args.get("full_text", False)),
            window=_line_window(corpus, work, start, end),
            next_citation=lambda row: (
                f"{work.display_title} "
                f"{work.locator.format_range(row['sort_start'], row['sort_start'])}"
            ),
        )
    )


@returns_input_errors
async def handle_search_lexicon(args: dict[str, Any]) -> list[TextContent]:
    """Handle search_lexicon tool - search across lexicon entries."""
    query = args.get("query", "")
    language = args.get("language")  # None means both
    limit = bounded_limit(args.get("limit", 4), LEXICON_SEARCH_MAX)
    offset = bounded_offset(args.get("offset"))

    if not query:
        return text("Please provide a search query.")

    # One extra row says whether another page exists.
    entries = (await db.search_lexicon(query, language=language, limit=offset + limit + 1))[offset:]
    more = len(entries) > limit
    entries = entries[:limit]

    if not entries:
        if offset:
            return text(f"No more entries for '{query}' at offset {offset}.")
        return text(f"No entries found for '{query}'.")

    shown = f" (results {page_window(offset, len(entries))})" if offset else ""
    result = f"## Lexicon Search: '{query}'\n\nFound {len(entries)} entries{shown}:\n\n"
    result += next_page_note(offset, len(entries), more)

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


@returns_input_errors
async def handle_get_cross_references(args: dict[str, Any]) -> list[TextContent]:
    """Handle get_cross_references tool - find related passages."""
    reference = args.get("reference")
    theme = args.get("theme")
    source_filter = args.get("source")
    limit = bounded_limit(args.get("limit", 4), CROSS_REFERENCE_MAX)
    offset = bounded_offset(args.get("offset"))
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
            limit=offset + limit + 1,
            min_strength=min_strength,
        )
        # Rows are ranked, so a page is a slice; the extra row says whether another exists.
        refs = refs[offset:]
        more = len(refs) > limit
        refs = refs[:limit]
        if not refs and offset:
            return text(f"No more cross-references for {reference} at offset {offset}.")
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
        if offset:
            result += f"*Results {page_window(offset, len(refs))}.*\n\n"
        result += next_page_note(offset, len(refs), more)

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


@returns_input_errors
async def handle_lookup_name(args: dict[str, Any]) -> list[TextContent]:
    """Handle lookup_name tool - get info about biblical names, enriched with ACAI data."""
    name = args.get("name", "")
    name_type = args.get("type")  # person, place, thing

    if not name:
        return text("Please provide a name to look up.")
    limit = bounded_limit(args.get("limit", 4), NAME_LOOKUP_MAX)
    offset = bounded_offset(args.get("offset"))

    entries = (await db.lookup_name(name, name_type=name_type, limit=offset + limit))[offset:]

    if not entries:
        if offset:
            return text(f"No more names matching '{name}' at offset {offset}.")
        return text(f"No entries found for '{name}'.")

    # ACAI enrichment, matched to each entry's own TIPNR entry so that
    # namesakes and 'City of David' are not annotated with King David's data
    acai: list[dict | None] = [None] * len(entries)
    try:
        if await db.has_acai_data():
            acai = await db.get_acai_entities_for_names(entries)
    except Exception:
        pass  # e.g. a database from before acai_entities.tipnr_keys

    result = f"## Biblical Names: {name}\n\n"
    total = entries[0]["match_count"]
    more = total > offset + len(entries)
    if more or offset:
        how = "raise limit" if name_type else "set type or raise limit"
        result += (
            f"*Showing {page_window(offset, len(entries))} of {total} matching names; {how} "
            "(at most 20) to see more.*\n\n"
        )
        result += next_page_note(offset, len(entries), more)

    for entry, acai_data in zip(entries, acai):
        result += format_name_entry(entry, acai_data=acai_data)
        result += "\n---\n\n"

    return text(result)


def _morphology_lines(row: dict) -> list[str]:
    """Header lines for one code: its expansion's fields, in order."""
    fields = parse_fields(row.get("parsing"))
    if fields:
        return [f"**{label}**: {value}" for label, value in fields]
    # An expansion not in Key=Value form: the stored columns, then the text.
    lines = []
    for column, label in (
        ("part_of_speech", "Part of Speech"), ("person", "Person"), ("number", "Number"),
        ("tense", "Tense"), ("voice", "Voice"), ("mood", "Mood"), ("case_value", "Case"),
        ("gender", "Gender"),
    ):
        if row.get(column):
            lines.append(f"**{label}**: {row[column]}")
    if row.get("parsing") and row["parsing"] != row.get("part_of_speech"):
        lines.append(f"\n**Full Parsing**: {row['parsing']}")
    return lines


def _morphology_summary(row: dict) -> str:
    """One line for a code: 'Verb; Stem: Qal (...); Person: Third; ...'."""
    fields = parse_fields(row.get("parsing"))
    if not fields:
        return row.get("parsing") or row.get("part_of_speech") or ""
    return "; ".join(
        value if label == "Part of Speech" else f"{label}: {value}" for label, value in fields
    )


async def handle_parse_morphology(args: dict[str, Any]) -> list[TextContent]:
    """Handle parse_morphology tool - explain grammatical codes."""
    code = (args.get("code") or "").strip()
    language = args.get("language", "greek")

    if not code:
        return text("Please provide a morphology code to parse.")

    found = await db.resolve_morphology(code, language)
    if not found:
        return text(f"Unknown morphology code: {code}")

    if "ambiguous" in found:
        lines = [f"## Morphology: {code}", "", "Codes are case-sensitive, and this one fits more than one:"]
        for segment, rows in found["ambiguous"]:
            for row in rows:
                lines.append(f"- '{segment}' as **{row['code']}**: {_morphology_summary(row)}")
        return text("\n".join(lines))

    parts = found["parts"]
    language_name = found["language"].title()
    if found["language"] == "hebrew" and parts[0][1]["code"].startswith("A"):
        language_name = "Aramaic"
    lines = [f"## Morphology: {code}", "", f"**Language**: {language_name}"]
    if len(parts) == 1:
        lines += _morphology_lines(parts[0][1])
    else:
        joiner = "/" if found["language"] == "hebrew" else "+"
        lines.append(f"**Parts**: {len(parts)} words joined by '{joiner}'")
        lines.append("")
        for number, (segment, row) in enumerate(parts, 1):
            lines.append(f"**{number}. {segment}**: {_morphology_summary(row)}")
    return text("\n".join(lines) + "\n")


@returns_input_errors
async def handle_search_by_strongs(args: dict[str, Any]) -> list[TextContent]:
    """Handle search_by_strongs tool - find all verses with a Strong's number."""
    strongs = args.get("strongs", "")
    limit = bounded_limit(args.get("limit", 4), STRONGS_SEARCH_MAX)
    offset = bounded_offset(args.get("offset"))

    if not strongs:
        return text("Please provide a Strong's number (e.g., 'G26' or 'H3068').")

    # Get lexicon entry first
    entry = await db.get_lexicon_entry(strongs)
    if not entry:
        return text(f"Unknown Strong's number: {strongs}")

    # One extra row says whether more exist; only then are they counted.
    verses = await db.get_verses_with_strongs(strongs, limit=limit + 1, offset=offset)
    more = len(verses) > limit
    verses = verses[:limit]
    if offset and not verses:
        return text(f"No more verses with {strongs} at offset {offset}.")

    result = (
        f"## Verses with {strongs} ({entry['word']} - {entry['transliteration']})"
        f"{bsb_label(verses)}\n\n"
    )
    result += f"*{entry['short_definition']}*\n\n"
    if more or offset:
        total = await db.count_verses_with_strongs(strongs)
        result += (
            f"*Showing {page_window(offset, len(verses))} of {total} verses; raise limit "
            f"(at most {STRONGS_SEARCH_MAX}) to see more.*\n\n"
        )
        result += next_page_note(offset, len(verses), more)

    if verses:
        for v in verses:
            result += f"**{verse_reference(v)}**: {verse_english(v)}{strongs_verse_note(v, strongs)}\n\n"
    else:
        result += "No verses found with this Strong's number in the database.\n"

    return text(result)


@returns_input_errors
async def handle_find_similar_passages(args: dict[str, Any]) -> list[TextContent]:
    """Handle find_similar_passages tool - find semantically similar passages."""
    reference = args.get("reference", "").strip()
    limit = bounded_limit(args.get("limit", 4), SIMILAR_PASSAGES_MAX)

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

    # Embeddings are per verse: a range or chapter is searched from its first verse.
    parsed = db.parse_passage_reference(reference)
    if parsed is None:
        return text(
            f"Could not read '{reference}' as a verse reference. "
            "Use 'Book chapter:verse', e.g. 'John 3:16' or 'Daniel 7:13'."
        )
    first_verse = parsed["start_verse"] or 1
    source_reference = f"{parsed['book_name']} {parsed['start_chapter']}:{first_verse}"
    range_note = ""
    if parsed["start_verse"] is None or (parsed["end_chapter"], parsed["end_verse"]) != (
        parsed["start_chapter"], parsed["start_verse"]
    ):
        range_note = (
            f"*Similarity is computed from one verse: {source_reference}, the first "
            f"verse of '{reference}'. Call again with another verse to search from it.*\n\n"
        )

    source_verse = await db.get_verse(source_reference)
    if source_verse is None:
        return text(
            f"{source_reference} is not in the verse table: check the book, "
            "chapter, and verse numbers."
        )
    if await db.get_verse_embedding(source_verse["id"]) is None:
        return text(
            f"{source_reference} has no pre-computed embedding, so similar passages "
            "cannot be ranked from it. Try a neighbouring verse."
        )

    # Find similar passages
    similar = await db.find_similar_passages(source_reference, limit=limit)

    if not similar:
        return text(f"No similar passages found for {source_reference}.")

    source_genre = get_genre_from_reference(source_reference)

    shown = [source_verse]
    for passage in similar:
        shown += passage.get("preview_verses", [])
    result = f"## Passages Similar to {source_reference}{bsb_label(shown)}\n\n" + range_note

    if source_verse:
        result += f"**Source**: {verse_english(source_verse)}\n\n"

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

        # Show passage text (truncated if very long): the BSB when loaded
        if "preview_verses" in passage:
            passage_text = " ".join(
                verse_english(v) for v in merge_english_verses(passage["preview_verses"])
            )
        else:
            passage_text = passage["text_combined"]
        passage_text = _truncate(passage_text, 500, "...")
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


def _parse_single_chapter(reference: str) -> tuple[str, int] | None:
    """(book code, chapter) for a whole-chapter reference such as 'Song of Solomon 2'.

    None for verses, chapter ranges, and anything unparseable.
    """
    parsed = StudyBibleDB.parse_passage_reference(reference)
    if (
        not parsed
        or parsed["start_verse"] is not None
        or parsed["end_chapter"] != parsed["start_chapter"]
    ):
        return None
    return parsed["book"], parsed["start_chapter"]


async def handle_get_study_notes(args: dict[str, Any]) -> list[TextContent]:
    """Handle get_study_notes tool - get study notes for a verse or chapter."""
    reference = args.get("reference", "")
    chapter_only = args.get("chapter_only", False)

    if not reference:
        return text("Please provide a Bible reference (e.g., 'John 3:16' or 'Genesis 1').")

    if err := await _check_aquifer_data():
        return err

    # A chapter (with chapter_only, the chapter of any reference: 'John 3:16'
    # -> John 3) or a verse range is a passage: Tyndale notes in full and the
    # long translator notes listed by verse. A single verse shows every note.
    parsed = db.parse_passage_reference(reference)
    passage = None
    if chapter_only and parsed:
        passage = (parsed["book"], parsed["book_name"], parsed["start_chapter"], None, None, None)
    elif ':' not in reference.strip() and (chapter := _parse_single_chapter(reference)):
        passage = (chapter[0], parsed["book_name"], chapter[1], None, None, None)
    elif (
        ':' in reference and parsed and parsed["start_verse"] is not None
        and (parsed["end_chapter"], parsed["end_verse"]) != (parsed["start_chapter"], parsed["start_verse"])
    ):
        passage = (
            parsed["book"], parsed["book_name"], parsed["start_chapter"], parsed["start_verse"],
            parsed["end_chapter"], parsed["end_verse"] or 999,
        )

    if passage is None:
        notes = await db.get_study_notes(reference)
        if not notes:
            return text(f"No study notes found for {reference}.")
        return text(f"## Study Notes: {reference}\n\n" + format_study_notes(notes))

    book, book_name, start_chapter, start_verse, end_chapter, end_verse = passage
    if start_verse is None:
        label = f"{book_name} {start_chapter}"
        notes = await db.get_chapter_study_notes(book, start_chapter)
        bounds = await db.get_chapter_verse_bounds(book)
        last_verse = bounds.get(start_chapter, (1, 0))[1] or max(
            (int((note.get("end_ref") or note["start_ref"])[5:8]) for note in notes if note.get("start_ref")),
            default=1,
        )
        span = ((start_chapter, 0), (start_chapter, last_verse))
    else:
        label = reference
        notes = await db.get_study_notes_in_span(
            book, start_chapter, start_verse, end_chapter, end_verse
        )
        span = ((start_chapter, start_verse), (end_chapter, end_verse))
    if not notes:
        return text(f"No study notes found for {label}.")
    return text(format_passage_study_notes(label, notes, book_name, span))


async def handle_get_bible_dictionary(args: dict[str, Any]) -> list[TextContent]:
    """Handle get_bible_dictionary tool - search dictionary articles."""
    topic = args.get("topic", "")

    if not topic:
        return text("Please provide a topic to look up.")
    try:
        offset = max(0, int(args.get("offset") or 0))
    except (TypeError, ValueError):
        return text("offset must be a whole number of characters (from a truncation note).")

    if err := await _check_aquifer_data():
        return err

    articles = await db.get_bible_dictionary(topic)

    if not articles:
        return text(f"No dictionary article found for '{topic}'.")

    result = format_dictionary_article(articles, section=args.get("section") or None, offset=offset)

    return text(result)


async def handle_get_key_terms(args: dict[str, Any]) -> list[TextContent]:
    """Handle get_key_terms tool - search FIA Key Terms."""
    term = args.get("term", "")

    if not term:
        return text("Please provide a term to look up.")

    if err := await _check_aquifer_data():
        return err

    found = await db.find_key_terms(term, limit=KEY_TERMS_SHOWN)

    if not found["entries"]:
        message = f"No key term found for '{term}'."
        if found["mentions"]:
            listed = ", ".join(f"'{title}'" for title in found["mentions"])
            message += f" Key terms whose entries mention it most: {listed}."
        else:
            message += (
                " Key terms are English titles such as 'grace', 'covenant', or "
                "'Son of Man'; for a Greek or Hebrew word use word_study."
            )
        return text(message)

    result = ""
    if found["match"] == "near":
        result += f"*No key term is titled '{term}'; showing the nearest.*\n\n"
    result += format_key_terms(found["entries"]).rstrip()
    if found["other_titles"]:
        listed = ", ".join(f"'{title}'" for title in found["other_titles"][:4])
        result += f"\n\n*Related key terms: {listed}.*"

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

@returns_input_errors
async def handle_get_ane_context(args: dict[str, Any]) -> list[TextContent]:
    """Handle get_ane_context tool - get Ancient Near East background."""
    reference = args.get("reference")
    dimension = args.get("dimension")
    period = args.get("period")
    detail_level = args.get("detail_level", "standard")
    limit = bounded_limit(args.get("limit", 4), ANE_CONTEXT_MAX)

    has_data = await db.has_ane_data()
    if not has_data:
        return text("ANE context data not available. Rebuild the database with ANE data files in data/ane_context/.")

    # If no arguments provided, list available dimensions
    if not reference and not dimension and not period:
        dimensions = await db.get_ane_dimensions()
        result = format_ane_dimensions(dimensions)
        return text(result)

    # Every match is fetched so the total can be reported; only `limit` are shown.
    entries = await db.get_ane_context(
        reference=reference,
        dimension=dimension,
        period=period,
        limit=ANE_CONTEXT_FETCH,
    )

    # Post-query: promote/filter broad entries using key_references, then put
    # direct chapter matches first (each group keeps its relevance order).
    if reference and entries:
        parsed = db.parse_passage_reference(reference)
        if parsed:
            entries = _refine_broad_entries(entries, parsed["book"], parsed["start_chapter"])
        entries.sort(key=lambda entry: (
            entry.get("match_type") != "direct", entry.get("relevance_score") or 0,
        ))
    total = len(entries)
    entries = entries[:limit]

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
    if total > len(entries):
        header += (
            f"*Showing {len(entries)} of {total} entries"
            + (", direct chapter matches first" if reference else "")
            + f"; raise limit (at most {ANE_CONTEXT_MAX}) or set dimension/period for more.*\n\n"
        )

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


# explore_genealogy walks at most this many generations each way
MAX_GENERATIONS = 40


async def _resolve_person(name: str) -> tuple[dict | None, str]:
    """The graph person a name most likely means, and a note naming the others."""
    matches = await db.graph_find_person(name)
    if not matches:
        return None, ""
    return matches[0], format_person_choice(name, matches)


async def _nation_mentions(entities: dict, reference: str) -> set[str]:
    """The tagged eponyms (Israel, Judah, Moab ...) that here mean a nation or tribe.

    Outside the chapters where Scripture speaks of the ancestor himself (see
    is_nation_mention), an eponym counts as the nation unless one of his
    relatives who is not an eponym is mentioned too, as in Ruth 4:12 ('Perez,
    whom Tamar bore to Judah').
    """
    people = {p.get("entity_id") for p in entities.get("people", [])}
    candidates = [pid for pid in people if pid and is_nation_mention(pid, reference)]
    if not candidates:
        return set()
    relatives = await db.graph_relatives(candidates)
    eponyms = eponym_ids()
    return {pid for pid in candidates if not ((relatives[pid] - eponyms) & people)}


async def handle_explore_genealogy(args: dict[str, Any]) -> list[TextContent]:
    """Handle explore_genealogy tool - trace family tree."""
    if err := await _check_graph_data():
        return err

    person_name = args.get("person", "")
    direction = args.get("direction", "both")

    if not person_name:
        return text("Please provide a person's name.")
    if direction not in ("ancestors", "descendants", "both"):
        return text("'direction' must be 'ancestors', 'descendants' or 'both'.")
    try:
        generations = int(args.get("generations", 5))
    except (TypeError, ValueError):
        return text(f"'generations' must be an integer from 1 to {MAX_GENERATIONS}.")
    if generations < 1:
        return text(f"'generations' must be an integer from 1 to {MAX_GENERATIONS}.")
    capped = generations > MAX_GENERATIONS
    generations = min(generations, MAX_GENERATIONS)

    person, note = await _resolve_person(person_name)
    if person is None:
        return text(f"No person found matching '{person_name}' in the Theographic database.")
    if capped:
        note += f"*Showing {MAX_GENERATIONS} generations, the most this tool traces.*\n"

    ancestors = descendants = None
    if direction in ("ancestors", "both"):
        ancestors = await db.graph_lineage(person["id"], "ancestors", generations)
    if direction in ("descendants", "both"):
        descendants = await db.graph_lineage(person["id"], "descendants", generations)
    family = await db.graph_get_family(person["id"])

    result = format_genealogy(person, ancestors, descendants, family, generations, note)
    diagram = mermaid_genealogy(person, [ancestors, descendants], family)
    if diagram:
        result += f"\n\n### Family Tree Diagram\n{diagram}\n"
    elif any(lineage and lineage["people"] for lineage in (ancestors, descendants)):
        result += "\n*No diagram: too many people to draw; ask for fewer generations for one.*\n"
    return text(result)


async def handle_people_in_passage(args: dict[str, Any]) -> list[TextContent]:
    """Handle people_in_passage tool - find entities in a verse or chapter."""
    if err := await _check_graph_data():
        return err

    reference = args.get("reference", "")
    if not reference:
        return text("Please provide a Bible reference (e.g., 'Romans 8' or 'Genesis 22:1').")

    # A verse, verse range, chapter, or chapter range ('Psalm 23-24').
    parsed = StudyBibleDB.parse_passage_reference(reference.strip())
    if not parsed:
        return text(f"Could not parse reference: {reference}. Use 'Romans 8' or 'Genesis 22:1' format.")
    entities = await db.graph_get_passage_entities(
        parsed["book"], parsed["start_chapter"], parsed["start_verse"],
        parsed["end_chapter"], parsed["end_verse"],
    )

    result = format_passage_entities(reference, entities, await _nation_mentions(entities, reference))
    return text(result)


async def handle_explore_person_events(args: dict[str, Any]) -> list[TextContent]:
    """Handle explore_person_events tool - timeline of a person's life."""
    if err := await _check_graph_data():
        return err

    person_name = args.get("person", "")
    if not person_name:
        return text("Please provide a person's name.")

    person, note = await _resolve_person(person_name)
    if person is None:
        return text(f"No person found matching '{person_name}' in the Theographic database.")

    events = await db.graph_get_person_events(person["id"])
    event_ids = [evt["id"] for evt in events]
    event_places = await db.graph_get_events_places(event_ids)
    event_verses = await db.graph_get_event_verses(event_ids)
    return text(format_person_events(person, events, event_places, event_verses, note))


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
    namesakes = [m for m in matches[1:] if m["name"].casefold() == place["name"].casefold()]
    note = ""
    if namesakes:
        def count(n: int, noun: str) -> str:
            return f"{n} {noun}{'s' if n != 1 else ''}"

        others = ", ".join(
            f"{m['id']} ({count(m['event_count'], 'event')}, {count(m['verse_count'], 'verse')})"
            for m in namesakes[:4]
        )
        note = (f"*{len(namesakes) + 1} places are called {place['name']}; showing {place['id']}. "
                f"Others: {others}. Pass an id to choose another.*\n")
    events = await db.graph_get_place_events(place["id"])
    people = await db.graph_get_place_people(place["id"])
    event_verses = await db.graph_get_event_verses([evt["id"] for evt in events])

    result = format_place_history(place, events, people, event_verses, note)

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

    person1, note1 = await _resolve_person(name1)
    person2, note2 = await _resolve_person(name2)

    if person1 is None:
        return text(f"No person found matching '{name1}'.")
    if person2 is None:
        return text(f"No person found matching '{name2}'.")

    label1, label2 = person_label(person1), person_label(person2)
    if person1["id"] == person2["id"]:
        return text(
            f"## Connection: {label1} → {label2}\n\n"
            f"'{name1}' and '{name2}' are the same person: {label1}.\n"
        )

    path = await db.graph_find_path(person1["id"], person2["id"])
    result = format_connection_path(label1, label2, path, note1 + note2)

    diagram = mermaid_connection_path(label1, label2, path)
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
    parsed = db.parse_passage_reference(reference)
    if parsed and (
        parsed["start_verse"] is None
        or (parsed["start_chapter"], parsed["start_verse"]) != (parsed["end_chapter"], parsed["end_verse"])
    ):
        return text(
            f"graph_enriched_search takes a single verse (e.g. '{parsed['book_name']} "
            f"{parsed['start_chapter']}:{parsed['start_verse'] or 1}'). For the people, places, "
            f"and events of {reference} use people_in_passage (reference='{reference}')."
        )

    # Get the verse text
    verse = await db.get_verse(reference)
    normalized = db._normalize_reference(reference)
    entities = await db.graph_get_verse_entities(normalized)

    # Family of each person mentioned, by the person's own id
    family_data = {}
    for p in entities.get("people", []):
        if p.get("entity_id") and p["entity_id"] not in family_data:
            family_data[p["entity_id"]] = await db.graph_get_family(p["entity_id"])

    nations = await _nation_mentions(entities, reference)
    result = format_enriched_verse(reference, verse, entities, family_data, nations)
    return text(result)


# =========================================================================
# Theological scholarship tool handler
# =========================================================================

@returns_input_errors
async def handle_get_theology_context(args: dict[str, Any]) -> list[TextContent]:
    """Handle get_theology_context tool — theological scholarship by reference, theme, and/or author."""
    author = (args.get("author") or "").strip().lower() or None
    limit = bounded_limit(args.get("limit", 4), THEOLOGY_MAX)
    offset = bounded_offset(args.get("offset"))
    has_data = await db.has_theology_data()
    if not has_data:
        return text("Theological scholarship data not available. Run 'python scripts/import_heiser_content.py' first.")
    if author and not await db.has_theology_data(author=author):
        authors = ", ".join(await db.get_theology_authors())
        return text(f"No scholarship by author '{author}'. Authors: {authors}.")

    reference = args.get("reference")
    theme = args.get("theme")

    # If neither provided, list themes
    if not reference and not theme:
        themes = await db.get_theology_themes(author=author)
        return text(format_theology_themes(themes))

    entries = []
    if theme:
        entries = await db.get_theology_context_by_theme(theme, author=author, limit=offset + limit + 1)
    elif reference:
        entries = await db.get_theology_context_by_reference(
            reference, author=author, limit=offset + limit + 1
        )
    # Entries are ranked, so a page is a slice; the extra row says whether another exists.
    entries = entries[offset:]
    more = len(entries) > limit
    entries = entries[:limit]

    if not entries and offset:
        return text(f"No more theological scholarship at offset {offset}.")
    if not entries:
        query_desc = f"theme='{theme}'" if theme else f"reference='{reference}'"
        if author:
            query_desc += f" (author='{author}')"
        hint = ""
        if theme and not await db.theology_theme_exists(theme):
            hint = " No theme has that key; call with no arguments to list the themes."
        return text(f"No theological scholarship found for {query_desc}.{hint}")

    author_label = author.capitalize() if author else "Theological"
    header = f"## {author_label} Scholarship Context"
    if reference:
        header += f" for {reference}"
    if theme:
        header += f" — theme: {theme}"
    header += "\n\n"
    if offset:
        header += f"*Results {page_window(offset, len(entries))}.*\n\n"
    header += next_page_note(offset, len(entries), more)

    result = header + format_theology_context(entries)
    return text(result)


_TORAH_BOOKS = ("Gen", "Exo", "Lev", "Num", "Deu")


def _torah_unit_line(unit: dict) -> str:
    cells = ", ".join(f"{cell['cell_label']} {cell['verse_range']}" for cell in unit["cells"])
    return f'- Unit {unit["id"]} · "{unit["title"]}" ({unit["verses"]}); cells: {cells}'


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

    parsed = db.parse_passage_reference(reference)
    if parsed is None:
        return text(
            f"Could not read '{reference}' as a Bible reference. Give a verse such as "
            "'Leviticus 19:18', or a chapter such as 'Leviticus 19'."
        )
    book = parsed["book"]
    if book not in _TORAH_BOOKS:
        return text(f"Torah Weave data covers Genesis–Deuteronomy only; {reference} is outside it.")
    start_chapter, end_chapter = parsed["start_chapter"], parsed["end_chapter"]
    start_verse, end_verse = parsed["start_verse"], parsed["end_verse"]
    single = start_verse is not None and (start_chapter, start_verse) == (end_chapter, end_verse)
    if single:
        matches = await db.get_torah_weave_cells_for_reference(reference)
        if matches:
            # Fetch full cell sets for each unique unit (needed to compute partners)
            unit_ids = {m["unit_id"] for m in matches}
            unit_cells_by_unit: dict[int, list[dict]] = {}
            for unit_id in unit_ids:
                unit_cells_by_unit[unit_id] = await db.get_torah_weave_unit_cells(unit_id)
            return text(format_torah_weave(
                reference, matches, unit_cells_by_unit, explain=bool(args.get("explain", False))
            ))

    # No cell: say whether the verse exists, and which unit (if any) holds it.
    bounds = await db.get_chapter_verse_bounds(book)
    if bounds:
        for chapter in (start_chapter, end_chapter):
            if chapter not in bounds:
                return text(
                    f"{parsed['book_name']} has no chapter {chapter} "
                    f"(chapters {min(bounds)}–{max(bounds)})."
                )
        first, last = bounds[start_chapter]
        if start_verse is not None and not first <= start_verse <= last:
            return text(
                f"{parsed['book_name']} {start_chapter} has no verse {start_verse} "
                f"(verses {first}–{last})."
            )

    start = (start_chapter, start_verse if start_verse is not None else bounds.get(start_chapter, (1, 1))[0])
    end = (end_chapter, end_verse if end_verse is not None else bounds.get(end_chapter, (1, 999))[1])
    units = await db.get_torah_weave_units_in_passage(book, start, end)
    if single:
        if not units:
            return text(f"No Torah Weave unit in Kline's dataset contains {reference}.")
        return text(
            f"{reference} is in the unit below, but Kline's cell map assigns it to no cell, "
            "so it has no weave partners. The unit's cells (verse ranges in English "
            "numbering) can be looked up one verse at a time:\n\n"
            + "\n".join(_torah_unit_line(unit) for unit in units)
        )
    if not units:
        return text(f"No Torah Weave unit in Kline's dataset falls within {reference}.")
    result = f"## Torah Weave units in {reference}\n\n" + "\n".join(
        _torah_unit_line(unit) for unit in units
    )
    # Suggest the first verse of the passage that sits in a cell.
    example = next((
        max(start, (cell["chapter_start"], cell["verse_start"]))
        for unit in units for cell in unit["cells"]
        if (cell["chapter_start"], cell["verse_start"]) <= end
        and start <= (cell["chapter_end"], cell["verse_end"])
    ), None)
    if example:
        result += (
            "\n\nWeave partners are per cell: pass one verse (e.g. reference='"
            f"{parsed['book_name']} {example[0]}:{example[1]}') for its cell and partners."
        )
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


@returns_input_errors
async def handle_list_research_sources(args: dict[str, Any]) -> list[TextContent]:
    """Handle list_research_sources tool — curated open repositories to consult."""
    topic = (args.get("topic") or "").strip() or None
    query = (args.get("query") or "").strip() or None
    perspective = (args.get("perspective") or "").strip() or None
    limit = bounded_limit(args.get("limit", RESEARCH_SOURCES_DEFAULT_LIMIT), RESEARCH_SOURCES_MAX_LIMIT)

    matches = find_research_sources(topic=topic, perspective=perspective)
    return text(format_research_sources(
        matches[:limit], total=len(matches), topic=topic, query=query, perspective=perspective,
    ))



_TOOL_HANDLERS = {
    "word_study": handle_word_study,
    "lookup_verse": handle_lookup_verse,
    "compare_biblical_versions": handle_compare_biblical_versions,
    "search_ancient_sources": handle_search_ancient_sources,
    "lookup_ancient_source": handle_lookup_ancient_source,
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
        # per-IP time of the last "rate limited" line (one per window)
        self._limited_logged: dict[str, float] = {}

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Extract client IP — behind Fly's proxy scope["client"] is the edge
        # proxy, so prefer the real-client headers it sets
        headers = {k.decode("latin-1").lower(): v.decode("latin-1")
                   for k, v in scope.get("headers", [])}
        ip = request_ip(scope, headers) or "unknown"

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
                    f"static: {int(hits[0])} request(s) for {path} from {client_tag(ip)} "
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
            if now - self._limited_logged.get(ip, -self.window_seconds) >= self.window_seconds:
                self._limited_logged[ip] = now
                logger.warning(
                    f"rate limited: client={client_tag(ip)} over {self.max_requests} requests "
                    f"in {self.window_seconds}s (last: {scope.get('method')} {path[:80]})"
                )
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


# The downloadable database bundles non-commercial and share-alike texts; the
# download response and the root endpoint carry this notice. ASCII only: it is
# also sent as an HTTP header.
DATABASE_LICENSE_NOTICE = (
    "The database includes CC BY-NC 4.0 material (ETCBC Dead Sea Scrolls transcription, "
    "Metsudah Chumash English), non-commercial use only, and CC BY-SA 4.0 material "
    "(Perseus Josephus, First1KGreek Philo, Latin Wikisource 4 Ezra), share alike."
)
ROOT_DESCRIPTION = (
    f"Bible study tools with Greek/Hebrew lexicons via MCP. {DATABASE_LICENSE_NOTICE}"
)


def _make_shared_routes():
    """Create route handler functions and routes shared by SSE and HTTP transports."""
    from starlette.responses import JSONResponse, Response
    from starlette.routing import Route

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
            headers={"X-Data-License-Notice": DATABASE_LICENSE_NOTICE},
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


class _ASGIEndpoint:
    """Route endpoint that passes the raw ASGI call straight to ``app``.

    Starlette treats a function or method endpoint as request -> response and
    sends whatever it returns, so an ASGI app that sends its own response and
    returns None has to be routed as an object instead.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        await self.app(scope, receive, send)


# The SSE stream sends a comment line this often while idle, so Fly's proxy
# (and any other) never closes a quiet session as idle. sse-starlette's
# default is 15 s today; pinned so a library upgrade cannot lengthen it.
SSE_PING_SECONDS = 15


def _make_sse_transport():
    """The SDK's SSE transport, made to forget a session once its stream closes.

    SseServerTransport keeps each session's writer after the client
    disconnects. A POST to that session id was then answered 202 Accepted and
    the message dropped (the send on the closed stream raised after the
    response), so the client's call hung until it timed out. Now a closed
    session is answered like an unknown one: 404 "Could not find session".

    404 is kept for unknown and expired sessions (the SDK's answer): no SSE
    client treats any status as "reconnect" (the TypeScript and Python SDKs
    raise on every non-2xx POST, e.g. "Error POSTing to endpoint (HTTP 404)"),
    and 404 is what the Streamable HTTP spec defines for an expired session,
    on which clients must start a new one.
    """
    from mcp.server.sse import SseServerTransport

    class ForgetfulSseTransport(SseServerTransport):
        def forget_closed_sessions(self) -> None:
            for session_id, writer in list(self._read_stream_writers.items()):
                counts = writer.statistics()
                if not counts.open_send_streams or not counts.open_receive_streams:
                    del self._read_stream_writers[session_id]

        async def handle_post_message(self, scope, receive, send) -> None:
            self.forget_closed_sessions()
            await super().handle_post_message(scope, receive, send)

    return ForgetfulSseTransport("/messages")


def _make_sse_routes():
    """Create the legacy SSE transport routes shared by the SSE and HTTP transports.

    GET /sse opens a session and tells the client to POST its messages to
    /messages?session_id=<id>. Deprecated: clients should use /mcp/.
    """
    from sse_starlette import EventSourceResponse
    from starlette.routing import Route

    EventSourceResponse.DEFAULT_PING_INTERVAL = SSE_PING_SECONDS
    sse = _make_sse_transport()

    async def handle_sse(scope, receive, send):
        try:
            async with sse.connect_sse(scope, receive, send) as streams:
                await server.run(
                    streams[0], streams[1],
                    server.create_initialization_options()
                )
        finally:
            sse.forget_closed_sessions()

    # Both handlers send their own response and return None (handle_post_message
    # answers 202, or 400/404 for a bad or unknown session id), so they are routed
    # as ASGI apps: as request -> response endpoints Starlette calls that None,
    # raising TypeError on every POST and SSE disconnect. Route, not the SDK's
    # Mount("/messages/"): a Mount 307-redirects the advertised /messages path.
    return [
        Route("/sse", endpoint=_ASGIEndpoint(handle_sse), methods=["GET"]),
        Route("/messages", endpoint=_ASGIEndpoint(sse.handle_post_message), methods=["POST"]),
    ]


def build_sse_app():
    """Build the ASGI app for the legacy SSE-only transport, behind the rate limiter."""
    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.middleware.cors import CORSMiddleware
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    async def root(request):
        return JSONResponse({
            "name": "Study Bible MCP Server",
            "version": "1.0.0",
            "description": ROOT_DESCRIPTION,
            "transport": "sse",
            "endpoints": {
                "/sse": "SSE connection endpoint (deprecated; use /mcp/ — will be removed)",
                "/messages": "Message POST endpoint (deprecated with /sse)",
                "/health": "Health check",
                "/privacy": "Privacy policy",
            },
            "tools": [tool.name for tool in TOOLS],
        })

    app = Starlette(
        routes=[
            Route("/", endpoint=root, methods=["GET"]),
            *_make_shared_routes(),
            *_make_sse_routes(),
        ],
        middleware=[
            Middleware(RequestLogMiddleware),
            Middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])
        ],
    )

    return RateLimitMiddleware(app)


async def run_sse_server(host: str, port: int):
    """Run the MCP server with SSE transport only (legacy)."""
    try:
        import uvicorn  # noqa: F401 (imported to fail here when the extra is missing)

        app = build_sse_app()
    except ImportError:
        logger.error(
            "SSE transport requires additional dependencies. "
            "Install with: pip install 'study-bible-mcp[sse]' or pip install starlette uvicorn"
        )
        sys.exit(1)

    logger.info(f"Starting SSE server on {host}:{port}")
    await _serve(uvicorn_config(app, host, port), "sse")


def uvicorn_config(app, host: str, port: int):
    """The uvicorn settings both HTTP transports run with."""
    import uvicorn

    # Trust Fly's proxy headers so the app sees https and any redirect it issues
    # points at https://, not http://. log_config=None leaves logging as
    # configure_logging set it (console + rotating file); the access log is
    # off because RequestLogMiddleware logs each request with the client's
    # address anonymised (with proxy headers trusted, uvicorn's would show it).
    return uvicorn.Config(
        app, host=host, port=port, log_level="info", log_config=None, access_log=False,
        proxy_headers=True, forwarded_allow_ips="*",
    )


def _package_version() -> str:
    try:
        from importlib.metadata import version

        return version("studybible-mcp")
    except Exception:
        return "unknown"


async def _log_startup(transport: str) -> None:
    """Log what is running: version, commit, machine, database, sqlite-vec."""
    import platform
    import sqlite3

    env = os.environ
    logger.info(
        f"startup: studybible-mcp {_package_version()} "
        f"commit={env.get('GIT_COMMIT') or 'unknown'} transport={transport} pid={os.getpid()} "
        f"python={platform.python_version()} sqlite={sqlite3.sqlite_version} "
        f"machine={env.get('FLY_MACHINE_ID', '-')} region={env.get('FLY_REGION', '-')} "
        f"image={env.get('FLY_IMAGE_REF', '-')}"
    )
    db_path = get_db_path()
    try:
        database = await open_database()
    except Exception:
        logger.exception(f"database: {db_path} failed to open")
        return
    if database is None:
        logger.error(f"database: {db_path} MISSING; tools will report it")
        return
    info = db_path.stat()
    modified = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(info.st_mtime))
    journal = await database._fetchone("PRAGMA journal_mode")
    vec = "loaded" if database._vec_loaded else f"unavailable ({database._vec_error})"
    logger.info(
        f"database: {db_path} {info.st_size / 1e6:.1f} MB modified {modified} "
        f"journal={next(iter(journal.values())) if journal else '?'} sqlite-vec={vec} "
        f"readers={database.reader_count}"
    )


def _exit_on_sigterm(signum, frame):
    raise SystemExit(128 + signum)


async def _serve(config, transport: str) -> None:
    """Serve until uvicorn stops, logging startup, loop stalls and shutdown."""
    import signal

    import uvicorn

    started = time.monotonic()
    await _log_startup(transport)
    watchdog = asyncio.create_task(watch_event_loop())
    # uvicorn shuts down gracefully on SIGTERM, then re-raises the signal once
    # serve() returns. Under the default handler that killed the process on
    # the spot, before the shutdown line and the queued log records were
    # written; this handler exits through the finally block below instead.
    with contextlib.suppress(ValueError):  # not the main thread
        signal.signal(signal.SIGTERM, _exit_on_sigterm)
    try:
        await uvicorn.Server(config).serve()
    finally:
        watchdog.cancel()
        logger.info(
            f"shutdown: uptime {time.monotonic() - started:.0f}s, {stats['calls']} tool calls "
            f"({stats['errors']} errors, {stats['slow']} slow)"
        )
        if db is not None and hasattr(db, "close"):
            await db.close()


def build_http_app():
    """Build the ASGI app for the HTTP transport, behind the rate limiter.

    Serves Streamable HTTP at /mcp and SSE at /sse for backwards compatibility.
    """
    from collections.abc import AsyncIterator

    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.middleware.cors import CORSMiddleware
    from starlette.responses import JSONResponse, Response
    from starlette.routing import Mount, Route

    # Streamable HTTP session manager. Stateless: no server-side session table,
    # so a machine suspend/restart can never invalidate a client's session id
    # (this server is pure request/response — no server-initiated messages).
    session_manager = StreamableHTTPSessionManager(app=server, stateless=True)

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        async with session_manager.run():
            yield

    async def root(request):
        return JSONResponse({
            "name": "Study Bible MCP Server",
            "version": "1.0.0",
            "description": ROOT_DESCRIPTION,
            "transports": ["streamable-http", "sse"],
            "endpoints": {
                "/mcp": "Streamable HTTP MCP endpoint (recommended)",
                "/sse": "SSE connection endpoint (deprecated; use /mcp/ — will be removed)",
                "/messages": "SSE message POST endpoint (deprecated with /sse)",
                "/health": "Health check",
                "/privacy": "Privacy policy",
                "/static/icon.png": "Server icon",
                "/download/study_bible.db": (
                    "Download pre-built database (~750MB; includes CC BY-NC and CC BY-SA texts)"
                ),
            },
            "tools": [tool.name for tool in TOOLS],
        })

    async def streamable_http(scope, receive, send):
        # Stateless and pure request/response: the server never sends unprompted
        # messages, so a client's GET stream would sit open forever, counting
        # against Fly's connection limit (94 of 100 were held this way when calls
        # began to stall). The spec lets a server refuse that stream with 405.
        if scope["type"] == "http" and scope["method"] == "GET":
            refusal = Response("Method Not Allowed", status_code=405,
                               headers={"Allow": "POST, DELETE"})
            await refusal(scope, receive, send)
            return
        await session_manager.handle_request(scope, receive, send)

    app = Starlette(
        lifespan=lifespan,
        routes=[
            Route("/", endpoint=root, methods=["GET"]),
            *_make_shared_routes(),
            # Serve /mcp itself, not just /mcp/: a Mount alone answers /mcp with a
            # 307 to /mcp/, which claude.ai's connector client does not follow.
            Route("/mcp", endpoint=_ASGIEndpoint(streamable_http),
                  methods=["GET", "POST", "DELETE"]),
            Mount("/mcp", app=streamable_http),
            *_make_sse_routes(),
        ],
        middleware=[
            Middleware(RequestLogMiddleware),
            Middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])
        ],
    )

    return RateLimitMiddleware(app)


async def run_http_server(host: str, port: int):
    """Run the MCP server with both Streamable HTTP and SSE transports.

    Serves Streamable HTTP at /mcp and SSE at /sse for backwards compatibility.
    """
    try:
        import uvicorn  # noqa: F401 (imported to fail here when the extra is missing)

        app = build_http_app()
    except ImportError:
        logger.error(
            "HTTP transport requires additional dependencies. "
            "Install with: pip install 'study-bible-mcp[sse]' or pip install starlette uvicorn"
        )
        sys.exit(1)

    logger.info(
        f"Starting server on {host}:{port}: Streamable HTTP at /mcp/, SSE (deprecated) at /sse"
    )
    await _serve(uvicorn_config(app, host, port), "http")


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

    if transport in ("sse", "http"):
        # The HTTP server also keeps a rotating log beside the database
        # (/data/logs on Fly) unless STUDY_BIBLE_LOG_DIR names another
        # directory, or is empty for console only.
        log_dir = os.environ.get("STUDY_BIBLE_LOG_DIR")
        if log_dir is None:
            log_dir = str(get_db_path().parent / "logs")
        log_path = configure_logging(Path(log_dir) if log_dir else None)
        logger.info(f"logging to {log_path or 'console only'}")

    logger.info(f"Starting Study Bible MCP server (transport: {transport})")

    if transport == "stdio":
        asyncio.run(run_server())
        return
    try:
        if transport == "sse":
            asyncio.run(run_sse_server(host, port))
        elif transport == "http":
            asyncio.run(run_http_server(host, port))
    except KeyboardInterrupt:  # SIGINT (Fly's default kill signal), after a graceful stop
        sys.exit(130)


if __name__ == "__main__":
    main()
