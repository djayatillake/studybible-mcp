"""Theographic import (parsers/theographic.py), the curated graph data, TIPNR
typing and corrections, and scripts/repair_theographic_graph.py."""

from __future__ import annotations

import csv
import gzip
import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

import scripts.import_theographic as import_theographic
import scripts.repair_theographic_graph as repair
from study_bible_mcp.database import create_schema
from study_bible_mcp.parsers import theographic
from study_bible_mcp.parsers.proper_names import (
    CuratedNameError,
    apply_tipnr_corrections,
    parse_tipnr,
)
from study_bible_mcp.parsers.theographic import (
    TABLE_COLUMNS,
    CuratedDataError,
    build_graph,
    expand_verses,
    load_curated,
)

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"

PEOPLE = [
    {"personLookup": "israel_682", "name": "Israel", "displayTitle": "Jacob (Israel)",
     "alsoCalled": "Israel", "gender": "Male", "birthYear": "-1836", "partners": "rachel_2386",
     "verses": "Gen.25.26"},
    {"personLookup": "rachel_2386", "name": "Rachel", "displayTitle": "Rachel", "gender": "Female",
     "birthYear": "-1755", "deathYear": "-1739", "partners": "israel_682",
     "verses": "Gen.29.6,Gen.30.1"},
    {"personLookup": "joseph_1710", "name": "Joseph", "displayTitle": "Joseph (son of Jacob)",
     "gender": "Male", "birthYear": "-1745", "birthPlace": "egypt_362", "father": "israel_682",
     "mother": "rachel_2386", "verses": "Gen.30.24"},
    {"personLookup": "peter_2745", "name": "Simon", "displayTitle": "Simon Peter", "surname": "Peter",
     "alsoCalled": "Cephas", "gender": "Male", "verses": "Matt.4.18"},
]
PLACES = [
    {"placeLookup": "egypt_362", "displayTitle": "Egypt", "openBibleLat": "30.1", "openBibleLong": "31.3",
     "featureType": "Region", "verses": "Gen.12.10"},
    {"placeLookup": "paddan-aram_916", "displayTitle": "Paddan-aram", "verses": "Gen.25.20"},
    {"placeLookup": "straight_1112", "displayTitle": "Straight Gate", "featureType": "Landmark",
     "verses": "Acts.9.11"},
]
# Theographic's sortKey is the year plus the first verse's book position, so
# within AD 30 it puts the Resurrection (Matt 28) before Lazarus (John 11).
EVENTS = [
    {"eventID": "460", "title": "Resurrection", "startDate": "0030-04-07",
     "predecessor": "Crucifixion and Burial", "verses": "Matt.28.1", "sortKey": "30.40028001"},
    {"eventID": "433", "title": "Lazarus Raised", "startDate": "30", "verses": "John.11.1",
     "sortKey": "30.43011001"},
    {"eventID": "459", "title": "Crucifixion and Burial", "startDate": "0030-04-04",
     "predecessor": "Lazarus Raised", "verses": "John.19.18,Matt.27.33", "sortKey": "30.43019018"},
    {"eventID": "102", "title": "Birth of Joseph", "startDate": "-1744", "verses": "Gen.30.23",
     "participants": "joseph_1710,rachel_2386", "locations": "egypt_362", "sortKey": "-1743.98969977"},
    {"eventID": "105", "title": "Joseph sold to Egypt", "startDate": "-1727",
     "predecessor": '"Birth of Joseph"', "verses": "Gen.37.3,Gen.37.4", "participants": "joseph_1710",
     "locations": "egypt_362", "sortKey": "-1726.98962997"},
]
GROUPS = [{"groupName": "Patriarchs", "members": "israel_682"}]

CURATED = {
    "theographic": {
        "people": [
            {"id": "rachel_2386", "field": "birth_year", "from": -1755, "to": None, "reason": "test"},
            {"id": "joseph_1710", "field": "birth_place_id", "from": "egypt_362",
             "to": "paddan-aram_916", "reason": "test"},
        ],
        "places": [{"id": "straight_1112", "field": "name", "from": "Straight Gate",
                    "to": "Straight Street", "reason": "test"}],
        "events": [{"id": "105", "field": "title", "from": "Joseph sold to Egypt",
                    "to": "Joseph sold into Egypt", "reason": "test"}],
        "event_predecessors": [],
        "event_places": [{"event": "102", "remove": "egypt_362", "add": "paddan-aram_916",
                          "reason": "test"}],
        "verse_mentions_remove": [{"verse_ref": "Gen.30.1", "entity_type": "person",
                                   "entity_id": "rachel_2386", "reason": "test"}],
        "supplement_events": [
            {"id": "9001", "title": "Joseph's dreams", "verses": ["Gen.37.5-7"],
             "participants": ["joseph_1710"], "locations": [], "after": ["102"]},
            {"id": "9002", "title": "Rachel at the well", "verses": ["Gen.29.9-10"],
             "participants": ["rachel_2386", "israel_682"], "locations": ["paddan-aram_916"],
             "after": []},
        ],
        "family_edge_notes": [],
        "eponyms": {"person_scope": [], "people": {}},
    },
    "tipnr": [{"entry": "Ezra@Ezr.7.1", "field": "parents", "from": ["Seraiah"],
               "to": ["Seraiah (test note)"], "reason": "test"}],
}

TIPNR_LINES = [
    "========== PERSON(s)",
    "Ezra@Ezr.7.1-Neh=H5830G\tPriest living at the time of Exile and Return\tSeraiah@2Ki.25.18-Jer"
    " + \t\t\t\tTribe of Levi\t#A priest from the tribe of Levi\tMale",
    "$========== OTHER",
    "Passover@Exo.12.11-Heb=H6453\tName of a feastival\t\t\t\t\t>\t#Name of a feastival; "
    "called Passover\t",
    "$========== OTHER",
    "Boaz@1Ki.7.21-2Ch=H1162H\tA pillar in the temple\t\t\t\t\t>\t#A pillar in the temple\t",
]


def _write_csv(path: Path, rows: list[dict]) -> None:
    columns = sorted({key for row in rows for key in row})
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture
def sources(tmp_path, monkeypatch):
    """A data directory (CSVs and TIPNR) and the curated file, as the importers find them."""
    data_dir = tmp_path / "data"
    csv_dir = data_dir / "theographic"
    csv_dir.mkdir(parents=True)
    for name, rows in (("People", PEOPLE), ("Places", PLACES), ("Events", EVENTS),
                       ("PeopleGroups", GROUPS)):
        _write_csv(csv_dir / f"{name}.csv", rows)
    (data_dir / "TIPNR.txt").write_text("\n".join(TIPNR_LINES) + "\n", encoding="utf-8")
    curated = tmp_path / "graph_curated.json"
    curated.write_text(json.dumps(CURATED), encoding="utf-8")
    monkeypatch.setattr(theographic, "CURATED_PATH", curated)
    return data_dir


def _by_id(rows: list[tuple], table: str) -> dict[str, dict]:
    columns = TABLE_COLUMNS[table]
    return {row[0]: dict(zip(columns, row)) for row in rows}


# ---------------------------------------------------------------------------
# build_graph
# ---------------------------------------------------------------------------


def test_event_years_and_chronological_order(sources):
    graph = build_graph(sources / "theographic")
    events = _by_id(graph["graph_events"], "graph_events")
    assert events["460"]["start_year"] == 30  # '0030-04-07'
    assert events["102"]["start_year"] == -1744  # astronomical, kept as Theographic has it
    order = [e for e, _ in sorted(((i, e["sort_key"]) for i, e in events.items()), key=lambda x: x[1])]
    # By year, then the predecessor chain (Lazarus -> Crucifixion -> Resurrection),
    # not Matthew-before-John; undated events by their anchor or Scripture order
    assert order == ["9002", "102", "9001", "105", "433", "459", "460"]


def test_curated_corrections_and_supplementary_events(sources):
    graph = build_graph(sources / "theographic")
    people = _by_id(graph["graph_people"], "graph_people")
    assert people["rachel_2386"]["birth_year"] is None
    assert people["joseph_1710"]["birth_place_id"] == "paddan-aram_916"
    assert (people["peter_2745"]["display_title"], people["peter_2745"]["surname"]) == ("Simon Peter", "Peter")
    assert people["rachel_2386"]["display_title"] is None  # the same as the name
    assert _by_id(graph["graph_places"], "graph_places")["straight_1112"]["name"] == "Straight Street"
    events = _by_id(graph["graph_events"], "graph_events")
    assert events["105"]["title"] == "Joseph sold into Egypt"
    assert events["9001"]["start_year"] is None
    assert ("102", "paddan-aram_916") in graph["graph_event_place_edges"]
    assert ("102", "egypt_362") not in graph["graph_event_place_edges"]
    assert ("joseph_1710", "9001") in graph["graph_person_event_edges"]
    mentions = set(graph["graph_verse_mentions"])
    assert {("Gen.37.5", "event", "9001"), ("Gen.37.7", "event", "9001")} <= mentions
    assert ("Gen.30.1", "person", "rachel_2386") not in mentions
    # Partners recorded from both sides stay two rows, as Theographic has them
    assert {("israel_682", "rachel_2386", "partner_of"),
            ("rachel_2386", "israel_682", "partner_of")} <= set(graph["graph_family_edges"])


def test_a_correction_that_no_longer_matches_stops_the_build(sources, tmp_path, monkeypatch):
    curated = json.loads(json.dumps(CURATED))
    curated["theographic"]["people"][0]["from"] = -1700
    with pytest.raises(CuratedDataError, match="rachel_2386 birth_year is -1755"):
        build_graph(sources / "theographic", curated)
    # A source that already has the corrected value needs nothing
    curated["theographic"]["people"][0].update({"from": -1700, "to": -1755})
    build_graph(sources / "theographic", curated)


def test_a_supplementary_event_must_name_known_ids(sources):
    curated = json.loads(json.dumps(CURATED))
    curated["theographic"]["supplement_events"][0]["participants"] = ["nobody_1"]
    with pytest.raises(CuratedDataError, match="unknown ids"):
        build_graph(sources / "theographic", curated)
    curated = json.loads(json.dumps(CURATED))
    curated["theographic"]["supplement_events"][0]["id"] = "102"
    with pytest.raises(CuratedDataError, match="already a Theographic event"):
        build_graph(sources / "theographic", curated)


def test_expand_verses():
    assert expand_verses(["Ruth.1.21-22", "1Sam.7.17"]) == ["Ruth.1.21", "Ruth.1.22", "1Sam.7.17"]
    for bad in (["Ruth.1.22-21"], ["Bogus.1.1"], ["Ruth 1:1"]):
        with pytest.raises(CuratedDataError):
            expand_verses(bad)


def test_the_curated_file_is_well_formed():
    curated = load_curated(theographic.Path(theographic.__file__).with_name("graph_curated.json"))
    theo = curated["theographic"]
    ids = [event["id"] for event in theo["supplement_events"]]
    assert len(ids) == len(set(ids)) and all(int(i) >= 9001 for i in ids)
    for event in theo["supplement_events"]:
        assert event["title"] and event["participants"] and event["locations"], event
        assert expand_verses(event["verses"])
    for section in ("people", "places", "events", "event_predecessors", "event_places",
                    "verse_mentions_remove"):
        assert all(fix.get("reason") for fix in theo[section]), section
    assert all(note["note"] and note["label"] for note in theo["family_edge_notes"])
    assert all(fix.get("reason") for fix in curated["tipnr"])


def test_import_graph_replaces_rows_and_adds_the_new_columns(sources, tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    create_schema(conn)
    conn.execute("ALTER TABLE graph_people DROP COLUMN display_title")
    conn.execute("ALTER TABLE graph_people DROP COLUMN surname")
    conn.execute("INSERT INTO graph_events (id, title) VALUES ('999', 'Stale')")
    counts = import_theographic.import_graph(conn, sources / "theographic")
    assert counts["graph_events"] == 7
    assert conn.execute("SELECT display_title FROM graph_people WHERE id = 'peter_2745'").fetchone() == (
        "Simon Peter",)
    assert conn.execute("SELECT COUNT(*) FROM graph_events WHERE id = '999'").fetchone() == (0,)
    conn.close()


# ---------------------------------------------------------------------------
# TIPNR
# ---------------------------------------------------------------------------


def test_tipnr_other_records_are_things(sources):
    entries = list(parse_tipnr(sources / "TIPNR.txt"))
    assert [(e["name"], e["type"]) for e in entries] == [
        ("Ezra", "person"), ("Passover", "thing"), ("Boaz", "thing")
    ]


def test_tipnr_corrections(sources):
    entries = list(parse_tipnr(sources / "TIPNR.txt"))
    fixed = list(apply_tipnr_corrections(entries, CURATED["tipnr"]))
    assert json.loads(fixed[0]["relationships"]) == {"parents": ["Seraiah (test note)"]}
    assert list(apply_tipnr_corrections(fixed, CURATED["tipnr"])) == fixed  # already applied
    removal = [{"entry": "Ezra@Ezr.7.1", "field": "parents", "from": ["Seraiah"], "to": None}]
    assert json.loads(next(apply_tipnr_corrections(entries, removal))["relationships"]) == {}
    text = [{"entry": "Ezra@Ezr.7.1", "field": "description", "from": "Exile and Return",
             "to": "the Exile and the Return"}]
    assert "at the time of the Exile and the Return" in next(
        apply_tipnr_corrections(entries, text))["description"]
    stale = [{"entry": "Ezra@Ezr.7.1", "field": "parents", "from": ["Hilkiah"], "to": ["X"]}]
    with pytest.raises(CuratedNameError, match="expected"):
        list(apply_tipnr_corrections(entries, stale))
    missing = [{"entry": "Nobody@Gen.1.1", "field": "parents", "from": [], "to": []}]
    assert len(list(apply_tipnr_corrections(entries, missing))) == 3
    with pytest.raises(CuratedNameError, match="no entries"):
        list(apply_tipnr_corrections(entries, missing, require_all=True))


# ---------------------------------------------------------------------------
# scripts/repair_theographic_graph.py
# ---------------------------------------------------------------------------


def _old_import(conn: sqlite3.Connection, data_dir: Path) -> None:
    """What the importers wrote before the fixes: no titles, no corrections, sortKey order."""
    csv_dir = data_dir / "theographic"
    conn.execute("ALTER TABLE graph_people DROP COLUMN display_title")
    conn.execute("ALTER TABLE graph_people DROP COLUMN surname")
    for row in PEOPLE:
        conn.execute(
            "INSERT INTO graph_people (id, name, also_called, gender, birth_year, death_year, "
            "birth_place_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (row["personLookup"], row["name"], row.get("alsoCalled"), row["gender"],
             theographic.safe_int(row.get("birthYear")), theographic.safe_int(row.get("deathYear")),
             row.get("birthPlace")),
        )
    for row in PLACES:
        conn.execute(
            "INSERT INTO graph_places (id, name, latitude, longitude, feature_type) VALUES (?, ?, ?, ?, ?)",
            (row["placeLookup"], row["displayTitle"], theographic.safe_float(row.get("openBibleLat")),
             theographic.safe_float(row.get("openBibleLong")), row.get("featureType")),
        )
    for row in EVENTS:
        conn.execute(
            "INSERT INTO graph_events (id, title, start_year, sort_key) VALUES (?, ?, ?, ?)",
            (row["eventID"], row["title"], theographic.safe_int(row["startDate"]), float(row["sortKey"])),
        )
        for person in theographic.split_field(row.get("participants")):
            conn.execute("INSERT INTO graph_person_event_edges VALUES (?, ?)", (person, row["eventID"]))
        for place in theographic.split_field(row.get("locations")):
            conn.execute("INSERT INTO graph_event_place_edges VALUES (?, ?)", (row["eventID"], place))
        for ref in theographic.split_field(row["verses"]):
            conn.execute("INSERT INTO graph_verse_mentions VALUES (?, 'event', ?)", (ref, row["eventID"]))
    graph = build_graph(csv_dir)  # rows the fixes did not touch
    for table in ("graph_family_edges", "graph_people_groups", "graph_person_group_edges"):
        columns = TABLE_COLUMNS[table]
        conn.executemany(
            f"INSERT INTO {table} VALUES ({', '.join('?' for _ in columns)})", graph[table]
        )
    for row in PEOPLE + PLACES:
        entity = ("person", row["personLookup"]) if "personLookup" in row else ("place", row["placeLookup"])
        for ref in theographic.split_field(row["verses"]):
            conn.execute("INSERT INTO graph_verse_mentions VALUES (?, ?, ?)", (ref, *entity))
    for entry in parse_tipnr(data_dir / "TIPNR.txt"):
        conn.execute(
            "INSERT INTO names (name, name_original, type, description, refs, relationships) "
            "VALUES (?, ?, 'person', ?, ?, ?)",
            (entry["name"], entry["name_original"], entry["description"], entry["references"],
             entry["relationships"]),
        )
    conn.execute(
        "INSERT INTO acai_entities (id, entity_type, name, referred_to_as) VALUES "
        "('place:Ai', 'place', 'Ai', '[\"Hai\", \"Ketiv. Qere\"]')"
    )


@pytest.fixture
def stale_db(sources, tmp_path):
    path = tmp_path / "study_bible.db"
    conn = sqlite3.connect(path)
    create_schema(conn)
    _old_import(conn, sources)
    conn.commit()
    conn.close()
    return path, sources


def _contents(path: Path) -> dict:
    conn = sqlite3.connect(path)
    contents = {}
    for table, columns in TABLE_COLUMNS.items():
        present = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        select = ", ".join(c if c in present else "'(missing)'" for c in columns)
        contents[table] = sorted(conn.execute(f"SELECT {select} FROM {table}").fetchall(), key=repr)
    contents["names"] = conn.execute("SELECT name, type, relationships FROM names ORDER BY id").fetchall()
    contents["acai"] = conn.execute("SELECT id, referred_to_as FROM acai_entities").fetchall()
    conn.close()
    return contents


def _fresh(data_dir: Path) -> dict:
    graph = build_graph(data_dir / "theographic")
    return {table: sorted(rows, key=repr) for table, rows in graph.items()}


def _run(monkeypatch, *argv) -> int:
    monkeypatch.setattr("sys.argv", ["repair_theographic_graph.py", *map(str, argv)])
    return repair.main()


def test_repair_matches_a_fresh_import_and_is_idempotent(stale_db, tmp_path, monkeypatch, capsys):
    path, data_dir = stale_db
    patch = tmp_path / "patch.json.gz"
    assert _run(monkeypatch, path, "--data-dir", data_dir, "--write-patch", patch) == 0
    out = capsys.readouterr().out
    assert "graph_events: 2 inserts, 5 updates" in out
    assert "names: 3 updates; acai_entities: 1 updates" in out
    repaired = _contents(path)
    fresh = _fresh(data_dir)
    for table in TABLE_COLUMNS:
        assert repaired[table] == fresh[table], table
    assert repaired["names"] == [
        ("Ezra", "person", '{"parents": ["Seraiah (test note)"]}'),
        ("Passover", "thing", "{}"), ("Boaz", "thing", "{}"),
    ]
    assert repaired["acai"] == [("place:Ai", '["Hai"]')]

    assert _run(monkeypatch, path, "--data-dir", data_dir) == 0
    assert "the database already held every change" in capsys.readouterr().out
    assert _contents(path) == repaired
    with gzip.open(patch, "rt", encoding="utf-8") as handle:
        assert json.load(handle)["add_columns"] == [["graph_people", "display_title", "TEXT"],
                                                    ["graph_people", "surname", "TEXT"]]


def test_patch_repairs_a_copy_with_the_standard_library_only(stale_db, tmp_path, monkeypatch):
    path, data_dir = stale_db
    server = tmp_path / "server"
    server.mkdir()
    shutil.copy(path, server / "study_bible.db")
    shutil.copy(SCRIPTS / "repair_theographic_graph.py", server)
    assert _run(monkeypatch, path, "--data-dir", data_dir, "--write-patch", server / "patch.gz") == 0

    # -I -S: no site-packages and no project source, as on the server.
    command = [sys.executable, "-I", "-S", "repair_theographic_graph.py", "study_bible.db",
               "--apply-patch", "patch.gz"]
    for _ in range(2):
        result = subprocess.run(command, cwd=server, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
    assert "the database already held every change" in result.stdout
    assert _contents(server / "study_bible.db") == _contents(path)


def test_patch_refuses_a_database_that_has_drifted(stale_db, tmp_path, monkeypatch, capsys):
    path, data_dir = stale_db
    copy = tmp_path / "copy.db"
    shutil.copy(path, copy)
    patch = tmp_path / "patch.json.gz"
    assert _run(monkeypatch, path, "--data-dir", data_dir, "--write-patch", patch) == 0
    capsys.readouterr()

    conn = sqlite3.connect(copy)
    conn.execute("UPDATE graph_events SET title = 'Edited' WHERE id = '105'")
    conn.commit()
    conn.close()
    before = _contents(copy)
    assert _run(monkeypatch, copy, "--apply-patch", patch) == 1
    err = capsys.readouterr().err
    assert "graph_events ['105']: title, sort_key changed since the patch was made" in err
    assert "Nothing was changed" in err
    assert _contents(copy) == before  # the added columns were rolled back too
