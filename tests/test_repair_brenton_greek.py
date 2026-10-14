"""scripts/repair_brenton_greek.py: recompute Brenton's columns of the LXX rows in place."""

from __future__ import annotations

import gzip
import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

import scripts.repair_brenton_greek as repair
from tests.test_biblical_versions import _build_db

COLUMNS = ("translation", "brenton_greek_differs", "brenton_greek", "brenton_greek_difference")


def _rows(db: Path) -> dict[tuple, tuple]:
    conn = sqlite3.connect(db)
    rows = {
        tuple(row[:3]): tuple(row[3:])
        for row in conn.execute(
            f"SELECT edition, edition_reference, canonical_reference, {', '.join(COLUMNS)} "
            "FROM biblical_version_verses"
        )
    }
    conn.close()
    return rows


@pytest.fixture
def setup(tmp_path):
    """A database whose Brenton columns hold stale values, the sources, and the fresh rows."""
    db = _build_db(tmp_path)
    fresh = _rows(db)
    conn = sqlite3.connect(db)
    # What the old importer left: another verse's English, the wrong Greek and
    # summary for a real difference, and a difference where Brenton's Greek agrees.
    conn.execute("UPDATE biblical_version_verses SET translation = 'Misplaced.' WHERE edition_reference = 'Psa.81.6'")
    conn.execute(
        "UPDATE biblical_version_verses SET brenton_greek_differs = 1, brenton_greek = 'Καὶ', "
        "brenton_greek_difference = 'Brenton''s Greek lacks: ...' WHERE edition_reference = 'Psa.39.7'"
    )
    conn.execute(
        "UPDATE biblical_version_verses SET brenton_greek_differs = 1, brenton_greek = 'Ἡ ὅρασις', "
        "brenton_greek_difference = 'stale' WHERE edition_reference = 'Dan.3.92' AND edition LIKE '%Theodotion'"
    )
    conn.commit()
    conn.close()
    return db, tmp_path / "data", fresh


def _run(monkeypatch, *argv) -> int:
    monkeypatch.setattr("sys.argv", ["repair_brenton_greek.py", *map(str, argv)])
    return repair.main()


def test_repair_matches_a_fresh_import_and_is_idempotent(setup, monkeypatch, capsys):
    db, data_dir, fresh = setup
    assert _rows(db) != fresh
    assert _run(monkeypatch, db, "--data-dir", data_dir) == 0
    assert _rows(db) == fresh
    out = capsys.readouterr().out
    assert "3 to update (3 updated)" in out
    assert "translation 1, brenton_greek_differs 1, brenton_greek 2, brenton_greek_difference 2" in out

    assert _run(monkeypatch, db, "--data-dir", data_dir) == 0
    assert "0 to update (0 updated)" in capsys.readouterr().out


def test_patch_repairs_a_copy_with_the_standard_library_only(setup, monkeypatch, tmp_path):
    db, data_dir, fresh = setup
    copy = tmp_path / "copy.db"
    shutil.copy(db, copy)
    patch = tmp_path / "brenton_greek.patch.gz"
    assert _run(monkeypatch, db, "--data-dir", data_dir, "--write-patch", patch) == 0
    with gzip.open(patch, "rt", encoding="utf-8") as handle:
        changes = json.load(handle)["update"]
    assert sorted(change["row"][1] for change in changes.values()) == ["Dan.3.92", "Psa.39.7", "Psa.81.6"]

    server = tmp_path / "server"
    server.mkdir()
    script = shutil.copy(Path(repair.__file__), server / "repair_brenton_greek.py")
    for _ in range(2):  # the second run is a no-op
        result = subprocess.run(
            [sys.executable, "-I", "-S", script, copy, "--apply-patch", patch],
            capture_output=True, text=True, cwd=server,
        )
        assert result.returncode == 0, result.stderr
    assert _rows(copy) == _rows(db) == fresh


def test_a_row_holding_unexpected_values_stops_the_whole_repair(setup, monkeypatch, tmp_path):
    db, data_dir, _ = setup
    copy = tmp_path / "copy.db"
    shutil.copy(db, copy)
    patch = tmp_path / "brenton_greek.patch.gz"
    assert _run(monkeypatch, db, "--data-dir", data_dir, "--write-patch", patch) == 0

    conn = sqlite3.connect(copy)
    conn.execute("UPDATE biblical_version_verses SET translation = 'Edited by hand.' WHERE edition_reference = 'Psa.81.6'")
    conn.commit()
    conn.close()
    before = _rows(copy)
    assert _run(monkeypatch, copy, "--apply-patch", patch) == 1
    assert _rows(copy) == before


def test_a_table_built_from_other_sources_is_refused(setup, monkeypatch):
    db, data_dir, _ = setup
    conn = sqlite3.connect(db)
    conn.execute("DELETE FROM biblical_version_verses WHERE edition_reference = 'Tob.1.1'")
    conn.commit()
    conn.close()
    before = _rows(db)
    with pytest.raises(SystemExit, match="does not hold the rows of these LXX sources"):
        _run(monkeypatch, db, "--data-dir", data_dir)
    assert _rows(db) == before
