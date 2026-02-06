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
