"""Scale-aware watershed, lake, and branching river-network generation."""

import heapq
import math
from collections import defaultdict, deque


MODEL_VERSION = "watershed-drainage-v2"


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


def _smoothed_channel_points(path, width, height, wrap_x):
    """Return a display polyline that preserves endpoints but hides D8 stair-steps."""
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
    return [
        {
            "x": round((x % width) / max(1, width - 1), 6),
            "y": round(y / max(1, height - 1), 6),
        }
        for x, y in points
    ]


def _lake_components(rows, filled, ocean_mask, downstream, wrap_x, detail_level):
    height, width = len(rows), len(rows[0])
    span = max(1.0, max(max(row) for row in rows) - min(min(row) for row in rows))
    minimum_depth = max(2.0, span * (0.00045 if detail_level >= 2 else 0.0012))
    candidate_mask = [[not ocean_mask[y][x] and filled[y][x] - float(rows[y][x]) >= minimum_depth for x in range(width)] for y in range(height)]
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
            cell_set = set(cells)
            outlet = next(((cx, cy, downstream.get((cx, cy))) for cx, cy in cells if downstream.get((cx, cy)) not in cell_set), None)
            min_x, max_x = min(cx for cx, _ in cells), max(cx for cx, _ in cells)
            min_y, max_y = min(cy for _, cy in cells), max(cy for _, cy in cells)
            surface = max(filled[cy][cx] for cx, cy in cells)
            lakes.append({
                "cell_count": len(cells),
                "cell_fraction": round(len(cells) / max(1, width * height), 6),
                "surface_elevation_m": round(surface, 1),
                "maximum_depth_m": round(max(filled[cy][cx] - float(rows[cy][cx]) for cx, cy in cells), 1),
                "bounds": {"min_x": round(min_x / max(1, width - 1), 5), "max_x": round(max_x / max(1, width - 1), 5), "min_y": round(min_y / max(1, height - 1), 5), "max_y": round(max_y / max(1, height - 1), 5)},
                "center": {"x": round(sum(cx for cx, _ in cells) / len(cells) / max(1, width - 1), 5), "y": round(sum(cy for _, cy in cells) / len(cells) / max(1, height - 1), 5)},
                "outlet": None if outlet is None or outlet[2] is None else {"x": round(outlet[2][0] / max(1, width - 1), 5), "y": round(outlet[2][1] / max(1, height - 1), 5)},
                "endorheic": outlet is None or outlet[2] is None,
                "cells": [[cx, cy] for cx, cy in cells],
            })
    lakes.sort(key=lambda item: item["cell_count"] * max(1.0, item["maximum_depth_m"]), reverse=True)
    lakes = lakes[:(32 if detail_level <= 0 else (64 if detail_level == 1 else 96))]
    for index, lake in enumerate(lakes):
        lake["id"] = f"lake_{index + 1:03d}"
        for cx, cy in lake["cells"]:
            lake_mask[cy][cx] = True
    return lake_mask, lakes


def derive_drainage_network(rows, ocean_mask, runoff_rows, *, wrap_x=True, detail_level=0, max_segments=None):
    if not rows or not rows[0]:
        return {"status": "unavailable", "model_version": MODEL_VERSION}
    height = len(rows)
    width = min(len(row) for row in rows)
    rows = [list(map(float, row[:width])) for row in rows]
    ocean_mask = [list(row[:width]) for row in ocean_mask]
    filled, downstream, visit_order = _priority_flood(rows, ocean_mask, bool(wrap_x))

    accumulation = [[max(0.0, float(runoff_rows[y][x] or 0.0)) for x in range(width)] for y in range(height)]
    contributing_cells = [[0 if ocean_mask[y][x] else 1 for x in range(width)] for y in range(height)]
    upstream = defaultdict(list)
    for x, y in reversed(visit_order):
        target = downstream.get((x, y))
        if target is None:
            continue
        tx, ty = target
        accumulation[ty][tx] += accumulation[y][x]
        contributing_cells[ty][tx] += contributing_cells[y][x]
        upstream[target].append((x, y))

    lake_mask, lakes = _lake_components(rows, filled, ocean_mask, downstream, bool(wrap_x), int(detail_level or 0))
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
    segment_limit = int(max_segments or (28 if detail_level <= 0 else (96 if detail_level == 1 else 160)))
    if len(raw_segments) > segment_limit:
        feeders = [item for item in raw_segments if item[1] == 1]
        tributaries = [item for item in raw_segments if item[1] == 2]
        mainstems = [item for item in raw_segments if item[1] >= 3]
        if detail_level <= 0:
            # Planetary maps communicate major drainage systems.  Dense D8
            # feeder fans belong to regional views and read as cross-hatching
            # when all are drawn at global scale.
            selected = mainstems[:12] + tributaries[:10] + feeders[:6]
        else:
            selected = mainstems[:max(8, segment_limit // 3)]
            selected += tributaries[:max(12, segment_limit // 3)]
            selected += feeders[:max(12, segment_limit // 3)]
            selected_ids = {id(item) for item in selected}
            selected += [item for item in raw_segments if id(item) not in selected_ids][:max(0, segment_limit - len(selected))]
        raw_segments = sorted(selected[:segment_limit], key=lambda item: (item[1], item[0], len(item[2])), reverse=True)
    rivers, node_to_segment = [], {}
    maximum_flow = max(item[0] for item in raw_segments) if raw_segments else max(land_values)
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
        rivers.append({
            "id": river_id,
            "points": points,
            "display_points": _smoothed_channel_points(path, width, height, bool(wrap_x)),
            "stream_order": int(stream_order),
            "network_role": role,
            "flow": round(max(0.035, min(1.0, math.log1p(mouth_flow) / max(1e-9, math.log1p(maximum_flow)))), 4),
            "runoff_accumulation_mm_cells": round(float(mouth_flow), 3),
            "mouth": mouth,
            "source_elevation_m": round(rows[path[0][1]][path[0][0]], 1),
            "catchment_cell_count": int(catchment_cells),
            "channel_cell_length": len(path),
        })
        node_to_segment[path[0]] = river_id
    for river, (_flow, _order, path, _catchment_cells) in zip(rivers, raw_segments):
        joined = node_to_segment.get(path[-1])
        if joined and joined != river["id"]:
            river["joins_river_id"] = joined

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
        "rivers": rivers,
        "river_segment_count": len(rivers),
        "feeder_count": sum(river["network_role"] == "feeder" for river in rivers),
        "maximum_stream_order": max((river["stream_order"] for river in rivers), default=0),
        "stream_threshold": round(stream_threshold, 3),
    }
