"""Brief definitions from STEPBible glosses, the TFLSJ/BDB parsers, and their repair script."""

from __future__ import annotations

import gzip
import json
import shutil
import sqlite3
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

import scripts.repair_lexicon_and_morphology as repair
from study_bible_mcp.database import create_schema
from study_bible_mcp.lexicon_glosses import (
    brief_definition,
    brief_pronunciation,
    gloss_row,
    is_grammar_label,
    update_brief_definitions,
)
from study_bible_mcp.parsers.lexicon import parse_bdb_lexicon, parse_tflsj_lexicon


def _line(*columns: str) -> str:
    return "\t".join(columns)


# TBESH rows: eStrong, dStrong = relation, uStrong, word, transliteration, morph, gloss, meaning.
TBESH = [
    _line("H0430", "H0430G = a Name of", "H3068G", "אֱלֹהִים", "e.lo.him", "H:N-M", "God", "gods"),
    _line("H0430", "H0430H = a Part of", "H3068G", "אֱלֹהִים", "e.lo.him", "H:N-M", "(LORD)-Elohe", ""),
    _line("H1121a", "H1121A =", "H1121A", "בֵּן", "ben", "H:N-M", "son: child", ""),
    _line("H1121b", "H1121B =", "H1121B", "בְּנוֹ", "be.no", "N:N-M-P", "Beno", ""),
    _line("H1121a", "H1121G = a Meaning of", "H1121A", "בֵּן", "ben", "H:N-M", "son: descendant/people", ""),
    _line("H2617a", "H2617A =", "H2617A", "חֶ֫סֶד", "che.sed", "H:N-M", "kindness", ""),
    _line("H2617b", "H2617B =", "H2617B", "חֶ֫סֶד", "che.sed", "H:N-M", "shame", ""),
    _line("H3722a", "H3722A =", "H3722A", "כִּפֶּר", "ki.pher", "H:V", "to atone", ""),
    _line("H3722b", "H3722B =", "H3722B", "כָּפַר", "ka.phar", "H:V", "to cover", ""),
    _line("H4057a", "H4057A =", "H4057A", "מִדְבָּר", "mid.bar", "H:N-M", "mouth", ""),
    _line("H4057b", "H4057B =", "H4057B", "מִדְבָּר", "mid.bar", "H:N-M", "wilderness", ""),
    _line("H4057b", "H4057G =", "H4057G", "מִדְבָּר", "mid.bar", "H:N-M", "Wilderness (of Sinai)", ""),
    _line("H7676", "H7676 =", "H7676", "שַׁבָּת", "shab.bat", "H:N-F", "Sabbath", ""),
]
# TBESG/TFLSJ rows; column 7 is the definition (HTML in TFLSJ).
TFLSJ = [
    _line("G0863", "G0863G =", "G0863G", "ἀφίημι", "aphiēmi", "G:V", "to release: leave", "<b>ἀφίημι</b> send away"),
    _line("G0863", "G0863H = a Meaning of", "G0863G", "ἀφίημι", "aphiēmi", "G:V", "to release: forgive", "<b>ἀφίημι</b> send away"),
    _line("G0863", "G0863I = a Meaning of", "G0863G", "ἀφίημι", "aphiēmi", "G:V", "to release: permit", "<b>ἀφίημι</b> send away"),
    _line("G2424", "G2424G =", "G2424G", "Ἰησοῦς", "Iēsous", "N:N-M-P", "Jesus", "Jesus, Greek form of <b>Joshua</b>"),
    _line("G2424", "G2424K =", "G2424K", "Ἰησοῦς", "Iēsous", "N:N-M-P", "Joshua", "<b>Ἰωσή</b>, see Ἰωσῆς, <b>Joses</b>"),
    _line("G2570", "G2570G =", "G2570G", "καλός", "kalos", "G:A", "good", "<b>καλός</b> beautiful"),
    _line("G2570", "G2570H =", "G2570H", "καλός", "kalos", "N:A--L", "Fair (Havens)", "<b>καλός</b> beautiful"),
    _line("G4074", "G4074H =", "G4074H", "[unnamed]", "Petros", "N:N-F-P", "[mother-in-law of Peter]", "<b>Πέτρος</b> Peter"),
    _line("G4074", "G4074G =", "G4074G", "Πέτρος", "Petros", "N:N-M-P", "Peter", "<b>Πέτρος</b> Peter"),
]


def _rows(lines: list[str], strongs: str):
    rows = [gloss_row(line.split("\t"), n) for n, line in enumerate(lines)]
    return [row for row in rows if row and row.strongs == strongs]


# ---------------------------------------------------------------------------
# brief_definition
# ---------------------------------------------------------------------------


def test_the_most_used_sense_leads_and_names_are_dropped():
    rows = _rows(TBESH, "H4057")
    # In file order "mouth" (Song 4:3 only) comes first; the tagged text
    # uses "wilderness" 269 times.
    assert brief_definition(rows) == "mouth; wilderness"
    assert brief_definition(rows, Counter({"H4057B": 269, "H4057A": 1, "H4057G": 1})) == (
        "wilderness; mouth"
    )
    assert brief_pronunciation(rows, Counter({"H4057B": 269})) == "mid.bar"


@pytest.mark.parametrize(
    ("strongs", "lines", "expected"),
    [
        ("H0430", TBESH, "God"),  # not "noun masculine plural", nor "(LORD)-Elohe"
        ("H1121", TBESH, "son: child, descendant/people"),  # "Beno" is a name
        ("H3722", TBESH, "to atone; to cover"),  # not "verb Pi`el"
        ("H7676", TBESH, "Sabbath"),  # not "masculine"
        ("G0863", TFLSJ, "to release: leave, forgive, permit"),
        ("G2570", TFLSJ, "good"),  # not "Fair (Havens)"
        ("G4074", TFLSJ, "Peter"),  # not "[mother-in-law of Peter]"
        ("G2424", TFLSJ, "Jesus; Joshua"),  # all names: kept
    ],
)
def test_brief_definitions_are_glosses(strongs, lines, expected):
    assert brief_definition(_rows(lines, strongs)) == expected


def test_grammar_labels_are_recognised():
    for label in ("noun masculine plural", "verb Pi`el", "masculine", "noun [masculine]",
                  "proper name, of a location 1.", "Qal"):
        assert is_grammar_label(label), label
    for gloss in ("mouth", "love", "constantly, as more precise designation", ""):
        assert not is_grammar_label(gloss), gloss


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def test_tflsj_gives_one_entry_per_number_from_its_main_row(tmp_path):
    path = tmp_path / "TFLSJ_0-5624.txt"
    path.write_text("\n".join(TFLSJ) + "\n", encoding="utf-8")
    entries = {entry["strongs"]: entry for entry in parse_tflsj_lexicon(path)}
    assert list(entries) == ["G0863", "G2424", "G2570", "G4074"]
    # The last row used to win: Jesus carried the Joses article, Peter was
    # "[mother-in-law of Peter]" with the word "[unnamed]".
    assert entries["G2424"]["full_definition"] == "Jesus, Greek form of **Joshua**"
    assert entries["G2424"]["short_definition"] == "Jesus; Joshua"
    assert entries["G4074"]["word"] == "Πέτρος"
    assert entries["G4074"]["short_definition"] == "Peter"
    assert entries["G2570"]["short_definition"] == "good"


def test_bdb_brief_skips_grammar_labels(tmp_path):
    path = tmp_path / "DictBDB.json"
    path.write_text(json.dumps([{
        "top": "H430",
        "def": "<b>H430. elohim</b> <font class='c3'>אֱלֹהִים</font> <b>noun masculine plural</b> "
               "(<b>feminine</b>) <b>1</b> <i>plural</i>. <b>rulers, judges</b>",
    }]), encoding="utf-8")
    (entry,) = parse_bdb_lexicon(path)
    assert entry["strongs"] == "H0430"
    assert entry["short_definition"] == "rulers, judges"


# ---------------------------------------------------------------------------
# update_brief_definitions and the repair script
# ---------------------------------------------------------------------------

TEGMC = """V-2ADS-3S\tFunction=Verb; Tense=2nd Aorist; Voice=Middle Deponent; Mood=Subjunctive; Person=3rd; Number=Singular
\tVerb 2nd Aorist Middle Deponent Subjunctive 3rd Singular
$
S-2PASM\tFunction=Possessive pronoun; Person=2nd Person; Case=Accusative; Number=Singular; Gender=Masculine
$
V-PMO-3P\t-1\tVerb\tPresent
S-2PASM\tKJV
"""
TEHMC = """Code\tExample in English\tMeaning
H:N-M\tman\tHebrew Noun (Masculine)
$
HVqp3ms\tFunction=Verb ; Stem=Qal (hence Action=Simple; Voice=Active); Form=Perfect (hence Tense=Past/present; Mood=Indicative); Person=Third; Gender=Masculine; Number=Singular
"""

# What the old importers stored: BDB's first bold phrase, TFLSJ's last row,
# morphology columns read from the code.
OLD_LEXICON = [
    ("H0430", "hebrew", "אֱלֹהִים", "elohim", "elohim", "noun masculine plural", "BDB elohim", 2603),
    ("H4057", "hebrew", "מִדְבָּר", "midbar", "midbar", "mouth", "BDB midbar", 271),
    ("H7676", "hebrew", "שַׁבָּת", "shabbath", "shabbath", "masculine", "BDB shabbath", 111),
    ("G2424", "greek", "Ἰησοῦς", "Iēsous", "Iēsous", "Joshua", "**Ἰωσή**, see Ἰωσῆς, **Joses**", 917),
    ("G2570", "greek", "καλός", "kalos", "kalos", "Fair (Havens)", "**καλός** beautiful", 102),
]
OLD_MORPHOLOGY = [
    ("V-2ADS-3S", "greek", "Function=Verb; Tense=2nd Aorist; Voice=Middle Deponent; Mood=Subjunctive; "
     "Person=3rd; Number=Singular", "Verb", "3rd", "Singular", "", "Active", "", "", ""),
    ("S-2PASM", "greek", "KJV", "S", "", "", "", "", "", "", ""),
    ("V-PMO-3P", "greek", "-1", "Verb", "", "", "", "", "", "", ""),
    ("H:N-M", "hebrew", "man", "H", "", "", "", "", "", "", ""),
    ("HVqp3ms", "hebrew", "Function=Verb ; Stem=Qal (hence Action=Simple; Voice=Active); Form=Perfect "
     "(hence Tense=Past/present; Mood=Indicative); Person=Third; Gender=Masculine; Number=Singular",
     "H", "", "", "", "", "", "", ""),
]
WORDS = [
    {"word": "בַּמִּדְבָּר", "strongs": "H4057B"}, {"word": "בַּמִּדְבָּר", "strongs": "H4057B"},
    {"word": "מִדְבָּרֵךְ", "strongs": "H4057A"}, {"word": "אֱלֹהִים", "strongs": "H0430G"},
]


@pytest.fixture
def setup(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "TBESH.txt").write_text("\n".join(TBESH) + "\n", encoding="utf-8")
    (data_dir / "TBESG.txt").write_text("\n".join(TFLSJ) + "\n", encoding="utf-8")
    (data_dir / "TFLSJ_0-5624.txt").write_text("\n".join(TFLSJ) + "\n", encoding="utf-8")
    (data_dir / "DictBDB.json").write_text("[]", encoding="utf-8")
    (data_dir / "TEGMC.txt").write_text(TEGMC, encoding="utf-8")
    (data_dir / "TEHMC.txt").write_text(TEHMC, encoding="utf-8")

    db = tmp_path / "study_bible.db"
    conn = sqlite3.connect(db)
    create_schema(conn)
    conn.executemany(
        """INSERT INTO lexicon (strongs, language, word, transliteration, pronunciation,
               short_definition, full_definition, usage_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        OLD_LEXICON,
    )
    conn.executemany(
        """INSERT INTO morphology (code, language, parsing, part_of_speech, person, number,
               tense, voice, mood, case_value, gender) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        OLD_MORPHOLOGY,
    )
    conn.execute(
        "INSERT INTO verses (reference, book, chapter, verse, word_data) VALUES (?, ?, ?, ?, ?)",
        ("Num.1.1", "Num", 1, 1, json.dumps(WORDS, ensure_ascii=False)),
    )
    conn.commit()
    conn.close()
    return db, data_dir


def _lexicon(db: Path) -> dict[str, tuple]:
    conn = sqlite3.connect(db)
    rows = conn.execute(
        "SELECT strongs, word, pronunciation, short_definition, full_definition, usage_count "
        "FROM lexicon ORDER BY strongs"
    ).fetchall()
    conn.close()
    return {row[0]: row[1:] for row in rows}


def _morphology(db: Path) -> list[tuple]:
    conn = sqlite3.connect(db)
    rows = conn.execute(
        "SELECT code, parsing, part_of_speech, voice, case_value FROM morphology ORDER BY code"
    ).fetchall()
    conn.close()
    return rows


def _run(monkeypatch, *argv) -> int:
    monkeypatch.setattr("sys.argv", ["repair_lexicon_and_morphology.py", *map(str, argv)])
    return repair.main()


def test_update_brief_definitions_orders_senses_by_the_tagged_text(setup):
    db, data_dir = setup
    conn = sqlite3.connect(db)
    assert update_brief_definitions(conn, data_dir) == 5
    assert update_brief_definitions(conn, data_dir) == 0
    conn.close()
    lexicon = _lexicon(db)
    assert lexicon["H4057"][1:3] == ("mid.bar", "wilderness; mouth")
    assert lexicon["H0430"][1:3] == ("e.lo.him", "God")
    assert lexicon["G2570"][2] == "good"
    assert lexicon["H0430"][4] == 2603  # usage counts untouched


def test_repair_matches_a_fresh_import_and_is_idempotent(setup, monkeypatch, capsys):
    db, data_dir = setup
    assert _run(monkeypatch, db, "--data-dir", data_dir) == 0
    out = capsys.readouterr().out
    assert "5 lexicon rows to update; morphology 4 to update, 0 to insert, 1 to delete" in out
    lexicon = _lexicon(db)
    assert lexicon["H7676"][2] == "Sabbath"
    assert lexicon["G2424"] == ("Ἰησοῦς", "Iēsous", "Jesus; Joshua", "Jesus, Greek form of **Joshua**", 917)
    assert _morphology(db) == [
        ("H:N-M", "Hebrew Noun (Masculine)", "Hebrew Noun (Masculine)", "", ""),
        ("HVqp3ms", OLD_MORPHOLOGY[4][2], "Verb", "Active", ""),
        ("S-2PASM", "Function=Possessive pronoun; Person=2nd Person; Case=Accusative; "
         "Number=Singular; Gender=Masculine", "Possessive pronoun", "", "Accusative"),
        ("V-2ADS-3S", OLD_MORPHOLOGY[0][2], "Verb", "Middle Deponent", ""),
    ]

    assert _run(monkeypatch, db, "--data-dir", data_dir) == 0
    assert "0 lexicon, 0 morphology update, 0 morphology insert, 0 morphology delete" in (
        capsys.readouterr().out
    )


def test_patch_repairs_a_copy_with_the_standard_library_only(setup, monkeypatch, tmp_path):
    db, data_dir = setup
    copy = tmp_path / "copy.db"
    shutil.copy(db, copy)
    patch = tmp_path / "lexicon.patch.gz"
    assert _run(monkeypatch, db, "--data-dir", data_dir, "--write-patch", patch) == 0
    with gzip.open(patch, "rt", encoding="utf-8") as handle:
        assert json.load(handle)["lexicon"]["H0430"] == {
            "short_definition": ["noun masculine plural", "God"],
            "pronunciation": ["elohim", "e.lo.him"],
        }

    server = tmp_path / "server"
    server.mkdir()
    script = shutil.copy(Path(repair.__file__), server / "repair_lexicon_and_morphology.py")
    for _ in range(2):  # the second run is a no-op
        result = subprocess.run(
            [sys.executable, "-I", "-S", script, copy, "--apply-patch", patch],
            capture_output=True, text=True, cwd=server,
        )
        assert result.returncode == 0, result.stderr
    assert _lexicon(copy) == _lexicon(db)
    assert _morphology(copy) == _morphology(db)


def test_a_row_holding_unexpected_values_stops_the_whole_repair(setup, monkeypatch, tmp_path):
    db, data_dir = setup
    patch = tmp_path / "lexicon.patch.gz"
    copy = tmp_path / "copy.db"
    shutil.copy(db, copy)
    assert _run(monkeypatch, db, "--data-dir", data_dir, "--write-patch", patch) == 0

    conn = sqlite3.connect(copy)
    conn.execute("UPDATE lexicon SET short_definition = 'edited' WHERE strongs = 'H7676'")
    conn.commit()
    conn.close()
    before = (_lexicon(copy), _morphology(copy))
    assert _run(monkeypatch, copy, "--apply-patch", patch) == 1
    assert (_lexicon(copy), _morphology(copy)) == before
