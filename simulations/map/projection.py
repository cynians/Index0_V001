"""Shared projection helpers for movable equirectangular world maps."""

import math


def project_normalized_point(nx, ny, focus_x=0.0, focus_y=0.0):
    focus_x = float(focus_x or 0.0) % 1.0
    focus_y = max(-0.5, min(0.5, float(focus_y or 0.0)))
    longitude = float(nx) * math.tau - math.pi
    latitude = math.pi * (0.5 - float(ny))
    cos_latitude = math.cos(latitude)
    world_x = cos_latitude * math.cos(longitude)
    world_y = cos_latitude * math.sin(longitude)
    world_z = math.sin(latitude)
    center_longitude = focus_x * math.tau
    center_latitude = -focus_y * math.pi
    sin_lon, cos_lon = math.sin(center_longitude), math.cos(center_longitude)
    sin_lat, cos_lat = math.sin(center_latitude), math.cos(center_latitude)
    untilted_x = cos_lon * world_x + sin_lon * world_y
    view_y = -sin_lon * world_x + cos_lon * world_y
    view_x = cos_lat * untilted_x + sin_lat * world_z
    view_z = -sin_lat * untilted_x + cos_lat * world_z
    view_longitude = math.atan2(view_y, view_x)
    view_latitude = math.asin(max(-1.0, min(1.0, view_z)))
    return (view_longitude + math.pi) / math.tau, 0.5 - view_latitude / math.pi


def unproject_normalized_point(nx, ny, focus_x=0.0, focus_y=0.0):
    view_longitude = float(nx) * math.tau - math.pi
    view_latitude = math.pi * (0.5 - float(ny))
    view_cos_lat = math.cos(view_latitude)
    view_x = view_cos_lat * math.cos(view_longitude)
    view_y = view_cos_lat * math.sin(view_longitude)
    view_z = math.sin(view_latitude)
    center_longitude = (float(focus_x or 0.0) % 1.0) * math.tau
    center_latitude = -max(-0.5, min(0.5, float(focus_y or 0.0))) * math.pi
    sin_lon, cos_lon = math.sin(center_longitude), math.cos(center_longitude)
    sin_lat, cos_lat = math.sin(center_latitude), math.cos(center_latitude)
    tilted_x = cos_lat * view_x - sin_lat * view_z
    source_z = sin_lat * view_x + cos_lat * view_z
    source_x = cos_lon * tilted_x - sin_lon * view_y
    source_y = sin_lon * tilted_x + cos_lon * view_y
    source_longitude = math.atan2(source_y, source_x)
    source_latitude = math.asin(max(-1.0, min(1.0, source_z)))
    return (source_longitude + math.pi) / math.tau, 0.5 - source_latitude / math.pi


def _to_uv(x, y):
    return (float(x) + 180.0) / 360.0, (float(y) + 90.0) / 180.0


def _from_uv(nx, ny):
    return float(nx) * 360.0 - 180.0, float(ny) * 180.0 - 90.0


def project_map_world_point(x, y, focus_x=0.0, focus_y=0.0):
    return _from_uv(*project_normalized_point(*_to_uv(x, y), focus_x, focus_y))


def unproject_map_world_point(x, y, focus_x=0.0, focus_y=0.0):
    return _from_uv(*unproject_normalized_point(*_to_uv(x, y), focus_x, focus_y))


def _densify_map_ring(points, maximum_step_degrees=1.5):
    source = [(float(x), float(y)) for x, y in points]
    if len(source) > 1 and source[0] == source[-1]:
        source.pop()
    if len(source) < 3:
        return source
    dense = []
    for index, (x0, y0) in enumerate(source):
        x1, y1 = source[(index + 1) % len(source)]
        delta_x = x1 - x0
        # GeoJSON rings normally split at the antimeridian. Interpolate over
        # that short wrapped edge, but preserve an intentional full-world edge.
        if 180.0 < abs(delta_x) < 359.999:
            delta_x -= math.copysign(360.0, delta_x)
        delta_y = y1 - y0
        steps = max(1, int(math.ceil(max(abs(delta_x), abs(delta_y)) / maximum_step_degrees)))
        for step in range(steps):
            amount = step / steps
            x = x0 + delta_x * amount
            while x < -180.0:
                x += 360.0
            while x > 180.0:
                x -= 360.0
            dense.append((x, y0 + delta_y * amount))
    return dense


def _densify_map_line(points, maximum_step_degrees=1.5):
    source = [(float(x), float(y)) for x, y in points]
    if len(source) < 2:
        return source
    dense = [source[0]]
    for x0, y0 in source[1:]:
        previous_x, previous_y = dense[-1]
        delta_x = x0 - previous_x
        if 180.0 < abs(delta_x) < 359.999:
            delta_x -= math.copysign(360.0, delta_x)
        delta_y = y0 - previous_y
        steps = max(1, int(math.ceil(max(abs(delta_x), abs(delta_y)) / maximum_step_degrees)))
        for step in range(1, steps + 1):
            amount = step / steps
            x = previous_x + delta_x * amount
            while x < -180.0:
                x += 360.0
            while x > 180.0:
                x -= 360.0
            dense.append((x, previous_y + delta_y * amount))
    return dense


def _clip_polygon_x(points, boundary, keep_greater):
    if not points:
        return []

    def inside(point):
        return point[0] >= boundary if keep_greater else point[0] <= boundary

    clipped = []
    previous = points[-1]
    previous_inside = inside(previous)
    for current in points:
        current_inside = inside(current)
        if current_inside != previous_inside:
            denominator = current[0] - previous[0]
            amount = 0.0 if abs(denominator) < 1e-12 else (boundary - previous[0]) / denominator
            clipped.append((boundary, previous[1] + (current[1] - previous[1]) * amount))
        if current_inside:
            clipped.append(current)
        previous = current
        previous_inside = current_inside
    return clipped


def _clip_to_projection_frame(points):
    return _clip_polygon_x(_clip_polygon_x(points, -180.0, True), 180.0, False)


def project_map_world_ring(points, focus_x=0.0, focus_y=0.0):
    """Morph a stored lon/lat ring into clipped pieces of the focused view."""
    projected = [
        project_map_world_point(x, y, focus_x, focus_y)
        for x, y in _densify_map_ring(points)
    ]
    if not projected:
        return []
    unwrapped = [projected[0]]
    for x, y in projected[1:]:
        previous_x = unwrapped[-1][0]
        while x - previous_x > 180.0:
            x -= 360.0
        while previous_x - x > 180.0:
            x += 360.0
        unwrapped.append((x, y))
    minimum_x = min(x for x, _y in unwrapped)
    maximum_x = max(x for x, _y in unwrapped)
    first_shift = int(math.floor((-180.0 - maximum_x) / 360.0)) - 1
    last_shift = int(math.ceil((180.0 - minimum_x) / 360.0)) + 1
    visible_parts = []
    signatures = set()
    for shift_index in range(first_shift, last_shift + 1):
        shifted = [(x + shift_index * 360.0, y) for x, y in unwrapped]
        clipped = _clip_to_projection_frame(shifted)
        if len(clipped) < 3:
            continue
        signature = tuple((round(x, 6), round(y, 6)) for x, y in clipped)
        if signature in signatures:
            continue
        signatures.add(signature)
        visible_parts.append(clipped)
    return visible_parts


def project_map_world_line(points, focus_x=0.0, focus_y=0.0):
    """Morph a stored lon/lat line into the focused map view.

    Lines are not clipped into polygons: off-frame endpoints are intentionally
    retained so the renderer can draw a continuous segment to the viewport
    edge.  Repeated shifted copies preserve lines that cross the antimeridian.
    """
    projected = [
        project_map_world_point(x, y, focus_x, focus_y)
        for x, y in _densify_map_line(points)
    ]
    if len(projected) < 2:
        return []
    unwrapped = [projected[0]]
    for x, y in projected[1:]:
        previous_x = unwrapped[-1][0]
        while x - previous_x > 180.0:
            x -= 360.0
        while previous_x - x > 180.0:
            x += 360.0
        unwrapped.append((x, y))
    minimum_x = min(x for x, _y in unwrapped)
    maximum_x = max(x for x, _y in unwrapped)
    first_shift = int(math.floor((-180.0 - maximum_x) / 360.0)) - 1
    last_shift = int(math.ceil((180.0 - minimum_x) / 360.0)) + 1
    visible_parts = []
    for shift_index in range(first_shift, last_shift + 1):
        shifted = [(x + shift_index * 360.0, y) for x, y in unwrapped]
        if max(x for x, _y in shifted) < -180.0 or min(x for x, _y in shifted) > 180.0:
            continue
        visible_parts.append(shifted)
    return visible_parts
