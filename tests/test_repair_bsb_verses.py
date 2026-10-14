"""scripts/repair_bsb_verses.py: bring an existing bsb_verses table into line with bsb.txt."""

from __future__ import annotations

import gzip
import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

import scripts.repair_bsb_verses as repair
from study_bible_mcp.database import create_schema
from study_bible_mcp.parsers import bsb

BSB_TXT = (
    "Test preamble: this test text has been dedicated to the public domain.\r\n"
    "Verse\tBerean Standard Bible\r\n"
    "Genesis 1:1\tIn the beginning God created the heavens and the earth.\r\n"
    "Psalm 3:1\tA Psalm of David. O LORD, how my foes have increased!\r\n"
    "Song of Solomon 1:4\tTake me away with you—let us hurry!\r\n"
)
# What the deployed table held: stray spaces, a speaker heading, no Psalm heading,
# and a verse the file no longer has.
OLD_ROWS = [
    ("Gen.1.1", "Gen", 1, 1, "In the beginning God created the heavens and the earth. "),
    ("Psa.3.1", "Psa", 3, 1, "O LORD, how my foes have increased!"),
    ("Sng.1.4", "Sng", 1, 4, "Take me away with you— let us hurry! The Friends"),
    ("Xyz.1.1", "Xyz", 1, 1, "A stray row."),
]
NEW_ROWS = [
    ("Gen.1.1", "Gen", 1, 1, "In the beginning God created the heavens and the earth."),
    ("Psa.3.0", "Psa", 3, 0, "A Psalm of David."),
    ("Psa.3.1", "Psa", 3, 1, "O LORD, how my foes have increased!"),
    ("Sng.1.4", "Sng", 1, 4, "Take me away with you—let us hurry!"),
]


@pytest.fixture
def setup(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    (data_dir / "bsb").mkdir(parents=True)
    source = data_dir / "bsb" / "bsb.txt"
    source.write_bytes(BSB_TXT.encode())
    headings = tmp_path / "headings.json"
    headings.write_text(json.dumps({"3": "A Psalm of David."}), encoding="utf-8")
    monkeypatch.setattr(bsb, "BSB_SHA256", hashlib.sha256(source.read_bytes()).hexdigest())
    monkeypatch.setattr(bsb, "BSB_EXPECTED_VERSES", 3)
    monkeypatch.setattr(bsb, "BSB_PSALM_HEADINGS_PATH", headings)

    db = tmp_path / "study_bible.db"
    conn = sqlite3.connect(db)
    create_schema(conn)
    conn.executemany("INSERT INTO bsb_verses VALUES (?, ?, ?, ?, ?)", OLD_ROWS)
    conn.commit()
    conn.close()
    return db, data_dir


def _rows(db: Path) -> list[tuple]:
    conn = sqlite3.connect(db)
    rows = conn.execute(
        "SELECT reference, book, chapter, verse, text FROM bsb_verses ORDER BY reference"
    ).fetchall()
    conn.close()
    return rows


def _run(monkeypatch, *argv) -> int:
    monkeypatch.setattr("sys.argv", ["repair_bsb_verses.py", *map(str, argv)])
    return repair.main()


def test_repair_matches_a_fresh_import_and_is_idempotent(setup, monkeypatch, capsys):
    db, data_dir = setup
    assert _run(monkeypatch, db, "--data-dir", data_dir) == 0
    assert _rows(db) == sorted(NEW_ROWS)
    assert "2 updated, 1 inserted, 1 deleted" in capsys.readouterr().out

    assert _run(monkeypatch, db, "--data-dir", data_dir) == 0
    assert "0 updated, 0 inserted, 0 deleted" in capsys.readouterr().out


def test_patch_repairs_a_copy_with_the_standard_library_only(setup, monkeypatch, tmp_path):
    db, data_dir = setup
    copy = tmp_path / "copy.db"
    shutil.copy(db, copy)
    patch = tmp_path / "bsb.patch.gz"
    assert _run(monkeypatch, db, "--data-dir", data_dir, "--write-patch", patch) == 0
    with gzip.open(patch, "rt", encoding="utf-8") as handle:
        assert set(json.load(handle)["update"]) == {"Gen.1.1", "Sng.1.4"}

    server = tmp_path / "server"
    server.mkdir()
    script = shutil.copy(Path(repair.__file__), server / "repair_bsb_verses.py")
    for _ in range(2):  # the second run is a no-op
        result = subprocess.run(
            [sys.executable, "-I", "-S", script, copy, "--apply-patch", patch],
            capture_output=True, text=True, cwd=server,
        )
        assert result.returncode == 0, result.stderr
    assert _rows(copy) == sorted(NEW_ROWS)


def test_a_row_holding_unexpected_text_stops_the_whole_repair(setup, monkeypatch, tmp_path):
    db, data_dir = setup
    patch = tmp_path / "bsb.patch.gz"
    copy = tmp_path / "copy.db"
    shutil.copy(db, copy)
    assert _run(monkeypatch, db, "--data-dir", data_dir, "--write-patch", patch) == 0

    conn = sqlite3.connect(copy)
    conn.execute("UPDATE bsb_verses SET text = 'Edited by hand.' WHERE reference = 'Sng.1.4'")
    conn.commit()
    conn.close()
    before = _rows(copy)
    assert _run(monkeypatch, copy, "--apply-patch", patch) == 1
    assert _rows(copy) == before
