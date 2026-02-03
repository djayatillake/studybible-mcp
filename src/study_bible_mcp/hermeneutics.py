"""
Hermeneutical framework for Bible interpretation.

Based on Fee & Stuart's "How to Read the Bible for All Its Worth"
methodology for genre-specific, context-aware interpretation.
"""

from typing import Literal

# Type alias for biblical genres
Genre = Literal[
    "epistle",
    "ot_narrative",
    "acts",
    "gospel",
    "parable",
    "law",
    "prophet",
    "psalm",
    "wisdom",
    "apocalyptic",
]

# Book to genre mapping
BOOK_GENRES: dict[str, Genre] = {
    # Old Testament Narrative
    "Gen": "ot_narrative",
    "Exo": "ot_narrative",
    "Num": "ot_narrative",
    "Jos": "ot_narrative",
    "Jdg": "ot_narrative",
    "Rut": "ot_narrative",
    "1Sa": "ot_narrative",
    "2Sa": "ot_narrative",
    "1Ki": "ot_narrative",
    "2Ki": "ot_narrative",
    "1Ch": "ot_narrative",
    "2Ch": "ot_narrative",
    "Ezr": "ot_narrative",
    "Neh": "ot_narrative",
    "Est": "ot_narrative",
    "Jon": "ot_narrative",

    # Law (Torah/Pentateuch sections)
    "Lev": "law",
    "Deu": "law",

    # Wisdom Literature
    "Job": "wisdom",
    "Pro": "wisdom",
    "Ecc": "wisdom",
    "Sng": "wisdom",

    # Psalms
    "Psa": "psalm",

    # Prophets
    "Isa": "prophet",
    "Jer": "prophet",
    "Lam": "prophet",
    "Ezk": "prophet",
    "Dan": "prophet",
    "Hos": "prophet",
    "Jol": "prophet",
    "Amo": "prophet",
    "Oba": "prophet",
    "Mic": "prophet",
    "Nam": "prophet",
    "Hab": "prophet",
    "Zep": "prophet",
    "Hag": "prophet",
    "Zec": "prophet",
    "Mal": "prophet",

    # Gospels
    "Mat": "gospel",
    "Mrk": "gospel",
    "Luk": "gospel",
    "Jhn": "gospel",

    # Acts
    "Act": "acts",

    # Epistles (Pauline)
    "Rom": "epistle",
    "1Co": "epistle",
    "2Co": "epistle",
    "Gal": "epistle",
    "Eph": "epistle",
    "Php": "epistle",
    "Col": "epistle",
    "1Th": "epistle",
    "2Th": "epistle",
    "1Ti": "epistle",
    "2Ti": "epistle",
    "Tit": "epistle",
    "Phm": "epistle",

    # Epistles (General)
    "Heb": "epistle",
    "Jas": "epistle",
    "1Pe": "epistle",
    "2Pe": "epistle",
    "1Jn": "epistle",
    "2Jn": "epistle",
    "3Jn": "epistle",
    "Jud": "epistle",

    # Apocalyptic
    "Rev": "apocalyptic",
}

# Genre-specific interpretation guidelines
GENRE_GUIDELINES: dict[Genre, dict] = {
    "epistle": {
        "name": "Epistles (Letters)",
        "key_principle": "Think contextually - what problem was being addressed?",
        "approach": [
            "Identify the occasion: What problem or situation prompted this letter?",
            "Understand the relationship between author and recipients",
            "Read the whole letter at once to grasp the argument flow",
            "Pay attention to logical connectors (therefore, because, so that)",
            "Distinguish between the central argument and supporting points",
        ],
        "common_errors": [
            "Taking verses out of their argumentative context",
            "Ignoring the historical situation being addressed",
            "Treating every statement as universally prescriptive",
            "Missing the logical flow by reading only isolated passages",
        ],
        "application_questions": [
            "Is this addressing a specific first-century issue or a timeless principle?",
            "Does the broader biblical witness inform this teaching?",
            "Is the instruction tied to creation order or cultural context?",
        ],
    },
    "ot_narrative": {
        "name": "Old Testament Narratives",
        "key_principle": "Three levels of narrative (meta, national, individual); descriptive not prescriptive",
        "approach": [
            "Remember: narratives describe what happened, not necessarily what should happen",
            "Look for the three levels: God's universal plan, Israel's story, individual accounts",
            "Characters are not always examples to follow - observe their flaws",
            "The narrator rarely makes direct theological statements",
            "God is the ultimate hero of every narrative",
        ],
        "common_errors": [
            "Treating every character's action as a model to follow",
            "Allegorizing details that are simply historical facts",
            "Missing the larger redemptive-historical purpose",
            "Moralizing: 'Be brave like David' without seeing God's work",
        ],
        "application_questions": [
            "What does this reveal about God's character and purposes?",
            "How does this fit into the larger story of redemption?",
            "Is this action approved, disapproved, or simply recorded?",
        ],
    },
    "acts": {
        "name": "Acts (Historical Narrative)",
        "key_principle": "Historical precedent vs normative teaching - not everything repeated is required",
        "approach": [
            "Acts is theological history - Luke is making a point",
            "Distinguish between what the church DID and what we MUST do",
            "Look for patterns repeated multiple times as potentially normative",
            "Unique events may not be meant as patterns for all time",
            "Read alongside the Epistles for doctrinal understanding",
        ],
        "common_errors": [
            "Requiring every practice in Acts for churches today",
            "Taking unique events (Pentecost) as repeatable patterns",
            "Missing the transitional nature of this period",
            "Ignoring Luke's theological agenda in selecting what to report",
        ],
        "application_questions": [
            "Is this event presented as a pattern or as a unique occurrence?",
            "Does the rest of the NT confirm this as normative?",
            "What was Luke's purpose in including this account?",
        ],
    },
    "gospel": {
        "name": "Gospels",
        "key_principle": "Two-level documents (Jesus' original context + evangelist's purpose)",
        "approach": [
            "Consider both Jesus' original meaning and the Gospel writer's purpose",
            "Each Gospel has a specific audience and theological emphasis",
            "Context in Jesus' ministry: Who is he speaking to?",
            "How does this teaching function in the Gospel's overall narrative?",
            "Compare parallel accounts to see each writer's emphasis",
        ],
        "common_errors": [
            "Harmonizing too quickly without hearing each Gospel's voice",
            "Ignoring Jesus' audience (Pharisees, disciples, crowds)",
            "Missing the already/not-yet tension of the Kingdom",
            "Applying everything directly without considering the cross",
        ],
        "application_questions": [
            "Who was Jesus addressing and what was their situation?",
            "How does the cross and resurrection affect this teaching?",
            "What does this tell us about Jesus and his Kingdom?",
        ],
    },
    "parable": {
        "name": "Parables",
        "key_principle": "Find the main point; don't allegorize every detail",
        "approach": [
            "Identify the one or two main points - parables are not allegories",
            "Consider the audience: Who is Jesus speaking to and why?",
            "Look for cultural background that illuminates meaning",
            "The unexpected twist often carries the main message",
            "Let the context determine the interpretation",
        ],
        "common_errors": [
            "Allegorizing every detail (the donkey represents X...)",
            "Missing the shock value for the original audience",
            "Ignoring the immediate context of why Jesus told this",
            "Creating theological systems from parabolic details",
        ],
        "application_questions": [
            "What is the one main point Jesus is making?",
            "What would have surprised or challenged the original hearers?",
            "How does this teach us about the Kingdom of God?",
        ],
    },
    "law": {
        "name": "Law (Torah)",
        "key_principle": "Covenant stipulations; distinguish civil/ritual/ethical categories",
        "approach": [
            "The Law is Israel's covenant document, not a universal law code",
            "Distinguish: Apodictic (absolute) vs. Case law (situational)",
            "Categories: Civil (Israel's government), Ritual (worship), Ethical (moral)",
            "The Law reveals God's character even when specific commands don't apply",
            "Christ fulfills the Law - consider its purpose in light of the gospel",
        ],
        "common_errors": [
            "Applying Israel's civil laws directly to modern nations",
            "Ignoring the ritual laws entirely instead of finding their purpose",
            "Cherry-picking laws without consistent hermeneutic",
            "Moralizing without seeing the redemptive purpose",
        ],
        "application_questions": [
            "What does this reveal about God's character and values?",
            "How is this fulfilled or transformed in Christ?",
            "What principle stands behind this specific regulation?",
        ],
    },
    "prophet": {
        "name": "Prophets",
        "key_principle": "Covenant enforcement; check if 'future' is now past",
        "approach": [
            "Prophets were covenant enforcement officers - calling Israel back",
            "Most 'predictions' were about events now in our past",
            "The prophetic lawsuit: accusation, judgment, hope",
            "Distinguish near fulfillment from ultimate/eschatological fulfillment",
            "Poetry and metaphor are the normal mode of prophetic speech",
        ],
        "common_errors": [
            "Reading all prophecy as about the end times",
            "Literalizing poetic and metaphorical language",
            "Ignoring the historical context of the original prophecy",
            "Creating detailed end-times timelines from prophetic poetry",
        ],
        "application_questions": [
            "What covenant violation was being addressed?",
            "Has this prophecy been fulfilled, or does it await fulfillment?",
            "What does this reveal about God's character and purposes?",
        ],
    },
    "psalm": {
        "name": "Psalms",
        "key_principle": "Poetry/prayer; understand the types (lament, thanksgiving, praise)",
        "approach": [
            "Psalms are inspired responses to God - poetry, not doctrine",
            "Identify the type: Lament, Thanksgiving, Praise, Royal, Wisdom, etc.",
            "Poetry uses metaphor, hyperbole, and parallelism",
            "The emotions are real and God-given - even the difficult ones",
            "Many psalms find their ultimate fulfillment in Christ",
        ],
        "common_errors": [
            "Treating poetic expressions as doctrinal statements",
            "Ignoring the emotional dimension of the psalms",
            "Literalizing metaphorical language",
            "Skipping the imprecatory psalms or sanitizing them",
        ],
        "application_questions": [
            "What type of psalm is this and what is its function?",
            "What honest emotion is being expressed to God?",
            "How does this psalm find fulfillment in Christ?",
        ],
    },
    "wisdom": {
        "name": "Wisdom Literature",
        "key_principle": "General truths, not guarantees; compare with full canon",
        "approach": [
            "Proverbs are general truths, not absolute promises",
            "Wisdom literature wrestles with life's complexity",
            "Job and Ecclesiastes challenge simplistic interpretations",
            "The fear of the Lord is the foundation of all wisdom",
            "Compare individual proverbs with the full biblical witness",
        ],
        "common_errors": [
            "Treating Proverbs as unconditional promises (e.g., child-training)",
            "Ignoring the dialogue format in Job (not all speeches are true)",
            "Missing the 'under the sun' perspective in Ecclesiastes",
            "Applying isolated proverbs without considering counter-proverbs",
        ],
        "application_questions": [
            "Is this a general principle or being stated as an absolute?",
            "How does the rest of Scripture nuance this teaching?",
            "What does this reveal about living skillfully before God?",
        ],
    },
    "apocalyptic": {
        "name": "Revelation/Apocalyptic",
        "key_principle": "Apocalyptic imagery; already/not yet eschatology",
        "approach": [
            "Apocalyptic is a literary genre with its own conventions",
            "Symbols are stock imagery (beasts, numbers) with recognized meanings",
            "The primary message is: God wins, evil is judged, Christ reigns",
            "Read in light of OT prophets and the already/not yet tension",
            "Multiple valid interpretive approaches exist (preterist, futurist, idealist)",
        ],
        "common_errors": [
            "Literalizing symbolic imagery (666 as a barcode, locusts as helicopters)",
            "Creating detailed chronological timelines",
            "Ignoring the first-century context and audience",
            "Missing the pastoral purpose: encouragement for suffering believers",
        ],
        "application_questions": [
            "What comfort or challenge did this offer the original readers?",
            "What does this reveal about God's sovereignty and Christ's victory?",
            "Am I interpreting symbols consistently with OT usage?",
        ],
    },
}

# Conditions that suggest checking Greek/Hebrew
GREEK_HEBREW_TRIGGERS = [
    "Multiple translations disagree significantly on a key term",
    "A word carries significant theological weight",
    "Understanding word morphology would clarify meaning",
    "Cross-references depend on shared vocabulary",
    "The user asks about original language meaning",
    "A hapax legomenon (word appearing only once) is involved",
    "The word has a technical theological meaning",
]


def get_genre(book_abbrev: str) -> Genre | None:
    """
    Get the genre for a biblical book.

    Args:
        book_abbrev: Three-letter book abbreviation (e.g., 'Gen', 'Rom')

    Returns:
        The Genre for the book, or None if not found
    """
    return BOOK_GENRES.get(book_abbrev)


def get_genre_from_reference(reference: str) -> Genre | None:
    """
    Extract genre from a Bible reference.

    Args:
        reference: A Bible reference like 'John 3:16' or 'Rom.3.21'

    Returns:
        The Genre for the book, or None if not determinable
    """
    import re

    # Handle format like "Jhn.3.16"
    match = re.match(r'^(\w{3})\.\d+\.\d+', reference)
    if match:
        return BOOK_GENRES.get(match.group(1))

    # Handle format like "John 3:16" or "1 Corinthians 13:4"
    book_map = {
        "genesis": "Gen", "gen": "Gen",
        "exodus": "Exo", "exod": "Exo", "ex": "Exo",
        "leviticus": "Lev", "lev": "Lev",
        "numbers": "Num", "num": "Num",
        "deuteronomy": "Deu", "deut": "Deu",
        "joshua": "Jos", "josh": "Jos",
        "judges": "Jdg", "judg": "Jdg",
        "ruth": "Rut",
        "1 samuel": "1Sa", "1sam": "1Sa",
        "2 samuel": "2Sa", "2sam": "2Sa",
        "1 kings": "1Ki", "1kgs": "1Ki",
        "2 kings": "2Ki", "2kgs": "2Ki",
        "1 chronicles": "1Ch", "1chr": "1Ch",
        "2 chronicles": "2Ch", "2chr": "2Ch",
        "ezra": "Ezr",
        "nehemiah": "Neh", "neh": "Neh",
        "esther": "Est", "esth": "Est",
        "job": "Job",
        "psalms": "Psa", "psalm": "Psa", "ps": "Psa",
        "proverbs": "Pro", "prov": "Pro",
        "ecclesiastes": "Ecc", "eccl": "Ecc",
        "song of solomon": "Sng", "song": "Sng",
        "isaiah": "Isa", "isa": "Isa",
        "jeremiah": "Jer", "jer": "Jer",
        "lamentations": "Lam", "lam": "Lam",
        "ezekiel": "Ezk", "ezek": "Ezk",
        "daniel": "Dan", "dan": "Dan",
        "hosea": "Hos", "hos": "Hos",
        "joel": "Jol",
        "amos": "Amo",
        "obadiah": "Oba", "obad": "Oba",
        "jonah": "Jon",
        "micah": "Mic", "mic": "Mic",
        "nahum": "Nam", "nah": "Nam",
        "habakkuk": "Hab", "hab": "Hab",
        "zephaniah": "Zep", "zeph": "Zep",
        "haggai": "Hag", "hag": "Hag",
        "zechariah": "Zec", "zech": "Zec",
        "malachi": "Mal", "mal": "Mal",
        "matthew": "Mat", "matt": "Mat", "mt": "Mat",
        "mark": "Mrk", "mk": "Mrk",
        "luke": "Luk", "lk": "Luk",
        "john": "Jhn", "jn": "Jhn",
        "acts": "Act",
        "romans": "Rom", "rom": "Rom",
        "1 corinthians": "1Co", "1cor": "1Co",
        "2 corinthians": "2Co", "2cor": "2Co",
        "galatians": "Gal", "gal": "Gal",
        "ephesians": "Eph", "eph": "Eph",
        "philippians": "Php", "phil": "Php",
        "colossians": "Col", "col": "Col",
        "1 thessalonians": "1Th", "1thess": "1Th",
        "2 thessalonians": "2Th", "2thess": "2Th",
        "1 timothy": "1Ti", "1tim": "1Ti",
        "2 timothy": "2Ti", "2tim": "2Ti",
        "titus": "Tit",
        "philemon": "Phm", "phlm": "Phm",
        "hebrews": "Heb", "heb": "Heb",
        "james": "Jas", "jas": "Jas",
        "1 peter": "1Pe", "1pet": "1Pe",
        "2 peter": "2Pe", "2pet": "2Pe",
        "1 john": "1Jn", "1jn": "1Jn",
        "2 john": "2Jn", "2jn": "2Jn",
        "3 john": "3Jn", "3jn": "3Jn",
        "jude": "Jud",
        "revelation": "Rev", "rev": "Rev",
    }

    match = re.match(r'^(\d?\s*[a-zA-Z]+)\s*\d+:\d+', reference.strip())
    if match:
        book_name = match.group(1).lower().strip()
        abbrev = book_map.get(book_name)
        if abbrev:
            return BOOK_GENRES.get(abbrev)

    return None


def get_interpretation_guidelines(genre: Genre) -> dict:
    """
    Get the interpretation guidelines for a specific genre.

    Args:
        genre: The biblical genre

    Returns:
        Dictionary with name, key_principle, approach, common_errors, and application_questions
    """
    return GENRE_GUIDELINES.get(genre, {})


def format_genre_guidance(genre: Genre) -> str:
    """
    Format genre guidance as a readable string for agent consumption.

    Args:
        genre: The biblical genre

    Returns:
        Formatted string with interpretation guidelines
    """
    guidelines = GENRE_GUIDELINES.get(genre)
    if not guidelines:
        return ""

    lines = [
        f"## Genre: {guidelines['name']}",
        "",
        f"**Key Principle**: {guidelines['key_principle']}",
        "",
        "### Interpretive Approach:",
    ]

    for item in guidelines["approach"]:
        lines.append(f"- {item}")

    lines.extend([
        "",
        "### Common Errors to Avoid:",
    ])

    for item in guidelines["common_errors"]:
        lines.append(f"- {item}")

    lines.extend([
        "",
        "### Questions for Application:",
    ])

    for item in guidelines["application_questions"]:
        lines.append(f"- {item}")

    return "\n".join(lines)


def should_check_original_language(context: str) -> list[str]:
    """
    Determine if checking Greek/Hebrew would be valuable.

    Args:
        context: The current study context or question

    Returns:
        List of reasons why original language study would be valuable
    """
    context_lower = context.lower()
    triggers = []

    # Check for explicit requests
    if any(word in context_lower for word in ["greek", "hebrew", "original", "strongs", "strong's"]):
        triggers.append("User is asking about original language meaning")

    # Check for word study indicators
    if any(phrase in context_lower for phrase in ["what does the word mean", "meaning of", "definition of"]):
        triggers.append("Word study would clarify meaning")

    # Check for theological terms
    theological_terms = [
        "love", "faith", "grace", "sin", "salvation", "justification", "righteousness",
        "sanctification", "atonement", "covenant", "holy", "spirit", "baptism", "lord",
        "kingdom", "gospel", "peace", "glory", "redemption", "propitiation", "reconciliation"
    ]
    for term in theological_terms:
        if term in context_lower:
            triggers.append(f"The term '{term}' has significant theological weight")
            break

    # Check for translation comparison
    if any(phrase in context_lower for phrase in ["translations differ", "some translations", "different version"]):
        triggers.append("Multiple translations disagree - original language would clarify")

    return triggers


def get_reasoning_pattern() -> str:
    """
    Get the hermeneutical reasoning pattern for agent use.

    Returns:
        The step-by-step reasoning pattern as a formatted string
    """
    return """
## Hermeneutical Reasoning Pattern

When studying a biblical passage, follow this sequence:

1. **IDENTIFY**: What biblical text(s) are relevant to this question?
   - Look up the specific passage(s)
   - Consider the immediate textual context

2. **GENRE**: What type of literature is this?
   - Apply genre-specific interpretation methods
   - Avoid forcing methods from one genre onto another

3. **CONTEXT**:
   - **Historical**: Who wrote to whom, when, and why?
   - **Literary**: What comes before and after? What's the book's purpose?
   - **Canonical**: How does this fit in the whole Bible's storyline?

4. **CONTENT**:
   - What does the text actually say?
   - Check multiple translations if unclear
   - Examine key words in Greek/Hebrew when significant

5. **CROSS-REFERENCES**: What related passages inform this?
   - Scripture interprets Scripture
   - Look for thematic and verbal connections

6. **APPLICATION**: How does this apply to us today?
   - Consider cultural differences between then and now
   - Find the timeless principle behind temporal commands
   - Apply through the lens of the gospel

7. **HUMILITY**: Note where interpretation is uncertain
   - Acknowledge when faithful Christians disagree
   - Distinguish between clear teaching and debatable matters
   - Hold convictions with appropriate confidence levels
"""
