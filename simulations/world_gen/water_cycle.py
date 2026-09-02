"""Climate, ocean, hydrology, and drainage models for generated worlds.

LOD contract: global climate, water inventory, sea level, major drainage, and
ice are canonical LOD0 fields. Descendants inherit parent boundary conditions
and progressively resolve regional runoff, lakes, tributaries, channels, and
microdrainage without silently replacing parent topology.
"""

import heapq
import logging
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


WATER_CYCLE_MODEL_VERSION = "monthly-normals-koppen-geiger-v20-parent-seeded-regional-moisture"
PARENT_CLIMATE_EDGE_BLEND_MARGIN = 0.025

# Only a fraction of condensed moisture truly leaves the advecting air mass
# each hop; the rest represents the same parcel producing rain repeatedly
# over a long fetch (real frontal/monsoonal systems don't exhaust after one
# grid cell). Splitting this from the local rain amount keeps a coastal cell
# from starving everything downwind just by raining efficiently.
MOISTURE_DEPLETION_FRACTION = 0.70
# A small energy-driven (not precipitation-bootstrapped) floor on land
# recycling, so a currently-dry cell isn't locked out of ever recovering --
# bare/moist ground and rock still carry some baseline evaporative flux.
BASELINE_LAND_RECYCLING_FRACTION = 0.05
# A moisture FLOOR (caps how low a cell's moisture can fall each iteration)
# rather than a flat additive supply -- an additive term compounds every
# iteration on cells that are already adequately wet and proved explosively
# sensitive over ~200 solver iterations. A floor only ever raises cells that
# would otherwise fall below it, so it cannot runaway the same way. Weighted
# toward the same ITCZ/storm-track bands real continental interiors (Amazon,
# Congo, US Midwest) are sustained by, independent of direct coastal advection.
BASELINE_LAND_MOISTURE_FLOOR = 0.09
STORM_TRACK_MOISTURE_FLOOR_WEIGHT = 0.6
# Characteristic recovery length (in grid cells) for orographic rain shadow:
# strong immediately behind a ridge, tapering off with distance rather than
# holding at full strength for the entire upwind scan window. Real rain
# shadows (e.g. the Great Basin, Patagonia's steppe) persist for a
# meaningful distance, not just a handful of cells.
RAIN_SHADOW_RECOVERY_LENGTH_CELLS = 10.0
# Half-width (in normalized latitude, 0-1 = pole to pole) over which the
# meridional wind smoothly passes through zero at the equator instead of
# hard-flipping sign between hemispheres -- real ITCZ convergence is
# continuous, not a knife-edge discontinuity.
EQUATOR_WIND_SMOOTHING_WIDTH = 0.035
# Half-width (in normalized latitude) over which adjacent circulation cells
# (trade winds / westerlies / polar easterlies) blend into each other
# instead of the wind direction completely reversing across a single grid
# row at the cell boundary.
WIND_BAND_TRANSITION_WIDTH = 0.05
# Warm ocean currents making landfall (Gulf-Stream-analog western boundary
# currents) carry moisture-laden air onshore, sustaining lush coastlines
# (British Isles, Pacific Northwest) beyond what the local latitude band
# alone would produce. This is the warm-anomaly counterpart to the cold
# upwelling-desert suppression already applied to coastal condensation.
WARM_CURRENT_MOISTURE_BONUS = 0.35
WARM_CURRENT_ANOMALY_SCALE_K = 5.0
# Real orographic rainfall peaks in a mid-elevation cloud-forest/fog-capture
# band and falls off both below it (less lift) and above it (past the cloud
# deck, drier) rather than increasing monotonically with slope alone.
CLOUD_FOREST_ELEVATION_NORM = 0.40
CLOUD_FOREST_BAND_WIDTH = 0.18
CLOUD_FOREST_BONUS_STRENGTH = 0.10

# Colors follow the conventional Koppen-Geiger map palette (as used by
# Peel/Beck-style reference maps: tropical = blues, arid = reds/oranges,
# temperate = greens/yellow-greens, continental = teals/purples, polar =
# grays) rather than an ad hoc scheme, so this reads the way anyone who has
# seen a real Koppen map expects. The classification logic itself was
# already correct and complete -- this only changes the palette.
KOPPEN_CLASSES = {
    "Af": {"label": "Tropical Rainforest", "color": [0, 0, 254]},
    "Am": {"label": "Tropical Monsoon", "color": [0, 119, 255]},
    "Aw": {"label": "Tropical Savanna", "color": [70, 169, 250]},
    "As": {"label": "Tropical Savanna, Dry Summer", "color": [96, 180, 240]},
    "BWh": {"label": "Hot Desert", "color": [255, 0, 0]},
    "BWk": {"label": "Cold Desert", "color": [255, 150, 150]},
    "BSh": {"label": "Hot Steppe", "color": [245, 165, 0]},
    "BSk": {"label": "Cold Steppe", "color": [255, 220, 100]},
    "Csa": {"label": "Hot-summer Mediterranean", "color": [255, 255, 0]},
    "Csb": {"label": "Warm-summer Mediterranean", "color": [198, 199, 0]},
    "Csc": {"label": "Cool-summer Mediterranean", "color": [150, 150, 0]},
    "Cwa": {"label": "Dry-winter Humid Subtropical", "color": [150, 255, 150]},
    "Cwb": {"label": "Dry-winter Subtropical Highland", "color": [100, 200, 100]},
    "Cwc": {"label": "Dry-winter Cool Highland", "color": [50, 150, 50]},
    "Cfa": {"label": "Humid Subtropical", "color": [198, 255, 78]},
    "Cfb": {"label": "Oceanic", "color": [102, 255, 51]},
    "Cfc": {"label": "Subpolar Oceanic", "color": [51, 199, 1]},
    "Dsa": {"label": "Dry-summer Continental", "color": [255, 0, 254]},
    "Dsb": {"label": "Dry-summer Continental", "color": [198, 0, 199]},
    "Dsc": {"label": "Dry-summer Subarctic", "color": [150, 50, 150]},
    "Dsd": {"label": "Severe Dry-summer Subarctic", "color": [150, 100, 150]},
    "Dwa": {"label": "Dry-winter Continental", "color": [171, 177, 255]},
    "Dwb": {"label": "Dry-winter Continental", "color": [90, 119, 219]},
    "Dwc": {"label": "Dry-winter Subarctic", "color": [76, 81, 181]},
    "Dwd": {"label": "Severe Dry-winter Subarctic", "color": [50, 0, 135]},
    "Dfa": {"label": "Hot-summer Continental", "color": [0, 255, 255]},
    "Dfb": {"label": "Warm-summer Continental", "color": [56, 200, 255]},
    "Dfc": {"label": "Subarctic", "color": [0, 126, 125]},
    "Dfd": {"label": "Severe Subarctic", "color": [0, 69, 94]},
    "ET": {"label": "Tundra", "color": [178, 178, 178]},
    "EF": {"label": "Ice Cap", "color": [104, 104, 104]},
    "Ocean": {"label": "Ocean", "color": [50, 92, 132]},
}


def shade_koppen_rgb(base_rgb, class_code, elevation, min_elevation, max_elevation):
    """Return the canonical visual shade for one Köppen climate cell.

    The climate class color is generated truth.  Relief shading is a display
    concern only, but it must be identical in the world-generation preview,
    the map renderer, and diagnostic comparisons or the same model will look
    like it changed between LODs.  Keep this helper pygame-free so every
    renderer uses the same deterministic transform.
    """
    try:
        color = tuple(max(0, min(255, int(base_rgb[index]))) for index in range(3))
    except (TypeError, ValueError, IndexError):
        color = (150, 150, 150)
    try:
        elevation_value = float(elevation or 0.0)
        minimum = float(min_elevation or 0.0)
        maximum = float(max_elevation or 0.0)
    except (TypeError, ValueError):
        elevation_value, minimum, maximum = 0.0, 0.0, 1.0
    span = max(1.0, maximum - minimum)
    elevation_norm = max(0.0, min(1.0, (elevation_value - minimum) / span))

    def mix(color_a, color_b, weight_b):
        weight_b = max(0.0, min(1.0, float(weight_b or 0.0)))
        return tuple(
            max(0, min(255, int(color_a[index] * (1.0 - weight_b) + color_b[index] * weight_b)))
            for index in range(3)
        )

    ocean = str(class_code) == "Ocean"
    if ocean:
        relief_color = mix((28, 69, 118), (73, 132, 166), elevation_norm)
        color = mix(color, relief_color, 0.14)
        shade = 0.76 + (1.0 - elevation_norm) * 0.14
    else:
        if elevation_norm < 0.52:
            relief_color = mix((105, 139, 91), (170, 151, 104), elevation_norm / 0.52)
        else:
            relief_color = mix((170, 151, 104), (218, 215, 202), (elevation_norm - 0.52) / 0.48)
        color = mix(color, relief_color, 0.20)
        shade = 0.78 + elevation_norm * 0.24
    return tuple(max(0, min(255, int(channel * shade))) for channel in color)


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, float(value)))


def _rows_all_finite(rows):
    """True if a nested list-of-lists grid contains no NaN/inf values."""
    if not rows:
        return False
    return all(
        math.isfinite(value)
        for row in rows
        for value in row
    )


def _smoothstep(edge0, edge1, x):
    t = _clamp((x - edge0) / max(1e-9, edge1 - edge0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _local_latitude_fraction(y, height):
    """Patch-local latitude fraction in [0, 1], ignorant of source_uv_bounds.

    Used by the scalar climate solver so it mirrors the array solver's local
    np.arange broadcast exactly; do not make this source-uv aware.
    """
    return abs(y / max(1, height - 1) - 0.5) * 2.0


def _global_latitude_metrics(ny):
    """Return (latitude_signed_deg, latitude_abs_fraction) from a global v coordinate.

    latitude_signed_deg is hemisphere-aware (+north/-south); latitude_abs_fraction
    is the old ignore-hemisphere magnitude in [0, 1]. Both must be recomputed per
    row wherever latitude is needed -- a prior refactor left one call site reusing
    a stale value from a previous loop, which silently broke hemisphere-aware
    Koppen classification for nearly every row.
    """
    latitude_signed_deg = (0.5 - ny) * 180.0
    latitude_abs_fraction = abs(latitude_signed_deg) / 90.0
    return latitude_signed_deg, latitude_abs_fraction


def _orbital_eccentricity(seed):
    seed = seed if isinstance(seed, dict) else {}
    return _clamp(seed.get("orbital_eccentricity", seed.get("eccentricity", 0.0)), 0.0, 0.85)


def _sample_inherited_rows(
    rows,
    global_u,
    global_v,
    source_bounds=None,
    *,
    width_hint=None,
):
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
    if width_hint is None:
        width = min(len(row) for row in rows if isinstance(row, list))
    else:
        try:
            width = int(width_hint)
        except (TypeError, ValueError):
            width = 0
        width = min(width, len(rows[0]))
    if width <= 0:
        return None
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
    # Keep the exact parent value on the outer boundary, but confine the
    # conditioning strip to a few cells. A broad 7.5% strip was visible as a
    # rectangular frame in 100 km diagnostic tiles after climate upscaling.
    transition = _clamp(edge_distance / PARENT_CLIMATE_EDGE_BLEND_MARGIN)
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
    target_width = min(257, width)
    target_height = min(max_height, len(rows))
    wrap_x = bool(heightmap.get("wrap_x", True)) if isinstance(heightmap, dict) else True
    if target_width == width and target_height == len(rows):
        return rows
    # Prefilter, then reconstruct onto the climate grid. Integer stride
    # decimation turned a 385x193 parent into only 193x97 samples and exposed
    # large rectangular cells. This retains the intended 257x129 solve while
    # suppressing aliases from unresolved ridge texture.
    filtered = _relax_continuous_planetary_field(rows, 0.16)
    source_height = len(filtered)
    sampled = []
    for target_y in range(target_height):
        source_y = target_y / max(1, target_height - 1) * max(1, source_height - 1)
        y0 = int(math.floor(source_y))
        y1 = min(source_height - 1, y0 + 1)
        ty = source_y - y0
        sampled_row = []
        for target_x in range(target_width):
            source_x = target_x / max(1, target_width - 1) * max(1, width - 1)
            x0 = int(math.floor(source_x))
            x1 = min(width - 1, x0 + 1)
            tx = source_x - x0
            top = float(filtered[y0][x0]) * (1.0 - tx) + float(filtered[y0][x1]) * tx
            bottom = float(filtered[y1][x0]) * (1.0 - tx) + float(filtered[y1][x1]) * tx
            sampled_row.append(top * (1.0 - ty) + bottom * ty)
        if wrap_x:
            sampled_row[-1] = sampled_row[0]
        sampled.append(sampled_row)
    return sampled


def _relax_continuous_planetary_field(rows, strength):
    """Remove solver-cell discontinuities without blurring causal structure."""
    if not rows or len(rows) < 3 or len(rows[0]) < 4:
        return rows
    height = len(rows)
    width = min(len(row) for row in rows)
    # Full planetary grids duplicate longitude zero in their final column.
    duplicate_seam = all(
        abs(float(row[0]) - float(row[width - 1])) < 1e-6
        for row in rows
    )
    unique_width = width - 1 if duplicate_seam else width
    amount = _clamp(strength, 0.0, 0.45)
    result = [[float(value) for value in row[:width]] for row in rows]
    for y in range(height):
        north = max(0, y - 1)
        south = min(height - 1, y + 1)
        for x in range(unique_width):
            west = (x - 1) % unique_width
            east = (x + 1) % unique_width
            neighbor_mean = (
                float(rows[y][west])
                + float(rows[y][east])
                + float(rows[north][x])
                + float(rows[south][x])
            ) * 0.25
            result[y][x] = float(rows[y][x]) * (1.0 - amount) + neighbor_mean * amount
        if duplicate_seam:
            result[y][-1] = result[y][0]
    return result


def _barrier_aware_relax_field(
    field_rows,
    elevation_rows,
    *,
    strength=0.32,
    passes=2,
    preserve_total=False,
    zonal_bias=1.0,
):
    """Diffuse cell lanes while retaining mountain-controlled gradients."""
    if not field_rows or len(field_rows) < 3 or len(field_rows[0]) < 4:
        return field_rows
    height = min(len(field_rows), len(elevation_rows or field_rows))
    width = min(
        min(len(row) for row in field_rows[:height]),
        min(len(row) for row in (elevation_rows or field_rows)[:height]),
    )
    values = [[float(value) for value in row[:width]] for row in field_rows[:height]]
    elevations = [
        [float(value) for value in row[:width]]
        for row in (elevation_rows or field_rows)[:height]
    ]
    duplicate_seam = all(
        abs(values[y][0] - values[y][-1]) < 1e-6
        and abs(elevations[y][0] - elevations[y][-1]) < 1e-6
        for y in range(height)
    )
    unique_width = width - 1 if duplicate_seam else width
    amount = _clamp(strength, 0.0, 0.48)
    zonal_weight = max(0.25, min(4.0, float(zonal_bias or 1.0)))
    area_weights = [
        max(0.02, math.cos((y / max(1, height - 1) - 0.5) * math.pi))
        for y in range(height)
    ]
    initial_total = sum(
        values[y][x] * area_weights[y]
        for y in range(height)
        for x in range(unique_width)
    )
    for _pass in range(max(1, int(passes or 1))):
        source = values
        target = [row[:] for row in source]
        for y in range(height):
            north = max(0, y - 1)
            south = min(height - 1, y + 1)
            for x in range(unique_width):
                center_height = elevations[y][x]
                weighted_sum = 0.0
                weight_sum = 0.0
                for nx, ny, directional_weight in (
                    ((x - 1) % unique_width, y, zonal_weight),
                    ((x + 1) % unique_width, y, zonal_weight),
                    (x, north, 1.0),
                    (x, south, 1.0),
                ):
                    # A kilometre-scale barrier strongly inhibits lateral
                    # reconstruction; ordinary rolling relief does not.
                    barrier = math.exp(
                        -((abs(elevations[ny][nx] - center_height) / 1050.0) ** 1.35)
                    )
                    weight = barrier * directional_weight
                    weighted_sum += source[ny][nx] * weight
                    weight_sum += weight
                neighbor_mean = weighted_sum / max(1e-9, weight_sum)
                target[y][x] = source[y][x] * (1.0 - amount) + neighbor_mean * amount
            if duplicate_seam:
                target[y][-1] = target[y][0]
        values = target
    if preserve_total:
        resolved_total = sum(
            values[y][x] * area_weights[y]
            for y in range(height)
            for x in range(unique_width)
        )
        scale = initial_total / max(1e-9, resolved_total)
        for y in range(height):
            for x in range(unique_width):
                values[y][x] = max(0.0, values[y][x] * scale)
            if duplicate_seam:
                values[y][-1] = values[y][0]
    return values


def _sample_bilinear_rows(rows, u, v, *, wrap_x=True):
    if not rows or not rows[0]:
        return 0.0
    height = len(rows)
    width = min(len(row) for row in rows)
    duplicate_seam = bool(
        wrap_x
        and width > 2
        and all(
            abs(float(row[0]) - float(row[width - 1])) < 1e-6
            for row in rows
        )
    )
    unique_width = width - 1 if duplicate_seam else width
    px = (float(u) % 1.0 if wrap_x else _clamp(u)) * max(1, unique_width)
    py = _clamp(v) * max(1, height - 1)
    x0 = int(math.floor(px)) % unique_width
    x1 = (x0 + 1) % unique_width if wrap_x else min(unique_width - 1, x0 + 1)
    y0 = max(0, min(height - 1, int(math.floor(py))))
    y1 = min(height - 1, y0 + 1)
    tx, ty = px - math.floor(px), py - math.floor(py)
    top = float(rows[y0][x0]) * (1.0 - tx) + float(rows[y0][x1]) * tx
    bottom = float(rows[y1][x0]) * (1.0 - tx) + float(rows[y1][x1]) * tx
    return top * (1.0 - ty) + bottom * ty


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
    heap = []
    for y, row in enumerate(ocean_mask):
        for x, is_ocean in enumerate(row[:width]):
            if is_ocean:
                distances[y][x] = 0.0
                heap.append((0.0, x, y))

    if not heap:
        return [[1.0 for _x in range(width)] for _y in range(height)]

    # Eight-directional (octile) Dijkstra distance from the coast, not a
    # four-directional BFS. A cardinal-only flood fill is a Manhattan/diamond
    # distance metric; against a typically-diagonal coastline its integer
    # rings alias into a dashed staircase texture tracing the shoreline,
    # which then propagates through maritime_land_convergence into
    # condensation_efficiency, precipitation, temperature and Koppen zones.
    # See tectonics.py's ridge-distance flood fill for the same fix applied
    # to seafloor-spreading age.
    heapq.heapify(heap)
    diagonal = math.sqrt(2.0)
    neighbours = (
        (-1, 0, 1.0), (1, 0, 1.0), (0, -1, 1.0), (0, 1, 1.0),
        (-1, -1, diagonal), (1, -1, diagonal), (-1, 1, diagonal), (1, 1, diagonal),
    )
    while heap:
        dist, x, y = heapq.heappop(heap)
        if dist > distances[y][x]:
            continue
        for dx, dy, cost in neighbours:
            ny = y + dy
            if not 0 <= ny < height:
                continue
            nx = (x + dx) % width
            candidate = dist + cost
            if distances[ny][nx] is None or candidate < distances[ny][nx]:
                distances[ny][nx] = candidate
                heapq.heappush(heap, (candidate, nx, ny))

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


def _bilinear_elevation(rows, width, height, px, py):
    x0 = int(math.floor(px)) % width
    x1 = (x0 + 1) % width
    y0 = max(0, min(height - 1, int(math.floor(py))))
    y1 = max(0, min(height - 1, y0 + 1))
    fx = px - math.floor(px)
    fy = py - math.floor(py)
    top = float(rows[y0][x0] or 0.0) * (1.0 - fx) + float(rows[y0][x1] or 0.0) * fx
    bottom = float(rows[y1][x0] or 0.0) * (1.0 - fx) + float(rows[y1][x1] or 0.0) * fx
    return top * (1.0 - fy) + bottom * fy


def _terrain_metrics(rows, ocean_mask, x, y, span):
    span = max(1.0, float(span or 1.0))
    height = len(rows)
    width = len(rows[0]) if height else 0
    center = _elevation_value(rows, x, y)
    center_is_ocean = bool(ocean_mask[y][x]) if ocean_mask and width else False

    def neighbour_elevation(nx, ny):
        if ocean_mask and width:
            clamped_y = max(0, min(height - 1, ny))
            wrapped_x = nx % width
            if bool(ocean_mask[clamped_y][wrapped_x]) != center_is_ocean:
                # The land/sea boundary is a genuine elevation cliff in the
                # data (land freeboard vs. the adjacent cell's seafloor
                # depth) but it is an artefact of where the coastline mask
                # happens to fall, not real rugged relief. Counting it as an
                # ordinary neighbour turned every coastline on the planet
                # into a spuriously high "roughness" reading -- a chain-link
                # lattice tracing every shoreline -- which then bled into
                # wind_speed and maritime_land_convergence and from there
                # into precipitation, temperature and Koppen zone edges.
                # Mirroring the centre value across the boundary measures
                # real terrain texture on each side without inventing a
                # false cliff exactly on the coastline.
                return center
        return _elevation_value(rows, nx, ny)

    left = neighbour_elevation(x - 1, y)
    right = neighbour_elevation(x + 1, y)
    up = neighbour_elevation(x, y - 1)
    down = neighbour_elevation(x, y + 1)
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


def _prevailing_wind_vector(ny, map_seed, nx=0.5):
    latitude = (0.5 - float(ny)) * 2.0
    abs_lat = abs(latitude)
    seasonal_tilt = seed_range(map_seed, "wind:seasonal_tilt", -0.16, 0.16)
    # A smooth odd function of latitude instead of a hard hemisphere flag:
    # the meridional component passes through zero at the equator (the true
    # ITCZ convergence centerline) and ramps to full strength within a
    # narrow band, rather than jumping between +1 and -1 across one grid row.
    meridional_sign = math.tanh(latitude / EQUATOR_WIND_SMOOTHING_WIDTH)
    trade_x, trade_y = -0.82, -0.24 * meridional_sign
    westerly_x, westerly_y = 0.92, 0.12 * meridional_sign
    polar_x, polar_y = -0.66, 0.18 * meridional_sign
    # Blend continuously across the Hadley/Ferrel and Ferrel/Polar cell
    # boundaries instead of the wind direction completely reversing across a
    # single grid row -- real circulation cells do not end at a knife-edge
    # latitude, and a hard reversal there was producing a visible ribbon.
    trade_to_westerly = _smoothstep(
        0.28 - WIND_BAND_TRANSITION_WIDTH, 0.28 + WIND_BAND_TRANSITION_WIDTH, abs_lat
    )
    westerly_to_polar = _smoothstep(
        0.68 - WIND_BAND_TRANSITION_WIDTH, 0.68 + WIND_BAND_TRANSITION_WIDTH, abs_lat
    )
    wind_x = trade_x + (westerly_x - trade_x) * trade_to_westerly
    wind_y = trade_y + (westerly_y - trade_y) * trade_to_westerly
    wind_x += (polar_x - wind_x) * westerly_to_polar
    wind_y += (polar_y - wind_y) * westerly_to_polar
    # Planetary circulation cells are zonally organized but not perfectly
    # straight.  A low-frequency, seed-stable meander gives storm tracks and
    # moisture advection a coherent longitude component without turning the
    # climate into independent random weather cells.  The amplitude is
    # deliberately strongest in the mid-latitude storm belt and weakest near
    # the equator/poles, where the zonal circulation is less meandering.
    meander = _wave_noise(map_seed, "wind_circulation_meander", nx, ny) - 0.5
    midlatitude_weight = math.exp(-(((abs_lat - 0.56) / 0.28) ** 2))
    wind_x += meander * 0.11 * midlatitude_weight
    wind_y += meander * 0.24 * (0.35 + 0.65 * midlatitude_weight)
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


def _season_half_months(northern_hemisphere):
    """Return high-sun and low-sun half-years (January is month zero)."""
    if northern_hemisphere:
        return (3, 4, 5, 6, 7, 8), (9, 10, 11, 0, 1, 2)
    return (9, 10, 11, 0, 1, 2), (3, 4, 5, 6, 7, 8)


def _monthly_climate_normals(
    mean_temperature_k,
    temperature_range_k,
    annual_precipitation_mm,
    latitude_signed,
    continentality,
    shore_influence,
    condensation_efficiency,
    circulation_texture,
):
    """Downscale coupled annual fields into hemisphere-aware monthly normals."""
    northern = float(latitude_signed) >= 0.0
    summer_months, winter_months = _season_half_months(northern)
    peak_warm_month = 6 if northern else 0
    mean_c = float(mean_temperature_k) - 273.15
    amplitude = max(0.0, float(temperature_range_k or 0.0)) * 0.5
    monthly_temperature_c = [
        mean_c
        + amplitude * math.cos(math.tau * (month - peak_warm_month) / 12.0)
        for month in range(12)
    ]

    annual_precipitation = max(0.0, float(annual_precipitation_mm or 0.0))
    if annual_precipitation <= 1e-9:
        return monthly_temperature_c, [0.0] * 12, summer_months, winter_months

    latitude_fraction = _clamp(abs(float(latitude_signed)) / 90.0)
    continentality = _clamp(continentality)
    shore_influence = _clamp(shore_influence)
    condensation_efficiency = _clamp(condensation_efficiency)
    warmest_c = max(monthly_temperature_c)

    # Convection and continental heating favour high-sun rainfall. Maritime
    # mid-latitude storm tracks favour the low-sun half of the year.
    tropical_convection = (
        max(0.0, 1.0 - latitude_fraction / 0.38)
        * _clamp((warmest_c - 12.0) / 18.0)
        * (0.48 + 0.42 * condensation_efficiency)
    )
    continental_convection = (
        continentality
        * _clamp((warmest_c - 8.0) / 24.0)
        * (0.18 + 0.38 * condensation_efficiency)
    )
    winter_storms = (
        max(0.0, 1.0 - abs(latitude_fraction - 0.52) / 0.34)
        * shore_influence
        * (0.28 + 0.38 * condensation_efficiency)
    )
    summer_bias = _clamp(
        tropical_convection + continental_convection - winter_storms,
        -0.78,
        0.88,
    )
    seasonal_strength = _clamp(
        0.10
        + abs(summer_bias) * 0.82
        + continentality * 0.16
        + abs(float(circulation_texture) - 0.5) * 0.16,
        0.08,
        0.92,
    )
    phase_shift = (float(circulation_texture) - 0.5) * 0.9
    weights = []
    for month in range(12):
        warm_phase = math.cos(
            math.tau * (month - peak_warm_month) / 12.0 + phase_shift
        )
        signed_phase = warm_phase if summer_bias >= 0.0 else -warm_phase
        shoulder_variation = math.cos(
            math.tau * 2.0 * (month - peak_warm_month) / 12.0
            + phase_shift * 0.5
        )
        weights.append(
            max(
                0.025,
                math.exp(seasonal_strength * 1.55 * signed_phase)
                * (1.0 + shoulder_variation * 0.10 * condensation_efficiency),
            )
        )
    weight_total = max(1e-9, sum(weights))
    monthly_precipitation_mm = [
        annual_precipitation * weight / weight_total for weight in weights
    ]
    return monthly_temperature_c, monthly_precipitation_mm, summer_months, winter_months


def _koppen_geiger_class(
    monthly_temperature_c,
    monthly_precipitation_mm,
    summer_months,
    winter_months,
    *,
    is_ocean=False,
):
    """Classify twelve monthly normals using Köppen-Geiger thresholds."""
    if is_ocean:
        return "Ocean"

    temperatures = [float(value) for value in monthly_temperature_c]
    precipitation = [max(0.0, float(value)) for value in monthly_precipitation_mm]
    mean_c = sum(temperatures) / 12.0
    warmest_c = max(temperatures)
    coldest_c = min(temperatures)
    annual_precipitation = sum(precipitation)
    summer_precipitation = sum(precipitation[index] for index in summer_months)
    summer_fraction = summer_precipitation / max(1e-9, annual_precipitation)

    if summer_fraction >= 0.70:
        aridity_offset = 280.0
    elif summer_fraction <= 0.30:
        aridity_offset = 0.0
    else:
        aridity_offset = 140.0
    aridity_threshold = max(0.0, 20.0 * mean_c + aridity_offset)
    if annual_precipitation < aridity_threshold:
        desert = annual_precipitation < aridity_threshold * 0.5
        return ("BW" if desert else "BS") + ("h" if mean_c >= 18.0 else "k")

    if warmest_c < 10.0:
        return "EF" if warmest_c < 0.0 else "ET"

    if coldest_c >= 18.0:
        driest_month = min(precipitation)
        if driest_month >= 60.0:
            return "Af"
        if driest_month >= max(0.0, 100.0 - annual_precipitation / 25.0):
            return "Am"
        driest_index = min(range(12), key=lambda index: precipitation[index])
        return "As" if driest_index in summer_months else "Aw"

    months_above_10c = sum(value > 10.0 for value in temperatures)
    if warmest_c >= 22.0 and months_above_10c >= 4:
        thermal_suffix = "a"
    elif months_above_10c >= 4:
        thermal_suffix = "b"
    elif coldest_c <= -38.0:
        thermal_suffix = "d"
    else:
        thermal_suffix = "c"

    driest_summer = min(precipitation[index] for index in summer_months)
    wettest_summer = max(precipitation[index] for index in summer_months)
    driest_winter = min(precipitation[index] for index in winter_months)
    wettest_winter = max(precipitation[index] for index in winter_months)
    strongly_summer_dry = (
        driest_summer < 40.0 and driest_summer < wettest_winter / 3.0
    )
    strongly_winter_dry = driest_winter < wettest_summer / 10.0
    moisture_suffix = "s" if strongly_summer_dry else ("w" if strongly_winter_dry else "f")
    major = "C" if coldest_c > 0.0 else "D"
    return major + moisture_suffix + thermal_suffix


def _derive_koppen_display_grid(
    temperature_rows,
    seasonality_rows,
    precipitation_rows,
    shore_distance_rows,
    condensation_rows,
    elevation_rows,
    *,
    sea_level,
    map_seed,
    source_uv_bounds,
    wrap_x,
):
    """Reclassify continuous climate fields at display resolution.

    The physical solver remains on its compact planetary grid.  Interpolating
    its *classes* would turn each solver cell into a rectangular biome panel,
    so the map instead interpolates the continuous state and applies the
    Koppen thresholds at the finer display samples.
    """
    source_height = len(temperature_rows)
    source_width = len(temperature_rows[0]) if source_height else 0
    if source_width < 2 or source_height < 2:
        return [], []

    display_width = min(513, (source_width - 1) * 2 + 1)
    display_height = min(257, (source_height - 1) * 2 + 1)
    source_u0 = float(source_uv_bounds.get("min_u", 0.0) or 0.0)
    source_u1 = float(source_uv_bounds.get("max_u", 1.0) or 1.0)
    source_v0 = float(source_uv_bounds.get("min_v", 0.0) or 0.0)
    source_v1 = float(source_uv_bounds.get("max_v", 1.0) or 1.0)
    display_rows = []
    display_elevation_rows = []

    for y in range(display_height):
        local_v = y / max(1, display_height - 1)
        global_v = source_v0 + (source_v1 - source_v0) * local_v
        latitude_signed, _latitude_abs = _global_latitude_metrics(global_v)
        class_row = []
        elevation_row = []
        for x in range(display_width):
            local_u = x / max(1, display_width - 1)
            global_u = source_u0 + (source_u1 - source_u0) * local_u
            temperature = _sample_bilinear_rows(
                temperature_rows, local_u, local_v, wrap_x=wrap_x
            )
            seasonality = _sample_bilinear_rows(
                seasonality_rows, local_u, local_v, wrap_x=wrap_x
            )
            precipitation = _sample_bilinear_rows(
                precipitation_rows, local_u, local_v, wrap_x=wrap_x
            )
            continentality = _clamp(_sample_bilinear_rows(
                shore_distance_rows, local_u, local_v, wrap_x=wrap_x
            ))
            condensation = _sample_bilinear_rows(
                condensation_rows, local_u, local_v, wrap_x=wrap_x
            )
            elevation = _sample_bilinear_rows(
                elevation_rows, local_u, local_v, wrap_x=wrap_x
            )
            circulation_texture = _wave_noise(
                map_seed, "precipitation_seasonality", global_u, global_v
            )
            monthly_temperature_c, monthly_precipitation_mm, summer, winter = (
                _monthly_climate_normals(
                    temperature,
                    seasonality,
                    precipitation,
                    latitude_signed,
                    continentality,
                    1.0 - continentality,
                    condensation,
                    circulation_texture,
                )
            )
            class_row.append(_koppen_geiger_class(
                monthly_temperature_c,
                monthly_precipitation_mm,
                summer,
                winter,
                is_ocean=(sea_level is not None and elevation < sea_level),
            ))
            elevation_row.append(round(elevation, 1))
        display_rows.append(class_row)
        display_elevation_rows.append(elevation_row)
    return display_rows, display_elevation_rows


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
    latitude_abs_rows=None,
    wrap_x=True,
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
        if grid.shape != (height, width):
            return None
        # A warm-start seed that already carries non-finite values (e.g. a
        # corrupted parent climate_grid) would otherwise multiplicatively
        # contaminate the whole solve within a handful of iterations -- see
        # docs/CLAUDE_CODE_HANDOFF_2026-08-16.md's 100%-NaN regional bug.
        if not np.all(np.isfinite(grid)):
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
    try:
        inherited_latitudes = np.asarray(latitude_abs_rows, dtype=np.float64)
    except (TypeError, ValueError):
        inherited_latitudes = np.asarray([], dtype=np.float64)
    if inherited_latitudes.shape == (height,):
        latitude_abs = np.clip(inherited_latitudes, 0.0, 1.0)[:, None]
    else:
        latitude_abs = (
            np.abs(
                np.arange(height, dtype=np.float64)
                / max(1, height - 1)
                - 0.5
            )
            * 2.0
        )[:, None]
    # A moisture floor (caps how low a cell can fall each iteration, rather
    # than adding on top of already-adequate cells) weighted toward the same
    # ITCZ/storm-track bands real continental interiors (Amazon, Congo, US
    # Midwest) are sustained by, independent of direct coastal advection.
    # An earlier flat additive version of this compounded every iteration on
    # cells that were already wet and proved explosively sensitive over the
    # ~200-iteration solve; a floor only ever raises cells that would
    # otherwise fall below it, so it cannot runaway the same way.
    land_moisture_floor = (
        BASELINE_LAND_MOISTURE_FLOOR * np.exp(-((latitude_abs / 0.19) ** 2))
        + BASELINE_LAND_MOISTURE_FLOOR * STORM_TRACK_MOISTURE_FLOOR_WEIGHT
        * np.exp(-(((latitude_abs - 0.58) / 0.20) ** 2))
    )
    wind_x = winds[:, :, 0]
    wind_y = winds[:, :, 1]
    wind_speed = np.clip(winds[:, :, 2], 0.1, 18.0)
    grid_y, grid_x = np.indices((height, width))
    # Bilinear-sample the upstream source instead of rounding to the single
    # nearest cell -- nearest-neighbour rounding quantizes the continuous
    # wind angle into whole-cell steps, aliasing into a blocky texture on
    # top of whatever the wind field itself contributes.
    source_x = grid_x - wind_x
    if not wrap_x:
        source_x = np.clip(source_x, 0.0, width - 1.0)
    source_y = np.clip(grid_y - wind_y, 0.0, height - 1)
    upstream_x0 = np.floor(source_x).astype(np.int64)
    if wrap_x:
        upstream_x0 %= width
        upstream_x1 = (upstream_x0 + 1) % width
    else:
        upstream_x0 = np.clip(upstream_x0, 0, width - 1)
        upstream_x1 = np.minimum(width - 1, upstream_x0 + 1)
    upstream_y0 = np.clip(np.floor(source_y).astype(np.int64), 0, height - 1)
    upstream_y1 = np.clip(upstream_y0 + 1, 0, height - 1)
    upstream_fx = source_x - np.floor(source_x)
    upstream_fy = source_y - np.floor(source_y)
    limited_factor = 0.32 if hydrology_cycle == "limited" else 1.0
    # Condensation already removes precipitated water.  The former 6-24%
    # additional loss on every grid hop was a second, unrecorded rain-out and
    # exhausted air masses before they crossed large continents.
    transport_retention = _clamp(
        0.955 + math.log1p(max(0.0, pressure_bar)) * 0.008,
        0.95,
        0.985,
    )
    # A cold start must be able to advect moisture across at least a broad
    # hemisphere; 42 one-cell iterations left continental interiors unsolved.
    # The former 112 cap was already binding at typical planetary sample
    # resolution (e.g. 257 wide), cutting the solve off before large
    # landmasses reached a converged interior.
    if warm_started:
        # Parent-seeded regional solves already begin near the atmospheric
        # fixed point. Keep them bounded for the representative test loop;
        # a cold planetary solve still receives the larger global budget.
        iterations = max(24, min(96, width // 3 + height // 5))
    else:
        iterations = max(48, min(220, width // 2 + height // 3))
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
    if not liquid_water or (not has_surface_reservoir and not warm_started):
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
        if wrap_x:
            west = np.roll(moisture, 1, axis=1)
            east = np.roll(moisture, -1, axis=1)
        else:
            west = np.concatenate((moisture[:, :1], moisture[:, :-1]), axis=1)
            east = np.concatenate((moisture[:, 1:], moisture[:, -1:]), axis=1)
        lateral = (west + east + north + south) * 0.25
        upstream_moisture = (
            moisture[upstream_y0, upstream_x0] * (1.0 - upstream_fx) * (1.0 - upstream_fy)
            + moisture[upstream_y0, upstream_x1] * upstream_fx * (1.0 - upstream_fy)
            + moisture[upstream_y1, upstream_x0] * (1.0 - upstream_fx) * upstream_fy
            + moisture[upstream_y1, upstream_x1] * upstream_fx * upstream_fy
        )
        incoming = (
            upstream_moisture * 0.64
            + lateral * 0.28
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
        # A floor tied to available energy (potential_evaporation), not to a
        # cell's own prior evaporation, so a currently-dry cell isn't locked
        # out of ever recovering -- bare/moist ground still carries some
        # baseline evaporative flux even with zero precipitation so far.
        recycling_source = np.where(
            ~ocean,
            np.maximum(
                actual_evaporation / 4200.0 * 0.62,
                potential_evaporation / 4200.0 * BASELINE_LAND_RECYCLING_FRACTION,
            ),
            0.0,
        )
        condensed = incoming * condensation
        # Only a fraction of condensed moisture truly leaves the advecting
        # air mass; the rest keeps moving so the same parcel can produce
        # rain again further downwind instead of a coastal cell raining
        # efficiently and starving everything behind it.
        depleted = condensed * MOISTURE_DEPLETION_FRACTION
        retained = (incoming - depleted) * transport_retention
        new_moisture = np.clip(
            ocean_source + ice_source + recycling_source + retained,
            0.0,
            2.8,
        )
        new_moisture = np.where(~ocean, np.maximum(new_moisture, land_moisture_floor), new_moisture)
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
        blended_temperature = temperatures * 0.72 + target_temperature * 0.28
        # Unlike moisture/humidity/PET/precip above, this state array was
        # never sanitized -- a single non-finite cell here would otherwise
        # ride the advection step and spread across the whole grid well
        # before the iteration cap. Fall back to the last-good value per
        # cell rather than letting NaN propagate forward.
        temperatures = np.where(
            np.isfinite(blended_temperature), blended_temperature, temperatures,
        )
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
    latitude_abs_rows=None,
    wrap_x=True,
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
            latitude_abs_rows=latitude_abs_rows,
            wrap_x=wrap_x,
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
        0.955 + math.log1p(max(0.0, pressure_bar)) * 0.008,
        0.95,
        0.985,
    )
    if warm_started:
        iterations = max(24, min(96, width // 3 + height // 5))
    else:
        iterations = max(48, min(220, width // 2 + height // 3))
    converged_at = iterations
    previous_max_delta = None

    has_surface_reservoir = any(any(row) for row in ocean_mask) or any(
        any(row) for row in permanent_ice_rows
    )
    if not liquid_water or (not has_surface_reservoir and not warm_started):
        for y in range(height):
            latitude_abs = _local_latitude_fraction(y, height)
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
            latitude_abs = _local_latitude_fraction(y, height)
            # A moisture floor (caps how low a cell can fall, doesn't add on
            # top of already-adequate cells) weighted toward the same
            # ITCZ/storm-track bands real continental interiors are
            # sustained by -- see the array solver's matching floor for the
            # full rationale.
            latitude_moisture_floor = (
                BASELINE_LAND_MOISTURE_FLOOR * math.exp(-((latitude_abs / 0.19) ** 2))
                + BASELINE_LAND_MOISTURE_FLOOR * STORM_TRACK_MOISTURE_FLOOR_WEIGHT
                * math.exp(-(((latitude_abs - 0.58) / 0.20) ** 2))
            )
            for x in range(width):
                wind_x, wind_y, wind_speed = wind_vector_rows[y][x]
                # Bilinear-sample the upstream source instead of rounding to
                # the single nearest cell -- see the array solver's matching
                # sampling for the full rationale.
                source_x = x - wind_x
                source_y = max(0.0, min(height - 1, y - wind_y))
                upstream_x0 = int(math.floor(source_x)) % width
                upstream_x1 = (upstream_x0 + 1) % width
                upstream_y0 = max(0, min(height - 1, int(math.floor(source_y))))
                upstream_y1 = max(0, min(height - 1, upstream_y0 + 1))
                upstream_fx = source_x - math.floor(source_x)
                upstream_fy = source_y - math.floor(source_y)
                upstream_moisture = (
                    moisture[upstream_y0][upstream_x0] * (1.0 - upstream_fx) * (1.0 - upstream_fy)
                    + moisture[upstream_y0][upstream_x1] * upstream_fx * (1.0 - upstream_fy)
                    + moisture[upstream_y1][upstream_x0] * (1.0 - upstream_fx) * upstream_fy
                    + moisture[upstream_y1][upstream_x1] * upstream_fx * upstream_fy
                )
                lateral = (
                    moisture[y][(x - 1) % width]
                    + moisture[y][(x + 1) % width]
                    + moisture[max(0, y - 1)][x]
                    + moisture[min(height - 1, y + 1)][x]
                ) * 0.25
                incoming = (
                    upstream_moisture * 0.64
                    + lateral * 0.28
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
                # A floor tied to available energy, not to a cell's own prior
                # evaporation, so a currently-dry cell isn't locked out of
                # ever recovering.
                recycling_source = (
                    max(
                        actual_evaporation[y][x] / 4200.0 * 0.62,
                        pet / 4200.0 * BASELINE_LAND_RECYCLING_FRACTION,
                    )
                    if not ocean_mask[y][x]
                    else 0.0
                )
                condensation = _clamp(condensation_rows[y][x], 0.01, 0.62)
                condensed = incoming * condensation
                # Only a fraction of condensed moisture truly leaves the
                # advecting air mass; see the array solver's matching split.
                depleted = condensed * MOISTURE_DEPLETION_FRACTION
                retained = (incoming - depleted) * transport_retention
                next_moisture = _clamp(
                    ocean_source + ice_source + recycling_source + retained,
                    0.0,
                    2.8,
                )
                if not ocean_mask[y][x]:
                    next_moisture = max(next_moisture, latitude_moisture_floor)
                new_moisture[y][x] = next_moisture
                precipitation_target[y][x] = min(5200.0, condensed * 5900.0)
                max_delta = max(max_delta, abs(next_moisture - moisture[y][x]))

        for y in range(height):
            latitude_abs = _local_latitude_fraction(y, height)
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


def _nearest_ocean_upwelling_rows(ocean_mask, upwelling_rows):
    """Diffuse coastal upwelling intensity onto adjacent land, nearest-source.

    Cold upwelling water caps convection with a marine temperature inversion,
    producing famously dry coastlines (Atacama, Namib) despite fog/high
    humidity. This is independent of -- and in addition to -- the indirect
    cooling upwelling already applies to sea-surface temperature.
    """
    height = len(ocean_mask)
    width = len(ocean_mask[0]) if height else 0
    result = [[None for _x in range(width)] for _y in range(height)]
    distance = [[None for _x in range(width)] for _y in range(height)]
    queue = deque()
    for y in range(height):
        for x in range(width):
            if ocean_mask[y][x]:
                value = (
                    float(upwelling_rows[y][x])
                    if upwelling_rows and y < len(upwelling_rows) and x < len(upwelling_rows[y])
                    and upwelling_rows[y][x] is not None
                    else 0.0
                )
                result[y][x] = value
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


def _row_mean_ocean_temperature_k(ocean_mask, sst_rows):
    """Per-row (zonal) mean sea-surface temperature, for anomaly comparison.

    A coastline sitting on a warm ocean current (Gulf-Stream-analog western
    boundary current) reads warmer than the surrounding latitude band's
    typical SST -- that anomaly, not the absolute temperature, is what
    should carry extra moisture onshore.
    """
    height = len(ocean_mask)
    width = len(ocean_mask[0]) if height else 0
    means = [None] * height
    for y in range(height):
        values = [
            float(sst_rows[y][x])
            for x in range(min(width, len(sst_rows[y]) if y < len(sst_rows) else 0))
            if ocean_mask[y][x] and sst_rows[y][x] is not None
        ]
        means[y] = sum(values) / len(values) if values else None
    return means


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
    steps_since_peak = 0
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
        # Bilinear-sample the elevation instead of rounding to the nearest
        # cell. The wind vector is rarely axis-aligned, so nearest-neighbour
        # rounding along this ray quantized the walk into a Bresenham-style
        # staircase -- a diagonal dashed/hatched texture baked straight into
        # windward_uplift/barrier_shadow, and from there into
        # condensation_efficiency, precipitation, temperature (via the
        # moisture/cloud feedback) and Koppen zone edges. The ocean-mask
        # break test above stays nearest-neighbour since a boolean land/sea
        # lookup has no meaningful sub-cell value to interpolate.
        elevation = _bilinear_elevation(rows, width, height, px, py)
        # Walking upwind, a drop means air approaching the target had to rise.
        cumulative_ascent += max(0.0, previous - elevation)
        if elevation > maximum_barrier:
            maximum_barrier = elevation
            steps_since_peak = _step
        previous = elevation
        land_steps += 1
    # A rain shadow is strongest immediately behind the ridge that casts it
    # and recovers with distance as air re-entrains moisture; without decay,
    # any barrier found anywhere in the scan window shadows the target at
    # full strength, flattening a broad swath behind every coastal range
    # into desert regardless of how far past the peak the target actually is.
    recovery = math.exp(-steps_since_peak / RAIN_SHADOW_RECOVERY_LENGTH_CELLS)
    return {
        "windward_uplift": _clamp(cumulative_ascent / max(1.0, span * 0.42)),
        "barrier_shadow": _clamp((maximum_barrier - current) / max(1.0, span * 0.32)) * recovery,
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


def _climate_field_diagnostics(
    rows,
    ocean_mask,
    shore_distances,
    temperature_rows,
    precipitation_rows,
    wind_vector_rows,
):
    """Summarize causal climate structure without replacing the climate grid.

    These metrics are intended for representative-world comparisons. They
    distinguish a useful longitudinal circulation signal from a purely zonal
    latitude field and make the terrain/climate coupling visible in reports.
    """
    height = len(rows)
    width = min((len(row) for row in rows if isinstance(row, list)), default=0)
    land_samples = []
    all_precipitation = []
    coastal_precipitation = []
    interior_precipitation = []
    wind_meander = []
    for y in range(height):
        row_values = rows[y][:width]
        precipitation_row = precipitation_rows[y][:width]
        ocean_row = ocean_mask[y][:width]
        shore_row = shore_distances[y][:width] if y < len(shore_distances) else []
        all_precipitation.extend(float(value or 0.0) for value in precipitation_row)
        for x, elevation in enumerate(row_values):
            precipitation = float(precipitation_row[x] or 0.0)
            if ocean_row[x]:
                continue
            land_samples.append((float(elevation or 0.0), precipitation))
            shore_distance = float(shore_row[x] or 0.0) if x < len(shore_row) else 0.0
            if shore_distance >= 0.5:
                coastal_precipitation.append(precipitation)
            elif shore_distance <= 0.25:
                interior_precipitation.append(precipitation)
        if y < len(wind_vector_rows):
            wind_row = wind_vector_rows[y][:width]
            if wind_row:
                wind_values = [
                    float(item[1])
                    for item in wind_row
                    if isinstance(item, list) and len(item) >= 2
                ]
                if wind_values:
                    wind_meander.append(max(wind_values) - min(wind_values))

    if not all_precipitation:
        return {
            "status": "not_applicable",
            "causal_inputs": ["heightmap", "wind_field", "ocean_mask"],
        }

    zonal_residual = 0.0
    total_residual = 0.0
    for y in range(height):
        values = [float(value or 0.0) for value in precipitation_rows[y][:width]]
        if not values:
            continue
        mean = sum(values) / len(values)
        zonal_residual += sum(abs(value - mean) for value in values)
        total_residual += sum(abs(value) for value in values)

    elevation_sorted = sorted(value[0] for value in land_samples)
    high_threshold = elevation_sorted[int(0.75 * (len(elevation_sorted) - 1))] if elevation_sorted else 0.0
    low_threshold = elevation_sorted[int(0.25 * (len(elevation_sorted) - 1))] if elevation_sorted else 0.0
    high_precipitation = [p for elevation, p in land_samples if elevation >= high_threshold]
    low_precipitation = [p for elevation, p in land_samples if elevation <= low_threshold]
    high_mean = sum(high_precipitation) / max(1, len(high_precipitation))
    low_mean = sum(low_precipitation) / max(1, len(low_precipitation))
    return {
        "status": "climate_structure_diagnosed",
        "causal_inputs": [
            "heightmap.sample_grid.rows",
            "heightmap.surface_masks.ocean_rows",
            "prevailing_wind_rows",
            "ocean_circulation_model",
        ],
        "non_zonal_precipitation_index": round(
            zonal_residual / max(1e-9, total_residual), 4
        ),
        "high_vs_low_relief_precipitation_ratio": round(
            high_mean / max(1e-9, low_mean), 4
        ),
        "coastal_precipitation_mm": round(
            sum(coastal_precipitation) / max(1, len(coastal_precipitation)), 2
        ),
        "interior_precipitation_mm": round(
            sum(interior_precipitation) / max(1, len(interior_precipitation)), 2
        ),
        "wind_longitude_meander_index": round(
            sum(wind_meander) / max(1, len(wind_meander)), 4
        ),
        "finite_fields": all(
            math.isfinite(float(value or 0.0))
            for field in (temperature_rows, precipitation_rows)
            for row in field
            for value in row
        ),
    }


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
            "koppen_classes": [],
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
    upwelling_rows = ocean_circulation.get("upwelling_rows") or [[0.0 for _x in range(width)] for _y in range(height)]
    nearest_ocean_upwelling = _nearest_ocean_upwelling_rows(ocean_mask, upwelling_rows)
    row_mean_ocean_temperature_k = _row_mean_ocean_temperature_k(ocean_mask, sst_rows)
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
    source_uv = heightmap.get("source_uv_bounds") if isinstance(heightmap.get("source_uv_bounds"), dict) else {}
    source_u0 = float(source_uv.get("min_u", 0.0) or 0.0)
    source_u1 = float(source_uv.get("max_u", 1.0) or 1.0)
    source_v0 = float(source_uv.get("min_v", 0.0) or 0.0)
    source_v1 = float(source_uv.get("max_v", 1.0) or 1.0)
    parent_climate_grid = parent_climate_model.get("climate_grid") if isinstance(parent_climate_model, dict) else {}
    has_parent_climate = bool(
        isinstance(parent_climate_grid, dict) and parent_climate_grid
    )
    parent_source_uv = parent_climate_grid.get("source_uv_bounds") if isinstance(parent_climate_grid, dict) else {}
    inherited_width_cache = {}

    def sample_parent_rows(parent_rows, global_u, global_v):
        """Sample parent climate rows without rescanning their shape per cell."""
        if not isinstance(parent_rows, list) or not parent_rows:
            return None
        cache_key = id(parent_rows)
        width_hint = inherited_width_cache.get(cache_key)
        if width_hint is None:
            valid_rows = [row for row in parent_rows if isinstance(row, list)]
            width_hint = min((len(row) for row in valid_rows), default=0)
            inherited_width_cache[cache_key] = width_hint
        return _sample_inherited_rows(
            parent_rows,
            global_u,
            global_v,
            parent_source_uv,
            width_hint=width_hint,
        )

    detail_level = int(heightmap.get("map_detail_level", 0) or 0)
    inheritance_weights = _climate_inheritance_weights(detail_level)

    for y, row in enumerate(rows):
        local_ny = y / max(1, height - 1)
        ny = source_v0 + (source_v1 - source_v0) * local_ny
        latitude_signed, latitude_abs = _global_latitude_metrics(ny)
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
            shore = _clamp(shore)
            terrain = _terrain_metrics(rows, ocean_mask, x, y, span)
            wind_x, wind_y = _prevailing_wind_vector(ny, map_seed, nx=nx)
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
            # Oceanic islands and coastal land force moist marine air to
            # converge through surface friction and, where relief exists,
            # rise over the terrain.  Previously the solver only represented
            # broad latitude belts and steep windward slopes, so most marine
            # moisture rained back into the ocean before small landmasses
            # could intercept it.
            maritime_land_convergence = (
                0.0
                if is_ocean
                else shore ** 1.35 * (0.026 + terrain["roughness"] * 0.060)
            )
            # ITCZ convection and midlatitude storm tracks are independent,
            # dominant drivers of precipitation over FLAT land -- real
            # tropical rainforest belts and midlatitude wet climates do not
            # require mountains. The previous weights (0.055 / 0.032) left
            # convective/frontal lift a minor addition to orographic lift
            # (0.16), so flat equatorial land topped out far below realistic
            # tropical rainfall; raised to parity with the orographic term.
            # Real orographic rainfall peaks in a mid-elevation cloud-forest/
            # fog-capture band and falls off both below it (less lift) and
            # above it (past the cloud deck, drier), rather than increasing
            # monotonically with windward lift alone.
            cloud_forest_band = math.exp(
                -(((elevation_norm - CLOUD_FOREST_ELEVATION_NORM) / CLOUD_FOREST_BAND_WIDTH) ** 2)
            )
            orographic_cloud_bonus = (
                cloud_forest_band * _clamp(windward) * CLOUD_FOREST_BONUS_STRENGTH
                if not is_ocean
                else 0.0
            )
            condensation_efficiency = _clamp(
                0.010
                + convective_lift * 0.17
                + storm_lift * 0.10
                + windward * 0.16
                + orographic_cloud_bonus
                + maritime_land_convergence
                - rain_shadow * 0.070
                + circulation_texture * 0.012,
                0.006,
                0.46,
            )
            if not is_ocean:
                # A cold upwelling coast caps convection with a marine
                # temperature inversion (Atacama/Namib-style fog deserts):
                # dry despite proximity to the ocean, not just because it is
                # cooler. This is independent of the SST-mediated cooling
                # already applied to nearest_ocean_temperatures above.
                upwelling_signal = float(nearest_ocean_upwelling[y][x] or 0.0)
                if upwelling_signal > 0.0:
                    upwelling_suppression = _clamp(upwelling_signal * 0.85)
                    condensation_efficiency = max(
                        0.006,
                        condensation_efficiency * (1.0 - upwelling_suppression * (shore ** 1.2)),
                    )
                # Warm ocean currents making landfall (Gulf-Stream-analog
                # western boundary currents) carry moisture-laden air onshore
                # -- the warm-anomaly counterpart to the cold upwelling-
                # desert suppression above. Anomaly is measured against this
                # row's own zonal mean SST, not an absolute temperature, so a
                # world that's simply warm overall doesn't trigger it
                # everywhere.
                row_mean_sst = row_mean_ocean_temperature_k[y] if y < len(row_mean_ocean_temperature_k) else None
                nearest_sst = nearest_ocean_temperatures[y][x]
                if row_mean_sst is not None and nearest_sst is not None:
                    warm_anomaly = _clamp((float(nearest_sst) - row_mean_sst) / WARM_CURRENT_ANOMALY_SCALE_K)
                    if warm_anomaly > 0.0:
                        condensation_efficiency = min(
                            0.46,
                            condensation_efficiency * (1.0 + warm_anomaly * (shore ** 1.2) * WARM_CURRENT_MOISTURE_BONUS),
                        )
            wind_vector_row.append([
                round(float(wind_x), 4),
                round(float(wind_y), 4),
                round(float(wind_speed), 3),
            ])
            condensation_row.append(round(condensation_efficiency, 5))
            permanent_ice_row.append(permanent_ice)
            temperature = surface_temp_k + 12.0 - latitude_abs * 48.0 - max(0.0, elevation) * 0.0062
            if permanent_ice and not is_ocean:
                # Ice-albedo feedback: snow/ice reflects far more shortwave
                # than bare ground or open water, reinforcing local cold
                # once a cell freezes. world_gen_sim.py's bounded ice-mask
                # refresh pass (see _save_water_cycle_model) lets this
                # propagate back into whether a cell counts as ice at all.
                temperature -= 6.0
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
            inherited_temperature = sample_parent_rows(
                parent_climate_grid.get("temperature_rows_k"), nx, ny,
            ) if isinstance(parent_climate_grid, dict) else None
            inherited_elevation = sample_parent_rows(
                parent_climate_grid.get("elevation_rows"), nx, ny,
            ) if isinstance(parent_climate_grid, dict) else None
            if inherited_temperature is not None:
                inherited_local_temperature = inherited_temperature
                if inherited_elevation is not None:
                    inherited_local_temperature -= (elevation - inherited_elevation) * 0.0062
                parent_weight = _edge_locked_parent_weight(
                    inheritance_weights["temperature"], local_nx, local_ny
                )
                temperature = inherited_local_temperature * parent_weight + temperature * (1.0 - parent_weight)
            inherited_seasonality = sample_parent_rows(
                parent_climate_grid.get("temperature_seasonality_rows_k"), nx, ny,
            ) if isinstance(parent_climate_grid, dict) else None
            if inherited_seasonality is not None:
                parent_weight = _edge_locked_parent_weight(
                    inheritance_weights["seasonality"], local_nx, local_ny
                )
                seasonality = inherited_seasonality * parent_weight + seasonality * (1.0 - parent_weight)
            # Moisture and land-water fields are intentionally not classified
            # in this pass. They are solved iteratively after every cell's
            # energy, wind, topography, and reservoir state is available.
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

    if not has_parent_climate:
        # Condensation is a transported atmospheric field, not a set of
        # independent longitude columns.  Relax it before the moisture solve
        # so column-scale forcing cannot be amplified into rainfall lanes.
        condensation_rows = _barrier_aware_relax_field(
            condensation_rows,
            rows,
            strength=0.34,
            passes=3,
            zonal_bias=2.4,
        )

    solver_initial_climate = (
        (previous_regional_model.get("climate_grid") or {})
        if isinstance(previous_regional_model, dict)
        else None
    )
    solver_seed_source = (
        "previous_regional_climate"
        if isinstance(solver_initial_climate, dict) and solver_initial_climate
        else "cold_start"
    )
    if (
        not solver_initial_climate
        and has_parent_climate
    ):
        # A small inland child has no local ocean cell, but it still sits
        # inside the parent atmosphere. Seed the local coupled solve from the
        # parent climate at the child's physical coordinates; otherwise the
        # no-reservoir guard returns zero precipitation and the later parent
        # blend collapses the whole region to one nearly uniform value.
        inherited_solver_climate = {}
        inherited_keys = (
            "temperature_rows_k",
            "annual_precipitation_rows_mm",
            "annual_evapotranspiration_rows_mm",
            "annual_potential_evaporation_rows_mm",
            "relative_humidity_rows",
        )
        for key in inherited_keys:
            parent_rows = parent_climate_grid.get(key)
            if not isinstance(parent_rows, list) or not parent_rows:
                continue
            local_rows = []
            for y in range(height):
                local_ny = y / max(1, height - 1)
                global_v = source_v0 + (source_v1 - source_v0) * local_ny
                local_row = []
                for x in range(width):
                    local_nx = x / max(1, width - 1)
                    global_u = source_u0 + (source_u1 - source_u0) * local_nx
                    value = sample_parent_rows(parent_rows, global_u, global_v)
                    local_row.append(0.0 if value is None else value)
                local_rows.append(local_row)
            inherited_solver_climate[key] = local_rows
        if all(key in inherited_solver_climate for key in inherited_keys):
            solver_initial_climate = inherited_solver_climate
            solver_seed_source = "parent_climate_coordinate_seed"

    latitude_abs_rows = [
        _global_latitude_metrics(
            source_v0 + (source_v1 - source_v0) * y / max(1, height - 1)
        )[1]
        for y in range(height)
    ]
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
        initial_climate=solver_initial_climate,
        latitude_abs_rows=latitude_abs_rows,
        wrap_x=bool(heightmap.get("wrap_x", True)),
    )
    solved_temperature_rows = coupled_climate.get("temperature_rows_k")
    if solved_temperature_rows and not _rows_all_finite(solved_temperature_rows):
        # Last line of defense: a corrupted solve should not overwrite the
        # pre-solve estimate with NaN just because the returned list is
        # non-empty (plain `or` only rejects falsy/empty results).
        logging.getLogger(__name__).warning(
            "Coupled climate solve produced non-finite temperatures; "
            "keeping the pre-solve estimate instead."
        )
        solved_temperature_rows = None
    temperature_rows = solved_temperature_rows or temperature_rows
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

    if not has_parent_climate:
        # The coupled solver works on a deliberately reduced planetary grid.
        # A light conservative relaxation makes its annual scalar outputs
        # continuous before categorical Köppen classification. This removes
        # single-column stripes and rectangular solver cells while retaining
        # broad circulation, coastal gradients and orographic rain shadows.
        temperature_rows = _relax_continuous_planetary_field(temperature_rows, 0.14)
        precipitation_rows = _barrier_aware_relax_field(
            precipitation_rows,
            rows,
            strength=0.38,
            passes=5,
            preserve_total=True,
            zonal_bias=2.8,
        )
        potential_evaporation_rows = _relax_continuous_planetary_field(
            potential_evaporation_rows, 0.12,
        )
        relative_humidity_rows = _relax_continuous_planetary_field(
            relative_humidity_rows, 0.16,
        )

    # Rebuild the land water balance and classifications from the converged
    # annual climate. The first pass only established energy, terrain, and
    # atmospheric-transport fields.
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
    koppen_counts = {code: 0 for code in KOPPEN_CLASSES}

    for y, elevation_row in enumerate(rows):
        local_ny = y / max(1, height - 1)
        ny = source_v0 + (source_v1 - source_v0) * local_ny
        latitude_signed, latitude_abs = _global_latitude_metrics(ny)
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
            terrain_metrics = _terrain_metrics(rows, ocean_mask, x, y, span)
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
                inherited_temperature = sample_parent_rows(
                    parent_climate_grid.get("temperature_rows_k"), nx, ny,
                )
                inherited_elevation = sample_parent_rows(
                    parent_climate_grid.get("elevation_rows"), nx, ny,
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

            if isinstance(parent_climate_grid, dict):
                parent_weight = _edge_locked_parent_weight(
                    inheritance_weights["precipitation"], local_nx, local_ny
                )
                inherited_precipitation = sample_parent_rows(
                    parent_climate_grid.get("annual_precipitation_rows_mm"), nx, ny,
                )
                if inherited_precipitation is not None and parent_weight > 0.0:
                    precipitation = (
                        float(inherited_precipitation) * parent_weight
                        + precipitation * (1.0 - parent_weight)
                    )
                    precipitation_rows[y][x] = precipitation
                    actual_evapotranspiration = (
                        0.0
                        if is_ocean
                        else _budyko_evapotranspiration_mm(
                            precipitation,
                            potential_evaporation,
                        )
                    )

            (
                monthly_temperature_c,
                monthly_precipitation_mm,
                summer_months,
                winter_months,
            ) = _monthly_climate_normals(
                mean_temperature,
                seasonality,
                precipitation,
                latitude_signed,
                continentality,
                shore,
                condensation_rows[y][x],
                circulation_texture,
            )
            annual_monthly_total = max(1e-9, sum(monthly_precipitation_mm))
            summer_fraction = sum(
                monthly_precipitation_mm[index] for index in summer_months
            ) / annual_monthly_total
            driest_month = min(monthly_precipitation_mm)
            wettest_month = max(monthly_precipitation_mm)
            koppen_code = _koppen_geiger_class(
                monthly_temperature_c,
                monthly_precipitation_mm,
                summer_months,
                winter_months,
                is_ocean=is_ocean,
            )

            seasonal_min_temperature = min(monthly_temperature_c) + 273.15
            seasonal_max_temperature = max(monthly_temperature_c) + 273.15
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
            koppen_counts[koppen_code] = koppen_counts.get(koppen_code, 0) + 1
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
            "color": list(spec["color"]),
            "fraction": round(count / total_cells, 3),
        })

    koppen_display_rows = []
    koppen_display_elevation_rows = []
    if not has_parent_climate and detail_level == 0:
        (
            koppen_display_rows,
            koppen_display_elevation_rows,
        ) = _derive_koppen_display_grid(
            temperature_rows,
            seasonality_rows,
            precipitation_rows,
            shore_distances,
            condensation_rows,
            rows,
            sea_level=sea_level,
            map_seed=map_seed,
            source_uv_bounds={
                "min_u": source_u0,
                "max_u": source_u1,
                "min_v": source_v0,
                "max_v": source_v1,
            },
            wrap_x=bool(heightmap.get("wrap_x", True)),
        )

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
    climate_field_diagnostics = _climate_field_diagnostics(
        rows,
        ocean_mask,
        shore_distances,
        temperature_rows,
        precipitation_rows,
        wind_vector_rows,
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
                "longitude_meandering_circulation",
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
        "climate_field_diagnostics": climate_field_diagnostics,
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
            "koppen_derivation": {
                "method": "twelve_month_temperature_and_precipitation_normals",
                "classification": "Koppen-Geiger",
                "temperature_phase": "hemisphere_aware",
                "precipitation_seasons": "high_sun_and_low_sun_half_years",
                "aridity_threshold": "20T_plus_seasonal_precipitation_offset",
            },
            "rows": koppen_rows,
            "koppen_rows": koppen_rows,
            "koppen_display_rows": koppen_display_rows,
            "koppen_display_elevation_rows": koppen_display_elevation_rows,
            "koppen_display_contract": {
                "method": "bilinear_continuous_fields_then_reclassify",
                "width": (
                    len(koppen_display_rows[0]) if koppen_display_rows else 0
                ),
                "height": len(koppen_display_rows),
                "purpose": "remove categorical solver-cell panels",
            },
            "elevation_rows": rows,
            "shore_distance_rows": shore_distances,
            "temperature_rows_k": temperature_rows,
            "annual_precipitation_rows_mm": precipitation_rows,
            "relative_humidity_rows": relative_humidity_rows,
            "prevailing_wind_rows": wind_vector_rows,
            "circulation_field_contract": {
                "method": "smooth_latitude_cells_with_seeded_longitude_meander",
                "meander_source": "wind_circulation_meander_seed_wave",
                "meander_scope": "midlatitude_storm_belts_and_meridional_transport",
                "orographic_feedback_source": "heightmap.sample_grid.rows",
            },
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
                "solver_seed_source": solver_seed_source,
                "solver_uses_global_latitude": True,
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
            "dominant_koppen_class": koppen_classes[0]["id"] if koppen_classes else None,
            "drainage_enabled": drainage_enabled,
            "mean_land_precipitation_mm": round(sum(precipitation_rows[y][x] for y in range(height) for x in range(width) if not ocean_mask[y][x]) / max(1, sum(1 for y in range(height) for x in range(width) if not ocean_mask[y][x])), 1),
            "ocean_basin_count": int((ocean_circulation.get("summary") or {}).get("ocean_basin_count", 0) or 0),
            "major_gyre_count": int((ocean_circulation.get("summary") or {}).get("major_gyre_count", 0) or 0),
            "mean_land_runoff_mm": round(sum(runoff_rows[y][x] for y in range(height) for x in range(width) if not ocean_mask[y][x]) / max(1, sum(1 for y in range(height) for x in range(width) if not ocean_mask[y][x])), 1),
            "mean_land_infiltration_mm": round(sum(infiltration_rows[y][x] for y in range(height) for x in range(width) if not ocean_mask[y][x]) / max(1, sum(1 for y in range(height) for x in range(width) if not ocean_mask[y][x])), 1),
            "mean_land_evapotranspiration_mm": round(sum(evapotranspiration_rows[y][x] for y in range(height) for x in range(width) if not ocean_mask[y][x]) / max(1, sum(1 for y in range(height) for x in range(width) if not ocean_mask[y][x])), 1),
        },
    }
