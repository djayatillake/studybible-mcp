"""scripts/repair_editorial_corrections.py: install the editorial corrections in place.

The fixture builds a database from the current sources with the real
importers, then sets every row the script tracks back to a stand-in for its
previous value (and removes the new case and links), with the script's BEFORE
fingerprints pointed at those stand-ins. The deployed rows themselves were
checked against the previous sources when the fingerprints were made.
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

import scripts.repair_editorial_corrections as repair
from scripts.import_heiser_content import (
    import_content_file,
    import_nt_ot_lxx_quote_hints,
    import_textual_variants,
    import_themes,
)
from scripts.ingest_burnett_gage import BURNETT_THEOLOGY
from study_bible_mcp.database import create_schema
from study_bible_mcp.parsers.ane_context import parse_ane_context_file

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
ENOCH = sorted({citation for _, citation, _ in repair.LINKS})


def _build(path: Path) -> None:
    """A database holding the corrected rows, as a fresh build makes them (no new links)."""
    conn = sqlite3.connect(path)
    create_schema(conn)
    import_textual_variants(conn, DATA / "heiser" / "variants")
    import_nt_ot_lxx_quote_hints(conn, DATA / "heiser" / "lxx_quote_hints.json")
    import_themes(conn, DATA / "heiser" / "themes.json")
    for content in sorted((DATA / "heiser" / "content").glob("*.json")):
        import_content_file(conn, content)
    for entry in BURNETT_THEOLOGY:
        conn.execute(
            """INSERT INTO theology_content
               (source_work, source_author, source_type, chapter_or_episode, title,
                content_summary, content_detail, page_range, url)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            tuple(entry[key] for key in (
                "source_work", "source_author", "source_type", "chapter_or_episode", "title",
                "content_summary", "content_detail", "page_range", "url",
            )),
        )
    for dimension in sorted((DATA / "ane_context").glob("*.json")):
        for entry, _ in parse_ane_context_file(dimension):
            columns = [key for key in entry if key != "books"]
            conn.execute(
                f"INSERT INTO ane_entries ({', '.join(columns)}) "
                f"VALUES ({', '.join('?' for _ in columns)})",
                [entry[column] for column in columns],
            )
    for number, reference in enumerate(ENOCH, start=1):
        chapter, verse = map(int, reference.split()[-1].split(":"))
        conn.execute(
            """INSERT INTO ancient_source_passages
               (corpus, author, work_key, work_title, reference, book_number, section_number,
                section_end, text, period_tags, edition, license, source_url, sort_start, sort_end)
               VALUES ('pseudepigrapha', 'Anonymous', '1_enoch', '1 Enoch', ?, 0, ?, 0, ?,
                       'second_temple', 'Charles 1912', 'Public domain', 'https://example.test',
                       ?, ?)""",
            (reference, str(number), f"Text of {reference}", chapter * 1000 + verse,
             chapter * 1000 + verse),
        )
    conn.commit()
    conn.close()


def _stale(conn: sqlite3.Connection) -> None:
    """Set every tracked row back to a stand-in for its previous value."""
    for reference, case_key in repair.CASES:
        case = conn.execute(
            "SELECT id FROM textual_variant_cases WHERE reference = ? AND case_key = ?",
            (reference, case_key),
        ).fetchone()[0]
        if (reference, case_key) == ("Gen.6.2", "LXX_manuscript_variant"):
            for table in ("textual_variant_witnesses", "textual_variant_readings",
                          *repair.CLAIM_TABLES):
                conn.execute(f"DELETE FROM {table} WHERE case_id = ?", (case,))
            conn.execute("DELETE FROM textual_variant_cases WHERE id = ?", (case,))
        else:
            conn.execute(
                "UPDATE textual_variant_readings SET text = text || ' (previous)' "
                "WHERE case_id = ?", (case,),
            )
    for nt, ot in repair.HINTS:
        conn.execute(
            "UPDATE nt_ot_lxx_quote_hints SET divergence_note = 'previous note' "
            "WHERE nt_reference = ? AND ot_reference = ?", (nt, ot),
        )
    for kind, keys in (("theme", [[k] for k in repair.THEMES]),
                       ("content", [list(k) for k in repair.CONTENT]),
                       ("ane", [[k] for k in repair.ANE])):
        table, key_columns, columns = repair.ROW_TABLES[kind]
        where = " AND ".join(f"{column} IS ?" for column in key_columns)
        for key in keys:
            conn.execute(
                f"UPDATE {table} SET {columns[0]} = 'previous: ' || {columns[0]} WHERE {where}",
                key,
            )
    conn.commit()


def _snapshot(path: Path) -> dict:
    """Every row of the tables the script may touch, without ids."""
    conn = sqlite3.connect(path)
    cases = {
        key: repair.read_case(conn, *key)
        for key in conn.execute("SELECT reference, case_key FROM textual_variant_cases")
    }
    hints = {
        key: repair.read_hint(conn, *key)
        for key in conn.execute("SELECT nt_reference, ot_reference FROM nt_ot_lxx_quote_hints")
    }
    tables = {
        table: sorted(conn.execute(f"SELECT {columns} FROM {table}").fetchall(), key=repr)
        for table, columns in (
            ("theology_themes", "theme_key, description"),
            ("theology_content", "source_work, chapter_or_episode, title, content_summary, content_detail"),
            ("ane_entries", "id, summary, detail, ane_parallels, interpretive_significance"),
            ("ancient_source_biblical_links",
             "passage_id, biblical_book, sort_start, sort_end, relationship_note, relation"),
        )
    }
    conn.close()
    return {"cases": cases, "hints": hints, **tables}


@pytest.fixture
def fresh_db(tmp_path) -> Path:
    path = tmp_path / "fresh.db"
    _build(path)
    return path


@pytest.fixture
def stale_db(tmp_path, monkeypatch) -> Path:
    path = tmp_path / "study_bible.db"
    _build(path)
    conn = sqlite3.connect(path)
    _stale(conn)
    # BEFORE names what this database holds now. (The deployed fingerprints
    # were checked against the previous sources when they were recorded.)
    monkeypatch.setattr(repair, "BEFORE", _AnyBefore())
    items = repair.compute_changes(DATA)
    before = {
        repair._label(item): repair.digest(repair._current(conn, item))
        for group in items.values() for item in group
    }
    conn.close()
    monkeypatch.setattr(repair, "BEFORE", before)
    return path


class _AnyBefore(dict):
    def __missing__(self, key):
        return None


def _run(monkeypatch, *argv) -> int:
    monkeypatch.setattr("sys.argv", ["repair_editorial_corrections.py", *map(str, argv)])
    return repair.main()


def _case_ids(path: Path) -> dict:
    conn = sqlite3.connect(path)
    ids = {
        (reference, case_key): case_id
        for case_id, reference, case_key in conn.execute(
            "SELECT id, reference, case_key FROM textual_variant_cases"
        )
    }
    conn.close()
    return ids


def _installed_links(path: Path) -> list[tuple]:
    conn = sqlite3.connect(path)
    rows = conn.execute(
        """SELECT p.reference, l.biblical_book, l.sort_start, l.sort_end, l.relation
           FROM ancient_source_biblical_links l
           JOIN ancient_source_passages p ON p.id = l.passage_id ORDER BY l.id"""
    ).fetchall()
    conn.close()
    return rows


def test_before_names_every_tracked_item_and_only_new_ones_are_absent():
    labels = {
        *(f"case {reference} {key}" for reference, key in repair.CASES),
        *(f"hint {nt} -> {ot}" for nt, ot in repair.HINTS),
        *(f"theme {key}" for key in repair.THEMES),
        *("content " + " / ".join(key) for key in repair.CONTENT),
        *(f"ane {key}" for key in repair.ANE),
    }
    assert labels <= set(repair.BEFORE)
    absent = {label for label, value in repair.BEFORE.items() if value is None}
    assert absent == {"case Gen.6.2 LXX_manuscript_variant"} | {
        label for label in repair.BEFORE if label.startswith("link ")
    }
    assert len([label for label in repair.BEFORE if label.startswith("link ")]) == len(repair.LINKS)


def test_repair_from_source_matches_a_fresh_build_and_is_idempotent(
    stale_db, fresh_db, tmp_path, monkeypatch, capsys
):
    patch = tmp_path / "patch.json.gz"
    case_ids = _case_ids(stale_db)

    assert _run(monkeypatch, stale_db, "--write-patch", patch) == 0
    out = capsys.readouterr().out
    total = len(repair.CASES) + len(repair.HINTS) + len(repair.THEMES) + len(repair.CONTENT) \
        + len(repair.ANE) + len(repair.LINKS)
    assert f"0 of {total} already held the corrected rows" in out

    after, fresh = _snapshot(stale_db), _snapshot(fresh_db)
    links = after.pop("ancient_source_biblical_links")
    assert fresh.pop("ancient_source_biblical_links") == []
    assert after == fresh
    assert len(links) == len(repair.LINKS)
    assert ("1 Enoch 69:29", "Mat", 25031, 25031, "aligned") in _installed_links(stale_db)
    # Existing case ids are kept.
    current = _case_ids(stale_db)
    assert all(current[key] == case_id for key, case_id in case_ids.items())

    with gzip.open(patch, "rt", encoding="utf-8") as handle:
        saved = json.load(handle)
    assert [(c["reference"], c["case_key"]) for c in saved["cases"]] == list(repair.CASES)
    assert all(item["before"] == repair.BEFORE[repair._label(item)]
               for group in saved.values() for item in group)

    assert _run(monkeypatch, stale_db) == 0
    out = capsys.readouterr().out
    assert "installed" not in out
    assert f"{total} of {total} already held the corrected rows" in out


def test_patch_repairs_a_copy_with_the_standard_library_only(stale_db, tmp_path, monkeypatch):
    server = tmp_path / "server"
    server.mkdir()
    shutil.copy(stale_db, server / "study_bible.db")
    shutil.copy(ROOT / "scripts" / "repair_editorial_corrections.py", server)
    assert _run(monkeypatch, stale_db, "--write-patch", server / "patch.gz") == 0

    # -I -S: no site-packages and no project source, as on the server.
    command = [sys.executable, "-I", "-S", "repair_editorial_corrections.py",
               "study_bible.db", "--apply-patch", "patch.gz"]
    first = subprocess.run(command, cwd=server, capture_output=True, text=True)
    second = subprocess.run(command, cwd=server, capture_output=True, text=True)

    assert first.returncode == 0, first.stderr
    assert "installed" in first.stdout
    assert second.returncode == 0, second.stderr
    assert "installed" not in second.stdout
    assert _snapshot(server / "study_bible.db") == _snapshot(stale_db)


def test_patch_refuses_a_database_that_differs(stale_db, tmp_path, monkeypatch, capsys):
    patch = tmp_path / "patch.json.gz"
    copy = tmp_path / "copy.db"
    shutil.copy(stale_db, copy)
    assert _run(monkeypatch, stale_db, "--write-patch", patch) == 0
    capsys.readouterr()

    # An ANE entry edited since the patch was made: nothing at all is changed.
    conn = sqlite3.connect(copy)
    conn.execute("UPDATE ane_entries SET summary = 'edited elsewhere' WHERE id = 'method_007'")
    conn.commit()
    conn.close()
    before = _snapshot(copy)
    assert _run(monkeypatch, copy, "--apply-patch", patch) == 1
    err = capsys.readouterr().err
    assert "ane method_007 holds neither" in err and "Nothing was changed" in err
    assert _snapshot(copy) == before

    # A link whose passage the database lacks.
    shutil.copy(stale_db, copy)
    conn = sqlite3.connect(copy)
    conn.execute("DELETE FROM ancient_source_passages WHERE reference = '1 Enoch 69:29'")
    conn.commit()
    conn.close()
    before = _snapshot(copy)
    assert _run(monkeypatch, copy, "--apply-patch", patch) == 1
    assert "link 1 Enoch 69:29 -> Dan 7013-7014: the database has no passage 1 Enoch 69:29" \
        in capsys.readouterr().err
    assert _snapshot(copy) == before


def test_source_mode_refuses_sources_without_a_tracked_item(stale_db, tmp_path, monkeypatch):
    data = tmp_path / "data"
    shutil.copytree(DATA / "heiser", data / "heiser")
    shutil.copytree(DATA / "ane_context", data / "ane_context")
    themes = json.loads((data / "heiser" / "themes.json").read_text(encoding="utf-8"))
    themes["themes"] = [t for t in themes["themes"] if t["theme_key"] != "cherem_warfare"]
    (data / "heiser" / "themes.json").write_text(json.dumps(themes), encoding="utf-8")
    before = _snapshot(stale_db)

    with pytest.raises(SystemExit, match="lack theme cherem_warfare"):
        _run(monkeypatch, stale_db, "--data-dir", data)
    assert _snapshot(stale_db) == before
