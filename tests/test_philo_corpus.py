"""Philo corpus: First1KGreek Greek/English pairing, import, citations, tools, download."""

import sqlite3
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from study_bible_mcp import server
from study_bible_mcp.corpora import CORPORA, combined_license, philo, resolve_citation
from study_bible_mcp.corpora.download import git_blob_sha1
from study_bible_mcp.corpora.philo import parse_philo_work
from study_bible_mcp.database import StudyBibleDB, create_schema
from study_bible_mcp.parsers.ancient_sources import import_corpus

LICENCE = (
    '<licence target="https://creativecommons.org/licenses/by-sa/4.0/">'
    "Available under a Creative Commons Attribution-ShareAlike 4.0 International License</licence>"
)
TEI = """<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <teiHeader><fileDesc><publicationStmt><availability>{licence}</availability>
  </publicationStmt></fileDesc></teiHeader>
  <text><body><div type="{kind}" n="urn:cts:greekLit:tlg0018.{work}">{body}</div></body></text>
</TEI>
"""


def _section(n, body):
    return f'<div type="textpart" subtype="section" n="{n}">{body}</div>'


OPIF_GREEK = (
    "<head>ΠΕΡΙ ΤΗΣ ΚΟΣΜΟΠΟΙΙΑΣ</head>"
    + _section(1, '<note type="marginal">I p. 1 M.</note><p><milestone unit="altref" n="1"/>'
                  "Τῶν ἄλλων νομοθετῶν <lb n=\"5\"/>οἱ μὲν ἀκαλλώπιστα.</p>"
                  '<note type="footnote">apparatus criticus</note>')
    + _section(2, "<p>Μωυσῆς δ’ ἑκάτερον ὑπερβάς.</p>")
    + _section(26, "<p>„ἐν ἀρχῇ ἐποίησεν ὁ θεὸς τὸν οὐρανὸν καὶ τὴν γῆν“ καὶ ὁ θεῖος λόγος.</p>")
)
OPIF_ENGLISH = (
    "<head><title>A TREATISE ON THE CREATION</title></head>"
    + _section(1, '<head>OF MOSES THE LAWGIVER.</head><p><milestone unit="chapter" n="1"/>'
                  "Of other lawgivers, some have set forth<note>Yonge footnote</note> "
                  "what they considered just.</p>")
    + _section(2, '<p>But Moses, rejecting <pb n="v.1.p.2"/>both of these methods.</p>')
    + _section(26, "<p>Moses says also; In the beginning God created the heaven and the earth: "
                   "and the divine word.</p>")
)


def _book(n, body, head=""):
    return f'<div type="textpart" subtype="book" n="{n}">{head}{body}</div>'


SPEC_GREEK = (
    _book(1, _section(1, "<p>Τὰ γένη τῶν ἐν μέρει νόμων.</p>") + _section(2, "<p>Χλευάζεται.</p>"))
    + _book(2, _section(1, "<p>Ἐν μὲν τῇ πρὸ ταύτης συντάξει.</p>")
            + _section(124, "<p>Ταῦτα περὶ τῆς ἑβδόμης.</p>"))
)
SPEC_ENGLISH = (
    _book(1, _section(1, "<p>The genera and heads of all special laws.</p>")
          + _section(2, "<p>The ordinance of circumcision is ridiculed.</p>"))
    + _book(2, _section(1, "<p>In the treatise preceding the present one.</p>"),
            head="<head>A TREATISE ON THE SPECIAL LAWS.</head>")
)


def _write(directory: Path, work_id: str, greek: str, english: str, licence: str = LICENCE) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"tlg0018.{work_id}.1st1K-grc1.xml").write_text(
        TEI.format(licence=licence, kind="edition", work=work_id, body=greek), encoding="utf-8"
    )
    (directory / f"tlg0018.{work_id}.1st1K-eng1.xml").write_text(
        TEI.format(licence=licence, kind="translation", work=work_id, body=english), encoding="utf-8"
    )


def _fixture(directory: Path) -> Path:
    _write(directory, "tlg001", OPIF_GREEK, OPIF_ENGLISH)
    _write(directory, "tlg024", SPEC_GREEK, SPEC_ENGLISH)
    return directory


def _fixture_rows(directory: Path) -> list[dict]:
    return parse_philo_work(directory, "tlg001") + parse_philo_work(directory, "tlg024")


# --- Parser


def test_pairs_each_greek_section_with_the_same_english_section(tmp_path):
    rows = parse_philo_work(_fixture(tmp_path), "tlg001")

    assert [(r["reference"], r["sort_start"], r["sort_end"]) for r in rows] == [
        ("Opif. 1", 1, 1), ("Opif. 2", 2, 2), ("Opif. 26", 26, 26),
    ]
    assert rows[0]["original_text"] == "Τῶν ἄλλων νομοθετῶν οἱ μὲν ἀκαλλώπιστα."
    assert rows[0]["text"] == "Of other lawgivers, some have set forth what they considered just."
    assert rows[1]["original_text"] == "Μωυσῆς δ’ ἑκάτερον ὑπερβάς."
    assert rows[1]["text"] == "But Moses, rejecting both of these methods."
    assert rows[0]["editorial_heading"] == "OF MOSES THE LAWGIVER."
    assert rows[1]["editorial_heading"] is None


def test_notes_headings_and_markers_stay_out_of_text(tmp_path):
    rows = parse_philo_work(_fixture(tmp_path), "tlg001")

    combined = " ".join(r["text"] + r["original_text"] for r in rows)
    for excluded in ("apparatus", "I p. 1 M.", "footnote", "ΚΟΣΜΟΠΟΙΙΑΣ", "TREATISE", "LAWGIVER"):
        assert excluded not in combined


def test_licences_editions_and_periods(tmp_path):
    rows = parse_philo_work(_fixture(tmp_path), "tlg001")

    for row in rows:
        assert row["original_license"] == row["translation_license"] == "CC BY-SA 4.0"
        assert row["license"] == combined_license("CC BY-SA 4.0", "CC BY-SA 4.0", "Greek")
        assert row["period_tags"] == "second_temple,roman"
        assert row["author"] == "Philo of Alexandria"
    assert rows[0]["edition"].startswith("Cohn–Wendland, Philonis Alexandrini opera quae supersunt, vol. 1")
    assert rows[0]["translation"] == "C. D. Yonge, The Works of Philo Judaeus, vol. 1 (London: Bohn, 1854)"
    assert philo.COMMIT in rows[0]["source_url"] and rows[0]["source_url"].endswith("/tlg001")


def test_multi_book_work_uses_book_section_and_keeps_greek_only_sections(tmp_path):
    rows = parse_philo_work(_fixture(tmp_path), "tlg024")

    assert [(r["reference"], r["sort_start"]) for r in rows] == [
        ("Spec. 1.1", 1001), ("Spec. 1.2", 1002), ("Spec. 2.1", 2001), ("Spec. 2.124", 2124),
    ]
    greek_only = rows[-1]
    assert {"text", "translation", "translation_license"}.isdisjoint(greek_only)
    assert greek_only["original_text"] == "Ταῦτα περὶ τῆς ἑβδόμης."
    assert greek_only["license"] == "CC BY-SA 4.0"
    assert rows[2]["editorial_heading"] == "A TREATISE ON THE SPECIAL LAWS."


@pytest.mark.parametrize("greek, english, message", [
    (OPIF_GREEK, OPIF_ENGLISH + _section(27, "<p>extra</p>"), "have no Greek section"),
    (OPIF_GREEK + _section(3, "<p>out of order</p>"), OPIF_ENGLISH, "out of order"),
    (OPIF_GREEK + _section(26, "<p>again</p>"), OPIF_ENGLISH, "duplicate section"),
    (OPIF_GREEK.replace('n="2"', 'n="2a"'), OPIF_ENGLISH, "unexpected section label"),
    (OPIF_GREEK, OPIF_ENGLISH.replace("But Moses, rejecting", "").replace(
        "both of these methods.", ""), "empty English section"),
])
def test_malformed_sources_fail(tmp_path, greek, english, message):
    _write(tmp_path, "tlg001", greek, english)

    with pytest.raises(ValueError, match=message):
        parse_philo_work(tmp_path, "tlg001")


def test_missing_licence_fails(tmp_path):
    _write(tmp_path, "tlg001", OPIF_GREEK, OPIF_ENGLISH, licence="<licence>none</licence>")

    with pytest.raises(ValueError, match="CC BY-SA 4.0"):
        parse_philo_work(tmp_path, "tlg001")


def test_book_division_in_single_book_work_fails(tmp_path):
    _write(tmp_path, "tlg001", _book(1, OPIF_GREEK), OPIF_ENGLISH)

    with pytest.raises(ValueError, match="unexpected book division"):
        parse_philo_work(tmp_path, "tlg001")


def test_require_files_names_every_missing_file(tmp_path):
    _fixture(tmp_path)

    with pytest.raises(FileNotFoundError) as error:
        CORPORA["philo"].require_files(tmp_path)

    message = str(error.value)
    assert "tlg0018.tlg002.1st1K-grc1.xml" in message and "tlg0018.tlg031.1st1K-eng1.xml" in message
    assert "tlg0018.tlg001.1st1K-grc1.xml" not in message
    assert len(philo.PHILO_TEI_FILES) == 62


# --- Import


LINKS = (
    ("opif", "26", "Gen", 1, 1, 1, 1, "Quotes and expounds: the creation of heaven and earth"),
    ("spec", "1.2", "Gen", 17, 10, 17, 14, "Expounds: the ordinance of circumcision"),
)


@pytest.fixture
def fixture_corpus(tmp_path, monkeypatch):
    directory = _fixture(tmp_path / "philo")
    corpus = replace(
        CORPORA["philo"], parse=_fixture_rows, require_files=lambda directory: None
    )
    monkeypatch.setitem(CORPORA, "philo", corpus)
    monkeypatch.setattr(philo, "_BIBLICAL_LINKS", LINKS)
    return directory


def _counts(conn):
    return [
        conn.execute(f"SELECT COUNT(*) FROM {table} {where}").fetchone()[0]
        for table, where in (
            ("ancient_source_passages", "WHERE corpus = 'philo'"),
            ("ancient_source_passages_fts", ""),
            ("ancient_source_biblical_links", ""),
        )
    ]


def _db(tmp_path, directory) -> Path:
    path = tmp_path / "philo.db"
    conn = sqlite3.connect(path)
    create_schema(conn)
    import_corpus(conn, "philo", directory)
    conn.close()
    return path


def test_import_is_idempotent_and_resolves_links(tmp_path, fixture_corpus):
    conn = sqlite3.connect(tmp_path / "philo.db")
    create_schema(conn)

    assert import_corpus(conn, "philo", fixture_corpus) == 7
    assert import_corpus(conn, "philo", fixture_corpus) == 7
    linked = conn.execute(
        """SELECT p.reference, l.biblical_book, l.sort_start, l.sort_end
           FROM ancient_source_biblical_links l JOIN ancient_source_passages p ON p.id = l.passage_id
           ORDER BY p.reference"""
    ).fetchall()

    assert _counts(conn) == [7, 7, 2]
    assert linked == [("Opif. 26", "Gen", 1001, 1001), ("Spec. 1.2", "Gen", 17010, 17014)]
    stored = conn.execute(
        "SELECT work_title, original_language FROM ancient_source_passages WHERE reference = 'Opif. 1'"
    ).fetchone()
    assert stored == ("On the Creation of the World", "Greek")


def test_unresolved_link_fails_import(tmp_path, fixture_corpus, monkeypatch):
    monkeypatch.setattr(philo, "_BIBLICAL_LINKS", (("opif", "99", "Gen", 1, 1, 1, 1, "x"),))
    conn = sqlite3.connect(tmp_path / "philo.db")
    create_schema(conn)

    with pytest.raises(ValueError, match="does not resolve"):
        import_corpus(conn, "philo", fixture_corpus)


def test_curated_links_target_registered_works_and_valid_books():
    from study_bible_mcp.database import BOOK_ABBREV_MAP

    keys = {work.key for work in CORPORA["philo"].works}
    books = set(BOOK_ABBREV_MAP.values())
    for work_key, locator, book, *_rest, note in philo._BIBLICAL_LINKS:
        work = CORPORA["philo"].work(work_key)
        assert work_key in keys and book in books and note
        assert work.locator.parse(locator) is not None


# --- Citations


def test_every_work_resolves_by_short_title_full_title_and_aliases():
    for work in CORPORA["philo"].works:
        locator = "1.1" if work.locator is philo.BOOK_SECTION else "1"
        for name in work.names:
            resolution = resolve_citation(f"{name} {locator}", CORPORA.values())
            assert resolution.status == "ok", (name, resolution)
            assert (resolution.match.corpus.key, resolution.match.work.key) == ("philo", work.key)


@pytest.mark.parametrize("citation, expected", [
    ("Opif. 1", ("opif", (1, 1))),
    ("Philo, Legat. 299", ("legat", (299, 299))),
    ("Philo of Alexandria, Opif. 26", ("opif", (26, 26))),
    ("Leg. 1.31", ("leg", (1031, 1031))),
    ("Leg. 3", ("leg", (3000, 3999))),
    ("Spec. 1.1-2.1", ("spec", (1001, 2001))),
    ("Leg. Gai. 299", ("legat", (299, 299))),
    ("Somn. 1.3", ("somn", (1003, 1003))),
    ("Life of Moses 1.65", ("mos", (1065, 1065))),
    ("Heres 205", ("her", (205, 205))),
    ("Gig. 6-7", ("gig", (6, 7))),
])
def test_resolves_philo_citations(citation, expected):
    resolution = resolve_citation(citation, CORPORA.values())

    assert resolution.status == "ok", resolution
    assert (resolution.match.work.key, resolution.match.sort_range) == expected


def test_book_section_grammar_rejects_bare_sections_of_multi_book_works():
    assert resolve_citation("Spec. 1.2.3", CORPORA.values()).status == "bad_locator"


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
async def test_lookup_returns_paired_greek_and_english(tmp_path, fixture_corpus, monkeypatch):
    path = _db(tmp_path, fixture_corpus)
    lookup = server.handle_lookup_ancient_source

    opif = await _call(path, monkeypatch, lookup, citation="Philo, Opif. 26")
    greek_only = await _call(path, monkeypatch, lookup, citation="Spec. 2.124")

    assert opif.startswith("## Opif. 26")
    assert "*Not Scripture · Hellenistic Jewish philosophy (c. AD 20–50) · tier A ·" in opif
    assert "- Philo: Not Scripture; not Christian." in opif and "License: CC BY-SA 4.0." in opif
    assert "In the beginning God created the heaven and the earth" in opif
    assert "ἐν ἀρχῇ ἐποίησεν" in opif
    assert "- Echo: Gen 1:1 — Quotes and expounds" in opif
    assert "No English translation included" in greek_only
    assert "Ταῦτα περὶ τῆς ἑβδόμης" in greek_only


@pytest.mark.asyncio
async def test_search_folds_greek_and_stems_english(tmp_path, fixture_corpus, monkeypatch):
    path = _db(tmp_path, fixture_corpus)
    search = server.handle_search_ancient_sources

    for query in ("λόγος", "λογος", "ΛΟΓΟΣ", "divine word"):
        result = await _call(path, monkeypatch, search, query=query, corpus="philo")
        assert "Opif. 26" in result, query
    transliterated = await _call(path, monkeypatch, search, query="logos", corpus="philo")
    assert transliterated.startswith("No Philo passage contains")


# --- Download


def test_download_verifies_pinned_blobs_and_licence(tmp_path, monkeypatch):
    good = TEI.format(licence=LICENCE, kind="edition", work="tlg001", body="").encode()
    unlicensed = TEI.format(licence="", kind="translation", work="tlg001", body="").encode()
    treatise = philo.TREATISES["tlg001"]
    monkeypatch.setattr(philo, "TREATISES", {"tlg001": replace(
        treatise, greek_blob=git_blob_sha1(good), english_blob=git_blob_sha1(unlicensed),
    )})
    served = {"grc1": good, "eng1": unlicensed}

    def handler(request: httpx.Request) -> httpx.Response:
        assert philo.COMMIT in request.url.path and "api.github.com" not in str(request.url)
        return httpx.Response(200, content=served[request.url.path.rsplit("-", 1)[1][:4]])

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RuntimeError, match="CC BY-SA 4.0 declaration"):
            philo.download(client, tmp_path, force=False)
        served["eng1"] = good
        with pytest.raises(RuntimeError, match="Checksum mismatch"):
            philo.download(client, tmp_path, force=False)

    assert (tmp_path / "tlg0018.tlg001.1st1K-grc1.xml").read_bytes() == good
    assert not (tmp_path / "tlg0018.tlg001.1st1K-eng1.xml").exists()
