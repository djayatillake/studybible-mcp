# Release: Ancient Near East Cultural Context

**Tool 18**: `get_ane_context` — structured ANE cultural and historical background for biblical passages.

## Why This Matters

The biblical authors wrote within the cultural world of the Ancient Near East. Modern readers (and LLMs trained on modern data) naturally impose a Western lens that can lead to misreadings:

- Reading "firmament" (Gen 1:6) as atmosphere rather than the solid dome ANE peoples assumed
- Missing the self-maledictory oath form in Genesis 15's covenant ceremony
- Not recognizing honor/shame dynamics in the Gospels
- Treating Deuteronomy as a legal code rather than a suzerainty treaty
- Misunderstanding household codes in the Epistles without Roman patronage context

The `get_ane_context` tool gives Claude access to structured scholarly data on ANE culture so it can surface this background naturally when studying any passage.

---

## How It's Triggered

The agent is instructed through two layers to know when ANE context is relevant.

### Layer 1: System Prompt — Reasoning Pattern

Every biblical question goes through a 7-step hermeneutical reasoning sequence (based on Fee & Stuart's *How to Read the Bible for All Its Worth*). ANE context is embedded as a **core part of Step 3 (CONTEXT)**, not as an optional extra:

```
### 3. CONTEXT
- Historical: Who wrote to whom, when, why?
- Cultural/ANE: What did the original audience assume about cosmology,
  social structure, law, or religion? Use get_ane_context to retrieve
  relevant Ancient Near East background that illuminates the passage.
- Literary: What comes before/after? Book's purpose?
- Canonical: Where does this fit in redemption history?
```

This means the agent considers cultural distance for every passage as part of its standard interpretive workflow.

### Layer 2: System Prompt — 10 Specific Triggers

The system prompt lists explicit situations where the agent should call `get_ane_context`:

| Trigger | What It Catches |
|---------|----------------|
| Creation, flood, or cosmological texts | Three-tier universe, cosmic waters, chaos motif (Gen 1-11, Job 38, Psalms) |
| Temples, sacrifices, or religious practices | ANE sacrifice systems, temple-as-divine-dwelling, idol polemics (Leviticus, Kings, Isaiah) |
| Covenants, treaties, or legal codes | Suzerainty treaties, lex talionis, covenant lawsuit pattern (Exodus, Deuteronomy, prophets) |
| Honor/shame dynamics | Mediterranean honor culture in Gospels and Epistles (parables, Paul's rhetoric) |
| Marriage customs, family structures, inheritance, slavery | Bride-price, levirate marriage, patrilocal households, debt slavery (Genesis, Ruth, Epistles) |
| Warfare, kingship, siege, imperial contexts | Holy war, divine warrior motif, imperial cult (Joshua, Samuel, Daniel, Revelation) |
| ANE literary forms | Chiasm, merismus, prophetic oracle, lament, apocalyptic imagery (throughout) |
| Daily life, agriculture, trade, material culture | Threshing floors, wineskins, trade routes (Gospel parables, OT narratives) |
| Death, underworld (Sheol), burial, afterlife | ANE underworld concepts, burial theology, resurrection hope (Psalms, Ezekiel, Daniel) |
| Educational context, scribal culture, oral tradition | Scribal schools, memorization, synagogue, Torah education (Wisdom literature, Gospels) |

### Layer 3: Tool Description

The MCP tool definition itself reinforces when to use it, visible to the agent at tool-selection time:

```
Get Ancient Near East (ANE) cultural and historical background for a biblical passage.

The biblical authors and their audiences lived in the Ancient Near East with
fundamentally different assumptions about cosmology, social structure, religion,
law, and daily life. This tool retrieves structured ANE contextual data to
illuminate what the text meant to its original audience.

USE THIS when:
- Studying creation, flood, or cosmological texts
- Encountering references to temples, sacrifices, or religious practices
- Reading about covenants, treaties, or legal codes
- Studying honor/shame dynamics in Gospels or Epistles
- Understanding marriage customs, family structures, or inheritance laws
- Reading about warfare, kingship, or imperial contexts
- Encountering literary forms (chiasm, inclusio, lament, oracle)
- Needing background on daily life, agriculture, or material culture
```

---

## How It's Used

### MCP Tool Interface

The tool accepts three optional parameters — `reference`, `dimension`, and `period` — in any combination:

```
# Get all ANE context for a passage
get_ane_context(reference="Genesis 1:1")
→ Returns cosmology, literary conventions, religious practices entries mapped to Genesis 1

# Filter by dimension
get_ane_context(reference="Genesis 15:1", dimension="legal_covenant")
→ Returns only covenant/treaty entries relevant to Genesis 15

# Filter by period (useful for NT study)
get_ane_context(dimension="social_structure", period="roman")
→ Returns Roman-period social structure (honor/shame, patronage for Gospels/Epistles)

# Combine dimension and period without a reference
get_ane_context(dimension="religious_practices", period="persian")
→ Returns Persian-period religious practices (Second Temple context)

# List all available dimensions and periods
get_ane_context()
→ Returns dimension names, entry counts, and period labels
```

### Reference Matching

When a reference is provided, the server:
1. Parses it using the existing `_normalize_reference()` method (e.g., "Genesis 15:1" → `Gen.15`)
2. Joins `ane_entries` with `ane_book_mappings` on `entry_id`
3. Matches the 3-letter book abbreviation and checks if the chapter falls within the entry's `chapter_start`–`chapter_end` range
4. If `chapter_start` is NULL, the entry applies to the entire book

### Output Format

Results are formatted as markdown, grouped by dimension:

```markdown
## Ancient Near East Context for Genesis 15:1

## Legal & Covenant

### Suzerainty Treaty Form and Deuteronomy
*Period: Exodus & Conquest*

The structure of Hittite suzerainty treaties from the Late Bronze Age closely
parallels the literary structure of Deuteronomy...

[Full scholarly detail paragraph]

**ANE Parallels:**
- Treaty between Hattusili III and Ramesses II: Major Hittite-Egyptian treaty...
- Treaty of Suppiluliuma and Huqqana: Hittite vassal treaty...
- Esarhaddon's Succession Treaty (672 BCE): Neo-Assyrian treaty...

**Interpretive Significance:** Recognizing the treaty form reveals that
Deuteronomy is not simply a law code but a covenant document...

**Key References:** Exo 19:3-6, Exo 20:1-17, Deu 1:1-5, Deu 5:1-21...

**Sources:** Mendenhall, 'Covenant Forms in Israelite Tradition'; Kitchen,
On the Reliability of the Old Testament; Weinfeld, Deuteronomy and the
Deuteronomic School...
```

### Typical Tool Chains

The agent typically uses `get_ane_context` alongside other tools:

- **Deep passage study**: `lookup_verse` → `get_study_notes` → `get_ane_context` → `word_study`
- **Cultural context question**: `get_ane_context` → `lookup_verse` → `get_bible_dictionary`
- **Verse enrichment**: After calling `lookup_verse`, the agent may follow up with `get_ane_context` when the passage touches on creation, covenant, temple, honor/shame, etc.

---

## The Data

**87 entries** across **12 dimensions**, mapped to **314 book-chapter ranges** covering the entire Bible.

### Dimensions

| # | Dimension | Entries | Data File | Example Topics |
|---|-----------|---------|-----------|---------------|
| 1 | Cosmology & Worldview | 8 | [`01_cosmology_worldview.json`](https://github.com/djayatillake/studybible-mcp/blob/main/data/ane_context/01_cosmology_worldview.json) | Three-tier universe, cosmic waters, divine council, creation by word |
| 2 | Religious Practices | 7 | [`02_religious_practices.json`](https://github.com/djayatillake/studybible-mcp/blob/main/data/ane_context/02_religious_practices.json) | Sacrifice systems, temple theology, idol polemics, purity/impurity |
| 3 | Social Structure | 7 | [`03_social_structure.json`](https://github.com/djayatillake/studybible-mcp/blob/main/data/ane_context/03_social_structure.json) | Honor/shame, patronage, tribal identity, slavery, hospitality |
| 4 | Legal & Covenant | 8 | [`04_legal_covenant.json`](https://github.com/djayatillake/studybible-mcp/blob/main/data/ane_context/04_legal_covenant.json) | Suzerainty treaties, lex talionis, self-maledictory oaths, debt law |
| 5 | Political & Imperial | 8 | [`05_political_imperial.json`](https://github.com/djayatillake/studybible-mcp/blob/main/data/ane_context/05_political_imperial.json) | Kingship ideology, vassal states, exile, imperial cult |
| 6 | Economic Life | 7 | [`06_economic_life.json`](https://github.com/djayatillake/studybible-mcp/blob/main/data/ane_context/06_economic_life.json) | Agricultural calendar, trade routes, taxation, debt/jubilee |
| 7 | Literary Conventions | 8 | [`07_literary_conventions.json`](https://github.com/djayatillake/studybible-mcp/blob/main/data/ane_context/07_literary_conventions.json) | Chiastic structure, merismus, prophetic oracle, apocalyptic imagery |
| 8 | Warfare & Military | 7 | [`08_warfare_military.json`](https://github.com/djayatillake/studybible-mcp/blob/main/data/ane_context/08_warfare_military.json) | Holy war, siege warfare, chariots, divine warrior motif |
| 9 | Daily Life & Material Culture | 7 | [`09_daily_life_material_culture.json`](https://github.com/djayatillake/studybible-mcp/blob/main/data/ane_context/09_daily_life_material_culture.json) | Housing, food, clothing, pottery, water systems |
| 10 | Death & Afterlife | 7 | [`10_death_afterlife.json`](https://github.com/djayatillake/studybible-mcp/blob/main/data/ane_context/10_death_afterlife.json) | Sheol, burial practices, ancestor veneration, resurrection hope |
| 11 | Gender & Family | 7 | [`11_gender_family.json`](https://github.com/djayatillake/studybible-mcp/blob/main/data/ane_context/11_gender_family.json) | Marriage customs, bride-price, levirate marriage, women's roles |
| 12 | Education & Literacy | 6 | [`12_education_literacy.json`](https://github.com/djayatillake/studybible-mcp/blob/main/data/ane_context/12_education_literacy.json) | Scribal schools, oral tradition, synagogue, Torah education |

### Periods

| Period | Label | Approx. Date Range |
|--------|-------|-------------------|
| `patriarchal` | Patriarchal | c. 2000–1500 BCE |
| `exodus_conquest` | Exodus & Conquest | c. 1500–1200 BCE |
| `judges_early_monarchy` | Judges & Early Monarchy | c. 1200–1000 BCE |
| `united_monarchy` | United Monarchy | c. 1000–930 BCE |
| `divided_monarchy` | Divided Monarchy | c. 930–722 BCE |
| `assyrian_babylonian` | Assyrian & Babylonian | c. 722–539 BCE |
| `persian` | Persian | c. 539–332 BCE |
| `hellenistic` | Hellenistic | c. 332–63 BCE |
| `roman` | Roman | c. 63 BCE–100 CE |

### Entry Structure

Each entry in the JSON files follows this schema:

```json
{
  "id": "legal_003",
  "title": "Covenant Ratification Rituals and Animal Cutting",
  "summary": "The covenant ceremony in Genesis 15, where God passes between severed animal halves, reflects a widely attested ANE ritual...",
  "detail": "In Genesis 15:9-21, Abraham cuts animals in half and arranges the pieces, after which a smoking fire pot and flaming torch (representing God's presence) pass between them. This mirrors the ANE covenant-cutting ceremony (the Hebrew idiom karat berit literally means 'to cut a covenant') known from multiple sources...",
  "ane_parallels": [
    "Sefire Treaty (eighth century BCE): Aramaic inscription containing explicit self-imprecatory oath...",
    "Mari Letters: References to 'killing a donkey foal' as the standard ritual...",
    "Neo-Assyrian Adê texts: Treaty oaths invoking self-curses..."
  ],
  "interpretive_significance": "The cutting ritual illuminates why 'covenant' and 'cut' are linguistically bound in Hebrew (karat berit). More theologically, Genesis 15 shows God assuming the full weight of the covenant curse upon himself...",
  "period": "patriarchal",
  "books": ["Gen", "Jer"],
  "chapter_start": 15,
  "chapter_end": 15,
  "key_references": ["Gen 15:9-21", "Jer 34:18-20", "Gen 17:1-14"],
  "scholarly_sources": [
    "Mendenhall, 'Covenant Forms in Israelite Tradition'",
    "Weinfeld, 'The Covenant of Grant in the Old Testament and in the Ancient Near East' (JAOS, 1970)",
    "Hallo, Context of Scripture, vol. 2 (Sefire treaty texts)"
  ]
}
```

### Book Mapping

Each entry maps to one or more biblical books with optional chapter ranges:

- `"books": ["Gen"], "chapter_start": 1, "chapter_end": 11` — applies to Genesis 1–11
- `"books": ["Gen", "Jer"], "chapter_start": 15, "chapter_end": 15` — applies to Genesis 15 and Jeremiah 15
- `"books": ["Mat", "Mrk", "Luk", "Jhn"], "chapter_start": null` — applies to all chapters of all four Gospels

---

## Database Schema

Two tables store the ANE data:

### `ane_entries` (87 rows)

| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT PK | Entry identifier (e.g., `legal_003`) |
| `dimension` | TEXT | Dimension key (e.g., `legal_covenant`) |
| `dimension_label` | TEXT | Display label (e.g., `Legal & Covenant`) |
| `title` | TEXT | Entry title |
| `summary` | TEXT | 1-3 sentence overview |
| `detail` | TEXT | Full scholarly explanation |
| `ane_parallels` | TEXT | JSON array of extra-biblical parallels |
| `interpretive_significance` | TEXT | How this affects reading the text |
| `period` | TEXT | Period key (e.g., `patriarchal`) |
| `period_label` | TEXT | Display label (e.g., `Patriarchal`) |
| `key_references` | TEXT | JSON array of biblical references |
| `scholarly_sources` | TEXT | JSON array of academic citations |

Indexes: `idx_ane_dimension` on `dimension`, `idx_ane_period` on `period`.

### `ane_book_mappings` (314 rows)

| Column | Type | Description |
|--------|------|-------------|
| `entry_id` | TEXT FK | References `ane_entries.id` |
| `book` | TEXT | 3-letter book abbreviation (e.g., `Gen`, `Deu`, `Mat`) |
| `chapter_start` | INTEGER | Start chapter (NULL = entire book) |
| `chapter_end` | INTEGER | End chapter (NULL = single chapter or entire book) |

Primary key: `(entry_id, book, chapter_start)`. Indexes on `book` and `entry_id`.

### Query Logic

When `get_ane_context(reference="Genesis 15:1")` is called:

```sql
SELECT DISTINCT e.*
FROM ane_entries e
JOIN ane_book_mappings bm ON e.id = bm.entry_id
WHERE bm.book = 'Gen'
  AND (bm.chapter_start IS NULL
       OR (bm.chapter_start <= 15
           AND (bm.chapter_end IS NULL OR bm.chapter_end >= 15)))
ORDER BY e.dimension, e.period
LIMIT 20
```

Additional `WHERE` clauses are appended when `dimension` or `period` filters are provided.

---

## Code Architecture

### Files Added

| File | Purpose |
|------|---------|
| [`data/ane_context/*.json`](https://github.com/djayatillake/studybible-mcp/tree/main/data/ane_context) | 12 JSON data files, one per dimension |
| [`src/study_bible_mcp/parsers/ane_context.py`](https://github.com/djayatillake/studybible-mcp/blob/main/src/study_bible_mcp/parsers/ane_context.py) | Parser: reads JSON, yields `(entry_dict, book_mappings)` tuples |

### Files Modified

| File | Changes |
|------|---------|
| [`src/study_bible_mcp/database.py`](https://github.com/djayatillake/studybible-mcp/blob/main/src/study_bible_mcp/database.py) | Schema (`ane_entries`, `ane_book_mappings`), query methods (`has_ane_data`, `get_ane_dimensions`, `get_ane_context`) |
| [`src/study_bible_mcp/tools.py`](https://github.com/djayatillake/studybible-mcp/blob/main/src/study_bible_mcp/tools.py) | Tool definition with input schema + enum validation, `format_ane_context()` and `format_ane_dimensions()` formatters |
| [`src/study_bible_mcp/server.py`](https://github.com/djayatillake/studybible-mcp/blob/main/src/study_bible_mcp/server.py) | `handle_get_ane_context()` handler, dispatch in `call_tool()` |
| [`scripts/build_database.py`](https://github.com/djayatillake/studybible-mcp/blob/main/scripts/build_database.py) | `import_ane_context()` function, wired into build pipeline |
| [`prompts/system_prompt.md`](https://github.com/djayatillake/studybible-mcp/blob/main/prompts/system_prompt.md) | ANE in reasoning pattern + 10 triggers in tool usage guide |

---

## Database Download

The pre-built database (including all ANE context) is available for direct download:

**[study_bible.db](https://studybible-mcp.fly.dev/download/study_bible.db)** (~600MB)
