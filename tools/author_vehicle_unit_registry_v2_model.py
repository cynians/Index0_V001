"""Vehicle Registry v2 schema refinements.

One-way ontology authoring utility, follow-up to
``tools/author_vehicle_unit_model.py`` (see the Vehicle Registry feature).
Refining the registry UI surfaced three schema changes:

1. ``schema_vehicle_unit.is_prototype`` (boolean) is folded away in favor of
   a freeform ``version_label`` string ("Prototype", "Mk I", "Mk II", ...) --
   it becomes the primary grouping level in the registry table, not just a
   flag. Existing ``vehicle_units`` entities with ``is_prototype: True`` are
   backfilled to ``version_label: "Prototype"``; the ``is_prototype`` key is
   dropped from every real entity that has it (no back-compat shim).
2. ``schema_vehicle_unit.assigned_faction``'s ``target`` metadata is fixed
   from the singular ``"faction"`` to the actual dataset key ``"factions"``
   (a pre-existing cosmetic mismatch, harmless at runtime but worth
   correcting while touching this schema).
3. ``schema_vehicle`` (dataset ``vehicles``) gains ``unit_placeholders`` --
   an ``object_list`` of ``{"name": "<typed text>"}`` entries living on the
   *design* entity. This is the "unfinished link" tier below ``vehicle_units``:
   a unit known to exist by name but not yet catalogued as a full entity.
   ``tools/author_formation_vehicle_placeholders.py`` already extends this
   same schema entity's ``fields`` dict via ``PersistentOntologyStore`` --
   this follows that precedent.

Re-runnable: a second run is a near no-op once the fields already match and
no real entity still carries ``is_prototype``.
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
BACKUP_ROOT = PROJECT_ROOT / "artifacts" / "vehicle_unit_registry_v2"


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


def _updated_vehicle_unit_schema(schema_entity):
    updated = copy.deepcopy(schema_entity)
    fields = dict(updated.get("fields") or {})
    fields.pop("is_prototype", None)
    fields["version_label"] = {
        "type": "string", "section": "Identity", "optional": True,
        "description": "Freeform version/mark label (e.g. 'Prototype', 'Mk I', 'Mk II') -- the registry's primary grouping level.",
    }
    if "assigned_faction" in fields:
        assigned_faction = dict(fields["assigned_faction"])
        assigned_faction["target"] = "factions"
        fields["assigned_faction"] = assigned_faction
    updated["fields"] = fields
    return updated


def _updated_vehicle_schema(schema_entity):
    updated = copy.deepcopy(schema_entity)
    fields = dict(updated.get("fields") or {})
    fields["unit_placeholders"] = {
        "type": "object_list", "section": "Registry", "optional": True,
        "description": "Units known to exist by name but not yet catalogued as a vehicle_units entity; each entry is {name}. Promoted one at a time into a real vehicle_units record.",
    }
    updated["fields"] = fields
    return updated


def _backfilled_vehicle_unit(entity):
    updated = copy.deepcopy(entity)
    was_prototype = bool(updated.pop("is_prototype", False))
    if was_prototype and not updated.get("version_label"):
        updated["version_label"] = "Prototype"
    return updated


def build_transaction(datasets):
    schemas = _schema_by_name(datasets)
    assert "vehicle_unit" in schemas, "schema_vehicle_unit missing -- run author_vehicle_unit_model.py first"
    assert "vehicle" in schemas, "schema_vehicle missing"

    upserts = [
        _updated_vehicle_unit_schema(schemas["vehicle_unit"]),
        _updated_vehicle_schema(schemas["vehicle"]),
    ]
    for entity in datasets.get("vehicle_units", []):
        if isinstance(entity, dict) and "is_prototype" in entity:
            upserts.append(_backfilled_vehicle_unit(entity))
    return upserts


def _backup(store, upserts, remove_entity_ids=()):
    """Keep what this run replaces or removes, not a copy of the whole store (``tools/ontology_backup.py``)."""
    from tools.ontology_backup import backup_entities

    return backup_entities(store, BACKUP_ROOT, upserts, remove_entity_ids)


def _validate(store):
    datasets = store.load_datasets()
    schemas = _schema_by_name(datasets)
    vehicle_unit_fields = schemas["vehicle_unit"].get("fields", {})
    assert "version_label" in vehicle_unit_fields, "version_label missing from schema_vehicle_unit"
    assert "is_prototype" not in vehicle_unit_fields, "is_prototype should have been removed"
    assert vehicle_unit_fields["assigned_faction"]["target"] == "factions"
    vehicle_fields = schemas["vehicle"].get("fields", {})
    assert "unit_placeholders" in vehicle_fields, "unit_placeholders missing from schema_vehicle"
    remaining = [
        entity.get("id") for entity in datasets.get("vehicle_units", [])
        if isinstance(entity, dict) and "is_prototype" in entity
    ]
    assert not remaining, f"is_prototype still present on: {remaining}"
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
