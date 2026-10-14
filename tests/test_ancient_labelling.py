"""Labelling contract (tags, caveats, editorial notes, typed links) and framework fixes."""

import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from study_bible_mcp import server
from study_bible_mcp.corpora import CORPORA, BiblicalLink, combined_license, editorial_notes
from study_bible_mcp.corpora.base import default_link_relation
from study_bible_mcp.corpora.editorial_notes import (
    EditorialNotes,
    load_editorial_notes,
    parse_editorial_notes,
)
from study_bible_mcp.database import (
    StudyBibleDB,
    create_schema,
    format_biblical_range,
    parse_biblical_range,
)
from study_bible_mcp.parsers.ancient_sources import import_corpus
from study_bible_mcp.tools import ANCIENT_RESPONSE_BUDGET

# --- Biblical references in notes and links


@pytest.mark.parametrize("reference, parsed, rendered", [
    ("Mark 14:62", ("Mrk", 14, 62, 14, 62), "Mark 14:62"),
    ("Gen 6:1–4", ("Gen", 6, 1, 6, 4), "Gen 6:1–4"),
    ("Genesis 6:13-8:19", ("Gen", 6, 13, 8, 19), "Gen 6:13–8:19"),
    ("Rev 13", ("Rev", 13, 1, 13, 999), "Rev 13"),
    ("Heb 9–10", ("Heb", 9, 1, 10, 999), "Heb 9–10"),
    ("Jude 6", ("Jud", 1, 6, 1, 6), "Jude 6"),
    ("Jude 14–15", ("Jud", 1, 14, 1, 15), "Jude 14–15"),
    ("2 Pet 2:4", ("2Pe", 2, 4, 2, 4), "2 Pet 2:4"),
    ("1 Pet 3:19-20", ("1Pe", 3, 19, 3, 20), "1 Pet 3:19–20"),
    ("Matt 19:3–9", ("Mat", 19, 3, 19, 9), "Matt 19:3–9"),
])
def test_biblical_ranges_parse_and_render(reference, parsed, rendered):
    assert parse_biblical_range(reference) == parsed
    assert format_biblical_range(*parsed) == rendered


@pytest.mark.parametrize("reference", [
    "Hezekiah 3:1", "Mark", "Mark 14:62-60", "Luke 99999999999999999999", "Mark 0:1", "",
])
def test_biblical_ranges_reject_unknown_books_and_bad_numbers(reference):
    assert parse_biblical_range(reference) is None


# --- Fixture: the real pseudepigrapha registry entry with fixture passages


def _row(work_key, chapter, verse, text="Enoch text.", original=None):
    title = "1 Enoch" if work_key == "1_enoch" else "4 Ezra"
    row = {
        "author": "Anonymous", "work_key": work_key,
        "reference": f"{title} {chapter}:{verse}",
        "sort_start": chapter * 1000 + verse, "sort_end": chapter * 1000 + verse,
        "text": text, "translation": "Test English", "translation_license": "Public domain",
        "license": "Public domain", "edition": "Test edition",
        "period_tags": "second_temple" if work_key == "1_enoch" else "roman",
        "source_url": f"https://example.test/{work_key}",
    }
    if original:
        row.update(
            original_text=original, original_language="Latin", original_license="CC BY-SA 4.0",
            license=combined_license("CC BY-SA 4.0", "Public domain", "Latin"),
        )
    return row


ROWS = [
    _row("1_enoch", 1, 9, "He cometh with ten thousands of His holy ones."),
    *(_row("1_enoch", 10, verse, f"Bind Azazel, verse {verse}.") for verse in range(4, 7)),
    _row("1_enoch", 71, 14, "This is the Son of Man who is born unto righteousness."),
    _row("4_ezra", 7, 35, "Work shall follow."),
    _row("4_ezra", 7, 106, "And I answered and said."),
]
MODULE_LINKS = [
    BiblicalLink("1_enoch", "1:9", "Jud", 1, 14, 1, 15,
                 "Related text: Jude 14–15 cites a prophecy of Enoch"),
    BiblicalLink("1_enoch", "10:4", "Lev", 16, 8, 16, 10, "Shared name: Azazel"),
]
NOTES = {
    "notes": [
        {"corpus": "pseudepigrapha", "citation": "1 Enoch 71:14", "kind": "emendation",
         "text": "Charles's emendation; the Ethiopic reads \"You are that Son of Man\".",
         "contrast": ["Mark 14:62", "John 3:13"], "aligned": []},
        {"corpus": "pseudepigrapha", "citation": "1 En. 10:4-6", "kind": "contrast",
         "text": "Sin traced to the Watchers.", "contrast": ["Rom 5:12"], "aligned": ["Jude 6"]},
        {"corpus": "pseudepigrapha", "citation": "4 Ezra 7:36-105", "kind": "gap",
         "text": "The missing fragment is absent from the KJV and the Clementine Latin."},
    ],
    "links": [
        {"corpus": "pseudepigrapha", "citation": "1 Enoch 1:9", "relation": "aligned",
         "biblical": "Jude 14-15", "note": "Jude quotes this verse"},
        {"corpus": "pseudepigrapha", "citation": "1 Enoch 10:4-6", "relation": "aligned",
         "biblical": "Jude 6", "note": "Angels bound in darkness"},
    ],
}


@pytest.fixture
def enoch(monkeypatch):
    rows = [dict(row) for row in ROWS]
    corpus = replace(
        CORPORA["pseudepigrapha"],
        parse=lambda directory: [dict(row) for row in rows],
        require_files=lambda directory: None,
        biblical_links=lambda passages: list(MODULE_LINKS),
    )
    monkeypatch.setitem(CORPORA, "pseudepigrapha", corpus)
    return rows


def _import(tmp_path, notes=NOTES) -> Path:
    path = tmp_path / "labels.db"
    conn = sqlite3.connect(path)
    create_schema(conn)
    import_corpus(conn, "pseudepigrapha", tmp_path, parse_editorial_notes(notes))
    conn.close()
    return path


async def _call(path: Path, monkeypatch, handler, **args) -> str:
    database = StudyBibleDB(path)
    await database.connect()
    monkeypatch.setattr(server, "db", database)
    try:
        return (await handler(args))[0].text
    finally:
        await database.close()


# --- Editorial notes file

# tests/conftest.py points NOTES_PATH at an empty file for fixture imports.
COMMITTED_NOTES_PATH = Path(editorial_notes.__file__).with_name("editorial_notes.json")


def test_committed_editorial_notes_file_is_valid():
    notes = load_editorial_notes(COMMITTED_NOTES_PATH)

    assert isinstance(notes, EditorialNotes)
    assert set(json.loads(COMMITTED_NOTES_PATH.read_text(encoding="utf-8"))) == {"notes", "links"}
    assert (len(notes.notes), len(notes.links)) == (46, 40)
    by_citation = {note.citation: note for note in notes.notes}
    # Onkelos is cited by English verse: the Peniel verse is Gen 32:30 (MT 32:31).
    assert "Targum Onkelos Genesis 32:30" in by_citation
    assert "Targum Onkelos Genesis 32:31" not in by_citation
    assert by_citation["1 Enoch 71:14"].kind == "emendation"
    assert by_citation["1 Enoch 71:14"].contrast == ("Mark 14:62", "John 3:13")
    assert {note.corpus for note in notes.notes} == set(CORPORA)
    assert all(link.relation in ("aligned", "echo") for link in notes.links)


def test_single_chapter_books_are_cited_by_verse():
    notes = parse_editorial_notes({
        "notes": [{**NOTES["notes"][0], "contrast": ["Jude 6", "Jude 1:6", "Phlm 4-6"]}],
        "links": [{**NOTES["links"][0], "biblical": "Jude 6"}],
    })

    assert notes.notes[0].contrast == ("Jude 6", "Jude 6", "Phlm 4–6")
    assert (notes.links[0].book, notes.links[0].chapter, notes.links[0].verse) == ("Jud", 1, 6)
    assert (notes.links[0].end_chapter, notes.links[0].end_verse) == (1, 6)


def _note(**overrides):
    return {"notes": [{**NOTES["notes"][0], **overrides}], "links": []}


def _link(**overrides):
    return {"notes": [], "links": [{**NOTES["links"][0], **overrides}]}


@pytest.mark.parametrize("data, message", [
    ([], "expected an object"),
    ({"notes": {}}, "must be lists"),
    (_note(kind="opinion"), "kind 'opinion' is not one of"),
    (_note(contrast=["Hezekiah 3:1"]), "biblical reference 'Hezekiah 3:1' does not parse"),
    (_note(contrast="Mark 14:62"), "must be a list"),
    (_note(corpus="talmud"), "unknown corpus 'talmud'"),
    (_note(citation="1 Enoch"), "does not resolve in pseudepigrapha"),
    (_note(text=""), "'text' must be a non-empty string"),
    (_note(text="x" * 251), "longer than 250"),
    (_note(source="x"), "expected an object with fields"),
    (_link(relation="translation"), "relation 'translation' is not one of"),
    (_link(biblical="Mark"), "does not parse"),
])
def test_editorial_notes_loader_rejects_invalid_entries(data, message):
    with pytest.raises(ValueError, match=message):
        parse_editorial_notes(data)


def test_loader_renders_biblical_references():
    notes = parse_editorial_notes(NOTES)

    assert notes.notes[0].contrast == ("Mark 14:62", "John 3:13")
    assert notes.notes[1].aligned == ("Jude 6",)
    assert (notes.links[0].book, notes.links[0].verse, notes.links[0].end_verse) == ("Jud", 14, 15)


# --- Import of notes and typed links


def test_import_attaches_notes_to_every_covered_passage_and_gaps_to_neighbours(tmp_path, enoch):
    conn = sqlite3.connect(_import(tmp_path))
    notes = conn.execute(
        """SELECT p.reference, n.citation, n.kind, n.contrast, n.aligned
           FROM ancient_source_notes n JOIN ancient_source_passages p ON p.id = n.passage_id
           ORDER BY p.sort_start, p.work_key"""
    ).fetchall()
    conn.close()

    assert notes == [
        ("4 Ezra 7:35", "4 Ezra 7:36–105", "gap", "", ""),
        ("4 Ezra 7:106", "4 Ezra 7:36–105", "gap", "", ""),
        ("1 Enoch 10:4", "1 Enoch 10:4–6", "contrast", "Rom 5:12", "Jude 6"),
        ("1 Enoch 10:5", "1 Enoch 10:4–6", "contrast", "Rom 5:12", "Jude 6"),
        ("1 Enoch 10:6", "1 Enoch 10:4–6", "contrast", "Rom 5:12", "Jude 6"),
        ("1 Enoch 71:14", "1 Enoch 71:14", "emendation", "Mark 14:62; John 3:13", ""),
    ]


@pytest.mark.parametrize("citation, kind", [("1 Enoch 50:1", "caution"), ("1 Enoch 50:1-60:2", "gap")])
def test_import_fails_before_writing_when_a_note_covers_no_passage(tmp_path, enoch, citation, kind):
    path = _import(tmp_path)
    conn = sqlite3.connect(path)
    unresolved = {"notes": [{**NOTES["notes"][0], "citation": citation, "kind": kind}], "links": []}
    before = conn.execute("SELECT COUNT(*) FROM ancient_source_notes").fetchone()

    # A gap note needs a passage on at least one side: 1 Enoch 50–60 has 10:6 before it.
    if kind == "gap":
        import_corpus(conn, "pseudepigrapha", tmp_path, parse_editorial_notes(unresolved))
        assert conn.execute("SELECT COUNT(*) FROM ancient_source_notes").fetchone() == (2,)
    else:
        with pytest.raises(ValueError, match="does not resolve to an imported passage"):
            import_corpus(conn, "pseudepigrapha", tmp_path, parse_editorial_notes(unresolved))
        assert conn.execute("SELECT COUNT(*) FROM ancient_source_notes").fetchone() == before
    conn.close()


def test_link_import_fails_when_its_citation_covers_no_passage(tmp_path, enoch):
    path = tmp_path / "labels.db"
    conn = sqlite3.connect(path)
    create_schema(conn)
    unresolved = {"notes": [], "links": [{**NOTES["links"][0], "citation": "1 Enoch 50:1"}]}

    with pytest.raises(ValueError, match="Editorial link '1 Enoch 50:1'"):
        import_corpus(conn, "pseudepigrapha", tmp_path, parse_editorial_notes(unresolved))
    assert conn.execute("SELECT COUNT(*) FROM ancient_source_passages").fetchone() == (0,)
    conn.close()


def test_links_are_typed_and_curated_links_replace_module_links(tmp_path, enoch):
    conn = sqlite3.connect(_import(tmp_path))
    links = conn.execute(
        """SELECT p.reference, l.biblical_book, l.sort_start, l.sort_end, l.relation,
                  l.relationship_note
           FROM ancient_source_biblical_links l
           JOIN ancient_source_passages p ON p.id = l.passage_id
           ORDER BY p.sort_start, l.biblical_book"""
    ).fetchall()
    conn.close()

    assert links == [
        # The file's aligned link replaces the module's echo link to the same range.
        ("1 Enoch 1:9", "Jud", 1014, 1015, "aligned", "Jude quotes this verse"),
        ("1 Enoch 10:4", "Jud", 1006, 1006, "aligned", "Angels bound in darkness"),
        ("1 Enoch 10:4", "Lev", 16008, 16010, "shared_tradition", "Shared name: Azazel"),
        ("1 Enoch 10:5", "Jud", 1006, 1006, "aligned", "Angels bound in darkness"),
        ("1 Enoch 10:6", "Jud", 1006, 1006, "aligned", "Angels bound in darkness"),
    ]


def test_module_links_get_relations_from_their_notes():
    assert default_link_relation("Related text: Jude 14–15 cites a prophecy") == "echo"
    assert default_link_relation("Quotes and expounds: the creation") == "echo"
    assert default_link_relation("Explicit reference: the eagle is the kingdom") == "echo"
    assert default_link_relation("Narrative overlap: Noah and the flood") == "shared_tradition"
    assert BiblicalLink("w", "1", "Gen", 1, 1, 1, 1, "x", "contrast").relation == "contrast"
    with pytest.raises(ValueError, match="Unknown link relation"):
        BiblicalLink("w", "1", "Gen", 1, 1, 1, 1, "x", "parallel")

    josephus = CORPORA["josephus"].biblical_links([])
    assert {link.relation for link in josephus} == {"shared_tradition"}
    philo = {link.note.split(":")[0]: link.relation for link in CORPORA["philo"].biblical_links([])}
    assert philo["Quotes and expounds"] == philo["Expounds"] == "echo"
    assert philo["Retells"] == philo["Related figure"] == "shared_tradition"
    enoch = {(link.locator, link.book): link.relation
             for link in CORPORA["pseudepigrapha"].biblical_links([])}
    # Set explicitly: the passages Scripture takes up are aligned.
    assert enoch[("1:9", "Jud")] == enoch[("6:1", "Gen")] == "aligned"
    assert enoch[("12:11", "Dan")] == enoch[("46:1", "Dan")] == "echo"
    assert enoch[("10:4", "Lev")] == "shared_tradition"


# --- Rendering: tags, notes, links, caveats once


@pytest.mark.asyncio
async def test_lookup_prints_tag_notes_typed_links_and_caveat_once(tmp_path, enoch, monkeypatch):
    path = _import(tmp_path)
    lookup = server.handle_lookup_ancient_source

    azazel = await _call(path, monkeypatch, lookup, citation="1 Enoch 10:4-6")
    son_of_man = await _call(path, monkeypatch, lookup, citation="1 Enoch 71:14")
    jude = await _call(path, monkeypatch, lookup, citation="1 Enoch 1:9")

    assert azazel.count("*Not Scripture · Jewish pseudepigraphon (Book of the Watchers, 4th–3rd c. BC) · tier A · Charles 1912*") == 3
    # The range note prints once, at its first passage, naming its citation.
    assert azazel.count("⚠ 1 Enoch 10:4–6: Sin traced to the Watchers. (Contrast: Rom 5:12. Aligned: Jude 6)") == 1
    assert azazel.index("- Aligned: Jude 6 — Angels bound") < azazel.index("- Shared tradition: Lev 16:8–10")
    assert azazel.count("- Pseudepigrapha: Not Scripture: pseudepigrapha outside the 66-book canon") == 1
    assert azazel.count("**Sources**") == 1 and azazel.count("https://example.test/1_enoch") == 1
    assert (
        "⚠ Charles's emendation; the Ethiopic reads \"You are that Son of Man\". "
        "(Contrast: Mark 14:62; John 3:13)"
    ) in son_of_man
    assert "tier A/B" in son_of_man and "- Tier A: " in son_of_man and "- Tier B: " in son_of_man
    assert "- Aligned: Jude 14–15 — Jude quotes this verse" in jude


@pytest.mark.asyncio
async def test_out_of_range_lookup_explains_a_gap(tmp_path, enoch, monkeypatch):
    path = _import(tmp_path)

    reply = await _call(path, monkeypatch, server.handle_lookup_ancient_source, citation="4 Ezra 7:50")

    assert reply.startswith("No passage covers 4 Ezra 7:50.")
    assert "⚠ 4 Ezra 7:36–105: The missing fragment is absent" in reply


@pytest.mark.asyncio
async def test_search_shows_notes_links_and_filters_by_curated_link(tmp_path, enoch, monkeypatch):
    path = _import(tmp_path)
    search = server.handle_search_ancient_sources

    linked = await _call(
        path, monkeypatch, search, query="Azazel", corpus="pseudepigrapha", biblical_reference="Jude 6",
    )
    oversized = await _call(
        path, monkeypatch, search, query="Azazel", biblical_reference="Luke 99999999999999999999",
    )

    assert "### Anonymous, 1 Enoch 10:4" in linked
    assert "*Not Scripture · Jewish pseudepigraphon (Book of the Watchers" in linked
    assert linked.count("⚠ 1 Enoch 10:4–6: Sin traced to the Watchers.") == 1
    assert "- Aligned: Jude 6 — Angels bound in darkness" in linked
    assert linked.count("**Caveats**") == 1
    assert oversized.startswith("Unsupported biblical_reference 'Luke 99999999999999999999'")


@pytest.mark.asyncio
async def test_search_prints_one_caveat_per_corpus_and_the_tiers_present(tmp_path, enoch, monkeypatch):
    path = _import(tmp_path)
    conn = sqlite3.connect(path)
    conn.execute(
        """INSERT INTO ancient_source_passages (corpus, author, work_key, work_title, reference,
           book_number, section_number, section_end, sort_start, sort_end, text, period_tags,
           edition, translation, license, source_url)
           VALUES ('josephus', 'Flavius Josephus', 'antiquities', 'Jewish Antiquities',
                   'Antiquities 18.116', 18, '116', 116, 18116, 18116, 'Azazel in Josephus.',
                   'roman', 'Niese', 'Whiston', 'CC BY-SA 4.0', 'https://example.test/ant')"""
    )
    conn.execute(
        """INSERT INTO ancient_source_passages_fts (passage_id, text, original_text_folded,
           original_prefix_variants) SELECT id, text, '', '' FROM ancient_source_passages
           WHERE corpus = 'josephus'"""
    )
    conn.commit()
    conn.close()

    reply = await _call(path, monkeypatch, server.handle_search_ancient_sources, query="Azazel", corpus="all")

    caveats = reply[reply.index("**Caveats**"):reply.index("**Sources**")]
    assert caveats.count("- Pseudepigrapha: Not Scripture") == 1
    assert caveats.count("- Josephus: Not Scripture") == 1
    assert "- Tier A: written before or alongside the NT." in caveats
    assert "Tier B" not in caveats


# --- F1: lookup economy


LONG_ENGLISH = " ".join(f"word{index}" for index in range(700))  # ~6,000 characters
LONG_LATIN = " ".join(f"verbum{index}" for index in range(150))  # ~1,300 characters


@pytest.fixture
def long_passages(monkeypatch):
    rows = [_row("4_ezra", 3, verse, LONG_ENGLISH, LONG_LATIN) for verse in range(1, 9)]
    corpus = replace(
        CORPORA["pseudepigrapha"],
        parse=lambda directory: [dict(row) for row in rows],
        require_files=lambda directory: None,
        biblical_links=lambda passages: [],
    )
    monkeypatch.setitem(CORPORA, "pseudepigrapha", corpus)


@pytest.mark.asyncio
async def test_lookup_defaults_to_four_capped_excerpts_within_the_budget(tmp_path, long_passages, monkeypatch):
    path = _import(tmp_path, {"notes": [], "links": []})
    lookup = server.handle_lookup_ancient_source

    default = await _call(path, monkeypatch, lookup, citation="4 Ezra 3")
    full = await _call(path, monkeypatch, lookup, citation="4 Ezra 3:1-8", limit=10, full_text=True)
    english_only = await _call(path, monkeypatch, lookup, citation="4 Ezra 3:1", include_original=False)

    assert "*Showing the first 4 of 8 overlapping passages;" in default
    assert default.count("### Anonymous, 4 Ezra 3:") == 4
    for block in default.split("### Anonymous, ")[1:]:
        english = block.split("\n\n")[1]
        latin = block.split("**Latin:** ")[1].split("\n")[0]
        assert len(english.split(" *[excerpt")[0]) <= 1501
        assert len(latin.split(" *[excerpt")[0]) <= 601
        assert f"*[excerpt of {len(LONG_ENGLISH):,} characters; full_text=true shows more]*" in english
    assert default.count("**Caveats**") == default.count("**Sources**") == 1
    assert len(default) < ANCIENT_RESPONSE_BUDGET
    # full_text lifts the excerpt caps but not the response budget.
    assert LONG_ENGLISH in full
    assert "*Stopped at the 12,000-character response budget after 1 passages. Continue from 4 Ezra 3:2.*" in full
    assert len(full) < ANCIENT_RESPONSE_BUDGET + 2000
    assert "**Latin:**" not in english_only


# --- F4: outdated databases


OLD_TABLES = """
CREATE TABLE ancient_source_passages (
    id INTEGER PRIMARY KEY AUTOINCREMENT, corpus TEXT NOT NULL, author TEXT NOT NULL,
    work_key TEXT NOT NULL, work_title TEXT NOT NULL, reference TEXT NOT NULL,
    alternate_reference TEXT, book_number INTEGER NOT NULL, section_number TEXT NOT NULL,
    section_end INTEGER NOT NULL, editorial_heading TEXT, text TEXT NOT NULL,
    original_text TEXT, period_tags TEXT NOT NULL, edition TEXT NOT NULL, translation TEXT,
    license TEXT NOT NULL, source_url TEXT NOT NULL, collection TEXT, sort_start INTEGER,
    sort_end INTEGER, original_language TEXT, original_license TEXT, translation_license TEXT,
    UNIQUE(corpus, work_key, reference)
);
CREATE VIRTUAL TABLE ancient_source_passages_fts USING fts5(
    passage_id UNINDEXED, work_title, reference, text, original_text_folded,
    tokenize = 'porter unicode61 remove_diacritics 2'
);
CREATE TABLE ancient_source_biblical_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    passage_id INTEGER NOT NULL REFERENCES ancient_source_passages(id),
    biblical_book TEXT NOT NULL, sort_start INTEGER NOT NULL, sort_end INTEGER NOT NULL,
    relationship_note TEXT NOT NULL, UNIQUE(passage_id, biblical_book, sort_start, sort_end)
);
INSERT INTO ancient_source_passages (corpus, author, work_key, work_title, reference,
    book_number, section_number, section_end, text, original_text, period_tags, edition,
    license, source_url, sort_start, sort_end)
VALUES ('qumran', 'Pesher Habakkuk', 'pesher_habakkuk', 'Pesher Habakkuk', '1QpHab 7:1–5',
        0, '', 0, '', 'ובהון רשעים', 'roman', 'e', 'l', 'u', 7001, 7005),
       ('targum', 'Targum Onkelos', 'onkelos_genesis', 'Genesis', 'Targum Onkelos Genesis 1:1',
        0, '', 0, 'In the beginning', NULL, 'amoraic', 'e', 'l', 'u', 1001, 1001);
INSERT INTO ancient_source_passages_fts (passage_id, work_title, reference, text, original_text_folded)
    SELECT id, work_title, reference, text, COALESCE(original_text, '') || ' הון' FROM ancient_source_passages;
INSERT INTO ancient_source_biblical_links (passage_id, biblical_book, sort_start, sort_end, relationship_note)
VALUES (1, 'Hab', 2004, 2004, 'Quotes and interprets: Hab 2:4'),
       (2, 'Gen', 1001, 1001, 'Translation of: Gen 1:1'),
       (2, 'Gen', 1002, 1002, 'Narrative overlap: creation');
"""


@pytest.mark.asyncio
async def test_tools_ask_for_an_upgrade_on_a_database_lacking_new_columns(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(OLD_TABLES)
    conn.close()

    search = await _call(path, monkeypatch, server.handle_search_ancient_sources, query="beginning", corpus="all")
    lookup = await _call(path, monkeypatch, server.handle_lookup_ancient_source, citation="Onkelos Genesis 1:1")

    for reply in (search, lookup):
        assert reply == server.ANCIENT_UPGRADE_MESSAGE
        assert "no such column" not in reply


@pytest.mark.asyncio
async def test_create_schema_types_old_links_and_rebuilds_the_search_index(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(OLD_TABLES)

    create_schema(conn)
    create_schema(conn)
    relations = conn.execute(
        "SELECT relationship_note, relation FROM ancient_source_biblical_links ORDER BY id"
    ).fetchall()
    fts_columns = [row[1] for row in conn.execute("PRAGMA table_info(ancient_source_passages_fts)")]
    indexed = conn.execute(
        "SELECT original_text_folded, original_prefix_variants FROM ancient_source_passages_fts "
        "WHERE passage_id = 1"
    ).fetchone()
    conn.close()

    assert relations == [
        ("Quotes and interprets: Hab 2:4", "echo"),
        ("Translation of: Gen 1:1", "translation"),
        ("Narrative overlap: creation", "shared_tradition"),
    ]
    assert "original_prefix_variants" in fts_columns
    # Rebuilt from the passages: the old mixed-in variant (' הון') is gone.
    assert indexed == ("ובהון רשעים", "בהון הון")

    exact = await _call(path, monkeypatch, server.handle_search_ancient_sources, query="רשעים", corpus="qumran")
    stripped = await _call(path, monkeypatch, server.handle_search_ancient_sources, query="הון", corpus="qumran")
    assert "1QpHab 7:1–5" in exact and "prefix match" not in exact
    assert "1QpHab 7:1–5 (prefix match)" in stripped


# --- F6: citation errors


@pytest.mark.asyncio
async def test_citation_errors_are_short_and_helpful(tmp_path, enoch, monkeypatch):
    path = _import(tmp_path)
    lookup = server.handle_lookup_ancient_source

    typo = await _call(path, monkeypatch, lookup, citation="Antiquites 18.116")
    enoc = await _call(path, monkeypatch, lookup, citation="1 Enoc 1:9")
    no_locator = await _call(path, monkeypatch, lookup, citation="4 Ezra")
    oversized = await _call(path, monkeypatch, lookup, citation="1 Enoch 1:99999999999999999999")

    assert "Did you mean Antiquities?" in typo and len(typo) < 700
    assert "Did you mean 1 Enoch?" in enoc
    # The example is the work's own first imported passage, not the corpus example.
    assert no_locator == (
        "No locator in '4 Ezra'. Expected: 4 Ezra (Pseudepigrapha, cited by chapter:verse); "
        "e.g. '4 Ezra 7:35'."
    )
    assert oversized.startswith("Could not read the locator '1:99999999999999999999'")
