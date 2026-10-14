"""The owner's editorial corrections to curated content (QA batch).

- HLT renderings and rationales stay in the database but are not printed.
- list_research_sources defaults to a mix of perspectives; STEP links open a
  passage when the query is a Bible reference.
- Targum Onkelos is labelled as a stated exception to the c. AD 200 limit.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import pytest

import study_bible_mcp.server as server_module
from scripts.import_heiser_content import import_textual_variant_record
from scripts.ingest_burnett_gage import BURNETT_THEOLOGY
from study_bible_mcp.corpora import CORPORA, TIERS, editorial_notes
from study_bible_mcp.database import StudyBibleDB, create_schema
from study_bible_mcp.parsers.heiser import parse_heiser_content_file
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


# ---------------------------------------------------------------------------
# Curated content (decisions 2-5, 7, 8)
# ---------------------------------------------------------------------------

DATA = Path(__file__).resolve().parent.parent / "data"
# tests/conftest.py points NOTES_PATH at an empty file; read the committed one.
COMMITTED_NOTES = Path(editorial_notes.__file__).with_name("editorial_notes.json")
NON_CANONICAL = re.compile(r"non-canonical|not canonical|pseudepigraph|outside (the )?canon", re.I)


def _variants() -> dict:
    return {
        (record["reference"], record["variant_source"]): record
        for path in sorted((DATA / "heiser" / "variants").glob("*.json"))
        for record in json.loads(path.read_text(encoding="utf-8"))["variants"]
    }


def _ane() -> dict:
    return {
        entry["id"]: entry
        for path in sorted((DATA / "ane_context").glob("*.json"))
        for entry in json.loads(path.read_text(encoding="utf-8"))["entries"]
    }


def _themes() -> dict:
    themes = json.loads((DATA / "heiser" / "themes.json").read_text(encoding="utf-8"))["themes"]
    return {theme["theme_key"]: theme["description"] for theme in themes}


def _content() -> list[dict]:
    return [
        entry
        for path in sorted(DATA.glob("*/content/*.json"))
        for entry, _, _ in parse_heiser_content_file(path)
    ] + BURNETT_THEOLOGY


def _all_curated_text() -> str:
    parts = [json.dumps(record, ensure_ascii=False) for record in _variants().values()]
    parts += [json.dumps(entry, ensure_ascii=False) for entry in _ane().values()]
    parts += list(_themes().values())
    parts += [f"{e['content_summary']} {e['content_detail']}" for e in _content()]
    return "\n".join(parts)


def test_consensus_overclaims_and_motive_attributions_are_gone():
    text = _all_curated_text()
    for phrase in ("universally recognized", "universally identified", "universally understood",
                   "universally noted", "was universal in", "universal pre-Christian",
                   "theological anxiety", "without textual support",
                   "noted by all major commentaries", "Nearly fifty sources",
                   "equally unanimous", "lacks textual support"):
        assert phrase not in text, phrase
    psalm_82 = _variants()[("Psa.82.1", "MT_preserved")]["scholarly_consensus"]
    assert "Heiser and other divine-council scholars hold" in psalm_82 and "Calvin" in psalm_82


def test_contested_readings_are_attributed():
    themes, ane = _themes(), _ane()
    assert themes["cherem_warfare"].startswith("Heiser reads")
    assert "This is contested" in themes["cherem_warfare"]
    assert "resolves the 'us'" not in ane["cosmo_008"]["interpretive_significance"]
    assert "Trinity" in ane["cosmo_008"]["interpretive_significance"]
    assert "bodily resurrection" in ane["death_005"]["interpretive_significance"]


def test_atonement_ratings_use_the_method_002_tiers():
    ane = _ane()
    for key in ("relig_013", "relig_014", "relig_015", "relig_016", "relig_020", "relig_021",
                "legal_009"):
        significance = ane[key]["interpretive_significance"]
        assert "Demonstrable." not in significance and " demonstrable" not in significance, key
        assert "method_002 tiers" in significance and "requires connecting texts" in significance
    method_007 = ane["method_007"]["interpretive_significance"]
    assert "not contested" not in method_007
    assert "Eusebius, Athanasius, Augustine" in method_007
    assert "theme='penal_substitution'" in method_007
    assert "debated" in ane["method_007"]["summary"]


def test_pseudepigrapha_in_curated_text_are_labelled_non_canonical():
    unlabelled = []
    for key, entry in _ane().items():
        for field in ("summary", "detail", "interpretive_significance"):
            if "1 Enoch" in (entry.get(field) or "") and not NON_CANONICAL.search(entry[field]):
                unlabelled.append((key, field))
        unlabelled += [
            (key, "ane_parallels") for item in entry.get("ane_parallels") or []
            if "1 Enoch" in item and not NON_CANONICAL.search(item)
        ]
    for key, description in _themes().items():
        if "1 Enoch" in description and not NON_CANONICAL.search(description):
            unlabelled.append(key)
    for key, record in _variants().items():
        for field in ("variant_reading", "heiser_analysis", "scholarly_consensus"):
            if "1 Enoch" in (record.get(field) or "") and not NON_CANONICAL.search(record[field]):
                unlabelled.append((key, field))
        assert not any("Enoch" in w["manuscript"] for w in record["witnesses"]), key
    for entry in _content():
        text = f"{entry['content_summary']} {entry['content_detail']}"
        if "1 Enoch" in text and not NON_CANONICAL.search(text):
            unlabelled.append(entry["title"])
    assert unlabelled == []
    method_002 = _ane()["method_002"]["detail"]
    assert "(canonical basis: Jude 6, 2 Pet 2:4; the non-canonical 1 Enoch is background" \
        in method_002


def test_new_1_enoch_links_pair_watchers_and_son_of_man_passages():
    links = editorial_notes.load_editorial_notes(COMMITTED_NOTES).links
    pairs = {(link.citation, link.book, link.chapter, link.verse) for link in links}
    for citation in ("1 Enoch 1:5", "1 Enoch 10:15", "1 Enoch 12:2"):
        assert (citation, "Gen", 6, 1) in pairs and (citation, "Jud", 1, 6) in pairs
    assert ("1 Enoch 1:5", "2Pe", 2, 4) in pairs
    for citation in ("1 Enoch 69:29", "1 Enoch 71:13"):
        assert (citation, "Dan", 7, 13) in pairs
    assert ("1 Enoch 69:29", "Mat", 25, 31) in pairs


def test_nachash_theme_is_heisers_view_with_the_methodology_caveat():
    nachash = _themes()["nachash_serpent"]
    assert "Heiser reads the Eden figure" in nachash and "speculative" in nachash
    assert "Nahash = 'shining one'" in _ane()["method_002"]["detail"]  # the caveat it cites


def test_genesis_6_2_greek_case():
    records = _variants()
    case = records[("Gen.6.2", "LXX_manuscript_variant")]
    assert case["variant_significance"] == "minor_textual"
    assert case["variant_original"] == "οἱ ἄγγελοι τοῦ θεοῦ"
    assert "ἰδόντες δὲ οἱ υἱοὶ τοῦ θεοῦ τὰς θυγατέρας τῶν ἀνθρώπων" in case["scholarly_consensus"]
    assert "πολλοὶ γὰρ ἄγγελοι θεοῦ γυναιξὶ συνιόντες" in case["scholarly_consensus"]
    assert "Gig. 6" in case["scholarly_consensus"]
    notes = records[("Gen.6.2", "MT_preserved")]
    assert "rabbinic innovation" not in notes["heiser_analysis"]
    assert "1 Enoch 6–16 (the Book of the Watchers, non-canonical" in notes["variant_reading"]


def test_factual_corrections():
    text = _all_curated_text()
    assert "El Elyon (the Most High" not in text and "El, with Athirat (Asherah)" in text
    assert "4QDeutj,n" not in text
    assert "over 1000 times" not in text and "over 2000 times" not in text
    assert "full text of 1 Enoch" not in text
    assert "Sethite interpretation popularized in the rabbinic period" not in text
    assert "Julius Africanus" in _themes()["sons_of_god"]
    records = _variants()
    deut_32_8 = {w["manuscript"] for w in records[("Deu.32.8", "DSS_4QDeutj")]["witnesses"]}
    assert "4QDeutj" in deut_32_8 and "4QDeutq" not in deut_32_8
    deut_32_43 = records[("Deu.32.43", "DSS_4QDeutq")]
    assert deut_32_43["variant_original"] == "הרנינו שמים עמו והשתחוו לו כל אלהים"
    assert "strengthen" not in deut_32_43["variant_reading"]
    psalm_40 = records[("Psa.40.6", "LXX_quoted_in_NT")]["scholarly_consensus"]
    assert "verbatim" in psalm_40 and "not verbatim" in psalm_40 and "ὠτία" in psalm_40
    assert "οὐκ εὐδόκησας" in psalm_40
    for key, record in records.items():
        if key[0].startswith("Psa."):
            dates = {w["manuscript_date"] for w in record["witnesses"]
                     if w["manuscript"].startswith("LXX")}
            assert "~250 BCE" not in dates, key
