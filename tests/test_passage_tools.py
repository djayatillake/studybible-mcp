"""Passage references in people_in_passage, get_torah_weave, and graph_enriched_search.

Texts are invented test data, not quotations.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import study_bible_mcp.server as server
from study_bible_mcp.database import StudyBibleDB, create_schema
from study_bible_mcp.tools import display_original

from .tool_handler_fixture import build_fixture_db


async def _call(tool: str, **arguments) -> str:
    response = await server.call_tool(tool, arguments)
    assert not response[0].text.startswith("Error:"), response[0].text
    return response[0].text


@pytest.fixture
async def graph_db(tmp_path, monkeypatch):
    path = tmp_path / "fixture.db"
    build_fixture_db(path)
    database = StudyBibleDB(path)
    await database.connect()
    monkeypatch.setattr(server, "db", database)
    yield database
    await database.close()


async def test_people_in_passage_reads_every_verse_of_a_range(graph_db):
    both = await _call("people_in_passage", reference="Genesis 22:1-3")
    assert both.startswith("## Entities in Genesis 22:1-3")
    for name in ("Abraham", "Isaac", "Moriah", "Binding of Isaac"):
        assert f"- **{name}**" in both
    second = await _call("people_in_passage", reference="Gen 22:2-3")
    assert "- **Isaac**" in second and "Abraham" not in second
    chapters = await _call("people_in_passage", reference="Genesis 21-22")
    assert "- **Abraham**" in chapters and "- **Moriah**" in chapters


async def test_graph_enriched_search_points_passages_to_people_in_passage(graph_db):
    for reference in ("Genesis 22", "Genesis 22:1-2"):
        assert await _call("graph_enriched_search", reference=reference) == (
            "graph_enriched_search takes a single verse (e.g. 'Genesis 22:1'). For the people, "
            f"places, and events of {reference} use people_in_passage (reference='{reference}')."
        )


def test_original_text_is_shown_without_word_markup():
    assert display_original("וַ/יִּקַּ֨ח אֶת\\־ הָ/עֵצִ֜ים") == "וַיִּקַּ֨ח אֶת־הָעֵצִ֜ים"
    assert display_original("לְ/דָוִֽד\\׃") == "לְדָוִֽד׃"
    assert display_original("מִ/פְּנֵ֤י\\׀ אַבְשָׁל֬וֹם") == "מִפְּנֵ֤י ׀ אַבְשָׁל֬וֹם"
    assert display_original("καὶ λέγων· κύριε") == "καὶ λέγων· κύριε"


async def test_graph_enriched_search_shows_every_hebrew_verse_of_an_english_verse(tmp_path, monkeypatch):
    path = tmp_path / "psalm.db"
    conn = sqlite3.connect(path)
    create_schema(conn)
    conn.executemany(
        "INSERT INTO verses (reference, book, chapter, verse, text_english, text_original) VALUES (?, ?, ?, ?, ?, ?)",
        [("Psa.51.0(51.1)", "Psa", 51, 0, "to the choirmaster", "לַ/מְנַצֵּ֗חַ מִזְמ֥וֹר לְ/דָוִֽד\\׃"),
         ("Psa.51.0(51.2)", "Psa", 51, 0, "when came Nathan", "בְּֽ/בוֹא\\־ אֵ֭לָי/ו נָתָ֣ן")],
    )
    conn.execute("INSERT INTO bsb_verses VALUES ('Psa.51.0', 'Psa', 51, 0, 'For the choirmaster (BSB test text).')")
    conn.execute("INSERT INTO graph_people (id, name) VALUES ('david_1', 'David')")
    conn.commit()
    conn.close()
    database = StudyBibleDB(path)
    await database.connect()
    monkeypatch.setattr(server, "db", database)
    try:
        output = await _call("graph_enriched_search", reference="Psalm 51:0")
    finally:
        await database.close()
    assert output.startswith(
        "## Psalm 51:0 (BSB)\n\nFor the choirmaster (BSB test text).\n\n"
        "**Original**: לַמְנַצֵּ֗חַ מִזְמ֥וֹר לְדָוִֽד׃ בְּֽבוֹא־אֵ֭לָיו נָתָ֣ן\n"
    )


# --- get_torah_weave ---------------------------------------------------------

def _torah_db(path: Path) -> Path:
    """Leviticus 5-7 (Hebrew 5:20-6:23 is English 6:1-30) and 19, with two of Kline's units."""
    conn = sqlite3.connect(path)
    create_schema(conn)
    verses = [(f"Lev.5.{v}", 5, v) for v in range(1, 20)]
    verses += [(f"Lev.6.{v}(5.{v + 19})", 6, v) for v in range(1, 8)]
    verses += [(f"Lev.6.{v}(6.{v - 7})", 6, v) for v in range(8, 31)]
    verses += [(f"Lev.7.{v}", 7, v) for v in range(1, 39)]
    verses += [(f"Lev.19.{v}", 19, v) for v in range(1, 38)]
    conn.executemany(
        "INSERT INTO verses (reference, book, chapter, verse, text_english) VALUES (?, 'Lev', ?, ?, 'gloss')",
        verses,
    )
    conn.executemany(
        """INSERT INTO torah_weave_units (id, book, book_full, unit_number, title, verses,
               verse_range, format, irregular, is_unique, cell_count, type, cell_count_with_subdivisions)
           VALUES (?, 'Lev', 'Leviticus', ?, ?, ?, ?, '3x3', 0, 0, 9, NULL, 9)""",
        [(41, 3, "Administrative Order", "Leviticus 6:1-7:38", "6:1-7:38"),
         (51, 13, "Holiness", "Leviticus 19:1-37", "19:1-37")],
    )
    # Kline's cells, in Hebrew numbers; Leviticus 19:3-19 is in no cell.
    cells = [(41, "1A", 1, "A", 6, 1, 6, 6), (41, "1B", 1, "B", 6, 7, 6, 11), (41, "2A", 2, "A", 6, 17, 6, 23),
             (51, "1A", 1, "A", 19, 1, 19, 2), (51, "2B", 2, "B", 19, 20, 19, 20)]
    conn.executemany(
        """INSERT INTO torah_weave_cells (unit_id, cell_label, row_num, column_letter, subdivision, book,
               verse_range, chapter_start, verse_start, chapter_end, verse_end, sort_start, sort_end)
           VALUES (?, ?, ?, ?, NULL, 'Lev', ?, ?, ?, ?, ?, ?, ?)""",
        [(unit, label, row, column, f"{c1}:{v1}-{c2}:{v2}", c1, v1, c2, v2, c1 * 1000 + v1, c2 * 1000 + v2)
         for unit, label, row, column, c1, v1, c2, v2 in cells],
    )
    conn.commit()
    conn.close()
    return path


@pytest.fixture
async def torah_db(tmp_path, monkeypatch):
    database = StudyBibleDB(_torah_db(tmp_path / "torah.db"))
    await database.connect()
    monkeypatch.setattr(server, "db", database)
    yield database
    await database.close()


async def test_torah_weave_reads_klines_hebrew_numbers_in_english(torah_db):
    output = await _call("get_torah_weave", reference="Leviticus 6:10")  # Hebrew 6:3
    assert '### Unit 41 · "Administrative Order" (Leviticus 6:8-7:38)' in output
    assert "**Cell verse range**: Leviticus 6:8-13" in output
    assert "- **Cell 1B** — Leviticus 6:14-18" in output
    assert "- **Cell 2A** — Leviticus 6:24-30" in output
    assert "No Torah Weave unit" in await _call("get_torah_weave", reference="Leviticus 6:3")


async def test_torah_weave_verse_in_a_unit_but_no_cell(torah_db):
    assert await _call("get_torah_weave", reference="Leviticus 19:18") == (
        "Leviticus 19:18 is in the unit below, but Kline's cell map assigns it to no cell, so it "
        "has no weave partners. The unit's cells (verse ranges in English numbering) can be looked "
        "up one verse at a time:\n\n"
        '- Unit 51 · "Holiness" (Leviticus 19:1-37); cells: 1A 19:1-2, 2B 19:20'
    )


async def test_torah_weave_lists_the_units_of_a_chapter(torah_db):
    output = await _call("get_torah_weave", reference="Leviticus 19")
    assert output == (
        "## Torah Weave units in Leviticus 19\n\n"
        '- Unit 51 · "Holiness" (Leviticus 19:1-37); cells: 1A 19:1-2, 2B 19:20\n\n'
        "Weave partners are per cell: pass one verse (e.g. reference='Leviticus 19:1') for its cell "
        "and partners."
    )
    assert '- Unit 41 · "Administrative Order" (Leviticus 6:8-7:38); cells: 1A 6:8-13, 1B 6:14-18, 2A 6:24-30' in (
        await _call("get_torah_weave", reference="Leviticus 6")
    )


@pytest.mark.parametrize("reference, message", [
    ("Leviticus 50:1", "Leviticus has no chapter 50 (chapters 5–19)."),
    ("Leviticus 19:40", "Leviticus 19 has no verse 40 (verses 1–37)."),
])
async def test_torah_weave_names_impossible_verses(torah_db, reference, message):
    assert await _call("get_torah_weave", reference=reference) == message
