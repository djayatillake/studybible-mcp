"""Josephus corpus: Perseus TEI of Whiston's English paired with Niese's Greek."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from .base import BiblicalLink, Corpus, SourceTag, Work, combined_license
from .download import fetch_github_directory
from .locators import SECTION, book_section

if TYPE_CHECKING:
    import httpx


PERSEUS_REPOSITORY = "PerseusDL/canonical-greekLit"
PERSEUS_COMMIT = "01b725d835e6e733062ffd79e0efdbae1ba06e5c"
PERSEUS_BASE_URL = (
    f"https://github.com/{PERSEUS_REPOSITORY}/blob/"
    f"{PERSEUS_COMMIT}/data/tlg0526"
)
LICENSE = "CC BY-SA 4.0"
ORIGINAL_LANGUAGE = "Greek"

# Labelling contract: a Jewish historian contemporary with the later NT
# writings (tier A); each work carries its own composition date.
TAG = SourceTag(
    kind="Jewish history", date="c. AD 75–100", tier="A",
    edition="Niese Greek, Whiston English",
)
CAVEAT = "Not Scripture: a Jewish historian writing c. AD 75–100; his editorial framing is his own."

WORKS = {
    "tlg001": Work(
        key="antiquities",
        title="Jewish Antiquities",
        reference_title="Antiquities",
        locator=book_section(20),
        aliases=(
            "Ant.", "A.J.", "Antiquities of the Jews", "Antiquitates Judaicae",
            "Jewish Ant.",
        ),
        tag=replace(TAG, date="AD 93–94"),
    ),
    "tlg002": Work(
        key="life",
        title="Life of Josephus",
        reference_title="Life",
        locator=SECTION,
        aliases=("Vita", "Vit.", "The Life"),
        tag=replace(TAG, date="c. AD 94–100"),
    ),
    "tlg003": Work(
        key="against_apion",
        title="Against Apion",
        reference_title="Against Apion",
        locator=book_section(2),
        aliases=("C. Ap.", "Ap.", "Apion", "Ag. Ap.", "Contra Apionem"),
        tag=replace(TAG, date="c. AD 95–100"),
    ),
    "tlg004": Work(
        key="jewish_war",
        title="The Jewish War",
        reference_title="War",
        locator=book_section(7),
        aliases=(
            "B.J.", "J.W.", "Jewish War", "Wars of the Jews", "War of the Jews",
            "Bellum Judaicum", "Bell.",
        ),
        tag=replace(TAG, date="c. AD 75–79"),
    ),
}

PERIODS = (
    "biblical", "persian", "second_temple", "hellenistic",
    "hasmonean", "herodian", "roman", "first_jewish_revolt",
)

# Editorial links, intentionally separate from Josephus's text. These identify
# direct narrative overlap, not literary dependence or historical agreement.
# Each link targets one Niese section and is attached to the imported passage
# whose section span contains it; import fails if any link does not resolve.
# Fields: work_key, book, Niese section, biblical book, chapter, verse, end
# chapter, end verse, note. The comment on each entry names what was verified
# in the pinned Whiston text of the passage containing that Niese section.
_BIBLICAL_LINKS = (
    ("antiquities", 1, 27, "Gen", 1, 1, 1, 31, "Narrative overlap: creation"),  # "In the beginning God created"
    ("antiquities", 1, 34, "Gen", 2, 4, 2, 25, "Narrative overlap: creation of humanity"),  # "God took dust from the ground"
    ("antiquities", 1, 40, "Gen", 3, 1, 3, 24, "Narrative overlap: Eden and expulsion"),  # garden, serpent
    ("antiquities", 1, 72, "Gen", 6, 1, 9, 29, "Narrative overlap: Noah and the flood"),  # "angels of God accompanied with women", Noah
    ("antiquities", 2, 224, "Exo", 2, 1, 2, 10, "Narrative overlap: birth of Moses"),  # Thermuthis finds the cradle
    ("antiquities", 2, 254, "Exo", 2, 11, 2, 22, "Narrative overlap: flight of Moses"),  # "he took his flight through the deserts"
    ("antiquities", 2, 311, "Exo", 12, 1, 14, 31, "Narrative overlap: exodus from Egypt"),  # last plague, Passover sacrifice
    ("antiquities", 3, 89, "Exo", 19, 1, 20, 26, "Narrative overlap: Sinai and the law"),  # God speaking at the mountain, two tables
    ("antiquities", 15, 380, "Jhn", 2, 20, 2, 20, "Narrative overlap: Herod begins rebuilding the temple"),  # "eighteenth year ... to build ... the temple"
    ("antiquities", 15, 391, "Mrk", 13, 1, 13, 2, "Narrative overlap: the stones of Herod's temple"),  # "stones that were white and strong"
    ("antiquities", 15, 391, "Luk", 21, 5, 21, 6, "Narrative overlap: the stones and dedicated spoils of Herod's temple"),  # stones; spoils "dedicated to the temple"
    ("antiquities", 17, 191, "Mat", 2, 19, 2, 19, "Narrative overlap: death of Herod the Great"),  # "he died, the fifth day after ... Antipater"
    ("antiquities", 17, 317, "Mat", 2, 22, 2, 22, "Narrative overlap: Archelaus made ethnarch over Judea"),  # Archelaus ethnarch; Judea
    ("antiquities", 18, 1, "Luk", 2, 1, 2, 2, "Narrative overlap: census under Cyrenius (Quirinius)"),  # Cyrenius, taxation
    ("antiquities", 18, 4, "Act", 5, 37, 5, 37, "Narrative overlap: Judas the Gaulonite and the census"),  # "Judas, a Gaulonite"
    ("antiquities", 18, 23, "Act", 5, 37, 5, 37, "Narrative overlap: Judas the Galilean"),  # "Judas the Galilean"
    ("antiquities", 18, 35, "Luk", 3, 2, 3, 2, "Narrative overlap: Ananus deposed and Caiaphas made high priest"),  # Ananus, Joseph Caiaphas
    ("antiquities", 18, 35, "Jhn", 18, 13, 18, 14, "Narrative overlap: Caiaphas made high priest"),  # Joseph Caiaphas
    ("antiquities", 18, 63, "Luk", 23, 1, 23, 25, "Narrative overlap: Jesus condemned under Pilate (Testimonium Flavianum; disputed authenticity)"),  # Jesus, Pilate, cross
    ("antiquities", 18, 95, "Jhn", 18, 13, 18, 14, "Narrative overlap: Caiaphas removed from the high priesthood"),  # Vitellius deprives Caiaphas
    ("antiquities", 18, 116, "Mrk", 6, 17, 6, 29, "Related account: death of John the Baptist"),  # John "called the Baptist", Herod
    ("antiquities", 19, 343, "Act", 12, 20, 12, 23, "Narrative overlap: death of Agrippa I at Caesarea"),  # Cesarea, acclaimed a god, five days
    ("antiquities", 20, 97, "Act", 5, 36, 5, 36, "Narrative overlap: Theudas, under the procurator Fadus"),  # Theudas, Jordan
    ("antiquities", 20, 141, "Act", 24, 24, 24, 24, "Narrative overlap: Felix and Drusilla"),  # Felix, Drusilla
    ("antiquities", 20, 169, "Act", 21, 38, 21, 38, "Narrative overlap: the Egyptian prophet"),  # out of Egypt, Mount of Olives
    ("antiquities", 20, 200, "Gal", 1, 19, 1, 19, "Narrative overlap: James, the brother of Jesus"),  # "the brother of Jesus ... James"
    ("jewish_war", 2, 118, "Act", 5, 37, 5, 37, "Narrative overlap: Judas the Galilean"),  # "a certain Galilean, whose name was Judas"
    ("jewish_war", 2, 261, "Act", 21, 38, 21, 38, "Narrative overlap: the Egyptian false prophet"),  # Egyptian, Mount of Olives
    ("jewish_war", 6, 249, "Mrk", 13, 2, 13, 2, "Narrative overlap: burning of the temple"),  # holy house "doomed it to the fire"
    ("jewish_war", 6, 249, "Luk", 21, 6, 21, 6, "Narrative overlap: burning of the temple"),
    ("jewish_war", 6, 420, "Luk", 21, 20, 21, 24, "Narrative overlap: Jerusalem besieged and its people taken captive"),  # "shut up by an army", "carried captive"
    ("jewish_war", 7, 1, "Mrk", 13, 2, 13, 2, "Narrative overlap: demolition of the city and temple"),  # "demolish the entire city and temple"
    ("jewish_war", 7, 1, "Luk", 21, 6, 21, 6, "Narrative overlap: demolition of the city and temple"),
)

# Whiston section 17.13.1 is labelled n="13" in the English TEI. The Greek
# TEI's Whiston_chapter 13 milestone and the text itself (Archelaus deposes
# Joazar, son of Boethus) place it at Niese 17.339.
_ENGLISH_SECTION_CORRECTIONS = {("tlg001", 17, "13"): 339}

_NS = {"tei": "http://www.tei-c.org/ns/1.0"}
_TEI = "{http://www.tei-c.org/ns/1.0}"
_SKIP_TEXT_ELEMENTS = {"note", "pb", "head"}


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _source_text(element: ET.Element, skip: set[str] = _SKIP_TEXT_ELEMENTS) -> str:
    """Return element text without editorial children, preserving TEI spacing."""
    parts: list[str] = []

    def visit(node: ET.Element) -> None:
        if node.text:
            parts.append(node.text)
        for child in node:
            if _local_name(child.tag) not in skip:
                visit(child)
            if child.tail:
                parts.append(child.tail)

    visit(element)
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def _section_elements(root: ET.Element) -> list[tuple[int, ET.Element]]:
    books = root.findall(".//tei:div[@subtype='book']", _NS)
    if books:
        sections: list[tuple[int, ET.Element]] = []
        for book in books:
            book_number = int(book.attrib["n"])
            for section in book.findall(".//tei:div[@subtype='section']", _NS):
                sections.append((book_number, section))
        return sections
    return [
        (1, section)
        for section in root.findall(".//tei:div[@subtype='section']", _NS)
    ]


def _period_tags(work_key: str, book_number: int) -> str:
    if work_key == "antiquities":
        if book_number <= 10:
            return "biblical"
        if book_number == 11:
            return "biblical,second_temple,persian"
        if book_number == 12:
            return "second_temple,hellenistic,hasmonean"
        if book_number == 13:
            return "second_temple,hasmonean"
        if book_number <= 17:
            return "second_temple,herodian"
        return "second_temple,herodian,roman"
    if work_key == "jewish_war":
        if book_number == 1:
            return "second_temple,hasmonean,herodian"
        return "second_temple,roman,first_jewish_revolt"
    if work_key == "life":
        return "second_temple,roman,first_jewish_revolt"
    return "second_temple,roman"


def _validate_license(root: ET.Element, path: Path) -> None:
    targets = [node.attrib.get("target", "") for node in root.findall(".//tei:licence", _NS)]
    if not any("creativecommons.org/licenses/by-sa/4.0" in target for target in targets):
        raise ValueError(f"Expected CC BY-SA 4.0 license metadata in {path}")


def _span_reference(title: str, book: int, start: int, end: int, has_books: bool) -> str:
    sections = str(start) if end == start else f"{start}–{end}"
    return f"{title} {book}.{sections}" if has_books else f"{title} {sections}"


def _english_sections(work_id: str, root: ET.Element, has_books: bool) -> dict[int, list[dict]]:
    """English Whiston sections per book, labelled with their starting Niese section."""
    by_book: dict[int, list[dict]] = {}
    chapter_by_book: dict[int, str] = {}
    for book, section in _section_elements(root):
        label = section.attrib["n"]
        start = _ENGLISH_SECTION_CORRECTIONS.get((work_id, book, label), int(label))
        whiston_section = None
        for milestone in section.iter(f"{_TEI}milestone"):
            if milestone.attrib.get("unit") == "Whiston_chapter":
                chapter_by_book[book] = milestone.attrib["n"]
            elif milestone.attrib.get("unit") == "Whiston_section" and whiston_section is None:
                whiston_section = milestone.attrib["n"]
        if whiston_section is None:
            raise ValueError(f"{work_id} {book}.{label}: missing Whiston_section milestone")
        whiston = [str(book)] if has_books else []
        if book in chapter_by_book:
            whiston.append(chapter_by_book[book])
        whiston.append(whiston_section)
        headings = [_source_text(head) for head in section.findall("tei:head", _NS)]
        sections = by_book.setdefault(book, [])
        if sections and start <= sections[-1]["start"]:
            raise ValueError(
                f"{work_id} book {book}: English section {label} does not follow "
                f"section {sections[-1]['start']}"
            )
        sections.append({
            "start": start,
            "text": _source_text(section),
            "alternate_reference": f"Whiston {'.'.join(whiston)}",
            "editorial_heading": " ".join(h for h in headings if h) or None,
        })
    return by_book


def _greek_sections(work_id: str, root: ET.Element) -> dict[int, list[tuple[int, str]]]:
    """Niese Greek sections per book; the later 'arg' tables of contents are excluded."""
    by_book: dict[int, list[tuple[int, str]]] = {}
    for book, section in _section_elements(root):
        label = section.attrib["n"]
        if label == "arg":
            continue
        if not label.isdigit():
            raise ValueError(f"{work_id} book {book}: unexpected Greek section label {label!r}")
        by_book.setdefault(book, []).append((int(label), _source_text(section)))
    for sections in by_book.values():
        sections.sort()
    return by_book


def parse_josephus_work(directory: Path, work_id: str) -> list[dict]:
    """Pair each Whiston English section with every Niese Greek section it spans.

    The English TEI has one division per Whiston section, labelled with the Niese
    section at which it starts; the Greek TEI has one division per Niese section.
    An English section spans [its start, the next English start) within its
    book; the last section of a book runs through the book's last Greek section.
    """
    work = WORKS[work_id]
    english_path = directory / f"tlg0526.{work_id}.perseus-eng2.xml"
    greek_path = directory / f"tlg0526.{work_id}.perseus-grc2.xml"
    english_root = ET.parse(english_path).getroot()
    greek_root = ET.parse(greek_path).getroot()
    _validate_license(english_root, english_path)
    _validate_license(greek_root, greek_path)

    has_books = work.key != "life"
    english = _english_sections(work_id, english_root, has_books)
    greek = _greek_sections(work_id, greek_root)
    unpaired_books = set(greek) - set(english)
    if unpaired_books:
        raise ValueError(f"{work_id}: Greek books {sorted(unpaired_books)} have no English sections")

    rows: list[dict] = []
    for book, sections in english.items():
        greek_sections = greek.get(book, [])
        if greek_sections and greek_sections[0][0] < sections[0]["start"]:
            raise ValueError(
                f"{work_id} book {book}: Greek section {greek_sections[0][0]} precedes "
                f"the first English section {sections[0]['start']}"
            )
        last_greek = greek_sections[-1][0] if greek_sections else sections[-1]["start"]
        for index, section in enumerate(sections):
            start = section["start"]
            if index + 1 < len(sections):
                end = sections[index + 1]["start"] - 1
            else:
                end = max(start, last_greek)
            greek_text = " ".join(
                text for number, text in greek_sections if start <= number <= end and text
            ) or None
            original_license = LICENSE if greek_text else None
            rows.append({
                "corpus": "josephus",
                "author": "Flavius Josephus",
                "work_key": work.key,
                "work_title": work.title,
                "reference": _span_reference(work.reference_title, book, start, end, has_books),
                "alternate_reference": section["alternate_reference"],
                "book_number": book,
                "section_number": str(start),
                "section_end": end,
                "sort_start": work.locator.key(book, start) if has_books else work.locator.key(start),
                "sort_end": work.locator.key(book, end) if has_books else work.locator.key(end),
                "editorial_heading": section["editorial_heading"],
                "text": section["text"],
                "original_text": greek_text,
                "original_language": ORIGINAL_LANGUAGE,
                "period_tags": _period_tags(work.key, book),
                "edition": "Benedikt Niese, Flavii Iosephi Opera (1885–1895)",
                "translation": "William Whiston, The Works of Flavius Josephus (1856)",
                "original_license": original_license,
                "translation_license": LICENSE,
                "license": combined_license(original_license, LICENSE, ORIGINAL_LANGUAGE),
                "source_url": f"{PERSEUS_BASE_URL}/{work_id}",
            })
    return rows


def parse(directory: Path) -> list[dict]:
    return [row for work_id in WORKS for row in parse_josephus_work(directory, work_id)]


def biblical_links(passages: list[dict]) -> list[BiblicalLink]:
    """The curated links, located by Niese 'book.section' ('section' for Life)."""
    return [
        BiblicalLink(
            work_key=work_key,
            locator=f"{book}.{section}" if work_key != "life" else str(section),
            book=biblical_book,
            chapter=c1,
            verse=v1,
            end_chapter=c2,
            end_verse=v2,
            note=note,
        )
        for work_key, book, section, biblical_book, c1, v1, c2, v2, note in _BIBLICAL_LINKS
    ]


_TEXT_FILE = re.compile(r"^tlg0526\.tlg00[1-4]\.perseus-(?:eng2|grc2)\.xml$")


JOSEPHUS_TEI_FILES = tuple(
    f"tlg0526.{work_id}.perseus-{language}.xml"
    for work_id in WORKS
    for language in ("eng2", "grc2")
)


def require_josephus_files(directory: Path) -> None:
    """Raise unless all eight pinned Josephus TEI files are present."""
    missing = [name for name in JOSEPHUS_TEI_FILES if not (directory / name).is_file()]
    if missing:
        raise FileNotFoundError(
            f"Josephus sources in {directory} are incomplete; missing "
            f"{', '.join(missing)}. Run python scripts/download_ancient_sources.py."
        )


def _select_download(work_id: str, name: str) -> str | None:
    if name == "__cts__.xml":
        return f"{work_id}.__cts__.xml"
    return name if _TEXT_FILE.fullmatch(name) else None


def _require_license_declaration(filename: str, content: bytes) -> None:
    if _TEXT_FILE.fullmatch(filename) and (
        "creativecommons.org/licenses/by-sa/4.0/" not in content.decode("utf-8")
    ):
        raise RuntimeError(f"Missing expected CC BY-SA 4.0 declaration in {filename}")


def download(client: httpx.Client, target: Path, force: bool) -> dict:
    """Fetch the metadata, Greek, and English TEI of each work at the pinned commit."""
    files: dict[str, dict] = {}
    for work_id in WORKS:
        fetched = fetch_github_directory(
            client,
            PERSEUS_REPOSITORY,
            PERSEUS_COMMIT,
            f"data/tlg0526/{work_id}",
            target,
            select=lambda name, work_id=work_id: _select_download(work_id, name),
            force=force,
            validate=_require_license_declaration,
        )
        if len(fetched) != 3:
            raise RuntimeError(f"Expected metadata, Greek, and English files for {work_id}")
        files.update(fetched)
    return {
        "repository": PERSEUS_REPOSITORY,
        "commit": PERSEUS_COMMIT,
        "license": LICENSE,
        "files": files,
    }


CORPUS = Corpus(
    key="josephus",
    label="Josephus",
    summary=(
        "Flavius Josephus: Jewish Antiquities, The Jewish War, Life, and Against "
        "Apion. Each passage is one Whiston English section with every "
        "Niese Greek section it spans, cited by Niese book.section "
        "('Antiquities 15.317–322', Life by section) plus Whiston's numbering "
        "('Whiston 15.9.3')."
    ),
    data_dir="josephus",
    original_language=ORIGINAL_LANGUAGE,
    works=tuple(WORKS.values()),
    periods=PERIODS,
    download=download,
    require_files=require_josephus_files,
    parse=parse,
    biblical_links=biblical_links,
    example_query="John Baptist",
    example_citation="Antiquities 18.116",
    aliases=("Flavius Josephus", "Josephus", "Jos."),
    heading_label="Whiston chapter heading",
    tag=TAG,
    caveat=CAVEAT,
)
