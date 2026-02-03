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

# Purple cross icon (32x32 PNG, base64 encoded)
ICON_BASE64 = "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAATklEQVR4nO3VQQoAIAhE0e+c3JvXCVroRsh5y8AYGCOw7aIzlOR5nJfvE8PkAGyvIKqb3vV6IWKYHIDtFURnyH/BVzsgB8AVDJMDYMasCzFDCS5Q8luaAAAAAElFTkSuQmCC"
from .tools import TOOLS, format_lexicon_entry, format_verse, format_name_entry
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
server = Server(
    "study-bible",
    version="1.0.0",
    icons=[
        Icon(
            src=f"data:image/png;base64,{ICON_BASE64}",
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
    """Handle lookup_name tool - get info about biblical names."""
    name = args.get("name", "")
    name_type = args.get("type")  # person, place, thing

    if not name:
        return [TextContent(type="text", text="Please provide a name to look up.")]

    entries = await db.lookup_name(name, name_type=name_type)

    if not entries:
        return [TextContent(type="text", text=f"No entries found for '{name}'.")]

    result = f"## Biblical Names: {name}\n\n"

    for entry in entries:
        result += format_name_entry(entry)
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
            },
            "tools": [tool.name for tool in TOOLS],
        })

    # Create Starlette app with CORS middleware
    app = Starlette(
        routes=[
            Route("/", endpoint=root, methods=["GET"]),
            Route("/health", endpoint=health_check, methods=["GET"]),
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
