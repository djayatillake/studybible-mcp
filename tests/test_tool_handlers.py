"""Tool handlers with no other coverage, run through server.call_tool.

Each tool runs against the small synthetic database in tool_handler_fixture.py
(happy path with fixture content, no-match path, and malformed input where
cheap) and against an empty schema (the missing-data message). List-returning
tools are also checked against their default result caps.

Tests marked xfail(strict=True) document bugs in the current handlers; each
reason names the bug. They assert the correct behaviour, so they fail today;
once a bug is fixed the strict XPASS fails the run until the mark is removed.
"""

from __future__ import annotations

import re
import sqlite3
from types import SimpleNamespace

import pytest

import study_bible_mcp.server as server
from study_bible_mcp.database import StudyBibleDB, create_schema

from .tool_handler_fixture import (
    GRAPH_FAMILY_EDGES,
    GRAPH_PEOPLE,
    XREF_JOHN_3_16_ORDER,
    build_fixture_db,
    similarity_for,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def fixture_file(tmp_path_factory):
    path = tmp_path_factory.mktemp("tool_handlers") / "fixture.db"
    vectors = build_fixture_db(path)
    return SimpleNamespace(path=path, vectors=vectors)


@pytest.fixture(scope="module")
def empty_file(tmp_path_factory):
    path = tmp_path_factory.mktemp("tool_handlers_empty") / "empty.db"
    conn = sqlite3.connect(path)
    create_schema(conn)
    conn.close()
    return path


async def _connect(path, monkeypatch):
    database = StudyBibleDB(path)
    await database.connect()
    # call_tool opens the default database when this is None, so it is
    # always set before a tool runs.
    monkeypatch.setattr(server, "db", database)
    return database


@pytest.fixture
async def db(fixture_file, monkeypatch):
    database = await _connect(fixture_file.path, monkeypatch)
    yield database
    await database.close()


@pytest.fixture
async def empty_db(empty_file, monkeypatch):
    database = await _connect(empty_file, monkeypatch)
    yield database
    await database.close()


@pytest.fixture
async def vector_db(fixture_file, db):
    """The fixture database, skipping the test when sqlite-vec cannot be loaded."""
    if not (fixture_file.vectors and db._vec_loaded):
        pytest.skip(
            "sqlite-vec unavailable, so the fixture has no vector tables "
            f"({db._vec_error or 'extension did not load when the fixture was built'})"
        )
    return db


async def call(tool: str, /, **arguments) -> str:
    """Run a tool through the server entry point; a handler exception fails the test."""
    response = await server.call_tool(tool, arguments)
    assert len(response) == 1
    output = response[0].text
    assert not output.startswith("Error:"), output
    return output


def _section(output: str, heading: str) -> str:
    """The text from ``heading`` up to the next heading of the same or higher level."""
    level = len(heading) - len(heading.lstrip("#"))
    start = output.index(heading)
    rest = output[start + len(heading):]
    following = re.search(rf"^#{{1,{level}}} ", rest, re.MULTILINE)
    return heading + (rest[: following.start()] if following else rest)


# ---------------------------------------------------------------------------
# word_study
# ---------------------------------------------------------------------------


async def test_word_study_by_strongs_returns_entry_and_five_example_passages(db):
    output = await call("word_study", strongs="G26")
    assert output.startswith("## G0026 - ἀγάπη")
    assert "**Transliteration**: agapē" in output
    assert "### Full LSJ Definition\nLove, esteem, affection" in output
    assert "### Semantic Range\nlove, affection" in output
    assert "- G0025 ἀγαπάω - to love" in output
    assert "Abbott-Smith test entry for agapē." in output
    # 21 verses carry G0026; the entry shows only the first five.
    assert re.findall(r"^\*\*(1Jn\.4\.\d+)\*\*", output, re.MULTILINE) == [
        f"1Jn.4.{v}" for v in range(1, 6)
    ]


async def test_word_study_by_word_uses_the_language_argument(db):
    greek = await call("word_study", word="love")
    assert greek.startswith("## G0025 - ἀγαπάω")  # highest-usage Greek match
    hebrew = await call("word_study", word="love", language="hebrew")
    assert hebrew.startswith("## H0157 - אָהַב")
    assert "### Full BDB Definition" in hebrew
    assert "## Example Passages" not in hebrew  # no verse carries H0157


@pytest.mark.parametrize("arguments", [{"strongs": "G9999"}, {"word": "zzzz"}])
async def test_word_study_without_a_match(db, arguments):
    assert await call("word_study", **arguments) == "No entry found for the given word/Strong's number."


async def test_word_study_requires_strongs_or_word(db):
    assert await call("word_study") == "Please provide either 'strongs' number or 'word' to study."


# ---------------------------------------------------------------------------
# search_lexicon
# ---------------------------------------------------------------------------


def _lexicon_hits(output: str) -> list[str]:
    return re.findall(r"^### ([GH]\d{4}) - ", output, re.MULTILINE)


async def test_search_lexicon_ranks_both_languages_by_usage(db):
    output = await call("search_lexicon", query="love")
    assert output.startswith("## Lexicon Search: 'love'\n\nFound 4 entries:")
    assert _lexicon_hits(output) == ["H0157", "G0025", "G0026", "G5368"]
    assert "### G0026 - ἀγάπη (agapē)\nlove, goodwill" in output


async def test_search_lexicon_language_filter(db):
    output = await call("search_lexicon", query="love", language="greek")
    assert _lexicon_hits(output) == ["G0025", "G0026", "G5368"]


async def test_search_lexicon_default_cap_is_four(db):
    output = await call("search_lexicon", query="lampstand")
    assert "Found 4 entries" in output
    # Twelve entries match; the eight with the lowest usage counts are cut.
    assert _lexicon_hits(output) == [f"G{9000 + n:04d}" for n in range(1, 5)]
    more = await call("search_lexicon", query="lampstand", limit=10)
    assert _lexicon_hits(more) == [f"G{9000 + n:04d}" for n in range(1, 11)]


async def test_search_lexicon_no_match_and_empty_query(db):
    assert await call("search_lexicon", query="zzzz") == "No entries found for 'zzzz'."
    assert await call("search_lexicon", query="") == "Please provide a search query."


# ---------------------------------------------------------------------------
# get_cross_references
# ---------------------------------------------------------------------------


def _xref_targets(output: str) -> list[str]:
    """Targets in printed order, converted back to 'Rom.5.8' form."""
    found = re.findall(r"^- (\S+) (\d+):(\d+)", output, re.MULTILINE)
    return [f"{book}.{chapter}.{verse}" for book, chapter, verse in found]


async def test_cross_references_default_cap_keeps_the_four_strongest(db):
    output = await call("get_cross_references", reference="John 3:16")
    assert "_4 reference(s) returned (cap limit=4;" in output
    assert sorted(_xref_targets(output)) == sorted(XREF_JOHN_3_16_ORDER[:4])
    assert "### Burnett" not in output
    assert _xref_targets(_section(output, "### TSK")) == ["Rom.5.8", "1Jn.4.10"]


async def test_cross_references_larger_limit_keeps_the_eight_strongest(db):
    output = await call("get_cross_references", reference="John 3:16", limit=8)
    assert "_8 reference(s) returned (cap limit=8;" in output
    targets = _xref_targets(output)
    assert sorted(targets) == sorted(XREF_JOHN_3_16_ORDER[:8])
    # Output is grouped by dataset; within each group the strength order holds.
    for heading in ("### Curated (CH)", "### Gage", "### Burnett", "### TSK"):
        group = _xref_targets(_section(output, heading))
        assert group == sorted(group, key=XREF_JOHN_3_16_ORDER.index)
    assert _xref_targets(_section(output, "### TSK")) == [
        "Rom.5.8", "1Jn.4.10", "Rom.8.32", "Heb.2.9", "Eph.2.4"
    ]


async def test_cross_references_annotate_dataset_signals(db):
    output = await call("get_cross_references", reference="John 3:16", limit=8)
    # The CH pair also has 40 TSK votes; it is shown once, as CH.
    assert "- 1Jn 4:9  *(canonical direction)*  *(also TSK: 40 votes)*" in output
    assert "- Rev 21:6  *(parallel)* — Gift of life (parallel)" in output
    assert "- Rom 4:18 — JSPL 5.2 step 3" in output
    assert "- Rom 5:8  *(votes: 600)*" in output


async def test_cross_references_suppress_tier_one_on_a_signal_rich_verse(db):
    output = await call("get_cross_references", reference="John 3:16", limit=20)
    targets = _xref_targets(output)
    assert targets.count("1Jn.4.9") == 1
    assert sorted(targets) == sorted(XREF_JOHN_3_16_ORDER[:9])
    assert "Tit 3:4" not in output and "Isa 9:6" not in output


async def test_cross_references_keep_tier_one_on_a_signal_poor_verse(db):
    output = await call("get_cross_references", reference="Ruth 1:1")
    assert _xref_targets(output) == ["Jdg.21.25", "Gen.12.10"]


async def test_cross_references_tsk_source_returns_the_long_tail(db):
    output = await call("get_cross_references", reference="John 3:16", source="tsk", limit=20)
    assert "### Curated (CH)" not in output and "### Gage" not in output
    assert _xref_targets(output) == [
        "Rom.5.8", "1Jn.4.10", "Rom.8.32", "1Jn.4.9", "Heb.2.9", "Eph.2.4", "Tit.3.4", "Isa.9.6"
    ]


async def test_cross_references_min_strength_floors_tsk_only(db):
    output = await call("get_cross_references", reference="John 3:16", min_strength=10, limit=20)
    targets = _xref_targets(output)
    assert "Tit.3.4" in targets  # 12 votes: kept, and tier-1 suppression is off
    assert "Isa.9.6" not in targets  # 3 votes: below the floor
    assert "Rev.22.17" in targets  # curated rows are exempt from the floor


async def test_cross_references_by_theme(db):
    output = await call("get_cross_references", theme="atonement")
    assert output.startswith("## Cross-References: atonement")
    assert "- **Lev 16:30**: Cleansing on the Day of Atonement" in output
    assert "- **Rom 3:25**: Christ set forth as a propitiation" in output


async def test_cross_references_without_a_match(db):
    assert (
        await call("get_cross_references", reference="Genesis 50:26")
        == "No cross-references found for Genesis 50:26."
    )
    assert (
        await call("get_cross_references", reference="Ruth 1:1", source="ch")
        == "No cross-references found for Ruth 1:1. (source filter: ch)"
    )
    assert (
        await call("get_cross_references", theme="eschatology")
        == "No cross-references found for theme 'eschatology'."
    )
    assert (
        await call("get_cross_references", reference="not a verse")
        == "No cross-references found for not a verse."
    )
    assert await call("get_cross_references") == "Please provide either 'reference' or 'theme'."


# ---------------------------------------------------------------------------
# lookup_name
# ---------------------------------------------------------------------------


async def test_lookup_name_returns_entry_relationships_and_acai(db):
    output = await call("lookup_name", name="David")
    assert output.startswith("## Biblical Names: David")
    assert "### David\n**Original**: דָּוִד\n**Type**: Person" in output
    assert "Youngest son of Jesse; king of Israel." in output
    assert "- Father: Jesse\n- Son: Solomon" in output
    assert "**Roles**: king, shepherd" in output
    assert "**Referenced in**: 1118 verses" in output
    assert "### City of David" in output  # substring match


async def test_lookup_name_type_filter(db):
    places = await call("lookup_name", name="David", type="place")
    assert "### City of David" in places
    assert "### David\n" not in places
    people = await call("lookup_name", name="David", type="person")
    assert "### David\n" in people
    assert "City of David" not in people


async def test_lookup_name_without_a_match(db):
    assert await call("lookup_name", name="Goliath") == "No entries found for 'Goliath'."
    assert await call("lookup_name", name="") == "Please provide a name to look up."


async def test_lookup_name_shows_key_references(db):
    output = await call("lookup_name", name="David", type="person")
    assert "**Key References**: 1Sa.16.13, 2Sa.5.3" in output


async def test_lookup_name_acai_annotations_belong_to_their_own_entry(db):
    output = await call("lookup_name", name="David")
    city = next(part for part in output.split("\n---\n") if "### City of David" in part)
    assert "**Roles**" not in city
    assert "**Referenced in**" not in city


async def test_lookup_name_acai_matches_each_entry_by_its_own_name_and_type(tmp_path, monkeypatch):
    # ACAI keys entities 'type:Name' and names them in English. The tribe of
    # Judah and a namesake have more references than the patriarch; a place
    # merely containing the name has no ACAI entity of its own.
    path = tmp_path / "acai.db"
    conn = sqlite3.connect(path)
    create_schema(conn)
    conn.executemany(
        "INSERT INTO names (name, type, description, refs, relationships) VALUES (?, ?, ?, '[]', '{}')",
        [("Judah", "person", "Fourth son of Jacob."), ("Bethlehem-judah", "place", "Town in Judah.")],
    )
    conn.executemany(
        "INSERT INTO acai_entities (id, entity_type, name, roles, reference_count) VALUES (?, ?, ?, ?, ?)",
        [("group:Judah", "group", "Judah", '["Tribe"]', 728),
         ("person:Judah.2", "person", "Judah", '["Musician"]', 300),
         ("person:Judah", "person", "Judah", '["Patriarch"]', 80)],
    )
    conn.commit()
    conn.close()
    database = await _connect(path, monkeypatch)
    try:
        output = await call("lookup_name", name="Judah")
    finally:
        await database.close()
    person, place = output.split("\n---\n")[:2]
    assert "### Judah\n" in person and "### Bethlehem-judah\n" in place
    assert "**Roles**: Patriarch\n**Referenced in**: 80 verses" in person
    assert "**ACAI Annotations**" not in place
    assert "Tribe" not in output and "Musician" not in output


async def test_lookup_name_acai_matches_by_english_name_within_the_type(tmp_path, monkeypatch):
    # No key 'place:Misgab' (ACAI numbers it Misgab.1), so the name matches.
    # Ziph has only a person of that name, which is not taken for the place.
    path = tmp_path / "acai.db"
    conn = sqlite3.connect(path)
    create_schema(conn)
    conn.executemany(
        "INSERT INTO names (name, type, description, refs, relationships) VALUES (?, ?, ?, '[]', '{}')",
        [("Misgab", "place", "A place in Moab."), ("Ziph", "place", "A town in Judah.")],
    )
    conn.executemany(
        "INSERT INTO acai_entities (id, entity_type, name, description, reference_count) "
        "VALUES (?, ?, ?, ?, ?)",
        [("place:Misgab.1", "place", "Misgab", "A fortified height in Moab.", 1),
         ("person:Ziph", "person", "Ziph", "A descendant of Caleb.", 2)],
    )
    conn.commit()
    conn.close()
    database = await _connect(path, monkeypatch)
    try:
        misgab = await call("lookup_name", name="Misgab")
        ziph = await call("lookup_name", name="Ziph")
    finally:
        await database.close()
    assert "**Description**: A fortified height in Moab." in misgab
    assert "**ACAI Annotations**" not in ziph


@pytest.fixture
async def names_db(tmp_path, monkeypatch):
    """Seven names containing 'ai', inserted so id order differs from match order."""
    path = tmp_path / "names.db"
    conn = sqlite3.connect(path)
    create_schema(conn)
    conn.executemany(
        "INSERT INTO names (name, type, description, refs, relationships) VALUES (?, ?, ?, '[]', '{}')",
        [("Sinai", "place", "Mountain."), ("Aijalon", "place", "Valley."),
         ("Abigail", "person", "Wife of David."), ("Ai", "place", "City near Bethel."),
         ("Aiah", "person", "Father of Rizpah."), ("Ai", "place", "City of Ammon."),
         ("Mordecai", "person", "Cousin of Esther.")],
    )
    conn.commit()
    conn.close()
    database = await _connect(path, monkeypatch)
    yield database
    await database.close()


def _name_hits(output: str) -> list[str]:
    return re.findall(r"^### (.+)$", output, re.MULTILINE)


async def test_lookup_name_default_cap_puts_exact_then_prefix_matches_first(names_db):
    output = await call("lookup_name", name="ai")
    assert _name_hits(output) == ["Ai", "Ai", "Aijalon", "Aiah"]
    assert output.index("City near Bethel.") < output.index("City of Ammon.")
    assert "*Showing 4 of 7 matching names; set type or raise limit (at most 20) to see more.*" in output


async def test_lookup_name_limit_and_type_arguments(names_db):
    output = await call("lookup_name", name="Ai", limit=20)
    assert _name_hits(output) == ["Ai", "Ai", "Aijalon", "Aiah", "Sinai", "Abigail", "Mordecai"]
    assert "*Showing" not in output
    people = await call("lookup_name", name="Ai", type="person")
    assert _name_hits(people) == ["Aiah", "Abigail", "Mordecai"]
    assert "*Showing" not in people
    one = await call("lookup_name", name="Ai", type="place", limit=1)
    assert _name_hits(one) == ["Ai"]
    assert "*Showing 1 of 4 matching names;" in one


@pytest.mark.parametrize("limit", [0, 21, "many"])
async def test_lookup_name_rejects_an_out_of_range_limit(names_db, limit):
    assert (
        await call("lookup_name", name="Ai", limit=limit)
        == "'limit' must be an integer from 1 to 20."
    )


# ---------------------------------------------------------------------------
# parse_morphology
# ---------------------------------------------------------------------------


async def test_parse_morphology_greek_verb_and_noun(db):
    verb = await call("parse_morphology", code="V-AAI-3S")
    assert verb.startswith("## Morphology: V-AAI-3S\n\n**Language**: Greek\n**Part of Speech**: Verb")
    for line in ("**Person**: 3rd", "**Number**: Singular", "**Tense**: Aorist",
                 "**Voice**: Active", "**Mood**: Indicative"):
        assert line in verb
    assert "**Full Parsing**: Verb, Aorist, Active, Indicative, 3rd person, Singular" in verb
    noun = await call("parse_morphology", code="N-GSF")
    assert "**Case**: Genitive" in noun and "**Gender**: Feminine" in noun
    assert "**Tense**" not in noun


async def test_parse_morphology_language_argument(db):
    hebrew = await call("parse_morphology", code="HVqp3ms", language="hebrew")
    assert "**Language**: Hebrew" in hebrew and "**Voice**: Qal" in hebrew
    # The Greek code is not a Hebrew code.
    assert (
        await call("parse_morphology", code="V-AAI-3S", language="hebrew")
        == "Unknown morphology code: V-AAI-3S"
    )


async def test_parse_morphology_unknown_and_empty_code(db):
    assert await call("parse_morphology", code="X-YYY") == "Unknown morphology code: X-YYY"
    assert await call("parse_morphology", code="") == "Please provide a morphology code to parse."


# ---------------------------------------------------------------------------
# search_by_strongs
# ---------------------------------------------------------------------------


def _verse_hits(output: str) -> list[str]:
    return re.findall(r"^\*\*([1-3]?[A-Za-z]{2,3}\.\d+\.\d+)\*\*", output, re.MULTILINE)


async def test_search_by_strongs_default_cap_is_four(db):
    output = await call("search_by_strongs", strongs="G26")
    assert output.startswith("## Verses with G26 (ἀγάπη - agapē)\n\n*love, goodwill*")
    # 21 verses carry G0026.
    assert _verse_hits(output) == [f"1Jn.4.{v}" for v in range(1, 5)]
    assert "**1Jn.4.1**: Beloved, love is from God (test text 1 John 4:1)." in output
    more = await call("search_by_strongs", strongs="G0026", limit=20)
    assert _verse_hits(more) == [f"1Jn.4.{v}" for v in range(1, 21)]


async def test_search_by_strongs_known_word_without_verses(db):
    output = await call("search_by_strongs", strongs="H157")
    assert "(אָהַב - ahav)" in output
    assert "No verses found with this Strong's number in the database." in output


async def test_search_by_strongs_unknown_and_empty(db):
    assert await call("search_by_strongs", strongs="G9999") == "Unknown Strong's number: G9999"
    assert (
        await call("search_by_strongs", strongs="")
        == "Please provide a Strong's number (e.g., 'G26' or 'H3068')."
    )


# ---------------------------------------------------------------------------
# find_similar_passages
# ---------------------------------------------------------------------------


async def test_similar_passages_report_missing_extension(db, monkeypatch):
    monkeypatch.setattr(db, "_vec_loaded", False)
    monkeypatch.setattr(db, "_vec_error", "sqlite-vec package not installed")
    output = await call("find_similar_passages", reference="John 3:16")
    assert output == "Vector search unavailable: sqlite-vec package not installed"


async def test_similar_passages_report_missing_embeddings(empty_db, monkeypatch):
    # Extension loaded (or reported loaded) but no vector tables.
    monkeypatch.setattr(empty_db, "_vec_loaded", True)
    output = await call("find_similar_passages", reference="John 3:16")
    assert output.startswith("Vector embeddings have not been generated yet.")


async def test_similar_passages_rank_by_similarity_with_default_cap(vector_db):
    output = await call("find_similar_passages", reference="John 3:16")
    assert output.startswith("## Passages Similar to John 3:16\n\n**Source**: For God so loved")
    assert "Hermeneutical Caution" in output
    ranked = re.findall(r"^### (\d+)\. (\S+) \(([\d.]+)% similar\)", output, re.MULTILINE)
    # Default limit 4 of 21 candidates, most similar first.
    assert [(int(rank), ref) for rank, ref, _ in ranked] == [
        (v, f"1Jn.4.{v}") for v in range(1, 5)
    ]
    assert [float(pct) for _, _, pct in ranked] == [
        round(similarity_for(v) * 100, 1) for v in range(1, 5)
    ]
    # The passage containing the source verse is excluded although identical.
    assert "Jhn.3.16 - Jhn.3.17" not in output
    assert "⚡ **Genre**: epistle (source is gospel)" in output
    # Passage text is cut at 500 characters.
    assert ("Long passage text. " * 40).strip() not in output
    assert "Long passage text. Long p..." in output


async def test_similar_passages_limit_argument(vector_db):
    output = await call("find_similar_passages", reference="John 3:16", limit=3)
    assert re.findall(r"^### \d+\. (\S+)", output, re.MULTILINE) == ["1Jn.4.1", "1Jn.4.2", "1Jn.4.3"]
    output = await call("find_similar_passages", reference="John 3:16", limit=10)
    assert re.findall(r"^### \d+\. (\S+)", output, re.MULTILINE) == [
        f"1Jn.4.{v}" for v in range(1, 11)
    ]


async def test_similar_passages_without_an_embedding_or_verse(vector_db):
    for reference in ("Genesis 22:1", "Obadiah 1:5"):
        output = await call("find_similar_passages", reference=reference)
        assert output.startswith(f"No similar passages found for {reference}.")


async def test_similar_passages_do_not_borrow_another_verse(vector_db):
    # John 3:1 is not in the fixture; John 3:16 (which has an embedding) must not stand in.
    output = await call("find_similar_passages", reference="John 3:1")
    assert output.startswith("No similar passages found for John 3:1.")


async def test_similar_passages_require_a_reference(db):
    assert (
        await call("find_similar_passages", reference="")
        == "Please provide a verse reference (e.g., 'John 3:16')."
    )


# ---------------------------------------------------------------------------
# Graph tools: explore_genealogy, people_in_passage, explore_person_events,
# explore_place, find_connection, graph_enriched_search
# ---------------------------------------------------------------------------


async def test_genealogy_ancestors_default_to_five_generations(db):
    output = await call("explore_genealogy", person="Hezron", direction="ancestors")
    assert output.startswith("## Genealogy of Hezron")
    assert "  - **Perez** (Father)" in output
    assert "        - **Isaac** (Father) (2066 BC)" in output
    for name in ("Judah", "Jacob", "Rebekah", "Abraham", "Sarah"):
        assert f"**{name}**" in output
    assert "Terah" not in output  # sixth generation
    assert "### Descendants" not in output
    assert "```mermaid\ngraph TD" in output
    deeper = await call("explore_genealogy", person="Hezron", direction="ancestors", generations=6)
    assert "**Terah** (Father)" in deeper


async def test_genealogy_descendants_family_and_description(db):
    output = await call("explore_genealogy", person="Abraham", direction="descendants", generations=2)
    descendants = _section(output, "### Descendants")
    assert "**Isaac**" in descendants and "**Jacob**" in descendants and "**Esau**" in descendants
    assert "Judah" not in output
    assert "### Ancestors" not in output
    assert "**Spouse(s)**: Sarah" in output
    assert "### About\nPatriarch called out of Ur (test description)." in output


async def test_genealogy_resolves_an_alias(db):
    output = await call("explore_genealogy", person="Israel")
    assert output.startswith("## Genealogy of Jacob")
    assert "**Siblings**: Esau" in output


async def test_genealogy_graceful_messages(db):
    assert (
        await call("explore_genealogy", person="Goliath")
        == "No person found matching 'Goliath' in the Theographic database."
    )
    lone = await call("explore_genealogy", person="Melchizedek")
    assert "No genealogical data found in the Theographic database." in lone
    assert await call("explore_genealogy", person="") == "Please provide a person's name."


async def test_genealogy_diagram_draws_only_real_parent_edges(db):
    output = await call("explore_genealogy", person="Hezron", direction="ancestors")
    names = {person_id: name for person_id, name, *_ in GRAPH_PEOPLE}
    real = {
        (names[parent], names[child])
        for parent, child, relation in GRAPH_FAMILY_EDGES
        if relation in ("father_of", "mother_of")
    }
    drawn = set(re.findall(r"^\s*(\w+)(?:\[\"[^\"]*\"\])? -->\|(?:father|mother)\| (\w+)", output, re.MULTILINE))
    assert drawn, "diagram has no parent edges"
    assert drawn <= real, sorted(drawn - real)


async def test_genealogy_diagram_draws_every_parent_edge_in_range(db):
    output = await call("explore_genealogy", person="Hezron", direction="ancestors")
    drawn = set(re.findall(r"^\s*(\w+)(?:\[\"[^\"]*\"\])? -->\|(?:father|mother)\| (\w+)", output, re.MULTILINE))
    # Five generations up: Terah (sixth) is out of range.
    assert drawn == {
        ("Perez", "Hezron"), ("Judah", "Perez"), ("Jacob", "Judah"), ("Isaac", "Jacob"),
        ("Rebekah", "Jacob"), ("Abraham", "Isaac"), ("Sarah", "Isaac"),
    }


async def test_people_in_passage_chapter_and_verse(db):
    chapter = await call("people_in_passage", reference="Genesis 22")
    assert chapter.startswith("## Entities in Genesis 22")
    people = _section(chapter, "### People")
    assert "- **Abraham**" in people and "- **Isaac**" in people
    assert "- **Moriah**" in _section(chapter, "### Places")
    assert "- **Binding of Isaac**" in _section(chapter, "### Events")
    verse = await call("people_in_passage", reference="Genesis 22:2")
    assert "- **Isaac**" in verse and "- **Moriah**" in verse
    assert "Abraham" not in verse


async def test_people_in_passage_maps_book_codes_to_theographic(db):
    # Theographic stores John as "John.8.58", not the database's "Jhn".
    assert "- **Abraham**" in await call("people_in_passage", reference="John 8:58")
    assert "- **Abraham**" in await call("people_in_passage", reference="John 8")


async def test_people_in_passage_graceful_messages(db):
    assert "No entities found for this passage in the Theographic database." in await call(
        "people_in_passage", reference="Genesis 50"
    )
    assert (
        await call("people_in_passage", reference="Genesis")
        == "Could not parse reference: Genesis. Use 'Romans 8' or 'Genesis 22:1' format."
    )
    assert (await call("people_in_passage", reference="")).startswith("Please provide a Bible reference")


@pytest.mark.parametrize(
    ("tool", "expected"),
    [("people_in_passage", "- **Sharon**"), ("get_study_notes", "The rose of Sharon")],
)
async def test_chapter_references_with_multi_word_book_names(db, tool, expected):
    assert expected in await call(tool, reference="Song of Solomon 2:1")
    assert expected in await call(tool, reference="Song of Solomon 2")


async def test_chapter_references_with_numbered_book_names(db):
    assert "God is love (test note)." in await call("get_study_notes", reference="1 John 4")
    whole_chapter = await call("get_study_notes", reference="1 John 4:7", chapter_only=True)
    assert "God is love (test note)." in whole_chapter


async def test_person_events_in_chronological_order_with_places(db):
    output = await call("explore_person_events", person="Abraham")
    assert output.startswith("## Timeline of Abraham")
    assert re.findall(r"^- \*\*(.+?)\*\*", output, re.MULTILINE) == [
        "Call of Abraham", "Binding of Isaac", "Death of Abraham"
    ]
    assert "- **Call of Abraham** (2091 BC)\n  Location: Haran" in output
    assert "- **Binding of Isaac** (2054 BC)\n  Location: Moriah" in output
    assert "```mermaid\ntimeline\n    title Abraham" in output


async def test_person_events_graceful_messages(db):
    terah = await call("explore_person_events", person="Terah")
    assert "No events found in the Theographic database." in terah
    assert "```mermaid" not in terah
    assert (
        await call("explore_person_events", person="Goliath")
        == "No person found matching 'Goliath' in the Theographic database."
    )
    assert await call("explore_person_events", person="") == "Please provide a person's name."


async def test_explore_place_events_people_and_coordinates(db):
    output = await call("explore_place", place="Hebron")
    assert output.startswith("## Hebron\n\n**Type**: city\n**Coordinates**: 31.5326, 35.0998")
    assert "### Events at this location\n- **Death of Abraham** (1991 BC)" in output
    assert "### Died here\n- Abraham\n- Sarah" in output
    assert "```mermaid\ngraph TD" in output
    assert "### Born here\n- Abraham" in await call("explore_place", place="Ur")


async def test_explore_place_graceful_messages(db):
    assert "No detailed history found in the Theographic database." in await call(
        "explore_place", place="Zoar"
    )
    assert (
        await call("explore_place", place="Atlantis")
        == "No place found matching 'Atlantis' in the Theographic database."
    )
    assert await call("explore_place", place="") == "Please provide a place name."


async def test_explore_place_prefers_the_exact_name(db):
    output = await call("explore_place", place="Ai")
    assert output.startswith("## Ai\n"), output.splitlines()[0]


async def test_explore_place_prefers_a_prefix_match_to_a_substring(db):
    # Haran, Moriah, Zoar, Sharon and Mount Sinai contain "a"; only Ai starts with it.
    output = await call("explore_place", place="a")
    assert output.startswith("## Ai\n"), output.splitlines()[0]


async def test_find_connection_paths_in_both_directions(db):
    output = await call("find_connection", person1="Esau", person2="Hezron")
    assert output.startswith("## Connection: Esau → Hezron")
    assert (
        "- Esau → *Sibling Of* → Jacob\n"
        "- Jacob → *Father Of* → Judah\n"
        "- Judah → *Father Of* → Perez\n"
        "- Perez → *Father Of* → Hezron"
    ) in output
    assert "```mermaid\ngraph LR" in output
    upward = await call("find_connection", person1="Hezron", person2="Abraham")
    assert "- Hezron → *Child Of* → Perez" in upward
    assert "- Isaac → *Child Of* → Abraham" in upward


async def test_find_connection_graceful_messages(db):
    unrelated = await call("find_connection", person1="Abraham", person2="Melchizedek")
    assert "No family connection found in the Theographic database." in unrelated
    assert "```mermaid" not in unrelated
    assert (
        await call("find_connection", person1="Abraham", person2="Goliath")
        == "No person found matching 'Goliath'."
    )
    assert (
        await call("find_connection", person1="Abraham")
        == "Please provide both person1 and person2 names."
    )


async def test_graph_enriched_search_combines_text_entities_and_family(db):
    output = await call("graph_enriched_search", reference="Genesis 22:1")
    assert output.startswith("## Genesis 22:1\n\nAfter these things God tested Abraham (test text).")
    assert "**Original**: וַיְהִי אַחַר" in output
    assert "**Abraham**\n  Parents: Terah | Spouse: Sarah | Children: Isaac" in output
    assert "### Events\n- **Binding of Isaac**" in output


async def test_graph_enriched_search_graceful_messages(db):
    no_entities = await call("graph_enriched_search", reference="1 John 4:8")
    assert "Beloved, love is from God (test text 1 John 4:8)." in no_entities
    assert "*No entity data available for this verse in the Theographic database.*" in no_entities
    missing = await call("graph_enriched_search", reference="Genesis 50:26")
    assert missing.startswith("## Genesis 50:26")
    assert "No entity data available" in missing
    assert (
        await call("graph_enriched_search", reference="")
        == "Please provide a verse reference (e.g., 'Genesis 22:1')."
    )


async def test_graph_enriched_search_does_not_borrow_another_verse(db):
    output = await call("graph_enriched_search", reference="John 3:1")
    assert "For God so loved the world" not in output


async def test_graph_enriched_search_finds_a_verse_stored_with_split_numbering(db):
    # The fixture row is 'Gen.32.1(32.2)': English 32:1, Hebrew 32:2.
    output = await call("graph_enriched_search", reference="Genesis 32:1")
    assert output.startswith("## Genesis 32:1\n\nJacob went on his way (test text).")
    assert "Jacob went on his way" not in await call("graph_enriched_search", reference="Genesis 32:2")


# ---------------------------------------------------------------------------
# Aquifer tools: get_study_notes, get_bible_dictionary, get_key_terms
# ---------------------------------------------------------------------------


async def test_study_notes_for_a_verse_include_covering_ranges(db):
    output = await call("get_study_notes", reference="John 3:16")
    assert output.startswith("## Study Notes: John 3:16")
    assert "### Tyndale Study Notes\n\n**John 3:16**\nGod's love for the world" in output
    assert "### Translation Notes (unfoldingWord)\n\n**John 3:14-18**" in output
    assert "Nicodemus" not in output
    in_range = await call("get_study_notes", reference="John 3:15")
    assert "Lifted up refers to the cross" in in_range
    assert "God's love" not in in_range


async def test_study_notes_for_a_chapter(db):
    output = await call("get_study_notes", reference="John 3")
    for text in ("Nicodemus came to Jesus by night", "God's love for the world", "Lifted up"):
        assert text in output


async def test_study_notes_graceful_messages(db):
    assert await call("get_study_notes", reference="John 3:20") == "No study notes found for John 3:20."
    assert (
        await call("get_study_notes", reference="not a reference")
        == "No study notes found for not a reference."
    )
    assert (await call("get_study_notes", reference="")).startswith("Please provide a Bible reference")


async def test_study_notes_chapter_only_returns_the_whole_chapter(db):
    output = await call("get_study_notes", reference="John 3:16", chapter_only=True)
    assert "Nicodemus came to Jesus by night" in output


async def test_bible_dictionary_prefers_an_exact_title(db):
    output = await call("get_bible_dictionary", topic="abraham")
    assert output.startswith("## Abraham\n\nAbraham, father of the faithful (test article).")
    # "Covenant" mentions Abraham in its text but loses to the exact title.
    assert "## Covenant" not in output
    fallback = await call("get_bible_dictionary", topic="binding agreement")
    assert fallback.startswith("## Covenant\n")


async def test_bible_dictionary_caps_matches_and_truncates_articles(db):
    output = await call("get_bible_dictionary", topic="jubilee")
    assert len(re.findall(r"^## Jubilee note \d+$", output, re.MULTILINE)) == 10  # of 12
    long_article = await call("get_bible_dictionary", topic="Tabernacle")
    assert "*[Article truncated — full text available in the Tyndale Bible Dictionary]*" in long_article
    assert len(long_article) < 4300


async def test_bible_dictionary_graceful_messages(db):
    assert (
        await call("get_bible_dictionary", topic="zzzz") == "No dictionary article found for 'zzzz'."
    )
    assert await call("get_bible_dictionary", topic="") == "Please provide a topic to look up."


async def test_key_terms_by_title_and_text(db):
    output = await call("get_key_terms", term="atonement")
    assert output.startswith("## Atonement\n\nAtonement is the reconciling of God and people")
    assert (await call("get_key_terms", term="undeserved")).startswith("## Grace\n")


async def test_key_terms_graceful_messages(db):
    # A dictionary title is not a key term.
    assert await call("get_key_terms", term="Covenant") == "No key term found for 'Covenant'."
    assert await call("get_key_terms", term="") == "Please provide a term to look up."


# ---------------------------------------------------------------------------
# get_ane_context
# ---------------------------------------------------------------------------


async def test_ane_context_separates_direct_and_broad_entries(db):
    output = await call("get_ane_context", reference="Genesis 15:6")
    assert output.startswith("## Ancient Near East Context for Genesis 15:6")
    direct = _section(output, "# Directly Relevant to This Passage")
    broad = _section(output, "# General ANE Reading Frame")
    assert "### Covenant-cutting ritual" in direct
    assert "Detail: self-maledictory oath (test detail)." in direct
    # A whole-book entry whose key references cite Genesis 15 is promoted.
    assert "### Smoking firepot theophany" in direct
    # A whole-book entry citing another Genesis chapter stays broad and brief.
    assert "### Three-tier cosmos" in broad
    assert "Detail: the raqia" not in output
    # A whole-book entry whose key references never cite Genesis is dropped.
    assert "Debt slavery" not in output


async def test_ane_context_detail_levels(db):
    full = await call("get_ane_context", reference="Genesis 15:6", detail_level="full")
    assert "Detail: the raqia as a solid dome (test detail)." in full
    brief = await call("get_ane_context", reference="Genesis 15:6", detail_level="brief")
    assert "Detail:" not in brief
    assert "### Covenant-cutting ritual" in brief


async def test_ane_context_lists_dimensions_without_arguments(db):
    output = await call("get_ane_context")
    assert output.startswith("## Ancient Near East Context — Available Dimensions")
    assert "- **Legal & Covenant** (`legal_covenant`) — 1 entries" in output
    assert "- `patriarchal` — Patriarchal Period" in output


async def test_ane_context_dimension_and_period_filters(db):
    by_dimension = await call("get_ane_context", dimension="legal_covenant")
    assert re.findall(r"^### (.+)$", by_dimension, re.MULTILINE) == ["Covenant-cutting ritual"]
    combined = await call("get_ane_context", dimension="cosmology_worldview", period="patriarchal")
    assert re.findall(r"^### (.+)$", combined, re.MULTILINE) == ["Three-tier cosmos"]


async def test_ane_context_caps_results_at_thirty(db):
    output = await call("get_ane_context", reference="Leviticus 16:1", detail_level="brief")
    assert len(re.findall(r"^### Levitical filler \d+$", output, re.MULTILINE)) == 30  # of 32


async def test_ane_context_without_a_match(db):
    assert (
        await call("get_ane_context", reference="Matthew 5:1")
        == "No ANE context entries found for reference=Matthew 5:1."
    )
    assert (
        await call("get_ane_context", reference="Genesis 15:6", dimension="warfare_military")
        == "No ANE context entries found for reference=Genesis 15:6, dimension=warfare_military."
    )


async def test_ane_context_abbreviation_with_a_period(db):
    output = await call("get_ane_context", reference="Gen. 15:6")
    assert output.startswith("## Ancient Near East Context") or output.startswith("No ANE context")


async def test_ane_context_reads_abbreviations_and_chapter_references(db):
    for reference in ("Gen. 15:6", "Genesis 15", "Gen.15.6"):
        output = await call("get_ane_context", reference=reference)
        assert "### Covenant-cutting ritual" in _section(output, "# Directly Relevant to This Passage")
    assert (
        await call("get_ane_context", reference="Gen. fifteen")
        == "No ANE context entries found for reference=Gen. fifteen."
    )
    # Verse tools normalize the period form too.
    output = await call("graph_enriched_search", reference="Gen. 22:1")
    assert "After these things God tested Abraham (test text)." in output
    assert "**Abraham**" in output


# ---------------------------------------------------------------------------
# get_torah_weave
# ---------------------------------------------------------------------------


async def test_torah_weave_partners_for_a_cell(db):
    output = await call("get_torah_weave", reference="Genesis 1:1")
    assert output.startswith("## Torah Weave for Genesis 1:1")
    assert '### Unit 1 · "Creation" (Genesis 1:1-2:3)' in output
    assert "**Format**: 3x2 · **Type**: F — Framework" in output
    assert "**Cell position**: `1A` — row 1, column A" in output
    assert "**Cell verse range**: Genesis 1:1-5" in output
    horizontal = _section(output, "#### ⇄ Horizontal weave partners (same row)")
    assert re.findall(r"Cell (\w+)\*\*", horizontal) == ["1B"]
    assert "- **Cell 1B** — Genesis 1:6-8" in horizontal
    vertical = _section(output, "#### ↕ Vertical weave partners (same column)")
    assert re.findall(r"Cell (\w+)\*\*", vertical) == ["2A", "3A"]
    assert "Sibling cells (same row + column)" not in output


async def test_torah_weave_subdivided_cell_has_siblings(db):
    output = await call("get_torah_weave", reference="Genesis 1:26")
    assert "**Cell position**: `3Ba` — row 3, column B (subdivision a)" in output
    assert "- **Cell 3Bb** (subdivision b) — Genesis 1:29-2:3" in output
    assert "*(none — this cell has no row partner)*" in output


async def test_torah_weave_graceful_messages(db):
    for reference in ("Matthew 5:1", "Exodus 3:1", "Genesis"):
        assert await call("get_torah_weave", reference=reference) == (
            f"No Torah Weave unit contains {reference}. "
            "Torah Weave data covers Genesis–Deuteronomy only."
        )
    assert (
        await call("get_torah_weave", reference="")
        == "Please provide a Bible reference in Genesis–Deuteronomy."
    )


# ---------------------------------------------------------------------------
# Every tool on an empty database
# ---------------------------------------------------------------------------

EMPTY_DATABASE_CASES = [
    ("word_study", {"strongs": "G26"}, "No entry found for the given word/Strong's number."),
    ("search_lexicon", {"query": "love"}, "No entries found for 'love'."),
    ("get_cross_references", {"reference": "John 3:16"}, "No cross-references found for John 3:16."),
    ("lookup_name", {"name": "David"}, "No entries found for 'David'."),
    ("parse_morphology", {"code": "V-AAI-3S"}, "Unknown morphology code: V-AAI-3S"),
    ("search_by_strongs", {"strongs": "G26"}, "Unknown Strong's number: G26"),
    ("find_similar_passages", {"reference": "John 3:16"}, None),  # depends on the extension
    ("explore_genealogy", {"person": "David"}, "Graph data not available."),
    ("people_in_passage", {"reference": "Genesis 22"}, "Graph data not available."),
    ("explore_person_events", {"person": "Moses"}, "Graph data not available."),
    ("explore_place", {"place": "Jerusalem"}, "Graph data not available."),
    ("find_connection", {"person1": "Abraham", "person2": "David"}, "Graph data not available."),
    ("graph_enriched_search", {"reference": "Genesis 22:1"}, "Graph data not available."),
    ("get_study_notes", {"reference": "John 3:16"}, "Aquifer data not available."),
    ("get_bible_dictionary", {"topic": "covenant"}, "Aquifer data not available."),
    ("get_key_terms", {"term": "atonement"}, "Aquifer data not available."),
    ("get_ane_context", {"reference": "Genesis 15:1"}, "ANE context data not available."),
    ("get_torah_weave", {"reference": "Genesis 1:1"}, "Torah Weave data not available."),
]


@pytest.mark.parametrize(
    ("tool", "arguments", "expected"),
    EMPTY_DATABASE_CASES,
    ids=[case[0] for case in EMPTY_DATABASE_CASES],
)
async def test_empty_database_gives_a_clear_message(empty_db, tool, arguments, expected):
    output = await call(tool, **arguments)
    if expected is None:
        assert output.startswith(
            ("Vector search unavailable:", "Vector embeddings have not been generated yet.")
        )
    else:
        assert output.startswith(expected)
