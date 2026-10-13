# Study Bible MCP - Quick Setup

Get Bible study tools with Greek/Hebrew lexicons in Claude Desktop in under 30 seconds.

## Setup

### Claude Desktop

1. Open **Settings** (gear icon)
2. Go to **Connectors**
3. Click **Add Custom Connector**
4. Paste this URL:
   ```
   https://studybible-mcp.fly.dev/sse
   ```
5. **Restart Claude Desktop** (quit completely and reopen)
6. Look for the tools icon in the chat - you're ready!

### Claude Code

```bash
claude mcp add study-bible https://studybible-mcp.fly.dev/sse
```

### Manual Config (Alternative)

If you prefer editing JSON config files, add this to your Claude Desktop config:

```json
{
  "mcpServers": {
    "study-bible": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "https://studybible-mcp.fly.dev/sse"]
    }
  }
}
```

Config file locations:
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
- **Linux**: `~/.config/Claude/claude_desktop_config.json`

## Available Tools

Once connected, you have access to these tools:

| Tool | Description | Example |
|------|-------------|---------|
| `lookup_verse` | Verse text with Greek/Hebrew | "Look up John 3:16" |
| `compare_biblical_versions` | Provenance-aware MT/LXX comparison | "Compare MT and LXX for Psalm 24:1" |
| `search_ancient_sources` | Licensed Josephus primary-source search | "Search Josephus for John the Baptist" |
| `word_study` | Greek/Hebrew lexicon study | "Study G26" |
| `search_lexicon` | Search lexicons by concept | "Greek words for love" |
| `get_cross_references` | Related passages and theme chains | "Cross-references for Romans 3:21" |
| `lookup_name` | Biblical person/place information | "Tell me about Abraham" |
| `parse_morphology` | Explain grammar codes | "What does V-AAI-3S mean?" |
| `search_by_strongs` | Find uses of a Strong's number | "Verses containing G26" |
| `find_similar_passages` | Semantic passage similarity | "Passages like Isaiah 53" |
| `get_study_notes` | Study and translation notes | "Notes on John 3:16" |
| `get_bible_dictionary` | Tyndale Bible Dictionary | "Dictionary article on covenant" |
| `get_key_terms` | FIA theological terms | "Define atonement" |
| `explore_genealogy` | Ancestor/descendant trees | "David's ancestors" |
| `people_in_passage` | People, places, and events in a passage | "Who is in Genesis 22?" |
| `explore_person_events` | Chronological life events | "Events in Moses' life" |
| `explore_place` | Biblical history of a place | "Explore Jerusalem" |
| `find_connection` | Family path between two people | "Connect Ruth and Jesus" |
| `graph_enriched_search` | Verse text plus graph context | "Enrich Matthew 1:1" |
| `get_ane_context` | Ancient cultural context | "ANE context for Genesis 15" |
| `get_theology_context` | Attributed theological scholarship | "Scholarship on Psalm 82" |
| `get_torah_weave` | Torah structural pairings | "Pairings for Genesis 1:1" |
| `get_textual_variant` | Separates manuscript evidence, critical judgments, theological interpretations, and author claims | "Variant at Deuteronomy 32:8" |
| `list_research_sources` | Open research repositories to consult | "Free sources for rabbinic commentary" |

## Example Questions

Try asking Claude:

- "What does 'agape' mean in Greek? Show me how it's used in 1 Corinthians 13."
- "Look up Philippians 2:5-11 and explain the Greek structure."
- "What's the difference between 'logos' and 'rhema' in the New Testament?"
- "Show me the Hebrew word for 'lovingkindness' (hesed) and where it appears."
- "What does Romans 3:21-26 say about justification? Include the Greek."

## Hermeneutical Approach

This tool uses the methodology from Fee & Stuart's "How to Read the Bible for All Its Worth":

- **Genre-aware interpretation** - Different rules for epistles, narratives, poetry, prophecy
- **Context first** - Historical and literary context before application
- **Original languages when helpful** - Greek/Hebrew to clarify meaning
- **Scripture interprets Scripture** - Cross-references and thematic connections

## Troubleshooting

### Tools not appearing?
- Make sure you restarted Claude Desktop completely
- Check that the JSON is valid (no trailing commas, proper quotes)
- Verify you have Node.js installed (for npx)

### Connection errors?
- The server may be starting up (auto-scales from zero)
- Wait 10-15 seconds and try again
- Check your internet connection

### Need help?
Open an issue: https://github.com/djayatillake/studybible-mcp/issues

## Self-Hosting

Want to run your own instance? See [SELF_HOST.md](SELF_HOST.md) for:
- Local development setup
- Docker deployment
- Your own Fly.io deployment
