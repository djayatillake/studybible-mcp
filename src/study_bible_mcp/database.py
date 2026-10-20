"""
Database layer for the Study Bible MCP server.

Uses SQLite with async access via aiosqlite.
"""

import asyncio
import contextlib
import contextvars
import difflib
import heapq
import json
import logging
import math
import re
import sqlite3
import struct
import unicodedata
from pathlib import Path
from typing import Any

import aiosqlite

from .lexicon_search import LexiconIndex, english_stem
from .morphology import morphology_lookups
from .parsers.biblical_versions import (
    BRENTON_GREEK_SOURCE_URL,
    BRENTON_TRANSLATION_NOTE,
    KJV_APOCRYPHA_NOTE,
    KJV_APOCRYPHA_TRANSLATION_LABEL,
    LXX_BOOK_CODES,
    LXX_LICENSE,
    LXX_SOURCE_URL,
    LXX_TRANSLATION_LABEL,
    MT_BOOK_CODES,
    MT_EDITION,
    MT_LICENSE,
    MT_SOURCE_URL,
    MT_TRANSLATION_LABEL,
    MT_VERSIFICATION_METHOD,
    apocrypha_name,
    expand_lxx_morphology,
    is_kjv_apocrypha,
)

logger = logging.getLogger("study-bible-mcp")

# Canonical book abbreviation map — used by _normalize_reference() and importable by server.py
BOOK_ABBREV_MAP = {
    "genesis": "Gen", "gen": "Gen",
    "exodus": "Exo", "exod": "Exo", "ex": "Exo",
    "leviticus": "Lev", "lev": "Lev",
    "numbers": "Num", "num": "Num",
    "deuteronomy": "Deu", "deut": "Deu", "dt": "Deu",
    "joshua": "Jos", "josh": "Jos",
    "judges": "Jdg", "judg": "Jdg",
    "ruth": "Rut",
    "1 samuel": "1Sa", "1sam": "1Sa", "1 sam": "1Sa",
    "2 samuel": "2Sa", "2sam": "2Sa", "2 sam": "2Sa",
    "1 kings": "1Ki", "1kgs": "1Ki", "1 kgs": "1Ki",
    "2 kings": "2Ki", "2kgs": "2Ki", "2 kgs": "2Ki",
    "1 chronicles": "1Ch", "1chr": "1Ch", "1 chr": "1Ch",
    "2 chronicles": "2Ch", "2chr": "2Ch", "2 chr": "2Ch",
    "ezra": "Ezr",
    "nehemiah": "Neh", "neh": "Neh",
    "esther": "Est", "esth": "Est",
    "job": "Job",
    "psalms": "Psa", "psalm": "Psa", "ps": "Psa",
    "proverbs": "Pro", "prov": "Pro", "pr": "Pro",
    "ecclesiastes": "Ecc", "eccl": "Ecc",
    "song of solomon": "Sng", "song of songs": "Sng", "song": "Sng", "sos": "Sng",
    "isaiah": "Isa", "isa": "Isa",
    "jeremiah": "Jer", "jer": "Jer",
    "lamentations": "Lam", "lam": "Lam",
    "ezekiel": "Ezk", "ezek": "Ezk", "eze": "Ezk",
    "daniel": "Dan", "dan": "Dan",
    "hosea": "Hos", "hos": "Hos",
    "joel": "Jol",
    "amos": "Amo",
    "obadiah": "Oba", "obad": "Oba", "ob": "Oba",
    "jonah": "Jon",
    "micah": "Mic", "mic": "Mic",
    "nahum": "Nam", "nah": "Nam",
    "habakkuk": "Hab", "hab": "Hab",
    "zephaniah": "Zep", "zeph": "Zep",
    "haggai": "Hag", "hag": "Hag",
    "zechariah": "Zec", "zech": "Zec",
    "malachi": "Mal", "mal": "Mal",
    "matthew": "Mat", "matt": "Mat", "mt": "Mat",
    "mark": "Mrk", "mk": "Mrk",
    "luke": "Luk", "lk": "Luk",
    "john": "Jhn", "jn": "Jhn",
    "acts": "Act",
    "romans": "Rom", "rom": "Rom",
    "1 corinthians": "1Co", "1cor": "1Co", "1 cor": "1Co",
    "2 corinthians": "2Co", "2cor": "2Co", "2 cor": "2Co",
    "galatians": "Gal", "gal": "Gal",
    "ephesians": "Eph", "eph": "Eph",
    "philippians": "Php", "phil": "Php",
    "colossians": "Col", "col": "Col",
    "1 thessalonians": "1Th", "1thess": "1Th", "1 thess": "1Th",
    "2 thessalonians": "2Th", "2thess": "2Th", "2 thess": "2Th",
    "1 timothy": "1Ti", "1tim": "1Ti", "1 tim": "1Ti",
    "2 timothy": "2Ti", "2tim": "2Ti", "2 tim": "2Ti",
    "titus": "Tit",
    "philemon": "Phm", "philem": "Phm", "phlm": "Phm",
    "hebrews": "Heb", "heb": "Heb",
    "james": "Jas", "jas": "Jas",
    "1 peter": "1Pe", "1pet": "1Pe", "1 pet": "1Pe",
    "2 peter": "2Pe", "2pet": "2Pe", "2 pet": "2Pe",
    "1 john": "1Jn", "1jn": "1Jn",
    "2 john": "2Jn", "2jn": "2Jn",
    "3 john": "3Jn", "3jn": "3Jn",
    "jude": "Jud",
    "revelation": "Rev", "rev": "Rev",
    "tobit": "Tob", "tob": "Tob",
    "judith": "Jdt", "jdt": "Jdt",
    "wisdom": "Wis", "wisdom of solomon": "Wis", "wis": "Wis",
    "sirach": "Sir", "ecclesiasticus": "Sir", "sir": "Sir",
    "baruch": "Bar", "bar": "Bar",
    "1 maccabees": "1Ma", "1macc": "1Ma", "1 macc": "1Ma",
    "2 maccabees": "2Ma", "2macc": "2Ma", "2 macc": "2Ma",
    "3 maccabees": "3Ma", "3macc": "3Ma", "3 macc": "3Ma",
    "4 maccabees": "4Ma", "4macc": "4Ma", "4 macc": "4Ma",
    "1 esdras": "1Es", "1esd": "1Es", "1 esd": "1Es",
    "prayer of manasseh": "Man", "manasseh": "Man",
    "psalms of solomon": "Pss", "psalm of solomon": "Pss",
    "greek esther": "EsG", "esther greek": "EsG",
    "letter of jeremiah": "Lje", "epistle of jeremiah": "Lje",
    "susanna": "Sus", "bel and the dragon": "Bel",
    "odes": "Ode",
    "2 esdras": "2Es", "2esd": "2Es", "2 esd": "2Es",
}
_BOOK_CODES_LOWER = {code.lower(): code for code in BOOK_ABBREV_MAP.values()}

_NT_BOOKS = frozenset({
    "Mat", "Mrk", "Luk", "Jhn", "Act", "Rom", "1Co", "2Co", "Gal", "Eph",
    "Php", "Col", "1Th", "2Th", "1Ti", "2Ti", "Tit", "Phm", "Heb", "Jas",
    "1Pe", "2Pe", "1Jn", "2Jn", "3Jn", "Jud", "Rev",
})
_MT_BOOKS = frozenset(MT_BOOK_CODES.values())
_LXX_ONLY_BOOKS = frozenset(LXX_BOOK_CODES.values()) - _MT_BOOKS
_HEBREW_NUMBERING_RE = re.compile(r"\((\d+)\.(\d+)\)$")
# A `verses` reference with a second numbering after the English one:
# English(Hebrew) in the OT ('Gen.32.1(32.2)'), and in the NT the Greek
# edition's verse with its KJV/English number in brackets ('Mat.17.15[17.14]')
# or another numbering in braces ('Jhn.7.53{8.1}').
_SPLIT_REFERENCE_RE = re.compile(r"^([^.]+)\.(\d+)\.(\d+)([(\[{])(\d+)\.(\d+)[)\]}]$")


def _source_number(row: dict) -> tuple[str | None, str]:
    """A `verses` row's own numbering: ('Hebrew' | 'Greek' | None, 'chapter.verse').

    None marks a plain reference, numbered alike in English.
    """
    match = _SPLIT_REFERENCE_RE.match(row["reference"])
    if not match:
        return None, ".".join(row["reference"].split(".")[1:])
    _, chapter, verse, bracket, other_chapter, other_verse = match.groups()
    if bracket == "(":
        return "Hebrew", f"{other_chapter}.{other_verse}"
    return "Greek", f"{chapter}.{verse}"


def _join_numbers(numbers: list[str]) -> str:
    """'51.1', '51.2' -> '51.1–2'; '20.42', '21.1' -> '20.42, 21.1'."""
    if len(numbers) > 1 and len({number.split(".")[0] for number in numbers}) == 1:
        verses = [int(number.split(".")[1]) for number in numbers]
        if verses == list(range(verses[0], verses[0] + len(verses))):
            return f"{numbers[0]}–{verses[-1]}"
    return ", ".join(numbers)


def verse_label(rows: list[dict]) -> str:
    """Heading for an English verse made of ``rows`` (one or more `verses` rows).

    The English (BSB) reference comes first, then any other numbering of the
    Hebrew or Greek text it shows: 'Psa.51 superscription (Hebrew Psa.51.1–2)',
    '2Co.13.14 (Greek 2Co.13.13)', '3Jn.1.14 (Greek 3Jn.1.14–15)'. A single
    English(Hebrew) row keeps its reference ('Psa.40.6(40.7)').
    """
    first = rows[0]
    english = first.get("english_reference") or f"{first['book']}.{first['chapter']}.{first['verse']}"
    book, chapter, verse = english.split(".")
    numbered = [_source_number(row) for row in rows]
    language = next((kind for kind, _ in numbered if kind), None)
    numbers = list(dict.fromkeys(number for _, number in numbered))
    if verse == "0":
        label = f"{book}.{chapter} superscription"
        return f"{label} (Hebrew {book}.{_join_numbers(numbers)})" if language else label
    if len(rows) == 1 and language == "Hebrew":
        return first["reference"]
    if language is None or numbers == [f"{chapter}.{verse}"]:
        return english
    return f"{english} ({language} {book}.{_join_numbers(numbers)})"


def merge_english_verses(rows: list[dict]) -> list[dict]:
    """Merge consecutive rows of one English verse into one row.

    Rows carrying ``english_reference`` (see ``StudyBibleDB.attach_bsb_text``)
    that share it, such as a Psalm's two Hebrew superscription verses or a
    Greek fragment the English counts with the next verse, become one row:
    the row carrying the BSB text, with every row's original text and words
    in order and a ``label`` naming their numbering. Other rows pass through.
    """
    merged: list[dict] = []
    group: list[dict] = []

    def flush() -> None:
        if not group:
            return
        if len(group) == 1:
            merged.append(group[0])
        else:
            base = dict(next((row for row in group if row.get("text_bsb")), group[0]))
            base["text_original"] = " ".join(
                row["text_original"] for row in group if row.get("text_original")
            ) or None
            base["text_english"] = " ".join(row["text_english"] for row in group if row.get("text_english"))
            words: list = []
            for row in group:
                value = row.get("word_data")
                try:
                    words += json.loads(value) if isinstance(value, str) else (value or [])
                except json.JSONDecodeError:
                    pass
            base["word_data"] = json.dumps(words, ensure_ascii=False)
            base["label"] = verse_label(group)
            base["references"] = [row["reference"] for row in group]
            merged.append(base)
        group.clear()

    for row in rows:
        key = row.get("english_reference")
        if group and (key is None or key != group[0].get("english_reference")):
            flush()
        group.append(row)
        if key is None:
            flush()
    flush()
    return merged
# Verse rows fetched for a similar-passage preview: ample for the 500
# characters find_similar_passages shows.
PASSAGE_PREVIEW_VERSES = 30
_PASSAGE_RE = re.compile(
    r"^(?P<book>\d?\s*[a-z]+(?:\s+[a-z]+)*)\s*"
    r"(?P<c1>\d+)(?::(?P<v1>\d+)(?P<s1>[a-z]?))?"
    r"(?:\s*[-–—]\s*(?:(?P<c2>\d+):)?(?P<v2>\d+)(?P<s2>[a-z]?))?$",
    re.IGNORECASE,
)
# Sorts after every verse suffix letter, so a range end includes 8a, 8b, ...
_LAST_SUFFIX = "~"


def book_code(name: str) -> str | None:
    """Resolve a book name, abbreviation, or compact form ('1john') to its code."""
    key = re.sub(r"\s+", " ", name.strip().lower())
    spaced = re.sub(r"^(\d)\s*", r"\1 ", key)
    for candidate in (key, spaced, key.replace(" ", "")):
        code = BOOK_ABBREV_MAP.get(candidate) or _BOOK_CODES_LOWER.get(candidate)
        if code:
            return code
    return None


# Books with a single chapter, conventionally cited by verse alone ("Jude 3").
SINGLE_CHAPTER_BOOKS = frozenset({"Oba", "Phm", "2Jn", "3Jn", "Jud"})
_SINGLE_CHAPTER_REF_RE = re.compile(
    r"^\s*(?P<book>(?:[1-4]\s*)?[A-Za-z]+(?:\s+[A-Za-z]+)*)\.?"
    r"(?:\s*(?P<verses>\d+[a-z]?(?:\s*[-\u2010-\u2015\u2212]\s*\d+[a-z]?)?))?\s*$"
)


def expand_single_chapter_reference(reference: str) -> str:
    """Rewrite verse-only citations of single-chapter books as chapter 1.

    'Jude 3' -> 'Jude 1:3' and 'Philemon 4-6' -> 'Philemon 1:4-6', matching
    standard citation style. A bare 'Jude' and a lone 'Jude 1' both mean the
    chapter (the whole book), as chapter-level tools such as get_study_notes
    and people_in_passage expect. Anything else, including 'Jude 1:3', is
    returned unchanged.
    """
    match = _SINGLE_CHAPTER_REF_RE.match(reference)
    if not match or book_code(match["book"]) not in SINGLE_CHAPTER_BOOKS:
        return reference
    book = re.sub(r"\s+", " ", match["book"]).strip()
    if not match["verses"] or match["verses"] == "1":
        return f"{book} 1"
    verses = re.sub(r"\s*[\u2010-\u2015\u2212-]\s*", "-", match["verses"])
    return f"{book} 1:{verses}"


def parse_passage_reference(
    reference: str,
) -> tuple[str, str | None, tuple[int, int, str], tuple[int, int, str]] | None:
    """Parse a verse, range (also across chapters), or whole chapter.

    Returns ``(book name, book code or None, start, end)`` where positions are
    ``(chapter, verse, suffix)`` bounds, or None when the text is unparseable
    or the range ends before it starts.
    """
    match = _PASSAGE_RE.match(reference.strip())
    if not match:
        return None
    parts = match.groupdict()
    chapter = int(parts["c1"])
    if parts["v1"] is None:
        if parts["c2"] or parts["s2"]:
            return None
        start = (chapter, 0, "")
        end_chapter = int(parts["v2"]) if parts["v2"] else chapter
        end = (end_chapter, 9999, _LAST_SUFFIX)
    else:
        start = (chapter, int(parts["v1"]), parts["s1"].lower())
        if parts["v2"] is None:
            end = start
        else:
            end_chapter = int(parts["c2"]) if parts["c2"] else chapter
            end = (end_chapter, int(parts["v2"]), parts["s2"].lower() or _LAST_SUFFIX)
    if end < start:
        return None
    return parts["book"].strip(), book_code(parts["book"]), start, end


# Short display names (SBL style) for book codes, used where editorial links
# and notes print a biblical reference ('Mark 14:62', '1 Pet 3:19–20').
BOOK_DISPLAY_NAMES = {
    "Gen": "Gen", "Exo": "Exod", "Lev": "Lev", "Num": "Num", "Deu": "Deut",
    "Jos": "Josh", "Jdg": "Judg", "Rut": "Ruth", "1Sa": "1 Sam", "2Sa": "2 Sam",
    "1Ki": "1 Kgs", "2Ki": "2 Kgs", "1Ch": "1 Chr", "2Ch": "2 Chr", "Ezr": "Ezra",
    "Neh": "Neh", "Est": "Esth", "Job": "Job", "Psa": "Ps", "Pro": "Prov",
    "Ecc": "Eccl", "Sng": "Song", "Isa": "Isa", "Jer": "Jer", "Lam": "Lam",
    "Ezk": "Ezek", "Dan": "Dan", "Hos": "Hos", "Jol": "Joel", "Amo": "Amos",
    "Oba": "Obad", "Jon": "Jonah", "Mic": "Mic", "Nam": "Nah", "Hab": "Hab",
    "Zep": "Zeph", "Hag": "Hag", "Zec": "Zech", "Mal": "Mal",
    "Mat": "Matt", "Mrk": "Mark", "Luk": "Luke", "Jhn": "John", "Act": "Acts",
    "Rom": "Rom", "1Co": "1 Cor", "2Co": "2 Cor", "Gal": "Gal", "Eph": "Eph",
    "Php": "Phil", "Col": "Col", "1Th": "1 Thess", "2Th": "2 Thess", "1Ti": "1 Tim",
    "2Ti": "2 Tim", "Tit": "Titus", "Phm": "Phlm", "Heb": "Heb", "Jas": "Jas",
    "1Pe": "1 Pet", "2Pe": "2 Pet", "1Jn": "1 John", "2Jn": "2 John", "3Jn": "3 John",
    "Jud": "Jude", "Rev": "Rev",
    "Tob": "Tob", "Jdt": "Jdt", "Wis": "Wis", "Sir": "Sir", "Bar": "Bar",
    "1Ma": "1 Macc", "2Ma": "2 Macc", "3Ma": "3 Macc", "4Ma": "4 Macc", "1Es": "1 Esd",
    "2Es": "2 Esd", "Man": "Pr Man", "Pss": "Pss Sol", "EsG": "Add Esth", "Lje": "Ep Jer",
    "Sus": "Sus", "Bel": "Bel", "Ode": "Odes",
}
# The highest chapter and verse a biblical reference may name: larger numbers
# are typing errors, and would overflow the packed chapter * 1000 + verse keys.
_MAX_CHAPTER = 200
_MAX_VERSE = 999


def parse_biblical_range(reference: str) -> tuple[str, int, int, int, int] | None:
    """Parse a biblical reference into (book code, chapter, verse, end chapter, end verse).

    Accepts a verse ('Mark 14:62'), a verse range ('Gen 6:1–4', 'Gen 6:13–8:19'),
    a chapter or chapter range ('Rev 13', 'Heb 9–10', run from verse 1 to 999),
    and verse-only citations of single-chapter books ('Jude 6', 'Jude 14–15').
    Returns None for unknown books, reversed ranges, or out-of-range numbers.
    """
    parsed = parse_passage_reference(expand_single_chapter_reference(reference.strip()))
    if parsed is None or parsed[1] is None:
        return None
    _, code, (chapter, verse, _), (end_chapter, end_verse, _) = parsed
    verse, end_verse = max(verse, 1), min(end_verse, _MAX_VERSE)
    if not (1 <= chapter <= end_chapter <= _MAX_CHAPTER) or verse > _MAX_VERSE:
        return None
    return code, chapter, verse, end_chapter, end_verse


def _format_chapter_range(chapter: int, verse: int, end_chapter: int, end_verse: int) -> str:
    """'19:1-37', '1:1-2:3', or '19:3'."""
    if (chapter, verse) == (end_chapter, end_verse):
        return f"{chapter}:{verse}"
    if chapter == end_chapter:
        return f"{chapter}:{verse}-{end_verse}"
    return f"{chapter}:{verse}-{end_chapter}:{end_verse}"


def format_biblical_range(code: str, chapter: int, verse: int, end_chapter: int, end_verse: int) -> str:
    """Render a parsed range: 'Mark 14:62', 'Gen 6:1–4', 'Heb 9–10', 'Jude 14–15'."""
    book = BOOK_DISPLAY_NAMES.get(code, code)
    if verse == 1 and end_verse == _MAX_VERSE:
        chapters = str(chapter) if chapter == end_chapter else f"{chapter}–{end_chapter}"
        return f"{book} {chapters}"
    if code in SINGLE_CHAPTER_BOOKS and chapter == end_chapter == 1:
        start, end = str(verse), str(end_verse)
    else:
        start = f"{chapter}:{verse}"
        end = str(end_verse) if chapter == end_chapter else f"{end_chapter}:{end_verse}"
    return f"{book} {start}" if (chapter, verse) == (end_chapter, end_verse) else f"{book} {start}–{end}"


def _lxx_row(row: dict) -> dict:
    """Attach the constant LXX provenance to a stored biblical_version_verses row.

    Rows with Brenton's English get the standing translation note. Brenton's
    own Greek (with its source) and the difference summary are kept only when
    that Greek differs from the Rahlfs text (``brenton_greek_differs`` = 1).
    Where Brenton's edition prints the KJV Apocrypha, the English is labelled
    as such and carries its own note instead: Brenton's Greek is not what that
    English translates, so it is not compared or shown. Rows outside the
    Protestant canon get ``apocrypha`` (the book or addition's name).
    """
    edition_book = row["edition_reference"].split(".", 1)[0]
    chapter, verse = row["edition_chapter"], row["edition_verse"]
    row.update(
        version="LXX",
        language="Greek",
        license=LXX_LICENSE,
        source_url=LXX_SOURCE_URL,
        translation_label=LXX_TRANSLATION_LABEL,
        morphology=expand_lxx_morphology(row["morphology"]),
        _edition_position=(
            row.pop("edition_chapter"), row.pop("edition_verse"), row.pop("edition_verse_suffix")
        ),
    )
    apocrypha = apocrypha_name(edition_book, chapter, verse, row["canonical_reference"])
    if apocrypha:
        row["apocrypha"] = apocrypha
    if row["translation"] and is_kjv_apocrypha(edition_book, chapter, verse):
        row.update(
            translation_label=KJV_APOCRYPHA_TRANSLATION_LABEL,
            translation_note=KJV_APOCRYPHA_NOTE,
            kjv_apocrypha=True,
        )
        del row["brenton_greek_differs"], row["brenton_greek"], row["brenton_greek_difference"]
        return row
    if row["translation"]:
        row["translation_note"] = BRENTON_TRANSLATION_NOTE
    if row["brenton_greek_differs"]:
        row["brenton_greek_source_url"] = BRENTON_GREEK_SOURCE_URL
    else:
        del row["brenton_greek"], row["brenton_greek_difference"]
    return row


def _group_key(row: dict) -> str:
    return row["canonical_reference"] or f"LXX-only {row['edition_reference']}"

_FTS_OPERATORS = {"AND", "OR", "NOT", "NEAR"}


def _strip_marks(text: str) -> str:
    """Drop nonspacing marks and format characters after decomposition, then recompose.

    Removes Greek accents, breathings and iota subscripts, Hebrew/Aramaic
    niqqud, cantillation, the uncertain-letter circlet and the combining
    grapheme joiner, and invisible format characters (left-to-right marks,
    zero-width joiners) that would otherwise split a word.
    """
    decomposed = unicodedata.normalize("NFD", unicodedata.normalize("NFC", text))
    return unicodedata.normalize(
        "NFC", "".join(ch for ch in decomposed if unicodedata.category(ch) not in ("Mn", "Cf"))
    )


def fold_ancient_search_text(text: str) -> str:
    """Fold marks and case for ancient-source search (NFD, drop marks, casefold, NFC).

    Applied to every indexed Greek, Hebrew, or Aramaic original and to every
    query token, so polytonic accents, breathings, iota subscripts, final
    sigma, niqqud, and cantillation do not affect matching.
    """
    return unicodedata.normalize("NFC", _strip_marks(text).casefold())


# Editorial signs printed inside words: restorations [ ] ⟨ ⟩, corrections < >
# and << >>, supralinear insertions ^ ^, alternative readings ( ), removals
# { } and {{ }}, and line-break bars ¦. Search deletes the signs (keeping the
# letters between them) rather than splitting the word at them.
_EDITORIAL_SIGNS = re.compile(r"[\[\]⟨⟩〈〉<>{}()^¦]")
# Prefixed particles written joined to the next word: and, in, the, to, from,
# as, which/that.
HEBREW_PREFIX_LETTERS = "ובהלמכש"
_HEBREW_WORD = re.compile(r"[\u05d0-\u05ea]+")
_MIN_UNPREFIXED_LETTERS = 3


def strip_editorial_signs(text: str) -> str:
    """Delete editorial signs so a marked word reads as one word."""
    return _EDITORIAL_SIGNS.sub("", text)


# Spelling of names varies between translations (Melchizedek, Josephus's
# Melchisedec, Philo's Melchisedek). Words sharing a loose spelling key are
# searched together; the key folds these letter alternations.
_SPELLING_FOLDS = (("ph", "f"), ("ch", "c"), ("ae", "e"), ("oe", "e"), ("k", "c"),
                   ("q", "c"), ("z", "s"), ("y", "i"), ("j", "i"))
# First letters an index word may start with for each first letter of a key.
_SPELLING_FIRST_LETTERS = {"c": "ckq", "s": "sz", "f": "fp", "i": "iyj", "e": "eao"}
_MIN_VARIANT_LETTERS = 5
_MAX_SPELLING_VARIANTS = 4


def spelling_key(word: str) -> str:
    """A loose key under which spelling variants of a Latin-script name coincide."""
    key = word.lower()
    for old, new in _SPELLING_FOLDS:
        key = key.replace(old, new)
    key = re.sub(r"(.)\1+", r"\1", key)
    return key[:-1] if len(key) > 4 and key.endswith("h") else key


def hebrew_prefix_variants(word: str) -> list[str]:
    """A Hebrew/Aramaic word without one, then two, leading prefix letters.

    Each variant keeps at least three letters ('ובהון' gives 'בהון' and 'הון';
    'בית' gives nothing). A root letter that is also a prefix letter is
    stripped too ('מקדש' gives 'קדש'), so these variants widen matching rather
    than parse the word; search uses them only as a fallback.
    """
    return [
        word[count:]
        for count in (1, 2)
        if len(word) - count >= _MIN_UNPREFIXED_LETTERS
        and all(letter in HEBREW_PREFIX_LETTERS for letter in word[:count])
    ]


def _ancient_index_words(
    original: str, removals: tuple[str, ...], gaps: tuple[str, ...] = (),
) -> str:
    for pattern in gaps:
        # Replaced by a space: the letters either side of a modern
        # reconstruction ('יג[די]לו') must not join into a word ('יגלו').
        original = re.sub(pattern, " ", original)
    for pattern in removals:
        # Deleted, not replaced by a space: an erasure inside a word
        # ('י{{א}}<<ע>>בורו') must leave the corrected word whole.
        original = re.sub(pattern, "", original)
    return fold_ancient_search_text(strip_editorial_signs(original))


def ancient_search_index_text(
    original: str, removals: tuple[str, ...] = (), gaps: tuple[str, ...] = (),
) -> str:
    """The folded original-language text stored in the exact search column.

    ``gaps`` are a corpus's patterns for printed text that is not evidence
    (modern reconstruction); each becomes a word break. ``removals`` are its
    patterns for printed text that is not part of the reading (e.g. scribal
    erasures); they are deleted. Editorial signs are then deleted and the text
    folded like a query. The displayed text is stored separately and keeps
    every sign.
    """
    return _ancient_index_words(original, removals, gaps)


def ancient_search_prefix_variants(
    original: str, removals: tuple[str, ...] = (), gaps: tuple[str, ...] = (),
) -> str:
    """Hebrew-script words of ``original`` without their leading prefix letters.

    Stored in a separate search column that is queried only when the exact
    search finds nothing, so 'הון' finds 'ובהון' as a marked fallback.
    """
    words = set(re.findall(r"\w+", _ancient_index_words(original, removals, gaps)))
    return " ".join(sorted(dict.fromkeys(
        variant
        for word in words
        if _HEBREW_WORD.fullmatch(word)
        for variant in hebrew_prefix_variants(word)
        if variant not in words
    )))


def parse_ancient_biblical_reference(reference: str) -> tuple[str, int, int] | None:
    """Parse 'Luke 21', 'Luke 21:5', 'Luke 21:5-6' or 'Jude 6' into (book code, sort start, sort end)."""
    parsed = parse_biblical_range(reference)
    if parsed is None:
        return None
    code, chapter, verse, end_chapter, end_verse = parsed
    return code, chapter * 1000 + verse, end_chapter * 1000 + end_verse


def _sort_theme_lists(rows: list[dict]) -> list[dict]:
    """Sort each row's comma-joined theme keys.

    GROUP_CONCAT has no defined order, and ORDER BY inside an aggregate needs
    SQLite 3.44+, so the list is ordered here to keep output stable.
    """
    for row in rows:
        if row.get("themes"):
            row["themes"] = ",".join(sorted(row["themes"].split(",")))
    return rows


# Textual-variant case keys for verses where the MT and the ancient versions
# agree. These records hold translation decisions and interpretive claims, not
# manuscript divergence, so they are stored and shown as interpretive cases.
INTERPRETIVE_CASE_KEYS = frozenset({"MT_preserved", "translation_choice"})


# --- People in the Theographic graph -----------------------------------------

_PERSON_COLUMNS = (
    "id", "name", "also_called", "gender", "birth_year", "death_year",
    "birth_place_id", "death_place_id",
)
# Never a link in a family connection: God is recorded as the father of Adam
# and Eve, which would otherwise join everyone through Him.
_NOT_FAMILY_LINKS = frozenset({"god_1324", "holy_spirit_7400"})


def _fold_name(text: str | None) -> str:
    """A name compared without case, underscores or extra spaces."""
    return re.sub(r"\s+", " ", (text or "").replace("_", " ")).strip().casefold()


def _person_match_tier(person: dict, query: str, raw: str = "") -> int | None:
    """How well a graph person matches a folded query (lower is better), or None."""
    if (raw or query) == person["id"].casefold():
        return 0
    name = _fold_name(person["name"])
    title = _fold_name(person.get("display_title"))
    surname = _fold_name(person.get("surname"))
    if query != name and query in (title, f"{name} {surname}" if surname else None):
        return 1
    base, _, aside = (person.get("display_title") or "").partition(" (")
    if query == name or (base and query == _fold_name(base)):
        return 2
    others = [surname] if surname else []
    others += [_fold_name(alias) for alias in (person.get("also_called") or "").split(",")
               if alias.strip()[:1].isupper()]
    aside = aside.rstrip(")")
    if aside[:1].isupper() and " " not in aside:
        others.append(_fold_name(aside))
    if query in others:
        return 3
    if len(query) >= 3 and (name.startswith(query) or title.startswith(query)):
        return 4
    return None


def _person_label(person: dict | None, fallback: str = "") -> str:
    """A person's display title ('Mary (Mother of Jesus)'), else name."""
    if not person:
        return fallback
    return person.get("display_title") or person.get("name") or fallback


# The pooled read connection bound to the running task by StudyBibleDB.reading(),
# as (database, connection). Context variables are per task, so concurrent tool
# calls each see their own connection.
_TASK_CONNECTION: contextvars.ContextVar[tuple[Any, aiosqlite.Connection] | None] = (
    contextvars.ContextVar("study_bible_task_connection", default=None)
)


class StudyBibleDB:
    """Async SQLite database interface for Bible study data.

    One aiosqlite connection runs its queries one at a time on its own thread,
    so with a single connection a slow query (a vector scan) holds up every
    other call. ``readers`` opens that many extra read-only connections; inside
    ``async with db.reading():`` a task's queries run on one of them, so
    concurrent tool calls query in parallel (WAL lets readers run together).
    Outside ``reading()``, and with ``readers=0`` (the default, used by tests
    and scripts), every query uses the one read-write connection as before.
    The caches below are shared by all connections.
    """

    def __init__(self, db_path: Path | str, readers: int = 0):
        self.db_path = Path(db_path)
        self.readers = max(0, int(readers))
        self._conn: aiosqlite.Connection | None = None
        self._reader_conns: list[aiosqlite.Connection] = []
        self._reader_pool: asyncio.Queue[aiosqlite.Connection] | None = None
        self._vec_loaded = False
        self._vec_error: str | None = None
        self._has_bsb: bool | None = None
        self._graph_people_cols: set[str] | None = None
        self._people_index: list[dict] | None = None
        self._family_graph: dict | None = None
        self._acai_keys: bool | None = None
        self._moved_verses: dict[str, tuple[int, int, int]] | None = None
        self._torah_numbering: dict[str, tuple[dict, dict]] = {}
        self._lexicon_index: LexiconIndex | None = None

    @property
    def conn(self) -> aiosqlite.Connection | None:
        """The connection this task's queries use: its pooled reader inside
        ``reading()``, else the read-write connection."""
        bound = _TASK_CONNECTION.get()
        if bound is not None and bound[0] is self:
            return bound[1]
        return self._conn

    @conn.setter
    def conn(self, value: aiosqlite.Connection | None) -> None:
        self._conn = value

    async def connect(self):
        """Open the read-write connection, then ``readers`` read-only ones."""
        self._conn = await self._open_connection()
        # Try to load sqlite-vec extension for vector search
        self._vec_loaded, self._vec_error = await self._load_sqlite_vec(self._conn)
        if self._vec_loaded:
            logger.info("sqlite-vec extension loaded successfully")
        else:
            logger.warning(self._vec_error)
        if self.readers:
            await self._open_readers()

    async def _open_connection(self, read_only: bool = False) -> aiosqlite.Connection:
        if read_only:
            uri = f"{self.db_path.resolve().as_uri()}?mode=ro"
            conn = await aiosqlite.connect(uri, uri=True)
        else:
            conn = await aiosqlite.connect(self.db_path)
        conn.row_factory = aiosqlite.Row
        return conn

    async def _open_readers(self) -> None:
        """Open the reader pool; a reader that fails is left out, never fatal."""
        # Read the schema on the main connection first: on a WAL database that
        # creates the -wal/-shm files a read-only connection cannot create.
        await self._fetchone("SELECT COUNT(*) AS n FROM sqlite_master")
        pool: asyncio.Queue[aiosqlite.Connection] = asyncio.Queue()
        for _ in range(self.readers):
            conn = None
            try:
                conn = await self._open_connection(read_only=True)
                async with conn.execute("SELECT COUNT(*) FROM sqlite_master") as cursor:
                    await cursor.fetchone()
                if self._vec_loaded:
                    loaded, error = await self._load_sqlite_vec(conn)
                    if not loaded:
                        raise RuntimeError(error)
            except Exception as e:
                logger.warning(f"Read connection unavailable, continuing without it: {e}")
                if conn is not None:
                    await conn.close()
                continue
            self._reader_conns.append(conn)
            pool.put_nowait(conn)
        if self._reader_conns:
            self._reader_pool = pool

    @staticmethod
    async def _load_sqlite_vec(conn: aiosqlite.Connection) -> tuple[bool, str | None]:
        """Load the sqlite-vec extension into ``conn``: (loaded, error message)."""
        try:
            import sqlite_vec

            # Get the loadable path for sqlite-vec
            vec_path = sqlite_vec.loadable_path()

            # Use aiosqlite's built-in extension loading methods
            await conn.enable_load_extension(True)
            await conn.load_extension(vec_path)
            await conn.enable_load_extension(False)
            return True, None
        except ImportError:
            return False, "sqlite-vec package not installed. Install with: pip install sqlite-vec"
        except Exception as e:
            return False, f"Failed to load sqlite-vec extension: {e}"

    @property
    def reader_count(self) -> int:
        """Read-only connections open in the pool (0: queries share one connection)."""
        return len(self._reader_conns)

    @contextlib.asynccontextmanager
    async def reading(self):
        """Run the block's queries on a pooled read-only connection of its own.

        Waits while every reader is busy. Without a pool, or inside another
        ``reading()`` of this database, the block uses the current connection.
        """
        bound = _TASK_CONNECTION.get()
        if self._reader_pool is None or (bound is not None and bound[0] is self):
            yield
            return
        pool = self._reader_pool
        conn = await pool.get()
        token = _TASK_CONNECTION.set((self, conn))
        try:
            yield
        finally:
            _TASK_CONNECTION.reset(token)
            pool.put_nowait(conn)

    async def close(self):
        """Close the read-only connections and the read-write one."""
        self._reader_pool = None
        readers, self._reader_conns = self._reader_conns, []
        for conn in readers:
            await conn.close()
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def _fetchall(self, sql: str, params: tuple | list = ()) -> list[dict]:
        """Execute SQL and return all rows as dicts."""
        async with self.conn.execute(sql, params) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def _fetchone(self, sql: str, params: tuple | list = ()) -> dict | None:
        """Execute SQL and return one row as dict, or None."""
        async with self.conn.execute(sql, params) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def _table_has_rows(self, table: str) -> bool:
        """Check if a table exists and has at least one row."""
        try:
            async with self.conn.execute(f"SELECT 1 FROM {table} LIMIT 1") as cursor:
                return await cursor.fetchone() is not None
        except Exception:
            return False

    # =========================================================================
    # Lexicon queries
    # =========================================================================

    @staticmethod
    def _normalize_strongs(strongs: str) -> str:
        """Normalize Strong's number to match DB format (G26 -> G0026, h430g -> H0430G)."""
        strongs = strongs.upper().strip()
        match = re.fullmatch(r"([GH])0*(\d{1,4})([A-Z]?)", strongs)
        if match:
            prefix, number, suffix = match.groups()
            return f"{prefix}{int(number):04d}{suffix}"
        return strongs

    async def get_lexicon_entry(self, strongs: str) -> dict | None:
        """Get a single lexicon entry by Strong's number."""
        strongs = self._normalize_strongs(strongs)
        entry = await self._fetchone("SELECT * FROM lexicon WHERE strongs = ?", (strongs,))
        if entry is None and re.fullmatch(r"[GH]\d{4}[A-Z]", strongs):
            # The lexicon is keyed by the bare number; STEPBible's sense
            # suffix (H0430G) appears only in verse word data.
            entry = await self._fetchone(
                "SELECT * FROM lexicon WHERE strongs = ?", (strongs[:-1],)
            )
        return entry

    async def lexicon_index(self) -> LexiconIndex:
        """Folded transliterations of every lexicon entry (built once per connection)."""
        if self._lexicon_index is None:
            rows = await self._fetchall(
                "SELECT strongs, language, transliteration, pronunciation, word, "
                "short_definition, usage_count FROM lexicon"
            )
            self._lexicon_index = LexiconIndex(tuple(row.values()) for row in rows)
        return self._lexicon_index

    # Strong's numbers passed to SQL from the lexicon index, per tier: the
    # most-used ones, far more than any result page.
    _INDEX_MATCH_CAP = 300
    # The opening of a full definition, where BDB and LSJ give the lead sense
    # ("H8451. torah ... noun feminine direction, instruction, law; ...").
    _LEAD_CHARS = 200

    async def search_lexicon(
        self,
        query: str,
        language: str | None = None,
        limit: int = 4
    ) -> list[dict]:
        """Search lexicon by transliteration, gloss, word, or definition.

        Results are ranked in tiers, then by usage (most frequent first):

        0. the query is the entry's transliteration or word, whatever the
           spelling ('agape' = agapē, 'hesed' = checed/che.sed), unless the
           query is itself an English gloss ('man', 'son', 'law'), so English
           searches are not led by a look-alike transliteration;
        1. the brief definition has the query as a word, or a form of it
           ('love' in 'to love', 'lover', 'beloved'; not 'sin' in 'since');
           or, for a transliteration or original-word query, the entry's
           transliteration or word contains it;
        2. the brief definition contains the query's stem ('propitiation' ->
           'to propitiate', 'righteousness' -> 'righteous'), or the lead
           sense of the full definition has the query as a word (BDB's
           'direction, instruction, law' for torah);
        3. the brief definition, lead sense, word or transliteration contains
           the query some other way ('sin' in 'since', 'law' in
           'daughter-in-law'), or an English query folds to the entry's
           transliteration ('son' and tso'n);
        4. the query appears only further into a full definition.
        """
        query = query.strip()
        if not query:
            return []
        language = language.lower() if language else None
        index = await self.lexicon_index()
        exact, partial = index.matches(query, language)
        english = index.is_gloss(query, language)
        lookalike: list[str] = []
        if english:
            # An English word ('son', 'law'): transliterations that fold to
            # it (tso'n, la'ab) rank with the weak matches, and spelling-folded
            # partial matches are not used.
            exact, partial, lookalike = [], [], exact
        cap = self._INDEX_MATCH_CAP
        exact, partial, lookalike = exact[:cap], partial[:cap], lookalike[:cap]
        glossed = index.gloss_matches(query, language)[:cap]

        lowered = query.lower()
        like = f"%{lowered}%"
        stem = english_stem(query)
        stem_like = f"%{stem}%" if stem else None
        lead = f"LOWER(SUBSTR(full_definition, 1, {self._LEAD_CHARS}))"
        word_glob = (
            f"*[^a-z'-]{lowered}[^a-z'-]*" if re.fullmatch(r"[a-z][a-z ]*", lowered) else None
        )

        # (sql, params) fragments, joined in the order they appear in the query.
        def in_list(values: list[str]) -> tuple[str, list]:
            if not values:
                return "0", []
            return f"strongs IN ({','.join('?' * len(values))})", list(values)

        def matches(column: str, pattern: str | None, op: str = "LIKE") -> tuple[str, list]:
            if pattern is None:
                return "0", []
            if op == "GLOB":
                return f"(' ' || {column} || ' ') GLOB ?", [pattern]
            return f"{column} LIKE ?", [pattern]

        def any_of(*fragments: tuple[str, list]) -> tuple[str, list]:
            return (
                "(" + " OR ".join(sql for sql, _ in fragments) + ")",
                [param for _, values in fragments for param in values],
            )

        original = any_of(matches("LOWER(word)", like), matches("LOWER(transliteration)", like))
        tiers = [
            in_list(exact),
            any_of(in_list(glossed), in_list(partial), ("0", []) if english else original),
            any_of(matches("LOWER(short_definition)", stem_like), matches(lead, word_glob, "GLOB")),
            any_of(
                matches("LOWER(short_definition)", like), matches(lead, like), original,
                in_list(lookalike),
            ),
        ]
        tier_sql = "CASE " + " ".join(
            f"WHEN {sql} THEN {number}" for number, (sql, _) in enumerate(tiers)
        ) + f" ELSE {len(tiers)} END"
        where_sql, where_params = any_of(
            matches("LOWER(short_definition)", like),
            matches("LOWER(short_definition)", stem_like),
            matches("LOWER(full_definition)", like),
            matches("LOWER(abbott_smith_def)", like),
            original,
            in_list(exact + partial + glossed + lookalike),
        )
        params = [param for _, values in tiers for param in values] + where_params
        language_sql = ""
        if language:
            language_sql = "AND language = ?"
            params.append(language)
        params.append(limit)
        rows = await self._fetchall(
            f"""SELECT * FROM (
                    SELECT *, {tier_sql} AS match_tier FROM lexicon
                    WHERE {where_sql} {language_sql}
                )
                ORDER BY match_tier, usage_count DESC, strongs
                LIMIT ?""",
            params,
        )
        for row in rows:
            row.pop("match_tier", None)
        return rows

    async def get_related_words(self, strongs: str) -> list[dict]:
        """Get words related to a Strong's number."""
        entry = await self.get_lexicon_entry(strongs)
        if not entry or not entry.get('related_words'):
            return []

        try:
            related = json.loads(entry['related_words'])
            results = []
            for r in related:
                if isinstance(r, dict) and r.get('strongs'):
                    full_entry = await self.get_lexicon_entry(r['strongs'])
                    if full_entry:
                        results.append(full_entry)
            return results
        except Exception:
            return []

    # =========================================================================
    # Verse queries
    # =========================================================================

    def _normalize_reference(self, reference: str) -> str:
        """Normalize a Bible reference to database format."""
        # Handle common variations: "John 3:16" -> "Jhn.3.16"
        # This is a simplified version - expand as needed

        # Parse reference like "John 3:16", "Gen. 15:6" or "1 Corinthians 13:4-7"
        match = re.match(
            r'^(\d?\s*[a-zA-Z]+(?:\s+[a-zA-Z]+)*)\.?\s*(\d+):(\d+[a-z]?)(?:-(\d+[a-z]?))?$',
            reference.strip(),
            re.IGNORECASE,
        )

        if match:
            book, chapter, verse_start, verse_end = match.groups()
            book_abbr = book_code(book) or book[:3].title()
            return f"{book_abbr}.{chapter}.{verse_start.lower()}"

        return reference

    async def get_verse(self, reference: str) -> dict | None:
        """Get a verse by its English reference.

        Matches book, chapter and English verse number, so a row stored with
        split numbering such as ``Gen.32.1(32.2)`` or ``2Co.13.13[13.14]`` (BSB
        2 Cor 13:14) is found; any other reference must match a row exactly.
        There is no substring match: a verse missing from the table returns
        None, not a neighbour ('Jhn.3.1' must not return 'Jhn.3.16'). The row
        carries ``text_bsb`` (see ``attach_bsb_text``); with the BSB loaded, an
        English verse stored as several rows is returned as one merged row
        (see ``merge_english_verses``).
        """
        normalized = self._normalize_reference(reference)
        parts = normalized.split(".")
        rows: list[dict] = []
        if len(parts) == 3 and parts[1].isdecimal() and parts[2].isdecimal():
            chapter, verse = int(parts[1]), int(parts[2])
            rows = await self.get_passage(parts[0], chapter, verse, chapter, verse)
        if not rows:
            rows = await self.attach_bsb_text(
                await self._fetchall("SELECT * FROM verses WHERE reference = ?", (normalized,))
            )
        if not rows:
            return None
        return merge_english_verses(rows)[0]

    async def get_verses_with_strongs(self, strongs: str, limit: int = 4) -> list[dict]:
        """Find verses containing a specific Strong's number.

        Word data keeps STEPBible's one-letter sense suffix (H0430G), so a bare
        number also matches its suffixed forms; a suffixed number matches only
        itself. Rows carry ``text_bsb`` (see ``attach_bsb_text``).
        """
        where, patterns = self._strongs_word_data_filter(strongs)
        return await self.attach_bsb_text(await self._fetchall(
            f"SELECT * FROM verses WHERE {where} LIMIT ?", (*patterns, limit)
        ))

    async def count_verses_with_strongs(self, strongs: str) -> int:
        """How many verses ``get_verses_with_strongs`` could return without a limit."""
        where, patterns = self._strongs_word_data_filter(strongs)
        row = await self._fetchone(f"SELECT COUNT(*) AS n FROM verses WHERE {where}", patterns)
        return row["n"] if row else 0

    def _strongs_word_data_filter(self, strongs: str) -> tuple[str, list[str]]:
        """SQL condition on verses.word_data, and its LIKE patterns, for a Strong's number."""
        strongs = self._normalize_strongs(strongs)
        patterns = [f'%"{strongs}"%']
        if re.fullmatch(r"[GH]\d{4}", strongs):
            patterns.append(f'%"{strongs}_"%')
        return " OR ".join("word_data LIKE ?" for _ in patterns), patterns

    async def has_bsb_text(self) -> bool:
        """True when the bsb_verses table exists and has rows (checked once per instance)."""
        if self._has_bsb is None:
            self._has_bsb = await self._table_has_rows("bsb_verses")
        return self._has_bsb

    async def _fetch_in(self, sql: str, values) -> list[dict]:
        """Run ``sql``, which ends in ``IN``, over ``values`` in chunks; return every row."""
        values = sorted(set(values))
        rows: list[dict] = []
        for start in range(0, len(values), 500):
            chunk = values[start:start + 500]
            rows += await self._fetchall(f"{sql} ({','.join('?' * len(chunk))})", chunk)
        return rows

    async def _moved_nt_verses(self) -> dict[str, tuple[int, int, int]]:
        """NT rows whose English (BSB) verse is not their Greek one.

        Returns ``{reference: (english chapter, english verse, id)}``, cached;
        empty without the BSB. A row such as ``2Co.13.13[13.14]`` carries the
        Greek edition's verse with the KJV's number in brackets; the BSB
        follows the KJV there (2 Cor 13:14) but keeps the Greek order of Phil
        1:16-17, which the KJV swaps. A row's English verse is:

        - for a whole Greek verse (no plain row shares its number): the
          bracketed verse, unless the BSB lacks it, or the BSB has the Greek
          verse and the two rows swap numbers (Phil 1:16-17);
        - for a fragment of a Greek verse that has its own row: the bracketed
          verse only if no other row is that English verse ('2Co.13.12[13.13]',
          the BSB's 13:13), else the Greek verse it belongs to.
        """
        if self._moved_verses is not None:
            return self._moved_verses
        # Built in a local dict and published once complete: concurrent calls
        # (one per pooled connection) must never see a half-built map.
        moved: dict[str, tuple[int, int, int]] = {}
        if not await self.has_bsb_text():
            self._moved_verses = moved
            return moved
        split: dict[str, tuple[int, str, str]] = {}
        for row in await self._fetchall(
            "SELECT id, reference FROM verses WHERE reference LIKE '%[%' ORDER BY id"
        ):
            match = _SPLIT_REFERENCE_RE.match(row["reference"])
            if match and match.group(4) == "[":
                book, chapter, verse, _, other_chapter, other_verse = match.groups()
                split[row["reference"]] = (
                    row["id"], f"{book}.{chapter}.{verse}", f"{book}.{other_chapter}.{other_verse}"
                )
        if not split:
            self._moved_verses = moved
            return moved
        numbers = {ref for _, greek, kjv in split.values() for ref in (greek, kjv)}
        plain = {
            row["reference"]
            for row in await self._fetch_in("SELECT reference FROM verses WHERE reference IN", numbers)
        }
        in_bsb = {
            row["reference"]
            for row in await self._fetch_in("SELECT reference FROM bsb_verses WHERE reference IN", numbers)
        }
        swapped = {greek: kjv for _, greek, kjv in split.values()}
        english: dict[str, str] = {}
        for ref, (_, greek, kjv) in split.items():
            if greek in plain:
                continue
            if greek not in in_bsb and kjv in in_bsb:
                english[ref] = kjv
            elif swapped.get(kjv) == greek or kjv not in in_bsb:
                english[ref] = greek
            else:
                english[ref] = kjv
        taken = plain | set(english.values())
        for ref, (_, greek, kjv) in split.items():
            if greek in plain:
                english[ref] = kjv if kjv in in_bsb and kjv not in taken else greek
        for ref, target in english.items():
            row_id, greek, _ = split[ref]
            if target != greek:
                _, chapter, verse = target.split(".")
                moved[ref] = (int(chapter), int(verse), row_id)
        self._moved_verses = moved
        return moved

    async def english_verse_of_greek(self, book: str, chapter: int, verse: int) -> tuple[int, int] | None:
        """The BSB (chapter, verse) of a Greek verse the BSB numbers differently, else None."""
        for ref, (english_chapter, english_verse, _) in (await self._moved_nt_verses()).items():
            match = _SPLIT_REFERENCE_RE.match(ref)
            if match.group(1) == book and (int(match.group(2)), int(match.group(3))) == (chapter, verse):
                return english_chapter, english_verse
        return None

    async def _bsb_carriers(self, english_refs: set[str]) -> dict[str, str]:
        """For each English verse, the reference of the row that carries its BSB text.

        That is the plain row with the verse's reference, else the verse's
        first row (by id): one row per verse, so a verse stored as several rows
        (Psalm 51's two Hebrew superscription verses) shows its text once.
        """
        carriers = {
            row["reference"]: row["reference"]
            for row in await self._fetch_in("SELECT reference FROM verses WHERE reference IN", english_refs)
        }
        moved = await self._moved_nt_verses()
        chapters: dict[tuple[str, int], set[str]] = {}
        for ref in english_refs - carriers.keys():
            book, chapter, _ = ref.split(".")
            chapters.setdefault((book, int(chapter)), set()).add(ref)
        for (book, chapter), refs in chapters.items():
            first: dict[str, tuple[int, str]] = {}
            rows = await self._fetchall(
                "SELECT id, reference, verse FROM verses WHERE book = ? AND chapter = ?", (book, chapter)
            )
            candidates = [
                (row["id"], row["reference"], f"{book}.{chapter}.{row['verse']}")
                for row in rows if row["reference"] not in moved
            ]
            candidates += [
                (row_id, ref, f"{book}.{moved_chapter}.{verse}")
                for ref, (moved_chapter, verse, row_id) in moved.items()
                if ref.split(".")[0] == book and moved_chapter == chapter
            ]
            for row_id, reference, english_ref in candidates:
                if english_ref in refs and (english_ref not in first or row_id < first[english_ref][0]):
                    first[english_ref] = (row_id, reference)
            carriers.update({english_ref: reference for english_ref, (_, reference) in first.items()})
        return carriers

    async def attach_bsb_text(self, rows: list[dict]) -> list[dict]:
        """Give each `verses` row its English (BSB) verse, text, and label.

        Rows are left unchanged when the database has no BSB, so callers show
        the STEPBible gloss (``text_english``) as before. Otherwise each row
        gets:

        - ``chapter`` and ``verse``: its English verse. OT columns already hold
          it ('Gen.32.1(32.2)' is English 32:1); an NT row the BSB numbers
          differently gets its BSB verse (``_moved_nt_verses``:
          '2Co.13.13[13.14]' is 2 Cor 13:14);
        - ``english_reference``: that verse's reference;
        - ``text_bsb``: the verse's BSB text on the one row that carries it
          (``_bsb_carriers``), None on the verse's other rows ('1Sa.20.42(21.1)'
          beside '1Sa.20.42') and for verses the BSB omits (Matt 17:21, Acts
          8:37, ...);
        - ``label``: its heading (``verse_label``).
        """
        if not rows or not await self.has_bsb_text():
            return rows
        moved = await self._moved_nt_verses()
        for row in rows:
            if row["reference"] in moved:
                row["chapter"], row["verse"], _ = moved[row["reference"]]
            row["english_reference"] = f"{row['book']}.{row['chapter']}.{row['verse']}"
        english_refs = {row["english_reference"] for row in rows}
        carriers = await self._bsb_carriers(english_refs)
        texts = {
            row["reference"]: row["text"]
            for row in await self._fetch_in(
                "SELECT reference, text FROM bsb_verses WHERE reference IN", english_refs
            )
        }
        for row in rows:
            carried = carriers.get(row["english_reference"]) == row["reference"]
            row["text_bsb"] = texts.get(row["english_reference"]) if carried else None
            row["label"] = verse_label([row])
        return rows

    # "Luke 19", "Luke 19:1-3", "Luke 19:45-20:2", "Psalm 23-24", "Luk.19.1".
    _PASSAGE_RE = re.compile(
        r"^(?P<book>[1-4]?\s*[A-Za-z]+(?:\s+[A-Za-z]+)*)\s*\.?\s*"
        r"(?P<c1>\d+)(?:[:.](?P<v1>\d+)[a-z]?)?"
        r"(?:\s*-\s*(?:(?P<c2>\d+)[:.])?(?P<v2>\d+)[a-z]?)?$",
        re.IGNORECASE,
    )
    @classmethod
    def parse_passage_reference(cls, reference: str) -> dict | None:
        """Parse a verse, verse range, cross-chapter range, or chapter reference.

        Returns ``{"book", "book_name", "start_chapter", "start_verse",
        "end_chapter", "end_verse"}`` using English numbering. A ``None``
        verse means "from the start" / "to the end" of that chapter. Hyphen,
        en dash, and em dash all separate a range. Returns ``None`` when the
        text is not a reference of a supported shape.
        """
        text = re.sub(r"\s*[\u2010-\u2015\u2212-]\s*", "-", reference.strip())
        match = cls._PASSAGE_RE.match(text)
        if not match:
            return None
        book_name = re.sub(r"\s+", " ", match["book"]).strip()
        # An unresolved name falls through to a code with no verses, which
        # lookup_verse reports as an unknown book.
        book = book_code(book_name) or book_name.replace(" ", "")[:3].title()
        start_chapter = int(match["c1"])
        start_verse = int(match["v1"]) if match["v1"] else None
        end_chapter = int(match["c2"]) if match["c2"] else start_chapter
        end_verse = int(match["v2"]) if match["v2"] else None
        if match["v2"] and not match["c2"] and start_verse is None:
            # "Psalm 23-24": a range of whole chapters.
            end_chapter, end_verse = end_verse, None
        elif match["v2"] is None and start_verse is not None:
            # Single verse.
            end_verse = start_verse
        return {
            "book": book,
            "book_name": book_name,
            "start_chapter": start_chapter,
            "start_verse": start_verse,
            "end_chapter": end_chapter,
            "end_verse": end_verse,
        }

    async def get_chapter_verse_bounds(self, book: str) -> dict[int, tuple[int, int]]:
        """Map each chapter of ``book`` to its (first, last) English verse number."""
        moved = {
            ref: position for ref, position in (await self._moved_nt_verses()).items()
            if ref.split(".")[0] == book
        }
        if not moved:
            rows = await self._fetchall(
                """SELECT chapter, MIN(verse) AS first, MAX(verse) AS last
                   FROM verses WHERE book = ? GROUP BY chapter""",
                (book,),
            )
            return {row["chapter"]: (row["first"], row["last"]) for row in rows}
        bounds: dict[int, tuple[int, int]] = {}
        for row in await self._fetchall(
            "SELECT reference, chapter, verse FROM verses WHERE book = ?", (book,)
        ):
            chapter, verse = moved[row["reference"]][:2] if row["reference"] in moved else (
                row["chapter"], row["verse"]
            )
            first, last = bounds.get(chapter, (verse, verse))
            bounds[chapter] = (min(first, verse), max(last, verse))
        return dict(sorted(bounds.items()))

    async def get_passage(
        self,
        book: str,
        start_chapter: int,
        start_verse: int,
        end_chapter: int,
        end_verse: int,
    ) -> list[dict]:
        """Get verse rows for an English-numbered passage, in canonical order.

        Matches the ``book``/``chapter``/``verse`` columns (English numbering)
        rather than ``reference`` strings, so OT rows whose reference carries
        English(Hebrew) split numbering such as ``Psa.40.6(40.7)`` are found,
        and NT rows the BSB numbers differently by their BSB verse
        (``2Co.13.13[13.14]`` is 2 Cor 13:14). A verse stored as several rows
        (e.g. ``1Ch.12.4`` and ``1Ch.12.4(12.5)``) returns every row, in
        source order. Rows carry ``text_bsb`` (see ``attach_bsb_text``).
        """
        moved = {
            ref: position for ref, position in (await self._moved_nt_verses()).items()
            if ref.split(".")[0] == book
        }
        margin = 1 if moved else 0
        rows = await self._fetchall(
            """SELECT * FROM verses
               WHERE book = ?
                 AND chapter BETWEEN ? AND ?
                 AND (chapter > ? OR verse >= ?)
                 AND (chapter < ? OR verse <= ?)
               ORDER BY chapter, verse, id""",
            (book, start_chapter - margin, end_chapter + margin,
             start_chapter - margin, start_verse if not margin else 0,
             end_chapter + margin, end_verse if not margin else 9999),
        )
        if moved:
            def position(row: dict) -> tuple[int, int]:
                if row["reference"] in moved:
                    return moved[row["reference"]][:2]
                return row["chapter"], row["verse"]

            rows = sorted(
                (row for row in rows
                 if (start_chapter, start_verse) <= position(row) <= (end_chapter, end_verse)),
                key=lambda row: (*position(row), row["id"]),
            )
        return await self.attach_bsb_text(rows)

    async def get_lxx_quote_hints_for_passage(
        self,
        book: str,
        start_chapter: int,
        start_verse: int,
        end_chapter: int,
        end_verse: int,
    ) -> list[dict]:
        """NT↔OT LXX-form quotation hints whose NT or OT verse lies in a passage.

        Each returned row carries ``passage_side`` ("nt" or "ot"): the side of
        the quotation that falls inside the requested passage.
        """
        if not await self._table_has_rows("nt_ot_lxx_quote_hints"):
            return []
        rows = await self._fetchall(
            """SELECT * FROM nt_ot_lxx_quote_hints
               WHERE nt_book = ? OR ot_book = ? ORDER BY id""",
            (book, book),
        )
        start = (start_chapter, start_verse)
        end = (end_chapter, end_verse)
        hits = []
        for row in rows:
            for side in ("ot", "nt"):
                parts = row[f"{side}_reference"].split(".")
                if len(parts) < 3 or parts[0] != book:
                    continue
                try:
                    position = (int(parts[1]), int(parts[2]))
                except ValueError:
                    continue
                if start <= position <= end:
                    hits.append({**row, "passage_side": side})
                    break
        return hits

    # =========================================================================
    # Cross-reference queries
    # =========================================================================

    async def get_cross_references(
        self,
        reference: str,
        source_filter: str | None = None,
        limit: int = 4,
        min_strength: int | None = None,
    ) -> list[dict]:
        """Get cross-references for a verse, ordered by strength.

        Tiers (high to low):
          tier 3 — CH (Harrison/Romhild, hand-curated), Gage parallel (the
                   tighter Gage/Bradley John↔Rev pairings), and TSK pairs with
                   ≥100 votes (the "breakthrough" rule: top ~0.4% of TSK is
                   near-universal cross-reference and competes with curated).
          tier 2 — Burnett (single-scholar argued chain, JSPL 5.2 (2015)),
                   Gage chiastic (the "looser connections" sheet), and TSK
                   pairs with 20–99 votes (top ~5%).
          tier 1 — everything else (low-vote TSK long-tail).

        Within a tier, ranks by a normalized strength score (CH rel*2+1, Gage
        rel*2+1, Burnett=7, TSK by vote bucket: ≥500→9, 200–499→8, 100–199→7,
        50–99→6, 20–49→5, 10–19→3, 5–9→2, else→1). Ties broken by TSK vote
        count when the same pair also appears in TSK.

        Adaptive return-volume policy: tier 1 rows are SUPPRESSED by default
        when the verse has at least 3 tier-2-or-better rows — so signal-rich
        verses return up to `limit` strong refs and signal-poor verses return only what
        passes the bar (rather than padding with noise). Override by passing
        `source_filter='tsk'` (returns all TSK including tier 1) or by passing
        `min_strength` (treated as explicit "I want some long-tail too").

        Args:
            reference: verse reference, e.g. "John 3:16".
            source_filter: 'ch' | 'tsk' | 'gage' | 'burnett' to restrict to one
                dataset. When 'tsk', the tier-1 suppression is disabled so the
                full TSK long-tail is available.
            limit: max rows (cap, not target). Default 4. The actual returned
                count may be less if the verse has fewer than `limit` rows
                above the noise floor — this is intentional. Raise to 20–30
                with `source_filter='tsk'` or `min_strength=0` for exhaustive
                study.
            min_strength: if set, TSK rows with relevance < min_strength are
                excluded. CH/Gage/Burnett rows always pass — they are
                hand-curated or scholarly-argued, so even relevance=0 means
                "vetted". Setting this disables the default tier-1 suppression
                (the user is explicitly choosing their own floor).
        """
        normalized = self._normalize_reference(reference)

        # Build the source whitelist from source_filter.
        all_types = ("ch", "gage", "burnett", "tsk")
        if source_filter in all_types:
            type_list = (source_filter,)
        else:
            type_list = all_types

        type_in = ",".join(f"'{t}'" for t in type_list)

        tsk_strength_clause = ""
        if min_strength is not None and min_strength > 0:
            # Only TSK rows are filtered by min_strength; the others always pass.
            tsk_strength_clause = (
                f"AND (type != 'tsk' OR relevance >= {int(min_strength)})"
            )

        # Tier mapping (Option B — split Gage + TSK breakthrough):
        #   tier 3: ch (any), gage rel=3 (parallel), tsk votes>=100
        #   tier 2: burnett, gage rel=1 (chiastic), tsk votes 20..99
        #   tier 1: everything else (low-vote tsk noise)
        # Within-tier strength score normalises curated and TSK signals onto
        # a comparable 1..9 scale so a 500-vote TSK link surfaces above a
        # CH rel=2 within tier 3, but a 100-vote TSK ties with CH rel=3.
        sql = f"""
            WITH base AS (
                SELECT source, target, type, relevance, note,
                       CASE
                           WHEN type = 'ch' THEN 3
                           WHEN type = 'gage' AND relevance >= 3 THEN 3
                           WHEN type = 'gage' THEN 2
                           WHEN type = 'burnett' THEN 2
                           WHEN type = 'tsk' AND relevance >= 100 THEN 3
                           WHEN type = 'tsk' AND relevance >= 20  THEN 2
                           WHEN type = 'tsk' THEN 1
                           ELSE 0
                       END AS tier,
                       CASE
                           WHEN type IN ('ch','gage') THEN relevance * 2 + 1
                           WHEN type = 'burnett' THEN 7
                           WHEN type = 'tsk' THEN
                               CASE
                                   WHEN relevance >= 500 THEN 9
                                   WHEN relevance >= 200 THEN 8
                                   WHEN relevance >= 100 THEN 7
                                   WHEN relevance >= 50  THEN 6
                                   WHEN relevance >= 20  THEN 5
                                   WHEN relevance >= 10  THEN 3
                                   WHEN relevance >= 5   THEN 2
                                   ELSE 1
                               END
                           ELSE 0
                       END AS strength_score
                FROM cross_references
                WHERE source = ?
                  AND type IN ({type_in})
                  {tsk_strength_clause}
            ),
            ranked AS (
                SELECT *,
                       ROW_NUMBER() OVER (
                           PARTITION BY source, target
                           ORDER BY tier DESC, strength_score DESC
                       ) AS rn
                FROM base
            ),
            tsk_side AS (
                SELECT source, target, relevance AS tsk_votes
                FROM cross_references
                WHERE source = ? AND type = 'tsk'
            )
            SELECT
                r.source, r.target, r.type, r.relevance, r.tier,
                r.strength_score,
                CASE WHEN r.type = 'ch' THEN r.relevance ELSE NULL END AS ch_relevance,
                COALESCE(t.tsk_votes, CASE WHEN r.type = 'tsk' THEN r.relevance END) AS tsk_votes,
                r.note
            FROM ranked r
            LEFT JOIN tsk_side t ON r.source = t.source AND r.target = t.target
            WHERE r.rn = 1
            ORDER BY
                r.tier DESC,
                r.strength_score DESC,
                COALESCE(t.tsk_votes, 0) DESC,
                CASE r.type WHEN 'ch' THEN 4 WHEN 'gage' THEN 3 WHEN 'burnett' THEN 2 ELSE 1 END DESC,
                r.target
            LIMIT ?
        """
        rows = await self._fetchall(sql, (normalized, normalized, limit))

        # Tier-1 suppression: when the user hasn't asked for raw TSK
        # (via source_filter='tsk') and hasn't set their own floor (via
        # min_strength), drop tier-1 rows IF the verse already has at least
        # 3 rows from tier 2+ (signal-rich). For signal-poor verses we keep
        # the tier-1 rows so the response isn't empty.
        suppression_active = (
            source_filter != "tsk"
            and min_strength is None
        )
        if suppression_active:
            high = [r for r in rows if r["tier"] >= 2]
            if len(high) >= 3:
                return high

        return rows

    async def get_thematic_references(self, theme: str) -> list[dict]:
        """Get references for a theological theme."""
        theme_lower = theme.lower().replace(" ", "_")
        return await self._fetchall(
            "SELECT * FROM thematic_references WHERE theme = ? OR theme LIKE ?",
            (theme_lower, f"%{theme_lower}%"),
        )

    # =========================================================================
    # Name queries
    # =========================================================================

    async def lookup_name(
        self, name: str, name_type: str | None = None, limit: int = 4
    ) -> list[dict]:
        """Look up a biblical name: exact matches first, then prefix, then substring.

        Matching ignores case, and a space matches TIPNR's underscore ('Mary
        Magdalene' finds 'Mary_Magdalene'); a name whose first word is the
        query ('Mary_Magdalene' for 'Mary') counts as exact. Within each tier
        the best-known entry comes first: the one ACAI records in the most
        verses, then the one with the most TIPNR references. Each row carries
        ``match_count``, the number of names that match before ``limit``.
        """
        query = re.sub(r"\s+", " ", name.replace("_", " ")).strip()
        pattern = query.replace(" ", "_")
        type_filter = " AND type = ?" if name_type else ""
        if await self._acai_has_tipnr_keys():
            prominence = """ac AS (
                    SELECT REPLACE(k.value, '_', '') AS tkey, MAX(a.reference_count) AS rc
                    FROM acai_entities a, json_each(a.tipnr_keys) k
                    WHERE REPLACE(k.value, '_', '') IN (SELECT tkey FROM m)
                    GROUP BY 1)"""
            join = "LEFT JOIN ac USING (tkey)"
            rank = "COALESCE(ac.rc, 0) DESC,"
        else:
            prominence = "ac AS (SELECT NULL AS tkey)"
            join = rank = ""
        return await self._fetchall(
            f"""WITH m AS (
                    SELECT *,
                        CASE WHEN REPLACE(name, '_', ' ') = ? COLLATE NOCASE
                                  OR REPLACE(name, '_', ' ') LIKE ? THEN 0
                             WHEN name LIKE ? THEN 1 ELSE 2 END AS match_tier,
                        REPLACE(name, '_', '') || '@' || json_extract(refs, '$[0]') AS tkey
                    FROM names WHERE name LIKE ?{type_filter}),
                {prominence}
                SELECT m.*, COUNT(*) OVER () AS match_count FROM m {join}
                ORDER BY match_tier, {rank} json_array_length(m.refs) DESC, m.id
                LIMIT ?""",
            [query, f"{query} %", f"{pattern}%", f"%{pattern}%",
             *([name_type] if name_type else []), limit],
        )

    async def _acai_has_tipnr_keys(self) -> bool:
        """Whether acai_entities has the tipnr_keys column (databases before it do not)."""
        if self._acai_keys is None:
            async with self.conn.execute("PRAGMA table_info(acai_entities)") as cursor:
                self._acai_keys = any(row[1] == "tipnr_keys" for row in await cursor.fetchall())
        return self._acai_keys

    # =========================================================================
    # Morphology queries
    # =========================================================================

    async def get_morphology(self, code: str, language: str = "greek") -> dict | None:
        """Get morphology parsing for a code."""
        return await self._fetchone("SELECT * FROM morphology WHERE code = ? AND language = ?", (code, language.lower()))

    async def resolve_morphology(self, code: str, language: str | None = "greek") -> dict | None:
        """Find the table rows for a code as the tagged text prints it.

        Accepts compounds ('Hc/Vqw3ms', 'P-1NS + G2532=CONJ'), a missing
        language letter ('Vqp3ms') and any case ('v-aai-3s'); see
        ``morphology.morphology_lookups``. Returns {'language', 'parts':
        [(segment, row)]}; or {'language', 'ambiguous': [(segment, rows)]} when
        a segment matches only ignoring case and several codes then fit
        ('hc' is 'HC' or 'Hc'); or None.
        """
        ambiguous = None
        for lang, segments in morphology_lookups(code, language):
            parts, unclear = [], []
            for shown, stored in segments:
                row = await self.get_morphology(stored, lang)
                if row is None:
                    rows = await self._fetchall(
                        "SELECT * FROM morphology WHERE code = ? COLLATE NOCASE AND language = ? "
                        "ORDER BY code",
                        (stored, lang),
                    )
                    if not rows:
                        break
                    if len(rows) > 1:
                        unclear.append((shown, rows))
                        continue
                    row = rows[0]
                parts.append((shown, row))
            else:
                if not unclear:
                    return {"language": lang, "parts": parts}
                ambiguous = ambiguous or {"language": lang, "ambiguous": unclear}
        return ambiguous

    # =========================================================================
    # Vector similarity queries
    # =========================================================================

    async def get_verse_embedding(self, verse_id: int) -> list[float] | None:
        """Get the embedding vector for a verse."""
        async with self.conn.execute(
            "SELECT embedding FROM verse_vectors WHERE verse_id = ?",
            (verse_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                # sqlite-vec returns bytes, need to decode
                embedding_bytes = row[0]
                if embedding_bytes:
                    return list(struct.unpack(f'{len(embedding_bytes)//4}f', embedding_bytes))
            return None

    async def find_similar_verses(
        self,
        verse_id: int,
        limit: int = 10,
        exclude_same_chapter: bool = False
    ) -> list[dict]:
        """Find verses semantically similar to a given verse."""
        # Get the source verse's embedding
        embedding = await self.get_verse_embedding(verse_id)
        if not embedding:
            return []

        # Get source verse info for exclusion
        async with self.conn.execute(
            "SELECT book, chapter FROM verses WHERE id = ?",
            (verse_id,)
        ) as cursor:
            source = await cursor.fetchone()

        # Convert embedding to bytes for sqlite-vec
        embedding_bytes = struct.pack(f'{len(embedding)}f', *embedding)

        # Find similar verses
        sql = """
            SELECT v.id, v.reference, v.book, v.chapter, v.verse,
                   v.text_english, v.text_original,
                   vec_distance_cosine(vv.embedding, ?) as distance
            FROM verse_vectors vv
            JOIN verses v ON v.id = vv.verse_id
            WHERE vv.verse_id != ?
        """
        params = [embedding_bytes, verse_id]

        if exclude_same_chapter and source:
            sql += " AND NOT (v.book = ? AND v.chapter = ?)"
            params.extend([source['book'], source['chapter']])

        sql += " ORDER BY distance LIMIT ?"
        params.append(limit)
        return await self._fetchall(sql, params)

    async def find_similar_passages(
        self,
        reference: str,
        limit: int = 4
    ) -> list[dict]:
        """Find passages semantically similar to a verse reference.

        With the BSB loaded, each passage also carries ``preview_verses``: its
        first PASSAGE_PREVIEW_VERSES verse rows with ``text_bsb``, to show in
        place of the gloss in ``text_combined``.
        """
        # First, get the verse
        verse = await self.get_verse(reference)
        if not verse:
            return []

        verse_id = verse['id']

        # Get embedding for this verse
        embedding = await self.get_verse_embedding(verse_id)
        if not embedding:
            return []

        # Convert embedding to bytes for sqlite-vec
        embedding_bytes = struct.pack(f'{len(embedding)}f', *embedding)

        # sqlite-vec's nearest-neighbour search ranks by L2 distance. The
        # embeddings are unit vectors, so that is the cosine ranking, and the
        # cosine distance is L2² / 2. Passages containing the verse are dropped,
        # so ask for that many extra neighbours.
        containing = await self._fetchone(
            "SELECT COUNT(*) AS n FROM passages WHERE start_verse_id <= ? AND end_verse_id >= ?",
            (verse_id, verse_id),
        )
        sql = """
            WITH nearest AS (
                SELECT passage_id, distance FROM passage_vectors
                WHERE embedding MATCH ? AND k = ?
            )
            SELECT p.id, p.reference_start, p.reference_end, p.book,
                   p.start_verse_id, p.end_verse_id,
                   p.text_combined, p.verse_count, p.section_type,
                   nearest.distance * nearest.distance / 2 AS distance
            FROM nearest
            JOIN passages p ON p.id = nearest.passage_id
            WHERE NOT (p.start_verse_id <= ? AND p.end_verse_id >= ?)
            ORDER BY nearest.distance
            LIMIT ?
        """

        async with self.conn.execute(
            sql,
            (embedding_bytes, limit + containing["n"], verse_id, verse_id, limit)
        ) as cursor:
            rows = await cursor.fetchall()
            results = []
            for row in rows:
                d = dict(row)
                # Format reference range nicely
                if d['reference_start'] == d['reference_end']:
                    d['reference'] = d['reference_start']
                else:
                    d['reference'] = f"{d['reference_start']} - {d['reference_end']}"
                # Convert distance to similarity score (0-1, higher is better)
                d['similarity'] = 1.0 - d['distance']
                results.append(d)
        if await self.has_bsb_text():
            for d in results:
                d["preview_verses"] = await self.attach_bsb_text(await self._fetchall(
                    """SELECT reference, book, chapter, verse, text_english FROM verses
                       WHERE id BETWEEN ? AND ? ORDER BY id LIMIT ?""",
                    (d["start_verse_id"], d["end_verse_id"], PASSAGE_PREVIEW_VERSES),
                ))
        return results

    # =========================================================================
    # Graph queries (Theographic Bible Metadata)
    # =========================================================================

    async def _graph_people_columns(self) -> set[str]:
        if self._graph_people_cols is None:
            async with self.conn.execute("PRAGMA table_info(graph_people)") as cursor:
                self._graph_people_cols = {row[1] for row in await cursor.fetchall()}
        return self._graph_people_cols

    async def _graph_people_index(self) -> list[dict]:
        """Every person's naming columns and verse count, loaded once."""
        if self._people_index is None:
            available = await self._graph_people_columns()
            columns = [c for c in (*_PERSON_COLUMNS, "display_title", "surname") if c in available]
            people = await self._fetchall(f"SELECT {', '.join(columns)} FROM graph_people")
            async with self.conn.execute(
                """SELECT entity_id, COUNT(*) FROM graph_verse_mentions
                   WHERE entity_type = 'person' GROUP BY entity_id"""
            ) as cursor:
                counts = dict(await cursor.fetchall())
            for person in people:
                person.setdefault("display_title", None)
                person.setdefault("surname", None)
                person["verse_count"] = counts.get(person["id"], 0)
            self._people_index = people
        return self._people_index

    async def graph_find_person(self, name: str) -> list[dict]:
        """People matching a name, best match first.

        Tiers: a person id ('mary_1939'); a full title or name with surname
        ('Simon Peter', 'Pontius Pilate', 'Mary Magdalene'); the name or the
        title before its parenthesis ('Jacob' for 'Jacob (Israel)'); another
        name (a surname such as 'Peter', an alias such as 'Abram', a
        parenthesised alternative such as 'Israel'); a prefix of the name.
        Within a tier the person mentioned in the most verses comes first, so
        'Mary' is the mother of Jesus and 'Jacob' the patriarch. Each row
        carries ``match_tier`` and ``verse_count``.
        """
        query = _fold_name(name)
        if not query:
            return []
        raw = name.strip().casefold()
        found = []
        for person in await self._graph_people_index():
            tier = _person_match_tier(person, query, raw)
            if tier is not None:
                found.append({**person, "match_tier": tier})
        found.sort(key=lambda p: (p["match_tier"], -p["verse_count"], p["id"]))
        return found

    async def graph_find_place(self, name: str) -> list[dict]:
        """Find a place by name or id (fuzzy match).

        Orders by: the id itself, then the exact name, then names starting
        with the query, then other substring matches; among same-tier places
        the one with the most recorded events comes first (Samuel's Ramah,
        not the Ramah of Josh 18:25 with none), then the one mentioned in the
        most verses (the Ai of Joshua 7-8 over the Ai of Jer 49:3). Rows carry
        ``event_count`` and ``verse_count``.
        """
        return await self._fetchall(
            """SELECT p.*,
                   (SELECT COUNT(*) FROM graph_event_place_edges ep
                    WHERE ep.place_id = p.id) AS event_count,
                   (SELECT COUNT(*) FROM graph_verse_mentions vm
                    WHERE vm.entity_type = 'place' AND vm.entity_id = p.id) AS verse_count
               FROM graph_places p
               WHERE LOWER(p.name) LIKE LOWER(?) OR p.id = ?
               ORDER BY
                   CASE
                       WHEN p.id = ? THEN -1
                       WHEN LOWER(p.name) = LOWER(?) THEN 0
                       WHEN LOWER(p.name) LIKE LOWER(?) THEN 1
                       ELSE 2
                   END,
                   event_count DESC, verse_count DESC, p.id
               LIMIT 10""",
            (f"%{name}%", name.strip(), name.strip(), name, f"{name}%"),
        )

    async def graph_get_people(self, person_ids) -> dict[str, dict]:
        """Naming and date columns of the given people, by id."""
        wanted = set(person_ids)
        return {p["id"]: p for p in await self._graph_people_index() if p["id"] in wanted}

    async def graph_lineage(
        self, person_id: str, direction: str, generations: int, max_people: int = 200
    ) -> dict:
        """A person's ancestors (direction 'ancestors') or descendants, each person once.

        Walks father/mother links a generation at a time, so each relative is
        listed at the nearest generation it is reached, under the relative one
        generation nearer through whom it was first reached (``via``). Returns
        {"people": [row], "edges": [(parent_id, child_id, relationship)],
        "truncated": bool}, where edges are every recorded parent link among
        the people listed (including the starting person), and truncated says
        whether ``max_people`` cut the walk short.
        """
        up = direction == "ancestors"
        near_col, far_col = ("to_person_id", "from_person_id") if up else ("from_person_id", "to_person_id")
        generation_of = {person_id: 0}
        listed: list[dict] = []
        edges: dict[tuple, None] = {}
        frontier = [person_id]
        truncated = False
        for generation in range(1, generations + 1):
            if not frontier or truncated:
                break
            order = {pid: index for index, pid in enumerate(frontier)}
            placeholders = ", ".join("?" for _ in frontier)
            rows = await self._fetchall(
                f"""SELECT {near_col} AS near, {far_col} AS far, relationship_type
                    FROM graph_family_edges
                    WHERE {near_col} IN ({placeholders})
                      AND relationship_type IN ('father_of', 'mother_of')""",
                frontier,
            )
            rows.sort(key=lambda r: (order[r["near"]], r["relationship_type"] != "father_of", r["far"]))
            next_frontier = []
            for row in rows:
                parent, child = (row["far"], row["near"]) if up else (row["near"], row["far"])
                if row["far"] not in generation_of:
                    if len(listed) >= max_people:
                        truncated = True
                        continue
                    generation_of[row["far"]] = generation
                    listed.append({"id": row["far"], "generation": generation, "via": row["near"],
                                   "relationship": row["relationship_type"]})
                    next_frontier.append(row["far"])
                edges[(parent, child, row["relationship_type"])] = None
            frontier = next_frontier
        details = await self.graph_get_people([p["id"] for p in listed])
        for person in listed:
            person.update({k: v for k, v in details.get(person["id"], {}).items() if k != "id"})
            person.setdefault("name", person["id"])
        return {"people": listed, "edges": list(edges), "truncated": truncated}

    async def _family_adjacency(self) -> dict[str, list[tuple[str, str, int]]]:
        """Person id -> [(neighbour id, relationship from the person, cost)], loaded once.

        Parent and child links cost 1, siblings 2 (as a shared parent would),
        spouses 3, so a connection runs through descent where one exists.
        """
        if self._family_graph is None:
            adjacency: dict[str, list[tuple[str, str, int]]] = {}
            async with self.conn.execute(
                "SELECT from_person_id, to_person_id, relationship_type FROM graph_family_edges"
            ) as cursor:
                for source, target, relationship in await cursor.fetchall():
                    if relationship in ("father_of", "mother_of"):
                        forward, backward, cost = relationship, "child_of", 1
                    elif relationship == "sibling_of":
                        forward, backward, cost = relationship, relationship, 2
                    else:
                        forward, backward, cost = relationship, relationship, 3
                    adjacency.setdefault(source, []).append((target, forward, cost))
                    adjacency.setdefault(target, []).append((source, backward, cost))
            self._family_graph = adjacency
        return self._family_graph

    async def graph_find_path(self, person1_id: str, person2_id: str) -> list[dict]:
        """The closest family connection between two people, as steps.

        A cheapest-path search over the whole family graph (a few thousand
        people, so no depth cap), preferring parent-child lines to marriages
        and siblings, then fewer steps. God and the Holy Spirit are not used
        as links between people. Each step has current_id, next_id,
        relationship_type ('father_of', 'mother_of', 'child_of', 'sibling_of',
        'partner_of': what current is to next), from_name and to_name.
        Returns [] when the two are the same person or not connected.
        """
        if person1_id == person2_id:
            return []
        adjacency = await self._family_adjacency()
        best = {person1_id: (0, 0)}
        previous: dict[str, tuple[str, str]] = {}
        heap = [(0, 0, person1_id)]
        while heap:
            cost, steps, current = heapq.heappop(heap)
            if current == person2_id:
                break
            if (cost, steps) > best.get(current, (cost, steps)):
                continue
            if current in _NOT_FAMILY_LINKS and current != person1_id:
                continue
            for neighbour, relationship, weight in adjacency.get(current, ()):
                candidate = (cost + weight, steps + 1)
                if candidate < best.get(neighbour, (math.inf, math.inf)):
                    best[neighbour] = candidate
                    previous[neighbour] = (current, relationship)
                    heapq.heappush(heap, (*candidate, neighbour))
        if person2_id not in previous:
            return []
        chain = [person2_id]
        while chain[-1] != person1_id:
            chain.append(previous[chain[-1]][0])
        chain.reverse()
        names = await self.graph_get_people(chain)
        result = []
        for depth, (current, following) in enumerate(zip(chain, chain[1:]), start=1):
            result.append({
                "current_id": current,
                "next_id": following,
                "relationship_type": previous[following][1],
                "depth": depth,
                "from_name": _person_label(names.get(current), current),
                "to_name": _person_label(names.get(following), following),
            })
        return result

    async def graph_get_family(self, person_id: str) -> dict:
        """Immediate family of a person, each relative once."""
        family = {
            "parents": await self._fetchall(
                """SELECT p.*, e.relationship_type FROM graph_family_edges e
                   JOIN graph_people p ON p.id = e.from_person_id
                   WHERE e.to_person_id = ?
                     AND e.relationship_type IN ('father_of', 'mother_of')
                   ORDER BY e.relationship_type, p.id""",
                (person_id,),
            ),
            "children": await self._fetchall(
                """SELECT p.*, e.relationship_type FROM graph_family_edges e
                   JOIN graph_people p ON p.id = e.to_person_id
                   WHERE e.from_person_id = ?
                     AND e.relationship_type IN ('father_of', 'mother_of')
                   ORDER BY p.name, p.id""",
                (person_id,),
            ),
            "partners": await self._fetchall(
                """SELECT p.* FROM graph_family_edges e
                   JOIN graph_people p ON p.id = CASE
                       WHEN e.from_person_id = ? THEN e.to_person_id
                       ELSE e.from_person_id END
                   WHERE (e.from_person_id = ? OR e.to_person_id = ?)
                     AND e.relationship_type = 'partner_of'
                   ORDER BY p.name, p.id""",
                (person_id, person_id, person_id),
            ),
            "siblings": await self._fetchall(
                """SELECT p.* FROM graph_family_edges e
                   JOIN graph_people p ON p.id = CASE
                       WHEN e.from_person_id = ? THEN e.to_person_id
                       ELSE e.from_person_id END
                   WHERE (e.from_person_id = ? OR e.to_person_id = ?)
                     AND e.relationship_type = 'sibling_of'
                   ORDER BY p.name, p.id""",
                (person_id, person_id, person_id),
            ),
        }
        # Spouses are recorded from both sides, so each would appear twice
        for key, people in family.items():
            seen = set()
            family[key] = [p for p in people if not (p["id"] in seen or seen.add(p["id"]))]
        return family

    async def graph_relatives(self, person_ids: list[str]) -> dict[str, set[str]]:
        """Each given person's parents, children, spouses and siblings, as ids."""
        if not person_ids:
            return {}
        placeholders = ", ".join("?" for _ in person_ids)
        relatives: dict[str, set[str]] = {pid: set() for pid in person_ids}
        async with self.conn.execute(
            f"""SELECT from_person_id, to_person_id FROM graph_family_edges
                WHERE from_person_id IN ({placeholders}) OR to_person_id IN ({placeholders})""",
            [*person_ids, *person_ids],
        ) as cursor:
            for source, target in await cursor.fetchall():
                if source in relatives:
                    relatives[source].add(target)
                if target in relatives:
                    relatives[target].add(source)
        return relatives

    async def graph_get_person_events(self, person_id: str) -> list[dict]:
        """Every event a person took part in, in chronological order."""
        return await self._fetchall(
            """SELECT e.* FROM graph_person_event_edges pe
               JOIN graph_events e ON e.id = pe.event_id
               WHERE pe.person_id = ?
               ORDER BY e.sort_key, e.id""",
            (person_id,),
        )

    async def graph_get_events_places(self, event_ids: list[str]) -> dict[str, list[dict]]:
        """The places of each of the given events, by event id (one query)."""
        if not event_ids:
            return {}
        placeholders = ", ".join("?" for _ in event_ids)
        places: dict[str, list[dict]] = {}
        for row in await self._fetchall(
            f"""SELECT ep.event_id, p.* FROM graph_event_place_edges ep
                JOIN graph_places p ON p.id = ep.place_id
                WHERE ep.event_id IN ({placeholders})
                ORDER BY ep.event_id, p.name""",
            list(event_ids),
        ):
            places.setdefault(row.pop("event_id"), []).append(row)
        return places

    async def graph_get_event_verses(self, event_ids: list[str]) -> dict[str, list[str]]:
        """The Theographic verse references of each of the given events, by event id."""
        if not event_ids:
            return {}
        placeholders = ", ".join("?" for _ in event_ids)
        verses: dict[str, list[str]] = {}
        async with self.conn.execute(
            f"""SELECT entity_id, verse_ref FROM graph_verse_mentions
                WHERE entity_type = 'event' AND entity_id IN ({placeholders})""",
            list(event_ids),
        ) as cursor:
            for event_id, ref in await cursor.fetchall():
                verses.setdefault(event_id, []).append(ref)
        return verses

    async def graph_get_place_events(self, place_id: str) -> list[dict]:
        """Every event at a place, in chronological order."""
        return await self._fetchall(
            """SELECT e.* FROM graph_event_place_edges ep
               JOIN graph_events e ON e.id = ep.event_id
               WHERE ep.place_id = ?
               ORDER BY e.sort_key, e.id""",
            (place_id,),
        )

    async def graph_get_place_people(self, place_id: str) -> dict:
        """Get people born/died at a place."""
        return {
            "born_here": await self._fetchall("SELECT * FROM graph_people WHERE birth_place_id = ?", (place_id,)),
            "died_here": await self._fetchall("SELECT * FROM graph_people WHERE death_place_id = ?", (place_id,)),
            "visited": [],
        }

    # Map from our DB abbreviations to Theographic abbreviations
    _THEOGRAPHIC_BOOK_MAP = {
        "1Ch": "1Chr", "1Co": "1Cor", "1Jn": "1John", "1Ki": "1Kgs",
        "1Pe": "1Pet", "1Sa": "1Sam", "1Th": "1Thess", "1Ti": "1Tim",
        "2Ch": "2Chr", "2Co": "2Cor", "2Jn": "2John", "2Ki": "2Kgs",
        "2Pe": "2Pet", "2Sa": "2Sam", "2Th": "2Thess", "2Ti": "2Tim",
        "3Jn": "3John", "Act": "Acts", "Amo": "Amos", "Deu": "Deut",
        "Ecc": "Eccl", "Est": "Esth", "Exo": "Exod", "Ezk": "Ezek",
        "Jdg": "Judg", "Jhn": "John", "Jol": "Joel", "Jon": "Jonah",
        "Jos": "Josh", "Jud": "Jude", "Luk": "Luke", "Mat": "Matt",
        "Mrk": "Mark", "Nam": "Nah", "Oba": "Obad", "Phm": "Phlm",
        "Php": "Phil", "Pro": "Prov", "Psa": "Ps", "Rut": "Ruth",
        "Sng": "Song", "Tit": "Titus", "Zec": "Zech", "Zep": "Zeph",
    }

    def _to_theographic_ref(self, ref: str) -> str:
        """Convert our DB verse reference format to Theographic format."""
        parts = ref.split(".")
        if parts:
            parts[0] = self._THEOGRAPHIC_BOOK_MAP.get(parts[0], parts[0])
        return ".".join(parts)

    async def graph_get_verse_entities(
        self, verse_ref: str
    ) -> dict:
        """Get all entities mentioned in a verse."""
        result = {"people": [], "places": [], "events": []}
        theo_ref = self._to_theographic_ref(verse_ref)

        async with self.conn.execute(
            """SELECT vm.entity_type, vm.entity_id,
                      COALESCE(p.name, pl.name, e.title) as entity_name
               FROM graph_verse_mentions vm
               LEFT JOIN graph_people p ON vm.entity_type = 'person' AND p.id = vm.entity_id
               LEFT JOIN graph_places pl ON vm.entity_type = 'place' AND pl.id = vm.entity_id
               LEFT JOIN graph_events e ON vm.entity_type = 'event' AND e.id = vm.entity_id
               WHERE vm.verse_ref = ?""",
            (theo_ref,)
        ) as cursor:
            for row in await cursor.fetchall():
                d = dict(row)
                if d["entity_type"] == "person":
                    result["people"].append(d)
                elif d["entity_type"] == "place":
                    result["places"].append(d)
                elif d["entity_type"] == "event":
                    result["events"].append(d)

        return result

    async def graph_get_chapter_entities(
        self, book: str, chapter: int
    ) -> dict:
        """Get all entities mentioned in a chapter."""
        result = {"people": [], "places": [], "events": []}
        theo_book = self._THEOGRAPHIC_BOOK_MAP.get(book, book)
        ref_pattern = f"{theo_book}.{chapter}.%"

        async with self.conn.execute(
            """SELECT DISTINCT vm.entity_type, vm.entity_id,
                      COALESCE(p.name, pl.name, e.title) as entity_name
               FROM graph_verse_mentions vm
               LEFT JOIN graph_people p ON vm.entity_type = 'person' AND p.id = vm.entity_id
               LEFT JOIN graph_places pl ON vm.entity_type = 'place' AND pl.id = vm.entity_id
               LEFT JOIN graph_events e ON vm.entity_type = 'event' AND e.id = vm.entity_id
               WHERE vm.verse_ref LIKE ?""",
            (ref_pattern,)
        ) as cursor:
            for row in await cursor.fetchall():
                d = dict(row)
                if d["entity_type"] == "person":
                    result["people"].append(d)
                elif d["entity_type"] == "place":
                    result["places"].append(d)
                elif d["entity_type"] == "event":
                    result["events"].append(d)

        return result

    async def graph_get_passage_entities(
        self,
        book: str,
        start_chapter: int,
        start_verse: int | None,
        end_chapter: int,
        end_verse: int | None,
    ) -> dict:
        """Entities mentioned in a verse, verse range, chapter, or chapter range.

        Verse numbers are English; a None verse means the start or end of its
        chapter. Each entity is listed once, in order of its first mention.
        """
        result: dict[str, list[dict]] = {"people": [], "places": [], "events": []}
        theo_book = self._THEOGRAPHIC_BOOK_MAP.get(book, book)
        start = (start_chapter, start_verse if start_verse is not None else 0)
        end = (end_chapter, end_verse if end_verse is not None else _MAX_VERSE)
        mentions: list[tuple[tuple[int, int], dict]] = []
        for chapter in range(start_chapter, end_chapter + 1):
            for row in await self._fetchall(
                """SELECT vm.verse_ref, vm.entity_type, vm.entity_id,
                          COALESCE(p.name, pl.name, e.title) as entity_name
                   FROM graph_verse_mentions vm
                   LEFT JOIN graph_people p ON vm.entity_type = 'person' AND p.id = vm.entity_id
                   LEFT JOIN graph_places pl ON vm.entity_type = 'place' AND pl.id = vm.entity_id
                   LEFT JOIN graph_events e ON vm.entity_type = 'event' AND e.id = vm.entity_id
                   WHERE vm.verse_ref LIKE ?""",
                (f"{theo_book}.{chapter}.%",),
            ):
                verse = row.pop("verse_ref").rsplit(".", 1)[-1]
                if verse.isdecimal() and start <= (chapter, int(verse)) <= end:
                    mentions.append(((chapter, int(verse)), row))
        seen: set[tuple[str, str]] = set()
        kinds = {"person": "people", "place": "places", "event": "events"}
        for _, row in sorted(mentions, key=lambda mention: mention[0]):
            key = (row["entity_type"], row["entity_id"])
            if key in seen or row["entity_type"] not in kinds:
                continue
            seen.add(key)
            result[kinds[row["entity_type"]]].append(row)
        return result

    async def graph_has_data(self) -> bool:
        """Check if graph tables have data."""
        return await self._table_has_rows("graph_people")

    async def has_vector_tables(self) -> bool:
        """Check if vector tables exist and have data."""
        if not self._vec_loaded:
            return False
        return await self._table_has_rows("verse_vectors")

    # =========================================================================
    # Aquifer content queries
    # =========================================================================

    # Book abbreviation to 2-digit number for BBCCCVVV references
    _BOOK_ABBR_TO_NUM = {
        "Gen": "01", "Exo": "02", "Lev": "03", "Num": "04", "Deu": "05",
        "Jos": "06", "Jdg": "07", "Rut": "08", "1Sa": "09", "2Sa": "10",
        "1Ki": "11", "2Ki": "12", "1Ch": "13", "2Ch": "14", "Ezr": "15",
        "Neh": "16", "Est": "17", "Job": "18", "Psa": "19", "Pro": "20",
        "Ecc": "21", "Sng": "22", "Isa": "23", "Jer": "24", "Lam": "25",
        "Ezk": "26", "Dan": "27", "Hos": "28", "Jol": "29", "Amo": "30",
        "Oba": "31", "Jon": "32", "Mic": "33", "Nam": "34", "Hab": "35",
        "Zep": "36", "Hag": "37", "Zec": "38", "Mal": "39",
        "Mat": "40", "Mrk": "41", "Luk": "42", "Jhn": "43", "Act": "44",
        "Rom": "45", "1Co": "46", "2Co": "47", "Gal": "48", "Eph": "49",
        "Php": "50", "Col": "51", "1Th": "52", "2Th": "53", "1Ti": "54",
        "2Ti": "55", "Tit": "56", "Phm": "57", "Heb": "58", "Jas": "59",
        "1Pe": "60", "2Pe": "61", "1Jn": "62", "2Jn": "63", "3Jn": "64",
        "Jud": "65", "Rev": "66",
    }

    def _to_aquifer_ref(self, normalized_ref: str) -> str | None:
        """Convert normalized reference 'Gen.1.1' to Aquifer 8-digit format '01001001'."""
        parts = normalized_ref.split('.')
        if len(parts) != 3:
            return None
        book_num = self._BOOK_ABBR_TO_NUM.get(parts[0])
        if not book_num:
            return None
        try:
            chapter = int(parts[1])
            verse = int(parts[2])
            return f"{book_num}{chapter:03d}{verse:03d}"
        except (ValueError, IndexError):
            return None

    async def has_aquifer_data(self) -> bool:
        """Check if aquifer_content table exists and has data."""
        return await self._table_has_rows("aquifer_content")

    async def get_study_notes(self, reference: str) -> list[dict]:
        """Get study notes + translation notes for a verse reference.

        Fetches study_notes, translation_notes_uw, and translation_notes_sil
        for a specific verse. Matches both exact refs and ranges containing the verse.
        """
        normalized = self._normalize_reference(reference)
        aq_ref = self._to_aquifer_ref(normalized)
        if not aq_ref:
            return []

        return await self._fetchall("""
            SELECT * FROM aquifer_content
            WHERE resource_type IN ('study_notes', 'translation_notes_uw', 'translation_notes_sil')
              AND (
                start_ref = ?
                OR (start_ref <= ? AND end_ref >= ? AND is_range = 1)
              )
            ORDER BY resource_type, start_ref
        """, (aq_ref, aq_ref, aq_ref))

    async def get_chapter_study_notes(self, book: str, chapter: int) -> list[dict]:
        """Get all study notes for an entire chapter."""
        book_num = self._BOOK_ABBR_TO_NUM.get(book)
        if not book_num:
            return []

        return await self._fetchall("""
            SELECT * FROM aquifer_content
            WHERE resource_type IN ('study_notes', 'translation_notes_uw', 'translation_notes_sil')
              AND book = ?
              AND chapter_start = ?
            ORDER BY resource_type, start_ref
        """, (book, chapter))

    async def get_study_notes_in_span(
        self, book: str, start_chapter: int, start_verse: int, end_chapter: int, end_verse: int
    ) -> list[dict]:
        """Study and translation notes overlapping a verse span, in verse order per source.

        A short note (at most six verses) that starts earlier in the span's first
        chapter and runs into the span (Romans 8:19-21 for 'Romans 8:20-22') is
        included; a longer section overview is not, so a continuation call
        ('Mark 13:32-37') does not repeat the overview of Mark 13:1-37.
        """
        book_num = self._BOOK_ABBR_TO_NUM.get(book)
        if not book_num:
            return []
        chapter_start = f"{book_num}{start_chapter:03d}000"
        low = f"{book_num}{start_chapter:03d}{start_verse:03d}"
        high = f"{book_num}{end_chapter:03d}{end_verse:03d}"
        return await self._fetchall("""
            SELECT * FROM aquifer_content
            WHERE resource_type IN ('study_notes', 'translation_notes_uw', 'translation_notes_sil')
              AND start_ref BETWEEN ? AND ?
              AND COALESCE(end_ref, start_ref) >= ?
              AND (start_ref >= ? OR CAST(end_ref AS INTEGER) - CAST(start_ref AS INTEGER) <= 5)
            ORDER BY resource_type, start_ref, end_ref
        """, (chapter_start, high, low, low))

    # Articles get_bible_dictionary returns when no title is the topic itself:
    # each is a page of up to ~4,000 characters, so "Gilboa" (no such title)
    # once returned ten (Mount Gilboa, Saul, David, Jerusalem, ...; ~24 KB).
    DICTIONARY_FALLBACK_LIMIT = 4

    async def _search_aquifer_by_type(
        self, resource_type: str, query: str, limit: int = DICTIONARY_FALLBACK_LIMIT
    ) -> list[dict]:
        """Search aquifer_content by type: every exact title match, else at most
        ``limit`` LIKE matches, titles containing the query first ('Mount Gilboa'
        for 'Gilboa'), then articles that only mention it, shortest title first."""
        exact = await self._fetchall(
            "SELECT * FROM aquifer_content WHERE resource_type = ? AND LOWER(title) = LOWER(?)",
            (resource_type, query),
        )
        if exact:
            return exact

        pattern = f"%{query}%"
        return await self._fetchall(
            """SELECT * FROM aquifer_content
               WHERE resource_type = ?
                 AND (LOWER(title) LIKE LOWER(?) OR LOWER(content_plain) LIKE LOWER(?))
               ORDER BY
                 CASE WHEN LOWER(title) LIKE LOWER(?) THEN 0 ELSE 1 END,
                 LENGTH(title), content_id
               LIMIT ?""",
            (resource_type, pattern, pattern, pattern, limit),
        )

    async def get_bible_dictionary(self, topic: str) -> list[dict]:
        """Search the Bible dictionary by title or content."""
        return await self._search_aquifer_by_type("dictionary", topic)

    # Key-term rows with no text: the Aquifer export's audio-only duplicates.
    _KEY_TERM_TEXT = "TRIM(COALESCE(content_plain, '')) NOT IN ('', 'Audio Content')"

    async def find_key_terms(self, term: str, limit: int = 2) -> dict:
        """FIA Key Terms whose title matches ``term``, exactly or nearly.

        Titles are matched case-insensitively: an exact title first; otherwise
        near titles (one a prefix of the other, 'righteous' -> 'righteousness';
        a title containing the term as a word; or a close spelling). Entries
        that only mention the term in their text are never returned as matches,
        and audio-only stubs ('Audio Content') are skipped.

        Returns ``{"entries": [...] (at most ``limit``), "match": "exact" |
        "near" | None, "other_titles": [further matching titles],
        "mentions": [up to 4 titles whose entries mention the term most, when
        no title matched]}``.
        """
        titles = [
            row["title"] for row in await self._fetchall(
                f"""SELECT DISTINCT title FROM aquifer_content
                    WHERE resource_type = 'key_terms' AND {self._KEY_TERM_TEXT}
                    ORDER BY LOWER(title)"""
            )
        ]
        wanted = " ".join(re.findall(r"\w+", term.lower()))
        result: dict = {"entries": [], "match": None, "other_titles": [], "mentions": []}
        if not wanted:
            return result

        def key(title: str) -> str:
            return " ".join(re.findall(r"\w+", title.lower()))

        def closeness(title: str) -> float:
            return difflib.SequenceMatcher(None, key(title), wanted).ratio()

        def near(title: str) -> bool:
            shorter, longer = sorted((key(title), wanted), key=len)
            return (
                (len(shorter) >= 4 and longer.startswith(shorter) and len(longer) - len(shorter) <= 4)
                or (len(wanted) >= 4 and re.search(rf"\b{re.escape(wanted)}\b", key(title)) is not None)
                or closeness(title) >= 0.85
            )

        exact = [title for title in titles if key(title) == wanted]
        nearby = sorted(
            (title for title in titles if title not in exact and near(title)),
            key=lambda title: -closeness(title),
        )
        matched = exact or nearby
        if matched:
            shown = matched[:limit]
            rows = await self._fetch_in(
                f"""SELECT * FROM aquifer_content
                    WHERE resource_type = 'key_terms' AND {self._KEY_TERM_TEXT} AND title IN""",
                shown,
            )
            rows.sort(key=lambda row: (shown.index(row["title"]), row["content_id"]))
            result.update(
                entries=rows,
                match="exact" if exact else "near",
                other_titles=[title for title in (exact + nearby) if title not in shown],
            )
            return result

        # No title matched: name the entries that mention the term most often.
        mentions = await self._fetchall(
            f"""SELECT title,
                       (LENGTH(LOWER(content_plain))
                        - LENGTH(REPLACE(LOWER(content_plain), ?, ''))) / LENGTH(?) AS hits
                FROM aquifer_content
                WHERE resource_type = 'key_terms' AND {self._KEY_TERM_TEXT}
                  AND LOWER(content_plain) LIKE ?
                ORDER BY hits DESC, LENGTH(title), title
                LIMIT 4""",
            (wanted, wanted, f"%{wanted}%"),
        )
        result["mentions"] = [row["title"] for row in mentions]
        return result

    async def search_aquifer_content(
        self,
        query: str,
        resource_type: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """Generic full-text search across any Aquifer resource type."""
        pattern = f"%{query}%"
        params: list = [pattern, pattern]

        sql = """
            SELECT * FROM aquifer_content
            WHERE (LOWER(title) LIKE LOWER(?) OR LOWER(content_plain) LIKE LOWER(?))
        """

        if resource_type:
            sql += " AND resource_type = ?"
            params.append(resource_type)

        sql += " ORDER BY CASE WHEN LOWER(title) LIKE LOWER(?) THEN 0 ELSE 1 END, LENGTH(title) LIMIT ?"
        params.extend([pattern, limit])

        return await self._fetchall(sql, params)

    # =========================================================================
    # ACAI entity queries
    # =========================================================================

    async def has_acai_data(self) -> bool:
        """Check if acai_entities table exists and has data."""
        return await self._table_has_rows("acai_entities")

    async def get_acai_entities_for_names(self, entries: list[dict]) -> list[dict | None]:
        """The ACAI entity of each names entry, or None if ACAI has none.

        A names entry is a TIPNR entry, identified by its name and first
        reference ('Ezra@Ezr.7.1'), and ACAI lists the TIPNR entries each of
        its entities is (tipnr_keys), so namesakes such as the Ezra of
        Neh.12.1 get their own entity, never the scribe's. Where a place and
        its people share an entry (Edom, the Edomites), the entry's own type
        wins. One query for all the entries.
        """
        keys = []
        for entry in entries:
            try:
                refs = json.loads(entry.get("refs") or "[]")
            except (TypeError, ValueError):
                refs = []
            # ACAI writes some TIPNR names without the underscore ('MaryMagdalene')
            keys.append(f"{entry['name'].replace('_', '')}@{refs[0]}" if refs else None)
        wanted = sorted({key for key in keys if key})
        if not wanted:
            return [None] * len(entries)

        placeholders = ", ".join("?" for _ in wanted)
        rows = await self._fetchall(
            f"""SELECT REPLACE(k.value, '_', '') AS tipnr_key, a.*
                FROM acai_entities a, json_each(a.tipnr_keys) k
                WHERE REPLACE(k.value, '_', '') IN ({placeholders})""",
            wanted,
        )
        found = []
        for entry, key in zip(entries, keys):
            entity_type = entry.get("type")
            own_id = f"{entity_type}:{re.sub(r'[ _]', '', entry['name'])}".lower()
            candidates = [row for row in rows if row["tipnr_key"] == key]
            if not candidates:
                found.append(None)
                continue
            best = dict(max(
                candidates,
                key=lambda row: (row["entity_type"] == entity_type, row["id"].lower() == own_id,
                                 row["reference_count"] or 0),
            ))
            del best["tipnr_key"]
            found.append(best)
        return found

    # =========================================================================
    # ANE (Ancient Near East) context queries
    # =========================================================================

    async def has_ane_data(self) -> bool:
        """Check if ane_entries table exists and has data."""
        return await self._table_has_rows("ane_entries")

    async def get_ane_dimensions(self) -> list[dict]:
        """Get all available ANE dimensions with entry counts."""
        return await self._fetchall("""
            SELECT dimension, dimension_label, COUNT(*) as entry_count
            FROM ane_entries
            GROUP BY dimension, dimension_label
            ORDER BY dimension
        """)

    async def get_ane_context(
        self,
        reference: str | None = None,
        dimension: str | None = None,
        period: str | None = None,
        limit: int = 30,
    ) -> list[dict]:
        """Get ANE context entries filtered by reference, dimension, and/or period.

        Args:
            reference: Bible reference (e.g., "Genesis 1:1") - finds entries mapped to that book/chapter
            dimension: ANE dimension key (e.g., "cosmology_worldview")
            period: Timeline period (e.g., "patriarchal")
            limit: Max results to return
        """
        params: list = []
        conditions: list[str] = []
        join_clause = ""
        # Extra columns for relevance scoring when querying by reference
        extra_cols = ""
        order_clause = "ORDER BY e.dimension, e.period"

        if reference:
            # Book and chapter of a verse, range, or chapter ("Gen. 15:6",
            # "Genesis 15"); an unparseable reference matches nothing.
            parsed = self.parse_passage_reference(reference)
            if not parsed:
                return []
            book_abbr = parsed["book"]
            chapter = parsed["start_chapter"]

            join_clause = " JOIN ane_book_mappings bm ON e.id = bm.entry_id"
            conditions.append("bm.book = ?")
            params.append(book_abbr)

            if chapter is not None:
                conditions.append(
                    "(bm.chapter_start IS NULL OR (bm.chapter_start <= ? AND (bm.chapter_end IS NULL OR bm.chapter_end >= ?)))"
                )
                params.extend([chapter, chapter])

            # Relevance scoring: tighter chapter ranges = more relevant
            extra_cols = """,
                CASE
                    WHEN bm.chapter_start IS NULL THEN 1000
                    ELSE (COALESCE(bm.chapter_end, bm.chapter_start) - bm.chapter_start + 1)
                END AS relevance_score,
                CASE WHEN bm.chapter_start IS NOT NULL THEN 'direct' ELSE 'broad' END AS match_type"""
            order_clause = "ORDER BY relevance_score, e.dimension, e.period"

        if dimension:
            conditions.append("e.dimension = ?")
            params.append(dimension)

        if period:
            conditions.append("e.period = ?")
            params.append(period)

        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""

        sql = f"""
            SELECT DISTINCT e.*{extra_cols}
            FROM ane_entries e{join_clause}{where}
            {order_clause}
            LIMIT ?
        """
        params.append(limit)

        return await self._fetchall(sql, params)

    # =========================================================================
    # Torah Weave queries (Moshe Kline's Woven Torah hypothesis)
    # =========================================================================

    async def has_torah_weave_data(self) -> bool:
        """Check if torah_weave tables exist and have data."""
        return await self._table_has_rows("torah_weave_units")

    async def _torah_hebrew_numbering(self, book: str) -> tuple[dict, dict]:
        """(English -> Hebrew, Hebrew -> English) verse lists for a book's renumbered verses.

        Kline's Torah Weave data numbers verses like the Hebrew Bible (Leviticus
        5:20-26 is English 6:1-7, Deuteronomy 28:69 is English 29:1); the
        `verses` table's English(Hebrew) rows pair the two. Verses absent from
        both maps are numbered alike.
        """
        if book not in self._torah_numbering:
            english_to_hebrew: dict[tuple[int, int], list[tuple[int, int]]] = {}
            hebrew_to_english: dict[tuple[int, int], list[tuple[int, int]]] = {}
            for row in await self._fetchall(
                "SELECT reference FROM verses WHERE book = ? AND reference LIKE '%(%' ORDER BY id", (book,)
            ):
                match = _SPLIT_REFERENCE_RE.match(row["reference"])
                if not match or match.group(4) != "(":
                    continue
                _, chapter, verse, _, hebrew_chapter, hebrew_verse = match.groups()
                english = (int(chapter), int(verse))
                hebrew = (int(hebrew_chapter), int(hebrew_verse))
                english_to_hebrew.setdefault(english, []).append(hebrew)
                hebrew_to_english.setdefault(hebrew, []).append(english)
            # An English verse that also has a plain row ('Num.26.1' beside
            # 'Num.26.1(25.19)') includes the Hebrew verse of its own number.
            plain = {
                row["reference"]
                for row in await self._fetch_in(
                    "SELECT reference FROM verses WHERE reference IN",
                    [f"{book}.{chapter}.{verse}" for chapter, verse in english_to_hebrew],
                )
            }
            for (chapter, verse), hebrew in english_to_hebrew.items():
                if f"{book}.{chapter}.{verse}" in plain:
                    hebrew.append((chapter, verse))
                    hebrew_to_english.setdefault((chapter, verse), []).append((chapter, verse))
            self._torah_numbering[book] = (english_to_hebrew, hebrew_to_english)
        return self._torah_numbering[book]

    async def _torah_english_range(
        self, book: str, start: tuple[int, int], end: tuple[int, int]
    ) -> tuple[int, int, int, int]:
        """English (chapter, verse, end chapter, end verse) of a Hebrew-numbered range."""
        _, hebrew_to_english = await self._torah_hebrew_numbering(book)
        first = min(hebrew_to_english.get(start, [start]))
        last = max(hebrew_to_english.get(end, [end]))
        return (*first, *last)

    async def _english_torah_cells(self, book: str, cells: list[dict]) -> list[dict]:
        """Renumber cells' (and their units') Hebrew verse ranges in English, in place."""
        for cell in cells:
            c1, v1, c2, v2 = await self._torah_english_range(
                book, (cell["chapter_start"], cell["verse_start"]), (cell["chapter_end"], cell["verse_end"])
            )
            cell.update(chapter_start=c1, verse_start=v1, chapter_end=c2, verse_end=v2,
                        verse_range=_format_chapter_range(c1, v1, c2, v2))
            if cell.get("unit_verses"):
                cell["unit_verses"] = await self._english_unit_verses(book, cell["unit_verses"])
        return cells

    async def _english_unit_verses(self, book: str, verses: str) -> str:
        """'Leviticus 6:1-7:38' (Hebrew numbers) -> 'Leviticus 6:8-7:38'."""
        match = re.match(r"^(.*?)\s*(\d+):(\d+)(?:-(?:(\d+):)?(\d+))?$", verses)
        if not match:
            return verses
        name, c1, v1, c2, v2 = match.groups()
        start = (int(c1), int(v1))
        end = (int(c2 or c1), int(v2)) if v2 else start
        return f"{name} {_format_chapter_range(*await self._torah_english_range(book, start, end))}".strip()

    async def get_torah_weave_cells_for_reference(
        self, reference: str
    ) -> list[dict]:
        """Find all Torah Weave cells that contain the given (English) verse.

        Returns cells joined with their parent unit metadata. Multiple cells
        may match if a verse sits within both a cell and a sibling subdivision
        in the same unit, or if units overlap at their boundaries. Kline's
        Hebrew verse numbers are matched and shown in English numbering.
        """
        normalized = self._normalize_reference(reference)
        parts = normalized.split(".")
        if len(parts) < 3:
            return []
        book_abbr = parts[0]
        try:
            chapter = int(parts[1])
            verse = int(parts[2])
        except ValueError:
            return []

        # Only Torah books have weave data
        if book_abbr not in ("Gen", "Exo", "Lev", "Num", "Deu"):
            return []

        english_to_hebrew, _ = await self._torah_hebrew_numbering(book_abbr)
        cells: dict[int, dict] = {}
        for hebrew_chapter, hebrew_verse in english_to_hebrew.get((chapter, verse), [(chapter, verse)]):
            target = hebrew_chapter * 1000 + hebrew_verse
            for cell in await self._fetchall(
                """
                SELECT c.*,
                       u.id AS unit_serial,
                       u.book_full AS unit_book_full,
                       u.unit_number AS unit_number,
                       u.title AS unit_title,
                       u.verses AS unit_verses,
                       u.verse_range AS unit_verse_range,
                       u.format AS unit_format,
                       u.irregular AS unit_irregular,
                       u.is_unique AS unit_is_unique,
                       u.cell_count AS unit_cell_count,
                       u.type AS unit_type
                FROM torah_weave_cells c
                JOIN torah_weave_units u ON u.id = c.unit_id
                WHERE c.book = ?
                  AND c.sort_start <= ?
                  AND c.sort_end >= ?
                ORDER BY (c.sort_end - c.sort_start) ASC, c.row_num, c.column_letter
                """,
                (book_abbr, target, target),
            ):
                cells.setdefault(cell["id"], cell)
        return await self._english_torah_cells(book_abbr, list(cells.values()))

    async def get_torah_weave_unit_cells(self, unit_id: int) -> list[dict]:
        """Get all cells for a given unit, ordered by row then column then subdivision.

        Verse ranges are in English numbering.
        """
        cells = await self._fetchall(
            """
            SELECT * FROM torah_weave_cells
            WHERE unit_id = ?
            ORDER BY row_num, column_letter,
                     CASE WHEN subdivision IS NULL THEN '' ELSE subdivision END
            """,
            (unit_id,),
        )
        return await self._english_torah_cells(cells[0]["book"], cells) if cells else cells

    async def get_torah_weave_units_in_passage(
        self, book: str, start: tuple[int, int], end: tuple[int, int]
    ) -> list[dict]:
        """Torah Weave units overlapping an English-numbered passage, in order.

        Each unit carries ``verses`` in English numbering and ``cells``: its
        cells, as from ``get_torah_weave_unit_cells``.
        """
        english_to_hebrew, _ = await self._torah_hebrew_numbering(book)
        first = min(english_to_hebrew.get(start, [start]))
        last = max(english_to_hebrew.get(end, [end]))
        units = []
        for unit in await self._fetchall(
            "SELECT * FROM torah_weave_units WHERE book = ? ORDER BY id", (book,)
        ):
            match = re.match(r"^(\d+):(\d+)(?:-(?:(\d+):)?(\d+))?$", unit["verse_range"].strip())
            if not match:
                continue
            c1, v1, c2, v2 = match.groups()
            unit_start = (int(c1), int(v1))
            unit_end = (int(c2 or c1), int(v2)) if v2 else unit_start
            if unit_start <= last and first <= unit_end:
                unit["verses"] = await self._english_unit_verses(book, unit["verses"])
                unit["cells"] = await self.get_torah_weave_unit_cells(unit["id"])
                units.append(unit)
        return units

    # =========================================================================
    # Theological scholarship queries (unified: Heiser, Bradley, etc.)
    # =========================================================================

    async def has_theology_data(self, author: str | None = None) -> bool:
        """Check if theology_content table exists and has data."""
        if author:
            rows = await self._fetchall(
                "SELECT 1 FROM theology_content WHERE source_author = ? LIMIT 1",
                (author,),
            )
            return bool(rows)
        return await self._table_has_rows("theology_content")

    async def get_theology_authors(self) -> list[str]:
        """The author keys that have scholarship entries, alphabetically."""
        rows = await self._fetchall(
            "SELECT DISTINCT source_author FROM theology_content ORDER BY source_author"
        )
        return [row["source_author"] for row in rows]

    async def theology_theme_exists(self, theme_key: str) -> bool:
        """True when ``theme_key`` names a theology theme."""
        return bool(await self._fetchone(
            "SELECT 1 FROM theology_themes WHERE theme_key = ?", (theme_key,)
        ))

    async def get_theology_context_by_reference(
        self, reference: str, author: str | None = None, limit: int = 4
    ) -> list[dict]:
        """Get scholarship entries relevant to a verse or chapter, optionally filtered by author.

        A verse returns the entries indexed to it, else those indexed to its
        chapter; a chapter reference ('Psalm 82') returns the chapter's entries.
        """
        normalized = self._normalize_reference(reference)
        parts = normalized.split(".")
        if len(parts) != 3:
            # Not a verse: read it as a chapter ('Psalm 82', 'Rom 3'), which
            # skips the exact-verse query and ranks the chapter's entries.
            parsed = self.parse_passage_reference(reference)
            if not parsed or parsed["start_verse"] is not None:
                return []
            normalized = None
            parts = [parsed["book"], str(parsed["start_chapter"])]
        book = parts[0] if parts else ""
        chapter = int(parts[1]) if len(parts) > 1 else None

        params: list = []
        conditions = []

        if book:
            conditions.append("vi.book = ?")
            params.append(book)
        if chapter:
            conditions.append("vi.chapter = ?")
            params.append(chapter)

        author_filter = ""
        if author:
            author_filter = " AND tc.source_author = ?"

        # Try exact verse match first, then chapter-level
        exact_params: list = [normalized]
        if author:
            exact_params.append(author)
        exact_params.append(limit)

        # Rank each entry by its best match: primary before secondary/supporting
        # (the two non-primary labels are used by different authors' datasets),
        # then by verse, then by id so ties are stable. relevance is TEXT, so
        # sorting it directly would put 'supporting' ahead of 'primary'. With a
        # single MIN() aggregate, SQLite takes matched_ref and relevance from
        # the row that produced the minimum.
        best_match = (
            "MIN(CASE vi.relevance WHEN 'primary' THEN 0 ELSE 1 END * 1000"
            " + COALESCE(vi.verse, 0)) AS match_rank"
        )
        exact = normalized and await self._fetchall(
            f"""SELECT tc.*, vi.reference AS matched_ref, vi.relevance, {best_match},
                      GROUP_CONCAT(DISTINCT tt.theme_key) AS themes
               FROM theology_content tc
               JOIN theology_verse_index vi ON tc.id = vi.content_id
               LEFT JOIN theology_theme_index tti ON tc.id = tti.content_id
               LEFT JOIN theology_themes tt ON tti.theme_key = tt.theme_key
               WHERE vi.reference = ?{author_filter}
               GROUP BY tc.id
               ORDER BY match_rank, tc.id
               LIMIT ?""",
            exact_params,
        )
        if exact:
            return _sort_theme_lists(exact)

        # Fall back to chapter-level
        where = f" AND {' AND '.join(conditions)}" if conditions else ""
        if author:
            where += " AND tc.source_author = ?"
            params.append(author)
        return _sort_theme_lists(await self._fetchall(
            f"""SELECT tc.*, vi.reference AS matched_ref, vi.relevance, {best_match},
                       GROUP_CONCAT(DISTINCT tt.theme_key) AS themes
                FROM theology_content tc
                JOIN theology_verse_index vi ON tc.id = vi.content_id
                LEFT JOIN theology_theme_index tti ON tc.id = tti.content_id
                LEFT JOIN theology_themes tt ON tti.theme_key = tt.theme_key
                WHERE 1=1{where}
                GROUP BY tc.id
                ORDER BY match_rank, tc.id
                LIMIT ?""",
            (*params, limit),
        ))

    async def get_theology_context_by_theme(
        self, theme_key: str, author: str | None = None, limit: int = 4
    ) -> list[dict]:
        """Get scholarship entries for a given theme, optionally filtered by author.

        Entries alternate between authors (each author's in id order), so a
        small limit still shows every scholar's view of the theme.
        """
        author_filter = ""
        params: list = [theme_key]
        if author:
            author_filter = " AND tc.source_author = ?"
            params.append(author)
        params.append(limit)
        return await self._fetchall(
            f"""SELECT * FROM (
                   SELECT tc.*, tt.theme_label, tt.description AS theme_description,
                          GROUP_CONCAT(DISTINCT vi.reference) AS verse_refs
                   FROM theology_content tc
                   JOIN theology_theme_index tti ON tc.id = tti.content_id
                   JOIN theology_themes tt ON tti.theme_key = tt.theme_key
                   LEFT JOIN theology_verse_index vi ON tc.id = vi.content_id
                   WHERE tti.theme_key = ?{author_filter}
                   GROUP BY tc.id
               )
               ORDER BY ROW_NUMBER() OVER (PARTITION BY source_author ORDER BY id),
                        source_author, id
               LIMIT ?""",
            params,
        )

    async def get_theology_themes(self, author: str | None = None) -> list[dict]:
        """List all theological themes, optionally filtered to those with entries by a specific author."""
        if author:
            return await self._fetchall(
                """SELECT tt.*,
                          (SELECT COUNT(*) FROM theology_theme_index tti
                           JOIN theology_content tc ON tti.content_id = tc.id
                           WHERE tti.theme_key = tt.theme_key AND tc.source_author = ?) AS entry_count
                   FROM theology_themes tt
                   WHERE EXISTS (
                       SELECT 1 FROM theology_theme_index tti
                       JOIN theology_content tc ON tti.content_id = tc.id
                       WHERE tti.theme_key = tt.theme_key AND tc.source_author = ?
                   )
                   ORDER BY tt.theme_key""",
                (author, author),
            )
        return await self._fetchall(
            """SELECT tt.*,
                      (SELECT COUNT(*) FROM theology_theme_index tti WHERE tti.theme_key = tt.theme_key) AS entry_count
               FROM theology_themes tt
               ORDER BY tt.theme_key"""
        )


    async def compare_biblical_versions(
        self,
        reference: str,
        versions: list[str],
        numbering: str = "canonical",
    ) -> dict:
        """Return MT/LXX edition rows for a verse, range, or chapter.

        ``numbering="canonical"`` reads the reference in MT/English numbering;
        ``"lxx"`` reads it in the Greek edition's own numbering, which is the
        only way to reach LXX-only verses (they have no canonical position).
        Books without an MT (Tobit, Sirach, ...) always use edition numbering.

        Returns a dict with ``status`` (``ok``, ``invalid_reference``,
        ``unsupported_book``, ``new_testament``, ``missing_data``,
        ``no_match``), ``book``, ``numbering``, ``lxx_only_book``, ``rows``
        in display order, and ``lxx_only`` (edition refs of LXX-only verses in
        the requested Greek-numbered range, for canonical lookups).
        """
        result: dict[str, Any] = {
            "status": "ok", "book": None, "numbering": numbering,
            "lxx_only_book": False, "rows": [], "lxx_only": [],
        }
        parsed = parse_passage_reference(reference)
        if parsed is None:
            result["status"] = "invalid_reference"
            return result
        book_name, book, start, end = parsed
        result["book"] = book or book_name
        if book in _NT_BOOKS:
            result["status"] = "new_testament"
            return result
        if book not in _MT_BOOKS and book not in _LXX_ONLY_BOOKS:
            result["status"] = "unsupported_book"
            return result
        if book in _LXX_ONLY_BOOKS:
            result["lxx_only_book"] = True
            numbering = result["numbering"] = "lxx"

        needs_lxx_table = "LXX" in versions or numbering == "lxx"
        if needs_lxx_table and not await self._table_has_rows("biblical_version_verses"):
            result["status"] = "missing_data"
            return result

        version_order = {version: index for index, version in enumerate(versions)}
        lxx_columns = """edition, canonical_reference, canonical_book, canonical_chapter,
                         canonical_verse, canonical_verse_suffix, edition_reference,
                         edition_chapter, edition_verse, edition_verse_suffix,
                         text, translation, morphology, mapping_method,
                         brenton_greek_differs, brenton_greek, brenton_greek_difference"""

        if numbering == "lxx":
            lxx_rows = [
                _lxx_row(row) for row in await self._fetchall(
                    f"""SELECT {lxx_columns} FROM biblical_version_verses
                        WHERE edition_book = ?
                          AND (edition_chapter, edition_verse, edition_verse_suffix)
                              BETWEEN (?, ?, ?) AND (?, ?, ?)
                        ORDER BY edition_chapter, edition_verse, edition_verse_suffix,
                                 edition, canonical_chapter, canonical_verse""",
                    (book, *start, *end),
                )
            ]
            groups: dict[str, list[dict]] = {}
            for row in lxx_rows:
                groups.setdefault(_group_key(row), [])
                if "LXX" in versions:
                    groups[_group_key(row)].append(row)
            if "MT" in versions:
                wanted: dict[tuple[str, int], set[int]] = {}
                for row in lxx_rows:
                    if row["canonical_book"] in _MT_BOOKS and not row["canonical_verse_suffix"]:
                        wanted.setdefault(
                            (row["canonical_book"], row["canonical_chapter"]), set()
                        ).add(row["canonical_verse"])
                for (mt_book, chapter), verse_numbers in wanted.items():
                    for row in await self._fetch_mt_rows(mt_book, (chapter, 0, ""), (chapter, 9999, "~")):
                        if row["canonical_verse"] in verse_numbers:
                            groups[row["canonical_reference"]].append(row)
            for rows in groups.values():
                rows.sort(key=lambda row: (
                    version_order.get(row["version"], len(version_order)),
                    row["edition"], row["_edition_position"],
                ))
                result["rows"].extend(rows)
        else:
            rows = []
            if "MT" in versions:
                rows.extend(await self._fetch_mt_rows(book, start, end))
            if "LXX" in versions:
                rows.extend(
                    _lxx_row(row) for row in await self._fetchall(
                        f"""SELECT {lxx_columns} FROM biblical_version_verses
                            WHERE canonical_book = ?
                              AND (canonical_chapter, canonical_verse, canonical_verse_suffix)
                                  BETWEEN (?, ?, ?) AND (?, ?, ?)""",
                        (book, *start, *end),
                    )
                )
                result["lxx_only"] = await self._fetchall(
                    """SELECT edition, edition_reference FROM biblical_version_verses
                       WHERE canonical_book IS NULL AND edition_book = ?
                         AND (edition_chapter, edition_verse, edition_verse_suffix)
                             BETWEEN (?, ?, ?) AND (?, ?, ?)
                       ORDER BY edition_chapter, edition_verse, edition_verse_suffix, edition""",
                    (book, *start, *end),
                )
            rows.sort(key=lambda row: (
                row["canonical_chapter"], row["canonical_verse"], row["canonical_verse_suffix"],
                version_order.get(row["version"], len(version_order)),
                row["edition"], row["_edition_position"],
            ))
            result["rows"] = rows

        for row in result["rows"]:
            del row["_edition_position"]
        if not result["rows"]:
            result["status"] = "no_match"
        return result

    async def _fetch_mt_rows(
        self,
        book: str,
        start: tuple[int, int, str],
        end: tuple[int, int, str],
    ) -> list[dict]:
        """Build MT edition rows from TAHOT `verses` (English canonical numbering)."""
        verses = await self._fetchall(
            """SELECT reference, chapter, verse, text_original, text_english, word_data
               FROM verses
               WHERE book = ? AND text_original IS NOT NULL
                 AND (chapter, verse, '') BETWEEN (?, ?, ?) AND (?, ?, ?)
               ORDER BY chapter, verse, id""",
            (book, *start, *end),
        )
        rows = []
        for verse in verses:
            canonical = f"{book}.{verse['chapter']}.{verse['verse']}"
            hebrew = _HEBREW_NUMBERING_RE.search(verse["reference"])
            edition_position = (
                (int(hebrew.group(1)), int(hebrew.group(2)), "") if hebrew
                else (verse["chapter"], verse["verse"], "")
            )
            rows.append({
                "version": "MT",
                "edition": MT_EDITION,
                "language": "Hebrew",
                "canonical_reference": canonical,
                "canonical_book": book,
                "canonical_chapter": verse["chapter"],
                "canonical_verse": verse["verse"],
                "canonical_verse_suffix": "",
                "edition_reference": f"{book}.{edition_position[0]}.{edition_position[1]}",
                "text": verse["text_original"],
                "translation": verse["text_english"],
                "translation_label": MT_TRANSLATION_LABEL,
                "license": MT_LICENSE,
                "source_url": MT_SOURCE_URL,
                "morphology": verse["word_data"],
                "mapping_method": MT_VERSIFICATION_METHOD if hebrew else "identity",
                "_edition_position": edition_position,
            })
        return rows


    async def ancient_schema_status(self) -> str:
        """``missing`` (no passages table), ``outdated`` (lacks current columns), or ``ready``.

        An outdated database must be upgraded (``scripts/upgrade_database.py``)
        before the ancient-source tools can query it.
        """
        present: dict[str, set[str]] = {}
        for table in ANCIENT_REQUIRED_COLUMNS:
            rows = await self._fetchall(f"PRAGMA table_info({table})")
            present[table] = {row["name"] for row in rows}
        if not present["ancient_source_passages"]:
            return "missing"
        for table, columns in ANCIENT_REQUIRED_COLUMNS.items():
            if not set(columns) <= present[table]:
                return "outdated"
        return "ready"

    async def search_ancient_sources(
        self,
        query: str,
        corpus: str | None = "josephus",
        biblical_reference: str | None = None,
        period: str | None = None,
        limit: int = 4,
    ) -> dict:
        """Full-text search licensed ancient sources with optional indexed filters.

        ``corpus`` is a registered corpus key, or None for every corpus.
        Only the passage text (English and the folded original) is searched;
        the work title and reference columns are display metadata, so a query
        word that only appears in a title ("Jewish", "War", "Life") does not
        match. Passages containing every term come first, then any term; only
        if neither finds anything are Hebrew/Aramaic prefix-stripped variants
        searched (``prefix_match`` is then True).
        Returns a dict with ``status`` (``ok``, ``invalid_query``,
        ``invalid_reference``, ``corpus_missing``, ``outdated_schema``,
        ``no_link``, ``no_match``), ``rows``, ``terms`` (the folded search
        terms), ``match`` (``all`` when every term matched, ``any`` for the
        any-term fallback), ``prefix_match``, and for ``no_link`` the
        ``link_count`` and ``linked_passage_count`` in scope.
        """
        terms: list[str] = []
        # Marks are stripped before tokenizing: Python's \w does not match
        # Hebrew niqqud or cantillation, which would otherwise split words.
        # Editorial signs are deleted as in the index, so a word pasted from
        # a transcription ('אלמנ֯[ו]ת') is searched whole.
        for token in re.findall(r"\w+", _strip_marks(strip_editorial_signs(query))):
            if token in _FTS_OPERATORS:
                continue
            for term in re.findall(r"\w+", fold_ancient_search_text(token)):
                if term not in terms:
                    terms.append(term)
        result: dict[str, Any] = {
            "status": "ok", "rows": [], "terms": terms, "match": None, "prefix_match": False,
            "variants": {},
        }
        if not terms:
            result["status"] = "invalid_query"
            return result

        link_range = None
        if biblical_reference:
            link_range = parse_ancient_biblical_reference(biblical_reference)
            if link_range is None:
                result["status"] = "invalid_reference"
                return result

        schema = await self.ancient_schema_status()
        if schema == "outdated":
            result["status"] = "outdated_schema"
            return result
        corpus_condition, corpus_params = ("p.corpus = ?", [corpus]) if corpus else ("1", [])
        present = schema == "ready" and await self._fetchone(
            f"SELECT 1 FROM ancient_source_passages p WHERE {corpus_condition} LIMIT 1",
            corpus_params,
        )
        if not present:
            result["status"] = "corpus_missing"
            return result

        where = ["ancient_source_passages_fts MATCH ?", corpus_condition]
        params: list[Any] = list(corpus_params)
        if period:
            where.append("(',' || p.period_tags || ',') LIKE ?")
            params.append(f"%,{period},%")
        if link_range:
            link_condition = """EXISTS (
                       SELECT 1 FROM ancient_source_biblical_links bl
                       WHERE bl.passage_id = p.id
                         AND bl.biblical_book = ?
                         AND bl.sort_start <= ?
                         AND bl.sort_end >= ?
                   )"""
            link_params = (link_range[0], link_range[2], link_range[1])
            linked = await self._fetchone(
                f"""SELECT 1 FROM ancient_source_passages p
                    WHERE {corpus_condition} AND {link_condition} LIMIT 1""",
                [*corpus_params, *link_params],
            )
            if linked is None:
                coverage = await self._fetchone(
                    f"""SELECT COUNT(*) AS link_count,
                              COUNT(DISTINCT bl.passage_id) AS linked_passage_count
                       FROM ancient_source_biblical_links bl
                       JOIN ancient_source_passages p ON p.id = bl.passage_id
                       WHERE {corpus_condition}""",
                    corpus_params,
                )
                result.update(status="no_link", **coverage)
                return result
            where.append(link_condition)
            params.extend(link_params)

        exact = "{text original_text_folded}"
        widened = "{text original_text_folded original_prefix_variants}"
        variants = await self._ancient_spelling_variants(terms)
        result["variants"] = variants
        # A term matches itself or any spelling variant of it.
        term_queries = [
            "(" + " OR ".join(f'"{word}"' for word in [term, *variants.get(term, ())]) + ")"
            for term in terms
        ]
        stages = [(exact, "all", " AND "), (exact, "any", " OR ")]
        if any(_HEBREW_WORD.fullmatch(term) for term in terms):
            stages += [(widened, "all", " AND "), (widened, "any", " OR ")]

        async def search(match_query: str, size: int) -> list[dict]:
            return await self._fetchall(
                f"""SELECT p.*, bm25(ancient_source_passages_fts) AS rank
                    FROM ancient_source_passages_fts
                    JOIN ancient_source_passages p
                      ON p.id = ancient_source_passages_fts.passage_id
                    WHERE {' AND '.join(where)}
                    ORDER BY rank, p.corpus, p.work_title, p.sort_start
                    LIMIT ?""",
                [match_query, *params, size],
            )

        rows: list[dict] = []
        for columns, match, operator in stages:
            if match == "any" and len(terms) == 1:
                continue
            rows = await search(f"{columns} : ({operator.join(term_queries)})", limit)
            if rows and match == "all" and columns == exact and len(terms) > 1:
                # Passages with the words as a phrase ('son of man') come first.
                phrase = await search(f'{columns} : ("{" ".join(terms)}")', limit)
                phrase_ids = {row["id"] for row in phrase}
                rows = (phrase + [row for row in rows if row["id"] not in phrase_ids])[:limit]
            if rows:
                result["match"] = match
                result["prefix_match"] = columns == widened
                break
        if not rows:
            result["status"] = "no_match"
            return result
        result["rows"] = await self._attach_ancient_annotations(rows)
        return result

    async def ancient_corpus_has_english(self, corpus: str) -> bool:
        """True when some passage of ``corpus`` has English text to search."""
        return bool(await self._fetchone(
            "SELECT 1 FROM ancient_source_passages WHERE corpus = ? AND text != '' LIMIT 1",
            (corpus,),
        ))

    async def _ancient_spelling_variants(self, terms: list[str]) -> dict[str, list[str]]:
        """Index words spelled like each Latin-script search term ('melchizedek' ->
        ['melchisedec', 'melchisedek']), read from the full-text index's vocabulary."""
        variants: dict[str, list[str]] = {}
        wanted = [
            term for term in terms
            if len(term) >= _MIN_VARIANT_LETTERS and re.fullmatch(r"[a-z]+", term)
        ]
        if not wanted:
            return variants
        try:
            await self.conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS temp.ancient_search_vocab "
                "USING fts5vocab(main, 'ancient_source_passages_fts', 'row')"
            )
        except Exception:
            return variants
        for term in wanted:
            key = spelling_key(term)
            if len(key) < _MIN_VARIANT_LETTERS - 1:
                continue
            found = []
            for letter in _SPELLING_FIRST_LETTERS.get(key[0], key[0]):
                rows = await self._fetchall(
                    "SELECT term FROM temp.ancient_search_vocab WHERE term >= ? AND term < ?",
                    (letter, chr(ord(letter) + 1)),
                )
                found += [
                    row["term"] for row in rows
                    if row["term"] != term and spelling_key(row["term"]) == key
                ]
            if found:
                variants[term] = sorted(found)[:_MAX_SPELLING_VARIANTS]
        return variants

    async def lookup_ancient_passages(
        self,
        corpus: str,
        work_key: str,
        sort_start: int,
        sort_end: int,
        limit: int,
    ) -> dict:
        """Passages of one work whose sort range overlaps ``[sort_start, sort_end]``.

        Returns ``status`` ``outdated_schema`` (tables predate the current
        schema), ``corpus_missing`` (no rows with sort keys, e.g. a corpus
        imported before the multi-corpus schema), ``out_of_range`` (with the
        work's imported ``first``/``last`` keys, the nearest ``before`` and
        ``after`` references, and any ``gap_notes`` covering the range), or
        ``ok`` with ``rows`` in citation order (at most ``limit``) and ``total``.
        """
        schema = await self.ancient_schema_status()
        if schema == "outdated":
            return {"status": "outdated_schema"}
        present = schema == "ready" and await self._fetchone(
            """SELECT 1 FROM ancient_source_passages
               WHERE corpus = ? AND sort_start IS NOT NULL LIMIT 1""",
            (corpus,),
        )
        if not present:
            return {"status": "corpus_missing"}

        work = "corpus = ? AND work_key = ?"
        overlap = f"{work} AND sort_start <= ? AND sort_end >= ?"
        params = (corpus, work_key, sort_end, sort_start)
        total = (await self._fetchone(
            f"SELECT COUNT(*) AS total FROM ancient_source_passages WHERE {overlap}", params
        ))["total"]
        if not total:
            bounds = await self._fetchone(
                f"""SELECT MIN(sort_start) AS first, MAX(sort_end) AS last
                    FROM ancient_source_passages WHERE {work}""",
                (corpus, work_key),
            )
            before = await self._fetchone(
                f"""SELECT reference FROM ancient_source_passages
                    WHERE {work} AND sort_end < ? ORDER BY sort_end DESC LIMIT 1""",
                (corpus, work_key, sort_start),
            )
            after = await self._fetchone(
                f"""SELECT reference FROM ancient_source_passages
                    WHERE {work} AND sort_start > ? ORDER BY sort_start LIMIT 1""",
                (corpus, work_key, sort_end),
            )
            gap_notes = await self._fetchall(
                f"""SELECT DISTINCT citation, kind, note, contrast, aligned
                    FROM ancient_source_notes
                    WHERE {work} AND kind = 'gap' AND sort_start <= ? AND sort_end >= ?
                    ORDER BY sort_start""",
                params,
            )
            return {
                "status": "out_of_range",
                **bounds,
                "before": before["reference"] if before else None,
                "after": after["reference"] if after else None,
                "gap_notes": gap_notes,
            }
        rows = await self._fetchall(
            f"""SELECT * FROM ancient_source_passages WHERE {overlap}
                ORDER BY sort_start, sort_end LIMIT ?""",
            (*params, limit),
        )
        return {
            "status": "ok",
            "rows": await self._attach_ancient_annotations(rows),
            "total": total,
        }

    async def first_ancient_passage(self, corpus: str, work_key: str) -> dict | None:
        """The first imported passage of a work (its sort keys and reference), or None."""
        try:
            return await self._fetchone(
                """SELECT reference, sort_start, sort_end FROM ancient_source_passages
                   WHERE corpus = ? AND work_key = ? AND sort_start IS NOT NULL
                   ORDER BY sort_start LIMIT 1""",
                (corpus, work_key),
            )
        except sqlite3.OperationalError:
            return None

    async def _attach_ancient_annotations(self, rows: list[dict]) -> list[dict]:
        """Attach typed biblical links and editorial notes to ancient-source passage rows."""
        passage_ids = [row["id"] for row in rows]
        placeholders = ",".join("?" for _ in passage_ids)
        links = await self._fetchall(
            f"""SELECT passage_id, biblical_book, sort_start, sort_end,
                       relationship_note, relation
                FROM ancient_source_biblical_links
                WHERE passage_id IN ({placeholders})
                ORDER BY CASE relation WHEN 'aligned' THEN 0 WHEN 'contrast' THEN 1
                         WHEN 'echo' THEN 2 ELSE 3 END, biblical_book, sort_start""",
            passage_ids,
        )
        notes = await self._fetchall(
            f"""SELECT passage_id, citation, kind, note, contrast, aligned
                FROM ancient_source_notes
                WHERE passage_id IN ({placeholders})
                ORDER BY sort_start, id""",
            passage_ids,
        )
        links_by_passage: dict[int, list[dict]] = {}
        for link in links:
            links_by_passage.setdefault(link["passage_id"], []).append(link)
        notes_by_passage: dict[int, list[dict]] = {}
        for note in notes:
            notes_by_passage.setdefault(note["passage_id"], []).append(note)
        for row in rows:
            row["biblical_links"] = links_by_passage.get(row["id"], [])
            row["editorial_notes"] = notes_by_passage.get(row["id"], [])
        return rows


    async def textual_variant_schema_status(self) -> str:
        """Classify the textual-variant tables: legacy, missing, empty, or ready.

        ``legacy`` means the old mixed ``textual_variants`` table is still present
        (``create_schema`` may have added empty new tables beside it), so the
        database must be migrated before the new tables can be trusted.
        """
        tables = {
            row["name"]
            for row in await self._fetchall(
                """SELECT name FROM sqlite_master WHERE type = 'table'
                   AND name IN ('textual_variants', 'textual_variant_cases')"""
            )
        }
        if "textual_variants" in tables:
            return "legacy"
        if "textual_variant_cases" not in tables:
            return "missing"
        if not await self._table_has_rows("textual_variant_cases"):
            return "empty"
        return "ready"

    async def get_textual_variant_cases_in_span(
        self,
        book: str,
        start_chapter: int,
        start_verse: int,
        end_chapter: int,
        end_verse: int,
    ) -> list[dict]:
        """Return (chapter, verse, case_key) for cases inside an English-numbered span.

        Empty when the table is absent or empty, so lookup_verse degrades on
        databases that have not been upgraded.
        """
        if not await self._table_has_rows("textual_variant_cases"):
            return []
        return await self._fetchall(
            """SELECT chapter, verse, case_key FROM textual_variant_cases
               WHERE book = ?
                 AND chapter * 1000 + verse BETWEEN ? AND ?
               ORDER BY chapter, verse, id""",
            (
                book,
                start_chapter * 1000 + start_verse,
                end_chapter * 1000 + end_verse,
            ),
        )

    async def get_textual_variant_cases(self, reference: str) -> list[dict]:
        """Get textual variant cases with each kind of claim kept separate.

        Witness rows are split by evidence type: manuscript witnesses stay on
        the reading they support, while NT citations, indirect evidence, and
        "not preserved" notes are returned as separate case-level lists.
        Critical judgments without a source citation are returned as
        ``unsourced_summaries`` rather than ``critical_judgments``.
        """
        normalized = self._normalize_reference(reference)
        cases = await self._fetchall(
            "SELECT * FROM textual_variant_cases WHERE reference = ? ORDER BY id",
            (normalized,),
        )
        for case in cases:
            case_id = case["id"]
            case["kind"] = (
                "interpretive" if case["case_key"] in INTERPRETIVE_CASE_KEYS else "manuscript"
            )
            readings = await self._fetchall(
                """SELECT * FROM textual_variant_readings
                   WHERE case_id = ? ORDER BY id""",
                (case_id,),
            )
            readings_by_id = {reading["id"]: reading for reading in readings}
            for reading in readings:
                reading["witnesses"] = []
            case["citation_evidence"] = []
            case["indirect_evidence"] = []
            case["not_preserved_in"] = []
            witnesses = await self._fetchall(
                """SELECT reading_id, witness, evidence_type, reading_support,
                          approximate_date, source_citation, source_url
                   FROM textual_variant_witnesses
                   WHERE case_id = ? ORDER BY id""",
                (case_id,),
            )
            for witness in witnesses:
                reading = readings_by_id.get(witness["reading_id"])
                if reading is not None:
                    witness["reading_key"] = reading["reading_key"]
                    witness["tradition"] = reading["tradition"]
                evidence_type = witness["evidence_type"]
                if evidence_type == "manuscript":
                    reading["witnesses"].append(witness)
                elif evidence_type == "citation":
                    case["citation_evidence"].append(witness)
                elif evidence_type == "indirect":
                    case["indirect_evidence"].append(witness)
                else:
                    case["not_preserved_in"].append(witness)
            case["manuscript_evidence"] = readings
            judgments = await self._fetchall(
                """SELECT judgment, attribution, source_citation, source_url
                   FROM textual_critical_judgments
                   WHERE case_id = ? ORDER BY id""",
                (case_id,),
            )
            case["critical_judgments"] = [
                judgment for judgment in judgments if judgment.get("source_citation")
            ]
            case["unsourced_summaries"] = [
                judgment for judgment in judgments if not judgment.get("source_citation")
            ]
            case["theological_interpretations"] = await self._fetchall(
                """SELECT interpretation, attribution, source_citation, source_url
                   FROM textual_theological_interpretations
                   WHERE case_id = ? ORDER BY id""",
                (case_id,),
            )
            case["author_specific_claims"] = await self._fetchall(
                """SELECT author, claim, source_citation, source_url
                   FROM textual_author_claims
                   WHERE case_id = ? ORDER BY id""",
                (case_id,),
            )
            case["translation_decisions"] = await self._fetchall(
                """SELECT translation, preferred_reading, rationale
                   FROM textual_translation_decisions
                   WHERE case_id = ? ORDER BY id""",
                (case_id,),
            )
        return cases

    async def get_nt_ot_lxx_quote_hints(self, reference: str) -> list[dict]:
        """Return NT↔OT LXX-form quotation hints for either the NT or OT side.

        Matches a verse looked up on either side of the quotation: an OT lookup
        of Psalm 40:6 returns the Heb 10:5-7 hint, and a NT lookup of Heb 10:5
        returns the same row. Used by lookup_verse to emit a one-line nudge so
        the agent can follow up with get_textual_variant when relevant.
        """
        normalized = self._normalize_reference(reference)
        return await self._fetchall(
            """SELECT * FROM nt_ot_lxx_quote_hints
                WHERE nt_reference = ? OR ot_reference = ?
                ORDER BY id""",
            (normalized, normalized),
        )

    async def get_hlt_verse(self, reference: str) -> dict | None:
        """Get the HLT translation for a single verse."""
        normalized = self._normalize_reference(reference)
        return await self._fetchone(
            "SELECT * FROM hlt_verses WHERE reference = ?", (normalized,)
        )

    async def get_hlt_annotations(self, reference: str) -> list[dict]:
        """Get HLT bracket annotations for a verse."""
        normalized = self._normalize_reference(reference)
        return await self._fetchall(
            "SELECT * FROM hlt_annotations WHERE reference = ? ORDER BY word_position",
            (normalized,),
        )

    async def get_hlt_study_notes(
        self, reference: str, note_type: str | None = None
    ) -> list[dict]:
        """Get HLT study notes for a verse, optionally filtered by type."""
        normalized = self._normalize_reference(reference)
        if note_type:
            return await self._fetchall(
                "SELECT * FROM hlt_study_notes WHERE reference = ? AND note_type = ? ORDER BY priority",
                (normalized, note_type),
            )
        return await self._fetchall(
            "SELECT * FROM hlt_study_notes WHERE reference = ? ORDER BY priority",
            (normalized,),
        )

    async def upsert_hlt_verse(self, data: dict) -> int:
        """Insert or update an HLT verse translation. Returns the row id."""
        sql = """INSERT INTO hlt_verses
                    (reference, book, chapter, verse, hlt_text, hlt_text_annotated,
                     base_text_source, variant_used, word_data_hlt, translation_notes,
                     confidence, status, last_updated)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                 ON CONFLICT(reference) DO UPDATE SET
                    hlt_text=excluded.hlt_text,
                    hlt_text_annotated=excluded.hlt_text_annotated,
                    base_text_source=excluded.base_text_source,
                    variant_used=excluded.variant_used,
                    word_data_hlt=excluded.word_data_hlt,
                    translation_notes=excluded.translation_notes,
                    confidence=excluded.confidence,
                    status=excluded.status,
                    last_updated=excluded.last_updated"""
        async with self._conn.execute(sql, (
            data["reference"], data["book"], data["chapter"], data["verse"],
            data["hlt_text"], data["hlt_text_annotated"],
            data.get("base_text_source", "MT"), data.get("variant_used"),
            data.get("word_data_hlt"), data.get("translation_notes"),
            data.get("confidence", "high"), data.get("status", "draft"),
        )) as cursor:
            await self._conn.commit()
            return cursor.lastrowid

    async def upsert_hlt_annotation(self, data: dict) -> int:
        """Insert or update an HLT bracket annotation."""
        sql = """INSERT INTO hlt_annotations
                    (reference, annotation_type, annotation_text, word_position,
                     explanation, heiser_content_id)
                 VALUES (?, ?, ?, ?, ?, ?)
                 ON CONFLICT(reference, annotation_type, word_position) DO UPDATE SET
                    annotation_text=excluded.annotation_text,
                    explanation=excluded.explanation,
                    heiser_content_id=excluded.heiser_content_id"""
        async with self._conn.execute(sql, (
            data["reference"], data["annotation_type"], data["annotation_text"],
            data.get("word_position"), data["explanation"],
            data.get("heiser_content_id"),
        )) as cursor:
            await self._conn.commit()
            return cursor.lastrowid

    async def upsert_hlt_study_note(self, data: dict) -> int:
        """Insert or update an HLT study note. Returns the row id."""
        sql = """INSERT INTO hlt_study_notes
                    (reference, book, chapter, verse, note_type, title, content,
                     heiser_content_ids, related_verses, priority)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                 ON CONFLICT(reference, note_type, title) DO UPDATE SET
                    content=excluded.content,
                    heiser_content_ids=excluded.heiser_content_ids,
                    related_verses=excluded.related_verses,
                    priority=excluded.priority"""
        async with self._conn.execute(sql, (
            data["reference"], data["book"], data["chapter"], data["verse"],
            data["note_type"], data["title"], data["content"],
            data.get("heiser_content_ids"), data.get("related_verses"),
            data.get("priority", 5),
        )) as cursor:
            await self._conn.commit()
            return cursor.lastrowid


def create_schema(conn: sqlite3.Connection):
    """Create the database schema."""
    conn.executescript("""
        -- Lexicon table for Greek and Hebrew words
        CREATE TABLE IF NOT EXISTS lexicon (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            strongs TEXT UNIQUE NOT NULL,
            language TEXT NOT NULL,
            word TEXT,
            transliteration TEXT,
            pronunciation TEXT,
            short_definition TEXT,
            full_definition TEXT,
            etymology TEXT,
            usage_count INTEGER DEFAULT 0,
            semantic_domain TEXT,
            related_words TEXT,
            abbott_smith_def TEXT,
            nt_occurrences INTEGER,
            lxx_hebrew TEXT,
            synonyms TEXT,
            sense_hierarchy TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_lexicon_strongs ON lexicon(strongs);
        CREATE INDEX IF NOT EXISTS idx_lexicon_language ON lexicon(language);

        -- Verses table for tagged Bible text
        CREATE TABLE IF NOT EXISTS verses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reference TEXT UNIQUE NOT NULL,
            book TEXT,
            chapter INTEGER,
            verse INTEGER,
            text_english TEXT,
            text_original TEXT,
            word_data TEXT,
            section_end TEXT  -- 'paragraph' (NT), 'petuchah' (OT major), 'setumah' (OT minor), or NULL
        );
        CREATE INDEX IF NOT EXISTS idx_verses_reference ON verses(reference);
        CREATE INDEX IF NOT EXISTS idx_verses_book ON verses(book);

        -- Berean Standard Bible (public domain), one row per English verse in
        -- canonical order: the readable English the verse tools show. Imported
        -- by parsers/bsb.py; the index mirrors the production table.
        CREATE TABLE IF NOT EXISTS bsb_verses (
            reference TEXT UNIQUE NOT NULL,
            book TEXT NOT NULL,
            chapter INTEGER,
            verse INTEGER,
            text TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_bsb_ref ON bsb_verses(reference);

        -- Passages table (verses grouped by section markers)
        CREATE TABLE IF NOT EXISTS passages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reference_start TEXT NOT NULL,    -- e.g., "Mat.1.1"
            reference_end TEXT NOT NULL,      -- e.g., "Mat.1.17"
            book TEXT NOT NULL,
            start_verse_id INTEGER NOT NULL,
            end_verse_id INTEGER NOT NULL,
            text_combined TEXT NOT NULL,      -- Full passage text for embedding
            verse_count INTEGER NOT NULL,
            section_type TEXT,                -- 'paragraph', 'petuchah', 'setumah'
            FOREIGN KEY (start_verse_id) REFERENCES verses(id),
            FOREIGN KEY (end_verse_id) REFERENCES verses(id)
        );
        CREATE INDEX IF NOT EXISTS idx_passages_book ON passages(book);
        CREATE INDEX IF NOT EXISTS idx_passages_refs ON passages(reference_start, reference_end);

        -- Biblical names table
        CREATE TABLE IF NOT EXISTS names (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            name_original TEXT,
            type TEXT,
            description TEXT,
            refs TEXT,
            relationships TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_names_name ON names(name);
        CREATE INDEX IF NOT EXISTS idx_names_type ON names(type);

        -- Cross references
        -- type: 'ch' (Harrison/Romhild curated), 'tsk' (Treasury of Scripture
        -- Knowledge via openbible.info), or NULL for legacy/manual entries.
        -- relevance: per-source ranking signal — CH uses 0..3 (Orig*2+Circ),
        -- TSK uses raw vote counts. Higher = stronger.
        CREATE TABLE IF NOT EXISTS cross_references (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            target TEXT NOT NULL,
            type TEXT,
            note TEXT,
            relevance INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_xref_source ON cross_references(source);
        CREATE INDEX IF NOT EXISTS idx_xref_source_rank
            ON cross_references(source, type, relevance DESC);

        -- Thematic references
        CREATE TABLE IF NOT EXISTS thematic_references (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            theme TEXT NOT NULL,
            reference TEXT NOT NULL,
            note TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_theme_name ON thematic_references(theme);

        -- Morphology codes
        CREATE TABLE IF NOT EXISTS morphology (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL,
            language TEXT NOT NULL,
            parsing TEXT,
            part_of_speech TEXT,
            person TEXT,
            number TEXT,
            tense TEXT,
            voice TEXT,
            mood TEXT,
            case_value TEXT,
            gender TEXT,
            UNIQUE(code, language)
        );
        CREATE INDEX IF NOT EXISTS idx_morph_code ON morphology(code);

        -- =====================================================================
        -- Graph tables (Theographic Bible Metadata)
        -- =====================================================================

        -- People nodes
        CREATE TABLE IF NOT EXISTS graph_people (
            id TEXT PRIMARY KEY,          -- e.g., "aaron_1"
            name TEXT NOT NULL,
            also_called TEXT,
            gender TEXT,
            birth_year INTEGER,
            death_year INTEGER,
            birth_place_id TEXT,
            death_place_id TEXT,
            description TEXT,
            display_title TEXT,           -- e.g. "Simon Peter"; NULL when it is the name
            surname TEXT                  -- e.g. "Peter", "Pilate", "Magdalene"
        );
        CREATE INDEX IF NOT EXISTS idx_graph_people_name ON graph_people(name);

        -- Place nodes
        CREATE TABLE IF NOT EXISTS graph_places (
            id TEXT PRIMARY KEY,          -- e.g., "eden_354"
            name TEXT NOT NULL,
            latitude REAL,
            longitude REAL,
            feature_type TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_graph_places_name ON graph_places(name);

        -- Event nodes
        CREATE TABLE IF NOT EXISTS graph_events (
            id TEXT PRIMARY KEY,          -- event_id as text
            title TEXT NOT NULL,
            start_year INTEGER,           -- astronomical: 0 is 1 BC, -3 is 4 BC
            duration TEXT,
            sort_key REAL                 -- chronological rank (parsers/theographic.py)
        );
        CREATE INDEX IF NOT EXISTS idx_graph_events_title ON graph_events(title);

        -- People group nodes
        CREATE TABLE IF NOT EXISTS graph_people_groups (
            name TEXT PRIMARY KEY,
            members TEXT                  -- JSON array of person IDs
        );

        -- Family relationship edges
        CREATE TABLE IF NOT EXISTS graph_family_edges (
            from_person_id TEXT NOT NULL,
            to_person_id TEXT NOT NULL,
            relationship_type TEXT NOT NULL,  -- father_of, mother_of, partner_of, sibling_of
            PRIMARY KEY (from_person_id, to_person_id, relationship_type)
        );
        CREATE INDEX IF NOT EXISTS idx_graph_family_from ON graph_family_edges(from_person_id);
        CREATE INDEX IF NOT EXISTS idx_graph_family_to ON graph_family_edges(to_person_id);

        -- Person-event participation edges
        CREATE TABLE IF NOT EXISTS graph_person_event_edges (
            person_id TEXT NOT NULL,
            event_id TEXT NOT NULL,
            PRIMARY KEY (person_id, event_id)
        );
        CREATE INDEX IF NOT EXISTS idx_graph_pe_person ON graph_person_event_edges(person_id);
        CREATE INDEX IF NOT EXISTS idx_graph_pe_event ON graph_person_event_edges(event_id);

        -- Event-place edges
        CREATE TABLE IF NOT EXISTS graph_event_place_edges (
            event_id TEXT NOT NULL,
            place_id TEXT NOT NULL,
            PRIMARY KEY (event_id, place_id)
        );
        CREATE INDEX IF NOT EXISTS idx_graph_ep_event ON graph_event_place_edges(event_id);
        CREATE INDEX IF NOT EXISTS idx_graph_ep_place ON graph_event_place_edges(place_id);

        -- Verse-entity mention links
        CREATE TABLE IF NOT EXISTS graph_verse_mentions (
            verse_ref TEXT NOT NULL,       -- e.g., "Gen.1.1" (matches verses.reference)
            entity_type TEXT NOT NULL,     -- person, place, event
            entity_id TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_graph_vm_ref ON graph_verse_mentions(verse_ref);
        CREATE INDEX IF NOT EXISTS idx_graph_vm_entity ON graph_verse_mentions(entity_type, entity_id);

        -- Person-group membership edges
        CREATE TABLE IF NOT EXISTS graph_person_group_edges (
            person_id TEXT NOT NULL,
            group_name TEXT NOT NULL,
            PRIMARY KEY (person_id, group_name)
        );
        CREATE INDEX IF NOT EXISTS idx_graph_pg_person ON graph_person_group_edges(person_id);
        CREATE INDEX IF NOT EXISTS idx_graph_pg_group ON graph_person_group_edges(group_name);

        -- =====================================================================
        -- Aquifer content (study notes, dictionary, translation notes, key terms)
        -- =====================================================================

        CREATE TABLE IF NOT EXISTS aquifer_content (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content_id INTEGER NOT NULL,
            resource_type TEXT NOT NULL,
            title TEXT NOT NULL,
            book TEXT,
            book_num INTEGER,
            start_ref TEXT,
            end_ref TEXT,
            chapter_start INTEGER,
            verse_start INTEGER,
            chapter_end INTEGER,
            verse_end INTEGER,
            content TEXT NOT NULL,
            content_plain TEXT NOT NULL,
            is_range INTEGER DEFAULT 0,
            UNIQUE(content_id, resource_type)
        );
        CREATE INDEX IF NOT EXISTS idx_aq_type ON aquifer_content(resource_type);
        CREATE INDEX IF NOT EXISTS idx_aq_ref ON aquifer_content(resource_type, start_ref);
        CREATE INDEX IF NOT EXISTS idx_aq_book ON aquifer_content(resource_type, book, chapter_start);
        CREATE INDEX IF NOT EXISTS idx_aq_title ON aquifer_content(resource_type, title);

        -- =====================================================================
        -- ACAI entity annotations
        -- =====================================================================

        CREATE TABLE IF NOT EXISTS acai_entities (
            id TEXT PRIMARY KEY,
            entity_type TEXT NOT NULL,
            name TEXT NOT NULL,
            gender TEXT,
            description TEXT,
            roles TEXT,
            father_id TEXT,
            mother_id TEXT,
            partners TEXT,
            offspring TEXT,
            siblings TEXT,
            referred_to_as TEXT,
            key_references TEXT,
            reference_count INTEGER,
            speeches_count INTEGER,
            tipnr_keys TEXT  -- JSON list of the TIPNR entries ('Name@FirstRef') it is
        );
        CREATE INDEX IF NOT EXISTS idx_acai_type ON acai_entities(entity_type);
        CREATE INDEX IF NOT EXISTS idx_acai_name ON acai_entities(name);

        -- =====================================================================
        -- ANE (Ancient Near East) context entries
        -- =====================================================================

        CREATE TABLE IF NOT EXISTS ane_entries (
            id TEXT PRIMARY KEY,
            dimension TEXT NOT NULL,
            dimension_label TEXT NOT NULL,
            title TEXT NOT NULL,
            summary TEXT NOT NULL,
            detail TEXT,
            ane_parallels TEXT,
            interpretive_significance TEXT,
            period TEXT,
            period_label TEXT,
            key_references TEXT,
            scholarly_sources TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_ane_dimension ON ane_entries(dimension);
        CREATE INDEX IF NOT EXISTS idx_ane_period ON ane_entries(period);

        CREATE TABLE IF NOT EXISTS ane_book_mappings (
            entry_id TEXT NOT NULL,
            book TEXT NOT NULL,
            chapter_start INTEGER,
            chapter_end INTEGER,
            PRIMARY KEY (entry_id, book, chapter_start),
            FOREIGN KEY (entry_id) REFERENCES ane_entries(id)
        );
        CREATE INDEX IF NOT EXISTS idx_ane_bm_book ON ane_book_mappings(book);
        CREATE INDEX IF NOT EXISTS idx_ane_bm_entry ON ane_book_mappings(entry_id);

        -- =====================================================================
        -- Torah Weave (Moshe Kline) — 86 literary units of the Torah as
        -- two-dimensional compositions. Each unit has cells arranged in rows
        -- and columns; horizontal and vertical cell pairings encode parallel
        -- correspondences and thematic progressions.
        -- =====================================================================

        CREATE TABLE IF NOT EXISTS torah_weave_units (
            id INTEGER PRIMARY KEY,           -- serial_number (1-86)
            book TEXT NOT NULL,               -- "Gen", "Exo", "Lev", "Num", "Deu"
            book_full TEXT NOT NULL,          -- "Genesis", ...
            unit_number INTEGER NOT NULL,
            title TEXT NOT NULL,
            verses TEXT NOT NULL,             -- e.g. "Genesis 1:1-2:3"
            verse_range TEXT NOT NULL,        -- e.g. "1:1-2:3"
            format TEXT NOT NULL,             -- "3x2" (regular) or digit string (irregular)
            irregular INTEGER NOT NULL,       -- 0/1
            is_unique INTEGER NOT NULL,       -- 0/1
            cell_count INTEGER NOT NULL,
            type TEXT,                        -- "F" framework, "CL" closure, "U" unique, or NULL
            cell_count_with_subdivisions INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_tw_units_book ON torah_weave_units(book);

        CREATE TABLE IF NOT EXISTS torah_weave_cells (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            unit_id INTEGER NOT NULL REFERENCES torah_weave_units(id),
            cell_label TEXT NOT NULL,         -- "1A", "2Ba", etc.
            row_num INTEGER NOT NULL,
            column_letter TEXT NOT NULL,      -- "A", "B", ...
            subdivision TEXT,                 -- "a", "b", or NULL
            book TEXT NOT NULL,               -- denormalized for lookup
            verse_range TEXT NOT NULL,        -- original string, e.g. "6:1-6:4"
            chapter_start INTEGER NOT NULL,
            verse_start INTEGER NOT NULL,
            chapter_end INTEGER NOT NULL,
            verse_end INTEGER NOT NULL,
            sort_start INTEGER NOT NULL,      -- chapter*1000 + verse (inclusive)
            sort_end INTEGER NOT NULL,        -- chapter*1000 + verse (inclusive)
            UNIQUE(unit_id, cell_label)
        );
        CREATE INDEX IF NOT EXISTS idx_tw_cells_unit ON torah_weave_cells(unit_id);
        CREATE INDEX IF NOT EXISTS idx_tw_cells_lookup ON torah_weave_cells(book, sort_start, sort_end);
    """)
    conn.commit()

    # --- Theological scholarship tables (unified: Heiser, Bradley, etc.) ---
    conn.executescript("""
        -- Scholarship content (multi-author)
        CREATE TABLE IF NOT EXISTS theology_content (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_work TEXT NOT NULL,
            source_author TEXT NOT NULL,
            source_type TEXT NOT NULL,
            chapter_or_episode TEXT,
            title TEXT,
            content_summary TEXT NOT NULL,
            content_detail TEXT,
            page_range TEXT,
            url TEXT,
            UNIQUE(source_work, chapter_or_episode, title)
        );
        CREATE INDEX IF NOT EXISTS idx_theology_source ON theology_content(source_work);
        CREATE INDEX IF NOT EXISTS idx_theology_author ON theology_content(source_author);

        -- Maps theology_content entries to specific verses
        CREATE TABLE IF NOT EXISTS theology_verse_index (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content_id INTEGER NOT NULL REFERENCES theology_content(id),
            reference TEXT NOT NULL,
            book TEXT NOT NULL,
            chapter INTEGER,
            verse INTEGER,
            relevance TEXT DEFAULT 'primary',
            UNIQUE(content_id, reference)
        );
        CREATE INDEX IF NOT EXISTS idx_theology_vi_ref ON theology_verse_index(reference);
        CREATE INDEX IF NOT EXISTS idx_theology_vi_book ON theology_verse_index(book);

        -- Shared theological themes taxonomy
        CREATE TABLE IF NOT EXISTS theology_themes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            theme_key TEXT UNIQUE NOT NULL,
            theme_label TEXT NOT NULL,
            description TEXT NOT NULL,
            parent_theme TEXT,
            key_works TEXT
        );

        -- Maps themes to content and verses
        CREATE TABLE IF NOT EXISTS theology_theme_index (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            theme_key TEXT NOT NULL REFERENCES theology_themes(theme_key),
            content_id INTEGER REFERENCES theology_content(id),
            reference TEXT,
            UNIQUE(theme_key, content_id, reference)
        );
        CREATE INDEX IF NOT EXISTS idx_theology_ti_theme ON theology_theme_index(theme_key);

        -- Legacy aliases (views) so old heiser_content_id FKs still resolve
        CREATE VIEW IF NOT EXISTS heiser_content AS SELECT * FROM theology_content;
        CREATE VIEW IF NOT EXISTS heiser_verse_index AS SELECT * FROM theology_verse_index;
        CREATE VIEW IF NOT EXISTS heiser_themes AS SELECT * FROM theology_themes;
        CREATE VIEW IF NOT EXISTS heiser_theme_index AS SELECT * FROM theology_theme_index;

        -- Septuagint edition texts for compare_biblical_versions. MT rows are
        -- built at query time from `verses`. edition_* preserves the Greek
        -- versification; canonical_* is the MT/English position from the
        -- explicit mapping dataset and is NULL for LXX-only verses that have
        -- no MT counterpart. Version, language, license, and source URL are
        -- constant per version and attached at query time.
        CREATE TABLE IF NOT EXISTS biblical_version_verses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            edition TEXT NOT NULL,
            canonical_reference TEXT,
            canonical_book TEXT,
            canonical_chapter INTEGER,
            canonical_verse INTEGER,
            canonical_verse_suffix TEXT NOT NULL DEFAULT '',
            edition_reference TEXT NOT NULL,
            edition_book TEXT NOT NULL,
            edition_chapter INTEGER NOT NULL,
            edition_verse INTEGER NOT NULL,
            edition_verse_suffix TEXT NOT NULL DEFAULT '',
            text TEXT NOT NULL,
            translation TEXT,
            morphology BLOB,
            mapping_method TEXT NOT NULL,
            -- Brenton's English translates his own Greek, not Rahlfs. NULL: no
            -- Brenton English or Greek for the row; 0: his Greek agrees with
            -- Rahlfs after orthographic levelling; 1: it differs, and only then
            -- are his Greek and a difference summary stored.
            brenton_greek_differs INTEGER,
            brenton_greek TEXT,
            brenton_greek_difference TEXT,
            UNIQUE(edition, edition_reference, canonical_reference)
        );
        CREATE INDEX IF NOT EXISTS idx_bvv_canonical
            ON biblical_version_verses(canonical_book, canonical_chapter, canonical_verse);
        CREATE INDEX IF NOT EXISTS idx_bvv_edition
            ON biblical_version_verses(edition_book, edition_chapter, edition_verse);

        -- Licensed ancient-source passages and full-text index. One table for
        -- every registered corpus (study_bible_mcp.corpora). book_number,
        -- section_number and section_end are Josephus's Niese numbering (0/''
        -- for other corpora); sort_start/sort_end are the generic citation
        -- keys in each work's locator grammar. Columns added after the first
        -- release are nullable so ensure_ancient_source_columns can add them.
        CREATE TABLE IF NOT EXISTS ancient_source_passages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            corpus TEXT NOT NULL,
            author TEXT NOT NULL,
            work_key TEXT NOT NULL,
            work_title TEXT NOT NULL,
            reference TEXT NOT NULL,
            alternate_reference TEXT,
            book_number INTEGER NOT NULL,
            section_number TEXT NOT NULL,
            section_end INTEGER NOT NULL,
            editorial_heading TEXT,
            text TEXT NOT NULL,
            original_text TEXT,
            period_tags TEXT NOT NULL,
            edition TEXT NOT NULL,
            translation TEXT,
            license TEXT NOT NULL,
            source_url TEXT NOT NULL,
            collection TEXT,
            sort_start INTEGER,
            sort_end INTEGER,
            original_language TEXT,
            original_license TEXT,
            translation_license TEXT,
            UNIQUE(corpus, work_key, reference)
        );
        CREATE INDEX IF NOT EXISTS idx_asp_corpus_period
            ON ancient_source_passages(corpus, period_tags);
        CREATE INDEX IF NOT EXISTS idx_asp_reference
            ON ancient_source_passages(corpus, work_key, book_number, section_number);

        -- The full-text index (ancient_source_passages_fts) is created by
        -- ensure_ancient_source_columns, which also rebuilds an older one.

        -- relation: aligned, echo, shared_tradition, contrast or translation
        -- (corpora.LINK_RELATIONS); added to older tables by
        -- ensure_ancient_source_columns.
        CREATE TABLE IF NOT EXISTS ancient_source_biblical_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            passage_id INTEGER NOT NULL REFERENCES ancient_source_passages(id),
            biblical_book TEXT NOT NULL,
            sort_start INTEGER NOT NULL,
            sort_end INTEGER NOT NULL,
            relationship_note TEXT NOT NULL,
            relation TEXT NOT NULL DEFAULT 'shared_tradition',
            UNIQUE(passage_id, biblical_book, sort_start, sort_end)
        );
        CREATE INDEX IF NOT EXISTS idx_asbl_biblical
            ON ancient_source_biblical_links(biblical_book, sort_start, sort_end);

        -- Curated verse-level editorial notes (corpora/editorial_notes.json),
        -- one row per passage a note's citation covers. citation and the sort
        -- range are the note's own (a gap note sits on the passages either
        -- side of its range); contrast and aligned hold '; '-joined biblical
        -- references.
        CREATE TABLE IF NOT EXISTS ancient_source_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            passage_id INTEGER NOT NULL REFERENCES ancient_source_passages(id),
            corpus TEXT NOT NULL,
            work_key TEXT NOT NULL,
            citation TEXT NOT NULL,
            sort_start INTEGER NOT NULL,
            sort_end INTEGER NOT NULL,
            kind TEXT NOT NULL,
            note TEXT NOT NULL,
            contrast TEXT NOT NULL DEFAULT '',
            aligned TEXT NOT NULL DEFAULT '',
            UNIQUE(passage_id, citation, kind, note)
        );
        CREATE INDEX IF NOT EXISTS idx_asn_passage ON ancient_source_notes(passage_id);
        CREATE INDEX IF NOT EXISTS idx_asn_locator
            ON ancient_source_notes(corpus, work_key, sort_start, sort_end);

        -- Textual variants: observed readings and interpretive claims are stored
        -- independently so the API cannot present a scholar's conclusion as
        -- manuscript evidence.
        CREATE TABLE IF NOT EXISTS textual_variant_cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reference TEXT NOT NULL,
            book TEXT NOT NULL,
            chapter INTEGER,
            verse INTEGER,
            case_key TEXT NOT NULL,
            significance TEXT,
            UNIQUE(reference, case_key)
        );
        CREATE INDEX IF NOT EXISTS idx_tvc_ref ON textual_variant_cases(reference);
        CREATE INDEX IF NOT EXISTS idx_tvc_book ON textual_variant_cases(book);

        CREATE TABLE IF NOT EXISTS textual_variant_readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id INTEGER NOT NULL REFERENCES textual_variant_cases(id) ON DELETE CASCADE,
            reading_key TEXT NOT NULL,
            tradition TEXT NOT NULL,
            text TEXT NOT NULL,
            original_text TEXT,
            language TEXT,
            UNIQUE(case_id, reading_key)
        );

        -- One row per piece of evidence. evidence_type separates manuscript
        -- witnesses from NT citations, indirect evidence (e.g. a scroll attesting
        -- a text form elsewhere in the book), and "not preserved" notes, which
        -- belong to the case rather than to any reading. reading_support keeps
        -- the raw dataset label the classification was derived from.
        CREATE TABLE IF NOT EXISTS textual_variant_witnesses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id INTEGER NOT NULL REFERENCES textual_variant_cases(id) ON DELETE CASCADE,
            reading_id INTEGER REFERENCES textual_variant_readings(id) ON DELETE CASCADE,
            witness TEXT NOT NULL,
            evidence_type TEXT NOT NULL CHECK (
                evidence_type IN ('manuscript', 'citation', 'indirect', 'not_preserved')
            ),
            reading_support TEXT NOT NULL,
            approximate_date TEXT,
            source_citation TEXT,
            source_url TEXT,
            CHECK ((evidence_type = 'not_preserved') = (reading_id IS NULL)),
            UNIQUE(case_id, witness)
        );
        CREATE INDEX IF NOT EXISTS idx_tvw_case ON textual_variant_witnesses(case_id);
        CREATE INDEX IF NOT EXISTS idx_tvw_reading ON textual_variant_witnesses(reading_id);

        CREATE TABLE IF NOT EXISTS textual_critical_judgments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id INTEGER NOT NULL REFERENCES textual_variant_cases(id) ON DELETE CASCADE,
            judgment TEXT NOT NULL,
            attribution TEXT,
            source_citation TEXT,
            source_url TEXT
        );

        CREATE TABLE IF NOT EXISTS textual_theological_interpretations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id INTEGER NOT NULL REFERENCES textual_variant_cases(id) ON DELETE CASCADE,
            interpretation TEXT NOT NULL,
            attribution TEXT,
            source_citation TEXT,
            source_url TEXT
        );

        CREATE TABLE IF NOT EXISTS textual_author_claims (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id INTEGER NOT NULL REFERENCES textual_variant_cases(id) ON DELETE CASCADE,
            author TEXT NOT NULL,
            claim TEXT NOT NULL,
            source_citation TEXT,
            source_url TEXT
        );

        CREATE TABLE IF NOT EXISTS textual_translation_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id INTEGER NOT NULL REFERENCES textual_variant_cases(id) ON DELETE CASCADE,
            translation TEXT NOT NULL,
            preferred_reading TEXT NOT NULL,
            rationale TEXT
        );

        -- NT→OT quotations where the NT follows the LXX form rather than MT.
        CREATE TABLE IF NOT EXISTS nt_ot_lxx_quote_hints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nt_reference TEXT NOT NULL,
            nt_display TEXT NOT NULL,
            nt_book TEXT NOT NULL,
            ot_reference TEXT NOT NULL,
            ot_display TEXT NOT NULL,
            ot_book TEXT NOT NULL,
            follows_lxx INTEGER NOT NULL DEFAULT 1,
            divergence_type TEXT,
            divergence_note TEXT,
            variant_case_id INTEGER REFERENCES textual_variant_cases(id),
            UNIQUE(nt_reference, ot_reference)
        );
        CREATE INDEX IF NOT EXISTS idx_ntoq_nt ON nt_ot_lxx_quote_hints(nt_reference);
        CREATE INDEX IF NOT EXISTS idx_ntoq_ot ON nt_ot_lxx_quote_hints(ot_reference);
        CREATE INDEX IF NOT EXISTS idx_ntoq_nt_book ON nt_ot_lxx_quote_hints(nt_book);
        CREATE INDEX IF NOT EXISTS idx_ntoq_ot_book ON nt_ot_lxx_quote_hints(ot_book);

        -- The HLT translation
        CREATE TABLE IF NOT EXISTS hlt_verses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reference TEXT UNIQUE NOT NULL,
            book TEXT NOT NULL,
            chapter INTEGER,
            verse INTEGER,
            hlt_text TEXT NOT NULL,
            hlt_text_annotated TEXT NOT NULL,
            base_text_source TEXT DEFAULT 'MT',
            variant_used INTEGER,
            word_data_hlt TEXT,
            translation_notes TEXT,
            confidence TEXT DEFAULT 'high',
            status TEXT DEFAULT 'draft',
            last_updated TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_hlt_ref ON hlt_verses(reference);
        CREATE INDEX IF NOT EXISTS idx_hlt_book ON hlt_verses(book);

        -- HLT bracket annotations
        CREATE TABLE IF NOT EXISTS hlt_annotations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reference TEXT NOT NULL,
            annotation_type TEXT NOT NULL,
            annotation_text TEXT NOT NULL,
            word_position INTEGER,
            explanation TEXT NOT NULL,
            heiser_content_id INTEGER,
            UNIQUE(reference, annotation_type, word_position)
        );
        CREATE INDEX IF NOT EXISTS idx_hlt_ann_ref ON hlt_annotations(reference);

        -- HLT study notes
        CREATE TABLE IF NOT EXISTS hlt_study_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reference TEXT NOT NULL,
            book TEXT NOT NULL,
            chapter INTEGER,
            verse INTEGER,
            note_type TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            heiser_content_ids TEXT,
            related_verses TEXT,
            priority INTEGER DEFAULT 5,
            UNIQUE(reference, note_type, title)
        );
        CREATE INDEX IF NOT EXISTS idx_hlt_sn_ref ON hlt_study_notes(reference);
        CREATE INDEX IF NOT EXISTS idx_hlt_sn_book ON hlt_study_notes(book);
        CREATE INDEX IF NOT EXISTS idx_hlt_sn_type ON hlt_study_notes(note_type);
    """)
    conn.commit()

    # Add Abbott-Smith columns to existing databases (idempotent)
    for col in [
        "abbott_smith_def TEXT",
        "nt_occurrences INTEGER",
        "lxx_hebrew TEXT",
        "synonyms TEXT",
        "sense_hierarchy TEXT",
    ]:
        try:
            conn.execute(f"ALTER TABLE lexicon ADD COLUMN {col}")
        except sqlite3.OperationalError:
            pass  # Column already exists
    conn.commit()
    ensure_ancient_source_columns(conn)


# Columns added to ancient_source_passages after the Josephus-only release.
_ANCIENT_SOURCE_ADDED_COLUMNS = (
    ("collection", "TEXT"),
    ("sort_start", "INTEGER"),
    ("sort_end", "INTEGER"),
    ("original_language", "TEXT"),
    ("original_license", "TEXT"),
    ("translation_license", "TEXT"),
)
# Searched columns: exact words first; prefix-stripped Hebrew/Aramaic variants
# only as a fallback (see StudyBibleDB.search_ancient_sources).
ANCIENT_FTS_COLUMNS = ("text", "original_text_folded", "original_prefix_variants")
_ANCIENT_FTS_SQL = """
    CREATE VIRTUAL TABLE IF NOT EXISTS ancient_source_passages_fts USING fts5(
        passage_id UNINDEXED,
        work_title UNINDEXED,
        reference UNINDEXED,
        text,
        original_text_folded,
        original_prefix_variants,
        tokenize = 'porter unicode61 remove_diacritics 2'
    )
"""
# Backfill for links stored before relations existed: the same rule as
# corpora.base.default_link_relation, plus targum verse renderings.
_LINK_RELATION_BACKFILL = """
    UPDATE ancient_source_biblical_links SET relation = CASE
        WHEN relationship_note LIKE 'Translation of:%' THEN 'translation'
        WHEN relationship_note LIKE '%cites%' OR relationship_note LIKE '%quotes%'
          OR relationship_note LIKE '%expounds%' OR relationship_note LIKE '%explicit reference%'
        THEN 'echo'
        ELSE 'shared_tradition' END
"""
# Columns and tables the ancient-source tools need; a database lacking any of
# them predates the current schema (StudyBibleDB.ancient_schema_status).
ANCIENT_REQUIRED_COLUMNS = {
    "ancient_source_passages": tuple(column for column, _ in _ANCIENT_SOURCE_ADDED_COLUMNS),
    "ancient_source_passages_fts": ANCIENT_FTS_COLUMNS,
    "ancient_source_biblical_links": ("relation",),
    "ancient_source_notes": ("passage_id", "kind", "note", "contrast", "aligned"),
}


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def rebuild_ancient_search_index(conn: sqlite3.Connection) -> int:
    """Recreate the ancient-source FTS table and refill it from the stored passages.

    Used when an older index lacks the prefix-variant column. Each corpus's
    ``search_index_gaps`` and ``search_index_removals`` are applied as at
    import. Returns the row count.
    """
    from .corpora import CORPORA  # Corpus modules never import this module.

    conn.execute("DROP TABLE IF EXISTS ancient_source_passages_fts")
    conn.execute(_ANCIENT_FTS_SQL)
    rows = conn.execute(
        "SELECT id, corpus, work_title, reference, text, original_text FROM ancient_source_passages"
    ).fetchall()
    for passage_id, corpus, work_title, reference, text, original in rows:
        registered = CORPORA.get(corpus)
        removals = registered.search_index_removals if registered else ()
        gaps = registered.search_index_gaps if registered else ()
        conn.execute(
            """INSERT INTO ancient_source_passages_fts
               (passage_id, work_title, reference, text, original_text_folded,
                original_prefix_variants)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                passage_id, work_title, reference, text or "",
                ancient_search_index_text(original or "", removals, gaps),
                ancient_search_prefix_variants(original or "", removals, gaps),
            ),
        )
    return len(rows)


def ensure_ancient_source_columns(conn: sqlite3.Connection) -> None:
    """Bring older ancient-source tables up to the current schema (idempotent).

    Adds the multi-corpus passage columns and locator index, the link
    ``relation`` column (backfilled from each link's note), and rebuilds an
    FTS index that lacks the prefix-variant column. Rows imported before the
    columns existed keep NULL sort keys until their corpus is re-imported
    (``scripts/upgrade_database.py``).
    """
    present = _columns(conn, "ancient_source_passages")
    for column, sql_type in _ANCIENT_SOURCE_ADDED_COLUMNS:
        if column not in present:
            conn.execute(f"ALTER TABLE ancient_source_passages ADD COLUMN {column} {sql_type}")
    conn.execute(
        """CREATE INDEX IF NOT EXISTS idx_asp_locator
           ON ancient_source_passages(corpus, work_key, sort_start, sort_end)"""
    )
    if "relation" not in _columns(conn, "ancient_source_biblical_links"):
        conn.execute(
            "ALTER TABLE ancient_source_biblical_links "
            "ADD COLUMN relation TEXT NOT NULL DEFAULT 'shared_tradition'"
        )
        conn.execute(_LINK_RELATION_BACKFILL)
    fts = _columns(conn, "ancient_source_passages_fts")
    if not fts:
        conn.execute(_ANCIENT_FTS_SQL)
    elif not set(ANCIENT_FTS_COLUMNS) <= fts:
        rebuild_ancient_search_index(conn)
    conn.commit()


def upsert_theology_content(conn: sqlite3.Connection, entry: dict) -> tuple[int, str]:
    """Insert a theology_content row, or refresh the url of the existing one.

    Rows are identified by (source_work, chapter_or_episode, title), compared with
    IS so a NULL chapter still matches. An existing row keeps all of its content;
    only its url is updated, so re-running an importer applies new or corrected
    source links without duplicating rows.

    Returns (content_id, status) where status is 'inserted', 'url_updated' or
    'unchanged'.
    """
    row = conn.execute(
        """SELECT id, url FROM theology_content
           WHERE source_work = ? AND chapter_or_episode IS ? AND title = ?""",
        (entry["source_work"], entry["chapter_or_episode"], entry["title"]),
    ).fetchone()
    if row is not None:
        content_id, current_url = row
        if current_url == entry["url"]:
            return content_id, "unchanged"
        conn.execute(
            "UPDATE theology_content SET url = ? WHERE id = ?", (entry["url"], content_id)
        )
        return content_id, "url_updated"
    cursor = conn.execute(
        """INSERT INTO theology_content
           (source_work, source_author, source_type, chapter_or_episode,
            title, content_summary, content_detail, page_range, url)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (entry["source_work"], entry["source_author"], entry["source_type"],
         entry["chapter_or_episode"], entry["title"], entry["content_summary"],
         entry["content_detail"], entry["page_range"], entry["url"]),
    )
    return cursor.lastrowid, "inserted"


def link_theology_theme(conn: sqlite3.Connection, theme_key: str, content_id: int) -> None:
    """Tag a theology_content row with a theme, once.

    Content-level links carry reference NULL, which the UNIQUE(theme_key, content_id,
    reference) constraint never treats as a duplicate, so INSERT OR IGNORE would add
    a fresh row on every importer run (inflating theme entry counts).
    """
    conn.execute(
        """INSERT INTO theology_theme_index (theme_key, content_id, reference)
           SELECT ?, ?, NULL
           WHERE NOT EXISTS (
               SELECT 1 FROM theology_theme_index
               WHERE theme_key = ? AND content_id = ? AND reference IS NULL
           )""",
        (theme_key, content_id, theme_key, content_id),
    )



def create_vector_tables(conn: sqlite3.Connection):
    """Create vector tables for semantic search using sqlite-vec.

    This should be called after loading the sqlite-vec extension.
    """
    conn.executescript("""
        -- Vector table for passage embeddings (1536 dimensions for OpenAI)
        CREATE VIRTUAL TABLE IF NOT EXISTS passage_vectors USING vec0(
            passage_id INTEGER PRIMARY KEY,
            embedding FLOAT[1536]
        );

        -- Vector table for verse embeddings
        CREATE VIRTUAL TABLE IF NOT EXISTS verse_vectors USING vec0(
            verse_id INTEGER PRIMARY KEY,
            embedding FLOAT[1536]
        );
    """)
    conn.commit()
