# Study Bible MCP - Release Notes

---

## Full Scholarly Lexicons & BibleAquifer Integration

### New Data Sources

- **Full LSJ Greek Lexicon** (TFLSJ) — Replaces the brief TBESG
  lexicon with the complete Liddell-Scott-Jones scholarly definitions
  (10,846 entries). Greek word studies now show both a brief gloss
  and the full LSJ entry.
- **Full BDB Hebrew Lexicon** — Replaces the brief TBESH lexicon
  with the complete unabridged Brown-Driver-Briggs (8,090 entries).
  Hebrew word studies now show the full BDB scholarly definition.
- **Tyndale Study Notes** — Verse-level scholarly commentary for
  all 66 books.
- **Tyndale Bible Dictionary** — 500+ topical articles covering
  people, places, theology, history, and archaeology.
- **UW Translation Notes** — Translator-focused commentary with
  linguistic insights (49+ books).
- **SIL Translator Notes** — Additional translation and cultural
  context.
- **FIA Key Terms** — 200+ carefully defined theological/biblical
  terms with translation guidance.
- **ACAI Entity Annotations** — 3,175 rich entity records (people,
  places, groups, key terms) with variant names, roles, family
  relationships, speech attributions, and verse reference counts.

### New Tools

**`get_study_notes`** — Get combined scholarly commentary from
Tyndale, UW, and SIL sources for any verse or chapter. Supports
both verse-specific and chapter-level queries.

**`get_bible_dictionary`** — Look up topics in the Tyndale Bible
Dictionary. Searches by title (exact then LIKE) across 500+
articles.

**`get_key_terms`** — Look up theological terms in the FIA Key
Terms database. 200+ terms with definitions, biblical usage, and
translation guidance.

### Enhancements

- **`word_study`** now shows separate "Brief Definition" and "Full
  LSJ Definition" (Greek) or "Full BDB Definition" (Hebrew)
  sections. Full definitions are truncated at 3,000 characters with
  a note that the full entry is available.
- **`lookup_name`** now enriched with ACAI data when available:
  variant names (e.g. Abraham/Abram), roles, verse reference count,
  and attributed speech count.
- Database grew from 323MB to 355MB with 102,673 Aquifer content
  entries and 3,175 ACAI entity records added.

### Testing

- Added 71 pytest tool selection tests (`tests/test_tool_selection.py`)
  verifying the agent picks the correct tool for natural language
  queries without explicit tool names. Uses a keyword-based scorer
  with bigrams and IDF normalisation to simulate LLM tool selection.

### Documentation

- Updated architecture diagram (ARCHITECTURE.md) with all 17 tools
  including the new Commentary path, light blue colour category, and
  three new typical tool chains.
- Rewrote README with all data sources, all 17 tool descriptions,
  current database stats, and updated project structure.

### Technical Details

- New `aquifer_content` table with indexes on resource type,
  reference, book, and title
- New `acai_entities` table with indexes on entity type and name
- Generic Aquifer JSON parser handles all five resource types with
  a single `parse_aquifer_content_file()` function
- ACAI parser handles per-entity JSON files across four type
  directories (people, places, groups, keyterms)
- TFLSJ parser converts HTML definitions to markdown (bold, italic,
  line breaks) via `clean_lsj_definition()`
- BDB parser extracts headword, transliteration, and gloss from
  HTML definition headers via `_extract_bdb_headword()`
- Download script gains `--aquifer` flag for BibleAquifer and ACAI
  resources; uses GitHub API for ACAI directory listing

---

## Semantic Vector Search

### What's New

**`find_similar_passages`** - A new tool that discovers thematic
connections across the Bible using vector embeddings. Unlike
cross-references or shared vocabulary, this finds passages with
similar *meaning* even when different words are used.

### How It Works

Every verse and passage in the Bible has been pre-embedded using
OpenAI embeddings (1,536 dimensions). Given a verse reference,
the tool searches across **31,280 verse embeddings** and
**5,190 passage embeddings** using cosine similarity via
sqlite-vec, returning the most semantically similar passages
ranked by score.

### Example Discoveries

- Daniel 7:13-14 (Son of Man vision) finds Revelation 1:7,
  14:14 (similar imagery)
- Exodus 12:1-13 (Passover) finds John 1:29, 1 Corinthians 5:7
  (Lamb imagery)
- Isaiah 53:4-6 (Suffering Servant) finds 1 Peter 2:24-25
  (echoes of Isaiah)
- Proverbs wisdom themes find James practical wisdom

### Hermeneutical Safeguards

The tool description includes built-in guardrails instructing
the agent to verify genre compatibility, historical context,
and literary context before presenting a similar passage as
theologically relevant. It distinguishes between direct
quotation, deliberate allusion, shared tradition, and
coincidental similarity.

### Technical Details

- Uses sqlite-vec virtual tables for efficient vector search
- Pre-computed OpenAI embeddings (1,536 dimensions)
- 31,280 verse-level + 5,190 passage-level embeddings
- Cosine distance search with similarity scoring (0-1)

---

## Graph-Based Biblical Knowledge

### What's New

Six new tools powered by the Theographic Bible Metadata, adding
relationship-aware queries across **3,069 biblical people**,
**1,274 places**, **450 events**, and **53,120 verse-entity
mentions**.

### New Tools

**`explore_genealogy`** - Trace family trees through biblical
history. Ask for ancestors, descendants, or both, with
configurable generation depth. Returns formatted family trees
with Mermaid diagrams.

**`people_in_passage`** - Find every person, place, and event
mentioned in a chapter or verse. Turns any passage reference
into a cast of characters with their relationships.

**`explore_person_events`** - Get a chronological timeline of a
biblical figure's life events with locations. Includes a Mermaid
timeline diagram.

**`explore_place`** - Explore what happened at a biblical
location across all of Scripture - events, people born or who
died there, with geographic coordinates. Includes a Mermaid
network diagram.

**`find_connection`** - Find the shortest relationship path
between any two biblical people through family edges (parent,
child, sibling, partner). Shows the chain from Abraham to David
in ~14 steps, or Ruth to Jesus through Boaz's lineage. Includes
a Mermaid flowchart.

**`graph_enriched_search`** - Combines verse lookup with graph
context. Given a verse reference, returns the text alongside all
mentioned entities and their family relationships - the most
comprehensive single-query tool for deep verse study.

### Visual Output

All graph tools include **Mermaid diagrams** that render in
Claude Desktop and other markdown-capable clients:

- Genealogy flowcharts with styled focal person, ancestors,
  descendants, and spouses
- Connection path flowcharts showing relationship chains
- Timeline diagrams for person event histories
- Place network graphs linking locations to events and people

### Bug Fixes

- **Lexicon data corrected**: The TBESG/TBESH parser was reading
  the wrong columns, resulting in Greek/Hebrew words appearing
  where definitions should be and vice versa. All 20,192 lexicon
  entries now have correct words, transliterations, and
  definitions.
- **Strong's number lookup fixed**: Queries like `G26` now
  correctly match the zero-padded database format `G0026`.
  Affects `word_study`, `search_by_strongs`, and
  `search_lexicon`.

### Technical Details

- Graph traversal uses **SQLite recursive CTEs** for
  ancestor/descendant queries and **Python-side BFS** for
  shortest-path finding
- No external dependencies added - everything runs on the
  existing SQLite database (+5MB for graph data)
- All queries return in under 500ms, including 40-generation
  genealogy traversals
- Deployed to Fly.io `iad` region with auto-stop/start
