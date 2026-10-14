"""Greek evidence at Job 38:7, Daniel 4:17 and 7:13, and Psalm 29:1 (#4).

The bundled records listed Greek witnesses as agreeing with the MT where the
Rahlfs text does not. Each verse now has a manuscript-variant case for the
Greek evidence beside its interpretation notes, and
scripts/repair_textual_variant_witnesses.py brings an existing database into
line.
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

import scripts.repair_textual_variant_witnesses as repair
import study_bible_mcp.server as server_module
from scripts.import_heiser_content import import_textual_variant_record, import_textual_variants
from study_bible_mcp.database import INTERPRETIVE_CASE_KEYS, StudyBibleDB, create_schema

ROOT = Path(__file__).resolve().parent.parent
VARIANTS_DIR = ROOT / "data" / "heiser" / "variants"
REFERENCES = {reference for reference, _ in repair.CASES}

# The interpretation notes' witnesses before the fix, all labelled supports_variant.
PREVIOUS_WITNESSES = {
    "Job.38.7": [("Masoretic Text", "~900 CE"), ("LXX", "~250 BCE")],
    "Dan.7.13": [
        ("Masoretic Text", "~900 CE"), ("LXX (Theodotion)", "~150 CE"), ("LXX (OG)", "~250 BCE"),
    ],
    "Dan.4.17": [("Masoretic Text", "~900 CE"), ("LXX (Theodotion)", "~150 CE")],
    "Psa.29.1": [("Masoretic Text", "~900 CE"), ("LXX (huioi theou)", "~250 BCE")],
}


def _records() -> list[dict]:
    return [
        record
        for path in sorted(VARIANTS_DIR.glob("*.json"))
        for record in json.loads(path.read_text(encoding="utf-8"))["variants"]
    ]


def _section(output: str, heading: str) -> str:
    """Return the text under a markdown heading, up to the next heading."""
    start = output.index(heading) + len(heading)
    following = [output.find(marker, start) for marker in ("\n### ", "\n#### ", "\n## ")]
    ends = [index for index in following if index != -1]
    return output[start : min(ends) if ends else len(output)]


def _notes(output: str, reference: str) -> str:
    """The interpretation-notes case, from its heading to the end."""
    return output[output.index(f"## Translation and interpretation notes at {reference}"):]


@pytest.fixture
def fresh_db(tmp_path) -> Path:
    """A database built from the bundled records, as build_database does."""
    path = tmp_path / "fresh.db"
    conn = sqlite3.connect(path)
    create_schema(conn)
    import_textual_variants(conn, VARIANTS_DIR)
    conn.executemany(
        "INSERT INTO verses (reference, book, chapter, verse, text_english) VALUES (?, ?, ?, ?, ?)",
        [
            ("Job.38.6", "Job", 38, 6, "On what were its bases sunk?"),
            ("Job.38.7", "Job", 38, 7, "when the morning stars sang together"),
            ("Psa.82.1", "Psa", 82, 1, "God has taken his place in the divine council"),
        ],
    )
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def stale_db(tmp_path) -> Path:
    """A database imported from the records as they stood before the fix."""
    path = tmp_path / "study_bible.db"
    conn = sqlite3.connect(path)
    create_schema(conn)
    for record in _records():
        if record["reference"] in REFERENCES:
            if record["variant_source"] not in INTERPRETIVE_CASE_KEYS:
                continue  # the Greek variant cases are new
            record = {
                **record,
                "witnesses": [
                    {"manuscript": name, "manuscript_date": date,
                     "reading_support": "supports_variant"}
                    for name, date in PREVIOUS_WITNESSES[record["reference"]]
                ],
            }
        import_textual_variant_record(conn, record)
    conn.commit()
    conn.close()
    return path


@pytest.fixture
async def server_db():
    databases = []

    async def connect(path: Path) -> StudyBibleDB:
        database = StudyBibleDB(path)
        await database.connect()
        databases.append(database)
        server_module.db = database
        return database

    yield connect
    server_module.db = None
    for database in databases:
        await database.close()


async def _variant(reference: str) -> str:
    [response] = await server_module.handle_get_textual_variant({"reference": reference})
    return response.text


# ---------------------------------------------------------------------------
# Rendered output
# ---------------------------------------------------------------------------


async def test_job_38_7_shows_the_lxx_angels_apart_from_the_mt(fresh_db, server_db):
    await server_db(fresh_db)
    output = await _variant("Job 38:7")

    assert output.startswith("# Textual variant record for Job 38:7")
    # The variant comes first; the notes follow and point back to it.
    assert output.index("## Variant at Job.38.7") < output.index(
        "## Translation and interpretation notes at Job.38.7"
    )
    mt = _section(output, "#### Masoretic Text")
    lxx = _section(output, "#### LXX_divergence")
    assert "**Masoretic Text** (~900 CE) (dataset label: `supports_mt`)" in mt
    assert "LXX" not in mt
    assert "πάντες ἄγγελοί μου" in lxx
    assert "**LXX** (~250 BCE) (dataset label: `supports_variant`)" in lxx
    assert "Whether the Greek reflects a different Hebrew Vorlage or an interpretive " \
        "rendering is open" in output

    notes = _notes(output, "Job.38.7")
    assert "Not a manuscript variant" not in output
    assert "The textual evidence at this verse is in the variant record above." in notes
    assert "Witnesses agreeing with this text" not in notes
    assert "### Text (Masoretic Text)" not in notes  # shown once, in the variant
    # The interpretation notes themselves are unchanged.
    assert "the sons of God (the heavenly host) shouted for joy" in _section(
        notes, "### Translation decisions"
    )
    assert "Heiser uses Job 38:7" in _section(notes, "### Author-specific claims")
    assert "synonymous parallelism" in _section(notes, "### Theological interpretations")


async def test_daniel_4_17_lists_the_old_greek_omission(fresh_db, server_db):
    await server_db(fresh_db)
    output = await _variant("Daniel 4:17")

    mt = _section(output, "#### Masoretic Text")
    omission = _section(output, "#### LXX_OG_omission")
    assert "LXX (Theodotion: διὰ συγκρίματος ιρ ὁ λόγος καὶ ῥῆμα ἁγίων τὸ ἐπερώτημα)" in mt
    assert "LXX (OG)" not in mt
    assert "**LXX (OG)** (~250 BCE) (dataset label: `omits`)" in omission
    assert "The Old Greek has no equivalent for this clause." in omission
    assert "ἕως ἂν γνῷ τὸν κύριον τοῦ οὐρανοῦ" in omission
    assert "The Watchers terminology is preserved in Theodotion, not in the Old Greek." in output
    assert "LXX (OG)" not in _notes(output, "Dan.4.17")


async def test_daniel_7_13_separates_old_greek_epi_from_theodotion_meta(fresh_db, server_db):
    await server_db(fresh_db)
    output = await _variant("Daniel 7:13")

    mt = _section(output, "#### Masoretic Text")
    old_greek = _section(output, "#### LXX_OG_divergence")
    assert "**LXX (Theodotion: μετὰ τῶν νεφελῶν τοῦ οὐρανοῦ)** (~150 CE)" in mt
    assert "LXX (OG)" not in mt
    assert "ἐπὶ τῶν νεφελῶν τοῦ οὐρανοῦ" in old_greek
    assert "**LXX (OG)** (~250 BCE) (dataset label: `supports_variant`)" in old_greek
    assert "Theodotion" not in old_greek

    citations = _section(output, "### NT citation evidence")
    assert "**Mark 14:62 (μετὰ τῶν νεφελῶν τοῦ οὐρανοῦ)** — quotes the Masoretic Text reading" \
        in citations
    assert "**Revelation 1:7 (μετὰ τῶν νεφελῶν)** — quotes the Masoretic Text reading" in citations
    for matthew in ("Matthew 24:30", "Matthew 26:64"):
        assert f"**{matthew} (ἐπὶ τῶν νεφελῶν τοῦ οὐρανοῦ)** — quotes the LXX_OG_divergence " \
            "reading" in citations
    assert "LXX (OG)" not in _notes(output, "Dan.7.13")


async def test_psalm_29_1_records_both_halves_of_the_lxx_doublet(fresh_db, server_db):
    await server_db(fresh_db)
    output = await _variant("Psalm 29:1")

    doublet = _section(output, "#### LXX_doublet")
    assert "υἱοὶ θεοῦ" in doublet and "υἱοὺς κριῶν" in doublet
    assert "**LXX (Psalm 28:1)** (~250 BCE) (dataset label: `supports_variant`)" in doublet
    assert "huioi theou" not in output


async def test_agreed_text_notes_elsewhere_keep_their_banner(fresh_db, server_db):
    await server_db(fresh_db)
    output = await _variant("Psalm 82:1")

    assert output.startswith("# Translation and interpretation notes for Psalm 82:1")
    assert "*Not a manuscript variant: the witnesses agree with the Masoretic Text here." in output
    assert "**Witnesses agreeing with this text:** Masoretic Text (~900 CE), LXX (~250 BCE)" \
        in output
    assert "## Variant at" not in output


async def test_lookup_verse_cues_a_verse_with_both_kinds_once_as_a_variant(fresh_db, server_db):
    await server_db(fresh_db)

    [verse] = await server_module.handle_lookup_verse({"reference": "Job 38:7"})
    [passage] = await server_module.handle_lookup_verse({"reference": "Job 38:6-7"})

    assert "Textual variant catalogued for this verse (LXX_divergence)" in verse.text
    assert "no manuscript variant" not in verse.text
    assert "Textual variants catalogued in this passage: Job 38:7 (LXX_divergence)" in passage.text
    assert "no manuscript variant" not in passage.text


# ---------------------------------------------------------------------------
# scripts/repair_textual_variant_witnesses.py
# ---------------------------------------------------------------------------


def _cases(path: Path) -> dict:
    """Every case's rows, without ids, by (reference, case_key)."""
    conn = sqlite3.connect(path)
    keys = conn.execute("SELECT reference, case_key FROM textual_variant_cases").fetchall()
    cases = {key: repair.read_case(conn, *key) for key in keys}
    conn.close()
    return cases


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


def _run(monkeypatch, *argv) -> int:
    monkeypatch.setattr("sys.argv", ["repair_textual_variant_witnesses.py", *map(str, argv)])
    return repair.main()


def test_previous_records_are_the_rows_the_repair_replaces(stale_db):
    conn = sqlite3.connect(stale_db)
    for key, expected in repair.BEFORE.items():
        assert repair.digest(repair.read_case(conn, *key)) == expected, key
    conn.close()


def test_repair_from_source_is_idempotent_and_writes_a_patch(
    stale_db, fresh_db, tmp_path, monkeypatch, capsys
):
    ids = _case_ids(stale_db)
    patch = tmp_path / "patch.json.gz"

    assert _run(monkeypatch, stale_db, "--write-patch", patch) == 0
    out = capsys.readouterr().out
    assert (
        "replaced Job.38.7 MT_preserved, Job.38.7 LXX_divergence, Dan.4.17 LXX_OG_omission, "
        "Dan.7.13 MT_preserved, Dan.7.13 LXX_OG_divergence, Psa.29.1 translation_choice, "
        "Psa.29.1 LXX_doublet"
    ) in out
    assert "1 of 8 already held the corrected rows" in out  # Dan.4.17's notes are unchanged
    # Every case, touched or not, now matches a fresh build; existing ids are kept.
    assert _cases(stale_db) == _cases(fresh_db)
    assert {key: _case_ids(stale_db)[key] for key in ids} == ids

    with gzip.open(patch, "rt", encoding="utf-8") as handle:
        saved = json.load(handle)
    assert [(case["reference"], case["case_key"]) for case in saved["cases"]] == list(repair.CASES)
    assert [case["before"] for case in saved["cases"]] == [repair.BEFORE[k] for k in repair.CASES]

    assert _run(monkeypatch, stale_db) == 0
    out = capsys.readouterr().out
    assert "replaced" not in out
    assert "8 of 8 already held the corrected rows" in out
    assert _cases(stale_db) == _cases(fresh_db)


def test_patch_repairs_a_copy_with_the_standard_library_only(
    stale_db, fresh_db, tmp_path, monkeypatch
):
    server = tmp_path / "server"
    server.mkdir()
    shutil.copy(stale_db, server / "study_bible.db")
    shutil.copy(ROOT / "scripts" / "repair_textual_variant_witnesses.py", server)
    assert _run(monkeypatch, stale_db, "--write-patch", server / "patch.gz") == 0

    # -I -S: no site-packages and no project source, as on the server.
    command = [sys.executable, "-I", "-S", "repair_textual_variant_witnesses.py",
               "study_bible.db", "--apply-patch", "patch.gz"]
    first = subprocess.run(command, cwd=server, capture_output=True, text=True)
    second = subprocess.run(command, cwd=server, capture_output=True, text=True)

    assert first.returncode == 0, first.stderr
    assert "1 of 8 already held the corrected rows" in first.stdout
    assert second.returncode == 0, second.stderr
    assert "8 of 8 already held the corrected rows" in second.stdout
    assert _cases(server / "study_bible.db") == _cases(fresh_db)


def test_patch_refuses_a_database_that_differs(stale_db, tmp_path, monkeypatch, capsys):
    patch = tmp_path / "patch.json.gz"
    copy = tmp_path / "copy.db"
    shutil.copy(stale_db, copy)
    assert _run(monkeypatch, stale_db, "--write-patch", patch) == 0
    capsys.readouterr()

    # A witness edited since the patch was made: nothing is changed, not even
    # the cases that are still as expected.
    conn = sqlite3.connect(copy)
    conn.execute(
        "UPDATE textual_variant_witnesses SET approximate_date = '~200 BCE' "
        "WHERE witness = 'LXX (huioi theou)'"
    )
    conn.commit()
    conn.close()
    before = _cases(copy)
    assert _run(monkeypatch, copy, "--apply-patch", patch) == 1
    err = capsys.readouterr().err
    assert "Psa.29.1 translation_choice holds neither" in err
    assert "Nothing was changed" in err
    assert _cases(copy) == before

    # A new case that already exists with other rows.
    conn = sqlite3.connect(copy)
    conn.execute(
        "UPDATE textual_variant_witnesses SET approximate_date = '~250 BCE' "
        "WHERE witness = 'LXX (huioi theou)'"
    )
    conn.execute(
        "INSERT INTO textual_variant_cases (reference, book, chapter, verse, case_key) "
        "VALUES ('Job.38.7', 'Job', 38, 7, 'LXX_divergence')"
    )
    conn.commit()
    conn.close()
    before = _cases(copy)
    assert _run(monkeypatch, copy, "--apply-patch", patch) == 1
    assert "Job.38.7 LXX_divergence holds neither" in capsys.readouterr().err
    assert _cases(copy) == before

    # A case the patch replaces that is missing.
    conn = sqlite3.connect(copy)
    conn.execute("DELETE FROM textual_variant_cases WHERE case_key = 'LXX_divergence'")
    for table in ("textual_variant_witnesses", "textual_variant_readings",
                  *repair.CLAIM_TABLES):
        conn.execute(
            f"DELETE FROM {table} WHERE case_id = (SELECT id FROM textual_variant_cases "
            "WHERE reference = 'Dan.7.13' AND case_key = 'MT_preserved')"
        )
    conn.execute(
        "DELETE FROM textual_variant_cases WHERE reference = 'Dan.7.13' "
        "AND case_key = 'MT_preserved'"
    )
    conn.commit()
    conn.close()
    before = _cases(copy)
    assert _run(monkeypatch, copy, "--apply-patch", patch) == 1
    assert "Dan.7.13 MT_preserved is missing" in capsys.readouterr().err
    assert _cases(copy) == before


def test_repair_refuses_records_other_than_the_expected_cases(stale_db, tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    shutil.copytree(VARIANTS_DIR, data_dir / "heiser" / "variants")
    daniel = data_dir / "heiser" / "variants" / "daniel.json"
    records = json.loads(daniel.read_text(encoding="utf-8"))
    records["variants"] = [
        record for record in records["variants"] if record["variant_source"] != "LXX_OG_omission"
    ]
    daniel.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
    before = _cases(stale_db)

    with pytest.raises(SystemExit, match="expected"):
        _run(monkeypatch, stale_db, "--data-dir", data_dir)
    assert _cases(stale_db) == before
