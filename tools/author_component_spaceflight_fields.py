"""Add spaceflight capability fields to the component ontology model.

One-way ontology authoring utility for the logistics capability profiles
(``docs/logistics_simulation_concept_v001.md`` section 7;
``simulations/logistics/vehicle_profiles.py`` reads these fields from the
installed components' own entities).

What it does, as a single ``apply_changes`` transaction: extends
``schema_components`` with typed fields for what a component contributes in
space -- engine thrust and specific impulse, tank propellant capacity,
shielding class, life support, docking and atmosphere entry.

No entity is backfilled: a component without these values stays unknown for
them rather than receiving a guessed figure. Runtime code reads the
definitions from the ontology; this module is not a parallel registry.
Re-runnable: a second run re-emits only the schema.
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
BACKUP_ROOT = PROJECT_ROOT / "artifacts" / "component_spaceflight_fields"


# Shielding classes, lowest first. Mirrors the ranks of the ``shielding_class``
# term in simulations/logistics/capabilities.py (tools/ scripts do not import
# from simulations/); change both together.
SHIELDING_CLASSES = ("none", "orbital", "deep_space")

COMPONENT_SPACEFLIGHT_FIELDS = {
    "thrust_n": {
        "type": "number", "section": "Spaceflight", "optional": True,
        "description": "Engine thrust in vacuum, newtons",
    },
    "specific_impulse_s": {
        "type": "number", "section": "Spaceflight", "optional": True,
        "description": "Engine specific impulse in vacuum, seconds",
    },
    "propellant_capacity_kg": {
        "type": "number", "section": "Spaceflight", "optional": True,
        "description": "Propellant a tank holds when full, kilograms",
    },
    "shielding_class": {
        "type": "string", "section": "Spaceflight", "optional": True,
        "description": "Radiation shielding the component gives the craft: " + ", ".join(SHIELDING_CLASSES),
    },
    "life_support_s": {
        "type": "number", "section": "Spaceflight", "optional": True,
        "description": "Crew life support the component supplies, seconds (shown in interplanetary cycles)",
    },
    "docking": {
        "type": "boolean", "section": "Spaceflight", "optional": True,
        "description": "The component lets the craft dock",
    },
    "atmosphere_entry": {
        "type": "boolean", "section": "Spaceflight", "optional": True,
        "description": "The component lets the craft enter an atmosphere (heat shield)",
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
    # The whole schema entity goes back in: apply_changes replaces entities, it does not patch them.
    component_schema = copy.deepcopy(_schema_by_name(datasets)["components"])
    fields = dict(component_schema.get("fields") or {})
    fields.update(copy.deepcopy(COMPONENT_SPACEFLIGHT_FIELDS))
    component_schema["fields"] = fields
    return [component_schema]


def _backup(store, upserts):
    """Keep what this run replaces, not a copy of the whole store (``tools/ontology_backup.py``)."""
    from tools.ontology_backup import backup_entities

    return backup_entities(store, BACKUP_ROOT, upserts, ())


def _validate(store, fields_before):
    datasets = store.load_datasets()
    fields = _schema_by_name(datasets)["components"].get("fields", {})
    missing = [key for key in COMPONENT_SPACEFLIGHT_FIELDS if key not in fields]
    assert not missing, f"spaceflight fields missing from schema_components: {missing}"
    lost = [key for key in fields_before if key not in fields]
    assert not lost, f"existing component fields lost: {lost}"
    return {"component_fields": len(fields), "components": len(datasets.get("components", []))}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report the transaction without writing")
    args = parser.parse_args(argv)

    store = PersistentOntologyStore(ONTOLOGY_PATH)
    datasets = store.load_datasets()
    fields_before = dict(_schema_by_name(datasets)["components"].get("fields") or {})
    upserts = build_transaction(datasets)

    added = [key for key in COMPONENT_SPACEFLIGHT_FIELDS if key not in fields_before]
    print(f"schema_components: {len(fields_before)} fields, adding {len(added)}: {', '.join(added) or 'none'}")
    if args.dry_run:
        return

    backup_dir = _backup(store, upserts)
    print(f"backup: {backup_dir}")
    started = time.perf_counter()
    result = store.apply_changes(entities=upserts)
    print(f"applied in {time.perf_counter() - started:.2f}s: {result}")
    stats = _validate(store, fields_before)
    store.export_rdfxml(ONTOLOGY_PATH)
    store.compact_database()
    print(f"checkpoint written; {stats}")


if __name__ == "__main__":
    main()
