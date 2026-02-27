"""
Parser for ANE (Ancient Near East) context data files.

Reads JSON files from data/ane_context/ (one per dimension) and yields
entry dicts with book mappings ready for database insertion.
"""

import json
from pathlib import Path
from typing import Iterator


# Map period keys to display labels
PERIOD_LABELS = {
    "patriarchal": "Patriarchal Period (c. 2000-1550 BC)",
    "exodus_conquest": "Exodus & Conquest (c. 1550-1200 BC)",
    "judges_early_monarchy": "Judges & Early Monarchy (c. 1200-1000 BC)",
    "united_monarchy": "United Monarchy (c. 1000-930 BC)",
    "divided_monarchy": "Divided Monarchy (c. 930-722 BC)",
    "assyrian_babylonian": "Assyrian & Babylonian Period (c. 722-539 BC)",
    "persian": "Persian Period (c. 539-332 BC)",
    "hellenistic": "Hellenistic Period (c. 332-63 BC)",
    "roman": "Roman Period (c. 63 BC-AD 100)",
}


def parse_ane_context_file(filepath: Path) -> Iterator[dict]:
    """Parse a single ANE context JSON file (one per dimension).

    Args:
        filepath: Path to the dimension JSON file

    Yields:
        Tuples of (entry_dict, book_mappings_list) ready for database insertion.
        entry_dict has all fields for ane_entries table.
        book_mappings_list is a list of dicts with entry_id, book, chapter_start, chapter_end.
    """
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    dimension = data.get("dimension", "")
    dimension_label = data.get("dimension_label", "")
    entries = data.get("entries", [])

    for entry_data in entries:
        if not isinstance(entry_data, dict):
            continue

        entry_id = entry_data.get("id", "")
        if not entry_id:
            continue

        period = entry_data.get("period", "")
        period_label = PERIOD_LABELS.get(period, period)

        # Serialize list fields to JSON
        ane_parallels = entry_data.get("ane_parallels", [])
        key_references = entry_data.get("key_references", [])
        scholarly_sources = entry_data.get("scholarly_sources", [])

        entry = {
            "id": entry_id,
            "dimension": dimension,
            "dimension_label": dimension_label,
            "title": entry_data.get("title", ""),
            "summary": entry_data.get("summary", ""),
            "detail": entry_data.get("detail"),
            "ane_parallels": json.dumps(ane_parallels) if isinstance(ane_parallels, list) else ane_parallels,
            "interpretive_significance": entry_data.get("interpretive_significance"),
            "period": period,
            "period_label": period_label,
            "key_references": json.dumps(key_references) if isinstance(key_references, list) else key_references,
            "scholarly_sources": json.dumps(scholarly_sources) if isinstance(scholarly_sources, list) else scholarly_sources,
        }

        # Build book mappings
        books = entry_data.get("books", [])
        chapter_start = entry_data.get("chapter_start")
        chapter_end = entry_data.get("chapter_end")

        book_mappings = []
        for book in books:
            book_mappings.append({
                "entry_id": entry_id,
                "book": book,
                "chapter_start": chapter_start,
                "chapter_end": chapter_end,
            })

        yield entry, book_mappings
