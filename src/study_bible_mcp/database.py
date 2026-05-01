"""
Database layer for the Study Bible MCP server.

Uses SQLite with async access via aiosqlite.
"""

import json
import re
import sqlite3
import struct
from collections import deque
from pathlib import Path
from typing import Any

import aiosqlite
import logging

logger = logging.getLogger("study-bible-mcp")

# Canonical book abbreviation map — used by _normalize_reference() and importable by server.py
BOOK_ABBREV_MAP = {
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


class StudyBibleDB:
    """Async SQLite database interface for Bible study data."""

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.conn: aiosqlite.Connection | None = None
        self._vec_loaded = False
        self._vec_error: str | None = None

    async def connect(self):
        """Open database connection."""
        self.conn = await aiosqlite.connect(self.db_path)
        self.conn.row_factory = aiosqlite.Row

        # Try to load sqlite-vec extension for vector search
        await self._load_sqlite_vec()

    async def _load_sqlite_vec(self):
        """Load sqlite-vec extension if available."""
        if self._vec_loaded:
            return

        try:
            import sqlite_vec

            # Get the loadable path for sqlite-vec
            vec_path = sqlite_vec.loadable_path()

            # Use aiosqlite's built-in extension loading methods
            await self.conn.enable_load_extension(True)
            await self.conn.load_extension(vec_path)
            await self.conn.enable_load_extension(False)
            self._vec_loaded = True
            logger.info("sqlite-vec extension loaded successfully")
        except ImportError:
            self._vec_error = "sqlite-vec package not installed. Install with: pip install sqlite-vec"
            logger.warning(self._vec_error)
        except Exception as e:
            self._vec_error = f"Failed to load sqlite-vec extension: {e}"
            logger.warning(self._vec_error)
    
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
    
    async def _fetchall(self, sql: str, params: tuple | list = ()) -> list[dict]:
        """Execute SQL and return all rows as dicts."""
        async with self.conn.execute(sql, params) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def _fetchone(self, sql: str, params: tuple | list = ()) -> dict | None:
        """Execute SQL and return one row as dict, or None."""
        async with self.conn.execute(sql, params) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def _table_has_rows(self, table: str) -> bool:
        """Check if a table exists and has at least one row."""
        try:
            async with self.conn.execute(f"SELECT 1 FROM {table} LIMIT 1") as cursor:
                return await cursor.fetchone() is not None
        except Exception:
            return False

    # =========================================================================
    # Lexicon queries
    # =========================================================================
    
    @staticmethod
    def _normalize_strongs(strongs: str) -> str:
        """Normalize Strong's number to match DB format (e.g., G26 -> G0026)."""
        strongs = strongs.upper().strip()
        if len(strongs) >= 2 and strongs[0] in ("G", "H"):
            num = strongs[1:]
            return strongs[0] + num.zfill(4)
        return strongs

    async def get_lexicon_entry(self, strongs: str) -> dict | None:
        """Get a single lexicon entry by Strong's number."""
        strongs = self._normalize_strongs(strongs)
        return await self._fetchone("SELECT * FROM lexicon WHERE strongs = ?", (strongs,))
    
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
                OR LOWER(abbott_smith_def) LIKE ?
            )
        """
        params = [query_lower, query_lower, query_lower, query_lower, query_lower]
        
        if language:
            sql += " AND language = ?"
            params.append(language.lower())
        
        sql += " ORDER BY usage_count DESC LIMIT ?"
        params.append(limit)
        return await self._fetchall(sql, params)
    
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
        except Exception:
            return []
    
    # =========================================================================
    # Verse queries
    # =========================================================================
    
    def _normalize_reference(self, reference: str) -> str:
        """Normalize a Bible reference to database format."""
        # Handle common variations: "John 3:16" -> "Jhn.3.16"
        # This is a simplified version - expand as needed
        
        # Parse reference like "John 3:16" or "1 Corinthians 13:4-7"
        match = re.match(
            r'^(\d?\s*[a-zA-Z]+)\s*(\d+):(\d+)(?:-(\d+))?$',
            reference.strip()
        )
        
        if match:
            book, chapter, verse_start, verse_end = match.groups()
            book_key = book.lower().strip()
            book_abbr = BOOK_ABBREV_MAP.get(book_key, book[:3].title())
            return f"{book_abbr}.{chapter}.{verse_start}"
        
        return reference
    
    async def get_verse(self, reference: str) -> dict | None:
        """Get a verse by reference."""
        normalized = self._normalize_reference(reference)
        # Try exact match first, then pattern match
        return (
            await self._fetchone("SELECT * FROM verses WHERE reference = ?", (normalized,))
            or await self._fetchone("SELECT * FROM verses WHERE reference LIKE ?", (f"%{normalized}%",))
        )
    
    async def get_verses_with_strongs(self, strongs: str, limit: int = 20) -> list[dict]:
        """Find verses containing a specific Strong's number."""
        strongs = self._normalize_strongs(strongs)
        return await self._fetchall(
            "SELECT * FROM verses WHERE word_data LIKE ? LIMIT ?",
            (f'%"{strongs}"%', limit),
        )
    
    # =========================================================================
    # Cross-reference queries
    # =========================================================================
    
    async def get_cross_references(
        self,
        reference: str,
        source_filter: str | None = None,
        limit: int = 4,
        min_strength: int | None = None,
    ) -> list[dict]:
        """Get cross-references for a verse, ordered by strength.

        Ranks CH (Harrison/Romhild) above TSK (Treasury of Scripture Knowledge).
        Within each provenance, sorts by `relevance` desc — for CH this is
        Orig*2+Circ (range 0..3), for TSK it is the openbible.info vote count.

        Args:
            reference: verse reference, e.g. "John 3:16".
            source_filter: 'ch' or 'tsk' to restrict to one dataset.
            limit: max rows. Default 4 — kept deliberately small to protect
                LLM context from bloat. Each verse can return hundreds of
                refs so we surface only the strongest few. Raise it (with
                min_strength to floor TSK noise) when the user explicitly
                wants exhaustive study.
            min_strength: if set, TSK rows with relevance < min_strength are
                excluded. CH rows are never dropped by this filter (all CH
                pairs are hand-curated, so even relevance=0 means "vetted").
        """
        normalized = self._normalize_reference(reference)
        params: list = [normalized]
        sql = "SELECT * FROM cross_references WHERE source = ? "
        if source_filter:
            sql += "AND type = ? "
            params.append(source_filter)
        if min_strength is not None and min_strength > 0:
            # CH refs always pass; TSK must clear the threshold.
            sql += "AND (type = 'ch' OR relevance >= ?) "
            params.append(min_strength)
        sql += (
            "ORDER BY CASE type WHEN 'ch' THEN 2 WHEN 'tsk' THEN 1 ELSE 0 END DESC, "
            "         relevance DESC, "
            "         target "
            "LIMIT ?"
        )
        params.append(limit)
        return await self._fetchall(sql, tuple(params))

    async def get_thematic_references(self, theme: str) -> list[dict]:
        """Get references for a theological theme."""
        theme_lower = theme.lower().replace(" ", "_")
        return await self._fetchall(
            "SELECT * FROM thematic_references WHERE theme = ? OR theme LIKE ?",
            (theme_lower, f"%{theme_lower}%"),
        )
    
    # =========================================================================
    # Name queries
    # =========================================================================
    
    async def lookup_name(self, name: str, name_type: str | None = None) -> list[dict]:
        """Look up a biblical name."""
        name_pattern = f"%{name}%"
        if name_type:
            return await self._fetchall("SELECT * FROM names WHERE name LIKE ? AND type = ?", (name_pattern, name_type))
        return await self._fetchall("SELECT * FROM names WHERE name LIKE ?", (name_pattern,))
    
    # =========================================================================
    # Morphology queries
    # =========================================================================
    
    async def get_morphology(self, code: str, language: str = "greek") -> dict | None:
        """Get morphology parsing for a code."""
        return await self._fetchone("SELECT * FROM morphology WHERE code = ? AND language = ?", (code, language.lower()))

    # =========================================================================
    # Vector similarity queries
    # =========================================================================

    async def get_verse_embedding(self, verse_id: int) -> list[float] | None:
        """Get the embedding vector for a verse."""
        async with self.conn.execute(
            "SELECT embedding FROM verse_vectors WHERE verse_id = ?",
            (verse_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                # sqlite-vec returns bytes, need to decode
                embedding_bytes = row[0]
                if embedding_bytes:
                    return list(struct.unpack(f'{len(embedding_bytes)//4}f', embedding_bytes))
            return None

    async def find_similar_verses(
        self,
        verse_id: int,
        limit: int = 10,
        exclude_same_chapter: bool = False
    ) -> list[dict]:
        """Find verses semantically similar to a given verse."""
        # Get the source verse's embedding
        embedding = await self.get_verse_embedding(verse_id)
        if not embedding:
            return []

        # Get source verse info for exclusion
        async with self.conn.execute(
            "SELECT book, chapter FROM verses WHERE id = ?",
            (verse_id,)
        ) as cursor:
            source = await cursor.fetchone()

        # Convert embedding to bytes for sqlite-vec
        embedding_bytes = struct.pack(f'{len(embedding)}f', *embedding)

        # Find similar verses
        sql = """
            SELECT v.id, v.reference, v.book, v.chapter, v.verse,
                   v.text_english, v.text_original,
                   vec_distance_cosine(vv.embedding, ?) as distance
            FROM verse_vectors vv
            JOIN verses v ON v.id = vv.verse_id
            WHERE vv.verse_id != ?
        """
        params = [embedding_bytes, verse_id]

        if exclude_same_chapter and source:
            sql += " AND NOT (v.book = ? AND v.chapter = ?)"
            params.extend([source['book'], source['chapter']])

        sql += " ORDER BY distance LIMIT ?"
        params.append(limit)
        return await self._fetchall(sql, params)

    async def find_similar_passages(
        self,
        reference: str,
        limit: int = 10
    ) -> list[dict]:
        """Find passages semantically similar to a verse reference."""
        # First, get the verse
        verse = await self.get_verse(reference)
        if not verse:
            return []

        verse_id = verse['id']

        # Get embedding for this verse
        embedding = await self.get_verse_embedding(verse_id)
        if not embedding:
            return []

        # Convert embedding to bytes for sqlite-vec
        embedding_bytes = struct.pack(f'{len(embedding)}f', *embedding)

        # Search against passage embeddings
        sql = """
            SELECT p.id, p.reference_start, p.reference_end, p.book,
                   p.text_combined, p.verse_count, p.section_type,
                   vec_distance_cosine(pv.embedding, ?) as distance
            FROM passage_vectors pv
            JOIN passages p ON p.id = pv.passage_id
            WHERE NOT (p.start_verse_id <= ? AND p.end_verse_id >= ?)
            ORDER BY distance
            LIMIT ?
        """

        async with self.conn.execute(
            sql,
            (embedding_bytes, verse_id, verse_id, limit)
        ) as cursor:
            rows = await cursor.fetchall()
            results = []
            for row in rows:
                d = dict(row)
                # Format reference range nicely
                if d['reference_start'] == d['reference_end']:
                    d['reference'] = d['reference_start']
                else:
                    d['reference'] = f"{d['reference_start']} - {d['reference_end']}"
                # Convert distance to similarity score (0-1, higher is better)
                d['similarity'] = 1.0 - d['distance']
                results.append(d)
            return results

    # =========================================================================
    # Graph queries (Theographic Bible Metadata)
    # =========================================================================

    async def graph_find_person(self, name: str) -> list[dict]:
        """Find a person by name (fuzzy match).

        Orders by: exact name match first, then by number of aliases
        (more aliases = more prominent biblical figure), then family edges.
        """
        return await self._fetchall(
            """SELECT p.* FROM graph_people p
               LEFT JOIN (
                   SELECT from_person_id as pid, COUNT(*) as cnt FROM graph_family_edges GROUP BY from_person_id
                   UNION ALL
                   SELECT to_person_id, COUNT(*) FROM graph_family_edges GROUP BY to_person_id
               ) fe ON fe.pid = p.id
               WHERE LOWER(p.name) = LOWER(?)
                  OR LOWER(p.also_called) LIKE LOWER(?)
               GROUP BY p.id
               ORDER BY
                   CASE WHEN LOWER(p.name) = LOWER(?) THEN 0 ELSE 1 END,
                   LENGTH(COALESCE(p.also_called, '')) DESC,
                   COALESCE(SUM(fe.cnt), 0) DESC
               LIMIT 10""",
            (name, f"%{name}%", name),
        )

    async def graph_find_place(self, name: str) -> list[dict]:
        """Find a place by name (fuzzy match)."""
        return await self._fetchall(
            "SELECT * FROM graph_places WHERE LOWER(name) LIKE LOWER(?) LIMIT 10",
            (f"%{name}%",),
        )

    async def graph_get_ancestors(
        self, person_id: str, max_generations: int = 10
    ) -> list[dict]:
        """Get ancestors using recursive CTE."""
        return await self._fetchall("""
            WITH RECURSIVE ancestors AS (
                SELECT p.id, p.name, p.gender, p.birth_year, p.death_year,
                       0 as generation, 'self' as relationship
                FROM graph_people p WHERE p.id = ?

                UNION ALL

                SELECT p.id, p.name, p.gender, p.birth_year, p.death_year,
                       a.generation + 1,
                       e.relationship_type
                FROM ancestors a
                JOIN graph_family_edges e ON e.to_person_id = a.id
                JOIN graph_people p ON p.id = e.from_person_id
                WHERE e.relationship_type IN ('father_of', 'mother_of')
                  AND a.generation < ?
            )
            SELECT * FROM ancestors ORDER BY generation
        """, (person_id, max_generations))

    async def graph_get_descendants(
        self, person_id: str, max_generations: int = 10
    ) -> list[dict]:
        """Get descendants using recursive CTE."""
        return await self._fetchall("""
            WITH RECURSIVE descendants AS (
                SELECT p.id, p.name, p.gender, p.birth_year, p.death_year,
                       0 as generation, 'self' as relationship
                FROM graph_people p WHERE p.id = ?

                UNION ALL

                SELECT p.id, p.name, p.gender, p.birth_year, p.death_year,
                       d.generation + 1,
                       e.relationship_type
                FROM descendants d
                JOIN graph_family_edges e ON e.from_person_id = d.id
                JOIN graph_people p ON p.id = e.to_person_id
                WHERE e.relationship_type IN ('father_of', 'mother_of')
                  AND d.generation < ?
            )
            SELECT * FROM descendants ORDER BY generation
        """, (person_id, max_generations))

    async def graph_find_path(
        self, person1_id: str, person2_id: str, max_depth: int = 15
    ) -> list[dict]:
        """Find shortest relationship path between two people using Python-side BFS.

        Returns list of dicts with from_name, to_name, relationship_type for each step.
        """
        if person1_id == person2_id:
            return []

        # Build adjacency list from the (small) family edges table
        adjacency: dict[str, list[tuple[str, str]]] = {}  # person_id -> [(neighbor_id, rel_type)]
        async with self.conn.execute(
            "SELECT from_person_id, to_person_id, relationship_type FROM graph_family_edges"
        ) as cursor:
            for row in await cursor.fetchall():
                fid, tid, rel = row[0], row[1], row[2]
                adjacency.setdefault(fid, []).append((tid, rel))
                # Reverse edge for bidirectional traversal
                reverse_rel = rel
                if rel == "father_of" or rel == "mother_of":
                    reverse_rel = "child_of"
                elif rel == "child_of":
                    reverse_rel = "parent_of"
                adjacency.setdefault(tid, []).append((fid, reverse_rel))

        # BFS
        queue = deque([(person1_id, [person1_id])])
        visited = {person1_id}

        while queue:
            current, path = queue.popleft()
            if len(path) - 1 >= max_depth:
                continue

            for neighbor_id, rel_type in adjacency.get(current, []):
                if neighbor_id in visited:
                    continue
                new_path = path + [neighbor_id]
                if neighbor_id == person2_id:
                    # Reconstruct path with names and relationships
                    result = []
                    # Walk the path and find the relationship at each step
                    for i in range(len(new_path) - 1):
                        from_id = new_path[i]
                        to_id = new_path[i + 1]
                        # Find the relationship type for this edge
                        step_rel = "related_to"
                        for nid, rt in adjacency.get(from_id, []):
                            if nid == to_id:
                                step_rel = rt
                                break
                        result.append({
                            "current_id": from_id,
                            "next_id": to_id,
                            "relationship_type": step_rel,
                            "depth": i + 1,
                            "from_name": from_id,  # placeholder, resolved below
                            "to_name": to_id,       # placeholder, resolved below
                        })

                    # Resolve names
                    all_ids = list(set(new_path))
                    placeholders = ",".join("?" * len(all_ids))
                    name_map = {}
                    async with self.conn.execute(
                        f"SELECT id, name FROM graph_people WHERE id IN ({placeholders})",
                        all_ids
                    ) as cursor:
                        for row in await cursor.fetchall():
                            name_map[row[0]] = row[1]

                    for step in result:
                        step["from_name"] = name_map.get(step["current_id"], step["current_id"])
                        step["to_name"] = name_map.get(step["next_id"], step["next_id"])

                    return result

                visited.add(neighbor_id)
                queue.append((neighbor_id, new_path))

        return []  # No path found

    async def graph_get_family(self, person_id: str) -> dict:
        """Get immediate family of a person."""
        return {
            "parents": await self._fetchall(
                """SELECT p.*, e.relationship_type FROM graph_family_edges e
                   JOIN graph_people p ON p.id = e.from_person_id
                   WHERE e.to_person_id = ?
                     AND e.relationship_type IN ('father_of', 'mother_of')""",
                (person_id,),
            ),
            "children": await self._fetchall(
                """SELECT p.*, e.relationship_type FROM graph_family_edges e
                   JOIN graph_people p ON p.id = e.to_person_id
                   WHERE e.from_person_id = ?
                     AND e.relationship_type IN ('father_of', 'mother_of')""",
                (person_id,),
            ),
            "partners": await self._fetchall(
                """SELECT p.* FROM graph_family_edges e
                   JOIN graph_people p ON p.id = CASE
                       WHEN e.from_person_id = ? THEN e.to_person_id
                       ELSE e.from_person_id END
                   WHERE (e.from_person_id = ? OR e.to_person_id = ?)
                     AND e.relationship_type = 'partner_of'""",
                (person_id, person_id, person_id),
            ),
            "siblings": await self._fetchall(
                """SELECT p.* FROM graph_family_edges e
                   JOIN graph_people p ON p.id = CASE
                       WHEN e.from_person_id = ? THEN e.to_person_id
                       ELSE e.from_person_id END
                   WHERE (e.from_person_id = ? OR e.to_person_id = ?)
                     AND e.relationship_type = 'sibling_of'""",
                (person_id, person_id, person_id),
            ),
        }

    async def graph_get_person_events(self, person_id: str) -> list[dict]:
        """Get all events a person participated in."""
        return await self._fetchall(
            """SELECT e.* FROM graph_person_event_edges pe
               JOIN graph_events e ON e.id = pe.event_id
               WHERE pe.person_id = ?
               ORDER BY e.sort_key""",
            (person_id,),
        )

    async def graph_get_event_places(self, event_id: str) -> list[dict]:
        """Get all places where an event occurred."""
        return await self._fetchall(
            """SELECT p.* FROM graph_event_place_edges ep
               JOIN graph_places p ON p.id = ep.place_id
               WHERE ep.event_id = ?""",
            (event_id,),
        )

    async def graph_get_place_events(self, place_id: str) -> list[dict]:
        """Get all events at a place."""
        return await self._fetchall(
            """SELECT e.* FROM graph_event_place_edges ep
               JOIN graph_events e ON e.id = ep.event_id
               WHERE ep.place_id = ?
               ORDER BY e.sort_key""",
            (place_id,),
        )

    async def graph_get_place_people(self, place_id: str) -> dict:
        """Get people born/died at a place."""
        return {
            "born_here": await self._fetchall("SELECT * FROM graph_people WHERE birth_place_id = ?", (place_id,)),
            "died_here": await self._fetchall("SELECT * FROM graph_people WHERE death_place_id = ?", (place_id,)),
            "visited": [],
        }

    # Map from our DB abbreviations to Theographic abbreviations
    _THEOGRAPHIC_BOOK_MAP = {
        "1Ch": "1Chr", "1Co": "1Cor", "1Jn": "1John", "1Ki": "1Kgs",
        "1Pe": "1Pet", "1Sa": "1Sam", "1Th": "1Thess", "1Ti": "1Tim",
        "2Ch": "2Chr", "2Co": "2Cor", "2Jn": "2John", "2Ki": "2Kgs",
        "2Pe": "2Pet", "2Sa": "2Sam", "2Th": "2Thess", "2Ti": "2Tim",
        "3Jn": "3John", "Act": "Acts", "Amo": "Amos", "Deu": "Deut",
        "Ecc": "Eccl", "Est": "Esth", "Exo": "Exod", "Ezk": "Ezek",
        "Jdg": "Judg", "Jhn": "John", "Jol": "Joel", "Jon": "Jonah",
        "Jos": "Josh", "Jud": "Jude", "Luk": "Luke", "Mat": "Matt",
        "Mrk": "Mark", "Nam": "Nah", "Oba": "Obad", "Phm": "Phlm",
        "Php": "Phil", "Pro": "Prov", "Psa": "Ps", "Rut": "Ruth",
        "Sng": "Song", "Tit": "Titus", "Zec": "Zech", "Zep": "Zeph",
    }

    def _to_theographic_ref(self, ref: str) -> str:
        """Convert our DB verse reference format to Theographic format."""
        parts = ref.split(".")
        if parts:
            parts[0] = self._THEOGRAPHIC_BOOK_MAP.get(parts[0], parts[0])
        return ".".join(parts)

    async def graph_get_verse_entities(
        self, verse_ref: str
    ) -> dict:
        """Get all entities mentioned in a verse."""
        result = {"people": [], "places": [], "events": []}
        theo_ref = self._to_theographic_ref(verse_ref)

        async with self.conn.execute(
            """SELECT vm.entity_type, vm.entity_id,
                      COALESCE(p.name, pl.name, e.title) as entity_name
               FROM graph_verse_mentions vm
               LEFT JOIN graph_people p ON vm.entity_type = 'person' AND p.id = vm.entity_id
               LEFT JOIN graph_places pl ON vm.entity_type = 'place' AND pl.id = vm.entity_id
               LEFT JOIN graph_events e ON vm.entity_type = 'event' AND e.id = vm.entity_id
               WHERE vm.verse_ref = ?""",
            (theo_ref,)
        ) as cursor:
            for row in await cursor.fetchall():
                d = dict(row)
                if d["entity_type"] == "person":
                    result["people"].append(d)
                elif d["entity_type"] == "place":
                    result["places"].append(d)
                elif d["entity_type"] == "event":
                    result["events"].append(d)

        return result

    async def graph_get_chapter_entities(
        self, book: str, chapter: int
    ) -> dict:
        """Get all entities mentioned in a chapter."""
        result = {"people": [], "places": [], "events": []}
        theo_book = self._THEOGRAPHIC_BOOK_MAP.get(book, book)
        ref_pattern = f"{theo_book}.{chapter}.%"

        async with self.conn.execute(
            """SELECT DISTINCT vm.entity_type, vm.entity_id,
                      COALESCE(p.name, pl.name, e.title) as entity_name
               FROM graph_verse_mentions vm
               LEFT JOIN graph_people p ON vm.entity_type = 'person' AND p.id = vm.entity_id
               LEFT JOIN graph_places pl ON vm.entity_type = 'place' AND pl.id = vm.entity_id
               LEFT JOIN graph_events e ON vm.entity_type = 'event' AND e.id = vm.entity_id
               WHERE vm.verse_ref LIKE ?""",
            (ref_pattern,)
        ) as cursor:
            for row in await cursor.fetchall():
                d = dict(row)
                if d["entity_type"] == "person":
                    result["people"].append(d)
                elif d["entity_type"] == "place":
                    result["places"].append(d)
                elif d["entity_type"] == "event":
                    result["events"].append(d)

        return result

    async def graph_has_data(self) -> bool:
        """Check if graph tables have data."""
        return await self._table_has_rows("graph_people")

    async def has_vector_tables(self) -> bool:
        """Check if vector tables exist and have data."""
        if not self._vec_loaded:
            return False
        return await self._table_has_rows("verse_vectors")

    # =========================================================================
    # Aquifer content queries
    # =========================================================================

    # Book abbreviation to 2-digit number for BBCCCVVV references
    _BOOK_ABBR_TO_NUM = {
        "Gen": "01", "Exo": "02", "Lev": "03", "Num": "04", "Deu": "05",
        "Jos": "06", "Jdg": "07", "Rut": "08", "1Sa": "09", "2Sa": "10",
        "1Ki": "11", "2Ki": "12", "1Ch": "13", "2Ch": "14", "Ezr": "15",
        "Neh": "16", "Est": "17", "Job": "18", "Psa": "19", "Pro": "20",
        "Ecc": "21", "Sng": "22", "Isa": "23", "Jer": "24", "Lam": "25",
        "Ezk": "26", "Dan": "27", "Hos": "28", "Jol": "29", "Amo": "30",
        "Oba": "31", "Jon": "32", "Mic": "33", "Nam": "34", "Hab": "35",
        "Zep": "36", "Hag": "37", "Zec": "38", "Mal": "39",
        "Mat": "40", "Mrk": "41", "Luk": "42", "Jhn": "43", "Act": "44",
        "Rom": "45", "1Co": "46", "2Co": "47", "Gal": "48", "Eph": "49",
        "Php": "50", "Col": "51", "1Th": "52", "2Th": "53", "1Ti": "54",
        "2Ti": "55", "Tit": "56", "Phm": "57", "Heb": "58", "Jas": "59",
        "1Pe": "60", "2Pe": "61", "1Jn": "62", "2Jn": "63", "3Jn": "64",
        "Jud": "65", "Rev": "66",
    }

    def _to_aquifer_ref(self, normalized_ref: str) -> str | None:
        """Convert normalized reference 'Gen.1.1' to Aquifer 8-digit format '01001001'."""
        parts = normalized_ref.split('.')
        if len(parts) != 3:
            return None
        book_num = self._BOOK_ABBR_TO_NUM.get(parts[0])
        if not book_num:
            return None
        try:
            chapter = int(parts[1])
            verse = int(parts[2])
            return f"{book_num}{chapter:03d}{verse:03d}"
        except (ValueError, IndexError):
            return None

    async def has_aquifer_data(self) -> bool:
        """Check if aquifer_content table exists and has data."""
        return await self._table_has_rows("aquifer_content")

    async def get_study_notes(self, reference: str) -> list[dict]:
        """Get study notes + translation notes for a verse reference.

        Fetches study_notes, translation_notes_uw, and translation_notes_sil
        for a specific verse. Matches both exact refs and ranges containing the verse.
        """
        normalized = self._normalize_reference(reference)
        aq_ref = self._to_aquifer_ref(normalized)
        if not aq_ref:
            return []

        return await self._fetchall("""
            SELECT * FROM aquifer_content
            WHERE resource_type IN ('study_notes', 'translation_notes_uw', 'translation_notes_sil')
              AND (
                start_ref = ?
                OR (start_ref <= ? AND end_ref >= ? AND is_range = 1)
              )
            ORDER BY resource_type, start_ref
        """, (aq_ref, aq_ref, aq_ref))

    async def get_chapter_study_notes(self, book: str, chapter: int) -> list[dict]:
        """Get all study notes for an entire chapter."""
        book_num = self._BOOK_ABBR_TO_NUM.get(book)
        if not book_num:
            return []

        return await self._fetchall("""
            SELECT * FROM aquifer_content
            WHERE resource_type IN ('study_notes', 'translation_notes_uw', 'translation_notes_sil')
              AND book = ?
              AND chapter_start = ?
            ORDER BY resource_type, start_ref
        """, (book, chapter))

    async def _search_aquifer_by_type(self, resource_type: str, query: str) -> list[dict]:
        """Search aquifer_content by type — exact title match then LIKE fallback."""
        exact = await self._fetchall(
            "SELECT * FROM aquifer_content WHERE resource_type = ? AND LOWER(title) = LOWER(?)",
            (resource_type, query),
        )
        if exact:
            return exact

        pattern = f"%{query}%"
        return await self._fetchall(
            """SELECT * FROM aquifer_content
               WHERE resource_type = ?
                 AND (LOWER(title) LIKE LOWER(?) OR LOWER(content_plain) LIKE LOWER(?))
               ORDER BY
                 CASE WHEN LOWER(title) LIKE LOWER(?) THEN 0 ELSE 1 END,
                 LENGTH(title)
               LIMIT 10""",
            (resource_type, pattern, pattern, pattern),
        )

    async def get_bible_dictionary(self, topic: str) -> list[dict]:
        """Search the Bible dictionary by title or content."""
        return await self._search_aquifer_by_type("dictionary", topic)

    async def get_key_terms(self, term: str) -> list[dict]:
        """Search FIA Key Terms by title or content."""
        return await self._search_aquifer_by_type("key_terms", term)

    async def search_aquifer_content(
        self,
        query: str,
        resource_type: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """Generic full-text search across any Aquifer resource type."""
        pattern = f"%{query}%"
        params: list = [pattern, pattern]

        sql = """
            SELECT * FROM aquifer_content
            WHERE (LOWER(title) LIKE LOWER(?) OR LOWER(content_plain) LIKE LOWER(?))
        """

        if resource_type:
            sql += " AND resource_type = ?"
            params.append(resource_type)

        sql += " ORDER BY CASE WHEN LOWER(title) LIKE LOWER(?) THEN 0 ELSE 1 END, LENGTH(title) LIMIT ?"
        params.extend([pattern, limit])

        return await self._fetchall(sql, params)

    # =========================================================================
    # ACAI entity queries
    # =========================================================================

    async def has_acai_data(self) -> bool:
        """Check if acai_entities table exists and has data."""
        return await self._table_has_rows("acai_entities")

    async def get_acai_entity(self, name: str) -> dict | None:
        """Get an ACAI entity by name (case-insensitive, fuzzy)."""
        exact = await self._fetchone(
            "SELECT * FROM acai_entities WHERE LOWER(name) = LOWER(?)", (name,)
        )
        if exact:
            return exact

        return await self._fetchone(
            "SELECT * FROM acai_entities WHERE LOWER(name) LIKE LOWER(?) ORDER BY reference_count DESC LIMIT 1",
            (f"%{name}%",),
        )

    # =========================================================================
    # ANE (Ancient Near East) context queries
    # =========================================================================

    async def has_ane_data(self) -> bool:
        """Check if ane_entries table exists and has data."""
        return await self._table_has_rows("ane_entries")

    async def get_ane_dimensions(self) -> list[dict]:
        """Get all available ANE dimensions with entry counts."""
        return await self._fetchall("""
            SELECT dimension, dimension_label, COUNT(*) as entry_count
            FROM ane_entries
            GROUP BY dimension, dimension_label
            ORDER BY dimension
        """)

    async def get_ane_context(
        self,
        reference: str | None = None,
        dimension: str | None = None,
        period: str | None = None,
        limit: int = 30,
    ) -> list[dict]:
        """Get ANE context entries filtered by reference, dimension, and/or period.

        Args:
            reference: Bible reference (e.g., "Genesis 1:1") - finds entries mapped to that book/chapter
            dimension: ANE dimension key (e.g., "cosmology_worldview")
            period: Timeline period (e.g., "patriarchal")
            limit: Max results to return
        """
        params: list = []
        conditions: list[str] = []
        join_clause = ""
        # Extra columns for relevance scoring when querying by reference
        extra_cols = ""
        order_clause = "ORDER BY e.dimension, e.period"

        if reference:
            normalized = self._normalize_reference(reference)
            parts = normalized.split(".")
            book_abbr = parts[0] if parts else ""
            chapter = int(parts[1]) if len(parts) > 1 else None

            join_clause = " JOIN ane_book_mappings bm ON e.id = bm.entry_id"
            conditions.append("bm.book = ?")
            params.append(book_abbr)

            if chapter is not None:
                conditions.append(
                    "(bm.chapter_start IS NULL OR (bm.chapter_start <= ? AND (bm.chapter_end IS NULL OR bm.chapter_end >= ?)))"
                )
                params.extend([chapter, chapter])

            # Relevance scoring: tighter chapter ranges = more relevant
            extra_cols = """,
                CASE
                    WHEN bm.chapter_start IS NULL THEN 1000
                    ELSE (COALESCE(bm.chapter_end, bm.chapter_start) - bm.chapter_start + 1)
                END AS relevance_score,
                CASE WHEN bm.chapter_start IS NOT NULL THEN 'direct' ELSE 'broad' END AS match_type"""
            order_clause = "ORDER BY relevance_score, e.dimension, e.period"

        if dimension:
            conditions.append("e.dimension = ?")
            params.append(dimension)

        if period:
            conditions.append("e.period = ?")
            params.append(period)

        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""

        sql = f"""
            SELECT DISTINCT e.*{extra_cols}
            FROM ane_entries e{join_clause}{where}
            {order_clause}
            LIMIT ?
        """
        params.append(limit)

        return await self._fetchall(sql, params)

    # =========================================================================
    # Torah Weave queries (Moshe Kline's Woven Torah hypothesis)
    # =========================================================================

    async def has_torah_weave_data(self) -> bool:
        """Check if torah_weave tables exist and have data."""
        return await self._table_has_rows("torah_weave_units")

    async def get_torah_weave_cells_for_reference(
        self, reference: str
    ) -> list[dict]:
        """Find all Torah Weave cells that contain the given reference.

        Returns cells joined with their parent unit metadata. Multiple cells
        may match if a verse sits within both a cell and a sibling subdivision
        in the same unit, or if units overlap at their boundaries.
        """
        normalized = self._normalize_reference(reference)
        parts = normalized.split(".")
        if len(parts) < 3:
            return []
        book_abbr = parts[0]
        try:
            chapter = int(parts[1])
            verse = int(parts[2])
        except ValueError:
            return []

        # Only Torah books have weave data
        if book_abbr not in ("Gen", "Exo", "Lev", "Num", "Deu"):
            return []

        target = chapter * 1000 + verse
        return await self._fetchall(
            """
            SELECT c.*,
                   u.id AS unit_serial,
                   u.book_full AS unit_book_full,
                   u.unit_number AS unit_number,
                   u.title AS unit_title,
                   u.verses AS unit_verses,
                   u.verse_range AS unit_verse_range,
                   u.format AS unit_format,
                   u.irregular AS unit_irregular,
                   u.is_unique AS unit_is_unique,
                   u.cell_count AS unit_cell_count,
                   u.type AS unit_type
            FROM torah_weave_cells c
            JOIN torah_weave_units u ON u.id = c.unit_id
            WHERE c.book = ?
              AND c.sort_start <= ?
              AND c.sort_end >= ?
            ORDER BY (c.sort_end - c.sort_start) ASC, c.row_num, c.column_letter
            """,
            (book_abbr, target, target),
        )

    async def get_torah_weave_unit_cells(self, unit_id: int) -> list[dict]:
        """Get all cells for a given unit, ordered by row then column then subdivision."""
        return await self._fetchall(
            """
            SELECT * FROM torah_weave_cells
            WHERE unit_id = ?
            ORDER BY row_num, column_letter,
                     CASE WHEN subdivision IS NULL THEN '' ELSE subdivision END
            """,
            (unit_id,),
        )

    # =========================================================================
    # Theological scholarship queries (unified: Heiser, Bradley, etc.)
    # =========================================================================

    async def has_theology_data(self, author: str | None = None) -> bool:
        """Check if theology_content table exists and has data."""
        if author:
            rows = await self._fetchall(
                "SELECT 1 FROM theology_content WHERE source_author = ? LIMIT 1",
                (author,),
            )
            return bool(rows)
        return await self._table_has_rows("theology_content")

    async def get_theology_context_by_reference(
        self, reference: str, author: str | None = None, limit: int = 20
    ) -> list[dict]:
        """Get scholarship entries relevant to a verse reference, optionally filtered by author."""
        normalized = self._normalize_reference(reference)
        parts = normalized.split(".")
        book = parts[0] if parts else ""
        chapter = int(parts[1]) if len(parts) > 1 else None

        params: list = []
        conditions = []

        if book:
            conditions.append("vi.book = ?")
            params.append(book)
        if chapter:
            conditions.append("vi.chapter = ?")
            params.append(chapter)

        author_filter = ""
        if author:
            author_filter = " AND tc.source_author = ?"

        # Try exact verse match first, then chapter-level
        exact_params: list = [normalized]
        if author:
            exact_params.append(author)
        exact_params.append(limit)

        exact = await self._fetchall(
            f"""SELECT DISTINCT tc.*, vi.reference AS matched_ref, vi.relevance,
                      GROUP_CONCAT(DISTINCT tt.theme_key) AS themes
               FROM theology_content tc
               JOIN theology_verse_index vi ON tc.id = vi.content_id
               LEFT JOIN theology_theme_index tti ON tc.id = tti.content_id
               LEFT JOIN theology_themes tt ON tti.theme_key = tt.theme_key
               WHERE vi.reference = ?{author_filter}
               GROUP BY tc.id
               ORDER BY vi.relevance DESC
               LIMIT ?""",
            exact_params,
        )
        if exact:
            return exact

        # Fall back to chapter-level
        where = f" AND {' AND '.join(conditions)}" if conditions else ""
        if author:
            where += " AND tc.source_author = ?"
            params.append(author)
        return await self._fetchall(
            f"""SELECT DISTINCT tc.*, vi.reference AS matched_ref, vi.relevance,
                       GROUP_CONCAT(DISTINCT tt.theme_key) AS themes
                FROM theology_content tc
                JOIN theology_verse_index vi ON tc.id = vi.content_id
                LEFT JOIN theology_theme_index tti ON tc.id = tti.content_id
                LEFT JOIN theology_themes tt ON tti.theme_key = tt.theme_key
                WHERE 1=1{where}
                GROUP BY tc.id
                ORDER BY vi.relevance DESC
                LIMIT ?""",
            (*params, limit),
        )

    async def get_theology_context_by_theme(
        self, theme_key: str, author: str | None = None, limit: int = 20
    ) -> list[dict]:
        """Get scholarship entries for a given theme, optionally filtered by author."""
        author_filter = ""
        params: list = [theme_key]
        if author:
            author_filter = " AND tc.source_author = ?"
            params.append(author)
        params.append(limit)
        return await self._fetchall(
            f"""SELECT DISTINCT tc.*, tt.theme_label, tt.description AS theme_description,
                      GROUP_CONCAT(DISTINCT vi.reference) AS verse_refs
               FROM theology_content tc
               JOIN theology_theme_index tti ON tc.id = tti.content_id
               JOIN theology_themes tt ON tti.theme_key = tt.theme_key
               LEFT JOIN theology_verse_index vi ON tc.id = vi.content_id
               WHERE tti.theme_key = ?{author_filter}
               GROUP BY tc.id
               ORDER BY tc.source_author, tc.id
               LIMIT ?""",
            params,
        )

    async def get_theology_themes(self, author: str | None = None) -> list[dict]:
        """List all theological themes, optionally filtered to those with entries by a specific author."""
        if author:
            return await self._fetchall(
                """SELECT tt.*,
                          (SELECT COUNT(*) FROM theology_theme_index tti
                           JOIN theology_content tc ON tti.content_id = tc.id
                           WHERE tti.theme_key = tt.theme_key AND tc.source_author = ?) AS entry_count
                   FROM theology_themes tt
                   WHERE EXISTS (
                       SELECT 1 FROM theology_theme_index tti
                       JOIN theology_content tc ON tti.content_id = tc.id
                       WHERE tti.theme_key = tt.theme_key AND tc.source_author = ?
                   )
                   ORDER BY tt.theme_key""",
                (author, author),
            )
        return await self._fetchall(
            """SELECT tt.*,
                      (SELECT COUNT(*) FROM theology_theme_index tti WHERE tti.theme_key = tt.theme_key) AS entry_count
               FROM theology_themes tt
               ORDER BY tt.theme_key"""
        )


    async def get_textual_variants(self, reference: str) -> list[dict]:
        """Get textual variants for a reference, with manuscript witnesses."""
        normalized = self._normalize_reference(reference)
        variants = await self._fetchall(
            "SELECT * FROM textual_variants WHERE reference = ?", (normalized,)
        )
        for v in variants:
            witnesses = await self._fetchall(
                "SELECT * FROM manuscript_witnesses WHERE variant_id = ?", (v["id"],)
            )
            v["witnesses"] = witnesses
        return variants

    async def get_hlt_verse(self, reference: str) -> dict | None:
        """Get the HLT translation for a single verse."""
        normalized = self._normalize_reference(reference)
        return await self._fetchone(
            "SELECT * FROM hlt_verses WHERE reference = ?", (normalized,)
        )

    async def get_hlt_annotations(self, reference: str) -> list[dict]:
        """Get HLT bracket annotations for a verse."""
        normalized = self._normalize_reference(reference)
        return await self._fetchall(
            "SELECT * FROM hlt_annotations WHERE reference = ? ORDER BY word_position",
            (normalized,),
        )

    async def get_hlt_study_notes(
        self, reference: str, note_type: str | None = None
    ) -> list[dict]:
        """Get HLT study notes for a verse, optionally filtered by type."""
        normalized = self._normalize_reference(reference)
        if note_type:
            return await self._fetchall(
                "SELECT * FROM hlt_study_notes WHERE reference = ? AND note_type = ? ORDER BY priority",
                (normalized, note_type),
            )
        return await self._fetchall(
            "SELECT * FROM hlt_study_notes WHERE reference = ? ORDER BY priority",
            (normalized,),
        )

    async def upsert_hlt_verse(self, data: dict) -> int:
        """Insert or update an HLT verse translation. Returns the row id."""
        sql = """INSERT INTO hlt_verses
                    (reference, book, chapter, verse, hlt_text, hlt_text_annotated,
                     base_text_source, variant_used, word_data_hlt, translation_notes,
                     confidence, status, last_updated)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                 ON CONFLICT(reference) DO UPDATE SET
                    hlt_text=excluded.hlt_text,
                    hlt_text_annotated=excluded.hlt_text_annotated,
                    base_text_source=excluded.base_text_source,
                    variant_used=excluded.variant_used,
                    word_data_hlt=excluded.word_data_hlt,
                    translation_notes=excluded.translation_notes,
                    confidence=excluded.confidence,
                    status=excluded.status,
                    last_updated=excluded.last_updated"""
        async with self.conn.execute(sql, (
            data["reference"], data["book"], data["chapter"], data["verse"],
            data["hlt_text"], data["hlt_text_annotated"],
            data.get("base_text_source", "MT"), data.get("variant_used"),
            data.get("word_data_hlt"), data.get("translation_notes"),
            data.get("confidence", "high"), data.get("status", "draft"),
        )) as cursor:
            await self.conn.commit()
            return cursor.lastrowid

    async def upsert_hlt_annotation(self, data: dict) -> int:
        """Insert or update an HLT bracket annotation."""
        sql = """INSERT INTO hlt_annotations
                    (reference, annotation_type, annotation_text, word_position,
                     explanation, heiser_content_id)
                 VALUES (?, ?, ?, ?, ?, ?)
                 ON CONFLICT(reference, annotation_type, word_position) DO UPDATE SET
                    annotation_text=excluded.annotation_text,
                    explanation=excluded.explanation,
                    heiser_content_id=excluded.heiser_content_id"""
        async with self.conn.execute(sql, (
            data["reference"], data["annotation_type"], data["annotation_text"],
            data.get("word_position"), data["explanation"],
            data.get("heiser_content_id"),
        )) as cursor:
            await self.conn.commit()
            return cursor.lastrowid

    async def upsert_hlt_study_note(self, data: dict) -> int:
        """Insert or update an HLT study note. Returns the row id."""
        sql = """INSERT INTO hlt_study_notes
                    (reference, book, chapter, verse, note_type, title, content,
                     heiser_content_ids, related_verses, priority)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                 ON CONFLICT(reference, note_type, title) DO UPDATE SET
                    content=excluded.content,
                    heiser_content_ids=excluded.heiser_content_ids,
                    related_verses=excluded.related_verses,
                    priority=excluded.priority"""
        async with self.conn.execute(sql, (
            data["reference"], data["book"], data["chapter"], data["verse"],
            data["note_type"], data["title"], data["content"],
            data.get("heiser_content_ids"), data.get("related_verses"),
            data.get("priority", 5),
        )) as cursor:
            await self.conn.commit()
            return cursor.lastrowid


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
            related_words TEXT,
            abbott_smith_def TEXT,
            nt_occurrences INTEGER,
            lxx_hebrew TEXT,
            synonyms TEXT,
            sense_hierarchy TEXT
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
            word_data TEXT,
            section_end TEXT  -- 'paragraph' (NT), 'petuchah' (OT major), 'setumah' (OT minor), or NULL
        );
        CREATE INDEX IF NOT EXISTS idx_verses_reference ON verses(reference);
        CREATE INDEX IF NOT EXISTS idx_verses_book ON verses(book);

        -- Passages table (verses grouped by section markers)
        CREATE TABLE IF NOT EXISTS passages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reference_start TEXT NOT NULL,    -- e.g., "Mat.1.1"
            reference_end TEXT NOT NULL,      -- e.g., "Mat.1.17"
            book TEXT NOT NULL,
            start_verse_id INTEGER NOT NULL,
            end_verse_id INTEGER NOT NULL,
            text_combined TEXT NOT NULL,      -- Full passage text for embedding
            verse_count INTEGER NOT NULL,
            section_type TEXT,                -- 'paragraph', 'petuchah', 'setumah'
            FOREIGN KEY (start_verse_id) REFERENCES verses(id),
            FOREIGN KEY (end_verse_id) REFERENCES verses(id)
        );
        CREATE INDEX IF NOT EXISTS idx_passages_book ON passages(book);
        CREATE INDEX IF NOT EXISTS idx_passages_refs ON passages(reference_start, reference_end);

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
        -- type: 'ch' (Harrison/Romhild curated), 'tsk' (Treasury of Scripture
        -- Knowledge via openbible.info), or NULL for legacy/manual entries.
        -- relevance: per-source ranking signal — CH uses 0..3 (Orig*2+Circ),
        -- TSK uses raw vote counts. Higher = stronger.
        CREATE TABLE IF NOT EXISTS cross_references (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            target TEXT NOT NULL,
            type TEXT,
            note TEXT,
            relevance INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_xref_source ON cross_references(source);
        CREATE INDEX IF NOT EXISTS idx_xref_source_rank
            ON cross_references(source, type, relevance DESC);

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

        -- =====================================================================
        -- Graph tables (Theographic Bible Metadata)
        -- =====================================================================

        -- People nodes
        CREATE TABLE IF NOT EXISTS graph_people (
            id TEXT PRIMARY KEY,          -- e.g., "aaron_1"
            name TEXT NOT NULL,
            also_called TEXT,
            gender TEXT,
            birth_year INTEGER,
            death_year INTEGER,
            birth_place_id TEXT,
            death_place_id TEXT,
            description TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_graph_people_name ON graph_people(name);

        -- Place nodes
        CREATE TABLE IF NOT EXISTS graph_places (
            id TEXT PRIMARY KEY,          -- e.g., "eden_354"
            name TEXT NOT NULL,
            latitude REAL,
            longitude REAL,
            feature_type TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_graph_places_name ON graph_places(name);

        -- Event nodes
        CREATE TABLE IF NOT EXISTS graph_events (
            id TEXT PRIMARY KEY,          -- event_id as text
            title TEXT NOT NULL,
            start_year INTEGER,
            duration TEXT,
            sort_key REAL
        );
        CREATE INDEX IF NOT EXISTS idx_graph_events_title ON graph_events(title);

        -- People group nodes
        CREATE TABLE IF NOT EXISTS graph_people_groups (
            name TEXT PRIMARY KEY,
            members TEXT                  -- JSON array of person IDs
        );

        -- Family relationship edges
        CREATE TABLE IF NOT EXISTS graph_family_edges (
            from_person_id TEXT NOT NULL,
            to_person_id TEXT NOT NULL,
            relationship_type TEXT NOT NULL,  -- father_of, mother_of, partner_of, sibling_of
            PRIMARY KEY (from_person_id, to_person_id, relationship_type)
        );
        CREATE INDEX IF NOT EXISTS idx_graph_family_from ON graph_family_edges(from_person_id);
        CREATE INDEX IF NOT EXISTS idx_graph_family_to ON graph_family_edges(to_person_id);

        -- Person-event participation edges
        CREATE TABLE IF NOT EXISTS graph_person_event_edges (
            person_id TEXT NOT NULL,
            event_id TEXT NOT NULL,
            PRIMARY KEY (person_id, event_id)
        );
        CREATE INDEX IF NOT EXISTS idx_graph_pe_person ON graph_person_event_edges(person_id);
        CREATE INDEX IF NOT EXISTS idx_graph_pe_event ON graph_person_event_edges(event_id);

        -- Event-place edges
        CREATE TABLE IF NOT EXISTS graph_event_place_edges (
            event_id TEXT NOT NULL,
            place_id TEXT NOT NULL,
            PRIMARY KEY (event_id, place_id)
        );
        CREATE INDEX IF NOT EXISTS idx_graph_ep_event ON graph_event_place_edges(event_id);
        CREATE INDEX IF NOT EXISTS idx_graph_ep_place ON graph_event_place_edges(place_id);

        -- Verse-entity mention links
        CREATE TABLE IF NOT EXISTS graph_verse_mentions (
            verse_ref TEXT NOT NULL,       -- e.g., "Gen.1.1" (matches verses.reference)
            entity_type TEXT NOT NULL,     -- person, place, event
            entity_id TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_graph_vm_ref ON graph_verse_mentions(verse_ref);
        CREATE INDEX IF NOT EXISTS idx_graph_vm_entity ON graph_verse_mentions(entity_type, entity_id);

        -- Person-group membership edges
        CREATE TABLE IF NOT EXISTS graph_person_group_edges (
            person_id TEXT NOT NULL,
            group_name TEXT NOT NULL,
            PRIMARY KEY (person_id, group_name)
        );
        CREATE INDEX IF NOT EXISTS idx_graph_pg_person ON graph_person_group_edges(person_id);
        CREATE INDEX IF NOT EXISTS idx_graph_pg_group ON graph_person_group_edges(group_name);

        -- =====================================================================
        -- Aquifer content (study notes, dictionary, translation notes, key terms)
        -- =====================================================================

        CREATE TABLE IF NOT EXISTS aquifer_content (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content_id INTEGER NOT NULL,
            resource_type TEXT NOT NULL,
            title TEXT NOT NULL,
            book TEXT,
            book_num INTEGER,
            start_ref TEXT,
            end_ref TEXT,
            chapter_start INTEGER,
            verse_start INTEGER,
            chapter_end INTEGER,
            verse_end INTEGER,
            content TEXT NOT NULL,
            content_plain TEXT NOT NULL,
            is_range INTEGER DEFAULT 0,
            UNIQUE(content_id, resource_type)
        );
        CREATE INDEX IF NOT EXISTS idx_aq_type ON aquifer_content(resource_type);
        CREATE INDEX IF NOT EXISTS idx_aq_ref ON aquifer_content(resource_type, start_ref);
        CREATE INDEX IF NOT EXISTS idx_aq_book ON aquifer_content(resource_type, book, chapter_start);
        CREATE INDEX IF NOT EXISTS idx_aq_title ON aquifer_content(resource_type, title);

        -- =====================================================================
        -- ACAI entity annotations
        -- =====================================================================

        CREATE TABLE IF NOT EXISTS acai_entities (
            id TEXT PRIMARY KEY,
            entity_type TEXT NOT NULL,
            name TEXT NOT NULL,
            gender TEXT,
            description TEXT,
            roles TEXT,
            father_id TEXT,
            mother_id TEXT,
            partners TEXT,
            offspring TEXT,
            siblings TEXT,
            referred_to_as TEXT,
            key_references TEXT,
            reference_count INTEGER,
            speeches_count INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_acai_type ON acai_entities(entity_type);
        CREATE INDEX IF NOT EXISTS idx_acai_name ON acai_entities(name);

        -- =====================================================================
        -- ANE (Ancient Near East) context entries
        -- =====================================================================

        CREATE TABLE IF NOT EXISTS ane_entries (
            id TEXT PRIMARY KEY,
            dimension TEXT NOT NULL,
            dimension_label TEXT NOT NULL,
            title TEXT NOT NULL,
            summary TEXT NOT NULL,
            detail TEXT,
            ane_parallels TEXT,
            interpretive_significance TEXT,
            period TEXT,
            period_label TEXT,
            key_references TEXT,
            scholarly_sources TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_ane_dimension ON ane_entries(dimension);
        CREATE INDEX IF NOT EXISTS idx_ane_period ON ane_entries(period);

        CREATE TABLE IF NOT EXISTS ane_book_mappings (
            entry_id TEXT NOT NULL,
            book TEXT NOT NULL,
            chapter_start INTEGER,
            chapter_end INTEGER,
            PRIMARY KEY (entry_id, book, chapter_start),
            FOREIGN KEY (entry_id) REFERENCES ane_entries(id)
        );
        CREATE INDEX IF NOT EXISTS idx_ane_bm_book ON ane_book_mappings(book);
        CREATE INDEX IF NOT EXISTS idx_ane_bm_entry ON ane_book_mappings(entry_id);

        -- =====================================================================
        -- Torah Weave (Moshe Kline) — 86 literary units of the Torah as
        -- two-dimensional compositions. Each unit has cells arranged in rows
        -- and columns; horizontal and vertical cell pairings encode parallel
        -- correspondences and thematic progressions.
        -- =====================================================================

        CREATE TABLE IF NOT EXISTS torah_weave_units (
            id INTEGER PRIMARY KEY,           -- serial_number (1-86)
            book TEXT NOT NULL,               -- "Gen", "Exo", "Lev", "Num", "Deu"
            book_full TEXT NOT NULL,          -- "Genesis", ...
            unit_number INTEGER NOT NULL,
            title TEXT NOT NULL,
            verses TEXT NOT NULL,             -- e.g. "Genesis 1:1-2:3"
            verse_range TEXT NOT NULL,        -- e.g. "1:1-2:3"
            format TEXT NOT NULL,             -- "3x2" (regular) or digit string (irregular)
            irregular INTEGER NOT NULL,       -- 0/1
            is_unique INTEGER NOT NULL,       -- 0/1
            cell_count INTEGER NOT NULL,
            type TEXT,                        -- "F" framework, "CL" closure, "U" unique, or NULL
            cell_count_with_subdivisions INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_tw_units_book ON torah_weave_units(book);

        CREATE TABLE IF NOT EXISTS torah_weave_cells (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            unit_id INTEGER NOT NULL REFERENCES torah_weave_units(id),
            cell_label TEXT NOT NULL,         -- "1A", "2Ba", etc.
            row_num INTEGER NOT NULL,
            column_letter TEXT NOT NULL,      -- "A", "B", ...
            subdivision TEXT,                 -- "a", "b", or NULL
            book TEXT NOT NULL,               -- denormalized for lookup
            verse_range TEXT NOT NULL,        -- original string, e.g. "6:1-6:4"
            chapter_start INTEGER NOT NULL,
            verse_start INTEGER NOT NULL,
            chapter_end INTEGER NOT NULL,
            verse_end INTEGER NOT NULL,
            sort_start INTEGER NOT NULL,      -- chapter*1000 + verse (inclusive)
            sort_end INTEGER NOT NULL,        -- chapter*1000 + verse (inclusive)
            UNIQUE(unit_id, cell_label)
        );
        CREATE INDEX IF NOT EXISTS idx_tw_cells_unit ON torah_weave_cells(unit_id);
        CREATE INDEX IF NOT EXISTS idx_tw_cells_lookup ON torah_weave_cells(book, sort_start, sort_end);
    """)
    conn.commit()

    # --- Theological scholarship tables (unified: Heiser, Bradley, etc.) ---
    conn.executescript("""
        -- Scholarship content (multi-author)
        CREATE TABLE IF NOT EXISTS theology_content (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_work TEXT NOT NULL,
            source_author TEXT NOT NULL,
            source_type TEXT NOT NULL,
            chapter_or_episode TEXT,
            title TEXT,
            content_summary TEXT NOT NULL,
            content_detail TEXT,
            page_range TEXT,
            url TEXT,
            UNIQUE(source_work, chapter_or_episode, title)
        );
        CREATE INDEX IF NOT EXISTS idx_theology_source ON theology_content(source_work);
        CREATE INDEX IF NOT EXISTS idx_theology_author ON theology_content(source_author);

        -- Maps theology_content entries to specific verses
        CREATE TABLE IF NOT EXISTS theology_verse_index (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content_id INTEGER NOT NULL REFERENCES theology_content(id),
            reference TEXT NOT NULL,
            book TEXT NOT NULL,
            chapter INTEGER,
            verse INTEGER,
            relevance TEXT DEFAULT 'primary',
            UNIQUE(content_id, reference)
        );
        CREATE INDEX IF NOT EXISTS idx_theology_vi_ref ON theology_verse_index(reference);
        CREATE INDEX IF NOT EXISTS idx_theology_vi_book ON theology_verse_index(book);

        -- Shared theological themes taxonomy
        CREATE TABLE IF NOT EXISTS theology_themes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            theme_key TEXT UNIQUE NOT NULL,
            theme_label TEXT NOT NULL,
            description TEXT NOT NULL,
            parent_theme TEXT,
            key_works TEXT
        );

        -- Maps themes to content and verses
        CREATE TABLE IF NOT EXISTS theology_theme_index (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            theme_key TEXT NOT NULL REFERENCES theology_themes(theme_key),
            content_id INTEGER REFERENCES theology_content(id),
            reference TEXT,
            UNIQUE(theme_key, content_id, reference)
        );
        CREATE INDEX IF NOT EXISTS idx_theology_ti_theme ON theology_theme_index(theme_key);

        -- Legacy aliases (views) so old heiser_content_id FKs still resolve
        CREATE VIEW IF NOT EXISTS heiser_content AS SELECT * FROM theology_content;
        CREATE VIEW IF NOT EXISTS heiser_verse_index AS SELECT * FROM theology_verse_index;
        CREATE VIEW IF NOT EXISTS heiser_themes AS SELECT * FROM theology_themes;
        CREATE VIEW IF NOT EXISTS heiser_theme_index AS SELECT * FROM theology_theme_index;

        -- Textual variants (MT vs DSS/LXX/SP)
        CREATE TABLE IF NOT EXISTS textual_variants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reference TEXT NOT NULL,
            book TEXT NOT NULL,
            chapter INTEGER,
            verse INTEGER,
            mt_reading TEXT NOT NULL,
            mt_hebrew TEXT,
            variant_source TEXT NOT NULL,
            variant_reading TEXT NOT NULL,
            variant_original TEXT,
            variant_significance TEXT,
            heiser_analysis TEXT,
            heiser_content_id INTEGER,
            scholarly_consensus TEXT,
            preferred_for_hlt TEXT,
            hlt_rationale TEXT,
            UNIQUE(reference, variant_source)
        );
        CREATE INDEX IF NOT EXISTS idx_tv_ref ON textual_variants(reference);
        CREATE INDEX IF NOT EXISTS idx_tv_book ON textual_variants(book);

        -- Manuscript witnesses for variants
        CREATE TABLE IF NOT EXISTS manuscript_witnesses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            variant_id INTEGER NOT NULL REFERENCES textual_variants(id),
            manuscript TEXT NOT NULL,
            manuscript_date TEXT,
            reading_support TEXT
        );

        -- The HLT translation
        CREATE TABLE IF NOT EXISTS hlt_verses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reference TEXT UNIQUE NOT NULL,
            book TEXT NOT NULL,
            chapter INTEGER,
            verse INTEGER,
            hlt_text TEXT NOT NULL,
            hlt_text_annotated TEXT NOT NULL,
            base_text_source TEXT DEFAULT 'MT',
            variant_used INTEGER,
            word_data_hlt TEXT,
            translation_notes TEXT,
            confidence TEXT DEFAULT 'high',
            status TEXT DEFAULT 'draft',
            last_updated TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_hlt_ref ON hlt_verses(reference);
        CREATE INDEX IF NOT EXISTS idx_hlt_book ON hlt_verses(book);

        -- HLT bracket annotations
        CREATE TABLE IF NOT EXISTS hlt_annotations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reference TEXT NOT NULL,
            annotation_type TEXT NOT NULL,
            annotation_text TEXT NOT NULL,
            word_position INTEGER,
            explanation TEXT NOT NULL,
            heiser_content_id INTEGER,
            UNIQUE(reference, annotation_type, word_position)
        );
        CREATE INDEX IF NOT EXISTS idx_hlt_ann_ref ON hlt_annotations(reference);

        -- HLT study notes
        CREATE TABLE IF NOT EXISTS hlt_study_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reference TEXT NOT NULL,
            book TEXT NOT NULL,
            chapter INTEGER,
            verse INTEGER,
            note_type TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            heiser_content_ids TEXT,
            related_verses TEXT,
            priority INTEGER DEFAULT 5,
            UNIQUE(reference, note_type, title)
        );
        CREATE INDEX IF NOT EXISTS idx_hlt_sn_ref ON hlt_study_notes(reference);
        CREATE INDEX IF NOT EXISTS idx_hlt_sn_book ON hlt_study_notes(book);
        CREATE INDEX IF NOT EXISTS idx_hlt_sn_type ON hlt_study_notes(note_type);
    """)
    conn.commit()

    # Add Abbott-Smith columns to existing databases (idempotent)
    for col in [
        "abbott_smith_def TEXT",
        "nt_occurrences INTEGER",
        "lxx_hebrew TEXT",
        "synonyms TEXT",
        "sense_hierarchy TEXT",
    ]:
        try:
            conn.execute(f"ALTER TABLE lexicon ADD COLUMN {col}")
        except sqlite3.OperationalError:
            pass  # Column already exists
    conn.commit()


def create_vector_tables(conn: sqlite3.Connection):
    """Create vector tables for semantic search using sqlite-vec.

    This should be called after loading the sqlite-vec extension.
    """
    conn.executescript("""
        -- Vector table for passage embeddings (1536 dimensions for OpenAI)
        CREATE VIRTUAL TABLE IF NOT EXISTS passage_vectors USING vec0(
            passage_id INTEGER PRIMARY KEY,
            embedding FLOAT[1536]
        );

        -- Vector table for verse embeddings
        CREATE VIRTUAL TABLE IF NOT EXISTS verse_vectors USING vec0(
            verse_id INTEGER PRIMARY KEY,
            embedding FLOAT[1536]
        );
    """)
    conn.commit()
