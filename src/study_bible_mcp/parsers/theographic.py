"""Theographic Bible Metadata: the graph_* rows a build imports.

``build_graph`` reads the Theographic CSVs (People, Places, Events,
PeopleGroups) and returns every graph table's rows, with the curated
corrections and supplementary events of ``graph_curated.json`` applied, so
that scripts/import_theographic.py (a fresh build) and
scripts/repair_theographic_graph.py (an existing database) write the same
rows.

Two things about Theographic's data that the rows account for:

- Event years are astronomical (year 0 is 1 BC: the birth of Jesus, 4 BC, is
  -3), while people's birth and death years count BC directly (Jesus: -4).
  ``graph_events.start_year`` keeps the astronomical year; the tools convert.
  Some events carry an ISO date ('0030-04-07'), which is read as its year.
- Theographic's sortKey is the year plus the position of the first verse, so
  within one year the Gospels sort Matthew, Mark, Luke, John rather than in
  time. ``sort_key`` here is a chronological rank instead: by year, then by
  Theographic's own predecessor chain (each event names the one before it),
  then by the first Scripture reference. An undated event takes its
  predecessor's year, or failing that the year of the dated event before it
  in Scripture order.
"""

from __future__ import annotations

import csv
import heapq
import json
import math
import re
from pathlib import Path

CURATED_PATH = Path(__file__).with_name("graph_curated.json")

# Theographic's book codes, in canonical order.
BOOKS = (
    "Gen", "Exod", "Lev", "Num", "Deut", "Josh", "Judg", "Ruth", "1Sam", "2Sam",
    "1Kgs", "2Kgs", "1Chr", "2Chr", "Ezra", "Neh", "Esth", "Job", "Ps", "Prov",
    "Eccl", "Song", "Isa", "Jer", "Lam", "Ezek", "Dan", "Hos", "Joel", "Amos",
    "Obad", "Jonah", "Mic", "Nah", "Hab", "Zeph", "Hag", "Zech", "Mal",
    "Matt", "Mark", "Luke", "John", "Acts", "Rom", "1Cor", "2Cor", "Gal", "Eph",
    "Phil", "Col", "1Thess", "2Thess", "1Tim", "2Tim", "Titus", "Phlm", "Heb", "Jas",
    "1Pet", "2Pet", "1John", "2John", "3John", "Jude", "Rev",
)
BOOK_INDEX = {book: index for index, book in enumerate(BOOKS)}

TABLE_COLUMNS = {
    "graph_people": (
        "id", "name", "also_called", "gender", "birth_year", "death_year",
        "birth_place_id", "death_place_id", "description", "display_title", "surname",
    ),
    "graph_places": ("id", "name", "latitude", "longitude", "feature_type"),
    "graph_events": ("id", "title", "start_year", "duration", "sort_key"),
    "graph_people_groups": ("name", "members"),
    "graph_family_edges": ("from_person_id", "to_person_id", "relationship_type"),
    "graph_person_event_edges": ("person_id", "event_id"),
    "graph_event_place_edges": ("event_id", "place_id"),
    "graph_verse_mentions": ("verse_ref", "entity_type", "entity_id"),
    "graph_person_group_edges": ("person_id", "group_name"),
}
# The columns that identify a row (the primary key; every column where none).
TABLE_KEYS = {
    "graph_people": ("id",),
    "graph_places": ("id",),
    "graph_events": ("id",),
    "graph_people_groups": ("name",),
    **{table: columns for table, columns in TABLE_COLUMNS.items()
       if table not in ("graph_people", "graph_places", "graph_events", "graph_people_groups")},
}

_YEAR_RE = re.compile(r"^(-?)(\d+)(?:-(\d{1,2})(?:-(\d{1,2}))?)?$")
_VERSE_RE = re.compile(r"^([1-3]?[A-Za-z]+)\.(\d+)\.(\d+)$")
_RANGE_RE = re.compile(r"^([1-3]?[A-Za-z]+)\.(\d+)\.(\d+)-(\d+)$")


class CuratedDataError(ValueError):
    """A curated correction no longer matches the source it corrects."""


def load_curated(path: Path | None = None) -> dict:
    with open(path or CURATED_PATH, encoding="utf-8") as handle:
        return json.load(handle)


def read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def split_field(value: str | None) -> list[str]:
    """A comma-separated field as a list, without empties."""
    if not value or not value.strip():
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def safe_int(value: str | None) -> int | None:
    if not value or not value.strip():
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def safe_float(value: str | None) -> float | None:
    if not value or not value.strip():
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_date(value: str | None) -> tuple[int | None, int, int]:
    """(astronomical year, month, day) of a Theographic startDate; 0 where not given.

    '-1895' -> (-1895, 0, 0); '0030-04-07' -> (30, 4, 7); '0029-10-9' -> (29, 10, 9).
    """
    match = _YEAR_RE.match((value or "").strip())
    if not match:
        return None, 0, 0
    sign, year, month, day = match.groups()
    return int(sign + year), int(month or 0), int(day or 0)


def unquote_title(value: str | None) -> str:
    """A predecessor title as written in the CSV ('"Apostles arrested, put on trial"')."""
    title = (value or "").strip()
    if len(title) >= 2 and title[0] == title[-1] == '"':
        title = title[1:-1].replace('""', '"')
    return title.strip()


def verse_position(ref: str) -> tuple[int, int, int] | None:
    """(book index, chapter, verse) of a Theographic verse reference, or None."""
    match = _VERSE_RE.match(ref.strip())
    if not match or match.group(1) not in BOOK_INDEX:
        return None
    return BOOK_INDEX[match.group(1)], int(match.group(2)), int(match.group(3))


def first_position(refs: list[str]) -> tuple[int, int, int] | None:
    positions = [pos for pos in map(verse_position, refs) if pos]
    return min(positions) if positions else None


def expand_verses(ranges: list[str]) -> list[str]:
    """['Gen.22.1-3', 'Gen.23.1'] -> ['Gen.22.1', 'Gen.22.2', 'Gen.22.3', 'Gen.23.1']."""
    verses = []
    for item in ranges:
        match = _RANGE_RE.match(item)
        if match:
            book, chapter, start, end = match.groups()
            if int(end) < int(start):
                raise CuratedDataError(f"Reversed verse range {item!r}")
            verses.extend(f"{book}.{chapter}.{v}" for v in range(int(start), int(end) + 1))
        elif verse_position(item):
            verses.append(item)
        else:
            raise CuratedDataError(f"Not a Theographic verse or range: {item!r}")
        if not verse_position(verses[-1]):
            raise CuratedDataError(f"Unknown book in {item!r}")
    return verses


def chronological_order(events: list[dict]) -> list[str]:
    """Event ids in chronological order.

    Each event is a dict with ``id``, ``year`` (astronomical, or None),
    ``month`` and ``day`` (0 where unknown), ``preds`` (ids of the events
    before it) and ``pos`` (first verse position, or None). Events sort by
    year, then by the predecessor chain, then by date within the year and
    first reference. An undated event takes the latest year among its
    predecessors, or else that of the last dated event before it in
    Scripture order.
    """
    by_id = {event["id"]: event for event in events}
    no_pos = (len(BOOKS), 0, 0)

    def pos(event: dict) -> tuple[int, int, int]:
        return event["pos"] or no_pos

    dated = sorted((pos(e), e["year"]) for e in events if e["year"] is not None)
    years: dict[str, int] = {}

    def year_of(event_id: str, seen: frozenset = frozenset()) -> int:
        if event_id in years:
            return years[event_id]
        event = by_id[event_id]
        year = event["year"]
        if year is None:
            inherited = [year_of(p, seen | {event_id}) for p in event["preds"]
                         if p in by_id and p not in seen and p != event_id]
            if inherited:
                year = max(inherited)
            else:
                before = [y for p, y in dated if p <= pos(event)]
                year = before[-1] if before else (dated[0][1] if dated else 0)
        years[event_id] = year
        return year

    def key(event_id: str) -> tuple:
        event = by_id[event_id]
        numeric = int(event_id) if event_id.isdigit() else math.inf
        return (year_of(event_id), event["month"], event["day"], pos(event), numeric, event_id)

    preds = {e["id"]: {p for p in e["preds"] if p in by_id and p != e["id"]} for e in events}
    successors: dict[str, set[str]] = {event_id: set() for event_id in by_id}
    for event_id, before in preds.items():
        for p in before:
            successors[p].add(event_id)
    waiting = {event_id: len(before) for event_id, before in preds.items()}
    heap = [(key(i), i) for i, n in waiting.items() if n == 0]
    heapq.heapify(heap)
    rank: dict[str, int] = {}
    while len(rank) < len(by_id):
        if not heap:  # a cycle: release its earliest event
            stuck = min((i for i in by_id if i not in rank), key=key)
            waiting[stuck] = 0
            heap = [(key(stuck), stuck)]
        _, event_id = heapq.heappop(heap)
        if event_id in rank:
            continue
        rank[event_id] = len(rank)
        for successor in sorted(successors[event_id]):
            if successor in rank:
                continue
            waiting[successor] -= 1
            if waiting[successor] == 0:
                heapq.heappush(heap, (key(successor), successor))
    return sorted(by_id, key=lambda i: (year_of(i), rank[i]))


def _check(kind: str, ident: str, field: str, current, correction: dict) -> bool:
    """Whether to apply ``correction`` to ``current``: True if it still holds the
    corrected value's source, False if the source now has the corrected value."""
    if current == correction["from"]:
        return True
    if current == correction["to"]:
        return False
    raise CuratedDataError(
        f"{kind} {ident} {field} is {current!r}, but graph_curated.json corrects "
        f"{correction['from']!r} to {correction['to']!r}; review the correction"
    )


def build_graph(csv_dir: Path, curated: dict | None = None) -> dict[str, list[tuple]]:
    """Every graph table's rows, as tuples in TABLE_COLUMNS order."""
    curated = load_curated() if curated is None else curated
    theo = curated["theographic"]
    people_rows = read_csv(csv_dir / "People.csv")
    place_rows = read_csv(csv_dir / "Places.csv")
    event_rows = read_csv(csv_dir / "Events.csv")
    group_rows = read_csv(csv_dir / "PeopleGroups.csv")

    # People (a later duplicate id replaces an earlier one, as INSERT OR REPLACE did)
    people: dict[str, dict] = {}
    for row in people_rows:
        person_id = row.get("personLookup", "").strip()
        name = row.get("name", "").strip() or row.get("displayTitle", "").strip()
        if not person_id or not name:
            continue
        display = row.get("displayTitle", "").strip()
        people[person_id] = {
            "id": person_id,
            "name": name,
            "also_called": row.get("alsoCalled", "").strip() or None,
            "gender": row.get("gender", "").strip() or None,
            "birth_year": safe_int(row.get("birthYear", "")),
            "death_year": safe_int(row.get("deathYear", "")),
            "birth_place_id": row.get("birthPlace", "").strip() or None,
            "death_place_id": row.get("deathPlace", "").strip() or None,
            "description": row.get("dictText", "").strip() or None,
            "display_title": display if display and display != name else None,
            "surname": row.get("surname", "").strip() or None,
        }
    for fix in theo["people"]:
        person = people.get(fix["id"])
        if person is None:
            raise CuratedDataError(f"graph_curated.json corrects unknown person {fix['id']}")
        if _check("Person", fix["id"], fix["field"], person[fix["field"]], fix):
            person[fix["field"]] = fix["to"]

    places: dict[str, dict] = {}
    for row in place_rows:
        place_id = row.get("placeLookup", "").strip()
        name = row.get("displayTitle", "").strip() or row.get("kjvName", "").strip()
        if not place_id or not name:
            continue
        places[place_id] = {
            "id": place_id,
            "name": name,
            "latitude": safe_float(row.get("openBibleLat", "")) or safe_float(row.get("latitude", "")),
            "longitude": safe_float(row.get("openBibleLong", "")) or safe_float(row.get("longitude", "")),
            "feature_type": row.get("featureType", "").strip() or None,
        }
    for fix in theo["places"]:
        place = places.get(fix["id"])
        if place is None:
            raise CuratedDataError(f"graph_curated.json corrects unknown place {fix['id']}")
        if _check("Place", fix["id"], fix["field"], place[fix["field"]], fix):
            place[fix["field"]] = fix["to"]

    # Family edges, in insertion order without duplicates (INSERT OR IGNORE)
    family: dict[tuple, None] = {}
    for row in people_rows:
        person_id = row.get("personLookup", "").strip()
        if not person_id:
            continue
        for father in split_field(row.get("father", "")):
            family[(father, person_id, "father_of")] = None
        for mother in split_field(row.get("mother", "")):
            family[(mother, person_id, "mother_of")] = None
        for partner in split_field(row.get("partners", "")):
            family[(person_id, partner, "partner_of")] = None
        for sibling in split_field(row.get("siblings", "")):
            if person_id < sibling:
                family[(person_id, sibling, "sibling_of")] = None

    # Events
    events: dict[str, dict] = {}
    titles: dict[str, str] = {}
    for row in event_rows:
        event_id = row.get("eventID", "").strip()
        title = row.get("title", "").strip()
        if not event_id or not title:
            continue
        year, month, day = parse_date(row.get("startDate"))
        sort_key = safe_float(row.get("sortKey"))
        verses = split_field(row.get("verses", ""))
        events[event_id] = {
            "id": event_id,
            "title": title,
            "start_year": year,
            "year": year if year is not None else (math.floor(sort_key) if sort_key is not None else None),
            "month": month,
            "day": day,
            "duration": row.get("duration", "").strip() or None,
            "predecessor": unquote_title(row.get("predecessor")),
            "verses": verses,
            "participants": split_field(row.get("participants", "")),
            "locations": split_field(row.get("locations", "")),
        }
        titles[title] = event_id
    for event in events.values():
        pred = titles.get(event["predecessor"])
        event["preds"] = [pred] if pred else []

    for fix in theo["events"]:
        event = events.get(fix["id"])
        if event is None:
            raise CuratedDataError(f"graph_curated.json corrects unknown event {fix['id']}")
        if _check("Event", fix["id"], fix["field"], event[fix["field"]], fix):
            event[fix["field"]] = fix["to"]
            if fix["field"] == "start_year":
                event["year"] = fix["to"]
    for fix in theo["event_predecessors"]:
        event = events.get(fix["id"])
        if event is None or fix["to"] not in events:
            raise CuratedDataError(f"graph_curated.json reorders unknown event {fix['id']}")
        current = event["preds"][0] if event["preds"] else None
        if _check("Event", fix["id"], "predecessor", current, fix):
            event["preds"] = [fix["to"]]
    for fix in theo["event_places"]:
        event = events.get(fix["event"])
        if event is None or (fix.get("add") and fix["add"] not in places):
            raise CuratedDataError(f"graph_curated.json moves unknown event or place {fix}")
        if fix.get("remove"):
            if fix["remove"] in event["locations"]:
                event["locations"] = [p for p in event["locations"] if p != fix["remove"]]
            elif fix.get("add") not in event["locations"]:
                raise CuratedDataError(f"Event {fix['event']} is not at {fix['remove']}: {fix}")
        if fix.get("add") and fix["add"] not in event["locations"]:
            event["locations"].append(fix["add"])

    for extra in theo["supplement_events"]:
        event_id = extra["id"]
        if event_id in events:
            raise CuratedDataError(f"Supplementary event id {event_id} is already a Theographic event")
        unknown = ([p for p in extra["participants"] if p not in people]
                   + [p for p in extra["locations"] if p not in places]
                   + [p for p in extra.get("after", []) if p not in events])
        if unknown:
            raise CuratedDataError(f"Supplementary event {event_id} names unknown ids {unknown}")
        events[event_id] = {
            "id": event_id,
            "title": extra["title"],
            "start_year": extra.get("start_year"),
            "year": extra.get("start_year"),
            "month": 0,
            "day": 0,
            "duration": extra.get("duration"),
            "preds": list(extra.get("after", [])),
            "verses": expand_verses(extra["verses"]),
            "participants": list(extra["participants"]),
            "locations": list(extra["locations"]),
        }
    removed = {(fix["verse_ref"], fix["entity_type"], fix["entity_id"])
               for fix in theo["verse_mentions_remove"]}
    for event in events.values():
        event["verses"] = [ref for ref in event["verses"] if (ref, "event", event["id"]) not in removed]
        event["pos"] = first_position(event["verses"])
    order = chronological_order(list(events.values()))
    for rank, event_id in enumerate(order, start=1):
        events[event_id]["sort_key"] = float(rank)

    person_events: dict[tuple, None] = {}
    event_places: dict[tuple, None] = {}
    for event in events.values():
        for person_id in event["participants"]:
            person_events[(person_id, event["id"])] = None
        for place_id in event["locations"]:
            event_places[(event["id"], place_id)] = None

    # Verse mentions, without duplicates
    mentions: dict[tuple, None] = {}
    for row in people_rows:
        person_id = row.get("personLookup", "").strip()
        if person_id:
            for ref in split_field(row.get("verses", "")):
                mentions[(ref, "person", person_id)] = None
    for event in events.values():
        for ref in event["verses"]:
            mentions[(ref, "event", event["id"])] = None
    for row in place_rows:
        place_id = row.get("placeLookup", "").strip()
        if place_id:
            for ref in split_field(row.get("verses", "")):
                mentions[(ref, "place", place_id)] = None
    for key in removed:
        mentions.pop(key, None)

    groups: dict[str, str] = {}
    group_edges: dict[tuple, None] = {}
    for row in group_rows:
        group_name = row.get("groupName", "").strip()
        if not group_name:
            continue
        members = row.get("members", "").strip()
        groups[group_name] = members
        for member in split_field(members):
            group_edges[(member, group_name)] = None

    def rows(table: str, records) -> list[tuple]:
        columns = TABLE_COLUMNS[table]
        return [tuple(record[c] for c in columns) for record in records]

    return {
        "graph_people": rows("graph_people", people.values()),
        "graph_places": rows("graph_places", places.values()),
        "graph_events": rows("graph_events", events.values()),
        "graph_people_groups": list(groups.items()),
        "graph_family_edges": list(family),
        "graph_person_event_edges": list(person_events),
        "graph_event_place_edges": list(event_places),
        "graph_verse_mentions": list(mentions),
        "graph_person_group_edges": list(group_edges),
    }
