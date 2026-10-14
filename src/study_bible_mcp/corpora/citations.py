"""Resolve a free-text citation ('Ant. 18.116', 'm. Shek. 1:1') to a work and sort range."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cache

from .base import Corpus, Work
from .locators import SortRange

_SKIP = re.compile(r"[\s.,]*")
# Apostrophes inside transliterated names are ignored: "Ta'anit" = "Taanit".
_APOSTROPHES = re.compile(r"['’ʼ]")


@dataclass(frozen=True)
class CitationMatch:
    """A work whose name prefixes the citation; ``sort_range`` is None if the rest did not parse."""

    corpus: Corpus
    work: Work
    locator_text: str
    sort_range: SortRange | None
    name_length: int

    @property
    def heading(self) -> str:
        return f"{self.work.display_title} {self.locator_text}".strip()


@dataclass(frozen=True)
class Resolution:
    """``status``: ``ok`` (one ``match``), ``ambiguous``, ``bad_locator``, or ``unknown_work``.

    ``candidates`` lists the competing works for ``ambiguous`` and the
    name-matched works whose locator did not parse for ``bad_locator``.
    """

    status: str
    match: CitationMatch | None = None
    candidates: tuple[CitationMatch, ...] = ()


@cache
def _name_regex(name: str) -> re.Pattern[str]:
    """Match a name ignoring case, punctuation, dashes and spacing ('A.J.' ~ 'AJ', 'Tg. Onq.' ~ 'Tg Onq')."""
    tokens = re.findall(r"[^\W_]+", name.lower())
    if not tokens:
        raise ValueError(f"Citation name {name!r} has no letters or digits")
    return re.compile(r"[\s.,\-‐‑‒–—]*".join(map(re.escape, tokens)) + r"(?![^\W_])", re.IGNORECASE)


def _after(name: str, text: str, position: int) -> int | None:
    """Position after ``name`` and any trailing punctuation, if it occurs at ``position``."""
    match = _name_regex(name).match(text, position)
    return match.end() if match else None


def _prefix_ends(names: Iterable[str], text: str, position: int) -> list[int]:
    ends = [position]
    for name in names:
        end = _after(name, text, position)
        if end is not None:
            ends.append(_SKIP.match(text, end).end())
    return ends


def _work_matches(corpus: Corpus, text: str) -> list[CitationMatch]:
    matches: dict[str, CitationMatch] = {}
    for start in _prefix_ends(corpus.aliases, text, 0):
        for work in corpus.works:
            collection_names = work.collection.names if work.collection else ()
            for position in _prefix_ends(collection_names, text, start):
                for name in work.names:
                    end = _after(name, text, position)
                    if end is None:
                        continue
                    locator_text = text[end:].strip(" .,")
                    best = matches.get(work.key)
                    if best is None or end > best.name_length:
                        matches[work.key] = CitationMatch(
                            corpus, work, locator_text, work.locator.parse(locator_text), end
                        )
    return list(matches.values())


def resolve_citation(citation: str, corpora: Iterable[Corpus]) -> Resolution:
    """Resolve ``citation`` against the works of ``corpora``.

    A citation is ``[corpus alias] [collection name] work name locator``, e.g.
    'Josephus, Ant. 18.116' or 'Mishnah Shekalim 1:1'. Among works whose name
    prefixes the citation and whose locator grammar parses the rest, the
    longest name match wins; a tie between different works is ambiguous (a
    collection prefix such as 'Mishnah' breaks it).
    """
    text = _APOSTROPHES.sub("", unicodedata.normalize("NFC", citation)).strip()
    candidates = [match for corpus in corpora for match in _work_matches(corpus, text)]
    if not candidates:
        return Resolution("unknown_work")
    parsed = [match for match in candidates if match.sort_range is not None]
    pool = parsed or candidates
    longest = max(match.name_length for match in pool)
    best = tuple(match for match in pool if match.name_length == longest)
    if not parsed:
        return Resolution("bad_locator", candidates=best)
    if len(best) > 1:
        return Resolution("ambiguous", candidates=best)
    return Resolution("ok", match=best[0])
