#!/usr/bin/env python3
"""Import cross-reference datasets into study_bible.db.

Two sources, both written into the existing `cross_references` table with
the `type` column distinguishing provenance:

* CH  — Harrison & Romhild's curated dataset (~82k pairs).
        Source xlsx: data/cross_references/CH-CrossReference.xlsx
        relevance = Orig*2 + Circ  (range 0..3)

* TSK — Treasury of Scripture Knowledge via openbible.info (~340k pairs).
        Source tsv: data/cross_references/cross_references.txt
        relevance = vote count

The script is idempotent — it DROPs and re-creates the cross_references
table on each run so re-imports stay clean. Existing thematic_references
are untouched.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from study_bible_mcp.parsers.cross_references import (  # noqa: E402
    parse_ch_xlsx,
    parse_tsk_tsv,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "db" / "study_bible.db"
DATA_DIR = PROJECT_ROOT / "data" / "cross_references"
CH_PATH = DATA_DIR / "CH-CrossReference.xlsx"
TSK_PATH = DATA_DIR / "cross_references.txt"

BATCH_SIZE = 5000


def reset_table(conn: sqlite3.Connection) -> None:
    """Drop and re-create cross_references to pick up the new schema."""
    conn.execute("DROP TABLE IF EXISTS cross_references")
    conn.execute(
        """
        CREATE TABLE cross_references (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            target TEXT NOT NULL,
            type TEXT,
            note TEXT,
            relevance INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute(
        "CREATE INDEX idx_xref_source ON cross_references(source)"
    )
    conn.execute(
        "CREATE INDEX idx_xref_source_rank "
        "ON cross_references(source, type, relevance DESC)"
    )
    conn.commit()


def bulk_insert(
    conn: sqlite3.Connection,
    rows: list[tuple[str, str, str, int]],
) -> None:
    conn.executemany(
        "INSERT INTO cross_references (source, target, type, relevance) "
        "VALUES (?, ?, ?, ?)",
        rows,
    )


def import_ch(conn: sqlite3.Connection) -> int:
    if not CH_PATH.exists():
        print(f"[CH] not found: {CH_PATH} — skipping")
        return 0

    print(f"[CH] importing from {CH_PATH.name} ...")
    batch: list[tuple[str, str, str, int]] = []
    total = 0
    for source, target, relevance in parse_ch_xlsx(CH_PATH):
        batch.append((source, target, "ch", relevance))
        if len(batch) >= BATCH_SIZE:
            bulk_insert(conn, batch)
            total += len(batch)
            batch.clear()
            print(f"  ... {total} CH rows")
    if batch:
        bulk_insert(conn, batch)
        total += len(batch)
    conn.commit()
    print(f"[CH] inserted {total} rows")
    return total


def import_tsk(conn: sqlite3.Connection) -> int:
    if not TSK_PATH.exists():
        print(f"[TSK] not found: {TSK_PATH} — skipping")
        return 0

    print(f"[TSK] importing from {TSK_PATH.name} ...")
    batch: list[tuple[str, str, str, int]] = []
    total = 0
    for source, target, relevance in parse_tsk_tsv(TSK_PATH):
        batch.append((source, target, "tsk", relevance))
        if len(batch) >= BATCH_SIZE:
            bulk_insert(conn, batch)
            total += len(batch)
            batch.clear()
            if total % 50000 == 0:
                print(f"  ... {total} TSK rows")
    if batch:
        bulk_insert(conn, batch)
        total += len(batch)
    conn.commit()
    print(f"[TSK] inserted {total} rows")
    return total


def main() -> None:
    if not DB_PATH.exists():
        print(f"Database not found at {DB_PATH}")
        print("Run scripts/build_database.py first.")
        sys.exit(1)

    if not CH_PATH.exists() and not TSK_PATH.exists():
        print(f"No source files in {DATA_DIR}/")
        print("Expected:")
        print(f"  - {CH_PATH.name}  (Harrison/Romhild xlsx — request from")
        print("      Robert Rouse / Viz.Bible; ~4 MB, 82k pairs)")
        print(f"  - {TSK_PATH.name}  (openbible.info TSK tsv)")
        print("    Download:")
        print("      curl -Lo /tmp/tsk.zip https://a.openbible.info/data/cross-references.zip")
        print(f"      unzip -p /tmp/tsk.zip > {TSK_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(str(DB_PATH))
    try:
        print("=" * 60)
        print("Importing cross-references")
        print("=" * 60)

        reset_table(conn)
        ch_n = import_ch(conn)
        tsk_n = import_tsk(conn)

        print()
        print("=" * 60)
        total = conn.execute(
            "SELECT COUNT(*) FROM cross_references"
        ).fetchone()[0]
        ch_count = conn.execute(
            "SELECT COUNT(*) FROM cross_references WHERE type = 'ch'"
        ).fetchone()[0]
        tsk_count = conn.execute(
            "SELECT COUNT(*) FROM cross_references WHERE type = 'tsk'"
        ).fetchone()[0]
        print(f"  cross_references: {total} rows")
        print(f"    type='ch':  {ch_count}")
        print(f"    type='tsk': {tsk_count}")
        print(f"  parsed: CH={ch_n}, TSK={tsk_n}")
        print("=" * 60)
    finally:
        conn.close()
    print("\nDone!")


if __name__ == "__main__":
    main()
