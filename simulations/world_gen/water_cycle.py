import math
from collections import deque

try:
    import numpy as np
except ImportError:  # pragma: no cover - requirements include numpy.
    np = None

from simulations.world_gen.map_seed import resolved_map_seed, seed_range
from simulations.world_gen.ocean_circulation import derive_ocean_circulation
from simulations.world_gen.drainage import (
    derive_drainage_network,
    inherit_parent_drainage,
)


WATER_CYCLE_MODEL_VERSION = "annual-energy-moisture-balance-koppen-v9"

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

KOPPEN_CLASSES = {
    "Af": {"label": "Tropical Rainforest", "zone_id": "tropical_rainforest", "color": [24, 116, 68]},
    "Am": {"label": "Tropical Monsoon", "zone_id": "tropical_monsoon", "color": [48, 142, 78]},
    "Aw": {"label": "Tropical Savanna", "zone_id": "savanna", "color": [160, 164, 70]},
    "BWh": {"label": "Hot Desert", "zone_id": "hot_desert", "color": [222, 184, 102]},
    "BWk": {"label": "Cold Desert", "zone_id": "cold_desert", "color": [188, 166, 124]},
    "BSh": {"label": "Hot Steppe", "zone_id": "steppe", "color": [178, 162, 94]},
    "BSk": {"label": "Cold Steppe", "zone_id": "cold_steppe", "color": [148, 154, 112]},
    "Csa": {"label": "Hot-summer Mediterranean", "zone_id": "mediterranean", "color": [142, 158, 86]},
    "Csb": {"label": "Warm-summer Mediterranean", "zone_id": "mediterranean", "color": [126, 158, 94]},
    "Csc": {"label": "Cool-summer Mediterranean", "zone_id": "mediterranean", "color": [112, 150, 104]},
    "Cwa": {"label": "Dry-winter Humid Subtropical", "zone_id": "humid_subtropical", "color": [76, 148, 88]},
    "Cwb": {"label": "Dry-winter Subtropical Highland", "zone_id": "temperate_wet", "color": [82, 142, 104]},
    "Cwc": {"label": "Dry-winter Cool Highland", "zone_id": "temperate_wet", "color": [96, 140, 112]},
    "Cfa": {"label": "Humid Subtropical", "zone_id": "humid_subtropical", "color": [66, 146, 92]},
    "Cfb": {"label": "Oceanic", "zone_id": "oceanic", "color": [72, 136, 116]},
    "Cfc": {"label": "Subpolar Oceanic", "zone_id": "subarctic", "color": [100, 136, 124]},
    "Dsa": {"label": "Dry-summer Continental", "zone_id": "humid_continental", "color": [112, 136, 94]},
    "Dsb": {"label": "Dry-summer Continental", "zone_id": "humid_continental", "color": [106, 134, 102]},
    "Dsc": {"label": "Dry-summer Subarctic", "zone_id": "subarctic", "color": [118, 138, 116]},
    "Dsd": {"label": "Severe Dry-summer Subarctic", "zone_id": "subarctic", "color": [126, 140, 124]},
    "Dwa": {"label": "Dry-winter Continental", "zone_id": "humid_continental", "color": [96, 132, 96]},
    "Dwb": {"label": "Dry-winter Continental", "zone_id": "humid_continental", "color": [100, 134, 102]},
    "Dwc": {"label": "Dry-winter Subarctic", "zone_id": "subarctic", "color": [112, 136, 118]},
    "Dwd": {"label": "Severe Dry-winter Subarctic", "zone_id": "subarctic", "color": [122, 138, 126]},
    "Dfa": {"label": "Hot-summer Continental", "zone_id": "humid_continental", "color": [88, 130, 98]},
    "Dfb": {"label": "Warm-summer Continental", "zone_id": "humid_continental", "color": [92, 132, 104]},
    "Dfc": {"label": "Subarctic", "zone_id": "subarctic", "color": [108, 136, 122]},
    "Dfd": {"label": "Severe Subarctic", "zone_id": "subarctic", "color": [118, 138, 128]},
    "ET": {"label": "Tundra", "zone_id": "tundra", "color": [166, 180, 168]},
    "EF": {"label": "Ice Cap", "zone_id": "ice_cap", "color": [218, 232, 238]},
    "Ocean": {"label": "Ocean", "zone_id": "ocean", "color": [50, 92, 132]},
}


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, float(value)))


def _orbital_eccentricity(seed):
    seed = seed if isinstance(seed, dict) else {}
    return _clamp(seed.get("orbital_eccentricity", seed.get("eccentricity", 0.0)), 0.0, 0.85)


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


def _sample_inherited_category(rows, global_u, global_v, source_bounds=None):
    if (
        not isinstance(rows, list)
        or not rows
        or not isinstance(rows[0], list)
        or not rows[0]
    ):
        return None
    source_bounds = source_bounds if isinstance(source_bounds, dict) else {}
    u0 = float(source_bounds.get("min_u", 0.0) or 0.0)
    u1 = float(source_bounds.get("max_u", 1.0) or 1.0)
    v0 = float(source_bounds.get("min_v", 0.0) or 0.0)
    v1 = float(source_bounds.get("max_v", 1.0) or 1.0)
    local_u = _clamp(
        (float(global_u) - u0) / max(1e-12, u1 - u0)
    )
    local_v = _clamp(
        (float(global_v) - v0) / max(1e-12, v1 - v0)
    )
    height = len(rows)
    width = min(len(row) for row in rows if isinstance(row, list))
    x = min(width - 1, max(0, int(round(local_u * (width - 1)))))
    y = min(height - 1, max(0, int(round(local_v * (height - 1)))))
    return rows[y][x]


def _edge_locked_parent_weight(base_weight, local_x, local_y):
    """Converge continuous child climate fields to their parent at patch edges."""
    edge_distance = min(
        float(local_x),
        1.0 - float(local_x),
        float(local_y),
        1.0 - float(local_y),
    )
    transition = _clamp(edge_distance / 0.075)
    transition = transition * transition * (3.0 - 2.0 * transition)
    edge_lock = 1.0 - transition
    return float(base_weight) + (1.0 - float(base_weight)) * edge_lock


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


def _annual_reference_evaporation_mm(
    temperature_k,
    latitude_abs,
    pressure_bar,
    wind_speed_m_s,
    relative_humidity,
):
    """FAO-56 Penman-Monteith-style annual reference evaporation estimate."""
    temperature_c = max(-80.0, min(80.0, float(temperature_k) - 273.15))
    pressure_kpa = max(0.08, float(pressure_bar) * 100.0)
    relative_humidity = _clamp(relative_humidity, 0.02, 0.99)
    wind_speed_m_s = _clamp(wind_speed_m_s, 0.1, 18.0)
    saturation_vapour_pressure = 0.6108 * math.exp(
        17.27 * temperature_c / max(1.0, temperature_c + 237.3)
    )
    vapour_pressure_deficit = saturation_vapour_pressure * (1.0 - relative_humidity)
    slope_vapour_curve = (
        4098.0 * saturation_vapour_pressure
        / max(1.0, (temperature_c + 237.3) ** 2)
    )
    psychrometric_constant = 0.000665 * pressure_kpa
    # Annual-mean available radiation proxy. Latitude remains an energy input,
    # not a source of water.
    net_radiation_mj_m2_day = 4.5 + 10.5 * math.cos(
        _clamp(latitude_abs) * math.pi * 0.5
    ) ** 1.35
    numerator = (
        0.408 * slope_vapour_curve * net_radiation_mj_m2_day
        + psychrometric_constant
        * (900.0 / max(193.0, temperature_c + 273.0))
        * wind_speed_m_s
        * vapour_pressure_deficit
    )
    denominator = slope_vapour_curve + psychrometric_constant * (
        1.0 + 0.34 * wind_speed_m_s
    )
    daily_mm = max(0.0, numerator / max(1e-9, denominator))
    return min(6200.0, daily_mm * 365.2425)


def _budyko_evapotranspiration_mm(precipitation_mm, potential_evaporation_mm, omega=2.6):
    """Fu-Budyko long-term partition of annual precipitation into ET and runoff."""
    precipitation = max(0.0, float(precipitation_mm or 0.0))
    potential = max(0.0, float(potential_evaporation_mm or 0.0))
    if precipitation <= 1e-9 or potential <= 1e-9:
        return 0.0
    aridity = potential / precipitation
    evaporation_ratio = (
        1.0
        + aridity
        - (1.0 + aridity ** float(omega)) ** (1.0 / float(omega))
    )
    return min(precipitation, potential, precipitation * _clamp(evaporation_ratio))


def _koppen_geiger_class(
    mean_temperature_k,
    seasonality_k,
    annual_precipitation_mm,
    summer_precipitation_fraction,
    precipitation_seasonality,
    *,
    is_ocean=False,
    permanent_ice=False,
):
    """Classify annual normals using the Beck et al. Köppen-Geiger thresholds."""
    if is_ocean:
        return "Ocean"

    mean_c = float(mean_temperature_k) - 273.15
    temperature_range = max(0.0, float(seasonality_k or 0.0))
    warmest_c = mean_c + temperature_range * 0.5
    coldest_c = mean_c - temperature_range * 0.5
    annual_precipitation = max(0.0, float(annual_precipitation_mm or 0.0))
    summer_fraction = _clamp(summer_precipitation_fraction)
    precipitation_seasonality = _clamp(precipitation_seasonality)
    mean_monthly_precipitation = annual_precipitation / 12.0
    wettest_month = mean_monthly_precipitation * (1.0 + precipitation_seasonality * 1.8)
    driest_month = mean_monthly_precipitation * max(
        0.02, 1.0 - precipitation_seasonality * 1.15
    )

    if summer_fraction >= 0.70:
        aridity_offset = 280.0
    elif summer_fraction <= 0.30:
        aridity_offset = 0.0
    else:
        aridity_offset = 140.0
    aridity_threshold = max(0.0, 20.0 * mean_c + aridity_offset)
    if annual_precipitation < aridity_threshold:
        desert = annual_precipitation < aridity_threshold * 0.5
        hot = mean_c >= 18.0
        return ("BW" if desert else "BS") + ("h" if hot else "k")

    if permanent_ice or warmest_c < 10.0:
        return "EF" if warmest_c < 0.0 else "ET"

    if coldest_c >= 18.0:
        if driest_month >= 60.0:
            return "Af"
        if driest_month >= max(0.0, 100.0 - annual_precipitation / 25.0):
            return "Am"
        return "Aw"

    phase = seed_range(
        f"{mean_c:.3f}:{temperature_range:.3f}",
        "koppen:temperature_phase",
        0.0,
        math.tau,
    )
    months_above_10c = sum(
        mean_c + temperature_range * 0.5 * math.sin(phase + month * math.tau / 12.0) > 10.0
        for month in range(12)
    )
    if warmest_c >= 22.0:
        thermal_suffix = "a"
    elif months_above_10c >= 4:
        thermal_suffix = "b"
    elif coldest_c <= -38.0:
        thermal_suffix = "d"
    else:
        thermal_suffix = "c"

    strongly_summer_dry = summer_fraction < 0.35 and driest_month < 40.0 and wettest_month > driest_month * 3.0
    strongly_winter_dry = summer_fraction > 0.65 and wettest_month > driest_month * 10.0
    moisture_suffix = "s" if strongly_summer_dry else ("w" if strongly_winter_dry else "f")
    major = "C" if coldest_c > 0.0 else "D"
    return major + moisture_suffix + thermal_suffix


def _koppen_zone_id(code):
    return (KOPPEN_CLASSES.get(str(code)) or {}).get("zone_id", "temperate_dry")


def _solve_coupled_annual_climate_arrays(
    base_temperature_rows,
    wind_vector_rows,
    condensation_rows,
    ocean_mask,
    permanent_ice_rows,
    *,
    pressure_bar,
    hydrology_cycle,
    liquid_water,
    initial_climate=None,
):
    """Array implementation of the annual solver's existing cell equations."""
    base_temperature = np.asarray(base_temperature_rows, dtype=np.float64)
    ocean = np.asarray(ocean_mask, dtype=bool)
    permanent_ice = np.asarray(permanent_ice_rows, dtype=bool)
    winds = np.asarray(wind_vector_rows, dtype=np.float64)
    condensation = np.clip(
        np.asarray(condensation_rows, dtype=np.float64),
        0.01,
        0.62,
    )
    height, width = base_temperature.shape
    initial_climate = (
        initial_climate if isinstance(initial_climate, dict) else {}
    )

    def compatible_grid(name):
        try:
            grid = np.asarray(initial_climate.get(name), dtype=np.float64)
        except (TypeError, ValueError):
            return None
        return grid if grid.shape == (height, width) else None

    initial_temperature = compatible_grid("temperature_rows_k")
    initial_precipitation = compatible_grid(
        "annual_precipitation_rows_mm"
    )
    initial_evaporation = compatible_grid(
        "annual_evapotranspiration_rows_mm"
    )
    initial_potential_evaporation = compatible_grid(
        "annual_potential_evaporation_rows_mm"
    )
    initial_humidity = compatible_grid("relative_humidity_rows")
    warm_started = all(
        grid is not None
        for grid in (
            initial_temperature,
            initial_precipitation,
            initial_evaporation,
            initial_potential_evaporation,
            initial_humidity,
        )
    )
    temperatures = (
        initial_temperature.copy()
        if warm_started
        else base_temperature.copy()
    )
    precipitation = (
        initial_precipitation.copy()
        if warm_started
        else np.zeros((height, width), dtype=np.float64)
    )
    actual_evaporation = (
        initial_evaporation.copy()
        if warm_started
        else np.zeros((height, width), dtype=np.float64)
    )
    potential_evaporation = (
        initial_potential_evaporation.copy()
        if warm_started
        else np.zeros((height, width), dtype=np.float64)
    )
    relative_humidity = (
        np.clip(initial_humidity, 0.03, 0.98)
        if warm_started
        else np.full((height, width), 0.05, dtype=np.float64)
    )
    moisture = (
        np.clip(relative_humidity * 1.8, 0.0, 2.8)
        if warm_started
        else np.zeros((height, width), dtype=np.float64)
    )
    latitude_abs = (
        np.abs(
            np.arange(height, dtype=np.float64)
            / max(1, height - 1)
            - 0.5
        )
        * 2.0
    )[:, None]
    wind_x = winds[:, :, 0]
    wind_y = winds[:, :, 1]
    wind_speed = np.clip(winds[:, :, 2], 0.1, 18.0)
    grid_y, grid_x = np.indices((height, width))
    upstream_x = np.rint(grid_x - wind_x).astype(np.int64) % width
    upstream_y = np.clip(
        np.rint(grid_y - wind_y).astype(np.int64),
        0,
        height - 1,
    )
    limited_factor = 0.32 if hydrology_cycle == "limited" else 1.0
    transport_retention = _clamp(
        0.78 + math.log1p(max(0.0, pressure_bar)) * 0.055,
        0.76,
        0.94,
    )
    iterations = max(18, min(42, width // 4 + height // 5))
    converged_at = iterations
    previous_max_delta = 0.0

    def annual_reference_evaporation(temperature, humidity):
        temperature_c = np.clip(temperature - 273.15, -80.0, 80.0)
        pressure_kpa = max(0.08, float(pressure_bar) * 100.0)
        humidity = np.clip(humidity, 0.02, 0.99)
        saturation = 0.6108 * np.exp(
            17.27
            * temperature_c
            / np.maximum(1.0, temperature_c + 237.3)
        )
        vapour_deficit = saturation * (1.0 - humidity)
        slope_curve = (
            4098.0
            * saturation
            / np.maximum(1.0, (temperature_c + 237.3) ** 2)
        )
        psychrometric = 0.000665 * pressure_kpa
        radiation = (
            4.5
            + 10.5
            * np.cos(np.clip(latitude_abs, 0.0, 1.0) * math.pi * 0.5)
            ** 1.35
        )
        numerator = (
            0.408 * slope_curve * radiation
            + psychrometric
            * (900.0 / np.maximum(193.0, temperature_c + 273.0))
            * wind_speed
            * vapour_deficit
        )
        denominator = slope_curve + psychrometric * (
            1.0 + 0.34 * wind_speed
        )
        return np.minimum(
            6200.0,
            np.maximum(0.0, numerator / np.maximum(1e-9, denominator))
            * 365.2425,
        )

    def budyko_evaporation(precipitation_field, potential_field):
        valid = (precipitation_field > 1e-9) & (potential_field > 1e-9)
        aridity = potential_field / np.maximum(1e-9, precipitation_field)
        ratio = (
            1.0
            + aridity
            - (1.0 + aridity ** 2.6) ** (1.0 / 2.6)
        )
        result = np.minimum(
            precipitation_field,
            np.minimum(
                potential_field,
                precipitation_field * np.clip(ratio, 0.0, 1.0),
            ),
        )
        return np.where(valid, result, 0.0)

    has_surface_reservoir = bool(ocean.any() or permanent_ice.any())
    if not liquid_water or not has_surface_reservoir:
        potential_evaporation = annual_reference_evaporation(
            temperatures,
            np.full((height, width), 0.05, dtype=np.float64),
        )
        return {
            "temperature_rows_k": temperatures.tolist(),
            "annual_precipitation_rows_mm": precipitation.tolist(),
            "annual_potential_evaporation_rows_mm": (
                potential_evaporation.tolist()
            ),
            "annual_evapotranspiration_rows_mm": (
                actual_evaporation.tolist()
            ),
            "relative_humidity_rows": relative_humidity.tolist(),
            "iterations": 0,
            "warm_started": warm_started,
            "converged": True,
            "maximum_final_change": 0.0,
            "global_water_balance_error_fraction": 0.0,
        }

    for iteration in range(iterations):
        north = np.vstack((moisture[:1], moisture[:-1]))
        south = np.vstack((moisture[1:], moisture[-1:]))
        lateral = (
            np.roll(moisture, 1, axis=1)
            + np.roll(moisture, -1, axis=1)
            + north
            + south
        ) * 0.25
        incoming = (
            moisture[upstream_y, upstream_x] * 0.72
            + lateral * 0.20
            + moisture * 0.08
        )
        humidity = np.clip(incoming / 1.8, 0.03, 0.98)
        potential_evaporation = annual_reference_evaporation(
            temperatures,
            humidity,
        )
        ocean_source = np.where(
            ocean,
            np.clip(potential_evaporation / 1800.0, 0.10, 1.65)
            * 0.62
            * limited_factor,
            0.0,
        )
        ice_source = np.where(
            permanent_ice & ~ocean,
            np.clip(potential_evaporation / 2600.0, 0.0, 0.22) * 0.12,
            0.0,
        )
        recycling_source = np.where(
            ~ocean,
            actual_evaporation / 4200.0 * 0.24,
            0.0,
        )
        condensed = incoming * condensation
        retained = incoming * (1.0 - condensation) * transport_retention
        new_moisture = np.clip(
            ocean_source + ice_source + recycling_source + retained,
            0.0,
            2.8,
        )
        precipitation_target = np.minimum(5200.0, condensed * 5900.0)
        previous_max_delta = float(
            np.max(np.abs(new_moisture - moisture))
        )
        precipitation = (
            precipitation * 0.62 + precipitation_target * 0.38
        )
        relative_humidity = np.clip(
            new_moisture / 1.8,
            0.03,
            0.98,
        )
        land_evaporation = budyko_evaporation(
            precipitation,
            potential_evaporation,
        )
        actual_evaporation = np.where(
            ~ocean,
            np.minimum(precipitation, land_evaporation),
            np.minimum(potential_evaporation * 0.86, 4800.0),
        )
        hydrologic_cooling = np.minimum(7.5, precipitation / 620.0)
        dry_surface_warming = np.where(
            ~ocean,
            (1.0 - relative_humidity) * 2.2,
            0.0,
        )
        target_temperature = (
            base_temperature
            - hydrologic_cooling
            + dry_surface_warming
        )
        temperatures = temperatures * 0.72 + target_temperature * 0.28
        moisture = new_moisture
        minimum_convergence_iteration = 5 if warm_started else 12
        if (
            iteration >= minimum_convergence_iteration
            and previous_max_delta < 0.0025
        ):
            converged_at = iteration + 1
            break

    area_weights = np.maximum(
        0.02,
        np.cos(
            (
                np.arange(height, dtype=np.float64)
                / max(1, height - 1)
                - 0.5
            )
            * math.pi
        ),
    )[:, None]
    evaporation_total = float(np.sum(actual_evaporation * area_weights))
    precipitation_total = float(np.sum(precipitation * area_weights))
    if evaporation_total <= 1e-9:
        precipitation.fill(0.0)
        water_balance_error = 0.0
    else:
        scale = _clamp(
            evaporation_total / max(1e-9, precipitation_total),
            0.30,
            2.40,
        )
        precipitation = np.minimum(5200.0, precipitation * scale)
        actual_evaporation = np.where(
            ~ocean,
            budyko_evaporation(precipitation, potential_evaporation),
            actual_evaporation,
        )
        balanced_total = float(np.sum(precipitation * area_weights))
        water_balance_error = abs(
            balanced_total - evaporation_total
        ) / max(1.0, evaporation_total)

    return {
        "temperature_rows_k": temperatures.tolist(),
        "annual_precipitation_rows_mm": precipitation.tolist(),
        "annual_potential_evaporation_rows_mm": (
            potential_evaporation.tolist()
        ),
        "annual_evapotranspiration_rows_mm": actual_evaporation.tolist(),
        "relative_humidity_rows": relative_humidity.tolist(),
        "iterations": converged_at,
        "warm_started": warm_started,
        "converged": (
            converged_at < iterations or previous_max_delta < 0.01
        ),
        "maximum_final_change": round(previous_max_delta, 6),
        "global_water_balance_error_fraction": round(
            water_balance_error,
            5,
        ),
    }


def _solve_coupled_annual_climate(
    base_temperature_rows,
    seasonality_rows,
    wind_vector_rows,
    condensation_rows,
    ocean_mask,
    permanent_ice_rows,
    *,
    pressure_bar,
    hydrology_cycle,
    liquid_water,
    initial_climate=None,
):
    """Iterate annual heat, atmospheric moisture, evaporation, and precipitation."""
    height = len(base_temperature_rows)
    width = len(base_temperature_rows[0]) if height else 0
    if width <= 0:
        return {}
    if np is not None:
        return _solve_coupled_annual_climate_arrays(
            base_temperature_rows,
            wind_vector_rows,
            condensation_rows,
            ocean_mask,
            permanent_ice_rows,
            pressure_bar=pressure_bar,
            hydrology_cycle=hydrology_cycle,
            liquid_water=liquid_water,
            initial_climate=initial_climate,
        )

    initial_climate = (
        initial_climate if isinstance(initial_climate, dict) else {}
    )

    def compatible_grid(name):
        grid = initial_climate.get(name)
        if (
            not isinstance(grid, list)
            or len(grid) != height
            or any(not isinstance(row, list) or len(row) != width for row in grid)
        ):
            return None
        return grid

    initial_temperature = compatible_grid("temperature_rows_k")
    initial_precipitation = compatible_grid(
        "annual_precipitation_rows_mm"
    )
    initial_evaporation = compatible_grid(
        "annual_evapotranspiration_rows_mm"
    )
    initial_potential_evaporation = compatible_grid(
        "annual_potential_evaporation_rows_mm"
    )
    initial_humidity = compatible_grid("relative_humidity_rows")
    warm_started = all(
        grid is not None
        for grid in (
            initial_temperature,
            initial_precipitation,
            initial_evaporation,
            initial_potential_evaporation,
            initial_humidity,
        )
    )
    temperatures = (
        [list(map(float, row)) for row in initial_temperature]
        if warm_started
        else [list(map(float, row)) for row in base_temperature_rows]
    )
    precipitation = (
        [list(map(float, row)) for row in initial_precipitation]
        if warm_started
        else [[0.0 for _x in range(width)] for _y in range(height)]
    )
    actual_evaporation = (
        [list(map(float, row)) for row in initial_evaporation]
        if warm_started
        else [[0.0 for _x in range(width)] for _y in range(height)]
    )
    potential_evaporation = (
        [list(map(float, row)) for row in initial_potential_evaporation]
        if warm_started
        else [[0.0 for _x in range(width)] for _y in range(height)]
    )
    relative_humidity = (
        [
            [_clamp(float(value), 0.03, 0.98) for value in row]
            for row in initial_humidity
        ]
        if warm_started
        else [[0.05 for _x in range(width)] for _y in range(height)]
    )
    moisture = (
        [
            [_clamp(value * 1.8, 0.0, 2.8) for value in row]
            for row in relative_humidity
        ]
        if warm_started
        else [[0.0 for _x in range(width)] for _y in range(height)]
    )
    limited_factor = 0.32 if hydrology_cycle == "limited" else 1.0
    transport_retention = _clamp(
        0.78 + math.log1p(max(0.0, pressure_bar)) * 0.055,
        0.76,
        0.94,
    )
    iterations = max(18, min(42, width // 4 + height // 5))
    converged_at = iterations
    previous_max_delta = None

    has_surface_reservoir = any(any(row) for row in ocean_mask) or any(
        any(row) for row in permanent_ice_rows
    )
    if not liquid_water or not has_surface_reservoir:
        for y in range(height):
            latitude_abs = abs(y / max(1, height - 1) - 0.5) * 2.0
            for x in range(width):
                wind = wind_vector_rows[y][x]
                potential_evaporation[y][x] = _annual_reference_evaporation_mm(
                    temperatures[y][x],
                    latitude_abs,
                    pressure_bar,
                    wind[2],
                    0.05,
                )
        return {
            "temperature_rows_k": temperatures,
            "annual_precipitation_rows_mm": precipitation,
            "annual_potential_evaporation_rows_mm": potential_evaporation,
            "annual_evapotranspiration_rows_mm": actual_evaporation,
            "relative_humidity_rows": relative_humidity,
            "iterations": 0,
            "converged": True,
            "maximum_final_change": 0.0,
            "global_water_balance_error_fraction": 0.0,
        }

    for iteration in range(iterations):
        new_moisture = [[0.0 for _x in range(width)] for _y in range(height)]
        precipitation_target = [[0.0 for _x in range(width)] for _y in range(height)]
        max_delta = 0.0
        for y in range(height):
            latitude_abs = abs(y / max(1, height - 1) - 0.5) * 2.0
            for x in range(width):
                wind_x, wind_y, wind_speed = wind_vector_rows[y][x]
                upstream_x = int(round(x - wind_x)) % width
                upstream_y = max(0, min(height - 1, int(round(y - wind_y))))
                lateral = (
                    moisture[y][(x - 1) % width]
                    + moisture[y][(x + 1) % width]
                    + moisture[max(0, y - 1)][x]
                    + moisture[min(height - 1, y + 1)][x]
                ) * 0.25
                incoming = (
                    moisture[upstream_y][upstream_x] * 0.72
                    + lateral * 0.20
                    + moisture[y][x] * 0.08
                )
                humidity = _clamp(incoming / 1.8, 0.03, 0.98)
                pet = _annual_reference_evaporation_mm(
                    temperatures[y][x],
                    latitude_abs,
                    pressure_bar,
                    wind_speed,
                    humidity,
                )
                potential_evaporation[y][x] = pet
                ocean_source = (
                    _clamp(pet / 1800.0, 0.10, 1.65) * 0.62 * limited_factor
                    if ocean_mask[y][x]
                    else 0.0
                )
                ice_source = (
                    _clamp(pet / 2600.0, 0.0, 0.22) * 0.12
                    if permanent_ice_rows[y][x] and not ocean_mask[y][x]
                    else 0.0
                )
                recycling_source = (
                    actual_evaporation[y][x] / 4200.0 * 0.24
                    if not ocean_mask[y][x]
                    else 0.0
                )
                condensation = _clamp(condensation_rows[y][x], 0.01, 0.62)
                condensed = incoming * condensation
                retained = incoming * (1.0 - condensation) * transport_retention
                next_moisture = _clamp(
                    ocean_source + ice_source + recycling_source + retained,
                    0.0,
                    2.8,
                )
                new_moisture[y][x] = next_moisture
                precipitation_target[y][x] = min(5200.0, condensed * 5900.0)
                max_delta = max(max_delta, abs(next_moisture - moisture[y][x]))

        for y in range(height):
            latitude_abs = abs(y / max(1, height - 1) - 0.5) * 2.0
            for x in range(width):
                precipitation[y][x] = (
                    precipitation[y][x] * 0.62
                    + precipitation_target[y][x] * 0.38
                )
                relative_humidity[y][x] = _clamp(new_moisture[y][x] / 1.8, 0.03, 0.98)
                actual_evaporation[y][x] = (
                    min(
                        precipitation[y][x],
                        _budyko_evapotranspiration_mm(
                            precipitation[y][x],
                            potential_evaporation[y][x],
                        ),
                    )
                    if not ocean_mask[y][x]
                    else min(potential_evaporation[y][x] * 0.86, 4800.0)
                )
                hydrologic_cooling = min(7.5, precipitation[y][x] / 620.0)
                dry_surface_warming = (
                    (1.0 - relative_humidity[y][x]) * 2.2
                    if not ocean_mask[y][x]
                    else 0.0
                )
                target_temperature = (
                    float(base_temperature_rows[y][x])
                    - hydrologic_cooling
                    + dry_surface_warming
                )
                temperatures[y][x] = (
                    temperatures[y][x] * 0.72 + target_temperature * 0.28
                )
        moisture = new_moisture
        minimum_convergence_iteration = 5 if warm_started else 12
        if iteration >= minimum_convergence_iteration and max_delta < 0.0025:
            converged_at = iteration + 1
            previous_max_delta = max_delta
            break
        previous_max_delta = max_delta

    # A closed annual climatology cannot create or lose water. Rescale the
    # precipitation field to ocean/ice evaporation plus recycled land ET.
    area_weights = [
        max(0.02, math.cos((y / max(1, height - 1) - 0.5) * math.pi))
        for y in range(height)
    ]
    evaporation_total = sum(
        actual_evaporation[y][x] * area_weights[y]
        for y in range(height)
        for x in range(width)
    )
    precipitation_total = sum(
        precipitation[y][x] * area_weights[y]
        for y in range(height)
        for x in range(width)
    )
    if evaporation_total <= 1e-9:
        precipitation = [[0.0 for _x in range(width)] for _y in range(height)]
        water_balance_error = 0.0
    else:
        scale = _clamp(
            evaporation_total / max(1e-9, precipitation_total),
            0.30,
            2.40,
        )
        for y in range(height):
            for x in range(width):
                precipitation[y][x] = min(5200.0, precipitation[y][x] * scale)
                if not ocean_mask[y][x]:
                    actual_evaporation[y][x] = _budyko_evapotranspiration_mm(
                        precipitation[y][x],
                        potential_evaporation[y][x],
                    )
        balanced_precipitation_total = sum(
            precipitation[y][x] * area_weights[y]
            for y in range(height)
            for x in range(width)
        )
        water_balance_error = abs(
            balanced_precipitation_total - evaporation_total
        ) / max(1.0, evaporation_total)

    return {
        "temperature_rows_k": temperatures,
        "annual_precipitation_rows_mm": precipitation,
        "annual_potential_evaporation_rows_mm": potential_evaporation,
        "annual_evapotranspiration_rows_mm": actual_evaporation,
        "relative_humidity_rows": relative_humidity,
        "iterations": converged_at,
        "warm_started": warm_started,
        "converged": converged_at < iterations or (previous_max_delta or 0.0) < 0.01,
        "maximum_final_change": round(float(previous_max_delta or 0.0), 6),
        "global_water_balance_error_fraction": round(water_balance_error, 5),
    }


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
    # Nearest-source propagation is useful for filling the field but creates
    # Voronoi-like polygons and vertical seams where two coasts are equally
    # near. Diffuse the maritime reference temperature over land while
    # keeping actual sea-surface temperatures fixed.
    for _iteration in range(18):
        smoothed = [row[:] for row in result]
        for y in range(height):
            for x in range(width):
                if ocean_mask[y][x] or result[y][x] is None:
                    continue
                neighbours = [
                    result[ny][nx]
                    for nx, ny in (
                        ((x - 1) % width, y), ((x + 1) % width, y),
                        (x, max(0, y - 1)), (x, min(height - 1, y + 1)),
                    )
                    if result[ny][nx] is not None
                ]
                if neighbours:
                    smoothed[y][x] = result[y][x] * 0.42 + sum(neighbours) / len(neighbours) * 0.58
        result = smoothed
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


def _upwind_relief_context(rows, ocean_mask, x, y, wind_x, wind_y, span, steps=24):
    """Measure cumulative windward ascent and intervening rain-shadow relief."""
    height = len(rows)
    width = len(rows[0]) if height else 0
    if width <= 0:
        return {"windward_uplift": 0.0, "barrier_shadow": 0.0, "land_fetch": 0.0}
    current = float(rows[y][x] or 0.0)
    px, py = float(x), float(y)
    previous = current
    cumulative_ascent = 0.0
    maximum_barrier = current
    land_steps = 0
    for _step in range(1, steps + 1):
        px = (px - wind_x) % width
        py -= wind_y
        iy = int(round(py))
        if not 0 <= iy < height:
            break
        ix = int(round(px)) % width
        if ocean_mask[iy][ix]:
            break
        elevation = float(rows[iy][ix] or 0.0)
        # Walking upwind, a drop means air approaching the target had to rise.
        cumulative_ascent += max(0.0, previous - elevation)
        maximum_barrier = max(maximum_barrier, elevation)
        previous = elevation
        land_steps += 1
    return {
        "windward_uplift": _clamp(cumulative_ascent / max(1.0, span * 0.42)),
        "barrier_shadow": _clamp((maximum_barrier - current) / max(1.0, span * 0.32)),
        "land_fetch": _clamp(land_steps / max(1.0, steps)),
    }


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


def _classify_channel_regime(river, *, hydrology_cycle="active"):
    """Classify a routed channel from catchment water balance, not latitude.

    The drainage solver supplies possible flow paths. This second-stage
    hydrograph test decides whether a path carries perennial water, seasonal
    water, only event runoff, or too little water to form a meaningful
    channel. Catchment means are used so a large river may remain perennial
    while crossing a locally arid reach.
    """
    river = river if isinstance(river, dict) else {}
    catchment = (
        river.get("catchment_climate")
        if isinstance(river.get("catchment_climate"), dict)
        else {}
    )

    def metric(name, fallback=0.0):
        try:
            return max(0.0, float(catchment.get(name, fallback) or 0.0))
        except (TypeError, ValueError):
            return max(0.0, float(fallback or 0.0))

    runoff = max(
        0.0, float(river.get("catchment_mean_runoff_mm", 0.0) or 0.0)
    )
    precipitation = metric("mean_precipitation_mm", runoff)
    potential_evaporation = metric(
        "mean_potential_evaporation_mm", max(precipitation, 1.0)
    )
    recharge = metric("mean_groundwater_recharge_mm")
    snowmelt = metric("mean_snowmelt_runoff_mm")
    driest_month = metric(
        "mean_driest_month_precipitation_mm", precipitation / 24.0
    )
    wettest_month = metric(
        "mean_wettest_month_precipitation_mm", precipitation / 6.0
    )
    discharge = max(
        0.0, float(river.get("estimated_discharge_m3_s", 0.0) or 0.0)
    )
    moisture_index = precipitation / max(1.0, potential_evaporation)
    seasonal_pulse = (
        wettest_month >= max(3.0, driest_month * 1.8)
        or snowmelt >= 2.0
    )

    # A high absolute discharge alone does not make an arid flash-flood river
    # perennial: very large dry basins can briefly move enormous volumes.
    perennial = (
        runoff >= 180.0
        or (
            runoff >= 90.0
            and (recharge >= 8.0 or driest_month >= 8.0)
        )
        or (runoff >= 45.0 and discharge >= 20.0 and recharge >= 3.0)
    )
    intermittent = (
        runoff >= 12.0
        and (seasonal_pulse or recharge >= 2.0 or discharge >= 0.05)
    )
    ephemeral = (
        runoff >= 1.0
        and (wettest_month >= 2.0 or snowmelt >= 1.0)
    )

    # A declared limited cycle already reduces precipitation and runoff in the
    # climate solve. It additionally prevents marginal dry-season channels
    # from being promoted to perennial merely by coarse cell area.
    if hydrology_cycle == "limited" and perennial:
        perennial = runoff >= 210.0 or (
            runoff >= 110.0 and recharge >= 12.0 and driest_month >= 6.0
        )
        intermittent = intermittent or not perennial

    if perennial:
        regime = "perennial"
        flow_months = 12.0
        expression = "permanent_channel"
    elif intermittent:
        regime = "intermittent"
        flow_months = _clamp(
            2.0
            + math.sqrt(runoff / 120.0) * 5.5
            + min(1.5, recharge / 20.0),
            2.0,
            10.5,
        )
        expression = "seasonal_channel"
    elif ephemeral:
        regime = "ephemeral"
        flow_months = _clamp(
            0.15 + math.sqrt(runoff / 18.0) * 1.15,
            0.15,
            1.8,
        )
        expression = "wadi_or_arroyo"
    else:
        regime = "inactive"
        flow_months = 0.0
        expression = "no_resolved_channel"

    return {
        "flow_regime": regime,
        "geomorphic_expression": expression,
        "flow_months_per_year": round(flow_months, 2),
        "active_water_fraction": round(flow_months / 12.0, 4),
        "catchment_moisture_index": round(moisture_index, 4),
        "catchment_dryness_ratio": round(
            potential_evaporation / max(1.0, precipitation), 4
        ),
        "catchment_mean_runoff_mm": round(runoff, 3),
    }


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


def derive_water_cycle_model(
    terrain,
    heightmap,
    atmosphere=None,
    seed=None,
    planet_id="",
    parent_climate_model=None,
    previous_regional_model=None,
):
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
    hydrology_cycle = str(hydrology.get("cycle") or "none")
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
    ocean_fraction = sum(1 for row in ocean_mask for value in row if value) / max(1, height * width)
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
    sst_rows = ocean_circulation.get("sea_surface_temperature_rows_k") or [[None for _x in range(width)] for _y in range(height)]
    nearest_ocean_temperatures = _nearest_ocean_temperature_rows(ocean_mask, sst_rows)
    axial_tilt_deg = abs(float((seed or {}).get("axial_tilt_deg", 23.4) or 23.4))
    orbital_eccentricity = _orbital_eccentricity(seed)
    climate_mode = str((seed or {}).get("climate_mode") or "latitudinal_seasonal")
    synchronous_rotation = bool((seed or {}).get("synchronous_rotation")) or climate_mode == "tidally_locked"
    substellar_longitude_deg = float((seed or {}).get("substellar_longitude_deg", 0.0) or 0.0)
    heat_transport = _clamp(math.log1p(pressure_bar) / math.log(11.0), 0.08, 0.92)
    # Eccentric orbits have a changing stellar flux.  Ocean coverage and a
    # denser atmosphere store/transport heat and therefore damp the local
    # temperature swing; a dry, thin-atmosphere world retains much more of it.
    ocean_thermal_buffer = _clamp(ocean_fraction * 0.68 + heat_transport * 0.28, 0.0, 0.86)
    orbital_temperature_amplitude_k = min(
        95.0,
        surface_temp_k * orbital_eccentricity * 0.46 * (1.0 - ocean_thermal_buffer * 0.72),
    )
    climate_rows = []
    temperature_rows = []
    precipitation_rows = []
    seasonality_rows = []
    runoff_rows = []
    evapotranspiration_rows = []
    potential_evaporation_rows = []
    infiltration_rows = []
    groundwater_recharge_rows = []
    snowmelt_runoff_rows = []
    snow_fraction_rows = []
    seasonal_min_temperature_rows = []
    seasonal_max_temperature_rows = []
    wind_vector_rows = []
    condensation_rows = []
    permanent_ice_rows = []
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
        potential_evaporation_row = []
        infiltration_row = []
        groundwater_recharge_row = []
        snowmelt_runoff_row = []
        snow_fraction_row = []
        seasonal_min_temperature_row = []
        seasonal_max_temperature_row = []
        wind_vector_row = []
        condensation_row = []
        permanent_ice_row = []
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
            relief_context = _upwind_relief_context(
                rows, ocean_mask, x, y, wind_x, wind_y, span,
            )
            windward = max(0.0, wind_gradient) * 7.0 + relief_context["windward_uplift"] * 0.46
            leeward = max(0.0, -wind_gradient) * 8.5
            circulation_texture = _wave_noise(map_seed, "climate_circulation", nx, ny)
            texture = _climate_texture(map_seed, "climate_texture", nx, ny)
            # Large-scale circulation cells meander around their nominal
            # latitudes.  Keeping the astronomical latitude as the dominant
            # control while gently displacing the rain belts prevents climate
            # classes from becoming ruler-straight horizontal stripes.
            climate_band_latitude_abs = _clamp(
                latitude_abs
                + (circulation_texture - 0.5) * 0.10
                + texture * 0.025
            )
            rain_shadow = (
                max(0.0, elevation_norm - 0.50) * 0.34
                + leeward
                + relief_context["barrier_shadow"] * (0.52 + relief_context["land_fetch"] * 0.34)
            )
            wind_speed = _clamp(
                2.0
                + latitude_abs * 3.1
                + terrain["roughness"] * 1.5
                + (24.0 / max(4.0, rotation_hours)) * 0.7,
                0.4,
                16.0,
            )
            convective_lift = math.exp(
                -((climate_band_latitude_abs / 0.19) ** 2)
            )
            storm_lift = math.exp(
                -(((climate_band_latitude_abs - 0.58) / 0.20) ** 2)
            )
            condensation_efficiency = _clamp(
                0.018
                + convective_lift * 0.13
                + storm_lift * 0.06
                + windward * 0.25
                - rain_shadow * 0.11
                + circulation_texture * 0.018,
                0.01,
                0.62,
            )
            wind_vector_row.append([
                round(float(wind_x), 4),
                round(float(wind_y), 4),
                round(float(wind_speed), 3),
            ])
            condensation_row.append(round(condensation_efficiency, 5))
            permanent_ice_row.append(permanent_ice)
            temperature = surface_temp_k + 12.0 - latitude_abs * 48.0 - max(0.0, elevation) * 0.0062
            if synchronous_rotation:
                longitude_deg = nx * 360.0 - 180.0
                longitude_delta = math.radians(((longitude_deg - substellar_longitude_deg + 180.0) % 360.0) - 180.0)
                illumination = max(0.0, math.cos(longitude_delta)) * max(0.0, math.cos((ny - 0.5) * math.pi))
                day_night_contrast = 72.0 * (1.0 - heat_transport) + 12.0
                temperature += (illumination - 0.28) * day_night_contrast
            temperature += (
                texture * 2.6
                + (circulation_texture - 0.5) * 7.0
                - terrain["roughness"] * 3.5
            )
            if is_ocean and sst_rows[y][x] is not None:
                temperature = float(sst_rows[y][x])
            elif nearest_ocean_temperatures[y][x] is not None:
                maritime = shore * 0.58
                temperature += (float(nearest_ocean_temperatures[y][x]) - temperature) * maritime
            continentality = 1.0 - shore
            seasonality = 4.0 + latitude_abs * (axial_tilt_deg / 23.44) * (10.0 + continentality * 18.0)
            seasonality += orbital_temperature_amplitude_k * (0.48 + continentality * 0.52)
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
                parent_weight = _edge_locked_parent_weight(
                    inheritance_weights["temperature"], local_nx, local_ny
                )
                temperature = inherited_local_temperature * parent_weight + temperature * (1.0 - parent_weight)
            inherited_seasonality = _sample_inherited_rows(
                parent_climate_grid.get("temperature_seasonality_rows_k"), nx, ny, parent_source_uv,
            ) if isinstance(parent_climate_grid, dict) else None
            if inherited_seasonality is not None:
                parent_weight = _edge_locked_parent_weight(
                    inheritance_weights["seasonality"], local_nx, local_ny
                )
                seasonality = inherited_seasonality * parent_weight + seasonality * (1.0 - parent_weight)
            # Moisture and land-water fields are intentionally not classified
            # in this pass. They are solved iteratively after every cell's
            # energy, wind, topography, and reservoir state is available.
            climate_row.append("ocean" if is_ocean else "temperate_dry")
            temperature_row.append(round(temperature, 1))
            precipitation_row.append(0.0)
            seasonality_row.append(round(seasonality, 1))
            runoff_row.append(0.0)
            evapotranspiration_row.append(0.0)
            potential_evaporation_row.append(0.0)
            infiltration_row.append(0.0)
            groundwater_recharge_row.append(0.0)
            snowmelt_runoff_row.append(0.0)
            snow_fraction_row.append(0.0)
            seasonal_min_temperature_row.append(
                round(temperature - seasonality * 0.5, 1)
            )
            seasonal_max_temperature_row.append(
                round(temperature + seasonality * 0.5, 1)
            )
        climate_rows.append(climate_row)
        temperature_rows.append(temperature_row)
        precipitation_rows.append(precipitation_row)
        seasonality_rows.append(seasonality_row)
        runoff_rows.append(runoff_row)
        evapotranspiration_rows.append(evapotranspiration_row)
        potential_evaporation_rows.append(potential_evaporation_row)
        infiltration_rows.append(infiltration_row)
        groundwater_recharge_rows.append(groundwater_recharge_row)
        snowmelt_runoff_rows.append(snowmelt_runoff_row)
        snow_fraction_rows.append(snow_fraction_row)
        seasonal_min_temperature_rows.append(seasonal_min_temperature_row)
        seasonal_max_temperature_rows.append(seasonal_max_temperature_row)
        wind_vector_rows.append(wind_vector_row)
        condensation_rows.append(condensation_row)
        permanent_ice_rows.append(permanent_ice_row)

    coupled_climate = _solve_coupled_annual_climate(
        temperature_rows,
        seasonality_rows,
        wind_vector_rows,
        condensation_rows,
        ocean_mask,
        permanent_ice_rows,
        pressure_bar=pressure_bar,
        hydrology_cycle=hydrology_cycle,
        liquid_water=liquid_water,
        initial_climate=(
            (previous_regional_model.get("climate_grid") or {})
            if isinstance(previous_regional_model, dict)
            else None
        ),
    )
    temperature_rows = coupled_climate.get("temperature_rows_k") or temperature_rows
    precipitation_rows = (
        coupled_climate.get("annual_precipitation_rows_mm")
        or precipitation_rows
    )
    potential_evaporation_rows = (
        coupled_climate.get("annual_potential_evaporation_rows_mm")
        or potential_evaporation_rows
    )
    solver_evapotranspiration_rows = (
        coupled_climate.get("annual_evapotranspiration_rows_mm")
        or evapotranspiration_rows
    )
    relative_humidity_rows = (
        coupled_climate.get("relative_humidity_rows")
        or [[0.0 for _x in range(width)] for _y in range(height)]
    )

    # Rebuild the land water balance and classifications from the converged
    # annual climate. The first pass only established energy, terrain, and
    # atmospheric-transport fields.
    climate_rows = []
    koppen_rows = []
    runoff_rows = []
    evapotranspiration_rows = []
    infiltration_rows = []
    groundwater_recharge_rows = []
    snowmelt_runoff_rows = []
    snow_fraction_rows = []
    seasonal_min_temperature_rows = []
    seasonal_max_temperature_rows = []
    driest_month_precipitation_rows = []
    wettest_month_precipitation_rows = []
    summer_precipitation_fraction_rows = []
    zone_counts = {zone_id: 0 for zone_id in CLIMATE_ZONES}
    koppen_counts = {code: 0 for code in KOPPEN_CLASSES}

    for y, elevation_row in enumerate(rows):
        local_ny = y / max(1, height - 1)
        ny = source_v0 + (source_v1 - source_v0) * local_ny
        latitude_abs = abs(ny - 0.5) * 2.0
        climate_row = []
        koppen_row = []
        runoff_row = []
        evapotranspiration_row = []
        infiltration_row = []
        groundwater_recharge_row = []
        snowmelt_runoff_row = []
        snow_fraction_row = []
        seasonal_min_temperature_row = []
        seasonal_max_temperature_row = []
        driest_month_row = []
        wettest_month_row = []
        summer_fraction_row = []
        for x, elevation_value in enumerate(elevation_row):
            local_nx = x / max(1, width - 1)
            nx = source_u0 + (source_u1 - source_u0) * local_nx
            is_ocean = ocean_mask[y][x]
            terrain_metrics = _terrain_metrics(rows, x, y, span)
            shore = 1.0 - (
                shore_distances[y][x]
                if shore_distances
                and y < len(shore_distances)
                and x < len(shore_distances[y])
                else _nearest_ocean_distance(ocean_mask, x, y)
            )
            continentality = 1.0 - shore
            mean_temperature = float(temperature_rows[y][x])
            seasonality = float(seasonality_rows[y][x])
            if isinstance(parent_climate_grid, dict):
                inherited_temperature = _sample_inherited_rows(
                    parent_climate_grid.get("temperature_rows_k"),
                    nx,
                    ny,
                    parent_source_uv,
                )
                inherited_elevation = _sample_inherited_rows(
                    parent_climate_grid.get("elevation_rows"),
                    nx,
                    ny,
                    parent_source_uv,
                )
                if inherited_temperature is not None:
                    inherited_local_temperature = float(inherited_temperature)
                    if inherited_elevation is not None:
                        inherited_local_temperature -= (
                            float(elevation_value or 0.0)
                            - float(inherited_elevation)
                        ) * 0.0062
                    parent_temperature_weight = _edge_locked_parent_weight(
                        inheritance_weights["temperature"],
                        local_nx,
                        local_ny,
                    )
                    mean_temperature = (
                        inherited_local_temperature * parent_temperature_weight
                        + mean_temperature * (1.0 - parent_temperature_weight)
                    )
                    temperature_rows[y][x] = mean_temperature
            precipitation = max(0.0, float(precipitation_rows[y][x]))
            potential_evaporation = max(
                0.0, float(potential_evaporation_rows[y][x])
            )
            actual_evapotranspiration = (
                0.0
                if is_ocean
                else max(
                    0.0,
                    min(
                        precipitation,
                        float(solver_evapotranspiration_rows[y][x]),
                    ),
                )
            )
            circulation_texture = _wave_noise(
                map_seed, "precipitation_seasonality", nx, ny
            )
            summer_fraction = _clamp(
                0.50
                + shore * max(0.0, mean_temperature - 285.0) / 110.0
                + (circulation_texture - 0.5) * 0.16
                - max(0.0, latitude_abs - 0.62) * 0.16,
                0.14,
                0.86,
            )
            precipitation_seasonality = _clamp(
                0.12
                + continentality * 0.34
                + abs(summer_fraction - 0.5) * 0.82,
                0.08,
                0.92,
            )
            mean_monthly_precipitation = precipitation / 12.0
            driest_month = mean_monthly_precipitation * max(
                0.02, 1.0 - precipitation_seasonality * 1.15
            )
            wettest_month = mean_monthly_precipitation * (
                1.0 + precipitation_seasonality * 1.8
            )
            koppen_code = _koppen_geiger_class(
                mean_temperature,
                seasonality,
                precipitation,
                summer_fraction,
                precipitation_seasonality,
                is_ocean=is_ocean,
                permanent_ice=permanent_ice_rows[y][x],
            )
            zone_id = _koppen_zone_id(koppen_code)

            if isinstance(parent_climate_grid, dict):
                parent_weight = _edge_locked_parent_weight(
                    inheritance_weights["precipitation"], local_nx, local_ny
                )
                inherited_precipitation = _sample_inherited_rows(
                    parent_climate_grid.get("annual_precipitation_rows_mm"),
                    nx,
                    ny,
                    parent_source_uv,
                )
                if inherited_precipitation is not None and parent_weight > 0.0:
                    precipitation = (
                        float(inherited_precipitation) * parent_weight
                        + precipitation * (1.0 - parent_weight)
                    )
                    precipitation_rows[y][x] = precipitation
                    mean_monthly_precipitation = precipitation / 12.0
                    driest_month = mean_monthly_precipitation * max(
                        0.02, 1.0 - precipitation_seasonality * 1.15
                    )
                    wettest_month = mean_monthly_precipitation * (
                        1.0 + precipitation_seasonality * 1.8
                    )
                    koppen_code = _koppen_geiger_class(
                        mean_temperature,
                        seasonality,
                        precipitation,
                        summer_fraction,
                        precipitation_seasonality,
                        is_ocean=is_ocean,
                        permanent_ice=permanent_ice_rows[y][x],
                    )
                    zone_id = _koppen_zone_id(koppen_code)
                    actual_evapotranspiration = (
                        0.0
                        if is_ocean
                        else _budyko_evapotranspiration_mm(
                            precipitation,
                            potential_evaporation,
                        )
                    )
                if min(local_nx, 1.0 - local_nx, local_ny, 1.0 - local_ny) <= 1e-12:
                    inherited_zone = _sample_inherited_category(
                        parent_climate_grid.get("rows"),
                        nx,
                        ny,
                        parent_source_uv,
                    )
                    inherited_koppen = _sample_inherited_category(
                        parent_climate_grid.get("koppen_rows"),
                        nx,
                        ny,
                        parent_source_uv,
                    )
                    if inherited_zone:
                        zone_id = str(inherited_zone)
                    if inherited_koppen:
                        koppen_code = str(inherited_koppen)

            seasonal_min_temperature = mean_temperature - seasonality * 0.5
            seasonal_max_temperature = mean_temperature + seasonality * 0.5
            snow_fraction = 0.0 if is_ocean else _clamp(
                (273.15 - seasonal_min_temperature) / max(2.0, seasonality)
            )
            snowfall_storage = precipitation * snow_fraction * 0.78
            melt_fraction = _clamp(
                (seasonal_max_temperature - 268.15) / 18.0
            )
            snowmelt_release = snowfall_storage * melt_fraction
            liquid_input = max(
                0.0, precipitation - snowfall_storage + snowmelt_release
            )
            frozen_ground = (
                _clamp((273.15 - seasonal_min_temperature) / 24.0)
                * snow_fraction
            )
            wetness = _clamp(
                precipitation / max(1.0, precipitation + potential_evaporation)
            )
            infiltration_fraction = _clamp(
                0.48
                - terrain_metrics["slope"] * 0.24
                - frozen_ground * 0.26
                + (0.08 if wetness < 0.3 else 0.0),
                0.10,
                0.66,
            )
            actual_evapotranspiration = (
                0.0
                if is_ocean
                else min(actual_evapotranspiration, liquid_input * 0.94)
            )
            available_water = (
                0.0
                if is_ocean
                else max(0.0, liquid_input - actual_evapotranspiration)
            )
            infiltration = available_water * infiltration_fraction
            quickflow = available_water - infiltration
            baseflow_fraction = _clamp(
                0.10 + wetness * 0.24 - frozen_ground * 0.08,
                0.05,
                0.34,
            )
            baseflow = infiltration * baseflow_fraction
            groundwater_recharge = max(0.0, infiltration - baseflow)
            runoff = quickflow + baseflow

            climate_row.append(zone_id)
            koppen_row.append(koppen_code)
            runoff_row.append(round(runoff, 1))
            evapotranspiration_row.append(round(actual_evapotranspiration, 1))
            infiltration_row.append(round(infiltration, 1))
            groundwater_recharge_row.append(round(groundwater_recharge, 1))
            snowmelt_runoff_row.append(round(snowmelt_release, 1))
            snow_fraction_row.append(round(snow_fraction, 3))
            seasonal_min_temperature_row.append(
                round(seasonal_min_temperature, 1)
            )
            seasonal_max_temperature_row.append(
                round(seasonal_max_temperature, 1)
            )
            driest_month_row.append(round(driest_month, 1))
            wettest_month_row.append(round(wettest_month, 1))
            summer_fraction_row.append(round(summer_fraction, 3))
            zone_counts[zone_id] = zone_counts.get(zone_id, 0) + 1
            koppen_counts[koppen_code] = koppen_counts.get(koppen_code, 0) + 1
        climate_rows.append(climate_row)
        koppen_rows.append(koppen_row)
        runoff_rows.append(runoff_row)
        evapotranspiration_rows.append(evapotranspiration_row)
        infiltration_rows.append(infiltration_row)
        groundwater_recharge_rows.append(groundwater_recharge_row)
        snowmelt_runoff_rows.append(snowmelt_runoff_row)
        snow_fraction_rows.append(snow_fraction_row)
        seasonal_min_temperature_rows.append(seasonal_min_temperature_row)
        seasonal_max_temperature_rows.append(seasonal_max_temperature_row)
        driest_month_precipitation_rows.append(driest_month_row)
        wettest_month_precipitation_rows.append(wettest_month_row)
        summer_precipitation_fraction_rows.append(summer_fraction_row)

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
    koppen_classes = []
    for code, count in sorted(
        koppen_counts.items(), key=lambda item: (-item[1], item[0])
    ):
        if count <= 0:
            continue
        spec = KOPPEN_CLASSES.get(code) or KOPPEN_CLASSES["BWh"]
        koppen_classes.append({
            "id": code,
            "label": spec["label"],
            "zone_id": spec["zone_id"],
            "color": list(spec["color"]),
            "fraction": round(count / total_cells, 3),
        })

    region_width_m = float(heightmap.get("region_width_m") or 0.0)
    region_height_m = float(heightmap.get("region_height_m") or 0.0)
    represented_area_m2 = (
        region_width_m * region_height_m
        if region_width_m > 0.0 and region_height_m > 0.0
        else circumference_m * circumference_m / math.pi
    )
    drainage_network = derive_drainage_network(
        rows,
        ocean_mask,
        runoff_rows,
        wrap_x=bool(heightmap.get("wrap_x", True)),
        detail_level=detail_level,
        precipitation_rows=precipitation_rows,
        potential_evaporation_rows=potential_evaporation_rows,
        groundwater_recharge_rows=groundwater_recharge_rows,
        snowmelt_runoff_rows=snowmelt_runoff_rows,
        driest_month_precipitation_rows=driest_month_precipitation_rows,
        wettest_month_precipitation_rows=wettest_month_precipitation_rows,
        represented_area_m2=represented_area_m2,
    ) if drainage_enabled else {"status": "inactive", "rivers": [], "lakes": [], "drainage_basins": []}
    if (
        drainage_enabled
        and isinstance(parent_climate_model, dict)
        and not bool(heightmap.get("wrap_x", True))
    ):
        drainage_network = inherit_parent_drainage(
            parent_climate_model.get("drainage_network_model"),
            drainage_network,
            heightmap.get("source_uv_bounds") or {},
            (parent_climate_model.get("climate_grid") or {}).get(
                "source_uv_bounds"
            )
            or {},
        )
    candidate_rivers = list(drainage_network.get("rivers") or [])
    mean_cell_area_m2 = represented_area_m2 / max(1, width * height)
    seconds_per_year = 365.2425 * 24.0 * 3600.0
    active_rivers = []
    ephemeral_channels = []
    inactive_channel_count = 0
    for river in candidate_rivers:
        length_m = _path_length_m(
            river.get("points") or [],
            region_width_m or circumference_m,
            region_height_m or circumference_m * 0.5,
            wrap_x=bool(heightmap.get("wrap_x", True)),
        )
        inherited_discharge = (
            river.get("estimated_discharge_m3_s")
            if river.get("inherited_from_parent")
            else None
        )
        discharge_m3_s = (
            max(0.0, float(inherited_discharge or 0.0))
            if inherited_discharge is not None
            else (
                max(
                    0.0,
                    float(
                        river.get("runoff_accumulation_mm_cells", 0.0) or 0.0
                    ),
                )
                * mean_cell_area_m2
                * 0.001
                / seconds_per_year
            )
        )
        average_width_m, mouth_width_m = _river_widths_m(
            river.get("flow", 0.0), length_m, ocean_fraction, discharge_m3_s=discharge_m3_s,
        )
        river.update({
            "length_m": round(length_m, 1),
            "length_km": round(length_m / 1000.0, 1),
            "average_width_m": average_width_m,
            "mouth_width_m": mouth_width_m,
            "estimated_discharge_m3_s": round(discharge_m3_s, 1),
            "catchment_area_km2": round(
                max(
                    0.0,
                    float(
                        river.get(
                            "catchment_area_weighted_cells",
                            river.get("catchment_cell_count", 0.0),
                        )
                        or 0.0
                    ),
                )
                * mean_cell_area_m2
                / 1_000_000.0,
                2,
            ),
        })
        if river.get("inherited_from_parent") and river.get("flow_regime") in {
            "perennial", "intermittent", "ephemeral", "inactive",
        }:
            regime = str(river["flow_regime"])
        else:
            river.update(
                _classify_channel_regime(
                    river, hydrology_cycle=hydrology_cycle
                )
            )
            regime = str(river["flow_regime"])
        if regime in {"perennial", "intermittent"}:
            active_rivers.append(river)
        elif regime == "ephemeral":
            ephemeral_channels.append(river)
        else:
            inactive_channel_count += 1

    if hydrology_cycle == "limited":
        channel_limit = min(18, 6 + max(0, int(detail_level or 0)) * 3)
        active_rivers = sorted(
            active_rivers,
            key=lambda river: (
                river.get("flow_regime") == "perennial",
                float(river.get("estimated_discharge_m3_s", 0.0) or 0.0),
                float(river.get("flow", 0.0) or 0.0),
            ),
            reverse=True,
        )[:channel_limit]
        ephemeral_channels = sorted(
            ephemeral_channels,
            key=lambda river: float(
                river.get("runoff_accumulation_mm_cells", 0.0) or 0.0
            ),
            reverse=True,
        )[:channel_limit]
        drainage_network["lakes"] = list(
            drainage_network.get("lakes") or []
        )[:max(2, channel_limit // 2)]
        drainage_network["hydrology_character"] = (
            "episodic_sparse_channels"
            if active_rivers or ephemeral_channels
            else "arid_without_resolved_channels"
        )

    rivers = active_rivers
    drainage_network["rivers"] = rivers
    drainage_network["ephemeral_channels"] = ephemeral_channels
    drainage_network["inactive_channel_candidate_count"] = (
        inactive_channel_count
    )
    drainage_network["channel_regime_counts"] = {
        "perennial": sum(
            river.get("flow_regime") == "perennial" for river in rivers
        ),
        "intermittent": sum(
            river.get("flow_regime") == "intermittent" for river in rivers
        ),
        "ephemeral": len(ephemeral_channels),
        "inactive": inactive_channel_count,
    }
    drainage_network["river_segment_count"] = len(rivers)
    drainage_network["ephemeral_channel_count"] = len(ephemeral_channels)
    active_ids = {str(river.get("id")) for river in rivers}
    drainage_network["delta_candidate_river_ids"] = [
        river.get("id")
        for river in rivers
        if river.get("mouth") in {"ocean", "lake"}
    ]
    drainage_network["deltas"] = [
        delta
        for delta in drainage_network.get("deltas") or []
        if str(delta.get("river_id")) in active_ids
    ]
    drainage_network["delta_count"] = len(drainage_network["deltas"])
    retained_lakes = list(drainage_network.get("lakes") or [])
    drainage_network["lake_count"] = len(retained_lakes)
    drainage_network["lake_area_fraction"] = round(
        sum(
            float(lake.get("area_fraction", 0.0) or 0.0)
            for lake in retained_lakes
        ),
        6,
    )
    drainage_network["largest_lake_area_fraction"] = round(
        max(
            (
                float(lake.get("area_fraction", 0.0) or 0.0)
                for lake in retained_lakes
            ),
            default=0.0,
        ),
        6,
    )
    drainage_network["endorheic_lake_fraction"] = round(
        sum(bool(lake.get("endorheic")) for lake in retained_lakes)
        / max(1, len(retained_lakes)),
        3,
    )
    drainage_network["lake_outlet_fraction"] = round(
        sum(not lake.get("endorheic") for lake in retained_lakes)
        / max(1, len(retained_lakes)),
        3,
    )

    return {
        "status": "water_cycle_seeded",
        "model_version": WATER_CYCLE_MODEL_VERSION,
        "climate_hierarchy": {
            "level": 2,
            "method": "iterative_annual_energy_moisture_balance_with_koppen_geiger_normals",
            "resolved_feedbacks": [
                "ice_albedo",
                "ocean_thermal_inertia",
                "seasonality",
                "prevailing_wind_moisture_transport",
                "orographic_rain_shadow",
                "penman_monteith_reference_evaporation",
                "budyko_land_water_balance",
                "hydrologic_temperature_feedback",
            ],
            "deferred_tier_3": ["full_general_circulation", "spectral_radiative_transfer", "dynamic_ocean_coupling"],
        },
        "climate_solver": {
            "method": "damped_iterative_annual_energy_moisture_balance",
            "iterations": int(coupled_climate.get("iterations", 0) or 0),
            "warm_started_from_previous_regional_state": bool(
                coupled_climate.get("warm_started")
            ),
            "converged": bool(coupled_climate.get("converged")),
            "maximum_final_change": float(
                coupled_climate.get("maximum_final_change", 0.0) or 0.0
            ),
            "global_water_balance_error_fraction": float(
                coupled_climate.get(
                    "global_water_balance_error_fraction", 0.0
                )
                or 0.0
            ),
        },
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
            "enabled": bool((seed or {}).get("seasonal_cycle")) or axial_tilt_deg >= 28.0 or orbital_eccentricity >= 0.03,
            "axial_tilt_deg": round(axial_tilt_deg, 2),
            "orbital_eccentricity": round(orbital_eccentricity, 5),
            "orbital_temperature_amplitude_k": round(orbital_temperature_amplitude_k, 2),
            "ocean_thermal_buffer": round(ocean_thermal_buffer, 3),
            "orbital_phases": [
                {
                    "phase": index,
                    "solar_longitude_deg": index * 45,
                    "global_temperature_anomaly_k": round(
                        math.sin(math.radians(index * 45)) * min(24.0, axial_tilt_deg * 0.22)
                        + math.cos(math.radians(index * 45)) * orbital_temperature_amplitude_k,
                        2,
                    ),
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
            "koppen_rows": koppen_rows,
            "elevation_rows": rows,
            "shore_distance_rows": shore_distances,
            "temperature_rows_k": temperature_rows,
            "annual_precipitation_rows_mm": precipitation_rows,
            "relative_humidity_rows": relative_humidity_rows,
            "prevailing_wind_rows": wind_vector_rows,
            "condensation_efficiency_rows": condensation_rows,
            "temperature_seasonality_rows_k": seasonality_rows,
            "seasonal_min_temperature_rows_k": seasonal_min_temperature_rows,
            "seasonal_max_temperature_rows_k": seasonal_max_temperature_rows,
            "driest_month_precipitation_rows_mm": driest_month_precipitation_rows,
            "wettest_month_precipitation_rows_mm": wettest_month_precipitation_rows,
            "summer_precipitation_fraction_rows": summer_precipitation_fraction_rows,
            "annual_runoff_rows_mm": runoff_rows,
            "annual_evapotranspiration_rows_mm": evapotranspiration_rows,
            "annual_potential_evaporation_rows_mm": potential_evaporation_rows,
            "annual_infiltration_rows_mm": infiltration_rows,
            "annual_groundwater_recharge_rows_mm": groundwater_recharge_rows,
            "annual_snowmelt_release_rows_mm": snowmelt_runoff_rows,
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
        "lake_outlet_fraction": float(drainage_network.get("lake_outlet_fraction", 0.0) or 0.0),
        "deltas": drainage_network.get("deltas") or [],
        "delta_count": int(drainage_network.get("delta_count", 0) or 0),
        "climate_zones": climate_zones,
        "koppen_classes": koppen_classes,
        "rivers": rivers,
        "river_count": len(rivers),
        "runoff_summary": {
            "target_ocean_fraction": round(target_ocean, 3),
            "realized_ocean_fraction": round(ocean_fraction, 3),
            "ocean_coverage_source": (
                "equivalent_water_inventory_and_generated_hypsometry"
                if float(heightmap.get("equivalent_global_water_depth_m", 0.0) or 0.0) > 0.0
                else "authored_coverage_target"
                if target_ocean > 0.0
                else "dry_surface"
            ),
            "surface_pressure_bar": round(pressure_bar, 4),
            "mean_temperature_k": round(
                sum(
                    float(temperature_rows[y][x])
                    for y in range(height)
                    for x in range(width)
                )
                / max(1, width * height),
                1,
            ),
            "mean_annual_precipitation_mm": round(
                sum(
                    float(precipitation_rows[y][x])
                    for y in range(height)
                    for x in range(width)
                )
                / max(1, width * height),
                1,
            ),
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
