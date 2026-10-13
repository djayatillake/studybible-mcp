"""Behavioural tests for lookup_verse: single verses, ranges, and chapters."""

import json
import re
import sqlite3

import pytest

import study_bible_mcp.server as server
from study_bible_mcp.database import StudyBibleDB, create_schema, expand_single_chapter_reference


def _verse_row(reference, book, chapter, verse):
    words = [{"word": f"w{chapter}.{verse}", "strongs": "G0001", "gloss": "gloss", "morph": "V-PAI-3S"}]
    return (
        reference, book, chapter, verse,
        f"English {book} {chapter}:{verse}", f"Original {book} {chapter}:{verse}",
        json.dumps(words),
    )


def _fixture_rows():
    rows = [_verse_row("Jhn.3.16", "Jhn", 3, 16)]
    rows += [_verse_row(f"Luk.19.{v}", "Luk", 19, v) for v in (1, 2, 3, 4, 44, 45, 46, 47, 48)]
    rows += [_verse_row(f"Luk.20.{v}", "Luk", 20, v) for v in (1, 2, 3)]
    # OT rows keyed by English(Hebrew) numbering, as in STEPBible TAHOT.
    rows += [_verse_row(f"Psa.40.{v}(40.{v + 1})", "Psa", 40, v) for v in range(0, 10)]
    rows += [_verse_row(f"Psa.119.{v}", "Psa", 119, v) for v in range(1, 61)]
    # Psalms with a verse-0 superscription: 50 and 72 numbered verses.
    rows += [_verse_row(f"Psa.18.{v}(18.{v + 1})", "Psa", 18, v) for v in range(0, 51)]
    rows += [_verse_row(f"Psa.78.{v}(78.{v + 1})", "Psa", 78, v) for v in range(0, 73)]
    # One English verse stored as two rows.
    rows += [
        _verse_row("1Ch.12.4", "1Ch", 12, 4),
        _verse_row("1Ch.12.4(12.5)", "1Ch", 12, 4),
        _verse_row("1Ch.12.5(12.6)", "1Ch", 12, 5),
    ]
    rows += [_verse_row(f"Heb.10.{v}", "Heb", 10, v) for v in (5, 6, 7)]
    # Single-chapter books.
    rows += [_verse_row(f"Jud.1.{v}", "Jud", 1, v) for v in range(1, 26)]
    rows += [_verse_row(f"Phm.1.{v}", "Phm", 1, v) for v in range(1, 26)]
    rows += [_verse_row(f"3Jn.1.{v}", "3Jn", 1, v) for v in range(1, 16)]
    return rows


@pytest.fixture
async def lookup_db(tmp_path, monkeypatch):
    db_path = tmp_path / "lookup.db"
    conn = sqlite3.connect(db_path)
    create_schema(conn)
    conn.executemany(
        """INSERT INTO verses (reference, book, chapter, verse, text_english, text_original, word_data)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        _fixture_rows(),
    )
    conn.execute(
        """INSERT INTO nt_ot_lxx_quote_hints
           (nt_reference, nt_display, nt_book, ot_reference, ot_display, ot_book, divergence_type)
           VALUES ('Heb.10.5', 'Hebrews 10:5-7', 'Heb', 'Psa.40.6', 'Psalm 40:6', 'Psa',
                   'vorlage_or_paraphrase')"""
    )
    conn.executemany(
        """INSERT INTO textual_variant_cases (reference, book, chapter, verse, case_key)
           VALUES (?, 'Psa', 40, ?, ?)""",
        [("Psa.40.6", 6, "LXX_quoted_in_NT"), ("Psa.40.8", 8, "MT_preserved")],
    )
    conn.commit()
    conn.close()
    db = StudyBibleDB(db_path)
    await db.connect()
    monkeypatch.setattr(server, "db", db)
    yield db
    await db.close()


async def _lookup(reference, **kwargs):
    result = await server.handle_lookup_verse({"reference": reference, **kwargs})
    return result[0].text


def _verse_headings(output):
    return re.findall(r"^## (\S+\.\d+\.\d+\S*)$", output, re.MULTILINE)


async def test_verse_range_returns_every_verse_in_order(lookup_db):
    output = await _lookup("Luke 19:1-3")
    assert _verse_headings(output) == ["Luk.19.1", "Luk.19.2", "Luk.19.3"]
    assert output.startswith("# Luke 19:1-3\n")


async def test_en_dash_range_is_accepted(lookup_db):
    output = await _lookup("Luke 19:1\u20133")
    assert _verse_headings(output) == ["Luk.19.1", "Luk.19.2", "Luk.19.3"]


async def test_whole_chapter_returns_the_chapter(lookup_db):
    output = await _lookup("Luke 19")
    assert _verse_headings(output) == [f"Luk.19.{v}" for v in (1, 2, 3, 4, 44, 45, 46, 47, 48)]
    assert output.startswith("# Luke 19\n")


async def test_cross_chapter_range(lookup_db):
    output = await _lookup("Luke 19:45-20:2")
    assert _verse_headings(output) == [
        "Luk.19.45", "Luk.19.46", "Luk.19.47", "Luk.19.48", "Luk.20.1", "Luk.20.2",
    ]


async def test_split_numbered_ot_verse_and_range(lookup_db):
    single = await _lookup("Psalm 40:6")
    assert _verse_headings(single) == ["Psa.40.6(40.7)"]
    ranged = await _lookup("Psalm 40:6-8")
    assert _verse_headings(ranged) == ["Psa.40.6(40.7)", "Psa.40.7(40.8)", "Psa.40.8(40.9)"]


async def test_single_verse_output_is_the_plain_verse_with_verse_hints(lookup_db):
    output = await _lookup("John 3:16")
    assert output.startswith("## Jhn.3.16\n\nEnglish Jhn 3:16\n")
    assert _verse_headings(output) == ["Jhn.3.16"]
    assert "`get_cross_references` (reference='John 3:16')" in output
    assert "Gage/Bradley John↔Revelation" in output


async def test_english_verse_stored_as_two_rows_returns_both(lookup_db):
    output = await _lookup("1 Chronicles 12:4")
    assert _verse_headings(output) == ["1Ch.12.4", "1Ch.12.4(12.5)"]


async def test_passage_hints_are_emitted_once(lookup_db):
    output = await _lookup("Psalm 40:6-8")
    assert output.count("## Genre:") == 1
    assert output.count("NT↔OT LXX-form quotation") == 1
    assert "Psalm 40:6 quoted in **Hebrews 10:5-7**" in output
    assert output.count("get_cross_references") == 1
    assert "reference='Psalm 40:6'" in output


async def test_nt_passage_lxx_hint_names_the_quoted_source(lookup_db):
    output = await _lookup("Hebrews 10:5-7")
    assert output.count("NT↔OT LXX-form quotation") == 1
    assert "quotes **Psalm 40:6** in its LXX form" in output


async def test_variant_cue_names_the_case_verse_inside_a_passage(lookup_db):
    single = await _lookup("Psalm 40:6")
    assert "Textual variant catalogued for this verse (LXX_quoted_in_NT)" in single
    assert "`get_textual_variant` (reference='Psalm 40:6')" in single

    passage = await _lookup("Psalm 40:5-8")
    assert "Textual variants catalogued in this passage: Psalm 40:6 (LXX_quoted_in_NT)" in passage
    assert "reference='Psalm 40:5-8'" not in passage

    assert "Textual variant" not in await _lookup("Psalm 40:7-8")


async def test_interpretive_cases_are_cued_apart_from_variants(lookup_db):
    single = await _lookup("Psalm 40:8")
    assert "Translation and interpretation notes catalogued for this verse" in single
    assert "Textual variant" not in single

    passage = await _lookup("Psalm 40:5-8")
    assert "Textual variants catalogued in this passage: Psalm 40:6 (LXX_quoted_in_NT)." in passage
    assert "catalogued in this passage: Psalm 40:8 (MT_preserved)." in passage
    assert "Psalm 40:8 (MT_preserved)" not in passage.split("Translation and interpretation")[0]


async def test_original_and_morphology_flags_apply_to_every_verse(lookup_db):
    plain = await _lookup("Luke 19:1-3", include_original=False)
    assert "### Original Text" not in plain
    assert "### Word Analysis" not in plain
    parsed = await _lookup("Luke 19:1-3", include_morphology=True)
    assert parsed.count("### Original Text") == 3
    assert parsed.count("[V-PAI-3S]") == 3


async def test_long_chapter_is_capped_with_continuation(lookup_db):
    output = await _lookup("Psalm 119")
    headings = _verse_headings(output)
    assert len(headings) == server.LOOKUP_VERSE_MAX_VERSES
    assert headings[-1] == f"Psa.119.{server.LOOKUP_VERSE_MAX_VERSES}"
    assert f"of 60 verses. Continue with reference='Psalm 119:{server.LOOKUP_VERSE_MAX_VERSES + 1}-60'" in output


async def test_range_past_chapter_end_is_clamped_with_note(lookup_db):
    output = await _lookup("Luke 19:47-60")
    assert _verse_headings(output) == ["Luk.19.47", "Luk.19.48"]
    assert "Luke 19 ends at verse 48" in output


@pytest.mark.parametrize(
    ("reference", "message"),
    [
        ("Luke 25", "Luke has no chapter 25 (chapters 19–20)."),
        ("Luke 19:60", "Luke 19 has no verse 60 (verses 1–48)."),
        ("Luke 19:5-3", "Invalid range 'Luke 19:5-3': the end comes before the start."),
        ("Nonsense 1:1", "Unknown book 'Nonsense'"),
        ("what is love", "Supported forms: a verse ('John 3:16'), a verse range"),
    ],
)
async def test_invalid_input_gets_a_clear_message(lookup_db, reference, message):
    output = await _lookup(reference)
    assert message in output
    assert not _verse_headings(output)


async def test_empty_verses_table_points_to_build_script(tmp_path, monkeypatch):
    db_path = tmp_path / "empty.db"
    conn = sqlite3.connect(db_path)
    create_schema(conn)
    conn.close()
    db = StudyBibleDB(db_path)
    await db.connect()
    monkeypatch.setattr(server, "db", db)
    try:
        output = await _lookup("John 3:16")
    finally:
        await db.close()
    assert "verses table is missing or empty" in output
    assert "scripts/build_database.py" in output


@pytest.mark.parametrize(
    ("reference", "expected"),
    [
        ("Jude 3", "Jude 1:3"),
        ("Jude 1", "Jude 1"),
        ("Obadiah 1", "Obadiah 1"),
        ("Philemon 4–6", "Philemon 1:4-6"),
        ("3 John 4", "3 John 1:4"),
        ("3John 4", "3John 1:4"),
        ("Obadiah 3", "Obadiah 1:3"),
        ("Jude", "Jude 1"),
        ("Jude 1:3", "Jude 1:3"),
        ("John 3", "John 3"),
        ("1 John 3", "1 John 3"),
        ("Psalm 82", "Psalm 82"),
    ],
)
def test_single_chapter_books_are_cited_by_verse(reference, expected):
    assert expand_single_chapter_reference(reference) == expected


async def test_single_chapter_citations_resolve_through_the_tool_boundary(lookup_db):
    async def call(reference):
        return (await server.call_tool("lookup_verse", {"reference": reference}))[0].text

    assert _verse_headings(await call("Jude 3")) == ["Jud.1.3"]
    assert _verse_headings(await call("Philemon 6")) == ["Phm.1.6"]
    assert _verse_headings(await call("3 John 4")) == ["3Jn.1.4"]
    assert _verse_headings(await call("Jude 3-5")) == ["Jud.1.3", "Jud.1.4", "Jud.1.5"]
    assert len(_verse_headings(await call("Jude"))) == 25
    # A lone "1" is the chapter, as chapter-level tools expect.
    assert len(_verse_headings(await call("Jude 1"))) == 25
    # Compact names resolve through the shared book-name resolver.
    assert _verse_headings(await call("3John 4")) == ["3Jn.1.4"]


async def test_passage_omits_word_list_unless_morphology_requested(lookup_db):
    passage = await _lookup("Luke 19:1-3")
    single = await _lookup("John 3:16")
    parsed = await _lookup("Luke 19:1-3", include_morphology=True)

    assert passage.count("### Original Text") == 3
    assert "### Word Analysis" not in passage
    assert "### Word Analysis" in single
    assert parsed.count("### Word Analysis") == 3


async def test_superscription_does_not_count_toward_the_cap(lookup_db):
    psalm_18 = await _lookup("Psalm 18", include_original=False)
    psalm_78 = await _lookup("Psalm 78", include_original=False)

    assert psalm_18.startswith("# Psalm 18\n")
    assert "Showing the first" not in psalm_18
    assert len(_verse_headings(psalm_18)) == 50  # plus the superscription
    assert psalm_78.startswith("# Psalm 78:1-50\n")
    assert "Showing the first 50 of 72 verses. Continue with reference='Psalm 78:51-72'" in psalm_78


async def test_psalm_superscription_is_labelled(lookup_db):
    output = await _lookup("Psalm 40:0-2", include_original=False)
    assert "## Psa.40 superscription (Hebrew Psa.40.1)" in output
    assert "Psa.40.0(40.1)" not in output
    assert _verse_headings(output) == ["Psa.40.1(40.2)", "Psa.40.2(40.3)"]
