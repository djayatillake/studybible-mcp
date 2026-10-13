# Study Bible MCP Server

A Bible study assistant for Claude that provides full scholarly lexicons (LSJ Greek, BDB Hebrew, Abbott-Smith NT Greek), morphologically-tagged biblical texts, cross-references, Theographic genealogy graphs, Aquifer Open Study Notes, a Bible dictionary, key theological terms, Ancient Near East cultural context, and hermeneutical methodology based on Fee & Stuart's "How to Read the Bible for All Its Worth".

## Quick Start

### Claude Desktop

1. Open **Settings** → **Connectors**
2. Click **Add Custom Connector**
3. Paste: `https://studybible-mcp.fly.dev/sse`
4. Restart Claude Desktop

That's it. No signup, no API keys, no downloads.

### Claude Code

```bash
claude mcp add study-bible https://studybible-mcp.fly.dev/sse
```

### ChatGPT (Developer Mode)

1. Open **Settings** → **Developer Mode** → enable it
2. Go to **Actions** → **Add MCP Server**
3. Enter URL: `https://studybible-mcp.fly.dev/mcp/`

### Cursor / Windsurf / Cline

Add to your MCP configuration (usually `.cursor/mcp.json`, `.windsurf/mcp.json`, or Cline settings):

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

### Install via pip / uvx (local stdio)

```bash
pip install studybible-mcp
studybible-mcp --transport stdio
```

Or run directly without installing:

```bash
uvx studybible-mcp --transport stdio
```

### Manual Config (Alternative)

If you prefer editing config files directly:

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
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`
- Linux: `~/.config/Claude/claude_desktop_config.json`

---

## How It Works

### Architecture Overview

```
┌─────────────────────┐     ┌──────────────────────────────────────────┐
│   Claude Desktop    │     │   Study Bible MCP Server                 │
│   or Claude Code    │     │   (Fly.io)                               │
│                     │     │                                          │
│  ┌───────────────┐  │ MCP │  ┌─────────────┐  ┌───────────────────┐  │
│  │ User asks a   │──┼─────┼─▶│ MCP Server  │─▶│ SQLite DB (600+MB)│  │
│  │ Bible question│  │     │  │ (Python)    │  │                   │  │
│  └───────────────┘  │     │  └─────────────┘  │ • Lexicons (LSJ,  │  │
│                     │     │        │          │   BDB, Abbott-     │  │
│  ┌───────────────┐  │     │        ▼          │   Smith, Strong's) │  │
│  │ Claude uses   │◀─┼─────┼── Tool Results    │ • Tagged NT + OT  │  │
│  │ study tools to│  │     │                   │ • Names + ACAI    │  │
│  │ answer        │  │     │                   │ • Morphology      │  │
│  └───────────────┘  │     │                   │ • Study Notes     │  │
│                     │     │                   │ • Bible Dictionary │  │
│                     │     │                   │ • Key Terms        │  │
│                     │     │                   │ • ANE Context      │  │
│                     │     │                   │ • Embeddings       │  │
│                     │     │                   └───────────────────┘  │
└─────────────────────┘     └──────────────────────────────────────────┘
```

When you ask Claude a Bible question:
1. Claude analyses your question and decides which tools to use
2. Claude calls the appropriate MCP tools (e.g., `lookup_verse`, `word_study`, `get_study_notes`)
3. The server queries the pre-built SQLite database
4. Results are returned to Claude
5. Claude synthesises the data into a helpful response

See [ARCHITECTURE.md](ARCHITECTURE.md) for a full Mermaid flowchart of the available tools and how the agent chains them together.

### The Database

The server includes a pre-built SQLite database (~600MB) containing:

| Table | Rows | Content |
|-------|------|---------|
| `lexicon` | 19,391 | Greek (Full LSJ + Abbott-Smith NT) and Hebrew (Full BDB) word definitions with Strong's numbers |
| `verses` | 31,280 | Every verse of the Bible with morphology tags |
| `passages` | 5,290 | Verses grouped by ancient section markers |
| `names` | 4,299 | Biblical people, places, and things |
| `morphology` | 2,768 | Grammatical parsing code definitions |
| `thematic_references` | 22 | Core theological theme cross-references |
| `aquifer_content` | 102,673 | Study notes, dictionary articles, translation notes, key terms |
| `acai_entities` | 3,175 | Rich entity annotations (people, places, groups, key terms) |
| `ane_entries` | 87 | Ancient Near East cultural context entries across 12 dimensions |
| `ane_book_mappings` | 314 | Maps ANE entries to biblical books and chapter ranges |
| `verse_vectors` | 31,280 | OpenAI embeddings for semantic search |
| `passage_vectors` | 5,190 | OpenAI embeddings for passage similarity |

---

You can download the pre-built database directly: **[study_bible.db](https://studybible-mcp.fly.dev/download/study_bible.db)** (~600MB)

---

## Available Tools

### Core Text & Language

#### 1. `lookup_verse`

Retrieve a verse, verse range, or whole chapter with its original language text and word-by-word analysis.

**When Claude uses it**: User asks about a specific verse or passage, wants to see the Greek or Hebrew text, or asks about specific words in a passage.

**Accepted references**: a verse (`John 3:16`), a range within a chapter (`Luke 19:1-3`; an en dash also works), a cross-chapter range (`Luke 19:45-20:2`), or whole chapters (`Psalm 23`, `Psalm 23-24`). Single-chapter books (Obadiah, Philemon, 2 John, 3 John, Jude) may be cited by verse alone, as is conventional: `Jude 3` means `Jude 1:3` and a bare `Jude` means the whole book. This applies to every tool's `reference` argument. Verses are matched by English chapter/verse numbering, so Old Testament verses whose Hebrew numbering differs (e.g. `Psalm 40:6`, stored as `Psa.40.6(40.7)`) are found, and an English verse stored as several source rows returns all of them. A Psalm superscription, which is verse 1 in the Hebrew, is headed as such (`Psa.82 superscription (Hebrew Psa.82.1)`). A passage returns at most 50 verses; longer requests (e.g. `Psalm 119`) open with a note naming the reference that continues the passage. Unknown books, missing chapters or verses, and reversed ranges get a message saying what exists.

**What it returns**: English word-by-word gloss text, original Greek/Hebrew text, word-by-word breakdown with Strong's numbers, optional morphological parsing, and genre-specific interpretation guidance. Notes about cross-references, Torah Weave partners, and NT/OT LXX quotations appear once per lookup; for a passage they name a verse to pass to those single-verse tools.

**Example**:
```
User: "Look up Romans 8:28 with the Greek"

Claude calls: lookup_verse(reference="Romans 8:28", include_original=true)

Returns:
- Verse text in English
- Greek: πάντα συνεργεῖ εἰς ἀγαθόν...
- Word analysis: συνεργεῖ (G4903) = "works together" [V-PAI-3S]
- Genre guidance: "Epistles - What problem was being addressed?"
```

#### `compare_biblical_versions`

Compare the Masoretic Text and Septuagint with explicit per-verse provenance.
Covers Old Testament and Septuagint books only. Rows that share a canonical
(MT/English) reference appear under one header, while each row keeps its own
edition reference, so Hebrew/Greek Psalm numbering and other mapped
versification shifts stay visible. Psalm 82:6, for example, shows MT `Psa.82.6`
and LXX `Psa.81.6`; Psalm 40:6 shows MT `Psa.40.7` (Hebrew numbering) and LXX
`Psa.39.7`.

```text
compare_biblical_versions(
  reference="Psalm 24:1",        # also "Psalm 82:1-8", "Psalm 81:6-82:1", "Psalm 82"
  versions=["MT", "LXX"],
  numbering="canonical",          # or "lxx" to read the reference in Greek numbering
  include_original=true,
  include_morphology=false
)
```

Each edition row names its version, edition, and edition reference (plus the
versification mapping whenever it is not `identity`), then its original text and
English. Licences, source URLs, translation labels, the verse-mapping credit, and
the Brenton caveat are listed once in a closing **Sources** block rather than on
every row. A call returns at most 10 verses; a longer range or chapter is cut
there with a note naming the verse to continue from.

- **MT** comes from the STEPBible TAHOT verses already in the database (Westminster
  Leningrad Codex). Its English is STEPBible word glosses (interlinear, not a
  translation).
- **LXX** covers all 59 books of the Rahlfs source edition. Brenton's English is
  shown only for the recension Brenton translated (Theodotion for Daniel, Susanna
  and Bel; Vaticanus B for Joshua and Judges); Old Greek and Alexandrinus rows say
  the translation is not available for that edition.
- **Brenton's English is not a translation of the Rahlfs text.** Brenton (1844)
  translated his own Greek edition, based chiefly on Codex Vaticanus, and his
  English sometimes departs even from that Greek. Every row with his English
  carries a note saying so. Each such verse is also compared with
  [Brenton's own Greek](https://ebible.org/details.php?id=grcbrent) after
  spelling noise is removed: accents, breathings, case, punctuation, elision,
  movable nu, itacism (ει/ι), doubled consonants, nasal assimilation, crasis,
  Hellenistic spellings (λήμψομαι/λήψομαι), word division (ἀνὰ μέσον/ἀναμέσον),
  name spellings, and one-letter keying errors in Brenton's digital text. Where
  his Greek still adds, lacks, substitutes, or reorders words, the row shows a
  warning, a difference summary, and Brenton's Greek as the text his English
  translates. Deuteronomy 32:43, for example, reports "word order differs (υἱοὶ
  ἄγγελοι)", and Psalm 40:6 reports "Brenton's Greek reads σῶμα for ὠτία".
  Differing verse divisions do not count as differences. About 38% of the
  28,314 rows with Brenton's English are flagged. Unflagged rows (Sirach 17:17,
  where the English adds words his Greek lacks) can still differ, because a
  Greek-to-Greek comparison cannot see where his English departs from his own
  Greek.
- **LXX-only verses** (pluses such as the Prayer of Azariah, Psalm 151, and the
  Septuagint-only books) have no canonical MT position, so they never appear as
  the counterpart of a different MT verse. Request them with `numbering="lxx"`; a
  canonical lookup notes when such verses sit at the same Greek-numbered
  position. Septuagint-only books (Tobit, Sirach, ...) always use Greek numbering.

New Testament references, unparseable references, and references with no
matching verses each return a specific message. A database without the
Septuagint table tells you to run `python scripts/upgrade_database.py`.

#### `search_ancient_sources`

Search licensed primary-source corpora for Jewish history. The initial
`josephus` corpus contains 2,304 Whiston sections from *Jewish Antiquities*,
*The Jewish War*, *Life*, and *Against Apion*. Each section is paired with
every Niese Greek section it spans and referenced as a Niese span plus
Whiston's numbering, e.g. `Antiquities 15.317–322 (Whiston 15.9.3)`. Each
result shows up to 1,500 characters of English around the first match and a
shorter Greek excerpt (match-centred when the query is Greek); the edition,
translation, license, and pinned source are listed once at the end. Up to 4
passages are returned by default.

```text
search_ancient_sources(
  query="John Baptist",
  corpus="josephus",
  biblical_reference="Mark 6:20",
  period="second_temple",
  limit=4
)
```

Only the passage text is searched, so a word that appears only in a work
title (`Jewish`, `War`, `Life`) does not match every passage of that work.
English search is stemmed (`build` matches `building`); Greek search ignores
accents, breathings, and case (`βαπτισμω` matches `βαπτισμῷ`). Passages
containing every query word come first; when none do, passages matching any
word are returned with an explicit note. `biblical_reference` accepts a
chapter, verse, or verse range (`Luke 21`, `Luke 21:5`, `Luke 21:5-6`) and
filters to 33 curated narrative-overlap links, each checked against the linked
passage text. Period tags, biblical links, and Whiston's chapter headings are
labelled editorial metadata; they are not presented as claims made by
Josephus. Empty results say whether the corpus is missing, the reference is
unsupported, the reference has no curated link, or nothing matched.

#### 2. `word_study`

Deep dive into a Greek or Hebrew word's meaning, usage, and etymology. Greek entries include both the full Liddell-Scott-Jones (LSJ) definition for classical breadth and the Abbott-Smith definition for NT-specific insight (with LXX/Hebrew equivalents, synonym discussions, and NT occurrence counts). Hebrew entries include the full Brown-Driver-Briggs (BDB) definition.

**When Claude uses it**: User asks about the meaning of a Greek/Hebrew word, wants to understand different translations of a term, or asks about theological concepts (love, faith, grace).

**What it returns**: Original word in Greek/Hebrew script, transliteration, Strong's number, brief definition, full LSJ or BDB scholarly definition, Abbott-Smith NT-focused definition (Greek words), LXX/Hebrew cross-references, synonym discussions, NT occurrence count, etymology, usage count, semantic range, related words, example passages.

**Example**:
```
User: "What does 'agape' mean in Greek?"

Claude calls: word_study(strongs="G26")

Returns:
- ἀγάπη (agapē, G26)
- Brief Definition: "love, goodwill, benevolence"
- Full LSJ Definition: [scholarly entry with classical and biblical usage]
- Abbott-Smith Definition: [NT-focused entry with sense hierarchy]
- LXX / Hebrew Equivalents: H0160 אַהֲבָה
- Synonyms: SYN.: φιλία — love which chooses its object...
- NT Usage: Occurs 116 times in the New Testament
- Related words: ἀγαπάω (to love), ἀγαπητός (beloved)
```

#### 3. `search_lexicon`

Search across Greek and Hebrew lexicons by English meaning.

**When Claude uses it**: User wants to find the Greek/Hebrew word for an English concept, asks "How do you say X in Greek?", or is exploring related words.

**Example**:
```
User: "What are the Greek words for 'love'?"

Claude calls: search_lexicon(query="love", language="greek")

Returns:
- G26 ἀγάπη - divine, unconditional love
- G5368 φιλέω - brotherly, affectionate love
- G2309 θέλω - desire, wish
```

#### 4. `get_cross_references`

Find passages related to a verse or theological theme.

**When Claude uses it**: User asks "What other passages talk about X?", wants to see Scripture interpreting Scripture, or is studying a theological theme.

**Built-in themes**: `salvation_by_grace`, `deity_of_christ`, `atonement`, `resurrection`, `holy_spirit`, `justification`.

**Example**:
```
User: "What passages support salvation by grace alone?"

Claude calls: get_cross_references(theme="salvation_by_grace")

Returns:
- Genesis 15:6 - Abraham believed, credited as righteousness
- Romans 3:21-26 - Righteousness through faith in Christ
- Ephesians 2:8-9 - Saved by grace through faith
- Titus 3:5-7 - Not by works of righteousness
```

#### 5. `lookup_name`

Get information about biblical people, places, and things, enriched with ACAI entity annotations (variant names, roles, reference counts, speech attributions).

**When Claude uses it**: User asks "Who was X?", wants to know about a place's significance, or asks about relationships between biblical figures.

**What it returns**: Original Hebrew/Greek form, type (person, place, thing), description, key references, relationships (father, mother, children), ACAI annotations (variant names, roles, verse reference count, attributed speeches).

**Example**:
```
User: "Who was Abraham?"

Claude calls: lookup_name(name="Abraham")

Returns:
- Type: Person
- Original: אַבְרָהָם
- Description, key references, family relationships
- ACAI: Also known as "Abram", referenced in 275 verses, 52 attributed speeches
```

#### 6. `parse_morphology`

Explain Greek or Hebrew grammatical parsing codes.

**When Claude uses it**: User asks what a morphology code means or wants to understand verb tense, mood, voice.

**Example**:
```
User: "What does V-AAI-3S mean?"

Claude calls: parse_morphology(code="V-AAI-3S", language="greek")

Returns:
- Part of Speech: Verb
- Tense: Aorist, Voice: Active, Mood: Indicative
- Person: 3rd, Number: Singular
```

#### 7. `search_by_strongs`

Find all verses containing a specific Strong's number.

**When Claude uses it**: User wants to see how a word is used throughout Scripture or is doing a comprehensive word study.

**Example**:
```
User: "Show me all the places where 'hesed' (H2617) appears"

Claude calls: search_by_strongs(strongs="H2617", limit=20)

Returns:
- H2617 חֶסֶד (hesed) - "lovingkindness, steadfast love"
- Genesis 24:12, Exodus 34:6, Psalm 23:6, Psalm 136...
```

### Scholarly Commentary

#### 8. `get_study_notes`

Get scholarly study notes and translation notes for a Bible verse or chapter.

**When Claude uses it**: User wants commentary on a specific verse, help explaining a difficult passage, or translation and cultural background notes.

**What it returns**: Combined commentary from three sources: Aquifer Open Study Notes (66 books of concise verse-level scholarly commentary), unfoldingWord Translation Notes (translator-focused linguistic insights), and SIL Translator Notes (additional translation and cultural context).

**Example**:
```
User: "What do the study notes say about John 3:16?"

Claude calls: get_study_notes(reference="John 3:16")

Returns:
- Aquifer Open Study Notes: [verse commentary]
- Translation Notes (UW): [linguistic insights]
- Translation Notes (SIL): [cultural context]
```

#### 9. `get_bible_dictionary`

Look up a topic in the Tyndale Bible Dictionary.

**When Claude uses it**: User needs background information on a biblical topic, historical or cultural context, or a detailed article about a person, place, or concept.

**What it returns**: Full dictionary article from a collection of 500+ topical articles covering biblical people, places, theological concepts, cultural practices, historical background, and archaeological findings.

**Example**:
```
User: "Tell me about the Pharisees"

Claude calls: get_bible_dictionary(topic="Pharisees")

Returns: Full Tyndale Bible Dictionary article with historical background,
beliefs, practices, and NT context.
```

#### 10. `get_key_terms`

Look up a key theological term in the FIA Key Terms database.

**When Claude uses it**: User wants a precise definition of a theological term, or needs to understand how a concept is used across Scripture.

**What it returns**: Definition from a collection of 200+ carefully defined theological and biblical terms with biblical usage, cross-references, and translation guidance.

**Example**:
```
User: "Define the term atonement"

Claude calls: get_key_terms(term="atonement")

Returns: FIA Key Terms definition with biblical usage, cross-references,
and translation guidance.
```

### Graph Knowledge (Theographic Bible Metadata)

#### 11. `explore_genealogy`

Trace family relationships (ancestors or descendants) for a biblical person using genealogical data for 1,100+ persons.

**What it returns**: Family tree with generation numbers and relationship types, immediate family (spouse, siblings), Mermaid diagram.

**Example**:
```
User: "Show me the family tree of David"

Claude calls: explore_genealogy(person="David", direction="both", generations=5)

Returns: Ancestor chain (Jesse → Obed → Boaz...), descendants,
spouse(s), siblings, Mermaid flowchart diagram.
```

#### 12. `explore_person_events`

Find all events a biblical person participated in, in chronological order.

**What it returns**: Timeline of a person's life events with locations and approximate dates, Mermaid timeline diagram.

#### 13. `explore_place`

Explore the biblical history of a geographic location.

**What it returns**: Events at the location, people born or who died there, coordinates, Mermaid network diagram.

#### 14. `find_connection`

Find the family relationship path between two biblical people.

**What it returns**: Shortest relationship path through parent, child, sibling, and partner relationships, Mermaid flowchart.

**Example**:
```
User: "How are Ruth and Jesus related?"

Claude calls: find_connection(person1="Ruth", person2="Jesus")

Returns: Ruth → child → Obed → child → Jesse → child → David → ... → Jesus
```

#### 15. `people_in_passage`

Find all people, places, and events mentioned in a Bible passage.

**What it returns**: All entities mentioned in a chapter or verse according to Theographic Bible Metadata.

### Cultural Context

#### 18. `get_ane_context`

Retrieve Ancient Near East cultural and historical context that illuminates biblical passages. Covers 12 dimensions of ANE life across 9 time periods.

**When Claude uses it**: User asks about cultural background, customs, practices, or worldview behind a passage; when understanding the original context would prevent modern misreadings.

**What it returns**: Structured entries with title, summary, detailed explanation, ANE parallels from extra-biblical sources, interpretive significance, key references, and scholarly sources.

**Dimensions**: Cosmology & Worldview, Religious Practices, Social Structure, Legal & Covenant, Political & Imperial, Economic Life, Literary Conventions, Warfare & Military, Daily Life & Material Culture, Death & Afterlife, Gender & Family, Education & Literacy.

**Periods**: Patriarchal, Exodus/Conquest, Judges/Early Monarchy, United Monarchy, Divided Monarchy, Assyrian/Babylonian, Persian, Hellenistic, Roman.

**Example**:
```
User: "What's the cultural background behind Genesis 15 - the covenant ceremony?"

Claude calls: get_ane_context(reference="Genesis 15:1", dimension="legal_covenant")

Returns:
- Suzerainty Treaty Forms: ANE covenant structure (preamble, stipulations,
  witnesses, curses/blessings) parallels Deuteronomy and Genesis 15
- Self-Maledictory Oath: Walking between animal halves = "may I become
  like these animals if I break this covenant"
- ANE Parallels: Hittite suzerainty treaties, Mari covenant rituals
- Interpretive Significance: God alone passes through the pieces,
  taking the covenant curse entirely upon himself
```

### Hybrid Search

#### 16. `graph_enriched_search`

Combine passage lookup with graph context for the most comprehensive single-query view of a verse.

**What it returns**: Verse text (English + original), all people/places/events mentioned, family relationships for each person mentioned.

#### 17. `find_similar_passages`

Discover semantically similar passages across the Bible using vector embeddings.

**When Claude uses it**: User wants to find thematic connections not captured by explicit cross-references, or asks "What passages are similar to X?"

**What it returns**: Similar passages ranked by semantic similarity (%), genre warnings, hermeneutical cautions.

**Important**: Semantic similarity indicates shared vocabulary and concepts, but does NOT establish theological connection. The tool includes warnings to verify genre compatibility, authorial intent, and historical context.

**Example**:
```
User: "Find passages similar to Daniel 7:7"

Claude calls: find_similar_passages(reference="Daniel 7:7", limit=5)

Returns:
- Daniel 7:15-28 (70.0% similar) - interpretation of the vision
- Revelation 9:17-21 (61.1% similar) - locusts with lion's teeth
- Daniel 2:29-45 (60.8% similar) - Nebuchadnezzar's statue
```

### Theological Scholarship & Structure

#### `get_theology_context`

Retrieve attributed theological scholarship by biblical reference, theme, or author.

#### `get_torah_weave`

Find structurally paired Torah passages under Moshe Kline's Woven Torah hypothesis.

#### `get_textual_variant`

Inspect catalogued MT/LXX/DSS divergences without collapsing sources and
conclusions. Each reading lists only the manuscripts that witness it. New
Testament quotations appear under **NT citation evidence**, and material that
bears on a text form without witnessing the verse (such as a Qumran scroll
attesting a short edition elsewhere in Jeremiah) appears under **Indirect
evidence**. Corpora with no surviving copy are listed in a case-level **Not
preserved in** note. Every witness keeps the dataset's raw support label.

**Critical judgments** contain only conclusions that carry a source citation.
Uncited dataset summaries appear separately as an **Unsourced dataset summary
(not verified against published text-critical scholarship)**. Theological
interpretations, named-author claims, translation decisions, and NT quotation
alignment also stay in their own sections, and sections with nothing
catalogued are omitted. Verses where the witnesses agree with the MT but the
reading or rendering is contested (for example the divine-council language of
Psalm 82:6) appear as **Translation and interpretation notes**, never as
variants. `lookup_verse` mentions when a verse has a catalogued variant case or
interpretation notes. On a database that still has the legacy
variant schema, the tool asks you to run `python scripts/upgrade_database.py`.

### Further Research

#### `list_research_sources`

List curated, freely accessible research repositories to consult before a general web search: primary-text libraries (Sefaria, CCEL, Perseus, the Internet Archive), open-access journals (Tyndale Bulletin, Themelios, the Journal of Hebrew Scriptures, HTS), Dead Sea Scrolls and Septuagint resources, and Heiser's own sites. Each entry states its coverage, perspective (Jewish, Catholic, Reformed, evangelical, academic/critical, multi-tradition, single-author) and access or licence terms. Filter by `topic` (coverage tag or name, matched loosely) and `perspective`; pass `query` to get a ready-to-open search link for every source that supports one. The list is a set of places to look, not endorsements.

The catalogue lives in [`src/study_bible_mcp/research_sources.json`](src/study_bible_mcp/research_sources.json). It is a directory of repositories, not a per-passage or per-scholar index.

**Checking links.** `python scripts/check_links.py` fetches, over the network, every catalogue URL, every search template filled with a sample query, and (when `db/study_bible.db` or `--db` is present) every distinct `theology_content.url` in the database. It makes about 100 requests to third-party sites, so run it occasionally rather than in CI. Checks run with bounded concurrency and a 20-second timeout; a link that times out is retried once with a 60-second limit, because some hosts are slow rather than dead. Any link answering with status 400 or above, or failing at the network level, is reported as `BROKEN` with where it came from; one that still times out after the retry is reported as `TIMEOUT`. Either makes the run exit non-zero. Hosts known to be slow but working are listed in `LINK_CHECK_SLOW_HOSTS` in the script (currently `drmsh.com`, which has taken 31-57 seconds to answer): their retry gets a 180-second limit, and a timeout that still persists is reported as `SLOW`, a warning that does not fail the run. A real error status from those hosts still does. Some sites refuse `HEAD` requests, so the checker falls back to `GET`. Some answer every automated client with a bot challenge; only for those, an entry may set `"link_check": "skip"` with a `"link_check_reason"`, and the checker lists it as skipped rather than checking it. Verify skipped entries by hand when updating `last_verified`.

---

## How Users Interact

### Natural Language Queries

Users don't need to know the tool names. They just ask questions:

| User Question | Claude Uses |
|--------------|-------------|
| "What does John 3:16 say in Greek?" | `lookup_verse` |
| "What's the Greek word for love?" | `search_lexicon` |
| "Study the word 'agape'" | `word_study` |
| "Who was Abraham?" | `lookup_name` |
| "What other passages talk about grace?" | `get_cross_references` |
| "Parse V-AAI-3S" | `parse_morphology` |
| "Where else does G26 appear?" | `search_by_strongs` |
| "What do the study notes say about Romans 8:28?" | `get_study_notes` |
| "Look up 'covenant' in the Bible dictionary" | `get_bible_dictionary` |
| "Define the key term 'atonement'" | `get_key_terms` |
| "Show me David's family tree" | `explore_genealogy` |
| "What events happened in Moses' life?" | `explore_person_events` |
| "What's the history of Bethlehem?" | `explore_place` |
| "How are Ruth and Jesus related?" | `find_connection` |
| "Who are the people in Romans 8?" | `people_in_passage` |
| "Give me everything about Genesis 22:1" | `graph_enriched_search` |
| "Find passages similar to Daniel 7" | `find_similar_passages` |
| "What's the cultural context of Genesis 15?" | `get_ane_context` |

### Example Conversation

**User**: "I'm studying Romans 5:8. What does Paul mean when he says God 'demonstrates' his love?"

**Claude's internal process**:
1. Look up the verse: `lookup_verse(reference="Romans 5:8")`
2. Study the key word: `word_study(word="demonstrates")` → finds G4921 συνίστημι
3. Get study notes: `get_study_notes(reference="Romans 5:8")`
4. Check cross-references for context
5. Apply genre guidance (Epistles)

**Claude's response**:
> In Romans 5:8, Paul uses the Greek word **συνίστημι** (synistēmi, G4921), which means "to stand together, to commend, to demonstrate." This is a present tense verb, indicating ongoing action.
>
> The genre context is important here: Romans is an epistle, and Paul is building an argument. In the immediate context (Romans 5:1-11), he's explaining how we have peace with God through justification by faith. Verse 8 is his proof: God didn't wait for us to become worthy, but demonstrated his love "while we were still sinners."
>
> The word "demonstrates" carries the sense of proving beyond doubt - not just telling us about his love, but showing it through action (Christ's death).
>
> Related passages on God's love demonstrated through Christ: John 3:16, 1 John 4:9-10.

---

## Example Questions

Try asking Claude:

```
What does John 3:16 say in Greek? Break down the key words.
```

```
Study the word 'agape' - how is it different from other Greek words for love?
```

```
What's the context of Romans 8:28? Who is Paul writing to and why?
```

```
Show me cross-references for Ephesians 2:8-9 on salvation by grace.
```

```
Who was Melchizedek and why is he significant?
```

```
Parse the verb morphology in Philippians 2:12 - "work out your salvation"
```

```
What does the Hebrew word 'hesed' mean? Where is it used?
```

```
Help me understand Revelation 13 - what are these beasts?
```

```
What do the study notes say about John 1:1?
```

```
Look up 'baptism' in the Bible dictionary.
```

```
Show me David's family tree going back 5 generations.
```

```
How are Abraham and Jesus connected genealogically?
```

```
What events happened in the life of Moses?
```

```
Find passages similar to John 3:16 - what other verses talk about God's love like this?
```

```
What Old Testament passages connect to Daniel's vision of the Son of Man?
```

```
What's the Ancient Near East background for the creation account in Genesis 1?
```

```
Explain the cultural context of covenant-making in Genesis 15.
```

---

## Hermeneutical Framework

This isn't just a reference tool. It's designed to guide users toward sound biblical interpretation.

### The Problem It Solves

Common interpretation errors include:
- **Proof-texting**: Using isolated verses to support predetermined conclusions
- **Allegorizing**: Finding hidden meanings not intended by the author
- **Ignoring genre**: Reading poetry as prose or prophecy as history
- **Ignoring context**: Ripping verses from their historical and literary setting
- **Moralizing**: Reducing narratives to "be good like David"

### The Fee & Stuart Method

The interpretive framework is based on **"How to Read the Bible for All Its Worth"** by Gordon Fee and Douglas Stuart - the standard textbook for biblical hermeneutics used in seminaries worldwide.

**About the authors:**
- **Gordon Fee** (1934-2022): New Testament scholar, professor at Regent College, author of major commentaries on 1 Corinthians, Philippians, and Pauline theology. One of the translators of the NIV and TNIV.
- **Douglas Stuart**: Old Testament scholar, professor at Gordon-Conwell Theological Seminary, author of commentaries on Hosea-Jonah, Exodus, and Old Testament hermeneutics.

Their book (first published 1981, now in its 4th edition) has sold over a million copies and is used as the introductory hermeneutics text at most evangelical seminaries. It teaches readers to interpret Scripture according to its literary genre, historical context, and authorial intent - avoiding both wooden literalism and uncontrolled allegorizing.

The server embeds genre-specific interpretation principles from this methodology:

#### Core Principles

1. **Exegesis Before Application**
   - First discover what the text meant to its original audience
   - Then determine what it means for us today
   - Never jump directly to application

2. **Context is King**
   - Historical context: time, culture, author, audience, occasion
   - Literary context: genre, surrounding passages, book structure
   - A text without context is a pretext for a proof text

3. **Genre Determines Method**
   Different biblical literature requires different approaches

### Genre-Specific Guidelines

#### Epistles (Letters)
**Key principle**: Think contextually - what problem was being addressed?

- Read the entire letter to understand the argument flow
- Ask: What problem prompted this letter?
- Pay attention to logical connectors (therefore, because, so that)
- Distinguish between central argument and supporting points
- Not every statement is universally prescriptive

**Common errors**:
- Taking verses out of their argumentative context
- Ignoring the specific historical situation being addressed
- Treating every instruction as a timeless command

#### Old Testament Narratives
**Key principle**: Three levels (meta, national, individual); descriptive not prescriptive

- Narratives describe what happened, not necessarily what should happen
- Three levels: God's universal plan, Israel's story, individual accounts
- Characters are not always examples to follow - observe their flaws
- The narrator rarely makes direct theological statements
- God is the ultimate hero of every narrative

**Common errors**:
- Treating every character's action as a model to follow
- Allegorizing details that are simply historical facts
- Moralizing: "Be brave like David" without seeing God's work

#### Gospels
**Key principle**: Two-level documents (Jesus' original context + evangelist's purpose)

- Consider both Jesus' original meaning and the Gospel writer's purpose
- Each Gospel has a specific audience and theological emphasis
- Account for the already/not-yet tension of the Kingdom
- Compare parallel accounts to see each writer's emphasis

**Common errors**:
- Harmonizing too quickly without hearing each Gospel's voice
- Ignoring Jesus' audience (Pharisees, disciples, crowds)
- Applying teachings directly without considering the cross

#### Parables
**Key principle**: Find the main point; don't allegorize every detail

- Identify the one or two main points - parables are not allegories
- Consider the audience: Who is Jesus speaking to and why?
- Look for cultural background that illuminates meaning
- The unexpected twist often carries the main message

**Common errors**:
- Allegorizing every detail (the donkey represents X...)
- Missing the shock value for the original audience
- Creating theological systems from parabolic details

#### Prophets
**Key principle**: Covenant enforcement; check if "future" is now past

- Prophets were covenant enforcement officers - calling Israel back
- Most "predictions" were about events now in our past
- The prophetic lawsuit pattern: accusation, judgment, hope
- Distinguish near fulfillment from ultimate/eschatological fulfillment
- Poetry and metaphor are the normal mode of prophetic speech

**Common errors**:
- Reading all prophecy as about the end times
- Literalizing poetic and metaphorical language
- Creating detailed end-times timelines from prophetic poetry

#### Psalms
**Key principle**: Poetry/prayer; understand the types (lament, thanksgiving, praise)

- Psalms are inspired responses to God - poetry, not doctrine
- Identify the type: Lament, Thanksgiving, Praise, Royal, Wisdom
- Poetry uses metaphor, hyperbole, and parallelism
- The emotions are real and God-given - even the difficult ones
- Many psalms find their ultimate fulfillment in Christ

**Common errors**:
- Treating poetic expressions as doctrinal statements
- Ignoring the emotional dimension
- Literalizing metaphorical language

#### Wisdom Literature
**Key principle**: General truths, not guarantees; compare with full canon

- Proverbs are general truths, not unconditional promises
- Wisdom literature wrestles with life's complexity
- Job and Ecclesiastes challenge simplistic interpretations
- The fear of the Lord is the foundation of all wisdom
- Compare individual proverbs with the full biblical witness

**Common errors**:
- Treating Proverbs as unconditional promises
- Ignoring the dialogue format in Job (not all speeches are true)
- Missing the "under the sun" perspective in Ecclesiastes

#### Apocalyptic (Revelation)
**Key principle**: Apocalyptic imagery; already/not yet eschatology

- Apocalyptic is a literary genre with its own conventions
- Symbols are stock imagery (beasts, numbers) with recognized meanings
- The primary message is: God wins, evil is judged, Christ reigns
- Read in light of OT prophets and the already/not yet tension
- Multiple valid interpretive approaches exist

**Common errors**:
- Literalizing symbolic imagery (666 as a barcode)
- Creating detailed chronological timelines
- Missing the pastoral purpose: encouragement for suffering believers

### The Reasoning Pattern

The server's hermeneutics module guides Claude through this sequence:

1. **IDENTIFY**: What biblical text(s) are relevant?
2. **GENRE**: What type of literature is this?
3. **CONTEXT**: Historical, literary, canonical
4. **CONTENT**: What does the text say? (Greek/Hebrew when helpful)
5. **CROSS-REFERENCES**: Scripture interprets Scripture
6. **APPLICATION**: Timeless principle behind temporal commands
7. **HUMILITY**: Acknowledge uncertainty where it exists

---

## Self-Hosting

Want to run your own instance? See [docs/SELF_HOST.md](docs/SELF_HOST.md).

Options:
- Local Python development
- Docker deployment
- Your own Fly.io instance

---

## Project Structure

```
studybible-mcp/
├── src/study_bible_mcp/
│   ├── server.py              # MCP server (stdio, SSE, and Streamable HTTP)
│   ├── database.py            # SQLite queries (async)
│   ├── tools.py               # MCP tool definitions and output formatters
│   ├── research_sources.json  # Curated open research repositories (list_research_sources)
│   ├── hermeneutics.py        # Genre detection & interpretation
│   └── parsers/
│       ├── lexicon.py         # TFLSJ, BDB, Abbott-Smith, TBESG, TBESH parsers
│       ├── aquifer.py         # BibleAquifer JSON parser
│       ├── acai.py            # ACAI entity annotation parser
│       ├── ane_context.py     # ANE cultural context parser
│       ├── biblical_versions.py # MT/LXX text, morphology, and versification
│       ├── ancient_sources.py # Josephus TEI parser and corpus metadata
│       ├── tagged_text.py     # TAGNT/TAHOT morphology parsers
│       └── proper_names.py    # TIPNR name parser
├── scripts/
│   ├── download_stepbible.py  # Download base source data (--aquifer flag)
│   ├── download_biblical_versions.py # Download pinned LXX/Brenton sources
│   ├── download_ancient_sources.py # Download pinned Josephus sources
│   ├── build_database.py      # Build SQLite database
│   ├── generate_embeddings.py # Generate vector embeddings
│   ├── import_theographic.py  # Import Theographic graph data
│   ├── upgrade_database.py    # In-place schema/source upgrade of an existing DB
│   ├── smoke_server.py        # Full-database smoke suite
│   └── check_links.py         # Checks research-source and theology URLs (network)
├── tests/                     # Deterministic unit and tool-selection tests
├── prompts/
│   └── system_prompt.md       # Full hermeneutical framework for agents
├── docs/
│   ├── SETUP.md               # Quick setup guide
│   └── SELF_HOST.md           # Self-hosting instructions
├── ARCHITECTURE.md            # Mermaid flowchart of the tool-selection paths
├── Dockerfile                 # Runtime image; database mounted separately
├── fly.toml                   # Fly.io deployment config
└── pyproject.toml
```

---

## Data Sources

### STEPBible - Tyndale House, Cambridge

Biblical text and brief lexicon data come from the [STEPBible project](https://www.stepbible.org/) ([GitHub](https://github.com/STEPBible/STEPBible-Data)), developed by scholars at **Tyndale House, Cambridge** - one of the world's leading centres for biblical research. Licensed CC BY 4.0.

| File | Description | Content |
|------|-------------|---------|
| **TFLSJ** | Full Liddell-Scott-Jones Greek Lexicon | 10,846 Greek words with full scholarly definitions |
| **Abbott-Smith** | Manual Greek Lexicon of the NT (TEI XML) | 5,896 NT-focused entries with LXX cross-refs and synonym discussions |
| **TBESG** | Tyndale Brief Lexicon - Greek (fallback) | 5,600+ Greek words with brief definitions |
| **TBESH** | Tyndale Brief Lexicon - Hebrew (fallback) | 8,600+ Hebrew words with brief definitions |
| **TAGNT** | Translators Amalgamated Greek NT (2 parts) | Every word of the Greek NT with morphology, Strong's numbers, glosses |
| **TAHOT** | Translators Amalgamated Hebrew OT (4 parts) | Every word of the Hebrew OT with morphology, Strong's numbers, glosses |
| **TIPNR** | Translators Proper Names | 4,299 biblical people, places, and things with references |
| **TEGMC/TEHMC** | Morphology Codes | Grammatical parsing code definitions |

### Septuagint and MT versification

The LXX comparison corpus uses the complete 59-book
[OpenScriptorium `lxx-morph`](https://github.com/OpenScriptorium/lxx-morph)
Rahlfs morphology dataset, pinned to commit
`c91f6b1e8fb3ba37df701e6ae31f675ace71a2b2`. Its explicit
`verse_pairs.jsonl` mapping resolves Psalm numbering, Jeremiah's chapter order,
2 Esdras, and smaller MT/LXX shifts. That mapping is derived in part from
[TVTMS](https://github.com/STEPBible/STEPBible-Data) (Tyndale Versification
Traditions Mapping System), CC BY 4.0, created by STEPBible.org / Tyndale House
Cambridge. Downloads are checked against the pinned
Git blob hashes. Morphology is CC BY 4.0; the underlying Rahlfs (1935) Greek
text is public domain. Only the LXX rows are stored (about 35 MB including
indexes, with word morphology zlib-compressed); MT rows are read from the
existing TAHOT `verses` table at query time.

English LXX translations come from the public-domain
[Brenton Septuagint at eBible.org](https://ebible.org/details.php?id=eng-Brenton),
and Brenton's own public-domain Greek text from
[eBible's grcbrent](https://ebible.org/details.php?id=grcbrent)
(`data/lxx/brenton-greek`). eBible regenerates its unversioned zips, so the
download script verifies the SHA-256 of every extracted USFM book rather than of
the archive, and never deletes or overwrites local files that fail verification.
Brenton's Greek is stored only for the verses where it differs from Rahlfs
(about 5 MB). `build_database.py` stops with an error if `data/lxx` is present
but incomplete (any of the 59 morphology books, the mapping, a required Brenton
English or Greek book, or a manifest-listed file is missing or truncated).

### Josephus

`search_ancient_sources` uses all four Josephus works from
[PerseusDL canonical-greekLit](https://github.com/PerseusDL/canonical-greekLit),
pinned to commit `01b725d835e6e733062ffd79e0efdbae1ba06e5c`. The English TEI
has one division per Whiston section, labelled with the Niese section where it
starts; the Greek TEI has one division per Niese section. The importer joins
every Greek section from each English start up to the next (the last section
of a book runs to the book's last Greek section), so no Niese Greek is dropped;
the later Greek book summaries (`arg`) are excluded. One mislabelled English
division (Whiston 17.13.1, labelled `13`) is corrected to Niese 17.339 from the
Greek milestone and text. Editor notes and Whiston's chapter headings are kept
out of the primary-source text and the search index; headings are stored as
editorial metadata. The FTS5 index uses Porter stemming for English and an
accent-folded copy of the Greek. Each TEI file declares CC BY-SA 4.0; downloads
are checked against their pinned Git blob hashes, and the build fails if any of
the eight TEI files is missing.

Biblical links are a small, separate editorial index of direct narrative
overlap. Each targets a Niese section, attaches to the passage whose span
contains it, and was checked against the passage text; the import fails if a
link does not resolve. They do not assert literary dependence or historical
agreement, and the Testimonium Flavianum link is marked as of disputed
authenticity.

### BDB Hebrew Lexicon

The full unabridged Brown-Driver-Briggs Hebrew lexicon (8,090 entries) comes from [eliranwong/unabridged-BDB-Hebrew-lexicon](https://github.com/eliranwong/unabridged-BDB-Hebrew-lexicon). The BDB is the standard scholarly Hebrew-English lexicon, originally published in 1906 and still widely used in academic study. Public domain text.

### Abbott-Smith Greek Lexicon

G. Abbott-Smith's *A Manual Greek Lexicon of the New Testament* (1922) provides NT-focused definitions that complement the broader classical coverage of LSJ. The TEI XML edition (5,896 entries) comes from [translatable-exegetical-tools/Abbott-Smith](https://github.com/translatable-exegetical-tools/Abbott-Smith). Public domain text.

Abbott-Smith enriches 5,426 existing Greek entries with:

| Field | Description | Coverage |
|-------|-------------|----------|
| **NT-focused definition** | Full definition with sense hierarchy | 5,871 entries |
| **NT occurrence count** | Word frequency in the New Testament | 5,480 entries |
| **LXX/Hebrew equivalents** | Hebrew words the Greek translates in the Septuagint | 3,317 entries |
| **Synonym discussions** | Scholarly notes distinguishing related Greek words | 398 entries |

### BibleAquifer

Scholarly commentary and reference content from [BibleAquifer](https://github.com/BibleAquifer) (CC BY-SA 4.0):

| Resource | Description | Content |
|----------|-------------|---------|
| **Aquifer Open Study Notes** | Verse-level scholarly commentary | 66 books |
| **Tyndale Bible Dictionary** | Topical articles | 500+ articles on people, places, theology, history, archaeology |
| **UW Translation Notes** | unfoldingWord translator commentary | Linguistic insights for 49+ books |
| **SIL Translator Notes** | SIL International translator notes | Translation and cultural context |
| **FIA Key Terms** | Key theological terms | 200+ carefully defined terms with cross-references |

### ACAI Entity Annotations

Rich entity annotations from [BibleAquifer/ACAI](https://github.com/BibleAquifer/ACAI) (CC BY-SA 4.0):

| Type | Count | Content |
|------|-------|---------|
| People | ~2,500 | Family relationships, variant names, roles, speech attributions, verse references |
| Places | ~400 | Geographic entities with biblical references |
| Groups | ~200 | People groups, nations, tribes |
| Key Terms | ~75 | Annotated theological concepts |

### Theographic Bible Metadata

Graph data for genealogy, events, and places from [Theographic](https://github.com/robertrouse/theographic-bible-metadata). Used by the `explore_genealogy`, `explore_person_events`, `explore_place`, `find_connection`, `people_in_passage`, and `graph_enriched_search` tools.

### Ancient Near East Context

87 structured entries covering 12 dimensions of ANE cultural and historical context across 9 time periods, with 314 book-chapter mappings. Data is stored in [`data/ane_context/`](data/ane_context/) as JSON files (one per dimension). Sources include Walton, Hallo, Matthews & Benjamin, Pritchard (ANET), and other standard ANE reference works.

### Theological Scholarship

193 verse-anchored entries covering Heiser, Bradley, Burnett, Owen, Stott, and Lennox, served by `get_theology_context`.

These entries are **original summary prose written for this database**, describing each author's argument on a passage or theme with attribution. They are not reproduced text from the authors' works. The material was derived from publicly available research and teaching — papers, articles, lectures, and podcasts — rather than from in-copyright books; where a specific public source is known, the entry carries its URL and the tool output shows it. Every result from `get_theology_context` states this provenance inline.

John Owen (d. 1683) is in the public domain, so those entries are cited directly by work.

#### Source links

An entry's `url` is shown as **Source URL** in `get_theology_context` output. Links are added only where the source itself is legitimately free online:

| Author | Link target |
|---|---|
| Owen | Free public-domain text: the [CCEL](https://ccel.org/ccel/owen) chapter or part the entry draws on (Communion with God, The Death of Death, The Glory of Christ, Justification, Mortification, Indwelling Sin); for the Exposition of Hebrews, which CCEL lacks, the Monergism PDF of the volume covering that chapter |
| Heiser | His papers on thedivinecouncil.com / drmsh.com / Liberty Digital Commons, and Naked Bible podcast transcripts |
| Burnett | His own serialisation of the argument on drmsh.com (based on his SBL paper); the JSPL article itself is not openly hosted |
| Bradley, Stott, Lennox | None: no free copy hosted by the author or publisher |

In the content JSON, a file-level `url` applies to every entry; an entry-level `url` (for example a chapter page) overrides it.

#### Applying data changes to an existing database

The importers are re-runnable. A row that already exists (same `source_work`, `chapter_or_episode`, `title`) is not duplicated and keeps its content; only its `url` is refreshed. To apply new or corrected links to an existing DB:

```bash
DB=db/study_bible.db
python scripts/relabel_theology_sources.py $DB      # no-op if already relabelled
python scripts/import_heiser_content.py $DB
python scripts/import_bradley_content.py $DB
python scripts/ingest_reformed_evangelical.py $DB    # Owen, Stott, Lennox
python scripts/ingest_burnett_gage.py --theology-only $DB
python scripts/dedupe_theology_theme_links.py $DB   # no-op once clean
```

The relabel step must come first on a DB built before the descriptive labels: the data files now use those labels as `source_work`, so an unrelabelled DB would not match and would gain duplicate rows. The dedupe step removes theme links that earlier importer runs duplicated (their NULL `reference` slipped past the UNIQUE constraint), which inflated theme entry counts.

### Ancient Near East Context

The 87 ANE entries are likewise original summary prose describing scholarly consensus on ANE background, with the standard reference works named as sources rather than quoted.

### Vector Embeddings

Semantic search uses OpenAI's `text-embedding-3-small` model via [sqlite-vec](https://github.com/asg017/sqlite-vec) for the `find_similar_passages` tool.

---

## Contributing

Contributions welcome! Especially:

- Additional thematic cross-references
- Improved genre detection
- New translation support
- Better morphology parsing
- Documentation improvements

---

## License

MIT License. See [LICENSE](LICENSE).

Data from STEPBible is licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
OpenScriptorium LXX morphology and MT/LXX verse mappings (derived in part from STEPBible's TVTMS) are licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/); the Rahlfs Greek text and Brenton's English translation and Greek text are public domain.
The Perseus Josephus Greek and English TEI editions are licensed under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
Data from BibleAquifer and ACAI is licensed under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
Torah Weave data from Moshe Kline ([chaver.com](https://www.chaver.com/)) is licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
BDB, Abbott-Smith, the Treasury of Scripture Knowledge, and the works of John Owen are public domain.
The theology and ANE entries are original summary prose written for this project — see [Data Sources](#data-sources).

---

## Acknowledgments

- [STEPBible](https://www.stepbible.org/) for the freely available biblical data
- [OpenScriptorium](https://github.com/OpenScriptorium/lxx-morph) for Rahlfs LXX morphology and explicit MT/LXX verse mappings
- [STEPBible.org / Tyndale House Cambridge](https://github.com/STEPBible/STEPBible-Data) for TVTMS, the versification data behind those mappings
- [eBible.org](https://ebible.org/details.php?id=eng-Brenton) for the public-domain Brenton Septuagint, English and [Greek](https://ebible.org/details.php?id=grcbrent)
- [Perseus Digital Library](https://github.com/PerseusDL/canonical-greekLit) for the licensed Josephus Greek and English editions
- [BibleAquifer](https://github.com/BibleAquifer) for study notes, dictionary, translation notes, and key terms
- [eliranwong](https://github.com/eliranwong/unabridged-BDB-Hebrew-lexicon) for the unabridged BDB Hebrew lexicon
- [translatable-exegetical-tools](https://github.com/translatable-exegetical-tools/Abbott-Smith) for the Abbott-Smith Greek Lexicon TEI XML edition
- [Theographic](https://github.com/robertrouse/theographic-bible-metadata) for genealogy and event graph data
- Gordon Fee & Douglas Stuart for the hermeneutical framework in "How to Read the Bible for All Its Worth"
- The MCP community for the protocol and tooling
