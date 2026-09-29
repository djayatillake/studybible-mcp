#!/usr/bin/env python3
"""Sanity-check an assembled daily-study HTML file. Run from the repo root:

    .venv-tts/bin/python .claude/skills/daily-bible-study/scripts/check_html.py \
        podcast/dayN/Bible_in_a_Year_Study_DayN.html

Fails (exit 1) if any of these is wrong:
  * more than one <div>, or the children of div.wrap are not flat (clean.py only recurses one level)
  * the literal "Part One — The Readings" h2 is missing or repeated (the audio intro-strip needs it)
  * Hebrew/Greek script outside a <strong> (clean.py only strips script that is bold)
  * a block (li, p, blockquote, h2, h3) whose first visible character is Hebrew: Substack, like any
    browser using dir="auto", lays a Hebrew-first block out right-to-left and scrambles the line.
    Lead with English instead:  <em>chesed</em> (<strong>חֶסֶד</strong>, H2617) — goodness…

Warns (does not fail) when a Part One bullet's bold label contains script: clean.py strips a script-bearing
<strong> whole, so the spoken label would vanish.

Prints the <sup> count (should equal the reading verses plus any Part Two lead quotes) and word counts
per part, with an estimate of spoken minutes at ~160 words a minute.
"""
import re
import sys

from bs4 import BeautifulSoup

HEB = re.compile(r'[֐-׿؀-ۿ]')
SCRIPT = re.compile(r'[֐-׿Ͱ-Ͽἀ-῿]')


def main(path):
    raw = open(path, encoding='utf-8').read()
    soup = BeautifulSoup(raw, 'html.parser')
    fails, warns = [], []

    n_div = len(soup.find_all('div'))
    if n_div != 1:
        fails.append('expected exactly one <div>, found %d' % n_div)
    wrap = soup.find('div', class_='wrap')
    if wrap is None:
        sys.exit('no div.wrap found')
    nested = sorted({c.name for c in wrap.find_all(recursive=False) if c.name in ('div', 'section', 'header', 'article')})
    if nested:
        fails.append('div.wrap has non-flat children: %s' % nested)

    n_p1 = sum(1 for h in soup.find_all('h2') if h.get_text(strip=True) == 'Part One — The Readings')
    if n_p1 != 1:
        fails.append('"Part One — The Readings" h2 count is %d (must be 1)' % n_p1)

    bare = []
    for s in soup.find_all(string=SCRIPT):
        if s.find_parent('title') is not None:
            continue
        if not any(p.name in ('strong', 'b') for p in s.parents):
            bare.append(s.strip()[:50])
    if bare:
        fails.append('script outside <strong>: %s' % bare[:5])

    rtl = []
    for el in wrap.find_all(['li', 'p', 'blockquote', 'h2', 'h3']):
        t = el.get_text(' ', strip=True)
        if t and HEB.match(t[0]):
            rtl.append(t[:50])
    if rtl:
        fails.append('%d block(s) start with Hebrew and will render right-to-left in Substack, e.g. %s' % (len(rtl), rtl[:3]))

    part = None
    counts = {'one': 0, 'two': 0, 'three': 0}
    for el in wrap.find_all(recursive=False):
        t = el.get_text(' ', strip=True)
        if el.name == 'h2':
            part = 'one' if t.startswith('Part One') else 'two' if t.startswith('Part Two') else 'three' if t.startswith('Part Three') else part
            continue
        if part:
            counts[part] += len(t.split())
        if part == 'one' and el.name == 'ul':
            for li in el.find_all('li', recursive=False):
                st = li.find('strong')
                if st is not None and li.get_text(strip=True).startswith(st.get_text(strip=True)) and SCRIPT.search(st.get_text()) \
                        and re.search(r'[A-Za-z]{3,}', st.get_text()):
                    warns.append('script inside a bold label: %s' % st.get_text()[:50])

    n_sup = len(soup.find_all('sup'))
    print('<sup> count: %d (reading verses + Part Two lead quotes)' % n_sup)
    print('words: Part One %d (incl. verses), Part Two %d, Part Three %d; ~%.0f spoken min at 160 wpm'
          % (counts['one'], counts['two'], counts['three'], sum(counts.values()) / 160))
    for w in warns:
        print('WARN:', w)
    if fails:
        for f in fails:
            print('FAIL:', f)
        sys.exit(1)
    print('OK')


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
