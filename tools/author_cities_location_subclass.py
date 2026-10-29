"""Make ``cities`` a real subclass of ``locations``.

One-way ontology authoring + migration utility (companion to
``tools/author_item_component_model.py``, which did the same thing for
``components``/``item``).

What it does, as a single ``apply_changes`` transaction:

1. Rewrites ``schema_cities`` to ``extends: "locations"``. Fields already
   covered by the ``locations`` schema (``parent_location``, ``population``,
   ``controlling_factions``) are dropped from the city-specific field dict;
   the redundant ``location_entity`` back-reference (a city used to *point
   at* a location instead of *being* one) is dropped entirely.
2. Migrates every ``cities`` entity: drops ``location_entity`` (folding its
   value into ``parent_location`` when that field was still empty), and adds
   ``location_class: "city"`` so cities participate in the same
   `location_class`-keyed UI logic (``CANONICAL_LOCATION_CLASSES``, scale
   tiers, etc.) as any other location.
3. Re-parents the ``city_entry`` OWL class onto ``location_entry`` in the
   live quadstore (``PersistentOntologyStore.reparent_type_classes``) --
   schema ``extends`` alone does not touch the OWL class hierarchy.

Runtime code reads these definitions from the ontology; this module is not a
parallel registry. Re-runnable: a second run is a near no-op (only entities
that still differ are re-emitted, and the reparent call is idempotent).
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
BACKUP_ROOT = PROJECT_ROOT / "artifacts" / "cities_location_subclass"

# Fields the `cities` schema declared itself but that `locations` (its new
# parent) already provides -- dropped so the merged field set has no
# duplicates. `location_entity` is not in this set: it isn't dropped because
# `locations` provides it, it's dropped because it's now meaningless (a city
# no longer needs to *point at* a location -- it *is* one).
FIELDS_COVERED_BY_LOCATIONS = {"parent_location", "population", "controlling_factions"}

SCHEMA_CITIES_FIELDS = {
    "city_class": {"type": "string", "optional": True},
    "city_role": {"type": "string_list", "optional": True},
    "city_systems": {"type": "dict", "optional": True},
    "urban_structure": {"type": "dict", "optional": True},
    "cultural_features": {"type": "string_list", "optional": True},
    "embedded_sites": {"type": "string_list", "optional": True},
    "associated_institutions": {
        "type": "entity_list", "target": "institutions", "optional": True,
    },
}


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

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
    cities_schema = copy.deepcopy(schemas["cities"])
    cities_schema["extends"] = "locations"
    cities_schema["fields"] = copy.deepcopy(SCHEMA_CITIES_FIELDS)
    return [cities_schema]


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------

def _migrate_one(entity):
    out = copy.deepcopy(entity)
    location_entity = out.pop("location_entity", None)
    if location_entity and not out.get("parent_location"):
        out["parent_location"] = location_entity
    out.setdefault("location_class", "city")
    return out


def _entity_changes(datasets):
    changes = []
    for entity in datasets.get("cities", []):
        if not isinstance(entity, dict) or not entity.get("id"):
            continue
        migrated = _migrate_one(entity)
        if migrated != entity:
            changes.append(migrated)
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
    assert schemas["cities"].get("extends") == "locations", "cities schema not subclassed"
    for field_name in FIELDS_COVERED_BY_LOCATIONS:
        assert field_name not in schemas["cities"].get("fields", {}), (
            f"{field_name} still duplicated on cities schema"
        )
    for entity in datasets.get("cities", []):
        assert "location_entity" not in entity, f"{entity['id']} still has location_entity"
        assert entity.get("location_class") == "city", f"{entity['id']} missing location_class"
    return {"cities": len(datasets.get("cities", []))}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report the transaction without writing")
    args = parser.parse_args(argv)

    store = PersistentOntologyStore(ONTOLOGY_PATH)
    datasets = store.load_datasets()
    upserts = build_transaction(datasets)

    print(f"upserts: {len(upserts)}")
    for entity in upserts:
        print(f"  {entity.get('_dataset', entity.get('type', '?')):<12} {entity['id']}")
    if args.dry_run:
        return

    backup_dir = _backup(store, upserts)
    print(f"backup: {backup_dir}")
    started = time.perf_counter()
    result = store.apply_changes(entities=upserts)
    print(f"applied in {time.perf_counter() - started:.2f}s: {result}")

    reparented = store.reparent_type_classes({"city": "location"})
    print(f"city_entry reparented onto location_entry: {reparented}")

    stats = _validate(store)
    store.export_rdfxml(ONTOLOGY_PATH)
    store.compact_database()
    print(f"checkpoint written; dataset sizes: {stats}")


if __name__ == "__main__":
    main()
