"""Reduced-physics reconstruction of the history behind a generated planet.

This is not a second generator.  It records the causal state consumed and
produced by the existing world-generation stages so later refinements can
inherit planetary boundary conditions instead of rolling unrelated detail.
"""

import math

from simulations.world_gen.map_seed import seed_range


SOLAR_MASS_KG = 1.98847e30
AU_M = 149_597_870_700.0


def _clamp(value, low, high):
    return max(low, min(high, float(value)))


def _number(mapping, *keys, default=0.0):
    for key in keys:
        if isinstance(mapping, dict) and mapping.get(key) is not None:
            try:
                return float(mapping[key])
            except (TypeError, ValueError):
                pass
    return float(default)


def _stellar_history(seed, age_gyr, key):
    luminosity = max(0.0001, _number(seed, "stellar_luminosity_solar", default=1.0))
    mass_solar = max(0.07, _number(seed, "stellar_mass_solar", default=luminosity ** 0.25))
    radius_solar = max(0.08, _number(seed, "stellar_radius_solar", default=mass_solar ** 0.8))
    effective_temperature_k = _number(seed, "stellar_effective_temperature_k", default=0.0)
    if effective_temperature_k <= 0.0:
        effective_temperature_k = 5772.0 * (luminosity / (radius_solar * radius_solar)) ** 0.25
    rotation_days = max(0.08, _number(seed, "stellar_rotation_period_days", default=25.0 * max(0.18, age_gyr / 4.57) ** 0.48))
    youth_activity = _clamp((0.75 / max(0.08, age_gyr)) ** 0.72, 0.08, 8.0)
    temperature_activity = _clamp((effective_temperature_k / 5772.0) ** 2.2, 0.18, 5.0)
    activity = youth_activity * temperature_activity * seed_range(key, "stellar_activity_variation", 0.78, 1.28)
    return {
        "mass_solar": round(mass_solar, 5),
        "radius_solar": round(radius_solar, 5),
        "luminosity_solar": round(luminosity, 7),
        "effective_temperature_k": round(effective_temperature_k, 1),
        "metallicity_feh": round(_number(seed, "stellar_metallicity_feh", default=0.0), 3),
        "age_gyr": round(age_gyr, 4),
        "rotation_period_days": round(rotation_days, 3),
        "uv_xray_activity_relative_sun": round(activity, 3),
        "flare_frequency_relative_sun": round(activity ** 1.18, 3),
        "stellar_wind_relative_sun": round(activity ** 0.72, 3),
        "spectral_class": seed.get("stellar_spectral_class") or "unknown",
        "multiplicity": seed.get("stellar_multiplicity") or "single_or_unresolved",
        "derivation": "stellar entity plus age/activity scaling",
    }


def _formation_history(seed, stellar, key):
    formation = seed.get("formation_model") if isinstance(seed.get("formation_model"), dict) else {}
    orbit_au = max(0.01, _number(seed, "semi_major_axis_au", default=formation.get("formation_orbit_au", 1.0)))
    metallicity_factor = 10.0 ** stellar["metallicity_feh"]
    disk_mass_fraction = _clamp(0.012 * metallicity_factor * seed_range(key, "disk_mass", 0.55, 2.2), 0.0015, 0.18)
    disk_lifetime = _number(formation, "disk_gas_lifetime_myr", default=seed_range(key, "disk_lifetime", 1.3, 7.0))
    migration_fraction = seed_range(key, "migration_fraction", -0.42, 0.36)
    formation_orbit = max(0.01, _number(formation, "formation_orbit_au", default=orbit_au / max(0.35, 1.0 + migration_fraction)))
    impact_count = int(round(seed_range(key, "giant_impact_count", 1.0, 7.0)))
    last_impact_myr = seed_range(key, "last_giant_impact_myr", 18.0, 145.0)
    late_delivery = seed_range(key, "late_delivery_fraction", 0.005, 0.19)
    return {
        "protoplanetary_disk": {
            "disk_mass_fraction_of_star": round(disk_mass_fraction, 5),
            "dust_to_gas_ratio": round(_clamp(0.01 * metallicity_factor, 0.002, 0.045), 5),
            "gas_lifetime_myr": round(disk_lifetime, 2),
            "turbulence_alpha": round(seed_range(key, "disk_turbulence", 0.0001, 0.012), 6),
            "formation_zone": formation.get("formation_zone") or "reconstructed_from_present_orbit",
            "condensation_fronts_au": formation.get("condensation_fronts_au") or {},
        },
        "accretion": {
            "formation_orbit_au": round(formation_orbit, 5),
            "present_orbit_au": round(orbit_au, 5),
            "migration_au": round(orbit_au - formation_orbit, 5),
            "giant_impact_count": impact_count,
            "last_giant_impact_myr_after_formation": round(last_impact_myr, 2),
            "late_accreted_mass_fraction": round(late_delivery, 4),
            "volatile_delivery_efficiency": round(late_delivery * seed_range(key, "volatile_delivery_efficiency", 0.7, 2.4), 4),
            "stochastic_exception": bool(formation.get("stochastic_exception")),
        },
    }


def _orbit_spin_history(seed, physics, stellar, key):
    mass_kg = max(1.0, _number(physics, "mass_kg", default=5.9722e24))
    orbit_au = max(0.001, _number(seed, "semi_major_axis_au", default=1.0))
    eccentricity = _clamp(_number(seed, "orbital_eccentricity", "eccentricity", default=0.0), 0.0, 0.95)
    star_mass_kg = stellar["mass_solar"] * SOLAR_MASS_KG
    hill_radius_m = orbit_au * AU_M * (1.0 - eccentricity) * (mass_kg / max(1.0, 3.0 * star_mass_kg)) ** (1.0 / 3.0)
    rotation_hours = max(0.01, abs(_number(physics, "rotation_period_hours", default=24.0)))
    obliquity = _clamp(_number(seed, "axial_tilt_deg", default=seed_range(key, "obliquity", 0.0, 52.0)), 0.0, 180.0)
    tidal_lock_score = _clamp((0.12 / orbit_au) ** 6 * (4.5 / max(0.1, _number(seed, "system_age_gyr", default=4.5))), 0.0, 1.0)
    synchronous = bool(seed.get("synchronous_rotation")) or tidal_lock_score > 0.68
    stability = _clamp(1.0 - eccentricity * 0.62 - max(0.0, tidal_lock_score - 0.8) * 0.2, 0.0, 1.0)
    return {
        "semi_major_axis_au": round(orbit_au, 6),
        "eccentricity": round(eccentricity, 6),
        "periapsis_flux_factor": round(1.0 / max(0.01, (orbit_au * (1.0 - eccentricity)) ** 2), 5),
        "apoapsis_flux_factor": round(1.0 / max(0.01, (orbit_au * (1.0 + eccentricity)) ** 2), 5),
        "long_term_stability_score": round(stability, 3),
        "stability_class": "stable" if stability >= 0.55 else "marginal_requires_system_evolution",
        "rotation_period_hours": round(rotation_hours, 5),
        "rotation_direction": physics.get("rotation_direction") or ("retrograde" if _number(seed, "angular_velocity_deg_per_hour", default=15.0) < 0 else "prograde"),
        "obliquity_deg": round(obliquity, 3),
        "tidal_locking_score": round(tidal_lock_score, 4),
        "synchronous_rotation": synchronous,
        "hill_radius_km": round(hill_radius_m / 1000.0, 2),
        "moon_stability_outer_limit_km": round(hill_radius_m * 0.49 / 1000.0, 2),
        "spin_origin": "impact/accretion history reconstructed to match first-screen rotation",
    }


def _differentiation_history(seed, physics, formation, key):
    mass_earth = max(0.0001, _number(physics, "mass_earth", default=1.0))
    core_fraction = _clamp(_number(physics, "core_radius_fraction", default=0.55), 0.0, 0.95)
    impact_energy = _clamp(0.34 + math.log10(max(0.01, mass_earth)) * 0.17 + formation["accretion"]["giant_impact_count"] * 0.055, 0.0, 1.0)
    radiogenic = _clamp(_number((seed.get("derived_planet_physics") or {}), "radiogenic_heat_multiplier", default=1.0), 0.2, 3.0)
    melt_fraction = _clamp(impact_energy * 0.72 + mass_earth ** 0.25 * 0.18 + seed_range(key, "magma_ocean", -0.08, 0.1), 0.0, 1.0)
    return {
        "differentiated": bool(core_fraction >= 0.08 or melt_fraction >= 0.42),
        "accretionary_melt_fraction": round(melt_fraction, 3),
        "magma_ocean_extent": "global" if melt_fraction >= 0.78 else ("regional" if melt_fraction >= 0.38 else "limited"),
        "core_formation_completion": round(_clamp(core_fraction / 0.55 * (0.72 + melt_fraction * 0.28), 0.0, 1.0), 3),
        "mantle_crust_extraction_fraction": round(_clamp(0.04 + melt_fraction * 0.16, 0.01, 0.28), 3),
        "volatile_partition": {
            "mantle_fraction": round(_clamp(0.62 - melt_fraction * 0.24, 0.16, 0.72), 3),
            "surface_reservoir_fraction": round(_clamp(0.18 + melt_fraction * 0.38, 0.08, 0.65), 3),
            "early_escape_exposure_fraction": round(_clamp(0.12 + melt_fraction * 0.24, 0.05, 0.42), 3),
        },
        "radiogenic_inventory_proxy": round(radiogenic, 3),
    }


def _provenance_nodes(tectonics, atmosphere_class, hydrology, surface_age_myr):
    return [
        {"id": "stellar_forcing", "kind": "boundary_condition", "causes": ["disk_chemistry", "atmospheric_escape", "climate_energy_balance"]},
        {"id": "disk_chemistry", "kind": "formation_process", "causes": ["bulk_composition", "volatile_budget"]},
        {"id": "accretion_history", "kind": "formation_process", "causes": ["spin_state", "differentiation", "impact_record"]},
        {"id": "differentiation", "kind": "interior_process", "causes": ["core_mantle_crust_partition", "surface_material_inventory"]},
        {"id": "thermal_evolution", "kind": "interior_process", "causes": [tectonics, "volcanism", "magnetic_field_proxy"]},
        {"id": "volatile_budget", "kind": "reservoir_balance", "causes": [atmosphere_class, hydrology]},
        {"id": "tectonic_provinces", "kind": "spatial_process", "causes": ["continents", "ocean_basins", "mountain_belts", "ore_affinities"]},
        {"id": "surface_record", "kind": "time_window", "age_myr": round(surface_age_myr, 1), "causes": ["preserved_impacts", "weathering_depth", "erosional_maturity"]},
    ]


def derive_planetary_evolution_model(seed, atmosphere=None, regime=None):
    seed = seed if isinstance(seed, dict) else {}
    atmosphere = atmosphere if isinstance(atmosphere, dict) else {}
    regime = regime if isinstance(regime, dict) else {}
    physics = seed.get("derived_planet_physics") if isinstance(seed.get("derived_planet_physics"), dict) else {}
    key = str(seed.get("resolved_map_seed") or seed.get("planet_id") or "planetary-history")
    system_age_gyr = max(0.01, float(seed.get("system_age_gyr", 4.5) or 4.5))
    formation_delay_myr = max(0.0, float(seed.get("formation_delay_myr", 5.0) or 5.0))
    body_age_gyr = max(0.0, system_age_gyr - formation_delay_myr / 1000.0)
    surface_age_myr = _clamp(seed.get("surface_age_myr", body_age_gyr * 1000.0), 0.0, body_age_gyr * 1000.0)
    water_loss = _clamp(seed.get("water_loss_fraction", 0.0), 0.0, 1.0)
    resurfacing = _clamp(seed.get("resurfacing_fraction", 0.0), 0.0, 1.0)
    atmosphere_class = str(atmosphere.get("atmosphere_class") or "unknown")
    interior = regime.get("interior") if isinstance(regime.get("interior"), dict) else {}
    surface = regime.get("surface_processes") if isinstance(regime.get("surface_processes"), dict) else {}
    tectonics = str(interior.get("tectonic_regime") or seed.get("tectonics_mode") or "unknown")
    volcanic = str(interior.get("volcanic_activity") or "unknown")
    hydrology = str(surface.get("hydrologic_cycle") or "unknown")

    stellar = _stellar_history(seed, system_age_gyr, key)
    formation = _formation_history(seed, stellar, key)
    orbit_spin = _orbit_spin_history(seed, physics, stellar, key)
    differentiation = _differentiation_history(seed, physics, formation, key)
    present_heat = max(0.0, _number(interior, "internal_heat_w_m2", default=0.0))
    initial_heat = present_heat * (1.0 + min(14.0, body_age_gyr * 1.8))

    events = [
        {"process": "disk_condensation_and_planetesimal_growth", "status": "complete", "ended_myr_after_formation": round(formation["protoplanetary_disk"]["gas_lifetime_myr"], 2)},
        {"process": "accretion", "status": "complete", "ended_myr_after_formation": 100.0},
        {"process": "interior_differentiation", "status": "complete", "ended_myr_after_formation": 180.0},
        {"process": "secular_cooling", "status": "active", "elapsed_gyr": round(body_age_gyr, 4)},
    ]
    if water_loss > 0.05:
        events.append({"process": "surface_water_loss", "status": "complete" if water_loss >= 0.95 else "in_progress", "completion_fraction": water_loss, "result": "desiccated_surface" if water_loss >= 0.9 else "reduced_surface_water"})
    if atmosphere_class == "runaway_co2":
        events.append({"process": "runaway_greenhouse_transition", "status": "complete", "result": "dense_hot_co2_atmosphere"})
    if resurfacing > 0.02:
        events.append({"process": "volcanic_resurfacing", "status": "intermittently_active" if volcanic in {"moderate", "high"} else "mostly_complete", "completion_fraction": resurfacing, "surface_record_age_myr": surface_age_myr})
    if tectonics in {"stagnant_lid", "episodic_lid", "plutonic_squishy_lid", "heat_pipe"}:
        events.append({"process": "mantle_plume_deformation", "status": "intermittently_active"})

    volatile_history = atmosphere.get("volatile_history") if isinstance(atmosphere.get("volatile_history"), dict) else {}
    return {
        "model_version": "planetary-causal-history-v2",
        "system_age_gyr": system_age_gyr,
        "body_age_gyr": round(body_age_gyr, 4),
        "surface_record_age_myr": round(surface_age_myr, 1),
        "snapshot_semantics": "present state derives from a seeded reduced-physics history; geological age is independent of registry time",
        "stellar_environment": stellar,
        "formation_history": formation,
        "orbital_and_spin_history": orbit_spin,
        "differentiation_history": differentiation,
        "thermal_history": {
            "initial_heat_flux_proxy_w_m2": round(initial_heat, 5),
            "present_internal_heat_w_m2": round(present_heat, 5),
            "radiogenic_heat_multiplier": round(_number((regime.get("thermal_evolution") or {}), "radiogenic_heat_multiplier", default=1.0), 3),
            "tectonic_regime": tectonics,
            "volcanic_activity": volcanic,
            "cooling_state": "geologically_active" if present_heat >= 0.055 else ("waning" if present_heat >= 0.015 else "mostly_cooled"),
        },
        "impact_history": {
            "giant_impacts": formation["accretion"]["giant_impact_count"],
            "last_giant_impact_myr": formation["accretion"]["last_giant_impact_myr_after_formation"],
            "present_flux_factor": round(_number(seed, "impact_flux_factor", default=1.0), 3),
            "retention_class": surface.get("crater_retention") or "unknown",
        },
        "volatile_budget": {
            **volatile_history,
            "sources": ["local_accretion", "magma_ocean_degassing", "mantle_outgassing", "late_impacts"],
            "sinks": ["thermal_escape", "nonthermal_escape", "surface_condensation", "mineral_sequestration"],
            "present_atmosphere_class": atmosphere_class,
        },
        "processes": events,
        "causal_provenance": {
            "schema_version": 1,
            "nodes": _provenance_nodes(tectonics, atmosphere_class, hydrology, surface_age_myr),
        },
        "fidelity": {
            "tier": 1,
            "method": "reduced_physics_and_parameterized_history",
            "planetary_spatial_stages": ["tectonic_provinces", "heightfield", "climate", "hydrology", "surface_evolution"],
            "regional_refinement_contract": "inherit_saved_planetary_boundary_conditions",
        },
    }


def update_causal_provenance(planet):
    """Attach downstream outputs to the history after spatial stages finish."""
    if not isinstance(planet, dict):
        return {}
    history = planet.get("planetary_evolution_model") if isinstance(planet.get("planetary_evolution_model"), dict) else {}
    provenance = history.setdefault("causal_provenance", {"schema_version": 1, "nodes": []})
    nodes = provenance.setdefault("nodes", [])
    by_id = {node.get("id"): node for node in nodes if isinstance(node, dict)}
    additions = [
        {"id": "heightfield", "kind": "spatial_state", "depends_on": ["tectonic_provinces", "impact_record", "isostasy"], "causes": ["ocean_basin_fill", "drainage"]},
        {"id": "climate", "kind": "spatial_state", "depends_on": ["stellar_forcing", "atmosphere", "rotation", "heightfield", "ocean_state"], "causes": ["precipitation", "cryosphere", "weathering"]},
        {"id": "hydrology", "kind": "spatial_state", "depends_on": ["heightfield", "climate", "volatile_budget"], "causes": ["rivers", "lakes", "sediment_transport"]},
        {"id": "coastal_geomorphology", "kind": "spatial_state", "depends_on": ["heightfield", "ocean_state", "climate", "hydrology", "tectonic_provinces", "sediment_transport"], "causes": ["coastal_landforms", "estuarine_accommodation", "biogenic_coast_potential"]},
        {"id": "surface_material_provinces", "kind": "spatial_state", "depends_on": ["core_mantle_crust_partition", "tectonic_provinces", "climate", "hydrology"], "causes": ["regional_deposit_candidates", "regolith"]},
    ]
    for node in additions:
        if node["id"] in by_id:
            by_id[node["id"]].update(node)
        else:
            nodes.append(node)
    provenance["terminal_outputs"] = {
        "tectonic_model": bool(planet.get("tectonic_model")),
        "heightmap_model": bool(planet.get("heightmap_model")),
        "water_cycle_model": bool(planet.get("water_cycle_model")),
        "coastal_geomorphology_model": bool(planet.get("coastal_geomorphology_model")),
        "surface_evolution_model": bool(planet.get("surface_evolution_model")),
        "natural_material_model": bool(planet.get("natural_material_model")),
    }
    planet["causal_provenance"] = provenance
    return provenance
