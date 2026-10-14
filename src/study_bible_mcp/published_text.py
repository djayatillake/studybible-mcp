"""Render-time cleanup of published third-party text.

The owner's policy: published wording stays verbatim. Only what is not the
publisher's wording is cleaned here, when a tool shows the text:

- Aquifer resources (Tyndale study notes and Bible dictionary, SIL and
  unfoldingWord translation notes, FIA key terms) are re-rendered from their
  stored HTML: entities unescaped (``&apos;``), headings and list items kept
  on their own lines instead of run into the next sentence, SIL footnotes
  marked, unfoldingWord quote lines repaired (see ``repair_uw_quote``), empty
  "See:" lines dropped, and Tyndale's "1:19–12.50" range titles read "12:50".
- Transcription slips in the ancient-source texts, listed in
  ``published_text_corrections.json``, are fixed (also at import).
- Factual errors are not edited: a ``[⚠ Correction: …]`` note from the same
  file is inserted right after the erroneous text, and ``safe_cut`` keeps a
  truncation from separating the two.

The cleanup runs on the stored HTML, so no database change is needed for a
database built before it.
"""

from __future__ import annotations

import html
import json
import re
from functools import lru_cache
from html.parser import HTMLParser
from pathlib import Path

CORRECTIONS_PATH = Path(__file__).with_name("published_text_corrections.json")
CORRECTION_MARK = "⚠ Correction: "
# Notes print inside the text: keep them short, and free of the bracket that ends them.
MAX_CORRECTION_LENGTH = 400

_BLOCK_TAGS = {
    "p", "div", "blockquote", "pre", "table", "tbody", "thead",
    "h1", "h2", "h3", "h4", "h5", "h6",
}
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
# Closes a footnote; any space the footnote ended with goes (a NUL is never in the text).
_FOOTNOTE_END = "\x00]"


class _AquiferRenderer(HTMLParser):
    """Aquifer HTML to plain text: one paragraph per block, one line per list item.

    Headings become their own paragraphs (``self.headings`` records each with
    its level), list items get ``- `` or ``1. ``, table cells are joined with
    `` | ``, and an SIL footnote reads ``[Footnote: …]`` instead of running
    into the sentence it annotates.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.lists: list[list] = []  # [kind, items so far]
        self.spans: list[bool] = []  # True for a footnote span
        self.headings: list[tuple[int, str]] = []
        self._heading: list[str] | None = None
        self._cells = 0  # cells so far in the current table row
        self._item_start = False  # just after a list item's marker

    def _at_line_start(self) -> bool:
        tail = "".join(self.parts[-4:]).rstrip(" \t")
        return not tail or tail.endswith("\n")

    def _block_break(self) -> None:
        if self._cells:
            return
        if self.lists:
            if not self._item_start and not self._at_line_start():
                self.parts.append("\n")
        else:
            self.parts.append("\n\n")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "br":
            self.parts.append("\n")
        elif tag in ("ul", "ol"):
            if not self.lists:
                self.parts.append("\n\n")
            self.lists.append([tag, 0])
        elif tag == "li":
            prefix = "- "
            if self.lists:
                self.lists[-1][1] += 1
                if self.lists[-1][0] == "ol":
                    prefix = f"{self.lists[-1][1]}. "
            self.parts.append(prefix if self._at_line_start() else "\n" + prefix)
            self._item_start = True
        elif tag == "tr":
            self._cells = 0
            self.parts.append("\n")
        elif tag in ("td", "th"):
            if self._cells:
                self.parts.append(" | ")
            self._cells += 1
        elif tag == "span":
            footnote = dict(attrs).get("data-bntype") == "footnote"
            self.spans.append(footnote)
            if footnote:
                self.parts.append(" [Footnote: ")
        elif tag in _BLOCK_TAGS:
            self._block_break()
            if tag in _HEADING_TAGS:
                self._heading = []

    def handle_endtag(self, tag: str) -> None:
        if tag in ("ul", "ol"):
            if self.lists:
                self.lists.pop()
            if not self.lists:
                self.parts.append("\n\n")
        elif tag == "span":
            if self.spans and self.spans.pop():
                self.parts.append(_FOOTNOTE_END)
        elif tag == "tr":
            self._cells = 0
        elif tag in _BLOCK_TAGS:
            if tag in _HEADING_TAGS and self._heading is not None:
                heading = _squeeze("".join(self._heading))
                if heading:
                    self.headings.append((int(tag[1]), heading))
                self._heading = None
            if not self._cells and not self.lists:
                self.parts.append("\n\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)
        if data.strip():
            self._item_start = False
        if self._heading is not None and not any(self.spans):
            self._heading.append(data)


def _squeeze(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def _tidy(text: str) -> str:
    """Collapse the renderer's whitespace into paragraphs and lines."""
    text = text.replace("\xa0", " ").replace("\u00ad", "")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\[Footnote: \s*", "[Footnote: ", text)
    text = re.sub(rf"\s*{_FOOTNOTE_END}", "]", text)
    # An unfoldingWord note's "See:" with no link after it.
    text = re.sub(r"(?m)^See:$", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    # The dictionary's "• Section" preview paragraphs read as one list.
    text = re.sub(r"(?m)^(• .*)\n\n(?=• )", r"\1\n", text)
    return text.strip()


def render_aquifer_html(content: str) -> tuple[str, list[tuple[int, str]]]:
    """Plain text of an Aquifer HTML body and its headings as (level, text)."""
    renderer = _AquiferRenderer()
    renderer.feed(_repair_uw_quote_lines(content))
    renderer.close()
    return _tidy("".join(renderer.parts)), renderer.headings


# ---------------------------------------------------------------------------
# unfoldingWord quote lines
# ---------------------------------------------------------------------------

# The quote a translation note annotates, as Aquifer prints it: a paragraph of
# its own, bold, in straight quotes; a discontinuous quote may instead be
# several such pieces joined by " - ".
_UW_QUOTE_PIECE = r"<strong>&quot;[^<]*?&quot;</strong>"
_UW_QUOTE_LINE = re.compile(rf"<p>{_UW_QUOTE_PIECE}(?: - {_UW_QUOTE_PIECE})*</p>")


def repair_uw_quote(quote: str) -> str:
    """Undo the damage the source's quote extraction did to an unfoldingWord ULT quote.

    In the ULT, {braces} mark words implied by the original. The quote is
    the ULT text aligned to the note's Hebrew or Greek words, with segments
    of a discontinuous quote joined by `` & ``; the extraction trimmed brace
    characters from the ends of each segment, so a segment starting inside
    an implied phrase lost its ``{`` ("am} a flower of") and one ending inside
    lost its ``}`` ("the fire {pot"). Each segment gets its brace back; an
    opening brace left with nothing after it is dropped ("Her ways {"). A
    straight quote mark the ULT text itself opens or closes at an end of the
    quote doubles the quote marks Aquifer prints around it, so it is
    dropped: ``""I {am} a flower of Sharon,"`` reads ``"I {am} a flower of Sharon,"``.
    """
    if quote.count('"') == 2 and quote.startswith('"') and quote.endswith('"') and len(quote) > 1:
        quote = quote[1:-1]
    elif quote.count('"') % 2:
        if quote.startswith('"'):
            quote = quote[1:]
        elif quote.endswith('"'):
            quote = quote[:-1]
    return " & ".join(_repair_braces(segment) for segment in quote.split(" & "))


def _repair_braces(segment: str) -> str:
    # A "(" opening an implied word the source closes with "}" ("He (is} swift").
    segment = re.sub(r"\((\w[^(){}]*)\}", r"{\1}", segment)
    depth = missing_open = 0
    for char in segment:
        if char == "{":
            depth += 1
        elif char == "}":
            if depth:
                depth -= 1
            else:
                missing_open += 1
    if depth and re.search(r"\{\s*$", segment):
        segment = re.sub(r"\s*\{\s*$", "", segment)
        depth -= 1
    stripped = segment.rstrip()
    return "{" * missing_open + stripped + "}" * depth + segment[len(stripped):]


def _repair_uw_quote_lines(content: str) -> str:
    def repair_piece(match: re.Match) -> str:
        quote = repair_uw_quote(html.unescape(match.group(1)))
        return f"<strong>&quot;{html.escape(quote, quote=False)}&quot;</strong>"

    def repair_line(match: re.Match) -> str:
        return re.sub(r"<strong>&quot;([^<]*?)&quot;</strong>", repair_piece, match.group(0))

    return _UW_QUOTE_LINE.sub(repair_line, content)


# ---------------------------------------------------------------------------
# Aquifer items
# ---------------------------------------------------------------------------

# "Genesis 11:27–25.11": Tyndale's titles put a period between the end
# chapter and verse of a range that crosses chapters.
_PERIOD_RANGE = re.compile(r"(\d+:\d+[–-])(\d+)\.(\d+)\b")


def aquifer_title(item: dict) -> str:
    """An item's title, unescaped, with a cross-chapter range written 'C:V'."""
    title = html.unescape(item.get("title") or "")
    if item.get("resource_type") == "study_notes":
        title = _PERIOD_RANGE.sub(r"\1\2:\3", title)
    return title


def aquifer_rendering(item: dict) -> tuple[str, list[tuple[int, str]]]:
    """An item's cleaned plain text (with any correction notes) and its headings."""
    content = item.get("content")
    if content:
        text, headings = render_aquifer_html(content)
    else:
        text, headings = _tidy(html.unescape(item.get("content_plain") or "")), []
    return apply_corrections(text, item), headings


def aquifer_text(item: dict) -> str:
    """An item's cleaned plain text, with any correction notes."""
    return aquifer_rendering(item)[0]


def clean_aquifer_items(items: list[dict]) -> list[dict]:
    """Copies of Aquifer rows with ``title`` and ``content_plain`` cleaned for display."""
    return [
        {**item, "title": aquifer_title(item), "content_plain": aquifer_text(item)}
        for item in items
    ]


# ---------------------------------------------------------------------------
# Curated corrections
# ---------------------------------------------------------------------------

_CORRECTION_FIELDS = {"resource_type", "content_id", "title", "match", "note"}
_TRANSCRIPTION_FIELDS = {"corpus", "work_key", "reference", "field", "find", "replace", "reason"}


@lru_cache(maxsize=1)
def load_corrections(path: Path | None = None) -> dict:
    """The curated corrections file, validated: ``corrections`` and ``transcriptions`` lists."""
    data = json.loads((path or CORRECTIONS_PATH).read_text(encoding="utf-8"))
    corrections = data.get("corrections", [])
    transcriptions = data.get("transcriptions", [])
    for entry in corrections:
        unknown = set(entry) - _CORRECTION_FIELDS
        if unknown or not entry.get("resource_type") or not entry.get("match") or not entry.get("note"):
            raise ValueError(f"Malformed correction {entry!r}")
        if "content_id" not in entry and "title" not in entry:
            raise ValueError(f"Correction {entry['match']!r} names neither a content_id nor a title")
        if "]" in entry["note"] or len(entry["note"]) > MAX_CORRECTION_LENGTH:
            raise ValueError(f"Correction note for {entry['match']!r} is too long or contains ']'")
    for entry in transcriptions:
        if set(entry) != _TRANSCRIPTION_FIELDS or entry["field"] not in ("text", "original_text"):
            raise ValueError(f"Malformed transcription fix {entry!r}")
        if entry["find"] == entry["replace"]:
            raise ValueError(f"Transcription fix {entry['find']!r} changes nothing")
    return {"corrections": corrections, "transcriptions": transcriptions}


def _correction_applies(entry: dict, item: dict) -> bool:
    if entry["resource_type"] != item.get("resource_type"):
        return False
    if "content_id" in entry:
        return entry["content_id"] == item.get("content_id")
    return entry["title"].casefold() == (item.get("title") or "").casefold()


def correction_note(note: str) -> str:
    return f" [{CORRECTION_MARK}{note}]"


def apply_corrections(text: str, item: dict) -> str:
    """``text`` with each correction for this item inserted right after its matched text.

    A correction whose text is not found (an article revised upstream) is
    skipped rather than misplaced.
    """
    for entry in load_corrections()["corrections"]:
        if not _correction_applies(entry, item):
            continue
        index = text.find(entry["match"])
        if index < 0:
            continue
        end = index + len(entry["match"])
        text = text[:end] + correction_note(entry["note"]) + text[end:]
    return text


def safe_cut(text: str, cut: int) -> int:
    """``cut`` moved past any correction note it would split from the text it corrects.

    A cut inside the corrected text, or between it and its note, would show
    the error without the correction; the note's end is returned instead.
    """
    if CORRECTION_MARK not in text:
        return cut
    for entry in load_corrections()["corrections"]:
        flagged = entry["match"] + correction_note(entry["note"])
        start = text.find(flagged)
        while start >= 0:
            end = start + len(flagged)
            if start < cut < end:
                return end
            start = text.find(flagged, end)
    return cut


# ---------------------------------------------------------------------------
# Ancient-source transcription slips
# ---------------------------------------------------------------------------


def fix_ancient_row(row: dict) -> dict:
    """``row`` with its listed transcription slips fixed (a copy, or ``row`` itself if none)."""
    fixed = None
    for entry in load_corrections()["transcriptions"]:
        if (
            entry["corpus"] == row.get("corpus")
            and entry["work_key"] == row.get("work_key")
            and entry["reference"] == row.get("reference")
            and entry["find"] in (row.get(entry["field"]) or "")
        ):
            fixed = fixed or dict(row)
            fixed[entry["field"]] = fixed[entry["field"]].replace(entry["find"], entry["replace"])
    return fixed or row
