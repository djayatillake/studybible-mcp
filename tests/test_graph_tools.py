"""The people/places graph tools after the QA fixes.

Covers name resolution (Peter, Pilate, the patriarch Jacob, Mary), the
family-connection search, genealogy output (each relative once, namesakes kept
apart, a bounded diagram), event dates and order, nations tagged as their
ancestor, spouse and God-family repeats, and lookup_name's ordering and
display. Everything runs on a small synthetic database; the ids are
Theographic's, so the curated notes in graph_curated.json apply.
"""

from __future__ import annotations

import json
import re
import sqlite3

import pytest

import study_bible_mcp.server as server
import study_bible_mcp.tools as tools
from study_bible_mcp.database import StudyBibleDB, create_schema
from study_bible_mcp.tools import humanize_tipnr, scripture_span

# (id, name, display_title, surname, also_called, gender, birth_year, death_year)
PEOPLE = [
    ("god_1324", "God", None, None, "LORD,Lord,Father", None, None, None),
    ("adam_78", "Adam", None, None, None, "Male", -4004, -3074),
    ("eve_1231", "Eve", None, None, None, "Female", -4004, None),
    ("seth_2504", "Seth", None, None, None, "Male", -3874, -2962),
    ("terah_2841", "Terah", None, None, None, "Male", -2126, None),
    ("abraham_58", "Abraham", None, None, "Abram", "Male", -1997, -1821),
    ("sarah_2473", "Sarah", None, None, "Sarai", "Female", None, None),
    ("isaac_616", "Isaac", None, None, None, "Male", -1896, -1716),
    ("israel_682", "Israel", "Jacob (Israel)", None, "Israel", "Male", -1836, -1689),
    ("jacob_683", "Jacob", None, None, None, "Male", None, None),
    ("judah_1751", "Judah", "Judah (patriarch)", None, None, "Male", -1755, None),
    ("tamar_2821", "Tamar", None, None, None, "Female", None, None),
    ("pharez_2338", "Pharez", None, None, "Perez", "Male", None, None),
    ("hezron_1516", "Hezron", None, None, None, "Male", None, None),
    ("ram_2393", "Ram", None, None, None, "Male", None, None),
    ("amminadab_234", "Amminadab", None, None, None, "Male", None, None),
    ("levi_1820", "Levi", "Levi (patriarch)", None, None, "Male", None, None),
    ("jochebed_1645", "Jochebed", None, None, None, "Female", None, None),
    ("aaron_1", "Aaron", None, None, None, "Male", None, None),
    ("elisheba_1162", "Elisheba", None, None, None, "Female", None, None),
    ("nahshon_2144", "Nahshon", None, None, None, "Male", None, None),
    ("salmon_2466", "Salmon", None, None, None, "Male", None, None),
    ("boaz_519", "Boaz", None, None, None, "Male", None, None),
    ("ruth_2450", "Ruth", None, None, None, "Female", None, None),
    ("obed_2228", "Obed", None, None, None, "Male", None, None),
    ("jesse_903", "Jesse", None, None, None, "Male", None, None),
    ("eliab_1075", "Eliab", None, None, None, "Male", None, None),
    ("eliab_1073", "Eliab", None, None, None, "Male", None, None),
    ("david_994", "David", None, None, None, "Male", -1085, -1015),
    ("solomon_2762", "Solomon", None, None, None, "Male", -1035, -975),
    ("joseph_1718", "Joseph", None, None, None, "Male", None, None),
    ("joseph_1715", "Joseph", "Joseph (Mary's Husband)", None, None, "Male", None, None),
    ("heli_1484", "Heli", None, None, None, "Male", None, None),
    ("mary_1938", "Mary", "Mary (Mother of Jesus)", None, "mother", "Female", None, None),
    ("mary_1943", "Mary", "Mary Magdalene", "Magdalene", "Magdalene", "Female", None, None),
    ("jesus_905", "Jesus", "Jesus Christ", "Christ", "Lord,Son,Messiah", "Male", -4, 30),
    ("simon_2747", "Simon", None, None, None, "Male", None, None),
    ("peter_2745", "Simon", "Simon Peter", "Peter", "Cephas,Simeon", "Male", None, None),
    ("pilate_2365", "Pontius", "Pontius Pilate", "Pilate", None, "Male", None, None),
    ("moab_2103", "Moab", None, None, "Moabites", "Male", None, None),
    ("melchisedec_1991", "Melchisedec", None, None, "Melchizedek", "Male", None, None),
]

FAMILY = [
    ("god_1324", "adam_78", "father_of"), ("god_1324", "eve_1231", "father_of"),
    ("adam_78", "eve_1231", "partner_of"), ("eve_1231", "adam_78", "partner_of"),
    ("adam_78", "seth_2504", "father_of"), ("seth_2504", "terah_2841", "father_of"),
    ("terah_2841", "abraham_58", "father_of"), ("terah_2841", "sarah_2473", "father_of"),
    ("abraham_58", "sarah_2473", "partner_of"), ("sarah_2473", "abraham_58", "partner_of"),
    ("abraham_58", "isaac_616", "father_of"), ("sarah_2473", "isaac_616", "mother_of"),
    ("isaac_616", "israel_682", "father_of"),
    ("israel_682", "judah_1751", "father_of"), ("israel_682", "levi_1820", "father_of"),
    ("judah_1751", "pharez_2338", "father_of"), ("tamar_2821", "pharez_2338", "mother_of"),
    ("pharez_2338", "hezron_1516", "father_of"), ("hezron_1516", "ram_2393", "father_of"),
    ("ram_2393", "amminadab_234", "father_of"), ("amminadab_234", "nahshon_2144", "father_of"),
    # A shorter way round through a marriage: Levi's line to Aaron, whose wife
    # Elisheba was Nahshon's sister (Exod 6:23)
    ("levi_1820", "jochebed_1645", "father_of"), ("jochebed_1645", "aaron_1", "mother_of"),
    ("aaron_1", "elisheba_1162", "partner_of"), ("elisheba_1162", "nahshon_2144", "sibling_of"),
    ("nahshon_2144", "salmon_2466", "father_of"), ("salmon_2466", "boaz_519", "father_of"),
    ("boaz_519", "obed_2228", "father_of"), ("ruth_2450", "obed_2228", "mother_of"),
    ("boaz_519", "ruth_2450", "partner_of"), ("ruth_2450", "boaz_519", "partner_of"),
    ("obed_2228", "jesse_903", "father_of"), ("jesse_903", "david_994", "father_of"),
    ("jesse_903", "eliab_1075", "father_of"),
    ("david_994", "solomon_2762", "father_of"), ("solomon_2762", "joseph_1718", "father_of"),
    ("joseph_1718", "jacob_683", "father_of"), ("jacob_683", "joseph_1715", "father_of"),
    ("joseph_1715", "jesus_905", "father_of"), ("mary_1938", "jesus_905", "mother_of"),
    ("heli_1484", "mary_1938", "father_of"),
    ("joseph_1715", "mary_1938", "partner_of"), ("mary_1938", "joseph_1715", "partner_of"),
    ("jesus_905", "simon_2747", "sibling_of"),
]

MENTIONS = [
    ("Gen.1.1", "person", "god_1324"),
    ("Gen.14.18", "person", "melchisedec_1991"),
    ("Gen.25.26", "person", "israel_682"), ("Gen.32.28", "person", "israel_682"),
    ("Matt.1.16", "person", "jacob_683"), ("Matt.1.16", "person", "joseph_1715"),
    ("Matt.1.16", "person", "mary_1938"), ("Matt.1.16", "person", "jesus_905"),
    ("Luke.1.27", "person", "mary_1938"), ("Luke.2.5", "person", "mary_1938"),
    ("Mark.16.9", "person", "mary_1943"), ("John.20.18", "person", "mary_1943"),
    ("Matt.4.18", "person", "peter_2745"), ("Matt.16.18", "person", "peter_2745"),
    ("Matt.13.55", "person", "simon_2747"),
    ("Matt.27.2", "person", "pilate_2365"),
    ("1Sam.17.1", "person", "judah_1751"), ("1Sam.17.53", "person", "israel_682"),
    ("1Sam.17.13", "person", "eliab_1075"), ("1Sam.17.28", "person", "eliab_1075"),
    ("1Sam.17.28", "person", "eliab_1073"), ("1Sam.17.13", "person", "jesse_903"),
    ("Ruth.4.3", "person", "moab_2103"),
    ("Ruth.4.12", "person", "judah_1751"), ("Ruth.4.12", "person", "pharez_2338"),
    ("Ruth.4.12", "person", "tamar_2821"),
    ("Ruth.4.13", "person", "boaz_519"), ("Ruth.4.13", "person", "ruth_2450"),
    ("Ruth.4.13", "person", "god_1324"),
    ("Gen.1.1", "event", "e0"),
    ("Josh.18.25", "place", "ramah_972"), ("Judg.4.5", "place", "ramah_972"),
    ("1Sam.7.17", "place", "ramah_975"), ("1Sam.7.17", "event", "9010"),
    *[(f"Luke.2.{v}", "event", "e1") for v in range(1, 8)],
    ("Matt.27.33", "event", "e2"), ("John.19.18", "event", "e2"),
    ("Matt.28.1", "event", "e3"), ("Mark.16.1", "event", "e3"),
    ("Luke.24.1", "event", "e3"), ("John.20.1", "event", "e3"),
]

PLACES = [("bethlehem_218", "Bethlehem", 31.7, 35.2, "City"),
          ("jerusalem_636", "Jerusalem", 31.8, 35.2, "City"),
          ("golgotha_487", "Golgotha", None, None, None),
          ("ramah_972", "Ramah", 31.9, 35.2, "City"), ("ramah_975", "Ramah", 31.8, 35.2, "City")]
# (id, title, astronomical start year, sort_key): inserted out of order
EVENTS = [("e3", "Resurrection and Ascension", 30, 4.0), ("e1", "Birth of Jesus", -3, 2.0),
          ("e0", "Creation of all things", -4003, 1.0), ("e2", "Crucifixion and Burial", 30, 3.0),
          ("9010", "Samuel judges Israel from Ramah", None, 0.5)]
PERSON_EVENTS = [("jesus_905", e) for e in ("e0", "e1", "e2", "e3")] + [("god_1324", "e0")]
EVENT_PLACES = [("e1", "bethlehem_218"), ("e2", "golgotha_487"), ("e3", "jerusalem_636"),
                ("9010", "ramah_975")]

# names rows: (name, type, refs, description, relationships); ACAI: (id, type,
# reference_count, tipnr key, referred_to_as)
NAMES = [
    ("Zechariah", "person", ["1Ch.24.25"], "A Levite (test).", {}),
    ("Zechariah", "person", ["Luk.1.5"], "Father of John the Baptist (test).", {}),
    ("Zechariah", "person", ["Ezr.5.1"], "The prophet (test).", {}),
    ("Mary", "person", ["Act.12.12"], "Mother of John Mark (test).", {}),
    ("Mary", "person", ["Mat.1.16"], "Mother of Jesus (test).", {"parents": ["Heli", "wife_of_Heli"]}),
    ("Mary_Magdalene", "person", ["Mat.27.56"], "Mary of Magdala (test).", {}),
    ("Sergius_Paulus", "person", ["Act.13.7"], "Proconsul of Cyprus (test).", {}),
    ("Barnabas", "person", ["Act.4.36"], "A Levite of Cyprus (test).",
     {"parents": ["father_of_Barnabas"], "spouse": ["a_wife_of_Barnabas"]}),
    ("Ai", "place", ["Jer.49.3"],
     "Ai_2= near Heshbon (Heshbon@Num.21.25-Jer=H2809) (A location only mentioned at Jer.49.3.)", {}),
    ("Passover", "thing", ["Exo.12.11"], "Name of a feastival (test).", {}),
]
ACAI = [
    ("person:Zechariah.12", "person", 1, "Zechariah@1Ch.24.25", []),
    ("person:Zechariah", "person", 9, "Zechariah@Luk.1.5", ["Zacharias"]),
    ("person:Zechariah.24", "person", 6, "Zechariah@Ezr.5.1", []),
    ("person:Mary.5", "person", 1, "Mary@Act.12.12", []),
    ("person:Mary", "person", 20, "Mary@Mat.1.16", []),
    # ACAI drops TIPNR's underscore from this key
    ("person:Marymagdalene", "person", 14, "MaryMagdalene@Mat.27.56", []),
    ("place:Ai.2", "place", 1, "Ai@Jer.49.3", ["Hai", "Ketiv. Qere"]),
]


@pytest.fixture(scope="module")
def graph_file(tmp_path_factory):
    path = tmp_path_factory.mktemp("graph") / "graph.db"
    conn = sqlite3.connect(path)
    create_schema(conn)
    conn.executemany(
        """INSERT INTO graph_people (id, name, display_title, surname, also_called, gender,
               birth_year, death_year) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        PEOPLE,
    )
    conn.executemany("INSERT INTO graph_family_edges VALUES (?, ?, ?)", FAMILY)
    conn.executemany("INSERT INTO graph_verse_mentions VALUES (?, ?, ?)", MENTIONS)
    conn.executemany("INSERT INTO graph_places VALUES (?, ?, ?, ?, ?)", PLACES)
    conn.executemany(
        "INSERT INTO graph_events (id, title, start_year, sort_key) VALUES (?, ?, ?, ?)", EVENTS
    )
    conn.executemany("INSERT INTO graph_person_event_edges VALUES (?, ?)", PERSON_EVENTS)
    conn.executemany("INSERT INTO graph_event_place_edges VALUES (?, ?)", EVENT_PLACES)
    conn.executemany(
        "INSERT INTO names (name, type, refs, description, relationships) VALUES (?, ?, ?, ?, ?)",
        [(n, t, json.dumps(r), d, json.dumps(rel)) for n, t, r, d, rel in NAMES],
    )
    conn.executemany(
        """INSERT INTO acai_entities (id, entity_type, name, reference_count, tipnr_keys,
               referred_to_as) VALUES (?, ?, ?, ?, ?, ?)""",
        [(i, t, i.split(":")[1], c, json.dumps([k]), json.dumps(a)) for i, t, c, k, a in ACAI],
    )
    conn.commit()
    conn.close()
    return path


@pytest.fixture
async def db(graph_file, monkeypatch):
    database = StudyBibleDB(graph_file)
    await database.connect()
    monkeypatch.setattr(server, "db", database)
    yield database
    await database.close()


async def call(tool: str, /, **arguments) -> str:
    response = await server.call_tool(tool, arguments)
    output = response[0].text
    assert not output.startswith("Error:"), output
    return output


# ---------------------------------------------------------------------------
# Which person a name means
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("query", "heading"),
    [
        ("Peter", "Simon Peter"),  # a surname, not the name
        ("Simon Peter", "Simon Peter"),
        ("Simon", "Simon Peter"),  # the most mentioned Simon
        ("Jacob", "Jacob (Israel)"),  # the patriarch, stored as Israel
        ("Israel", "Jacob (Israel)"),
        ("Mary", "Mary (Mother of Jesus)"),
        ("Mary Magdalene", "Mary Magdalene"),
        ("mary_1943", "Mary Magdalene"),  # an id chooses exactly
        ("Pontius Pilate", "Pontius Pilate"),
    ],
)
async def test_names_resolve_to_the_person_meant(db, query, heading):
    output = await call("explore_genealogy", person=query)
    assert output.startswith(f"## Genealogy of {heading}\n")


async def test_the_choice_among_namesakes_is_stated(db):
    mary = await call("explore_person_events", person="Mary")
    assert mary.startswith("## Timeline of Mary (Mother of Jesus)")
    assert ("*Showing Mary (Mother of Jesus) (mary_1938), the most mentioned of 2 people matching "
            "'Mary'; others (pass an id to choose): Mary Magdalene (mary_1943).*") in mary
    jacob = await call("explore_genealogy", person="Jacob")
    assert "others (pass an id to choose): Jacob (jacob_683).*" in jacob
    # Aliases are not rivals: Jesus is not Joshua, nor the Lord God
    assert "the most mentioned" not in await call("explore_genealogy", person="Jesus")
    assert "*'Melchizedek' is listed as Melchisedec.*" in await call(
        "explore_genealogy", person="Melchizedek"
    )


async def test_pilate_is_found_by_surname(db):
    output = await call("find_connection", person1="Pilate", person2="Jesus")
    assert output.startswith("## Connection: Pontius Pilate → Jesus Christ")
    assert "No family connection between them is recorded" in output


# ---------------------------------------------------------------------------
# find_connection
# ---------------------------------------------------------------------------


async def test_connection_prefers_descent_to_a_shorter_way_through_marriage(db):
    output = await call("find_connection", person1="Abraham", person2="David")
    assert "Abraham is an ancestor of David, 13 generations back." in output
    assert "→ Judah (patriarch) → Pharez →" in output
    assert "Elisheba" not in output and "Aaron" not in output


async def test_connection_has_no_depth_cap(db):
    # 21 generations: beyond the old search's cap of 15
    output = await call("find_connection", person1="Adam", person2="Jesus")
    assert "Adam is an ancestor of Jesus Christ, 21 generations back." in output
    assert "→ Joseph (Mary's Husband) → Jesus Christ (each a parent of the next)" in output
    assert "legal father: Jesus was conceived by the Holy Spirit" in output
    assert "```mermaid" not in output  # too long to draw usefully
    upward = await call("find_connection", person1="Jesus", person2="David")
    assert "Jesus Christ is a descendant of David, 5 generations down." in upward


async def test_connection_same_person_and_never_through_god(db):
    same = await call("find_connection", person1="David", person2="David")
    assert same == "## Connection: David → David\n\n'David' and 'David' are the same person: David.\n"
    # Seth's mother is not recorded: the link to Eve is through Adam's marriage,
    # not 'son of Adam, son of God, father of Eve'
    output = await call("find_connection", person1="Seth", person2="Eve")
    assert "- Seth → Adam (a child of the next)\n- Adam — Eve (spouses)" in output
    assert "God" not in output


async def test_connection_names_the_common_ancestor(db):
    output = await call("find_connection", person1="Judah", person2="Levi")
    assert "Judah (patriarch) — Levi (patriarch)" not in output  # no sibling edge recorded
    assert "They share the ancestor Jacob (Israel): Judah (patriarch) is 1 generation below, Levi (patriarch) 1." in output


# ---------------------------------------------------------------------------
# explore_genealogy
# ---------------------------------------------------------------------------


async def test_genealogy_lists_each_ancestor_once(db):
    output = await call("explore_genealogy", person="Isaac", direction="ancestors", generations=10)
    # Terah is Abraham's and Sarah's father: one line, both children
    assert output.count("**Terah**") == 1
    assert "**Terah** (father of Abraham and Sarah; b. c. 2126 BC)" in output
    assert output.count("**God**") == 1
    assert "- Generation 5: **God** (father of Adam)" in output


async def test_genealogy_diagram_keys_namesakes_by_id(db):
    output = await call("explore_genealogy", person="Jesus", direction="ancestors", generations=4)
    # Two Josephs (father and great-grandfather) stay two nodes
    assert 'n_joseph_1715["Joseph"] -->|father| n_jesus_905' in output
    assert 'n_joseph_1718["Joseph"] -->|father| n_jacob_683' in output
    for parent, child in re.findall(r"(n_\w+?)(?:\[[^\]]*\])? -->\|\w+\| (n_\w+)", output):
        assert parent != child
    # The legal father, and the traditional reading of Luke 3:23
    assert "**Joseph** (father of Jesus; legal father: Jesus was conceived" in output
    assert "**Heli** (father of Mary; a traditional reading of Luke 3:23" in output


async def test_genealogy_descendants_draw_every_generation_with_child_labels(db):
    output = await call("explore_genealogy", person="Isaac", direction="descendants", generations=3)
    assert "- Generation 1: **Israel** (son of Isaac; b. c. 1836 BC)" in output
    assert "**Pharez** (son of Judah)" in output and "**Jochebed** (son of Levi)" not in output
    assert "**Jochebed** (child of Levi)" in output or "**Jochebed** (daughter of Levi)" in output
    assert "n_judah_1751 -->|father| n_pharez_2338" in output  # third generation drawn


async def test_genealogy_bounds_and_spouses(db, monkeypatch):
    monkeypatch.setattr(tools, "MERMAID_MAX_NODES", 10)
    capped = await call("explore_genealogy", person="Jesus", direction="ancestors", generations=99)
    assert "*Showing 40 generations, the most this tool traces.*" in capped
    assert "*No diagram: too many people to draw" in capped
    abraham = await call("explore_genealogy", person="Abraham")
    assert "**Spouse(s)**: Sarah\n" in abraham  # stored from both sides, listed once


# ---------------------------------------------------------------------------
# Events: dates, order, passages
# ---------------------------------------------------------------------------


async def test_person_events_dates_order_and_passages(db):
    output = await call("explore_person_events", person="Jesus")
    assert re.findall(r"^- \*\*(.+?)\*\*", output, re.MULTILINE) == [
        "Creation of all things", "Birth of Jesus", "Crucifixion and Burial",
        "Resurrection and Ascension",
    ]
    assert "- **Creation of all things** (c. 4004 BC) — Gen 1:1\n" in output
    assert "- **Birth of Jesus** (c. 4 BC) — Bethlehem; Luke 2:1–7\n" in output
    assert "- **Crucifixion and Burial** (c. AD 30) — Golgotha; Matt 27:33; also John\n" in output
    assert "Jerusalem; Matt 28:1; also Mark, Luke, John" in output
    assert "Theographic chronology" in output
    assert "```mermaid" not in output


def test_scripture_span():
    assert scripture_span(["Gen.22.3", "Gen.22.1", "Gen.22.19"]) == "Gen 22:1–19"
    assert scripture_span(["Exod.4.17", "Exod.3.1"]) == "Exod 3:1–4:17"
    assert scripture_span(["1Sam.16.13"]) == "1 Sam 16:13"
    assert scripture_span(["John.12.12", "Matt.21.1", "Mark.11.1", "Luke.19.29", "Acts.1.1"]) == (
        "Matt 21:1; also Mark, Luke, John and others"
    )
    assert scripture_span(["Bogus.1.1"]) == ""


# ---------------------------------------------------------------------------
# people_in_passage and graph_enriched_search
# ---------------------------------------------------------------------------


async def test_people_in_passage_lists_nations_apart_and_namesakes_once(db):
    output = await call("people_in_passage", reference="1 Samuel 17")
    people = output.split("### Nations and tribes")[0]
    assert "**Israel**" not in people and "**Judah**" not in people
    assert "### Nations and tribes\n*(tagged in the source as their ancestor)*\n- **Israel**\n- **Judah**" in output
    assert "- **Eliab (eliab_1073)**\n- **Eliab (eliab_1075)**" in output

    ruth = await call("people_in_passage", reference="Ruth 4")
    # Ruth 4:12 names Judah with Perez and Tamar: the patriarch, not the tribe
    assert "- **Judah**" in ruth.split("### Nations and tribes")[0]
    assert "### Nations and tribes\n*(tagged in the source as their ancestor)*\n- **Moab**" in ruth


async def test_enriched_search_family_lines(db):
    creation = await call("graph_enriched_search", reference="Genesis 1:1")
    assert "**God**" in creation and "Children: Adam" not in creation
    genealogy = await call("graph_enriched_search", reference="Matthew 1:16")
    assert "**Jesus**\n  Parents: Joseph (legal father), Mary" in genealogy
    ruth = await call("graph_enriched_search", reference="Ruth 4:13")
    assert "Spouse: Ruth |" in ruth and "Ruth, Ruth" not in ruth
    assert "Spouse: Boaz |" in ruth


# ---------------------------------------------------------------------------
# lookup_name
# ---------------------------------------------------------------------------


def _headings(output: str) -> list[str]:
    return re.findall(r"^### (.+)$", output, re.MULTILINE)


async def test_lookup_name_puts_the_best_known_first(db):
    output = await call("lookup_name", name="Zechariah", limit=3)
    assert [line for line in output.splitlines() if "(test)" in line] == [
        "Father of John the Baptist (test).", "The prophet (test).", "A Levite (test).",
    ]
    mary = await call("lookup_name", name="Mary", limit=3)
    # Mary Magdalene is a Mary; ACAI's key for her lacks TIPNR's underscore
    assert _headings(mary) == ["Mary", "Mary Magdalene", "Mary"]
    assert mary.index("Mother of Jesus (test).") < mary.index("Mary of Magdala") < mary.index(
        "Mother of John Mark")
    assert "**Referenced in**: 14 verses" in mary


async def test_lookup_name_multi_word_names_and_readable_ids(db):
    assert _headings(await call("lookup_name", name="Mary Magdalene")) == ["Mary Magdalene"]
    assert _headings(await call("lookup_name", name="Sergius Paulus")) == ["Sergius Paulus"]
    barnabas = await call("lookup_name", name="Barnabas")
    assert "- Parents: father of Barnabas\n- Spouse: a wife of Barnabas" in barnabas
    mary = await call("lookup_name", name="Mary", limit=3)
    assert "- Parents: Heli, wife of Heli" in mary
    ai = await call("lookup_name", name="Ai", type="place")
    assert "Ai (2), near Heshbon (Heshbon) (A location" in ai
    assert "**Also known as**: Hai\n" in ai and "Ketiv" not in ai


async def test_lookup_name_types_and_hint(db):
    assert _headings(await call("lookup_name", name="Passover", type="thing")) == ["Passover"]
    assert await call("lookup_name", name="Passover", type="person") == "No entries found for 'Passover'."
    typed = await call("lookup_name", name="Zechariah", type="person", limit=1)
    assert "*Showing 1 of 3 matching names; raise limit (at most 20) to see more.*" in typed
    untyped = await call("lookup_name", name="Zechariah", limit=1)
    assert "set type or raise limit" in untyped


def test_humanize_tipnr():
    assert humanize_tipnr("Jerusalem_wives") == "Jerusalem wives"
    assert humanize_tipnr("Etam_2= near Ain_2 (Ain@Jos.15.32-Neh=H5871H)") == "Etam (2), near Ain (2) (Ain)"


async def test_explore_place_prefers_the_namesake_with_events_and_names_the_others(db):
    output = await call("explore_place", place="Ramah")
    assert output.startswith(
        "## Ramah\n\n*2 places are called Ramah; showing ramah_975. Others: ramah_972 (0 events, "
        "2 verses). Pass an id to choose another.*\n"
    )
    assert "- **Samuel judges Israel from Ramah** — 1 Sam 7:17\n" in output
    chosen = await call("explore_place", place="ramah_972")
    assert "No detailed history found" in chosen and "places are called" not in chosen
