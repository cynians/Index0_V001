"""Scale-aware watershed, lake, and branching river-network generation."""

import heapq
import math
from collections import defaultdict, deque


MODEL_VERSION = "watershed-drainage-v5"


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, float(value)))


def _neighbors(width, height, x, y, wrap_x):
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            nx, ny = x + dx, y + dy
            if wrap_x:
                nx %= width
            if 0 <= nx < width and 0 <= ny < height:
                yield nx, ny


def _priority_flood(rows, ocean_mask, wrap_x):
    height, width = len(rows), len(rows[0])
    filled = [[float(value or 0.0) for value in row[:width]] for row in rows]
    parent, visited, heap, visit_order = {}, set(), [] , []
    relief_span = max(1.0, max(max(row) for row in filled) - min(min(row) for row in filled))
    flat_epsilon = max(1e-5, relief_span * 1e-8)

    def seed(x, y):
        if (x, y) in visited:
            return
        visited.add((x, y))
        heapq.heappush(heap, (filled[y][x], y, x))
        parent[(x, y)] = None

    for y in range(height):
        for x in range(width):
            if ocean_mask[y][x]:
                seed(x, y)
    # A global equirectangular grid has no open north/south edge: the first and
    # last rows represent polar caps, not places where rivers may leave the map.
    # Regional, non-wrapping grids still use their complete boundary as an outlet.
    if not wrap_x:
        for x in range(width):
            seed(x, 0)
            seed(x, height - 1)
        for y in range(height):
            seed(0, y)
            seed(width - 1, y)
    if not heap:
        # Oceanless global worlds drain to their lowest closed basin instead of
        # inventing outlets at the poles.
        minimum = min((filled[y][x], x, y) for y in range(height) for x in range(width))
        seed(minimum[1], minimum[2])

    while heap:
        spill_height, y, x = heapq.heappop(heap)
        visit_order.append((x, y))
        for nx, ny in _neighbors(width, height, x, y, wrap_x):
            if (nx, ny) in visited:
                continue
            visited.add((nx, ny))
            parent[(nx, ny)] = (x, y)
            original_height = filled[ny][nx]
            filled[ny][nx] = original_height if original_height > spill_height else spill_height + flat_epsilon
            heapq.heappush(heap, (filled[ny][nx], ny, nx))
    return filled, parent, visit_order


def _channel_morphology(path, rows, width, height, cell_spacing_m, flow, stream_order):
    relief_span = max(1.0, max(max(row) for row in rows) - min(min(row) for row in rows))
    drops = []
    confinement_samples = []
    for (x0, y0), (x1, y1) in zip(path, path[1:]):
        distance_cells = max(1.0, math.hypot(x1 - x0, y1 - y0))
        drops.append(max(0.0, float(rows[y0][x0]) - float(rows[y1][x1])) / distance_cells)
    stride = max(1, len(path) // 24)
    for x, y in path[::stride]:
        channel_elevation = float(rows[y][x])
        shoulders = [
            float(rows[ny][nx])
            for nx, ny in _neighbors(width, height, x, y, False)
            if (nx, ny) not in path
        ]
        if shoulders:
            confinement_samples.append(max(0.0, sum(shoulders) / len(shoulders) - channel_elevation))
    mean_drop_m = sum(drops) / max(1, len(drops))
    gradient = mean_drop_m / max(1.0, cell_spacing_m)
    confinement = _clamp(
        (sum(confinement_samples) / max(1, len(confinement_samples)))
        / max(2.0, relief_span * 0.018)
    )
    steepness = _clamp((gradient - 0.0015) / 0.012)
    lowland = _clamp((0.006 - gradient) / 0.006)
    discharge = _clamp(flow)
    order_factor = _clamp((max(1, int(stream_order)) - 1) / 3.0)
    meander_potential = lowland * (0.22 + discharge * 0.78) * (0.38 + order_factor * 0.62) * (1.0 - confinement * 0.82)
    wandering_potential = lowland * discharge * (0.35 + steepness * 0.65) * (1.0 - confinement * 0.55)
    if steepness > 0.52 or confinement > 0.62:
        pattern = "confined_straight"
        sinuosity = 0.03 + (1.0 - steepness) * 0.08
    elif meander_potential > 0.42:
        pattern = "meandering"
        sinuosity = 0.20 + meander_potential * 0.82
    elif wandering_potential > 0.30:
        pattern = "wandering"
        sinuosity = 0.12 + wandering_potential * 0.42
    else:
        pattern = "low_sinuosity"
        sinuosity = 0.06 + meander_potential * 0.24
    # Braiding is a depositional exception, not a general-purpose visual
    # flourish. We record only a candidate here; actual distributaries remain
    # confined to deltas until a sediment-load solver can support braiding.
    braid_candidate = bool(
        discharge > 0.72
        and 0.001 <= gradient <= 0.009
        and confinement < 0.28
        and wandering_potential > 0.38
    )
    path_cells = max(1.0, float(len(path) - 1))
    # Even confined bedrock rivers inherit joints, resistant outcrops, and
    # small tributary deflections. This short-scale irregularity is separate
    # from floodplain meandering and prevents exact ruler lines.
    reach_length_factor = _clamp((path_cells - 3.0) / 8.0)
    terrain_irregularity = (0.28 - steepness * 0.10) * (0.65 + (1.0 - confinement) * 0.35)
    meander_amplitude = (0.16 + path_cells * 0.016) * meander_potential
    amplitude_cells = min(1.25, (terrain_irregularity + meander_amplitude) * reach_length_factor)
    if path_cells < 5.0:
        pattern = "junction_segment"
    wavelength_cells = max(
        5.0,
        min(24.0, 5.5 + (1.0 - steepness) * 3.0 + discharge * 7.0 + order_factor * 6.0),
    )
    return {
        "pattern": pattern,
        "gradient_m_per_m": round(gradient, 7),
        "confinement_index": round(confinement, 4),
        "meander_potential": round(meander_potential, 4),
        "sinuosity_amplitude_cells": round(amplitude_cells, 4),
        "meander_wavelength_cells": round(wavelength_cells, 3),
        "braid_candidate": braid_candidate,
        "divergence_allowed": False,
        "render_width_px": 2 if stream_order >= 3 and discharge >= 0.62 and path_cells >= 6.0 else 1,
    }


def _smoothed_channel_points(
    path, width, height, wrap_x, *, amplitude_cells=0.0, wavelength_cells=12.0,
):
    """Return a terrain-faithful, gently sinuous display polyline.

    The drainage truth remains the D8 cell path.  Sub-cell sinuosity prevents
    long diagonal tributaries from reading as ruler-straight vectors without
    moving them out of the incised channel-and-bank footprint.
    """
    if len(path) < 2:
        return []
    unwrapped = []
    previous_x = float(path[0][0])
    unwrapped.append((previous_x, float(path[0][1])))
    for x, y in path[1:]:
        candidate_x = float(x)
        if wrap_x:
            while candidate_x - previous_x > width * 0.5:
                candidate_x -= width
            while previous_x - candidate_x > width * 0.5:
                candidate_x += width
        unwrapped.append((candidate_x, float(y)))
        previous_x = candidate_x

    points = unwrapped
    # Two restrained Chaikin passes make channels visually continuous while
    # retaining their drainage-cell route and exact confluence endpoints.
    for _pass in range(2):
        refined = [points[0]]
        for first, second in zip(points, points[1:]):
            refined.append((first[0] * 0.75 + second[0] * 0.25, first[1] * 0.75 + second[1] * 0.25))
            refined.append((first[0] * 0.25 + second[0] * 0.75, first[1] * 0.25 + second[1] * 0.75))
        refined.append(points[-1])
        points = refined
    if len(points) > 3:
        phase = ((path[0][0] * 37 + path[0][1] * 61 + path[-1][0] * 17 + path[-1][1] * 29) % 97) / 97.0 * math.tau
        path_cells = max(1.0, float(len(path) - 1))
        wavelength = max(4.0, float(wavelength_cells or 12.0))
        amplitude_cells = max(0.0, min(1.5, float(amplitude_cells or 0.0)))
        sinuous = [points[0]]
        for index in range(1, len(points) - 1):
            before, point, after = points[index - 1], points[index], points[index + 1]
            tx, ty = after[0] - before[0], after[1] - before[1]
            length = math.hypot(tx, ty)
            if length <= 1e-9:
                sinuous.append(point)
                continue
            progress = index / max(1, len(points) - 1)
            taper = math.sin(math.pi * progress) ** 0.8
            offset = math.sin(phase + progress * path_cells / wavelength * math.tau) * amplitude_cells * taper
            nx, ny = -ty / length, tx / length
            sinuous.append((point[0] + nx * offset, point[1] + ny * offset))
        sinuous.append(points[-1])
        points = sinuous
    return [
        {
            "x": round((x % width) / max(1, width - 1), 6),
            "y": round(y / max(1, height - 1), 6),
        }
        for x, y in points
    ]


def _cell_area_weights(width, height, spherical):
    if not spherical:
        return [[1.0 for _x in range(width)] for _y in range(height)]
    raw = [max(0.01, math.sin(math.pi * (y + 0.5) / height)) for y in range(height)]
    mean = sum(raw) / max(1, len(raw))
    return [[value / max(1e-9, mean) for _x in range(width)] for value in raw]


def _spatially_diverse_segments(candidates, limit, width, minimum_source_spacing_cells, wrap_x):
    """Keep the strongest reach from clusters that collapse at the current LOD.

    Adjacent headwater cells can produce many legitimate graph segments with
    almost identical paths. Drawing all of them on a macroregion turns a
    dendritic network into parallel hatching. Deeper LODs retain progressively
    more of those reaches; this filter affects presentation selection only.
    """
    chosen = []
    spacing = max(0.0, float(minimum_source_spacing_cells or 0.0))
    for candidate in candidates:
        source_x, source_y = candidate[2][0]
        redundant = False
        for existing in chosen:
            other_x, other_y = existing[2][0]
            dx = abs(source_x - other_x)
            if wrap_x:
                dx = min(dx, max(0, width - dx))
            if math.hypot(dx, source_y - other_y) < spacing:
                redundant = True
                break
        if not redundant:
            chosen.append(candidate)
            if len(chosen) >= limit:
                break
    return chosen


def _include_downstream_connectors(selected, candidates):
    """Add the omitted graph reaches required to connect selected rivers."""
    by_source = {}
    for candidate in candidates:
        source = candidate[2][0]
        previous = by_source.get(source)
        if previous is None or (candidate[1], candidate[0], len(candidate[2])) > (
            previous[1], previous[0], len(previous[2])
        ):
            by_source[source] = candidate
    connected = list(selected)
    seen = {id(candidate) for candidate in connected}
    cursor = 0
    while cursor < len(connected):
        candidate = connected[cursor]
        cursor += 1
        connector = by_source.get(candidate[2][-1])
        if connector is None or id(connector) in seen:
            continue
        seen.add(id(connector))
        connected.append(connector)
    return connected


def _lake_components(
    rows, filled, ocean_mask, downstream, wrap_x, detail_level,
    accumulation, area_weights, precipitation_rows, potential_evaporation_rows,
    represented_area_m2=None,
):
    height, width = len(rows), len(rows[0])
    span = max(1.0, max(max(row) for row in rows) - min(min(row) for row in rows))
    minimum_depth = max(
        2.0 if detail_level >= 2 else (8.0 if detail_level == 1 else 35.0),
        span * (0.00045 if detail_level >= 2 else 0.0012),
    )
    candidate_mask = [[
        not ocean_mask[y][x]
        and y not in {0, height - 1}
        and filled[y][x] - float(rows[y][x]) >= minimum_depth
        for x in range(width)
    ] for y in range(height)]
    lake_mask = [[False for _x in range(width)] for _y in range(height)]
    visited, lakes = set(), []
    minimum_cells = 1 if detail_level >= 3 else (2 if detail_level == 2 else 3)
    for y in range(height):
        for x in range(width):
            if not candidate_mask[y][x] or (x, y) in visited:
                continue
            queue, cells = deque([(x, y)]), []
            visited.add((x, y))
            while queue:
                cx, cy = queue.popleft()
                cells.append((cx, cy))
                for nx, ny in _neighbors(width, height, cx, cy, wrap_x):
                    if candidate_mask[ny][nx] and (nx, ny) not in visited:
                        visited.add((nx, ny))
                        queue.append((nx, ny))
            if len(cells) < minimum_cells:
                continue
            full_cell_set = set(cells)
            outlet_candidates = [
                (cx, cy, downstream.get((cx, cy)))
                for cx, cy in cells
                if downstream.get((cx, cy)) not in full_cell_set
            ]
            outlet = min(
                outlet_candidates,
                key=lambda item: (filled[item[1]][item[0]], float(rows[item[1]][item[0]])),
                default=None,
            )
            spill_surface = max(filled[cy][cx] for cx, cy in cells)
            maximum_depth = max(spill_surface - float(rows[cy][cx]) for cx, cy in cells)
            inflow_index = max(float(accumulation[cy][cx]) for cx, cy in cells)

            # A depression is maximum storage capacity, not automatically a
            # full lake.  Grow inundation from the deepest cells until annual
            # catchment runoff can no longer offset open-water evaporation,
            # precipitation deficit, and conservative seepage.
            ordered = sorted(cells, key=lambda cell: float(rows[cell[1]][cell[0]]))
            water_budget = inflow_index * 0.82
            cumulative_loss = 0.0
            selected = []
            for cx, cy in ordered:
                precipitation = float(precipitation_rows[cy][cx]) if precipitation_rows else 0.0
                evaporation = float(potential_evaporation_rows[cy][cx]) if potential_evaporation_rows else 350.0
                net_loss = max(35.0, evaporation - precipitation + 25.0)
                next_loss = cumulative_loss + net_loss * area_weights[cy][cx]
                if selected and next_loss > water_budget:
                    break
                selected.append((cx, cy))
                cumulative_loss = next_loss
            water_balance_limited = len(selected) < len(cells)
            overflowing = not water_balance_limited and outlet is not None and outlet[2] is not None

            if overflowing:
                # Long-lived through-flow cuts a spillway below the raw DEM
                # saddle. This breaches broad shallow closures while retaining
                # deep structural, volcanic, glacial, and rift lakes.
                base_incision_m = min(
                    maximum_depth * 0.58,
                    25.0 + math.log1p(max(0.0, inflow_index)) * (16.0 if detail_level <= 0 else 9.0),
                )
                depth_per_radius_cell = maximum_depth / max(1.0, math.sqrt(len(cells)))
                broad_shallow_factor = _clamp((125.0 - depth_per_radius_cell) / 125.0)
                morphometric_incision_m = maximum_depth * broad_shallow_factor * 0.34
                incision_m = min(maximum_depth * 0.76, base_incision_m + morphometric_incision_m)
                incised_surface = spill_surface - incision_m
                incised = [cell for cell in cells if float(rows[cell[1]][cell[0]]) <= incised_surface]
                if len(incised) >= minimum_cells:
                    selected = incised
            if len(selected) < minimum_cells:
                continue

            cells = selected
            min_x, max_x = min(cx for cx, _ in cells), max(cx for cx, _ in cells)
            min_y, max_y = min(cy for _, cy in cells), max(cy for _, cy in cells)
            surface = min(spill_surface, max(float(rows[cy][cx]) for cx, cy in cells) + minimum_depth)
            area_weight = sum(area_weights[cy][cx] for cx, cy in cells)
            total_area_weight = sum(sum(row) for row in area_weights)
            area_fraction = area_weight / max(1e-9, total_area_weight)
            area_km2 = (
                area_fraction * float(represented_area_m2) / 1_000_000.0
                if represented_area_m2 else None
            )
            actual_outlet = outlet if overflowing else None
            if wrap_x:
                x_sin = sum(math.sin(math.tau * cx / width) for cx, _cy in cells)
                x_cos = sum(math.cos(math.tau * cx / width) for cx, _cy in cells)
                center_x = (math.atan2(x_sin, x_cos) / math.tau) % 1.0
            else:
                center_x = sum(cx for cx, _ in cells) / len(cells) / max(1, width - 1)
            lakes.append({
                "cell_count": len(cells),
                "maximum_capacity_cell_count": len(full_cell_set),
                "cell_fraction": round(len(cells) / max(1, width * height), 6),
                "area_fraction": round(area_fraction, 7),
                "area_km2": None if area_km2 is None else round(area_km2, 1),
                "surface_elevation_m": round(surface, 1),
                "maximum_depth_m": round(max(surface - float(rows[cy][cx]) for cx, cy in cells), 1),
                "spill_elevation_m": round(spill_surface, 1),
                "spillway_incision_m": round(spill_surface - surface, 1) if overflowing else 0.0,
                "annual_inflow_index_mm_weighted_cells": round(inflow_index, 2),
                "annual_open_water_loss_index_mm_weighted_cells": round(cumulative_loss, 2),
                "water_balance_limited": water_balance_limited,
                "overflowing": overflowing,
                "bounds": {"min_x": round(min_x / max(1, width - 1), 5), "max_x": round(max_x / max(1, width - 1), 5), "min_y": round(min_y / max(1, height - 1), 5), "max_y": round(max_y / max(1, height - 1), 5), "wraps_dateline": bool(wrap_x and max_x - min_x > width * 0.5)},
                "center": {"x": round(center_x, 5), "y": round(sum(cy for _, cy in cells) / len(cells) / max(1, height - 1), 5)},
                "outlet": None if actual_outlet is None else {"x": round(actual_outlet[2][0] / max(1, width - 1), 5), "y": round(actual_outlet[2][1] / max(1, height - 1), 5)},
                "endorheic": not overflowing,
                "cells": [[cx, cy] for cx, cy in cells],
            })
    lakes.sort(key=lambda item: item["cell_count"] * max(1.0, item["maximum_depth_m"]), reverse=True)
    lakes = lakes[:(32 if detail_level <= 0 else (64 if detail_level == 1 else 96))]
    for index, lake in enumerate(lakes):
        lake["id"] = f"lake_{index + 1:03d}"
        for cx, cy in lake["cells"]:
            lake_mask[cy][cx] = True
    return lake_mask, lakes


def derive_drainage_network(
    rows, ocean_mask, runoff_rows, *, wrap_x=True, detail_level=0,
    max_segments=None, precipitation_rows=None, potential_evaporation_rows=None,
    represented_area_m2=None,
):
    if not rows or not rows[0]:
        return {"status": "unavailable", "model_version": MODEL_VERSION}
    height = len(rows)
    width = min(len(row) for row in rows)
    rows = [list(map(float, row[:width])) for row in rows]
    ocean_mask = [list(row[:width]) for row in ocean_mask]
    filled, downstream, visit_order = _priority_flood(rows, ocean_mask, bool(wrap_x))

    area_weights = _cell_area_weights(width, height, spherical=bool(wrap_x))
    accumulation = [[max(0.0, float(runoff_rows[y][x] or 0.0)) * area_weights[y][x] for x in range(width)] for y in range(height)]
    contributing_cells = [[0 if ocean_mask[y][x] else 1 for x in range(width)] for y in range(height)]
    contributing_area = [[0.0 if ocean_mask[y][x] else area_weights[y][x] for x in range(width)] for y in range(height)]
    upstream = defaultdict(list)
    for x, y in reversed(visit_order):
        target = downstream.get((x, y))
        if target is None:
            continue
        tx, ty = target
        accumulation[ty][tx] += accumulation[y][x]
        contributing_cells[ty][tx] += contributing_cells[y][x]
        contributing_area[ty][tx] += contributing_area[y][x]
        upstream[target].append((x, y))

    lake_mask, lakes = _lake_components(
        rows, filled, ocean_mask, downstream, bool(wrap_x), int(detail_level or 0),
        accumulation, area_weights, precipitation_rows, potential_evaporation_rows,
        represented_area_m2=represented_area_m2,
    )
    land_values = sorted(accumulation[y][x] for y in range(height) for x in range(width) if not ocean_mask[y][x] and accumulation[y][x] > 0.0)
    if not land_values:
        return {"status": "inactive", "model_version": MODEL_VERSION, "rivers": [], "lakes": lakes, "drainage_basins": []}
    quantile = 0.88 if detail_level <= 0 else (0.82 if detail_level == 1 else 0.76)
    land_cell_count = sum(1 for y in range(height) for x in range(width) if not ocean_mask[y][x])
    if land_cell_count < 128:
        quantile = min(quantile, 0.55)
    quantile_threshold = land_values[min(len(land_values) - 1, int(len(land_values) * quantile))]
    local_runoff = sorted(max(0.0, float(runoff_rows[y][x] or 0.0)) for y in range(height) for x in range(width) if not ocean_mask[y][x])
    median_runoff = local_runoff[len(local_runoff) // 2] if local_runoff else 0.0
    minimum_catchment_cells = 7 if detail_level <= 0 else (4 if detail_level == 1 else 2)
    if land_cell_count < 128:
        minimum_catchment_cells = 1
    stream_threshold = max(quantile_threshold, median_runoff * minimum_catchment_cells)
    stream_cells = {
        (x, y)
        for y in range(height)
        for x in range(width)
        if not ocean_mask[y][x]
        and accumulation[y][x] >= stream_threshold
        and contributing_cells[y][x] >= minimum_catchment_cells
    }

    orders = {}
    for x, y in reversed(visit_order):
        child_orders = [orders[child] for child in upstream.get((x, y), ()) if child in stream_cells and child in orders]
        if not child_orders:
            orders[(x, y)] = 1
        else:
            maximum = max(child_orders)
            orders[(x, y)] = maximum + 1 if child_orders.count(maximum) >= 2 else maximum

    network_nodes = {
        cell for cell in stream_cells
        if len([child for child in upstream.get(cell, ()) if child in stream_cells]) != 1
        or downstream.get(cell) not in stream_cells
    }
    raw_segments = []
    for start in network_nodes:
        target = downstream.get(start)
        if target not in stream_cells:
            if target is not None and (ocean_mask[target[1]][target[0]] or lake_mask[target[1]][target[0]]):
                raw_segments.append((
                    accumulation[start[1]][start[0]],
                    orders.get(start, 1),
                    [start, target],
                    contributing_cells[start[1]][start[0]],
                ))
            continue
        path, current, seen = [start], start, {start}
        while True:
            current = downstream.get(current)
            if current is None or current in seen:
                break
            path.append(current)
            seen.add(current)
            if current in network_nodes:
                break
        if len(path) < 2:
            continue
        end = path[-1]
        catchment_cells = contributing_cells[end[1]][end[0]]
        raw_segments.append((accumulation[end[1]][end[0]], orders.get(end, 1), path, catchment_cells))
    raw_segments.sort(key=lambda item: (item[1], item[0], len(item[2])), reverse=True)
    segment_limit = int(max_segments or (28 if detail_level <= 0 else (64 if detail_level == 1 else 140)))
    feeders = [item for item in raw_segments if item[1] == 1]
    tributaries = [item for item in raw_segments if item[1] == 2]
    mainstems = [item for item in raw_segments if item[1] >= 3]
    if detail_level <= 0:
        # Planetary maps communicate only the major drainage skeleton.
        selected = (
            _spatially_diverse_segments(mainstems, 12, width, 10, bool(wrap_x))
            + _spatially_diverse_segments(tributaries, 10, width, 14, bool(wrap_x))
            + _spatially_diverse_segments(feeders, 4, width, 18, bool(wrap_x))
        )
    elif detail_level == 1:
        # Macroregions show river systems and principal tributaries. Dense
        # first-order fans read as hatching and belong to the next LOD.
        selected = (
            _spatially_diverse_segments(mainstems, 24, width, 6, bool(wrap_x))
            + _spatially_diverse_segments(tributaries, 32, width, 9, bool(wrap_x))
            + _spatially_diverse_segments(feeders, 6, width, 13, bool(wrap_x))
        )
    elif detail_level == 2:
        selected = mainstems[:36] + tributaries[:54] + feeders[:28]
    else:
        selected = mainstems[:48] + tributaries[:56] + feeders[:36]
    if detail_level <= 1:
        selected = _include_downstream_connectors(selected[:segment_limit], raw_segments)
    raw_segments = sorted(
        selected if detail_level <= 1 else selected[:segment_limit],
        key=lambda item: (item[1], item[0], len(item[2])),
        reverse=True,
    )
    rivers, node_to_segment = [], {}
    maximum_flow = max(item[0] for item in raw_segments) if raw_segments else max(land_values)
    cell_spacing_m = math.sqrt(float(represented_area_m2) / max(1, width * height)) if represented_area_m2 else 1.0
    for index, (mouth_flow, stream_order, path, catchment_cells) in enumerate(raw_segments):
        river_id = f"river_{index + 1:03d}"
        role = "mainstem" if stream_order >= 3 else ("tributary" if stream_order == 2 else "feeder")
        points = [{"x": round(x / max(1, width - 1), 5), "y": round(y / max(1, height - 1), 5)} for x, y in path]
        end_target = downstream.get(path[-1])
        mouth = "confluence"
        if ocean_mask[path[-1][1]][path[-1][0]]:
            mouth = "ocean"
        elif lake_mask[path[-1][1]][path[-1][0]]:
            mouth = "lake"
        elif end_target is None:
            mouth = "endorheic_basin"
        elif ocean_mask[end_target[1]][end_target[0]]:
            mouth = "ocean"
        elif lake_mask[path[-1][1]][path[-1][0]] or lake_mask[end_target[1]][end_target[0]]:
            mouth = "lake"
        normalized_flow = max(0.035, min(1.0, math.log1p(mouth_flow) / max(1e-9, math.log1p(maximum_flow))))
        morphology = _channel_morphology(
            path, rows, width, height, cell_spacing_m, normalized_flow, stream_order,
        )
        rivers.append({
            "id": river_id,
            "points": points,
            "display_points": _smoothed_channel_points(
                path, width, height, bool(wrap_x),
                amplitude_cells=morphology["sinuosity_amplitude_cells"],
                wavelength_cells=morphology["meander_wavelength_cells"],
            ),
            "stream_order": int(stream_order),
            "network_role": role,
            "flow": round(normalized_flow, 4),
            "channel_morphology": morphology,
            "runoff_accumulation_mm_cells": round(float(mouth_flow), 3),
            "mouth": mouth,
            "source_elevation_m": round(rows[path[0][1]][path[0][0]], 1),
            "catchment_cell_count": int(catchment_cells),
            "catchment_area_weighted_cells": round(contributing_area[path[-1][1]][path[-1][0]], 3),
            "channel_cell_length": len(path),
        })
        node_to_segment[path[0]] = river_id
    for river, (_flow, _order, path, _catchment_cells) in zip(rivers, raw_segments):
        joined = node_to_segment.get(path[-1])
        if joined and joined != river["id"]:
            river["joins_river_id"] = joined

    deltas = []
    for river in rivers:
        if river.get("mouth") != "ocean" or float(river.get("flow", 0.0) or 0.0) < 0.18:
            continue
        points = river.get("display_points") or river.get("points") or []
        if not points:
            continue
        mouth = points[-1]
        catchment = max(1, int(river.get("catchment_cell_count", 1) or 1))
        fan_radius_cells = max(1.0, min(7.0, math.sqrt(catchment) * 0.42))
        deltas.append({
            "id": f"delta_{len(deltas) + 1:03d}",
            "river_id": river["id"],
            "center": {"x": mouth["x"], "y": mouth["y"]},
            "fan_radius_cells": round(fan_radius_cells, 2),
            "distributary_count": max(2, min(9, int(round(2 + float(river.get("flow", 0.0) or 0.0) * 7)))),
            "progradation_index": round(min(1.0, float(river.get("flow", 0.0) or 0.0) * math.log1p(catchment) / 5.0), 3),
            "sediment_source": "catchment_erosion_and_river_transport",
        })
        morphology = river.get("channel_morphology")
        if isinstance(morphology, dict):
            morphology["divergence_allowed"] = True
            morphology["divergence_context"] = "ocean_delta"

    terminal_cache = {}
    def terminal(cell):
        trail = []
        while cell not in terminal_cache and downstream.get(cell) is not None:
            trail.append(cell)
            cell = downstream[cell]
        result = terminal_cache.get(cell, cell)
        for item in trail:
            terminal_cache[item] = result
        return result

    basin_groups = defaultdict(list)
    for y in range(height):
        for x in range(width):
            if not ocean_mask[y][x]:
                basin_groups[terminal((x, y))].append((x, y))
    basin_items = sorted(basin_groups.items(), key=lambda item: len(item[1]), reverse=True)[:96]
    drainage_basins = []
    basin_rows = [[-1 for _x in range(width)] for _y in range(height)]
    for index, (outlet, cells) in enumerate(basin_items):
        basin_id = f"drainage_basin_{index + 1:03d}"
        for x, y in cells:
            basin_rows[y][x] = index
        drainage_basins.append({
            "id": basin_id,
            "cell_count": len(cells),
            "land_fraction": round(len(cells) / max(1, sum(len(group) for group in basin_groups.values())), 5),
            "outlet": {"x": round(outlet[0] / max(1, width - 1), 5), "y": round(outlet[1] / max(1, height - 1), 5)},
            "discharge_index": round(accumulation[outlet[1]][outlet[0]], 2),
        })

    return {
        "status": "drainage_network_seeded",
        "model_version": MODEL_VERSION,
        "detail_level": int(detail_level or 0),
        "filled_elevation_rows": [[round(value, 2) for value in row] for row in filled],
        "flow_accumulation_rows": [[round(value, 2) for value in row] for row in accumulation],
        "drainage_basin_rows": basin_rows,
        "drainage_basins": drainage_basins,
        "lakes": lakes,
        "lake_count": len(lakes),
        "lake_area_fraction": round(sum(float(lake.get("area_fraction", 0.0) or 0.0) for lake in lakes), 6),
        "largest_lake_area_fraction": round(max((float(lake.get("area_fraction", 0.0) or 0.0) for lake in lakes), default=0.0), 6),
        "endorheic_lake_fraction": round(sum(bool(lake.get("endorheic")) for lake in lakes) / max(1, len(lakes)), 3),
        "lake_outlet_fraction": round(sum(not lake.get("endorheic") for lake in lakes) / max(1, len(lakes)), 3),
        "deltas": deltas,
        "delta_count": len(deltas),
        "rivers": rivers,
        "river_segment_count": len(rivers),
        "feeder_count": sum(river["network_role"] == "feeder" for river in rivers),
        "maximum_stream_order": max((river["stream_order"] for river in rivers), default=0),
        "stream_threshold": round(stream_threshold, 3),
    }
