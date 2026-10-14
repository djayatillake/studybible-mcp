"""A small synthetic database for the tool-handler tests.

Every row is hand-written except the generated "filler" rows, which exist only
to push a list-returning tool past its default cap. Texts are invented test
data, not quotations. The vector tables are added only when the sqlite-vec
extension loads; ``build_fixture_db`` returns whether it did.
"""

from __future__ import annotations

import json
import math
import sqlite3
import struct
from pathlib import Path

from study_bible_mcp.database import create_schema, create_vector_tables


def _words(strongs: str, word: str, gloss: str, morph: str) -> str:
    return json.dumps(
        [{"word": word, "transliteration": "", "strongs": strongs, "morph": morph, "gloss": gloss}],
        ensure_ascii=False,
    )


# --- Lexicon ---------------------------------------------------------------

# (strongs, language, word, transliteration, short, full, usage_count, extras)
LEXICON = [
    ("G0025", "greek", "ἀγαπάω", "agapaō", "to love", "To love, to value, to esteem.", 143, {}),
    (
        "G0026", "greek", "ἀγάπη", "agapē", "love, goodwill",
        "Love, esteem, affection; in the NT the love of God shown in Christ.", 116,
        {
            "etymology": "From agapaō.",
            "semantic_domain": json.dumps(["love", "affection"]),
            "related_words": json.dumps([{"strongs": "G0025", "word": "ἀγαπάω", "gloss": "to love"}]),
            "abbott_smith_def": "Abbott-Smith test entry for agapē.",
        },
    ),
    ("G5368", "greek", "φιλέω", "phileō", "to love, be fond of", "To be a friend to, to be fond of.", 25, {}),
    ("H0157", "hebrew", "אָהַב", "ahav", "to love", "To love, of human and divine love.", 217, {}),
    ("H0430", "hebrew", "אֱלֹהִים", "elohim", "God, gods", "God; also gods, divine beings.", 2600, {}),
]

# Twelve entries matching "lampstand", for the search_lexicon default cap (4).
LAMPSTAND_FILLER = [
    (f"G{9000 + n:04d}", "greek", f"λυχνία{n}", f"luchnia{n}", f"lampstand (filler {n:02d})",
     f"Synthetic lampstand entry {n:02d}.", 100 - n, {})
    for n in range(1, 13)
]

# --- Verses ----------------------------------------------------------------

# 1 John 4:1-21 all carry G0026, for the search_by_strongs (4) and
# word_study example-passage (5) caps.
VERSES = [
    ("Jhn.3.16", "Jhn", 3, 16, "For God so loved the world (test text).", "οὕτως γὰρ ἠγάπησεν",
     _words("G0025", "ἠγάπησεν", "loved", "V-AAI-3S")),
    ("Jhn.3.17", "Jhn", 3, 17, "God did not send the Son to condemn (test text).", "οὐ γὰρ ἀπέστειλεν",
     _words("G0649", "ἀπέστειλεν", "sent", "V-AAI-3S")),
    ("Gen.22.1", "Gen", 22, 1, "After these things God tested Abraham (test text).", "וַיְהִי אַחַר",
     _words("H0430", "הָאֱלֹהִים", "God", "HNcmpa")),
    ("Gen.22.2", "Gen", 22, 2, "Take your son to the land of Moriah (test text).", "וַיֹּאמֶר קַח־נָא",
     _words("H1121", "בִּנְךָ", "your son", "HNcmsc")),
    # Stored with English(Hebrew) split numbering, as in the built database.
    ("Gen.32.1(32.2)", "Gen", 32, 1, "Jacob went on his way (test text).", "וְיַעֲקֹב הָלַךְ",
     _words("H3290", "וְיַעֲקֹב", "Jacob", "HNpm")),
] + [
    (f"1Jn.4.{v}", "1Jn", 4, v, f"Beloved, love is from God (test text 1 John 4:{v}).", "ἀγάπη",
     _words("G0026", "ἀγάπη", "love", "N-NSF"))
    for v in range(1, 22)
]

# BSB rows, loaded only by build_fixture_db(bsb=True). Gen 22:2 and 1 John 4:3
# have none, so they fall back to the marked gloss; Gen.32.1 is matched by the
# split-numbered row 'Gen.32.1(32.2)'. 1 John 4:1 is long enough to be cut in
# a similar-passage preview.
BSB_VERSES = [
    ("Jhn.3.16", "Jhn", 3, 16, "For God so loved the world that He gave His Son (BSB test text)."),
    ("Jhn.3.17", "Jhn", 3, 17, "For God did not send His Son to condemn (BSB test text)."),
    ("Gen.22.1", "Gen", 22, 1, "Some time later God tested Abraham (BSB test text)."),
    ("Gen.32.1", "Gen", 32, 1, "Jacob also went on his way (BSB test text)."),
    ("1Jn.4.1", "1Jn", 4, 1, "Beloved, test the spirits (BSB test text 1 John 4:1). " * 12),
] + [
    (f"1Jn.4.{v}", "1Jn", 4, v, f"Beloved, let us love one another (BSB test text 1 John 4:{v}).")
    for v in range(2, 22) if v != 3
]

# --- Names and ACAI ----------------------------------------------------------

NAMES = [
    ("David", "דָּוִד", "person", "Youngest son of Jesse; king of Israel.",
     json.dumps(["1Sa.16.13", "2Sa.5.3"]), json.dumps({"father": "Jesse", "son": "Solomon"})),
    ("City of David", None, "place", "The stronghold of Zion taken by David.",
     json.dumps(["2Sa.5.7"]), json.dumps({})),
    ("Jerusalem", "יְרוּשָׁלַםִ", "place", "City of the temple.",
     json.dumps(["Jos.10.1"]), json.dumps({})),
]

ACAI = [
    ("david", "person", "David", "male", "Second king of Israel.", json.dumps(["king", "shepherd"]),
     json.dumps(["son of Jesse"]), 1118, 120),
]

# --- Morphology --------------------------------------------------------------

# (code, language, parsing, part_of_speech, person, number, tense, voice, mood, case, gender)
MORPHOLOGY = [
    ("V-AAI-3S", "greek", "Verb, Aorist, Active, Indicative, 3rd person, Singular",
     "Verb", "3rd", "Singular", "Aorist", "Active", "Indicative", None, None),
    ("N-GSF", "greek", "Noun, Genitive, Singular, Feminine",
     "Noun", None, "Singular", None, None, None, "Genitive", "Feminine"),
    ("HVqp3ms", "hebrew", "Hebrew Verb, Qal, Perfect, 3rd person, masculine, singular",
     "Verb", "3rd", "singular", "Perfect", "Qal", None, None, "masculine"),
]

# --- Cross-references --------------------------------------------------------

# John 3:16 is signal-rich: nine rows at tier 2 or above plus two tier-1 TSK
# rows. In default order (tier, then strength score, then TSK votes):
XREF_JOHN_3_16_ORDER = [
    "Rom.5.8",    # tsk 600 votes: tier 3, score 9
    "1Jn.4.10",   # tsk 150: tier 3, score 7, 150 votes
    "1Jn.4.9",    # ch rel 3: tier 3, score 7, also 40 TSK votes
    "Rev.21.6",   # gage parallel: tier 3, score 7
    "Rom.4.18",   # burnett: tier 2, score 7
    "Rom.8.32",   # tsk 60: tier 2, score 6
    "Heb.2.9",    # tsk 30: tier 2, score 5
    "Eph.2.4",    # tsk 25: tier 2, score 5
    "Rev.22.17",  # gage chiastic: tier 2, score 3
    "Tit.3.4",    # tsk 12: tier 1
    "Isa.9.6",    # tsk 3: tier 1
]

# (source, target, type, relevance, note); inserted out of order on purpose.
CROSS_REFERENCES = [
    ("Jhn.3.16", "Isa.9.6", "tsk", 3, None),
    ("Jhn.3.16", "Eph.2.4", "tsk", 25, None),
    ("Jhn.3.16", "Rev.22.17", "gage", 1, "Water of life (chiastic echo)"),
    ("Jhn.3.16", "Tit.3.4", "tsk", 12, None),
    ("Jhn.3.16", "Rom.4.18", "burnett", 5, "JSPL 5.2 step 3"),
    ("Jhn.3.16", "1Jn.4.9", "tsk", 40, None),
    ("Jhn.3.16", "Heb.2.9", "tsk", 30, None),
    ("Jhn.3.16", "Rom.8.32", "tsk", 60, None),
    ("Jhn.3.16", "1Jn.4.9", "ch", 3, None),
    ("Jhn.3.16", "Rev.21.6", "gage", 3, "Gift of life (parallel)"),
    ("Jhn.3.16", "1Jn.4.10", "tsk", 150, None),
    ("Jhn.3.16", "Rom.5.8", "tsk", 600, None),
    # Ruth 1:1 is signal-poor: only tier-1 rows, which are kept.
    ("Rut.1.1", "Jdg.21.25", "tsk", 4, None),
    ("Rut.1.1", "Gen.12.10", "tsk", 2, None),
]

THEMATIC_REFERENCES = [
    ("atonement", "Lev 16:30", "Cleansing on the Day of Atonement"),
    ("atonement", "Rom 3:25", "Christ set forth as a propitiation"),
]

# --- Theographic graph -------------------------------------------------------

# (id, name, also_called, gender, birth_year, birth_place, death_place, description)
GRAPH_PEOPLE = [
    ("terah_1", "Terah", None, "male", None, None, None, None),
    ("abraham_1", "Abraham", "Abram", "male", -2166, "ur_1", "hebron_1",
     "Patriarch called out of Ur (test description)."),
    ("sarah_1", "Sarah", "Sarai", "female", None, None, "hebron_1", None),
    ("isaac_1", "Isaac", None, "male", -2066, None, None, None),
    ("rebekah_1", "Rebekah", None, "female", None, None, None, None),
    ("jacob_1", "Jacob", "Israel", "male", -2006, None, None, None),
    ("esau_1", "Esau", "Edom", "male", -2006, None, None, None),
    ("judah_1", "Judah", None, "male", None, None, None, None),
    ("perez_1", "Perez", None, "male", None, None, None, None),
    ("hezron_1", "Hezron", None, "male", None, None, None, None),
    ("melchizedek_1", "Melchizedek", None, "male", None, None, None, None),
]

GRAPH_FAMILY_EDGES = [
    ("terah_1", "abraham_1", "father_of"),
    ("abraham_1", "isaac_1", "father_of"),
    ("sarah_1", "isaac_1", "mother_of"),
    ("abraham_1", "sarah_1", "partner_of"),
    ("isaac_1", "rebekah_1", "partner_of"),
    ("isaac_1", "jacob_1", "father_of"),
    ("isaac_1", "esau_1", "father_of"),
    ("rebekah_1", "jacob_1", "mother_of"),
    ("jacob_1", "esau_1", "sibling_of"),
    ("jacob_1", "judah_1", "father_of"),
    ("judah_1", "perez_1", "father_of"),
    ("perez_1", "hezron_1", "father_of"),
]

# (id, name, latitude, longitude, feature_type)
GRAPH_PLACES = [
    ("ur_1", "Ur", 30.9625, 46.1031, "city"),
    ("haran_1", "Haran", 36.8650, 39.0317, "city"),
    ("moriah_1", "Moriah", 31.7780, 35.2354, "mountain"),
    ("hebron_1", "Hebron", 31.5326, 35.0998, "city"),
    ("zoar_1", "Zoar", None, None, "city"),
    ("sharon_1", "Sharon", 32.4, 34.9, "region"),
    # "Mount Sinai" precedes "Ai" and contains "ai".
    ("sinai_1", "Mount Sinai", 28.5392, 33.9750, "mountain"),
    ("ai_1", "Ai", 31.9167, 35.2614, "city"),
]

# (id, title, start_year, sort_key); inserted out of chronological order.
GRAPH_EVENTS = [
    ("e3", "Death of Abraham", -1991, 30.0),
    ("e1", "Call of Abraham", -2091, 10.0),
    ("e2", "Binding of Isaac", -2054, 20.0),
]

GRAPH_PERSON_EVENTS = [
    ("abraham_1", "e1"), ("abraham_1", "e2"), ("abraham_1", "e3"), ("isaac_1", "e2"),
]

GRAPH_EVENT_PLACES = [("e1", "haran_1"), ("e2", "moriah_1"), ("e3", "hebron_1")]

# Theographic verse refs use its own book codes ("John", not "Jhn").
GRAPH_VERSE_MENTIONS = [
    ("Gen.22.1", "person", "abraham_1"),
    ("Gen.22.1", "event", "e2"),
    ("Gen.22.2", "person", "isaac_1"),
    ("Gen.22.2", "place", "moriah_1"),
    ("John.8.58", "person", "abraham_1"),
    ("Song.2.1", "place", "sharon_1"),
]

# --- Aquifer -----------------------------------------------------------------

LONG_ARTICLE = "The tabernacle was a portable sanctuary. " * 150  # > 4000 characters

# (content_id, resource_type, title, book, start_ref, end_ref, chapter_start,
#  content_plain, is_range)
AQUIFER = [
    (1, "study_notes", "John 3:16", "Jhn", "43003016", "43003016", 3,
     "God's love for the world is the motive for sending the Son (test note).", 0),
    (2, "translation_notes_uw", "John 3:14-18", "Jhn", "43003014", "43003018", 3,
     "Lifted up refers to the cross (test translation note).", 1),
    (3, "study_notes", "John 3:1-8", "Jhn", "43003001", "43003008", 3,
     "Nicodemus came to Jesus by night (test note).", 1),
    (4, "study_notes", "Song of Solomon 2:1", "Sng", "22002001", "22002001", 2,
     "The rose of Sharon (test note).", 0),
    (5, "study_notes", "1 John 4:8", "1Jn", "62004008", "62004008", 4,
     "God is love (test note).", 0),
    (10, "dictionary", "Covenant", None, None, None, None,
     "A covenant is a binding agreement; God made one with Abraham (test article).", 0),
    (11, "dictionary", "Abraham", None, None, None, None,
     "Abraham, father of the faithful (test article).", 0),
    (12, "dictionary", "Tabernacle", None, None, None, None, LONG_ARTICLE, 0),
    (40, "key_terms", "Atonement", None, None, None, None,
     "Atonement is the reconciling of God and people through sacrifice (test key term).", 0),
    (41, "key_terms", "Grace", None, None, None, None,
     "Grace is God's undeserved favour (test key term).", 0),
] + [
    # Twelve articles matching "jubilee", for the dictionary search cap (10).
    (100 + n, "dictionary", f"Jubilee note {n:02d}", None, None, None, None,
     f"Synthetic jubilee article {n:02d}.", 0)
    for n in range(1, 13)
]

# --- ANE context -------------------------------------------------------------

# (id, dimension, dimension_label, title, summary, detail, period, period_label,
#  key_references, mappings [(book, chapter_start, chapter_end)])
ANE_ENTRIES = [
    ("cov_001", "legal_covenant", "Legal & Covenant", "Covenant-cutting ritual",
     "Walking between halves of animals bound the parties (test summary).",
     "Detail: self-maledictory oath (test detail).", "patriarchal", "Patriarchal Period",
     ["Gen 15:9-21"], [("Gen", 15, 15)]),
    ("rel_001", "religious_practices", "Religious Practices", "Smoking firepot theophany",
     "Fire and smoke mark the divine presence (test summary).",
     "Detail: fire theophanies (test detail).", "patriarchal", "Patriarchal Period",
     ["Gen 15:17"], [("Gen", None, None)]),
    ("cos_001", "cosmology_worldview", "Cosmology & Worldview", "Three-tier cosmos",
     "Heavens, earth, and underworld (test summary).",
     "Detail: the raqia as a solid dome (test detail).", "patriarchal", "Patriarchal Period",
     ["Gen 1:6-8"], [("Gen", None, None)]),
    ("soc_001", "social_structure", "Social Structure", "Debt slavery",
     "Bond service for debt (test summary).", "Detail: release in the seventh year.",
     "exodus_conquest", "Exodus & Conquest", ["Exo 21:2"], [("Gen", None, None)]),
] + [
    # Thirty-two entries on Leviticus, for the get_ane_context cap (30).
    (f"lev_{n:03d}", "religious_practices", "Religious Practices", f"Levitical filler {n:02d}",
     f"Synthetic Levitical entry {n:02d}.", None, "exodus_conquest", "Exodus & Conquest",
     ["Lev 16:1"], [("Lev", 1, 27)])
    for n in range(1, 33)
]

# --- Torah Weave -------------------------------------------------------------

TORAH_WEAVE_UNIT = (1, "Gen", "Genesis", 1, "Creation", "Genesis 1:1-2:3", "1:1-2:3",
                    "3x2", 0, 0, 6, "F", 7)

# (label, row, column, subdivision, chapter_start, verse_start, chapter_end, verse_end)
TORAH_WEAVE_CELLS = [
    ("1A", 1, "A", None, 1, 1, 1, 5),
    ("1B", 1, "B", None, 1, 6, 1, 8),
    ("2A", 2, "A", None, 1, 9, 1, 13),
    ("2B", 2, "B", None, 1, 14, 1, 19),
    ("3A", 3, "A", None, 1, 20, 1, 23),
    ("3Ba", 3, "B", "a", 1, 24, 1, 28),
    ("3Bb", 3, "B", "b", 1, 29, 2, 3),
]

# --- Vectors -----------------------------------------------------------------

VECTOR_DIMENSIONS = 1536  # create_vector_tables declares FLOAT[1536]


def _unit_vector(cosine: float) -> bytes:
    """A unit vector whose cosine similarity to the first axis is ``cosine``."""
    values = [0.0] * VECTOR_DIMENSIONS
    values[0] = cosine
    values[1] = math.sqrt(max(0.0, 1.0 - cosine * cosine))
    return struct.pack(f"{VECTOR_DIMENSIONS}f", *values)


def similarity_for(verse: int) -> float:
    """Similarity of the 1 John 4:<verse> passage to John 3:16: falls as the verse rises."""
    return round(0.95 - 0.04 * (verse - 1), 2)


def _load_sqlite_vec(conn: sqlite3.Connection) -> bool:
    try:
        import sqlite_vec

        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        return True
    except Exception:
        return False


def build_fixture_db(path: Path, bsb: bool = False) -> bool:
    """Create the fixture database at ``path``; return True if vectors were added.

    ``bsb`` loads BSB_VERSES; without it bsb_verses is empty and the verse
    tools show the STEPBible gloss.
    """
    conn = sqlite3.connect(path)
    create_schema(conn)
    if bsb:
        conn.executemany(
            "INSERT INTO bsb_verses (reference, book, chapter, verse, text) VALUES (?, ?, ?, ?, ?)",
            BSB_VERSES,
        )

    conn.executemany(
        """INSERT INTO lexicon (strongs, language, word, transliteration, short_definition,
               full_definition, usage_count, etymology, semantic_domain, related_words,
               abbott_smith_def)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (s, lang, w, tr, short, full, usage, x.get("etymology"), x.get("semantic_domain"),
             x.get("related_words"), x.get("abbott_smith_def"))
            for s, lang, w, tr, short, full, usage, x in LEXICON + LAMPSTAND_FILLER
        ],
    )
    conn.executemany(
        """INSERT INTO verses (reference, book, chapter, verse, text_english, text_original, word_data)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        VERSES,
    )
    conn.executemany(
        """INSERT INTO names (name, name_original, type, description, refs, relationships)
           VALUES (?, ?, ?, ?, ?, ?)""",
        NAMES,
    )
    conn.executemany(
        """INSERT INTO acai_entities (id, entity_type, name, gender, description, roles,
               referred_to_as, reference_count, speeches_count)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ACAI,
    )
    conn.executemany(
        """INSERT INTO morphology (code, language, parsing, part_of_speech, person, number,
               tense, voice, mood, case_value, gender)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        MORPHOLOGY,
    )
    conn.executemany(
        "INSERT INTO cross_references (source, target, type, relevance, note) VALUES (?, ?, ?, ?, ?)",
        CROSS_REFERENCES,
    )
    conn.executemany(
        "INSERT INTO thematic_references (theme, reference, note) VALUES (?, ?, ?)",
        THEMATIC_REFERENCES,
    )

    conn.executemany(
        """INSERT INTO graph_people (id, name, also_called, gender, birth_year, birth_place_id,
               death_place_id, description)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        GRAPH_PEOPLE,
    )
    conn.executemany(
        "INSERT INTO graph_family_edges (from_person_id, to_person_id, relationship_type) VALUES (?, ?, ?)",
        GRAPH_FAMILY_EDGES,
    )
    conn.executemany(
        "INSERT INTO graph_places (id, name, latitude, longitude, feature_type) VALUES (?, ?, ?, ?, ?)",
        GRAPH_PLACES,
    )
    conn.executemany(
        "INSERT INTO graph_events (id, title, start_year, sort_key) VALUES (?, ?, ?, ?)",
        GRAPH_EVENTS,
    )
    conn.executemany(
        "INSERT INTO graph_person_event_edges (person_id, event_id) VALUES (?, ?)",
        GRAPH_PERSON_EVENTS,
    )
    conn.executemany(
        "INSERT INTO graph_event_place_edges (event_id, place_id) VALUES (?, ?)",
        GRAPH_EVENT_PLACES,
    )
    conn.executemany(
        "INSERT INTO graph_verse_mentions (verse_ref, entity_type, entity_id) VALUES (?, ?, ?)",
        GRAPH_VERSE_MENTIONS,
    )

    conn.executemany(
        """INSERT INTO aquifer_content (content_id, resource_type, title, book, start_ref, end_ref,
               chapter_start, content, content_plain, is_range)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (cid, rtype, title, book, start, end, chapter, f"<p>{plain}</p>", plain, is_range)
            for cid, rtype, title, book, start, end, chapter, plain, is_range in AQUIFER
        ],
    )

    for (entry_id, dimension, dimension_label, title, summary, detail, period, period_label,
         key_references, mappings) in ANE_ENTRIES:
        conn.execute(
            """INSERT INTO ane_entries (id, dimension, dimension_label, title, summary, detail,
                   period, period_label, key_references)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (entry_id, dimension, dimension_label, title, summary, detail, period, period_label,
             json.dumps(key_references)),
        )
        conn.executemany(
            "INSERT INTO ane_book_mappings (entry_id, book, chapter_start, chapter_end) VALUES (?, ?, ?, ?)",
            [(entry_id, book, start, end) for book, start, end in mappings],
        )

    conn.execute(
        """INSERT INTO torah_weave_units (id, book, book_full, unit_number, title, verses,
               verse_range, format, irregular, is_unique, cell_count, type,
               cell_count_with_subdivisions)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        TORAH_WEAVE_UNIT,
    )
    conn.executemany(
        """INSERT INTO torah_weave_cells (unit_id, cell_label, row_num, column_letter, subdivision,
               book, verse_range, chapter_start, verse_start, chapter_end, verse_end,
               sort_start, sort_end)
           VALUES (1, ?, ?, ?, ?, 'Gen', ?, ?, ?, ?, ?, ?, ?)""",
        [
            (label, row, column, sub, f"{c1}:{v1}-{c2}:{v2}", c1, v1, c2, v2,
             c1 * 1000 + v1, c2 * 1000 + v2)
            for label, row, column, sub, c1, v1, c2, v2 in TORAH_WEAVE_CELLS
        ],
    )

    ids = dict(conn.execute("SELECT reference, id FROM verses"))
    # One passage per verse of 1 John 4, plus John 3:16-17, which contains the
    # source verse and must be excluded however similar it is.
    passages = [
        (f"1Jn.4.{v}", f"1Jn.4.{v}", "1Jn", ids[f"1Jn.4.{v}"], ids[f"1Jn.4.{v}"],
         ("Long passage text. " * 40) if v == 1 else f"Synthetic passage 1 John 4:{v}.", 1)
        for v in range(1, 22)
    ]
    passages.append(("Jhn.3.16", "Jhn.3.17", "Jhn", ids["Jhn.3.16"], ids["Jhn.3.17"],
                     "John 3:16-17 passage (contains the source verse).", 2))
    conn.executemany(
        """INSERT INTO passages (reference_start, reference_end, book, start_verse_id, end_verse_id,
               text_combined, verse_count)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        passages,
    )

    vectors = _load_sqlite_vec(conn)
    if vectors:
        create_vector_tables(conn)
        conn.execute(
            "INSERT INTO verse_vectors (verse_id, embedding) VALUES (?, ?)",
            (ids["Jhn.3.16"], _unit_vector(1.0)),
        )
        for passage_id, reference_start in conn.execute(
            "SELECT id, reference_start FROM passages"
        ).fetchall():
            cosine = 1.0 if reference_start == "Jhn.3.16" else similarity_for(
                int(reference_start.rsplit(".", 1)[1])
            )
            conn.execute(
                "INSERT INTO passage_vectors (passage_id, embedding) VALUES (?, ?)",
                (passage_id, _unit_vector(cosine)),
            )

    conn.commit()
    conn.close()
    return vectors
