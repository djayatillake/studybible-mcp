#!/usr/bin/env python3
"""Build the podcast raw JSON DIRECTLY from the day's study HTML, preserving the
<sup> verse numbers and <strong>Hebrew/Greek</strong> tags so the substack-podcast
clean.py can strip verse numbers, original-language script, and Strong's natively.

Do NOT use the skill's html_to_raw.py for this: it flattens <sup> into plain text,
which leaks verse numbers into the spoken audio.

Usage:
  make_audio_input.py --html podcast/dayN/Bible_in_a_Year_Study_DayN.html \
      --work podcast/dayN --title "Day N · …" --subtitle "Passage · Passage" \
      --date YYYY-MM-DD [--track 1]
"""
import argparse, json, os, re
from bs4 import BeautifulSoup

def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:50] or "post"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--subtitle", default="")
    ap.add_argument("--date", default="")
    ap.add_argument("--track", type=int, default=1)
    a = ap.parse_args()

    soup = BeautifulSoup(open(a.html, encoding="utf-8").read(), "lxml")
    wrap = soup.find("div", class_="wrap") or soup.body or soup
    body_html = wrap.decode_contents()

    out = {
        "title": a.title, "subtitle": a.subtitle, "body_html": body_html,
        "post_date": (a.date + "T00:00:00Z") if a.date else "",
        "cover_image": None, "audience": "everyone",
    }
    os.makedirs(os.path.join(a.work, "raw"), exist_ok=True)
    fn = os.path.join(a.work, "raw", f"{a.track:02d}_{slugify(a.title)}.json")
    json.dump(out, open(fn, "w"), ensure_ascii=False)
    print(f"wrote {fn}\n  title:    {a.title}\n  body_html chars: {len(body_html)}")

if __name__ == "__main__":
    main()
