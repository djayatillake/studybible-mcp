"""
Tool definitions for the Study Bible MCP server.

Each tool is defined as an MCP Tool object with name, description, and input schema.

IMPORTANT: These tools should be used PROACTIVELY for ANY question about:
- The Bible, Scripture, or biblical texts
- Christianity, theology, or doctrine
- Biblical characters, places, or events
- Greek or Hebrew words and their meanings
- Interpreting or understanding passages

Even if you know the answer from training data, USE THESE TOOLS to:
1. Verify and ground your response in the actual text
2. Add depth with original language insights
3. Find additional relevant passages
4. Provide proper scholarly support

THEMATIC LINKING STRATEGIES:
When answering questions, connect passages and concepts using these approaches:

1. **Person-based linking**: Use lookup_name to find family relationships (parents,
   siblings, spouse, children) that connect narratives across books. Example:
   Moses → parents Amram & Jochebed → brother Aaron → Levitical priesthood lineage

2. **Place-based linking**: Use lookup_name with type="place" to trace locations
   through salvation history. Example: Bethlehem → Ruth's story → David's birthplace
   → Jesus' birth → Micah's prophecy fulfilled

3. **Word-based linking**: Use search_by_strongs to find all passages using the same
   Greek/Hebrew word. This reveals thematic threads across different books and authors.
   Example: G26 (agapē) appears in John, Paul's epistles, and 1 John - showing unified
   theology of love across different authors.

4. **Cross-reference linking**: Use get_cross_references on ANY verse to find the
   passages historically read alongside it (400k+ links from Harrison/Romhild's
   curated dataset and the Treasury of Scripture Knowledge). Scripture interprets
   Scripture — never argue a doctrine from one verse without checking these.

DISPLAY GUIDANCE: When presenting results to users, ALWAYS include:
- The original Greek/Hebrew text when available (this is what makes responses scholarly)
- Key words with their Strong's numbers for reference
- The transliteration for readers unfamiliar with Greek/Hebrew script
- Word-by-word analysis for key theological terms

Example format for verses:
  "For God so loved the world..." (John 3:16)
  Greek: οὕτως γὰρ ἠγάπησεν ὁ θεὸς τὸν κόσμον...
  Key: ἠγάπησεν (ēgapēsen, G25) - "loved" (aorist active indicative)

The combination of your knowledge + these research tools + showing original languages
produces responses that are both accessible AND scholarly.
"""

import json

from mcp.types import Tool, ToolAnnotations


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

TOOLS = [
    Tool(
        name="word_study",
        annotations=ToolAnnotations(title="Word Study", readOnlyHint=True, destructiveHint=False, idempotentHint=True),
        description="""ALWAYS USE THIS when discussing any Greek or Hebrew word, theological term, or concept.

Even if you know the word from training, this tool provides verified lexical data.

IMPORTANT: When presenting word studies, ALWAYS SHOW:
- The word in original script: ἀγάπη or אֱלֹהִים
- Transliteration: agapē, elohim
- Strong's number: G26, H430
- Full definition and semantic range
- Key passages showing usage

Format example in your response:
  **ἀγάπη** (agapē, G26)
  Definition: "Love, goodwill, benevolence; the love of God for humanity"
  Usage: Occurs 116 times in the NT
  Key passages: John 3:16, 1 Corinthians 13, 1 John 4:8

This makes responses scholarly and shows the depth available through original languages.""",
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
        description="""ALWAYS USE THIS when any Bible verse is mentioned or relevant.

Even if you can quote a verse from memory, this tool provides:
- The actual verse text (not paraphrased from training)
- Original Greek/Hebrew text (ALWAYS DISPLAY THIS in your response)
- Word-by-word breakdown with Strong's numbers
- Genre-specific interpretation guidance

IMPORTANT: When you use this tool, SHOW the original language text in your response.
This is what makes the Study Bible valuable - users see the actual Greek/Hebrew.

Format example in your response:
  **Romans 13:1**: "Let every soul be subject to the governing authorities..."
  Greek: Πᾶσα ψυχὴ ἐξουσίαις ὑπερεχούσαις ὑποτασσέσθω...
  Key term: ἐξουσία (exousia, G1849) - "authority, power"

Supports: 'John 3:16', 'Gen 1:1', 'Romans 3:21-26', etc.""",
        inputSchema={
            "type": "object",
            "properties": {
                "reference": {
                    "type": "string",
                    "description": "Bible reference (e.g., 'John 3:16', 'Genesis 1:1', 'Romans 3:21-26')"
                },
                "include_original": {
                    "type": "boolean",
                    "description": "Include original Greek/Hebrew text. Default: true"
                },
                "include_morphology": {
                    "type": "boolean",
                    "description": "Include grammatical parsing for each word. Default: false"
                }
            },
            "required": ["reference"]
        }
    ),
    Tool(
        name="search_lexicon",
        annotations=ToolAnnotations(title="Search Lexicon", readOnlyHint=True, destructiveHint=False, idempotentHint=True),
        description="""USE THIS to find Greek/Hebrew words for English concepts.

When a user asks about a biblical concept (love, faith, salvation, sin, grace, etc.),
search for the original language words to provide accurate, grounded information.

This finds multiple words that translate a concept (e.g., "love" → agape, phileo, eros)
so you can explain the distinctions and nuances.

Also use when you want to identify the Greek/Hebrew behind an English term.""",
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
        description="""USE THIS whenever you are explaining, exegeting, or arguing from
a specific Bible verse — and for any theological or doctrinal question.

Two complementary modes:

**By verse reference** (most common). Pass `reference="John 3:16"` (or any
canonical verse) to get the passages historically read alongside it. The
database contains 400k+ cross-references drawn from two scholarly sources,
returned in priority order:

  1. **CH** — Harrison & Romhild's curated cross-reference dataset (~58k
     links), the basis of the well-known "Bible cross-references" visualization.
     These appear first because they are hand-vetted; the highest-relevance
     ones are flagged as canonical-direction ("Orig") and circle members.
  2. **TSK** — Treasury of Scripture Knowledge via openbible.info (~345k
     links), with crowd-sourced relevance votes. Provides much wider
     breadth, including the long-tail allusions and minor parallels CH
     omits.

Use this BEFORE drawing any theological conclusion from a single verse —
results frequently surface the texts the original verse is quoting, the
fulfilment passages, contested parallel readings, and the chain of NT
authors who picked the verse up.

**By theme**. Pass `theme="atonement"` (or `salvation_by_grace`, `deity_of_christ`,
`resurrection`, `holy_spirit`, `justification`) to get a hand-curated chain
of foundational passages for that doctrine. Use this when the user asks a
broad theological question without anchoring to a specific verse.

**Important caveat about coverage.** TSK is built on R.A. Torrey's 19th-century
index, which catalogues **topical/thematic** connections — not necessarily
direct quotations or verbal allusions. Consequence: a verse with few cross-refs
here is NOT necessarily a verse with few biblical echoes. Famously,
Revelation shows surprisingly few links to OT prophetic books even though
it is saturated with OT symbolism, because Torrey indexed by subject and
Revelation's subject is "apocalyptic". The CH dataset partly compensates
(it leans toward NT-quotes-OT linking), so when you suspect a quotation/
allusion is being missed, retry with `source="ch"` or use `find_similar_passages`
to catch verbal parallels the topical index would skip.

**Strength scoring is meaningful — respect it.** TSK includes a long tail of
weakly-voted pairs (200k+ refs with ≤4 votes) that are mostly noise. Default
behaviour is tuned for context-economy: `limit=12` returns only the strongest
refs (CH first, then highest-voted TSK). Increase `limit` only when the user
wants exhaustive study, and pair it with `min_strength` (e.g. `min_strength=10`)
to keep the long tail out of context. CH refs always pass `min_strength`
because every CH pair is hand-curated — they all carry signal even at
relevance=0.

You may pass `source="ch"` or `source="tsk"` to restrict to one dataset —
useful when CH alone gives too little (e.g. an obscure verse with no CH
coverage) or when you want the dense TSK long-tail.""",
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
                    "enum": ["ch", "tsk"],
                    "description": "Optional dataset filter when using `reference`. 'ch' = Harrison/Romhild curated; 'tsk' = Treasury of Scripture Knowledge. Default: both, with CH ranked above TSK."
                },
                "limit": {
                    "type": "integer",
                    "description": "Max references to return when using `reference`. Default 12 — tuned to surface only strong refs. Raise (e.g. 30, 50) for exhaustive study, but pair with `min_strength` to suppress noise."
                },
                "min_strength": {
                    "type": "integer",
                    "description": "Strength floor for TSK refs (vote count). Pairs below this are excluded; CH refs always pass since they are hand-curated. Sensible thresholds: 5 (drops the bottom ~75%% of TSK noise), 20 (top-tier only). Default: no floor."
                }
            }
        }
    ),
    Tool(
        name="lookup_name",
        annotations=ToolAnnotations(title="Lookup Name", readOnlyHint=True, destructiveHint=False, idempotentHint=True),
        description="""USE THIS when any biblical person, place, or thing is mentioned.

This is your PRIMARY TOOL for thematic linking across the Bible. The database contains
4,000+ biblical persons and 1,000+ places with rich relationship data.

RELATIONSHIP DATA ENABLES THEMATIC CONNECTIONS:
- **Parents**: Trace lineages backward (e.g., David → Jesse → Obed → Boaz → Salmon)
- **Children**: Trace lineages forward (e.g., Abraham → Isaac → Jacob → 12 tribes)
- **Siblings**: Connect related narratives (e.g., Moses ↔ Aaron ↔ Miriam)
- **Spouse**: Connect family narratives (e.g., Ruth → Boaz → David's lineage)

THEMATIC LINKING EXAMPLES:
1. Messianic lineage: lookup Abraham → David → Solomon → ... → Joseph/Mary
2. Priesthood lineage: lookup Aaron → Eleazar → Phinehas → ... → Zadok
3. Geographic connections: lookup Bethlehem for its role in Ruth, David, and Jesus narratives
4. Prophecy fulfillment: trace how places mentioned in OT prophecy appear in NT

When answering questions about biblical characters or places, ALWAYS check their
relationships to find connections that enrich your answer with biblical context.

This grounds character discussions in the actual biblical data
rather than just training recall.""",
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
        description="""USE THIS after word_study to show how a word is actually used.

After identifying a key Greek/Hebrew word (via word_study or search_lexicon),
use this to find actual verses where it appears. This shows:
- How biblical authors used the word in context
- Range of meanings through actual examples
- Key passages for that term

This transforms word study from definition into demonstration.""",
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

USE THIS to discover thematic connections across the Bible that may not be captured
by explicit cross-references or shared vocabulary. This tool uses vector embeddings
to find passages with similar meaning, not just similar words.

EXAMPLES OF DISCOVERIES:
- Daniel 7:13-14 (Son of Man vision) → Revelation 1:7, 14:14 (similar imagery)
- Exodus 12:1-13 (Passover) → John 1:29, 1 Corinthians 5:7 (Lamb imagery)
- Isaiah 53:4-6 (Suffering Servant) → 1 Peter 2:24-25 (echoes of Isaiah)
- Proverbs wisdom themes → James practical wisdom

⚠️ CRITICAL HERMENEUTICAL WARNING:
Semantic similarity does NOT equal theological connection or relevance.
Two passages may use similar language but have completely different meanings
based on their literary context, historical setting, and authorial intent.

BEFORE USING SIMILAR PASSAGES IN YOUR RESPONSE, YOU MUST:

1. **Check Genre Compatibility**: A prophetic vision and a historical narrative
   may share imagery but require different interpretive approaches. Use lookup_verse
   to understand each passage's genre.

2. **Verify Historical Context**: What did this passage mean to its original audience?
   Similar language across centuries may have different referents.

3. **Examine Literary Context**: Is the similar passage using the language literally,
   metaphorically, or as an allusion? A quote vs. independent usage matters greatly.

4. **Apply Fee & Stuart's Questions**:
   - What did this text mean to the original readers?
   - What is the author's stated purpose?
   - How does this fit the book's overall argument/narrative?

5. **Distinguish Types of Similarity**:
   - Direct quotation (explicit OT in NT)
   - Deliberate allusion (author intentionally echoing)
   - Shared tradition (common Jewish/Christian concepts)
   - Coincidental similarity (similar words, unrelated meaning)

Only present a similar passage as theologically relevant if you can establish
an actual interpretive connection, not mere semantic overlap.

Takes a verse reference (with pre-computed embedding) and returns
semantically similar passages ranked by similarity score.""",
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
        description="""ALWAYS USE THIS when a question involves family lineage, ancestry, descendants, or tribal identity.

This tool traverses multi-generational family trees using genealogical data for 1,100+ biblical persons.
Unlike lookup_name (which shows immediate family), this traces lineage across many generations.

WHEN TO USE (instead of lookup_name):
- "Who was David's father?" → lookup_name is enough for one generation
- "Trace the line from Abraham to David" → USE THIS — traverses multiple generations
- "What tribe was Paul from?" → USE THIS — traces tribal ancestry
- "Show me Jesus' genealogy" → USE THIS — traces the full Messianic lineage
- "How does Ruth connect to the line of David?" → USE THIS

Returns a family tree with generation numbers, relationship types, and a Mermaid diagram.
ALWAYS include the Mermaid diagram in your response so the user can visualize the family tree.""",
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
        description="""ALWAYS USE THIS when studying or explaining a Bible passage to identify WHO is present and WHERE it takes place.

Returns all people, places, and events mentioned in a passage according to the Theographic Bible Metadata.
This is essential context for passage study — you cannot properly explain a passage without knowing its cast.

USE THIS WHEN:
- Studying any narrative passage (e.g., "Who is in Genesis 22?" → Abraham, Isaac, angel of the LORD, Moriah)
- Explaining a chapter (e.g., "What's happening in Acts 15?" → shows Paul, Barnabas, James, Jerusalem, Antioch)
- A user asks "Tell me about [passage]" → use this alongside lookup_verse for complete context

DIFFERENCE FROM graph_enriched_search:
- people_in_passage: works on chapters AND verses, returns entity lists
- graph_enriched_search: verse-level only, but adds family relationships for each person found""",
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
        description="""ALWAYS USE THIS when a user asks about a biblical person's life, biography, or timeline.

Returns every recorded event in a person's life in chronological order, with locations and dates.
This is the ONLY tool that shows what happened in someone's life and in what order.

USE THIS WHEN:
- "Tell me about Moses" → shows his entire life: birth, burning bush, exodus, Sinai, death on Nebo
- "What did Paul do?" → shows conversion, missionary journeys, imprisonment, Rome
- "What happened to David?" → anointing, Goliath, fleeing Saul, kingship, Bathsheba, death
- Any biographical question about a biblical figure

COMBINE WITH lookup_name (for identity/relationships) and explore_genealogy (for lineage).
Returns a Mermaid timeline diagram — ALWAYS include this in your response.""",
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
        description="""ALWAYS USE THIS when a user asks about a biblical location or its significance.

Returns the complete biblical history of a place: events that occurred there, people born/died there,
and geographic data. Shows how a location threads through salvation history across multiple eras.

USE THIS WHEN:
- "Tell me about Jerusalem" → shows events from Salem/Melchizedek through David, Solomon, exile, Jesus
- "What happened at Bethlehem?" → Ruth & Boaz, David's birthplace, Jesus' birth, Micah's prophecy
- "Why is Mount Sinai important?" → shows all events: burning bush, law given, golden calf, Elijah
- "What is the significance of [any place]?" → always use this
- Any question about biblical geography or a specific location

DIFFERENCE FROM lookup_name with type="place":
- lookup_name: returns basic place info and immediate connections
- explore_place: returns FULL history — every event, every person, across all biblical periods

Returns a Mermaid network diagram — ALWAYS include this in your response.""",
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
        description="""ALWAYS USE THIS when a user asks how two biblical people are related or connected.

Traces the shortest family relationship path between any two people in the biblical genealogies.
Uses parent, child, sibling, and spouse relationships to find the connection.

USE THIS WHEN:
- "How are Ruth and David related?" → shows Ruth → Obed → Jesse → David
- "What's the connection between Abraham and Moses?" → traces through Levi
- "Are Paul and Barnabas related?" → checks for any family connection
- Any question comparing two biblical figures or asking about their relationship

DIFFERENCE FROM explore_genealogy:
- explore_genealogy: shows one person's family tree (ancestors/descendants)
- find_connection: finds the PATH between two specific people

Returns a Mermaid flowchart — ALWAYS include this in your response.""",
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
        description="""USE THIS for deep study of a specific verse — combines the verse text with all relational context.

Returns the verse text PLUS all people, places, and events mentioned in it, PLUS family
relationships for each person found. This is the most comprehensive single-query tool
for studying a specific verse.

USE THIS WHEN:
- Deep-diving into a single verse (e.g., "Explain Genesis 22:1 in detail")
- Preparing a sermon or Bible study on a specific text
- You need verse text + entity context in one call (saves calling lookup_verse + people_in_passage separately)

Example: graph_enriched_search("Matthew 1:1") returns:
- Verse text: "The book of the genealogy of Jesus Christ, the son of David, the son of Abraham"
- People found: Jesus, David, Abraham — with their family relationships
- Places and events associated with the verse

DIFFERENCE FROM people_in_passage:
- people_in_passage: works on chapters AND verses, returns entity lists only
- graph_enriched_search: verse-level only, but includes verse text AND family relationships""",
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

USE THIS when you need:
- Scholarly commentary on a specific verse
- Help explaining difficult passages
- Translation and cultural background notes
- Chapter-level overview of themes and context

This provides published, peer-reviewed scholarship rather than AI-generated commentary.""",
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

USE THIS when you need:
- Background information on a biblical topic
- Historical or cultural context for a passage
- Detailed article about a person, place, or concept
- Scholarly definition of a theological term

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

USE THIS when you need:
- A precise definition of a theological term (agape, atonement, justification, etc.)
- To understand how a concept is used across Scripture
- Translation-oriented explanation of a term
- Cross-references to related theological concepts""",
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
This tool retrieves structured ANE contextual data to illuminate what the text meant
to its original audience.

USE THIS when:
- Studying creation, flood, or cosmological texts (three-tier universe, cosmic waters)
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

Call with NO arguments to see available dimensions and periods.
Call with just a reference to get ALL relevant ANE context for a passage.
Filter by dimension and/or period for focused results.
Call with dimension='ane_methodology' to retrieve the derivation hierarchy, confidence calibration, and methodological guardrails for working with ANE parallels.""",
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

USE THIS when discussing:
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

Query by verse reference, theme key, and/or author.""",
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
                    "description": "Filter by author: 'heiser', 'bradley'. Omit to get all scholars' content."
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

The Torah is organised as 86 two-dimensional literary units (Genesis–Deuteronomy). Each unit is a grid of cells arranged in rows and columns, and cells are deliberately paired with one another across rows (horizontal partners) and down columns (vertical partners). Knowing the weave partners of a verse gives you additional passages that the Torah's author(s) intended to be read alongside it.

USE THIS when:
- Studying any passage in Genesis, Exodus, Leviticus, Numbers, or Deuteronomy
- You want to see which other verses are structurally paired with a passage
- You suspect two passages in the Torah are deliberately interwoven (doublets, creation/flood, law parallels, etc.)
- You're preparing a comparative reading and want the author-intended partners, not just thematic cross-references
- You want additional context for a Torah verse beyond lexical or thematic similarity

WHAT IT RETURNS:
- The literary unit the verse sits in (title, format, type, verse span)
- The cell the verse occupies (row/column label + verse range)
- Horizontal partner cells (same row, same subdivision, different column)
- Vertical partner cells (same column, same subdivision, different row)
- Sibling cells (same row and column, adjacent subdivisions)
- A short explanation of what each direction of pairing means under Kline's method
- A directive block instructing the caller how to turn these pointers into an interpretation

HOW TO USE THE OUTPUT:
This tool returns STRUCTURAL POINTERS, not pre-written interpretation. After calling it, call `lookup_verse` on each partner cell's verse range to read the actual text, then synthesise the interpretation yourself using the directional semantics the tool provides. Horizontal partners are symmetric parallels (same register, different thematic tracks); vertical partners trace a progression through divine-name registers along a single thematic track. Reading the paired verses and applying those semantics is how the weave yields meaning.

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
]


# =========================================================================
# Format functions — Theological scholarship
# =========================================================================

def format_theology_context(entries: list[dict], themes: list[dict] | None = None) -> str:
    """Format theological scholarship entries for display."""
    if not entries:
        return "No theological scholarship found for this query."

    lines = []
    for entry in entries:
        lines.append(f"### {entry.get('title') or entry.get('chapter_or_episode', 'Untitled')}")
        lines.append(f"**Source**: {entry.get('source_author', '')} — *{entry.get('source_work', '')}*")
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


def format_verse(verse: dict, include_original: bool = True, include_morphology: bool = False) -> str:
    """Format a verse for display."""
    lines = []
    
    lines.append(f"## {verse['reference']}")
    lines.append("")
    lines.append(verse.get('text_english', 'No English text available.'))
    lines.append("")
    
    if include_original and verse.get('text_original'):
        lines.append("### Original Text")
        lines.append(verse['text_original'])
        lines.append("")
    
    words = _parse_json_field(verse.get('word_data'))
    if words and include_original:
        lines.append("### Word Analysis")
        for w in words:
            if isinstance(w, dict):
                word_line = f"- **{w.get('word', '')}** ({w.get('strongs', '')}): {w.get('gloss', '')}"
                if include_morphology and w.get('morph'):
                    word_line += f" [{w['morph']}]"
                lines.append(word_line)
        lines.append("")
    
    return "\n".join(lines)


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

**What to do next**: call `lookup_verse` on each partner cell's verse range to read \
the actual text, then synthesise the interpretation yourself by applying the \
directional semantics above to what you read. The thematic content of each unit's \
columns is NOT pre-labelled in Kline's dataset — you infer it from the verses."""


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
