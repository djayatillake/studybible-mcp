"""Parsers and import helpers for provenance-aware MT/LXX edition text.

Only Septuagint rows are stored in ``biblical_version_verses``. Masoretic rows
are built at query time from the STEPBible TAHOT ``verses`` table, so the MT is
never duplicated in the database.
"""

from __future__ import annotations

import difflib
import json
import math
import re
import sqlite3
import unicodedata
import zlib
from collections import Counter
from collections.abc import Iterator
from functools import cache
from pathlib import Path

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

# USFM is read as a stream of markers (\v, \p, \add, \+it, \add*, a milestone's
# bare \*), not line by line, so verse, paragraph and note markers may stand
# anywhere in a line and notes may run over several lines.
_USFM_MARKER_RE = re.compile(r"\\(\+?[A-Za-z0-9-]*)(\*?)")
# Text after these markers is a title, heading, label or introduction, not
# verse text, until the next paragraph, verse or chapter marker.
_USFM_HEADING_MARKERS = re.compile(
    r"(?:id|ide|usfm|rem|sts|restore|h\d?|toca?\d|mte?\d?|ms\d?|mr|s\d?|sr|r|d|sp|sd\d?"
    r"|cl|cd|lit|qa|qd|periph"
    # introductions (\it, italic, is a character marker and keeps its words)
    r"|imte?\d?|is\d?|ip|ipi|im|imi|ipq|imq|ipr|iq\d?|ib|ili\d?|iot|io\d?|iex|ie)"
)
# Paragraph, poetry, list and table markers: text after them continues the
# verse in progress (a verse may run over several paragraphs or poetic lines).
_USFM_PARAGRAPH_MARKERS = re.compile(
    r"(?:p|m|po|pr|cls|pmo|pm|pmc|pmr|pi\d?|mi|nb|pc|ph\d?|q\d?|qr|qc|qm\d?"
    r"|li\d?|lh|lf|lim\d?|tr|b|pb)"
)
# Character spans whose content is apparatus, not verse text: footnotes,
# endnotes, cross-references, figures, inline quotation references, and
# alternate or published verse and chapter numbers. Each ends at its own
# closing marker (\f ... \f*).
_USFM_DROPPED_SPANS = frozenset({"f", "fe", "ef", "x", "ex", "fig", "rq", "va", "vp", "ca", "cat"})
# USFM 3 word attributes (\w λόγος|lemma="λόγος"\w*) end at the closing marker.
_USFM_ATTRIBUTES_RE = re.compile(r"\|[^\\|]*(?=\\\+?[A-Za-z0-9-]*\*)")
_USFM_CHAPTER_RE = re.compile(r"\s*(\d+)")
# A verse number, lettered (12a), or a bridge (10-11) stored under its first verse.
_USFM_VERSE_RE = re.compile(r"\s*(\d+)([A-Za-z]?)(?:[-‐–]\d+[A-Za-z]?)?")


def _split_ref(reference: str) -> tuple[int, int, str]:
    match = _REF_RE.match(reference)
    if not match:
        raise ValueError(f"Unsupported edition reference: {reference}")
    return int(match.group(1)), int(match.group(2)), match.group(3).lower()


def _usfm_verses(content: str) -> dict[str, list[str]]:
    """Split one USFM book into {"chapter:verse": [text pieces]}, markup removed.

    Opening markers consume the one space that ends them; closing markers
    (\\add*) consume nothing, so "is\\add* good" keeps its space. Text after
    a chapter marker and before its first verse (an unnumbered introduction)
    belongs to no verse. A verse number repeated within a chapter continues
    that verse.
    """
    content = _USFM_ATTRIBUTES_RE.sub("", content.replace("~", " ").replace("//", " "))
    verses: dict[str, list[str]] = {}
    chapter: str | None = None
    verse: str | None = None
    heading = False
    dropped: str | None = None  # the dropped span being skipped (f, x, ...)
    position = 0

    def keep(text: str) -> None:
        if verse is not None and not heading and dropped is None and text:
            verses[verse].append(text)

    for match in _USFM_MARKER_RE.finditer(content):
        if match.start() < position:  # inside a chapter or verse number already read
            continue
        keep(content[position:match.start()])
        name, closing = match.group(1).lstrip("+"), match.group(2)
        position = match.end()
        if closing:
            if dropped is not None and name == dropped:
                dropped = None
            continue
        if position < len(content) and content[position] in " \t\r\n":
            position += 1
        if dropped is not None:
            # A note never spans a verse, chapter or paragraph; an unclosed one ends there.
            if name not in ("v", "c") and not _USFM_PARAGRAPH_MARKERS.fullmatch(name) \
                    and not _USFM_HEADING_MARKERS.fullmatch(name):
                continue
            dropped = None
        if name == "c":
            number = _USFM_CHAPTER_RE.match(content, position)
            if number:
                chapter, verse, heading = number.group(1), None, False
                position = number.end()
        elif name == "v":
            number = _USFM_VERSE_RE.match(content, position)
            if number and chapter is not None:
                verse = f"{chapter}:{number.group(1)}{number.group(2).lower()}"
                verses.setdefault(verse, [])
                heading = False
                position = number.end()
        elif name in _USFM_DROPPED_SPANS:
            dropped = name
        elif _USFM_PARAGRAPH_MARKERS.fullmatch(name):
            heading = False
        elif _USFM_HEADING_MARKERS.fullmatch(name):
            heading = True
    keep(content[position:])
    return verses


# Corrections to eBible's Brenton USFM (the pinned files), applied before it
# is parsed: the book, why, and each (text as eBible has it, corrected text).
# A correction applies only where every one of its texts occurs exactly once;
# a file with none of them (a corrected upstream file, the other language) is
# left alone, and a file with only some of them is an error.
BRENTON_USFM_CORRECTIONS: tuple[tuple[str, str, tuple[tuple[str, str], ...]], ...] = (
    (
        "PSA",
        "eBible's Greek Psalm 12 (20-PSAgrcbrent.usfm) lacks the marker of verse 2: its "
        "words stand in a paragraph of verse 1, the title, so verses 3-5 are numbered 2-4 "
        "and verse 6 is split between 5 and 6. Brenton's English and Rahlfs number the "
        "Psalm 1-6, with 'I will sing to the Lord' in verse 6.",
        (
            ("\\p Ἕως πότε Κύριε ἐπιλήσῃ μου,", "\\p\n\\v 2 Ἕως πότε Κύριε ἐπιλήσῃ μου,"),
            ("\\v 2 Ἕως τίνος θήσομαι", "\\v 3 Ἕως τίνος θήσομαι"),
            ("\\v 3 Ἐπίβλεψον, εἰσάκουσόν μου", "\\v 4 Ἐπίβλεψον, εἰσάκουσόν μου"),
            ("\\v 4 μή ποτε εἴποι", "\\v 5 μή ποτε εἴποι"),
            ("\\v 5 Ἐγὼ δὲ ἐπὶ τῷ ἐλέει σου ἤλπισα", "\\v 6 Ἐγὼ δὲ ἐπὶ τῷ ἐλέει σου ἤλπισα"),
            ("\\v 6 Ἄσω τῷ Κυρίῳ τῷ εὐεργετήσαντί με", "Ἄσω τῷ Κυρίῳ τῷ εὐεργετήσαντί με"),
        ),
    ),
)


def correct_brenton_usfm(book: str, content: str) -> str:
    """Apply BRENTON_USFM_CORRECTIONS for ``book`` to one USFM file's content."""
    for code, reason, replacements in BRENTON_USFM_CORRECTIONS:
        if code != book:
            continue
        counts = [content.count(old) for old, _ in replacements]
        if not any(counts):
            continue
        if counts != [1] * len(replacements):
            raise ValueError(f"{book} USFM no longer matches its correction ({reason})")
        for old, new in replacements:
            content = content.replace(old, new)
    return content


def parse_brenton_usfm(directory: Path) -> dict[tuple[str, str], str]:
    """Read eBible's Brenton USFM files into (book code, chapter:verse) text.

    Verse text runs from its verse marker to the next verse or chapter
    marker, across paragraph and poetry markers (\\p, \\q1, \\m, \\nb, ...),
    wherever in a line the markers stand. Headings, titles, introductions,
    notes and cross-references are left out; character markup (\\add, \\nd,
    \\+it, \\w ...|lemma\\w*) keeps its words. Known errors in eBible's
    files are corrected first (BRENTON_USFM_CORRECTIONS).
    """
    translations: dict[tuple[str, str], str] = {}
    for path in sorted(directory.glob("*.usfm")):
        content = path.read_text(encoding="utf-8-sig")
        id_match = re.search(r"^\\id\s+(\S+)", content, re.MULTILINE)
        if not id_match:
            continue
        book = id_match.group(1)
        for reference, pieces in _usfm_verses(correct_brenton_usfm(book, content)).items():
            translations[(book, reference)] = re.sub(r"\s+", " ", "".join(pieces)).strip()
    return translations


PSALM_SUPERSCRIPTION_METHOD = "tvtms, superscription as verse 0"


def load_lxx_pairings(path: Path) -> dict[tuple[str, str], list[dict]]:
    """Index the explicit LXX→MT versification map by Greek book and verse.

    The map pairs a Greek Psalm's superscription verses with English verse 1
    (Psalm 51's three Greek verses 50:1-3 all with 51:1), but the `verses`
    table and the BSB number superscriptions verse 0. Where several Greek
    verses map to an English Psalm's verse 1 alone, all but the last are the
    superscription and are paired with verse 0 (see
    ``pair_psalm_superscriptions``).
    """
    pairings: dict[tuple[str, str], list[dict]] = {}
    with path.open(encoding="utf-8") as source:
        for line in source:
            record = json.loads(line)
            pairings.setdefault((record["grk_book"], record["grk_ref"]), []).append(record)
    pair_psalm_superscriptions(pairings)
    return pairings


def pair_psalm_superscriptions(pairings: dict[tuple[str, str], list[dict]]) -> None:
    """Re-pair Greek Psalm superscription verses with English verse 0, in place.

    Each English Psalm's verse 1 can be the target of several Greek verses
    only because the superscription (Greek verse 1, or 1-2) is counted with
    it: the number of extra Greek verses equals the number of Hebrew verses
    the `verses` table numbers 0 in every Psalm. A short title sharing its
    verse with the Psalm's first words (Greek 10:1 = Psalm 11:0-1) stays
    paired with verse 1.
    """
    by_psalm: dict[str, list[tuple[int, dict]]] = {}
    for (book, greek_ref), records in pairings.items():
        if book != "psalms-lxx":
            continue
        for record in records:
            refs = record.get("mt_refs") or []
            if len(refs) == 1 and refs[0].endswith(":1") and record.get("mt_book") == "psalms":
                chapter, verse, _ = _split_ref(greek_ref)
                by_psalm.setdefault(refs[0], []).append(((chapter, verse), record))
    for target, records in by_psalm.items():
        records.sort(key=lambda item: item[0])
        for _, record in records[:-1]:
            record["mt_refs"] = [f"{target.split(':')[0]}:0"]
            record["method"] = PSALM_SUPERSCRIPTION_METHOD


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


@cache
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


# Aligning Brenton's verses with Rahlfs's (see align_brenton_keys). Scores are
# weighted Dice coefficients of the two verses' normalized word sets, 0-1.
_ALIGNED = 0.5  # a Rahlfs verse this close to Brenton's verse of its number keeps it
_REALIGN = 0.6  # a better Brenton verse must score at least this ...
_REALIGN_GAIN = 0.25  # ... and this much more than the verse of the same number
_REALIGN_ALONE = 0.85  # a realignment with no realigned neighbour needs this, in its chapter
_CONTAINED = 0.8  # share of a Rahlfs verse's (weighted) words within a Brenton verse that holds it
_NEARBY = 3  # Brenton verses this many places either side of a verse's own number are nearby
# Brenton's English and Greek files share verse numbers; where one merges or
# misnumbers verses, their lengths can disagree.
_ENGLISH_GREEK_LENGTHS = (0.5, 2.6)
_ENGLISH_STOPWORDS = frozenset(
    "the a an and of to in on for with be is are was were you your i me my he him his it "
    "they them their we us our that this not but or as from by at shall will thou thee thy "
    "ye hath have has o unto upon which who all".split()
)


def _english_words(text: str) -> set[str]:
    """An English verse's content words (first five letters)."""
    return {
        word[:5] for word in re.findall(r"[a-z]+", text.lower())
        if len(word) > 2 and word not in _ENGLISH_STOPWORDS
    }


def _english_overlap(left: str, right: str) -> float:
    """Dice overlap of two English verses' content words (first five letters)."""
    left_words, right_words = _english_words(left), _english_words(right)
    if not left_words or not right_words:
        return 0.0
    return 2 * len(left_words & right_words) / (len(left_words) + len(right_words))


# A Brenton Greek verse repeating its neighbour (see without_repeated_verses):
_REPEAT_COVERAGE = 0.9  # this much of the neighbour's words, in order, at one end of the verse ...
_REPEAT_ENGLISH = 0.6  # ... where his English for the two shares less than this of its words
_REPEAT_REMAINDER = 0.1  # a verse with no more than this left over is nothing but the copy


def without_repeated_verses(
    greek: dict[str, str], english: dict[str, str], rahlfs: dict[str, str] | None = None
) -> dict[str, str]:
    """One book of Brenton's Greek without the copies of a neighbouring verse it repeats.

    eBible's transcription repeats a few verses by mistake: Job 3:14 and
    3 Kingdoms 8:58 begin with the whole of the verse before, 1 Chronicles
    11:24 ends with the whole of the verse after, and Numbers 34:10 is a second
    copy of 34:11 instead of its own text. Brenton's English does not repeat
    them, which tells a keying error from a refrain or formula (repeated in his
    English too). ``greek`` and ``english`` map Brenton's verse numbers to his
    text in file order; ``rahlfs`` maps Rahlfs verse numbers to the Rahlfs text.

    The neighbour's words found again, in order, at the start or end of a
    verse are removed from it. Where the two verses are the same text, the copy
    is removed altogether: the one further from the Rahlfs verse of its number,
    or both when Rahlfs cannot tell.
    """
    rahlfs = rahlfs or {}
    corrected = dict(greek)
    keys = list(greek)
    for pair in zip(keys, keys[1:]):
        if pair[0].split(":")[0] != pair[1].split(":")[0] or not all(key in corrected for key in pair):
            continue
        english_words = [_english_words(english.get(key, "")) for key in pair]
        if not all(english_words) or len(english_words[0] & english_words[1]) >= _REPEAT_ENGLISH * min(
            len(words) for words in english_words
        ):
            continue
        tokens = {key: _greek_tokens(corrected[key].split(), 0) for key in pair}
        short, long = sorted(pair, key=lambda key: len(tokens[key]))
        blocks = [
            block for block in difflib.SequenceMatcher(
                None, [form for form, _, _ in tokens[short]], [form for form, _, _ in tokens[long]],
                autojunk=False,
            ).get_matching_blocks()
            if block.size >= 2
        ]
        if not tokens[short] or sum(block.size for block in blocks) < _REPEAT_COVERAGE * len(tokens[short]):
            continue
        start, end = blocks[0].b, blocks[-1].b + blocks[-1].size
        if start and end < len(tokens[long]):
            continue  # inside the verse, not a copy appended to it
        if len(tokens[long]) - (end - start) > _REPEAT_REMAINDER * len(tokens[long]):
            words = corrected[long].split()
            first_word, last_word = tokens[long][start][1], tokens[long][end - 1][2]
            corrected[long] = " ".join(words[:first_word] + words[last_word + 1:])
            continue

        def own_match(key: str) -> float:
            own, theirs = set(normalize_greek_text(rahlfs.get(key, ""))), {form for form, _, _ in tokens[key]}
            return 2 * len(own & theirs) / (len(own) + len(theirs)) if own and theirs else 0.0

        matches = {key: own_match(key) for key in pair}
        for key in pair:
            if matches[key] <= min(matches.values()):
                del corrected[key]
    return corrected


def align_brenton_keys(
    rahlfs: list[tuple[str, str]],
    brenton_greek: dict[str, str],
    brenton_english: dict[str, str],
    reference_english: dict[str, str] | None = None,
) -> dict[str, str | None]:
    """Find Rahlfs verses that Brenton numbers differently, by their Greek.

    ``rahlfs`` is one book's (verse, Greek text) in file order; ``brenton_greek``
    and ``brenton_english`` map Brenton's verse numbers for the same book to
    his Greek and English, in file order. Returns ``{rahlfs verse: Brenton
    verse}`` for each Rahlfs verse whose own number in Brenton holds other text
    (the Letter of Jeremiah is one verse behind Brenton's; Brenton prints
    Sirach's prologue as 1:1-1:1g and its 1:1 as 1:1h; his Proverbs 24:22a-t
    is Rahlfs 30:1-14). The value is None for a verse whose Brenton verse
    went to a closer match, when no other Brenton verse holds it: its own
    number holds another verse's English.

    A verse is moved only when its own number matches poorly, another Brenton
    verse matches it well and much better, that verse is not already matched
    by the Rahlfs verse of its own number, and Brenton's English and Greek for
    it are of comparable length. A move must also continue a neighbour's move
    (a run of renumbered verses), or match very closely within its chapter.
    A verse whose own Brenton verse was moved to another verse then follows
    its text to wherever Brenton prints it (Brenton's 4 Maccabees 7:24-8:1 is
    Rahlfs 8:1-2), unless it lies within that verse too. Words are weighted by
    rarity, so refrains (Daniel 3's "bless the Lord") do not make verses
    match. ``reference_english`` (another English version of a Rahlfs verse:
    the BSB of its MT verse) vetoes a move whose English is further from it
    than the English of the verse's own number, where Brenton's Greek is a
    verse out from his English, which is not (eBible's Greek Psalm 12 was,
    until BRENTON_USFM_CORRECTIONS restored its verse 2).
    """
    reference_english = reference_english or {}
    rahlfs_words = {ref: frozenset(normalize_greek_text(text)) for ref, text in rahlfs}
    brenton_words = {key: frozenset(normalize_greek_text(text)) for key, text in brenton_greek.items()}
    frequency: Counter = Counter()
    for words in (*rahlfs_words.values(), *brenton_words.values()):
        frequency.update(words)
    total = len(rahlfs_words) + len(brenton_words)
    weight = {word: math.log(1 + total / count) for word, count in frequency.items()}

    def score(left: frozenset, right: frozenset) -> float:
        if not left or not right:
            return 0.0
        shared = sum(weight[word] for word in left & right)
        return 2 * shared / (sum(weight[word] for word in left) + sum(weight[word] for word in right))

    def comparable_lengths(key: str) -> bool:
        english, greek = brenton_english.get(key), brenton_greek.get(key)
        if not english or not greek:
            return False
        low, high = _ENGLISH_GREEK_LENGTHS
        return low <= len(english) / len(greek) <= high

    own = {
        ref: score(words, brenton_words.get(ref, frozenset())) for ref, words in rahlfs_words.items()
    }
    taken = {ref for ref, value in own.items() if value >= _ALIGNED and ref in brenton_words}
    free = [key for key in brenton_words if key not in taken and comparable_lengths(key)]
    proposals: dict[str, tuple[str, float]] = {}
    for ref, words in rahlfs_words.items():
        if own[ref] >= _ALIGNED or not free:
            continue
        best = max(free, key=lambda key: score(words, brenton_words[key]))
        value = score(words, brenton_words[best])
        if value >= _REALIGN and value >= own[ref] + _REALIGN_GAIN:
            proposals[ref] = (best, value)

    position = {key: index for index, key in enumerate(brenton_words)}
    order = [ref for ref, _ in rahlfs]
    accepted: dict[str, tuple[str, float]] = {}
    for index, ref in enumerate(order):
        if ref not in proposals:
            continue
        key, value = proposals[ref]
        continues_run = any(
            neighbour in proposals
            and abs(position[proposals[neighbour][0]] - position[key]) == 1
            for neighbour in order[max(index - 1, 0):index] + order[index + 1:index + 2]
        )
        same_chapter = key.split(":")[0] == ref.split(":")[0]
        if not (continues_run or (value >= _REALIGN_ALONE and same_chapter)):
            continue
        reference = reference_english.get(ref)
        if reference and _english_overlap(reference, brenton_english.get(key, "")) < _english_overlap(
            reference, brenton_english.get(ref, "")
        ):
            continue
        accepted[ref] = (key, value)

    # One Brenton verse goes to its closest Rahlfs verse; the others lose the
    # verse of their own number, which belongs to someone else.
    best_for_key: dict[str, str] = {}
    for ref, (key, value) in accepted.items():
        if key not in best_for_key or value > accepted[best_for_key[key]][1]:
            best_for_key[key] = ref
    moved: dict[str, str | None] = {
        ref: key if best_for_key[key] == ref else None for ref, (key, _) in accepted.items()
    }

    # So does a Rahlfs verse whose own number went to the verse it belongs to
    # (Rahlfs 4 Maccabees 8:2 is Brenton's 7:25-8:1), unless it lies within that
    # Brenton verse too (Brenton joins two Rahlfs verses). It takes the Brenton
    # verse closest to it instead (Rahlfs 8:1 is Brenton's 7:24) when that is
    # as close as an aligned verse, or else a nearby Brenton verse that holds
    # it, provided Brenton's English for that verse is no further from the
    # reference English than his English of its own number.
    def within(words: frozenset, key: str) -> float:
        total = sum(weight[word] for word in words)
        return sum(weight[word] for word in words & brenton_words.get(key, frozenset())) / total if total else 0.0

    for ref, words in rahlfs_words.items():
        if ref in moved or ref not in best_for_key or within(words, ref) >= _CONTAINED:
            continue
        candidates = [key for key in brenton_words if key != ref and comparable_lengths(key)]
        best = max(candidates, key=lambda key: score(words, brenton_words[key]), default=None)
        if best is None or score(words, brenton_words[best]) < _ALIGNED:
            nearby = [key for key in candidates if abs(position[key] - position[ref]) <= _NEARBY]
            best = max(nearby, key=lambda key: within(words, key), default=None)
            if best is None or within(words, best) < _CONTAINED:
                moved[ref] = None
                continue
        reference = reference_english.get(ref)
        if reference and _english_overlap(reference, brenton_english.get(best, "")) < _english_overlap(
            reference, brenton_english.get(ref, "")
        ):
            continue
        moved[ref] = best
    return moved


def iter_lxx_rows(
    morphology_dir: Path,
    pairings: dict[tuple[str, str], list[dict]],
    translations: dict[tuple[str, str], str],
    brenton_greek: dict[tuple[str, str], str],
    bsb: dict[str, str] | None = None,
) -> Iterator[tuple]:
    """Yield rows for biblical_version_verses from pinned Rahlfs morphology.

    Paired verses carry the MT/English canonical position from the explicit
    mapping. Verses without an MT counterpart (unpaired pluses, deuterocanonical
    books) get NULL canonical columns, so canonical lookups never return them as
    a counterpart of a different MT verse; they are reachable by their own
    edition (Greek) numbering.

    Brenton's English and Greek for a verse are those of the same number,
    except where Brenton numbers the text differently (``align_brenton_keys``,
    checked against ``bsb``: BSB text by MT reference, when available).
    Rows carrying Brenton's English are compared with Brenton's own Greek for
    the same verse, less any copy of a neighbouring verse that eBible's
    transcription repeats (``without_repeated_verses``): ``brenton_greek_differs``
    is 1 when it differs from Rahlfs (and Brenton's Greek plus a difference
    summary are stored), 0 when it agrees, and NULL when there is no English or
    no Brenton Greek verse (Numbers 34:10, which eBible replaces with 34:11). Verses
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
        # Brenton's verse for each Rahlfs verse: the same number, except where
        # Brenton numbers the text differently. 2 Esdras takes its English
        # from Brenton's Ezra and Nehemiah by MT verse instead.
        brenton_refs: list[str | None] = list(raw_refs)
        book_greek = {key: text for (code, key), text in brenton_greek.items() if code == greek_code}
        if translation_code and slug != "2-esdras":
            book_english = {key: text for (code, key), text in translations.items() if code == translation_code}
            book_greek = without_repeated_verses(book_greek, book_english, dict(zip(raw_refs, texts)))
            reference_english = {}
            for raw_ref in raw_refs:
                targets, _ = _mapping_targets(pairings.get((slug, raw_ref)) or [{}])
                english = " ".join(
                    (bsb or {}).get(f"{book}.{chapter}.{verse_number}", "")
                    for book, target, _ in targets
                    for chapter, verse_number, _ in [_split_ref(target)]
                ).strip()
                if english:
                    reference_english[raw_ref] = english
            moved = align_brenton_keys(list(zip(raw_refs, texts)), book_greek, book_english, reference_english)
            brenton_refs = [moved.get(raw_ref, raw_ref) for raw_ref in raw_refs]
        greek_texts = [book_greek.get(brenton_ref, "") if brenton_ref else "" for brenton_ref in brenton_refs]
        seen: set[tuple[str, str | None]] = set()
        for index, verse in enumerate(verses):
            raw_ref, text = raw_refs[index], texts[index]
            edition_chapter, edition_verse, edition_suffix = _split_ref(raw_ref)
            edition_ref = f"{edition_book}.{edition_chapter}.{edition_verse}{edition_suffix}"
            mapped = pairings.get((slug, raw_ref)) or [{"method": "lxx-only"}]
            targets, unpaired_method = _mapping_targets(mapped)
            morphology = _morphology(verse["words"])
            brenton_ref = brenton_refs[index]
            translation = (
                translations.get((translation_code, brenton_ref))
                if translation_code and brenton_ref else None
            )

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


def bsb_by_reference(conn: sqlite3.Connection) -> dict[str, str]:
    """BSB text by reference ('Psa.13.2'), or {} when the database has no BSB."""
    try:
        return dict(conn.execute("SELECT reference, text FROM bsb_verses"))
    except sqlite3.OperationalError:
        return {}


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
    rows = iter_lxx_rows(
        lxx_dir / "morphology", pairings, translations, brenton_greek, bsb_by_reference(conn)
    )
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
