"""scripts/repair_torah_weave.py: swap version 1.0 Torah Weave tables for version 1.1."""

from __future__ import annotations

import gzip
import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

import scripts.repair_torah_weave as repair
from study_bible_mcp.database import create_schema
from study_bible_mcp.parsers.torah_weave import import_torah_weave

ROOT = Path(__file__).resolve().parent.parent
SHIPPED = ROOT / "data" / "torah_weave" / "torah-units.json"

# Stand-ins for the version 1.0 rows: cell ids continue from an earlier import,
# as in production, and Leviticus 19:3-19 is in no cell.
OLD_UNITS = [
    (1, "Gen", "Genesis", 1, "Creation", "Genesis 1:1-2:3", "1:1-2:3", "3x2", 0, 0, 6, "CL", 6),
    (51, "Lev", "Leviticus", 13, "Holiness", "Leviticus 19:1-37", "19:1-37", "232", 1, 1, 7, None,
     10),
]
OLD_CELLS = [
    (940, 1, "1A", 1, "A", None, "Gen", "1:1", 1, 1, 1, 1, 1001, 1001),
    (941, 51, "1A", 1, "A", None, "Lev", "19:1-19:2", 19, 1, 19, 2, 19001, 19002),
    (942, 51, "2Ba", 2, "B", "a", "Lev", "19:20-19:22", 19, 20, 19, 22, 19020, 19022),
]


def _insert(conn: sqlite3.Connection) -> None:
    conn.executemany(f"INSERT INTO torah_weave_units VALUES ({', '.join('?' * 13)})", OLD_UNITS)
    conn.executemany(f"INSERT INTO torah_weave_cells VALUES ({', '.join('?' * 14)})", OLD_CELLS)


def _dump(db: Path) -> list:
    """Both tables in full, cell ids included, and the cells' AUTOINCREMENT counter."""
    conn = sqlite3.connect(db)
    rows = [conn.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
            for table in ("torah_weave_units", "torah_weave_cells")]
    rows.append(conn.execute(
        "SELECT seq FROM sqlite_sequence WHERE name = 'torah_weave_cells'").fetchall())
    conn.close()
    return rows


@pytest.fixture
def fresh(tmp_path) -> list:
    """The tables a fresh import of the shipped version 1.1 file writes."""
    db = tmp_path / "fresh.db"
    conn = sqlite3.connect(db)
    create_schema(conn)
    import_torah_weave(conn, SHIPPED)
    conn.close()
    return _dump(db)


@pytest.fixture
def old_db(tmp_path, monkeypatch) -> Path:
    db = tmp_path / "study_bible.db"
    conn = sqlite3.connect(db)
    create_schema(conn)
    _insert(conn)
    conn.commit()
    monkeypatch.setattr(repair, "V1_0_FINGERPRINT", repair.fingerprint(conn))
    conn.close()
    return db


def _run(monkeypatch, *argv) -> int:
    monkeypatch.setattr("sys.argv", ["repair_torah_weave.py", *map(str, argv)])
    return repair.main()


def _write_patch(monkeypatch, db: Path, tmp_path: Path) -> tuple[Path, Path]:
    """Write a patch while repairing ``db``; return (patch, an unrepaired copy)."""
    copy = tmp_path / "copy.db"
    shutil.copy(db, copy)
    patch = tmp_path / "torah_weave.patch.gz"
    assert _run(monkeypatch, db, "--write-patch", patch) == 0
    return patch, copy


def test_the_pinned_v1_0_fingerprint_is_a_full_sha256():
    assert len(repair.V1_0_FINGERPRINT) == 64 and int(repair.V1_0_FINGERPRINT, 16) >= 0


def test_repair_matches_a_fresh_import_and_is_idempotent(old_db, fresh, monkeypatch, capsys):
    assert _run(monkeypatch, old_db) == 0
    assert "replaced 2 units and 3 cells (version 1.0) with version 1.1" in capsys.readouterr().out
    assert _dump(old_db) == fresh
    assert fresh[2] == [(1019,)] and len(fresh[0]) == 86

    assert _run(monkeypatch, old_db) == 0
    assert "already hold version 1.1; nothing changed" in capsys.readouterr().out
    assert _dump(old_db) == fresh


def test_patch_repairs_a_copy_with_the_standard_library_only(old_db, fresh, monkeypatch, tmp_path):
    patch, copy = _write_patch(monkeypatch, old_db, tmp_path)
    with gzip.open(patch, "rt", encoding="utf-8") as handle:
        saved = json.load(handle)
    assert (saved["version"], saved["source_sha256"], len(saved["units"]), len(saved["cells"])) == (
        "1.1", "60ea3c92120a57180ea371ac5fdc577a993ac0839cbc8e1208717e74368a93af", 86, 1019
    )

    server = tmp_path / "server"
    server.mkdir()
    script = shutil.copy(ROOT / "scripts" / "repair_torah_weave.py", server)
    outputs = []
    for _ in range(2):  # the second run is a no-op
        result = subprocess.run(
            [sys.executable, "-I", "-S", script, copy, "--apply-patch", patch],
            capture_output=True, text=True, cwd=server,
        )
        assert result.returncode == 0, result.stderr
        outputs.append(result.stdout)
    assert "replaced 2 units and 3 cells" in outputs[0]
    assert "nothing changed" in outputs[1]
    assert _dump(copy) == fresh


def test_tables_holding_other_rows_are_refused_unchanged(old_db, monkeypatch, tmp_path, capsys):
    patch, copy = _write_patch(monkeypatch, old_db, tmp_path)
    conn = sqlite3.connect(copy)
    conn.execute("UPDATE torah_weave_cells SET verse_end = 3, sort_end = 19003 WHERE id = 941")
    conn.commit()
    conn.close()
    before = _dump(copy)
    capsys.readouterr()
    assert _run(monkeypatch, copy, "--apply-patch", patch) == 1
    assert "hold neither version 1.0 nor 1.1" in capsys.readouterr().err
    assert _run(monkeypatch, copy) == 1
    assert _dump(copy) == before


def test_a_failure_part_way_rolls_back_the_whole_swap(old_db, monkeypatch, tmp_path, capsys):
    patch, copy = _write_patch(monkeypatch, old_db, tmp_path)
    with gzip.open(patch, "rt", encoding="utf-8") as handle:
        saved = json.load(handle)
    # A second cell with the first cell's label: the insert fails after the deletes.
    saved["cells"].append([2000, *saved["cells"][0][1:]])
    saved["to"] = repair.rows_fingerprint(saved["units"], [cell[1:] for cell in saved["cells"]])
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
    saved["cells"][0][-1] += 1
    edited = tmp_path / "edited.patch.gz"
    with gzip.open(edited, "wt", encoding="utf-8") as handle:
        json.dump(saved, handle)
    before = _dump(copy)
    assert _run(monkeypatch, copy, "--apply-patch", edited) == 1
    assert _dump(copy) == before


def test_a_source_file_with_another_checksum_is_refused(old_db, monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    (data_dir / "torah_weave").mkdir(parents=True)
    (data_dir / "torah_weave" / "torah-units.json").write_bytes(SHIPPED.read_bytes() + b"\n")
    before = _dump(old_db)
    with pytest.raises(SystemExit, match="Checksum mismatch"):
        _run(monkeypatch, old_db, "--data-dir", data_dir)
    assert _dump(old_db) == before
