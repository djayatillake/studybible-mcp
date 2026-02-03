"""
Database layer for the Study Bible MCP server.

Uses SQLite with async access via aiosqlite.
"""

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

import aiosqlite


class StudyBibleDB:
    """Async SQLite database interface for Bible study data."""
    
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.conn: aiosqlite.Connection | None = None
    
    async def connect(self):
        """Open database connection."""
        self.conn = await aiosqlite.connect(self.db_path)
        self.conn.row_factory = aiosqlite.Row
    
    async def close(self):
        """Close database connection."""
        if self.conn:
            await self.conn.close()
            self.conn = None
    
    async def __aenter__(self):
        await self.connect()
        return self
    
    async def __aexit__(self, *args):
        await self.close()
    
    # =========================================================================
    # Lexicon queries
    # =========================================================================
    
    async def get_lexicon_entry(self, strongs: str) -> dict | None:
        """Get a single lexicon entry by Strong's number."""
        strongs = strongs.upper()
        async with self.conn.execute(
            "SELECT * FROM lexicon WHERE strongs = ?",
            (strongs,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None
    
    async def search_lexicon(
        self,
        query: str,
        language: str | None = None,
        limit: int = 10
    ) -> list[dict]:
        """Search lexicon by definition, transliteration, or word."""
        query_lower = f"%{query.lower()}%"
        
        sql = """
            SELECT * FROM lexicon
            WHERE (
                LOWER(short_definition) LIKE ?
                OR LOWER(full_definition) LIKE ?
                OR LOWER(transliteration) LIKE ?
                OR LOWER(word) LIKE ?
            )
        """
        params = [query_lower, query_lower, query_lower, query_lower]
        
        if language:
            sql += " AND language = ?"
            params.append(language.lower())
        
        sql += " ORDER BY usage_count DESC LIMIT ?"
        params.append(limit)
        
        async with self.conn.execute(sql, params) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
    
    async def get_related_words(self, strongs: str) -> list[dict]:
        """Get words related to a Strong's number."""
        entry = await self.get_lexicon_entry(strongs)
        if not entry or not entry.get('related_words'):
            return []
        
        try:
            related = json.loads(entry['related_words'])
            results = []
            for r in related:
                if isinstance(r, dict) and r.get('strongs'):
                    full_entry = await self.get_lexicon_entry(r['strongs'])
                    if full_entry:
                        results.append(full_entry)
            return results
        except:
            return []
    
    # =========================================================================
    # Verse queries
    # =========================================================================
    
    def _normalize_reference(self, reference: str) -> str:
        """Normalize a Bible reference to database format."""
        # Handle common variations: "John 3:16" -> "Jhn.3.16"
        # This is a simplified version - expand as needed
        
        book_map = {
            "genesis": "Gen", "gen": "Gen",
            "exodus": "Exo", "exod": "Exo", "ex": "Exo",
            "leviticus": "Lev", "lev": "Lev",
            "numbers": "Num", "num": "Num",
            "deuteronomy": "Deu", "deut": "Deu", "dt": "Deu",
            "joshua": "Jos", "josh": "Jos",
            "judges": "Jdg", "judg": "Jdg",
            "ruth": "Rut",
            "1 samuel": "1Sa", "1sam": "1Sa", "1 sam": "1Sa",
            "2 samuel": "2Sa", "2sam": "2Sa", "2 sam": "2Sa",
            "1 kings": "1Ki", "1kgs": "1Ki", "1 kgs": "1Ki",
            "2 kings": "2Ki", "2kgs": "2Ki", "2 kgs": "2Ki",
            "1 chronicles": "1Ch", "1chr": "1Ch", "1 chr": "1Ch",
            "2 chronicles": "2Ch", "2chr": "2Ch", "2 chr": "2Ch",
            "ezra": "Ezr",
            "nehemiah": "Neh", "neh": "Neh",
            "esther": "Est", "esth": "Est",
            "job": "Job",
            "psalms": "Psa", "psalm": "Psa", "ps": "Psa",
            "proverbs": "Pro", "prov": "Pro", "pr": "Pro",
            "ecclesiastes": "Ecc", "eccl": "Ecc",
            "song of solomon": "Sng", "song": "Sng", "sos": "Sng",
            "isaiah": "Isa", "isa": "Isa",
            "jeremiah": "Jer", "jer": "Jer",
            "lamentations": "Lam", "lam": "Lam",
            "ezekiel": "Ezk", "ezek": "Ezk", "eze": "Ezk",
            "daniel": "Dan", "dan": "Dan",
            "hosea": "Hos", "hos": "Hos",
            "joel": "Jol",
            "amos": "Amo",
            "obadiah": "Oba", "obad": "Oba",
            "jonah": "Jon",
            "micah": "Mic", "mic": "Mic",
            "nahum": "Nam", "nah": "Nam",
            "habakkuk": "Hab", "hab": "Hab",
            "zephaniah": "Zep", "zeph": "Zep",
            "haggai": "Hag", "hag": "Hag",
            "zechariah": "Zec", "zech": "Zec",
            "malachi": "Mal", "mal": "Mal",
            "matthew": "Mat", "matt": "Mat", "mt": "Mat",
            "mark": "Mrk", "mk": "Mrk",
            "luke": "Luk", "lk": "Luk",
            "john": "Jhn", "jn": "Jhn",
            "acts": "Act",
            "romans": "Rom", "rom": "Rom",
            "1 corinthians": "1Co", "1cor": "1Co", "1 cor": "1Co",
            "2 corinthians": "2Co", "2cor": "2Co", "2 cor": "2Co",
            "galatians": "Gal", "gal": "Gal",
            "ephesians": "Eph", "eph": "Eph",
            "philippians": "Php", "phil": "Php",
            "colossians": "Col", "col": "Col",
            "1 thessalonians": "1Th", "1thess": "1Th", "1 thess": "1Th",
            "2 thessalonians": "2Th", "2thess": "2Th", "2 thess": "2Th",
            "1 timothy": "1Ti", "1tim": "1Ti", "1 tim": "1Ti",
            "2 timothy": "2Ti", "2tim": "2Ti", "2 tim": "2Ti",
            "titus": "Tit",
            "philemon": "Phm", "phlm": "Phm",
            "hebrews": "Heb", "heb": "Heb",
            "james": "Jas", "jas": "Jas",
            "1 peter": "1Pe", "1pet": "1Pe", "1 pet": "1Pe",
            "2 peter": "2Pe", "2pet": "2Pe", "2 pet": "2Pe",
            "1 john": "1Jn", "1jn": "1Jn",
            "2 john": "2Jn", "2jn": "2Jn",
            "3 john": "3Jn", "3jn": "3Jn",
            "jude": "Jud",
            "revelation": "Rev", "rev": "Rev",
        }
        
        # Parse reference like "John 3:16" or "1 Corinthians 13:4-7"
        match = re.match(
            r'^(\d?\s*[a-zA-Z]+)\s*(\d+):(\d+)(?:-(\d+))?$',
            reference.strip()
        )
        
        if match:
            book, chapter, verse_start, verse_end = match.groups()
            book_key = book.lower().strip()
            book_abbr = book_map.get(book_key, book[:3].title())
            return f"{book_abbr}.{chapter}.{verse_start}"
        
        return reference
    
    async def get_verse(self, reference: str) -> dict | None:
        """Get a verse by reference."""
        normalized = self._normalize_reference(reference)
        
        # Try exact match first
        async with self.conn.execute(
            "SELECT * FROM verses WHERE reference = ?",
            (normalized,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return dict(row)
        
        # Try pattern match
        async with self.conn.execute(
            "SELECT * FROM verses WHERE reference LIKE ?",
            (f"%{normalized}%",)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None
    
    async def get_verses_with_strongs(self, strongs: str, limit: int = 20) -> list[dict]:
        """Find verses containing a specific Strong's number."""
        strongs = strongs.upper()
        
        async with self.conn.execute(
            """
            SELECT * FROM verses 
            WHERE word_data LIKE ?
            LIMIT ?
            """,
            (f'%"{strongs}"%', limit)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
    
    # =========================================================================
    # Cross-reference queries
    # =========================================================================
    
    async def get_cross_references(self, reference: str) -> list[dict]:
        """Get cross-references for a verse."""
        normalized = self._normalize_reference(reference)
        
        async with self.conn.execute(
            "SELECT * FROM cross_references WHERE source = ? OR source LIKE ?",
            (normalized, f"%{normalized}%")
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
    
    async def get_thematic_references(self, theme: str) -> list[dict]:
        """Get references for a theological theme."""
        theme_lower = theme.lower().replace(" ", "_")
        
        async with self.conn.execute(
            "SELECT * FROM thematic_references WHERE theme = ? OR theme LIKE ?",
            (theme_lower, f"%{theme_lower}%")
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
    
    # =========================================================================
    # Name queries
    # =========================================================================
    
    async def lookup_name(self, name: str, name_type: str | None = None) -> list[dict]:
        """Look up a biblical name."""
        name_pattern = f"%{name}%"
        
        if name_type:
            async with self.conn.execute(
                "SELECT * FROM names WHERE name LIKE ? AND type = ?",
                (name_pattern, name_type)
            ) as cursor:
                rows = await cursor.fetchall()
        else:
            async with self.conn.execute(
                "SELECT * FROM names WHERE name LIKE ?",
                (name_pattern,)
            ) as cursor:
                rows = await cursor.fetchall()
        
        return [dict(row) for row in rows]
    
    # =========================================================================
    # Morphology queries
    # =========================================================================
    
    async def get_morphology(self, code: str, language: str = "greek") -> dict | None:
        """Get morphology parsing for a code."""
        async with self.conn.execute(
            "SELECT * FROM morphology WHERE code = ? AND language = ?",
            (code, language.lower())
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


def create_schema(conn: sqlite3.Connection):
    """Create the database schema."""
    conn.executescript("""
        -- Lexicon table for Greek and Hebrew words
        CREATE TABLE IF NOT EXISTS lexicon (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            strongs TEXT UNIQUE NOT NULL,
            language TEXT NOT NULL,
            word TEXT,
            transliteration TEXT,
            pronunciation TEXT,
            short_definition TEXT,
            full_definition TEXT,
            etymology TEXT,
            usage_count INTEGER DEFAULT 0,
            semantic_domain TEXT,
            related_words TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_lexicon_strongs ON lexicon(strongs);
        CREATE INDEX IF NOT EXISTS idx_lexicon_language ON lexicon(language);
        
        -- Verses table for tagged Bible text
        CREATE TABLE IF NOT EXISTS verses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reference TEXT UNIQUE NOT NULL,
            book TEXT,
            chapter INTEGER,
            verse INTEGER,
            text_english TEXT,
            text_original TEXT,
            word_data TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_verses_reference ON verses(reference);
        CREATE INDEX IF NOT EXISTS idx_verses_book ON verses(book);
        
        -- Biblical names table
        CREATE TABLE IF NOT EXISTS names (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            name_original TEXT,
            type TEXT,
            description TEXT,
            refs TEXT,
            relationships TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_names_name ON names(name);
        CREATE INDEX IF NOT EXISTS idx_names_type ON names(type);
        
        -- Cross references
        CREATE TABLE IF NOT EXISTS cross_references (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            target TEXT NOT NULL,
            type TEXT,
            note TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_xref_source ON cross_references(source);
        
        -- Thematic references
        CREATE TABLE IF NOT EXISTS thematic_references (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            theme TEXT NOT NULL,
            reference TEXT NOT NULL,
            note TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_theme_name ON thematic_references(theme);
        
        -- Morphology codes
        CREATE TABLE IF NOT EXISTS morphology (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL,
            language TEXT NOT NULL,
            parsing TEXT,
            part_of_speech TEXT,
            person TEXT,
            number TEXT,
            tense TEXT,
            voice TEXT,
            mood TEXT,
            case_value TEXT,
            gender TEXT,
            UNIQUE(code, language)
        );
        CREATE INDEX IF NOT EXISTS idx_morph_code ON morphology(code);
    """)
    conn.commit()
