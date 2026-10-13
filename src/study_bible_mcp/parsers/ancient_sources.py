"""Import registered ancient-source corpora into searchable, citable passages."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from ..corpora import CORPORA, Corpus, combined_license
from ..database import BOOK_ABBREV_MAP, ancient_search_index_text

_BOOK_CODES = frozenset(BOOK_ABBREV_MAP.values())

# Every column written per passage; keys absent from a passage dict are NULL
# except the legacy Josephus columns, which default as below.
_COLUMNS = (
    "corpus", "author", "work_key", "work_title", "collection", "reference",
    "alternate_reference", "book_number", "section_number", "section_end",
    "sort_start", "sort_end", "editorial_heading", "text", "original_text",
    "original_language", "period_tags", "edition", "translation", "license",
    "original_license", "translation_license", "source_url",
)
_LEGACY_DEFAULTS = {"book_number": 0, "section_number": "", "section_end": 0}
_REQUIRED_TEXT = (
    "author", "reference", "period_tags", "edition", "license", "source_url",
)
# English is optional only when no openly licensed translation exists; such a
# passage carries its original-language text instead (e.g. 1QpHab).
_ENGLISH_FIELDS = ("text", "translation", "translation_license")


def _passage(corpus: Corpus, raw: dict[str, Any]) -> dict[str, Any]:
    """Validate one parsed passage and fill registry-derived fields."""
    row = {**_LEGACY_DEFAULTS, **raw}
    label = f"{corpus.key} {row.get('reference', '<no reference>')}"
    unknown = set(row) - set(_COLUMNS)
    if unknown:
        raise ValueError(f"{label}: unknown passage fields {sorted(unknown)}")
    try:
        work = corpus.work(row.get("work_key", ""))
    except KeyError as error:
        raise ValueError(f"{label}: {error.args[0]}") from None
    derived = {
        "corpus": corpus.key,
        "work_title": work.title,
        "collection": work.collection.title if work.collection else None,
    }
    for field, value in derived.items():
        if row.setdefault(field, value) != value:
            raise ValueError(f"{label}: {field} {row[field]!r} != registry value {value!r}")
    missing = [field for field in _REQUIRED_TEXT if not row.get(field)]
    has_english = [field for field in _ENGLISH_FIELDS if row.get(field)]
    if has_english and len(has_english) != len(_ENGLISH_FIELDS):
        missing += [field for field in _ENGLISH_FIELDS if not row.get(field)]
    if not has_english and not row.get("original_text"):
        missing += [*_ENGLISH_FIELDS, "or original_text"]
    if missing:
        raise ValueError(f"{label}: missing {', '.join(missing)}")
    row["text"] = row.get("text") or ""
    start, end = row.get("sort_start"), row.get("sort_end")
    if not isinstance(start, int) or not isinstance(end, int) or start > end:
        raise ValueError(f"{label}: sort_start/sort_end must be integers with start <= end")
    if row.get("original_text"):
        row.setdefault("original_language", corpus.original_language)
        if not row.get("original_license"):
            raise ValueError(f"{label}: original_text needs original_license")
    expected_license = combined_license(
        row.get("original_license"), row.get("translation_license"), row.get("original_language")
    )
    if row["license"] != expected_license:
        raise ValueError(f"{label}: license {row['license']!r} != {expected_license!r}")
    unknown_periods = set(row["period_tags"].split(",")) - set(corpus.periods)
    if unknown_periods:
        raise ValueError(f"{label}: period tags {sorted(unknown_periods)} not in {corpus.key}.periods")
    return row


def _link_rows(corpus: Corpus, rows: list[dict[str, Any]]) -> list[tuple[int, str, int, int, str]]:
    """Resolve each curated link to the index of the passage containing its locator."""
    by_work: dict[str, list[tuple[int, int, int]]] = {}
    for index, row in enumerate(rows):
        by_work.setdefault(row["work_key"], []).append((row["sort_start"], row["sort_end"], index))
    resolved = []
    for link in corpus.biblical_links(rows):
        target = f"{link.work_key} {link.locator} -> {link.book} {link.chapter}:{link.verse}"
        if link.book not in _BOOK_CODES:
            raise ValueError(f"Curated biblical link {target}: unknown book code {link.book!r}")
        start, end = link.chapter * 1000 + link.verse, link.end_chapter * 1000 + link.end_verse
        if not (1 <= link.verse <= 999 and 1 <= link.end_verse <= 999 and start <= end):
            raise ValueError(f"Curated biblical link {target}: invalid verse range")
        sort_range = corpus.work(link.work_key).locator.parse(link.locator)
        index = None
        if sort_range is not None:
            key = sort_range[0]
            index = next(
                (i for first, last, i in by_work.get(link.work_key, []) if first <= key <= last),
                None,
            )
        if index is None:
            raise ValueError(
                f"Curated biblical link {target} does not resolve to an imported passage"
            )
        resolved.append((index, link.book, start, end, link.note))
    return resolved


def import_corpus(conn: sqlite3.Connection, key: str, directory: Path) -> int:
    """Replace one registered corpus's passages, FTS rows, and biblical links.

    The files are checked and every passage and link validated before any row
    is touched; the replacement then runs in a savepoint, so a failure leaves
    the previously imported corpus intact. Returns the passage count.
    """
    corpus = CORPORA[key]
    corpus.require_files(directory)
    rows = [_passage(corpus, dict(raw)) for raw in corpus.parse(directory)]
    if not rows:
        raise ValueError(f"{key}: the parser produced no passages from {directory}")
    links = _link_rows(corpus, rows)

    conn.execute("SAVEPOINT import_corpus")
    try:
        conn.execute(
            """DELETE FROM ancient_source_biblical_links WHERE passage_id IN
               (SELECT id FROM ancient_source_passages WHERE corpus = ?)""",
            (key,),
        )
        conn.execute(
            """DELETE FROM ancient_source_passages_fts WHERE passage_id IN
               (SELECT id FROM ancient_source_passages WHERE corpus = ?)""",
            (key,),
        )
        conn.execute("DELETE FROM ancient_source_passages WHERE corpus = ?", (key,))
        insert = (
            f"INSERT INTO ancient_source_passages ({', '.join(_COLUMNS)}) "
            f"VALUES ({', '.join(':' + column for column in _COLUMNS)})"
        )
        ids = [
            conn.execute(insert, {column: row.get(column) for column in _COLUMNS}).lastrowid
            for row in rows
        ]
        conn.executemany(
            """INSERT INTO ancient_source_passages_fts
               (passage_id, work_title, reference, text, original_text_folded)
               VALUES (?, ?, ?, ?, ?)""",
            (
                (
                    passage_id, row["work_title"], row["reference"], row["text"],
                    ancient_search_index_text(
                        row.get("original_text") or "", corpus.search_index_removals
                    ),
                )
                for passage_id, row in zip(ids, rows)
            ),
        )
        conn.executemany(
            """INSERT INTO ancient_source_biblical_links
               (passage_id, biblical_book, sort_start, sort_end, relationship_note)
               VALUES (?, ?, ?, ?, ?)""",
            ((ids[index], *link) for index, *link in links),
        )
        # Merge FTS segments so a re-import does not leave deleted entries behind.
        conn.execute(
            "INSERT INTO ancient_source_passages_fts(ancient_source_passages_fts) VALUES ('optimize')"
        )
    except BaseException:
        conn.execute("ROLLBACK TO import_corpus")
        conn.execute("RELEASE import_corpus")
        raise
    conn.execute("RELEASE import_corpus")
    conn.commit()
    return len(rows)


def import_josephus(conn: sqlite3.Connection, directory: Path) -> int:
    """Replace the Josephus corpus and rebuild its FTS and biblical links."""
    return import_corpus(conn, "josephus", directory)


def import_available_corpora(conn: sqlite3.Connection, root: Path) -> dict[str, int | None]:
    """Import every registered corpus whose directory exists under ``root``.

    Returns passage counts per corpus key, None for a corpus not downloaded. A
    present but incomplete corpus raises from its ``require_files`` check.
    """
    return {
        key: import_corpus(conn, key, root / corpus.data_dir)
        if (root / corpus.data_dir).exists()
        else None
        for key, corpus in CORPORA.items()
    }
