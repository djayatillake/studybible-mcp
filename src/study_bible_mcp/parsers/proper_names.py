"""
Parser for STEPBible proper names file (TIPNR).

TIPNR = Translators Individualised Proper Names with all References

This file contains every proper noun in the Bible with:
- Name (English)
- Original Hebrew/Greek
- Type (person, place, thing)
- References where it appears
- Relationships (for people)
"""

import json
import re
from pathlib import Path
from typing import Iterator


def parse_tipnr(filepath: Path) -> Iterator[dict]:
    """
    Parse TIPNR proper names file.
    
    The file uses a multi-line record format:
    - Lines starting with $ begin a new record (header)
    - Subsequent lines starting with tab are sub-records
    """
    current_header = None
    
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.rstrip('\n\r')
            
            # Skip empty lines and comments
            if not line or line.startswith('#'):
                continue
            
            # New record header
            if line.startswith('$'):
                if current_header:
                    # Yield previous complete entry
                    entry = build_name_entry(current_header)
                    if entry:
                        yield entry
                
                current_header = parse_header(line[1:])
            
            # Sub-record (additional data for current header)
            elif line.startswith('\t') and current_header:
                parse_subrecord(line[1:], current_header)
        
        # Yield final entry
        if current_header:
            entry = build_name_entry(current_header)
            if entry:
                yield entry


def parse_header(line: str) -> dict:
    """Parse a header line (starts with $)."""
    parts = line.split('\t')
    
    header = {
        'name': '',
        'name_original': '',
        'type': 'unknown',
        'description': '',
        'references': [],
        'relationships': {},
        'strongs': [],
    }
    
    # Parse based on column positions (may vary by file version)
    if len(parts) >= 1:
        header['name'] = parts[0].strip()
    
    if len(parts) >= 2:
        # Second column often contains type or original name
        second = parts[1].strip()
        if second in ('Person', 'Place', 'Thing', 'Title', 'Tribe', 'Nation'):
            header['type'] = second.lower()
        else:
            header['name_original'] = second
    
    if len(parts) >= 3:
        # Third column might be type or description
        third = parts[2].strip()
        if third in ('Person', 'Place', 'Thing', 'Title', 'Tribe', 'Nation'):
            header['type'] = third.lower()
        elif header['type'] == 'unknown':
            header['description'] = third
    
    if len(parts) >= 4:
        header['description'] = parts[3].strip()
    
    return header


def parse_subrecord(line: str, header: dict):
    """Parse a sub-record line (starts with tab) and update header."""
    parts = line.split('\t')
    
    for part in parts:
        part = part.strip()
        
        if not part:
            continue
        
        # Check for references (e.g., "Gen.1.1", "Mat.1.1")
        if re.match(r'^[A-Z][a-z]{2}\.\d+\.\d+', part):
            header['references'].append(part)
        
        # Check for Strong's numbers
        elif re.match(r'^[GH]\d+', part):
            header['strongs'].append(part.upper())
        
        # Check for relationships
        elif ':' in part:
            key, value = part.split(':', 1)
            key = key.strip().lower()
            value = value.strip()
            
            if key in ('father', 'mother', 'son', 'daughter', 'husband', 
                       'wife', 'brother', 'sister', 'tribe', 'from'):
                if key not in header['relationships']:
                    header['relationships'][key] = []
                header['relationships'][key].append(value)
        
        # Additional description
        elif len(part) > 20 and not header['description']:
            header['description'] = part


def build_name_entry(header: dict) -> dict | None:
    """Build a final name entry from parsed header data."""
    if not header.get('name'):
        return None
    
    return {
        'name': header['name'],
        'name_original': header.get('name_original', ''),
        'type': header.get('type', 'unknown'),
        'description': header.get('description', ''),
        'references': json.dumps(header.get('references', []), ensure_ascii=False),
        'relationships': json.dumps(header.get('relationships', {}), ensure_ascii=False),
    }


def parse_simple_names(filepath: Path) -> Iterator[dict]:
    """
    Parse a simpler names file format.
    
    For files that don't use the multi-line record format.
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            
            if not line or line.startswith('#') or line.startswith('$'):
                continue
            
            parts = line.split('\t')
            
            if len(parts) < 2:
                continue
            
            entry = {
                'name': parts[0].strip(),
                'name_original': parts[1].strip() if len(parts) > 1 else '',
                'type': determine_type(parts),
                'description': parts[3].strip() if len(parts) > 3 else '',
                'references': '[]',
                'relationships': '{}',
            }
            
            # Look for references in remaining columns
            refs = []
            for part in parts[2:]:
                part = part.strip()
                if re.match(r'^[A-Z][a-z]{2}\.\d+\.\d+', part):
                    refs.append(part)
            
            if refs:
                entry['references'] = json.dumps(refs)
            
            yield entry


def determine_type(parts: list[str]) -> str:
    """Determine the type of name entry from parts."""
    for part in parts:
        part = part.strip().lower()
        if part in ('person', 'people', 'man', 'woman'):
            return 'person'
        elif part in ('place', 'city', 'region', 'mountain', 'river'):
            return 'place'
        elif part in ('thing', 'object', 'title'):
            return 'thing'
        elif part in ('tribe', 'nation', 'people group'):
            return 'tribe'
    
    return 'unknown'
