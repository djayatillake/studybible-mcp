"""Curated corrections to ACAI annotations attached to the wrong entity.

The corrections live in graph_curated.json ("acai"); the build applies them
(scripts/build_database.py) and scripts/repair_acai_corrections.py brings an
existing database into line.
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

import scripts.build_database as build
import scripts.repair_acai_and_header_rows as acai_reimport
import scripts.repair_acai_corrections as repair
from study_bible_mcp.database import create_schema
from study_bible_mcp.parsers import theographic
from study_bible_mcp.parsers.acai import (
    CORRECTABLE_FIELDS,
    JSON_FIELDS,
    CuratedAcaiError,
    apply_acai_corrections,
    parse_acai_dir,
)

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"

SIMEON = "A town in the territory of Simeon; also known as Ramoth-Negev."
BENJAMIN = "A town in the territory of Benjamin, where Deborah would judge Israel (Judges 4:5)."


def _entity(entity_id: str, label: str, description: str, tipnr: list[str], references: list[str],
            **fields) -> dict:
    """An ACAI entity file, its English text under localizations."""
    return {
        "id": entity_id,
        "primary_id": entity_id,
        "type": entity_id.split(":")[0],
        "alternate_sources": {"tipnr": tipnr} if tipnr else {},
        "localizations": {"eng": {
            "preferred_label": label,
            "alternate_labels": fields.pop("alternate_labels", []),
            "descriptions": [{"source": "acai", "gloss": label, "description": description}],
        }},
        "references": references,
        **fields,
    }


# Benjamin's Ramah (its references and TIPNR key) labelled as the Negev's; the
# description that belongs to it is on another entity.
ENTITIES = {
    "places": [
        _entity("place:Ramah.2", "Ramah (of the Negev)", SIMEON, ["Ramah@Jos.18.25-Mat"],
                ["06018025", "07004005", "24031015"], alternate_labels=["Rama", "Ramah"]),
        _entity("place:Ramah.4", "Ramah (of Benjamin)", BENJAMIN, ["Ramah@Jos.19.36"], ["06019036"]),
    ],
    "people": [
        _entity("person:Judah.4", "Judah", "A son of the patriarch Jacob.",
                ["David|Judah@Gen.29.35-Rev", "Judah@Gen.29.35-Rev"], ["01029035"],
                alternate_labels=["Juda", "David"], roles=["Patriarch"]),
        _entity("person:Aiah.2", "Aiah (Father of Rizpah)", "Father of Saul's concubine Rizpah.",
                ["Aiah@2Sa.3.7-"], ["10003007"], roles=["Royal Family Member", "Concubine"]),
    ],
}

CORRECTIONS = [
    {"id": "place:Ramah.2", "field": "name", "from": "Ramah (of the Negev)",
     "to": "Ramah (of Benjamin)", "source": "place:Ramah.4", "reason": "Benjamin's Ramah."},
    {"id": "place:Ramah.2", "field": "description", "from": SIMEON, "to": BENJAMIN,
     "source": "place:Ramah.4", "reason": "Benjamin's Ramah."},
    {"id": "person:Judah.4", "field": "referred_to_as", "from": ["Juda", "David"], "to": ["Juda"],
     "reason": "An ESV rendering at 2 Chr 25:28."},
    {"id": "person:Aiah.2", "field": "roles", "from": ["Royal Family Member", "Concubine"], "to": [],
     "reason": "His daughter Rizpah's roles."},
]

# What the corrected rows hold: (id, name, description, roles, referred_to_as)
CORRECTED = [
    ("person:Aiah.2", "Aiah (Father of Rizpah)", "Father of Saul's concubine Rizpah.", "[]", "[]"),
    ("person:Judah.4", "Judah", "A son of the patriarch Jacob.", '["Patriarch"]', '["Juda"]'),
    ("place:Ramah.2", "Ramah (of Benjamin)", BENJAMIN, "[]", '["Rama", "Ramah"]'),
    ("place:Ramah.4", "Ramah (of Benjamin)", BENJAMIN, "[]", "[]"),
]


@pytest.fixture
def sources(tmp_path, monkeypatch):
    """A data directory of ACAI files and a curated file with the corrections."""
    data_dir = tmp_path / "data"
    for entity_type, entities in ENTITIES.items():
        directory = data_dir / "acai" / entity_type
        directory.mkdir(parents=True)
        for entity in entities:
            (directory / f"{entity['id'].split(':', 1)[1]}.json").write_text(
                json.dumps(entity), encoding="utf-8"
            )
    curated = tmp_path / "graph_curated.json"
    curated.write_text(json.dumps({"theographic": {}, "tipnr": [], "acai": CORRECTIONS}),
                       encoding="utf-8")
    monkeypatch.setattr(theographic, "CURATED_PATH", curated)
    return data_dir


def _fixes(**changes) -> list[dict]:
    fixes = json.loads(json.dumps(CORRECTIONS))
    for index, change in changes.items():
        fixes[int(index[1:])].update(change)
    return fixes


# ---------------------------------------------------------------------------
# apply_acai_corrections
# ---------------------------------------------------------------------------


def test_corrections_move_the_text_and_leave_the_source_alone(sources):
    entities = parse_acai_dir(sources / "acai")
    corrected = apply_acai_corrections(entities, CORRECTIONS, require_all=True)

    assert corrected["place:Ramah.2"]["name"] == "Ramah (of Benjamin)"
    assert corrected["place:Ramah.2"]["description"] == BENJAMIN
    assert corrected["place:Ramah.2"]["reference_count"] == 3  # its own references stay
    assert corrected["person:Judah.4"]["referred_to_as"] == '["Juda"]'
    assert corrected["person:Aiah.2"]["roles"] == "[]"
    assert entities["place:Ramah.2"]["description"] == SIMEON
    # A source already holding the corrected value needs nothing
    assert apply_acai_corrections(corrected, CORRECTIONS, require_all=True) == corrected


def test_a_correction_that_no_longer_matches_stops_the_build(sources):
    entities = parse_acai_dir(sources / "acai")
    with pytest.raises(CuratedAcaiError, match="place:Ramah.2 description is .*review"):
        apply_acai_corrections(entities, _fixes(c1={"from": "Something else."}))
    # The text moved must be what ACAI gives the entity named as its source
    with pytest.raises(CuratedAcaiError, match="person:Judah.4 description is .*, not the"):
        apply_acai_corrections(entities, _fixes(c1={"source": "person:Judah.4"}))
    with pytest.raises(CuratedAcaiError, match="no entity place:Ramah.9"):
        apply_acai_corrections(entities, _fixes(c1={"source": "place:Ramah.9"}), require_all=True)
    with pytest.raises(CuratedAcaiError, match="no entity person:Nobody"):
        apply_acai_corrections(entities, _fixes(c2={"id": "person:Nobody"}), require_all=True)
    # Without require_all (a partial source) an absent entity is skipped
    partial = apply_acai_corrections(entities, _fixes(c2={"id": "person:Nobody"}))
    assert partial["person:Judah.4"] == entities["person:Judah.4"]
    with pytest.raises(CuratedAcaiError, match="unknown field 'id'"):
        apply_acai_corrections(entities, _fixes(c3={"field": "id"}))
    with pytest.raises(CuratedAcaiError, match="twice"):
        apply_acai_corrections(entities, CORRECTIONS + CORRECTIONS[:1])


def test_the_curated_file_is_well_formed():
    curated = theographic.load_curated(
        Path(theographic.__file__).with_name("graph_curated.json")
    )
    keys = [(fix["id"], fix["field"]) for fix in curated["acai"]]
    assert keys and len(keys) == len(set(keys))
    for fix in curated["acai"]:
        assert fix["reason"] and fix["field"] in CORRECTABLE_FIELDS, fix
        assert fix["from"] != fix["to"], fix
        if fix["field"] in JSON_FIELDS:
            assert isinstance(fix["from"], list) and isinstance(fix["to"], list), fix
        assert fix.get("source", "x:y") != fix["id"] and ":" in fix.get("source", "x:y"), fix


def test_the_build_and_the_acai_reimport_apply_the_corrections(sources, tmp_path):
    path = tmp_path / "fresh.db"
    conn = sqlite3.connect(path)
    create_schema(conn)
    build.import_acai_entities(conn, sources / "acai")
    conn.close()
    assert _corrected_rows(path) == CORRECTED

    # repair_acai_and_header_rows.py replaces the table with what a build imports
    conn = sqlite3.connect(path)
    built = sorted(
        list(row) for row in
        conn.execute(f"SELECT {', '.join(acai_reimport.ACAI_COLUMNS)} FROM acai_entities")
    )
    conn.close()
    assert sorted(acai_reimport.parse_acai(sources / "acai")) == built

    # A correction that no longer matches stops the build
    curated = json.loads(theographic.CURATED_PATH.read_text(encoding="utf-8"))
    curated["acai"][3]["from"] = ["Concubine"]
    theographic.CURATED_PATH.write_text(json.dumps(curated), encoding="utf-8")
    conn = sqlite3.connect(tmp_path / "other.db")
    create_schema(conn)
    with pytest.raises(CuratedAcaiError, match="person:Aiah.2 roles"):
        build.import_acai_entities(conn, sources / "acai")
    conn.close()


# ---------------------------------------------------------------------------
# scripts/repair_acai_corrections.py
# ---------------------------------------------------------------------------


@pytest.fixture
def stale_db(sources, tmp_path):
    """A database whose ACAI rows were imported before the corrections."""
    path = tmp_path / "study_bible.db"
    conn = sqlite3.connect(path)
    create_schema(conn)
    entities = parse_acai_dir(sources / "acai")
    conn.executemany(
        f"INSERT INTO acai_entities ({', '.join(acai_reimport.ACAI_COLUMNS)}) "
        f"VALUES ({', '.join('?' for _ in acai_reimport.ACAI_COLUMNS)})",
        [[e.get(c) for c in acai_reimport.ACAI_COLUMNS] for e in entities.values()],
    )
    conn.commit()
    conn.close()
    return path, sources


def _corrected_rows(path: Path) -> list[tuple]:
    conn = sqlite3.connect(path)
    rows = conn.execute(
        "SELECT id, name, description, roles, referred_to_as FROM acai_entities ORDER BY id"
    ).fetchall()
    conn.close()
    return rows


def _table(path: Path) -> list[tuple]:
    conn = sqlite3.connect(path)
    rows = conn.execute("SELECT * FROM acai_entities ORDER BY id").fetchall()
    conn.close()
    return rows


def _run(monkeypatch, *argv) -> int:
    monkeypatch.setattr("sys.argv", ["repair_acai_corrections.py", *map(str, argv)])
    return repair.main()


def test_repair_matches_a_fresh_import_and_is_idempotent(stale_db, tmp_path, monkeypatch, capsys):
    path, data_dir = stale_db
    stale = _table(path)
    patch = tmp_path / "patch.json.gz"
    assert _run(monkeypatch, path, "--data-dir", data_dir, "--write-patch", patch) == 0
    assert "4 corrected fields in 3 acai_entities rows" in capsys.readouterr().out
    assert _corrected_rows(path) == CORRECTED

    fresh = tmp_path / "fresh.db"
    conn = sqlite3.connect(fresh)
    create_schema(conn)
    build.import_acai_entities(conn, data_dir / "acai")
    conn.close()
    assert _table(path) == _table(fresh)
    # Only the corrected fields of the corrected rows changed
    changed = {row[0] for row in set(_table(path)) - set(stale)}
    assert changed == {"place:Ramah.2", "person:Judah.4", "person:Aiah.2"}

    with gzip.open(patch, "rt", encoding="utf-8") as handle:
        saved = json.load(handle)
    ramah = next(change for change in saved["update"] if change["key"] == ["place:Ramah.2"])
    assert ramah["set"] == {"name": ["Ramah (of the Negev)", "Ramah (of Benjamin)"],
                            "description": [SIMEON, BENJAMIN]}
    assert ramah["reasons"] == ["name: Benjamin's Ramah.", "description: Benjamin's Ramah."]

    assert _run(monkeypatch, path, "--data-dir", data_dir) == 0
    assert "the database already held every correction" in capsys.readouterr().out
    assert _table(path) == _table(fresh)


def test_patch_repairs_a_copy_with_the_standard_library_only(stale_db, tmp_path, monkeypatch):
    path, data_dir = stale_db
    server = tmp_path / "server"
    server.mkdir()
    shutil.copy(path, server / "study_bible.db")
    shutil.copy(SCRIPTS / "repair_acai_corrections.py", server)
    assert _run(monkeypatch, path, "--data-dir", data_dir, "--write-patch", server / "patch.gz") == 0

    # -I -S: no site-packages and no project source, as on the server.
    command = [sys.executable, "-I", "-S", "repair_acai_corrections.py", "study_bible.db",
               "--apply-patch", "patch.gz"]
    result = subprocess.run(command, cwd=server, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "updated 3 rows" in result.stdout
    result = subprocess.run(command, cwd=server, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "the database already held every correction" in result.stdout
    assert _table(server / "study_bible.db") == _table(path)


def test_patch_refuses_a_database_that_has_drifted(stale_db, tmp_path, monkeypatch, capsys):
    path, data_dir = stale_db
    copy = tmp_path / "copy.db"
    shutil.copy(path, copy)
    patch = tmp_path / "patch.json.gz"
    assert _run(monkeypatch, path, "--data-dir", data_dir, "--write-patch", patch) == 0
    capsys.readouterr()

    conn = sqlite3.connect(copy)
    conn.execute("UPDATE acai_entities SET roles = '[\"Priest\"]' WHERE id = 'person:Aiah.2'")
    conn.commit()
    conn.close()
    before = _table(copy)
    assert _run(monkeypatch, copy, "--apply-patch", patch) == 1
    err = capsys.readouterr().err
    assert "person:Aiah.2: roles changed since the patch was made" in err
    assert "Nothing was changed" in err
    assert _table(copy) == before  # the rows that matched were rolled back too

    conn = sqlite3.connect(copy)
    conn.execute("DELETE FROM acai_entities WHERE id = 'person:Aiah.2'")
    conn.commit()
    conn.close()
    before = _table(copy)
    assert _run(monkeypatch, copy, "--apply-patch", patch) == 1
    assert "person:Aiah.2: row missing" in capsys.readouterr().err
    assert _table(copy) == before


def test_repair_refuses_sources_the_corrections_no_longer_match(stale_db, monkeypatch):
    path, data_dir = stale_db
    before = _table(path)
    ramah = data_dir / "acai" / "places" / "Ramah.4.json"
    entity = json.loads(ramah.read_text(encoding="utf-8"))
    entity["localizations"]["eng"]["descriptions"][0]["description"] = "Revised upstream."
    ramah.write_text(json.dumps(entity), encoding="utf-8")
    with pytest.raises(SystemExit, match="place:Ramah.4 description is 'Revised upstream.'"):
        _run(monkeypatch, path, "--data-dir", data_dir)
    ramah.unlink()
    with pytest.raises(SystemExit, match="no entity place:Ramah.4"):
        _run(monkeypatch, path, "--data-dir", data_dir)
    assert _table(path) == before
