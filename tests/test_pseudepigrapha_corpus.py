"""Pseudepigrapha corpus: 1 Enoch (Charles) verses, 4 Ezra KJV/Latin pairing, import, tools."""

import sqlite3
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from study_bible_mcp import server
from study_bible_mcp.corpora import CORPORA, combined_license, pseudepigrapha, resolve_citation
from study_bible_mcp.corpora.pseudepigrapha import (
    ezra_verse,
    parse_enoch_chapter,
    parse_ezra,
    parse_kjv_2_esdras,
    parse_latin_4_esdras,
)
from study_bible_mcp.database import BOOK_ABBREV_MAP, StudyBibleDB, create_schema
from study_bible_mcp.parsers.ancient_sources import import_corpus

HEADER = """{{header
 | title      = [[../]]
 | section    = Chapter 89
 | previous   = [[../Chapter 88|Chapter 88]]
}}
"""

CHAPTER_89 = HEADER + """===LXXXIX. 1-71. Earlier verses.===

CHAPTER LXXXIX.

""" + " ".join(f"{verse}. Earlier text." for verse in range(1, 72)) + """

===LXXXIX. 72-77. Second Period—from the Time of Cyrus.===

72. And forthwith I saw how the shepherds pastured for twelve hours, and behold three of those sheep turned back and began to build up all that had fallen down of that house. 73. And they began again to build as before, and they reared up that tower, and it was named the ''high'' tower; and they began again to place a table before the tower, but all the bread on it was polluted and not pure.

{| class="wikitable"
|-
! Ethiopic !! Greek
|-
| 74. And as touching all this the eyes of those sheep were blinded.|| 74. Greek-recension rendering that must be omitted.
|}

{| class="wikitable"
|-
| 75. And the Lord of the sheep remained unmoved. || 76. A doublet column that belongs to the text.
|}

And an unnumbered poetic line continues verse 76.
"""

CHAPTER_5 = HEADER + """CHAPTER V.

1. Observe ye how the trees cover themselves.

6a. In those days ye shall make your names an eternal execration,

b. And by you shall all who curse, curse,

7c. And for you the godless there shall be a curse.

6d. And all the . . . shall rejoice,

e. And there shall be forgiveness of sins,

2. And all His works go on thus.

3. And behold how the sea.

4. But ye have not been steadfast.

5. Therefore shall ye execrate your days.

7a. But for the elect there shall be light.
"""

CHAPTER_74 = HEADER + """1. And I saw another course. 2. [For in 8 years she falls behind to the amount of 80 days], all the days she falls behind in 8 years are 80. 3. And the year is completed.
"""


def _write_enoch(directory: Path, chapters: dict[int, str]) -> None:
    for chapter, text in chapters.items():
        (directory / pseudepigrapha._enoch_file(chapter)).write_text(text, encoding="utf-8")


# --- 1 Enoch parser


def test_enoch_verses_headings_and_parallel_columns():
    every = parse_enoch_chapter(89, CHAPTER_89)
    rows = every[71:]

    assert len(every) == 76 and every[0]["editorial_heading"] == "LXXXIX. 1-71. Earlier verses."

    assert [(r["reference"], r["sort_start"]) for r in rows] == [
        ("1 Enoch 89:72", 89072), ("1 Enoch 89:73", 89073), ("1 Enoch 89:74", 89074),
        ("1 Enoch 89:75", 89075), ("1 Enoch 89:76", 89076),
    ]
    assert rows[0]["editorial_heading"] == "LXXXIX. 72-77. Second Period—from the Time of Cyrus."
    assert rows[1]["editorial_heading"] is None
    assert rows[1]["text"].startswith("And they began again to build as before")
    assert "high tower" in rows[1]["text"] and "''" not in rows[1]["text"]
    assert rows[2]["text"] == "And as touching all this the eyes of those sheep were blinded."
    assert rows[4]["text"] == (
        "A doublet column that belongs to the text. "
        "And an unnumbered poetic line continues verse 76."
    )
    joined = " ".join(r["text"] for r in rows)
    assert "Greek-recension" not in joined and "CHAPTER" not in joined and "header" not in joined


def test_enoch_licence_and_metadata():
    row = parse_enoch_chapter(89, CHAPTER_89)[72]

    assert row["translation_license"] == "Public domain"
    assert row["license"] == combined_license(None, "Public domain", None) == "Public domain"
    assert "original_text" not in row and "original_license" not in row
    assert row["period_tags"] == "second_temple,hellenistic"
    assert row["author"] == "Anonymous (attributed to Enoch)"
    assert "oldid=13274793" in row["source_url"]
    assert parse_enoch_chapter(46, "1. And there I saw One.")[0]["period_tags"] == "second_temple,roman"


def test_enoch_sub_verses_keep_charles_order_and_labels():
    rows = parse_enoch_chapter(5, CHAPTER_5)

    assert [r["reference"] for r in rows] == [
        "1 Enoch 5:1", "1 Enoch 5:6a–b", "1 Enoch 5:7c", "1 Enoch 5:6d–e", "1 Enoch 5:2",
        "1 Enoch 5:3", "1 Enoch 5:4", "1 Enoch 5:5", "1 Enoch 5:7a",
    ]
    assert rows[1]["sort_start"] == rows[3]["sort_start"] == 5006
    assert rows[1]["text"] == (
        "In those days ye shall make your names an eternal execration, "
        "b. And by you shall all who curse, curse,"
    )


def test_enoch_false_marker_in_running_text_is_ignored():
    rows = parse_enoch_chapter(74, CHAPTER_74)

    assert [r["reference"] for r in rows] == ["1 Enoch 74:1", "1 Enoch 74:2", "1 Enoch 74:3"]
    assert rows[1]["text"].endswith("in 8 years are 80.")


@pytest.mark.parametrize("text, message", [
    ("Preamble text. 1. A verse.", "before the first verse"),
    ("1. One. 3. Three.", "not contiguous"),
    ("1. One. 2. Two. 2. Two again.", "appears twice"),
    ("No verses at all", "before the first verse"),
])
def test_enoch_malformed_chapters_fail(text, message):
    with pytest.raises(ValueError, match=message):
        parse_enoch_chapter(3, text)


# --- 4 Ezra parser

USFM = "\\id 2ES\n\\h 2 Esdras\n\\c 7\n" + "".join(
    f"\\p\n\\v {verse} English seven {verse}.\n" for verse in range(1, 38)
) + "\\c 10\n" + "".join(f"\\p\n\\v {verse} English ten {verse}.\n" for verse in range(1, 4))

LATIN = "{{Liber}}\n\n==Caput 7==\n\n" + " ".join(
    f"<sup>{verse}</sup> Latina septem {verse}." for verse in range(1, 38)
) + "\n\n==Caput 10==\n\n" + " ".join(f"<sup>{verse}</sup> Latina decem {verse}." for verse in range(1, 5))


@pytest.fixture
def ezra_dir(tmp_path, monkeypatch):
    (tmp_path / pseudepigrapha.KJV_FILE).write_text(USFM, encoding="utf-8")
    (tmp_path / pseudepigrapha.LATIN_FILE).write_text(LATIN, encoding="utf-8")
    monkeypatch.setattr(pseudepigrapha, "EZRA_CHAPTERS", (7, 10))
    monkeypatch.setattr(pseudepigrapha, "_EZRA_ALIGNED_SPANS", ((7, 2, 3),))
    return tmp_path


def test_kjv_and_latin_verse_parsers():
    english = parse_kjv_2_esdras(USFM)
    latin = parse_latin_4_esdras(LATIN)

    assert english[(7, 36)] == "English seven 36." and len(english) == 40
    assert latin[(10, 4)] == "Latina decem 4." and len(latin) == 41
    with pytest.raises(ValueError, match="not sequential"):
        parse_latin_4_esdras("==Caput 3==\n<sup>1</sup> a <sup>3</sup> c")
    with pytest.raises(ValueError, match="unexpected USFM"):
        parse_kjv_2_esdras("\\c 3\n\\q1 poetry")


def test_4_ezra_numbering_skips_the_missing_fragment():
    assert ezra_verse(7, 35) == 35
    assert ezra_verse(7, 36) == 106
    assert ezra_verse(7, 70) == 140
    assert ezra_verse(11, 36) == 36


def test_ezra_pairs_english_and_latin_with_aligned_spans(ezra_dir):
    rows = {r["reference"]: r for r in parse_ezra(ezra_dir)}

    span = rows["4 Ezra 7:2–3"]
    assert span["text"] == "English seven 2. English seven 3."
    assert span["original_text"] == "Latina septem 2. Latina septem 3."
    assert (span["sort_start"], span["sort_end"]) == (7002, 7003)
    renumbered = rows["4 Ezra 7:106"]
    assert renumbered["alternate_reference"] == "KJV 2 Esdras 7:36"
    assert renumbered["text"] == "English seven 36." and renumbered["sort_start"] == 7106
    assert "4 Ezra 7:36" not in rows
    last = rows["4 Ezra 10:3"]
    assert last["original_text"] == "Latina decem 3. Latina decem 4."
    assert last["license"] == "Latin text: CC BY-SA 4.0; English translation: Public domain"
    assert last["original_language"] == "Latin" and last["period_tags"] == "roman"
    assert last["author"] == "Anonymous (attributed to Ezra)"


def test_ezra_missing_chapter_fails(ezra_dir, monkeypatch):
    monkeypatch.setattr(pseudepigrapha, "EZRA_CHAPTERS", (7, 11))

    with pytest.raises(ValueError, match="chapter missing"):
        parse_ezra(ezra_dir)


def test_require_files_names_every_missing_file(tmp_path):
    _write_enoch(tmp_path, {1: "1. x"})

    with pytest.raises(FileNotFoundError) as error:
        CORPORA["pseudepigrapha"].require_files(tmp_path)

    message = str(error.value)
    assert "1_enoch_charles_002.wiki" in message and "1_enoch_charles_108.wiki" in message
    assert pseudepigrapha.KJV_FILE in message and pseudepigrapha.LATIN_FILE in message
    assert "1_enoch_charles_001.wiki" not in message


def test_aligned_spans_do_not_overlap():
    seen = set()
    for chapter, start, end in pseudepigrapha._EZRA_ALIGNED_SPANS:
        verses = {(chapter, verse) for verse in range(start, end + 1)}
        assert start < end and not verses & seen
        seen |= verses


# --- Import


LINKS = (
    ("1_enoch", "89:73", "Mal", 1, 7, 1, 7, "Related image: polluted bread on the table before the sanctuary"),
    ("4_ezra", "7:106", "Gen", 18, 23, 18, 33, "Related account: Abraham's intercession for Sodom"),
)


@pytest.fixture
def fixture_corpus(ezra_dir, monkeypatch):
    _write_enoch(ezra_dir, {89: CHAPTER_89})

    def parse(directory):
        return parse_enoch_chapter(89, CHAPTER_89) + parse_ezra(directory)

    monkeypatch.setitem(CORPORA, "pseudepigrapha", replace(
        CORPORA["pseudepigrapha"], parse=parse, require_files=lambda directory: None
    ))
    monkeypatch.setattr(pseudepigrapha, "_BIBLICAL_LINKS", LINKS)
    return ezra_dir


def _db(tmp_path, directory) -> Path:
    path = tmp_path / "pseudepigrapha.db"
    conn = sqlite3.connect(path)
    create_schema(conn)
    import_corpus(conn, "pseudepigrapha", directory)
    conn.close()
    return path


def test_import_is_idempotent_and_attaches_links(tmp_path, fixture_corpus):
    conn = sqlite3.connect(tmp_path / "p.db")
    create_schema(conn)

    first = import_corpus(conn, "pseudepigrapha", fixture_corpus)
    second = import_corpus(conn, "pseudepigrapha", fixture_corpus)
    links = conn.execute(
        """SELECT p.reference, l.biblical_book FROM ancient_source_biblical_links l
           JOIN ancient_source_passages p ON p.id = l.passage_id ORDER BY p.reference"""
    ).fetchall()
    languages = dict(conn.execute(
        "SELECT work_key, COALESCE(original_language, '') FROM ancient_source_passages GROUP BY work_key"
    ).fetchall())

    assert first == second == 76 + 36 + 3
    assert links == [("1 Enoch 89:73", "Mal"), ("4 Ezra 7:106", "Gen")]
    assert languages == {"1_enoch": "", "4_ezra": "Latin"}


def test_unresolved_link_fails_import(tmp_path, fixture_corpus, monkeypatch):
    monkeypatch.setattr(pseudepigrapha, "_BIBLICAL_LINKS", (("4_ezra", "7:50", "Gen", 1, 1, 1, 1, "x"),))
    conn = sqlite3.connect(tmp_path / "p.db")
    create_schema(conn)

    with pytest.raises(ValueError, match="does not resolve"):
        import_corpus(conn, "pseudepigrapha", fixture_corpus)


def test_curated_links_target_registered_works_and_valid_books():
    books = set(BOOK_ABBREV_MAP.values())
    for work_key, locator, book, c1, v1, c2, v2, note in pseudepigrapha._BIBLICAL_LINKS:
        work = CORPORA["pseudepigrapha"].work(work_key)
        assert work.locator.parse(locator) is not None and book in books and note
        assert (c1, v1) <= (c2, v2)


# --- Citations


@pytest.mark.parametrize("citation, expected", [
    ("1 Enoch 89:73", ("1_enoch", (89073, 89073))),
    ("1 En. 1:9", ("1_enoch", (1009, 1009))),
    ("Ethiopic Enoch 46", ("1_enoch", (46000, 46999))),
    ("Book of Enoch 6:1-2", ("1_enoch", (6001, 6002))),
    ("4 Ezra 11-12", ("4_ezra", (11000, 12999))),
    ("4 Ezr. 7:106", ("4_ezra", (7106, 7106))),
    ("2 Esdras 11:1", ("4_ezra", (11001, 11001))),
    ("2 Esd. 11:1", ("4_ezra", (11001, 11001))),
    ("4 Esdras 11:1", ("4_ezra", (11001, 11001))),
])
def test_resolves_pseudepigrapha_citations(citation, expected):
    resolution = resolve_citation(citation, CORPORA.values())

    assert resolution.status == "ok", resolution
    assert resolution.match.corpus.key == "pseudepigrapha"
    assert (resolution.match.work.key, resolution.match.sort_range) == expected


# --- Tools


async def _call(path: Path, monkeypatch, handler, **args) -> str:
    database = StudyBibleDB(path)
    await database.connect()
    monkeypatch.setattr(server, "db", database)
    try:
        return (await handler(args))[0].text
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_lookup_enoch_and_both_ezra_citation_forms(tmp_path, fixture_corpus, monkeypatch):
    path = _db(tmp_path, fixture_corpus)
    lookup = server.handle_lookup_ancient_source

    enoch = await _call(path, monkeypatch, lookup, citation="1 Enoch 89:73")
    ezra = await _call(path, monkeypatch, lookup, citation="4 Ezra 7:106")
    esdras = await _call(path, monkeypatch, lookup, citation="2 Esdras 7:106")
    fragment = await _call(path, monkeypatch, lookup, citation="4 Ezra 7:36")

    assert enoch.startswith("## 1 Enoch 89:73")
    assert "*Not Scripture · Jewish pseudepigraphon (Dream Visions, c. 165–160 BC) · tier A ·" in enoch
    assert "- Pseudepigrapha: Not Scripture: pseudepigrapha outside the 66-book canon" in enoch
    assert "License: Public domain." in enoch
    assert "all the bread on it was polluted" in enoch and "No English translation" not in enoch
    assert "- Shared tradition: Mal 1:7 — Related image" in enoch
    assert "(KJV 2 Esdras 7:36)" in ezra and "English seven 36." in ezra
    assert "*Not Scripture · Jewish apocalypse, 2 Esd 3–14 (c. AD 100) · tier B ·" in ezra
    assert "**Latin:** Latina septem 36." in ezra
    assert "License: Latin text: CC BY-SA 4.0; English translation: Public domain." in ezra
    assert esdras.split("\n", 1)[1] == ezra.split("\n", 1)[1]
    assert fragment.startswith("No passage covers 4 Ezra 7:36")


@pytest.mark.asyncio
async def test_search_english_and_latin(tmp_path, fixture_corpus, monkeypatch):
    path = _db(tmp_path, fixture_corpus)
    search = server.handle_search_ancient_sources

    sheep = await _call(path, monkeypatch, search, query="bread polluted", corpus="pseudepigrapha")
    latin = await _call(path, monkeypatch, search, query="Latina decem", corpus="pseudepigrapha")
    linked = await _call(
        path, monkeypatch, search, query="bread", corpus="pseudepigrapha", biblical_reference="Malachi 1:7"
    )

    assert "1 Enoch 89:73" in sheep
    assert "4 Ezra 10:3" in latin
    assert "1 Enoch 89:73" in linked


# --- Download


def test_download_verifies_kjv_and_latin_pins(tmp_path, monkeypatch):
    import io
    import zipfile

    usfm = b"\\c 3\n\\v 1 text\n"
    latin = b"==Caput 3==\n<sup>1</sup> textus"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(pseudepigrapha.KJV_FILE, usfm)
    monkeypatch.setattr(pseudepigrapha, "ENOCH_REVISIONS", {})
    monkeypatch.setattr(pseudepigrapha, "KJV_SHA256", pseudepigrapha.sha256_hex(usfm))
    monkeypatch.setattr(pseudepigrapha, "LATIN_SHA1", "0" * 40)
    seen_agents = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "ebible.org":
            return httpx.Response(200, content=buffer.getvalue())
        seen_agents.append(request.headers["user-agent"])
        return httpx.Response(200, content=latin)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RuntimeError, match="Checksum mismatch"):
            pseudepigrapha.download(client, tmp_path, force=False)

    assert (tmp_path / pseudepigrapha.KJV_FILE).read_bytes() == usfm
    assert not (tmp_path / pseudepigrapha.LATIN_FILE).exists()
    assert seen_agents and "github.com/djayatillake/studybible-mcp" in seen_agents[0]
