"""Targum corpus: Targum Onkelos on the Torah, one passage per Masoretic verse.

Aramaic: the Torat Emet text of Onkelos as exported by Sefaria. English: the
Metsudah Chumash (2009, CC BY-NC), which renders the Hebrew text with Onkelos's
departures in brackets and is labelled as such on every passage. All files come
from Sefaria's archived export repository at one commit, verified by Git blob
hash.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote

from .base import BiblicalLink, Collection, Corpus, SourceTag, Work, combined_license
from .download import fetch_verified, git_blob_sha1
from .locators import CHAPTER_VERSE

if TYPE_CHECKING:
    import httpx


SEFARIA_REPOSITORY = "Sefaria/Sefaria-Export-Archive"
SEFARIA_COMMIT = "3f1013631fdfe452e953a93a2c5f921319e394ed"
_SOURCE_ROOT = "json/Tanakh/Targum"
_RAW_BASE = f"https://raw.githubusercontent.com/{SEFARIA_REPOSITORY}/{SEFARIA_COMMIT}"
_TREE_BASE = f"https://github.com/{SEFARIA_REPOSITORY}/tree/{SEFARIA_COMMIT}"
_BLOB_BASE = f"https://github.com/{SEFARIA_REPOSITORY}/blob/{SEFARIA_COMMIT}"

ORIGINAL_LANGUAGE = "Aramaic"
PUBLIC_DOMAIN = "Public domain"
CC_BY_NC = "CC BY-NC 4.0"

ONKELOS = Collection(
    "Targum Onkelos", ("Onkelos", "Onqelos", "Targum Onqelos", "Tg. Onq.", "Tg. Onk.", "Onk."),
)
AUTHOR = "Targum Onkelos"
# Redaction-era tag (editorial): Onkelos took its final form in the amoraic period.
PERIOD_TAGS = "amoraic"
TAG = SourceTag(
    kind="Jewish Aramaic Torah rendering", date="final form c. 3rd–5th c. AD, Babylonia",
    tier="B", edition="Torat Emet Aramaic; Metsudah English of the Hebrew",
)
CAVEAT = (
    "Not Scripture: a Jewish Aramaic rendering of the Torah (final form c. 3rd–5th c. AD) "
    "that avoids describing God bodily."
)
PERIODS = (PERIOD_TAGS,)
_SEFARIA_DIRECTORY = "Onkelos/Torah/Onkelos {book}"  # One book's versions.
_ARAMAIC_VERSION = "Onkelos {book}"  # Sefaria versionTitle and file name.

# Torah book: (citation abbreviation, database book code, aliases).
BOOKS = {
    "Genesis": ("Gen", "Gen", ("Gen.", "Gn.", "Bereshit", "Bereshith", "Bereishit")),
    "Exodus": ("Exod", "Exo", ("Exod.", "Exo.", "Ex.", "Shemot", "Shemoth")),
    "Leviticus": ("Lev", "Lev", ("Lev.", "Lv.", "Vayikra", "Vaiyikra")),
    "Numbers": ("Num", "Num", ("Num.", "Nm.", "Bamidbar", "Bemidbar")),
    "Deuteronomy": ("Deut", "Deu", ("Deut.", "Dt.", "Devarim", "Debarim")),
}

METSUDAH = (
    "Metsudah Chumash, Metsudah Publications, 2009 [with Onkelos translation] — "
    "English of the Hebrew text with Onkelos's renderings in [brackets]; not a "
    "direct translation of the Aramaic"
)


def _work(book: str) -> Work:
    return Work(
        key=f"onkelos_{book.lower()}",
        title=book,
        reference_title=book,
        locator=CHAPTER_VERSE,
        aliases=BOOKS[book][2],
        collection=ONKELOS,
    )


WORKS = {book: _work(book) for book in BOOKS}


@dataclass(frozen=True)
class SourceFile:
    """One pinned Sefaria version file and the licence and title it must declare."""

    filename: str
    path: str  # Repository path under json/Tanakh/Targum.
    git_blob_sha1: str
    license: str  # Sefaria's exact 'license' value.
    version_title: str
    language: str  # 'he' (Aramaic) or 'en'.

    @property
    def raw_url(self) -> str:
        return f"{_RAW_BASE}/{quote(f'{_SOURCE_ROOT}/{self.path}')}"

    @property
    def source_url(self) -> str:
        return f"{_BLOB_BASE}/{quote(f'{_SOURCE_ROOT}/{self.path}')}"


_METSUDAH_VERSION = "Metsudah Chumash, Metsudah Publications, 2009 [with Onkelos translation]"

# Git blob SHA-1s at SEFARIA_COMMIT, checked against the GitHub contents API.
_BLOBS = {
    ("Genesis", "aramaic"): "7f4483b9df5aeb1c107a5cc6c1dd9a5d3c350e19",
    ("Exodus", "aramaic"): "2307cb16124f62cd1cd97d24d967d411b760fd35",
    ("Leviticus", "aramaic"): "721423bc857c0416513cd0e21f6b9f8b916b9914",
    ("Numbers", "aramaic"): "d3f56eca6015be24478fc35bf7cb6c5f951de763",
    ("Deuteronomy", "aramaic"): "13e81dc5535fa343b07f591ad7aeae5ed11edcd0",
    ("Genesis", "metsudah"): "2ac288a342b028ebf6e23c28cf136d735c8ce132",
    ("Exodus", "metsudah"): "031df525a8e69b998a02982f79e38e08f495e166",
    ("Leviticus", "metsudah"): "63a385dae702fd1c7bb6c854ead61df360877b48",
    ("Numbers", "metsudah"): "44328083d9f5cc91cb5f4b21305e7ff312849f15",
    ("Deuteronomy", "metsudah"): "76d8d6c9f6f98070a8e08c13e45791dde2d9fc02",
}


def _source(book: str, kind: str) -> SourceFile:
    directory = _SEFARIA_DIRECTORY.format(book=book)
    filename = f"onkelos_{book.lower()}.{kind}.json"
    blob = _BLOBS[(book, kind)]
    if kind == "aramaic":
        version = _ARAMAIC_VERSION.format(book=book)
        return SourceFile(filename, f"{directory}/Hebrew/{version}.json", blob, "Public Domain", version, "he")
    return SourceFile(
        filename, f"{directory}/English/{_METSUDAH_VERSION}.json", blob, "CC-BY-NC",
        _METSUDAH_VERSION, "en",
    )


SOURCE_FILES = tuple(_source(book, kind) for book in BOOKS for kind in ("aramaic", "metsudah"))

# Digitization artefacts in the pinned Aramaic: (book, chapter, verse) ->
# (text that must be present, replacement). Sefaria's later export drops the
# "??? " before Onkelos Genesis 49:12.
_ARAMAIC_TEXT_CORRECTIONS = {
    ("Genesis", 49, 12): ("??? ", ""),
}

_WHITESPACE = re.compile(r"\s+")
_EMPHASIS_TAG = re.compile(r"</?(?:b|i)>")


def _normalize(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


def clean_metsudah(text: str) -> str:
    """Metsudah English without its bold/italic tags; bracketed Onkelos renderings stay."""
    text = _normalize(html.unescape(_EMPHASIS_TAG.sub("", text)))
    if re.search(r"[<>{}]", text):
        raise ValueError(f"Unexpected markup left in Metsudah text: {text[:80]!r}")
    return text


def _load(directory: Path, source: SourceFile) -> list[list[str]]:
    path = directory / source.filename
    data = json.loads(path.read_text(encoding="utf-8"))
    _check_declaration(source, data)
    chapters = data.get("text")
    if not isinstance(chapters, list) or not all(
        isinstance(chapter, list) and all(isinstance(verse, str) for verse in chapter)
        for chapter in chapters
    ):
        raise ValueError(f"{source.filename}: expected a chapter list of verse strings")
    return chapters


def _check_declaration(source: SourceFile, data: dict) -> None:
    if data.get("license") != source.license:
        raise ValueError(
            f"{source.filename}: expected Sefaria license {source.license!r}, "
            f"found {data.get('license')!r}"
        )
    if data.get("versionTitle") != source.version_title or data.get("language") != source.language:
        raise ValueError(f"{source.filename}: unexpected version {data.get('versionTitle')!r}")


def _aramaic_verses(book: str, chapters: list[list[str]]) -> dict[tuple[int, int], str]:
    """Non-empty Aramaic text keyed by (chapter, verse)."""
    verses: dict[tuple[int, int], str] = {}
    for chapter_number, chapter in enumerate(chapters, 1):
        for verse_number, raw in enumerate(chapter, 1):
            text = raw
            fix = _ARAMAIC_TEXT_CORRECTIONS.get((book, chapter_number, verse_number))
            if fix is not None:
                if fix[0] not in text:
                    raise ValueError(f"onkelos {book} {chapter_number}:{verse_number}: expected {fix[0]!r}")
                text = text.replace(fix[0], fix[1])
            text = _normalize(text)
            if not text:
                continue
            if "??" in text:
                raise ValueError(f"onkelos {book} {chapter_number}:{verse_number}: '??' in Aramaic")
            verses[(chapter_number, verse_number)] = text
    return verses


def _english_verses(book: str, directory: Path) -> dict[tuple[int, int], str]:
    """Non-empty Metsudah English keyed by (chapter, verse)."""
    return {
        (chapter_number, verse_number): text
        for chapter_number, chapter in enumerate(_load(directory, _source(book, "metsudah")), 1)
        for verse_number, raw in enumerate(chapter, 1)
        if (text := clean_metsudah(raw))
    }


def parse_targum_book(directory: Path, book: str) -> list[dict]:
    """One passage per verse with Aramaic or English; a verse with only one is single-language."""
    work = WORKS[book]
    aramaic_source = _source(book, "aramaic")
    aramaic = _aramaic_verses(book, _load(directory, aramaic_source))
    english = _english_verses(book, directory)
    rows: list[dict] = []
    for chapter, verse in sorted(aramaic.keys() | english.keys()):
        row = {
            "author": AUTHOR,
            "work_key": work.key,
            "reference": f"{work.display_title} {chapter}:{verse}",
            "sort_start": work.locator.key(chapter, verse),
            "sort_end": work.locator.key(chapter, verse),
            "edition": (
                f"Torat Emet Aramaic text (toratemetfreeware.com), Sefaria version "
                f"'{aramaic_source.version_title}'"
            ),
            "period_tags": PERIOD_TAGS,
            "source_url": f"{_TREE_BASE}/{quote(f'{_SOURCE_ROOT}/{_SEFARIA_DIRECTORY.format(book=book)}')}",
        }
        original_license = translation_license = None
        if (chapter, verse) in aramaic:
            original_license = PUBLIC_DOMAIN
            row["original_text"] = aramaic[(chapter, verse)]
            row["original_language"] = ORIGINAL_LANGUAGE
            row["original_license"] = original_license
        if (chapter, verse) in english:
            translation_license = CC_BY_NC
            row["text"] = english[(chapter, verse)]
            row["translation"] = METSUDAH
            row["translation_license"] = translation_license
        row["license"] = combined_license(original_license, translation_license, ORIGINAL_LANGUAGE)
        rows.append(row)
    return rows


def parse(directory: Path) -> list[dict]:
    return [row for book in BOOKS for row in parse_targum_book(directory, book)]


_BOOK_BY_WORK = {work.key: book for book, work in WORKS.items()}


def biblical_links(passages: list[dict]) -> list[BiblicalLink]:
    """One link per passage to the Torah verse it translates, from its sort key."""
    links = []
    for passage in passages:
        book = _BOOK_BY_WORK[passage["work_key"]]
        _, book_code, _ = BOOKS[book]
        chapter, verse = divmod(passage["sort_start"], 1000)
        links.append(BiblicalLink(
            work_key=passage["work_key"],
            locator=f"{chapter}:{verse}",
            book=book_code,
            chapter=chapter,
            verse=verse,
            end_chapter=chapter,
            end_verse=verse,
            note="",
            relation="translation",
        ))
    return links


def require_targum_files(directory: Path) -> None:
    """Raise unless every pinned Aramaic and English version file is present."""
    missing = [source.filename for source in SOURCE_FILES if not (directory / source.filename).is_file()]
    if missing:
        raise FileNotFoundError(
            f"Targum sources in {directory} are incomplete; missing {', '.join(missing)}. "
            "Run python scripts/download_ancient_sources.py."
        )


def download(client: httpx.Client, target: Path, force: bool) -> dict:
    """Fetch each pinned Sefaria version file, verify its blob hash and declared licence."""
    files: dict[str, dict] = {}
    for source in SOURCE_FILES:
        content = fetch_verified(
            client, source.raw_url, target / source.filename, source.git_blob_sha1, force, git_blob_sha1
        )
        try:
            _check_declaration(source, json.loads(content))
        except ValueError as error:
            raise RuntimeError(str(error)) from error
        files[source.filename] = {
            "git_blob_sha1": source.git_blob_sha1,
            "bytes": len(content),
            "source_url": source.source_url,
            "version_title": source.version_title,
            "license": source.license,
        }
    return {
        "repository": SEFARIA_REPOSITORY,
        "commit": SEFARIA_COMMIT,
        "license": (
            "Aramaic (Torat Emet): Public domain; Metsudah English: CC BY-NC 4.0 "
            "(as declared per version by Sefaria)"
        ),
        "files": files,
    }


CORPUS = Corpus(
    key="targum",
    label="Targum",
    summary=(
        "Targum Onkelos on the five books of the Torah (Torat Emet Aramaic via "
        "Sefaria), one passage per Masoretic verse, cited by book and chapter:verse "
        "('Onkelos Genesis 1:2', 'Tg. Onq. Deut 32:8'), each linked to the verse it "
        "translates. English: the Metsudah Chumash (2009, CC BY-NC), an English of "
        "the Hebrew text with Onkelos's renderings in brackets."
    ),
    data_dir="targum",
    original_language=ORIGINAL_LANGUAGE,
    works=tuple(WORKS.values()),
    periods=PERIODS,
    download=download,
    require_files=require_targum_files,
    parse=parse,
    biblical_links=biblical_links,
    example_query="canopy",
    example_citation="Onkelos Genesis 1:2",
    aliases=("Targum", "Targums", "Tg."),
    tag=TAG,
    caveat=CAVEAT,
)
