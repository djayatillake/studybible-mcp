# Study Bible MCP - Release Notes

---

## Verse ranges and chapters in lookup_verse

- `lookup_verse` now returns every verse of a range (`Luke 19:1-3`, en dash
  accepted), a cross-chapter range (`Luke 19:45-20:2`), or whole chapters
  (`Luke 19`, `Psalm 23-24`); previously a range returned only its first verse
  and a chapter returned "Verse not found".
- Verses are matched on English book/chapter/verse numbering instead of
  reference strings, so split English(Hebrew) references such as
  `Psa.40.6(40.7)` resolve directly, and an English verse stored as two source
  rows (e.g. `1 Chronicles 12:4`) returns both.
- Passages are capped at 50 verses with a note naming the continuation
  reference; reversed ranges, unknown books, and missing chapters or verses get
  a message stating what exists.
- Cross-reference, Torah Weave, and LXX-quotation notes appear once per
  passage and point at a verse inside it. Single-verse output is otherwise
  unchanged.
- Single-chapter books (Obadiah, Philemon, 2 John, 3 John, Jude) can be cited
  by verse alone (`Jude 3`, `Philemon 6`, `3 John 4`) in every tool's
  reference argument; previously `Jude 3` was read as chapter 3.
- Psalm superscriptions are headed `Psa.82 superscription (Hebrew Psa.82.1)`
  instead of the raw `Psa.82.0(82.1)`.

---

## Research Sources Catalogue & Link Checker

### New Tool

**`list_research_sources`** lists 37 freely accessible research
repositories that an agent can consult before a general web search,
which mostly surfaces blogs and advocacy sites. The catalogue covers
primary-text libraries, open-access journals, Dead Sea Scrolls and
Septuagint resources, patristic and Reformation texts, and Heiser's own
sites. Each entry records its coverage, perspective and access or
licence terms, and the date it was last verified. The tool filters by
`topic` (loosely, against coverage tags and names) and by
`perspective`. With `query`, it adds a URL-encoded search link for
every source that supports one. The output states that these are
places to look, not endorsements.

`get_theology_context` and `get_study_notes` now point to the new tool
for perspectives, journals and primary texts that they do not cover.

### Link Checker

`scripts/check_links.py` checks, over the network, every catalogue URL,
every search template filled with a sample query, and (when the database
is present) every distinct `theology_content.url`. It falls back from `HEAD` to
`GET`, reports broken links (status 400 or above, or a network error)
with their origin, and exits non-zero when any link is broken. A
timed-out link is retried once with a 60-second limit and reported as
`TIMEOUT` if it persists. Hosts known to be slow but working
(`drmsh.com`, 31-57 s) get a 180-second retry, and a persistent timeout
there is reported as `SLOW`, a warning that does not fail the run. Sites
that block automated clients carry an explicit `link_check: "skip"`
with a reason.

---

## Textual evidence and interpretation separation

- Replaced the mixed textual-variant record with independent tables and output
  sections for manuscript readings and witnesses, critical judgments,
  theological interpretations, named-author claims, and translation decisions.
- Classified every witness with an explicit evidence type. Manuscripts attach
  to the reading they support. NT quotations are reported as citation
  evidence, scrolls that attest a text form only elsewhere in the book as
  indirect evidence, and corpora with no copy of the verse in a case-level
  "Not preserved in" note. At Jeremiah 33:14 the Masoretic Text now supports
  the MT long reading instead of the LXX omission. Unknown support labels
  abort the import, and the raw label is preserved on every witness.
- Limited "Critical judgments" to conclusions with a source citation. Uncited
  dataset summaries are shown separately as an unsourced dataset summary that
  has not been verified against published text-critical scholarship.
- Kept NT quotation alignment separate from both textual evidence and the HLT's
  translation decisions.
- Kept the legacy `MT_preserved` and `translation_choice` records (18 verses,
  e.g. Psalm 82:6, Genesis 6:2, Daniel 7:13) as interpretive cases. The MT and
  the versions agree at these verses, so they are shown under "Translation and
  interpretation notes" with the MT as the only reading, never as variants.
  Their HLT readings and rationales become translation decisions, Heiser's
  analysis an author claim, and the record's prose attributed interpretation.
- Omitted output sections with nothing catalogued instead of printing
  "No ... catalogued" placeholders.
- Added a one-time migration that preserves every legacy record, witness, and
  NT quotation link while removing the obsolete mixed tables.
- Exported the six variant cases that existed only in the database (Jeremiah
  33:14, Psalm 40:6, Psalm 8:2, Isaiah 61:1, Isaiah 40:5, Amos 9:12) to
  `data/heiser/variants/lxx_cases.json`, and the 18 NT quotation hints to
  `data/heiser/lxx_quote_hints.json`, so a fresh build reproduces them. Added
  the Deuteronomy 32:43 rationale's Hebrews 1:6 sentence to the bundled JSON,
  so re-importing it no longer reverts the database text.
- Made each variant record's replacement atomic: records are validated before
  any row is deleted and written inside a savepoint. A malformed record keeps
  its previously imported rows and fails the import with an error instead of
  being skipped silently.
- `get_textual_variant` now distinguishes a legacy or missing schema (run
  `python scripts/upgrade_database.py`), a reference that is not a single
  verse, and a verse with no catalogued case. `lookup_verse` now mentions
  catalogued variant cases and, separately, translation and interpretation
  notes.
- Added `scripts/upgrade_database.py`, a repeatable in-place upgrade. It
  downloads the pinned sources, migrates, imports MT/LXX, Josephus, and the
  bundled variants, and checks integrity and foreign keys on a temporary copy
  before atomically replacing the database.
- `scripts/smoke_server.py` now decides skips from table row counts and fails
  tools that return empty or no-match results when their data is present.
- The Fly runbook and `scripts/upload-db.sh` now upload next to the live
  database, verify size and SHA-256, and `mv` the file into place. They also
  check free space with `df` and never delete the live database first.

---

## Josephus primary-source search

- Added `search_ancient_sources` with full-text, corpus, biblical-reference,
  editorial-period, and result-limit controls.
- Added 2,304 Whiston sections across all four surviving Josephus works, each
  paired with every Niese Greek section it spans and referenced as a Niese span
  plus Whiston's numbering (`Antiquities 18.116–119 (Whiston 18.5.2)`).
- Added Porter-stemmed English search, accent-insensitive Greek search, and an
  explicitly labelled any-term fallback when no passage contains every word.
- Added 33 curated narrative-overlap biblical links, each verified against the
  passage text and resolved by section containment; `biblical_reference`
  accepts chapters, verses, and verse ranges.
- Added checksum verification at a pinned Perseus commit, a build check for all
  eight TEI files, and preserved edition, translation, license, and source URL
  on each passage.
- Kept editor notes and Whiston's chapter headings out of primary-source text,
  and labelled period tags, headings, and biblical links as editorial metadata.
- Empty results distinguish a missing corpus, an unsupported reference, a
  reference without curated links, and no matching passage.

---

## Brenton's English checked against Brenton's own Greek

- Brenton's English translates his own 1844 Greek edition (chiefly Codex
  Vaticanus), not the Rahlfs text shown beside it. Every LXX row with his
  English now carries a standing note saying so, and that his English sometimes
  departs even from his own Greek.
- Added Brenton's public-domain Greek text (eBible `grcbrent`, stored in
  `data/lxx/brenton-greek`), pinned by the SHA-256 of each extracted USFM book
  like the English.
- Each verse with Brenton's English is compared with his Greek for the same
  verse after spelling noise is levelled (accents, case, punctuation, elision,
  movable nu, itacism, doubled consonants, nasal assimilation, crasis,
  Hellenistic spellings, word division, name spellings, one-letter keying
  errors) and verse-division differences are absorbed. Rows whose word
  sequences still differ get a warning, a summary (word order, substitutions,
  additions, omissions), and Brenton's Greek labelled as the text his English
  translates: Deuteronomy 32:43 reports "word order differs (υἱοὶ ἄγγελοι)" and
  Psalm 40:6 "Brenton's Greek reads σῶμα for ὠτία". Psalm 82:6 and Sirach 17:17
  agree and show only the note.
- 10,756 of the 28,314 rows with Brenton's English (38%) are flagged. Brenton's
  Greek and the summary are stored only on flagged rows, which adds about 5 MB to
  the database. Existing comparison tables gain the new columns on re-import.

---

## Provenance-aware Septuagint comparison

- Added `compare_biblical_versions` with MT/LXX selection and independent
  original-text and morphology controls. References can be single verses,
  ranges within or across chapters (`Psalm 81:6-82:1`), or whole chapters
  (`Psalm 82`); `numbering="lxx"` reads them in Greek edition numbering.
- Added all 59 books of the pinned Rahlfs morphology corpus plus the
  public-domain Brenton translation, attached only to the recension Brenton
  translated (Theodotion Daniel/Susanna/Bel, Vaticanus B Joshua/Judges).
- MT rows are built at query time from the existing TAHOT verses (English
  canonical numbering, Hebrew numbering as the edition reference) instead of
  being copied, so the comparison adds about 35 MB to the database rather than
  about 200 MB.
- Every returned row carries version, edition, language, canonical reference,
  edition reference, text, English, license, and source URL; MT English is
  labelled as STEPBible word glosses, not a translation.
- Added explicit MT/LXX verse mapping, including Hebrew/Greek Psalm numbering,
  rather than calculating offsets. LXX-only verses have no canonical position
  and are never shown as the counterpart of a different MT verse.
- Added per-book SHA-256 verification of the Brenton USFM, Git-blob
  verification of the LXX sources, and a build-time check that fails on
  partial downloads.
- Distinct messages for New Testament references, unparseable references, no
  matching verses, and a missing comparison table.

---

## Theology Source Links

- **Owen entries link to his text.** All 45 Owen entries now carry a
  Source URL to the free public-domain text: the CCEL chapter or part
  each entry draws on, or (for the Exposition of Hebrews, which CCEL
  lacks) the Monergism PDF of the volume covering that chapter.
- **Burnett** entries link to his own free serialisation of the
  argument on drmsh.com; the JSPL article itself is not openly hosted.
- **Heiser**: fixed two dead Naked Bible transcript links (episodes 94
  and 334), pointed the Jude entries at the episode 434 transcript
  instead of the podcast home page, and linked the nachash entry to the
  episode 143 transcript.
- Bradley, Stott, and Lennox stay unlinked: no free copy is hosted by
  the author or publisher.
- **Entry-level `url`** in content JSON overrides the file-level one.
- **Re-runnable importers.** Re-importing into an existing DB refreshes
  `url` on existing rows (matched on source_work, chapter_or_episode,
  title) without duplicating rows or changing their content, and no
  longer duplicates theme links on every run. The importers take an
  optional DB path; `ingest_burnett_gage.py --theology-only` reloads
  only the Burnett entries. See README → Theological Scholarship for
  the upgrade commands.
- Content JSON `source_key`/`type` now carry the descriptive labels
  that `relabel_theology_sources.py` applied, so fresh builds and
  relabelled DBs agree.

---

## Deterministic theology-context ordering

- `get_theology_context` by reference now lists primary entries before
  secondary/supporting ones. `relevance` is text, so the previous
  `ORDER BY relevance DESC` put `supporting` ahead of `primary` (e.g.
  "Deuteronomy 32:17 — Demons are Elohim" first for Psalm 82:6).
- Ties are broken by verse and entry id, and theme lists are sorted, so the
  hosted server and local databases return the same order.
- Chapter-level fallbacks report each entry's best-ranked matching verse.

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
- **Aquifer Open Study Notes** — Verse-level scholarly commentary for
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
Aquifer Open Study Notes, UW, and SIL sources for any verse or chapter. Supports
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
