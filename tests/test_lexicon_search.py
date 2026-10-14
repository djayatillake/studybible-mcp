"""search_lexicon: transliteration spellings, gloss words, stems and lead senses."""

from __future__ import annotations

import sqlite3

import pytest

from study_bible_mcp.database import StudyBibleDB, create_schema
from study_bible_mcp.lexicon_search import (
    LexiconIndex,
    english_stem,
    fold_transliteration,
    word_forms,
)

FILLER = "x" * 220  # pushes a mention past the lead sense of a full definition

# strongs, language, word, transliteration, pronunciation, short, full, usage
LEXICON = [
    ("G0025", "greek", "ἀγαπάω", "agapaō", "agapaō", "to love", "**ἀγαπάω** greet with affection", 143),
    ("G0026", "greek", "ἀγάπη", "agapē", "agapē", "love", "**ἀγάπη** love", 116),
    ("G0027", "greek", "ἀγαπητός", "agapētos", "agapētos", "beloved", "**ἀγαπητός** beloved", 61),
    ("G9690", "greek", "χαίνω", "chainō", "chainō", "to gape wide", "stand agape, yawn", 0),
    ("H0157", "hebrew", "אָהֵב", "aheb", "a.hav", "to love: lover, friend", "H157. aheb verb love", 211),
    ("H0160", "hebrew", "אַהֲבָה", "ahabah", "a.ha.vah", "love", "H160. ahabah noun love", 40),
    ("H2617", "hebrew", "חֶ֫סֶד", "checed", "che.sed", "kindness; shame", "H2617. checed goodness", 247),
    ("H1136", "hebrew", "בֶּן־חֶ֫סֶד", "Ben-checed", "ben-che.sed", "Ben-hesed", "H1136. a name", 1),
    ("H2403", "hebrew", "חַטָּאת", "chatta'ah", "chat.tat", "sin: sin offering", "H2403. sin", 295),
    ("H2398", "hebrew", "חָטָא", "chata'", "cha.ta", "to sin", "H2398. miss, sin", 238),
    ("G3754", "greek", "ὅτι", "hoti", "hoti", "that/since: that, since", "**ὅτι** that", 1296),
    ("H6030", "hebrew", "עָנָה", "anah", "a.nah", "to answer; to sing", "H6030. answer", 316),
    ("G2433", "greek", "ἱλάσκομαι", "hilaskomai", "hilaskomai", "to propitiate", "**ἱλάσκομαι** appease", 2),
    ("G2434", "greek", "ἱλασμός", "hilasmos", "hilasmos", "propitiation", "**ἱλασμός** propitiation", 2),
    ("H3722", "hebrew", "כִּפֶּר", "kaphar", "ki.pher", "to atone; to cover",
     "H3722. kaphar verb Pi`el cover over, pacify, make propitiation; —", 102),
    ("H7676", "hebrew", "שַׁבָּת", "shabbath", "shab.bat", "Sabbath", f"H7676. sabbath {FILLER} propitiation", 111),
    ("H0430", "hebrew", "אֱלֹהִים", "elohim", "e.lo.him", "God", f"H430. elohim {FILLER} righteousness", 2603),
    ("H6666", "hebrew", "צְדָקָה", "tsedaqah", "tse.da.qah", "righteousness", "H6666. righteousness", 157),
    ("H6662", "hebrew", "צַדִּיק", "tsaddiyq", "tsad.diq", "righteous", "H6662. just, righteous", 206),
    ("H8451", "hebrew", "תּוֹרָה", "towrah", "to.rah", "instruction", "H8451. towrah direction, instruction, law", 219),
    ("H1881", "hebrew", "דָּת", "dath", "dat", "law", "H1881. dath decree, law", 21),
    ("H3618", "hebrew", "כַּלָּה", "kallah", "kal.lah", "daughter-in-law: bride", "H3618. daughter-in-law", 34),
    ("H1121", "hebrew", "בֵּן", "ben", "ben", "son: child", "H1121. ben son", 4941),
    ("H6629", "hebrew", "צֹאן", "tso'n", "tson", "flock", "H6629. small cattle", 274),
]


@pytest.fixture
async def db(tmp_path):
    path = tmp_path / "lexicon.db"
    conn = sqlite3.connect(path)
    create_schema(conn)
    conn.executemany(
        """INSERT INTO lexicon (strongs, language, word, transliteration, pronunciation,
               short_definition, full_definition, usage_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        LEXICON,
    )
    conn.commit()
    conn.close()
    database = StudyBibleDB(path)
    await database.connect()
    yield database
    await database.close()


async def _hits(db, query, language=None, limit=4):
    return [row["strongs"] for row in await db.search_lexicon(query, language=language, limit=limit)]


@pytest.mark.parametrize(
    ("spellings", "first"),
    [
        (("agape", "agapē", "AGAPE", "αγαπη"), "G0026"),
        (("hesed", "chesed", "ḥesed", "khesed", "checed"), "H2617"),
        (("ahav", "aheb"), "H0157"),
        (("kipper", "kaphar"), "H3722"),
        (("torah", "towrah"), "H8451"),
        (("tzedakah", "tsedaqah", "ṣedāqâ"), "H6666"),
    ],
)
async def test_any_spelling_of_a_transliteration_finds_the_entry_first(db, spellings, first):
    for spelling in spellings:
        assert (await _hits(db, spelling))[0] == first, spelling


async def test_a_transliteration_outranks_names_and_definition_mentions(db):
    # Before: 'agape' found only chainō ("stand agape"), 'hesed' only names.
    assert await _hits(db, "agape", "greek") == ["G0026", "G0027", "G9690"]
    assert await _hits(db, "hesed") == ["H2617", "H1136"]


async def test_love_keeps_its_order(db):
    assert await _hits(db, "love") == ["H0157", "G0025", "G0026", "G0027"]


async def test_an_english_word_is_matched_as_a_word(db):
    # 'sin' in 'since' and 'to sing' (hoti, anah) comes after the sin words.
    assert await _hits(db, "sin", limit=10) == ["H2403", "H2398", "G3754", "H6030"]
    # tso'n folds to 'son' but is no son.
    assert await _hits(db, "son", "hebrew") == ["H1121", "H6629"]


async def test_stems_and_lead_senses_outrank_deep_definition_mentions(db):
    # hilaskomai ("to propitiate") by stem, kaphar by its BDB lead sense; the
    # sabbath entry only mentions propitiation deep in its definition.
    assert await _hits(db, "propitiation") == ["G2434", "H3722", "G2433", "H7676"]
    assert await _hits(db, "righteousness", "hebrew") == ["H6666", "H6662", "H0430"]
    # torah's gloss is "instruction"; BDB's lead sense says "law".
    assert await _hits(db, "law", "hebrew") == ["H1881", "H8451", "H3618"]


def test_fold_transliteration():
    assert {fold_transliteration(s) for s in ("ḥesed", "hesed", "chesed", "khesed", "checed", "che.sed")} == {"hesed"}
    assert fold_transliteration("agapē") == fold_transliteration("agape") == "agape"
    assert fold_transliteration("towrah") == fold_transliteration("to.rah") == "tora"
    assert fold_transliteration("shabbath") == fold_transliteration("shab.bat")
    assert fold_transliteration("nephesh") == fold_transliteration("nefesh")


def test_word_forms_and_stems():
    assert {"love", "loves", "loved", "lover", "loving", "beloved"} <= word_forms("love")
    assert {"sinner", "sinful", "sins"} <= word_forms("sin")
    assert not {"since", "sing", "sinew"} & word_forms("sin")
    assert "kingdom" in word_forms("king") and "speaking" not in word_forms("king")
    assert english_stem("propitiation") == "propitiat"
    assert english_stem("righteousness") == "righteous"
    assert english_stem("love") is None


def test_index_treats_english_glosses_apart():
    index = LexiconIndex([
        ("H1121", "hebrew", "ben", "ben", "בֵּן", "son: child", 4941),
        ("H6629", "hebrew", "tso'n", "tson", "צֹאן", "flock", 274),
    ])
    assert index.is_gloss("son") and index.is_gloss("child", "hebrew")
    assert not index.is_gloss("tson")
    assert index.matches("son") == (["H6629"], [])
    assert index.gloss_matches("son") == ["H1121"]
