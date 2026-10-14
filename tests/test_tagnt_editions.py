"""NT words missing from NA28: kept by the TAGNT parser, noted by search_by_strongs, repaired in place."""

from __future__ import annotations

import gzip
import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

import scripts.repair_tagnt_editions as repair
import study_bible_mcp.server as server
from study_bible_mcp.database import StudyBibleDB, create_schema
from study_bible_mcp.parsers.tagged_text import parse_tagnt
from study_bible_mcp.tools import non_na_editions

ALL = "NA28+NA27+Tyn+SBL+WH+Treg+TR+Byz"
TAGNT = "\n".join("\t".join(row) for row in [
    ("Word & Type", "Greek", "English translation", "dStrongs = Grammar", "Dictionary form =  Gloss", "editions"),
    ("Mrk.9.29#01=NKO", "ἐν (en)", "by", "G1722=PREP", "ἐν=in/on/among", ALL),
    ("Mrk.9.29#02=NKO", "προσευχῇ (proseuchēa)", "prayer", "G4335=N-DSF", "προσευχή=prayer", ALL),
    ("Mrk.9.29#03=KO", "καὶ (kai)", "and", "G2532=CONJ", "καί=and", "Tyn+Treg+TR+Byz"),
    ("Mrk.9.29#04=KO", "νηστείᾳ.¶ (nēsteia)", "with fastings.", "G3521=N-DSF", "νηστεία=fasting", "Tyn+Treg+TR+Byz"),
    ("Luk.2.37#01=NKO", "νηστείαις (nēsteiais)", "with fastings", "G3521=N-DPF", "νηστεία=fasting", ALL),
    ("Luk.2.37#02=N(k)O", "καὶ (kai)", "and", "G2532=CONJ", "καί=and", ALL),
]) + "\n"


@pytest.fixture
def tagnt(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    path = data_dir / "TAGNT_Mat-Jhn.txt"
    path.write_text(TAGNT, encoding="utf-8")
    return data_dir, {verse["reference"]: verse for verse in parse_tagnt(path)}


def _unmarked(word_data: str) -> str:
    words = [{k: v for k, v in word.items() if k != "editions"} for word in json.loads(word_data)]
    return json.dumps(words, ensure_ascii=False)


def test_the_parser_keeps_the_editions_of_words_missing_from_na28(tagnt):
    _, verses = tagnt
    mark = json.loads(verses["Mrk.9.29"]["word_data"])
    assert [word.get("editions") for word in mark] == [None, None, "Tyn+Treg+TR+Byz", "Tyn+Treg+TR+Byz"]
    assert mark[3] == {
        "word": "νηστείᾳ.", "transliteration": "nēsteia", "strongs": "G3521", "morph": "N-DSF",
        "gloss": "with fastings.", "paragraph_end": True, "editions": "Tyn+Treg+TR+Byz",
    }
    assert all("editions" not in word for word in json.loads(verses["Luk.2.37"]["word_data"]))


def test_non_na_editions_needs_every_occurrence_outside_na28(tagnt):
    _, verses = tagnt
    assert non_na_editions(verses["Mrk.9.29"], "G3521") == "Tyn+Treg+TR+Byz"
    assert non_na_editions(verses["Mrk.9.29"], "g3521") == "Tyn+Treg+TR+Byz"
    assert non_na_editions(verses["Luk.2.37"], "G3521") is None
    # καὶ is in NA28 at Luke 2:37 and only in the TR at Mark 9:29.
    assert non_na_editions(verses["Mrk.9.29"], "G2532") == "Tyn+Treg+TR+Byz"
    assert non_na_editions(verses["Mrk.9.29"], "G4335") is None


def _database(path: Path, verses: dict, marked: bool) -> None:
    conn = sqlite3.connect(path)
    create_schema(conn)
    conn.execute(
        "INSERT INTO lexicon (strongs, language, word, transliteration, short_definition) "
        "VALUES ('G3521', 'greek', 'νηστεία', 'nēsteia', 'fasting')"
    )
    for reference, verse in verses.items():
        word_data = verse["word_data"] if marked else _unmarked(verse["word_data"])
        conn.execute(
            "INSERT INTO verses (reference, book, chapter, verse, text_english, word_data) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (reference, verse["book"], verse["chapter"], verse["verse"], verse["text_english"], word_data),
        )
    conn.executemany(
        "INSERT INTO bsb_verses (reference, book, chapter, verse, text) VALUES (?, ?, ?, ?, ?)",
        [("Mrk.9.29", "Mrk", 9, 29, "Jesus answered, “This kind cannot come out, except by prayer.”"),
         ("Luk.2.37", "Luk", 2, 37, "She worshiped night and day, fasting and praying.")],
    )
    conn.commit()
    conn.close()


async def test_search_by_strongs_notes_a_verse_whose_word_is_not_in_na28(tagnt, tmp_path, monkeypatch):
    _, verses = tagnt
    path = tmp_path / "fasting.db"
    _database(path, verses, marked=True)
    database = StudyBibleDB(path)
    await database.connect()
    monkeypatch.setattr(server, "db", database)
    try:
        (response,) = await server.call_tool("search_by_strongs", {"strongs": "G3521"})
    finally:
        await database.close()
    lines = {line.split("**")[1]: line for line in response.text.splitlines() if line.startswith("**")}
    assert lines["Mrk.9.29"].endswith(
        "except by prayer.” *(word only in Tyn+Treg+TR+Byz Greek, not NA28; the BSB may lack it)*"
    )
    assert lines["Luk.2.37"].endswith("fasting and praying.")


def _word_data(path: Path) -> dict[str, str]:
    conn = sqlite3.connect(path)
    rows = dict(conn.execute("SELECT reference, word_data FROM verses"))
    conn.close()
    return rows


def _run(monkeypatch, *argv) -> int:
    monkeypatch.setattr("sys.argv", ["repair_tagnt_editions.py", *map(str, argv)])
    return repair.main()


def test_repair_marks_an_existing_database_like_a_fresh_import(tagnt, tmp_path, monkeypatch, capsys):
    data_dir, verses = tagnt
    db, copy = tmp_path / "study_bible.db", tmp_path / "copy.db"
    _database(db, verses, marked=False)
    shutil.copy(db, copy)
    patch = tmp_path / "editions.patch.gz"

    assert _run(monkeypatch, db, "--data-dir", data_dir, "--write-patch", patch) == 0
    assert "marks 2 words in 1 verses" in capsys.readouterr().out
    assert _word_data(db) == {reference: verse["word_data"] for reference, verse in verses.items()}
    assert _run(monkeypatch, db, "--data-dir", data_dir) == 0
    assert "0 verses updated" in capsys.readouterr().out
    with gzip.open(patch, "rt", encoding="utf-8") as handle:
        assert json.load(handle)["Mrk.9.29"]["add"] == [[2, "Tyn+Treg+TR+Byz"], [3, "Tyn+Treg+TR+Byz"]]

    server_dir = tmp_path / "server"
    server_dir.mkdir()
    script = shutil.copy(Path(repair.__file__), server_dir / "repair_tagnt_editions.py")
    for _ in range(2):  # the second run is a no-op
        result = subprocess.run(
            [sys.executable, "-I", "-S", script, copy, "--apply-patch", patch],
            capture_output=True, text=True, cwd=server_dir,
        )
        assert result.returncode == 0, result.stderr
    assert _word_data(copy) == _word_data(db)


def test_a_verse_with_other_word_data_stops_the_repair(tagnt, tmp_path, monkeypatch):
    data_dir, verses = tagnt
    db, copy = tmp_path / "study_bible.db", tmp_path / "copy.db"
    _database(db, verses, marked=False)
    shutil.copy(db, copy)
    patch = tmp_path / "editions.patch.gz"
    assert _run(monkeypatch, db, "--data-dir", data_dir, "--write-patch", patch) == 0

    conn = sqlite3.connect(copy)
    conn.execute("UPDATE verses SET word_data = replace(word_data, 'prayer', 'PRAYER')")
    conn.commit()
    conn.close()
    before = _word_data(copy)
    assert _run(monkeypatch, copy, "--apply-patch", patch) == 1
    assert _word_data(copy) == before
