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

4. **Cross-reference linking**: Use get_cross_references with themes to find the
   key passages that form biblical doctrines. Scripture interprets Scripture.

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

from mcp.types import Tool

TOOLS = [
    Tool(
        name="word_study",
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
        description="""USE THIS for any theological or doctrinal question.

When discussing themes like salvation, grace, atonement, resurrection, etc.,
this tool provides the key passages that form the biblical basis.

Available themes: salvation_by_grace, deity_of_christ, atonement, resurrection,
holy_spirit, justification.

Also use when discussing a specific passage to find related texts
(Scripture interprets Scripture).

This ensures your theological claims are grounded in multiple passages,
not just one proof-text.""",
        inputSchema={
            "type": "object",
            "properties": {
                "reference": {
                    "type": "string",
                    "description": "Bible reference to find cross-references for"
                },
                "theme": {
                    "type": "string",
                    "description": "Theological theme (e.g., 'salvation', 'justification', 'resurrection')"
                }
            }
        }
    ),
    Tool(
        name="lookup_name",
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
        description="""Trace family relationships (ancestors or descendants) for a biblical person.

Uses the Theographic Bible Metadata graph to traverse family trees using
genealogical data for 1,100+ biblical persons.

USE THIS when discussing:
- Family lineages (e.g., "Who was David's father?")
- Genealogies (e.g., "Trace the line from Abraham to Jesus")
- Tribal connections (e.g., "What tribe was Paul from?")

Returns a family tree with generation numbers and relationship types.""",
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
        description="""Find all people, places, and events mentioned in a Bible passage.

Given a chapter or verse reference, returns all entities mentioned according
to the Theographic Bible Metadata. This enriches passage study with
knowledge of who is present, where it takes place, and what events occur.

USE THIS when studying a passage to understand its cast of characters,
geographic setting, and narrative context.""",
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
        description="""Find all events a biblical person participated in, in chronological order.

Returns the timeline of a person's life as recorded in Scripture,
including events with their locations and approximate dates.

USE THIS when building a biographical picture of a biblical figure,
or when tracing how someone's life connects different parts of Scripture.""",
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
        description="""Explore the biblical history of a geographic location.

Returns events that occurred at a place, people born or who died there,
and geographic information. Traces how a location threads through
salvation history.

USE THIS when discussing biblical geography, tracing how a place
appears across different periods of biblical history, or understanding
the significance of a location.""",
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
        description="""Find the family relationship path between two biblical people.

Traces through parent, child, sibling, and partner relationships to find
how two people are connected in the biblical genealogies.

USE THIS when exploring how biblical figures relate to each other,
especially across different books or periods.""",
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
        description="""Combine passage lookup with graph context to get a rich view of a verse.

Given a verse reference, returns the verse text along with all people,
places, and events mentioned in it, plus family relationships for
mentioned people. This is the most comprehensive single-query tool
for studying a specific verse in its relational context.

USE THIS as a starting point for deep verse study - it combines
the text with the full web of relationships around it.""",
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
]


def format_lexicon_entry(entry: dict) -> str:
    """Format a lexicon entry for display."""
    lines = []
    
    # Header
    lines.append(f"## {entry['strongs']} - {entry['word']}")
    lines.append(f"**Transliteration**: {entry['transliteration']}")
    if entry.get('pronunciation'):
        lines.append(f"**Pronunciation**: {entry['pronunciation']}")
    lines.append(f"**Language**: {entry['language'].title()}")
    lines.append("")
    
    # Definition
    lines.append("### Definition")
    lines.append(entry.get('full_definition') or entry.get('short_definition', 'No definition available.'))
    lines.append("")
    
    # Etymology
    if entry.get('etymology'):
        lines.append("### Etymology")
        lines.append(entry['etymology'])
        lines.append("")
    
    # Semantic range
    if entry.get('semantic_domain'):
        try:
            domains = entry['semantic_domain']
            if isinstance(domains, str):
                import json
                domains = json.loads(domains)
            if domains:
                lines.append("### Semantic Range")
                lines.append(", ".join(domains))
                lines.append("")
        except:
            pass
    
    # Usage count
    if entry.get('usage_count'):
        lines.append(f"**Usage**: Occurs {entry['usage_count']} times in the Bible")
        lines.append("")
    
    # Related words
    if entry.get('related_words'):
        try:
            related = entry['related_words']
            if isinstance(related, str):
                import json
                related = json.loads(related)
            if related:
                lines.append("### Related Words")
                for r in related:
                    if isinstance(r, dict):
                        lines.append(f"- {r.get('strongs', '')} {r.get('word', '')} - {r.get('gloss', '')}")
                    else:
                        lines.append(f"- {r}")
                lines.append("")
        except:
            pass
    
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
    
    if verse.get('word_data'):
        try:
            import json
            words = verse['word_data']
            if isinstance(words, str):
                words = json.loads(words)
            
            if words and include_original:
                lines.append("### Word Analysis")
                for w in words:
                    if isinstance(w, dict):
                        word_line = f"- **{w.get('word', '')}** ({w.get('strongs', '')}): {w.get('gloss', '')}"
                        if include_morphology and w.get('morph'):
                            word_line += f" [{w['morph']}]"
                        lines.append(word_line)
                lines.append("")
        except:
            pass
    
    return "\n".join(lines)


def format_name_entry(entry: dict) -> str:
    """Format a name entry for display."""
    lines = []
    
    lines.append(f"### {entry['name']}")
    if entry.get('name_original'):
        lines.append(f"**Original**: {entry['name_original']}")
    lines.append(f"**Type**: {entry.get('type', 'Unknown').title()}")
    lines.append("")
    
    if entry.get('description'):
        lines.append(entry['description'])
        lines.append("")
    
    if entry.get('relationships'):
        try:
            import json
            rels = entry['relationships']
            if isinstance(rels, str):
                rels = json.loads(rels)
            if rels:
                lines.append("**Relationships**:")
                for key, value in rels.items():
                    if value:
                        lines.append(f"- {key.title()}: {value}")
                lines.append("")
        except:
            pass
    
    if entry.get('references'):
        try:
            import json
            refs = entry['references']
            if isinstance(refs, str):
                refs = json.loads(refs)
            if refs:
                lines.append("**Key References**: " + ", ".join(refs[:10]))
                if len(refs) > 10:
                    lines.append(f"(and {len(refs) - 10} more)")
                lines.append("")
        except:
            pass

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


def format_genealogy(person_name: str, ancestors: list[dict], descendants: list[dict]) -> str:
    """Format a genealogy tree for display."""
    lines = [f"## Genealogy of {person_name}\n"]

    if ancestors and len(ancestors) > 1:
        lines.append("### Ancestors")
        for a in ancestors:
            if a["generation"] == 0:
                continue
            indent = "  " * a["generation"]
            rel = a["relationship"].replace("_of", "").title()
            year_str = f" ({format_year(a.get('birth_year'))})" if a.get("birth_year") else ""
            lines.append(f"{indent}- **{a['name']}** ({rel}){year_str}")
        lines.append("")

    if descendants and len(descendants) > 1:
        lines.append("### Descendants")
        for d in descendants:
            if d["generation"] == 0:
                continue
            indent = "  " * d["generation"]
            rel = d["relationship"].replace("_of", "").title()
            year_str = f" ({format_year(d.get('birth_year'))})" if d.get("birth_year") else ""
            lines.append(f"{indent}- **{d['name']}** ({rel}){year_str}")
        lines.append("")

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
    born = people.get("born_here", [])
    died = people.get("died_here", [])

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
