import dataclasses
import json
import sqlite3
from pathlib import Path

import pytest

import study_bible_mcp.server as server_module
from scripts.import_heiser_content import (
    import_nt_ot_lxx_quote_hints,
    import_textual_variant_record,
    import_textual_variants,
)
from scripts.migrate_textual_variants import migrate
from study_bible_mcp.database import StudyBibleDB, create_schema
from study_bible_mcp.tools import format_textual_variant_cases

LEGACY_SCHEMA = """
    CREATE TABLE verses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        reference TEXT UNIQUE NOT NULL, book TEXT, chapter INTEGER, verse INTEGER,
        text_english TEXT, text_original TEXT, word_data TEXT, section_end TEXT
    );
    CREATE TABLE textual_variants (
        id INTEGER PRIMARY KEY,
        reference TEXT NOT NULL,
        book TEXT NOT NULL,
        chapter INTEGER,
        verse INTEGER,
        mt_reading TEXT NOT NULL,
        mt_hebrew TEXT,
        variant_source TEXT NOT NULL,
        variant_reading TEXT NOT NULL,
        variant_original TEXT,
        variant_significance TEXT,
        heiser_analysis TEXT,
        heiser_content_id INTEGER,
        scholarly_consensus TEXT,
        preferred_for_hlt TEXT,
        hlt_rationale TEXT
    );
    CREATE TABLE manuscript_witnesses (
        id INTEGER PRIMARY KEY,
        variant_id INTEGER NOT NULL,
        manuscript TEXT NOT NULL,
        manuscript_date TEXT,
        reading_support TEXT
    );
    CREATE TABLE nt_ot_lxx_quote_hints (
        id INTEGER PRIMARY KEY,
        nt_reference TEXT NOT NULL,
        nt_display TEXT NOT NULL,
        nt_book TEXT NOT NULL,
        ot_reference TEXT NOT NULL,
        ot_display TEXT NOT NULL,
        ot_book TEXT NOT NULL,
        follows_lxx INTEGER NOT NULL,
        divergence_type TEXT,
        divergence_note TEXT,
        textual_variant_id INTEGER
    );
"""


def _legacy_variant(variant_id, reference, source, consensus=None):
    book, chapter, verse = reference.split(".")
    return (
        variant_id, reference, book, int(chapter), int(verse),
        f"{reference} MT reading", None, source, f"{reference} variant reading",
        None, "major", None, None, consensus, None, None,
    )


def _create_legacy_db(path: Path, extra_witnesses=()) -> None:
    """Small legacy DB mirroring the production witness labels."""
    conn = sqlite3.connect(path)
    conn.executescript(LEGACY_SCHEMA)
    conn.execute(
        "INSERT INTO verses VALUES (NULL, 'Psa.40.6(40.7)', 'Psa', 40, 6, 'ears', 'אזנים', '[]', NULL)"
    )
    conn.executemany(
        "INSERT INTO textual_variants VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            _legacy_variant(1, "Jer.33.14", "LXX_omission", "Unsourced summary."),
            _legacy_variant(2, "Psa.40.6", "LXX_quoted_in_NT"),
            _legacy_variant(3, "Gen.6.2", "MT_preserved"),
        ],
    )
    conn.executemany(
        "INSERT INTO manuscript_witnesses VALUES (NULL, ?, ?, ?, ?)",
        [
            (1, "LXX (Jer 40 ends at v.13)", "~150 BCE", "omits"),
            (1, "4QJer^b (short Vorlage elsewhere in Jer)", "~200 BCE", "supports_short_form_pattern"),
            (1, "Masoretic Text", "~900 CE", "supports_long_form"),
            (2, "LXX", "~150 BCE", "supports_variant"),
            (2, "Masoretic Text", "~900 CE", "supports_mt"),
            (2, "DSS (none preserved)", "", "not_preserved"),
            (2, "Hebrews 10:5-7", "~65 CE", "supports_variant"),
            (3, "Masoretic Text", "~900 CE", "supports_variant"),
            *extra_witnesses,
        ],
    )
    conn.execute(
        """INSERT INTO nt_ot_lxx_quote_hints VALUES
           (1, 'Heb.10.5', 'Hebrews 10:5-7', 'Heb', 'Psa.40.6', 'Psalm 40:6',
            'Psa', 1, 'vorlage_or_paraphrase', 'body vs ears', 2)"""
    )
    conn.commit()
    conn.close()


async def _cases(db_path: Path, reference: str) -> list[dict]:
    database = StudyBibleDB(db_path)
    await database.connect()
    try:
        return await database.get_textual_variant_cases(reference)
    finally:
        await database.close()


def _section(output: str, heading: str) -> str:
    """Return the text under a markdown heading, up to the next heading."""
    start = output.index(heading) + len(heading)
    following = [output.find(marker, start) for marker in ("\n### ", "\n#### ", "\n## ")]
    ends = [index for index in following if index != -1]
    return output[start : min(ends) if ends else len(output)]


@pytest.mark.asyncio
async def test_import_keeps_variant_evidence_and_interpretation_separate(tmp_path):
    db_path = tmp_path / "variants.db"
    conn = sqlite3.connect(db_path)
    create_schema(conn)

    variants_dir = Path(__file__).parents[1] / "data" / "heiser" / "variants"
    imported = import_textual_variants(conn, variants_dir)
    legacy_tables = conn.execute(
        """SELECT name FROM sqlite_master
           WHERE type = 'table' AND name IN ('textual_variants', 'manuscript_witnesses')"""
    ).fetchall()
    conn.close()

    cases = await _cases(db_path, "Deuteronomy 32:8")
    [interpretive] = await _cases(db_path, "Psalm 82:6")

    assert imported == 31
    assert legacy_tables == []
    assert len(cases) == 1

    # Agreed-text records keep the MT as their only reading and their HLT
    # decision and Heiser claim, with the record's prose as interpretation.
    assert interpretive["kind"] == "interpretive"
    assert [r["reading_key"] for r in interpretive["manuscript_evidence"]] == ["mt"]
    assert {w["witness"] for w in interpretive["manuscript_evidence"][0]["witnesses"]} == {
        "Masoretic Text",
        "LXX (theoi este)",
    }
    assert interpretive["critical_judgments"] == []
    assert interpretive["unsourced_summaries"] == []
    assert "shining ones" in interpretive["translation_decisions"][0]["preferred_reading"]
    assert interpretive["author_specific_claims"][0]["author"] == "Michael S. Heiser"
    assert [i["attribution"] for i in interpretive["theological_interpretations"]] == [
        "Dataset editorial note",
        "Dataset summary of scholarly opinion",
    ]

    case = cases[0]
    assert case["kind"] == "manuscript"
    assert set(case) >= {
        "manuscript_evidence",
        "citation_evidence",
        "indirect_evidence",
        "not_preserved_in",
        "critical_judgments",
        "unsourced_summaries",
        "theological_interpretations",
        "author_specific_claims",
        "translation_decisions",
    }
    readings = {reading["reading_key"]: reading for reading in case["manuscript_evidence"]}
    assert set(readings) == {"mt", "variant"}
    assert {w["witness"] for w in readings["mt"]["witnesses"]} == {
        "Masoretic Text",
        "Aquila Codex X",
        "Symmachus Codex X",
        "Theodotion",
    }
    assert "4QDeutj" in {
        w["witness"] for w in readings["variant"]["witnesses"]
    }
    assert case["critical_judgments"] == []
    assert case["unsourced_summaries"][0]["attribution"] == "Dataset editorial summary"
    assert case["theological_interpretations"] == []
    assert case["author_specific_claims"][0]["author"] == "Michael S. Heiser"
    assert case["translation_decisions"][0]["translation"] == (
        "Heiser Literal Translation (HLT)"
    )


def test_bundled_quotation_hints_link_to_bundled_cases(tmp_path):
    data_dir = Path(__file__).parents[1] / "data" / "heiser"
    conn = sqlite3.connect(tmp_path / "variants.db")
    create_schema(conn)
    import_textual_variants(conn, data_dir / "variants")

    first = import_nt_ot_lxx_quote_hints(conn, data_dir / "lxx_quote_hints.json")
    second = import_nt_ot_lxx_quote_hints(conn, data_dir / "lxx_quote_hints.json")
    links = dict(
        conn.execute(
            """SELECT h.nt_reference, c.reference || ' ' || c.case_key
               FROM nt_ot_lxx_quote_hints h
               JOIN textual_variant_cases c ON c.id = h.variant_case_id"""
        ).fetchall()
    )
    total = conn.execute("SELECT COUNT(*) FROM nt_ot_lxx_quote_hints").fetchone()[0]
    conn.close()

    assert first == second == total == 22
    assert links == {
        "Heb.10.5": "Psa.40.6 LXX_quoted_in_NT",
        "Heb.1.6": "Deu.32.43 DSS_4QDeutq",
        "Act.15.17": "Amo.9.12 LXX_quoted_in_NT",
        "Luk.4.18": "Isa.61.1 LXX_quoted_in_NT",
        "Luk.3.6": "Isa.40.5 LXX_quoted_in_NT",
        "Mat.21.16": "Psa.8.2 LXX_quoted_in_NT",
        "Mrk.14.62": "Dan.7.13 LXX_OG_divergence",
        "Mat.26.64": "Dan.7.13 LXX_OG_divergence",
        "Mat.24.30": "Dan.7.13 LXX_OG_divergence",
        "Rev.1.7": "Dan.7.13 LXX_OG_divergence",
    }


def test_quotation_hint_linking_a_missing_case_fails(tmp_path):
    hints_path = tmp_path / "hints.json"
    hints_path.write_text(json.dumps({"hints": [{
        "nt_reference": "Heb.10.5", "nt_display": "Hebrews 10:5", "nt_book": "Heb",
        "ot_reference": "Psa.40.6", "ot_display": "Psalm 40:6", "ot_book": "Psa",
        "follows_lxx": 1, "divergence_type": None, "divergence_note": None,
        "variant_case": {"reference": "Psa.40.6", "case_key": "LXX_quoted_in_NT"},
    }]}))
    conn = sqlite3.connect(tmp_path / "variants.db")
    create_schema(conn)

    with pytest.raises(ValueError, match="links to missing case Psa.40.6"):
        import_nt_ot_lxx_quote_hints(conn, hints_path)
    conn.close()


@pytest.mark.asyncio
async def test_unsourced_summary_is_not_rendered_as_critical_judgment(tmp_path):
    db_path = tmp_path / "variants.db"
    conn = sqlite3.connect(db_path)
    create_schema(conn)
    import_textual_variants(conn, Path(__file__).parents[1] / "data" / "heiser" / "variants")
    case_id = conn.execute(
        "SELECT id FROM textual_variant_cases WHERE reference = 'Deu.32.8'"
    ).fetchone()[0]
    conn.execute(
        """INSERT INTO textual_critical_judgments
           (case_id, judgment, attribution, source_citation)
           VALUES (?, 'Cited judgment.', 'Example editor', 'Example, Textual Criticism, p. 1')""",
        (case_id,),
    )
    conn.commit()
    conn.close()

    output = format_textual_variant_cases(
        "Deuteronomy 32:8", await _cases(db_path, "Deuteronomy 32:8"), []
    )

    judgments = _section(output, "### Critical judgments")
    unsourced = _section(
        output,
        "### Unsourced dataset summary (not verified against published "
        "text-critical scholarship)",
    )
    assert "Cited judgment." in judgments
    assert "Example, Textual Criticism, p. 1" in judgments
    assert "MT altered" not in judgments
    assert "MT altered" in unsourced


def test_migration_rebuilds_legacy_schema_and_preserves_hint_links(tmp_path):
    db_path = tmp_path / "legacy.db"
    _create_legacy_db(db_path)
    conn = sqlite3.connect(db_path)

    result = migrate(conn)

    assert result == (2, 1, 1)
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert "textual_variants" not in tables
    assert "manuscript_witnesses" not in tables
    assert "textual_variant_cases" in tables
    case_id = conn.execute(
        "SELECT id FROM textual_variant_cases WHERE reference = 'Psa.40.6'"
    ).fetchone()[0]
    linked_case_id = conn.execute(
        "SELECT variant_case_id FROM nt_ot_lxx_quote_hints"
    ).fetchone()[0]
    assert linked_case_id == case_id
    assert conn.execute("SELECT COUNT(*) FROM textual_variant_witnesses").fetchone()[0] == 8
    conn.close()


@pytest.mark.asyncio
async def test_witnesses_are_classified_by_evidence_type(tmp_path):
    db_path = tmp_path / "legacy.db"
    _create_legacy_db(db_path)
    conn = sqlite3.connect(db_path)
    migrate(conn)
    conn.close()

    [jeremiah] = await _cases(db_path, "Jeremiah 33:14")
    readings = {r["reading_key"]: r for r in jeremiah["manuscript_evidence"]}
    assert [(w["witness"], w["reading_support"]) for w in readings["mt"]["witnesses"]] == [
        ("Masoretic Text", "supports_long_form")
    ]
    assert [w["witness"] for w in readings["variant"]["witnesses"]] == [
        "LXX (Jer 40 ends at v.13)"
    ]
    assert [w["witness"] for w in jeremiah["indirect_evidence"]] == [
        "4QJer^b (short Vorlage elsewhere in Jer)"
    ]

    [psalm] = await _cases(db_path, "Psalm 40:6")
    readings = {r["reading_key"]: r for r in psalm["manuscript_evidence"]}
    assert [w["witness"] for w in readings["variant"]["witnesses"]] == ["LXX"]
    assert [(w["witness"], w["reading_key"]) for w in psalm["citation_evidence"]] == [
        ("Hebrews 10:5-7", "variant")
    ]
    assert [w["witness"] for w in psalm["not_preserved_in"]] == ["DSS (none preserved)"]

    jeremiah_output = format_textual_variant_cases("Jeremiah 33:14", [jeremiah], [])
    assert "Masoretic Text" in _section(jeremiah_output, "#### Masoretic Text")
    assert "4QJer^b" not in _section(jeremiah_output, "#### LXX_omission")
    assert "4QJer^b" in _section(jeremiah_output, "### Indirect evidence")

    psalm_output = format_textual_variant_cases("Psalm 40:6", [psalm], [])
    assert "Hebrews 10:5-7" not in _section(psalm_output, "#### LXX_quoted_in_NT")
    assert "Hebrews 10:5-7" in _section(psalm_output, "### NT citation evidence")
    assert "**Not preserved in:** DSS\n" in psalm_output


def test_unknown_reading_support_aborts_migration(tmp_path):
    db_path = tmp_path / "legacy.db"
    _create_legacy_db(db_path, [(2, "Vulgate", "~400 CE", "supports_something_new")])
    conn = sqlite3.connect(db_path)

    with pytest.raises(ValueError, match="supports_something_new"):
        migrate(conn)

    assert conn.execute("SELECT COUNT(*) FROM textual_variants").fetchone()[0] == 3
    assert conn.execute("SELECT COUNT(*) FROM manuscript_witnesses").fetchone()[0] == 9
    assert conn.execute("SELECT COUNT(*) FROM textual_variant_cases").fetchone()[0] == 0
    conn.close()


def _variant_record(**overrides) -> dict:
    record = {
        "reference": "Deu.32.43",
        "variant_source": "DSS_4QDeutq",
        "mt_reading": "short reading",
        "variant_reading": "long reading",
        "scholarly_consensus": "Original summary.",
        "witnesses": [
            {"manuscript": "4QDeutq", "manuscript_date": "~100 BCE", "reading_support": "supports_variant"},
            {"manuscript": "Masoretic Text", "manuscript_date": "~900 CE", "reading_support": "supports_mt"},
        ],
    }
    record.update(overrides)
    return record


def _case_rows(conn: sqlite3.Connection) -> tuple:
    return (
        conn.execute(
            "SELECT witness, evidence_type FROM textual_variant_witnesses ORDER BY witness"
        ).fetchall(),
        conn.execute("SELECT judgment FROM textual_critical_judgments").fetchall(),
        conn.execute("SELECT reading_key, text FROM textual_variant_readings ORDER BY 1").fetchall(),
    )


def test_failed_record_replacement_keeps_existing_rows(tmp_path):
    conn = sqlite3.connect(tmp_path / "variants.db")
    create_schema(conn)
    import_textual_variant_record(conn, _variant_record())
    conn.commit()
    before = _case_rows(conn)

    # Fails validation before any row is touched.
    with pytest.raises(ValueError, match="bogus"):
        import_textual_variant_record(
            conn,
            _variant_record(
                scholarly_consensus="Replacement summary.",
                witnesses=[{"manuscript": "X", "reading_support": "bogus"}],
            ),
        )
    assert _case_rows(conn) == before

    # Fails while writing, after the old child rows were deleted: the
    # duplicate witness violates UNIQUE(case_id, witness).
    duplicate = {"manuscript": "4QDeutq", "reading_support": "supports_variant"}
    with pytest.raises(sqlite3.IntegrityError):
        import_textual_variant_record(
            conn,
            _variant_record(
                scholarly_consensus="Replacement summary.",
                witnesses=[duplicate, duplicate],
            ),
        )
    assert _case_rows(conn) == before
    conn.commit()
    assert _case_rows(conn) == before
    conn.close()


def test_import_reports_malformed_records_and_keeps_their_rows(tmp_path):
    db_path = tmp_path / "variants.db"
    conn = sqlite3.connect(db_path)
    create_schema(conn)
    import_textual_variant_record(conn, _variant_record())
    conn.commit()
    before = _case_rows(conn)

    variants_dir = tmp_path / "variants"
    variants_dir.mkdir()
    (variants_dir / "bad.json").write_text(
        json.dumps({"variants": [_variant_record(mt_reading="", scholarly_consensus="New.")]})
    )
    (variants_dir / "good.json").write_text(
        json.dumps({"variants": [_variant_record(reference="Deu.32.8", variant_source="DSS_4QDeutj")]})
    )

    with pytest.raises(ValueError, match=r"bad\.json Deu\.32\.43"):
        import_textual_variants(conn, variants_dir)
    conn.close()

    conn = sqlite3.connect(db_path)
    references = {
        row[0] for row in conn.execute("SELECT reference FROM textual_variant_cases")
    }
    assert references == {"Deu.32.43", "Deu.32.8"}
    assert conn.execute(
        """SELECT judgment FROM textual_critical_judgments j
           JOIN textual_variant_cases c ON c.id = j.case_id
           WHERE c.reference = 'Deu.32.43'"""
    ).fetchall() == before[1]
    conn.close()


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


@pytest.mark.asyncio
async def test_get_textual_variant_requires_upgrade_on_legacy_or_missing_schema(
    tmp_path, server_db
):
    legacy = tmp_path / "legacy.db"
    _create_legacy_db(legacy)
    conn = sqlite3.connect(legacy)
    create_schema(conn)  # new empty tables beside the legacy ones
    conn.close()
    missing = tmp_path / "missing.db"
    sqlite3.connect(missing).execute("CREATE TABLE verses (reference TEXT)").connection.close()
    empty = tmp_path / "empty.db"
    conn = sqlite3.connect(empty)
    create_schema(conn)
    conn.close()

    for path, reason in (
        (legacy, "legacy textual-variant schema"),
        (missing, "no textual-variant tables"),
        (empty, "no textual-variant cases loaded"),
    ):
        await server_db(path)
        [response] = await server_module.handle_get_textual_variant(
            {"reference": "Psalm 40:6"}
        )
        assert reason in response.text
        assert "python scripts/upgrade_database.py" in response.text


@pytest.mark.asyncio
async def test_get_textual_variant_distinguishes_invalid_input_and_no_match(
    tmp_path, server_db
):
    db_path = tmp_path / "legacy.db"
    _create_legacy_db(db_path)
    conn = sqlite3.connect(db_path)
    migrate(conn)
    conn.close()
    await server_db(db_path)

    [invalid] = await server_module.handle_get_textual_variant({"reference": "Psalm 40"})
    [no_match] = await server_module.handle_get_textual_variant({"reference": "Genesis 1:1"})
    [nt_side] = await server_module.handle_get_textual_variant({"reference": "Hebrews 10:5"})

    assert "is not a single-verse reference" in invalid.text
    assert "upgrade_database" not in invalid.text
    assert no_match.text == (
        "No textual-variant case or NT quotation alignment is catalogued for Genesis 1:1."
    )
    assert "## Variant at Psa.40.6" in nt_side.text


@pytest.mark.asyncio
async def test_lookup_verse_cues_catalogued_variant_case(tmp_path, server_db):
    db_path = tmp_path / "legacy.db"
    _create_legacy_db(db_path)
    conn = sqlite3.connect(db_path)
    migrate(conn)
    conn.execute(
        "INSERT INTO verses VALUES (NULL, 'Jer.33.14', 'Jer', 33, 14, 'days', 'ימים', '[]', NULL)"
    )
    conn.commit()
    conn.close()
    await server_db(db_path)

    [jeremiah] = await server_module.handle_lookup_verse({"reference": "Jeremiah 33:14"})
    [psalm] = await server_module.handle_lookup_verse({"reference": "Psalm 40:6"})

    assert "Textual variant catalogued for this verse (LXX_omission)" in jeremiah.text
    assert "NT↔OT LXX-form quotation" not in jeremiah.text
    assert "Textual variant catalogued for this verse (LXX_quoted_in_NT)" in psalm.text


async def test_interpretive_case_is_shown_as_notes_not_a_variant(tmp_path, server_db):
    db_path = tmp_path / "legacy.db"
    _create_legacy_db(db_path)
    conn = sqlite3.connect(db_path)
    migrate(conn)
    conn.execute(
        "INSERT INTO verses VALUES (NULL, 'Gen.6.2', 'Gen', 6, 2, 'sons of God', 'בני האלהים', '[]', NULL)"
    )
    conn.commit()
    conn.close()
    await server_db(db_path)

    [notes] = await server_module.handle_get_textual_variant({"reference": "Genesis 6:2"})
    [verse] = await server_module.handle_lookup_verse({"reference": "Genesis 6:2"})

    assert notes.text.startswith("# Translation and interpretation notes for Genesis 6:2")
    assert "## Translation and interpretation notes at Gen.6.2" in notes.text
    assert "Not a manuscript variant" in notes.text
    assert "Gen.6.2 variant reading" in _section(notes.text, "### Theological interpretations")
    assert "**Witnesses agreeing with this text:** Masoretic Text (~900 CE)" in notes.text
    assert "## Variant at" not in notes.text
    assert "dataset label" not in notes.text
    assert "catalogued.*" not in notes.text  # empty sections are omitted
    assert "Translation and interpretation notes catalogued for this verse" in verse.text
    assert "Textual variant catalogued" not in verse.text


@pytest.mark.asyncio
async def test_lookup_verse_omits_variant_cue_on_legacy_db(tmp_path, server_db):
    db_path = tmp_path / "legacy.db"
    _create_legacy_db(db_path)
    await server_db(db_path)

    [psalm] = await server_module.handle_lookup_verse({"reference": "Psalm 40:6"})

    assert "Textual variant catalogued" not in psalm.text


def _variant_snapshot(path: Path) -> dict:
    conn = sqlite3.connect(path)
    queries = {
        "schema": "SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY name",
        "cases": "SELECT * FROM textual_variant_cases ORDER BY id",
        "readings": """SELECT c.reference, r.reading_key, r.tradition, r.text
                       FROM textual_variant_readings r
                       JOIN textual_variant_cases c ON c.id = r.case_id ORDER BY 1, 2""",
        "witnesses": """SELECT c.reference, r.reading_key, w.witness, w.evidence_type,
                               w.reading_support, w.approximate_date
                        FROM textual_variant_witnesses w
                        JOIN textual_variant_cases c ON c.id = w.case_id
                        LEFT JOIN textual_variant_readings r ON r.id = w.reading_id
                        ORDER BY 1, 3""",
        "judgments": "SELECT case_id, judgment, attribution FROM textual_critical_judgments ORDER BY 1, 2",
        "hints": "SELECT * FROM nt_ot_lxx_quote_hints ORDER BY id",
        "verses": "SELECT * FROM verses",
    }
    snapshot = {key: conn.execute(sql).fetchall() for key, sql in queries.items()}
    conn.close()
    return snapshot


def test_upgrade_is_repeatable_and_failure_leaves_original_untouched(
    tmp_path, monkeypatch
):
    import scripts.upgrade_database as upgrade_database

    database = tmp_path / "study_bible.db"
    _create_legacy_db(database)
    data_dir = tmp_path / "data"
    variants_dir = data_dir / "heiser" / "variants"
    variants_dir.mkdir(parents=True)
    (variants_dir / "deuteronomy.json").write_text(
        json.dumps({"variants": [_variant_record()]})
    )
    # Corpus importers have their own tests; stub them so this test exercises
    # the migration, variant import, integrity/FK checks, and file swap.
    monkeypatch.setattr(upgrade_database, "import_biblical_versions", lambda conn, path: (3, 2))
    monkeypatch.setattr(upgrade_database, "missing_corpora", lambda root: {})
    monkeypatch.setattr(
        upgrade_database, "import_available_corpora", lambda conn, root: {"josephus": 1}
    )

    first = upgrade_database.upgrade_in_place(database, data_dir)
    first_snapshot = _variant_snapshot(database)
    second = upgrade_database.upgrade_in_place(database, data_dir)
    second_snapshot = _variant_snapshot(database)

    assert first["migrated_variant_cases"] == 2
    assert second["migrated_variant_cases"] == 0
    assert first["migrated_interpretive_cases"] == 1
    assert first["textual_variant_cases"] == second["textual_variant_cases"] == 4
    assert first_snapshot == second_snapshot
    assert first["josephus_passages"] == second["josephus_passages"] == 1
    assert first["strongs_index_rows"] == second["strongs_index_rows"]
    assert not database.with_name(database.name + ".upgrade-tmp").exists()

    original_bytes = database.read_bytes()

    def failing_corpora(conn, root):
        raise RuntimeError("corpus import failed")

    monkeypatch.setattr(upgrade_database, "import_available_corpora", failing_corpora)
    with pytest.raises(RuntimeError, match="corpus import failed"):
        upgrade_database.upgrade_in_place(database, data_dir)

    assert database.read_bytes() == original_bytes
    assert not database.with_name(database.name + ".upgrade-tmp").exists()

    legacy = tmp_path / "legacy.db"
    _create_legacy_db(legacy)
    legacy_bytes = legacy.read_bytes()
    with pytest.raises(RuntimeError, match="corpus import failed"):
        upgrade_database.upgrade_in_place(legacy, data_dir)
    assert legacy.read_bytes() == legacy_bytes


def test_upgrade_fails_when_a_registered_corpus_is_missing(tmp_path, monkeypatch):
    import click

    import scripts.upgrade_database as upgrade_database
    from study_bible_mcp.corpora import CORPORA

    database = tmp_path / "study_bible.db"
    _create_legacy_db(database)
    original_bytes = database.read_bytes()
    ancient = tmp_path / "data" / "ancient_sources"
    for corpus in CORPORA.values():
        (ancient / corpus.data_dir).mkdir(parents=True)
    # Every corpus directory exists but one; the others pass their file check.
    (ancient / "qumran").rmdir()
    for key, corpus in CORPORA.items():
        if key != "qumran":
            monkeypatch.setitem(
                CORPORA, key, dataclasses.replace(corpus, require_files=lambda directory: None)
            )

    with pytest.raises(click.ClickException, match=r"Missing ancient-source corpora.*qumran"):
        upgrade_database.require_ancient_sources(ancient)
    with pytest.raises(click.ClickException, match="qumran"):
        upgrade_database.upgrade_in_place(database, tmp_path / "data")
    assert database.read_bytes() == original_bytes

    # A present but incomplete corpus fails too, naming the missing file.
    (ancient / "qumran").mkdir()
    with pytest.raises(click.ClickException, match=r"qumran: .*incomplete; missing"):
        upgrade_database.require_ancient_sources(ancient)

    # Corpora that were never imported (e.g. a stub import) also fail the upgrade.
    monkeypatch.setitem(
        CORPORA, "qumran", dataclasses.replace(CORPORA["qumran"], require_files=lambda directory: None)
    )
    monkeypatch.setattr(upgrade_database, "import_biblical_versions", lambda conn, path: (3, 2))
    monkeypatch.setattr(
        upgrade_database, "import_available_corpora",
        lambda conn, root: {key: (None if key == "philo" else 1) for key in CORPORA},
    )
    with pytest.raises(click.ClickException, match=r"not imported: philo"):
        upgrade_database.upgrade_in_place(database, tmp_path / "data")
    assert database.read_bytes() == original_bytes
