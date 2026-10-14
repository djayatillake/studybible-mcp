#!/usr/bin/env python3
"""Import theological scholarship content, themes, and textual variants into the study_bible database.

Re-runnable: rows already present (same source_work, chapter_or_episode, title) are
not duplicated; only their url is refreshed from the data files.

Usage: python scripts/import_heiser_content.py [db_path]
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from study_bible_mcp.database import (
    INTERPRETIVE_CASE_KEYS,
    link_theology_theme,
    upsert_theology_content,
)
from study_bible_mcp.parsers.heiser import parse_heiser_content_file, parse_themes_file


def get_db_path() -> Path:
    """Get the database path: the first CLI argument, else db/study_bible.db."""
    if len(sys.argv) > 1:
        return Path(sys.argv[1])
    return Path(__file__).resolve().parent.parent / "db" / "study_bible.db"


def import_themes(conn: sqlite3.Connection, themes_path: Path) -> int:
    """Import theological themes from themes.json."""
    themes = parse_themes_file(themes_path)
    count = 0
    for theme in themes:
        try:
            conn.execute(
                """INSERT OR REPLACE INTO theology_themes
                   (theme_key, theme_label, description, parent_theme, key_works)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    theme["theme_key"],
                    theme["theme_label"],
                    theme["description"],
                    theme["parent_theme"],
                    theme.get("heiser_key_works") or theme.get("key_works"),
                ),
            )
            count += 1
        except sqlite3.Error as e:
            print(f"  Warning: Failed to insert theme {theme['theme_key']}: {e}")
    conn.commit()
    return count


def import_content_file(conn: sqlite3.Connection, filepath: Path) -> tuple[int, int, int, int]:
    """Import a single Heiser content JSON file.

    Existing rows keep their content but have their url refreshed.

    Returns (entries_imported, urls_updated, verse_refs_imported, theme_links_imported).
    """
    entries = 0
    urls_updated = 0
    refs = 0
    themes = 0

    for content_entry, verse_refs, theme_keys in parse_heiser_content_file(filepath):
        try:
            content_id, status = upsert_theology_content(conn, content_entry)
            if status == "inserted":
                entries += 1
            elif status == "url_updated":
                urls_updated += 1

            # Insert verse references
            for vref in verse_refs:
                try:
                    conn.execute(
                        """INSERT OR IGNORE INTO theology_verse_index
                           (content_id, reference, book, chapter, verse, relevance)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (content_id, vref["reference"], vref["book"],
                         vref["chapter"], vref["verse"], vref["relevance"]),
                    )
                    refs += 1
                except sqlite3.Error:
                    pass

            # Insert theme links
            for theme_key in theme_keys:
                try:
                    link_theology_theme(conn, theme_key, content_id)
                    themes += 1
                except sqlite3.Error:
                    pass

        except sqlite3.Error as e:
            print(f"  Warning: Failed to insert entry '{content_entry.get('title', '?')}': {e}")

    conn.commit()
    return entries, urls_updated, refs, themes


# Explicit mapping from the dataset's raw ``reading_support`` label to
# (reading the evidence bears on, evidence type). ``None`` means the evidence
# belongs to the case as a whole rather than to one reading.
#
# - supports_long_form / omits / supports_short_form_pattern only occur in
#   omission cases, where the MT carries the long form and the variant is the
#   omission (enforced in ``_classify_witness``).
# - supports_short_form_pattern marks a scroll that attests the short text form
#   elsewhere in the book: indirect evidence, not a witness to this verse.
# - not_preserved records that a corpus has no copy of the verse at all.
READING_SUPPORT_MAP: dict[str, tuple[str | None, str]] = {
    "supports_mt": ("mt", "manuscript"),
    "supports_variant": ("variant", "manuscript"),
    "supports_long_form": ("mt", "manuscript"),
    "omits": ("variant", "manuscript"),
    "supports_short_form_pattern": ("variant", "indirect"),
    "not_preserved": (None, "not_preserved"),
}
_FORM_SUPPORT_LABELS = frozenset(
    {"supports_long_form", "omits", "supports_short_form_pattern"}
)

# A witness labelled with an NT passage ("Hebrews 10:5-7", "Luke 4:18 (Jesus)")
# is citation evidence: it shows how the verse was quoted, not a copy of it.
NT_BOOK_NAMES = frozenset({
    "matthew", "mark", "luke", "john", "acts", "romans",
    "1 corinthians", "2 corinthians", "galatians", "ephesians", "philippians",
    "colossians", "1 thessalonians", "2 thessalonians", "1 timothy",
    "2 timothy", "titus", "philemon", "hebrews", "james", "1 peter",
    "2 peter", "1 john", "2 john", "3 john", "jude", "revelation",
})
_CITATION_PATTERN = re.compile(r"^((?:[123] )?[A-Za-z]+) \d+:\d+")


def _is_nt_citation(witness: str) -> bool:
    match = _CITATION_PATTERN.match(witness.strip())
    return bool(match) and match.group(1).lower() in NT_BOOK_NAMES


def _classify_witness(case_key: str, witness: dict) -> tuple[str | None, str]:
    """Return (reading_key, evidence_type) for one dataset witness entry."""
    support = witness.get("reading_support")
    if support not in READING_SUPPORT_MAP:
        raise ValueError(
            f"Unknown reading_support {support!r} for witness "
            f"{witness.get('manuscript')!r}; add it to READING_SUPPORT_MAP"
        )
    if support in _FORM_SUPPORT_LABELS and not case_key.endswith("_omission"):
        raise ValueError(
            f"reading_support {support!r} is only defined for omission cases, "
            f"not {case_key!r}"
        )
    if not witness.get("manuscript"):
        raise ValueError("Witness entry has no manuscript name")
    reading_key, evidence_type = READING_SUPPORT_MAP[support]
    if evidence_type == "manuscript" and _is_nt_citation(witness["manuscript"]):
        evidence_type = "citation"
    return reading_key, evidence_type


def _parse_variant_reference(reference: str) -> tuple[str, int, int]:
    parts = reference.split(".")
    if len(parts) != 3 or not parts[0]:
        raise ValueError(f"Variant reference {reference!r} is not Book.Chapter.Verse")
    return parts[0], int(parts[1]), int(parts[2])


def import_textual_variant_record(
    conn: sqlite3.Connection,
    variant: dict,
) -> int:
    """Replace one textual-variant case and return its case ID.

    Records labelled ``MT_preserved`` or ``translation_choice`` are not
    manuscript variants: the MT and the versions agree, and the record argues
    for a reading or rendering. They are stored as interpretive cases with the
    MT as their only reading, the witnesses attached to it, and the record's
    prose kept as attributed interpretation rather than as a variant reading.

    The record is validated completely before any row is touched, and the
    replacement runs inside a SAVEPOINT, so a malformed record raises and
    leaves the previously imported rows for the case intact.
    """
    case_key = variant["variant_source"]
    interpretive = case_key in INTERPRETIVE_CASE_KEYS

    reference = variant["reference"]
    book, chapter, verse = _parse_variant_reference(reference)
    readings = (
        ("mt", "Masoretic Text", variant["mt_reading"], variant.get("mt_hebrew")),
    )
    if not interpretive:
        readings += (
            (
                "variant",
                case_key,
                variant["variant_reading"],
                variant.get("variant_original"),
            ),
        )
    for reading_key, _, reading_text, _ in readings:
        if not reading_text:
            raise ValueError(f"{reference} {case_key}: empty {reading_key} reading")
    witnesses = []
    for witness in variant.get("witnesses", []):
        reading_key, evidence_type = _classify_witness(case_key, witness)
        if interpretive and reading_key is not None:
            # No competing reading exists, so every witness attests the MT text.
            reading_key = "mt"
        witnesses.append((witness, reading_key, evidence_type))

    conn.execute("SAVEPOINT textual_variant_record")
    try:
        case_id = _write_textual_variant_record(
            conn, variant, (reference, book, chapter, verse, case_key), readings, witnesses
        )
    except BaseException:
        conn.execute("ROLLBACK TO textual_variant_record")
        conn.execute("RELEASE textual_variant_record")
        raise
    conn.execute("RELEASE textual_variant_record")
    return case_id


def _write_textual_variant_record(
    conn: sqlite3.Connection,
    variant: dict,
    case_row: tuple[str, str, int, int, str],
    readings: tuple,
    witnesses: list[tuple[dict, str | None, str]],
) -> int:
    reference, _, _, _, case_key = case_row
    interpretive = case_key in INTERPRETIVE_CASE_KEYS
    conn.execute(
        """INSERT INTO textual_variant_cases
           (reference, book, chapter, verse, case_key, significance)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(reference, case_key) DO UPDATE SET
               book = excluded.book,
               chapter = excluded.chapter,
               verse = excluded.verse,
               significance = excluded.significance""",
        (*case_row, variant.get("variant_significance")),
    )
    case_id = conn.execute(
        """SELECT id FROM textual_variant_cases
           WHERE reference = ? AND case_key = ?""",
        (reference, case_key),
    ).fetchone()[0]

    for table in (
        "textual_variant_witnesses",
        "textual_variant_readings",
        "textual_critical_judgments",
        "textual_theological_interpretations",
        "textual_author_claims",
        "textual_translation_decisions",
    ):
        conn.execute(f"DELETE FROM {table} WHERE case_id = ?", (case_id,))

    reading_ids: dict[str, int] = {}
    for reading_key, tradition, reading_text, original_text in readings:
        cursor = conn.execute(
            """INSERT INTO textual_variant_readings
               (case_id, reading_key, tradition, text, original_text)
               VALUES (?, ?, ?, ?, ?)""",
            (case_id, reading_key, tradition, reading_text, original_text),
        )
        reading_ids[reading_key] = cursor.lastrowid

    for witness, reading_key, evidence_type in witnesses:
        conn.execute(
            """INSERT INTO textual_variant_witnesses
               (case_id, reading_id, witness, evidence_type, reading_support,
                approximate_date)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                case_id,
                reading_ids[reading_key] if reading_key else None,
                witness["manuscript"],
                evidence_type,
                witness["reading_support"],
                witness.get("manuscript_date") or None,
            ),
        )

    if interpretive:
        # The record's "variant reading" is an argument about how to read an
        # agreed text, and its consensus note concerns interpretation, not the
        # text; both are kept as attributed, uncited interpretation.
        for interpretation, attribution in (
            (variant.get("variant_reading"), "Dataset editorial note"),
            (variant.get("scholarly_consensus"), "Dataset summary of scholarly opinion"),
        ):
            if interpretation:
                conn.execute(
                    """INSERT INTO textual_theological_interpretations
                       (case_id, interpretation, attribution)
                       VALUES (?, ?, ?)""",
                    (case_id, interpretation, attribution),
                )

    # The dataset's consensus text carries no source citation, so it is stored
    # without one; the API presents uncited judgments as unsourced summaries.
    elif variant.get("scholarly_consensus"):
        conn.execute(
            """INSERT INTO textual_critical_judgments
               (case_id, judgment, attribution)
               VALUES (?, ?, ?)""",
            (
                case_id,
                variant["scholarly_consensus"],
                "Dataset editorial summary",
            ),
        )

    if variant.get("heiser_analysis"):
        conn.execute(
            """INSERT INTO textual_author_claims
               (case_id, author, claim)
               VALUES (?, ?, ?)""",
            (case_id, "Michael S. Heiser", variant["heiser_analysis"]),
        )

    if variant.get("preferred_for_hlt"):
        conn.execute(
            """INSERT INTO textual_translation_decisions
               (case_id, translation, preferred_reading, rationale)
               VALUES (?, ?, ?, ?)""",
            (
                case_id,
                "Heiser Literal Translation (HLT)",
                variant["preferred_for_hlt"],
                variant.get("hlt_rationale"),
            ),
        )

    return case_id


def import_textual_variants(conn: sqlite3.Connection, variants_dir: Path) -> int:
    """Import the bundled JSON dataset's variant and interpretive cases.

    Each record is replaced atomically. A malformed record is rolled back (its
    previously imported rows stay intact), the remaining records are imported
    and committed, and a ``ValueError`` naming every failed record is raised
    so the problem cannot pass silently.
    """
    count = 0
    failures: list[str] = []
    for filepath in sorted(variants_dir.glob("*.json")):
        with open(filepath, encoding="utf-8") as file:
            data = json.load(file)
        for variant in data.get("variants", []):
            try:
                import_textual_variant_record(conn, variant)
                count += 1
            except (KeyError, TypeError, ValueError, sqlite3.Error) as error:
                failures.append(
                    f"{filepath.name} {variant.get('reference', '?')}: {error!r}"
                )

    conn.commit()
    if failures:
        raise ValueError(
            "Textual-variant records not imported: " + "; ".join(failures)
        )
    return count


def import_nt_ot_lxx_quote_hints(conn: sqlite3.Connection, hints_path: Path) -> int:
    """Import NT->OT LXX-form quotation hints, linking each to its variant case.

    A hint's ``variant_case`` names the case by (reference, case_key), so the
    link survives case IDs changing between builds. Re-importing updates the
    existing hint for the same NT/OT pair. A link to a case that is not loaded
    raises, so the variant cases must be imported first.
    """
    with open(hints_path, encoding="utf-8") as file:
        hints = json.load(file)["hints"]
    for hint in hints:
        case_id = None
        if hint.get("variant_case"):
            link = hint["variant_case"]
            row = conn.execute(
                "SELECT id FROM textual_variant_cases WHERE reference = ? AND case_key = ?",
                (link["reference"], link["case_key"]),
            ).fetchone()
            if row is None:
                raise ValueError(
                    f"Quotation hint {hint['nt_reference']} -> {hint['ot_reference']} "
                    f"links to missing case {link['reference']} {link['case_key']}"
                )
            case_id = row[0]
        conn.execute(
            """INSERT INTO nt_ot_lxx_quote_hints
               (nt_reference, nt_display, nt_book, ot_reference, ot_display,
                ot_book, follows_lxx, divergence_type, divergence_note,
                variant_case_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(nt_reference, ot_reference) DO UPDATE SET
                   nt_display = excluded.nt_display,
                   nt_book = excluded.nt_book,
                   ot_display = excluded.ot_display,
                   ot_book = excluded.ot_book,
                   follows_lxx = excluded.follows_lxx,
                   divergence_type = excluded.divergence_type,
                   divergence_note = excluded.divergence_note,
                   variant_case_id = excluded.variant_case_id""",
            (
                hint["nt_reference"], hint["nt_display"], hint["nt_book"],
                hint["ot_reference"], hint["ot_display"], hint["ot_book"],
                hint["follows_lxx"], hint.get("divergence_type"),
                hint.get("divergence_note"), case_id,
            ),
        )
    conn.commit()
    return len(hints)


def main():
    db_path = get_db_path()
    if not db_path.exists():
        print(f"Database not found at {db_path}")
        print("Run build_database.py first to create the base database.")
        sys.exit(1)

    data_dir = Path(__file__).resolve().parent.parent / "data" / "heiser"

    conn = sqlite3.connect(str(db_path))

    # Ensure HLT tables exist
    from study_bible_mcp.database import create_schema
    create_schema(conn)

    print("=" * 60)
    print("Importing Heiser Content for HLT")
    print("=" * 60)

    # 1. Import themes
    themes_path = data_dir / "themes.json"
    if themes_path.exists():
        count = import_themes(conn, themes_path)
        print(f"\n[Themes] Imported {count} themes")
    else:
        print(f"\nWarning: {themes_path} not found")

    # 2. Import content files
    content_dir = data_dir / "content"
    total_entries = 0
    total_urls = 0
    total_refs = 0
    total_themes = 0
    json_files = sorted(content_dir.glob("*.json"))
    print(f"\n[Content] Found {len(json_files)} content files")
    for filepath in json_files:
        entries, urls, refs, themes = import_content_file(conn, filepath)
        total_entries += entries
        total_urls += urls
        total_refs += refs
        total_themes += themes
        print(f"  {filepath.name}: {entries} entries, {urls} urls updated, "
              f"{refs} verse refs, {themes} theme links")

    print(f"\n[Content Totals] {total_entries} entries, {total_urls} urls updated, "
          f"{total_refs} verse refs, {total_themes} theme links")

    # 3. Import manuscript variants and interpretive (agreed-text) cases.
    variants_dir = data_dir / "variants"
    if variants_dir.exists() and list(variants_dir.glob("*.json")):
        count = import_textual_variants(conn, variants_dir)
        print(f"\n[Variants] Imported {count} textual-variant cases")
    else:
        print(f"\n[Variants] No variant files found in {variants_dir}")

    # 4. NT->OT LXX-form quotation hints (linked to the variant cases above).
    hints_path = data_dir / "lxx_quote_hints.json"
    if hints_path.exists():
        count = import_nt_ot_lxx_quote_hints(conn, hints_path)
        print(f"\n[Quotation hints] Imported {count} NT->OT LXX quotation hints")

    # Summary
    print("\n" + "=" * 60)
    for table in [
        "theology_themes",
        "theology_content",
        "theology_verse_index",
        "theology_theme_index",
        "textual_variant_cases",
        "textual_variant_readings",
        "textual_variant_witnesses",
        "textual_critical_judgments",
        "textual_theological_interpretations",
        "textual_author_claims",
        "textual_translation_decisions",
        "nt_ot_lxx_quote_hints",
    ]:
        row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        print(f"  {table}: {row[0]} rows")
    print("=" * 60)

    conn.close()
    print("\nDone!")


if __name__ == "__main__":
    main()
