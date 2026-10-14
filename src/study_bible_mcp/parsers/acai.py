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
"""

import json
from collections.abc import Iterator
from pathlib import Path


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
            if label[:1].isupper() and label.lower() != name.lower() and label not in variants:
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
