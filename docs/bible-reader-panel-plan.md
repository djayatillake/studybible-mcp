# Bible Reader Panel — Implementation Plan

A plan for adding an interactive Bible reader panel to the Study Bible MCP server, using the helloao.org translation API and MCP Apps extension.

## Context

The Study Bible MCP server currently has 18 tools covering lexicons, morphology, cross-references, ANE context, genealogy, and more — all text-in, text-out. When studying a passage, the agent references specific verses and words, but the scripture itself isn't visible alongside the study output. The reader has to open a separate tab or trust the quotation.

The goal: bring up the actual chapter text in an interactive panel when studying a passage, keep it visible during the study, and enable interactivity between the study output and the scripture panel.

## Bible Text Source: helloao.org

[bible.helloao.org](https://bible.helloao.org/) is a free Bible API by AO Lab (nonprofit). Key characteristics:

- **500+ translations** across hundreds of languages
- **No API keys, no rate limits, no authentication** — static JSON files on AWS
- **MIT licensed**, no copyright restrictions
- **Rich structured JSON** — headings, poetry formatting, footnotes, verse content
- **Commentaries** — 6 available (Adam Clarke, JFB, John Gill, Keil-Delitzsch, Matthew Henry, Tyndale Open Study Notes)
- **Cross-references** — 344,799 entries from OpenBible.info (CC BY 4.0)

### API Endpoints

| Endpoint | Example |
|---|---|
| List translations | `GET /api/available_translations.json` |
| Books in translation | `GET /api/{translation}/books.json` |
| Chapter content | `GET /api/{translation}/{book}/{chapter}.json` |
| List commentaries | `GET /api/available_commentaries.json` |
| Commentary chapter | `GET /api/c/{commentary}/{book}/{chapter}.json` |
| Commentary profiles | `GET /api/c/{commentary}/profiles.json` |
| List datasets | `GET /api/available_datasets.json` |
| Dataset chapter | `GET /api/d/{dataset}/{book}/{chapter}.json` |

Base URL: `https://bible.helloao.org`

### Chapter JSON Structure

```json
{
  "translation": { /* metadata */ },
  "book": { /* metadata */ },
  "chapter": {
    "content": [
      { "type": "heading", "content": ["The Creation"] },
      {
        "type": "verse",
        "number": 1,
        "content": [
          "In the beginning God created...",
          { "noteId": 1 },
          { "lineBreak": true },
          { "text": "poetic line", "poem": 1 }
        ]
      },
      { "type": "line_break" }
    ]
  },
  "footnotes": [
    { "noteId": 1, "caller": "+", "text": "Or...", "reference": { "chapter": 1, "verse": 1 } }
  ],
  "thisChapterAudioLinks": { /* audio URLs */ },
  "nextChapterApiLink": "...",
  "numberOfVerses": 31
}
```

## UI Technology: MCP Apps Extension

### What It Is

MCP Apps (`io.modelcontextprotocol/ui`) is an official extension to the Model Context Protocol, launched January 2026. It allows MCP servers to declare UI resources that clients render in sandboxed iframes with bidirectional JSON-RPC communication.

- Tools declare a UI via `_meta.ui.resourceUri` in tool metadata
- Server serves HTML at a `ui://` URI
- Host renders it in a sandboxed iframe
- Iframe communicates back via `postMessage` / JSON-RPC
- The app can call MCP tools, update context, receive data from the host

### Client Support

| Client | MCP Apps Support |
|---|---|
| Claude Desktop | Yes |
| Claude web (claude.ai) | Yes |
| ChatGPT | Yes |
| VS Code (GitHub Copilot) | Yes |
| Goose, Postman, MCPJam | Yes |
| **Claude Code (CLI)** | **No** — terminal app, cannot render iframes |

**Important constraint:** Claude Code users get text-only fallback (which is what the existing `lookup_verse` tool already provides). The panel is an enhancement, not a replacement.

## Architecture

```
┌─────────────────────────────────────────────────┐
│  MCP Client (Claude Desktop / claude.ai / etc.) │
│                                                 │
│  ┌───────────────────────────────────────────┐  │
│  │  Sandboxed iframe: Bible Reader Panel     │  │
│  │                                           │  │
│  │  Genesis 1 (BSB)              [BSB ▼]     │  │
│  │                                           │  │
│  │  ¹In the beginning God created the        │  │
│  │  heavens and the earth. ²The earth        │  │
│  │  was formless and void...                 │  │
│  │                                           │  │
│  │  [clickable words → Greek/Hebrew popover] │  │
│  └───────────────────────────────────────────┘  │
│                                                 │
│  Study output (text):                           │
│  "The word בָּרָא (bara') in v.1..."            │
│  Agent can trigger panel navigation/highlights  │
└─────────────────────────────────────────────────┘
         │ JSON-RPC / postMessage    ▲
         ▼                           │
┌─────────────────────────────────────────────────┐
│  studybible-mcp server                          │
│                                                 │
│  Existing 18 tools (unchanged)                  │
│  + New: bible_reader tool (triggers UI)         │
│  + New: ui://study-bible/reader resource (HTML) │
│                                                 │
│  Fetches from: bible.helloao.org/api/...        │
│  Cross-references with: local SQLite DB         │
└─────────────────────────────────────────────────┘
```

## Implementation Phases

### Phase 1: Core Bible Reader Panel

**Goal:** Chapter text appears in an interactive panel when studying a passage.

**New tool — `bible_reader`:**
- Inputs: `book`, `chapter`, `translation` (default BSB), `highlight_verses` (optional array)
- Declares UI via `_meta.ui.resourceUri: "ui://study-bible/reader"`
- Returns text content as fallback for non-UI clients

**New UI resource — `ui://study-bible/reader`:**
- Self-contained HTML/CSS/JS
- Fetches chapter JSON directly from helloao.org API
- Renders verses with proper formatting (headings, poetry indentation, footnotes)
- Highlights specified verses
- Translation selector dropdown (populated from available_translations.json)
- Chapter navigation (prev/next)

**Server changes:**
- Register `@server.list_resources()` with the UI resource
- Register `@server.read_resource()` to serve the HTML
- Add `bible_reader` tool handler
- Text-only fallback for Claude Code / non-UI clients

**Feasibility: Straightforward.** The helloao.org JSON maps cleanly to HTML. The MCP Apps iframe pattern is well-documented.

### Phase 2: Word-Level Interactivity

**Goal:** Click any word in the panel to see original language info. Greek/Hebrew words in the study output highlight in the panel.

**Panel → Server (user clicks a word):**
1. Iframe sends JSON-RPC message: `{"method": "wordClicked", "params": {"word": "created", "verse": 1}}`
2. Server looks up the word in the verse from TAGNT/TAHOT tagged text
3. Calls internal `word_study` logic — returns Strong's number, lexicon entry, morphology
4. Panel shows a tooltip/popover with Greek/Hebrew data

**Study text → Panel (agent mentions a word):**
1. Agent calls `bible_reader` with `{"highlight_words": [{"strongs": "H1254", "verses": [1]}]}`
2. Panel receives via JSON-RPC bridge, highlights/pulses that word in the text

**The word alignment problem:**
- helloao.org gives English text per verse
- Our `verses` table has morphology-tagged original text per verse
- We need to map English word positions to Strong's numbers
- **Best case:** BSB data on helloao.org includes Strong's numbers per word (some translations do) — need to verify
- **Fallback:** Server-side alignment using TAGNT/TAHOT — works well for content words (nouns, verbs), gets messy for function words
- **Scaled-back option:** Verse-level highlighting only, skip word-level mapping

**Feasibility: Medium.** Depends on whether helloao.org's BSB data includes Strong's numbers. If yes, straightforward. If no, requires a word alignment layer.

### Phase 3: Full Bidirectional Integration

**Goal:** Deep interactivity between study output and panel.

Features:
- **Cross-reference navigation:** "cf. Psalm 33:6" in study text → clickable link that navigates the panel
- **Footnote expansion:** Click footnote markers in panel to see helloao.org footnote data
- **Verse pinning:** Click a verse in panel → added to conversation context
- **Multi-translation comparison:** Split panel showing two translations side by side
- **Commentary overlay:** Toggle Tyndale/Gill/Matthew Henry notes alongside the verse text (from helloao.org commentary API)

**Feasibility: Each feature is individually tractable**, but together they represent significant UI engineering. The data sources exist (helloao.org has commentaries, cross-references), and the JSON-RPC bridge supports the communication patterns.

## Feasibility Summary

| Feature | Difficulty | Notes |
|---|---|---|
| Chapter text in panel | Straightforward | helloao.org JSON → rendered HTML |
| Verse highlighting | Straightforward | Pass verse numbers, CSS highlights |
| Translation switching | Straightforward | Dropdown, re-fetch from helloao.org |
| Text fallback (Claude Code) | Straightforward | Already exists via `lookup_verse` |
| Click word → tooltip | Medium | Requires word-to-Strong's alignment |
| Agent triggers panel navigation | Medium | JSON-RPC bridge, well-documented |
| Greek/Hebrew in study → panel highlights | Hard | Requires reliable word alignment |
| Commentary overlay | Medium | helloao.org has the data, UI work |
| Multi-translation comparison | Medium | Two fetches, split layout |
| Verse pinning to context | Medium | JSON-RPC context update |

## Recommendation

**Start with Phase 1 + verse-level highlighting.** This delivers 80% of the value with 20% of the complexity. A panel that shows the chapter, highlights the verses being studied, and supports translation switching is immediately useful.

Before starting Phase 2, verify the BSB data format on helloao.org — check whether `content` arrays in verse objects include Strong's numbers or other alignment data. This determines whether word-level interactivity is a weekend project or a multi-week alignment effort.

## Open Questions

1. Does the Python MCP SDK (`mcp>=1.0.0`) support the `io.modelcontextprotocol/ui` extension, or do we need a newer version?
2. Does the BSB translation on helloao.org include Strong's numbers in its verse content?
3. Should the iframe fetch directly from helloao.org, or should the server proxy/cache responses?
4. What's the right UX when the user is in Claude Code (no panel)? Just the existing text output, or something enhanced?
