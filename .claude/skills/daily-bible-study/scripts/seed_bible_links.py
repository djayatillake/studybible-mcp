#!/usr/bin/env python3
"""Link each Part One reading heading to its chapter on Seed Bible. Run from the repo root:

    .venv-tts/bin/python .claude/skills/daily-bible-study/scripts/seed_bible_links.py \
        podcast/dayN/Bible_in_a_Year_Study_DayN.html

In Part One (from the "Part One — The Readings" h2 to the next h2), the reference that starts
each h3 is wrapped in a link to that chapter in the BSB, with the section's verses highlighted:

    <h3><a href="https://seedbible.org/?translation=BSB&amp;book=2KI&amp;chapter=4&amp;verse=18-37">2 Kings 4:18–37</a>
    <span class="ref">— The son lost and given back</span></h3>

The link adds no words: clean.py voices the heading's text as before. Seed Bible shows the whole
chapter and highlights the verses named. translation=BSB is always set, since its English default
is a different translation. A whole chapter ("Psalm 23") links the bare chapter; a cross-chapter
heading ("Joshua 13:1–14:5") links its first chapter. Headings already linked are left alone, so
re-running is safe. Exits 1 if a Part One heading starts with no reference it can resolve.
"""
import re
import sys
from html import escape, unescape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pull_bsb import BOOKS  # noqa: E402  (book names -> this project's codes)

SEED_BIBLE_URL = "https://seedbible.org/"
PART_ONE = "Part One — The Readings"
# "2 Kings 4:18–37", "Psalm 23", "Song of Songs 2:1", "Joshua 13:1–14:5" at the start of a heading.
HEADING_REF = re.compile(
    r"^\s*(?P<book>(?:[1-3]\s*)?[A-Za-z]+(?:\s+[A-Za-z]+)*?)\s+(?P<chapter>\d+)"
    r"(?::(?P<v1>\d+)[a-c]?(?:\s*[-–]\s*(?P<v2>\d+)[a-c]?(?P<cross>:\d+[a-c]?)?)?)?"
)
# The same reference as written in the HTML source, where the dash may be an entity (older posts
# use &ndash;). The file is edited as text so everything else stays byte-for-byte as it was.
# Half verses ("7:1–8a") link their whole verse; in a list ("Mark 8:14–38; 9:1") the first
# reference is linked.
_DASH = r"(?:-|–|&ndash;|&#8211;|&#x2013;)"
RAW_REF = re.compile(
    r"\s*(?:[1-3]\s*)?[A-Za-z]+(?:\s+[A-Za-z]+)*?\s+\d+"
    r"(?::\d+[a-c]?(?:\s*" + _DASH + r"\s*\d+[a-c]?(?::\d+[a-c]?)?)?)?(?=[\s<;,])"
)
PART_ONE_H2 = re.compile(r"<h2[^>]*>\s*Part One (?:—|&mdash;|&#8212;) The Readings\s*</h2>")
H3_OPEN = re.compile(r"<h3(?:\s[^>]*)?>")


def seed_bible_url(code, chapter, v1=None, v2=None):
    """The Seed Bible URL for a chapter, highlighting v1 or v1-v2; its book parameter is the USFM code.

    USFM codes for the 66 books are this project's codes uppercased ('Ezk' -> 'EZK').
    """
    url = f"{SEED_BIBLE_URL}?translation=BSB&book={code.upper()}&chapter={chapter}"
    if v1:
        url += f"&verse={v1}" + (f"-{v2}" if v2 and int(v2) > int(v1) else "")
    return url


def heading_link(text):
    """(matched reference text, URL) for a heading that starts with a reference, else None."""
    m = HEADING_REF.match(text)
    if not m:
        return None
    code = BOOKS.get(re.sub(r"\s+", "", m["book"]).lower())
    if not code:
        return None
    if m["cross"]:  # a cross-chapter range opens its first chapter
        return m.group(0).strip(), seed_bible_url(code, m["chapter"])
    return m.group(0).strip(), seed_bible_url(code, m["chapter"], m["v1"], m["v2"])


def part_one_headings(soup):
    """The h3 elements between the Part One h2 and the next h2."""
    wrap = soup.find("div", class_="wrap") or soup
    heads, inside = [], False
    for el in wrap.find_all(recursive=False):
        if el.name == "h2":
            if inside:
                break
            inside = el.get_text(strip=True) == PART_ONE
        elif inside and el.name == "h3":
            heads.append(el)
    return heads


def main(path):
    raw = Path(path).read_text(encoding="utf-8")
    start_match = PART_ONE_H2.search(raw)
    if not start_match:
        sys.exit(f'no "{PART_ONE}" h2 in {path}')
    start = start_match.end()
    end = raw.find("<h2", start)
    end = len(raw) if end < 0 else end
    region, out, pos = raw[start:end], [], 0
    added, unresolved = [], []
    for h3 in H3_OPEN.finditer(region):
        body = h3.end()
        if re.match(r"\s*<a[\s>]", region[body:body + 50]):
            continue  # already linked
        m = RAW_REF.match(region, body)
        found = heading_link(unescape(m.group(0))) if m else None
        if found is None:
            text = re.sub(r"<[^>]+>", "", region[body:region.find("</h3>", body)])
            unresolved.append(unescape(text).strip()[:60])
            continue
        lead = len(m.group(0)) - len(m.group(0).lstrip())
        ref_start = body + lead
        _, url = found
        out.append(region[pos:ref_start])
        out.append(f'<a href="{escape(url)}">{region[ref_start:m.end()]}</a>')
        pos = m.end()
        added.append(f"{unescape(region[ref_start:m.end()])} -> {url}")
    out.append(region[pos:])
    Path(path).write_text(raw[:start] + "".join(out) + raw[end:], encoding="utf-8")
    for line in added:
        print("linked", line)
    print(f"{len(added)} heading(s) linked")
    for text in unresolved:
        print("UNRESOLVED:", text)
    if unresolved:
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
