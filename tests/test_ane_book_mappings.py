"""ANE book mappings: each book of an entry has its own chapter range.

Twenty-one entries used to list several books with one entry-level range that
the parser copied to every book (Exodus 25-40 also became Revelation 25-40).
The data now gives per-book ranges, the parser refuses the old shape, and
scripts/repair_ane_book_mappings.py swaps a deployed database's rows.
"""

from __future__ import annotations

import gzip
import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

import scripts.repair_ane_book_mappings as repair
from scripts.build_database import import_ane_context
from study_bible_mcp.database import create_schema
from study_bible_mcp.parsers.ane_context import parse_ane_context_file

ROOT = Path(__file__).resolve().parent.parent
ANE_DIR = ROOT / "data" / "ane_context"

# English chapter counts, keyed by the book codes the mappings use.
CHAPTERS = {
    "Gen": 50, "Exo": 40, "Lev": 27, "Num": 36, "Deu": 34, "Jos": 24, "Jdg": 21, "Rut": 4,
    "1Sa": 31, "2Sa": 24, "1Ki": 22, "2Ki": 25, "1Ch": 29, "2Ch": 36, "Ezr": 10, "Neh": 13,
    "Est": 10, "Job": 42, "Psa": 150, "Pro": 31, "Ecc": 12, "Sng": 8, "Isa": 66, "Jer": 52,
    "Lam": 5, "Ezk": 48, "Dan": 12, "Hos": 14, "Jol": 3, "Amo": 9, "Oba": 1, "Jon": 4,
    "Mic": 7, "Nam": 3, "Hab": 3, "Zep": 3, "Hag": 2, "Zec": 14, "Mal": 4, "Mat": 28,
    "Mrk": 16, "Luk": 24, "Jhn": 21, "Act": 28, "Rom": 16, "1Co": 16, "2Co": 13, "Gal": 6,
    "Eph": 6, "Php": 4, "Col": 4, "1Th": 5, "2Th": 3, "1Ti": 6, "2Ti": 4, "Tit": 3,
    "Phm": 1, "Heb": 13, "Jas": 5, "1Pe": 5, "2Pe": 3, "1Jn": 5, "2Jn": 1, "3Jn": 1,
    "Jud": 1, "Rev": 22,
}


def _shipped_mappings() -> list[dict]:
    return [
        mapping
        for path in sorted(ANE_DIR.glob("*.json"))
        for _entry, mappings in parse_ane_context_file(path)
        for mapping in mappings
    ]


def _write_entries(tmp_path: Path, entries: list[dict]) -> Path:
    path = tmp_path / "99_test.json"
    path.write_text(json.dumps({"dimension": "test", "entries": entries}), encoding="utf-8")
    return path


# --- parser ------------------------------------------------------------------


def test_one_chapter_range_for_several_books_is_refused(tmp_path):
    path = _write_entries(tmp_path, [{
        "id": "temple", "books": ["Exo", "Rev"], "chapter_start": 25, "chapter_end": 40,
    }])
    with pytest.raises(ValueError, match=r"temple: one chapter range \(25-40\) for 2 books"):
        list(parse_ane_context_file(path))


def test_a_single_book_range_and_per_book_ranges_are_kept(tmp_path):
    path = _write_entries(tmp_path, [
        {"id": "one", "books": ["Deu"], "chapter_start": 5, "chapter_end": 5},
        {"id": "whole", "books": ["Gen", "Exo"], "chapter_start": None, "chapter_end": None},
        {"id": "each", "books": [
            {"book": "Exo", "chapter_start": 25, "chapter_end": 40},
            {"book": "Rev", "chapter_start": 21, "chapter_end": 21},
        ]},
    ])
    rows = [
        (m["entry_id"], m["book"], m["chapter_start"], m["chapter_end"])
        for _entry, mappings in parse_ane_context_file(path) for m in mappings
    ]
    assert rows == [
        ("one", "Deu", 5, 5),
        ("whole", "Gen", None, None), ("whole", "Exo", None, None),
        ("each", "Exo", 25, 40), ("each", "Rev", 21, 21),
    ]


# --- shipped data --------------------------------------------------------------


def test_every_shipped_range_lies_inside_its_book():
    for m in _shipped_mappings():
        assert m["book"] in CHAPTERS, m
        if m["chapter_start"] is None:
            assert m["chapter_end"] is None, m
            continue
        assert 1 <= m["chapter_start"] <= m["chapter_end"] <= CHAPTERS[m["book"]], m


def test_no_entry_maps_a_book_twice_over_the_same_chapters():
    spans: dict[tuple[str, str], list[tuple[int, int]]] = {}
    for m in _shipped_mappings():
        if m["chapter_start"] is not None:
            spans.setdefault((m["entry_id"], m["book"]), []).append(
                (m["chapter_start"], m["chapter_end"])
            )
    for key, ranges in spans.items():
        ranges.sort()
        for (_, end), (start, _) in zip(ranges, ranges[1:]):
            assert end < start, (key, ranges)


def test_the_temple_entry_maps_each_book_to_the_chapters_it_cites():
    temple = [
        (m["book"], m["chapter_start"], m["chapter_end"])
        for m in _shipped_mappings() if m["entry_id"] == "relig_002"
    ]
    assert temple == [("Exo", 25, 40), ("1Ki", 6, 6), ("Ezk", 40, 48), ("Rev", 21, 21)]


# --- repair script ---------------------------------------------------------------

# Stand-ins for the old parser's rows: one range copied to every book.
OLD_ROWS = [
    ("relig_002", "Exo", 25, 40), ("relig_002", "1Ki", 25, 40),
    ("relig_002", "Ezk", 25, 40), ("relig_002", "Rev", 25, 40),
    ("relig_009", "Gen", None, None),
]


def _dump(db: Path) -> list:
    conn = sqlite3.connect(db)
    rows = conn.execute(
        "SELECT entry_id, book, chapter_start, chapter_end FROM ane_book_mappings "
        "ORDER BY entry_id, book, chapter_start"
    ).fetchall()
    conn.close()
    return rows


@pytest.fixture
def fresh(tmp_path) -> list:
    """The table a fresh build of the shipped data files writes."""
    db = tmp_path / "fresh.db"
    conn = sqlite3.connect(db)
    create_schema(conn)
    import_ane_context(conn, ANE_DIR)
    conn.close()
    return _dump(db)


@pytest.fixture
def old_db(tmp_path, monkeypatch) -> Path:
    db = tmp_path / "study_bible.db"
    conn = sqlite3.connect(db)
    create_schema(conn)
    conn.executemany("INSERT INTO ane_book_mappings VALUES (?, ?, ?, ?)", OLD_ROWS)
    conn.commit()
    monkeypatch.setattr(repair, "BEFORE_FINGERPRINT", repair.fingerprint(conn))
    conn.close()
    return db


def _run(monkeypatch, *argv) -> int:
    monkeypatch.setattr("sys.argv", ["repair_ane_book_mappings.py", *map(str, argv)])
    return repair.main()


def _write_patch(monkeypatch, db: Path, tmp_path: Path) -> tuple[Path, Path]:
    """Write a patch while repairing ``db``; return (patch, an unrepaired copy)."""
    copy = tmp_path / "copy.db"
    shutil.copy(db, copy)
    patch = tmp_path / "ane_book_mappings.patch.gz"
    assert _run(monkeypatch, db, "--write-patch", patch) == 0
    return patch, copy


def test_the_pinned_before_fingerprint_is_a_full_sha256():
    assert len(repair.BEFORE_FINGERPRINT) == 64 and int(repair.BEFORE_FINGERPRINT, 16) >= 0


def test_repair_matches_a_fresh_build_and_is_idempotent(old_db, fresh, monkeypatch, capsys):
    assert _run(monkeypatch, old_db) == 0
    assert "replaced 5 mappings written by the old parser" in capsys.readouterr().out
    assert _dump(old_db) == fresh
    assert ("relig_002", "Rev", 21, 21) in fresh

    assert _run(monkeypatch, old_db) == 0
    assert "the table already holds them; nothing changed" in capsys.readouterr().out
    assert _dump(old_db) == fresh


def test_patch_repairs_a_copy_with_the_standard_library_only(old_db, fresh, monkeypatch, tmp_path):
    patch, copy = _write_patch(monkeypatch, old_db, tmp_path)
    server = tmp_path / "server"
    server.mkdir()
    script = shutil.copy(ROOT / "scripts" / "repair_ane_book_mappings.py", server)
    outputs = []
    for _ in range(2):  # the second run is a no-op
        result = subprocess.run(
            [sys.executable, "-I", "-S", script, copy, "--apply-patch", patch],
            capture_output=True, text=True, cwd=server,
        )
        assert result.returncode == 0, result.stderr
        outputs.append(result.stdout)
    assert "replaced 5 mappings" in outputs[0]
    assert "nothing changed" in outputs[1]
    assert _dump(copy) == fresh


def test_a_table_holding_other_rows_is_refused_unchanged(old_db, monkeypatch, tmp_path, capsys):
    patch, copy = _write_patch(monkeypatch, old_db, tmp_path)
    conn = sqlite3.connect(copy)
    conn.execute("UPDATE ane_book_mappings SET chapter_end = 39 WHERE book = 'Rev'")
    conn.commit()
    conn.close()
    before = _dump(copy)
    capsys.readouterr()
    assert _run(monkeypatch, copy, "--apply-patch", patch) == 1
    assert "holds neither the old parser's rows nor the corrected ones" in capsys.readouterr().err
    assert _run(monkeypatch, copy) == 1
    assert _dump(copy) == before


def test_a_failure_part_way_rolls_back_the_whole_swap(old_db, monkeypatch, tmp_path, capsys):
    patch, copy = _write_patch(monkeypatch, old_db, tmp_path)
    with gzip.open(patch, "rt", encoding="utf-8") as handle:
        saved = json.load(handle)
    # A repeat of a chapter-specific row: the insert fails after the delete.
    saved["rows"].append(next(row for row in saved["rows"] if row[2] is not None))
    saved["to"] = repair.rows_fingerprint(saved["rows"])
    broken = tmp_path / "broken.patch.gz"
    with gzip.open(broken, "wt", encoding="utf-8") as handle:
        json.dump(saved, handle)
    before = _dump(copy)
    assert _run(monkeypatch, copy, "--apply-patch", broken) == 1
    assert "UNIQUE constraint failed" in capsys.readouterr().err
    assert _dump(copy) == before


def test_a_patch_whose_rows_do_not_match_its_fingerprint_is_refused(old_db, monkeypatch, tmp_path):
    patch, copy = _write_patch(monkeypatch, old_db, tmp_path)
    with gzip.open(patch, "rt", encoding="utf-8") as handle:
        saved = json.load(handle)
    saved["rows"][0][3] += 1
    edited = tmp_path / "edited.patch.gz"
    with gzip.open(edited, "wt", encoding="utf-8") as handle:
        json.dump(saved, handle)
    before = _dump(copy)
    assert _run(monkeypatch, copy, "--apply-patch", edited) == 1
    assert _dump(copy) == before


def test_source_data_in_the_old_shape_is_refused(old_db, monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    (data_dir / "ane_context").mkdir(parents=True)
    _write_entries(data_dir / "ane_context", [{
        "id": "temple", "books": ["Exo", "Rev"], "chapter_start": 25, "chapter_end": 40,
    }])
    before = _dump(old_db)
    with pytest.raises(SystemExit, match="one chapter range"):
        _run(monkeypatch, old_db, "--data-dir", data_dir)
    assert _dump(old_db) == before
