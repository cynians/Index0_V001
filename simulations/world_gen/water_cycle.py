import math

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


def _classify_climate(temperature_k, wetness, elevation_norm, is_ocean):
    if is_ocean:
        return "ocean"
    if elevation_norm > 0.78:
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


def _select_river_sources(rows, ocean_mask, climate_rows, sea_level, max_rivers):
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
            shore_bonus = 0.16 * (1.0 - _nearest_ocean_distance(ocean_mask, x, y))
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
            shore = 1.0 - _nearest_ocean_distance(ocean_mask, x, y)
            circulation = _wave_noise(map_seed, "climate_circulation", nx, ny)
            rain_shadow = max(0.0, elevation_norm - 0.54) * 0.45
            wetness = _clamp(target_ocean * 0.52 + shore * 0.28 + circulation * 0.26 - rain_shadow)
            temperature = surface_temp_k - latitude_abs * 44.0 - max(0.0, elevation) * 0.006
            zone_id = _classify_climate(temperature, wetness, elevation_norm, is_ocean)
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
        sources = _select_river_sources(rows, ocean_mask, climate_rows, sea_level, max_rivers=max_rivers)
        for index, source in enumerate(sources):
            river = _trace_river(rows, ocean_mask, source, sea_level)
            if river is None:
                continue
            river["id"] = f"river_{index + 1:02d}"
            rivers.append(river)

    return {
        "status": "water_cycle_seeded",
        "model_version": WATER_CYCLE_MODEL_VERSION,
        "map_seed": map_seed,
        "hydrology_enabled": drainage_enabled,
        "liquid_water_possible": liquid_water,
        "projection": heightmap.get("projection", "equirectangular"),
        "wrap_x": bool(heightmap.get("wrap_x", True)),
        "wrap_y": bool(heightmap.get("wrap_y", False)),
        "climate_grid": {
            "width": width,
            "height": height,
            "rows": climate_rows,
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
