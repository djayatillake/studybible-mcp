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
    # Substack's editor flattens a pasted <table> into one run-on paragraph, so
    # convert each table into an <ol>: one <li> per body row, the first cell
    # bolded as the row label and the rest as "Header: cell" sentences.
    for table in wrap.find_all("table"):
        rows = table.find_all("tr")
        heads = [th.get_text(" ", strip=True) for th in rows[0].find_all(["th", "td"])] if rows else []
        ol = soup.new_tag("ol")
        for tr in rows[1:]:
            cells = tr.find_all(["td", "th"])
            if not cells:
                continue
            li = soup.new_tag("li")
            # row label = first non-index cell (skip a leading "#"-style number)
            start = 1 if heads and heads[0].strip() in ("#", "") and len(cells) > 1 else 0
            label = cells[start]
            b = soup.new_tag("strong"); b.string = label.get_text(" ", strip=True) + "."
            li.append(b)
            for i in range(start + 1, len(cells)):
                c = cells[i].get_text(" ", strip=True)
                if not c or c in ("—", "-"):
                    continue
                h = heads[i] if i < len(heads) else ""
                sent = f" {h}: {c}" if h else f" {c}"
                if not sent.rstrip().endswith((".", "!", "?", ")")):
                    sent += "."
                li.append(soup.new_string(sent))
            ol.append(li)
        table.replace_with(ol)

    for t in wrap.find_all(True):
        t.attrs.pop("class", None)

    body = wrap.decode_contents().strip()
    out = os.path.join(a.work, "body_substack.html")
    open(out, "w", encoding="utf-8").write(body)
    print(f"wrote {out} ({len(body)} chars)\n  starts: {body[:90]!r}")

if __name__ == "__main__":
    main()
