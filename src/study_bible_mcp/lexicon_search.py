"""Transliteration-aware matching for search_lexicon.

Lexicon transliterations come in several schemes: BDB's ("checed",
"towrah", "aheb"), STEPBible's syllabified one ("che.sed", "to.rah", "a.hav",
stored as the Hebrew pronunciation) and Greek with macrons ("agapē"). People
type yet others: "hesed", "chesed", "ḥesed", "khesed", "agape", "torah",
"tzedakah". ``fold_transliteration`` reduces all of them to one key, so an
exact transliteration can be found whatever the spelling.

``LexiconIndex`` holds those keys, and each entry's gloss words, for the
whole lexicon (about 19,000 short rows). It answers which entries a query
names exactly or contains, and whose brief definition has the query as a word
or a form of it ('love' -> 'lover', 'beloved'; not 'sin' -> 'since').
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# Applied in order, after accents, case and punctuation are dropped.
_FOLDS = (
    ("sh", "$"),  # shin / sh: kept apart from s and h
    ("ow", "o"), ("uw", "u"), ("iy", "i"),  # BDB vowel letters: towrah, ruwach, beriyth
    ("tz", "s"), ("ts", "s"),  # tsade: tsedaqah, tzedakah, sedaqah
    ("kh", "h"), ("ch", "h"),  # het / chi: chesed, khesed, hesed
    ("ph", "p"), ("f", "p"),  # pe / phi: nephesh, nefesh
    ("th", "t"),  # tav / theta: berith, berit
    ("v", "b"), ("w", "b"),  # bet / vav: ahav, aheb
    ("q", "k"), ("c", "s"),  # qof; BDB's c for samekh: checed
)
_DOUBLE = re.compile(r"(.)\1+")
_FINAL_H = re.compile(r"(?<=[aeiou])h$")
_FILLER = re.compile(r"^(?:to|an?|be|the)\s+")
_GLOSS_SPLIT = re.compile(r"[;:,/]")


def _strip_marks(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def fold_transliteration(text: str) -> str:
    """A spelling-insensitive key for a Latin transliteration.

    'ḥesed', 'hesed', 'chesed', 'khesed' and BDB's 'checed' all give 'hesed';
    'agapē' and 'agape' give 'agape'; 'towrah' and 'torah' give 'tora'.
    """
    text = re.sub(r"[^a-z]", "", _strip_marks(text).lower())
    for old, new in _FOLDS:
        text = text.replace(old, new)
    text = _DOUBLE.sub(r"\1", text)
    return _FINAL_H.sub("", text)


def fold_word(text: str) -> str:
    """Greek or Hebrew script without accents, vowel points or punctuation."""
    text = _strip_marks(text).lower().replace("ς", "σ")
    return "".join(ch for ch in text if ch.isalpha())


def gloss_items(short_definition: str | None) -> set[str]:
    """English items of a brief definition: 'to love: lover, friend' -> {love, lover, friend}."""
    items = set()
    for item in _GLOSS_SPLIT.split((short_definition or "").lower()):
        item = _FILLER.sub("", item.strip())
        if item:
            items.add(item)
    return items


_GLOSS_WORD = re.compile(r"[a-z]+(?:['-][a-z]+)*")
# Endings and prefixes that keep a gloss word about the query's own idea:
# 'love' -> 'loves', 'loved', 'lover', 'loving', 'beloved'; 'sin' -> 'sinner',
# 'sinful'; 'king' -> 'kingdom', 'kingship'. 'since', 'sing' and 'speaking'
# are not forms of 'sin' or 'king'.
_SUFFIXES_KEPT = (
    "", "s", "es", "d", "ed", "r", "er", "ers", "ly", "ing", "ings", "ness", "ful",
    "less", "dom", "ship", "hood", "ment", "ments", "ous",
)
_PREFIXES_KEPT = ("", "be")


def word_forms(query: str) -> frozenset[str]:
    """The query word with the endings and prefixes in _SUFFIXES_KEPT/_PREFIXES_KEPT."""
    bases = {query}
    if query.endswith("e"):
        bases.add(query[:-1])  # loving
    if query.endswith("y"):
        bases.add(query[:-1] + "i")  # holiness
    if len(query) >= 3 and query[-1] not in "aeiouwy":
        bases.add(query + query[-1])  # sinner
    return frozenset(
        prefix + base + suffix
        for prefix in _PREFIXES_KEPT for base in bases for suffix in _SUFFIXES_KEPT
    )


@dataclass(frozen=True)
class _Entry:
    strongs: str
    language: str
    usage: int
    latin: frozenset[str]  # folded transliteration and pronunciation
    word: str  # folded original word
    gloss: str  # brief definition, lower case
    gloss_words: frozenset[str]  # its words; hyphenated compounds stay whole


class LexiconIndex:
    """Folded transliterations and words of every lexicon entry."""

    def __init__(self, rows):
        """``rows``: (strongs, language, transliteration, pronunciation, word,
        short_definition, usage_count) tuples."""
        self._entries: list[_Entry] = []
        self._glosses: dict[str, set[str]] = {}
        for strongs, language, transliteration, pronunciation, word, short, usage in rows:
            latin = frozenset(
                key for key in (
                    fold_transliteration(transliteration or ""),
                    fold_transliteration(pronunciation or ""),
                ) if key
            )
            gloss = (short or "").lower()
            self._entries.append(_Entry(
                strongs, language or "", usage or 0, latin, fold_word(word or ""),
                gloss, frozenset(_GLOSS_WORD.findall(gloss)),
            ))
            self._glosses.setdefault(language or "", set()).update(gloss_items(short))

    def _scope(self, language: str | None) -> list[_Entry]:
        if not language:
            return self._entries
        return [entry for entry in self._entries if entry.language == language]

    def is_gloss(self, query: str, language: str | None = None) -> bool:
        """Whether the query is an English gloss of some entry ('love', 'sin', 'man')."""
        query = _FILLER.sub("", query.strip().lower())
        if language:
            return query in self._glosses.get(language, set())
        return any(query in glosses for glosses in self._glosses.values())

    def gloss_matches(self, query: str, language: str | None = None) -> list[str]:
        """Entries whose brief definition has the query as a word, or a form of it.

        'love' finds 'to love', 'lover' and 'beloved' but 'sin' does not find
        'since' or 'sing', nor 'law' 'daughter-in-law'. A query of several
        words must appear as that phrase. Ordered by usage.
        """
        query = _FILLER.sub("", query.strip().lower())
        if not query:
            return []
        if _GLOSS_WORD.fullmatch(query):
            forms = word_forms(query)
            found = [e for e in self._scope(language) if e.gloss_words & forms]
        else:
            phrase = re.compile(rf"(?<![\w'-]){re.escape(query)}(?![\w'-])")
            found = [e for e in self._scope(language) if phrase.search(e.gloss)]
        return [e.strongs for e in sorted(found, key=lambda e: (-e.usage, e.strongs))]

    def matches(self, query: str, language: str | None = None) -> tuple[list[str], list[str]]:
        """(exact, partial) Strong's numbers for a transliteration or word query.

        Exact: the folded transliteration, pronunciation or word equals the
        query's. Partial: one of them contains it (queries of 3+ letters).
        Each list is ordered by usage, most frequent first.
        """
        latin = fold_transliteration(query)
        word = fold_word(query)
        exact: list[_Entry] = []
        partial: list[_Entry] = []
        for entry in self._scope(language):
            if (latin and latin in entry.latin) or (word and word == entry.word):
                exact.append(entry)
            elif (len(latin) >= 3 and any(latin in key for key in entry.latin)) or (
                len(word) >= 3 and word in entry.word
            ):
                partial.append(entry)

        def order(entries: list[_Entry]) -> list[str]:
            return [e.strongs for e in sorted(entries, key=lambda e: (-e.usage, e.strongs))]

        return order(exact), order(partial)


_SUFFIXES = (
    ("iness", "y"), ("ness", ""), ("ation", "at"), ("ment", ""),
    ("ings", ""), ("ing", ""), ("ies", "y"), ("ed", ""), ("es", ""), ("s", ""),
)


def english_stem(query: str) -> str | None:
    """A shorter form of an English query for a looser gloss match.

    'propitiation' -> 'propitiat' (matches 'to propitiate'), 'righteousness'
    -> 'righteous', 'blessing' -> 'bless'. None when there is no useful stem.
    """
    query = query.strip().lower()
    if len(query) < 6 or not query.isalpha():
        return None
    for suffix, replacement in _SUFFIXES:
        if not query.endswith(suffix) or (suffix in ("s", "es") and query.endswith("ss")):
            continue
        stem = query[: -len(suffix)] + replacement
        return stem if len(stem) >= 4 else None
    return None
