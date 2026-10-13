"""Rabbinic corpus (the Mishnah): text cleaning, parsing, import, citations, tools, download."""

import json
import sqlite3
from pathlib import Path

import httpx
import pytest

from study_bible_mcp import server
from study_bible_mcp.corpora import CORPORA, combined_license, rabbinic, resolve_citation
from study_bible_mcp.corpora.download import git_blob_sha1
from study_bible_mcp.corpora.rabbinic import clean_html
from study_bible_mcp.database import StudyBibleDB, create_schema
from study_bible_mcp.parsers.ancient_sources import import_corpus

CORPUS = CORPORA["rabbinic"]

SHEKALIM = "Mishnah/Seder Moed/Mishnah Shekalim"
SHEKALIM_HEBREW = "באחד באדר משמיעין על השקלים"


def _version(title, license_, text, language="en"):
    return {"versionTitle": title, "license": license_, "language": language, "text": text}


FILES = {
    f"{SHEKALIM}/Hebrew/Mishnah, ed. Romm, Vilna 1913.json": _version(
        "Mishnah, ed. Romm, Vilna 1913", "Public Domain",
        [[f"<b>{SHEKALIM_HEBREW}</b>", "ב", "שולחנות היו יושבין במדינה"]], "he"),
    f"{SHEKALIM}/English/Mishnah Yomit by Dr. Joshua Kulp.json": _version(
        "Mishnah Yomit by Dr. Joshua Kulp", "CC-BY",
        [["On the first of Adar they announce the shekels.<br>Second line.", "Two.",
          "They set up tables of money changers."], ["An English-only mishnah."]]),
}


@pytest.fixture
def fixture_dir(tmp_path, monkeypatch):
    directory = tmp_path / "rabbinic"
    blobs = []
    for path, version in FILES.items():
        content = json.dumps(version, ensure_ascii=False).encode()
        (directory / "sefaria" / path).parent.mkdir(parents=True, exist_ok=True)
        (directory / "sefaria" / path).write_bytes(content)
        blobs.append(f"{git_blob_sha1(content)}  {path}")
    monkeypatch.setattr(rabbinic, "_SEFARIA_BLOBS", "\n".join(blobs))
    monkeypatch.setattr(
        rabbinic, "SOURCES", tuple(source for source in rabbinic.SOURCES if source.work.key == "mishnah_shekalim")
    )
    monkeypatch.setattr(rabbinic, "_BIBLICAL_LINKS", (
        ("mishnah_shekalim", "1:1", "Mat", 17, 24, 17, 27, "Related account: half-shekel"),
    ))
    return directory


def _rows(directory):
    return {row["reference"]: row for row in rabbinic.parse(directory)}


# --- Text cleaning


def test_clean_html_drops_tags_and_footnotes_but_keeps_editorial_brackets():
    raw = 'A <b>bold</b><sup class="footnote-marker">1</sup><i class="footnote">x <i>y</i></i> b.<br><Behold> &amp; c'
    assert clean_html(raw, "t") == "A bold b.\n<Behold> & c"
    assert clean_html("word<sup>*</sup><i class=\"footnote\">gloss</i> end", "t") == "word end"


@pytest.mark.parametrize("raw, message", [
    ('a<i class="footnote">open <i>x</i> b', "unbalanced"),
    ('a<sup class="footnote-marker">1</sup><i class="footnote">note<i>x</i>', "unbalanced"),
])
def test_clean_html_rejects_footnotes_that_would_swallow_text(raw, message):
    with pytest.raises(ValueError, match=message):
        clean_html(raw, "t")


# --- Parsing


def test_parse_pairs_versions_with_licences(fixture_dir):
    rows = _rows(fixture_dir)
    shekalim = rows["Mishnah Shekalim 1:1"]

    assert shekalim["text"] == "On the first of Adar they announce the shekels.\nSecond line."
    assert shekalim["original_text"] == SHEKALIM_HEBREW
    assert (shekalim["sort_start"], shekalim["sort_end"]) == (1001, 1001)
    assert shekalim["edition"] == "Mishnah, ed. Romm, Vilna 1913"
    assert shekalim["translation"] == "Mishnah Yomit by Dr. Joshua Kulp"
    assert shekalim["original_license"] == "Public domain"
    assert shekalim["translation_license"] == "CC BY 3.0"
    assert shekalim["license"] == combined_license("Public domain", "CC BY 3.0", "Hebrew")
    assert shekalim["period_tags"] == "tannaitic" and shekalim["author"] == "Mishnah"

    english_only = rows["Mishnah Shekalim 2:1"]
    assert "original_text" not in english_only and english_only["license"] == "CC BY 3.0"
    assert english_only["edition"] == "Mishnah, ed. Romm, Vilna 1913 (lacks this passage)"


def test_parse_rejects_versions_without_an_open_licence(fixture_dir):
    path = fixture_dir / "sefaria" / f"{SHEKALIM}/English/Mishnah Yomit by Dr. Joshua Kulp.json"
    version = json.loads(path.read_text())
    path.write_text(json.dumps({**version, "license": "unknown"}))

    with pytest.raises(ValueError, match="not an open licence"):
        list(rabbinic.parse(fixture_dir))


def test_require_files_names_every_missing_file(fixture_dir):
    CORPUS.require_files(fixture_dir)
    (fixture_dir / "sefaria" / f"{SHEKALIM}/English/Mishnah Yomit by Dr. Joshua Kulp.json").unlink()

    with pytest.raises(FileNotFoundError) as error:
        CORPUS.require_files(fixture_dir)
    assert "Mishnah Shekalim/English/Mishnah Yomit by Dr. Joshua Kulp.json" in str(error.value)


def test_registered_pins_cover_every_mishnah_tractate_and_nothing_else():
    pins = rabbinic._sefaria_pins()
    for source in rabbinic.SOURCES:
        assert rabbinic._pinned_version(pins, source.directory, "Hebrew"), source.work.key
        assert rabbinic._pinned_version(pins, source.directory, "English"), source.work.key
    assert len(rabbinic.WORKS) == 63 and len(pins) == 126
    assert all(path.startswith("Mishnah/") for path in pins)
    assert {work.collection.title for work in rabbinic.WORKS} == {"Mishnah"}
    assert CORPUS.periods == ("tannaitic",)


# --- Import


def _import(fixture_dir, tmp_path):
    conn = sqlite3.connect(tmp_path / "rabbinic.db")
    create_schema(conn)
    count = import_corpus(conn, "rabbinic", fixture_dir)
    return conn, count


def test_import_is_idempotent_and_resolves_links(fixture_dir, tmp_path):
    conn, count = _import(fixture_dir, tmp_path)
    again = import_corpus(conn, "rabbinic", fixture_dir)
    links = conn.execute(
        """SELECT p.reference, l.biblical_book, l.sort_start FROM ancient_source_biblical_links l
           JOIN ancient_source_passages p ON p.id = l.passage_id ORDER BY p.reference"""
    ).fetchall()

    assert count == again == len(_rows(fixture_dir))
    assert conn.execute("SELECT COUNT(*) FROM ancient_source_passages").fetchone() == (count,)
    assert links == [("Mishnah Shekalim 1:1", "Mat", 17024)]


def test_import_fails_on_an_unresolved_link(fixture_dir, tmp_path, monkeypatch):
    monkeypatch.setattr(rabbinic, "_BIBLICAL_LINKS", (
        ("mishnah_shekalim", "9:1", "Mat", 17, 24, 17, 27, "x"),
    ))
    with pytest.raises(ValueError, match="does not resolve"):
        _import(fixture_dir, tmp_path)


def test_curated_links_point_only_into_the_mishnah():
    work_keys = {work.key for work in rabbinic.WORKS}
    assert {link[0] for link in rabbinic._BIBLICAL_LINKS} <= work_keys


# --- Citations


@pytest.mark.parametrize("citation, work, sort_range", [
    ("Mishnah Shekalim 1:1", "mishnah_shekalim", (1001, 1001)),
    ("m. Shek. 1:1", "mishnah_shekalim", (1001, 1001)),
    ("Shekalim 1:1", "mishnah_shekalim", (1001, 1001)),
    ("Mishnah Menachot 13:22", "mishnah_menachot", (13022, 13022)),
    ("Mishnah Pirkei Avot 1:1", "mishnah_pirkei_avot", (1001, 1001)),
    ("Avot 1:1", "mishnah_pirkei_avot", (1001, 1001)),
    ("Kelim 1:1", "mishnah_kelim", (1001, 1001)),
    ("Ta'anit 2:1", "mishnah_taanit", (2001, 2001)),
    ("m. B. Bat. 1:1", "mishnah_bava_batra", (1001, 1001)),
])
def test_resolves_mishnah_citations(citation, work, sort_range):
    resolution = resolve_citation(citation, [CORPUS])

    assert resolution.status == "ok", citation
    assert (resolution.match.work.key, resolution.match.sort_range) == (work, sort_range)


@pytest.mark.parametrize("citation, status", [
    ("Tosefta Menahot 13:22", "unknown_work"),
    ("t. Men. 13:4", "unknown_work"),
    ("b. Sanh. 43a", "unknown_work"),
    ("Bavli Bava Batra 3b", "unknown_work"),
    ("Bava Batra 3b-4a", "bad_locator"),
    ("Pes. 57a:8", "bad_locator"),
])
def test_tosefta_talmud_and_midrash_citations_do_not_resolve(citation, status):
    assert resolve_citation(citation, [CORPUS]).status == status


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
async def test_lookup_and_search_tools(fixture_dir, tmp_path, monkeypatch):
    conn, _ = _import(fixture_dir, tmp_path)
    conn.close()
    path = tmp_path / "rabbinic.db"
    lookup, search = server.handle_lookup_ancient_source, server.handle_search_ancient_sources

    shekalim = await _call(path, monkeypatch, lookup, citation="Mishnah Shekalim 1:1")
    folded = await _call(path, monkeypatch, search, query="הַשְּׁקָלִים", corpus="rabbinic")
    english = await _call(path, monkeypatch, search, query="money changers", corpus="rabbinic")

    assert shekalim.startswith("## Mishnah Shekalim 1:1")
    assert "License: Hebrew text: Public domain; English translation: CC BY 3.0." in shekalim
    assert "- Shared tradition: Matt 17:24–27 — Related account" in shekalim
    assert "Where the NT evaluates these traditions" in shekalim
    assert "Kulp's bracketed Bible references sometimes use Hebrew numbering or contain errors." in shekalim
    assert "*Not Scripture · Mishnah (redacted c. AD 200; pre-70 attributions unverified) · tier B ·" in shekalim
    assert "Mishnah Shekalim 1:1" in folded
    assert "Mishnah Shekalim 1:3" in english


# --- Download


def test_download_verifies_pins_and_licences(tmp_path, monkeypatch):
    version = json.dumps(_version("Mishnah Yomit by Dr. Joshua Kulp", "CC-BY", [["x"]])).encode()
    closed = json.dumps(_version("Closed", "unknown", [["x"]])).encode()
    path = f"{SHEKALIM}/English/Mishnah Yomit by Dr. Joshua Kulp.json"
    monkeypatch.setattr(rabbinic, "_SEFARIA_BLOBS", f"{git_blob_sha1(version)}  {path}")

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith(rabbinic.ARCHIVE_RAW_URL)
        return httpx.Response(200, content=served)

    served = version
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        manifest = CORPUS.download(client, tmp_path, False)

    assert manifest["commit"] == rabbinic.ARCHIVE_COMMIT
    assert manifest["files"] == {f"sefaria/{path}": {
        "git_blob_sha1": git_blob_sha1(version),
        "bytes": len(version),
        "license": "CC BY 3.0",
        "source_url": f"https://github.com/{rabbinic.ARCHIVE_REPOSITORY}/blob/{rabbinic.ARCHIVE_COMMIT}/json/"
        "Mishnah/Seder%20Moed/Mishnah%20Shekalim/English/Mishnah%20Yomit%20by%20Dr.%20Joshua%20Kulp.json",
    }}

    served = closed
    monkeypatch.setattr(rabbinic, "_SEFARIA_BLOBS", f"{git_blob_sha1(closed)}  {path}")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RuntimeError, match="not an open licence"):
            CORPUS.download(client, tmp_path / "closed", False)
        with pytest.raises(RuntimeError, match="Checksum mismatch"):
            monkeypatch.setattr(rabbinic, "_SEFARIA_BLOBS", f"{'0' * 40}  {path}")
            CORPUS.download(client, tmp_path / "tampered", True)
