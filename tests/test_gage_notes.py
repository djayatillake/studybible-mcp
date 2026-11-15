"""Gage/Bradley cross-reference notes: excerpting long quotes, and the repair
script that rewrites the notes in an existing database."""

from __future__ import annotations

import gzip
import json
import sqlite3

import pytest

import scripts.repair_gage_notes as repair
from scripts.ingest_burnett_gage import (
    NOTE_SIDE_BUDGET,
    _cue_words,
    excerpt_side,
    gage_note,
    gage_rows,
)
from study_bible_mcp.database import create_schema

# John 6:51-53 and Rev 19:11-21 as the spreadsheet quotes them: whole passages.
JOHN_6 = (
    "I am the living bread that came down from heaven. If anyone eats of this bread, he will "
    "live forever. And this bread, which I will give for the life of the world, is My flesh.” "
    "At this, the Jews began to argue among themselves, “How can this man give us His flesh to "
    "eat?” So Jesus said to them, “Truly, truly, I tell you, unless you eat the flesh and drink "
    "the blood of the Son of Man, you have no life in you."
)
REV_19 = (
    "Then I saw heaven standing open, and there before me was a white horse. He is dressed in a "
    "robe dipped in blood, and His name is The Word of God. ...Then I saw an angel standing in "
    "the sun, and he cried out in a loud voice to all the birds flying overhead, “Come, gather "
    "together for the great supper of God, so that you may eat the flesh of kings and "
    "commanders and mighty men, of horses and riders, of everyone slave and free, small and "
    "great.” And all the birds gorged themselves on their flesh."
)


def _pair(theme_a: str, theme_c: str, commentary: str = "", attribution: str = "Bradley") -> dict:
    return {"source": "Jhn.6.51", "target": "Rev.19.11", "tier": "chiastic",
            "theme_a": theme_a, "theme_c": theme_c, "commentary": commentary,
            "attribution": attribution}


def test_a_short_quote_is_left_exactly_as_written():
    quote = "“they will see Him whom they pierced”  "
    assert excerpt_side(quote, {"pierced"}) == quote
    assert gage_note(_pair("“they will see Him whom they pierced”",
                           "“they who pierced Him will see Him”", attribution="Gage")) == (
        "“they will see Him whom they pierced” ⟷ “they who pierced Him will see Him” | Gage"
    )


def test_a_long_quote_keeps_the_sentences_that_share_the_most_words():
    quote = excerpt_side(JOHN_6, _cue_words(REV_19))
    assert quote == (
        "… So Jesus said to them, “Truly, truly, I tell you, unless you eat the flesh and drink "
        "the blood of the Son of Man, you have no life in you."
    )
    assert len(quote) <= NOTE_SIDE_BUDGET + 4


def test_an_over_long_best_sentence_is_cut_around_its_shared_words():
    quote = excerpt_side(REV_19, _cue_words(JOHN_6))
    # Cutting from the start would stop at "the great supper of"; the window
    # keeps "eat the flesh", the words the pairing rests on.
    assert "eat the flesh" in quote
    assert quote.startswith("… ") and quote.endswith(" …")
    assert len(quote) <= NOTE_SIDE_BUDGET + 4


def test_a_quote_sharing_no_words_falls_back_to_its_first_sentence():
    text = "Alpha beta gamma delta. " * 10
    assert excerpt_side(text, {"omega"}) == "Alpha beta gamma delta. …"


def test_the_note_of_a_pasted_passage_pair_is_a_fraction_of_its_length():
    commentary = "Eat flesh, drink blood are clear communion analogies"
    old_length = len(f"{JOHN_6} ⟷ {REV_19} | {commentary} | Bradley")
    note = gage_note(_pair(JOHN_6, REV_19, commentary))
    assert note.endswith(f" | {commentary} | Bradley")
    assert " ⟷ " in note
    assert len(note) < old_length / 2


def test_gage_rows_run_both_directions_and_the_first_pair_wins_a_repeat():
    first = _pair("bread", "supper")
    repeat = {**_pair("flesh", "flesh"), "tier": "parallel"}
    rows, dropped = gage_rows([first, repeat])
    assert rows == [
        ("Jhn.6.51", "Rev.19.11", 1, "bread ⟷ supper | Bradley"),
        ("Rev.19.11", "Jhn.6.51", 1, "bread ⟷ supper | Bradley"),
    ]
    assert dropped == 2


# --- repair_gage_notes ---------------------------------------------------------

OLD_ROWS = [
    ("Jhn.6.51", "Rev.19.11", 1, f"{JOHN_6} ⟷ {REV_19} | Bradley"),
    ("Rev.19.11", "Jhn.6.51", 1, f"{JOHN_6} ⟷ {REV_19} | Bradley"),
    ("Jhn.19.37", "Rev.1.7", 3, "“they will see Him whom they pierced” ⟷ “they who pierced Him will see Him” | Gage"),
]
NEW_ROWS = [
    (s, t, r, gage_note(_pair(JOHN_6, REV_19))) if r == 1 else (s, t, r, n)
    for s, t, r, n in OLD_ROWS
]


def _rows(db) -> list:
    conn = sqlite3.connect(db)
    rows = conn.execute(
        "SELECT source, target, type, relevance, note FROM cross_references ORDER BY id"
    ).fetchall()
    conn.close()
    return rows


@pytest.fixture
def old_db(tmp_path, monkeypatch):
    db = tmp_path / "study_bible.db"
    conn = sqlite3.connect(db)
    create_schema(conn)
    conn.executemany(
        "INSERT INTO cross_references (source, target, type, relevance, note) VALUES (?,?,'gage',?,?)",
        OLD_ROWS,
    )
    conn.execute("INSERT INTO cross_references (source, target, type, relevance) "
                 "VALUES ('Jhn.6.51', 'Jhn.6.35', 'tsk', 30)")
    conn.commit()
    monkeypatch.setattr(repair, "BEFORE_FINGERPRINT", repair.fingerprint(conn))
    conn.close()
    return db


def test_repair_rewrites_only_the_gage_notes_and_is_idempotent(old_db):
    before = _rows(old_db)
    patch = repair.patch_from_rows(NEW_ROWS)
    conn = sqlite3.connect(old_db)
    assert repair.apply_patch(conn, patch) == 2
    assert repair.apply_patch(conn, patch) is None
    conn.close()
    after = _rows(old_db)
    assert [row[:4] for row in after] == [row[:4] for row in before]
    assert [row[4] for row in after] == [n for *_, n in NEW_ROWS] + [None]


def test_repair_refuses_rows_it_does_not_recognise(old_db):
    conn = sqlite3.connect(old_db)
    conn.execute("UPDATE cross_references SET note = 'edited by hand' WHERE target = 'Rev.1.7'")
    conn.commit()
    before = _rows(old_db)
    with pytest.raises(repair.RefusedError, match="neither"):
        repair.apply_patch(conn, repair.patch_from_rows(NEW_ROWS))
    conn.close()
    assert _rows(old_db) == before


def test_repair_refuses_a_patch_that_does_not_match_itself(old_db):
    patch = repair.patch_from_rows(NEW_ROWS)
    patch["rows"][0][3] = "tampered"
    conn = sqlite3.connect(old_db)
    with pytest.raises(repair.RefusedError, match="'to' fingerprint"):
        repair.apply_patch(conn, patch)
    conn.close()


def test_repair_applies_a_saved_patch_from_the_command_line(old_db, tmp_path, monkeypatch, capsys):
    patch_path = tmp_path / "gage_notes.json.gz"
    with gzip.open(patch_path, "wt", encoding="utf-8") as handle:
        json.dump(repair.patch_from_rows(NEW_ROWS), handle, ensure_ascii=False)
    monkeypatch.setattr("sys.argv", ["repair_gage_notes.py", str(old_db), "--apply-patch", str(patch_path)])
    assert repair.main() == 0
    assert "rewrote 2 notes" in capsys.readouterr().out
    assert [row[4] for row in _rows(old_db)][:3] == [n for *_, n in NEW_ROWS]
