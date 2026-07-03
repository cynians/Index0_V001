import math

from simulations.world_gen.map_seed import resolved_map_seed, seed_range


def _clamp(value, low, high):
    return max(low, min(high, float(value)))


def height_marker_interval_m(pixels_per_map_pixel):
    zoom = max(0.0, float(pixels_per_map_pixel or 0.0))
    if zoom >= 12.0:
        return 1
    if zoom >= 6.0:
        return 2
    if zoom >= 3.0:
        return 5
    if zoom >= 1.5:
        return 10
    if zoom >= 0.75:
        return 20
    if zoom >= 0.35:
        return 50
    return 100


def display_contour_interval_m(heightmap, requested_interval_m, max_levels=24):
    min_elevation = float(heightmap.get("min_elevation_m", 0.0) or 0.0)
    max_elevation = float(heightmap.get("max_elevation_m", 0.0) or 0.0)
    requested = max(1, int(requested_interval_m or 1))
    elevation_range = max(0.0, max_elevation - min_elevation)
    if elevation_range <= 0:
        return requested

    minimum_interval = elevation_range / max(1, int(max_levels or 1))
    if requested >= minimum_interval:
        return requested

    magnitude = 10 ** math.floor(math.log10(max(1.0, minimum_interval)))
    for multiplier in (1, 2, 5, 10):
        candidate = int(multiplier * magnitude)
        if candidate >= minimum_interval:
            return max(requested, candidate)
    return max(requested, int(10 * magnitude))


def _wrapped_distance(a, b):
    delta = abs(a - b)
    return min(delta, 1.0 - delta)


def _wrapped_delta(a, b):
    delta = float(a) - float(b)
    if delta > 0.5:
        delta -= 1.0
    elif delta < -0.5:
        delta += 1.0
    return delta


def _ridge_belt(nx, ny, phase, latitude_center, amplitude, width):
    center = latitude_center + amplitude * math.sin(math.tau * (nx + phase))
    center += amplitude * 0.45 * math.sin(math.tau * (nx * 2.1 - phase))
    distance = abs(ny - center)
    return math.exp(-((distance / max(0.001, width)) ** 2))


def _crater_signal(nx, ny, map_seed=""):
    centers = [
        (seed_range(map_seed, "basin_0_x", 0.05, 0.28), seed_range(map_seed, "basin_0_y", 0.22, 0.45), seed_range(map_seed, "basin_0_r", 0.035, 0.075)),
        (seed_range(map_seed, "basin_1_x", 0.28, 0.48), seed_range(map_seed, "basin_1_y", 0.52, 0.74), seed_range(map_seed, "basin_1_r", 0.030, 0.065)),
        (seed_range(map_seed, "basin_2_x", 0.52, 0.70), seed_range(map_seed, "basin_2_y", 0.30, 0.55), seed_range(map_seed, "basin_2_r", 0.035, 0.070)),
        (seed_range(map_seed, "basin_3_x", 0.70, 0.86), seed_range(map_seed, "basin_3_y", 0.62, 0.82), seed_range(map_seed, "basin_3_r", 0.030, 0.065)),
        (seed_range(map_seed, "basin_4_x", 0.82, 0.96), seed_range(map_seed, "basin_4_y", 0.15, 0.35), seed_range(map_seed, "basin_4_r", 0.025, 0.055)),
    ]
    value = 0.0
    for cx, cy, radius in centers:
        distance = math.hypot(_wrapped_distance(nx, cx), ny - cy)
        rim = math.exp(-(((distance - radius) / (radius * 0.18)) ** 2))
        basin = math.exp(-((distance / (radius * 0.72)) ** 2))
        value += rim * 0.28 - basin * 0.38
    return _clamp(value, -0.8, 0.8)


def _nearest_plate(nx, ny, plates):
    best = None
    best_distance = 999.0
    for plate in plates:
        distance = math.hypot(
            _wrapped_delta(nx, float(plate.get("center_x", 0.0) or 0.0)),
            ny - float(plate.get("center_y", 0.0) or 0.0),
        )
        if distance < best_distance:
            best_distance = distance
            best = plate
    return best


def _plate_base_height_m(plate):
    if not isinstance(plate, dict):
        return 0.0
    plate_type = plate.get("plate_type")
    continentality = float(plate.get("continentality", 0.5) or 0.5)
    if plate_type == "continental":
        return 680.0 + continentality * 420.0
    if plate_type == "mixed":
        return -750.0 + continentality * 1650.0
    return -4100.0 + continentality * 850.0


def _blended_plate_base_height_m(nx, ny, plates):
    weighted_height = 0.0
    total_weight = 0.0
    nearest = None
    nearest_distance = 999.0
    for plate in plates:
        distance = math.hypot(
            _wrapped_delta(nx, float(plate.get("center_x", 0.0) or 0.0)),
            ny - float(plate.get("center_y", 0.0) or 0.0),
        )
        if distance < nearest_distance:
            nearest_distance = distance
            nearest = plate
        weight = 1.0 / ((distance + 0.08) ** 2.15)
        weighted_height += _plate_base_height_m(plate) * weight
        total_weight += weight
    if total_weight <= 0:
        return 0.0, nearest
    return weighted_height / total_weight, nearest


def _point_segment_distance(px, py, x1, y1, x2, y2):
    dx = x2 - x1
    dy = y2 - y1
    length_sq = dx * dx + dy * dy
    if length_sq <= 1e-12:
        return math.hypot(px - x1, py - y1)
    t = _clamp(((px - x1) * dx + (py - y1) * dy) / length_sq, 0.0, 1.0)
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def _wrapped_point_segment_distance(px, py, x1, y1, x2, y2):
    if x2 - x1 > 0.5:
        x2 -= 1.0
    elif x2 - x1 < -0.5:
        x2 += 1.0

    best = 999.0
    for point_offset in (-1.0, 0.0, 1.0):
        shifted_px = px + point_offset
        for segment_offset in (-1.0, 0.0, 1.0):
            best = min(
                best,
                _point_segment_distance(
                    shifted_px,
                    py,
                    x1 + segment_offset,
                    y1,
                    x2 + segment_offset,
                    y2,
                ),
            )
    return best


def _boundary_kind_lookup(tectonic_model):
    lookup = {}
    for boundary in tectonic_model.get("boundaries") or []:
        pair = tuple(sorted((boundary.get("plate_a"), boundary.get("plate_b"))))
        lookup[pair] = boundary.get("kind", "passive")
    return lookup


def _tectonic_height_m(nx, ny, terrain, tectonic_model):
    plates = tectonic_model.get("plates") or []
    if not plates:
        return None
    base, plate = _blended_plate_base_height_m(nx, ny, plates)
    plate_type = plate.get("plate_type") if isinstance(plate, dict) else "mixed"

    longitude = nx * math.tau
    latitude = (ny - 0.5) * math.pi
    map_seed = str(tectonic_model.get("map_seed") or terrain.get("map_seed") or "")
    broad_relief = (
        360.0 * math.sin(longitude * seed_range(map_seed, "tectonic_broad_freq_a", 0.85, 1.45) + latitude * 0.75)
        + 220.0 * math.cos(longitude * seed_range(map_seed, "tectonic_broad_freq_b", 1.65, 2.55) - latitude)
        + 95.0 * math.sin(longitude * 4.1 + latitude * 1.7)
    )
    height = base + broad_relief

    effects = tectonic_model.get("surface_effects") if isinstance(tectonic_model.get("surface_effects"), dict) else {}
    uplift_gain = 0.7 + float(effects.get("orogenic_uplift", 0.0) or 0.0) * 0.9
    basin_gain = 0.65 + float(effects.get("ocean_basin_opening", 0.0) or 0.0) * 0.75
    erosion = float(effects.get("erosion_progress", 0.0) or 0.0)
    boundary_lookup = _boundary_kind_lookup(tectonic_model)

    for segment in (tectonic_model.get("boundary_segments") or []):
        distance = _wrapped_point_segment_distance(
            nx,
            ny,
            float(segment.get("x1", 0.0) or 0.0),
            float(segment.get("y1", 0.0) or 0.0),
            float(segment.get("x2", 0.0) or 0.0),
            float(segment.get("y2", 0.0) or 0.0),
        )
        if distance > 0.09:
            continue
        influence = math.exp(-((distance / 0.045) ** 2))
        influence = influence ** 1.18
        kind = boundary_lookup.get(tuple(sorted((segment.get("plate_a"), segment.get("plate_b")))), "passive")
        if kind == "collision":
            height += 4300.0 * uplift_gain * influence
        elif kind == "subduction":
            height += 3300.0 * uplift_gain * influence
            height -= 1800.0 * influence * (1.0 if plate_type == "oceanic" else 0.3)
        elif kind == "divergent":
            height -= 2100.0 * basin_gain * influence
        elif kind == "transform":
            height += 650.0 * influence

    if height > 1000.0:
        height *= 1.0 - min(0.34, erosion * 0.24)
    return height


def _crater_height_adjustment_m(nx, ny, crater_model):
    adjustment = 0.0
    for crater in crater_model.get("craters") or []:
        cx = float(crater.get("x", 0.0) or 0.0)
        cy = float(crater.get("y", 0.0) or 0.0)
        diameter_norm = max(0.004, float(crater.get("diameter_km", 1.0) or 1.0) / 8000.0)
        distance = math.hypot(_wrapped_distance(nx, cx), ny - cy)
        basin = math.exp(-((distance / max(0.001, diameter_norm * 0.5)) ** 2))
        rim = math.exp(-(((distance - diameter_norm * 0.5) / max(0.001, diameter_norm * 0.11)) ** 2))
        adjustment -= float(crater.get("depth_m", 0.0) or 0.0) * basin
        adjustment += float(crater.get("rim_height_m", 0.0) or 0.0) * rim
    return adjustment


def _wave_height(nx, ny, terrain, tectonic_model=None, crater_model=None, map_seed=""):
    heightfield = terrain.get("heightfield") if isinstance(terrain.get("heightfield"), dict) else {}
    tectonics = terrain.get("tectonics") if isinstance(terrain.get("tectonics"), dict) else {}
    cratering = terrain.get("cratering") if isinstance(terrain.get("cratering"), dict) else {}
    hydrology = terrain.get("hydrology") if isinstance(terrain.get("hydrology"), dict) else {}

    roughness = float(heightfield.get("roughness", 0.5) or 0.5)
    crater_gain = float(cratering.get("density", 0.0) or 0.0)
    water_smoothing = float(hydrology.get("target_ocean_fraction", 0.0) or 0.0) * 0.28

    longitude = nx * math.tau
    latitude = (ny - 0.5) * math.pi
    phase_a = seed_range(map_seed, "wave_phase_a", 0.0, math.tau)
    phase_b = seed_range(map_seed, "wave_phase_b", 0.0, math.tau)
    phase_c = seed_range(map_seed, "wave_phase_c", 0.0, math.tau)
    basin_a = seed_range(map_seed, "basin_freq_a", 0.75, 1.55)
    basin_b = seed_range(map_seed, "basin_freq_b", 1.25, 2.25)
    basin_c = seed_range(map_seed, "basin_freq_c", 2.35, 3.75)
    broad_basins = (
        0.16 * math.sin(longitude * basin_a + 0.7 * math.sin(latitude + phase_a))
        + 0.11 * math.cos(longitude * basin_b - latitude * 1.2 + phase_b)
        + 0.07 * math.sin(longitude * basin_c + latitude * 0.7 + phase_c)
    )
    lowland_bias = -0.12 - water_smoothing * 0.22
    value = lowland_bias + broad_basins * (0.7 + roughness * 0.35)

    tectonic_height = None
    if isinstance(tectonic_model, dict) and tectonic_model.get("status") == "tectonics_advanced":
        tectonic_height = _tectonic_height_m(nx, ny, terrain, tectonic_model)

    if tectonic_height is not None:
        min_elevation = float(heightfield.get("min_elevation_m", -5000.0) or -5000.0)
        max_elevation = float(heightfield.get("max_elevation_m", 6000.0) or 6000.0)
        span = max(1.0, max_elevation - min_elevation)
        tectonic_value = ((tectonic_height - min_elevation) / span) * 2.0 - 1.0
        value = tectonic_value * 0.78 + value * 0.22
    elif tectonics.get("enabled"):
        ridge_a = _ridge_belt(nx, ny, phase=seed_range(map_seed, "ridge_a_phase", 0.0, 1.0), latitude_center=seed_range(map_seed, "ridge_a_lat", 0.28, 0.48), amplitude=seed_range(map_seed, "ridge_a_amp", 0.05, 0.095), width=0.034)
        ridge_b = _ridge_belt(nx, ny, phase=seed_range(map_seed, "ridge_b_phase", 0.0, 1.0), latitude_center=seed_range(map_seed, "ridge_b_lat", 0.55, 0.75), amplitude=seed_range(map_seed, "ridge_b_amp", 0.045, 0.085), width=0.028)
        ridge_c = _ridge_belt(nx, ny, phase=seed_range(map_seed, "ridge_c_phase", 0.0, 1.0), latitude_center=seed_range(map_seed, "ridge_c_lat", 0.38, 0.62), amplitude=seed_range(map_seed, "ridge_c_amp", 0.03, 0.07), width=0.022)
        ridge_strength = max(ridge_a, ridge_b * 0.78, ridge_c * 0.55)
        trench_strength = max(
            _ridge_belt(nx, ny, phase=seed_range(map_seed, "trench_a_phase", 0.0, 1.0), latitude_center=seed_range(map_seed, "trench_a_lat", 0.25, 0.45), amplitude=0.07, width=0.018),
            _ridge_belt(nx, ny, phase=seed_range(map_seed, "trench_b_phase", 0.0, 1.0), latitude_center=seed_range(map_seed, "trench_b_lat", 0.58, 0.76), amplitude=0.055, width=0.016),
        )
        value += ridge_strength * (0.72 + roughness * 0.24)
        value -= trench_strength * 0.28
        value += math.sin(longitude * 9.0 + latitude * 2.4) * ridge_strength * 0.07
    else:
        shield_wave = math.sin(longitude * seed_range(map_seed, "shield_freq", 1.4, 2.7) - latitude + phase_a) * math.cos(latitude * 2.0 + phase_b)
        value += shield_wave * 0.12 * roughness

    if crater_gain > 0.12:
        value += _crater_signal(nx, ny, map_seed=map_seed) * crater_gain * 0.55
    if isinstance(crater_model, dict):
        min_elevation = float(heightfield.get("min_elevation_m", -5000.0) or -5000.0)
        max_elevation = float(heightfield.get("max_elevation_m", 5000.0) or 5000.0)
        span = max(1.0, max_elevation - min_elevation)
        value += (_crater_height_adjustment_m(nx, ny, crater_model) / span) * 2.0

    value *= 1.0 - water_smoothing * 0.25
    return _clamp(value, -1.0, 1.0)


def _smooth_height_rows(rows, passes=1, blend=0.35):
    smoothed = [list(row) for row in rows]
    for _index in range(max(0, int(passes or 0))):
        next_rows = []
        height = len(smoothed)
        width = len(smoothed[0]) if height else 0
        for row_index, row in enumerate(smoothed):
            next_row = []
            for col_index, value in enumerate(row):
                left = row[(col_index - 1) % width]
                right = row[(col_index + 1) % width]
                up = smoothed[max(0, row_index - 1)][col_index]
                down = smoothed[min(height - 1, row_index + 1)][col_index]
                neighbor_average = (left + right + up + down) / 4.0
                next_row.append(round(value * (1.0 - blend) + neighbor_average * blend, 1))
            if next_row:
                next_row[-1] = next_row[0]
            next_rows.append(next_row)
        smoothed = next_rows
    return smoothed


def _ice_score(nx, ny, elevation, min_elevation, max_elevation, map_seed=""):
    latitude_polarity = abs(ny - 0.5) * 2.0
    elevation_norm = (float(elevation) - float(min_elevation)) / max(1.0, float(max_elevation) - float(min_elevation))
    ridge_noise = (
        math.sin(nx * math.tau * seed_range(map_seed, "ice_freq_a", 1.2, 2.8) + seed_range(map_seed, "ice_phase_a", 0.0, math.tau))
        + math.cos((nx + ny) * math.tau * seed_range(map_seed, "ice_freq_b", 0.8, 1.9) + seed_range(map_seed, "ice_phase_b", 0.0, math.tau))
    ) * 0.08
    return latitude_polarity * 0.68 + elevation_norm * 0.22 + ridge_noise


def derive_heightmap_model(terrain, seed=None, physics=None, planet_id="", tectonic_model=None, crater_model=None):
    terrain = terrain if isinstance(terrain, dict) else {}
    heightfield = terrain.get("heightfield") if isinstance(terrain.get("heightfield"), dict) else {}
    canvas = terrain.get("map_canvas") if isinstance(terrain.get("map_canvas"), dict) else {}
    map_seed = terrain.get("map_seed") or resolved_map_seed(seed, planet_id=planet_id)
    simulated_age_myr = float(terrain.get("simulated_age_myr", 0.0) or 0.0)

    width_px = int(canvas.get("width_px", 2048) or 2048)
    height_px = int(canvas.get("height_px", 1024) or 1024)
    min_elevation = float(heightfield.get("min_elevation_m", -4000.0) or -4000.0)
    max_elevation = float(heightfield.get("max_elevation_m", 4000.0) or 4000.0)
    sea_level = heightfield.get("sea_level_m")
    hydrology = terrain.get("hydrology") if isinstance(terrain.get("hydrology"), dict) else {}
    try:
        target_ocean_fraction = _clamp(hydrology.get("target_ocean_fraction", 0.0), 0.0, 0.92)
    except (TypeError, ValueError):
        target_ocean_fraction = 0.0
    try:
        target_ice_fraction = _clamp(hydrology.get("target_ice_fraction", 0.0), 0.0, 0.86)
    except (TypeError, ValueError):
        target_ice_fraction = 0.0
    if sea_level is None and not hydrology.get("liquid_water_possible"):
        target_ocean_fraction = 0.0
    midpoint = (max_elevation + min_elevation) * 0.5
    half_range = max(1.0, (max_elevation - min_elevation) * 0.5)

    sample_width = 65
    sample_height = 33
    rows = []
    sample_values = []
    sample_positions = []
    for row in range(sample_height):
        ny = row / max(1, sample_height - 1)
        row_values = []
        for col in range(sample_width):
            nx = 0.0 if col == sample_width - 1 else col / max(1, sample_width - 1)
            normalized = _wave_height(nx, ny, terrain, tectonic_model=tectonic_model, crater_model=crater_model, map_seed=map_seed)
            elevation = midpoint + normalized * half_range
            elevation = round(_clamp(elevation, min_elevation, max_elevation), 1)
            row_values.append(elevation)
            sample_positions.append((col, row, nx, ny, elevation))
        if row_values:
            row_values[-1] = row_values[0]
        sample_values.extend(row_values)
        rows.append(row_values)

    if isinstance(tectonic_model, dict) and tectonic_model.get("status") == "tectonics_advanced":
        rows = _smooth_height_rows(rows, passes=2, blend=0.28)
        sample_values = [value for row in rows for value in row]
        sample_positions = [
            (
                col,
                row,
                0.0 if col == sample_width - 1 else col / max(1, sample_width - 1),
                row / max(1, sample_height - 1),
                rows[row][col],
            )
            for row in range(sample_height)
            for col in range(sample_width)
        ]
    if simulated_age_myr > 0.0:
        age_passes = min(5, max(1, int(simulated_age_myr // 25.0)))
        erosion_blend = min(0.34, 0.08 + simulated_age_myr / 1400.0)
        if target_ice_fraction > 0.0:
            erosion_blend += min(0.08, target_ice_fraction * 0.08)
        rows = _smooth_height_rows(rows, passes=age_passes, blend=erosion_blend)
        sample_values = [value for row in rows for value in row]
        sample_positions = [
            (
                col,
                row,
                0.0 if col == sample_width - 1 else col / max(1, sample_width - 1),
                row / max(1, sample_height - 1),
                rows[row][col],
            )
            for row in range(sample_height)
            for col in range(sample_width)
        ]

    sample_count = max(1, len(sample_values))
    if sea_level is None and target_ocean_fraction > 0.0 and sample_values:
        sorted_values = sorted(sample_values)
        index = max(0, min(len(sorted_values) - 1, int(round(target_ocean_fraction * (len(sorted_values) - 1)))))
        sea_level = sorted_values[index]
    broad_plain_fraction = sum(-2000.0 <= value <= 1000.0 for value in sample_values) / sample_count
    mountain_fraction = sum(value > 2000.0 for value in sample_values) / sample_count
    deep_basin_fraction = sum(value < -2000.0 for value in sample_values) / sample_count
    sea_level_value = None if sea_level is None else float(sea_level)
    ocean_fraction = 0.0 if sea_level_value is None else sum(value < sea_level_value for value in sample_values) / sample_count
    land_fraction = 1.0 - ocean_fraction
    ice_rows = [[False for _col in range(sample_width)] for _row in range(sample_height)]
    if target_ice_fraction > 0.0 and sample_positions:
        scored = [
            (
                _ice_score(nx, ny, elevation, min_elevation, max_elevation, map_seed=map_seed),
                col,
                row,
            )
            for col, row, nx, ny, elevation in sample_positions
        ]
        scored.sort(reverse=True)
        ice_count = int(round(target_ice_fraction * len(scored)))
        for _score, col, row in scored[:ice_count]:
            ice_rows[row][col] = True
        for row in range(sample_height):
            ice_rows[row][-1] = ice_rows[row][0]
    ice_count = sum(1 for row in ice_rows for value in row if value)
    ice_fraction = ice_count / sample_count

    return {
        "status": "heightmap_seeded",
        "planet_id": planet_id,
        "map_seed": map_seed,
        "projection": canvas.get("projection", "equirectangular"),
        "spherical_body": True,
        "wrap_x": True,
        "wrap_y": False,
        "edge_policy": "longitude_wrap_latitude_clamp",
        "width_px": width_px,
        "height_px": height_px,
        "vertical_datum": canvas.get("vertical_datum", "mean_radius"),
        "elevation_unit": "m",
        "min_elevation_m": round(min_elevation, 1),
        "max_elevation_m": round(max_elevation, 1),
        "sea_level_m": None if sea_level is None else round(float(sea_level), 1),
        "simulated_age_myr": round(simulated_age_myr, 1),
        "sample_grid": {
            "width": sample_width,
            "height": sample_height,
            "wrap_x": True,
            "wrap_y": False,
            "spacing_x_px": round(width_px / max(1, sample_width - 1), 4),
            "spacing_y_px": round(height_px / max(1, sample_height - 1), 4),
            "rows": rows,
        },
        "surface_masks": {
            "ice_rows": ice_rows,
            "ice_source": "frozen_water_inventory" if target_ice_fraction > 0.0 else None,
            "target_ice_fraction": round(target_ice_fraction, 3),
        },
        "hypsometry_summary": {
            "broad_plain_fraction": round(broad_plain_fraction, 3),
            "mountain_fraction_above_2000m": round(mountain_fraction, 3),
            "deep_basin_fraction_below_minus_2000m": round(deep_basin_fraction, 3),
            "land_fraction": round(land_fraction, 3),
            "ocean_fraction": round(ocean_fraction, 3),
            "ice_fraction": round(ice_fraction, 3),
        },
        "storage": {
            "kind": "chunked_heightfield_seed",
            "chunk_width_px": 256,
            "chunk_height_px": 256,
            "chunk_cols": math.ceil(width_px / 256),
            "chunk_rows": math.ceil(height_px / 256),
            "sample_format": "float_meters",
            "edge_policy": "longitude_wrap_latitude_clamp",
            "consumer_contract": "chunks are addressed by projection pixel bbox and may be resampled for bio-sim grids",
        },
        "source_models": {
            "tectonics": (tectonic_model or {}).get("status") if isinstance(tectonic_model, dict) else None,
            "craters": (crater_model or {}).get("status") if isinstance(crater_model, dict) else None,
        },
    }


def contour_levels_for_heightmap(heightmap, interval_m, max_levels=24):
    min_elevation = float(heightmap.get("min_elevation_m", 0.0) or 0.0)
    max_elevation = float(heightmap.get("max_elevation_m", 0.0) or 0.0)
    interval = display_contour_interval_m(heightmap, interval_m, max_levels=max_levels)
    center = heightmap.get("sea_level_m")
    if center is None:
        center = (min_elevation + max_elevation) * 0.5
    center = float(center or 0.0)
    possible_count = int((max_elevation - min_elevation) // interval) + 1
    if possible_count > max_levels:
        half_window = (max_levels // 2) * interval
        min_elevation = max(min_elevation, center - half_window)
        max_elevation = min(max_elevation, center + half_window)
    start = math.ceil(min_elevation / interval) * interval
    levels = []
    level = start
    while level <= max_elevation + interval * 0.1:
        levels.append(level)
        level += interval
        if len(levels) >= max_levels:
            break
    return levels
