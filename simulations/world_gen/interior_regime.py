def _clamp(value, low, high):
    return max(low, min(high, float(value)))


def _pressure_bar(atmosphere):
    if not isinstance(atmosphere, dict):
        return 0.0
    return max(0.0, float(atmosphere.get("surface_pressure_bar", 0.0) or 0.0))


def _surface_temperature_k(atmosphere):
    if not isinstance(atmosphere, dict):
        return 0.0
    return max(0.0, float(atmosphere.get("estimated_surface_temperature_k", 0.0) or 0.0))


def _tectonic_regime(seed, physics, internal_heat_w_m2, mantle_present, liquid_water_possible):
    requested = str(seed.get("tectonics_mode") or "unknown").strip().lower()
    mantle_fraction = float(physics.get("mantle_radius_fraction", 0.0) or 0.0)
    crust_fraction = float(physics.get("crust_radius_fraction", 0.0) or 0.0)

    if not mantle_present:
        return "inactive"

    explicit_modes = {
        "plate_tectonics",
        "mobile_lid",
        "stagnant_lid",
        "episodic_lid",
        "heat_pipe",
        "inactive",
    }
    if requested in explicit_modes:
        return requested

    if internal_heat_w_m2 < 0.015 or mantle_fraction < 0.08:
        return "inactive"
    if internal_heat_w_m2 > 0.18 and crust_fraction < 0.025:
        return "heat_pipe"
    if internal_heat_w_m2 > 0.055 and liquid_water_possible:
        return "plate_tectonics"
    if internal_heat_w_m2 > 0.04:
        return "episodic_lid"
    return "stagnant_lid"


def derive_interior_regime_model(seed, physics, atmosphere, crust_type="unknown"):
    seed = seed if isinstance(seed, dict) else {}
    physics = physics if isinstance(physics, dict) else {}
    atmosphere = atmosphere if isinstance(atmosphere, dict) else {}

    radius_earth = max(0.01, float(physics.get("radius_earth", seed.get("radius_earth", 1.0)) or 1.0))
    core_fraction = _clamp(physics.get("core_radius_fraction", seed.get("core_radius_fraction", 0.0)), 0.0, 0.95)
    mantle_fraction = max(0.0, float(physics.get("mantle_radius_fraction", 0.0) or 0.0))
    crust_fraction = max(0.0, float(physics.get("crust_radius_fraction", 0.0) or 0.0))
    crust_thickness_km = max(0.0, float(physics.get("crust_thickness_km", seed.get("crust_thickness_km", 0.0)) or 0.0))
    gravity_g = max(0.0, float(physics.get("surface_gravity_g", 0.0) or 0.0))
    water_fraction = _clamp(seed.get("water_fraction", 0.0), 0.0, 1.0)

    mantle_present = mantle_fraction >= 0.03
    differentiated = core_fraction >= 0.08 or mantle_fraction >= 0.12
    pressure_bar = _pressure_bar(atmosphere)
    surface_temp_k = _surface_temperature_k(atmosphere)

    volatile_factor = {
        "none": 0.3,
        "dry": 0.45,
        "thin": 0.65,
        "earthlike": 1.0,
        "wet": 1.08,
        "dense": 1.12,
    }.get(str(seed.get("volatile_inventory") or "earthlike").strip().lower(), 1.0)
    size_factor = radius_earth ** 0.75
    core_heat_factor = 0.35 + core_fraction
    mantle_heat_factor = _clamp(mantle_fraction / 0.44, 0.0, 1.4)
    internal_heat_w_m2 = 0.087 * size_factor * core_heat_factor * mantle_heat_factor
    internal_heat_w_m2 = max(0.0, internal_heat_w_m2)

    liquid_water_possible = (
        water_fraction > 0.03
        and pressure_bar >= 0.006
        and 250.0 <= surface_temp_k <= 395.0
    )
    hydrologic_cycle = (
        "active"
        if liquid_water_possible and pressure_bar >= 0.08 and 260.0 <= surface_temp_k <= 360.0
        else ("limited" if liquid_water_possible else "none")
    )

    tectonics = _tectonic_regime(seed, physics, internal_heat_w_m2, mantle_present, liquid_water_possible)
    volcanic_activity = "none"
    if mantle_present and internal_heat_w_m2 >= 0.015:
        volcanic_activity = "low"
    if mantle_present and internal_heat_w_m2 >= 0.055:
        volcanic_activity = "moderate"
    if mantle_present and internal_heat_w_m2 >= 0.14:
        volcanic_activity = "high"

    aeolian_activity = "none"
    if pressure_bar >= 0.01:
        aeolian_activity = "weak"
    if pressure_bar >= 0.15:
        aeolian_activity = "moderate"
    if pressure_bar >= 1.5:
        aeolian_activity = "strong"

    erosion_processes = []
    if hydrologic_cycle == "active":
        erosion_processes.extend(["fluvial", "coastal", "chemical_weathering"])
    elif hydrologic_cycle == "limited":
        erosion_processes.append("episodic_fluvial")
    if aeolian_activity != "none":
        erosion_processes.append("aeolian")
    if water_fraction > 0.02 and surface_temp_k < 273.0 and pressure_bar >= 0.02:
        erosion_processes.append("glacial")
    if not erosion_processes:
        erosion_processes.append("impact_gardening")

    resurfacing_score = 0
    if tectonics in {"plate_tectonics", "mobile_lid"}:
        resurfacing_score += 3
    elif tectonics in {"episodic_lid", "heat_pipe"}:
        resurfacing_score += 2
    elif tectonics == "stagnant_lid":
        resurfacing_score += 1
    if hydrologic_cycle == "active":
        resurfacing_score += 3
    elif hydrologic_cycle == "limited":
        resurfacing_score += 1
    if aeolian_activity in {"moderate", "strong"}:
        resurfacing_score += 1
    if volcanic_activity in {"moderate", "high"}:
        resurfacing_score += 1

    if resurfacing_score >= 5:
        crater_retention = "low"
    elif resurfacing_score >= 2:
        crater_retention = "moderate"
    else:
        crater_retention = "high"

    if tectonics in {"plate_tectonics", "mobile_lid"}:
        primary_topography = "plate_boundaries_mountain_belts_and_trenches"
    elif tectonics == "heat_pipe":
        primary_topography = "volcanic_plains_and_shield_provinces"
    elif tectonics == "episodic_lid":
        primary_topography = "rifted_stagnant_lid_with_resurfaced_provinces"
    elif crater_retention == "high":
        primary_topography = "impact_basins_cratered_highlands"
    else:
        primary_topography = "stagnant_lid_shields_and_old_basins"

    map_recipe = [
        "initialize_spherical_height_field",
        f"apply_{primary_topography}",
    ]
    if crater_retention in {"moderate", "high"}:
        map_recipe.append(f"apply_{crater_retention}_crater_population")
    if hydrologic_cycle != "none":
        map_recipe.append(f"solve_{hydrologic_cycle}_hydrology")
    for process in erosion_processes:
        if process != "impact_gardening":
            map_recipe.append(f"erode_{process}")

    return {
        "interior": {
            "differentiated": differentiated,
            "core_radius_fraction": core_fraction,
            "mantle_radius_fraction": mantle_fraction,
            "crust_radius_fraction": crust_fraction,
            "mantle_present": mantle_present,
            "crust_thickness_km": crust_thickness_km,
            "internal_heat_w_m2": internal_heat_w_m2,
            "tectonic_regime": tectonics,
            "volcanic_activity": volcanic_activity,
            "crust_type": crust_type,
        },
        "surface_processes": {
            "surface_pressure_bar": pressure_bar,
            "surface_temperature_k": surface_temp_k,
            "surface_gravity_g": gravity_g,
            "liquid_water_possible": liquid_water_possible,
            "hydrologic_cycle": hydrologic_cycle,
            "aeolian_activity": aeolian_activity,
            "erosion_processes": erosion_processes,
            "crater_retention": crater_retention,
            "primary_topography": primary_topography,
        },
        "map_recipe": map_recipe,
        "notes": [
            "This regime selects which terrain processes are physically allowed before map synthesis.",
            "Plate boundaries are only enabled when mantle heat and surface conditions can support mobile lithosphere.",
            "Crater preservation rises when atmosphere, hydrology, tectonics, and volcanism cannot erase impacts.",
        ],
    }
