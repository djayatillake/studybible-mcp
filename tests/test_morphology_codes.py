"""parse_morphology: codes as the tagged text prints them, and the TEGMC/TEHMC parser."""

from __future__ import annotations

import sqlite3

import pytest

import study_bible_mcp.server as server
from study_bible_mcp.database import StudyBibleDB, create_schema
from study_bible_mcp.morphology import morphology_columns, morphology_lookups, parse_fields
from study_bible_mcp.parsers.tagged_text import parse_morphology_codes

QAL_PERFECT = (
    "Function=Verb ; Stem=Qal (hence Action=Simple; Voice=Active); Form=Perfect "
    "(hence Tense=Past/present; Mood=Indicative); Person=Third; Gender=Masculine; Number=Singular"
)
EXPANSIONS = {
    ("HC", "hebrew"): "Function=Conjunction ",
    ("Hc", "hebrew"): "Function=Conjunction; Form=Consecutive;  ",
    ("HVqp3ms", "hebrew"): QAL_PERFECT,
    ("HVqw3ms", "hebrew"): QAL_PERFECT.replace("Form=Perfect", "Form=Consecutive Imperfect"),
    ("HVhq3ms", "hebrew"): QAL_PERFECT.replace("Stem=Qal", "Stem=Hiphil"),
    ("HVHq3ms", "hebrew"): QAL_PERFECT.replace("Stem=Qal", "Stem=Hophal"),
    ("HNcmpa", "hebrew"): "Function=Noun ; Form=Common ; Gender=Masculine; Number=Plural; State=Absolute",
    ("HSp3ms", "hebrew"): "Function=Suffix ; Form=Personal ; Person=Third; Gender=Masculine; Number=Singular",
    ("V-AAI-3S", "greek"): "Function=Verb; Tense=Aorist; Voice=Active; Mood=Indicative; Person=3rd; Number=Singular",
    ("V-2ADS-3S", "greek"): "Function=Verb; Tense=2nd Aorist; Voice=Middle Deponent; Mood=Subjunctive; "
                            "Person=3rd; Number=Singular",
    ("V-PAP-NSM", "greek"): "Function=Verb; Tense=Present; Voice=Active; Form=Participle; Case=Nominative; "
                            "Number=Singular; Gender=Masculine",
    ("P-1NS", "greek"): "Function=Personal pronoun; Person=1st; Case=Nominative; Number=Singular",
    ("CONJ", "greek"): "Function=Conjunction",
}


@pytest.fixture
async def db(tmp_path, monkeypatch):
    path = tmp_path / "morphology.db"
    conn = sqlite3.connect(path)
    create_schema(conn)
    for (code, language), parsing in EXPANSIONS.items():
        # The old importer's columns: Hebrew part of speech "H", 2nd aorist "Active".
        conn.execute(
            "INSERT INTO morphology (code, language, parsing, part_of_speech, voice) VALUES (?, ?, ?, ?, ?)",
            (code, language, parsing, "H" if language == "hebrew" else "Verb", "Active"),
        )
    conn.commit()
    conn.close()
    database = StudyBibleDB(path)
    await database.connect()
    monkeypatch.setattr(server, "db", database)
    yield database
    await database.close()


async def parse(**arguments) -> str:
    (response,) = await server.call_tool("parse_morphology", arguments)
    return response.text


@pytest.mark.parametrize("code", ["Hc/Vqw3ms", "HC/Vqw3ms"])
async def test_hebrew_prefix_compounds_parse(db, code):
    output = await parse(code=code)
    assert "**Language**: Hebrew" in output and "**Parts**: 2 words joined by '/'" in output
    first = "Conjunction; Form: Consecutive" if code.startswith("Hc") else "Conjunction\n"
    assert f"**1. {code[:2]}**: {first}" in output
    assert "**2. Vqw3ms**: Verb; Stem: Qal (Action: Simple; Voice: Active); " \
           "Form: Consecutive Imperfect (Tense: Past/present; Mood: Indicative)" in output


async def test_suffix_compound_and_bare_and_lowercase_codes(db):
    assert "**2. Sp3ms**: Suffix; Form: Personal" in await parse(code="HNcmpa/Sp3ms")
    bare = await parse(code="Vqp3ms")  # no language letter, default language greek
    assert "**Language**: Hebrew\n**Part of Speech**: Verb\n**Stem**: Qal" in bare
    lower = await parse(code="v-aai-3s")
    assert "**Language**: Greek\n**Part of Speech**: Verb\n**Tense**: Aorist" in lower
    crasis = await parse(code="P-1NS + G2532=CONJ")
    assert "**1. P-1NS**: Personal pronoun" in crasis and "**2. CONJ**: Conjunction" in crasis


async def test_header_fields_come_from_the_expansion(db):
    hebrew = await parse(code="HNcmpa", language="hebrew")
    assert "**Part of Speech**: Noun" in hebrew and "**Part of Speech**: H" not in hebrew
    second_aorist = await parse(code="V-2ADS-3S")
    assert "**Voice**: Middle Deponent" in second_aorist and "Active" not in second_aorist
    assert "**Tense**: 2nd Aorist" in second_aorist
    participle = await parse(code="V-PAP-NSM")
    for line in ("**Tense**: Present", "**Voice**: Active", "**Form**: Participle",
                 "**Case**: Nominative", "**Gender**: Masculine"):
        assert line in participle


async def test_a_case_ambiguous_code_lists_its_readings(db):
    output = await parse(code="hvhq3ms")
    assert "Codes are case-sensitive" in output
    assert "as **HVHq3ms**: Verb; Stem: Hophal" in output
    assert "as **HVhq3ms**: Verb; Stem: Hiphil" in output
    assert await parse(code="HVhq3ms") != output  # the exact code is not ambiguous


async def test_unknown_codes(db):
    assert await parse(code="X-YYY") == "Unknown morphology code: X-YYY"
    assert await parse(code="HC/Zzz") == "Unknown morphology code: HC/Zzz"


def test_lookups_try_the_requested_language_first():
    assert morphology_lookups("Hc/Vqw3ms")[-1] == ("hebrew", [("Hc", "Hc"), ("Vqw3ms", "HVqw3ms")])
    assert morphology_lookups("Vqp3ms", "hebrew")[0] == ("hebrew", [("Vqp3ms", "HVqp3ms")])
    assert morphology_lookups("v-aai-3s")[0] == ("greek", [("v-aai-3s", "V-AAI-3S")])


def test_fields_and_columns_from_an_expansion():
    assert parse_fields(QAL_PERFECT)[:3] == [
        ("Part of Speech", "Verb"),
        ("Stem", "Qal (Action: Simple; Voice: Active)"),
        ("Form", "Perfect (Tense: Past/present; Mood: Indicative)"),
    ]
    assert parse_fields("Verb, Aorist") is None
    columns = morphology_columns(QAL_PERFECT)
    assert (columns["part_of_speech"], columns["voice"], columns["tense"], columns["person"]) == (
        "Verb", "Active", "Past/present", "Third",
    )
    participle = morphology_columns(EXPANSIONS[("V-PAP-NSM", "greek")])
    assert (participle["mood"], participle["case_value"], participle["gender"]) == (
        "Participle", "Nominative", "Masculine",
    )


def test_expansion_files_keep_key_value_rows_and_brief_meanings(tmp_path):
    path = tmp_path / "TEGMC.txt"
    path.write_text(
        "Code\tExample in English\tMeaning\n"
        "G:A\tthoughtful\tGreek Adjective\n"
        "S-2PASM\tFunction=Possessive pronoun; Person=2nd Person; Case=Accusative\n"
        "\tPossessive pronoun 2nd Person Accusative\n"
        "$\n"
        "V-PMO-3P\t-1\tVerb\tPresent\n"
        "S-2PASM\tKJV\n",
        encoding="utf-8",
    )
    rows = {row["code"]: row for row in parse_morphology_codes(path, "greek")}
    assert set(rows) == {"G:A", "S-2PASM"}
    assert rows["G:A"]["parsing"] == rows["G:A"]["part_of_speech"] == "Greek Adjective"
    assert rows["S-2PASM"]["parsing"].startswith("Function=Possessive pronoun")
    assert rows["S-2PASM"]["case_value"] == "Accusative"
