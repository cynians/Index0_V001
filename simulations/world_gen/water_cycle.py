import math
from collections import deque

from simulations.world_gen.map_seed import resolved_map_seed, seed_range


WATER_CYCLE_MODEL_VERSION = "water-cycle-v1"

CLIMATE_ZONES = {
    "polar_ice": {"label": "Polar Ice", "color": [202, 224, 232]},
    "cold_steppe": {"label": "Cold Steppe", "color": [146, 158, 132]},
    "temperate_wet": {"label": "Temperate Wet", "color": [82, 142, 104]},
    "temperate_dry": {"label": "Temperate Dry", "color": [172, 156, 104]},
    "tropical_wet": {"label": "Tropical Wet", "color": [48, 130, 88]},
    "tropical_dry": {"label": "Tropical Dry", "color": [184, 146, 78]},
    "arid": {"label": "Arid", "color": [196, 176, 118]},
    "highland": {"label": "Highland", "color": [138, 128, 118]},
    "ocean": {"label": "Ocean", "color": [50, 92, 132]},
}


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, float(value)))


def _rows_from_heightmap(heightmap):
    grid = heightmap.get("sample_grid") if isinstance(heightmap, dict) else {}
    rows = grid.get("rows") if isinstance(grid, dict) else []
    if not rows or len(rows) < 2 or len(rows[0]) < 2:
        return []
    width = min(len(row) for row in rows)
    return [list(row[:width]) for row in rows]


def _wave_noise(map_seed, key, nx, ny):
    freq_a = seed_range(map_seed, f"{key}:freq_a", 1.1, 4.2)
    freq_b = seed_range(map_seed, f"{key}:freq_b", 2.0, 7.8)
    phase_a = seed_range(map_seed, f"{key}:phase_a", 0.0, math.tau)
    phase_b = seed_range(map_seed, f"{key}:phase_b", 0.0, math.tau)
    signal = (
        math.sin(nx * math.tau * freq_a + ny * 3.1 + phase_a)
        + math.cos((nx * 0.6 + ny) * math.tau * freq_b + phase_b)
    ) * 0.5
    return _clamp((signal + 1.0) * 0.5)


def _nearest_ocean_distance(ocean_mask, x, y):
    if not ocean_mask:
        return 1.0
    height = len(ocean_mask)
    width = len(ocean_mask[0])
    if ocean_mask[y][x]:
        return 0.0
    best = width + height
    for oy, row in enumerate(ocean_mask):
        for ox, is_ocean in enumerate(row):
            if not is_ocean:
                continue
            dx = min(abs(x - ox), width - abs(x - ox))
            dy = abs(y - oy)
            best = min(best, dx + dy)
    return _clamp(best / max(1.0, (width + height) * 0.32))


def _shore_distance_rows(ocean_mask):
    if not ocean_mask:
        return []
    height = len(ocean_mask)
    width = len(ocean_mask[0]) if height else 0
    if width <= 0:
        return []

    max_steps = max(1.0, (width + height) * 0.32)
    distances = [[None for _x in range(width)] for _y in range(height)]
    queue = deque()
    for y, row in enumerate(ocean_mask):
        for x, is_ocean in enumerate(row[:width]):
            if is_ocean:
                distances[y][x] = 0
                queue.append((x, y))

    if not queue:
        return [[1.0 for _x in range(width)] for _y in range(height)]

    while queue:
        x, y = queue.popleft()
        next_distance = distances[y][x] + 1
        for nx, ny in (((x - 1) % width, y), ((x + 1) % width, y), (x, y - 1), (x, y + 1)):
            if not 0 <= ny < height:
                continue
            if distances[ny][nx] is not None and distances[ny][nx] <= next_distance:
                continue
            distances[ny][nx] = next_distance
            queue.append((nx, ny))

    return [
        [_clamp((cell if cell is not None else max_steps) / max_steps) for cell in row]
        for row in distances
    ]


def _climate_texture(map_seed, key, nx, ny):
    phase_a = seed_range(map_seed, f"{key}:phase_a", 0.0, math.tau)
    phase_b = seed_range(map_seed, f"{key}:phase_b", 0.0, math.tau)
    phase_c = seed_range(map_seed, f"{key}:phase_c", 0.0, math.tau)
    value = (
        math.sin((nx * 11.0 + ny * 3.2) * math.tau + phase_a) * 0.46
        + math.cos((nx * 5.4 - ny * 8.1) * math.tau + phase_b) * 0.34
        + math.sin((nx + ny * 0.55) * math.tau * 17.0 + phase_c) * 0.20
    )
    return max(-1.0, min(1.0, value))


def _elevation_value(rows, x, y):
    height = len(rows)
    width = len(rows[0]) if height else 0
    if height <= 0 or width <= 0:
        return 0.0
    return float(rows[max(0, min(height - 1, y))][x % width] or 0.0)


def _terrain_metrics(rows, x, y, span):
    span = max(1.0, float(span or 1.0))
    center = _elevation_value(rows, x, y)
    left = _elevation_value(rows, x - 1, y)
    right = _elevation_value(rows, x + 1, y)
    up = _elevation_value(rows, x, y - 1)
    down = _elevation_value(rows, x, y + 1)
    gradient_x = (right - left) / (2.0 * span)
    gradient_y = (down - up) / (2.0 * span)
    neighbor_values = [left, right, up, down]
    roughness = sum(abs(value - center) for value in neighbor_values) / (len(neighbor_values) * span)
    slope = min(1.0, math.hypot(gradient_x, gradient_y) * 5.0)
    return {
        "gradient_x": gradient_x,
        "gradient_y": gradient_y,
        "slope": slope,
        "roughness": min(1.0, roughness * 6.0),
    }


def _prevailing_wind_vector(ny, map_seed):
    latitude = (0.5 - float(ny)) * 2.0
    abs_lat = abs(latitude)
    hemisphere = -1.0 if latitude < 0 else 1.0
    seasonal_tilt = seed_range(map_seed, "wind:seasonal_tilt", -0.16, 0.16)
    if abs_lat < 0.28:
        wind_x = -0.82
        wind_y = -0.24 * hemisphere
    elif abs_lat < 0.68:
        wind_x = 0.92
        wind_y = 0.12 * hemisphere
    else:
        wind_x = -0.66
        wind_y = 0.18 * hemisphere
    wind_y += seasonal_tilt
    length = math.hypot(wind_x, wind_y) or 1.0
    return wind_x / length, wind_y / length


def _classify_climate(temperature_k, wetness, elevation_norm, is_ocean, slope=0.0, roughness=0.0):
    if is_ocean:
        return "ocean"
    highland_score = elevation_norm * 0.82 + slope * 0.12 + roughness * 0.06
    if highland_score > 0.82 and elevation_norm > 0.68:
        return "highland"
    if temperature_k < 255.0:
        return "polar_ice"
    if wetness < 0.18:
        return "arid"
    if temperature_k < 273.0:
        return "cold_steppe"
    if temperature_k >= 296.0:
        return "tropical_wet" if wetness >= 0.52 else "tropical_dry"
    return "temperate_wet" if wetness >= 0.42 else "temperate_dry"


def _neighbor_points(width, height, x, y):
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            nx = (x + dx) % width
            ny = y + dy
            if 0 <= ny < height:
                yield nx, ny


def _planet_circumference_m(heightmap):
    try:
        circumference = float(heightmap.get("circumference_m") or 0.0)
    except (TypeError, ValueError):
        circumference = 0.0
    if circumference > 0.0:
        return circumference

    try:
        radius_m = float(heightmap.get("radius_m") or 0.0)
    except (TypeError, ValueError):
        radius_m = 0.0
    if radius_m > 0.0:
        return 2.0 * math.pi * radius_m

    try:
        meters_per_px = float(heightmap.get("equator_resolution_m_per_px") or 0.0)
        width_px = float(heightmap.get("width_px") or 0.0)
    except (TypeError, ValueError):
        meters_per_px = 0.0
        width_px = 0.0
    if meters_per_px > 0.0 and width_px > 0.0:
        return meters_per_px * width_px

    return 2.0 * math.pi * 6_371_000.0


def _path_length_m(points, circumference_m):
    if len(points) < 2:
        return 0.0
    circumference_m = max(1.0, float(circumference_m or 1.0))
    meridian_span_m = circumference_m * 0.5
    total = 0.0
    previous = points[0]
    for current in points[1:]:
        x0 = float(previous.get("x", 0.0) or 0.0)
        y0 = float(previous.get("y", 0.0) or 0.0)
        x1 = float(current.get("x", 0.0) or 0.0)
        y1 = float(current.get("y", 0.0) or 0.0)
        dx_norm = min(abs(x1 - x0), 1.0 - abs(x1 - x0))
        dy_norm = abs(y1 - y0)
        mid_y = (y0 + y1) * 0.5
        latitude = (0.5 - mid_y) * math.pi
        dx_m = dx_norm * circumference_m * max(0.06, math.cos(latitude))
        dy_m = dy_norm * meridian_span_m
        total += math.hypot(dx_m, dy_m)
        previous = current
    return total


def _river_widths_m(flow, length_m, target_ocean):
    flow = _clamp(flow, 0.0, 1.0)
    length_factor = _clamp(float(length_m or 0.0) / 2_500_000.0, 0.0, 1.0)
    ocean_factor = _clamp(target_ocean, 0.0, 1.0)
    average_width = 18.0 + (flow ** 1.25) * 620.0 + length_factor * 220.0 + ocean_factor * 90.0
    mouth_width = average_width * (1.8 + flow * 1.9 + length_factor * 1.2)
    return round(average_width, 1), round(mouth_width, 1)


def _trace_river(rows, ocean_mask, source, sea_level):
    height = len(rows)
    width = len(rows[0])
    x, y = source
    points = []
    seen = set()
    source_elevation = float(rows[y][x] or 0.0)
    mouth = "basin"
    for _step in range(width + height):
        if (x, y) in seen:
            break
        seen.add((x, y))
        points.append({
            "x": round(x / max(1, width - 1), 4),
            "y": round(y / max(1, height - 1), 4),
        })
        if ocean_mask[y][x] or (sea_level is not None and rows[y][x] <= sea_level):
            mouth = "ocean"
            break
        current = float(rows[y][x] or 0.0)
        next_point = None
        next_height = current
        for nx, ny in _neighbor_points(width, height, x, y):
            candidate_height = float(rows[ny][nx] or 0.0)
            if candidate_height < next_height:
                next_height = candidate_height
                next_point = (nx, ny)
        if next_point is None:
            break
        x, y = next_point
    if len(points) < 3:
        return None
    return {
        "points": points,
        "source_elevation_m": round(source_elevation, 1),
        "mouth": mouth,
        "flow": round(_clamp((source_elevation - float(rows[y][x] or 0.0)) / 9000.0, 0.08, 1.0), 3),
    }


def _select_river_sources(rows, ocean_mask, climate_rows, sea_level, max_rivers, shore_distances=None):
    height = len(rows)
    width = len(rows[0])
    elevations = [float(value or 0.0) for row in rows for value in row]
    min_elevation = min(elevations)
    max_elevation = max(elevations)
    span = max(1.0, max_elevation - min_elevation)
    candidates = []
    for y in range(1, max(1, height - 1)):
        for x in range(width):
            elevation = float(rows[y][x] or 0.0)
            if sea_level is not None and elevation <= sea_level:
                continue
            if ocean_mask[y][x]:
                continue
            climate = climate_rows[y][x]
            wet_bonus = 0.28 if climate in {"temperate_wet", "tropical_wet", "highland"} else 0.0
            shore_distance = (
                shore_distances[y][x]
                if shore_distances and y < len(shore_distances) and x < len(shore_distances[y])
                else _nearest_ocean_distance(ocean_mask, x, y)
            )
            shore_bonus = 0.16 * (1.0 - shore_distance)
            score = _clamp((elevation - min_elevation) / span) + wet_bonus + shore_bonus
            if score >= 0.58:
                candidates.append((score, x, y))
    candidates.sort(reverse=True)
    selected = []
    min_spacing = max(2, min(width, height) // 6)
    for score, x, y in candidates:
        if any(min(abs(x - sx), width - abs(x - sx)) + abs(y - sy) < min_spacing for sx, sy in selected):
            continue
        selected.append((x, y))
        if len(selected) >= max_rivers:
            break
    return selected


def derive_water_cycle_model(terrain, heightmap, atmosphere=None, seed=None, planet_id=""):
    terrain = terrain if isinstance(terrain, dict) else {}
    heightmap = heightmap if isinstance(heightmap, dict) else {}
    atmosphere = atmosphere if isinstance(atmosphere, dict) else {}
    rows = _rows_from_heightmap(heightmap)
    if not rows:
        return {
            "status": "unavailable",
            "model_version": WATER_CYCLE_MODEL_VERSION,
            "reason": "heightmap_missing",
            "climate_zones": [],
            "rivers": [],
        }

    map_seed = str(
        heightmap.get("map_seed")
        or terrain.get("map_seed")
        or resolved_map_seed(seed or {}, planet_id=planet_id)
    )
    sea_level = heightmap.get("sea_level_m")
    sea_level = None if sea_level is None else float(sea_level or 0.0)
    hydrology = terrain.get("hydrology") if isinstance(terrain.get("hydrology"), dict) else {}
    surface_temp_k = float(
        atmosphere.get("estimated_surface_temperature_k")
        or atmosphere.get("surface_temperature_k")
        or 288.0
    )
    pressure_bar = max(0.0, float(atmosphere.get("surface_pressure_bar", 0.0) or 0.0))
    target_ocean = _clamp(hydrology.get("target_ocean_fraction", 0.0))
    liquid_water = bool(hydrology.get("liquid_water_possible")) and pressure_bar >= 0.006
    drainage_enabled = bool(hydrology.get("drainage_enabled")) and liquid_water
    circumference_m = _planet_circumference_m(heightmap)

    height = len(rows)
    width = len(rows[0])
    elevations = [float(value or 0.0) for row in rows for value in row]
    min_elevation = min(elevations)
    max_elevation = max(elevations)
    span = max(1.0, max_elevation - min_elevation)
    ocean_mask = [
        [bool(sea_level is not None and float(value or 0.0) <= sea_level) for value in row]
        for row in rows
    ]
    shore_distances = _shore_distance_rows(ocean_mask)
    climate_rows = []
    zone_counts = {zone_id: 0 for zone_id in CLIMATE_ZONES}

    for y, row in enumerate(rows):
        ny = y / max(1, height - 1)
        latitude_abs = abs(ny - 0.5) * 2.0
        climate_row = []
        for x, value in enumerate(row):
            nx = x / max(1, width - 1)
            elevation = float(value or 0.0)
            elevation_norm = _clamp((elevation - min_elevation) / span)
            is_ocean = ocean_mask[y][x]
            shore = 1.0 - (
                shore_distances[y][x]
                if shore_distances and y < len(shore_distances) and x < len(shore_distances[y])
                else _nearest_ocean_distance(ocean_mask, x, y)
            )
            terrain = _terrain_metrics(rows, x, y, span)
            wind_x, wind_y = _prevailing_wind_vector(ny, map_seed)
            wind_gradient = terrain["gradient_x"] * wind_x + terrain["gradient_y"] * wind_y
            windward = max(0.0, wind_gradient) * 7.0
            leeward = max(0.0, -wind_gradient) * 8.5
            circulation = _wave_noise(map_seed, "climate_circulation", nx, ny)
            texture = _climate_texture(map_seed, "climate_texture", nx, ny)
            subtropical_dryness = max(0.0, 1.0 - abs(latitude_abs - 0.52) / 0.24) * 0.22
            rain_shadow = max(0.0, elevation_norm - 0.50) * 0.34 + leeward
            wetness = _clamp(
                target_ocean * 0.48
                + shore * 0.24
                + circulation * 0.18
                + windward
                + texture * 0.12
                - rain_shadow
                - subtropical_dryness
            )
            temperature = surface_temp_k - latitude_abs * 44.0 - max(0.0, elevation) * 0.006
            temperature += texture * 2.6 - terrain["roughness"] * 3.5
            zone_id = _classify_climate(
                temperature,
                wetness,
                elevation_norm,
                is_ocean,
                slope=terrain["slope"],
                roughness=terrain["roughness"],
            )
            climate_row.append(zone_id)
            zone_counts[zone_id] = zone_counts.get(zone_id, 0) + 1
        climate_rows.append(climate_row)

    total_cells = max(1, width * height)
    climate_zones = []
    for zone_id, count in sorted(zone_counts.items(), key=lambda item: (-item[1], item[0])):
        if count <= 0:
            continue
        spec = CLIMATE_ZONES.get(zone_id, CLIMATE_ZONES["temperate_dry"])
        climate_zones.append({
            "id": zone_id,
            "label": spec["label"],
            "color": list(spec["color"]),
            "fraction": round(count / total_cells, 3),
        })

    rivers = []
    if drainage_enabled and target_ocean > 0.02:
        max_rivers = int(round(5 + target_ocean * 10))
        sources = _select_river_sources(
            rows,
            ocean_mask,
            climate_rows,
            sea_level,
            max_rivers=max_rivers,
            shore_distances=shore_distances,
        )
        for index, source in enumerate(sources):
            river = _trace_river(rows, ocean_mask, source, sea_level)
            if river is None:
                continue
            river["id"] = f"river_{index + 1:02d}"
            length_m = _path_length_m(river.get("points") or [], circumference_m)
            average_width_m, mouth_width_m = _river_widths_m(
                river.get("flow", 0.0),
                length_m,
                target_ocean,
            )
            river["length_m"] = round(length_m, 1)
            river["length_km"] = round(length_m / 1000.0, 1)
            river["average_width_m"] = average_width_m
            river["mouth_width_m"] = mouth_width_m
            rivers.append(river)

    return {
        "status": "water_cycle_seeded",
        "model_version": WATER_CYCLE_MODEL_VERSION,
        "map_seed": map_seed,
        "hydrology_enabled": drainage_enabled,
        "liquid_water_possible": liquid_water,
        "projection": heightmap.get("projection", "equirectangular"),
        "scale": {
            "coverage": heightmap.get("coverage", "full_planet"),
            "circumference_m": round(circumference_m, 1),
            "equator_resolution_m_per_px": heightmap.get("equator_resolution_m_per_px"),
        },
        "wrap_x": bool(heightmap.get("wrap_x", True)),
        "wrap_y": bool(heightmap.get("wrap_y", False)),
        "climate_grid": {
            "width": width,
            "height": height,
            "rows": climate_rows,
            "elevation_rows": rows,
            "shore_distance_rows": shore_distances,
        },
        "climate_zones": climate_zones,
        "rivers": rivers,
        "river_count": len(rivers),
        "runoff_summary": {
            "target_ocean_fraction": round(target_ocean, 3),
            "surface_pressure_bar": round(pressure_bar, 4),
            "mean_temperature_k": round(surface_temp_k, 1),
            "dominant_climate": climate_zones[0]["id"] if climate_zones else None,
            "drainage_enabled": drainage_enabled,
        },
    }
