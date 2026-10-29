"""Pixel-mask-backed 3D solid interaction fields for Species Sim.

Each logical mask is authored top-to-bottom in local x/z sprite space and is
extruded through a finite local y depth.  Growth queries operate in world 3D;
the renderer may project the same occupied cells into any 2D camera.
"""

from __future__ import annotations

import math
from typing import Any


MAX_MASK_SIZE = 64
MAX_SOLID_STRUCTURES = 24


def _finite_float(value, default=0.0):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float(default)
    return result if math.isfinite(result) else float(default)


def _normalise_mask_rows(value):
    if not isinstance(value, list) or not value:
        return []
    rows = []
    for raw_row in value[:MAX_MASK_SIZE]:
        if isinstance(raw_row, str):
            row = "".join("#" if char not in {".", "0", " ", "_"} else "." for char in raw_row)
        elif isinstance(raw_row, (list, tuple)):
            row = "".join("#" if bool(cell) else "." for cell in raw_row)
        else:
            continue
        rows.append(row[:MAX_MASK_SIZE])
    width = max((len(row) for row in rows), default=0)
    if width <= 0:
        return []
    return [row.ljust(width, ".") for row in rows if row]


def _normalise_color(value, default):
    if not isinstance(value, (list, tuple)) or len(value) < 3:
        return list(default)
    return [max(0, min(255, round(_finite_float(channel, default[index])))) for index, channel in enumerate(value[:3])]


def normalise_solid_structures(environment):
    """Decode bounded pixel solids from transient scene environment data."""

    environment = environment if isinstance(environment, dict) else {}
    values = environment.get("solid_structures")
    if not isinstance(values, list):
        return []
    solids = []
    for index, raw in enumerate(values[:MAX_SOLID_STRUCTURES]):
        if not isinstance(raw, dict):
            continue
        rows = _normalise_mask_rows(raw.get("mask_rows"))
        if not rows or not any("#" in row for row in rows):
            continue
        position = raw.get("position_m")
        if not isinstance(position, (list, tuple)) or len(position) < 3:
            continue
        x, y, z = (_finite_float(position[axis], float("nan")) for axis in range(3))
        if not all(math.isfinite(value) for value in (x, y, z)):
            continue
        pixel_size = _finite_float(raw.get("pixel_size_m"), 0.1)
        extrusion_depth = _finite_float(raw.get("extrusion_depth_m"), pixel_size)
        if pixel_size <= 0.0 or extrusion_depth <= 0.0:
            continue
        pixel_size = max(0.01, min(5.0, pixel_size))
        extrusion_depth = max(0.01, min(25.0, extrusion_depth))
        palette = raw.get("palette") if isinstance(raw.get("palette"), dict) else {}
        solids.append({
            "id": str(raw.get("id") or f"solid_structure_{index + 1}"),
            "kind": str(raw.get("kind") or "solid").strip().lower(),
            "position_m": [round(max(-1000.0, min(1000.0, value)), 4) for value in (x, y, z)],
            "rotation_deg": round(_finite_float(raw.get("rotation_deg"), 0.0) % 360.0, 4),
            "pixel_size_m": round(pixel_size, 5),
            "extrusion_depth_m": round(extrusion_depth, 5),
            "mask_rows": rows,
            "mask_width_px": len(rows[0]),
            "mask_height_px": len(rows),
            "palette": {
                "fill": _normalise_color(palette.get("fill"), (108, 101, 91)),
                "edge": _normalise_color(palette.get("edge"), (184, 174, 153)),
            },
        })
    return solids


class SolidStructureField:
    """Read-only collision queries over normalized extruded pixel masks."""

    def __init__(self, structures):
        self.structures = list(structures or [])

    @classmethod
    def from_environment(cls, environment):
        return cls(normalise_solid_structures(environment))

    @staticmethod
    def _world_to_local(structure, point):
        x, y, z = (float(point[0]), float(point[1]), float(point[2]))
        px, py, pz = structure["position_m"]
        angle = math.radians(float(structure["rotation_deg"]))
        cos_angle, sin_angle = math.cos(angle), math.sin(angle)
        dx, dy = x - px, y - py
        return (
            cos_angle * dx + sin_angle * dy,
            -sin_angle * dx + cos_angle * dy,
            z - pz,
        )

    @staticmethod
    def _local_to_world(structure, point):
        x, y, z = (float(point[0]), float(point[1]), float(point[2]))
        px, py, pz = structure["position_m"]
        angle = math.radians(float(structure["rotation_deg"]))
        cos_angle, sin_angle = math.cos(angle), math.sin(angle)
        return (
            px + cos_angle * x - sin_angle * y,
            py + sin_angle * x + cos_angle * y,
            pz + z,
        )

    @staticmethod
    def occupied_cell(structure, point):
        local_x, local_y, local_z = SolidStructureField._world_to_local(structure, point)
        pixel = float(structure["pixel_size_m"])
        if abs(local_y) > float(structure["extrusion_depth_m"]) * 0.5:
            return None
        if local_z < 0.0 or local_z >= int(structure["mask_height_px"]) * pixel:
            return None
        column = math.floor(local_x / pixel + int(structure["mask_width_px"]) * 0.5)
        row_from_bottom = math.floor(local_z / pixel)
        row = int(structure["mask_height_px"]) - 1 - row_from_bottom
        if not (0 <= row < int(structure["mask_height_px"]) and 0 <= column < int(structure["mask_width_px"])):
            return None
        if structure["mask_rows"][row][column] != "#":
            return None
        return row, column

    def contains(self, point):
        for structure in self.structures:
            cell = self.occupied_cell(structure, point)
            if cell is not None:
                return {"structure": structure, "cell": cell, "point_m": tuple(float(v) for v in point)}
        return None

    def segment_hit(self, start, end):
        """Return the first occupied sample along one 3D segment."""

        if not self.structures:
            return None
        start = tuple(float(value) for value in start[:3])
        end = tuple(float(value) for value in end[:3])
        length = math.dist(start, end)
        minimum_cell = min(
            min(float(item["pixel_size_m"]), float(item["extrusion_depth_m"]))
            for item in self.structures
        )
        steps = max(1, min(4096, int(math.ceil(length / max(0.003, minimum_cell * 0.24)))))
        previous = start
        for step in range(1, steps + 1):
            fraction = step / steps
            point = tuple(start[axis] + (end[axis] - start[axis]) * fraction for axis in range(3))
            hit = self.contains(point)
            if hit is not None:
                return {
                    **hit,
                    "fraction": round(fraction, 6),
                    "previous_point_m": previous,
                }
            previous = point
        return None

    def path_hit(self, points):
        points = [tuple(float(value) for value in point[:3]) for point in points if len(point) >= 3]
        for start, end in zip(points, points[1:]):
            hit = self.segment_hit(start, end)
            if hit is not None:
                return hit
        return None

    def nearest_ground_contact(self, origin, max_distance):
        """Find the nearest occupied ground-level cell face to an origin."""

        origin = tuple(float(value) for value in origin[:3])
        max_distance = max(0.0, float(max_distance))
        contacts = []
        for structure in self.structures:
            pixel = float(structure["pixel_size_m"])
            width = int(structure["mask_width_px"])
            height = int(structure["mask_height_px"])
            depth = float(structure["extrusion_depth_m"])
            local_origin = self._world_to_local(structure, origin)
            local_z = max(local_origin[2], min(0.045, pixel * 0.45))
            if not 0.0 <= local_z < height * pixel:
                continue
            row_from_bottom = min(height - 1, max(0, int(math.floor(local_z / pixel))))
            row = height - 1 - row_from_bottom
            occupied = [column for column, value in enumerate(structure["mask_rows"][row]) if value == "#"]
            best = None
            for column in occupied:
                left = (column - width * 0.5) * pixel
                right = left + pixel
                nearest_x = max(left, min(right, local_origin[0]))
                nearest_y = max(-depth * 0.5, min(depth * 0.5, local_origin[1]))
                dx, dy = nearest_x - local_origin[0], nearest_y - local_origin[1]
                planar_distance = math.hypot(dx, dy)
                candidate = (planar_distance, column, nearest_x, nearest_y, dx, dy)
                if best is None or candidate[:2] < best[:2]:
                    best = candidate
            if best is None or best[0] > max_distance + 1e-9:
                continue
            planar_distance, column, nearest_x, nearest_y, dx, dy = best
            if planar_distance <= 1e-9:
                # Invalid scene overlap: choose the nearest local face so the
                # returned contact still lies outside occupied volume.
                face_options = (
                    (abs(local_origin[0] - (column - width * 0.5) * pixel), -1.0, 0.0),
                    (abs((column + 1 - width * 0.5) * pixel - local_origin[0]), 1.0, 0.0),
                    (abs(local_origin[1] + depth * 0.5), 0.0, -1.0),
                    (abs(depth * 0.5 - local_origin[1]), 0.0, 1.0),
                )
                _distance, local_dx, local_dy = min(face_options, key=lambda item: item[0])
            else:
                local_dx, local_dy = dx / planar_distance, dy / planar_distance
            clearance = min(0.03, planar_distance * 0.5) if planar_distance > 1e-9 else 0.03
            exterior_local = (
                nearest_x - local_dx * clearance,
                nearest_y - local_dy * clearance,
                local_z,
            )
            collision_world = self._local_to_world(structure, (nearest_x, nearest_y, local_z))
            exterior_world = self._local_to_world(structure, exterior_local)
            angle = math.radians(float(structure["rotation_deg"]))
            direction = (
                math.cos(angle) * local_dx - math.sin(angle) * local_dy,
                math.sin(angle) * local_dx + math.cos(angle) * local_dy,
            )
            contacts.append({
                "structure": structure,
                "point_m": exterior_world,
                "collision_point_m": collision_world,
                "distance_m": math.dist(origin, exterior_world),
                "cell": (row, column),
                "direction": direction,
                "top_z_m": float(structure["position_m"][2]) + height * pixel,
            })
        return min(contacts, default=None, key=lambda item: (item["distance_m"], item["structure"]["id"]))

    def surface_point_at_z(
        self,
        structure,
        approach_direction,
        z,
        clearance=0.03,
        previous_point=None,
        preferred_local_tangent_m=None,
    ):
        """Return an exterior point beside an occupied mask cell at height z.

        ``preferred_local_tangent_m`` lets climbing growth move across the 2D
        surface while the occupied row still gates where attachment is valid.
        It is local x on a front/back face and local y on a side face.
        """

        pixel = float(structure["pixel_size_m"])
        local_z = float(z) - float(structure["position_m"][2])
        row_from_bottom = min(
            int(structure["mask_height_px"]) - 1,
            max(0, int(math.floor(local_z / pixel))),
        )
        row = int(structure["mask_height_px"]) - 1 - row_from_bottom
        occupied = [index for index, value in enumerate(structure["mask_rows"][row]) if value == "#"]
        if not occupied:
            return tuple(previous_point) if previous_point is not None else None

        angle = math.radians(float(structure["rotation_deg"]))
        cos_angle, sin_angle = math.cos(angle), math.sin(angle)
        world_dx, world_dy = float(approach_direction[0]), float(approach_direction[1])
        local_dx = cos_angle * world_dx + sin_angle * world_dy
        local_dy = -sin_angle * world_dx + cos_angle * world_dy
        previous_local = (
            self._world_to_local(structure, previous_point)
            if previous_point is not None else (0.0, 0.0, local_z)
        )
        width = int(structure["mask_width_px"])
        if abs(local_dx) >= abs(local_dy):
            if local_dx >= 0.0:
                column = min(occupied)
                local_x = (column - width * 0.5) * pixel - abs(float(clearance))
            else:
                column = max(occupied)
                local_x = (column + 1 - width * 0.5) * pixel + abs(float(clearance))
            preferred_y = previous_local[1] if preferred_local_tangent_m is None else float(preferred_local_tangent_m)
            local_y = max(
                -float(structure["extrusion_depth_m"]) * 0.5,
                min(float(structure["extrusion_depth_m"]) * 0.5, preferred_y),
            )
        else:
            preferred_x = previous_local[0] if preferred_local_tangent_m is None else float(preferred_local_tangent_m)
            column = min(occupied, key=lambda value: abs((value + 0.5 - width * 0.5) * pixel - preferred_x))
            cell_left = (column - width * 0.5) * pixel
            cell_right = cell_left + pixel
            inset = min(pixel * 0.08, 0.005)
            local_x = max(cell_left + inset, min(cell_right - inset, preferred_x))
            local_y = (
                -float(structure["extrusion_depth_m"]) * 0.5 - abs(float(clearance))
                if local_dy >= 0.0
                else float(structure["extrusion_depth_m"]) * 0.5 + abs(float(clearance))
            )
        return self._local_to_world(structure, (local_x, local_y, local_z))

    @staticmethod
    def bounds_m(structure):
        width = int(structure["mask_width_px"]) * float(structure["pixel_size_m"])
        depth = float(structure["extrusion_depth_m"])
        height = int(structure["mask_height_px"]) * float(structure["pixel_size_m"])
        corners = [
            SolidStructureField._local_to_world(structure, (x, y, z))
            for x in (-width * 0.5, width * 0.5)
            for y in (-depth * 0.5, depth * 0.5)
            for z in (0.0, height)
        ]
        return (
            min(point[0] for point in corners), max(point[0] for point in corners),
            min(point[1] for point in corners), max(point[1] for point in corners),
            min(point[2] for point in corners), max(point[2] for point in corners),
        )
