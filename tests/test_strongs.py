"""Strong's numbers in Hebrew word data: import, search, and the in-place repair.

STEPBible tags a Hebrew word with prefixes as H9003/{H7225G}: the braces mark
the root, and the letter is a sense suffix that the lexicon does not carry.
"""

from __future__ import annotations

import gzip
import json
import sqlite3

import pytest

import scripts.repair_hebrew_word_strongs as repair
import study_bible_mcp.server as server
from study_bible_mcp.database import StudyBibleDB, build_strongs_index, create_schema
from study_bible_mcp.parsers.tagged_text import parse_hebrew_word, parse_tahot

# Genesis 1:1, first three words, in TAHOT's column layout.
TAHOT_GEN_1_1 = [
    "Gen.1.1#01=L\tבְּ/רֵאשִׁ֖ית\tbe./re.Shit\tin/ beginning\tH9003/{H7225G}\tHR/Ncfsa",
    "Gen.1.1#02=L\tבָּרָ֣א\tba.Ra'\the created\t{H1254A}\tHVqp3ms",
    "Gen.1.1#03=L\tאֱלֹהִ֑ים\t'E.lo.Him\tGod\t{H0430G}\tHNcmpa",
]


def _parse(line: str) -> dict:
    return parse_hebrew_word(line.split("\t"))


def test_hebrew_word_keeps_the_braced_root_not_the_prefix():
    assert _parse(TAHOT_GEN_1_1[0])["strongs"] == "H7225G"
    assert _parse("Gen.1.2#01=L\tוְ/הָ/אָ֗רֶץ\tve./ha./'A.retz\tand/ the/ earth\t"
                  "H9002/H9009/{H0776G}\tHC/Td/Ncbsa")["strongs"] == "H0776G"
    # The root comes first; the pronoun suffix and section marker are not it.
    word = _parse("Gen.1.5#13=L\tאֶחָֽד\\׃\\ \\פ\t'e.Chad\tone\t{H0259}\\H9016\\ \\H9017\tHAcmsa")
    assert word["strongs"] == "H0259"
    assert word["section_end"] == "petuchah"


def test_hebrew_word_without_braces_falls_back_to_the_first_number():
    assert _parse("Gen.1.1#09=L\tהָ/אָֽרֶץ\tha./'A.retz\tthe/ earth\tH9009/H0776G\tHTd/Ncbsa")[
        "strongs"
    ] == "H9009"
    assert _parse("Isa.44.24#16=Q(K)\tמֵ/אִתִּי\tme./'it.Ti\tby/ myself\t\tHR/Sp1bs")["strongs"] == ""


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("G26", "G0026"),
        ("g0026", "G0026"),
        ("H430", "H0430"),
        ("h430g", "H0430G"),
        ("H0430G", "H0430G"),
        ("H00430", "H0430"),
        ("H12345", "H12345"),
        ("AS_word", "AS_WORD"),
    ],
)
def test_normalize_strongs(given, expected):
    assert StudyBibleDB._normalize_strongs(given) == expected


def _words(*numbers: str) -> str:
    return json.dumps(
        [{"word": f"w{n}", "transliteration": "", "strongs": s, "morph": "", "gloss": ""}
         for n, s in enumerate(numbers)],
        ensure_ascii=False,
    )


@pytest.fixture
async def db(tmp_path, monkeypatch):
    path = tmp_path / "strongs.db"
    conn = sqlite3.connect(path)
    create_schema(conn)
    conn.executemany(
        "INSERT INTO lexicon (strongs, language, word, transliteration, short_definition)"
        " VALUES (?, ?, ?, ?, ?)",
        [
            ("H0430", "hebrew", "אֱלֹהִים", "elohim", "God, gods"),
            ("H0043", "hebrew", "אֶבְיָתָר", "evyatar", "Abiathar"),
            ("H7225", "hebrew", "רֵאשִׁית", "reshit", "beginning"),
        ],
    )
    conn.executemany(
        "INSERT INTO verses (reference, book, chapter, verse, text_english, word_data)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("Gen.1.1", "Gen", 1, 1, "In the beginning God created", _words("H7225G", "H1254A", "H0430G")),
            ("Exo.3.6", "Exo", 3, 6, "I am the God of your father", _words("H0430")),
            ("Psa.82.1", "Psa", 82, 1, "God stands in the divine council", _words("H0430H")),
            ("Jhn.3.16", "Jhn", 3, 16, "For God so loved the world", _words("G2316")),
        ],
    )
    conn.commit()
    conn.close()
    database = StudyBibleDB(path)
    await database.connect()
    monkeypatch.setattr(server, "db", database)
    yield database
    await database.close()


def _references(rows: list[dict]) -> list[str]:
    return [row["reference"] for row in rows]


async def test_bare_number_finds_every_sense_suffix(db):
    assert _references(await db.get_verses_with_strongs("H430")) == ["Gen.1.1", "Exo.3.6", "Psa.82.1"]
    assert _references(await db.get_verses_with_strongs("H7225")) == ["Gen.1.1"]


async def test_suffixed_number_finds_only_that_sense(db):
    assert _references(await db.get_verses_with_strongs("H430G")) == ["Gen.1.1"]


async def test_number_does_not_match_a_longer_number(db):
    assert await db.get_verses_with_strongs("H43") == []


async def test_suffixed_number_uses_the_bare_lexicon_entry(db):
    assert (await db.get_lexicon_entry("H430G"))["strongs"] == "H0430"
    assert await db.get_lexicon_entry("H9999G") is None


async def test_search_by_strongs_finds_hebrew_verses(db):
    result = await server.call_tool("search_by_strongs", {"strongs": "H430"})
    output = result[0].text
    assert output.startswith("## Verses with H430 (אֱלֹהִים - elohim)")
    assert "**Gen.1.1**: In the beginning God created" in output
    assert "**Psa.82.1**" in output
    assert "No verses found" not in output


# ---------------------------------------------------------------------------
# scripts/repair_hebrew_word_strongs.py
# ---------------------------------------------------------------------------


@pytest.fixture
def stale_db(tmp_path):
    """A database imported before the fix, plus the TAHOT source it came from."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    for name in repair.TAHOT_FILES:
        (data_dir / name).write_text("", encoding="utf-8")
    (data_dir / repair.TAHOT_FILES[0]).write_text("\n".join(TAHOT_GEN_1_1) + "\n", encoding="utf-8")

    verse = next(parse_tahot(data_dir / repair.TAHOT_FILES[0]))
    words = json.loads(verse["word_data"])
    words[0]["strongs"] = "H9003"  # what the old importer kept

    path = tmp_path / "study_bible.db"
    conn = sqlite3.connect(path)
    create_schema(conn)
    conn.execute(
        "INSERT INTO verses (reference, book, chapter, verse, word_data) VALUES (?, ?, ?, ?, ?)",
        ("Gen.1.1", "Gen", 1, 1, json.dumps(words, ensure_ascii=False)),
    )
    conn.commit()
    conn.close()
    return path, data_dir


def _stored_numbers(path) -> list[str]:
    conn = sqlite3.connect(path)
    (word_data,) = conn.execute("SELECT word_data FROM verses WHERE reference = 'Gen.1.1'").fetchone()
    conn.close()
    return [word["strongs"] for word in json.loads(word_data)]


def _run(monkeypatch, *argv) -> int:
    monkeypatch.setattr("sys.argv", ["repair_hebrew_word_strongs.py", *map(str, argv)])
    return repair.main()


def test_repair_from_source_is_idempotent_and_writes_a_patch(stale_db, tmp_path, monkeypatch, capsys):
    path, data_dir = stale_db
    patch = tmp_path / "patch.json.gz"
    assert _run(monkeypatch, path, "--data-dir", data_dir, "--write-patch", patch) == 0
    assert _stored_numbers(path) == ["H7225G", "H1254A", "H0430G"]
    with gzip.open(patch, "rt", encoding="utf-8") as handle:
        assert json.load(handle) == {"Gen.1.1": {"0": ["H9003", "H7225G"]}}
    assert "updated 1 words in 1 verses" in capsys.readouterr().out

    assert _run(monkeypatch, path, "--data-dir", data_dir) == 0
    assert "corrects 0 Hebrew words" in capsys.readouterr().out


def test_repair_keeps_an_existing_strongs_index_current(stale_db, monkeypatch):
    path, data_dir = stale_db
    conn = sqlite3.connect(path)
    build_strongs_index(conn)
    conn.commit()
    conn.close()

    assert _run(monkeypatch, path, "--data-dir", data_dir) == 0
    conn = sqlite3.connect(path)
    indexed = {row[0] for row in conn.execute("SELECT strongs FROM verse_strongs")}
    conn.close()
    assert indexed == {"H7225G", "H1254A", "H0430G"}


def test_patch_repairs_a_copy_and_refuses_a_mismatch(stale_db, tmp_path, monkeypatch, capsys):
    path, data_dir = stale_db
    copy = tmp_path / "copy.db"
    copy.write_bytes(path.read_bytes())
    patch = tmp_path / "patch.json.gz"
    assert _run(monkeypatch, path, "--data-dir", data_dir, "--write-patch", patch) == 0

    assert _run(monkeypatch, copy, "--apply-patch", patch) == 0
    assert _stored_numbers(copy) == ["H7225G", "H1254A", "H0430G"]
    assert _run(monkeypatch, copy, "--apply-patch", patch) == 0
    assert "updated 0 words in 0 verses" in capsys.readouterr().out

    # A word holding neither the old nor the new number is not overwritten.
    conn = sqlite3.connect(copy)
    conn.execute(
        "UPDATE verses SET word_data = replace(word_data, '\"H7225G\"', '\"H1234\"')"
    )
    conn.commit()
    conn.close()
    assert _run(monkeypatch, copy, "--apply-patch", patch) == 1
    assert _stored_numbers(copy) == ["H1234", "H1254A", "H0430G"]
