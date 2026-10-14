"""Brief English glosses for lexicon entries, from STEPBible's "Gloss" column.

The full lexicons the database is built from make poor brief definitions:

- BDB (Hebrew) has no gloss field, so the importer took the first bold phrase
  of each entry, which is often a grammar label ("noun masculine plural" for
  elohim, "verb Pi`el" for kaphar, "proper name, masculine" for 1,227 names),
  a homonym the tagged text hardly uses ("mouth" for midbar, which means
  "wilderness" 269 times), or a stray phrase.
- TFLSJ (Greek) has one row per *sense* of a Strong's number (G2570G "good",
  G2570H "Fair (Havens)"), and the importer kept whichever row came last.

STEPBible's brief lexicons (TBESH, TBESG; TFLSJ repeats TBESG's gloss column)
give every disambiguated Strong's number (dStrong: H4057B, G0863H) a short
gloss written by Tyndale House scholars. ``brief_definition`` combines the
rows of one Strong's number into a single line:

- proper-name rows (``N:`` morphology, "a Part of" compounds, "Wilderness (of
  Sinai)") are dropped when the number also has ordinary-word rows;
- glosses are ordered by how often their dStrong occurs in the tagged text,
  so the common sense leads ("wilderness; mouth", not "mouth; wilderness");
- sub-meanings ("to release: forgive") are folded under their head gloss:
  "to release: leave, forgive, permit".

``update_brief_definitions`` applies this to the lexicon table, and sets each
Hebrew entry's pronunciation to STEPBible's syllabified transliteration
("che.sed"), which search_lexicon also matches. build_database.py runs it
after the verses are imported; scripts/repair_lexicon_and_morphology.py
brings an existing database into line.
"""

from __future__ import annotations

import dataclasses
import json
import re
import sqlite3
from collections import Counter
from collections.abc import Iterable, Iterator
from pathlib import Path

# Gloss sources per language, in order of preference. TBESG and TFLSJ carry
# the same rows and gloss column, so either is enough for Greek.
GLOSS_FILES = {
    "hebrew": ("TBESH.txt",),
    "greek": ("TBESG.txt", "TFLSJ_0-5624.txt", "TFLSJ_extra.txt"),
}

MAX_HEADS = 3  # distinct head glosses (homonyms) per entry
MAX_SUBMEANINGS = 3  # sub-meanings shown under each head gloss

_ESTRONG = re.compile(r"^([GH])(\d{1,5})([a-z]?)$")
_DSTRONG = re.compile(r"^([GH])(\d{1,5})([A-Z]?)$")
# Glosses that name part of a longer proper name: "(Huram)-abi", "Fair
# (Havens)", "El (Most High)", "Beth-(ashbea)", "Lebo-(Hamath)".
_NAME_GLOSS = re.compile(r"\([A-Z]|[A-Z][\w'’]*\s*\(|\)-|-\(")
_NAME_RELATIONS = ("a Part of", "combination of")
_LEADING_FILLER = re.compile(r"^(?:to|an?|be|the)\s+", re.IGNORECASE)


# Words of the grammar labels BDB puts where a gloss would be: "noun
# masculine plural", "verb Pi`el", "proper name, of a location 1.".
_GRAMMAR_WORDS = frozenset("""
    a an and or of the noun verb verbal adjective adverb preposition conjunction
    particle pronoun interjection substantive proper name names masculine
    feminine common plural singular dual collective abstract denominative
    indeclinable demonstrative interrogative relative personal suffix
    construct absolute participle infinitive perfect imperfect imperative
    location people territory river mountain divinity deity city region place
    person gentilic
""".split())


def is_grammar_label(text: str | None) -> bool:
    """Whether a brief definition is only a grammar label ("noun [masculine]", "Qal")."""
    words = re.sub(r"[\[\](),.;:\d]", " ", (text or "").lower()).split()
    return bool(words) and all(
        word in _GRAMMAR_WORDS or "`" in word or word in ("qal", "piel", "hiphil", "niphal")
        for word in words
    )


def pad_strongs(strongs: str) -> str:
    """'H430G' -> 'H0430G'; anything else unchanged."""
    match = _DSTRONG.match(strongs)
    if not match:
        return strongs
    prefix, number, suffix = match.groups()
    return f"{prefix}{int(number):04d}{suffix}"


@dataclasses.dataclass(frozen=True)
class GlossRow:
    """One row of a STEPBible brief lexicon."""

    strongs: str  # lexicon key: H4057, G2570
    dstrong: str  # disambiguated number: H4057B, G2570G, H7676
    relation: str  # "", "a Meaning of", "a Name of", "a Part of", ...
    transliteration: str  # STEPBible's form: "che.sed", "agapē"
    morph: str  # "H:N-M", "N:N--L", "G:V"
    gloss: str  # "wilderness", "to release: forgive"
    position: int  # row order in the source

    @property
    def is_compound_name(self) -> bool:
        """Part of a longer name, or an unnamed relative ("[wife of Peter]")."""
        return (
            self.relation in _NAME_RELATIONS
            or self.gloss.startswith("[")
            or bool(_NAME_GLOSS.search(self.gloss))
        )

    @property
    def is_name(self) -> bool:
        return self.morph.startswith("N:") or self.is_compound_name

    @property
    def head(self) -> str:
        """The gloss before any sub-meaning: "to release: forgive" -> "to release"."""
        head, _, sub = self.gloss.partition(":")
        return head.strip() or sub.strip()

    @property
    def submeaning(self) -> str:
        head, colon, sub = self.gloss.partition(":")
        return sub.strip() if colon and head.strip() else ""


def gloss_row(parts: list[str], position: int) -> GlossRow | None:
    """A GlossRow from the tab-separated columns of a TBESH/TBESG/TFLSJ line.

    Columns: eStrong, "dStrong = relation", uStrong, word, transliteration,
    morph, gloss, definition.
    """
    if len(parts) < 7:
        return None
    match = _ESTRONG.match(parts[0].strip())
    gloss = " ".join(parts[6].split())
    if not match or not gloss:
        return None
    prefix, number, _ = match.groups()
    strongs = f"{prefix}{int(number):04d}"
    dstrong, _, relation = parts[1].partition("=")
    dstrong = pad_strongs(dstrong.strip().upper())
    if not _DSTRONG.match(dstrong):
        dstrong = strongs
    return GlossRow(
        strongs=strongs,
        dstrong=dstrong,
        relation=" ".join(relation.split()),
        transliteration=parts[4].strip(),
        morph=parts[5].strip(),
        gloss=gloss,
        position=position,
    )


def read_gloss_rows(path: Path, offset: int = 0) -> Iterator[GlossRow]:
    """Yield the lexical rows of a TBESH, TBESG or TFLSJ file."""
    with open(path, encoding="utf-8-sig") as handle:
        for position, line in enumerate(handle, offset):
            row = gloss_row(line.rstrip("\n").split("\t"), position)
            if row:
                yield row


def group_gloss_rows(paths: Iterable[Path]) -> dict[str, list[GlossRow]]:
    """Rows per Strong's number, from the first of ``paths`` that exists.

    The Greek files repeat one another, so only one source is read; TFLSJ
    splits its rows over two files, which are read together.
    """
    existing = [path for path in paths if path.exists()]
    if not existing:
        return {}
    chosen = [existing[0]]
    if existing[0].name.startswith("TFLSJ"):
        chosen = [path for path in existing if path.name.startswith("TFLSJ")]
    grouped: dict[str, list[GlossRow]] = {}
    offset = 0
    for path in chosen:
        for row in read_gloss_rows(path, offset):
            grouped.setdefault(row.strongs, []).append(row)
            offset = row.position + 1
    return grouped


def _same(a: str, b: str) -> bool:
    return _LEADING_FILLER.sub("", a).casefold() == _LEADING_FILLER.sub("", b).casefold()


def _ranked(rows: list[GlossRow], counts: Counter) -> list[GlossRow]:
    """The rows worth showing, most-used dStrong first (file order breaks ties)."""
    chosen = (
        [row for row in rows if not row.is_name]
        or [row for row in rows if not row.is_compound_name]
        or rows
    )
    return sorted(chosen, key=lambda row: (-counts.get(row.dstrong, 0), row.position))


def brief_definition(rows: list[GlossRow], counts: Counter | None = None) -> str:
    """One line of glosses for the rows of one Strong's number.

    ``counts`` maps dStrong numbers to their occurrences in the tagged text;
    without it the file order decides.
    """
    counts = counts or Counter()
    heads: dict[str, dict] = {}
    for row in _ranked(rows, counts):
        head = heads.setdefault(
            row.head.casefold(),
            {"text": row.head, "weight": 0, "first": row.position, "subs": {}},
        )
        weight = counts.get(row.dstrong, 0)
        head["weight"] += weight
        sub = row.submeaning
        if sub and not _same(sub, row.head):
            previous = head["subs"].get(sub, (0, row.position))
            head["subs"][sub] = (previous[0] + weight, previous[1])
    ordered = sorted(heads.values(), key=lambda head: (-head["weight"], head["first"]))
    # A capitalised head after an ordinary one is a name use of the word
    # ("to come (in)" ... "Lebo"; "field" ... "Field of"), not another sense.
    kept, seen_common = [], False
    for head in ordered:
        capitalised = head["text"][:1].isupper()
        if capitalised and seen_common:
            continue
        seen_common = seen_common or not capitalised
        kept.append(head)
    parts = []
    for head in kept[:MAX_HEADS]:
        subs = sorted(head["subs"], key=lambda sub: (-head["subs"][sub][0], head["subs"][sub][1]))
        shown = subs[:MAX_SUBMEANINGS]
        parts.append(f"{head['text']}: {', '.join(shown)}" if shown else head["text"])
    return "; ".join(parts)


def brief_pronunciation(rows: list[GlossRow], counts: Counter | None = None) -> str:
    """STEPBible's transliteration of the most-used row ("che.sed")."""
    ranked = _ranked(rows, counts or Counter())
    return ranked[0].transliteration if ranked else ""


def count_dstrong_usage(conn: sqlite3.Connection) -> Counter:
    """Occurrences of each disambiguated Strong's number (H4057B) in the tagged text."""
    counts: Counter = Counter()
    for (word_data,) in conn.execute(
        "SELECT word_data FROM verses WHERE word_data IS NOT NULL AND word_data != ''"
    ):
        try:
            words = json.loads(word_data)
        except ValueError:
            continue
        for word in words:
            if isinstance(word, dict) and word.get("strongs"):
                counts[pad_strongs(str(word["strongs"]).strip().upper())] += 1
    return counts


def compute_brief_definitions(
    conn: sqlite3.Connection, data_dir: Path
) -> dict[str, dict[str, str]]:
    """Lexicon values from STEPBible's glosses: {strongs: {column: value}}.

    Covers every Strong's number with gloss rows: ``short_definition``, and
    for Hebrew also ``pronunciation``.
    """
    counts = count_dstrong_usage(conn)
    wanted: dict[str, dict[str, str]] = {}
    for language, names in GLOSS_FILES.items():
        for strongs, rows in group_gloss_rows(data_dir / name for name in names).items():
            values = {"short_definition": brief_definition(rows, counts)}
            if language == "hebrew":
                values["pronunciation"] = brief_pronunciation(rows, counts)
            wanted[strongs] = values
    return wanted


def brief_definition_changes(
    conn: sqlite3.Connection, data_dir: Path
) -> dict[str, dict[str, list[str | None]]]:
    """{strongs: {column: [current, wanted]}} for lexicon rows that differ."""
    wanted = compute_brief_definitions(conn, data_dir)
    changes: dict[str, dict[str, list[str | None]]] = {}
    for strongs, short_definition, pronunciation in conn.execute(
        "SELECT strongs, short_definition, pronunciation FROM lexicon"
    ):
        values = wanted.get(strongs)
        if not values:
            continue
        current = {"short_definition": short_definition, "pronunciation": pronunciation}
        diff = {
            column: [current[column], value]
            for column, value in values.items()
            if current[column] != value
        }
        if diff:
            changes[strongs] = diff
    return changes


def update_brief_definitions(conn: sqlite3.Connection, data_dir: Path) -> int:
    """Set lexicon brief definitions from STEPBible glosses; return rows changed."""
    changes = brief_definition_changes(conn, data_dir)
    for strongs, diff in changes.items():
        assignments = ", ".join(f"{column} = ?" for column in diff)
        conn.execute(
            f"UPDATE lexicon SET {assignments} WHERE strongs = ?",
            (*(new for _, new in diff.values()), strongs),
        )
    conn.commit()
    return len(changes)
