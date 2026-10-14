"""Reading morphology codes as the tagged text prints them.

The morphology table holds STEPBible's code expansions (TEGMC for Greek,
TEHMC for Hebrew), one row per code: 'V-AAI-3S', 'HVqp3ms', 'Hc'. The tagged
text, and so lookup_verse, prints compounds of them:

- Hebrew prefixes and suffixes joined by "/", where only the first segment
  carries the language letter: 'Hc/Vqw3ms' is 'Hc' + 'HVqw3ms', and
  'HNcmsc/Sp3ms' is 'HNcmsc' + 'HSp3ms'. People also drop the letter
  ('Vqp3ms') or the case ('v-aai-3s').
- Greek crasis joined by " + ": 'P-1NS + G2532=CONJ' is 'P-1NS' + 'CONJ'.

``morphology_lookups`` lists the readings of a code to try, and
``parse_fields`` splits an expansion ('Function=Verb; Tense=2nd Aorist; ...')
into the fields parse_morphology shows, so its header always agrees with the
expansion.
"""

from __future__ import annotations

import re

LANGUAGES = ("greek", "hebrew")

# Hebrew codes after the language letter start with one of these (TEHMC).
_HEBREW_FUNCTION = re.compile(r"^[ACDNPRSTV]")
_GREEK_STRONGS_PREFIX = re.compile(r"^G\d+[A-Z]?=", re.IGNORECASE)

FIELD_LABELS = {"Function": "Part of Speech"}


def _greek_segments(code: str) -> list[tuple[str, str]]:
    segments = []
    for piece in code.split("+"):
        piece = _GREEK_STRONGS_PREFIX.sub("", piece.strip())
        if piece:
            segments.append((piece, piece.upper()))
    return segments


def _hebrew_readings(code: str) -> list[list[tuple[str, str]]]:
    pieces = [piece.strip() for piece in code.split("/")]
    if not all(pieces):
        return []
    readings = []
    first = pieces[0]
    # As written: the first piece carries the language letter (H or A),
    # which the later pieces share.
    letter = first[0]
    if letter in "HAha" and len(first) > 1:
        rest = [(piece, letter.upper() + piece) for piece in pieces[1:]]
        readings.append([(first, letter.upper() + first[1:])] + rest)
    # Without a language letter ('Vqp3ms', 'Ncmsa/Sp3ms'): Hebrew.
    if _HEBREW_FUNCTION.match(first.upper()):
        readings.append([(piece, "H" + piece) for piece in pieces])
    return readings


def morphology_lookups(code: str, language: str | None = None) -> list[tuple[str, list[tuple[str, str]]]]:
    """Readings of ``code`` to try, best first: [(language, [(shown, db_code), ...])].

    The requested language comes first; the other is tried after it, so a
    Hebrew code passed with the default language still parses. Each reading
    lists the code's segments as written and as stored in the table.
    """
    code = code.strip()
    if not code:
        return []
    order = list(LANGUAGES)
    if language and language.lower() in order:
        order.remove(language.lower())
        order.insert(0, language.lower())
    readings = []
    for lang in order:
        if lang == "greek":
            segments = _greek_segments(code)
            if segments:
                readings.append((lang, segments))
        else:
            readings.extend((lang, segments) for segments in _hebrew_readings(code))
    return readings


def _split_top_level(text: str) -> list[str]:
    """Split on ';' outside parentheses."""
    parts, depth, current = [], 0, []
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(depth - 1, 0)
        if ch == ";" and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    parts.append("".join(current))
    return [part.strip() for part in parts if part.strip()]


def parse_fields(parsing: str | None) -> list[tuple[str, str]] | None:
    """Split a TEGMC/TEHMC expansion into (label, value) pairs.

    'Function=Verb; Tense=2nd Aorist; Voice=Middle Deponent' ->
    [('Part of Speech', 'Verb'), ('Tense', '2nd Aorist'), ('Voice', 'Middle Deponent')].
    Hebrew stems and forms keep what they imply: 'Stem=Qal (hence Action=Simple;
    Voice=Active)' -> ('Stem', 'Qal (Action: Simple; Voice: Active)').
    None when the text is not in Key=Value form.
    """
    fields = []
    for part in _split_top_level(parsing or ""):
        key, sep, value = part.partition("=")
        if not sep or not key.strip() or not value.strip():
            return None
        value = re.sub(r"\(hence\s+", "(", value.strip())
        value = re.sub(r"(\w)=", r"\1: ", value)
        key = key.strip()
        fields.append((FIELD_LABELS.get(key, key), value))
    return fields or None


# Columns of the morphology table, filled from the expansion's fields.
_COLUMN_FIELDS = {
    "part_of_speech": ("Function",),
    "person": ("Person",),
    "number": ("Number",),
    "tense": ("Tense",),
    "voice": ("Voice",),
    "mood": ("Mood",),
    "case_value": ("Case",),
    "gender": ("Gender",),
}


def morphology_columns(parsing: str | None) -> dict[str, str] | None:
    """The table columns an expansion gives, or None when it is not Key=Value.

    Hebrew voice, tense and mood are implied by the stem and form ('Stem=Qal
    (hence Action=Simple; Voice=Active)'); those implied values fill the
    columns, and a Greek participle's 'Form=Participle' fills the mood.
    """
    raw: dict[str, str] = {}
    for part in _split_top_level(parsing or ""):
        key, sep, value = part.partition("=")
        if not sep:
            return None
        key, value = key.strip(), value.strip()
        implied = re.search(r"\(hence\s+(.*)\)\s*$", value)
        if implied:
            value = value[: implied.start()].strip()
            for inner in implied.group(1).split(";"):
                inner_key, inner_sep, inner_value = inner.partition("=")
                if inner_sep:
                    raw.setdefault(inner_key.strip(), inner_value.strip())
        raw[key] = value
    if not raw:
        return None
    columns = {column: "" for column in _COLUMN_FIELDS}
    for column, keys in _COLUMN_FIELDS.items():
        for key in keys:
            if raw.get(key):
                columns[column] = raw[key]
                break
    if not columns["mood"] and raw.get("Form") in ("Participle", "Infinitive"):
        columns["mood"] = raw["Form"]
    return columns
