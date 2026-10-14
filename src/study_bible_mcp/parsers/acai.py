"""
Parser for ACAI (Aquifer Comprehensive AI-powered Bible Annotations) entity files.

ACAI provides per-entity JSON files organized by type:
- people/ (3,426 person entities)
- places/
- groups/
- keyterms/

Each entity file contains structured data including:
- Identity: name, gender, type, description
- Relationships: family (father, mother, partners, offspring, siblings)
- References: verse-level annotations, speech attributions
- Localization: multilingual labels and descriptions

Some annotations are attached to the wrong entity; the curated corrections
in graph_curated.json ("acai") put them right (``apply_acai_corrections``).
"""

import json
import re
from collections.abc import Iterator
from pathlib import Path

# The entity directories, in the order a build imports them
ACAI_TYPES = ("people", "places", "groups", "keyterms")
# acai_entities columns that hold a JSON list; a curated correction gives them as lists
JSON_FIELDS = (
    "roles", "partners", "offspring", "siblings", "referred_to_as", "key_references", "tipnr_keys",
)
CORRECTABLE_FIELDS = (
    "name", "gender", "description", "father_id", "mother_id",
    "reference_count", "speeches_count", *JSON_FIELDS,
)


class CuratedAcaiError(ValueError):
    """A curated ACAI correction no longer matches the source it corrects."""


def parse_acai_dir(acai_dir: Path, on_error=None) -> dict[str, dict]:
    """Every entity under acai_dir, by id, as parse_acai_entities yields them.

    A later duplicate id replaces an earlier one, as the build's INSERT OR
    REPLACE does. A file that fails to parse is passed to ``on_error(path,
    error)`` if given, and otherwise raises.
    """
    entities: dict[str, dict] = {}
    for entity_type in ACAI_TYPES:
        for path in sorted((acai_dir / entity_type).glob("*.json")):
            try:
                parsed = list(parse_acai_entities(path, entity_type))
            except Exception as error:
                if on_error is None:
                    raise
                on_error(path, error)
                continue
            for entity in parsed:
                entities[entity["id"]] = entity
    return entities


def field_value(entity: dict, field: str):
    """A parsed entity's field as a correction gives it: JSON lists decoded."""
    value = entity.get(field)
    return json.loads(value) if field in JSON_FIELDS and value is not None else value


def apply_acai_corrections(
    entities: dict[str, dict], corrections: list[dict], require_all: bool = False
) -> dict[str, dict]:
    """Apply the curated corrections of graph_curated.json ("acai") to parsed entities.

    ACAI attaches some of its annotations to the wrong entity: the Ramahs'
    labels and descriptions are rotated against their own references and
    TIPNR keys, and the patriarch Judah is 'also known as' David. Each
    correction names an entity ('id'), a field (an acai_entities column; a
    JSON list column is given as a list), the value the source has ('from')
    and the corrected value ('to'), with the reason. 'source', where given,
    names the entity whose own value of that field 'to' is, so a correction
    moves ACAI's text to the entity it describes and never brings in new text.

    An entity already holding 'to' is left alone. One holding neither, a
    'source' that no longer holds 'to', or (with require_all) an entity
    missing from the source raises CuratedAcaiError, so that a change
    upstream stops the build until the correction is reviewed. Returns the
    entities, corrected; ``entities`` itself is not changed.
    """
    corrected = dict(entities)
    seen = set()
    for fix in corrections:
        entity_id, field = fix["id"], fix["field"]
        if field not in CORRECTABLE_FIELDS:
            raise CuratedAcaiError(f"graph_curated.json corrects unknown field {field!r} of {entity_id}")
        if (entity_id, field) in seen:
            raise CuratedAcaiError(f"graph_curated.json corrects {entity_id} {field} twice")
        seen.add((entity_id, field))
        entity = entities.get(entity_id)
        if entity is None:
            if require_all:
                raise CuratedAcaiError(f"ACAI has no entity {entity_id}, which graph_curated.json corrects")
            continue
        current = field_value(entity, field)
        if current == fix["to"]:
            continue
        if current != fix["from"]:
            raise CuratedAcaiError(
                f"ACAI {entity_id} {field} is {current!r}, but graph_curated.json corrects "
                f"{fix['from']!r} to {fix['to']!r}; review the correction"
            )
        source_id = fix.get("source")
        if source_id:
            source = entities.get(source_id)
            if source is None:
                if require_all:
                    raise CuratedAcaiError(
                        f"ACAI has no entity {source_id}, whose {field} graph_curated.json gives {entity_id}"
                    )
            elif field_value(source, field) != fix["to"]:
                raise CuratedAcaiError(
                    f"ACAI {source_id} {field} is {field_value(source, field)!r}, not the "
                    f"{fix['to']!r} graph_curated.json gives {entity_id}; review the correction"
                )
        corrected[entity_id] = {
            **corrected[entity_id],
            field: json.dumps(fix["to"]) if field in JSON_FIELDS else fix["to"],
        }
    return corrected


def parse_acai_entities(filepath: Path, entity_type: str) -> Iterator[dict]:
    """Parse a single ACAI entity JSON file.

    Args:
        filepath: Path to the entity JSON file
        entity_type: One of 'people', 'places', 'groups', 'keyterms'

    Yields:
        Dicts ready for database insertion into acai_entities table.
    """
    with open(filepath, encoding='utf-8') as f:
        data = json.load(f)

    # Handle both single entity and array formats
    if isinstance(data, list):
        entities = data
    elif isinstance(data, dict):
        # Could be a single entity or a wrapper
        if 'id' in data or 'name' in data:
            entities = [data]
        else:
            # Try to find entities in the data structure
            for key in ('entities', 'items', 'content', 'data'):
                if key in data and isinstance(data[key], list):
                    entities = data[key]
                    break
            else:
                entities = [data]
    else:
        return

    # Map entity_type directory name to a clean type string
    type_map = {
        'people': 'person',
        'places': 'place',
        'groups': 'group',
        'keyterms': 'keyterm',
    }
    clean_type = type_map.get(entity_type, entity_type)

    for entity_data in entities:
        if not isinstance(entity_data, dict):
            continue

        entity = _extract_entity(entity_data, clean_type)
        if entity and entity.get('name'):
            yield entity


def _extract_entity(data: dict, entity_type: str) -> dict | None:
    """Extract entity fields from raw ACAI JSON data."""
    # Build entity ID
    entity_id = data.get('id', '')
    name = data.get('name', data.get('label', ''))

    if not entity_id and name:
        entity_id = f"{entity_type}:{name}"
    elif not entity_id:
        return None

    # ACAI files carry no top-level name or description: the English ones are
    # localizations.eng.preferred_label and .descriptions[].description
    eng = (data.get('localizations') or {}).get('eng') or {}
    if not name:
        name = eng.get('preferred_label', eng.get('label', eng.get('name', str(entity_id))))

    # Description from localizations or direct field
    description = data.get('description', '')
    if not description:
        descriptions = eng.get('descriptions') or [{}]
        description = descriptions[0].get(
            'description', eng.get('description', eng.get('gloss', ''))
        )

    # Gender
    gender = data.get('gender', data.get('sex', ''))

    # Roles
    roles = data.get('roles', [])
    if isinstance(roles, list):
        roles_json = json.dumps(roles)
    else:
        roles_json = json.dumps([str(roles)]) if roles else '[]'

    # Family relationships
    father_id = _get_relationship_id(data, 'father')
    mother_id = _get_relationship_id(data, 'mother')

    partners = _get_relationship_list(data, 'partners', 'spouses', 'spouse')
    offspring = _get_relationship_list(data, 'offspring', 'children', 'child')
    siblings = _get_relationship_list(data, 'siblings', 'brothers', 'sisters')

    # Variant names: the English alternate labels that are names (ACAI's own
    # referred_to_as lists related entities' keys, e.g. keyterm:Believe for
    # Faith; lower-case labels are renderings such as "his" for Moses)
    referred_to_as = eng.get('alternate_labels') or data.get(
        'referredToAs', data.get('also_known_as', [])
    )
    if isinstance(referred_to_as, list):
        variants = []
        for label in referred_to_as:
            label = str(label).strip()
            if (label[:1].isupper() and is_name_label(label)
                    and label.lower() != name.lower() and label not in variants):
                variants.append(label)
        referred_to_as_json = json.dumps(variants)
    else:
        referred_to_as_json = json.dumps([str(referred_to_as)]) if referred_to_as else '[]'

    # References and speeches
    references = data.get('references', data.get('verses', []))
    reference_count = len(references) if isinstance(references, list) else 0

    key_refs = references[:20] if isinstance(references, list) else []
    key_references_json = json.dumps(key_refs)

    # Speeches are grouped by source text, e.g. {"wlc": [...], "SBLGNT": [...]}
    speeches = data.get('speeches', data.get('speechActs', []))
    if isinstance(speeches, dict):
        speeches = [s for group in speeches.values() if isinstance(group, list) for s in group]
    speeches_count = len(speeches) if isinstance(speeches, list) else 0

    # The TIPNR entries this entity is, keyed as names rows are (name + first
    # reference): 'Ezra@Ezr.7.1-Neh' -> 'Ezra@Ezr.7.1'. 'Alt|Name@Ref' keys
    # are another name of an entry, which the names table does not list.
    tipnr_keys = []
    for source_key in (data.get('alternate_sources') or {}).get('tipnr') or []:
        tipnr_name, _, first_ref = source_key.partition('@')
        key = f"{tipnr_name}@{first_ref.split('-')[0]}"
        if '|' not in tipnr_name and key not in tipnr_keys:
            tipnr_keys.append(key)

    return {
        'id': str(entity_id),
        'entity_type': entity_type,
        'name': name,
        'gender': gender or None,
        'description': description or None,
        'roles': roles_json,
        'father_id': father_id,
        'mother_id': mother_id,
        'partners': partners,
        'offspring': offspring,
        'siblings': siblings,
        'referred_to_as': referred_to_as_json,
        'key_references': key_references_json,
        'reference_count': reference_count,
        'speeches_count': speeches_count,
        'tipnr_keys': json.dumps(tipnr_keys),
    }


def is_name_label(label: str) -> bool:
    """Whether an ACAI alternate label is a name, not a textual note such as
    'Ketiv. Qere' (written and read forms differ) or 'Geruth like.them'."""
    return not re.search(r"\b(?:ketiv|qere)\b|\w\.\w", label, re.IGNORECASE)


def _get_relationship_id(data: dict, key: str) -> str | None:
    """Extract a single relationship ID (e.g., father, mother)."""
    val = data.get(key, data.get(f'{key}Id', data.get(f'{key}_id')))
    if val:
        if isinstance(val, dict):
            return val.get('id', val.get('entityId', str(val)))
        return str(val)
    return None


def _get_relationship_list(data: dict, *keys: str) -> str:
    """Extract a list of relationship IDs, trying multiple field names."""
    for key in keys:
        val = data.get(key)
        if val:
            if isinstance(val, list):
                ids = []
                for item in val:
                    if isinstance(item, dict):
                        ids.append(item.get('id', item.get('entityId', str(item))))
                    else:
                        ids.append(str(item))
                return json.dumps(ids)
            elif isinstance(val, str):
                return json.dumps([val])
    return '[]'
