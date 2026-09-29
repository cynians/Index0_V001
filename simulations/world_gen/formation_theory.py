import math

from simulations.world_gen.map_seed import seed_range


AU_M = 149_597_870_700.0


def kelvin_to_celsius(temperature_k):
    try:
        return float(temperature_k) - 273.15
    except (TypeError, ValueError):
        return 0.0


def condensation_fronts_au(luminosity_solar):
    luminosity = max(0.001, float(luminosity_solar or 1.0))
    scale = math.sqrt(luminosity)
    return {
        "refractory_inner_au": 0.08 * scale,
        "silicate_line_au": 0.28 * scale,
        "habitable_inner_au": 0.95 * scale,
        "habitable_outer_au": 1.67 * scale,
        "water_snow_line_au": 2.7 * scale,
        "co2_ice_line_au": 9.5 * scale,
        "co_ch4_ice_line_au": 28.0 * scale,
    }


def disk_temperature_k(luminosity_solar, semi_major_axis_au):
    distance = max(0.03, float(semi_major_axis_au or 1.0))
    luminosity = max(0.001, float(luminosity_solar or 1.0))
    return 278.0 * (luminosity ** 0.25) / math.sqrt(distance)


def max_feasible_planets(luminosity_solar, existing_count=0):
    luminosity = max(0.001, float(luminosity_solar or 1.0))
    base = 8 + int(min(4.0, math.log10(luminosity + 1.0) * 4.0))
    if luminosity < 0.12:
        base = 6
    return max(3, min(12, base + min(2, int(existing_count) // 5)))


def candidate_orbits_au(luminosity_solar, existing_orbits_au, count=2, system_id=""):
    fronts = condensation_fronts_au(luminosity_solar)
    existing = sorted(float(value) for value in existing_orbits_au if value and float(value) > 0)
    min_orbit = max(0.045, fronts["refractory_inner_au"] * 1.25)
    max_orbit = max(fronts["co2_ice_line_au"] * 1.35, fronts["water_snow_line_au"] * 2.4, 5.0)
    anchors = [min_orbit] + existing + [max_orbit]
    gaps = []
    for left, right in zip(anchors, anchors[1:]):
        if right <= left:
            continue
        log_gap = math.log(right / left)
        if log_gap >= 0.32:
            gaps.append((log_gap, left, right))
    gaps.sort(reverse=True)

    candidates = []
    for index, (_gap, left, right) in enumerate(gaps[:max(1, int(count or 1))]):
        ratio = seed_range(system_id, f"formation_gap_ratio_{index}", 0.38, 0.62)
        orbit = math.exp(math.log(left) * (1.0 - ratio) + math.log(right) * ratio)
        if all(abs(math.log(orbit / existing_orbit)) > 0.22 for existing_orbit in existing):
            candidates.append(round(orbit, 4))

    fallback_index = 0
    while len(candidates) < count:
        orbit = fronts["water_snow_line_au"] * seed_range(system_id, f"formation_fallback_{fallback_index}", 0.42, 1.85)
        fallback_index += 1
        if min_orbit <= orbit <= max_orbit and all(abs(math.log(orbit / other)) > 0.22 for other in existing + candidates):
            candidates.append(round(orbit, 4))
        if fallback_index > 16:
            break
    return candidates[:count]


def formation_model_for_orbit(luminosity_solar, semi_major_axis_au, system_id="", candidate_index=0, mode="generic"):
    fronts = condensation_fronts_au(luminosity_solar)
    orbit = max(0.03, float(semi_major_axis_au or 1.0))
    temp_k = disk_temperature_k(luminosity_solar, orbit)
    seed_key = f"{system_id}:{orbit:.5f}:{candidate_index}:{mode}"
    eccentric = str(mode or "generic").lower() == "eccentric"
    gimmick = seed_range(seed_key, "gimmick", 0.0, 1.0) < (0.08 if eccentric else 0.025)

    if orbit < fronts["silicate_line_au"]:
        zone = "refractory_inner_disk"
        template = "carbon_rich" if gimmick else "desiccated_former_ocean"
        volatile_inventory = "dry"
        water_range = (0.0, 0.035)
    elif orbit < fronts["habitable_inner_au"]:
        zone = "inner_rocky_disk"
        template = "carbon_rich" if gimmick else "silicate_terrestrial"
        volatile_inventory = "dry"
        water_range = (0.0, 0.18)
    elif orbit < fronts["water_snow_line_au"]:
        zone = "temperate_rocky_disk"
        template = "ocean_world" if seed_range(seed_key, "ocean_bias", 0.0, 1.0) > 0.58 else "silicate_terrestrial"
        volatile_inventory = "wet" if template == "ocean_world" else "earthlike"
        water_range = (0.18, 0.82)
    elif orbit < fronts["co2_ice_line_au"]:
        zone = "water_ice_accretion_zone"
        gas_capture = seed_range(seed_key, "gas_capture", 0.0, 1.0)
        template = "gas_giant" if gas_capture > 0.72 else ("ice_giant" if gas_capture > 0.52 else "ocean_world")
        volatile_inventory = "dense" if template in {"gas_giant", "ice_giant"} else "wet"
        water_range = (0.25, 0.95)
    elif orbit < fronts["co_ch4_ice_line_au"]:
        zone = "outer_ice_giant_zone"
        template = "ice_giant" if seed_range(seed_key, "ice_giant_bias", 0.0, 1.0) > 0.35 else "cratered_airless"
        volatile_inventory = "dense" if template == "ice_giant" else "thin"
        water_range = (0.02, 0.45)
    else:
        zone = "deep_volatile_ice_zone"
        template = "ice_giant" if seed_range(seed_key, "deep_giant_bias", 0.0, 1.0) > 0.62 else "cratered_airless"
        volatile_inventory = "dense" if template == "ice_giant" else "thin"
        water_range = (0.0, 0.25)

    core_mass_earth = seed_range(seed_key, "core_mass", 0.25, 4.5)
    if template == "gas_giant":
        core_mass_earth = seed_range(seed_key, "gas_core_mass", 6.0, 18.0)
    elif template == "ice_giant":
        core_mass_earth = seed_range(seed_key, "ice_core_mass", 4.0, 12.0)

    return {
        "model_version": "formation_theory_v001",
        "formation_zone": zone,
        "formation_orbit_au": round(orbit, 4),
        "present_orbit_au": round(orbit, 4),
        "disk_temperature_k": round(temp_k, 1),
        "disk_temperature_c": round(kelvin_to_celsius(temp_k), 1),
        "condensation_fronts_au": {key: round(value, 4) for key, value in fronts.items()},
        "suggested_planet_template": template,
        "volatile_inventory": volatile_inventory,
        "water_fraction_range": [round(water_range[0], 3), round(water_range[1], 3)],
        "core_accretion_mass_earth": round(core_mass_earth, 3),
        "disk_gas_lifetime_myr": round(seed_range(seed_key, "disk_lifetime", 1.4, 6.2), 2),
        "envelope_mass_fraction": round(seed_range(seed_key, "envelope_fraction", 0.0, 0.08) if template not in {"gas_giant", "ice_giant"} else seed_range(seed_key, "giant_envelope_fraction", 0.12, 0.78), 4),
        "runaway_gas_accretion_likely": template == "gas_giant",
        "stochastic_exception": gimmick,
    }


def volatile_history_from_seed(seed, retained_column_fraction=1.0):
    seed = seed if isinstance(seed, dict) else {}
    formation = seed.get("formation_model") if isinstance(seed.get("formation_model"), dict) else {}
    volatile_key = str(seed.get("volatile_inventory") or formation.get("volatile_inventory") or "earthlike").lower()
    water_fraction = max(0.0, min(1.0, float(seed.get("water_fraction", 0.0) or 0.0)))
    base = {
        "none": 0.02,
        "dry": 0.12,
        "thin": 0.35,
        "earthlike": 1.0,
        "wet": 1.8,
        "dense": 4.5,
    }.get(volatile_key, 1.0)
    primordial = base * (0.45 + water_fraction * 0.6)
    outgassed = base * seed_range(str(seed.get("resolved_map_seed") or seed.get("planet_id") or ""), "outgassed_volatiles", 0.18, 0.55)
    late_delivered = base * seed_range(str(seed.get("resolved_map_seed") or seed.get("planet_id") or ""), "late_delivered_volatiles", 0.02, 0.35)
    retained = max(0.0, min(1.0, float(retained_column_fraction or 0.0)))
    escaped = (primordial + outgassed + late_delivered) * (1.0 - retained)
    return {
        "primordial_volatiles_bar": round(primordial, 4),
        "outgassed_volatiles_bar": round(outgassed, 4),
        "late_delivered_volatiles_bar": round(late_delivered, 4),
        "escaped_or_stripped_volatiles_bar": round(escaped, 4),
        "retained_fraction": round(retained, 4),
        "terraforming_adjustment_bar": 0.0,
    }
