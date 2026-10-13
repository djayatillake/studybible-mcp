import hashlib
import importlib.util
import io
import json
import sqlite3
import zipfile
import zlib
from pathlib import Path

import httpx
import pytest

from study_bible_mcp import server
from study_bible_mcp.parsers import biblical_versions as biblical_versions_module
from study_bible_mcp.database import StudyBibleDB, create_schema, parse_passage_reference
from study_bible_mcp.parsers.biblical_versions import (
    BRENTON_BOOK_CODES,
    APOCRYPHA_BOOK_NAMES,
    BRENTON_TRANSLATION_NOTE,
    KJV_APOCRYPHA_NOTE,
    KJV_APOCRYPHA_TRANSLATION_LABEL,
    LXX_BOOK_CODES,
    LXX_TRANSLATION_LABEL,
    MT_BOOK_CODES,
    LXX_SOURCE_BOOKS,
    REQUIRED_BRENTON_BOOKS,
    REQUIRED_BRENTON_GREEK_BOOKS,
    apocrypha_name,
    compare_brenton_greek,
    expand_lxx_morphology,
    import_biblical_versions,
    iter_lxx_rows,
    normalize_greek_text,
    parse_brenton_usfm,
)
from study_bible_mcp.tools import format_biblical_version_comparison


PROVENANCE_FIELDS = {
    "version",
    "edition",
    "language",
    "canonical_reference",
    "edition_reference",
    "text",
    "translation",
    "license",
    "source_url",
}
LXX_ROW_FIELDS = (
    "edition", "canonical_reference", "canonical_book", "canonical_chapter",
    "canonical_verse", "canonical_verse_suffix", "edition_reference", "edition_book",
    "edition_chapter", "edition_verse", "edition_verse_suffix", "text", "translation",
    "morphology", "mapping_method", "brenton_greek_differs", "brenton_greek",
    "brenton_greek_difference",
)


def _word(surface, lemma="", parsing="", pos=""):
    return {
        "surface": surface, "lemma": lemma, "parsing": parsing, "pos": pos,
        "confidence": "high", "source": "morpheus", "reasoning": "unused",
    }


def _words(text):
    return [_word(token) for token in text.split()]


def _pair(slug, grk_ref, mt_book, mt_ref, method="tvtms"):
    return {"grk_book": slug, "grk_ref": grk_ref, "mt_book": mt_book, "mt_refs": [mt_ref], "method": method}


def _unpaired(slug, grk_ref):
    return {"grk_book": slug, "grk_ref": grk_ref, "method": "unpaired", "reason": "no-hebrew-counterpart"}


LXX_FIXTURE = {
    "psalms-lxx": [
        ("Ps 8:6", "ἠλάττωσας αὐτὸν βραχύ τι παρ᾿ ἀγγέλους"),
        ("Ps 39:7", "θυσίαν καὶ προσφορὰν οὐκ ἠθέλησας ὠτία δὲ κατηρτίσω μοι"),
        ("Ps 80:7", "ἀπέστησεν ἀπὸ ἄρσεων τὸν νῶτον αὐτοῦ"),
        ("Ps 81:1", "ψαλμὸς τῷ Ασαφ ὁ θεὸς ἔστη ἐν συναγωγῇ θεῶν"),
        ("Ps 81:6", "ἐγὼ εἶπα θεοί ἐστε καὶ υἱοὶ ὑψίστου πάντες"),
    ],
    "deuteronomy": [(
        "Deut 32:43",
        "προσκυνησάτωσαν αὐτῷ πάντες υἱοὶ θεοῦ καὶ ἐνισχυσάτωσαν αὐτῷ πάντες ἄγγελοι θεοῦ",
    )],
    "daniel": [
        ("Dan 3:25", "στὰς δὲ Αζαριας προσηύξατο"),
        ("Dan 3:92", "ἡ ὅρασις τοῦ τετάρτου ὁμοίωμα ἀγγέλου θεοῦ"),
    ],
    "daniel-theodotion": [
        ("Dan 3:25", "καὶ συστὰς Αζαριας προσηύξατο"),
        ("Dan 3:92", "ἡ ὅρασις τοῦ τετάρτου ὁμοία υἱῷ θεοῦ"),
    ],
    "tobit": [("Tob 1:1", "βίβλος λόγων Τωβιθ")],
}
PAIRS = [
    _pair("psalms-lxx", "8:6", "psalms", "8:5"),
    _pair("psalms-lxx", "39:7", "psalms", "40:6"),
    _pair("psalms-lxx", "80:7", "psalms", "81:6"),
    _pair("psalms-lxx", "81:1", "psalms", "82:1"),
    _pair("psalms-lxx", "81:6", "psalms", "82:6"),
    _pair("deuteronomy", "32:43", "deuteronomy", "32:43", method="identity"),
    _unpaired("daniel", "3:25"),
    _pair("daniel", "3:92", "daniel", "3:25"),
    _unpaired("daniel-theodotion", "3:25"),
    _pair("daniel-theodotion", "3:92", "daniel", "3:25"),
]
BRENTON_FIXTURE = {
    "PSA": (
        "\\c 39\n\\v 7 Sacrifice and offering thou wouldest not; but a body hast thou prepared me\n"
        "\\c 81\n\\v 6 I said, Ye are gods; and all \\add of you\\add* children of the most High.\n"
    ),
    "DEU": (
        "\\c 32\n\\v 43 and let all the angels of God worship him, "
        "and let all the sons of God strengthen themselves in him\n"
    ),
    "DAG": (
        "\\c 3\n\\v 25 Then Azarias stood up, and prayed on this manner;\n"
        "\\v 92 and the appearance of the fourth is like the Son of God.\n"
    ),
    "TOB": "\\c 1\n\\v 1 The book of the words of Tobit.\n",
}
# Brenton's own Greek: Psalm 81:6 and Daniel 3:92 differ from Rahlfs only in
# spelling and punctuation; Psalm 39:7 and Deuteronomy 32:43 differ in text.
# Tobit 1:1 and Daniel 3:25 have English but no Greek verse.
BRENTON_GREEK_FIXTURE = {
    "PSA": (
        "\\c 39\n\\v 7 Θυσίαν καὶ προσφορὰν οὐκ ἠθέλησας, σῶμα δὲ κατηρτίσω μοι·\n"
        "\\c 81\n\\v 6 Ἐγὼ εἶπα, θεοί ἐστε, καὶ υἱοὶ Ὑψίστου πάντες.\n"
    ),
    "DEU": (
        "\\c 32\n\\v 43 προσκυνησάτωσαν αὐτῷ πάντες ἄγγελοι Θεοῦ, "
        "καὶ ἐνισχυσάτωσαν αὐτῷ πάντες υἱοὶ Θεοῦ.\n"
    ),
    "DAG": "\\c 3\n\\v 92 Ἡ ὅρασις τοῦ τετάρτου ὁμοία υἱῷ Θεοῦ.\n",
}
MT_FIXTURE = [
    ("Psa.8.5(8.6)", "Psa", 8, 5, "and/ you have made lack/ him", "וַתְּחַסְּרֵהוּ"),
    ("Psa.40.6(40.7)", "Psa", 40, 6, "sacrifice and/ offering", "זֶבַח וּמִנְחָה"),
    ("Psa.81.6(81.7)", "Psa", 81, 6, "I removed from burden", "הֲסִירוֹתִי"),
    ("Psa.82.1", "Psa", 82, 1, "God [is] standing", "אֱלֹהִים נִצָּב"),
    ("Psa.82.6", "Psa", 82, 6, "I I said gods you", "אֲנִי אָמַרְתִּי"),
    ("Dan.3.25", "Dan", 3, 25, "he answered and/ said", "עָנֵה וְאָמַר"),
    ("Luk.4.9", "Luk", 4, 9, "And he led him", "Ἤγαγεν δὲ αὐτὸν"),
]


def _write_lxx_sources(data_dir: Path) -> Path:
    lxx_dir = data_dir / "lxx"
    morphology_dir = lxx_dir / "morphology"
    morphology_dir.mkdir(parents=True)
    for slug in LXX_SOURCE_BOOKS:
        verses = [{"ref": ref, "words": _words(text)} for ref, text in LXX_FIXTURE.get(slug, [])]
        (morphology_dir / f"{slug}.json").write_text(json.dumps(verses), encoding="utf-8")
    (lxx_dir / "verse_pairs.jsonl").write_text(
        "".join(json.dumps(pair) + "\n" for pair in PAIRS), encoding="utf-8"
    )
    brenton_dir = lxx_dir / "brenton"
    brenton_dir.mkdir()
    for code in REQUIRED_BRENTON_BOOKS:
        (brenton_dir / f"{code}eng-Brenton.usfm").write_text(
            f"\\id {code}\n{BRENTON_FIXTURE.get(code, '')}", encoding="utf-8"
        )
    greek_dir = lxx_dir / "brenton-greek"
    greek_dir.mkdir()
    for code in REQUIRED_BRENTON_GREEK_BOOKS:
        (greek_dir / f"{code}grcbrent.usfm").write_text(
            f"\\id {code} - Brenton Greek Text\n{BRENTON_GREEK_FIXTURE.get(code, '')}", encoding="utf-8"
        )
    return lxx_dir


def _build_db(tmp_path: Path, import_lxx: bool = True) -> Path:
    db_path = tmp_path / "versions.db"
    conn = sqlite3.connect(db_path)
    create_schema(conn)
    conn.executemany(
        """INSERT INTO verses (reference, book, chapter, verse, text_english, text_original, word_data)
           VALUES (?, ?, ?, ?, ?, ?, '[]')""",
        MT_FIXTURE,
    )
    conn.commit()
    if import_lxx:
        _write_lxx_sources(tmp_path / "data")
        import_biblical_versions(conn, tmp_path / "data")
    conn.close()
    return db_path


async def _compare(db_path: Path, reference: str, versions=("MT", "LXX"), numbering="canonical") -> dict:
    database = StudyBibleDB(db_path)
    await database.connect()
    try:
        return await database.compare_biblical_versions(reference, list(versions), numbering)
    finally:
        await database.close()


def test_all_pinned_lxx_books_have_canonical_codes():
    assert len(LXX_SOURCE_BOOKS) == 59
    assert LXX_SOURCE_BOOKS <= LXX_BOOK_CODES.keys()


def test_lxx_psalm_numbering_uses_explicit_mapping(tmp_path):
    morphology_dir = tmp_path / "morphology"
    morphology_dir.mkdir()
    (morphology_dir / "psalms-lxx.json").write_text(
        json.dumps([{
            "ref": "Ps 23:1",
            "words": [_word("τοῦ", "ὁ", "masc gen sg", "article"), _word("κυρίου", "κύριος", "masc gen sg", "noun")],
        }]),
        encoding="utf-8",
    )
    pairings = {("psalms-lxx", "23:1"): [_pair("psalms-lxx", "23:1", "psalms", "24:1")]}

    row = dict(zip(LXX_ROW_FIELDS, next(iter_lxx_rows(
        morphology_dir, pairings, {("PSA", "23:1"): "The earth is the Lord's."}, {}
    ))))

    assert row["canonical_reference"] == "Psa.24.1"
    assert row["edition_reference"] == "Psa.23.1"
    assert row["translation"] == "The earth is the Lord's."
    assert row["mapping_method"] == "tvtms"
    assert json.loads(zlib.decompress(row["morphology"]))[1] == [
        "κυρίου", "κύριος", "masc gen sg", "noun", "high", "morpheus",
    ]
    assert expand_lxx_morphology(row["morphology"])[1] == {
        "surface": "κυρίου", "lemma": "κύριος", "parsing": "masc gen sg", "pos": "noun",
        "confidence": "high", "source": "morpheus",
    }


def test_brenton_markers_keep_word_spacing(tmp_path):
    (tmp_path / "test.usfm").write_text(
        "\\id GEN\n\\c 1\n"
        "\\v 1 In \\add the\\add* beginning \\sc God\\sc* made\\f + \\fr 1:1 \\ft Or, formed.\\f* the heaven.\n"
        "\\v 2 But the earth was \\x - \\xo 1:2 \\xt Jer 4.23\\x*unsightly and \\add unfurnished\\add*, and darkness.\n"
        "\\c 81\n\\v 6 and all \\add of you\\add* children of the most High.\n",
        encoding="utf-8",
    )

    translations = parse_brenton_usfm(tmp_path)

    assert translations[("GEN", "1:1")] == "In the beginning God made the heaven."
    assert translations[("GEN", "1:2")] == "But the earth was unsightly and unfurnished, and darkness."
    assert translations[("GEN", "81:6")] == "and all of you children of the most High."


def test_brenton_is_attached_only_to_its_own_recension(tmp_path):
    morphology_dir = tmp_path / "morphology"
    morphology_dir.mkdir()
    for slug in ("daniel", "daniel-theodotion"):
        verses = [{"ref": ref, "words": _words(text)} for ref, text in LXX_FIXTURE[slug]]
        (morphology_dir / f"{slug}.json").write_text(json.dumps(verses), encoding="utf-8")
    pairings = {}
    for pair in PAIRS:
        pairings.setdefault((pair["grk_book"], pair["grk_ref"]), []).append(pair)

    rows = [dict(zip(LXX_ROW_FIELDS, row)) for row in iter_lxx_rows(
        morphology_dir, pairings, {("DAG", "3:92"): "like the Son of God."}, {}
    )]
    by_edition = {(row["edition"], row["edition_reference"]): row for row in rows}

    assert by_edition[("Rahlfs Septuagint (1935), Theodotion", "Dan.3.92")]["translation"] == "like the Son of God."
    assert by_edition[("Rahlfs Septuagint (1935), Old Greek", "Dan.3.92")]["translation"] is None
    assert BRENTON_BOOK_CODES["daniel-theodotion"] == "DAG"
    assert BRENTON_BOOK_CODES["susanna-theodotion"] == "SUS"
    assert BRENTON_BOOK_CODES["bel-and-the-dragon-theodotion"] == "BEL"
    assert BRENTON_BOOK_CODES["judges-vaticanus-b"] == "JDG"
    assert BRENTON_BOOK_CODES["joshua-vaticanus-b"] == "JOS"
    for slug in ("daniel", "susanna", "bel-and-the-dragon", "judges", "joshua"):
        assert slug not in BRENTON_BOOK_CODES


def test_unpaired_lxx_verses_get_no_canonical_position(tmp_path):
    morphology_dir = tmp_path / "morphology"
    morphology_dir.mkdir()
    (morphology_dir / "daniel.json").write_text(
        json.dumps([{"ref": "Dan 3:25", "words": _words("στὰς δὲ Αζαριας")}]), encoding="utf-8"
    )

    row = dict(zip(LXX_ROW_FIELDS, next(iter_lxx_rows(
        morphology_dir, {("daniel", "3:25"): [_unpaired("daniel", "3:25")]}, {}, {}
    ))))

    assert row["canonical_reference"] is None
    assert row["canonical_book"] is None
    assert row["edition_reference"] == "Dan.3.25"
    assert row["mapping_method"] == "unpaired (no-hebrew-counterpart)"


async def test_import_stores_only_lxx_rows_and_is_idempotent(tmp_path):
    db_path = _build_db(tmp_path)
    conn = sqlite3.connect(db_path)
    try:
        first = import_biblical_versions(conn, tmp_path / "data")
        second = import_biblical_versions(conn, tmp_path / "data")
        stored = conn.execute("SELECT COUNT(*) FROM biblical_version_verses").fetchone()[0]
    finally:
        conn.close()

    assert first == second == (6, 11)
    assert stored == 11


@pytest.mark.parametrize(("reference", "mt_edition", "lxx_edition"), [
    ("Psalm 40:6", "Psa.40.7", "Psa.39.7"),
    ("Psalm 8:5", "Psa.8.6", "Psa.8.6"),
    ("Psalm 82:6", "Psa.82.6", "Psa.81.6"),
])
async def test_mt_and_lxx_share_one_canonical_header(tmp_path, reference, mt_edition, lxx_edition):
    db_path = _build_db(tmp_path)

    result = await _compare(db_path, reference)
    rows = result["rows"]
    output = format_biblical_version_comparison(reference, rows)

    assert result["status"] == "ok"
    assert [row["version"] for row in rows] == ["MT", "LXX"]
    assert all(PROVENANCE_FIELDS <= row.keys() for row in rows)
    assert len({row["canonical_reference"] for row in rows}) == 1
    assert [row["edition_reference"] for row in rows] == [mt_edition, lxx_edition]
    assert output.count("\n### ") == 1
    assert "STEPBible word glosses (interlinear, not a translation)" in output
    shifted = mt_edition != rows[0]["canonical_reference"]
    assert ("TAHOT English/Hebrew versification" in output) == shifted


async def test_comparison_shows_spaced_brenton_text(tmp_path):
    db_path = _build_db(tmp_path)

    result = await _compare(db_path, "Psalm 82:6", ["LXX"])

    assert result["rows"][0]["translation"] == "I said, Ye are gods; and all of you children of the most High."
    output = format_biblical_version_comparison("Psalm 82:6", result["rows"], include_morphology=True)
    assert "- **ἐγὼ**" in output


async def test_unpaired_lxx_verses_are_not_mt_counterparts(tmp_path):
    db_path = _build_db(tmp_path)

    canonical = await _compare(db_path, "Daniel 3:25")
    greek = await _compare(db_path, "Daniel 3:25", numbering="lxx")
    output = format_biblical_version_comparison("Daniel 3:25", canonical["rows"])

    assert [(row["version"], row["edition_reference"]) for row in canonical["rows"]] == [
        ("MT", "Dan.3.25"), ("LXX", "Dan.3.92"), ("LXX", "Dan.3.92"),
    ]
    assert "Αζαριας" not in output
    assert "Azarias" not in output
    assert "**English:** not available for this edition." in output
    assert "like the Son of God." in output
    assert [row["edition_reference"] for row in canonical["lxx_only"]] == ["Dan.3.25", "Dan.3.25"]
    assert [row["canonical_reference"] for row in greek["rows"]] == [None, None]
    assert "LXX-only, no MT counterpart" in format_biblical_version_comparison(
        "Daniel 3:25", greek["rows"], numbering="lxx"
    )


@pytest.mark.parametrize(("reference", "expected"), [
    ("Psalm 81:6-82:1", ["Psa.81.6", "Psa.81.6", "Psa.82.1", "Psa.82.1"]),
    ("Psalm 81:6–82:1", ["Psa.81.6", "Psa.81.6", "Psa.82.1", "Psa.82.1"]),
    ("Psalm 82", ["Psa.82.1", "Psa.82.1", "Psa.82.6", "Psa.82.6"]),
    ("Psalm 82:1-8", ["Psa.82.1", "Psa.82.1", "Psa.82.6", "Psa.82.6"]),
    ("Ps82:6", ["Psa.82.6", "Psa.82.6"]),
])
async def test_comparison_reference_forms(tmp_path, reference, expected):
    db_path = _build_db(tmp_path)

    result = await _compare(db_path, reference)

    assert result["status"] == "ok"
    assert [row["canonical_reference"] for row in result["rows"]] == expected


@pytest.mark.parametrize(("reference", "status"), [
    ("Luke 4:9", "new_testament"),
    ("Psalm eighty-two", "invalid_reference"),
    ("Psalm 82:8-1", "invalid_reference"),
    ("Hezekiah 1:1", "unsupported_book"),
    ("Psalm 24:1a", "no_match"),
    ("Psalm 30:1", "no_match"),
])
async def test_comparison_reports_why_nothing_matched(tmp_path, reference, status):
    db_path = _build_db(tmp_path)

    assert (await _compare(db_path, reference))["status"] == status


async def test_lxx_only_books_use_edition_numbering(tmp_path):
    db_path = _build_db(tmp_path)

    result = await _compare(db_path, "Tobit 1:1")

    assert result["numbering"] == "lxx"
    assert [(row["version"], row["edition_reference"]) for row in result["rows"]] == [("LXX", "Tob.1.1")]
    assert result["rows"][0]["translation"] == "The book of the words of Tobit."


async def test_missing_lxx_table_is_reported_but_mt_still_works(tmp_path):
    db_path = _build_db(tmp_path, import_lxx=False)

    assert (await _compare(db_path, "Psalm 82:6"))["status"] == "missing_data"
    mt_only = await _compare(db_path, "Psalm 82:6", ["MT"])
    assert [row["edition_reference"] for row in mt_only["rows"]] == ["Psa.82.6"]


@pytest.mark.parametrize(("reference", "versions", "expected", "absent"), [
    ("Luke 4:9", ["MT", "LXX"], "Old Testament and Septuagint books only", "download"),
    ("Psalm eighty-two", ["MT", "LXX"], "Could not parse", "download"),
    ("Psalm 30:1", ["MT", "LXX"], "No MT or LXX text found for Psalm 30:1", "download"),
    ("Daniel 3:25", ["LXX"], "numbering='lxx'", "Αζαριας"),
])
async def test_handler_messages(tmp_path, monkeypatch, reference, versions, expected, absent):
    database = StudyBibleDB(_build_db(tmp_path))
    await database.connect()
    monkeypatch.setattr(server, "db", database)
    try:
        response = await server.handle_compare_biblical_versions(
            {"reference": reference, "versions": versions}
        )
    finally:
        await database.close()

    assert expected in response[0].text
    assert absent not in response[0].text


async def test_handler_suggests_upgrade_when_table_is_empty(tmp_path, monkeypatch):
    database = StudyBibleDB(_build_db(tmp_path, import_lxx=False))
    await database.connect()
    monkeypatch.setattr(server, "db", database)
    try:
        response = await server.handle_compare_biblical_versions({"reference": "Psalm 82:6"})
    finally:
        await database.close()

    assert "python scripts/upgrade_database.py" in response[0].text
    assert "download" not in response[0].text


@pytest.mark.parametrize("missing", ["morphology/sirach.json", "brenton-greek/DEUgrcbrent.usfm"])
def test_partial_lxx_download_fails_loudly(tmp_path, missing):
    lxx_dir = _write_lxx_sources(tmp_path / "data")
    (lxx_dir / missing).unlink()
    conn = sqlite3.connect(":memory:")
    create_schema(conn)

    expected = "brenton-greek/\\*DEU\\*.usfm" if missing.startswith("brenton-greek") else missing
    with pytest.raises(FileNotFoundError, match=expected):
        import_biblical_versions(conn, tmp_path / "data")


def _brenton_difference(rahlfs: str, brenton: str, rahlfs_words=frozenset()):
    return compare_brenton_greek(("", rahlfs, ""), ("", brenton, ""), frozenset(rahlfs_words))


@pytest.mark.parametrize(("rahlfs", "brenton"), [
    ("καὶ ἐλάλησεν κύριος πρὸς Μωυσῆν", "Καὶ ἐλάλησε Κύριος πρὸς Μωυσῆν,"),  # movable nu, case
    ("ἐπ᾿ αὐτούς ἀπ᾿ ἐμοῦ", "ἐπʼ αὐτοὺς, ἀπὸ ἐμοῦ·"),  # elision marks, elided vs full
    ("τοῦτό ἐστιν πᾶσιν", "τοῦτʼ ἐστὶ πᾶσι."),  # elided pronoun, movable nu
    ("λήμψεται οὕτως Ιωακιμ", "λήψεται οὕτω Ἰωακείμ"),  # Hellenistic μψ, movable ς, itacism
    ("κἀγὼ συνπορεύσομαι ἐξ αὐτῶν", "καὶ ἐγὼ συμπορεύσομαι ἐκ αὐτῶν"),  # crasis, assimilation
    ("ἀνὰ μέσον ἐπὶ τὸ αὐτό", "ἀναμέσον ἐπιτοαυτό"),  # word division
    ("εἶπαν ἐξολεθρεῦσαι γενήματα", "εἶπον ἐξολοθρεῦσαι γεννήματα"),  # aorist ending, spelling
    ("ἐν Βαιθλεεμ τῷ Βοος", "ἐν Βηθλεὲμ τῷ Βοόζ"),  # proper names
    ("ΑΛΕΦ. πῶς ἐκάθισεν μόνη", "ΑΛΕΦ. Πῶς ἐκάθισε μόνη"),  # acrostic heading on both sides
    ("πῶς ἐκάθισεν μόνη", "ΑΛΕΦ. Πῶς ἐκάθισε μόνη"),  # Brenton's acrostic heading
    ("οἱ υἱοὶ αὐτοῦ", "οἱ γἱοὶ αὐτοῦ"),  # keyed γ for υ
])
def test_orthographic_variants_do_not_flag(rahlfs, brenton):
    assert _brenton_difference(rahlfs, brenton) is None


def test_normalization_keeps_real_word_differences():
    assert normalize_greek_text("ἓξ ἡμέρας") != normalize_greek_text("ἐκ ἡμέρας")
    assert normalize_greek_text("ὑμῶν") != normalize_greek_text("ἡμῶν")
    assert normalize_greek_text("Καὶ ἐλάλησε") == normalize_greek_text("καὶ ἐλάλησεν")


def test_reordered_words_are_reported_as_word_order():
    brenton = "προσκυνησάτωσαν αὐτῷ πάντες ἄγγελοι Θεοῦ, καὶ ἐνισχυσάτωσαν αὐτῷ πάντες υἱοὶ Θεοῦ."

    brenton_text, summary = _brenton_difference(
        "προσκυνησάτωσαν αὐτῷ πάντες υἱοὶ θεοῦ καὶ ἐνισχυσάτωσαν αὐτῷ πάντες ἄγγελοι θεοῦ", brenton
    )

    assert summary == "word order differs (υἱοὶ ἄγγελοι)"
    assert brenton_text == brenton


@pytest.mark.parametrize(("rahlfs", "brenton", "summary"), [
    ("ὠτία δὲ κατηρτίσω μοι", "σῶμα δὲ κατηρτίσω μοι", "Brenton's Greek reads σῶμα for ὠτία"),
    ("καὶ εἶπεν αὐτῷ", "καὶ εἶπεν αὐτῷ Κύριος,", "Brenton's Greek adds: Κύριος"),
    ("καὶ εἶπεν αὐτῷ κύριος", "καὶ εἶπεν αὐτῷ.", "Brenton's Greek lacks: κύριος"),
    ("ἐν τῷ οἴκῳ ὑμῶν", "ἐν τῷ οἴκῳ ἡμῶν", "Brenton's Greek reads ἡμῶν for ὑμῶν"),
])
def test_substitutions_additions_and_omissions_are_summarized(rahlfs, brenton, summary):
    assert _brenton_difference(rahlfs, brenton, normalize_greek_text("ὑμῶν ἡμῶν")) == (brenton, summary)


def test_keying_error_is_ignored_only_when_unknown_to_rahlfs():
    rahlfs, brenton = "τοῦ σπέρματός σου", "τοῦ σηέρματός σου"

    assert _brenton_difference(rahlfs, brenton, normalize_greek_text(rahlfs)) is None
    assert _brenton_difference(rahlfs, brenton, normalize_greek_text(f"{rahlfs} σηέρματος")) == (
        brenton, "Brenton's Greek reads σηέρματός for σπέρματός"
    )


def test_verse_division_differences_do_not_flag():
    rahlfs_2, rahlfs_3 = "ἕνδεκα ἡμερῶν ἐν Χωρηβ ὁδὸς ἐπ᾿ ὄρος Σηιρ ἕως Καδης Βαρνη", "καὶ ἐγενήθη ἐν τῷ ἔτει"
    # Brenton's Greek moves "Σηεὶρ ἕως Κάδης Βαρνή" into the next verse.
    brenton_2, brenton_3 = "Ἕνδεκα ἡμερῶν ἐν Χωρὴβ ὁδὸς ἐπʼ ὄρος", "Σηεὶρ ἕως Κάδης Βαρνή. Καὶ ἐγενήθη ἐν τῷ ἔτει"

    assert compare_brenton_greek(("", rahlfs_2, rahlfs_3), ("", brenton_2, brenton_3)) is None
    assert compare_brenton_greek((rahlfs_2, rahlfs_3, ""), (brenton_2, brenton_3, "")) is None
    # A real difference is still reported, with Brenton's Greek aligned to the Rahlfs verse.
    changed_2 = "Ἕνδεκα ἡμερῶν ἐκ Χωρὴβ ὁδὸς ἐπʼ ὄρος"
    assert compare_brenton_greek(("", rahlfs_2, rahlfs_3), ("", changed_2, brenton_3)) == (
        "Ἕνδεκα ἡμερῶν ἐκ Χωρὴβ ὁδὸς ἐπʼ ὄρος Σηεὶρ ἕως Κάδης Βαρνή.",
        "Brenton's Greek reads ἐκ for ἐν",
    )


async def test_flagged_row_shows_warning_and_brentons_greek(tmp_path):
    db_path = _build_db(tmp_path)

    result = await _compare(db_path, "Deuteronomy 32:43", ["LXX"])
    row = result["rows"][0]
    output = format_biblical_version_comparison("Deuteronomy 32:43", result["rows"])

    assert row["brenton_greek_differs"] == 1
    assert row["brenton_greek_difference"] == "word order differs (υἱοὶ ἄγγελοι)"
    assert row["brenton_greek"].index("ἄγγελοι") < row["brenton_greek"].index("υἱοὶ")
    assert "**Warning: Brenton's English below translates a different Greek text.**" in output
    assert "word order differs (υἱοὶ ἄγγελοι)" in output
    assert (
        "**Brenton's Greek (the text his English translates):** "
        "προσκυνησάτωσαν αὐτῷ πάντες ἄγγελοι Θεοῦ" in output
    )
    assert output.count(BRENTON_TRANSLATION_NOTE) == 1
    assert f"*Brenton's English: {BRENTON_TRANSLATION_NOTE}*" in output
    assert output.index("Warning") < output.index("**English") < output.index("*Brenton's English:")
    without_greek = format_biblical_version_comparison(
        "Deuteronomy 32:43", result["rows"], include_original=False
    )
    assert "Warning" in without_greek and "Brenton's Greek (the text" not in without_greek


async def test_psalm_40_6_flags_body_for_ears(tmp_path):
    result = await _compare(_build_db(tmp_path), "Psalm 40:6", ["LXX"])

    assert result["rows"][0]["brenton_greek_difference"] == "Brenton's Greek reads σῶμα for ὠτία"


async def test_matching_greek_shows_only_the_standing_note(tmp_path):
    db_path = _build_db(tmp_path)

    result = await _compare(db_path, "Psalm 82:6", ["LXX"])
    row = result["rows"][0]
    output = format_biblical_version_comparison("Psalm 82:6", result["rows"])

    assert row["brenton_greek_differs"] == 0
    assert "brenton_greek" not in row and "brenton_greek_difference" not in row
    assert "Warning" not in output and "Brenton's Greek (the text" not in output
    assert output.count(BRENTON_TRANSLATION_NOTE) == 1
    assert f"*Brenton's English: {BRENTON_TRANSLATION_NOTE}*" in output
    assert "Apocrypha" not in output and "apocrypha" not in row


async def test_rows_without_brenton_english_are_unchanged(tmp_path):
    result = await _compare(_build_db(tmp_path), "Daniel 3:25", ["LXX"])
    old_greek, theodotion = result["rows"]

    assert old_greek["translation"] is None and old_greek["brenton_greek_differs"] is None
    assert "translation_note" not in old_greek
    output = format_biblical_version_comparison("Daniel 3:25", [old_greek])
    assert "Note:" not in output and "Warning" not in output
    assert theodotion["brenton_greek_differs"] == 0


async def test_english_without_brenton_greek_says_it_was_not_compared(tmp_path, monkeypatch):
    # Tobit is a KJV Apocrypha book; treat it as Brenton's own here to reach this path.
    monkeypatch.setattr(biblical_versions_module, "KJV_APOCRYPHA_BOOKS", frozenset())
    result = await _compare(_build_db(tmp_path), "Tobit 1:1")
    output = format_biblical_version_comparison("Tobit 1:1", result["rows"], numbering="lxx")

    assert result["rows"][0]["brenton_greek_differs"] is None
    assert "Brenton's Greek for this verse is unavailable, so it was not compared." in output
    assert "Warning" not in output


async def test_kjv_apocrypha_english_is_labelled_with_one_closing_note(tmp_path):
    result = await _compare(_build_db(tmp_path), "Tobit 1:1")
    row = result["rows"][0]
    output = format_biblical_version_comparison("Tobit 1:1", result["rows"], numbering="lxx")

    assert row["kjv_apocrypha"] is True
    assert "brenton_greek_differs" not in row and "brenton_greek" not in row
    assert "#### LXX Rahlfs Septuagint (1935) · Tob.1.1 (mapping: lxx-only) (Apocrypha)" in output
    assert "**English (KJV Apocrypha):** The book of the words of Tobit." in output
    assert "Warning" not in output and "1611" not in output
    assert f"English: {KJV_APOCRYPHA_TRANSLATION_LABEL}." in output  # Sources block
    assert output.count(KJV_APOCRYPHA_NOTE) == 1
    assert output.endswith(f"*KJV Apocrypha English: {KJV_APOCRYPHA_NOTE}*")
    assert (
        "*Apocrypha: Tobit is not in the Protestant canon "
        "(cf. Westminster Confession 1.3); background only.*"
    ) in output
    assert "Brenton's English:" not in output and "English (Brenton)" not in output
    assert "Brenton's Greek (the text" not in output and "not compared" not in output
    assert output.index("**Sources**") < output.index("*Apocrypha:")


async def test_daniel_3_24_to_90_is_kjv_apocrypha(tmp_path):
    result = await _compare(_build_db(tmp_path), "Daniel 3:25", numbering="lxx")
    old_greek, theodotion = result["rows"]
    output = format_biblical_version_comparison("Daniel 3:25", result["rows"], numbering="lxx")

    assert theodotion["kjv_apocrypha"] is True and "kjv_apocrypha" not in old_greek
    assert "brenton_greek_differs" not in theodotion
    assert old_greek["apocrypha"] == theodotion["apocrypha"]
    assert output.count(" (Apocrypha)\n") == 2
    assert "**English (KJV Apocrypha):** Then Azarias stood up" in output
    assert "*Apocrypha: the Prayer of Azariah and Song of the Three (Dan 3:24–90) are not" in output
    assert "Brenton's English:" not in output and "not compared" not in output


async def test_mixed_kjv_and_brenton_rows_list_both_english_labels(tmp_path):
    # Greek numbering: Daniel 3:25 (Theodotion, KJV) and 3:92 (= MT 3:25, Brenton's own).
    result = await _compare(_build_db(tmp_path), "Daniel 3:25-92", numbering="lxx")
    output = format_biblical_version_comparison("Daniel 3:25-92", result["rows"], numbering="lxx")
    sources = output[output.index("**Sources**"):]

    assert [row["edition_reference"] for row in result["rows"]] == [
        "Dan.3.25", "Dan.3.25", "Dan.3.25", "Dan.3.92", "Dan.3.92",
    ]
    assert "**English (KJV Apocrypha):** Then Azarias" in output
    assert "**English (Brenton):** and the appearance of the fourth" in output
    assert (
        f"Theodotion (Greek): {result['rows'][-1]['license']}. "
        f"English: {KJV_APOCRYPHA_TRANSLATION_LABEL}; {LXX_TRANSLATION_LABEL}."
    ) in sources
    assert "Old Greek (Greek): " in sources and "English: none." in sources
    assert output.count(KJV_APOCRYPHA_NOTE) == output.count(BRENTON_TRANSLATION_NOTE) == 1
    assert output.count(" (Apocrypha)\n") == 2 and output.count("*Apocrypha:") == 1
    assert "Dan.3.92 (mapping: tvtms) (Apocrypha)" not in output


def test_kjv_apocrypha_range_in_daniel_is_not_compared_at_import(tmp_path):
    morphology_dir = tmp_path / "morphology"
    morphology_dir.mkdir()
    verses = [
        ("Dan 3:25", "καὶ συστὰς Αζαριας προσηύξατο"),
        ("Dan 3:92", "ἡ ὅρασις τοῦ τετάρτου ὁμοία υἱῷ θεοῦ"),
    ]
    (morphology_dir / "daniel-theodotion.json").write_text(
        json.dumps([{"ref": ref, "words": _words(text)} for ref, text in verses]), encoding="utf-8"
    )
    pairings = {}
    for pair in PAIRS:
        pairings.setdefault((pair["grk_book"], pair["grk_ref"]), []).append(pair)
    translations = {("DAG", "3:25"): "Then Azarias stood up.", ("DAG", "3:92"): "like the Son of God."}
    # Both verses differ from Brenton's Greek; only 3:92 (outside 3:24-90) is compared.
    greek = {("DAG", "3:25"): "καὶ συστὰς Ανανιας προσηύξατο", ("DAG", "3:92"): "ἡ ὅρασις τοῦ τετάρτου ὁμοία ἀγγέλῳ θεοῦ"}

    rows = {
        row["edition_reference"]: row
        for row in (dict(zip(LXX_ROW_FIELDS, row)) for row in iter_lxx_rows(
            morphology_dir, pairings, translations, greek
        ))
    }

    assert [rows["Dan.3.25"][key] for key in LXX_ROW_FIELDS[-3:]] == [None, None, None]
    assert rows["Dan.3.92"]["brenton_greek_differs"] == 1


@pytest.mark.parametrize(("book", "chapter", "verse", "canonical", "expected"), [
    ("Sir", 17, 17, None, "Sirach"),
    ("Pss", 17, 1, None, "the Psalms of Solomon"),
    ("EsG", 1, 1, None, "the Greek additions to Esther"),
    ("EsG", 1, 1, "Est.1.1", None),
    ("Dan", 3, 24, None, "the Prayer of Azariah and Song of the Three (Dan 3:24–90)"),
    ("Dan", 3, 90, None, "the Prayer of Azariah and Song of the Three (Dan 3:24–90)"),
    ("Dan", 3, 91, "Dan.3.24", None),
    ("Dan", 4, 17, None, None),  # Old Greek plus 4:17a, a textual variant
    ("Psa", 151, 1, None, "Psalm 151"),
    ("Psa", 144, 13, None, None),  # 144:13a, a textual plus
    ("1Ki", 2, 35, None, None),  # 3 Kingdoms 2:35a
    ("Ode", 1, 1, None, None),  # Exodus 15
    ("Ode", 12, 1, None, "the Prayer of Manasseh (Ode 12)"),
    ("2Es", 1, 1, "Ezr.1.1", None),
])
def test_apocrypha_rows_are_identified(book, chapter, verse, canonical, expected):
    assert apocrypha_name(book, chapter, verse, canonical) == expected


def test_every_lxx_only_book_but_ezra_nehemiah_greek_esther_and_odes_is_apocrypha():
    lxx_only = set(LXX_BOOK_CODES.values()) - set(MT_BOOK_CODES.values())
    assert set(APOCRYPHA_BOOK_NAMES) == lxx_only - {"2Es", "EsG", "Ode"}


def test_kjv_apocrypha_books_are_not_compared_with_brentons_greek(tmp_path, monkeypatch):
    # Deuteronomy 32:43 differs from Brenton's Greek fixture (it is flagged
    # elsewhere); as a KJV Apocrypha book it must be stored uncompared.
    monkeypatch.setattr(biblical_versions_module, "KJV_APOCRYPHA_BOOKS", frozenset({"Deu"}))
    conn = sqlite3.connect(_build_db(tmp_path))
    stored = conn.execute(
        """SELECT brenton_greek_differs, brenton_greek, brenton_greek_difference
           FROM biblical_version_verses WHERE edition_reference = 'Deu.32.43'"""
    ).fetchall()
    conn.close()

    assert stored == [(None, None, None)]


def test_import_adds_comparison_columns_to_an_existing_table(tmp_path):
    _write_lxx_sources(tmp_path / "data")
    conn = sqlite3.connect(":memory:")
    create_schema(conn)
    for column in ("brenton_greek_differs", "brenton_greek", "brenton_greek_difference"):
        conn.execute(f"ALTER TABLE biblical_version_verses DROP COLUMN {column}")

    import_biblical_versions(conn, tmp_path / "data")

    assert conn.execute(
        "SELECT brenton_greek_differs FROM biblical_version_verses WHERE edition_reference = 'Deu.32.43'"
    ).fetchone() == (1,)


def test_parse_passage_reference_bounds():
    assert parse_passage_reference("Psalm 81:6-82:1")[1:] == ("Psa", (81, 6, ""), (82, 1, "~"))
    assert parse_passage_reference("Psalm 82")[1:] == ("Psa", (82, 0, ""), (82, 9999, "~"))
    assert parse_passage_reference("1 Kings 2:35a")[1:] == ("1Ki", (2, 35, "a"), (2, 35, "a"))


@pytest.mark.parametrize(("reference", "expected"), [
    ("John3:16", "Jhn.3.16"),
    ("1John3:16", "1Jn.3.16"),
    ("Gen1:1", "Gen.1.1"),
    ("Ps23:1", "Psa.23.1"),
    ("John 3:16", "Jhn.3.16"),
    ("Song of Solomon 2:1", "Sng.2.1"),
])
def test_normalize_reference_accepts_compact_forms(tmp_path, reference, expected):
    assert StudyBibleDB(tmp_path / "unused.db")._normalize_reference(reference) == expected


def test_comparison_formatter_honors_original_and_morphology_flags():
    row = {
        "version": "LXX",
        "edition": "Rahlfs Septuagint (1935)",
        "language": "Greek",
        "canonical_reference": "Psa.24.1",
        "edition_reference": "Psa.23.1",
        "text": "τοῦ κυρίου",
        "translation": "The earth is the Lord's.",
        "license": "CC BY 4.0",
        "source_url": "https://example.test/lxx",
        "mapping_method": "tvtms",
        "morphology": json.dumps([
            {"surface": "κυρίου", "lemma": "κύριος", "parsing": "masc gen sg", "pos": "noun"}
        ]),
    }

    compact = format_biblical_version_comparison("Psalm 24:1", [row], False, False)
    detailed = format_biblical_version_comparison("Psalm 24:1", [row], True, True)

    assert "τοῦ κυρίου" not in compact
    assert "Morphology" not in compact
    assert "### Psa.24.1" in compact
    assert "#### LXX Rahlfs Septuagint (1935) · Psa.23.1 (mapping: tvtms)" in compact
    # Provenance is listed once, in the closing Sources block.
    assert compact.count("https://example.test/lxx") == 1
    assert "- LXX Rahlfs Septuagint (1935) (Greek): CC BY 4.0." in compact
    assert "TVTMS (Tyndale Versification Traditions Mapping System)" in compact
    assert "τοῦ κυρίου" in detailed
    assert "κύριος; noun; masc gen sg" in detailed


def test_formatter_prints_non_identity_mapping_even_when_references_match():
    row = {
        "version": "LXX", "edition": "Rahlfs Septuagint (1935)", "language": "Greek",
        "canonical_reference": "Psa.8.6", "edition_reference": "Psa.8.6", "text": "x",
        "translation": None, "license": "CC BY 4.0", "source_url": "https://example.test",
        "mapping_method": "tvtms",
    }

    assert "· Psa.8.6 (mapping: tvtms)" in format_biblical_version_comparison("Psalm 8:6", [row])


def _load_download_script():
    path = Path(__file__).resolve().parent.parent / "scripts" / "download_biblical_versions.py"
    spec = importlib.util.spec_from_file_location("download_biblical_versions", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _zip_client(files: dict[str, bytes]) -> httpx.Client:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(f"eng-Brenton_usfm/{name}", content)
    return httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, content=buffer.getvalue())
    ))


def test_brenton_download_verifies_extracted_books_not_archive_bytes(tmp_path, monkeypatch):
    module = _load_download_script()
    good = b"\\id GEN\n\\c 1\n\\v 1 In the beginning.\n"
    monkeypatch.setattr(module, "BRENTON_USFM_SHA256", {"02-GENeng-Brenton.usfm": hashlib.sha256(good).hexdigest()})

    manifest = module._download_brenton(_zip_client({"02-GENeng-Brenton.usfm": good}), tmp_path, force=False)

    assert (tmp_path / "brenton" / "02-GENeng-Brenton.usfm").read_bytes() == good
    assert manifest["files"]["02-GENeng-Brenton.usfm"]["sha256"] == hashlib.sha256(good).hexdigest()


def test_brenton_mismatch_keeps_user_files(tmp_path, monkeypatch):
    module = _load_download_script()
    good = b"\\id GEN\n\\c 1\n\\v 1 In the beginning.\n"
    local = tmp_path / "brenton" / "02-GENeng-Brenton.usfm"
    local.parent.mkdir()
    local.write_bytes(good)
    monkeypatch.setattr(module, "BRENTON_USFM_SHA256", {"02-GENeng-Brenton.usfm": hashlib.sha256(good).hexdigest()})

    with pytest.raises(RuntimeError, match="02-GENeng-Brenton.usfm"):
        module._download_brenton(_zip_client({"02-GENeng-Brenton.usfm": b"changed"}), tmp_path, force=True)
    assert local.read_bytes() == good

    local.write_bytes(b"locally edited")
    with pytest.raises(RuntimeError, match="left in place"):
        module._download_brenton(_zip_client({}), tmp_path, force=False)
    assert local.read_bytes() == b"locally edited"


def test_brenton_greek_download_is_pinned_per_book(tmp_path, monkeypatch):
    module = _load_download_script()
    good = "\\id DEU - Brenton Greek Text\n\\c 32\n\\v 43 Εὐφράνθητε οὐρανοὶ\n".encode()
    name = "06-DEUgrcbrent.usfm"
    monkeypatch.setattr(module, "BRENTON_GREEK_USFM_SHA256", {name: hashlib.sha256(good).hexdigest()})

    with pytest.raises(RuntimeError, match="BRENTON_GREEK_USFM_SHA256"):
        module._download_brenton_greek(_zip_client({name: b"changed"}), tmp_path, force=False)
    assert not (tmp_path / "brenton-greek").exists()

    manifest = module._download_brenton_greek(_zip_client({name: good}), tmp_path, force=False)

    assert (tmp_path / "brenton-greek" / name).read_bytes() == good
    assert manifest["source_url"] == "https://ebible.org/Scriptures/grcbrent_usfm.zip"
    assert manifest["files"][name]["sha256"] == hashlib.sha256(good).hexdigest()


def test_download_default_data_dir_is_project_relative():
    module = _load_download_script()
    default = next(param.default for param in module.main.params if param.name == "data_dir")

    assert default == Path(module.__file__).resolve().parent.parent / "data" / "lxx"


def _comparison_rows(count: int) -> list[dict]:
    rows = []
    for verse in range(1, count + 1):
        for version in ("MT", "LXX"):
            rows.append({
                "version": version,
                "canonical_reference": f"Psa.119.{verse}",
                "canonical_chapter": 119,
                "canonical_verse": verse,
                "edition_reference": f"Psa.{119 if version == 'MT' else 118}.{verse}",
            })
    return rows


def test_comparison_is_capped_and_names_where_to_continue():
    from study_bible_mcp.server import MAX_COMPARISON_VERSES, _cap_comparison_rows

    rows, note = _cap_comparison_rows("Psalm 119", _comparison_rows(176), "canonical")

    assert len({row["canonical_reference"] for row in rows}) == MAX_COMPARISON_VERSES == 10
    assert len(rows) == 20  # both versions of each kept verse
    assert note == "Showing the first 10 of 176 verses. Continue from 'Psalm 119:11' in another call."

    _, lxx_note = _cap_comparison_rows("Psalm 118", _comparison_rows(12), "lxx")
    assert "Continue from Psa.118.11 (numbering='lxx')" in lxx_note


def test_comparison_under_the_cap_is_unchanged():
    from study_bible_mcp.server import _cap_comparison_rows

    rows = _comparison_rows(8)
    assert _cap_comparison_rows("1 Samuel 3:1-8", rows, "canonical") == (rows, "")
