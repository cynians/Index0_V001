"""Generate one or two planetary-to-survey coastal benchmark image series."""

import argparse
import copy
import json
import math
import os
import sys
import time
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from simulations.world_gen.coastal_geomorphology import (
    ASSEMBLAGE_COLORS,
    coastal_summary,
    derive_coastal_geomorphology_model,
    enrich_coastal_hydrology,
)
from simulations.world_gen.regional_refinement import (
    DETAIL_LEVELS,
    MAX_DETAIL_LEVEL,
    generate_refined_region,
    map_physical_dimensions_m,
)
from world.world_model import WorldModel


TARGET_EXTENT_M = {
    1: 2_000_000.0,
    2: 200_000.0,
    3: 20_000.0,
    4: 2_000.0,
    5: 200.0,
    6: 30.0,
    7: 10.0,
}


def _font(size, bold=False):
    return pygame.font.SysFont("consolas", int(size), bold=bold)


def _text(surface, value, position, size=18, color=(228, 234, 240), bold=False):
    surface.blit(_font(size, bold=bold).render(str(value), True, color), position)


def _fmt_distance(metres):
    metres = float(metres or 0.0)
    if metres >= 1_000_000.0:
        return f"{metres / 1_000_000.0:.2f} Mm"
    if metres >= 1_000.0:
        return f"{metres / 1_000.0:.2f} km"
    if metres >= 1.0:
        return f"{metres:.2f} m"
    return f"{metres * 100.0:.1f} cm"


def _nice_scale_length(width_m):
    target = max(0.01, float(width_m) * 0.20)
    exponent = math.floor(math.log10(target))
    fraction = target / (10.0 ** exponent)
    nice = 1.0 if fraction < 2.0 else (2.0 if fraction < 5.0 else 5.0)
    return nice * (10.0 ** exponent)


def _segment_distance_to(segment, point=(0.5, 0.5)):
    points = ((segment.get("geometry") or {}).get("points") or [])
    if not points:
        points = [(segment.get("measurements") or {}).get("centroid_uv") or [0.5, 0.5]]
    return min(math.hypot(float(item[0]) - point[0], float(item[1]) - point[1]) for item in points)


def _tracking_point(segment):
    points = ((segment.get("geometry") or {}).get("points") or [])
    if not points:
        centroid = (segment.get("measurements") or {}).get("centroid_uv") or [0.5, 0.5]
        return [float(centroid[0]), float(centroid[1])]
    # Keep the shoreline near the center of every child patch. Segment
    # centroids can sit far along a bent chain and previously drove the next
    # refinement against a parent edge.
    return list(min(points, key=lambda item: math.hypot(float(item[0]) - 0.5, float(item[1]) - 0.5)))


def _nearest_center_segment(entity):
    segments = (entity.get("coastal_geomorphology_model") or {}).get("segments") or []
    return min(segments, key=_segment_distance_to) if segments else None


def _select_root_segments(planet, required_branches=("depositional", "cliff")):
    segments = (planet.get("coastal_geomorphology_model") or {}).get("segments") or []
    depositional_order = [
        "deltaic",
        "clastic_beach",
        "barrier_lagoon",
        "tidal_flat_accommodation",
        "estuarine_drowned_valley",
    ]
    depositional = None
    for assemblage in depositional_order:
        matches = [item for item in segments if (item.get("morphology_assemblage") or item.get("primary_assemblage")) == assemblage]
        if matches:
            depositional = max(
                matches,
                key=lambda item: (
                    float(item.get("river_influence", 0.0) or 0.0)
                    + float((item.get("sediment_budget") or {}).get("source_strength", 0.0) or 0.0)
                    - float((item.get("measurements") or {}).get("inland_relief_m", 0.0) or 0.0) / 20_000.0
                ),
            )
            break
    cliffs = [item for item in segments if (item.get("morphology_assemblage") or item.get("primary_assemblage")) in {"rocky_cliff", "headland_bay"}]
    cliff = max(
        cliffs,
        key=lambda item: (
            float((item.get("measurements") or {}).get("inland_relief_m", 0.0) or 0.0)
            + float((item.get("measurements") or {}).get("nearshore_gradient", 0.0) or 0.0) * 10_000.0
        ),
    ) if cliffs else None
    selections = {"depositional": depositional, "cliff": cliff}
    missing = [branch for branch in required_branches if selections.get(branch) is None]
    if missing:
        raise RuntimeError(f"The planet does not contain the requested benchmark end member(s): {', '.join(missing)}")
    return {branch: segment for branch, segment in selections.items() if segment is not None}


def _child_bounds(parent, center_uv, target_extent_m):
    bounds = parent.get("bounds") or {}
    parent_width_world = float(bounds["max_x"]) - float(bounds["min_x"])
    parent_height_world = float(bounds["max_y"]) - float(bounds["min_y"])
    parent_width_m, parent_height_m = map_physical_dimensions_m(parent)
    width_fraction = min(0.72, target_extent_m / max(1.0, parent_width_m))
    height_fraction = min(0.72, target_extent_m / max(1.0, parent_height_m))
    width_world = parent_width_world * width_fraction
    height_world = parent_height_world * height_fraction
    center_x = float(bounds["min_x"]) + float(center_uv[0]) * parent_width_world
    center_y = float(bounds["min_y"]) + float(center_uv[1]) * parent_height_world
    minimum_x = max(float(bounds["min_x"]), min(float(bounds["max_x"]) - width_world, center_x - width_world * 0.5))
    minimum_y = max(float(bounds["min_y"]), min(float(bounds["max_y"]) - height_world, center_y - height_world * 0.5))
    return {
        "min_x": minimum_x,
        "max_x": minimum_x + width_world,
        "min_y": minimum_y,
        "max_y": minimum_y + height_world,
    }


def _blend(a, b, amount):
    amount = max(0.0, min(1.0, float(amount)))
    return tuple(int(a[index] * (1.0 - amount) + b[index] * amount) for index in range(3))


def _topographic_surface(entity, output_size):
    heightmap = entity.get("heightmap_model") or {}
    rows = ((heightmap.get("sample_grid") or {}).get("rows") or [])
    source_height = len(rows)
    source_width = min(len(row) for row in rows) if rows else 0
    if not source_width:
        surface = pygame.Surface(output_size)
        surface.fill((16, 22, 30))
        return surface
    sea = heightmap.get("sea_level_m")
    sea = float(sea) if sea is not None else min(min(row) for row in rows)
    land_values = [float(value) for row in rows for value in row[:source_width] if float(value) >= sea]
    ocean_values = [float(value) for row in rows for value in row[:source_width] if float(value) < sea]
    land_span = max(0.1, (max(land_values) - sea) if land_values else 1.0)
    ocean_span = max(0.1, (sea - min(ocean_values)) if ocean_values else 1.0)
    centre_segment = _nearest_center_segment(entity)
    morphology = str(
        (centre_segment or {}).get("morphology_assemblage")
        or (centre_segment or {}).get("coastal_system")
        or (centre_segment or {}).get("primary_assemblage")
        or ""
    )
    rocky_surface = morphology in {
        "rocky_cliff",
        "headland_bay",
        "glacial_fjord_fjard_skerry",
        "emergent_marine_terrace",
    }
    spacing_x = max(0.01, float(heightmap.get("sample_spacing_x_m", 1.0) or 1.0))
    spacing_y = max(0.01, float(heightmap.get("sample_spacing_y_m", 1.0) or 1.0))
    source = pygame.Surface((source_width, source_height))
    for y in range(source_height):
        north_y = max(0, y - 1)
        south_y = min(source_height - 1, y + 1)
        for x in range(source_width):
            west_x = max(0, x - 1)
            east_x = min(source_width - 1, x + 1)
            elevation = float(rows[y][x])
            dzdx = (float(rows[y][east_x]) - float(rows[y][west_x])) / max(0.02, 2.0 * spacing_x)
            dzdy = (float(rows[south_y][x]) - float(rows[north_y][x])) / max(0.02, 2.0 * spacing_y)
            normal_length = math.sqrt(dzdx * dzdx + dzdy * dzdy + 1.0)
            illumination = max(0.0, min(1.0, (-dzdx * 0.45 - dzdy * 0.35 + 0.82) / normal_length))
            shade = 0.80 + illumination * 0.28
            if elevation < sea:
                depth = min(1.0, (sea - elevation) / ocean_span)
                base = _blend((38, 132, 151), (5, 28, 55), depth ** 0.55)
            else:
                relative = min(1.0, (elevation - sea) / land_span)
                if rocky_surface:
                    if relative < 0.18:
                        base = _blend((70, 72, 66), (103, 105, 88), relative / 0.18)
                    elif relative < 0.55:
                        base = _blend((103, 105, 88), (119, 126, 92), (relative - 0.18) / 0.37)
                    else:
                        base = _blend((119, 126, 92), (165, 158, 139), (relative - 0.55) / 0.45)
                elif relative < 0.055:
                    base = (205, 190, 137)
                elif relative < 0.28:
                    base = _blend((105, 142, 91), (139, 126, 91), relative / 0.28)
                else:
                    base = _blend((139, 126, 91), (183, 184, 181), (relative - 0.28) / 0.72)
            source.set_at((x, y), tuple(max(0, min(255, int(channel * shade))) for channel in base))
    return pygame.transform.smoothscale(source, output_size)


def _draw_segment(surface, segment, color, width=3):
    canvas_width, canvas_height = surface.get_size()
    run = []
    for point in ((segment.get("geometry") or {}).get("points") or []):
        candidate = (
            int(round(float(point[0]) * (canvas_width - 1))),
            int(round(float(point[1]) * (canvas_height - 1))),
        )
        if run and abs(candidate[0] - run[-1][0]) > canvas_width * 0.5:
            if len(run) >= 2:
                pygame.draw.lines(surface, (8, 12, 16), False, run, width + 3)
                pygame.draw.lines(surface, color, False, run, width)
            run = []
        run.append(candidate)
    if len(run) >= 2:
        pygame.draw.lines(surface, (8, 12, 16), False, run, width + 3)
        pygame.draw.lines(surface, color, False, run, width)


def _heightfield_topology_metrics(entity):
    heightmap = entity.get("heightmap_model") or {}
    grid = heightmap.get("sample_grid") or {}
    rows = grid.get("rows") or []
    if not rows or not rows[0] or heightmap.get("sea_level_m") is None:
        return {}
    sea = float(heightmap["sea_level_m"])
    height = len(rows)
    width = min(len(row) for row in rows)
    land = [[float(rows[y][x]) >= sea for x in range(width)] for y in range(height)]
    spacing_x = max(0.001, float(heightmap.get("sample_spacing_x_m") or 1.0))
    spacing_y = max(0.001, float(heightmap.get("sample_spacing_y_m") or spacing_x))

    def components(target):
        seen = [[False for _x in range(width)] for _y in range(height)]
        found = []
        for start_y in range(height):
            for start_x in range(width):
                if seen[start_y][start_x] or land[start_y][start_x] != target:
                    continue
                queue = deque([(start_x, start_y)])
                seen[start_y][start_x] = True
                size = 0
                touches_edge = False
                while queue:
                    x, y = queue.popleft()
                    size += 1
                    touches_edge = touches_edge or x == 0 or y == 0 or x == width - 1 or y == height - 1
                    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                        xx, yy = x + dx, y + dy
                        if 0 <= xx < width and 0 <= yy < height and not seen[yy][xx] and land[yy][xx] == target:
                            seen[yy][xx] = True
                            queue.append((xx, yy))
                found.append({"cells": size, "touches_edge": touches_edge})
        return found

    land_components = components(True)
    water_components = components(False)
    shoreline_length_m = 0.0
    for y in range(height):
        for x in range(1, width):
            if land[y][x] != land[y][x - 1]:
                shoreline_length_m += spacing_y
    for y in range(1, height):
        for x in range(width):
            if land[y][x] != land[y - 1][x]:
                shoreline_length_m += spacing_x
    area_m2 = max(1e-9, (width - 1) * spacing_x * (height - 1) * spacing_y)
    return {
        "terrain_sample_count": width * height,
        "land_fraction": round(sum(sum(row) for row in land) / max(1, width * height), 6),
        "land_component_count": len(land_components),
        "water_component_count": len(water_components),
        "enclosed_land_component_count": sum(not item["touches_edge"] for item in land_components),
        "enclosed_water_component_count": sum(not item["touches_edge"] for item in water_components),
        "shoreline_length_m_grid": round(shoreline_length_m, 4),
        "shoreline_length_per_hectare_m": round(shoreline_length_m / area_m2 * 10_000.0, 4),
    }


def _child_bounds_uv(entity, child_bounds):
    if not child_bounds:
        return None
    bounds = entity.get("bounds") or {}
    width = float(bounds.get("max_x", 0.0)) - float(bounds.get("min_x", 0.0))
    height = float(bounds.get("max_y", 0.0)) - float(bounds.get("min_y", 0.0))
    if width <= 0.0 or height <= 0.0:
        return None
    return {
        "min_u": (float(child_bounds["min_x"]) - float(bounds["min_x"])) / width,
        "max_u": (float(child_bounds["max_x"]) - float(bounds["min_x"])) / width,
        "min_v": (float(child_bounds["min_y"]) - float(bounds["min_y"])) / height,
        "max_v": (float(child_bounds["max_y"]) - float(bounds["min_y"])) / height,
    }


def _render_level(entity, branch, tracked_segment, output_path, *, next_child_bounds=None, next_level=None):
    canvas_size = (1200, 720)
    surface = _topographic_surface(entity, canvas_size)
    coastal = entity.get("coastal_geomorphology_model") or {}
    level = int(entity.get("map_detail_level", 0) or 0)
    if level <= 3:
        for segment in coastal.get("segments") or []:
            color = tuple(segment.get("display_color") or [218, 198, 126])
            _draw_segment(surface, segment, color, width=2)
    if tracked_segment and level <= 3:
        highlight = tuple(tracked_segment.get("display_color") or [250, 232, 118])
        _draw_segment(surface, tracked_segment, highlight, width=5)
        center = (tracked_segment.get("measurements") or {}).get("centroid_uv") or [0.5, 0.5]
        marker = (int(float(center[0]) * canvas_size[0]), int(float(center[1]) * canvas_size[1]))
        pygame.draw.circle(surface, (8, 12, 18), marker, 12, 4)
        pygame.draw.circle(surface, highlight, marker, 9, 3)

    child_uv = _child_bounds_uv(entity, next_child_bounds)
    if child_uv:
        left = int(round(child_uv["min_u"] * (canvas_size[0] - 1)))
        right = int(round(child_uv["max_u"] * (canvas_size[0] - 1)))
        top = int(round(child_uv["min_v"] * (canvas_size[1] - 1)))
        bottom = int(round(child_uv["max_v"] * (canvas_size[1] - 1)))
        rect = pygame.Rect(left, top, max(2, right - left), max(2, bottom - top))
        pygame.draw.rect(surface, (8, 12, 18), rect.inflate(6, 6), 6)
        pygame.draw.rect(surface, (255, 92, 168), rect, 4)
        label = _font(16, bold=True).render(f"NEXT: L{next_level}", True, (255, 225, 241))
        label_x = max(8, min(canvas_size[0] - label.get_width() - 8, rect.left))
        label_y = max(8, min(canvas_size[1] - label.get_height() - 8, rect.top - label.get_height() - 6))
        backing = pygame.Surface((label.get_width() + 10, label.get_height() + 6), pygame.SRCALPHA)
        backing.fill((8, 12, 18, 220))
        surface.blit(backing, (label_x - 5, label_y - 3))
        surface.blit(label, (label_x, label_y))

    shade = pygame.Surface(canvas_size, pygame.SRCALPHA)
    shade.fill((0, 0, 0, 0))
    pygame.draw.rect(shade, (7, 12, 19, 220), pygame.Rect(14, 14, 480, 170))
    surface.blit(shade, (0, 0))
    spec = DETAIL_LEVELS[level]
    width_m, height_m = map_physical_dimensions_m(entity)
    heightmap = entity.get("heightmap_model") or {}
    grid = heightmap.get("sample_grid") or {}
    spacing = max(float(heightmap.get("sample_spacing_x_m", 0.0) or 0.0), float(heightmap.get("sample_spacing_y_m", 0.0) or 0.0))
    assemblage = str((tracked_segment or {}).get("morphology_assemblage") or (tracked_segment or {}).get("primary_assemblage") or "no resolved shoreline").replace("_", " ")
    coastal_system = str((tracked_segment or {}).get("coastal_system") or assemblage).replace("_", " ")
    _text(surface, f"{branch.upper()} — L{level} {spec['label'].upper()}", (28, 25), 24, bold=True)
    _text(surface, f"footprint  {_fmt_distance(width_m)} × {_fmt_distance(height_m)}", (28, 61), 17)
    _text(surface, f"sampling   {int(grid.get('width', 0))} × {int(grid.get('height', 0))}  |  {_fmt_distance(spacing)} max spacing", (28, 88), 17)
    _text(surface, f"coast      {coastal_system} system  |  {assemblage} facies  |  {(tracked_segment or {}).get('substrate', 'n/a')}", (28, 115), 17)
    _text(surface, f"elevation  {float(heightmap.get('min_elevation_m', 0.0)):.2f} to {float(heightmap.get('max_elevation_m', 0.0)):.2f} m", (28, 142), 17)

    scale_length = _nice_scale_length(width_m)
    scale_pixels = max(45, int(canvas_size[0] * scale_length / max(1.0, width_m)))
    scale_x = canvas_size[0] - 40 - scale_pixels
    scale_y = canvas_size[1] - 38
    pygame.draw.line(surface, (245, 245, 238), (scale_x, scale_y), (scale_x + scale_pixels, scale_y), 4)
    pygame.draw.line(surface, (245, 245, 238), (scale_x, scale_y - 8), (scale_x, scale_y + 8), 3)
    pygame.draw.line(surface, (245, 245, 238), (scale_x + scale_pixels, scale_y - 8), (scale_x + scale_pixels, scale_y + 8), 3)
    label = _font(16, bold=True).render(_fmt_distance(scale_length), True, (245, 245, 238))
    surface.blit(label, (scale_x + (scale_pixels - label.get_width()) // 2, scale_y - 30))
    pygame.image.save(surface, str(output_path))


def _level_record(entity, root_assemblage, tracked_segment, seconds, image_path, *, next_child_bounds=None):
    level = int(entity.get("map_detail_level", 0) or 0)
    width_m, height_m = map_physical_dimensions_m(entity)
    heightmap = entity.get("heightmap_model") or {}
    coastal = entity.get("coastal_geomorphology_model") or {}
    refinement = coastal.get("regional_landform_materialization") or {}
    topology = refinement.get("topology_stabilization") or {}
    relief_limiter = heightmap.get("scale_appropriate_relief") or {}
    elevation_range = float(heightmap.get("max_elevation_m", 0.0) or 0.0) - float(heightmap.get("min_elevation_m", 0.0) or 0.0)
    topology_metrics = _heightfield_topology_metrics(entity)
    return {
        "level": level,
        "level_id": DETAIL_LEVELS[level]["id"],
        "label": DETAIL_LEVELS[level]["label"],
        "nominal_resolution": DETAIL_LEVELS[level]["nominal_resolution"],
        "footprint_width_m": round(width_m, 6),
        "footprint_height_m": round(height_m, 6),
        "sample_spacing_x_m": round(float(heightmap.get("sample_spacing_x_m", 0.0) or 0.0), 9),
        "sample_spacing_y_m": round(float(heightmap.get("sample_spacing_y_m", 0.0) or 0.0), 9),
        "elevation_range_m": round(elevation_range, 4),
        "relief_to_footprint_ratio": round(elevation_range / max(1e-9, max(width_m, height_m)), 6),
        "segment_count": len(coastal.get("segments") or []),
        "component_count": len(coastal.get("components") or []),
        **topology_metrics,
        "coastline_length_km": (coastal.get("summary") or {}).get("coastline_length_km"),
        "tracked_assemblage": (tracked_segment or {}).get("morphology_assemblage") or (tracked_segment or {}).get("primary_assemblage"),
        "coastal_system": (tracked_segment or {}).get("coastal_system"),
        "geologic_characters": list((tracked_segment or {}).get("geologic_characters") or []),
        "root_assemblage": root_assemblage,
        "classification_preserved": bool(tracked_segment and ((tracked_segment.get("coastal_system") or tracked_segment.get("morphology_assemblage") or tracked_segment.get("primary_assemblage")) == root_assemblage)),
        "substrate": (tracked_segment or {}).get("substrate"),
        "river_influence": (tracked_segment or {}).get("river_influence"),
        "inland_relief_m": ((tracked_segment or {}).get("measurements") or {}).get("inland_relief_m"),
        "nearshore_gradient": ((tracked_segment or {}).get("measurements") or {}).get("nearshore_gradient"),
        "parent_segment_ids": list(coastal.get("parent_segment_ids") or []),
        "modified_cell_samples": int(refinement.get("modified_cell_samples", 0) or 0),
        "sediment_budget_conserved": refinement.get("sediment_budget_conserved"),
        "drainage_reconciliation_count": int(refinement.get("drainage_reconciliation_count", 0) or 0),
        "resolved_feature_families": list(refinement.get("resolved_feature_families") or []),
        "deferred_object_detail_families": list(refinement.get("deferred_object_detail_families") or []),
        "object_detail_policy": refinement.get("object_detail_policy"),
        "topology_flipped_cell_count": int(topology.get("flipped_cell_count", 0) or 0),
        "relief_limiter": relief_limiter,
        "generation_seconds": round(seconds, 4),
        "image": str(image_path.resolve()),
        "next_child_bounds_uv": _child_bounds_uv(entity, next_child_bounds),
    }


def _build_contact_sheet(records, output_path, title):
    thumb_size = (600, 360)
    margin, gap, header = 22, 16, 58
    sheet = pygame.Surface((margin * 2 + thumb_size[0] * 2 + gap, header + margin + (thumb_size[1] + 34 + gap) * 4))
    sheet.fill((12, 17, 25))
    _text(sheet, title, (margin, 18), 24, bold=True)
    for index, record in enumerate(records):
        col, row = index % 2, index // 2
        x = margin + col * (thumb_size[0] + gap)
        y = header + row * (thumb_size[1] + 34 + gap)
        image = pygame.image.load(record["image"])
        sheet.blit(pygame.transform.smoothscale(image, thumb_size), (x, y))
        _text(sheet, f"L{record['level']} {record['label']} — {_fmt_distance(record['footprint_width_m'])}", (x + 6, y + thumb_size[1] + 7), 15)
    pygame.image.save(sheet, str(output_path))


def _automatic_discrepancies(branches):
    discrepancies = []
    for branch, records in branches.items():
        root = records[0]
        previous = root
        for record in records[1:]:
            prefix = f"{branch} L{record['level']} ({record['label']})"
            if not record["tracked_assemblage"]:
                discrepancies.append({"severity": "high", "scope": prefix, "issue": "No shoreline remained resolved in the tracked patch."})
                continue
            if not record["classification_preserved"]:
                discrepancies.append({
                    "severity": "medium",
                    "scope": prefix,
                    "issue": f"Classification drifted from {root['root_assemblage']} to {record['tracked_assemblage']}.",
                })
            if not record["parent_segment_ids"]:
                discrepancies.append({"severity": "high", "scope": prefix, "issue": "No parent coastal segment lineage was recorded."})
            if record["relief_to_footprint_ratio"] > 1.0:
                discrepancies.append({
                    "severity": "high",
                    "scope": prefix,
                    "issue": f"Elevation range exceeds patch width ({record['relief_to_footprint_ratio']:.2f}×), indicating scale-inappropriate inherited/coastal relief.",
                })
            rocky_relief = record["coastal_system"] in {
                "rocky_cliff",
                "headland_bay",
                "glacial_fjord_fjard_skerry",
                "emergent_marine_terrace",
            }
            relief_warning_ratio = 0.45 if rocky_relief else 0.35
            if (
                record["relief_to_footprint_ratio"] <= 1.0
                and record["relief_to_footprint_ratio"] > relief_warning_ratio
            ):
                discrepancies.append({
                    "severity": "medium",
                    "scope": prefix,
                    "issue": f"Elevation range is large relative to the footprint ({record['relief_to_footprint_ratio']:.2f}×).",
                })
            if record["modified_cell_samples"] and record["sediment_budget_conserved"] is not True:
                discrepancies.append({"severity": "high", "scope": prefix, "issue": "Materialized coastal relief did not conserve its resolved sediment budget."})
            if record["modified_cell_samples"] and record["drainage_reconciliation_count"] != 1:
                discrepancies.append({"severity": "high", "scope": prefix, "issue": "Terrain-changing coastal materialization did not trigger exactly one drainage reconciliation."})
            if (
                record["level"] >= 5
                and int(record.get("enclosed_land_component_count", 0) or 0)
                + int(record.get("enclosed_water_component_count", 0) or 0)
                > int(previous.get("enclosed_land_component_count", 0) or 0)
                + int(previous.get("enclosed_water_component_count", 0) or 0)
                + 8
            ):
                discrepancies.append({
                    "severity": "high",
                    "scope": prefix,
                    "issue": "Closed land/water components proliferate at finer scale instead of resolving a coherent parent shoreline.",
                })
            if (
                record["level"] >= 6
                and float(record.get("sample_spacing_x_m", 0.0) or 0.0) < 0.0999
            ):
                discrepancies.append({
                    "severity": "high",
                    "scope": prefix,
                    "issue": "Terrain sampling crosses the 10 cm physical floor reserved for the heightfield.",
                })
            previous = record
    deepest_features = {
        tuple(record["resolved_feature_families"])
        for records in branches.values()
        for record in records
        if record["level"] >= 3
    }
    if len(deepest_features) == 1:
        discrepancies.append({
            "severity": "medium",
            "scope": "L3–L7 coastal feature gating",
            "issue": "No new coastal feature families are introduced below Local scale; Site, Parcel, Plot, and Survey reuse the L3 family list.",
        })
    return discrepancies


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("planet_json", type=Path)
    parser.add_argument("output_directory", type=Path)
    parser.add_argument("repository_directory", type=Path)
    parser.add_argument("--branch", choices=("depositional", "cliff", "both"), default="both")
    args = parser.parse_args()
    args.output_directory.mkdir(parents=True, exist_ok=True)
    if args.repository_directory.exists():
        raise RuntimeError(f"Temporary repository already exists: {args.repository_directory}")
    entries = args.repository_directory / "entries"
    entries.mkdir(parents=True)

    pygame.init()
    pygame.font.init()
    planet = json.loads(args.planet_json.read_text(encoding="utf-8"))
    planet["map_detail_level"] = 0
    planet.setdefault("bounds", {"type": "bbox", "min_x": -180.0, "max_x": 180.0, "min_y": -90.0, "max_y": 90.0})
    star = {
        "id": planet.get("parent_body") or "star_coastal_benchmark",
        "name": "Benchmark Star",
        "type": "location",
        "_dataset": "locations",
        "location_class": "star",
        "mass_kg": 1.98847e30,
        "mass_solar": 1.0,
    }
    root_model = derive_coastal_geomorphology_model(
        planet=planet,
        heightmap=planet.get("heightmap_model"),
        water_cycle=planet.get("water_cycle_model"),
        tectonic_model=planet.get("tectonic_model"),
        surface_evolution=planet.get("surface_evolution_model"),
        star=star,
    )
    planet["coastal_geomorphology_model"] = root_model
    planet["coastal_summary"] = coastal_summary(root_model)
    enrich_coastal_hydrology(planet.get("water_cycle_model"), root_model)

    world = WorldModel(entries_directory=entries, use_ontology=False)
    world.loader.persist_entity(star)
    world.loader.persist_entity(planet)
    requested_branches = ["depositional", "cliff"] if args.branch == "both" else [args.branch]
    selections = _select_root_segments(planet, requested_branches)
    branches = {}

    for branch in requested_branches:
        root_segment = selections[branch]
        branch_dir = args.output_directory / branch
        branch_dir.mkdir(parents=True, exist_ok=True)
        records = []
        current = planet
        tracked = root_segment
        root_assemblage = str(root_segment.get("morphology_assemblage") or root_segment.get("primary_assemblage"))
        next_bounds = _child_bounds(current, _tracking_point(tracked), TARGET_EXTENT_M[1])
        image_path = branch_dir / "level_0_planetary.png"
        _render_level(current, branch, tracked, image_path, next_child_bounds=next_bounds, next_level=1)
        records.append(_level_record(current, root_assemblage, tracked, 0.0, image_path, next_child_bounds=next_bounds))

        for level in range(1, MAX_DETAIL_LEVEL + 1):
            bounds = next_bounds
            started = time.perf_counter()
            current = generate_refined_region(
                world,
                current,
                bounds,
                seed_suffix=f"coastal-scale-benchmark-{branch}",
            )
            elapsed = time.perf_counter() - started
            tracked = _nearest_center_segment(current)
            next_bounds = (
                _child_bounds(current, _tracking_point(tracked) if tracked else [0.5, 0.5], TARGET_EXTENT_M[level + 1])
                if level < MAX_DETAIL_LEVEL else None
            )
            image_path = branch_dir / f"level_{level}_{DETAIL_LEVELS[level]['id']}.png"
            _render_level(current, branch, tracked, image_path, next_child_bounds=next_bounds, next_level=level + 1 if next_bounds else None)
            records.append(_level_record(current, root_assemblage, tracked, elapsed, image_path, next_child_bounds=next_bounds))
            print(json.dumps({
                "branch": branch,
                "level": level,
                "label": DETAIL_LEVELS[level]["label"],
                "seconds": round(elapsed, 3),
                "tracked_assemblage": (tracked or {}).get("morphology_assemblage") or (tracked or {}).get("primary_assemblage"),
                "coastal_system": (tracked or {}).get("coastal_system"),
                "footprint_m": list(map_physical_dimensions_m(current)),
            }), flush=True)
        contact_sheet = args.output_directory / f"{branch}_scale_contact_sheet.png"
        _build_contact_sheet(records, contact_sheet, f"{branch.upper()} COAST — PLANETARY TO SURVEY")
        branches[branch] = records

    report = {
        "benchmark": "coastal-scale-benchmark-v2",
        "planet_id": planet.get("id"),
        "map_seed": (planet.get("world_gen_seed") or {}).get("map_seed"),
        "selected_segments": {
            branch: {
                "id": segment.get("id"),
                "primary_assemblage": segment.get("primary_assemblage"),
                "morphology_assemblage": segment.get("morphology_assemblage"),
                "geologic_characters": segment.get("geologic_characters"),
                "substrate": segment.get("substrate"),
                "river_influence": segment.get("river_influence"),
                "measurements": segment.get("measurements"),
                "wave_climate": segment.get("wave_climate"),
                "tidal_regime": segment.get("tidal_regime"),
                "sediment_budget": segment.get("sediment_budget"),
            }
            for branch, segment in selections.items() if branch in requested_branches
        },
        "branches": branches,
        "discrepancies": _automatic_discrepancies(branches),
    }
    report_path = args.output_directory / "benchmark_report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "report": str(report_path.resolve()),
        "discrepancy_count": len(report["discrepancies"]),
        "contact_sheets": [
            str((args.output_directory / f"{branch}_scale_contact_sheet.png").resolve())
            for branch in requested_branches
        ],
    }, indent=2), flush=True)


if __name__ == "__main__":
    main()
