"""Curated verse-level editorial notes and typed biblical links (labelling contract L3–L4).

The committed data file ``editorial_notes.json`` beside this module holds::

    {"notes": [{"corpus": "pseudepigrapha", "citation": "1 Enoch 71:14",
                "kind": "emendation", "text": "...",
                "contrast": ["Mark 14:62"], "aligned": []}],
     "links": [{"corpus": "pseudepigrapha", "citation": "1 Enoch 10:4-6",
                "relation": "aligned", "biblical": "Jude 6", "note": "..."}]}

``citation`` uses the citation grammar of ``lookup_ancient_source``; a
citation covering several passages attaches to each. ``load_editorial_notes``
validates the structure, kinds, relations, citation grammar and biblical
references; the importer then fails if a citation covers no imported passage
(a ``gap`` note instead attaches to the passages either side of its range).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..database import format_biblical_range, parse_biblical_range
from .base import CURATED_LINK_RELATIONS
from .citations import resolve_citation

NOTES_PATH = Path(__file__).with_name("editorial_notes.json")
NOTE_KINDS = (
    "emendation", "interpolation", "reconstruction", "contrast", "polemic", "caution", "gap",
)
# Notes print beside the passage: keep them short.
MAX_NOTE_LENGTH = 250

_NOTE_FIELDS = {"corpus", "citation", "kind", "text", "contrast", "aligned"}
_LINK_FIELDS = {"corpus", "citation", "relation", "biblical", "note"}


@dataclass(frozen=True)
class EditorialNote:
    """A note on the passages a citation covers; references are rendered ('Mark 14:62')."""

    corpus: str
    citation: str
    kind: str
    text: str
    contrast: tuple[str, ...] = ()
    aligned: tuple[str, ...] = ()


@dataclass(frozen=True)
class EditorialLink:
    """A typed link from the passages a citation covers to a biblical range."""

    corpus: str
    citation: str
    relation: str
    book: str
    chapter: int
    verse: int
    end_chapter: int
    end_verse: int
    note: str


@dataclass(frozen=True)
class EditorialNotes:
    notes: tuple[EditorialNote, ...] = ()
    links: tuple[EditorialLink, ...] = ()

    def for_corpus(self, key: str) -> tuple[list[EditorialNote], list[EditorialLink]]:
        return (
            [note for note in self.notes if note.corpus == key],
            [link for link in self.links if link.corpus == key],
        )


def _text(entry: dict, field: str, where: str, required: bool = True) -> str:
    value = entry.get(field, "")
    if not isinstance(value, str) or (required and not value.strip()):
        raise ValueError(f"{where}: '{field}' must be a non-empty string")
    if len(value) > MAX_NOTE_LENGTH:
        raise ValueError(f"{where}: '{field}' is longer than {MAX_NOTE_LENGTH} characters")
    return value.strip()


def _biblical(reference: object, where: str) -> tuple[str, int, int, int, int]:
    parsed = parse_biblical_range(reference) if isinstance(reference, str) else None
    if parsed is None:
        raise ValueError(f"{where}: biblical reference {reference!r} does not parse")
    return parsed


def _check_citation(corpus_key: str, citation: str, where: str) -> None:
    from . import CORPORA  # The registry imports no editorial data.

    corpus = CORPORA.get(corpus_key)
    if corpus is None:
        raise ValueError(f"{where}: unknown corpus {corpus_key!r}")
    if resolve_citation(citation, [corpus]).status != "ok":
        raise ValueError(f"{where}: citation {citation!r} does not resolve in {corpus_key}")


def parse_editorial_notes(data: object, source: str = "editorial notes") -> EditorialNotes:
    """Validate parsed JSON and return its notes and links; raises ``ValueError``."""
    if not isinstance(data, dict) or set(data) - {"notes", "links"}:
        raise ValueError(f"{source}: expected an object with 'notes' and 'links' lists")
    entries = {key: data.get(key, []) for key in ("notes", "links")}
    if not all(isinstance(value, list) for value in entries.values()):
        raise ValueError(f"{source}: 'notes' and 'links' must be lists")

    notes = []
    for index, entry in enumerate(entries["notes"]):
        where = f"{source} notes[{index}]"
        if not isinstance(entry, dict) or set(entry) - _NOTE_FIELDS:
            raise ValueError(f"{where}: expected an object with fields {sorted(_NOTE_FIELDS)}")
        corpus, citation = _text(entry, "corpus", where), _text(entry, "citation", where)
        where = f"{where} ({citation})"
        kind = _text(entry, "kind", where)
        if kind not in NOTE_KINDS:
            raise ValueError(f"{where}: kind {kind!r} is not one of {', '.join(NOTE_KINDS)}")
        related = {}
        for field in ("contrast", "aligned"):
            references = entry.get(field, [])
            if not isinstance(references, list):
                raise ValueError(f"{where}: '{field}' must be a list of biblical references")
            related[field] = tuple(
                format_biblical_range(*_biblical(reference, where)) for reference in references
            )
        _check_citation(corpus, citation, where)
        notes.append(EditorialNote(corpus, citation, kind, _text(entry, "text", where), **related))

    links = []
    for index, entry in enumerate(entries["links"]):
        where = f"{source} links[{index}]"
        if not isinstance(entry, dict) or set(entry) - _LINK_FIELDS:
            raise ValueError(f"{where}: expected an object with fields {sorted(_LINK_FIELDS)}")
        corpus, citation = _text(entry, "corpus", where), _text(entry, "citation", where)
        where = f"{where} ({citation})"
        relation = _text(entry, "relation", where)
        if relation not in CURATED_LINK_RELATIONS:
            raise ValueError(
                f"{where}: relation {relation!r} is not one of {', '.join(CURATED_LINK_RELATIONS)}"
            )
        biblical = _biblical(entry.get("biblical"), where)
        _check_citation(corpus, citation, where)
        links.append(EditorialLink(
            corpus, citation, relation, *biblical, _text(entry, "note", where, required=False),
        ))
    return EditorialNotes(tuple(notes), tuple(links))


def load_editorial_notes(path: Path | None = None) -> EditorialNotes:
    """Load and validate the committed notes file (``NOTES_PATH`` by default)."""
    path = path or NOTES_PATH
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    return parse_editorial_notes(data, source=path.name)
