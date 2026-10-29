"""Orthographic design views of a blueprint.

Both views are projections of the same derived 3D geometry:

* ``top``      -- plan ``(x, y)`` seen from above (roofs, or one level's floors)
* elevations   -- ``north`` / ``east`` / ``south`` / ``west`` facades, seen
                  face-on from outside, projected to ``(u, z)`` where ``u`` is
                  the viewer's rightward axis and ``z`` is height.

Primitives are plain dicts so the renderer, hit-testing, and Pixel Studio
rasterization all share one description of what is visible.
"""

from __future__ import annotations

import math

from .blueprint_model import (
    ELEVATION_DIRECTIONS,
    OPENING_CLASSES,
    polygon_bbox,
    wall_surface_key,
)


# Unit vector pointing from the building toward a viewer standing outside.
VIEW_NORMALS = {
    "north": (0.0, -1.0),
    "south": (0.0, 1.0),
    "east": (1.0, 0.0),
    "west": (-1.0, 0.0),
}

VIEW_LABELS = {
    "top": "Top",
    "north": "North facade",
    "east": "East facade",
    "south": "South facade",
    "west": "West facade",
}


def project_elevation(point, direction):
    """Plan ``(x, y)`` -> ``(u, depth)`` for a facade view.

    ``u`` grows to the viewer's right; ``depth`` grows away from the viewer.
    """

    x, y = float(point[0]), float(point[1])
    if direction == "south":  # viewer south of the building, looking north
        return x, -y
    if direction == "north":  # looking south: east is on the viewer's left
        return -x, y
    if direction == "east":   # looking west: north is on the viewer's right
        return -y, -x
    return y, x               # west: looking east, south on the right


def elevation_primitives(blueprint, derived, direction):
    """Visible facade pieces for one compass direction, far-to-near."""

    if direction not in ELEVATION_DIRECTIONS:
        return []
    view_nx, view_ny = VIEW_NORMALS[direction]
    primitives = []
    for wall in derived.get("walls") or []:
        if wall.get("kind") != "exterior" or not wall.get("outward_normal"):
            continue
        nx, ny = wall["outward_normal"]
        facing = nx * view_nx + ny * view_ny
        if facing <= 0.05:
            continue
        # The visible face is the outer face, half a wall thickness outward.
        half = wall["thickness_m"] / 2.0
        start = (wall["start"][0] + nx * half, wall["start"][1] + ny * half)
        end = (wall["end"][0] + nx * half, wall["end"][1] + ny * half)
        u1, d1 = project_elevation(start, direction)
        u2, d2 = project_elevation(end, direction)
        if abs(u2 - u1) < 1e-6:
            continue
        base_z, top_z = wall["base_z"], wall["top_z"]
        depth = (d1 + d2) / 2.0
        surface_key = wall_surface_key(wall, outer=True)
        primitives.append({
            "kind": "wall",
            "polygon": [(u1, base_z), (u2, base_z), (u2, top_z), (u1, top_z)],
            "depth": depth,
            "surface_key": surface_key,
            "role": "facade",
            "wall_key": wall["key"],
            "level": wall["level"],
            "shade": 0.78 + 0.22 * facing,
        })
        length = wall["length_m"] or 1.0
        for opening in wall.get("openings") or []:
            low = opening["offset_m"] - opening["width_m"] / 2.0
            high = opening["offset_m"] + opening["width_m"] / 2.0
            a = (start[0] + (end[0] - start[0]) * low / length, start[1] + (end[1] - start[1]) * low / length)
            b = (start[0] + (end[0] - start[0]) * high / length, start[1] + (end[1] - start[1]) * high / length)
            ua, _ = project_elevation(a, direction)
            ub, _ = project_elevation(b, direction)
            z0 = base_z + opening["sill_m"]
            z1 = base_z + opening["head_m"]
            role = OPENING_CLASSES[opening["opening_class"]]["material_role"]
            primitives.append({
                "kind": "opening",
                "polygon": [(ua, z0), (ub, z0), (ub, z1), (ua, z1)],
                "depth": depth - 0.001,
                "surface_key": f"opening:{opening['key']}",
                "role": role,
                "opening_key": opening["key"],
                "opening_class": opening["opening_class"],
                "level": wall["level"],
                "shade": 0.78 + 0.22 * facing,
            })

    roof = derived.get("roof") or {}
    for gable in roof.get("gable_walls") or []:
        points = gable["points"]
        nx, ny = VIEW_NORMALS.get(gable.get("facing"), (0.0, 0.0))
        facing = nx * view_nx + ny * view_ny
        if facing <= 0.05:
            continue
        projected = [(project_elevation((p[0], p[1]), direction)[0], p[2]) for p in points]
        depth = sum(project_elevation((p[0], p[1]), direction)[1] for p in points) / len(points)
        primitives.append({
            "kind": "gable",
            "polygon": projected,
            "depth": depth,
            "surface_key": f"gable:{gable.get('facing')}",
            "role": "facade",
            "shade": 0.78 + 0.22 * facing,
        })
    for plane in roof.get("planes") or []:
        points = plane["points"]
        projected = [(project_elevation((p[0], p[1]), direction)[0], p[2]) for p in points]
        us = [p[0] for p in projected]
        zs = [p[1] for p in projected]
        if max(zs) - min(zs) < 1e-6 or max(us) - min(us) < 1e-6:
            continue
        depth = sum(project_elevation((p[0], p[1]), direction)[1] for p in points) / len(points)
        if abs(_polygon_area_2d(projected)) < 1e-4:
            # Seen edge-on (a gable verge): give the roof its build-up
            # thickness so the slope still reads in the facade.
            a, b = max(
                ((p, q) for p in projected for q in projected),
                key=lambda pair: math.dist(pair[0], pair[1]),
            )
            projected = [a, b, (b[0], b[1] + ROOF_BUILDUP_M), (a[0], a[1] + ROOF_BUILDUP_M)]
            primitives.append({
                "kind": "roof",
                "polygon": projected,
                "depth": depth - 1.0,
                "surface_key": "roof",
                "role": "roof",
                "roof_plane": plane["key"],
                "shade": 0.7,
            })
            continue
        primitives.append({
            "kind": "roof",
            "polygon": projected,
            "depth": depth - 0.5,
            "surface_key": "roof",
            "role": "roof",
            "roof_plane": plane["key"],
            "shade": _roof_plane_shade(points, (view_nx, view_ny)),
        })
    primitives.sort(key=lambda item: item["depth"], reverse=True)
    return primitives


ROOF_BUILDUP_M = 0.25


def _polygon_area_2d(points):
    total = 0.0
    for index in range(len(points)):
        x1, y1 = points[index]
        x2, y2 = points[(index + 1) % len(points)]
        total += x1 * y2 - x2 * y1
    return total / 2.0


def _plane_normal(points):
    if len(points) < 3:
        return 0.0, 0.0, 1.0
    (x0, y0, z0), (x1, y1, z1), (x2, y2, z2) = points[0], points[1], points[2]
    ux, uy, uz = x1 - x0, y1 - y0, z1 - z0
    vx, vy, vz = x2 - x0, y2 - y0, z2 - z0
    nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
    length = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
    nx, ny, nz = nx / length, ny / length, nz / length
    if nz < 0:
        nx, ny, nz = -nx, -ny, -nz
    return nx, ny, nz


def _roof_plane_shade(points, view_normal=None):
    """Simple fixed-light shading so roof planes read as 3D (light from NW)."""

    nx, ny, nz = _plane_normal(points)
    light = (-0.45, -0.45, 0.77)
    lambert = max(0.0, nx * light[0] + ny * light[1] + nz * light[2])
    return 0.62 + 0.38 * lambert


def top_primitives(blueprint, derived, *, show_roof=True, level_key=None):
    """Plan-view pieces: roofs (all levels, bottom-up) or one level's floors."""

    primitives = []
    levels = [level for level in derived.get("levels") or [] if level.get("rooms")]
    if show_roof:
        roof = derived.get("roof") or {}
        top_key = roof.get("level")
        pitched = roof.get("shape") != "flat"
        for level in levels:
            if pitched and level["key"] == top_key:
                continue
            for loop in level.get("outer_outlines") or []:
                primitives.append({
                    "kind": "roof",
                    "polygon": [tuple(p) for p in loop],
                    "z": level["top_z"],
                    "surface_key": "roof",
                    "role": "roof",
                    "level": level["key"],
                    "shade": 0.9,
                })
        if pitched:
            for plane in roof.get("planes") or []:
                primitives.append({
                    "kind": "roof",
                    "polygon": [(p[0], p[1]) for p in plane["points"]],
                    "z": max(p[2] for p in plane["points"]),
                    "surface_key": "roof",
                    "role": "roof",
                    "roof_plane": plane["key"],
                    "shade": _roof_plane_shade(plane["points"]),
                })
        return primitives

    for surface in derived.get("surfaces") or []:
        if surface.get("role") != "floor" or surface.get("level") != level_key:
            continue
        primitives.append({
            "kind": "floor",
            "polygon": [tuple(p) for p in surface.get("plan_points") or []],
            "z": surface.get("z", 0.0),
            "surface_key": surface["key"],
            "role": "floor",
            "room": surface.get("room"),
            "level": level_key,
            "shade": 1.0,
        })
    return primitives


def primitives_bounds(primitives):
    points = [p for primitive in primitives for p in primitive.get("polygon") or []]
    return polygon_bbox(points) if points else None


def view_frame(blueprint, derived, view_id, *, show_roof=True, level_key=None, margin_m=1.0):
    """Stable view rectangle for a design view (used for canvas sizing and
    as the Pixel Studio canvas extent)."""

    if view_id == "top":
        primitives = top_primitives(blueprint, derived, show_roof=True)
        primitives += top_primitives(blueprint, derived, show_roof=False, level_key=level_key)
    else:
        primitives = elevation_primitives(blueprint, derived, view_id)
    bounds = primitives_bounds(primitives)
    if bounds is None:
        return None
    min_u, min_v, max_u, max_v = bounds
    if view_id != "top":
        min_v = min(min_v, 0.0)
    return (min_u - margin_m, min_v - margin_m, max_u + margin_m, max_v + margin_m)
