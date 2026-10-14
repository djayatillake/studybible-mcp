"""
Tests for key-reference promotion and zero-overlap filtering of broad ANE entries.

Tests _parse_key_ref_books_chapters() and _refine_broad_entries() in server.py.
"""

import json

from study_bible_mcp.server import _parse_key_ref_books_chapters, _refine_broad_entries

# ---------------------------------------------------------------------------
# _parse_key_ref_books_chapters
# ---------------------------------------------------------------------------

class TestParseKeyRefBooksChapters:
    def test_simple_reference(self):
        refs = json.dumps(["Gen 38:24"])
        result = _parse_key_ref_books_chapters(refs)
        assert ("Gen", 38) in result

    def test_multiple_references(self):
        refs = json.dumps(["Gen 38:6-26", "Gen 1:1-2:3", "Deut 25:5-10"])
        result = _parse_key_ref_books_chapters(refs)
        assert ("Gen", 38) in result
        assert ("Gen", 1) in result
        assert ("Deu", 25) in result

    def test_numbered_book(self):
        refs = json.dumps(["1 Cor 12:12-27"])
        result = _parse_key_ref_books_chapters(refs)
        assert ("1Co", 12) in result

    def test_psalm(self):
        refs = json.dumps(["Psalm 104:2-3"])
        result = _parse_key_ref_books_chapters(refs)
        assert ("Psa", 104) in result

    def test_empty_list(self):
        assert _parse_key_ref_books_chapters("[]") == set()

    def test_list_input(self):
        result = _parse_key_ref_books_chapters(["Gen 1:1"])
        assert ("Gen", 1) in result

    def test_unparseable_reference_skipped(self):
        refs = json.dumps(["something weird", "Gen 3:15"])
        result = _parse_key_ref_books_chapters(refs)
        assert len(result) == 1
        assert ("Gen", 3) in result

    def test_full_book_name(self):
        refs = json.dumps(["Genesis 12:1-3"])
        result = _parse_key_ref_books_chapters(refs)
        assert ("Gen", 12) in result

    def test_isaiah(self):
        refs = json.dumps(["Isaiah 40:1-2", "Isa 53:4-6"])
        result = _parse_key_ref_books_chapters(refs)
        assert ("Isa", 40) in result
        assert ("Isa", 53) in result


# ---------------------------------------------------------------------------
# _refine_broad_entries
# ---------------------------------------------------------------------------

def _make_entry(entry_id: str, match_type: str, key_refs: list[str], relevance_score: int = 1000) -> dict:
    """Helper to create a mock ANE entry dict."""
    return {
        "id": entry_id,
        "match_type": match_type,
        "key_references": json.dumps(key_refs),
        "relevance_score": relevance_score,
    }


class TestRefineBroadEntries:
    def test_direct_entries_pass_through(self):
        """Direct entries are never filtered or modified."""
        entry = _make_entry("gender_003", "direct", ["Gen 38:6-26"], relevance_score=10)
        result = _refine_broad_entries([entry], "Gen", 38)
        assert len(result) == 1
        assert result[0]["match_type"] == "direct"
        assert result[0]["relevance_score"] == 10  # unchanged

    def test_promote_broad_with_matching_chapter(self):
        """Broad entry citing the queried book+chapter gets promoted to direct."""
        entry = _make_entry("gender_002", "broad", ["Gen 38:24", "Deut 22:13-21"])
        result = _refine_broad_entries([entry], "Gen", 38)
        assert len(result) == 1
        assert result[0]["match_type"] == "direct"
        assert result[0]["relevance_score"] == 500

    def test_filter_zero_overlap(self):
        """Broad entry with no references to the queried book gets dropped."""
        entry = _make_entry("cosmo_013", "broad", ["Ezek 37:5-6", "Psalm 104:29-30"])
        result = _refine_broad_entries([entry], "Gen", 38)
        assert len(result) == 0

    def test_keep_broad_same_book_different_chapter(self):
        """Broad entry citing the same book but different chapter stays as broad."""
        entry = _make_entry("legal_004", "broad", ["Gen 23:3-20", "Deut 19:14"])
        result = _refine_broad_entries([entry], "Gen", 38)
        assert len(result) == 1
        assert result[0]["match_type"] == "broad"

    def test_no_key_references_kept(self):
        """Broad entry with no parseable key_references is kept (conservative)."""
        entry = _make_entry("misc_001", "broad", [])
        result = _refine_broad_entries([entry], "Gen", 38)
        assert len(result) == 1
        assert result[0]["match_type"] == "broad"

    def test_mixed_entries(self):
        """Full scenario: direct pass-through, promote, filter, keep broad."""
        entries = [
            _make_entry("direct_one", "direct", ["Gen 38:1-30"], relevance_score=10),
            _make_entry("promote_me", "broad", ["Gen 38:24"]),
            _make_entry("drop_me", "broad", ["Ezek 37:5-6"]),
            _make_entry("keep_broad", "broad", ["Gen 23:3-20"]),
        ]
        result = _refine_broad_entries(entries, "Gen", 38)
        ids = [e["id"] for e in result]
        assert ids == ["direct_one", "promote_me", "keep_broad"]
        # Check promotion
        promoted = result[1]
        assert promoted["match_type"] == "direct"
        assert promoted["relevance_score"] == 500
        # Check direct unchanged
        assert result[0]["relevance_score"] == 10
        # Check broad kept
        assert result[2]["match_type"] == "broad"

    def test_does_not_mutate_original(self):
        """Promotion creates a copy, doesn't mutate the original dict."""
        entry = _make_entry("gender_002", "broad", ["Gen 38:24"])
        original_match_type = entry["match_type"]
        _refine_broad_entries([entry], "Gen", 38)
        assert entry["match_type"] == original_match_type

    def test_no_chapter_provided(self):
        """When chapter is None, no promotion happens but zero-overlap still filters."""
        entries = [
            _make_entry("has_gen", "broad", ["Gen 23:3-20"]),
            _make_entry("no_gen", "broad", ["Ezek 37:5-6"]),
        ]
        result = _refine_broad_entries(entries, "Gen", None)
        assert len(result) == 1
        assert result[0]["id"] == "has_gen"
        assert result[0]["match_type"] == "broad"  # no promotion without chapter
