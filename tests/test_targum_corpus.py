"""Targum corpus: Sefaria version files, verse keying, licences, links, citations, tools."""

import json
import sqlite3
from pathlib import Path

import httpx
import pytest

from study_bible_mcp import server
from study_bible_mcp.corpora import CORPORA, combined_license, resolve_citation, targum
from study_bible_mcp.corpora.download import git_blob_sha1
from study_bible_mcp.database import StudyBibleDB, create_schema
from study_bible_mcp.parsers.ancient_sources import import_corpus

ONKELOS_GEN_1_1 = "בְּקַדְמִין בְּרָא יְיָ יָת שְׁמַיָּא וְיָת אַרְעָא"
ONKELOS_GEN_1_2 = "וְאַרְעָא הֲוָת צַדְיָא וְרֵקַנְיָא"
ONKELOS_GEN_6_1 = "וַהֲוָה אֲרֵי שָׁרִיאוּ בְּנֵי אֲנָשָׁא לְמִסְגֵּי"
ONKELOS_EXOD_12_40 = "וּמוֹתַב בְּנֵי יִשְׂרָאֵל דִי יְתִיבוּ בְּמִצְרָיִם אַרְבַּע מְאָה וּתְלָתִין שְׁנִין:"
ONKELOS_GEN_32_31 = "אֲרֵי חֲזֵיתִי מַלְאָכַיָּא דַּיְיָ אַפִּין בְּאַפִּין"
ONKELOS_EXOD_7_26 = "וַאֲמַר יְיָ לְמשֶׁה עוּל לְוָת פַּרְעֹה"
ONKELOS_EXOD_8_1 = "וַאֲמַר יְיָ לְמשֶׁה אֱמַר לְאַהֲרֹן"
ONKELOS_EXOD_20_13 = "לָא תִקְטוֹל נְפָשׁ לָא תְגוּף"
ONKELOS_EXOD_20_14 = "לָא תַחְמֵד בֵּית חַבְרָךְ"


def _chapters(**verses_by_chapter) -> list[list[str]]:
    """Chapter lists from {'c12': [...]}; missing chapters are empty."""
    last = max(int(key[1:]) for key in verses_by_chapter)
    return [verses_by_chapter.get(f"c{number}", []) for number in range(1, last + 1)]


def _texts() -> dict[str, list[list[str]]]:
    texts = {source.filename: [[f"{source.filename} 1:1"]] for source in targum.SOURCE_FILES}
    texts["onkelos_genesis.aramaic.json"] = _chapters(
        c1=[ONKELOS_GEN_1_1, ONKELOS_GEN_1_2], c6=[ONKELOS_GEN_6_1],
        c32=[""] * 30 + [ONKELOS_GEN_32_31, ""], c49=[""] * 11 + ["??? יְסַמְקוּן טּוּרוֹהִי"],
    )
    texts["onkelos_genesis.metsudah.json"] = _chapters(
        c1=["In the beginning [<b>In the first times</b>] Elohim <i>created</i>  the heavens.", ""],
        c6=["It came to pass when man began to multiply on the face of the earth,"],
        c12=["Adonoy appeared [<i>became revealed</i>] to Avram."],
        c32=[""] * 30 + ["For I have seen God[ly beings] [<b>Angles of God</b>] face to face.", ""],
        c49=[""] * 11 + ["His eyes are red from wine."],
        c50=["He was placed in a coffin in Egypt. <b>Chazak</b>"],
    )
    # Sefaria numbers Onkelos by the Hebrew: MT 7:26 and 8:1 are English 8:1
    # and 8:5, and its Exodus 20 joins the four short commandments into 20:13.
    texts["onkelos_exodus.aramaic.json"] = _chapters(
        c7=[""] * 25 + [ONKELOS_EXOD_7_26] + [""] * 3,
        c8=[ONKELOS_EXOD_8_1] + [""] * 27,
        c12=[""] * 39 + [ONKELOS_EXOD_12_40],
        c20=[""] * 12 + [ONKELOS_EXOD_20_13, ONKELOS_EXOD_20_14] + [""] * 9,
    )
    texts["onkelos_exodus.metsudah.json"] = _chapters(
        c7=[""] * 25 + ["Go to Pharaoh, that they may worship [<b>before</b>] Me."] + [""] * 3,
        c8=["Say to Aharon, Extend your hand with your rod."] + [""] * 27,
        c12=[""] * 39 + ["The habitation of the B&#8217;nei Yisrael in Egypt [<b>lasted</b>] 430 years."],
        c20=[""] * 12 + ["Do not commit murder. Do not commit adultery.", "Do not covet."] + [""] * 9,
    )
    texts["onkelos_numbers.metsudah.json"] = _chapters(
        c7=["One spoon of ten gold [<i>shekolim</i>], filled with [<b>fragrant</b>] incense."],
        c26=["It was after the plague. Adonoy spoke to Moshe."],
    )
    return texts


def _write(directory: Path, texts=None, **declaration) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for source in targum.SOURCE_FILES:
        data = {
            "language": source.language,
            "versionTitle": source.version_title,
            "license": source.license,
            "text": (texts or _texts())[source.filename],
            **declaration.get(source.filename, {}),
        }
        (directory / source.filename).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return directory


def _rows(directory: Path) -> dict[str, dict]:
    return {row["reference"]: row for row in targum.parse(directory)}


# --- Parser


def test_onkelos_pairs_aramaic_with_labelled_metsudah_english(tmp_path):
    rows = _rows(_write(tmp_path))

    genesis = rows["Targum Onkelos Genesis 1:1"]
    flood = rows["Targum Onkelos Genesis 6:1"]
    exodus = rows["Targum Onkelos Exodus 12:40"]

    assert genesis["original_text"] == ONKELOS_GEN_1_1
    assert genesis["text"] == "In the beginning ⟨In the first times⟩ Elohim created the heavens."
    assert genesis["translation"] == targum.METSUDAH
    assert "not a direct translation of the Aramaic" in genesis["translation"]
    assert "⟨marked⟩ words are Onkelos's renderings" in genesis["translation"]
    assert genesis["alternate_reference"] is None
    assert genesis["translation_license"] == "CC BY-NC 4.0"
    assert genesis["license"] == "Aramaic text: Public domain; English translation: CC BY-NC 4.0"
    assert (genesis["sort_start"], genesis["sort_end"], genesis["work_key"]) == (1001, 1001, "onkelos_genesis")
    assert genesis["author"] == "Targum Onkelos" and genesis["period_tags"] == "amoraic"
    assert flood["text"].startswith("It came to pass when man began")
    assert flood["translation"] == targum.METSUDAH
    assert exodus["text"] == "The habitation of the B’nei Yisrael in Egypt ⟨lasted⟩ 430 years."
    assert exodus["original_text"] == ONKELOS_EXOD_12_40
    assert rows["Targum Onkelos Genesis 49:12"]["original_text"] == "יְסַמְקוּן טּוּרוֹהִי"
    assert "Sefaria-Export-Archive/tree/" in genesis["source_url"]
    assert targum.SEFARIA_COMMIT in genesis["source_url"]


def test_a_verse_without_english_is_an_aramaic_only_passage(tmp_path):
    row = _rows(_write(tmp_path))["Targum Onkelos Genesis 1:2"]

    assert row["original_text"] == ONKELOS_GEN_1_2
    assert not {"text", "translation", "translation_license"} & set(row)
    assert row["license"] == "Public domain"
    assert row["license"] == combined_license(row.get("original_license"), None, "Aramaic")


def test_metsudah_cleaning_rejects_unexpected_markup():
    with pytest.raises(ValueError, match="markup"):
        targum.clean_metsudah("an <sup>1</sup> footnote")
    with pytest.raises(ValueError, match="markup"):
        targum.clean_metsudah("a stray { brace")
    with pytest.raises(ValueError, match="markup"):
        targum.clean_metsudah("a footnote mark* in the text")
    with pytest.raises(ValueError, match="Unbalanced"):
        targum.clean_metsudah("an unclosed ⟨mark")
    with pytest.raises(ValueError, match="markup"):
        targum.clean_metsudah("[<b>a</b> [<b>b</b>]")


@pytest.mark.parametrize("raw, italic, expected", [
    # Bold bracket groups are Onkelos's renderings; plain brackets are Metsudah's.
    ("They saw [a vision of] the [<b>Glory of the</b>] God", False,
     "They saw [a vision of] the ⟨Glory of the⟩ God"),
    # Metsudah's own supplement inside an Onkelos rendering stays bracketed.
    ("help him [but you should] [<b>[you should]</b>] unload", False,
     "help him [but you should] ⟨[you should]⟩ unload"),
    # Bold partly inside brackets is still Onkelos.
    ("what he can afford [lit. <b>may attach to his hands</b>]", False,
     "what he can afford [lit. ⟨may attach to his hands⟩]"),
    # Italics are transliterations, unless the chapter marks Onkelos in italics.
    ("nine <i>amohs</i> its length, the <i>tachash [<b>multi-colored</b>]</i>-hide", False,
     "nine amohs its length, the tachash ⟨multi-colored⟩-hide"),
    ("ten gold [<i>shekolim</i>]", False, "ten gold [shekolim]"),
    ("Adonoy appeared [<i>became revealed</i>] to Avram", True,
     "Adonoy appeared ⟨became revealed⟩ to Avram"),
    # 'Chazak' ends a book: neither Torah nor Onkelos.
    ("placed in a coffin in Egypt. <b>Chazak</b>", False, "placed in a coffin in Egypt."),
])
def test_metsudah_marks_onkelos_renderings_apart_from_its_own_brackets(raw, italic, expected):
    assert targum.clean_metsudah(raw, italic) == expected


@pytest.mark.parametrize("book, chapter, verse, expected", [
    ("Genesis", 32, 31, (32, 30, 30, "MT 32:31")),
    ("Genesis", 32, 1, (31, 55, 55, "MT 32:1")),
    ("Exodus", 7, 26, (8, 1, 1, "MT 7:26")),
    ("Exodus", 8, 1, (8, 5, 5, "MT 8:1")),
    ("Exodus", 21, 37, (22, 1, 1, "MT 21:37")),
    ("Leviticus", 5, 20, (6, 1, 1, "MT 5:20")),
    ("Numbers", 17, 28, (17, 13, 13, "MT 17:28")),
    ("Deuteronomy", 28, 69, (29, 1, 1, "MT 28:69")),
    ("Deuteronomy", 29, 28, (29, 29, 29, "MT 29:28")),
    ("Exodus", 20, 13, (20, 13, 16, "Sefaria 20:13")),
    ("Exodus", 20, 23, (20, 26, 26, "Sefaria 20:23")),
    ("Deuteronomy", 5, 18, (5, 21, 21, "Sefaria 5:18")),
    ("Numbers", 26, 1, (26, 1, 1, "MT 25:19–26:1")),
    ("Exodus", 20, 12, (20, 12, 12, None)),
    ("Deuteronomy", 32, 8, (32, 8, 8, None)),
])
def test_sefaria_onkelos_verses_map_to_english_numbering(book, chapter, verse, expected):
    assert targum.english_verses(book, chapter, verse) == expected


def test_passages_are_keyed_and_cited_by_english_verse_with_the_hebrew_number(tmp_path):
    rows = _rows(_write(tmp_path))

    peniel = rows["Targum Onkelos Genesis 32:30"]
    assert (peniel["alternate_reference"], peniel["sort_start"]) == ("MT 32:31", 32030)
    assert peniel["original_text"] == ONKELOS_GEN_32_31
    assert peniel["text"] == "For I have seen God[ly beings] ⟨Angles of God⟩ face to face."
    assert rows["Targum Onkelos Exodus 8:1"]["alternate_reference"] == "MT 7:26"
    assert rows["Targum Onkelos Exodus 8:1"]["original_text"] == ONKELOS_EXOD_7_26
    assert rows["Targum Onkelos Exodus 8:5"]["alternate_reference"] == "MT 8:1"
    assert rows["Targum Onkelos Exodus 8:5"]["text"].startswith("Say to Aharon")
    decalogue = rows["Targum Onkelos Exodus 20:13–16"]
    assert (decalogue["sort_start"], decalogue["sort_end"]) == (20013, 20016)
    assert decalogue["alternate_reference"] == "Sefaria 20:13"
    assert rows["Targum Onkelos Exodus 20:17"]["original_text"] == ONKELOS_EXOD_20_14
    assert rows["Targum Onkelos Numbers 26:1"]["alternate_reference"] == "MT 25:19–26:1"
    assert rows["Targum Onkelos Numbers 7:1"]["text"] == (
        "One spoon of ten gold [shekolim], filled with ⟨fragrant⟩ incense."
    )
    assert rows["Targum Onkelos Genesis 12:1"]["text"] == "Adonoy appeared ⟨became revealed⟩ to Avram."
    assert rows["Targum Onkelos Genesis 50:1"]["text"] == "He was placed in a coffin in Egypt."
    assert "Targum Onkelos Genesis 32:31" not in rows and "Targum Onkelos Exodus 20:13" not in rows


def test_parser_rejects_a_decalogue_not_divided_by_the_upper_accents(tmp_path):
    texts = _texts()
    texts["onkelos_exodus.aramaic.json"][19] = texts["onkelos_exodus.aramaic.json"][19] + ["", "", ""]

    with pytest.raises(ValueError, match="upper-accent Decalogue division"):
        targum.parse(_write(tmp_path, texts))


def test_links_name_the_hebrew_verse_where_numbering_differs(tmp_path):
    links = {
        link.locator: link for link in targum.biblical_links(targum.parse(_write(tmp_path)))
        if link.work_key == "onkelos_exodus"
    }

    assert (links["8:5"].chapter, links["8:5"].verse, links["8:5"].note) == (8, 5, "(MT 8:1)")
    assert (links["20:13"].verse, links["20:13"].end_verse) == (13, 16)
    assert links["20:13"].note == "(Sefaria 20:13)"
    assert links["12:40"].note == "" and links["12:40"].relation == "translation"


def test_parser_rejects_unexpected_licence_and_missing_correction(tmp_path):
    _write(tmp_path / "licence", **{"onkelos_exodus.metsudah.json": {"license": "unknown"}})
    texts = _texts()
    texts["onkelos_genesis.aramaic.json"][48][11] = "יְסַמְקוּן"
    _write(tmp_path / "artefact", texts)

    with pytest.raises(ValueError, match="expected Sefaria license 'CC-BY-NC'"):
        targum.parse(tmp_path / "licence")
    with pytest.raises(ValueError, match="expected '\\?\\?\\? '"):
        targum.parse(tmp_path / "artefact")


def test_require_files_names_every_missing_file(tmp_path):
    directory = _write(tmp_path)
    (directory / "onkelos_genesis.metsudah.json").unlink()
    (directory / "onkelos_numbers.aramaic.json").unlink()

    with pytest.raises(FileNotFoundError) as error:
        targum.require_targum_files(directory)

    assert "onkelos_genesis.metsudah.json, onkelos_numbers.aramaic.json" in str(error.value)
    assert len(targum.SOURCE_FILES) == 10


# --- Import and links


def _import(tmp_path: Path) -> Path:
    db_path = tmp_path / "targum.db"
    conn = sqlite3.connect(db_path)
    create_schema(conn)
    import_corpus(conn, "targum", _write(tmp_path / "targum"))
    conn.close()
    return db_path


def test_import_links_every_passage_to_the_verse_it_translates_and_is_idempotent(tmp_path):
    db_path = _import(tmp_path)
    conn = sqlite3.connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM ancient_source_passages").fetchone()[0]

    assert import_corpus(conn, "targum", tmp_path / "targum") == count
    assert conn.execute("SELECT COUNT(*) FROM ancient_source_biblical_links").fetchone()[0] == count
    assert conn.execute(
        "SELECT l.biblical_book, l.sort_start, l.sort_end, l.relationship_note, l.relation "
        "FROM ancient_source_biblical_links l JOIN ancient_source_passages p ON p.id = l.passage_id "
        "WHERE p.reference = ?",
        ("Targum Onkelos Exodus 12:40",),
    ).fetchone() == ("Exo", 12040, 12040, "", "translation")
    assert conn.execute(
        "SELECT collection, work_title FROM ancient_source_passages WHERE reference = ?",
        ("Targum Onkelos Exodus 12:40",),
    ).fetchone() == ("Targum Onkelos", "Exodus")


# --- Citations


@pytest.mark.parametrize("citation, work_key, sort_range", [
    ("Onkelos Genesis 1:1", "onkelos_genesis", (1001, 1001)),
    ("Targum Onkelos Gen 1:1", "onkelos_genesis", (1001, 1001)),
    ("Tg. Onq. Gen. 1:1-3", "onkelos_genesis", (1001, 1003)),
    ("Onqelos Exodus 12", "onkelos_exodus", (12000, 12999)),
    ("Onkelos Num 24:17", "onkelos_numbers", (24017, 24017)),
    ("Tg. Onq. Deut 32:8", "onkelos_deuteronomy", (32008, 32008)),
    ("Genesis 1:1", "onkelos_genesis", (1001, 1001)),
])
def test_resolves_targum_citations(citation, work_key, sort_range):
    resolution = resolve_citation(citation, list(CORPORA.values()))

    assert resolution.status == "ok", (citation, resolution)
    assert (resolution.match.corpus.key, resolution.match.work.key, resolution.match.sort_range) == (
        "targum", work_key, sort_range,
    )


@pytest.mark.parametrize("citation", [
    "Pseudo-Jonathan Exodus 12:40", "Tg. Ps.-J. Deut 32:8", "Targum Jonathan Genesis 20:17",
])
def test_only_onkelos_is_registered(citation):
    assert resolve_citation(citation, list(CORPORA.values())).status == "unknown_work"


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
async def test_lookup_shows_aramaic_english_and_licence_labels(tmp_path, monkeypatch):
    db_path = _import(tmp_path)
    lookup = server.handle_lookup_ancient_source

    onkelos = await _call(db_path, monkeypatch, lookup, citation="Onkelos Genesis 1:1")
    original_only = await _call(db_path, monkeypatch, lookup, citation="Tg. Onq. Gen 1:2")
    exodus = await _call(db_path, monkeypatch, lookup, citation="Onkelos Exodus 12:40")
    renumbered = await _call(db_path, monkeypatch, lookup, citation="Onkelos Exod 8:5")
    peniel = await _call(db_path, monkeypatch, lookup, citation="Tg. Onq. Gen 32:30")
    decalogue = await _call(db_path, monkeypatch, lookup, citation="Onkelos Exodus 20:15")

    assert onkelos.startswith("## Targum Onkelos Genesis 1:1")
    assert ONKELOS_GEN_1_1 in onkelos and "In the beginning ⟨In the first times⟩" in onkelos
    assert "not a direct translation of the Aramaic" in onkelos
    assert "Metsudah: English of the Hebrew Torah; ⟨marked⟩ words are Onkelos's renderings*" in onkelos
    assert "*Not Scripture · Jewish Aramaic Torah rendering (final form c. 3rd–5th c. AD" in onkelos
    assert (
        "License: Aramaic text: Public domain; English translation: CC BY-NC 4.0 "
        "(non-commercial; https://creativecommons.org/licenses/by-nc/4.0/)."
    ) in onkelos
    assert "No English translation included; Aramaic only." in original_only
    assert ONKELOS_GEN_1_2 in original_only
    assert "License: Public domain." in original_only
    assert "- Translation of: Exod 12:40\n" in exodus
    assert "### Targum Onkelos Exodus 8:5 (MT 8:1)" in renumbered
    assert "- Translation of: Exod 8:5 (MT 8:1)\n" in renumbered
    assert "### Targum Onkelos Genesis 32:30 (MT 32:31)" in peniel
    assert "### Targum Onkelos Exodus 20:13–16 (Sefaria 20:13)" in decalogue


@pytest.mark.asyncio
async def test_search_filters_by_biblical_reference_and_folds_aramaic(tmp_path, monkeypatch):
    db_path = _import(tmp_path)
    search = server.handle_search_ancient_sources

    linked = await _call(
        db_path, monkeypatch, search, query="Egypt", corpus="targum",
        biblical_reference="Exodus 12:40",
    )
    elsewhere = await _call(
        db_path, monkeypatch, search, query="Egypt", corpus="targum",
        biblical_reference="Genesis 1:1",
    )
    aramaic = await _call(db_path, monkeypatch, search, query="במצרים", corpus="targum")

    assert "Targum Onkelos Exodus 12:40" in linked
    assert "No Targum passage contains" in elsewhere
    assert "Targum Onkelos Exodus 12:40" in aramaic


# --- Download


def test_download_verifies_blob_hashes_and_declared_licences(tmp_path):
    texts = _texts()
    contents = {}
    for source in targum.SOURCE_FILES:
        data = {"language": source.language, "versionTitle": source.version_title,
                "license": source.license, "text": texts[source.filename]}
        contents[source.raw_url] = json.dumps(data).encode()
    pins = {source.filename: git_blob_sha1(contents[source.raw_url]) for source in targum.SOURCE_FILES}
    sources = tuple(
        targum.SourceFile(**{**source.__dict__, "git_blob_sha1": pins[source.filename]})
        for source in targum.SOURCE_FILES
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=contents[str(request.url)])

    with pytest.MonkeyPatch.context() as patch, httpx.Client(transport=httpx.MockTransport(handler)) as client:
        patch.setattr(targum, "SOURCE_FILES", sources)
        manifest = targum.download(client, tmp_path / "ok", force=False)
        targum.require_targum_files(tmp_path / "ok")

        bad = sources[0]
        contents[bad.raw_url] = json.dumps({
            "language": bad.language, "versionTitle": bad.version_title, "license": "unknown", "text": [],
        }).encode()
        patch.setattr(targum, "SOURCE_FILES", (
            targum.SourceFile(**{**bad.__dict__, "git_blob_sha1": git_blob_sha1(contents[bad.raw_url])}),
        ))
        with pytest.raises(RuntimeError, match="expected Sefaria license"):
            targum.download(client, tmp_path / "bad", force=False)
        with pytest.raises(RuntimeError, match="Checksum mismatch"):
            patch.setattr(targum, "SOURCE_FILES", sources[:1])
            targum.download(client, tmp_path / "tampered", force=False)

    assert manifest["repository"] == "Sefaria/Sefaria-Export-Archive"
    assert manifest["commit"] == targum.SEFARIA_COMMIT
    assert len(manifest["files"]) == 10
    assert manifest["files"]["onkelos_genesis.metsudah.json"]["license"] == "CC-BY-NC"
    assert "Etheridge" not in manifest["license"]
