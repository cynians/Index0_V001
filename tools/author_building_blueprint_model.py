"""Introduce the building blueprint model and rebuild the lumber compound.

One-way ontology authoring utility for the building system
(docs/building_blueprint_concept_v001.md).  As one ``apply_changes``
transaction it:

1. introduces ``schema_building_blueprint`` (dataset ``building_blueprints``);
2. extends ``schema_locations`` with the placed-building fields
   (``building_blueprint``, ``blueprint_position``, ``blueprint_rotation_deg``,
   ``blueprint_room_key``);
3. extends ``schema_materials`` with ``material_texture_set_ref`` (a Pixel
   Studio texture-mode document, the same format tree bark uses);
4. adds six construction materials the blueprints need (timber, brick,
   concrete, gypsum plaster, clay roof tile, corrugated steel sheet);
5. authors blueprints for the four lumber-compound buildings, writes their
   geometry to ``assets/buildings/*.json.gz``, and re-points the existing
   building locations at them (``building_blueprint`` + position), so Site
   Simulation walls and doorways now come from blueprint geometry.

Existing entities are always merged from their full current dict -- the
store replaces whole entities.  Re-runnable: a second run re-emits the same
records.  The ``.owl`` checkpoint is only exported with ``--export-checkpoint``.
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

from simulations.building import blueprint_model as bm
from simulations.building.blueprint_store import (
    BlueprintAssetStore,
    default_asset_path,
    updated_blueprint_entity,
)
from world.persistent_ontology_store import PersistentOntologyStore


ONTOLOGY_PATH = PROJECT_ROOT / "ontology" / "index0.owl"
BACKUP_ROOT = PROJECT_ROOT / "artifacts" / "building_blueprint_model"
SECTION = "Building Blueprint"

SCHEMA_BUILDING_BLUEPRINT_FIELDS = {
    "blueprint_asset_path": {
        "type": "string", "section": SECTION, "optional": True,
        "description": "Geometry payload (rooms, openings, fixed items, levels, roof, materials, painted details).",
    },
    "blueprint_fingerprint": {"type": "string", "section": SECTION, "optional": True},
    "blueprint_status": {
        "type": "string", "section": SECTION, "optional": True,
        "description": "draft while editable; released once placed -- edits then fork a new version.",
    },
    "blueprint_version_label": {"type": "string", "section": SECTION, "optional": True},
    "predecessor": {"type": "entity", "target": "building_blueprints", "section": SECTION, "optional": True},
    "successor": {"type": "entity", "target": "building_blueprints", "section": SECTION, "optional": True},
    "building_class": {"type": "string", "section": SECTION, "optional": True},
    "map_color": {"type": "string", "section": SECTION, "optional": True},
    "level_count": {"type": "number", "section": "Floor Space", "optional": True},
    "footprint_area_m2": {"type": "number", "section": "Floor Space", "optional": True},
    "gross_floor_area_m2": {"type": "number", "section": "Floor Space", "optional": True},
    "net_floor_area_m2": {"type": "number", "section": "Floor Space", "optional": True},
    "building_height_m": {"type": "number", "section": "Floor Space", "optional": True},
    "enclosed_volume_m3": {"type": "number", "section": "Floor Space", "optional": True},
    "footprint_width_m": {"type": "number", "section": "Floor Space", "optional": True},
    "footprint_depth_m": {"type": "number", "section": "Floor Space", "optional": True},
    "roof_shape": {"type": "string", "section": "Floor Space", "optional": True},
    "blueprint_rooms": {
        "type": "object_list", "section": "Floor Space", "optional": True,
        "description": "Rooms stay inside the blueprint; placed buildings address them as <building>#room:<key>.",
    },
    "blueprint_fixtures": {"type": "object_list", "section": "Floor Space", "optional": True},
    "fixed_items": {"type": "entity_list", "target": "entity_core", "section": "Floor Space", "optional": True},
    "materials_used": {"type": "entity_list", "target": "materials", "section": "Floor Space", "optional": True},
}

LOCATION_FIELDS = {
    "building_blueprint": {
        "type": "entity", "target": "building_blueprints", "section": "Building", "optional": True,
        "description": "The exact blueprint version this building was placed from.",
    },
    "blueprint_position": {
        "type": "object", "section": "Building", "optional": True,
        "description": "[x, y] in the parent's site metres where the blueprint plan origin lands.",
    },
    "blueprint_rotation_deg": {"type": "number", "section": "Building", "optional": True},
    "blueprint_room_key": {
        "type": "string", "section": "Building", "optional": True,
        "description": "For a materialised room entity: the blueprint room it represents.",
    },
}

MATERIAL_FIELDS = {
    "material_texture_set_ref": {
        "type": "string", "section": "Appearance", "optional": True,
        "description": "Pixel Studio texture-mode document (base tile + character tiles) used on building surfaces.",
    },
}

CONSTRUCTION_MATERIALS = [
    {
        "id": "mat_softwood_timber", "name": "Softwood Timber", "subclass": "timber",
        "parent": "mat_biological_material", "color": [168, 128, 84],
        "feedstock": [], "process": ["felling", "sawing", "kiln_drying"],
        "properties": ["combustible", "renewable", "machinable"],
        "uses": ["framing", "cladding", "flooring", "doors"],
        "wiki": "Sawn and dried conifer wood used for framing, cladding, floors, and doors.",
    },
    {
        "id": "mat_fired_clay_brick", "name": "Fired Clay Brick", "subclass": "structural_ceramic",
        "parent": "mat_engineered_ceramic", "color": [152, 82, 60],
        "feedstock": ["mat_clay"], "process": ["molding", "drying", "kiln_firing"],
        "properties": ["fire_resistant", "load_bearing", "durable"],
        "uses": ["masonry_walls", "facades", "chimneys"],
        "wiki": "Kiln-fired clay units laid in mortar for load-bearing walls and facades.",
    },
    {
        "id": "mat_concrete", "name": "Concrete", "subclass": "cementitious_composite",
        "parent": "mat_engineered_composite", "color": [150, 150, 144],
        "feedstock": ["mat_limestone", "mat_silica_sand"], "process": ["batching", "mixing", "casting", "curing"],
        "properties": ["fire_resistant", "load_bearing", "compressive_strength"],
        "uses": ["foundations", "floor_slabs", "walls"],
        "wiki": "Cement-bound aggregate cast into slabs, foundations, and walls.",
    },
    {
        "id": "mat_gypsum_plaster", "name": "Gypsum Plaster", "subclass": "plaster",
        "parent": "mat_engineered_ceramic", "color": [224, 218, 206],
        "feedstock": ["mat_gypsum"], "process": ["calcining", "mixing", "troweling"],
        "properties": ["fire_resistant", "smooth_finish"],
        "uses": ["interior_wall_finish", "ceilings"],
        "wiki": "Calcined gypsum finish applied to interior walls and ceilings.",
    },
    {
        "id": "mat_clay_roof_tile", "name": "Clay Roof Tile", "subclass": "structural_ceramic",
        "parent": "mat_engineered_ceramic", "color": [146, 66, 50],
        "feedstock": ["mat_clay"], "process": ["pressing", "drying", "kiln_firing"],
        "properties": ["weatherproof", "fire_resistant", "durable"],
        "uses": ["pitched_roofs"],
        "wiki": "Fired clay tiles overlapped on pitched roofs.",
    },
    {
        "id": "mat_corrugated_steel_sheet", "name": "Corrugated Steel Sheet", "subclass": "sheet_metal",
        "parent": "mat_engineered_metal", "color": [132, 140, 146],
        "feedstock": ["mat_carbon_steel"], "process": ["rolling", "galvanizing", "corrugating"],
        "properties": ["weatherproof", "lightweight", "recyclable"],
        "uses": ["industrial_roofs", "industrial_cladding"],
        "wiki": "Galvanized, corrugated steel sheet for industrial roofs and cladding.",
    },
]

TIMBER = "mat_softwood_timber"
BRICK = "mat_fired_clay_brick"
CONCRETE = "mat_concrete"
PLASTER = "mat_gypsum_plaster"
TILE = "mat_clay_roof_tile"
STEEL_SHEET = "mat_corrugated_steel_sheet"
GLASS = "mat_soda_lime_glass"


def _window(key, center, width=1.2, sill=0.9, head=2.1):
    return {"key": key, "center": center, "opening_class": "window", "width_m": width, "sill_m": sill, "head_m": head}


def lumber_blueprints():
    """(blueprint entity fields, blueprint payload, building id, plan origin)."""

    barracks = {
        "blueprint_id": "bp_lumber_worker_barracks",
        "display_name": "Lumber Worker Barracks",
        "levels": [{"key": "L0", "name": "Ground floor", "elevation_m": 0.0, "height_m": 3.0}],
        "rooms": [{"key": "r001", "level": "L0", "name": "Dormitory", "points": [[0, 0], [22, 0], [22, 12], [0, 12]]}],
        "openings": [
            {"key": "o001", "center": [0, 6], "opening_class": "double_door", "width_m": 3.0},
            {"key": "o002", "center": [17, 12], "opening_class": "doorway", "width_m": 3.0},
            _window("o003", [3, 0]), _window("o004", [7, 0]), _window("o005", [11, 0]),
            _window("o006", [15, 0]), _window("o007", [19, 0]),
            _window("o008", [4, 12]), _window("o009", [9, 12]),
            _window("o010", [22, 4]), _window("o011", [22, 8]),
        ],
        "roof": {"shape": "gable", "pitch_deg": 25, "ridge_axis": "x", "overhang_m": 0.4},
        "default_materials": {
            "facade": TIMBER, "interior_wall": PLASTER, "floor": TIMBER, "ceiling": PLASTER,
            "roof": TILE, "window": GLASS, "door": TIMBER,
        },
    }
    kitchen = {
        "blueprint_id": "bp_lumber_attached_kitchen",
        "display_name": "Attached Barracks Kitchen",
        "levels": [{"key": "L0", "name": "Ground floor", "elevation_m": 0.0, "height_m": 3.0}],
        "rooms": [{"key": "r001", "level": "L0", "name": "Kitchen", "points": [[0, 0], [10, 0], [10, 8], [0, 8]]}],
        "openings": [
            {"key": "o001", "center": [5, 0], "opening_class": "doorway", "width_m": 3.0},
            {"key": "o002", "center": [5, 8], "opening_class": "double_door", "width_m": 2.0},
            _window("o003", [10, 4], width=1.5),
            _window("o004", [0, 4], width=1.5),
        ],
        "fixtures": [
            {"key": "f001", "ref": "component_kitchen_sink", "position": [9.4, 2.5], "rotation_deg": 90, "size_m": [1.2, 0.6]},
            {"key": "f002", "ref": "component_electric_oven", "position": [9.4, 5.5], "rotation_deg": 90, "size_m": [0.6, 0.6]},
        ],
        "roof": {"shape": "shed", "pitch_deg": 10, "ridge_axis": "x", "overhang_m": 0.3},
        "default_materials": {
            "facade": BRICK, "interior_wall": PLASTER, "floor": CONCRETE, "ceiling": PLASTER,
            "roof": TILE, "window": GLASS, "door": TIMBER,
        },
    }
    storage = {
        "blueprint_id": "bp_lumber_storage_shed",
        "display_name": "Lumber Storage Shed",
        "levels": [{"key": "L0", "name": "Ground floor", "elevation_m": 0.0, "height_m": 4.5}],
        "rooms": [{"key": "r001", "level": "L0", "name": "Lumber Store", "points": [[0, 0], [14, 0], [14, 14], [0, 14]]}],
        "openings": [
            {"key": "o001", "center": [0, 7], "opening_class": "loading_door", "width_m": 4.0},
            _window("o002", [14, 7], width=2.0, sill=2.2, head=3.4),
        ],
        "fixtures": [
            {"key": "f001", "ref": "item_storage_rack", "position": [12.9, 3.0], "rotation_deg": 0, "size_m": [0.9, 2.4]},
            {"key": "f002", "ref": "item_storage_rack", "position": [12.9, 7.0], "rotation_deg": 0, "size_m": [0.9, 2.4]},
            {"key": "f003", "ref": "item_storage_rack", "position": [12.9, 11.0], "rotation_deg": 0, "size_m": [0.9, 2.4]},
        ],
        "roof": {"shape": "gable", "pitch_deg": 20, "ridge_axis": "y", "overhang_m": 0.5},
        "default_materials": {
            "facade": TIMBER, "interior_wall": TIMBER, "floor": CONCRETE, "ceiling": TIMBER,
            "roof": STEEL_SHEET, "window": GLASS, "door": TIMBER,
        },
    }
    factory = {
        "blueprint_id": "bp_lumber_factory_hall",
        "display_name": "Lumber Factory Hall",
        "levels": [{"key": "L0", "name": "Ground floor", "elevation_m": 0.0, "height_m": 6.0}],
        "rooms": [{"key": "r001", "level": "L0", "name": "Sawmill Hall", "points": [[0, 0], [18, 0], [18, 18], [0, 18]]}],
        "openings": [
            {"key": "o001", "center": [0, 8], "opening_class": "loading_door", "width_m": 4.0, "head_m": 4.0},
            _window("o002", [3, 0], width=2.0, sill=3.2, head=4.6),
            _window("o003", [7, 0], width=2.0, sill=3.2, head=4.6),
            _window("o004", [11, 0], width=2.0, sill=3.2, head=4.6),
            _window("o005", [15, 0], width=2.0, sill=3.2, head=4.6),
            _window("o006", [18, 5], width=2.0, sill=3.2, head=4.6),
            _window("o007", [18, 13], width=2.0, sill=3.2, head=4.6),
        ],
        "roof": {"shape": "shed", "pitch_deg": 12, "ridge_axis": "x", "overhang_m": 0.4},
        "default_materials": {
            "facade": STEEL_SHEET, "interior_wall": STEEL_SHEET, "floor": CONCRETE, "ceiling": STEEL_SHEET,
            "roof": STEEL_SHEET, "window": GLASS, "door": STEEL_SHEET,
        },
    }
    return [
        ({"building_class": "barracks", "map_color": "#536271",
          "wiki": "Single-storey timber dormitory for the lumber compound's workers."},
         barracks, "location_lumber_test_barracks", (8.0, -22.0)),
        ({"building_class": "attached kitchen", "map_color": "#6e6252",
          "wiki": "Brick kitchen attached to the barracks' south wall; the sink and oven are fixed items."},
         kitchen, "location_person_test_kitchen", (20.0, -10.0)),
        ({"building_class": "warehouse", "map_color": "#625a49",
          "wiki": "Tall timber shed with a loading door and fixed storage racks."},
         storage, "location_lumber_test_storage", (8.0, 8.0)),
        ({"building_class": "factory hall", "map_color": "#58616a",
          "wiki": "Steel-clad sawmill hall with clerestory windows and an industrial loading door."},
         factory, "location_lumber_test_factory", (26.0, 2.0)),
    ]


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

    if entity is None:
        return None
    materialize = getattr(entity, "materialize", None)
    if callable(materialize):
        entity = materialize()
    return copy.deepcopy(dict(entity))


def _entities_by_id(datasets):
    return {
        entity["id"]: entity
        for records in datasets.values() if isinstance(records, list)
        for entity in records if isinstance(entity, dict) and entity.get("id")
    }


def _material_record(spec, existing):
    record = _plain(existing) if existing else {}
    record.update({
        "id": spec["id"],
        "_dataset": "materials",
        "type": "material",
        "name": spec["name"],
        "pretty_name": spec["name"],
        "material_class": "engineered_material",
        "material_system_role": "engineered_material",
        "material_subclass": spec["subclass"],
        "material_form": "engineered_stock",
        "material_hierarchy_system": "chemical_engineering_v2",
        "material_record_schema_version": 2,
        "resource_origin": "industrial_manufacture",
        "natural_distribution_role": "manufactured_stock",
        "distribution_scale": "not_naturally_distributed",
        "worldgen_participation": "none",
        "recyclability_class": record.get("recyclability_class") or "recoverable_bulk_material",
        "canonical_parent": spec["parent"],
        "parents": [spec["parent"]],
        "display_color": spec["color"],
        "feedstock_material_ids": list(spec["feedstock"]),
        "production_process_tags": list(spec["process"]),
        "production_role_tags": ["manufactured_stock", "construction_material"],
        "engineering_property_tags": list(spec["properties"]),
        "common_uses": list(spec["uses"]),
        "tags": ["material", "engineered_material", "construction_material", spec["subclass"]],
        "wiki_entry": spec["wiki"],
        "entry_status": record.get("entry_status") or "draft",
    })
    return record


def build_transaction(datasets, store=None):
    """Return (upserts, asset writes) without touching disk."""

    schemas = _schema_by_name(datasets)
    by_id = _entities_by_id(datasets)
    upserts = []

    if "building_blueprint" in schemas:
        schema = _plain(schemas["building_blueprint"])
        schema["fields"] = {**dict(schema.get("fields") or {}), **copy.deepcopy(SCHEMA_BUILDING_BLUEPRINT_FIELDS)}
    else:
        schema = {
            "id": "schema_building_blueprint",
            "_dataset": "schemas",
            "type": "schema",
            "schema": "building_blueprint",
            "name": "building_blueprint",
            "pretty_name": "Building Blueprint",
            "extends": "entity_core",
            "fields": copy.deepcopy(SCHEMA_BUILDING_BLUEPRINT_FIELDS),
        }
    upserts.append(schema)

    for schema_name, fields in (("locations", LOCATION_FIELDS), ("materials", MATERIAL_FIELDS)):
        existing = schemas.get(schema_name)
        if existing is None:
            raise RuntimeError(f"schema_{schema_name} is missing from the ontology")
        updated = _plain(existing)
        updated["fields"] = {**dict(updated.get("fields") or {}), **copy.deepcopy(fields)}
        upserts.append(updated)

    for spec in CONSTRUCTION_MATERIALS:
        upserts.append(_material_record(spec, by_id.get(spec["id"])))

    assets = []
    for extra, payload, building_id, origin in lumber_blueprints():
        blueprint = bm.normalize_blueprint(payload)
        blueprint_id = blueprint["blueprint_id"]
        asset_path = default_asset_path(blueprint_id)
        existing = _plain(by_id.get(blueprint_id)) or {}
        entity = {
            **existing,
            "id": blueprint_id,
            "_dataset": "building_blueprints",
            "type": "building_blueprint",
            "name": blueprint["display_name"],
            "pretty_name": blueprint["display_name"],
            "blueprint_version_label": existing.get("blueprint_version_label") or "Mk I",
            "blueprint_status": "released",
            "building_class": extra["building_class"],
            "map_color": extra["map_color"],
            "wiki_entry": extra["wiki"],
            "entry_status": existing.get("entry_status") or "draft",
        }
        upserts.append(updated_blueprint_entity(entity, blueprint, asset_path))
        assets.append((blueprint, asset_path))

        building = by_id.get(building_id)
        if building is None:
            raise RuntimeError(f"{building_id} is missing; run tools/author_person_food_ownership_model.py first")
        building = _plain(building)
        derived = bm.derive_geometry(blueprint)
        footprint = bm.placed_footprint(derived, origin, 0.0)
        building.update({
            "building_blueprint": blueprint_id,
            "blueprint_position": [origin[0], origin[1]],
            "blueprint_rotation_deg": 0.0,
            "bounds": {
                "type": "polygon",
                "coordinate_space": "map_world",
                "points": [[round(x, 4), round(y, 4)] for x, y in footprint[0]],
            },
        })
        # Side-based openings are superseded by the blueprint's wall openings.
        building.pop("openings", None)
        upserts.append(building)
    return upserts, assets


def _backup(store, upserts, remove_entity_ids=()):
    """Keep what this run replaces or removes, not a copy of the whole store (``tools/ontology_backup.py``)."""
    from tools.ontology_backup import backup_entities

    return backup_entities(store, BACKUP_ROOT, upserts, remove_entity_ids)


def _validate(store):
    datasets = store.load_datasets()
    schemas = _schema_by_name(datasets)
    assert "building_blueprint" in schemas, "schema_building_blueprint missing"
    assert "building_blueprint" in schemas["locations"].get("fields", {}), "locations.building_blueprint missing"
    assert "material_texture_set_ref" in schemas["materials"].get("fields", {}), "materials texture field missing"
    by_id = _entities_by_id(datasets)
    for _extra, payload, building_id, _origin in lumber_blueprints():
        assert by_id[building_id].get("building_blueprint") == payload["blueprint_id"], building_id
        assert by_id[building_id].get("bounds", {}).get("points"), f"{building_id} bounds lost"
        assert by_id[building_id].get("parent_location"), f"{building_id} lost its parent"
    return {"building_blueprints": len(datasets.get("building_blueprints", []))}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="report the transaction without writing")
    parser.add_argument("--export-checkpoint", action="store_true",
                        help="also export ontology/index0.owl (slow; captures every session's pending edits)")
    args = parser.parse_args(argv)

    store = PersistentOntologyStore(ONTOLOGY_PATH)
    datasets = store.load_datasets()
    upserts, assets = build_transaction(datasets)
    print(f"upserts: {len(upserts)}")
    for entity in upserts:
        print(f"  {entity.get('_dataset', '?'):<20} {entity['id']}")
    for blueprint, asset_path in assets:
        totals = bm.derive_geometry(blueprint)["totals"]
        print(f"  asset {asset_path}: {totals['gross_floor_area_m2']:.1f} m² gross, "
              f"{totals['net_floor_area_m2']:.1f} m² net, {totals['opening_count']} openings")
    if args.dry_run:
        return

    asset_store = BlueprintAssetStore(PROJECT_ROOT)
    for blueprint, asset_path in assets:
        asset_store.save(blueprint, asset_path)
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
