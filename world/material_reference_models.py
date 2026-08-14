"""Shared material taxonomy shape and generic tag-query helpers.

Concrete materials are durably authored in the ontology and load like any
other entity type. No Python or JSON concrete-material registry lives here.
Any runtime taxonomy or material mapping is a disposable ontology-derived
cache. Generated worlds are currently disposable, so material/worldgen
contract changes do not require legacy-world migration.
"""


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
    """Shape a catalog record into the entity dict form persisted to the ontology."""
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
        "standard_phase", "display_color", "geological_map_color",
        "molar_mass_kg_mol", "material_form",
        "minimum_map_detail_level", "distribution_scale",
        "formation_category", "formation_process", "spatial_representation",
        "formation_requirements", "formation_contract_status",
        "optical_surface_profile",
        # World-gen selection inputs. These aren't card/UI content, but the
        # ontology individual is the durable record now, so they have to
        # round-trip through it losslessly for natural_material_entries() to
        # rebuild the same candidate-selection data it used to compute live.
        "required_element_thresholds", "required_element_groups",
        "favorable_planet_tags", "atmosphere_molecule", "band_color",
        "surface_affinity_profile",
        "mechanical_class", "mechanical_rock_profile",
    ):
        if record.get(field) is not None:
            entry[field] = record[field]
    return entry
