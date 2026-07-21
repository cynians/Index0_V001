from simulations.world_gen.map_seed import resolved_map_seed, seed_range


PLANETARY_CANVAS_WIDTH_PX = 8192
PLANETARY_CANVAS_HEIGHT_PX = 4096


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
    circumference_m = 2.0 * 3.141592653589793 * radius_m
    gravity_g = max(0.05, float(physics.get("surface_gravity_g", 1.0) or 1.0))
    water_fraction = _clamp(seed.get("water_fraction", 0.0), 0.0, 1.0)
    planet_class = str(seed.get("planet_class") or seed.get("planet_template") or "").strip().lower()
    icy_satellite = planet_class == "icy_satellite"
    snowball_world = planet_class == "snowball_terrestrial" or str(seed.get("climate_mode") or "").lower() == "snowball"
    pressure_bar = _surface_pressure_bar(atmosphere)
    surface_temp_k = max(0.0, float(atmosphere.get("estimated_surface_temperature_k", 0.0) or 0.0))
    internal_heat = max(0.0, float(interior.get("internal_heat_w_m2", 0.0) or 0.0))
    tectonics = str(interior.get("tectonic_regime") or "unknown")
    hydrology = str(surface.get("hydrologic_cycle") or "none")
    crater_retention = str(surface.get("crater_retention") or "moderate")
    topography = str(surface.get("primary_topography") or "unknown")
    erosion_processes = list(surface.get("erosion_processes") or [])

    mobile_plates = tectonics in {"plate_tectonics", "mobile_lid"}
    partial_resurfacing = tectonics in {"episodic_lid", "plutonic_squishy_lid", "heat_pipe", "cryotectonic"}
    liquid_water = bool(surface.get("liquid_water_possible") or surface.get("alternate_surface_fluid_possible"))
    frozen_water = (water_fraction > 0.015 or icy_satellite) and surface_temp_k < 273.15
    # A frozen surface does not remove the planet's ocean basins.  Snowball
    # worlds retain their water inventory beneath sea ice even when open
    # liquid water and the ordinary surface hydrologic cycle are unavailable.
    frozen_ocean = bool(snowball_world and frozen_water and water_fraction > 0.12)
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
    relief_scale = _clamp(seed.get("relief_scale", 1.0), 0.2, 2.5)
    max_elevation_m *= relief_scale
    min_elevation_m *= relief_scale
    geologic_style = str(seed.get("geologic_style") or "").strip().lower()
    geologic_style_source = "explicit" if geologic_style else "derived"
    # Do not send every unconfigured solid planet through the same generic
    # rocky scaffold.  These are observable regime families inferred from the
    # existing thermal, volatile, atmospheric, and hydrologic inputs; a user
    # can still select any named style explicitly.
    if not geologic_style:
        if surface_temp_k >= 1050.0:
            geologic_style = "magma_seas"
        elif icy_satellite and tectonics == "cryotectonic":
            geologic_style = "active_ice_shell"
        elif pressure_bar >= 20.0 and surface_temp_k >= 550.0 and elements.get("S", 0.0) >= 0.2:
            geologic_style = "sulfur_heat_pipe"
        elif tectonics == "heat_pipe":
            geologic_style = "heat_pipe_volcanic"
        elif tectonics == "plutonic_squishy_lid":
            geologic_style = "plutonic_intrusive_uplands"
        elif frozen_water and surface_temp_k < 190.0:
            geologic_style = "volatile_frost_transport"
        elif frozen_water:
            geologic_style = "glaciated"
        elif hydrology == "none" and pressure_bar >= 0.15 and surface_temp_k >= 225.0:
            geologic_style = "evaporite_basins" if water_fraction >= 0.08 else "aeolian_dune_seas"
        elif tectonics == "episodic_lid":
            geologic_style = "episodic_rifting"
        else:
            geologic_style = "continental_oceanic" if mobile_plates else "stagnant_shields"
    if geologic_style == "plume_lid_volcanic":
        max_elevation_m = 11000.0
        min_elevation_m = -3000.0
        roughness = 0.42
        relief_driver = "plume_lid_coronae_tesserae_and_volcanic_plains"
    style_relief = {
        "cold_desert": (0.72, 0.66, "periglacial_cratered_plains_and_outflow_channels"),
        "glaciated": (0.62, 0.52, "ice_scoured_highlands_and_subglacial_basins"),
        "heat_pipe_volcanic": (1.25, 0.58, "shield_provinces_lava_plains_and_heat_pipes"),
        "sulfur_heat_pipe": (1.18, 0.64, "sulfur_calderas_lava_lakes_and_flow_fields"),
        "active_ice_shell": (0.55, 0.48, "chaos_terrain_ridges_chasmata_and_plume_fissures"),
        "volatile_frost_transport": (0.46, 0.36, "volatile_glaciers_sublimation_pits_and_frost_plains"),
        "aeolian_dune_seas": (0.48, 0.44, "sand_seas_yardangs_and_wind_corridors"),
        "evaporite_basins": (0.58, 0.38, "terminal_basins_salt_flats_and_paleoshorelines"),
        "magma_seas": (0.82, 0.34, "magma_seas_lava_plains_and_solidification_fronts"),
        "hydrocarbon_dunes_and_lakes": (0.52, 0.42, "organic_dunes_dendritic_channels_and_hydrocarbon_basins"),
        "episodic_rifting": (1.05, 0.56, "rift_provinces_flood_lavas_and_old_cratons"),
        "plutonic_intrusive_uplands": (0.96, 0.46, "intrusive_domes_batholith_uplands_and_local_fault_scarps"),
    }
    if geologic_style in style_relief:
        relief_factor, roughness, relief_driver = style_relief[geologic_style]
        max_elevation_m *= relief_factor
        min_elevation_m *= relief_factor
    roughness = _clamp(roughness + mafic_roughness_bonus - erosion * 0.08, 0.18, 0.9)
    airless_or_near_airless = pressure_bar < 0.01
    if pressure_bar < 0.02 and crater_retention == "low":
        crater_retention = "moderate" if mobile_plates or partial_resurfacing else "high"
    elif pressure_bar < 0.15 and crater_retention == "low":
        crater_retention = "moderate"
    if airless_or_near_airless and not liquid_water and not mobile_plates:
        crater_retention = "high"
        roughness = _clamp(max(roughness, 0.82), 0.18, 0.96)

    # The first-screen water value is a volatile-inventory index, not a desired
    # map color percentage.  Convert it to an equivalent global water depth;
    # the generated hypsometry will determine how much surface is inundated.
    # The nonlinear curve keeps modest inventories continental while allowing
    # genuinely wet seeds to become ocean worlds.  At the Earth control value
    # (0.71) it yields approximately Earth's 2.7 km global-equivalent layer.
    inventory_variation = seed_range(map_seed, "water_inventory_variation", 0.94, 1.06)
    equivalent_global_water_depth_m = 9000.0 * (water_fraction ** 3.4) * inventory_variation
    if liquid_water:
        thermal_retention = _clamp(
            1.0
            - max(0.0, surface_temp_k - 305.0) / 120.0
            - max(0.0, 245.0 - surface_temp_k) / 180.0,
            0.04,
            1.0,
        )
        pressure_retention = _clamp(pressure_bar / 0.08, 0.08, 1.0)
        equivalent_global_water_depth_m *= thermal_retention * pressure_retention
    elif not frozen_ocean:
        equivalent_global_water_depth_m = 0.0
    planet_kind = str(
        seed.get("planet_class")
        or seed.get("planet_template")
        or ""
    ).strip().lower()
    if planet_kind in {"desert_terrestrial", "desiccated_former_ocean"}:
        equivalent_global_water_depth_m = min(equivalent_global_water_depth_m, 90.0)
    # Legacy authored targets remain an explicit compatibility override only.
    # Normal generation never writes this field and therefore always uses the
    # inventory-volume route.
    target_ocean_fraction = 0.0
    if seed.get("ocean_fraction_target") is not None and (liquid_water or frozen_ocean):
        target_ocean_fraction = _clamp(seed.get("ocean_fraction_target"), 0.0, 0.92)
    cold_ice_factor = _clamp((273.15 - surface_temp_k) / 95.0, 0.0, 1.0)
    pressure_ice_factor = _clamp(0.78 + pressure_bar * 0.08, 0.55, 1.08)
    target_ice_fraction = (
        water_fraction
        * seed_range(map_seed, "ice_scale", 0.62, 1.32)
        * cold_ice_factor
        * pressure_ice_factor
        + seed_range(map_seed, "ice_bias", -0.04, 0.08)
    ) if frozen_water else 0.0
    if icy_satellite:
        target_ice_fraction = _clamp(seed.get("surface_ice_fraction", 0.98), 0.75, 1.0)
    if liquid_water and surface_temp_k < 286.0:
        target_ice_fraction += target_ocean_fraction * _clamp((286.0 - surface_temp_k) / 42.0, 0.0, 0.55)
    target_ice_fraction = _clamp(target_ice_fraction, 0.0, 1.0)
    if seed.get("target_ice_fraction") is not None:
        target_ice_fraction = _clamp(seed.get("target_ice_fraction"), 0.0, 1.0)

    if crater_retention == "high":
        crater_density = 0.85
    elif crater_retention == "moderate":
        crater_density = 0.42
    else:
        crater_density = 0.08
    crater_density *= 1.0 - erosion * 0.35
    crater_density *= 1.0 - _clamp(pressure_bar / 8.0, 0.0, 0.22)
    crater_density *= 1.0 - _clamp(internal_heat / 0.35, 0.0, 0.18)
    if "glacial" in erosion_processes:
        # Moving ice and repeated freeze/thaw burial strongly degrade the
        # visible impact population, especially the small-crater saturation
        # that otherwise makes a snowball resemble an airless moon.
        crater_density *= 1.0 - target_ice_fraction * 0.62
    if airless_or_near_airless and not liquid_water:
        crater_density = max(crater_density, 0.92 if crater_retention == "high" else 0.68)
    crater_density = _clamp(crater_density, 0.0, 1.0)
    retention_basin_fraction = {"high": 0.50, "moderate": 0.28, "low": 0.12}.get(crater_retention, 0.22)
    gravity_basin_factor = _clamp((0.16 / max(0.015, gravity_g)) ** 0.12, 0.75, 1.25)
    max_crater_diameter_km = min(
        radius_m / 1000.0 * 1.35,
        radius_m / 1000.0 * retention_basin_fraction * gravity_basin_factor,
    )
    if seed.get("max_crater_diameter_km") is not None:
        max_crater_diameter_km = min(
            max_crater_diameter_km,
            max(10.0, float(seed.get("max_crater_diameter_km") or 10.0)),
        )

    layers = [
        {"id": "elevation", "kind": "heightfield", "source": relief_driver},
        {"id": "slope", "kind": "derived_raster", "source": "elevation"},
        {"id": "crust_type", "kind": "classification", "source": "crust_composition"},
    ]
    if mobile_plates:
        layers.append({"id": "tectonic_boundaries", "kind": "vector", "source": "plate_solver_seed"})
    if crater_density > 0.12:
        layers.append({"id": "crater_population", "kind": "feature_set", "source": "impact_seed"})
    if equivalent_global_water_depth_m > 0.0 or target_ocean_fraction > 0.0:
        layers.append({"id": "water_mask", "kind": "raster_mask", "source": "sea_level"})
    if target_ice_fraction > 0:
        layers.append({"id": "ice_mask", "kind": "raster_mask", "source": "frozen_volatile_inventory"})
    if erosion_processes:
        layers.append({"id": "erosion_potential", "kind": "raster", "source": "surface_process_model"})
    specialized_features = {
        "aeolian_dune_seas": ["dune_fields", "prevailing_wind_corridors", "yardangs"],
        "evaporite_basins": ["salt_flats", "terminal_lakes", "paleoshorelines"],
        "magma_seas": ["molten_silicate_mask", "lava_flows", "solidification_fronts"],
        "hydrocarbon_dunes_and_lakes": ["methane_lakes", "hydrocarbon_channels", "organic_dunes"],
        "sulfur_heat_pipe": ["active_calderas", "sulfur_flow_fields", "volcanic_plumes"],
        "active_ice_shell": ["chaos_terrain", "double_ridges", "plume_fissures"],
        "volatile_frost_transport": ["seasonal_frost", "sublimation_pits", "volatile_glaciers"],
    }.get(geologic_style, [])
    for feature in specialized_features:
        layers.append({"id": feature, "kind": "procedural_feature_set", "source": geologic_style})
    layers.append({"id": "climate_stub", "kind": "placeholder", "source": "atmosphere_model"})

    map_recipe = list(regime.get("map_recipe") or [])
    if "allocate_map_canvas" not in map_recipe:
        map_recipe.insert(0, "allocate_map_canvas")
    for step in ("seed_heightfield_layers", "derive_water_and_erosion_masks"):
        if step not in map_recipe:
            map_recipe.append(step)
    if crater_density >= 0.75 and "simulate_impact_gardening" not in map_recipe:
        map_recipe.append("simulate_impact_gardening")
    for feature in specialized_features:
        step = f"generate_{feature}"
        if step not in map_recipe:
            map_recipe.append(step)

    surface_regime = "cratered_ice_shell" if icy_satellite else (
        "plume_lid_volcanic" if geologic_style == "plume_lid_volcanic" else (geologic_style or "rocky_surface")
    )

    return {
        "status": "terrain_seeded",
        "map_seed": map_seed,
        "map_seed_input": str(seed.get("map_seed") or "auto"),
        "map_canvas": {
            "projection": "equirectangular",
            "width_px": PLANETARY_CANVAS_WIDTH_PX,
            "height_px": PLANETARY_CANVAS_HEIGHT_PX,
            "vertical_datum": "mean_radius",
            "coverage": "full_moon" if icy_satellite else "full_planet",
            "radius_m": round(radius_m, 3),
            "circumference_m": round(circumference_m, 3),
            "equator_resolution_m_per_px": round(circumference_m / PLANETARY_CANVAS_WIDTH_PX, 3),
        },
        "heightfield": {
            "resolution": "global_seed",
            "min_elevation_m": round(min_elevation_m, 1),
            "max_elevation_m": round(max_elevation_m, 1),
            "sea_level_m": None,
            "target_ocean_fraction": round(target_ocean_fraction, 3),
            "equivalent_global_water_depth_m": round(equivalent_global_water_depth_m, 2),
            "sea_level_resolution": "volume_balance_against_generated_hypsometry",
            "roughness": round(roughness, 3),
            "relief_driver": relief_driver,
            "primary_topography": topography,
            "datum_center_m": 0.0 if geologic_style == "plume_lid_volcanic" else None,
            "hypsometry_compression": round(_clamp(seed.get("hypsometry_compression", 1.0), 0.2, 1.0), 3),
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
            "max_crater_diameter_km": round(max_crater_diameter_km, 1),
            "surface_age_myr": round(max(0.0, float(seed.get("surface_age_myr", 4500.0) or 0.0)), 1),
            "impact_flux_factor": round(max(0.05, float(seed.get("impact_flux_factor", 1.0) or 1.0)), 3),
            "resurfacing_fraction": round(_clamp(seed.get("resurfacing_fraction", 0.0), 0.0, 1.0), 3),
            "target_material": "water_ice_regolith" if icy_satellite else "rock_regolith",
            "atmospheric_entry_cutoff_km": round(max(0.0, float(seed.get("atmospheric_crater_cutoff_km", 0.4 * pressure_bar ** 0.5) or 0.0)), 3),
        },
        "erosion": {
            "processes": erosion_processes,
            "strength": round(erosion, 3),
            "atmospheric_pressure_bar": round(pressure_bar, 4),
        },
        "hydrology": {
            "cycle": hydrology,
            "liquid_water_possible": liquid_water,
            "frozen_water_possible": frozen_water,
            "frozen_ocean_possible": frozen_ocean,
            "target_ocean_fraction": round(target_ocean_fraction, 3),
            "water_inventory_index": round(water_fraction, 4),
            "equivalent_global_water_depth_m": round(equivalent_global_water_depth_m, 2),
            "coverage_mode": "derived_from_inventory_and_hypsometry",
            "target_ice_fraction": round(target_ice_fraction, 3),
            "drainage_enabled": hydrology in {"active", "limited"},
            "surface_fluid": seed.get("surface_fluid", "water"),
        },
        "specialized_surface_processes": {
            "geologic_style": geologic_style,
            "geologic_style_source": geologic_style_source,
            "features": specialized_features,
            "climate_mode": seed.get("climate_mode", "latitudinal_seasonal"),
            "seasonal_cycle": bool(seed.get("seasonal_cycle")),
            "synchronous_rotation": bool(seed.get("synchronous_rotation")),
            "high_pressure_ice": bool(seed.get("high_pressure_ice")),
        },
        "map_layers": layers,
        "map_recipe": map_recipe,
        "notes": [
            "This is a deterministic terrain scaffold, not a finished elevation raster.",
            "The next pass can replace layer seeds with plate polygons, crater fields, drainage, and erosion iterations.",
        ],
        "surface_regime": surface_regime,
    }
