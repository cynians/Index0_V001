"""Derive planetary mechanical-lithology priors from ontology materials.

Architecture invariants: mechanical classes and material properties are
authored on ontology material entities. This module only builds disposable,
weighted runtime projections. Generated planets have no legacy contract.
"""

from __future__ import annotations


MECHANICAL_LITHOLOGY_MODEL_VERSION = "mechanical-lithology-v1-ontology-prior"

_NUMERIC_FIELDS = (
    "bulk_density_kg_m3",
    "cohesion_mpa",
    "friction_angle_deg",
    "tensile_strength_mpa",
    "erodibility_index",
    "permeability_index",
    "slope_resistance_index",
    "fracture_density_index",
    "elastic_strength_index",
)

_NEUTRAL_PROFILE = {
    "mechanical_class": "unresolved_geologic_material",
    "bulk_density_kg_m3": 2700.0,
    "cohesion_mpa": 18.0,
    "friction_angle_deg": 34.0,
    "tensile_strength_mpa": 5.0,
    "erodibility_index": 0.50,
    "permeability_index": 0.40,
    "slope_resistance_index": 0.55,
    "fracture_density_index": 0.45,
    "elastic_strength_index": 0.55,
    "fabric": "massive_or_unresolved",
}


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, float(value)))


def mechanical_profile_for_material(material):
    """Return one ontology-authored profile with a neutral unresolved fallback."""
    material = material if isinstance(material, dict) else {}
    profile = material.get("mechanical_rock_profile")
    profile = dict(profile) if isinstance(profile, dict) else {}
    resolved = dict(_NEUTRAL_PROFILE)
    resolved.update({key: value for key, value in profile.items() if value is not None})
    if material.get("mechanical_class"):
        resolved["mechanical_class"] = str(material["mechanical_class"])
    for field in _NUMERIC_FIELDS:
        try:
            resolved[field] = float(resolved[field])
        except (TypeError, ValueError):
            resolved[field] = float(_NEUTRAL_PROFILE[field])
    return resolved


def derive_planetary_mechanical_lithology_model(natural_material_model):
    """Aggregate likely ontology materials into a coarse pre-geology prior."""
    natural_material_model = natural_material_model if isinstance(natural_material_model, dict) else {}
    candidates = [
        item for item in (natural_material_model.get("likely_materials") or [])
        if isinstance(item, dict) and item.get("material_id")
    ]
    weighted = []
    for item in candidates:
        profile = mechanical_profile_for_material(item)
        try:
            weight = max(0.0, float(item.get("prevalence_score", item.get("confidence", 0.0)) or 0.0))
        except (TypeError, ValueError):
            weight = 0.0
        if weight > 0.0:
            weighted.append((weight, item, profile))
    if not weighted:
        weighted = [(1.0, {"material_id": None}, dict(_NEUTRAL_PROFILE))]
    weighted.sort(key=lambda row: (-row[0], str(row[1].get("material_id") or "")))
    total = sum(row[0] for row in weighted) or 1.0
    aggregate = {
        field: round(sum(weight * float(profile[field]) for weight, _item, profile in weighted) / total, 4)
        for field in _NUMERIC_FIELDS
    }
    class_weights = {}
    for weight, _item, profile in weighted:
        class_id = str(profile.get("mechanical_class") or "unresolved_geologic_material")
        class_weights[class_id] = class_weights.get(class_id, 0.0) + weight
    dominant_class = max(class_weights, key=class_weights.get)
    return {
        "status": "mechanical_lithology_prior_derived",
        "model_version": MECHANICAL_LITHOLOGY_MODEL_VERSION,
        "truth_state": "ontology_material_weighted_planetary_prior",
        "dominant_mechanical_class": dominant_class,
        "class_weights": {
            key: round(value / total, 4)
            for key, value in sorted(class_weights.items())
        },
        "aggregate_profile": aggregate,
        "source_materials": [
            {
                "material_id": item.get("material_id"),
                "weight": round(weight / total, 4),
                "mechanical_class": profile.get("mechanical_class"),
            }
            for weight, item, profile in weighted[:12]
        ],
        "spatial_scope": "planetary_prior_before_2_5d_geologic_units",
        "notes": [
            "This prior changes broad deformation preservation and flexural response.",
            "Phase 3 geologic columns will replace the global prior with spatial units.",
        ],
    }


def terrain_response_factors(model):
    """Resolve bounded terrain factors from the aggregate mechanical profile."""
    profile = (model or {}).get("aggregate_profile") if isinstance(model, dict) else {}
    profile = profile if isinstance(profile, dict) else _NEUTRAL_PROFILE
    resistance = _clamp(profile.get("slope_resistance_index", 0.55))
    erodibility = _clamp(profile.get("erodibility_index", 0.50))
    elastic = _clamp(profile.get("elastic_strength_index", 0.55))
    density = max(1800.0, min(3600.0, float(profile.get("bulk_density_kg_m3", 2700.0) or 2700.0)))
    return {
        "relief_retention": 0.82 + resistance * 0.30 - erodibility * 0.16,
        "erosion_susceptibility": 0.62 + erodibility * 0.72 - resistance * 0.28,
        "elastic_thickness_factor": 0.72 + elastic * 0.58,
        "isostatic_density_factor": max(0.78, min(1.18, 2700.0 / density)),
        "ruggedness_factor": 0.72 + resistance * 0.42,
    }
