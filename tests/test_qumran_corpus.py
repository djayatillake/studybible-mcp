"""Qumran corpus: ETCBC/dss Text-Fabric parsing (CD, 1QS, 1QSa, 1QpHab), import, lookup."""

import sqlite3
from pathlib import Path

import pytest

from study_bible_mcp import server
from study_bible_mcp.corpora import CORPORA, qumran, resolve_citation
from study_bible_mcp.corpora.locators import COLUMN_LINE
from study_bible_mcp.database import StudyBibleDB, create_schema
from study_bible_mcp.parsers.ancient_sources import import_corpus

LICENSE_LINE = qumran.ETCBC_LICENSE_DECLARATION

# --- Text-Fabric fixture -----------------------------------------------------
#
# Each scroll line is written in a small notation: Hebrew letters are signs,
# ' ' ends a word, '/' is Abegg's morpheme break, '.' the transcription's
# sof pasuq, '?' flags the previous letter as uncertain, '[ ]' a modern
# reconstruction, '{{ }}' a scribal erasure, '^ ^' a supralinear correction,
# 'V' a vacat, '_' an empty sign, '-' a missing sign, '#' an unidentified sign.

_TOGGLES = {"[": ("rec", "1"), "{{": ("rem", "2"), "^": ("cor", "3")}
_CLOSERS = {"]": "[", "}}": "{{"}


def _signs(notation: str) -> list[dict]:
    signs: list[dict] = []
    active: dict[str, str] = {}
    position = 0
    while position < len(notation):
        token = notation[position:position + 2] if notation[position:position + 2] in ("{{", "}}") else notation[position]
        position += len(token)
        if token in _TOGGLES:
            feature, value = _TOGGLES[token]
            if token == "^" and feature in active:
                del active[feature]
            else:
                active[feature] = value
        elif token in _CLOSERS:
            del active[_TOGGLES[_CLOSERS[token]][0]]
        elif token == " ":
            signs[-1]["after"] = " "
        elif token == "?":
            signs[-1]["unc"] = "1"
        else:
            kind, glyph = {
                "/": ("sep", "׳"), ".": ("punct", "׃"), "V": ("empty", ""),
                "_": ("empty", ""), "-": ("missing", "ε"), "#": ("unc", " # "),
            }.get(token, ("cons", token))
            sign = {"type": kind, "glyph": glyph, **active}
            if token == "V":
                sign["vac"] = "1"
            signs.append(sign)
    return signs


def _write_tf(directory: Path, name: str, values: dict[int, str], kind: str = "@node") -> None:
    lines = [kind, "@valueType=str", LICENSE_LINE, "@writtenBy=test", ""]
    previous = 0
    for node in sorted(values):
        lines.append(values[node] if node == previous + 1 else f"{node}\t{values[node]}")
        previous = node
    (directory / name).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _cd_column_6() -> list[str]:
    lines = [f"שורה {'א' * number}" for number in range(1, 11)]
    return [*lines, "יורה הצדק באחרית הימים . V וכל אשר הובאו בברית"]


ETCBC_LINES = (
    ("CD", "1", ["V ועתה שמעו כל יודעי צדק ובינו במעשי", "אל . כי ריב ל/ו עם כל בשר"]),
    ("CD", "6", _cd_column_6()),
    ("CD", "19", ["ו/הם ישמרו ענ?ו?ה? {{נפ##}} נפתח"]),
    ("1QS", "1", ["ל[-]שים לחי/ו [ספר ס]ר?ך היחד . לדרוש"]),
    ("1QSb", "f9", ["[ברוך]"]),
    ("1QSa", "1", ["ו/זה הסרך לכול עדת ישראל ^ה^ _ [_]"]),
    # A vacat sign written with no space either side ('V' between '.]' and a
    # letter) must not glue 'vacat' to the text around it.
    ("1QpHab", "1", ["[עד אנה יהוה] ש?ועתי ולוא", "[ושוד וחמס .]Vיג[די]לו ריב"]),
    ("1QpHab", "2", [
        "יסופר . V [פשר הדבר על] ה?בוגדים עם איש",
        "להם ברזי ערמתו . הנה עופלה לוא יושרה",
        "[נפשו בו] . V פשרו",
    ]),
)


def _write_etcbc(directory: Path, lines=ETCBC_LINES) -> None:
    features: dict[str, dict[int, str]] = {
        name: {} for name in ("type", "glyph", "after", "rec", "rem", "cor", "alt", "vac", "unc")
    }
    slot = 0
    spans = []
    for scroll, column, column_lines in lines:
        for number, notation in enumerate(column_lines, 1):
            first = slot + 1
            for sign in _signs(notation):
                slot += 1
                for feature, value in sign.items():
                    features[feature][slot] = value
            spans.append((scroll, column, str(number), first, slot))
    line_first = slot + 1
    line_last = slot + len(spans)
    otype = [f"1-{slot}\tsign", f"{line_first}-{line_last}\tline"]
    (directory / "otype.tf").write_text(
        "\n".join(["@node", LICENSE_LINE, "", *otype]) + "\n", encoding="utf-8"
    )
    for name, values in features.items():
        _write_tf(directory, f"{name}.tf", values)
    nodes = range(line_first, line_last + 1)
    _write_tf(directory, "scroll.tf", {node: span[0] for node, span in zip(nodes, spans)})
    _write_tf(directory, "fragment.tf", {node: span[1] for node, span in zip(nodes, spans)})
    _write_tf(directory, "line.tf", {node: span[2] for node, span in zip(nodes, spans)})
    _write_tf(
        directory, "oslots.tf",
        {node: f"{span[3]}-{span[4]}" for node, span in zip(nodes, spans)}, kind="@edge",
    )


FIXTURE_LINKS = (
    ("1:2", "ריב", 1, 3, 1, 3, " (lemma mostly restored)"),
    ("2:2", "הנה עופלה לוא יושרה", 2, 4, 2, 4, "a (end of 2:4a restored; 2:4b wholly reconstructed)"),
)


def _write_corpus(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    _write_etcbc(directory)
    return directory


def _by_reference(rows: list[dict]) -> dict[str, dict]:
    return {row["reference"]: row for row in rows}


# --- Parsing -------------------------------------------------------------------


def test_tf_reader_follows_implicit_explicit_range_and_list_specs(tmp_path):
    path = tmp_path / "f.tf"
    path.write_text(
        "\n".join(["@node", LICENSE_LINE, "", "a", "b", "5\tc", "7-8\td", "10,12\te", "f", "99\tg"])
        + "\n",
        encoding="utf-8",
    )

    assert qumran._tf_feature(path, 1, 13) == {
        1: "a", 2: "b", 5: "c", 7: "d", 8: "d", 10: "e", 12: "e", 13: "f",
    }
    assert qumran._tf_feature(path, 6, 8) == {7: "d", 8: "d"}


def test_tf_reader_requires_the_nc_licence_and_increasing_nodes(tmp_path):
    unlicensed = tmp_path / "unlicensed.tf"
    unlicensed.write_text("@node\n@license=Other\n\nvalue\n", encoding="utf-8")
    backwards = tmp_path / "backwards.tf"
    backwards.write_text(f"@node\n{LICENSE_LINE}\n\n5\ta\n3\tb\n", encoding="utf-8")

    with pytest.raises(ValueError, match="CC BY-NC 4.0"):
        qumran._tf_feature(unlicensed, 1, 10)
    with pytest.raises(ValueError, match="does not follow"):
        qumran._tf_feature(backwards, 1, 10)


def test_etcbc_columns_render_lines_with_brackets_and_marks(tmp_path):
    rows = _by_reference(qumran.parse_etcbc(_write_corpus(tmp_path)))

    assert list(rows) == [
        "CD 1:1–2", "CD 6:1–11", "CD 19:1", "1QS 1:1", "1QSa 1:1", "1QpHab 1:1–2", "1QpHab 2:1–3",
    ]
    cd1 = rows["CD 1:1–2"]
    assert cd1["original_text"] == (
        "1 vacat ועתה שמעו כל יודעי צדק ובינו במעשי\n2 אל ׃ כי ריב לו עם כל בשר"
    )
    assert (cd1["sort_start"], cd1["sort_end"]) == (COLUMN_LINE.key(1, 1), COLUMN_LINE.key(1, 2))
    assert cd1["alternate_reference"] == "CD-A 1:1–2"
    assert cd1["author"] == "Damascus Document"
    cd19 = rows["CD 19:1"]
    assert cd19["alternate_reference"] == "CD-B 19:1"
    assert (cd19["sort_start"], cd19["sort_end"]) == (19001, 19001)
    # Uncertain letters carry a circlet; the morpheme break is dropped; an empty
    # erasure keeps its brackets; an unidentified sign is a white circle.
    assert cd19["original_text"] == "1 והם ישמרו ענ\u05afו\u05afה\u05af {{נפ◦◦}} נפתח"
    assert rows["1QS 1:1"]["original_text"] == "1 ל[…]שים לחיו [ספר ס]ר\u05afך היחד ׃ לדרוש"
    assert rows["1QS 1:1"]["alternate_reference"] is None
    assert rows["1QSa 1:1"]["original_text"] == "1 וזה הסרך לכול עדת ישראל ^ה^ [ ]"
    assert "1QSb" not in " ".join(rows)


def test_etcbc_passages_are_original_only_with_the_nc_licence(tmp_path):
    for row in qumran.parse_etcbc(_write_corpus(tmp_path)):
        assert not {"text", "translation", "translation_license"} & set(row)
        assert row["original_license"] == row["license"] == "CC BY-NC 4.0"
        assert row["original_language"] == "Hebrew"
        assert row["source_url"] == qumran.ETCBC_SOURCE_URL
        assert qumran.ETCBC_COMMIT in row["source_url"]
        assert row["edition"] == qumran.ETCBC_EDITION
        expected = "second_temple,hasmonean" + (
            ",roman" if row["work_key"] == "pesher_habakkuk" else ""
        )
        assert row["period_tags"] == expected


def test_pesher_habakkuk_comes_from_etcbc_with_a_spaced_vacat(tmp_path):
    rows = _by_reference(qumran.parse(_write_corpus(tmp_path)))

    assert rows["1QpHab 1:1–2"]["original_text"] == (
        "1 [עד אנה יהוה] ש\u05afועתי ולוא\n2 [ושוד וחמס ׃] vacat יג[די]לו ריב"
    )
    assert rows["1QpHab 2:1–3"]["original_text"].splitlines()[0] == (
        "1 יסופר ׃ vacat [פשר הדבר על] ה\u05afבוגדים עם איש"
    )
    assert rows["1QpHab 2:1–3"]["author"] == "Pesher Habakkuk"
    assert not hasattr(qumran, "WIKISOURCE_FILE") and not hasattr(qumran, "parse_pesher_habakkuk")
    assert qumran.REQUIRED_FILES == qumran.ETCBC_FILES


def test_damascus_document_tag_names_each_genizah_manuscript_and_its_date():
    corpus = CORPORA["qumran"]

    assert corpus.tag_line("damascus_document", COLUMN_LINE.key(6, 1)).endswith(
        "· copy: Cairo Genizah MS A, 10th c. AD"
    )
    assert corpus.tag_line("damascus_document", COLUMN_LINE.key(19, 1)).endswith(
        "· copy: Cairo Genizah MS B, 11th–12th c. AD"
    )
    assert "Genizah" not in corpus.tag_line("community_rule", COLUMN_LINE.key(3, 1))
    assert "Wikisource" not in corpus.tag_line("pesher_habakkuk", COLUMN_LINE.key(7, 1))
    assert "no English translation included" in corpus.summary
    assert "openly licensed" not in corpus.summary



def test_etcbc_rejects_gaps_unknown_signs_and_missing_scrolls(tmp_path):
    gap = tmp_path / "gap"
    gap.mkdir()
    _write_etcbc(gap, (*ETCBC_LINES, ("CD", "7", ["א"])))
    (gap / "line.tf").write_text(
        (gap / "line.tf").read_text(encoding="utf-8").rstrip("\n").rsplit("\n", 1)[0] + "\n3\n",
        encoding="utf-8",
    )
    missing = tmp_path / "missing"
    missing.mkdir()
    _write_etcbc(missing, [entry for entry in ETCBC_LINES if entry[0] != "1QSa"])
    unknown = tmp_path / "unknown"
    unknown.mkdir()
    _write_etcbc(unknown)
    (unknown / "type.tf").write_text(
        (unknown / "type.tf").read_text(encoding="utf-8").replace("\ncons\n", "\nglyphoid\n", 1),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="not numbered"):
        qumran.parse_etcbc(gap)
    with pytest.raises(ValueError, match="1QSa"):
        qumran.parse_etcbc(missing)
    with pytest.raises(ValueError, match="Unknown ETCBC sign type"):
        qumran.parse_etcbc(unknown)


def test_require_files_names_every_missing_file(tmp_path):
    directory = _write_corpus(tmp_path)
    (directory / "oslots.tf").unlink()
    (directory / "vac.tf").unlink()

    with pytest.raises(FileNotFoundError) as error:
        qumran.require_qumran_files(directory)
    assert "oslots.tf, vac.tf" in str(error.value)


def test_download_licence_check_reads_the_header():
    qumran._require_license_declaration("glyph.tf", f"@node\r\n{LICENSE_LINE}\r\n\r\nא\r\n".encode())
    with pytest.raises(RuntimeError, match="CC BY-NC 4.0"):
        qumran._require_license_declaration("glyph.tf", f"@node\n\n{LICENSE_LINE}\n".encode())


# --- Curated links -------------------------------------------------------------


def test_curated_links_are_well_formed_habakkuk_lemmas():
    seen = set()
    for locator, quoted, c1, v1, c2, v2, suffix in qumran._BIBLICAL_LINKS:
        assert COLUMN_LINE.parse(locator) is not None
        assert quoted.strip() and "[" not in quoted and "]" not in quoted
        assert 1 <= c1 <= c2 <= 2 and (c1, v1) <= (c2, v2)
        assert suffix == "" or suffix.startswith((" (", "a (", "b ("))
        assert (locator, c1, v1) not in seen
        seen.add((locator, c1, v1))
    # 1QpHab 7:14 keeps four words of Hab 2:4a; the rest of the lemma is restored.
    assert ("7:14", "הנה עופלה לוא יושרה", 2, 4, 2, 4,
            "a (end of 2:4a restored; 2:4b wholly reconstructed)") in qumran._BIBLICAL_LINKS


def test_links_check_the_quoted_lemma_on_its_line(tmp_path, monkeypatch):
    rows = qumran.parse(_write_corpus(tmp_path))
    monkeypatch.setattr(qumran, "_BIBLICAL_LINKS", FIXTURE_LINKS)

    links = qumran.biblical_links(rows)

    assert [(link.locator, link.book, link.chapter, link.verse, link.note) for link in links] == [
        ("1:2", "Hab", 1, 3, "Quotes and interprets: Hab 1:3 (lemma mostly restored)"),
        ("2:2", "Hab", 2, 4,
         "Quotes and interprets: Hab 2:4a (end of 2:4a restored; 2:4b wholly reconstructed)"),
    ]
    monkeypatch.setattr(qumran, "_BIBLICAL_LINKS", (("2:1", "הנה עופלה", 2, 4, 2, 4, ""),))
    with pytest.raises(ValueError, match="does not contain the quoted lemma"):
        qumran.biblical_links(rows)


@pytest.mark.parametrize("anchor", [
    "עד אנה יהוה",  # wholly inside the reconstruction on 1:1
    "יהוה שועתי",  # straddles the closing bracket
    "יגדילו",  # letters restored inside the word
])
def test_links_reject_an_anchor_in_the_editors_reconstruction(tmp_path, monkeypatch, anchor):
    rows = qumran.parse(_write_corpus(tmp_path))
    line = "1:2" if anchor == "יגדילו" else "1:1"
    monkeypatch.setattr(qumran, "_BIBLICAL_LINKS", ((line, anchor, 1, 2, 1, 2, ""),))

    with pytest.raises(ValueError, match="reconstruction"):
        qumran.biblical_links(rows)
    monkeypatch.setattr(qumran, "_BIBLICAL_LINKS", ((line, f"[{anchor}]", 1, 2, 1, 2, ""),))
    with pytest.raises(ValueError, match="reconstruction brackets"):
        qumran.biblical_links(rows)


def test_surviving_text_marks_reconstruction_and_drops_signs():
    assert qumran.surviving_text("[עד אנה] ש\u05afועתי ^ה^ {{א}} vacat יג[די]לו") == (
        "| שועתי ה יג | לו"
    )


def test_note_renders_verse_spans(tmp_path, monkeypatch):
    rows = qumran.parse(_write_corpus(tmp_path))
    monkeypatch.setattr(qumran, "_BIBLICAL_LINKS", (
        ("2:2", "עופלה", 2, 4, 2, 6, ""),
        ("2:2", "יושרה", 1, 17, 2, 1, ""),
    ))

    notes = [link.note for link in qumran.biblical_links(rows)]

    assert notes == ["Quotes and interprets: Hab 2:4–6", "Quotes and interprets: Hab 1:17–2:1"]


# --- Import and tools ----------------------------------------------------------


def _build_db(tmp_path: Path, monkeypatch, links=FIXTURE_LINKS) -> Path:
    monkeypatch.setattr(qumran, "_BIBLICAL_LINKS", links)
    db_path = tmp_path / "qumran.db"
    conn = sqlite3.connect(db_path)
    create_schema(conn)
    import_corpus(conn, "qumran", _write_corpus(tmp_path / "qumran"))
    conn.close()
    return db_path


def _counts(db_path: Path) -> tuple[int, int]:
    conn = sqlite3.connect(db_path)
    try:
        passages = conn.execute(
            "SELECT COUNT(*) FROM ancient_source_passages WHERE corpus = 'qumran'"
        ).fetchone()[0]
        links = conn.execute("SELECT COUNT(*) FROM ancient_source_biblical_links").fetchone()[0]
    finally:
        conn.close()
    return passages, links


def test_import_counts_links_and_is_idempotent(tmp_path, monkeypatch):
    db_path = _build_db(tmp_path, monkeypatch)
    first = _counts(db_path)
    conn = sqlite3.connect(db_path)
    again = import_corpus(conn, "qumran", tmp_path / "qumran")
    linked = conn.execute(
        "SELECT p.reference, l.biblical_book, l.sort_start FROM ancient_source_biblical_links l "
        "JOIN ancient_source_passages p ON p.id = l.passage_id ORDER BY l.sort_start"
    ).fetchall()
    conn.close()

    assert first == (7, 2)
    assert again == 7 and _counts(db_path) == first
    assert linked == [("1QpHab 1:1–2", "Hab", 1003), ("1QpHab 2:1–3", "Hab", 2004)]


def test_import_fails_on_an_unresolved_link_and_keeps_the_previous_import(tmp_path, monkeypatch):
    db_path = _build_db(tmp_path, monkeypatch)
    monkeypatch.setattr(qumran, "_BIBLICAL_LINKS", (("9:1", "פשרו", 2, 4, 2, 4, ""),))
    conn = sqlite3.connect(db_path)

    with pytest.raises(ValueError, match="1QpHab 9:1"):
        import_corpus(conn, "qumran", tmp_path / "qumran")
    conn.close()
    assert _counts(db_path) == (7, 2)


@pytest.mark.parametrize("citation, expected", [
    ("CD 6:11", ("damascus_document", (6011, 6011))),
    ("CD VI, 11", ("damascus_document", (6011, 6011))),
    ("Damascus Document 1:1", ("damascus_document", (1001, 1001))),
    ("CD 19:10", ("damascus_document", (19010, 19010))),
    ("Zadokite Fragments 6:11-7:2", ("damascus_document", (6011, 7002))),
    ("Qumran CD 6", ("damascus_document", (6000, 6999))),
    ("1QS 3:13", ("community_rule", (3013, 3013))),
    ("Community Rule III 13-15", ("community_rule", (3013, 3015))),
    ("1QSa 2:11", ("rule_of_the_congregation", (2011, 2011))),
    ("1Q28a 2:11", ("rule_of_the_congregation", (2011, 2011))),
    ("1QpHab 2:1", ("pesher_habakkuk", (2001, 2001))),
    ("Pesher Habakkuk 7:4", ("pesher_habakkuk", (7004, 7004))),
    ("Dead Sea Scrolls, 1QpHab VII 1-5", ("pesher_habakkuk", (7001, 7005))),
])
def test_resolves_qumran_citations(citation, expected):
    resolution = resolve_citation(citation, CORPORA.values())

    assert resolution.status == "ok", resolution
    assert resolution.match.corpus.key == "qumran"
    assert (resolution.match.work.key, resolution.match.sort_range) == expected


def test_example_citation_and_query_belong_to_the_corpus():
    corpus = CORPORA["qumran"]
    resolution = resolve_citation(corpus.example_citation, CORPORA.values())

    assert resolution.status == "ok" and resolution.match.corpus is corpus
    assert [work.key for work in corpus.works] == [
        "damascus_document", "community_rule", "rule_of_the_congregation", "pesher_habakkuk",
    ]


async def _call(path: Path, monkeypatch, handler, **args) -> str:
    database = StudyBibleDB(path)
    await database.connect()
    monkeypatch.setattr(server, "db", database)
    try:
        return (await handler(args))[0].text
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_lookup_returns_the_column_with_licence_and_original_only_note(tmp_path, monkeypatch):
    db_path = _build_db(tmp_path, monkeypatch)
    lookup = server.handle_lookup_ancient_source

    cd = await _call(db_path, monkeypatch, lookup, citation="CD 6:11")
    middle = await _call(db_path, monkeypatch, lookup, citation="CD 6:5")
    column = await _call(db_path, monkeypatch, lookup, citation="CD 6")
    first = await _call(db_path, monkeypatch, lookup, citation="Damascus Document 1:1")
    pesher = await _call(db_path, monkeypatch, lookup, citation="1QpHab 2:1")
    missing_line = await _call(db_path, monkeypatch, lookup, citation="CD 6:30")

    assert "### Damascus Document, CD 6:1–11 (CD-A 6:1–11)" in cd
    assert "*Not Scripture · Qumran sectarian rule (composed 2nd–1st c. BC) · tier A ·" in cd
    assert "copy: Cairo Genizah MS A, 10th c. AD*" in cd
    assert "[ ] marks modern reconstruction, never evidence" in cd
    assert "11 יורה הצדק באחרית הימים ׃ vacat וכל אשר הובאו בברית" in cd
    assert "*No English translation included; Hebrew only.*" in cd
    assert "License: CC BY-NC 4.0 (non-commercial; https://creativecommons.org/licenses/by-nc/4.0/)." in cd
    # A line citation shows the cited line ±2, not the whole column.
    assert "*Lines 6:9–11 shown (the cited line ±2); cite the column for all of it.*" in cd
    assert "9 שורה " in cd and "8 שורה " not in cd
    assert "3 שורה " in middle and "7 שורה " in middle
    assert "2 שורה " not in middle and "8 שורה " not in middle
    assert "1 שורה " in column and "Lines " not in column
    assert "1 vacat ועתה שמעו כל יודעי צדק" in first
    assert "### Pesher Habakkuk, 1QpHab 2:1–3" in pesher
    assert "License: CC BY-NC 4.0 (non-commercial;" in pesher and "CC BY-SA" not in pesher
    assert (
        "- Echo: Hab 2:4 — Quotes and interprets: Hab 2:4a "
        "(end of 2:4a restored; 2:4b wholly reconstructed)"
    ) in pesher
    assert missing_line.startswith("No passage covers CD 6:30.")
    assert "preceding CD 6:1–11, following CD 19:1" in missing_line


@pytest.mark.asyncio
async def test_search_filters_by_habakkuk_link_and_folds_hebrew(tmp_path, monkeypatch):
    db_path = _build_db(tmp_path, monkeypatch)
    search = server.handle_search_ancient_sources

    # Qumran passages have no English and titles are not searched, so the
    # linked column is found by a Hebrew word on it.
    linked = await _call(
        db_path, monkeypatch, search, query="יושרה", biblical_reference="Habakkuk 2:4",
        corpus="qumran",
    )
    uncertain = await _call(db_path, monkeypatch, search, query="ענוה", corpus="qumran")
    suffix = await _call(db_path, monkeypatch, search, query="והם ישמרו", corpus="qumran")
    restored = await _call(db_path, monkeypatch, search, query="עופלה", corpus="qumran")

    assert "### Pesher Habakkuk, 1QpHab 2:1–3" in linked
    assert "1QpHab 1:1–2" not in linked
    assert "CD 19:1" in uncertain
    assert "CD 19:1" in suffix
    assert "1QpHab 2:1–3" in restored


@pytest.mark.asyncio
async def test_search_never_matches_reconstruction_and_drops_erasures(tmp_path, monkeypatch):
    db_path = _build_db(tmp_path, monkeypatch)
    search = server.handle_search_ancient_sources

    # 1QS 1:1 prints '[ספר ס]ר֯ך': 'ספר' and the first letter of 'סרך' are an
    # editor's restoration, so neither is searchable there; 1QSa 1:1 has the
    # surviving 'הסרך', found through the prefix fallback.
    restored_word = await _call(db_path, monkeypatch, search, query="ספר", corpus="qumran")
    serekh = await _call(db_path, monkeypatch, search, query="סרך", corpus="qumran")
    pasted = await _call(db_path, monkeypatch, search, query="ס]ר֯ך", corpus="qumran")
    # 1QpHab 1:2 prints 'יג[די]לו': surviving letters either side do not join into 'יגלו'.
    joined = await _call(db_path, monkeypatch, search, query="יגלו", corpus="qumran")
    surviving = await _call(db_path, monkeypatch, search, query="ריב", corpus="qumran")
    # 'זה' is too short to strip; 'יחד' only occurs prefixed ('היחד') in 1QS 1:1.
    stripped = await _call(db_path, monkeypatch, search, query="יחד", corpus="qumran")
    # CD 19:1 prints the scribe's erasure '{{נפ◦◦}}'; CD 1:1 a vacat.
    erased = await _call(db_path, monkeypatch, search, query="נפ", corpus="qumran")
    vacat = await _call(db_path, monkeypatch, search, query="vacat", corpus="qumran")

    assert restored_word.startswith("No Qumran passage contains")
    assert "1QS 1:1" not in serekh and "### Rule of the Congregation, 1QSa 1:1 (prefix match)" in serekh
    assert "1QS 1:1" not in pasted
    assert joined.startswith("No Qumran passage contains")
    assert "1QpHab 1:1–2" in surviving
    # The display keeps the reconstruction and its brackets.
    assert "יג[די]לו" in surviving
    assert "### Community Rule, 1QS 1:1 (prefix match)" in stripped
    assert "*No exact match: these passages match only after stripping" in stripped
    assert "CD 19:1" not in erased
    assert "CD 1:1" not in vacat
