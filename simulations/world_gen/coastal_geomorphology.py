"""Deterministic reduced-physics coastal geomorphology.

The planetary product is a compact shoreline graph with independent causal
classifications.  It deliberately does not claim spectral wave modelling or
harmonic tidal solutions; every reduced-physics estimate carries confidence
and a rule trace.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from collections import Counter, defaultdict, deque

from simulations.world_gen.heightmap import (
    heightmap_derivatives_are_current,
    refresh_heightmap_derivatives,
)
from simulations.world_gen.map_seed import seed_range


COASTAL_MODEL_VERSION = "coastal-geomorphology-v7"
MIN_COASTAL_TERRAIN_FEATURE_WIDTH_M = 0.50
G = 6.67430e-11
EARTH_SOLAR_TIDE_ACCELERATION = 5.04e-7

ASSEMBLAGE_COLORS = {
    "rocky_cliff": [126, 112, 106],
    "headland_bay": [156, 130, 104],
    "clastic_beach": [230, 204, 126],
    "barrier_lagoon": [238, 184, 94],
    "deltaic": [118, 170, 104],
    "estuarine_drowned_valley": [88, 156, 164],
    "tidal_flat_accommodation": [154, 164, 112],
    "glacial_fjord_fjard_skerry": [142, 196, 214],
    "volcanic": [108, 82, 76],
    "carbonate_karst": [220, 218, 194],
    "permafrost": [178, 210, 218],
    "emergent_marine_terrace": [186, 146, 112],
}


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, float(value)))


def _sample(rows, u, v, default=0.0):
    if not rows or not rows[0]:
        return default
    height = len(rows)
    width = min(len(row) for row in rows)
    unique_width = width - 1 if width > 1 and rows[0][0] == rows[0][-1] else width
    x = (float(u) % 1.0) * unique_width
    y = _clamp(v) * max(1, height - 1)
    x0 = int(math.floor(x)) % unique_width
    x1 = (x0 + 1) % unique_width
    y0 = max(0, min(height - 1, int(math.floor(y))))
    y1 = min(height - 1, y0 + 1)
    tx, ty = x - math.floor(x), y - y0
    top = float(rows[y0][x0] or 0.0) * (1.0 - tx) + float(rows[y0][x1] or 0.0) * tx
    bottom = float(rows[y1][x0] or 0.0) * (1.0 - tx) + float(rows[y1][x1] or 0.0) * tx
    return top * (1.0 - ty) + bottom * ty


def _grid_dimensions(heightmap):
    grid = heightmap.get("sample_grid") if isinstance(heightmap, dict) else {}
    rows = grid.get("rows") if isinstance(grid, dict) else []
    if not rows or not rows[0]:
        return rows, 0, 0, False
    width = min(len(row) for row in rows)
    wrap_x = bool(grid.get("wrap_x", heightmap.get("wrap_x", True)))
    unique_width = width - 1 if wrap_x and width > 1 else width
    return rows, unique_width, len(rows), wrap_x


def _planetary_uv(heightmap, local_uv):
    """Map regional UV coordinates back into the root planetary projection."""
    source = heightmap.get("source_uv_bounds") if isinstance(heightmap, dict) else None
    if not isinstance(source, dict):
        return [float(local_uv[0]) % 1.0, _clamp(local_uv[1])]
    minimum_u = float(source.get("min_u", 0.0) or 0.0)
    maximum_u = float(source.get("max_u", 1.0) or 1.0)
    minimum_v = float(source.get("min_v", 0.0) or 0.0)
    maximum_v = float(source.get("max_v", 1.0) or 1.0)
    return [
        (minimum_u + (maximum_u - minimum_u) * float(local_uv[0])) % 1.0,
        _clamp(minimum_v + (maximum_v - minimum_v) * float(local_uv[1])),
    ]


def _interpolate_edge(x, y, side, corners, sea_level, width, height):
    # Corners are top-left, top-right, bottom-right, bottom-left.
    endpoints = {
        0: ((x, y, corners[0]), (x + 1, y, corners[1])),
        1: ((x + 1, y, corners[1]), (x + 1, y + 1, corners[2])),
        2: ((x + 1, y + 1, corners[2]), (x, y + 1, corners[3])),
        3: ((x, y + 1, corners[3]), (x, y, corners[0])),
    }
    a, b = endpoints[side]
    denominator = float(b[2]) - float(a[2])
    t = 0.5 if abs(denominator) < 1e-12 else _clamp((float(sea_level) - float(a[2])) / denominator)
    gx = float(a[0]) + (float(b[0]) - float(a[0])) * t
    gy = float(a[1]) + (float(b[1]) - float(a[1])) * t
    return [round((gx / max(1, width)) % 1.0, 7), round(gy / max(1, height - 1), 7)]


def _marching_edges(heightmap):
    rows, width, height, wrap_x = _grid_dimensions(heightmap)
    sea_level = heightmap.get("sea_level_m") if isinstance(heightmap, dict) else None
    if sea_level is None or width < 2 or height < 2:
        return []
    sea_level = float(sea_level)
    edges = []
    x_cells = width if wrap_x else width - 1
    for y in range(height - 1):
        for x in range(x_cells):
            x1 = (x + 1) % width
            corners = [rows[y][x], rows[y][x1], rows[y + 1][x1], rows[y + 1][x]]
            state = sum((1 << index) for index, value in enumerate(corners) if float(value) >= sea_level)
            if state in {0, 15}:
                continue
            crossed = []
            pairs = ((0, 1), (1, 2), (2, 3), (3, 0))
            for side, (a, b) in enumerate(pairs):
                if (float(corners[a]) >= sea_level) != (float(corners[b]) >= sea_level):
                    crossed.append(side)
            if len(crossed) == 2:
                edges.append((_interpolate_edge(x, y, crossed[0], corners, sea_level, width, height), _interpolate_edge(x, y, crossed[1], corners, sea_level, width, height)))
            elif len(crossed) == 4:
                center_land = sum(float(value) for value in corners) * 0.25 >= sea_level
                pairing = ((0, 1), (2, 3)) if (state == 5) == center_land else ((0, 3), (1, 2))
                for side_a, side_b in pairing:
                    edges.append((_interpolate_edge(x, y, side_a, corners, sea_level, width, height), _interpolate_edge(x, y, side_b, corners, sea_level, width, height)))
    return edges


def _point_key(point, wrap_x=True):
    raw_u = float(point[0])
    u = (0.0 if abs(raw_u - 1.0) < 1e-6 else raw_u % 1.0) if wrap_x else _clamp(raw_u)
    return round(u, 6), round(float(point[1]), 6)


def _ordered_chains(edges, wrap_x=True):
    adjacency = defaultdict(list)
    coordinates = {}
    edge_keys = []
    for edge_index, (a, b) in enumerate(edges):
        ka, kb = _point_key(a, wrap_x), _point_key(b, wrap_x)
        edge_keys.append((ka, kb))
        coordinates[ka], coordinates[kb] = [ka[0], ka[1]], [kb[0], kb[1]]
        adjacency[ka].append((edge_index, kb))
        adjacency[kb].append((edge_index, ka))
    unused = set(range(len(edges)))
    chains = []
    starts = sorted(adjacency, key=lambda key: (len(adjacency[key]) != 1, key[1], key[0]))
    start_cursor = 0
    while unused:
        start = None
        while start_cursor < len(starts):
            candidate = starts[start_cursor]
            start_cursor += 1
            if any(index in unused for index, _other in adjacency[candidate]):
                start = candidate
                break
        if start is None:
            edge_index = min(unused)
            start = edge_keys[edge_index][0]
        chain = [coordinates[start]]
        current = start
        previous = None
        while True:
            candidates = sorted(
                ((index, other) for index, other in adjacency[current] if index in unused and other != previous),
                key=lambda item: item[1],
            )
            if not candidates:
                candidates = [(index, other) for index, other in adjacency[current] if index in unused]
            if not candidates:
                break
            edge_index, other = candidates[0]
            unused.remove(edge_index)
            chain.append(coordinates[other])
            previous, current = current, other
            if current == start:
                break
        if len(chain) >= 2:
            chains.append(chain)
    chains.sort(key=lambda chain: (_point_key(min(chain, key=lambda p: (p[1], p[0])), wrap_x), -len(chain)))
    return chains


def _spherical_length(points, radius_m):
    total = 0.0
    radius_m = max(1.0, float(radius_m or 6_371_000.0))
    for a, b in zip(points, points[1:]):
        lon_a, lon_b = (float(a[0]) * math.tau, float(b[0]) * math.tau)
        lat_a, lat_b = ((0.5 - float(a[1])) * math.pi, (0.5 - float(b[1])) * math.pi)
        delta_lon = ((lon_b - lon_a + math.pi) % math.tau) - math.pi
        h = math.sin((lat_b - lat_a) * 0.5) ** 2 + math.cos(lat_a) * math.cos(lat_b) * math.sin(delta_lon * 0.5) ** 2
        total += 2.0 * radius_m * math.asin(min(1.0, math.sqrt(max(0.0, h))))
    return total


def _polyline_length_m(heightmap, points, radius_m):
    """Measure shoreline geometry in the coordinate system of its map."""
    if str(heightmap.get("coverage") or "") == "regional_patch" or str(heightmap.get("projection") or "").startswith("local_"):
        width_m = float(heightmap.get("region_width_m") or heightmap.get("circumference_m") or 0.0)
        height_m = float(heightmap.get("region_height_m") or width_m or 0.0)
        total = 0.0
        for a, b in zip(points, points[1:]):
            total += math.hypot(
                (float(b[0]) - float(a[0])) * width_m,
                (float(b[1]) - float(a[1])) * height_m,
            )
        return total
    return _spherical_length(points, radius_m)


def _split_chain(points, maximum_points=20, curvature_threshold_rad=0.85):
    if len(points) < 2:
        return []
    chunks, start = [], 0
    previous_heading = None
    for index in range(1, len(points)):
        a, b = points[index - 1], points[index]
        du = ((float(b[0]) - float(a[0]) + 0.5) % 1.0) - 0.5
        heading = math.atan2(float(b[1]) - float(a[1]), du)
        turn = 0.0 if previous_heading is None else abs(((heading - previous_heading + math.pi) % math.tau) - math.pi)
        reached_limit = index - start + 1 >= maximum_points
        meaningful_bend = turn >= curvature_threshold_rad and index - start >= 3
        if reached_limit or meaningful_bend:
            chunks.append((start, points[start:index + 1]))
            start = index
        previous_heading = heading
    if start < len(points) - 1:
        chunks.append((start, points[start:]))
    return chunks


def _mean_point(points):
    if not points:
        return 0.0, 0.5
    angles = [float(point[0]) * math.tau for point in points]
    u = (math.atan2(sum(math.sin(a) for a in angles), sum(math.cos(a) for a in angles)) / math.tau) % 1.0
    return u, sum(float(point[1]) for point in points) / len(points)


def _orient_chain(heightmap, points):
    if len(points) < 2:
        return points
    measurements = _local_measurements(heightmap, points)
    landward = measurements["landward_normal_uv"]
    du = ((float(points[-1][0]) - float(points[0][0]) + 0.5) % 1.0) - 0.5
    dv = float(points[-1][1]) - float(points[0][1])
    cross = du * float(landward[1]) - dv * float(landward[0])
    return list(reversed(points)) if cross < 0.0 else points


def _local_measurements(heightmap, points):
    rows, width, height, wrap_x = _grid_dimensions(heightmap)
    sea = float(heightmap.get("sea_level_m", 0.0) or 0.0)
    u, v = _mean_point(points)
    x = int(round(u * width)) % max(1, width)
    y = max(0, min(height - 1, int(round(v * (height - 1)))))
    radius = 3
    land_values, sea_values = [], []
    for dy in range(-radius, radius + 1):
        yy = max(0, min(height - 1, y + dy))
        for dx in range(-radius, radius + 1):
            xx = (x + dx) % width if wrap_x else max(0, min(width - 1, x + dx))
            elevation = float(rows[yy][xx])
            (land_values if elevation >= sea else sea_values).append(elevation)
    spacing_x = float(heightmap.get("sample_spacing_x_m") or heightmap.get("equator_resolution_m_per_px") or ((heightmap.get("circumference_m") or 40_030_000.0) / max(1, width)))
    spacing_y = float(heightmap.get("sample_spacing_y_m") or spacing_x)
    left, right = float(rows[y][(x - 1) % width]), float(rows[y][(x + 1) % width])
    up, down = float(rows[max(0, y - 1)][x]), float(rows[min(height - 1, y + 1)][x])
    gradient_x, gradient_y = (right - left) / max(0.01, 2.0 * spacing_x), (down - up) / max(0.01, 2.0 * spacing_y)
    gradient_norm = max(1e-12, math.hypot(gradient_x, gradient_y))
    landward = [gradient_x / gradient_norm, gradient_y / gradient_norm]
    nearshore_gradient = max(0.0, ((sum(land_values) / max(1, len(land_values))) - (sum(sea_values) / max(1, len(sea_values)))) / max(0.01, radius * (spacing_x + spacing_y)))
    relief = max(land_values or [sea]) - min(land_values or [sea])
    tangent_angle = 0.0
    if len(points) >= 2:
        du = ((float(points[-1][0]) - float(points[0][0]) + 0.5) % 1.0) - 0.5
        dv = float(points[-1][1]) - float(points[0][1])
        tangent_angle = math.atan2(dv, du * max(0.1, math.cos((0.5 - v) * math.pi)))
    curvature = 0.0
    if len(points) >= 3:
        headings = []
        for a, b in zip(points, points[1:]):
            du = ((float(b[0]) - float(a[0]) + 0.5) % 1.0) - 0.5
            headings.append(math.atan2(float(b[1]) - float(a[1]), du))
        curvature = sum(abs(((b - a + math.pi) % math.tau) - math.pi) for a, b in zip(headings, headings[1:])) / max(1, len(headings) - 1)
    masks = heightmap.get("surface_masks") or {}
    shelf_rows = masks.get("continental_shelf_rows") or []
    seaward = [-landward[0], -landward[1]]
    shelf_cells = 0
    if shelf_rows:
        for step in range(1, 13):
            xx = int(round(x + seaward[0] * step))
            yy = int(round(y + seaward[1] * step))
            if wrap_x:
                xx %= width
            elif xx < 0 or xx >= width:
                break
            yy = max(0, min(height - 1, yy))
            if not shelf_rows[yy][xx]:
                break
            shelf_cells = step
    local_transitions = 0
    local_edges = 0
    for dy in range(-3, 4):
        yy = max(0, min(height - 1, y + dy))
        for dx in range(-3, 4):
            xx = (x + dx) % width if wrap_x else max(0, min(width - 1, x + dx))
            land = float(rows[yy][xx]) >= sea
            east = float(rows[yy][(xx + 1) % width if wrap_x else min(width - 1, xx + 1)]) >= sea
            south = float(rows[min(height - 1, yy + 1)][xx]) >= sea
            local_transitions += int(land != east) + int(land != south)
            local_edges += 2
    return {
        "centroid_uv": [round(u, 6), round(v, 6)],
        "inland_relief_m": round(relief, 1),
        "inland_slope": round(max(0.0, gradient_norm), 6),
        "nearshore_gradient": round(nearshore_gradient, 6),
        "landward_normal_uv": [round(landward[0], 5), round(landward[1], 5)],
        "seaward_normal_uv": [round(-landward[0], 5), round(-landward[1], 5)],
        "orientation_rad": round(tangent_angle, 5),
        "curvature_index": round(_clamp(curvature / math.pi), 3),
        "embayment_index": round(_clamp(curvature / (math.pi * 0.7)), 3),
        "enclosure_index": round(_clamp(curvature / (math.pi * 0.8)), 3),
        "archipelago_index": round(_clamp(local_transitions / max(1, local_edges) * 4.0), 3),
        "shelf_width_km": round(shelf_cells * math.sqrt(spacing_x * spacing_y) / 1000.0, 2),
        "headland_index": round(_clamp((relief / 1800.0) * (0.4 + nearshore_gradient * 1400.0)), 3),
    }


def _ray_fetch_km(heightmap, origin, direction, max_steps=48):
    masks = heightmap.get("surface_masks") or {}
    ocean = masks.get("ocean_rows") or []
    rows, width, height, wrap_x = _grid_dimensions(heightmap)
    if not ocean or not width:
        return 0.0
    u, v = origin
    cell_km = float(heightmap.get("circumference_m") or 40_030_000.0) / max(1, width) / 1000.0
    travelled = 0
    for step in range(1, max_steps + 1):
        sample_u = u + direction[0] * step / width
        sample_v = v + direction[1] * step / max(1, height - 1)
        if not wrap_x and not 0.0 <= sample_u <= 1.0 or not 0.0 <= sample_v <= 1.0:
            break
        x = int(round((sample_u % 1.0) * width)) % width
        y = max(0, min(height - 1, int(round(sample_v * (height - 1)))))
        if not ocean[y][x]:
            break
        travelled = step
    return travelled * cell_km


def _nearest_river_influence(water_cycle, centroid, width, height):
    best = None
    for river in water_cycle.get("rivers") or []:
        points = river.get("display_points") or river.get("points") or []
        if not points:
            continue
        mouth = points[-1]
        try:
            raw_u = mouth.get("x") if isinstance(mouth, dict) else mouth[0]
            raw_v = mouth.get("y") if isinstance(mouth, dict) else mouth[1]
            u = float(raw_u) / max(1, width - 1) if float(raw_u) > 1.0 else float(raw_u)
            v = float(raw_v) / max(1, height - 1) if float(raw_v) > 1.0 else float(raw_v)
        except (TypeError, ValueError, IndexError):
            continue
        du = abs(u - centroid[0])
        du = min(du, 1.0 - du)
        distance = math.hypot(du * max(0.1, math.cos((0.5 - centroid[1]) * math.pi)), v - centroid[1])
        if best is None or distance < best[0]:
            discharge = float(river.get("estimated_discharge_m3_s", 0.0) or 0.0)
            best = (distance, discharge, river)
    if best is None:
        return 0.0, None
    influence = _clamp((0.08 - best[0]) / 0.08) * _clamp(math.log1p(best[1]) / math.log(10001.0))
    return influence, best[2] if influence > 0.0 else None


def _nearest_coastal_segment(segments, point, *, wrap_x=True):
    if not segments or not isinstance(point, dict):
        return None
    u = float(point.get("x", 0.0) or 0.0)
    v = float(point.get("y", 0.0) or 0.0)

    def distance(segment):
        centroid = (
            (segment.get("measurements") or {}).get("centroid_uv")
            or [0.0, 0.5]
        )
        du = abs(float(centroid[0]) - u)
        if wrap_x:
            du = min(du, 1.0 - du)
        return math.hypot(du, float(centroid[1]) - v)

    return min(segments, key=distance)


def _normalized_hydrology_point(point, *, width, height):
    """Normalize current and legacy hydrology point encodings to map UV."""
    try:
        if isinstance(point, dict):
            raw_x = point.get("x", point.get("u"))
            raw_y = point.get("y", point.get("v"))
        elif isinstance(point, (list, tuple)) and len(point) >= 2:
            raw_x, raw_y = point[0], point[1]
        else:
            return None
        x, y = float(raw_x), float(raw_y)
    except (TypeError, ValueError):
        return None
    if abs(x) > 1.0:
        x /= max(1, int(width) - 1)
    if abs(y) > 1.0:
        y /= max(1, int(height) - 1)
    return {"x": _clamp(x), "y": _clamp(y)}


def _river_delta_sediment_index(river, segment=None):
    """Estimate relative fluvial sediment delivery at a receiving basin.

    This is a reduced-physics source term, not a claimed mass-flux estimate.
    Discharge supplies transport capacity; catchment runoff, area, relief,
    channel gradient and substrate erodibility supply and route sediment.
    """
    river = river if isinstance(river, dict) else {}
    segment = segment if isinstance(segment, dict) else {}
    discharge = _clamp(
        math.log1p(
            max(0.0, float(river.get("estimated_discharge_m3_s", 0.0) or 0.0))
        )
        / math.log(10_001.0)
    )
    catchment_area = _clamp(
        math.log1p(max(0.0, float(river.get("catchment_area_km2", 0.0) or 0.0)))
        / math.log(2_000_001.0)
    )
    runoff = _clamp(
        float(river.get("catchment_mean_runoff_mm", 0.0) or 0.0) / 700.0
    )
    source_relief = _clamp(
        max(0.0, float(river.get("source_elevation_m", 0.0) or 0.0))
        / 3_500.0
    )
    morphology = (
        river.get("channel_morphology")
        if isinstance(river.get("channel_morphology"), dict)
        else {}
    )
    gradient = _clamp(
        float(morphology.get("gradient_m_per_m", 0.0) or 0.0) / 0.012
    )
    erodibility = _clamp(
        float(
            (segment.get("influences") or {}).get(
                "material_erodibility_proxy", 0.55
            )
            or 0.55
        )
    )
    persistence = (
        1.0
        if river.get("flow_regime") == "perennial"
        else 0.76
        if river.get("flow_regime") == "intermittent"
        else 0.35
    )
    source = (
        discharge * 0.28
        + catchment_area * 0.18
        + runoff * 0.22
        + max(source_relief, gradient) * 0.17
        + erodibility * 0.15
    )
    return _clamp(source * (0.58 + persistence * 0.42))


def _delta_planform(
    center,
    direction,
    *,
    width,
    height,
    radius_cells,
    dominance,
    distributary_count,
    wrap_x,
):
    """Create a compact scale-aware delta lobe and distributary geometry."""
    center_u = float(center.get("x", 0.0) or 0.0)
    center_v = float(center.get("y", 0.0) or 0.0)
    dx, dy = float(direction[0]), float(direction[1])
    length = max(1e-9, math.hypot(dx, dy))
    dx, dy = dx / length, dy / length
    tx, ty = -dy, dx
    radius_u = float(radius_cells) / max(2, width - 1)
    radius_v = float(radius_cells) / max(2, height - 1)
    if dominance == "river_dominated":
        forward_scale, lateral_scale, spread = 1.45, 0.72, math.radians(34.0)
    elif dominance == "wave_dominated":
        forward_scale, lateral_scale, spread = 0.82, 1.38, math.radians(68.0)
    elif dominance == "tide_dominated":
        forward_scale, lateral_scale, spread = 1.18, 0.82, math.radians(28.0)
    else:
        forward_scale, lateral_scale, spread = 1.0, 1.0, math.radians(48.0)

    def point(forward, lateral):
        u = center_u + dx * forward * radius_u + tx * lateral * radius_u
        v = center_v + dy * forward * radius_v + ty * lateral * radius_v
        if wrap_x:
            u %= 1.0
        return {
            "x": round(_clamp(u) if not wrap_x else u, 6),
            "y": round(_clamp(v), 6),
        }

    footprint = [
        point(-0.28, -0.42 * lateral_scale),
        point(0.18, -0.86 * lateral_scale),
        point(0.72 * forward_scale, -0.74 * lateral_scale),
        point(1.00 * forward_scale, 0.0),
        point(0.72 * forward_scale, 0.74 * lateral_scale),
        point(0.18, 0.86 * lateral_scale),
        point(-0.28, 0.42 * lateral_scale),
    ]
    trunk = point(-0.42, 0.0)
    first_split = point(0.03, 0.0)
    distributaries = []
    count = max(1, int(distributary_count or 1))
    # Real deltas bifurcate repeatedly at staggered points rather than every
    # channel fanning from one shared split -- that produced a rigid star.
    # Group branches into a small number of primary channels, each splitting
    # again at its OWN secondary point further out, and give each branch a
    # gentle sinusoidal undulation instead of a single straight midpoint.
    primary_count = min(count, 3)
    group_sizes = [count // primary_count] * primary_count
    for extra in range(count % primary_count):
        group_sizes[extra] += 1
    branch_index = 0
    for group_index, group_size in enumerate(group_sizes):
        if group_size <= 0:
            continue
        primary_fraction = 0.5 if primary_count == 1 else group_index / (primary_count - 1)
        primary_angle = (primary_fraction - 0.5) * spread * 1.3
        primary_dx = dx * math.cos(primary_angle) - dy * math.sin(primary_angle)
        primary_dy = dx * math.sin(primary_angle) + dy * math.cos(primary_angle)
        secondary_forward = 0.30 * forward_scale
        secondary_u = center_u + primary_dx * radius_u * secondary_forward
        secondary_v = center_v + primary_dy * radius_v * secondary_forward
        if wrap_x:
            secondary_u %= 1.0
        secondary_split = {
            "x": round(_clamp(secondary_u) if not wrap_x else secondary_u, 6),
            "y": round(_clamp(secondary_v), 6),
        }
        for sub_index in range(group_size):
            sub_fraction = 0.5 if group_size == 1 else sub_index / (group_size - 1)
            angle = primary_angle + (sub_fraction - 0.5) * spread * 1.1
            branch_dx = dx * math.cos(angle) - dy * math.sin(angle)
            branch_dy = dx * math.sin(angle) + dy * math.cos(angle)
            undulation = math.sin(branch_index * 2.4 + sub_fraction * math.pi) * lateral_scale * 0.09
            mid_forward = 0.62 * forward_scale
            mid_u = center_u + branch_dx * radius_u * mid_forward + tx * undulation * radius_u
            mid_v = center_v + branch_dy * radius_v * mid_forward + ty * undulation * radius_v
            if wrap_x:
                mid_u %= 1.0
            mid = {
                "x": round(_clamp(mid_u) if not wrap_x else mid_u, 6),
                "y": round(_clamp(mid_v), 6),
            }
            end_u = center_u + branch_dx * radius_u * forward_scale
            end_v = center_v + branch_dy * radius_v * forward_scale
            if wrap_x:
                end_u %= 1.0
            end = {
                "x": round(_clamp(end_u) if not wrap_x else end_u, 6),
                "y": round(_clamp(end_v), 6),
            }
            distributaries.append([trunk, first_split, secondary_split, mid, end])
            branch_index += 1
    return footprint, distributaries


def _resolve_delta_systems(water_cycle, segments, *, width, height, wrap_x):
    """Resolve marine and lacustrine deltas from sediment-flux balance."""
    # Disabled for now: the delta footprint/distributary visualization is
    # not yet worth showing (see conversation history for the geometry
    # rework attempts). Returns no deltas until this is revisited, rather
    # than deleting the underlying sediment-balance model.
    return [], []
    water_cycle = water_cycle if isinstance(water_cycle, dict) else {}
    segments = [segment for segment in segments if isinstance(segment, dict)]
    rivers = [
        river
        for river in water_cycle.get("rivers") or []
        if isinstance(river, dict)
        and river.get("mouth") in {"ocean", "lake"}
        and river.get("flow_regime", "perennial") in {
            "perennial", "intermittent",
        }
    ]
    lakes = [
        lake
        for lake in water_cycle.get("lakes") or []
        if isinstance(lake, dict)
    ]
    assessments = []
    deltas = []
    for river in rivers:
        points = river.get("display_points") or river.get("points") or []
        if not points:
            continue
        normalized_points = [
            normalized
            for normalized in (
                _normalized_hydrology_point(
                    point,
                    width=width,
                    height=height,
                )
                for point in points
            )
            if normalized is not None
        ]
        if not normalized_points:
            continue
        center = normalized_points[-1]
        receiving_basin = str(river.get("mouth"))
        segment = (
            _nearest_coastal_segment(segments, center, wrap_x=wrap_x)
            if receiving_basin == "ocean"
            else None
        )
        sediment_source = _river_delta_sediment_index(river, segment)
        if segment is not None:
            measurements = segment.get("measurements") or {}
            wave = segment.get("wave_climate") or {}
            tide = segment.get("tidal_regime") or {}
            sediment = segment.get("sediment_budget") or {}
            sediment_supply = max(
                sediment_source,
                _clamp(float(sediment.get("river_supply", 0.0) or 0.0) * 0.88),
            )
            shelf_retention = _clamp(
                (1.0 - _clamp(float(measurements.get("nearshore_gradient", 0.0) or 0.0) / 0.015)) * 0.38
                + _clamp(float(sediment.get("accommodation_index", 0.0) or 0.0)) * 0.24
                + _clamp(float(measurements.get("embayment_index", 0.0) or 0.0)) * 0.14
                + _clamp(float(measurements.get("shelf_width_km", 0.0) or 0.0) / 120.0) * 0.14
                + (
                    float(segment.get("substrate") in {"mud", "sand"})
                    * 0.10
                )
            )
            wave_strength = _clamp(
                float(wave.get("transport_capacity_index", 0.0) or 0.0)
            )
            tide_strength = _clamp(
                float(tide.get("estimated_range_m", 0.0) or 0.0) / 5.0
            )
            reworking = _clamp(
                wave_strength * 0.62 + tide_strength * 0.38
            )
            relative_state = str(
                segment.get("relative_sea_level_state") or "stable"
            )
            accommodation_demand = {
                "emergent": 0.02,
                "stable": 0.08,
                "submergent": 0.24,
            }.get(relative_state, 0.10)
            steep_shelf = _clamp(
                float(measurements.get("nearshore_gradient", 0.0) or 0.0)
                / 0.020
            )
            direction = measurements.get("seaward_normal_uv") or [0.0, 1.0]
            forcing = {
                "river_dominated": sediment_supply,
                "wave_dominated": wave_strength,
                "tide_dominated": tide_strength,
            }
        else:
            nearest_lake = None
            if lakes:
                nearest_lake = min(
                    lakes,
                    key=lambda lake: math.hypot(
                        min(
                            abs(
                                float((lake.get("center") or {}).get("x", 0.0))
                                - float(center.get("x", 0.0))
                            ),
                            1.0
                            - abs(
                                float((lake.get("center") or {}).get("x", 0.0))
                                - float(center.get("x", 0.0))
                            ),
                        ),
                        float((lake.get("center") or {}).get("y", 0.0))
                        - float(center.get("y", 0.0)),
                    ),
                )
            lake_area = float(
                (nearest_lake or {}).get("area_fraction", 0.0) or 0.0
            )
            wave_strength = _clamp(math.sqrt(max(0.0, lake_area)) * 1.8)
            tide_strength = 0.0
            reworking = wave_strength * 0.45
            shelf_retention = 0.86
            accommodation_demand = (
                0.18
                if (nearest_lake or {}).get("water_balance_limited")
                else 0.07
            )
            steep_shelf = 0.12
            sediment_supply = sediment_source
            relative_state = "lake_level_limited"
            if len(normalized_points) >= 2:
                direction = [
                    float(normalized_points[-1].get("x", 0.0))
                    - float(normalized_points[-2].get("x", 0.0)),
                    float(normalized_points[-1].get("y", 0.0))
                    - float(normalized_points[-2].get("y", 0.0)),
                ]
            else:
                direction = [0.0, 1.0]
            forcing = {
                "river_dominated": sediment_supply,
                "wave_dominated": wave_strength,
                "tide_dominated": 0.0,
            }

        gross_deposition = sediment_supply * (0.55 + shelf_retention * 0.45)
        removal_capacity = reworking * 0.55 + accommodation_demand * 0.22
        net_sediment_balance = gross_deposition - removal_capacity
        formation_index = _clamp(
            gross_deposition
            - reworking * 0.32
            - accommodation_demand * 0.12
            - steep_shelf * 0.12
        )
        # Most rivers reach the sea without building a delta -- an estuary,
        # or a plain unremarkable river mouth, is the common case. A delta
        # specifically needs high sediment supply that outpaces wave/tidal
        # reworking and available accommodation, sustained long enough to
        # prograde. A high-energy (wave/tide-dominated) coast needs
        # proportionally MORE sediment to still build a delta rather than
        # being smoothed into an open coast or estuary -- that scaling was
        # previously missing, so nearly every river qualified.
        sediment_required_for_energy = 0.34 + reworking * 0.42
        formed = (
            sediment_supply >= 0.40
            and formation_index >= 0.32
            and steep_shelf < 0.75
            and sediment_supply >= sediment_required_for_energy
        )
        if not formed:
            reason = (
                "insufficient_fluvial_sediment"
                if sediment_supply < 0.40
                else "steep_deep_receiving_margin"
                if steep_shelf >= 0.75
                else "marine_or_lake_reworking_exceeds_deposition"
            )
            assessments.append({
                "river_id": river.get("id"),
                "receiving_basin": receiving_basin,
                "formation_state": "no_delta",
                "limiting_factor": reason,
                "sediment_supply_index": round(sediment_supply, 3),
                "retention_index": round(shelf_retention, 3),
                "reworking_index": round(reworking, 3),
                "net_sediment_balance_index": round(net_sediment_balance, 3),
            })
            continue

        dominance = max(forcing, key=forcing.get)
        if receiving_basin == "lake":
            dominance = "lacustrine"
        trajectory = (
            "prograding"
            if net_sediment_balance > 0.14
            else "retrograding"
            if net_sediment_balance < -0.06
            else "approximately_stable"
        )
        area_scale = _clamp(
            math.log1p(
                max(0.0, float(river.get("catchment_area_km2", 0.0) or 0.0))
            )
            / math.log(1_000_001.0)
        )
        radius_cells = _clamp(
            1.2 + formation_index * 5.0 + area_scale * 2.0,
            1.0,
            8.0,
        )
        if dominance == "wave_dominated":
            distributary_count = max(
                2, min(4, int(round(2 + formation_index * 3.0)))
            )
        elif dominance == "tide_dominated":
            distributary_count = max(
                3, min(7, int(round(3 + formation_index * 5.0)))
            )
        else:
            distributary_count = max(
                3, min(9, int(round(3 + formation_index * 7.0)))
            )
        planform_dominance = (
            "river_dominated" if dominance == "lacustrine" else dominance
        )
        footprint, distributaries = _delta_planform(
            center,
            direction,
            width=width,
            height=height,
            radius_cells=radius_cells,
            dominance=planform_dominance,
            distributary_count=distributary_count,
            wrap_x=wrap_x,
        )
        delta_id = f"delta_{len(deltas) + 1:03d}"
        delta = {
            "id": delta_id,
            "river_id": river.get("id"),
            "center": center,
            "receiving_basin": receiving_basin,
            "coastal_segment_id": (segment or {}).get("id"),
            "morphodynamic_dominance": dominance,
            "marine_reworking_end_member": (
                dominance if receiving_basin == "ocean" else "lacustrine"
            ),
            "formation_state": "formed_delta",
            "trajectory": trajectory,
            "sediment_supply_index": round(sediment_supply, 3),
            "retention_index": round(shelf_retention, 3),
            "reworking_index": round(reworking, 3),
            "net_sediment_balance_index": round(net_sediment_balance, 3),
            "formation_index": round(formation_index, 3),
            "forcing_strengths": {
                key: round(value, 3) for key, value in forcing.items()
            },
            "fan_radius_cells": round(radius_cells, 2),
            "distributary_count": distributary_count,
            "footprint_points": footprint,
            "distributaries": distributaries,
            "sediment_source": (
                "catchment_erosion_river_transport_and_receiving_basin_retention"
            ),
            "relative_water_level_state": relative_state,
            "rule_trace": {
                "required": [
                    "active_river_mouth",
                    "sufficient_fluvial_sediment",
                    "receiving_basin",
                    "net_depositional_retention",
                ],
                "rejected_processes": [
                    "wave_reworking",
                    "tidal_reworking",
                    "relative_water_level_accommodation",
                    "steep_margin_bypass",
                ],
                "reduced_physics": True,
            },
        }
        deltas.append(delta)
        assessments.append({
            **{
                key: delta[key]
                for key in (
                    "river_id",
                    "receiving_basin",
                    "formation_state",
                    "sediment_supply_index",
                    "retention_index",
                    "reworking_index",
                    "net_sediment_balance_index",
                    "formation_index",
                )
            },
            "delta_id": delta_id,
        })
        if segment is not None:
            previous = segment.get("morphology_assemblage")
            segment["secondary_assemblage"] = (
                previous if previous != "deltaic" else segment.get("secondary_assemblage")
            )
            segment["primary_assemblage"] = "deltaic"
            segment["morphology_assemblage"] = "deltaic"
            segment["coastal_system"] = "deltaic"
            segment["display_color"] = ASSEMBLAGE_COLORS["deltaic"]
            segment["delta_id"] = delta_id
            segment["shoreline_trajectory"] = trajectory
            trace = segment.setdefault("rule_trace", {})
            trace["delta_formation"] = {
                "formation_index": round(formation_index, 3),
                "net_sediment_balance_index": round(net_sediment_balance, 3),
                "morphodynamic_dominance": dominance,
            }
    return assessments, deltas


def _tectonic_setting(tectonic_model, centroid):
    regime = str((tectonic_model.get("summary") or {}).get("regime") or tectonic_model.get("tectonic_regime") or "").lower()
    nearest_kind, nearest_distance = None, 2.0
    for boundary in tectonic_model.get("boundary_segments") or []:
        points = boundary.get("points") or boundary.get("polyline") or []
        if not points and all(key in boundary for key in ("x1", "y1", "x2", "y2")):
            points = [
                [boundary["x1"], boundary["y1"]],
                [(float(boundary["x1"]) + float(boundary["x2"])) * 0.5, (float(boundary["y1"]) + float(boundary["y2"])) * 0.5],
                [boundary["x2"], boundary["y2"]],
            ]
        for point in points:
            try:
                u, v = float(point[0]), float(point[1])
            except (TypeError, ValueError, IndexError):
                continue
            du = min(abs(u - centroid[0]), 1.0 - abs(u - centroid[0]))
            distance = math.hypot(du, v - centroid[1])
            if distance < nearest_distance:
                nearest_distance, nearest_kind = distance, boundary.get("kind")
    if nearest_distance <= 0.055 and nearest_kind in {"subduction", "collision", "convergent", "transform"}:
        return "collision_active", nearest_kind, 0.82
    if "mobile" in regime or tectonic_model.get("plates"):
        return "trailing_passive", nearest_kind, 0.66
    if any(token in regime for token in ("stagnant", "heat_pipe", "plume")):
        return "oceanic_island", nearest_kind, 0.62
    return "uncertain", nearest_kind, 0.38


def _seiche_resonance_factor(embayment_index, nearshore_gradient, shelf_width_km):
    """Approximate quarter-wave seiche resonance for a semi-enclosed basin.

    The existing shelf/enclosure amplification above is purely geometric
    funnelling. Real macrotidal extremes (Bay of Fundy ~16m, Bristol Channel,
    Ungava Bay) come from a basin's natural oscillation period resonating
    with the semidiurnal tidal forcing period -- a fundamentally different
    and much larger amplification mechanism than geometric funnelling alone.
    This module deliberately does not solve real bathymetry. Basin length is
    driven by embayment_index (curvature-based enclosure, which has real
    spread) rather than shelf_width_km, which is typically only a few
    hundred metres to a few km in this codebase's shoreline measurements --
    far too short for anything to resonate with a ~12.4h tidal period, which
    made an earlier version of this function silently return ~1.0 (no
    effect) for essentially every coastline. Real resonant bays span a few
    km (small coves, negligible effect) to several hundred km (Fundy-scale).
    """
    embayment_index = _clamp(embayment_index)
    basin_length_m = 3_000.0 + (embayment_index ** 2) * 300_000.0
    basin_depth_m = _clamp(70.0 - float(nearshore_gradient or 0.0) * 120.0, 8.0, 70.0)
    wave_speed_m_s = math.sqrt(9.81 * basin_depth_m)
    natural_period_h = (4.0 * basin_length_m / wave_speed_m_s) / 3600.0
    forcing_period_h = 12.42
    mismatch = (natural_period_h - forcing_period_h) / forcing_period_h
    resonance = math.exp(-((mismatch / 0.45) ** 2))
    return min(2.5, 1.0 + resonance * embayment_index * 1.5)


def _paleoclimate_sea_level_signal(map_seed, eccentricity, axial_tilt_deg, planetary_centroid):
    """Bounded, seed-reproducible multi-cycle paleoclimate sea-level proxy.

    Quaternary-style raised terraces and drowned valleys are not one flat
    present-day snapshot: repeated eccentricity/obliquity/precession-style
    orbital cycles drive successive glacial/interglacial eustatic
    highstands and lowstands, and which highstand generation is best
    preserved/exposed varies by location. This module deliberately does not
    solve real glacial chronology, so amplitude is scaled by the planet's
    own orbital parameters (near-circular, low-tilt worlds get far less
    orbitally forced variability than an eccentric, high-tilt one) rather
    than literal Earth cycle periods, and each location's phase in that
    history is an independent seeded value standing in for its own
    preservation/exposure history.
    """
    amplitude = _clamp(
        float(eccentricity or 0.0) * 1.8 + abs(float(axial_tilt_deg or 23.44) - 23.44) / 35.0,
        0.0,
        1.0,
    )
    if amplitude <= 0.0:
        return 0.0
    key = f"paleoclimate_phase:{round(planetary_centroid[0], 5)}:{round(planetary_centroid[1], 5)}"
    phase = seed_range(map_seed, key, 0.0, math.tau)
    eccentricity_cycle = math.sin(phase)
    obliquity_cycle = math.sin(phase * 2.44 + 1.7)
    precession_cycle = math.sin(phase * 4.31 + 3.2)
    signal = eccentricity_cycle * 0.5 + obliquity_cycle * 0.32 + precession_cycle * 0.18
    return _clamp(signal * amplitude, -1.0, 1.0) * 0.30


def _tidal_regime(planet, star, measurements):
    radius = float(planet.get("radius_m") or (planet.get("derived_planet_physics") or {}).get("radius_m") or 6_371_000.0)
    distance = float(planet.get("semi_major_axis_m") or 0.0)
    mass = float((star or {}).get("mass_kg") or 0.0)
    contributors = []
    potential = 0.0
    if distance > 0.0 and mass > 0.0:
        acceleration = 2.0 * G * mass * radius / distance ** 3
        potential += acceleration
        contributors.append("stellar_tide")
    for satellite in planet.get("satellites") or []:
        if not isinstance(satellite, dict):
            continue
        satellite_mass = float(satellite.get("mass_kg") or 0.0)
        orbit = float(satellite.get("semi_major_axis_m") or 0.0)
        if satellite_mass > 0.0 and orbit > radius:
            potential += 2.0 * G * satellite_mass * radius / orbit ** 3
            contributors.append(str(satellite.get("id") or "satellite_tide"))
    normalized = potential / EARTH_SOLAR_TIDE_ACCELERATION if potential > 0.0 else 0.0
    shelf_amplification = 1.0 + _clamp((0.004 - measurements["nearshore_gradient"]) / 0.004) * 1.2
    enclosure_amplification = 1.0 + measurements["embayment_index"] * 0.8
    resonance_factor = _seiche_resonance_factor(
        measurements["embayment_index"],
        measurements["nearshore_gradient"],
        measurements.get("shelf_width_km", 0.0),
    )
    tidal_range = (
        0.0
        if not contributors
        else 0.55 * math.sqrt(max(0.0, normalized)) * shelf_amplification * enclosure_amplification * resonance_factor
    )
    tidal_class = "microtidal" if tidal_range < 2.0 else ("mesotidal" if tidal_range < 4.0 else "macrotidal")
    confidence = 0.72 if mass > 0.0 and distance > 0.0 else 0.28
    if not planet.get("satellites"):
        confidence *= 0.78
    return {
        "estimated_range_m": round(tidal_range, 2),
        "class": tidal_class,
        "astronomical_potential_relative_to_earth_solar": round(normalized, 4),
        "resonance_amplification": round(resonance_factor, 3),
        "contributors": contributors,
        "confidence": round(confidence, 3),
        "method": "equilibrium_tide_with_reduced_shelf_and_enclosure_amplification",
    }


def _wrapped_uv_distance(a, b):
    du = abs(float(a[0]) - float(b[0]))
    du = min(du, 1.0 - du)
    latitude_scale = max(0.1, math.cos((0.5 - float(a[1])) * math.pi))
    return math.hypot(du * latitude_scale, float(a[1]) - float(b[1]))


def _local_volcanic_influence(tectonic_model, centroid, tectonic):
    """Resolve global volcanic provenance into local coastal evidence."""
    hotspots = ((tectonic_model.get("hotspot_model") or {}).get("hotspots") or [])
    boundaries = tectonic_model.get("boundary_segments") or []
    if not hotspots and not boundaries:
        return None

    influence = 0.0
    for hotspot in hotspots:
        for point in hotspot.get("track") or []:
            age = float(point.get("age_myr", 0.0) or 0.0)
            if age > 35.0:
                continue
            relative_volume = _clamp(point.get("relative_volume", 0.0))
            distance = _wrapped_uv_distance(
                centroid,
                [point.get("x", 0.0), point.get("y", 0.0)],
            )
            radius = 0.035 + relative_volume * 0.025
            proximity = _clamp((radius - distance) / radius)
            age_factor = _clamp(1.0 - age / 50.0)
            influence = max(
                influence,
                proximity * (0.55 + relative_volume * 0.45) * age_factor,
            )

    if tectonic[0] == "collision_active" and tectonic[1] in {
        "subduction",
        "convergent",
        "collision",
    }:
        influence = max(influence, 0.82)
    return _clamp(influence)


def _substrate_and_sediment(
    planet,
    measurements,
    river_influence,
    water_cycle,
    surface_evolution,
    tectonic_model=None,
    tectonic=None,
):
    tags = {str(tag).lower() for tag in (planet.get("tags") or [])}
    materials = planet.get("natural_material_model") or {}
    material_text = " ".join(
        str(item.get("material_id") or item.get("name") or "").lower()
        for item in (materials.get("regional_material_candidates") or materials.get("likely_materials") or [])
        if isinstance(item, dict)
    )
    glacial_rows = ((surface_evolution.get("process_grid") or {}).get("glacial_erosion_rows") or [])
    glacial = _sample(glacial_rows, *measurements["centroid_uv"]) if glacial_rows else 0.0
    deposition_rows = ((surface_evolution.get("process_grid") or {}).get("sediment_deposition_rows") or [])
    deposition = _sample(deposition_rows, *measurements["centroid_uv"]) if deposition_rows else 0.0
    material_context = " ".join(tags) + material_text
    volcanic_context = any(
        token in material_context
        for token in ("basalt", "volcan", "lava", "scoria", "tuff", "pumice")
    )
    carbonate_context = any(
        token in material_context
        for token in ("carbonate", "limestone", "dolomite", "karst")
    )
    planetary_centroid = measurements.get("planetary_centroid_uv") or measurements["centroid_uv"]
    local_volcanism = _local_volcanic_influence(
        tectonic_model or {},
        planetary_centroid,
        tectonic or ("uncertain", None, 0.0),
    )
    volcanic_influence = (
        float(volcanic_context) if local_volcanism is None else local_volcanism
    )
    volcanic = volcanic_influence >= 0.34

    climate = water_cycle.get("climate_grid") or {}
    temperature_rows = climate.get("temperature_rows_k") or []
    temperature_k = (
        _sample(temperature_rows, *measurements["centroid_uv"])
        if temperature_rows
        else 0.0
    )
    latitude = abs((0.5 - float(planetary_centroid[1])) * 180.0)
    biosphere_state = str(
        planet.get("biosphere_state")
        or (planet.get("world_gen_seed") or {}).get("biosphere_state")
        or ""
    ).lower()
    biogenic_context = any(
        token in biosphere_state
        for token in ("oxygenic", "marine", "mature", "complex")
    )
    if carbonate_context and not temperature_rows:
        carbonate_influence = 1.0
    else:
        thermal_suitability = _clamp((temperature_k - 285.0) / 10.0) * _clamp(
            (310.0 - temperature_k) / 8.0
        )
        latitude_suitability = _clamp((42.0 - latitude) / 20.0)
        sediment_exclusion = 1.0 - _clamp(
            river_influence * 1.7 + deposition * 0.55
        )
        substrate_suitability = 1.0 - _clamp(
            measurements["inland_relief_m"] / 1200.0
            + measurements["nearshore_gradient"] / 0.012
        )
        carbonate_factory = (
            thermal_suitability
            * latitude_suitability
            * sediment_exclusion
            * (0.45 + substrate_suitability * 0.55)
        )
        carbonate_influence = max(
            0.58 if carbonate_context else 0.0,
            carbonate_factory if biogenic_context else 0.0,
        )
    carbonate = carbonate_influence >= 0.52
    # Glacial erosion records former ice flow; it is not evidence that the
    # present substrate contains excess ground ice or permafrost.
    ice_rich = any("ice_rich" in tag or "permafrost" in tag for tag in tags)
    relief = measurements["inland_relief_m"]
    if volcanic:
        substrate = "volcanic"
    elif carbonate:
        substrate = "carbonate"
    elif ice_rich:
        substrate = "ice_rich"
    elif relief >= 850.0 or measurements["nearshore_gradient"] >= 0.006:
        substrate = "resistant_bedrock"
    elif relief >= 280.0:
        substrate = "erodible_bedrock"
    elif river_influence >= 0.45 or deposition >= 0.45:
        substrate = "mud"
    else:
        substrate = "sand"
    marine_delivery = float((surface_evolution.get("sediment_budget") or {}).get("marine_delivery_index", 0.0) or 0.0)
    river_supply = _clamp(river_influence * 0.72 + math.log1p(max(0.0, marine_delivery)) / 18.0)
    cliff_supply = _clamp(relief / 2200.0) * (1.0 - river_influence)
    glacial_supply = _clamp(glacial)
    volcanic_supply = 0.72 * volcanic_influence if volcanic else 0.0
    carbonate_supply = 0.56 * carbonate_influence if carbonate else 0.0
    total = river_supply + cliff_supply + glacial_supply + volcanic_supply + carbonate_supply
    fractions = {
        "mud": river_supply * 0.55 + glacial_supply * 0.25,
        "sand": river_supply * 0.35 + cliff_supply * 0.45 + carbonate_supply * 0.75,
        "gravel": cliff_supply * 0.55 + glacial_supply * 0.65,
        "bioclastic": carbonate_supply,
        "volcaniclastic": volcanic_supply,
    }
    fraction_total = sum(fractions.values())
    fractions = {key: round(value / max(1e-9, fraction_total), 3) for key, value in fractions.items()}
    return substrate, {
        "source_strength": round(_clamp(total / 2.2), 3),
        "river_supply": round(river_supply, 3),
        "cliff_supply": round(cliff_supply, 3),
        "glacial_supply": round(glacial_supply, 3),
        "volcaniclastic_supply": round(volcanic_supply, 3),
        "carbonate_supply": round(carbonate_supply, 3),
        "fractions": fractions,
        "accommodation_index": round(_clamp(measurements["embayment_index"] * 0.55 + (1.0 - measurements["nearshore_gradient"] * 90.0) * 0.45), 3),
    }, {
        "glacial": glacial,
        "volcanic": volcanic,
        "volcanic_influence": round(volcanic_influence, 3),
        "carbonate": carbonate,
        "carbonate_influence": round(carbonate_influence, 3),
        "ice_rich": ice_rich,
    }


def _classify(measurements, tectonic, wave, tide, substrate, sediment, special, river_influence, relative_sea_level):
    relief = measurements["inland_relief_m"]
    gradient = measurements["nearshore_gradient"]
    source = sediment["source_strength"]
    accommodation = sediment["accommodation_index"]
    scores = defaultdict(float)
    scores["rocky_cliff"] = _clamp(relief / 1300.0) * 0.58 + _clamp(gradient / 0.008) * 0.42
    scores["headland_bay"] = measurements["headland_index"] * 0.52 + measurements["embayment_index"] * 0.48
    scores["clastic_beach"] = (1.0 if substrate in {"sand", "gravel", "mixed"} else 0.15) * 0.55 + source * 0.25 + wave["exposure_index"] * 0.20
    scores["barrier_lagoon"] = (1.0 if substrate == "sand" else 0.15) * 0.35 + accommodation * 0.35 + source * 0.18 + (1.0 - _clamp(gradient / 0.004)) * 0.12
    scores["deltaic"] = river_influence * 0.62 + source * 0.25 + (1.0 - wave["exposure_index"] * 0.45) * 0.13
    scores["estuarine_drowned_valley"] = river_influence * 0.28 + measurements["embayment_index"] * 0.32 + (1.0 if relative_sea_level == "submergent" else 0.0) * 0.40
    scores["tidal_flat_accommodation"] = (1.0 if substrate == "mud" else 0.15) * 0.30 + accommodation * 0.30 + (1.0 if tide["class"] == "macrotidal" else 0.35) * 0.40
    scores["glacial_fjord_fjard_skerry"] = special["glacial"] * 0.60 + _clamp(relief / 1500.0) * 0.25 + (1.0 if relative_sea_level == "submergent" else 0.0) * 0.15
    scores["volcanic"] = special.get(
        "volcanic_influence", float(special["volcanic"])
    )
    scores["carbonate_karst"] = special.get(
        "carbonate_influence", float(special["carbonate"])
    )
    scores["permafrost"] = 0.9 if special["ice_rich"] else 0.0
    scores["emergent_marine_terrace"] = (1.0 if relative_sea_level == "emergent" else 0.0) * 0.72 + _clamp(relief / 1000.0) * 0.28
    ordered = sorted(scores, key=lambda key: (scores[key], key), reverse=True)
    primary = ordered[0]
    secondary = next((key for key in ordered[1:] if scores[key] >= max(0.34, scores[primary] * 0.58)), None)
    if special["glacial"] < 0.18 and primary == "glacial_fjord_fjard_skerry":
        primary = "rocky_cliff"
    forcing = max(
        {
            "wave": wave["exposure_index"],
            "tide": _clamp(tide["estimated_range_m"] / 5.0),
            "fluvial": river_influence,
            "glacial": special["glacial"],
            "volcanic": special.get("volcanic_influence", float(special["volcanic"])),
            "chemical_karst": special.get("carbonate_influence", float(special["carbonate"])),
        }.items(),
        key=lambda item: item[1],
    )[0]
    trajectory = "prograding" if source > wave["transport_capacity_index"] + 0.18 else ("retrograding" if source + 0.18 < wave["transport_capacity_index"] else "approximately_stable")
    morphology_keys = [
        "rocky_cliff", "headland_bay", "clastic_beach", "barrier_lagoon",
        "deltaic", "estuarine_drowned_valley", "tidal_flat_accommodation",
        "glacial_fjord_fjard_skerry", "emergent_marine_terrace",
    ]
    morphology_ordered = sorted(morphology_keys, key=lambda key: (scores[key], key), reverse=True)
    morphology = morphology_ordered[0]
    if special["glacial"] < 0.18 and morphology == "glacial_fjord_fjard_skerry":
        morphology = "rocky_cliff"
    geologic_characters = []
    if special["volcanic"]:
        geologic_characters.append("volcanic")
    if special["carbonate"]:
        geologic_characters.append("carbonate_karst")
    if special["ice_rich"]:
        geologic_characters.append("permafrost")
    confidence = _clamp(0.38 + abs(scores[ordered[0]] - scores[ordered[1]]) * 0.35 + tide["confidence"] * 0.15 + tectonic[2] * 0.12)
    return primary, secondary, morphology, geologic_characters, forcing, trajectory, confidence, scores


def derive_coastal_geomorphology_model(*, planet, heightmap, water_cycle=None, tectonic_model=None, surface_evolution=None, star=None):
    planet = planet if isinstance(planet, dict) else {}
    heightmap = heightmap if isinstance(heightmap, dict) else {}
    water_cycle = water_cycle if isinstance(water_cycle, dict) else {}
    tectonic_model = tectonic_model if isinstance(tectonic_model, dict) else {}
    surface_evolution = surface_evolution if isinstance(surface_evolution, dict) else {}
    world_gen_seed = planet.get("world_gen_seed") if isinstance(planet.get("world_gen_seed"), dict) else {}
    paleoclimate_map_seed = world_gen_seed.get("map_seed") or planet.get("id", "")
    paleoclimate_eccentricity = _clamp(float(world_gen_seed.get("orbital_eccentricity", 0.0) or 0.0), 0.0, 0.85)
    paleoclimate_axial_tilt_deg = float(world_gen_seed.get("axial_tilt_deg", 23.44) or 23.44)
    sea_level = heightmap.get("sea_level_m")
    if sea_level is None:
        return {"status": "not_applicable", "model_version": COASTAL_MODEL_VERSION, "reason": "no_marine_datum", "segments": [], "summary": {"segment_count": 0, "coastline_length_km": 0.0}}
    rows, width, height, wrap_x = _grid_dimensions(heightmap)
    edges = _marching_edges(heightmap)
    chains = _ordered_chains(edges, wrap_x=wrap_x)
    radius = float(heightmap.get("radius_m") or planet.get("radius_m") or 6_371_000.0)
    segments = []
    component_records = []
    for component_index, chain in enumerate(chains):
        if len(chain) < 2:
            continue
        chain = _orient_chain(heightmap, chain)
        component_length = _polyline_length_m(heightmap, chain, radius)
        component_id = hashlib.sha256(f"{planet.get('id')}|component|{component_index}|{COASTAL_MODEL_VERSION}".encode("utf-8")).hexdigest()[:16]
        component_records.append({"id": f"coast_component_{component_id}", "point_count": len(chain), "length_km": round(component_length / 1000.0, 2), "closed": _point_key(chain[0], wrap_x) == _point_key(chain[-1], wrap_x)})
        # Stable fixed-resolution splits also bound persisted geometry size.
        for offset, points in _split_chain(chain):
            if len(points) < 2:
                continue
            measurements = _local_measurements(heightmap, points)
            centroid = measurements["centroid_uv"]
            planetary_centroid = _planetary_uv(heightmap, centroid)
            measurements["planetary_centroid_uv"] = [
                round(planetary_centroid[0], 6),
                round(planetary_centroid[1], 6),
            ]
            tectonic = _tectonic_setting(tectonic_model, planetary_centroid)
            seaward = measurements["seaward_normal_uv"]
            norm = max(1e-9, math.hypot(*seaward))
            base_direction = [seaward[0] / norm, seaward[1] / norm]
            directions = []
            for angle in (-math.pi / 4, -math.pi / 8, 0.0, math.pi / 8, math.pi / 4):
                directions.append([base_direction[0] * math.cos(angle) - base_direction[1] * math.sin(angle), base_direction[0] * math.sin(angle) + base_direction[1] * math.cos(angle)])
            fetches = [_ray_fetch_km(heightmap, centroid, direction) for direction in directions]
            fetch_km = max(fetches or [0.0])
            latitude = abs((0.5 - planetary_centroid[1]) * 180.0)
            climate = water_cycle.get("climate_grid") or {}
            seasonality = _sample(climate.get("temperature_seasonality_rows_k") or [], *centroid) if climate else 0.0
            storm = _clamp(0.18 + latitude / 90.0 * 0.42 + seasonality / 50.0 * 0.40)
            exposure = _clamp(math.log1p(fetch_km) / math.log(5001.0) * (0.62 + storm * 0.38))
            measurements["enclosure_index"] = round(max(measurements["enclosure_index"], 1.0 - _clamp(fetch_km / 600.0)), 3)
            latitude_deg = (0.5 - planetary_centroid[1]) * 180.0
            absolute_latitude = abs(latitude_deg)
            prevailing_wind_u = -1.0 if absolute_latitude < 30.0 or absolute_latitude >= 60.0 else 1.0
            prevailing_wind = [prevailing_wind_u, 0.15 * (-1.0 if latitude_deg > 0.0 else 1.0)]
            wind_norm = max(1e-9, math.hypot(*prevailing_wind))
            dot = _clamp((prevailing_wind[0] * base_direction[0] + prevailing_wind[1] * base_direction[1]) / wind_norm, -1.0, 1.0)
            incidence_angle = math.degrees(math.acos(dot))
            wave = {
                "open_water_fetch_km": round(fetch_km, 1),
                "exposure_index": round(exposure, 3),
                "exposure_class": "sheltered" if exposure < 0.28 else ("moderate" if exposure < 0.62 else "exposed"),
                "significant_wave_height_class": "low" if exposure < 0.3 else ("moderate" if exposure < 0.68 else "high"),
                "peak_period_class": "short" if fetch_km < 100.0 else ("intermediate" if fetch_km < 800.0 else "long"),
                "storm_energy_proxy": round(storm, 3),
                "prevailing_wind_vector_uv": [round(prevailing_wind[0] / wind_norm, 3), round(prevailing_wind[1] / wind_norm, 3)],
                "shoreline_incidence_angle_deg": round(incidence_angle, 1),
                "transport_capacity_index": round(_clamp(exposure * (0.55 + storm * 0.45)), 3),
                "longshore_transport_direction": "chain_forward" if math.sin(measurements["orientation_rad"]) >= 0.0 else "chain_reverse",
                "method": "directional_fetch_and_climate_storm_proxy",
            }
            tide = _tidal_regime(planet, star, measurements)
            basin_rows = ((water_cycle.get("ocean_circulation_model") or {}).get("basin_rows") or [])
            basin_index = int(round(_sample(basin_rows, *centroid, default=-1))) if basin_rows else -1
            river_influence, river = _nearest_river_influence(water_cycle, centroid, width, height)
            substrate, sediment, special = _substrate_and_sediment(
                planet,
                measurements,
                river_influence,
                water_cycle,
                surface_evolution,
                tectonic_model=tectonic_model,
                tectonic=tectonic,
            )
            if special["volcanic"] and tectonic[0] in {"uncertain", "trailing_passive"}:
                tectonic = ("oceanic_island", tectonic[1], max(tectonic[2], 0.72))
            elif measurements["enclosure_index"] >= 0.72 and tectonic[0] == "trailing_passive":
                tectonic = ("marginal_sea", tectonic[1], tectonic[2])
            ice_loading = special["glacial"]
            tectonic_uplift = 0.7 if tectonic[0] == "collision_active" else (-0.15 if tectonic[0] == "trailing_passive" else 0.1)
            sediment_loading = sediment["river_supply"] * 0.55
            paleoclimate_signal = _paleoclimate_sea_level_signal(
                paleoclimate_map_seed, paleoclimate_eccentricity, paleoclimate_axial_tilt_deg, planetary_centroid,
            )
            relative_index = tectonic_uplift + ice_loading * 0.35 - sediment_loading + paleoclimate_signal
            relative_state = "emergent" if relative_index > 0.34 else ("submergent" if relative_index < -0.18 else "stable")
            primary, secondary, morphology, geologic_characters, forcing, trajectory, confidence, scores = _classify(measurements, tectonic, wave, tide, substrate, sediment, special, river_influence, relative_state)
            beach_state = None
            if substrate == "sand" and forcing == "wave" and primary in {"clastic_beach", "barrier_lagoon"}:
                morphodynamic_index = wave["exposure_index"] * (1.0 - sediment["fractions"]["gravel"])
                beach_state = "reflective" if morphodynamic_index < 0.32 else ("intermediate" if morphodynamic_index < 0.68 else "dissipative")
            non_sandy_shore_state = "gravel_beach" if substrate == "gravel" else ("mudflat" if substrate == "mud" and measurements["nearshore_gradient"] < 0.004 else None)
            stable_source = f"{planet.get('id')}|{component_id}|{offset}|{round(centroid[0], 5)}|{round(centroid[1], 5)}|{COASTAL_MODEL_VERSION}"
            segment_id = "coast_" + hashlib.sha256(stable_source.encode("utf-8")).hexdigest()[:20]
            segments.append({
                "id": segment_id,
                "component_id": f"coast_component_{component_id}",
                "normalized_position": round(offset / max(1, len(chain) - 1), 6),
                "geometry": {"type": "polyline_uv", "points": points, "bbox_uv": [round(min(p[0] for p in points), 6), round(min(p[1] for p in points), 6), round(max(p[0] for p in points), 6), round(max(p[1] for p in points), 6)]},
                "length_km": round(_polyline_length_m(heightmap, points, radius) / 1000.0, 4),
                "measurements": measurements,
                "tectonic_setting": tectonic[0],
                "nearest_tectonic_boundary_kind": tectonic[1],
                "relative_sea_level_state": relative_state,
                "relative_sea_level_drivers": {
                    "tectonic_uplift_proxy": round(tectonic_uplift, 3),
                    "isostatic_ice_influence": round(ice_loading * 0.35, 3),
                    "sediment_loading_subsidence_proxy": round(sediment_loading, 3),
                    "orbital_paleoclimate_signal": round(paleoclimate_signal, 3),
                    "eustatic_history_resolution": "bounded_multi_cycle_orbital_paleoclimate_proxy",
                },
                "shoreline_trajectory": trajectory,
                "substrate": substrate,
                "dominant_forcing": forcing,
                "wave_climate": wave,
                "tidal_regime": tide,
                "sediment_budget": sediment,
                "river_influence": round(river_influence, 3),
                "adjacent_river_id": (river or {}).get("id"),
                "adjacent_ocean_basin_id": f"ocean_basin_{basin_index + 1:02d}" if basin_index >= 0 else None,
                "influences": {
                    "glacial_erosion": round(float(special["glacial"]), 3),
                    "volcanic": bool(special["volcanic"]),
                    "volcanic_influence": special["volcanic_influence"],
                    "carbonate_or_karst": bool(special["carbonate"]),
                    "carbonate_factory_influence": special["carbonate_influence"],
                    "permafrost_or_ice_rich": bool(special["ice_rich"]),
                    "material_erodibility_proxy": 0.18 if substrate == "resistant_bedrock" else (0.42 if substrate in {"erodible_bedrock", "volcanic", "carbonate"} else 0.78),
                },
                "primary_assemblage": primary,
                "secondary_assemblage": secondary,
                "morphology_assemblage": morphology,
                "coastal_system": morphology,
                "geologic_characters": geologic_characters,
                "beach_morphodynamic_state": beach_state,
                "non_sandy_shore_state": non_sandy_shore_state,
                "display_color": ASSEMBLAGE_COLORS.get(morphology, [180, 180, 180]),
                "biogenic_accommodation": {
                    "reef": round(_clamp(special["carbonate"] * (1.0 - special["glacial"]) * (1.0 - storm * 0.45)), 3),
                    "salt_marsh": round(_clamp(sediment["accommodation_index"] * (1.0 - wave["exposure_index"]) * (0.4 + sediment["fractions"]["mud"])), 3),
                    "mangrove": round(_clamp(sediment["accommodation_index"] * (1.0 - wave["exposure_index"]) * (1.0 - latitude / 42.0)), 3),
                    "occupied": False,
                    "requires_biosphere_result": True,
                },
                "confidence": round(confidence, 3),
                "rule_trace": {
                    "classification_scores": {key: round(value, 3) for key, value in scores.items()},
                    "causal_sources": ["evolved_heightfield", "tectonic_model", "climate_grid", "ocean_fetch", "drainage_network", "surface_sediment_budget", "material_affinities", "astronomical_context"],
                    "reduced_physics": True,
                },
            })
    delta_assessments, deltas = _resolve_delta_systems(
        water_cycle,
        segments,
        width=width,
        height=height,
        wrap_x=wrap_x,
    )
    assemblages = Counter(segment.get("morphology_assemblage") or segment["primary_assemblage"] for segment in segments)
    geologic_characters = Counter(
        character
        for segment in segments
        for character in segment.get("geologic_characters") or []
    )
    tidal_classes = Counter(segment["tidal_regime"]["class"] for segment in segments)
    wave_classes = Counter(segment["wave_climate"]["exposure_class"] for segment in segments)
    total_length = sum(segment["length_km"] for segment in segments)
    delta_count = len(deltas)
    estuary_count = sum((segment.get("morphology_assemblage") or segment["primary_assemblage"]) == "estuarine_drowned_valley" for segment in segments)
    source_fingerprint = hashlib.sha256(json.dumps({"heightfield": heightmap.get("source_heightfield_fingerprint"), "water": water_cycle.get("model_version"), "tectonics": tectonic_model.get("model_version"), "planet": planet.get("id")}, sort_keys=True).encode("utf-8")).hexdigest()
    return {
        "status": "coastal_geomorphology_resolved",
        "model_version": COASTAL_MODEL_VERSION,
        "projection": heightmap.get("projection", "equirectangular"),
        "wrap_x": wrap_x,
        "source_heightfield_fingerprint": heightmap.get("source_heightfield_fingerprint"),
        "input_fingerprint": source_fingerprint,
        "shoreline_extraction": "marching_squares_spherical_ordered_chains",
        "chain_orientation": "landward_normal_on_consistent_positive_cross_side",
        "components": component_records,
        "segments": segments,
        "delta_assessments": delta_assessments,
        "deltas": deltas,
        "summary": {
            "segment_count": len(segments),
            "component_count": len(component_records),
            "coastline_length_km": round(total_length, 1),
            "dominant_assemblages": [{"id": key, "segment_count": count, "length_km": round(sum(segment["length_km"] for segment in segments if (segment.get("morphology_assemblage") or segment["primary_assemblage"]) == key), 1)} for key, count in assemblages.most_common(6)],
            "geologic_character_distribution": dict(sorted(geologic_characters.items())),
            "tidal_class_distribution": dict(sorted(tidal_classes.items())),
            "wave_exposure_distribution": dict(sorted(wave_classes.items())),
            "delta_count": delta_count,
            "estuary_count": estuary_count,
            "mean_confidence": round(sum(segment["confidence"] for segment in segments) / max(1, len(segments)), 3),
        },
        "fidelity": {
            "tier": 1,
            "resolved": ["shoreline_topology", "directional_fetch", "wave_exposure_class", "equilibrium_tidal_potential", "relative_sea_level_class", "sediment_source_partition", "river_delta_flux_balance", "delta_planform_end_members", "multiaxial_geomorphic_assemblage"],
            "deferred": ["spectral_wave_transformation", "harmonic_tidal_constituents", "event_resolved_storms", "three_dimensional_sediment_transport", "event_resolved_delta_avulsion"],
        },
    }


def coastal_summary(model):
    if not isinstance(model, dict):
        return {}
    return copy.deepcopy(model.get("summary") or {})


def enrich_coastal_hydrology(water_cycle, coastal_model):
    """Persist flux-balanced deltas and estuaries into the water-cycle model."""
    if not isinstance(water_cycle, dict) or not isinstance(coastal_model, dict):
        return water_cycle
    segments = [segment for segment in coastal_model.get("segments") or [] if isinstance(segment, dict)]

    drainage = water_cycle.get("drainage_network_model") if isinstance(water_cycle.get("drainage_network_model"), dict) else {}
    deltas = list(coastal_model.get("deltas") or [])
    # Upgrade compatibility for saved fixtures from the former flow-only
    # marker model. New generation always supplies coastal_model["deltas"].
    if not deltas:
        deltas = (
            list(drainage.get("deltas") or [])
            if isinstance(drainage.get("deltas"), list)
            else list(water_cycle.get("deltas") or [])
        )
    for delta in deltas:
        segment = _nearest_coastal_segment(
            segments,
            delta.get("center"),
            wrap_x=bool(coastal_model.get("wrap_x", True)),
        )
        if segment is None:
            continue
        strengths = {
            "river_dominated": float(segment.get("river_influence", 0.0) or 0.0),
            "wave_dominated": float((segment.get("wave_climate") or {}).get("transport_capacity_index", 0.0) or 0.0),
            "tide_dominated": _clamp(float((segment.get("tidal_regime") or {}).get("estimated_range_m", 0.0) or 0.0) / 5.0),
        }
        dominance = max(strengths, key=strengths.get)
        delta.update({
            "coastal_segment_id": (
                delta.get("coastal_segment_id") or segment.get("id")
            ),
            "marine_reworking_end_member": (
                delta.get("marine_reworking_end_member") or dominance
            ),
            "forcing_strengths": (
                delta.get("forcing_strengths")
                or {key: round(value, 3) for key, value in strengths.items()}
            ),
            "shoreline_trajectory": segment.get("shoreline_trajectory"),
            "substrate": segment.get("substrate"),
            "classification_confidence": segment.get("confidence"),
        })
    estuaries = [
        {
            "id": f"estuary_{index + 1:03d}",
            "coastal_segment_id": segment.get("id"),
            "center": {"x": (segment.get("measurements") or {}).get("centroid_uv", [0.0, 0.5])[0], "y": (segment.get("measurements") or {}).get("centroid_uv", [0.0, 0.5])[1]},
            "adjacent_river_id": segment.get("adjacent_river_id"),
            "relative_sea_level_state": segment.get("relative_sea_level_state"),
            "tidal_class": (segment.get("tidal_regime") or {}).get("class"),
            "wave_exposure_class": (segment.get("wave_climate") or {}).get("exposure_class"),
            "classification_confidence": segment.get("confidence"),
        }
        for index, segment in enumerate(segments)
        if (segment.get("morphology_assemblage") or segment.get("primary_assemblage")) == "estuarine_drowned_valley"
    ]
    if drainage:
        drainage["deltas"] = deltas
        drainage["delta_count"] = len(deltas)
        drainage["delta_assessments"] = list(
            coastal_model.get("delta_assessments") or []
        )
        drainage["estuaries"] = estuaries
        drainage["estuary_count"] = len(estuaries)
    water_cycle["deltas"] = deltas
    water_cycle["delta_count"] = len(deltas)
    water_cycle["delta_assessments"] = list(
        coastal_model.get("delta_assessments") or []
    )
    water_cycle["estuaries"] = estuaries
    water_cycle["estuary_count"] = len(estuaries)
    summary = (
        coastal_model.get("summary")
        if isinstance(coastal_model.get("summary"), dict)
        else {}
    )
    summary["delta_count"] = len(deltas)
    summary["estuary_count"] = len(estuaries)
    coastal_model["summary"] = summary
    return water_cycle


def ensure_coastal_model_current(planet, *, star=None, satellites=None, inherited_sea_level_m=None):
    """Upgrade stale saved-world derivatives without changing parent truth."""
    if not isinstance(planet, dict) or not isinstance(planet.get("heightmap_model"), dict):
        return False
    changed = False
    heightmap = planet["heightmap_model"]
    if not heightmap_derivatives_are_current(heightmap):
        heightmap = refresh_heightmap_derivatives(
            heightmap,
            tectonic_model=planet.get("tectonic_model"),
            inherited_sea_level_m=inherited_sea_level_m,
        )
        planet["heightmap_model"] = heightmap
        changed = True
    existing = planet.get("coastal_geomorphology_model") if isinstance(planet.get("coastal_geomorphology_model"), dict) else {}
    coastal_stale = (
        existing.get("model_version") != COASTAL_MODEL_VERSION
        or existing.get("source_heightfield_fingerprint") != heightmap.get("source_heightfield_fingerprint")
    )
    if coastal_stale and isinstance(planet.get("water_cycle_model"), dict):
        coastal_context = dict(planet)
        if satellites is not None:
            coastal_context["satellites"] = [dict(item) for item in satellites if isinstance(item, dict)]
        model = derive_coastal_geomorphology_model(
            planet=coastal_context,
            heightmap=heightmap,
            water_cycle=planet.get("water_cycle_model"),
            tectonic_model=planet.get("tectonic_model"),
            surface_evolution=planet.get("surface_evolution_model"),
            star=star,
        )
        planet["coastal_geomorphology_model"] = model
        planet["coastal_summary"] = coastal_summary(model)
        enrich_coastal_hydrology(planet["water_cycle_model"], model)
        changed = True
    material_model = planet.get("material_heatmap_model")
    if (
        isinstance(material_model, dict)
        and material_model.get("status") == "generated"
        and material_model.get("source_heightfield_fingerprint") != heightmap.get("source_heightfield_fingerprint")
    ):
        material_model["derivation_status"] = "stale_source_heightfield"
        changed = True
    return changed


def inherit_parent_coastal_context(coastal_model, parent_model):
    """Keep coastal-system identity stable while allowing compatible local facies."""
    if not isinstance(coastal_model, dict) or not isinstance(parent_model, dict):
        return coastal_model
    parents = [segment for segment in parent_model.get("segments") or [] if isinstance(segment, dict)]
    if not parents:
        return coastal_model
    depositional = {
        "clastic_beach", "barrier_lagoon", "deltaic",
        "estuarine_drowned_valley", "tidal_flat_accommodation",
    }
    erosional = {"rocky_cliff", "headland_bay", "emergent_marine_terrace"}

    def family(value):
        if value in depositional:
            return "depositional"
        if value in erosional:
            return "erosional"
        if value == "glacial_fjord_fjard_skerry":
            return "glacial"
        return "other"

    for segment in coastal_model.get("segments") or []:
        centroid = (segment.get("measurements") or {}).get("planetary_centroid_uv")
        if not centroid:
            continue
        parent = min(
            parents,
            key=lambda item: _wrapped_uv_distance(
                centroid,
                (item.get("measurements") or {}).get("planetary_centroid_uv")
                or (item.get("measurements") or {}).get("centroid_uv")
                or [0.5, 0.5],
            ),
        )
        parent_morphology = str(
            parent.get("morphology_assemblage")
            or parent.get("primary_assemblage")
            or "headland_bay"
        )
        local_morphology = str(
            segment.get("morphology_assemblage")
            or segment.get("primary_assemblage")
            or parent_morphology
        )
        segment["local_morphology_assemblage"] = local_morphology
        locally_resolved_delta = (
            local_morphology == "deltaic"
            and bool(segment.get("delta_id"))
        )
        if locally_resolved_delta:
            segment["scale_consistency"] = (
                "locally_resolved_delta_retained_from_sediment_budget"
            )
        elif family(local_morphology) != family(parent_morphology):
            segment["morphology_assemblage"] = parent_morphology
            segment["scale_consistency"] = "parent_morphology_retained_over_incompatible_local_class"
        else:
            segment["scale_consistency"] = "compatible_local_facies"
        segment["coastal_system"] = (
            "deltaic"
            if locally_resolved_delta
            else str(parent.get("coastal_system") or parent_morphology)
        )
        segment["parent_segment_id"] = parent.get("id")
        segment["display_color"] = ASSEMBLAGE_COLORS.get(
            segment.get("morphology_assemblage"),
            segment.get("display_color") or [180, 180, 180],
        )
    return coastal_model


def stabilize_regional_coastal_topology(heightmap, *, detail_level=1):
    """Remove sub-terrain-scale shoreline noise while preserving patch edges."""
    if not isinstance(heightmap, dict) or int(detail_level or 0) < 4:
        return heightmap, {"status": "not_applied", "flipped_cell_count": 0}
    grid = heightmap.get("sample_grid") or {}
    rows = grid.get("rows") or []
    sea = heightmap.get("sea_level_m")
    if not rows or not rows[0] or sea is None:
        return heightmap, {"status": "not_applicable", "flipped_cell_count": 0}
    values = [list(map(float, row)) for row in rows]
    height, width = len(values), min(len(row) for row in values)
    wrap_x = bool(grid.get("wrap_x", heightmap.get("wrap_x", False)))
    unique_width = width - 1 if wrap_x and width > 1 else width
    total_flips = 0
    majority_flips = 0
    component_flips = 0
    level = int(detail_level or 0)
    spacing_x = max(0.001, float(heightmap.get("sample_spacing_x_m") or 1.0))
    spacing_y = max(0.001, float(heightmap.get("sample_spacing_y_m") or spacing_x))
    cell_area_m2 = spacing_x * spacing_y
    minimum_width_m = MIN_COASTAL_TERRAIN_FEATURE_WIDTH_M if level >= 6 else max(
        min(spacing_x, spacing_y) * 1.5,
        MIN_COASTAL_TERRAIN_FEATURE_WIDTH_M,
    )
    minimum_component_area_m2 = math.pi * (minimum_width_m * 0.5) ** 2
    minimum_component_cells = max(2, int(math.ceil(minimum_component_area_m2 / cell_area_m2)))
    neighbourhood_radius = max(
        1,
        min(3, int(math.ceil((minimum_width_m * 0.5) / max(spacing_x, spacing_y)))),
    )
    passes = 1 if level == 4 else 2
    epsilon = max(0.005, min(0.05, spacing_x * 0.08))

    def replacement_elevation(x, y, becomes_land):
        """Change topology without flattening every corrected cell to one datum."""
        desired_offsets = []
        for radius in (1, 2):
            for dy in range(-radius, radius + 1):
                for dx in range(-radius, radius + 1):
                    if not (dx or dy):
                        continue
                    xx, yy = x + dx, y + dy
                    if wrap_x:
                        xx %= unique_width
                    if xx < 0 or xx >= unique_width or yy < 0 or yy >= height:
                        continue
                    neighbour = float(values[yy][xx])
                    if (neighbour >= float(sea)) == becomes_land:
                        desired_offsets.append(abs(neighbour - float(sea)))
            if desired_offsets:
                break
        old_offset = max(epsilon, abs(float(values[y][x]) - float(sea)))
        if desired_offsets:
            desired_offsets.sort()
            neighbour_offset = max(epsilon, desired_offsets[len(desired_offsets) // 2])
            old_offset = math.sqrt(old_offset * neighbour_offset)
        sign = 1.0 if becomes_land else -1.0
        return float(sea) + sign * max(epsilon, old_offset)

    for _pass in range(passes):
        land = [[values[y][x] >= float(sea) for x in range(unique_width)] for y in range(height)]
        flips = []
        radius = neighbourhood_radius
        for y in range(radius, height - radius):
            for x in range(radius, unique_width - radius):
                neighbours = [
                    land[y + dy][x + dx]
                    for dy in range(-radius, radius + 1)
                    for dx in range(-radius, radius + 1)
                    if dx or dy
                ]
                same = sum(value == land[y][x] for value in neighbours)
                if same / max(1, len(neighbours)) <= 0.28:
                    flips.append((x, y, not land[y][x]))
                elif land[y][x] and sum(neighbours) <= len(neighbours) * 0.22:
                    flips.append((x, y, False))
                elif not land[y][x] and sum(neighbours) >= len(neighbours) * 0.78:
                    flips.append((x, y, True))
        if not flips:
            break
        for x, y, becomes_land in flips:
            values[y][x] = replacement_elevation(x, y, becomes_land)
        total_flips += len(flips)
        majority_flips += len(flips)

    def components(mask, target):
        seen = [[False for _x in range(unique_width)] for _y in range(height)]
        found = []
        for start_y in range(height):
            for start_x in range(unique_width):
                if seen[start_y][start_x] or mask[start_y][start_x] != target:
                    continue
                cells = []
                touches_edge = False
                queue = deque([(start_x, start_y)])
                seen[start_y][start_x] = True
                while queue:
                    x, y = queue.popleft()
                    cells.append((x, y))
                    touches_edge = touches_edge or x == 0 or y == 0 or x == unique_width - 1 or y == height - 1
                    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                        xx, yy = x + dx, y + dy
                        if wrap_x:
                            xx %= unique_width
                        if xx < 0 or xx >= unique_width or yy < 0 or yy >= height:
                            continue
                        if not seen[yy][xx] and mask[yy][xx] == target:
                            seen[yy][xx] = True
                            queue.append((xx, yy))
                found.append((cells, touches_edge))
        return found

    land = [[values[y][x] >= float(sea) for x in range(unique_width)] for y in range(height)]
    for target in (False, True):
        target_components = components(land, target)
        for cells, touches_edge in target_components:
            if touches_edge or len(cells) >= minimum_component_cells:
                continue
            replacement = not target
            for x, y in cells:
                values[y][x] = replacement_elevation(x, y, replacement)
                land[y][x] = replacement
            total_flips += len(cells)
            component_flips += len(cells)

    resulting_land_components = len(components(land, True))
    resulting_water_components = len(components(land, False))
    audit = {
        "status": "subresolution_coastal_speckle_removed" if total_flips else "already_stable",
        "model_version": COASTAL_MODEL_VERSION,
        "flipped_cell_count": total_flips,
        "majority_flipped_cell_count": majority_flips,
        "component_flipped_cell_count": component_flips,
        "passes": passes,
        "edge_cells_preserved": True,
        "minimum_resolved_vertical_offset_m": round(epsilon, 4),
        "minimum_resolved_feature_width_m": round(minimum_width_m, 3),
        "minimum_component_area_m2": round(minimum_component_area_m2, 4),
        "minimum_component_cells": minimum_component_cells,
        "resulting_land_components": resulting_land_components,
        "resulting_water_components": resulting_water_components,
    }
    if not total_flips:
        return heightmap, audit
    changed = dict(heightmap)
    changed["sample_grid"] = {
        **grid,
        "rows": [[round(value, 3) for value in row] for row in values],
    }
    changed["coastal_topology_stabilization"] = audit
    return changed, dict(changed["coastal_topology_stabilization"])


def _squared_distance_transform_1d(values, spacing):
    """Exact squared Euclidean distance and nearest source for one grid axis."""
    coefficient = max(1e-12, float(spacing) ** 2)
    finite = [index for index, value in enumerate(values) if math.isfinite(value)]
    if not finite:
        return [math.inf] * len(values), [-1] * len(values)
    envelope = [finite[0]]
    boundaries = [-math.inf, math.inf]
    for candidate in finite[1:]:
        while envelope:
            previous = envelope[-1]
            crossing = (
                (float(values[candidate]) + coefficient * candidate * candidate)
                - (float(values[previous]) + coefficient * previous * previous)
            ) / (2.0 * coefficient * (candidate - previous))
            if crossing > boundaries[len(envelope) - 1]:
                break
            envelope.pop()
            boundaries.pop()
        if not envelope:
            envelope = [candidate]
            boundaries = [-math.inf, math.inf]
        else:
            boundaries[-1] = crossing
            envelope.append(candidate)
            boundaries.append(math.inf)
    distances = []
    nearest = []
    envelope_index = 0
    for index in range(len(values)):
        while (
            envelope_index + 1 < len(envelope)
            and boundaries[envelope_index + 1] < index
        ):
            envelope_index += 1
        source = envelope[envelope_index]
        distances.append(float(values[source]) + coefficient * (index - source) ** 2)
        nearest.append(source)
    return distances, nearest


def _shoreline_euclidean_distance_field(
    shoreline_rows,
    shoreline_morphology_rows,
    spacing_x,
    spacing_y,
):
    """Return exact physical distance and nearest shoreline morphology per cell."""
    height = len(shoreline_rows)
    width = len(shoreline_rows[0]) if height else 0
    horizontal_distance = [[math.inf for _x in range(width)] for _y in range(height)]
    horizontal_source_x = [[-1 for _x in range(width)] for _y in range(height)]
    for y in range(height):
        values = [0.0 if shoreline_rows[y][x] else math.inf for x in range(width)]
        horizontal_distance[y], horizontal_source_x[y] = _squared_distance_transform_1d(
            values, spacing_x,
        )

    distance_rows = [[math.inf for _x in range(width)] for _y in range(height)]
    morphology_rows = [[None for _x in range(width)] for _y in range(height)]
    for x in range(width):
        vertical_values = [horizontal_distance[y][x] for y in range(height)]
        squared_distances, nearest_y = _squared_distance_transform_1d(
            vertical_values, spacing_y,
        )
        for y in range(height):
            source_y = nearest_y[y]
            if source_y < 0:
                continue
            source_x = horizontal_source_x[source_y][x]
            if source_x < 0:
                continue
            distance_rows[y][x] = math.sqrt(max(0.0, squared_distances[y]))
            morphology_rows[y][x] = shoreline_morphology_rows[source_y][source_x]
    return distance_rows, morphology_rows


def materialize_regional_coastal_landforms(heightmap, coastal_model, *, detail_level=1):
    """Apply conservative, parent-conditioned coastal relief at regional LOD."""
    if not isinstance(heightmap, dict) or not isinstance(coastal_model, dict) or int(detail_level or 0) < 1:
        return heightmap, {"status": "not_applied", "drainage_reconciliation_required": False}
    segments = coastal_model.get("segments") or []
    grid = heightmap.get("sample_grid") or {}
    rows = grid.get("rows") or []
    sea = heightmap.get("sea_level_m")
    if not rows or not rows[0] or sea is None or not segments:
        return heightmap, {"status": "not_applicable", "drainage_reconciliation_required": False}
    changed = copy.deepcopy(heightmap)
    original_rows = [list(map(float, row)) for row in rows]
    changed_rows = [list(row) for row in original_rows]
    height, width = len(changed_rows), min(len(row) for row in changed_rows)
    wrap_x = bool(grid.get("wrap_x", heightmap.get("wrap_x", False)))
    unique_width = width - 1 if wrap_x and width > 1 else width
    modified_cells = set()
    feature_gates = {
        "rocky_cliff": {
            1: ["cliff_belts", "headlands", "embayments"],
            2: ["rocky_shore_platforms", "pocket_beaches"],
            3: ["shore_platforms", "stacks", "talus_contacts"],
            4: ["cliff_toes", "wave_cut_notches", "intertidal_platforms"],
            5: ["bedrock_steps", "drainage_grooves"],
            6: ["erosion_rills"],
            7: ["tide_pool_basins", "microdrainage_hollows"],
        },
        "headland_bay": {
            1: ["headlands", "embayments"],
            2: ["pocket_beaches", "rocky_shore_platforms"],
            3: ["shore_platforms", "talus_contacts"],
            4: ["cliff_toes", "wave_cut_notches"],
            5: ["bedrock_steps", "drainage_grooves"],
            6: ["erosion_rills"],
            7: ["tide_pool_basins", "microdrainage_hollows"],
        },
        "emergent_marine_terrace": {
            1: ["raised_coastal_belts", "headlands"],
            2: ["marine_terraces", "raised_shorelines"],
            3: ["terrace_treads", "terrace_risers", "shore_platforms"],
            4: ["cliff_toes", "wave_cut_notches", "intertidal_platforms"],
            5: ["bedrock_steps", "drainage_grooves"],
            6: ["erosion_rills"],
            7: ["tide_pool_basins", "microdrainage_hollows"],
        },
        "glacial_fjord_fjard_skerry": {
            1: ["fjord_troughs", "skerry_fields"],
            2: ["hanging_valleys", "rocky_shore_platforms"],
            3: ["cliff_belts", "talus_contacts"],
            4: ["cliff_toes", "intertidal_platforms"],
            5: ["bedrock_steps", "drainage_grooves"],
            6: ["erosion_rills"],
            7: ["tide_pool_basins", "microdrainage_hollows"],
        },
        "clastic_beach": {
            1: ["beach_belts", "embayments"],
            2: ["beaches", "spits", "tombolos", "inlets"],
            3: ["berms", "bar_trough_systems", "dune_ridges"],
            4: ["beachface_backshore_breaks"],
            5: ["beach_cusps", "swash_bars"],
            6: ["swash_runnels", "berm_microtopography"],
            7: ["microdrainage_hollows"],
        },
        "barrier_lagoon": {
            1: ["barrier_chains", "lagoons"],
            2: ["spits", "inlets", "dunes"],
            3: ["berms", "bar_trough_systems", "washover_fans", "dune_ridges"],
            4: ["beachface_backshore_breaks", "tidal_channel_cross_sections"],
            5: ["beach_cusps", "swash_bars", "lagoon_margin_microrelief"],
            6: ["swash_runnels", "berm_microtopography"],
            7: ["microdrainage_hollows"],
        },
        "deltaic": {
            1: ["delta_lobes"],
            2: ["distributaries", "inlets", "wetlands"],
            3: ["tidal_creeks", "natural_levees"],
            4: ["tidal_channel_cross_sections"],
            5: ["channel_bars", "lagoon_margin_microrelief"],
            6: ["swash_runnels", "microchannels"],
            7: ["microdrainage_hollows"],
        },
        "estuarine_drowned_valley": {
            1: ["drowned_valleys", "embayments"],
            2: ["inlets", "tidal_flats"],
            3: ["tidal_creeks", "shore_platforms"],
            4: ["tidal_channel_cross_sections"],
            5: ["lagoon_margin_microrelief"],
            6: ["microchannels"],
            7: ["microdrainage_hollows"],
        },
        "tidal_flat_accommodation": {
            1: ["tidal_flats"],
            2: ["inlets", "wetlands"],
            3: ["tidal_creeks"],
            4: ["tidal_channel_cross_sections"],
            5: ["lagoon_margin_microrelief"],
            6: ["microchannels"],
            7: ["microdrainage_hollows"],
        },
    }
    deferred_object_detail = [
        "loose_rocks",
        "boulders",
        "clasts",
        "debris_and_wrack",
        "individual_vegetation",
        "shells_and_organic_remains",
        "joint_and_fissure_surface_meshes",
        "organism_scale_microhabitats",
    ]
    spacing_x = max(0.001, float(heightmap.get("sample_spacing_x_m") or 1.0))
    spacing_y = max(0.001, float(heightmap.get("sample_spacing_y_m") or spacing_x))
    footprint_m = max(
        spacing_x * max(1, unique_width - 1),
        spacing_y * max(1, height - 1),
    )
    profiles = {
        "rocky_cliff": {"width": min(footprint_m * 0.42, 160.0), "land_slope": 0.72, "sea_slope": 0.08, "relief": min(30.0, footprint_m * 0.22)},
        "headland_bay": {"width": min(footprint_m * 0.38, 180.0), "land_slope": 0.38, "sea_slope": 0.045, "relief": min(22.0, footprint_m * 0.22)},
        "clastic_beach": {"width": min(footprint_m * 0.46, 320.0), "land_slope": 0.065, "sea_slope": 0.025, "relief": min(4.0, footprint_m * 0.08)},
        "barrier_lagoon": {"width": min(footprint_m * 0.46, 650.0), "land_slope": 0.025, "sea_slope": 0.012, "relief": min(3.5, footprint_m * 0.06)},
        "deltaic": {"width": min(footprint_m * 0.48, 1_600.0), "land_slope": 0.008, "sea_slope": 0.004, "relief": min(2.5, footprint_m * 0.035)},
        "estuarine_drowned_valley": {"width": min(footprint_m * 0.44, 700.0), "land_slope": 0.035, "sea_slope": 0.015, "relief": min(6.0, footprint_m * 0.10)},
        "tidal_flat_accommodation": {"width": min(footprint_m * 0.48, 1_000.0), "land_slope": 0.003, "sea_slope": 0.002, "relief": min(1.2, footprint_m * 0.018)},
        "glacial_fjord_fjard_skerry": {"width": min(footprint_m * 0.35, 180.0), "land_slope": 0.65, "sea_slope": 0.12, "relief": min(28.0, footprint_m * 0.28)},
        "emergent_marine_terrace": {"width": min(footprint_m * 0.46, 250.0), "land_slope": 0.45, "sea_slope": 0.09, "relief": min(18.0, footprint_m * 0.32)},
    }
    shoreline_rows = [[False for _x in range(unique_width)] for _y in range(height)]
    shoreline_morphology_rows = [[None for _x in range(unique_width)] for _y in range(height)]
    for segment in segments:
        assemblage = str(
            segment.get("coastal_system")
            or segment.get("morphology_assemblage")
            or segment.get("primary_assemblage")
            or ""
        )
        if assemblage not in profiles:
            continue
        previous = None
        for u, v in (segment.get("geometry") or {}).get("points") or []:
            raw_x = int(round(float(u) * max(1, unique_width - 1)))
            x = raw_x % unique_width if wrap_x else max(0, min(unique_width - 1, raw_x))
            y = max(0, min(height - 1, int(round(float(v) * (height - 1)))))
            if previous is None:
                line_cells = [(x, y)]
            else:
                dx = x - previous[0]
                if wrap_x and abs(dx) > unique_width * 0.5:
                    dx -= int(math.copysign(unique_width, dx))
                dy = y - previous[1]
                steps = max(1, abs(dx), abs(dy))
                line_cells = [
                    (
                        (previous[0] + int(round(dx * step / steps))) % unique_width,
                        max(0, min(height - 1, previous[1] + int(round(dy * step / steps)))),
                    )
                    for step in range(steps + 1)
                ]
            for xx, yy in line_cells:
                shoreline_rows[yy][xx] = True
                shoreline_morphology_rows[yy][xx] = assemblage
            previous = (x, y)

    distance_rows, morphology_rows = _shoreline_euclidean_distance_field(
        shoreline_rows,
        shoreline_morphology_rows,
        spacing_x,
        spacing_y,
    )

    maximum_adjustment = 0.0
    for y in range(height):
        for x in range(unique_width):
            assemblage = morphology_rows[y][x]
            if assemblage not in profiles:
                continue
            profile = profiles[assemblage]
            distance_m = distance_rows[y][x]
            if not math.isfinite(distance_m) or distance_m > profile["width"]:
                continue
            old = original_rows[y][x]
            # Marching-squares points lie between source cells. Rasterized
            # zero-distance seeds are therefore not samples exactly at the
            # waterline; retaining them avoids a dotted, datum-flat contour.
            if distance_m < min(spacing_x, spacing_y) * 0.55:
                continue
            land = old >= float(sea)
            if land:
                target = float(sea) + min(profile["relief"], distance_m * profile["land_slope"])
            else:
                target = float(sea) - min(profile["relief"] * 0.55, distance_m * profile["sea_slope"])
            if int(detail_level or 0) >= 5 and land:
                x_m = x * spacing_x
                y_m = y * spacing_y
                minimum_wavelength = max(MIN_COASTAL_TERRAIN_FEATURE_WIDTH_M, max(spacing_x, spacing_y) * 4.0)
                if assemblage in {"clastic_beach", "barrier_lagoon", "deltaic", "tidal_flat_accommodation"}:
                    wavelength = max(minimum_wavelength, min(8.0, footprint_m * 0.10))
                    secondary = max(minimum_wavelength, wavelength * 1.7)
                    coherent_runnels = (
                        math.sin(math.tau * (x_m * 0.22 + y_m * 0.05) / wavelength) * 0.68
                        + math.sin(math.tau * (-x_m * 0.08 + y_m * 0.24) / secondary) * 0.32
                    )
                    target += coherent_runnels * min(0.12, profile["relief"] * 0.035)
                elif assemblage == "emergent_marine_terrace":
                    tread_spacing = max(minimum_wavelength, min(8.0, footprint_m * 0.16))
                    tread = max(0.0, math.sin(math.tau * distance_m / tread_spacing)) ** 4
                    target += tread * min(0.14, profile["relief"] * 0.03)
            scale_blend = 0.30 if int(detail_level or 0) <= 2 else (0.62 if int(detail_level or 0) == 3 else 0.90)
            distance_fade = _clamp(1.0 - distance_m / max(0.001, profile["width"]))
            edge_cells = min(x, unique_width - 1 - x, y, height - 1 - y)
            edge_blend_cells = max(8.0, min(unique_width, height) * 0.08)
            edge_fade = _clamp(edge_cells / edge_blend_cells)
            edge_fade = edge_fade * edge_fade * (3.0 - 2.0 * edge_fade)
            blend = scale_blend * (0.35 + distance_fade * 0.65) * edge_fade
            value = old + (target - old) * blend
            delta = value - old
            if abs(delta) > 0.005:
                changed_rows[y][x] = value
                modified_cells.add((x, y))
                maximum_adjustment = max(maximum_adjustment, abs(delta))
    sediment_delta_before_correction = sum(
        changed_rows[y][x] - original_rows[y][x]
        for x, y in modified_cells
    )
    conservation_correction = sediment_delta_before_correction / max(1, len(modified_cells))
    for x, y in modified_cells:
        changed_rows[y][x] -= conservation_correction
    sediment_delta = sum(changed_rows[y][x] - original_rows[y][x] for x, y in modified_cells)
    modified = len(modified_cells)
    if unique_width < width:
        for row in changed_rows:
            row[-1] = row[0]
    active_assemblages = {
        str(
            segment.get("coastal_system")
            or segment.get("morphology_assemblage")
            or segment.get("primary_assemblage")
            or ""
        )
        for segment in segments
    }
    resolved_feature_families = sorted({
        feature
        for assemblage in active_assemblages
        for gate, features in (feature_gates.get(assemblage) or {}).items()
        if int(detail_level or 0) >= gate
        for feature in features
    })
    changed["sample_grid"] = {**grid, "rows": [[round(value, 2) for value in row] for row in changed_rows]}
    changed["coastal_landform_refinement"] = {
        "status": "regional_coastal_landforms_materialized" if modified else "not_applied",
        "model_version": COASTAL_MODEL_VERSION,
        "modified_cell_samples": modified,
        "net_resolved_elevation_delta_m": round(sediment_delta, 3),
        "preconservation_elevation_delta_m": round(sediment_delta_before_correction, 3),
        "maximum_vertical_adjustment_m": round(maximum_adjustment, 3),
        "profile_amplitudes_scaled_to_physical_footprint": True,
        "morphology_and_geologic_character_separated": True,
        "sediment_conservation_tolerance_m": 0.01,
        "sediment_budget_conserved": abs(sediment_delta) <= 0.01,
        "edge_detail_fades_to_parent": True,
        "resolved_feature_families": resolved_feature_families,
        "active_coastal_assemblages": sorted(active_assemblages),
        "minimum_heightfield_feature_width_m": MIN_COASTAL_TERRAIN_FEATURE_WIDTH_M,
        "deferred_object_detail_families": deferred_object_detail if int(detail_level or 0) >= 6 else [],
        "object_detail_policy": "sparse_objects_not_heightfield" if int(detail_level or 0) >= 6 else "not_active_at_this_scale",
        "drainage_reconciliation_required": bool(modified),
    }
    return changed, changed["coastal_landform_refinement"]
