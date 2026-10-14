"""search_ancient_sources: name spellings, untranslated corpora, other-corpora hints, phrases.

The passages are invented test text, inserted directly with the search index
rebuilt from them.
"""

from __future__ import annotations

import re
import sqlite3

import pytest

from study_bible_mcp import server
from study_bible_mcp.database import (
    StudyBibleDB,
    create_schema,
    rebuild_ancient_search_index,
    spelling_key,
)

# (corpus, author, work_key, work_title, reference, sort_start, text, original_text)
PASSAGES = [
    ("josephus", "Flavius Josephus", "antiquities", "Jewish Antiquities", "Antiquities 1.180",
     1180, "Melchisedec, king of Solyma, received Abram (test text).", ""),
    ("josephus", "Flavius Josephus", "antiquities", "Jewish Antiquities", "Antiquities 1.181",
     1181, "The temple at Solyma was built later (test text).", ""),
    ("philo", "Philo of Alexandria", "legum-allegoriae-3", "Allegorical Interpretation 3",
     "Leg. 3.79", 3079, "God made Melchisedek the king of peace (test text).", ""),
    ("philo", "Philo of Alexandria", "legum-allegoriae-3", "Allegorical Interpretation 3",
     "Leg. 3.80", 3080, "Gabriel spoke to the man and his son (test text).", ""),
    # Scattered words come first by bm25 (shorter text), the phrase second.
    ("pseudepigrapha", "Anonymous", "1-enoch", "1 Enoch", "1 Enoch 46:1", 46001,
     "Of man, a son.", ""),
    ("pseudepigrapha", "Anonymous", "1-enoch", "1 Enoch", "1 Enoch 46:2", 46002,
     "And there I saw that Son of Man who has righteousness, with the Head of Days, "
     "and the angel went with me and showed me all the hidden things (test text).", ""),
    ("qumran", "Qumran community", "cd", "Damascus Document", "CD 12", 12000, "",
     "1 עד עמוד משיח אהרון וישראל"),
]


@pytest.fixture
async def search_db(tmp_path, monkeypatch):
    path = tmp_path / "ancient.db"
    conn = sqlite3.connect(path)
    create_schema(conn)
    conn.executemany(
        """INSERT INTO ancient_source_passages (corpus, author, work_key, work_title, reference,
               book_number, section_number, section_end, sort_start, sort_end, text,
               original_text, period_tags, edition, license, source_url)
           VALUES (?, ?, ?, ?, ?, 0, '', 0, ?, ?, ?, ?, 'roman', 'Test edition', 'CC BY 4.0',
                   'https://example.test')""",
        [
            (corpus, author, work_key, title, reference, start, start, text, original)
            for corpus, author, work_key, title, reference, start, text, original in PASSAGES
        ],
    )
    conn.executemany(
        """INSERT INTO lexicon (strongs, language, word, transliteration, short_definition,
               usage_count) VALUES (?, 'hebrew', ?, ?, ?, ?)""",
        [
            ("H4899", "מָשִׁיחַ", "mashiach", "messiah, anointed one", 39),
            ("H3068", "יְהוָה", "YHWH", "proper name, of deity", 6000),
        ],
    )
    rebuild_ancient_search_index(conn)
    conn.commit()
    conn.close()
    database = StudyBibleDB(path)
    await database.connect()
    monkeypatch.setattr(server, "db", database)
    yield database
    await database.close()


async def search(**arguments) -> str:
    response = await server.call_tool("search_ancient_sources", arguments)
    return response[0].text


def _headings(output: str) -> list[str]:
    return re.findall(r"^### (.+)$", output, re.MULTILINE)


def test_spelling_key_joins_name_variants():
    assert spelling_key("Melchizedek") == spelling_key("Melchisedec") == spelling_key("Melchisedek")
    assert spelling_key("Melchisedech") == spelling_key("Melchizedek")
    assert spelling_key("Caiaphas") == spelling_key("Kaiafas")
    assert spelling_key("Melchizedek") != spelling_key("Melchiel")


async def test_a_name_finds_other_translations_spellings(search_db):
    josephus = await search(query="Melchizedek")
    assert _headings(josephus) == ["Flavius Josephus, Antiquities 1.180"]
    assert "*Spelling variants also searched (melchizedek: melchisedec, melchisedek).*" in josephus
    every = await search(query="Melchizedek", corpus="all")
    assert sorted(_headings(every)) == ["Flavius Josephus, Antiquities 1.180", "Philo of Alexandria, Leg. 3.79"]
    # Variants combine with the other words of the query.
    assert _headings(await search(query="Melchizedek peace", corpus="all")) == [
        "Philo of Alexandria, Leg. 3.79"
    ]


async def test_an_exactly_spelled_name_gets_no_variant_note_without_variants(search_db):
    output = await search(query="Solyma temple")
    assert "Spelling variants" not in output
    assert _headings(output) == ["Flavius Josephus, Antiquities 1.181"]


async def test_english_query_on_an_untranslated_corpus_suggests_hebrew(search_db):
    output = await search(query="messiah", corpus="qumran")
    assert output == (
        "No Qumran passage contains any of the search terms (messiah). The Qumran corpus "
        "has no English translation: search it in Hebrew script, e.g. משיח (H4899, "
        "'messiah, anointed one')."
    )
    # With no lexicon gloss to offer, the corpus's own example query is suggested.
    fallback = await search(query="community", corpus="qumran")
    assert fallback.endswith("search it in Hebrew script, e.g. 'מורה הצדק'.")
    # The Hebrew itself is found.
    assert _headings(await search(query="משיח", corpus="qumran")) == ["Qumran community, CD 12"]


async def test_a_miss_in_one_corpus_names_the_corpora_that_match(search_db):
    output = await search(query="Gabriel")
    assert output == (
        "No Josephus passage contains any of the search terms (gabriel). Other corpora "
        "match (philo): retry with corpus='all'."
    )
    assert await search(query="nowhere") == (
        "No Josephus passage contains any of the search terms (nowhere)."
    )


async def test_a_phrase_ranks_above_scattered_words(search_db):
    # Without a phrase, the shorter passage ranks first.
    scattered = await search(query="son man", corpus="pseudepigrapha")
    assert _headings(scattered) == ["Anonymous, 1 Enoch 46:1", "Anonymous, 1 Enoch 46:2"]
    phrase = await search(query="son of man", corpus="pseudepigrapha")
    assert _headings(phrase) == ["Anonymous, 1 Enoch 46:2", "Anonymous, 1 Enoch 46:1"]
    assert _headings(await search(query="son of man", corpus="pseudepigrapha", limit=1)) == [
        "Anonymous, 1 Enoch 46:2"
    ]
