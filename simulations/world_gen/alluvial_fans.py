"""Alluvial fans at mountain fronts (LOD2+).

Where a sediment-laden channel leaves its confined mountain valley, the flow
spreads and the slope drops, transport capacity falls and the channel
deposits a cone of gravel and sand that it sweeps back and forth by
avulsion: an alluvial fan.  Neighbouring fans coalesce into a bajada
(Death Valley and Owens Valley fans, the Tian Shan piedmont, Andean
volcanic ring plains, Martian crater fans at Gale and Saheki).

Scaling, from the catchment area ``A_d`` (km2):

* fan area ``A_f = c A_d^0.9`` (Bull 1964; Hooke 1968: exponent 0.8-1.0,
  coefficient 0.1-2); fans are largest in drylands, where flashy runoff
  delivers more sediment than the basin removes (Blair & McPherson 1994), so
  ``c`` grows with the parent's aridity;
* fan surface gradient ``S_f = a A_d^-0.25`` (Bull 1964; Harvey 2011:
  exponent 0.15-0.35), 3.4 degrees at 1 km2, 1.1 degrees at 100 km2.

Fans are fed by mountain catchments (below ~10^3 km2) through channels at
least ~2 % steep.  The apex is where such a channel's slope over the reach
upstream is at least 1.5 times the fan gradient and the ground downstream is gentler than the fan:
the channel leaves its confinement.  The fan surface is a slightly concave
cone from the apex (``z = z_apex - S_f r (1 - 0.25 r / R)``, radius
``R = sqrt(2 A_f / pi)`` for a half cone), and the deposit is where that
surface lies above the ground, so fans end against valley sides and merge
where they meet.  Mass is redistributed, not added: each fan's volume is
eroded from its own catchment, weighted by slope.

Scale gate as for ``alluvial_channels``: a fan is built at the first level
whose spacing resolves its radius (``R >= RESOLVE_RADIUS_CELLS dx``).
Deeper levels inherit the surface through the heightfield and the fan
geometry through ``heightmap_model.regional_landforms`` (global UV), which
the material layer reads for the gravel-to-sand radial fining.
"""

from __future__ import annotations

import math

import numpy as np

from simulations.world_gen.material_routing import (
    d8_receivers,
    filled_routing,
    inlet_mask,
    upstream_sum,
)

LANDFORM_ID = "alluvial_fans"
FAN_MIN_LEVEL = 2
# A fan's cone reads as a shape when its radius spans this many cells.
RESOLVE_RADIUS_CELLS = 4.0
FAN_AREA_EXPONENT = 0.9
# c in A_f = c A_d^0.9 (km2), humid .. hyper-arid.
FAN_AREA_COEFFICIENT = (0.12, 0.6)
FAN_GRADIENT_AT_1_KM2 = 0.06
FAN_GRADIENT_EXPONENT = 0.25
# Radial concavity of the fan surface (gradient at the toe / at the apex = 0.5).
FAN_CONCAVITY = 0.25
# Apex test: upstream channel at least this many fan gradients steep,
# downstream ground at most this fraction of the fan gradient.
APEX_UPSTREAM_FACTOR = 1.5
APEX_DOWNSTREAM_FACTOR = 0.8
# Fans are fed by mountain catchments, nearly all below ~10^3 km2 (Harvey
# 2011); larger rivers build megafans only in subsiding forelands (not
# modelled), and their feeders are mountain channels, at least ~2 % steep.
MAX_FAN_CATCHMENT_KM2 = 1000.0
MIN_FEEDER_SLOPE = 0.02
# Below ~0.1 km2 a gully mouth builds a colluvial or debris cone, not an
# alluvial fan, and the gradient law (calibrated on 0.1-1000 km2 basins)
# runs off to 20-degree "fans" on every river bank at Parcel scale.
MIN_FAN_CATCHMENT_KM2 = 0.1
# Cells over which up- and downstream slopes are measured.
APEX_REACH_CELLS = 4
# Largest share of a catchment cell's height above the apex that its fan may take.
MAX_CATCHMENT_LOWERING_SHARE = 0.3


def fan_area_coefficient(aridity):
    low, high = FAN_AREA_COEFFICIENT
    return low + (high - low) * float(np.clip(aridity, 0.0, 1.0))


def fan_geometry(catchment_km2, aridity):
    """``(radius_m, gradient)`` of the fan a catchment builds."""
    catchment_km2 = np.maximum(np.asarray(catchment_km2, dtype=np.float64), 1e-6)
    fan_km2 = fan_area_coefficient(aridity) * catchment_km2 ** FAN_AREA_EXPONENT
    radius_m = np.sqrt(2.0 * fan_km2 * 1.0e6 / math.pi)
    gradient = FAN_GRADIENT_AT_1_KM2 * catchment_km2 ** -FAN_GRADIENT_EXPONENT
    return radius_m, gradient


def _pointer_steps(pointer, steps):
    """Follow ``pointer`` (flat indices, ``size`` = none) ``steps`` times."""
    size = pointer.size
    current = np.arange(size)
    extended = np.append(pointer, size)
    for _step in range(steps):
        current = np.where(current < size, extended[np.minimum(current, size)], size)
    return current


def _main_donor(receivers, area):
    """The donor with the largest catchment for every cell (``size`` = none)."""
    size = receivers.size
    donor = np.full(size, size, dtype=np.int64)
    order = np.argsort(area.ravel(), kind="stable")
    valid = receivers[order] < size
    donor[receivers[order][valid]] = order[valid]
    return donor


def find_fan_apexes(elevation, land, *, dx, dy, aridity, inflow_cells=None, min_radius_m=0.0, max_radius_m=np.inf):
    """Apex cells, catchment area and fan geometry for this grid.

    Returns ``(receivers, area_m2, apexes)`` with ``apexes`` a list of dicts
    (``cell``, ``area_km2``, ``radius_m``, ``gradient``), largest first,
    none closer to a larger one than half its radius.
    """
    elevation = np.asarray(elevation, dtype=np.float64)
    shape = elevation.shape
    receivers = filled_routing(elevation, land, dx=dx, dy=dy, inlets=inlet_mask(inflow_cells, shape, dx=dx, dy=dy))
    sources = np.ones(receivers.size)
    if inflow_cells is not None:
        sources = sources + np.asarray(inflow_cells, dtype=np.float64).ravel()
    area = upstream_sum(receivers, sources)[:, 0] * dx * dy
    flat = elevation.ravel()
    spacing = math.sqrt(dx * dy)
    reach = APEX_REACH_CELLS
    downstream = _pointer_steps(receivers, reach)
    upstream = _pointer_steps(_main_donor(receivers, area), reach)
    size = receivers.size
    down_ok = downstream < size
    up_ok = upstream < size
    slope_down = np.where(down_ok, (flat - flat[np.minimum(downstream, size - 1)]) / (reach * spacing), 0.0)
    slope_up = np.where(up_ok, (flat[np.minimum(upstream, size - 1)] - flat) / (reach * spacing), 0.0)
    radius_m, gradient = fan_geometry(area / 1.0e6, aridity)
    candidate = (
        np.asarray(land, dtype=bool).ravel() & up_ok & down_ok
        & (slope_up >= np.maximum(APEX_UPSTREAM_FACTOR * gradient, MIN_FEEDER_SLOPE))
        & (area <= MAX_FAN_CATCHMENT_KM2 * 1.0e6)
        & (area >= MIN_FAN_CATCHMENT_KM2 * 1.0e6)
        & (slope_down <= APEX_DOWNSTREAM_FACTOR * gradient)
        & (slope_down > 0.0)
        & (radius_m >= min_radius_m) & (radius_m < max_radius_m)
    )
    # Along one channel only the first gentle cell below the front is an
    # apex: drop candidates whose main donor is itself a candidate.
    donor = _main_donor(receivers, area)
    donor_candidate = np.where(donor < size, candidate[np.minimum(donor, size - 1)], False)
    candidate &= ~donor_candidate
    cells = np.flatnonzero(candidate)
    height, width = shape
    apexes = []
    taken_rows, taken_columns, taken_radius = [], [], []
    for cell in cells[np.argsort(-area[cells], kind="stable")].tolist():
        row, column = divmod(cell, width)
        if taken_rows:
            distance = np.hypot((np.asarray(taken_columns) - column) * dx, (np.asarray(taken_rows) - row) * dy)
            if np.any(distance < 0.5 * np.asarray(taken_radius)):
                continue
        # The fan surface meets the basin floor at its toe, one radius down
        # the channel; its head stands (S_f - S_basin) R above the old floor.
        toe = cell
        for _step in range(max(1, int(round(radius_m[cell] / spacing)))):
            if receivers[toe] >= size:
                break
            toe = int(receivers[toe])
        surface_at_apex = float(flat[toe]) + float(gradient[cell]) * float(radius_m[cell]) * (1.0 - FAN_CONCAVITY)
        apexes.append({
            "cell": cell,
            "area_km2": float(area[cell] / 1.0e6),
            "radius_m": float(radius_m[cell]),
            "gradient": float(gradient[cell]),
            "surface_at_apex_m": max(surface_at_apex, float(flat[cell])),
        })
        taken_rows.append(row)
        taken_columns.append(column)
        taken_radius.append(float(radius_m[cell]))
    return receivers, area.reshape(shape), apexes


def fan_surface_fields(fans, shape, *, dx, dy, to_local, elevation, build=False):
    """Rasterize fans: ``deposit`` (m), ``fan`` index, ``radial`` (r / R, 0 at
    the apex) and ``cover`` (0..1).

    ``fans`` are stored records (global-UV apex, ``radius_m``, ``gradient``,
    ``apex_elevation_m``).  With ``build`` the deposit is the cone above the
    ground; otherwise the fan already exists and its ground is where the
    surface lies on the cone (within a tolerance for later detail).
    """
    height, width = shape
    radial = np.full(shape, np.inf)
    index = np.full(shape, -1, dtype=np.int64)
    deposit = np.zeros(shape)
    x_cells = (np.arange(width) * dx)[None, :]
    y_cells = (np.arange(height) * dy)[:, None]
    for number, fan in enumerate(fans or []):
        ax, ay = to_local(np.asarray([fan["apex_u"]]), np.asarray([fan["apex_v"]]))
        ax, ay = float(ax[0]), float(ay[0])
        radius = float(fan["radius_m"])
        c0 = max(0, int((ax - radius) / dx) - 1)
        c1 = min(width, int((ax + radius) / dx) + 2)
        r0 = max(0, int((ay - radius) / dy) - 1)
        r1 = min(height, int((ay + radius) / dy) + 2)
        if c0 >= c1 or r0 >= r1:
            continue
        distance = np.hypot(x_cells[:, c0:c1] - ax, y_cells[r0:r1, :] - ay)
        ratio = distance / max(radius, 1e-6)
        cone = float(fan["apex_elevation_m"]) - float(fan["gradient"]) * distance * (1.0 - FAN_CONCAVITY * np.clip(ratio, 0.0, 1.0))
        inside = ratio <= 1.0
        ground = np.asarray(elevation, dtype=np.float64)[r0:r1, c0:c1]
        if build:
            taper = 1.0 - _smooth01((ratio - 0.7) / 0.3)
            thickness = np.where(inside, np.maximum(cone - ground, 0.0) * taper, 0.0)
            window = deposit[r0:r1, c0:c1]
            deposit[r0:r1, c0:c1] = np.maximum(thickness, window)
            covered = thickness > 0.0
        else:
            # Fan ground lies on the cone: ground well below it (a side
            # valley, the plain past the toe) is not fan, which also gives
            # the fan its real, lobate outline instead of a disc.
            tolerance = max(1.5, 0.08 * float(fan["gradient"]) * radius)
            covered = inside & (np.abs(ground - cone) <= tolerance)
        window_radial = radial[r0:r1, c0:c1]
        closer = covered & (ratio < window_radial)
        radial[r0:r1, c0:c1] = np.where(closer, ratio, window_radial)
        index[r0:r1, c0:c1] = np.where(closer, number, index[r0:r1, c0:c1])
    cover = np.where(np.isfinite(radial), 1.0 - _smooth01((radial - 0.75) / 0.25), 0.0)
    return {"deposit": deposit, "fan": index, "radial": radial, "cover": cover}


def _smooth01(values):
    values = np.clip(values, 0.0, 1.0)
    return values * values * (3.0 - 2.0 * values)


def alluvial_fan_residual(
    elevation,
    land,
    *,
    level,
    dx,
    dy,
    parent_spacing_m,
    parent_entity,
    to_local,
    to_uv,
    inflow_cells=None,
    sea_level=None,
):
    """Build the fans this level resolves; return ``(residual, record)``."""
    from simulations.world_gen.alluvial_channels import parent_aridity

    elevation = np.asarray(elevation, dtype=np.float64)
    land = np.asarray(land, dtype=bool)
    shape = elevation.shape
    inherited = inherited_fans(parent_entity)
    record = {"landform": LANDFORM_ID, "level": int(level), "fans": [], "inherited_fans": inherited}
    residual = np.zeros(shape)
    if int(level) < FAN_MIN_LEVEL or land.sum() < 64 or not _running_water(parent_entity):
        return residual, record
    aridity = parent_aridity(parent_entity)
    spacing = math.sqrt(dx * dy)
    minimum = RESOLVE_RADIUS_CELLS * spacing
    maximum = np.inf if int(level) == FAN_MIN_LEVEL or parent_spacing_m <= 0.0 else RESOLVE_RADIUS_CELLS * parent_spacing_m
    receivers, area, apexes = find_fan_apexes(
        elevation, land, dx=dx, dy=dy, aridity=aridity, inflow_cells=inflow_cells,
        min_radius_m=minimum, max_radius_m=maximum,
    )
    record.update({"aridity": round(aridity, 3), "area_coefficient": round(fan_area_coefficient(aridity), 3), "candidate_apexes": len(apexes)})
    if inherited:
        fields = fan_surface_fields(inherited, shape, dx=dx, dy=dy, to_local=to_local, elevation=elevation)
        taken = fields["cover"] > 0.0
        apexes = [apex for apex in apexes if not taken.ravel()[apex["cell"]]]
    if not apexes:
        return residual, record
    height, width = shape
    fans = []
    for apex in apexes:
        row, column = divmod(apex["cell"], width)
        u, v = to_uv(np.asarray([column * dx]), np.asarray([row * dy]))
        if sea_level is not None and elevation[row, column] < float(sea_level) + 1.0:
            continue
        fans.append({
            "apex_u": round(float(u[0]), 10),
            "apex_v": round(float(v[0]), 10),
            "apex_elevation_m": round(apex["surface_at_apex_m"], 2),
            "radius_m": round(apex["radius_m"], 1),
            "gradient": round(apex["gradient"], 5),
            "catchment_km2": round(apex["area_km2"], 2),
            "cell": apex["cell"],
        })
    fields = fan_surface_fields(fans, shape, dx=dx, dy=dy, to_local=to_local, elevation=elevation, build=True)
    deposit = np.where(land, fields["deposit"], 0.0)
    # Each fan's volume comes out of its own catchment, more from steep ground.
    _unused, gradient = d8_receivers(elevation, dx=dx, dy=dy, sinks=~land)
    label = np.full(receivers.size, -1, dtype=np.int64)
    for number, fan in enumerate(fans):
        label[fan["cell"]] = number
    label = _upstream_labels(receivers, label)
    erosion = np.zeros(receivers.size)
    flat_gradient = gradient.ravel()
    kept = []
    for number, fan in enumerate(fans):
        volume = float(deposit[fields["fan"] == number].sum()) * dx * dy
        catchment = (label == number) & land.ravel()
        catchment[fan["cell"]] = False
        weight = flat_gradient * catchment
        if volume <= 0.0 or weight.sum() <= 0.0:
            continue
        lowering = volume * weight / (weight.sum() * dx * dy)
        # Never below the fan's apex: ridges shed debris, they do not vanish.
        headroom = np.maximum(elevation.ravel() - elevation.ravel()[fan["cell"]], 0.0) * MAX_CATCHMENT_LOWERING_SHARE
        erosion += np.minimum(lowering, headroom)
        fan["deposit_volume_km3"] = round(volume / 1.0e9, 5)
        fan["max_thickness_m"] = round(float(deposit[fields["fan"] == number].max()), 1)
        kept.append({key: value for key, value in fan.items() if key != "cell"})
    residual = deposit - erosion.reshape(shape)
    if sea_level is not None:
        # Ground a fan has built or its catchment has lost stays land.  Only
        # that ground: applied to every land cell, the floor stood all land
        # lower than half a metre on a half-metre step along the shore.
        touched = land & (residual != 0.0)
        residual = np.where(touched, np.maximum(elevation + residual, float(sea_level) + 0.5) - elevation, 0.0)
    record["fans"] = kept
    record["fan_cover_fraction"] = round(float((deposit > 0.5)[land].mean()), 4)
    record["max_erosion_m"] = round(float(erosion.max()), 1) if erosion.size else 0.0
    return residual, record


def _running_water(parent_entity):
    """Fans need floods: no liquid water or hydrology, no fans."""
    water_cycle = (parent_entity or {}).get("water_cycle_model")
    if not isinstance(water_cycle, dict) or not water_cycle:
        return True
    return bool(water_cycle.get("liquid_water_possible", True)) and bool(water_cycle.get("hydrology_enabled", True))


def _upstream_labels(receivers, label):
    """Label every cell with the first labelled cell downstream of it."""
    size = receivers.size
    pointer = np.append(np.asarray(receivers, dtype=np.int64), size)
    result = np.append(label.copy(), -1)
    for _step in range(64):
        unresolved = (result[:size] < 0) & (pointer[:size] < size)
        if not unresolved.any():
            break
        target = pointer[:size]
        result[:size] = np.where(unresolved, result[np.minimum(target, size)], result[:size])
        pointer[:size] = np.where(unresolved, pointer[np.minimum(target, size)], pointer[:size])
    return result[:size]


def inherited_fans(parent_entity):
    heightmap = (parent_entity or {}).get("heightmap_model") or {}
    return heightmap_fans(heightmap)


def heightmap_fans(heightmap):
    """Every fan a level knows (its own and inherited)."""
    for landform in (((heightmap or {}).get("regional_landforms") or {}).get("landforms") or []):
        if isinstance(landform, dict) and landform.get("landform") == LANDFORM_ID:
            return list(landform.get("inherited_fans") or []) + list(landform.get("fans") or [])
    return []


def heightmap_fan_fields(heightmap, shape=None):
    """Fan cover and radial position on a heightmap's grid, or ``None``."""
    fans = heightmap_fans(heightmap)
    if not fans:
        return None
    from simulations.world_gen.alluvial_channels import local_frame

    rows = ((heightmap or {}).get("sample_grid") or {}).get("rows") or []
    shape = shape or (len(rows), len(rows[0]) if rows else 0)
    dx, dy, to_local, _to_uv = local_frame(heightmap, shape)
    elevation = np.asarray(rows, dtype=np.float64)
    if elevation.shape != tuple(shape):
        return None
    return fan_surface_fields(fans, shape, dx=dx, dy=dy, to_local=to_local, elevation=elevation)
