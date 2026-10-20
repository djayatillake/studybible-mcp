#!/usr/bin/env python3
"""Upgrade an existing study_bible.db in place with the current schema and sources.

Intended for the deployed-database workflow (download from Fly, upgrade, upload),
where a full ``build_database.py --rebuild`` is impractical. The upgrade:

1. downloads the pinned LXX/Brenton sources and every registered ancient-source
   corpus (skipping files already present; every file is checksum-verified
   against its pinned source),
2. migrates legacy mixed textual-variant tables to the evidence-separated schema
   and adds new columns to existing tables,
3. imports MT/LXX edition rows, every registered ancient-source corpus with
   its curated editorial notes and links (a corpus whose source files are
   missing or incomplete fails the upgrade), and the bundled manuscript-variant
   records,
4. verifies SQLite integrity and foreign keys.

All work happens on a temporary copy next to the target; the target file is
replaced atomically only after every step and check succeeds, so a failed
upgrade leaves the original intact. Re-running the upgrade is safe: the
migration is a no-op once applied and every import replaces its own rows.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import click

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from import_heiser_content import import_nt_ot_lxx_quote_hints, import_textual_variants
from migrate_textual_variants import migrate

from study_bible_mcp.corpora import CORPORA
from study_bible_mcp.database import build_strongs_index, create_schema
from study_bible_mcp.parsers.ancient_sources import import_available_corpora, missing_corpora
from study_bible_mcp.parsers.biblical_versions import import_biblical_versions


def _download_sources(data_dir: Path) -> None:
    for script, target in (
        ("download_biblical_versions.py", data_dir / "lxx"),
        ("download_ancient_sources.py", data_dir / "ancient_sources"),
    ):
        subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / script), "--data-dir", str(target)],
            check=True,
        )


def require_ancient_sources(ancient_dir: Path) -> None:
    """Fail unless every registered ancient-source corpus is downloaded and complete."""
    missing = missing_corpora(ancient_dir)
    if missing:
        raise click.ClickException(
            "Missing ancient-source corpora (run without --offline, or "
            "scripts/download_ancient_sources.py): "
            + "; ".join(f"{key}: {reason}" for key, reason in missing.items())
        )


def _require_sources(data_dir: Path) -> None:
    required = (
        data_dir / "lxx" / "verse_pairs.jsonl",
        data_dir / "lxx" / "morphology",
        data_dir / "lxx" / "brenton",
        data_dir / "heiser" / "variants",
    )
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise click.ClickException(
            "Missing source data (run without --offline to download): " + ", ".join(missing)
        )
    require_ancient_sources(data_dir / "ancient_sources")


def upgrade(database: Path, data_dir: Path) -> dict[str, int]:
    """Upgrade ``database`` (already a working copy) and return import counts."""
    conn = sqlite3.connect(database)
    try:
        if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'verses'"
        ).fetchone() is None:
            raise click.ClickException(
                f"{database} has no verses table; build it with build_database.py first."
            )
        require_ancient_sources(data_dir / "ancient_sources")
        cases, interpretive, hints = migrate(conn)
        create_schema(conn)
        mt_rows, lxx_rows = import_biblical_versions(conn, data_dir)
        corpora = import_available_corpora(conn, data_dir / "ancient_sources")
        variants = import_textual_variants(conn, data_dir / "heiser" / "variants")
        bundled_hints = 0
        hints_path = data_dir / "heiser" / "lxx_quote_hints.json"
        if hints_path.exists():
            bundled_hints = import_nt_ot_lxx_quote_hints(conn, hints_path)
        strongs_index = build_strongs_index(conn)
        conn.execute("ANALYZE")
        conn.commit()

        if not mt_rows or not lxx_rows:
            raise click.ClickException(
                f"Import produced no rows (MT={mt_rows}, LXX={lxx_rows})."
            )
        skipped = [key for key, count in corpora.items() if count is None]
        if skipped:
            raise click.ClickException(
                "Ancient-source corpora not imported: "
                + ", ".join(f"{key} ({CORPORA[key].data_dir})" for key in skipped)
            )
        variant_cases = conn.execute(
            "SELECT COUNT(*) FROM textual_variant_cases"
        ).fetchone()[0]
        if not variant_cases:
            raise click.ClickException("No textual-variant cases after the upgrade.")
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise click.ClickException(f"Integrity check failed: {integrity}")
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise click.ClickException(f"Foreign key violations: {violations[:5]}")
    finally:
        conn.close()

    return {
        "migrated_variant_cases": cases,
        "migrated_interpretive_cases": interpretive,
        "quotation_hints": hints,
        "mt_rows": mt_rows,
        "lxx_rows": lxx_rows,
        **{f"{key}_passages": count for key, count in corpora.items() if count is not None},
        "bundled_variant_cases": variants,
        "bundled_quotation_hints": bundled_hints,
        "textual_variant_cases": variant_cases,
        "strongs_index_rows": strongs_index,
    }


def upgrade_in_place(database: Path, data_dir: Path) -> dict[str, int]:
    """Upgrade a copy of ``database`` and atomically replace it on success.

    The copy is taken with SQLite's backup API (so committed WAL content is
    included) into the same directory, which keeps the final ``os.replace``
    atomic. On any failure the copy is removed and ``database`` is untouched.
    """
    working = database.with_name(database.name + ".upgrade-tmp")
    working.unlink(missing_ok=True)
    try:
        source = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)
        target = sqlite3.connect(working)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()

        counts = upgrade(working, data_dir)

        with open(working, "rb") as handle:
            os.fsync(handle.fileno())
        shutil.copymode(database, working)
        os.replace(working, database)
    finally:
        working.unlink(missing_ok=True)
    return counts


@click.command()
@click.option(
    "--database",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=PROJECT_ROOT / "db" / "study_bible.db",
    show_default=True,
)
@click.option(
    "--data-dir",
    type=click.Path(path_type=Path, file_okay=False),
    default=PROJECT_ROOT / "data",
    show_default=True,
)
@click.option("--offline", is_flag=True, help="Use already-downloaded sources only.")
def main(database: Path, data_dir: Path, offline: bool) -> None:
    """Upgrade an existing database with the current schema and pinned sources."""
    if not offline:
        _download_sources(data_dir)
    _require_sources(data_dir)

    counts = upgrade_in_place(database, data_dir)

    for key, value in counts.items():
        click.echo(f"{key}: {value}")
    click.echo(f"Upgraded {database}")


if __name__ == "__main__":
    main()
