"""
Parser for STEPBible lexicon files.

Supported formats:
- TBESG: Brief Greek lexicon (Extended Strong's)
- TBESH: Brief Hebrew lexicon (Extended Strong's)
- TFLSJ: Full LSJ (Liddell-Scott-Jones) Greek lexicon
- BDB: Full Brown-Driver-Briggs Hebrew lexicon (JSON)
- Abbott-Smith: Manual Greek Lexicon of the NT (TEI XML)

Tab-separated formats share columns:
- Extended Strongs number
- Original word
- Transliteration
- Brief definition
- (Additional columns vary by file)
"""

import json
import re
import xml.etree.ElementTree as ET
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


# =========================================================================
# Abbott-Smith - Manual Greek Lexicon of the New Testament (TEI XML)
# =========================================================================

# TEI namespace used in the Abbott-Smith XML
_TEI_NS = "http://www.crosswire.org/2013/TEIOSIS/namespace"


def _strip_ns(tag: str) -> str:
    """Strip XML namespace from an element tag."""
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _get_text_content(elem) -> str:
    """Get all text content from an element, including tail text of children."""
    if elem is None:
        return ""
    parts = []
    if elem.text:
        parts.append(elem.text)
    for child in elem:
        parts.append(_get_text_content(child))
        if child.tail:
            parts.append(child.tail)
    return "".join(parts)


def _extract_lxx_hebrew(entry_elem) -> list[dict]:
    """Extract LXX/Hebrew equivalents from etymology and form elements.

    Looks for <foreign xml:lang="heb" n="Hxxx"> patterns in <etym><seg type="septuagint">
    and also in <form> elements.
    """
    results = []
    seen = set()

    for foreign in entry_elem.iter(f"{{{_TEI_NS}}}foreign"):
        lang = foreign.get("{http://www.w3.org/XML/1998/namespace}lang", "")
        if lang not in ("heb", "arc"):
            continue
        strongs_attr = foreign.get("n", "")
        if not strongs_attr or not strongs_attr.startswith("H"):
            continue
        # Normalize Strong's: H160 -> H0160
        num = strongs_attr[1:]
        normalized = "H" + num.zfill(4)
        if normalized in seen:
            continue
        seen.add(normalized)
        hebrew_text = _get_text_content(foreign).strip()
        results.append({"strongs": normalized, "hebrew": hebrew_text})

    return results


def _build_sense_tree(sense_elem) -> dict:
    """Recursively build a sense hierarchy from <sense> elements."""
    result = {}
    n = sense_elem.get("n", "")
    if n:
        result["n"] = n

    # Extract glosses
    glosses = []
    for gloss in sense_elem.findall(f"{{{_TEI_NS}}}gloss"):
        text = _get_text_content(gloss).strip()
        if text:
            glosses.append(text)
    if glosses:
        result["glosses"] = glosses

    # Extract references
    refs = []
    for ref in sense_elem.findall(f"{{{_TEI_NS}}}ref"):
        osis = ref.get("osisRef", "")
        if osis:
            refs.append(osis)
    if refs:
        result["refs"] = refs

    # Recurse into child senses
    subsenses = []
    for child in sense_elem.findall(f"{{{_TEI_NS}}}sense"):
        subsenses.append(_build_sense_tree(child))
    if subsenses:
        result["senses"] = subsenses

    return result


def _tei_to_markdown(entry_elem) -> str:
    """Convert a TEI <entry> element to readable markdown text."""
    parts = []

    def _process_elem(elem, depth=0):
        tag = _strip_ns(elem.tag)

        if tag == "entry":
            if elem.text and elem.text.strip():
                parts.append(elem.text.strip())
            for child in elem:
                _process_elem(child, depth)
                if child.tail and child.tail.strip():
                    parts.append(child.tail.strip() + " ")
            return

        if tag == "note":
            note_type = elem.get("type", "")
            if note_type == "occurrencesNT":
                count = _get_text_content(elem).strip()
                if count:
                    parts.append(f"[NT: {count}x] ")
            else:
                text = _get_text_content(elem).strip()
                if text:
                    parts.append(f"({text}) ")
        elif tag == "form":
            text = _get_text_content(elem).strip()
            if text:
                parts.append(f"**{text}** ")
        elif tag == "orth":
            text = _get_text_content(elem).strip()
            if text:
                parts.append(f"**{text}**")
        elif tag == "etym":
            text = _get_text_content(elem).strip()
            if text:
                parts.append(f"*Etymology*: {text} ")
        elif tag == "sense":
            n = elem.get("n", "")
            prefix = f"**{n}** " if n else ""
            # Collect text and glosses inline
            inline_parts = []
            if elem.text and elem.text.strip():
                inline_parts.append(elem.text.strip())
            for child in elem:
                child_tag = _strip_ns(child.tag)
                if child_tag == "gloss":
                    inline_parts.append(f"*{_get_text_content(child).strip()}*")
                elif child_tag == "ref":
                    osis = child.get("osisRef", "")
                    text = _get_text_content(child).strip()
                    inline_parts.append(text or osis)
                elif child_tag == "foreign":
                    inline_parts.append(_get_text_content(child).strip())
                elif child_tag == "sense":
                    # Sub-senses get processed recursively
                    _process_elem(child, depth + 1)
                elif child_tag == "emph":
                    inline_parts.append(f"*{_get_text_content(child).strip()}*")
                else:
                    inline_parts.append(_get_text_content(child).strip())
                if child.tail and child.tail.strip():
                    inline_parts.append(child.tail.strip())
            text = " ".join(p for p in inline_parts if p)
            if text:
                indent = "  " * depth
                parts.append(f"\n{indent}{prefix}{text}")
        elif tag == "re":
            # Synonym discussion
            text = _get_text_content(elem).strip()
            if text:
                parts.append(f"\n\n**Synonyms**: {text}")
        elif tag == "gloss":
            text = _get_text_content(elem).strip()
            if text:
                parts.append(f"*{text}*")
        elif tag == "foreign":
            text = _get_text_content(elem).strip()
            if text:
                parts.append(text)
        elif tag == "ref":
            text = _get_text_content(elem).strip()
            osis = elem.get("osisRef", "")
            parts.append(text or osis)
        elif tag == "emph":
            text = _get_text_content(elem).strip()
            if text:
                parts.append(f"*{text}*")
        elif tag == "pb":
            pass  # Page breaks - skip
        elif tag == "gramGrp":
            pass  # Empty grammar groups - skip
        elif tag == "seg":
            text = _get_text_content(elem).strip()
            if text:
                parts.append(text + " ")
        else:
            # Default: just get text content
            text = _get_text_content(elem).strip()
            if text:
                parts.append(text + " ")

    _process_elem(entry_elem)

    # Clean up
    result = " ".join(parts)
    result = re.sub(r'\s+', ' ', result)
    result = re.sub(r'\n ', '\n', result)
    result = result.strip()
    return result


def _extract_synonyms(entry_elem) -> str:
    """Extract synonym discussion from <re> elements."""
    parts = []
    for re_elem in entry_elem.findall(f"{{{_TEI_NS}}}re"):
        text = _get_text_content(re_elem).strip()
        if text:
            parts.append(text)
    return "\n".join(parts) if parts else ""


def parse_abbott_smith(filepath: Path) -> Iterator[dict]:
    """Parse the Abbott-Smith Manual Greek Lexicon TEI XML file.

    Yields dictionaries with:
    - strongs: Strong's number (G0026) or synthetic AS_word key
    - word: Greek headword
    - short_definition: comma-joined glosses
    - abbott_smith_def: full markdown definition
    - nt_occurrences: NT word frequency
    - lxx_hebrew: JSON array of Hebrew equivalents
    - synonyms: synonym discussion text
    - sense_hierarchy: JSON sense tree
    """
    tree = ET.parse(filepath)
    root = tree.getroot()

    # Find all entry elements
    entries = root.iter(f"{{{_TEI_NS}}}entry")

    for entry_elem in entries:
        n_attr = entry_elem.get("n", "")
        if not n_attr:
            continue

        # Parse the n attribute: "word|Gxxx" or just "word"
        if "|" in n_attr:
            word_part, strongs_raw = n_attr.rsplit("|", 1)
        else:
            word_part = n_attr
            strongs_raw = ""

        # Normalize Strong's number
        if strongs_raw and re.match(r'^G\d+$', strongs_raw):
            num = strongs_raw[1:]
            strongs = "G" + num.zfill(4)
        elif strongs_raw:
            strongs = strongs_raw
        else:
            # Synthetic key for entries without Strong's numbers
            strongs = f"AS_{word_part}"

        # Extract headword from <form><orth>
        orth_elem = entry_elem.find(f".//{{{_TEI_NS}}}orth")
        word = _get_text_content(orth_elem).strip() if orth_elem is not None else word_part

        # Extract NT occurrences
        nt_occurrences = None
        for note in entry_elem.findall(f"{{{_TEI_NS}}}note"):
            if note.get("type") == "occurrencesNT":
                try:
                    nt_occurrences = int(_get_text_content(note).strip())
                except (ValueError, AttributeError):
                    pass

        # Extract glosses for short_definition
        glosses = []
        for sense in entry_elem.iter(f"{{{_TEI_NS}}}sense"):
            for gloss in sense.findall(f"{{{_TEI_NS}}}gloss"):
                text = _get_text_content(gloss).strip()
                if text and text not in glosses:
                    glosses.append(text)
        short_def = ", ".join(glosses) if glosses else ""

        # Extract LXX Hebrew equivalents
        lxx_hebrew = _extract_lxx_hebrew(entry_elem)

        # Build sense hierarchy from top-level senses
        top_senses = []
        for child in entry_elem:
            if _strip_ns(child.tag) == "sense":
                top_senses.append(child)

        sense_tree = []
        for sense in top_senses:
            sense_tree.append(_build_sense_tree(sense))

        # Extract synonym discussion
        synonyms = _extract_synonyms(entry_elem)

        # Full definition as markdown
        abbott_smith_def = _tei_to_markdown(entry_elem)

        entry = {
            "strongs": strongs,
            "word": word,
            "short_definition": short_def,
            "abbott_smith_def": abbott_smith_def,
            "nt_occurrences": nt_occurrences,
            "lxx_hebrew": json.dumps(lxx_hebrew) if lxx_hebrew else None,
            "synonyms": synonyms or None,
            "sense_hierarchy": json.dumps(sense_tree) if sense_tree else None,
        }

        yield entry
