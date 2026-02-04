"""
Parser for STEPBible proper names file (TIPNR).

TIPNR = Translators Individualised Proper Names with all References

This file contains every proper noun in the Bible with:
- Name (English) with first reference and Strong's number
- Description (role/time period)
- Family relationships (parents, siblings, spouse, children)
- Tribe/lineage
- HTML summary with all details
- Gender

Format: Name@FirstRef=Strong's<TAB>Description<TAB>Parents<TAB>Siblings<TAB>Partner<TAB>Offspring<TAB>Tribe<TAB>Summary<TAB>Gender
Example: Aaron@Exo.4.14-Heb=H0175	High Priest living at the time of Egypt and Wilderness	Amram@Exo.6.18-1Ch + Jochebed@Exo.6.20-Num	...
"""

import json
import re
from pathlib import Path
from typing import Iterator


def parse_tipnr(filepath: Path) -> Iterator[dict]:
    """
    Parse TIPNR proper names file.

    Entries have format: Name@FirstRef=Strong's followed by tab-separated fields.

    Section markers:
    - "========== PERSON(s)" (without $) marks person data sections
    - Lines starting with $ are documentation headers, not data
    """
    # Track current section for type classification
    # The TIPNR file primarily contains persons
    current_section = "person"

    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.rstrip('\n\r')

            # Skip empty lines
            if not line:
                continue

            # Section markers (without $) indicate type
            # e.g., "========== PERSON(s)" marks person sections
            if line.startswith('=========='):
                section_match = re.search(r'(PERSON|PLACE|OTHER|THING)', line, re.IGNORECASE)
                if section_match:
                    section = section_match.group(1).lower()
                    if section == 'other':
                        current_section = 'thing'
                    elif section == 'person':
                        current_section = 'person'
                    else:
                        current_section = section
                continue

            # Skip documentation headers (start with $), comments, meta lines
            if line.startswith(('$', '#', '*', '‖', '–', '\t')):
                continue

            # Skip lines that don't look like entries (no @ in first field)
            first_field = line.split('\t')[0]
            if '@' not in first_field:
                continue

            # Parse entry
            entry = parse_entry(line, current_section)
            if entry:
                yield entry


def parse_entry(line: str, section_type: str) -> dict | None:
    """
    Parse a single TIPNR entry line.

    Columns (tab-separated):
    0: Name@FirstRef=Strong's (e.g., Aaron@Exo.4.14-Heb=H0175)
    1: Description (e.g., High Priest living at the time of Egypt and Wilderness)
    2: Parents (e.g., Amram@Exo.6.18-1Ch + Jochebed@Exo.6.20-Num)
    3: Siblings (e.g., Moses@Exo.2.10-Rev, Miriam@Exo.15.20-Mic)
    4: Partner/Spouse (e.g., Elisheba@Exo.6.23)
    5: Offspring (e.g., Nadab@Exo.6.23-1Ch, Abihu@Exo.6.23-1Ch, ...)
    6: Tribe (e.g., Tribe of Levi)
    7: Summary (HTML with full description)
    8: Gender (Male/Female)
    """
    parts = line.split('\t')

    if len(parts) < 2:
        return None

    # Parse first field: Name@Reference=Strong's
    first_field = parts[0].strip()
    name_match = re.match(r'^([^@]+)@([^=]+)=([A-Z]\d+[A-Za-z]?)', first_field)

    if not name_match:
        # Try without Strong's: Name@Reference
        name_match = re.match(r'^([^@]+)@(.+)', first_field)
        if not name_match:
            return None
        name = name_match.group(1)
        first_ref = name_match.group(2)
        strongs = ''
    else:
        name = name_match.group(1)
        first_ref = name_match.group(2)
        strongs = name_match.group(3)

    # Description
    description = parts[1].strip() if len(parts) > 1 else ''

    # Relationships
    relationships = {}

    # Parents (column 2)
    if len(parts) > 2 and parts[2].strip() and parts[2].strip() != '+':
        parents = parse_relationship_field(parts[2])
        if parents:
            relationships['parents'] = parents

    # Siblings (column 3)
    if len(parts) > 3 and parts[3].strip():
        siblings = parse_relationship_field(parts[3])
        if siblings:
            relationships['siblings'] = siblings

    # Partner/Spouse (column 4)
    if len(parts) > 4 and parts[4].strip():
        partner = parse_relationship_field(parts[4])
        if partner:
            relationships['spouse'] = partner

    # Offspring (column 5)
    if len(parts) > 5 and parts[5].strip():
        offspring = parse_relationship_field(parts[5])
        if offspring:
            relationships['children'] = offspring

    # Tribe (column 6)
    tribe = ''
    if len(parts) > 6 and parts[6].strip():
        tribe_field = parts[6].strip()
        if tribe_field.startswith('Tribe of '):
            tribe = tribe_field[9:]
        elif tribe_field != '>':
            tribe = tribe_field

    # Summary/HTML description (column 7)
    summary = ''
    if len(parts) > 7 and parts[7].strip():
        summary = clean_html_summary(parts[7])

    # Gender (column 8)
    gender = ''
    if len(parts) > 8 and parts[8].strip():
        gender = parts[8].strip()

    # Extract references from the summary
    references = extract_references(summary, first_ref)

    # Extract original language name from summary
    name_original = extract_original_name(summary)

    # Determine type from section, description, gender, and relationships
    entry_type = determine_type(section_type, description, gender, relationships)

    return {
        'name': name,
        'name_original': name_original,
        'type': entry_type,
        'description': description + (f" ({summary})" if summary and len(summary) < 500 else ""),
        'references': json.dumps(references, ensure_ascii=False),
        'relationships': json.dumps(relationships, ensure_ascii=False),
        'strongs': strongs,
        'tribe': tribe,
        'gender': gender,
    }


def parse_relationship_field(field: str) -> list[str]:
    """
    Parse a relationship field containing names.

    Format: Name@Ref, Name@Ref or Name@Ref + Name@Ref
    """
    field = field.strip()
    if not field or field in ('+', '>', '-'):
        return []

    # Split by comma and/or +
    names = []
    for part in re.split(r'[,+]', field):
        part = part.strip()
        if not part or part in ('>', '-'):
            continue

        # Extract just the name (before @)
        if '@' in part:
            name = part.split('@')[0].strip()
        else:
            name = part

        if name and len(name) > 1:
            names.append(name)

    return names


def clean_html_summary(html: str) -> str:
    """Clean HTML tags from summary text."""
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', html)
    # Clean up whitespace
    text = re.sub(r'\s+', ' ', text)
    # Remove leading # if present
    if text.startswith('#'):
        text = text[1:]
    return text.strip()


def extract_references(summary: str, first_ref: str) -> list[str]:
    """Extract Bible references from summary text."""
    refs = []

    # Add the first reference
    if first_ref:
        # Clean up first_ref (remove suffix like -Heb)
        clean_ref = first_ref.split('-')[0] if '-' in first_ref else first_ref
        refs.append(clean_ref)

    # Find additional references in the pattern Book.Chapter.Verse
    for match in re.finditer(r'\b([A-Z][a-z]{2,})\.(\d+)\.(\d+)\b', summary):
        ref = f"{match.group(1)}.{match.group(2)}.{match.group(3)}"
        if ref not in refs:
            refs.append(ref)

    return refs[:20]  # Limit to 20 references


def extract_original_name(summary: str) -> str:
    """Extract Hebrew/Greek name from summary."""
    # Look for Hebrew (in parentheses with Hebrew characters)
    hebrew_match = re.search(r'\(([א-ת]+)\)', summary)
    if hebrew_match:
        return hebrew_match.group(1)

    # Look for Greek (in parentheses with Greek characters)
    greek_match = re.search(r'\(([Α-Ωα-ω]+)\)', summary)
    if greek_match:
        return greek_match.group(1)

    return ''


def determine_type(section_type: str, description: str, gender: str, relationships: dict = None) -> str:
    """Determine the type of entry."""
    # Gender is the most reliable indicator for persons
    if gender in ('Male', 'Female'):
        return 'person'

    # Infer from description
    desc_lower = description.lower()

    # Place indicators - check these first as they're more specific
    place_words = [
        'city', 'region', 'mountain', 'river', 'valley', 'land', 'territory',
        'town', 'village', 'wilderness', 'desert', 'sea', 'lake', 'brook',
        'plain', 'hill', 'cave', 'gate', 'well', 'spring', 'pool'
    ]
    if any(word in desc_lower for word in place_words):
        return 'place'

    # Check if relationships contain URLs (indicates place data with geolocation)
    if relationships:
        for value in relationships.values():
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, str) and ('http' in item or 'google.com' in item or 'palopenmaps' in item):
                        return 'place'

    # If description is just the name itself (common for places), check other indicators
    # Places often have very short descriptions that just repeat the name

    # Person indicators (more comprehensive list)
    person_words = [
        'king', 'priest', 'prophet', 'man', 'woman', 'son', 'daughter',
        'father', 'mother', 'brother', 'sister', 'wife', 'husband',
        'levite', 'israelite', 'high priest', 'judge', 'ruler',
        'living at the time', 'mentioned at', 'only mentioned',
        'tribe of', 'ancestor', 'descendant'
    ]
    if any(word in desc_lower for word in person_words):
        return 'person'

    # Use section type as fallback
    if section_type and section_type != 'unknown':
        return section_type

    return 'unknown'


# Keep legacy function for backwards compatibility
def parse_simple_names(filepath: Path) -> Iterator[dict]:
    """Legacy parser - redirects to main parser."""
    yield from parse_tipnr(filepath)
