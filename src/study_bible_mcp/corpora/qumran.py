"""Qumran corpus: Hebrew Dead Sea Scrolls texts, one passage per manuscript column.

The Damascus Document (Cairo Genizah MSS A and B), the Community Rule (1QS)
and the Rule of the Congregation (1QSa) come from the ETCBC/dss Text-Fabric
transcription by Martin G. Abegg Jr., James E. Bowley and Edward M. Cook
(CC BY-NC 4.0); Pesher Habakkuk (1QpHab) comes from Hebrew Wikisource
(CC BY-SA 4.0). No openly licensed English translation exists for any of them,
so every passage is original-only.
"""

from __future__ import annotations

import re
from itertools import takewhile
from pathlib import Path
from typing import TYPE_CHECKING

from .base import BiblicalLink, Corpus, SourceTag, Work
from .download import fetch_github_directory, fetch_verified, sha256_hex
from .locators import COLUMN_LINE

if TYPE_CHECKING:
    import httpx


ORIGINAL_LANGUAGE = "Hebrew"

ETCBC_REPOSITORY = "ETCBC/dss"
ETCBC_COMMIT = "47ecc1738fad6e67df7d40a3e84d73e4a125e265"  # tag v2.0.1
ETCBC_TF_PATH = "tf/2.0.1"
ETCBC_LICENSE = "CC BY-NC 4.0"
ETCBC_LICENSE_DECLARATION = (
    "@license=Creative Commons Attribution-NonCommercial 4.0 International License"
)
ETCBC_SOURCE_URL = f"https://github.com/{ETCBC_REPOSITORY}/tree/{ETCBC_COMMIT}/{ETCBC_TF_PATH}"
ETCBC_EDITION = (
    "Martin G. Abegg Jr., James E. Bowley and Edward M. Cook, Dead Sea Scrolls "
    "transcription, ETCBC/dss Text-Fabric release 2.0.1"
)
# Text-Fabric features read from the release: node types and slot links, the
# scroll/column/line labels, and the sign-level text and text-critical marks.
ETCBC_FEATURES = (
    "otype", "oslots", "scroll", "fragment", "line", "type", "glyph", "after",
    "rec", "rem", "cor", "alt", "vac", "unc",
)
ETCBC_FILES = tuple(f"{feature}.tf" for feature in ETCBC_FEATURES)

WIKISOURCE_REVISION = 2949117
WIKISOURCE_FILE = f"1QpHab.he-wikisource.{WIKISOURCE_REVISION}.wikitext"
WIKISOURCE_URL = (
    f"https://he.wikisource.org/w/index.php?oldid={WIKISOURCE_REVISION}&action=raw"
)
WIKISOURCE_SHA256 = "2ee32f91af3ea60d4c4d116313d797183c24f79fef6bb4a1758b64c5b55e6b24"
WIKISOURCE_SOURCE_URL = f"https://he.wikisource.org/w/index.php?oldid={WIKISOURCE_REVISION}"
WIKISOURCE_LICENSE = "CC BY-SA 4.0"
WIKISOURCE_EDITION = (
    "Hebrew Wikisource, 'מגילות מדבר יהודה/1QpHab פשר חבקוק', "
    f"revision {WIKISOURCE_REVISION} (2025-07-20)"
)
# Wikimedia's robot policy requires a User-Agent with contact details.
WIKIMEDIA_USER_AGENT = (
    "studybible-mcp/1.0 (+https://github.com/djayatillake/studybible-mcp) httpx"
)

REQUIRED_FILES = (*ETCBC_FILES, WIKISOURCE_FILE)

# Labelling contract: dates from the canon review's date ladder.
_ETCBC_EDITION = "Abegg–Bowley–Cook Hebrew (ETCBC)"
RULE_TAG = SourceTag(
    kind="Qumran sectarian rule", date="c. 100 BC; Cave 1 copy c. 75 BC", tier="A",
    edition=_ETCBC_EDITION,
)
CAVEAT = (
    "Not Scripture: sectarian texts of a strict priestly movement (c. 150–50 BC). "
    "[ ] marks modern reconstruction, never evidence; any English is the assistant's own."
)

DAMASCUS_DOCUMENT = Work(
    key="damascus_document",
    title="Damascus Document",
    reference_title="CD",
    locator=COLUMN_LINE,
    aliases=("Damascus Rule", "Zadokite Fragments", "Zadokite Work"),
    tag=SourceTag(
        kind="Qumran sectarian rule", date="composed 2nd–1st c. BC", tier="A",
        edition=_ETCBC_EDITION,
        manuscript="copies: Cairo Genizah, 10th and 11th–12th c. AD",
    ),
)
COMMUNITY_RULE = Work(
    key="community_rule",
    title="Community Rule",
    reference_title="1QS",
    locator=COLUMN_LINE,
    aliases=("Rule of the Community", "Manual of Discipline"),
    tag=RULE_TAG,
)
RULE_OF_THE_CONGREGATION = Work(
    key="rule_of_the_congregation",
    title="Rule of the Congregation",
    reference_title="1QSa",
    locator=COLUMN_LINE,
    aliases=("1Q28a", "Messianic Rule"),
    tag=RULE_TAG,
)
PESHER_HABAKKUK = Work(
    key="pesher_habakkuk",
    title="Pesher Habakkuk",
    reference_title="1QpHab",
    locator=COLUMN_LINE,
    aliases=("Habakkuk Pesher", "Habakkuk Commentary"),
    tag=SourceTag(
        kind="Qumran pesher", date="Herodian-era copy, late 1st c. BC", tier="A",
        edition="Hebrew Wikisource transcription",
    ),
)
WORKS = (DAMASCUS_DOCUMENT, COMMUNITY_RULE, RULE_OF_THE_CONGREGATION, PESHER_HABAKKUK)

# ETCBC scroll acronyms imported, in corpus order. Every column and line label
# of these scrolls is a plain number; other scrolls (e.g. 1QSb) mix fragment
# labels and line gaps and are not imported.
_ETCBC_WORKS = {"CD": DAMASCUS_DOCUMENT, "1QS": COMMUNITY_RULE, "1QSa": RULE_OF_THE_CONGREGATION}

PERIODS = ("second_temple", "hasmonean", "roman")
# Editorial composition-period tags. The rules and the Damascus Document are
# generally dated to the Hasmonean era; Pesher Habakkuk's Kittim are generally
# identified with the Romans, so it also carries 'roman'.
_PERIOD_TAGS = {
    DAMASCUS_DOCUMENT.key: "second_temple,hasmonean",
    COMMUNITY_RULE.key: "second_temple,hasmonean",
    RULE_OF_THE_CONGREGATION.key: "second_temple,hasmonean",
    PESHER_HABAKKUK.key: "second_temple,hasmonean,roman",
}

# Editorial links from Pesher Habakkuk to the Habakkuk verses its lemmas quote,
# never inferred from wording. Fields: 1QpHab column:line where the quotation
# begins, words of the lemma that survive outside the editor's brackets on that
# line of the pinned Wikisource text (checked by ``biblical_links`` on import),
# Habakkuk chapter, verse, end chapter, end verse, and an optional note suffix.
# Each comment names the matching words of the Masoretic verse. Line numbers
# follow the scroll (see _WIKISOURCE_LINE_CORRECTIONS for column 1).
_BIBLICAL_LINKS = (
    ("1:1", "שועתי ולוא", 1, 2, 1, 2, ""),  # Hab 1:2 'שועתי ולא תשמע'
    ("1:8", "ריב", 1, 3, 1, 3, " (lemma mostly restored)"),  # Hab 1:3b 'ויהי ריב ומדון ישא'
    ("1:10", "על כן תפוג תורה", 1, 4, 1, 4, ""),  # Hab 1:4a; 1:12 'את הצדיק', 1:14 'על כן יצא המשפט'
    ("2:1", "יסופר", 1, 5, 1, 5, " (lemma mostly restored)"),  # last word of Hab 1:5 'כי יספר'
    ("2:10", "כיא הנני מקים את", 1, 6, 1, 6, ""),  # Hab 1:6a 'כי הנני מקים את'; 2:11 'הכשדאים הגוי'
    ("3:2", "לרשת משכנות לוא לו", 1, 6, 1, 6, ""),  # Hab 1:6b 'לרשת משכנות לא לו'
    ("3:2", "איום", 1, 7, 1, 7, ""),  # Hab 1:7, continued on 3:3 'ונורא הוא ממנו משפטו ושאתו יצא'
    ("3:6", "וקול מנמרים סוסו", 1, 8, 1, 9, ""),  # Hab 1:8 'וקלו מנמרים סוסיו'; 3:8-9 Hab 1:9a 'לחמס יבוא מגמת פניהם'
    ("4:1", "קלס ורזנים משחק לו", 1, 10, 1, 10, ""),  # Hab 1:10a; 4:3 Hab 1:10b 'לכול מבצר ישחק'
    ("4:9", "אז חלף רוח ויעבר", 1, 11, 1, 11, ""),  # Hab 1:11 'אז חלף רוח ויעבר'
    ("5:1", "למשפט שמתו וצור", 1, 12, 1, 13, ""),  # Hab 1:12b; 5:1-2 Hab 1:13a 'טהור עינים', 5:8 Hab 1:13b 'למה תביטו בוגדים'
    ("5:12", "ותעש אדם כדגי הים", 1, 14, 1, 16, ""),  # Hab 1:14; 5:13 Hab 1:15 'בחרמו'; 5:14 Hab 1:16 'לחרמו'
    ("6:2", "על כן יזבח לחרמו", 1, 16, 1, 16, ""),  # Hab 1:16 'על כן יזבח לחרמו'; 6:5 'כי בהם שמן חלקו'
    ("6:8", "על כן יריק חרבו תמיד", 1, 17, 1, 17, ""),  # Hab 1:17 'על כן יריק חרמו ותמיד'
    ("6:12", "על משמרתי אעמודה", 2, 1, 2, 1, ""),  # Hab 2:1 'על משמרתי אעמדה'
    ("6:14", "ויענני יהוה", 2, 2, 2, 2, ""),  # Hab 2:2 'ויענני יהוה'; 6:15 'על הלוחות למען'
    ("7:3", "ואשר אמר למען ירוץ הקורא בו", 2, 2, 2, 2, ""),  # Hab 2:2b 'למען ירוץ קורא בו'
    ("7:5", "כי עוד חזון", 2, 3, 2, 3, ""),  # Hab 2:3a 'כי עוד חזון למועד'; 7:9 Hab 2:3b 'אם יתמהמה חכה לו'
    ("7:14", "הנה עופלה לוא יושרה", 2, 4, 2, 4, ""),  # Hab 2:4a 'הנה עפלה לא ישרה'
    ("8:3", "ואף כיא הון יבגוד גבר יהיר", 2, 5, 2, 6, ""),  # Hab 2:5 'גבר יהיר'; 8:6-8 Hab 2:6 'הלוא כולם משל', 'עבטט'
    ("8:13", "הלוא פתאום ויקומו", 2, 7, 2, 8, ""),  # Hab 2:7 'הלוא פתע יקומו'; 8:14 Hab 2:8a 'כי אתה שלותה גוים'
    ("9:3", "אמר כי אתה שלותה גוים רבים", 2, 8, 2, 8, ""),  # Hab 2:8a; 9:8 Hab 2:8b 'מדמי אדם וחמס ארץ'
    ("9:12", "הוי הבוצע בצע רע", 2, 9, 2, 11, ""),  # Hab 2:9 'הוי בצע בצע רע'; 9:14 Hab 2:10; 9:15 Hab 2:11 'מקיר תזעק'
    ("10:2", "ואשר אמר קצות עמים רבים", 2, 10, 2, 10, ""),  # Hab 2:10b 'קצות עמים רבים'
    ("10:6", "הוי בונה עיר בדמים", 2, 12, 2, 13, ""),  # Hab 2:12; 10:7 Hab 2:13 'מעם יהוה צבאות'
    ("10:14", "כיא תמלא הארץ לדעת את כבוד יהוה", 2, 14, 2, 14, ""),  # Hab 2:14
    ("11:2", "הוי משקה רעיהו", 2, 15, 2, 15, ""),  # Hab 2:15 'הוי משקה רעהו'
    ("11:8", "שבעת", 2, 16, 2, 16, ""),  # Hab 2:16, continued on 11:9 'קלון מ[כ]בוד שתה גם אתה'
    ("12:1", "מדמי אדם וחמת ארץ קריה", 2, 17, 2, 17, ""),  # Hab 2:17b; 12:6-7 'מדמי קריה וחמס ארץ'
    ("12:10", "מה הועיל פסל", 2, 18, 2, 18, ""),  # Hab 2:18 'מה הועיל פסל'
    ("12:15", "לעץ הקיצה", 2, 19, 2, 19, ""),  # Hab 2:19 'לעץ הקיצה'
    ("13:1", "הס מלפניו כול", 2, 20, 2, 20, ""),  # Hab 2:20b 'הס מפניו כל הארץ'
)

# Hebrew Wikisource numbers column 1 continuously from 1 to 14, but folds the
# wholly restored scroll line 7 ('ושוד וחמס לנגדי') into its line 6, so its
# lines 7-14 carry scroll lines 8-15. Verified against the ETCBC/dss
# transcription of 1QpHab at ETCBC_COMMIT, whose surviving words agree line by
# line after this shift: Wikisource 1:9 'על כן תפוג תורה' is ETCBC 1:10 and
# Wikisource 1:12 'הוא מורה הצדק' is ETCBC 1:13. Columns 2-13 agree as numbered.
_WIKISOURCE_LINE_CORRECTIONS = {(1, line): line + 1 for line in range(7, 15)}

_COLUMN_SECTION = "==ערוך לפי סדר עמודות ושורות=="
_COLUMN_HEADER = re.compile(r"1QpHab עמודה (\d+)")
_WIKI_MARKUP = re.compile(r"\{\{|\[\[|<")


def _period_tags(work: Work) -> str:
    return _PERIOD_TAGS[work.key]


def _column_passage(
    work: Work,
    column: int,
    lines: list[tuple[int, str]],
    edition: str,
    original_license: str,
    source_url: str,
    manuscript: str | None = None,
) -> dict:
    """One passage per manuscript column; the text keeps the line numbers.

    ``manuscript`` is a siglum ('CD-A') cited with the same span as
    ``alternate_reference``.
    """
    start = work.locator.key(column, lines[0][0])
    end = work.locator.key(column, lines[-1][0])
    span = work.locator.format_range(start, end)
    return {
        "work_key": work.key,
        "reference": f"{work.reference_title} {span}",
        "alternate_reference": f"{manuscript} {span}" if manuscript else None,
        "sort_start": start,
        "sort_end": end,
        "author": work.title,
        "original_text": "\n".join(f"{number} {text}".rstrip() for number, text in lines),
        "original_language": ORIGINAL_LANGUAGE,
        "original_license": original_license,
        "license": original_license,
        "edition": edition,
        "period_tags": _period_tags(work),
        "source_url": source_url,
    }


# --- ETCBC/dss Text-Fabric ---------------------------------------------------

_TF_ESCAPES = re.compile(r"\\([\\tn])")


def _tf_unescape(value: str) -> str:
    return _TF_ESCAPES.sub(lambda m: {"\\": "\\", "t": "\t", "n": "\n"}[m.group(1)], value)


def _tf_ranges(spec: str) -> list[tuple[int, int]]:
    """Node ranges of a Text-Fabric spec such as '7', '3-5' or '1,4-6'."""
    ranges = []
    for part in spec.split(","):
        first, _, last = part.partition("-")
        ranges.append((int(first), int(last or first)))
    return ranges


def _tf_data(path: Path):
    """Yield the data lines of a Text-Fabric file after checking its licence header."""
    with path.open(encoding="utf-8") as handle:
        header = []
        for raw in handle:
            line = raw.rstrip("\r\n")
            if not line:
                break
            if not line.startswith("@"):
                raise ValueError(f"{path.name}: malformed Text-Fabric header line {line!r}")
            header.append(line)
        if ETCBC_LICENSE_DECLARATION not in header:
            raise ValueError(f"Expected the CC BY-NC 4.0 declaration in {path}")
        for raw in handle:
            yield raw.rstrip("\r\n")


def _tf_feature(path: Path, first: int, last: int) -> dict[int, str]:
    """Values of a Text-Fabric node feature (or ``oslots``) for nodes first..last.

    A data line is ``value`` (the next node) or ``spec<TAB>value``; nodes only
    increase, so reading stops after ``last``.
    """
    values: dict[int, str] = {}
    node = 0
    for line in _tf_data(path):
        spec, tab, value = line.partition("\t")
        if not tab:
            spec, value = str(node + 1), line
        try:
            ranges = _tf_ranges(spec)
        except ValueError as error:
            raise ValueError(f"{path.name}: malformed node spec {spec!r}") from error
        value = _tf_unescape(value)
        for start, end in ranges:
            if start <= node:
                raise ValueError(f"{path.name}: node {start} does not follow node {node}")
            for current in range(max(start, first), min(end, last) + 1):
                values[current] = value
            node = end
        if node >= last:
            break
    return values


def _tf_types(path: Path) -> dict[str, tuple[int, int]]:
    """Node range of each Text-Fabric node type from ``otype.tf``."""
    types: dict[str, tuple[int, int]] = {}
    for line in _tf_data(path):
        if not line:
            continue
        spec, tab, name = line.partition("\t")
        if not tab:
            raise ValueError(f"{path.name}: malformed type line {line!r}")
        (start, end), = _tf_ranges(spec)
        types[name] = (start, end)
    for name in ("sign", "line"):
        if name not in types:
            raise ValueError(f"{path.name}: no {name!r} nodes")
    return types


# Text-critical brackets of the transcription, by sign feature and value, in
# opening order: modern reconstruction, removal by a modern editor or by the
# scribe, correction by a modern editor, by the scribe, or supralinear, and an
# alternative reading. A vacat (unwritten space) is rendered as 'vacat'.
_BRACKETS = (
    ("rec", "1", "[", "]"),
    ("rem", "1", "{", "}"),
    ("rem", "2", "{{", "}}"),
    ("cor", "1", "<", ">"),
    ("cor", "2", "<<", ">>"),
    ("cor", "3", "^", "^"),
    ("alt", "1", "(", ")"),
    ("vac", "1", "vacat", ""),
)
_MARK_FEATURES = ("rec", "rem", "cor", "alt", "vac")
# Letters removed by the scribe {{ }} or a modern editor { } are not part of
# the corrected reading, and 'vacat' is not text: search drops them, so
# 'י{{א}}<<ע>>בורו' is indexed as 'יעבורו'. Doubled braces first.
SEARCH_INDEX_REMOVALS = (r"\{\{[^{}]*\}\}", r"\{[^{}]*\}", r"\bvacat\b")
_EMPTY_BRACKETS = re.compile(r"(\[|\{\{|\{|<<|<|\^|\()(\]|\}\}|\}|>>|>|\^|\))")
# A circlet above a letter marks it as damaged or uncertain (any of the
# transcription's four uncertainty degrees); search folding drops it.
_UNCERTAIN = "\u05af"
_MORPHEME_BREAK = "׳"


def _render_line(slots: range, signs: dict[str, dict[int, str]]) -> str:
    """Hebrew text of one scroll line from its signs, with editorial brackets."""
    types, glyphs, after = signs["type"], signs["glyph"], signs["after"]

    def marks(slot: int) -> tuple[int, ...]:
        return tuple(
            index for index, (feature, value, _, _) in enumerate(_BRACKETS)
            if signs[feature].get(slot) == value
        )

    parts: list[str] = []
    previous: tuple[int, ...] = ()
    current = marks(slots[0]) if slots else ()
    for position, slot in enumerate(slots):
        following = marks(slots[position + 1]) if position + 1 < len(slots) else ()
        parts.extend(_BRACKETS[index][2] for index in current if index not in previous)
        kind, glyph = types.get(slot), glyphs.get(slot, "")
        if kind in ("cons", "vwl", "numr"):
            parts.append(glyph + (_UNCERTAIN if signs["unc"].get(slot) else ""))
        elif kind == "sep":
            # Abegg's '/' morpheme break is analytical, not written.
            parts.append("" if glyph == _MORPHEME_BREAK else glyph)
        elif kind in ("punct", "add"):
            parts.append(glyph)
        elif kind == "missing":
            parts.append("…")
        elif kind == "unc":
            parts.append("◦")
        elif kind not in ("empty", "term"):
            raise ValueError(f"Unknown ETCBC sign type {kind!r} at slot {slot}")
        parts.extend(_BRACKETS[index][3] for index in reversed(current) if index not in following)
        parts.append(after.get(slot) or "")
        previous, current = current, following
    text = re.sub(r"\s+", " ", "".join(parts)).strip()
    return _EMPTY_BRACKETS.sub(r"\1 \2", text)


def _number(label: str, what: str) -> int:
    if not label.isdigit():
        raise ValueError(f"ETCBC {what} label {label!r} is not a number")
    return int(label)


def parse_etcbc(directory: Path) -> list[dict]:
    """One passage per column of each imported ETCBC scroll, lines in order."""
    types = _tf_types(directory / "otype.tf")
    line_first, line_last = types["line"]
    scrolls = _tf_feature(directory / "scroll.tf", line_first, line_last)
    wanted = sorted(node for node, scroll in scrolls.items() if scroll in _ETCBC_WORKS)
    found = {scrolls[node] for node in wanted}
    if found != set(_ETCBC_WORKS):
        raise ValueError(f"ETCBC scrolls missing: {sorted(set(_ETCBC_WORKS) - found)}")
    low, high = wanted[0], wanted[-1]
    columns = _tf_feature(directory / "fragment.tf", low, high)
    numbers = _tf_feature(directory / "line.tf", low, high)
    slot_specs = _tf_feature(directory / "oslots.tf", low, high)

    line_slots: dict[int, range] = {}
    for node in wanted:
        ranges = _tf_ranges(slot_specs[node])
        line_slots[node] = range(ranges[0][0], ranges[-1][1] + 1)
        if len(ranges) != 1:
            raise ValueError(f"ETCBC line node {node} has discontinuous slots")
    first_slot = min(slots[0] for slots in line_slots.values() if slots)
    last_slot = max(slots[-1] for slots in line_slots.values() if slots)
    signs = {
        feature: _tf_feature(directory / f"{feature}.tf", first_slot, last_slot)
        for feature in ("type", "glyph", "after", "unc", *_MARK_FEATURES)
    }

    by_column: dict[tuple[str, int], list[tuple[int, str]]] = {}
    for node in wanted:
        scroll = scrolls[node]
        key = (scroll, _number(columns[node], f"{scroll} column"))
        by_column.setdefault(key, []).append(
            (_number(numbers[node], f"{scroll} line"), _render_line(line_slots[node], signs))
        )

    rows = []
    for (scroll, column), lines in by_column.items():
        expected = list(range(1, len(lines) + 1))
        if [number for number, _ in lines] != expected:
            raise ValueError(f"ETCBC {scroll} column {column}: lines are not numbered 1..{len(lines)}")
        work = _ETCBC_WORKS[scroll]
        alternate = None
        if work is DAMASCUS_DOCUMENT:
            # Genizah MS A has columns 1-16; MS B, columns 19-20.
            alternate = "CD-A" if column <= 16 else "CD-B"
        rows.append(
            _column_passage(
                work, column, lines, ETCBC_EDITION, ETCBC_LICENSE, ETCBC_SOURCE_URL, alternate
            )
        )
    return rows


# --- Hebrew Wikisource 1QpHab --------------------------------------------------


def _wikisource_columns(text: str) -> dict[int, list[tuple[int, str]]]:
    """Scroll lines of the column-and-line section, keyed by column."""
    _, found, rest = text.partition(_COLUMN_SECTION)
    _, opened, rest = rest.partition("<poem>")
    poem, closed, _ = rest.partition("</poem>")
    if not (found and opened and closed):
        raise ValueError("1QpHab Wikisource page has no column-and-line <poem> section")
    columns: dict[int, list[tuple[int, str]]] = {}
    column = 0
    for raw in poem.splitlines():
        line = raw.strip()
        if not line:
            continue
        if header := _COLUMN_HEADER.fullmatch(line):
            if int(header.group(1)) != column + 1:
                raise ValueError(f"1QpHab column {header.group(1)} does not follow column {column}")
            column = int(header.group(1))
            columns[column] = []
            continue
        if not line.startswith("#") or not column:
            raise ValueError(f"Unexpected 1QpHab line outside a numbered column: {line!r}")
        content = line[1:].strip()
        if _WIKI_MARKUP.search(content):
            raise ValueError(f"Unexpected markup in 1QpHab column {column}: {content!r}")
        number = len(columns[column]) + 1
        columns[column].append((_WIKISOURCE_LINE_CORRECTIONS.get((column, number), number), content))
    if not columns or any(not lines for lines in columns.values()):
        raise ValueError("1QpHab Wikisource columns must each have lines")
    return columns


def parse_pesher_habakkuk(directory: Path) -> list[dict]:
    text = (directory / WIKISOURCE_FILE).read_text(encoding="utf-8")
    return [
        _column_passage(
            PESHER_HABAKKUK, column, lines, WIKISOURCE_EDITION, WIKISOURCE_LICENSE,
            WIKISOURCE_SOURCE_URL,
        )
        for column, lines in _wikisource_columns(text).items()
    ]


def parse(directory: Path) -> list[dict]:
    return [*parse_etcbc(directory), *parse_pesher_habakkuk(directory)]


def _passage_lines(passage: dict) -> dict[int, str]:
    lines = {}
    for line in passage["original_text"].splitlines():
        number, _, text = line.partition(" ")
        lines[int(number)] = text
    return lines


def biblical_links(passages: list[dict]) -> list[BiblicalLink]:
    """The curated 1QpHab lemma links, each checked against its pinned line."""
    pesher = [row for row in passages if row["work_key"] == PESHER_HABAKKUK.key]
    links = []
    for locator, quoted, c1, v1, c2, v2, suffix in _BIBLICAL_LINKS:
        column, line = (int(part) for part in locator.split(":"))
        key = COLUMN_LINE.key(column, line)
        passage = next(
            (row for row in pesher if row["sort_start"] <= key <= row["sort_end"]), None
        )
        text = _passage_lines(passage).get(line, "") if passage else ""
        if quoted not in text:
            raise ValueError(f"1QpHab {locator} does not contain the quoted lemma {quoted!r}")
        verses = f"{c1}:{v1}" if (c1, v1) == (c2, v2) else (
            f"{c1}:{v1}–{v2}" if c1 == c2 else f"{c1}:{v1}–{c2}:{v2}"
        )
        links.append(BiblicalLink(
            work_key=PESHER_HABAKKUK.key,
            locator=locator,
            book="Hab",
            chapter=c1,
            verse=v1,
            end_chapter=c2,
            end_verse=v2,
            note=f"Quotes and interprets: Hab {verses}{suffix}",
        ))
    return links


def require_qumran_files(directory: Path) -> None:
    """Raise unless every pinned ETCBC feature file and the 1QpHab page are present."""
    missing = [name for name in REQUIRED_FILES if not (directory / name).is_file()]
    if missing:
        raise FileNotFoundError(
            f"Qumran sources in {directory} are incomplete; missing "
            f"{', '.join(missing)}. Run python scripts/download_ancient_sources.py."
        )


def _require_license_declaration(filename: str, content: bytes) -> None:
    head = content[:4096].decode("utf-8", errors="replace").splitlines()
    header = list(takewhile(bool, (line.rstrip("\r") for line in head)))
    if ETCBC_LICENSE_DECLARATION not in header:
        raise RuntimeError(f"Missing expected CC BY-NC 4.0 declaration in {filename}")


def _select_download(name: str) -> str | None:
    return name if name in ETCBC_FILES else None


def _fetch_wikisource(client: httpx.Client, destination: Path, force: bool) -> bytes:
    """Download the pinned revision with the contact User-Agent Wikimedia requires.

    Wikimedia's robot policy rejects library clients without contact details,
    so the request carries its own header; the file is written only once it
    verifies, and ``fetch_verified`` re-checks whatever is on disk.
    """
    if force or not destination.is_file():
        response = client.get(WIKISOURCE_URL, headers={"User-Agent": WIKIMEDIA_USER_AGENT})
        response.raise_for_status()
        actual = sha256_hex(response.content)
        if actual != WIKISOURCE_SHA256:
            raise RuntimeError(
                f"Checksum mismatch for {destination.name}: {actual} != {WIKISOURCE_SHA256}"
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(response.content)
    return fetch_verified(client, WIKISOURCE_URL, destination, WIKISOURCE_SHA256)



def download(client: httpx.Client, target: Path, force: bool) -> dict:
    """Fetch the ETCBC feature files at the pinned commit and the pinned 1QpHab revision."""
    files = fetch_github_directory(
        client,
        ETCBC_REPOSITORY,
        ETCBC_COMMIT,
        ETCBC_TF_PATH,
        target,
        select=_select_download,
        force=force,
        validate=_require_license_declaration,
    )
    missing = sorted(set(ETCBC_FILES) - set(files))
    if missing:
        raise RuntimeError(f"ETCBC/dss {ETCBC_TF_PATH} at {ETCBC_COMMIT} lacks {missing}")
    for entry in files.values():
        entry["license"] = ETCBC_LICENSE
    content = _fetch_wikisource(client, target / WIKISOURCE_FILE, force)
    files[WIKISOURCE_FILE] = {
        "sha256": WIKISOURCE_SHA256,
        "bytes": len(content),
        "source_url": WIKISOURCE_SOURCE_URL,
        "license": WIKISOURCE_LICENSE,
    }
    return {
        "sources": [
            {"repository": ETCBC_REPOSITORY, "commit": ETCBC_COMMIT, "path": ETCBC_TF_PATH,
             "license": ETCBC_LICENSE},
            {"source": WIKISOURCE_SOURCE_URL, "version": f"revision {WIKISOURCE_REVISION}",
             "license": WIKISOURCE_LICENSE},
        ],
        "files": files,
    }


CORPUS = Corpus(
    key="qumran",
    label="Qumran",
    summary=(
        "Hebrew Dead Sea Scrolls texts without English (none is openly licensed): "
        "the Damascus Document (Cairo Genizah MS A columns 1–16 and MS B columns "
        "19–20), the Community Rule (1QS) and the Rule of the Congregation (1QSa) "
        "from the ETCBC/dss transcription of Abegg, Bowley and Cook, and Pesher "
        "Habakkuk (1QpHab) from Hebrew Wikisource. Each passage is one manuscript "
        "column with numbered lines, cited by column:line ('CD 6:11', '1QS 3:13', "
        "'1QpHab 7:4')."
    ),
    data_dir="qumran",
    original_language=ORIGINAL_LANGUAGE,
    works=WORKS,
    periods=PERIODS,
    download=download,
    require_files=require_qumran_files,
    parse=parse,
    biblical_links=biblical_links,
    example_query="מורה הצדק",
    example_citation="CD 6:11",
    aliases=("Dead Sea Scrolls", "Qumran", "DSS"),
    search_index_removals=SEARCH_INDEX_REMOVALS,
    caveat=CAVEAT,
    line_numbered=True,
)

