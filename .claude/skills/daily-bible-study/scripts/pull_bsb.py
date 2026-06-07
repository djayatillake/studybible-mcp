#!/usr/bin/env python3
"""Print smooth BSB text for one or more passages from db/study_bible.db (table bsb_verses).

Usage:
  pull_bsb.py [--db PATH] "Proverbs 1:8-19" "Matthew 7:1-23" "Genesis 17" "Psalm 6" "1 Samuel 2:1-10"

Each ref: "<Book> <chapter>[:<verse>[-<verse>]]". No verse range => whole chapter.
The smooth BSB is the text to put in the post body; the MCP lookup_verse tool returns
a wooden interlinear and only the first verse of a range, so use this instead.
"""
import argparse, re, sqlite3, sys

# full names / common aliases -> the codes actually used in bsb_verses
BOOKS = {
    "genesis":"Gen","exodus":"Exo","leviticus":"Lev","numbers":"Num","deuteronomy":"Deu",
    "joshua":"Jos","judges":"Jdg","ruth":"Rut","1samuel":"1Sa","2samuel":"2Sa",
    "1kings":"1Ki","2kings":"2Ki","1chronicles":"1Ch","2chronicles":"2Ch","ezra":"Ezr",
    "nehemiah":"Neh","esther":"Est","job":"Job","psalm":"Psa","psalms":"Psa",
    "proverbs":"Pro","ecclesiastes":"Ecc","songofsongs":"Sng","songofsolomon":"Sng",
    "canticles":"Sng","song":"Sng","isaiah":"Isa","jeremiah":"Jer","lamentations":"Lam",
    "ezekiel":"Ezk","daniel":"Dan","hosea":"Hos","joel":"Jol","amos":"Amo","obadiah":"Oba",
    "jonah":"Jon","micah":"Mic","nahum":"Nam","habakkuk":"Hab","zephaniah":"Zep",
    "haggai":"Hag","zechariah":"Zec","malachi":"Mal","matthew":"Mat","mark":"Mrk",
    "luke":"Luk","john":"Jhn","acts":"Act","romans":"Rom","1corinthians":"1Co",
    "2corinthians":"2Co","galatians":"Gal","ephesians":"Eph","philippians":"Php",
    "colossians":"Col","1thessalonians":"1Th","2thessalonians":"2Th","1timothy":"1Ti",
    "2timothy":"2Ti","titus":"Tit","philemon":"Phm","hebrews":"Heb","james":"Jas",
    "1peter":"1Pe","2peter":"2Pe","1john":"1Jn","2john":"2Jn","3john":"3Jn",
    "jude":"Jud","revelation":"Rev",
}

REF_RE = re.compile(r"^\s*((?:[1-3]\s*)?[A-Za-z][A-Za-z ]*?)\s+(\d+)(?::(\d+)(?:\s*[-–]\s*(\d+))?)?\s*$")

def resolve(book, codes):
    n = re.sub(r"\s+", "", book).lower()
    if n in BOOKS and BOOKS[n] in codes:
        return BOOKS[n]
    for c in codes:                       # last resort: exact code or prefix
        if c.lower() == n:
            return c
    raise SystemExit(f"Can't resolve book {book!r}. Known codes: {sorted(codes)}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="db/study_bible.db")
    ap.add_argument("refs", nargs="+")
    a = ap.parse_args()
    con = sqlite3.connect(a.db)
    codes = {r[0] for r in con.execute("SELECT DISTINCT book FROM bsb_verses")}
    for ref in a.refs:
        m = REF_RE.match(ref)
        if not m:
            print(f"!! could not parse {ref!r}", file=sys.stderr); continue
        book, ch, v1, v2 = m.group(1), int(m.group(2)), m.group(3), m.group(4)
        code = resolve(book, codes)
        lo = int(v1) if v1 else 1
        hi = int(v2) if v2 else (int(v1) if v1 else 999)
        rows = con.execute(
            "SELECT verse, text FROM bsb_verses WHERE book=? AND chapter=? "
            "AND verse BETWEEN ? AND ? ORDER BY verse", (code, ch, lo, hi)).fetchall()
        print(f"===== {ref} =====")
        for v, t in rows:
            print(f"{v}  {t}")
        print()

if __name__ == "__main__":
    main()
