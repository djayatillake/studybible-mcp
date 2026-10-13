import importlib.util
import sqlite3
from pathlib import Path

import pytest

from study_bible_mcp import server
from study_bible_mcp.database import StudyBibleDB, create_schema
from study_bible_mcp.corpora import CORPORA, josephus
from study_bible_mcp.corpora.josephus import parse_josephus_work
from study_bible_mcp.parsers.ancient_sources import import_josephus
from study_bible_mcp.tools import format_ancient_source_results


TEI_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <teiHeader><fileDesc><publicationStmt><availability>
    <licence target="https://creativecommons.org/licenses/by-sa/4.0/">CC BY-SA 4.0</licence>
  </availability></publicationStmt></fileDesc></teiHeader>
  <text><body><div type="{kind}">{body}</div></body></text>
</TEI>
"""

ANTIQUITIES_ENGLISH = """
<div type="textpart" subtype="book" n="18">
  <head>Book XVIII</head>
  <div type="textpart" subtype="section" n="116">
    <milestone n="5" unit="Whiston_chapter"/><milestone n="2" unit="Whiston_section"/>
    <head>HOW HEROD THE TETRARCH FOUGHT WITH ARETAS.</head>
    <p>Some thought the destruction of Herod's army came as a punishment of what he
    did against John, that was called the <soCalled>Baptist</soCalled>, and<note>editorial
    note must not enter source text</note> Herod resolved to build the temple.</p>
  </div>
  <div type="textpart" subtype="section" n="120">
    <milestone n="3" unit="Whiston_section"/>
    <p>So Vitellius prepared to make war with Aretas.</p>
  </div>
</div>
"""

ANTIQUITIES_GREEK = """
<div type="textpart" subtype="book" n="18">
  <div type="textpart" subtype="section" n="arg"><p>Τάδε ἔνεστιν ἐν τῇ βίβλῳ.</p></div>
  <div type="textpart" subtype="section" n="116"><p>Ἰωάννου τοῦ ἐπικαλουμένου βαπτιστοῦ.</p></div>
  <div type="textpart" subtype="section" n="117"><p>βαπτισμῷ συνιέναι.</p></div>
  <div type="textpart" subtype="section" n="118"><p>δείσας Ἡρώδης.</p></div>
  <div type="textpart" subtype="section" n="119"><p>εἰς τὸν Μαχαιροῦντα.</p></div>
  <div type="textpart" subtype="section" n="120"><p>Οὐιτέλλιος δὲ παρασκευασάμενος.</p></div>
  <div type="textpart" subtype="section" n="121"><p>ὡς πολεμήσων Ἀρέτᾳ.</p></div>
</div>
"""

SINGLE_SECTION = """
<div type="textpart" subtype="book" n="1">
  <div type="textpart" subtype="section" n="1">
    <milestone n="1" unit="Whiston_section"/><p>{text}</p>
  </div>
</div>
"""

LIFE_SECTION = """
<div type="textpart" subtype="section" n="1">
  <milestone n="1" unit="Whiston_section"/><p>{text}</p>
</div>
"""

TEST_LINK = ("antiquities", 18, 117, "Mrk", 6, 17, 6, 29, "Related account: death of John the Baptist")


def _write_work(directory: Path, work_id: str, english: str, greek: str) -> None:
    (directory / f"tlg0526.{work_id}.perseus-eng2.xml").write_text(
        TEI_TEMPLATE.format(kind="translation", body=english), encoding="utf-8"
    )
    (directory / f"tlg0526.{work_id}.perseus-grc2.xml").write_text(
        TEI_TEMPLATE.format(kind="edition", body=greek), encoding="utf-8"
    )


def _write_corpus(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    _write_work(directory, "tlg001", ANTIQUITIES_ENGLISH, ANTIQUITIES_GREEK)
    _write_work(
        directory, "tlg002",
        LIFE_SECTION.format(text="The family from which I am derived is not ignoble."),
        LIFE_SECTION.format(text="Ἐμοὶ δὲ γένος ἐστὶν οὐκ ἄσημον."),
    )
    _write_work(
        directory, "tlg003",
        SINGLE_SECTION.format(text="Our nation is of very great antiquity."),
        SINGLE_SECTION.format(text="Ἱκανῶς μὲν ὑπολαμβάνω."),
    )
    _write_work(
        directory, "tlg004",
        SINGLE_SECTION.format(text="The war of the Jews with the Romans was the greatest."),
        SINGLE_SECTION.format(text="Ἐπειδὴ τὸν Ἰουδαίων πρὸς Ῥωμαίους πόλεμον."),
    )
    return directory


def _build_db(tmp_path: Path, monkeypatch, links=(TEST_LINK,)) -> Path:
    monkeypatch.setattr(josephus, "_BIBLICAL_LINKS", links)
    db_path = tmp_path / "ancient.db"
    conn = sqlite3.connect(db_path)
    create_schema(conn)
    import_josephus(conn, _write_corpus(tmp_path / "josephus"))
    conn.close()
    return db_path


def test_parser_joins_every_greek_section_in_each_english_span(tmp_path):
    _write_corpus(tmp_path)

    rows = parse_josephus_work(tmp_path, "tlg001")

    assert [row["reference"] for row in rows] == ["Antiquities 18.116–119", "Antiquities 18.120–121"]
    assert [(row["section_number"], row["section_end"]) for row in rows] == [("116", 119), ("120", 121)]
    assert rows[0]["original_text"] == (
        "Ἰωάννου τοῦ ἐπικαλουμένου βαπτιστοῦ. βαπτισμῷ συνιέναι. "
        "δείσας Ἡρώδης. εἰς τὸν Μαχαιροῦντα."
    )
    assert rows[1]["original_text"] == "Οὐιτέλλιος δὲ παρασκευασάμενος. ὡς πολεμήσων Ἀρέτᾳ."
    assert "Τάδε ἔνεστιν" not in " ".join(row["original_text"] for row in rows)
    assert [row["alternate_reference"] for row in rows] == ["Whiston 18.5.2", "Whiston 18.5.3"]


def test_parser_keeps_headings_and_notes_out_of_source_text(tmp_path):
    _write_corpus(tmp_path)

    first = parse_josephus_work(tmp_path, "tlg001")[0]

    assert first["text"].startswith("Some thought the destruction")
    assert "called the Baptist, and Herod resolved" in first["text"]
    assert "HOW HEROD" not in first["text"]
    assert "editorial note" not in first["text"]
    assert first["editorial_heading"] == "HOW HEROD THE TETRARCH FOUGHT WITH ARETAS."
    assert first["license"] == "CC BY-SA 4.0"


def test_parser_references_single_sections_and_works_without_books(tmp_path):
    _write_corpus(tmp_path)

    life = parse_josephus_work(tmp_path, "tlg002")

    assert [(row["reference"], row["alternate_reference"]) for row in life] == [("Life 1", "Whiston 1")]


def test_parser_rejects_out_of_order_english_sections(tmp_path):
    _write_corpus(tmp_path)
    english = ANTIQUITIES_ENGLISH.replace('n="120"', 'n="12"')
    _write_work(tmp_path, "tlg001", english, ANTIQUITIES_GREEK)

    with pytest.raises(ValueError, match="does not follow"):
        parse_josephus_work(tmp_path, "tlg001")


def test_import_attaches_links_by_section_containment_and_is_idempotent(tmp_path, monkeypatch):
    db_path = _build_db(tmp_path, monkeypatch)
    conn = sqlite3.connect(db_path)
    import_josephus(conn, tmp_path / "josephus")

    counts = [
        conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in (
            "ancient_source_passages",
            "ancient_source_passages_fts",
            "ancient_source_biblical_links",
        )
    ]
    linked = conn.execute(
        """SELECT p.reference FROM ancient_source_biblical_links bl
           JOIN ancient_source_passages p ON p.id = bl.passage_id"""
    ).fetchall()
    conn.close()

    assert counts == [5, 5, 1]
    assert linked == [("Antiquities 18.116–119",)]


def test_import_fails_when_a_curated_link_does_not_resolve(tmp_path, monkeypatch):
    unresolved = ("antiquities", 18, 500, "Act", 1, 1, 1, 1, "Narrative overlap: missing")

    with pytest.raises(ValueError, match="does not resolve"):
        _build_db(tmp_path, monkeypatch, links=(TEST_LINK, unresolved))


def test_import_requires_all_eight_tei_files(tmp_path):
    directory = _write_corpus(tmp_path / "josephus")
    (directory / "tlg0526.tlg003.perseus-grc2.xml").unlink()
    conn = sqlite3.connect(tmp_path / "ancient.db")
    create_schema(conn)

    with pytest.raises(FileNotFoundError, match="tlg0526.tlg003.perseus-grc2.xml"):
        import_josephus(conn, directory)
    conn.close()


async def _search(db_path: Path, query: str, **filters) -> dict:
    database = StudyBibleDB(db_path)
    await database.connect()
    try:
        return await database.search_ancient_sources(query, corpus="josephus", **filters)
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_search_stems_english_and_combines_filters(tmp_path, monkeypatch):
    db_path = _build_db(tmp_path, monkeypatch)

    stemmed = await _search(db_path, "Herod temple building")
    linked = await _search(
        db_path, "John Baptist", biblical_reference="Mark 6:20", period="second_temple"
    )
    chapter = await _search(db_path, "John Baptist", biblical_reference="Mark 6")
    excluded = await _search(db_path, "John Baptist", period="hasmonean")

    assert stemmed["match"] == "all"
    assert [row["reference"] for row in stemmed["rows"]] == ["Antiquities 18.116–119"]
    assert [row["reference"] for row in linked["rows"]] == ["Antiquities 18.116–119"]
    assert linked["rows"][0]["biblical_links"][0]["relationship_note"].startswith("Related account")
    assert [row["reference"] for row in chapter["rows"]] == ["Antiquities 18.116–119"]
    assert excluded["status"] == "no_match"


@pytest.mark.asyncio
async def test_search_ignores_work_titles_and_references(tmp_path, monkeypatch):
    db_path = _build_db(tmp_path, monkeypatch)

    # Each word appears only in a work title ("Jewish Antiquities", "Against
    # Apion", "Life of Josephus"), never in passage text.
    for query in ("Jewish", "Apion", "Josephus"):
        result = await _search(db_path, query)
        assert result["status"] == "no_match", query


@pytest.mark.asyncio
async def test_search_folds_greek_accents_case_and_spanned_sections(tmp_path, monkeypatch):
    db_path = _build_db(tmp_path, monkeypatch)

    for query in ("βαπτισμῷ", "βαπτισμω", "βαπτιστου Ιωαννου", "ΒΑΠΤΙΣΤΟΥ"):
        result = await _search(db_path, query)
        assert [row["reference"] for row in result["rows"]] == ["Antiquities 18.116–119"], query


@pytest.mark.asyncio
async def test_search_falls_back_to_any_term_and_ignores_operators(tmp_path, monkeypatch):
    db_path = _build_db(tmp_path, monkeypatch)

    fallback = await _search(db_path, "Vitellius xylophone")
    operators = await _search(db_path, 'Vitellius OR NOT "Aretas')
    only_operators = await _search(db_path, "AND OR")

    assert fallback["match"] == "any"
    assert [row["reference"] for row in fallback["rows"]] == ["Antiquities 18.120–121"]
    assert operators["terms"] == ["vitellius", "aretas"]
    assert operators["match"] == "all"
    assert only_operators["status"] == "invalid_query"


@pytest.mark.asyncio
async def test_handler_distinguishes_empty_result_causes(tmp_path, monkeypatch):
    db_path = _build_db(tmp_path, monkeypatch)
    empty_path = tmp_path / "empty.db"
    sqlite3.connect(empty_path).close()

    async def reply(path: Path, **args) -> str:
        database = StudyBibleDB(path)
        await database.connect()
        monkeypatch.setattr(server, "db", database)
        try:
            return (await server.handle_search_ancient_sources(args))[0].text
        finally:
            await database.close()

    missing = await reply(empty_path, query="John")
    invalid = await reply(db_path, query="John", biblical_reference="Hezekiah 3:1")
    no_link = await reply(db_path, query="John", biblical_reference="Luke 21:5")
    no_match = await reply(db_path, query="xylophone")
    fallback = await reply(db_path, query="Vitellius xylophone")

    assert "python scripts/upgrade_database.py" in missing
    assert "Unsupported biblical_reference 'Hezekiah 3:1'" in invalid
    assert "'Luke 21'" in invalid
    assert "No Josephus passage has an editorial biblical link covering Luke 21:5" in no_link
    assert "curated" in no_link and "1 links currently cover 1 Josephus passages" in no_link
    assert no_match == "No Josephus passage contains any of the search terms (xylophone)."
    assert "No passage contains all terms; showing passages matching any term" in fallback
    for message in (invalid, no_link, no_match):
        assert "upgrade_database" not in message and "download" not in message


async def _call(path: Path, monkeypatch, handler, **args) -> str:
    database = StudyBibleDB(path)
    await database.connect()
    monkeypatch.setattr(server, "db", database)
    try:
        return (await handler(args))[0].text
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_lookup_resolves_a_section_inside_a_whiston_span(tmp_path, monkeypatch):
    db_path = _build_db(tmp_path, monkeypatch)
    lookup = server.handle_lookup_ancient_source

    inside = await _call(db_path, monkeypatch, lookup, citation="Ant. 18.117")
    spanning = await _call(db_path, monkeypatch, lookup, citation="Josephus, A.J. 18.116-121")
    no_greek = await _call(db_path, monkeypatch, lookup, citation="Antiquities 18.116", include_original=False)
    life = await _call(db_path, monkeypatch, lookup, citation="Life 1")

    assert inside.startswith("## Antiquities 18.117\n")
    assert "1 overlapping passage*" in inside
    assert (
        "### Flavius Josephus, Antiquities 18.116–119 (Whiston 18.5.2)\n"
        "*Not Scripture · Jewish history (AD 93–94) · tier A · Niese Greek, Whiston English*"
    ) in inside
    assert "- Josephus: Not Scripture: a Jewish historian writing c. AD 75–100" in inside
    assert "License: CC BY-SA 4.0." in inside
    assert "**Greek:** Ἰωάννου" in inside
    assert "- Shared tradition: Mark 6:17–29 — Related account" in inside
    assert spanning.index("Antiquities 18.116–119") < spanning.index("Antiquities 18.120–121")
    assert "2 overlapping passages" in spanning
    assert "**Greek:**" not in no_greek and "Some thought" in no_greek
    assert "### Flavius Josephus, Life 1 (Whiston 1)" in life


@pytest.mark.asyncio
async def test_lookup_caps_passages_and_explains_failures(tmp_path, monkeypatch):
    db_path = _build_db(tmp_path, monkeypatch)
    empty_path = tmp_path / "empty.db"
    sqlite3.connect(empty_path).close()
    lookup = server.handle_lookup_ancient_source
    capped = await _call(db_path, monkeypatch, lookup, citation="Antiquities 18", limit=1)
    bad_limit = await _call(db_path, monkeypatch, lookup, citation="Antiquities 18", limit=11)
    oversized = await _call(db_path, monkeypatch, lookup, citation="Ant. 99999999999999999999.1")
    out_of_range = await _call(db_path, monkeypatch, lookup, citation="Ant. 18.200")
    unknown = await _call(db_path, monkeypatch, lookup, citation="Lifeboat 1-2")
    no_locator = await _call(db_path, monkeypatch, lookup, citation="Antiquities")
    whiston = await _call(db_path, monkeypatch, lookup, citation="Ant. 18.5.2")
    bad_corpus = await _call(db_path, monkeypatch, lookup, citation="Ant. 18.116", corpus="nonesuch")
    missing = await _call(empty_path, monkeypatch, lookup, citation="Ant. 18.116")

    assert "Showing the first 1 of 2 overlapping passages" in capped
    assert "Antiquities 18.120–121" not in capped
    assert bad_limit == "'limit' must be an integer from 1 to 10."
    assert oversized.startswith("Could not read the locator '99999999999999999999.1'")
    assert out_of_range == (
        "No passage covers Antiquities 18.200. Imported Antiquities runs Antiquities "
        "18.116–121; nearest passages: preceding Antiquities 18.120–121."
    )
    assert unknown.startswith("Unknown work in citation 'Lifeboat 1-2'")
    assert "Josephus (Antiquities, Life, Against Apion, War; e.g. 'Antiquities 18.116')" in unknown
    assert "Rabbinic (Mishnah, 63 works; e.g. 'Mishnah Shekalim 1:1')" in unknown
    assert len(unknown) < 700
    assert no_locator.startswith("No locator in 'Antiquities'")
    # The example is the work's first imported passage, not another work's.
    assert "cited by book.section" in no_locator and "e.g. 'Antiquities 18.116'" in no_locator
    assert whiston.startswith("Could not read the locator '18.5.2'")
    assert bad_corpus.startswith("Unsupported ancient-source corpus 'nonesuch'")
    assert "python scripts/upgrade_database.py" in missing


@pytest.mark.asyncio
async def test_lookup_asks_for_reimport_when_rows_predate_sort_keys(tmp_path, monkeypatch):
    db_path = _build_db(tmp_path, monkeypatch)
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE ancient_source_passages SET sort_start = NULL, sort_end = NULL")
    conn.commit()
    conn.close()

    reply = await _call(db_path, monkeypatch, server.handle_lookup_ancient_source, citation="Ant. 18.116")

    assert "imported before citation lookup existed" in reply
    assert "python scripts/upgrade_database.py" in reply


@pytest.mark.asyncio
async def test_search_accepts_all_and_rejects_unregistered_corpora(tmp_path, monkeypatch):
    db_path = _build_db(tmp_path, monkeypatch)
    search = server.handle_search_ancient_sources

    everything = await _call(db_path, monkeypatch, search, query="John Baptist", corpus="all")
    none = await _call(db_path, monkeypatch, search, query="xylophone", corpus="all")
    unknown = await _call(db_path, monkeypatch, search, query="John", corpus="nonesuch")

    assert "*Filters: corpus=all*" in everything
    assert "*Not Scripture · Jewish history (AD 93–94) · tier A ·" in everything
    assert "Antiquities 18.116–119" in everything
    assert none == "No ancient-source passage contains any of the search terms (xylophone)."
    assert unknown == (
        f"Unsupported ancient-source corpus 'nonesuch'. Available corpora: "
        f"{', '.join(CORPORA)}, or 'all'."
    )


def test_parser_emits_generic_sort_keys_and_licences(tmp_path):
    _write_corpus(tmp_path)

    antiquities = parse_josephus_work(tmp_path, "tlg001")
    life = parse_josephus_work(tmp_path, "tlg002")

    assert [(row["sort_start"], row["sort_end"]) for row in antiquities] == [(18116, 18119), (18120, 18121)]
    assert [(row["sort_start"], row["sort_end"]) for row in life] == [(1, 1)]
    assert {(row["original_language"], row["original_license"], row["translation_license"])
            for row in antiquities} == {("Greek", "CC BY-SA 4.0", "CC BY-SA 4.0")}


def test_ancient_source_formatter_labels_primary_text_and_provenance():
    row = {
        "corpus": "josephus",
        "work_key": "antiquities",
        "sort_start": 18116,
        "author": "Flavius Josephus",
        "reference": "Antiquities 18.116–119",
        "alternate_reference": "Whiston 18.5.2",
        "editorial_heading": "HOW HEROD THE TETRARCH FOUGHT WITH ARETAS.",
        "work_title": "Jewish Antiquities",
        "period_tags": "second_temple,herodian,roman",
        "edition": "Benedikt Niese",
        "translation": "William Whiston",
        "license": "CC BY-SA 4.0",
        "source_url": "https://example.test/josephus",
        "text": "John was called the Baptist.",
        "original_text": "Ἰωάννου τοῦ βαπτιστοῦ",
        "biblical_links": [],
    }

    output = format_ancient_source_results("John Baptist", [row], "josephus")

    assert "### Flavius Josephus, Antiquities 18.116–119 (Whiston 18.5.2)" in output
    assert "*Not Scripture · Jewish history (AD 93–94) · tier A · Niese Greek, Whiston English*" in output
    assert "*Whiston chapter heading (editorial): HOW HEROD" in output
    assert "**Greek:** Ἰωάννου τοῦ βαπτιστοῦ" in output
    assert output.endswith(
        "**Caveats**\n"
        "- Josephus: Not Scripture: a Jewish historian writing c. AD 75–100; his editorial "
        "framing is his own.\n"
        "- Tier A: written before or alongside the NT.\n\n"
        "**Sources**\n- Josephus: Greek: Benedikt Niese. English: William Whiston. "
        "License: CC BY-SA 4.0. https://example.test/josephus"
    )
    assert "No passage contains all terms" not in output


def test_ancient_source_provenance_is_listed_once_per_response():
    row = {
        "author": "Flavius Josephus", "reference": "War 1.1", "alternate_reference": None,
        "editorial_heading": None, "work_title": "The Jewish War", "period_tags": "roman",
        "edition": "Niese", "translation": "Whiston", "license": "CC BY-SA 4.0",
        "source_url": "https://example.test/war", "text": "x", "original_text": None,
        "biblical_links": [],
    }
    other = dict(row, reference="Antiquities 1.1", source_url="https://example.test/ant")

    output = format_ancient_source_results("x", [row, dict(row, reference="War 1.2"), other], "josephus")

    assert output.count("CC BY-SA 4.0") == 1
    assert output.count("https://example.test/war") == 1
    assert "https://example.test/war https://example.test/ant" in output


def test_excerpt_is_centred_on_the_first_match():
    from study_bible_mcp.tools import _match_excerpt

    text = "Opening words of the passage. " * 100 + "Herod rebuilt the temple. " + "Tail. " * 100
    excerpt = _match_excerpt(text, "temple building", 600)
    greek = _match_excerpt("ἀρχή " * 300 + "τοῦ βαπτιστοῦ" + " τέλος" * 300, "βαπτιστου", 400)

    assert "Herod rebuilt the temple." in excerpt
    assert excerpt.startswith("…") and excerpt.endswith("…")
    assert len(excerpt) <= 602
    assert "βαπτιστοῦ" in greek
    assert _match_excerpt("short text", "missing", 600) == "short text"


def test_download_default_data_dir_is_project_relative():
    script = Path(__file__).resolve().parent.parent / "scripts" / "download_ancient_sources.py"
    spec = importlib.util.spec_from_file_location("download_ancient_sources", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    default = next(param.default for param in module.main.params if param.name == "data_dir")

    assert default == script.parent.parent / "data" / "ancient_sources"
    assert default.is_absolute()
