"""Parsers and import helpers for provenance-aware MT/LXX edition text.

Only Septuagint rows are stored in ``biblical_version_verses``. Masoretic rows
are built at query time from the STEPBible TAHOT ``verses`` table, so the MT is
never duplicated in the database.
"""

from __future__ import annotations

import difflib
import json
import re
import sqlite3
import unicodedata
import zlib
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Iterator


LXX_COMMIT = "c91f6b1e8fb3ba37df701e6ae31f675ace71a2b2"
LXX_SOURCE_URL = f"https://github.com/OpenScriptorium/lxx-morph/tree/{LXX_COMMIT}"
LXX_LICENSE = (
    "CC BY 4.0 (morphology); Rahlfs Greek text public domain; "
    "Brenton translation and Greek text public domain"
)
LXX_TRANSLATION_LABEL = "Brenton English Septuagint translation"
BRENTON_SOURCE_URL = "https://ebible.org/details.php?id=eng-Brenton"
BRENTON_GREEK_SOURCE_URL = "https://ebible.org/details.php?id=grcbrent"
# Shown once in any comparison that includes Brenton's English.
BRENTON_TRANSLATION_NOTE = (
    "Brenton (1844) translated his own Greek edition, which is based chiefly on Codex "
    "Vaticanus and is not the Rahlfs text shown, and his English sometimes departs even "
    "from that Greek, so his wording may not match the Greek beside it."
)
# For these books (Rahlfs edition-book codes) and for Daniel 3:24-90 (the
# Prayer of Azariah and Song of the Three, the KJV "Song of the Three
# Children"), eBible's Brenton prints the KJV (Authorized Version) Apocrypha,
# lightly adapted, not his own translation: verse-by-verse similarity to
# eBible's KJV is 0.92-1.00 (0.24-0.49 for the Hebrew-canon books). The KJV was
# translated from other Greek texts, so neither the Rahlfs nor Brenton's Greek
# is what it renders (Sirach 17:17 adds "in the division of the nations of the
# whole earth"). Greek Esther and 3-4 Maccabees are Brenton's own.
KJV_APOCRYPHA_BOOKS = frozenset({
    "1Es", "1Ma", "2Ma", "Bar", "Bel", "Jdt", "Lje", "Sir", "Sus", "Tob", "Wis",
})
KJV_APOCRYPHA_TRANSLATION_LABEL = "KJV (Authorized Version) Apocrypha, lightly adapted by Brenton"
KJV_APOCRYPHA_NOTE = (
    "Brenton's edition prints it in place of his own translation. The KJV was translated "
    "from other Greek texts, not the Rahlfs or Brenton's Greek shown, so it can add or "
    "omit words that Greek lacks (e.g. Sirach 17:17)."
)


def is_kjv_apocrypha(edition_book: str, chapter: int, verse: int) -> bool:
    """True where Brenton's English is the KJV Apocrypha rather than his own."""
    return edition_book in KJV_APOCRYPHA_BOOKS or (
        edition_book == "Dan" and chapter == 3 and 24 <= verse <= 90
    )


# Rahlfs books and passages outside the 66-book Protestant canon (Westminster
# Confession 1.3): every LXX-only book except 2 Esdras (Ezra-Nehemiah) and Greek
# Esther, plus the Greek additions to canonical books. Odes 1-6, 9-11 and 13
# reprint canonical songs (Exodus 15, Luke 1, ...) and are not marked.
APOCRYPHA_BOOK_NAMES = {
    "1Es": "1 Esdras", "1Ma": "1 Maccabees", "2Ma": "2 Maccabees",
    "3Ma": "3 Maccabees", "4Ma": "4 Maccabees", "Bar": "Baruch",
    "Bel": "Bel and the Dragon", "Jdt": "Judith", "Lje": "the Letter of Jeremiah",
    "Pss": "the Psalms of Solomon", "Sir": "Sirach", "Sus": "Susanna",
    "Tob": "Tobit", "Wis": "Wisdom",
}
_ESTHER_ADDITIONS = "the Greek additions to Esther"
_AZARIAH = "the Prayer of Azariah and Song of the Three"
_NONCANONICAL_ODES = {
    7: f"{_AZARIAH} (Odes 7–8)", 8: f"{_AZARIAH} (Odes 7–8)",
    12: "the Prayer of Manasseh (Ode 12)", 14: "Ode 14 (a morning hymn)",
}
# Names that take a plural verb ("... are not in the Protestant canon").
APOCRYPHA_PLURAL_NAMES = frozenset({
    "the Psalms of Solomon", _ESTHER_ADDITIONS, f"{_AZARIAH} (Dan 3:24–90)",
    f"{_AZARIAH} (Odes 7–8)",
})


def apocrypha_name(
    edition_book: str, chapter: int, verse: int, canonical_reference: str | None
) -> str | None:
    """Name the non-canonical book or Greek addition a Rahlfs row belongs to.

    Greek Esther's additions are its lettered verses with no MT position; the
    other additions are Daniel 3:24-90 (both editions) and Psalm 151. Other
    LXX pluses in canonical books (3 Kingdoms 2:35a, Proverbs 9:12a, ...) are
    textual variants, not Apocrypha, and return None.
    """
    if edition_book in APOCRYPHA_BOOK_NAMES:
        return APOCRYPHA_BOOK_NAMES[edition_book]
    if edition_book == "Ode":
        return _NONCANONICAL_ODES.get(chapter)
    if edition_book == "EsG" and canonical_reference is None:
        return _ESTHER_ADDITIONS
    if edition_book == "Dan" and chapter == 3 and 24 <= verse <= 90:
        return f"{_AZARIAH} (Dan 3:24–90)"
    if edition_book == "Psa" and chapter == 151:
        return "Psalm 151"
    return None


MT_EDITION = "STEPBible TAHOT / Westminster Leningrad Codex"
MT_LICENSE = "CC BY 4.0"
MT_SOURCE_URL = "https://github.com/STEPBible/STEPBible-Data"
MT_TRANSLATION_LABEL = "STEPBible word glosses (interlinear, not a translation)"
MT_VERSIFICATION_METHOD = "TAHOT English/Hebrew versification"
# OpenScriptorium's MT/LXX verse pairs, which the upstream README credits to TVTMS.
VERSE_MAPPING_CREDIT = (
    "MT/LXX verse pairs from OpenScriptorium lxx-morph, derived in part from TVTMS "
    "(Tyndale Versification Traditions Mapping System), CC BY 4.0, created by "
    "STEPBible.org / Tyndale House Cambridge"
)

# Field order of the compact per-word arrays stored in the morphology column.
LXX_MORPHOLOGY_FIELDS = ("surface", "lemma", "parsing", "pos", "confidence", "source")

MT_BOOK_CODES = {
    "genesis": "Gen", "exodus": "Exo", "leviticus": "Lev", "numbers": "Num",
    "deuteronomy": "Deu", "joshua": "Jos", "judges": "Jdg", "ruth": "Rut",
    "1-samuel": "1Sa", "2-samuel": "2Sa", "1-kings": "1Ki", "2-kings": "2Ki",
    "1-chronicles": "1Ch", "2-chronicles": "2Ch", "ezra": "Ezr",
    "nehemiah": "Neh", "esther": "Est", "job": "Job", "psalms": "Psa",
    "proverbs": "Pro", "ecclesiastes": "Ecc", "song-of-solomon": "Sng",
    "isaiah": "Isa", "jeremiah": "Jer", "lamentations": "Lam", "ezekiel": "Ezk",
    "daniel": "Dan", "hosea": "Hos", "joel": "Jol", "amos": "Amo",
    "obadiah": "Oba", "jonah": "Jon", "micah": "Mic", "nahum": "Nam",
    "habakkuk": "Hab", "zephaniah": "Zep", "haggai": "Hag",
    "zechariah": "Zec", "malachi": "Mal",
}

LXX_SOURCE_BOOKS = frozenset({
    "1-chronicles", "1-esdras", "1-kings", "1-maccabees", "1-samuel",
    "2-chronicles", "2-esdras", "2-kings", "2-maccabees", "2-samuel",
    "3-maccabees", "4-maccabees", "amos", "baruch",
    "bel-and-the-dragon-theodotion", "bel-and-the-dragon", "daniel-theodotion",
    "daniel", "deuteronomy", "ecclesiastes", "esther-greek", "exodus",
    "ezekiel", "genesis", "habakkuk", "haggai", "hosea", "isaiah",
    "jeremiah-lxx", "job-lxx", "joel", "jonah", "joshua-vaticanus-b",
    "joshua", "judges-vaticanus-b", "judges", "judith", "lamentations",
    "letter-of-jeremiah", "leviticus", "malachi", "micah", "nahum", "numbers",
    "obadiah", "odes", "proverbs", "psalms-lxx", "psalms-of-solomon", "ruth",
    "sirach", "song-of-solomon", "susanna-theodotion", "susanna",
    "tobit-sinaiticus", "tobit", "wisdom", "zechariah", "zephaniah",
})


LXX_BOOK_CODES = {
    **MT_BOOK_CODES,
    "1-esdras": "1Es", "2-esdras": "2Es", "1-maccabees": "1Ma",
    "2-maccabees": "2Ma", "3-maccabees": "3Ma", "4-maccabees": "4Ma",
    "baruch": "Bar", "bel-and-the-dragon": "Bel",
    "bel-and-the-dragon-theodotion": "Bel", "daniel-theodotion": "Dan",
    "esther-greek": "EsG", "jeremiah-lxx": "Jer", "job-lxx": "Job",
    "joshua-vaticanus-b": "Jos", "judges-vaticanus-b": "Jdg",
    "letter-of-jeremiah": "Lje", "odes": "Ode", "psalms-lxx": "Psa",
    "psalms-of-solomon": "Pss", "sirach": "Sir", "susanna": "Sus",
    "susanna-theodotion": "Sus", "tobit": "Tob", "tobit-sinaiticus": "Tob",
    "judith": "Jdt", "wisdom": "Wis",
}

# Brenton translates Codex Vaticanus (B) and, for Daniel, Susanna and Bel,
# Theodotion. Its English is attached only to the Rahlfs file of the same
# recension; the Old Greek and Alexandrinus (A) files stay untranslated.
BRENTON_BOOK_CODES = {
    "genesis": "GEN", "exodus": "EXO", "leviticus": "LEV", "numbers": "NUM",
    "deuteronomy": "DEU", "joshua-vaticanus-b": "JOS",
    "judges-vaticanus-b": "JDG", "ruth": "RUT",
    "1-samuel": "1SA", "2-samuel": "2SA", "1-kings": "1KI", "2-kings": "2KI",
    "1-chronicles": "1CH", "2-chronicles": "2CH", "1-esdras": "1ES",
    "1-maccabees": "1MA", "2-maccabees": "2MA", "3-maccabees": "3MA",
    "4-maccabees": "4MA", "amos": "AMO", "baruch": "BAR",
    "bel-and-the-dragon-theodotion": "BEL", "daniel-theodotion": "DAG",
    "ecclesiastes": "ECC", "esther-greek": "ESG", "ezekiel": "EZK",
    "habakkuk": "HAB", "haggai": "HAG", "hosea": "HOS", "isaiah": "ISA",
    "jeremiah-lxx": "JER", "job-lxx": "JOB", "joel": "JOL", "jonah": "JON",
    "judith": "JDT", "lamentations": "LAM", "letter-of-jeremiah": "LJE",
    "malachi": "MAL", "micah": "MIC", "nahum": "NAM", "obadiah": "OBA",
    "proverbs": "PRO", "psalms-lxx": "PSA", "sirach": "SIR",
    "song-of-solomon": "SNG", "susanna-theodotion": "SUS", "tobit": "TOB",
    "wisdom": "WIS", "zechariah": "ZEC", "zephaniah": "ZEP",
}
# 2 Esdras is translated by Brenton's separate Ezra and Nehemiah books; his
# Greek prints all of 2 Esdras as EZR.
REQUIRED_BRENTON_BOOKS = frozenset(BRENTON_BOOK_CODES.values()) | {"EZR", "NEH"}
REQUIRED_BRENTON_GREEK_BOOKS = frozenset(BRENTON_BOOK_CODES.values()) | {"EZR"}
# Columns added for the Brenton Greek comparison (see iter_lxx_rows).
_BRENTON_GREEK_COLUMNS = (
    ("brenton_greek_differs", "INTEGER"),
    ("brenton_greek", "TEXT"),
    ("brenton_greek_difference", "TEXT"),
)

_EDITION_SUFFIXES = {
    "daniel": "Old Greek",
    "daniel-theodotion": "Theodotion",
    "susanna": "Old Greek",
    "susanna-theodotion": "Theodotion",
    "bel-and-the-dragon": "Old Greek",
    "bel-and-the-dragon-theodotion": "Theodotion",
    "joshua": "Alexandrinus A text",
    "judges": "Alexandrinus A text",
    "joshua-vaticanus-b": "Vaticanus B recension",
    "judges-vaticanus-b": "Vaticanus B recension",
    "tobit-sinaiticus": "Sinaiticus recension",
}

_OT_CODES = tuple(MT_BOOK_CODES.values())
_REF_RE = re.compile(r"^(\d+):(\d+)([a-z]?)$", re.IGNORECASE)
_USFM_NOTE_RE = re.compile(r"\\(?:f|x)\s.*?\\(?:f|x)\*", re.DOTALL)
# Closing character markers (\add*, \+it*) never consume the following space;
# opening markers (\add, \+it) consume the one delimiter space after them.
_USFM_CLOSE_MARKER_RE = re.compile(r"\\\+?[a-z0-9-]+\*", re.IGNORECASE)
_USFM_OPEN_MARKER_RE = re.compile(r"\\\+?[a-z0-9-]+\s?", re.IGNORECASE)


def _split_ref(reference: str) -> tuple[int, int, str]:
    match = _REF_RE.match(reference)
    if not match:
        raise ValueError(f"Unsupported edition reference: {reference}")
    return int(match.group(1)), int(match.group(2)), match.group(3).lower()


def _clean_usfm(text: str) -> str:
    text = _USFM_NOTE_RE.sub("", text)
    text = _USFM_CLOSE_MARKER_RE.sub("", text)
    text = _USFM_OPEN_MARKER_RE.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_brenton_usfm(directory: Path) -> dict[tuple[str, str], str]:
    """Read eBible's Brenton USFM files into (book code, chapter:verse) text."""
    translations: dict[tuple[str, str], str] = {}
    for path in sorted(directory.glob("*.usfm")):
        content = path.read_text(encoding="utf-8-sig")
        id_match = re.search(r"^\\id\s+(\S+)", content, re.MULTILINE)
        if not id_match:
            continue
        book = id_match.group(1)
        chapter: str | None = None
        current_key: tuple[str, str] | None = None
        for line in content.splitlines():
            chapter_match = re.match(r"^\\c\s+(\d+)", line)
            if chapter_match:
                chapter = chapter_match.group(1)
                current_key = None
                continue
            verse_match = re.match(r"^\\v\s+(\d+[a-z]?(?:-\d+[a-z]?)?)\s*(.*)", line)
            if verse_match and chapter:
                current_key = (book, f"{chapter}:{verse_match.group(1)}")
                translations[current_key] = _clean_usfm(verse_match.group(2))
                continue
            if current_key and line and not re.match(r"^\\(?:c|s|ms|mt|r|d|b|ib)\b", line):
                continuation = _clean_usfm(line)
                if continuation:
                    translations[current_key] = f"{translations[current_key]} {continuation}".strip()
    return translations


def load_lxx_pairings(path: Path) -> dict[tuple[str, str], list[dict]]:
    """Index the explicit LXX→MT versification map by Greek book and verse."""
    pairings: dict[tuple[str, str], list[dict]] = {}
    with path.open(encoding="utf-8") as source:
        for line in source:
            record = json.loads(line)
            pairings.setdefault((record["grk_book"], record["grk_ref"]), []).append(record)
    return pairings


# ---------------------------------------------------------------------------
# Brenton's own Greek against the Rahlfs text it is shown beside
# ---------------------------------------------------------------------------

# Elided, conditioned, and alternative spellings of one word, reduced to one
# form. Keys are already accentless, ει→ι, with doubled letters collapsed.
_GREEK_WORD_FORMS = {
    "επ": "επι", "εφ": "επι", "απ": "απο", "αφ": "απο", "μετ": "μετα", "μεθ": "μετα",
    "κατ": "κατα", "καθ": "κατα", "δι": "δια", "παρ": "παρα", "υπ": "υπο", "υφ": "υπο",
    "αντ": "αντι", "ανθ": "αντι", "αλ": "αλα", "δ": "δε", "τ": "τε", "ουδ": "ουδε",
    "μηδ": "μηδε", "ουκ": "ου", "ουχ": "ου", "εαν": "αν", "ουτωσ": "ουτω",
    "μεχρισ": "μεχρι", "αχρισ": "αχρι", "εχθεσ": "χθεσ",
}
# Hellenistic (Rahlfs) against classicizing (Brenton) spellings inside words.
_GREEK_SPELLINGS = (
    ("λημψ", "ληψ"), ("λημπ", "ληπ"), ("λημφ", "ληφ"),  # λήμψομαι / λήψομαι
    ("λεθρευ", "λοθρευ"),  # ἐξολεθρεύω / ἐξολοθρεύω
    ("τεσερακ", "τεσαρακ"),  # τεσσεράκοντα / τεσσαράκοντα
    ("πηχεω", "πηχω"),  # πήχεων / πηχῶν
    ("σεαυτ", "σαυτ"),  # σεαυτόν / σαυτόν
)
_GREEK_PREFIXES = (  # ηὐλόγησε, οὐθείς, ἠθέλησε / ἐθέλησε, ἠνεῴχθη / ἀνεῴχθη
    ("ηυ", "ευ"), ("ουθ", "ουδ"), ("μηθ", "μηδ"),
    ("ηθελ", "εθελ"), ("ηδυν", "εδυν"), ("ηβουλ", "εβουλ"), ("ημελ", "εμελ"), ("ηνεω", "ανεω"),
)
# Unassimilated nasals (Rahlfs ἐνκαλέω, συνπορεύομαι) against ἐγκαλέω, συμπορεύομαι.
_NASAL_ASSIMILATION = (
    (re.compile(r"ν(?=[πβφψμ])"), "μ"), (re.compile(r"ν(?=[κγχξ])"), "γ"),
    (re.compile(r"ν(?=[λρ])"), ""), (re.compile(r"συνσ"), "συσ"), (re.compile(r"συνζ"), "συζ"),
)
# Brenton heads acrostic verses (Lamentations) with the Hebrew letter: "ΑΛΕΦ."
_ACROSTIC_LETTERS = frozenset({
    "αλεφ", "βηθ", "γιμελ", "δαλεθ", "η", "ουαυ", "ζαιν", "ηθ", "τηθ", "ιωδ", "χαφ", "λαμεδ",
    "μημ", "νουν", "σαμεχ", "αιν", "φη", "τσαδη", "κωφ", "ρηχσ", "χσεν", "θαυ",
})
# First-aorist endings on second aorists (εἶπαν / εἶπον, ἀφείλαντο / ἀφείλοντο).
_AORIST_ENDINGS = re.compile(r"(αντο|αμεν|ασθε|ατε|αν)$")
_AORIST_EQUIVALENTS = {"αντο": "οντο", "αμεν": "ομεν", "ασθε": "εσθε", "ατε": "ετε", "αν": "ον"}
# Consonant skeleton used to match differently spelled proper names.
_NAME_SKELETON = str.maketrans(
    {"ζ": "σ", "ξ": "κσ", "χ": "κ", "φ": "π", "θ": "τ", "ψ": "πσ", **dict.fromkeys("αεηιουω")}
)
_SMOOTH_BREATHING = "\u0313"
_ROUGH_BREATHING = "\u0314"
_ELISION_MARKS = ("\u02bc", "\u1fbf", "\u1fbd", "\u2019", "'")
_SUMMARY_WORDS = 8


def _greek_letters(word: str) -> str:
    return "".join(ch for ch in word if unicodedata.category(ch) in ("Ll", "Lu")).casefold()


@lru_cache(maxsize=None)
def normalize_greek_word(word: str) -> tuple[str, ...]:
    """Reduce one printed Greek word to comparable spelling-neutral forms.

    Accents, breathings, iota subscripts, case, final sigma, punctuation and
    elision marks are removed; itacistic ει/ι, doubled consonants, movable
    nu/sigma, elided and Hellenistic spellings are levelled. Crasis (κἀγώ)
    expands to two words, matching editions that print καὶ ἐγώ.
    """
    decomposed = unicodedata.normalize("NFD", word)
    letters = _greek_letters(decomposed)
    if not letters:
        return ()
    marks = [ch for ch in decomposed if unicodedata.category(ch) in ("Ll", "Lu", "Mn")]
    # κἀγώ, κἀκεῖ, κἄν: a breathing on the vowel after κ marks crasis with καί.
    if letters.startswith("κ") and len(marks) > 2 and marks[2] == _SMOOTH_BREATHING:
        rest = letters[2:]
        return ("και", *normalize_greek_word("αν" if rest == "ν" else f"ε{rest}"))
    # αὑτοῦ (rough breathing) is the contracted reflexive ἑαυτοῦ.
    if letters.startswith("αυτ") and len(marks) > 2 and marks[2] == _ROUGH_BREATHING:
        letters = f"ε{letters}"
    # A breathing never follows an initial consonant: "γἱοὶ" is υἱοὶ mis-keyed.
    if letters.startswith("γ") and len(marks) > 2 and marks[2] in (_SMOOTH_BREATHING, _ROUGH_BREATHING):
        letters = f"υ{letters[1:]}"
    for pattern, replacement in _NASAL_ASSIMILATION:
        letters = pattern.sub(replacement, letters)
    letters = re.sub(r"(.)\1+", r"\1", letters.replace("ει", "ι"))
    for old, new in _GREEK_SPELLINGS:
        letters = letters.replace(old, new)
    for old, new in _GREEK_PREFIXES:
        if letters.startswith(old):
            letters = new + letters[len(old):]
    letters = _GREEK_WORD_FORMS.get(letters, letters)
    if letters.endswith("ιμ"):  # χερουβιμ / χερουβιν
        letters = f"{letters[:-1]}ν"
    if len(letters) >= 4 and letters[-1] == "ν" and letters[-2] in "ει":  # movable nu
        letters = letters[:-1]
    return (letters,)


def normalize_greek_text(text: str) -> list[str]:
    """Normalized word sequence of a Greek verse (see normalize_greek_word)."""
    return [form for word in text.split() for form in normalize_greek_word(word)]


# A token is (normalized form, first raw word index, last raw word index).
_Token = tuple[str, int, int]


def _is_acrostic_heading(word: str) -> bool:
    letters = "".join(ch for ch in word if ch.isalpha())
    return word.endswith(".") and letters.isupper() and letters.casefold() in _ACROSTIC_LETTERS


def _greek_tokens(words: list[str], offset: int) -> list[_Token]:
    return [
        (form, index, index)
        for index, word in enumerate(words, offset)
        if not _is_acrostic_heading(word)
        for form in normalize_greek_word(word)
    ]


def _join_split_words(tokens: list[_Token], single_words: set[str]) -> list[_Token]:
    """Merge up to three adjacent words printed elsewhere as one word
    (ἀνὰ μέσον / ἀναμέσον, ἐπὶ τὸ αὐτό / ἐπιτοαυτό)."""
    joined: list[_Token] = []
    index = 0
    while index < len(tokens):
        for size in (3, 2, 1):
            group = tokens[index:index + size]
            form = "".join(token[0] for token in group)
            if size == 1 or (len(group) == size and form in single_words):
                joined.append((form, group[0][1], group[-1][2]))
                index += size
                break
    return joined


def _aorist_neutral(form: str) -> str:
    return _AORIST_ENDINGS.sub(lambda match: _AORIST_EQUIVALENTS[match.group(1)], form)


def _name_skeleton(form: str) -> str:
    return re.sub(r"(.)\1+", r"\1", form.removesuffix("ν").translate(_NAME_SKELETON))


def _one_edit_apart(left: str, right: str) -> bool:
    """Whether one letter substitution, insertion, or deletion turns left into right."""
    if abs(len(left) - len(right)) > 1 or left == right:
        return False
    if len(left) == len(right):
        return sum(a != b for a, b in zip(left, right)) == 1
    shorter, longer = sorted((left, right), key=len)
    return any(longer[:i] + longer[i + 1:] == shorter for i in range(len(longer)))


def _same_word(
    rahlfs: str, brenton: str, rahlfs_raw: str, brenton_raw: str, rahlfs_words: frozenset[str]
) -> bool:
    """Whether two differently normalized words are still one word spelled two ways."""
    if rahlfs == brenton:
        return True
    # ἐκ / ἐξ before a vowel; ἕξ "six" has a rough breathing.
    if {rahlfs, brenton} == {"εκ", "εξ"} and not any(
        _ROUGH_BREATHING in unicodedata.normalize("NFD", raw) for raw in (rahlfs_raw, brenton_raw)
    ):
        return True
    # τοῦτʼ / τοῦτο: an elided word is the full word minus its final vowel.
    for short, short_raw, full in ((rahlfs, rahlfs_raw, brenton), (brenton, brenton_raw, rahlfs)):
        if (
            short_raw.rstrip(",.;:·").endswith(_ELISION_MARKS) and len(full) == len(short) + 1
            and full.startswith(short) and full[-1] in "αεοι"
        ):
            return True
    if len(rahlfs) >= 4 and len(brenton) >= 4 and _aorist_neutral(rahlfs) == _aorist_neutral(brenton):
        return True
    # A Brenton word found nowhere in the Rahlfs corpus and one letter away from
    # the Rahlfs word is a keying error or rare spelling (σηέρματος / σπέρματος).
    if len(rahlfs) >= 4 and brenton not in rahlfs_words and _one_edit_apart(rahlfs, brenton):
        return True
    # Proper names are spelled very differently across editions (Βαιθλεεμ /
    # Βηθλεέμ, Βοος / Βοόζ, Ιου / Ἰηού); both editions capitalize them.
    if rahlfs_raw[:1].isupper() and brenton_raw[:1].isupper():
        skeleton = _name_skeleton(rahlfs)
        if skeleton == _name_skeleton(brenton):
            return bool(skeleton) or min(len(rahlfs), len(brenton)) >= 3
    return False


def _unmatched(
    left: list[_Token], right: list[_Token], left_raw: list[str], right_raw: list[str],
    rahlfs_words: frozenset[str],
) -> tuple[list[_Token], list[_Token]]:
    """Drop Rahlfs (left) and Brenton (right) words that are spellings of each other,
    keeping order (LCS)."""
    same = [
        [_same_word(a[0], b[0], left_raw[a[1]], right_raw[b[1]], rahlfs_words) for b in right]
        for a in left
    ]
    lengths = [[0] * (len(right) + 1) for _ in range(len(left) + 1)]
    for i in range(len(left) - 1, -1, -1):
        for j in range(len(right) - 1, -1, -1):
            lengths[i][j] = (
                lengths[i + 1][j + 1] + 1 if same[i][j]
                else max(lengths[i + 1][j], lengths[i][j + 1])
            )
    i = j = 0
    left_only: list[_Token] = []
    right_only: list[_Token] = []
    while i < len(left) and j < len(right):
        if same[i][j]:
            i, j = i + 1, j + 1
        elif lengths[i + 1][j] >= lengths[i][j + 1]:
            left_only.append(left[i])
            i += 1
        else:
            right_only.append(right[j])
            j += 1
    return left_only + left[i:], right_only + right[j:]


def _display(tokens: list[_Token], raw: list[str]) -> str:
    """Printed words (punctuation removed) behind tokens, each raw word once."""
    indexes = dict.fromkeys(index for _, first, last in tokens for index in range(first, last + 1))
    words = [
        unicodedata.normalize("NFC", "".join(ch for ch in raw[index] if unicodedata.category(ch)[0] in "LM"))
        for index in indexes
    ]
    if len(words) > _SUMMARY_WORDS:
        words = [*words[:_SUMMARY_WORDS], "…"]
    return " ".join(words)


def compare_brenton_greek(
    rahlfs: tuple[str, str, str],
    brenton: tuple[str, str, str],
    rahlfs_words: frozenset[str] = frozenset(),
) -> tuple[str, str] | None:
    """Compare the middle verse of Rahlfs and Brenton's Greek after orthographic levelling.

    Both arguments are (previous, current, next) verse texts. The neighbours
    absorb differing verse divisions: words Brenton prints in an adjacent verse
    are not reported as missing. ``rahlfs_words`` (normalized forms of the
    whole Rahlfs corpus) lets a Brenton word unknown to Rahlfs and one letter
    from the Rahlfs word count as a keying error. Returns ``None`` when the
    word sequences agree, otherwise Brenton's Greek for the verse (aligned to
    the Rahlfs verse) and a short summary of word-order changes,
    substitutions, additions and omissions.
    """
    if normalize_greek_text(rahlfs[1]) == normalize_greek_text(brenton[1]):
        return None
    rahlfs_raw = [word for text in rahlfs for word in text.split()]
    brenton_raw = [word for text in brenton for word in text.split()]
    rahlfs_parts = [text.split() for text in rahlfs]
    brenton_parts = [text.split() for text in brenton]
    rahlfs_offsets = (0, len(rahlfs_parts[0]), len(rahlfs_parts[0]) + len(rahlfs_parts[1]))
    brenton_offsets = (0, len(brenton_parts[0]), len(brenton_parts[0]) + len(brenton_parts[1]))
    rahlfs_segments = [_greek_tokens(words, offset) for words, offset in zip(rahlfs_parts, rahlfs_offsets)]
    brenton_segments = [_greek_tokens(words, offset) for words, offset in zip(brenton_parts, brenton_offsets)]
    # Join against both editions so the same phrase is merged on both sides.
    single_words = {token[0] for segment in (*rahlfs_segments, *brenton_segments) for token in segment}
    rahlfs_segments = [_join_split_words(segment, single_words) for segment in rahlfs_segments]
    brenton_segments = [_join_split_words(segment, single_words) for segment in brenton_segments]

    left = [token for segment in rahlfs_segments for token in segment]
    right = [token for segment in brenton_segments for token in segment]
    start, end = len(rahlfs_segments[0]), len(rahlfs_segments[0]) + len(rahlfs_segments[1])
    own_start = len(brenton_segments[0])
    own_end = own_start + len(brenton_segments[1])
    matcher = difflib.SequenceMatcher(
        None, [token[0] for token in left], [token[0] for token in right], autojunk=False
    )
    changes: list[tuple[list[_Token], list[_Token]]] = []
    covered: list[int] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "insert":
            # Words added between two verses belong to the verse Brenton prints them in.
            inside = start < i1 < end or (i1 in (start, end) and own_start <= j1 and j2 <= own_end)
        else:
            inside = i1 < end and i2 > start
        if not inside:
            continue
        if tag == "equal":
            first, last = max(i1, start), min(i2, end)
            covered.extend((j1 + first - i1, j1 + last - i1 - 1))
            continue
        if j2 > j1:
            covered.extend((j1, j2 - 1))
        rahlfs_only, brenton_only = _unmatched(
            left[max(i1, start):min(i2, end)], right[j1:j2], rahlfs_raw, brenton_raw, rahlfs_words
        )
        if rahlfs_only or brenton_only:
            changes.append((rahlfs_only, brenton_only))
    if not changes:
        return None

    # Words present on both sides but in different places are a change of order.
    moved = Counter(token[0] for rahlfs_only, _ in changes for token in rahlfs_only) & Counter(
        token[0] for _, brenton_only in changes for token in brenton_only
    )

    def without_moved(tokens: list[_Token], budget: Counter) -> tuple[list[_Token], list[_Token]]:
        kept, taken = [], []
        for token in tokens:
            if budget[token[0]]:
                budget[token[0]] -= 1
                taken.append(token)
            else:
                kept.append(token)
        return kept, taken

    rahlfs_budget, brenton_budget = Counter(moved), Counter(moved)
    moved_words: list[_Token] = []
    substitutions, additions, omissions = [], [], []
    for rahlfs_only, brenton_only in changes:
        rahlfs_only, taken = without_moved(rahlfs_only, rahlfs_budget)
        moved_words.extend(taken)
        brenton_only, _ = without_moved(brenton_only, brenton_budget)
        if rahlfs_only and brenton_only:
            substitutions.append(
                f"{_display(brenton_only, brenton_raw)} for {_display(rahlfs_only, rahlfs_raw)}"
            )
        elif brenton_only:
            additions.append(_display(brenton_only, brenton_raw))
        elif rahlfs_only:
            omissions.append(_display(rahlfs_only, rahlfs_raw))

    parts = []
    if moved_words:
        parts.append(f"word order differs ({_display(moved_words, rahlfs_raw)})")
    if substitutions:
        parts.append(f"Brenton's Greek reads {', '.join(substitutions)}")
    if additions:
        parts.append(f"Brenton's Greek adds: {' … '.join(additions)}")
    if omissions:
        parts.append(f"Brenton's Greek lacks: {' … '.join(omissions)}")

    if covered:
        first_raw, last_raw = right[min(covered)][1], right[max(covered)][2]
        brenton_text = " ".join(brenton_raw[first_raw:last_raw + 1])
    else:
        brenton_text = brenton[1]
    return brenton_text, "; ".join(parts)


def _detokenize(words: list[dict]) -> str:
    text = " ".join(word["surface"] for word in words)
    text = re.sub(r"\s+([,.;:!?·])", r"\1", text)
    text = re.sub(r"([‘“(])\s+", r"\1", text)
    return text.strip()


def _morphology(words: list[dict]) -> bytes:
    """Store word morphology as zlib-compressed positional JSON arrays.

    Each word is ``[surface, lemma, parsing, pos, confidence, source]`` (see
    LXX_MORPHOLOGY_FIELDS); compression shrinks the column about threefold.
    """
    compact = [[word.get(key) or "" for key in LXX_MORPHOLOGY_FIELDS] for word in words]
    return zlib.compress(json.dumps(compact, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), 9)


def expand_lxx_morphology(value: bytes | None) -> list[dict]:
    """Expand stored morphology into per-word dicts."""
    if not value:
        return []
    return [
        {key: item for key, item in zip(LXX_MORPHOLOGY_FIELDS, word) if item}
        for word in json.loads(zlib.decompress(value))
    ]


def _edition_name(slug: str) -> str:
    suffix = _EDITION_SUFFIXES.get(slug)
    return f"Rahlfs Septuagint (1935), {suffix}" if suffix else "Rahlfs Septuagint (1935)"


def _mapping_targets(mapped: list[dict]) -> tuple[list[tuple[str, str, str]], str]:
    """Return MT targets plus the method label used when there are none."""
    targets: list[tuple[str, str, str]] = []
    for mapping in mapped:
        for mt_ref in mapping.get("mt_refs") or []:
            targets.append((MT_BOOK_CODES[mapping["mt_book"]], mt_ref, mapping["method"]))
    first = mapped[0]
    unpaired_method = first.get("method", "lxx-only")
    if first.get("reason"):
        unpaired_method = f"{unpaired_method} ({first['reason']})"
    return targets, unpaired_method


def _neighbours(values: list[str], index: int) -> tuple[str, str, str]:
    """(previous, current, next) values around ``index``, empty past either end."""
    previous = values[index - 1] if index > 0 else ""
    following = values[index + 1] if index + 1 < len(values) else ""
    return previous, values[index], following


def _rahlfs_words(morphology_dir: Path) -> frozenset[str]:
    """Every normalized word form in the Rahlfs corpus."""
    return frozenset(
        form
        for path in sorted(morphology_dir.glob("*.json"))
        for verse in json.loads(path.read_text(encoding="utf-8"))
        for word in verse["words"]
        for form in normalize_greek_word(word["surface"])
    )


def iter_lxx_rows(
    morphology_dir: Path,
    pairings: dict[tuple[str, str], list[dict]],
    translations: dict[tuple[str, str], str],
    brenton_greek: dict[tuple[str, str], str],
) -> Iterator[tuple]:
    """Yield rows for biblical_version_verses from pinned Rahlfs morphology.

    Paired verses carry the MT/English canonical position from the explicit
    mapping. Verses without an MT counterpart (unpaired pluses, deuterocanonical
    books) get NULL canonical columns, so canonical lookups never return them as
    a counterpart of a different MT verse; they are reachable by their own
    edition (Greek) numbering.

    Rows carrying Brenton's English are compared with Brenton's own Greek for
    the same verse: ``brenton_greek_differs`` is 1 when it differs from Rahlfs
    (and Brenton's Greek plus a difference summary are stored), 0 when it
    agrees, and NULL when there is no English or no Brenton Greek verse. Verses
    whose English is the KJV Apocrypha (see ``is_kjv_apocrypha``) are not
    compared (NULL): that English does not translate Brenton's Greek.
    """
    rahlfs_words = _rahlfs_words(morphology_dir) if brenton_greek else frozenset()
    for path in sorted(morphology_dir.glob("*.json")):
        slug = path.stem
        if slug not in LXX_BOOK_CODES:
            continue
        edition_book = LXX_BOOK_CODES[slug]
        edition = _edition_name(slug)
        translation_code = BRENTON_BOOK_CODES.get(slug)
        # Brenton's Greek prints 2 Esdras (Ezra-Nehemiah) as one book, EZR.
        greek_code = "EZR" if slug == "2-esdras" else translation_code
        verses = json.loads(path.read_text(encoding="utf-8"))
        raw_refs = [verse["ref"].rsplit(" ", 1)[-1] for verse in verses]
        texts = [_detokenize(verse["words"]) for verse in verses]
        greek_texts = [brenton_greek.get((greek_code, raw_ref), "") for raw_ref in raw_refs]
        seen: set[tuple[str, str | None]] = set()
        for index, verse in enumerate(verses):
            raw_ref, text = raw_refs[index], texts[index]
            edition_chapter, edition_verse, edition_suffix = _split_ref(raw_ref)
            edition_ref = f"{edition_book}.{edition_chapter}.{edition_verse}{edition_suffix}"
            mapped = pairings.get((slug, raw_ref)) or [{"method": "lxx-only"}]
            targets, unpaired_method = _mapping_targets(mapped)
            morphology = _morphology(verse["words"])
            translation = translations.get((translation_code, raw_ref)) if translation_code else None

            positions: list[tuple[str | None, str | None, int | None, int | None, str, str | None, str]] = []
            for canonical_book, canonical_raw, method in targets:
                chapter, verse_number, suffix = _split_ref(canonical_raw)
                row_translation = translation
                if slug == "2-esdras":
                    brenton_code = "EZR" if canonical_book == "Ezr" else "NEH"
                    row_translation = translations.get((brenton_code, canonical_raw))
                positions.append((
                    f"{canonical_book}.{chapter}.{verse_number}{suffix}", canonical_book,
                    chapter, verse_number, suffix, row_translation, method,
                ))
            if not positions:
                positions.append((None, None, None, None, "", translation, unpaired_method))

            comparison: tuple[int | None, str | None, str | None] = (None, None, None)
            if (
                greek_texts[index]
                and not is_kjv_apocrypha(edition_book, edition_chapter, edition_verse)
                and any(position[5] for position in positions)
            ):
                difference = compare_brenton_greek(
                    _neighbours(texts, index), _neighbours(greek_texts, index), rahlfs_words
                )
                comparison = (1, *difference) if difference else (0, None, None)

            for canonical_ref, book, chapter, verse_number, suffix, row_translation, method in positions:
                if (edition_ref, canonical_ref) in seen:
                    continue
                seen.add((edition_ref, canonical_ref))
                yield (
                    edition, canonical_ref, book, chapter, verse_number, suffix,
                    edition_ref, edition_book, edition_chapter, edition_verse,
                    edition_suffix, text, row_translation, morphology, method,
                    *(comparison if row_translation else (None, None, None)),
                )


def missing_lxx_sources(lxx_dir: Path) -> list[str]:
    """List required LXX/Brenton English/Brenton Greek files that are absent or truncated."""
    missing = [
        f"morphology/{slug}.json"
        for slug in sorted(LXX_SOURCE_BOOKS)
        if not (lxx_dir / "morphology" / f"{slug}.json").is_file()
    ]
    if not (lxx_dir / "verse_pairs.jsonl").is_file():
        missing.append("verse_pairs.jsonl")

    for directory, required in (
        ("brenton", REQUIRED_BRENTON_BOOKS), ("brenton-greek", REQUIRED_BRENTON_GREEK_BOOKS),
    ):
        books: set[str] = set()
        usfm_dir = lxx_dir / directory
        for path in sorted(usfm_dir.glob("*.usfm")) if usfm_dir.is_dir() else []:
            with path.open(encoding="utf-8-sig") as source:
                id_match = re.match(r"^\\id\s+(\S+)", source.readline())
            if id_match:
                books.add(id_match.group(1))
        missing.extend(f"{directory}/*{code}*.usfm" for code in sorted(required - books))

    manifest_path = lxx_dir / "source_manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        listed = dict(manifest.get("files", {}))
        for key, directory in (("brenton", "brenton"), ("brenton_greek", "brenton-greek")):
            listed.update(
                {f"{directory}/{name}": info for name, info in manifest.get(key, {}).get("files", {}).items()}
            )
        for relative, info in sorted(listed.items()):
            path = lxx_dir / relative
            if not path.is_file():
                missing.append(relative)
            elif "bytes" in info and path.stat().st_size != info["bytes"]:
                missing.append(f"{relative} (size {path.stat().st_size}, expected {info['bytes']})")
    return list(dict.fromkeys(missing))


def import_biblical_versions(conn: sqlite3.Connection, data_dir: Path) -> tuple[int, int]:
    """Replace LXX rows from the downloaded sources; MT is read from ``verses``.

    Returns ``(mt_count, lxx_count)`` where ``mt_count`` is the number of OT
    TAHOT verses available for MT comparison at query time. Raises
    ``FileNotFoundError`` when the LXX download is incomplete.
    """
    lxx_dir = data_dir / "lxx"
    missing = missing_lxx_sources(lxx_dir)
    if missing:
        raise FileNotFoundError(
            f"Incomplete LXX sources in {lxx_dir}: missing {', '.join(missing)}. "
            "Run python scripts/download_biblical_versions.py to complete the download."
        )

    placeholders = ",".join("?" for _ in _OT_CODES)
    mt_count = conn.execute(
        f"SELECT COUNT(*) FROM verses WHERE book IN ({placeholders}) AND text_original IS NOT NULL",
        _OT_CODES,
    ).fetchone()[0]

    pairings = load_lxx_pairings(lxx_dir / "verse_pairs.jsonl")
    translations = parse_brenton_usfm(lxx_dir / "brenton")
    brenton_greek = parse_brenton_usfm(lxx_dir / "brenton-greek")
    rows = iter_lxx_rows(lxx_dir / "morphology", pairings, translations, brenton_greek)
    # Tables created before the Brenton Greek comparison lack its columns.
    existing = {row[1] for row in conn.execute("PRAGMA table_info(biblical_version_verses)")}
    for column, kind in _BRENTON_GREEK_COLUMNS:
        if column not in existing:
            conn.execute(f"ALTER TABLE biblical_version_verses ADD COLUMN {column} {kind}")
    conn.execute("DELETE FROM biblical_version_verses")
    before = conn.total_changes
    conn.executemany(
        """INSERT INTO biblical_version_verses
           (edition, canonical_reference, canonical_book, canonical_chapter,
            canonical_verse, canonical_verse_suffix, edition_reference,
            edition_book, edition_chapter, edition_verse, edition_verse_suffix,
            text, translation, morphology, mapping_method,
            brenton_greek_differs, brenton_greek, brenton_greek_difference)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    lxx_count = conn.total_changes - before
    conn.commit()
    return mt_count, lxx_count
