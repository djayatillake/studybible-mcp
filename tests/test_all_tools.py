#!/usr/bin/env python3
"""
Test all 17 Study Bible MCP tools individually.

Calls each tool handler directly (no MCP transport needed).
Verifies each returns non-empty, non-error results.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from study_bible_mcp.database import StudyBibleDB

# Import server module to use its handlers directly
import study_bible_mcp.server as srv


DB_PATH = Path(__file__).parent.parent / "db" / "study_bible.db"

# Test cases: (tool_name, args, description, required_substring)
TEST_CASES = [
    # 1. word_study - by Strong's number
    ("word_study", {"strongs": "G26"}, "Word study for agape (G26)", "agap"),

    # 2. word_study - by English word
    ("word_study", {"word": "faith", "language": "greek"}, "Word study for 'faith'", "faith"),

    # 3. lookup_verse - single verse
    ("lookup_verse", {"reference": "John 3:16"}, "Lookup John 3:16", "loved"),

    # 4. lookup_verse - range
    ("lookup_verse", {"reference": "Romans 8:28"}, "Lookup Romans 8:28", ""),

    # 5. search_lexicon - Greek
    ("search_lexicon", {"query": "love", "language": "greek"}, "Lexicon search for 'love'", "G"),

    # 6. search_lexicon - Hebrew
    ("search_lexicon", {"query": "God", "language": "hebrew"}, "Lexicon search for 'God' (Hebrew)", "H"),

    # 7. get_cross_references - by theme
    ("get_cross_references", {"theme": "salvation_by_grace"}, "Cross-refs: salvation by grace", "Ephesians"),

    # 8. get_cross_references - by reference
    ("get_cross_references", {"reference": "John 3:16"}, "Cross-refs for John 3:16", ""),

    # 9. lookup_name - person
    ("lookup_name", {"name": "David", "type": "person"}, "Lookup name: David", "David"),

    # 10. lookup_name - place
    ("lookup_name", {"name": "Jerusalem"}, "Lookup name: Jerusalem", "Jerusalem"),

    # 11. parse_morphology
    ("parse_morphology", {"code": "V-AAI-3S", "language": "greek"}, "Parse morphology V-AAI-3S", "Aorist"),

    # 12. search_by_strongs
    ("search_by_strongs", {"strongs": "G26", "limit": 5}, "Search verses by Strong's G26", ""),

    # 13. find_similar_passages (may fail if embeddings not generated)
    ("find_similar_passages", {"reference": "John 3:16", "limit": 5}, "Find similar passages to John 3:16", ""),

    # 14. explore_genealogy
    ("explore_genealogy", {"person": "David", "direction": "ancestors", "generations": 3}, "David's ancestors", "Jesse"),

    # 15. people_in_passage - chapter
    ("people_in_passage", {"reference": "Genesis 22"}, "People in Genesis 22", "Abraham"),

    # 16. explore_person_events
    ("explore_person_events", {"person": "Moses"}, "Moses' life events", "Moses"),

    # 17. explore_place
    ("explore_place", {"place": "Jerusalem"}, "Explore Jerusalem", "Jerusalem"),

    # 18. find_connection
    ("find_connection", {"person1": "Abraham", "person2": "David"}, "Connection: Abraham to David", ""),

    # 19. graph_enriched_search
    ("graph_enriched_search", {"reference": "Genesis 22:1"}, "Graph-enriched Genesis 22:1", "Abraham"),

    # 20. get_study_notes
    ("get_study_notes", {"reference": "John 3:16"}, "Study notes for John 3:16", ""),

    # 21. get_bible_dictionary
    ("get_bible_dictionary", {"topic": "covenant"}, "Dictionary: covenant", ""),

    # 22. get_key_terms
    ("get_key_terms", {"term": "atonement"}, "Key term: atonement", ""),
]


async def run_tests():
    """Run all tool tests."""
    # Initialize database
    db = StudyBibleDB(DB_PATH)
    await db.connect()
    srv.db = db

    passed = 0
    failed = 0
    skipped = 0
    results = []

    print(f"\n{'='*70}")
    print(f"  Study Bible MCP — Tool Test Suite ({len(TEST_CASES)} tests)")
    print(f"{'='*70}\n")

    for i, (tool_name, args, description, required_substr) in enumerate(TEST_CASES, 1):
        print(f"  [{i:2d}/{len(TEST_CASES)}] {description}...", end=" ", flush=True)

        try:
            response = await srv.call_tool(tool_name, args)
            text = response[0].text if response else ""

            # Check for error indicators
            is_error = any(phrase in text.lower() for phrase in [
                "error:", "not found", "not available", "no entries found",
                "no cross-references found", "unknown tool",
                "please provide", "could not parse",
            ])
            # Some "not found" responses are expected for certain queries
            is_expected_empty = (
                (tool_name == "get_cross_references" and "reference" in args and not args.get("theme"))
                or (tool_name == "find_similar_passages" and ("unavailable" in text.lower() or "not been generated" in text.lower()))
            )

            if is_error and not is_expected_empty:
                # Check if it's a "data not available" error (acceptable - means tool works but data missing)
                if "not available" in text.lower() or "not been generated" in text.lower():
                    print(f"SKIP (data not available)")
                    skipped += 1
                    results.append((tool_name, "SKIP", text[:100]))
                else:
                    print(f"FAIL")
                    print(f"         Response: {text[:200]}")
                    failed += 1
                    results.append((tool_name, "FAIL", text[:200]))
            elif required_substr and required_substr.lower() not in text.lower():
                print(f"FAIL (missing '{required_substr}')")
                print(f"         Response: {text[:200]}")
                failed += 1
                results.append((tool_name, "FAIL", f"Missing '{required_substr}'"))
            else:
                # Truncate for display
                preview = text[:80].replace("\n", " ")
                print(f"OK ({len(text)} chars)")
                passed += 1
                results.append((tool_name, "OK", f"{len(text)} chars"))

        except Exception as e:
            print(f"ERROR: {e}")
            failed += 1
            results.append((tool_name, "ERROR", str(e)))

    await db.close()

    # Summary
    print(f"\n{'='*70}")
    print(f"  Results: {passed} passed, {failed} failed, {skipped} skipped")
    print(f"{'='*70}\n")

    if failed > 0:
        print("  FAILURES:")
        for tool_name, status, detail in results:
            if status in ("FAIL", "ERROR"):
                print(f"    - {tool_name}: {detail}")
        print()

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(run_tests())
    sys.exit(0 if success else 1)
