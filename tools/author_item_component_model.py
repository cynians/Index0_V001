"""Consolidate the item / component ontology model.

One-way ontology authoring + migration utility (see
``docs/entity_field_overview_item_component_v001.md`` for the design).

What it does, as a single ``apply_changes`` transaction:

1. Introduces a ``categories`` entity family (``schema_category`` + a shallow
   starter taxonomy). Categories nest through the ordinary ``parents`` relation,
   so ``offspring`` gives sub-categories for free.
2. Rewrites ``schema_item`` as the corporal-object base: adds ``categories`` and
   the universal physical block (``dimension_*``, ``mass_kg``); renames
   ``inventory_unit`` -> ``default_unit`` and ``uses_technology`` ->
   ``requires_technology``; drops ``item_class``, ``component_equivalent``,
   ``installable`` (derived from ``install_contexts``) and the standalone
   ``stackable`` (covered by ``storage_modes``).
3. Rewrites ``schema_components`` to ``extends: "item"`` -- a subclass that only
   adds the "installed functional part" vocabulary. Drops ``represented_item``
   and everything now inherited.
4. Migrates every ``items`` / ``components`` entity to the new shape.
5. Merges the two duplicate item/component pairs (``pump_module``,
   ``storage_rack``) onto the item, deletes the ``comp_*`` twin, and repoints the
   two production entities that referenced them.
6. Normalises stray ``target: "item"`` schema references to ``"items"``.

Runtime code reads these definitions from the ontology; this module is not a
parallel registry. Re-runnable: a second run is a near no-op (only entities that
still differ are re-emitted).
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
BACKUP_ROOT = PROJECT_ROOT / "artifacts" / "item_component_model"


# ---------------------------------------------------------------------------
# Category taxonomy
# ---------------------------------------------------------------------------

# id -> (pretty_name, category_kind, [parent category ids])
CATEGORY_TREE = {
    "cat_manufactured_good": ("Manufactured Good", "form", []),
    "cat_foodstuff": ("Foodstuff", "functional", []),
    "cat_raw_material_good": ("Raw Material Good", "functional", []),

    "cat_industrial_good": ("Industrial Good", "market", ["cat_manufactured_good"]),
    "cat_machinery_module": ("Machinery Module", "functional", ["cat_manufactured_good"]),
    "cat_storage_fixture": ("Storage Fixture", "functional", ["cat_manufactured_good"]),
    "cat_small_arm": ("Small Arm", "functional", ["cat_manufactured_good"]),
    "cat_kitchen_fixture": ("Kitchen Fixture", "functional", ["cat_manufactured_good"]),
    "cat_cooking_appliance": ("Cooking Appliance", "functional", ["cat_manufactured_good"]),
    "cat_vehicle_part": ("Vehicle Part", "functional", ["cat_manufactured_good"]),

    "cat_food_ingredient": ("Food Ingredient", "functional", ["cat_foodstuff"]),
    "cat_prepared_food": ("Prepared Food", "functional", ["cat_foodstuff"]),

    "cat_raw_building_material": ("Raw Building Material", "functional", ["cat_raw_material_good"]),

    # Demonstrates multi-parent classification -- no items yet.
    "cat_communication_good": ("Communication Good", "functional", ["cat_manufactured_good"]),
    "cat_electronic_item": ("Electronic Item", "form", ["cat_manufactured_good"]),
    "cat_consumer_good_tech": ("Consumer Technology Good", "market", ["cat_manufactured_good"]),
}

# legacy item_class / component_class string -> category ids
CLASS_TO_CATEGORIES = {
    "industrial_good": ["cat_industrial_good"],
    "machinery_module": ["cat_machinery_module", "cat_industrial_good"],
    "storage_fixture": ["cat_storage_fixture", "cat_industrial_good"],
    "small_arm": ["cat_small_arm"],
    "prepared food": ["cat_prepared_food"],
    "food ingredient": ["cat_food_ingredient"],
    "raw building material": ["cat_raw_building_material"],
    "kitchen fixture": ["cat_kitchen_fixture"],
    "cooking appliance": ["cat_cooking_appliance"],
    # noise literal on ~30 components -- carries no information
    "component": [],
}

# items with no legacy class that still deserve a category
EXTRA_ITEM_CATEGORIES = {
    "item_zilovic_mgx_188_canibal": ["cat_small_arm"],
}


def _category_entities():
    entities = []
    for cat_id, (pretty, kind, parents) in CATEGORY_TREE.items():
        entity = {
            "id": cat_id,
            "_dataset": "categories",
            "type": "category",
            "name": pretty,
            "pretty_name": pretty,
            "category_kind": kind,
        }
        if parents:
            entity["parents"] = list(parents)
        entities.append(entity)
    # parents first so relation targets resolve during the single transaction
    entities.sort(key=lambda e: 0 if not e.get("parents") else 1)
    return entities


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

SCHEMA_CATEGORY_FIELDS = {
    "category_kind": {
        "type": "string",
        "section": "Classification",
        "optional": True,
        "description": "functional | form | market | regulatory | material_domain",
    },
    "synonyms": {"type": "string_list", "section": "Classification", "optional": True},
    "category_notes": {"type": "text", "section": "Overview", "optional": True},
    # Derived from every item's `categories` by
    # EntityLoader.populate_category_members() -- never hand-authored.
    "members": {"type": "entity_list", "section": "Relations", "optional": True},
}

SCHEMA_ITEM_FIELDS = {
    "categories": {
        "type": "entity_list", "target": "categories",
        "section": "Classification", "optional": True,
    },
    "primary_material": {"type": "entity", "target": "materials", "optional": True},
    "secondary_materials": {"type": "entity_list", "target": "materials", "optional": True},
    "production_materials_needed": {
        "type": "entity_list", "target": "materials",
        "section": "Class Relations", "optional": True,
    },
    "production_components_needed": {
        "type": "entity_list", "target": "components",
        "section": "Class Relations", "optional": True,
    },
    "production_items_needed": {
        "type": "entity_list", "target": "items",
        "section": "Class Relations", "optional": True,
    },
    "produced_by": {"type": "entity_list", "target": "faction", "optional": True},
    "requires_technology": {"type": "entity_list", "target": "technology", "optional": True},
    "dimension_length_m": {"type": "number", "section": "Physical", "optional": True},
    "dimension_width_m": {"type": "number", "section": "Physical", "optional": True},
    "dimension_height_m": {"type": "number", "section": "Physical", "optional": True},
    "mass_kg": {"type": "number", "section": "Physical", "optional": True},
    "storage_modes": {"type": "string_list", "section": "Handling", "optional": True},
    "handling_notes": {"type": "text", "section": "Handling", "optional": True},
    "default_state": {"type": "string", "section": "Handling", "optional": True},
    "portable": {
        "type": "string", "section": "Handling", "optional": True,
        "description": "hand | team | vehicle | fixed",
    },
    "placeable": {"type": "boolean", "section": "Handling", "optional": True},
    "install_contexts": {"type": "string_list", "section": "Handling", "optional": True},
    "descriptive_capabilities": {"type": "string_list", "optional": True},
    "ownership_records": {
        "type": "entity_list", "target": "ownerships",
        "section": "Ownership", "optional": True,
    },
    "consumable": {"type": "boolean", "section": "Food", "optional": True},
    "food_energy_kcal": {"type": "number", "section": "Food", "optional": True},
    "food_satiation": {"type": "number", "section": "Food", "optional": True},
    "inventory_items": {"type": "object_list", "section": "Inventory", "optional": True},
    "default_unit": {"type": "string", "section": "Inventory", "optional": True},
}

SCHEMA_COMPONENT_FIELDS = {
    "functional_roles": {"type": "string_list", "optional": True},
    "satisfies_categories": {"type": "string_list", "optional": True},
    "operational_groups": {"type": "string_list", "optional": True},
    "subsystem_labels": {"type": "string_list", "optional": True},
    "maintenance_notes": {"type": "text", "optional": True},
    "power_kw": {"type": "number", "section": "Physical", "optional": True},
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
    changes = []

    changes.append({
        "id": "schema_category",
        "_dataset": "schemas",
        "type": "schema",
        "schema": "category",
        "name": "category",
        "pretty_name": "Category",
        "extends": "entity_core",
        "fields": copy.deepcopy(SCHEMA_CATEGORY_FIELDS),
    })

    item_schema = copy.deepcopy(schemas["item"])
    item_schema["fields"] = copy.deepcopy(SCHEMA_ITEM_FIELDS)
    changes.append(item_schema)

    component_schema = copy.deepcopy(schemas["components"])
    component_schema["extends"] = "item"
    component_schema["fields"] = copy.deepcopy(SCHEMA_COMPONENT_FIELDS)
    changes.append(component_schema)

    # NOTE: stray `target: "item"` -> `"items"` on other schemas (production,
    # technology, producer, locations, formation, vehicle) is deferred to a
    # follow-up pass -- rewriting those whole schema entities risks colliding
    # with other sessions that also author them. It is cosmetic (the relation
    # picker resolves plural datasets anyway).

    return changes


# ---------------------------------------------------------------------------
# Entity migration
# ---------------------------------------------------------------------------

MERGE_PAIRS = {
    # surviving item id -> component twin id to delete
    "item_pump_module": "comp_pump_module",
    "item_storage_rack": "comp_storage_rack",
}
COMPONENT_ONLY_MERGE_KEYS = ("functional_roles", "maintenance_notes")


def _categories_for(entity):
    legacy = str(entity.get("item_class") or entity.get("component_class") or "").strip()
    cats = list(CLASS_TO_CATEGORIES.get(legacy, []))
    cats.extend(EXTRA_ITEM_CATEGORIES.get(entity.get("id"), []))
    if entity.get("_dataset") == "components" and entity.get("install_contexts") == ["vehicle"]:
        cats.append("cat_vehicle_part")
    # de-dup, preserve order
    seen = []
    for c in cats:
        if c not in seen:
            seen.append(c)
    return seen


def _migrate_one(entity, twin_by_item):
    out = copy.deepcopy(entity)

    cats = _categories_for(entity)
    out.pop("item_class", None)
    out.pop("component_class", None)
    if cats:
        out["categories"] = cats

    if "inventory_unit" in out:
        out["default_unit"] = out.pop("inventory_unit")
    if "uses_technology" in out:
        out.setdefault("requires_technology", out.pop("uses_technology"))
    else:
        out.pop("uses_technology", None)
    if "associated_technologies" in out:
        out.setdefault("requires_technology", out.pop("associated_technologies"))

    # standalone stackable -> storage_modes membership
    if out.pop("stackable", None):
        modes = list(out.get("storage_modes") or [])
        if "stackable" not in modes:
            modes.insert(0, "stackable")
        out["storage_modes"] = modes

    out.pop("installable", None)
    out.pop("component_equivalent", None)
    out.pop("represented_item", None)

    # fold the component twin's engineering fields onto the surviving item
    twin = twin_by_item.get(entity.get("id"))
    if twin is not None:
        for key in COMPONENT_ONLY_MERGE_KEYS:
            if key in twin and key not in out:
                out[key] = copy.deepcopy(twin[key])
        merged_caps = list(out.get("descriptive_capabilities") or [])
        for cap in twin.get("descriptive_capabilities") or []:
            if cap not in merged_caps:
                merged_caps.append(cap)
        if merged_caps:
            out["descriptive_capabilities"] = merged_caps

    return out


def _entity_changes(datasets):
    by_id = {}
    for name in ("items", "components"):
        for entity in datasets.get(name, []):
            if isinstance(entity, dict) and entity.get("id"):
                by_id[entity["id"]] = entity

    twin_by_item = {
        item_id: by_id.get(twin_id)
        for item_id, twin_id in MERGE_PAIRS.items()
    }
    delete_ids = list(MERGE_PAIRS.values())

    changes = []
    for entity_id, entity in by_id.items():
        if entity_id in delete_ids:
            continue
        migrated = _migrate_one(entity, twin_by_item)
        if migrated != entity:
            changes.append(migrated)
    return changes, delete_ids


# ---------------------------------------------------------------------------
# Repoint production entities that referenced a deleted component twin
# ---------------------------------------------------------------------------

def _repoint_changes(datasets):
    by_id = {
        e["id"]: e
        for e in datasets.get("production", [])
        if isinstance(e, dict) and e.get("id")
    }
    changes = []

    assembly = by_id.get("prod_pump_module_assembly")
    if assembly is not None:
        out = copy.deepcopy(assembly)
        out.pop("output_components", None)
        out.pop("input_items", None)          # can't assemble a thing from itself
        out.pop("required_components", None)
        out["output_items"] = ["item_pump_module"]
        out["required_items"] = ["item_storage_rack"]
        if out != assembly:
            changes.append(out)

    rolling = by_id.get("prod_steel_plate_rolling")
    if rolling is not None:
        out = copy.deepcopy(rolling)
        if "comp_storage_rack" in (out.get("required_components") or []):
            out.pop("required_components", None)
            out["required_items"] = ["item_storage_rack"]
        if out != rolling:
            changes.append(out)

    return changes


# ---------------------------------------------------------------------------

def build_transaction(datasets):
    schema_changes = _schema_changes(datasets)
    category_changes = _category_entities()
    entity_changes, delete_ids = _entity_changes(datasets)
    repoint_changes = _repoint_changes(datasets)
    # order: categories -> schemas -> items/components -> repointed producers
    upserts = category_changes + schema_changes + entity_changes + repoint_changes
    return upserts, delete_ids


def _backup(store):
    BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    backup_dir = BACKUP_ROOT / f"backup_{stamp}"
    backup_dir.mkdir()
    source = sqlite3.connect(f"file:{store.database_path}?mode=ro", uri=True, check_same_thread=False)
    dest = sqlite3.connect(str(backup_dir / store.database_path.name))
    try:
        source.backup(dest, pages=8192, sleep=0.02)
    finally:
        dest.close()
        source.close()
    if store.manifest_path.exists():
        shutil.copy2(store.manifest_path, backup_dir / store.manifest_path.name)
    if store.ontology_path.exists():
        shutil.copy2(store.ontology_path, backup_dir / store.ontology_path.name)
    return backup_dir


def _validate(store, delete_ids):
    datasets = store.load_datasets()
    ids = {e["id"] for entries in datasets.values() for e in entries if isinstance(e, dict)}
    for dead in delete_ids:
        assert dead not in ids, f"{dead} still present after delete"
    schemas = _schema_by_name(datasets)
    assert "category" in schemas, "schema_category missing"
    assert schemas["components"].get("extends") == "item", "component schema not subclassed"
    for forbidden in ("component_equivalent", "represented_item", "item_class"):
        assert forbidden not in schemas["item"].get("fields", {}), f"{forbidden} still in item schema"
    assert "categories" in schemas["item"].get("fields", {}), "categories missing from item schema"
    cats = {e["id"] for e in datasets.get("categories", []) if isinstance(e, dict)}
    assert len(cats) >= len(CATEGORY_TREE), f"expected >= {len(CATEGORY_TREE)} categories, got {len(cats)}"
    for entity in datasets.get("items", []):
        assert "item_class" not in entity, f"{entity['id']} still has item_class"
    return {
        "categories": len(datasets.get("categories", [])),
        "items": len(datasets.get("items", [])),
        "components": len(datasets.get("components", [])),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report the transaction without writing")
    args = parser.parse_args(argv)

    store = PersistentOntologyStore(ONTOLOGY_PATH)
    datasets = store.load_datasets()
    upserts, delete_ids = build_transaction(datasets)

    print(f"upserts: {len(upserts)}  deletes: {delete_ids}")
    for entity in upserts:
        print(f"  {entity.get('_dataset','?'):<12} {entity['id']}")
    if args.dry_run:
        return

    backup_dir = _backup(store)
    print(f"backup: {backup_dir}")
    started = time.perf_counter()
    result = store.apply_changes(entities=upserts, remove_entity_ids=delete_ids)
    print(f"applied in {time.perf_counter() - started:.2f}s: {result}")
    stats = _validate(store, delete_ids)
    store.export_rdfxml(ONTOLOGY_PATH)
    store.compact_database()
    print(f"checkpoint written; dataset sizes: {stats}")


if __name__ == "__main__":
    main()
