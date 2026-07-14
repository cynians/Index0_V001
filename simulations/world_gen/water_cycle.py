import math
from collections import deque

from simulations.world_gen.map_seed import resolved_map_seed, seed_range
from simulations.world_gen.ocean_circulation import derive_ocean_circulation
from simulations.world_gen.drainage import derive_drainage_network


WATER_CYCLE_MODEL_VERSION = "coupled-ocean-climate-hydrology-v4"

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
    "tropical_rainforest": {"label": "Tropical Rainforest", "color": [34, 122, 72]},
    "tropical_monsoon": {"label": "Tropical Monsoon", "color": [58, 146, 82]},
    "savanna": {"label": "Savanna", "color": [166, 162, 72]},
    "hot_desert": {"label": "Hot Desert", "color": [218, 184, 108]},
    "cold_desert": {"label": "Cold Desert", "color": [184, 164, 124]},
    "steppe": {"label": "Steppe", "color": [164, 154, 104]},
    "mediterranean": {"label": "Mediterranean", "color": [126, 158, 94]},
    "humid_subtropical": {"label": "Humid Subtropical", "color": [70, 150, 96]},
    "oceanic": {"label": "Oceanic", "color": [74, 138, 118]},
    "humid_continental": {"label": "Humid Continental", "color": [92, 132, 104]},
    "subarctic": {"label": "Subarctic", "color": [112, 138, 126]},
    "tundra": {"label": "Tundra", "color": [164, 178, 166]},
    "ice_cap": {"label": "Ice Cap", "color": [218, 232, 238]},
}


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, float(value)))


def _sample_inherited_rows(rows, global_u, global_v, source_bounds=None):
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], list) or not rows[0]:
        return None
    source_bounds = source_bounds if isinstance(source_bounds, dict) else {}
    u0 = float(source_bounds.get("min_u", 0.0) or 0.0)
    u1 = float(source_bounds.get("max_u", 1.0) or 1.0)
    v0 = float(source_bounds.get("min_v", 0.0) or 0.0)
    v1 = float(source_bounds.get("max_v", 1.0) or 1.0)
    local_u = (float(global_u) - u0) / max(1e-12, u1 - u0)
    local_v = (float(global_v) - v0) / max(1e-12, v1 - v0)
    local_u = _clamp(local_u)
    local_v = _clamp(local_v)
    height = len(rows)
    width = min(len(row) for row in rows if isinstance(row, list))
    px, py = local_u * max(1, width - 1), local_v * max(1, height - 1)
    x0, y0 = int(math.floor(px)), int(math.floor(py))
    x1, y1 = min(width - 1, x0 + 1), min(height - 1, y0 + 1)
    tx, ty = px - x0, py - y0
    samples = (
        (rows[y0][x0], (1.0 - tx) * (1.0 - ty)),
        (rows[y0][x1], tx * (1.0 - ty)),
        (rows[y1][x0], (1.0 - tx) * ty),
        (rows[y1][x1], tx * ty),
    )
    numeric = []
    for value, weight in samples:
        try:
            if value is not None:
                numeric.append((float(value), weight))
        except (TypeError, ValueError):
            pass
    total_weight = sum(weight for _value, weight in numeric)
    return sum(value * weight for value, weight in numeric) / total_weight if total_weight > 1e-12 else None


def _inherit_parent_ocean_circulation(local_model, parent_model, source_bounds, parent_source_bounds):
    if not isinstance(local_model, dict) or not isinstance(parent_model, dict):
        return local_model
    local_vectors = local_model.get("vector_rows")
    parent_vectors = parent_model.get("vector_rows")
    if not isinstance(local_vectors, list) or not isinstance(parent_vectors, list) or not local_vectors:
        return local_model
    height = len(local_vectors)
    width = min((len(row) for row in local_vectors if isinstance(row, list)), default=0)
    if width <= 0:
        return local_model
    u0, u1 = float(source_bounds.get("min_u", 0.0)), float(source_bounds.get("max_u", 1.0))
    v0, v1 = float(source_bounds.get("min_v", 0.0)), float(source_bounds.get("max_v", 1.0))
    parent_u = [[value[0] if isinstance(value, (list, tuple)) and len(value) >= 2 else None for value in row] for row in parent_vectors]
    parent_v = [[value[1] if isinstance(value, (list, tuple)) and len(value) >= 2 else None for value in row] for row in parent_vectors]
    field_pairs = [
        ("sea_surface_temperature_rows_k", 0.88),
        ("upwelling_rows", 0.72),
        ("surface_salinity_rows_psu", 0.85),
    ]
    for y in range(height):
        global_v = v0 + (v1 - v0) * y / max(1, height - 1)
        for x in range(width):
            local_vector = local_vectors[y][x]
            if not isinstance(local_vector, (list, tuple)) or len(local_vector) < 2:
                continue
            global_u = u0 + (u1 - u0) * x / max(1, width - 1)
            inherited_u = _sample_inherited_rows(parent_u, global_u, global_v, parent_source_bounds)
            inherited_v = _sample_inherited_rows(parent_v, global_u, global_v, parent_source_bounds)
            if inherited_u is not None and inherited_v is not None:
                local_vectors[y][x] = [
                    round(inherited_u * 0.82 + float(local_vector[0]) * 0.18, 3),
                    round(inherited_v * 0.82 + float(local_vector[1]) * 0.18, 3),
                ]
            for field, inheritance in field_pairs:
                local_rows = local_model.get(field)
                parent_rows = parent_model.get(field)
                if not isinstance(local_rows, list) or not isinstance(parent_rows, list):
                    continue
                inherited = _sample_inherited_rows(parent_rows, global_u, global_v, parent_source_bounds)
                if inherited is None or y >= len(local_rows) or x >= len(local_rows[y]) or local_rows[y][x] is None:
                    continue
                local_rows[y][x] = round(inherited * inheritance + float(local_rows[y][x]) * (1.0 - inheritance), 3)
    local_model["parent_boundary_inheritance"] = {
        "enabled": True,
        "vector_weight": 0.82,
        "scalar_weight": 0.85,
    }
    return local_model


def _rows_from_heightmap(heightmap):
    grid = heightmap.get("sample_grid") if isinstance(heightmap, dict) else {}
    rows = grid.get("rows") if isinstance(grid, dict) else []
    if not rows or len(rows) < 2 or len(rows[0]) < 2:
        return []
    width = min(len(row) for row in rows)
    rows = [list(row[:width]) for row in rows]
    # Preserve the heightfield's resolved shores. The old 129x65 cap erased
    # narrow peninsulas, small islands, straits, and inland drainage basins.
    detail_level = int(heightmap.get("map_detail_level", 0) or 0) if isinstance(heightmap, dict) else 0
    max_height = 257 if detail_level > 0 else 129
    stride = max(1, math.ceil(width / 257), math.ceil(len(rows) / max_height))
    if stride <= 1:
        return rows
    sampled = [row[::stride] for row in rows[::stride]]
    if (len(rows) - 1) % stride != 0:
        sampled.append(rows[-1][::stride])
    return sampled


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


def _classify_climate(
    temperature_k, wetness, elevation_norm, is_ocean, slope=0.0,
    roughness=0.0, precipitation_mm=0.0, seasonality_k=0.0,
    latitude_abs=0.0, coastal=0.0, permanent_ice=False,
    liquid_water_possible=True,
):
    # Cold rock/regolith is a polar desert, not an ice cap.  The latter is
    # reserved for cells where the generated volatile inventory actually
    # leaves persistent surface ice.
    if permanent_ice:
        return "ice_cap"
    if is_ocean:
        return "ocean"
    highland_score = elevation_norm * 0.82 + slope * 0.12 + roughness * 0.06
    if highland_score > 0.82 and elevation_norm > 0.68:
        return "highland"
    if temperature_k < 255.0:
        return "cold_desert"
    if temperature_k < 269.0:
        if not liquid_water_possible or wetness < 0.16:
            return "cold_desert"
        return "tundra"
    if wetness < 0.13:
        return "hot_desert" if temperature_k >= 286.0 else "cold_desert"
    if wetness < 0.25:
        return "steppe"
    if temperature_k >= 296.0:
        if precipitation_mm >= 2100:
            return "tropical_rainforest"
        if precipitation_mm >= 1250:
            return "tropical_monsoon"
        return "savanna"
    if temperature_k >= 286.0:
        if 0.28 <= latitude_abs <= 0.58 and wetness < 0.48:
            return "mediterranean"
        return "humid_subtropical" if wetness >= 0.48 else "temperate_dry"
    if temperature_k >= 274.0:
        if coastal > 0.48 and seasonality_k < 18.0:
            return "oceanic"
        return "humid_continental" if wetness >= 0.40 else "temperate_dry"
    return "subarctic" if wetness >= 0.28 else "cold_steppe"


def _nearest_ocean_temperature_rows(ocean_mask, sst_rows):
    height = len(ocean_mask)
    width = len(ocean_mask[0]) if height else 0
    result = [[None for _x in range(width)] for _y in range(height)]
    distance = [[None for _x in range(width)] for _y in range(height)]
    queue = deque()
    for y in range(height):
        for x in range(width):
            if ocean_mask[y][x] and sst_rows[y][x] is not None:
                result[y][x] = float(sst_rows[y][x])
                distance[y][x] = 0
                queue.append((x, y))
    while queue:
        x, y = queue.popleft()
        for nx, ny in (((x - 1) % width, y), ((x + 1) % width, y), (x, y - 1), (x, y + 1)):
            if not 0 <= ny < height or distance[ny][nx] is not None:
                continue
            distance[ny][nx] = distance[y][x] + 1
            result[ny][nx] = result[y][x]
            queue.append((nx, ny))
    return result


def _climate_inheritance_weights(detail_level):
    """Preserve synoptic climate while allowing finer-scale terrain to matter."""
    level = max(0, int(detail_level or 0))
    parent_weight = {
        0: 0.0,
        1: 0.80,
        2: 0.70,
        3: 0.60,
        4: 0.52,
        5: 0.44,
        6: 0.38,
        7: 0.32,
    }.get(level, 0.32)
    return {
        "temperature": parent_weight,
        "precipitation": max(0.24, parent_weight - 0.04),
        "seasonality": min(0.86, parent_weight + 0.04),
    }


def _upwind_ocean_fetch(ocean_mask, sst_rows, x, y, wind_x, wind_y, steps=14):
    height = len(ocean_mask)
    width = len(ocean_mask[0]) if height else 0
    px, py = float(x), float(y)
    fetch = 0.0
    thermal = 0.0
    for step in range(1, steps + 1):
        px = (px - wind_x) % width
        py = py - wind_y
        iy = int(round(py))
        if not 0 <= iy < height:
            break
        ix = int(round(px)) % width
        if ocean_mask[iy][ix]:
            weight = math.exp(-step / 6.0)
            fetch += weight
            thermal += weight * _clamp((float(sst_rows[iy][ix] or 273.0) - 273.0) / 28.0)
    return _clamp(fetch / 3.8), _clamp(thermal / 3.8)


def _flow_accumulation(rows, ocean_mask, runoff_rows):
    height = len(rows)
    width = len(rows[0])
    accumulation = [[float(runoff_rows[y][x] or 0.0) for x in range(width)] for y in range(height)]
    downstream = {}
    cells = sorted(((float(rows[y][x] or 0.0), x, y) for y in range(height) for x in range(width) if not ocean_mask[y][x]), reverse=True)
    for elevation, x, y in cells:
        candidates = [(float(rows[ny][nx] or 0.0), nx, ny) for nx, ny in _neighbor_points(width, height, x, y)]
        if not candidates:
            continue
        next_height, nx, ny = min(candidates)
        if next_height >= elevation and not ocean_mask[ny][nx]:
            continue
        downstream[(x, y)] = (nx, ny)
        accumulation[ny][nx] += accumulation[y][x]
    return accumulation, downstream


def _trace_accumulated_river(rows, ocean_mask, source, downstream, accumulation):
    width, height = len(rows[0]), len(rows)
    x, y = source
    points, seen = [], set()
    while (x, y) not in seen and len(points) < width + height:
        seen.add((x, y))
        points.append({"x": round(x / max(1, width - 1), 4), "y": round(y / max(1, height - 1), 4)})
        if ocean_mask[y][x]:
            break
        next_point = downstream.get((x, y))
        if next_point is None:
            break
        x, y = next_point
    if len(points) < 3:
        return None
    source_flow = float(accumulation[source[1]][source[0]] or 0.0)
    max_flow = max(max(row) for row in accumulation) or 1.0
    return {"points": points, "source_elevation_m": round(float(rows[source[1]][source[0]]), 1), "mouth": "ocean" if ocean_mask[y][x] else "basin", "flow": round(_clamp(math.log1p(source_flow) / math.log1p(max_flow), 0.08, 1.0), 3)}


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


def _path_length_m(points, width_m, height_m=None, *, wrap_x=True):
    if len(points) < 2:
        return 0.0
    width_m = max(1.0, float(width_m or 1.0))
    height_m = max(1.0, float(height_m if height_m is not None else width_m * 0.5))
    total = 0.0
    previous = points[0]
    for current in points[1:]:
        x0 = float(previous.get("x", 0.0) or 0.0)
        y0 = float(previous.get("y", 0.0) or 0.0)
        x1 = float(current.get("x", 0.0) or 0.0)
        y1 = float(current.get("y", 0.0) or 0.0)
        dx_norm = abs(x1 - x0)
        if wrap_x:
            dx_norm = min(dx_norm, 1.0 - dx_norm)
        dy_norm = abs(y1 - y0)
        if wrap_x:
            mid_y = (y0 + y1) * 0.5
            latitude = (0.5 - mid_y) * math.pi
            dx_m = dx_norm * width_m * max(0.06, math.cos(latitude))
        else:
            dx_m = dx_norm * width_m
        dy_m = dy_norm * height_m
        total += math.hypot(dx_m, dy_m)
        previous = current
    return total


def _river_widths_m(flow, length_m, target_ocean, discharge_m3_s=None):
    flow = _clamp(flow, 0.0, 1.0)
    length_factor = _clamp(float(length_m or 0.0) / 2_500_000.0, 0.0, 1.0)
    ocean_factor = _clamp(target_ocean, 0.0, 1.0)
    if discharge_m3_s is not None:
        discharge = max(0.01, float(discharge_m3_s or 0.0))
        # Hydraulic-geometry approximation for a bankfull natural channel.
        average_width = 2.8 * math.sqrt(discharge) * (0.84 + length_factor * 0.16)
        mouth_width = 4.6 * math.sqrt(discharge) * (1.0 + ocean_factor * 0.28)
        average_width = _clamp(average_width, 2.0, 3200.0)
        mouth_width = _clamp(max(average_width, mouth_width), 3.0, 9000.0)
    else:
        average_width = 12.0 + (flow ** 1.25) * 260.0 + length_factor * 90.0
        mouth_width = average_width * (1.45 + flow * 0.9 + ocean_factor * 0.35)
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


def derive_water_cycle_model(terrain, heightmap, atmosphere=None, seed=None, planet_id="", parent_climate_model=None):
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
    surface_fluid = str(hydrology.get("surface_fluid") or (seed or {}).get("surface_fluid") or "water")
    liquid_water = bool(hydrology.get("liquid_water_possible")) and pressure_bar >= 0.006
    if surface_fluid != "water" and target_ocean > 0.0:
        liquid_water = True
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
    surface_ice_rows = ((heightmap.get("surface_masks") or {}).get("ice_rows") or [])
    shore_distances = _shore_distance_rows(ocean_mask)
    rotation_hours = float((seed or {}).get("rotation_hours", (seed or {}).get("rotation_period_hours", 24.0)) or 24.0)
    ocean_circulation = derive_ocean_circulation(
        ocean_mask,
        mean_surface_temperature_k=surface_temp_k,
        rotation_hours=rotation_hours,
        wrap_x=bool(heightmap.get("wrap_x", True)),
        source_uv_bounds=heightmap.get("source_uv_bounds"),
        inherit_major_gyres=isinstance(parent_climate_model, dict),
    ) if liquid_water and any(any(row) for row in ocean_mask) else {"status": "inactive"}
    if isinstance(parent_climate_model, dict) and ocean_circulation.get("status") == "ocean_circulation_seeded":
        ocean_circulation = _inherit_parent_ocean_circulation(
            ocean_circulation,
            parent_climate_model.get("ocean_circulation_model"),
            heightmap.get("source_uv_bounds") or {"min_u": 0.0, "max_u": 1.0, "min_v": 0.0, "max_v": 1.0},
            ((parent_climate_model.get("climate_grid") or {}).get("source_uv_bounds") or {"min_u": 0.0, "max_u": 1.0, "min_v": 0.0, "max_v": 1.0}),
        )
    current_vectors = ocean_circulation.get("vector_rows") or [[None for _x in range(width)] for _y in range(height)]
    sst_rows = ocean_circulation.get("sea_surface_temperature_rows_k") or [[None for _x in range(width)] for _y in range(height)]
    upwelling_rows = ocean_circulation.get("upwelling_rows") or [[0.0 for _x in range(width)] for _y in range(height)]
    nearest_ocean_temperatures = _nearest_ocean_temperature_rows(ocean_mask, sst_rows)
    axial_tilt_deg = abs(float((seed or {}).get("axial_tilt_deg", 23.4) or 23.4))
    climate_mode = str((seed or {}).get("climate_mode") or "latitudinal_seasonal")
    synchronous_rotation = bool((seed or {}).get("synchronous_rotation")) or climate_mode == "tidally_locked"
    substellar_longitude_deg = float((seed or {}).get("substellar_longitude_deg", 0.0) or 0.0)
    heat_transport = _clamp(math.log1p(pressure_bar) / math.log(11.0), 0.08, 0.92)
    climate_rows = []
    temperature_rows = []
    precipitation_rows = []
    seasonality_rows = []
    runoff_rows = []
    evapotranspiration_rows = []
    infiltration_rows = []
    snow_fraction_rows = []
    zone_counts = {zone_id: 0 for zone_id in CLIMATE_ZONES}
    source_uv = heightmap.get("source_uv_bounds") if isinstance(heightmap.get("source_uv_bounds"), dict) else {}
    source_u0 = float(source_uv.get("min_u", 0.0) or 0.0)
    source_u1 = float(source_uv.get("max_u", 1.0) or 1.0)
    source_v0 = float(source_uv.get("min_v", 0.0) or 0.0)
    source_v1 = float(source_uv.get("max_v", 1.0) or 1.0)
    parent_climate_grid = parent_climate_model.get("climate_grid") if isinstance(parent_climate_model, dict) else {}
    parent_source_uv = parent_climate_grid.get("source_uv_bounds") if isinstance(parent_climate_grid, dict) else {}
    detail_level = int(heightmap.get("map_detail_level", 0) or 0)
    inheritance_weights = _climate_inheritance_weights(detail_level)

    for y, row in enumerate(rows):
        local_ny = y / max(1, height - 1)
        ny = source_v0 + (source_v1 - source_v0) * local_ny
        latitude_abs = abs(ny - 0.5) * 2.0
        climate_row = []
        temperature_row = []
        precipitation_row = []
        seasonality_row = []
        runoff_row = []
        evapotranspiration_row = []
        infiltration_row = []
        snow_fraction_row = []
        for x, value in enumerate(row):
            local_nx = x / max(1, width - 1)
            nx = source_u0 + (source_u1 - source_u0) * local_nx
            elevation = float(value or 0.0)
            elevation_norm = _clamp((elevation - min_elevation) / span)
            is_ocean = ocean_mask[y][x]
            permanent_ice = bool(
                y < len(surface_ice_rows)
                and isinstance(surface_ice_rows[y], list)
                and x < len(surface_ice_rows[y])
                and surface_ice_rows[y][x]
            )
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
            circulation_texture = _wave_noise(map_seed, "climate_circulation", nx, ny)
            texture = _climate_texture(map_seed, "climate_texture", nx, ny)
            subtropical_dryness = max(0.0, 1.0 - abs(latitude_abs - 0.52) / 0.24) * 0.22
            rain_shadow = max(0.0, elevation_norm - 0.50) * 0.34 + leeward
            ocean_fetch, warm_fetch = _upwind_ocean_fetch(ocean_mask, sst_rows, x, y, wind_x, wind_y)
            temperature = surface_temp_k + 12.0 - latitude_abs * 48.0 - max(0.0, elevation) * 0.0062
            if synchronous_rotation:
                longitude_deg = nx * 360.0 - 180.0
                longitude_delta = math.radians(((longitude_deg - substellar_longitude_deg + 180.0) % 360.0) - 180.0)
                illumination = max(0.0, math.cos(longitude_delta)) * max(0.0, math.cos((ny - 0.5) * math.pi))
                day_night_contrast = 72.0 * (1.0 - heat_transport) + 12.0
                temperature += (illumination - 0.28) * day_night_contrast
            temperature += texture * 2.6 - terrain["roughness"] * 3.5
            if is_ocean and sst_rows[y][x] is not None:
                temperature = float(sst_rows[y][x])
            elif nearest_ocean_temperatures[y][x] is not None:
                maritime = shore * 0.58
                temperature += (float(nearest_ocean_temperatures[y][x]) - temperature) * maritime
            continentality = 1.0 - shore
            seasonality = 4.0 + latitude_abs * (axial_tilt_deg / 23.44) * (10.0 + continentality * 18.0)
            inherited_temperature = _sample_inherited_rows(
                parent_climate_grid.get("temperature_rows_k"), nx, ny, parent_source_uv,
            ) if isinstance(parent_climate_grid, dict) else None
            inherited_elevation = _sample_inherited_rows(
                parent_climate_grid.get("elevation_rows"), nx, ny, parent_source_uv,
            ) if isinstance(parent_climate_grid, dict) else None
            if inherited_temperature is not None:
                inherited_local_temperature = inherited_temperature
                if inherited_elevation is not None:
                    inherited_local_temperature -= (elevation - inherited_elevation) * 0.0062
                parent_weight = inheritance_weights["temperature"]
                temperature = inherited_local_temperature * parent_weight + temperature * (1.0 - parent_weight)
            inherited_seasonality = _sample_inherited_rows(
                parent_climate_grid.get("temperature_seasonality_rows_k"), nx, ny, parent_source_uv,
            ) if isinstance(parent_climate_grid, dict) else None
            if inherited_seasonality is not None:
                parent_weight = inheritance_weights["seasonality"]
                seasonality = inherited_seasonality * parent_weight + seasonality * (1.0 - parent_weight)
            itcz_rain = math.exp(-((latitude_abs / 0.16) ** 2)) * 1450.0
            storm_track_rain = math.exp(-(((latitude_abs - 0.58) / 0.18) ** 2)) * 520.0
            ocean_supply = ocean_fetch * (620.0 + warm_fetch * 760.0)
            relief_rain = windward * 1500.0
            upwelling_cooling = float(upwelling_rows[y][x] or 0.0) if is_ocean else 0.0
            precipitation = 90.0 + itcz_rain + storm_track_rain + ocean_supply + circulation_texture * 210.0 + relief_rain
            precipitation -= subtropical_dryness * 1850.0 + rain_shadow * 1350.0 + upwelling_cooling * 240.0
            inherited_precipitation = _sample_inherited_rows(
                parent_climate_grid.get("annual_precipitation_rows_mm"), nx, ny, parent_source_uv,
            ) if isinstance(parent_climate_grid, dict) else None
            if inherited_precipitation is not None:
                parent_weight = inheritance_weights["precipitation"]
                precipitation = inherited_precipitation * parent_weight + precipitation * (1.0 - parent_weight)
            precipitation = max(15.0, min(4200.0, precipitation))
            potential_evaporation = max(80.0, (temperature - 250.0) * 24.0) * (1.0 + subtropical_dryness)
            wetness = _clamp(precipitation / max(1.0, precipitation + potential_evaporation))
            zone_id = _classify_climate(
                temperature,
                wetness,
                elevation_norm,
                is_ocean,
                slope=terrain["slope"],
                roughness=terrain["roughness"],
                precipitation_mm=precipitation,
                seasonality_k=seasonality,
                latitude_abs=latitude_abs,
                coastal=shore,
                permanent_ice=permanent_ice,
                liquid_water_possible=liquid_water,
            )
            climate_row.append(zone_id)
            temperature_row.append(round(temperature, 1))
            precipitation_row.append(round(precipitation, 1))
            seasonality_row.append(round(seasonality, 1))
            infiltration_fraction = _clamp(0.48 - terrain["slope"] * 0.24 + (0.08 if wetness < 0.3 else 0.0), 0.14, 0.62)
            actual_evapotranspiration = 0.0 if is_ocean else min(precipitation * 0.88, potential_evaporation * (0.28 + wetness * 0.72))
            available_water = 0.0 if is_ocean else max(0.0, precipitation - actual_evapotranspiration)
            runoff = available_water * (1.0 - infiltration_fraction)
            infiltration = available_water - runoff
            snow_fraction = 0.0 if is_ocean else _clamp((273.15 - temperature + seasonality * 0.22) / 18.0)
            runoff_row.append(round(runoff, 1))
            evapotranspiration_row.append(round(actual_evapotranspiration, 1))
            infiltration_row.append(round(infiltration, 1))
            snow_fraction_row.append(round(snow_fraction, 3))
            zone_counts[zone_id] = zone_counts.get(zone_id, 0) + 1
        climate_rows.append(climate_row)
        temperature_rows.append(temperature_row)
        precipitation_rows.append(precipitation_row)
        seasonality_rows.append(seasonality_row)
        runoff_rows.append(runoff_row)
        evapotranspiration_rows.append(evapotranspiration_row)
        infiltration_rows.append(infiltration_row)
        snow_fraction_rows.append(snow_fraction_row)

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

    drainage_network = derive_drainage_network(
        rows,
        ocean_mask,
        runoff_rows,
        wrap_x=bool(heightmap.get("wrap_x", True)),
        detail_level=detail_level,
    ) if drainage_enabled else {"status": "inactive", "rivers": [], "lakes": [], "drainage_basins": []}
    rivers = list(drainage_network.get("rivers") or [])
    region_width_m = float(heightmap.get("region_width_m") or 0.0)
    region_height_m = float(heightmap.get("region_height_m") or 0.0)
    represented_area_m2 = (
        region_width_m * region_height_m
        if region_width_m > 0.0 and region_height_m > 0.0
        else circumference_m * circumference_m / math.pi
    )
    mean_cell_area_m2 = represented_area_m2 / max(1, width * height)
    seconds_per_year = 365.2425 * 24.0 * 3600.0
    for river in rivers:
        length_m = _path_length_m(
            river.get("points") or [],
            region_width_m or circumference_m,
            region_height_m or circumference_m * 0.5,
            wrap_x=bool(heightmap.get("wrap_x", True)),
        )
        discharge_m3_s = (
            max(0.0, float(river.get("runoff_accumulation_mm_cells", 0.0) or 0.0))
            * mean_cell_area_m2 * 0.001 / seconds_per_year
        )
        average_width_m, mouth_width_m = _river_widths_m(
            river.get("flow", 0.0), length_m, target_ocean, discharge_m3_s=discharge_m3_s,
        )
        river.update({
            "length_m": round(length_m, 1),
            "length_km": round(length_m / 1000.0, 1),
            "average_width_m": average_width_m,
            "mouth_width_m": mouth_width_m,
            "estimated_discharge_m3_s": round(discharge_m3_s, 1),
        })

    return {
        "status": "water_cycle_seeded",
        "model_version": WATER_CYCLE_MODEL_VERSION,
        "map_seed": map_seed,
        "hydrology_enabled": drainage_enabled,
        "liquid_water_possible": liquid_water,
        "surface_fluid": surface_fluid,
        "climate_mode": climate_mode,
        "tidally_locked_climate": {
            "enabled": synchronous_rotation,
            "substellar_longitude_deg": substellar_longitude_deg,
            "atmospheric_heat_transport_efficiency": round(heat_transport, 3),
            "permanent_nightside": synchronous_rotation,
            "terminator_transition_modeled": synchronous_rotation,
        },
        "seasonal_cycle_model": {
            "enabled": bool((seed or {}).get("seasonal_cycle")) or axial_tilt_deg >= 28.0,
            "axial_tilt_deg": round(axial_tilt_deg, 2),
            "orbital_phases": [
                {
                    "phase": index,
                    "solar_longitude_deg": index * 45,
                    "global_temperature_anomaly_k": round(math.sin(math.radians(index * 45)) * min(24.0, axial_tilt_deg * 0.22), 2),
                    "frost_migration_bias": round(math.sin(math.radians(index * 45)) * min(1.0, axial_tilt_deg / 60.0), 3),
                }
                for index in range(8)
            ],
        },
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
            "temperature_rows_k": temperature_rows,
            "annual_precipitation_rows_mm": precipitation_rows,
            "temperature_seasonality_rows_k": seasonality_rows,
            "annual_runoff_rows_mm": runoff_rows,
            "annual_evapotranspiration_rows_mm": evapotranspiration_rows,
            "annual_infiltration_rows_mm": infiltration_rows,
            "seasonal_snow_fraction_rows": snow_fraction_rows,
            "source_uv_bounds": {
                "min_u": source_u0, "max_u": source_u1,
                "min_v": source_v0, "max_v": source_v1,
            },
            "parent_climate_inheritance": {
                "enabled": isinstance(parent_climate_model, dict),
                "temperature_weight": inheritance_weights["temperature"],
                "precipitation_weight": inheritance_weights["precipitation"],
                "seasonality_weight": inheritance_weights["seasonality"],
            },
        },
        "ocean_circulation_model": ocean_circulation,
        "drainage_network_model": drainage_network,
        "drainage_basins": drainage_network.get("drainage_basins") or [],
        "lakes": drainage_network.get("lakes") or [],
        "lake_count": int(drainage_network.get("lake_count", 0) or 0),
        "climate_zones": climate_zones,
        "rivers": rivers,
        "river_count": len(rivers),
        "runoff_summary": {
            "target_ocean_fraction": round(target_ocean, 3),
            "surface_pressure_bar": round(pressure_bar, 4),
            "mean_temperature_k": round(surface_temp_k, 1),
            "dominant_climate": climate_zones[0]["id"] if climate_zones else None,
            "drainage_enabled": drainage_enabled,
            "mean_land_precipitation_mm": round(sum(precipitation_rows[y][x] for y in range(height) for x in range(width) if not ocean_mask[y][x]) / max(1, sum(1 for y in range(height) for x in range(width) if not ocean_mask[y][x])), 1),
            "ocean_basin_count": int((ocean_circulation.get("summary") or {}).get("ocean_basin_count", 0) or 0),
            "major_gyre_count": int((ocean_circulation.get("summary") or {}).get("major_gyre_count", 0) or 0),
            "mean_land_runoff_mm": round(sum(runoff_rows[y][x] for y in range(height) for x in range(width) if not ocean_mask[y][x]) / max(1, sum(1 for y in range(height) for x in range(width) if not ocean_mask[y][x])), 1),
            "mean_land_infiltration_mm": round(sum(infiltration_rows[y][x] for y in range(height) for x in range(width) if not ocean_mask[y][x]) / max(1, sum(1 for y in range(height) for x in range(width) if not ocean_mask[y][x])), 1),
            "mean_land_evapotranspiration_mm": round(sum(evapotranspiration_rows[y][x] for y in range(height) for x in range(width) if not ocean_mask[y][x]) / max(1, sum(1 for y in range(height) for x in range(width) if not ocean_mask[y][x])), 1),
        },
    }
