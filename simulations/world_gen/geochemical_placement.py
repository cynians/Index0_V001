"""Element-conserving, worldgen-owned material bodies.

Material cards describe substances.  Generated location cards describe where
that substance formed on one world.  LOD0 provinces (connected regions of one
dominant lithotectonic setting) are produced with the planetary material
product in ``material_lod``; this module owns the card shape, the element
budget partition, the pre-heightfield substrate prior and the regional
chemistry inventory.  The compact province model is the scientific input for
raster views; the raster is never the placement authority.
"""

from __future__ import annotations

import math

from simulations.world_gen.map_seed import seed_range
from simulations.world_gen.natural_materials import (
    _element_abundance_map,
    _group_score,
    _threshold_score,
)
from simulations.world_gen import natural_materials


PLACEMENT_VERSION = "geochemical-material-placements-v2-lithotectonic"


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, float(value)))


def _local_element_profiles(global_elements, sources, map_seed):
    """Partition a conserved crust inventory over area-weighted sources.

    Felsic elements concentrate in continental sources, mafic ones in oceanic
    sources; the area-weighted mean of every profile equals the global crust.
    """
    weights = [source["area_fraction"] for source in sources]
    weight_total = sum(weights) or 1.0
    weights = [weight / weight_total for weight in weights]
    for source, weight in zip(sources, weights):
        source["area_fraction"] = weight

    profiles = [{} for _ in sources]
    for symbol, abundance in global_elements.items():
        factors = []
        for source in sources:
            continentality = source["continentality"]
            if symbol in {"Si", "Al", "Na", "K"}:
                differentiation = 0.70 + continentality * 0.60
            elif symbol in {"Fe", "Mg", "Ni", "Cr", "Co", "Ti"}:
                differentiation = 1.25 - continentality * 0.45
            else:
                differentiation = 1.0
            variation = seed_range(
                map_seed, f"element:{symbol}:{source['id']}:partition", 0.86, 1.14
            )
            factors.append(differentiation * variation)
        normalizer = sum(weight * factor for weight, factor in zip(weights, factors)) or 1.0
        for profile, factor in zip(profiles, factors):
            profile[symbol] = float(abundance) * factor / normalizer
    return profiles


def _body_card(planet_id, province, candidate, *, kind="geologic_unit"):
    material_id = str(candidate["material_id"])
    body_id = str(province["body_id"] if kind == "geologic_unit" else province["cover_body_id"])
    material = natural_materials.MATERIAL_BY_ID.get(material_id) or {}
    province_label = str(province["id"]).replace("_", " ").title()
    material_label = candidate.get("name") or material.get("name") or material_id
    return {
        "id": body_id,
        "name": f"{material_label} — {province_label}",
        "pretty_name": f"{material_label} — {province_label}",
        "type": "location",
        "_dataset": "locations",
        "location_class": kind,
        "location_role": "generated_material_body",
        "parent_location": planet_id,
        "parents": [planet_id],
        "primary_material": material_id,
        "natural_materials": [material_id],
        "material_id": material_id,
        "tectonic_province_id": province["id"],
        "geographic_center_uv": {
            "u": round(province["center_u"] % 1.0, 6),
            "v": round(_clamp(province["center_v"]), 6),
        },
        "estimated_area_fraction": round(province["area_fraction"], 5),
        "local_element_profile": {
            symbol: round(value, 6)
            for symbol, value in (province.get("elements") or {}).items()
        },
        "formation_category": candidate.get("formation_category"),
        "formation_process": candidate.get("formation_process"),
        "spatial_representation": candidate.get("spatial_representation"),
        "mechanical_rock_profile": material.get("mechanical_rock_profile"),
        "mechanical_class": material.get("mechanical_class"),
        "truth_state": "generated_material_body",
        "knowledge_state": "inferred",
        "worldgen_model_version": PLACEMENT_VERSION,
        "tags": ["worldgen_generated", "material_body", kind],
    }


def derive_planetary_material_placements(
    planet_id,
    crust_composition,
    natural_material_model,
    tectonic_model,
    map_seed,
    *,
    crater_model=None,
    radius_m=None,
):
    """Pre-heightfield substrate prior from tectonics alone.

    The heightfield needs rock strength before terrain exists, so this runs
    the lithotectonic classification without elevation evidence and returns
    a spatial relief-retention raster.  Provinces and their cards are formed
    after the heightfield by the LOD0 material product (``material_lod``).
    Returns ``(model, cards)``; the prior creates no cards.
    """
    from simulations.world_gen.material_lod import derive_substrate_prior

    prior = derive_substrate_prior(
        tectonic_model,
        natural_material_model,
        map_seed=map_seed,
        crater_model=crater_model,
        radius_m=radius_m,
    )
    return {
        "status": "tectonic_prior",
        "model_version": PLACEMENT_VERSION,
        "planet_id": planet_id,
        "map_seed": str(map_seed),
        "global_element_profile": _element_abundance_map(crust_composition or {}),
        "provinces": [],
        "body_ids": [],
        "cover_body_ids": [],
        "relief_retention_rows": prior["relief_retention_rows"],
        "recipe_provenance": prior["recipe_provenance"],
        "prior_setting_area_fractions": prior["evidence"].get("mean_memberships"),
        "element_budget_contract": "area_weighted_local_abundances_equal_global_crust_abundances",
        "source_material_catalog": "ontology_material_cards",
    }, []


def occurrence_entity(region_id, occurrence):
    """Give a generated regional body a durable card under its region."""
    material_id = str(occurrence.get("material_id") or "")
    role = str(occurrence.get("occurrence_role") or "")
    location_class = (
        "material_deposit" if role == "ore_or_mineral_prospect"
        else "geologic_unit" if role == "geologic_unit"
        else "mineral_constituent_occurrence"
    )
    card = {
        key: value for key, value in occurrence.items()
        if not str(key).startswith("_")
    }
    card.update({
        "id": str(occurrence["id"]),
        "name": occurrence.get("name") or material_id,
        "pretty_name": occurrence.get("name") or material_id,
        "type": "location",
        "_dataset": "locations",
        "location_class": location_class,
        "location_role": "generated_material_body",
        "parent_location": region_id,
        "parents": [region_id],
        "primary_material": material_id,
        "natural_materials": [material_id],
        "material_id": material_id,
        "truth_state": occurrence.get("truth_state", "generated_material_body"),
        "knowledge_state": occurrence.get("knowledge_state", "inferred"),
        "worldgen_model_version": PLACEMENT_VERSION,
        "tags": ["worldgen_generated", "material_body", location_class],
    })
    return card


def _wrapped_delta(a, b):
    delta = (float(a) - float(b)) % 1.0
    return delta - 1.0 if delta > 0.5 else delta


def _footprint_provinces(provinces, bounds):
    min_u = float(bounds.get("min_u", 0.0))
    max_u = float(bounds.get("max_u", 1.0))
    min_v = float(bounds.get("min_v", 0.0))
    max_v = float(bounds.get("max_v", 1.0))
    center_u = (min_u + max_u) * 0.5
    center_v = (min_v + max_v) * 0.5
    half_u = max(0.01, (max_u - min_u) * 0.5 + 0.02)
    half_v = max(0.01, (max_v - min_v) * 0.5 + 0.02)
    inside = [
        province for province in provinces
        if abs(_wrapped_delta(province.get("center_u", 0.5), center_u)) <= half_u
        and abs(float(province.get("center_v", 0.5)) - center_v) <= half_v
        and province.get("elements")
    ]
    if inside:
        return inside
    ranked = sorted(
        (province for province in provinces if province.get("elements")),
        key=lambda province: math.hypot(
            _wrapped_delta(province.get("center_u", 0.5), center_u),
            float(province.get("center_v", 0.5)) - center_v,
        ),
    )
    return ranked[:1]


def regional_material_inventory(material_model, placement_model, source_bounds):
    """Constrain regional possibilities to the provinces inside the footprint.

    Chemistry is the area-weighted element profile of every LOD0 province in
    (or, failing that, nearest to) the child footprint; a material is
    possible when any of those provinces supports it.
    """
    if not isinstance(material_model, dict) or not isinstance(placement_model, dict):
        return material_model
    provinces = _footprint_provinces(placement_model.get("provinces") or [], source_bounds or {})
    if not provinces:
        return material_model
    total_area = sum(max(1e-9, float(province.get("area_fraction", 0.0) or 0.0)) for province in provinces)
    elements = {}
    for province in provinces:
        weight = max(1e-9, float(province.get("area_fraction", 0.0) or 0.0)) / total_area
        for symbol, value in (province.get("elements") or {}).items():
            elements[symbol] = elements.get(symbol, 0.0) + float(value) * weight

    def supported(candidate):
        material = natural_materials.MATERIAL_BY_ID.get(candidate.get("material_id")) or {}
        return any(
            _threshold_score(province.get("elements") or {}, material.get("required_element_thresholds")) > 0.0
            and _group_score(province.get("elements") or {}, material.get("required_element_groups")) > 0.0
            for province in provinces
        )

    candidates = [
        candidate for candidate in material_model.get("likely_materials") or []
        if isinstance(candidate, dict) and supported(candidate)
    ]
    return {
        **material_model,
        "likely_materials": candidates,
        "dominant_materials": [candidate["material_id"] for candidate in candidates[:5]],
        "element_profile": elements,
        "source_geochemical_province_ids": [province.get("id") for province in provinces],
        "source_geochemical_body_ids": [province.get("body_id") for province in provinces if province.get("body_id")],
    }
