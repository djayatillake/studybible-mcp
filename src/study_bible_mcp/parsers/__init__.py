"""
Parsers for STEPBible data files and supplementary resources.

These parsers read the tab-separated text files from STEPBible,
BibleAquifer JSON files, and ACAI entity files, converting them
into structured data for the database.
"""

from .lexicon import (
    parse_greek_lexicon,
    parse_hebrew_lexicon,
    parse_tflsj_lexicon,
    parse_bdb_lexicon,
)
from .tagged_text import parse_tagnt, parse_tahot
from .proper_names import parse_tipnr
from .aquifer import parse_aquifer_content_file
from .acai import parse_acai_entities

__all__ = [
    "parse_greek_lexicon",
    "parse_hebrew_lexicon",
    "parse_tflsj_lexicon",
    "parse_bdb_lexicon",
    "parse_tagnt",
    "parse_tahot",
    "parse_tipnr",
    "parse_aquifer_content_file",
    "parse_acai_entities",
]
