"""Author the city-simulation fields into the ontology schema.

One-way ontology authoring utility for the city simulation
(docs/city_simulation_concept_v001.md).  As one ``apply_changes`` transaction
it extends ``schema_locations`` with the fields a city founded on generated
terrain carries (``simulations/city/city_site.py``):

* ``terrain_source_map_id`` -- the refined region whose terrain, water,
  climate, soil and material models are the city's ground;
* ``terrain_source_fingerprint`` -- that region's heightfield fingerprint at
  founding, so a regenerated region can be reported as changed ground;
* ``terrain_root_planet_id`` -- the planet the region was refined from;
* ``geographic_source_bounds`` -- the region's bounds in its parent map's
  frame (the city's own ``bounds`` are metres).

The schema is merged from its full current dict -- the store replaces whole
entities.  Re-runnable: a second run re-emits the same record.  The ``.owl``
checkpoint is only exported with ``--export-checkpoint``.
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
BACKUP_ROOT = PROJECT_ROOT / "artifacts" / "city_simulation_model"

SECTION = "City Site"

LOCATION_FIELDS = {
    "terrain_source_map_id": {
        "type": "entity", "target": "locations", "section": SECTION, "optional": True,
        "description": "The refined worldgen region this location stands on. Its models are read through this link, never copied.",
    },
    "terrain_source_fingerprint": {
        "type": "string", "section": SECTION, "optional": True,
        "description": "Heightfield fingerprint of the terrain source at founding; a mismatch means the region was regenerated.",
    },
    "terrain_root_planet_id": {
        "type": "entity", "target": "locations", "section": SECTION, "optional": True,
        "description": "The planet the terrain source was refined from.",
    },
    "geographic_source_bounds": {
        "type": "object", "section": SECTION, "optional": True,
        "description": "The terrain source's bounds in its parent map's coordinates. The location's own bounds are site metres.",
    },
}


def _schema_by_name(datasets):
    out = {}
    for entity in datasets.get("schemas", []):
        if not isinstance(entity, dict):
            continue
        name = str(entity.get("schema") or entity.get("name") or entity.get("id") or "").removeprefix("schema_")
        if name:
            out[name] = entity
    return out


def _plain(entity):
    """Complete plain-dict copy (hydrates lazy projection wrappers first)."""

    materialize = getattr(entity, "materialize", None)
    if callable(materialize):
        entity = materialize()
    return copy.deepcopy(dict(entity))


def build_transaction(datasets):
    """Return the upserts without touching disk."""

    existing = _schema_by_name(datasets).get("locations")
    if existing is None:
        raise RuntimeError("schema_locations is missing from the ontology")
    updated = _plain(existing)
    updated["fields"] = {**dict(updated.get("fields") or {}), **copy.deepcopy(LOCATION_FIELDS)}
    return [updated]


def _backup(store, upserts, remove_entity_ids=()):
    """Keep what this run replaces or removes, not a copy of the whole store (``tools/ontology_backup.py``)."""
    from tools.ontology_backup import backup_entities

    return backup_entities(store, BACKUP_ROOT, upserts, remove_entity_ids)


def _validate(store):
    fields = _schema_by_name(store.load_datasets())["locations"].get("fields", {})
    for field_name in LOCATION_FIELDS:
        assert field_name in fields, f"locations.{field_name} missing"
    return {"location_fields": len(fields)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="report the transaction without writing")
    parser.add_argument("--export-checkpoint", action="store_true",
                        help="also export ontology/index0.owl (slow; captures every session's pending edits)")
    args = parser.parse_args(argv)

    store = PersistentOntologyStore(ONTOLOGY_PATH)
    datasets = store.load_datasets()
    before = set((_schema_by_name(datasets)["locations"].get("fields") or {}))
    upserts = build_transaction(datasets)
    after = set(upserts[0]["fields"])
    print(f"schema_locations: {len(before)} -> {len(after)} fields; adds {sorted(after - before)}")
    if args.dry_run:
        return

    backup_dir = _backup(store, upserts)
    print(f"backup: {backup_dir}")
    started = time.perf_counter()
    result = store.apply_changes(entities=upserts)
    print(f"applied in {time.perf_counter() - started:.2f}s: {result}")
    print(f"validated: {_validate(store)}")
    if args.export_checkpoint:
        store.export_rdfxml(ONTOLOGY_PATH)
        print("checkpoint exported")


if __name__ == "__main__":
    main()
