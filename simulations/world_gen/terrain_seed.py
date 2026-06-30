from simulations.world_gen.map_seed import resolved_map_seed, seed_range


def _clamp(value, low, high):
    return max(low, min(high, float(value)))


def _surface_pressure_bar(atmosphere):
    if not isinstance(atmosphere, dict):
        return 0.0
    return max(0.0, float(atmosphere.get("surface_pressure_bar", 0.0) or 0.0))


def _erosion_strength(surface, pressure_bar):
    hydrology = surface.get("hydrologic_cycle")
    aeolian = surface.get("aeolian_activity")
    strength = 0.0
    if hydrology == "active":
        strength += 0.55
    elif hydrology == "limited":
        strength += 0.25
    if aeolian == "strong":
        strength += 0.25
    elif aeolian == "moderate":
        strength += 0.16
    elif aeolian == "weak":
        strength += 0.06
    if pressure_bar >= 1.0:
        strength += 0.08
    return _clamp(strength, 0.0, 1.0)


def _plate_count(radius_earth, internal_heat_w_m2, water_fraction):
    radius_factor = _clamp(radius_earth, 0.35, 2.4)
    heat_factor = _clamp(internal_heat_w_m2 / 0.087, 0.4, 2.0)
    water_factor = 0.85 + _clamp(water_fraction, 0.0, 1.0) * 0.45
    return int(round(_clamp(8.0 * radius_factor * heat_factor * water_factor, 3.0, 28.0)))


def _element_profile(seed):
    composition = seed.get("crust_composition") if isinstance(seed.get("crust_composition"), dict) else {}
    profile = {}
    for group_name in ("major_elements", "trace_elements"):
        for row in composition.get(group_name) or []:
            if not isinstance(row, dict):
                continue
            symbol = str(row.get("symbol") or "").strip()
            if not symbol:
                continue
            try:
                amount = float(row.get("abundance_percent", 0.0) or 0.0)
            except (TypeError, ValueError):
                amount = 0.0
            profile[symbol] = max(profile.get(symbol, 0.0), amount)
    return profile


def derive_terrain_seed_model(seed, physics, atmosphere, regime, planet_id="", system_id=""):
    seed = seed if isinstance(seed, dict) else {}
    physics = physics if isinstance(physics, dict) else {}
    atmosphere = atmosphere if isinstance(atmosphere, dict) else {}
    regime = regime if isinstance(regime, dict) else {}
    interior = regime.get("interior") if isinstance(regime.get("interior"), dict) else {}
    surface = regime.get("surface_processes") if isinstance(regime.get("surface_processes"), dict) else {}
    map_seed = resolved_map_seed(seed, planet_id=planet_id, system_id=system_id)

    radius_earth = max(0.01, float(physics.get("radius_earth", seed.get("radius_earth", 1.0)) or 1.0))
    radius_m = max(1.0, float(physics.get("radius_m", radius_earth * 6_371_000.0) or 1.0))
    gravity_g = max(0.05, float(physics.get("surface_gravity_g", 1.0) or 1.0))
    water_fraction = _clamp(seed.get("water_fraction", 0.0), 0.0, 1.0)
    pressure_bar = _surface_pressure_bar(atmosphere)
    surface_temp_k = max(0.0, float(atmosphere.get("estimated_surface_temperature_k", 0.0) or 0.0))
    internal_heat = max(0.0, float(interior.get("internal_heat_w_m2", 0.0) or 0.0))
    tectonics = str(interior.get("tectonic_regime") or "unknown")
    hydrology = str(surface.get("hydrologic_cycle") or "none")
    crater_retention = str(surface.get("crater_retention") or "moderate")
    topography = str(surface.get("primary_topography") or "unknown")
    erosion_processes = list(surface.get("erosion_processes") or [])

    mobile_plates = tectonics in {"plate_tectonics", "mobile_lid"}
    partial_resurfacing = tectonics in {"episodic_lid", "heat_pipe"}
    liquid_water = bool(surface.get("liquid_water_possible"))
    erosion = _erosion_strength(surface, pressure_bar)
    elements = _element_profile(seed)
    silica = elements.get("Si", 0.0)
    mafic = elements.get("Fe", 0.0) + elements.get("Mg", 0.0) + elements.get("Ni", 0.0)
    volatile_elements = elements.get("C", 0.0) + elements.get("N", 0.0) + elements.get("S", 0.0)
    gravity_relief_factor = _clamp(1.0 / (gravity_g ** 0.5), 0.55, 1.45)
    silica_relief_factor = 1.0 + _clamp((silica - 24.0) / 80.0, -0.18, 0.22)
    mafic_roughness_bonus = _clamp((mafic - 8.0) / 90.0, -0.08, 0.18)

    if mobile_plates:
        max_elevation_m = 8200.0 + radius_earth * 1800.0
        min_elevation_m = -7800.0 - radius_earth * 1200.0
        roughness = 0.62
        relief_driver = "plate_boundary_relief"
    elif partial_resurfacing:
        max_elevation_m = 5200.0 + radius_earth * 1300.0
        min_elevation_m = -4200.0 - radius_earth * 700.0
        roughness = 0.5
        relief_driver = "volcanic_and_rift_relief"
    elif crater_retention == "high":
        max_elevation_m = 3600.0 + radius_earth * 1500.0
        min_elevation_m = -5200.0 - radius_earth * 2200.0
        roughness = 0.78
        relief_driver = "impact_basin_relief"
    else:
        max_elevation_m = 4200.0 + radius_earth * 900.0
        min_elevation_m = -3600.0 - radius_earth * 600.0
        roughness = 0.46
        relief_driver = "stagnant_lid_relief"

    max_elevation_m *= gravity_relief_factor * silica_relief_factor * (1.0 - erosion * 0.22)
    min_elevation_m *= gravity_relief_factor * (1.0 - erosion * 0.16)
    roughness = _clamp(roughness + mafic_roughness_bonus - erosion * 0.08, 0.18, 0.9)
    ocean_bias = seed_range(map_seed, "ocean_bias", -0.18, 0.18)
    temp_ocean_factor = _clamp(1.0 - abs(surface_temp_k - 288.0) / 155.0, 0.12, 1.0)
    pressure_ocean_factor = _clamp(0.55 + pressure_bar * 0.32, 0.35, 1.18)
    volatile_ocean_bonus = _clamp(volatile_elements / 80.0, 0.0, 0.12)
    target_ocean_fraction = (
        water_fraction
        * seed_range(map_seed, "ocean_scale", 0.75, 1.18)
        * temp_ocean_factor
        * pressure_ocean_factor
        + ocean_bias
        + volatile_ocean_bonus
    ) if liquid_water else 0.0
    target_ocean_fraction = _clamp(target_ocean_fraction, 0.0, 0.92)

    if crater_retention == "high":
        crater_density = 0.85
    elif crater_retention == "moderate":
        crater_density = 0.42
    else:
        crater_density = 0.08
    crater_density *= 1.0 - erosion * 0.35
    crater_density *= 1.0 - _clamp(pressure_bar / 8.0, 0.0, 0.22)
    crater_density *= 1.0 - _clamp(internal_heat / 0.35, 0.0, 0.18)
    crater_density = _clamp(crater_density, 0.0, 1.0)

    layers = [
        {"id": "elevation", "kind": "heightfield", "source": relief_driver},
        {"id": "slope", "kind": "derived_raster", "source": "elevation"},
        {"id": "crust_type", "kind": "classification", "source": "crust_composition"},
    ]
    if mobile_plates:
        layers.append({"id": "tectonic_boundaries", "kind": "vector", "source": "plate_solver_seed"})
    if crater_density > 0.12:
        layers.append({"id": "crater_population", "kind": "feature_set", "source": "impact_seed"})
    if target_ocean_fraction > 0:
        layers.append({"id": "water_mask", "kind": "raster_mask", "source": "sea_level"})
    if erosion_processes:
        layers.append({"id": "erosion_potential", "kind": "raster", "source": "surface_process_model"})
    layers.append({"id": "climate_stub", "kind": "placeholder", "source": "atmosphere_model"})

    map_recipe = list(regime.get("map_recipe") or [])
    if "allocate_map_canvas" not in map_recipe:
        map_recipe.insert(0, "allocate_map_canvas")
    for step in ("seed_heightfield_layers", "derive_water_and_erosion_masks"):
        if step not in map_recipe:
            map_recipe.append(step)

    return {
        "status": "terrain_seeded",
        "map_seed": map_seed,
        "map_seed_input": str(seed.get("map_seed") or "auto"),
        "map_canvas": {
            "projection": "equirectangular",
            "width_px": 2048,
            "height_px": 1024,
            "vertical_datum": "mean_radius",
        },
        "heightfield": {
            "resolution": "global_seed",
            "min_elevation_m": round(min_elevation_m, 1),
            "max_elevation_m": round(max_elevation_m, 1),
            "sea_level_m": 0.0 if target_ocean_fraction > 0 else None,
            "target_ocean_fraction": round(target_ocean_fraction, 3),
            "roughness": round(roughness, 3),
            "relief_driver": relief_driver,
            "primary_topography": topography,
        },
        "tectonics": {
            "enabled": mobile_plates,
            "regime": tectonics,
            "plate_count": _plate_count(radius_earth, internal_heat, water_fraction) if mobile_plates else 0,
            "boundary_style": "subduction_rift_transform" if mobile_plates else tectonics,
            "mountain_scale_m": round(max(0.0, max_elevation_m * 0.82), 1),
            "trench_scale_m": round(abs(min_elevation_m) * 0.74 if mobile_plates else 0.0, 1),
        },
        "cratering": {
            "enabled": crater_density > 0.02,
            "retention": crater_retention,
            "density": round(crater_density, 3),
            "max_crater_diameter_km": round(
                (radius_m / 1000.0)
                * (0.055 if crater_retention == "high" else 0.025)
                * _clamp(1.25 / gravity_g, 0.55, 1.75),
                1,
            ),
        },
        "erosion": {
            "processes": erosion_processes,
            "strength": round(erosion, 3),
            "atmospheric_pressure_bar": round(pressure_bar, 4),
        },
        "hydrology": {
            "cycle": hydrology,
            "liquid_water_possible": liquid_water,
            "target_ocean_fraction": round(target_ocean_fraction, 3),
            "drainage_enabled": hydrology in {"active", "limited"},
        },
        "map_layers": layers,
        "map_recipe": map_recipe,
        "notes": [
            "This is a deterministic terrain scaffold, not a finished elevation raster.",
            "The next pass can replace layer seeds with plate polygons, crater fields, drainage, and erosion iterations.",
        ],
    }
