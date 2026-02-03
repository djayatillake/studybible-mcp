"""
Parser for STEPBible lexicon files (TBESG and TBESH).

TBESG = Translators Brief lexicon of Extended Strongs for Greek
TBESH = Translators Brief lexicon of Extended Strongs for Hebrew

Format is tab-separated with columns:
- Extended Strongs number
- Original word
- Transliteration  
- Brief definition
- (Additional columns vary by file)
"""

import json
import re
from pathlib import Path
from typing import Iterator


def parse_greek_lexicon(filepath: Path) -> Iterator[dict]:
    """
    Parse TBESG Greek lexicon file.
    
    Yields dictionaries with lexicon entries.
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            
            # Skip empty lines and comments
            if not line or line.startswith('#') or line.startswith('$'):
                continue
            
            # Skip header line
            if line_num == 1 and 'Strong' in line:
                continue
            
            parts = line.split('\t')
            
            if len(parts) < 3:
                continue
            
            try:
                entry = parse_greek_entry(parts)
                if entry:
                    yield entry
            except Exception as e:
                # Log but continue parsing
                print(f"Warning: Could not parse line {line_num}: {e}")
                continue


def parse_greek_entry(parts: list[str]) -> dict | None:
    """Parse a single Greek lexicon entry."""
    if len(parts) < 3:
        return None
    
    strongs = parts[0].strip()
    
    # Validate Strong's format (G#### or G####a, etc.)
    if not re.match(r'^G\d+[a-z]?$', strongs, re.IGNORECASE):
        return None
    
    strongs = strongs.upper()
    
    entry = {
        'strongs': strongs,
        'language': 'greek',
        'word': parts[1].strip() if len(parts) > 1 else '',
        'transliteration': parts[2].strip() if len(parts) > 2 else '',
        'short_definition': parts[3].strip() if len(parts) > 3 else '',
        'full_definition': parts[4].strip() if len(parts) > 4 else '',
        'etymology': '',
        'usage_count': 0,
        'semantic_domain': '[]',
        'related_words': '[]',
    }
    
    # Parse additional fields if present
    if len(parts) > 5:
        # Some files have etymology, usage count, etc.
        for i, part in enumerate(parts[5:], 5):
            part = part.strip()
            if part.isdigit():
                entry['usage_count'] = int(part)
            elif part.startswith('from ') or part.startswith('From '):
                entry['etymology'] = part
    
    # Clean up definitions
    entry['short_definition'] = clean_definition(entry['short_definition'])
    entry['full_definition'] = clean_definition(entry['full_definition'])
    
    return entry


def parse_hebrew_lexicon(filepath: Path) -> Iterator[dict]:
    """
    Parse TBESH Hebrew lexicon file.
    
    Yields dictionaries with lexicon entries.
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            
            # Skip empty lines and comments
            if not line or line.startswith('#') or line.startswith('$'):
                continue
            
            # Skip header line
            if line_num == 1 and 'Strong' in line:
                continue
            
            parts = line.split('\t')
            
            if len(parts) < 3:
                continue
            
            try:
                entry = parse_hebrew_entry(parts)
                if entry:
                    yield entry
            except Exception as e:
                print(f"Warning: Could not parse line {line_num}: {e}")
                continue


def parse_hebrew_entry(parts: list[str]) -> dict | None:
    """Parse a single Hebrew lexicon entry."""
    if len(parts) < 3:
        return None
    
    strongs = parts[0].strip()
    
    # Validate Strong's format (H#### or H####a, etc.)
    if not re.match(r'^H\d+[a-z]?$', strongs, re.IGNORECASE):
        return None
    
    strongs = strongs.upper()
    
    entry = {
        'strongs': strongs,
        'language': 'hebrew',
        'word': parts[1].strip() if len(parts) > 1 else '',
        'transliteration': parts[2].strip() if len(parts) > 2 else '',
        'short_definition': parts[3].strip() if len(parts) > 3 else '',
        'full_definition': parts[4].strip() if len(parts) > 4 else '',
        'etymology': '',
        'usage_count': 0,
        'semantic_domain': '[]',
        'related_words': '[]',
    }
    
    # Parse additional fields
    if len(parts) > 5:
        for i, part in enumerate(parts[5:], 5):
            part = part.strip()
            if part.isdigit():
                entry['usage_count'] = int(part)
            elif part.startswith('from ') or part.startswith('From '):
                entry['etymology'] = part
    
    entry['short_definition'] = clean_definition(entry['short_definition'])
    entry['full_definition'] = clean_definition(entry['full_definition'])
    
    return entry


def clean_definition(definition: str) -> str:
    """Clean up a lexicon definition."""
    if not definition:
        return ''
    
    # Remove HTML tags
    definition = re.sub(r'<[^>]+>', '', definition)
    
    # Clean up whitespace
    definition = ' '.join(definition.split())
    
    return definition


def parse_extended_lexicon(filepath: Path, language: str) -> Iterator[dict]:
    """
    Parse the full LSJ or BDB formatted lexicons.
    
    These have more detailed entries with etymology, usage examples, etc.
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        current_entry = None
        
        for line in f:
            line = line.strip()
            
            if not line or line.startswith('#'):
                continue
            
            # New entry starts with Strong's number
            if re.match(r'^[GH]\d+', line):
                if current_entry:
                    yield current_entry
                
                parts = line.split('\t')
                current_entry = {
                    'strongs': parts[0].strip().upper(),
                    'language': language,
                    'word': parts[1].strip() if len(parts) > 1 else '',
                    'transliteration': parts[2].strip() if len(parts) > 2 else '',
                    'short_definition': '',
                    'full_definition': '',
                    'etymology': '',
                    'usage_count': 0,
                    'semantic_domain': '[]',
                    'related_words': '[]',
                }
            
            elif current_entry:
                # Additional lines belong to current entry
                parts = line.split('\t')
                
                for part in parts:
                    part = part.strip()
                    
                    if part.startswith('def:'):
                        current_entry['full_definition'] = part[4:].strip()
                    elif part.startswith('etym:'):
                        current_entry['etymology'] = part[5:].strip()
                    elif part.startswith('count:'):
                        try:
                            current_entry['usage_count'] = int(part[6:].strip())
                        except ValueError:
                            pass
        
        # Yield last entry
        if current_entry:
            yield current_entry
