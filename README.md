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
| `bsb_verses` | 31,086 | Berean Standard Bible text, the English the verse tools show |
| `passages` | 5,290 | Verses grouped by ancient section markers |
| `names` | 4,299 | Biblical people, places, and things |
| `morphology` | 2,768 | Grammatical parsing code definitions |
| `thematic_references` | 22 | Core theological theme cross-references |
| `aquifer_content` | 102,673 | Study notes, dictionary articles, translation notes, key terms |
| `acai_entities` | 6,019 | Rich entity annotations (people, places, groups, key terms) |
| `ane_entries` | 87 | Ancient Near East cultural context entries across 12 dimensions |
| `ane_book_mappings` | 314 | Maps ANE entries to biblical books and chapter ranges |
| `verse_vectors` | 31,280 | OpenAI embeddings for semantic search |
| `passage_vectors` | 5,190 | OpenAI embeddings for passage similarity |

---

You can download the pre-built database directly: **[study_bible.db](https://studybible-mcp.fly.dev/download/study_bible.db)** (~750MB)

The database includes CC BY-NC 4.0 material (the ETCBC Dead Sea Scrolls
transcription and the Metsudah Chumash English), for non-commercial use only,
and CC BY-SA 4.0 material (Perseus Josephus, First1KGreek Philo, Latin
Wikisource 4 Ezra), which must be shared alike. The download response repeats
this in an `X-Data-License-Notice` header.

---

## Available Tools

### Core Text & Language

#### 1. `lookup_verse`

Retrieve a verse, verse range, or whole chapter with its original language text and word-by-word analysis.

**When Claude uses it**: User asks about a specific verse or passage, wants to see the Greek or Hebrew text, or asks about specific words in a passage.

**Accepted references**: a verse (`John 3:16`), a range within a chapter (`Luke 19:1-3`; an en dash also works), a cross-chapter range (`Luke 19:45-20:2`), or whole chapters (`Psalm 23`, `Psalm 23-24`). Single-chapter books (Obadiah, Philemon, 2 John, 3 John, Jude) may be cited by verse alone, as is conventional: `Jude 3` means `Jude 1:3` and a bare `Jude` means the whole book. This applies to every tool's `reference` argument. Verses are matched by English chapter/verse numbering, so Old Testament verses whose Hebrew numbering differs (e.g. `Psalm 40:6`, stored as `Psa.40.6(40.7)`) are found, and an English verse stored as several source rows returns all of them. A Psalm superscription, which is verse 1 in the Hebrew, is headed as such (`Psa.82 superscription (Hebrew Psa.82.1)`). A passage returns at most 50 verses; longer requests (e.g. `Psalm 119`) open with a note naming the reference that continues the passage. Unknown books, missing chapters or verses, and reversed ranges get a message saying what exists.

**What it returns**: English text from the Berean Standard Bible (labelled `(BSB)` once per response; STEPBible's word-by-word gloss, marked `[gloss]`, stands in for the few verses the BSB lacks, such as Psalm superscriptions and Matthew 17:21), original Greek/Hebrew text, word-by-word breakdown with Strong's numbers, optional morphological parsing, and genre-specific interpretation guidance. Notes about cross-references, Torah Weave partners, and NT/OT LXX quotations appear once per lookup; for a passage they name a verse to pass to those single-verse tools.

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
  Differing verse divisions do not count as differences. 8,914 of the 23,684
  rows with Brenton's own English (38%) are flagged. Unflagged rows can still
  differ, because a Greek-to-Greek comparison cannot see where his English
  departs from his own Greek.
- **Most Apocrypha English is the KJV, not Brenton's translation.** For 1
  Esdras, 1–2 Maccabees, Baruch, Bel, Judith, the Letter of Jeremiah, Sirach,
  Susanna, Tobit, Wisdom, and Daniel 3:24–90 (the Prayer of Azariah and Song of
  the Three), Brenton's edition prints the KJV (Authorized Version) Apocrypha,
  lightly adapted by Brenton (verse-by-verse similarity to the KJV is 92–100%,
  against 24–49% for his own Hebrew-canon translations). The KJV was translated
  from other Greek texts, so it can contain words neither the Rahlfs nor
  Brenton's Greek has: Sirach 17:17 adds "in the division of the nations of the
  whole earth". These 4,630 rows label the English "KJV Apocrypha", are named in
  the Sources block with one closing note, and are not compared with Brenton's
  Greek. Greek Esther and 3–4 Maccabees are Brenton's own translation.
- **Apocrypha rows are marked.** Rows outside the 66-book Protestant canon (the
  Septuagint-only books, the Greek additions to Esther, Daniel 3:24–90, Psalm
  151, and Odes 7–8, 12 and 14) end their header with "(Apocrypha)", and the
  closing block adds one line saying they are not in the Protestant canon (cf.
  Westminster Confession 1.3). Other Septuagint pluses in canonical books
  (3 Kingdoms 2:35a–o, Proverbs 9:12a–c, ...) are textual variants and are not
  marked.
- **LXX-only verses** (pluses such as the Prayer of Azariah, Psalm 151, and the
  Septuagint-only books) have no canonical MT position, so they never appear as
  the counterpart of a different MT verse. Request them with `numbering="lxx"`; a
  canonical lookup notes when such verses sit at the same Greek-numbered
  position. Septuagint-only books (Tobit, Sirach, ...) always use Greek numbering.

New Testament references, unparseable references, and references with no
matching verses each return a specific message. A database without the
Septuagint table tells you to run `python scripts/upgrade_database.py`.

#### `search_ancient_sources`

Search licensed primary-source corpora for Jewish history. `corpus` is any
registered corpus key or `all`; the registry (`src/study_bible_mcp/corpora/`)
currently holds `josephus`: 2,304 Whiston sections from *Jewish Antiquities*,
*The Jewish War*, *Life*, and *Against Apion*. Each section is paired with
every Niese Greek section it spans and referenced as a Niese span plus
Whiston's numbering, e.g. `Antiquities 15.317–322 (Whiston 15.9.3)`. `targum`
holds Targum Onkelos on the five books of the Torah: 5,846 Aramaic verse
passages with the CC BY-NC Metsudah English, an English of the Hebrew in which
Onkelos's own renderings are marked `⟨…⟩` (see [Targums](#targums)), each
linked to the verse it translates. `qumran`
holds 44 Hebrew manuscript columns with numbered lines, no English translation
included: the Damascus Document (`CD 1:1–21`, Genizah MS A columns 1–16
and MS B columns 19–20), the Community Rule (`1QS`), the Rule of the
Congregation (`1QSa`) and Pesher Habakkuk (`1QpHab`), all from the ETCBC/dss
transcription; 32 curated links name the Habakkuk verses each 1QpHab lemma
quotes. `philo` holds the 31 Greek treatises of Philo of Alexandria
(Cohn–Wendland, via First1KGreek), one passage per Cohn–Wendland section with
the same section of Yonge's English (7,901 passages; 58 sections of *Spec.* 1–2
that Yonge's text lacks are Greek only). `pseudepigrapha` holds 1 Enoch in
R. H. Charles's English, one passage per Charles verse, and 4 Ezra (2 Esdras
3–14) in the KJV with the Clementine Latin, one passage per verse (1,679
passages); both works are non-canonical and are labelled as attributed to
Enoch or Ezra. The
`rabbinic` corpus holds the Mishnah from Sefaria (63 tractates, one passage per
mishnah). Each result gives its citation and, on the line below, its
canon-and-date tag (e.g. `*Not Scripture · Jewish pseudepigraphon (Parables,
c. 50 BC–AD 117, debated) · tier A/B · Charles 1912*`), then up to 1,500
characters of English around the first match and a shorter original-language
excerpt (match-centred when the query is in the original's script; a passage
without English shows its original instead), any editorial `⚠` notes, and its
typed biblical links. A closing **Caveats** block prints each corpus's caveat
and the date tiers present once, and a **Sources** block lists the edition,
translation, license (non-commercial licences marked and linked), and pinned
source once. Up to 4 passages are returned by default, within a
12,000-character budget (see [Ancient sources](#ancient-sources)).

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
English search is stemmed (`build` matches `building`); Greek, Hebrew, and
Aramaic search ignores accents, breathings, vowel points, cantillation, and case
(`βαπτισμω` matches `βαπτισμῷ`), and editorial signs printed inside a word
(`יעבורו` matches the corrected `י{{א}}<<ע>>בורו`); Qumran text in `[ ]` is a
modern reconstruction and is never matched. Passages containing every query word come
first; when none do, passages matching any word are returned with an explicit
note. Only when the exact search finds nothing is a Hebrew or Aramaic word
retried with one or two attached prefix letters (ו ב ה ל מ כ ש) stripped from
the indexed words, keeping at least three letters (`הון` then finds `ובהון`);
those results are marked `(prefix match)`, because a root letter can look like
a prefix (`קדש` finds `מקדש`). `biblical_reference` accepts a chapter, verse,
or range (`Luke 21`, `Luke 21:5`, `Luke 21:5-6`, `Jude 6`) and filters to
editorial links: curated links (33 for Josephus, 2 for the rabbinic corpus),
each checked against the linked passage text, links from
`corpora/editorial_notes.json`, and one "Translation of" link per targum
verse, derived from its verse key (`biblical_reference="Deuteronomy 32:8"`
with `corpus="targum"` finds Onkelos on that verse). Each link is typed —
`Aligned`, `Echo`, `Shared tradition`, `Contrast`, or `Translation of` — and
printed as e.g. `- Shared tradition: Mark 6:17–29 — Related account: death of
John the Baptist`. Period tags,
biblical links, and editorial chapter headings (Whiston's, for Josephus) are
labelled editorial metadata; they are not presented as claims made by the
ancient author. Empty results say whether the corpus is missing, the reference
is unsupported, the reference has no curated link, or nothing matched.

#### `lookup_ancient_source`

Read an ancient-source passage by its citation. A citation is a work name or
abbreviation plus a locator in that work's numbering; an author prefix is
optional. For Josephus: `Antiquities`/`Ant.`/`A.J.`, `War`/`B.J.`/`J.W.`, and
`Against Apion`/`C. Ap.` take Niese `book.section`; `Life`/`Vita` takes a
section.
For Targum Onkelos, `Targum Onkelos`/`Onkelos`/`Tg. Onq.` precedes a Torah
book (`Genesis`/`Gen`, `Exodus`/`Exod`, `Leviticus`/`Lev`, `Numbers`/`Num`,
`Deuteronomy`/`Deut`) and `chapter:verse`; the prefix is optional, so a bare
`Genesis 1:1` also finds Onkelos. Onkelos is cited by English verse numbers,
like the rest of the server; where Sefaria's Hebrew (MT) numbering differs,
the heading and link show it: `Targum Onkelos Exodus 8:5 (MT 8:1)`, and the
Peniel verse is `Onkelos Genesis 32:30 (MT 32:31)`. Sefaria joins the four
short commandments into one verse, served as `Exodus 20:13–16` and
`Deuteronomy 5:17–20`. For Qumran: `CD`/`Damascus Document`/`Zadokite Fragments`, `1QS`/
`Community Rule`, `1QSa`/`1Q28a`/`Rule of the Congregation`, and
`1QpHab`/`Pesher Habakkuk` take `column:line`, with Arabic or Roman column
numbers (`CD 6:11`, `CD VI 11`, `1QpHab VII 1-5`); a line citation shows the
cited lines ±2 from the column that contains them, and a column citation
(`CD 6`) the whole column, with the line numbers in the text.
For Philo, SBL short titles, Latin titles, and English titles
(`Opif.`/`De Opificio Mundi`/`On the Creation of the World`, `Legat.`/`Leg.
Gai.`, `Her.`/`Heres`, ...) take a Cohn–Wendland section; the multi-book works
`Leg.` 1–3, `Somn.` 1–2, `Mos.` 1–2, and `Spec.` 1–4 take `book.section`; a
book number the work lacks (`Leg. 31`, likewise `Ant. 21.1`) is rejected
rather than read as a book.
`1 Enoch`/`1 En.` and `4 Ezra`/`2 Esdras`/`4 Esdras` take `chapter:verse`.
4 Ezra 3–14 is 2 Esdras 3–14 with the same chapter numbers, so `2 Esdras 11:1`
and `4 Ezra 11:1` are the same passage; 2 Esdras 1–2 and 15–16 (5 and 6 Ezra)
are not included. 4 Ezra is cited in modern (Bensly) numbering: the KJV and
Clementine Latin lack the "missing fragment" 7:36–105, so their 7:36–70 is
4 Ezra 7:106–140, shown as e.g. `4 Ezra 7:106 (KJV 2 Esdras 7:36)`. A 4 Ezra
citation outside the served text says what is missing and why.
For the Mishnah, a tractate takes `chapter:mishnah`, with an optional
`Mishnah`/`m.` prefix (`Mishnah Shekalim 1:1`, `m. Shek. 1:1`). Tractate names
follow Sefaria (`Menachot`, `Pesachim`) with SBL abbreviations and common
spellings as aliases (`Menahot`, `Men.`, `Pesah.`, `B. Bat.`); apostrophes are
ignored, so `Ta'anit 2:1` is `Taanit 2:1`.

```text
lookup_ancient_source(citation="Ant. 15.320")            # inside Antiquities 15.317–322
lookup_ancient_source(citation="Josephus, War 6.316")
lookup_ancient_source(citation="Antiquities 18.116-121", include_original=False)
lookup_ancient_source(citation="Tg. Onq. Deut 32:8")
lookup_ancient_source(citation="Onkelos Genesis 1:1-3")
lookup_ancient_source(citation="CD 6:11")               # inside CD 6:1–21 (CD-A)
lookup_ancient_source(citation="1QpHab 7:4")
lookup_ancient_source(citation="Philo, Legat. 299")
lookup_ancient_source(citation="Leg. 1.31")
lookup_ancient_source(citation="1 Enoch 89:73")
lookup_ancient_source(citation="2 Esdras 11:1")          # = 4 Ezra 11:1
lookup_ancient_source(citation="m. Shek. 1:3")
```

A locator inside a longer passage returns the passage containing it; a range
returns the overlapping passages in citation order, 4 by default (`limit` up
to 10), with a note when more exist. Each passage shows its citation,
canon-and-date tag, up to 1,500 characters of English and 600 of the original
(`full_text=true` lifts these caps), editorial `⚠` notes, and typed biblical
links; caveats and sources are printed once at the end, and the response
stops at about 12,000 characters, naming the citation to continue from. If
registered works share a title, a collection prefix (such as `Mishnah`) or the
locator grammar itself selects one.
Unknown works get a short summary of the citable works (and a close match,
e.g. `Did you mean Antiquities?`), ambiguous citations list the candidates,
unreadable or missing locators name the expected grammar with an example from
the same work, a locator outside the imported text names the imported range,
the nearest passages, and any `gap` note covering it, and a database without
the corpus (or with ancient-source tables from before the current schema) is
told to run `python scripts/upgrade_database.py`.

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

**What it returns**: The dictionary article from a collection of 500+ topical articles covering biblical people, places, theological concepts, cultural practices, historical background, and archaeological findings. A long article comes about 4,000 characters at a time, ending with the `offset` to continue from and the headings of the sections still to come (`section="The Sinai Covenant"` reads one section).

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

Trace family relationships (ancestors or descendants, 1 to 40 generations) for a biblical person using the parent links of 2,000 persons.

**What it returns**: Each ancestor or descendant once, generation by generation, with whose parent or child they are (and curated notes such as Joseph as Jesus' legal father), immediate family (spouse, siblings), and a Mermaid diagram when the tree has at most 40 people. Dictionary articles are left to `get_bible_dictionary`.

**Example**:
```
User: "Show me the family tree of David"

Claude calls: explore_genealogy(person="David", direction="both", generations=5)

Returns: Ancestor chain (Jesse → Obed → Boaz...), descendants,
spouse(s), siblings, Mermaid flowchart diagram.
```

#### 12. `explore_person_events`

Find all events a biblical person participated in, in chronological order.

**What it returns**: Each event once, in chronological order, with its approximate date (Theographic chronology), places, and passage. Names resolve as Scripture uses them ('Peter', 'Jacob' the patriarch), and the tool says which namesake it chose.

#### 13. `explore_place`

Explore the biblical history of a geographic location.

**What it returns**: Events at the location in chronological order with their passages, people born or who died there, coordinates, Mermaid network diagram.

#### 14. `find_connection`

Find the family relationship path between two biblical people.

**What it returns**: The closest relationship path through parent, child, sibling, and partner relationships, preferring lines of descent, summarised and listed compactly, with a Mermaid flowchart for paths of up to 12 steps.

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
variants. A verse can have both: at Job 38:7, Daniel 4:17 and 7:13, and Psalm
29:1 a variant case records where the Greek differs from the MT, and the notes
follow it; Mark 14:62, Matthew 24:30 and 26:64, and Revelation 1:7 reach the
Daniel 7:13 case through NT quotation alignment. `lookup_verse` mentions when a verse has a catalogued variant case or
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
│   ├── corpora/               # Ancient-source corpus registry
│   │   ├── __init__.py        # CORPORA registry (one line per corpus)
│   │   ├── base.py            # Corpus, Work, Collection, BiblicalLink types
│   │   ├── locators.py        # Citation locator grammars and sort keys
│   │   ├── citations.py       # Citation-to-work resolution
│   │   ├── download.py        # Checksum-verified download helpers
│   │   ├── josephus.py        # Josephus TEI parser, works, and links
│   │   ├── targum.py          # Targum Onkelos Sefaria files, verse keys
│   │   └── rabbinic.py        # Mishnah (Sefaria)
│   └── parsers/
│       ├── lexicon.py         # TFLSJ, BDB, Abbott-Smith, TBESG, TBESH parsers
│       ├── aquifer.py         # BibleAquifer JSON parser
│       ├── acai.py            # ACAI entity annotation parser
│       ├── ane_context.py     # ANE cultural context parser
│       ├── biblical_versions.py # MT/LXX text, morphology, and versification
│       ├── bsb.py             # Berean Standard Bible (bsb.txt) parser and importer
│       ├── ancient_sources.py # Generic corpus importer (passages, FTS, links)
│       ├── tagged_text.py     # TAGNT/TAHOT morphology parsers
│       └── proper_names.py    # TIPNR name parser
├── scripts/
│   ├── download_stepbible.py  # Download base source data (--aquifer flag)
│   ├── download_biblical_versions.py # Download pinned LXX/Brenton sources
│   ├── download_bsb.py        # Download the pinned Berean Standard Bible text
│   ├── download_ancient_sources.py # Download every registered ancient corpus
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

### Berean Standard Bible

The English verse text shown by `lookup_verse`, `search_by_strongs`,
`word_study`, `find_similar_passages` and `graph_enriched_search` is the
[Berean Standard Bible](https://bereanbible.com/), which its publisher has
dedicated to the public domain. `scripts/download_bsb.py` fetches `bsb.txt`
from bereanbible.com, which is unversioned, so the file is pinned by SHA-256
(`BSB_SHA256` in `src/study_bible_mcp/parsers/bsb.py`, the edition downloaded
on 2026-10-14); the download and import fail on any other file. The import also
requires the file's own public-domain statement, and moves the Psalm headings
the file prints at the start of verse 1 into verse 0 rows, so a Psalm's
superscription shows its BSB heading and verse 1 is the verse alone. Verses are matched by English
numbering, so split-numbered STEPBible rows (`Gen.32.1(32.2)`) get their BSB
verse; where the BSB has no such verse the tools show the STEPBible gloss
marked `[gloss]`, and without the table they show the gloss as before.

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

### Ancient sources

The ancient sources are texts written by about AD 200 that witness the Second
Temple world: Josephus, Targum Onkelos, four Qumran texts (CD, 1QS, 1QSa,
1QpHab), Philo, 1 Enoch, 4 Ezra and the Mishnah. Sources later than c. AD 200
(Targum Pseudo-Jonathan with Etheridge's English, the Tosefta, the Babylonian
Talmud and Leviticus Rabbah) were removed: they are too far from the New
Testament to witness its world without an earlier source.

Each corpus is a module in `src/study_bible_mcp/corpora/` registered in
`CORPORA`; its pinned files live in `data/ancient_sources/<corpus>/` and
`source_manifest.json` records every verified file. `build_database.py`
imports every corpus whose directory exists and fails if a present directory is
incomplete; `upgrade_database.py` fails unless every registered corpus is
downloaded and complete. All corpora share `ancient_source_passages`,
whose `sort_start`/`sort_end` keys (in each work's citation grammar) back
`lookup_ancient_source`, and whose `original_license`, `translation_license`,
and combined `license` record provenance per passage. Each import replaces only
its own corpus inside a savepoint after validating every passage and link, and
merges the FTS index so repeated upgrades do not grow it. Indexed originals are
folded for search: Greek accents and breathings and Hebrew/Aramaic vowel points
and cantillation are removed and case is folded, in the index and the query.
Editorial signs inside words (`[ ] ⟨ ⟩ < > { } ( ) ^ ¦`) and invisible format
characters are deleted rather than treated as word breaks, in the index and the
query; a corpus can also declare `search_index_removals`, patterns for printed
text that is not part of the reading (Qumran's scribal erasures and `vacat`),
which are deleted from the index, and `search_index_gaps`, printed text that
is not evidence (Qumran's `[ ]` reconstruction), which becomes a word break, so
it is never matched and the surviving letters either side are not joined into
a false word. Every Hebrew-script word is also indexed,
in a separate column searched only as a fallback, without one or two leading
prefix letters, keeping at least three letters. The displayed text keeps
every sign.

Every passage is labelled so that the agent never mistakes it for Scripture:

- **Tag.** Each corpus (or work) declares a `SourceTag` in the registry: canon
  status, kind, composition date, date tier (A: written before or alongside the
  NT; B: after the NT, to c. AD 200), edition, and, where the copy is much
  later than the work, the manuscript date. 1 Enoch is dated book by book.
  The registry refuses a corpus with an untagged work.
- **Caveat.** Each corpus declares a 1–3 sentence caveat, printed once per
  response that shows it (e.g. Philo: his Logos is not the incarnate Son).
- **Editorial notes.** `src/study_bible_mcp/corpora/editorial_notes.json`
  (committed) holds verse-level notes — `emendation`, `interpolation`,
  `reconstruction`, `contrast`, `polemic`, `caution`, `gap` — with contrasting
  and aligned biblical references, and extra typed links. Each corpus import
  loads them into `ancient_source_notes` (one row per passage a citation
  covers; a `gap` note sits on the passages either side of its range) and
  fails if a citation covers no passage or a biblical reference does not
  parse. A file link to the same passage and range as a module link replaces
  it. Notes print as `⚠ <note> (Contrast: Mark 14:62)`, once per response.
  The file holds 46 notes and 29 links, e.g. Charles's emendation at 1 Enoch
  71:14, the Christian "Jesus" of 4 Ezra 7:28–29, the restored lemma at 1QpHab
  7:17, Philo's Logos at Conf. 146, and Yom Kippur atonement at m. Yoma 8:8–9.
- **Typed links.** `ancient_source_biblical_links.relation` is `aligned`,
  `echo`, `shared_tradition`, `contrast`, or `translation`, printed as
  `Aligned: Jude 14–15 — …`, `Contrast: …` and so on. A pseudepigraphon is
  paired with the Scripture that takes it up (1 Enoch with Gen 6:1–4, Jude
  6 and 14–15, 2 Pet 2:4, 1 Pet 3:19–20). Module links take `echo` when their
  note says the text cites, quotes or expounds the Bible and
  `shared_tradition` otherwise, unless they set a relation; `create_schema`
  adds the column to older databases with the same rule, and rebuilds an
  older search index.

### Josephus

The `josephus` corpus uses all four Josephus works from
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

### Targums

The `targum` corpus holds Targum Onkelos on all five books of the Torah, one
work per book (`onkelos_genesis` … `onkelos_deuteronomy`, cited as `Onkelos
Genesis 1:1` or `Tg. Onq. Deut 32:8`). The 10 version files come from Sefaria's
archived export,
[Sefaria/Sefaria-Export-Archive](https://github.com/Sefaria/Sefaria-Export-Archive)
at commit `3f1013631fdfe452e953a93a2c5f921319e394ed` (the last commit holding
the JSON texts), each checked against its pinned Git blob hash and against the
`license` and `versionTitle` it declares; `merged.json` files are never used.

- **Aramaic:** the Torat Emet text of Onkelos (Sefaria versions `Onkelos
  {Book}`), declared Public Domain by Sefaria. One passage per Sefaria verse
  (5,846). A `???` digitization mark before Genesis 49:12 is removed.
- **English:** the Metsudah Chumash (Metsudah Publications, 2009, Sefaria
  version `Metsudah Chumash, Metsudah Publications, 2009 [with Onkelos
  translation]`, CC BY-NC 4.0). It translates the Hebrew text, so it is **not
  a direct translation of the Aramaic** beside it. Metsudah sets Onkelos's own
  renderings in bold (in Genesis 12–17, italic) brackets; these print as
  `⟨…⟩` (3,599 of them), while plain `[ ]` are Metsudah's own supplements,
  e.g. Genesis 49:10 "until Shiloh Comes ⟨the Moshiach will come, for his is
  the kingship⟩". The tag says "Metsudah: English of the Hebrew Torah;
  ⟨marked⟩ words are Onkelos's renderings", and the licence line reads
  `Aramaic text: Public domain; English translation: CC BY-NC 4.0`. A verse
  without Metsudah English is an Aramaic-only passage.

**Versification.** Sefaria numbers Onkelos by the Hebrew verses; passages,
citations and links use the server's English numbering, with the Hebrew
number in the heading where it differs (`Targum Onkelos Exodus 8:5 (MT 8:1)`).
A static table in `targum.py` covers the Torah's 18 differing runs, as in
TAHOT's verses table (`Exo.8.5(8.1)`): Gen 31:55–32:32, Exod 8:1–32 and
22:1–31, Lev 6:1–30, Num 16:36–17:13 and 29:40–30:16, Deut 12:32–13:18,
22:30–23:25 and 29:1–29. Sefaria's Decalogue follows the upper accents, so
`Exodus 20:13–16` and `Deuteronomy 5:17–20` are one passage each and later
verses shift by three; `Numbers 26:1` also holds MT 25:19. The import fails if
the English keys stop rising.

Each passage has one editorial "Translation of" link to the English verse(s)
it covers, printed with the Hebrew number where it differs (`Translation of:
Exod 8:5 (MT 8:1)`), so `biblical_reference` finds Onkelos on a verse. The
period tag gives the redaction era (editorial): `amoraic`.

### Qumran

The `qumran` corpus has one passage per manuscript column, its Hebrew lines
prefixed with their line numbers and cited `column:line`. No English
translation is included, so every passage is original-only and the tools say
so.

- **Damascus Document, Community Rule, Rule of the Congregation, Pesher
  Habakkuk** (`CD`, `1QS`, `1QSa`, `1QpHab`): the Text-Fabric transcription by Martin G. Abegg Jr., James E.
  Bowley and Edward M. Cook in [ETCBC/dss](https://github.com/ETCBC/dss),
  release 2.0.1, pinned to commit `47ecc1738fad6e67df7d40a3e84d73e4a125e265`
  and licensed [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/)
  (checked in every feature file's header at download and import). CD keeps
  the conventional page numbers: Genizah MS A columns 1–16 and MS B columns
  19–20, shown as `CD-A`/`CD-B` alongside, and its tag names the medieval copy
  served (`copy: Cairo Genizah MS A, 10th c. AD`). Lines are rendered from the
  sign-level features with the transcription's brackets: `[ ]` modern
  reconstruction, `{ }` and `{{ }}` removal by a modern editor or the scribe,
  `< >` and `<< >>` correction by a modern editor or the scribe, `^ ^`
  supralinear, `( )` alternative reading, and `vacat` (spaced off from the
  text) for an unwritten space.
  A circlet above a letter (U+05AF) marks any of its four uncertainty
  degrees, `◦` an unidentified sign, and `…` a missing sign; the morpheme
  breaks Abegg inserts before suffixes are dropped, and the transcription's
  `׃` marks are kept. Search ignores the circlets and indexes the corrected,
  surviving reading: modern reconstruction in `[ ]` is never matched (the
  letters either side of `יג[די]לו` are not joined into `יגלו`), and letters
  in `{ }` and `{{ }}` and the word `vacat` are left out of the index
  (`י{{א}}<<ע>>בורו` is found as `יעבורו`); the displayed text keeps every
  sign. Other ETCBC scrolls are not imported (1QSb, for example, mixes
  fragment labels and line gaps).

The 32 biblical links connect a 1QpHab column to each Habakkuk 1–2 verse
(range) whose lemma it quotes. Each was checked against the Masoretic verse,
and the import fails unless the anchor words survive outside the editor's
`[ ]` on their line. Three say how much of the lemma is restored; 7:14 links
Hab 2:4a only, "(end of 2:4a restored; 2:4b wholly reconstructed)".

R. H. Charles's public-domain English of the Damascus Document ("Fragments of
a Zadokite Work", *APOT* II, 1913) is not used. It is available only as OCR,
in Charles's own chapter:verse numbering with no Schechter page and line
references, and his chapter IX prints MSS A and B in parallel columns that the
OCR interleaves line by line, so it cannot be aligned reliably with CD lines.

### Philo

The `philo` corpus uses the Greek (`grc1`, Cohn–Wendland–Reiter, *Philonis
Alexandrini opera quae supersunt*, Berlin: Reimer 1896–1915) and English
(`eng1`, C. D. Yonge, *The Works of Philo Judaeus*, London: Bohn 1854–55) TEI of
all 31 treatises in
[OpenGreekAndLatin/First1KGreek](https://github.com/OpenGreekAndLatin/First1KGreek)
(`data/tlg0018/tlg001`–`tlg031`, *De Opificio Mundi* to *Legatio ad Gaium*),
pinned to commit `03776b39f4047c5cff06f5296fae4b2bae4b08fb`. The module pins
each file's Git blob hash and fetches it from that commit without GitHub API
calls. The First1KGreek editors divided the English at the same Cohn–Wendland
sections as the Greek, so each passage is exactly one section: its Greek and
the English section of the same number, never a neighbouring one. The 58
Greek sections of *Spec.* 1.177–193 and 2.124–213 that Yonge's shorter text
lacks are imported as Greek-only passages, marked "Yonge has no English for
this section"; an English section without a Greek counterpart fails the
import. Apparatus, marginal notes, page and line markers,
and Yonge's footnotes and source references are kept out of the text; Yonge's
treatise headings (e.g. "A TREATISE ON CIRCUMCISION." within *Spec.*) are
editorial headings. Each file declares CC BY-SA 4.0, checked at download and
parse. Works surviving only in Armenian or Latin (*QG*, *QE*, *Prov.*, *Anim.*),
the *Hypothetica*, and fragments are not in First1KGreek and are not included.
Twenty-five curated links name the Genesis or Exodus verse a section quotes and
expounds (e.g. *Leg.* 1.31 → Gen 2:7) and *Legat.* 299 → Luke 3:1 (Pilate).
Search for Philo's Greek uses Greek script (`λόγος`, `λογος`); a transliteration
such as `logos` does not match, and Yonge renders λόγος as "word" or "reason".

### Pseudepigrapha

The `pseudepigrapha` corpus holds two non-canonical works. **1 Enoch** is R. H.
Charles's translation (2nd ed. 1912, SPCK reprint 1917) from English Wikisource,
one page per chapter (1–108), each pinned to a revision id and its SHA-1 and
fetched in three MediaWiki API requests. The translation is in the public domain
in the United States (Charles died in 1931; Wikisource `{{PD/US|1931}}`). Each
passage is one Charles verse in his order, including his sub-verses and
transpositions (`1 Enoch 5:6a–b`, `5:7c`, `5:6d–j`; `89:48b`; `91:14d`), all
sorted under their verse number; Charles's section headings
(`LXXXIX. 72-77. ...`) are editorial headings. Where Charles prints a parallel
column with a header (his rendering of the Greek or Latin witnesses in chapters
22, 27, 32, 89, and 106) only the main Ethiopic column is imported; the
unheaded doublet columns of 90:13–18 are both text. No Ge'ez is included: the
Beta maṣāḥǝft file (`LIT1340EnochE`) offers Dillmann's text only at chapter
level under a custom non-commercial notice that must accompany every copy, and
an EOTC printed-edition text whose own rights are not stated.

**4 Ezra** is 2 Esdras 3–14 in the KJV with Apocrypha (eBible.org `eng-kjv`,
public domain; the extracted `58-2ESeng-kjv.usfm` is pinned by SHA-256 because
eBible regenerates its zip) paired with the Clementine Vulgate's *Liber Quartus
Esdrae* (Rome 1598) from Latin Wikisource revision 148869 (transcribed from
public-domain page images; Wikisource transcription CC BY-SA 4.0, credited by
URL in every Sources block). Passages are
one KJV verse with the Latin verse of the same number, except 27 spans where
the two divide verses differently (usually a speech introduction such as "Et
dixit ad me," / "And he said unto me" placed on the other side of a verse
boundary, and an offset in 14:14–20); each span pairs all of its English with
all of its Latin, and the import fails if any verse of either text is left
unpaired. 4 Ezra 3–14 keeps the 2 Esdras chapter numbers; KJV 7:36–70 is
cited as 7:106–140 (both texts lack the "missing fragment" 7:36–105, which is
not available from an openly licensed source). 2 Esdras 1–2 and 15–16 are later
Christian additions (5 and 6 Ezra) and are not included. A citation outside
the served text (`4 Ezra 7:50`, `2 Esdras 15:1`) says both.

Period tags give conventional composition dates (1 Enoch: Watchers,
Astronomical Book, Dream Visions, and Epistle `hellenistic`, Parables `roman`;
4 Ezra `roman`, after 70 CE). Twenty-two curated links mark allegorical
retellings and shared imagery, e.g. the Animal Apocalypse (1 Enoch 89) with the
Genesis–Kings narrative and Malachi 1:7, and the eagle vision (4 Ezra 11–12)
with Daniel 7, which 4 Ezra 12:11 names; 1 Enoch 1:9 → Jude 14–15 and 6:1 →
Gen 6:1–2 are `aligned`. The editorial-notes file adds the aligned links to
Jude 6, 2 Pet 2:4 and 1 Pet 3:19–20.

### Rabbinic texts

The `rabbinic` corpus holds the Mishnah from Sefaria's JSON export, pinned to
commit `3f1013631fdfe452e953a93a2c5f921319e394ed` of
[Sefaria/Sefaria-Export-Archive](https://github.com/Sefaria/Sefaria-Export-Archive)
(the last full export committed before Sefaria moved it to a GCS bucket that
is overwritten monthly and not versioned) and verified by Git blob hash. Every
Sefaria version declares its own licence; downloads and imports reject any
version that is not Public Domain or CC-BY. CC-BY is recorded as CC BY 3.0,
the licence Sefaria's reader links it to.

- **Mishnah**, all 63 tractates, one passage per mishnah (`Mishnah Shekalim
  1:1`): Hebrew *Mishnah, ed. Romm, Vilna 1913* (public domain) with Joshua
  Kulp's *Mishnah Yomit* English (CC BY). Bikkurim chapter 4, absent from the
  Vilna version, is English only.

Footnotes, footnote markers and HTML are removed from the English. Curated
links: Mishnah Shekalim 1:1 and 1:3 to Matthew 17:24–27 (the half-shekel); the
editorial-notes file adds Gospel echoes (e.g. Shekalim 1:3 → Mark 11:15) and
contrast notes. The corpus caveat warns that Kulp's bracketed Bible references
sometimes use Hebrew numbering or contain errors.

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
| People | 3,426 | Family relationships, variant names, roles, speech attributions, verse references |
| Places | 1,418 | Geographic entities with biblical references |
| Groups | 307 | People groups, nations, tribes |
| Key Terms | 868 | Annotated theological concepts |

### Theographic Bible Metadata

Graph data for genealogy, events, and places from [Theographic](https://github.com/robertrouse/theographic-bible-metadata), with curated corrections and twenty added events (the binding of Isaac, the burning bush, the fall of Jerusalem ...) in [`src/study_bible_mcp/parsers/graph_curated.json`](src/study_bible_mcp/parsers/graph_curated.json). Used by the `explore_genealogy`, `explore_person_events`, `explore_place`, `find_connection`, `people_in_passage`, and `graph_enriched_search` tools.

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

Contributions welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, the test
suite (run in CI on every pull request) and the rules every change keeps:
small outputs, Scripture kept distinct from other sources, pinned and licensed
data, and safe database upgrades. Especially welcome:

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
The Onkelos Aramaic (Torat Emet) is public domain as declared by [Sefaria](https://www.sefaria.org/); the Metsudah Chumash English of Onkelos is licensed under [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/) (non-commercial use only), and its licence is shown on every passage.
The ETCBC/dss Dead Sea Scrolls transcription (Abegg, Bowley and Cook), the source of all four Qumran texts, is licensed under [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/) (non-commercial use only).
The First1KGreek Philo Greek and English TEI editions are licensed under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/); Cohn–Wendland's Greek and Yonge's English are public domain.
Charles's 1 Enoch (via English Wikisource) and the KJV 2 Esdras (via eBible.org) are public domain; the Latin Wikisource transcription of the Clementine 4 Esdras is licensed under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
Mishnah passages carry each version's licence: Kulp's Mishnah Yomit English is CC BY, and the Vilna Mishnah is public domain.
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
- [Sefaria](https://www.sefaria.org/) for the Torat Emet text of Onkelos and the Metsudah Chumash English, via [Sefaria-Export-Archive](https://github.com/Sefaria/Sefaria-Export-Archive)
- [ETCBC/dss](https://github.com/ETCBC/dss) and Martin G. Abegg Jr., James E. Bowley and Edward M. Cook for the Dead Sea Scrolls transcription
- [Open Greek and Latin / First1KGreek](https://github.com/OpenGreekAndLatin/First1KGreek) for the licensed Philo Greek and English editions
- [Wikisource](https://en.wikisource.org/wiki/The_Book_of_Enoch_(Charles)) contributors for R. H. Charles's 1 Enoch and the [Latin Clementine Vulgate](https://la.wikisource.org/wiki/Vulgata_Clementina) 4 Esdras
- [eBible.org](https://ebible.org/find/show.php?id=eng-kjv) for the public-domain KJV with Apocrypha
- [Sefaria](https://www.sefaria.org/) for the Vilna Mishnah and Joshua Kulp's Mishnah Yomit English
- [BibleAquifer](https://github.com/BibleAquifer) for study notes, dictionary, translation notes, and key terms
- [eliranwong](https://github.com/eliranwong/unabridged-BDB-Hebrew-lexicon) for the unabridged BDB Hebrew lexicon
- [translatable-exegetical-tools](https://github.com/translatable-exegetical-tools/Abbott-Smith) for the Abbott-Smith Greek Lexicon TEI XML edition
- [Theographic](https://github.com/robertrouse/theographic-bible-metadata) for genealogy and event graph data
- Gordon Fee & Douglas Stuart for the hermeneutical framework in "How to Read the Bible for All Its Worth"
- The MCP community for the protocol and tooling
