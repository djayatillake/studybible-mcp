"""The owner's editorial corrections to curated content (QA batch).

- HLT renderings and rationales stay in the database but are not printed.
- list_research_sources defaults to a mix of perspectives; STEP links open a
  passage when the query is a Bible reference.
- Targum Onkelos is labelled as a stated exception to the c. AD 200 limit.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import study_bible_mcp.server as server_module
from scripts.import_heiser_content import import_textual_variant_record
from study_bible_mcp.corpora import CORPORA, TIERS
from study_bible_mcp.database import StudyBibleDB, create_schema
from study_bible_mcp.tools import (
    RESEARCH_SOURCES_DEFAULT_MIX,
    _format_interpretation_sections,
    find_research_sources,
    load_research_sources,
    research_search_url,
)

HLT = "Heiser Literal Translation (HLT)"


@pytest.fixture
async def server_db():
    databases = []

    async def connect(path: Path) -> StudyBibleDB:
        database = StudyBibleDB(path)
        await database.connect()
        databases.append(database)
        server_module.db = database
        return database

    yield connect
    server_module.db = None
    for database in databases:
        await database.close()


# ---------------------------------------------------------------------------
# 1. HLT hidden from tool output
# ---------------------------------------------------------------------------


@pytest.fixture
def hlt_db(tmp_path) -> Path:
    path = tmp_path / "hlt.db"
    conn = sqlite3.connect(path)
    create_schema(conn)
    import_textual_variant_record(conn, {
        "reference": "Psa.82.6",
        "mt_reading": "I said, 'You are gods'",
        "mt_hebrew": "אֱלֹהִים אַתֶּם",
        "variant_source": "MT_preserved",
        "variant_reading": "Yahweh calls the council members gods.",
        "variant_original": "Same text",
        "variant_significance": "major_theological",
        "heiser_analysis": "Heiser: divine beings.",
        "scholarly_consensus": "Dominant in Hebrew Bible scholarship.",
        "preferred_for_hlt": "You are gods (elohim — divine beings)",
        "hlt_rationale": "The HLT preserves the Hebrew elohim.",
        "witnesses": [
            {"manuscript": "Masoretic Text", "manuscript_date": "~900 CE",
             "reading_support": "supports_variant"},
        ],
    })
    conn.execute(
        "INSERT INTO verses (reference, book, chapter, verse, text_english) "
        "VALUES ('Psa.82.6', 'Psa', 82, 6, 'I said, You are gods')"
    )
    conn.commit()
    conn.close()
    return path


async def test_hlt_rendering_and_rationale_are_not_printed(hlt_db, server_db):
    await server_db(hlt_db)
    [variant] = await server_module.handle_get_textual_variant({"reference": "Psalm 82:6"})
    [verse] = await server_module.handle_lookup_verse({"reference": "Psalm 82:6"})

    assert "Heiser: divine beings." in variant.text  # the attributed layers remain
    for hidden in ("HLT", "Heiser Literal Translation", "divine beings)", "Translation decisions"):
        assert hidden not in variant.text
    assert "translation decisions" not in verse.text.lower()
    assert "Translation and interpretation notes catalogued for this verse" in verse.text

    # The data stays in the database.
    conn = sqlite3.connect(hlt_db)
    assert conn.execute(
        "SELECT translation, rationale FROM textual_translation_decisions"
    ).fetchall() == [(HLT, "The HLT preserves the Hebrew elohim.")]
    conn.close()


def test_other_translations_decisions_would_still_print():
    lines = "\n".join(_format_interpretation_sections({"translation_decisions": [
        {"translation": HLT, "preferred_reading": "hidden", "rationale": "hidden"},
        {"translation": "Some Published Version", "preferred_reading": "shown",
         "rationale": "why"},
    ]}))
    assert "hidden" not in lines
    assert "- **Some Published Version:** shown" in lines


def test_get_textual_variant_description_no_longer_promises_translation_decisions():
    tool = next(tool for tool in server_module.TOOLS if tool.name == "get_textual_variant")
    assert "Translation decisions" not in tool.description


# ---------------------------------------------------------------------------
# 9. list_research_sources: a mixed default and STEP passage links
# ---------------------------------------------------------------------------


def test_default_research_sources_are_a_mix_of_perspectives():
    sources = find_research_sources()
    lead = sources[:len(RESEARCH_SOURCES_DEFAULT_MIX)]
    assert [s["key"] for s in lead] == list(RESEARCH_SOURCES_DEFAULT_MIX)
    assert {s["perspective"] for s in lead} == {
        "evangelical", "multi-tradition", "Jewish", "academic/critical",
    }
    # Nothing is dropped; the rest keep catalogue order.
    catalogue = [s["key"] for s in load_research_sources()]
    rest = [s["key"] for s in sources[len(lead):]]
    assert sorted(rest + list(RESEARCH_SOURCES_DEFAULT_MIX)) == sorted(catalogue)
    assert rest == [key for key in catalogue if key not in RESEARCH_SOURCES_DEFAULT_MIX]


async def test_default_tool_output_is_no_longer_four_jewish_sites():
    [result] = await server_module.handle_list_research_sources({})
    assert result.text.count("\n### ") == 4
    assert "### Tyndale Bulletin" in result.text
    assert "### STEP Bible (Tyndale House, Cambridge)" in result.text
    assert "### Sefaria" in result.text
    assert "AlHaTorah" not in result.text and "Mechon Mamre" not in result.text


def test_perspective_and_topic_filters_are_unchanged():
    assert [s["key"] for s in find_research_sources(perspective="Jewish")] == [
        s["key"] for s in load_research_sources() if s["perspective"] == "Jewish"
    ]
    assert find_research_sources(topic="rabbinic")[0]["key"] == "sefaria"


@pytest.mark.parametrize(("query", "expected"), [
    ("Deuteronomy 32:8", "https://www.stepbible.org/?q=reference=Deuteronomy+32%3A8"),
    ("Psalm 82", "https://www.stepbible.org/?q=reference=Psalm+82"),
    ("sons of God", "https://www.stepbible.org/?q=text=sons+of+God"),
])
def test_step_links_open_a_passage_for_a_reference(query, expected):
    step = next(s for s in load_research_sources() if s["key"] == "step_bible")
    assert research_search_url(step, query) == expected


def test_only_step_has_a_reference_template():
    with_reference = [s["key"] for s in load_research_sources() if s.get("reference_url_template")]
    assert with_reference == ["step_bible"]


# ---------------------------------------------------------------------------
# 6. Targum Onkelos: a stated exception to the c. AD 200 limit
# ---------------------------------------------------------------------------


def test_onkelos_labels_state_its_final_form_and_the_exception():
    targum = CORPORA["targum"]
    tag = targum.work_tag(targum.works[0]).line()
    assert "final form c. 3rd–5th c. AD, Babylonia; earlier tradition" in tag
    assert "tier B" in tag
    assert "stated exception" in targum.caveat and "3rd–5th century AD" in targum.caveat
    assert "Targum Onkelos" in TIERS["B"] and "stated exception" in TIERS["B"]
