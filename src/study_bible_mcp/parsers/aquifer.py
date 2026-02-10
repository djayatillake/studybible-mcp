"""
Parser for BibleAquifer standard JSON content files.

All standard Aquifer resources (study notes, dictionary, translation notes,
key terms) share an identical JSON schema:

{
  "content_id": 18794,
  "title": "John 1:1",
  "index_reference": "43001001",   // or "43001001-43001018" for ranges
  "content": "<p>HTML content...</p>",
  "associations": { "passage": [...], "resource": [...] }
}

This module provides a generic parser that works for all resource types.
"""

import json
import re
from pathlib import Path
from typing import Iterator


# Book number to 3-letter abbreviation mapping (BBCCCVVV format uses 2-digit book numbers)
_BOOK_NUM_TO_ABBR = {
    1: "Gen", 2: "Exo", 3: "Lev", 4: "Num", 5: "Deu",
    6: "Jos", 7: "Jdg", 8: "Rut", 9: "1Sa", 10: "2Sa",
    11: "1Ki", 12: "2Ki", 13: "1Ch", 14: "2Ch", 15: "Ezr",
    16: "Neh", 17: "Est", 18: "Job", 19: "Psa", 20: "Pro",
    21: "Ecc", 22: "Sng", 23: "Isa", 24: "Jer", 25: "Lam",
    26: "Ezk", 27: "Dan", 28: "Hos", 29: "Jol", 30: "Amo",
    31: "Oba", 32: "Jon", 33: "Mic", 34: "Nam", 35: "Hab",
    36: "Zep", 37: "Hag", 38: "Zec", 39: "Mal",
    40: "Mat", 41: "Mrk", 42: "Luk", 43: "Jhn", 44: "Act",
    45: "Rom", 46: "1Co", 47: "2Co", 48: "Gal", 49: "Eph",
    50: "Php", 51: "Col", 52: "1Th", 53: "2Th", 54: "1Ti",
    55: "2Ti", 56: "Tit", 57: "Phm", 58: "Heb", 59: "Jas",
    60: "1Pe", 61: "2Pe", 62: "1Jn", 63: "2Jn", 64: "3Jn",
    65: "Jud", 66: "Rev",
}


def strip_html(html: str) -> str:
    """Strip HTML tags and convert to plain text."""
    if not html:
        return ''

    text = html

    # Convert block elements to newlines
    text = re.sub(r'<br\s*/?>', '\n', text)
    text = re.sub(r'</p>\s*<p[^>]*>', '\n\n', text)
    text = re.sub(r'</(div|h[1-6]|li|tr)>', '\n', text)

    # Strip all remaining tags
    text = re.sub(r'<[^>]+>', '', text)

    # Decode common HTML entities
    text = text.replace('&amp;', '&')
    text = text.replace('&lt;', '<')
    text = text.replace('&gt;', '>')
    text = text.replace('&quot;', '"')
    text = text.replace('&#39;', "'")
    text = text.replace('&nbsp;', ' ')
    text = text.replace('&mdash;', '—')
    text = text.replace('&ndash;', '–')

    # Clean up whitespace
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = text.strip()

    return text


def _parse_ref(ref_str: str) -> dict:
    """Parse an 8-digit BBCCCVVV reference string.

    Returns dict with book_num, chapter, verse, book (3-letter abbr).
    """
    ref_str = ref_str.strip()
    if len(ref_str) < 8:
        ref_str = ref_str.zfill(8)

    try:
        book_num = int(ref_str[:2])
        chapter = int(ref_str[2:5])
        verse = int(ref_str[5:8])
    except (ValueError, IndexError):
        return {}

    book_abbr = _BOOK_NUM_TO_ABBR.get(book_num, '')

    return {
        'book_num': book_num,
        'chapter': chapter,
        'verse': verse,
        'book': book_abbr,
    }


def parse_aquifer_content_file(
    filepath: Path,
    resource_type: str,
    book_num: int | None = None,
) -> Iterator[dict]:
    """Parse a standard Aquifer JSON content file.

    Args:
        filepath: Path to the JSON file
        resource_type: One of 'study_notes', 'dictionary',
                       'translation_notes_uw', 'translation_notes_sil', 'key_terms'
        book_num: Book number for per-book files (1-66), or None for non-book files

    Yields:
        Dicts ready for database insertion into aquifer_content table.
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Handle both array and object formats
    if isinstance(data, dict):
        items = data.get('content', data.get('items', [data]))
        if isinstance(items, dict):
            items = [items]
    elif isinstance(data, list):
        items = data
    else:
        return

    for item in items:
        if not isinstance(item, dict):
            continue

        content_id = item.get('content_id', 0)
        title = item.get('title', '')
        index_ref = str(item.get('index_reference', ''))
        content_html = item.get('content', '')

        if not content_html and not title:
            continue

        content_plain = strip_html(content_html)

        # Parse index_reference - may be a single ref or a range
        entry = {
            'content_id': content_id,
            'resource_type': resource_type,
            'title': title,
            'book': None,
            'book_num': book_num,
            'start_ref': None,
            'end_ref': None,
            'chapter_start': None,
            'verse_start': None,
            'chapter_end': None,
            'verse_end': None,
            'content': content_html,
            'content_plain': content_plain,
            'is_range': 0,
        }

        if index_ref and index_ref[0].isdigit():
            # Numeric reference - parse as BBCCCVVV
            if '-' in index_ref:
                # Range: "43001001-43001018"
                parts = index_ref.split('-', 1)
                start = _parse_ref(parts[0])
                end = _parse_ref(parts[1])

                if start:
                    entry['start_ref'] = parts[0].strip()
                    entry['book'] = start.get('book')
                    entry['book_num'] = start.get('book_num', book_num)
                    entry['chapter_start'] = start.get('chapter')
                    entry['verse_start'] = start.get('verse')

                if end:
                    entry['end_ref'] = parts[1].strip()
                    entry['chapter_end'] = end.get('chapter')
                    entry['verse_end'] = end.get('verse')
                    entry['is_range'] = 1
            else:
                # Single reference
                parsed = _parse_ref(index_ref)
                if parsed:
                    entry['start_ref'] = index_ref.strip()
                    entry['end_ref'] = index_ref.strip()
                    entry['book'] = parsed.get('book')
                    entry['book_num'] = parsed.get('book_num', book_num)
                    entry['chapter_start'] = parsed.get('chapter')
                    entry['verse_start'] = parsed.get('verse')
                    entry['chapter_end'] = parsed.get('chapter')
                    entry['verse_end'] = parsed.get('verse')

        yield entry
