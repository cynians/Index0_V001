"""Build the dependency-free runtime material reference from world-gen catalogs."""

import ast
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from simulations.world_gen.natural_materials import natural_material_entries
from simulations.world_gen.material_catalog import (
    ATMOSPHERIC_MATERIAL_CATALOG as EXTENDED_ATMOSPHERIC_MATERIAL_CATALOG,
)


OUTPUT = ROOT / "world" / "reference_data" / "material_catalog_reference.json"
GEOLOGICAL_MATERIAL_TARGET = 200
CONCRETE_MATERIAL_TARGET = 322


def _curated_material_catalog():
    source = ROOT / "world" / "material_reference_models.py"
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    for statement in tree.body:
        if not isinstance(statement, ast.Assign):
            continue
        if any(
            isinstance(target, ast.Name)
            and target.id == "_CURATED_MATERIALS"
            for target in statement.targets
        ):
            return ast.literal_eval(statement.value)
    raise ValueError("_CURATED_MATERIALS was not found")


def _parent_for_natural(material):
    return {
        "mineral": "mat_natural_mineral",
        "rock": "mat_natural_rock",
        "sediment": "mat_natural_sediment",
        "regolith": "mat_natural_regolith",
    }.get(material.get("material_subclass"), "mat_natural_material")


def _taxonomy_tags(material):
    material_class = material.get("material_class")
    subclass = material.get("material_subclass")
    if material_class == "element":
        tags = [
            "material",
            "chemical_element",
            material.get("element_group", "element"),
            material.get("standard_phase", "unknown_phase"),
        ]
        if material.get("element_group") in {
            "alkali_metal",
            "alkaline_earth_metal",
            "transition_metal",
            "post_transition_metal",
            "lanthanide",
            "actinide",
        }:
            tags.append("metallic")
        return tags
    if subclass == "atmospheric_gas":
        return [
            "material", "natural_material", "atmospheric", "gas", "volatile",
        ]
    return ["material", "natural_material", subclass or "natural_material"]


def _normalize_curated_material(material):
    item = dict(material)
    material_class = item.get("material_class") or "engineered_material"
    biological = material_class == "natural_material"
    property_tags = list(item.get("engineering_property_tags") or [])
    item.setdefault("material_record_schema_version", 2)
    item.setdefault(
        "material_system_role",
        "biological_material" if biological else "engineered_material",
    )
    item.setdefault(
        "natural_distribution_role",
        "biogenic_material" if biological else "manufactured_stock",
    )
    item.setdefault("worldgen_participation", "none")
    item.setdefault(
        "production_role_tags",
        ["biogenic_feedstock"] if biological else [
            "manufactured_stock", "production_intermediate",
        ],
    )
    item.setdefault(
        "resource_origin",
        "biological_harvest" if biological else "industrial_manufacture",
    )
    item.setdefault(
        "recyclability_class",
        "biodegradable"
        if biological
        else "limited_recovery"
        if "difficult_to_recycle" in property_tags
        else "recyclable"
        if "recyclable" in property_tags
        else "process_dependent",
    )
    item.setdefault(
        "material_form",
        "biological_solid" if biological else "engineered_stock",
    )
    item.setdefault("minimum_map_detail_level", None)
    item.setdefault("distribution_scale", "not_naturally_distributed")
    item.setdefault("production_process_tags", [])
    item.setdefault("feedstock_material_ids", [])
    item.setdefault("taxonomy_tags", list(item.get("tags") or []))
    return item


def build():
    materials = []
    for material in natural_material_entries():
        item = dict(material)
        if item.get("material_class") == "element":
            item["canonical_parent"] = "mat_elemental_material"
        elif item.get("material_subclass") == "atmospheric_gas":
            item["canonical_parent"] = "mat_atmospheric_material"
        else:
            item["canonical_parent"] = _parent_for_natural(item)
        item["taxonomy_tags"] = _taxonomy_tags(item)
        materials.append(item)
    existing_ids = {material["id"] for material in materials}
    for material in EXTENDED_ATMOSPHERIC_MATERIAL_CATALOG:
        if (
            material.get("atmosphere_molecule") not in {"H", "O", "Na", "K"}
            or material.get("id") in existing_ids
        ):
            continue
        item = {
            **material,
            "material_class": "natural_material",
            "material_record_schema_version": 2,
            "material_system_role": "atmospheric_material",
            "natural_distribution_role": "atmospheric_constituent",
            "worldgen_participation": "atmospheric_inventory",
            "production_role_tags": [
                "process_gas", "volatile_feedstock", "atomic_vapor_feedstock",
            ],
            "resource_origin": "atmospheric_capture_or_volatile_processing",
            "recyclability_class": "dissipative_or_recapturable",
            "minimum_map_detail_level": 0,
            "distribution_scale": "atmospheric_inventory",
            "material_form": "atmospheric_gas",
            "canonical_parent": "mat_atmospheric_material",
        }
        item["taxonomy_tags"] = _taxonomy_tags(item)
        materials.append(item)
    materials.extend(
        _normalize_curated_material(material)
        for material in _curated_material_catalog()
    )
    material_ids = [material["id"] for material in materials]
    if len(material_ids) != len(set(material_ids)):
        raise ValueError("Duplicate concrete material ids in reference sources")
    if len(materials) != CONCRETE_MATERIAL_TARGET:
        raise ValueError(
            f"Expected {CONCRETE_MATERIAL_TARGET} concrete materials, "
            f"found {len(materials)}"
        )
    geological_count = sum(
        material.get("material_system_role") == "natural_geologic_material"
        for material in materials
    )
    if geological_count != GEOLOGICAL_MATERIAL_TARGET:
        raise ValueError(
            f"Expected {GEOLOGICAL_MATERIAL_TARGET} geological materials, "
            f"found {geological_count}"
        )
    unresolved_formations = [
        material["id"]
        for material in materials
        if (
            material.get("material_system_role") == "natural_geologic_material"
            and (
                material.get("formation_contract_status") != "resolved"
                or not material.get("formation_category")
                or material.get("spatial_representation")
                not in {
                    "bedrock_unit",
                    "surface_cover",
                    "constituent_abundance",
                    "bounded_deposit",
                }
            )
        )
    ]
    if unresolved_formations:
        raise ValueError(
            "Natural geological materials require a resolved formation "
            f"category and spatial representation: {unresolved_formations}"
        )
    payload = {
        "schema_version": 2,
        "concrete_material_count": len(materials),
        "geological_material_count": geological_count,
        "taxonomy_nodes_excluded_from_count": True,
        "sources": [
            "simulations/world_gen/material_catalog.py",
            "simulations/world_gen/natural_materials.py",
            "world/material_reference_models.py::_CURATED_MATERIALS",
        ],
        "materials": materials,
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return payload


if __name__ == "__main__":
    result = build()
    print(f"Wrote {OUTPUT} ({len(result['materials'])} material definitions)")
