"""Targum corpus: Targum Onkelos on the Torah, one passage per verse.

Aramaic: the Torat Emet text of Onkelos as exported by Sefaria. English: the
Metsudah Chumash (2009, CC BY-NC), an English of the Hebrew Torah, not of the
Aramaic: the words Metsudah marks as Onkelos's own renderings (bold or, in
Genesis 12–17, italic brackets) are printed ⟨…⟩, and plain [ ] are Metsudah's
supplements. All files come from Sefaria's archived export repository at one
commit, verified by Git blob hash.

Versification: Sefaria numbers Onkelos by the Hebrew (MT) verses. Passages,
citations and links use the server's English (BSB/KJV) numbering, and the
heading names the Hebrew number where it differs: 'Targum Onkelos Exodus 8:5
(MT 8:1)'. So 'Onkelos Genesis 32:30' is the Peniel verse (MT 32:31).
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
    tier="B",
    edition=(
        "Torat Emet Aramaic; Metsudah: English of the Hebrew Torah; "
        "⟨marked⟩ words are Onkelos's renderings"
    ),
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
    "English of the Hebrew Torah, not a direct translation of the Aramaic; ⟨marked⟩ "
    "words are Onkelos's renderings, [ ] Metsudah's own supplements"
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
# Metsudah marks Onkelos's renderings as bold (in Genesis 12–17, italic)
# bracket groups, '[<b>Glory of the</b>]'; plain brackets are its own English
# supplements, '[a vision of]', and other italics are transliterated terms
# ('<i>kohein</i>', and '[<i>shekolim</i>]' in Numbers 7).
_ONKELOS_BOLD = re.compile(r"\[<b>(.*?)</b>\]")
_ONKELOS_ITALIC = re.compile(r"\[<i>(.*?)</i>\]")
_BOLD = re.compile(r"<b>(.*?)</b>")
_ITALIC_TAG = re.compile(r"</?i>")
# 'Chazak' closes Genesis, Leviticus and Numbers: a liturgical exclamation in
# bold, neither Torah nor Onkelos.
_CHAZAK = re.compile(r"\s*<b>Chazak</b>\s*$")
_ITALIC_ONKELOS_CHAPTERS = {("Genesis", chapter) for chapter in range(12, 18)}
ONKELOS_OPEN, ONKELOS_CLOSE = "⟨", "⟩"


def _normalize(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


def _mark(match: re.Match) -> str:
    return f"{ONKELOS_OPEN}{match.group(1).strip()}{ONKELOS_CLOSE}"


def clean_metsudah(text: str, italic_marks_onkelos: bool = False) -> str:
    """Metsudah English with Onkelos's renderings marked ⟨…⟩ and other emphasis dropped.

    A bold group ('[<b>…</b>]', or bold text partly inside brackets such as
    '[lit. <b>…</b>]') is Onkelos's rendering; so is an italic bracket group
    where ``italic_marks_onkelos`` (Genesis 12–17). Any other markup, a
    footnote asterisk, or unbalanced ⟨ ⟩ fails.
    """
    text = _CHAZAK.sub("", text)
    text = _ONKELOS_BOLD.sub(_mark, text)
    if italic_marks_onkelos:
        text = _ONKELOS_ITALIC.sub(_mark, text)
    text = _BOLD.sub(_mark, text)
    text = _normalize(html.unescape(_ITALIC_TAG.sub("", text)))
    if re.search(r"[<>{}*]", text):
        raise ValueError(f"Unexpected markup left in Metsudah text: {text[:80]!r}")
    depth = 0
    for char in text:
        depth += {ONKELOS_OPEN: 1, ONKELOS_CLOSE: -1}.get(char, 0)
        if depth not in (0, 1):
            raise ValueError(f"Unbalanced Onkelos marks in Metsudah text: {text[:80]!r}")
    if depth:
        raise ValueError(f"Unbalanced Onkelos marks in Metsudah text: {text[:80]!r}")
    return text


# --- Versification -----------------------------------------------------------
#
# Sefaria numbers Onkelos by the Hebrew (MT) verses; the server cites the
# English (BSB/KJV) verses. Runs of MT verses that the English numbers
# differently, as in TAHOT's verses table ('Exo.8.5(8.1)'): (book, MT chapter,
# first and last MT verse, English chapter, English number of the first).
MT_TO_ENGLISH = (
    ("Genesis", 32, 1, 1, 31, 55),
    ("Genesis", 32, 2, 33, 32, 1),
    ("Exodus", 7, 26, 29, 8, 1),
    ("Exodus", 8, 1, 28, 8, 5),
    ("Exodus", 21, 37, 37, 22, 1),
    ("Exodus", 22, 1, 30, 22, 2),
    ("Leviticus", 5, 20, 26, 6, 1),
    ("Leviticus", 6, 1, 23, 6, 8),
    ("Numbers", 17, 1, 15, 16, 36),
    ("Numbers", 17, 16, 28, 17, 1),
    ("Numbers", 30, 1, 1, 29, 40),
    ("Numbers", 30, 2, 17, 30, 1),
    ("Deuteronomy", 13, 1, 1, 12, 32),
    ("Deuteronomy", 13, 2, 19, 13, 1),
    ("Deuteronomy", 23, 1, 1, 22, 30),
    ("Deuteronomy", 23, 2, 26, 23, 1),
    ("Deuteronomy", 28, 69, 69, 29, 1),
    ("Deuteronomy", 29, 1, 28, 29, 2),
)
# Sefaria's Onkelos divides the Decalogue by the upper accents: one verse holds
# the four short commandments (English Exod 20:13–16, Deut 5:17–20) and the
# verses after it are numbered three lower than the English. Book: (chapter,
# the joined verse, the chapter's verse count in that division).
DECALOGUE = {"Exodus": (20, 13, 23), "Deuteronomy": (5, 17, 30)}
# Sefaria's Onkelos Numbers 26:1 also holds 'after the plague', MT 25:19.
_JOINED_MT = {("Numbers", 26, 1): "MT 25:19–26:1"}


def english_verses(book: str, chapter: int, verse: int) -> tuple[int, int, int, str | None]:
    """English (chapter, first verse, last verse) of a Sefaria Onkelos verse, and its own label.

    The label ('MT 8:1', 'Sefaria 20:14') is None where the numbers agree.
    """
    for name, mt_chapter, first, last, english_chapter, english_first in MT_TO_ENGLISH:
        if (name, mt_chapter) == (book, chapter) and first <= verse <= last:
            english = english_first + verse - first
            return english_chapter, english, english, f"MT {chapter}:{verse}"
    if book in DECALOGUE and chapter == DECALOGUE[book][0]:
        joined = DECALOGUE[book][1]
        if verse == joined:
            return chapter, verse, verse + 3, f"Sefaria {chapter}:{verse}"
        if verse > joined:
            return chapter, verse + 3, verse + 3, f"Sefaria {chapter}:{verse}"
    return chapter, verse, verse, _JOINED_MT.get((book, chapter, verse))


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


def _english_verses(book: str, chapters: list[list[str]]) -> dict[tuple[int, int], str]:
    """Non-empty Metsudah English keyed by (chapter, verse), Onkelos's renderings marked."""
    return {
        (chapter_number, verse_number): text
        for chapter_number, chapter in enumerate(chapters, 1)
        for verse_number, raw in enumerate(chapter, 1)
        if (text := clean_metsudah(raw, (book, chapter_number) in _ITALIC_ONKELOS_CHAPTERS))
    }


def _check_decalogue(book: str, source: SourceFile, chapters: list[list[str]]) -> None:
    """Fail unless a Decalogue chapter present in the file has the upper-accent verse count."""
    if book in DECALOGUE:
        chapter, _, count = DECALOGUE[book]
        if len(chapters) >= chapter and chapters[chapter - 1] and len(chapters[chapter - 1]) != count:
            raise ValueError(
                f"{source.filename}: expected the upper-accent Decalogue division "
                f"({count} verses in chapter {chapter})"
            )


def parse_targum_book(directory: Path, book: str) -> list[dict]:
    """One passage per Sefaria verse, keyed and cited by the English verse(s) it covers.

    A verse with only Aramaic or only English is single-language. The English
    keys must rise through the book, so a renumbering that does not fit the
    source fails the parse.
    """
    work = WORKS[book]
    aramaic_source, english_source = _source(book, "aramaic"), _source(book, "metsudah")
    aramaic_chapters = _load(directory, aramaic_source)
    english_chapters = _load(directory, english_source)
    _check_decalogue(book, aramaic_source, aramaic_chapters)
    _check_decalogue(book, english_source, english_chapters)
    aramaic = _aramaic_verses(book, aramaic_chapters)
    english = _english_verses(book, english_chapters)
    rows: list[dict] = []
    previous_end = 0
    for chapter, verse in sorted(aramaic.keys() | english.keys()):
        english_chapter, first, last, label = english_verses(book, chapter, verse)
        start = work.locator.key(english_chapter, first)
        end = work.locator.key(english_chapter, last)
        if start <= previous_end:
            raise ValueError(f"onkelos {book} {chapter}:{verse}: English verses out of order")
        previous_end = end
        verses = f"{first}" if first == last else f"{first}–{last}"
        row = {
            "author": AUTHOR,
            "work_key": work.key,
            "reference": f"{work.display_title} {english_chapter}:{verses}",
            "alternate_reference": label,
            "sort_start": start,
            "sort_end": end,
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
    """One link per passage to the English Torah verse(s) it translates, from its sort keys.

    The note names the Hebrew numbering where it differs, so the link prints
    'Translation of: Exod 8:5 (MT 8:1)'.
    """
    links = []
    for passage in passages:
        book = _BOOK_BY_WORK[passage["work_key"]]
        _, book_code, _ = BOOKS[book]
        chapter, verse = divmod(passage["sort_start"], 1000)
        end_chapter, end_verse = divmod(passage["sort_end"], 1000)
        label = passage.get("alternate_reference")
        links.append(BiblicalLink(
            work_key=passage["work_key"],
            locator=f"{chapter}:{verse}",
            book=book_code,
            chapter=chapter,
            verse=verse,
            end_chapter=end_chapter,
            end_verse=end_verse,
            note=f"({label})" if label else "",
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
        "Sefaria), one passage per verse, cited by book and chapter:verse in English "
        "numbering with the Hebrew number shown where it differs ('Onkelos Exodus 8:5' "
        "= MT 8:1; 'Tg. Onq. Deut 32:8'), each linked to the verse it translates. "
        "English: the Metsudah Chumash (2009, CC BY-NC), an English of the Hebrew "
        "Torah with Onkelos's renderings marked ⟨…⟩."
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
