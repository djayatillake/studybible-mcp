#!/usr/bin/env python3
"""Correct the Greek evidence at Job 38:7, Daniel 4:17 and 7:13, and Psalm 29:1.

The bundled records for these verses (reported in #4) listed Greek witnesses as
agreeing with the MT where the Rahlfs text does not:

- Job 38:7: the LXX has πάντες ἄγγελοί μου ("all my angels") for "all the
  sons of God".
- Daniel 4:17: the Old Greek has no equivalent for the decree-of-the-watchers
  clause; only Theodotion keeps it.
- Daniel 7:13: the Old Greek has ἐπί ("upon") the clouds, Theodotion μετά
  ("with"), as the MT.
- Psalm 29:1: the LXX has a doublet, υἱοὶ θεοῦ and υἱοὺς κριῶν.

The corrected records add a manuscript-variant case at each verse beside its
interpretation notes, and drop the diverging Greek witnesses from the notes.
This script brings an existing database into line without rebuilding it. It
touches only the textual-variant rows of the eight cases in CASES.

Two modes, both idempotent:

  repair_textual_variant_witnesses.py DB [--data-dir data] [--write-patch PATCH]
      Import the corrected records from data/heiser/variants with the real
      importer and install their rows. --write-patch also saves the rows, so a
      copy of the same database elsewhere (the Fly volume) can be repaired
      without the sources.

  repair_textual_variant_witnesses.py DB --apply-patch PATCH
      Apply a saved patch. Needs only the standard library, so it runs on the
      server from a copy of this script.

A case is replaced only while it holds exactly the rows the previous records
produced (for a new case: while it is absent); a case that already holds the
corrected rows is left alone. If any case holds anything else, nothing is
changed. Case ids are kept, so links to them stay valid.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CASES = (
    ("Job.38.7", "MT_preserved"),
    ("Job.38.7", "LXX_divergence"),
    ("Dan.4.17", "MT_preserved"),
    ("Dan.4.17", "LXX_OG_omission"),
    ("Dan.7.13", "MT_preserved"),
    ("Dan.7.13", "LXX_OG_divergence"),
    ("Psa.29.1", "translation_choice"),
    ("Psa.29.1", "LXX_doublet"),
)
# Fingerprints of the rows the previous records produced; None: no such case.
BEFORE = {
    ("Job.38.7", "MT_preserved"): "1f9f57f9e278bf7a4134f18604325d925dd905ed10aa451010fd942b7115f842",
    ("Job.38.7", "LXX_divergence"): None,
    ("Dan.4.17", "MT_preserved"): "660b341d560fe487efe317dc31dab73577e501bbfe1a6199478cb03236c18586",
    ("Dan.4.17", "LXX_OG_omission"): None,
    ("Dan.7.13", "MT_preserved"): "d677d9d6b2eb92b6bb3f3721e547c24b5557999a42d3973ab3f7695da5c05c83",
    ("Dan.7.13", "LXX_OG_divergence"): None,
    ("Psa.29.1", "translation_choice"): "28a4460ea71b123fe1f807dd6769c5863a3c7f1196462878314aeb3df871bc2a",
    ("Psa.29.1", "LXX_doublet"): None,
}
CASE_COLUMNS = ("reference", "book", "chapter", "verse", "case_key", "significance")
READING_COLUMNS = ("reading_key", "tradition", "text", "original_text", "language")
WITNESS_COLUMNS = (
    "witness", "evidence_type", "reading_support", "approximate_date",
    "source_citation", "source_url",
)
# The other per-case tables and their columns, in the importer's order.
CLAIM_TABLES = {
    "textual_critical_judgments": ("judgment", "attribution", "source_citation", "source_url"),
    "textual_theological_interpretations": (
        "interpretation", "attribution", "source_citation", "source_url",
    ),
    "textual_author_claims": ("author", "claim", "source_citation", "source_url"),
    "textual_translation_decisions": ("translation", "preferred_reading", "rationale"),
}


def read_case(conn: sqlite3.Connection, reference: str, case_key: str) -> dict | None:
    """A case's rows without their ids, each table in id order; None if absent."""
    row = conn.execute(
        f"SELECT id, {', '.join(CASE_COLUMNS)} FROM textual_variant_cases "
        "WHERE reference = ? AND case_key = ?",
        (reference, case_key),
    ).fetchone()
    if row is None:
        return None
    case_id = row[0]
    rows = {
        "case": list(row[1:]),
        "readings": [
            list(r) for r in conn.execute(
                f"SELECT {', '.join(READING_COLUMNS)} FROM textual_variant_readings "
                "WHERE case_id = ? ORDER BY id",
                (case_id,),
            )
        ],
        # A witness names its reading by key, so the rows hold no ids.
        "witnesses": [
            list(r) for r in conn.execute(
                "SELECT r.reading_key, "
                + ", ".join(f"w.{column}" for column in WITNESS_COLUMNS)
                + " FROM textual_variant_witnesses w "
                "LEFT JOIN textual_variant_readings r ON r.id = w.reading_id "
                "WHERE w.case_id = ? ORDER BY w.id",
                (case_id,),
            )
        ],
    }
    for table, columns in CLAIM_TABLES.items():
        rows[table] = [
            list(r) for r in conn.execute(
                f"SELECT {', '.join(columns)} FROM {table} WHERE case_id = ? ORDER BY id",
                (case_id,),
            )
        ]
    return rows


def digest(rows: dict | None) -> str | None:
    """A fingerprint of a case's rows; None for an absent case."""
    if rows is None:
        return None
    canonical = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def write_case(conn: sqlite3.Connection, rows: dict) -> None:
    """Replace one case's rows, keeping its id, as the importer does."""
    case = dict(zip(CASE_COLUMNS, rows["case"]))
    found = conn.execute(
        "SELECT id FROM textual_variant_cases WHERE reference = ? AND case_key = ?",
        (case["reference"], case["case_key"]),
    ).fetchone()
    if found is None:
        case_id = conn.execute(
            f"INSERT INTO textual_variant_cases ({', '.join(CASE_COLUMNS)}) "
            f"VALUES ({', '.join('?' for _ in CASE_COLUMNS)})",
            rows["case"],
        ).lastrowid
    else:
        case_id = found[0]
        conn.execute(
            "UPDATE textual_variant_cases SET book = ?, chapter = ?, verse = ?, "
            "significance = ? WHERE id = ?",
            (case["book"], case["chapter"], case["verse"], case["significance"], case_id),
        )
    for table in ("textual_variant_witnesses", "textual_variant_readings", *CLAIM_TABLES):
        conn.execute(f"DELETE FROM {table} WHERE case_id = ?", (case_id,))

    reading_ids = {}
    for reading in rows["readings"]:
        reading_ids[reading[0]] = conn.execute(
            f"INSERT INTO textual_variant_readings (case_id, {', '.join(READING_COLUMNS)}) "
            f"VALUES (?, {', '.join('?' for _ in READING_COLUMNS)})",
            (case_id, *reading),
        ).lastrowid
    for reading_key, *witness in rows["witnesses"]:
        conn.execute(
            f"INSERT INTO textual_variant_witnesses "
            f"(case_id, reading_id, {', '.join(WITNESS_COLUMNS)}) "
            f"VALUES (?, ?, {', '.join('?' for _ in WITNESS_COLUMNS)})",
            (case_id, None if reading_key is None else reading_ids[reading_key], *witness),
        )
    for table, columns in CLAIM_TABLES.items():
        conn.executemany(
            f"INSERT INTO {table} (case_id, {', '.join(columns)}) "
            f"VALUES (?, {', '.join('?' for _ in columns)})",
            [(case_id, *row) for row in rows[table]],
        )


def compute_changes(data_dir: Path) -> dict:
    """The patch: each case's expected fingerprint and its corrected rows.

    The rows come from importing the bundled records with the real importer
    into an empty in-memory database.
    """
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    from import_heiser_content import import_textual_variant_record

    from study_bible_mcp.database import create_schema

    variants_dir = data_dir / "heiser" / "variants"
    references = {reference for reference, _ in CASES}
    records = [
        variant
        for path in sorted(variants_dir.glob("*.json"))
        for variant in json.loads(path.read_text(encoding="utf-8")).get("variants", [])
        if variant.get("reference") in references
    ]
    found = sorted((variant["reference"], variant["variant_source"]) for variant in records)
    if found != sorted(CASES):
        raise SystemExit(
            f"{variants_dir} has records {found} for {sorted(references)}, "
            f"expected {sorted(CASES)}; nothing was changed"
        )

    scratch = sqlite3.connect(":memory:")
    try:
        create_schema(scratch)
        for variant in records:
            import_textual_variant_record(scratch, variant)
        cases = [
            {
                "reference": reference,
                "case_key": case_key,
                "before": BEFORE[(reference, case_key)],
                "rows": read_case(scratch, reference, case_key),
            }
            for reference, case_key in CASES
        ]
    finally:
        scratch.close()
    return {"cases": cases}


def apply_changes(conn: sqlite3.Connection, changes: dict) -> tuple[list[str], list[str]]:
    """Apply a patch in one transaction; return (cases replaced, conflicts)."""
    if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'textual_variant_cases'"
    ).fetchone() is None:
        raise SystemExit(
            "The database has no textual_variant_cases table; run "
            "scripts/upgrade_database.py first. Nothing was changed"
        )
    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")
    replaced = []
    conflicts = []
    for case in changes["cases"]:
        label = f"{case['reference']} {case['case_key']}"
        after = digest(case["rows"])
        current = digest(read_case(conn, case["reference"], case["case_key"]))
        if current == after:
            continue
        if current != case["before"]:
            conflicts.append(
                f"{label} is missing" if current is None
                else f"{label} holds neither the rows the patch replaces nor its rows"
            )
            continue
        write_case(conn, case["rows"])
        if digest(read_case(conn, case["reference"], case["case_key"])) != after:
            conflicts.append(f"{label} did not read back as the patch's rows")
        replaced.append(label)
    return replaced, conflicts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("db", type=Path)
    parser.add_argument("--data-dir", type=Path, default=PROJECT_ROOT / "data")
    parser.add_argument("--write-patch", type=Path)
    parser.add_argument("--apply-patch", type=Path)
    args = parser.parse_args()
    if not args.db.exists():
        raise SystemExit(f"No database at {args.db}")

    if args.apply_patch:
        with gzip.open(args.apply_patch, "rt", encoding="utf-8") as handle:
            changes = json.load(handle)
    else:
        changes = compute_changes(args.data_dir)
        if args.write_patch:
            with gzip.open(args.write_patch, "wt", encoding="utf-8") as handle:
                json.dump(changes, handle, ensure_ascii=False, separators=(",", ":"))

    conn = sqlite3.connect(args.db, timeout=30)
    try:
        replaced, conflicts = apply_changes(conn, changes)
        if conflicts:
            conn.rollback()
            for conflict in conflicts:
                print(f"ERROR: {conflict}", file=sys.stderr)
            print("Nothing was changed", file=sys.stderr)
            return 1
        conn.commit()
    finally:
        conn.close()

    source = f"the patch {args.apply_patch}" if args.apply_patch else f"the records in {args.data_dir}"
    total = len(changes["cases"])
    print(f"{args.db}, from {source}: {total} textual-variant cases")
    if replaced:
        print(f"   replaced {', '.join(replaced)}")
    print(f"   {total - len(replaced)} of {total} already held the corrected rows")
    if args.write_patch:
        print(f"   patch written to {args.write_patch}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
