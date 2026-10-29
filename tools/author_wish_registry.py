"""Author the wishes dataset: structured wish/goal/dream entities.

Replaces free-text wishes/goals/dreams strings on person entities with
references into a dedicated `wishes` dataset. Each wish is a small structured
record -- task type, optional qualifier, an optional linked target entity,
and a wish type used for tag-based matching against interaction points --
plus a free-text note kept for display only, never for matching. See
docs/conceptual_layer_overview_v006.txt section 22 (Persons and Pops) for the
Is-State description of this distinction, including why job-assigned duties
(e.g. the lumber site's cart unload) are never wish-driven: wishes are
personality/context-driven and produce a person's own internally formed
tasks, while job duties arrive only through externally issued employment
tasks.

This is a one-way ontology authoring utility, following the same pattern as
the other tools/author_*.py scripts: runtime code (PersonSimulation) resolves
these entities from the ontology projection and does not maintain a parallel
registry.
"""

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from world.persistent_ontology_store import PersistentOntologyStore


ONTOLOGY_PATH = PROJECT_ROOT / "ontology" / "index0.owl"


WISH_SCHEMA_FIELDS = {
    "task_type": {
        "type": "string", "section": "Wish", "optional": True,
        "description": "The verb this wish wants acted on, e.g. obtain, experience, avoid, improve.",
    },
    "qualifier": {
        "type": "string", "section": "Wish", "optional": True,
        "description": "An optional modifier on the task type, e.g. affordable, quiet, quick.",
    },
    "target": {
        "type": "entity", "target": "items", "section": "Wish", "optional": True,
        "description": "The concrete entity this wish is about, if any.",
    },
    "wish_type": {
        "type": "string", "section": "Wish", "optional": True,
        "description": "Category tag matched against interaction-point tags to drive a self-initiated task.",
    },
    "note": {
        "type": "text", "section": "Wish", "optional": True,
        "description": "Free-text description, retained for display only -- never used for matching.",
    },
}


def _schema_name(entity):
    return str(entity.get("schema") or entity.get("name") or entity.get("id") or "").removeprefix("schema_")


def build_changes(datasets):
    schemas = {_schema_name(entity): dict(entity) for entity in datasets.get("schemas", []) if isinstance(entity, dict)}
    changes = []

    wishes_schema = schemas.get("wishes")
    if wishes_schema is None:
        wishes_schema = {
            "id": "schema_wishes", "_dataset": "schemas", "type": "schema",
            "extends": "entity_core", "schema": "wishes", "name": "wishes",
            "pretty_name": "Wishes", "offspring": [],
        }
    wishes_schema["fields"] = {**(wishes_schema.get("fields") or {}), **WISH_SCHEMA_FIELDS}
    changes.append(wishes_schema)

    changes.extend([
        {
            "id": "wish_obtain_lumber_for_repairs", "_dataset": "wishes", "type": "wish",
            "name": "Obtain Affordable Lumber For Repairs", "pretty_name": "Obtain Affordable Lumber For Repairs",
            "task_type": "obtain", "qualifier": "affordable", "target": "item_raw_lumber",
            "wish_type": "Home Improvement",
            "note": "Obtain affordable lumber for house repairs.",
        },
        {
            "id": "wish_relax_after_shift", "_dataset": "wishes", "type": "wish",
            "name": "Relax With Colleagues After A Shift", "pretty_name": "Relax With Colleagues After A Shift",
            "task_type": "experience", "qualifier": "quiet",
            "wish_type": "Social Place",
            "note": "Relax with colleagues after a long shift.",
        },
    ])
    return changes


def main():
    store = PersistentOntologyStore(ONTOLOGY_PATH)
    changes = build_changes(store.load_datasets())
    result = store.apply_changes(entities=changes)
    print(f"Authored {result['upserted']} wish registry ontology entities")


if __name__ == "__main__":
    main()
