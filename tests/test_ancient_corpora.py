"""Corpus registry, locator grammars, citation resolution, generic import and lookup."""

import hashlib
import importlib.util
import sqlite3
import sys
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from study_bible_mcp import server
from study_bible_mcp.corpora import (
    CORPORA,
    BiblicalLink,
    Collection,
    Corpus,
    SourceTag,
    TagSection,
    Work,
    build_registry,
    combined_license,
    resolve_citation,
)
from study_bible_mcp.corpora.download import fetch_github_directory, fetch_verified, git_blob_sha1
from study_bible_mcp.corpora.locators import (
    BOOK_SECTION,
    CHAPTER_VERSE,
    COLUMN_LINE,
    SECTION,
    roman_to_int,
)
from study_bible_mcp.database import (
    StudyBibleDB,
    ancient_search_index_text,
    create_schema,
    fold_ancient_search_text,
    hebrew_prefix_variants,
)
from study_bible_mcp.parsers.ancient_sources import import_corpus
from study_bible_mcp.tools import TOOLS


# --- Test-only corpora shaped like the rabbinic, pseudepigrapha and Qumran ones.

MISHNAH = Collection("Mishnah", ("m.",))
# Test-only collections sharing a tractate title with the Mishnah under other
# grammars, to exercise collection prefixes and selection by locator grammar.
SCROLLS = Collection("Test Scrolls", ("ts.",))
SECTIONS = Collection("Test Sections", ("tsec.",))
BAVA_BATRA = ("BB", "Baba Bathra", "B. Bat.")


TEST_TAG = SourceTag(kind="Test tradition", date="c. AD 200", tier="B", edition="Test edition")


def _corpus(key, works, parse=lambda directory: [], links=lambda passages: [], periods=("test",),
            original_language="Hebrew", aliases=(), tag=TEST_TAG, caveat=None):
    return Corpus(
        key=key, label=key.title(), summary=f"{key} test corpus", data_dir=key,
        original_language=original_language, works=tuple(works), periods=periods,
        download=lambda client, target, force: {}, require_files=lambda directory: None,
        parse=parse, biblical_links=links, example_query="shekels",
        example_citation="Mishnah Shekalim 1:1", aliases=aliases, tag=tag,
        caveat=f"Not Scripture: {key} test caveat." if caveat is None else caveat,
    )


RABBINIC_WORKS = (
    Work("mishnah_bava_batra", "Bava Batra", "Bava Batra", CHAPTER_VERSE, BAVA_BATRA, MISHNAH),
    Work("scroll_bava_batra", "Bava Batra", "Bava Batra", COLUMN_LINE, BAVA_BATRA, SCROLLS),
    Work("section_bava_batra", "Bava Batra", "Bava Batra", SECTION, BAVA_BATRA, SECTIONS),
    Work("mishnah_shekalim", "Shekalim", "Shekalim", CHAPTER_VERSE, ("Shek.",), MISHNAH),
)
PSEUDEPIGRAPHA_WORKS = (
    Work("1_enoch", "1 Enoch", "1 Enoch", CHAPTER_VERSE, ("1 En.", "Ethiopic Enoch")),
    Work("4_ezra", "4 Ezra", "4 Ezra", CHAPTER_VERSE, ("4 Ezr.",)),
)
QUMRAN_WORKS = (
    Work("damascus_document", "Damascus Document", "CD", COLUMN_LINE, ("Damascus Document",)),
    Work("pesher_habakkuk", "Pesher Habakkuk", "1QpHab", COLUMN_LINE, ("Pesher Habakkuk",)),
)
_STAND_IN_CORPORA = (
    _corpus("rabbinic", RABBINIC_WORKS),
    _corpus("pseudepigrapha", PSEUDEPIGRAPHA_WORKS, original_language="Ge'ez"),
    _corpus("qumran", QUMRAN_WORKS),
)
# Real corpora with a stand-in's key are replaced by the stand-in, so these
# citation tests stay fixed as corpora are registered.
TEST_CORPORA = (
    *(corpus for key, corpus in CORPORA.items()
      if key not in {stand_in.key for stand_in in _STAND_IN_CORPORA}),
    *_STAND_IN_CORPORA,
)

SHEKALIM_HEBREW = "בְּאֶחָד בַּאֲדָר מַשְׁמִיעִין עַל הַשְּׁקָלִים"


def _shekalim_row(**overrides):
    row = {
        "author": "Mishnah",
        "work_key": "mishnah_shekalim",
        "reference": "Mishnah Shekalim 1:1",
        "sort_start": CHAPTER_VERSE.key(1, 1),
        "sort_end": CHAPTER_VERSE.key(1, 1),
        "text": "On the first of Adar they announce the shekels.",
        "original_text": SHEKALIM_HEBREW,
        "original_language": "Hebrew",
        "period_tags": "test",
        "edition": "Test Hebrew edition",
        "translation": "Test English translation",
        "original_license": "CC BY-NC 4.0",
        "translation_license": "Public domain",
        "license": combined_license("CC BY-NC 4.0", "Public domain", "Hebrew"),
        "source_url": "https://example.test/shekalim",
    }
    row.update(overrides)
    return row


# --- Locator grammars


@pytest.mark.parametrize("text, expected", [
    ("18.116", (18116, 18116)),
    ("18.116-119", (18116, 18119)),
    ("18.116–119", (18116, 18119)),
    ("18,116", (18116, 18116)),
    ("18.116-19.5", (18116, 19005)),
    ("18", (18000, 18999)),
    ("17-18", (17000, 18999)),
    ("18.116.", (18116, 18116)),
])
def test_book_section_locator(text, expected):
    assert BOOK_SECTION.parse(text) == expected


@pytest.mark.parametrize("text", ["", "18.116.2", "18.119-116", "18.1000", "a.1", "18.-", "18.116-19.5.1"])
def test_book_section_locator_rejects(text):
    assert BOOK_SECTION.parse(text) is None


def test_chapter_verse_and_section_locators():
    assert CHAPTER_VERSE.parse("89:73") == (89073, 89073)
    assert CHAPTER_VERSE.parse("11-12") == (11000, 12999)
    assert CHAPTER_VERSE.parse("13:22-14:2") == (13022, 14002)
    assert CHAPTER_VERSE.parse("3b") is None
    assert SECTION.parse("116") == (116, 116)
    assert SECTION.parse("1-6") == (1, 6)
    assert SECTION.parse("1.2") is None


def test_column_line_locator_accepts_roman_columns():
    assert roman_to_int("VI") == 6 and roman_to_int("xiv") == 14 and roman_to_int("iiii") is None
    for text in ("6:11", "VI 11", "vi, 11", "VI.11"):
        assert COLUMN_LINE.parse(text) == (6011, 6011), text
    assert COLUMN_LINE.parse("VI 11-VII 2") == (6011, 7002)
    assert COLUMN_LINE.parse("6:11-VII") is None


def test_numbered_format_range_collapses_whole_units():
    assert BOOK_SECTION.format_range(18116, 18119) == "18.116–119"
    assert BOOK_SECTION.format_range(1001, 20268) == "1.1–20.268"
    assert BOOK_SECTION.format_range(18000, 18999) == "18"
    assert CHAPTER_VERSE.format_range(11000, 12999) == "11–12"
    assert CHAPTER_VERSE.format_range(3005, 3005) == "3:5"


def test_locator_key_rejects_out_of_range_parts():
    with pytest.raises(ValueError):
        BOOK_SECTION.key(18, 1000)
    with pytest.raises(ValueError):
        BOOK_SECTION.key(18)


# --- Citation resolution


def _resolved(citation, corpora=TEST_CORPORA):
    resolution = resolve_citation(citation, corpora)
    assert resolution.status == "ok", (citation, resolution)
    return resolution.match.corpus.key, resolution.match.work.key, resolution.match.sort_range


@pytest.mark.parametrize("citation, expected", [
    ("Antiquities 18.116", ("josephus", "antiquities", (18116, 18116))),
    ("Ant. 18.116-119", ("josephus", "antiquities", (18116, 18119))),
    ("A.J. 15.320", ("josephus", "antiquities", (15320, 15320))),
    ("AJ 15.320", ("josephus", "antiquities", (15320, 15320))),
    ("Josephus, Jewish Antiquities 18.116", ("josephus", "antiquities", (18116, 18116))),
    ("War 6.316", ("josephus", "jewish_war", (6316, 6316))),
    ("B.J. 6.316", ("josephus", "jewish_war", (6316, 6316))),
    ("Life 1", ("josephus", "life", (1, 1))),
    ("Against Apion 2.1", ("josephus", "against_apion", (2001, 2001))),
    ("Bava Batra VI 11", ("rabbinic", "scroll_bava_batra", (6011, 6011))),
    ("BB VI 11-VII 2", ("rabbinic", "scroll_bava_batra", (6011, 7002))),
    ("Baba Bathra vi, 11", ("rabbinic", "scroll_bava_batra", (6011, 6011))),
    ("Test Sections Bava Batra 116", ("rabbinic", "section_bava_batra", (116, 116))),
    ("Mishnah Bava Batra 1:1", ("rabbinic", "mishnah_bava_batra", (1001, 1001))),
    ("m. B. Bat. 1:1", ("rabbinic", "mishnah_bava_batra", (1001, 1001))),
    ("Mishnah Shekalim 1:1", ("rabbinic", "mishnah_shekalim", (1001, 1001))),
    ("1 Enoch 89:73", ("pseudepigrapha", "1_enoch", (89073, 89073))),
    ("4 Ezra 11-12", ("pseudepigrapha", "4_ezra", (11000, 12999))),
    ("CD 1:1", ("qumran", "damascus_document", (1001, 1001))),
    ("CD VI, 11", ("qumran", "damascus_document", (6011, 6011))),
    ("Damascus Document 6:11", ("qumran", "damascus_document", (6011, 6011))),
    ("1QpHab 2:1", ("qumran", "pesher_habakkuk", (2001, 2001))),
])
def test_resolves_citations_across_corpora(citation, expected):
    assert _resolved(citation) == expected


def test_shared_title_without_collection_is_ambiguous_until_prefixed():
    ambiguous = resolve_citation("Bava Batra 1:1", TEST_CORPORA)

    assert ambiguous.status == "ambiguous"
    assert {match.work.key for match in ambiguous.candidates} == {
        "mishnah_bava_batra", "scroll_bava_batra",
    }
    assert _resolved("Test Scrolls Bava Batra 1:1")[1] == "scroll_bava_batra"
    assert _resolved("ts. BB 1:1")[1] == "scroll_bava_batra"


def test_hyphens_and_dashes_separate_name_tokens_but_not_locators():
    hyphenated = _corpus("hyphenated", (
        Work("proto_exodus", "Exodus", "Exodus", CHAPTER_VERSE, ("Exod.",),
             Collection("Proto-Collection", ("Proto-Coll.", "Pr.-C."))),
    ))
    corpora = (CORPORA["josephus"], hyphenated)

    for citation in ("Proto-Collection Exodus 12:40", "Proto Collection Exodus 12:40",
                     "Proto–Collection Exod. 12:40", "Pr.-C. Exod 12:40", "Pr C Exodus 12:40"):
        assert _resolved(citation, corpora) == ("hyphenated", "proto_exodus", (12040, 12040)), citation
    assert _resolved("Pr.-C. Exodus 12:40-13:2", corpora)[2] == (12040, 13002)
    assert _resolved("Ant. 18.116-119", corpora) == ("josephus", "antiquities", (18116, 18119))
    assert _resolved("Ant. 18.116–119", corpora) == ("josephus", "antiquities", (18116, 18119))


def test_unknown_work_and_unreadable_locator():
    assert resolve_citation("Lifeboat 1-2", list(CORPORA.values())).status == "unknown_work"
    assert resolve_citation("Lifeboat 1", TEST_CORPORA).status == "unknown_work"

    bad = resolve_citation("Mishnah Bava Batra 3b", TEST_CORPORA)
    whiston = resolve_citation("Ant. 18.5.2", TEST_CORPORA)

    assert bad.status == "bad_locator"
    assert [match.work.key for match in bad.candidates] == ["mishnah_bava_batra"]
    assert whiston.status == "bad_locator" and whiston.candidates[0].locator_text == "18.5.2"


def test_apostrophes_in_transliterated_names_are_ignored():
    corpus = _corpus("apostrophes", (
        Work("mishnah_taanit", "Taanit", "Taanit", CHAPTER_VERSE),
        Work("mishnah_meilah", "Me'ilah", "Me'ilah", CHAPTER_VERSE),
    ))

    for citation, expected in (
        ("Ta'anit 2:1", ("mishnah_taanit", (2001, 2001))),
        ("Ta’anit 2:1", ("mishnah_taanit", (2001, 2001))),
        ("Meʼilah 1:1", ("mishnah_meilah", (1001, 1001))),
        ("Meilah 1:1", ("mishnah_meilah", (1001, 1001))),
    ):
        assert _resolved(citation, [corpus])[1:] == expected, citation


# --- Registry


def test_registry_rejects_duplicate_keys_works_and_directories():
    rabbinic = _corpus("rabbinic", RABBINIC_WORKS)
    duplicate_work = _corpus("doubled", (RABBINIC_WORKS[0], RABBINIC_WORKS[0]))

    with pytest.raises(ValueError, match="Duplicate corpus key"):
        build_registry((rabbinic, rabbinic))
    with pytest.raises(ValueError, match="unique keys"):
        build_registry((duplicate_work,))
    with pytest.raises(ValueError, match="already used"):
        build_registry((rabbinic, replace(_corpus("other", QUMRAN_WORKS), data_dir="rabbinic")))


def test_registry_requires_a_caveat_and_a_complete_tag_for_every_work():
    untagged = _corpus("untagged", QUMRAN_WORKS, tag=None)
    work_tagged = _corpus("work_tagged", (replace(QUMRAN_WORKS[0], tag=TEST_TAG),), tag=None)
    bad_tier = _corpus("bad_tier", QUMRAN_WORKS, tag=replace(TEST_TAG, tier="C"))
    bad_section = _corpus("bad_section", QUMRAN_WORKS, tag=replace(
        TEST_TAG, sections=(TagSection("not a locator", "Part", "c. 100 BC", "A"),)
    ))

    with pytest.raises(ValueError, match="'damascus_document' has no tag"):
        build_registry((untagged,))
    with pytest.raises(ValueError, match="caveat"):
        build_registry((_corpus("silent", QUMRAN_WORKS, caveat=""),))
    with pytest.raises(ValueError, match="caveat"):
        build_registry((_corpus("verbose", QUMRAN_WORKS, caveat="x" * 400),))
    with pytest.raises(ValueError, match="unknown tiers"):
        build_registry((bad_tier,))
    with pytest.raises(ValueError, match="not a damascus_document locator"):
        build_registry((bad_section,))
    assert build_registry((work_tagged,))["work_tagged"].tag is None


def test_every_registered_work_has_a_tag_and_every_corpus_a_caveat():
    for corpus in CORPORA.values():
        assert corpus.caveat.startswith("Not Scripture"), corpus.key
        assert corpus.caveat.count(". ") <= 2, corpus.key
        for work in corpus.works:
            line = corpus.tag_line(work.key, None)
            assert line.startswith("Not Scripture · "), (corpus.key, work.key)
            assert " · tier " in line


def test_tag_lines_date_sections_and_name_manuscripts():
    enoch = CORPORA["pseudepigrapha"]
    key = enoch.work("1_enoch").locator.parse

    assert enoch.tag_line("1_enoch", key("1:9")[0]) == (
        "Not Scripture · Jewish pseudepigraphon (Book of the Watchers, 4th–3rd c. BC) · "
        "tier A · Charles 1912"
    )
    assert enoch.tag_line("1_enoch", key("71:14")[0]) == (
        "Not Scripture · Jewish pseudepigraphon (Parables, c. 50 BC–AD 117, debated) · "
        "tier A/B · Charles 1912"
    )
    assert "tier B" in enoch.tag_line("4_ezra", key("7:28")[0])
    assert CORPORA["rabbinic"].tag_line("mishnah_sukkah", None) == (
        "Not Scripture · Mishnah (redacted c. AD 200; pre-70 attributions unverified) · "
        "tier B · Vilna Hebrew, Kulp English"
    )
    assert CORPORA["qumran"].tag_line("damascus_document", None).endswith(
        "copies: Cairo Genizah, 10th and 11th–12th c. AD"
    )
    assert "AD 93–94" in CORPORA["josephus"].tag_line("antiquities", None)
    assert set(enoch.tiers()) == {"A", "B"}


def test_every_registered_corpus_declares_a_resolvable_example_citation():
    for corpus in CORPORA.values():
        resolution = resolve_citation(corpus.example_citation, [corpus])
        assert resolution.status == "ok", corpus.key
        assert corpus.example_query.strip()


def test_tool_schemas_list_registered_corpora_and_periods():
    tools = {tool.name: tool for tool in TOOLS}
    search = tools["search_ancient_sources"].inputSchema["properties"]
    lookup = tools["lookup_ancient_source"].inputSchema["properties"]

    assert search["corpus"]["enum"] == [*CORPORA, "all"]
    assert lookup["corpus"]["enum"] == list(CORPORA)
    for corpus in CORPORA.values():
        assert f"`{corpus.key}`" in tools["search_ancient_sources"].description
        assert set(corpus.periods) <= set(search["period"]["enum"])


def test_combined_license_collapses_identical_licenses():
    assert combined_license("CC BY-SA 4.0", "CC BY-SA 4.0", "Greek") == "CC BY-SA 4.0"
    assert combined_license(None, "Public domain", None) == "Public domain"
    assert combined_license("CC BY-NC 4.0", "Public domain", "Hebrew") == (
        "Hebrew text: CC BY-NC 4.0; English translation: Public domain"
    )


# --- Schema, folding and generic import


OLD_SCHEMA = """
CREATE TABLE ancient_source_passages (
    id INTEGER PRIMARY KEY AUTOINCREMENT, corpus TEXT NOT NULL, author TEXT NOT NULL,
    work_key TEXT NOT NULL, work_title TEXT NOT NULL, reference TEXT NOT NULL,
    alternate_reference TEXT, book_number INTEGER NOT NULL, section_number TEXT NOT NULL,
    section_end INTEGER NOT NULL, editorial_heading TEXT, text TEXT NOT NULL,
    original_text TEXT, period_tags TEXT NOT NULL, edition TEXT NOT NULL, translation TEXT,
    license TEXT NOT NULL, source_url TEXT NOT NULL, UNIQUE(corpus, work_key, reference)
);
INSERT INTO ancient_source_passages
    (corpus, author, work_key, work_title, reference, book_number, section_number,
     section_end, text, period_tags, edition, license, source_url)
VALUES ('josephus', 'Flavius Josephus', 'antiquities', 'Jewish Antiquities',
        'Antiquities 18.116–119', 18, '116', 119, 'John', 'roman', 'Niese', 'CC BY-SA 4.0', 'u');
"""


def test_create_schema_adds_multi_corpus_columns_to_josephus_only_table(tmp_path):
    conn = sqlite3.connect(tmp_path / "old.db")
    conn.executescript(OLD_SCHEMA)

    create_schema(conn)
    create_schema(conn)

    columns = {row[1] for row in conn.execute("PRAGMA table_info(ancient_source_passages)")}
    indexes = {row[1] for row in conn.execute("PRAGMA index_list(ancient_source_passages)")}
    kept = conn.execute("SELECT reference, sort_start FROM ancient_source_passages").fetchall()
    conn.close()

    assert {"collection", "sort_start", "sort_end", "original_language",
            "original_license", "translation_license"} <= columns
    assert "idx_asp_locator" in indexes
    assert kept == [("Antiquities 18.116–119", None)]


def test_fold_strips_greek_accents_and_hebrew_points_and_cantillation():
    assert fold_ancient_search_text("Ἰωάννου βαπτισμῷ") == "ιωαννου βαπτισμω"
    assert fold_ancient_search_text("בְּרֵאשִׁ֖ית בָּרָ֣א") == "בראשית ברא"


@pytest.fixture
def rabbinic(monkeypatch):
    rows = [_shekalim_row()]
    corpus = _corpus("rabbinic", RABBINIC_WORKS, parse=lambda directory: [dict(r) for r in rows])
    monkeypatch.setitem(CORPORA, "rabbinic", corpus)
    monkeypatch.setitem(CORPORA, "pseudepigrapha", _corpus("pseudepigrapha", PSEUDEPIGRAPHA_WORKS))
    return rows


def _db(tmp_path) -> sqlite3.Connection:
    conn = sqlite3.connect(tmp_path / "corpora.db")
    create_schema(conn)
    return conn


def _counts(conn):
    return [
        conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("ancient_source_passages", "ancient_source_passages_fts",
                      "ancient_source_biblical_links")
    ]


def test_import_corpus_fills_registry_fields_and_is_idempotent(tmp_path, rabbinic):
    conn = _db(tmp_path)

    assert import_corpus(conn, "rabbinic", tmp_path) == 1
    assert import_corpus(conn, "rabbinic", tmp_path) == 1
    stored = conn.execute(
        """SELECT corpus, work_title, collection, sort_start, sort_end, original_language,
                  original_license, translation_license, license, book_number, section_number
           FROM ancient_source_passages"""
    ).fetchone()

    assert _counts(conn) == [1, 1, 0]
    assert stored == (
        "rabbinic", "Shekalim", "Mishnah", 1001, 1001, "Hebrew", "CC BY-NC 4.0",
        "Public domain", "Hebrew text: CC BY-NC 4.0; English translation: Public domain", 0, "",
    )


@pytest.mark.parametrize("override, message", [
    ({"period_tags": "tannaitic"}, "period tags"),
    ({"license": "CC BY-NC 4.0"}, "license"),
    ({"original_license": None}, "original_license"),
    ({"work_key": "mishnah_berakhot"}, "unknown work"),
    ({"work_title": "Shabbat"}, "registry value"),
    ({"sort_end": 1000}, "sort_start/sort_end"),
    ({"edition": ""}, "missing edition"),
    ({"chapter": 1}, "unknown passage fields"),
    ({"translation": ""}, "missing translation"),
    ({"text": "", "translation": "", "translation_license": "", "original_text": None,
      "original_license": None, "license": "Public domain"}, "or original_text"),
])
def test_import_corpus_validates_before_replacing_rows(tmp_path, rabbinic, override, message):
    conn = _db(tmp_path)
    import_corpus(conn, "rabbinic", tmp_path)
    rabbinic[0] = _shekalim_row(**override)

    with pytest.raises(ValueError, match=message):
        import_corpus(conn, "rabbinic", tmp_path)

    assert _counts(conn) == [1, 1, 0]


def test_import_corpus_rolls_back_a_failed_write_and_keeps_other_corpora(tmp_path, rabbinic, monkeypatch):
    conn = _db(tmp_path)
    import_corpus(conn, "rabbinic", tmp_path)
    conn.execute(
        """INSERT INTO ancient_source_passages (corpus, author, work_key, work_title, reference,
           book_number, section_number, section_end, text, period_tags, edition, license, source_url)
           VALUES ('other', 'a', 'w', 't', 'r', 0, '', 0, 'x', 'p', 'e', 'l', 'u')"""
    )
    conn.commit()
    rabbinic[:] = [_shekalim_row(), _shekalim_row()]  # duplicate reference: UNIQUE fails mid-write

    with pytest.raises(sqlite3.IntegrityError):
        import_corpus(conn, "rabbinic", tmp_path)

    assert _counts(conn) == [2, 1, 0]
    assert conn.execute("SELECT COUNT(*) FROM ancient_source_passages WHERE corpus = 'other'").fetchone() == (1,)


def test_import_corpus_resolves_links_by_locator_containment(tmp_path, rabbinic, monkeypatch):
    seen = []

    def derived_links(passages):
        # A verse-keyed corpus (e.g. a targum) derives links from its validated passages.
        seen.extend(passage["corpus"] for passage in passages)
        return [
            BiblicalLink(passage["work_key"], "1:1", "Exo", 30, 11, 30, 16, "Half-shekel offering")
            for passage in passages
        ]

    corpus = CORPORA["rabbinic"]
    monkeypatch.setitem(CORPORA, "rabbinic", replace(corpus, biblical_links=derived_links))
    conn = _db(tmp_path)

    import_corpus(conn, "rabbinic", tmp_path)

    assert seen == ["rabbinic"]

    assert conn.execute(
        "SELECT biblical_book, sort_start, sort_end FROM ancient_source_biblical_links"
    ).fetchall() == [("Exo", 30011, 30016)]
    for bad, message in (
        (BiblicalLink("mishnah_shekalim", "2:1", "Exo", 30, 11, 30, 16, "x"), "does not resolve"),
        (BiblicalLink("mishnah_shekalim", "1:1", "Exod", 30, 11, 30, 16, "x"), "unknown book code"),
    ):
        monkeypatch.setitem(
            CORPORA, "rabbinic", replace(corpus, biblical_links=lambda passages, bad=bad: [bad])
        )
        with pytest.raises(ValueError, match=message):
            import_corpus(conn, "rabbinic", tmp_path)


@pytest.mark.asyncio
async def test_search_folds_hebrew_niqqud_in_index_and_query(tmp_path, rabbinic):
    conn = _db(tmp_path)
    import_corpus(conn, "rabbinic", tmp_path)
    conn.close()
    database = StudyBibleDB(tmp_path / "corpora.db")
    await database.connect()
    try:
        pointed = await database.search_ancient_sources("הַשְּׁקָלִים", corpus="rabbinic")
        plain = await database.search_ancient_sources("השקלים", corpus=None)
        missing = await database.search_ancient_sources("השקלים", corpus="pseudepigrapha")
    finally:
        await database.close()

    assert pointed["terms"] == ["השקלים"]
    assert [row["reference"] for row in pointed["rows"]] == ["Mishnah Shekalim 1:1"]
    assert [row["reference"] for row in plain["rows"]] == ["Mishnah Shekalim 1:1"]
    assert missing["status"] == "corpus_missing"


# A Qumran-style line: an uncertain letter (circlet) and a restoration inside a
# word, a prefixed phrase, a scribal correction (erased א, ע written over it),
# and a vacat.
MARKED_HEBREW = "אלמנ֯[ו]ת ובהון המקדש י{{א}}<<ע>>בורו vacat יתומים"
ERASURES = (r"\{\{[^{}]*\}\}", r"\{[^{}]*\}", r"\bvacat\b")


@pytest.mark.asyncio
async def test_search_reads_through_editorial_signs_and_prefixes(tmp_path, rabbinic, monkeypatch):
    monkeypatch.setitem(
        CORPORA, "rabbinic", replace(CORPORA["rabbinic"], search_index_removals=ERASURES)
    )
    rabbinic[0] = _shekalim_row(original_text=MARKED_HEBREW)
    conn = _db(tmp_path)
    import_corpus(conn, "rabbinic", tmp_path)
    stored = conn.execute("SELECT original_text FROM ancient_source_passages").fetchone()[0]
    conn.close()
    database = StudyBibleDB(tmp_path / "corpora.db")
    await database.connect()
    try:
        async def search(query):
            return await database.search_ancient_sources(query, corpus="rabbinic")

        restored = await search("אלמנות")
        pasted = await search("אלמנ֯[ו]ת")
        unprefixed = await search("הון המקדש")
        one_prefix = await search("בהון")
        corrected = await search("יעבורו")
        erased = await search("יאבורו")
        vacat = await search("vacat")
    finally:
        await database.close()

    assert stored == MARKED_HEBREW
    for found in (restored, pasted, one_prefix, corrected):
        assert [row["reference"] for row in found["rows"]] == ["Mishnah Shekalim 1:1"]
    assert pasted["terms"] == ["אלמנות"]
    assert unprefixed["match"] == "all"
    assert erased["status"] == "no_match"
    assert vacat["status"] == "no_match"


def test_prefix_variants_strip_one_or_two_prefix_letters_and_keep_two_letters():
    assert hebrew_prefix_variants("ובהון") == ["בהון", "הון"]
    assert hebrew_prefix_variants("ומה") == ["מה"]
    assert hebrew_prefix_variants("שם") == []
    assert hebrew_prefix_variants("דבר") == []
    assert hebrew_prefix_variants("יתומים") == []


def test_index_text_adds_new_prefix_variants_only_for_hebrew_script():
    assert ancient_search_index_text("Ἰωάννου [τοῦ] βαπτιστοῦ") == "ιωαννου του βαπτιστου"
    # 'טוב' is already indexed, so 'וטוב' adds nothing.
    assert ancient_search_index_text("וטוב טוב") == "וטוב טוב"
    assert ancient_search_index_text("ובהון") == "ובהון\nבהון הון"


def test_excerpt_centres_hebrew_matches_through_points_signs_and_prefixes():
    from study_bible_mcp.tools import _match_excerpt

    def passage(middle):
        return "שורה " * 400 + middle + " סוף" * 400

    pointed = passage(SHEKALIM_HEBREW)
    marked = passage("ובהון המקדש אלמנ֯[ו]ת")

    assert "הַשְּׁקָלִים" in _match_excerpt(pointed, "שקלים", 600)
    assert "אלמנ֯[ו]ת" in _match_excerpt(marked, "אלמנות", 600)
    assert "ובהון" in _match_excerpt(marked, "הון", 600)


# --- lookup_ancient_source across corpora


async def _lookup(db_path: Path, monkeypatch, **args) -> str:
    database = StudyBibleDB(db_path)
    await database.connect()
    monkeypatch.setattr(server, "db", database)
    try:
        return (await server.handle_lookup_ancient_source(args))[0].text
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_lookup_shows_licences_and_original_language_of_any_corpus(tmp_path, rabbinic, monkeypatch):
    conn = _db(tmp_path)
    import_corpus(conn, "rabbinic", tmp_path)
    conn.close()
    db_path = tmp_path / "corpora.db"

    found = await _lookup(db_path, monkeypatch, citation="m. Shek. 1:1")
    ambiguous = await _lookup(db_path, monkeypatch, citation="Bava Batra 1:1")
    work_missing = await _lookup(db_path, monkeypatch, citation="Mishnah Bava Batra 1:1")
    corpus_missing = await _lookup(db_path, monkeypatch, citation="1 Enoch 89:73")

    assert found.startswith("## Mishnah Shekalim 1:1")
    assert "**Corpus:** Rabbinic" in found
    assert "**Work:** Shekalim (Mishnah)" in found
    assert "**Hebrew edition:** Test Hebrew edition" in found
    assert "**License:** Hebrew text: CC BY-NC 4.0; English translation: Public domain" in found
    assert f"**Hebrew text excerpt:**\n{SHEKALIM_HEBREW}" in found
    assert ambiguous.startswith("Ambiguous citation 'Bava Batra 1:1'")
    assert "Mishnah Bava Batra (Rabbinic, cited by chapter:verse)" in ambiguous
    assert "Test Scrolls Bava Batra (Rabbinic, cited by column:line)" in ambiguous
    assert "Test Sections" not in ambiguous
    assert work_missing == "No Mishnah Bava Batra passages are imported in this database."
    assert "Pseudepigrapha corpus is not in this database" in corpus_missing
    assert "python scripts/upgrade_database.py" in corpus_missing


@pytest.mark.asyncio
async def test_original_only_passage_imports_and_renders_its_original(tmp_path, rabbinic, monkeypatch):
    rabbinic[0] = _shekalim_row(
        text=None, translation=None, translation_license=None, license="CC BY-NC 4.0"
    )
    conn = _db(tmp_path)
    assert import_corpus(conn, "rabbinic", tmp_path) == 1
    conn.close()

    found = await _lookup(
        tmp_path / "corpora.db", monkeypatch, citation="m. Shek. 1:1", include_original=False
    )

    assert "**English translation:** none openly licensed" in found
    assert "showing the Hebrew text only" in found
    assert f"**Hebrew text excerpt:**\n{SHEKALIM_HEBREW}" in found
    assert "**License:** CC BY-NC 4.0" in found


# --- Downloads and smoke coverage


def _transport(files: dict[str, bytes], listing: list[dict] | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if "/contents/" in request.url.path:
            return httpx.Response(200, json=listing)
        return httpx.Response(200, content=files[request.url.path])
    return httpx.MockTransport(handler)


def test_fetch_verified_writes_only_verified_content(tmp_path):
    content = b"pinned text"
    expected = hashlib.sha256(content).hexdigest()
    with httpx.Client(transport=_transport({"/good": content, "/bad": b"tampered"})) as client:
        assert fetch_verified(client, "https://host.test/good", tmp_path / "good.txt", expected) == content
        with pytest.raises(RuntimeError, match="Checksum mismatch"):
            fetch_verified(client, "https://host.test/bad", tmp_path / "bad.txt", expected)
        (tmp_path / "stale.txt").write_bytes(b"stale")
        with pytest.raises(RuntimeError, match="Checksum mismatch"):
            fetch_verified(client, "https://host.test/good", tmp_path / "stale.txt", expected)

    assert (tmp_path / "good.txt").read_bytes() == content
    assert not (tmp_path / "bad.txt").exists()
    assert not (tmp_path / "stale.txt").exists()


def test_fetch_github_directory_selects_and_verifies_blob_hashes(tmp_path):
    content = b"<TEI/>"
    listing = [
        {"type": "file", "name": "wanted.xml", "sha": git_blob_sha1(content),
         "download_url": "https://raw.test/wanted.xml", "html_url": "https://github.test/wanted.xml"},
        {"type": "file", "name": "ignored.txt", "sha": "0", "download_url": "https://raw.test/x",
         "html_url": "x"},
        {"type": "dir", "name": "sub", "sha": "0", "download_url": None, "html_url": "x"},
    ]
    with httpx.Client(transport=_transport({"/wanted.xml": content}, listing)) as client:
        manifest = fetch_github_directory(
            client, "owner/repo", "abc123", "data", tmp_path,
            select=lambda name: f"local-{name}" if name.endswith(".xml") else None,
        )

    assert manifest == {"local-wanted.xml": {
        "git_blob_sha1": git_blob_sha1(content), "bytes": len(content),
        "source_url": "https://github.test/wanted.xml",
    }}
    assert (tmp_path / "local-wanted.xml").read_bytes() == content


def test_smoke_runner_covers_both_ancient_tools_for_every_corpus(monkeypatch):
    script = Path(__file__).resolve().parent.parent / "scripts" / "smoke_server.py"
    spec = importlib.util.spec_from_file_location("smoke_server", script)
    module = importlib.util.module_from_spec(spec)
    # Registered like a normal import, so module-level dataclasses can resolve it.
    monkeypatch.setitem(sys.modules, "smoke_server", module)
    spec.loader.exec_module(module)

    labels = {case[0] for case in module._cases()}

    for key in CORPORA:
        assert {f"search_ancient_sources[{key}]", f"lookup_ancient_source[{key}]"} <= labels
    assert set(module.TOOL_CASES) | set(module._PER_CORPUS_TOOLS) == {tool.name for tool in TOOLS}
