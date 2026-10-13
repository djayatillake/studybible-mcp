"""Types every ancient-source corpus module declares (see ``corpora/__init__.py``)."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .locators import Locator

if TYPE_CHECKING:
    import httpx


@dataclass(frozen=True)
class Collection:
    """A named collection within a corpus, cited as a prefix ('Mishnah', 'Targum Onkelos')."""

    title: str
    aliases: tuple[str, ...] = ()

    @property
    def names(self) -> tuple[str, ...]:
        return (self.title, *self.aliases)


# Date tiers (see the canon review's date ladder). A text's tier says how much
# it can testify to about the first century.
TIERS = {
    "A": "written before or alongside the NT",
    "B": "after the NT (to c. AD 200); first-century background only where an earlier "
         "witness agrees",
}


@dataclass(frozen=True)
class TagSection:
    """A part of a work dated separately, e.g. 1 Enoch's Parables (37–71).

    ``locator`` is text in the work's own citation grammar ('37-71'); a passage
    takes the first section whose range contains its ``sort_start``. Empty
    fields fall back to the work's tag, so a section may set only its
    ``manuscript`` (the Damascus Document's Genizah MS A and MS B).
    """

    locator: str
    name: str = ""
    date: str = ""
    tier: str = ""
    manuscript: str | None = None


@dataclass(frozen=True)
class SourceTag:
    """Canon status, kind, date, tier and edition printed under every result heading.

    Rendered as one line, e.g. 'Not Scripture · Jewish pseudepigraphon
    (Parables, c. 50 BC–AD 117, debated) · tier A/B · Charles 1912'. ``tier`` is
    a key of ``TIERS`` or 'A/B' for a text whose date straddles the NT.
    ``manuscript`` dates the copy served when it is much later than the work
    (the Cairo Genizah Damascus Document).
    """

    kind: str
    date: str
    tier: str
    edition: str
    status: str = "Not Scripture"
    manuscript: str | None = None
    sections: tuple[TagSection, ...] = ()

    @property
    def tiers(self) -> tuple[str, ...]:
        """Every tier this tag can print, each a key of ``TIERS``."""
        return tuple(dict.fromkeys(
            tier for value in (self.tier, *(s.tier for s in self.sections if s.tier))
            for tier in value.split("/")
        ))

    def tier_for(self, section: TagSection | None = None) -> str:
        return section.tier if section and section.tier else self.tier

    def line(self, section: TagSection | None = None) -> str:
        date = self.date
        if section and section.date:
            date = f"{section.name}, {section.date}" if section.name else section.date
        parts = [self.status, f"{self.kind} ({date})", f"tier {self.tier_for(section)}", self.edition]
        manuscript = section.manuscript if section and section.manuscript else self.manuscript
        if manuscript:
            parts.append(manuscript)
        return " · ".join(parts)


@dataclass(frozen=True)
class Work:
    """One citable work and its citation grammar.

    ``reference_title`` is the name used in stored references and lookup
    headings ('Antiquities'); ``aliases`` are further names and abbreviations a
    user may cite ('Ant.', 'A.J.'). Punctuation and spacing in names are not
    significant: 'A.J.' also matches 'AJ' and 'A. J.'. Work keys are unique
    within a corpus; works sharing a title across collections need distinct keys
    (e.g. 'mishnah_bava_batra' and 'other_bava_batra').
    """

    key: str
    title: str
    reference_title: str
    locator: Locator
    aliases: tuple[str, ...] = ()
    collection: Collection | None = None
    # Overrides the corpus's tag (see ``Corpus.tag``) for this work.
    tag: SourceTag | None = None
    # Printed when a citation falls outside the imported passages: what the
    # edition omits ('2 Esdras 1–2 and 15–16 are excluded').
    coverage_note: str = ""

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((self.reference_title, self.title, *self.aliases)))

    @property
    def display_title(self) -> str:
        """Reference title with its collection, e.g. 'Mishnah Shekalim'."""
        if self.collection is None:
            return self.reference_title
        return f"{self.collection.title} {self.reference_title}"


# How a curated link relates a passage to the Bible: ``aligned`` (the Bible
# backs or uses the passage, e.g. Jude 14–15 and 1 Enoch 1:9), ``echo`` (one
# quotes, cites or expounds the other), ``shared_tradition`` (both tell the
# same story or use the same image, with no claim of dependence), ``contrast``
# (the Bible says otherwise), and ``translation`` (a targum verse rendering
# the verse it translates; derived by the corpus, never curated by hand).
LINK_RELATIONS = {
    "aligned": "Aligned",
    "contrast": "Contrast",
    "echo": "Echo",
    "shared_tradition": "Shared tradition",
    "translation": "Translation of",
}
CURATED_LINK_RELATIONS = ("aligned", "echo", "shared_tradition", "contrast")
_ECHO_NOTE = re.compile(r"\b(?:cites|quotes|expounds|explicit reference)\b", re.IGNORECASE)


def default_link_relation(note: str) -> str:
    """``echo`` for a note saying the text cites, quotes or expounds; else ``shared_tradition``."""
    return "echo" if _ECHO_NOTE.search(note) else "shared_tradition"


@dataclass(frozen=True)
class BiblicalLink:
    """A curated editorial link from a passage to a biblical verse range.

    ``locator`` is a point in the work's own citation grammar ('18.116'); the
    link attaches to the imported passage whose sort range contains the start
    of that locator, and the import fails if none does. ``book`` is a
    canonical book code from ``database.BOOK_ABBREV_MAP`` ('Mrk', 'Gen').
    ``relation`` is a key of ``LINK_RELATIONS``; left empty it follows the
    note (``default_link_relation``).
    """

    work_key: str
    locator: str
    book: str
    chapter: int
    verse: int
    end_chapter: int
    end_verse: int
    note: str
    relation: str = ""

    def __post_init__(self) -> None:
        if not self.relation:
            object.__setattr__(self, "relation", default_link_relation(self.note))
        if self.relation not in LINK_RELATIONS:
            raise ValueError(f"Unknown link relation {self.relation!r}")


@dataclass(frozen=True)
class Corpus:
    """Everything the importer, search, lookup, download and smoke tools need.

    Callables:

    - ``download(client, target, force) -> dict``: fetch pinned files into
      ``target`` (``data/ancient_sources/<data_dir>``), verify each checksum,
      raise on any mismatch, and return this corpus's manifest entry.
    - ``require_files(directory)``: raise ``FileNotFoundError`` naming every
      missing file unless the downloaded data is complete.
    - ``parse(directory)``: yield passage dicts (see ``import_corpus``).
    - ``biblical_links(passages)``: the ``BiblicalLink`` entries, given the
      validated passage dicts (static curated lists may ignore them; a corpus
      keyed to biblical verses, such as a targum, can derive one per passage).

    ``search_index_removals`` are regular expressions for printed text that is
    not part of the reading a search should match, such as a transcription's
    scribal erasures; matches are deleted from the search index only.
    ``search_index_gaps`` are regular expressions for printed text that is not
    evidence, such as modern reconstruction in [ ]; each match becomes a word
    break in the search index (the display keeps it).

    ``tag`` is the per-result canon/date/edition tag (a work's own ``tag``
    overrides it); ``caveat`` is printed once per response that shows this
    corpus (1–3 sentences). ``line_numbered`` marks passages whose original
    text is one numbered line per row ('11 text'), so a line citation shows
    only the cited lines and their neighbours. ``no_english_note`` is printed
    above a passage that has only its original ('Yonge has no English for
    this section').
    """

    key: str
    label: str
    summary: str
    data_dir: str
    original_language: str
    works: tuple[Work, ...]
    periods: tuple[str, ...]
    download: Callable[[httpx.Client, Path, bool], dict[str, Any]]
    require_files: Callable[[Path], None]
    parse: Callable[[Path], Iterable[dict[str, Any]]]
    biblical_links: Callable[[list[dict[str, Any]]], Iterable[BiblicalLink]]
    example_query: str
    example_citation: str
    aliases: tuple[str, ...] = ()
    heading_label: str = "Editorial heading"
    search_index_removals: tuple[str, ...] = ()
    search_index_gaps: tuple[str, ...] = ()
    tag: SourceTag | None = None
    caveat: str = ""
    line_numbered: bool = False
    no_english_note: str = "No English translation included"

    def work(self, key: str) -> Work:
        for work in self.works:
            if work.key == key:
                return work
        raise KeyError(f"{self.key}: unknown work {key!r}")

    def work_tag(self, work: Work) -> SourceTag | None:
        return work.tag or self.tag

    def tag_for(
        self, work_key: str | None, sort_start: int | None,
    ) -> tuple[SourceTag | None, TagSection | None]:
        """The tag of a passage of ``work_key`` starting at ``sort_start``, and its dated section."""
        try:
            work = self.work(work_key or "")
        except KeyError:
            return self.tag, None
        tag = self.work_tag(work)
        if tag is not None and sort_start is not None:
            for section in tag.sections:
                bounds = work.locator.parse(section.locator)
                if bounds and bounds[0] <= sort_start <= bounds[1]:
                    return tag, section
        return tag, None

    def tag_line(self, work_key: str | None, sort_start: int | None) -> str | None:
        """The rendered tag for a passage, or None if neither work nor corpus is tagged."""
        tag, section = self.tag_for(work_key, sort_start)
        return tag.line(section) if tag else None

    def tiers(self) -> tuple[str, ...]:
        """Every tier any of this corpus's passages can carry."""
        return tuple(dict.fromkeys(
            tier for work in self.works if (tag := self.work_tag(work)) for tier in tag.tiers
        ))


def combined_license(
    original: str | None,
    translation: str | None,
    original_language: str | None,
    translation_language: str = "English",
) -> str:
    """Human-readable licence for a passage combining its two licences.

    Identical licences collapse to one ('CC BY-SA 4.0'); otherwise each is
    labelled ('Hebrew text: CC BY-NC 4.0; English translation: Public domain').
    """
    if original and translation and original != translation:
        return (
            f"{original_language or 'Original'} text: {original}; "
            f"{translation_language} translation: {translation}"
        )
    combined = original or translation
    if not combined:
        raise ValueError("A passage needs at least one licence")
    return combined
