"""Introduce the vehicle-unit ontology model.

One-way ontology authoring utility (see the Vehicle Registry feature: a
vehicle *design* entity in the ``vehicles`` dataset represents a type/
blueprint; a ``vehicle_units`` entity represents one specific, individually
tracked constructed instance of that design -- serial number, which
production batch it came from, when it was built/destroyed, and an optional
link to whatever live entity currently represents it once it has been
actualized somewhere).

What it does, as a single ``apply_changes`` transaction:

1. Introduces ``schema_vehicle_unit`` (dataset ``vehicle_units``, id prefix
   ``unit_``, extends ``entity_core``).

This is a new dataset with no existing entities to migrate -- unlike
``tools/author_item_component_model.py``/``tools/author_component_ports_model.py``,
there is no entity-rewrite step here. Runtime code reads this definition from
the ontology; this module is not a parallel registry. Re-runnable: a second
run is a near no-op (the schema entity is only re-emitted if it differs).
"""

from __future__ import annotations

import argparse
import copy
import shutil
import sqlite3
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from world.persistent_ontology_store import PersistentOntologyStore

ONTOLOGY_PATH = PROJECT_ROOT / "ontology" / "index0.owl"
BACKUP_ROOT = PROJECT_ROOT / "artifacts" / "vehicle_unit_model"


SCHEMA_VEHICLE_UNIT_FIELDS = {
    "represents_design": {
        "type": "entity", "target": "vehicles",
        "section": "Identity", "optional": True,
        "description": "The vehicle design this is a constructed instance of.",
    },
    "produced_by": {
        "type": "entity", "target": "producers",
        "section": "Production", "optional": True,
    },
    "production_line_id": {
        "type": "string", "section": "Production", "optional": True,
        "description": "Matches a value in the producer's inline production_lines[].line_id -- the batch-grouping key.",
    },
    "batch_label": {
        "type": "string", "section": "Production", "optional": True,
        "description": "Friendly display override for the batch group header; derived from the production line when unset.",
    },
    "serial_number": {"type": "string", "section": "Identity", "optional": True},
    "is_prototype": {"type": "boolean", "section": "Identity", "optional": True},
    "year_constructed": {"type": "number", "section": "History", "optional": True},
    "year_destroyed": {"type": "number", "section": "History", "optional": True},
    "fate_notes": {"type": "text", "section": "History", "optional": True},
    "assigned_faction": {"type": "entity", "target": "faction", "section": "History", "optional": True},
    "current_link_entity_id": {
        "type": "string", "section": "History", "optional": True,
        "description": "Whatever live entity currently represents this unit (a site, a formation slot, a flight instance, ...); blank until actualized.",
    },
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
    schemas = _schema_by_name(datasets)
    if "vehicle_unit" in schemas:
        existing = copy.deepcopy(schemas["vehicle_unit"])
        existing["fields"] = copy.deepcopy(SCHEMA_VEHICLE_UNIT_FIELDS)
        return [existing]

    return [{
        "id": "schema_vehicle_unit",
        "_dataset": "schemas",
        "type": "schema",
        "schema": "vehicle_unit",
        "name": "vehicle_unit",
        "pretty_name": "Vehicle Unit",
        "extends": "entity_core",
        "fields": copy.deepcopy(SCHEMA_VEHICLE_UNIT_FIELDS),
    }]


def _backup(store, upserts, remove_entity_ids=()):
    """Keep what this run replaces or removes, not a copy of the whole store (``tools/ontology_backup.py``)."""
    from tools.ontology_backup import backup_entities

    return backup_entities(store, BACKUP_ROOT, upserts, remove_entity_ids)


def _validate(store):
    datasets = store.load_datasets()
    schemas = _schema_by_name(datasets)
    assert "vehicle_unit" in schemas, "schema_vehicle_unit missing"
    fields = schemas["vehicle_unit"].get("fields", {})
    for required_field in ("represents_design", "serial_number", "production_line_id"):
        assert required_field in fields, f"{required_field} missing from schema_vehicle_unit"
    return {"vehicle_units": len(datasets.get("vehicle_units", []))}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report the transaction without writing")
    args = parser.parse_args(argv)

    store = PersistentOntologyStore(ONTOLOGY_PATH)
    datasets = store.load_datasets()
    upserts = build_transaction(datasets)

    print(f"upserts: {len(upserts)}")
    for entity in upserts:
        print(f"  {entity.get('_dataset', '?'):<12} {entity['id']}")
    if args.dry_run:
        return

    backup_dir = _backup(store, upserts)
    print(f"backup: {backup_dir}")
    started = time.perf_counter()
    result = store.apply_changes(entities=upserts)
    print(f"applied in {time.perf_counter() - started:.2f}s: {result}")
    stats = _validate(store)
    store.export_rdfxml(ONTOLOGY_PATH)
    store.compact_database()
    print(f"checkpoint written; dataset sizes: {stats}")


if __name__ == "__main__":
    main()
