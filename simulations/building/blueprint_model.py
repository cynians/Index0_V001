"""Building blueprint model: authored floorplan data plus derived geometry.

Plan space is metric: ``x`` grows east, ``y`` grows south (screen-down, the
same convention Site Simulation uses) and ``z`` grows up.  Rooms are authored
as polygons drawn on wall centerlines.  Everything else -- walls, the building
outline, gross/net areas, surfaces, the roof, and placement transforms -- is
derived from the authored rooms, levels, openings, and fixtures and is never
stored.  See docs/building_blueprint_concept_v001.md.

The blueprint itself is a plain JSON-compatible dict so it can live in a
fingerprinted asset file (``assets/buildings/<id>.json.gz``) next to its
ontology entity, following the plant blueprint precedent.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from typing import Any, Iterable


SCHEMA_VERSION = 1
PIXELS_PER_METER = 16
DEFAULT_SNAP_M = 0.5
DEFAULT_LEVEL_HEIGHT_M = 3.0
POINT_TOLERANCE_M = 1e-3
KEY_DECIMALS = 4

MODEL_SPACE = {
    "dimensions": 3,
    "up_axis": "z",
    "plan_axes": ["x", "y"],
    "plan_y_direction": "south",
    "units": "m",
    "projection": "orthographic",
    "asset_dimension": 2,
    "pixels_per_meter": PIXELS_PER_METER,
}

DEFAULT_WALL_CLASSES = {
    "exterior": {"label": "Exterior wall", "thickness_m": 0.30},
    "interior": {"label": "Interior wall", "thickness_m": 0.12},
}

# Opening vocabulary: geometry defaults for placement, plus whether people can
# walk through it.  Materials are never implied here; they come from the
# blueprint's own material assignments.
OPENING_CLASSES = {
    "door": {"label": "Door", "width_m": 1.0, "sill_m": 0.0, "head_m": 2.1, "passable": True, "material_role": "door"},
    "double_door": {"label": "Double door", "width_m": 2.0, "sill_m": 0.0, "head_m": 2.2, "passable": True, "material_role": "door"},
    "doorway": {"label": "Open doorway", "width_m": 1.4, "sill_m": 0.0, "head_m": 2.2, "passable": True, "material_role": None},
    "loading_door": {"label": "Loading door", "width_m": 4.0, "sill_m": 0.0, "head_m": 3.5, "passable": True, "material_role": "door"},
    "window": {"label": "Window", "width_m": 1.2, "sill_m": 0.9, "head_m": 2.1, "passable": False, "material_role": "window"},
}
OPENING_CLASS_ORDER = ("door", "double_door", "doorway", "loading_door", "window")

# Surface roles a material can be assigned to.  ``default_materials`` maps a
# role to a material entity id; ``surface_materials`` overrides one surface.
MATERIAL_ROLES = ("facade", "interior_wall", "floor", "ceiling", "roof", "window", "door")
MATERIAL_ROLE_LABELS = {
    "facade": "Facade",
    "interior_wall": "Interior walls",
    "floor": "Floors",
    "ceiling": "Ceilings",
    "roof": "Roof",
    "window": "Windows",
    "door": "Doors",
}

ROOF_SHAPES = ("flat", "shed", "gable", "hip")
ELEVATION_DIRECTIONS = ("north", "east", "south", "west")

DEFAULT_FIXTURE_SIZE_M = (0.8, 0.6)


# ---------------------------------------------------------------------------
# Blueprint construction / normalization
# ---------------------------------------------------------------------------


def new_blueprint(blueprint_id: str, display_name: str | None = None) -> dict[str, Any]:
    """Return an empty single-level blueprint."""

    return normalize_blueprint({
        "blueprint_id": str(blueprint_id or "blueprint"),
        "display_name": str(display_name or blueprint_id or "Building Blueprint"),
    })


def _float(value: Any, default: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float(default)
    if math.isnan(result) or math.isinf(result):
        return float(default)
    return result


def _point(value: Any) -> tuple[float, float] | None:
    if isinstance(value, dict):
        value = (value.get("x"), value.get("y"))
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    try:
        x, y = float(value[0]), float(value[1])
    except (TypeError, ValueError):
        return None
    if any(math.isnan(v) or math.isinf(v) for v in (x, y)):
        return None
    return x, y


def _points(values: Any) -> list[tuple[float, float]]:
    result = []
    for value in values or []:
        point = _point(value)
        if point is not None:
            result.append(point)
    return result


def normalize_blueprint(raw: Any) -> dict[str, Any]:
    """Return a complete, JSON-compatible blueprint dict.

    Unknown top-level keys are preserved so newer fields survive a round trip
    through older code.
    """

    source = copy.deepcopy(raw) if isinstance(raw, dict) else {}
    blueprint = dict(source)
    blueprint["schema_version"] = SCHEMA_VERSION
    blueprint["kind"] = "building_blueprint"
    blueprint["blueprint_id"] = str(source.get("blueprint_id") or "blueprint")
    blueprint["display_name"] = str(source.get("display_name") or blueprint["blueprint_id"])
    blueprint["model_space"] = {**MODEL_SPACE, **dict(source.get("model_space") or {})}

    grid = dict(source.get("grid") or {})
    blueprint["grid"] = {"snap_m": max(0.05, _float(grid.get("snap_m"), DEFAULT_SNAP_M))}

    levels = []
    seen_levels = set()
    for index, raw_level in enumerate(source.get("levels") or []):
        if not isinstance(raw_level, dict):
            continue
        key = str(raw_level.get("key") or f"L{index}")
        if key in seen_levels:
            continue
        seen_levels.add(key)
        levels.append({
            "key": key,
            "name": str(raw_level.get("name") or level_default_name(index)),
            "elevation_m": _float(raw_level.get("elevation_m"), index * DEFAULT_LEVEL_HEIGHT_M),
            "height_m": max(1.0, _float(raw_level.get("height_m"), DEFAULT_LEVEL_HEIGHT_M)),
        })
    if not levels:
        levels = [{"key": "L0", "name": level_default_name(0), "elevation_m": 0.0, "height_m": DEFAULT_LEVEL_HEIGHT_M}]
    levels.sort(key=lambda level: level["elevation_m"])
    blueprint["levels"] = levels
    level_keys = {level["key"] for level in levels}
    first_level = levels[0]["key"]

    wall_classes = copy.deepcopy(DEFAULT_WALL_CLASSES)
    for class_key, values in dict(source.get("wall_classes") or {}).items():
        if class_key in wall_classes and isinstance(values, dict):
            wall_classes[class_key]["thickness_m"] = max(
                0.02, _float(values.get("thickness_m"), wall_classes[class_key]["thickness_m"])
            )
            for extra_key, extra_value in values.items():
                if extra_key not in {"thickness_m"}:
                    wall_classes[class_key][extra_key] = extra_value
    blueprint["wall_classes"] = wall_classes

    rooms = []
    seen_rooms = set()
    for index, raw_room in enumerate(source.get("rooms") or []):
        if not isinstance(raw_room, dict):
            continue
        points = _points(raw_room.get("points"))
        if len(points) < 3:
            continue
        key = str(raw_room.get("key") or f"r{index + 1:03d}")
        if key in seen_rooms:
            continue
        seen_rooms.add(key)
        level = str(raw_room.get("level") or first_level)
        room = dict(raw_room)
        room.update({
            "key": key,
            "level": level if level in level_keys else first_level,
            "name": str(raw_room.get("name") or f"Room {index + 1}"),
            "points": [[round(x, 6), round(y, 6)] for x, y in points],
        })
        rooms.append(room)
    blueprint["rooms"] = rooms

    openings = []
    seen_openings = set()
    for index, raw_opening in enumerate(source.get("openings") or []):
        if not isinstance(raw_opening, dict):
            continue
        center = _point(raw_opening.get("center"))
        if center is None:
            continue
        key = str(raw_opening.get("key") or f"o{index + 1:03d}")
        if key in seen_openings:
            continue
        seen_openings.add(key)
        opening_class = str(raw_opening.get("opening_class") or "door")
        defaults = OPENING_CLASSES.get(opening_class, OPENING_CLASSES["door"])
        level = str(raw_opening.get("level") or first_level)
        opening = dict(raw_opening)
        opening.update({
            "key": key,
            "level": level if level in level_keys else first_level,
            "center": [round(center[0], 6), round(center[1], 6)],
            "opening_class": opening_class if opening_class in OPENING_CLASSES else "door",
            "width_m": max(0.3, _float(raw_opening.get("width_m"), defaults["width_m"])),
            "sill_m": max(0.0, _float(raw_opening.get("sill_m"), defaults["sill_m"])),
            "head_m": max(0.5, _float(raw_opening.get("head_m"), defaults["head_m"])),
        })
        openings.append(opening)
    blueprint["openings"] = openings

    fixtures = []
    seen_fixtures = set()
    for index, raw_fixture in enumerate(source.get("fixtures") or []):
        if not isinstance(raw_fixture, dict):
            continue
        position = _point(raw_fixture.get("position"))
        ref = str(raw_fixture.get("ref") or raw_fixture.get("item") or "").strip()
        if position is None or not ref:
            continue
        key = str(raw_fixture.get("key") or f"f{index + 1:03d}")
        if key in seen_fixtures:
            continue
        seen_fixtures.add(key)
        size = _point(raw_fixture.get("size_m")) or DEFAULT_FIXTURE_SIZE_M
        level = str(raw_fixture.get("level") or first_level)
        fixture = dict(raw_fixture)
        fixture.pop("item", None)
        fixture.update({
            "key": key,
            "ref": ref,
            "level": level if level in level_keys else first_level,
            "position": [round(position[0], 6), round(position[1], 6)],
            "rotation_deg": _float(raw_fixture.get("rotation_deg"), 0.0) % 360.0,
            "size_m": [max(0.1, size[0]), max(0.1, size[1])],
        })
        fixtures.append(fixture)
    blueprint["fixtures"] = fixtures

    features = []
    for index, raw_feature in enumerate(source.get("vertical_features") or []):
        if not isinstance(raw_feature, dict):
            continue
        points = _points(raw_feature.get("points"))
        if len(points) < 3:
            continue
        feature = dict(raw_feature)
        from_level = str(raw_feature.get("from_level") or first_level)
        feature.update({
            "key": str(raw_feature.get("key") or f"v{index + 1:03d}"),
            "kind": str(raw_feature.get("kind") or "stair"),
            "from_level": from_level if from_level in level_keys else first_level,
            "to_level": str(raw_feature.get("to_level") or ""),
            "points": [[round(x, 6), round(y, 6)] for x, y in points],
        })
        features.append(feature)
    blueprint["vertical_features"] = features

    roof = dict(source.get("roof") or {})
    shape = str(roof.get("shape") or "flat")
    blueprint["roof"] = {
        "shape": shape if shape in ROOF_SHAPES else "flat",
        "pitch_deg": max(0.0, min(75.0, _float(roof.get("pitch_deg"), 30.0))),
        "ridge_axis": "y" if str(roof.get("ridge_axis") or "x") == "y" else "x",
        "overhang_m": max(0.0, min(3.0, _float(roof.get("overhang_m"), 0.3))),
    }

    blueprint["default_materials"] = {
        str(role): str(material)
        for role, material in dict(source.get("default_materials") or {}).items()
        if role in MATERIAL_ROLES and material
    }
    blueprint["surface_materials"] = {
        str(key): str(material)
        for key, material in dict(source.get("surface_materials") or {}).items()
        if key and material
    }
    details = {}
    for view_key, detail in dict(source.get("view_details") or {}).items():
        if isinstance(detail, dict) and isinstance(detail.get("layers"), list):
            details[str(view_key)] = detail
    blueprint["view_details"] = details
    return blueprint


def level_default_name(index: int) -> str:
    if index == 0:
        return "Ground floor"
    suffix = "th"
    if index % 100 not in {11, 12, 13}:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(index % 10, "th")
    return f"{index}{suffix} floor"


def blueprint_fingerprint(blueprint: dict[str, Any]) -> str:
    payload = json.dumps(normalize_blueprint(blueprint), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def next_key(existing: Iterable[str], prefix: str) -> str:
    used = set(existing)
    index = 1
    while f"{prefix}{index:03d}" in used:
        index += 1
    return f"{prefix}{index:03d}"


def level_by_key(blueprint: dict[str, Any], level_key: str) -> dict[str, Any] | None:
    for level in blueprint.get("levels") or []:
        if level.get("key") == level_key:
            return level
    return None


# ---------------------------------------------------------------------------
# Plane geometry
# ---------------------------------------------------------------------------


def polygon_signed_area(points: list[tuple[float, float]]) -> float:
    total = 0.0
    count = len(points)
    for index in range(count):
        x1, y1 = points[index]
        x2, y2 = points[(index + 1) % count]
        total += x1 * y2 - x2 * y1
    return total / 2.0


def polygon_area(points: list[tuple[float, float]]) -> float:
    return abs(polygon_signed_area(points))


def polygon_perimeter(points: list[tuple[float, float]]) -> float:
    return sum(math.dist(points[index], points[(index + 1) % len(points)]) for index in range(len(points)))


def polygon_centroid(points: list[tuple[float, float]]) -> tuple[float, float]:
    area = polygon_signed_area(points)
    if abs(area) < 1e-12:
        if not points:
            return 0.0, 0.0
        return (sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points))
    cx = cy = 0.0
    for index in range(len(points)):
        x1, y1 = points[index]
        x2, y2 = points[(index + 1) % len(points)]
        cross = x1 * y2 - x2 * y1
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    return cx / (6.0 * area), cy / (6.0 * area)


def polygon_bbox(points: Iterable[tuple[float, float]]) -> tuple[float, float, float, float] | None:
    points = list(points)
    if not points:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def point_segment_distance(point, start, end) -> tuple[float, float]:
    """Return ``(distance, t)`` from ``point`` to the segment, ``t`` in [0, 1]."""

    px, py = point
    ax, ay = start
    bx, by = end
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq <= 1e-18:
        return math.dist(point, start), 0.0
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
    return math.dist(point, (ax + dx * t, ay + dy * t)), t


def point_on_boundary(point, points, tolerance=POINT_TOLERANCE_M) -> bool:
    for index in range(len(points)):
        if point_segment_distance(point, points[index], points[(index + 1) % len(points)])[0] <= tolerance:
            return True
    return False


def point_in_polygon(point, points) -> bool:
    """Even-odd test.  Boundary points may report either result; callers that
    care use :func:`point_on_boundary` first."""

    x, y = point
    inside = False
    count = len(points)
    j = count - 1
    for i in range(count):
        xi, yi = points[i]
        xj, yj = points[j]
        if (yi > y) != (yj > y):
            crossing = (xj - xi) * (y - yi) / ((yj - yi) or 1e-18) + xi
            if x < crossing:
                inside = not inside
        j = i
    return inside


def point_strictly_inside(point, points, tolerance=POINT_TOLERANCE_M) -> bool:
    return not point_on_boundary(point, points, tolerance) and point_in_polygon(point, points)


def _orientation(a, b, c) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def segments_properly_cross(a, b, c, d, tolerance=1e-9) -> bool:
    """True when the segments cross at a single point interior to both."""

    o1 = _orientation(a, b, c)
    o2 = _orientation(a, b, d)
    o3 = _orientation(c, d, a)
    o4 = _orientation(c, d, b)
    return (
        ((o1 > tolerance and o2 < -tolerance) or (o1 < -tolerance and o2 > tolerance))
        and ((o3 > tolerance and o4 < -tolerance) or (o3 < -tolerance and o4 > tolerance))
    )


def polygon_is_simple(points: list[tuple[float, float]]) -> bool:
    count = len(points)
    if count < 3 or polygon_area(points) < 1e-6:
        return False
    for i in range(count):
        a, b = points[i], points[(i + 1) % count]
        if math.dist(a, b) < POINT_TOLERANCE_M:
            return False
        for j in range(i + 1, count):
            if abs(i - j) <= 1 or (i == 0 and j == count - 1):
                continue
            c, d = points[j], points[(j + 1) % count]
            if segments_properly_cross(a, b, c, d):
                return False
    return True


def _inward_probe_points(points, offset=0.01) -> list[tuple[float, float]]:
    """Points just inside the polygon next to each edge midpoint."""

    probes = []
    for index in range(len(points)):
        a = points[index]
        b = points[(index + 1) % len(points)]
        length = math.dist(a, b)
        if length < 1e-9:
            continue
        mx, my = (a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0
        nx, ny = -(b[1] - a[1]) / length, (b[0] - a[0]) / length
        candidate = (mx + nx * offset, my + ny * offset)
        if not point_in_polygon(candidate, points):
            candidate = (mx - nx * offset, my - ny * offset)
        probes.append(candidate)
    return probes


def polygons_overlap(first, second) -> bool:
    """True when the polygon interiors intersect.  Shared edges, partial shared
    edges (T-junctions), and shared vertices are allowed -- that is how
    neighbouring rooms meet."""

    first = list(first)
    second = list(second)
    if len(first) < 3 or len(second) < 3:
        return False
    box_a, box_b = polygon_bbox(first), polygon_bbox(second)
    if (box_a[2] <= box_b[0] + POINT_TOLERANCE_M or box_b[2] <= box_a[0] + POINT_TOLERANCE_M
            or box_a[3] <= box_b[1] + POINT_TOLERANCE_M or box_b[3] <= box_a[1] + POINT_TOLERANCE_M):
        return False
    for i in range(len(first)):
        a, b = first[i], first[(i + 1) % len(first)]
        for j in range(len(second)):
            if segments_properly_cross(a, b, second[j], second[(j + 1) % len(second)]):
                return True
    for probe in _inward_probe_points(first):
        if point_strictly_inside(probe, second):
            return True
    for probe in _inward_probe_points(second):
        if point_strictly_inside(probe, first):
            return True
    for vertex in first:
        if point_strictly_inside(vertex, second):
            return True
    for vertex in second:
        if point_strictly_inside(vertex, first):
            return True
    return False


def offset_polygon(points, offsets, outward=False):
    """Offset each edge by its own distance (mitered corners).

    ``offsets[i]`` belongs to the edge from ``points[i]`` to ``points[i + 1]``.
    Offsets move inward unless ``outward`` is set.  Returns ``None`` when the
    result would be degenerate (the caller falls back to an estimate).
    """

    count = len(points)
    if count < 3 or len(offsets) != count:
        return None
    orientation = 1.0 if polygon_signed_area(points) > 0 else -1.0
    lines = []
    for index in range(count):
        a = points[index]
        b = points[(index + 1) % count]
        length = math.dist(a, b)
        if length < 1e-9:
            return None
        dx, dy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
        # For positive signed area (counter-clockwise in math axes) the
        # interior lies to the left of each directed edge.
        nx, ny = -dy * orientation, dx * orientation
        if outward:
            nx, ny = -nx, -ny
        distance = float(offsets[index])
        lines.append(((a[0] + nx * distance, a[1] + ny * distance), (dx, dy)))
    result = []
    for index in range(count):
        (p1, d1) = lines[index - 1]
        (p2, d2) = lines[index]
        cross = d1[0] * d2[1] - d1[1] * d2[0]
        if abs(cross) < 1e-9:
            result.append(p2)
            continue
        t = ((p2[0] - p1[0]) * d2[1] - (p2[1] - p1[1]) * d2[0]) / cross
        result.append((p1[0] + d1[0] * t, p1[1] + d1[1] * t))
    new_area = polygon_signed_area(result)
    if new_area == 0 or (new_area > 0) != (orientation > 0):
        return None
    if not outward and abs(new_area) > polygon_area(points) + 1e-9:
        return None
    if outward and abs(new_area) < polygon_area(points) - 1e-9:
        return None
    return result


def rotate_point(point, degrees):
    radians = math.radians(float(degrees or 0.0))
    cos_a, sin_a = math.cos(radians), math.sin(radians)
    x, y = point
    return x * cos_a - y * sin_a, x * sin_a + y * cos_a


def rectangle_points(center, size, rotation_deg=0.0):
    cx, cy = center
    hw, hd = size[0] / 2.0, size[1] / 2.0
    corners = [(-hw, -hd), (hw, -hd), (hw, hd), (-hw, hd)]
    return [
        (cx + rx, cy + ry)
        for rx, ry in (rotate_point(corner, rotation_deg) for corner in corners)
    ]


def _key_point(point) -> tuple[float, float]:
    return round(point[0], KEY_DECIMALS), round(point[1], KEY_DECIMALS)


def _segment_key(a, b):
    ka, kb = _key_point(a), _key_point(b)
    return (ka, kb) if ka <= kb else (kb, ka)


# ---------------------------------------------------------------------------
# Derivation
# ---------------------------------------------------------------------------


def room_polygon(room: dict[str, Any]) -> list[tuple[float, float]]:
    return _points(room.get("points"))


def rooms_on_level(blueprint: dict[str, Any], level_key: str) -> list[dict[str, Any]]:
    return [room for room in blueprint.get("rooms") or [] if room.get("level") == level_key]


def validate_room_polygon(blueprint, level_key, points, ignore_room_key=None) -> str | None:
    """Return a human-readable problem with a proposed room polygon, or None."""

    blueprint = normalize_blueprint(blueprint)
    points = _points(points)
    if len(points) < 3:
        return "A room needs at least three corners"
    count = len(points)
    for i in range(count):
        for j in range(i + 2, count):
            if i == 0 and j == count - 1:
                continue
            if segments_properly_cross(points[i], points[(i + 1) % count], points[j], points[(j + 1) % count]):
                return "Room outline crosses itself"
    if polygon_area(points) < 0.25:
        return "Room is smaller than 0.25 m²"
    if not polygon_is_simple(points):
        return "Room outline has repeated corners"
    for other in rooms_on_level(blueprint, level_key):
        if other.get("key") == ignore_room_key:
            continue
        if polygons_overlap(points, room_polygon(other)):
            return f"Overlaps {other.get('name') or other.get('key')}"
    return None


def _split_level_edges(rooms):
    """Split every room edge at the other rooms' vertices lying on it.

    Returns ``{segment_key: {"a", "b", "sides": [(room_key, edge_index)]}}``.
    """

    vertices = []
    for room in rooms:
        vertices.extend(room_polygon(room))
    segments: dict[tuple, dict[str, Any]] = {}
    for room in rooms:
        points = room_polygon(room)
        for edge_index in range(len(points)):
            a = points[edge_index]
            b = points[(edge_index + 1) % len(points)]
            length = math.dist(a, b)
            if length < POINT_TOLERANCE_M:
                continue
            params = {0.0, 1.0}
            for vertex in vertices:
                distance, t = point_segment_distance(vertex, a, b)
                if distance <= POINT_TOLERANCE_M and POINT_TOLERANCE_M / length < t < 1.0 - POINT_TOLERANCE_M / length:
                    params.add(t)
            ordered = sorted(params)
            for t0, t1 in zip(ordered, ordered[1:]):
                p0 = (a[0] + (b[0] - a[0]) * t0, a[1] + (b[1] - a[1]) * t0)
                p1 = (a[0] + (b[0] - a[0]) * t1, a[1] + (b[1] - a[1]) * t1)
                if math.dist(p0, p1) < POINT_TOLERANCE_M:
                    continue
                key = _segment_key(p0, p1)
                entry = segments.setdefault(key, {"a": key[0], "b": key[1], "sides": []})
                side = (room["key"], edge_index)
                if side not in entry["sides"]:
                    entry["sides"].append(side)
    return segments


def _merge_wall_runs(segments):
    """Chain collinear atomic segments with identical room sides into runs."""

    incident: dict[tuple, list[tuple]] = {}
    for key, entry in segments.items():
        incident.setdefault(entry["a"], []).append(key)
        incident.setdefault(entry["b"], []).append(key)

    def direction(entry):
        (ax, ay), (bx, by) = entry["a"], entry["b"]
        length = math.hypot(bx - ax, by - ay) or 1.0
        return (bx - ax) / length, (by - ay) / length

    def compatible(first, second):
        if sorted(first["sides"]) != sorted(second["sides"]):
            return False
        d1, d2 = direction(first), direction(second)
        return abs(d1[0] * d2[1] - d1[1] * d2[0]) < 1e-6

    visited = set()
    runs = []
    for key in sorted(segments):
        if key in visited:
            continue
        visited.add(key)
        entry = segments[key]
        chain_points = [entry["a"], entry["b"]]
        for end_index in (0, -1):
            while True:
                endpoint = chain_points[end_index]
                neighbours = incident.get(endpoint, [])
                if len(neighbours) != 2:
                    break
                other = next((item for item in neighbours if item not in visited), None)
                if other is None or not compatible(entry, segments[other]):
                    break
                visited.add(other)
                other_entry = segments[other]
                far = other_entry["b"] if other_entry["a"] == endpoint else other_entry["a"]
                if end_index == 0:
                    chain_points.insert(0, far)
                else:
                    chain_points.append(far)
        runs.append({"start": chain_points[0], "end": chain_points[-1], "sides": sorted(entry["sides"])})
    return runs


def _chain_loops(runs):
    """Chain exterior runs into closed outline loops (list of point lists)."""

    remaining = [(run["start"], run["end"]) for run in runs]
    loops = []
    while remaining:
        start, end = remaining.pop(0)
        loop = [start, end]
        progressed = True
        while progressed and _key_point(loop[-1]) != _key_point(loop[0]):
            progressed = False
            for index, (a, b) in enumerate(remaining):
                if _key_point(a) == _key_point(loop[-1]):
                    loop.append(b)
                elif _key_point(b) == _key_point(loop[-1]):
                    loop.append(a)
                else:
                    continue
                remaining.pop(index)
                progressed = True
                break
        if len(loop) >= 4 and _key_point(loop[-1]) == _key_point(loop[0]):
            loop = loop[:-1]
            loops.append(_simplify_collinear(loop))
    return loops


def _simplify_collinear(points):
    result = list(points)
    changed = True
    while changed and len(result) > 3:
        changed = False
        for index in range(len(result)):
            prev_point = result[index - 1]
            point = result[index]
            next_point = result[(index + 1) % len(result)]
            if abs(_orientation(prev_point, point, next_point)) < 1e-9:
                result.pop(index)
                changed = True
                break
    return result


def _outward_normal(start, end, room_points):
    length = math.dist(start, end) or 1.0
    dx, dy = (end[0] - start[0]) / length, (end[1] - start[1]) / length
    nx, ny = -dy, dx
    mid = ((start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0)
    probe = (mid[0] + nx * 0.02, mid[1] + ny * 0.02)
    if point_in_polygon(probe, room_points):
        nx, ny = -nx, -ny
    return nx, ny


def facing_direction(normal) -> str:
    """Compass direction a wall with this outward plan normal faces."""

    nx, ny = normal
    if abs(nx) >= abs(ny):
        return "east" if nx > 0 else "west"
    return "south" if ny > 0 else "north"


def derive_geometry(blueprint: dict[str, Any]) -> dict[str, Any]:
    """Derive walls, outlines, areas, surfaces, and roof from a blueprint."""

    blueprint = normalize_blueprint(blueprint)
    wall_classes = blueprint["wall_classes"]
    exterior_t = wall_classes["exterior"]["thickness_m"]
    interior_t = wall_classes["interior"]["thickness_m"]
    rooms_by_key = {room["key"]: room for room in blueprint["rooms"]}

    levels_out = []
    all_walls = []
    surfaces = []
    room_metrics = {}
    for level in blueprint["levels"]:
        level_key = level["key"]
        base_z = level["elevation_m"]
        top_z = base_z + level["height_m"]
        level_rooms = rooms_on_level(blueprint, level_key)
        segments = _split_level_edges(level_rooms)
        runs = _merge_wall_runs(segments)

        walls = []
        edge_thickness: dict[tuple, list[tuple[float, float]]] = {}
        for index, run in enumerate(runs):
            start, end = run["start"], run["end"]
            length = math.dist(start, end)
            kind = "exterior" if len(run["sides"]) == 1 else "interior"
            thickness = exterior_t if kind == "exterior" else interior_t
            room_keys = [side[0] for side in run["sides"]]
            normal = None
            facing = None
            if kind == "exterior":
                room = rooms_by_key.get(room_keys[0])
                normal = _outward_normal(start, end, room_polygon(room) if room else [])
                facing = facing_direction(normal)
            wall = {
                "key": f"{level_key}:w{index:03d}",
                "level": level_key,
                "kind": kind,
                "start": list(start),
                "end": list(end),
                "length_m": length,
                "thickness_m": thickness,
                "base_z": base_z,
                "top_z": top_z,
                "sides": [list(side) for side in run["sides"]],
                "rooms": room_keys,
                "outward_normal": list(normal) if normal else None,
                "facing": facing,
                "openings": [],
            }
            walls.append(wall)
            for side in run["sides"]:
                edge_thickness.setdefault(tuple(side), []).append((length, thickness))

        _attach_openings(blueprint, level_key, walls)

        exterior_runs = [run for run in runs if len(run["sides"]) == 1]
        loops = _chain_loops(exterior_runs)
        loops.sort(key=polygon_area, reverse=True)
        outer_loops = []
        hole_loops = []
        for loop in loops:
            probe = _inward_probe_points(loop)[0] if loop else None
            if probe is not None and any(point_strictly_inside(probe, other) for other in outer_loops):
                hole_loops.append(loop)
            else:
                outer_loops.append(loop)

        level_gross_centerline = 0.0
        level_net = 0.0
        for room in level_rooms:
            points = room_polygon(room)
            gross = polygon_area(points)
            offsets = []
            for edge_index in range(len(points)):
                entries = edge_thickness.get((room["key"], edge_index)) or []
                total = sum(length for length, _t in entries)
                weighted = sum(length * t for length, t in entries)
                offsets.append((weighted / total if total > 0 else exterior_t) / 2.0)
            inset = offset_polygon(points, offsets)
            if inset is not None:
                net = polygon_area(inset)
            else:
                net = max(0.0, gross - sum(
                    math.dist(points[i], points[(i + 1) % len(points)]) * offsets[i]
                    for i in range(len(points))
                ))
                inset = points
            fixtures_inside = [
                fixture["key"] for fixture in blueprint["fixtures"]
                if fixture["level"] == level_key and point_in_polygon(_point(fixture["position"]), points)
            ]
            room_metrics[room["key"]] = {
                "key": room["key"],
                "name": room["name"],
                "level": level_key,
                "gross_area_m2": gross,
                "net_area_m2": net,
                "perimeter_m": polygon_perimeter(points),
                "centroid": list(polygon_centroid(points)),
                "net_outline": [list(p) for p in inset],
                "fixtures": fixtures_inside,
            }
            level_gross_centerline += gross
            level_net += net
            surfaces.append(_surface("room:%s:floor" % room["key"], "floor", level_key, room["key"],
                                     plan_points=points, z=base_z))
            surfaces.append(_surface("room:%s:ceiling" % room["key"], "ceiling", level_key, room["key"],
                                     plan_points=points, z=top_z))
            for edge_index in range(len(points)):
                surfaces.append(_surface(
                    f"room:{room['key']}:edge:{edge_index}:inner", "interior_wall", level_key, room["key"],
                    edge_index=edge_index,
                ))

        outer_outlines = []
        gross_outer = 0.0
        for loop in outer_loops:
            outset = offset_polygon(loop, [exterior_t / 2.0] * len(loop), outward=True)
            outline = outset or loop
            outer_outlines.append([list(p) for p in outline])
            gross_outer += polygon_area(outline)
        for loop in hole_loops:
            inset = offset_polygon(loop, [exterior_t / 2.0] * len(loop))
            gross_outer -= polygon_area(inset or loop)
        if not outer_loops:
            gross_outer = level_gross_centerline

        for wall in walls:
            if wall["kind"] != "exterior":
                continue
            room_key, edge_index = wall["sides"][0]
            key = f"room:{room_key}:edge:{edge_index}:outer"
            if not any(surface["key"] == key for surface in surfaces):
                surfaces.append(_surface(key, "facade", level_key, room_key, edge_index=edge_index))

        levels_out.append({
            "key": level_key,
            "name": level["name"],
            "elevation_m": base_z,
            "height_m": level["height_m"],
            "top_z": top_z,
            "rooms": [room["key"] for room in level_rooms],
            "walls": walls,
            "outline_loops": [[list(p) for p in loop] for loop in outer_loops],
            "hole_loops": [[list(p) for p in loop] for loop in hole_loops],
            "outer_outlines": outer_outlines,
            "gross_area_m2": gross_outer,
            "centerline_area_m2": level_gross_centerline,
            "net_area_m2": level_net,
        })
        all_walls.extend(walls)

    occupied_levels = [level for level in levels_out if level["rooms"]]
    ground = occupied_levels[0] if occupied_levels else (levels_out[0] if levels_out else None)
    roof = _derive_roof(blueprint, occupied_levels)
    if roof["planes"]:
        surfaces.append(_surface("roof", "roof", roof.get("level"), None))

    all_outline_points = [tuple(p) for level in levels_out for loop in level["outer_outlines"] for p in loop]
    bbox = polygon_bbox(all_outline_points) if all_outline_points else None
    top_of_walls = max((level["top_z"] for level in occupied_levels), default=0.0)
    base = min((level["elevation_m"] for level in occupied_levels), default=0.0)
    volume = sum(level["gross_area_m2"] * level["height_m"] for level in occupied_levels) + roof["volume_m3"]
    totals = {
        "level_count": len(occupied_levels),
        "room_count": len(blueprint["rooms"]),
        "footprint_area_m2": ground["gross_area_m2"] if ground else 0.0,
        "gross_floor_area_m2": sum(level["gross_area_m2"] for level in occupied_levels),
        "net_floor_area_m2": sum(level["net_area_m2"] for level in occupied_levels),
        "wall_height_m": top_of_walls - base,
        "building_height_m": (top_of_walls - base) + roof["rise_m"],
        "enclosed_volume_m3": volume,
        "footprint_width_m": (bbox[2] - bbox[0]) if bbox else 0.0,
        "footprint_depth_m": (bbox[3] - bbox[1]) if bbox else 0.0,
        "exterior_wall_length_m": sum(w["length_m"] for w in all_walls if w["kind"] == "exterior"),
        "interior_wall_length_m": sum(w["length_m"] for w in all_walls if w["kind"] == "interior"),
        "opening_count": sum(len(w["openings"]) for w in all_walls),
        "fixture_count": len(blueprint["fixtures"]),
    }
    return {
        "blueprint_id": blueprint["blueprint_id"],
        "levels": levels_out,
        "walls": all_walls,
        "rooms": room_metrics,
        "surfaces": surfaces,
        "roof": roof,
        "bbox": list(bbox) if bbox else None,
        "totals": totals,
        "detached_openings": [
            opening["key"] for opening in blueprint["openings"]
            if not any(o["key"] == opening["key"] for w in all_walls for o in w["openings"])
        ],
    }


def _surface(key, role, level_key, room_key, *, edge_index=None, plan_points=None, z=None):
    surface = {"key": key, "role": role, "level": level_key, "room": room_key}
    if edge_index is not None:
        surface["edge_index"] = edge_index
    if plan_points is not None:
        surface["plan_points"] = [list(p) for p in plan_points]
    if z is not None:
        surface["z"] = z
    return surface


def _attach_openings(blueprint, level_key, walls):
    for opening in blueprint["openings"]:
        if opening["level"] != level_key:
            continue
        center = _point(opening["center"])
        best = None
        for wall in walls:
            distance, t = point_segment_distance(center, wall["start"], wall["end"])
            limit = max(0.6, wall["thickness_m"])
            if distance > limit:
                continue
            if best is None or distance < best[0]:
                best = (distance, t, wall)
        if best is None:
            continue
        _distance, t, wall = best
        length = wall["length_m"]
        width = min(opening["width_m"], max(0.0, length - 0.1))
        if width < 0.3:
            continue
        offset = max(width / 2.0 + 0.05, min(length - width / 2.0 - 0.05, t * length))
        dx = (wall["end"][0] - wall["start"][0]) / (length or 1.0)
        dy = (wall["end"][1] - wall["start"][1]) / (length or 1.0)
        low = offset - width / 2.0
        high = offset + width / 2.0
        defaults = OPENING_CLASSES[opening["opening_class"]]
        wall["openings"].append({
            "key": opening["key"],
            "opening_class": opening["opening_class"],
            "offset_m": offset,
            "width_m": width,
            "sill_m": opening["sill_m"],
            "head_m": min(opening["head_m"], wall["top_z"] - wall["base_z"]),
            "passable": bool(defaults["passable"]),
            "start": [wall["start"][0] + dx * low, wall["start"][1] + dy * low],
            "end": [wall["start"][0] + dx * high, wall["start"][1] + dy * high],
            "center": [wall["start"][0] + dx * offset, wall["start"][1] + dy * offset],
        })
    for wall in walls:
        wall["openings"].sort(key=lambda item: item["offset_m"])


def _derive_roof(blueprint, occupied_levels):
    roof_spec = blueprint["roof"]
    empty = {"shape": roof_spec["shape"], "planes": [], "gable_walls": [], "rise_m": 0.0,
             "volume_m3": 0.0, "level": None, "eave_z": 0.0}
    if not occupied_levels:
        return empty
    top_level = max(occupied_levels, key=lambda level: level["top_z"])
    loops = top_level["outer_outlines"] or top_level["outline_loops"]
    if not loops:
        return empty
    eave_z = top_level["top_z"]
    shape = roof_spec["shape"]
    if shape == "flat":
        planes = [{"key": "roof:flat", "points": [[p[0], p[1], eave_z] for p in loop]} for loop in loops]
        return {**empty, "planes": planes, "level": top_level["key"], "eave_z": eave_z}

    points = [tuple(p) for loop in loops for p in loop]
    min_x, min_y, max_x, max_y = polygon_bbox(points)
    overhang = roof_spec["overhang_m"]
    min_x, min_y, max_x, max_y = min_x - overhang, min_y - overhang, max_x + overhang, max_y + overhang
    slope = math.tan(math.radians(roof_spec["pitch_deg"]))
    ridge_x = roof_spec["ridge_axis"] == "x"
    span = (max_y - min_y) if ridge_x else (max_x - min_x)
    length = (max_x - min_x) if ridge_x else (max_y - min_y)
    planes = []
    gable_walls = []
    if shape == "shed":
        rise = span * slope
        top = eave_z + rise
        if ridge_x:  # high edge on the north side
            planes.append({"key": "roof:shed", "points": [
                [min_x, min_y, top], [max_x, min_y, top], [max_x, max_y, eave_z], [min_x, max_y, eave_z]]})
            gable_walls = [
                {"facing": "west", "points": [[min_x + overhang, min_y + overhang, eave_z], [min_x + overhang, max_y - overhang, eave_z], [min_x + overhang, min_y + overhang, eave_z + (span - overhang) * slope]]},
                {"facing": "east", "points": [[max_x - overhang, min_y + overhang, eave_z], [max_x - overhang, max_y - overhang, eave_z], [max_x - overhang, min_y + overhang, eave_z + (span - overhang) * slope]]},
            ]
        else:  # high edge on the west side
            planes.append({"key": "roof:shed", "points": [
                [min_x, min_y, top], [max_x, min_y, eave_z], [max_x, max_y, eave_z], [min_x, max_y, top]]})
            gable_walls = [
                {"facing": "north", "points": [[min_x + overhang, min_y + overhang, eave_z], [max_x - overhang, min_y + overhang, eave_z], [min_x + overhang, min_y + overhang, eave_z + (span - overhang) * slope]]},
                {"facing": "south", "points": [[min_x + overhang, max_y - overhang, eave_z], [max_x - overhang, max_y - overhang, eave_z], [min_x + overhang, max_y - overhang, eave_z + (span - overhang) * slope]]},
            ]
        volume = (max_x - min_x) * (max_y - min_y) * rise / 2.0
        return {**empty, "planes": planes, "gable_walls": gable_walls, "rise_m": rise,
                "volume_m3": volume, "level": top_level["key"], "eave_z": eave_z}

    rise = (span / 2.0) * slope
    ridge_z = eave_z + rise
    if ridge_x:
        mid = (min_y + max_y) / 2.0
        inset = min(span / 2.0, length / 2.0) if shape == "hip" else 0.0
        r0, r1 = min_x + inset, max_x - inset
        planes.append({"key": "roof:north", "points": [[min_x, min_y, eave_z], [max_x, min_y, eave_z], [r1, mid, ridge_z], [r0, mid, ridge_z]]})
        planes.append({"key": "roof:south", "points": [[max_x, max_y, eave_z], [min_x, max_y, eave_z], [r0, mid, ridge_z], [r1, mid, ridge_z]]})
        if shape == "hip":
            planes.append({"key": "roof:west", "points": [[min_x, max_y, eave_z], [min_x, min_y, eave_z], [r0, mid, ridge_z]]})
            planes.append({"key": "roof:east", "points": [[max_x, min_y, eave_z], [max_x, max_y, eave_z], [r1, mid, ridge_z]]})
        else:
            wall_rise = (span / 2.0 - overhang) * slope
            gable_walls = [
                {"facing": "west", "points": [[min_x + overhang, min_y + overhang, eave_z], [min_x + overhang, max_y - overhang, eave_z], [min_x + overhang, mid, eave_z + wall_rise]]},
                {"facing": "east", "points": [[max_x - overhang, min_y + overhang, eave_z], [max_x - overhang, max_y - overhang, eave_z], [max_x - overhang, mid, eave_z + wall_rise]]},
            ]
    else:
        mid = (min_x + max_x) / 2.0
        inset = min(span / 2.0, length / 2.0) if shape == "hip" else 0.0
        r0, r1 = min_y + inset, max_y - inset
        planes.append({"key": "roof:west", "points": [[min_x, max_y, eave_z], [min_x, min_y, eave_z], [mid, r0, ridge_z], [mid, r1, ridge_z]]})
        planes.append({"key": "roof:east", "points": [[max_x, min_y, eave_z], [max_x, max_y, eave_z], [mid, r1, ridge_z], [mid, r0, ridge_z]]})
        if shape == "hip":
            planes.append({"key": "roof:north", "points": [[min_x, min_y, eave_z], [max_x, min_y, eave_z], [mid, r0, ridge_z]]})
            planes.append({"key": "roof:south", "points": [[max_x, max_y, eave_z], [min_x, max_y, eave_z], [mid, r1, ridge_z]]})
        else:
            wall_rise = (span / 2.0 - overhang) * slope
            gable_walls = [
                {"facing": "north", "points": [[min_x + overhang, min_y + overhang, eave_z], [max_x - overhang, min_y + overhang, eave_z], [mid, min_y + overhang, eave_z + wall_rise]]},
                {"facing": "south", "points": [[min_x + overhang, max_y - overhang, eave_z], [max_x - overhang, max_y - overhang, eave_z], [mid, max_y - overhang, eave_z + wall_rise]]},
            ]
    volume = (max_x - min_x) * (max_y - min_y) * rise / 2.0
    if shape == "hip":
        volume *= 0.8
    return {**empty, "planes": planes, "gable_walls": gable_walls, "rise_m": rise,
            "volume_m3": volume, "level": top_level["key"], "eave_z": eave_z}


# ---------------------------------------------------------------------------
# Materials
# ---------------------------------------------------------------------------


def surface_material(blueprint: dict[str, Any], surface_key: str, role: str) -> str | None:
    material = (blueprint.get("surface_materials") or {}).get(surface_key)
    if material:
        return material
    return (blueprint.get("default_materials") or {}).get(role)


def wall_surface_key(wall: dict[str, Any], *, outer=True, room_key=None) -> str | None:
    """Surface key for one face of a derived wall."""

    sides = [tuple(side) for side in wall.get("sides") or []]
    if wall.get("kind") == "exterior" and outer:
        room_key, edge_index = sides[0]
        return f"room:{room_key}:edge:{edge_index}:outer"
    for side_room, edge_index in sides:
        if room_key is None or side_room == room_key:
            return f"room:{side_room}:edge:{edge_index}:inner"
    return None


def materials_used(blueprint: dict[str, Any]) -> list[str]:
    used = set((blueprint.get("default_materials") or {}).values())
    used.update((blueprint.get("surface_materials") or {}).values())
    return sorted(material for material in used if material)


# ---------------------------------------------------------------------------
# Placement transforms
# ---------------------------------------------------------------------------


def plan_to_parent(point, position, rotation_deg=0.0):
    """Blueprint plan coordinates -> parent map coordinates.

    ``position`` is where the plan origin lands; rotation is clockwise on
    screen because plan ``y`` points south.
    """

    rx, ry = rotate_point(point, rotation_deg)
    return rx + float(position[0]), ry + float(position[1])


def parent_to_plan(point, position, rotation_deg=0.0):
    local = (float(point[0]) - float(position[0]), float(point[1]) - float(position[1]))
    return rotate_point(local, -float(rotation_deg or 0.0))


def plan_anchor(derived: dict[str, Any]) -> tuple[float, float]:
    """The footprint center, used to hold a blueprint under the cursor."""

    bbox = derived.get("bbox")
    if not bbox:
        return 0.0, 0.0
    return (bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0


def placed_footprint(derived, position, rotation_deg=0.0) -> list[list[list[float]]]:
    """Outer-face outline loops of the ground level in parent coordinates."""

    occupied = [level for level in derived.get("levels") or [] if level.get("rooms")]
    if not occupied:
        return []
    ground = occupied[0]
    return [
        [list(plan_to_parent(point, position, rotation_deg)) for point in loop]
        for loop in ground.get("outer_outlines") or []
    ]


def placed_wall_segments(derived, position, rotation_deg=0.0, level_key=None):
    """Walkable-space wall segments (centerlines) with gaps at passable openings."""

    levels = derived.get("levels") or []
    if level_key is None:
        occupied = [level for level in levels if level.get("rooms")]
        level_key = occupied[0]["key"] if occupied else None
    result = []
    for wall in derived.get("walls") or []:
        if wall.get("level") != level_key:
            continue
        start, end = wall["start"], wall["end"]
        length = wall["length_m"] or 1.0
        cursor = 0.0
        for opening in wall.get("openings") or []:
            if not opening.get("passable"):
                continue
            low = opening["offset_m"] - opening["width_m"] / 2.0
            high = opening["offset_m"] + opening["width_m"] / 2.0
            if low > cursor + 1e-6:
                result.append(_segment_between(start, end, cursor / length, low / length))
            cursor = max(cursor, high)
        if cursor < length - 1e-6:
            result.append(_segment_between(start, end, cursor / length, 1.0))
    return [
        (plan_to_parent(a, position, rotation_deg), plan_to_parent(b, position, rotation_deg))
        for a, b in result
    ]


def placed_openings(derived, position, rotation_deg=0.0, level_key=None):
    levels = derived.get("levels") or []
    if level_key is None:
        occupied = [level for level in levels if level.get("rooms")]
        level_key = occupied[0]["key"] if occupied else None
    result = []
    for wall in derived.get("walls") or []:
        if wall.get("level") != level_key:
            continue
        for opening in wall.get("openings") or []:
            result.append({
                "key": opening["key"],
                "opening_class": opening["opening_class"],
                "passable": opening["passable"],
                "width": opening["width_m"],
                "wall_kind": wall["kind"],
                "start": list(plan_to_parent(opening["start"], position, rotation_deg)),
                "end": list(plan_to_parent(opening["end"], position, rotation_deg)),
                "center": list(plan_to_parent(opening["center"], position, rotation_deg)),
            })
    return result


def placed_rooms(blueprint, position, rotation_deg=0.0, level_key=None):
    blueprint = normalize_blueprint(blueprint)
    if level_key is None:
        level_key = next((room["level"] for room in blueprint["rooms"]), None)
    return [
        {
            "key": room["key"],
            "name": room["name"],
            "points": [list(plan_to_parent(p, position, rotation_deg)) for p in room_polygon(room)],
        }
        for room in blueprint["rooms"]
        if room["level"] == level_key
    ]


def _segment_between(start, end, t0, t1):
    return (
        (start[0] + (end[0] - start[0]) * t0, start[1] + (end[1] - start[1]) * t0),
        (start[0] + (end[0] - start[0]) * t1, start[1] + (end[1] - start[1]) * t1),
    )


# ---------------------------------------------------------------------------
# Ontology summary
# ---------------------------------------------------------------------------


def summary_fields(blueprint: dict[str, Any], derived: dict[str, Any] | None = None) -> dict[str, Any]:
    """Semantic summary written onto the blueprint's ontology entity.

    Rooms and fixtures stay inside the blueprint (they are addressed as
    ``<building>#room:<key>``); the entity only lists them so other systems
    can reason about floor space and built-ins without loading geometry.
    """

    blueprint = normalize_blueprint(blueprint)
    derived = derived or derive_geometry(blueprint)
    totals = derived["totals"]
    rooms = []
    for room in blueprint["rooms"]:
        metrics = derived["rooms"].get(room["key"], {})
        rooms.append({
            "key": room["key"],
            "name": room["name"],
            "level": room["level"],
            "net_area_m2": round(metrics.get("net_area_m2", 0.0), 2),
        })
    fixtures = []
    for fixture in blueprint["fixtures"]:
        room_key = next(
            (key for key, metrics in derived["rooms"].items() if fixture["key"] in metrics.get("fixtures", [])),
            None,
        )
        fixtures.append({"key": fixture["key"], "ref": fixture["ref"], "level": fixture["level"], "room": room_key})
    return {
        "level_count": totals["level_count"],
        "footprint_area_m2": round(totals["footprint_area_m2"], 2),
        "gross_floor_area_m2": round(totals["gross_floor_area_m2"], 2),
        "net_floor_area_m2": round(totals["net_floor_area_m2"], 2),
        "building_height_m": round(totals["building_height_m"], 2),
        "enclosed_volume_m3": round(totals["enclosed_volume_m3"], 1),
        "footprint_width_m": round(totals["footprint_width_m"], 2),
        "footprint_depth_m": round(totals["footprint_depth_m"], 2),
        "roof_shape": blueprint["roof"]["shape"],
        "blueprint_rooms": rooms,
        "blueprint_fixtures": fixtures,
        "fixed_items": sorted({fixture["ref"] for fixture in blueprint["fixtures"]}),
        "materials_used": materials_used(blueprint),
    }
