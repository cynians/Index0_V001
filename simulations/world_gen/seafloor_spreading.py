"""Seafloor spreading: segmented mid-ocean ridges, transform offsets, fracture zones.

A spreading ridge is not a smooth curve.  It is a staircase of short ridge
segments perpendicular to the plates' relative motion, joined by transform
faults parallel to it (Atlantic: major offsets every ~300-800 km).  Crust
ages linearly away from its own segment, at the half-spreading rate, so
where two segments are offset the crust on either side of the transform's
inactive extension -- a fracture zone -- differs in age, and therefore in
depth, by a fixed step all the way across the ocean basin.

Depth follows the plate-cooling law GDH1 (Stein & Stein 1992): the ridge
crest sits ~2.6 km deep, the seafloor subsides as 365 sqrt(t) m for the
first 20 Myr and then flattens toward ~5.6 km as the lithosphere reaches
thermal equilibrium.

``build_spreading_model`` is computed once per tectonic state from the
divergent plate-boundary segments and plate velocities;
``seafloor_age_myr`` is evaluated at any map point.
"""

from __future__ import annotations

import math

from simulations.world_gen.map_seed import seed_range

# First-order ridge segmentation: major transform faults every ~320-700 km.
RIDGE_SEGMENT_M = (320_000.0, 700_000.0)
# Offset of a segment's axis beyond the boundary's own curvature (ridge
# jumps, asymmetric spreading), as a fraction of the segment length.
TRANSFORM_OFFSET_JITTER = 0.18
MAX_SEAFLOOR_AGE_MYR = 200.0
# Width over which the age steps at a fracture zone (a transform's inactive
# trace; physically tens of km, widened to ~1.5 planetary samples so the
# step renders as a lineament instead of aliased stipple).
FRACTURE_ZONE_WIDTH_M = 120_000.0
# GDH1 plate-cooling depth-age relation (m, Myr).
RIDGE_CREST_DEPTH_M = 2600.0
YOUNG_SUBSIDENCE_M_PER_SQRT_MYR = 365.0
OLD_SEAFLOOR_ASYMPTOTE_M = 5651.0
OLD_SEAFLOOR_DECAY_M = 2473.0
OLD_SEAFLOOR_RATE_PER_MYR = 0.0278
# 1 cm/yr = 10 km/Myr.
M_PER_MYR_PER_CM_YEAR = 10_000.0
# Mean plate speed of a planet whose mantle loses Earth's 0.087 W m^-2.
# Boundary-layer convection: heat flow q ~ Ra^(1/3), surface velocity
# v ~ Ra^(2/3), so v scales as q^2.
EARTH_MEAN_PLATE_SPEED_CM_YEAR = 5.0
EARTH_MANTLE_HEAT_FLOW_W_M2 = 0.087


def convective_plate_speed_cm_year(internal_heat_w_m2):
    """Mean surface (plate) speed a convecting mantle with this heat flow drives."""
    ratio = max(0.0, float(internal_heat_w_m2)) / EARTH_MANTLE_HEAT_FLOW_W_M2
    return min(25.0, max(0.3, EARTH_MEAN_PLATE_SPEED_CM_YEAR * ratio * ratio))


def plate_cooling_subsidence_m(age_myr):
    """Seafloor depth below the ridge crest (m) for crust of this age (GDH1)."""
    age = max(0.0, float(age_myr))
    if age <= 20.0:
        return YOUNG_SUBSIDENCE_M_PER_SQRT_MYR * math.sqrt(age)
    return OLD_SEAFLOOR_ASYMPTOTE_M - OLD_SEAFLOOR_DECAY_M * math.exp(-OLD_SEAFLOOR_RATE_PER_MYR * age) - RIDGE_CREST_DEPTH_M


def _smoothstep(value):
    value = min(1.0, max(0.0, value))
    return value * value * (3.0 - 2.0 * value)


def _wrapped_delta(a, b):
    delta = (float(a) - float(b)) % 1.0
    return delta - 1.0 if delta > 0.5 else delta


def _local_metres(nx, ny, center_x, center_y, circumference_m):
    """East/south offsets (m) of a map point from a centre, on the sphere."""
    mean_latitude = (0.5 - 0.5 * (float(ny) + center_y)) * math.pi
    east = _wrapped_delta(nx, center_x) * circumference_m * max(0.05, math.cos(mean_latitude))
    south = (float(ny) - center_y) * circumference_m * 0.5
    return east, south


def build_spreading_model(plates, boundary_segments, map_seed, circumference_m, internal_heat_w_m2=None):
    """Segmented ridge axes for every divergent plate pair.

    Plate velocities give each ridge's spreading direction and its rate
    relative to the other plates; the absolute scale comes from the
    planet's convective vigour (``convective_plate_speed_cm_year``), since
    the tectonic model's own speeds are only relative (clamped at a floor).
    """
    plates_by_id = {plate.get("id"): plate for plate in plates or []}
    model_speeds = [float(plate.get("speed_cm_per_year", 0.0) or 0.0) for plate in plates or []]
    mean_model_speed = sum(model_speeds) / len(model_speeds) if model_speeds else 0.0
    rate_scale = 1.0
    if internal_heat_w_m2 is not None and mean_model_speed > 1e-6:
        rate_scale = convective_plate_speed_cm_year(internal_heat_w_m2) / mean_model_speed
    groups = {}
    for segment in boundary_segments or []:
        if segment.get("kind") != "divergent":
            continue
        pair = tuple(sorted((str(segment.get("plate_a")), str(segment.get("plate_b")))))
        groups.setdefault(pair, []).append(segment)
    ridges = []
    for pair, segments in sorted(groups.items()):
        plate_a, plate_b = plates_by_id.get(pair[0]), plates_by_id.get(pair[1])
        if not plate_a or not plate_b:
            continue
        relative_x = float(plate_b.get("velocity_x_cm_year", 0.0) or 0.0) - float(plate_a.get("velocity_x_cm_year", 0.0) or 0.0)
        relative_y = float(plate_b.get("velocity_y_cm_year", 0.0) or 0.0) - float(plate_a.get("velocity_y_cm_year", 0.0) or 0.0)
        model_rate = math.hypot(relative_x, relative_y)
        if model_rate < 0.2:
            continue
        direction = (relative_x / model_rate, relative_y / model_rate)
        full_rate = model_rate * rate_scale
        along = (-direction[1], direction[0])
        points = []
        for segment in segments:
            for key in ("1", "2"):
                points.append((float(segment.get(f"x{key}", 0.0) or 0.0), float(segment.get(f"y{key}", 0.5) or 0.5)))
        # Wrap-aware centroid.
        reference_x = points[0][0]
        center_x = (reference_x + sum(_wrapped_delta(x, reference_x) for x, _y in points) / len(points)) % 1.0
        center_y = sum(y for _x, y in points) / len(points)
        across_along = []
        for x, y in points:
            east, south = _local_metres(x, y, center_x, center_y, circumference_m)
            across_along.append((east * direction[0] + south * direction[1], east * along[0] + south * along[1]))
        key = f"ridge:{pair[0]}:{pair[1]}"
        segment_m = seed_range(map_seed, f"{key}:segment_m", *RIDGE_SEGMENT_M)
        along_min = min(value for _a, value in across_along)
        along_max = max(value for _a, value in across_along)
        origin = along_min - seed_range(map_seed, f"{key}:phase", 0.0, 1.0) * segment_m
        count = max(1, int(math.ceil((along_max - origin) / segment_m)))
        bins = [[] for _ in range(count)]
        for across, along_value in across_along:
            bins[min(count - 1, int((along_value - origin) // segment_m))].append(across)
        axis = [sum(values) / len(values) if values else None for values in bins]
        known = [index for index, value in enumerate(axis) if value is not None]
        for index in range(count):
            if axis[index] is None:
                nearest = min(known, key=lambda other: abs(other - index))
                axis[index] = axis[nearest]
        axis = [
            value + seed_range(map_seed, f"{key}:offset:{index}", -1.0, 1.0) * TRANSFORM_OFFSET_JITTER * segment_m
            for index, value in enumerate(axis)
        ]
        ridges.append({
            "plates": list(pair),
            "center_x": round(center_x, 6),
            "center_y": round(center_y, 6),
            "direction": [round(direction[0], 6), round(direction[1], 6)],
            "along_origin_m": round(origin, 1),
            "along_extent_m": [round(along_min, 1), round(along_max, 1)],
            "segment_m": round(segment_m, 1),
            "axis_m": [round(value, 1) for value in axis],
            "full_rate_cm_year": round(full_rate, 3),
            "half_rate_m_per_myr": round(full_rate * 0.5 * M_PER_MYR_PER_CM_YEAR, 1),
        })
    return {
        "model": "segmented_ridge_transform_v1",
        "circumference_m": float(circumference_m),
        "ridges": ridges,
        "depth_law": "GDH1 plate cooling (Stein & Stein 1992)",
        "rate_scale": round(rate_scale, 4),
    }


def seafloor_age_myr(model, nx, ny):
    """Age (Myr) of oceanic crust at a map point, or None without ridges.

    Distance across the point's own ridge segment (along the spreading
    direction) over the half-spreading rate; beyond a ridge's ends the
    lateral distance counts too, so the ridge that made the crust wins.
    """
    ridges = (model or {}).get("ridges") or []
    if not ridges:
        return None
    circumference_m = float(model.get("circumference_m") or 40_075_000.0)
    best = None
    for ridge in ridges:
        direction = ridge["direction"]
        east, south = _local_metres(nx, ny, float(ridge["center_x"]), float(ridge["center_y"]), circumference_m)
        across = east * direction[0] + south * direction[1]
        along = east * -direction[1] + south * direction[0]
        axis = ridge["axis_m"]
        segment_m = float(ridge["segment_m"])
        position = (along - float(ridge["along_origin_m"])) / segment_m
        index = min(len(axis) - 1, max(0, int(math.floor(position))))
        axis_m = float(axis[index])
        # Blend into the neighbouring segment within FRACTURE_ZONE_WIDTH_M of
        # the boundary: the age step is narrower than a planetary sample, so
        # a hard switch aliased into stippled stair-steps.
        offset = (position - math.floor(position)) * segment_m
        half_width = FRACTURE_ZONE_WIDTH_M * 0.5
        if offset > segment_m - half_width and index + 1 < len(axis):
            blend = _smoothstep((offset - (segment_m - half_width)) / FRACTURE_ZONE_WIDTH_M)
            axis_m += (float(axis[index + 1]) - axis_m) * blend
        elif offset < half_width and index > 0:
            blend = _smoothstep((half_width - offset) / FRACTURE_ZONE_WIDTH_M)
            axis_m += (float(axis[index - 1]) - axis_m) * blend
        distance = abs(across - axis_m)
        low, high = ridge["along_extent_m"]
        lateral = max(0.0, float(low) - segment_m - along, along - float(high) - segment_m)
        age = math.hypot(distance, lateral) / max(1.0, float(ridge["half_rate_m_per_myr"]))
        if best is None or age < best:
            best = age
    return min(MAX_SEAFLOOR_AGE_MYR, best)
