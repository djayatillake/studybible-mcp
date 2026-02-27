# Release: Ancient Near East Cultural Context

## What's New

A new tool — `get_ane_context` — that retrieves structured Ancient Near East cultural and historical context to illuminate biblical passages. This is the 18th tool in the Study Bible MCP server.

### Why This Matters

The biblical authors wrote within the cultural world of the Ancient Near East. Modern readers (and LLMs trained on modern data) naturally impose a Western lens that can lead to misreadings:

- Reading "firmament" (Gen 1:6) as atmosphere rather than the solid dome ANE peoples assumed
- Missing the self-maledictory oath form in Genesis 15's covenant ceremony
- Not recognizing honor/shame dynamics in the Gospels
- Treating Deuteronomy as a legal code rather than a suzerainty treaty
- Misunderstanding household codes in the Epistles without Roman patronage context

The `get_ane_context` tool gives Claude access to structured scholarly data on ANE culture so it can surface this background naturally when studying any passage.

## The Data

**87 entries** across **12 dimensions** of ANE life, mapped to **314 book-chapter ranges** covering the entire Bible:

| Dimension | Entries | Example Topics |
|-----------|---------|---------------|
| [Cosmology & Worldview](data/ane_context/01_cosmology_worldview.json) | 8 | Three-tier universe, cosmic waters, divine council, creation by word |
| [Religious Practices](data/ane_context/02_religious_practices.json) | 7 | Sacrifice systems, temple theology, idol polemics, purity/impurity |
| [Social Structure](data/ane_context/03_social_structure.json) | 7 | Honor/shame, patronage, tribal identity, slavery, hospitality |
| [Legal & Covenant](data/ane_context/04_legal_covenant.json) | 8 | Suzerainty treaties, lex talionis, self-maledictory oaths, debt law |
| [Political & Imperial](data/ane_context/05_political_imperial.json) | 8 | Kingship ideology, vassal states, exile, imperial cult |
| [Economic Life](data/ane_context/06_economic_life.json) | 7 | Agricultural calendar, trade routes, taxation, debt/jubilee |
| [Literary Conventions](data/ane_context/07_literary_conventions.json) | 8 | Chiastic structure, merismus, prophetic oracle, apocalyptic imagery |
| [Warfare & Military](data/ane_context/08_warfare_military.json) | 7 | Holy war, siege warfare, chariots, divine warrior motif |
| [Daily Life & Material Culture](data/ane_context/09_daily_life_material_culture.json) | 7 | Housing, food, clothing, pottery, water systems |
| [Death & Afterlife](data/ane_context/10_death_afterlife.json) | 7 | Sheol, burial practices, ancestor veneration, resurrection hope |
| [Gender & Family](data/ane_context/11_gender_family.json) | 7 | Marriage customs, bride-price, levirate marriage, women's roles |
| [Education & Literacy](data/ane_context/12_education_literacy.json) | 6 | Scribal schools, oral tradition, synagogue, Torah education |

**9 time periods**: Patriarchal, Exodus/Conquest, Judges/Early Monarchy, United Monarchy, Divided Monarchy, Assyrian/Babylonian, Persian, Hellenistic, Roman.

Each entry includes:
- **Summary**: 1-3 sentence overview
- **Detail**: Full scholarly explanation with nuance
- **ANE Parallels**: Specific extra-biblical sources (Enuma Elish, Code of Hammurabi, Hittite treaties, etc.)
- **Interpretive Significance**: How this background affects reading the text
- **Key References**: Biblical passages where this context is most relevant
- **Scholarly Sources**: Academic references (Walton, Hallo, Matthews & Benjamin, Pritchard, etc.)

Browse all data files: [`data/ane_context/`](data/ane_context/)

## How It Works

### Querying

The tool accepts three optional filters (any combination):

```
get_ane_context(reference="Genesis 1:1")
  → Returns all ANE entries mapped to Genesis 1 (cosmology, literary conventions, etc.)

get_ane_context(reference="Genesis 15:1", dimension="legal_covenant")
  → Returns covenant/treaty entries relevant to Genesis 15

get_ane_context(dimension="social_structure", period="roman")
  → Returns Roman-period social structure entries (honor/shame for NT study)

get_ane_context()
  → Lists all available dimensions and periods
```

### Agent Integration

The tool is integrated into the hermeneutical reasoning pattern at the **CONTEXT** step — the agent is instructed to consider ANE cultural background as a core part of contextual analysis for every passage, not as an optional add-on. The system prompt lists 10 specific triggers for when to call the tool (creation texts, covenants, honor/shame dynamics, temple theology, etc.).

## Technical Details

- **Database**: Two new tables (`ane_entries`, `ane_book_mappings`) added to the SQLite database
- **Parser**: New `parsers/ane_context.py` following existing parser patterns
- **Data format**: 12 JSON files in `data/ane_context/`, one per dimension
- **Mapping**: Each entry maps to one or more biblical books with optional chapter ranges
- **Query**: Joins book mappings with reference parsing to find relevant entries

## Database Download

The pre-built database (including ANE context) is available for download:

**[study_bible.db](https://studybible-mcp.fly.dev/download/study_bible.db)** (~600MB)
