"""Shared qualitative plant nutrient response for SpeciesSim and BioSim.

The ontology supplies categorical traits; the soil supplies explicit N/P pools.
This module is the sole translation layer between them.  Coefficients are
bounded gameplay responses, not calibrated physiological constants.
"""

from __future__ import annotations

import math


def _clamp(value, lower=0.0, upper=1.0):
    try:
        value = float(value)
    except (TypeError, ValueError):
        value = lower
    return max(lower, min(upper, value if math.isfinite(value) else lower))


def _term(value):
    return str(value or "other_unknown").strip().lower().replace("-", "_").replace(" ", "_")


MYCORRHIZAL_PHOSPHORUS_ACCESS = {
    "none": 0.88,
    "arbuscular": 1.24,
    "ectomycorrhizal": 1.18,
    "ericoid": 1.16,
    "orchid": 1.08,
    "mixed": 1.22,
    "other_unknown": 1.0,
}

NITROGEN_FIXATION_FLOOR = {
    "none": 0.0,
    "associated": 0.22,
    "active": 0.42,
    "other_unknown": 0.0,
}


def resolve_plant_nutrient_response(growth, environment, stats=None):
    """Resolve N/P access from authored traits and an explicit soil state.

    Unknown or absent traits are neutral.  Fixation provides a bounded nitrogen
    response floor; it never adds phosphorus.  Soil-pool mutations remain the
    responsibility of the biosphere soil field.
    """
    growth = growth if isinstance(growth, dict) else {}
    environment = environment if isinstance(environment, dict) else {}
    stats = stats if isinstance(stats, dict) else {}
    if growth.get("surface_growth_profile"):
        # Soil pools are not accessible through invented roots. Surface
        # deposition/mineral exchange is unresolved in this model.
        return {
            "nitrogen_response":1., "phosphorus_response":1.,
            "nitrogen_stress":0., "phosphorus_stress":0.,
            "limiting_nutrient":"unresolved_surface_deposition",
            "nitrogen_access_multiplier":0., "phosphorus_root_access_multiplier":0.,
            "mycorrhizal_phosphorus_multiplier":1.,
            "nitrogen_fixation":_term(growth.get("nitrogen_fixation")),
            "mycorrhizal_type":"not_applicable", "root_architecture":"not_applicable",
            "root_depth_class":"not_applicable", "trait_provenance":{},
            "model_status":"surface_deposition_unresolved_no_soil_root_access",
            "nutrient_environment_status":{"nitrogen":"unresolved_surface_deposition",
                                            "phosphorus":"unresolved_surface_deposition"},
        }

    fixation = _term(growth.get("nitrogen_fixation"))
    mycorrhiza = _term(growth.get("mycorrhizal_type"))
    root_architecture = _term(growth.get("root_architecture"))
    root_depth_class = _term(growth.get("root_depth_class"))

    root_depth = stats.get("root_depth_m", growth.get("max_root_depth"))
    try:
        root_depth = max(0.0, float(root_depth or 0.0))
    except (TypeError, ValueError):
        root_depth = 0.0
    root_spread = stats.get("root_system_span_m", stats.get("root_spread_m", 0.0))
    try:
        root_spread = max(0.0, float(root_spread or 0.0))
    except (TypeError, ValueError):
        root_spread = 0.0

    depth_default = {"shallow": 0.20, "intermediate": 0.65, "deep": 1.35}.get(root_depth_class, 0.45)
    effective_depth = root_depth if root_depth > 0.0 else depth_default
    depth_exploration = _clamp(effective_depth / 1.5)
    spread_exploration = _clamp(root_spread / 1.5)
    fibrous_bonus = 0.12 if root_architecture in {"fibrous", "adventitious"} else 0.0
    taproot_bonus = 0.10 if root_architecture in {"taproot", "mixed"} else 0.0

    nitrogen_access = _clamp(0.76 + 0.25 * depth_exploration + taproot_bonus, 0.55, 1.25)
    phosphorus_root_access = _clamp(
        0.78 + 0.24 * spread_exploration + fibrous_bonus + 0.08 * (1.0 - depth_exploration),
        0.55,
        1.25,
    )
    mycorrhizal_access = MYCORRHIZAL_PHOSPHORUS_ACCESS.get(mycorrhiza, 1.0)

    nitrogen_resolved = environment.get("available_nitrogen_g_m2") is not None and "available_nitrogen_g_m2" in environment
    phosphorus_resolved = environment.get("available_phosphorus_g_m2") is not None and "available_phosphorus_g_m2" in environment
    available_n = max(0.0, float(environment.get("available_nitrogen_g_m2", 0.0) or 0.0))
    available_p = max(0.0, float(environment.get("available_phosphorus_g_m2", 0.0) or 0.0))
    accessed_n = available_n * nitrogen_access
    accessed_p = available_p * phosphorus_root_access * mycorrhizal_access
    nitrogen_response = accessed_n / (accessed_n + 0.32) if accessed_n > 0.0 else 0.0
    phosphorus_response = accessed_p / (accessed_p + 0.055) if accessed_p > 0.0 else 0.0
    if nitrogen_resolved:
        nitrogen_response = max(nitrogen_response, NITROGEN_FIXATION_FLOOR.get(fixation, 0.0))
    else:
        nitrogen_response = 1.0
    if not phosphorus_resolved:
        phosphorus_response = 1.0

    return {
        "nitrogen_response": round(_clamp(nitrogen_response), 6),
        "phosphorus_response": round(_clamp(phosphorus_response), 6),
        "nitrogen_stress": round(1.0 - _clamp(nitrogen_response), 6),
        "phosphorus_stress": round(1.0 - _clamp(phosphorus_response), 6),
        "limiting_nutrient": "nitrogen" if nitrogen_response <= phosphorus_response else "phosphorus",
        "nitrogen_access_multiplier": round(nitrogen_access, 6),
        "phosphorus_root_access_multiplier": round(phosphorus_root_access, 6),
        "mycorrhizal_phosphorus_multiplier": round(mycorrhizal_access, 6),
        "nitrogen_fixation": fixation,
        "mycorrhizal_type": mycorrhiza,
        "root_architecture": root_architecture,
        "root_depth_class": root_depth_class,
        "trait_provenance": {
            "nitrogen_fixation": "authored" if fixation != "other_unknown" else "neutral_missing_default",
            "mycorrhizal_type": "authored" if mycorrhiza != "other_unknown" else "neutral_missing_default",
            "root_architecture": "authored" if root_architecture != "other_unknown" else "neutral_missing_default",
            "root_depth_class": "authored" if root_depth_class != "other_unknown" else "neutral_missing_default",
        },
        "model_status": "qualitative_bounded_runtime_response",
        "nutrient_environment_status": {
            "nitrogen": "resolved" if nitrogen_resolved else "unresolved_neutral",
            "phosphorus": "resolved" if phosphorus_resolved else "unresolved_neutral",
        },
    }
