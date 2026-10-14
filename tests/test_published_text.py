"""Published third-party text: Aquifer cleanup, correction notes, dictionary paging, ancient texts.

The Aquifer rows carry HTML excerpted from the real resources, with the
crudely stripped ``content_plain`` of databases built before this cleanup
(entities kept, headings run in), so each test shows the artefact as
published and as displayed.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import replace

import pytest

import study_bible_mcp.server as server
from study_bible_mcp.corpora import CORPORA, pseudepigrapha
from study_bible_mcp.database import StudyBibleDB, create_schema
from study_bible_mcp.parsers.ancient_sources import import_corpus
from study_bible_mcp.parsers.aquifer import strip_html
from study_bible_mcp.published_text import (
    MAX_CORRECTION_LENGTH,
    aquifer_text,
    aquifer_title,
    fix_ancient_row,
    load_corrections,
    render_aquifer_html,
    repair_uw_quote,
    safe_cut,
)
from study_bible_mcp.tools import (
    DICTIONARY_PAGE,
    _truncate,
    format_ancient_source_lookup,
    format_ancient_source_results,
)

# --- Aquifer fixture rows (content_id, resource_type, title, start_ref, end_ref, html)

ABRAHAM_HTML = (
    "<h1>ABRAHAM</h1><p>God called him from the city of Ur to become the leader of God&apos;s "
    "chosen people.</p><p>It was a test of faith because Abraham was 99 years old, and his wife "
    'Sarah was 90 years old and had no children (<a href="https://ref.ly/Gen11:30">Genesis 11:30</a>; '
    '<a href="https://ref.ly/Gen17:1-Gen17:4">17:1–4</a>, <a href="https://ref.ly/Gen17:17">17</a>).</p>'
    "<h2>Abraham’s Life</h2><p>Terah had three sons: </p><ul><li><p>Abram</p></li><li><p>Nahor</p>"
    "</li><li><p>Haran. </p></li></ul><p>Abram trusted God’s promise and left Haran at the age of 74. "
    "He went to Shechem in Canaan, between Mount&nbsp;Gerizim and Mount Ebal.</p>"
)

HIGH_PRIEST_HTML = (
    "<p>One of the priests was named the <strong>high priest</strong>. On this day, the high priest "
    "offered a sacrifice. This means something like &quot;the great day of forgiveness.&quot; The high "
    "priest killed a lamb, and took the blood inside the temple. The furthest part of the temple was "
    "called the most holy place.</p><h3>Audio Content</h3>"
)


def _covenant_html() -> str:
    """A long article shaped like Tyndale's 'Covenant': a preview list, then sections."""
    sections = [
        (2, "The Meaning of Covenant"), (2, "Human Covenants"), (2, "Divine-Human Covenants"),
        (3, "Adam"), (3, "Noah"), (2, "The Sinai Covenant"), (3, "The Covenant Law"),
        (2, "The New Covenant Predicted in the Old Testament"),
    ]
    preview = "".join(
        f'<p>•&nbsp;<a target="_blank">{name}</a></p>' for level, name in sections if level == 2
    )
    body = "".join(
        f"<h{level}>{name}</h{level}>"
        + "".join(f"<p>{name} paragraph {n}: " + "covenant words " * 40 + "end.</p>" for n in range(3))
        for level, name in sections
    )
    return f"<h1>COVENANT</h1><p>Arrangement between two parties.</p><p>Preview</p>{preview}{body}"


AQUIFER_ROWS = [
    (11580, "study_notes", "Genesis 11:27–25.11", "01011027", "01025011",
     "<p>This is the account of Terah’s family: about Isaac, the child of promise.</p>"),
    (22001, "study_notes", "Song of Solomon 2:1–2", "22002001", "22002002",
     "<ul><li><p><em>a lily of the valley</em>: The Hebrew text shows the woman&apos;s modesty "
     "&amp; humility. </p></li><li><p>The man agrees with her comparison.</p></li></ul>"),
    (90003, "translation_notes_uw", "Genesis 22:6 (#3)", "01022006", "01022006",
     "<p><strong>&quot;and he took in his hand{s&quot;</strong></p><p>Consider whether or not it is "
     "better to begin a new sentence here.</p>"),
    (90004, "translation_notes_uw", "Genesis 22:6 (#4)", "01022006", "01022006",
     "<p><span style='direction: rtl;'>אֶת־הָ⁠אֵ֖שׁ</span></p><p><strong>&quot;the fire {pot&quot;"
     "</strong></p><p>The <strong>fire</strong> can refer to hot coals.</p><p>See: "
     '<span data-bnType="resourceReference" data-resourceId="26707">Metonymy</span></p>'),
    (90006, "translation_notes_uw", "Genesis 22:6 (#6)", "01022006", "01022006",
     "<p><strong>&quot;Then the two of them went on together&quot;</strong></p><p>Some languages "
     "have a dual pronoun.</p><p>See:</p>"),
    (90101, "translation_notes_uw", "Song of Solomon 2:1 (#1)", "22002001", "22002001",
     "<p><strong>&quot;&quot;I {am} a flower of Sharon,&quot;</strong></p><p>The woman is speaking "
     "of herself.</p>"),
    (90102, "translation_notes_uw", "Song of Solomon 2:1 (#2)", "22002001", "22002001",
     "<p><span style='direction: rtl;'>חֲבַצֶּ֣לֶת</span></p><p><strong>&quot;am} a flower of&quot;"
     "</strong></p><p>The original word refers to a specific type of flower.</p>"),
    (90201, "translation_notes_sil", "Song of Solomon 2:1", "22002001", "22002001",
     "<p>She spoke of her humble life (1:5–6).</p><h4>2:1a</h4><p><strong>I am a rose of Sharon:"
     '</strong> <span data-bnType="footnote"><span>This verse was mistakenly thought to be spoken '
     "by the man.</span></span> The statement is a metaphor.</p>"),
    (3320, "dictionary", "Abraham", None, None, ABRAHAM_HTML),
    (4674, "dictionary", "Covenant", None, None, _covenant_html()),
    (4770, "dictionary", "Day of Atonement", None, None,
     "<h1>DAY OF ATONEMENT</h1><p><em>See</em> Atonement, Day of.</p>"),
    (3866, "dictionary", "Day of Atonement", None, None,
     "<h1>DAY OF ATONEMENT</h1>" + "<p>The high priest would sacrifice a young bull. </p>" * 120),
    (280074, "key_terms", "high priest", None, None, HIGH_PRIEST_HTML),
]


def _legacy_plain(html_: str) -> str:
    """``content_plain`` as databases built before this cleanup stored it."""
    return re.sub(r"<[^>]+>", "", html_)


def _build(path) -> None:
    conn = sqlite3.connect(path)
    create_schema(conn)
    for content_id, resource_type, title, start, end, html_ in AQUIFER_ROWS:
        book = {"01": "Gen", "22": "Sng"}.get((start or "")[:2])
        chapter = int(start[2:5]) if start else None
        conn.execute(
            """INSERT INTO aquifer_content (content_id, resource_type, title, book, start_ref, end_ref,
                   chapter_start, content, content_plain, is_range)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (content_id, resource_type, title, book, start, end, chapter, html_, _legacy_plain(html_),
             int(start != end)),
        )
    conn.commit()
    conn.close()


@pytest.fixture(scope="module")
def aquifer_file(tmp_path_factory):
    path = tmp_path_factory.mktemp("published_text") / "aquifer.db"
    _build(path)
    return path


@pytest.fixture
async def db(aquifer_file, monkeypatch):
    database = StudyBibleDB(aquifer_file)
    await database.connect()
    monkeypatch.setattr(server, "db", database)
    yield database
    await database.close()


async def call(tool: str, /, **arguments) -> str:
    response = await server.call_tool(tool, arguments)
    output = response[0].text
    assert not output.startswith("Error:"), output
    return output


# ---------------------------------------------------------------------------
# Entities, headings, lists, footnotes, titles
# ---------------------------------------------------------------------------


async def test_study_notes_unescape_entities_and_fix_range_titles(db):
    genesis = await call("get_study_notes", reference="Genesis 22:6")
    song = await call("get_study_notes", reference="Song of Solomon 2:1")

    assert "**Genesis 11:27–25:11**" in genesis and "25.11" not in genesis
    assert "- a lily of the valley: The Hebrew text shows the woman's modesty & humility." in song
    assert "- The man agrees" in song
    assert "&apos;" not in song and "&amp;" not in song


async def test_sil_headings_and_footnotes_do_not_run_into_the_text(db):
    song = await call("get_study_notes", reference="Song of Solomon 2:1")

    assert "(1:5–6).\n\n2:1a\n\nI am a rose of Sharon:" in song
    assert "Sharon: [Footnote: This verse was mistakenly thought to be spoken by the man.] The statement" in song


async def test_dictionary_headings_and_lists_get_their_own_lines(db):
    abraham = await call("get_bible_dictionary", topic="Abraham")
    covenant = await call("get_bible_dictionary", topic="Covenant")

    assert "17:1–4, 17).\n\nAbraham’s Life\n\nTerah had three sons:\n\n- Abram\n- Nahor\n- Haran." in abraham
    assert "God's chosen people" in abraham and "Mount Gerizim" in abraham
    assert "Preview\n\n• The Meaning of Covenant\n• Human Covenants\n" in covenant
    assert "• The New Covenant Predicted in the Old Testament\n\nThe Meaning of Covenant\n\n" in covenant
    assert "Old TestamentThe Meaning" not in covenant


async def test_key_terms_unescape_entities(db):
    output = await call("get_key_terms", term="high priest")

    assert 'something like "the great day of forgiveness."' in output and "&quot;" not in output


def test_titles_fix_only_tyndale_cross_chapter_ranges():
    assert aquifer_title({"resource_type": "study_notes", "title": "John 1:19–12.50"}) == "John 1:19–12:50"
    assert aquifer_title({"resource_type": "study_notes", "title": "Genesis 22:18–25.11"}) == "Genesis 22:18–25:11"
    assert aquifer_title({"resource_type": "study_notes", "title": "John 3:16"}) == "John 3:16"
    assert aquifer_title({"resource_type": "dictionary", "title": "Sarah #1"}) == "Sarah #1"


def test_the_importer_stores_the_displayed_plain_text():
    assert strip_html(ABRAHAM_HTML).startswith("ABRAHAM\n\nGod called him from the city of Ur to become the leader of God's")
    assert "17).\n\nAbraham’s Life\n\n" in strip_html(ABRAHAM_HTML)
    assert "Correction" not in strip_html(ABRAHAM_HTML)


def test_plain_text_fallback_without_html():
    item = {"resource_type": "key_terms", "content_plain": "God&apos;s  grace\n\n\n\nabounds"}

    assert aquifer_text(item) == "God's grace\n\nabounds"


# ---------------------------------------------------------------------------
# unfoldingWord quote lines
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("quote, expected", [
    ("and he took in his hand{s", "and he took in his hand{s}"),
    ("the fire {pot", "the fire {pot}"),
    ("am} a flower of", "{am} a flower of"),
    ('"I {am} a flower of Sharon,', "I {am} a flower of Sharon,"),
    ('"is} bone from my bones', "{is} bone from my bones"),
    ("because {she had said", "because {she had said}"),
    ("I have given} every green plant for food", "{I have given} every green plant for food"),
    ("Her ways {", "Her ways"),
    ("He (is} swift on the face of the waters", "He {is} swift on the face of the waters"),
    ("with God{, is there", "with God{, is there}"),
    ("bring {them & other {mortar", "bring {them} & other {mortar}"),
    ("was} over & was} over", "{was} over & {was} over"),
    ('"Make ready the way of the Lord; make his paths straight"', "Make ready the way of the Lord; make his paths straight"),
    ("Parosh: Zechariah\"", "Parosh: Zechariah"),
    ("and put {it} on Isaac his son", "and put {it} on Isaac his son"),
    ('saying,"Speak to the sons of Israel, saying', 'saying,"Speak to the sons of Israel, saying'),
])
def test_repair_uw_quote(quote, expected):
    assert repair_uw_quote(quote) == expected


async def test_uw_quote_lines_and_empty_see_lines(db):
    genesis = await call("get_study_notes", reference="Genesis 22:6")
    song = await call("get_study_notes", reference="Song of Solomon 2:1")

    assert '\n"and he took in his hand{s}"\n' in genesis
    assert '\n"the fire {pot}"\n' in genesis
    assert "See: Metonymy" in genesis
    assert not re.search(r"(?m)^See:\s*$", genesis)
    assert '\n"I {am} a flower of Sharon,"\n' in song and '""' not in song
    assert '\n"{am} a flower of"\n' in song


def test_uw_quote_pieces_joined_by_a_dash_are_each_repaired():
    text, _ = render_aquifer_html(
        "<p><strong>&quot;&quot;Shecaniah.&quot;</strong> - <strong>&quot;Parosh: Zechariah&quot;&quot;"
        "</strong></p><p><strong>&quot;And&quot;</strong> - <strong>&quot;was} twenty&quot;</strong></p>"
    )

    assert text == '"Shecaniah." - "Parosh: Zechariah"\n\n"And" - "{was} twenty"'


# ---------------------------------------------------------------------------
# Correction notes
# ---------------------------------------------------------------------------


def test_corrections_file_is_valid_and_short():
    data = load_corrections()

    assert {entry["title"] for entry in data["corrections"]} >= {"Abraham", "high priest"}
    for entry in data["corrections"]:
        assert len(entry["note"]) <= MAX_CORRECTION_LENGTH and "]" not in entry["note"]
    assert [entry["reference"] for entry in data["transcriptions"]] == ["4 Ezra 7:28"]


async def test_correction_notes_print_beside_the_error(db):
    abraham = await call("get_bible_dictionary", topic="Abraham")
    priest = await call("get_key_terms", term="high priest")

    assert (
        "left Haran at the age of 74. [⚠ Correction: Genesis 12:4 gives Abram's age on leaving Haran "
        "as 75" in abraham
    )
    assert "The high priest killed a lamb, and took the blood inside the temple. [⚠ Correction: " \
        "Leviticus 16 prescribes no lamb on the Day of Atonement: the high priest killed a bull" in priest
    # The publisher's sentence after the note is untouched.
    assert "] The furthest part of the temple was called the most holy place." in priest


def test_correction_needs_the_same_item_and_the_exact_text():
    sentence = "<p>Abram trusted God’s promise and left Haran at the age of 74. He went on.</p>"

    other_article = {"resource_type": "dictionary", "content_id": 9999, "title": "Haran", "content": sentence}
    revised = {"resource_type": "dictionary", "content_id": 3320, "title": "Abraham",
               "content": "<p>He left Haran at the age of 75.</p>"}

    assert "Correction" not in aquifer_text(other_article)
    assert "Correction" not in aquifer_text(revised)


def test_truncation_never_separates_a_correction_from_its_error():
    item = {"resource_type": "key_terms", "content_id": 280074, "title": "high priest", "content": HIGH_PRIEST_HTML}
    text = aquifer_text(item)
    inside_the_error = text.index("killed a lamb") + 3

    truncated = _truncate(text, inside_the_error, "\n*[cut]*")

    assert re.search(r"Heb 9:7, 12\)\. 'The lamb' later in this paragraph has the same slip\.\]\n\*\[cut\]\*$", truncated)
    assert safe_cut(text, 10) == 10
    assert _truncate("short", 100) == "short"


async def test_a_dictionary_page_boundary_keeps_the_correction(db, monkeypatch):
    # One long paragraph puts the page's last word break inside the corrected sentence.
    words = (DICTIONARY_PAGE - 12 - len("and ")) // len("word ")
    content = "<p>" + "word " * words + "and left Haran at the age of 74. He went on.</p>"
    monkeypatch.setattr(server.db, "get_bible_dictionary", _rows_with_html(3320, "Abraham", content))

    output = await call("get_bible_dictionary", topic="Abraham")

    assert output.index("left Haran") < 15 + DICTIONARY_PAGE < output.index("[⚠ Correction: ")
    assert re.search(r"implies\)\.\]\n\n\*\[Truncated — 12 more characters\. .* offset=\d+\.\]\*", output)


def _rows_with_html(content_id, title, content):
    async def fetch(topic):
        return [{"resource_type": "dictionary", "content_id": content_id, "title": title,
                 "content": content, "content_plain": _legacy_plain(content)}]
    return fetch


# ---------------------------------------------------------------------------
# Dictionary paging
# ---------------------------------------------------------------------------


async def test_a_long_article_ends_with_where_to_read_on(db):
    output = await call("get_bible_dictionary", topic="Covenant")

    pointer = re.search(
        r'\*\[Truncated — ([\d,]+) more characters\. Call get_bible_dictionary again with '
        r'topic="Covenant" and offset=(\d+), or section= one of: ([^\]]+)\.\]\*$', output.rstrip()
    )
    assert pointer, output[-400:]
    assert len(output) < DICTIONARY_PAGE + 600
    assert "The Sinai Covenant" in pointer.group(3)


async def test_offsets_page_through_the_whole_article(db):
    full = aquifer_text({"resource_type": "dictionary", "content_id": 4674, "content": _covenant_html()})
    pages, offset = [], 0
    while True:
        output = await call("get_bible_dictionary", topic="Covenant", offset=offset)
        body = output.split("\n\n", 1)[1]
        if offset:
            assert body.startswith(f"*[From character {offset:,} of {len(full):,}.]*")
            body = body.split("\n\n", 1)[1]
        pointer = re.search(r"offset=(\d+)", body)
        pages.append(body[: body.index("\n\n*[Truncated")] if pointer else body)
        if not pointer:
            break
        offset = int(pointer.group(1))

    assert len(pages) > 2
    assert re.sub(r"\s+", " ", " ".join(pages)).strip() == re.sub(r"\s+", " ", full)


async def test_a_section_by_heading(db):
    sinai = await call("get_bible_dictionary", topic="covenant", section="sinai covenant")
    adam = await call("get_bible_dictionary", topic="covenant", section="ADAM")

    assert "\n\nThe Sinai Covenant\n\nThe Sinai Covenant paragraph 0" in sinai
    # A level-2 section takes its subsections and stops at the next level-2 heading.
    assert "The Covenant Law paragraph 2" in sinai and "The New Covenant Predicted" not in sinai.split("*[End")[0]
    assert '*[End of section "The Sinai Covenant";' in sinai
    assert "section= one of: The New Covenant Predicted in the Old Testament.]*" in sinai
    assert "Adam paragraph 2" in adam and "Noah paragraph" not in adam.split("*[End")[0]


async def test_unknown_section_and_offset_past_the_end(db):
    missing = await call("get_bible_dictionary", topic="Covenant", section="Melchizedek")
    past = await call("get_bible_dictionary", topic="Abraham", offset=99999)
    bad = await call("get_bible_dictionary", topic="Abraham", offset="ten")

    assert '*[No section matching "Melchizedek". Sections: The Meaning of Covenant; Human Covenants;' in missing
    assert "*[Offset 99,999 is past the end of this article" in past
    assert bad.startswith("offset must be a whole number")


async def test_paging_skips_a_same_title_stub(db):
    output = await call("get_bible_dictionary", topic="Day of Atonement", offset=DICTIONARY_PAGE)

    assert output.count("## Day of Atonement") == 1 and "young bull" in output
    assert "past the end" not in output


# ---------------------------------------------------------------------------
# Ancient sources
# ---------------------------------------------------------------------------


def _ezra_row(**overrides) -> dict:
    row = {
        "corpus": "pseudepigrapha", "author": "Anonymous (attributed to Ezra)", "work_key": "4_ezra",
        "reference": "4 Ezra 7:28", "alternate_reference": "KJV 2 Esdras 7:28",
        "sort_start": 7028, "sort_end": 7028,
        "text": "For my son Jesus shall be revealed with those that be with him.",
        "original_text": "Revelabitur enim filius meus Jesus cum bis qui cum eo sunt.",
        "original_language": "Latin", "edition": "Vulgata Clementina", "translation": "KJV",
        "license": "Latin text: CC BY-SA 4.0; English translation: Public domain",
        "source_url": "https://ebible.org/find/show.php?id=eng-kjv",
    }
    return {**row, **overrides}


def test_4_ezra_7_28_reads_cum_his_when_shown():
    output = format_ancient_source_lookup("4 Ezra 7:28", "resolved", [_ezra_row()], 1)

    assert "**Latin:** Revelabitur enim filius meus Jesus cum his qui cum eo sunt." in output
    assert "cum bis" not in output


def test_transcription_fixes_touch_only_the_listed_passage():
    other_verse = _ezra_row(reference="4 Ezra 7:29")
    already_fixed = _ezra_row(original_text="cum his qui")

    assert fix_ancient_row(other_verse) is other_verse
    assert fix_ancient_row(already_fixed) is already_fixed
    assert fix_ancient_row(_ezra_row())["text"] == _ezra_row()["text"]


def test_import_fixes_the_transcription_slip(tmp_path, monkeypatch):
    usfm = "\\id 2ES\n\\c 7\n" + "".join(f"\\p\n\\v {verse} English {verse}.\n" for verse in range(1, 29))
    latin = "==Caput 7==\n" + " ".join(
        f"<sup>{verse}</sup> " + ("Revelabitur enim filius meus Jesus cum bis qui cum eo sunt." if verse == 28
                                  else f"Latina {verse}.")
        for verse in range(1, 29)
    )
    (tmp_path / pseudepigrapha.KJV_FILE).write_text(usfm, encoding="utf-8")
    (tmp_path / pseudepigrapha.LATIN_FILE).write_text(latin, encoding="utf-8")
    monkeypatch.setattr(pseudepigrapha, "EZRA_CHAPTERS", (7,))
    monkeypatch.setattr(pseudepigrapha, "_EZRA_ALIGNED_SPANS", ())
    monkeypatch.setattr(pseudepigrapha, "_BIBLICAL_LINKS", ())
    monkeypatch.setitem(CORPORA, "pseudepigrapha", replace(
        CORPORA["pseudepigrapha"], parse=pseudepigrapha.parse_ezra, require_files=lambda directory: None
    ))
    conn = sqlite3.connect(tmp_path / "p.db")
    create_schema(conn)

    import_corpus(conn, "pseudepigrapha", tmp_path)

    (latin_28,) = conn.execute(
        "SELECT original_text FROM ancient_source_passages WHERE reference = '4 Ezra 7:28'"
    ).fetchone()
    assert latin_28 == "Revelabitur enim filius meus Jesus cum his qui cum eo sunt."


def _bilingual_row(english_word: str = "", hebrew_word: str = "") -> dict:
    """Forty sentences each way, sentence 25 holding the given word."""
    english = " ".join(
        f"Sentence {n} of the English translation, with enough words to be long{' ' + english_word if n == 25 else ''}."
        for n in range(1, 41)
    )
    hebrew = " ".join(
        f"משפט {n} בלשון הקודש ועוד מילים כאן{' ' + hebrew_word if n == 25 else ''}." for n in range(1, 41)
    )
    return {
        "corpus": "rabbinic", "author": "Mishnah", "work_key": "mishnah_sotah",
        "reference": "Mishnah Sotah 9:15", "sort_start": 9015, "sort_end": 9015,
        "text": english, "original_text": hebrew, "original_language": "Hebrew",
        "edition": "Mishnah, ed. Romm, Vilna 1913", "translation": "Mishnah Yomit by Dr. Joshua Kulp",
        "license": "Hebrew text: Public domain; English translation: CC BY 3.0",
        "source_url": "https://github.com/Sefaria",
    }


def _excerpts(output: str) -> tuple[str, str]:
    english = output.split("tier B · ", 1)[1].split("\n\n", 2)[1]
    hebrew = output.split("**Hebrew:** ", 1)[1].split("\n", 1)[0]
    return english, hebrew


def test_an_english_match_aligns_the_hebrew_excerpt():
    row = _bilingual_row(english_word="Temple")

    english, hebrew = _excerpts(format_ancient_source_results("Temple", [row], "rabbinic"))

    assert "Temple" in english and english.startswith("…")
    # The Hebrew excerpt covers the same stretch, not the passage's opening.
    assert "משפט 25 " in hebrew and hebrew.startswith("…משפט ")
    assert "משפט 1 " not in hebrew


def test_a_hebrew_match_aligns_the_english_excerpt():
    row = _bilingual_row(hebrew_word="מקדש")

    english, hebrew = _excerpts(format_ancient_source_results("מקדש", [row], "rabbinic"))

    assert "מקדש" in hebrew
    assert "Sentence 1 " not in english and english.startswith("…Sentence ")
