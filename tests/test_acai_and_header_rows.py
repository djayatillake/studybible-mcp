"""ACAI entities and file-header rows: download, parse, and the in-place repair.

The ACAI downloader used to list each directory through GitHub's contents API,
which stops at 1,000 files, and the parser missed the files' English label and
description. The TAGNT/TAHOT and TIPNR parsers imported header and note lines
as verses and people. scripts/repair_acai_and_header_rows.py brings an existing
database into line.
"""

from __future__ import annotations

import gzip
import importlib.util
import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

import scripts.repair_acai_and_header_rows as repair
from study_bible_mcp.database import create_schema
from study_bible_mcp.parsers.acai import parse_acai_entities
from study_bible_mcp.parsers.proper_names import parse_tipnr
from study_bible_mcp.parsers.tagged_text import parse_tagnt, parse_tahot

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def _entity(entity_id: str, label: str, description: str | None, alternate_labels=None,
            **fields) -> dict:
    """An ACAI entity file: no top-level name, English text under localizations."""
    eng: dict = {"preferred_label": label, "descriptions": []}
    if alternate_labels:
        eng["alternate_labels"] = alternate_labels
    if description:
        eng["descriptions"].append(
            {"source": "acai", "gloss": label, "article": entity_id, "description": description}
        )
    return {
        "id": entity_id,
        "primary_id": entity_id,
        "type": entity_id.split(":")[0],
        "localizations": {"eng": eng, "fra": {"preferred_label": f"{label} (fr)"}},
        "speeches": None,
        **fields,
    }


EZRA = _entity(
    "person:Ezra", "Ezra",
    "A Levite who served as both a priest and a scribe after the Israelite exile.",
    alternate_labels=["Ezra ", "Esdras", "his", "Esdras"], referred_to_as=["person:Ezra.2"],
    alternate_sources={"tipnr": ["Ezra@Ezr.7.1-Neh", "Scribe|Ezra@Ezr.7.1-Neh"]},
    gender="male", father="person:Seraiah.2", siblings=["person:Jehozadak"],
    roles=["Priest", "Scribe"], key_references=["15007001"],
    references=["15007001", "15007006", "16008001"],
    speeches={"wlc": [{"quote_type": "Normal", "words": ["o150090060011"]},
                      {"quote_type": "Normal", "words": ["o160080060021"]}],
              "SBLGNT": [{"quote_type": "Normal", "words": ["n0"]}]},
)
MISGAB = _entity("place:Misgab.1", "Misgab", None, references=["24048001"],
                 alternate_sources={"tipnr": ["Misgab@Jer.48.1"]})


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def test_acai_entity_takes_the_english_label_description_and_speeches(tmp_path):
    path = tmp_path / "Ezra.json"
    path.write_text(json.dumps(EZRA), encoding="utf-8")

    (entity,) = parse_acai_entities(path, "people")

    assert entity["id"] == "person:Ezra"
    assert entity["entity_type"] == "person"
    assert entity["name"] == "Ezra"
    assert entity["description"].startswith("A Levite who served")
    assert entity["speeches_count"] == 3
    assert entity["roles"] == '["Priest", "Scribe"]'
    assert entity["father_id"] == "person:Seraiah.2"
    assert entity["reference_count"] == 3
    # Spelling variants, not ACAI's related entities; TIPNR keys as names rows have them.
    assert entity["referred_to_as"] == '["Esdras"]'
    assert entity["tipnr_keys"] == '["Ezra@Ezr.7.1"]'


def test_acai_entity_without_a_description(tmp_path):
    path = tmp_path / "Misgab.1.json"
    path.write_text(json.dumps(MISGAB), encoding="utf-8")

    (entity,) = parse_acai_entities(path, "places")

    assert (entity["name"], entity["description"], entity["speeches_count"]) == ("Misgab", None, 0)


TAGNT_LINES = [
    "Types of words\tNUMBERS FOUND IN TYPES OF MANUSCRIPTS\tUSAGE IN TYPES OF BIBLES\tSIGNIFICANCE",
    "NKO / NK(O) / NK(o)\t133608 words that are identical\tTranslated in almost all Bibles\t94% of the total words",
    "Word & Type\tGreek\tEnglish translation\tdStrongs = Grammar\tDictionary form =  Gloss",
    "Mat.1.1#01=NKO\tΒίβλος (Biblos)\t[The] book\tG0976=N-NSF\tβίβλος=book",
    "Mat.1.1#02=NKO\tγενέσεως (geneseōs)\tof [the] genealogy\tG1078=N-GSF\tγένεσις=origin",
    "Word & Type\tGreek\tEnglish translation\tdStrongs = Grammar\tDictionary form =  Gloss",
    "Mat.1.2#01=NKO\tἈβραὰμ (Abraam)\tAbraham\tG0011=N-NSM-P\tἈβραάμ=Abraham",
]

TAHOT_LINES = [
    "Eng (Heb) Ref & Type\tHebrew\tTransliteration\tTranslation\tdStrongs\tGrammar",
    "Gen.1.1#01=L\tבְּ/רֵאשִׁ֖ית\tbe./re.Shit\tin/ beginning\tH9003/{H7225G}\tHR/Ncfsa",
    "Gen.1.1#02=L\tבָּרָ֣א\tba.Ra'\the created\t{H1254A}\tHVqp3ms",
    "Eng (Heb) Ref & Type\tHebrew\tTransliteration\tTranslation\tdStrongs\tGrammar",
    "Psa.3.0(3.1)#01=L\tמִזְמ֥וֹר\tmiz.Mor\ta psalm\tH4210\tHNcmsa",
]


def test_tagged_text_skips_header_and_summary_rows(tmp_path):
    tagnt = tmp_path / "TAGNT.txt"
    tagnt.write_text("\n".join(TAGNT_LINES) + "\n", encoding="utf-8")
    tahot = tmp_path / "TAHOT.txt"
    tahot.write_text("\n".join(TAHOT_LINES) + "\n", encoding="utf-8")

    greek = list(parse_tagnt(tagnt))
    hebrew = list(parse_tahot(tahot))

    assert [v["reference"] for v in greek] == ["Mat.1.1", "Mat.1.2"]
    assert greek[0]["text_english"] == "[The] book of [the] genealogy"
    assert [v["reference"] for v in hebrew] == ["Gen.1.1", "Psa.3.0(3.1)"]
    assert hebrew[0]["text_english"] == "in/ beginning he created"


TIPNR_LINES = [
    "TIPNR - Translators Individualised Proper Names with all References = STEPBible.org CC BY\t\t>",
    "(?) indicates  a decision based on an ambiguity e.g. Jahdai@1Ch.2.47(?) which may be discussed"
    " at\tTinyURL.com/TIPNR-Decisions",
    "$==========PERSON(s)",
    "UnifiedName=uStrong\tDescription\tParents Male+Female\tSiblings\tPartners\tOffspring\tTribe",
    "",
    "========== PERSON(s)",
    "Ezra@Ezr.7.1-Neh=H5830G\tPriest living at the time of Exile and Return\tSeraiah@2Ki.25.18-Jer"
    " + \tJehozadak@1Ch.6.14-Zec\t\t\tTribe of Levi\t#A priest from the tribe of Levi\tMale",
    "– Named\tEzra@Ezr.7.1-Neh\tH5830G«H5830=עֶזְרָא\tEzra\thttps://www.stepbible.org/\tEzr.7.1",
    "@Briefest= Scribe",
    "$========== PLACE",
    "Bethlehem@Gen.35.19-Mic=H1035G\tBethlehem\tSalma@1Ch.2.51-=H8007H\t\t"
    "https://www.google.com/maps/@31.704,35.207,14z\thttps://palopenmaps.org/view/9999/@31.704,35.207"
    "\tJudea\t#A town in Judea first mentioned at Gen.35.19.\tPlace",
    "$========== PLACE",
    "Misgab@Jer.48.1=H4869B\tWord sometimes translated as a place name\t\t\t"
    "https://www.google.com/maps/@0,14z\thttps://palopenmaps.org/view/9999/@0\tMoab"
    "\t#A location in Moab only mentioned at Jer.48.1.\tPlace",
    "PEOPLE:\t\t\t\t\t\t>",
    "SEPARATED Immanuel/Emmanuel from Jesus; Hermes/Mercurius from Paul; Judith@Gen.26.34/Oholibamah"
    "@Gen.36.2\t\t\t\t\t\t>",
]


def test_tipnr_reads_only_the_records_after_a_marker(tmp_path):
    path = tmp_path / "TIPNR.txt"
    path.write_text("\n".join(TIPNR_LINES) + "\n", encoding="utf-8")

    entries = list(parse_tipnr(path))

    assert [e["name"] for e in entries] == ["Ezra", "Bethlehem", "Misgab"]
    assert json.loads(entries[0]["relationships"]) == {
        "parents": ["Seraiah"], "siblings": ["Jehozadak"]
    }


def test_tipnr_place_columns_are_not_family(tmp_path):
    # A place has founder and people-living-there columns where a person has
    # parents and siblings, then map links where a person has a spouse and children.
    path = tmp_path / "TIPNR.txt"
    path.write_text("\n".join(TIPNR_LINES) + "\n", encoding="utf-8")

    bethlehem, misgab = list(parse_tipnr(path))[1:]

    assert (bethlehem["type"], json.loads(bethlehem["relationships"])) == (
        "place", {"founder": ["Salma"]}
    )
    assert (misgab["type"], misgab["relationships"]) == ("place", "{}")


# ---------------------------------------------------------------------------
# scripts/download_stepbible.py
# ---------------------------------------------------------------------------


def _load_downloader():
    spec = importlib.util.spec_from_file_location("download_stepbible", SCRIPTS / "download_stepbible.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _github(tree: list[dict], files: dict[str, bytes], truncated: bool = False):
    """A mock GitHub serving the ACAI repository; returns (client, raw paths requested)."""
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.github.com":
            if request.url.path == "/repos/BibleAquifer/ACAI":
                return httpx.Response(200, json={"default_branch": "main"})
            if request.url.path == "/repos/BibleAquifer/ACAI/git/trees/main":
                assert request.url.params["recursive"] == "1"
                return httpx.Response(200, json={"tree": tree, "truncated": truncated})
        prefix = b"/BibleAquifer/ACAI/main/"
        if request.url.host == "raw.githubusercontent.com" and request.url.raw_path.startswith(prefix):
            requested.append(request.url.raw_path[len(prefix):].decode())
            path = request.url.path[len(prefix):]
            if path in files:
                return httpx.Response(200, content=files[path])
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler)), requested


def _blob(path: str) -> dict:
    return {"path": path, "type": "blob"}


def test_acai_download_lists_past_a_thousand_files(tmp_path):
    module = _load_downloader()
    people = {f"people/json/Person{n:04}.json": f'{{"n": {n}}}'.encode() for n in range(1001)}
    files = {**people, "places/json/Cistern of sirah.json": b"{}"}
    tree = [
        {"path": "people", "type": "tree"},
        {"path": "people/json", "type": "tree"},
        *map(_blob, files),
        _blob("people/csv/people.csv"),
        _blob("people/json/README.md"),
        _blob("README.md"),
    ]
    cached = tmp_path / "acai" / "people" / "Person0000.json"
    cached.parent.mkdir(parents=True)
    cached.write_bytes(b"cached")
    client, requested = _github(tree, files)

    assert module._download_acai(client, tmp_path) is True

    assert len(list((tmp_path / "acai" / "people").glob("*.json"))) == 1001
    assert (tmp_path / "acai" / "people" / "Person1000.json").read_bytes() == b'{"n": 1000}'
    assert cached.read_bytes() == b"cached"
    assert (tmp_path / "acai" / "places" / "Cistern of sirah.json").read_bytes() == b"{}"
    assert "places/json/Cistern%20of%20sirah.json" in requested
    assert len(requested) == 1001  # neither the cached file nor non-entity files


def test_acai_download_fails_on_a_truncated_tree_or_missing_file(tmp_path):
    module = _load_downloader()
    tree = [_blob("people/json/Ezra.json"), _blob("people/json/Gone.json")]
    client, requested = _github(tree, {"people/json/Ezra.json": b"{}"}, truncated=True)
    assert module._download_acai(client, tmp_path) is False
    assert requested == []

    client, _ = _github(tree, {"people/json/Ezra.json": b"{}"})
    assert module._download_acai(client, tmp_path) is False
    assert (tmp_path / "acai" / "people" / "Ezra.json").exists()


# ---------------------------------------------------------------------------
# scripts/repair_acai_and_header_rows.py
# ---------------------------------------------------------------------------

# What the old parser read from the place records' map links.
OLD_PLACE_RELATIONSHIPS = {
    "Bethlehem": {"parents": ["Salma"], "spouse": ["https://www.google.com/maps/", "35.207", "14z"],
                  "children": ["https://palopenmaps.org/view/9999/", "35.207"]},
    "Misgab": {"spouse": ["https://www.google.com/maps/", "14z"],
               "children": ["https://palopenmaps.org/view/9999/"]},
}

VERSES = [  # (reference, book, chapter, verse): a header row between two verses
    ("Mal.4.5(3.23)", "Mal", 4, 5),
    ("Eng (Heb) Ref & Type", "Eng (Heb) Ref & Type", 0, 0),
    ("Mal.4.6(3.24)", "Mal", 4, 6),
]


@pytest.fixture
def stale_db(tmp_path):
    """A database imported before the fixes, plus the sources it came from."""
    data_dir = tmp_path / "data"
    for entity_type, entity in (("people", EZRA), ("places", MISGAB)):
        directory = data_dir / "acai" / entity_type
        directory.mkdir(parents=True)
        (directory / f"{entity['id'].split(':', 1)[1]}.json").write_text(
            json.dumps(entity), encoding="utf-8"
        )
    tipnr = data_dir / "TIPNR.txt"
    tipnr.write_text("\n".join(TIPNR_LINES) + "\n", encoding="utf-8")

    path = tmp_path / "study_bible.db"
    conn = sqlite3.connect(path)
    create_schema(conn)
    # The old importer: no tipnr_keys, the key as name, no description, and
    # Misgab.1 cut off.
    conn.execute("ALTER TABLE acai_entities DROP COLUMN tipnr_keys")
    conn.execute(
        "INSERT INTO acai_entities (id, entity_type, name, roles, reference_count, speeches_count) "
        "VALUES ('person:Ezra', 'person', 'person:Ezra', '[\"Priest\", \"Scribe\"]', 3, 0)"
    )
    conn.execute(
        "INSERT INTO names (name, name_original, type, description, refs, relationships) "
        "VALUES ('(?) indicates  a decision based on an ambiguity e.g. Jahdai', '', 'person', "
        "'TinyURL.com/TIPNR-Decisions', '[\"1Ch.2.47(?) which may be discussed at\"]', '{}')"
    )
    conn.executemany(
        "INSERT INTO names (name, name_original, type, description, refs, relationships) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [(e["name"], e["name_original"], e["type"], e["description"], e["references"],
          json.dumps(OLD_PLACE_RELATIONSHIPS.get(e["name"]) or json.loads(e["relationships"])))
         for e in parse_tipnr(tipnr)],
    )
    for reference, book, chapter, verse in VERSES:
        verse_id = conn.execute(
            "INSERT INTO verses (reference, book, chapter, verse, text_english) VALUES (?, ?, ?, ?, ?)",
            (reference, book, chapter, verse, f"text of {reference}"),
        ).lastrowid
        conn.execute(
            "INSERT INTO passages (reference_start, reference_end, book, start_verse_id, "
            "end_verse_id, text_combined, verse_count) VALUES (?, ?, ?, ?, ?, ?, 1)",
            (reference, reference, book, verse_id, verse_id, f"text of {reference}"),
        )
    conn.commit()
    conn.close()
    return path, data_dir


def _contents(path) -> dict:
    conn = sqlite3.connect(path)
    columns = [row[1] for row in conn.execute("PRAGMA table_info(acai_entities)")]
    keys = ", tipnr_keys" if "tipnr_keys" in columns else ""
    contents = {
        "acai": conn.execute(
            f"SELECT id, name, description, speeches_count{keys} FROM acai_entities ORDER BY id"
        ).fetchall(),
        "verses": [r for (r,) in conn.execute("SELECT reference FROM verses ORDER BY id")],
        "passages": [r for (r,) in conn.execute("SELECT reference_start FROM passages ORDER BY id")],
        "names": conn.execute("SELECT name, relationships FROM names ORDER BY id").fetchall(),
    }
    conn.close()
    return contents


REPAIRED = {
    "acai": [
        ("person:Ezra", "Ezra",
         "A Levite who served as both a priest and a scribe after the Israelite exile.", 3,
         '["Ezra@Ezr.7.1"]'),
        ("place:Misgab.1", "Misgab", None, 0, '["Misgab@Jer.48.1"]'),
    ],
    "verses": ["Mal.4.5(3.23)", "Mal.4.6(3.24)"],
    "passages": ["Mal.4.5(3.23)", "Mal.4.6(3.24)"],
    "names": [("Ezra", '{"parents": ["Seraiah"], "siblings": ["Jehozadak"]}'),
              ("Bethlehem", '{"founder": ["Salma"]}'), ("Misgab", "{}")],
}


def _run(monkeypatch, *argv) -> int:
    monkeypatch.setattr("sys.argv", ["repair_acai_and_header_rows.py", *map(str, argv)])
    return repair.main()


def test_repair_from_source_is_idempotent_and_writes_a_patch(stale_db, tmp_path, monkeypatch, capsys):
    path, data_dir = stale_db
    patch = tmp_path / "patch.json.gz"
    assert _run(monkeypatch, path, "--data-dir", data_dir, "--write-patch", patch) == 0
    assert _contents(path) == REPAIRED
    out = capsys.readouterr().out
    assert "replaced acai_entities with 2 rows" in out
    assert "deleted 1 of 1 verses rows, 1 of 1 passages rows, 1 of 1 names rows" in out
    assert "corrected the relationships of 2 of 2 names rows" in out
    with gzip.open(patch, "rt", encoding="utf-8") as handle:
        saved = json.load(handle)
    assert [row[0] for row in saved["acai_entities"]["rows"]] == ["person:Ezra", "place:Misgab.1"]
    assert saved["verses"] == [[2, "Eng (Heb) Ref & Type"]]

    assert _run(monkeypatch, path, "--data-dir", data_dir) == 0
    out = capsys.readouterr().out
    assert "acai_entities already held them" in out
    assert "deleted 0 of 0 verses rows" in out
    assert "corrected the relationships of 0 of 0 names rows" in out
    assert _contents(path) == REPAIRED


def test_patch_repairs_a_copy_with_the_standard_library_only(stale_db, tmp_path, monkeypatch):
    path, data_dir = stale_db
    server = tmp_path / "server"
    server.mkdir()
    shutil.copy(path, server / "study_bible.db")
    shutil.copy(SCRIPTS / "repair_acai_and_header_rows.py", server)
    assert _run(monkeypatch, path, "--data-dir", data_dir, "--write-patch", server / "patch.gz") == 0

    # -I -S: no site-packages and no project source, as on the server.
    command = [sys.executable, "-I", "-S", "repair_acai_and_header_rows.py", "study_bible.db",
               "--apply-patch", "patch.gz"]
    for _ in range(2):
        result = subprocess.run(command, cwd=server, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
    assert "deleted 0 of 1 verses rows" in result.stdout
    assert _contents(server / "study_bible.db") == REPAIRED


def test_patch_refuses_a_database_that_differs(stale_db, tmp_path, monkeypatch, capsys):
    path, data_dir = stale_db
    copy = tmp_path / "copy.db"
    shutil.copy(path, copy)
    patch = tmp_path / "patch.json.gz"
    assert _run(monkeypatch, path, "--data-dir", data_dir, "--write-patch", patch) == 0
    capsys.readouterr()

    conn = sqlite3.connect(copy)
    conn.execute("UPDATE acai_entities SET roles = '[\"King\"]' WHERE id = 'person:Ezra'")
    conn.commit()
    conn.close()
    before = _contents(copy)
    assert _run(monkeypatch, copy, "--apply-patch", patch) == 1
    assert "acai_entities holds neither" in capsys.readouterr().err
    assert _contents(copy) == before

    # A row to delete that no longer holds what the patch expects is kept.
    conn = sqlite3.connect(copy)
    conn.execute("UPDATE acai_entities SET roles = '[\"Priest\", \"Scribe\"]' WHERE id = 'person:Ezra'")
    conn.execute("UPDATE names SET name = 'Jahdai' WHERE id = 1")
    conn.commit()
    conn.close()
    before = _contents(copy)
    assert _run(monkeypatch, copy, "--apply-patch", patch) == 1
    assert "1 names rows no longer hold the expected values (first ids: 1)" in capsys.readouterr().err
    assert _contents(copy) == before  # tipnr_keys was added, then rolled back

    # So are relationships edited since the patch was made.
    conn = sqlite3.connect(copy)
    conn.execute("UPDATE names SET name = '(?) indicates  a decision based on an ambiguity e.g. Jahdai' "
                 "WHERE id = 1")
    conn.execute("UPDATE names SET relationships = '{\"founder\": [\"Mesha\"]}' WHERE name = 'Misgab'")
    conn.commit()
    conn.close()
    before = _contents(copy)
    assert _run(monkeypatch, copy, "--apply-patch", patch) == 1
    assert "1 names rows no longer hold the expected relationships" in capsys.readouterr().err
    assert _contents(copy) == before


def test_repair_refuses_a_source_missing_entities_or_a_spanning_passage(stale_db, monkeypatch):
    path, data_dir = stale_db
    (data_dir / "acai" / "people" / "Ezra.json").unlink()
    before = _contents(path)
    with pytest.raises(SystemExit, match="lacks 1 entities the database has"):
        _run(monkeypatch, path, "--data-dir", data_dir)
    assert _contents(path) == before

    (data_dir / "acai" / "people" / "Ezra.json").write_text(json.dumps(EZRA), encoding="utf-8")
    conn = sqlite3.connect(path)
    conn.execute("UPDATE passages SET end_verse_id = 3 WHERE reference_start = 'Eng (Heb) Ref & Type'")
    conn.commit()
    conn.close()
    with pytest.raises(SystemExit, match="include real verses"):
        _run(monkeypatch, path, "--data-dir", data_dir)
    assert _contents(path) == before
