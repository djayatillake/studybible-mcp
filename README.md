# Study Bible MCP Server

A Bible study assistant for Claude that provides full scholarly lexicons (LSJ Greek, BDB Hebrew), morphologically-tagged biblical texts, cross-references, Theographic genealogy graphs, Tyndale study notes, a Bible dictionary, key theological terms, and hermeneutical methodology based on Fee & Stuart's "How to Read the Bible for All Its Worth".

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
│  ┌───────────────┐  │ SSE │  ┌─────────────┐  ┌───────────────────┐  │
│  │ User asks a   │──┼─────┼─▶│ MCP Server  │─▶│ SQLite DB (355MB) │  │
│  │ Bible question│  │     │  │ (Python)    │  │                   │  │
│  └───────────────┘  │     │  └─────────────┘  │ • Lexicons (LSJ,  │  │
│                     │     │        │          │   BDB, Extended    │  │
│  ┌───────────────┐  │     │        ▼          │   Strong's)       │  │
│  │ Claude uses   │◀─┼─────┼── Tool Results    │ • Tagged NT + OT  │  │
│  │ 17 tools to   │  │     │                   │ • Names + ACAI    │  │
│  │ look up data  │  │     │                   │ • Morphology      │  │
│  └───────────────┘  │     │                   │ • Study Notes     │  │
│                     │     │                   │ • Bible Dictionary │  │
│                     │     │                   │ • Key Terms        │  │
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

See [ARCHITECTURE.md](ARCHITECTURE.md) for a full Mermaid flowchart of all 17 tools and how the agent chains them together.

### The Database

The server includes a pre-built SQLite database (~355MB) containing:

| Table | Rows | Content |
|-------|------|---------|
| `lexicon` | 18,936 | Greek (Full LSJ) and Hebrew (Full BDB) word definitions with Strong's numbers |
| `verses` | 31,280 | Every verse of the Bible with morphology tags |
| `passages` | 5,290 | Verses grouped by ancient section markers |
| `names` | 4,299 | Biblical people, places, and things |
| `morphology` | 2,768 | Grammatical parsing code definitions |
| `thematic_references` | 22 | Core theological theme cross-references |
| `aquifer_content` | 102,673 | Study notes, dictionary articles, translation notes, key terms |
| `acai_entities` | 3,175 | Rich entity annotations (people, places, groups, key terms) |
| `verse_vectors` | 31,280 | OpenAI embeddings for semantic search |
| `passage_vectors` | 5,190 | OpenAI embeddings for passage similarity |

---

## Available Tools (17)

### Core Text & Language

#### 1. `lookup_verse`

Retrieve a verse with its original language text and word-by-word analysis.

**When Claude uses it**: User asks about a specific verse, wants to see the Greek or Hebrew text, or asks about specific words in a passage.

**What it returns**: English translation, original Greek/Hebrew text, word-by-word breakdown with Strong's numbers, morphological parsing, genre-specific interpretation guidance.

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

#### 2. `word_study`

Deep dive into a Greek or Hebrew word's meaning, usage, and etymology. Greek entries include the full Liddell-Scott-Jones (LSJ) definition; Hebrew entries include the full Brown-Driver-Briggs (BDB) definition.

**When Claude uses it**: User asks about the meaning of a Greek/Hebrew word, wants to understand different translations of a term, or asks about theological concepts (love, faith, grace).

**What it returns**: Original word in Greek/Hebrew script, transliteration, Strong's number, brief definition, full LSJ or BDB scholarly definition, etymology, usage count, semantic range, related words, example passages.

**Example**:
```
User: "What does 'agape' mean in Greek?"

Claude calls: word_study(strongs="G26")

Returns:
- ἀγάπη (agapē, G26)
- Brief Definition: "love, goodwill, benevolence"
- Full LSJ Definition: [scholarly entry with classical and biblical usage]
- Related words: ἀγαπάω (to love), ἀγαπητός (beloved)
- Example passages showing usage
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

**What it returns**: Combined commentary from three sources: Tyndale Study Notes (66 books of concise verse-level scholarly commentary), unfoldingWord Translation Notes (translator-focused linguistic insights), and SIL Translator Notes (additional translation and cultural context).

**Example**:
```
User: "What do the study notes say about John 3:16?"

Claude calls: get_study_notes(reference="John 3:16")

Returns:
- Tyndale Study Notes: [verse commentary]
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
│   ├── server.py              # MCP server (stdio + SSE transports)
│   ├── database.py            # SQLite queries (async)
│   ├── tools.py               # 17 tool definitions
│   ├── hermeneutics.py        # Genre detection & interpretation
│   └── parsers/
│       ├── lexicon.py         # TFLSJ, BDB, TBESG, TBESH parsers
│       ├── aquifer.py         # BibleAquifer JSON parser
│       ├── acai.py            # ACAI entity annotation parser
│       ├── tagged_text.py     # TAGNT/TAHOT morphology parsers
│       └── proper_names.py    # TIPNR name parser
├── scripts/
│   ├── download_stepbible.py  # Download all source data (--aquifer flag)
│   ├── build_database.py      # Build SQLite database
│   ├── generate_embeddings.py # Generate vector embeddings
│   ├── import_theographic.py  # Import Theographic graph data
│   └── test_server.py         # Manual test suite
├── tests/
│   └── test_tool_selection.py # Pytest: agent tool selection (71 tests)
├── prompts/
│   └── system_prompt.md       # Full hermeneutical framework for agents
├── docs/
│   ├── SETUP.md               # Quick setup guide
│   └── SELF_HOST.md           # Self-hosting instructions
├── ARCHITECTURE.md            # Mermaid flowchart of all 17 tools
├── Dockerfile                 # Multi-stage build with database
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
| **TBESG** | Tyndale Brief Lexicon - Greek (fallback) | 5,600+ Greek words with brief definitions |
| **TBESH** | Tyndale Brief Lexicon - Hebrew (fallback) | 8,600+ Hebrew words with brief definitions |
| **TAGNT** | Translators Amalgamated Greek NT (2 parts) | Every word of the Greek NT with morphology, Strong's numbers, glosses |
| **TAHOT** | Translators Amalgamated Hebrew OT (4 parts) | Every word of the Hebrew OT with morphology, Strong's numbers, glosses |
| **TIPNR** | Translators Proper Names | 4,299 biblical people, places, and things with references |
| **TEGMC/TEHMC** | Morphology Codes | Grammatical parsing code definitions |

### BDB Hebrew Lexicon

The full unabridged Brown-Driver-Briggs Hebrew lexicon (8,090 entries) comes from [eliranwong/unabridged-BDB-Hebrew-lexicon](https://github.com/eliranwong/unabridged-BDB-Hebrew-lexicon). The BDB is the standard scholarly Hebrew-English lexicon, originally published in 1906 and still widely used in academic study. Public domain text.

### BibleAquifer

Scholarly commentary and reference content from [BibleAquifer](https://github.com/BibleAquifer) (CC BY-SA 4.0):

| Resource | Description | Content |
|----------|-------------|---------|
| **Tyndale Study Notes** | Verse-level scholarly commentary | 66 books |
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
Data from BibleAquifer and ACAI is licensed under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).

---

## Acknowledgments

- [STEPBible](https://www.stepbible.org/) for the freely available biblical data
- [BibleAquifer](https://github.com/BibleAquifer) for study notes, dictionary, translation notes, and key terms
- [eliranwong](https://github.com/eliranwong/unabridged-BDB-Hebrew-lexicon) for the unabridged BDB Hebrew lexicon
- [Theographic](https://github.com/robertrouse/theographic-bible-metadata) for genealogy and event graph data
- Gordon Fee & Douglas Stuart for the hermeneutical framework in "How to Read the Bible for All Its Worth"
- The MCP community for the protocol and tooling
