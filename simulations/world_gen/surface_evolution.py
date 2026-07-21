"""Climate-coupled, scale-aware planetary surface evolution.

This is deliberately a *landscape evolution proxy*, not a claim to solve a
planet's billion-year geological history.  It couples the resolved climate and
drainage grids to the existing tectonic/impact heightfield with conservative,
bounded changes.  The process ordering follows the usual planetary surface
framework: tectonism and impacts create relief; water, ice, wind, weathering,
mass wasting, and deposition progressively redistribute it.
"""

import math


SURFACE_EVOLUTION_MODEL_VERSION = "climate-coupled-surface-evolution-v2"


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, float(value)))


def _grid(rows):
    if not isinstance(rows, list) or len(rows) < 2:
        return []
    width = min((len(row) for row in rows if isinstance(row, list)), default=0)
    if width < 2:
        return []
    return [[float(value or 0.0) for value in row[:width]] for row in rows]


def _sample(rows, x, y, default=0.0):
    if not rows or not rows[0]:
        return default
    y = min(len(rows) - 1, max(0, int(y)))
    x = min(len(rows[0]) - 1, max(0, int(x)))
    return float(rows[y][x] or default)


def _normalise(rows, *, log=False):
    values = [float(value or 0.0) for row in rows for value in row]
    if not values:
        return []
    if log:
        values = [math.log1p(max(0.0, value)) for value in values]
    low, high = min(values), max(values)
    span = max(1e-9, high - low)
    result = []
    for row in rows:
        result.append([
            _clamp(((math.log1p(max(0.0, float(value or 0.0))) if log else float(value or 0.0)) - low) / span)
            for value in row
        ])
    return result


def _gradient(rows, x, y, dx_m, dy_m, wrap_x):
    height, width = len(rows), len(rows[0])
    left = _sample(rows, (x - 1) % width if wrap_x else max(0, x - 1), y)
    right = _sample(rows, (x + 1) % width if wrap_x else min(width - 1, x + 1), y)
    up = _sample(rows, x, max(0, y - 1))
    down = _sample(rows, x, min(height - 1, y + 1))
    return math.hypot((right - left) / max(1.0, 2.0 * dx_m), (down - up) / max(1.0, 2.0 * dy_m))


def _neighbour_mean(rows, x, y, wrap_x):
    height, width = len(rows), len(rows[0])
    values = []
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            nx, ny = x + dx, y + dy
            if wrap_x:
                nx %= width
            if 0 <= nx < width and 0 <= ny < height:
                values.append(rows[ny][nx])
    return sum(values) / max(1, len(values))


def _river_grid_path(river, width, height):
    path = []
    # Drainage cells determine connectivity and discharge.  The smoothed
    # centerline adds floodplain-scale curvature while retaining exact source
    # and confluence endpoints; carving it lets the next drainage iteration
    # adopt that valley instead of preserving a ruler-straight D8 reach.
    for point in river.get("display_points") or river.get("points") or []:
        if not isinstance(point, dict):
            continue
        x = max(0, min(width - 1, int(round(float(point.get("x", 0.0) or 0.0) * max(1, width - 1)))))
        y = max(0, min(height - 1, int(round(float(point.get("y", 0.0) or 0.0) * max(1, height - 1)))))
        if not path or path[-1] != (x, y):
            path.append((x, y))
    return path


def _apply_channel_incision(rows, drainage, heightmap, active_water, declared_strength, wrap_x):
    """Carve routed channels into the DEM and return the incision-depth grid.

    Priority-flood drainage can legitimately cross a filled depression or a
    nearly level saddle.  A drawn polyline alone therefore need not coincide
    with a valley in the raw terrain.  This bounded stream-power pass lowers
    the routed cells, enforces a small downstream bed gradient, and feathers
    the incision into adjacent banks.  The next drainage solve then responds
    to those valleys instead of redrawing an unrelated network.
    """
    height, width = len(rows), len(rows[0])
    incision = [[0.0 for _x in range(width)] for _y in range(height)]
    if not active_water or not isinstance(drainage, dict):
        return [[value for value in row] for row in rows], incision
    rivers = [river for river in (drainage.get("rivers") or []) if isinstance(river, dict)]
    if not rivers:
        return [[value for value in row] for row in rows], incision

    relief_span = max(1.0, max(max(row) for row in rows) - min(min(row) for row in rows))
    spacing_x = float(heightmap.get("sample_spacing_x_m") or 0.0)
    spacing_y = float(heightmap.get("sample_spacing_y_m") or 0.0)
    if spacing_x <= 0.0:
        spacing_x = float(heightmap.get("circumference_m") or 40_030_000.0) / max(1, width - 1)
    if spacing_y <= 0.0:
        radius_m = float(heightmap.get("radius_m") or 6_371_000.0)
        spacing_y = math.pi * radius_m / max(1, height - 1)
    cell_spacing_m = max(1.0, math.sqrt(spacing_x * spacing_y))
    # Valley depth scales with represented cell size, but remains a small
    # fraction of total relief so a coarse planetary channel cannot excavate
    # a continent-scale trench in one feedback pass.
    maximum_depth_m = min(relief_span * 0.030, max(0.25, cell_spacing_m * 0.011))
    minimum_drop_m = min(maximum_depth_m * 0.08, max(0.02, cell_spacing_m * 0.000025))
    channel_floor = [[None for _x in range(width)] for _y in range(height)]

    # Large downstream segments establish trunk valleys first; tributaries
    # then meet an already incised confluence elevation.
    rivers.sort(
        key=lambda river: (
            int(river.get("stream_order", 1) or 1),
            float(river.get("flow", 0.0) or 0.0),
        ),
        reverse=True,
    )
    for river in rivers:
        path = _river_grid_path(river, width, height)
        if len(path) < 2:
            continue
        flow = _clamp(float(river.get("flow", 0.0) or 0.0))
        order = max(1, int(river.get("stream_order", 1) or 1))
        morphology = river.get("channel_morphology") if isinstance(river.get("channel_morphology"), dict) else {}
        channel_gradient = max(0.0, float(morphology.get("gradient_m_per_m", 0.0) or 0.0))
        confinement = _clamp(float(morphology.get("confinement_index", 0.0) or 0.0))
        slope_energy = _clamp(channel_gradient / 0.012)
        strength = _clamp((0.24 + 0.76 * math.sqrt(flow)) * (0.70 + min(4, order) * 0.09))
        incision_regime = 0.24 + slope_energy * 0.56 + confinement * 0.20
        target_depth = maximum_depth_m * declared_strength * strength * incision_regime
        previous_bed = None
        for index, (x, y) in enumerate(path):
            downstream_fraction = index / max(1, len(path) - 1)
            local_depth = target_depth * (0.58 + downstream_fraction * 0.42)
            bed = float(rows[y][x]) - local_depth
            existing_floor = channel_floor[y][x]
            if existing_floor is not None:
                bed = min(bed, existing_floor)
            if previous_bed is not None:
                bed = min(bed, previous_bed - minimum_drop_m)
            channel_floor[y][x] = bed if existing_floor is None else min(existing_floor, bed)
            previous_bed = channel_floor[y][x]

    carved = [[value for value in row] for row in rows]
    for y in range(height):
        for x in range(width):
            bed = channel_floor[y][x]
            if bed is None:
                continue
            depth = max(0.0, float(rows[y][x]) - bed)
            carved[y][x] = min(carved[y][x], bed)
            incision[y][x] = max(incision[y][x], depth)
            # A shallow shoulder gives contours a readable V-shaped ravine
            # rather than an invisible single-cell cut.
            # The strongest channel occupying this cell is not retained as a
            # separate grid, so local depth acts as a stable confinement
            # proxy: deeply incised reaches receive steeper shoulders while
            # lowland channels blend into broad, subtle floodplains.
            shoulder_strength = _clamp(depth / max(1e-9, maximum_depth_m))
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    nx, ny = x + dx, y + dy
                    if wrap_x:
                        nx %= width
                    if not (0 <= nx < width and 0 <= ny < height):
                        continue
                    if channel_floor[ny][nx] is not None:
                        continue
                    bank_factor = (
                        0.06 + shoulder_strength * 0.12
                        if dx == 0 or dy == 0
                        else 0.025 + shoulder_strength * 0.055
                    )
                    bank_depth = depth * bank_factor
                    carved[ny][nx] = min(carved[ny][nx], float(rows[ny][nx]) - bank_depth)
                    incision[ny][nx] = max(incision[ny][nx], bank_depth)
    return carved, incision


def _apply_crater_degradation(rows, erosion_rows, weathering_rows, glacial_rows, aeolian_rows, crater_model, radius_m, wrap_x):
    """Soften catalogued crater relief only where local surface processes act."""
    craters = crater_model.get("craters") if isinstance(crater_model, dict) else []
    if not craters:
        return rows, [[0.0 for _value in row] for row in rows]
    height, width = len(rows), len(rows[0])
    evolved = [[value for value in row] for row in rows]
    degradation = [[0.0 for _x in range(width)] for _y in range(height)]
    for crater in craters:
        if not isinstance(crater, dict):
            continue
        try:
            center_x = float(crater.get("x", 0.5) or 0.5) % 1.0
            center_y = _clamp(float(crater.get("y", 0.5) or 0.5))
            diameter_m = max(1_000.0, float(crater.get("diameter_km", 0.0) or 0.0) * 1_000.0)
        except (TypeError, ValueError):
            continue
        angular_radius = diameter_m * 0.5 / max(1.0, radius_m)
        radius_y = max(1, int(math.ceil(angular_radius / math.pi * (height - 1) * 1.55)))
        latitude = (0.5 - center_y) * math.pi
        radius_x = max(1, int(math.ceil(radius_y / max(0.10, math.cos(latitude)))))
        center_ix = int(round(center_x * (width - 1)))
        center_iy = int(round(center_y * (height - 1)))
        for y in range(max(0, center_iy - radius_y), min(height, center_iy + radius_y + 1)):
            ny = y / max(1, height - 1)
            for raw_x in range(center_ix - radius_x, center_ix + radius_x + 1):
                if not wrap_x and not 0 <= raw_x < width:
                    continue
                x = raw_x % width if wrap_x else raw_x
                nx = x / max(1, width - 1)
                delta_lon = abs(nx - center_x)
                delta_lon = min(delta_lon, 1.0 - delta_lon) if wrap_x else delta_lon
                angular_distance = math.hypot((ny - center_y) * math.pi, delta_lon * math.tau * max(0.10, math.cos(latitude)))
                normalized_distance = angular_distance / max(1e-8, angular_radius)
                if normalized_distance > 1.5:
                    continue
                local_process = _clamp(
                    erosion_rows[y][x] * 1.65
                    + weathering_rows[y][x] * 0.65
                    + glacial_rows[y][x] * 0.95
                    + aeolian_rows[y][x] * 0.42
                )
                rim_or_floor = max(
                    math.exp(-((normalized_distance - 1.0) / 0.32) ** 2),
                    0.46 * _clamp(1.0 - normalized_distance),
                )
                blend = _clamp(local_process * rim_or_floor * 0.42)
                if blend <= degradation[y][x]:
                    continue
                degradation[y][x] = blend
    for y in range(height):
        for x in range(width):
            blend = degradation[y][x]
            if blend:
                evolved[y][x] = evolved[y][x] * (1.0 - blend) + _neighbour_mean(rows, x, y, wrap_x) * blend
        if wrap_x:
            evolved[y][-1] = evolved[y][0]
    return evolved, degradation


def _surface_age_myr(planet, terrain):
    candidates = (
        planet.get("simulated_geology_age_myr"),
        terrain.get("simulated_age_myr"),
        (planet.get("planetary_evolution_model") or {}).get("surface_record_age_myr"),
        (planet.get("planetary_evolution_model") or {}).get("surface_age_myr"),
        4500.0,
    )
    for candidate in candidates:
        try:
            if candidate is not None and float(candidate) > 0.0:
                return float(candidate)
        except (TypeError, ValueError):
            pass
    return 4500.0


def derive_surface_evolution_model(planet, terrain, heightmap, water_cycle, atmosphere=None):
    """Return a conservative evolved heightmap plus interpretable process grids.

    The water-cycle grid is the source of temperature, rainfall, runoff and
    snow.  Flow accumulation is supplied by the existing priority-flood
    drainage solver.  On dry or airless planets the model intentionally makes
    only weak aeolian/impact-gardening adjustments, preserving their cratered
    character.
    """
    planet = planet if isinstance(planet, dict) else {}
    terrain = terrain if isinstance(terrain, dict) else {}
    heightmap = heightmap if isinstance(heightmap, dict) else {}
    water_cycle = water_cycle if isinstance(water_cycle, dict) else {}
    atmosphere = atmosphere if isinstance(atmosphere, dict) else {}
    original_rows = _grid(((heightmap.get("sample_grid") or {}).get("rows")))
    climate = water_cycle.get("climate_grid") if isinstance(water_cycle.get("climate_grid"), dict) else {}
    if not original_rows or not climate:
        return {
            "status": "unavailable",
            "model_version": SURFACE_EVOLUTION_MODEL_VERSION,
            "reason": "heightmap_or_climate_grid_missing",
            "heightmap": heightmap,
        }

    height, width = len(original_rows), len(original_rows[0])
    temperature = _grid(climate.get("temperature_rows_k"))
    precipitation = _grid(climate.get("annual_precipitation_rows_mm"))
    runoff = _grid(climate.get("annual_runoff_rows_mm"))
    snow = _grid(climate.get("seasonal_snow_fraction_rows"))
    if not temperature or not precipitation or not runoff:
        return {
            "status": "unavailable",
            "model_version": SURFACE_EVOLUTION_MODEL_VERSION,
            "reason": "climate_forcing_missing",
            "heightmap": heightmap,
        }

    drainage = water_cycle.get("drainage_network_model") if isinstance(water_cycle.get("drainage_network_model"), dict) else {}
    accumulation = _grid(drainage.get("flow_accumulation_rows"))
    if not accumulation:
        accumulation = runoff
    accumulation_norm = _normalise(accumulation, log=True)
    sea_level = heightmap.get("sea_level_m")
    sea_level = None if sea_level is None else float(sea_level or 0.0)
    min_elevation = min(min(row) for row in original_rows)
    max_elevation = max(max(row) for row in original_rows)
    relief_span = max(1.0, max_elevation - min_elevation)
    radius_m = float(heightmap.get("radius_m") or ((terrain.get("map_canvas") or {}).get("radius_m")) or 6_371_000.0)
    circumference_m = float(heightmap.get("circumference_m") or (math.tau * radius_m))
    dy_m = math.pi * radius_m / max(1, height - 1)
    wrap_x = bool(heightmap.get("wrap_x", True))
    pressure_bar = float(
        atmosphere.get(
            "surface_pressure_bar",
            atmosphere.get("pressure_bar", atmosphere.get("pressure_estimate_bar", 0.0)),
        )
        or 0.0
    )
    liquid_water = bool(water_cycle.get("liquid_water_possible"))
    hydrology_enabled = bool(water_cycle.get("hydrology_enabled"))
    erosion_cfg = terrain.get("erosion") if isinstance(terrain.get("erosion"), dict) else {}
    declared_strength = _clamp(float(erosion_cfg.get("strength", 0.35) or 0.35))
    declared_processes = set(erosion_cfg.get("processes") or [])
    surface_age_myr = _surface_age_myr(planet, terrain)
    # This is the representative interval that reaches steady-state at the map
    # scale.  It prevents a 4.5 Gyr planet from being numerically flattened.
    equilibration_myr = min(180.0, max(8.0, surface_age_myr * 0.045))
    pressure_weathering = _clamp(math.log1p(max(0.0, pressure_bar) * 12.0) / math.log(13.0))
    active_water = 1.0 if liquid_water and hydrology_enabled else 0.0

    fluvial_rows, weathering_rows, aeolian_rows, glacial_rows = [], [], [], []
    deposition_rows, erosion_rows, age_rows = [], [], []
    for y in range(height):
        fluvial_row, weathering_row, aeolian_row, glacial_row = [], [], [], []
        deposition_row, erosion_row, age_row = [], [], []
        latitude = abs((y / max(1, height - 1)) - 0.5) * math.pi
        dx_m = max(1.0, circumference_m * max(0.08, math.cos(latitude)) / max(1, width - 1))
        for x in range(width):
            elevation = original_rows[y][x]
            ocean = sea_level is not None and elevation < sea_level
            temp_k = _sample(temperature, x, y, 250.0)
            precip_mm = max(0.0, _sample(precipitation, x, y))
            runoff_mm = max(0.0, _sample(runoff, x, y))
            snow_fraction = _clamp(_sample(snow, x, y)) if snow else 0.0
            slope = _gradient(original_rows, x, y, dx_m, dy_m, wrap_x)
            # The global sample grid averages over tens to hundreds of
            # kilometres.  A 0.6% gradient is already a strong resolved
            # mountain-front/channel gradient at that scale; using a
            # hand-sample (35 mm/m) threshold would silently turn off rivers.
            slope_index = _clamp(slope / 0.006)
            flow_index = _sample(accumulation_norm, x, y)
            humidity = _clamp(precip_mm / 1800.0)
            aridity = _clamp(1.0 - precip_mm / 650.0)
            temperate_weathering = math.exp(-((temp_k - 294.0) / 36.0) ** 2)
            # Stream-power style proxy: contributing area and local gradient
            # set channel incision; no liquid water means no fluvial term.
            fluvial = active_water * (runoff_mm / (runoff_mm + 240.0)) ** 0.7 * flow_index ** 0.52 * slope_index ** 0.88
            weathering = active_water * pressure_weathering * humidity * temperate_weathering * (0.35 + slope_index * 0.45)
            glacial = active_water * snow_fraction * _clamp((273.15 - temp_k) / 28.0) * (0.25 + slope_index * 0.75)
            # Wind transport remains possible in a thin atmosphere, but is
            # suppressed for a true exosphere and for wet/ice-covered ground.
            wind_density = _clamp(math.sqrt(max(0.0, pressure_bar)) / math.sqrt(0.12))
            aeolian = wind_density * aridity * _clamp((temp_k - 150.0) / 150.0) * (0.18 + slope_index * 0.42) * (1.0 - snow_fraction * 0.8)
            if ocean:
                fluvial *= 0.08
                weathering *= 0.12
                aeolian = 0.0
                glacial *= 0.35
            erosion = _clamp(
                fluvial * 0.74 + weathering * 0.20 + glacial * 0.44 + aeolian * 0.22,
            ) * declared_strength
            basin = _clamp(1.0 - slope_index * 1.45)
            deposition = _clamp((fluvial * 0.68 + weathering * 0.22 + glacial * 0.18 + aeolian * 0.30) * basin)
            # Fresh terrain is associated with active erosion/deposition; old,
            # quiet terrain retains a high relative surface age.
            resurfacing = _clamp(0.18 if "volcanic" in declared_processes else 0.0)
            relative_age = _clamp(1.0 - erosion * 0.73 - deposition * 0.34 - resurfacing)
            fluvial_row.append(round(fluvial, 5))
            weathering_row.append(round(weathering, 5))
            aeolian_row.append(round(aeolian, 5))
            glacial_row.append(round(glacial, 5))
            deposition_row.append(round(deposition, 5))
            erosion_row.append(round(erosion, 5))
            age_row.append(round(relative_age, 5))
        fluvial_rows.append(fluvial_row)
        weathering_rows.append(weathering_row)
        aeolian_rows.append(aeolian_row)
        glacial_rows.append(glacial_row)
        deposition_rows.append(deposition_row)
        erosion_rows.append(erosion_row)
        age_rows.append(age_row)

    # Move only a restrained fraction of local relief in this pass.  Hillslope
    # relaxation is applied separately, keeping channels from becoming a
    # salt-and-pepper heightfield at global resolution.
    process_amplitude_m = relief_span * (0.012 + 0.020 * active_water) * declared_strength
    evolved_rows = [[value for value in row] for row in original_rows]
    for y in range(height):
        for x in range(width):
            ocean = sea_level is not None and original_rows[y][x] < sea_level
            erosion = erosion_rows[y][x]
            deposition = deposition_rows[y][x]
            delta_m = process_amplitude_m * (deposition * 0.56 - erosion)
            if ocean:
                delta_m *= 0.20
            evolved_rows[y][x] = original_rows[y][x] + delta_m
    diffusion_strength = (0.008 + 0.024 * declared_strength) * (0.35 + pressure_weathering * 0.65)
    if not active_water:
        diffusion_strength *= 0.22
    smoothed = [[value for value in row] for row in evolved_rows]
    for y in range(height):
        for x in range(width):
            slope_activity = erosion_rows[y][x] + glacial_rows[y][x] * 0.5 + aeolian_rows[y][x] * 0.25
            blend = _clamp(diffusion_strength * slope_activity, 0.0, 0.09)
            if blend:
                mean = _neighbour_mean(evolved_rows, x, y, wrap_x)
                smoothed[y][x] = evolved_rows[y][x] * (1.0 - blend) + mean * blend
    for y in range(height):
        if wrap_x:
            smoothed[y][-1] = smoothed[y][0]
    smoothed, crater_degradation_rows = _apply_crater_degradation(
        smoothed,
        erosion_rows,
        weathering_rows,
        glacial_rows,
        aeolian_rows,
        planet.get("crater_model"),
        radius_m,
        wrap_x,
    )
    smoothed, channel_incision_rows = _apply_channel_incision(
        smoothed,
        drainage,
        heightmap,
        active_water,
        declared_strength,
        wrap_x,
    )

    changed_heightmap = dict(heightmap)
    sample_grid = dict(heightmap.get("sample_grid") or {})
    sample_grid["rows"] = [[round(value, 2) for value in row] for row in smoothed]
    changed_heightmap["sample_grid"] = sample_grid
    changed_heightmap["min_elevation_m"] = round(min(min(row) for row in smoothed), 1)
    changed_heightmap["max_elevation_m"] = round(max(max(row) for row in smoothed), 1)
    geology = dict(heightmap.get("geology_model") or {})
    geology.update({
        "surface_evolution_model_version": SURFACE_EVOLUTION_MODEL_VERSION,
        "surface_evolution_processes": ["routed_channel_incision", "fluvial_incision", "chemical_weathering", "hillslope_diffusion", "sediment_deposition", "aeolian_transport", "glacial_erosion"],
        "climate_coupled": True,
        "drainage_feedback": "routed_channels_incise_dem_before_next_drainage_solve",
    })
    changed_heightmap["geology_model"] = geology

    process_means = {
        "fluvial": sum(sum(row) for row in fluvial_rows) / (width * height),
        "weathering": sum(sum(row) for row in weathering_rows) / (width * height),
        "aeolian": sum(sum(row) for row in aeolian_rows) / (width * height),
        "glacial": sum(sum(row) for row in glacial_rows) / (width * height),
        "deposition": sum(sum(row) for row in deposition_rows) / (width * height),
    }
    process_means["erosion"] = sum(sum(row) for row in erosion_rows) / (width * height)
    process_means["crater_degradation"] = sum(sum(row) for row in crater_degradation_rows) / (width * height)
    channel_cell_count = sum(value > 0.0 for row in channel_incision_rows for value in row)
    maximum_channel_incision_m = max((value for row in channel_incision_rows for value in row), default=0.0)
    eroded_index = sum(sum(row) for row in erosion_rows)
    deposited_index = sum(sum(row) for row in deposition_rows) * 0.56
    marine_delivery_index = max(0.0, eroded_index - deposited_index)
    dominant_process = max(process_means, key=process_means.get)
    return {
        "status": "surface_evolution_seeded",
        "model_version": SURFACE_EVOLUTION_MODEL_VERSION,
        "coupling": "one_climate_to_landscape_feedback_iteration",
        "surface_age_myr": round(surface_age_myr, 1),
        "equilibration_interval_myr": round(equilibration_myr, 1),
        "liquid_water_enabled": active_water > 0.0,
        "surface_pressure_bar": round(pressure_bar, 5),
        "dominant_process": dominant_process,
        "process_means": {key: round(value, 4) for key, value in process_means.items()},
        "sediment_budget": {
            "model": "conservative_hillslope_channel_margin_budget_v1",
            "eroded_sediment_index": round(eroded_index, 3),
            "terrestrial_deposition_index": round(deposited_index, 3),
            "marine_delivery_index": round(marine_delivery_index, 3),
            "mass_partition_fraction": {
                "terrestrial": round(deposited_index / max(1e-9, eroded_index), 3),
                "marine": round(marine_delivery_index / max(1e-9, eroded_index), 3),
            },
        },
        "process_grid": {
            "width": width,
            "height": height,
            "fluvial_incision_rows": fluvial_rows,
            "chemical_weathering_rows": weathering_rows,
            "aeolian_transport_rows": aeolian_rows,
            "glacial_erosion_rows": glacial_rows,
            "erosion_potential_rows": erosion_rows,
            "sediment_deposition_rows": deposition_rows,
            "relative_surface_age_rows": age_rows,
            "crater_degradation_rows": [[round(value, 5) for value in row] for row in crater_degradation_rows],
            "channel_incision_rows_m": [[round(value, 3) for value in row] for row in channel_incision_rows],
        },
        "channel_incision": {
            "status": "routed_channels_incised" if channel_cell_count else "inactive",
            "channel_and_bank_cell_count": channel_cell_count,
            "maximum_incision_m": round(maximum_channel_incision_m, 3),
            "downstream_gradient_enforced": bool(channel_cell_count),
        },
        "heightmap": changed_heightmap,
    }
