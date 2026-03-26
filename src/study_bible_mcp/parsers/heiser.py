"""Parser for Heiser content JSON files and theme taxonomy."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Generator

# Book abbreviation mapping (same as database.py)
BOOK_ABBREVS = {
    "Gen": "Gen", "Exo": "Exo", "Lev": "Lev", "Num": "Num", "Deu": "Deu",
    "Jos": "Jos", "Jdg": "Jdg", "Rut": "Rut", "1Sa": "1Sa", "2Sa": "2Sa",
    "1Ki": "1Ki", "2Ki": "2Ki", "1Ch": "1Ch", "2Ch": "2Ch", "Ezr": "Ezr",
    "Neh": "Neh", "Est": "Est", "Job": "Job", "Psa": "Psa", "Pro": "Pro",
    "Ecc": "Ecc", "Sng": "Sng", "Isa": "Isa", "Jer": "Jer", "Lam": "Lam",
    "Eze": "Eze", "Dan": "Dan", "Hos": "Hos", "Joe": "Joe", "Amo": "Amo",
    "Oba": "Oba", "Jon": "Jon", "Mic": "Mic", "Nah": "Nah", "Hab": "Hab",
    "Zep": "Zep", "Hag": "Hag", "Zec": "Zec", "Mal": "Mal",
    "Mat": "Mat", "Mrk": "Mrk", "Luk": "Luk", "Jhn": "Jhn", "Act": "Act",
    "Rom": "Rom", "1Co": "1Co", "2Co": "2Co", "Gal": "Gal", "Eph": "Eph",
    "Php": "Php", "Col": "Col", "1Th": "1Th", "2Th": "2Th", "1Ti": "1Ti",
    "2Ti": "2Ti", "Tit": "Tit", "Phm": "Phm", "Heb": "Heb", "Jas": "Jas",
    "1Pe": "1Pe", "2Pe": "2Pe", "1Jn": "1Jn", "2Jn": "2Jn", "3Jn": "3Jn",
    "Jud": "Jud", "Rev": "Rev",
}


def parse_reference(ref: str) -> tuple[str, int | None, int | None]:
    """Parse a reference like 'Deu.32.8' into (book, chapter, verse)."""
    parts = ref.split(".")
    book = parts[0] if parts else ""
    chapter = int(parts[1]) if len(parts) > 1 else None
    verse = int(parts[2]) if len(parts) > 2 else None
    return book, chapter, verse


def parse_themes_file(filepath: str | Path) -> list[dict]:
    """Parse the themes.json taxonomy file.

    Returns list of theme dicts ready for DB insertion.
    """
    with open(filepath) as f:
        data = json.load(f)

    themes = []
    for theme in data["themes"]:
        themes.append({
            "theme_key": theme["theme_key"],
            "theme_label": theme["theme_label"],
            "description": theme["description"],
            "parent_theme": theme.get("parent_theme"),
            "heiser_key_works": json.dumps(theme.get("heiser_key_works", [])),
        })
    return themes


def parse_heiser_content_file(filepath: str | Path) -> Generator[tuple[dict, list[dict], list[str]], None, None]:
    """Parse a Heiser content JSON file.

    Yields tuples of:
      (content_entry, verse_references, theme_keys)

    where content_entry is ready for heiser_content table insertion,
    verse_references is a list of {reference, book, chapter, verse, relevance},
    and theme_keys is a list of theme_key strings.
    """
    with open(filepath) as f:
        data = json.load(f)

    source_key = data["source_key"]
    author = data.get("author", "heiser")
    source_type = data.get("type", "article")
    url = data.get("url")

    for entry in data.get("entries", []):
        content_entry = {
            "source_work": source_key,
            "source_author": author,
            "source_type": source_type,
            "chapter_or_episode": entry.get("chapter_or_episode"),
            "title": entry["title"],
            "content_summary": entry["content_summary"],
            "content_detail": entry.get("content_detail"),
            "page_range": entry.get("page_range"),
            "url": url,
        }

        verse_refs = []
        for ref_entry in entry.get("references", []):
            ref_str = ref_entry["reference"]
            book, chapter, verse = parse_reference(ref_str)
            verse_refs.append({
                "reference": ref_str,
                "book": book,
                "chapter": chapter,
                "verse": verse,
                "relevance": ref_entry.get("relevance", "primary"),
            })

        theme_keys = entry.get("themes", [])

        yield content_entry, verse_refs, theme_keys
