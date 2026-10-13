"""Citation locator grammars: locator text to an inclusive integer sort range.

A work's locator turns the part of a citation after the work name ('18.116',
'3:5-7', 'VI, 11') into ``(sort_start, sort_end)``. Passages store keys from the
same grammar in ``ancient_source_passages.sort_start``/``sort_end`` (built with
the locator's ``key`` method), so a lookup is a plain interval-overlap query.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

SortRange = tuple[int, int]

_DASH = re.compile(r"\s*[-‐‑‒–—]\s*")
_SEPARATOR = re.compile(r"\s*[.:,]\s*|\s+")
_TRAILING = re.compile(r"[\s.;,]+$")
_ROMAN = re.compile(
    r"(?=[mdclxvi])m{0,3}(cm|cd|d?c{0,3})(xc|xl|l?x{0,3})(ix|iv|v?i{0,3})", re.IGNORECASE
)
_ROMAN_VALUES = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}


class Locator(Protocol):
    """Interface every work's citation grammar implements."""

    name: str
    example: str

    def parse(self, text: str) -> SortRange | None:
        """Inclusive sort range for locator text, or None if it is not this grammar."""

    def format_range(self, start: int, end: int) -> str:
        """Render a sort range as locator text ('18.116–119')."""


def _pieces(text: str) -> list[str] | None:
    """Split cleaned locator text into a start and an optional range end."""
    pieces = _DASH.split(_TRAILING.sub("", text.strip()))
    return pieces if len(pieces) <= 2 and all(pieces) else None


def roman_to_int(text: str) -> int | None:
    """Value of a Roman numeral ('vi', 'XIV'), or None if ``text`` is not one."""
    if not text or not _ROMAN.fullmatch(text):
        return None
    values = [_ROMAN_VALUES[ch] for ch in text.lower()]
    return sum(
        -value if index + 1 < len(values) and value < values[index + 1] else value
        for index, value in enumerate(values)
    )


@dataclass(frozen=True)
class NumberedLocator:
    """Hierarchical numbers: 'section', 'book.section', 'chapter:verse', 'column:line'.

    ``depth`` levels pack into one integer, each subordinate level in base
    ``scale``: ``key(18, 116) == 18 * scale + 116``. Levels may be separated by
    ``.``, ``:``, ``,`` or a space; any dash separates a range. Accepted forms:

    - a point ``18.116`` or a prefix ``18`` (every subordinate unit of book 18);
    - ``18.116-119`` (the end replaces the start's last levels), ``18.116-19.5``
      (across units), or ``11-12`` (a range of top-level units).

    ``roman=True`` also accepts a Roman numeral at the top level ('VI 11',
    'vi, 11'), as used for scroll columns.
    """

    name: str
    example: str
    depth: int = 2
    scale: int = 1000
    separator: str = "."
    roman: bool = False

    def key(self, *parts: int) -> int:
        """Sort key of a full point, e.g. ``key(18, 116)``; raises on bad parts."""
        if len(parts) != self.depth:
            raise ValueError(f"{self.name}: expected {self.depth} parts, got {parts}")
        if any(part < 0 for part in parts) or any(part >= self.scale for part in parts[1:]):
            raise ValueError(f"{self.name}: part out of range in {parts}")
        value = 0
        for part in parts:
            value = value * self.scale + part
        return value

    def _numbers(self, text: str, includes_top: bool, max_levels: int) -> list[int] | None:
        tokens = _SEPARATOR.split(text)
        if not 1 <= len(tokens) <= max_levels:
            return None
        numbers: list[int] = []
        for index, token in enumerate(tokens):
            top = includes_top and index == 0
            if token.isdigit():
                value = int(token)
            elif self.roman and top and (roman := roman_to_int(token)) is not None:
                value = roman
            else:
                return None
            if not top and value >= self.scale:
                return None
            numbers.append(value)
        return numbers

    def _bounds(self, parts: list[int]) -> SortRange:
        missing = self.depth - len(parts)
        return self.key(*parts, *[0] * missing), self.key(*parts, *[self.scale - 1] * missing)

    def parse(self, text: str) -> SortRange | None:
        pieces = _pieces(text)
        if pieces is None:
            return None
        start = self._numbers(pieces[0], includes_top=True, max_levels=self.depth)
        if start is None:
            return None
        end = start
        if len(pieces) == 2:
            levels = len(_SEPARATOR.split(pieces[1]))
            tail = self._numbers(pieces[1], includes_top=levels == len(start), max_levels=len(start))
            if tail is None:
                return None
            end = start[: len(start) - len(tail)] + tail
        low, high = self._bounds(start)[0], self._bounds(end)[1]
        return (low, high) if low <= high else None

    def _levels(self, key: int) -> list[int]:
        parts = []
        for _ in range(self.depth - 1):
            key, part = divmod(key, self.scale)
            parts.append(part)
        parts.append(key)
        return parts[::-1]

    def format_range(self, start: int, end: int) -> str:
        first, last = self._levels(start), self._levels(end)
        # Collapse whole subordinate units: (18.0, 18.999) renders as '18'.
        while len(first) > 1 and first[-1] == 0 and last[-1] == self.scale - 1:
            first, last = first[:-1], last[:-1]
        render = lambda parts: self.separator.join(str(part) for part in parts)  # noqa: E731
        if first == last:
            return render(first)
        shared = 0
        while shared < len(first) - 1 and first[shared] == last[shared]:
            shared += 1
        return f"{render(first)}–{render(last[shared:])}"


SECTION = NumberedLocator("section", "116", depth=1)
BOOK_SECTION = NumberedLocator("book.section", "18.116")
CHAPTER_VERSE = NumberedLocator("chapter:verse", "1:1", separator=":")
COLUMN_LINE = NumberedLocator("column:line", "6:11", separator=":", roman=True)
