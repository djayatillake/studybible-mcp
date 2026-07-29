#!/usr/bin/env python3
"""Relabel theology_content source_work / source_type for accurate provenance.

The original labels were internal slugs that read like book citations
('stott_cross_of_christ', 'lennox_seven_days'), and they surface in
get_theology_context output. The entries are original summary prose written from
the authors' publicly available research and teaching, not reproduced text from
their books, so the labels understated the provenance.

This rewrites them to descriptive labels and sets source_type accordingly:

  - Modern authors whose entries summarise public teaching -> 'summary'
  - Entries traceable to a specific public paper/article/podcast -> that medium
    (these rows already carry the source URL, shown in tool output)
  - John Owen (d. 1683), public domain -> cited directly by work

Idempotent: re-running after a successful pass is a no-op.

Usage: python scripts/relabel_theology_sources.py [db_path]
"""

import sqlite3
import sys

# old source_work -> (new source_work, new source_type)
REMAP = {
    # --- Modern authors: summaries of publicly available research/teaching ---
    "two_fathers_only": ("Bradley — Two Fathers Only (paper)", "paper"),
    "Burnett: So Shall Your Seed Be (JSPL 5.2, 2015)": (
        "Burnett — So Shall Your Seed Be (JSPL 5.2, 2015)",
        "article",
    ),
    "deut32_ot_worldview": (
        "Heiser — Deuteronomy 32 and the OT Worldview (paper)",
        "paper",
    ),
    "deut32_paper": (
        "Heiser — Deuteronomy 32:8 and the Sons of God (BibSac paper)",
        "paper",
    ),
    "divine_council_dotwpw": ("Heiser — The Divine Council (DOTWPW article)", "article"),
    "drmsh_articles": ("Heiser — collected papers and articles", "paper"),
    "naked_bible_podcast": ("Heiser — Naked Bible Podcast", "podcast"),
    "two_powers_drmsh": ("Heiser — Two Powers in Heaven (article)", "article"),
    "unseen_realm": ("Heiser — What Is an Elohim? and related articles", "article"),
    "lennox_daniel": ("Lennox on Daniel — faithful witness under empire", "summary"),
    "lennox_joseph_providence": (
        "Lennox on Joseph — providence and the problem of evil",
        "summary",
    ),
    "lennox_seven_days": ("Lennox on Genesis 1 — creation and science", "summary"),
    "stott_basic_christianity": ("Stott on the person and claims of Christ", "summary"),
    "stott_bst_acts_spirit": ("Stott on Acts and the work of the Spirit", "summary"),
    "stott_bst_ephesians": ("Stott on Ephesians", "summary"),
    "stott_bst_galatians": ("Stott on Galatians", "summary"),
    "stott_bst_romans": ("Stott on Romans", "summary"),
    "stott_bst_sermon": ("Stott on the Sermon on the Mount", "summary"),
    "stott_cross_of_christ": ("Stott on the cross and the atonement", "summary"),
    # --- Public domain (17th c.): cite the works directly ---
    "owen_communion": ("Owen — Communion with God (1657)", "treatise"),
    "owen_death_of_death": (
        "Owen — The Death of Death in the Death of Christ (1647)",
        "treatise",
    ),
    "owen_glory_of_christ": ("Owen — The Glory of Christ (1684)", "treatise"),
    "owen_hebrews": ("Owen — Exposition of Hebrews (1668-84)", "commentary"),
    "owen_justification": (
        "Owen — The Doctrine of Justification by Faith (1677)",
        "treatise",
    ),
    "owen_mortification": (
        "Owen — Of the Mortification of Sin in Believers (1656)",
        "treatise",
    ),
    "atonement_models": ("Synthesis note — atonement models compared", "synthesis_note"),
}

# Labels this script produces, so a second run can recognise its own work.
ALREADY_APPLIED = {new for new, _ in REMAP.values()}


def main(db_path: str = "db/study_bible.db") -> int:
    conn = sqlite3.connect(db_path)
    present = {r[0] for r in conn.execute("SELECT DISTINCT source_work FROM theology_content")}

    if present <= ALREADY_APPLIED:
        print(f"{db_path}: already relabelled ({len(present)} distinct labels) — nothing to do")
        return 0

    unmapped = present - set(REMAP) - ALREADY_APPLIED
    if unmapped:
        print(f"ERROR: unmapped source_work values in {db_path}: {sorted(unmapped)}", file=sys.stderr)
        return 1

    total = 0
    for old, (new_work, new_type) in REMAP.items():
        total += conn.execute(
            "UPDATE theology_content SET source_work = ?, source_type = ? WHERE source_work = ?",
            (new_work, new_type, old),
        ).rowcount
    conn.commit()

    print(f"{db_path}: relabelled {total} rows")
    for row in conn.execute(
        "SELECT source_author, source_work, source_type, COUNT(*) "
        "FROM theology_content GROUP BY 1, 2, 3 ORDER BY 1, 2"
    ):
        print("  ", row)
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
