"""Rabbinic corpus: the Mishnah.

Sefaria texts come from the last full JSON export committed to
Sefaria/Sefaria-Export-Archive, pinned by commit and Git blob SHA-1 (the live
export is an unversioned GCS bucket overwritten monthly, so a checksum pin on
it cannot be re-fetched once Sefaria edits a text). Every version carries its
own licence, recorded on each passage.
"""

from __future__ import annotations

import html
import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from .base import BiblicalLink, Collection, Corpus, Work, combined_license
from .download import fetch_verified, git_blob_sha1
from .locators import NumberedLocator

if TYPE_CHECKING:
    import httpx


ARCHIVE_REPOSITORY = "Sefaria/Sefaria-Export-Archive"
# "upload sources", 2026-03-23: the last commit holding the full JSON export
# before the data moved to GCS (a1b6997, "migrate data to GCS").
ARCHIVE_COMMIT = "3f1013631fdfe452e953a93a2c5f921319e394ed"
ARCHIVE_RAW_URL = f"https://raw.githubusercontent.com/{ARCHIVE_REPOSITORY}/{ARCHIVE_COMMIT}/json/"
ARCHIVE_TREE_URL = f"https://github.com/{ARCHIVE_REPOSITORY}/tree/{ARCHIVE_COMMIT}/json/"
SEFARIA_DIR = "sefaria"
ORIGINAL_LANGUAGE = "Hebrew"

# Sefaria's per-version ``license`` values, spelled as the licence Sefaria's
# reader links them to (Sefaria-Project static/js/sefaria/sefaria.js
# getLicenseMap: CC-BY -> licenses/by/3.0). The Vilna Hebrew is Public Domain
# and Kulp's English CC-BY; any other value (e.g. "unknown") is rejected at
# download and parse time.
SEFARIA_LICENSES = {
    "Public Domain": "Public domain",
    "CC-BY": "CC BY 3.0",
}

MISHNAH = Collection("Mishnah", ("m.",))
AUTHOR = "Mishnah"
PERIOD_TAGS = "tannaitic"
PERIODS = (PERIOD_TAGS,)

CHAPTER_MISHNAH = NumberedLocator("chapter:mishnah", "1:1", separator=":")


# Tractates in order: (title, seder, aliases). Titles follow Sefaria's
# spelling; aliases add SBL abbreviations (without diacritics, which citation
# matching does not fold) and common spellings, shortest first.
_TRACTATES = (
    ("Berakhot", "Zeraim", ("Ber.", "Berachot", "Brachot")),
    ("Peah", "Zeraim", ("Pea",)),
    ("Demai", "Zeraim", ("Dem.",)),
    ("Kilayim", "Zeraim", ("Kil.", "Kilaim")),
    ("Sheviit", "Zeraim", ("Sheb.", "Shebiit")),
    ("Terumot", "Zeraim", ("Ter.", "Terumoth")),
    ("Maasrot", "Zeraim", ("Maas.", "Maaserot")),
    ("Maaser Sheni", "Zeraim", ("Maas. Sh.", "Maaser Sheini")),
    ("Challah", "Zeraim", ("Hal.", "Hallah")),
    ("Orlah", "Zeraim", ("Orl.",)),
    ("Bikkurim", "Zeraim", ("Bik.", "Bikk.")),
    ("Shabbat", "Moed", ("Shabb.", "Shab.", "Sabbath")),
    ("Eruvin", "Moed", ("Erub.", "Eruv.", "Erubin")),
    ("Pesachim", "Moed", ("Pes.", "Pesah.", "Pesahim")),
    ("Shekalim", "Moed", ("Shek.", "Sheqal.", "Sheqalim")),
    ("Yoma", "Moed", ("Kippurim",)),
    ("Sukkah", "Moed", ("Suk.", "Sukk.")),
    ("Beitzah", "Moed", ("Besah", "Betzah", "Yom Tov")),
    ("Rosh Hashanah", "Moed", ("RH", "Rosh Hash.")),
    ("Taanit", "Moed", ("Taan.", "Taanith")),
    ("Megillah", "Moed", ("Meg.",)),
    ("Moed Katan", "Moed", ("MK", "Moed Qat.", "Moed Qatan")),
    ("Chagigah", "Moed", ("Hag.", "Hagigah")),
    ("Yevamot", "Nashim", ("Yev.", "Yebam.", "Yebamot")),
    ("Ketubot", "Nashim", ("Ket.", "Ketub.", "Ketuboth")),
    ("Nedarim", "Nashim", ("Ned.",)),
    ("Nazir", "Nashim", ("Naz.",)),
    ("Sotah", "Nashim", ("Sot.", "Sota")),
    ("Gittin", "Nashim", ("Git.",)),
    ("Kiddushin", "Nashim", ("Kid.", "Qidd.", "Qiddushin")),
    ("Bava Kamma", "Nezikin", ("BK", "B. Qam.", "Baba Kamma", "Bava Qamma")),
    ("Bava Metzia", "Nezikin", ("BM", "B. Mes.", "Baba Metzia", "Baba Mezia")),
    ("Bava Batra", "Nezikin", ("BB", "B. Bat.", "Baba Bathra", "Baba Batra")),
    ("Sanhedrin", "Nezikin", ("Sanh.",)),
    ("Makkot", "Nezikin", ("Mak.", "Makkoth")),
    ("Shevuot", "Nezikin", ("Shebu.", "Shevu.", "Shebuot")),
    ("Eduyot", "Nezikin", ("Ed.", "Eduy.", "Eduyyot")),
    ("Avodah Zarah", "Nezikin", ("AZ", "Abod. Zar.", "Avod. Zar.", "Avoda Zara")),
    ("Pirkei Avot", "Nezikin", ("Avot", "Abot", "Aboth", "Pirke Avot")),
    ("Horayot", "Nezikin", ("Hor.",)),
    ("Zevachim", "Kodashim", ("Zev.", "Zebah.", "Zebahim", "Zevahim")),
    ("Menachot", "Kodashim", ("Men.", "Menah.", "Menahot")),
    ("Chullin", "Kodashim", ("Hul.", "Hullin")),
    ("Bekhorot", "Kodashim", ("Bek.", "Bekh.", "Bekorot")),
    ("Arakhin", "Kodashim", ("Arak.", "Arakin")),
    ("Temurah", "Kodashim", ("Tem.",)),
    ("Keritot", "Kodashim", ("Ker.", "Kerithot")),
    ("Meilah", "Kodashim", ("Meil.",)),
    ("Tamid", "Kodashim", ("Tam.",)),
    ("Middot", "Kodashim", ("Mid.", "Midd.")),
    ("Kinnim", "Kodashim", ("Qin.", "Qinnim")),
    ("Kelim", "Tahorot", ("Kel.",)),
    ("Oholot", "Tahorot", ("Ohal.", "Ohol.", "Ohalot", "Ahilot")),
    ("Negaim", "Tahorot", ("Neg.",)),
    ("Parah", "Tahorot", ("Par.",)),
    ("Tahorot", "Tahorot", ("Tehar.", "Toh.", "Tohorot", "Teharot")),
    ("Mikvaot", "Tahorot", ("Mikv.", "Miqw.", "Miqvaot")),
    ("Niddah", "Tahorot", ("Nid.", "Nidd.")),
    ("Makhshirin", "Tahorot", ("Maksh.", "Makhsh.", "Makshirin")),
    ("Zavim", "Tahorot", ("Zab.", "Zabim")),
    ("Tevul Yom", "Tahorot", ("T. Yom", "Tebul Yom")),
    ("Yadayim", "Tahorot", ("Yad.",)),
    ("Oktzin", "Tahorot", ("Uq.", "Uktzin", "Uqsin", "Oktsin")),
)

# Sefaria directory names that differ from the title.
_SEFARIA_NAMES = {"Taanit": "Ta'anit"}


def _slug(title: str) -> str:
    return re.sub(r"\W+", "_", title.lower()).strip("_")


@dataclass(frozen=True)
class _Source:
    """One tractate's Sefaria directory, relative to the archive's ``json/`` directory."""

    work: Work
    directory: str


def _sources() -> tuple[_Source, ...]:
    sources: list[_Source] = []
    for title, seder, aliases in _TRACTATES:
        name = _SEFARIA_NAMES.get(title, title)
        directory = name if title == "Pirkei Avot" else f"Mishnah {name}"
        work = Work(f"mishnah_{_slug(title)}", title, title, CHAPTER_MISHNAH, aliases, MISHNAH)
        sources.append(_Source(work, f"Mishnah/Seder {seder}/{directory}"))
    return tuple(sources)


SOURCES = _sources()
WORKS = tuple(source.work for source in SOURCES)

# Editorial links, separate from the texts: narrative overlap or related
# accounts, not literary dependence or historical agreement. Fields: work
# key, locator in the work's grammar, biblical book, chapter, verse, end
# chapter, end verse, note. The comment on each entry names what was verified
# in the pinned text of the passage containing the locator.
_BIBLICAL_LINKS = (
    # Kulp 1:1: "they make a public announcement about the shekels"
    ("mishnah_shekalim", "1:1", "Mat", 17, 24, 17, 27,
     "Related account: the annual half-shekel contribution to the temple"),
    # Kulp 1:3: "they would set up tables [of money changers] in the provinces.
    # On the twenty-fifth they set them up in the Temple"; pledges exacted
    ("mishnah_shekalim", "1:3", "Mat", 17, 24, 17, 27,
     "Related account: collection of the half-shekel temple contribution"),
)


# --- Text cleaning

_HTML_TAG = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9]*)\b([^<>]*)>")
# Only these are markup; anything else in angle brackets is editorial text of
# the version and is kept.
_HTML_TAGS = frozenset(
    {"a", "b", "big", "br", "div", "em", "i", "p", "small", "span", "strong", "sub", "sup", "u"}
)


def _tidy(text: str) -> str:
    lines = (re.sub(r"[ \t ]+", " ", line).strip() for line in text.split("\n"))
    return "\n".join(line for line in lines if line)


def clean_html(raw: str, where: str) -> str:
    """Plain text of a Sefaria segment: tags dropped, footnotes and their markers removed.

    A footnote is a ``<sup>`` marker or an element whose attributes name a
    footnote class; its content is skipped up to the matching close tag. In a
    segment with footnotes, unbalanced ``<i>``/``<sup>`` tags (which would
    misplace a footnote's end) raise ``ValueError``.
    """
    if "<sup" in raw or "footnote" in raw:
        for name in ("i", "sup"):
            opened = len(re.findall(rf"<{name}\b[^<>]*>", raw))
            if opened != raw.count(f"</{name}>"):
                raise ValueError(f"{where}: unbalanced <{name}> tags around a footnote")
    parts: list[str] = []
    skipping: str | None = None
    depth = 0
    position = 0
    for match in _HTML_TAG.finditer(raw):
        closing, name, attributes = match[1] == "/", match[2].lower(), match[3]
        if name not in _HTML_TAGS:
            continue
        if skipping is None:
            parts.append(raw[position:match.start()])
        position = match.end()
        if name == "br":
            if skipping is None:
                parts.append("\n")
            continue
        if attributes.rstrip().endswith("/"):
            continue
        if skipping is not None:
            if name == skipping:
                depth += -1 if closing else 1
                if depth == 0:
                    skipping = None
        elif not closing and (name == "sup" or "footnote" in attributes):
            skipping, depth = name, 1
    if skipping is not None:
        raise ValueError(f"{where}: unclosed footnote <{skipping}>")
    parts.append(raw[position:])
    return _tidy(html.unescape("".join(parts)))


# --- Pins

def _sefaria_pins() -> dict[str, str]:
    pins = {}
    for line in _SEFARIA_BLOBS.strip().splitlines():
        blob, path = line.split("  ", 1)
        pins[path] = blob
    return pins


def _pinned_version(pins: dict[str, str], directory: str, language: str) -> str | None:
    """The pinned file of ``directory``/``language``, if any; more than one is an error."""
    found = [path for path in pins if path.startswith(f"{directory}/{language}/")]
    if len(found) > 1:
        raise ValueError(f"Several pinned {language} versions in {directory}: {found}")
    return found[0] if found else None


def required_files() -> list[str]:
    return [f"{SEFARIA_DIR}/{path}" for path in _sefaria_pins()]


def require_rabbinic_files(directory: Path) -> None:
    """Raise unless every pinned Sefaria file is present."""
    missing = [name for name in required_files() if not (directory / name).is_file()]
    if missing:
        raise FileNotFoundError(
            f"Rabbinic sources in {directory} are incomplete; missing {len(missing)} files: "
            f"{', '.join(missing)}. Run python scripts/download_ancient_sources.py."
        )


# --- Parsing

def _load_version(directory: Path, path: str) -> dict[str, Any]:
    version = json.loads((directory / SEFARIA_DIR / path).read_text(encoding="utf-8"))
    license_ = version.get("license")
    if license_ not in SEFARIA_LICENSES:
        raise ValueError(f"{path}: Sefaria licence {license_!r} is not an open licence")
    version["license"] = SEFARIA_LICENSES[license_]
    return version


def _source_url(directory: str) -> str:
    return ARCHIVE_TREE_URL + quote(directory)


def _passage(work: Work, reference: str, key: int, english: tuple[dict, str] | None,
             original: tuple[dict, str] | None, hebrew: dict, source_url: str) -> dict[str, Any]:
    """A passage dict; ``hebrew`` names the edition even where it lacks this passage."""
    row: dict[str, Any] = {
        "work_key": work.key,
        "reference": reference,
        "sort_start": key,
        "sort_end": key,
        "author": AUTHOR,
        "period_tags": PERIOD_TAGS,
        "source_url": source_url,
        "edition": hebrew["versionTitle"] if original else
        f"{hebrew['versionTitle']} (lacks this passage)",
    }
    original_license = translation_license = None
    if original is not None:
        version, text = original
        original_license = version["license"]
        row.update(original_text=text, original_language=ORIGINAL_LANGUAGE,
                   original_license=original_license)
    if english is not None:
        version, text = english
        translation_license = version["license"]
        row.update(text=text, translation=version["versionTitle"],
                   translation_license=translation_license)
    row["license"] = combined_license(original_license, translation_license, ORIGINAL_LANGUAGE)
    return row


def _mishnah_passages(directory: Path, source: _Source, pins: dict[str, str]) -> Iterator[dict]:
    """One passage per mishnah, with whichever of the Hebrew and English it has."""
    hebrew_path = _pinned_version(pins, source.directory, "Hebrew")
    english_path = _pinned_version(pins, source.directory, "English")
    if hebrew_path is None:
        raise ValueError(f"No pinned Hebrew version for {source.work.display_title}")
    if english_path is None:
        raise ValueError(f"No pinned English version for {source.work.display_title}")
    hebrew = _load_version(directory, hebrew_path)
    english = _load_version(directory, english_path)
    work = source.work
    chapters = max(len(hebrew["text"]), len(english["text"]))
    for chapter in range(1, chapters + 1):
        hebrew_chapter = hebrew["text"][chapter - 1] if chapter <= len(hebrew["text"]) else []
        english_chapter = english["text"][chapter - 1] if chapter <= len(english["text"]) else []
        for number in range(1, max(len(hebrew_chapter), len(english_chapter)) + 1):
            reference = f"{work.display_title} {chapter}:{number}"
            original = english_segment = None
            if number <= len(hebrew_chapter) and (text := clean_html(hebrew_chapter[number - 1], reference)):
                original = (hebrew, text)
            if number <= len(english_chapter) and (text := clean_html(english_chapter[number - 1], reference)):
                english_segment = (english, text)
            if original is None and english_segment is None:
                continue
            yield _passage(
                work, reference, work.locator.key(chapter, number), english_segment, original,
                hebrew, _source_url(source.directory),
            )


def parse(directory: Path) -> Iterator[dict]:
    pins = _sefaria_pins()
    for source in SOURCES:
        yield from _mishnah_passages(directory, source, pins)


def biblical_links(passages: list[dict]) -> list[BiblicalLink]:
    return [BiblicalLink(*link) for link in _BIBLICAL_LINKS]


# --- Download

def _require_open_license(path: str, content: bytes) -> str:
    license_ = json.loads(content).get("license")
    if license_ not in SEFARIA_LICENSES:
        raise RuntimeError(f"{path}: Sefaria licence {license_!r} is not an open licence")
    return SEFARIA_LICENSES[license_]


def download(client: httpx.Client, target: Path, force: bool) -> dict:
    """Fetch the pinned Sefaria archive files, verifying each hash and licence."""
    files: dict[str, dict] = {}
    for path, blob in _sefaria_pins().items():
        local = f"{SEFARIA_DIR}/{path}"
        content = fetch_verified(
            client, ARCHIVE_RAW_URL + quote(path), target / local, blob, force, git_blob_sha1
        )
        files[local] = {
            "git_blob_sha1": blob,
            "bytes": len(content),
            "license": _require_open_license(path, content),
            "source_url": f"https://github.com/{ARCHIVE_REPOSITORY}/blob/{ARCHIVE_COMMIT}/json/{quote(path)}",
        }
    return {
        "repository": ARCHIVE_REPOSITORY,
        "commit": ARCHIVE_COMMIT,
        "license": "Per version: see each file's licence",
        "files": files,
    }


CORPUS = Corpus(
    key="rabbinic",
    label="Rabbinic",
    summary=(
        "The Mishnah from Sefaria: all 63 tractates, the Vilna 1913 Hebrew with "
        "Joshua Kulp's English (Mishnah Yomit), one passage per mishnah, cited by "
        "tractate and chapter:mishnah ('Mishnah Shekalim 1:1', 'm. Shek. 1:1'). "
        "Each passage carries its versions' licences."
    ),
    data_dir="rabbinic",
    original_language=ORIGINAL_LANGUAGE,
    works=WORKS,
    periods=PERIODS,
    download=download,
    require_files=require_rabbinic_files,
    parse=parse,
    biblical_links=biblical_links,
    example_query="shekels Adar",
    example_citation="Mishnah Shekalim 1:1",
    aliases=("Rabbinic",),
)


# --- Pins. Sefaria files: Git blob SHA-1 and path under json/ in
# Sefaria/Sefaria-Export-Archive at ARCHIVE_COMMIT. Each version's licence is
# its JSON ``license`` field, checked at download and parse time.
_SEFARIA_BLOBS = """
e9df1fefec2f44cb1ebefb478446f248b19b2913  Mishnah/Seder Kodashim/Mishnah Arakhin/English/Mishnah Yomit by Dr. Joshua Kulp.json
17a8c1817ed7e3c3aa5fd6eaf83e162e12c61824  Mishnah/Seder Kodashim/Mishnah Arakhin/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
6b6927ad7c2041c623680a5fc184260f62d175c4  Mishnah/Seder Kodashim/Mishnah Bekhorot/English/Mishnah Yomit by Dr. Joshua Kulp.json
eadcf73f0fb6cd44eef81c5fae0b9f8a4e060ade  Mishnah/Seder Kodashim/Mishnah Bekhorot/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
8034a657bcf9ce7c6ecca077c32f335a51ca9498  Mishnah/Seder Kodashim/Mishnah Chullin/English/Mishnah Yomit by Dr. Joshua Kulp.json
3b9f31756a97b73106284ba9c76442fc7f184806  Mishnah/Seder Kodashim/Mishnah Chullin/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
4781100b6bba4a97e927881ced24c29d87961195  Mishnah/Seder Kodashim/Mishnah Keritot/English/Mishnah Yomit by Dr. Joshua Kulp.json
a5e8c034872714f61a594287dcfb3a3ed9bc703b  Mishnah/Seder Kodashim/Mishnah Keritot/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
f0b4604f0a77b6ef9f638fa395000c3de1465310  Mishnah/Seder Kodashim/Mishnah Kinnim/English/Mishnah Yomit by Dr. Joshua Kulp.json
37994f782a7f0820a97b9585da4b0242e6cdee9e  Mishnah/Seder Kodashim/Mishnah Kinnim/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
34966d324e74b6a317d090a5308fb2f2a5ae68d9  Mishnah/Seder Kodashim/Mishnah Meilah/English/Mishnah Yomit by Dr. Joshua Kulp.json
466477b20664e1e020c605a4f275b82fe86a4513  Mishnah/Seder Kodashim/Mishnah Meilah/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
835f8b99acf8857c808da1b66022724c2f9544f9  Mishnah/Seder Kodashim/Mishnah Menachot/English/Mishnah Yomit by Dr. Joshua Kulp.json
26f5ec7f472512a7227bf7801bd1b3f98261c482  Mishnah/Seder Kodashim/Mishnah Menachot/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
420a5b3aa848291bff003ccd67d146f15ac2c998  Mishnah/Seder Kodashim/Mishnah Middot/English/Mishnah Yomit by Dr. Joshua Kulp.json
46079cf7215fddfa794c42a005af29ded2c99d76  Mishnah/Seder Kodashim/Mishnah Middot/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
307df490bb991cf7ed7d456bfbac387a9adbeb4f  Mishnah/Seder Kodashim/Mishnah Tamid/English/Mishnah Yomit by Dr. Joshua Kulp.json
356e989fc85683ee6c6b0e7449f54c68eb429c79  Mishnah/Seder Kodashim/Mishnah Tamid/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
2adb83327d0307842a9e5f569ce80df601bb839a  Mishnah/Seder Kodashim/Mishnah Temurah/English/Mishnah Yomit by Dr. Joshua Kulp.json
faae65c4ae16f2a73ab9517d7f5b7de74c71d5fb  Mishnah/Seder Kodashim/Mishnah Temurah/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
f52909550a034262140bfa2765bfb6e732c39f9a  Mishnah/Seder Kodashim/Mishnah Zevachim/English/Mishnah Yomit by Dr. Joshua Kulp.json
412162f32289155d9addd1b57cd67c7ab0fef6a8  Mishnah/Seder Kodashim/Mishnah Zevachim/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
a927c6bc65517aab13bd4d52c2d1140e71191b1e  Mishnah/Seder Moed/Mishnah Beitzah/English/Mishnah Yomit by Dr. Joshua Kulp.json
3571d4cf76da1e7ec81d30567d0308633d13ec6b  Mishnah/Seder Moed/Mishnah Beitzah/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
e37ad0c4feb65d7226ba012d27d5b5a0ea9247c8  Mishnah/Seder Moed/Mishnah Chagigah/English/Mishnah Yomit by Dr. Joshua Kulp.json
11c5866ee7b894eab2f02cdd1e77e8d51df50f83  Mishnah/Seder Moed/Mishnah Chagigah/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
1fed90b487d3b0d392fb4918c09a91fb1ca8fc7d  Mishnah/Seder Moed/Mishnah Eruvin/English/Mishnah Yomit by Dr. Joshua Kulp.json
5e18a12500006b33b0482f531cf1d9bc7a2fece8  Mishnah/Seder Moed/Mishnah Eruvin/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
012eaf978da2bb69bcafe0c9d37676210c0bf2e9  Mishnah/Seder Moed/Mishnah Megillah/English/Mishnah Yomit by Dr. Joshua Kulp.json
6c6c34fdd066970ecef9ab0dbd99c802a07809fb  Mishnah/Seder Moed/Mishnah Megillah/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
5891c6adc2e7ce68bdc08f049e700431a2a230f7  Mishnah/Seder Moed/Mishnah Moed Katan/English/Mishnah Yomit by Dr. Joshua Kulp.json
8615732d86b7205a489b90f5da43d843d0d34602  Mishnah/Seder Moed/Mishnah Moed Katan/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
6b67686cbc27df3129a43723a12a70a7f1d038b8  Mishnah/Seder Moed/Mishnah Pesachim/English/Mishnah Yomit by Dr. Joshua Kulp.json
97da310d4198d7da9c1d757b2b03187b93e7cc73  Mishnah/Seder Moed/Mishnah Pesachim/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
74a7f5f62b6a59ded9fa3863095c13cdaa80ee9b  Mishnah/Seder Moed/Mishnah Rosh Hashanah/English/Mishnah Yomit by Dr. Joshua Kulp.json
979f83510f497c2892de6a5b6d1e9b2a0f10a9e3  Mishnah/Seder Moed/Mishnah Rosh Hashanah/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
01ccf3ebf15a90e89ccce46720b4fa6ac1e84f71  Mishnah/Seder Moed/Mishnah Shabbat/English/Mishnah Yomit by Dr. Joshua Kulp.json
33e5c57f1a085d6ea8447352528edc8521606957  Mishnah/Seder Moed/Mishnah Shabbat/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
e0224bdc53708f29358f602129c1683750618ee0  Mishnah/Seder Moed/Mishnah Shekalim/English/Mishnah Yomit by Dr. Joshua Kulp.json
4c570c7e07e5d0f01ff6a48cf7f7b55f443642c3  Mishnah/Seder Moed/Mishnah Shekalim/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
538c6f35433efc533a8e87975c4526083cbe2dc5  Mishnah/Seder Moed/Mishnah Sukkah/English/Mishnah Yomit by Dr. Joshua Kulp.json
b87665dc9cd4b33224ce45788cc84bef31fc34bb  Mishnah/Seder Moed/Mishnah Sukkah/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
f845e1fcb572d93f5cb9fb1a9f89177a095bfb8f  Mishnah/Seder Moed/Mishnah Ta'anit/English/Mishnah Yomit by Dr. Joshua Kulp.json
667750fab4e48cf28ac54fa5587dfc058ac87436  Mishnah/Seder Moed/Mishnah Ta'anit/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
9f8e93e135b1f1d8edf1202197d8727fcd3ce49a  Mishnah/Seder Moed/Mishnah Yoma/English/Mishnah Yomit by Dr. Joshua Kulp.json
6c5115ee11632c68f3e37591d812760c44953b6d  Mishnah/Seder Moed/Mishnah Yoma/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
52a04e74912922c7256c3afa603505216bdfa45f  Mishnah/Seder Nashim/Mishnah Gittin/English/Mishnah Yomit by Dr. Joshua Kulp.json
42bf5ff6289994fa22191029f41560ebac9be8ec  Mishnah/Seder Nashim/Mishnah Gittin/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
7d861424d5b6750dd84f0b41bb17e6e028c9415f  Mishnah/Seder Nashim/Mishnah Ketubot/English/Mishnah Yomit by Dr. Joshua Kulp.json
19739b737b3062dec7faaa8171e549398af7172f  Mishnah/Seder Nashim/Mishnah Ketubot/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
ce1e4cf57aa047c9dbb197b99ef06855368395d3  Mishnah/Seder Nashim/Mishnah Kiddushin/English/Mishnah Yomit by Dr. Joshua Kulp.json
fc8703f318bf2870f064e6eb0bdfc6887c5a79c1  Mishnah/Seder Nashim/Mishnah Kiddushin/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
e007f1e54a47a8e998c7dc4f66f61a6035c9bd79  Mishnah/Seder Nashim/Mishnah Nazir/English/Mishnah Yomit by Dr. Joshua Kulp.json
a4d4e1e8a0a744a99be729477040757668120850  Mishnah/Seder Nashim/Mishnah Nazir/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
49e976fd68662776a5d75b1f5a6cfb7ce1462ae3  Mishnah/Seder Nashim/Mishnah Nedarim/English/Mishnah Yomit by Dr. Joshua Kulp.json
d3074ff4350eaffb030c66b4fd3b89065fc9db19  Mishnah/Seder Nashim/Mishnah Nedarim/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
f951e4be123fe455ecbe510687b092bc7dd408a3  Mishnah/Seder Nashim/Mishnah Sotah/English/Mishnah Yomit by Dr. Joshua Kulp.json
4693577314500c22915b00c6331b8078fea0726b  Mishnah/Seder Nashim/Mishnah Sotah/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
6b548c789e381790d44123faa27a8961d609436c  Mishnah/Seder Nashim/Mishnah Yevamot/English/Mishnah Yomit by Dr. Joshua Kulp.json
83c25c2007f657c8fafb824649576eea4f1d43e4  Mishnah/Seder Nashim/Mishnah Yevamot/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
f1c1e48df745d4eef4411e0034c42f2ec11d43a8  Mishnah/Seder Nezikin/Mishnah Avodah Zarah/English/Mishnah Yomit by Dr. Joshua Kulp.json
6f573aea678e24b44fa81745a6e397371aa096a9  Mishnah/Seder Nezikin/Mishnah Avodah Zarah/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
4d8b2068ba28f9b8ba9db49237025f95acd7bb93  Mishnah/Seder Nezikin/Mishnah Bava Batra/English/Mishnah Yomit by Dr. Joshua Kulp.json
88d534256b04ca0673ba4bcb83b76d06857ef7a8  Mishnah/Seder Nezikin/Mishnah Bava Batra/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
b2e6762c3cd78f2b021b38ac9d50a9f16d893fb3  Mishnah/Seder Nezikin/Mishnah Bava Kamma/English/Mishnah Yomit by Dr. Joshua Kulp.json
a918c9c9c8b739995724c7571f17380f3ddee5a6  Mishnah/Seder Nezikin/Mishnah Bava Kamma/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
158dbbd33f0385f2c336f27a76e06eac9420d722  Mishnah/Seder Nezikin/Mishnah Bava Metzia/English/Mishnah Yomit by Dr. Joshua Kulp.json
575af823968ed44e16d18724be6ffdef86cf0f51  Mishnah/Seder Nezikin/Mishnah Bava Metzia/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
b730b0bcdeafc34501711123a5fce94685baceac  Mishnah/Seder Nezikin/Mishnah Eduyot/English/Mishnah Yomit by Dr. Joshua Kulp.json
dab24dc65bdc0261c911e67af34d4496c825150b  Mishnah/Seder Nezikin/Mishnah Eduyot/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
4a7f79421b1f77fd961e6f6b72c1e3f6f145e7e5  Mishnah/Seder Nezikin/Mishnah Horayot/English/Mishnah Yomit by Dr. Joshua Kulp.json
e00ca809e72d683c4fb5208886e72141d2c76ff4  Mishnah/Seder Nezikin/Mishnah Horayot/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
fbb4b1b76e5357007990a7751b1afc4dc941c788  Mishnah/Seder Nezikin/Mishnah Makkot/English/Mishnah Yomit by Dr. Joshua Kulp.json
6294e0aab0b3f1f1dddf88db67cffc255988bd05  Mishnah/Seder Nezikin/Mishnah Makkot/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
783e2592296ce02dce874d82b595956e33dca998  Mishnah/Seder Nezikin/Mishnah Sanhedrin/English/Mishnah Yomit by Dr. Joshua Kulp.json
990b83ab7a96f57c9ca02936ed431cd2d940e818  Mishnah/Seder Nezikin/Mishnah Sanhedrin/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
4ec9d9efa7daf65ae76c9de9b3d51ab245c059a0  Mishnah/Seder Nezikin/Mishnah Shevuot/English/Mishnah Yomit by Dr. Joshua Kulp.json
0f2c739e7d081e155e94bedafd833bf3d80036be  Mishnah/Seder Nezikin/Mishnah Shevuot/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
c3164223aa4ddeecf23c76bfce29a91138b0cb0f  Mishnah/Seder Nezikin/Pirkei Avot/English/Mishnah Yomit by Dr. Joshua Kulp.json
76b6484cb972f56fc31565e8be3a44101eaf042d  Mishnah/Seder Nezikin/Pirkei Avot/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
16dc313781d1d4fee57fcdc3772157b0784dbfae  Mishnah/Seder Tahorot/Mishnah Kelim/English/Mishnah Yomit by Dr. Joshua Kulp.json
2067eeb89c69903c708e9b608fbc3128782a36a3  Mishnah/Seder Tahorot/Mishnah Kelim/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
8e9fc091ad80271bc160c4d019aaf61f1ce309ea  Mishnah/Seder Tahorot/Mishnah Makhshirin/English/Mishnah Yomit by Dr. Joshua Kulp.json
50b68a14b9077faa8d60035cbe97b928b6cc5388  Mishnah/Seder Tahorot/Mishnah Makhshirin/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
026220ce56eccf748f5097056294f265118cb6ff  Mishnah/Seder Tahorot/Mishnah Mikvaot/English/Mishnah Yomit by Dr. Joshua Kulp.json
a9cb603ecf24056047bfe4ec3b877ba926886310  Mishnah/Seder Tahorot/Mishnah Mikvaot/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
8406bd7e9654860b4b816abf5a6279b560d6cc7b  Mishnah/Seder Tahorot/Mishnah Negaim/English/Mishnah Yomit by Dr. Joshua Kulp.json
2d867ba1b2dac4992a67110c447ba18d7234f3ad  Mishnah/Seder Tahorot/Mishnah Negaim/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
e14bc4b6b5893f984d06f73611cdd93af473b530  Mishnah/Seder Tahorot/Mishnah Niddah/English/Mishnah Yomit by Dr. Joshua Kulp.json
9320fc5ed22d32437c664b4b195466e0e2056720  Mishnah/Seder Tahorot/Mishnah Niddah/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
548db13bbb75630faea3b4263ce8a669dea0e8de  Mishnah/Seder Tahorot/Mishnah Oholot/English/Mishnah Yomit by Dr. Joshua Kulp.json
b245546dbda4e7e8255f1eda2e8ecbdee6b43400  Mishnah/Seder Tahorot/Mishnah Oholot/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
d27323c895e1889bf69db90beedb8f349f8915c6  Mishnah/Seder Tahorot/Mishnah Oktzin/English/Mishnah Yomit by Dr. Joshua Kulp.json
60ed4fb4da5730474d4bf5b23b5fc0b1ce2cf980  Mishnah/Seder Tahorot/Mishnah Oktzin/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
94a66f013cba08dca41061d8ef7b92abc8849f37  Mishnah/Seder Tahorot/Mishnah Parah/English/Mishnah Yomit by Dr. Joshua Kulp.json
b818233a9f91617a08f3aa529376296561632e73  Mishnah/Seder Tahorot/Mishnah Parah/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
626decf7f796b73f70eef7059c082c43e293739a  Mishnah/Seder Tahorot/Mishnah Tahorot/English/Mishnah Yomit by Dr. Joshua Kulp.json
dd579f3d45090369912a07bdfa28577fcd72c41c  Mishnah/Seder Tahorot/Mishnah Tahorot/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
bf60c487672e92727d5645913e833632c299c309  Mishnah/Seder Tahorot/Mishnah Tevul Yom/English/Mishnah Yomit by Dr. Joshua Kulp.json
4fbaad9e767462176aebe0baa80b09884c583873  Mishnah/Seder Tahorot/Mishnah Tevul Yom/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
d4af3abdbeb9ab2ad717b517177e51ae95e9a2bb  Mishnah/Seder Tahorot/Mishnah Yadayim/English/Mishnah Yomit by Dr. Joshua Kulp.json
373515656974d5a7100137b5a0e97eb4024d1ec8  Mishnah/Seder Tahorot/Mishnah Yadayim/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
accfd83d560d35c570892101b54ac98c37ee5824  Mishnah/Seder Tahorot/Mishnah Zavim/English/Mishnah Yomit by Dr. Joshua Kulp.json
9acf0f1e9ef0943fc78a388e02d28a9ac6f3411f  Mishnah/Seder Tahorot/Mishnah Zavim/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
d00c7bba9c12ad8a8be249619da9a600db2fbb36  Mishnah/Seder Zeraim/Mishnah Berakhot/English/Mishnah Yomit by Dr. Joshua Kulp.json
62b357931b00366f5c4d0f250ba1fbd3fd6d79de  Mishnah/Seder Zeraim/Mishnah Berakhot/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
f0f006cce15cc7d35752f0b8d25e130faff4a537  Mishnah/Seder Zeraim/Mishnah Bikkurim/English/Mishnah Yomit by Dr. Joshua Kulp.json
a288833f36b81cfa0c386a350255f279ee555962  Mishnah/Seder Zeraim/Mishnah Bikkurim/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
582512085e5bba9561a1a365376755823c5e723d  Mishnah/Seder Zeraim/Mishnah Challah/English/Mishnah Yomit by Dr. Joshua Kulp.json
36be8be4d29953fe58455633f868909b7b29a2a5  Mishnah/Seder Zeraim/Mishnah Challah/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
2bc9b8428d812f94f4afe89e29ec74cce71725e6  Mishnah/Seder Zeraim/Mishnah Demai/English/Mishnah Yomit by Dr. Joshua Kulp.json
35957b1be5d3de8c5b7fab9d717d37c3388139fe  Mishnah/Seder Zeraim/Mishnah Demai/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
68a4fc89e794f1ecfe790d1eece8e29c6627c72c  Mishnah/Seder Zeraim/Mishnah Kilayim/English/Mishnah Yomit by Dr. Joshua Kulp.json
38b5a465112b841f353533c9ab0d87503548513e  Mishnah/Seder Zeraim/Mishnah Kilayim/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
e0cf029434fe874ec7e9f68946b4915795fc077f  Mishnah/Seder Zeraim/Mishnah Maaser Sheni/English/Mishnah Yomit by Dr. Joshua Kulp.json
b46ec33f927b9819f6b79dc2713dc9296d41b819  Mishnah/Seder Zeraim/Mishnah Maaser Sheni/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
e7e98d282e4f50f0ed912f81cf8b75cfffc709ed  Mishnah/Seder Zeraim/Mishnah Maasrot/English/Mishnah Yomit by Dr. Joshua Kulp.json
1fd93cc64accc688656306563714039d9f075c3e  Mishnah/Seder Zeraim/Mishnah Maasrot/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
f738cef67eb7fb16dd388496ec09a36ea9deca0b  Mishnah/Seder Zeraim/Mishnah Orlah/English/Mishnah Yomit by Dr. Joshua Kulp.json
547ff8f64965ee3677de160278fafb9a8a31ca23  Mishnah/Seder Zeraim/Mishnah Orlah/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
ee7da8bf70dcc5b12f4689e4ffcbf1668e19dddf  Mishnah/Seder Zeraim/Mishnah Peah/English/Mishnah Yomit by Dr. Joshua Kulp.json
26c99385e70359265cee2c24c3390b53d1a82ceb  Mishnah/Seder Zeraim/Mishnah Peah/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
416e7c2df5efa18175d85df95f2f605709c02c41  Mishnah/Seder Zeraim/Mishnah Sheviit/English/Mishnah Yomit by Dr. Joshua Kulp.json
9b576cc4c4fa56028cd918973b18be113f4537b0  Mishnah/Seder Zeraim/Mishnah Sheviit/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
be084d1b572ea5f189cfb2d39e07149056b957d4  Mishnah/Seder Zeraim/Mishnah Terumot/English/Mishnah Yomit by Dr. Joshua Kulp.json
f64b01ca0c3d7e6e7a6a08973a7ec175195e3ace  Mishnah/Seder Zeraim/Mishnah Terumot/Hebrew/Mishnah, ed. Romm, Vilna 1913.json
"""
