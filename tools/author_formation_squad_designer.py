"""Author the Formation Sim squad-designer schema fields and the GGO Sol Marines
worked example.

Slice 1 of the squad designer (see ``.claude/plans`` / the Formation Sim design
notes):

1. Adds two ``schema_formation`` fields used by the new Design workspace:
   * ``roster_slots`` -- an ``object_list`` of abstract personnel/vehicle slots
     ``{id, kind, role, rank, count, is_command}`` (no per-soldier entity).
   * ``doctrine`` -- a free string tag (a ``doctrines`` entity family is Slice 2).
2. Stamps ``form_ggo_sol_marines`` with its faction / kind / doctrine and seeds a
   concrete command hierarchy beneath the existing ``form_1st_landing_battalion``
   (Landing Company -> 1st Platoon -> 1st Fire Team) with roster slots, so the
   feature ships with a fixture and the schema is demonstrated end to end.

Re-runnable: a second run only re-emits entities whose stored shape still differs.
Runtime code reads these definitions from the ontology; this module is not a
parallel registry.
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
BACKUP_ROOT = PROJECT_ROOT / "artifacts" / "formation_squad_designer"

DOCTRINE_VOCAB = ("assault", "defensive", "recon", "garrison", "mobile", "logistics")

# New schema_formation fields (section groups them in the card editor with the
# rest of the Formation Sim block).
NEW_FORMATION_FIELDS = {
    "roster_slots": {
        "type": "object_list",
        "section": "Formation Sim",
        "optional": True,
        "description": (
            "Abstract personnel/vehicle slots for the squad designer: "
            "{id, kind: personnel|vehicle, role, rank, count, is_command}."
        ),
    },
    "doctrine": {
        "type": "string",
        "section": "Formation Sim",
        "optional": True,
        "description": "Doctrine tag: " + " | ".join(DOCTRINE_VOCAB),
    },
}


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def _schema_change(datasets):
    schema = next(
        entity
        for entity in datasets.get("schemas", [])
        if entity.get("id") == "schema_formation"
    )
    updated = copy.deepcopy(schema)
    fields = dict(updated.get("fields") or {})
    changed = False
    for name, spec in NEW_FORMATION_FIELDS.items():
        if fields.get(name) != spec:
            fields[name] = copy.deepcopy(spec)
            changed = True
    if not changed:
        return None
    updated["fields"] = fields
    return updated


# ---------------------------------------------------------------------------
# GGO Sol Marines worked example
# ---------------------------------------------------------------------------

FIRE_TEAM_SLOTS = [
    {"id": "slot_ft1_lead", "kind": "personnel", "role": "Team Leader", "rank": "Sergeant", "count": 1, "is_command": True},
    {"id": "slot_ft1_rifleman", "kind": "personnel", "role": "Rifleman", "rank": "Marine", "count": 4, "is_command": False},
    {"id": "slot_ft1_grenadier", "kind": "personnel", "role": "Grenadier", "rank": "Marine", "count": 1, "is_command": False},
    {"id": "slot_ft1_apc", "kind": "vehicle", "role": "Landing APC", "rank": "", "count": 1, "is_command": False},
]

PLATOON_SLOTS = [
    {"id": "slot_pl1_lead", "kind": "personnel", "role": "Platoon Commander", "rank": "Lieutenant", "count": 1, "is_command": True},
    {"id": "slot_pl1_medic", "kind": "personnel", "role": "Corpsman", "rank": "Petty Officer", "count": 1, "is_command": False},
]

COMPANY_SLOTS = [
    {"id": "slot_co1_lead", "kind": "personnel", "role": "Company Commander", "rank": "Captain", "count": 1, "is_command": True},
]

# child id -> (pretty_name, parent id, doctrine, roster_slots)
SOL_MARINE_TREE = {
    "form_ggo_1st_landing_company": (
        "1st Landing Company", "form_1st_landing_battalion", "assault", COMPANY_SLOTS,
    ),
    "form_ggo_1st_landing_platoon": (
        "1st Platoon", "form_ggo_1st_landing_company", "assault", PLATOON_SLOTS,
    ),
    "form_ggo_1st_fire_team": (
        "1st Fire Team", "form_ggo_1st_landing_platoon", "mobile", FIRE_TEAM_SLOTS,
    ),
}

SOL_MARINE_FACTION = "fac_ggo_sol_marine_command"


def _formation_by_id(datasets):
    return {
        entity["id"]: entity
        for entity in datasets.get("formations", [])
        if isinstance(entity, dict) and entity.get("id")
    }


def _root_change(existing):
    """Stamp form_ggo_sol_marines with faction / kind / doctrine."""
    want = {
        "faction": SOL_MARINE_FACTION,
        "formation_kind": "realization",
        "doctrine": "mobile",
    }
    if existing is None:
        return None
    if all(existing.get(key) == value for key, value in want.items()):
        return None
    updated = copy.deepcopy(existing)
    updated.update(want)
    return updated


def _tree_changes(datasets):
    by_id = _formation_by_id(datasets)
    changes = []
    for child_id, (label, parent_id, doctrine, slots) in SOL_MARINE_TREE.items():
        want = {
            "id": child_id,
            "_dataset": "formations",
            "type": "formation",
            "name": label,
            "pretty_name": label,
            "entry_status": "draft",
            "formation_kind": "realization",
            "parents": [parent_id],
            "faction": SOL_MARINE_FACTION,
            "doctrine": doctrine,
            "roster_slots": copy.deepcopy(slots),
            "start_year": 2448,
        }
        existing = by_id.get(child_id)
        if existing is None:
            changes.append(want)
            continue
        merged = copy.deepcopy(existing)
        merged.update(want)
        if merged != existing:
            changes.append(merged)
    return changes


def build_transaction(datasets):
    upserts = []
    schema = _schema_change(datasets)
    if schema is not None:
        upserts.append(schema)
    root = _root_change(_formation_by_id(datasets).get("form_ggo_sol_marines"))
    if root is not None:
        upserts.append(root)
    upserts.extend(_tree_changes(datasets))
    return upserts


# ---------------------------------------------------------------------------

def _backup(store, upserts, remove_entity_ids=()):
    """Keep what this run replaces or removes, not a copy of the whole store (``tools/ontology_backup.py``)."""
    from tools.ontology_backup import backup_entities

    return backup_entities(store, BACKUP_ROOT, upserts, remove_entity_ids)


def _validate(store):
    datasets = store.load_datasets()
    schema = next(e for e in datasets.get("schemas", []) if e.get("id") == "schema_formation")
    for name in NEW_FORMATION_FIELDS:
        assert name in schema.get("fields", {}), f"{name} missing from schema_formation"
    by_id = _formation_by_id(datasets)
    for child_id, (label, parent_id, doctrine, slots) in SOL_MARINE_TREE.items():
        entity = by_id.get(child_id)
        assert isinstance(entity, dict), f"{child_id} not persisted"
        assert entity.get("parents") == [parent_id], f"{child_id} parent wrong"
        assert entity.get("doctrine") == doctrine, f"{child_id} doctrine wrong"
        assert len(entity.get("roster_slots") or []) == len(slots), f"{child_id} slots wrong"
    return {"formations": len(datasets.get("formations", []))}


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
    if not upserts:
        print("nothing to do (ontology already matches)")
        return

    backup_dir = _backup(store, upserts)
    print(f"backup: {backup_dir}")
    started = time.perf_counter()
    result = store.apply_changes(entities=upserts)
    print(f"applied in {time.perf_counter() - started:.2f}s: {result}")
    stats = _validate(store)
    store.export_rdfxml(ONTOLOGY_PATH)
    store.compact_database()
    print(f"checkpoint written; {stats}")


if __name__ == "__main__":
    main()
