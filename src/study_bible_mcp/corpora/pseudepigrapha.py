"""Pseudepigrapha corpus: 1 Enoch (Charles) and 4 Ezra (KJV 2 Esdras 3–14 with the Clementine Latin)."""

from __future__ import annotations

import hashlib
import io
import re
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

from .base import BiblicalLink, Corpus, SourceTag, TagSection, Work, combined_license
from .download import sha256_hex
from .locators import CHAPTER_VERSE

if TYPE_CHECKING:
    import httpx


PUBLIC_DOMAIN = "Public domain"
WIKISOURCE_LICENSE = "CC BY-SA 4.0"
PERIODS = ("second_temple", "hellenistic", "roman")

CAVEAT = (
    "Not Scripture: pseudepigrapha outside the 66-book canon; background only, never a "
    "basis for doctrine. Jude 14–15 quotes 1 Enoch 1:9 without making the book Scripture."
)

ENOCH = Work(
    key="1_enoch",
    title="1 Enoch",
    reference_title="1 Enoch",
    locator=CHAPTER_VERSE,
    aliases=("1 En.", "Ethiopic Enoch", "Book of Enoch", "Ethiopic Apocalypse of Enoch"),
    # Book dates follow the canon review's date ladder (Watchers, Parables)
    # and the conventional dating of the other books.
    tag=SourceTag(
        kind="Jewish pseudepigraphon", date="c. 300 BC–1st c. AD", tier="A/B",
        edition="Charles 1912",
        sections=(
            TagSection("1-36", "Book of the Watchers", "4th–3rd c. BC", "A"),
            TagSection("37-71", "Parables", "c. 50 BC–AD 117, debated", "A/B"),
            TagSection("72-82", "Astronomical Book", "3rd c. BC", "A"),
            TagSection("83-90", "Dream Visions", "c. 165–160 BC", "A"),
            TagSection("91-107", "Epistle of Enoch", "2nd c. BC", "A"),
            TagSection("108", "appendix", "late addition, date uncertain", "A/B"),
        ),
    ),
)
EZRA = Work(
    key="4_ezra",
    title="4 Ezra",
    reference_title="4 Ezra",
    locator=CHAPTER_VERSE,
    aliases=("4 Ezr.", "2 Esdras", "2 Esd.", "4 Esdras", "4 Esd."),
    tag=SourceTag(
        kind="Jewish apocalypse, 2 Esd 3–14", date="c. AD 100", tier="B",
        edition="KJV 2 Esdras, Clementine Latin",
    ),
    coverage_note=(
        "Only 4 Ezra (2 Esdras 3–14) is served: 2 Esdras 1–2 and 15–16, the later "
        "Christian additions (5 and 6 Ezra), are excluded, and the KJV and Latin lack "
        "4 Ezra 7:36–105 (the 'missing fragment', published by Bensly in 1875)."
    ),
)

# --- 1 Enoch: R. H. Charles's translation on English Wikisource, one page per chapter.

_ENOCH_API = "https://en.wikisource.org/w/api.php"
_ENOCH_PAGE = "The_Book_of_Enoch_(Charles)/Chapter_{chapter:02d}"
ENOCH_TRANSLATION = (
    "R. H. Charles, The Book of Enoch (2nd ed., Oxford 1912; SPCK reprint 1917), "
    "English Wikisource"
)
ENOCH_EDITION = (
    "Translated from R. H. Charles, The Ethiopic Version of the Book of Enoch (Oxford, 1906); "
    "no openly licensed Ge'ez text is included"
)
# Chapter -> (Wikisource revision id, SHA-1 of the revision's wikitext). The
# index page carries {{PD/US|1931}}: Charles died in 1931 and the translation
# was published before 1931, so it is in the public domain in the United States.
ENOCH_REVISIONS = {
    1: (13274564, "34169eac6d5c5c44550fe833e69f3a678bbd42b6"),
    2: (13274151, "87d30bdb13475fa9ff838e4d57d952a6cb6041da"),
    3: (7211018, "55cf44a20d89dc87a42f07878fbe433bf58ec1e3"),
    4: (7211020, "0aa2b8c2d667f5b1a966cba54711f827144043f3"),
    5: (13274421, "00688fb320675de831f7eb35189d43fcb38448b7"),
    6: (13274565, "776544c7643688803790c33ca18d141064e85c65"),
    7: (13274566, "cd8c4ad3c7c1f4c865d6088501a260b5b0c872a4"),
    8: (13274567, "354916f3bce0b010721ae3fffeb8919ae48e6636"),
    9: (13274568, "c1cc927f988878a922007c453da991ed714955a1"),
    10: (13274569, "98976ceb6940620eb9d03d275459e867ba634491"),
    11: (13274570, "60ff91cc703b3881116b77f933e002489756794f"),
    12: (13274173, "fd9b20c8c8df6e51a547f17cadd62dca6d29452b"),
    13: (13274571, "0da142f49c02be8f83abcb9eb427ddf1fb7d256d"),
    14: (13274572, "fbed9c68ea583536aedd379aa2ba3a2b8bbcb766"),
    15: (13274573, "665d92868418de0a911d860d92dcf8b3d691dcb6"),
    16: (13274574, "e8a8dadbf779f5665279381ce2f98f90af32f579"),
    17: (13271602, "5429b6ea0c122459abfb85f86a9fe8ddbe345f67"),
    18: (13273855, "99b861f6c8bbb53cd8178dfda723db23c9ff0a46"),
    19: (13274575, "5d7654f1428faaf552af34ee7892632385cd4da3"),
    20: (13274582, "c5e15545f04c68fcd92de3f6808d620cf0d82eb7"),
    21: (13274584, "236284ca42859e05f3a029c403f5cf89ca4694b4"),
    22: (13274585, "7a78b997bd62cc77df4dba29e767e01826392afd"),
    23: (13274586, "337d444dc986f570852044598e48dea98065e99e"),
    24: (13274587, "91502a84bce212a1c6c0891268ae591233d86f4f"),
    25: (13274588, "fefc69c3e015f0ff01608772353caff851fe1426"),
    26: (13274589, "25431cf75570d2f5a3804cadc5233b47a06c9a27"),
    27: (13274590, "05e0fd7eb9a17684cba4b6667e86d4ec4eb7cca2"),
    28: (13267717, "612ed3532c97591dfceeb3942417552624ceac54"),
    29: (13274591, "2254d825e47ce6205356c9776441a650221a9b62"),
    30: (13267719, "c178dd2e4149ebb62958fb5174ea3ab365c853bb"),
    31: (13274592, "330f6405afad6c359eacda959f61a7553c30dab3"),
    32: (13274444, "247aa6c1d679f93b0868d66f45383a1b8f8ddc81"),
    33: (9155116, "9240c1c66a3de31b18ae43764c3e1bd1346b17b6"),
    34: (13272348, "134e9c47a2bc808a445436709d7c482d676a973d"),
    35: (6077020, "4811418606bb3a733e6c22c92014780fc370ac48"),
    36: (9155104, "0d96b5eae0485d81e11e0da2d3335488cd898000"),
    37: (13272350, "fa42e14d4de3bd04626182dfe2d9d43497605a64"),
    38: (13274594, "717cc4e0b697c64a8402cb13701d62748e03fb96"),
    39: (13274450, "9667f4f54f251aeb97a9f38e08b5315b1a22cac1"),
    40: (13273907, "e0a3e7a522bc4a7f44ea2b356fba77c0b0440ae1"),
    41: (13274451, "9dc089ca154de44a2101b27ddc059ea5048feef5"),
    42: (13274453, "36604f8741791451b540d6cf12090a5a5d6d4581"),
    43: (13272653, "1af64ea88f00cbca71b3d2d1fcfda02cd8deb9c6"),
    44: (13267958, "73218fea741ac539c3936523f1c8ed9fd24d0720"),
    45: (13274456, "51ee149e83f02087887cf57a5d33af7a4ef4d79f"),
    46: (13274459, "9982c4993f492b1aa50e7514e19e95958d773c29"),
    47: (13274462, "ba59e7b6d1c51daefec17cdb5dbe3f15f7efcb9f"),
    48: (13274464, "2c2fe2e507c4d242bb107e9d286633bc652dc977"),
    49: (9155277, "70d62f2a6e4e39a156ca404718e6521c22b8d501"),
    50: (13274465, "c4571e679a2b06270b39f8d9f62d02fa96804efd"),
    51: (13274467, "d5ae6f07bf17849f20a59083e38ea948dca91073"),
    52: (13273919, "1c20d73f67083019d0dabb9acb5dab9b1b72529e"),
    53: (13273921, "8742e2fa2e5c40d6f50b280d0b8f57479cec23d2"),
    54: (13272706, "f451ffc090af8c4ed8c5b7d033d16a8b5b540787"),
    55: (13272708, "19bd581ec72baa1c11051addccc2eb14454083e5"),
    56: (13274471, "41d9400154d7ed32ba0cb63b90373025184664bf"),
    57: (13268064, "e4d637fa06017c3263683f97b333a3e113cf25c1"),
    58: (13274472, "55394912b47df41a188b99ae480339d333882adb"),
    59: (13274604, "5509a035eba0d7533404b79c242b9391b01d2c68"),
    60: (13274475, "3ab6b807502bb1a90c8299544ce062faabaeccab"),
    61: (13274477, "b4e51bf5497b45ab41b7c57314c74b63245144c5"),
    62: (13274479, "6848cf0ec75f1c536c44813deab0fa45a075a777"),
    63: (13268124, "bd3a843d06ff3f2c5e7cc76fe4a91553258e84e3"),
    64: (9155183, "eff16cc44bf242ffa9365158dbeb2c13a4a81962"),
    65: (13274481, "6bd941741484507e365a0f7a1e51cea0dcee1b14"),
    66: (9155186, "9f05e78f1b7d85c6f69956ca6cb2734e0d3e7af5"),
    67: (13273929, "31759ff5eac2ebae4808030cd4c196d8d5dd225a"),
    68: (13268155, "b592012e043df983bb6d6e3abeb1bb01334442c4"),
    69: (13284527, "421d39f4cb92d0f642543bf0f296a19745bcbc65"),
    70: (9155190, "100c907669ef794837dcb77263d2b165da1020a5"),
    71: (13274487, "6ed1d1957e38fcf5c3b344ad0fcd00be541d835c"),
    72: (13273951, "3c36da812d516dafb1a9f5bd31c74a00e5a301fe"),
    73: (9155196, "de9fc963318a9da22b6096b687ff5f617597b1fe"),
    74: (13273677, "3835296550dfaf78f3b77bdef904bdfc081fb94f"),
    75: (13273679, "cfdb33152e702cb37ea25d26deec4a3e36d0cb90"),
    76: (13268197, "4a40dcf75a3cacab230abbbd896d72baa1053141"),
    77: (13268198, "9988bba2c2636435c5a23755d34c38a7c30bcd18"),
    78: (13268203, "66dc2519a16e7db773d9ddcd82c07a947f190b4a"),
    79: (13273687, "b51c161372bc6337c9deaf9d003cef32ac85a19f"),
    80: (13274497, "e12cb10a37d7e28b9e4f16a9080876af9130636a"),
    81: (13274500, "96e4d998e0ca63029b74605cfe75c46217bf1797"),
    82: (13274503, "c9b51ac024add155939ce887f8d72eee4835ff63"),
    83: (13273699, "cc8bba100f3f8a889c8fc314309eb29897eae75c"),
    84: (13274505, "745a4eff6b8d07c68f4b5e6361539b2492d5c844"),
    85: (13268576, "ae8ed9bae0ac30b2e64c98bb7be010433b756151"),
    86: (13268578, "2c54c8599bb53dbb6aad63930c0f8f60370dd678"),
    87: (13273704, "272918e88b0a633789f32a675a84672f76f99d1c"),
    88: (13268579, "888656dd8c04dc0a7b12da07a20179e783307bad"),
    89: (13274793, "b85560ef1ddd1e756386f10ae73ab40313b0a631"),
    90: (13274795, "e4ace9f127240eb0b73bbfb646ab31e24469540b"),
    91: (13274537, "62af3b78dc5fcab003bde68cf9e01fc108396f28"),
    92: (13274530, "2f92f7eefc7b728a85b9760546da502ed3fe4763"),
    93: (13274534, "0a44cea9c91dfac64c2a55b7f38678cc97376385"),
    94: (13273972, "df8f99f0a2773590a28fb0ba40e16247788bd9bc"),
    95: (13274539, "fe17aa3abac919447efcd0cd11c1196d1638e22e"),
    96: (13274597, "57a4474033a6c1b49e1c7c905c9703d24dce4bc2"),
    97: (13274542, "605c682f4578e4628ebc3ffdbacafcef3cbd1d9d"),
    98: (13274545, "c5610bb14facefce49bd495b17d388cd1bef48af"),
    99: (13274549, "202f9708bb80604f06a53cf9bc7e8c057fdd4630"),
    100: (13274550, "e77a1fb3215a1e0e7a22ad56e97fec76a6d4ec80"),
    101: (13274551, "0d1ae0623fa44401f04753c13daec12e6a668523"),
    102: (13274553, "861d9855f4c4b64f52f71ace7743503e36fbc994"),
    103: (13274555, "b219f309ababc619d05b4561ca4aca07cabca617"),
    104: (13273775, "1fc116870bc81310e6938c7d04bd1ad0836453a5"),
    105: (13273779, "b645504154e2b2201fa4581ebb430693aefb99be"),
    106: (13274813, "e860c10bd1194bcac42649a458f2a946e8b2253d"),
    107: (13268718, "1302bddfe4c21b9615e696d57e992e33ffa37954"),
    108: (13273788, "25a922cf3e2c40d50c83efe1f737c99948a85e0e"),
}

# Numbers in running text that the verse-marker pattern would otherwise take
# for verses: 74:16 "falls behind in 8 years are 80. 17. And ...".
_ENOCH_FALSE_MARKERS = {(74, "80")}

# Conventional composition dating of the five books of 1 Enoch (editorial).
_ENOCH_PERIODS = (
    (36, "second_temple,hellenistic"),   # Book of the Watchers, 1–36
    (71, "second_temple,roman"),         # Parables (Similitudes), 37–71
    (82, "second_temple,hellenistic"),   # Astronomical Book, 72–82
    (90, "second_temple,hellenistic"),   # Dream Visions, incl. the Animal Apocalypse, 83–90
    (107, "second_temple,hellenistic"),  # Epistle of Enoch and the birth of Noah, 91–107
    (108, "second_temple"),              # Concluding appendix, 108
)

_VERSE_MARKER = re.compile(r"(?:(?<=^)|(?<=[\s‘“'\"(\[⌈〈]))(\d{1,3})([a-j]?)\.(?=\s)", re.M)
_SUB_VERSE = re.compile(r"(?:^|(?<=\s))([a-j])\.\s", re.M)
_HEADING = re.compile(r"^=+\s*(.*?)\s*=+\s*$")
_CHAPTER_LINE = re.compile(r"^\s*CHAPTER [IVXLC]+\.?\s*$")

# --- 4 Ezra: KJV 2 Esdras 3–14 (eBible eng-kjv) with the Clementine Latin (Latin Wikisource).

KJV_ZIP_URL = "https://ebible.org/Scriptures/eng-kjv_usfm.zip"
KJV_PAGE_URL = "https://ebible.org/find/show.php?id=eng-kjv"
KJV_FILE = "58-2ESeng-kjv.usfm"
# eBible regenerates the unversioned zip, so pin the extracted book file instead.
KJV_SHA256 = "10a448ea0ede1240b8d2473627db09dde806df080dca5a180978fa2b99ac4ef8"
KJV_TRANSLATION = (
    "King James Version with Apocrypha, 2 Esdras (1611; standard text of 1769), "
    "eBible.org eng-kjv"
)
LATIN_FILE = "vulgata_clementina_liber_quartus_esdrae.wiki"
LATIN_REVISION = 148869
LATIN_SHA1 = "d6aaad12fa739ce789e3ea0d1e43631cb91eaa80"
LATIN_URL = (
    "https://la.wikisource.org/w/index.php?title=Vulgata_Clementina/Liber_Quartus_Esdrae"
    f"&oldid={LATIN_REVISION}"
)
# The Latin Wikisource transcription is CC BY-SA: its URL is part of the
# edition so the Sources block of every response credits it.
LATIN_EDITION = (
    "Vulgata Clementina (Rome, 1598), Liber Quartus Esdrae, "
    f"Latin Wikisource revision {LATIN_REVISION} ({LATIN_URL})"
)
EZRA_PERIODS = "roman"  # Composed c. 100 CE, after the destruction of 70 CE (editorial).
EZRA_CHAPTERS = range(3, 15)

# 4 Ezra 3–14 is 2 Esdras 3–14 with the same chapter numbers (2 Esdras 1–2 and
# 15–16 are the later Christian additions known as 5 and 6 Ezra). Both the KJV
# and the Clementine Latin lack the 'missing fragment', 4 Ezra 7:36–105, so
# their 7:36–70 is 7:106–140 in the numbering of Bensly's edition and modern
# translations; passages are cited in that numbering, with the KJV verse as
# the alternate reference.
MISSING_FRAGMENT = (36, 105)
_FRAGMENT_OFFSET = MISSING_FRAGMENT[1] - MISSING_FRAGMENT[0] + 1

# KJV verse spans (KJV numbering) whose Latin verse division differs: each span
# is one passage pairing all of its English verses with all of its Latin
# verses. Each was checked by reading both pinned texts; most move a speech
# introduction ('Et dixit ad me,' / 'And he said unto me') across a boundary.
_EZRA_ALIGNED_SPANS = (
    (3, 3, 4), (3, 15, 16), (5, 55, 56), (7, 45, 46), (7, 53, 54), (7, 69, 70),
    (8, 19, 20), (9, 11, 12), (9, 16, 17), (9, 29, 30), (9, 39, 43), (10, 13, 14),
    (10, 17, 18), (10, 26, 27), (10, 31, 34), (10, 37, 38),
    (12, 9, 10), (12, 17, 18), (12, 19, 20), (12, 22, 23), (13, 10, 11),
    (13, 37, 38), (13, 51, 52), (14, 1, 3), (14, 14, 20), (14, 42, 43), (14, 47, 48),
)

# Editorial links, separate from the texts. They name narrative overlaps and
# shared imagery, not dependence or historicity. Fields: work_key, locator,
# biblical book, chapter, verse, end chapter, end verse, note, and optionally
# the relation (else derived from the note: corpora.base.default_link_relation).
# 'aligned' marks the passages the Bible itself takes up (Jude 14–15; Gen 6),
# pairing the pseudepigraphon with Scripture as David's rule requires. The
# comment on each entry quotes what was verified in the pinned text.
_BIBLICAL_LINKS = (
    ("1_enoch", "1:9", "Jud", 1, 14, 1, 15, "Related text: Jude 14–15 cites a prophecy of Enoch in closely similar words", "aligned"),  # "He cometh with ten thousands of His holy ones To execute judgement upon all"
    ("1_enoch", "6:1", "Gen", 6, 1, 6, 2, "Narrative overlap: the children of heaven and the daughters of men", "aligned"),  # 6:1 "beautiful and comely daughters"; 6:2 "the angels, the children of the heaven, saw and lusted"
    ("1_enoch", "10:4", "Lev", 16, 8, 16, 10, "Shared name: Azazel"),  # "Bind Azâzêl hand and foot, and cast him into the darkness"
    ("1_enoch", "46:1", "Dan", 7, 9, 7, 13, "Related imagery: one with a head of days, white like wool, and one with the appearance of a man", "echo"),  # "a head of days ... white like wool ... the appearance of a man"
    ("1_enoch", "89:1", "Gen", 6, 13, 8, 19, "Allegorical retelling: Noah's vessel and the flood"),  # white bull "became a man, and built for himself a great vessel"
    ("1_enoch", "89:12", "Gen", 25, 21, 25, 26, "Allegorical retelling: a boar and a sheep, conventionally read as Esau and Jacob"),  # "begat a black wild boar and a white sheep"
    ("1_enoch", "89:13", "Gen", 37, 25, 37, 28, "Allegorical retelling: one of the twelve given up and taken to Egypt, conventionally read as Joseph"),  # "they gave up one of them to the asses ... gave up that sheep to the wolves"
    ("1_enoch", "89:15", "Exo", 1, 8, 1, 22, "Allegorical retelling: oppression and the young cast into the river"),  # "they cast their young into a river of much water"
    ("1_enoch", "89:24", "Exo", 14, 21, 14, 29, "Allegorical retelling: the dividing of the sea"),  # "that sea was divided, and the water stood on this side and on that"
    ("1_enoch", "89:32", "Exo", 32, 1, 32, 8, "Allegorical retelling: the flock strays while its leader is on the summit"),  # "ascended to the summit of that rock, but the sheep began to be blinded"
    ("1_enoch", "89:50", "1Ki", 6, 1, 6, 38, "Allegorical retelling: a tower built on the house, read as the temple"),  # "a tower lofty and great was built on the house for the Lord of the sheep"
    ("1_enoch", "89:66", "2Ki", 25, 8, 25, 10, "Allegorical retelling: the tower burnt and the house demolished"),  # "they burnt that tower and demolished that house"
    ("1_enoch", "89:72", "Ezr", 3, 8, 4, 5, "Allegorical retelling: three return to rebuild the house and are opposed"),  # "three of those sheep turned back ... began to build up ... the wild boars tried to hinder them"
    ("1_enoch", "89:73", "Mal", 1, 7, 1, 7, "Related image: polluted bread on the table before the sanctuary"),  # "all the bread on it was polluted and not pure"
    ("4_ezra", "3:5", "Gen", 2, 7, 2, 7, "Retells: God breathes the breath of life into Adam"),  # "didst breathe into him the breath of life"
    ("4_ezra", "3:7", "Gen", 2, 16, 3, 19, "Retells: Adam's transgression of the commandment, and death"),  # "gavest commandment ... which he transgressed, and immediately thou appointedst death"
    ("4_ezra", "3:9", "Gen", 7, 17, 7, 23, "Retells: the flood"),  # "thou broughtest the flood upon those that dwelt in the world"
    ("4_ezra", "10:21", "2Ki", 25, 8, 25, 10, "Narrative setting: the sanctuary laid waste and the temple destroyed"),  # "our sanctuary is laid waste, our altar broken down, our temple destroyed"
    ("4_ezra", "11:1", "Dan", 7, 2, 7, 3, "Related imagery: a creature coming up from the sea"),  # "there came up from the sea an eagle, which had twelve feathered wings"
    ("4_ezra", "11:39", "Dan", 7, 3, 7, 8, "Related imagery: the four beasts"),  # "remainest of the four beasts, whom I made to reign in my world"
    ("4_ezra", "12:11", "Dan", 7, 7, 7, 8, "Explicit reference: the eagle is the kingdom seen in Daniel's vision"),  # "the kingdom which was seen in the vision of thy brother Daniel"
    ("4_ezra", "12:11", "Dan", 7, 23, 7, 24, "Explicit reference: the eagle is the kingdom seen in Daniel's vision"),  # same verse; Daniel's interpretation of the fourth beast
)


def _strip_wiki_markup(text: str) -> str:
    text = re.sub(r"'{2,}", "", text)
    text = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", text)
    text = re.sub(r"<br\s*/?>", " ", text)
    return text


def _table_text(lines: list[str]) -> list[str]:
    """Body text of a wikitable: the first column only when it has a header row.

    Charles prints parallel columns: with a header ('Ethiopic || Greek', '|| Latin
    Fragment.') the second column is a parallel witness and is omitted; without
    one (90:13–18) both columns are doublets of the main text and are kept.
    """
    has_header = any(line.startswith("!") for line in lines)
    cells: list[str] = []
    for line in lines:
        if line.startswith(("|-", "!")):
            continue
        if line.startswith("|"):
            cells.extend(line[1:].split("||"))
        elif cells:
            cells[-1] += "\n" + line
    return cells[:1] if has_header else cells


def _enoch_lines(wikitext: str) -> list[tuple[str, str]]:
    """('H', heading) and ('T', text) lines of one chapter page."""
    body = re.sub(r"\{\{header.*?\n\}\}", "", wikitext, flags=re.S)
    lines = body.split("\n")
    out: list[tuple[str, str]] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("{|"):
            end = index
            while not lines[end].startswith("|}"):
                end += 1
            out.extend(("T", cell) for cell in _table_text(lines[index + 1:end]))
            index = end + 1
            continue
        heading = _HEADING.match(line)
        if heading:
            out.append(("H", _strip_wiki_markup(heading.group(1)).strip()))
        elif not _CHAPTER_LINE.match(line):
            out.append(("T", line))
        index += 1
    return out


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", _strip_wiki_markup(text)).strip()


def parse_enoch_chapter(chapter: int, wikitext: str) -> list[dict]:
    """One passage per Charles verse marker, in page order.

    A verse marker is 'N.' or 'Na.'; sub-verse letters printed without a number
    ('b. And by you') stay in the text, and the reference spans them ('5:6a–b').
    Charles's section headings become the editorial heading of the next verse.
    Unnumbered text belongs to the preceding verse; text before the first
    verse, a gap in the verse numbers, or a repeated label fails the parse.
    """
    segments: list[dict] = []
    pending_headings: list[str] = []
    preamble: list[str] = []
    for kind, line in _enoch_lines(wikitext):
        if kind == "H":
            if line:
                pending_headings.append(line)
            continue
        position = 0
        markers = [
            match for match in _VERSE_MARKER.finditer(line)
            if (chapter, match.group(1) + match.group(2)) not in _ENOCH_FALSE_MARKERS
        ]
        for match in markers:
            before = line[position:match.start()]
            (segments[-1]["parts"] if segments else preamble).append(before)
            segments.append({
                "verse": int(match.group(1)),
                "letter": match.group(2),
                "parts": [],
                "heading": " ".join(pending_headings) or None,
            })
            pending_headings = []
            position = match.end()
        (segments[-1]["parts"] if segments else preamble).append(line[position:])
    if _clean("\n".join(preamble)):
        raise ValueError(f"1 Enoch {chapter}: text before the first verse")
    if not segments:
        raise ValueError(f"1 Enoch {chapter}: no verses")
    verses = {segment["verse"] for segment in segments}
    if verses != set(range(1, max(verses) + 1)):
        raise ValueError(f"1 Enoch {chapter}: verses {sorted(verses)} are not contiguous")

    rows: list[dict] = []
    labels: set[str] = set()
    for segment in segments:
        raw = "\n".join(segment["parts"])
        label = f"{segment['verse']}{segment['letter']}"
        if segment["letter"]:
            inner = _SUB_VERSE.findall(raw)
            if inner:
                label = f"{label}–{inner[-1]}"
        if label in labels:
            raise ValueError(f"1 Enoch {chapter}:{label} appears twice")
        labels.add(label)
        text = _clean(raw)
        if not text:
            raise ValueError(f"1 Enoch {chapter}:{label} is empty")
        key = ENOCH.locator.key(chapter, segment["verse"])
        rows.append({
            "author": "Anonymous (attributed to Enoch)",
            "work_key": ENOCH.key,
            "reference": f"{ENOCH.reference_title} {chapter}:{label}",
            "sort_start": key,
            "sort_end": key,
            "editorial_heading": segment["heading"],
            "text": text,
            "translation": ENOCH_TRANSLATION,
            "edition": ENOCH_EDITION,
            "translation_license": PUBLIC_DOMAIN,
            "license": combined_license(None, PUBLIC_DOMAIN, None),
            "period_tags": next(tags for last, tags in _ENOCH_PERIODS if chapter <= last),
            "source_url": (
                f"https://en.wikisource.org/w/index.php?title={_ENOCH_PAGE.format(chapter=chapter)}"
                f"&oldid={ENOCH_REVISIONS[chapter][0]}"
            ),
        })
    return rows


def _enoch_file(chapter: int) -> str:
    return f"1_enoch_charles_{chapter:03d}.wiki"


def parse_enoch(directory: Path) -> list[dict]:
    return [
        row
        for chapter in ENOCH_REVISIONS
        for row in parse_enoch_chapter(
            chapter, (directory / _enoch_file(chapter)).read_text(encoding="utf-8")
        )
    ]


def parse_kjv_2_esdras(usfm: str) -> dict[tuple[int, int], str]:
    """KJV 2 Esdras verses by (chapter, verse) from the eBible USFM."""
    verses: dict[tuple[int, int], str] = {}
    chapter = None
    for line in usfm.splitlines():
        marker = re.match(r"\\c (\d+)", line)
        if marker:
            chapter = int(marker.group(1))
            continue
        verse = re.match(r"\\v (\d+) (.*)", line)
        if verse:
            if chapter is None:
                raise ValueError("KJV 2 Esdras: verse before the first chapter")
            text = re.sub(r"\\\w+\*?", "", verse.group(2))
            verses[(chapter, int(verse.group(1)))] = re.sub(r"\s+", " ", text).strip()
        elif line.strip() and not line.startswith(("\\id", "\\ide", "\\h", "\\toc", "\\mt", "\\p")):
            raise ValueError(f"KJV 2 Esdras: unexpected USFM line {line[:40]!r}")
    if not verses:
        raise ValueError("KJV 2 Esdras: no verses")
    return verses


def parse_latin_4_esdras(wikitext: str) -> dict[tuple[int, int], str]:
    """Clementine Latin verses by (chapter, verse) from the Wikisource page."""
    pieces = re.split(r"^==\s*Caput (\d+)\s*==\s*$", wikitext, flags=re.M)
    verses: dict[tuple[int, int], str] = {}
    for index in range(1, len(pieces), 2):
        chapter = int(pieces[index])
        parts = re.split(r"<sup>(\d+)</sup>", pieces[index + 1])
        numbers = [int(number) for number in parts[1::2]]
        if numbers != list(range(1, len(numbers) + 1)):
            raise ValueError(f"Latin 4 Esdras {chapter}: verse numbers are not sequential")
        for number, text in zip(numbers, parts[2::2]):
            verses[(chapter, number)] = re.sub(r"\s+", " ", _strip_wiki_markup(text)).strip()
    if not verses:
        raise ValueError("Latin 4 Esdras: no chapters")
    return verses


def ezra_verse(chapter: int, kjv_verse: int) -> int:
    """4 Ezra verse (Bensly/modern numbering) of a KJV 2 Esdras verse."""
    if chapter == 7 and kjv_verse >= MISSING_FRAGMENT[0]:
        return kjv_verse + _FRAGMENT_OFFSET
    return kjv_verse


def _span_text(start: int, end: int) -> str:
    return f"{start}" if start == end else f"{start}–{end}"


def parse_ezra(directory: Path) -> list[dict]:
    """One passage per KJV verse of 2 Esdras 3–14, or per aligned span, with its Latin.

    Verses pair by number except inside ``_EZRA_ALIGNED_SPANS``; the last
    passage of a chapter also takes any further Latin verses (Latin 10:60).
    Every English and Latin verse of chapters 3–14 must land in exactly one
    passage.
    """
    english = parse_kjv_2_esdras((directory / KJV_FILE).read_text(encoding="utf-8"))
    latin = parse_latin_4_esdras((directory / LATIN_FILE).read_text(encoding="utf-8"))
    spans = {(chapter, start): end for chapter, start, end in _EZRA_ALIGNED_SPANS}
    rows: list[dict] = []
    for chapter in EZRA_CHAPTERS:
        english_verses = sorted(verse for c, verse in english if c == chapter)
        latin_verses = sorted(verse for c, verse in latin if c == chapter)
        if not english_verses or not latin_verses:
            raise ValueError(f"4 Ezra {chapter}: chapter missing from the English or the Latin")
        last = english_verses[-1]
        used_english: list[int] = []
        used_latin: list[int] = []
        verse = 1
        while verse <= last:
            end = spans.get((chapter, verse), verse)
            english_part = [v for v in range(verse, end + 1) if (chapter, v) in english]
            latin_end = latin_verses[-1] if end == last else end
            latin_part = [v for v in range(verse, latin_end + 1) if (chapter, v) in latin]
            if not english_part or not latin_part:
                raise ValueError(f"4 Ezra {chapter}:{verse}: missing English or Latin text")
            used_english.extend(english_part)
            used_latin.extend(latin_part)
            start_key, end_key = ezra_verse(chapter, verse), ezra_verse(chapter, end)
            rows.append({
                "author": "Anonymous (attributed to Ezra)",
                "work_key": EZRA.key,
                "reference": f"{EZRA.reference_title} {chapter}:{_span_text(start_key, end_key)}",
                "alternate_reference": f"KJV 2 Esdras {chapter}:{_span_text(verse, end)}",
                "sort_start": EZRA.locator.key(chapter, start_key),
                "sort_end": EZRA.locator.key(chapter, end_key),
                "text": " ".join(english[(chapter, v)] for v in english_part),
                "translation": KJV_TRANSLATION,
                "translation_license": PUBLIC_DOMAIN,
                "original_text": " ".join(latin[(chapter, v)] for v in latin_part),
                "original_language": "Latin",
                "original_license": WIKISOURCE_LICENSE,
                "license": combined_license(WIKISOURCE_LICENSE, PUBLIC_DOMAIN, "Latin"),
                "edition": LATIN_EDITION,
                "period_tags": EZRA_PERIODS,
                "source_url": KJV_PAGE_URL,
            })
            verse = end + 1
        if used_english != english_verses or used_latin != latin_verses:
            raise ValueError(f"4 Ezra {chapter}: English or Latin verses left unpaired")
    return rows


def parse(directory: Path) -> list[dict]:
    return [*parse_enoch(directory), *parse_ezra(directory)]


def biblical_links(passages: list[dict]) -> list[BiblicalLink]:
    return [BiblicalLink(*link) for link in _BIBLICAL_LINKS]


REQUIRED_FILES = (*(_enoch_file(chapter) for chapter in ENOCH_REVISIONS), KJV_FILE, LATIN_FILE)


def require_pseudepigrapha_files(directory: Path) -> None:
    """Raise unless every 1 Enoch chapter, the KJV 2 Esdras and the Latin page are present."""
    missing = [name for name in REQUIRED_FILES if not (directory / name).is_file()]
    if missing:
        raise FileNotFoundError(
            f"Pseudepigrapha sources in {directory} are incomplete; missing "
            f"{', '.join(missing)}. Run python scripts/download_ancient_sources.py."
        )


def _sha1_hex(content: bytes) -> str:
    return hashlib.sha1(content).hexdigest()


# Wikimedia's robot policy rejects requests whose User-Agent carries no contact
# URL, so Wikisource requests name the project.
_WIKIMEDIA_HEADERS = {
    "User-Agent": "studybible-mcp/1.0 (https://github.com/djayatillake/studybible-mcp)"
}


def _verified_existing(path: Path, expected: str, digest) -> bool:
    if not path.is_file():
        return False
    if digest(path.read_bytes()) == expected:
        return True
    path.unlink()
    return False


def _download_enoch(client: httpx.Client, target: Path, force: bool) -> dict[str, dict]:
    """Fetch the pinned revisions in batches of 50 through the MediaWiki API."""
    wanted = [
        chapter for chapter, (_, sha1) in ENOCH_REVISIONS.items()
        if force or not _verified_existing(target / _enoch_file(chapter), sha1, _sha1_hex)
    ]
    by_revision = {revision: chapter for chapter, (revision, _) in ENOCH_REVISIONS.items()}
    for offset in range(0, len(wanted), 50):
        batch = [ENOCH_REVISIONS[chapter][0] for chapter in wanted[offset:offset + 50]]
        response = client.get(_ENOCH_API, headers=_WIKIMEDIA_HEADERS, params={
            "action": "query", "prop": "revisions", "revids": "|".join(map(str, batch)),
            "rvprop": "ids|sha1|content", "rvslots": "main", "format": "json",
            "formatversion": "2",
        })
        response.raise_for_status()
        received = set()
        for page in response.json()["query"]["pages"]:
            for revision in page.get("revisions", []):
                chapter = by_revision[revision["revid"]]
                content = revision["slots"]["main"]["content"].encode("utf-8")
                expected = ENOCH_REVISIONS[chapter][1]
                if _sha1_hex(content) != expected:
                    raise RuntimeError(
                        f"Checksum mismatch for 1 Enoch chapter {chapter}: "
                        f"{_sha1_hex(content)} != {expected}"
                    )
                (target / _enoch_file(chapter)).write_bytes(content)
                received.add(revision["revid"])
        if received != set(batch):
            raise RuntimeError(f"Wikisource did not return revisions {sorted(set(batch) - received)}")
    return {
        _enoch_file(chapter): {
            "revision": revision, "sha1": sha1,
            "source_url": (
                f"https://en.wikisource.org/w/index.php?title={_ENOCH_PAGE.format(chapter=chapter)}"
                f"&oldid={revision}"
            ),
        }
        for chapter, (revision, sha1) in ENOCH_REVISIONS.items()
    }


def _download_kjv(client: httpx.Client, target: Path, force: bool) -> bytes:
    path = target / KJV_FILE
    if not force and _verified_existing(path, KJV_SHA256, sha256_hex):
        return path.read_bytes()
    response = client.get(KJV_ZIP_URL)
    response.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        content = archive.read(KJV_FILE)
    if sha256_hex(content) != KJV_SHA256:
        raise RuntimeError(f"Checksum mismatch for {KJV_FILE}: {sha256_hex(content)} != {KJV_SHA256}")
    path.write_bytes(content)
    return content


def _download_latin(client: httpx.Client, target: Path, force: bool) -> bytes:
    path = target / LATIN_FILE
    if not force and _verified_existing(path, LATIN_SHA1, _sha1_hex):
        return path.read_bytes()
    response = client.get(f"{LATIN_URL}&action=raw", headers=_WIKIMEDIA_HEADERS)
    response.raise_for_status()
    content = response.content
    if _sha1_hex(content) != LATIN_SHA1:
        raise RuntimeError(f"Checksum mismatch for {LATIN_FILE}: {_sha1_hex(content)} != {LATIN_SHA1}")
    path.write_bytes(content)
    return content


def download(client: httpx.Client, target: Path, force: bool) -> dict:
    """Fetch the 108 pinned Enoch revisions, the KJV 2 Esdras USFM, and the Latin revision."""
    files = _download_enoch(client, target, force)
    kjv = _download_kjv(client, target, force)
    files[KJV_FILE] = {"sha256": KJV_SHA256, "bytes": len(kjv), "source_url": KJV_ZIP_URL}
    latin = _download_latin(client, target, force)
    files[LATIN_FILE] = {
        "revision": LATIN_REVISION, "sha1": LATIN_SHA1, "bytes": len(latin), "source_url": LATIN_URL,
    }
    return {
        "source": "English Wikisource (1 Enoch, Charles); eBible.org eng-kjv (2 Esdras); "
                  "Latin Wikisource (Vulgata Clementina, 4 Esdras)",
        "license": "Public domain (English); CC BY-SA 4.0 (Latin Wikisource transcription)",
        "files": files,
    }


CORPUS = Corpus(
    key="pseudepigrapha",
    label="Pseudepigrapha",
    summary=(
        "Jewish pseudepigrapha (non-canonical; attributed to ancient figures): 1 Enoch in "
        "R. H. Charles's English translation (1912), one passage per Charles verse "
        "('1 Enoch 89:73'); and 4 Ezra = 2 Esdras 3–14 (same chapter numbers; '2 Esdras' "
        "and '4 Esdras' also accepted) in the KJV with the Clementine Latin, one passage "
        "per verse in modern numbering (KJV 7:36–70 = 4 Ezra 7:106–140)."
    ),
    data_dir="pseudepigrapha",
    original_language="Ge'ez",
    works=(ENOCH, EZRA),
    periods=PERIODS,
    download=download,
    require_files=require_pseudepigrapha_files,
    parse=parse,
    biblical_links=biblical_links,
    example_query="Lord of the sheep",
    example_citation="1 Enoch 89:73",
    aliases=(),
    heading_label="Charles section heading",
    caveat=CAVEAT,
)
