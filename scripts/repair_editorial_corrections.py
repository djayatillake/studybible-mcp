#!/usr/bin/env python3
"""Install the editorial corrections to curated content in an existing database.

The owner's editorial review recalibrated curated text that a fresh build now
takes from the source files: consensus overclaims attributed, non-canonical
sources labelled, the atonement corpus's confidence ratings brought to the
method_002 tiers, factual slips corrected, a manuscript-variant case for the
Greek evidence at Genesis 6:2, and 1 Enoch passages paired with biblical
texts. This script brings an existing database into line without rebuilding
it. It touches only these rows:

- textual-variant cases in CASES (each replaced whole, keeping its id, as the
  importer does) and NT quotation hints in HINTS;
- theology_themes.description for THEMES;
- theology_content summary and detail for CONTENT (Heiser and Burnett);
- ane_entries text columns for ANE;
- new ancient_source_biblical_links rows for the 1 Enoch passages in LINKS.

Two modes, both idempotent:

  repair_editorial_corrections.py DB [--data-dir data] [--write-patch PATCH]
      Read the corrected rows from the source files with the real parsers and
      importers, and install them. --write-patch also saves them, so a copy of
      the same database elsewhere (the Fly volume) can be repaired without the
      sources.

  repair_editorial_corrections.py DB --apply-patch PATCH
      Apply a saved patch. Needs only the standard library, so it runs on the
      server from a copy of this script.

Every row is checked first. A row is changed only while it holds exactly what
the previous sources produced (BEFORE; for a new case, hint or link: while it
is absent); a row already holding the corrected values is left alone. If any
row holds anything else, the whole run rolls back and nothing is changed.

The database must already have the Greek-evidence fix of
scripts/repair_textual_variant_witnesses.py (#4). That script, run on an older
database, now installs these corrections' text for its own eight cases too, so
the two scripts can be run in either order on such a database.
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

# --- What changes ------------------------------------------------------------

CASES = (
    ("Gen.1.26", "translation_choice"),
    ("Gen.3.1", "translation_choice"),
    ("Gen.6.2", "MT_preserved"),
    ("Gen.6.2", "LXX_manuscript_variant"),
    ("Gen.6.4", "translation_choice"),
    ("Gen.18.1", "MT_preserved"),
    ("Gen.48.16", "MT_preserved"),
    ("Deu.32.8", "DSS_4QDeutj"),
    ("Deu.32.43", "DSS_4QDeutq"),
    ("Jos.5.13", "MT_preserved"),
    ("Job.38.7", "MT_preserved"),
    ("Psa.29.1", "translation_choice"),
    ("Psa.40.6", "LXX_quoted_in_NT"),
    ("Psa.82.1", "MT_preserved"),
    ("Psa.82.6", "MT_preserved"),
    ("Psa.89.6", "translation_choice"),
    ("Dan.4.17", "MT_preserved"),
    ("Dan.7.13", "MT_preserved"),
    ("Zec.3.1", "MT_preserved"),
    ("Zec.3.2", "MT_preserved"),
)
HINTS = (("Heb.10.5", "Psa.40.6"), ("Heb.1.6", "Deu.32.43"))
THEMES = ("sons_of_god", "nachash_serpent", "cherem_warfare", "watchers_tradition")
CONTENT = (
    ("Heiser — Deuteronomy 32:8 and the Sons of God (BibSac paper)", "Introduction",
     "The Textual Variant in Deuteronomy 32:8 — Sons of God vs Sons of Israel"),
    ("Heiser — Deuteronomy 32:8 and the Sons of God (BibSac paper)", "Textual Criticism section",
     "Text-Critical Methodology: No A Priori MT Superiority"),
    ("Heiser — collected papers and articles", "Elohim FSB article",
     "The Five Uses of Elohim in the Hebrew Bible"),
    ("Heiser — collected papers and articles", "Section 2: The Meaning of Elohim",
     "Elohim as a 'Place of Residence' Term — The Key to Psalm 82"),
    ("Heiser — What Is an Elohim? and related articles", "What is an Elohim",
     "Elohim Describes a Plane of Existence, Not a Set of Attributes"),
    ("Heiser — What Is an Elohim? and related articles", "The Nachash",
     "The Nachash of Eden — A Shining Divine Being, Not a Talking Snake"),
    ("Heiser — Naked Bible Podcast", "Episode 94",
     "The Watchers' Sin as the Origin of Evil — Not Adam's Fall Alone"),
    ("Heiser — Naked Bible Podcast", "Episode 94",
     "Demons as Disembodied Spirits of Dead Nephilim — The Second Temple Understanding"),
    ("Heiser — Naked Bible Podcast", "Episode 334",
     "The Nephilim Were Giants — Offspring of the Divine-Human Union"),
    ("Heiser — Naked Bible Podcast", "Episodes 434-435",
     "Jude 6 — The Angels Who Left Their Proper Domain Are the Watchers of Genesis 6"),
    ("Heiser — Naked Bible Podcast", "Episodes 434-435 (cross-reference)",
     "The Azazel/Scapegoat Connection — Leviticus 16 and the Watchers Tradition"),
    ("Burnett — So Shall Your Seed Be (JSPL 5.2, 2015)", "Main thesis",
     "Abraham's Star-Like Seed: The Qualitative Reading of Genesis 15:5"),
    ("Burnett — So Shall Your Seed Be (JSPL 5.2, 2015)", "Divine-council frame",
     "Deuteronomy 32:8 and the Inheritance of the Nations"),
)
ANE = (
    "cosmo_008", "cosmo_009", "cosmo_012", "relig_008", "relig_011", "relig_013",
    "relig_014", "relig_015", "relig_016", "relig_020", "relig_021", "legal_009",
    "lit_006", "death_005", "method_002", "method_004", "method_006", "method_007",
    "method_008",
)
# New typed links (corpus, citation, biblical reference) from editorial_notes.json.
LINKS = (
    ("pseudepigrapha", "1 Enoch 1:5", "Gen 6:1-4"),
    ("pseudepigrapha", "1 Enoch 1:5", "Jude 1:6"),
    ("pseudepigrapha", "1 Enoch 1:5", "2 Pet 2:4"),
    ("pseudepigrapha", "1 Enoch 10:15", "Gen 6:1-4"),
    ("pseudepigrapha", "1 Enoch 10:15", "Jude 1:6"),
    ("pseudepigrapha", "1 Enoch 12:2", "Gen 6:1-4"),
    ("pseudepigrapha", "1 Enoch 12:2", "Jude 1:6"),
    ("pseudepigrapha", "1 Enoch 69:29", "Dan 7:13-14"),
    ("pseudepigrapha", "1 Enoch 69:29", "Matt 25:31"),
    ("pseudepigrapha", "1 Enoch 69:29", "Matt 19:28"),
    ("pseudepigrapha", "1 Enoch 71:13", "Dan 7:13-14"),
)

# Columns each kind of row carries (the rest of the row is not touched).
THEME_COLUMNS = ("description",)
CONTENT_COLUMNS = ("content_summary", "content_detail")
ANE_COLUMNS = ("summary", "detail", "ane_parallels", "interpretive_significance")

# Fingerprints of the rows the previous sources produced (the deployed
# database); None: no such row yet.
BEFORE = {
    "case Gen.1.26 translation_choice":
        "419a255c16176d72e395930682ae03ec365f9357a72b5a405707b51ae5172baf",
    "case Gen.3.1 translation_choice":
        "1cb387510100f030bf2843c5b55dcf4c017e1eec193076f3241fe351412246fc",
    "case Gen.6.2 MT_preserved": "abb623c3a40d0cf605921c115e31c81e120a9ba20fa550f1f1b4f89fd3e4fd54",
    "case Gen.6.2 LXX_manuscript_variant": None,
    "case Gen.6.4 translation_choice":
        "581dcca7e49d6703f57f3141a4b24eeecd9e586849273b739f055459f03d993f",
    "case Gen.18.1 MT_preserved":
        "6688f59c9065f916dec499830f813357ea54747e553417ab8e3b703fbe184679",
    "case Gen.48.16 MT_preserved":
        "e70c811aa992df13899d915635a86c40d7ea17f41768c35c84f122c5734508f9",
    "case Deu.32.8 DSS_4QDeutj": "103447ef8fc35c9f9dcdf1de80bfc9211d2cc0bcdbb087d13356762faccfe4ad",
    "case Deu.32.43 DSS_4QDeutq":
        "569c0e2c32920093b14df062641df415cf97d919f0cee2819f6380a171d5a936",
    "case Jos.5.13 MT_preserved":
        "d09754bc26ac6dc7eee2f1e3795f746ab42bba15dad16a598b653ca07aad4e97",
    "case Job.38.7 MT_preserved":
        "529aac425f6de9812e45780a777eb17e8c32fa1c8baecf473ae53870188a23d6",
    "case Psa.29.1 translation_choice":
        "e71887554aa3a1ccce6482a163419ff49066a27d441ab2927015cdfc1705ce82",
    "case Psa.40.6 LXX_quoted_in_NT":
        "68611e64bf67e423affc66462f945706cda013096b556bf65fa9df6b4d746777",
    "case Psa.82.1 MT_preserved":
        "6fab89dd13c5c4e78a3690d24ade70943541a62bb3bb70c4e7f75ff02fc9bcd7",
    "case Psa.82.6 MT_preserved":
        "bbd5806653df570f97767d24eba4c168689e5518fd4ea0d677562ee535e4a482",
    "case Psa.89.6 translation_choice":
        "88f2881694dcf20e6c2dbbec56195ad60b2e9a7d2dedc9c1a0c0290fe4d8a934",
    "case Dan.4.17 MT_preserved":
        "660b341d560fe487efe317dc31dab73577e501bbfe1a6199478cb03236c18586",
    "case Dan.7.13 MT_preserved":
        "aed7d68ef3e7c77a377384fc1e762d22634184c352a4f195fbe985979e01ca5a",
    "case Zec.3.1 MT_preserved": "6f8a57e241385bcd35327bf89c1c9e3175190c52d21ba24857021e39b2b8fe90",
    "case Zec.3.2 MT_preserved": "730737b61944acae79aeccc4733a863ceb0752d2825da807a45632975d3821f6",
    "hint Heb.10.5 -> Psa.40.6": "d517507f3bba80e7602a96dd20e792cc7e06204e6395f8c1fda98b9044881410",
    "hint Heb.1.6 -> Deu.32.43": "822dde3cb24cb764653ed851eeda9c7707c3bca85ae705a52408eb5de5ab0b8a",
    "theme sons_of_god": "5d186714ea6c292c42a22d495ddefb69f41e9eacc2d4dda0590e4c77978a3235",
    "theme nachash_serpent": "a209d37dd0014781f7c6f02afd63c3cc36946d7a1b2f889ec4ecadc62649ce15",
    "theme cherem_warfare": "068087a709a25d09bbcb0ff9ea3275e4f06232db09e6f81ef9f853d27e38e3c0",
    "theme watchers_tradition": "f336c6397a097e5a9f721190e152bf02bf79bc1371471a601ed0bba5a545e577",
    "content Heiser — Deuteronomy 32:8 and the Sons of God (BibSac paper) / Introduction / The Textual Variant in Deuteronomy 32:8 — Sons of God vs Sons of Israel":
        "932616dd13bf63f90a1bc76ba3f18a3dbf55bae0d63560d21be190f61ac885c4",
    "content Heiser — Deuteronomy 32:8 and the Sons of God (BibSac paper) / Textual Criticism section / Text-Critical Methodology: No A Priori MT Superiority":
        "ed3ef2c15063dc592b3d80a7de02c98c8bb53f6be9280d2a8dd54029ed3c1bfa",
    "content Heiser — collected papers and articles / Elohim FSB article / The Five Uses of Elohim in the Hebrew Bible":
        "9db5d0fac701c56bb359d5cb70aa762838f997ef723dbbe4deff41a8db1ad573",
    "content Heiser — collected papers and articles / Section 2: The Meaning of Elohim / Elohim as a 'Place of Residence' Term — The Key to Psalm 82":
        "8bdb9cc8cd98c32f079497ef9b630c04203b7f40bc066deec7443a943ab4462b",
    "content Heiser — What Is an Elohim? and related articles / What is an Elohim / Elohim Describes a Plane of Existence, Not a Set of Attributes":
        "f1c353fa14e99f444f4b29e3c6383ba9a9671fbbfb11ba1c365e2d692618a4db",
    "content Heiser — What Is an Elohim? and related articles / The Nachash / The Nachash of Eden — A Shining Divine Being, Not a Talking Snake":
        "fc957b3e189fc4a19d4a8cb10e8a7ec0ffaf62f1c3e544f644b8a340501afb03",
    "content Heiser — Naked Bible Podcast / Episode 94 / The Watchers' Sin as the Origin of Evil — Not Adam's Fall Alone":
        "cc65ee33352218a20d9c86aa64ab19ae75e503209797d26f58fea4683b086b93",
    "content Heiser — Naked Bible Podcast / Episode 94 / Demons as Disembodied Spirits of Dead Nephilim — The Second Temple Understanding":
        "54794343f29e047fff7d1f3d4f5b75efdebf8b5020c164e56b0e4aa366da1754",
    "content Heiser — Naked Bible Podcast / Episode 334 / The Nephilim Were Giants — Offspring of the Divine-Human Union":
        "f315b14fe057c4d805d2cc66a4d85c0639bd2ec879d8614707d7435972583b4b",
    "content Heiser — Naked Bible Podcast / Episodes 434-435 / Jude 6 — The Angels Who Left Their Proper Domain Are the Watchers of Genesis 6":
        "c36538976aea8532e47b5074734e370be8a0ed9f5c48378db0326fd3074797fb",
    "content Heiser — Naked Bible Podcast / Episodes 434-435 (cross-reference) / The Azazel/Scapegoat Connection — Leviticus 16 and the Watchers Tradition":
        "adc12d3693b0a1a264a1c16100b17353a1c253c66763ad4e5a8a5eaabd68a2e0",
    "content Burnett — So Shall Your Seed Be (JSPL 5.2, 2015) / Main thesis / Abraham's Star-Like Seed: The Qualitative Reading of Genesis 15:5":
        "428a6d5a799d4117cae4eefa7ba5e10c8d411911da547117fe06003d77fb686a",
    "content Burnett — So Shall Your Seed Be (JSPL 5.2, 2015) / Divine-council frame / Deuteronomy 32:8 and the Inheritance of the Nations":
        "80a19dd7309e31af69fc07cba9591055b2d6eb44607f9a1ca4ede10b6d02e829",
    "ane cosmo_008": "cca0aa9f4a71f7fbbd45c0437b4833c6bab96838e7c2cb08d2f319281b5ee6d6",
    "ane cosmo_009": "2cd59d7262f19746689a0635cde96468424373cc4f52c0d232facd4d2b8bf571",
    "ane cosmo_012": "61aa78767b5c53537c4104b577adb9a254bae2ed98365f1f51a8cf6fd3b5392f",
    "ane relig_008": "504dce0f31399a8ab308ca191fcce0c98df72242294f9686e1f7351e194e880a",
    "ane relig_011": "b828b07cffcbe84c57b39f16cde1338aac2982b550d7e5571b87b4c674df2416",
    "ane relig_013": "f6fbd61fd0fefaf798138cb8140bfd62f65aaab97879169b8025eaec0614b0b7",
    "ane relig_014": "574b3f8219222a9bed1e2359a1c4206d2420b14eb1b4dae51b745ad982e0d493",
    "ane relig_015": "b52a0455b644847f3683f6f102db11ffa60dd322f702ff04d39fdf9534bd4134",
    "ane relig_016": "f7921dd42959791f435b8d23737850ca72fcbc010bd6adc4e2ba6acbabba6f54",
    "ane relig_020": "f82bab2275ae44b1fbe711a383bcdc2d3ed55616e64c5fcd1659ee60bf5c751a",
    "ane relig_021": "46b0a80d5d7218a7ea93b511dda44c321580ee2ef61b780e62e0e6f6563747f1",
    "ane legal_009": "9499a217e9ec46194f11c6c11af2a61d4d2dad24fb0dc1d1ffd2e613d85a5104",
    "ane lit_006": "8b8116b7ad8b0213ad91c64e22ed1dbe5c762575ba1fdebfa693bd98914221f3",
    "ane death_005": "4e59b900fc09e2dd791b4846112cba52489e3b8e1e5d5a9588ff5ad03d692269",
    "ane method_002": "3f9f5f324e1d73e9826fad7ff69807ceac07606cd37cba0945d4cada22381efb",
    "ane method_004": "8edd5c1153e81977627961f5a729354519a5b9bd0ec852944715573a717a00b4",
    "ane method_006": "9b5df06990d89b862e5c7be8cda5bf7f71df52c1afb7c6dcfe072114f67cb836",
    "ane method_007": "a0b69eabae1804fc91ea2c341918a0857ede4512e2974a826f1be906c09c08ee",
    "ane method_008": "e0461f2753ededaab8bd59dbe2d1590c052f07d35e585f5b29bca3f4d330ffe9",
    "link 1 Enoch 1:5 -> Gen 6001-6004": None,
    "link 1 Enoch 1:5 -> Jud 1006-1006": None,
    "link 1 Enoch 1:5 -> 2Pe 2004-2004": None,
    "link 1 Enoch 10:15 -> Gen 6001-6004": None,
    "link 1 Enoch 10:15 -> Jud 1006-1006": None,
    "link 1 Enoch 12:2 -> Gen 6001-6004": None,
    "link 1 Enoch 12:2 -> Jud 1006-1006": None,
    "link 1 Enoch 69:29 -> Dan 7013-7014": None,
    "link 1 Enoch 69:29 -> Mat 25031-25031": None,
    "link 1 Enoch 69:29 -> Mat 19028-19028": None,
    "link 1 Enoch 71:13 -> Dan 7013-7014": None,
}

# --- Row access (standard library only) ----------------------------------------

CASE_COLUMNS = ("reference", "book", "chapter", "verse", "case_key", "significance")
READING_COLUMNS = ("reading_key", "tradition", "text", "original_text", "language")
WITNESS_COLUMNS = (
    "witness", "evidence_type", "reading_support", "approximate_date",
    "source_citation", "source_url",
)
CLAIM_TABLES = {
    "textual_critical_judgments": ("judgment", "attribution", "source_citation", "source_url"),
    "textual_theological_interpretations": (
        "interpretation", "attribution", "source_citation", "source_url",
    ),
    "textual_author_claims": ("author", "claim", "source_citation", "source_url"),
    "textual_translation_decisions": ("translation", "preferred_reading", "rationale"),
}
HINT_COLUMNS = (
    "nt_reference", "nt_display", "nt_book", "ot_reference", "ot_display", "ot_book",
    "follows_lxx", "divergence_type", "divergence_note",
)
LINK_COLUMNS = ("relationship_note", "relation")
NOTES_NAME = "editorial_notes.json"


def digest(rows) -> str | None:
    """A fingerprint of a row set; None for an absent one."""
    if rows is None:
        return None
    canonical = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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


def read_hint(conn: sqlite3.Connection, nt_reference: str, ot_reference: str) -> dict | None:
    """A quotation hint without its id, naming its case by key; None if absent."""
    row = conn.execute(
        "SELECT " + ", ".join(f"h.{column}" for column in HINT_COLUMNS)
        + ", h.variant_case_id, c.reference, c.case_key FROM nt_ot_lxx_quote_hints h "
        "LEFT JOIN textual_variant_cases c ON c.id = h.variant_case_id "
        "WHERE h.nt_reference = ? AND h.ot_reference = ?",
        (nt_reference, ot_reference),
    ).fetchone()
    if row is None:
        return None
    case_id, reference, case_key = row[len(HINT_COLUMNS):]
    if case_id is None:
        variant_case = None
    elif reference is None:
        variant_case = ["missing case id", case_id]
    else:
        variant_case = [reference, case_key]
    return {"values": list(row[:len(HINT_COLUMNS)]), "variant_case": variant_case}


def write_hint(conn: sqlite3.Connection, hint: dict) -> bool:
    """Update a hint's values, linked to its case here; False if that case is missing."""
    case_id = None
    if hint["variant_case"] is not None:
        found = conn.execute(
            "SELECT id FROM textual_variant_cases WHERE reference = ? AND case_key = ?",
            tuple(hint["variant_case"]),
        ).fetchone()
        if found is None:
            return False
        case_id = found[0]
    updates = ", ".join(f"{column} = excluded.{column}" for column in HINT_COLUMNS[2:])
    conn.execute(
        f"INSERT INTO nt_ot_lxx_quote_hints ({', '.join(HINT_COLUMNS)}, variant_case_id) "
        f"VALUES ({', '.join('?' for _ in HINT_COLUMNS)}, ?) "
        f"ON CONFLICT(nt_reference, ot_reference) DO UPDATE SET {updates}, "
        "variant_case_id = excluded.variant_case_id",
        (*hint["values"], case_id),
    )
    return True


# A plain row: (table, key columns, value columns).
ROW_TABLES = {
    "theme": ("theology_themes", ("theme_key",), THEME_COLUMNS),
    "content": ("theology_content", ("source_work", "chapter_or_episode", "title"), CONTENT_COLUMNS),
    "ane": ("ane_entries", ("id",), ANE_COLUMNS),
}


def read_row(conn: sqlite3.Connection, kind: str, key: list) -> dict | None:
    """A row's value columns by name; None if the row is absent (or not unique)."""
    table, key_columns, columns = ROW_TABLES[kind]
    where = " AND ".join(f"{column} IS ?" for column in key_columns)
    rows = conn.execute(
        f"SELECT {', '.join(columns)} FROM {table} WHERE {where}", key
    ).fetchall()
    if len(rows) != 1:
        return None if not rows else {"duplicate rows": len(rows)}
    return dict(zip(columns, rows[0]))


def write_row(conn: sqlite3.Connection, kind: str, key: list, values: dict) -> None:
    table, key_columns, columns = ROW_TABLES[kind]
    where = " AND ".join(f"{column} IS ?" for column in key_columns)
    conn.execute(
        f"UPDATE {table} SET {', '.join(f'{column} = ?' for column in columns)} WHERE {where}",
        (*(values[column] for column in columns), *key),
    )


def passage_id(conn: sqlite3.Connection, corpus: str, reference: str) -> int | None:
    rows = conn.execute(
        "SELECT id FROM ancient_source_passages WHERE corpus = ? AND reference = ?",
        (corpus, reference),
    ).fetchall()
    return rows[0][0] if len(rows) == 1 else None


def read_link(conn: sqlite3.Connection, link: dict) -> dict | None:
    """A link's note and relation; None if absent; a marker if its passage is missing."""
    found = passage_id(conn, link["corpus"], link["reference"])
    if found is None:
        return {"missing passage": link["reference"]}
    row = conn.execute(
        f"SELECT {', '.join(LINK_COLUMNS)} FROM ancient_source_biblical_links "
        "WHERE passage_id = ? AND biblical_book = ? AND sort_start = ? AND sort_end = ?",
        (found, link["book"], link["sort_start"], link["sort_end"]),
    ).fetchone()
    return None if row is None else dict(zip(LINK_COLUMNS, row))


def write_link(conn: sqlite3.Connection, link: dict) -> None:
    conn.execute(
        "INSERT INTO ancient_source_biblical_links "
        "(passage_id, biblical_book, sort_start, sort_end, relationship_note, relation) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            passage_id(conn, link["corpus"], link["reference"]), link["book"],
            link["sort_start"], link["sort_end"], *(link["values"][c] for c in LINK_COLUMNS),
        ),
    )


# --- Source mode -------------------------------------------------------------------


def compute_changes(data_dir: Path) -> dict:
    """The patch: every item's expected fingerprint and corrected rows, from the sources.

    Variant cases and hints come from importing the bundled records with the
    real importers into an empty in-memory database; themes, content, ANE
    entries and links from the parsers the build uses.
    """
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    from import_heiser_content import import_nt_ot_lxx_quote_hints, import_textual_variants
    from ingest_burnett_gage import BURNETT_THEOLOGY

    from study_bible_mcp.corpora import editorial_notes
    from study_bible_mcp.corpora.editorial_notes import load_editorial_notes
    from study_bible_mcp.database import create_schema
    from study_bible_mcp.parsers.ane_context import parse_ane_context_file
    from study_bible_mcp.parsers.heiser import parse_heiser_content_file, parse_themes_file

    heiser = data_dir / "heiser"
    scratch = sqlite3.connect(":memory:")
    try:
        create_schema(scratch)
        import_textual_variants(scratch, heiser / "variants")
        import_nt_ot_lxx_quote_hints(scratch, heiser / "lxx_quote_hints.json")
        cases = [
            {"reference": reference, "case_key": case_key,
             "rows": read_case(scratch, reference, case_key)}
            for reference, case_key in CASES
        ]
        hints = [
            {"nt_reference": nt, "ot_reference": ot, "row": read_hint(scratch, nt, ot)}
            for nt, ot in HINTS
        ]
    finally:
        scratch.close()
    missing = [f"{c['reference']} {c['case_key']}" for c in cases if c["rows"] is None]
    missing += [f"hint {h['nt_reference']} -> {h['ot_reference']}" for h in hints if h["row"] is None]

    themes = {theme["theme_key"]: theme for theme in parse_themes_file(heiser / "themes.json")}
    content = {}
    for path in sorted((heiser / "content").glob("*.json")):
        for entry, _, _ in parse_heiser_content_file(path):
            content[(entry["source_work"], entry["chapter_or_episode"], entry["title"])] = entry
    for entry in BURNETT_THEOLOGY:
        content[(entry["source_work"], entry["chapter_or_episode"], entry["title"])] = entry
    ane = {}
    for path in sorted((data_dir / "ane_context").glob("*.json")):
        for entry, _ in parse_ane_context_file(path):
            ane[entry["id"]] = entry

    rows = []
    for key in THEMES:
        if key not in themes:
            missing.append(f"theme {key}")
            continue
        rows.append({"kind": "theme", "key": [key],
                     "values": {c: themes[key][c] for c in THEME_COLUMNS}})
    for key in CONTENT:
        if key not in content:
            missing.append(f"content {key}")
            continue
        rows.append({"kind": "content", "key": list(key),
                     "values": {c: content[key][c] for c in CONTENT_COLUMNS}})
    for key in ANE:
        if key not in ane:
            missing.append(f"ANE entry {key}")
            continue
        rows.append({"kind": "ane", "key": [key], "values": {c: ane[key][c] for c in ANE_COLUMNS}})

    # Each new link covers one passage, named by its citation. The links come
    # from the committed notes file beside the corpus registry.
    curated = load_editorial_notes(Path(editorial_notes.__file__).with_name(NOTES_NAME))
    links = []
    for corpus, citation, biblical in LINKS:
        matches = [
            link for link in curated.links
            if (link.corpus, link.citation) == (corpus, citation)
            and _same_range(link, biblical)
        ]
        if len(matches) != 1:
            missing.append(f"link {citation} -> {biblical}")
            continue
        link = matches[0]
        links.append({
            "corpus": corpus, "reference": citation, "book": link.book,
            "sort_start": link.chapter * 1000 + link.verse,
            "sort_end": link.end_chapter * 1000 + link.end_verse,
            "values": {"relationship_note": link.note, "relation": link.relation},
        })
    if missing:
        raise SystemExit(f"The sources lack {', '.join(missing)}; nothing was changed")
    for item in (*cases, *hints, *rows, *links):
        item["before"] = BEFORE[_label(item)]
    return {"cases": cases, "hints": hints, "rows": rows, "links": links}


def _same_range(link, biblical: str) -> bool:
    from study_bible_mcp.database import expand_single_chapter_reference, parse_biblical_range

    parsed = parse_biblical_range(expand_single_chapter_reference(biblical))
    return parsed == (link.book, link.chapter, link.verse, link.end_chapter, link.end_verse)


# --- Apply (standard library only) ----------------------------------------------------


def _label(item: dict) -> str:
    if "case_key" in item:
        return f"case {item['reference']} {item['case_key']}"
    if "nt_reference" in item:
        return f"hint {item['nt_reference']} -> {item['ot_reference']}"
    if "kind" in item:
        return f"{item['kind']} {' / '.join(str(part) for part in item['key'])}"
    return f"link {item['reference']} -> {item['book']} {item['sort_start']}-{item['sort_end']}"


def _current(conn: sqlite3.Connection, item: dict):
    if "case_key" in item:
        return read_case(conn, item["reference"], item["case_key"])
    if "nt_reference" in item:
        return read_hint(conn, item["nt_reference"], item["ot_reference"])
    if "kind" in item:
        return read_row(conn, item["kind"], item["key"])
    return read_link(conn, item)


def _after(item: dict):
    if "case_key" in item:
        return item["rows"]
    if "nt_reference" in item:
        return item["row"]
    return item["values"]


def _write(conn: sqlite3.Connection, item: dict) -> str | None:
    """Install one item's corrected rows; return a conflict message, if any."""
    if "case_key" in item:
        write_case(conn, item["rows"])
    elif "nt_reference" in item:
        if not write_hint(conn, item["row"]):
            return f"{_label(item)} links to a case the database lacks"
    elif "kind" in item:
        write_row(conn, item["kind"], item["key"], item["values"])
    else:
        write_link(conn, item)
    return None


REQUIRED_TABLES = (
    "textual_variant_cases", "nt_ot_lxx_quote_hints", "theology_themes", "theology_content",
    "ane_entries", "ancient_source_passages", "ancient_source_biblical_links",
)


def apply_changes(conn: sqlite3.Connection, changes: dict) -> tuple[list[str], list[str]]:
    """Apply a patch in one transaction; return (items replaced, conflicts)."""
    present = {
        row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    lacking = [table for table in REQUIRED_TABLES if table not in present]
    if lacking:
        raise SystemExit(
            f"The database lacks {', '.join(lacking)}; run scripts/upgrade_database.py "
            "first. Nothing was changed"
        )
    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")
    replaced: list[str] = []
    conflicts: list[str] = []
    # Cases first: a hint is linked to its case's id in this database.
    for group in ("cases", "hints", "rows", "links"):
        for item in changes[group]:
            label = _label(item)
            after = digest(_after(item))
            found = _current(conn, item)
            if isinstance(found, dict) and "missing passage" in found:
                conflicts.append(f"{label}: the database has no passage {item['reference']}")
                continue
            current = digest(found)
            if current == after:
                continue
            if current != item["before"]:
                conflicts.append(
                    f"{label} is missing" if current is None
                    else f"{label} holds neither the rows the patch replaces nor its rows"
                )
                continue
            problem = _write(conn, item)
            if problem:
                conflicts.append(problem)
            elif digest(_current(conn, item)) != after:
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

    source = f"the patch {args.apply_patch}" if args.apply_patch else f"the sources in {args.data_dir}"
    counts = {group: len(changes[group]) for group in ("cases", "hints", "rows", "links")}
    total = sum(counts.values())
    print(
        f"{args.db}, from {source}: {counts['cases']} textual-variant cases, "
        f"{counts['hints']} NT quotation hints, {counts['rows']} theme, content and ANE rows, "
        f"{counts['links']} ancient-source links"
    )
    if replaced:
        print(f"   installed {len(replaced)}: {', '.join(replaced)}")
    print(f"   {total - len(replaced)} of {total} already held the corrected rows")
    if args.write_patch:
        print(f"   patch written to {args.write_patch}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
