#!/usr/bin/env python3
"""Migrate the legacy mixed textual-variant tables to evidence-separated tables."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from import_heiser_content import import_textual_variant_record

from study_bible_mcp.database import INTERPRETIVE_CASE_KEYS, create_schema


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone() is not None


def migrate(conn: sqlite3.Connection) -> tuple[int, int, int]:
    """Migrate legacy rows; return (variant_cases, interpretive_cases, quotation_hints).

    Interpretive cases are the ``MT_preserved`` and ``translation_choice``
    records, kept with their translation decisions and attributed claims.

    Runs in one transaction: any invalid legacy record (for example a witness
    whose ``reading_support`` label has no evidence-type mapping) raises and
    rolls the whole migration back, leaving the legacy tables in place.
    """
    if not _table_exists(conn, "textual_variants"):
        create_schema(conn)
        return (0, 0, 0)

    conn.row_factory = sqlite3.Row
    legacy_variants = [dict(row) for row in conn.execute("SELECT * FROM textual_variants")]
    legacy_witnesses = [
        dict(row) for row in conn.execute("SELECT * FROM manuscript_witnesses")
    ]
    legacy_hints = (
        [dict(row) for row in conn.execute("SELECT * FROM nt_ot_lxx_quote_hints")]
        if _table_exists(conn, "nt_ot_lxx_quote_hints")
        else []
    )
    witnesses_by_variant: dict[int, list[dict]] = {}
    for witness in legacy_witnesses:
        witnesses_by_variant.setdefault(witness["variant_id"], []).append(witness)

    create_schema(conn)
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("BEGIN IMMEDIATE")
    try:
        old_to_new: dict[int, int] = {}
        interpretive = 0
        for legacy in legacy_variants:
            variant = {
                "reference": legacy["reference"],
                "mt_reading": legacy["mt_reading"],
                "mt_hebrew": legacy["mt_hebrew"],
                "variant_source": legacy["variant_source"],
                "variant_reading": legacy["variant_reading"],
                "variant_original": legacy["variant_original"],
                "variant_significance": legacy["variant_significance"],
                "heiser_analysis": legacy["heiser_analysis"],
                "scholarly_consensus": legacy["scholarly_consensus"],
                "preferred_for_hlt": legacy["preferred_for_hlt"],
                "hlt_rationale": legacy["hlt_rationale"],
                "witnesses": witnesses_by_variant.get(legacy["id"], []),
            }
            old_to_new[legacy["id"]] = import_textual_variant_record(conn, variant)
            if legacy["variant_source"] in INTERPRETIVE_CASE_KEYS:
                interpretive += 1

        if _table_exists(conn, "nt_ot_lxx_quote_hints"):
            conn.execute("DROP TABLE nt_ot_lxx_quote_hints")
        conn.execute(
            """CREATE TABLE nt_ot_lxx_quote_hints (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   nt_reference TEXT NOT NULL,
                   nt_display TEXT NOT NULL,
                   nt_book TEXT NOT NULL,
                   ot_reference TEXT NOT NULL,
                   ot_display TEXT NOT NULL,
                   ot_book TEXT NOT NULL,
                   follows_lxx INTEGER NOT NULL DEFAULT 1,
                   divergence_type TEXT,
                   divergence_note TEXT,
                   variant_case_id INTEGER REFERENCES textual_variant_cases(id),
                   UNIQUE(nt_reference, ot_reference)
               )"""
        )
        conn.execute(
            "CREATE INDEX idx_ntoq_nt ON nt_ot_lxx_quote_hints(nt_reference)"
        )
        conn.execute(
            "CREATE INDEX idx_ntoq_ot ON nt_ot_lxx_quote_hints(ot_reference)"
        )
        conn.execute(
            "CREATE INDEX idx_ntoq_nt_book ON nt_ot_lxx_quote_hints(nt_book)"
        )
        conn.execute(
            "CREATE INDEX idx_ntoq_ot_book ON nt_ot_lxx_quote_hints(ot_book)"
        )
        for hint in legacy_hints:
            conn.execute(
                """INSERT INTO nt_ot_lxx_quote_hints
                   (id, nt_reference, nt_display, nt_book, ot_reference,
                    ot_display, ot_book, follows_lxx, divergence_type,
                    divergence_note, variant_case_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    hint["id"],
                    hint["nt_reference"],
                    hint["nt_display"],
                    hint["nt_book"],
                    hint["ot_reference"],
                    hint["ot_display"],
                    hint["ot_book"],
                    hint["follows_lxx"],
                    hint["divergence_type"],
                    hint["divergence_note"],
                    old_to_new.get(hint["textual_variant_id"]),
                ),
            )

        conn.execute("DROP TABLE manuscript_witnesses")
        conn.execute("DROP TABLE textual_variants")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")

    return (len(old_to_new) - interpretive, interpretive, len(legacy_hints))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        type=Path,
        default=PROJECT_ROOT / "db" / "study_bible.db",
        help="SQLite database to migrate",
    )
    args = parser.parse_args()

    with sqlite3.connect(args.database) as conn:
        cases, interpretive, hints = migrate(conn)
    print(
        f"Migrated {cases} manuscript variant cases, {interpretive} interpretive "
        f"cases, and {hints} quotation hints."
    )


if __name__ == "__main__":
    main()
