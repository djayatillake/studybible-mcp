"""English versification of cross-references and LXX rows, and the repair script."""

from __future__ import annotations

import gzip
import json
import shutil
import sqlite3
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

import scripts.import_cross_references as import_xrefs
import scripts.repair_versification as repair
from study_bible_mcp.database import create_schema
from study_bible_mcp.parsers.biblical_versions import (
    PSALM_SUPERSCRIPTION_METHOD,
    align_brenton_keys,
    import_biblical_versions,
    iter_lxx_rows,
    pair_psalm_superscriptions,
    without_repeated_verses,
)
from study_bible_mcp.parsers.cross_references import (
    EnglishNumbering,
    parse_ch_xlsx,
    parse_tsk_tsv,
    renumber_pairs,
)
from tests.test_biblical_versions import (
    LXX_ROW_FIELDS,
    _compare,
    _pair,
    _word,
    _write_lxx_sources,
)

# `verses` references: English, with the Hebrew verse in parentheses.
VERSE_REFS = [
    "Gen.1.1", "Psa.11.0(11.1)", "Psa.11.1", "Psa.40.4(40.5)", "Psa.40.5(40.6)",
    "Psa.40.6(40.7)", "Psa.51.0(51.1)", "Psa.51.0(51.2)", "Psa.51.1(51.3)",
    "Jol.2.28(3.1)", "Jol.3.1(4.1)", "Mal.4.1(3.19)", "Job.5.9", "Isa.44.3",
    "Ezk.39.29", "2Sa.12.1", "Php.1.16[1.17]", "Php.1.17[1.16]",
]


def _numbering() -> EnglishNumbering:
    return EnglishNumbering(VERSE_REFS)


@pytest.mark.parametrize("hebrew, english", [
    ("Psa.40.6", "Psa.40.5"),   # the English verse before
    ("Jol.3.1", "Jol.2.28"),    # Hebrew Joel 3 is English 2:28-32
    ("Jol.4.1", "Jol.3.1"),
    ("Psa.51.1", "Psa.51.0"),   # two Hebrew superscription verses: English verse 0
    ("Psa.51.2", "Psa.51.0"),
    ("Psa.11.1", "Psa.11.1"),   # a short title shares its verse with the opening words
    ("Gen.1.1", "Gen.1.1"),
    ("Mal.4.1", "Mal.4.1"),     # the Hebrew has no Malachi 4: already English
    ("Psa.96.96", None),        # in neither numbering
])
def test_hebrew_references_are_renumbered_to_english(hebrew, english):
    assert _numbering().from_hebrew(hebrew) == english


def test_renumbered_pairs_drop_self_links_and_keep_one_of_each_pair():
    pairs = [
        ("Psa.51.1", "2Sa.12.1", 0), ("Psa.51.2", "2Sa.12.1", 3),  # both Psalm 51:0
        ("Psa.51.1", "Psa.51.2", 2),  # one verse once renumbered
        ("Psa.96.96", "Gen.1.1", 2),  # no such verse
        ("Psa.40.6", "Job.5.9", 3),
    ]
    assert list(renumber_pairs(pairs, _numbering().from_hebrew)) == [
        ("Psa.51.0", "2Sa.12.1", 3), ("Psa.40.5", "Job.5.9", 3),
    ]


def test_tsk_philippians_1_16_17_and_3_john_15_take_bsb_numbers(tmp_path):
    path = tmp_path / "tsk.txt"
    path.write_text(
        "From Verse\tTo Verse\tVotes\n"
        "Phil.1.16\tPs.69.26\t5\n"      # KJV 1:16: "add affliction to my bonds"
        "Phil.1.17\tActs.22.1\t4\n"     # KJV 1:17: "the defence of the gospel"
        "3John.1.15\tJohn.10.3\t2\n",   # greet the friends by name
        encoding="utf-8",
    )
    assert list(parse_tsk_tsv(path)) == [
        ("Php.1.17", "Psa.69.26", 5), ("Php.1.16", "Act.22.1", 4), ("3Jn.1.14", "Jhn.10.3", 2),
    ]


def _write_xlsx(path: Path, rows: list[tuple]) -> None:
    """A minimal xlsx: a shared-string header row, then numeric rows."""
    header, *body = rows
    cells = "".join(
        f'<c r="{chr(65 + index)}1" t="s"><v>{index}</v></c>' for index in range(len(header))
    )
    sheet_rows = [f'<row r="1">{cells}</row>']
    for number, row in enumerate(body, 2):
        cells = "".join(
            f'<c r="{chr(65 + index)}{number}"><v>{value}</v></c>'
            for index, value in enumerate(row) if value is not None
        )
        sheet_rows.append(f'<row r="{number}">{cells}</row>')
    namespace = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "xl/sharedStrings.xml",
            f'<sst xmlns="{namespace}">' + "".join(f"<si><t>{name}</t></si>" for name in header) + "</sst>",
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            f'<worksheet xmlns="{namespace}"><sheetData>{"".join(sheet_rows)}</sheetData></worksheet>',
        )


CH_HEADER = ("Book1", "Chapter1", "Verse1", "Book2", "Chapter2", "Verse2", "Orig", "Circ")
# Hebrew-numbered rows: Psalm 40:6 (English 40:5) with Job 5:9; Joel 3:1
# (English 2:28) with Ezekiel 39:29; Psalm 51:2 (English 51:0) with 2 Samuel
# 12:1, its Orig and Circ cells empty.
CH_ROWS = [CH_HEADER, (19, 40, 6, 18, 5, 9, 1, 1), (29, 3, 1, 26, 39, 29, 1, 1), (19, 51, 2, 10, 12, 1, None, None)]


def test_ch_xlsx_is_read_without_openpyxl(tmp_path):
    path = tmp_path / "ch.xlsx"
    _write_xlsx(path, CH_ROWS)
    assert list(parse_ch_xlsx(path)) == [
        ("Psa.40.6", "Job.5.9", 3), ("Jol.3.1", "Ezk.39.29", 3), ("Psa.51.2", "2Sa.12.1", 0),
    ]


def _xref_db(tmp_path: Path) -> Path:
    db = tmp_path / "xrefs.db"
    conn = sqlite3.connect(db)
    create_schema(conn)
    conn.executemany(
        "INSERT INTO verses (reference, book, chapter, verse) VALUES (?, ?, ?, ?)",
        [(ref, ref.split(".")[0], 0, 0) for ref in VERSE_REFS],
    )
    conn.commit()
    conn.close()
    return db


def test_importer_stores_ch_links_under_english_numbers(tmp_path, monkeypatch):
    db = _xref_db(tmp_path)
    _write_xlsx(tmp_path / "ch.xlsx", CH_ROWS)
    monkeypatch.setattr(import_xrefs, "CH_PATH", tmp_path / "ch.xlsx")
    conn = sqlite3.connect(db)
    import_xrefs.reset_table(conn)
    assert import_xrefs.import_ch(conn) == 3
    assert conn.execute("SELECT source, target, relevance FROM cross_references ORDER BY id").fetchall() == [
        ("Psa.40.5", "Job.5.9", 3), ("Jol.2.28", "Ezk.39.29", 3), ("Psa.51.0", "2Sa.12.1", 0),
    ]
    conn.close()


# --- LXX: Psalm superscriptions ---------------------------------------------

def test_psalm_superscription_verses_pair_with_english_verse_0():
    pairings = {
        ("psalms-lxx", ref): [_pair("psalms-lxx", ref, "psalms", target)]
        for ref, target in (("50:1", "51:1"), ("50:2", "51:1"), ("50:3", "51:1"), ("50:4", "51:2"),
                            ("10:1", "11:1"))
    }
    pair_psalm_superscriptions(pairings)
    targets = {ref: (records[0]["mt_refs"], records[0]["method"]) for (_, ref), records in pairings.items()}
    assert targets == {
        "50:1": (["51:0"], PSALM_SUPERSCRIPTION_METHOD),
        "50:2": (["51:0"], PSALM_SUPERSCRIPTION_METHOD),
        "50:3": (["51:1"], "tvtms"),  # "Have mercy on me, O God"
        "50:4": (["51:2"], "tvtms"),
        "10:1": (["11:1"], "tvtms"),  # title and first words share one Greek verse
    }


async def test_comparison_pairs_superscription_with_superscription(tmp_path):
    lxx = {
        "psalms-lxx": [("Ps 82:1", "ᾠδὴ ψαλμοῦ τῷ Ασαφ"), ("Ps 82:2", "ὁ θεός τίς ὁμοιωθήσεταί σοι")],
    }
    pairs = [_pair("psalms-lxx", "82:1", "psalms", "83:1"), _pair("psalms-lxx", "82:2", "psalms", "83:1")]
    mt = [
        ("Psa.83.0(83.1)", "Psa", 83, 0, "a song a psalm of/ Asaph", "שִׁיר מִזְמוֹר לְאָסָף"),
        ("Psa.83.1(83.2)", "Psa", 83, 1, "O God not [let there be] silence", "אֱלֹהִים אַל־דֳּמִי"),
    ]
    db = tmp_path / "psalms.db"
    conn = sqlite3.connect(db)
    create_schema(conn)
    conn.executemany(
        """INSERT INTO verses (reference, book, chapter, verse, text_english, text_original, word_data)
           VALUES (?, ?, ?, ?, ?, ?, '[]')""",
        mt,
    )
    conn.commit()
    lxx_dir = _write_lxx_sources(tmp_path / "data")
    for slug, verses in lxx.items():
        (lxx_dir / "morphology" / f"{slug}.json").write_text(
            json.dumps([{"ref": ref, "words": [_word(w) for w in text.split()]} for ref, text in verses]),
            encoding="utf-8",
        )
    (lxx_dir / "verse_pairs.jsonl").write_text("".join(json.dumps(p) + "\n" for p in pairs), encoding="utf-8")
    import_biblical_versions(conn, tmp_path / "data")
    conn.close()

    def pairing(result):
        return [(row["canonical_reference"], row["version"], row["edition_reference"]) for row in result["rows"]]

    assert pairing(await _compare(db, "Psalm 83:0")) == [
        ("Psa.83.0", "MT", "Psa.83.1"), ("Psa.83.0", "LXX", "Psa.82.1"),
    ]
    assert pairing(await _compare(db, "Psalm 83:1")) == [
        ("Psa.83.1", "MT", "Psa.83.2"), ("Psa.83.1", "LXX", "Psa.82.2"),
    ]
    assert pairing(await _compare(db, "Psalm 82:1", numbering="lxx")) == [
        ("Psa.83.0", "MT", "Psa.83.1"), ("Psa.83.0", "LXX", "Psa.82.1"),
    ]


# --- LXX: Brenton's English beside the right Greek verse --------------------

# Invented "Greek" verses: distinct words per verse, so each is recognisable.
SIRACH_PROLOGUE = "πολλων και μεγαλων ημιν δια του νομου και των προφητων δεδομενων"
SIRACH_1_1 = "πασα σοφια παρα κυριου και μετ αυτου εστιν εις τον αιωνα"
SIRACH_1_2 = "αμμον θαλασσων και σταγονας υετου και ημερας αιωνος τις εξαριθμησει"
SIRACH_1_3 = "υψος ουρανου και πλατος γης και αβυσσον και σοφιαν τις εξιχνιασει"


def test_brenton_verse_numbered_differently_is_found_by_its_greek():
    rahlfs = [("0:1", SIRACH_PROLOGUE), ("1:1", SIRACH_1_1), ("1:2", SIRACH_1_2), ("1:3", SIRACH_1_3)]
    # Brenton prints the prologue as 1:1 and Sirach 1:1 as 1:1h.
    greek = {"1:1": SIRACH_PROLOGUE, "1:1h": SIRACH_1_1, "1:2": SIRACH_1_2, "1:3": SIRACH_1_3}
    english = {
        "1:1": "Whereas many and great things have been delivered unto us by the law",
        "1:1h": "All wisdom cometh from the Lord, and is with him for ever.",
        "1:2": "Who can number the sand of the sea, and the drops of rain?",
        "1:3": "Who can find out the height of heaven, and the breadth of the earth?",
    }
    assert align_brenton_keys(rahlfs, greek, english) == {"0:1": "1:1", "1:1": "1:1h"}


def test_a_run_of_verses_one_behind_brenton_is_realigned():
    verses = [SIRACH_1_1, SIRACH_1_2, SIRACH_1_3]
    rahlfs = list(zip(("1:1", "1:2", "1:3"), verses))
    greek = {"1:1": SIRACH_PROLOGUE, **dict(zip(("1:2", "1:3", "1:4"), verses))}
    english = {key: f"English {key} " + "word " * (len(text) // 8) for key, text in greek.items()}
    assert align_brenton_keys(rahlfs, greek, english) == {"1:1": "1:2", "1:2": "1:3", "1:3": "1:4"}


def test_another_english_version_vetoes_a_move_brentons_english_does_not_share():
    # Brenton's Greek is a verse out from his English (as eBible's Psalm 12 was, uncorrected).
    verses = [SIRACH_1_1, SIRACH_1_2, SIRACH_1_3]
    rahlfs = list(zip(("12:1", "12:2", "12:3"), verses))
    greek = {"12:1": SIRACH_PROLOGUE, **dict(zip(("12:2", "12:3", "12:4"), verses))}
    english = {
        "12:1": "All wisdom is from the Lord and abides with him for ever and ever",
        "12:2": "Who can number the sand of the seas and the drops of the rain",
        "12:3": "Who can search out the height of heaven and the breadth of the earth",
        "12:4": "Wisdom was created before all things and prudent understanding",
    }
    bsb = {"12:1": "All wisdom comes from the Lord and remains with him forever",
           "12:2": "Who can count the sand of the seas or the drops of rain",
           "12:3": "Who can measure the height of heaven or the breadth of the earth"}
    assert align_brenton_keys(rahlfs, greek, english, bsb) == {}
    assert len(align_brenton_keys(rahlfs, greek, english)) == 3


def test_iter_lxx_rows_takes_english_from_the_matching_brenton_verse(tmp_path):
    morphology = tmp_path / "morphology"
    morphology.mkdir()
    (morphology / "sirach.json").write_text(json.dumps([
        {"ref": f"Sir {ref}", "words": [_word(w) for w in text.split()]}
        for ref, text in (("0:1", SIRACH_PROLOGUE), ("1:1", SIRACH_1_1), ("1:2", SIRACH_1_2))
    ]), encoding="utf-8")
    english = {("SIR", "1:1"): "Whereas many and great things have been delivered unto us",
               ("SIR", "1:1h"): "All wisdom cometh from the Lord, and is with him for ever.",
               ("SIR", "1:2"): "Who can number the sand of the sea, and the drops of rain"}
    greek = {("SIR", "1:1"): SIRACH_PROLOGUE, ("SIR", "1:1h"): SIRACH_1_1, ("SIR", "1:2"): SIRACH_1_2}
    rows = [dict(zip(LXX_ROW_FIELDS, row)) for row in iter_lxx_rows(morphology, {}, english, greek)]
    assert {row["edition_reference"]: row["translation"] for row in rows} == {
        "Sir.0.1": "Whereas many and great things have been delivered unto us",
        "Sir.1.1": "All wisdom cometh from the Lord, and is with him for ever.",
        "Sir.1.2": "Who can number the sand of the sea, and the drops of rain",
    }


# Invented verses for 4 Maccabees 7:23-8:4, where Brenton prints Rahlfs 8:1
# as 7:24 and splits Rahlfs 8:2 into 7:25 and 8:1.
MACC = {
    "7:23": "μονοσ γαρ ο σοφοσ και ανδρειοσ εστιν των παθων κυριοσ",
    "8:1": "δια τουτο μειρακισκοι λογισμω φιλοσοφουντεσ χαλεπωτερων βασανιστηριων επεκρατησαν",
    "8:2a": "επειδη πρωτην πειραν ενικηθη",
    "8:2b": "τοτε σφοδρα περιπαθωσ εκελευσεν αλλουσ εβραιων αγαγειν πικροτερον βασανιζειν",
    "8:3": "ταυτα διαταξαμενου τυραννου παρησαν αγομενοι γεραιασ μητροσ επτα αδελφοι",
    "8:4": "ουσ ιδων τυραννοσ καθαπερ χορω μεσην μητερα περιεχοντασ ησθετο",
}


def _english_for(greek: dict[str, str]) -> dict[str, str]:
    return {key: f"English {key} " + "word " * (len(text) // 6) for key, text in greek.items()}


def test_a_verse_whose_brenton_number_went_to_another_verse_follows_its_text():
    rahlfs = [
        ("7:23", MACC["7:23"]), ("8:1", MACC["8:1"]), ("8:2", f"{MACC['8:2a']} {MACC['8:2b']}"),
        ("8:3", MACC["8:3"]), ("8:4", MACC["8:4"]),
    ]
    greek = {
        "7:23": MACC["7:23"], "7:24": MACC["8:1"], "7:25": MACC["8:2a"], "8:1": MACC["8:2b"],
        "8:2": MACC["8:3"], "8:3": MACC["8:4"],
    }
    # Rahlfs 8:1 used to keep Brenton's 8:1, which went to Rahlfs 8:2.
    assert align_brenton_keys(rahlfs, greek, _english_for(greek)) == {
        "8:1": "7:24", "8:2": "8:1", "8:3": "8:2", "8:4": "8:3",
    }


def test_a_verse_within_the_brenton_verse_another_verse_took_keeps_it():
    # Brenton prints Rahlfs 1:1-2 as one verse, 1:1 (Numbers 21:19-20).
    short, long, last = MACC["8:2a"], MACC["8:2b"], MACC["8:3"]
    rahlfs = [("1:1", short), ("1:2", long), ("1:3", last)]
    greek = {"1:1": f"{short} {long}", "1:2": last, "1:3": MACC["8:4"]}
    assert align_brenton_keys(rahlfs, greek, _english_for(greek)) == {"1:2": "1:1", "1:3": "1:2"}


def test_a_verse_whose_brenton_number_went_elsewhere_and_has_no_match_loses_it():
    rahlfs = [("1:1", MACC["7:23"]), ("1:2", MACC["8:3"]), ("1:3", MACC["8:4"])]
    greek = {"1:1": MACC["8:3"], "1:2": MACC["8:4"], "1:3": MACC["8:1"]}
    assert align_brenton_keys(rahlfs, greek, _english_for(greek)) == {"1:1": None, "1:2": "1:1", "1:3": "1:2"}


# eBible's Greek repeats a neighbouring verse (Job 3:13-14, 1 Chronicles
# 11:24-25, Numbers 34:10-11); Brenton's English does not.
JOB_3 = {
    "3:13": "νῦν ἂν κοιμηθεὶς ἡσύχασα, ὑπνώσας δὲ ἀνεπαυσάμην",
    "3:14": "Νῦν ἂν κοιμηθεὶς ἡσύχασα, ὑπνώσας δὲ ἀνεπαυσάμην μετὰ βασιλέων βουλευτῶν γῆς οἳ ἐγαυριῶντο ἐπὶ ξίφεσιν,",
}
JOB_3_ENGLISH = {
    "3:13": "Now I should have lain down and been quiet, I should have slept and been at rest,",
    "3:14": "with kings and councillors of the earth, who gloried in their swords;",
}
CHRONICLES_11 = {
    "11:24": "Ταῦτα ἐποίησε Βαναία υἱὸς Ἰωδαὲ, καὶ τούτῳ ὄνομα ἐν τοῖς τρισὶ τοῖς δυνατοῖς. Ὑπὲρ τοὺς "
             "τριάκοντα ἦν ἔνδοξος οὗτος, καὶ πρὸς τοὺς τρεῖς οὐκ ἤρχετο· καὶ κατέστησεν αὐτὸν Δαυὶδ ἐπὶ "
             "τὴν πατριὰν αὐτοῦ.",
    "11:25": "Ὑπὲρ τοὺς τριάκοντα ἦν ἔνδοξος οὗτος, καὶ πρὸς τοὺς τρεῖς οὐκ ἤρχετο· καὶ κατέστησεν "
             "αὐτὸν Δαυεὶδ ἐπὶ τὴν πατριὰν αὐτοῦ.",
}
CHRONICLES_11_ENGLISH = {
    "11:24": "These things did Banaia son of Jodae, and his name was among the three mighties.",
    "11:25": "He was distinguished beyond the thirty, yet he reached not to the first three: "
             "and David set him over his family.",
}
NUMBERS_34 = {
    "34:9": "Καὶ ἐξελεύσεται τὰ ὅρια Δεφρωνὰ, καὶ ἔσται ἡ διέξοδος αὐτοῦ Ἀρσεναΐν· τοῦτο ἔσται ὑμῖν ὅρια ἀπὸ Βοῤῥᾶ.",
    "34:10": "Καὶ καταβήσεται τὰ ὅρια ἀπὸ Σεπεφαμὰρ Βηλὰ ἀπὸ ἀνατολῶν ἐπὶ πηγὰς, και καταβήσεται τὰ ὅρια "
             "Βηλὰ ἐπὶ νώτου θαλάσσης Χενερὲθ ἀπὸ ἀνατολῶν.",
    "34:11": "Καὶ καταβήσεται τὰ ὅρια ἀπὸ Σεπφαμὰρ Βηλὰ ἀπὸ ἀνατολῶν ἐπὶ πηγάς, καὶ καταβήσεται τὰ ὅρια "
             "Βηλὰ ἐπὶ νώτου θαλάσσης Χενερὲθ ἀπὸ ἀνατολῶν.",
}
NUMBERS_34_ENGLISH = {
    "34:9": "And the border shall go out to Dephrona, and its termination shall be at Arsenain; "
            "this shall be your border from the north.",
    "34:10": "And ye shall measure to yourselves the eastern border from Arsenain to Sepphamar.",
    "34:11": "And the border shall go down from Sepphamar to Bela eastward to the fountains, and the "
             "border shall go down from Bela behind the sea Chenereth eastward.",
}
NUMBERS_34_RAHLFS = {
    "34:9": "καὶ ἐξελεύσεται τὰ ὅρια Δεφρωνα καὶ ἔσται ἡ διέξοδος αὐτοῦ Ασερναιν τοῦτο ἔσται ὑμῖν ὅρια ἀπὸ βορρᾶ",
    "34:10": "καὶ καταμετρήσετε ὑμῖν αὐτοῖς τὰ ὅρια ἀνατολῶν ἀπὸ Ασερναιν Σεπφαμα",
    "34:11": "καὶ καταβήσεται τὰ ὅρια ἀπὸ Σεπφαμ Αρβηλα ἀπὸ ἀνατολῶν ἐπὶ πηγάς καὶ καταβήσεται τὰ ὅρια "
             "Βηλα ἐπὶ νώτου θαλάσσης Χεναρα ἀπὸ ἀνατολῶν",
}


def test_a_copy_of_the_verse_before_or_after_is_removed_from_a_verse():
    assert without_repeated_verses(JOB_3, JOB_3_ENGLISH) == {
        "3:13": JOB_3["3:13"], "3:14": "μετὰ βασιλέων βουλευτῶν γῆς οἳ ἐγαυριῶντο ἐπὶ ξίφεσιν,",
    }
    assert without_repeated_verses(CHRONICLES_11, CHRONICLES_11_ENGLISH) == {
        "11:24": "Ταῦτα ἐποίησε Βαναία υἱὸς Ἰωδαὲ, καὶ τούτῳ ὄνομα ἐν τοῖς τρισὶ τοῖς δυνατοῖς.",
        "11:25": CHRONICLES_11["11:25"],
    }


def test_a_verse_that_is_only_a_copy_of_its_neighbour_is_removed():
    # Rahlfs tells which of the two is the copy; without it both go.
    corrected = without_repeated_verses(NUMBERS_34, NUMBERS_34_ENGLISH, NUMBERS_34_RAHLFS)
    assert corrected == {"34:9": NUMBERS_34["34:9"], "34:11": NUMBERS_34["34:11"]}
    assert without_repeated_verses(NUMBERS_34, NUMBERS_34_ENGLISH) == {"34:9": NUMBERS_34["34:9"]}


def test_a_refrain_brentons_english_repeats_too_is_kept():
    greek = {
        "37:8": "καὶ οἱ στύλοι αὐτῶν εἴκοσι, καὶ αἱ βάσεις αὐτῶν εἴκοσι.",
        "37:9": "καὶ τὸ κλίτος τὸ πρὸς Βοῤῥᾶν, ἑκατὸν ἐφʼ ἑκατόν· καὶ οἱ στύλοι αὐτῶν εἴκοσι, καὶ αἱ βάσεις αὐτῶν εἴκοσι·",
    }
    english = {
        "37:8": "and their posts twenty, and their sockets twenty;",
        "37:9": "and on the north side a hundred every way, and their posts twenty and their sockets twenty.",
    }
    assert without_repeated_verses(greek, english) == greek


def test_iter_lxx_rows_does_not_compare_a_verse_ebible_replaced_with_its_neighbour(tmp_path):
    morphology = tmp_path / "morphology"
    morphology.mkdir()
    (morphology / "numbers.json").write_text(json.dumps([
        {"ref": f"Num {ref}", "words": [_word(w) for w in text.split()]} for ref, text in NUMBERS_34_RAHLFS.items()
    ]), encoding="utf-8")
    rows = {
        row["edition_reference"]: row
        for row in (dict(zip(LXX_ROW_FIELDS, values)) for values in iter_lxx_rows(
            morphology, {},
            {("NUM", key): text for key, text in NUMBERS_34_ENGLISH.items()},
            {("NUM", key): text for key, text in NUMBERS_34.items()},
        ))
    }
    assert rows["Num.34.10"]["translation"] == NUMBERS_34_ENGLISH["34:10"]
    assert rows["Num.34.10"]["brenton_greek_differs"] is None
    # 34:11 is compared with its own Greek only, not the copy before it.
    assert rows["Num.34.11"]["brenton_greek"] == NUMBERS_34["34:11"]
    assert "Καὶ καταβήσεται" not in rows["Num.34.11"]["brenton_greek_difference"]


# --- scripts/repair_versification.py ----------------------------------------

def _repair_setup(tmp_path: Path) -> tuple[Path, Path]:
    """A database as the old importers left it, and the sources it came from."""
    data_dir = tmp_path / "data"
    (data_dir / "cross_references").mkdir(parents=True)
    _write_xlsx(data_dir / "cross_references" / "CH-CrossReference.xlsx", CH_ROWS)
    (data_dir / "cross_references" / "cross_references.txt").write_text(
        "From Verse\tTo Verse\tVotes\nPhil.1.16\tPs.69.26\t5\nIsa.38.1\tIsa.38.1\t21\nGen.1.1\tJohn.1.1\t90\n",
        encoding="utf-8",
    )
    _write_lxx_sources(data_dir)
    db = _xref_db(tmp_path)
    conn = sqlite3.connect(db)
    import_biblical_versions(conn, data_dir)
    # The old rows: CH in Hebrew numbers, TSK's KJV Philippians and its self-link,
    # a Burnett row the repair leaves alone, and an LXX row with misplaced English.
    conn.executemany(
        "INSERT INTO cross_references (source, target, type, relevance) VALUES (?, ?, ?, ?)",
        [("Psa.40.6", "Job.5.9", "ch", 3), ("Jol.3.1", "Ezk.39.29", "ch", 3), ("Psa.51.2", "2Sa.12.1", "ch", 0),
         ("Php.1.16", "Psa.69.26", "tsk", 5), ("Isa.38.1", "Isa.38.1", "tsk", 21), ("Gen.1.1", "Jhn.1.1", "tsk", 90),
         ("Gen.1.1", "Rom.4.13", "burnett", 3)],
    )
    conn.execute("UPDATE biblical_version_verses SET translation = 'Misplaced.' WHERE edition_reference = 'Psa.81.6'")
    conn.commit()
    conn.close()
    return db, data_dir


def _xrefs(db: Path) -> list[tuple]:
    conn = sqlite3.connect(db)
    rows = conn.execute("SELECT source, target, type, relevance FROM cross_references ORDER BY 1, 2, 3").fetchall()
    conn.close()
    return rows


def _lxx_translation(db: Path, edition_reference: str) -> str:
    conn = sqlite3.connect(db)
    (value,) = conn.execute(
        "SELECT translation FROM biblical_version_verses WHERE edition_reference = ?", (edition_reference,)
    ).fetchone()
    conn.close()
    return value


REPAIRED_XREFS = sorted([
    ("Psa.40.5", "Job.5.9", "ch", 3), ("Jol.2.28", "Ezk.39.29", "ch", 3), ("Psa.51.0", "2Sa.12.1", "ch", 0),
    ("Php.1.17", "Psa.69.26", "tsk", 5), ("Gen.1.1", "Jhn.1.1", "tsk", 90), ("Gen.1.1", "Rom.4.13", "burnett", 3),
])


def _run(monkeypatch, *argv) -> int:
    monkeypatch.setattr("sys.argv", ["repair_versification.py", *map(str, argv)])
    return repair.main()


def test_repair_matches_a_fresh_import_and_is_idempotent(tmp_path, monkeypatch, capsys):
    db, data_dir = _repair_setup(tmp_path)
    assert _run(monkeypatch, db, "--data-dir", data_dir) == 0
    assert _xrefs(db) == REPAIRED_XREFS
    assert _lxx_translation(db, "Psa.81.6").startswith("I said, Ye are gods")
    out = capsys.readouterr().out
    assert "5 to delete, 4 to insert (5 deleted, 4 inserted)" in out
    assert "1 to update (1 updated)" in out

    assert _run(monkeypatch, db, "--data-dir", data_dir) == 0
    out = capsys.readouterr().out
    assert "0 to delete, 0 to insert" in out and "0 to update" in out


def test_patch_repairs_a_copy_with_the_standard_library_only(tmp_path, monkeypatch):
    db, data_dir = _repair_setup(tmp_path)
    copy = tmp_path / "copy.db"
    shutil.copy(db, copy)
    patch = tmp_path / "versification.patch.gz"
    assert _run(monkeypatch, db, "--data-dir", data_dir, "--write-patch", patch) == 0
    with gzip.open(patch, "rt", encoding="utf-8") as handle:
        assert set(json.load(handle)) == {"cross_references", "biblical_version_verses"}

    server = tmp_path / "server"
    server.mkdir()
    script = shutil.copy(Path(repair.__file__), server / "repair_versification.py")
    for _ in range(2):  # the second run is a no-op
        result = subprocess.run(
            [sys.executable, "-I", "-S", script, copy, "--apply-patch", patch],
            capture_output=True, text=True, cwd=server,
        )
        assert result.returncode == 0, result.stderr
    assert _xrefs(copy) == _xrefs(db) == REPAIRED_XREFS
    assert _lxx_translation(copy, "Psa.81.6") == _lxx_translation(db, "Psa.81.6")


def test_a_row_holding_unexpected_values_stops_the_whole_repair(tmp_path, monkeypatch):
    db, data_dir = _repair_setup(tmp_path)
    copy = tmp_path / "copy.db"
    shutil.copy(db, copy)
    patch = tmp_path / "versification.patch.gz"
    assert _run(monkeypatch, db, "--data-dir", data_dir, "--write-patch", patch) == 0

    conn = sqlite3.connect(copy)
    conn.execute("UPDATE cross_references SET relevance = 1 WHERE source = 'Psa.40.6'")
    conn.commit()
    conn.close()
    before = _xrefs(copy)
    assert _run(monkeypatch, copy, "--apply-patch", patch) == 1
    assert _xrefs(copy) == before
    assert _lxx_translation(copy, "Psa.81.6") == "Misplaced."
