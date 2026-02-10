"""
Parser for STEPBible lexicon files.

Supported formats:
- TBESG: Brief Greek lexicon (Extended Strong's)
- TBESH: Brief Hebrew lexicon (Extended Strong's)
- TFLSJ: Full LSJ (Liddell-Scott-Jones) Greek lexicon
- BDB: Full Brown-Driver-Briggs Hebrew lexicon (JSON)

Tab-separated formats share columns:
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
    """Parse a single Greek lexicon entry.

    TBESG tab-separated columns:
      0: Extended Strong's number (e.g., G0026)
      1: Extended reference (e.g., "G0026 =")
      2: Back-reference / related Strong's
      3: Greek word (e.g., ἀγάπη)
      4: Transliteration (e.g., agapē)
      5: Part of speech (e.g., G:N-F)
      6: Short English definition (e.g., "love")
      7: Full Abbott-Smith definition (HTML)
    """
    if len(parts) < 5:
        return None

    strongs = parts[0].strip()

    # Validate Strong's format (G#### or G####a, etc.)
    if not re.match(r'^G\d+[a-z]?$', strongs, re.IGNORECASE):
        return None

    strongs = strongs.upper()

    entry = {
        'strongs': strongs,
        'language': 'greek',
        'word': parts[3].strip() if len(parts) > 3 else '',
        'transliteration': parts[4].strip() if len(parts) > 4 else '',
        'short_definition': parts[6].strip() if len(parts) > 6 else '',
        'full_definition': parts[7].strip() if len(parts) > 7 else '',
        'pronunciation': parts[4].strip() if len(parts) > 4 else '',
        'etymology': '',
        'usage_count': 0,
        'semantic_domain': '[]',
        'related_words': '[]',
    }

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
    """Parse a single Hebrew lexicon entry.

    TBESH tab-separated columns (same layout as TBESG):
      0: Extended Strong's number (e.g., H0430)
      1: Extended reference (e.g., "H0430G = a Name of")
      2: Back-reference / related Strong's
      3: Hebrew word (e.g., אֱלֹהִים)
      4: Transliteration (e.g., e.lo.him)
      5: Part of speech (e.g., H:N-M)
      6: Short English definition (e.g., "God")
      7: Full definition
    """
    if len(parts) < 5:
        return None

    strongs = parts[0].strip()

    # Validate Strong's format (H#### or H####a, etc.)
    if not re.match(r'^H\d+[a-z]?$', strongs, re.IGNORECASE):
        return None

    strongs = strongs.upper()

    entry = {
        'strongs': strongs,
        'language': 'hebrew',
        'word': parts[3].strip() if len(parts) > 3 else '',
        'transliteration': parts[4].strip() if len(parts) > 4 else '',
        'short_definition': parts[6].strip() if len(parts) > 6 else '',
        'full_definition': parts[7].strip() if len(parts) > 7 else '',
        'pronunciation': parts[4].strip() if len(parts) > 4 else '',
        'etymology': '',
        'usage_count': 0,
        'semantic_domain': '[]',
        'related_words': '[]',
    }

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


# =========================================================================
# TFLSJ - Full LSJ Greek Lexicon
# =========================================================================

def clean_lsj_definition(html: str) -> str:
    """Convert LSJ HTML definition to readable markdown text.

    The TFLSJ column 7 contains heavy HTML markup including:
    - <b>bold</b> for headwords/senses
    - <i>italic</i> for transliterations and references
    - <br> for line breaks
    - Various other tags
    """
    if not html:
        return ''

    text = html

    # Convert <br> and <br/> to newlines
    text = re.sub(r'<br\s*/?>', '\n', text)

    # Convert bold to markdown
    text = re.sub(r'<b>(.*?)</b>', r'**\1**', text)

    # Convert italic to markdown
    text = re.sub(r'<i>(.*?)</i>', r'*\1*', text)

    # Strip all remaining HTML tags
    text = re.sub(r'<[^>]+>', '', text)

    # Decode HTML entities
    text = text.replace('&amp;', '&')
    text = text.replace('&lt;', '<')
    text = text.replace('&gt;', '>')
    text = text.replace('&quot;', '"')
    text = text.replace('&#39;', "'")
    text = text.replace('&nbsp;', ' ')

    # Clean up excessive whitespace while preserving newlines
    lines = text.split('\n')
    lines = [' '.join(line.split()) for line in lines]
    text = '\n'.join(line for line in lines if line)

    return text


def parse_tflsj_lexicon(filepath: Path) -> Iterator[dict]:
    """Parse a TFLSJ (Full LSJ) Greek lexicon file.

    TFLSJ has the same tab-separated column layout as TBESG:
      0: Extended Strong's number (e.g., G0026)
      1: Extended reference
      2: Back-reference / related Strong's
      3: Greek word
      4: Transliteration
      5: Part of speech
      6: Short gloss/definition
      7: Full LSJ definition (HTML)
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()

            if not line or line.startswith('#') or line.startswith('$'):
                continue

            parts = line.split('\t')
            if len(parts) < 5:
                continue

            strongs = parts[0].strip()
            if not re.match(r'^G\d+[a-z]?$', strongs, re.IGNORECASE):
                continue

            strongs = strongs.upper()

            gloss = parts[6].strip() if len(parts) > 6 else ''
            full_html = parts[7].strip() if len(parts) > 7 else ''

            entry = {
                'strongs': strongs,
                'language': 'greek',
                'word': parts[3].strip() if len(parts) > 3 else '',
                'transliteration': parts[4].strip() if len(parts) > 4 else '',
                'short_definition': clean_definition(gloss),
                'full_definition': clean_lsj_definition(full_html),
                'pronunciation': parts[4].strip() if len(parts) > 4 else '',
                'etymology': '',
                'usage_count': 0,
                'semantic_domain': '[]',
                'related_words': '[]',
            }

            yield entry


# =========================================================================
# BDB - Brown-Driver-Briggs Hebrew Lexicon
# =========================================================================

def clean_bdb_definition(text: str) -> str:
    """Clean BDB definition text.

    BDB entries may contain numbered senses, cross-references,
    abbreviations, and Unicode Hebrew text.
    """
    if not text:
        return ''

    # Strip any HTML that might be present
    text = re.sub(r'<[^>]+>', '', text)

    # Clean excessive whitespace while preserving paragraph breaks
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ \t]+', ' ', text)

    return text.strip()


def _extract_bdb_headword(html: str) -> tuple[str, str, str]:
    """Extract Hebrew word, transliteration, and short gloss from BDB HTML header.

    BDB entries start with patterns like:
      <b>H1. ab</b></p><p> <heb>...אָב...</heb> <b>noun masculine</b> <b>father</b>
    Returns (hebrew_word, transliteration, short_gloss).
    """
    word = ''
    translit = ''
    short_gloss = ''

    # Extract Hebrew word from <font class='c3'>...</font> or <heb> tags
    heb_match = re.search(r"<font class='c3'>([^<]+)</font>", html)
    if heb_match:
        word = heb_match.group(1).strip()

    # Extract transliteration from the "H\d+\. (translit)" pattern in the bold header
    translit_match = re.search(r'<b>H\d+[a-z]?\.\s*([^<]+)</b>', html)
    if translit_match:
        translit = translit_match.group(1).strip()

    # Extract short gloss - first bold noun/adjective/verb definition
    # Look for patterns like <b>father</b>, <b>noun masculine</b> <b>father</b>
    bold_parts = re.findall(r'<b>([^<]+)</b>', html)
    for part in bold_parts:
        part = part.strip()
        # Skip the header "H1. ab" and POS labels
        if re.match(r'^H\d+', part):
            continue
        if part.lower() in ('noun', 'verb', 'adjective', 'adverb', 'preposition',
                            'conjunction', 'particle', 'pronoun', 'interjection',
                            'noun masculine', 'noun feminine', 'noun common',
                            'proper name', 'proper noun'):
            continue
        if len(part) > 2 and not part[0].isdigit():
            short_gloss = part
            break

    return word, translit, short_gloss


def parse_bdb_lexicon(filepath: Path) -> Iterator[dict]:
    """Parse the BDB (Brown-Driver-Briggs) Hebrew lexicon JSON file.

    The JSON file is a list of {"top": "H1", "def": "<html>..."} entries.
    The 'top' field contains the Strong's number, and 'def' contains
    the full HTML definition.
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    if not isinstance(data, list):
        return

    for item in data:
        if not isinstance(item, dict):
            continue

        top = item.get('top', '')
        def_html = item.get('def', '')

        if not top or not def_html:
            continue

        # Skip non-entry items (like DictInfo)
        if not re.match(r'^H\d+', top):
            continue

        # Normalize Strong's number
        strongs_match = re.match(r'^(H\d+[a-z]?)', top)
        if not strongs_match:
            continue

        strongs_raw = strongs_match.group(1)
        num = strongs_raw[1:]
        # Pad number part to 4 digits
        num_clean = re.match(r'(\d+)', num).group(1)
        suffix = num[len(num_clean):]
        strongs = 'H' + num_clean.zfill(4) + suffix.upper()

        # Extract headword info from the HTML
        word, translit, short_gloss = _extract_bdb_headword(def_html)

        # Clean the full definition
        full_def = clean_bdb_definition(def_html)

        # If no short gloss extracted, take first meaningful line
        if not short_gloss and full_def:
            first_line = full_def.split('\n')[0]
            # Try to find a meaningful part after the header
            parts = first_line.split('  ')
            for part in parts:
                part = part.strip()
                if part and not re.match(r'^H\d+', part) and len(part) > 3:
                    short_gloss = part[:200]
                    break

        entry = {
            'strongs': strongs,
            'language': 'hebrew',
            'word': word,
            'transliteration': translit,
            'short_definition': short_gloss,
            'full_definition': full_def,
            'pronunciation': translit,
            'etymology': '',
            'usage_count': 0,
            'semantic_domain': '[]',
            'related_words': '[]',
        }

        yield entry
