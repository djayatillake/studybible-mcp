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

import json
import re
import sqlite3
from types import SimpleNamespace

import pytest

import study_bible_mcp.server as server
from study_bible_mcp.database import StudyBibleDB, create_schema
from study_bible_mcp.tools import format_name_entry

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


async def test_word_study_by_strongs_returns_entry_and_four_example_passages(db):
    output = await call("word_study", strongs="G26")
    assert output.startswith("## G0026 - ἀγάπη")
    assert "**Transliteration**: agapē" in output
    # An NT word shows Abbott-Smith; the classical LSJ entry is reduced to its senses.
    assert "Abbott-Smith test entry for agapē." in output
    assert "Full LSJ Definition" not in output
    assert "### LSJ Senses (Classical Greek)\nLove, esteem, affection" in output
    assert "### Semantic Range\nlove, affection" in output
    assert "- G0025 ἀγαπάω - to love" in output
    # 21 verses carry G0026; the entry shows only the first four.
    assert re.findall(r"^\*\*(1Jn\.4\.\d+)\*\*", output, re.MULTILINE) == [
        f"1Jn.4.{v}" for v in range(1, 5)
    ]


async def test_word_study_greek_without_abbott_smith_keeps_the_full_lsj(db):
    output = await call("word_study", strongs="G5368")
    assert "### Full LSJ Definition\nTo be a friend to, to be fond of." in output
    assert "LSJ Senses" not in output


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


async def _acai_db(tmp_path, monkeypatch, names, entities, *, legacy=False):
    """A database of names (name, type, first ref) and ACAI entities, connected as server.db."""
    path = tmp_path / "acai.db"
    conn = sqlite3.connect(path)
    create_schema(conn)
    if legacy:  # acai_entities as built before tipnr_keys
        conn.execute("ALTER TABLE acai_entities DROP COLUMN tipnr_keys")
    conn.executemany(
        "INSERT INTO names (name, type, description, refs, relationships) VALUES (?, ?, ?, ?, '{}')",
        [(name, kind, f"{name} at {ref}.", json.dumps([ref])) for name, kind, ref in names],
    )
    columns = ("id", "entity_type", "name", "roles", "reference_count") + (() if legacy else ("tipnr_keys",))
    conn.executemany(
        f"INSERT INTO acai_entities ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
        [row[:len(columns)] for row in entities],
    )
    conn.commit()
    conn.close()
    return await _connect(path, monkeypatch)


# Three of TIPNR's Judahs and a place containing the name. ACAI records the
# patriarch as both the person and the tribe; it has no entity for the Judah
# of Neh.11.9, while the Judah of Neh.12.8 is in ACAI but not in these names.
JUDAH_NAMES = [("Judah", "person", "Gen.29.35"), ("Judah", "person", "Ezr.10.23"),
               ("Judah", "person", "Neh.11.9"), ("Bethlehem-judah", "place", "Jdg.17.7")]
JUDAH_ACAI = [
    ("group:Judah", "group", "Tribe of Judah", '["Tribe"]', 728, '["Judah@Gen.29.35"]'),
    ("person:Judah", "person", "Judah", '["Patriarch"]', 80, '["Judah@Gen.29.35"]'),
    ("person:Judah.2", "person", "Judah", '["Priest"]', 1, '["Judah@Ezr.10.23"]'),
    ("person:Judah.3", "person", "Judah", '["Musician"]', 300, '["Judah@Neh.12.8"]'),
]


async def test_lookup_name_acai_matches_each_entry_by_its_tipnr_entry(tmp_path, monkeypatch):
    database = await _acai_db(tmp_path, monkeypatch, JUDAH_NAMES, JUDAH_ACAI)
    try:
        output = await call("lookup_name", name="Judah", limit=10)
    finally:
        await database.close()
    patriarch, levite, other, place = output.split("\n---\n")[:4]
    assert "**Roles**: Patriarch\n**Referenced in**: 80 verses" in patriarch
    assert "**Roles**: Priest\n**Referenced in**: 1 verses" in levite
    assert "Judah at Neh.11.9." in other and "**ACAI Annotations**" not in other
    assert "### Bethlehem-judah\n" in place and "**ACAI Annotations**" not in place
    assert "Tribe" not in output and "Musician" not in output


async def test_lookup_name_acai_places_get_their_own_entity(tmp_path, monkeypatch):
    names = [("Ai", "place", "Gen.12.8"), ("Ai", "place", "Jer.49.3")]
    entities = [("place:Ai", "place", "Ai", '["City of Canaan"]', 39, '["Ai@Gen.12.8"]'),
                ("place:Ai.2", "place", "Ai", '["City of Ammon"]', 1, '["Ai@Jer.49.3"]')]
    database = await _acai_db(tmp_path, monkeypatch, names, entities)
    try:
        output = await call("lookup_name", name="Ai", type="place")
    finally:
        await database.close()
    canaan, ammon = output.split("\n---\n")[:2]
    assert "Ai at Gen.12.8." in canaan and "**Roles**: City of Canaan" in canaan
    assert "Ai at Jer.49.3." in ammon and "**Roles**: City of Ammon" in ammon


def test_name_entry_lists_only_other_variant_names():
    output = format_name_entry({"name": "Ai", "type": "place"},
                               acai_data={"referred_to_as": '["Ai", "Hai", "Aiath"]'})
    assert "**Also known as**: Hai, Aiath\n" in output


async def test_lookup_name_without_tipnr_keys_shows_no_acai(tmp_path, monkeypatch):
    # A database from before acai_entities.tipnr_keys: names, but no ACAI lines.
    database = await _acai_db(tmp_path, monkeypatch, JUDAH_NAMES, JUDAH_ACAI, legacy=True)
    try:
        output = await call("lookup_name", name="Judah")
    finally:
        await database.close()
    assert "Judah at Gen.29.35." in output
    assert "**ACAI Annotations**" not in output


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
    # A Greek code passed as Hebrew is not a Hebrew code, so it is read as Greek.
    greek = await call("parse_morphology", code="V-AAI-3S", language="hebrew")
    assert "**Language**: Greek" in greek and "**Tense**: Aorist" in greek
    assert (
        await call("parse_morphology", code="X-YYY", language="hebrew")
        == "Unknown morphology code: X-YYY"
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
    # 21 verses carry G0026, and the output says so.
    assert "*Showing 4 of 21 verses; raise limit (at most 50) to see more.*" in output
    assert _verse_hits(output) == [f"1Jn.4.{v}" for v in range(1, 5)]
    assert "**1Jn.4.1**: Beloved, love is from God (test text 1 John 4:1)." in output
    more = await call("search_by_strongs", strongs="G0026", limit=20)
    assert _verse_hits(more) == [f"1Jn.4.{v}" for v in range(1, 21)]
    assert "*Showing 20 of 21 verses;" in more
    every = await call("search_by_strongs", strongs="G0026", limit=21)
    assert len(_verse_hits(every)) == 21 and "*Showing" not in every


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
    assert await call("find_similar_passages", reference="Genesis 22:1") == (
        "Genesis 22:1 has no pre-computed embedding, so similar passages cannot be "
        "ranked from it. Try a neighbouring verse."
    )
    assert await call("find_similar_passages", reference="Obadiah 1:5") == (
        "Obadiah 1:5 is not in the verse table: check the book, chapter, and verse numbers."
    )
    assert await call("find_similar_passages", reference="not a verse") == (
        "Could not read 'not a verse' as a verse reference. "
        "Use 'Book chapter:verse', e.g. 'John 3:16' or 'Daniel 7:13'."
    )


async def test_similar_passages_do_not_borrow_another_verse(vector_db):
    # John 3:1 is not in the fixture; John 3:16 (which has an embedding) must not stand in.
    output = await call("find_similar_passages", reference="John 3:1")
    assert output.startswith("John 3:1 is not in the verse table")


async def test_similar_passages_say_a_range_uses_its_first_verse(vector_db):
    output = await call("find_similar_passages", reference="John 3:16-17")
    assert output.startswith("## Passages Similar to John 3:16\n\n")
    assert (
        "*Similarity is computed from one verse: John 3:16, the first verse of "
        "'John 3:16-17'. Call again with another verse to search from it.*"
    ) in output
    single = await call("find_similar_passages", reference="John 3:16")
    assert "Similarity is computed from one verse" not in single


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
    assert "- Generation 1: **Perez** (father of Hezron)" in output
    assert "- Generation 4: **Isaac** (father of Jacob; b. c. 2066 BC); **Rebekah** (mother of Jacob)" in output
    for name in ("Judah", "Jacob", "Rebekah", "Abraham", "Sarah"):
        assert f"**{name}**" in output
    assert "Terah" not in output  # sixth generation
    assert "### Descendants" not in output
    assert "```mermaid\ngraph TD" in output
    deeper = await call("explore_genealogy", person="Hezron", direction="ancestors", generations=6)
    assert "- Generation 6: **Terah** (father of Abraham)" in deeper


async def test_genealogy_descendants_family_and_dictionary_pointer(db):
    output = await call("explore_genealogy", person="Abraham", direction="descendants", generations=2)
    descendants = _section(output, "### Descendants")
    assert "**Isaac** (son of Abraham; b. c. 2066 BC)" in descendants
    assert "**Jacob** (son of Isaac" in descendants and "**Esau** (son of Isaac" in descendants
    assert "Judah" not in output
    assert "### Ancestors" not in output
    assert "**Spouse(s)**: Sarah" in output
    # The dictionary article is get_bible_dictionary's, not repeated here
    assert "test description" not in output
    assert "*For a dictionary article on Abraham, use get_bible_dictionary.*" in output


async def test_genealogy_resolves_an_alias(db):
    output = await call("explore_genealogy", person="Israel")
    assert output.startswith("## Genealogy of Jacob")
    assert "*'Israel' is listed as Jacob.*" in output
    assert "**Siblings**: Esau" in output


async def test_genealogy_graceful_messages(db):
    assert (
        await call("explore_genealogy", person="Goliath")
        == "No person found matching 'Goliath' in the Theographic database."
    )
    lone = await call("explore_genealogy", person="Melchizedek")
    assert "No parents or children are recorded for Melchizedek in the Theographic database." in lone
    assert "```mermaid" not in lone  # no empty diagram
    assert await call("explore_genealogy", person="") == "Please provide a person's name."
    for generations in (0, -1, "many"):
        assert (
            await call("explore_genealogy", person="Abraham", generations=generations)
            == "'generations' must be an integer from 1 to 40."
        )


def _drawn_parent_edges(output: str) -> set[tuple[str, str]]:
    """(parent name, child name) of every parent edge in the diagram; nodes are n_<id>."""
    names = {person_id: name for person_id, name, *_ in GRAPH_PEOPLE}
    edges = re.findall(r"^\s*n_(\w+?)(?:\[\"[^\"]*\"\])? -->\|(?:father|mother)\| n_(\w+?)(?:\[|$)",
                       output, re.MULTILINE)
    return {(names[parent], names[child]) for parent, child in edges}


async def test_genealogy_diagram_draws_only_real_parent_edges(db):
    output = await call("explore_genealogy", person="Hezron", direction="ancestors")
    names = {person_id: name for person_id, name, *_ in GRAPH_PEOPLE}
    real = {
        (names[parent], names[child])
        for parent, child, relation in GRAPH_FAMILY_EDGES
        if relation in ("father_of", "mother_of")
    }
    drawn = _drawn_parent_edges(output)
    assert drawn, "diagram has no parent edges"
    assert drawn <= real, sorted(drawn - real)


async def test_genealogy_diagram_draws_every_parent_edge_in_range(db):
    output = await call("explore_genealogy", person="Hezron", direction="ancestors")
    # Five generations up: Terah (sixth) is out of range.
    assert _drawn_parent_edges(output) == {
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
    # Event years are astronomical: -2091 is 2092 BC
    assert "- **Call of Abraham** (c. 2092 BC) — Haran\n" in output
    assert "- **Binding of Isaac** (c. 2055 BC) — Moriah; Gen 22:1\n" in output
    assert "Dates are approximate (c.), from the Theographic chronology" in output
    assert "```mermaid" not in output  # each event once, not again as a timeline


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
    assert "### Events at this location\n*Dates are approximate" in output
    assert "- **Death of Abraham** (c. 1992 BC)\n" in output
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
        "- Esau — Jacob (siblings)\n"
        "- Jacob → Judah → Perez → Hezron (each a parent of the next)\n"
    ) in output
    assert "```mermaid\ngraph LR" in output
    upward = await call("find_connection", person1="Hezron", person2="Abraham")
    assert "Hezron is a descendant of Abraham, 5 generations down." in upward
    assert "- Hezron → Perez → Judah → Jacob → Isaac → Abraham (each a child of the next)" in upward


async def test_find_connection_graceful_messages(db):
    unrelated = await call("find_connection", person1="Abraham", person2="Melchizedek")
    assert "No family connection between them is recorded in the Theographic database." in unrelated
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
    assert output.startswith("## Study Notes: John 3\n\n### Tyndale Study Notes")
    for text in ("Nicodemus came to Jesus by night", "God's love for the world"):
        assert text in output
    # Translator notes are listed by verse for a per-verse call, not shown
    # (the fixture's John 3 ends at verse 17, so the 3:14-18 note lists 14-17).
    assert "Lifted up" not in output
    assert (
        "*unfoldingWord on 3:14–17. Not shown for a passage: call get_study_notes "
        "with one verse (e.g. reference='John 3:14') for its notes.*"
    ) in output


async def test_study_notes_for_a_long_chapter_stop_near_the_budget(db):
    from study_bible_mcp.tools import STUDY_NOTES_PASSAGE_BUDGET

    output = await call("get_study_notes", reference="Romans 8")
    assert len(output) < STUDY_NOTES_PASSAGE_BUDGET + 1500
    shown = re.findall(r"^\*\*Romans 8:(\d+)\*\*$", output, re.MULTILINE)
    assert shown == [str(v) for v in range(1, len(shown) + 1)] and len(shown) < 12
    resume = len(shown) + 1
    # No verse table rows for Romans 8: the chapter ends at its last note (8:21).
    assert f"*Tyndale notes continue: call again with reference='Romans 8:{resume}-21'.*" in output
    assert "*SIL on 8:1–3, 5; unfoldingWord on 8:19–21." in output
    rest = await call("get_study_notes", reference=f"Romans 8:{resume}-21")
    assert rest.startswith(f"## Study Notes: Romans 8:{resume}-21\n\n### Tyndale Study Notes")
    assert re.findall(r"^\*\*Romans 8:(\d+)\*\*$", rest, re.MULTILINE) == [
        str(v) for v in range(resume, 13)
    ]
    assert "continue" not in rest
    assert "*unfoldingWord on 8:19–21." in rest and "SIL" not in rest


async def test_study_notes_for_a_verse_range_include_a_short_note_that_starts_before_it(db):
    output = await call("get_study_notes", reference="Romans 8:20-22")
    assert "### Tyndale Study Notes" not in output  # no Tyndale note touches 8:20-22
    assert "*unfoldingWord on 8:20–21." in output


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
    titles = re.findall(r"^## (.+)$", output, re.MULTILINE)
    # Four of the twelve titled matches; "Year" only mentions jubilee.
    assert titles == [f"Jubilee note {n:02d}" for n in range(1, 5)]
    gilboa = await call("get_bible_dictionary", topic="Gilboa")
    assert re.findall(r"^## (.+)$", gilboa, re.MULTILINE) == ["Mount Gilboa", "Saul"]
    long_article = await call("get_bible_dictionary", topic="Tabernacle")
    assert re.search(
        r'\*\[Truncated — 2,152 more characters\. Call get_bible_dictionary again with '
        r'topic="Tabernacle" and offset=3997\.\]\*', long_article
    )
    assert len(long_article) < 4300


async def test_bible_dictionary_graceful_messages(db):
    assert (
        await call("get_bible_dictionary", topic="zzzz") == "No dictionary article found for 'zzzz'."
    )
    assert await call("get_bible_dictionary", topic="") == "Please provide a topic to look up."


async def test_key_terms_by_title(db):
    output = await call("get_key_terms", term="atonement")
    assert output.startswith("## Atonement\n\nAtonement is the reconciling of God and people")
    # The audio-only duplicate of Grace is not shown.
    grace = await call("get_key_terms", term="grace")
    assert grace == "## Grace\n\nGrace is God's undeserved favour (test key term)."


async def test_key_terms_exact_title_lists_related_titles(db):
    output = await call("get_key_terms", term="Spirit")
    assert output.startswith("## spirit\n")
    assert "The Holy Spirit is the Spirit of God" not in output
    assert output.endswith("*Related key terms: 'Holy Spirit'.*")


async def test_key_terms_near_title(db):
    output = await call("get_key_terms", term="graces")
    assert output.startswith("*No key term is titled 'graces'; showing the nearest.*\n\n## Grace\n")


async def test_key_terms_without_a_title_match_list_titles_only(db):
    # A word found only in an entry's text names that entry; it is not shown.
    assert await call("get_key_terms", term="undeserved") == (
        "No key term found for 'undeserved'. Key terms whose entries mention it most: 'Grace'."
    )


async def test_key_terms_graceful_messages(db):
    # A dictionary title is not a key term.
    assert await call("get_key_terms", term="Covenant") == (
        "No key term found for 'Covenant'. Key terms are English titles such as 'grace', "
        "'covenant', or 'Son of Man'; for a Greek or Hebrew word use word_study."
    )
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


async def test_ane_context_limit_defaults_to_four_and_reports_the_total(db):
    output = await call("get_ane_context", reference="Leviticus 16:1", detail_level="brief")
    assert re.findall(r"^### Levitical filler (\d+)$", output, re.MULTILINE) == ["01", "02", "03", "04"]
    assert (
        "*Showing 4 of 32 entries, direct chapter matches first; raise limit (at most 30) "
        "or set dimension/period for more.*"
    ) in output
    more = await call("get_ane_context", reference="Leviticus 16:1", detail_level="brief", limit=30)
    assert len(re.findall(r"^### Levitical filler \d+$", more, re.MULTILINE)) == 30  # of 32
    assert "*Showing 30 of 32 entries" in more


async def test_ane_context_puts_direct_matches_first(db):
    output = await call("get_ane_context", reference="Genesis 15:6", limit=2)
    assert re.findall(r"^### (.+)$", output, re.MULTILINE) == [
        "Covenant-cutting ritual", "Smoking firepot theophany",
    ]
    assert "*Showing 2 of 3 entries, direct chapter matches first;" in output
    assert "# General ANE Reading Frame" not in output


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


async def test_torah_weave_reading_guide_only_on_request(db):
    output = await call("get_torah_weave", reference="Genesis 1:1")
    assert "### How to read Torah Weave partners" not in output
    assert output.rstrip().endswith(
        "*Partner text: `lookup_verse` on each range. Kline's dataset does not label "
        "column themes. Full reading guide: explain=true.*"
    )
    explained = await call("get_torah_weave", reference="Genesis 1:1", explain=True)
    assert "### How to read Torah Weave partners" in explained
    assert "Full reading guide: explain=true" not in explained
    assert len(output) < len(explained) - 1000


async def test_torah_weave_graceful_messages(db):
    assert await call("get_torah_weave", reference="Matthew 5:1") == (
        "Torah Weave data covers Genesis–Deuteronomy only; Matthew 5:1 is outside it."
    )
    assert await call("get_torah_weave", reference="Exodus 3:1") == (
        "No Torah Weave unit in Kline's dataset contains Exodus 3:1."
    )
    assert await call("get_torah_weave", reference="Genesis") == (
        "Could not read 'Genesis' as a Bible reference. Give a verse such as "
        "'Leviticus 19:18', or a chapter such as 'Leviticus 19'."
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


# ---------------------------------------------------------------------------
# Shared limit validation and lexicon rendering
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("value", "expected"), [(1, 1), (20, 20), ("7", 7), (3.0, 3)])
def test_bounded_limit_accepts_whole_numbers_in_range(value, expected):
    assert server.bounded_limit(value, 20) == expected


@pytest.mark.parametrize("value", [0, -1, 21, "many", "", 2.5, True, None, [4]])
def test_bounded_limit_rejects_other_values(value):
    with pytest.raises(server.ToolInputError, match=r"^'limit' must be an integer from 1 to 20\.$"):
        server.bounded_limit(value, 20)


def test_search_lexicon_example_names_only_new_testament_words():
    tool = next(tool for tool in server.TOOLS if tool.name == "search_lexicon")
    assert "erōs" not in tool.description and "agapē, agapaō, phileō" in tool.description


def test_lexicon_entry_is_cleaned_and_compact():
    from study_bible_mcp.tools import LEXICON_DEFINITION_LIMIT, format_lexicon_entry

    synonyms = "SYN.: φιλία, friendship (test synonym note)."
    entry = {
        "strongs": "G9998", "word": "ἀγάπη", "transliteration": "agapē", "pronunciation": "agapē",
        "language": "greek", "short_definition": "love &amp; esteem",
        "full_definition": (
            "** ἀγάπ-η**, ἡ, **love,** [LXX] **__2** **brotherly love, charity,** [NT] "
            "**__II** **love-feast,** [NT] **alms** &#8212; Isis &gt; title"
        ),
        "abbott_smith_def": (
            "[NT: 116x] Of divine love&#x200E;. " + "Sentence of commentary. " * 120
            + f"**Synonyms**: {synonyms}"
        ),
        "synonyms": synonyms,
        "usage_count": 116, "nt_occurrences": 116,
    }
    output = format_lexicon_entry(entry)
    assert "&amp;" not in output and "&#" not in output and "\u200e" not in output
    assert "### Brief Definition\nlove & esteem" in output
    assert "**Pronunciation**" not in output  # same as the transliteration
    # The Synonyms paragraph prints once, under its own heading.
    assert output.count("friendship (test synonym note)") == 1
    assert "### Synonyms\nSYN.: φιλία, friendship (test synonym note)." in output
    # One usage line, not a Bible count and an equal NT count.
    assert output.count("Occurs 116 times") == 1
    assert "**Usage**: Occurs 116 times in the New Testament" in output
    # The classical LSJ entry is reduced to its glosses beside Abbott-Smith.
    assert "### LSJ Senses (Classical Greek)\nlove, brotherly love, charity, love-feast, alms" in output
    assert "Full LSJ Definition" not in output
    # A long definition is cut at a sentence end.
    abbott = output[output.index("### Abbott-Smith"):output.index("### LSJ Senses")]
    assert len(abbott) < LEXICON_DEFINITION_LIMIT + 200
    assert "Sentence of commentary.\n\n*[Definition cut — the full entry is in Abbott-Smith]*" in abbott


async def test_search_by_strongs_pages_with_offset(db):
    first = await call("search_by_strongs", strongs="G26", limit=8)
    assert "*Next page: offset=8.*" in first
    second = await call("search_by_strongs", strongs="G26", limit=8, offset=8)
    assert "*Showing 9–16 of 21 verses;" in second and "*Next page: offset=16.*" in second
    last = await call("search_by_strongs", strongs="G26", limit=8, offset=16)
    assert "*Showing 17–21 of 21 verses;" in last and "Next page" not in last
    pages = _verse_hits(first) + _verse_hits(second) + _verse_hits(last)
    assert pages == [f"1Jn.4.{v}" for v in range(1, 22)]
    assert "No more verses with G26 at offset 21." in await call("search_by_strongs", strongs="G26", offset=21)
    assert "'offset' must be" in await call("search_by_strongs", strongs="G26", offset=-1)


async def test_lookup_name_pages_with_offset(names_db):
    first = await call("lookup_name", name="Ai", limit=4)
    assert "*Next page: offset=4.*" in first
    rest = await call("lookup_name", name="Ai", limit=4, offset=4)
    assert _name_hits(rest) == ["Sinai", "Abigail", "Mordecai"]
    assert "*Showing 5–7 of 7 matching names;" in rest and "Next page" not in rest
