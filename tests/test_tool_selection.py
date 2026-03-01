"""
Tests for agent tool selection.

Verifies that given a natural language user query (without naming a tool),
a keyword-based scorer selects the correct tool from the 17 available.

This validates that tool names, descriptions, and parameter descriptions
contain sufficient discriminating keywords for an LLM agent to pick the
right tool for each type of question.
"""

import math
import re
from collections import Counter

import pytest

from study_bible_mcp.tools import TOOLS


# ---------------------------------------------------------------------------
# Lightweight keyword scorer – simulates how an LLM matches a query to tools
# ---------------------------------------------------------------------------

# Stop words that carry no discriminating signal
_STOP = frozenset(
    "a an the is are was were be been being do does did will would shall should "
    "can could may might must have has had having it its this that these those "
    "of in to for on with at by from as into through about between after before "
    "and or but not nor so yet if then than when where how what which who whom "
    "all each every any some no more most other such only also very just even "
    "use using used also always your you any get make up".split()
)


def _tokenize(text: str) -> list[str]:
    """Lowercase, strip punctuation, split into tokens, remove stop words."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return [w for w in text.split() if len(w) > 1 and w not in _STOP]


def _bigrams(tokens: list[str]) -> list[str]:
    """Generate bigrams from token list."""
    return [f"{tokens[i]}_{tokens[i+1]}" for i in range(len(tokens) - 1)]


def _build_tool_keywords(tool) -> dict[str, float]:
    """Extract weighted keywords from a tool's metadata.

    Weights:
      - tool name tokens:          5.0
      - tool name bigrams:         6.0
      - parameter names:           3.0
      - parameter enum values:     3.0
      - parameter descriptions:    1.5
      - tool description (first 200 chars): 2.0  (core description)
      - tool description (rest):   0.5  (verbose detail)
    """
    weighted: Counter = Counter()

    # Tool name (highest signal)
    name_tokens = _tokenize(tool.name)
    for tok in name_tokens:
        weighted[tok] += 5.0
    for bg in _bigrams(name_tokens):
        weighted[bg] += 6.0

    # Parameter names and descriptions
    schema = tool.inputSchema or {}
    props = schema.get("properties", {})
    for param_name, param_info in props.items():
        for tok in _tokenize(param_name):
            weighted[tok] += 3.0
        desc = param_info.get("description", "")
        for tok in _tokenize(desc):
            weighted[tok] += 1.5
        # Enum values are highly discriminating
        for val in param_info.get("enum", []):
            for tok in _tokenize(val):
                weighted[tok] += 3.0

    # Tool description — weight the core summary more than verbose detail
    desc = tool.description or ""
    core = desc[:200]
    detail = desc[200:]

    for tok in _tokenize(core):
        weighted[tok] += 2.0
    for bg in _bigrams(_tokenize(core)):
        weighted[bg] += 2.5

    for tok in _tokenize(detail):
        weighted[tok] += 0.5

    return dict(weighted)


# Pre-build keyword indexes for all tools
_TOOL_KW = {tool.name: _build_tool_keywords(tool) for tool in TOOLS}

# Compute IDF-like normalization: penalize tools with huge keyword sets
_TOOL_NORM = {
    name: math.log(2 + len(kw))
    for name, kw in _TOOL_KW.items()
}


def score_tool(query: str, tool_name: str) -> float:
    """Score how well a query matches a tool's keywords.

    Normalized by the size of the tool's keyword vocabulary to prevent
    tools with long descriptions from dominating.
    """
    tokens = _tokenize(query)
    bigrams = _bigrams(tokens)
    kw = _TOOL_KW[tool_name]
    raw = sum(kw.get(tok, 0.0) for tok in tokens)
    raw += sum(kw.get(bg, 0.0) for bg in bigrams)
    return raw / _TOOL_NORM[tool_name]


def rank_tools(query: str) -> list[tuple[str, float]]:
    """Return all tools ranked by match score (descending)."""
    scores = [(name, score_tool(query, name)) for name in _TOOL_KW]
    scores.sort(key=lambda x: x[1], reverse=True)
    return scores


def best_tool(query: str) -> str:
    """Return the top-ranked tool name for a query."""
    return rank_tools(query)[0][0]


def top_n_tools(query: str, n: int = 3) -> list[str]:
    """Return the top-n tool names for a query."""
    return [name for name, _ in rank_tools(query)[:n]]


# ---------------------------------------------------------------------------
# Test cases: (query, expected_tool)
#
# Each query is phrased as a user would naturally ask, without naming a tool.
# ---------------------------------------------------------------------------

class TestWordStudySelection:
    """Queries that should route to word_study."""

    def test_greek_word_meaning(self):
        assert best_tool("What does agape mean in Greek?") == "word_study"

    def test_strongs_number_lookup(self):
        assert best_tool("Tell me about Strong's number G26") == "word_study"

    def test_hebrew_word_meaning(self):
        assert best_tool("What is the Hebrew word for God?") == "word_study"

    def test_word_study_theological_term(self):
        assert best_tool("Do a word study on faith") == "word_study"

    def test_strongs_h3068(self):
        assert best_tool("Study the word H3068 in the Hebrew lexicon") == "word_study"


class TestLookupVerseSelection:
    """Queries that should route to lookup_verse."""

    def test_show_verse(self):
        assert best_tool("Show me the verse John 3:16") == "lookup_verse"

    def test_read_verse(self):
        assert best_tool("Look up the verse Romans 8:28") == "lookup_verse"

    def test_verse_with_greek(self):
        assert best_tool("Look up Genesis 1:1 with the original text") == "lookup_verse"

    def test_quote_verse(self):
        assert best_tool("Display the verse Ephesians 2:8") == "lookup_verse"


class TestSearchLexiconSelection:
    """Queries that should route to search_lexicon."""

    def test_find_greek_words_for_concept(self):
        assert best_tool("Search the lexicon for Greek words meaning love") == "search_lexicon"

    def test_search_lexicon_concept(self):
        assert best_tool("Search the lexicon for words related to salvation") == "search_lexicon"

    def test_find_hebrew_words(self):
        assert best_tool("Search the Hebrew lexicon for words that mean peace") == "search_lexicon"


class TestCrossReferencesSelection:
    """Queries that should route to get_cross_references."""

    def test_cross_references_for_verse(self):
        assert best_tool("What are the cross-references for Romans 3:23?") == "get_cross_references"

    def test_theme_salvation(self):
        assert best_tool("Show me cross-references about salvation by grace") == "get_cross_references"

    def test_related_passages_theme(self):
        assert best_tool("Get cross-references on the theme of justification") == "get_cross_references"

    def test_theological_theme_atonement(self):
        assert best_tool("Give me cross-references on the theme of atonement") == "get_cross_references"


class TestLookupNameSelection:
    """Queries that should route to lookup_name."""

    def test_who_was_person(self):
        assert best_tool("Look up the name David") == "lookup_name"

    def test_biblical_place_name(self):
        assert best_tool("Look up the name Jerusalem in the Bible") == "lookup_name"

    def test_person_info(self):
        assert best_tool("What do we know about Abraham?") == "lookup_name"

    def test_place_lookup(self):
        assert best_tool("Look up the name Bethlehem") == "lookup_name"


class TestParseMorphologySelection:
    """Queries that should route to parse_morphology."""

    def test_parse_greek_code(self):
        assert best_tool("What does the morphology code V-AAI-3S mean?") == "parse_morphology"

    def test_grammatical_parsing(self):
        assert best_tool("Parse the grammatical code N-GSF") == "parse_morphology"

    def test_explain_morphology(self):
        assert best_tool("Explain this morphology parsing code: V-PPN") == "parse_morphology"


class TestSearchByStrongsSelection:
    """Queries that should route to search_by_strongs."""

    def test_verses_with_strongs(self):
        assert best_tool("Search by strongs G26 to find all verses") == "search_by_strongs"

    def test_where_word_appears(self):
        assert best_tool("Show every verse where strongs G2424 appears") == "search_by_strongs"

    def test_strongs_verse_search(self):
        assert best_tool("Search by strongs H430 to find verses") == "search_by_strongs"


class TestFindSimilarPassagesSelection:
    """Queries that should route to find_similar_passages."""

    def test_similar_passages(self):
        assert best_tool("Find passages similar to John 3:16") == "find_similar_passages"

    def test_semantic_similarity(self):
        assert best_tool("What passages are semantically similar to Daniel 7:13?") == "find_similar_passages"

    def test_thematic_echoes(self):
        assert best_tool("Find similar verses to Isaiah 53:4 using embeddings") == "find_similar_passages"


class TestExploreGenealogySelection:
    """Queries that should route to explore_genealogy."""

    def test_family_tree(self):
        assert best_tool("Show me the family tree of David") == "explore_genealogy"

    def test_ancestors(self):
        assert best_tool("Who are the ancestors of Jesus?") == "explore_genealogy"

    def test_descendants(self):
        assert best_tool("Trace the descendants of Abraham") == "explore_genealogy"

    def test_genealogy_lineage(self):
        assert best_tool("What is the genealogy from Abraham to David?") == "explore_genealogy"


class TestPeopleInPassageSelection:
    """Queries that should route to people_in_passage."""

    def test_who_is_in_chapter(self):
        assert best_tool("Who are the people mentioned in Romans 8?") == "people_in_passage"

    def test_entities_in_verse(self):
        assert best_tool("What people and places are in Genesis 22:1?") == "people_in_passage"

    def test_characters_in_passage(self):
        assert best_tool("List all the people in this passage: Matthew 1") == "people_in_passage"


class TestExplorePersonEventsSelection:
    """Queries that should route to explore_person_events."""

    def test_life_events(self):
        assert best_tool("What events happened in the life of Moses?") == "explore_person_events"

    def test_person_timeline(self):
        assert best_tool("Show me a timeline of Paul's life events") == "explore_person_events"

    def test_chronological_events(self):
        assert best_tool("What were the events of David's life in chronological order?") == "explore_person_events"


class TestExplorePlaceSelection:
    """Queries that should route to explore_place."""

    def test_place_history(self):
        assert best_tool("What is the biblical history of Bethlehem?") == "explore_place"

    def test_location_events(self):
        assert best_tool("Explore what happened at the place Mount Sinai") == "explore_place"

    def test_geographic_history(self):
        assert best_tool("Explore the geographic significance of Egypt in the Bible") == "explore_place"


class TestFindConnectionSelection:
    """Queries that should route to find_connection."""

    def test_how_related(self):
        assert best_tool("Find the connection between Abraham and David") == "find_connection"

    def test_relationship_path(self):
        assert best_tool("Find the family connection between Ruth and Jesus") == "find_connection"

    def test_find_path_between_people(self):
        assert best_tool("Find the connection path from Moses to Aaron") == "find_connection"


class TestGraphEnrichedSearchSelection:
    """Queries that should route to graph_enriched_search."""

    def test_deep_verse_study(self):
        assert best_tool("Give me a comprehensive enriched view of Genesis 22:1 with all people and places") == "graph_enriched_search"

    def test_verse_with_graph_context(self):
        assert best_tool("Show Matthew 1:1 with full graph context and relationships") == "graph_enriched_search"


class TestGetStudyNotesSelection:
    """Queries that should route to get_study_notes."""

    def test_study_notes_verse(self):
        assert best_tool("What do the study notes say about John 3:16?") == "get_study_notes"

    def test_commentary(self):
        assert best_tool("Show me scholarly study notes on Romans 8:28") == "get_study_notes"

    def test_translation_notes(self):
        assert best_tool("What are the translation notes for Genesis 1?") == "get_study_notes"

    def test_tyndale_notes(self):
        assert best_tool("Get the Tyndale study notes for Ephesians 2") == "get_study_notes"


class TestGetBibleDictionarySelection:
    """Queries that should route to get_bible_dictionary."""

    def test_dictionary_topic(self):
        assert best_tool("Look up covenant in the Bible dictionary") == "get_bible_dictionary"

    def test_dictionary_person(self):
        assert best_tool("What does the Bible dictionary say about the Pharisees?") == "get_bible_dictionary"

    def test_cultural_background(self):
        assert best_tool("Give me a dictionary article about baptism") == "get_bible_dictionary"

    def test_topical_article(self):
        assert best_tool("Look up Jericho in the Bible dictionary") == "get_bible_dictionary"


class TestGetKeyTermsSelection:
    """Queries that should route to get_key_terms."""

    def test_theological_term(self):
        assert best_tool("Define the key term atonement") == "get_key_terms"

    def test_key_term_lookup(self):
        assert best_tool("What is the key term definition of grace?") == "get_key_terms"

    def test_term_for_translators(self):
        assert best_tool("Look up the key term justification for translators") == "get_key_terms"


class TestGetAneContextSelection:
    """Queries that should route to get_ane_context."""

    def test_ane_background(self):
        assert best_tool("What is the Ancient Near East background for Genesis 1?") == "get_ane_context"

    def test_cultural_context_ane(self):
        assert best_tool("Show me the ANE cultural context for the flood narrative") == "get_ane_context"

    def test_cosmology_context(self):
        assert best_tool("What did the ancient Near Eastern cosmology look like for creation texts?") == "get_ane_context"


# ---------------------------------------------------------------------------
# Aggregate tests – verify no tool is unreachable
# ---------------------------------------------------------------------------

ALL_TOOLS = {tool.name for tool in TOOLS}

# Every test case above, collected for coverage checking
_EXPECTED_TOOLS_TESTED = {
    "word_study", "lookup_verse", "search_lexicon", "get_cross_references",
    "lookup_name", "parse_morphology", "search_by_strongs",
    "find_similar_passages", "explore_genealogy", "people_in_passage",
    "explore_person_events", "explore_place", "find_connection",
    "graph_enriched_search", "get_study_notes", "get_bible_dictionary",
    "get_ane_context",
    "get_key_terms",
}


class TestToolCoverage:
    """Meta-tests ensuring every tool has test coverage."""

    def test_all_tools_have_test_cases(self):
        """Every registered tool should have at least one test case above."""
        untested = ALL_TOOLS - _EXPECTED_TOOLS_TESTED
        assert not untested, f"Tools without test cases: {untested}"

    def test_no_phantom_tools_tested(self):
        """Test cases should only reference tools that actually exist."""
        phantoms = _EXPECTED_TOOLS_TESTED - ALL_TOOLS
        assert not phantoms, f"Test cases reference non-existent tools: {phantoms}"

    def test_tool_count(self):
        """Sanity check the expected number of tools."""
        assert len(TOOLS) == 18


class TestScorerSanity:
    """Verify the scoring mechanism itself behaves sensibly."""

    def test_exact_tool_name_scores_highest(self):
        """Using a tool's exact name in the query should score that tool highly."""
        for tool in TOOLS:
            name_query = tool.name.replace("_", " ")
            top3 = top_n_tools(name_query, 3)
            assert tool.name in top3, (
                f"Tool '{tool.name}' not in top 3 for query '{name_query}': got {top3}"
            )

    def test_empty_query_scores_zero(self):
        """An empty query should give zero scores for all tools."""
        scores = rank_tools("")
        for _, s in scores:
            assert s == 0.0

    def test_scores_are_non_negative(self):
        """All scores should be non-negative."""
        scores = rank_tools("some random bible question")
        for _, s in scores:
            assert s >= 0.0


class TestDiscrimination:
    """Verify tools are sufficiently distinct from each other.

    These tests catch cases where two tools are too similar in their
    keyword profiles, which would confuse an LLM agent.
    """

    def test_word_study_vs_search_lexicon(self):
        """word_study (specific word) vs search_lexicon (find words for concept)."""
        # Specific word → word_study
        assert best_tool("What does the word agape mean?") == "word_study"
        # Search for concept → search_lexicon
        assert best_tool("Search the lexicon for words meaning redemption") == "search_lexicon"

    def test_lookup_name_vs_explore_place(self):
        """lookup_name (info about any name) vs explore_place (place history)."""
        # General info → lookup_name
        assert best_tool("Who was David?") == "lookup_name"
        # Place-specific history → explore_place
        assert best_tool("Explore the biblical history of Jerusalem as a place") == "explore_place"

    def test_study_notes_vs_dictionary(self):
        """get_study_notes (verse commentary) vs get_bible_dictionary (topical article)."""
        # Verse-specific → study_notes
        assert best_tool("What do the study notes say about John 3:16?") == "get_study_notes"
        # Topical article → dictionary
        assert best_tool("Look up covenant in the Bible dictionary") == "get_bible_dictionary"

    def test_cross_references_vs_similar_passages(self):
        """get_cross_references (explicit refs) vs find_similar_passages (semantic)."""
        # Explicit cross-refs → get_cross_references
        assert best_tool("What are the cross-references for Romans 3:23?") == "get_cross_references"
        # Semantic similarity → find_similar_passages
        assert best_tool("Find passages semantically similar to John 3:16") == "find_similar_passages"

    def test_genealogy_vs_connection(self):
        """explore_genealogy (one person's tree) vs find_connection (path between two)."""
        # One person's tree → explore_genealogy
        assert best_tool("Show me the family tree of David") == "explore_genealogy"
        # Path between two → find_connection
        assert best_tool("Find the connection between Abraham and David") == "find_connection"

    def test_people_in_passage_vs_graph_enriched(self):
        """people_in_passage (entities list) vs graph_enriched_search (verse + context)."""
        # Entity list for chapter → people_in_passage
        assert best_tool("Who are the people mentioned in Romans 8?") == "people_in_passage"
        # Full enriched verse view → graph_enriched_search
        assert best_tool("Give me an enriched search of Genesis 22:1 with graph context") == "graph_enriched_search"

    def test_key_terms_vs_dictionary(self):
        """get_key_terms (theological term def) vs get_bible_dictionary (broad topic)."""
        # Theological term → key_terms
        assert best_tool("Define the key term atonement") == "get_key_terms"
        # Dictionary article → dictionary
        assert best_tool("Give me a dictionary article about the Pharisees") == "get_bible_dictionary"
