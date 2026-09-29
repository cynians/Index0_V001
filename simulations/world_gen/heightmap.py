"""Derive planetary terrain from causal world-generation state.

Architecture invariants: ontology data is the sole durable entity/semantic
authority; heightfields and lookup tables are disposable products and caches.
No generated planet currently needs backward-compatible regeneration.

LOD contract: the full-planet heightmap is canonical LOD0 scientific truth;
its sample support must be sufficient for continents, basins, mountain systems,
and parent conditions. Child heightmaps are parent samples plus bounded
child-scale residuals, never a second root-generation path.
"""

import copy
import hashlib
import json
import math
from functools import lru_cache

try:
    import numpy as np
except ImportError:  # pragma: no cover - supported fallback for minimal installs
    np = None

from simulations.world_gen.map_seed import resolved_map_seed, seed_range as _uncached_seed_range
from simulations.world_gen.seafloor_spreading import plate_cooling_subsidence_m, seafloor_age_myr
from simulations.world_gen.mechanical_lithology import terrain_response_factors
from simulations.world_gen.terrain_seed import (
    PLANETARY_CANVAS_HEIGHT_PX,
    PLANETARY_CANVAS_WIDTH_PX,
)

_NOISE_CORNER_CACHE = {}

DEFORMATION_STATE_MODEL_VERSION = "planetary-deformation-v1-reduced-flexure"

# LOD0 carries only the global causal scaffold needed by climate, coast,
# materials, and child LODs. Province-scale geometry and high-frequency
# relief are regenerated below LOD0 from this parent truth.
CANONICAL_LOD0_SAMPLE_WIDTH = 513
CANONICAL_LOD0_SAMPLE_HEIGHT = 257
CANONICAL_LOD0_BENCHMARK_DIMENSIONS = (1025, 513)
CANONICAL_LOD0_RESOLUTION_VERSION = "lod0-global-scaffold-v2"


def _heightmap_sample_dimensions(canvas, heightfield):
    """Return an explicit canonical LOD0 scientific grid size.

    Authored callers may request a bounded benchmark or fixture grid through
    ``heightfield.scientific_sample_dimensions``.  The ordinary world-gen
    route always uses the canonical LOD0 dimensions and never derives science
    resolution from the render canvas.
    """
    requested = heightfield.get("scientific_sample_dimensions")
    if requested is None:
        requested = canvas.get("scientific_sample_dimensions")
    if isinstance(requested, dict):
        requested = (requested.get("width"), requested.get("height"))
    if isinstance(requested, (list, tuple)) and len(requested) == 2:
        try:
            width = int(requested[0])
            height = int(requested[1])
        except (TypeError, ValueError):
            width = height = 0
        if width >= 3 and height >= 3 and width % 2 == 1 and height % 2 == 1:
            return width, height, "explicit"
    return CANONICAL_LOD0_SAMPLE_WIDTH, CANONICAL_LOD0_SAMPLE_HEIGHT, "canonical_lod0"


def _lod0_evaluation_dimensions(sample_width, sample_height, resolution_mode):
    """Use half-resolution causal synthesis for the global scaffold.

    LOD0 retains a 513x257 consumer grid, but expensive procedural geology is
    evaluated on 257x129 anchors. Regional regeneration owns wavelengths below
    that support and never inherits invented high-frequency global detail.
    """
    if resolution_mode != "canonical_lod0":
        return sample_width, sample_height
    return (sample_width - 1) // 2 + 1, (sample_height - 1) // 2 + 1


def _clamped_cubic_axis(values, positions, *, periodic):
    """Catmull-Rom along the last axis at fractional ``positions``.

    ``periodic`` rows repeat their first sample as the last (the longitude
    seam), so the period is ``n - 1``.  Results are clamped between the two
    samples that bracket each position.
    """
    values = np.asarray(values, dtype=np.float64)
    count = values.shape[-1]
    positions = np.asarray(positions, dtype=np.float64)
    base = np.floor(positions).astype(np.int64)
    fraction = positions - base
    if periodic and count > 2:
        period = count - 1
        index = [np.mod(base + offset, period) for offset in (-1, 0, 1, 2)]
    else:
        index = [np.clip(base + offset, 0, count - 1) for offset in (-1, 0, 1, 2)]
    p0, p1, p2, p3 = (values[..., item] for item in index)
    t = fraction
    cubic = 0.5 * (
        2.0 * p1
        + (-p0 + p2) * t
        + (2.0 * p0 - 5.0 * p1 + 4.0 * p2 - p3) * t * t
        + (-p0 + 3.0 * p1 - 3.0 * p2 + p3) * t * t * t
    )
    return np.clip(cubic, np.minimum(p1, p2), np.maximum(p1, p2))


def _resample_height_rows(rows, target_width, target_height):
    if not rows or not rows[0]:
        return rows
    source_height = len(rows)
    source_width = min(len(row) for row in rows)
    if (source_width, source_height) == (target_width, target_height):
        return [list(row[:source_width]) for row in rows]
    if np is not None:
        # Clamped Catmull-Rom, not linear: linear interpolation of the
        # 257 x 129 causal anchors gave every anchor cell flat facets, which
        # hillshade rendered as stacked blocks along ranges and terraces on
        # plateaus.  The cubic is C1 between anchors and is held within the
        # two neighbouring anchors, so steep margins cannot ring.
        source = np.asarray([row[:source_width] for row in rows], dtype=np.float64)
        horizontal = _clamped_cubic_axis(
            source, (source_width - 1) * np.arange(target_width) / max(1, target_width - 1), periodic=True,
        )
        result = _clamped_cubic_axis(
            horizontal.T, (source_height - 1) * np.arange(target_height) / max(1, target_height - 1), periodic=False,
        ).T
        result[:, -1] = result[:, 0]
        return [[round(float(value), 1) for value in row] for row in result]

    result = []
    for target_y in range(target_height):
        source_y = target_y * (source_height - 1) / max(1, target_height - 1)
        y0 = int(math.floor(source_y))
        y1 = min(source_height - 1, y0 + 1)
        ty = source_y - y0
        row = []
        for target_x in range(target_width):
            source_x = target_x * (source_width - 1) / max(1, target_width - 1)
            x0 = int(math.floor(source_x))
            x1 = min(source_width - 1, x0 + 1)
            tx = source_x - x0
            top = float(rows[y0][x0]) * (1.0 - tx) + float(rows[y0][x1]) * tx
            bottom = float(rows[y1][x0]) * (1.0 - tx) + float(rows[y1][x1]) * tx
            row.append(round(top * (1.0 - ty) + bottom * ty, 1))
        row[-1] = row[0]
        result.append(row)
    return result


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


def _continent_signal(
    nx,
    ny,
    map_seed="",
    tectonic_model=None,
    lod0_synthesis=False,
    lithosphere_sample=None,
):
    """Continental crust assembled from cratons, terranes, sutures and rifts."""
    model = _continental_process_model(str(map_seed or ""))
    if lod0_synthesis:
        broad_noise = _fbm_noise(
            map_seed,
            "lod0_continental_scaffold",
            nx,
            ny,
            base_cells=5,
            octaves=2,
            gain=0.48,
        )
        if isinstance(tectonic_model, dict) and tectonic_model.get("plates"):
            continental = _clamp(
                (lithosphere_sample or _sample_lithosphere(tectonic_model, nx, ny)).get("continental_fraction", 0.5),
                0.0,
                1.0,
            )
            signal = -0.56 + continental * 0.92 + broad_noise * 0.10
        else:
            # A dozen broad nuclei are sufficient to anchor a credible global
            # silhouette. Sutures, rifts, embayments, and coast roughness are
            # intentionally deferred to regional regeneration.
            cratons = model["cratons"]
            stride = max(1, len(cratons) // 12)
            lithosphere = 0.0
            for cx, cy, width, height, angle, strength in cratons[::stride][:12]:
                dx, dy = _wrapped_delta(nx, cx), ny - cy
                rx = dx * math.cos(angle) - dy * math.sin(angle)
                ry = dx * math.sin(angle) + dy * math.cos(angle)
                distance = (rx / max(0.06, width * 1.8)) ** 2 + (ry / max(0.05, height * 1.8)) ** 2
                lithosphere = max(lithosphere, math.exp(-(distance * 0.72)) * strength)
            signal = -0.56 + lithosphere * 0.92 + broad_noise * 0.10
        latitude_taper = 1.0 - max(0.0, abs(ny - 0.5) * 2.0 - 0.84) * 1.15
        return _clamp(signal * max(0.42, latitude_taper), -0.9, 1.0)

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
    """A sinuous belt around the planet whose centreline wanders with seamless noise.

    (Formerly sine curves in longitude, which drew one regular diagonal wave
    across the map and broke at the date line.)
    """
    wander = sphere_signed_table(f"belt:{float(phase):.6f}", "centreline", nx, 0.5, features=1.3, octaves=3)
    center = latitude_center + amplitude * 1.6 * wander
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


# Isostatic contrast between the median continental-crust surface and the
# median oceanic-crust floor.  Earth's hypsometric peaks sit about 4.6 km
# apart (+0.1 km and -4.5 km); crustal thickness and density set it, not the
# water inventory.  The water then decides where sea level falls.
CRUSTAL_CONTRAST_TARGET_M = 4600.0


def ocean_crust_weight(continental_fraction):
    """0 on continental crust, 1 on oceanic crust (smoothstep in between)."""
    fraction = continental_fraction
    if np is not None and isinstance(fraction, np.ndarray):
        fraction = np.clip(fraction, 0.0, 1.0)
    else:
        fraction = _clamp(fraction, 0.0, 1.0)
    return 1.0 - fraction * fraction * (3.0 - 2.0 * fraction)


def _crustal_freeboard_calibration(rows, width, height, tectonic_model):
    """Measure the continent/ocean contrast of freshly sampled LOD0 relief.

    The relief generator stacks several continental and oceanic terms and is
    then stretched onto the planet's elevation range, which left continental
    crust about 8 km above the oceanic floor (Earth: about 4.6 km).  With any
    realistic water inventory that stranded coastlines at the foot of the
    continental slope and continents kilometres above sea level.  Oceanic
    crust is raised to the Earth contrast; continents and all relief within
    the ocean (ridges, abyssal plains, trenches) keep their shape.  Only an
    excess is removed; a smaller contrast is left alone.
    """
    if np is None or not rows or not isinstance(tectonic_model, dict):
        return {}
    u_values = np.asarray([0.0 if col == width - 1 else col / max(1, width - 1) for col in range(width)])
    v_values = np.arange(height, dtype=np.float64) / max(1, height - 1)
    continental, _age, _oceanic = _sample_lithosphere_grid(tectonic_model, u_values[None, :], v_values[:, None])
    weight = ocean_crust_weight(continental)
    elevation = np.asarray(rows, dtype=np.float64)
    continental_cells = elevation[weight < 0.1]
    oceanic_cells = elevation[weight > 0.9]
    minimum_cells = max(8, int(0.02 * elevation.size))
    if continental_cells.size < minimum_cells or oceanic_cells.size < minimum_cells:
        return {}
    contrast = float(np.median(continental_cells) - np.median(oceanic_cells))
    return {
        "model": "isostatic_crustal_contrast_v1",
        "measured_contrast_m": round(contrast, 1),
        "target_contrast_m": CRUSTAL_CONTRAST_TARGET_M,
        "ocean_shift_m": round(max(0.0, contrast - CRUSTAL_CONTRAST_TARGET_M), 1),
    }


def _apply_crustal_freeboard_calibration(rows, width, height, tectonic_model, calibration, *, min_elevation, max_elevation):
    shift = float(calibration.get("ocean_shift_m") or 0.0)
    u_values = np.asarray([0.0 if col == width - 1 else col / max(1, width - 1) for col in range(width)])
    v_values = np.arange(height, dtype=np.float64) / max(1, height - 1)
    continental, _age, _oceanic = _sample_lithosphere_grid(tectonic_model, u_values[None, :], v_values[:, None])
    raised = np.asarray(rows, dtype=np.float64) + ocean_crust_weight(continental) * shift
    raised = np.clip(np.round(raised, 1), min_elevation, max_elevation)
    return raised.tolist()


def crustal_freeboard_shift_at(nx, ny, tectonic_model, root_heightmap):
    """Calibration offset at one planet UV point (regional production heights)."""
    calibration = (root_heightmap or {}).get("crustal_freeboard_calibration") if isinstance(root_heightmap, dict) else None
    shift = float((calibration or {}).get("ocean_shift_m") or 0.0)
    if shift <= 0.0 or not isinstance(tectonic_model, dict):
        return 0.0
    continental = _sample_lithosphere(tectonic_model, nx, ny).get("continental_fraction", 0.5)
    return float(ocean_crust_weight(continental)) * shift


# Lifts oceanic crust from the crustal base (-3.92 km) to a ridge crest ~3 km
# below the continental end member (+0.98 + 0.78 + 0.36 km).
OCEANIC_CREST_OFFSET_M = 3040.0


def _continuous_crustal_base_height_m(continental_fraction):
    """Resolve freeboard from continuous crustal buoyancy, never plate ids."""
    fraction = _smoothstep(_clamp(continental_fraction, 0.0, 1.0))
    # The end members preserve the former global hypsometric contrast while
    # transitional crust now crosses sea level without an ownership step.
    return _lerp(-3920.0, 980.0, fraction)


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


def _heightmap_tectonic_model(tectonic_model):
    if not isinstance(tectonic_model, dict):
        return tectonic_model
    segments = [
        segment
        for segment in (tectonic_model.get("boundary_segments") or [])
        if isinstance(segment, dict)
    ]
    sampled = dict(tectonic_model)
    sampled["boundary_segments"] = segments
    sampled["heightmap_boundary_segment_count"] = len(segments)
    sampled["original_boundary_segment_count"] = len(tectonic_model.get("boundary_segments") or [])
    sampled["_heightmap_boundary_spatial_index"] = _boundary_spatial_index(segments)
    orogen_model = tectonic_model.get("orogen_system_model") if isinstance(tectonic_model.get("orogen_system_model"), dict) else {}
    sampled["_heightmap_orogen_system_lookup"] = {
        str(system.get("id")): system
        for system in (orogen_model.get("systems") or [])
        if isinstance(system, dict) and system.get("id")
    }
    return sampled


def _ensure_heightmap_tectonic_model(tectonic_model):
    """Return a tectonic model with the heightfield lookup structures ready.

    Regional derivative refreshes are also called by older world-generation
    paths that pass the durable raw tectonic snapshot.  Keep those callers
    correct and fast by materializing the same private indexes used by the
    production height evaluator exactly once per model object.
    """
    if not isinstance(tectonic_model, dict):
        return tectonic_model
    segments = tectonic_model.get("boundary_segments") or []
    spatial_index = tectonic_model.get("_heightmap_boundary_spatial_index")
    system_lookup = tectonic_model.get("_heightmap_orogen_system_lookup")
    if (
        isinstance(spatial_index, dict)
        and isinstance(system_lookup, dict)
        and tectonic_model.get("heightmap_boundary_segment_count") == len(segments)
    ):
        return tectonic_model
    return _heightmap_tectonic_model(tectonic_model)


def _boundary_spatial_index(segments, bins_x=64, bins_y=32):
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
        margin = _clamp(segment.get("influence_width", 0.028), 0.012, 0.05) * 3.2
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


def _cross_range_band(signed_distance, center, width):
    width = max(1e-6, float(width))
    return math.exp(-(((float(signed_distance) - float(center)) / width) ** 2))


def _orogen_segment_forcing(nx, ny, segment, system, signed_normal_distance, influence):
    """Resolve one system segment into separate uplift/subsidence/volcanic forcing."""
    profile = system.get("forcing_profile") if isinstance(system.get("forcing_profile"), dict) else {}
    sides = system.get("sides") if isinstance(system.get("sides"), dict) else {}
    mechanism = str(system.get("mechanism") or "")
    width = _clamp(
        segment.get("influence_width", profile.get("reference_width", 0.028)),
        0.012,
        0.05,
    )
    segment_activity = _clamp(segment.get("activity_scale", 1.0), 0.25, 1.35)
    variation = profile.get("along_strike_variation") if isinstance(profile.get("along_strike_variation"), dict) else {}
    continuity_floor = _clamp(variation.get("minimum_continuity", 0.66), 0.45, 0.90)
    continuity = continuity_floor + (1.0 - continuity_floor) * _clamp((segment_activity - 0.25) / 1.10, 0.0, 1.0)
    peak_uplift = max(0.0, float(profile.get("rock_uplift_peak_m", 0.0) or 0.0))
    peak_subsidence = max(0.0, float(profile.get("tectonic_subsidence_peak_m", 0.0) or 0.0))
    peak_volcanic = max(0.0, float(profile.get("volcanic_construction_peak_m", 0.0) or 0.0))
    peak_outer_bulge = max(0.0, float(profile.get("outer_bulge_peak_m", 0.0) or 0.0))
    response = {
        "rock_uplift_m": 0.0,
        "tectonic_subsidence_m": 0.0,
        "volcanic_construction_m": 0.0,
        "outer_bulge_m": 0.0,
        "convergent_influence": 0.0,
        "divergent_influence": 0.0,
        "trench_influence": 0.0,
        "transform_influence": 0.0,
    }

    if mechanism == "continental_collision":
        hinterland_side = 1.0 if int(sides.get("hinterland_normal_side", 1) or 1) >= 0 else -1.0
        foreland_side = -hinterland_side
        core = _cross_range_band(signed_normal_distance, hinterland_side * width * 0.24, width * 0.68)
        fold_thrust = _cross_range_band(signed_normal_distance, foreland_side * width * 0.52, width * 0.72)
        foreland = _cross_range_band(signed_normal_distance, foreland_side * width * 1.48, width * 0.52)
        outer_bulge = _cross_range_band(signed_normal_distance, foreland_side * width * 2.22, width * 0.58)
        response["rock_uplift_m"] = min(peak_uplift * 1.08, peak_uplift * (core * 0.76 + fold_thrust * 0.38)) * continuity
        response["tectonic_subsidence_m"] = peak_subsidence * foreland * continuity
        response["outer_bulge_m"] = peak_outer_bulge * outer_bulge
        response["convergent_influence"] = max(influence, core, fold_thrust)
    elif mechanism in {"ocean_continent_subduction", "island_arc_subduction"}:
        overriding_side = 1.0 if int(sides.get("overriding_normal_side", 1) or 1) >= 0 else -1.0
        # Keep the volcanic/mountain arc inland of the trench and forearc.
        # The former compact profile welded the entire active margin to the
        # coastline and read as one narrow wall at planetary scale.
        trench = _cross_range_band(signed_normal_distance, -overriding_side * width * 0.62, width * 0.34)
        accretionary_margin = _cross_range_band(signed_normal_distance, -overriding_side * width * 0.10, width * 0.38)
        forearc = _cross_range_band(signed_normal_distance, overriding_side * width * 0.44, width * 0.46)
        arc = _cross_range_band(signed_normal_distance, overriding_side * width * 1.24, width * 0.58)
        backarc = _cross_range_band(signed_normal_distance, overriding_side * width * 2.08, width * 0.72)
        segment_x1 = float(segment.get("x1", 0.0) or 0.0)
        segment_x2 = float(segment.get("x2", 0.0) or 0.0)
        midpoint_x = (segment_x1 + _wrapped_delta(segment_x2, segment_x1) * 0.5) % 1.0
        midpoint_y = (float(segment.get("y1", 0.5) or 0.5) + float(segment.get("y2", 0.5) or 0.5)) * 0.5
        phase = float(variation.get("phase", 0.0) or 0.0)
        frequency = float(variation.get("frequency", 4.0) or 4.0)
        arc_pulse = max(0.0, math.sin(math.tau * frequency * (midpoint_x + midpoint_y * 0.618) + phase)) ** 4
        response["rock_uplift_m"] = peak_uplift * (arc * 0.72 + accretionary_margin * 0.22) * continuity
        response["tectonic_subsidence_m"] = peak_subsidence * (trench + forearc * 0.10 + backarc * 0.18)
        response["volcanic_construction_m"] = peak_volcanic * arc * (0.28 + arc_pulse * 0.72)
        response["convergent_influence"] = max(influence, arc, accretionary_margin)
        response["trench_influence"] = trench
    elif mechanism == "continental_rift":
        rift_axis = _cross_range_band(signed_normal_distance, 0.0, width * 0.42)
        shoulder_a = _cross_range_band(signed_normal_distance, width * 0.92, width * 0.48)
        shoulder_b = _cross_range_band(signed_normal_distance, -width * 0.92, width * 0.48)
        response["rock_uplift_m"] = peak_uplift * max(shoulder_a, shoulder_b) * continuity
        response["tectonic_subsidence_m"] = peak_subsidence * rift_axis
        response["divergent_influence"] = max(rift_axis, shoulder_a, shoulder_b)
    elif mechanism == "oceanic_spreading":
        ridge = _cross_range_band(signed_normal_distance, 0.0, width * 0.92)
        axial_valley = _cross_range_band(signed_normal_distance, 0.0, width * 0.22)
        # The ridge's elevation is thermal: it comes from the age-depth law
        # on its own segmented axis, not from a band along the boundary.
        response["rock_uplift_m"] = 0.0
        response["tectonic_subsidence_m"] = peak_subsidence * axial_valley
        response["divergent_influence"] = ridge
    elif mechanism in {"transpressional_strike_slip", "transtensional_strike_slip", "strike_slip"}:
        fault_zone = _cross_range_band(signed_normal_distance, 0.0, width * 0.40)
        if mechanism == "transpressional_strike_slip":
            response["rock_uplift_m"] = peak_uplift * fault_zone * continuity
            response["tectonic_subsidence_m"] = peak_subsidence * fault_zone * 0.15
        elif mechanism == "transtensional_strike_slip":
            response["rock_uplift_m"] = peak_uplift * fault_zone * 0.22
            response["tectonic_subsidence_m"] = peak_subsidence * fault_zone * continuity
        else:
            response["rock_uplift_m"] = peak_uplift * fault_zone * 0.42
            response["tectonic_subsidence_m"] = peak_subsidence * fault_zone * 0.28
        response["transform_influence"] = fault_zone
    return response


def _orogen_forcing_at(nx, ny, tectonic_model):
    """Resolve system forcing without collapsing its physical components."""
    orogen_lookup = tectonic_model.get("_heightmap_orogen_system_lookup")
    if not isinstance(orogen_lookup, dict):
        orogen_model = tectonic_model.get("orogen_system_model") if isinstance(tectonic_model.get("orogen_system_model"), dict) else {}
        orogen_lookup = {
            str(system.get("id")): system
            for system in (orogen_model.get("systems") or [])
            if isinstance(system, dict) and system.get("id")
        }
    combined_by_system = {}
    for segment in _nearby_boundary_segments(tectonic_model, nx, ny):
        distance = _wrapped_point_segment_distance(
            nx, ny,
            float(segment.get("x1", 0.0) or 0.0), float(segment.get("y1", 0.0) or 0.0),
            float(segment.get("x2", 0.0) or 0.0), float(segment.get("y2", 0.0) or 0.0),
        )
        influence_width = _clamp(segment.get("influence_width", 0.028), 0.012, 0.05)
        if distance > influence_width * 3.2:
            continue
        influence = math.exp(-((distance / influence_width) ** 2))
        influence = influence ** 1.18 * _clamp(segment.get("activity_scale", 1.0), 0.25, 1.35)
        normal_x = float(segment.get("normal_x", 0.0) or 0.0)
        normal_y = float(segment.get("normal_y", 0.0) or 0.0)
        segment_x1 = float(segment.get("x1", 0.0) or 0.0)
        segment_x2 = float(segment.get("x2", 0.0) or 0.0)
        midpoint_x = (segment_x1 + _wrapped_delta(segment_x2, segment_x1) * 0.5) % 1.0
        midpoint_y = (float(segment.get("y1", 0.0) or 0.0) + float(segment.get("y2", 0.0) or 0.0)) * 0.5
        signed_distance = _wrapped_delta(nx, midpoint_x) * normal_x + (ny - midpoint_y) * normal_y
        system_id = str(segment.get("orogen_system_id") or "")
        system = orogen_lookup.get(system_id)
        if not isinstance(system, dict):
            continue
        response = _orogen_segment_forcing(nx, ny, segment, system, signed_distance, influence)
        response["crustal_thickening_index"] = (
            float((system.get("forcing_profile") or {}).get("crustal_thickening_index", 0.0) or 0.0)
            * float(response.get("convergent_influence", 0.0) or 0.0)
        )
        response["cumulative_strain_index"] = max(
            float(response.get("convergent_influence", 0.0) or 0.0),
            float(response.get("divergent_influence", 0.0) or 0.0),
            float(response.get("transform_influence", 0.0) or 0.0),
        )
        combined = combined_by_system.setdefault(system_id, {key: 0.0 for key in response})
        for key, value in response.items():
            previous = float(combined.get(key, 0.0) or 0.0)
            current = float(value or 0.0)
            high, low = max(previous, current), min(previous, current)
            combined[key] = high * ((1.0 + (low / high) ** 6.0) ** (1.0 / 6.0)) if high > 0.0 else 0.0
    total = {
        "rock_uplift_m": 0.0,
        "tectonic_subsidence_m": 0.0,
        "volcanic_construction_m": 0.0,
        "outer_bulge_m": 0.0,
        "crustal_thickening_index": 0.0,
        "cumulative_strain_index": 0.0,
        "convergent_influence": 0.0,
        "divergent_influence": 0.0,
        "trench_influence": 0.0,
        "transform_influence": 0.0,
    }
    for forcing in combined_by_system.values():
        for key in ("rock_uplift_m", "tectonic_subsidence_m", "volcanic_construction_m", "outer_bulge_m"):
            total[key] += float(forcing.get(key, 0.0) or 0.0)
        for key in ("crustal_thickening_index", "cumulative_strain_index", "convergent_influence", "divergent_influence", "trench_influence", "transform_influence"):
            total[key] = max(total[key], float(forcing.get(key, 0.0) or 0.0))
    return total


_OROGEN_FORCING_SUM_KEYS = (
    "rock_uplift_m",
    "tectonic_subsidence_m",
    "volcanic_construction_m",
    "outer_bulge_m",
)
_OROGEN_FORCING_MAX_KEYS = (
    "crustal_thickening_index",
    "cumulative_strain_index",
    "convergent_influence",
    "divergent_influence",
    "trench_influence",
    "transform_influence",
)


def _np_smoothstep(values):
    values = np.clip(values, 0.0, 1.0)
    return values * values * (3.0 - 2.0 * values)


def _np_band(signed_distance, center, width):
    width = max(1e-6, float(width))
    return np.exp(-(((signed_distance - float(center)) / width) ** 2))


def _np_segment_forcing(segment, system, signed_distance, influence):
    """Array form of ``_orogen_segment_forcing`` for one segment."""
    profile = system.get("forcing_profile") if isinstance(system.get("forcing_profile"), dict) else {}
    sides = system.get("sides") if isinstance(system.get("sides"), dict) else {}
    mechanism = str(system.get("mechanism") or "")
    width = _clamp(
        segment.get("influence_width", profile.get("reference_width", 0.028)),
        0.012,
        0.05,
    )
    segment_activity = _clamp(segment.get("activity_scale", 1.0), 0.25, 1.35)
    variation = profile.get("along_strike_variation") if isinstance(profile.get("along_strike_variation"), dict) else {}
    continuity_floor = _clamp(variation.get("minimum_continuity", 0.66), 0.45, 0.90)
    continuity = continuity_floor + (1.0 - continuity_floor) * _clamp((segment_activity - 0.25) / 1.10, 0.0, 1.0)
    peak_uplift = max(0.0, float(profile.get("rock_uplift_peak_m", 0.0) or 0.0))
    peak_subsidence = max(0.0, float(profile.get("tectonic_subsidence_peak_m", 0.0) or 0.0))
    peak_volcanic = max(0.0, float(profile.get("volcanic_construction_peak_m", 0.0) or 0.0))
    peak_outer_bulge = max(0.0, float(profile.get("outer_bulge_peak_m", 0.0) or 0.0))
    zero = np.zeros_like(signed_distance)
    response = {
        "rock_uplift_m": zero,
        "tectonic_subsidence_m": zero,
        "volcanic_construction_m": zero,
        "outer_bulge_m": zero,
        "convergent_influence": zero,
        "divergent_influence": zero,
        "trench_influence": zero,
        "transform_influence": zero,
    }
    if mechanism == "continental_collision":
        hinterland_side = 1.0 if int(sides.get("hinterland_normal_side", 1) or 1) >= 0 else -1.0
        foreland_side = -hinterland_side
        core = _np_band(signed_distance, hinterland_side * width * 0.24, width * 0.68)
        fold_thrust = _np_band(signed_distance, foreland_side * width * 0.52, width * 0.72)
        foreland = _np_band(signed_distance, foreland_side * width * 1.48, width * 0.52)
        outer_bulge = _np_band(signed_distance, foreland_side * width * 2.22, width * 0.58)
        response["rock_uplift_m"] = np.minimum(peak_uplift * 1.08, peak_uplift * (core * 0.76 + fold_thrust * 0.38)) * continuity
        response["tectonic_subsidence_m"] = peak_subsidence * foreland * continuity
        response["outer_bulge_m"] = peak_outer_bulge * outer_bulge
        response["convergent_influence"] = np.maximum(np.maximum(influence, core), fold_thrust)
    elif mechanism in {"ocean_continent_subduction", "island_arc_subduction"}:
        overriding_side = 1.0 if int(sides.get("overriding_normal_side", 1) or 1) >= 0 else -1.0
        trench = _np_band(signed_distance, -overriding_side * width * 0.62, width * 0.34)
        accretionary_margin = _np_band(signed_distance, -overriding_side * width * 0.10, width * 0.38)
        forearc = _np_band(signed_distance, overriding_side * width * 0.44, width * 0.46)
        arc = _np_band(signed_distance, overriding_side * width * 1.24, width * 0.58)
        backarc = _np_band(signed_distance, overriding_side * width * 2.08, width * 0.72)
        segment_x1 = float(segment.get("x1", 0.0) or 0.0)
        segment_x2 = float(segment.get("x2", 0.0) or 0.0)
        midpoint_x = (segment_x1 + _wrapped_delta(segment_x2, segment_x1) * 0.5) % 1.0
        midpoint_y = (float(segment.get("y1", 0.5) or 0.5) + float(segment.get("y2", 0.5) or 0.5)) * 0.5
        phase = float(variation.get("phase", 0.0) or 0.0)
        frequency = float(variation.get("frequency", 4.0) or 4.0)
        arc_pulse = max(0.0, math.sin(math.tau * frequency * (midpoint_x + midpoint_y * 0.618) + phase)) ** 4
        response["rock_uplift_m"] = peak_uplift * (arc * 0.72 + accretionary_margin * 0.22) * continuity
        response["tectonic_subsidence_m"] = peak_subsidence * (trench + forearc * 0.10 + backarc * 0.18)
        response["volcanic_construction_m"] = peak_volcanic * arc * (0.28 + arc_pulse * 0.72)
        response["convergent_influence"] = np.maximum(np.maximum(influence, arc), accretionary_margin)
        response["trench_influence"] = trench
    elif mechanism == "continental_rift":
        rift_axis = _np_band(signed_distance, 0.0, width * 0.42)
        shoulder_a = _np_band(signed_distance, width * 0.92, width * 0.48)
        shoulder_b = _np_band(signed_distance, -width * 0.92, width * 0.48)
        shoulders = np.maximum(shoulder_a, shoulder_b)
        response["rock_uplift_m"] = peak_uplift * shoulders * continuity
        response["tectonic_subsidence_m"] = peak_subsidence * rift_axis
        response["divergent_influence"] = np.maximum(rift_axis, shoulders)
    elif mechanism == "oceanic_spreading":
        ridge = _np_band(signed_distance, 0.0, width * 0.92)
        axial_valley = _np_band(signed_distance, 0.0, width * 0.22)
        # Thermal ridge elevation comes from the age-depth law (see scalar form).
        response["rock_uplift_m"] = ridge * 0.0
        response["tectonic_subsidence_m"] = peak_subsidence * axial_valley
        response["divergent_influence"] = ridge
    elif mechanism in {"transpressional_strike_slip", "transtensional_strike_slip", "strike_slip"}:
        fault_zone = _np_band(signed_distance, 0.0, width * 0.40)
        if mechanism == "transpressional_strike_slip":
            response["rock_uplift_m"] = peak_uplift * fault_zone * continuity
            response["tectonic_subsidence_m"] = peak_subsidence * fault_zone * 0.15
        elif mechanism == "transtensional_strike_slip":
            response["rock_uplift_m"] = peak_uplift * fault_zone * 0.22
            response["tectonic_subsidence_m"] = peak_subsidence * fault_zone * continuity
        else:
            response["rock_uplift_m"] = peak_uplift * fault_zone * 0.42
            response["tectonic_subsidence_m"] = peak_subsidence * fault_zone * 0.28
        response["transform_influence"] = fault_zone
    return response


def iter_orogen_segment_geometry(u_values, v_values, tectonic_model, *, cell_mask=None):
    """Yield the exact per-segment geometry used by ``_orogen_forcing_at``.

    Segments are grouped by orogen system.  Each yielded item carries the
    row/column slices a segment can reach, the validity mask (inside the
    3.2-width cutoff and ``cell_mask``), the signed normal distance and the
    activity-weighted influence, all as arrays over that sub-grid.
    """
    u_values = np.asarray(u_values, dtype=np.float64)
    v_values = np.asarray(v_values, dtype=np.float64)
    tectonic_model = tectonic_model if isinstance(tectonic_model, dict) else {}
    orogen_lookup = tectonic_model.get("_heightmap_orogen_system_lookup")
    if not isinstance(orogen_lookup, dict):
        orogen_model = tectonic_model.get("orogen_system_model") if isinstance(tectonic_model.get("orogen_system_model"), dict) else {}
        orogen_lookup = {
            str(system.get("id")): system
            for system in (orogen_model.get("systems") or [])
            if isinstance(system, dict) and system.get("id")
        }
    mask = None if cell_mask is None else np.asarray(cell_mask, dtype=bool)
    segments_by_system = {}
    for segment in tectonic_model.get("boundary_segments") or []:
        if not isinstance(segment, dict):
            continue
        system_id = str(segment.get("orogen_system_id") or "")
        if isinstance(orogen_lookup.get(system_id), dict):
            segments_by_system.setdefault(system_id, []).append(segment)
    for system_id, segments in segments_by_system.items():
        system = orogen_lookup[system_id]
        for segment in segments:
            x1 = float(segment.get("x1", 0.0) or 0.0)
            y1 = float(segment.get("y1", 0.0) or 0.0)
            x2 = float(segment.get("x2", 0.0) or 0.0)
            y2 = float(segment.get("y2", 0.0) or 0.0)
            unwrapped_x2 = x2
            if unwrapped_x2 - x1 > 0.5:
                unwrapped_x2 -= 1.0
            elif unwrapped_x2 - x1 < -0.5:
                unwrapped_x2 += 1.0
            influence_width = _clamp(segment.get("influence_width", 0.028), 0.012, 0.05)
            cutoff = influence_width * 3.2
            row_hits = np.nonzero(
                (v_values >= min(y1, y2) - cutoff) & (v_values <= max(y1, y2) + cutoff)
            )[0]
            if row_hits.size == 0:
                continue
            column_reach = np.zeros(u_values.size, dtype=bool)
            active_shifts = []
            for shift in (-2.0, -1.0, 0.0, 1.0, 2.0):
                shifted = u_values + shift
                reach = (
                    (shifted >= min(x1, unwrapped_x2) - cutoff)
                    & (shifted <= max(x1, unwrapped_x2) + cutoff)
                )
                if reach.any():
                    active_shifts.append(shift)
                    column_reach |= reach
            column_hits = np.nonzero(column_reach)[0]
            if column_hits.size == 0:
                continue
            rows = slice(int(row_hits[0]), int(row_hits[-1]) + 1)
            columns = slice(int(column_hits[0]), int(column_hits[-1]) + 1)
            pu = u_values[columns][None, :]
            pv = v_values[rows][:, None]
            dx = unwrapped_x2 - x1
            dy = y2 - y1
            length_sq = dx * dx + dy * dy
            distance = None
            # Only wrap copies that can reach the grid can be nearest within
            # the cutoff; every other copy is farther than the cutoff.
            for shift in active_shifts:
                px = pu + shift
                if length_sq <= 1e-12:
                    candidate = np.hypot(px - x1, pv - y1)
                else:
                    t = np.clip(((px - x1) * dx + (pv - y1) * dy) / length_sq, 0.0, 1.0)
                    candidate = np.hypot(px - (x1 + t * dx), pv - (y1 + t * dy))
                distance = candidate if distance is None else np.minimum(distance, candidate)
            valid = distance <= cutoff
            if mask is not None:
                valid &= mask[rows, columns]
            if not valid.any():
                continue
            influence = np.exp(-((distance / influence_width) ** 2)) ** 1.18 * _clamp(
                segment.get("activity_scale", 1.0), 0.25, 1.35
            )
            normal_x = float(segment.get("normal_x", 0.0) or 0.0)
            normal_y = float(segment.get("normal_y", 0.0) or 0.0)
            midpoint_x = (x1 + _wrapped_delta(x2, x1) * 0.5) % 1.0
            midpoint_y = (y1 + y2) * 0.5
            delta_u = pu - midpoint_x
            delta_u = np.where(delta_u > 0.5, delta_u - 1.0, np.where(delta_u < -0.5, delta_u + 1.0, delta_u))
            signed_distance = np.broadcast_to(
                delta_u * normal_x + (pv - midpoint_y) * normal_y,
                valid.shape,
            )
            yield {
                "system_id": system_id,
                "system": system,
                "segment": segment,
                "rows": rows,
                "columns": columns,
                "valid": valid,
                "distance": distance,
                "signed_distance": signed_distance,
                "influence": influence,
                "influence_width": influence_width,
            }


def orogen_forcing_grid(u_values, v_values, tectonic_model, *, cell_mask=None):
    """Evaluate ``_orogen_forcing_at`` for a whole grid of global UV samples.

    ``u_values`` are column coordinates and ``v_values`` row coordinates.  The
    per-system combination in the scalar path is an iterated L6 norm, which is
    order independent, so segments can be accumulated as ``sum(v**6)`` and
    finalised once per system.  Each segment only touches the rows and columns
    inside its own influence cutoff.
    """
    u_values = np.asarray(u_values, dtype=np.float64)
    v_values = np.asarray(v_values, dtype=np.float64)
    shape = (v_values.size, u_values.size)
    totals = {key: np.zeros(shape, dtype=np.float64) for key in (*_OROGEN_FORCING_SUM_KEYS, *_OROGEN_FORCING_MAX_KEYS)}
    response_keys = (*_OROGEN_FORCING_SUM_KEYS, *_OROGEN_FORCING_MAX_KEYS)

    def finalise(sixth_powers):
        for key in _OROGEN_FORCING_SUM_KEYS:
            totals[key] += sixth_powers[key] ** (1.0 / 6.0)
        for key in _OROGEN_FORCING_MAX_KEYS:
            np.maximum(totals[key], sixth_powers[key] ** (1.0 / 6.0), out=totals[key])

    current_system = None
    sixth_powers = None
    for item in iter_orogen_segment_geometry(u_values, v_values, tectonic_model, cell_mask=cell_mask):
        if item["system_id"] != current_system:
            if sixth_powers is not None:
                finalise(sixth_powers)
            current_system = item["system_id"]
            sixth_powers = {key: np.zeros(shape, dtype=np.float64) for key in response_keys}
        system = item["system"]
        valid = item["valid"]
        all_valid = bool(valid.all())
        response = _np_segment_forcing(item["segment"], system, item["signed_distance"], item["influence"])
        thickening = float((system.get("forcing_profile") or {}).get("crustal_thickening_index", 0.0) or 0.0)
        response["crustal_thickening_index"] = thickening * response["convergent_influence"]
        response["cumulative_strain_index"] = np.maximum(
            np.maximum(response["convergent_influence"], response["divergent_influence"]),
            response["transform_influence"],
        )
        rows, columns = item["rows"], item["columns"]
        for key in response_keys:
            value = response[key]
            if not np.any(value):
                continue
            values = np.broadcast_to(value, valid.shape)
            if not all_valid:
                values = np.where(valid, values, 0.0)
            # Repeated products instead of ``** 6.0``: a regional tile sits
            # inside every nearby segment's cutoff, and pow dominated the cost.
            square = values * values
            sixth_powers[key][rows, columns] += square * square * square
    if sixth_powers is not None:
        finalise(sixth_powers)
    return totals


_OROGEN_FORCING_CACHE_SIZE = 2
_orogen_forcing_cache = []


def cached_orogen_forcing_grid(u_values, v_values, tectonic_model):
    """Unmasked ``orogen_forcing_grid`` memoised per tectonic model and grid.

    Regional refinement refreshes a tile's derivatives several times with the
    same footprint and tectonic model; only the heightfield changes.  The key
    is the identity of the boundary segments and orogen systems, not of the
    model dict, because ``_ensure_heightmap_tectonic_model`` wraps a raw model
    in a new dict on every call.  Entries keep the model alive so those ids
    cannot be reused while cached.  Arrays are read-only because callers share
    them.
    """
    u_values = np.ascontiguousarray(u_values, dtype=np.float64)
    v_values = np.ascontiguousarray(v_values, dtype=np.float64)
    tectonic_model = tectonic_model if isinstance(tectonic_model, dict) else {}
    key = (
        u_values.tobytes(),
        v_values.tobytes(),
        tuple(id(segment) for segment in tectonic_model.get("boundary_segments") or ()),
        id(tectonic_model.get("orogen_system_model")),
    )
    for _entry_model, entry_key, result in _orogen_forcing_cache:
        if entry_key == key:
            return result
    result = orogen_forcing_grid(u_values, v_values, tectonic_model)
    for array in result.values():
        array.flags.writeable = False
    _orogen_forcing_cache.insert(0, (tectonic_model, key, result))
    del _orogen_forcing_cache[_OROGEN_FORCING_CACHE_SIZE:]
    return result


def _mountain_morphology_mask_array(
    rows,
    land_rows,
    cell_spacing_m,
    *,
    wrap_x=False,
    tectonic_model=None,
    source_uv_bounds=None,
    sea_level=None,
):
    """NumPy implementation of ``_mountain_morphology_mask`` (same contract)."""
    height = len(rows)
    width = min(len(row) for row in rows)
    unique_width = width - 1 if wrap_x and width > 1 else width
    radius = 2 if min(height, unique_width) >= 9 else 1
    relief_threshold_m = _clamp(float(cell_spacing_m) * 0.006, 140.0, 900.0)
    elevation = np.asarray([row[:unique_width] for row in rows], dtype=np.float64)
    land = np.asarray([row[:unique_width] for row in land_rows[:height]], dtype=bool)
    row_index = np.arange(height)
    column_index = np.arange(unique_width)

    def shifted_columns(offset):
        if wrap_x:
            return (column_index + offset) % unique_width
        return np.clip(column_index + offset, 0, unique_width - 1)

    local_max = np.full(elevation.shape, -np.inf)
    local_min = np.full(elevation.shape, np.inf)
    land_count = np.zeros(elevation.shape, dtype=np.int32)
    for oy in range(-radius, radius + 1):
        source_rows = np.clip(row_index + oy, 0, height - 1)
        for ox in range(-radius, radius + 1):
            source_columns = shifted_columns(ox)
            window_elevation = elevation[source_rows][:, source_columns]
            window_land = land[source_rows][:, source_columns]
            local_max = np.where(window_land, np.maximum(local_max, window_elevation), local_max)
            local_min = np.where(window_land, np.minimum(local_min, window_elevation), local_min)
            land_count += window_land
    resolved = land & (land_count >= 4)
    relief = np.where(resolved, local_max - local_min, 0.0)
    relative_height = np.where(resolved, elevation - local_min, 0.0)
    relief_score = _np_smoothstep((relief - relief_threshold_m) / max(1.0, relief_threshold_m * 1.35))
    position_score = _np_smoothstep(
        (relative_height - relief_threshold_m * 0.12) / max(1.0, relief_threshold_m * 0.72)
    )
    raw = np.where(resolved, relief_score * (0.42 + 0.58 * position_score), 0.0)

    if source_uv_bounds and isinstance(tectonic_model, dict):
        min_u = float(source_uv_bounds.get("min_u", 0.0) or 0.0)
        max_u = float(source_uv_bounds.get("max_u", 1.0) or 1.0)
        min_v = float(source_uv_bounds.get("min_v", 0.0) or 0.0)
        max_v = float(source_uv_bounds.get("max_v", 1.0) or 1.0)
        u_values = min_u + (max_u - min_u) * column_index / max(1, unique_width - 1)
        v_values = min_v + (max_v - min_v) * row_index / max(1, height - 1)
        # Unmasked and cached: only land cells are read below, and their
        # values do not depend on the mask, so repeated refreshes of one tile
        # reuse a single evaluation.
        forcing = cached_orogen_forcing_grid(u_values, v_values, tectonic_model)
        uplift = np.clip(forcing["rock_uplift_m"] / 1800.0, 0.0, 1.0)
        volcanic = np.clip(forcing["volcanic_construction_m"] / 2400.0, 0.0, 1.0)
        convergence = np.clip(forcing["convergent_influence"] / 2.0, 0.0, 1.0)
        tectonic_score = np.clip(uplift * 0.52 + volcanic * 0.28 + convergence * 0.20, 0.0, 1.0)
        if sea_level is not None:
            standing = _np_smoothstep((elevation - float(sea_level) - 250.0) / 1000.0)
            tectonic_score = tectonic_score * (0.30 + 0.70 * standing)
        tectonic_support = np.where(land, np.round(tectonic_score, 4), 0.0)
        raw = np.maximum(raw, tectonic_support * 0.82)

    smoothed = raw
    west_columns = shifted_columns(-1)
    east_columns = shifted_columns(1)
    north_rows = np.clip(row_index - 1, 0, height - 1)
    south_rows = np.clip(row_index + 1, 0, height - 1)
    for _pass in range(2):
        value = (
            smoothed * 4.0
            + smoothed[:, west_columns]
            + smoothed[:, east_columns]
            + smoothed[north_rows, :]
            + smoothed[south_rows, :]
        ) / 8.0
        smoothed = np.where(
            land & (value >= 0.035),
            np.round(np.clip(value, 0.0, 1.0), 4),
            0.0,
        )
    if width > unique_width:
        smoothed = np.concatenate([smoothed, smoothed[:, :1]], axis=1)
    return smoothed.tolist(), relief_threshold_m


def _smooth_wrapped_rows(rows, passes=1):
    current = [list(row) for row in rows]
    height = len(current)
    width = len(current[0]) if height else 0
    unique_width = max(1, width - 1)
    for _pass in range(max(0, int(passes))):
        result = []
        for y in range(height):
            row = []
            for x in range(unique_width):
                center = current[y][x]
                west = current[y][(x - 1) % unique_width]
                east = current[y][(x + 1) % unique_width]
                north = current[max(0, y - 1)][x]
                south = current[min(height - 1, y + 1)][x]
                row.append(center * 0.44 + (west + east) * 0.16 + (north + south) * 0.12)
            row.append(row[0] if row else 0.0)
            result.append(row)
        current = result
    return current


def _emit_heightmap_progress(progress_callback, fraction, detail, preview=None):
    if not callable(progress_callback):
        return
    try:
        progress_callback(
            max(0.0, min(1.0, float(fraction))),
            str(detail or "Building global relief"),
            preview,
        )
    except Exception:
        # Diagnostics must never make generation fail.
        return


def derive_planetary_deformation_state(
    terrain,
    tectonic_model,
    mechanical_lithology_model=None,
    width=97,
    height=49,
    progress_callback=None,
):
    """Materialize persistent reduced-physics deformation and load fields."""
    if not isinstance(tectonic_model, dict) or not tectonic_model.get("plates"):
        return None
    sampled = _heightmap_tectonic_model(tectonic_model)
    mechanical = mechanical_lithology_model if isinstance(mechanical_lithology_model, dict) else {}
    response_factors = terrain_response_factors(mechanical)
    profile = mechanical.get("aggregate_profile") if isinstance(mechanical.get("aggregate_profile"), dict) else {}
    resistance = _clamp(profile.get("slope_resistance_index", 0.55), 0.0, 1.0)
    erodibility = _clamp(profile.get("erodibility_index", 0.50), 0.0, 1.0)
    elastic_strength = _clamp(profile.get("elastic_strength_index", 0.55), 0.0, 1.0)
    density = _clamp(profile.get("bulk_density_kg_m3", 2700.0), 1800.0, 3600.0)
    retention = _clamp(response_factors["relief_retention"], 0.72, 1.12)
    fields = {key: [] for key in (
        "crust_thickness_km", "cumulative_strain_index", "rock_uplift_m",
        "tectonic_subsidence_m", "volcanic_construction_m", "outer_bulge_m", "sediment_load_m",
        "effective_elastic_thickness_km", "convergent_influence",
        "divergent_influence", "trench_influence", "transform_influence",
    )}
    for row_index in range(height):
        ny = row_index / max(1, height - 1)
        row_fields = {key: [] for key in fields}
        for col_index in range(width):
            nx = 0.0 if col_index == width - 1 else col_index / max(1, width - 1)
            lithosphere = _sample_lithosphere(sampled, nx, ny)
            continental = _clamp(lithosphere.get("continental_fraction", 0.5), 0.0, 1.0)
            forcing = _orogen_forcing_at(nx, ny, sampled)
            thickening = float(forcing.get("crustal_thickening_index", 0.0) or 0.0)
            base_crust = 7.0 + continental * 29.0
            crust_thickness = base_crust + thickening * (11.0 + continental * 9.0)
            strain = _clamp(float(forcing.get("cumulative_strain_index", 0.0) or 0.0), 0.0, 1.0)
            elastic_km = (8.0 + continental * 24.0) * (0.72 + elastic_strength * 0.58) * (1.0 - strain * 0.28)
            sediment_load = max(0.0, float(forcing.get("tectonic_subsidence_m", 0.0) or 0.0) * (0.10 + erodibility * 0.16))
            values = {
                "crust_thickness_km": crust_thickness,
                "cumulative_strain_index": strain,
                "rock_uplift_m": float(forcing.get("rock_uplift_m", 0.0) or 0.0) * retention,
                "tectonic_subsidence_m": float(forcing.get("tectonic_subsidence_m", 0.0) or 0.0),
                "volcanic_construction_m": float(forcing.get("volcanic_construction_m", 0.0) or 0.0),
                "outer_bulge_m": float(forcing.get("outer_bulge_m", 0.0) or 0.0),
                "sediment_load_m": sediment_load,
                "effective_elastic_thickness_km": elastic_km,
                "convergent_influence": float(forcing.get("convergent_influence", 0.0) or 0.0),
                "divergent_influence": float(forcing.get("divergent_influence", 0.0) or 0.0),
                "trench_influence": float(forcing.get("trench_influence", 0.0) or 0.0),
                "transform_influence": float(forcing.get("transform_influence", 0.0) or 0.0),
            }
            for key, value in values.items():
                row_fields[key].append(value)
        for key in fields:
            if row_fields[key]:
                row_fields[key][-1] = row_fields[key][0]
            fields[key].append(row_fields[key])
        if row_index == height - 1 or row_index % max(1, height // 10) == 0:
            _emit_heightmap_progress(
                progress_callback,
                (row_index + 1) / max(1, height),
                f"Resolving tectonic deformation row {row_index + 1} of {height}",
            )
    net_load_rows = [
        [
            fields["rock_uplift_m"][y][x] * 0.24
            + fields["volcanic_construction_m"][y][x] * 0.34
            + fields["sediment_load_m"][y][x] * 0.62
            for x in range(width)
        ]
        for y in range(height)
    ]
    flexural_load = _smooth_wrapped_rows(net_load_rows, passes=2)
    isostatic_rows, flexural_rows, response_rows = [], [], []
    density_factor = _clamp(2700.0 / density, 0.78, 1.18)
    for y in range(height):
        iso_row, flex_row, response_row = [], [], []
        for x in range(width):
            continental = _clamp(
                _sample_lithosphere(
                    sampled,
                    0.0 if x == width - 1 else x / max(1, width - 1),
                    y / max(1, height - 1),
                ).get("continental_fraction", 0.5),
                0.0,
                1.0,
            )
            root_excess_km = max(
                0.0,
                fields["crust_thickness_km"][y][x] - (7.0 + 29.0 * continental),
            )
            isostatic = root_excess_km * 1000.0 * 0.115 * density_factor - fields["sediment_load_m"][y][x] * 0.18
            rigidity = _clamp(fields["effective_elastic_thickness_km"][y][x] / 42.0, 0.18, 1.0)
            flexure = -flexural_load[y][x] * (0.16 + rigidity * 0.24)
            surface = (
                fields["rock_uplift_m"][y][x]
                - fields["tectonic_subsidence_m"][y][x]
                + fields["volcanic_construction_m"][y][x]
                + fields["outer_bulge_m"][y][x]
                + isostatic + flexure
            )
            iso_row.append(isostatic)
            flex_row.append(flexure)
            response_row.append(surface)
        isostatic_rows.append(iso_row)
        flexural_rows.append(flex_row)
        response_rows.append(response_row)
    fields["isostatic_response_m"] = isostatic_rows
    fields["flexural_response_m"] = flexural_rows
    fields["surface_response_m"] = response_rows
    summaries = {
        key: {"min": round(min(value for row in rows for value in row), 3), "max": round(max(value for row in rows for value in row), 3)}
        for key, rows in fields.items()
    }
    return {
        "status": "deformation_state_derived",
        "model_version": DEFORMATION_STATE_MODEL_VERSION,
        "truth_state": "persistent_reduced_physics_deformation_and_load_state",
        "width": width, "height": height, "wrap_x": True,
        "fields": {key: [[round(value, 3) for value in row] for row in rows] for key, rows in fields.items()},
        "summaries": summaries,
        "source_orogen_model_version": ((tectonic_model.get("orogen_system_model") or {}).get("model_version")),
        "source_mechanical_model_version": mechanical.get("model_version"),
        "dominant_mechanical_class": mechanical.get("dominant_mechanical_class"),
        "terrain_response_factors": response_factors,
        "composition_contract": "surface_response=rock_uplift-tectonic_subsidence+volcanic_construction+outer_bulge+isostasy+flexure",
    }


def _sample_deformation_state(model, nx, ny):
    if not isinstance(model, dict) or model.get("status") != "deformation_state_derived":
        return None
    width, height = int(model.get("width", 0) or 0), int(model.get("height", 0) or 0)
    fields = model.get("fields") if isinstance(model.get("fields"), dict) else {}
    if width < 2 or height < 2:
        return None
    fx, fy = (float(nx) % 1.0) * (width - 1), _clamp(ny, 0.0, 1.0) * (height - 1)
    x0, y0 = int(math.floor(fx)), int(math.floor(fy))
    x1, y1 = (x0 + 1) % (width - 1), min(height - 1, y0 + 1)
    tx, ty = fx - x0, fy - y0
    sampled = {}
    for key, rows in fields.items():
        if not isinstance(rows, list) or len(rows) <= y1:
            continue
        top = float(rows[y0][x0]) * (1.0 - tx) + float(rows[y0][x1]) * tx
        bottom = float(rows[y1][x0]) * (1.0 - tx) + float(rows[y1][x1]) * tx
        sampled[key] = top * (1.0 - ty) + bottom * ty
    return sampled


def _tectonic_height_m(
    nx,
    ny,
    terrain,
    tectonic_model,
    *,
    continent_signal=None,
    lod0_synthesis=False,
    lithosphere_sample=None,
):
    plates = tectonic_model.get("plates") or []
    if not plates:
        return None
    lithosphere = lithosphere_sample or _sample_lithosphere(tectonic_model, nx, ny)
    crust_fraction = float(lithosphere.get("continental_fraction", 0.5) or 0.0)
    oceanic_fraction = _clamp(lithosphere.get("oceanic_fraction", 1.0 - crust_fraction), 0.0, 1.0)
    ocean_floor_age_myr = lithosphere["age_myr"]
    if oceanic_fraction > 0.0:
        # Crust ages away from its own ridge segment at the half-spreading
        # rate; segment offsets make fracture zones (seafloor_spreading).
        spreading_age = seafloor_age_myr(tectonic_model.get("seafloor_spreading_model"), nx, ny)
        if spreading_age is not None:
            ocean_floor_age_myr = spreading_age
    base = _continuous_crustal_base_height_m(crust_fraction)

    map_seed = str(tectonic_model.get("map_seed") or terrain.get("map_seed") or "")
    if continent_signal is None:
        continent_signal = _continent_signal(
            nx,
            ny,
            map_seed=map_seed,
            tectonic_model=tectonic_model,
            lod0_synthesis=lod0_synthesis,
        )
    assembled_crust = _continental_mask(continent_signal)
    # The causal lithosphere field owns continentality. Procedural cratons and
    # terranes perturb its margins, but cannot impose a categorical plate-wide
    # shelf or abyssal step.
    continent_mask = _clamp(
        crust_fraction * 0.78 + assembled_crust * 0.22,
        0.0,
        1.0,
    )
    rugged_noise = _fbm_noise(
        map_seed, "rugged_relief", nx, ny,
        base_cells=12 if lod0_synthesis else 18,
        octaves=2 if lod0_synthesis else 4,
    )
    shield_noise = _fbm_noise(
        map_seed, "cratonic_shields", nx, ny,
        base_cells=6 if lod0_synthesis else 8,
        octaves=2 if lod0_synthesis else 3,
    )
    basin_noise = _fbm_noise(
        map_seed, "sedimentary_basins", nx, ny,
        base_cells=7 if lod0_synthesis else 11,
        octaves=2 if lod0_synthesis else 3,
    )
    intracontinental_basin = (
        max(0.0, -basin_noise) * 0.55
        if lod0_synthesis
        else _intracontinental_basin_signal(nx, ny, map_seed=map_seed)
    )
    island_signal = 0.0 if lod0_synthesis else _oceanic_island_signal(nx, ny, map_seed=map_seed)
    # Major interior relief comes from explicit cratons, failed rifts and
    # intracratonic basins below. Retain only a low-amplitude residual instead
    # of continent-scale sine domes.
    broad_relief = shield_noise * 105.0 * continent_mask + basin_noise * 75.0 * oceanic_fraction
    height = base + broad_relief
    height += continent_mask * (780.0 + shield_noise * 360.0)
    # Isostatic contrast is what lets a realistic water volume coexist with
    # exposed continents: young dense oceanic lithosphere forms deep basins,
    # while buoyant differentiated continental crust retains freeboard.
    height += continent_mask * 360.0
    # Oceanic crust: the ridge crest sits ~3 km below the median continental
    # surface (Earth: -2.6 km vs +0.3 km); the seafloor deepens from there
    # with age (plate cooling, below).  The former -2.85 km term put even
    # zero-age crust ~9 km below the continents, so all but the youngest
    # seafloor fell below the planet's minimum elevation and was clamped
    # flat -- no ridges, no fracture zones, no deep basins.
    height += (1.0 - continent_mask) * (OCEANIC_CREST_OFFSET_M + basin_noise * 360.0)
    if oceanic_fraction > 0.0:
        # Young ridge crust is hot and buoyant; cooling lithosphere subsides
        # with the square root of age, then flattens (GDH1 plate cooling:
        # ridge crest ~2.6 km, 20 Myr ~4.2 km, old basins ~5.6 km deep).
        height -= plate_cooling_subsidence_m(ocean_floor_age_myr) * oceanic_fraction
    # Subsidence within stable crust creates sedimentary and endorheic basins.
    height -= intracontinental_basin * continent_mask * 1150.0
    if not lod0_synthesis:
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
    effects = tectonic_model.get("surface_effects") if isinstance(tectonic_model.get("surface_effects"), dict) else {}
    uplift_gain = 0.7 + float(effects.get("orogenic_uplift", 0.0) or 0.0) * 0.9
    erosion = float(effects.get("erosion_progress", 0.0) or 0.0)
    convergent_influence = 0.0
    divergent_influence = 0.0
    trench_influence = 0.0
    transform_influence = 0.0
    deformation = _sample_deformation_state(tectonic_model.get("deformation_state_model"), nx, ny)
    height_before_orogen_response = height
    orogen_lookup = tectonic_model.get("_heightmap_orogen_system_lookup")
    if not isinstance(orogen_lookup, dict):
        orogen_model = tectonic_model.get("orogen_system_model") if isinstance(tectonic_model.get("orogen_system_model"), dict) else {}
        orogen_lookup = {
            str(system.get("id")): system
            for system in (orogen_model.get("systems") or [])
            if isinstance(system, dict) and system.get("id")
        }
    orogen_forcing_by_system = {}

    # The coarse deformation product already resolved all orogen segments.
    # Re-evaluating them at every denser height sample would duplicate both
    # physics and cost; retain direct evaluation only as the Phase 1 fallback.
    candidate_segments = () if isinstance(deformation, dict) else _nearby_boundary_segments(tectonic_model, nx, ny)
    for segment in candidate_segments:
        distance = _wrapped_point_segment_distance(
            nx,
            ny,
            float(segment.get("x1", 0.0) or 0.0),
            float(segment.get("y1", 0.0) or 0.0),
            float(segment.get("x2", 0.0) or 0.0),
            float(segment.get("y2", 0.0) or 0.0),
        )
        influence_width = _clamp(segment.get("influence_width", 0.028), 0.012, 0.05)
        if distance > influence_width * 3.2:
            continue
        influence = math.exp(-((distance / influence_width) ** 2))
        influence = influence ** 1.18 * _clamp(segment.get("activity_scale", 1.0), 0.25, 1.35)
        normal_x = float(segment.get("normal_x", 0.0) or 0.0)
        normal_y = float(segment.get("normal_y", 0.0) or 0.0)
        segment_x1 = float(segment.get("x1", 0.0) or 0.0)
        segment_x2 = float(segment.get("x2", 0.0) or 0.0)
        midpoint_x = (segment_x1 + _wrapped_delta(segment_x2, segment_x1) * 0.5) % 1.0
        midpoint_y = (float(segment.get("y1", 0.0) or 0.0) + float(segment.get("y2", 0.0) or 0.0)) * 0.5
        signed_normal_distance = _wrapped_delta(nx, midpoint_x) * normal_x + (ny - midpoint_y) * normal_y
        orogen_system_id = str(segment.get("orogen_system_id") or "")
        orogen_system = orogen_lookup.get(orogen_system_id)
        if isinstance(orogen_system, dict):
            response = _orogen_segment_forcing(
                nx,
                ny,
                segment,
                orogen_system,
                signed_normal_distance,
                influence,
            )
            combined = orogen_forcing_by_system.setdefault(
                orogen_system_id,
                {key: 0.0 for key in response},
            )
            for key, value in response.items():
                previous = float(combined.get(key, 0.0) or 0.0)
                current = float(value or 0.0)
                # A sixth-order smooth maximum removes max() cusps where
                # adjacent trace segments exchange dominance without stacking
                # several coincident segments into an artificial summit.
                high = max(previous, current)
                low = min(previous, current)
                combined[key] = (
                    high * ((1.0 + (low / high) ** 6.0) ** (1.0 / 6.0))
                    if high > 0.0
                    else 0.0
                )

    for forcing in orogen_forcing_by_system.values():
        height += float(forcing.get("rock_uplift_m", 0.0) or 0.0) * (0.86 + uplift_gain * 0.14)
        height -= float(forcing.get("tectonic_subsidence_m", 0.0) or 0.0)
        height += float(forcing.get("volcanic_construction_m", 0.0) or 0.0)
        height += float(forcing.get("outer_bulge_m", 0.0) or 0.0)
        convergent_influence = max(convergent_influence, float(forcing.get("convergent_influence", 0.0) or 0.0))
        divergent_influence = max(divergent_influence, float(forcing.get("divergent_influence", 0.0) or 0.0))
        trench_influence = max(trench_influence, float(forcing.get("trench_influence", 0.0) or 0.0))
        transform_influence = max(transform_influence, float(forcing.get("transform_influence", 0.0) or 0.0))

    if isinstance(deformation, dict):
        # Phase 2 owns the physical collapse into elevation. The direct Phase 1
        # forcing above remains only as a deterministic fallback for callers
        # that have not requested a deformation-state product.
        height = height_before_orogen_response + float(deformation.get("surface_response_m", 0.0) or 0.0)
        convergent_influence = float(deformation.get("convergent_influence", 0.0) or 0.0)
        divergent_influence = float(deformation.get("divergent_influence", 0.0) or 0.0)
        trench_influence = float(deformation.get("trench_influence", 0.0) or 0.0)
        transform_influence = float(deformation.get("transform_influence", 0.0) or 0.0)

    continental_shelf = math.exp(-(((continent_signal + 0.10) / 0.18) ** 2))
    passive_margin = continental_shelf * max(0.0, 1.0 - convergent_influence - divergent_influence * 0.7)
    height += passive_margin * 520.0
    height -= (1.0 - continent_mask) * max(0.0, 1.0 - divergent_influence) * 380.0
    if isinstance(deformation, dict):
        mechanical_response = (tectonic_model.get("deformation_state_model") or {}).get("terrain_response_factors") or {}
        ruggedness_factor = float(mechanical_response.get("ruggedness_factor", 1.0) or 1.0)
        # Noise is now bounded sub-resolution heterogeneity. It cannot place
        # ranges, trenches, rifts, or transform relief independently of the
        # persistent deformation fields.
        height += rugged_noise * (105.0 + continent_mask * 235.0) * ruggedness_factor
    else:
        height += divergent_influence * _lerp(-380.0, 950.0, oceanic_fraction)
        height -= trench_influence * (1150.0 + (1.0 - continent_mask) * 900.0)
        height += transform_influence * rugged_noise * 520.0
        height += rugged_noise * (180.0 + continent_mask * 380.0 + convergent_influence * 950.0)
    # Mantle plumes leave volcanic chains primarily on oceanic lithosphere.
    height += island_signal * (1.0 - continent_mask) * _lerp(2300.0, 4100.0, oceanic_fraction)
    if not lod0_synthesis:
        hotspot_model = tectonic_model.get("hotspot_model") if isinstance(tectonic_model.get("hotspot_model"), dict) else {}
        for hotspot in hotspot_model.get("hotspots") or []:
            for point in hotspot.get("track") or []:
                distance = math.hypot(
                    _wrapped_delta(nx, float(point.get("x", 0.0) or 0.0)),
                    ny - float(point.get("y", 0.5) or 0.5),
                )
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
        erosion_factor = 1.0
        if isinstance(deformation, dict):
            mechanical_response = (tectonic_model.get("deformation_state_model") or {}).get("terrain_response_factors") or {}
            erosion_factor = float(mechanical_response.get("erosion_susceptibility", 1.0) or 1.0)
        height *= 1.0 - min(0.34, erosion * 0.24 * erosion_factor)
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
        - ice_fraction * 0.36,
        0.06,
        1.0,
    )
    # Volcanic resurfacing floods from the bottom up: lava ponds in the
    # lowest terrain first (lunar maria in basins, Mars's northern plains),
    # so the resurfaced fraction of the area is the part below a flood level.
    flood_level = _area_quantile(base_rows, resurfacing) if resurfacing > 0.0 else None
    map_seed = str(crater_model.get("map_seed") or "")
    flooded_count = 0
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
        relief_m = max(1.0, float(crater.get("rim_height_m", 0.0) or 0.0) + 0.5 * float(crater.get("depth_m", 0.0) or 0.0))
        # Buried share: 1 well inside the flooded lowland (a resurfaced
        # surface is one whose old craters are gone), 1/2 for a crater
        # sitting at the flood level, 0 a half crater-relief above it --
        # the ghost rings of the plains' margins.
        burial = (
            _clamp(0.5 + (flood_level - center_elevation) / relief_m, 0.0, 1.0)
            if flood_level is not None and water_depth_m <= 0.0 else 0.0
        )
        if burial > 0.0 and seed_range(
            map_seed, f"{crater.get('id')}:post_flood", 0.0, 1.0,
        ) >= FLOOD_PLAINS_CRATER_SHARE:
            # Formed before the flooding (the rest are younger impacts on
            # the new plains and keep their shape).
            preservation *= (1.0 - burial) ** 2
            flooded_count += int(burial >= 0.5)
        crater["target_environment"] = "marine" if water_depth_m > 0.0 else "subaerial"
        crater["target_water_depth_m"] = round(water_depth_m, 1)
        crater["marine_crater_transmission"] = round(marine_transmission, 4)
        crater["morphology_preservation"] = round(preservation, 4)
        conditioned.append(crater)
    crater_model["craters"] = conditioned
    crater_model["surface_morphology_preservation"] = round(global_preservation, 4)
    crater_model["marine_target_model"] = "water_depth_to_projectile_scale_v1"
    crater_model["volcanic_flood_level_m"] = round(flood_level, 1) if flood_level is not None else None
    crater_model["flooded_crater_count"] = flooded_count
    audit = {
        "status": "resolved",
        "global_preservation": round(global_preservation, 4),
        "marine_crater_count": marine_count,
        "strongly_suppressed_marine_crater_count": suppressed_count,
        "pressure_bar": round(pressure_bar, 5),
        "erosion_strength": round(erosion_strength, 4),
        "volcanic_flood_level_m": crater_model["volcanic_flood_level_m"],
        "flooded_crater_count": flooded_count,
    }
    return crater_model, audit


# Share of a flooded plain's craters that formed after the flooding: the
# impact record is dominated by early bombardment, so ~3.6 Gyr plains carry
# about a fifth of the crater density of ~4.1 Gyr highlands (Neukum
# chronology; Mars's Hesperian plains vs. Noachian highlands).
FLOOD_PLAINS_CRATER_SHARE = 0.2


def _area_quantile(rows, fraction):
    """Elevation below which ``fraction`` of the sphere's area lies (equirectangular rows)."""
    values, weights = [], []
    height = len(rows)
    for index, row in enumerate(rows):
        if not isinstance(row, list) or not row:
            continue
        weight = math.cos((0.5 - (index + 0.5) / max(1, height)) * math.pi)
        for value in row[:-1] if len(row) > 1 else row:
            values.append(float(value))
            weights.append(weight)
    if not values:
        return None
    order = sorted(range(len(values)), key=values.__getitem__)
    target = _clamp(fraction, 0.0, 1.0) * sum(weights)
    running = 0.0
    for position in order:
        running += weights[position]
        if running >= target:
            return values[position]
    return values[order[-1]]


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


def _wave_height(
    nx,
    ny,
    terrain,
    tectonic_model=None,
    crater_model=None,
    crater_spatial_index=None,
    map_seed="",
    lod0_synthesis=False,
):
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
    # Planet-scale basins and swells: seamless noise on the sphere (the
    # former three map-space sinusoids drew tilted sine-curve basins that
    # broke at the date line).  Spread ~0.14, like the sinusoid sum it
    # replaces.
    broad_basins = sphere_signed_table(map_seed, "broad_basins", nx, ny, features=1.1, octaves=3) * 0.34
    icy_surface = terrain.get("surface_regime") == "cratered_ice_shell"
    lod0_lithosphere = (
        _sample_lithosphere(tectonic_model, nx, ny)
        if lod0_synthesis and isinstance(tectonic_model, dict) and tectonic_model.get("plates")
        else None
    )
    continents = _continent_signal(
        nx,
        ny,
        map_seed=map_seed,
        tectonic_model=tectonic_model,
        lod0_synthesis=lod0_synthesis,
        lithosphere_sample=lod0_lithosphere,
    )
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
        if not lod0_synthesis:
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
        dunes = sphere_signed_table(map_seed, "dune_seas", nx, ny, features=4.0 + dune_wavelength * 0.1, octaves=2) * 0.028
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
        tectonic_height = _tectonic_height_m(
            nx,
            ny,
            terrain,
            tectonic_model,
            continent_signal=continents,
            lod0_synthesis=lod0_synthesis,
            lithosphere_sample=lod0_lithosphere,
        )

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
        value += sphere_signed_table(map_seed, "ridge_texture", nx, ny, features=6.0, octaves=2) * ridge_strength * 0.07
    else:
        # Broad volcanic shields and swells of a plate-less lid (seamless on
        # the sphere; formerly a tilted map-space sinusoid).
        shield_wave = sphere_signed_table(map_seed, "shield_swells", nx, ny, features=1.5, octaves=2)
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


def _ice_score(nx, ny, elevation, min_elevation, max_elevation, map_seed=""):
    """Rank cells for the pre-climate ice quota by how cold they are.

    Annual-mean temperature falls with latitude and, through the 6.5 K/km
    lapse rate, with height.  In latitude units (Earth's ~48 K
    pole-to-equator contrast spans one unit) a kilometre of elevation is
    worth ~0.14: a 6 km equatorial peak is as cold as ~75 degrees latitude,
    which is why equatorial summits carry glaciers.  A little seamless
    sphere noise keeps the quota edge from being a pure parallel.  (The old
    map-space sinusoids drew a tilted sine-curve ice edge.)
    """
    latitude_polarity = abs(ny - 0.5) * 2.0
    lapse_equivalent = max(0.0, float(elevation)) * 0.0065 / 48.0
    noise = sphere_signed_table(map_seed, "ice_quota", nx, ny, features=3.0, octaves=2) * 0.03
    return latitude_polarity + lapse_equivalent + noise


from simulations.world_gen.sphere_noise import sphere_signed_table  # noqa: E402


def sea_level_for_equivalent_water_depth(rows, equivalent_depth_m, wrap_x=True):
    """Solve sea level from water volume on a spherical sampled surface."""
    if not rows or not rows[0] or float(equivalent_depth_m or 0.0) <= 0.0:
        return None
    height = len(rows)
    width = min(len(row) for row in rows)
    unique_width = max(1, width - 1) if wrap_x and width > 1 else width
    if np is not None:
        elevation = np.asarray([row[:unique_width] for row in rows], dtype=np.float64).ravel()
        weights = np.repeat(
            [max(1e-6, math.cos((0.5 - y / max(1, height - 1)) * math.pi)) for y in range(height)],
            unique_width,
        )
        total_weight = float(weights.sum())
        if total_weight <= 0.0:
            return None
        target_depth = float(equivalent_depth_m)
        low = float(elevation.min())
        high = float(elevation.max()) + target_depth
        for _iteration in range(52):
            candidate = (low + high) * 0.5
            stored_depth = float(np.dot(np.maximum(0.0, candidate - elevation), weights)) / total_weight
            if stored_depth < target_depth:
                low = candidate
            else:
                high = candidate
        return (low + high) * 0.5
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


def _materialize_shallow_margin_bathymetry(rows, sea_level, tectonic_model=None, circumference_m=0.0):
    """Create a bounded shallow-margin ramp before shelf classification.

    The tectonic height sampler correctly creates deep ocean basins, but its
    continental/oceanic freeboard transition can be steeper than a planetary
    sample cell.  In that case the existing shelf classifier sees almost no
    cells between sea level and 420 m depth.  This pass raises only submerged
    cells immediately offshore toward a passive-margin ramp; active convergent
    margins retain a much narrower response.  Water volume is conserved later
    by the normal sea-level solve.
    """
    if sea_level is None or not rows or not rows[0]:
        return {"status": "not_applicable", "raised_cell_count": 0}
    height, width = len(rows), len(rows[0])
    unique_width = width - 1 if width > 1 else width
    spacing_m = max(
        1.0,
        float(circumference_m or 0.0) / max(1, unique_width - 1),
    )
    band_cells = max(2, min(8, int(round(520.0 / spacing_m)) + 2))
    distance = [[999 for _x in range(width)] for _y in range(height)]
    frontier = []
    for y in range(height):
        for x in range(unique_width):
            if float(rows[y][x]) >= float(sea_level):
                distance[y][x] = 0
                frontier.append((x, y))
    cursor = 0
    while cursor < len(frontier):
        x, y = frontier[cursor]
        cursor += 1
        next_distance = distance[y][x] + 1
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if ny < 0 or ny >= height:
                continue
            nx %= unique_width
            if next_distance < distance[ny][nx]:
                distance[ny][nx] = next_distance
                frontier.append((nx, ny))

    boundaries = [
        segment for segment in (tectonic_model or {}).get("boundary_segments") or []
        if isinstance(segment, dict)
    ]
    raised = 0
    for y in range(height):
        ny = y / max(1, height - 1)
        for x in range(unique_width):
            current = float(rows[y][x])
            if current >= float(sea_level) or distance[y][x] > band_cells:
                continue
            nx = x / max(1, unique_width - 1)
            step = float(distance[y][x])
            target_depth = 55.0 + 365.0 * (step / max(1.0, band_cells))
            target = float(sea_level) - target_depth
            if current >= target:
                continue
            active_margin = 1.0
            for segment in boundaries:
                kind = str(segment.get("kind") or "")
                if kind not in {"subduction", "collision", "divergent"}:
                    continue
                distance_to_boundary = _wrapped_point_segment_distance(
                    nx,
                    ny,
                    float(segment.get("x1", 0.0) or 0.0),
                    float(segment.get("y1", 0.5) or 0.5),
                    float(segment.get("x2", 0.0) or 0.0),
                    float(segment.get("y2", 0.5) or 0.5),
                )
                if distance_to_boundary <= 0.035:
                    active_margin = min(
                        active_margin,
                        0.22 if kind == "subduction" else 0.42,
                    )
            if active_margin >= 0.999:
                # A passive shelf is a bounded shallow-water condition, not
                # a soft colour transition.  Enforce the ramp's lower bound
                # so a one-cell continental/oceanic freeboard jump cannot
                # erase the shelf entirely.
                updated = max(current, target)
            else:
                blend = active_margin * (0.74 - 0.16 * step / max(1.0, band_cells))
                updated = current * (1.0 - blend) + target * blend
            if updated > current:
                rows[y][x] = round(updated, 1)
                raised += 1
    for y in range(height):
        rows[y][-1] = rows[y][0]
    return {
        "status": "shallow_margin_bathymetry_materialized",
        "raised_cell_count": raised,
        "band_cells": band_cells,
        "shelf_depth_limit_m": 420.0,
        "active_margin_blend": "subduction_0.22_collision_0.42_passive_1.0",
    }


VECTORISED_SHELF_MODEL = True


def _uv_axes(width, height, source_uv_bounds=None):
    """Global UV of each column/row; regional grids map through their bounds."""
    u_values = np.arange(width, dtype=np.float64) / max(1, width - 1)
    v_values = np.arange(height, dtype=np.float64) / max(1, height - 1)
    if source_uv_bounds:
        min_u = float(source_uv_bounds.get("min_u", 0.0) or 0.0)
        max_u = float(source_uv_bounds.get("max_u", 1.0) or 1.0)
        min_v = float(source_uv_bounds.get("min_v", 0.0) or 0.0)
        max_v = float(source_uv_bounds.get("max_v", 1.0) or 1.0)
        u_values = min_u + (max_u - min_u) * u_values
        v_values = min_v + (max_v - min_v) * v_values
    return u_values, v_values


def _np_catmull_rom(p0, p1, p2, p3, t):
    # Same operation order as ``_sample_lithosphere.cubic`` for bit parity.
    return 0.5 * (
        2.0 * p1
        + (-p0 + p2) * t
        + (2.0 * p0 - 5.0 * p1 + 4.0 * p2 - p3) * t * t
        + (-p0 + 3.0 * p1 - 3.0 * p2 + p3) * t * t * t
    )


def _sample_lithosphere_grid(tectonic_model, nx, ny):
    """Array form of ``_sample_lithosphere``.

    Returns ``(continental_fraction, age_myr, oceanic_fraction)`` for the
    broadcast ``nx``/``ny`` points.  Without a crust grid the scalar sampler
    omits ``oceanic_fraction``; callers that default it to zero get zeros here.
    """
    nx, ny = np.broadcast_arrays(np.asarray(nx, dtype=np.float64), np.asarray(ny, dtype=np.float64))
    grid = tectonic_model.get("lithosphere_grid") if isinstance(tectonic_model.get("lithosphere_grid"), dict) else {}
    crust_rows = grid.get("crust_type_rows") or []
    age_rows = grid.get("ocean_floor_age_rows_myr") or []
    fraction_rows = grid.get("continental_fraction_rows") or []
    if not crust_rows or not crust_rows[0]:
        return np.full(nx.shape, 0.5), np.zeros(nx.shape), np.zeros(nx.shape)
    height = len(crust_rows)
    width = min(len(row) for row in crust_rows)
    x = np.rint(nx * max(1, width - 1)).astype(np.int64) % width
    y = np.clip(np.rint(ny * max(1, height - 1)).astype(np.int64), 0, height - 1)
    nearest_age = np.zeros((height, width))
    for row_index, row in enumerate(age_rows[:height]):
        values = [float(value) for value in row[:width]]
        nearest_age[row_index, :len(values)] = values
    age = nearest_age[y, x]

    def sample_continuous(rows, default):
        if not rows or len(rows) < 2 or not rows[0]:
            return np.asarray(default, dtype=np.float64) + np.zeros(nx.shape)
        grid_height = len(rows)
        grid_width = min(len(row) for row in rows)
        values = np.asarray([[float(value) for value in row[:grid_width]] for row in rows], dtype=np.float64)
        fx = np.mod(nx, 1.0) * max(1, grid_width - 1)
        fy = np.clip(ny, 0.0, 1.0) * max(1, grid_height - 1)
        x1 = np.floor(fx).astype(np.int64)
        y1 = np.floor(fy).astype(np.int64)
        tx, ty = fx - x1, fy - y1
        columns = [(x1 + offset) % grid_width for offset in (-1, 0, 1, 2)]
        low = np.full(nx.shape, np.inf)
        high = np.full(nx.shape, -np.inf)
        interpolated = []
        for offset in (-1, 0, 1, 2):
            source_rows = np.clip(y1 + offset, 0, grid_height - 1)
            support = [values[source_rows, column] for column in columns]
            for item in support:
                low = np.minimum(low, item)
                high = np.maximum(high, item)
            interpolated.append(_np_catmull_rom(*support, tx))
        value = _np_catmull_rom(*interpolated, ty)
        return np.maximum(low, np.minimum(high, value))

    if fraction_rows and fraction_rows[0]:
        continental_fraction = np.clip(sample_continuous(fraction_rows, 0.5), 0.0, 1.0)
        age = np.maximum(0.0, sample_continuous(age_rows, age)) if age_rows else age
    else:
        continental = np.zeros((height, width), dtype=bool)
        for row_index, row in enumerate(crust_rows):
            continental[row_index] = [value in {"continental", "continental_fragment"} for value in row[:width]]
        continental_fraction = continental[y, x].astype(np.float64)
    return continental_fraction, age, 1.0 - continental_fraction


def _grid_l1_distance(mask, *, wrap_x, cap):
    """4-neighbour grid distance to the nearest ``mask`` cell, capped at ``cap``.

    Every cell is passable, so the breadth-first distance equals the L1
    distance (wrapped in x when ``wrap_x``) and separates into two 1-D sweeps.
    """
    height, width = mask.shape
    tiled = np.concatenate([mask, mask, mask], axis=1) if wrap_x else mask
    columns = np.where(tiled, 0, cap).astype(np.int64).T.copy()
    for index in range(1, columns.shape[0]):
        np.minimum(columns[index], columns[index - 1] + 1, out=columns[index])
    for index in range(columns.shape[0] - 2, -1, -1):
        np.minimum(columns[index], columns[index + 1] + 1, out=columns[index])
    distance = columns.T[:, width:2 * width] if wrap_x else columns.T
    distance = np.ascontiguousarray(distance)
    for index in range(1, height):
        np.minimum(distance[index], distance[index - 1] + 1, out=distance[index])
    for index in range(height - 2, -1, -1):
        np.minimum(distance[index], distance[index + 1] + 1, out=distance[index])
    return np.minimum(distance, cap)


def _shelf_and_sediment_model_array(rows, sea_level, tectonic_model, *, wrap_x, source_uv_bounds):
    elevation = np.asarray(rows, dtype=np.float64)
    height, width = elevation.shape
    sea_level = float(sea_level)
    land = elevation >= sea_level
    distance = _grid_l1_distance(land, wrap_x=wrap_x, cap=999)
    depth = np.maximum(0.0, sea_level - elevation)
    ocean = depth > 0.0
    shelf = ocean & (depth <= 420.0) & (distance <= 7)
    u_values, v_values = _uv_axes(width, height, source_uv_bounds)
    ocean_rows, ocean_columns = np.nonzero(ocean)
    _continental, age, oceanic = _sample_lithosphere_grid(
        tectonic_model or {}, u_values[ocean_columns], v_values[ocean_rows]
    )
    oceanic = np.clip(oceanic, 0.0, 1.0)
    age_myr = age * oceanic + 800.0 * (1.0 - oceanic)
    # Integer distances, so a math.exp table keeps parity with the scalar path.
    wedge_table = np.asarray([3600.0 * math.exp(-step / 3.2) for step in range(1000)])
    pelagic = np.minimum(1600.0, np.maximum(0.0, age_myr) * 7.0)
    sediment = np.zeros((height, width))
    sediment[ocean_rows, ocean_columns] = np.minimum(
        7200.0, wedge_table[distance[ocean_rows, ocean_columns]] + pelagic
    )
    shelf_count = int(np.count_nonzero(shelf))
    return {
        "model": "passive_margin_shelf_and_sediment_wedge_v1",
        "shelf_rows": shelf.tolist(),
        "sediment_thickness_rows_m": [[round(value, 1) for value in row] for row in sediment.tolist()],
        "shelf_fraction": round(shelf_count / max(1, width * height), 4),
        "shelf_depth_limit_m": 420.0,
        "sediment_loading_causes_subsidence": True,
    }


def _shelf_and_sediment_model(rows, sea_level, tectonic_model=None, *, wrap_x=True, source_uv_bounds=None):
    """Shelf mask and sediment thickness from the resolved heightfield.

    ``source_uv_bounds`` maps a regional grid to planetary UV so ocean-floor
    age is read where the tile actually is; ``wrap_x`` is false for tiles.
    """
    if sea_level is None or not rows or not rows[0]:
        return {"shelf_rows": [], "sediment_thickness_rows_m": [], "shelf_fraction": 0.0}
    if np is not None and VECTORISED_SHELF_MODEL:
        return _shelf_and_sediment_model_array(
            rows, sea_level, tectonic_model, wrap_x=wrap_x, source_uv_bounds=source_uv_bounds,
        )
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
        if wrap_x:
            neighbors = (((x - 1) % width, y), ((x + 1) % width, y), (x, y - 1), (x, y + 1))
        else:
            neighbors = ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1))
        for nx, ny in neighbors:
            if nx < 0 or nx >= width or ny < 0 or ny >= height or next_distance >= distance[ny][nx]:
                continue
            distance[ny][nx] = next_distance
            frontier.append((nx, ny))
    u_values = [x / max(1, width - 1) for x in range(width)]
    v_values = [y / max(1, height - 1) for y in range(height)]
    if source_uv_bounds and np is not None:
        u_array, v_array = _uv_axes(width, height, source_uv_bounds)
        u_values, v_values = u_array.tolist(), v_array.tolist()
    shelf_rows, sediment_rows = [], []
    shelf_count = 0
    for y, row in enumerate(rows):
        shelf_row, sediment_row = [], []
        for x, elevation in enumerate(row):
            depth = max(0.0, float(sea_level) - float(elevation))
            lithosphere = _sample_lithosphere(tectonic_model or {}, u_values[x], v_values[y])
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


def _mountain_morphology_mask(
    rows,
    land_rows,
    cell_spacing_m,
    *,
    wrap_x=False,
    tectonic_model=None,
    source_uv_bounds=None,
    sea_level=None,
):
    """Classify resolved mountain terrain from relief, not latitude or noise.

    The returned field is deliberately continuous.  Regional refinement can
    taper ridge-scale relief across the real edge of an inherited mountain
    belt instead of applying a mountain texture to an entire requested tile.
    Ocean depths are excluded from the neighbourhood range so coastlines do
    not masquerade as mountain fronts.
    """
    if np is not None:
        return _mountain_morphology_mask_array(
            rows,
            land_rows,
            cell_spacing_m,
            wrap_x=wrap_x,
            tectonic_model=tectonic_model,
            source_uv_bounds=source_uv_bounds,
            sea_level=sea_level,
        )
    return _mountain_morphology_mask_python(
        rows,
        land_rows,
        cell_spacing_m,
        wrap_x=wrap_x,
        tectonic_model=tectonic_model,
        source_uv_bounds=source_uv_bounds,
        sea_level=sea_level,
    )


def _mountain_morphology_mask_python(
    rows,
    land_rows,
    cell_spacing_m,
    *,
    wrap_x=False,
    tectonic_model=None,
    source_uv_bounds=None,
    sea_level=None,
):
    """Pure-Python reference path, used when NumPy is unavailable."""
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

    # A regional child can resolve a mountain system as a broad, mostly
    # monotonic rise.  In that case local relief alone is below the threshold
    # even though the production tectonic model explicitly places the cell in
    # an active uplift/arc system.  Use that causal signal as support for the
    # inherited mask, but only for regional products; the canonical planetary
    # derivative remains purely height-derived.
    if source_uv_bounds and isinstance(tectonic_model, dict):
        tectonic_support = [[0.0] * width for _ in range(height)]
        min_u = float(source_uv_bounds.get("min_u", 0.0) or 0.0)
        max_u = float(source_uv_bounds.get("max_u", 1.0) or 1.0)
        min_v = float(source_uv_bounds.get("min_v", 0.0) or 0.0)
        max_v = float(source_uv_bounds.get("max_v", 1.0) or 1.0)
        for y in range(height):
            v = min_v + (max_v - min_v) * y / max(1, height - 1)
            for x in range(unique_width):
                if not land_rows[y][x]:
                    continue
                u = min_u + (max_u - min_u) * x / max(1, unique_width - 1)
                response = _orogen_forcing_at(u, v, tectonic_model)
                uplift = _clamp(
                    float(response.get("rock_uplift_m", 0.0) or 0.0) / 1800.0,
                    0.0,
                    1.0,
                )
                volcanic = _clamp(
                    float(response.get("volcanic_construction_m", 0.0) or 0.0) / 2400.0,
                    0.0,
                    1.0,
                )
                convergence = _clamp(
                    float(response.get("convergent_influence", 0.0) or 0.0) / 2.0,
                    0.0,
                    1.0,
                )
                tectonic_score = _clamp(
                    uplift * 0.52 + volcanic * 0.28 + convergence * 0.20,
                    0.0,
                    1.0,
                )
                if sea_level is not None:
                    standing = _smoothstep(
                        (float(rows[y][x]) - float(sea_level) - 250.0) / 1000.0
                    )
                    tectonic_score *= 0.30 + 0.70 * standing
                tectonic_support[y][x] = round(tectonic_score, 4)
            if wrap_x and width > unique_width:
                tectonic_support[y][-1] = tectonic_support[y][0]
        for y in range(height):
            for x in range(unique_width):
                raw[y][x] = max(raw[y][x], tectonic_support[y][x] * 0.82)
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
    # Keep the helper's historical two-value return contract; callers and
    # tests outside derivative refresh use it directly.
    return smoothed, relief_threshold_m


def _heightfield_fingerprint(rows, sea_level):
    payload = json.dumps(
        {"rows": rows, "sea_level_m": sea_level},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _neighbour_indices(height, unique_width, wrap_x):
    """West/east columns and north/south rows of the 4-neighbour stencil.

    Non-wrapping grids clamp at the edge, so an edge cell's outside neighbour
    is itself (it never differs from itself).
    """
    columns = np.arange(unique_width)
    rows = np.arange(height)
    if wrap_x:
        west, east = (columns - 1) % unique_width, (columns + 1) % unique_width
    else:
        west, east = np.clip(columns - 1, 0, unique_width - 1), np.clip(columns + 1, 0, unique_width - 1)
    north, south = np.clip(rows - 1, 0, height - 1), np.clip(rows + 1, 0, height - 1)
    return west, east, north, south


def _with_seam(core, width):
    """Pad a unique-column field to ``width`` by repeating column 0 (the seam)."""
    if core.shape[1] >= width:
        return core
    return np.concatenate([core, core[:, :width - core.shape[1]]], axis=1)


def refresh_heightmap_derivatives(
    heightmap,
    *,
    tectonic_model=None,
    inherited_sea_level_m=None,
    progress_callback=None,
):
    """Rebuild every derivative that depends on the evolved heightfield.

    Full planets conserve their equivalent global water depth and solve a new
    sea level.  Regional products inherit the planetary datum and only rebuild
    local masks and morphology.  The duplicate longitude seam is excluded
    from all area-weighted statistics.
    """
    if not isinstance(heightmap, dict):
        return {}
    # Masks and the shelf model are rebuilt below; copying them first only
    # to overwrite them cost about half a second per regional refresh.
    rebuilt_keys = {"surface_masks", "shelf_sediment_model"}
    refreshed = {key: copy.deepcopy(value) for key, value in heightmap.items() if key not in rebuilt_keys}
    _emit_heightmap_progress(progress_callback, 0.05, "Copying the resolved heightfield")
    grid = refreshed.get("sample_grid") if isinstance(refreshed.get("sample_grid"), dict) else {}
    rows = grid.get("rows") if isinstance(grid.get("rows"), list) else []
    if not rows or not rows[0]:
        for key in rebuilt_keys & set(heightmap):
            refreshed[key] = copy.deepcopy(heightmap[key])
        return refreshed
    height = len(rows)
    width = min(len(row) for row in rows)
    wrap_x = bool(grid.get("wrap_x", refreshed.get("wrap_x", True)))
    unique_width = width - 1 if wrap_x and width > 1 else width
    regional = str(refreshed.get("coverage") or "full_planet") != "full_planet" or not wrap_x
    indexed_tectonic_model = (
        _ensure_heightmap_tectonic_model(tectonic_model)
        if regional and isinstance(tectonic_model, dict)
        else tectonic_model
    )
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
    _emit_heightmap_progress(progress_callback, 0.16, "Solving the planetary sea-level datum")

    elevation = np.asarray([row[:width] for row in rows], dtype=np.float64)
    core = elevation[:, :unique_width]
    row_weights = [
        max(1e-6, math.cos((0.5 - y / max(1, height - 1)) * math.pi)) if not regional else 1.0
        for y in range(height)
    ]
    land = np.ones(core.shape, dtype=bool) if sea_level is None else core >= sea_level
    land_per_row = np.count_nonzero(land, axis=1).tolist()
    weighted_land = weighted_ocean = total_weight = 0.0
    for weight, land_count in zip(row_weights, land_per_row):
        weighted_land += weight * land_count
        weighted_ocean += weight * (unique_width - land_count)
        total_weight += weight * unique_width
    west, east, north, south = _neighbour_indices(height, unique_width, wrap_x)
    if sea_level is not None:
        coastal = (
            (land[:, west] != land)
            | (land[:, east] != land)
            | (land[north, :] != land)
            | (land[south, :] != land)
        )
    else:
        coastal = np.zeros(core.shape, dtype=bool)
    land_rows = _with_seam(land, width).tolist()
    ocean_rows = _with_seam(~land, width).tolist()
    coastal_rows = _with_seam(coastal, width).tolist()
    _emit_heightmap_progress(progress_callback, 0.36, "Classifying land, ocean, and coast cells")

    prior_masks = heightmap.get("surface_masks") if isinstance(heightmap.get("surface_masks"), dict) else {}
    ice_rows = copy.deepcopy(prior_masks.get("ice_rows") or [[False] * width for _ in range(height)])
    if len(ice_rows) != height or any(len(row) < width for row in ice_rows):
        ice_rows = [[False] * width for _ in range(height)]
    ice = np.asarray([[bool(value) for value in row[:unique_width]] for row in ice_rows], dtype=bool)
    ice_adjacency = ice | ice[:, west] | ice[:, east] | ice[north, :] | ice[south, :]
    ice_adjacency_rows = _with_seam(ice_adjacency, width).tolist()
    _emit_heightmap_progress(progress_callback, 0.46, "Resolving ice adjacency")

    shelf_model = _shelf_and_sediment_model(
        rows,
        sea_level,
        indexed_tectonic_model,
        wrap_x=wrap_x,
        source_uv_bounds=refreshed.get("source_uv_bounds") if regional else None,
    )
    _emit_heightmap_progress(progress_callback, 0.59, "Resolving shelves and sediment wedges")
    prior_shelf_model = heightmap.get("shelf_sediment_model")
    if isinstance(prior_shelf_model, dict) and isinstance(
        prior_shelf_model.get("bathymetry_materialization"), dict
    ):
        # Derivative refreshes rebuild the shelf rows from the evolved
        # heightfield, but must retain the causal audit that explains why the
        # canonical parent contains a shallow-margin ramp.
        shelf_model["bathymetry_materialization"] = copy.deepcopy(
            prior_shelf_model["bathymetry_materialization"]
        )
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
        tectonic_model=indexed_tectonic_model if regional else None,
        source_uv_bounds=refreshed.get("source_uv_bounds") if regional else None,
        sea_level=sea_level,
    )
    _emit_heightmap_progress(progress_callback, 0.78, "Resolving mountain morphology")
    mountain_support_source = (
        "resolved_relief_plus_production_orogen"
        if regional and isinstance(tectonic_model, dict)
        else "resolved_relief"
    )
    coastal_y, coastal_x = np.nonzero(coastal)
    gradient_x = (core[coastal_y, east[coastal_x]] - core[coastal_y, west[coastal_x]]).tolist()
    gradient_y = (core[south[coastal_y], coastal_x] - core[north[coastal_y], coastal_x]).tolist()
    gradient_scale = max(1.0, 2.0 * cell_spacing_m)
    coastal_gradients = [math.hypot(dx, dy) / gradient_scale for dx, dy in zip(gradient_x, gradient_y)]
    shelf_cell_count = (
        int(np.count_nonzero(np.asarray([row[:unique_width] for row in shelf_rows], dtype=bool)))
        if shelf_rows else 0
    )

    land_fraction = weighted_land / max(1e-9, total_weight)
    ocean_fraction = weighted_ocean / max(1e-9, total_weight)
    ice_weight = 0.0
    for weight, ice_count in zip(row_weights, np.count_nonzero(ice, axis=1).tolist()):
        ice_weight += ice_count * weight
    ice_fraction = ice_weight / max(1e-9, total_weight)
    sample_count = max(1, core.size)
    hypsometry = dict(refreshed.get("hypsometry_summary") or {})
    hypsometry.update({
        "broad_plain_fraction": round(int(np.count_nonzero((core >= -2000.0) & (core <= 1000.0))) / sample_count, 3),
        "mountain_fraction_above_2000m": round(int(np.count_nonzero(core > 2000.0)) / sample_count, 3),
        "deep_basin_fraction_below_minus_2000m": round(int(np.count_nonzero(core < -2000.0)) / sample_count, 3),
        "land_fraction": round(land_fraction, 4),
        "ocean_fraction": round(ocean_fraction, 4),
        "ice_fraction": round(ice_fraction, 4),
        "continental_shelf_fraction": round(shelf_cell_count / max(1, unique_width * height), 4),
        "area_weighting": "spherical_cosine_latitude" if not regional else "local_equal_area_approximation",
        "duplicate_longitude_seam_excluded": bool(wrap_x and width > unique_width),
    })
    shelf_model["morphology_summary"] = {
        "mean_coastal_gradient": round(sum(coastal_gradients) / max(1, len(coastal_gradients)), 6),
        "mean_resolved_shelf_width_km": round(shelf_cell_count * cell_spacing_m / max(1, int(np.count_nonzero(coastal))) / 1000.0, 2),
        "coastal_sample_count": len(coastal_gradients),
    }
    mountain = np.asarray([row[:unique_width] for row in mountain_rows], dtype=np.float64)
    replaced_masks = {
        "land_rows", "ocean_rows", "coastal_rows", "ice_rows", "ice_adjacency_rows",
        "continental_shelf_rows", "mountain_rows",
    }
    refreshed.update({
        "min_elevation_m": round(float(core.min()), 1),
        "max_elevation_m": round(float(core.max()), 1),
        "sea_level_m": None if sea_level is None else round(sea_level, 2),
        "sea_level_resolution": sea_level_resolution,
        "surface_masks": {
            **{key: copy.deepcopy(value) for key, value in prior_masks.items() if key not in replaced_masks},
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
            "model": "resolved_relief_plus_orogen_support_v2",
            "relief_threshold_m": round(mountain_relief_threshold_m, 2),
            "support_source": mountain_support_source,
            "mountain_cell_fraction": round(
                int(np.count_nonzero(mountain >= 0.35)) / max(1, height * unique_width),
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
    _emit_heightmap_progress(progress_callback, 1.0, "Heightmap derivatives complete")
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


def derive_heightmap_model(
    terrain,
    seed=None,
    physics=None,
    planet_id="",
    tectonic_model=None,
    crater_model=None,
    mechanical_lithology_model=None,
    geochemical_material_model=None,
    progress_callback=None,
):
    terrain = terrain if isinstance(terrain, dict) else {}
    heightfield = terrain.get("heightfield") if isinstance(terrain.get("heightfield"), dict) else {}
    canvas = terrain.get("map_canvas") if isinstance(terrain.get("map_canvas"), dict) else {}
    map_seed = terrain.get("map_seed") or resolved_map_seed(seed, planet_id=planet_id)
    simulated_age_myr = float(terrain.get("simulated_age_myr", 0.0) or 0.0)

    width_px = int(canvas.get("width_px", PLANETARY_CANVAS_WIDTH_PX) or PLANETARY_CANVAS_WIDTH_PX)
    height_px = int(canvas.get("height_px", PLANETARY_CANVAS_HEIGHT_PX) or PLANETARY_CANVAS_HEIGHT_PX)
    circumference_m = float(
        canvas.get("circumference_m")
        or (math.tau * float((physics or {}).get("radius_m", 0.0) or 0.0))
        or 0.0
    )
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
    local_material_provinces = (
        geochemical_material_model.get("provinces") or []
        if isinstance(geochemical_material_model, dict)
        else []
    )
    # Rock strength varies continuously with lithotectonic composition; the
    # substrate prior/province model carries it as a global raster.
    relief_retention_rows = (
        geochemical_material_model.get("relief_retention_rows")
        if isinstance(geochemical_material_model, dict)
        else None
    )
    relief_retention_grid = None
    if relief_retention_rows and np is not None:
        relief_retention_grid = np.asarray(relief_retention_rows, dtype=np.float64)
        local_material_provinces = []
    if local_material_provinces:
        from simulations.world_gen.tectonics import _nearest_plate_index
    deformation_state_model = None
    if isinstance(sampled_tectonic_model, dict) and sampled_tectonic_model.get("plates"):
        _emit_heightmap_progress(progress_callback, 0.02, "Preparing tectonic deformation fields")

        def deformation_progress(fraction, detail, _preview=None):
            _emit_heightmap_progress(
                progress_callback,
                0.02 + float(fraction) * 0.14,
                detail,
            )

        deformation_state_model = derive_planetary_deformation_state(
            terrain,
            sampled_tectonic_model,
            mechanical_lithology_model=mechanical_lithology_model,
            progress_callback=deformation_progress,
        )
        sampled_tectonic_model["deformation_state_model"] = deformation_state_model
    explicit_crater_model = isinstance(crater_model, dict)

    # LOD0 scientific resolution is an explicit physical contract.  It must
    # not change when the display canvas changes, and must not be inferred from
    # render pixels.  A smaller explicit grid remains available for authored
    # fixtures and bounded performance benchmarks.
    sample_width, sample_height, resolution_mode = _heightmap_sample_dimensions(
        canvas, heightfield,
    )
    evaluation_width, evaluation_height = _lod0_evaluation_dimensions(
        sample_width,
        sample_height,
        resolution_mode,
    )
    rows = []
    sample_values = []
    sample_positions = []

    def partial_preview(completed_rows):
        if not rows:
            return None
        current_width = len(rows[0])
        current_height = (
            sample_height
            if len(rows) == sample_height and current_width == sample_width
            else evaluation_height
        )
        preview_rows = [list(values) for values in rows]
        preview_rows.extend(
            [[None] * current_width for _index in range(max(0, current_height - len(preview_rows)))]
        )
        return {
            "status": "heightmap_building",
            "projection": canvas.get("projection", "equirectangular"),
            "sea_level_m": None if sea_level is None else float(sea_level),
            "min_elevation_m": min_elevation,
            "max_elevation_m": max_elevation,
            "preview_completed_rows": completed_rows,
            "sample_grid": {
                "width": current_width,
                "height": current_height,
                "wrap_x": True,
                "wrap_y": False,
                "rows": preview_rows,
            },
        }

    _emit_heightmap_progress(progress_callback, 0.17, "Sampling base planetary relief")
    for row in range(evaluation_height):
        ny = row / max(1, evaluation_height - 1)
        row_values = []
        for col in range(evaluation_width):
            nx = 0.0 if col == evaluation_width - 1 else col / max(1, evaluation_width - 1)
            # Explicit impacts are applied in a second pass after the
            # pre-impact sea level is known.  Passing an empty catalogue here
            # also disables the legacy generic crater stamp without changing
            # dry worlds that do not use an explicit crater model.
            wave_craters = {} if explicit_crater_model else crater_model
            normalized = _wave_height(
                nx,
                ny,
                terrain,
                tectonic_model=sampled_tectonic_model,
                crater_model=wave_craters,
                crater_spatial_index=None,
                map_seed=map_seed,
                lod0_synthesis=resolution_mode == "canonical_lod0",
            )
            if relief_retention_grid is not None:
                grid_height, grid_width = relief_retention_grid.shape
                fx = (float(nx) % 1.0) * (grid_width - 1)
                fy = _clamp(ny, 0.0, 1.0) * (grid_height - 1)
                gx0, gy0 = int(fx), int(fy)
                gx1, gy1 = min(grid_width - 1, gx0 + 1), min(grid_height - 1, gy0 + 1)
                tx, ty = fx - gx0, fy - gy0
                retention = (
                    (relief_retention_grid[gy0, gx0] * (1.0 - tx) + relief_retention_grid[gy0, gx1] * tx) * (1.0 - ty)
                    + (relief_retention_grid[gy1, gx0] * (1.0 - tx) + relief_retention_grid[gy1, gx1] * tx) * ty
                )
                normalized *= _clamp(retention, 0.94, 1.06)
            elif local_material_provinces:
                province = local_material_provinces[
                    _nearest_plate_index(nx, ny, local_material_provinces)
                ]
                retention = float(
                    (province.get("terrain_response") or {}).get("relief_retention", 1.0)
                )
                normalized *= _clamp(retention, 0.94, 1.06)
            elevation = midpoint + normalized * half_range
            elevation = round(_clamp(elevation, min_elevation, max_elevation), 1)
            row_values.append(elevation)
            sample_positions.append((col, row, nx, ny, elevation))
        if row_values:
            row_values[-1] = row_values[0]
        sample_values.extend(row_values)
        rows.append(row_values)
        if row == evaluation_height - 1 or row % max(1, evaluation_height // 12) == 0:
            row_fraction = (row + 1) / max(1, evaluation_height)
            _emit_heightmap_progress(
                progress_callback,
                0.17 + row_fraction * 0.36,
                f"Sampling relief row {row + 1} of {evaluation_height}",
                partial_preview(row + 1),
            )

    crustal_calibration = _crustal_freeboard_calibration(rows, evaluation_width, evaluation_height, sampled_tectonic_model)
    if crustal_calibration.get("ocean_shift_m"):
        rows = _apply_crustal_freeboard_calibration(
            rows, evaluation_width, evaluation_height, sampled_tectonic_model, crustal_calibration,
            min_elevation=min_elevation, max_elevation=max_elevation,
        )
        sample_values = [value for row in rows for value in row]
        sample_positions = [
            (col, row_index, nx, ny, rows[row_index][col])
            for col, row_index, nx, ny, _elevation in sample_positions
        ]

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
        _emit_heightmap_progress(progress_callback, 0.56, "Conditioning impacts to the generated surface")
        crater_model, crater_surface_audit = condition_crater_model_to_surface(
            crater_model, terrain, rows, preliminary_sea_level,
        )
        crater_spatial_index = _crater_spatial_index(crater_model)
        for row_index in range(evaluation_height):
            ny = row_index / max(1, evaluation_height - 1)
            for col_index in range(evaluation_width):
                nx = 0.0 if col_index == evaluation_width - 1 else col_index / max(1, evaluation_width - 1)
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
            if row_index == evaluation_height - 1 or row_index % max(1, evaluation_height // 10) == 0:
                row_fraction = (row_index + 1) / max(1, evaluation_height)
                _emit_heightmap_progress(
                    progress_callback,
                    0.58 + row_fraction * 0.13,
                    f"Carving impact relief row {row_index + 1} of {evaluation_height}",
                    partial_preview(row_index + 1),
                )
        sample_values = [value for row_values in rows for value in row_values]
        sample_positions = [
            (
                col,
                row,
                0.0 if col == evaluation_width - 1 else col / max(1, evaluation_width - 1),
                row / max(1, evaluation_height - 1),
                rows[row][col],
            )
            for row in range(evaluation_height)
            for col in range(evaluation_width)
        ]

    if (evaluation_width, evaluation_height) != (sample_width, sample_height):
        _emit_heightmap_progress(
            progress_callback,
            0.72,
            f"Interpolating global scaffold to {sample_width} x {sample_height}",
            partial_preview(evaluation_height),
        )
        rows = _resample_height_rows(rows, sample_width, sample_height)
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

    # The tectonic sampler remains the source of truth for continental and
    # oceanic elevation.  At planetary LOD0 its freeboard transition can be
    # steeper than one scientific cell, which otherwise removes nearly all
    # continental-shelf cells before the shelf and sediment systems see them.
    # Materialize a bounded margin ramp here, then let the normal water-volume
    # solve restore the global datum.  Authored small grids retain their old
    # behavior so fixtures and regional products are not silently changed.
    bathymetry_materialization = {"status": "not_applicable"}
    if resolution_mode == "canonical_lod0" and preliminary_sea_level is not None:
        _emit_heightmap_progress(progress_callback, 0.73, "Materializing shallow continental margins")
        bathymetry_materialization = _materialize_shallow_margin_bathymetry(
            rows,
            preliminary_sea_level,
            sampled_tectonic_model,
            circumference_m,
        )
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
    shelf_model["bathymetry_materialization"] = bathymetry_materialization
    _emit_heightmap_progress(progress_callback, 0.82, "Resolving water, ice, and shelf coverage", partial_preview(sample_height))

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
        "circumference_m": circumference_m or None,
        "equator_resolution_m_per_px": canvas.get("equator_resolution_m_per_px"),
        # Physical spacing of the scientific samples. Render-pixel resolution
        # is much finer and must never be used for slope or hillshade.
        "sample_spacing_x_m": round(
            circumference_m / max(1, sample_width - 1),
            3,
        ) if circumference_m else None,
        "sample_spacing_y_m": round(
            circumference_m * 0.5 / max(1, sample_height - 1),
            3,
        ) if circumference_m else None,
        "vertical_datum": canvas.get("vertical_datum", "mean_radius"),
        "elevation_unit": "m",
        "min_elevation_m": round(min_elevation, 1),
        "max_elevation_m": round(max_elevation, 1),
        "sea_level_m": None if sea_level is None else round(float(sea_level), 1),
        "equivalent_global_water_depth_m": round(equivalent_global_water_depth_m, 2),
        "crustal_freeboard_calibration": dict(crustal_calibration),
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
            "model_version": "physiographic-heightmap-v9-global-scaffold",
            "surface_regime": terrain.get("surface_regime", "rocky_surface"),
            "continental_lithosphere": None if terrain.get("surface_regime") == "cratered_ice_shell" else "assembled_cratons_accreted_terranes_rifted_margins",
            "oceanic_lithosphere": None if terrain.get("surface_regime") == "cratered_ice_shell" else "abyssal_plains_ridges_trenches",
            "active_margin_features": ["ice_chasmata", "extensional_fractures"] if terrain.get("surface_regime") == "cratered_ice_shell" else ["orogenic_belts", "volcanic_arcs", "foreland_basins"],
            "passive_margin_features": [] if terrain.get("surface_regime") == "cratered_ice_shell" else ["continental_shelves", "slope_breaks", "rifted_edges"],
            "erosion_model": "impact_gardening_and_viscous_relaxation" if terrain.get("surface_regime") == "cratered_ice_shell" else "multiscale_fl_pluvial_glacial_coastal_erosion",
            "continental_processes": ["craton_assembly", "terrane_accretion", "suture_uplift", "continental_rifting", "sedimentary_subsidence"],
            "island_processes": ["subduction_volcanic_arcs", "age_progressive_hotspot_chains", "rifted_microcontinents"],
            "mountain_forcing": "coherent_orogen_system_signed_cross_range_profiles",
            "mountain_forcing_components": ["rock_uplift", "tectonic_subsidence", "volcanic_construction", "outer_bulge", "isostatic_response", "flexural_response"],
            "elevation_composition": "persistent_planetary_deformation_state_v1",
            "tectonic_boundary_geometry": "continuous_plate_distance_contour_v1",
            "crustal_freeboard": "continuous_lithosphere_fraction_isostasy_v2",
            "coastline_parent_truth": "dense_continuous_sea_level_crossings_v2",
            "age_expression": "explicit_tectonic_maturity_and_surface_processes_not_heightfield_smoothing",
            "inland_basin_count": len(_continental_process_model(str(map_seed or ""))["basins"]),
            "hotspot_chain_count": len(_continental_process_model(str(map_seed or ""))["island_chains"]),
            "sample_resolution": f"{sample_width}x{sample_height}",
        },
        "resolution_contract": {
            "version": CANONICAL_LOD0_RESOLUTION_VERSION,
            "detail_level": 0,
            "mode": resolution_mode,
            "scientific_sample_dimensions": {
                "width": sample_width,
                "height": sample_height,
            },
            "causal_evaluation_dimensions": {
                "width": evaluation_width,
                "height": evaluation_height,
            },
            "render_canvas_dimensions": {
                "width": width_px,
                "height": height_px,
            },
            "benchmark_dimensions": {
                "width": CANONICAL_LOD0_BENCHMARK_DIMENSIONS[0],
                "height": CANONICAL_LOD0_BENCHMARK_DIMENSIONS[1],
            },
            "resolution_source": "global_causal_anchors_interpolated_to_consumer_grid",
            "detail_ownership": "province_and_surface_detail_deferred_to_regional_regeneration",
            "interpolation": (
                "bilinear_numpy" if np is not None else "bilinear_python"
            ) if (evaluation_width, evaluation_height) != (sample_width, sample_height) else "none",
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
            "orogen_systems": (
                ((tectonic_model or {}).get("orogen_system_model") or {}).get("system_count")
                if isinstance(tectonic_model, dict)
                else None
            ),
            "orogen_system_model_version": (
                ((tectonic_model or {}).get("orogen_system_model") or {}).get("model_version")
                if isinstance(tectonic_model, dict)
                else None
            ),
        },
        "deformation_state_model": deformation_state_model,
        "crater_surface_resolution": crater_surface_audit,
    }
    def derivative_progress(fraction, detail, _preview=None):
        _emit_heightmap_progress(
            progress_callback,
            0.84 + float(fraction) * 0.16,
            detail,
            model,
        )

    return refresh_heightmap_derivatives(
        model,
        tectonic_model=sampled_tectonic_model,
        progress_callback=derivative_progress,
    )


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
