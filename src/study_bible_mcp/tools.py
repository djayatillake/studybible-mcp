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

import html
import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

from mcp.types import Tool, ToolAnnotations

from .corpora import CORPORA, LINK_RELATIONS, TIERS, all_periods
from .database import (
    BOOK_DISPLAY_NAMES,
    HEBREW_PREFIX_LETTERS,
    format_biblical_range,
    parse_biblical_range,
    parse_passage_reference,
    strip_editorial_signs,
)
from .parsers.acai import is_name_label
from .parsers.biblical_versions import APOCRYPHA_PLURAL_NAMES
from .parsers.theographic import BOOKS as GRAPH_BOOKS
from .parsers.theographic import verse_position
from .published_text import (
    aquifer_rendering,
    aquifer_title,
    clean_aquifer_items,
    fix_ancient_row,
    safe_cut,
)


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
    """Truncate text to limit characters, appending suffix if truncated.

    A cut that would separate a published text's correction note from the
    text it corrects moves to the end of the note.
    """
    if len(text) <= limit:
        return text
    cut = safe_cut(text, limit)
    return text if cut >= len(text) else text[:cut] + suffix


# The ``offset`` argument of the paged list tools.
OFFSET_PARAMETER = {
    "type": "integer",
    "description": "Results to skip (from a 'Next page' note)",
}

RESEARCH_SOURCES_DEFAULT_LIMIT = 4
# With no topic or perspective, these lead the list so the default is a mix: an
# evangelical journal, a Bible reference tool, Jewish primary texts, and an
# academic site. The rest follow in catalogue order.
RESEARCH_SOURCES_DEFAULT_MIX = ("tyndale_bulletin", "step_bible", "sefaria", "bible_odyssey")
RESEARCH_SOURCES_MAX_LIMIT = 10

# lookup_ancient_source: passages per citation (default and maximum), excerpt
# caps per passage, and the whole response's budget (context economy).
ANCIENT_LOOKUP_DEFAULT = 4
ANCIENT_LOOKUP_LIMIT = 10
ANCIENT_ENGLISH_EXCERPT = 1500
ANCIENT_ORIGINAL_EXCERPT = 600
# With full_text the per-passage caps rise to these; the budget still applies.
ANCIENT_FULL_ENGLISH = 8000
ANCIENT_FULL_ORIGINAL = 3000
ANCIENT_RESPONSE_BUDGET = 12000
# Lines either side of a cited line in a line-numbered corpus (Qumran).
ANCIENT_LINE_CONTEXT = 2

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
- Definitions: Abbott-Smith for NT Greek (with LSJ's classical senses), LSJ
  for other Greek, BDB for Hebrew
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
- The English text: the Berean Standard Bible (BSB), or STEPBible's word
  gloss marked [gloss] where the BSB lacks the verse
- The original Greek/Hebrew text (optional, on by default)
- A word-by-word breakdown with Strong's numbers and glosses (single verses;
  for a passage only when include_morphology is set)
- Optional grammatical parsing for each word

And once for the passage:
- The passage's genre (interpretive guidance with include_genre)
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
                },
                "include_genre": {
                    "type": "boolean",
                    "description": "Append genre interpretive guidance. Default: false"
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

Rows are grouped by canonical MT/English reference and keep each edition's own reference, so Hebrew/Greek versification differences stay explicit (Psalm 82:6 = Greek Psa.81.6). MT: Westminster Leningrad Codex with STEPBible word glosses (not a translation). LXX: Rahlfs, with Brenton's English only where Brenton translated the same recension. Brenton translated his own Greek, not Rahlfs: where it differs the row warns and shows his Greek, and his English should be quoted as a rendering of that text; most Apocrypha rows carry the KJV Apocrypha instead. LXX-only verses (e.g. the Prayer of Azariah) need numbering='lxx'. One sources line (licences, verse-mapping credit) ends the output.""",
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
        description="""Find an ancient source passage by searching its words: Jewish texts of the
Second Temple world to c. AD 200 (Josephus on Herod, the temple, John the
Baptist and the Jewish revolt; Targum Onkelos, final form later; the Qumran rules; Philo;
1 Enoch and 4 Ezra; the Mishnah). None is Scripture: each result carries a
canon, date and edition tag, and each corpus's caveat and the sources are
printed once at the end.

English search is stemmed and matches only the translation's wording. Search
Greek, Hebrew and Aramaic in their own script (accents, vowel points and case
are ignored; transliterations such as "logos" do not match). Passages with
every word come first; otherwise passages with any word, and the output says
so. Only if nothing matches exactly is a Hebrew or Aramaic word retried
without prefix letters (ו ב ה ל מ כ ש), and those results are marked.

Only passage text is searched, not titles or references. `biblical_reference`
keeps passages with a curated editorial link (aligned, echo, shared tradition,
contrast) to that range, never keyword overlap. To read a passage by its
citation, use lookup_ancient_source.""",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "English or original-language words to search for (e.g. 'John Baptist', 'Herod temple', or 'βαπτισμῷ'). Write Greek, Hebrew, and Aramaic in their own script (accents optional); transliterations do not match. Search operators are ignored.",
                },
                "corpus": {
                    "type": "string",
                    "enum": [*CORPORA, "all"],
                    "default": "josephus",
                    "description": "Corpus to search, or 'all'. targum = Onkelos; qumran = CD, 1QS, 1QSa, 1QpHab; pseudepigrapha = 1 Enoch, 4 Ezra; rabbinic = Mishnah. Default: josephus",
                },
                "biblical_reference": {
                    "type": "string",
                    "description": "Optional chapter, verse, or verse range (e.g. 'Luke 21', 'Luke 21:5', 'Luke 21:5-6') limiting results to passages with a curated editorial link overlapping it",
                },
                "period": {
                    "type": "string",
                    "enum": list(all_periods()),
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
        name="lookup_ancient_source",
        annotations=ToolAnnotations(
            title="Look Up Ancient Source Citation",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
        ),
        description="""Look up an ancient source by citation and read it in English with the
original language: 'Antiquities 18.116', 'Ant. 15.320', 'War 6.316', 'Life 1',
'Onkelos Gen 49:10', 'CD 6:11', 'Opif. 26', '1 Enoch 1:9', '4 Ezra 7:28',
'm. Sukkah 4:9'. A work name or abbreviation is followed by a locator in that
work's numbering; a range returns the overlapping passages in order. None is
Scripture: each passage carries a canon, date and edition tag and any
editorial ⚠ notes; caveats and sources are printed once. An unknown or
ambiguous citation gets a short list of works or candidates. To find passages
by wording, use search_ancient_sources.""",
        inputSchema={
            "type": "object",
            "properties": {
                "citation": {
                    "type": "string",
                    "description": "Work and locator, e.g. 'Antiquities 18.116', 'Ant. 18.116-119', 'War 6.316', 'Josephus, Life 1'",
                },
                "corpus": {
                    "type": "string",
                    "enum": list(CORPORA),
                    "description": "Optional corpus to resolve the citation in. Default: every registered corpus",
                },
                "include_original": {
                    "type": "boolean",
                    "default": True,
                    "description": "Include the original-language text. Default: true",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": ANCIENT_LOOKUP_LIMIT,
                    "default": ANCIENT_LOOKUP_DEFAULT,
                    "description": f"Maximum passages. Default: {ANCIENT_LOOKUP_DEFAULT}",
                },
                "full_text": {
                    "type": "boolean",
                    "default": False,
                    "description": "Show whole passages instead of excerpts (English is cut at 1,500 characters, the original at 600). Default: false",
                },
            },
            "required": ["citation"],
        },
    ),
    Tool(
        name="search_lexicon",
        annotations=ToolAnnotations(title="Search Lexicon", readOnlyHint=True, destructiveHint=False, idempotentHint=True),
        description="""Search the Greek and Hebrew lexicons by English word, transliteration, or concept.

Returns the matching lexicon entries ranked by relevance — typically several
distinct original-language words that an English term covers (e.g. "love" →
agapē, agapaō, phileō), each with its Strong's number and brief definition.

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
                "offset": OFFSET_PARAMETER,
                "limit": {
                    "type": "integer",
                    "description": "Maximum results (1-20). Default: 4"
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

**Adaptive default — `limit` is a cap, not a target.** Default `limit=4`. Rows
are returned in tier-then-strength order, and tier-1 noise (low-vote TSK) is
suppressed by default whenever the verse has at least 3 rows from tier 2+. So:

  - Signal-rich anchors return up to `limit` strong refs from curated,
    scholarly, and consensus-TSK sources.
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
                "offset": OFFSET_PARAMETER,
                "limit": {
                    "type": "integer",
                    "description": "Cap on rows returned (not a target), 1-50. Default 4. The returned count may be smaller when the verse has fewer rows above the noise floor. Values of 20–30 combined with `source='tsk'` or `min_strength=0` return the long tail."
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

Covers 3,000+ people, 1,000+ places and 100+ other names (deities, festivals,
months). Returns the entry's original-language name, description, key verse
references, ACAI annotations where available (variant names, roles, reference
and speech counts), and its immediate relationships:

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
                },
                "offset": OFFSET_PARAMETER,
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20,
                    "default": 4,
                    "description": "Maximum entries; exact name matches come first, best known first. Default: 4"
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
For Hebrew: Westminster/OpenScriptures codes, as lookup_verse prints them:
prefixes joined by '/' ('Hc/Vqw3ms' = consecutive "and" + Qal imperfect),
with or without the language letter ('Vqp3ms'). Any case; a code not found
in the given language is tried in the other.

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
                "offset": OFFSET_PARAMETER,
                "limit": {
                    "type": "integer",
                    "description": "Maximum verses (1-50). Default: 4"
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
                    "description": "Bible verse (e.g., 'John 3:16', 'Daniel 7:13'); a range or chapter uses its first verse"
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of similar passages (1-20). Default: 4"
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

Traverses the parent links of 2,000 biblical persons. Returns a family tree
listing each relative once, generation by generation, with whose parent or
child they are, plus a Mermaid diagram of the tree (up to 40 people).

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
                    "description": "Generations to trace, 1 to 40. Default: 5"
                }
            },
            "required": ["person"]
        }
    ),
    Tool(
        name="people_in_passage",
        annotations=ToolAnnotations(title="People in Passage", readOnlyHint=True, destructiveHint=False, idempotentHint=True),
        description="""List the people, places, and events mentioned in a Bible passage.

Returns the entities recorded for a verse, range, or chapter in the Theographic
Bible Metadata — for example, Genesis 22 returns Abraham, Isaac, God, and Moriah;
Acts 15 returns Paul, Barnabas, James, Jerusalem, and Antioch. Nations tagged
under their ancestor's name (Israel, Judah, Moab) are listed apart.

Relevant for establishing the cast and setting of a narrative passage. Related
tools: `graph_enriched_search` is verse-level only but adds the verse text and
family relationships for each person found.""",
        inputSchema={
            "type": "object",
            "properties": {
                "reference": {
                    "type": "string",
                    "description": "Bible reference - chapter ('Romans 8'), verse ('Genesis 22:1'), or range ('Genesis 22:1-14', 'Psalm 23-24')"
                }
            },
            "required": ["reference"]
        }
    ),
    Tool(
        name="explore_person_events",
        annotations=ToolAnnotations(title="Explore Person Events", readOnlyHint=True, destructiveHint=False, idempotentHint=True),
        description="""Retrieve the recorded events of a biblical person's life in chronological order.

Returns each event once, with its approximate date where known, places, and
passage. Moses returns birth, burning bush, exodus, Sinai, and death on Nebo;
Paul returns conversion, missionary journeys, imprisonment, and Rome.

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
genealogies, preferring lines of descent, and returns the path (with a Mermaid
flowchart when it has at most 12 steps). Ruth and David return Ruth → Obed →
Jesse → David; Abraham and Moses trace through Levi. Where no family
connection exists, that is reported.

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
attribution. A chapter or verse range returns the Tyndale notes and lists the
verses with translator notes, for per-verse calls. For journal articles, see
`list_research_sources`.""",
        inputSchema={
            "type": "object",
            "properties": {
                "reference": {
                    "type": "string",
                    "description": "Bible reference (e.g., 'John 3:16', 'Genesis 1', 'Romans 8:28')"
                },
                "chapter_only": {
                    "type": "boolean",
                    "description": "If true, return the notes for the reference's whole chapter. Default: false"
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

Long articles come a page at a time; the truncation note says how to read on.""",
        inputSchema={
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "Topic to look up (e.g., 'Abraham', 'covenant', 'baptism', 'Pharisees')"
                },
                "section": {
                    "type": "string",
                    "description": "Heading of one section to read (a truncated article lists them)"
                },
                "offset": {
                    "type": "integer",
                    "description": "Character offset to continue a truncated article from"
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

Relevant for a precise definition of a key biblical term (grace, covenant,
righteousness, Son of Man, and similar), how a concept is used across
Scripture, or a translation-oriented explanation. Titles are English; an
unmatched term gets the closest entries' titles.""",
        inputSchema={
            "type": "object",
            "properties": {
                "term": {
                    "type": "string",
                    "description": "Key term to look up (e.g., 'grace', 'covenant', 'righteousness', 'Son of Man')"
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

The 13 dimensions and 9 periods are the `dimension` and `period` values.

With no arguments, returns the available dimensions and periods. With a
reference, returns the best matches (direct chapter matches first, `limit`
default 4). The dimension and period parameters narrow the result set. The
dimension 'ane_methodology' returns the derivation hierarchy, confidence
calibration, and methodological limits that apply to ANE parallels generally.""",
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
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum entries (1-30). Default: 4"
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

Returns scholarly content from multiple authors (Heiser, Bradley, etc.) with verse mappings and theme links. When no author is specified, every scholar's content is searched (theme results alternate between authors), allowing side-by-side comparison.

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
                    "description": "Bible verse or chapter (e.g., 'Psalm 82:1', 'Psalm 82', 'Genesis 6:2', 'John 8:44')"
                },
                "theme": {
                    "type": "string",
                    "description": "Theme key (e.g., 'divine_council', 'pater_familias_binary', 'domain_transfer', 'sin_death_satan_chain')"
                },
                "author": {
                    "type": "string",
                    "description": "Filter by author: 'heiser', 'bradley', 'owen', 'stott', 'lennox'. Omit to get all scholars' content."
                },
                "offset": OFFSET_PARAMETER,
                "limit": {
                    "type": "integer",
                    "description": "Maximum entries (1-20). Default: 4"
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
- With explain=true, Kline's guide to reading each direction of pairing

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
                },
                "explain": {
                    "type": "boolean",
                    "description": "Append Kline's full reading guide. Default: false"
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
- NT quotation alignment: separately catalogued links showing which form (an LXX form or the MT) an NT quotation follows
- Translation and interpretation notes: how a contested verse is read or rendered (e.g. divine-council language at Psalm 82:6); shown separately, after any manuscript variant at the verse, never as one

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
                    "description": f"Maximum sources (1-{RESEARCH_SOURCES_MAX_LIMIT}). Default: {RESEARCH_SOURCES_DEFAULT_LIMIT}"
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
    """Fill a source's search template with the URL-encoded query, if it has one.

    A source with a ``reference_url_template`` (STEP Bible's passage view) uses
    it when the query is a Bible reference, so 'Deuteronomy 32:8' opens the
    passage rather than a word search for it.
    """
    template = source.get("search_url_template")
    if source.get("reference_url_template") and parse_biblical_range(query) is not None:
        template = source["reference_url_template"]
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
    normalised = _normalise_topic(topic or "")
    if not normalised and not (perspective and perspective.strip()):
        lead = [s for key in RESEARCH_SOURCES_DEFAULT_MIX for s in sources if s["key"] == key]
        return lead + [s for s in sources if s["key"] not in RESEARCH_SOURCES_DEFAULT_MIX]
    if perspective and perspective.strip():
        wanted = perspective.strip().lower()
        sources = [s for s in sources if wanted in s["perspective"].lower()]
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


# word_study: definitions are cut at a sentence boundary near this length.
LEXICON_DEFINITION_LIMIT = 2000
# Glosses taken from a classical LSJ entry when Abbott-Smith covers the NT sense.
LSJ_GLOSS_COUNT = 8
_INVISIBLE_MARKS = re.compile("[\u200e\u200f\u202a-\u202e]")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")


def clean_lexicon_text(text: str | None) -> str:
    """Lexicon text with HTML entities decoded and direction marks removed.

    BDB and LSJ arrive with '&#x200E;' after Hebrew words and '&amp;', '&gt;',
    '&apos;', '&#8212;' in the prose; double-escaped entities are decoded too.
    """
    if not text:
        return ""
    for _ in range(2):
        decoded = html.unescape(text)
        if decoded == text:
            break
        text = decoded
    return _INVISIBLE_MARKS.sub("", text)


def cut_at_sentence(text: str, limit: int, suffix: str) -> str:
    """``text`` cut to at most ``limit`` characters at a sentence end, with ``suffix``."""
    if len(text) <= limit:
        return text
    head = text[:limit]
    cut = max(head.rfind(mark) for mark in (". ", ".\n", "; ", "\n"))
    if cut < limit // 2:
        cut = head.rfind(" ")
    return head[: cut + 1].rstrip() + suffix


def lsj_glosses(full_definition: str, count: int = LSJ_GLOSS_COUNT) -> str:
    """The English senses an LSJ entry prints in bold ('trust, faith, persuasion, ...').

    Sense numbers ('**__2**') and the Greek headword are skipped. An entry with
    no bold senses gives its first sentence instead.
    """
    glosses: list[str] = []
    for match in _BOLD.finditer(full_definition):
        text = match.group(1).strip()
        if text.startswith("__") or re.search(r"[\u0370-\u03ff\u1f00-\u1fff]", text):
            continue
        for part in re.split(r"[,;]", text):
            part = part.strip(" .:—-")
            if part and part.lower() not in (gloss.lower() for gloss in glosses):
                glosses.append(part)
    if glosses:
        more = ", …" if len(glosses) > count else ""
        return ", ".join(glosses[:count]) + more
    return cut_at_sentence(full_definition, 200, " …")


def format_lexicon_entry(entry: dict) -> str:
    """Format a lexicon entry for display.

    Shows separate sections for brief and full definitions when both exist.
    A Greek word with an Abbott-Smith (NT) entry shows that entry, with the
    classical LSJ entry reduced to its glosses; other Greek entries show the
    "Full LSJ Definition", Hebrew entries the "Full BDB Definition". Text is
    cleaned of HTML entities and cut at a sentence boundary.
    """
    lines = []

    # Header
    lines.append(f"## {entry['strongs']} - {entry['word']}")
    lines.append(f"**Transliteration**: {entry['transliteration']}")
    if entry.get('pronunciation') and entry['pronunciation'] != entry['transliteration']:
        lines.append(f"**Pronunciation**: {entry['pronunciation']}")
    lines.append(f"**Language**: {entry['language'].title()}")
    lines.append("")

    short_def = clean_lexicon_text(entry.get('short_definition'))
    full_def = clean_lexicon_text(entry.get('full_definition'))
    abbott_def = clean_lexicon_text(entry.get('abbott_smith_def'))
    syn_text = clean_lexicon_text(entry.get('synonyms'))
    nt_focused = bool(abbott_def) and entry.get('language') == 'greek'

    def definition(text: str, source: str) -> str:
        return cut_at_sentence(
            text, LEXICON_DEFINITION_LIMIT,
            f"\n\n*[Definition cut — the full entry is in {source}]*",
        )

    if short_def and full_def and short_def != full_def:
        lines.append("### Brief Definition")
        lines.append(short_def)
        lines.append("")
        # An NT word's sense comes from Abbott-Smith below, LSJ's as glosses.
        if not nt_focused:
            source = {"greek": "LSJ", "hebrew": "BDB"}.get(entry.get('language'))
            lines.append(f"### Full {source} Definition" if source else "### Full Definition")
            lines.append(definition(full_def, source or "the lexicon"))
            lines.append("")
    elif full_def and not nt_focused:
        lines.append("### Definition")
        lines.append(definition(full_def, "the lexicon"))
        lines.append("")
    elif short_def:
        lines.append("### Definition")
        lines.append(short_def)
        lines.append("")
    elif not nt_focused:
        lines.append("### Definition")
        lines.append("No definition available.")
        lines.append("")

    # Etymology
    if entry.get('etymology'):
        lines.append("### Etymology")
        lines.append(clean_lexicon_text(entry['etymology']))
        lines.append("")

    # Semantic range
    domains = _parse_json_field(entry.get('semantic_domain'))
    if domains:
        lines.append("### Semantic Range")
        lines.append(", ".join(domains))
        lines.append("")

    # Usage: one line (for a Greek word the Bible count is its NT count)
    usage = entry.get('usage_count')
    nt_count = entry.get('nt_occurrences')
    if nt_count and (not usage or usage == nt_count):
        lines.append(f"**Usage**: Occurs {nt_count} times in the New Testament")
        lines.append("")
    elif usage:
        nt_note = f" ({nt_count} in the New Testament)" if nt_count else ""
        lines.append(f"**Usage**: Occurs {usage} times in the Bible{nt_note}")
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

    # Abbott-Smith definition (NT-focused). Its synonym note is printed once,
    # under Synonyms, when the entry also carries it separately.
    if abbott_def:
        if syn_text and syn_text in abbott_def:
            abbott_def = abbott_def.replace(f"**Synonyms**: {syn_text}", "").replace(syn_text, "")
            abbott_def = re.sub(r"[ \t]{2,}", " ", abbott_def).strip()
        lines.append("### Abbott-Smith Definition (NT-Focused)")
        lines.append(definition(abbott_def, "Abbott-Smith"))
        lines.append("")
    if nt_focused and full_def:
        lines.append("### LSJ Senses (Classical Greek)")
        lines.append(lsj_glosses(full_def))
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
    if syn_text:
        lines.append("### Synonyms")
        lines.append(syn_text)
        lines.append("")

    return "\n".join(lines)


def _verse_heading(verse: dict) -> str:
    """Heading for a verse; English verse 0 is a Psalm superscription.

    STEPBible stores superscriptions as English verse 0 with the Hebrew verse
    in parentheses ('Psa.82.0(82.1)'), which reads oddly next to 'Psa.82.1'.
    Rows with the BSB loaded carry their heading as ``label`` (see
    ``database.verse_label``).
    """
    if verse.get("label"):
        return verse["label"]
    reference = verse["reference"]
    if verse.get("verse") != 0:
        return reference
    match = re.match(r"^([^.]+)\.(\d+)\.0(?:\((\d+\.\d+)\))?$", reference)
    if not match:
        return reference
    book, chapter, hebrew = match.groups()
    label = f"{book}.{chapter} superscription"
    return f"{label} (Hebrew {book}.{hebrew})" if hebrew else label


# Marks STEPBible's word-by-word gloss where a response labelled BSB has no
# BSB text for a verse.
GLOSS_MARK = "[gloss]"


def verse_english(verse: dict) -> str:
    """A verse row's English line: its BSB text, else the STEPBible gloss.

    Rows carry ``text_bsb`` only when the database has the BSB, and the gloss
    is then marked; without the BSB the gloss is shown unmarked.
    """
    gloss = verse.get("text_english") or ""
    if "text_bsb" not in verse:
        return gloss
    if verse["text_bsb"]:
        return verse["text_bsb"]
    return f"{GLOSS_MARK} {gloss}".rstrip()


def display_original(text: str) -> str:
    """Original-language text without STEPBible's word markup.

    TAHOT separates morphemes with '/' and escapes punctuation with '\\'
    ('וַ/יִּקַּ֨ח', 'אֶת\\־', 'דָוִֽד\\׃'); a maqaf joins its words.
    """
    text = text.replace("\\׀", " ׀").replace("/", "").replace("\\", "")
    return re.sub(r"־\s+", "־", text)


def verse_reference(verse: dict) -> str:
    """A verse row's reference as shown: English first (see ``_verse_heading``)."""
    return _verse_heading(verse)


def non_na_editions(verse: dict, strongs: str) -> str | None:
    """The editions that alone have ``strongs`` in this verse, if NA28 lacks it.

    TAGNT tags words found only in some Greek editions (Mark 9:29 "and
    fasting": Tyn+Treg+TR+Byz) with their editions in the word data; the BSB,
    following NA28, usually has no word for them. None when any occurrence of
    the number is in NA28, or the word data has no editions.
    """
    match = re.fullmatch(r"([GH])0*(\d{1,5})[A-Za-z]?", strongs.strip().upper())
    if not match:
        return None
    wanted = (match[1], int(match[2]))
    editions = []
    for word in _parse_json_field(verse.get("word_data"), []):
        if not isinstance(word, dict):
            continue
        found = re.fullmatch(r"([GH])0*(\d{1,5})[A-Za-z]?", str(word.get("strongs") or ""))
        if found and (found[1], int(found[2])) == wanted:
            if not word.get("editions"):
                return None
            editions.append(word["editions"])
    return " / ".join(dict.fromkeys(editions)) or None


def strongs_verse_note(verse: dict, strongs: str) -> str:
    """' *(...)*' after a search_by_strongs verse whose word is not in NA28, else ''."""
    editions = non_na_editions(verse, strongs)
    if not editions:
        return ""
    return f" *(word only in {editions} Greek, not NA28; the BSB may lack it)*"


def bsb_label(verses: list[dict]) -> str:
    """' (BSB)' for the heading of a response that shows any BSB text, else ''."""
    return " (BSB)" if any(verse.get("text_bsb") for verse in verses) else ""


def format_verse(
    verse: dict,
    include_original: bool = True,
    include_morphology: bool = False,
    include_words: bool = True,
    heading_note: str = "",
) -> str:
    """Format a verse for display; ``include_words`` controls the word list."""
    lines = []

    lines.append(f"## {_verse_heading(verse)}{heading_note}")
    lines.append("")
    lines.append(verse_english(verse) or "No English text available.")
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
# The verse-mapping credit (VERSE_MAPPING_CREDIT) in the one-line sources.
VERSE_MAPPING_SHORT_CREDIT = (
    "OpenScriptorium lxx-morph, partly from TVTMS, CC BY 4.0, STEPBible.org / "
    "Tyndale House Cambridge"
)
# Shown when Brenton's English appears and no row's Greek differs; the full
# BRENTON_TRANSLATION_NOTE accompanies a row whose Greek differs.
BRENTON_SHORT_NOTE = (
    "Brenton's English renders his own Greek edition (chiefly Vaticanus), not the Rahlfs text shown."
)


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
    edition reference. Each row names its version, edition, edition reference,
    and English label. One closing Sources line gives each edition's licence
    and source and the verse-mapping credit; then, once each, a one-line
    Brenton note (the full caveat only when a row's Greek differs from his),
    the KJV Apocrypha caveat, and the canon note for Apocrypha rows (marked
    "(Apocrypha)").
    """
    title = f"## Biblical Version Comparison: {reference}"
    if numbering == "lxx":
        title += " (Septuagint edition numbering)"
    lines = [title, ""]
    if note:
        lines.extend([f"*{note}*", ""])
    current_group: str | None = None
    sources: dict[tuple[str, str], dict] = {}
    apocrypha: dict[str, None] = {}
    brenton_note = ""
    kjv_note = ""
    brenton_greek_url = ""
    greek_differs = False
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
        if row.get("apocrypha"):
            header += " (Apocrypha)"
            apocrypha[row["apocrypha"]] = None
        lines.append(header)
        if include_original:
            lines.append(f"**{row['language']}:** {row['text']}")
        if row.get("brenton_greek_differs"):
            greek_differs = True
            lines.append(
                "> **Warning: Brenton's English below translates a different Greek text.** "
                f"His own Greek differs from the Rahlfs text here: {row['brenton_greek_difference']}"
            )
            brenton_greek_url = row.get("brenton_greek_source_url") or brenton_greek_url
            if include_original:
                lines.append(
                    f"**Brenton's Greek (the text his English translates):** {row['brenton_greek']}"
                )
        if row.get("kjv_apocrypha"):
            label = "KJV Apocrypha"
        else:
            label = _SHORT_ENGLISH_LABELS.get(row["version"]) or row.get("translation_label") or "English"
        if row.get("translation"):
            lines.append(f"**English ({label}):** {row['translation']}")
        else:
            lines.append("**English:** not available for this edition.")
        if row.get("kjv_apocrypha"):
            kjv_note = row["translation_note"]
        elif row.get("translation_note"):
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

    # One sources line: each edition's licence and source, the verse-mapping
    # credit, and (where Brenton's English is shown) what his English renders.
    # Editions sharing a licence and source (Rahlfs and its Sinaiticus
    # recension) are named together; row labels already name each English.
    by_source: dict[tuple[str, str], list[str]] = {}
    for (version, edition), row in sources.items():
        by_source.setdefault((row["license"], row["source_url"]), []).append(f"{version} {edition}")
    parts = [
        f"{' and '.join(names)} ({license_}) {url}" for (license_, url), names in by_source.items()
    ]
    if brenton_greek_url:
        parts.append(f"Brenton's Greek (public domain) {brenton_greek_url}")
    parts.append(f"verse mapping: {VERSE_MAPPING_SHORT_CREDIT}")
    lines.extend(["---", f"*Sources: {' · '.join(parts)}.*"])
    if brenton_note and not greek_differs:
        lines.append(f"*{BRENTON_SHORT_NOTE}*")
    if apocrypha:
        names = list(apocrypha)
        listed = names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"
        verb = "are" if len(names) > 1 or names[0] in APOCRYPHA_PLURAL_NAMES else "is"
        lines.append(
            f"\n*Apocrypha: {listed} {verb} not in the Protestant canon "
            "(cf. Westminster Confession 1.3); background only.*"
        )
    if brenton_note and greek_differs:
        lines.append(f"\n*Brenton's English: {brenton_note}*")
    if kjv_note:
        lines.append(f"\n*KJV Apocrypha English: {kjv_note}*")
    return "\n".join(lines).rstrip()


def _format_ancient_biblical_link(link: dict) -> str:
    """'Echo: Jude 14–15 — Related text: ...' (relation, biblical range, editorial note).

    A parenthesised note qualifies the reference itself: 'Translation of: Exod
    8:5 (MT 8:1)'.
    """
    start_chapter, start_verse = divmod(link["sort_start"], 1000)
    end_chapter, end_verse = divmod(link["sort_end"], 1000)
    reference = format_biblical_range(
        link["biblical_book"], start_chapter, start_verse, end_chapter, end_verse
    )
    relation = LINK_RELATIONS.get(link.get("relation") or "", "Link")
    note = link.get("relationship_note")
    if not note:
        return f"{relation}: {reference}"
    return f"{relation}: {reference}" + (f" {note}" if note.startswith("(") else f" — {note}")


def _format_ancient_note(note: dict, reference: str) -> str:
    """'⚠ <note> (Contrast: Mark 14:62. Aligned: Jude 6)', naming the citation if it differs."""
    related = "; ".join(
        f"{label}: {note[field]}" for field, label in (("contrast", "Contrast"), ("aligned", "Aligned"))
        if note.get(field)
    ).replace("; Aligned:", ". Aligned:")
    where = "" if note["citation"] == reference else f"{note['citation']}: "
    return f"⚠ {where}{note['note']}" + (f" ({related})" if related else "")


def _fold_with_positions(text: str) -> tuple[str, list[int]]:
    """Fold text as the search index does, keeping each kept character's position.

    Accents, vowel points, cantillation, circlets, format characters, and
    editorial signs are dropped and case is folded, so ``הַשְּׁקָלִים`` and
    ``אלמנ֯[ו]ת`` read as ``השקלים`` and ``אלמנות``. ``positions[i]`` is the index
    in ``text`` of folded character ``i``.
    """
    chars: list[str] = []
    positions: list[int] = []
    for index, ch in enumerate(text):
        if unicodedata.category(ch) in ("Mn", "Cf") or not strip_editorial_signs(ch):
            continue
        base = "".join(
            c for c in unicodedata.normalize("NFD", ch) if not unicodedata.combining(c)
        ).casefold()
        chars.append(base[:1] or ch)
        positions.append(index)
    return "".join(chars), positions


_HEBREW_WORD = re.compile(r"[\u05d0-\u05ea]+")


def _match_start(text: str, query: str, limit: int) -> int | None:
    """Where an excerpt of ``limit`` characters around the first query match starts.

    Matching folds like the search index and accepts a word stem (``build``
    finds ``building``) and, for a Hebrew/Aramaic word, one or two attached
    prefix letters (``הון`` finds ``ובהון``). None when nothing matches.
    """
    folded, folded_positions = _fold_with_positions(text)
    positions = []
    for word in re.findall(r"\w+", _fold_with_positions(query)[0]):
        stem = word if len(word) <= 5 else word[: len(word) - 2]
        if _HEBREW_WORD.fullmatch(word):
            pattern = rf"(?<!\w)[{HEBREW_PREFIX_LETTERS}]{{0,2}}{re.escape(stem)}"
        else:
            pattern = rf"\b{re.escape(stem)}"
        found = re.search(pattern, folded)
        if found:
            positions.append(folded_positions[found.start()])
    return max(0, min(positions) - limit // 5) if positions else None


def _aligned_start(start: int, source: str, target: str) -> int:
    """The point of ``target`` at the same proportion as ``start`` in ``source``, at a sentence start.

    A bilingual passage's two excerpts then cover roughly the same text when
    only one of them matched the query (an English query never matches the
    Hebrew). The point moves back to just after a nearby sentence end.
    """
    point = round(start * len(target) / max(len(source), 1))
    sentence = max(target.rfind(mark, max(0, point - 80), point) for mark in (". ", ": ", "; ", "· "))
    return sentence + 2 if sentence >= 0 else point


def _match_excerpt(text: str, query: str, limit: int, fallback_start: int = 0) -> str:
    """Return up to ``limit`` characters of ``text`` around the first query match.

    Without a match the excerpt starts at ``fallback_start`` (the beginning
    unless aligned with the other language's excerpt). Ellipses mark text cut
    at either end.
    """
    if len(text) <= limit:
        return text
    start = _match_start(text, query, limit)
    if start is None:
        start = min(fallback_start, max(0, len(text) - limit))
    if start and not text[start - 1].isspace():
        space = text.find(" ", start)
        start = space + 1 if 0 <= space < start + 40 else start
    end = min(len(text), start + limit)
    if end < len(text):
        space = text.rfind(" ", start, end)
        end = space if space > start + limit // 2 else end
    return f"{'…' if start else ''}{text[start:end]}{'…' if end < len(text) else ''}"


_ORIGINAL_SCRIPT = re.compile(r"[\u0370-\u03ff\u1f00-\u1fff\u0590-\u05ff]")
_NC_LICENSE = re.compile(r"CC BY-NC(-SA)? (\d\.\d)")


def _passage_heading(row: dict) -> str:
    """'### Flavius Josephus, Antiquities 18.116–119 (Whiston 18.5.2)', without a repeated author."""
    reference = row["reference"]
    heading = reference if reference.startswith(row["author"]) else f"{row['author']}, {reference}"
    if row.get("alternate_reference"):
        heading += f" ({row['alternate_reference']})"
    return f"### {heading}"


def _row_tag(row: dict, default_corpus: str | None) -> tuple[str, tuple[str, ...]]:
    """The italic per-result tag (labelling contract L1) and the tiers it names."""
    registered = CORPORA.get(row.get("corpus") or default_corpus or "")
    if registered is None:
        return "Not Scripture", ()
    tag, section = registered.tag_for(row.get("work_key"), row.get("sort_start"))
    if tag is None:
        return "Not Scripture", ()
    return tag.line(section), tuple(tag.tier_for(section).split("/"))


def _line_window(row: dict, window: tuple[int, int] | None) -> tuple[str, str | None]:
    """A line-numbered original cut to the lines whose keys fall in ``window``.

    Returns the text and a note naming the lines shown, or the whole text and
    None when the window covers the passage (or the corpus is not line-numbered).
    """
    text = row["original_text"]
    registered = CORPORA.get(row.get("corpus") or "")
    if window is None or registered is None or not registered.line_numbered:
        return text, None
    try:
        scale = registered.work(row["work_key"]).locator.scale
    except (KeyError, AttributeError):
        return text, None
    base = row["sort_start"] - row["sort_start"] % scale
    kept = []
    for line in text.splitlines():
        number = line.split(" ", 1)[0]
        if number.isdigit() and window[0] <= base + int(number) <= window[1]:
            kept.append(line)
    if not kept or len(kept) == len(text.splitlines()):
        return text, None
    first, last = kept[0].split(" ", 1)[0], kept[-1].split(" ", 1)[0]
    column = base // scale
    lines = f"{column}:{first}" if first == last else f"{column}:{first}–{last}"
    return "\n".join(kept), (
        f"Lines {lines} shown (the cited line ±{ANCIENT_LINE_CONTEXT}); "
        f"cite the column for all of it."
    )


def _excerpt(text: str, query: str, limit: int, note_cut: bool, fallback_start: int = 0) -> str:
    excerpt = _match_excerpt(text, query, limit, fallback_start)
    if note_cut and len(text) > limit:
        excerpt += f" *[excerpt of {len(text):,} characters; full_text=true shows more]*"
    return excerpt


def _ancient_passage_lines(
    row: dict,
    corpus: str | None,
    query: str,
    *,
    include_original: bool,
    english_limit: int,
    original_limit: int,
    seen_notes: set,
    note_cut: bool = False,
    window: tuple[int, int] | None = None,
) -> tuple[list[str], tuple[str, ...]]:
    """One passage: heading, tag, editorial heading, excerpts, ⚠ notes and typed links."""
    row = fix_ancient_row(row)
    registered = CORPORA.get(row.get("corpus") or corpus or "")
    language = row.get("original_language") or (
        registered.original_language if registered else "Original-language"
    )
    tag, tiers = _row_tag(row, corpus)
    lines = [_passage_heading(row), f"*{tag}*"]
    if row.get("editorial_heading"):
        label = registered.heading_label if registered else "Editorial heading"
        lines.append(f"*{label} (editorial): {row['editorial_heading']}*")
    original_query = query if _ORIGINAL_SCRIPT.search(query) else ""
    if row.get("text"):
        english = row["text"]
        original = limit = None
        if row.get("original_text") and include_original:
            original, _ = _line_window(row, window)
            limit = original_limit * 2 if original_query else original_limit
        # The language that matched the query sets where the other's excerpt starts.
        english_start = _match_start(english, query, english_limit)
        original_start = None
        if original and original_query:
            original_start = _match_start(original, original_query, limit)
        if original and original_start is None and english_start:
            original_start = _aligned_start(english_start, english, original)
        elif original_start and english_start is None:
            english_start = _aligned_start(original_start, original, english)
        lines.extend(["", _excerpt(english, query, english_limit, note_cut, english_start or 0)])
        if original:
            excerpt = _excerpt(original, original_query, limit, note_cut, original_start or 0)
            lines.extend(["", f"**{language}:** {excerpt}"])
    elif row.get("original_text"):
        # Without English the original is the passage: centre it on the match.
        original, shown = _line_window(row, window)
        missing = registered.no_english_note if registered else "No English translation included"
        lines.extend(["", f"*{missing}; {language} only.*"])
        if shown:
            lines.append(f"*{shown}*")
        lines.extend(["", f"**{language}:** {_excerpt(original, query, english_limit, note_cut)}"])
    for note in row.get("editorial_notes") or ():
        key = (note["citation"], note["kind"], note["note"])
        if key not in seen_notes:
            seen_notes.add(key)
            lines.extend(["", _format_ancient_note(note, row["reference"])])
    if row.get("biblical_links"):
        lines.append("")
        lines.extend(f"- {_format_ancient_biblical_link(link)}" for link in row["biblical_links"])
    lines.extend(["", "---", ""])
    return lines, tiers


def _license_text(license_: str) -> str:
    """The licence, with non-commercial licences marked and linked."""
    def mark(match: re.Match) -> str:
        variant = "by-nc-sa" if match.group(1) else "by-nc"
        return (
            f"{match.group(0)} (non-commercial; "
            f"https://creativecommons.org/licenses/{variant}/{match.group(2)}/)"
        )
    return _NC_LICENSE.sub(mark, license_)


def _closing_block(rows: list[dict], corpus: str | None, tiers: set[str]) -> list[str]:
    """Caveats once per corpus present (labelling contract L2), the tier key, and Sources once."""
    lines = ["**Caveats**"]
    present = dict.fromkeys(row.get("corpus") or corpus or "" for row in rows)
    for key in present:
        registered = CORPORA.get(key)
        if registered and registered.caveat:
            lines.append(f"- {registered.label}: {registered.caveat}")
        elif key:
            lines.append(f"- {registered.label if registered else key}: Not Scripture.")
    for tier in sorted(tiers & set(TIERS)):
        lines.append(f"- Tier {tier}: {TIERS[tier]}.")
    sources: dict[tuple, list[str]] = {}
    for row in rows:
        registered = CORPORA.get(row.get("corpus") or corpus or "")
        label = registered.label if registered else (row.get("corpus") or "Ancient source")
        language = row.get("original_language") or (
            registered.original_language if registered else "Original-language"
        )
        translation = row["translation"] if row.get("text") else "none included"
        key = (label, language, row["edition"], translation, row["license"])
        if row["source_url"] not in sources.setdefault(key, []):
            sources[key].append(row["source_url"])
    lines.extend(["", "**Sources**"])
    for (label, language, edition, translation, license_), urls in sources.items():
        lines.append(
            f"- {label}: {language}: {edition}. English: {translation}. "
            f"License: {_license_text(license_)}. " + " ".join(urls)
        )
    return lines


def format_ancient_source_results(
    query: str,
    rows: list[dict],
    corpus: str,
    biblical_reference: str | None = None,
    period: str | None = None,
    match: str = "all",
    prefix_match: bool = False,
    variants: dict[str, list[str]] | None = None,
) -> str:
    """Format primary-source results compactly, with caveats and provenance listed once.

    Each result shows a heading, its canon/date/edition tag, an excerpt of the
    English around the first match, a shorter original-language excerpt (a
    longer, match-centred one when the query is in Greek or Hebrew script),
    editorial ⚠ notes and typed biblical links. Without English, the original
    is the excerpt. Results stop at the response budget. ``variants`` maps a
    search term to the other spellings searched with it ('Melchisedec').
    """
    filters = [f"corpus={corpus}"]
    if biblical_reference:
        filters.append(f"biblical_reference={biblical_reference}")
    if period:
        filters.append(f"period={period}")
    lines = [f"## Ancient Source Search: {query}", "", f"*Filters: {', '.join(filters)}*", ""]
    if match == "any":
        lines.extend(["*No passage contains all terms; showing passages matching any term.*", ""])
    if prefix_match:
        lines.extend([
            "*No exact match: these passages match only after stripping Hebrew/Aramaic prefix "
            "letters (ו ב ה ל מ כ ש), which can also match a different word (קדש finds מקדש).*",
            "",
        ])
    excerpt_query = query
    if variants:
        listed = "; ".join(f"{term}: {', '.join(found)}" for term, found in variants.items())
        lines.extend([f"*Spelling variants also searched ({listed}).*", ""])
        excerpt_query = " ".join([query, *(word for found in variants.values() for word in found)])
    default_corpus = None if corpus == "all" else corpus
    tiers: set[str] = set()
    seen_notes: set = set()
    shown: list[dict] = []
    for row in rows:
        block, row_tiers = _ancient_passage_lines(
            row, default_corpus, excerpt_query, include_original=True,
            english_limit=ANCIENT_ENGLISH_EXCERPT, original_limit=ANCIENT_ORIGINAL_EXCERPT,
            seen_notes=seen_notes,
        )
        if prefix_match:
            block[0] += " (prefix match)"
        if shown and sum(map(len, lines)) + sum(map(len, block)) > ANCIENT_RESPONSE_BUDGET:
            lines.extend([f"*{len(rows) - len(shown)} more results omitted to keep the response short.*", ""])
            break
        lines.extend(block)
        tiers.update(row_tiers)
        shown.append(row)
    lines.extend(_closing_block(shown, default_corpus, tiers))
    return "\n".join(lines).rstrip()


def format_ancient_source_lookup(
    heading: str,
    resolution_note: str,
    rows: list[dict],
    total: int,
    include_original: bool = True,
    full_text: bool = False,
    window: tuple[int, int] | None = None,
    next_citation=None,
) -> str:
    """Format the passages overlapping one resolved citation, in citation order.

    Excerpts are capped per passage (unless ``full_text``) and the response
    stops at ``ANCIENT_RESPONSE_BUDGET`` characters, saying where to continue.
    ``window`` (a sort-key range) cuts a line-numbered original to the cited
    lines; ``next_citation(row)`` renders the citation to continue from.
    """
    lines = [f"## {heading}", "", f"*{resolution_note}*", ""]
    if total > len(rows):
        lines.extend([
            f"*Showing the first {len(rows)} of {total} overlapping passages; cite a "
            f"narrower range or raise limit (at most {ANCIENT_LOOKUP_LIMIT}) to read more.*",
            "",
        ])
    tiers: set[str] = set()
    seen_notes: set = set()
    shown: list[dict] = []
    for row in rows:
        block, row_tiers = _ancient_passage_lines(
            row, None, "", include_original=include_original,
            english_limit=ANCIENT_FULL_ENGLISH if full_text else ANCIENT_ENGLISH_EXCERPT,
            original_limit=ANCIENT_FULL_ORIGINAL if full_text else ANCIENT_ORIGINAL_EXCERPT,
            seen_notes=seen_notes, note_cut=not full_text, window=window,
        )
        if shown and sum(map(len, lines)) + sum(map(len, block)) > ANCIENT_RESPONSE_BUDGET:
            resume = f" Continue from {next_citation(row)}." if next_citation else ""
            lines.extend([
                f"*Stopped at the {ANCIENT_RESPONSE_BUDGET:,}-character response budget after "
                f"{len(shown)} passages.{resume}*",
                "",
            ])
            break
        lines.extend(block)
        tiers.update(row_tiers)
        shown.append(row)
    lines.extend(_closing_block(shown, None, tiers))
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


# Translations whose decisions stay in the database but are never printed: the
# HLT is the owner's own unpublished translation, not a published authority.
WITHHELD_TRANSLATIONS = frozenset({"Heiser Literal Translation (HLT)"})


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

    decisions = [
        decision for decision in case.get("translation_decisions") or []
        if decision.get("translation") not in WITHHELD_TRANSLATIONS
    ]
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


def _format_interpretive_case(
    case: dict, shown_readings: set[tuple[str, str | None]] | None = None
) -> list[str]:
    """Format an agreed-text case: the MT reading, then the attributed layers.

    ``shown_readings`` holds the (text, original_text) of readings already shown
    by a manuscript variant at the same verse. The notes then say the evidence
    is in that record, and skip a text block that would repeat it.
    """
    if shown_readings is None:
        banner = (
            "*Not a manuscript variant: the witnesses agree with the Masoretic Text "
            "here. These notes record how the verse is read and translated.*"
        )
    else:
        banner = (
            "*Not manuscript evidence: these notes record how the verse is read and "
            "translated. The textual evidence at this verse is in the variant record "
            "above.*"
        )
    lines = [
        f"## Translation and interpretation notes at {case['reference']}",
        banner,
        f"**Case key:** {case['case_key']}",
    ]
    if case.get("significance"):
        lines.append(f"**Significance classification:** {case['significance']}")
    for reading in case.get("manuscript_evidence") or []:
        if (reading["text"], reading.get("original_text")) in (shown_readings or set()):
            continue
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
    """Format evidence, judgments, interpretations, and claims as separate sections.

    Where a verse has both a manuscript variant and interpretation notes, the
    variant comes first and the notes point back to it.
    """
    if cases and all(case.get("kind") == "interpretive" for case in cases):
        lines = [f"# Translation and interpretation notes for {reference}", ""]
    else:
        lines = [f"# Textual variant record for {reference}", ""]
    variant_cases = [case for case in cases if case.get("kind") != "interpretive"]
    shown_readings: dict[str, set[tuple[str, str | None]]] = {}
    for case in variant_cases:
        shown_readings.setdefault(case["reference"], set()).update(
            (reading["text"], reading.get("original_text"))
            for reading in case.get("manuscript_evidence") or []
        )
    for case in variant_cases + [case for case in cases if case.get("kind") == "interpretive"]:
        if case.get("kind") == "interpretive":
            lines.extend(
                _format_interpretive_case(case, shown_readings.get(case["reference"]))
            )
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


_TIPNR_LINK_RE = re.compile(r"([A-Za-z][\w'-]*)@[\w.]+(?:-\w+)?(?:=[A-Z]\d+[A-Za-z]?)?")
_TIPNR_NUMBERED_RE = re.compile(r"\b([A-Za-z][\w'-]*?)_(\d+)(=\s*)?")


def humanize_tipnr(text: str) -> str:
    """TIPNR's internal names made readable: 'father_of_Barnabas' -> 'father of
    Barnabas', 'Ai_2= near Heshbon (Heshbon@Num.21.25-Jer=H2809)' -> 'Ai (2), near
    Heshbon (Heshbon)'."""
    text = _TIPNR_LINK_RE.sub(r"\1", text)
    text = _TIPNR_NUMBERED_RE.sub(lambda m: f"{m[1]} ({m[2]})" + (", " if m[3] else ""), text)
    return re.sub(r"(?<=\w)_(?=\w)", " ", text)


def format_name_entry(entry: dict, acai_data: dict | None = None) -> str:
    """Format a name entry for display, optionally enriched with ACAI data."""
    lines = []

    lines.append(f"### {humanize_tipnr(entry['name'])}")
    if entry.get('name_original'):
        lines.append(f"**Original**: {entry['name_original']}")
    lines.append(f"**Type**: {entry.get('type', 'Unknown').title()}")
    lines.append("")

    if entry.get('description'):
        lines.append(humanize_tipnr(entry['description']))
        lines.append("")

    # ACAI enrichment
    if acai_data:
        acai_parts = []

        if acai_data.get('description'):
            acai_parts.append(f"**Description**: {acai_data['description']}")

        # Variant names, other than the entry's own
        own = {entry['name'].lower(), humanize_tipnr(entry['name']).lower()}
        variants = [
            v for v in _parse_json_field(acai_data.get('referred_to_as')) or []
            if str(v).lower() not in own and is_name_label(str(v))
        ]
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
                names = value if isinstance(value, list) else [value]
                lines.append(f"- {key.title()}: {', '.join(humanize_tipnr(str(n)) for n in names)}")
        lines.append("")

    # The names table stores these in the 'refs' column.
    refs = _parse_json_field(entry.get('refs') or entry.get('references'))
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
    notes = clean_aquifer_items(notes)

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


#: A chapter or passage of study notes is cut, at a note boundary, near this size.
STUDY_NOTES_PASSAGE_BUDGET = 10_000
_TRANSLATOR_NOTE_LABELS = {
    "translation_notes_sil": "SIL",
    "translation_notes_uw": "unfoldingWord",
}


def _aquifer_chapter_verse(ref: str) -> tuple[int, int]:
    """(chapter, verse) of an Aquifer reference such as '45008019'."""
    return int(ref[2:5]), int(ref[5:8])


def _verse_list(pairs: set[tuple[int, int]]) -> str:
    """'8:1–17, 19–39; 9:1' for a set of (chapter, verse) pairs."""
    by_chapter: dict[int, list[int]] = {}
    for chapter, verse in sorted(pairs):
        by_chapter.setdefault(chapter, []).append(verse)
    parts = []
    for chapter, verses in by_chapter.items():
        runs = [[verses[0], verses[0]]]
        for verse in verses[1:]:
            if verse == runs[-1][1] + 1:
                runs[-1][1] = verse
            else:
                runs.append([verse, verse])
        listed = ", ".join(str(a) if a == b else f"{a}–{b}" for a, b in runs)
        parts.append(f"{chapter}:{listed}")
    return "; ".join(parts)


def format_passage_study_notes(
    label: str,
    notes: list[dict],
    book_name: str,
    span: tuple[tuple[int, int], tuple[int, int]],
    budget: int = STUDY_NOTES_PASSAGE_BUDGET,
) -> str:
    """Study notes for a chapter or passage: Tyndale in full, translator notes as a verse list.

    The SIL and unfoldingWord translator notes run to tens of kilobytes a
    chapter, so they are listed by verse for a per-verse call. Tyndale notes
    stop at a note boundary near ``budget`` with the reference that continues
    them. ``span`` is the ((chapter, verse), (chapter, verse)) range shown.
    """
    (first, last) = span
    tyndale = [note for note in notes if note.get("resource_type") == "study_notes"]
    lines = [f"## Study Notes: {label}", ""]
    shown, size, omitted = [], 0, None
    for note in tyndale:
        note_size = len(note.get("title") or "") + min(len(note.get("content_plain") or ""), 2000) + 8
        if shown and size + note_size > budget:
            omitted = note
            break
        shown.append(note)
        size += note_size
    if shown:
        lines.append(format_study_notes(shown).rstrip())
        lines.append("")
    if omitted:
        chapter, verse = max(_aquifer_chapter_verse(omitted["start_ref"]), first)
        end = f"{last[1]}" if chapter == last[0] else f"{last[0]}:{last[1]}"
        lines.extend([
            f"*Tyndale notes continue: call again with reference='{book_name} {chapter}:{verse}-{end}'.*",
            "",
        ])

    translator: dict[str, set[tuple[int, int]]] = {}
    for note in notes:
        source = _TRANSLATOR_NOTE_LABELS.get(note.get("resource_type"))
        if not source or not note.get("start_ref"):
            continue
        start = _aquifer_chapter_verse(note["start_ref"])
        end = _aquifer_chapter_verse(note.get("end_ref") or note["start_ref"])
        verses = (
            {(start[0], verse) for verse in range(start[1], end[1] + 1)}
            if start[0] == end[0] else {start, end}
        )
        translator.setdefault(source, set()).update(v for v in verses if first <= v <= last)
    translator = {source: verses for source, verses in translator.items() if verses}
    if translator:
        listed = "; ".join(f"{source} on {_verse_list(verses)}" for source, verses in translator.items())
        example = min(min(verses) for verses in translator.values())
        lines.extend([
            "### Translator Notes (by verse)",
            f"*{listed}. Not shown for a passage: call get_study_notes with one verse "
            f"(e.g. reference='{book_name} {example[0]}:{example[1]}') for its notes.*",
        ])
    return "\n".join(lines).rstrip()


def _format_content_items(items: list[dict], limit: int, truncation_note: str, empty_msg: str) -> str:
    """Format a list of content items (articles, terms) with title + truncated body."""
    if not items:
        return empty_msg
    items = clean_aquifer_items(items)

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


# get_bible_dictionary shows a long article a page at a time (context economy),
# naming at most this many of the sections still to come.
DICTIONARY_PAGE = 4000
DICTIONARY_POINTER_SECTIONS = 8


def _page_end(text: str, start: int, limit: int, stop: int) -> int:
    """Where a page of ``text`` from ``start`` ends: ``stop`` if it fits, else a line or word break."""
    end = start + limit
    if end >= stop:
        return stop
    floor = start + limit * 3 // 4
    for separator in ("\n", " "):
        index = text.rfind(separator, floor, end)
        if index > start:
            end = index
            break
    return min(safe_cut(text, end), len(text))


def _article_sections(text: str, headings: list[tuple[int, str]]) -> list[tuple[int, str, int]]:
    """(level, heading, position) of each section heading (h2 and below) on its own line, in order."""
    sections = []
    position = 0
    for level, heading in headings:
        found = re.compile(rf"(?m)^{re.escape(heading)}$").search(text, position)
        if found:
            if level > 1:
                sections.append((level, heading, found.start()))
            position = found.end()
    return sections


def _find_section(sections: list[tuple[int, str, int]], name: str) -> int | None:
    """Index of the section headed ``name`` (case-insensitive; else the first containing it)."""
    wanted = name.strip().casefold()
    for matches in (lambda h: h.casefold() == wanted, lambda h: wanted in h.casefold()):
        for index, (_, heading, _) in enumerate(sections):
            if matches(heading):
                return index
    return None


def _dictionary_page(item: dict, section: str | None, offset: int) -> tuple[bool, list[str]]:
    """One article's page: (whether the section or offset was found, its lines).

    The page runs from ``offset`` (or the named section's heading) for up to
    ``DICTIONARY_PAGE`` characters; a section page stops at the next heading
    of the same or a higher level. Anything left is announced with the
    ``offset`` to continue from and the headings of the sections still to come.
    """
    title = aquifer_title(item) or "Untitled"
    text, headings = aquifer_rendering(item)
    sections = _article_sections(text, headings)
    lines = [f"## {title}", ""]
    start, stop, heading = offset, len(text), None
    if section:
        index = _find_section(sections, section)
        if index is None:
            names = "; ".join(name for _, name, _ in sections) or "none (read on with offset)"
            lines.extend([f'*[No section matching "{section}". Sections: {names}.]*', ""])
            return False, lines
        level, heading, start = sections[index]
        stop = next((pos for lvl, _, pos in sections[index + 1:] if lvl <= level), len(text))
    elif start >= len(text) and start:
        lines.extend([
            f"*[Offset {start:,} is past the end of this article ({len(text):,} characters).]*", "",
        ])
        return False, lines
    end = _page_end(text, start, DICTIONARY_PAGE, stop)
    # A page cut just after a heading leaves the heading for the next page.
    end = next(
        (pos for _, name, pos in sections
         if start < pos < end and not text[pos + len(name):end].strip()),
        end,
    )
    if start:
        lines.extend([f"*[From character {start:,} of {len(text):,}.]*", ""])
    if text[start:end].strip():
        lines.append(text[start:end].strip())
    if end < len(text):
        rest = [name for _, name, pos in sections if pos >= end]
        names = "; ".join(rest[:DICTIONARY_POINTER_SECTIONS])
        if len(rest) > DICTIONARY_POINTER_SECTIONS:
            names += f" (and {len(rest) - DICTIONARY_POINTER_SECTIONS} more)"
        lead = (
            f'End of section "{heading}"; {len(text) - end:,} more characters in the article'
            if heading and end == stop else f"Truncated — {len(text) - end:,} more characters"
        )
        lines.extend([
            "",
            f'*[{lead}. Call get_bible_dictionary again with topic="{title}" and offset={end}'
            + (f", or section= one of: {names}" if names else "") + ".]*",
        ])
    lines.append("")
    return True, lines


def format_dictionary_article(articles: list[dict], section: str | None = None, offset: int = 0) -> str:
    """Format Bible dictionary articles, a page each, from ``offset`` or the named ``section``.

    With a section or offset, articles that lack it (another article of the
    same title) are left out unless none has it.
    """
    if not articles:
        return "No dictionary article found for this topic.\n"
    pages = [_dictionary_page(item, section, max(0, offset)) for item in articles]
    if section or offset:
        found = [lines for hit, lines in pages if hit]
        chosen = found or [lines for _, lines in pages]
    else:
        chosen = [lines for _, lines in pages]
    return "\n".join(line for lines in chosen for line in lines)


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

# Above this many people a family-tree diagram is left out (the list has them all).
MERMAID_MAX_NODES = 40
# A connection path longer than this is listed without a diagram.
MERMAID_MAX_PATH = 12
DATE_NOTE = (
    "*Dates are approximate (c.), from the Theographic chronology (Ussher-based); "
    "undated events are placed in Scripture order.*"
)
_DEITIES = frozenset({"god_1324", "holy_spirit_7400"})


@lru_cache(maxsize=1)
def _graph_curated() -> dict:
    """The runtime parts of graph_curated.json: edge notes and eponyms."""
    with open(Path(__file__).parent / "parsers" / "graph_curated.json", encoding="utf-8") as f:
        theo = json.load(f)["theographic"]
    notes = {(n["from"], n["to"], n["type"]): n for n in theo["family_edge_notes"]}
    return {"edge_notes": notes, "eponyms": theo["eponyms"]}


def edge_note(parent_id: str, child_id: str, relationship: str, short: bool = False) -> str | None:
    """A curated caveat on a parent link, if any: the note ('legal father: Jesus was
    conceived by the Holy Spirit ...') or, with short, its label ('legal father')."""
    note = _graph_curated()["edge_notes"].get((parent_id, child_id, relationship))
    return (note["label"] if short else note["note"]) if note else None


def eponym_ids() -> frozenset[str]:
    """People whose name is also a nation or tribe's (Israel, Judah, Moab ...)."""
    return frozenset(_graph_curated()["eponyms"]["people"])


def format_year(year: int | None) -> str:
    """Format a person's birth or death year (negative is BC) as 'c. 1085 BC'."""
    if year is None:
        return "unknown"
    return f"c. {abs(year)} BC" if year < 0 else f"c. AD {year}"


def format_event_year(year: int | None) -> str:
    """Format an event year, which Theographic counts astronomically (0 = 1 BC)."""
    if year is None:
        return ""
    return f"c. {1 - year} BC" if year <= 0 else f"c. AD {year}"


def _book_label(code: str) -> str:
    """'1Sam' -> '1 Sam'."""
    return re.sub(r"^(\d)", r"\1 ", code)


def scripture_span(refs: list[str]) -> str:
    """Where an event is told: 'Gen 22:1–19', or 'Matt 21:1–11; also Mark, Luke, John'."""
    positions = sorted(p for p in map(verse_position, refs) if p)
    if not positions:
        return ""
    book = positions[0][0]
    own = [p for p in positions if p[0] == book]
    (_, c1, v1), (_, c2, v2) = own[0], own[-1]
    span = f"{_book_label(GRAPH_BOOKS[book])} {c1}:{v1}"
    if (c1, v1) != (c2, v2):
        span += f"–{v2}" if c1 == c2 else f"–{c2}:{v2}"
    others = sorted({p[0] for p in positions} - {book})
    if others:
        names = [_book_label(GRAPH_BOOKS[b]) for b in others[:3]]
        span += "; also " + ", ".join(names) + (" and others" if len(others) > 3 else "")
    return span


def person_label(person: dict | None, fallback: str = "") -> str:
    """'Mary (Mother of Jesus)' where Theographic gives a title, else the name."""
    if not person:
        return fallback
    return person.get("display_title") or person.get("name") or fallback


def format_person_choice(query: str, matches: list[dict]) -> str:
    """A note saying which of several people a name was taken to mean, or ''."""
    chosen = matches[0]
    label = person_label(chosen)
    renamed = ""
    if chosen.get("match_tier") == 3 and query.strip().casefold() not in label.casefold():
        renamed = f"*'{query}' is listed as {label}.*\n"
    worst = max(chosen.get("match_tier", 9), 2)
    rivals = [m for m in matches[1:] if m.get("match_tier", 9) <= worst]
    if not rivals:
        return renamed
    shown = ", ".join(f"{person_label(m)} ({m['id']})" for m in rivals[:4])
    more = f", +{len(rivals) - 4} more" if len(rivals) > 4 else ""
    return renamed + (
        f"*Showing {label} ({chosen['id']}), the most mentioned of {len(rivals) + 1} people "
        f"matching '{query}'; others (pass an id to choose): {shown}{more}.*\n"
    )


def _child_word(person: dict) -> str:
    gender = (person.get("gender") or "").lower()
    return {"male": "son", "female": "daughter"}.get(gender, "child")


def _join_names(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _lineage_lines(
    focal: dict, lineage: dict, direction: str, names: dict[str, str]
) -> list[str]:
    """One line per generation, each relative with the relatives it links to."""
    up = direction == "ancestors"
    links: dict[str, list[tuple[str, str]]] = {}
    for parent, child, relationship in lineage["edges"]:
        relative, other = (parent, child) if up else (child, parent)
        links.setdefault(relative, []).append((other, relationship))
    by_generation: dict[int, list[str]] = {}
    for person in lineage["people"]:
        words: dict[str, list[str]] = {}
        notes = []
        for other, relationship in links.get(person["id"], []):
            if other not in names:
                continue
            word = relationship[:-3] if up else _child_word(person)
            words.setdefault(word, []).append(names[other])
            parent, child = (person["id"], other) if up else (other, person["id"])
            note = edge_note(parent, child, relationship)
            if note:
                notes.append(note)
        parts = [f"{word} of {_join_names(of)}" for word, of in words.items()]
        if person.get("birth_year") is not None:
            parts.append(f"b. {format_year(person['birth_year'])}")
        parts += notes
        detail = f" ({'; '.join(parts)})" if parts else ""
        by_generation.setdefault(person["generation"], []).append(f"**{names[person['id']]}**{detail}")
    return [f"- Generation {gen}: " + "; ".join(entries) for gen, entries in sorted(by_generation.items())]


def format_genealogy(
    person: dict,
    ancestors: dict | None,
    descendants: dict | None,
    family: dict | None = None,
    generations: int = 5,
    note: str = "",
) -> str:
    """A person's ancestors and/or descendants, one line per generation.

    ``ancestors``/``descendants`` are graph_lineage results (or None when not
    asked for); each relative appears once, with the relatives it is a parent
    or child of, so pedigree collapse and namesakes stay unambiguous.
    """
    title = person_label(person)
    lines = [f"## Genealogy of {title}\n"]
    if note:
        lines.append(note)
    names = {person["id"]: person["name"]}
    for lineage in (ancestors, descendants):
        for relative in (lineage or {}).get("people", []):
            names[relative["id"]] = relative["name"]
    found = False
    for heading, direction, lineage in (("Ancestors", "ancestors", ancestors),
                                        ("Descendants", "descendants", descendants)):
        if not lineage or not lineage["people"]:
            continue
        found = True
        deepest = max(p["generation"] for p in lineage["people"])
        lines.append(f"### {heading} ({deepest} generation{'s' if deepest != 1 else ''})")
        lines.extend(_lineage_lines(person, lineage, direction, names))
        if lineage.get("truncated"):
            lines.append(f"- *(cut off at {len(lineage['people'])} people; ask for fewer generations)*")
        lines.append("")
    if not found:
        asked = " or ".join(h.lower() for h, lineage in (("Parents", ancestors), ("Children", descendants))
                            if lineage is not None)
        lines.append(f"No {asked} are recorded for {title} in the Theographic database.\n")
    if any(p.get("birth_year") is not None for lineage in (ancestors, descendants)
           for p in (lineage or {}).get("people", [])):
        lines.append("*Birth years are approximate (Theographic chronology).*\n")

    family_lines = []
    if family and family.get("partners"):
        family_lines.append("**Spouse(s)**: " + ", ".join(person_label(p) for p in family["partners"]))
    if family and family.get("siblings"):
        family_lines.append("**Siblings**: " + ", ".join(person_label(p) for p in family["siblings"]))
    if family_lines:
        lines.append("### Immediate Family")
        lines.extend(family_lines)
        lines.append("")
    lines.append(f"*For a dictionary article on {person['name']}, use get_bible_dictionary.*")
    return "\n".join(lines)


def _event_line(event: dict, places: list[dict] | None, verses: list[str] | None) -> str:
    year = format_event_year(event.get("start_year"))
    line = f"- **{event['title']}**" + (f" ({year})" if year else "")
    details = []
    if places:
        shown = ", ".join(p["name"] for p in places[:3])
        details.append(shown + (f" +{len(places) - 3} more" if len(places) > 3 else ""))
    span = scripture_span(verses or [])
    if span:
        details.append(span)
    return line + (" — " + "; ".join(details) if details else "")


def format_person_events(
    person: dict | str,
    events: list[dict],
    event_places: dict[str, list[dict]],
    event_verses: dict[str, list[str]] | None = None,
    note: str = "",
) -> str:
    """A person's events in chronological order, each once: date, places, passage."""
    title = person_label(person) if isinstance(person, dict) else person
    lines = [f"## Timeline of {title}\n"]
    if note:
        lines.append(note)
    if not events:
        lines.append("No events found in the Theographic database.\n")
        return "\n".join(lines)
    lines.append(DATE_NOTE + "\n")
    event_verses = event_verses or {}
    for event in events:
        lines.append(_event_line(event, event_places.get(event["id"]), event_verses.get(event["id"])))
    lines.append("")
    return "\n".join(lines)


def format_place_history(
    place: dict,
    events: list[dict],
    people: dict,
    event_verses: dict[str, list[str]] | None = None,
    note: str = "",
) -> str:
    """Format a place's biblical history."""
    lines = [f"## {place['name']}\n"]
    if note:
        lines.append(note)

    if place.get("feature_type"):
        lines.append(f"**Type**: {place['feature_type']}")
    if place.get("latitude") and place.get("longitude"):
        lines.append(f"**Coordinates**: {place['latitude']:.4f}, {place['longitude']:.4f}")
    lines.append("")

    if events:
        lines.append("### Events at this location")
        lines.append(DATE_NOTE)
        event_verses = event_verses or {}
        for event in events:
            lines.append(_event_line(event, None, event_verses.get(event["id"])))
        lines.append("")

    born = people.get("born_here", [])
    died = people.get("died_here", [])

    if born:
        lines.append("### Born here")
        for p in born:
            lines.append(f"- {person_label(p)}")
        lines.append("")

    if died:
        lines.append("### Died here")
        for p in died:
            lines.append(f"- {person_label(p)}")
        lines.append("")

    if not events and not born and not died:
        lines.append("No detailed history found in the Theographic database.\n")

    return "\n".join(lines)


def _graph_scope(reference: str) -> tuple[str, int, int] | None:
    """(Theographic book code, first chapter, last chapter) of a passage reference."""
    parsed = parse_passage_reference(reference or "")
    if not parsed or not parsed[1] or parsed[1] not in BOOK_DISPLAY_NAMES:
        return None
    return BOOK_DISPLAY_NAMES[parsed[1]].replace(" ", ""), parsed[2][0], parsed[3][0]


def is_nation_mention(entity_id: str, reference: str) -> bool:
    """Whether a tagged eponym (Israel, Judah, Moab ...) here means the people named after them."""
    eponyms = _graph_curated()["eponyms"]
    if entity_id not in eponyms["people"]:
        return False
    scope = _graph_scope(reference)
    if scope is None:
        return False
    book, first, last = scope
    person_scope = set(eponyms["person_scope"])
    return book not in person_scope and not any(
        f"{book}.{chapter}" in person_scope for chapter in range(first, last + 1)
    )


def _split_people(
    people: list[dict], reference: str, nations: set[str] | None = None
) -> tuple[list[dict], list[dict]]:
    """People mentioned in a passage, without repeats, and the eponyms that mean nations.

    ``nations`` (from the server, which also checks for the eponym's family
    in the passage) overrides the reference-only test of is_nation_mention.
    """
    seen = set()
    persons, nation_rows = [], []
    for p in people:
        entity_id = p.get("entity_id")
        if entity_id in seen:
            continue
        seen.add(entity_id)
        is_nation = entity_id in nations if nations is not None else is_nation_mention(entity_id, reference)
        (nation_rows if is_nation else persons).append(p)
    return persons, nation_rows


def _entity_names(entities: list[dict]) -> list[str]:
    """Names to list, with namesakes told apart by their id."""
    names = [e.get("entity_name") or e.get("entity_id", "unknown") for e in entities]
    repeated = {n for n in names if names.count(n) > 1}
    return [f"{n} ({e.get('entity_id')})" if n in repeated else n for n, e in zip(names, entities)]


def format_passage_entities(reference: str, entities: dict, nations: set[str] | None = None) -> str:
    """Format entities found in a passage."""
    lines = [f"## Entities in {reference}\n"]

    people, nations = _split_people(entities.get("people", []), reference, nations)
    places = entities.get("places", [])
    events = entities.get("events", [])

    if people:
        lines.append("### People")
        lines.extend(f"- **{name}**" for name in _entity_names(people))
        lines.append("")

    if nations:
        lines.append("### Nations and tribes")
        lines.append("*(tagged in the source as their ancestor)*")
        lines.extend(f"- **{_graph_curated()['eponyms']['people'][n['entity_id']]}**" for n in nations)
        lines.append("")

    if places:
        lines.append("### Places")
        lines.extend(f"- **{name}**" for name in _entity_names(places))
        lines.append("")

    if events:
        lines.append("### Events")
        lines.extend(f"- **{name}**" for name in _entity_names(events))
        lines.append("")

    if not people and not nations and not places and not events:
        lines.append("No entities found for this passage in the Theographic database.\n")

    return "\n".join(lines)


def _run_phrase(relationship: str, length: int) -> str:
    each = "each " if length > 1 else ""
    return {
        "down": f"{each}a parent of the next",
        "up": f"{each}a child of the next",
        "sibling_of": "siblings",
        "partner_of": "spouses",
    }[relationship]


def format_connection_path(person1: str, person2: str, path: list[dict], note: str = "") -> str:
    """A family connection, summarised and listed as runs of the same kind of link."""
    lines = [f"## Connection: {person1} → {person2}\n"]
    if note:
        lines.append(note)
    if not path:
        lines.append("No family connection between them is recorded in the Theographic database.\n")
        return "\n".join(lines)

    kinds = ["down" if s["relationship_type"] in ("father_of", "mother_of")
             else "up" if s["relationship_type"] == "child_of" else s["relationship_type"]
             for s in path]
    def generations(n: int) -> str:
        return f"{n} generation{'s' if n != 1 else ''}"

    if set(kinds) == {"down"}:
        summary = f"{person1} is an ancestor of {person2}, {generations(len(path))} back."
    elif set(kinds) == {"up"}:
        summary = f"{person1} is a descendant of {person2}, {generations(len(path))} down."
    elif set(kinds) <= {"up", "down"} and kinds == sorted(kinds, key=lambda k: k != "up"):
        top = path[kinds.index("down")]["from_name"]
        summary = (f"They share the ancestor {top}: {person1} is {generations(kinds.count('up'))} "
                   f"below, {person2} {kinds.count('down')}.")
    else:
        summary = f"Connected in {len(path)} steps, through marriage or siblings as well as descent."
    lines.append(summary + "\n")

    runs: list[tuple[str, list[dict]]] = []
    for kind, step in zip(kinds, path):
        if runs and runs[-1][0] == kind and kind in ("up", "down"):
            runs[-1][1].append(step)
        else:
            runs.append((kind, [step]))
    for kind, steps in runs:
        names = [steps[0]["from_name"]] + [s["to_name"] for s in steps]
        joiner = " → " if kind in ("up", "down") else " — "
        line = f"- {joiner.join(names)} ({_run_phrase(kind, len(steps))})"
        mothers = [s["from_name"] for s in steps[1:] if s["relationship_type"] == "mother_of"]
        if kind == "down" and mothers:
            line += f"; through the mother{'s' if len(mothers) > 1 else ''} {_join_names(mothers)}"
        notes = [edge_note(s["current_id"], s["next_id"], s["relationship_type"]) if kind == "down"
                 else edge_note(s["next_id"], s["current_id"], "father_of") if kind == "up"
                 else None for s in steps]
        notes = [f"{s['from_name']}/{s['to_name']}: {n}" for s, n in zip(steps, notes) if n]
        if notes:
            line += " — " + "; ".join(notes)
        lines.append(line)
    lines.append("")
    return "\n".join(lines)


def format_enriched_verse(
    reference: str,
    verse: dict | None,
    entities: dict,
    family_data: dict[str, dict],
    nations: set[str] | None = None,
) -> str:
    """Format a verse with its entity context and family relationships.

    Args:
        reference: The verse reference string
        verse: The verse dict (or None)
        entities: Dict with 'people', 'places', 'events' lists
        family_data: Map of person id -> family dict from graph_get_family
    """
    lines = [f"## {reference}{bsb_label([verse] if verse else [])}\n"]

    if verse:
        lines.append(verse_english(verse))
        lines.append("")
        if verse.get("text_original"):
            lines.append(f"**Original**: {display_original(verse['text_original'])}")
            lines.append("")

    people, nations = _split_people(entities.get("people", []), reference, nations)
    places = entities.get("places", [])
    events = entities.get("events", [])

    if people:
        lines.append("### People Mentioned")
        for p, name in zip(people, _entity_names(people)):
            lines.append(f"\n**{name}**")
            family = family_data.get(p.get("entity_id"))
            if family and p.get("entity_id") not in _DEITIES:
                parts = []
                if family["parents"]:
                    parent_names = ", ".join(
                        pr["name"] + (f" ({label})" if (label := edge_note(
                            pr["id"], p["entity_id"], pr.get("relationship_type", ""), short=True)) else "")
                        for pr in family["parents"]
                    )
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

    if nations:
        lines.append("### Nations and tribes")
        lines.append("*(tagged in the source as their ancestor)*")
        lines.extend(f"- **{_graph_curated()['eponyms']['people'][n['entity_id']]}**" for n in nations)
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

    if not people and not nations and not places and not events:
        lines.append("*No entity data available for this verse in the Theographic database.*\n")

    return "\n".join(lines)


# =========================================================================
# Mermaid diagram formatters
# =========================================================================

def _mermaid_id(name: str) -> str:
    """Create a safe Mermaid node ID from a name or graph id."""
    return "n_" + re.sub(r"\W", "_", name)


def _mermaid_label(text: str) -> str:
    return text.replace('"', "'")


def mermaid_genealogy(
    person: dict,
    lineages: list[dict | None],
    family: dict | None = None,
) -> str:
    """A Mermaid family tree of the given lineages, nodes keyed by person id.

    Every recorded parent link among the people drawn is an edge, so
    namesakes stay separate and pedigree collapse shows as two edges into one
    node. Returns '' when there is nothing to draw or more than
    MERMAID_MAX_NODES people (the text list has them all).
    """
    names = {person["id"]: person_label(person)}
    edges: dict[tuple, None] = {}
    for lineage in lineages:
        for relative in (lineage or {}).get("people", []):
            names[relative["id"]] = relative["name"]
        for edge in (lineage or {}).get("edges", []):
            edges[edge] = None
    partners = [p for p in (family or {}).get("partners", []) if p["id"] not in names]
    if not edges and not partners:
        return ""
    if len(names) + len(partners) > MERMAID_MAX_NODES:
        return ""
    focal = _mermaid_id(person["id"])
    lines = ["```mermaid", "graph TD", f'    {focal}["{_mermaid_label(names[person["id"]])}"]',
             f"    style {focal} fill:#4a90d9,color:#fff,stroke:#2a5a8a"]
    declared = {person["id"]}
    for parent, child, relationship in edges:
        ends = []
        for pid in (parent, child):
            node = _mermaid_id(pid)
            if pid not in declared:
                declared.add(pid)
                node += f'["{_mermaid_label(names.get(pid, pid))}"]'
            ends.append(node)
        lines.append(f"    {ends[0]} -->|{relationship[:-3]}| {ends[1]}")
    for partner in partners:
        node = _mermaid_id(partner["id"])
        lines.append(f'    {focal} -.-|spouse| {node}["{_mermaid_label(person_label(partner))}"]')
        lines.append(f"    style {node} fill:#d9a04a,color:#fff")
    lines.append("```")
    return "\n".join(lines)


def mermaid_connection_path(person1: str, person2: str, path: list[dict]) -> str:
    """A Mermaid flowchart of a short relationship path ('' if none or too long to help)."""
    if not path or len(path) > MERMAID_MAX_PATH:
        return ""

    lines = ["```mermaid", "graph LR"]
    start_id = _mermaid_id(path[0]["current_id"])
    end_id = _mermaid_id(path[-1]["next_id"])
    lines.append(f"    style {start_id} fill:#4a90d9,color:#fff,stroke:#2a5a8a")
    lines.append(f"    style {end_id} fill:#d94a4a,color:#fff,stroke:#8a2a2a")

    for step in path:
        fid = _mermaid_id(step["current_id"])
        tid = _mermaid_id(step["next_id"])
        rel = step["relationship_type"].replace("_", " ")
        lines.append(
            f'    {fid}["{_mermaid_label(step["from_name"])}"] -->|{rel}| '
            f'{tid}["{_mermaid_label(step["to_name"])}"]'
        )

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

    place_id = _mermaid_id(place["id"])
    lines.append(f'    {place_id}["{_mermaid_label(place["name"])}"]')
    lines.append(f"    style {place_id} fill:#2a8a4a,color:#fff,stroke:#1a5a2a")

    for evt in events[:12]:  # limit to avoid huge diagrams
        eid = _mermaid_id(f"e{evt['id']}")
        year = format_event_year(evt.get("start_year"))
        title = evt["title"] if len(evt["title"]) <= 40 else evt["title"][:39].rsplit(" ", 1)[0] + "…"
        label = title + (f" ({year})" if year else "")
        lines.append(f'    {place_id} --- {eid}["{_mermaid_label(label)}"]')

    for p in born[:8]:
        pid = _mermaid_id(p["id"]) + "_b"
        lines.append(f'    {pid}["{_mermaid_label(person_label(p))}"] -->|born| {place_id}')
        lines.append(f"    style {pid} fill:#4a90d9,color:#fff")

    for p in died[:8]:
        pid = _mermaid_id(p["id"]) + "_d"
        lines.append(f'    {place_id} -->|died| {pid}["{_mermaid_label(person_label(p))}"]')
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


# The one-line pointer printed instead of _TORAH_WEAVE_DIRECTIONAL_DOC.
_TORAH_WEAVE_POINTER = (
    "*Partner text: `lookup_verse` on each range. Kline's dataset does not label "
    "column themes. Full reading guide: explain=true.*"
)


def format_torah_weave(
    reference: str,
    matches: list[dict],
    unit_cells_by_unit: dict[int, list[dict]],
    explain: bool = False,
) -> str:
    """Format Torah Weave match(es) for a reference.

    matches: list of cells (joined with unit metadata) returned by
        get_torah_weave_cells_for_reference.
    unit_cells_by_unit: map of unit_id → all cells in that unit.
    explain: append the full guide to reading each pairing direction; otherwise
        a one-line pointer (each partner heading already says what it means).
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
    lines.append(_TORAH_WEAVE_DIRECTIONAL_DOC if explain else _TORAH_WEAVE_POINTER)
    lines.append("")
    return "\n".join(lines)
