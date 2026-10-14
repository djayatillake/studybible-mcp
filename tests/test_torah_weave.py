"""The pinned Torah Weave 1.1 file (Moshe Kline): parser, checksum, and verse coverage."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

import scripts.import_torah_weave as importer
from study_bible_mcp.database import StudyBibleDB, create_schema
from study_bible_mcp.parsers import torah_weave
from study_bible_mcp.parsers.torah_weave import (
    import_torah_weave,
    parse_torah_weave,
    torah_weave_rows,
)

SHIPPED = Path(__file__).resolve().parent.parent / "data" / "torah_weave" / "torah-units.json"

# The production `verses` table's Torah rows, compactly: English verses per
# chapter, and the runs it stores as English(Hebrew), e.g. 'Lev.6.1(5.20)'.
# Each run is (book, English chapter, first verse, last verse, Hebrew chapter,
# Hebrew first verse). English Numbers 26:1 also has a plain row after its
# 'Num.26.1(25.19)' row.
ENGLISH_VERSES_PER_CHAPTER = {
    "Gen": [31, 25, 24, 26, 32, 22, 24, 22, 29, 32, 32, 20, 18, 24, 21, 16, 27, 33, 38, 18, 34,
            24, 20, 67, 34, 35, 46, 22, 35, 43, 55, 32, 20, 31, 29, 43, 36, 30, 23, 23, 57, 38,
            34, 34, 28, 34, 31, 22, 33, 26],
    "Exo": [22, 25, 22, 31, 23, 30, 25, 32, 35, 29, 10, 51, 22, 31, 27, 36, 16, 27, 25, 26, 36,
            31, 33, 18, 40, 37, 21, 43, 46, 38, 18, 35, 23, 35, 35, 38, 29, 31, 43, 38],
    "Lev": [17, 16, 17, 35, 19, 30, 38, 36, 24, 20, 47, 8, 59, 57, 33, 34, 16, 30, 37, 27, 24,
            33, 44, 23, 55, 46, 34],
    "Num": [54, 34, 51, 49, 31, 27, 89, 26, 23, 36, 35, 16, 33, 45, 41, 50, 13, 32, 22, 29, 35,
            41, 30, 25, 18, 65, 23, 31, 40, 16, 54, 42, 56, 29, 34, 13],
    "Deu": [46, 37, 29, 49, 33, 25, 26, 20, 29, 22, 32, 32, 18, 29, 23, 22, 20, 22, 21, 20, 23,
            30, 25, 22, 19, 19, 26, 68, 29, 20, 30, 52, 29, 12],
}
HEBREW_RUNS = [
    ("Gen", 31, 55, 55, 32, 1), ("Gen", 32, 1, 32, 32, 2),
    ("Exo", 8, 1, 4, 7, 26), ("Exo", 8, 5, 32, 8, 1),
    ("Exo", 22, 1, 1, 21, 37), ("Exo", 22, 2, 31, 22, 1),
    ("Lev", 6, 1, 7, 5, 20), ("Lev", 6, 8, 30, 6, 1),
    ("Num", 16, 36, 50, 17, 1), ("Num", 17, 1, 13, 17, 16), ("Num", 26, 1, 1, 25, 19),
    ("Num", 29, 40, 40, 30, 1), ("Num", 30, 1, 16, 30, 2),
    ("Deu", 12, 32, 32, 13, 1), ("Deu", 13, 1, 18, 13, 2), ("Deu", 22, 30, 30, 23, 1),
    ("Deu", 23, 1, 25, 23, 2), ("Deu", 29, 1, 1, 28, 69), ("Deu", 29, 2, 29, 29, 1),
]
ALSO_PLAIN = {("Num", 26, 1)}
BOOK_NAMES = {"Gen": "Genesis", "Exo": "Exodus", "Lev": "Leviticus", "Num": "Numbers",
              "Deu": "Deuteronomy"}


def torah_verse_rows() -> list[tuple[str, str, int, int]]:
    """(reference, book, chapter, verse) for the Torah, as the verses table holds them."""
    hebrew = {}
    for book, chapter, first, last, hebrew_chapter, hebrew_first in HEBREW_RUNS:
        for verse in range(first, last + 1):
            hebrew[(book, chapter, verse)] = (hebrew_chapter, hebrew_first + verse - first)
    rows = []
    for book, counts in ENGLISH_VERSES_PER_CHAPTER.items():
        for chapter, count in enumerate(counts, 1):
            for verse in range(1, count + 1):
                key = (book, chapter, verse)
                if key in hebrew:
                    rows.append((f"{book}.{chapter}.{verse}({hebrew[key][0]}.{hebrew[key][1]})",
                                 book, chapter, verse))
                if key not in hebrew or key in ALSO_PLAIN:
                    rows.append((f"{book}.{chapter}.{verse}", book, chapter, verse))
    return rows


def test_the_shipped_file_is_kline_version_1_1():
    content = SHIPPED.read_bytes()
    assert hashlib.sha256(content).hexdigest() == torah_weave.TORAH_WEAVE_SHA256
    data = json.loads(content)
    assert (data["version"], data["author"], data["license"]) == ("1.1", "Moshe Kline", "CC BY 4.0")
    assert data["version"] == torah_weave.TORAH_WEAVE_VERSION
    assert (data["total_units"], data["total_cells"], data["total_cells_with_subdivisions"]) == (
        86, 600, 1019
    )


def test_every_cell_of_the_shipped_file_parses():
    units, cells = torah_weave_rows(SHIPPED)
    assert (len(units), len(cells)) == (86, 1019)
    assert [cell[0] for cell in cells] == list(range(1, 1020))
    per_unit: dict[int, int] = {}
    for cell in cells:
        per_unit[cell[1]] = per_unit.get(cell[1], 0) + 1
    # 1.1 makes each unit's published count equal its cell map.
    assert {unit[0]: unit[-1] for unit in units} == per_unit
    for cell in cells:
        assert cell[-2] <= cell[-1]  # sort_start <= sort_end


def test_the_parser_reads_each_label_and_range_form():
    data = {"units": [{
        "serial_number": 84, "book": "Deuteronomy", "unit_number": 11, "title": "Covenant",
        "verses": "Deuteronomy 28:69-30:20", "verse_range": "28:69-30:20", "format": "12221",
        "irregular": True, "unique": False, "cells": 3, "type": "F",
        "cell_count_with_subdivisions": 5,
        "cells_detail": {"1": "28:69", "2Aa": "29:1-29:5", "10Ac": "29:6-8",
                         "2B": "29:9-30:1", "3Bc": "30:2"},
    }]}
    [(unit, cells)] = list(parse_torah_weave(data))
    assert (unit["id"], unit["book"], unit["irregular"], unit["is_unique"], unit["type"]) == (
        84, "Deu", 1, 0, "F"
    )
    assert [
        (c["cell_label"], c["row_num"], c["column_letter"], c["subdivision"], c["chapter_start"],
         c["verse_start"], c["chapter_end"], c["verse_end"], c["sort_start"], c["sort_end"])
        for c in cells
    ] == [
        ("1", 1, "", None, 28, 69, 28, 69, 28069, 28069),
        ("2Aa", 2, "A", "a", 29, 1, 29, 5, 29001, 29005),
        ("10Ac", 10, "A", "c", 29, 6, 29, 8, 29006, 29008),
        ("2B", 2, "B", None, 29, 9, 30, 1, 29009, 30001),
        ("3Bc", 3, "B", "c", 30, 2, 30, 2, 30002, 30002),
    ]


@pytest.mark.parametrize("label, verses, message", [
    ("A1", "1:1", "Invalid cell label"),
    ("1A", "1:1-", "Invalid verse range"),
    ("1A", "Genesis 1:1", "Invalid verse range"),
    ("1A", "6:4-6:1", "runs backwards"),
])
def test_the_parser_refuses_a_cell_it_cannot_read(label, verses, message):
    data = {"units": [{"serial_number": 1, "book": "Genesis", "unit_number": 1, "title": "T",
                       "cells_detail": {label: verses}}]}
    with pytest.raises(ValueError, match=message):
        list(parse_torah_weave(data))


def _tampered(tmp_path: Path) -> Path:
    path = tmp_path / "torah-units.json"
    path.write_bytes(SHIPPED.read_bytes().replace(b'"2B": "1:14-1:19"', b'"2B": "1:14-1:18"', 1))
    assert path.read_bytes() != SHIPPED.read_bytes()
    return path


def test_a_file_with_another_checksum_is_refused_and_nothing_changes(tmp_path, monkeypatch):
    db = tmp_path / "study_bible.db"
    conn = sqlite3.connect(db)
    create_schema(conn)
    import_torah_weave(conn, SHIPPED)
    before = conn.execute("SELECT * FROM torah_weave_cells ORDER BY id").fetchall()
    with pytest.raises(ValueError, match="Checksum mismatch"):
        import_torah_weave(conn, _tampered(tmp_path))
    assert conn.execute("SELECT * FROM torah_weave_cells ORDER BY id").fetchall() == before
    conn.close()

    monkeypatch.setattr(importer, "get_data_path", lambda: _tampered(tmp_path))
    monkeypatch.setattr("sys.argv", ["import_torah_weave.py", str(db)])
    assert importer.main() == 1
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT * FROM torah_weave_cells ORDER BY id").fetchall() == before
    conn.close()


def test_a_file_with_the_wrong_number_of_cells_is_refused(monkeypatch):
    monkeypatch.setattr(torah_weave, "TORAH_WEAVE_EXPECTED_CELLS", 952)
    with pytest.raises(ValueError, match="1019 cells; expected 86 and 952"):
        torah_weave_rows(SHIPPED)


def test_reimporting_gives_the_tables_of_a_fresh_import(tmp_path, monkeypatch):
    def dump(path: Path) -> list:
        conn = sqlite3.connect(path)
        rows = [conn.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
                for table in ("torah_weave_units", "torah_weave_cells")]
        rows.append(conn.execute(
            "SELECT seq FROM sqlite_sequence WHERE name = 'torah_weave_cells'").fetchall())
        conn.close()
        return rows

    paths = []
    for name, runs in (("fresh.db", 1), ("again.db", 3)):
        path = tmp_path / name
        sqlite3.connect(path).close()
        monkeypatch.setattr("sys.argv", ["import_torah_weave.py", str(path)])
        for _ in range(runs):
            assert importer.main() == 0
        paths.append(path)
    assert dump(paths[0]) == dump(paths[1])
    assert dump(paths[0])[2] == [(1019,)]


@pytest.fixture
async def torah_db(tmp_path):
    path = tmp_path / "torah.db"
    conn = sqlite3.connect(path)
    create_schema(conn)
    conn.executemany(
        "INSERT INTO verses (reference, book, chapter, verse) VALUES (?, ?, ?, ?)",
        torah_verse_rows(),
    )
    import_torah_weave(conn, SHIPPED)
    conn.close()
    database = StudyBibleDB(path)
    await database.connect()
    yield database
    await database.close()


async def test_every_torah_verse_is_in_a_cell_but_deuteronomy_5_30_to_33(torah_db):
    """Verse by verse in English numbering, as get_torah_weave looks them up."""
    no_cell = []
    for _, book, chapter, verse in torah_verse_rows():
        reference = f"{BOOK_NAMES[book]} {chapter}:{verse}"
        if reference not in no_cell and not await torah_db.get_torah_weave_cells_for_reference(reference):
            no_cell.append(reference)
    assert no_cell == [
        "Exodus 20:23", "Exodus 20:24", "Exodus 20:25", "Exodus 20:26",
        "Deuteronomy 5:30", "Deuteronomy 5:31", "Deuteronomy 5:32", "Deuteronomy 5:33",
    ]
    # Deuteronomy 5:30-33 sit in unit 76 without a cell; Exodus 20:23-26 are in
    # no unit (Kline's units 26 and 27 end at 20:22 and start at 21:1).
    [unit] = await torah_db.get_torah_weave_units_in_passage("Deu", (5, 30), (5, 33))
    assert unit["id"] == 76
    assert await torah_db.get_torah_weave_units_in_passage("Exo", (20, 23), (20, 26)) == []
