"""Generate tectonic state from ontology-backed planetary inputs.

Architecture invariants: entities and semantic facts live only in the ontology;
tectonic models are derived products. Generated planets are currently
disposable, so model changes do not carry legacy compatibility requirements.

LOD contract: plate geometry, boundaries, events, and orogen envelopes first
appear in canonical LOD0 and are inherited downward. Deeper levels may resolve
local structural expressions but must not invent a contradictory plate story.
"""

import math

from simulations.world_gen.map_seed import resolved_map_seed, seed_range
from simulations.world_gen.orogen_systems import derive_orogen_system_model


def _clamp(value, low, high):
    return max(low, min(high, float(value)))


def _wrapped_delta(a, b):
    delta = float(a) - float(b)
    if delta > 0.5:
        delta -= 1.0
    elif delta < -0.5:
        delta += 1.0
    return delta


def _wrapped_distance(ax, ay, bx, by):
    dx = _wrapped_delta(ax, bx)
    dy = float(ay) - float(by)
    return math.hypot(dx, dy)


def _rotate_spherical_point(nx, ny, pole_longitude_deg, pole_latitude_deg, angle_deg):
    longitude = float(nx) * math.tau - math.pi
    latitude = (0.5 - float(ny)) * math.pi
    vector = [math.cos(latitude) * math.cos(longitude), math.cos(latitude) * math.sin(longitude), math.sin(latitude)]
    pole_lon = math.radians(float(pole_longitude_deg))
    pole_lat = math.radians(float(pole_latitude_deg))
    pole = [math.cos(pole_lat) * math.cos(pole_lon), math.cos(pole_lat) * math.sin(pole_lon), math.sin(pole_lat)]
    angle = math.radians(float(angle_deg))
    cos_angle, sin_angle = math.cos(angle), math.sin(angle)
    dot = sum(vector[index] * pole[index] for index in range(3))
    cross = [
        pole[1] * vector[2] - pole[2] * vector[1],
        pole[2] * vector[0] - pole[0] * vector[2],
        pole[0] * vector[1] - pole[1] * vector[0],
    ]
    rotated = [
        vector[index] * cos_angle + cross[index] * sin_angle + pole[index] * dot * (1.0 - cos_angle)
        for index in range(3)
    ]
    new_lon = math.atan2(rotated[1], rotated[0])
    new_lat = math.asin(_clamp(rotated[2], -1.0, 1.0))
    return ((new_lon + math.pi) / math.tau) % 1.0, _clamp(0.5 - new_lat / math.pi, 0.0, 1.0)


def _element_abundance(seed, symbol):
    composition = seed.get("crust_composition") if isinstance(seed, dict) else {}
    composition = composition if isinstance(composition, dict) else {}
    total = 0.0
    for group in ("major_elements", "trace_elements"):
        for item in composition.get(group) or []:
            if isinstance(item, dict) and item.get("symbol") == symbol:
                total += float(item.get("abundance_percent", 0.0) or 0.0)
    return total


def _mantle_current_at(nx, ny, cell_count=3, map_seed=""):
    vx = 0.0
    vy = 0.0
    for index in range(cell_count):
        phase = index / max(1, cell_count)
        cx = (phase * seed_range(map_seed, f"cell_{index}_spacing", 0.29, 0.47) + seed_range(map_seed, f"cell_{index}_x", 0.04, 0.34)) % 1.0
        cy = _clamp(0.18 + (index % 3) * seed_range(map_seed, f"cell_{index}_band", 0.18, 0.28) + seed_range(map_seed, f"cell_{index}_y", -0.05, 0.08), 0.08, 0.92)
        dx = _wrapped_delta(nx, cx)
        dy = ny - cy
        falloff = math.exp(-((dx * dx + dy * dy) / 0.085))
        swirl = -1.0 if seed_range(map_seed, f"cell_{index}_swirl", 0, 1) < 0.5 else 1.0
        vx += (-dy * swirl + 0.18 * math.sin(math.tau * (ny + phase))) * falloff
        vy += (dx * swirl + 0.12 * math.cos(math.tau * (nx - phase))) * falloff
    length = math.hypot(vx, vy)
    if length <= 1e-9:
        return {"x": 0.0, "y": 0.0, "speed_cm_per_year": 0.0}
    speed = _clamp(length * 5.5, 0.5, 8.5)
    return {
        "dir_x": round(vx / length, 4),
        "dir_y": round(vy / length, 4),
        "speed_cm_per_year": round(speed, 3),
    }


def _plate_centers(count, map_seed=""):
    centers = []
    golden = 0.61803398875
    x_offset = seed_range(map_seed, "plate_x_offset", 0.0, 1.0)
    y_phase = seed_range(map_seed, "plate_y_phase", 0.0, math.tau)
    for index in range(count):
        nx = (x_offset + index * golden + seed_range(map_seed, f"plate_{index}_jitter_x", -0.035, 0.035)) % 1.0
        band = index % 4
        ny = 0.16 + band * 0.22 + 0.055 * math.sin(index * 1.73 + y_phase)
        ny += seed_range(map_seed, f"plate_{index}_jitter_y", -0.045, 0.045)
        ny = _clamp(ny, 0.08, 0.92)
        centers.append((nx, ny))
    return centers


def _continent_seed_signal(nx, ny, map_seed=""):
    longitude = nx * math.tau
    latitude = (ny - 0.5) * math.pi
    phase_a = seed_range(map_seed, "continent_phase_a", 0.0, math.tau)
    phase_b = seed_range(map_seed, "continent_phase_b", 0.0, math.tau)
    phase_c = seed_range(map_seed, "continent_phase_c", 0.0, math.tau)
    return (
        0.52 * math.sin(longitude * seed_range(map_seed, "continent_freq_a", 1.1, 1.9) + latitude * 0.8 + phase_a)
        + 0.34 * math.cos(longitude * seed_range(map_seed, "continent_freq_b", 2.0, 3.2) - latitude * 1.15 + phase_b)
        + 0.22 * math.sin(longitude * seed_range(map_seed, "continent_freq_c", 3.2, 5.1) + math.sin(latitude + phase_c))
    )


def _plate_distance(nx, ny, plate):
    """Distance in a seeded, anisotropic plate metric with lobed margins."""
    dx = _wrapped_delta(nx, float(plate.get("center_x", 0.0) or 0.0))
    dy = float(ny) - float(plate.get("center_y", 0.5) or 0.5)
    shape = plate.get("boundary_shape") if isinstance(plate.get("boundary_shape"), dict) else {}
    orientation = float(shape.get("orientation_rad", 0.0) or 0.0)
    axis_ratio = _clamp(shape.get("axis_ratio", 1.0), 0.72, 1.38)
    cos_angle = math.cos(orientation)
    sin_angle = math.sin(orientation)
    rx = dx * cos_angle - dy * sin_angle
    ry = dx * sin_angle + dy * cos_angle
    rx /= axis_ratio
    ry *= axis_ratio
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


def _nearest_plate_index(nx, ny, plates):
    best_index = 0
    best_distance = 999.0
    for index, plate in enumerate(plates):
        distance = _plate_distance(nx, ny, plate)
        if distance < best_distance:
            best_distance = distance
            best_index = index
    return best_index


def _plate_area_fractions(plates, sample_width=96, sample_height=48):
    """Estimate spherical Voronoi areas so plate roles are area-stable."""
    areas = [0.0 for _ in plates]
    total = 0.0
    for row in range(sample_height):
        ny = (row + 0.5) / sample_height
        latitude_weight = math.sin(math.pi * ny)
        for col in range(sample_width):
            nx = (col + 0.5) / sample_width
            areas[_nearest_plate_index(nx, ny, plates)] += latitude_weight
            total += latitude_weight
    if total <= 0.0:
        return [1.0 / max(1, len(plates)) for _ in plates]
    return [area / total for area in areas]


def _take_ranked_area(candidates, target_fraction, min_separation=0.0):
    """Take ranked plates until their spherical area best matches a target.

    `_continentality_score` is a smooth, low-frequency noise field, so the
    top-ranked ("most continental") plates tend to have adjacent centers and
    their continental roots fuse into one supercontinent-shaped landmass.
    When min_separation > 0, prefer spatially spread-out candidates among the
    ranked list first, and only fall back to closely-spaced ones (in rank
    order) if the separation constraint would leave the area target unmet --
    real multi-continent worlds are a common outcome, not the exception.
    """
    selected = []
    selected_area = 0.0
    deferred = []
    for plate in candidates:
        if selected and selected_area >= target_fraction:
            break
        if min_separation > 0.0 and selected and not _plate_centers_separated(plate, selected, min_separation):
            deferred.append(plate)
            continue
        selected.append(plate)
        selected_area += float(plate.get("area_fraction", 0.0) or 0.0)
    for plate in deferred:
        if selected_area >= target_fraction:
            break
        selected.append(plate)
        selected_area += float(plate.get("area_fraction", 0.0) or 0.0)
    if len(selected) > 1:
        last_area = float(selected[-1].get("area_fraction", 0.0) or 0.0)
        without_last = selected_area - last_area
        if abs(without_last - target_fraction) < abs(selected_area - target_fraction):
            selected.pop()
    return selected


def _plate_centers_separated(candidate, selected, min_separation):
    cx = float(candidate.get("center_x", 0.0) or 0.0)
    cy = float(candidate.get("center_y", 0.5) or 0.5)
    for other in selected:
        ox = float(other.get("center_x", 0.0) or 0.0)
        oy = float(other.get("center_y", 0.5) or 0.5)
        if math.hypot(_wrapped_delta(cx, ox), cy - oy) < min_separation:
            return False
    return True


def _boundary_kind(plate_a, plate_b):
    dx = _wrapped_delta(plate_b["center_x"], plate_a["center_x"])
    dy = plate_b["center_y"] - plate_a["center_y"]
    normal_len = math.hypot(dx, dy) or 1.0
    nx = dx / normal_len
    ny = dy / normal_len
    rel_vx = plate_b["velocity_x_cm_year"] - plate_a["velocity_x_cm_year"]
    rel_vy = plate_b["velocity_y_cm_year"] - plate_a["velocity_y_cm_year"]
    normal_motion = rel_vx * nx + rel_vy * ny
    shear_motion = abs(rel_vx * -ny + rel_vy * nx)
    if normal_motion < -0.65:
        if plate_a["plate_type"] != plate_b["plate_type"]:
            return "subduction"
        return "collision"
    if normal_motion > 0.55:
        return "divergent"
    if shear_motion > 0.7:
        return "transform"
    return "passive"


def _segment_kinematics(segment, plates_by_id):
    plate_a = plates_by_id.get(segment.get("plate_a")) or {}
    plate_b = plates_by_id.get(segment.get("plate_b")) or {}
    nx = float(segment.get("normal_x", 0.0) or 0.0)
    ny = float(segment.get("normal_y", 0.0) or 0.0)
    normal_length = math.hypot(nx, ny) or 1.0
    nx, ny = nx / normal_length, ny / normal_length
    rel_vx = float(plate_b.get("velocity_x_cm_year", 0.0) or 0.0) - float(plate_a.get("velocity_x_cm_year", 0.0) or 0.0)
    rel_vy = float(plate_b.get("velocity_y_cm_year", 0.0) or 0.0) - float(plate_a.get("velocity_y_cm_year", 0.0) or 0.0)
    normal_motion = rel_vx * nx + rel_vy * ny
    shear_motion = rel_vx * -ny + rel_vy * nx
    if normal_motion < -0.48:
        kind = "subduction" if "oceanic" in {plate_a.get("plate_type"), plate_b.get("plate_type")} else "collision"
    elif normal_motion > 0.42:
        kind = "divergent"
    elif abs(shear_motion) > 0.58:
        kind = "transform"
    else:
        kind = "passive"
    subducting = None
    overriding = None
    if kind == "subduction":
        density_rank = {"oceanic": 3, "mixed": 2, "continental": 1}
        if density_rank.get(plate_a.get("plate_type"), 2) >= density_rank.get(plate_b.get("plate_type"), 2):
            subducting, overriding = plate_a.get("id"), plate_b.get("id")
        else:
            subducting, overriding = plate_b.get("id"), plate_a.get("id")
    relative_speed = math.hypot(rel_vx, rel_vy)
    obliquity = math.degrees(math.atan2(abs(shear_motion), max(1e-6, abs(normal_motion))))
    return {
        "kind": kind,
        "normal_x": round(nx, 4),
        "normal_y": round(ny, 4),
        "normal_velocity_cm_year": round(normal_motion, 3),
        "shear_velocity_cm_year": round(shear_motion, 3),
        "relative_speed_cm_year": round(relative_speed, 3),
        "obliquity_deg": round(obliquity, 1),
        "subducting_plate": subducting,
        "overriding_plate": overriding,
    }


def _summarize_boundaries(boundary_segments):
    boundaries = []
    segments_by_pair = {}
    for segment in boundary_segments or []:
        if not isinstance(segment, dict):
            continue
        pair = tuple(sorted((segment.get("plate_a"), segment.get("plate_b"))))
        segments_by_pair.setdefault(pair, []).append(segment)
    for pair, pair_segments in sorted(segments_by_pair.items(), key=lambda item: len(item[1]), reverse=True):
        kind_counts = {}
        for segment in pair_segments:
            kind = str(segment.get("kind") or "passive")
            kind_counts[kind] = kind_counts.get(kind, 0) + 1
        dominant_kind = max(kind_counts, key=kind_counts.get)
        boundaries.append({
            "plate_a": pair[0],
            "plate_b": pair[1],
            "kind": dominant_kind,
            "segment_kind_counts": kind_counts,
            "sample_length": len(pair_segments),
            "activity": round(sum(float(item.get("activity_scale", 1.0)) for item in pair_segments) / len(pair_segments), 3),
            "mean_normal_velocity_cm_year": round(sum(float(item.get("normal_velocity_cm_year", 0.0)) for item in pair_segments) / len(pair_segments), 3),
            "mean_shear_velocity_cm_year": round(sum(float(item.get("shear_velocity_cm_year", 0.0)) for item in pair_segments) / len(pair_segments), 3),
        })
    return boundaries


def _pair_distance_delta(nx, ny, plate_a, plate_b):
    return _plate_distance(nx % 1.0, _clamp(ny, 0.0, 1.0), plate_a) - _plate_distance(
        nx % 1.0,
        _clamp(ny, 0.0, 1.0),
        plate_b,
    )


def _boundary_edge_crossing(point_a, owner_a, point_b, owner_b, plates):
    pair = tuple(sorted((owner_a, owner_b)))
    plate_a, plate_b = plates[pair[0]], plates[pair[1]]
    value_a = _pair_distance_delta(point_a[0], point_a[1], plate_a, plate_b)
    value_b = _pair_distance_delta(point_b[0], point_b[1], plate_a, plate_b)
    denominator = value_a - value_b
    t = 0.5 if abs(denominator) <= 1e-12 else _clamp(value_a / denominator, 0.0, 1.0)
    dx = _wrapped_delta(point_b[0], point_a[0])
    return pair, ((point_a[0] + dx * t) % 1.0, point_a[1] + (point_b[1] - point_a[1]) * t)


def _continuous_boundary_segments(owner_rows, plates):
    """Extract sub-cell plate boundaries from continuous plate-distance fields."""
    height = len(owner_rows)
    width = len(owner_rows[0]) if height else 0
    if width < 2 or height < 2:
        return []
    segments = []

    def point_distance(first, second):
        return math.hypot(_wrapped_delta(first[0], second[0]), first[1] - second[1])

    def add_segment(pair, point_a, point_b):
        dx = _wrapped_delta(point_b[0], point_a[0])
        dy = point_b[1] - point_a[1]
        length = math.hypot(dx, dy)
        if length <= 1e-8:
            return
        midpoint_x = (point_a[0] + dx * 0.5) % 1.0
        midpoint_y = (point_a[1] + point_b[1]) * 0.5
        plate_a, plate_b = plates[pair[0]], plates[pair[1]]
        # The contour tangent is continuous; its perpendicular is oriented by
        # the underlying distance field so the normal always points A -> B.
        normal_x, normal_y = -dy / length, dx / length
        probe = min(0.0015, length * 0.35)
        forward = _pair_distance_delta(
            midpoint_x + normal_x * probe,
            midpoint_y + normal_y * probe,
            plate_a,
            plate_b,
        )
        backward = _pair_distance_delta(
            midpoint_x - normal_x * probe,
            midpoint_y - normal_y * probe,
            plate_a,
            plate_b,
        )
        if forward < backward:
            normal_x, normal_y = -normal_x, -normal_y
        segments.append({
            "x1": round(point_a[0] % 1.0, 7),
            "y1": round(_clamp(point_a[1], 0.0, 1.0), 7),
            "x2": round(point_b[0] % 1.0, 7),
            "y2": round(_clamp(point_b[1], 0.0, 1.0), 7),
            "plate_a": plate_a["id"],
            "plate_b": plate_b["id"],
            "normal_x": round(normal_x, 6),
            "normal_y": round(normal_y, 6),
            "geometry_model": "continuous_plate_distance_contour_v1",
        })

    for row in range(height - 1):
        y0 = row / max(1, height - 1)
        y1 = (row + 1) / max(1, height - 1)
        for col in range(width - 1):
            x0 = col / max(1, width - 1)
            x1 = (col + 1) / max(1, width - 1)
            corners = (
                ((x0, y0), owner_rows[row][col]),
                ((x1, y0), owner_rows[row][col + 1]),
                ((x1, y1), owner_rows[row + 1][col + 1]),
                ((x0, y1), owner_rows[row + 1][col]),
            )
            crossings = {}
            for first, second in ((0, 1), (1, 2), (2, 3), (3, 0)):
                point_a, owner_a = corners[first]
                point_b, owner_b = corners[second]
                if owner_a == owner_b:
                    continue
                pair, crossing = _boundary_edge_crossing(point_a, owner_a, point_b, owner_b, plates)
                pair_crossings = crossings.setdefault(pair, [])
                if not any(point_distance(crossing, existing) <= 1e-8 for existing in pair_crossings):
                    pair_crossings.append(crossing)

            for pair, points in crossings.items():
                if len(points) == 2:
                    add_segment(pair, points[0], points[1])
                elif len(points) == 4:
                    pairings = (
                        ((0, 1), (2, 3)),
                        ((0, 2), (1, 3)),
                        ((0, 3), (1, 2)),
                    )
                    best = min(
                        pairings,
                        key=lambda pairing: sum(point_distance(points[a], points[b]) for a, b in pairing),
                    )
                    for first, second in best:
                        add_segment(pair, points[first], points[second])
                elif points:
                    # Triple-junction cells commonly contribute one crossing
                    # for each participating pair. Join those arms at a shared
                    # sub-cell junction instead of leaving visible gaps.
                    junction = ((x0 + x1) * 0.5 % 1.0, (y0 + y1) * 0.5)
                    for point in points:
                        add_segment(pair, point, junction)
    return segments


def _sample_plate_owner_rows(plates, width, height):
    rows = []
    for row in range(height):
        ny = row / max(1, height - 1)
        rows.append([
            _nearest_plate_index(col / max(1, width - 1), ny, plates)
            for col in range(width)
        ])
    return rows


def _decorate_boundary_segments(boundary_segments, plates, map_seed):
    plates_by_id = {plate["id"]: plate for plate in plates}
    for index, segment in enumerate(boundary_segments):
        segment["id"] = f"boundary_segment_{index + 1:04d}"
        pair = tuple(sorted((segment.get("plate_a"), segment.get("plate_b"))))
        segment.update(_segment_kinematics(segment, plates_by_id))
        pair_key = f"{pair[0]}:{pair[1]}"
        segment_x1 = float(segment.get("x1", 0.0) or 0.0)
        segment_x2 = float(segment.get("x2", 0.0) or 0.0)
        midpoint_x = (segment_x1 + _wrapped_delta(segment_x2, segment_x1) * 0.5) % 1.0
        midpoint_y = (float(segment.get("y1", 0.5) or 0.5) + float(segment.get("y2", 0.5) or 0.5)) * 0.5
        activity_phase = seed_range(map_seed, f"boundary:{pair_key}:activity_phase", 0.0, math.tau)
        activity_frequency = seed_range(map_seed, f"boundary:{pair_key}:activity_frequency", 2.4, 5.8)
        activity_wave = 0.5 + 0.5 * math.sin(
            math.tau * activity_frequency * (midpoint_x + midpoint_y * 0.57)
            + activity_phase
        )
        segment["activity_scale"] = round(0.42 + activity_wave * 0.78, 3)
        segment["influence_width"] = round(
            seed_range(map_seed, f"boundary:{pair_key}:base_width", 0.018, 0.033)
            * (0.82 + activity_wave * 0.34),
            5,
        )
    return boundary_segments


def _topology_and_lithosphere(owner_rows, plates, boundary_segments, map_seed):
    height = len(owner_rows)
    width = len(owner_rows[0]) if height else 0
    neighbours = {plate["id"]: set() for plate in plates}
    for segment in boundary_segments:
        a, b = segment.get("plate_a"), segment.get("plate_b")
        if a in neighbours and b in neighbours:
            neighbours[a].add(b)
            neighbours[b].add(a)
    triple_junctions = []
    for y in range(max(0, height - 1)):
        for x in range(max(0, width - 1)):
            owners = {
                owner_rows[y][x], owner_rows[y][x + 1],
                owner_rows[y + 1][x], owner_rows[y + 1][x + 1],
            }
            if len(owners) >= 3:
                triple_junctions.append({
                    "x": round((x + 0.5) / max(1, width - 1), 4),
                    "y": round((y + 0.5) / max(1, height - 1), 4),
                    "plates": [plates[index]["id"] for index in sorted(owners)],
                    "junction_type": "ridge_ridge_transform_or_mixed",
                })

    ridge_cells = set()
    for segment in boundary_segments:
        if segment.get("kind") != "divergent":
            continue
        x = int(round(((float(segment["x1"]) + float(segment["x2"])) * 0.5) * max(1, width - 1)))
        y = int(round(((float(segment["y1"]) + float(segment["y2"])) * 0.5) * max(1, height - 1)))
        ridge_cells.add((x % max(1, width), max(0, min(height - 1, y))))
    distance_rows = [[999.0 for _x in range(width)] for _y in range(height)]
    frontier = []
    for x, y in ridge_cells:
        distance_rows[y][x] = 0
        frontier.append((x, y))
    # Chamfer distance from active ridges approximates seafloor spreading age.
    # Eight directions avoid the square/Manhattan bands produced by a cardinal
    # flood fill while retaining the wrapped spherical map seam.
    for _pass in range(max(width, height)):
        changed = False
        for y in range(height):
            for x in range(width):
                current = distance_rows[y][x]
                for dx, dy, cost in (
                    (-1, 0, 1.0), (1, 0, 1.0), (0, -1, 1.0), (0, 1, 1.0),
                    (-1, -1, math.sqrt(2.0)), (1, -1, math.sqrt(2.0)),
                    (-1, 1, math.sqrt(2.0)), (1, 1, math.sqrt(2.0)),
                ):
                    neighbour_y = y + dy
                    if neighbour_y < 0 or neighbour_y >= height:
                        continue
                    candidate = distance_rows[neighbour_y][(x + dx) % width] + cost
                    if candidate + 1e-6 < current:
                        current = candidate
                if current + 1e-6 < distance_rows[y][x]:
                    distance_rows[y][x] = current
                    changed = True
        if not changed:
            break
    age_rows = []
    crust_rows = []
    continental_fraction_rows = []
    for y, owner_row in enumerate(owner_rows):
        age_row = []
        crust_row = []
        continental_fraction_row = []
        for x, owner in enumerate(owner_row):
            plate = plates[owner]
            plate_type = plate.get("plate_type", "mixed")
            if plate_type == "continental":
                crust_type = "continental"
                continental_fraction = 1.0
                age = seed_range(map_seed, f"craton_age:{plate['id']}", 650.0, 3200.0)
            elif plate_type == "oceanic":
                crust_type = "oceanic"
                continental_fraction = 0.0
                age = min(220.0, distance_rows[y][x] * seed_range(map_seed, "ocean_age_cell_myr", 2.4, 4.2))
            else:
                # Mixed plates carry coherent terranes.  A former block-hash
                # implementation made every 6x6 sample province a visible
                # rectangle in elevation, climate, and material maps.
                nx = x / max(1, width - 1)
                ny = y / max(1, height - 1)
                phase_a = seed_range(map_seed, f"mixed_crust:{plate['id']}:phase_a", 0.0, math.tau)
                phase_b = seed_range(map_seed, f"mixed_crust:{plate['id']}:phase_b", 0.0, math.tau)
                province = (
                    0.52
                    + 0.27 * math.sin(math.tau * (nx * 2.3 + ny * 1.1) + phase_a)
                    + 0.18 * math.cos(math.tau * (nx * 4.7 - ny * 2.4) + phase_b)
                    + 0.10 * _continent_seed_signal(nx, ny, f"{map_seed}:{plate['id']}:terrane")
                )
                continental_fraction = _clamp((province - 0.48) / 0.30, 0.0, 1.0)
                continental_fraction = continental_fraction * continental_fraction * (3.0 - 2.0 * continental_fraction)
                crust_type = "continental_fragment" if continental_fraction >= 0.5 else "oceanic"
                age = (
                    seed_range(map_seed, f"fragment_age:{plate['id']}", 350.0, 1800.0)
                    if crust_type == "continental_fragment"
                    else min(220.0, distance_rows[y][x] * 3.2)
                )
            crust_row.append(crust_type)
            continental_fraction_row.append(round(continental_fraction, 4))
            age_row.append(round(age, 1))
        crust_rows.append(crust_row)
        continental_fraction_rows.append(continental_fraction_row)
        age_rows.append(age_row)
    return {
        "plate_topology": {
            "model": "closed_spherical_partition_v1",
            "closed_surface": True,
            "plate_neighbours": {key: sorted(value) for key, value in neighbours.items()},
            "triple_junctions": triple_junctions,
        },
        "lithosphere_grid": {
            "model": "mixed_crust_and_ocean_floor_age_v1",
            "width": width,
            "height": height,
            "crust_type_rows": crust_rows,
            "continental_fraction_rows": continental_fraction_rows,
            "ocean_floor_age_rows_myr": age_rows,
            "ocean_floor_max_age_myr": 220.0,
            "ridge_source_count": len(ridge_cells),
            "thermal_subsidence_rule": "depth_increases_with_sqrt_ocean_floor_age",
        },
    }


def _hotspot_model(plates, map_seed):
    hotspot_count = int(round(seed_range(map_seed, "hotspot_count", 2.0, 5.0)))
    hotspots = []
    for index in range(hotspot_count):
        x = seed_range(map_seed, f"hotspot:{index}:x", 0.0, 1.0)
        y = seed_range(map_seed, f"hotspot:{index}:y", 0.12, 0.88)
        plate = plates[_nearest_plate_index(x, y, plates)]
        motion = plate.get("motion_model") if isinstance(plate.get("motion_model"), dict) else {}
        euler_lon = float(motion.get("euler_pole_longitude_deg", 0.0) or 0.0)
        euler_lat = float(motion.get("euler_pole_latitude_deg", 90.0) or 90.0)
        angular_velocity_deg_myr = float(motion.get("angular_velocity_deg_myr", 0.0) or 0.0)
        decay_myr = seed_range(map_seed, f"hotspot:{index}:decay", 55.0, 105.0)
        track = []
        for step, age_myr in enumerate((0.0, 12.0, 28.0, 50.0, 78.0, 110.0)):
            # The mantle plume is fixed; the plate above it carries older
            # volcanoes away as it rotates, trailing opposite the plate's
            # instantaneous motion (same age-backward convention as
            # _latent_geologic_history's plate-position rotation, and the
            # same sign as the flat-map linear approximation this replaces
            # -- but correct near poles/the date-line, where a flat-map
            # linear velocity approximation is not).
            track_x, track_y = _rotate_spherical_point(
                x, y, euler_lon, euler_lat, -angular_velocity_deg_myr * age_myr,
            )
            track.append({
                "age_myr": age_myr,
                "x": round(track_x, 4),
                "y": round(_clamp(track_y, 0.04, 0.96), 4),
                "relative_volume": round(math.exp(-age_myr / decay_myr), 3),
                # Older seamounts have subsided/eroded longer: wider, softer
                # relief, independent of the buoyancy-driven amplitude decay
                # already captured by relative_volume.
                "erosion_softening": round(_clamp(age_myr / 110.0, 0.0, 1.0), 3),
            })
        hotspots.append({
            "id": f"hotspot_{index + 1:02d}",
            "mantle_x": round(x, 4),
            "mantle_y": round(y, 4),
            "present_plate": plate["id"],
            "buoyancy_flux_class": "major" if seed_range(map_seed, f"hotspot:{index}:flux", 0.0, 1.0) > 0.72 else "moderate",
            "track": track,
        })
    return {
        "model": "mantle_fixed_age_progressive_tracks_v2",
        "hotspots": hotspots,
        "large_igneous_province_possible": any(item["buoyancy_flux_class"] == "major" for item in hotspots),
    }


def _continental_province_model(plates, map_seed):
    cratons, failed_rifts, basins = [], [], []
    for plate_index, plate in enumerate(plates):
        if plate.get("plate_type") == "oceanic":
            continue
        province_count = 2 if plate.get("plate_type") == "continental" else 1
        for province_index in range(province_count):
            key = f"province:{plate['id']}:{province_index}"
            offset_x = seed_range(map_seed, f"{key}:offset_x", -0.055, 0.055)
            offset_y = seed_range(map_seed, f"{key}:offset_y", -0.045, 0.045)
            cratons.append({
                "id": f"craton_{plate_index + 1:02d}_{province_index + 1:02d}",
                "plate_id": plate["id"],
                "center_x": round((float(plate["center_x"]) + offset_x) % 1.0, 4),
                "center_y": round(_clamp(float(plate["center_y"]) + offset_y, 0.06, 0.94), 4),
                "width": round(seed_range(map_seed, f"{key}:width", 0.055, 0.135), 4),
                "height": round(seed_range(map_seed, f"{key}:height", 0.045, 0.110), 4),
                "crustal_age_myr": round(seed_range(map_seed, f"{key}:age", 900.0, 3600.0), 1),
                "crust_thickness_km": round(seed_range(map_seed, f"{key}:thickness", 34.0, 52.0), 1),
                "state": "exposed_shield" if seed_range(map_seed, f"{key}:shield", 0.0, 1.0) > 0.48 else "sediment_covered_craton",
            })
        angle = seed_range(map_seed, f"failed_rift:{plate['id']}:angle", 0.0, math.tau)
        half_length = seed_range(map_seed, f"failed_rift:{plate['id']}:length", 0.055, 0.13)
        failed_rifts.append({
            "id": f"failed_rift_{plate_index + 1:02d}",
            "plate_id": plate["id"],
            "x1": round((float(plate["center_x"]) - math.cos(angle) * half_length) % 1.0, 4),
            "y1": round(_clamp(float(plate["center_y"]) - math.sin(angle) * half_length, 0.05, 0.95), 4),
            "x2": round((float(plate["center_x"]) + math.cos(angle) * half_length) % 1.0, 4),
            "y2": round(_clamp(float(plate["center_y"]) + math.sin(angle) * half_length, 0.05, 0.95), 4),
            "subsidence_m": round(seed_range(map_seed, f"failed_rift:{plate['id']}:subsidence", 350.0, 1100.0), 1),
            "status": "aulacogen_or_inverted_rift",
        })
        basins.append({
            "id": f"intracratonic_basin_{plate_index + 1:02d}",
            "plate_id": plate["id"],
            "center_x": round((float(plate["center_x"]) + seed_range(map_seed, f"basin:{plate['id']}:x", -0.08, 0.08)) % 1.0, 4),
            "center_y": round(_clamp(float(plate["center_y"]) + seed_range(map_seed, f"basin:{plate['id']}:y", -0.07, 0.07), 0.06, 0.94), 4),
            "radius": round(seed_range(map_seed, f"basin:{plate['id']}:radius", 0.035, 0.095), 4),
            "sediment_capacity_m": round(seed_range(map_seed, f"basin:{plate['id']}:capacity", 1200.0, 6500.0), 1),
        })
    return {
        "model": "craton_shield_failed_rift_basin_v1",
        "cratons": cratons,
        "failed_rifts": failed_rifts,
        "intracratonic_basins": basins,
    }


def _latent_geologic_history(plates, terrain, map_seed, boundaries=None):
    """Reconstruct a seeded pre-present plate history, separate from game time."""
    canvas = terrain.get("map_canvas") if isinstance(terrain.get("map_canvas"), dict) else {}
    circumference_m = max(1.0, float(canvas.get("circumference_m", 40_075_000.0) or 40_075_000.0))
    history_span_myr = seed_range(map_seed, "geologic_history_span_myr", 720.0, 1250.0)
    snapshot_ages = (history_span_myr, history_span_myr * 0.58, history_span_myr * 0.24, 0.0)
    snapshots = []
    positions_by_age = {}
    for age_myr in snapshot_ages:
        positions = []
        for plate in plates:
            motion = plate.get("motion_model") if isinstance(plate.get("motion_model"), dict) else {}
            x, y = _rotate_spherical_point(
                float(plate.get("center_x", 0.0) or 0.0),
                float(plate.get("center_y", 0.5) or 0.5),
                motion.get("euler_pole_longitude_deg", 0.0),
                motion.get("euler_pole_latitude_deg", 90.0),
                -float(motion.get("angular_velocity_deg_myr", 0.0) or 0.0) * age_myr,
            )
            y = _clamp(y, 0.05, 0.95)
            positions.append({"plate_id": plate["id"], "center_x": round(x, 4), "center_y": round(y, 4)})
        positions_by_age[round(age_myr, 3)] = positions
        snapshots.append({"age_before_present_myr": round(age_myr, 1), "plates": positions})

    oldest = positions_by_age[round(snapshot_ages[0], 3)]
    present = positions_by_age[0.0]
    oldest_by_id = {item["plate_id"]: item for item in oldest}
    present_by_id = {item["plate_id"]: item for item in present}
    events = []
    for first_index, first in enumerate(plates):
        for second in plates[first_index + 1:]:
            old_a, old_b = oldest_by_id[first["id"]], oldest_by_id[second["id"]]
            now_a, now_b = present_by_id[first["id"]], present_by_id[second["id"]]
            old_distance = _wrapped_distance(old_a["center_x"], old_a["center_y"], old_b["center_x"], old_b["center_y"])
            present_distance = _wrapped_distance(now_a["center_x"], now_a["center_y"], now_b["center_x"], now_b["center_y"])
            if old_distance < 0.18 and present_distance > old_distance + 0.08:
                kind = "continental_rifting"
            elif present_distance < 0.18 and old_distance > present_distance + 0.07:
                kind = "terrane_accretion_or_collision"
            else:
                continue
            events.append({
                "kind": kind,
                "plate_a": first["id"],
                "plate_b": second["id"],
                "old_distance": round(old_distance, 3),
                "present_distance": round(present_distance, 3),
            })
    continental_ids = [plate["id"] for plate in plates if plate.get("plate_type") == "continental"]
    if len(continental_ids) >= 2:
        events.extend([
            {
                "kind": "supercontinent_assembly",
                "age_before_present_myr": round(history_span_myr * seed_range(map_seed, "history:assembly_age", 0.55, 0.82), 1),
                "participants": continental_ids,
            },
            {
                "kind": "supercontinent_rifting_and_breakup",
                "age_before_present_myr": round(history_span_myr * seed_range(map_seed, "history:breakup_age", 0.24, 0.48), 1),
                "participants": continental_ids,
            },
        ])
    for index, boundary in enumerate(boundaries or []):
        kind = boundary.get("kind")
        event_kind = {
            "divergent": "ocean_basin_opening_and_passive_margin_birth",
            "subduction": "subduction_arc_and_terrane_accretion",
            "collision": "continental_suture_and_orogeny",
            "transform": "transform_reorganization_and_pull_apart_basins",
        }.get(kind)
        if event_kind:
            events.append({
                "kind": event_kind,
                "age_before_present_myr": round(seed_range(map_seed, f"history:boundary:{index}:age", 18.0, min(420.0, history_span_myr * 0.55)), 1),
                "plate_a": boundary.get("plate_a"),
                "plate_b": boundary.get("plate_b"),
                "activity": boundary.get("activity"),
            })
    events.sort(key=lambda item: float(item.get("age_before_present_myr", history_span_myr) or 0.0), reverse=True)
    return {
        "model_version": "eventful-prepresent-plate-history-v2",
        "time_domain": "pre_generation_geologic_history",
        "registry_time_coupled": False,
        "history_span_myr": round(history_span_myr, 1),
        "snapshots": snapshots,
        "events": events,
        "purpose": "causal_scaffold_for_continents_margins_basins_and_orogens",
    }


def derive_tectonic_model(terrain, seed=None, physics=None, planet_id=""):
    terrain = terrain if isinstance(terrain, dict) else {}
    tectonics = terrain.get("tectonics") if isinstance(terrain.get("tectonics"), dict) else {}
    hydrology = terrain.get("hydrology") if isinstance(terrain.get("hydrology"), dict) else {}
    map_seed = terrain.get("map_seed") or resolved_map_seed(seed, planet_id=planet_id)
    requested_count = int(tectonics.get("plate_count", 8) or 8)
    plate_count = max(3, min(18, requested_count))
    water_inventory = _clamp(hydrology.get("water_inventory_index", 0.35), 0.0, 1.0)
    # Plate composition precedes the final coastline. Use volatile-enabled
    # differentiation as a weak lithosphere prior, never the resolved or
    # requested ocean coverage (which would reverse the causal direction).
    expected_oceanic_lithosphere = _clamp(0.42 + water_inventory * 0.25, 0.34, 0.72)
    felsic_inventory = sum(_element_abundance(seed or {}, symbol) for symbol in ("Si", "Al", "Na", "K"))
    continental_crust_potential = _clamp((felsic_inventory - 20.0) / 38.0, 0.0, 1.0)

    plates = []
    for index, (center_x, center_y) in enumerate(_plate_centers(plate_count, map_seed=map_seed)):
        current = _mantle_current_at(center_x, center_y, map_seed=map_seed)
        continentality = _continent_seed_signal(center_x, center_y, map_seed=map_seed)
        continentality += (0.5 - expected_oceanic_lithosphere) * 0.65
        continentality += seed_range(map_seed, f"plate_{index}_continentality_jitter", -0.22, 0.22)
        speed = current["speed_cm_per_year"]
        plates.append({
            "id": f"plate_{index + 1:02d}",
            "center_x": round(center_x, 4),
            "center_y": round(center_y, 4),
            "plate_type": "mixed",
            "continentality": round(_clamp((continentality + 1.4) / 2.8, 0.0, 1.0), 3),
            "_continentality_score": continentality,
            "boundary_shape": {
                "model": "anisotropic_lobed_plate_metric_v1",
                "orientation_rad": round(seed_range(map_seed, f"plate_{index}_shape_orientation", 0.0, math.tau), 5),
                "axis_ratio": round(seed_range(map_seed, f"plate_{index}_shape_axis", 0.78, 1.28), 4),
                "lobe_a_frequency": int(round(seed_range(map_seed, f"plate_{index}_shape_freq_a", 2.0, 4.0))),
                "lobe_a_amplitude": round(seed_range(map_seed, f"plate_{index}_shape_amp_a", 0.10, 0.22), 4),
                "lobe_a_phase": round(seed_range(map_seed, f"plate_{index}_shape_phase_a", 0.0, math.tau), 5),
                "lobe_b_frequency": int(round(seed_range(map_seed, f"plate_{index}_shape_freq_b", 5.0, 8.0))),
                "lobe_b_amplitude": round(seed_range(map_seed, f"plate_{index}_shape_amp_b", 0.04, 0.11), 4),
                "lobe_b_phase": round(seed_range(map_seed, f"plate_{index}_shape_phase_b", 0.0, math.tau), 5),
            },
            "velocity_x_cm_year": round(current["dir_x"] * speed, 3),
            "velocity_y_cm_year": round(current["dir_y"] * speed, 3),
            "speed_cm_per_year": speed,
            "motion_model": {
                "type": "spherical_euler_rotation",
                "euler_pole_longitude_deg": round(seed_range(map_seed, f"plate_{index}_euler_lon", -180.0, 180.0), 2),
                "euler_pole_latitude_deg": round(seed_range(map_seed, f"plate_{index}_euler_lat", -72.0, 72.0), 2),
                "angular_velocity_deg_myr": round(seed_range(map_seed, f"plate_{index}_euler_rate", 0.035, 0.22) * (0.55 + speed / 8.5), 4),
            },
        })

    for plate, area_fraction in zip(plates, _plate_area_fractions(plates)):
        plate["area_fraction"] = round(area_fraction, 4)

    # Counts are a poor control because polar and equatorial Voronoi plates
    # can differ greatly in spherical area. Composition sets a broad target
    # area of differentiated continental crust; seeded plate geometry and
    # ranking decide which plates carry it. This is still upstream of relief,
    # sea level and the final coastline.
    continental_area_target = _clamp(0.30 + continental_crust_potential * 0.16, 0.28, 0.47)
    oceanic_area_target = _clamp(0.43 + (1.0 - continental_crust_potential) * 0.12, 0.40, 0.56)
    descending = sorted(plates, key=lambda item: float(item.get("_continentality_score", 0.0)), reverse=True)
    # Active plate tectonics (mobile_lid) should commonly produce several
    # separated continents rather than one supercontinent-shaped blob;
    # enforce a minimum angular spread among the highest-ranked continental
    # candidates for that regime specifically, since other regimes (stagnant
    # lid, etc.) are not expected to exhibit Earth-like multi-continent
    # break-up behavior.
    continental_min_separation = 0.30 if str(tectonics.get("regime") or "").lower() == "mobile_lid" else 0.0
    continental_plates = _take_ranked_area(descending, continental_area_target, min_separation=continental_min_separation)
    continental_ids = {plate["id"] for plate in continental_plates}
    ascending_remaining = sorted(
        (plate for plate in plates if plate["id"] not in continental_ids),
        key=lambda item: float(item.get("_continentality_score", 0.0)),
    )
    oceanic_plates = _take_ranked_area(ascending_remaining, oceanic_area_target)
    oceanic_ids = {plate["id"] for plate in oceanic_plates}
    if len(continental_ids | oceanic_ids) == plate_count and plate_count >= 3:
        oceanic_ids.discard(oceanic_plates[-1]["id"])

    for plate in plates:
        if plate["id"] in continental_ids:
            plate["plate_type"] = "continental"
        elif plate["id"] in oceanic_ids:
            plate["plate_type"] = "oceanic"
        else:
            plate["plate_type"] = "mixed"
        plate.pop("_continentality_score", None)

    continental_count = sum(1 for plate in plates if plate["plate_type"] == "continental")
    oceanic_count = sum(1 for plate in plates if plate["plate_type"] == "oceanic")
    continental_area = sum(float(plate.get("area_fraction", 0.0) or 0.0) for plate in plates if plate["plate_type"] == "continental")
    oceanic_area = sum(float(plate.get("area_fraction", 0.0) or 0.0) for plate in plates if plate["plate_type"] == "oceanic")

    currents = []
    for row in range(3):
        for col in range(5):
            nx = (col + 0.5) / 5.0
            ny = (row + 0.5) / 3.0
            current = _mantle_current_at(nx, ny, map_seed=map_seed)
            currents.append({
                "pos_x": round(nx, 4),
                "pos_y": round(ny, 4),
                **current,
            })

    sample_w = 97
    sample_h = 49
    owner_rows = _sample_plate_owner_rows(plates, sample_w, sample_h)

    # Boundary geometry needs substantially more resolution than the stored
    # lithosphere summary. Marching the continuous plate-distance fields at
    # the heightfield resolution removes the old axis-aligned stair steps
    # without inflating every downstream lithosphere grid.
    boundary_w = 257
    boundary_h = 129
    boundary_owner_rows = _sample_plate_owner_rows(plates, boundary_w, boundary_h)
    boundary_segments = _decorate_boundary_segments(
        _continuous_boundary_segments(boundary_owner_rows, plates),
        plates,
        map_seed,
    )

    boundaries = _summarize_boundaries(boundary_segments)

    topology = _topology_and_lithosphere(owner_rows, plates, boundary_segments, map_seed)

    geologic_history = _latent_geologic_history(plates, terrain, map_seed, boundaries=boundaries)
    hotspot_model = _hotspot_model(plates, map_seed)
    continental_provinces = _continental_province_model(plates, map_seed)
    canvas = terrain.get("map_canvas") if isinstance(terrain.get("map_canvas"), dict) else {}
    orogen_system_model = derive_orogen_system_model(
        plates,
        boundary_segments,
        geologic_history=geologic_history,
        map_seed=map_seed,
        age_myr=0.0,
        circumference_m=max(1.0, float(canvas.get("circumference_m", 40_075_000.0) or 40_075_000.0)),
    )

    return {
        "status": "plates_defined",
        "planet_id": planet_id,
        "map_seed": map_seed,
        "age_myr": 0.0,
        "plate_count": plate_count,
        "lithosphere_prior": {
            "source": "first_screen_composition_and_volatile_history",
            "water_inventory_index": round(water_inventory, 4),
            "felsic_inventory_percent": round(felsic_inventory, 4),
            "continental_crust_potential": round(continental_crust_potential, 3),
            "continental_plate_count": continental_count,
            "oceanic_plate_count": oceanic_count,
            "continental_lithosphere_area_target": round(continental_area_target, 3),
            "resolved_continental_plate_area": round(continental_area, 3),
            "oceanic_lithosphere_area_target": round(oceanic_area_target, 3),
            "resolved_oceanic_plate_area": round(oceanic_area, 3),
            "expected_oceanic_lithosphere_fraction": round(expected_oceanic_lithosphere, 3),
            "uses_final_ocean_coverage": False,
        },
        "sample_grid": {"width": sample_w, "height": sample_h, "owners": owner_rows},
        "boundary_trace_grid": {
            "width": boundary_w,
            "height": boundary_h,
            "geometry_model": "continuous_plate_distance_contour_v1",
        },
        "plates": plates,
        "mantle_currents": currents,
        "boundary_segments": boundary_segments,
        "boundaries": boundaries,
        **topology,
        "geologic_history": geologic_history,
        "orogen_system_model": orogen_system_model,
        "hotspot_model": hotspot_model,
        "continental_province_model": continental_provinces,
        "registry_time_coupled": False,
        "notes": [
            "Plate motion is seeded from mantle current cells before terrain is uplifted.",
            "Coherent orogen systems translate local boundary kinematics into signed uplift, subsidence, volcanic and crustal-thickening forcing.",
        ],
    }


def advance_tectonics_model(tectonic_model, terrain, million_years=125.0):
    tectonic_model = tectonic_model if isinstance(tectonic_model, dict) else {}
    age = float(tectonic_model.get("age_myr", 0.0) or 0.0) + max(1.0, float(million_years or 1.0))
    advanced = dict(tectonic_model)
    plates = []
    drift_factor = max(1.0, float(million_years or 1.0)) / 100.0
    map_seed = str(advanced.get("map_seed") or "")
    for plate in list(advanced.get("plates") or []):
        if not isinstance(plate, dict):
            continue
        updated = dict(plate)
        try:
            cx = float(updated.get("center_x", 0.0) or 0.0)
            cy = float(updated.get("center_y", 0.5) or 0.5)
            vx = float(updated.get("velocity_x_cm_year", 0.0) or 0.0)
            vy = float(updated.get("velocity_y_cm_year", 0.0) or 0.0)
        except (TypeError, ValueError):
            plates.append(updated)
            continue
        current = _mantle_current_at(cx, cy, map_seed=map_seed)
        cx = (cx + vx * 0.00022 * drift_factor + current["dir_x"] * 0.0025 * drift_factor) % 1.0
        cy = _clamp(cy + vy * 0.00016 * drift_factor + current["dir_y"] * 0.0018 * drift_factor, 0.045, 0.955)
        speed = _clamp(float(updated.get("speed_cm_per_year", current["speed_cm_per_year"]) or 0.0) * 0.88 + current["speed_cm_per_year"] * 0.12, 0.3, 9.5)
        updated["center_x"] = round(cx, 4)
        updated["center_y"] = round(cy, 4)
        updated["velocity_x_cm_year"] = round((float(updated.get("velocity_x_cm_year", 0.0) or 0.0) * 0.82 + current["dir_x"] * speed * 0.18), 3)
        updated["velocity_y_cm_year"] = round((float(updated.get("velocity_y_cm_year", 0.0) or 0.0) * 0.82 + current["dir_y"] * speed * 0.18), 3)
        updated["speed_cm_per_year"] = round(speed, 3)
        plates.append(updated)
    if plates:
        advanced["plates"] = plates
        sample_w, sample_h = 97, 49
        boundary_w, boundary_h = 257, 129
        owner_rows = _sample_plate_owner_rows(plates, sample_w, sample_h)
        boundary_owner_rows = _sample_plate_owner_rows(plates, boundary_w, boundary_h)
        advanced["boundary_segments"] = _decorate_boundary_segments(
            _continuous_boundary_segments(boundary_owner_rows, plates),
            plates,
            map_seed,
        )
        advanced["sample_grid"] = {"width": sample_w, "height": sample_h, "owners": owner_rows}
        advanced["boundary_trace_grid"] = {
            "width": boundary_w,
            "height": boundary_h,
            "geometry_model": "continuous_plate_distance_contour_v1",
        }
        advanced.update(_topology_and_lithosphere(owner_rows, plates, advanced["boundary_segments"], map_seed))
    boundaries = _summarize_boundaries(advanced.get("boundary_segments") or [])
    advanced["boundaries"] = boundaries
    canvas = terrain.get("map_canvas") if isinstance(terrain.get("map_canvas"), dict) else {}
    advanced["orogen_system_model"] = derive_orogen_system_model(
        advanced.get("plates") or [],
        advanced.get("boundary_segments") or [],
        geologic_history=advanced.get("geologic_history") or {},
        map_seed=map_seed,
        age_myr=age,
        circumference_m=max(1.0, float(canvas.get("circumference_m", 40_075_000.0) or 40_075_000.0)),
    )
    advanced["status"] = "tectonics_advanced"
    advanced["age_myr"] = round(age, 1)
    advanced["geologic_time_step_myr"] = max(1.0, float(million_years or 1.0))
    advanced["time_domain"] = "pre_generation_geologic_history"
    advanced["registry_time_coupled"] = False
    uplift = 0.0
    basin = 0.0
    erosion = 0.0
    for boundary in boundaries:
        activity = float(boundary.get("activity", 0.0) or 0.0)
        kind = boundary.get("kind")
        if kind in {"collision", "subduction"}:
            uplift += activity
        elif kind == "divergent":
            basin += activity
        if kind in {"collision", "subduction", "divergent"}:
            erosion += activity * 0.35
    time_factor = min(1.0, age / 125.0)
    advanced["surface_effects"] = {
        "orogenic_uplift": round(min(1.0, time_factor * 0.65 + uplift / max(1.0, len(boundaries) * 0.12)), 3),
        "ocean_basin_opening": round(min(1.0, time_factor * 0.55 + basin / max(1.0, len(boundaries) * 0.10)), 3),
        "erosion_progress": round(min(1.0, age / 320.0 + erosion / max(1.0, len(boundaries) * 1.8)), 3),
    }
    return advanced


def mature_tectonics_model(tectonic_model, terrain, cycles=4, million_years_per_cycle=45.0):
    matured = tectonic_model if isinstance(tectonic_model, dict) else {}
    for _index in range(max(1, int(cycles or 1))):
        matured = advance_tectonics_model(matured, terrain, million_years=million_years_per_cycle)
    matured["maturation_cycles"] = max(1, int(cycles or 1))
    return matured


def derive_crater_model(terrain, seed=None, physics=None, planet_id=""):
    terrain = terrain if isinstance(terrain, dict) else {}
    seed = seed if isinstance(seed, dict) else {}
    physics = physics if isinstance(physics, dict) else {}
    cratering = terrain.get("cratering") if isinstance(terrain.get("cratering"), dict) else {}
    map_seed = terrain.get("map_seed") or resolved_map_seed(seed, planet_id=planet_id)
    density = _clamp(cratering.get("density", 0.65), 0.0, 1.0)
    retention = str(cratering.get("retention") or "moderate")
    max_km = max(10.0, float(cratering.get("max_crater_diameter_km", 400.0) or 400.0))
    radius_m = max(1.0, float(physics.get("radius_m") or (terrain.get("map_canvas") or {}).get("radius_m") or 6_371_000.0))
    radius_km = radius_m / 1000.0
    circumference_km = math.tau * radius_km
    surface_area_million_km2 = 4.0 * math.pi * radius_km * radius_km / 1_000_000.0
    min_km = max(1.2, circumference_km / 512.0)
    atmospheric_cutoff_km = max(0.0, float(cratering.get("atmospheric_entry_cutoff_km", 0.0) or 0.0))
    min_km = max(min_km, atmospheric_cutoff_km)
    surface_age_myr = max(0.0, float(cratering.get("surface_age_myr", seed.get("surface_age_myr", 4500.0)) or 0.0))
    impact_flux = max(0.05, float(cratering.get("impact_flux_factor", seed.get("impact_flux_factor", 1.0)) or 1.0))
    resurfacing = _clamp(cratering.get("resurfacing_fraction", seed.get("resurfacing_fraction", 0.0)), 0.0, 1.0)
    exposure = 1.0 - math.exp(-surface_age_myr / 1150.0)
    retention_factor = {"high": 1.0, "moderate": 0.58, "low": 0.2}.get(retention, 0.5)
    population_slope = _clamp(seed.get("crater_population_slope", 1.9), 1.45, 2.35)
    stochastic_flux = seed_range(map_seed, "crater_flux_history", 0.72, 1.28)
    density_ge10_per_million_km2 = 780.0 * density * exposure * impact_flux * stochastic_flux * retention_factor
    expected_count = (
        density_ge10_per_million_km2
        * surface_area_million_km2
        * ((min_km / 10.0) ** -population_slope)
    )
    count = max(12, min(2200, int(round(expected_count))))
    craters = []
    golden = 0.61803398875
    for index in range(count):
        nx = (seed_range(map_seed, "crater_x_offset", 0.0, 1.0) + index * golden) % 1.0
        nx = (nx + seed_range(map_seed, f"crater_{index}_jitter_x", -0.025, 0.025)) % 1.0
        sphere_z = 1.0 - 2.0 * ((index + 0.5) / count)
        sphere_z = _clamp(sphere_z + seed_range(map_seed, f"crater_{index}_jitter_z", -0.025, 0.025), -0.995, 0.995)
        latitude = math.asin(sphere_z)
        ny = _clamp(0.5 - latitude / math.pi, 0.01, 0.99)
        quantile = _clamp(seed_range(map_seed, f"crater_{index}_size", 0.0001, 0.9999), 0.0001, 0.9999)
        diameter = min(max_km, min_km * ((1.0 - quantile) ** (-1.0 / population_slope)))
        small_crater_survival = 1.0 - resurfacing * math.exp(-diameter / 38.0)
        if seed_range(map_seed, f"crater_{index}_survival", 0.0, 1.0) > small_crater_survival:
            continue
        simple_to_complex_km = max(8.0, 18.0 * (max(0.02, float(physics.get("surface_gravity_g", 1.0) or 1.0)) / 0.16) ** -0.22)
        depth_ratio = 0.105 if diameter <= simple_to_complex_km else 0.075 * (diameter / simple_to_complex_km) ** -0.22
        thermal_relaxation = resurfacing * _clamp((diameter - 25.0) / 180.0, 0.0, 0.78)
        depth_m = min(7200.0, diameter * 1000.0 * depth_ratio) * (1.0 - thermal_relaxation)
        rim_height_m = min(1800.0, diameter * 1000.0 * 0.025) * (1.0 - thermal_relaxation * 0.65)
        craters.append({
            "id": f"crater_{index + 1:02d}",
            "x": round(nx, 4),
            "y": round(ny, 4),
            "diameter_km": round(diameter, 2),
            "depth_m": round(depth_m, 1),
            "rim_height_m": round(rim_height_m, 1),
            "morphology": "complex_or_basin" if diameter > simple_to_complex_km else "simple",
            "relaxation_fraction": round(thermal_relaxation, 3),
        })
    actual_density = len(craters) / max(1e-9, surface_area_million_km2)
    return {
        "status": "craters_seeded",
        "planet_id": planet_id,
        "map_seed": map_seed,
        "density": round(density, 3),
        "radius_m": round(radius_m, 3),
        "surface_area_million_km2": round(surface_area_million_km2, 4),
        "minimum_catalog_diameter_km": round(min_km, 3),
        "atmospheric_entry_cutoff_km": round(atmospheric_cutoff_km, 3),
        "maximum_crater_diameter_km": round(max_km, 3),
        "size_frequency_cumulative_slope": round(population_slope, 3),
        "craters_per_million_km2_above_catalog_min": round(actual_density, 2),
        "surface_age_myr": round(surface_age_myr, 1),
        "impact_flux_factor": round(impact_flux * stochastic_flux, 3),
        "resurfacing_fraction": round(resurfacing, 3),
        "craters": craters,
        "drivers": {
            "size": ["impactor_size_distribution", "surface_gravity", "body_radius", "target_material", "impact_velocity"],
            "density": ["surface_exposure_age", "impact_flux", "atmospheric_screening", "erosion", "resurfacing", "saturation"],
        },
        "notes": [
            "Crater diameters follow a deterministic power-law size-frequency population capped by the body's basin scale.",
            "Surface age and impact flux add craters; atmosphere, erosion, resurfacing, and saturation reduce the retained population.",
        ],
    }
