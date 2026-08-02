"""Runtime material taxonomy built from the existing world-generation catalogs.

The material tree answers *what a material is*.  Cross-cutting engineering
properties stay in tags so a material can be filtered as metallic, corrosion
resistant, biological, or heat resistant without acquiring extra parents.
"""

import json
from functools import lru_cache
from pathlib import Path


_TAXONOMY = [
    {"id": "mat_material", "name": "Material", "parent": None, "material_subclass": "material_family", "tags": ["material", "taxonomy_root"]},
    {"id": "mat_elemental_material", "name": "Elemental Material", "parent": "mat_material", "material_subclass": "material_family", "tags": ["material", "chemical_element"]},
    {"id": "mat_natural_material", "name": "Natural Material", "parent": "mat_material", "material_subclass": "material_family", "tags": ["material", "natural_material"]},
    {"id": "mat_natural_mineral", "name": "Mineral", "parent": "mat_natural_material", "material_subclass": "material_family", "tags": ["material", "natural_material", "mineral"]},
    {"id": "mat_natural_rock", "name": "Rock", "parent": "mat_natural_material", "material_subclass": "material_family", "tags": ["material", "natural_material", "rock"]},
    {"id": "mat_natural_sediment", "name": "Sediment", "parent": "mat_natural_material", "material_subclass": "material_family", "tags": ["material", "natural_material", "sediment"]},
    {"id": "mat_natural_regolith", "name": "Regolith", "parent": "mat_natural_material", "material_subclass": "material_family", "tags": ["material", "natural_material", "regolith"]},
    {"id": "mat_atmospheric_material", "name": "Atmospheric Material", "parent": "mat_natural_material", "material_subclass": "material_family", "tags": ["material", "natural_material", "atmospheric", "gas"]},
    {"id": "mat_biological_material", "name": "Biological Material", "parent": "mat_natural_material", "material_subclass": "material_family", "tags": ["material", "natural_material", "biological"]},
    {"id": "mat_bone", "name": "Bone", "parent": "mat_biological_material", "material_subclass": "biological_tissue", "tags": ["material", "biological", "bone", "biogenic_composite"]},
    {"id": "mat_engineered_material", "name": "Engineered Material", "parent": "mat_material", "material_subclass": "material_family", "tags": ["material", "engineered_material"]},
    {"id": "mat_engineered_metal", "name": "Metal and Alloy", "parent": "mat_engineered_material", "material_subclass": "material_family", "tags": ["material", "engineered_material", "metallic"]},
    {"id": "mat_metal_alloy", "name": "Metal Alloy", "parent": "mat_engineered_metal", "material_subclass": "alloy", "tags": ["material", "engineered_material", "metallic", "alloy"]},
    {"id": "mat_ferrous_alloy", "name": "Ferrous Alloy", "parent": "mat_metal_alloy", "material_subclass": "alloy", "tags": ["material", "metallic", "alloy", "ferrous", "iron_alloy"]},
    {"id": "mat_steel", "name": "Steel", "parent": "mat_ferrous_alloy", "material_subclass": "steel", "tags": ["material", "metallic", "alloy", "ferrous", "iron_alloy", "steel"]},
    {"id": "mat_engineered_polymer", "name": "Polymer", "parent": "mat_engineered_material", "material_subclass": "material_family", "tags": ["material", "engineered_material", "polymer"]},
    {"id": "mat_engineered_ceramic", "name": "Ceramic", "parent": "mat_engineered_material", "material_subclass": "material_family", "tags": ["material", "engineered_material", "ceramic"]},
    {"id": "mat_engineered_composite", "name": "Composite", "parent": "mat_engineered_material", "material_subclass": "material_family", "tags": ["material", "engineered_material", "composite"]},
]


_CURATED_MATERIALS = [
    {
        "id": "mat_elephant_bone", "name": "Elephant Bone", "canonical_parent": "mat_bone",
        "material_class": "natural_material", "material_subclass": "biological_tissue",
        "tags": ["material", "natural_material", "biological", "bone", "mammalian", "elephant_derived", "biogenic_composite"],
        "engineering_property_tags": ["biobased", "biodegradable", "combustible", "calcium_phosphate_rich"],
        "production_process_tags": ["biological_recovery", "cleaning", "cutting"],
    },
    {
        "id": "mat_whale_bone", "name": "Whale Bone", "canonical_parent": "mat_bone",
        "material_class": "natural_material", "material_subclass": "biological_tissue",
        "tags": ["material", "natural_material", "biological", "bone", "mammalian", "cetacean_derived", "biogenic_composite"],
        "engineering_property_tags": ["biobased", "biodegradable", "combustible", "calcium_phosphate_rich"],
        "production_process_tags": ["biological_recovery", "cleaning", "cutting"],
    },
    {
        "id": "mat_e325_steel", "name": "E325 Steel", "canonical_parent": "mat_steel",
        "material_class": "engineered_material", "material_subclass": "structural_steel",
        "tags": ["material", "engineered_material", "metallic", "alloy", "ferrous", "iron_alloy", "steel", "structural_steel", "e325_grade"],
        "engineering_property_tags": ["structural", "weldable", "strength_grade_specified"],
        "feedstock_material_ids": ["mat_element_fe", "mat_element_c"],
        "production_process_tags": ["steelmaking", "alloying", "casting", "rolling"],
    },
    {
        "id": "mat_stainless_steel", "name": "Stainless Steel", "canonical_parent": "mat_steel",
        "material_class": "engineered_material", "material_subclass": "stainless_steel",
        "tags": ["material", "engineered_material", "metallic", "alloy", "ferrous", "iron_alloy", "steel", "stainless_steel"],
        "engineering_property_tags": ["corrosion_resistant", "oxidation_resistant", "heat_resistance_grade_dependent"],
        "feedstock_material_ids": ["mat_element_fe", "mat_element_cr", "mat_element_ni"],
        "production_process_tags": ["steelmaking", "alloying", "vacuum_refining", "rolling"],
    },
    {
        "id": "mat_acrylate_polymer", "name": "Acrylate Polymer", "canonical_parent": "mat_engineered_polymer",
        "material_class": "engineered_material", "material_subclass": "synthetic_polymer",
        "tags": ["material", "engineered_material", "polymer", "synthetic_polymer", "organic_polymer", "acrylate"],
        "engineering_property_tags": ["lightweight", "corrosion_resistant", "temperature_limited"],
        "feedstock_material_ids": ["mat_element_c", "mat_element_h", "mat_element_o"],
        "production_process_tags": ["monomer_synthesis", "polymerization", "forming"],
    },
    {
        "id": "mat_carbon_steel", "name": "Carbon Steel", "canonical_parent": "mat_steel",
        "material_class": "engineered_material", "material_subclass": "carbon_steel",
        "tags": ["material", "engineered_material", "metallic", "alloy", "ferrous", "iron_alloy", "steel"],
        "engineering_property_tags": ["structural", "weldable", "machinable", "recyclable"],
        "feedstock_material_ids": ["mat_element_fe", "mat_element_c"],
        "production_process_tags": ["ironmaking", "steelmaking", "casting", "rolling"],
    },
    {
        "id": "mat_aluminium_alloy", "name": "Aluminium Alloy", "canonical_parent": "mat_metal_alloy",
        "material_class": "engineered_material", "material_subclass": "aluminium_alloy",
        "tags": ["material", "engineered_material", "metallic", "alloy", "nonferrous", "aluminium_alloy"],
        "engineering_property_tags": ["lightweight", "corrosion_resistant", "formable", "recyclable"],
        "feedstock_material_ids": ["mat_element_al"],
        "production_process_tags": ["refining", "alloying", "casting", "rolling", "extrusion"],
    },
    {
        "id": "mat_titanium_alloy", "name": "Titanium Alloy", "canonical_parent": "mat_metal_alloy",
        "material_class": "engineered_material", "material_subclass": "titanium_alloy",
        "tags": ["material", "engineered_material", "metallic", "alloy", "nonferrous", "titanium_alloy"],
        "engineering_property_tags": ["high_specific_strength", "corrosion_resistant", "heat_resistant", "recyclable"],
        "feedstock_material_ids": ["mat_element_ti"],
        "production_process_tags": ["chlorination", "reduction", "vacuum_melting", "forging"],
    },
    {
        "id": "mat_copper_alloy", "name": "Copper Alloy", "canonical_parent": "mat_metal_alloy",
        "material_class": "engineered_material", "material_subclass": "copper_alloy",
        "tags": ["material", "engineered_material", "metallic", "alloy", "nonferrous", "copper_alloy"],
        "engineering_property_tags": ["electrically_conductive", "thermally_conductive", "formable", "recyclable"],
        "feedstock_material_ids": ["mat_element_cu"],
        "production_process_tags": ["smelting", "electrorefining", "alloying", "casting"],
    },
    {
        "id": "mat_soda_lime_glass", "name": "Soda-Lime Glass", "canonical_parent": "mat_engineered_ceramic",
        "material_class": "engineered_material", "material_subclass": "glass",
        "tags": ["material", "engineered_material", "ceramic", "glass", "silicate_glass"],
        "engineering_property_tags": ["transparent", "electrically_insulating", "chemically_stable", "recyclable"],
        "feedstock_material_ids": ["mat_silica_sand", "mat_calcite"],
        "production_process_tags": ["batching", "melting", "forming", "annealing"],
    },
    {
        "id": "mat_alumina_ceramic", "name": "Alumina Ceramic", "canonical_parent": "mat_engineered_ceramic",
        "material_class": "engineered_material", "material_subclass": "technical_ceramic",
        "tags": ["material", "engineered_material", "ceramic", "oxide_ceramic", "alumina"],
        "engineering_property_tags": ["hard", "wear_resistant", "electrically_insulating", "heat_resistant", "brittle"],
        "feedstock_material_ids": ["mat_bauxite"],
        "production_process_tags": ["refining", "powder_processing", "forming", "sintering"],
    },
    {
        "id": "mat_carbon_fiber_composite", "name": "Carbon-Fiber Composite", "canonical_parent": "mat_engineered_composite",
        "material_class": "engineered_material", "material_subclass": "fiber_reinforced_composite",
        "tags": ["material", "engineered_material", "composite", "carbon_fiber", "polymer_matrix"],
        "engineering_property_tags": ["high_specific_strength", "anisotropic", "fatigue_resistant", "difficult_to_recycle"],
        "feedstock_material_ids": ["mat_element_c", "mat_acrylate_polymer"],
        "production_process_tags": ["fiber_production", "layup", "resin_infusion", "curing"],
    },
    {
        "id": "mat_polyethylene", "name": "Polyethylene", "canonical_parent": "mat_engineered_polymer",
        "material_class": "engineered_material", "material_subclass": "thermoplastic",
        "tags": ["material", "engineered_material", "polymer", "synthetic_polymer", "thermoplastic", "polyolefin"],
        "engineering_property_tags": ["lightweight", "chemically_resistant", "electrically_insulating", "recyclable"],
        "feedstock_material_ids": ["mat_methane_gas"],
        "production_process_tags": ["steam_cracking", "monomer_separation", "polymerization", "pelletizing", "forming"],
    },
]


@lru_cache(maxsize=1)
def _catalog_reference():
    path = Path(__file__).resolve().parent / "reference_data" / "material_catalog_reference.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _runtime_entity_store(target):
    if hasattr(target, "entities"):
        entities = getattr(target, "entities", {})
        datasets = getattr(target, "datasets", None)
        if not isinstance(datasets, dict):
            datasets = {}
            target.datasets = datasets
        return entities, datasets
    return target, {}


def _string_list(value):
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item or "").strip()]
    return []


def _merged_tags(*values):
    merged = []
    for value in values:
        for tag in _string_list(value):
            if tag not in merged:
                merged.append(tag)
    return merged


def material_matches_tags(material, required_tags=(), excluded_tags=()):
    """Return whether a material fulfils a production-oriented tag query.

    Both classification and engineering-property tags participate.  This keeps
    property filtering independent of the material's single tree parent.
    """
    if not isinstance(material, dict):
        return False
    tags = set(_merged_tags(
        material.get("tags"),
        material.get("engineering_property_tags"),
        material.get("production_role_tags"),
        material.get("production_process_tags"),
    ))
    return (
        set(_string_list(required_tags)).issubset(tags)
        and not tags.intersection(_string_list(excluded_tags))
    )


def _ensure_dataset_entry(dataset, entity):
    entity_id = entity.get("id") if isinstance(entity, dict) else None
    if entity_id and not any(isinstance(item, dict) and item.get("id") == entity_id for item in dataset):
        dataset.append(entity)


def _children_tree(entity_id, children_by_parent, ancestry=None):
    ancestry = set(ancestry or [])
    if entity_id in ancestry:
        return []
    ancestry.add(entity_id)
    result = []
    for child_id in children_by_parent.get(entity_id, []):
        node = {"id": child_id}
        descendants = _children_tree(child_id, children_by_parent, ancestry)
        if descendants:
            node["offspring"] = descendants
        result.append(node)
    return result


def _refresh_offspring(materials_by_id):
    children_by_parent = {}
    for entity_id, entity in materials_by_id.items():
        parents = _string_list(entity.get("parents"))
        if len(parents) != 1 or parents[0] not in materials_by_id:
            continue
        children_by_parent.setdefault(parents[0], []).append(entity_id)
    for child_ids in children_by_parent.values():
        child_ids.sort()
    changed = False
    for entity_id, entity in materials_by_id.items():
        offspring = _children_tree(entity_id, children_by_parent)
        if entity.get("offspring") != offspring:
            entity["offspring"] = offspring
            changed = True
    return changed


def _reference_entry(record):
    material_class = record.get("material_class") or "natural_material"
    is_family = material_class == "material_family"
    entry = {
        "id": record["id"],
        "name": record.get("name") or record["id"],
        "pretty_name": record.get("name") or record["id"],
        "type": "material",
        "_dataset": "materials",
        "material_class": material_class,
        "material_subclass": record.get("material_subclass") or "material",
        "parents": [record["canonical_parent"]],
        "canonical_parent": record["canonical_parent"],
        "tags": _merged_tags(record.get("taxonomy_tags"), record.get("tags")),
        "engineering_property_tags": _string_list(record.get("engineering_property_tags")),
        "production_role_tags": _string_list(record.get("production_role_tags")),
        "production_process_tags": _string_list(record.get("production_process_tags")),
        "feedstock_material_ids": _string_list(record.get("feedstock_material_ids")),
        "material_record_schema_version": int(
            record.get("material_record_schema_version", 2) or 2
        ),
        "material_system_role": (
            record.get("material_system_role")
            or ("material_family" if is_family else material_class)
        ),
        "natural_distribution_role": (
            record.get("natural_distribution_role")
            or ("not_applicable" if is_family else "unspecified")
        ),
        "worldgen_participation": (
            record.get("worldgen_participation")
            or ("none" if is_family else "unspecified")
        ),
        "resource_origin": (
            record.get("resource_origin")
            or ("taxonomy" if is_family else "unspecified")
        ),
        "recyclability_class": (
            record.get("recyclability_class")
            or ("not_applicable" if is_family else "process_dependent")
        ),
        "material_reference_generated": True,
        "material_hierarchy_system": "chemical_engineering_v2",
    }
    for field in (
        "scientific_name", "scientific_classification", "chemical_formula",
        "element_symbol", "element_group", "atomic_number", "rarity",
        "standard_phase", "display_color", "molar_mass_kg_mol", "material_form",
        "minimum_map_detail_level", "distribution_scale",
        "formation_category", "formation_process", "spatial_representation",
        "formation_requirements", "formation_contract_status",
        "optical_surface_profile",
    ):
        if record.get(field) is not None:
            entry[field] = record[field]
    return entry


def _apply_reference_fields(entity, reference, *, force_parent=False):
    changed = False
    for field, value in reference.items():
        if field in {"id", "_dataset", "offspring"}:
            continue
        if field == "tags":
            value = _merged_tags(entity.get("tags"), value)
        elif field in {
            "engineering_property_tags",
            "production_role_tags",
            "production_process_tags",
            "feedstock_material_ids",
        }:
            value = _merged_tags(entity.get(field), value)
        elif field == "parents" and not (force_parent or not _string_list(entity.get("parents"))):
            continue
        elif field not in {"parents", "canonical_parent", "material_hierarchy_system"} and entity.get(field) not in (None, "", [], {}):
            continue
        if entity.get(field) != value:
            entity[field] = value
            changed = True
    return changed


def apply_material_reference_models(target):
    """Populate and normalize the runtime materials dataset.

    This is intentionally a load-time projection like the Earth reference
    models.  It keeps the ontology concise while making every world-generation
    material available as a named material record.
    """
    entities, datasets = _runtime_entity_store(target)
    if not isinstance(entities, dict) or not isinstance(datasets, dict):
        return False

    changed = False
    materials = datasets.setdefault("materials", [])
    if not isinstance(materials, list):
        return False
    for legacy in datasets.get("material", []) if isinstance(datasets.get("material"), list) else []:
        if not isinstance(legacy, dict) or not legacy.get("id"):
            continue
        legacy["_dataset"] = "materials"
        entities[legacy["id"]] = legacy
        _ensure_dataset_entry(materials, legacy)

    records = []
    for node in _TAXONOMY:
        record = _reference_entry({
            "id": node["id"], "name": node["name"], "material_class": "material_family",
            "material_subclass": node["material_subclass"], "canonical_parent": node["parent"],
            "tags": node["tags"], "engineering_property_tags": [],
        })
        if not node["parent"]:
            record["parents"] = []
        records.append(record)
    catalog = _catalog_reference().get("materials") or []
    records.extend(
        _reference_entry(record)
        for record in catalog
        if isinstance(record, dict) and record.get("id")
    )

    for record in records:
        entity_id = record.get("id")
        entity = entities.get(entity_id)
        if not isinstance(entity, dict):
            entity = dict(record)
            entities[entity_id] = entity
            changed = True
        else:
            changed = _apply_reference_fields(
                entity, record,
                force_parent=bool(entity.get("material_reference_generated")),
            ) or changed
        entity["_dataset"] = "materials"
        entity.setdefault("type", "material")
        _ensure_dataset_entry(materials, entity)

    materials_by_id = {
        entity_id: entity
        for entity_id, entity in entities.items()
        if isinstance(entity, dict) and entity.get("_dataset") == "materials"
    }
    changed = _refresh_offspring(materials_by_id) or changed
    return changed
