"""Types every ancient-source corpus module declares (see ``corpora/__init__.py``)."""

from __future__ import annotations

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

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((self.reference_title, self.title, *self.aliases)))

    @property
    def display_title(self) -> str:
        """Reference title with its collection, e.g. 'Mishnah Shekalim'."""
        if self.collection is None:
            return self.reference_title
        return f"{self.collection.title} {self.reference_title}"


@dataclass(frozen=True)
class BiblicalLink:
    """A curated editorial link from a passage to a biblical verse range.

    ``locator`` is a point in the work's own citation grammar ('18.116'); the
    link attaches to the imported passage whose sort range contains the start
    of that locator, and the import fails if none does. ``book`` is a
    canonical book code from ``database.BOOK_ABBREV_MAP`` ('Mrk', 'Gen').
    """

    work_key: str
    locator: str
    book: str
    chapter: int
    verse: int
    end_chapter: int
    end_verse: int
    note: str


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

    def work(self, key: str) -> Work:
        for work in self.works:
            if work.key == key:
                return work
        raise KeyError(f"{self.key}: unknown work {key!r}")


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
