import math
from functools import lru_cache

from simulations.world_gen.map_seed import resolved_map_seed, seed_range
from simulations.world_gen.terrain_seed import (
    PLANETARY_CANVAS_HEIGHT_PX,
    PLANETARY_CANVAS_WIDTH_PX,
)

_NOISE_CORNER_CACHE = {}


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


def _smoothstep(value):
    value = _clamp(value, 0.0, 1.0)
    return value * value * (3.0 - 2.0 * value)


def _lerp(a, b, t):
    return float(a) * (1.0 - t) + float(b) * t


def _value_noise(map_seed, key, nx, ny, cells_x, cells_y):
    cells_x = max(1, int(cells_x or 1))
    cells_y = max(1, int(cells_y or 1))
    gx = float(nx) * cells_x
    gy = _clamp(float(ny), 0.0, 1.0) * cells_y
    x0 = math.floor(gx)
    y0 = math.floor(gy)
    tx = _smoothstep(gx - x0)
    ty = _smoothstep(gy - y0)
    y0 = max(0, min(cells_y, y0))
    y1 = max(0, min(cells_y, y0 + 1))
    x1 = x0 + 1

    def corner(ix, iy):
        wrapped_x = int(ix) % cells_x
        clamped_y = max(0, min(cells_y, int(iy)))
        cache_key = (map_seed, key, cells_x, cells_y, wrapped_x, clamped_y)
        cached = _NOISE_CORNER_CACHE.get(cache_key)
        if cached is not None:
            return cached
        value = seed_range(map_seed, f"{key}:{cells_x}:{cells_y}:{wrapped_x}:{clamped_y}", -1.0, 1.0)
        if len(_NOISE_CORNER_CACHE) > 80_000:
            _NOISE_CORNER_CACHE.clear()
        _NOISE_CORNER_CACHE[cache_key] = value
        return value

    top = _lerp(corner(x0, y0), corner(x1, y0), tx)
    bottom = _lerp(corner(x0, y1), corner(x1, y1), tx)
    return _lerp(top, bottom, ty)


def _fbm_noise(map_seed, key, nx, ny, base_cells=4, octaves=4, lacunarity=2.0, gain=0.52):
    total = 0.0
    amplitude = 1.0
    amplitude_sum = 0.0
    cells = max(1, int(base_cells or 1))
    for octave in range(max(1, int(octaves or 1))):
        total += _value_noise(map_seed, f"{key}:octave_{octave}", nx, ny, cells, max(1, cells // 2)) * amplitude
        amplitude_sum += amplitude
        amplitude *= gain
        cells = max(cells + 1, int(cells * lacunarity))
    if amplitude_sum <= 0.0:
        return 0.0
    return _clamp(total / amplitude_sum, -1.0, 1.0)


@lru_cache(maxsize=48)
def _continental_process_model(map_seed):
    """Build ancient crustal provinces once; sampling them stays inexpensive."""
    seed = str(map_seed or "")
    assembly_count = int(round(seed_range(seed, "crust:assembly_count", 5.0, 7.0)))
    cratons, sutures, rifts, basins = [], [], [], []
    for assembly in range(assembly_count):
        key = f"crust:assembly_{assembly}"
        cx = seed_range(seed, f"{key}:x", 0.0, 1.0)
        cy = seed_range(seed, f"{key}:y", 0.14, 0.86)
        bearing = seed_range(seed, f"{key}:bearing", 0.0, math.tau)
        craton_count = int(round(seed_range(seed, f"{key}:cratons", 3.0, 5.0)))
        local = []
        for index in range(craton_count):
            along = (index - (craton_count - 1) * 0.5) * seed_range(seed, f"{key}:spacing", 0.045, 0.085)
            across = seed_range(seed, f"{key}:across_{index}", -0.045, 0.045)
            px = (cx + math.cos(bearing) * along - math.sin(bearing) * across) % 1.0
            py = _clamp(cy + math.sin(bearing) * along + math.cos(bearing) * across, 0.08, 0.92)
            width = seed_range(seed, f"{key}:w_{index}", 0.045, 0.105)
            height = seed_range(seed, f"{key}:h_{index}", 0.040, 0.095)
            angle = bearing + seed_range(seed, f"{key}:angle_{index}", -0.65, 0.65)
            item = (px, py, width, height, angle, seed_range(seed, f"{key}:strength_{index}", 0.78, 1.08))
            cratons.append(item)
            local.append(item)
            if index:
                sutures.append((local[index - 1][0], local[index - 1][1], px, py, seed_range(seed, f"{key}:suture_{index}", 0.012, 0.026)))
        rift_angle = bearing + seed_range(seed, f"{key}:rift_angle", 1.05, 2.05)
        rift_half = seed_range(seed, f"{key}:rift_length", 0.07, 0.16)
        rifts.append(((cx - math.cos(rift_angle) * rift_half) % 1.0, cy - math.sin(rift_angle) * rift_half,
                      (cx + math.cos(rift_angle) * rift_half) % 1.0, cy + math.sin(rift_angle) * rift_half,
                      seed_range(seed, f"{key}:rift_width", 0.008, 0.018)))
        for index in range(2):
            basin_angle = seed_range(seed, f"{key}:basin_angle_{index}", 0.0, math.tau)
            basin_radius = seed_range(seed, f"{key}:basin_offset_{index}", 0.025, 0.080)
            basins.append(((cx + math.cos(basin_angle) * basin_radius) % 1.0,
                           _clamp(cy + math.sin(basin_angle) * basin_radius, 0.08, 0.92),
                           seed_range(seed, f"{key}:basin_w_{index}", 0.025, 0.060),
                           seed_range(seed, f"{key}:basin_h_{index}", 0.018, 0.045),
                           seed_range(seed, f"{key}:basin_depth_{index}", 0.45, 1.0)))

    # Oceanic hotspots move with their plates, producing age-progressive chains.
    island_chains = []
    for chain in range(6):
        key = f"crust:hotspot_{chain}"
        x = seed_range(seed, f"{key}:x", 0.0, 1.0)
        y = seed_range(seed, f"{key}:y", 0.16, 0.84)
        angle = seed_range(seed, f"{key}:motion", 0.0, math.tau)
        count = int(round(seed_range(seed, f"{key}:count", 4.0, 8.0)))
        spacing = seed_range(seed, f"{key}:spacing", 0.010, 0.024)
        chain_points = []
        for index in range(count):
            age_scale = 1.0 - index / max(1, count) * 0.58
            chain_points.append(((x + math.cos(angle) * spacing * index) % 1.0,
                                 _clamp(y + math.sin(angle) * spacing * index, 0.06, 0.94),
                                 seed_range(seed, f"{key}:radius_{index}", 0.005, 0.013), age_scale))
        island_chains.append(tuple(chain_points))
    return {"cratons": tuple(cratons), "sutures": tuple(sutures), "rifts": tuple(rifts),
            "basins": tuple(basins), "island_chains": tuple(island_chains)}


def _continent_signal(nx, ny, map_seed=""):
    """Continental crust assembled from cratons, terranes, sutures and rifts."""
    model = _continental_process_model(str(map_seed or ""))
    warp_x = _fbm_noise(map_seed, "continental_warp_x", nx, ny, base_cells=4, octaves=3) * 0.035
    warp_y = _fbm_noise(map_seed, "continental_warp_y", nx, ny, base_cells=4, octaves=3) * 0.025
    wx, wy = (nx + warp_x) % 1.0, _clamp(ny + warp_y, 0.0, 1.0)
    lithosphere = 0.0
    for cx, cy, width, height, angle, strength in model["cratons"]:
        dx, dy = _wrapped_delta(wx, cx), wy - cy
        rx = dx * math.cos(angle) - dy * math.sin(angle)
        ry = dx * math.sin(angle) + dy * math.cos(angle)
        distance = (rx / width) ** 2 + (ry / height) ** 2
        lithosphere = max(lithosphere, math.exp(-(distance * 0.72)) * strength)
    signal = -0.56 + lithosphere * 0.92
    for x1, y1, x2, y2, width in model["sutures"]:
        distance = _wrapped_point_segment_distance(wx, wy, x1, y1, x2, y2)
        signal += 0.13 * math.exp(-((distance / width) ** 2))
    for x1, y1, x2, y2, width in model["rifts"]:
        distance = _wrapped_point_segment_distance(wx, wy, x1, y1, x2, y2)
        signal -= 0.22 * math.exp(-((distance / width) ** 2)) * _smoothstep(lithosphere)

    terrane = _fbm_noise(map_seed, "continental_terrane_texture", wx, wy, base_cells=10, octaves=4)
    shore = _fbm_noise(map_seed, "continental_eroded_margins", wx, wy, base_cells=28, octaves=3, gain=0.48)
    shore_band = math.exp(-(((signal + 0.08) / 0.24) ** 2))
    signal += terrane * 0.09 + shore * (0.06 + shore_band * 0.19)
    latitude_taper = 1.0 - max(0.0, abs(wy - 0.5) * 2.0 - 0.84) * 1.15
    return _clamp(signal * max(0.42, latitude_taper), -0.9, 1.0)


def _intracontinental_basin_signal(nx, ny, map_seed=""):
    value = 0.0
    for cx, cy, width, height, depth in _continental_process_model(str(map_seed or ""))["basins"]:
        distance = (_wrapped_delta(nx, cx) / width) ** 2 + ((ny - cy) / height) ** 2
        value = max(value, math.exp(-distance) * depth)
    return value


def _oceanic_island_signal(nx, ny, map_seed=""):
    value = 0.0
    for chain in _continental_process_model(str(map_seed or ""))["island_chains"]:
        for cx, cy, radius, age_scale in chain:
            distance = math.hypot(_wrapped_delta(nx, cx), ny - cy) / radius
            if distance < 2.2:
                value = max(value, math.exp(-(distance ** 2)) * age_scale)
    return value


def _continental_mask(signal):
    return _smoothstep((float(signal) + 0.08) / 0.42)


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


def _representative_boundary_segments(tectonic_model, max_segments=96):
    segments = [
        segment
        for segment in (tectonic_model.get("boundary_segments") or [])
        if isinstance(segment, dict)
    ]
    if len(segments) <= max_segments:
        return segments

    by_kind = {}
    for segment in segments:
        by_kind.setdefault(segment.get("kind", "passive"), []).append(segment)

    kind_priority = ["collision", "subduction", "divergent", "transform", "passive"]
    selected = []
    active_kind_count = max(1, sum(1 for items in by_kind.values() if items))
    base_limit = max(8, int(max_segments / active_kind_count))
    for kind in kind_priority:
        items = by_kind.get(kind) or []
        if not items:
            continue
        kind_limit = base_limit
        if kind in {"collision", "subduction", "divergent"}:
            kind_limit = int(base_limit * 1.35)
        kind_limit = max(6, min(len(items), kind_limit))
        stride = max(1, len(items) / kind_limit)
        for index in range(kind_limit):
            selected.append(items[min(len(items) - 1, int(index * stride))])
            if len(selected) >= max_segments:
                return selected

    if len(selected) < max_segments:
        remaining = [segment for segment in segments if segment not in selected]
        stride = max(1, len(remaining) / max(1, max_segments - len(selected)))
        for index in range(max_segments - len(selected)):
            if not remaining:
                break
            selected.append(remaining[min(len(remaining) - 1, int(index * stride))])
    return selected[:max_segments]


def _heightmap_tectonic_model(tectonic_model):
    if not isinstance(tectonic_model, dict):
        return tectonic_model
    segments = _representative_boundary_segments(tectonic_model)
    if segments is tectonic_model.get("boundary_segments"):
        return tectonic_model
    sampled = dict(tectonic_model)
    sampled["boundary_segments"] = segments
    sampled["heightmap_boundary_segment_count"] = len(segments)
    sampled["original_boundary_segment_count"] = len(tectonic_model.get("boundary_segments") or [])
    return sampled


def _tectonic_height_m(nx, ny, terrain, tectonic_model):
    plates = tectonic_model.get("plates") or []
    if not plates:
        return None
    base, plate = _blended_plate_base_height_m(nx, ny, plates)
    plate_type = plate.get("plate_type") if isinstance(plate, dict) else "mixed"
    plate_continentality = float(plate.get("continentality", 0.5) or 0.5) if isinstance(plate, dict) else 0.5

    longitude = nx * math.tau
    latitude = (ny - 0.5) * math.pi
    map_seed = str(tectonic_model.get("map_seed") or terrain.get("map_seed") or "")
    continent_signal = _continent_signal(nx, ny, map_seed=map_seed)
    continent_mask = _continental_mask(continent_signal + (plate_continentality - 0.5) * 0.48)
    rugged_noise = _fbm_noise(map_seed, "rugged_relief", nx, ny, base_cells=18, octaves=4)
    shield_noise = _fbm_noise(map_seed, "cratonic_shields", nx, ny, base_cells=8, octaves=3)
    basin_noise = _fbm_noise(map_seed, "sedimentary_basins", nx, ny, base_cells=11, octaves=3)
    intracontinental_basin = _intracontinental_basin_signal(nx, ny, map_seed=map_seed)
    island_signal = _oceanic_island_signal(nx, ny, map_seed=map_seed)
    broad_relief = (
        360.0 * math.sin(longitude * seed_range(map_seed, "tectonic_broad_freq_a", 0.85, 1.45) + latitude * 0.75)
        + 220.0 * math.cos(longitude * seed_range(map_seed, "tectonic_broad_freq_b", 1.65, 2.55) - latitude)
        + 95.0 * math.sin(longitude * 4.1 + latitude * 1.7)
    )
    height = base + broad_relief
    height += continent_mask * (780.0 + shield_noise * 360.0)
    height += (1.0 - continent_mask) * (-660.0 + basin_noise * 220.0)
    # Subsidence within stable crust creates sedimentary and endorheic basins.
    height -= intracontinental_basin * continent_mask * 1150.0
    if plate_type == "oceanic":
        height -= 520.0
    elif plate_type == "continental":
        height += 280.0

    effects = tectonic_model.get("surface_effects") if isinstance(tectonic_model.get("surface_effects"), dict) else {}
    uplift_gain = 0.7 + float(effects.get("orogenic_uplift", 0.0) or 0.0) * 0.9
    basin_gain = 0.65 + float(effects.get("ocean_basin_opening", 0.0) or 0.0) * 0.75
    erosion = float(effects.get("erosion_progress", 0.0) or 0.0)
    boundary_lookup = _boundary_kind_lookup(tectonic_model)
    convergent_influence = 0.0
    divergent_influence = 0.0
    trench_influence = 0.0
    transform_influence = 0.0

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
            convergent_influence = max(convergent_influence, influence)
        elif kind == "subduction":
            height += 3300.0 * uplift_gain * influence
            height -= 1800.0 * influence * (1.0 if plate_type == "oceanic" else 0.3)
            # Discrete volcanoes make island arcs instead of continuous walls.
            arc_beads = max(0.0, math.sin((nx * 71.0 + ny * 43.0) * math.tau)) ** 5
            height += 2600.0 * influence * arc_beads * (1.0 if plate_type == "oceanic" else 0.32)
            convergent_influence = max(convergent_influence, influence)
            trench_influence = max(trench_influence, influence)
        elif kind == "divergent":
            height -= 2100.0 * basin_gain * influence
            divergent_influence = max(divergent_influence, influence)
        elif kind == "transform":
            height += 650.0 * influence
            transform_influence = max(transform_influence, influence)

    continental_shelf = math.exp(-(((continent_signal + 0.10) / 0.18) ** 2))
    passive_margin = continental_shelf * max(0.0, 1.0 - convergent_influence - divergent_influence * 0.7)
    height += passive_margin * 520.0
    height -= (1.0 - continent_mask) * max(0.0, 1.0 - divergent_influence) * 380.0
    height += divergent_influence * (950.0 if plate_type == "oceanic" else -380.0)
    height -= trench_influence * (1150.0 + (1.0 - continent_mask) * 900.0)
    height += transform_influence * rugged_noise * 520.0
    height += rugged_noise * (180.0 + continent_mask * 380.0 + convergent_influence * 950.0)
    # Mantle plumes leave volcanic chains primarily on oceanic lithosphere.
    height += island_signal * (1.0 - continent_mask) * (4100.0 if plate_type == "oceanic" else 2300.0)

    if height > 1000.0:
        height *= 1.0 - min(0.34, erosion * 0.24)
    return height


def _crater_spatial_index(crater_model, bins_x=32, bins_y=16):
    craters = crater_model.get("craters") or []
    radius_m = max(1.0, float(crater_model.get("radius_m", 1.0) or 1.0))
    bins = {}
    max_angular_radius = 0.0
    for crater in craters:
        bx = int(float(crater.get("x", 0.0) or 0.0) * bins_x) % bins_x
        by = max(0, min(bins_y - 1, int(float(crater.get("y", 0.0) or 0.0) * bins_y)))
        bins.setdefault((bx, by), []).append(crater)
        angular_radius = float(crater.get("diameter_km", 0.0) or 0.0) * 500.0 / radius_m
        max_angular_radius = max(max_angular_radius, angular_radius)
    return {
        "bins": bins,
        "bins_x": bins_x,
        "bins_y": bins_y,
        "neighbor_x": min(bins_x // 2, max(1, int(math.ceil(max_angular_radius * 1.85 / math.tau * bins_x)) + 1)),
        "neighbor_y": min(bins_y, max(1, int(math.ceil(max_angular_radius * 1.85 / math.pi * bins_y)) + 1)),
    }


def _nearby_craters(nx, ny, crater_model, spatial_index=None):
    if not isinstance(spatial_index, dict):
        return crater_model.get("craters") or []
    bins_x = spatial_index["bins_x"]
    bins_y = spatial_index["bins_y"]
    bx = int(float(nx) * bins_x) % bins_x
    by = max(0, min(bins_y - 1, int(float(ny) * bins_y)))
    candidates = []
    visited = set()
    for dy in range(-spatial_index["neighbor_y"], spatial_index["neighbor_y"] + 1):
        candidate_y = max(0, min(bins_y - 1, by + dy))
        for dx in range(-spatial_index["neighbor_x"], spatial_index["neighbor_x"] + 1):
            key = ((bx + dx) % bins_x, candidate_y)
            if key in visited:
                continue
            visited.add(key)
            candidates.extend(spatial_index["bins"].get(key, ()))
    return candidates


def _crater_height_adjustment_m(nx, ny, crater_model, spatial_index=None):
    adjustment = 0.0
    radius_m = max(1.0, float(crater_model.get("radius_m", 1.0) or 1.0))
    latitude = (0.5 - float(ny)) * math.pi
    for crater in _nearby_craters(nx, ny, crater_model, spatial_index):
        cx = float(crater.get("x", 0.0) or 0.0)
        cy = float(crater.get("y", 0.0) or 0.0)
        crater_latitude = (0.5 - cy) * math.pi
        delta_latitude = latitude - crater_latitude
        delta_longitude = _wrapped_delta(nx, cx) * math.tau
        angular_distance = math.hypot(
            delta_latitude,
            math.cos((latitude + crater_latitude) * 0.5) * delta_longitude,
        )
        angular_radius = max(1e-6, float(crater.get("diameter_km", 1.0) or 1.0) * 500.0 / radius_m)
        normalized_distance = angular_distance / angular_radius
        if normalized_distance > 1.8:
            continue
        depth_m = float(crater.get("depth_m", 0.0) or 0.0)
        rim_height_m = float(crater.get("rim_height_m", 0.0) or 0.0)
        morphology = str(crater.get("morphology") or "simple")
        if normalized_distance < 1.0:
            if morphology == "complex_or_basin":
                # Complex craters have a flatter floor, steep terraced walls,
                # and a central uplift rather than a single blurred bowl.
                wall_t = _clamp((normalized_distance - 0.52) / 0.48, 0.0, 1.0)
                wall_t = wall_t * wall_t * (3.0 - 2.0 * wall_t)
                basin = 0.62 + 0.38 * (1.0 - wall_t)
                central_peak = math.exp(-((normalized_distance / 0.17) ** 2))
                terrace = math.exp(-(((normalized_distance - 0.72) / 0.075) ** 2))
                adjustment -= depth_m * basin
                adjustment += min(depth_m * 0.34, rim_height_m * 3.2) * central_peak
                adjustment += rim_height_m * 0.24 * terrace
            else:
                bowl = max(0.0, 1.0 - normalized_distance * normalized_distance) ** 1.35
                adjustment -= depth_m * bowl
        rim = math.exp(-(((normalized_distance - 1.0) / 0.105) ** 2))
        adjustment += rim_height_m * rim
        if normalized_distance > 1.0:
            azimuth = math.atan2(delta_latitude, delta_longitude + 1e-12)
            ray_phase = (cx * 17.0 + cy * 31.0) * math.tau
            ray_modulation = 0.72 + 0.28 * max(0.0, math.cos(5.0 * azimuth + ray_phase)) ** 3
            ejecta = math.exp(-(normalized_distance - 1.0) / 0.31) * ray_modulation
            adjustment += rim_height_m * 0.22 * ejecta
    return adjustment


def _plume_lid_feature_signal(nx, ny, terrain):
    model = terrain.get("plume_lid_feature_model") if isinstance(terrain.get("plume_lid_feature_model"), dict) else {}
    if not model:
        return 0.0
    radius_km = max(1.0, float(model.get("radius_km", 6000.0) or 6000.0))
    span_m = max(1.0, float((terrain.get("heightfield") or {}).get("max_elevation_m", 11000.0)) - float((terrain.get("heightfield") or {}).get("min_elevation_m", -3000.0)))
    signal = 0.0

    def distance(item):
        dx = _wrapped_delta(nx, float(item.get("x", 0.0) or 0.0)) * math.tau
        dy = (ny - float(item.get("y", 0.5) or 0.5)) * math.pi
        return math.hypot(dx * math.cos((ny - 0.5) * math.pi), dy) * radius_km

    for item in model.get("coronae") or []:
        radius = max(20.0, float(item.get("diameter_km", 200.0) or 200.0) * 0.5)
        d = distance(item) / radius
        ring = math.exp(-(((d - 0.82) / 0.20) ** 2))
        center = math.exp(-((d / 0.55) ** 2))
        signal += (ring * float(item.get("uplift_m", 600.0)) - center * 220.0) / span_m * 2.0
    for item in model.get("tesserae") or []:
        width = max(80.0, float(item.get("width_km", 700.0) or 700.0))
        d = distance(item) / (width * 0.5)
        if d <= 1.7:
            envelope = math.exp(-((d / 1.05) ** 4))
            ridges = item.get("ridge_orientations_deg") or [25.0, 115.0]
            crosshatch = sum(math.sin((nx * math.cos(math.radians(angle)) + ny * math.sin(math.radians(angle))) * math.tau * 34.0) for angle in ridges) / len(ridges)
            signal += envelope * (float(item.get("uplift_m", 1400.0)) / span_m * 2.0 + abs(crosshatch) * 0.15)
    for item in (model.get("volcanic_rises") or []) + (model.get("pancake_domes") or []):
        radius = max(8.0, float(item.get("diameter_km", 120.0) or 120.0) * 0.5)
        d = distance(item) / radius
        if d <= 2.0:
            dome = math.exp(-((d / 0.72) ** 2))
            if item.get("profile") == "flat_topped_steep_sided":
                dome = 1.0 / (1.0 + math.exp((d - 0.78) * 16.0))
            signal += dome * float(item.get("height_m", 900.0) or 900.0) / span_m * 2.0
    for group, gain in (("rift_belts", -0.055), ("lava_channels", -0.018)):
        for item in model.get(group) or []:
            points = item.get("points") or []
            for start, end in zip(points, points[1:]):
                d = _wrapped_point_segment_distance(nx, ny, start["x"], start["y"], end["x"], end["y"])
                signal += gain * math.exp(-((d / (0.008 if group == "rift_belts" else 0.0035)) ** 2))
    return signal


def _wave_height(nx, ny, terrain, tectonic_model=None, crater_model=None, crater_spatial_index=None, map_seed=""):
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
    icy_surface = terrain.get("surface_regime") == "cratered_ice_shell"
    continents = _continent_signal(nx, ny, map_seed=map_seed)
    lowland_bias = -0.12 - water_smoothing * 0.22
    plume_lid_surface = terrain.get("surface_regime") == "plume_lid_volcanic"
    if icy_surface:
        ice_texture = _fbm_noise(map_seed, "ice_shell_relief", nx, ny, base_cells=9, octaves=4)
        fracture_a = _ridge_belt(nx, ny, seed_range(map_seed, "ice_fracture_a_phase", 0.0, 1.0), 0.42, 0.075, 0.012)
        fracture_b = _ridge_belt(nx, ny, seed_range(map_seed, "ice_fracture_b_phase", 0.0, 1.0), 0.64, 0.055, 0.009)
        value = -0.04 + broad_basins * (0.42 + roughness * 0.24) + ice_texture * (0.20 + roughness * 0.15)
        value += max(fracture_a, fracture_b * 0.8) * 0.26
    elif plume_lid_surface:
        plains_noise = _fbm_noise(map_seed, "volcanic_plains", nx, ny, base_cells=10, octaves=3)
        value = -0.025 + broad_basins * 0.24 + plains_noise * 0.075
    else:
        value = lowland_bias + broad_basins * (0.7 + roughness * 0.35)
        value += continents * (0.26 + roughness * 0.14)
        value -= _intracontinental_basin_signal(nx, ny, map_seed=map_seed) * _continental_mask(continents) * 0.11
        value += _oceanic_island_signal(nx, ny, map_seed=map_seed) * (1.0 - _continental_mask(continents)) * 0.34

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

    if crater_gain > 0.12 and not isinstance(crater_model, dict):
        value += _crater_signal(nx, ny, map_seed=map_seed) * crater_gain * 0.55
    if isinstance(crater_model, dict):
        min_elevation = float(heightfield.get("min_elevation_m", -5000.0) or -5000.0)
        max_elevation = float(heightfield.get("max_elevation_m", 5000.0) or 5000.0)
        span = max(1.0, max_elevation - min_elevation)
        value += (_crater_height_adjustment_m(nx, ny, crater_model, crater_spatial_index) / span) * 2.0

    if plume_lid_surface:
        value *= float(heightfield.get("hypsometry_compression", 0.52) or 0.52)
        value += _plume_lid_feature_signal(nx, ny, terrain)
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

    width_px = int(canvas.get("width_px", PLANETARY_CANVAS_WIDTH_PX) or PLANETARY_CANVAS_WIDTH_PX)
    height_px = int(canvas.get("height_px", PLANETARY_CANVAS_HEIGHT_PX) or PLANETARY_CANVAS_HEIGHT_PX)
    min_elevation = float(heightfield.get("min_elevation_m", -4000.0) or -4000.0)
    max_elevation = float(heightfield.get("max_elevation_m", 4000.0) or 4000.0)
    sea_level = heightfield.get("sea_level_m")
    hydrology = terrain.get("hydrology") if isinstance(terrain.get("hydrology"), dict) else {}
    try:
        target_ocean_fraction = _clamp(hydrology.get("target_ocean_fraction", 0.0), 0.0, 0.92)
    except (TypeError, ValueError):
        target_ocean_fraction = 0.0
    try:
        target_ice_fraction = _clamp(hydrology.get("target_ice_fraction", 0.0), 0.0, 1.0)
    except (TypeError, ValueError):
        target_ice_fraction = 0.0
    if sea_level is None and not (
        hydrology.get("liquid_water_possible") or hydrology.get("frozen_ocean_possible")
    ):
        target_ocean_fraction = 0.0
    midpoint = (max_elevation + min_elevation) * 0.5
    datum_center = heightfield.get("datum_center_m")
    if datum_center is not None:
        midpoint = float(datum_center)
    half_range = max(1.0, (max_elevation - min_elevation) * 0.5)
    sampled_tectonic_model = _heightmap_tectonic_model(tectonic_model)
    crater_spatial_index = _crater_spatial_index(crater_model) if isinstance(crater_model, dict) else None

    sample_width = max(129, min(257, int(width_px // 32) + 1))
    if sample_width % 2 == 0:
        sample_width += 1
    sample_height = max(65, min(129, int((sample_width - 1) / 2) + 1))
    rows = []
    sample_values = []
    sample_positions = []
    for row in range(sample_height):
        ny = row / max(1, sample_height - 1)
        row_values = []
        for col in range(sample_width):
            nx = 0.0 if col == sample_width - 1 else col / max(1, sample_width - 1)
            normalized = _wave_height(nx, ny, terrain, tectonic_model=sampled_tectonic_model, crater_model=crater_model, crater_spatial_index=crater_spatial_index, map_seed=map_seed)
            elevation = midpoint + normalized * half_range
            elevation = round(_clamp(elevation, min_elevation, max_elevation), 1)
            row_values.append(elevation)
            sample_positions.append((col, row, nx, ny, elevation))
        if row_values:
            row_values[-1] = row_values[0]
        sample_values.extend(row_values)
        rows.append(row_values)

    if isinstance(sampled_tectonic_model, dict) and sampled_tectonic_model.get("status") == "tectonics_advanced":
        rows = _smooth_height_rows(rows, passes=1, blend=0.20)
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
        age_passes = min(3, max(1, int(simulated_age_myr // 60.0)))
        erosion_blend = min(0.22, 0.06 + simulated_age_myr / 2200.0)
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
    if target_ocean_fraction > 0.0 and sample_values and not bool(heightfield.get("sea_level_locked")):
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
        "coverage": canvas.get("coverage", "full_planet"),
        "radius_m": canvas.get("radius_m") or (physics or {}).get("radius_m"),
        "circumference_m": canvas.get("circumference_m"),
        "equator_resolution_m_per_px": canvas.get("equator_resolution_m_per_px"),
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
        "geology_model": {
            "model_version": "physiographic-heightmap-v3",
            "surface_regime": terrain.get("surface_regime", "rocky_surface"),
            "continental_lithosphere": None if terrain.get("surface_regime") == "cratered_ice_shell" else "assembled_cratons_accreted_terranes_rifted_margins",
            "oceanic_lithosphere": None if terrain.get("surface_regime") == "cratered_ice_shell" else "abyssal_plains_ridges_trenches",
            "active_margin_features": ["ice_chasmata", "extensional_fractures"] if terrain.get("surface_regime") == "cratered_ice_shell" else ["orogenic_belts", "volcanic_arcs", "foreland_basins"],
            "passive_margin_features": [] if terrain.get("surface_regime") == "cratered_ice_shell" else ["continental_shelves", "slope_breaks", "rifted_edges"],
            "erosion_model": "impact_gardening_and_viscous_relaxation" if terrain.get("surface_regime") == "cratered_ice_shell" else "multiscale_fl_pluvial_glacial_coastal_erosion",
            "continental_processes": ["craton_assembly", "terrane_accretion", "suture_uplift", "continental_rifting", "sedimentary_subsidence"],
            "island_processes": ["subduction_volcanic_arcs", "age_progressive_hotspot_chains", "rifted_microcontinents"],
            "inland_basin_count": len(_continental_process_model(str(map_seed or ""))["basins"]),
            "hotspot_chain_count": len(_continental_process_model(str(map_seed or ""))["island_chains"]),
            "sample_resolution": f"{sample_width}x{sample_height}",
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
            "heightmap_boundary_segments": (
                sampled_tectonic_model.get("heightmap_boundary_segment_count")
                if isinstance(sampled_tectonic_model, dict)
                else None
            ),
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
