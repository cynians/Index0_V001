import math


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


def _heat_pipe_support_model(seed, internal_heat_w_m2, tidal_heating_w_m2):
    intrinsic_heat = max(0.0, float(internal_heat_w_m2) - float(tidal_heating_w_m2))
    surface_age_myr = max(0.0, float(seed.get("surface_age_myr", 4500.0) or 4500.0))
    if tidal_heating_w_m2 >= 0.12:
        supported = True
        source = "tidal_heating"
    elif intrinsic_heat >= 0.16:
        supported = True
        source = "high_intrinsic_heat"
    elif surface_age_myr <= 650.0 and intrinsic_heat >= 0.07:
        supported = True
        source = "young_planetary_heat"
    else:
        supported = False
        source = "insufficient_melt_heat_flux"
    return {
        "supported": supported,
        "source": source,
        "intrinsic_heat_w_m2": round(intrinsic_heat, 5),
        "tidal_heating_w_m2": round(float(tidal_heating_w_m2), 5),
        "surface_age_myr": round(surface_age_myr, 1),
        "minimum_tidal_heat_w_m2": 0.12,
        "minimum_intrinsic_heat_w_m2": 0.16,
        "young_world_max_age_myr": 650.0,
    }


def _tectonic_regime(
    seed,
    physics,
    internal_heat_w_m2,
    mantle_present,
    liquid_water_possible,
    heat_pipe_supported,
):
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
        "plutonic_squishy_lid",
        "heat_pipe",
        "inactive",
    }
    if requested in explicit_modes:
        if requested != "heat_pipe" or heat_pipe_supported:
            return requested

    if internal_heat_w_m2 < 0.015 or mantle_fraction < 0.08:
        return "inactive"
    if heat_pipe_supported and internal_heat_w_m2 > 0.18 and crust_fraction < 0.025:
        return "heat_pipe"
    if internal_heat_w_m2 > 0.055 and liquid_water_possible:
        return "plate_tectonics"
    # Intrusive magmatism can soften a mostly stagnant lithosphere without
    # producing a mobile lid or an extrusion-dominated heat pipe.  This gives
    # broad plutonic uplands and local deformation rather than global rifts.
    if internal_heat_w_m2 > 0.070 and crust_fraction >= 0.025:
        return "plutonic_squishy_lid"
    if internal_heat_w_m2 > 0.04:
        return "episodic_lid"
    return "stagnant_lid"


def _element_abundance_percent(seed, symbol):
    composition = seed.get("crust_composition") if isinstance(seed.get("crust_composition"), dict) else {}
    total = 0.0
    for bucket in ("major_elements", "trace_elements"):
        for element in composition.get(bucket, []) or []:
            if element.get("symbol") == symbol:
                try:
                    total += float(element.get("abundance_percent", 0.0) or 0.0)
                except (TypeError, ValueError):
                    pass
    return total


def _radiogenic_heat_multiplier(seed):
    potassium = _element_abundance_percent(seed, "K")
    uranium = _element_abundance_percent(seed, "U")
    thorium = _element_abundance_percent(seed, "Th")
    multiplier = 0.72 + min(1.1, potassium / 2.7 * 0.18)
    multiplier += min(0.9, uranium / 0.00018 * 0.26)
    multiplier += min(0.9, thorium / 0.00075 * 0.24)
    return _clamp(multiplier, 0.35, 2.4)


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
    icy_satellite = infer_world_class(seed, physics) == "icy_satellite"

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
    radiogenic_multiplier = _radiogenic_heat_multiplier(seed)
    internal_heat_w_m2 = 0.087 * size_factor * core_heat_factor * mantle_heat_factor * radiogenic_multiplier
    internal_heat_w_m2 = max(0.0, internal_heat_w_m2)
    tidal_heating_w_m2 = max(0.0, float(seed.get("tidal_heating_w_m2", 0.0) or 0.0))
    internal_heat_w_m2 += tidal_heating_w_m2
    heat_pipe_support = _heat_pipe_support_model(
        seed,
        internal_heat_w_m2,
        tidal_heating_w_m2,
    )
    mantle_depth_m = max(1.0, mantle_fraction * radius_earth * 6_371_000.0)
    mantle_delta_t_k = 700.0 + min(1900.0, internal_heat_w_m2 * 7800.0)
    water_weakening = 1.0 + water_fraction * 0.35
    viscosity_pa_s = 1.0e21 / water_weakening * math.exp(-min(2.2, internal_heat_w_m2 * 8.0))
    rayleigh_number = (
        4500.0 * max(0.01, gravity_g * 9.80665) * 3.0e-5
        * mantle_delta_t_k * mantle_depth_m ** 3
        / (1.0e-6 * max(1.0e17, viscosity_pa_s))
    )

    liquid_water_possible = (not icy_satellite) and (
        water_fraction > 0.03
        and pressure_bar >= 0.006
        and 250.0 <= surface_temp_k <= 395.0
    )
    surface_fluid = str(seed.get("surface_fluid") or "water").strip().lower()
    alternate_fluid_possible = (
        ("methane" in surface_fluid and pressure_bar >= 0.08 and 70.0 <= surface_temp_k <= 135.0)
        or (surface_fluid == "brine" and pressure_bar >= 0.01 and 235.0 <= surface_temp_k <= 390.0)
        or ("magma" in surface_fluid and surface_temp_k >= 1050.0)
    )
    hydrologic_cycle = (
        "active"
        if (
            liquid_water_possible
            and water_fraction >= 0.08
            and pressure_bar >= 0.08
            and 260.0 <= surface_temp_k <= 360.0
        )
        else ("limited" if liquid_water_possible else ("active" if alternate_fluid_possible else "none"))
    )

    if icy_satellite:
        resurfacing_fraction = _clamp(seed.get("resurfacing_fraction", 0.0), 0.0, 1.0)
        tectonics = "cryotectonic" if internal_heat_w_m2 >= 0.008 or resurfacing_fraction >= 0.16 else "inactive"
    else:
        resurfacing_fraction = _clamp(seed.get("resurfacing_fraction", 0.0), 0.0, 1.0)
        tectonics = _tectonic_regime(
            seed,
            physics,
            internal_heat_w_m2,
            mantle_present,
            liquid_water_possible,
            heat_pipe_support["supported"],
        )
    volcanic_activity = "none"
    if mantle_present and internal_heat_w_m2 >= 0.015:
        volcanic_activity = "low"
    if mantle_present and internal_heat_w_m2 >= 0.055:
        volcanic_activity = "moderate"
    if mantle_present and internal_heat_w_m2 >= 0.14:
        volcanic_activity = "high"
    if icy_satellite:
        volcanic_activity = "cryovolcanic" if internal_heat_w_m2 >= 0.025 else ("possible_ancient_cryovolcanism" if tectonics == "cryotectonic" else "none")
    if not icy_satellite:
        volcanic_resurfacing_floor = {
            "low": 0.005,
            "moderate": 0.04,
            "high": 0.14,
        }.get(volcanic_activity, 0.0)
        resurfacing_fraction = max(
            resurfacing_fraction,
            volcanic_resurfacing_floor,
        )

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
    if pressure_bar >= 20.0 and surface_temp_k >= 550.0:
        erosion_processes.append("supercritical_co2_chemical_weathering")
        if _element_abundance_percent(seed, "S") >= 0.2:
            erosion_processes.append("sulfur_atmosphere_surface_reactions")
    if water_fraction > 0.02 and surface_temp_k < 273.0 and pressure_bar >= 0.02:
        erosion_processes.append("glacial")
    if not erosion_processes:
        erosion_processes.append("impact_gardening")
    if icy_satellite and resurfacing_fraction >= 0.12:
        erosion_processes.append("viscous_relaxation")

    resurfacing_score = 0
    if icy_satellite:
        primary_topography = "impact_basins_fractured_ice_plains"
    elif tectonics in {"plate_tectonics", "mobile_lid"}:
        resurfacing_score += 3
    elif tectonics in {"episodic_lid", "plutonic_squishy_lid", "heat_pipe"}:
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
    elif str(seed.get("geologic_style") or "") == "plume_lid_volcanic":
        primary_topography = "plume_rises_coronae_tesserae_and_volcanic_plains"
    elif tectonics == "heat_pipe":
        primary_topography = "volcanic_plains_and_shield_provinces"
    elif tectonics == "plutonic_squishy_lid":
        primary_topography = "plutonic_uplands_intrusive_domes_and_localized_deformation"
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
            "tidal_heating_w_m2": tidal_heating_w_m2,
            "heat_pipe_support": heat_pipe_support,
            "radiogenic_heat_multiplier": radiogenic_multiplier,
            "tectonic_regime": tectonics,
            "volcanic_activity": volcanic_activity,
            "crust_type": crust_type,
            "ice_shell_thickness_km": physics.get("ice_shell_thickness_km") if icy_satellite else None,
            "bulk_ice_fraction": physics.get("bulk_ice_fraction") if icy_satellite else None,
            "subsurface_ocean_possible": bool(icy_satellite and internal_heat_w_m2 >= 0.018),
        },
        "thermal_evolution": {
            "model_version": "thermal_evolution_v002",
            "radiogenic_elements": {
                "K_percent": round(_element_abundance_percent(seed, "K"), 5),
                "U_percent": round(_element_abundance_percent(seed, "U"), 6),
                "Th_percent": round(_element_abundance_percent(seed, "Th"), 6),
            },
            "radiogenic_heat_multiplier": round(radiogenic_multiplier, 3),
            "internal_heat_w_m2": round(internal_heat_w_m2, 5),
            "mantle_fraction": round(mantle_fraction, 4),
            "water_weakening_factor": round(water_weakening, 3),
            "mantle_temperature_contrast_k_proxy": round(mantle_delta_t_k, 1),
            "mantle_viscosity_pa_s_proxy": viscosity_pa_s,
            "rayleigh_number_proxy": rayleigh_number,
            "critical_rayleigh_number": 1100.0,
            "convective": bool(rayleigh_number >= 1100.0),
            "derived_tectonic_regime": tectonics,
            "requested_tectonic_regime": str(seed.get("tectonics_mode") or "unknown"),
            "heat_pipe_request_rejected": bool(
                str(seed.get("tectonics_mode") or "").strip().lower() == "heat_pipe"
                and tectonics != "heat_pipe"
            ),
            "heat_pipe_support": heat_pipe_support,
            "note": "Tectonic mode is derived from heat, geometry, water, and explicit requests; heat-pipe requests require a qualifying thermal or tidal source.",
        },
        "surface_processes": {
            "surface_pressure_bar": pressure_bar,
            "surface_temperature_k": surface_temp_k,
            "surface_temperature_c": surface_temp_k - 273.15,
            "surface_gravity_g": gravity_g,
            "liquid_water_possible": liquid_water_possible,
            "alternate_surface_fluid_possible": alternate_fluid_possible,
            "surface_fluid": surface_fluid,
            "hydrologic_cycle": hydrologic_cycle,
            "aeolian_activity": aeolian_activity,
            "erosion_processes": erosion_processes,
            "crater_retention": crater_retention,
            "primary_topography": primary_topography,
            "resurfacing_fraction": resurfacing_fraction,
        },
        "map_recipe": map_recipe,
        "notes": [
            "This regime selects which terrain processes are physically allowed before map synthesis.",
            "Plate boundaries are only enabled when mantle heat and surface conditions can support mobile lithosphere.",
            "Crater preservation rises when atmosphere, hydrology, tectonics, and volcanism cannot erase impacts.",
        ],
    }
from simulations.world_gen.world_classification import infer_world_class
