"""
Parsers for STEPBible data files.

These parsers read the tab-separated text files from STEPBible
and convert them into structured data for the database.
"""

from .lexicon import parse_greek_lexicon, parse_hebrew_lexicon
from .tagged_text import parse_tagnt, parse_tahot
from .proper_names import parse_tipnr

__all__ = [
    "parse_greek_lexicon",
    "parse_hebrew_lexicon", 
    "parse_tagnt",
    "parse_tahot",
    "parse_tipnr",
]
