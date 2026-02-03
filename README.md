# Study Bible MCP Server

A Bible study assistant for Claude that provides Greek/Hebrew lexicons, morphologically-tagged biblical texts, cross-references, and hermeneutical methodology based on Fee & Stuart's "How to Read the Bible for All Its Worth".

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
┌─────────────────────┐     ┌─────────────────────────────────────┐
│   Claude Desktop    │     │   Study Bible MCP Server            │
│   or Claude Code    │     │   (Fly.io)                          │
│                     │     │                                     │
│  ┌───────────────┐  │ SSE │  ┌─────────────┐  ┌──────────────┐  │
│  │ User asks a   │──┼─────┼─▶│ MCP Server  │─▶│ SQLite DB    │  │
│  │ Bible question│  │     │  │ (Python)    │  │ (120MB)      │  │
│  └───────────────┘  │     │  └─────────────┘  │              │  │
│                     │     │        │          │ • Lexicons   │  │
│  ┌───────────────┐  │     │        ▼          │ • Tagged NT  │  │
│  │ Claude uses   │◀─┼─────┼── Tool Results    │ • Tagged OT  │  │
│  │ tools to look │  │     │                   │ • Names      │  │
│  │ up data       │  │     │                   │ • Morphology │  │
│  └───────────────┘  │     │                   └──────────────┘  │
└─────────────────────┘     └─────────────────────────────────────┘
```

When you ask Claude a Bible question:
1. Claude analyzes your question and decides which tools to use
2. Claude calls the appropriate MCP tools (e.g., `lookup_verse`, `word_study`)
3. The server queries the pre-built SQLite database
4. Results are returned to Claude
5. Claude synthesizes the data into a helpful response

### The Database

The server includes a pre-built SQLite database (~120MB) containing:

| Table | Rows | Content |
|-------|------|---------|
| `lexicon` | 20,192 | Greek and Hebrew word definitions with Strong's numbers |
| `verses` | 447,756 | Every word of the Bible with morphology tags |
| `names` | 1,131 | Biblical people, places, and things |
| `morphology` | 2,768 | Grammatical parsing code definitions |
| `thematic_references` | 22 | Core theological theme cross-references |

All data comes from [STEPBible](https://github.com/STEPBible/STEPBible-Data), licensed CC BY 4.0.

---

## Available Tools

### 1. `lookup_verse`

**Purpose**: Retrieve a verse with its original language text and word-by-word analysis.

**When Claude uses it**:
- User asks "What does John 3:16 say?"
- User wants to see the Greek or Hebrew text
- User asks about specific words in a passage

**What it returns**:
- English translation
- Original Greek/Hebrew text
- Word-by-word breakdown with Strong's numbers
- Morphological parsing for each word
- Genre-specific interpretation guidance

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

### 2. `word_study`

**Purpose**: Deep dive into a Greek or Hebrew word's meaning, usage, and etymology.

**When Claude uses it**:
- User asks about the meaning of a Greek/Hebrew word
- User wants to understand different translations of a term
- User asks about theological concepts (love, faith, grace)
- Multiple English translations differ on a key word

**What it returns**:
- Original word in Greek/Hebrew script
- Transliteration and pronunciation
- Strong's number
- Short and full definitions
- Etymology
- Usage count
- Semantic range
- Related words
- Example passages

**Example**:
```
User: "What does 'agape' mean in Greek?"

Claude calls: word_study(strongs="G26")

Returns:
- ἀγάπη (agapē)
- Definition: "Love, goodwill, benevolence"
- Usage: Occurs 116 times
- Related words: ἀγαπάω (to love), ἀγαπητός (beloved)
- Example passages showing usage
```

### 3. `search_lexicon`

**Purpose**: Search across Greek and Hebrew lexicons by English meaning.

**When Claude uses it**:
- User wants to find the Greek/Hebrew word for an English concept
- User asks "How do you say X in Greek?"
- User is exploring related words in a semantic field

**What it returns**:
- List of matching lexicon entries
- Strong's numbers for each
- Brief definitions
- Language (Greek or Hebrew)

**Example**:
```
User: "What are the Greek words for 'love'?"

Claude calls: search_lexicon(query="love", language="greek")

Returns:
- G26 ἀγάπη - divine, unconditional love
- G5368 φιλέω - brotherly, affectionate love
- G2309 θέλω - desire, wish
```

### 4. `get_cross_references`

**Purpose**: Find passages related to a verse or theological theme.

**When Claude uses it**:
- User asks "What other passages talk about X?"
- User wants to see Scripture interpreting Scripture
- User is studying a theological theme

**What it returns**:
- Related passages with brief notes
- Either verse-specific cross-references or thematic collections

**Built-in themes**:
- `salvation_by_grace` - Genesis 15:6, Romans 3:21-26, Ephesians 2:8-9, Titus 3:5-7
- `deity_of_christ` - John 1:1-3, John 8:58, Colossians 2:9, Hebrews 1:3
- `atonement` - Isaiah 53:4-6, Romans 3:25, 2 Corinthians 5:21, 1 Peter 2:24
- `resurrection` - Psalm 16:10, 1 Corinthians 15:3-8, 1 Corinthians 15:20-23
- `holy_spirit` - Joel 2:28-29, John 14:16-17, Romans 8:9-11, Galatians 5:22-23
- `justification` - Romans 3:24-26, Romans 5:1, Galatians 2:16

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

### 5. `lookup_name`

**Purpose**: Get information about biblical people, places, and things.

**When Claude uses it**:
- User asks "Who was X?"
- User wants to know about a place's significance
- User asks about relationships between biblical figures

**What it returns**:
- Original Hebrew/Greek form
- Type (person, place, thing, tribe)
- Description
- Key references
- Relationships (father, mother, children, etc.)

**Example**:
```
User: "Who was Melchizedek?"

Claude calls: lookup_name(name="Melchizedek")

Returns:
- Type: Person
- Description: King of Salem, priest of God Most High
- References: Genesis 14:18, Psalm 110:4, Hebrews 5-7
- Significance in Hebrews' argument about Christ's priesthood
```

### 6. `parse_morphology`

**Purpose**: Explain Greek or Hebrew grammatical parsing codes.

**When Claude uses it**:
- User asks what a morphology code means
- User wants to understand verb tense, mood, voice
- User is studying Greek or Hebrew grammar

**What it returns**:
- Part of speech
- For verbs: person, number, tense, voice, mood
- For nouns: case, number, gender
- Full parsing description

**Example**:
```
User: "What does V-AAI-3S mean?"

Claude calls: parse_morphology(code="V-AAI-3S", language="greek")

Returns:
- Part of Speech: Verb
- Tense: Aorist
- Voice: Active
- Mood: Indicative
- Person: 3rd
- Number: Singular
- Full Parsing: "Verb, Aorist Active Indicative, 3rd Person Singular"
```

### 7. `search_by_strongs`

**Purpose**: Find all verses containing a specific Strong's number.

**When Claude uses it**:
- User wants to see how a word is used throughout Scripture
- User is doing a comprehensive word study
- User wants to trace a concept across the Bible

**What it returns**:
- Lexicon entry for the word
- List of verses where the word appears
- Context showing how the word is used

**Example**:
```
User: "Show me all the places where 'hesed' (H2617) appears"

Claude calls: search_by_strongs(strongs="H2617", limit=20)

Returns:
- H2617 חֶסֶד (hesed) - "lovingkindness, steadfast love"
- Genesis 24:12, Exodus 34:6, Psalm 23:6, Psalm 136...
- Each verse showing the context of hesed
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

### Example Conversation

**User**: "I'm studying Romans 5:8. What does Paul mean when he says God 'demonstrates' his love?"

**Claude's internal process**:
1. Look up the verse: `lookup_verse(reference="Romans 5:8")`
2. Study the key word: `word_study(word="demonstrates")` → finds G4921 συνίστημι
3. Check cross-references for context
4. Apply genre guidance (Epistles)

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
│   ├── server.py          # MCP server (stdio + SSE transports)
│   ├── database.py        # SQLite queries
│   ├── tools.py           # 7 tool definitions
│   ├── hermeneutics.py    # Genre detection & interpretation
│   └── parsers/           # STEPBible data parsers
├── scripts/
│   ├── download_stepbible.py  # Download source data
│   └── build_database.py      # Build SQLite database
├── prompts/
│   └── system_prompt.md   # Full hermeneutical framework for agents
├── docs/
│   ├── SETUP.md           # Quick setup guide
│   └── SELF_HOST.md       # Self-hosting instructions
├── Dockerfile             # Multi-stage build with database
├── fly.toml               # Fly.io deployment config
└── pyproject.toml
```

---

## Data Sources

### STEPBible - Tyndale House, Cambridge

All biblical data comes from the [STEPBible project](https://www.stepbible.org/) ([GitHub](https://github.com/STEPBible/STEPBible-Data)), developed by scholars at **Tyndale House, Cambridge** - one of the world's leading centers for biblical research.

**Why STEPBible is authoritative:**
- Created by Tyndale House scholars with access to primary manuscripts
- Peer-reviewed by biblical language experts
- Used by translators, seminaries, and Bible software worldwide
- Continuously updated with corrections and improvements
- Freely licensed (CC BY 4.0) for maximum accessibility

**Data files used:**

| File | Description | Content |
|------|-------------|---------|
| **TBESG** | Tyndale Brief Lexicon - Greek | 5,600+ Greek words with definitions, etymology, semantic domains |
| **TBESH** | Tyndale Brief Lexicon - Hebrew | 8,600+ Hebrew words with definitions, etymology, semantic domains |
| **TAGNT** | Translators Amalgamated Greek NT | Every word of the Greek NT with morphology, Strong's numbers, glosses |
| **TAHOT** | Translators Amalgamated Hebrew OT | Every word of the Hebrew OT with morphology, Strong's numbers, glosses |
| **TIPNR** | Translators Proper Names | 1,100+ biblical people, places, and things with references |
| **TEGMC/TEHMC** | Morphology Codes | Grammatical parsing code definitions |

The lexicons are based on Extended Strong's numbering, which disambiguates words that share traditional Strong's numbers (e.g., distinguishing different Hebrew words that Strong's grouped together).

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

---

## Acknowledgments

- [STEPBible](https://www.stepbible.org/) for the freely available biblical data
- Gordon Fee & Douglas Stuart for the hermeneutical framework in "How to Read the Bible for All Its Worth"
- The MCP community for the protocol and tooling
