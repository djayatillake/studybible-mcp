"""The BSB as the verse tools' English text: verse mapping, labels, gloss
fallback, and the pinned bsb.txt importer and downloader.

Texts are invented test data, not quotations.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

import study_bible_mcp.server as server
from study_bible_mcp.database import StudyBibleDB, create_schema
from study_bible_mcp.parsers import bsb

from .tool_handler_fixture import build_fixture_db

# ---------------------------------------------------------------------------
# Verse mapping on a small database shaped like the STEPBible tables
# ---------------------------------------------------------------------------


def _words(gloss: str) -> str:
    return json.dumps([{"word": "λόγος", "strongs": "G3056", "gloss": gloss, "morph": "N-NSM"}])


# (reference, book, chapter, verse, gloss); every row also has original text.
VERSES = [
    ("Jhn.3.16", "Jhn", 3, 16, "Thus for loved the God the world"),
    # OT English(Hebrew) numbering.
    ("Gen.32.1(32.2)", "Gen", 32, 1, "and/ Jacob he went"),
    # One English verse stored as two rows (Hebrew 20:42 and 21:1).
    ("1Sa.20.42", "1Sa", 20, 42, "and/ he said Jonathan"),
    ("1Sa.20.42(21.1)", "1Sa", 20, 42, "and/ he arose and/ he went"),
    # An NT fragment with its KJV number in brackets beside the plain verse.
    ("Mat.17.14", "Mat", 17, 14, "And when coming they to the crowd"),
    ("Mat.17.15[17.14]", "Mat", 17, 15, "and saying;"),
    ("Mat.17.15", "Mat", 17, 15, "Lord, do have mercy"),
    # A textual-variant verse the BSB omits.
    ("Mat.17.21", "Mat", 17, 21, "this kind not goes out"),
    # Greek order with swapped KJV numbers: the BSB follows the Greek order.
    ("Php.1.16[1.17]", "Php", 1, 16, "the ones out of love"),
    ("Php.1.17[1.16]", "Php", 1, 17, "the ones out of selfish ambition"),
    # Greek 13:13 is English 13:14, which has no row of its own.
    ("2Co.13.12", "2Co", 13, 12, "do greet one another"),
    ("2Co.13.12[13.13]", "2Co", 13, 12, "[13] Greet you the saints all."),
    ("2Co.13.13[13.14]", "2Co", 13, 13, "[14] The grace of the Lord"),
    # A Psalm superscription (English verse 0); the BSB has no verse 0.
    ("Psa.23.0(23.1)", "Psa", 23, 0, "a psalm of/ David"),
    ("Psa.23.1", "Psa", 23, 1, "Yahweh [is] shepherd/ my"),
]

BSB_ROWS = [
    ("Jhn.3.16", "For God so loved the world (BSB test text)."),
    ("Gen.32.1", "Jacob went on his way (BSB test text)."),
    ("1Sa.20.42", "Jonathan said, Go in peace; and David departed (BSB test text)."),
    ("Mat.17.14", "A man came up to Jesus (BSB test text)."),
    ("Mat.17.15", "Lord, have mercy on my son, he said (BSB test text)."),
    ("Php.1.16", "The latter do so in love (BSB test text)."),
    ("Php.1.17", "The former preach out of selfish ambition (BSB test text)."),
    ("2Co.13.12", "Greet one another (BSB test text)."),
    ("2Co.13.13", "All the saints send greetings (BSB test text)."),
    ("2Co.13.14", "The grace of the Lord be with you (BSB test text)."),
    ("Psa.23.1", "The LORD is my shepherd (BSB test text)."),
]

EXPECTED_BSB = {
    "Jhn.3.16": "Jhn.3.16",
    "Gen.32.1(32.2)": "Gen.32.1",
    "1Sa.20.42": "1Sa.20.42",
    "1Sa.20.42(21.1)": None,
    "Mat.17.14": "Mat.17.14",
    "Mat.17.15[17.14]": None,
    "Mat.17.15": "Mat.17.15",
    "Mat.17.21": None,
    "Php.1.16[1.17]": "Php.1.16",
    "Php.1.17[1.16]": "Php.1.17",
    "2Co.13.12": "2Co.13.12",
    "2Co.13.12[13.13]": None,
    "2Co.13.13[13.14]": "2Co.13.14",
    "Psa.23.0(23.1)": None,
    "Psa.23.1": "Psa.23.1",
}


def _build(path: Path, *, bsb_rows=BSB_ROWS, drop_bsb: bool = False) -> Path:
    conn = sqlite3.connect(path)
    create_schema(conn)
    conn.executemany(
        """INSERT INTO verses (reference, book, chapter, verse, text_english, text_original, word_data)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [(ref, book, ch, v, gloss, f"original {ref}", _words(f"gloss {ref}"))
         for ref, book, ch, v, gloss in VERSES],
    )
    conn.executemany(
        "INSERT INTO bsb_verses (reference, book, chapter, verse, text) VALUES (?, ?, ?, ?, ?)",
        [(ref, *ref.split(".")[:1], *map(int, ref.split(".")[1:]), text) for ref, text in bsb_rows],
    )
    if drop_bsb:
        conn.execute("DROP TABLE bsb_verses")
    conn.commit()
    conn.close()
    return path


async def _open(path: Path, monkeypatch) -> StudyBibleDB:
    database = StudyBibleDB(path)
    await database.connect()
    monkeypatch.setattr(server, "db", database)
    return database


@pytest.fixture
async def mapped_db(tmp_path, monkeypatch):
    database = await _open(_build(tmp_path / "bsb.db"), monkeypatch)
    yield database
    await database.close()


async def _lookup(reference: str, **kwargs) -> str:
    return (await server.handle_lookup_verse({"reference": reference, **kwargs}))[0].text


async def test_each_row_gets_its_english_verse_and_each_bsb_verse_is_shown_once(mapped_db):
    rows = await mapped_db.attach_bsb_text(
        await mapped_db._fetchall("SELECT * FROM verses ORDER BY id")
    )
    texts = dict(BSB_ROWS)
    assert {row["reference"]: row["text_bsb"] for row in rows} == {
        ref: texts.get(target) for ref, target in EXPECTED_BSB.items()
    }


async def test_single_verse_shows_bsb_labelled_once_and_keeps_word_glosses(mapped_db):
    output = await _lookup("John 3:16")
    assert output.startswith("## Jhn.3.16 (BSB)\n\nFor God so loved the world (BSB test text).\n")
    assert "Thus for loved the God the world" not in output
    assert "- **λόγος** (G3056): gloss Jhn.3.16" in output
    assert output.count("(BSB)") == 1


async def test_passage_is_labelled_once_and_marks_glosses(mapped_db):
    output = await _lookup("Matthew 17:14-21")
    assert output.startswith("# Matthew 17:14-21 (BSB)\n")
    assert output.count("(BSB)") == 1
    assert "## Mat.17.15[17.14]\n\n[gloss] and saying;\n" in output
    assert "## Mat.17.15\n\nLord, have mercy on my son, he said (BSB test text).\n" in output
    assert "## Mat.17.21\n\n[gloss] this kind not goes out\n" in output


async def test_split_numbered_rows(mapped_db):
    assert (await _lookup("Genesis 32:1")).startswith(
        "## Gen.32.1(32.2) (BSB)\n\nJacob went on his way (BSB test text).\n"
    )
    two_rows = await _lookup("1 Samuel 20:42")
    assert two_rows.startswith("## 1Sa.20.42 (BSB)\n\nJonathan said")
    assert "## 1Sa.20.42(21.1)\n\n[gloss] and/ he arose and/ he went\n" in two_rows
    corinthians = await _lookup("2 Corinthians 13:12-13")
    assert "## 2Co.13.13[13.14]\n\nThe grace of the Lord be with you (BSB test text).\n" in corinthians
    assert "## 2Co.13.12[13.13]\n\n[gloss] [13] Greet you the saints all.\n" in corinthians
    psalm = await _lookup("Psalm 23")
    assert "## Psa.23 superscription (Hebrew Psa.23.1)\n\n[gloss] a psalm of/ David\n" in psalm


async def test_verse_the_bsb_omits_shows_the_marked_gloss_without_a_bsb_label(mapped_db):
    output = await _lookup("Matthew 17:21")
    assert output.startswith("## Mat.17.21\n\n[gloss] this kind not goes out\n")
    assert "(BSB)" not in output


@pytest.mark.parametrize("bsb_rows, drop", [([], False), (BSB_ROWS, True)], ids=["empty", "absent"])
async def test_without_the_bsb_the_gloss_is_shown_unmarked(tmp_path, monkeypatch, bsb_rows, drop):
    database = await _open(_build(tmp_path / "gloss.db", bsb_rows=bsb_rows, drop_bsb=drop), monkeypatch)
    try:
        output = await _lookup("John 3:16")
        assert output.startswith("## Jhn.3.16\n\nThus for loved the God the world\n")
        assert "(BSB)" not in output and "[gloss]" not in output
        verse = await database.get_verse("Genesis 32:1")
        assert "text_bsb" not in verse
    finally:
        await database.close()


# ---------------------------------------------------------------------------
# The other verse tools, on the handler fixture with BSB rows
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def bsb_fixture_file(tmp_path_factory):
    path = tmp_path_factory.mktemp("bsb_handlers") / "fixture.db"
    return SimpleNamespace(path=path, vectors=build_fixture_db(path, bsb=True))


@pytest.fixture
async def fixture_db(bsb_fixture_file, monkeypatch):
    database = await _open(bsb_fixture_file.path, monkeypatch)
    yield database
    await database.close()


async def _call(tool: str, **arguments) -> str:
    response = await server.call_tool(tool, arguments)
    assert not response[0].text.startswith("Error:"), response[0].text
    return response[0].text


async def test_search_by_strongs_shows_bsb(fixture_db):
    output = await _call("search_by_strongs", strongs="G26", limit=3)
    assert output.startswith("## Verses with G26 (ἀγάπη - agapē) (BSB)\n\n*love, goodwill*")
    assert "**1Jn.4.2**: Beloved, let us love one another (BSB test text 1 John 4:2)." in output
    assert "**1Jn.4.3**: [gloss] Beloved, love is from God (test text 1 John 4:3)." in output
    assert "(test text 1 John 4:2)" not in output


async def test_word_study_example_passages_show_bsb(fixture_db):
    output = await _call("word_study", strongs="G26")
    assert "## Example Passages (BSB)\n" in output
    assert "**1Jn.4.2**: Beloved, let us love one another (BSB test text 1 John 4:2)." in output


async def test_graph_enriched_search_shows_bsb_or_the_marked_gloss(fixture_db):
    output = await _call("graph_enriched_search", reference="Genesis 22:1")
    assert output.startswith("## Genesis 22:1 (BSB)\n\nSome time later God tested Abraham (BSB test text).")
    assert "**Original**: וַיְהִי אַחַר" in output
    fallback = await _call("graph_enriched_search", reference="Genesis 22:2")
    assert fallback.startswith("## Genesis 22:2\n\n[gloss] Take your son to the land of Moriah (test text).")


async def test_similar_passages_show_bsb_source_and_previews(fixture_db, bsb_fixture_file):
    if not (bsb_fixture_file.vectors and fixture_db._vec_loaded):
        pytest.skip("sqlite-vec unavailable, so the fixture has no vector tables")
    output = await _call("find_similar_passages", reference="John 3:16", limit=2)
    assert output.startswith(
        "## Passages Similar to John 3:16 (BSB)\n\n"
        "**Source**: For God so loved the world that He gave His Son (BSB test text)."
    )
    assert output.count("(BSB)") == 1
    # 1 John 4:1's BSB preview is cut at 500 characters; 4:2 is shown whole.
    assert "Beloved, test the spirits (BSB test text 1 John 4:1). Bel" in output
    assert output.count("(BSB test text 1 John 4:1)") == 9
    assert "Beloved, let us love one another (BSB test text 1 John 4:2)." in output
    assert "Long passage text" not in output


# ---------------------------------------------------------------------------
# bsb.txt parser and importer
# ---------------------------------------------------------------------------

SAMPLE = (
    "﻿Test preamble: this test text has been dedicated to the public domain.\t\r\n"
    "Verse\tBerean Standard Bible\r\n"
    "Genesis 1:1\tIn the beginning (test text).\r\n"
    "Psalm 23:1\tThe LORD is my shepherd (test text).\r\n"
    "Song of Solomon 1:1\tThe song of songs (test text).\r\n"
    "Matthew 17:21\t\r\n"
    "1 John 4:8\tGod is love (test text). \r\n"
    "\r\n"
)
SAMPLE_ROWS = [
    ("Gen.1.1", "Gen", 1, 1, "In the beginning (test text)."),
    ("Psa.23.1", "Psa", 23, 1, "The LORD is my shepherd (test text)."),
    ("Sng.1.1", "Sng", 1, 1, "The song of songs (test text)."),
    ("1Jn.4.8", "1Jn", 4, 8, "God is love (test text)."),
]


def test_parse_reads_verses_and_skips_omitted_ones():
    preamble, rows = bsb.parse_bsb_text(SAMPLE)
    assert preamble == [
        "Test preamble: this test text has been dedicated to the public domain.",
        "Verse\tBerean Standard Bible",
    ]
    assert rows == SAMPLE_ROWS


@pytest.mark.parametrize("text, message", [
    ("Genesis 1:1\tA.\nGenesis 1:1\tB.\n", "Gen.1.1 appears twice"),
    ("Genesis 1:1\tA.\nTobit 1:1\tB.\n", "unknown book 'Tobit'"),
    ("Genesis 1:1\tA.\nA trailing note\n", "Line 2 is not a verse"),
])
def test_parse_rejects_malformed_files(text, message):
    with pytest.raises(ValueError, match=message):
        bsb.parse_bsb_text(text)


@pytest.fixture
def sample_file(tmp_path, monkeypatch):
    path = tmp_path / "bsb.txt"
    path.write_bytes(SAMPLE.encode())
    monkeypatch.setattr(bsb, "BSB_SHA256", hashlib.sha256(path.read_bytes()).hexdigest())
    monkeypatch.setattr(bsb, "BSB_EXPECTED_VERSES", len(SAMPLE_ROWS))
    return path


def _schema_conn(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    create_schema(conn)
    return conn


def test_schema_matches_the_production_table(tmp_path):
    conn = _schema_conn(tmp_path / "schema.db")
    columns = [row[1:4] for row in conn.execute("PRAGMA table_info(bsb_verses)")]
    assert columns == [
        ("reference", "TEXT", 1), ("book", "TEXT", 1), ("chapter", "INTEGER", 0),
        ("verse", "INTEGER", 0), ("text", "TEXT", 1),
    ]
    indexes = {row[1]: row[2] for row in conn.execute("PRAGMA index_list(bsb_verses)")}
    assert indexes["idx_bsb_ref"] == 0 and 1 in indexes.values()  # plus UNIQUE(reference)
    create_schema(conn)  # idempotent on an existing table


def test_import_writes_rows_in_file_order_and_is_repeatable(tmp_path, sample_file):
    conn = _schema_conn(tmp_path / "import.db")
    assert bsb.import_bsb(conn, sample_file) == len(SAMPLE_ROWS)
    assert bsb.import_bsb(conn, sample_file) == len(SAMPLE_ROWS)
    assert conn.execute(
        "SELECT reference, book, chapter, verse, text FROM bsb_verses ORDER BY rowid"
    ).fetchall() == SAMPLE_ROWS


def _assert_import_refused(conn, path, message):
    before = conn.execute("SELECT * FROM bsb_verses").fetchall()
    with pytest.raises(ValueError, match=message):
        bsb.import_bsb(conn, path)
    assert conn.execute("SELECT * FROM bsb_verses").fetchall() == before


def test_import_refuses_unpinned_changed_unlicensed_or_short_files(tmp_path, sample_file, monkeypatch):
    conn = _schema_conn(tmp_path / "refuse.db")
    bsb.import_bsb(conn, sample_file)

    changed = tmp_path / "changed.txt"
    changed.write_bytes(SAMPLE.replace("love", "light").encode())
    _assert_import_refused(conn, changed, "Checksum mismatch")

    unlicensed = tmp_path / "unlicensed.txt"
    unlicensed.write_bytes(SAMPLE.replace("public domain", "test domain").encode())
    monkeypatch.setattr(bsb, "BSB_SHA256", hashlib.sha256(unlicensed.read_bytes()).hexdigest())
    _assert_import_refused(conn, unlicensed, "public-domain dedication")

    monkeypatch.setattr(bsb, "BSB_SHA256", hashlib.sha256(sample_file.read_bytes()).hexdigest())
    monkeypatch.setattr(bsb, "BSB_EXPECTED_VERSES", 31_086)
    _assert_import_refused(conn, sample_file, "has 4 verses; expected 31086")

    monkeypatch.setattr(bsb, "BSB_SHA256", None)
    _assert_import_refused(conn, sample_file, "BSB_SHA256 is not set")


def test_production_pin_is_unset_until_reviewed():
    # Flip this test when the owner pins the reviewed file.
    assert bsb.BSB_SHA256 is None
    assert bsb.BSB_SOURCE_URL == "https://bereanbible.com/bsb.txt"


# ---------------------------------------------------------------------------
# scripts/download_bsb.py
# ---------------------------------------------------------------------------


def _load_download_script():
    path = Path(__file__).resolve().parent.parent / "scripts" / "download_bsb.py"
    spec = importlib.util.spec_from_file_location("download_bsb", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _client(content: bytes, requests: list) -> httpx.Client:
    def handler(request):
        requests.append(str(request.url))
        return httpx.Response(200, content=content)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_download_refuses_without_a_pin_before_any_request(tmp_path, monkeypatch):
    module = _load_download_script()
    monkeypatch.setattr(bsb, "BSB_SHA256", None)
    requests: list = []
    with pytest.raises(RuntimeError, match="BSB_SHA256 is not set"):
        module.download_bsb(_client(SAMPLE.encode(), requests), tmp_path, force=False)
    assert requests == []
    assert not (tmp_path / "bsb.txt").exists()


def test_download_writes_only_a_verified_file(tmp_path, sample_file):
    module = _load_download_script()
    target = tmp_path / "data"
    requests: list = []
    with pytest.raises(RuntimeError, match="Nothing was written"):
        module.download_bsb(_client(b"changed upstream", requests), target, force=False)
    assert not (target / "bsb.txt").exists()

    manifest = module.download_bsb(_client(SAMPLE.encode(), requests), target, force=False)
    assert requests == [bsb.BSB_SOURCE_URL] * 2
    assert (target / "bsb.txt").read_bytes() == SAMPLE.encode()
    assert manifest == {
        "source_url": bsb.BSB_SOURCE_URL,
        "sha256": hashlib.sha256(SAMPLE.encode()).hexdigest(),
        "bytes": len(SAMPLE.encode()),
        "license": bsb.BSB_LICENSE,
    }

    (target / "bsb.txt").write_bytes(b"locally edited")
    with pytest.raises(RuntimeError, match="left in place"):
        module.download_bsb(_client(SAMPLE.encode(), requests), target, force=False)
    assert (target / "bsb.txt").read_bytes() == b"locally edited"
    assert len(requests) == 2
