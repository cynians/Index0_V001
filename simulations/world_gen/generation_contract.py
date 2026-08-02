"""Versioned player-input contract for reproducible world-generation replay.

The contract contains only the authored first-screen boundary conditions and
the astronomical context visible to the production simulation. Later stages
remain derived by :class:`WorldGenSimulation`.
"""

import copy
import hashlib
import json


CONTRACT_VERSION = 1

STAR_CONTEXT_FIELDS = (
    "id", "name", "pretty_name", "type", "location_class", "location_role",
    "system_role", "star_class", "spectral_class", "mass_kg", "radius_m",
    "luminosity_solar", "effective_temperature_k", "metallicity_feh",
    "mass_solar", "radius_solar", "age_gyr", "rotation_period_days",
    "uv_activity", "xray_activity", "flare_frequency", "stellar_wind_strength",
    "multiplicity", "companions",
)
SYSTEM_CONTEXT_FIELDS = (
    "id", "name", "pretty_name", "type", "location_class", "location_role",
    "system_role", "system_age_gyr", "metallicity_feh", "multiplicity", "constituents",
)
PLANET_IDENTITY_FIELDS = (
    "id", "name", "pretty_name", "location_class", "location_role",
    "system_role", "body_subclass", "parent_body",
)


def _snapshot(entity, fields):
    entity = entity if isinstance(entity, dict) else {}
    return {field: copy.deepcopy(entity.get(field)) for field in fields if entity.get(field) is not None}


def contract_fingerprint(contract):
    payload = copy.deepcopy(contract if isinstance(contract, dict) else {})
    payload.pop("fingerprint_sha256", None)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_generation_input_contract(*, planet, seed, system=None, star=None, year=None):
    planet = planet if isinstance(planet, dict) else {}
    seed = seed if isinstance(seed, dict) else {}
    contract = {
        "contract_version": CONTRACT_VERSION,
        "contract_kind": "worldgen_player_first_screen",
        "derivation_policy": "all_later_stages_derive_from_first_screen_and_astronomical_context",
        "template_policy": "planet_template_is_noncausal_preset_provenance_only",
        "registry_year": year,
        "planet_identity": _snapshot(planet, PLANET_IDENTITY_FIELDS),
        "system_context": _snapshot(system, SYSTEM_CONTEXT_FIELDS),
        "star_context": _snapshot(star, STAR_CONTEXT_FIELDS),
        "orbit": {
            "periapsis_au": planet.get("periapsis_au"),
            "apoapsis_au": planet.get("apoapsis_au"),
            "semi_major_axis_m": planet.get("semi_major_axis_m"),
            "eccentricity": planet.get("eccentricity"),
            "orbit_reference_frame": planet.get("orbit_reference_frame"),
            "parent_body": planet.get("parent_body"),
        },
        "first_screen": {
            "planet_template": seed.get("planet_template"),
            "radius_earth": seed.get("radius_earth"),
            "core_radius_fraction": seed.get("core_radius_fraction"),
            "crust_thickness_km": seed.get("crust_thickness_km"),
            "angular_velocity_deg_per_hour": seed.get("angular_velocity_deg_per_hour"),
            "water_fraction": seed.get("water_fraction"),
            "volatile_inventory": seed.get("volatile_inventory"),
            "tectonics_mode": seed.get("tectonics_mode"),
            "map_seed": seed.get("map_seed"),
            "crust_composition": copy.deepcopy(seed.get("crust_composition") or {}),
        },
    }
    contract["fingerprint_sha256"] = contract_fingerprint(contract)
    return contract


def validate_generation_input_contract(contract):
    if not isinstance(contract, dict):
        raise ValueError("Generation contract must be an object")
    if int(contract.get("contract_version", 0) or 0) != CONTRACT_VERSION:
        raise ValueError(f"Unsupported generation contract version: {contract.get('contract_version')}")
    if contract.get("contract_kind") != "worldgen_player_first_screen":
        raise ValueError("Generation contract kind is not player first-screen worldgen")
    first_screen = contract.get("first_screen")
    if not isinstance(first_screen, dict):
        raise ValueError("Generation contract has no first-screen payload")
    expected = contract.get("fingerprint_sha256")
    if expected and expected != contract_fingerprint(contract):
        raise ValueError("Generation contract fingerprint does not match its contents")
    return contract
