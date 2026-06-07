#!/usr/bin/env python3
"""Emit a Substack-ready body from the day's study HTML.

Drops the elements that already live in the Substack title & subtitle fields
(the kicker line, the <h1> passage list, the "Day N …" banner, and the first ❦
ornament) and strips class attributes. The result is the paste-target for the
clipboard -> Cmd+V step. Output: <work>/body_substack.html

Usage:
  make_substack_body.py --html podcast/dayN/Bible_in_a_Year_Study_DayN.html --work podcast/dayN
"""
import argparse, os
from bs4 import BeautifulSoup

def first_decompose(wrap, name, cls=None):
    el = wrap.find(name, class_=cls) if cls else wrap.find(name)
    if el:
        el.decompose()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", required=True)
    ap.add_argument("--work", required=True)
    a = ap.parse_args()

    soup = BeautifulSoup(open(a.html, encoding="utf-8").read(), "lxml")
    wrap = soup.find("div", class_="wrap") or soup.body or soup

    first_decompose(wrap, "p", "kicker")
    first_decompose(wrap, "p", "banner")
    first_decompose(wrap, "h1")
    first_decompose(wrap, "p", "orn")     # the ornament that sat right after the h1
    for t in wrap.find_all(True):
        t.attrs.pop("class", None)

    body = wrap.decode_contents().strip()
    out = os.path.join(a.work, "body_substack.html")
    open(out, "w", encoding="utf-8").write(body)
    print(f"wrote {out} ({len(body)} chars)\n  starts: {body[:90]!r}")

if __name__ == "__main__":
    main()
