"""
Tool definitions for the Study Bible MCP server.

Each tool is defined as an MCP Tool object with name, description, and input schema.

The server exposes read-only research data about the Bible: verse text in English
and the original Greek/Hebrew, Strong's lexicon entries, morphological parsing,
cross-reference datasets, a biblical people/places/events graph, published study
notes and dictionary articles, Ancient Near East background, theological
scholarship extracts, Torah literary-structure data, and MT/LXX/DSS textual
variants.

The datasets relate to one another through several shared keys, which is what
makes multi-tool research possible:

- **People and places** — entries carry family relationships (parents, siblings,
  spouse, children) and event/location links, so narratives can be traced across
  books.
- **Strong's numbers** — lexicon entries, verse word data, and concordance search
  share the same identifiers, so a term can be followed through its occurrences.
- **Verse references** — cross-references, study notes, ANE context, scholarship,
  Torah weave cells, and textual variants are all keyed by canonical reference.

Results are returned as Markdown text. Where a tool produces a diagram it is
emitted as a Mermaid code block within that text.
"""

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

from mcp.types import Tool, ToolAnnotations

from .parsers.biblical_versions import VERSE_MAPPING_CREDIT


def _parse_json_field(value, default=None):
    """Parse a JSON string field, returning default if parsing fails or value is already the right type."""
    if value is None:
        return default
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


def _truncate(text: str, limit: int, suffix: str = "\n\n*[Truncated]*") -> str:
    """Truncate text to limit characters, appending suffix if truncated."""
    if len(text) <= limit:
        return text
    return text[:limit] + suffix


RESEARCH_SOURCES_DEFAULT_LIMIT = 4
RESEARCH_SOURCES_MAX_LIMIT = 10


TOOLS = [
    Tool(
        name="word_study",
        annotations=ToolAnnotations(title="Word Study", readOnlyHint=True, destructiveHint=False, idempotentHint=True),
        description="""Look up the lexicon entry for a Strong's number, or for a Greek, Hebrew, or English word.

Given a Strong's number (G26, H430) the entry is returned directly; given an
English word, the most relevant Greek or Hebrew term is resolved first.

Returns:
- The word in its original script (e.g. ἀγάπη, אֱלֹהִים)
- Transliteration and pronunciation
- Strong's number
- Brief and full definitions (LSJ for Greek, BDB for Hebrew, plus Abbott-Smith
  for NT Greek where available)
- Etymology, semantic range, and related words
- Occurrence counts and representative passages

Relevant for questions about a specific original-language term, a theological
term's underlying vocabulary, or the semantic range behind an English rendering.""",
        inputSchema={
            "type": "object",
            "properties": {
                "strongs": {
                    "type": "string",
                    "description": "Strong's number (e.g., 'G26' for agapē, 'H3068' for YHWH)"
                },
                "word": {
                    "type": "string",
                    "description": "English word to study (e.g., 'love', 'faith'). Will find the most relevant Greek/Hebrew term."
                },
                "language": {
                    "type": "string",
                    "enum": ["greek", "hebrew"],
                    "description": "Language to search if using 'word' parameter. Default: greek"
                }
            }
        }
    ),
    Tool(
        name="lookup_verse",
        annotations=ToolAnnotations(title="Lookup Verse", readOnlyHint=True, destructiveHint=False, idempotentHint=True),
        description="""Look up the text of a Bible verse, verse range, or whole chapter, in English and in the original language.

Returns, for each verse in canonical order:
- The English verse text (STEPBible word-by-word glosses)
- The original Greek/Hebrew text (optional, on by default)
- A word-by-word breakdown with Strong's numbers and glosses (single verses;
  for a passage only when include_morphology is set)
- Optional grammatical parsing for each word

And once for the passage:
- Genre-specific interpretive background for the passage's literary type
- Availability notes for related data (cross-references, Torah weave partners,
  and NT/OT LXX-quotation variants) where the verses have such records

Accepts 'John 3:16', 'Luke 19:1-3', cross-chapter ranges such as
'Luke 19:45-20:2', and whole chapters such as 'Psalm 23'. Single-chapter books
may be cited by verse alone ('Jude 3', 'Philemon 6', '3 John 4'); 'Jude 1' is the
whole chapter. Numbering is
English; a Psalm superscription (verse 1 in the Hebrew) is labelled as the
superscription. Returns at most 50 verses per call, with a note naming the
reference that continues a longer passage.

Relevant whenever the verified wording of a passage, or its original-language
form, is needed.""",
        inputSchema={
            "type": "object",
            "properties": {
                "reference": {
                    "type": "string",
                    "description": "Bible reference (e.g., 'John 3:16', 'Luke 19:1-3', 'Luke 19:45-20:2', or a whole chapter such as 'Psalm 23')"
                },
                "include_original": {
                    "type": "boolean",
                    "description": "Include original Greek/Hebrew text. Default: true"
                },
                "include_morphology": {
                    "type": "boolean",
                    "description": "Include grammatical parsing for each word (and, for a passage, the word-by-word list). Default: false"
                }
            },
            "required": ["reference"]
        }
    ),
    Tool(
        name="compare_biblical_versions",
        annotations=ToolAnnotations(
            title="Compare Biblical Versions",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
        ),
        description="""Compare the Masoretic Text (MT) and Septuagint (LXX) side by side for an Old Testament or Septuagint verse, range, or chapter. Not for the New Testament. Returns at most ten verses per call and names the verse to continue from.

Rows are grouped by canonical MT/English reference and keep each edition's own reference, so Hebrew/Greek versification differences stay explicit (Psalm 82:6 = Greek Psa.81.6). MT: Westminster Leningrad Codex with STEPBible word glosses (not a translation). LXX: Rahlfs, with Brenton's English only where Brenton translated the same recension. Brenton translated his own Greek, not Rahlfs: where it differs the row warns and shows his Greek, and his English should be quoted as a rendering of that text. LXX-only verses (e.g. the Prayer of Azariah) need numbering='lxx'. Sources, licences, and the TVTMS verse-mapping credit are listed once at the end.""",
        inputSchema={
            "type": "object",
            "properties": {
                "reference": {
                    "type": "string",
                    "description": (
                        "Verse, range (also across chapters), or chapter; at most 10 verses "
                        "are returned. E.g. 'Psalm 24:1', 'Genesis 1:1-3', 'Psalm 81:6-82:1'"
                    ),
                },
                "versions": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["MT", "LXX"]},
                    "default": ["MT", "LXX"],
                    "description": "Editions to return, in display order. Default: MT and LXX",
                },
                "numbering": {
                    "type": "string",
                    "enum": ["canonical", "lxx"],
                    "default": "canonical",
                    "description": (
                        "Read the reference in canonical MT/English numbering (default) or in "
                        "the Greek edition's numbering ('lxx', e.g. Psalm 81:6 = MT Psalm 82:6). "
                        "Books without an MT always use Greek numbering."
                    ),
                },
                "include_original": {
                    "type": "boolean",
                    "default": True,
                    "description": "Include Hebrew/Greek text. Default: true",
                },
                "include_morphology": {
                    "type": "boolean",
                    "default": False,
                    "description": "Include word-level morphology. Default: false",
                },
            },
            "required": ["reference"],
        },
    ),
    Tool(
        name="search_ancient_sources",
        annotations=ToolAnnotations(
            title="Search Ancient Sources",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
        ),
        description="""Search licensed primary-source corpora for Second Temple and
early Roman Jewish history. The initial corpus is all four surviving works of
Flavius Josephus in Whiston's English translation paired with Niese's Greek.

Each result is one Whiston section with every Niese Greek section it spans,
referenced as a Niese span ('Antiquities 15.317–322') plus Whiston's numbering
('Whiston 15.9.3'). English search is stemmed (build/building); Greek search
ignores accents, breathings, and case. Passages containing every query word
are returned first; if none contain all of them, passages matching any word are
returned and the output says so.

Only the passage text is searched, not work titles or references. Results are
source passages, not modern historical judgments. Each result gives the work,
reference, editorial period tags, and an excerpt around the first match; the
edition, translation, license, and source are listed once at the end. Whiston's
chapter headings are shown as editorial metadata, not as Josephus's text. `biblical_reference` uses a
small curated set of editorial narrative-overlap links and is never inferred
from keyword overlap.""",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "English or Greek words to search for (e.g. 'John Baptist', 'Herod temple', or 'βαπτισμῷ'). Search operators are ignored.",
                },
                "corpus": {
                    "type": "string",
                    "enum": ["josephus"],
                    "default": "josephus",
                    "description": "Licensed corpus to search. Default: josephus",
                },
                "biblical_reference": {
                    "type": "string",
                    "description": "Optional chapter, verse, or verse range (e.g. 'Luke 21', 'Luke 21:5', 'Luke 21:5-6') limiting results to passages with a curated editorial link overlapping it",
                },
                "period": {
                    "type": "string",
                    "enum": [
                        "biblical", "persian", "second_temple", "hellenistic",
                        "hasmonean", "herodian", "roman", "first_jewish_revolt",
                    ],
                    "description": "Optional editorial period tag",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20,
                    "default": 4,
                    "description": "Maximum passages. Default: 4",
                },
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="search_lexicon",
        annotations=ToolAnnotations(title="Search Lexicon", readOnlyHint=True, destructiveHint=False, idempotentHint=True),
        description="""Search the Greek and Hebrew lexicons by English word, transliteration, or concept.

Returns the matching lexicon entries ranked by relevance — typically several
distinct original-language words that an English term covers (e.g. "love" →
agapē, phileō, erōs), each with its Strong's number, definition, and semantic
range.

Relevant for identifying which original-language terms lie behind an English
word or a biblical concept, and for distinguishing between near-synonyms.""",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search term (English word, transliteration, or concept)"
                },
                "language": {
                    "type": "string",
                    "enum": ["greek", "hebrew"],
                    "description": "Limit search to one language. Omit to search both."
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results to return. Default: 10"
                }
            },
            "required": ["query"]
        }
    ),
    Tool(
        name="get_cross_references",
        annotations=ToolAnnotations(title="Cross References", readOnlyHint=True, destructiveHint=False, idempotentHint=True),
        description="""Retrieve the cross-references for a Bible reference — the passages traditionally read alongside it — or a curated chain of passages for a doctrinal theme.

Two modes:

**By verse reference** (most common). Pass `reference="John 3:16"` (or any
canonical verse) to get the passages historically read alongside it. The
database draws from four scholarly sources, returned in a three-tier ranking:

  **Tier 3 (top, "consensus and curated"):**
    - **CH** — Harrison & Romhild's curated dataset (~58k links, OT-only as
      source). Hand-vetted; high-relevance pairs flagged canonical-direction.
    - **Gage parallel** — the tighter pairings from Warren Gage's John ↔
      Revelation typological reading (Bradley/Gage, John/Rev only).
    - **TSK ≥100 votes** — TSK pairs with crowd-source consensus that strong
      are near-universal cross-references (top ~0.4% of TSK) and break
      through to compete with curated.

  **Tier 2 ("argued and acknowledged"):**
    - **Burnett** — David A. Burnett's argued chain for the Gen 15:5 / Rom
      4:18 "star-like seed" deification reading (JSPL 5.2, 2015). ~30 pairs.
    - **Gage chiastic** — the looser-typology sheet of Bradley/Gage (the
      source spreadsheet labels these "looser connections, just noting").
    - **TSK 20–99 votes** — solid topical links acknowledged across
      commentaries (top ~5%).

  **Tier 1 (long-tail):** TSK <20 votes — surface only when explicitly raising
  `limit` for exhaustive study.

Results typically include the texts the verse quotes, its fulfilment passages,
contested parallel readings, and the later authors who picked the verse up.

**By theme**. Pass `theme="atonement"` (or `salvation_by_grace`, `deity_of_christ`,
`resurrection`, `holy_spirit`, `justification`) to get a hand-curated chain
of foundational passages for that doctrine — relevant for broad theological
questions not anchored to a specific verse.

**Coverage caveat.** TSK is built on R.A. Torrey's 19th-century
index, which catalogues **topical/thematic** connections — not necessarily
direct quotations or verbal allusions. Consequence: a verse with few cross-refs
here is NOT necessarily a verse with few biblical echoes. Famously,
Revelation shows surprisingly few links to OT prophetic books even though
it is saturated with OT symbolism, because Torrey indexed by subject and
Revelation's subject is "apocalyptic". The CH dataset partly compensates
(it leans toward NT-quotes-OT linking), so `source="ch"` may surface a
quotation or allusion the topical index misses, as may `find_similar_passages`
for verbal parallels.

**Adaptive default — `limit` is a cap, not a target.** Default `limit=8`. Rows
are returned in tier-then-strength order, and tier-1 noise (low-vote TSK) is
suppressed by default whenever the verse has at least 3 rows from tier 2+. So:

  - Signal-rich anchors return 6–8 strong refs spanning curated, scholarly,
    and consensus-TSK sources.
  - Signal-poor anchors return only what passes the bar; a short result set
    means the verse has few well-attested links, not that the query failed.

For the long tail, `source="tsk"` returns all TSK rows including tier 1, and
`min_strength=0` sets an explicit floor of zero. Either disables tier-1
suppression; both pair with a higher `limit` (20–30).

**Interpreting the scores.** Each row carries `type` (the dataset),
`relevance` (its native strength signal), and where applicable a `tsk_votes`
side-channel showing the TSK count for that pair. The scales differ by
dataset:

  TSK vote scale (full corpus distribution):
    ≥ 500 votes  — extraordinary; near-universal cross-reference (top 0.01%, only 35 pairs)
    100-499      — very strong; the link tradition reflexively makes (top 0.4%)
     50-99       — strong; well-established parallel (top 1.3%)
     20-49       — solid; real connection acknowledged across commentaries (top 5%)
     10-19       — moderate; one of many recognised links (top 12%)
      5-9        — weak; thematic stretch, use with caution (top 33%)
      2-4        — very weak; mostly noise floor (62% of TSK)
      0-1        — noise

  CH (curated — all CH refs carry signal; the tag indicates weight):
    "canonical direction" (rel=3 or 2) — Harrison's flag for the canonical
        direction of the pair, often part of a thematic circle (top 78% of CH)
    no tag (rel=0) — present in CH but unflagged (still hand-curated)

  Gage (John ↔ Revelation typology):
    relevance=3 ("parallel" tier) — tighter pairings from the parallel-reading
        of John 1 ↔ Revelation 1
    relevance=1 ("chiastic" tier) — looser thematic echoes across the full
        John-Revelation chiasm; the source spreadsheet flags these as
        "looser connections, just noting"
    The `note` field carries the thematic tags + commentary + per-row
    attribution (Bradley vs Gage). Treat as canonical-typology, not topical.

  Burnett (single-paper argued chain):
    All Burnett rows are at relevance=5 by convention — they're explicit
    claims from one scholar's published argument, not graded by strength.
    The `note` field carries the JSPL citation and which step of the argument
    the pair belongs to. They represent a single scholarly proposal rather
    than consensus.

A result whose strongest row has only 5–15 votes indicates a verse the topical
index does not treat as a major thematic anchor — a materially weaker signal
than a 200-vote parallel. For such verses `source="ch"` (Harrison's curated
set, which leans toward NT-quotes-OT links) and `find_similar_passages`
(verbal/semantic parallels Torrey did not index) cover different ground.

The `source` parameter restricts results to a single dataset — useful when CH
alone gives too little coverage for an obscure verse, or when the dense TSK
long-tail is wanted.""",
        inputSchema={
            "type": "object",
            "properties": {
                "reference": {
                    "type": "string",
                    "description": "Bible reference to find cross-references for (e.g. 'John 3:16', 'Rom 3:23')."
                },
                "theme": {
                    "type": "string",
                    "description": "Theological theme. One of: salvation_by_grace, deity_of_christ, atonement, resurrection, holy_spirit, justification."
                },
                "source": {
                    "type": "string",
                    "enum": ["ch", "tsk", "gage", "burnett"],
                    "description": "Optional dataset filter when using `reference`. 'ch' = Harrison/Romhild curated; 'tsk' = Treasury of Scripture Knowledge; 'gage' = Gage/Bradley John↔Revelation typology; 'burnett' = Burnett's Gen 15:5 / Rom 4:18 deification chain (JSPL 5.2). Default: all four, ranked CH/Gage > Burnett > TSK."
                },
                "limit": {
                    "type": "integer",
                    "description": "Cap on rows returned (not a target). Default 8. The returned count may be smaller when the verse has fewer rows above the noise floor. Values of 20–30 combined with `source='tsk'` or `min_strength=0` return the long tail."
                },
                "min_strength": {
                    "type": "integer",
                    "description": "Strength floor for TSK refs (vote count). TSK pairs below this are excluded; CH/Gage/Burnett refs are exempt from this floor, being hand-curated or scholarly-argued. Setting this also disables the default tier-1 suppression, since it specifies an explicit floor. Sensible thresholds: 0 (include long-tail), 5 (drops bottom ~75%% of TSK), 20 (top ~5%% only). Default: tier-1 suppressed when verse is signal-rich."
                }
            }
        }
    ),
    Tool(
        name="lookup_name",
        annotations=ToolAnnotations(title="Lookup Name", readOnlyHint=True, destructiveHint=False, idempotentHint=True),
        description="""Look up general information about a biblical person, place, or thing by name — Abraham, David, Bethlehem, and so on.

Covers 4,000+ biblical persons and 1,000+ places. Returns the entry's original-language
name, description, key verse references, ACAI annotations where available (variant
names, roles, reference and speech counts), and its immediate relationships:

- **Parents** — one generation back (e.g. David → Jesse)
- **Children** — one generation forward (e.g. Abraham → Isaac)
- **Siblings** (e.g. Moses ↔ Aaron ↔ Miriam)
- **Spouse** (e.g. Ruth ↔ Boaz)

Relevant for identifying a named figure or location and for the immediate
family and reference context around it. Multi-generation lineages are covered by
`explore_genealogy`, a person's life events by `explore_person_events`, and a
location's full history by `explore_place`.""",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name to look up (e.g., 'David', 'Jerusalem', 'Abraham')"
                },
                "type": {
                    "type": "string",
                    "enum": ["person", "place", "thing"],
                    "description": "Filter by type. Omit to search all types."
                }
            },
            "required": ["name"]
        }
    ),
    Tool(
        name="parse_morphology",
        annotations=ToolAnnotations(title="Parse Morphology", readOnlyHint=True, destructiveHint=False, idempotentHint=True),
        description="""Explain a morphological/grammatical parsing code.

For Greek: Robinson codes (e.g., 'V-AAI-3S' = Verb, Aorist, Active, Indicative, 3rd person, Singular)
For Hebrew: Westminster/OpenScriptures codes

Returns full grammatical explanation including part of speech, 
person, number, tense, voice, mood, case, and gender where applicable.""",
        inputSchema={
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Morphology code to parse (e.g., 'V-AAI-3S', 'N-GSF')"
                },
                "language": {
                    "type": "string",
                    "enum": ["greek", "hebrew"],
                    "description": "Language of the code. Default: greek"
                }
            },
            "required": ["code"]
        }
    ),
    Tool(
        name="search_by_strongs",
        annotations=ToolAnnotations(title="Search by Strong's Number", readOnlyHint=True, destructiveHint=False, idempotentHint=True),
        description="""Search by Strong's number for every verse where that word appears.

Takes a Strong's number (typically obtained from `word_study` or
`search_lexicon`) and returns the passages containing that Greek or Hebrew word,
showing how biblical authors used it in context and the range of senses it
carries across occurrences.""",
        inputSchema={
            "type": "object",
            "properties": {
                "strongs": {
                    "type": "string",
                    "description": "Strong's number (e.g., 'G26', 'H430')"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum verses to return. Default: 20"
                }
            },
            "required": ["strongs"]
        }
    ),
    Tool(
        name="find_similar_passages",
        annotations=ToolAnnotations(title="Find Similar Passages", readOnlyHint=True, destructiveHint=False, idempotentHint=True),
        description="""Find passages with similar semantic content to a given Bible verse.

Takes a verse reference (one with a pre-computed embedding) and returns
semantically similar passages ranked by similarity score. Matching is by vector
embedding rather than shared vocabulary, so it surfaces connections that explicit
cross-reference indexes and word searches miss.

Typical results:
- Daniel 7:13-14 (Son of Man vision) → Revelation 1:7, 14:14 (similar imagery)
- Exodus 12:1-13 (Passover) → John 1:29, 1 Corinthians 5:7 (Lamb imagery)
- Isaiah 53:4-6 (Suffering Servant) → 1 Peter 2:24-25 (echoes of Isaiah)
- Proverbs wisdom themes → James practical wisdom

**What the similarity score does and does not mean.** The score measures
proximity in embedding space, which is not evidence of a theological or
authorial connection. Two passages can share vocabulary and imagery while
differing in genre, historical setting, referent, and authorial intent. The
returned set mixes several distinct phenomena that the score cannot tell apart:
direct quotation (an explicit OT citation in the NT), deliberate allusion,
shared tradition (common Jewish or Christian concepts), and coincidental
verbal overlap between unrelated texts.

Establishing which of these applies to a given pair requires the passages'
genre, historical setting, and literary context — `lookup_verse` returns genre
background, `get_study_notes` and `get_ane_context` cover context and original
audience, and `get_cross_references` indicates whether the link is attested in
the cross-reference tradition.""",
        inputSchema={
            "type": "object",
            "properties": {
                "reference": {
                    "type": "string",
                    "description": "Bible reference to find similar passages for (e.g., 'John 3:16', 'Daniel 7:13')"
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of similar passages to return. Default: 10"
                }
            },
            "required": ["reference"]
        }
    ),
    # =========================================================================
    # Graph tools (Theographic Bible Metadata)
    # =========================================================================
    Tool(
        name="explore_genealogy",
        annotations=ToolAnnotations(title="Explore Genealogy", readOnlyHint=True, destructiveHint=False, idempotentHint=True),
        description="""Trace a genealogy: a biblical person's ancestors and/or descendants across multiple generations of lineage.

Traverses genealogical data covering 1,100+ biblical persons. Returns a family
tree with generation numbers and relationship types, plus a Mermaid diagram of
the tree.

Covers questions such as tracing the line from Abraham to David, a person's
tribal ancestry, the Messianic lineage, or how a figure connects into a known
line. For a single generation (e.g. one person's father), `lookup_name` returns
immediate family without the traversal.""",
        inputSchema={
            "type": "object",
            "properties": {
                "person": {
                    "type": "string",
                    "description": "Name of the person (e.g., 'David', 'Abraham', 'Jesus')"
                },
                "direction": {
                    "type": "string",
                    "enum": ["ancestors", "descendants", "both"],
                    "description": "Direction to trace. Default: both"
                },
                "generations": {
                    "type": "integer",
                    "description": "Maximum generations to trace. Default: 5"
                }
            },
            "required": ["person"]
        }
    ),
    Tool(
        name="people_in_passage",
        annotations=ToolAnnotations(title="People in Passage", readOnlyHint=True, destructiveHint=False, idempotentHint=True),
        description="""List the people, places, and events mentioned in a Bible passage.

Returns the entities recorded for a chapter or verse in the Theographic Bible
Metadata — for example, Genesis 22 returns Abraham, Isaac, the angel of the LORD,
and Moriah; Acts 15 returns Paul, Barnabas, James, Jerusalem, and Antioch.

Relevant for establishing the cast and setting of a narrative passage. Related
tools: `graph_enriched_search` is verse-level only but adds the verse text and
family relationships for each person found.""",
        inputSchema={
            "type": "object",
            "properties": {
                "reference": {
                    "type": "string",
                    "description": "Bible reference - chapter (e.g., 'Romans 8') or verse (e.g., 'Genesis 22:1')"
                }
            },
            "required": ["reference"]
        }
    ),
    Tool(
        name="explore_person_events",
        annotations=ToolAnnotations(title="Explore Person Events", readOnlyHint=True, destructiveHint=False, idempotentHint=True),
        description="""Retrieve the recorded events of a biblical person's life in chronological order.

Returns each event with its location and date where known, plus a Mermaid
timeline diagram. Moses returns birth, burning bush, exodus, Sinai, and death on
Nebo; Paul returns conversion, missionary journeys, imprisonment, and Rome.

This is the only tool covering event sequence and dating for a person. Related
tools: `lookup_name` for identity and relationships, `explore_genealogy` for
lineage.""",
        inputSchema={
            "type": "object",
            "properties": {
                "person": {
                    "type": "string",
                    "description": "Name of the person (e.g., 'Moses', 'Paul', 'David')"
                }
            },
            "required": ["person"]
        }
    ),
    Tool(
        name="explore_place",
        annotations=ToolAnnotations(title="Explore Place", readOnlyHint=True, destructiveHint=False, idempotentHint=True),
        description="""Retrieve the full biblical history of a place.

Returns the events recorded there, the people born or who died there, and
geographic data, spanning all biblical periods — plus a Mermaid network diagram.
Jerusalem returns events from Salem/Melchizedek through David, Solomon, the
exile, and Jesus; Mount Sinai returns the burning bush, the giving of the law,
the golden calf, and Elijah.

Relevant for questions about biblical geography or a location's significance
across salvation history. Related tool: `lookup_name` with type="place" returns
basic place info and immediate connections only.""",
        inputSchema={
            "type": "object",
            "properties": {
                "place": {
                    "type": "string",
                    "description": "Name of the place (e.g., 'Jerusalem', 'Bethlehem', 'Egypt')"
                }
            },
            "required": ["place"]
        }
    ),
    Tool(
        name="find_connection",
        annotations=ToolAnnotations(title="Find Connection", readOnlyHint=True, destructiveHint=False, idempotentHint=True),
        description="""Trace the shortest family relationship path between two biblical people.

Walks parent, child, sibling, and spouse relationships in the biblical
genealogies to find a connecting path, and returns it as a Mermaid flowchart.
Ruth and David return Ruth → Obed → Jesse → David; Abraham and Moses trace
through Levi. Where no family connection exists, that is reported.

Relevant for questions about how two named figures relate. Related tool:
`explore_genealogy` returns one person's ancestors or descendants rather than a
path between two people.""",
        inputSchema={
            "type": "object",
            "properties": {
                "person1": {
                    "type": "string",
                    "description": "First person's name (e.g., 'Abraham')"
                },
                "person2": {
                    "type": "string",
                    "description": "Second person's name (e.g., 'David')"
                }
            },
            "required": ["person1", "person2"]
        }
    ),
    Tool(
        name="graph_enriched_search",
        annotations=ToolAnnotations(title="Graph Enriched Search", readOnlyHint=True, destructiveHint=False, idempotentHint=True),
        description="""Retrieve a comprehensive enriched view of a single verse: its text plus all people, places, events, and family relationships.

Returns the verse text, the people, places, and events mentioned in it, and the
family relationships of each person found. For 'Matthew 1:1' that is the verse
text, Jesus, David, and Abraham with their relationships, and the associated
places and events.

Combines what `lookup_verse` and `people_in_passage` return separately. Verse
level only; `people_in_passage` also accepts chapters but returns entity lists
without verse text or relationships.""",
        inputSchema={
            "type": "object",
            "properties": {
                "reference": {
                    "type": "string",
                    "description": "Bible verse reference (e.g., 'Genesis 22:1', 'Matthew 1:1')"
                }
            },
            "required": ["reference"]
        }
    ),
    # =========================================================================
    # Aquifer content tools
    # =========================================================================
    Tool(
        name="get_study_notes",
        annotations=ToolAnnotations(title="Study Notes", readOnlyHint=True, destructiveHint=False, idempotentHint=True),
        description="""Get scholarly study notes and translation notes for a Bible verse or chapter.

Returns combined commentary from:
- **Tyndale Study Notes**: Concise, verse-level scholarly commentary (66 books)
- **UW Translation Notes**: Translator-focused commentary with linguistic insights
- **SIL Translator Notes**: Additional translation and cultural context

Relevant for published commentary on a specific verse, difficult passages,
translation and cultural background, and chapter-level overviews of themes and
context. The content is published scholarship, quoted as-is with source
attribution. For journal articles, see `list_research_sources`.""",
        inputSchema={
            "type": "object",
            "properties": {
                "reference": {
                    "type": "string",
                    "description": "Bible reference (e.g., 'John 3:16', 'Genesis 1', 'Romans 8:28')"
                },
                "chapter_only": {
                    "type": "boolean",
                    "description": "If true, return all notes for the chapter. Default: false (verse-specific)"
                }
            },
            "required": ["reference"]
        }
    ),
    Tool(
        name="get_bible_dictionary",
        annotations=ToolAnnotations(title="Bible Dictionary", readOnlyHint=True, destructiveHint=False, idempotentHint=True),
        description="""Look up a topic in the Tyndale Bible Dictionary.

Contains 500+ topical articles covering:
- Biblical people and places
- Theological concepts and doctrines
- Cultural practices and customs
- Historical background
- Archaeological findings

Relevant for background on a biblical topic, historical or cultural context, a
detailed article on a person, place, or concept, or a published definition of a
theological term.

Returns the full dictionary article with cross-references.""",
        inputSchema={
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "Topic to look up (e.g., 'Abraham', 'covenant', 'baptism', 'Pharisees')"
                }
            },
            "required": ["topic"]
        }
    ),
    Tool(
        name="get_key_terms",
        annotations=ToolAnnotations(title="Key Terms", readOnlyHint=True, destructiveHint=False, idempotentHint=True),
        description="""Look up a key theological term in the FIA Key Terms database.

Contains 200+ carefully defined theological and biblical terms with:
- Clear definitions accessible to translators
- Biblical usage and context
- Cross-references to related terms
- Translation guidance

Relevant for a precise definition of a theological term (agape, atonement,
justification, and similar), how a concept is used across Scripture, a
translation-oriented explanation, or cross-references to related concepts.""",
        inputSchema={
            "type": "object",
            "properties": {
                "term": {
                    "type": "string",
                    "description": "Theological term to look up (e.g., 'agape', 'atonement', 'covenant', 'grace')"
                }
            },
            "required": ["term"]
        }
    ),
    Tool(
        name="get_ane_context",
        annotations=ToolAnnotations(title="Ancient Near East Context", readOnlyHint=True, destructiveHint=False, idempotentHint=True),
        description="""Get Ancient Near East (ANE) cultural and historical background for a biblical passage.

The biblical authors and their audiences lived in the Ancient Near East with fundamentally
different assumptions about cosmology, social structure, religion, law, and daily life.
This tool retrieves structured ANE contextual data on what the text meant
to its original audience.

Relevant to passages involving:
- Creation, flood, or cosmological texts (three-tier universe, cosmic waters)
- Encountering divine council, heavenly assembly, or "sons of God" language
- Reading about the serpent, Eden, the fall, or spiritual warfare passages
- Encountering references to temples, sacrifices, or religious practices
- Studying meal, table, or eating passages (fellowship, allegiance, covenant meals)
- Encountering household, family, or father language applied to God
- Reading about covenants, treaties, or legal codes (suzerainty treaties, lex talionis)
- Studying honor/shame dynamics in Gospels or Epistles
- Understanding marriage customs, family structures, or inheritance laws
- Reading about warfare, kingship, or imperial contexts
- Studying Levitical purity, clean/unclean categories, or scapegoat rituals
- Encountering literary forms (chiasm, inclusio, lament, oracle)
- Needing background on daily life, agriculture, or material culture
- Encountering "soul," "spirit," nephesh, or ruach language (Hebrew vs. Greek anthropology)
- Any passage where modern Western assumptions might obscure the ANE meaning
- Needing the interpretive methodology (derivation hierarchy, confidence calibration)

13 dimensions: cosmology_worldview, religious_practices, social_structure, legal_covenant,
political_imperial, economic_life, literary_conventions, warfare_military,
daily_life_material_culture, death_afterlife, gender_family, education_literacy,
ane_methodology

9 periods: patriarchal, exodus_conquest, judges_early_monarchy, united_monarchy,
divided_monarchy, assyrian_babylonian, persian, hellenistic, roman

With no arguments, returns the available dimensions and periods. With a
reference alone, returns all ANE context matching that passage. The dimension
and period parameters narrow the result set. The dimension 'ane_methodology'
returns the derivation hierarchy, confidence calibration, and methodological
limits that apply to ANE parallels generally.""",
        inputSchema={
            "type": "object",
            "properties": {
                "reference": {
                    "type": "string",
                    "description": "Bible reference (e.g., 'Genesis 1:1', 'Deuteronomy 5:1', 'Matthew 5:1')"
                },
                "dimension": {
                    "type": "string",
                    "description": "ANE dimension to filter by (e.g., 'cosmology_worldview', 'legal_covenant')",
                    "enum": [
                        "cosmology_worldview", "religious_practices", "social_structure",
                        "legal_covenant", "political_imperial", "economic_life",
                        "literary_conventions", "warfare_military", "daily_life_material_culture",
                        "death_afterlife", "gender_family", "education_literacy",
                        "ane_methodology"
                    ]
                },
                "period": {
                    "type": "string",
                    "description": "Historical period to filter by",
                    "enum": [
                        "patriarchal", "exodus_conquest", "judges_early_monarchy",
                        "united_monarchy", "divided_monarchy", "assyrian_babylonian",
                        "persian", "hellenistic", "roman"
                    ]
                },
                "detail_level": {
                    "type": "string",
                    "description": "Output detail level. 'brief' = title + summary + significance for all entries. 'standard' (default) = full detail for direct chapter matches, brief for broad/whole-book matches. 'full' = full detail for all entries.",
                    "enum": ["brief", "standard", "full"],
                    "default": "standard"
                }
            }
        }
    ),
    # =========================================================================
    # Theological scholarship tools
    # =========================================================================
    Tool(
        name="get_theology_context",
        annotations=ToolAnnotations(title="Theological Scholarship", readOnlyHint=True, destructiveHint=False, idempotentHint=True),
        description="""Get theological scholarship context for a Bible passage or theme.

Returns scholarly content from multiple authors (Heiser, Bradley, etc.) with verse mappings and theme links. When no author is specified, returns all scholars' content for the query — allowing side-by-side comparison.

Coverage by topic, with the author and theme keys that hold it:
- The divine council (Psalm 82, Deuteronomy 32, Job 1-2) — Heiser
- Sons of God / bene elohim (Genesis 6, Job 38) — Heiser
- The Angel of Yahweh / two-powers theology — Heiser
- Nephilim, Rephaim, and the giant clans — Heiser
- The nachash / serpent in Eden (Genesis 3) — Heiser, Bradley
- Cosmic geography and spiritual warfare — Heiser
- Deuteronomy 32 worldview / allotment of nations — Heiser, Bradley
- Salvation, soteriology, the gospel, conversion, atonement — Bradley (theme: domain_transfer)
- The Fall, Genesis 3, sin entering the world — Bradley (theme: nested_household, corporate_headship)
- Life/death, light/darkness, righteousness/sin, love/pride and other biblical binary pairs — Bradley (theme: binary_hierarchy)
- Satan, the devil, spiritual warfare, the enemy, two kingdoms — Bradley (theme: pater_familias_binary)
- The sin-death connection, wages of sin, power of death — Bradley (theme: sin_death_satan_chain)
- Corporate solidarity, "in Adam" / "in Christ", federal headship — Bradley (theme: corporate_headship)
- Satan's imitation of God's kingdom, counterfeit worship — Bradley (theme: rival_counterfeits)
- Acts 26:17-18 and Paul's commission — Bradley (theme: domain_transfer)
- Penal substitution, propitiation, definite/particular atonement, imputed righteousness, justification — Owen, Stott (themes: penal_substitution, propitiation, definite_atonement, justification_imputation)
- Mortification of indwelling sin, sanctification, communion with God, the glory of Christ — Owen (themes: mortification_of_sin, sanctification, communion_with_god, glory_of_christ)
- Christ's high priesthood, the new covenant, Hebrews — Owen (themes: high_priesthood, new_covenant)
- The cross of Christ, the four images of salvation, the self-substitution of God — Stott (theme: atonement_models, reconciliation)
- The Sermon on the Mount, kingdom ethics, the Holy Spirit's fullness (baptism vs filling) — Stott (themes: kingdom_ethics, holy_spirit_work)
- Genesis 1 and science, creation, the days debate — Lennox (theme: creation_genesis)
- Providence, God's sovereignty and human freedom, the problem of evil (Joseph, Daniel) — Lennox (themes: providence, divine_sovereignty_freedom)
- Faithful witness in a hostile culture, Daniel — Lennox (theme: faithful_witness)

Each entry includes a Source URL when the source is freely available online: Owen's public-domain text (CCEL chapter pages; Monergism volume PDFs for the Exposition of Hebrews), Heiser's papers and Naked Bible podcast transcripts, and Burnett's article series. Stott, Lennox, and Bradley entries have no URL.

Query by verse reference, theme key, and/or author. For other authors, see
`list_research_sources`.""",
        inputSchema={
            "type": "object",
            "properties": {
                "reference": {
                    "type": "string",
                    "description": "Bible reference (e.g., 'Psalm 82:1', 'Genesis 6:2', 'Acts 26:18', 'John 8:44')"
                },
                "theme": {
                    "type": "string",
                    "description": "Theme key (e.g., 'divine_council', 'pater_familias_binary', 'domain_transfer', 'sin_death_satan_chain')"
                },
                "author": {
                    "type": "string",
                    "description": "Filter by author: 'heiser', 'bradley', 'owen', 'stott', 'lennox'. Omit to get all scholars' content."
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum entries to return. Default: 10"
                }
            }
        }
    ),
    Tool(
        name="get_torah_weave",
        annotations=ToolAnnotations(title="Torah Weave Structural Parallels", readOnlyHint=True, destructiveHint=False, idempotentHint=True),
        description="""Get the structurally-paired verses for a Torah passage under Moshe Kline's Woven Torah hypothesis.

The Torah is organised as 86 two-dimensional literary units (Genesis–Deuteronomy). Each unit is a grid of cells arranged in rows and columns, and cells are deliberately paired with one another across rows (horizontal partners) and down columns (vertical partners). A verse's weave partners are therefore the passages the hypothesis holds the Torah's author(s) intended to be read alongside it.

Relevant to any passage in Genesis, Exodus, Leviticus, Numbers, or Deuteronomy —
particularly for identifying which verses are structurally paired with a
passage, for suspected deliberate interweaving (doublets, creation/flood, law
parallels), and for comparative readings where the pairing claimed is
compositional rather than thematic.

WHAT IT RETURNS:
- The literary unit the verse sits in (title, format, type, verse span)
- The cell the verse occupies (row/column label + verse range)
- Horizontal partner cells (same row, same subdivision, different column)
- Vertical partner cells (same column, same subdivision, different row)
- Sibling cells (same row and column, adjacent subdivisions)
- A short explanation of what each direction of pairing means under Kline's method

The output is a set of structural pointers — verse ranges and their pairing
direction — not pre-written interpretation. The text of the partner cells is
not included; `lookup_verse` returns it. Under Kline's method horizontal
partners are symmetric parallels (same divine-name register, different thematic
tracks) and vertical partners are a progression through registers along a single
thematic track; the thematic content of each column is not labelled in Kline's
dataset.

Only Torah books (Genesis through Deuteronomy) have weave data. Source: Moshe Kline, chaver.com, CC BY 4.0.""",
        inputSchema={
            "type": "object",
            "properties": {
                "reference": {
                    "type": "string",
                    "description": "Bible reference in Genesis–Deuteronomy (e.g., 'Genesis 6:1', 'Exodus 14:21', 'Leviticus 19:18')"
                }
            },
            "required": ["reference"]
        }
    ),
    Tool(
        name="get_textual_variant",
        annotations=ToolAnnotations(title="Textual Variant (MT vs LXX/DSS)", readOnlyHint=True, destructiveHint=False, idempotentHint=True),
        description="""Retrieve a textual-variant record without conflating evidence and interpretation.

WHAT IT RETURNS for a given verse reference:
- Manuscript evidence: distinct readings and the manuscript witnesses attached to each reading
- NT citation evidence: New Testament quotations of the verse, kept apart from manuscript copies
- Indirect evidence: material bearing on a reading's text form without witnessing this verse (e.g. a scroll attesting a short edition elsewhere in the book)
- Not preserved in: corpora with no surviving copy of the verse (e.g. no Dead Sea Scroll)
- Critical judgments: text-critical conclusions that carry a source citation
- Unsourced dataset summary: uncited editorial summaries, labelled as not verified against published text-critical scholarship
- Theological interpretations: explicitly labelled interpretations, never presented as manuscript evidence
- Author-specific claims: named-author arguments, separate from critical judgments
- Translation decisions: a translation's selected reading and rationale
- NT quotation alignment: separately catalogued links where an NT quotation follows an LXX form
- Translation and interpretation notes: verses where the witnesses agree with the MT but the reading or rendering is contested (e.g. divine-council language at Psalm 82:6); shown separately, never as a variant

Sections with nothing catalogued are omitted. Each manuscript-variant witness
keeps the dataset's raw support label. A witness date describes the witness
record; it does not by itself date the underlying reading.

Relevant where a New Testament quotation does not match the Old Testament verse
it quotes (e.g. why Hebrews 10:5 says "a body you prepared" where Psalm 40:6 says
"ears you have dug"), and to questions about how the Hebrew, Greek, and Qumran
textual traditions differ at a specific verse.

`lookup_verse` notes when a verse has a catalogued variant case or a quotation
alignment.""",
        inputSchema={
            "type": "object",
            "properties": {
                "reference": {
                    "type": "string",
                    "description": "A single verse — either the OT verse (e.g., 'Psalm 40:6', 'Deuteronomy 32:43', 'Isaiah 61:1') or the NT verse that quotes it (e.g., 'Hebrews 10:5', 'Hebrews 1:6', 'Luke 4:18'). Both sides return the same variant case."
                }
            },
            "required": ["reference"]
        }
    ),
    Tool(
        name="list_research_sources",
        annotations=ToolAnnotations(title="Research Sources", readOnlyHint=True, destructiveHint=False, idempotentHint=True),
        description="""Find free, reliable places to look for scholarly articles, primary texts, and commentary beyond this server's data, before a general web search: open journals, digital libraries, and text archives covering other authors and traditions, church fathers, rabbinic texts, Dead Sea Scrolls, Septuagint studies, and public-domain books. Each listing gives coverage, perspective, and access terms; with a `query`, sources that support it get a ready-to-open search link. Places to look, not endorsements.""",
        inputSchema={
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "Coverage tag or source name, matched loosely (e.g. 'rabbinic', 'church fathers', 'dead sea scrolls', 'septuagint')"
                },
                "query": {
                    "type": "string",
                    "description": "Search terms for each source's search link (e.g. 'Psalm 82')"
                },
                "perspective": {
                    "type": "string",
                    "description": "Jewish, Catholic, Reformed, evangelical, academic, multi-tradition, or single-author"
                },
                "limit": {
                    "type": "integer",
                    "description": f"Maximum sources to return. Default: {RESEARCH_SOURCES_DEFAULT_LIMIT}"
                }
            }
        }
    ),
]


# =========================================================================
# Format functions — Theological scholarship
# =========================================================================

# Stated on every theology result so the nature of the content is explicit in the
# output itself: these cells are original summary prose, not reproduced text.
_THEOLOGY_PROVENANCE = (
    "*Provenance: these entries are original summaries of the named author's "
    "publicly available research and teaching, written for this database. They "
    "are not reproduced text from the authors' works. Owen (d. 1683) is in the "
    "public domain and is cited by work, with a link to the free text.*"
)


def format_theology_context(entries: list[dict], themes: list[dict] | None = None) -> str:
    """Format theological scholarship entries for display."""
    if not entries:
        return "No theological scholarship found for this query."

    lines = []
    for entry in entries:
        lines.append(f"### {entry.get('title') or entry.get('chapter_or_episode', 'Untitled')}")

        # source_work labels already lead with the author's name ("Stott on
        # Romans", "Owen — Communion with God"), so don't repeat it.
        author = entry.get("source_author", "") or ""
        work = entry.get("source_work", "") or ""
        label = f"*{work}*" if work.lower().startswith(author.lower()) and author else f"{author} — *{work}*"
        if entry.get("source_type"):
            label += f" ({entry['source_type']})"
        lines.append(f"**Source**: {label}")
        if entry.get("url"):
            lines.append(f"**Source URL**: {entry['url']}")
        if entry.get("chapter_or_episode"):
            lines.append(f"**Chapter/Episode**: {entry['chapter_or_episode']}")
        if entry.get("matched_ref"):
            lines.append(f"**Matched Reference**: {entry['matched_ref']}")
        if entry.get("themes"):
            lines.append(f"**Themes**: {entry['themes']}")
        lines.append("")

        if entry.get("content_summary"):
            lines.append(entry["content_summary"])
            lines.append("")

        if entry.get("content_detail"):
            lines.append("**Detail**:")
            lines.append(_truncate(entry["content_detail"], 2000))
            lines.append("")

        lines.append("---")
        lines.append("")

    if themes:
        lines.append("## Available Themes")
        for t in themes:
            count = t.get("entry_count", 0)
            lines.append(f"- **{t['theme_key']}** ({t['theme_label']}): {t['description'][:100]} [{count} entries]")
        lines.append("")

    lines.append(_THEOLOGY_PROVENANCE)
    lines.append("")

    return "\n".join(lines)



def format_theology_themes(themes: list[dict]) -> str:
    """Format list of all theological themes."""
    lines = ["## Theological Themes\n"]
    for t in themes:
        count = t.get("entry_count", 0)
        lines.append(f"### {t['theme_label']} (`{t['theme_key']}`)")
        lines.append(f"{t['description']}")
        if t.get("parent_theme"):
            lines.append(f"**Parent theme**: {t['parent_theme']}")
        lines.append(f"**Entries**: {count}")
        lines.append("")

    return "\n".join(lines)


# =========================================================================
# Research sources — curated open repositories (research_sources.json)
# =========================================================================

RESEARCH_SOURCES_PATH = Path(__file__).with_name("research_sources.json")

# Topic words an agent is likely to use that differ from the catalogue's tags.
_TOPIC_ALIASES = {
    "dss": "dead sea scrolls",
    "qumran": "dead sea scrolls",
    "lxx": "septuagint",
    "patristic": "church fathers",
    "patristics": "church fathers",
    "talmud": "rabbinic",
    "midrash": "rabbinic",
    "mishnah": "rabbinic",
    "old testament": "hebrew bible",
    "tanakh": "hebrew bible",
    "pseudepigrapha": "second temple",
    "journal": "biblical studies articles",
    "journals": "biblical studies articles",
    "articles": "biblical studies articles",
    "ane": "ancient near east",
    "manuscripts": "textual criticism",
}

_RESEARCH_DISCLAIMER = (
    "*These are places to look, not endorsements. Each source is listed for what it "
    "holds, with its perspective stated so it can be weighed; check claims against "
    "the primary texts.*"
)


@lru_cache(maxsize=1)
def load_research_sources() -> tuple[dict, ...]:
    """Load the curated research-source catalogue shipped with the package."""
    with RESEARCH_SOURCES_PATH.open(encoding="utf-8") as f:
        return tuple(json.load(f))


def research_search_url(source: dict, query: str) -> str | None:
    """Fill a source's search template with the URL-encoded query, if it has one."""
    template = source.get("search_url_template")
    if not template:
        return None
    return template.replace("{query}", quote_plus(query.strip()))


def _normalise_topic(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9\s]", " ", text.lower()).split())


def _topic_score(source: dict, topic: str) -> int:
    """2 = topic names a coverage tag or the source; 1 = every topic word appears; 0 = no match."""
    tags = [tag.lower() for tag in source["coverage"]]
    names = _normalise_topic(f"{source['name']} {source['key'].replace('_', ' ')}")
    wanted = {topic} | {
        tag for phrase, tag in _TOPIC_ALIASES.items() if re.search(rf"\b{re.escape(phrase)}\b", topic)
    }
    for phrase in wanted:
        if any(phrase in tag or tag in phrase for tag in tags) or phrase in names:
            return 2
    haystack = " ".join(tags) + " " + names
    words = [word for word in topic.split() if len(word) > 2]
    if words and all(word in haystack for word in words):
        return 1
    return 0


def find_research_sources(topic: str | None = None, perspective: str | None = None) -> list[dict]:
    """Filter the catalogue by perspective and loosely by topic, strongest topic matches first."""
    sources = list(load_research_sources())
    if perspective and perspective.strip():
        wanted = perspective.strip().lower()
        sources = [s for s in sources if wanted in s["perspective"].lower()]
    normalised = _normalise_topic(topic or "")
    if normalised:
        scored = [(_topic_score(s, normalised), s) for s in sources]
        scored = [pair for pair in scored if pair[0]]
        scored.sort(key=lambda pair: -pair[0])  # stable: catalogue order within a score
        sources = [s for _, s in scored]
    return sources


def format_research_sources(
    sources: list[dict],
    total: int,
    topic: str | None = None,
    query: str | None = None,
    perspective: str | None = None,
) -> str:
    """Format catalogue entries, with a search link per source when a query is given."""
    filters = [f"{label}: {value}" for label, value in (
        ("topic", topic), ("perspective", perspective), ("query", query)) if value]
    header = "## Research Sources"
    if filters:
        header += " (" + "; ".join(filters) + ")"
    lines = [header, "", _RESEARCH_DISCLAIMER, ""]

    if not sources:
        catalogue = load_research_sources()
        perspectives = sorted({s["perspective"] for s in catalogue})
        tags = sorted({tag for s in catalogue for tag in s["coverage"]})
        lines.append("No sources match these filters.")
        lines.append(f"- Perspectives: {', '.join(perspectives)}")
        lines.append(f"- Coverage tags: {', '.join(tags)}")
        return "\n".join(lines)

    shown = f"Showing {len(sources)} of {total} matching sources." if total > len(sources) else f"{total} matching sources."
    lines.extend([shown, ""])
    for source in sources:
        lines.append(f"### {source['name']}")
        lines.append(source["url"])
        lines.append(source["description"])
        lines.append(f"- **Coverage**: {', '.join(source['coverage'])}")
        lines.append(f"- **Perspective**: {source['perspective']}")
        lines.append(f"- **Access**: {source['access']}")
        if query:
            link = research_search_url(source, query)
            if link:
                lines.append(f"- **Search**: {link}")
            else:
                lines.append("- **Search**: no linkable search; browse or use the site's own search")
        lines.append("")
    # The oldest date is the one a reader can rely on for every listing shown.
    lines.append(f"*Listings verified on or after {min(s['last_verified'] for s in sources)}.*")
    return "\n".join(lines)


def format_lexicon_entry(entry: dict) -> str:
    """Format a lexicon entry for display.

    Shows separate sections for brief and full definitions when both exist.
    Greek entries with TFLSJ data show "Full LSJ Definition".
    Hebrew entries with BDB data show "Full BDB Definition".
    """
    lines = []

    # Header
    lines.append(f"## {entry['strongs']} - {entry['word']}")
    lines.append(f"**Transliteration**: {entry['transliteration']}")
    if entry.get('pronunciation'):
        lines.append(f"**Pronunciation**: {entry['pronunciation']}")
    lines.append(f"**Language**: {entry['language'].title()}")
    lines.append("")

    short_def = entry.get('short_definition', '')
    full_def = entry.get('full_definition', '')

    if short_def and full_def and short_def != full_def:
        # Show both brief and full definitions
        lines.append("### Brief Definition")
        lines.append(short_def)
        lines.append("")

        # Label based on language
        if entry.get('language') == 'greek':
            label = "Full LSJ Definition"
        elif entry.get('language') == 'hebrew':
            label = "Full BDB Definition"
        else:
            label = "Full Definition"

        lines.append(f"### {label}")
        lines.append(_truncate(full_def, 3000, "\n\n*[Definition truncated — full entry available in the lexicon]*"))
        lines.append("")
    elif full_def:
        lines.append("### Definition")
        lines.append(_truncate(full_def, 3000, "\n\n*[Definition truncated]*"))
        lines.append("")
    elif short_def:
        lines.append("### Definition")
        lines.append(short_def)
        lines.append("")
    else:
        lines.append("### Definition")
        lines.append("No definition available.")
        lines.append("")

    # Etymology
    if entry.get('etymology'):
        lines.append("### Etymology")
        lines.append(entry['etymology'])
        lines.append("")

    # Semantic range
    domains = _parse_json_field(entry.get('semantic_domain'))
    if domains:
        lines.append("### Semantic Range")
        lines.append(", ".join(domains))
        lines.append("")

    # Usage count
    if entry.get('usage_count'):
        lines.append(f"**Usage**: Occurs {entry['usage_count']} times in the Bible")
        lines.append("")

    # Related words
    related = _parse_json_field(entry.get('related_words'))
    if related:
        lines.append("### Related Words")
        for r in related:
            if isinstance(r, dict):
                lines.append(f"- {r.get('strongs', '')} {r.get('word', '')} - {r.get('gloss', '')}")
            else:
                lines.append(f"- {r}")
        lines.append("")

    # Abbott-Smith definition (NT-focused)
    abbott_def = entry.get('abbott_smith_def')
    if abbott_def:
        lines.append("### Abbott-Smith Definition (NT-Focused)")
        lines.append(_truncate(abbott_def, 3000, "\n\n*[Definition truncated — full entry available in Abbott-Smith]*"))
        lines.append("")

    # LXX / Hebrew equivalents
    lxx = _parse_json_field(entry.get('lxx_hebrew'))
    if lxx:
        lines.append("### LXX / Hebrew Equivalents")
        for item in lxx:
            if isinstance(item, dict):
                lines.append(f"- {item.get('strongs', '')} {item.get('hebrew', '')}")
        lines.append("")

    # Synonyms
    syn_text = entry.get('synonyms')
    if syn_text:
        lines.append("### Synonyms")
        lines.append(syn_text)
        lines.append("")

    # NT occurrences
    nt_count = entry.get('nt_occurrences')
    if nt_count:
        lines.append(f"**NT Usage**: Occurs {nt_count} times in the New Testament")
        lines.append("")

    return "\n".join(lines)


def _verse_heading(verse: dict) -> str:
    """Heading for a verse; English verse 0 is a Psalm superscription.

    STEPBible stores superscriptions as English verse 0 with the Hebrew verse
    in parentheses ('Psa.82.0(82.1)'), which reads oddly next to 'Psa.82.1'.
    """
    reference = verse["reference"]
    if verse.get("verse") != 0:
        return reference
    match = re.match(r"^([^.]+)\.(\d+)\.0(?:\((\d+\.\d+)\))?$", reference)
    if not match:
        return reference
    book, chapter, hebrew = match.groups()
    label = f"{book}.{chapter} superscription"
    return f"{label} (Hebrew {book}.{hebrew})" if hebrew else label


def format_verse(
    verse: dict,
    include_original: bool = True,
    include_morphology: bool = False,
    include_words: bool = True,
) -> str:
    """Format a verse for display; ``include_words`` controls the word list."""
    lines = []
    
    lines.append(f"## {_verse_heading(verse)}")
    lines.append("")
    lines.append(verse.get('text_english', 'No English text available.'))
    lines.append("")
    
    if include_original and verse.get('text_original'):
        lines.append("### Original Text")
        lines.append(verse['text_original'])
        lines.append("")
    
    words = _parse_json_field(verse.get('word_data'))
    if words and include_original and include_words:
        lines.append("### Word Analysis")
        for w in words:
            if isinstance(w, dict):
                word_line = f"- **{w.get('word', '')}** ({w.get('strongs', '')}): {w.get('gloss', '')}"
                if include_morphology and w.get('morph'):
                    word_line += f" [{w['morph']}]"
                lines.append(word_line)
        lines.append("")
    
    return "\n".join(lines)


_SHORT_ENGLISH_LABELS = {"MT": "word glosses", "LXX": "Brenton"}


def format_biblical_version_comparison(
    reference: str,
    rows: list[dict],
    include_original: bool = True,
    include_morphology: bool = False,
    numbering: str = "canonical",
    note: str = "",
) -> str:
    """Format edition rows compactly, with provenance listed once at the end.

    Rows sharing a canonical (MT/English) reference are grouped under one
    header; LXX-only rows (no canonical reference) are grouped by their
    edition reference. Each row names its version, edition, and edition
    reference; licence, source, translation label, verse-mapping credit, and
    the Brenton caveat appear once in a closing Sources block.
    """
    title = f"## Biblical Version Comparison: {reference}"
    if numbering == "lxx":
        title += " (Septuagint edition numbering)"
    lines = [title, ""]
    if note:
        lines.extend([f"*{note}*", ""])
    current_group: str | None = None
    sources: dict[tuple[str, str], dict] = {}
    brenton_note = ""
    brenton_greek_url = ""
    for row in rows:
        canonical = row.get("canonical_reference")
        group = canonical or f"{row['edition_reference']} (LXX-only, no MT counterpart)"
        if group != current_group:
            current_group = group
            lines.extend([f"### {group}", ""])
        sources.setdefault((row["version"], row["edition"]), row)

        header = f"#### {row['version']} {row['edition']} · {row['edition_reference']}"
        if row.get("mapping_method") and row["mapping_method"] != "identity":
            header += f" (mapping: {row['mapping_method']})"
        lines.append(header)
        if include_original:
            lines.append(f"**{row['language']}:** {row['text']}")
        if row.get("brenton_greek_differs"):
            lines.append(
                "> **Warning: Brenton's English below translates a different Greek text.** "
                f"His own Greek differs from the Rahlfs text here: {row['brenton_greek_difference']}"
            )
            brenton_greek_url = row.get("brenton_greek_source_url") or brenton_greek_url
            if include_original:
                lines.append(
                    f"**Brenton's Greek (the text his English translates):** {row['brenton_greek']}"
                )
        label = _SHORT_ENGLISH_LABELS.get(row["version"]) or row.get("translation_label") or "English"
        if row.get("translation"):
            lines.append(f"**English ({label}):** {row['translation']}")
        else:
            lines.append("**English:** not available for this edition.")
        if row.get("translation_note"):
            brenton_note = row["translation_note"]
            if "brenton_greek_differs" in row and row["brenton_greek_differs"] is None:
                lines.append("*Brenton's Greek for this verse is unavailable, so it was not compared.*")

        if include_morphology:
            words = _parse_json_field(row.get("morphology"), [])
            if words:
                lines.append("**Morphology:**")
                for word in words:
                    surface = word.get("surface") or word.get("word") or ""
                    identifier = word.get("lemma") or word.get("strongs") or ""
                    parsing = word.get("parsing") or word.get("morph") or ""
                    pos = word.get("pos") or ""
                    details = "; ".join(part for part in (identifier, pos, parsing) if part)
                    gloss = f" — {word['gloss']}" if word.get("gloss") else ""
                    lines.append(f"- **{surface}**{f' ({details})' if details else ''}{gloss}")
        lines.append("")

    lines.extend(["---", "**Sources**"])
    for (version, edition), row in sources.items():
        english = row.get("translation_label") or "none"
        lines.append(
            f"- {version} {edition} ({row['language']}): {row['license']}. "
            f"English: {english}. {row['source_url']}"
        )
    if brenton_greek_url:
        lines.append(f"- Brenton's Greek: public domain. {brenton_greek_url}")
    lines.append(f"- Verse mapping: {VERSE_MAPPING_CREDIT}")
    if brenton_note:
        lines.append(f"\n*Brenton's English: {brenton_note}*")
    return "\n".join(lines).rstrip()


def _format_ancient_biblical_link(link: dict) -> str:
    start_chapter, start_verse = divmod(link["sort_start"], 1000)
    end_chapter, end_verse = divmod(link["sort_end"], 1000)
    start = f"{link['biblical_book']} {start_chapter}:{start_verse}"
    end = (
        f"{end_verse}"
        if start_chapter == end_chapter
        else f"{end_chapter}:{end_verse}"
    )
    reference = start if link["sort_start"] == link["sort_end"] else f"{start}–{end}"
    return f"{reference} — {link['relationship_note']}"


def _fold_for_match(text: str) -> str:
    """Case- and accent-fold text one character at a time, keeping positions."""
    folded = []
    for ch in text:
        base = "".join(
            c for c in unicodedata.normalize("NFD", ch) if not unicodedata.combining(c)
        ).casefold()
        folded.append(base[:1] or ch)
    return "".join(folded)


def _match_excerpt(text: str, query: str, limit: int) -> str:
    """Return up to ``limit`` characters of ``text`` around the first query match.

    Matching folds case and accents and accepts a word stem (``build`` finds
    ``building``), mirroring the search index. Without a match the excerpt
    starts at the beginning. Ellipses mark text cut at either end.
    """
    if len(text) <= limit:
        return text
    folded = _fold_for_match(text)
    positions = []
    for word in re.findall(r"\w+", _fold_for_match(query)):
        stem = word if len(word) <= 5 else word[: len(word) - 2]
        found = re.search(rf"\b{re.escape(stem)}", folded)
        if found:
            positions.append(found.start())
    start = max(0, min(positions) - limit // 5) if positions else 0
    if start:
        space = text.find(" ", start)
        start = space + 1 if 0 <= space < start + 40 else start
    end = min(len(text), start + limit)
    if end < len(text):
        space = text.rfind(" ", start, end)
        end = space if space > start + limit // 2 else end
    return f"{'…' if start else ''}{text[start:end]}{'…' if end < len(text) else ''}"


def format_ancient_source_results(
    query: str,
    rows: list[dict],
    corpus: str,
    biblical_reference: str | None = None,
    period: str | None = None,
    match: str = "all",
) -> str:
    """Format primary-source results compactly, with provenance listed once.

    Each result shows a heading, its work and editorial period tags, an
    excerpt of the English around the first match, and a shorter Greek
    excerpt (a longer, match-centred one when the query is Greek).
    """
    filters = [f"corpus={corpus}"]
    if biblical_reference:
        filters.append(f"biblical_reference={biblical_reference}")
    if period:
        filters.append(f"period={period}")
    lines = [
        f"## Ancient Source Search: {query}",
        "",
        f"*Filters: {', '.join(filters)}*",
        "",
    ]
    if match == "any":
        lines.extend([
            "*No passage contains all terms; showing passages matching any term.*",
            "",
        ])
    greek_query = any("\u0370" <= ch <= "\u03ff" or "\u1f00" <= ch <= "\u1fff" for ch in query)
    sources: dict[tuple, list[str]] = {}
    for row in rows:
        heading = f"### {row['author']}, {row['reference']}"
        if row.get("alternate_reference"):
            heading += f" ({row['alternate_reference']})"
        lines.append(heading)
        lines.append(f"*{row['work_title']} · editorial period tags: {row['period_tags']}*")
        if row.get("editorial_heading"):
            lines.append(f"*Whiston chapter heading (editorial): {row['editorial_heading']}*")
        key = (row["edition"], row["translation"], row["license"])
        if row["source_url"] not in sources.setdefault(key, []):
            sources[key].append(row["source_url"])
        lines.extend(["", _match_excerpt(row["text"], query, 1500)])
        if row.get("original_text"):
            greek = (
                _match_excerpt(row["original_text"], query, 1200)
                if greek_query
                else _match_excerpt(row["original_text"], "", 600)
            )
            lines.extend(["", f"**Greek:** {greek}"])
        if row.get("biblical_links"):
            lines.extend(["", "**Editorial biblical links:**"])
            for link in row["biblical_links"]:
                lines.append(f"- {_format_ancient_biblical_link(link)}")
        lines.extend(["", "---", ""])
    lines.append("**Sources**")
    for (edition, translation, license_), urls in sources.items():
        lines.append(
            f"- Greek: {edition}. English: {translation}. License: {license_}. "
            + " ".join(urls)
        )
    return "\n".join(lines).rstrip()


def _format_sourced_statement(item: dict, field: str, label: str) -> list[str]:
    """Format an attributed judgment or interpretation without implying provenance."""
    attribution = item.get("attribution") or "Unattributed"
    lines = [f"- **{label}: {attribution}.** {item[field]}"]
    if item.get("source_citation"):
        lines.append(f"  - Citation: {item['source_citation']}")
    if item.get("source_url"):
        lines.append(f"  - Source: {item['source_url']}")
    return lines


def _format_witness(witness: dict, note: str = "") -> list[str]:
    """Format one evidence row, keeping the raw dataset support label visible."""
    date = f" ({witness['approximate_date']})" if witness.get("approximate_date") else ""
    line = f"- **{witness['witness']}**{date}"
    if note:
        line += f" — {note}"
    if witness.get("reading_support"):
        line += f" (dataset label: `{witness['reading_support']}`)"
    lines = [line]
    if witness.get("source_citation"):
        lines.append(f"  - Citation: {witness['source_citation']}")
    if witness.get("source_url"):
        lines.append(f"  - Source: {witness['source_url']}")
    return lines


_NOT_PRESERVED_SUFFIX = re.compile(r"\s*\(none preserved\)\s*$", re.IGNORECASE)


def _format_interpretation_sections(case: dict) -> list[str]:
    """Format a case's attributed layers, omitting any section with no rows."""
    lines: list[str] = []
    judgments = case.get("critical_judgments") or []
    if judgments:
        lines.extend(["", "### Critical judgments"])
        for judgment in judgments:
            lines.extend(_format_sourced_statement(judgment, "judgment", "Attribution"))

    summaries = case.get("unsourced_summaries") or []
    if summaries:
        lines.extend(
            [
                "",
                "### Unsourced dataset summary (not verified against published "
                "text-critical scholarship)",
            ]
        )
        for summary in summaries:
            lines.append(f"- {summary['judgment']}")

    decisions = case.get("translation_decisions") or []
    if decisions:
        lines.extend(["", "### Translation decisions"])
        for decision in decisions:
            lines.append(f"- **{decision['translation']}:** {decision['preferred_reading']}")
            if decision.get("rationale"):
                lines.append(f"  - Rationale: {decision['rationale']}")

    claims = case.get("author_specific_claims") or []
    if claims:
        lines.extend(["", "### Author-specific claims"])
        for claim in claims:
            lines.append(f"- **{claim['author']}.** {claim['claim']}")
            if claim.get("source_citation"):
                lines.append(f"  - Citation: {claim['source_citation']}")
            if claim.get("source_url"):
                lines.append(f"  - Source: {claim['source_url']}")

    interpretations = case.get("theological_interpretations") or []
    if interpretations:
        lines.extend(["", "### Theological interpretations"])
        for interpretation in interpretations:
            lines.extend(
                _format_sourced_statement(interpretation, "interpretation", "Attribution")
            )
    return lines


def _format_citation_evidence(case: dict) -> list[str]:
    citations = case.get("citation_evidence") or []
    if not citations:
        return []
    lines = [
        "",
        "### NT citation evidence",
        "*New Testament quotations show how the verse was cited; "
        "they are not manuscript copies of it.*",
    ]
    for witness in citations:
        lines.extend(
            _format_witness(witness, f"quotes the {witness.get('tradition', '?')} reading")
        )
    return lines


def _format_interpretive_case(case: dict) -> list[str]:
    """Format an agreed-text case: the MT reading, then the attributed layers."""
    lines = [
        f"## Translation and interpretation notes at {case['reference']}",
        "*Not a manuscript variant: the witnesses agree with the Masoretic Text "
        "here. These notes record how the verse is read and translated.*",
        f"**Case key:** {case['case_key']}",
    ]
    if case.get("significance"):
        lines.append(f"**Significance classification:** {case['significance']}")
    for reading in case.get("manuscript_evidence") or []:
        lines.extend(["", f"### Text ({reading['tradition']})", reading["text"]])
        if reading.get("original_text"):
            lines.append(f"\n**Original-language text:** `{reading['original_text']}`")
        witnesses = reading.get("witnesses") or []
        if witnesses:
            names = ", ".join(
                f"{w['witness']} ({w['approximate_date']})" if w.get("approximate_date")
                else w["witness"]
                for w in witnesses
            )
            lines.append(f"\n**Witnesses agreeing with this text:** {names}")
    lines.extend(_format_citation_evidence(case))
    lines.extend(_format_interpretation_sections(case))
    lines.extend(["", "---", ""])
    return lines


def format_textual_variant_cases(
    reference: str,
    cases: list[dict],
    quotation_hints: list[dict],
) -> str:
    """Format evidence, judgments, interpretations, and claims as separate sections."""
    if cases and all(case.get("kind") == "interpretive" for case in cases):
        lines = [f"# Translation and interpretation notes for {reference}", ""]
    else:
        lines = [f"# Textual variant record for {reference}", ""]
    for case in cases:
        if case.get("kind") == "interpretive":
            lines.extend(_format_interpretive_case(case))
            continue
        lines.extend(
            [
                f"## Variant at {case['reference']}",
                f"**Case key:** {case['case_key']}",
            ]
        )
        if case.get("significance"):
            lines.append(f"**Significance classification:** {case['significance']}")

        lines.extend(["", "### Manuscript evidence"])
        readings = case.get("manuscript_evidence") or []
        if not readings:
            lines.append("*No manuscript readings catalogued.*")
        for reading in readings:
            lines.extend(["", f"#### {reading['tradition']}", reading["text"]])
            if reading.get("original_text"):
                lines.append(f"\n**Original-language text:** `{reading['original_text']}`")
            witnesses = reading.get("witnesses") or []
            if witnesses:
                lines.append("\n**Manuscript witnesses for this reading:**")
                for witness in witnesses:
                    lines.extend(_format_witness(witness))

        lines.extend(_format_citation_evidence(case))

        indirect = case.get("indirect_evidence") or []
        if indirect:
            lines.extend(
                [
                    "",
                    "### Indirect evidence",
                    "*Not a direct witness to this verse; bears on the text form "
                    "behind a reading.*",
                ]
            )
            for witness in indirect:
                lines.extend(
                    _format_witness(
                        witness, f"bears on the {witness.get('tradition', '?')} reading"
                    )
                )

        not_preserved = case.get("not_preserved_in") or []
        if not_preserved:
            names = ", ".join(
                _NOT_PRESERVED_SUFFIX.sub("", witness["witness"]) for witness in not_preserved
            )
            lines.extend(["", f"**Not preserved in:** {names}"])

        lines.extend(_format_interpretation_sections(case))
        lines.extend(["", "---", ""])

    if quotation_hints:
        lines.extend(["## NT quotation alignment", ""])
        for hint in quotation_hints:
            lines.append(
                f"- **{hint['nt_display']}** quotes **{hint['ot_display']}** — "
                f"*{hint.get('divergence_type') or 'alignment'}*: "
                f"{hint.get('divergence_note') or 'No note catalogued.'}"
            )

    return "\n".join(lines).rstrip()


def format_name_entry(entry: dict, acai_data: dict | None = None) -> str:
    """Format a name entry for display, optionally enriched with ACAI data."""
    lines = []

    lines.append(f"### {entry['name']}")
    if entry.get('name_original'):
        lines.append(f"**Original**: {entry['name_original']}")
    lines.append(f"**Type**: {entry.get('type', 'Unknown').title()}")
    lines.append("")

    if entry.get('description'):
        lines.append(entry['description'])
        lines.append("")

    # ACAI enrichment
    if acai_data:
        acai_parts = []

        if acai_data.get('description'):
            acai_parts.append(f"**Description**: {acai_data['description']}")

        # Variant names
        variants = _parse_json_field(acai_data.get('referred_to_as'))
        if variants:
            acai_parts.append(f"**Also known as**: {', '.join(str(v) for v in variants[:5])}")

        # Roles
        roles = _parse_json_field(acai_data.get('roles'))
        if roles:
            acai_parts.append(f"**Roles**: {', '.join(str(r) for r in roles)}")

        if acai_data.get('reference_count'):
            acai_parts.append(f"**Referenced in**: {acai_data['reference_count']} verses")

        if acai_data.get('speeches_count'):
            acai_parts.append(f"**Attributed speeches**: {acai_data['speeches_count']}")

        if acai_parts:
            lines.append("**ACAI Annotations**:")
            lines.extend(acai_parts)
            lines.append("")

    rels = _parse_json_field(entry.get('relationships'))
    if rels:
        lines.append("**Relationships**:")
        for key, value in rels.items():
            if value:
                lines.append(f"- {key.title()}: {value}")
        lines.append("")

    refs = _parse_json_field(entry.get('references'))
    if refs:
        lines.append("**Key References**: " + ", ".join(refs[:10]))
        if len(refs) > 10:
            lines.append(f"(and {len(refs) - 10} more)")
        lines.append("")

    return "\n".join(lines)


# =========================================================================
# Aquifer content formatters
# =========================================================================

def format_study_notes(notes: list[dict]) -> str:
    """Format study notes grouped by source type."""
    if not notes:
        return "No study notes available for this reference.\n"

    lines = []

    # Group by resource_type
    groups: dict[str, list[dict]] = {}
    for note in notes:
        rt = note.get('resource_type', 'unknown')
        groups.setdefault(rt, []).append(note)

    type_labels = {
        'study_notes': 'Tyndale Study Notes',
        'translation_notes_uw': 'Translation Notes (unfoldingWord)',
        'translation_notes_sil': 'Translation Notes (SIL)',
    }

    for resource_type, group_notes in groups.items():
        label = type_labels.get(resource_type, resource_type)
        lines.append(f"### {label}")
        lines.append("")

        for note in group_notes:
            title = note.get('title', '')
            content = note.get('content_plain', '')

            if title:
                lines.append(f"**{title}**")
            if content:
                lines.append(_truncate(content, 2000, "\n\n*[Note truncated]*"))
            lines.append("")

    return "\n".join(lines)


def _format_content_items(items: list[dict], limit: int, truncation_note: str, empty_msg: str) -> str:
    """Format a list of content items (articles, terms) with title + truncated body."""
    if not items:
        return empty_msg

    lines = []
    for item in items:
        title = item.get('title', 'Untitled')
        content = item.get('content_plain', '')
        lines.append(f"## {title}")
        lines.append("")
        if content:
            lines.append(_truncate(content, limit, truncation_note))
        lines.append("")
    return "\n".join(lines)


def format_dictionary_article(articles: list[dict]) -> str:
    """Format Bible dictionary articles."""
    return _format_content_items(
        articles, 4000,
        "\n\n*[Article truncated — full text available in the Tyndale Bible Dictionary]*",
        "No dictionary article found for this topic.\n",
    )


def format_key_terms(terms: list[dict]) -> str:
    """Format FIA Key Terms results."""
    return _format_content_items(
        terms, 3000,
        "\n\n*[Term entry truncated]*",
        "No key term found matching this query.\n",
    )


# =========================================================================
# ANE context formatting
# =========================================================================

def _format_ane_entry_full(entry: dict, lines: list[str]) -> None:
    """Format a single ANE entry with full detail."""
    title = entry.get("title", "")
    summary = entry.get("summary", "")
    detail = entry.get("detail", "")
    period_label = entry.get("period_label", "")
    significance = entry.get("interpretive_significance", "")

    lines.append(f"### {title}")
    if period_label:
        lines.append(f"*Period: {period_label}*")
    lines.append("")

    if summary:
        lines.append(summary)
        lines.append("")

    if detail:
        lines.append(detail)
        lines.append("")

    # ANE parallels
    parallels = _parse_json_field(entry.get("ane_parallels"), [])
    if parallels:
        lines.append("**ANE Parallels:**")
        for p in parallels:
            lines.append(f"- {p}")
        lines.append("")

    if significance:
        lines.append(f"**Interpretive Significance:** {significance}")
        lines.append("")

    # Key references
    refs = _parse_json_field(entry.get("key_references"), [])
    if refs:
        lines.append(f"**Key References:** {', '.join(refs)}")
        lines.append("")

    # Scholarly sources
    sources = _parse_json_field(entry.get("scholarly_sources"), [])
    if sources:
        lines.append(f"**Sources:** {'; '.join(sources)}")
        lines.append("")


def _format_ane_entry_brief(entry: dict, lines: list[str]) -> None:
    """Format a single ANE entry briefly — title, summary, significance, key refs."""
    title = entry.get("title", "")
    summary = entry.get("summary", "")
    significance = entry.get("interpretive_significance", "")

    lines.append(f"### {title}")
    lines.append("")

    if summary:
        lines.append(summary)
        lines.append("")

    if significance:
        lines.append(f"**Interpretive Significance:** {significance}")
        lines.append("")

    refs = _parse_json_field(entry.get("key_references"), [])
    if refs:
        lines.append(f"**Key References:** {', '.join(refs)}")
        lines.append("")


def _format_grouped(entries: list[dict], lines: list[str], formatter) -> None:
    """Group entries by dimension and format each with the given formatter."""
    groups: dict[str, list[dict]] = {}
    for entry in entries:
        dim = entry.get("dimension_label", entry.get("dimension", "Unknown"))
        groups.setdefault(dim, []).append(entry)

    for dimension_label, group_entries in groups.items():
        lines.append(f"## {dimension_label}")
        lines.append("")
        for entry in group_entries:
            formatter(entry, lines)
        lines.append("---")
        lines.append("")


def format_ane_context(entries: list[dict], detail_level: str = "standard") -> str:
    """Format ANE context entries for display.

    Args:
        entries: List of ANE entry dicts from the database.
        detail_level: 'brief' = all entries brief, 'standard' = direct matches full /
            broad matches brief, 'full' = all entries full.
    """
    if not entries:
        return "No ANE context entries found for the given criteria.\n"

    lines = []
    has_match_types = any(e.get("match_type") for e in entries)

    if detail_level == "full" or not has_match_types:
        # Full detail for everything, or no match_type info (dimension/period queries)
        formatter = _format_ane_entry_full if detail_level != "brief" else _format_ane_entry_brief
        _format_grouped(entries, lines, formatter)
    elif detail_level == "brief":
        _format_grouped(entries, lines, _format_ane_entry_brief)
    else:
        # Standard mode: separate direct from broad with clear headers
        direct = [e for e in entries if e.get("match_type") == "direct"]
        broad = [e for e in entries if e.get("match_type") == "broad"]

        if direct:
            lines.append("# Directly Relevant to This Passage")
            lines.append("")
            _format_grouped(direct, lines, _format_ane_entry_full)

        if broad:
            lines.append("# General ANE Reading Frame")
            lines.append("*These entries provide broad cultural context for this book. Summaries shown; call with detail_level='full' for complete entries.*")
            lines.append("")
            _format_grouped(broad, lines, _format_ane_entry_brief)

    return "\n".join(lines)


def format_ane_dimensions(dimensions: list[dict]) -> str:
    """Format the list of available ANE dimensions."""
    lines = [
        "## Ancient Near East Context — Available Dimensions",
        "",
        "Use `get_ane_context` with a `reference` to get relevant ANE background for any passage.",
        "Optionally filter by `dimension` and/or `period`.",
        "",
        "### Dimensions",
        "",
    ]
    for dim in dimensions:
        lines.append(f"- **{dim['dimension_label']}** (`{dim['dimension']}`) — {dim['entry_count']} entries")
    lines.append("")
    lines.append("### Periods")
    lines.append("")
    from .parsers.ane_context import PERIOD_LABELS
    for key, label in PERIOD_LABELS.items():
        lines.append(f"- `{key}` — {label}")
    lines.append("")
    return "\n".join(lines)


# =========================================================================
# Graph formatting functions
# =========================================================================

def format_year(year: int | None) -> str:
    """Format a year as BC/AD."""
    if year is None:
        return "unknown"
    if year < 0:
        return f"{abs(year)} BC"
    return f"AD {year}"


def _render_family_list(people: list[dict], heading: str, lines: list[str]) -> None:
    """Render a list of ancestors or descendants into lines."""
    if people and len(people) > 1:
        lines.append(f"### {heading}")
        for p in people:
            if p["generation"] == 0:
                continue
            indent = "  " * p["generation"]
            rel = p["relationship"].replace("_of", "").title()
            year_str = f" ({format_year(p.get('birth_year'))})" if p.get("birth_year") else ""
            lines.append(f"{indent}- **{p['name']}** ({rel}){year_str}")
        lines.append("")


def format_genealogy(person_name: str, ancestors: list[dict], descendants: list[dict]) -> str:
    """Format a genealogy tree for display."""
    lines = [f"## Genealogy of {person_name}\n"]

    _render_family_list(ancestors, "Ancestors", lines)
    _render_family_list(descendants, "Descendants", lines)

    if len(ancestors) <= 1 and len(descendants) <= 1:
        lines.append("No genealogical data found in the Theographic database.\n")

    return "\n".join(lines)


def format_person_events(person_name: str, events: list[dict], event_places: dict[str, list[dict]]) -> str:
    """Format a person's event timeline."""
    lines = [f"## Timeline of {person_name}\n"]

    if not events:
        lines.append("No events found in the Theographic database.\n")
        return "\n".join(lines)

    for evt in events:
        year_str = f" ({format_year(evt.get('start_year'))})" if evt.get("start_year") else ""
        lines.append(f"- **{evt['title']}**{year_str}")
        places = event_places.get(evt["id"], [])
        if places:
            place_names = ", ".join(p["name"] for p in places)
            lines.append(f"  Location: {place_names}")
    lines.append("")

    return "\n".join(lines)


def format_place_history(place: dict, events: list[dict], people: dict) -> str:
    """Format a place's biblical history."""
    lines = [f"## {place['name']}\n"]

    if place.get("feature_type"):
        lines.append(f"**Type**: {place['feature_type']}")
    if place.get("latitude") and place.get("longitude"):
        lines.append(f"**Coordinates**: {place['latitude']:.4f}, {place['longitude']:.4f}")
    lines.append("")

    if events:
        lines.append("### Events at this location")
        for evt in events:
            year_str = f" ({format_year(evt.get('start_year'))})" if evt.get("start_year") else ""
            lines.append(f"- **{evt['title']}**{year_str}")
        lines.append("")

    born = people.get("born_here", [])
    died = people.get("died_here", [])

    if born:
        lines.append("### Born here")
        for p in born:
            lines.append(f"- {p['name']}")
        lines.append("")

    if died:
        lines.append("### Died here")
        for p in died:
            lines.append(f"- {p['name']}")
        lines.append("")

    if not events and not born and not died:
        lines.append("No detailed history found in the Theographic database.\n")

    return "\n".join(lines)


def format_passage_entities(reference: str, entities: dict) -> str:
    """Format entities found in a passage."""
    lines = [f"## Entities in {reference}\n"]

    people = entities.get("people", [])
    places = entities.get("places", [])
    events = entities.get("events", [])

    if people:
        lines.append("### People")
        for p in people:
            lines.append(f"- **{p.get('entity_name', p.get('entity_id', 'unknown'))}**")
        lines.append("")

    if places:
        lines.append("### Places")
        for p in places:
            lines.append(f"- **{p.get('entity_name', p.get('entity_id', 'unknown'))}**")
        lines.append("")

    if events:
        lines.append("### Events")
        for e in events:
            lines.append(f"- **{e.get('entity_name', e.get('entity_id', 'unknown'))}**")
        lines.append("")

    if not people and not places and not events:
        lines.append("No entities found for this passage in the Theographic database.\n")

    return "\n".join(lines)


def format_connection_path(person1: str, person2: str, path: list[dict]) -> str:
    """Format a relationship path between two people."""
    lines = [f"## Connection: {person1} → {person2}\n"]

    if not path:
        lines.append("No family connection found in the Theographic database.\n")
        return "\n".join(lines)

    for step in path:
        rel = step["relationship_type"].replace("_", " ").title()
        lines.append(f"- {step['from_name']} → *{rel}* → {step['to_name']}")
    lines.append("")

    return "\n".join(lines)


def format_enriched_verse(reference: str, verse: dict | None, entities: dict, family_data: dict[str, dict]) -> str:
    """Format a verse with its entity context and family relationships.

    Args:
        reference: The verse reference string
        verse: The verse dict (or None)
        entities: Dict with 'people', 'places', 'events' lists
        family_data: Map of person name -> family dict from graph_get_family
    """
    lines = [f"## {reference}\n"]

    if verse:
        lines.append(verse.get("text_english", ""))
        lines.append("")
        if verse.get("text_original"):
            lines.append(f"**Original**: {verse['text_original']}")
            lines.append("")

    people = entities.get("people", [])
    places = entities.get("places", [])
    events = entities.get("events", [])

    if people:
        lines.append("### People Mentioned")
        for p in people:
            name = p.get("entity_name", p.get("entity_id"))
            lines.append(f"\n**{name}**")
            family = family_data.get(name)
            if family:
                parts = []
                if family["parents"]:
                    parent_names = ", ".join(pr["name"] for pr in family["parents"])
                    parts.append(f"Parents: {parent_names}")
                if family["partners"]:
                    partner_names = ", ".join(pr["name"] for pr in family["partners"])
                    parts.append(f"Spouse: {partner_names}")
                if family["children"]:
                    child_names = ", ".join(c["name"] for c in family["children"][:5])
                    suffix = f" (+{len(family['children'])-5} more)" if len(family["children"]) > 5 else ""
                    parts.append(f"Children: {child_names}{suffix}")
                if parts:
                    lines.append("  " + " | ".join(parts))
        lines.append("")

    if places:
        lines.append("### Places Mentioned")
        for p in places:
            lines.append(f"- **{p.get('entity_name', p.get('entity_id'))}**")
        lines.append("")

    if events:
        lines.append("### Events")
        for e in events:
            lines.append(f"- **{e.get('entity_name', e.get('entity_id'))}**")
        lines.append("")

    if not people and not places and not events:
        lines.append("*No entity data available for this verse in the Theographic database.*\n")

    return "\n".join(lines)


# =========================================================================
# Mermaid diagram formatters
# =========================================================================

def _mermaid_id(name: str) -> str:
    """Create a safe Mermaid node ID from a name."""
    return name.replace(" ", "_").replace("'", "").replace("(", "").replace(")", "")


def mermaid_genealogy(
    person_name: str,
    ancestors: list[dict],
    descendants: list[dict],
    family: dict | None = None,
) -> str:
    """Generate a Mermaid flowchart for a family tree.

    Uses family edges (parents/children/partners) for accurate connections.
    Falls back to generation-based layout if family data not provided.
    """
    lines = ["```mermaid", "graph TD"]
    seen_edges = set()
    seen_nodes = set()
    person_mid = _mermaid_id(person_name)

    # Style the focal person
    lines.append(f'    {person_mid}["{person_name}"]')
    lines.append(f"    style {person_mid} fill:#4a90d9,color:#fff,stroke:#2a5a8a")
    seen_nodes.add(person_mid)

    # Ancestors: show direct lineage chain only (gen 1 = parents, gen 2 = grandparents, etc.)
    # Build a map of unique people per generation to avoid cartesian products
    if ancestors and len(ancestors) > 1:
        by_gen: dict[int, list[dict]] = {}
        for a in ancestors:
            by_gen.setdefault(a["generation"], []).append(a)

        max_gen = max(by_gen.keys())
        # Connect each generation to the one below, but limit edges
        for gen in range(max_gen, 0, -1):
            people_at_gen = by_gen.get(gen, [])
            people_below = by_gen.get(gen - 1, [])
            for person in people_at_gen:
                pid = _mermaid_id(person["name"])
                rel = person["relationship"].replace("_of", "")
                if not seen_nodes.__contains__(pid):
                    seen_nodes.add(pid)
                # Connect to the person one generation below
                # For gen 1, connect to the focal person
                if gen == 1:
                    edge_key = (pid, person_mid)
                    if edge_key not in seen_edges:
                        seen_edges.add(edge_key)
                        lines.append(f'    {pid}["{person["name"]}"] -->|{rel}| {person_mid}')
                else:
                    # Connect to people at gen-1 (limit to 2 to avoid explosion)
                    for child in people_below[:2]:
                        child_id = _mermaid_id(child["name"])
                        edge_key = (pid, child_id)
                        if edge_key not in seen_edges:
                            seen_edges.add(edge_key)
                            lines.append(f'    {pid}["{person["name"]}"] -->|{rel}| {child_id}["{child["name"]}"]')

    # Descendants: only show generation 1 (direct children) to keep diagram clean
    if descendants and len(descendants) > 1:
        direct_children = [d for d in descendants if d["generation"] == 1]
        for d in direct_children:
            did = _mermaid_id(d["name"])
            rel = d["relationship"].replace("_of", "")
            edge_key = (person_mid, did)
            if edge_key not in seen_edges:
                seen_edges.add(edge_key)
                lines.append(f'    {person_mid} -->|{rel}| {did}["{d["name"]}"]')

    # Partners from family data
    if family and family.get("partners"):
        for p in family["partners"]:
            pid = _mermaid_id(p["name"])
            edge_key = (person_mid, pid)
            if edge_key not in seen_edges:
                seen_edges.add(edge_key)
                lines.append(f'    {person_mid} -.-|spouse| {pid}["{p["name"]}"]')
                lines.append(f"    style {pid} fill:#d9a04a,color:#fff")

    lines.append("```")
    return "\n".join(lines)


def mermaid_connection_path(person1: str, person2: str, path: list[dict]) -> str:
    """Generate a Mermaid flowchart showing the relationship path between two people."""
    if not path:
        return ""

    lines = ["```mermaid", "graph LR"]

    # Style start and end
    start_id = _mermaid_id(person1)
    end_id = _mermaid_id(person2)
    lines.append(f"    style {start_id} fill:#4a90d9,color:#fff,stroke:#2a5a8a")
    lines.append(f"    style {end_id} fill:#d94a4a,color:#fff,stroke:#8a2a2a")

    seen = set()
    for step in path:
        fid = _mermaid_id(step["from_name"])
        tid = _mermaid_id(step["to_name"])
        rel = step["relationship_type"].replace("_", " ")
        edge_key = (fid, tid)
        if edge_key not in seen:
            seen.add(edge_key)
            lines.append(f'    {fid}["{step["from_name"]}"] -->|{rel}| {tid}["{step["to_name"]}"]')

    lines.append("```")
    return "\n".join(lines)


def mermaid_person_timeline(
    person_name: str,
    events: list[dict],
    event_places: dict[str, list[dict]],
) -> str:
    """Generate a Mermaid timeline diagram for a person's life events."""
    if not events:
        return ""

    lines = ["```mermaid", "timeline", f"    title {person_name}"]

    for evt in events:
        year = evt.get("start_year")
        year_str = format_year(year) if year else ""
        title = evt["title"].replace('"', "'")
        places = event_places.get(evt["id"], [])

        section_label = year_str if year_str else title[:20]
        lines.append(f"    {section_label} : {title}")
        if places:
            place_names = ", ".join(p["name"] for p in places[:3])
            lines.append(f"        : {place_names}")

    lines.append("```")
    return "\n".join(lines)


def mermaid_place_network(
    place: dict,
    events: list[dict],
    people: dict,
) -> str:
    """Generate a Mermaid graph showing a place's connections to events and people."""
    born = people.get("born_here", [])
    died = people.get("died_here", [])
    if not events and not born and not died:
        return ""

    lines = ["```mermaid", "graph TD"]

    place_id = _mermaid_id(place["name"])
    lines.append(f'    {place_id}["{place["name"]}"]')
    lines.append(f"    style {place_id} fill:#2a8a4a,color:#fff,stroke:#1a5a2a")

    # Events
    if events:
        for evt in events[:12]:  # limit to avoid huge diagrams
            eid = _mermaid_id(evt["title"][:30])
            year_str = f" ({format_year(evt.get('start_year'))})" if evt.get("start_year") else ""
            label = evt["title"][:40] + year_str
            lines.append(f'    {place_id} --- {eid}["{label}"]')

    # People born/died
    for p in born[:8]:
        pid = _mermaid_id(p["name"]) + "_b"
        lines.append(f'    {pid}["{p["name"]}"] -->|born| {place_id}')
        lines.append(f"    style {pid} fill:#4a90d9,color:#fff")

    for p in died[:8]:
        pid = _mermaid_id(p["name"]) + "_d"
        lines.append(f'    {place_id} -->|died| {pid}["{p["name"]}"]')
        lines.append(f"    style {pid} fill:#d94a4a,color:#fff")

    lines.append("```")
    return "\n".join(lines)


# =========================================================================
# Format functions — Torah Weave
# =========================================================================

# Template explaining the structural meaning of each direction.
_TORAH_WEAVE_DIRECTIONAL_DOC = """\
### How to read Torah Weave partners

Under Moshe Kline's Woven Torah hypothesis, each Torah unit is a 2D grid whose \
cells are deliberately paired in two directions:

- **Horizontal partners** (same row, different column) are **parallel correspondences** \
at the same compositional tier. Rows in Kline's method carry divine-name registers \
(Row 1 tends to feature YHWH as active subject, Row 3 Elohim, Row 2 the interface \
between them), so horizontal partners sit at the same register but on different \
thematic tracks. Read them as a symmetry: the two cells are the same "note" played \
in different thematic keys. Look for inversion, contrast, completion, or framework-\
and-filling.

- **Vertical partners** (same column, different row) are **progressions through \
divine-name registers along a single thematic track**. Columns are thematic tracks, \
so vertical partners follow one theme as it moves through the register hierarchy. \
Read them as development, not symmetry. Look for escalation, register shift, or \
narrative arc.

- **Sibling cells** (same row + column, adjacent subdivisions) are an internal \
progression inside a single cell position. Read them sequentially.

The text of the partner cells is not included above; `lookup_verse` returns it for \
each verse range. The thematic content of each unit's columns is not labelled in \
Kline's dataset; under his method it is inferred from the verses themselves."""


def _cell_sort_key(cell: dict) -> tuple:
    """Sort key: row, then column, then subdivision ('' before 'a' before 'b')."""
    return (
        cell["row_num"],
        cell["column_letter"],
        cell.get("subdivision") or "",
    )


def _cells_match_subdivision(a: dict, b: dict) -> bool:
    """Two cells match on subdivision if both are parent (None) or both same letter."""
    return (a.get("subdivision") or None) == (b.get("subdivision") or None)


def compute_torah_weave_partners(
    target_cell: dict, all_cells: list[dict]
) -> dict[str, list[dict]]:
    """Given a cell and all cells in its unit, compute partners by direction."""
    horizontal: list[dict] = []
    vertical: list[dict] = []
    siblings: list[dict] = []

    for c in all_cells:
        if c["id"] == target_cell["id"]:
            continue

        same_row = c["row_num"] == target_cell["row_num"]
        same_col = c["column_letter"] == target_cell["column_letter"]
        same_sub = _cells_match_subdivision(c, target_cell)

        if same_row and same_sub and not same_col:
            horizontal.append(c)
        elif same_col and same_sub and not same_row:
            vertical.append(c)
        elif same_row and same_col and not same_sub:
            siblings.append(c)

    horizontal.sort(key=_cell_sort_key)
    vertical.sort(key=_cell_sort_key)
    siblings.sort(key=_cell_sort_key)
    return {"horizontal": horizontal, "vertical": vertical, "siblings": siblings}


def _format_cell_ref(cell: dict, book_full: str) -> str:
    """Format a cell's verse range as a user-readable reference."""
    c1, v1, c2, v2 = (
        cell["chapter_start"],
        cell["verse_start"],
        cell["chapter_end"],
        cell["verse_end"],
    )
    if c1 == c2 and v1 == v2:
        return f"{book_full} {c1}:{v1}"
    if c1 == c2:
        return f"{book_full} {c1}:{v1}-{v2}"
    return f"{book_full} {c1}:{v1}-{c2}:{v2}"


def _format_partner_line(cell: dict, book_full: str) -> str:
    sub = f" (subdivision {cell['subdivision']})" if cell.get("subdivision") else ""
    return (
        f"- **Cell {cell['cell_label']}**{sub} — "
        f"{_format_cell_ref(cell, book_full)}"
    )


def format_torah_weave(
    reference: str,
    matches: list[dict],
    unit_cells_by_unit: dict[int, list[dict]],
) -> str:
    """Format Torah Weave match(es) for a reference.

    matches: list of cells (joined with unit metadata) returned by
        get_torah_weave_cells_for_reference.
    unit_cells_by_unit: map of unit_id → all cells in that unit.
    """
    if not matches:
        return (
            f"No Torah Weave unit contains {reference}. "
            "Torah Weave data covers Genesis–Deuteronomy only."
        )

    lines: list[str] = []
    lines.append(f"## Torah Weave for {reference}\n")
    lines.append(
        "*Source: Moshe Kline, Woven Torah hypothesis "
        "(chaver.com, CC BY 4.0)*\n"
    )

    type_labels = {
        "F": "Framework (marks structural boundaries)",
        "CL": "Closure (provides envelope closure)",
        "U": "Unique (stands outside triadic groupings)",
    }

    for i, cell in enumerate(matches):
        if i > 0:
            lines.append("\n---\n")

        unit_id = cell["unit_id"]
        unit_book_full = cell["unit_book_full"]
        unit_title = cell["unit_title"]
        unit_verses = cell["unit_verses"]
        unit_format = cell["unit_format"]
        unit_type = cell.get("unit_type")
        unit_type_label = type_labels.get(unit_type) if unit_type else None
        unit_irregular = bool(cell.get("unit_irregular"))
        unit_is_unique = bool(cell.get("unit_is_unique"))

        lines.append(
            f"### Unit {unit_id} · \"{unit_title}\" ({unit_verses})"
        )
        lines.append("")
        meta_bits = [f"**Format**: {unit_format}"]
        if unit_irregular:
            meta_bits.append("irregular")
        if unit_is_unique:
            meta_bits.append("unique (outside triadic pattern)")
        if unit_type_label:
            meta_bits.append(f"**Type**: {unit_type} — {unit_type_label}")
        lines.append(" · ".join(meta_bits))
        lines.append("")

        sub_note = (
            f" (subdivision {cell['subdivision']})"
            if cell.get("subdivision")
            else ""
        )
        lines.append(
            f"**Cell position**: `{cell['cell_label']}` — "
            f"row {cell['row_num']}, column {cell['column_letter']}{sub_note}"
        )
        lines.append(
            f"**Cell verse range**: {_format_cell_ref(cell, unit_book_full)}"
        )
        lines.append("")

        all_cells = unit_cells_by_unit.get(unit_id, [])
        partners = compute_torah_weave_partners(cell, all_cells)

        if partners["horizontal"]:
            lines.append("#### ⇄ Horizontal weave partners (same row)")
            lines.append(
                "*Parallel correspondences at the same compositional tier / divine-name register.*"
            )
            for p in partners["horizontal"]:
                lines.append(_format_partner_line(p, unit_book_full))
            lines.append("")
        else:
            lines.append("#### ⇄ Horizontal weave partners")
            lines.append("*(none — this cell has no row partner)*\n")

        if partners["vertical"]:
            lines.append("#### ↕ Vertical weave partners (same column)")
            lines.append(
                "*Progression through divine-name registers along a single thematic track.*"
            )
            for p in partners["vertical"]:
                lines.append(_format_partner_line(p, unit_book_full))
            lines.append("")
        else:
            lines.append("#### ↕ Vertical weave partners")
            lines.append("*(none — this cell has no column partner)*\n")

        if partners["siblings"]:
            lines.append("#### ↔ Sibling cells (same row + column)")
            lines.append(
                "*Internal progression within this cell position; read sequentially.*"
            )
            for p in partners["siblings"]:
                lines.append(_format_partner_line(p, unit_book_full))
            lines.append("")

    lines.append("\n---\n")
    lines.append(_TORAH_WEAVE_DIRECTIONAL_DOC)
    lines.append("")
    return "\n".join(lines)
