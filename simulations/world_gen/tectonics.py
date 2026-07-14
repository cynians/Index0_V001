import math

from simulations.world_gen.map_seed import resolved_map_seed, seed_range


def _clamp(value, low, high):
    return max(low, min(high, float(value)))


def _wrapped_delta(a, b):
    delta = float(a) - float(b)
    if delta > 0.5:
        delta -= 1.0
    elif delta < -0.5:
        delta += 1.0
    return delta


def _wrapped_distance(ax, ay, bx, by):
    dx = _wrapped_delta(ax, bx)
    dy = float(ay) - float(by)
    return math.hypot(dx, dy)


def _mantle_current_at(nx, ny, cell_count=3, map_seed=""):
    vx = 0.0
    vy = 0.0
    for index in range(cell_count):
        phase = index / max(1, cell_count)
        cx = (phase * seed_range(map_seed, f"cell_{index}_spacing", 0.29, 0.47) + seed_range(map_seed, f"cell_{index}_x", 0.04, 0.34)) % 1.0
        cy = _clamp(0.18 + (index % 3) * seed_range(map_seed, f"cell_{index}_band", 0.18, 0.28) + seed_range(map_seed, f"cell_{index}_y", -0.05, 0.08), 0.08, 0.92)
        dx = _wrapped_delta(nx, cx)
        dy = ny - cy
        falloff = math.exp(-((dx * dx + dy * dy) / 0.085))
        swirl = -1.0 if seed_range(map_seed, f"cell_{index}_swirl", 0, 1) < 0.5 else 1.0
        vx += (-dy * swirl + 0.18 * math.sin(math.tau * (ny + phase))) * falloff
        vy += (dx * swirl + 0.12 * math.cos(math.tau * (nx - phase))) * falloff
    length = math.hypot(vx, vy)
    if length <= 1e-9:
        return {"x": 0.0, "y": 0.0, "speed_cm_per_year": 0.0}
    speed = _clamp(length * 5.5, 0.5, 8.5)
    return {
        "dir_x": round(vx / length, 4),
        "dir_y": round(vy / length, 4),
        "speed_cm_per_year": round(speed, 3),
    }


def _plate_centers(count, map_seed=""):
    centers = []
    golden = 0.61803398875
    x_offset = seed_range(map_seed, "plate_x_offset", 0.0, 1.0)
    y_phase = seed_range(map_seed, "plate_y_phase", 0.0, math.tau)
    for index in range(count):
        nx = (x_offset + index * golden + seed_range(map_seed, f"plate_{index}_jitter_x", -0.035, 0.035)) % 1.0
        band = index % 4
        ny = 0.16 + band * 0.22 + 0.055 * math.sin(index * 1.73 + y_phase)
        ny += seed_range(map_seed, f"plate_{index}_jitter_y", -0.045, 0.045)
        ny = _clamp(ny, 0.08, 0.92)
        centers.append((nx, ny))
    return centers


def _continent_seed_signal(nx, ny, map_seed=""):
    longitude = nx * math.tau
    latitude = (ny - 0.5) * math.pi
    phase_a = seed_range(map_seed, "continent_phase_a", 0.0, math.tau)
    phase_b = seed_range(map_seed, "continent_phase_b", 0.0, math.tau)
    phase_c = seed_range(map_seed, "continent_phase_c", 0.0, math.tau)
    return (
        0.52 * math.sin(longitude * seed_range(map_seed, "continent_freq_a", 1.1, 1.9) + latitude * 0.8 + phase_a)
        + 0.34 * math.cos(longitude * seed_range(map_seed, "continent_freq_b", 2.0, 3.2) - latitude * 1.15 + phase_b)
        + 0.22 * math.sin(longitude * seed_range(map_seed, "continent_freq_c", 3.2, 5.1) + math.sin(latitude + phase_c))
    )


def _nearest_plate_index(nx, ny, plates):
    best_index = 0
    best_distance = 999.0
    for index, plate in enumerate(plates):
        distance = _wrapped_distance(nx, ny, plate["center_x"], plate["center_y"])
        if distance < best_distance:
            best_distance = distance
            best_index = index
    return best_index


def _boundary_kind(plate_a, plate_b):
    dx = _wrapped_delta(plate_b["center_x"], plate_a["center_x"])
    dy = plate_b["center_y"] - plate_a["center_y"]
    normal_len = math.hypot(dx, dy) or 1.0
    nx = dx / normal_len
    ny = dy / normal_len
    rel_vx = plate_b["velocity_x_cm_year"] - plate_a["velocity_x_cm_year"]
    rel_vy = plate_b["velocity_y_cm_year"] - plate_a["velocity_y_cm_year"]
    normal_motion = rel_vx * nx + rel_vy * ny
    shear_motion = abs(rel_vx * -ny + rel_vy * nx)
    if normal_motion < -0.65:
        if plate_a["plate_type"] != plate_b["plate_type"]:
            return "subduction"
        return "collision"
    if normal_motion > 0.55:
        return "divergent"
    if shear_motion > 0.7:
        return "transform"
    return "passive"


def derive_tectonic_model(terrain, seed=None, physics=None, planet_id=""):
    terrain = terrain if isinstance(terrain, dict) else {}
    tectonics = terrain.get("tectonics") if isinstance(terrain.get("tectonics"), dict) else {}
    hydrology = terrain.get("hydrology") if isinstance(terrain.get("hydrology"), dict) else {}
    map_seed = terrain.get("map_seed") or resolved_map_seed(seed, planet_id=planet_id)
    requested_count = int(tectonics.get("plate_count", 8) or 8)
    plate_count = max(3, min(18, requested_count))
    ocean_fraction = _clamp(hydrology.get("target_ocean_fraction", 0.45), 0.0, 0.92)

    plates = []
    for index, (center_x, center_y) in enumerate(_plate_centers(plate_count, map_seed=map_seed)):
        current = _mantle_current_at(center_x, center_y, map_seed=map_seed)
        continentality = _continent_seed_signal(center_x, center_y, map_seed=map_seed)
        continentality += (0.5 - ocean_fraction) * 0.65
        continentality += seed_range(map_seed, f"plate_{index}_continentality_jitter", -0.22, 0.22)
        if continentality > 0.18:
            plate_type = "continental"
        elif continentality < -0.18:
            plate_type = "oceanic"
        else:
            plate_type = "mixed"
        speed = current["speed_cm_per_year"]
        plates.append({
            "id": f"plate_{index + 1:02d}",
            "center_x": round(center_x, 4),
            "center_y": round(center_y, 4),
            "plate_type": plate_type,
            "continentality": round(_clamp((continentality + 1.4) / 2.8, 0.0, 1.0), 3),
            "velocity_x_cm_year": round(current["dir_x"] * speed, 3),
            "velocity_y_cm_year": round(current["dir_y"] * speed, 3),
            "speed_cm_per_year": speed,
        })

    currents = []
    for row in range(3):
        for col in range(5):
            nx = (col + 0.5) / 5.0
            ny = (row + 0.5) / 3.0
            current = _mantle_current_at(nx, ny, map_seed=map_seed)
            currents.append({
                "pos_x": round(nx, 4),
                "pos_y": round(ny, 4),
                **current,
            })

    sample_w = 57
    sample_h = 29
    owner_rows = []
    boundary_segments = []
    boundary_pairs = {}
    for row in range(sample_h):
        ny = row / max(1, sample_h - 1)
        owner_row = []
        for col in range(sample_w):
            nx = col / max(1, sample_w - 1)
            owner_row.append(_nearest_plate_index(nx, ny, plates))
        owner_rows.append(owner_row)

    for row in range(sample_h - 1):
        for col in range(sample_w - 1):
            a = owner_rows[row][col]
            east = owner_rows[row][col + 1]
            south = owner_rows[row + 1][col]
            if east != a:
                pair = tuple(sorted((a, east)))
                x = (col + 0.5) / max(1, sample_w - 1)
                y1 = row / max(1, sample_h - 1)
                y2 = (row + 1) / max(1, sample_h - 1)
                boundary_segments.append({"x1": x, "y1": y1, "x2": x, "y2": y2, "plate_a": plates[pair[0]]["id"], "plate_b": plates[pair[1]]["id"]})
                boundary_pairs[pair] = boundary_pairs.get(pair, 0) + 1
            if south != a:
                pair = tuple(sorted((a, south)))
                x1 = col / max(1, sample_w - 1)
                x2 = (col + 1) / max(1, sample_w - 1)
                y = (row + 0.5) / max(1, sample_h - 1)
                boundary_segments.append({"x1": x1, "y1": y, "x2": x2, "y2": y, "plate_a": plates[pair[0]]["id"], "plate_b": plates[pair[1]]["id"]})
                boundary_pairs[pair] = boundary_pairs.get(pair, 0) + 1

    boundaries = []
    boundary_kind_by_pair = {}
    for (a, b), length in sorted(boundary_pairs.items(), key=lambda item: item[1], reverse=True):
        kind = _boundary_kind(plates[a], plates[b])
        boundary_kind_by_pair[tuple(sorted((plates[a]["id"], plates[b]["id"])))] = kind
        boundaries.append({
            "plate_a": plates[a]["id"],
            "plate_b": plates[b]["id"],
            "kind": kind,
            "sample_length": length,
            "activity": round(min(1.0, length / max(1, sample_w)), 3),
        })

    for segment in boundary_segments:
        pair = tuple(sorted((segment.get("plate_a"), segment.get("plate_b"))))
        segment["kind"] = boundary_kind_by_pair.get(pair, "passive")

    return {
        "status": "plates_defined",
        "planet_id": planet_id,
        "map_seed": map_seed,
        "age_myr": 0.0,
        "plate_count": plate_count,
        "sample_grid": {"width": sample_w, "height": sample_h, "owners": owner_rows},
        "plates": plates,
        "mantle_currents": currents,
        "boundary_segments": boundary_segments,
        "boundaries": boundaries,
        "notes": [
            "Plate motion is seeded from mantle current cells before terrain is uplifted.",
            "Advancing tectonics turns convergent boundaries into mountains/trenches and divergent boundaries into ocean basins.",
        ],
    }


def advance_tectonics_model(tectonic_model, terrain, million_years=125.0):
    tectonic_model = tectonic_model if isinstance(tectonic_model, dict) else {}
    boundaries = list(tectonic_model.get("boundaries") or [])
    age = float(tectonic_model.get("age_myr", 0.0) or 0.0) + max(1.0, float(million_years or 1.0))
    uplift = 0.0
    basin = 0.0
    erosion = 0.0
    for boundary in boundaries:
        activity = float(boundary.get("activity", 0.0) or 0.0)
        kind = boundary.get("kind")
        if kind in {"collision", "subduction"}:
            uplift += activity
        elif kind == "divergent":
            basin += activity
        if kind in {"collision", "subduction", "divergent"}:
            erosion += activity * 0.35

    advanced = dict(tectonic_model)
    plates = []
    drift_factor = max(1.0, float(million_years or 1.0)) / 100.0
    map_seed = str(advanced.get("map_seed") or "")
    for plate in list(advanced.get("plates") or []):
        if not isinstance(plate, dict):
            continue
        updated = dict(plate)
        try:
            cx = float(updated.get("center_x", 0.0) or 0.0)
            cy = float(updated.get("center_y", 0.5) or 0.5)
            vx = float(updated.get("velocity_x_cm_year", 0.0) or 0.0)
            vy = float(updated.get("velocity_y_cm_year", 0.0) or 0.0)
        except (TypeError, ValueError):
            plates.append(updated)
            continue
        current = _mantle_current_at(cx, cy, map_seed=map_seed)
        cx = (cx + vx * 0.00022 * drift_factor + current["dir_x"] * 0.0025 * drift_factor) % 1.0
        cy = _clamp(cy + vy * 0.00016 * drift_factor + current["dir_y"] * 0.0018 * drift_factor, 0.045, 0.955)
        speed = _clamp(float(updated.get("speed_cm_per_year", current["speed_cm_per_year"]) or 0.0) * 0.88 + current["speed_cm_per_year"] * 0.12, 0.3, 9.5)
        updated["center_x"] = round(cx, 4)
        updated["center_y"] = round(cy, 4)
        updated["velocity_x_cm_year"] = round((float(updated.get("velocity_x_cm_year", 0.0) or 0.0) * 0.82 + current["dir_x"] * speed * 0.18), 3)
        updated["velocity_y_cm_year"] = round((float(updated.get("velocity_y_cm_year", 0.0) or 0.0) * 0.82 + current["dir_y"] * speed * 0.18), 3)
        updated["speed_cm_per_year"] = round(speed, 3)
        plates.append(updated)
    if plates:
        advanced["plates"] = plates
    advanced["status"] = "tectonics_advanced"
    advanced["age_myr"] = round(age, 1)
    advanced["geologic_time_step_myr"] = max(1.0, float(million_years or 1.0))
    time_factor = min(1.0, age / 125.0)
    advanced["surface_effects"] = {
        "orogenic_uplift": round(min(1.0, time_factor * 0.65 + uplift / max(1.0, len(boundaries) * 0.12)), 3),
        "ocean_basin_opening": round(min(1.0, time_factor * 0.55 + basin / max(1.0, len(boundaries) * 0.10)), 3),
        "erosion_progress": round(min(1.0, age / 320.0 + erosion / max(1.0, len(boundaries) * 1.8)), 3),
    }
    return advanced


def mature_tectonics_model(tectonic_model, terrain, cycles=4, million_years_per_cycle=45.0):
    matured = tectonic_model if isinstance(tectonic_model, dict) else {}
    for _index in range(max(1, int(cycles or 1))):
        matured = advance_tectonics_model(matured, terrain, million_years=million_years_per_cycle)
    matured["maturation_cycles"] = max(1, int(cycles or 1))
    return matured


def derive_crater_model(terrain, seed=None, physics=None, planet_id=""):
    terrain = terrain if isinstance(terrain, dict) else {}
    seed = seed if isinstance(seed, dict) else {}
    physics = physics if isinstance(physics, dict) else {}
    cratering = terrain.get("cratering") if isinstance(terrain.get("cratering"), dict) else {}
    map_seed = terrain.get("map_seed") or resolved_map_seed(seed, planet_id=planet_id)
    density = _clamp(cratering.get("density", 0.65), 0.0, 1.0)
    retention = str(cratering.get("retention") or "moderate")
    max_km = max(10.0, float(cratering.get("max_crater_diameter_km", 400.0) or 400.0))
    radius_m = max(1.0, float(physics.get("radius_m") or (terrain.get("map_canvas") or {}).get("radius_m") or 6_371_000.0))
    radius_km = radius_m / 1000.0
    circumference_km = math.tau * radius_km
    surface_area_million_km2 = 4.0 * math.pi * radius_km * radius_km / 1_000_000.0
    min_km = max(1.2, circumference_km / 512.0)
    atmospheric_cutoff_km = max(0.0, float(cratering.get("atmospheric_entry_cutoff_km", 0.0) or 0.0))
    min_km = max(min_km, atmospheric_cutoff_km)
    surface_age_myr = max(0.0, float(cratering.get("surface_age_myr", seed.get("surface_age_myr", 4500.0)) or 0.0))
    impact_flux = max(0.05, float(cratering.get("impact_flux_factor", seed.get("impact_flux_factor", 1.0)) or 1.0))
    resurfacing = _clamp(cratering.get("resurfacing_fraction", seed.get("resurfacing_fraction", 0.0)), 0.0, 1.0)
    exposure = 1.0 - math.exp(-surface_age_myr / 1150.0)
    retention_factor = {"high": 1.0, "moderate": 0.58, "low": 0.2}.get(retention, 0.5)
    population_slope = _clamp(seed.get("crater_population_slope", 1.9), 1.45, 2.35)
    stochastic_flux = seed_range(map_seed, "crater_flux_history", 0.72, 1.28)
    density_ge10_per_million_km2 = 780.0 * density * exposure * impact_flux * stochastic_flux * retention_factor
    expected_count = (
        density_ge10_per_million_km2
        * surface_area_million_km2
        * ((min_km / 10.0) ** -population_slope)
    )
    count = max(12, min(2200, int(round(expected_count))))
    craters = []
    golden = 0.61803398875
    for index in range(count):
        nx = (seed_range(map_seed, "crater_x_offset", 0.0, 1.0) + index * golden) % 1.0
        nx = (nx + seed_range(map_seed, f"crater_{index}_jitter_x", -0.025, 0.025)) % 1.0
        sphere_z = 1.0 - 2.0 * ((index + 0.5) / count)
        sphere_z = _clamp(sphere_z + seed_range(map_seed, f"crater_{index}_jitter_z", -0.025, 0.025), -0.995, 0.995)
        latitude = math.asin(sphere_z)
        ny = _clamp(0.5 - latitude / math.pi, 0.01, 0.99)
        quantile = _clamp(seed_range(map_seed, f"crater_{index}_size", 0.0001, 0.9999), 0.0001, 0.9999)
        diameter = min(max_km, min_km * ((1.0 - quantile) ** (-1.0 / population_slope)))
        small_crater_survival = 1.0 - resurfacing * math.exp(-diameter / 38.0)
        if seed_range(map_seed, f"crater_{index}_survival", 0.0, 1.0) > small_crater_survival:
            continue
        simple_to_complex_km = max(8.0, 18.0 * (max(0.02, float(physics.get("surface_gravity_g", 1.0) or 1.0)) / 0.16) ** -0.22)
        depth_ratio = 0.105 if diameter <= simple_to_complex_km else 0.075 * (diameter / simple_to_complex_km) ** -0.22
        thermal_relaxation = resurfacing * _clamp((diameter - 25.0) / 180.0, 0.0, 0.78)
        depth_m = min(7200.0, diameter * 1000.0 * depth_ratio) * (1.0 - thermal_relaxation)
        rim_height_m = min(1800.0, diameter * 1000.0 * 0.025) * (1.0 - thermal_relaxation * 0.65)
        craters.append({
            "id": f"crater_{index + 1:02d}",
            "x": round(nx, 4),
            "y": round(ny, 4),
            "diameter_km": round(diameter, 2),
            "depth_m": round(depth_m, 1),
            "rim_height_m": round(rim_height_m, 1),
            "morphology": "complex_or_basin" if diameter > simple_to_complex_km else "simple",
            "relaxation_fraction": round(thermal_relaxation, 3),
        })
    actual_density = len(craters) / max(1e-9, surface_area_million_km2)
    return {
        "status": "craters_seeded",
        "planet_id": planet_id,
        "map_seed": map_seed,
        "density": round(density, 3),
        "radius_m": round(radius_m, 3),
        "surface_area_million_km2": round(surface_area_million_km2, 4),
        "minimum_catalog_diameter_km": round(min_km, 3),
        "atmospheric_entry_cutoff_km": round(atmospheric_cutoff_km, 3),
        "maximum_crater_diameter_km": round(max_km, 3),
        "size_frequency_cumulative_slope": round(population_slope, 3),
        "craters_per_million_km2_above_catalog_min": round(actual_density, 2),
        "surface_age_myr": round(surface_age_myr, 1),
        "impact_flux_factor": round(impact_flux * stochastic_flux, 3),
        "resurfacing_fraction": round(resurfacing, 3),
        "craters": craters,
        "drivers": {
            "size": ["impactor_size_distribution", "surface_gravity", "body_radius", "target_material", "impact_velocity"],
            "density": ["surface_exposure_age", "impact_flux", "atmospheric_screening", "erosion", "resurfacing", "saturation"],
        },
        "notes": [
            "Crater diameters follow a deterministic power-law size-frequency population capped by the body's basin scale.",
            "Surface age and impact flux add craters; atmosphere, erosion, resurfacing, and saturation reduce the retained population.",
        ],
    }
