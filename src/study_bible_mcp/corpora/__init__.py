"""Registry of licensed ancient-source corpora.

Each corpus lives in its own module in this package and defines ``CORPUS``, a
``base.Corpus``. Registering a corpus is one line in ``_CORPUS_MODULES``; the
importer, downloader, search and lookup tools, and smoke runner all iterate
over ``CORPORA``. See ``base.Corpus`` for the interface.
"""

from __future__ import annotations

from importlib import import_module

from .base import (
    CURATED_LINK_RELATIONS,
    LINK_RELATIONS,
    TIERS,
    BiblicalLink,
    Collection,
    Corpus,
    SourceTag,
    TagSection,
    Work,
    combined_license,
)
from .citations import CitationMatch, Resolution, resolve_citation

# One module name per corpus, in display order.
_CORPUS_MODULES = (
    "josephus",
    "targum",
    "qumran",
    "philo",
    "pseudepigrapha",
    "rabbinic",
)


# A corpus caveat is printed once per response: keep it to 1–3 sentences.
MAX_CAVEAT_LENGTH = 320


def validate_labels(corpus: Corpus) -> None:
    """Require a caveat and a complete tag for every work (labelling contract L1–L2)."""
    if not corpus.caveat.strip() or len(corpus.caveat) > MAX_CAVEAT_LENGTH:
        raise ValueError(f"{corpus.key}: declare a caveat of 1–{MAX_CAVEAT_LENGTH} characters")
    for work in corpus.works:
        tag = corpus.work_tag(work)
        if tag is None:
            raise ValueError(f"{corpus.key}: work {work.key!r} has no tag (set Corpus.tag or Work.tag)")
        if not all((tag.status, tag.kind, tag.date, tag.edition)):
            raise ValueError(f"{corpus.key}: work {work.key!r} has an incomplete tag")
        unknown = set(tag.tiers) - set(TIERS)
        if unknown:
            raise ValueError(f"{corpus.key}: work {work.key!r} has unknown tiers {sorted(unknown)}")
        for section in tag.sections:
            if work.locator.parse(section.locator) is None:
                raise ValueError(
                    f"{corpus.key}: tag section {section.locator!r} is not a {work.key} locator"
                )


def build_registry(corpora: tuple[Corpus, ...]) -> dict[str, Corpus]:
    """Index corpora by key, rejecting duplicate keys, works, and directories, and unlabelled works."""
    registry: dict[str, Corpus] = {}
    directories: set[str] = set()
    for corpus in corpora:
        if corpus.key in registry:
            raise ValueError(f"Duplicate corpus key {corpus.key!r}")
        if corpus.data_dir in directories:
            raise ValueError(f"{corpus.key}: data_dir {corpus.data_dir!r} is already used")
        work_keys = [work.key for work in corpus.works]
        if not work_keys or len(set(work_keys)) != len(work_keys):
            raise ValueError(f"{corpus.key}: works must be non-empty with unique keys")
        if not corpus.periods:
            raise ValueError(f"{corpus.key}: declare at least one period tag")
        validate_labels(corpus)
        directories.add(corpus.data_dir)
        registry[corpus.key] = corpus
    return registry


CORPORA: dict[str, Corpus] = build_registry(
    tuple(import_module(f"{__name__}.{name}").CORPUS for name in _CORPUS_MODULES)
)


def all_periods() -> tuple[str, ...]:
    """Every registered period tag, in registry order without duplicates."""
    return tuple(dict.fromkeys(tag for corpus in CORPORA.values() for tag in corpus.periods))


__all__ = [
    "BiblicalLink",
    "CORPORA",
    "CURATED_LINK_RELATIONS",
    "CitationMatch",
    "Collection",
    "Corpus",
    "LINK_RELATIONS",
    "Resolution",
    "SourceTag",
    "TIERS",
    "TagSection",
    "Work",
    "all_periods",
    "build_registry",
    "combined_license",
    "resolve_citation",
    "validate_labels",
]
