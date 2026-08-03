import copy
import hashlib
import json
import math
from functools import lru_cache

from simulations.world_gen.map_seed import resolved_map_seed, seed_range as _uncached_seed_range
from simulations.world_gen.terrain_seed import (
    PLANETARY_CANVAS_HEIGHT_PX,
    PLANETARY_CANVAS_WIDTH_PX,
)

_NOISE_CORNER_CACHE = {}


@lru_cache(maxsize=4096)
def seed_range(seed_text, salt, low, high):
    """Cache immutable seed constants reused at every heightfield sample."""
    return _uncached_seed_range(seed_text, salt, low, high)


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
    assembly_count = int(round(seed_range(seed, "crust:assembly_count", 6.0, 9.0)))
    cratons, sutures, rifts, basins, embayments = [], [], [], [], []
    for assembly in range(assembly_count):
        key = f"crust:assembly_{assembly}"
        cx = seed_range(seed, f"{key}:x", 0.0, 1.0)
        cy = seed_range(seed, f"{key}:y", 0.14, 0.86)
        bearing = seed_range(seed, f"{key}:bearing", 0.0, math.tau)
        craton_count = int(round(seed_range(seed, f"{key}:cratons", 3.0, 6.0)))
        local = []
        for index in range(craton_count):
            along = (index - (craton_count - 1) * 0.5) * seed_range(seed, f"{key}:spacing", 0.045, 0.085)
            across = seed_range(seed, f"{key}:across_{index}", -0.045, 0.045)
            px = (cx + math.cos(bearing) * along - math.sin(bearing) * across) % 1.0
            py = _clamp(cy + math.sin(bearing) * along + math.cos(bearing) * across, 0.08, 0.92)
            width = seed_range(seed, f"{key}:w_{index}", 0.035, 0.090)
            height = seed_range(seed, f"{key}:h_{index}", 0.032, 0.082)
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
        # Accreted terranes and rifted fragments keep continental margins from
        # collapsing into a few smooth ellipses. Some remain connected as
        # peninsulas while others become nearby microcontinents.
        terrane_count = int(round(seed_range(seed, f"{key}:terranes", 2.0, 4.0)))
        for index in range(terrane_count):
            terrane_angle = bearing + seed_range(seed, f"{key}:terrane_angle_{index}", -1.9, 1.9)
            terrane_offset = seed_range(seed, f"{key}:terrane_offset_{index}", 0.070, 0.145)
            cratons.append((
                (cx + math.cos(terrane_angle) * terrane_offset) % 1.0,
                _clamp(cy + math.sin(terrane_angle) * terrane_offset, 0.07, 0.93),
                seed_range(seed, f"{key}:terrane_w_{index}", 0.016, 0.043),
                seed_range(seed, f"{key}:terrane_h_{index}", 0.014, 0.038),
                terrane_angle + seed_range(seed, f"{key}:terrane_rotation_{index}", -0.8, 0.8),
                seed_range(seed, f"{key}:terrane_strength_{index}", 0.62, 0.92),
            ))
        embayment_count = int(round(seed_range(seed, f"{key}:embayments", 1.0, 2.0)))
        for index in range(embayment_count):
            embayment_angle = bearing + seed_range(seed, f"{key}:embayment_angle_{index}", -2.4, 2.4)
            embayment_offset = seed_range(seed, f"{key}:embayment_offset_{index}", 0.055, 0.105)
            embayments.append((
                (cx + math.cos(embayment_angle) * embayment_offset) % 1.0,
                _clamp(cy + math.sin(embayment_angle) * embayment_offset, 0.07, 0.93),
                seed_range(seed, f"{key}:embayment_w_{index}", 0.018, 0.052),
                seed_range(seed, f"{key}:embayment_h_{index}", 0.014, 0.040),
                seed_range(seed, f"{key}:embayment_depth_{index}", 0.12, 0.30),
            ))
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
            "basins": tuple(basins), "embayments": tuple(embayments),
            "island_chains": tuple(island_chains)}


def _continent_signal(nx, ny, map_seed="", tectonic_model=None):
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
    # Anchor old continental nuclei to present-day continental plates. The
    # smaller procedural cratons above provide irregular detail; these broad
    # plate-conditioned roots prevent continents from ignoring plate history.
    if isinstance(tectonic_model, dict):
        for plate in tectonic_model.get("plates") or []:
            if not isinstance(plate, dict) or plate.get("plate_type") == "oceanic":
                continue
            continentality = float(plate.get("continentality", 0.5) or 0.5)
            width = 0.075 + continentality * 0.10
            height = 0.055 + continentality * 0.075
            dx = _wrapped_delta(wx, float(plate.get("center_x", 0.0) or 0.0))
            dy = wy - float(plate.get("center_y", 0.5) or 0.5)
            root = math.exp(-(((dx / width) ** 2 + (dy / height) ** 2) * 0.72))
            lithosphere = max(lithosphere, root * (0.90 + continentality * 0.45))
    signal = -0.56 + lithosphere * 0.92
    for x1, y1, x2, y2, width in model["sutures"]:
        distance = _wrapped_point_segment_distance(wx, wy, x1, y1, x2, y2)
        signal += 0.13 * math.exp(-((distance / width) ** 2))
    for x1, y1, x2, y2, width in model["rifts"]:
        distance = _wrapped_point_segment_distance(wx, wy, x1, y1, x2, y2)
        signal -= 0.22 * math.exp(-((distance / width) ** 2)) * _smoothstep(lithosphere)
    for cx, cy, width, height, depth in model["embayments"]:
        distance = (_wrapped_delta(wx, cx) / width) ** 2 + ((wy - cy) / height) ** 2
        signal -= math.exp(-distance) * depth

    terrane = _fbm_noise(map_seed, "continental_terrane_texture", wx, wy, base_cells=10, octaves=4)
    shore = _fbm_noise(map_seed, "continental_eroded_margins", wx, wy, base_cells=28, octaves=3, gain=0.48)
    coast_detail = _fbm_noise(map_seed, "continental_coast_detail", wx, wy, base_cells=52, octaves=2, gain=0.42)
    shore_band = math.exp(-(((signal + 0.08) / 0.24) ** 2))
    signal += terrane * 0.09 + shore * (0.06 + shore_band * 0.19) + coast_detail * shore_band * 0.10
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


def _plate_distance(nx, ny, plate):
    dx = _wrapped_delta(nx, float(plate.get("center_x", 0.0) or 0.0))
    dy = float(ny) - float(plate.get("center_y", 0.5) or 0.5)
    shape = plate.get("boundary_shape") if isinstance(plate.get("boundary_shape"), dict) else {}
    orientation = float(shape.get("orientation_rad", 0.0) or 0.0)
    axis_ratio = _clamp(shape.get("axis_ratio", 1.0), 0.72, 1.38)
    cos_angle = math.cos(orientation)
    sin_angle = math.sin(orientation)
    rx = (dx * cos_angle - dy * sin_angle) / axis_ratio
    ry = (dx * sin_angle + dy * cos_angle) * axis_ratio
    angle = math.atan2(ry, rx)
    lobe_scale = 1.0
    lobe_scale += float(shape.get("lobe_a_amplitude", 0.0) or 0.0) * math.sin(
        angle * int(shape.get("lobe_a_frequency", 3) or 3)
        + float(shape.get("lobe_a_phase", 0.0) or 0.0)
    )
    lobe_scale += float(shape.get("lobe_b_amplitude", 0.0) or 0.0) * math.sin(
        angle * int(shape.get("lobe_b_frequency", 5) or 5)
        + float(shape.get("lobe_b_phase", 0.0) or 0.0)
    )
    return math.hypot(rx, ry) / max(0.68, lobe_scale)


def _nearest_plate(nx, ny, plates):
    best = None
    best_distance = 999.0
    for plate in plates:
        distance = _plate_distance(nx, ny, plate)
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


def _sample_lithosphere(tectonic_model, nx, ny):
    grid = tectonic_model.get("lithosphere_grid") if isinstance(tectonic_model.get("lithosphere_grid"), dict) else {}
    crust_rows = grid.get("crust_type_rows") or []
    age_rows = grid.get("ocean_floor_age_rows_myr") or []
    fraction_rows = grid.get("continental_fraction_rows") or []
    if not crust_rows or not crust_rows[0]:
        return {"crust_type": "unknown", "age_myr": 0.0, "continental_fraction": 0.5}
    height = len(crust_rows)
    width = min(len(row) for row in crust_rows)
    x = int(round(float(nx) * max(1, width - 1))) % width
    y = max(0, min(height - 1, int(round(float(ny) * max(1, height - 1)))))
    age = float(age_rows[y][x]) if y < len(age_rows) and x < len(age_rows[y]) else 0.0

    def sample_continuous(rows, default=0.0):
        if not rows or len(rows) < 2 or not rows[0]:
            return float(default)
        grid_height = len(rows)
        grid_width = min(len(row) for row in rows)
        fx = (float(nx) % 1.0) * max(1, grid_width - 1)
        fy = _clamp(ny, 0.0, 1.0) * max(1, grid_height - 1)
        x1, y1 = int(math.floor(fx)), int(math.floor(fy))
        tx, ty = fx - x1, fy - y1

        def cubic(p0, p1, p2, p3, t):
            return 0.5 * (
                2.0 * p1
                + (-p0 + p2) * t
                + (2.0 * p0 - 5.0 * p1 + 4.0 * p2 - p3) * t * t
                + (-p0 + 3.0 * p1 - 3.0 * p2 + p3) * t * t * t
            )

        support, interpolated_rows = [], []
        for source_y in range(y1 - 1, y1 + 3):
            yy = max(0, min(grid_height - 1, source_y))
            values = [
                float(rows[yy][source_x % grid_width])
                for source_x in range(x1 - 1, x1 + 3)
            ]
            support.extend(values)
            interpolated_rows.append(cubic(*values, tx))
        value = cubic(*interpolated_rows, ty)
        return _clamp(value, min(support), max(support))

    if fraction_rows and fraction_rows[0]:
        # Bicubic reconstruction gives the low-resolution causal lithosphere
        # fields continuous first derivatives.  Bilinear interpolation hid
        # value jumps but left every source-cell edge visible after hillshade.
        continental_fraction = _clamp(sample_continuous(fraction_rows, 0.5), 0.0, 1.0)
        age = max(0.0, sample_continuous(age_rows, age)) if age_rows else age
    else:
        continental_fraction = 1.0 if crust_rows[y][x] in {"continental", "continental_fragment"} else 0.0
    crust_type = (
        "continental" if continental_fraction >= 0.67
        else "oceanic" if continental_fraction <= 0.33
        else "continental_fragment"
    )
    return {
        "crust_type": crust_type,
        "age_myr": age,
        "continental_fraction": continental_fraction,
        "oceanic_fraction": 1.0 - continental_fraction,
    }


def _blended_plate_base_height_m(nx, ny, plates):
    weighted_height = 0.0
    total_weight = 0.0
    nearest = None
    nearest_distance = 999.0
    for plate in plates:
        distance = _plate_distance(nx, ny, plate)
        if distance < nearest_distance:
            nearest_distance = distance
            nearest = plate
        weight = 1.0 / ((distance + 0.08) ** 2.15)
        weighted_height += _plate_base_height_m(plate) * weight
        total_weight += weight
    if total_weight <= 0:
        return 0.0, nearest
    weighted_average = weighted_height / total_weight
    # Preserve isostatic plate identity in interiors while retaining a small
    # boundary blend. Global averaging flattened both continental freeboard
    # and ocean-basin depth, drowning continents at realistic water volumes.
    nearest_height = _plate_base_height_m(nearest)
    return nearest_height * 0.76 + weighted_average * 0.24, nearest


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


def _representative_boundary_segments(tectonic_model, max_segments=180):
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
    sampled["_heightmap_boundary_spatial_index"] = _boundary_spatial_index(segments)
    return sampled


def _boundary_spatial_index(segments, bins_x=32, bins_y=16):
    """Bucket boundary segments without changing the exact distance test."""
    bins = {}
    for segment in segments:
        x1 = float(segment.get("x1", 0.0) or 0.0)
        x2 = float(segment.get("x2", 0.0) or 0.0)
        if x2 - x1 > 0.5:
            x2 -= 1.0
        elif x2 - x1 < -0.5:
            x2 += 1.0
        y1 = float(segment.get("y1", 0.0) or 0.0)
        y2 = float(segment.get("y2", 0.0) or 0.0)
        margin = _clamp(segment.get("influence_width", 0.028), 0.012, 0.05) * 2.5
        y_min = max(0.0, min(y1, y2) - margin)
        y_max = min(1.0, max(y1, y2) + margin)
        first_y = max(0, min(bins_y - 1, int(math.floor(y_min * bins_y))))
        last_y = max(0, min(bins_y - 1, int(math.floor(y_max * bins_y))))
        for shift in (-1.0, 0.0, 1.0):
            x_min = min(x1, x2) + shift - margin
            x_max = max(x1, x2) + shift + margin
            first_x = max(0, int(math.floor(x_min * bins_x)))
            last_x = min(bins_x - 1, int(math.floor(x_max * bins_x)))
            if first_x > last_x:
                continue
            for by in range(first_y, last_y + 1):
                for bx in range(first_x, last_x + 1):
                    bucket = bins.setdefault((bx, by), [])
                    if segment not in bucket:
                        bucket.append(segment)
    return {"bins": bins, "bins_x": bins_x, "bins_y": bins_y}


def _nearby_boundary_segments(tectonic_model, nx, ny):
    spatial_index = tectonic_model.get("_heightmap_boundary_spatial_index")
    if not isinstance(spatial_index, dict):
        return tectonic_model.get("boundary_segments") or []
    bins_x = int(spatial_index["bins_x"])
    bins_y = int(spatial_index["bins_y"])
    bx = int(float(nx) * bins_x) % bins_x
    by = max(0, min(bins_y - 1, int(float(ny) * bins_y)))
    return spatial_index["bins"].get((bx, by), [])


def _tectonic_height_m(nx, ny, terrain, tectonic_model):
    plates = tectonic_model.get("plates") or []
    if not plates:
        return None
    base, plate = _blended_plate_base_height_m(nx, ny, plates)
    plate_type = plate.get("plate_type") if isinstance(plate, dict) else "mixed"
    plate_continentality = float(plate.get("continentality", 0.5) or 0.5) if isinstance(plate, dict) else 0.5
    lithosphere = _sample_lithosphere(tectonic_model, nx, ny)
    crust_type = lithosphere["crust_type"]
    crust_fraction = float(lithosphere.get("continental_fraction", 0.5) or 0.0)
    oceanic_fraction = _clamp(lithosphere.get("oceanic_fraction", 1.0 - crust_fraction), 0.0, 1.0)
    ocean_floor_age_myr = lithosphere["age_myr"] * oceanic_fraction

    longitude = nx * math.tau
    latitude = (ny - 0.5) * math.pi
    map_seed = str(tectonic_model.get("map_seed") or terrain.get("map_seed") or "")
    continent_signal = _continent_signal(
        nx,
        ny,
        map_seed=map_seed,
        tectonic_model=tectonic_model,
    )
    # A continental plate must carry broad buoyant crust, not merely a small
    # circular root at its centre. Rifts, embayments and terrane noise still
    # cut into this support, producing irregular margins and internal seas.
    # Oceanic plates receive the opposite bias; mixed plates can host arcs and
    # microcontinents without turning the whole plate into exposed land.
    lithosphere_bias = {
        "continental": 0.0,
        "mixed": 0.18,
        "oceanic": -0.20,
    }.get(plate_type, 0.0)
    continent_mask = _continental_mask(
        continent_signal
        + lithosphere_bias
        + (plate_continentality - 0.5) * 0.48
    )
    if plate_type == "continental":
        crust_province = _fbm_noise(
            map_seed, "continental_plate_provinces", nx, ny,
            base_cells=5, octaves=4,
        )
        margin_detail = _fbm_noise(
            map_seed, "continental_plate_margin_detail", nx, ny,
            base_cells=17, octaves=3, gain=0.48,
        )
        province_mix = _smoothstep(
            (crust_province + margin_detail * 0.22 + 0.35) / 0.55
        )
        plate_support = 0.42 + province_mix * 0.56
        continent_mask = max(plate_support, continent_mask)
    elif plate_type == "oceanic":
        continent_mask = min(0.06, continent_mask)
    if plate_type == "mixed":
        # Continental fragments grade into stretched transitional crust rather
        # than stepping abruptly from abyssal basin to high continent.
        continent_mask = continent_mask * 0.18 + crust_fraction * 0.82
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
    # Isostatic contrast is what lets a realistic water volume coexist with
    # exposed continents: young dense oceanic lithosphere forms deep basins,
    # while buoyant differentiated continental crust retains freeboard.
    height += continent_mask * 360.0
    height += (1.0 - continent_mask) * (-2850.0 + basin_noise * 360.0)
    if oceanic_fraction > 0.0:
        # Young ridge crust is hot and buoyant; cooling lithosphere subsides
        # approximately with the square root of age until subduction recycles it.
        height -= min(1450.0, math.sqrt(max(0.0, ocean_floor_age_myr)) * 105.0) * oceanic_fraction
    # Subsidence within stable crust creates sedimentary and endorheic basins.
    height -= intracontinental_basin * continent_mask * 1150.0
    province_model = tectonic_model.get("continental_province_model") if isinstance(tectonic_model.get("continental_province_model"), dict) else {}
    for craton in province_model.get("cratons") or []:
        dx = _wrapped_delta(nx, float(craton.get("center_x", 0.0) or 0.0)) / max(0.01, float(craton.get("width", 0.08) or 0.08))
        dy = (ny - float(craton.get("center_y", 0.5) or 0.5)) / max(0.01, float(craton.get("height", 0.06) or 0.06))
        shield = math.exp(-((dx * dx + dy * dy) * 1.15))
        height += shield * (420.0 if craton.get("state") == "exposed_shield" else 120.0)
    for rift in province_model.get("failed_rifts") or []:
        distance = _wrapped_point_segment_distance(
            nx, ny,
            float(rift.get("x1", 0.0) or 0.0), float(rift.get("y1", 0.5) or 0.5),
            float(rift.get("x2", 0.0) or 0.0), float(rift.get("y2", 0.5) or 0.5),
        )
        height -= math.exp(-((distance / 0.014) ** 2)) * float(rift.get("subsidence_m", 0.0) or 0.0) * continent_mask
    for basin in province_model.get("intracratonic_basins") or []:
        distance = math.hypot(
            _wrapped_delta(nx, float(basin.get("center_x", 0.0) or 0.0)),
            ny - float(basin.get("center_y", 0.5) or 0.5),
        ) / max(0.01, float(basin.get("radius", 0.05) or 0.05))
        height -= math.exp(-(distance ** 2)) * min(1250.0, float(basin.get("sediment_capacity_m", 0.0) or 0.0) * 0.16) * continent_mask
    if plate_type == "oceanic":
        height -= 520.0
    elif plate_type == "continental":
        height += 280.0

    effects = tectonic_model.get("surface_effects") if isinstance(tectonic_model.get("surface_effects"), dict) else {}
    uplift_gain = 0.7 + float(effects.get("orogenic_uplift", 0.0) or 0.0) * 0.9
    basin_gain = 0.65 + float(effects.get("ocean_basin_opening", 0.0) or 0.0) * 0.75
    erosion = float(effects.get("erosion_progress", 0.0) or 0.0)
    convergent_influence = 0.0
    divergent_influence = 0.0
    trench_influence = 0.0
    transform_influence = 0.0

    for segment in _nearby_boundary_segments(tectonic_model, nx, ny):
        distance = _wrapped_point_segment_distance(
            nx,
            ny,
            float(segment.get("x1", 0.0) or 0.0),
            float(segment.get("y1", 0.0) or 0.0),
            float(segment.get("x2", 0.0) or 0.0),
            float(segment.get("y2", 0.0) or 0.0),
        )
        influence_width = _clamp(segment.get("influence_width", 0.028), 0.012, 0.05)
        if distance > influence_width * 2.5:
            continue
        influence = math.exp(-((distance / influence_width) ** 2))
        influence = influence ** 1.18 * _clamp(segment.get("activity_scale", 1.0), 0.25, 1.35)
        # Fixed frequencies here (only the phase was seeded) gave every
        # generated world's fold-and-thrust ridges the exact same along-
        # strike wavelength -- a comb-regular pattern that reads as banding
        # once rain shadow inherits it. Seeding the frequencies too, and
        # adding a third, higher, lower-weight octave, breaks the pure
        # 2-term periodicity into something closer to real ridge-and-valley
        # terrain's irregular spacing.
        segmentation_phase = seed_range(map_seed, "orogen_segmentation_phase", 0.0, math.tau)
        primary_freq_x = seed_range(map_seed, "orogen_segmentation_freq_primary_x", 7.0, 15.0)
        primary_freq_y = seed_range(map_seed, "orogen_segmentation_freq_primary_y", 10.0, 20.0)
        secondary_freq_x = seed_range(map_seed, "orogen_segmentation_freq_secondary_x", 21.0, 37.0)
        secondary_freq_y = seed_range(map_seed, "orogen_segmentation_freq_secondary_y", 13.0, 25.0)
        tertiary_freq_x = seed_range(map_seed, "orogen_segmentation_freq_tertiary_x", 43.0, 61.0)
        tertiary_freq_y = seed_range(map_seed, "orogen_segmentation_freq_tertiary_y", 31.0, 47.0)
        primary_segment = 0.5 + 0.5 * math.sin(
            (nx * primary_freq_x + ny * primary_freq_y) * math.tau + segmentation_phase
        )
        secondary_segment = 0.5 + 0.5 * math.sin(
            (nx * secondary_freq_x - ny * secondary_freq_y) * math.tau + segmentation_phase * 1.73
        )
        tertiary_segment = 0.5 + 0.5 * math.sin(
            (nx * tertiary_freq_x + ny * tertiary_freq_y) * math.tau + segmentation_phase * 2.41
        )
        along_strike_texture = 0.20 + 0.80 * _smoothstep(
            primary_segment * 0.56 + secondary_segment * 0.28 + tertiary_segment * 0.16
        )
        kind = segment.get("kind") or "passive"
        normal_x = float(segment.get("normal_x", 0.0) or 0.0)
        normal_y = float(segment.get("normal_y", 0.0) or 0.0)
        midpoint_x = (float(segment.get("x1", 0.0) or 0.0) + float(segment.get("x2", 0.0) or 0.0)) * 0.5
        midpoint_y = (float(segment.get("y1", 0.0) or 0.0) + float(segment.get("y2", 0.0) or 0.0)) * 0.5
        signed_normal_distance = _wrapped_delta(nx, midpoint_x) * normal_x + (ny - midpoint_y) * normal_y
        if kind == "collision":
            height += 3700.0 * uplift_gain * influence * along_strike_texture
            # Flexural loading depresses a foreland basin outside the central
            # fold-and-thrust belt and raises a weak outer bulge farther out.
            foreland = math.exp(-(((abs(signed_normal_distance) - 0.040) / 0.014) ** 2))
            outer_bulge = math.exp(-(((abs(signed_normal_distance) - 0.068) / 0.016) ** 2))
            height -= 920.0 * foreland * along_strike_texture
            height += 260.0 * outer_bulge
            convergent_influence = max(convergent_influence, influence)
        elif kind == "subduction":
            overriding_side = 1.0 if segment.get("overriding_plate") == segment.get("plate_b") else -1.0
            trench_band = math.exp(-(((signed_normal_distance + overriding_side * 0.012) / 0.009) ** 2))
            arc_band = math.exp(-(((signed_normal_distance - overriding_side * 0.024) / 0.013) ** 2))
            forearc_band = math.exp(-(((signed_normal_distance - overriding_side * 0.010) / 0.010) ** 2))
            backarc_band = math.exp(-(((signed_normal_distance - overriding_side * 0.045) / 0.018) ** 2))
            height += 2700.0 * uplift_gain * arc_band * along_strike_texture
            height -= 2300.0 * trench_band
            height -= 320.0 * forearc_band
            height -= 520.0 * backarc_band * (0.35 + along_strike_texture * 0.65)
            # Discrete volcanoes sit on the overriding arc rather than forming
            # a continuous ridge exactly on the trench.
            arc_beads = max(0.0, math.sin((nx * 71.0 + ny * 43.0) * math.tau)) ** 5
            height += 2300.0 * arc_band * arc_beads
            convergent_influence = max(convergent_influence, influence)
            trench_influence = max(trench_influence, trench_band)
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
    hotspot_model = tectonic_model.get("hotspot_model") if isinstance(tectonic_model.get("hotspot_model"), dict) else {}
    for hotspot in hotspot_model.get("hotspots") or []:
        for point in hotspot.get("track") or []:
            distance = math.hypot(
                _wrapped_delta(nx, float(point.get("x", 0.0) or 0.0)),
                ny - float(point.get("y", 0.5) or 0.5),
            )
            # Older track points have subsided/eroded longer: wider and
            # softer than just shorter, independent of the buoyancy-driven
            # amplitude decay already carried by relative_volume.
            erosion_softening = _clamp(float(point.get("erosion_softening", 0.0) or 0.0), 0.0, 1.0)
            radius = (0.008 + float(point.get("relative_volume", 0.0) or 0.0) * 0.010) * (1.0 + erosion_softening * 0.9)
            if distance < radius * 2.5:
                height += (
                    math.exp(-((distance / radius) ** 2))
                    * 2600.0
                    * float(point.get("relative_volume", 0.0) or 0.0)
                    * (1.0 - continent_mask * 0.55)
                    * (1.0 - erosion_softening * 0.35)
                )

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
        preservation = _clamp(
            crater.get("morphology_preservation", 1.0), 0.0, 1.0
        )
        depth_m = float(crater.get("depth_m", 0.0) or 0.0) * preservation
        rim_height_m = float(crater.get("rim_height_m", 0.0) or 0.0) * preservation
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


def _sample_height_rows(rows, u, v, *, wrap_x=True):
    if not rows or not rows[0]:
        return 0.0
    height, width = len(rows), len(rows[0])
    px = (float(u) % 1.0 if wrap_x else _clamp(u, 0.0, 1.0)) * max(1, width - 1)
    py = _clamp(v, 0.0, 1.0) * max(1, height - 1)
    x0, y0 = int(math.floor(px)), int(math.floor(py))
    x1 = (x0 + 1) % width if wrap_x else min(width - 1, x0 + 1)
    y1 = min(height - 1, y0 + 1)
    tx, ty = px - x0, py - y0
    top = float(rows[y0][x0]) * (1.0 - tx) + float(rows[y0][x1]) * tx
    bottom = float(rows[y1][x0]) * (1.0 - tx) + float(rows[y1][x1]) * tx
    return top * (1.0 - ty) + bottom * ty


def condition_crater_model_to_surface(crater_model, terrain, base_rows, sea_level):
    """Resolve long-term and marine preservation before carving relief.

    A marine impact only excavates a strong seafloor crater when its projectile
    is large compared with the water column.  Atmosphere, water, ice and
    erosion then reduce the retained topographic expression over geologic
    time.  The impact catalogue remains intact; each event records how much of
    its morphology is visible in the present-day heightfield.
    """
    if not isinstance(crater_model, dict):
        return crater_model, {"status": "not_applicable"}
    terrain = terrain if isinstance(terrain, dict) else {}
    erosion = terrain.get("erosion") if isinstance(terrain.get("erosion"), dict) else {}
    hydrology = terrain.get("hydrology") if isinstance(terrain.get("hydrology"), dict) else {}
    cratering = terrain.get("cratering") if isinstance(terrain.get("cratering"), dict) else {}
    pressure_bar = max(0.0, float(erosion.get("atmospheric_pressure_bar", 0.0) or 0.0))
    erosion_strength = _clamp(erosion.get("strength", 0.0), 0.0, 1.0)
    resurfacing = _clamp(
        cratering.get(
            "resurfacing_fraction",
            crater_model.get("resurfacing_fraction", 0.0),
        ),
        0.0,
        1.0,
    )
    ice_fraction = _clamp(hydrology.get("target_ice_fraction", 0.0), 0.0, 1.0)
    atmosphere_degradation = _clamp(
        math.log1p(pressure_bar * 3.0) / math.log(31.0), 0.0, 1.0
    )
    global_preservation = _clamp(
        1.0
        - erosion_strength * 0.58
        - atmosphere_degradation * 0.24
        - resurfacing * 0.52
        - ice_fraction * 0.36,
        0.06,
        1.0,
    )
    # Near-airless inactive surfaces should retain their original morphology.
    if pressure_bar < 0.01 and erosion_strength < 0.08 and resurfacing < 0.05:
        global_preservation = max(global_preservation, 0.94)

    conditioned = []
    marine_count = 0
    suppressed_count = 0
    for source in crater_model.get("craters") or []:
        crater = dict(source)
        center_elevation = _sample_height_rows(
            base_rows,
            float(crater.get("x", 0.0) or 0.0),
            float(crater.get("y", 0.5) or 0.5),
            wrap_x=True,
        )
        water_depth_m = (
            max(0.0, float(sea_level) - center_elevation)
            if sea_level is not None
            else 0.0
        )
        marine_transmission = 1.0
        if water_depth_m > 0.0:
            marine_count += 1
            crater_diameter_m = max(
                1.0, float(crater.get("diameter_km", 0.0) or 0.0) * 1000.0
            )
            # Final crater diameters are commonly an order of magnitude or
            # more larger than the projectile.  This proxy makes shallow-water
            # giant impacts survive while deep-water small impacts do not
            # stamp lunar bowls into the seabed.
            projectile_diameter_m = crater_diameter_m / 16.0
            depth_ratio = water_depth_m / max(1.0, projectile_diameter_m)
            marine_transmission = _clamp(
                math.exp(-1.18 * max(0.0, depth_ratio - 0.12)),
                0.015,
                1.0,
            )
            if marine_transmission < 0.20:
                suppressed_count += 1
        preservation = _clamp(
            global_preservation * marine_transmission, 0.0, 1.0
        )
        crater["target_environment"] = "marine" if water_depth_m > 0.0 else "subaerial"
        crater["target_water_depth_m"] = round(water_depth_m, 1)
        crater["marine_crater_transmission"] = round(marine_transmission, 4)
        crater["morphology_preservation"] = round(preservation, 4)
        conditioned.append(crater)
    crater_model["craters"] = conditioned
    crater_model["surface_morphology_preservation"] = round(global_preservation, 4)
    crater_model["marine_target_model"] = "water_depth_to_projectile_scale_v1"
    audit = {
        "status": "resolved",
        "global_preservation": round(global_preservation, 4),
        "marine_crater_count": marine_count,
        "strongly_suppressed_marine_crater_count": suppressed_count,
        "pressure_bar": round(pressure_bar, 5),
        "erosion_strength": round(erosion_strength, 4),
    }
    return crater_model, audit


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
    specialized = terrain.get("specialized_surface_processes") if isinstance(terrain.get("specialized_surface_processes"), dict) else {}
    geologic_style = str(specialized.get("geologic_style") or "").lower()

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

    # Regime-specific morphology is added before tectonic/crater features. It
    # gives dry, volatile, volcanic, and rifted worlds recognisably different
    # landforms while retaining the same heightfield contract for map tools.
    if geologic_style in {"heat_pipe_volcanic", "sulfur_heat_pipe"}:
        plume_noise = _fbm_noise(map_seed, "heat_pipe_provinces", nx, ny, base_cells=7, octaves=4)
        volcanic_belts = max(
            _ridge_belt(nx, ny, seed_range(map_seed, "heat_pipe_a", 0.0, 1.0), 0.34, 0.10, 0.070),
            _ridge_belt(nx, ny, seed_range(map_seed, "heat_pipe_b", 0.0, 1.0), 0.66, 0.085, 0.060),
        )
        value = value * 0.48 + plume_noise * 0.18 + volcanic_belts * 0.34
    elif geologic_style == "episodic_rifting":
        rift_a = _ridge_belt(nx, ny, seed_range(map_seed, "episodic_rift_a", 0.0, 1.0), 0.38, 0.050, 0.115)
        rift_b = _ridge_belt(nx, ny, seed_range(map_seed, "episodic_rift_b", 0.0, 1.0), 0.63, 0.042, 0.090)
        flood_plain = _fbm_noise(map_seed, "episodic_flood_lava", nx, ny, base_cells=11, octaves=3)
        value += max(rift_a, rift_b * 0.82) * 0.36 + flood_plain * 0.08
    elif geologic_style == "plutonic_intrusive_uplands":
        batholiths = _fbm_noise(map_seed, "plutonic_batholiths", nx, ny, base_cells=5, octaves=3)
        dome_a = _ridge_belt(nx, ny, seed_range(map_seed, "plutonic_dome_a", 0.0, 1.0), 0.34, 0.13, 0.12)
        dome_b = _ridge_belt(nx, ny, seed_range(map_seed, "plutonic_dome_b", 0.0, 1.0), 0.68, 0.11, 0.10)
        value = value * 0.66 + batholiths * 0.13 + max(dome_a, dome_b * 0.88) * 0.18
    elif geologic_style == "aeolian_dune_seas":
        dune_wavelength = seed_range(map_seed, "dune_wavelength", 13.0, 22.0)
        dunes = math.sin(longitude * dune_wavelength + latitude * 2.8 + phase_a) * 0.028
        yardang_belts = _ridge_belt(nx, ny, seed_range(map_seed, "yardang_belt", 0.0, 1.0), 0.52, 0.12, 0.035)
        value = value * 0.58 + dunes + yardang_belts * 0.08
    elif geologic_style == "evaporite_basins":
        terminal_basins = _intracontinental_basin_signal(nx, ny, map_seed=map_seed)
        playa_texture = _fbm_noise(map_seed, "playa_relief", nx, ny, base_cells=14, octaves=2)
        value = value * 0.54 - terminal_basins * 0.19 + playa_texture * 0.035
    elif geologic_style == "volatile_frost_transport":
        frost_plains = _fbm_noise(map_seed, "volatile_frost_plains", nx, ny, base_cells=8, octaves=3)
        sublimation_belts = _ridge_belt(nx, ny, seed_range(map_seed, "sublimation_belt", 0.0, 1.0), 0.50, 0.10, 0.032)
        value = value * 0.42 + frost_plains * 0.10 + sublimation_belts * 0.06
    elif geologic_style == "glaciated":
        glacial_texture = _fbm_noise(map_seed, "glacial_scour", nx, ny, base_cells=12, octaves=3)
        value = value * 0.76 + glacial_texture * 0.055
    elif geologic_style == "magma_seas":
        lava_plains = _fbm_noise(map_seed, "magma_convection", nx, ny, base_cells=14, octaves=2)
        solidification_front = _ridge_belt(nx, ny, seed_range(map_seed, "magma_front", 0.0, 1.0), 0.50, 0.13, 0.025)
        value = value * 0.30 + lava_plains * 0.055 + solidification_front * 0.045

    tectonic_height = None
    if isinstance(tectonic_model, dict) and tectonic_model.get("status") == "tectonics_advanced":
        tectonic_height = _tectonic_height_m(nx, ny, terrain, tectonic_model)

    if tectonic_height is not None:
        min_elevation = float(heightfield.get("min_elevation_m", -5000.0) or -5000.0)
        max_elevation = float(heightfield.get("max_elevation_m", 6000.0) or 6000.0)
        span = max(1.0, max_elevation - min_elevation)
        tectonic_value = ((tectonic_height - min_elevation) / span) * 2.0 - 1.0
        # Mature tectonics owns large-scale hypsometry. The legacy wave field
        # contributes fine irregularity only; a stronger blend here drowned
        # buoyant plate interiors and partially refilled ocean basins.
        value = tectonic_value * 0.88 + value * 0.12
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


def sea_level_for_equivalent_water_depth(rows, equivalent_depth_m, wrap_x=True):
    """Solve sea level from water volume on a spherical sampled surface."""
    if not rows or not rows[0] or float(equivalent_depth_m or 0.0) <= 0.0:
        return None
    height = len(rows)
    width = min(len(row) for row in rows)
    unique_width = max(1, width - 1) if wrap_x and width > 1 else width
    weighted_cells = []
    total_weight = 0.0
    for y, row in enumerate(rows):
        latitude = (0.5 - y / max(1, height - 1)) * math.pi
        area_weight = max(1e-6, math.cos(latitude))
        for x in range(unique_width):
            weighted_cells.append((float(row[x]), area_weight))
            total_weight += area_weight
    if not weighted_cells or total_weight <= 0.0:
        return None
    target_depth = float(equivalent_depth_m)
    low = min(value for value, _weight in weighted_cells)
    high = max(value for value, _weight in weighted_cells) + target_depth
    for _iteration in range(52):
        candidate = (low + high) * 0.5
        stored_depth = sum(
            max(0.0, candidate - elevation) * weight
            for elevation, weight in weighted_cells
        ) / total_weight
        if stored_depth < target_depth:
            low = candidate
        else:
            high = candidate
    return (low + high) * 0.5


def _shelf_and_sediment_model(rows, sea_level, tectonic_model=None):
    if sea_level is None or not rows or not rows[0]:
        return {"shelf_rows": [], "sediment_thickness_rows_m": [], "shelf_fraction": 0.0}
    height, width = len(rows), len(rows[0])
    distance = [[999 for _x in range(width)] for _y in range(height)]
    frontier = []
    for y in range(height):
        for x in range(width):
            if float(rows[y][x]) >= float(sea_level):
                distance[y][x] = 0
                frontier.append((x, y))
    cursor = 0
    while cursor < len(frontier):
        x, y = frontier[cursor]
        cursor += 1
        next_distance = distance[y][x] + 1
        for nx, ny in (((x - 1) % width, y), ((x + 1) % width, y), (x, y - 1), (x, y + 1)):
            if ny < 0 or ny >= height or next_distance >= distance[ny][nx]:
                continue
            distance[ny][nx] = next_distance
            frontier.append((nx, ny))
    shelf_rows, sediment_rows = [], []
    shelf_count = 0
    for y, row in enumerate(rows):
        shelf_row, sediment_row = [], []
        for x, elevation in enumerate(row):
            depth = max(0.0, float(sea_level) - float(elevation))
            lithosphere = _sample_lithosphere(tectonic_model or {}, x / max(1, width - 1), y / max(1, height - 1))
            passive_margin_distance = distance[y][x]
            shelf = depth > 0.0 and depth <= 420.0 and passive_margin_distance <= 7
            if shelf:
                shelf_count += 1
            oceanic_fraction = _clamp(lithosphere.get("oceanic_fraction", 0.0), 0.0, 1.0)
            age_myr = lithosphere["age_myr"] * oceanic_fraction + 800.0 * (1.0 - oceanic_fraction)
            margin_wedge = 3600.0 * math.exp(-passive_margin_distance / 3.2) if depth > 0.0 else 0.0
            pelagic = min(1600.0, max(0.0, age_myr) * 7.0) if depth > 0.0 else 0.0
            sediment = min(7200.0, margin_wedge + pelagic)
            shelf_row.append(bool(shelf))
            sediment_row.append(round(sediment, 1))
        shelf_rows.append(shelf_row)
        sediment_rows.append(sediment_row)
    return {
        "model": "passive_margin_shelf_and_sediment_wedge_v1",
        "shelf_rows": shelf_rows,
        "sediment_thickness_rows_m": sediment_rows,
        "shelf_fraction": round(shelf_count / max(1, width * height), 4),
        "shelf_depth_limit_m": 420.0,
        "sediment_loading_causes_subsidence": True,
    }


HEIGHTMAP_DERIVATIVE_MODEL_VERSION = "heightmap-derivatives-v2"


def _mountain_morphology_mask(rows, land_rows, cell_spacing_m, *, wrap_x=False):
    """Classify resolved mountain terrain from relief, not latitude or noise.

    The returned field is deliberately continuous.  Regional refinement can
    taper ridge-scale relief across the real edge of an inherited mountain
    belt instead of applying a mountain texture to an entire requested tile.
    Ocean depths are excluded from the neighbourhood range so coastlines do
    not masquerade as mountain fronts.
    """
    height = len(rows)
    width = min(len(row) for row in rows)
    unique_width = width - 1 if wrap_x and width > 1 else width
    radius = 2 if min(height, unique_width) >= 9 else 1
    relief_threshold_m = _clamp(float(cell_spacing_m) * 0.006, 140.0, 900.0)
    raw = [[0.0] * width for _ in range(height)]
    for y in range(height):
        for x in range(unique_width):
            if not land_rows[y][x]:
                continue
            local_land = []
            for oy in range(-radius, radius + 1):
                sy = max(0, min(height - 1, y + oy))
                for ox in range(-radius, radius + 1):
                    sx = (x + ox) % unique_width if wrap_x else max(0, min(unique_width - 1, x + ox))
                    if land_rows[sy][sx]:
                        local_land.append(float(rows[sy][sx]))
            if len(local_land) < 4:
                continue
            relief = max(local_land) - min(local_land)
            relief_score = _smoothstep(
                (relief - relief_threshold_m) / max(1.0, relief_threshold_m * 1.35)
            )
            # High-standing parts of a relief complex are likelier to be the
            # range itself; low foreland and basin cells retain only the
            # relief evidence and therefore fade out naturally.
            relative_height = float(rows[y][x]) - min(local_land)
            position_score = _smoothstep(
                (relative_height - relief_threshold_m * 0.12)
                / max(1.0, relief_threshold_m * 0.72)
            )
            raw[y][x] = relief_score * (0.42 + 0.58 * position_score)
        if wrap_x and width > unique_width:
            raw[y][-1] = raw[y][0]

    # Two compact diffusion passes produce a coherent belt mask while
    # preserving broad non-mountain interiors as exact zeroes.
    smoothed = raw
    for _pass in range(2):
        next_rows = [[0.0] * width for _ in range(height)]
        for y in range(height):
            for x in range(unique_width):
                if not land_rows[y][x]:
                    continue
                neighbours = [smoothed[y][x] * 4.0]
                for ox, oy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    sx = (x + ox) % unique_width if wrap_x else max(0, min(unique_width - 1, x + ox))
                    sy = max(0, min(height - 1, y + oy))
                    neighbours.append(smoothed[sy][sx])
                value = sum(neighbours) / 8.0
                next_rows[y][x] = 0.0 if value < 0.035 else round(_clamp(value, 0.0, 1.0), 4)
            if wrap_x and width > unique_width:
                next_rows[y][-1] = next_rows[y][0]
        smoothed = next_rows
    return smoothed, relief_threshold_m


def _heightfield_fingerprint(rows, sea_level):
    payload = json.dumps(
        {"rows": rows, "sea_level_m": sea_level},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def refresh_heightmap_derivatives(heightmap, *, tectonic_model=None, inherited_sea_level_m=None):
    """Rebuild every derivative that depends on the evolved heightfield.

    Full planets conserve their equivalent global water depth and solve a new
    sea level.  Regional products inherit the planetary datum and only rebuild
    local masks and morphology.  The duplicate longitude seam is excluded
    from all area-weighted statistics.
    """
    if not isinstance(heightmap, dict):
        return {}
    refreshed = copy.deepcopy(heightmap)
    grid = refreshed.get("sample_grid") if isinstance(refreshed.get("sample_grid"), dict) else {}
    rows = grid.get("rows") if isinstance(grid.get("rows"), list) else []
    if not rows or not rows[0]:
        return refreshed
    height = len(rows)
    width = min(len(row) for row in rows)
    wrap_x = bool(grid.get("wrap_x", refreshed.get("wrap_x", True)))
    unique_width = width - 1 if wrap_x and width > 1 else width
    regional = str(refreshed.get("coverage") or "full_planet") != "full_planet" or not wrap_x
    equivalent_depth = max(0.0, float(refreshed.get("equivalent_global_water_depth_m", 0.0) or 0.0))
    if regional and inherited_sea_level_m is not None:
        sea_level = float(inherited_sea_level_m)
        sea_level_resolution = "inherited_planetary_datum"
    elif not regional and equivalent_depth > 0.0 and not bool(refreshed.get("sea_level_locked")):
        sea_level = sea_level_for_equivalent_water_depth(rows, equivalent_depth, wrap_x=wrap_x)
        sea_level_resolution = "volume_balance_against_evolved_hypsometry"
    else:
        sea_level = refreshed.get("sea_level_m")
        sea_level = None if sea_level is None else float(sea_level)
        sea_level_resolution = refreshed.get("sea_level_resolution") or ("dry_surface" if sea_level is None else "preserved_datum")

    land_rows = [[False] * width for _ in range(height)]
    ocean_rows = [[False] * width for _ in range(height)]
    coastal_rows = [[False] * width for _ in range(height)]
    weighted_land = weighted_ocean = total_weight = 0.0
    values = []
    for y in range(height):
        latitude = (0.5 - y / max(1, height - 1)) * math.pi
        area_weight = max(1e-6, math.cos(latitude)) if not regional else 1.0
        for x in range(unique_width):
            elevation = float(rows[y][x])
            values.append(elevation)
            land = sea_level is None or elevation >= sea_level
            land_rows[y][x] = land
            ocean_rows[y][x] = not land
            weighted_land += area_weight * int(land)
            weighted_ocean += area_weight * int(not land)
            total_weight += area_weight
        if wrap_x and width > unique_width:
            land_rows[y][-1] = land_rows[y][0]
            ocean_rows[y][-1] = ocean_rows[y][0]

    if sea_level is not None:
        for y in range(height):
            for x in range(unique_width):
                land = land_rows[y][x]
                neighbors = [((x - 1) % unique_width, y), ((x + 1) % unique_width, y)] if wrap_x else []
                if not wrap_x:
                    neighbors.extend([(max(0, x - 1), y), (min(unique_width - 1, x + 1), y)])
                neighbors.extend([(x, max(0, y - 1)), (x, min(height - 1, y + 1))])
                coastal_rows[y][x] = any(land_rows[ny][nx] != land for nx, ny in neighbors)
            if wrap_x and width > unique_width:
                coastal_rows[y][-1] = coastal_rows[y][0]

    prior_masks = refreshed.get("surface_masks") if isinstance(refreshed.get("surface_masks"), dict) else {}
    ice_rows = copy.deepcopy(prior_masks.get("ice_rows") or [[False] * width for _ in range(height)])
    if len(ice_rows) != height or any(len(row) < width for row in ice_rows):
        ice_rows = [[False] * width for _ in range(height)]
    ice_adjacency_rows = [[False] * width for _ in range(height)]
    for y in range(height):
        for x in range(unique_width):
            neighbors = [((x - 1) % unique_width, y), ((x + 1) % unique_width, y)] if wrap_x else [(max(0, x - 1), y), (min(unique_width - 1, x + 1), y)]
            neighbors.extend([(x, max(0, y - 1)), (x, min(height - 1, y + 1))])
            ice_adjacency_rows[y][x] = bool(ice_rows[y][x]) or any(bool(ice_rows[ny][nx]) for nx, ny in neighbors)
        if wrap_x and width > unique_width:
            ice_adjacency_rows[y][-1] = ice_adjacency_rows[y][0]

    shelf_model = _shelf_and_sediment_model(rows, sea_level, tectonic_model)
    shelf_rows = shelf_model.get("shelf_rows") or []
    if wrap_x:
        for row in shelf_rows:
            if len(row) > unique_width:
                row[-1] = row[0]
        for row in shelf_model.get("sediment_thickness_rows_m") or []:
            if len(row) > unique_width:
                row[-1] = row[0]
    # The stored render-pixel resolution is not the spacing of the compact
    # scientific sample grid.  Using it here made a 257-column planet appear
    # roughly thirty times more finely sampled and classified ordinary rolling
    # terrain as mountains. Derive from the grid's physical footprint unless
    # an explicit sample spacing is available.
    sampled_extent_m = float(
        refreshed.get("region_width_m")
        or refreshed.get("circumference_m")
        or 0.0
    )
    derived_grid_spacing_m = sampled_extent_m / max(1, unique_width - 1)
    cell_spacing_m = float(
        refreshed.get("sample_spacing_x_m")
        or derived_grid_spacing_m
        or refreshed.get("equator_resolution_m_per_px")
        or 1.0
    )
    mountain_rows, mountain_relief_threshold_m = _mountain_morphology_mask(
        rows,
        land_rows,
        cell_spacing_m,
        wrap_x=wrap_x,
    )
    coastal_gradients = []
    shelf_cell_count = 0
    for y in range(height):
        for x in range(unique_width):
            if shelf_rows and shelf_rows[y][x]:
                shelf_cell_count += 1
            if not coastal_rows[y][x]:
                continue
            left = float(rows[y][(x - 1) % unique_width if wrap_x else max(0, x - 1)])
            right = float(rows[y][(x + 1) % unique_width if wrap_x else min(unique_width - 1, x + 1)])
            up = float(rows[max(0, y - 1)][x])
            down = float(rows[min(height - 1, y + 1)][x])
            coastal_gradients.append(math.hypot(right - left, down - up) / max(1.0, 2.0 * cell_spacing_m))

    land_fraction = weighted_land / max(1e-9, total_weight)
    ocean_fraction = weighted_ocean / max(1e-9, total_weight)
    ice_weight = 0.0
    for y in range(height):
        weight = max(1e-6, math.cos((0.5 - y / max(1, height - 1)) * math.pi)) if not regional else 1.0
        ice_weight += sum(bool(ice_rows[y][x]) for x in range(unique_width)) * weight
    ice_fraction = ice_weight / max(1e-9, total_weight)
    sample_count = max(1, len(values))
    hypsometry = dict(refreshed.get("hypsometry_summary") or {})
    hypsometry.update({
        "broad_plain_fraction": round(sum(-2000.0 <= value <= 1000.0 for value in values) / sample_count, 3),
        "mountain_fraction_above_2000m": round(sum(value > 2000.0 for value in values) / sample_count, 3),
        "deep_basin_fraction_below_minus_2000m": round(sum(value < -2000.0 for value in values) / sample_count, 3),
        "land_fraction": round(land_fraction, 4),
        "ocean_fraction": round(ocean_fraction, 4),
        "ice_fraction": round(ice_fraction, 4),
        "continental_shelf_fraction": round(shelf_cell_count / max(1, unique_width * height), 4),
        "area_weighting": "spherical_cosine_latitude" if not regional else "local_equal_area_approximation",
        "duplicate_longitude_seam_excluded": bool(wrap_x and width > unique_width),
    })
    shelf_model["morphology_summary"] = {
        "mean_coastal_gradient": round(sum(coastal_gradients) / max(1, len(coastal_gradients)), 6),
        "mean_resolved_shelf_width_km": round(shelf_cell_count * cell_spacing_m / max(1, sum(sum(bool(v) for v in row[:unique_width]) for row in coastal_rows)) / 1000.0, 2),
        "coastal_sample_count": len(coastal_gradients),
    }
    refreshed.update({
        "min_elevation_m": round(min(values), 1),
        "max_elevation_m": round(max(values), 1),
        "sea_level_m": None if sea_level is None else round(sea_level, 2),
        "sea_level_resolution": sea_level_resolution,
        "surface_masks": {
            **prior_masks,
            "land_rows": land_rows,
            "ocean_rows": ocean_rows,
            "coastal_rows": coastal_rows,
            "ice_rows": ice_rows,
            "ice_adjacency_rows": ice_adjacency_rows,
            "continental_shelf_rows": shelf_rows,
            "mountain_rows": mountain_rows,
        },
        "hypsometry_summary": hypsometry,
        "shelf_sediment_model": shelf_model,
        "derivative_model_version": HEIGHTMAP_DERIVATIVE_MODEL_VERSION,
        "mountain_morphology": {
            "model": "resolved_local_relief_v1",
            "relief_threshold_m": round(mountain_relief_threshold_m, 2),
            "mountain_cell_fraction": round(
                sum(mountain_rows[y][x] >= 0.35 for y in range(height) for x in range(unique_width))
                / max(1, height * unique_width),
                4,
            ),
            "purpose": "localize_subgrid_orogenic_relief_to_resolved_mountain_terrain",
        },
    })
    refreshed["source_heightfield_fingerprint"] = _heightfield_fingerprint(rows, refreshed.get("sea_level_m"))
    refreshed["derivatives"] = {
        "model_version": HEIGHTMAP_DERIVATIVE_MODEL_VERSION,
        "source_heightfield_fingerprint": refreshed["source_heightfield_fingerprint"],
        "status": "current",
    }
    return refreshed


def heightmap_derivatives_are_current(heightmap):
    if not isinstance(heightmap, dict):
        return False
    grid = heightmap.get("sample_grid") if isinstance(heightmap.get("sample_grid"), dict) else {}
    rows = grid.get("rows") if isinstance(grid.get("rows"), list) else []
    if not rows:
        return False
    derivatives = heightmap.get("derivatives") if isinstance(heightmap.get("derivatives"), dict) else {}
    return (
        derivatives.get("model_version") == HEIGHTMAP_DERIVATIVE_MODEL_VERSION
        and derivatives.get("source_heightfield_fingerprint") == _heightfield_fingerprint(rows, heightmap.get("sea_level_m"))
    )


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
    explicit_crater_model = isinstance(crater_model, dict)

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
            # Explicit impacts are applied in a second pass after the
            # pre-impact sea level is known.  Passing an empty catalogue here
            # also disables the legacy generic crater stamp without changing
            # dry worlds that do not use an explicit crater model.
            wave_craters = {} if explicit_crater_model else crater_model
            normalized = _wave_height(nx, ny, terrain, tectonic_model=sampled_tectonic_model, crater_model=wave_craters, crater_spatial_index=None, map_seed=map_seed)
            elevation = midpoint + normalized * half_range
            elevation = round(_clamp(elevation, min_elevation, max_elevation), 1)
            row_values.append(elevation)
            sample_positions.append((col, row, nx, ny, elevation))
        if row_values:
            row_values[-1] = row_values[0]
        sample_values.extend(row_values)
        rows.append(row_values)

    equivalent_global_water_depth_m = max(
        0.0,
        float(
            hydrology.get(
                "equivalent_global_water_depth_m",
                heightfield.get("equivalent_global_water_depth_m", 0.0),
            )
            or 0.0
        ),
    )
    preliminary_sea_level = sea_level
    if equivalent_global_water_depth_m > 0.0 and sample_values and not bool(heightfield.get("sea_level_locked")):
        preliminary_sea_level = sea_level_for_equivalent_water_depth(
            rows, equivalent_global_water_depth_m, wrap_x=True,
        )
    elif target_ocean_fraction > 0.0 and sample_values and not bool(heightfield.get("sea_level_locked")):
        preliminary_sorted = sorted(sample_values)
        preliminary_index = max(
            0,
            min(
                len(preliminary_sorted) - 1,
                int(round(target_ocean_fraction * (len(preliminary_sorted) - 1))),
            ),
        )
        preliminary_sea_level = preliminary_sorted[preliminary_index]

    crater_surface_audit = {"status": "not_applicable"}
    if explicit_crater_model:
        crater_model, crater_surface_audit = condition_crater_model_to_surface(
            crater_model, terrain, rows, preliminary_sea_level,
        )
        crater_spatial_index = _crater_spatial_index(crater_model)
        for row_index in range(sample_height):
            ny = row_index / max(1, sample_height - 1)
            for col_index in range(sample_width):
                nx = 0.0 if col_index == sample_width - 1 else col_index / max(1, sample_width - 1)
                rows[row_index][col_index] = round(
                    _clamp(
                        rows[row_index][col_index]
                        + _crater_height_adjustment_m(
                            nx, ny, crater_model, crater_spatial_index,
                        ),
                        min_elevation,
                        max_elevation,
                    ),
                    1,
                )
            rows[row_index][-1] = rows[row_index][0]
        sample_values = [value for row_values in rows for value in row_values]
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
    if equivalent_global_water_depth_m > 0.0 and sample_values and not bool(heightfield.get("sea_level_locked")):
        sea_level = sea_level_for_equivalent_water_depth(
            rows,
            equivalent_global_water_depth_m,
            wrap_x=True,
        )
    elif target_ocean_fraction > 0.0 and sample_values and not bool(heightfield.get("sea_level_locked")):
        # Compatibility for explicitly authored legacy ocean-coverage targets.
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
    shelf_model = _shelf_and_sediment_model(rows, sea_level_value, sampled_tectonic_model)

    model = {
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
        "equivalent_global_water_depth_m": round(equivalent_global_water_depth_m, 2),
        "sea_level_resolution": (
            "volume_balance_against_generated_hypsometry"
            if equivalent_global_water_depth_m > 0.0
            else ("authored_coverage_compatibility" if target_ocean_fraction > 0.0 else "dry_surface")
        ),
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
            "continental_shelf_rows": shelf_model["shelf_rows"],
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
            "continental_shelf_fraction": shelf_model["shelf_fraction"],
        },
        "shelf_sediment_model": shelf_model,
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
        "crater_surface_resolution": crater_surface_audit,
    }
    return refresh_heightmap_derivatives(model, tectonic_model=sampled_tectonic_model)


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
