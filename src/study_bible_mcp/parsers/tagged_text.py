"""
Parser for STEPBible tagged Bible text files (TAGNT and TAHOT).

TAGNT = Translators Amalgamated Greek NT
TAHOT = Translators Amalgamated Hebrew OT

These files contain morphologically tagged text with:
- Reference
- Greek/Hebrew word
- Transliteration
- Strong's number
- Morphology code
- English gloss
"""

import json
import re
from pathlib import Path
from typing import Iterator


def extract_verse_ref(ref: str) -> str:
    """Extract base verse reference, stripping word position markers.

    'Mat.1.1#01=NKO' -> 'Mat.1.1'
    'Gen.1.1#05' -> 'Gen.1.1'
    """
    # Strip word position markers like #01, #02=NKO, etc.
    if '#' in ref:
        ref = ref.split('#')[0]
    return ref


def parse_tagnt(filepath: Path) -> Iterator[dict]:
    """
    Parse TAGNT Greek New Testament file.

    Yields verse dictionaries with word-level tagging.
    """
    current_verse_ref = None
    word_data = []

    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()

            if not line or line.startswith('#'):
                continue

            parts = line.split('\t')

            if len(parts) < 4:
                continue

            full_ref = parts[0].strip()
            verse_ref = extract_verse_ref(full_ref)

            # New verse - yield previous if exists
            if verse_ref != current_verse_ref:
                if current_verse_ref and word_data:
                    yield build_verse_entry(current_verse_ref, word_data, 'greek')

                current_verse_ref = verse_ref
                word_data = []

            # Parse word data
            word_entry = parse_greek_word(parts)
            if word_entry:
                word_data.append(word_entry)

    # Yield final verse
    if current_verse_ref and word_data:
        yield build_verse_entry(current_verse_ref, word_data, 'greek')


def parse_greek_word(parts: list[str]) -> dict | None:
    """Parse a single Greek word from TAGNT.

    TAGNT columns:
    0: Reference (Mat.1.1#01=NKO)
    1: Greek word with transliteration (Βίβλος (Biblos))
    2: English translation ([The] book)
    3: dStrongs=Grammar (G0976=N-NSF)
    4: Dictionary=Gloss (βίβλος=book)
    5: Editions (NA28+NA27+...)
    """
    if len(parts) < 4:
        return None

    # Parse Greek word and transliteration from "Βίβλος (Biblos)"
    greek_field = parts[1].strip() if len(parts) > 1 else ''
    word = greek_field
    transliteration = ''
    if '(' in greek_field and ')' in greek_field:
        match = re.match(r'^(.+?)\s*\(([^)]+)\)', greek_field)
        if match:
            word = match.group(1).strip()
            transliteration = match.group(2).strip()

    # English translation
    english = parts[2].strip() if len(parts) > 2 else ''

    # Parse dStrongs=Grammar (G0976=N-NSF)
    strongs_grammar = parts[3].strip() if len(parts) > 3 else ''
    strongs = ''
    morph = ''
    if '=' in strongs_grammar:
        sg_parts = strongs_grammar.split('=', 1)
        strongs = normalize_strongs(sg_parts[0])
        morph = sg_parts[1] if len(sg_parts) > 1 else ''
    else:
        strongs = normalize_strongs(strongs_grammar)

    return {
        'word': word,
        'transliteration': transliteration,
        'strongs': strongs,
        'morph': morph,
        'gloss': english,
    }


def parse_tahot(filepath: Path) -> Iterator[dict]:
    """
    Parse TAHOT Hebrew Old Testament file.

    Yields verse dictionaries with word-level tagging.
    """
    current_verse_ref = None
    word_data = []

    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()

            if not line or line.startswith('#'):
                continue

            parts = line.split('\t')

            if len(parts) < 4:
                continue

            full_ref = parts[0].strip()
            verse_ref = extract_verse_ref(full_ref)

            # New verse
            if verse_ref != current_verse_ref:
                if current_verse_ref and word_data:
                    yield build_verse_entry(current_verse_ref, word_data, 'hebrew')

                current_verse_ref = verse_ref
                word_data = []

            # Parse word data
            word_entry = parse_hebrew_word(parts)
            if word_entry:
                word_data.append(word_entry)

    # Yield final verse
    if current_verse_ref and word_data:
        yield build_verse_entry(current_verse_ref, word_data, 'hebrew')


def parse_hebrew_word(parts: list[str]) -> dict | None:
    """Parse a single Hebrew word from TAHOT.

    TAHOT columns:
    0: Reference (Gen.1.1#01=L)
    1: Hebrew word (בְּ/רֵאשִׁ֖ית)
    2: Transliteration (be./re.Shit)
    3: English translation (in/ beginning)
    4: Strong's numbers (H9003/{H7225G})
    5: Morphology (HR/Ncfsa)
    """
    if len(parts) < 4:
        return None

    word = parts[1].strip() if len(parts) > 1 else ''
    transliteration = parts[2].strip() if len(parts) > 2 else ''
    english = parts[3].strip() if len(parts) > 3 else ''

    # Parse Strong's - may have multiple (H9003/{H7225G})
    strongs_field = parts[4].strip() if len(parts) > 4 else ''
    # Extract the primary Strong's number
    strongs = ''
    if strongs_field:
        # Remove braces and take first number
        strongs_clean = re.sub(r'[{}]', '', strongs_field)
        strongs_parts = re.split(r'[/,]', strongs_clean)
        for s in strongs_parts:
            normalized = normalize_strongs(s.strip())
            if normalized and normalized.startswith('H'):
                strongs = normalized
                break

    morph = parts[5].strip() if len(parts) > 5 else ''

    return {
        'word': word,
        'transliteration': transliteration,
        'strongs': strongs,
        'morph': morph,
        'gloss': english,
    }


def build_verse_entry(ref: str, word_data: list[dict], language: str) -> dict:
    """Build a verse entry from word data."""
    # Parse reference into components
    match = re.match(r'^(\w+)\.(\d+)\.(\d+)', ref)
    
    book = match.group(1) if match else ref
    chapter = int(match.group(2)) if match else 0
    verse = int(match.group(3)) if match else 0
    
    # Build original text from words
    original_text = ' '.join(w['word'] for w in word_data if w.get('word'))
    
    # Build English gloss
    english_text = ' '.join(w['gloss'] for w in word_data if w.get('gloss'))
    
    return {
        'reference': ref,
        'book': book,
        'chapter': chapter,
        'verse': verse,
        'text_english': english_text,
        'text_original': original_text,
        'word_data': json.dumps(word_data, ensure_ascii=False),
    }


def normalize_strongs(strongs: str) -> str:
    """Normalize a Strong's number."""
    if not strongs:
        return ''
    
    # Handle multiple Strong's (e.g., "G1234/G5678")
    strongs = strongs.split('/')[0]
    strongs = strongs.split(',')[0]
    
    # Remove any non-standard prefixes
    strongs = strongs.strip()
    
    # Ensure proper format
    match = re.match(r'^([GH])(\d+)([a-z])?', strongs, re.IGNORECASE)
    if match:
        prefix = match.group(1).upper()
        number = match.group(2)
        suffix = match.group(3) or ''
        return f"{prefix}{number}{suffix}"
    
    return strongs


def parse_morphology_codes(filepath: Path, language: str) -> Iterator[dict]:
    """
    Parse morphology expansion files (TEGMC or TEHMC).
    
    Returns dictionaries mapping codes to their full descriptions.
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            
            if not line or line.startswith('#'):
                continue
            
            parts = line.split('\t')
            
            if len(parts) < 2:
                continue
            
            code = parts[0].strip()
            parsing = parts[1].strip() if len(parts) > 1 else ''
            
            entry = parse_morph_code(code, parsing, language)
            if entry:
                yield entry


def parse_morph_code(code: str, parsing: str, language: str) -> dict | None:
    """Parse a single morphology code."""
    if not code:
        return None
    
    entry = {
        'code': code,
        'language': language,
        'parsing': parsing,
        'part_of_speech': '',
        'person': '',
        'number': '',
        'tense': '',
        'voice': '',
        'mood': '',
        'case_value': '',
        'gender': '',
    }
    
    # Parse Greek Robinson codes (e.g., V-AAI-3S, N-GSF)
    if language == 'greek':
        entry = parse_robinson_code(code, parsing, entry)
    
    # Parse Hebrew codes
    elif language == 'hebrew':
        entry = parse_hebrew_morph(code, parsing, entry)
    
    return entry


def parse_robinson_code(code: str, parsing: str, entry: dict) -> dict:
    """Parse a Greek Robinson morphology code."""
    parts = code.split('-')
    
    if not parts:
        return entry
    
    # Part of speech is first character(s)
    pos_map = {
        'V': 'Verb',
        'N': 'Noun',
        'A': 'Adjective',
        'D': 'Adverb',
        'P': 'Preposition',
        'C': 'Conjunction',
        'T': 'Article',
        'R': 'Pronoun',
        'I': 'Interjection',
        'X': 'Particle',
    }
    
    pos = parts[0]
    entry['part_of_speech'] = pos_map.get(pos[0], pos)
    
    # For verbs: Tense-Voice-Mood-Person-Number
    if pos.startswith('V') and len(parts) > 1:
        verb_part = parts[1] if len(parts) > 1 else ''
        
        tense_map = {'P': 'Present', 'I': 'Imperfect', 'F': 'Future', 
                     'A': 'Aorist', 'R': 'Perfect', 'L': 'Pluperfect'}
        voice_map = {'A': 'Active', 'M': 'Middle', 'P': 'Passive', 
                     'E': 'Middle/Passive', 'D': 'Middle Deponent', 
                     'O': 'Passive Deponent', 'N': 'Middle/Passive Deponent'}
        mood_map = {'I': 'Indicative', 'S': 'Subjunctive', 'O': 'Optative',
                    'M': 'Imperative', 'N': 'Infinitive', 'P': 'Participle'}
        
        if len(verb_part) >= 1:
            entry['tense'] = tense_map.get(verb_part[0], '')
        if len(verb_part) >= 2:
            entry['voice'] = voice_map.get(verb_part[1], '')
        if len(verb_part) >= 3:
            entry['mood'] = mood_map.get(verb_part[2], '')
        
        # Person-Number
        if len(parts) > 2:
            pn = parts[2]
            person_map = {'1': '1st', '2': '2nd', '3': '3rd'}
            number_map = {'S': 'Singular', 'P': 'Plural'}
            
            if len(pn) >= 1:
                entry['person'] = person_map.get(pn[0], '')
            if len(pn) >= 2:
                entry['number'] = number_map.get(pn[1], '')
    
    # For nouns/adjectives: Case-Number-Gender
    elif pos.startswith(('N', 'A')) and len(parts) > 1:
        cng = parts[1]
        
        case_map = {'N': 'Nominative', 'G': 'Genitive', 'D': 'Dative',
                    'A': 'Accusative', 'V': 'Vocative'}
        number_map = {'S': 'Singular', 'P': 'Plural'}
        gender_map = {'M': 'Masculine', 'F': 'Feminine', 'N': 'Neuter'}
        
        if len(cng) >= 1:
            entry['case_value'] = case_map.get(cng[0], '')
        if len(cng) >= 2:
            entry['number'] = number_map.get(cng[1], '')
        if len(cng) >= 3:
            entry['gender'] = gender_map.get(cng[2], '')
    
    return entry


def parse_hebrew_morph(code: str, parsing: str, entry: dict) -> dict:
    """Parse a Hebrew morphology code."""
    # Hebrew morphology is more complex
    # Simplified parsing here - expand as needed
    
    pos_map = {
        'A': 'Adjective',
        'C': 'Conjunction',
        'D': 'Adverb',
        'N': 'Noun',
        'P': 'Pronoun',
        'R': 'Preposition',
        'S': 'Suffix',
        'T': 'Particle',
        'V': 'Verb',
    }
    
    if code:
        entry['part_of_speech'] = pos_map.get(code[0], code[0])
    
    return entry
