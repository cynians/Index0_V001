"""Move the lab people's knowledge into knowledge collections (Person Sim slice N2).

Each full person keeps what they know in one collection of class
``personal_knowledge``, named by the person's ``knowledge_collection``. It
nests shared collections (``shared_knowledge``) for what a group knows:
Lumber Camp Lore for everyone at the lumber site, Site Cook Training for the
cook. Beliefs are ``member_records`` rows; every member is also listed in
``includes`` so collection readers that only read membership see it too.
See simulations/person/person_knowledge.py and
docs/person_simulation_concept_v001.md section 5.

The four lab people's former ``knowledge_records`` are their personal
records here, unchanged; their ``knowledge_records`` and ``known_entities``
fields are removed, and so are those two fields from the person schema.
Existing entities are merged over their full stored dict.

Dry run by default; ``--apply`` writes.
"""

import argparse
import copy
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.author_person_psychology_model import PERSON_PSYCHOLOGY_FIELDS
from world.persistent_ontology_store import PersistentOntologyStore


ONTOLOGY_PATH = PROJECT_ROOT / "ontology" / "index0.owl"

COLLECTION_FIELDS = {
    "member_records": {
        "type": "object_list", "section": "Members", "optional": True,
        "description": (
            "One row per member, {member: id, ...}: what the collection says about that member. "
            "In a knowledge collection these are beliefs: familiarity, interest, conviction, "
            "navigation_knowledge, direction_hint, route_waypoints, believed_location, "
            "believed_state, checked_at, experienced, source."
        ),
    },
}
COLLECTION_CLASSES = ("personal_knowledge", "shared_knowledge")
REMOVED_PERSON_FIELDS = ("knowledge_records", "known_entities")


def _knowledge_collection(collection_id, name, collection_class, records, nested=()):
    return {
        "id": collection_id, "_dataset": "collections", "type": "collection",
        "name": name, "pretty_name": name, "collection_class": collection_class,
        "includes": list(nested) + [record["member"] for record in records],
        "member_records": [dict(record) for record in records],
    }


LUMBER_CAMP_LORE = "coll_knowledge_lumber_camp_lore"
SITE_COOK_TRAINING = "coll_knowledge_site_cook_training"

SHARED_COLLECTIONS = [
    _knowledge_collection(LUMBER_CAMP_LORE, "Lumber Camp Lore", "shared_knowledge", [
        {"member": "location_lumber_test_site", "familiarity": 0.9, "navigation_knowledge": "route"},
        {"member": "location_lumber_test_woodlot", "familiarity": 0.3,
         "navigation_knowledge": "direction", "direction_hint": [-1, 0]},
        {"member": "spec_empetrum_nigrum", "interest": 0.4, "familiarity": 0.5,
         "believed_location": "location_lumber_test_woodlot"},
    ]),
    _knowledge_collection(SITE_COOK_TRAINING, "Site Cook Training", "shared_knowledge", [
        {"member": "recipe_simple_cooked_meal", "interest": 0.7, "familiarity": 0.7},
        {"member": "location_person_test_kitchen", "familiarity": 0.8, "navigation_knowledge": "route"},
        {"member": "location_person_test_pantry", "familiarity": 0.8, "navigation_knowledge": "route"},
    ]),
]

# person id -> (collection id, shared collections it nests, the person's own beliefs).
# The beliefs are the former knowledge_records of tools/author_person_food_ownership_model.py.
PERSONAL_COLLECTIONS = {
    "person_lab_worker": ("coll_knowledge_mara_voss", (LUMBER_CAMP_LORE, SITE_COOK_TRAINING), [
        {"member": "recipe_simple_cooked_meal", "interest": 0.86, "familiarity": 0.81, "source": "learned recipe"},
        {"member": "location_lumber_test_barracks", "interest": 0.65, "familiarity": 0.95, "navigation_knowledge": "route", "source": "resident knowledge"},
        {"member": "location_person_test_kitchen", "interest": 0.92, "familiarity": 1.0, "navigation_knowledge": "route", "source": "workplace knowledge"},
        {"member": "location_person_test_pantry", "interest": 0.78, "familiarity": 0.9, "navigation_knowledge": "route", "source": "daily provisioning"},
        {"member": "location_lumber_test_factory", "interest": 0.55, "familiarity": 0.35, "navigation_knowledge": "direction", "direction_hint": [1, 0.35], "source": "general site orientation"},
        {"member": "location_lumber_test_woodlot", "interest": 0.45, "familiarity": 0.25, "navigation_knowledge": "direction", "direction_hint": [-1, 0], "source": "told it lies west"},
    ]),
    "person_lumber_laborer_elias": ("coll_knowledge_elias_kern", (LUMBER_CAMP_LORE,), [
        {"member": "location_lumber_test_factory", "familiarity": 0.95, "navigation_knowledge": "route"},
        {"member": "location_lumber_test_storage", "familiarity": 0.9, "navigation_knowledge": "route"},
        {"member": "location_lumber_test_woodlot", "familiarity": 0.8, "navigation_knowledge": "route"},
    ]),
    "person_lumber_laborer_nia": ("coll_knowledge_nia_vale", (LUMBER_CAMP_LORE,), [
        {"member": "location_lumber_test_factory", "familiarity": 0.9, "navigation_knowledge": "route"},
        {"member": "location_lumber_test_storage", "familiarity": 0.98, "navigation_knowledge": "route"},
        {"member": "location_lumber_test_woodlot", "familiarity": 0.35, "navigation_knowledge": "direction", "direction_hint": [-1, 0]},
    ]),
    "person_lumber_overseer_tomas": ("coll_knowledge_tomas_rhee", (LUMBER_CAMP_LORE,), [
        {"member": "location_lumber_test_site", "familiarity": 0.98, "navigation_knowledge": "route"},
        {"member": "location_lumber_test_factory", "familiarity": 0.98, "navigation_knowledge": "route"},
        {"member": "location_lumber_test_storage", "familiarity": 0.95, "navigation_knowledge": "route"},
        {"member": "location_lumber_test_woodlot", "familiarity": 0.9, "navigation_knowledge": "route"},
    ]),
}


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

    collection_schema = copy.deepcopy(schemas["collections"])
    fields = {**(collection_schema.get("fields") or {}), **copy.deepcopy(COLLECTION_FIELDS)}
    class_field = dict(fields.get("collection_class") or {"type": "string", "optional": True})
    suggestions = list(class_field.get("suggestions") or [])
    class_field["suggestions"] = suggestions + [value for value in COLLECTION_CLASSES if value not in suggestions]
    fields["collection_class"] = class_field
    collection_schema["fields"] = fields
    changes.append(collection_schema)

    person_schema = copy.deepcopy(schemas["person"])
    person_fields = {
        key: value for key, value in (person_schema.get("fields") or {}).items()
        if key not in REMOVED_PERSON_FIELDS
    }
    person_fields["knowledge_collection"] = copy.deepcopy(PERSON_PSYCHOLOGY_FIELDS["knowledge_collection"])
    person_schema["fields"] = person_fields
    changes.append(person_schema)

    for collection in SHARED_COLLECTIONS:
        existing = by_id.get(collection["id"])
        changes.append({**copy.deepcopy(existing), **collection} if existing else copy.deepcopy(collection))

    for person_id, (collection_id, nested, records) in PERSONAL_COLLECTIONS.items():
        person = copy.deepcopy(by_id[person_id])
        name = person.get("pretty_name") or person.get("name") or person_id
        existing = by_id.get(collection_id)
        collection = _knowledge_collection(
            collection_id, f"Knowledge of {name}", "personal_knowledge", records, nested,
        )
        changes.append({**copy.deepcopy(existing), **collection} if existing else collection)
        for field_name in REMOVED_PERSON_FIELDS:
            person.pop(field_name, None)
        person["knowledge_collection"] = collection_id
        changes.append(person)
    return changes


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="Write to the ontology store; default is a dry run")
    args = parser.parse_args(argv)

    store = PersistentOntologyStore(ONTOLOGY_PATH)
    changes = build_changes(store.load_datasets())
    for change in changes:
        records = change.get("member_records")
        detail = f", {len(records)} member records" if records is not None else ""
        print(f"{change['id']}: {len(change)} fields{detail}")
    if not args.apply:
        print(f"Dry run: {len(changes)} entities would be written")
        return
    result = store.apply_changes(entities=changes)
    print(f"Authored {result['upserted']} person knowledge ontology entities")


if __name__ == "__main__":
    main()
