"""Author action tags, the personality fields of tags, and the schemas' tag rows.

Personality words themselves (tag entities with ``tag_class: personality``
and a ``big_five`` position) come from measured data, written by
tools/derive_personality_word_positions.py. Action tags (``tag_class: action``) are what
decisions carry; they nest through ``parents`` and may say who does them
(``trait_profiles``) and who never would (``excluded_by_traits``). A word
may exclude actions outright (``excludes_actions``: Pacifist excludes
Violence).

The schemas get ``tag_rows`` for the cards' Tags tab (world/tag_rows.py):
Personality on people, Needs on items and categories.

See docs/person_personality_concept_v001.md. Dry run by default;
``--apply`` writes. Existing entities are merged over their full stored dict.
"""

import argparse
import copy
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from world.persistent_ontology_store import PersistentOntologyStore


ONTOLOGY_PATH = PROJECT_ROOT / "ontology" / "index0.owl"

TAG_FIELDS = {
    "big_five": {
        "type": "dict", "section": "Personality", "optional": True,
        "description": "For tag_class 'personality': the word's place on the Big Five axes it speaks to, 0-1.",
    },
    "excludes_actions": {
        "type": "string_list", "section": "Personality", "optional": True,
        "description": "For a personality word: action tags a person with this word never considers.",
    },
    "excluded_by_traits": {
        "type": "string_list", "section": "Action", "optional": True,
        "description": "For tag_class 'action': personality words whose holders never consider this action.",
    },
    "trait_profiles": {
        "type": "dict", "section": "Action", "optional": True,
        "description": "For an action tag: {for: [[words]], against: [[words]]}, who does it and who refuses it.",
    },
}

SCHEMA_TAG_ROWS = {
    "person": [{"label": "Personality", "field": "personality_adjectives", "tag_class": "personality"}],
    "item": [{"label": "Needs", "field": "tags", "tag_class": "need"}],
    "category": [{"label": "Needs", "field": "tags", "tag_class": "need"}],
}

ACTION_COLORS = {"primary_color": "#c4796f", "secondary_color": "#3a201c"}

ACTIONS = [
    {"id": "tag_action_violence", "name": "Violence",
     "wiki_entry": "Harming someone on purpose. Any harmful act is a kind of Violence."},
    {"id": "tag_action_kill", "name": "Kill", "parents": ["tag_action_violence"],
     "wiki_entry": "Taking a life."},
    {"id": "tag_action_torture", "name": "Torture", "parents": ["tag_action_violence"],
     "trait_profiles": {"for": [["Cruel"], ["Sadistic"], ["Obedient"]], "against": [["Kind"], ["Merciful"]]},
     "wiki_entry": "Inflicting pain on someone in one's power. Done by the cruel, or by those who follow orders blindly."},
]


def action_entities():
    return [
        {"_dataset": "tags", "type": "tag", "tag_class": "action", "pretty_name": spec["name"], **ACTION_COLORS, **spec}
        for spec in ACTIONS
    ]


def build_changes(datasets):
    by_id = {
        entity.get("id"): entity
        for entities in datasets.values() if isinstance(entities, list)
        for entity in entities if isinstance(entity, dict)
    }
    schemas = {
        str(entity.get("schema") or entity.get("name") or "").removeprefix("schema_"): entity
        for entity in datasets.get("schemas", []) if isinstance(entity, dict)
    }
    changes = []
    tags_schema = copy.deepcopy(schemas["tags"])
    tags_schema["fields"] = {**(tags_schema.get("fields") or {}), **copy.deepcopy(TAG_FIELDS)}
    changes.append(tags_schema)
    for schema_name, rows in SCHEMA_TAG_ROWS.items():
        schema = copy.deepcopy(schemas[schema_name])
        existing_rows = [row for row in schema.get("tag_rows") or [] if isinstance(row, dict)]
        keys = {(row.get("field"), row.get("tag_class")) for row in existing_rows}
        schema["tag_rows"] = existing_rows + [row for row in rows if (row["field"], row["tag_class"]) not in keys]
        changes.append(schema)
    for entity in action_entities():
        existing = by_id.get(entity["id"])
        changes.append({**copy.deepcopy(existing), **entity} if existing else entity)
    return changes


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="Write to the ontology store; default is a dry run")
    args = parser.parse_args(argv)

    store = PersistentOntologyStore(ONTOLOGY_PATH)
    changes = build_changes(store.load_datasets())
    for change in changes:
        print(f"{change['id']}: {len(change)} fields")
    if not args.apply:
        print(f"Dry run: {len(changes)} entities would be written")
        return
    result = store.apply_changes(entities=changes)
    print(f"Authored {result['upserted']} personality and action tag entities")


if __name__ == "__main__":
    main()
