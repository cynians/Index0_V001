"""Add generated membership and member weights to collections; author the debug test-craft collection.

One-way ontology authoring utility for the collection simulation
(``docs/collection_simulation_concept_v001.md``; read by
``simulations/collection/collections.py``).

What it does, as a single ``apply_changes`` transaction:

1. Extends ``schema_collections`` with ``membership_rule`` (a structured filter
   whose matches are members, worked out when read and never stored) and
   ``member_weights`` (a numeric weight per member), and suggests the
   collection class ``vehicle_roster``.
2. Authors ``coll_debug_test_spacecraft``: every vehicle of a spacecraft class
   tagged ``test craft``, which the space view's transfer panel checks.

Runtime code reads the definitions from the ontology; this module is not a
parallel registry. Re-runnable: a second run re-emits the same two entities.
"""

from __future__ import annotations

import argparse
import copy
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from world.persistent_ontology_store import PersistentOntologyStore

ONTOLOGY_PATH = PROJECT_ROOT / "ontology" / "index0.owl"
BACKUP_ROOT = PROJECT_ROOT / "artifacts" / "collection_membership"
DEBUG_COLLECTION_ID = "coll_debug_test_spacecraft"

COLLECTION_MEMBERSHIP_FIELDS = {
    "membership_rule": {
        "type": "object", "section": "Membership", "optional": True,
        "description": "Structured filter whose matches are members, worked out when read: datasets, "
                       "field_values {field: [values]}, tags_all, tags_any, fields_present, weight",
    },
    "member_weights": {
        "type": "object_list", "section": "Membership", "optional": True,
        "description": "Numeric weight per member, e.g. {member: 'veh_x', weight: 0.5}; members without one weigh 1",
    },
}
NEW_CLASS_SUGGESTIONS = ("vehicle_roster",)

# Mirrors SPACECRAFT_CLASSES in simulations/logistics/vehicle_profiles.py
# (tools/ scripts do not import from simulations/); change both together.
SPACECRAFT_CLASSES = ["orbital_spacecraft", "planetary_spacecraft", "system_spacecraft", "interstellar_spacecraft"]


def debug_collection():
    return {
        "id": DEBUG_COLLECTION_ID,
        "_dataset": "collections",
        "type": "collections",
        "name": "Debug Test Spacecraft",
        "pretty_name": "Debug Test Spacecraft",
        "collection_class": "vehicle_roster",
        "scope": "Every spacecraft design tagged 'test craft'. The space view's transfer panel checks these "
                 "against each window while the logistics simulation is being built.",
        "membership_rule": {
            "datasets": ["vehicles"],
            "field_values": {"vehicle_class": list(SPACECRAFT_CLASSES)},
            "tags_all": ["test craft"],
        },
        "tags": ["debug", "test craft", "logistics verification"],
        "entry_status": "verification sample",
    }


def _schema_by_name(datasets):
    out = {}
    for entity in datasets.get("schemas", []):
        if not isinstance(entity, dict):
            continue
        name = str(entity.get("schema") or entity.get("name") or entity.get("id") or "")
        name = name.removeprefix("schema_")
        if name:
            out[name] = entity
    return out


def build_transaction(datasets):
    # The whole schema entity goes back in: apply_changes replaces entities, it does not patch them.
    schema = copy.deepcopy(_schema_by_name(datasets)["collections"])
    fields = dict(schema.get("fields") or {})
    fields.update(copy.deepcopy(COLLECTION_MEMBERSHIP_FIELDS))
    class_field = dict(fields.get("collection_class") or {"type": "string", "optional": True})
    suggestions = list(class_field.get("suggestions") or [])
    class_field["suggestions"] = suggestions + [value for value in NEW_CLASS_SUGGESTIONS if value not in suggestions]
    fields["collection_class"] = class_field
    schema["fields"] = fields
    return [schema, debug_collection()]


def _validate(store, fields_before):
    datasets = store.load_datasets()
    fields = _schema_by_name(datasets)["collections"].get("fields", {})
    missing = [key for key in COLLECTION_MEMBERSHIP_FIELDS if key not in fields]
    assert not missing, f"membership fields missing from schema_collections: {missing}"
    lost = [key for key in fields_before if key not in fields]
    assert not lost, f"existing collection fields lost: {lost}"
    assert any(entity.get("id") == DEBUG_COLLECTION_ID for entity in datasets.get("collections", [])), "debug collection missing"
    return {"collection_fields": len(fields), "collections": len(datasets.get("collections", []))}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report the transaction without writing")
    args = parser.parse_args(argv)

    store = PersistentOntologyStore(ONTOLOGY_PATH)
    datasets = store.load_datasets()
    fields_before = dict(_schema_by_name(datasets)["collections"].get("fields") or {})
    upserts = build_transaction(datasets)
    added = [key for key in COLLECTION_MEMBERSHIP_FIELDS if key not in fields_before]
    print(f"schema_collections: {len(fields_before)} fields, adding {', '.join(added) or 'none'}; "
          f"class suggestions {upserts[0]['fields']['collection_class']['suggestions']}")
    print(f"collection: {DEBUG_COLLECTION_ID}")
    if args.dry_run:
        return

    from tools.ontology_backup import backup_entities

    print(f"backup: {backup_entities(store, BACKUP_ROOT, upserts, ())}")
    started = time.perf_counter()
    result = store.apply_changes(entities=upserts)
    print(f"applied in {time.perf_counter() - started:.2f}s: {result}")
    stats = _validate(store, fields_before)
    store.export_rdfxml(ONTOLOGY_PATH)
    store.compact_database()
    print(f"checkpoint written; {stats}")


if __name__ == "__main__":
    main()
