"""Add input/output ports to the component ontology model.

One-way ontology authoring + migration utility (see the vehicle-designer
system-diagram work: components now separate a reserved *slot* -- a
category and a size -- from the specific catalog part installed into it,
and installed parts declare typed input/output ports so a system diagram
can auto-wire matching outputs to inputs).

What it does, as a single ``apply_changes`` transaction:

1. Extends ``schema_components`` (see ``tools/author_item_component_model.py``
   for the base item/component schema) with ``inputs``/``outputs`` fields --
   object lists of ``{resource_type, label}`` ports.
2. Backfills every ``components`` dataset entity that has no explicit
   ``inputs``/``outputs`` with ports inferred from its ``satisfies_categories``
   (real component entities carry a generic ``type`` of "component"/"assembly",
   not a fine-grained kind, so category is the only reliable signal to infer
   from).

Runtime code reads these definitions from the ontology; this module is not a
parallel registry. Re-runnable: a second run is a near no-op (only entities
that still differ are re-emitted).
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
BACKUP_ROOT = PROJECT_ROOT / "artifacts" / "component_ports_model"


# ---------------------------------------------------------------------------
# Port vocabulary and category -> default port inference
# ---------------------------------------------------------------------------

RESOURCE_TYPES = {
    "mechanical_power", "electrical_power", "fuel", "coolant",
    "thrust", "lift", "control_signal", "cargo_mass", "crew_capacity",
}

# Mirrors simulations/vehicle/vehicle_design.py::VehicleDesignController.
# CATEGORY_DEFAULT_PORTS -- kept as a separate, self-contained copy here
# (tools/ scripts do not import from simulations/) but any change to the
# port vocabulary or this inference table should be made in both places.
CATEGORY_DEFAULT_PORTS = {
    "propulsion_road": {
        "inputs": [{"resource_type": "fuel", "label": "Fuel"}],
        "outputs": [{"resource_type": "mechanical_power", "label": "Shaft Power"}],
    },
    "propulsion_air": {
        "inputs": [{"resource_type": "fuel", "label": "Fuel"}],
        "outputs": [{"resource_type": "thrust", "label": "Thrust"}],
    },
    "propulsion_marine": {
        "inputs": [{"resource_type": "mechanical_power", "label": "Drive Power"}],
        "outputs": [{"resource_type": "thrust", "label": "Thrust"}],
    },
    "propulsion_space": {
        "inputs": [{"resource_type": "fuel", "label": "Propellant"}],
        "outputs": [{"resource_type": "thrust", "label": "Thrust"}],
    },
    "wheels": {
        "inputs": [{"resource_type": "mechanical_power", "label": "Drive Power"}],
        "outputs": [{"resource_type": "thrust", "label": "Traction"}],
    },
    "tracks": {
        "inputs": [{"resource_type": "mechanical_power", "label": "Drive Power"}],
        "outputs": [{"resource_type": "thrust", "label": "Traction"}],
    },
    "flight_surfaces": {
        "inputs": [{"resource_type": "control_signal", "label": "Control Input"}],
        "outputs": [{"resource_type": "lift", "label": "Lift"}],
    },
    "control": {
        "outputs": [{"resource_type": "control_signal", "label": "Control Signal"}],
    },
    "fuel_storage": {
        "outputs": [{"resource_type": "fuel", "label": "Fuel"}],
    },
    "electrical_storage": {
        "outputs": [{"resource_type": "electrical_power", "label": "Electric Power"}],
    },
    "cargo_handling": {
        "outputs": [{"resource_type": "cargo_mass", "label": "Cargo Capacity"}],
    },
}


def _ports_for_categories(categories):
    for category in categories or []:
        defaults = CATEGORY_DEFAULT_PORTS.get(str(category).strip().lower())
        if defaults:
            return list(defaults.get("inputs", [])), list(defaults.get("outputs", []))
    return [], []


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

COMPONENT_PORT_FIELDS = {
    "inputs": {
        "type": "object_list", "section": "Systems", "optional": True,
        "description": "Resource ports consumed to operate, e.g. {resource_type: 'fuel', label: 'Fuel'}",
    },
    "outputs": {
        "type": "object_list", "section": "Systems", "optional": True,
        "description": "Resource ports produced, e.g. {resource_type: 'thrust', label: 'Thrust'}",
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


def _schema_changes(datasets):
    schemas = _schema_by_name(datasets)
    component_schema = copy.deepcopy(schemas["components"])
    fields = dict(component_schema.get("fields") or {})
    fields.update(copy.deepcopy(COMPONENT_PORT_FIELDS))
    component_schema["fields"] = fields
    return [component_schema]


# ---------------------------------------------------------------------------
# Entity backfill
# ---------------------------------------------------------------------------

def _entity_changes(datasets):
    changes = []
    for entity in datasets.get("components", []):
        if not isinstance(entity, dict) or not entity.get("id"):
            continue
        if entity.get("inputs") or entity.get("outputs"):
            continue
        inputs, outputs = _ports_for_categories(entity.get("satisfies_categories"))
        if not inputs and not outputs:
            continue
        out = copy.deepcopy(entity)
        out["inputs"] = inputs
        out["outputs"] = outputs
        changes.append(out)
    return changes


# ---------------------------------------------------------------------------

def build_transaction(datasets):
    schema_changes = _schema_changes(datasets)
    entity_changes = _entity_changes(datasets)
    return schema_changes + entity_changes


def _backup(store, upserts, remove_entity_ids=()):
    """Keep what this run replaces or removes, not a copy of the whole store (``tools/ontology_backup.py``)."""
    from tools.ontology_backup import backup_entities

    return backup_entities(store, BACKUP_ROOT, upserts, remove_entity_ids)


def _validate(store):
    datasets = store.load_datasets()
    schemas = _schema_by_name(datasets)
    fields = schemas["components"].get("fields", {})
    assert "inputs" in fields and "outputs" in fields, "port fields missing from schema_components"
    return {"components": len(datasets.get("components", []))}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report the transaction without writing")
    args = parser.parse_args(argv)

    store = PersistentOntologyStore(ONTOLOGY_PATH)
    datasets = store.load_datasets()
    upserts = build_transaction(datasets)

    print(f"upserts: {len(upserts)}")
    for entity in upserts:
        print(f"  {entity.get('_dataset', entity.get('schema', '?')):<12} {entity['id']}")
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
