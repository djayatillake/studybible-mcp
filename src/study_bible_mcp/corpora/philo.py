"""Philo corpus: First1KGreek TEI of the Cohn–Wendland Greek paired with Yonge's English."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .base import BiblicalLink, Corpus, SourceTag, Work, combined_license
from .download import fetch_verified, git_blob_sha1
from .locators import BOOK_SECTION, SECTION

if TYPE_CHECKING:
    import httpx


REPOSITORY = "OpenGreekAndLatin/First1KGreek"
COMMIT = "03776b39f4047c5cff06f5296fae4b2bae4b08fb"
_RAW_BASE = f"https://raw.githubusercontent.com/{REPOSITORY}/{COMMIT}/data/tlg0018"
_TREE_BASE = f"https://github.com/{REPOSITORY}/tree/{COMMIT}/data/tlg0018"
LICENSE = "CC BY-SA 4.0"
ORIGINAL_LANGUAGE = "Greek"
AUTHOR = "Philo of Alexandria"
PERIODS = ("second_temple", "roman")
# Every treatise was written in Roman Alexandria in the first half of the first
# century CE; the tag records the period of composition.
_PERIOD_TAGS = "second_temple,roman"
TAG = SourceTag(
    kind="Hellenistic Jewish philosophy", date="c. AD 20–50", tier="A",
    edition="Cohn–Wendland Greek, Yonge English 1854–55",
)
CAVEAT = (
    "Not Scripture; not Christian. Platonising allegory on the Greek Pentateuch; "
    "his Logos is not the incarnate Son (John 1:14; Heb 1)."
)

# Cohn–Wendland volume -> year of publication (Berlin: Reimer).
_CW_YEARS = {1: 1896, 2: 1897, 3: 1898, 4: 1902, 5: 1906, 6: 1915}
# Yonge volume -> year of publication (London: Bohn).
_YONGE_YEARS = {1: 1854, 2: 1854, 3: 1855, 4: 1855}


@dataclass(frozen=True)
class _Treatise:
    """One First1KGreek work: citation metadata, edition volumes and pinned blobs."""

    work: Work
    cw_volume: int
    yonge_volume: int
    greek_blob: str
    english_blob: str


def _work(key, title, short, locator, *aliases):
    return Work(key=key, title=title, reference_title=short, locator=locator, aliases=aliases)


# tlg id -> treatise. Short titles follow the SBL Handbook; multi-book works are
# cited book.section ('Leg. 1.31'), the rest by section ('Opif. 1'). Blob hashes
# are the Git blob SHA-1s of the grc1 and eng1 files at COMMIT.
TREATISES = {
    "tlg001": _Treatise(_work(
        "opif", "On the Creation of the World", "Opif.", SECTION,
        "Op.", "De Opificio Mundi", "On the Creation", "Creation of the World",
    ), 1, 1, "b7a7546f5a27cc30a79976f29ff86c6afb297e5d", "f6fa0377cfe8a5b8a30d6568a99420ffcb7f9936"),
    "tlg002": _Treatise(_work(
        "leg", "Allegorical Interpretation", "Leg.", BOOK_SECTION,
        "Leg. All.", "Legum Allegoriae", "Allegorical Interpretation of Genesis",
        "On the Allegories of the Sacred Laws",
    ), 1, 1, "9e26b69b588c36751f1e1de8755b2e9325d39106", "bc3190c9259edeb4474ebe7025e990cf224293f7"),
    "tlg003": _Treatise(_work(
        "cher", "On the Cherubim", "Cher.", SECTION, "De Cherubim",
    ), 1, 1, "55e689330e568bcfa5eaf4893073763218205292", "b701d53aaa241f79526f811eb2c45a36fb663004"),
    "tlg004": _Treatise(_work(
        "sacr", "On the Sacrifices of Abel and Cain", "Sacr.", SECTION,
        "De Sacrificiis Abelis et Caini", "On the Sacrifice of Abel and Cain",
    ), 1, 1, "52515652b19de30aab82e59d0605c4305ee6e7f9", "1e48d492430d5bed301bec922b09be34884a6eb0"),
    "tlg005": _Treatise(_work(
        "det", "That the Worse Attacks the Better", "Det.", SECTION,
        "Quod Deterius Potiori Insidiari Soleat", "Quod Deterius",
    ), 1, 1, "050a74ad2e1d8df52bac05547e299135c22c1aeb", "ecdc3af7cf1bd35b62e12022a4822192ef5062e2"),
    "tlg006": _Treatise(_work(
        "post", "On the Posterity of Cain", "Post.", SECTION, "De Posteritate Caini",
    ), 2, 1, "bf99d505c31107114d842d7b3d98fc98bdfcb967", "3ba658f8ecaf4b0d9396133b20e5d280bd262f20"),
    "tlg007": _Treatise(_work(
        "gig", "On the Giants", "Gig.", SECTION, "De Gigantibus",
    ), 2, 1, "c8b29f9a5722b47a8fcc7b1d1f3ef49cdc1615c4", "aadd7f4dfc4ed2fb0c7f782c1b8e97a5a4bcf81f"),
    "tlg008": _Treatise(_work(
        "deus", "That God Is Unchangeable", "Deus", SECTION,
        "Immut.", "Quod Deus Sit Immutabilis", "Quod Deus", "On the Unchangeableness of God",
    ), 2, 1, "da1161e257ad85a5fa632c24222afdbc02e75176", "8cd88c2e4a642b0396436c9e713aefa7437962fd"),
    "tlg009": _Treatise(_work(
        "agr", "On Husbandry", "Agr.", SECTION,
        "De Agricultura", "On Agriculture", "On the Tilling of the Earth by Noah",
    ), 2, 1, "5e2d269c1ed6a3b751caa2fbc6314a750a9c68fa", "537bd17198c72ef16772e9b21806a9acfea8daef"),
    "tlg010": _Treatise(_work(
        "plant", "On Planting", "Plant.", SECTION,
        "De Plantatione", "About the Planting of Noah",
    ), 2, 1, "ddcfea402c950cb8e1f20c9758e02f433cc19def", "1c1ea71fe92dcb86d62b94b77d5710f396a6f0cc"),
    "tlg011": _Treatise(_work(
        "ebr", "On Drunkenness", "Ebr.", SECTION, "De Ebrietate",
    ), 2, 1, "eb4ec505e23d7e653d575a1b2dda299d954e0dfd", "c36405035160c46140d33ce4751da2af82321dee"),
    "tlg012": _Treatise(_work(
        "sobr", "On Sobriety", "Sobr.", SECTION, "De Sobrietate",
    ), 2, 1, "0cd2f08c82b27c2f83f8254a015ed7020dfe2e37", "5bc42f04b49285c3989585b8cea187c90b92558e"),
    "tlg013": _Treatise(_work(
        "conf", "On the Confusion of Tongues", "Conf.", SECTION,
        "De Confusione Linguarum", "On the Confusion of Languages",
    ), 2, 2, "199cd189cf7240c2a26895e9d0f832473090e902", "d67082dff2489ad8c474d1f19ba9699a6d82eb02"),
    "tlg014": _Treatise(_work(
        "migr", "On the Migration of Abraham", "Migr.", SECTION, "De Migratione Abrahami",
    ), 2, 2, "173df5072b2861330127c222de077def7fe126b9", "3bbd34e4d23dcc5957f9ccea2143764f08e30500"),
    "tlg015": _Treatise(_work(
        "her", "Who Is the Heir of Divine Things", "Her.", SECTION,
        "Heres", "Quis Rerum Divinarum Heres Sit", "Quis Heres", "Who Is the Heir",
    ), 3, 2, "28c57047c296c7d4b4414edac98a9c70dd4b456c", "663dd6f76283d0a439686827e65491ee346228af"),
    "tlg016": _Treatise(_work(
        "congr", "On the Preliminary Studies", "Congr.", SECTION,
        "De Congressu Eruditionis Gratia", "De Congressu",
        "On Mating with the Preliminary Studies",
    ), 3, 2, "5a5119f86b370c1f371c51aea23793ee7d18c24c", "8c973f345703eb53fe507dc4c96fc366bd12da87"),
    "tlg017": _Treatise(_work(
        "fug", "On Flight and Finding", "Fug.", SECTION,
        "De Fuga et Inventione", "On Fugitives",
    ), 3, 2, "6ee7236ed82e176e96709422c7906e1c75635fa3", "ebca565728ef24074e635bd2697025c69c6d7276"),
    "tlg018": _Treatise(_work(
        "mut", "On the Change of Names", "Mut.", SECTION, "De Mutatione Nominum",
    ), 3, 2, "653fc764203903a0d1101ca505e86c593cb37ddb", "344d0a34becf1091feb2c784a03fab3d35a601eb"),
    "tlg019": _Treatise(_work(
        "somn", "On Dreams", "Somn.", BOOK_SECTION, "De Somniis",
    ), 3, 2, "15c00e63974400ece0f397415815eea6d7bf0004", "0bc625d520159f127e2186ee9b55d0bec8c15585"),
    "tlg020": _Treatise(_work(
        "abr", "On the Life of Abraham", "Abr.", SECTION, "De Abrahamo", "On Abraham",
        "Life of Abraham",
    ), 4, 2, "836febf10c95cf35a1232383c64e451963e36cec", "d46a29b2183893a32f8f6a8901cdfe1daefee15a"),
    "tlg021": _Treatise(_work(
        "ios", "On the Life of Joseph", "Ios.", SECTION, "De Iosepho", "De Josepho", "On Joseph",
        "Life of Joseph",
    ), 4, 2, "64f1cfbdd988bceb9cf6660c79558be725956353", "8ae067b74c574d1afbee839ec03908f5afbc9e85"),
    "tlg022": _Treatise(_work(
        "mos", "On the Life of Moses", "Mos.", BOOK_SECTION, "Vit. Mos.", "De Vita Mosis",
        "Life of Moses",
    ), 4, 3, "a8b460b9ef0ef9e1d6b490de88faae3308afc9cc", "f93c43182be0a148df79a0d8d20e0da9e81a0ac3"),
    "tlg023": _Treatise(_work(
        "decal", "On the Decalogue", "Decal.", SECTION,
        "De Decalogo", "Concerning the Ten Commandments",
    ), 4, 3, "826af0566f41e2d6e09b0816e9bfed9218e69fef", "04fc44754d05b0ce8d0a07baffd0d4274643f374"),
    "tlg024": _Treatise(_work(
        "spec", "On the Special Laws", "Spec.", BOOK_SECTION,
        "Spec. Leg.", "De Specialibus Legibus",
    ), 5, 3, "71fd30b794537115bef26800f6ba9c40144afb60", "aa49c1a1592c72c487b4baf216f4cb0f305c97b7"),
    "tlg025": _Treatise(_work(
        "virt", "On the Virtues", "Virt.", SECTION, "De Virtutibus", "On Three Virtues",
    ), 5, 3, "ba1f99a2aa2713ae5964922268ef15d93db9d9bf", "4feac4d5d0af9697053b78c0b384f3eedffb850f"),
    "tlg026": _Treatise(_work(
        "praem", "On Rewards and Punishments", "Praem.", SECTION, "De Praemiis et Poenis",
    ), 5, 3, "ecb5fe46d2de092ae2f9c49b94237ff4c7358780", "37c5655a3109d9c68f542623b4eff76fc7ff7a07"),
    "tlg027": _Treatise(_work(
        "prob", "That Every Good Person Is Free", "Prob.", SECTION,
        "Quod Omnis Probus Liber Sit", "Quod Omnis Probus",
        "That Every Good Man Is Free", "Every Good Man Is Free",
    ), 6, 3, "b3bdc823e09056f7c4d06affb6e18a9a5bfc132e", "da5e62e52aa2ae55a4562520ff9832f4ae9f6e4b"),
    "tlg028": _Treatise(_work(
        "contempl", "On the Contemplative Life", "Contempl.", SECTION,
        "Vit. Cont.", "De Vita Contemplativa", "Contemplative Life",
    ), 6, 4, "8348e0e8385cfbc4b5d69281c5a9bf1924d076fb", "39bf58263b806c8e223fc60e7fec7c42aa73d9bd"),
    "tlg029": _Treatise(_work(
        "aet", "On the Eternity of the World", "Aet.", SECTION,
        "De Aeternitate Mundi", "On the Incorruptibility of the World",
    ), 6, 4, "405eb25172b7426c2141ff88754fd02f707ea882", "e874d4429566ad53ff2591cfb6ccaf3ead0202c2"),
    "tlg030": _Treatise(_work(
        "flacc", "Against Flaccus", "Flacc.", SECTION, "In Flaccum",
    ), 6, 4, "d7282f3178708c88c915c3a882d7f8a0fa80eb8c", "c63fc4a2dc5c5c3fb3bc321e54587a7fb57c768d"),
    "tlg031": _Treatise(_work(
        "legat", "On the Embassy to Gaius", "Legat.", SECTION,
        "Leg. Gai.", "Legatio ad Gaium", "Embassy to Gaius",
    ), 6, 4, "28d22f45e3da408abcb6f1a0b38ef7717ee3b799", "521fb341090d2446cd732c9f71bd7640dc44161d"),
}
WORKS = {work_id: treatise.work for work_id, treatise in TREATISES.items()}

# Editorial links, separate from Philo's text: each names the biblical passage a
# treatise section quotes and expounds, or the account it retells. They assert
# no dependence or historicity. Fields: work_key, Cohn–Wendland locator,
# biblical book, chapter, verse, end chapter, end verse, note. The comment on
# each entry quotes what was verified in the pinned Yonge text of that section.
_BIBLICAL_LINKS = (
    ("opif", "26", "Gen", 1, 1, 1, 1, "Quotes and expounds: the creation of heaven and earth"),  # "In the beginning God created the heaven and the earth"
    ("opif", "134", "Gen", 2, 7, 2, 7, "Quotes and expounds: the forming of man from clay"),  # "God made man, having taken clay from the earth, and he breathed into his face"
    ("leg", "1.1", "Gen", 2, 1, 2, 1, "Quotes and expounds: the completion of heaven and earth"),  # "And the heaven and the earth and all their world was completed"
    ("leg", "1.31", "Gen", 2, 7, 2, 7, "Quotes and expounds: the forming of man from clay"),  # "God created man, taking a lump of clay from the earth"
    ("cher", "1", "Gen", 3, 24, 3, 24, "Quotes and expounds: the cherubim and the flaming sword"),  # "God cast out Adam ... the cherubim and a flaming sword"
    ("sacr", "1", "Gen", 4, 2, 4, 2, "Quotes and expounds: the birth of Abel"),  # "she should bring forth his brother"
    ("det", "1", "Gen", 4, 8, 4, 8, "Quotes and expounds: Cain and Abel in the field"),  # "Let us go to the field ... slew him"
    ("post", "1", "Gen", 4, 16, 4, 16, "Quotes and expounds: Cain dwelling in the land of Nod"),  # "Cain went out from before the face of God, and dwelt in the land of Nod"
    ("gig", "6", "Gen", 6, 2, 6, 2, "Quotes and expounds: the angels of God and the daughters of men"),  # "when the angels of God saw the daughters of men"
    ("deus", "1", "Gen", 6, 4, 6, 4, "Quotes and expounds: the angels of God and the daughters of men"),  # "the angels of God went in unto the daughters of men"
    ("agr", "1", "Gen", 9, 20, 9, 21, "Quotes and expounds: Noah the husbandman and his vineyard"),  # "Noah began to be a husbandman; and he planted a vineyard"
    ("sobr", "1", "Gen", 9, 24, 9, 24, "Quotes and expounds: Noah awaking from his wine"),  # "And Noah awoke from his wine"
    ("conf", "1", "Gen", 11, 1, 11, 9, "Quotes and expounds: the confusion of languages"),  # "And all the earth had one pronunciation"
    ("migr", "1", "Gen", 12, 1, 12, 3, "Quotes and expounds: the call of Abraham"),  # "Depart from thy land, and from thy kindred"
    ("her", "2", "Gen", 15, 1, 15, 3, "Quotes and expounds: Abraham's question about his heir"),  # "Thy reward is exceedingly great ... this Eliezer of Damascus"
    ("congr", "1", "Gen", 16, 1, 16, 2, "Quotes and expounds: Sarah gives Hagar to Abraham"),  # "she had an Egyptian handmaiden, whose name was Hagar"
    ("fug", "1", "Gen", 16, 6, 16, 8, "Quotes and expounds: Hagar's flight and the angel at the fountain"),  # "Sarah afflicted her, and she fled ... the way to Shur"
    ("mut", "1", "Gen", 17, 1, 17, 1, "Quotes and expounds: the Lord appears to Abraham at ninety-nine"),  # "Abraham was ninety and nine years old; and the Lord appeared"
    ("somn", "1.3", "Gen", 28, 12, 28, 13, "Quotes and expounds: Jacob's dream of the ladder"),  # "Jacob dreamed, and behold a ladder was firmly planted on the earth"
    ("somn", "2.6", "Gen", 37, 7, 37, 7, "Quotes and expounds: Joseph's dream of the sheaves"),  # "the first dreams are those which Joseph beheld ... binding sheaves"
    ("abr", "107", "Gen", 18, 1, 18, 8, "Retells: Abraham's hospitality to three travellers"),  # "beholding as it were three men travelling"
    ("mos", "1.65", "Exo", 3, 1, 3, 3, "Retells: Moses and the burning bush"),  # "leading his flock ... There was a bush or briar"
    ("decal", "50", "Exo", 20, 1, 20, 17, "Expounds: the ten commandments on two tables"),  # "God divided them, being ten ... into two tables of five each"
    ("spec", "1.2", "Gen", 17, 10, 17, 14, "Expounds: the ordinance of circumcision"),  # "The ordinance of circumcision ... is ridiculed"
    ("legat", "299", "Luk", 3, 1, 3, 1, "Related figure: Pilate, governor of Judaea"),  # "Pilate was one of the emperor's lieutenants, having been appointed governor of Judaea"
)

_NS = {"tei": "http://www.tei-c.org/ns/1.0"}
_TEI = "{http://www.tei-c.org/ns/1.0}"
# Apparatus, page/line markers, headings and Yonge's source references never
# enter the passage text.
_SKIP_TEXT_ELEMENTS = {"note", "pb", "lb", "head", "milestone", "bibl"}


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _source_text(element: ET.Element) -> str:
    """Element text without editorial children, with whitespace collapsed."""
    parts: list[str] = []

    def visit(node: ET.Element) -> None:
        if node.text:
            parts.append(node.text)
        for child in node:
            if _local_name(child.tag) not in _SKIP_TEXT_ELEMENTS:
                visit(child)
            if child.tail:
                parts.append(child.tail)

    visit(element)
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def _head_text(element: ET.Element) -> str:
    return re.sub(r"\s+", " ", "".join(element.itertext())).strip()


def _validate_license(root: ET.Element, path: Path) -> None:
    targets = [node.attrib.get("target", "") for node in root.iter(f"{_TEI}licence")]
    if not any("creativecommons.org/licenses/by-sa/4.0" in target for target in targets):
        raise ValueError(f"Expected CC BY-SA 4.0 license metadata in {path}")


def _sections(path: Path, has_books: bool) -> list[dict]:
    """Sections in document order: book (None without books), number, element, book heading."""
    root = ET.parse(path).getroot()
    _validate_license(root, path)
    body = root.find(".//tei:body", _NS)
    if body is None:
        raise ValueError(f"{path.name}: no TEI body")
    sections: list[dict] = []

    def walk(node: ET.Element, book: int | None, book_heading: list[str]) -> None:
        for child in node:
            if _local_name(child.tag) != "div":
                continue
            subtype = child.attrib.get("subtype")
            if subtype == "book":
                if not has_books:
                    raise ValueError(f"{path.name}: unexpected book division")
                headings = [_head_text(head) for head in child.findall("tei:head", _NS)]
                walk(child, int(child.attrib["n"]), [h for h in headings if h])
            elif subtype == "section":
                label = child.attrib.get("n", "")
                if not label.isdigit():
                    raise ValueError(f"{path.name}: unexpected section label {label!r}")
                if has_books and book is None:
                    raise ValueError(f"{path.name}: section {label} outside a book")
                sections.append({
                    "book": book, "section": int(label), "element": child,
                    "book_heading": book_heading,
                })
                book_heading = []
            else:
                walk(child, book, book_heading)

    walk(body, None, [])
    seen: set[tuple] = set()
    previous: dict[int | None, int] = {}
    for item in sections:
        key = (item["book"], item["section"])
        if key in seen:
            raise ValueError(f"{path.name}: duplicate section {key}")
        if item["section"] <= previous.get(item["book"], 0):
            raise ValueError(f"{path.name}: section {key} is out of order")
        seen.add(key)
        previous[item["book"]] = item["section"]
    if not sections:
        raise ValueError(f"{path.name}: no sections")
    return sections


def _greek_name(work_id: str) -> str:
    return f"tlg0018.{work_id}.1st1K-grc1.xml"


def _english_name(work_id: str) -> str:
    return f"tlg0018.{work_id}.1st1K-eng1.xml"


def parse_philo_work(directory: Path, work_id: str) -> list[dict]:
    """One passage per Cohn–Wendland section, pairing its Greek with Yonge's English.

    Both TEI files are divided at the same Cohn–Wendland sections (the English
    was realigned to them by the First1KGreek editors), so each passage pairs
    exactly one Greek section with the English section of the same number.
    Greek sections Yonge's text lacks (parts of Spec. 1–2) become Greek-only
    passages. An English section with no Greek counterpart fails the parse.
    """
    treatise = TREATISES[work_id]
    work = treatise.work
    has_books = work.locator is BOOK_SECTION
    greek = _sections(directory / _greek_name(work_id), has_books)
    english = {
        (item["book"], item["section"]): item
        for item in _sections(directory / _english_name(work_id), has_books)
    }
    unpaired = sorted(set(english) - {(item["book"], item["section"]) for item in greek})
    if unpaired:
        raise ValueError(f"{work_id}: English sections {unpaired} have no Greek section")

    edition = (
        f"Cohn–Wendland, Philonis Alexandrini opera quae supersunt, vol. {treatise.cw_volume} "
        f"(Berlin: Reimer, {_CW_YEARS[treatise.cw_volume]})"
    )
    translation = (
        f"C. D. Yonge, The Works of Philo Judaeus, vol. {treatise.yonge_volume} "
        f"(London: Bohn, {_YONGE_YEARS[treatise.yonge_volume]})"
    )
    rows: list[dict] = []
    for item in greek:
        book, section = item["book"], item["section"]
        greek_text = _source_text(item["element"])
        if not greek_text:
            raise ValueError(f"{work_id} {book}.{section}: empty Greek section")
        row = {
            "author": AUTHOR,
            "work_key": work.key,
            "reference": (
                f"{work.reference_title} {book}.{section}" if has_books
                else f"{work.reference_title} {section}"
            ),
            "sort_start": work.locator.key(book, section) if has_books else work.locator.key(section),
            "period_tags": _PERIOD_TAGS,
            "edition": edition,
            "original_text": greek_text,
            "original_language": ORIGINAL_LANGUAGE,
            "original_license": LICENSE,
            "license": LICENSE,
            "source_url": f"{_TREE_BASE}/{work_id}",
        }
        row["sort_end"] = row["sort_start"]
        paired = english.get((book, section))
        if paired is not None:
            english_text = _source_text(paired["element"])
            if not english_text:
                raise ValueError(f"{work_id} {book}.{section}: empty English section")
            headings = paired["book_heading"] + [
                _head_text(head) for head in paired["element"].findall("tei:head", _NS)
            ]
            row.update({
                "text": english_text,
                "translation": translation,
                "translation_license": LICENSE,
                "license": combined_license(LICENSE, LICENSE, ORIGINAL_LANGUAGE),
                "editorial_heading": " ".join(h for h in headings if h) or None,
            })
        rows.append(row)
    return rows


def parse(directory: Path) -> list[dict]:
    return [row for work_id in TREATISES for row in parse_philo_work(directory, work_id)]


def biblical_links(passages: list[dict]) -> list[BiblicalLink]:
    return [
        BiblicalLink(work_key, locator, book, c1, v1, c2, v2, note)
        for work_key, locator, book, c1, v1, c2, v2, note in _BIBLICAL_LINKS
    ]


PHILO_TEI_FILES = tuple(
    name for work_id in TREATISES for name in (_greek_name(work_id), _english_name(work_id))
)


def require_philo_files(directory: Path) -> None:
    """Raise unless the Greek and English TEI of all 31 treatises are present."""
    missing = [name for name in PHILO_TEI_FILES if not (directory / name).is_file()]
    if missing:
        raise FileNotFoundError(
            f"Philo sources in {directory} are incomplete; missing {', '.join(missing)}. "
            "Run python scripts/download_ancient_sources.py."
        )


def download(client: httpx.Client, target: Path, force: bool) -> dict:
    """Fetch each treatise's Greek and English TEI at COMMIT, verified by Git blob hash.

    The blob hashes are pinned here, so present files are verified without any
    GitHub API request (the unauthenticated API allows 60 requests an hour).
    """
    files: dict[str, dict] = {}
    for work_id, treatise in TREATISES.items():
        for name, blob in (
            (_greek_name(work_id), treatise.greek_blob),
            (_english_name(work_id), treatise.english_blob),
        ):
            content = fetch_verified(
                client, f"{_RAW_BASE}/{work_id}/{name}", target / name, blob, force, git_blob_sha1
            )
            if b"creativecommons.org/licenses/by-sa/4.0/" not in content:
                (target / name).unlink(missing_ok=True)
                raise RuntimeError(f"Missing expected CC BY-SA 4.0 declaration in {name}")
            files[name] = {
                "git_blob_sha1": blob,
                "bytes": len(content),
                "source_url": f"https://github.com/{REPOSITORY}/blob/{COMMIT}/data/tlg0018/{work_id}/{name}",
            }
    return {"repository": REPOSITORY, "commit": COMMIT, "license": LICENSE, "files": files}


CORPUS = Corpus(
    key="philo",
    label="Philo",
    summary=(
        "Philo of Alexandria: the 31 Greek treatises of the Cohn–Wendland edition "
        "(Opif. through Legat.) from First1KGreek, each Cohn–Wendland section paired "
        "with the same section of C. D. Yonge's English translation. Cited by SBL short "
        "title and section ('Opif. 26'; multi-book works by book.section: 'Leg. 1.31', "
        "'Somn. 1.3', 'Mos. 1.65', 'Spec. 1.2'); sections Yonge's text lacks are Greek only."
    ),
    data_dir="philo",
    original_language=ORIGINAL_LANGUAGE,
    works=tuple(WORKS.values()),
    periods=PERIODS,
    download=download,
    require_files=require_philo_files,
    parse=parse,
    biblical_links=biblical_links,
    example_query="divine word",
    example_citation="Opif. 26",
    aliases=("Philo of Alexandria", "Philo Judaeus", "Philo"),
    heading_label="Yonge treatise heading",
    tag=TAG,
    caveat=CAVEAT,
)
