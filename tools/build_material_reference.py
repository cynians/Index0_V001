"""Build the dependency-free runtime material reference from world-gen catalogs."""

import ast
import json
import runpy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "world" / "reference_data" / "material_catalog_reference.json"


def _natural_material_catalog():
    source = ROOT / "simulations" / "world_gen" / "natural_materials.py"
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    for statement in tree.body:
        if not isinstance(statement, ast.Assign):
            continue
        if any(isinstance(target, ast.Name) and target.id == "NATURAL_MATERIAL_CATALOG" for target in statement.targets):
            return ast.literal_eval(statement.value)
    raise ValueError("NATURAL_MATERIAL_CATALOG was not found")


def _parent_for_natural(material):
    return {
        "mineral": "mat_natural_mineral",
        "rock": "mat_natural_rock",
        "sediment": "mat_natural_sediment",
        "regolith": "mat_natural_regolith",
    }.get(material.get("material_subclass"), "mat_natural_material")


def build():
    catalog = runpy.run_path(str(ROOT / "simulations" / "world_gen" / "material_catalog.py"))
    materials = []
    for material in catalog["ELEMENT_MATERIAL_CATALOG"]:
        item = dict(material)
        item["canonical_parent"] = "mat_elemental_material"
        tags = ["material", "chemical_element", item.get("element_group", "element"), item.get("standard_phase", "unknown_phase")]
        if item.get("element_group") in {
            "alkali_metal",
            "alkaline_earth_metal",
            "transition_metal",
            "post_transition_metal",
            "lanthanide",
            "actinide",
        }:
            tags.append("metallic")
        item["taxonomy_tags"] = tags
        materials.append(item)
    for material in catalog["ATMOSPHERIC_MATERIAL_CATALOG"]:
        item = dict(material)
        item["canonical_parent"] = "mat_atmospheric_material"
        item["taxonomy_tags"] = ["material", "natural_material", "atmospheric", "gas", "volatile"]
        materials.append(item)
    for material in _natural_material_catalog():
        item = dict(material)
        item["material_class"] = item.get("material_class") or "natural_material"
        item["canonical_parent"] = _parent_for_natural(item)
        item["taxonomy_tags"] = ["material", "natural_material", item.get("material_subclass", "natural_material")]
        materials.append(item)
    payload = {
        "schema_version": 1,
        "sources": [
            "simulations/world_gen/material_catalog.py",
            "simulations/world_gen/natural_materials.py",
        ],
        "materials": materials,
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return payload


if __name__ == "__main__":
    result = build()
    print(f"Wrote {OUTPUT} ({len(result['materials'])} material definitions)")
