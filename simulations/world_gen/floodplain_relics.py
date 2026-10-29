"""Relic channels of a floodplain: the bar-and-swale ground a river leaves behind (LOD4+).

A floodplain is not a plane beside a channel.  It is assembled from the
river's former courses: threads a braided river abandoned when it shifted,
chutes that cut across its bars at high flow, single channels left by an
avulsion.  Each survives as a swale that floods and silts up ("heals") until
too little relief is left to tell it from the plain (Martin & Edmonds 2022
take a quarter of the channel depth as that limit), so a floodplain shows
swales of every age between bars: the bar-and-swale topography of braidplains
and young alluvial-fan surfaces (Frankel & Dolan 2007 measure its relief
smoothing out with surface age on arid fans), the "negative relief" of large
floodplains (Lewin & Ashworth 2014).

The forms come in orders.  Braided rivers divide into first-order channels
around their bars, those into second-order channels around smaller bars, and
bar tops are cut by third-order chutes (Williams & Rust 1969; Bristow 1987;
Kelly 2006 finds the hierarchy self-similar over the sizes of rivers).  Each
order here is ``ORDER_WIDTH_RATIO`` narrower than the last, and its depth
follows at-a-station hydraulic geometry: depth ~ Q^0.4 against width ~ Q^0.5
(Leopold & Maddock 1953), so depth ~ width^0.8.

Sizes come from the river that built the plain (``alluvial_channels``:
bankfull width and depth, braided or single thread, and the floodplain
half-width of ``material_routing``'s area law).  Geometry:

* the valley axis is the carved channel's centreline, smoothed over a few
  widths and stored once in global UV; every level and every sibling tile
  measures the same along-valley distance ``s`` and across-valley distance
  ``n`` from it;
* a relic thread of order ``k`` is a line ``n = (j + wander_j(s)) x spacing``;
  neighbours wander into each other, so threads join and part around
  lens-shaped bars; along its length a thread is fresh, healing or gone;
* the swales' volume stands in the bars between them (each order's relief is
  zero-mean at its own spacing).

Scale gate (procedure section 4.3): an order belongs to the first level whose
cells resolve its width (``RESOLVE_WIDTH_CELLS``).  A level adds the orders
its parent could not resolve and sharpens the ones the parent built; an order
the parent could have resolved but did not carry (regions generated before
this landform) is not made up for at a finer level, where it would end at the
tile's edge.  Like the carved channel, the relic field is one geometry read
by terrain, water, soils and materials (``heightmap_relic_fields``).

Abiotic: no plant holds a bank or traps silt here.
"""

from __future__ import annotations

import math

import numpy as np

from simulations.world_gen import alluvial_channels
from simulations.world_gen.array_noise import value_noise
from simulations.world_gen.material_routing import (
    FLOODPLAIN_WIDTH_COEFFICIENT_M,
    FLOODPLAIN_WIDTH_EXPONENT,
    _block_mean,
    _upsample,
    gaussian_blur,
)

LANDFORM_ID = "floodplain_relics"
RELIC_MIN_LEVEL = 4
# A form reads as a shape from about four cells across (procedure section 2).
RESOLVE_WIDTH_CELLS = 4.0
# Each order of channel is this much narrower than the one it divides.
ORDER_WIDTH_RATIO = 5.0
MAX_ORDER = 3
# depth ~ width ** 0.8 down the hierarchy (Leopold & Maddock 1953 exponents).
DEPTH_WIDTH_EXPONENT = 0.8
# Remnant relief of an abandoned channel as a share of its depth when active:
# from nearly fresh down to the quarter below which it counts as healed.
RELIC_RELIEF_SHARE = (0.25, 0.9)
# Share of a thread's length that has healed completely: a third of the
# first-order channels, nearly half of the chutes, which are short.
HEALED_LENGTH_SHARE = (0.3, 0.45)
# A thread keeps one state (fresh, healing, gone) over about this many wander
# lengths.
STATE_LENGTH_WANDERS = 2.0
# A surface the river left long ago has lost most of its relief; one it
# crossed lately keeps it.  Patches of different age are a few belt widths
# across.
OLD_SURFACE_RELIEF_SHARE = 0.35
SURFACE_AGE_PATCH_WIDTHS = 6.0
# First-order relic threads.  Braided: one thread of the active belt's size
# stays visible per belt width.  Single thread: abandoned channels a few
# widths apart, wandering like the river meanders.
BRAIDED_THREAD_WIDTHS = 1.3 / alluvial_channels.BRAID_THREADS
BRAIDED_THREAD_DEPTHS = 2.2
BRAIDED_SPACING_WIDTHS = 1.0
BRAIDED_WANDER_LENGTH_WIDTHS = 4.5
SINGLE_THREAD_DEPTHS = 1.5
SINGLE_SPACING_WIDTHS = 4.0
SINGLE_WANDER_LENGTH_WIDTHS = 0.5 * alluvial_channels.MEANDER_WAVELENGTH_WIDTHS
# Threads wander most of a lane either side over four to five lane spacings,
# so neighbours meet and part around lens-shaped bars a few times longer
# than wide, turning from the valley's direction by about half a radian at
# most.  On top of that the whole lane pattern is bent across the valley (a
# displacement field a few lanes long), which sets chutes oblique to the
# flow as they are on bar tops.
WANDER_AMPLITUDE_SPACINGS = 0.9
HIGHER_ORDER_WANDER_LENGTH_SPACINGS = 4.5
LANE_WARP_LENGTH_SPACINGS = 5.0
LANE_WARP_AMPLITUDE_SPACINGS = (0.5, 1.2)
# Between its channels a floodplain is smooth at the scale of a cell: overbank
# silt drapes it.  This share of a level's own unorganised roughness is taken
# off the plain.
FLOODPLAIN_SMOOTHING = 0.7
# Higher orders: chutes three widths apart.
HIGHER_ORDER_SPACING_WIDTHS = 3.0
# Flat floor, steep margins: an infilled channel, not a V.
SECTION_EXPONENT = 4.0
# The valley axis follows the valley, not the river's bends: smoothed over
# this share of the floodplain's half-width, its radius of curvature stays
# larger than the plain is wide and every cell has one nearest point on it
# (a tighter axis left seams where two stretches were equally near).
AXIS_SMOOTHING_HALF_WIDTHS = 0.75
# A floodplain or fan surface is nearly level: a few per cent on fans, less
# on river plains.  Ground steeper than this over a quarter of the river's
# width (a valley side, a hill standing in the plain) is not the river's
# deposit, however near and low it lies.
LEVEL_GROUND_SLOPE = (0.06, 0.12)
LEVEL_GROUND_SMOOTHING_WIDTHS = 0.25
# First-order relics keep clear of the active channel and its levee ramp.
# Chutes (higher orders) also cut the bars inside the active belt, wherever a
# bar stands this far above the mean-flow stage.
ACTIVE_CHANNEL_CLEARANCE_WIDTHS = 0.25
BAR_CHUTE_CLEARANCE_M = 0.15
# The bars' share of the swales' volume is a mean over a few lane spacings.
# It is taken over ground this many of them beyond the tile as well, so the
# bars do not stand higher or lower for where a tile's edge happens to fall
# and neighbouring tiles agree.
CONSERVATION_MARGIN_SPACINGS = 3.0


def _smooth01(values):
    values = np.clip(values, 0.0, 1.0)
    return values * values * (3.0 - 2.0 * values)


def _record(entity_or_heightmap):
    heightmap = (entity_or_heightmap or {}).get("heightmap_model") or entity_or_heightmap or {}
    for landform in ((heightmap.get("regional_landforms") or {}).get("landforms") or []):
        if isinstance(landform, dict) and landform.get("landform") == LANDFORM_ID:
            return landform
    return None


def _channel_record(entity):
    heightmap = (entity or {}).get("heightmap_model") or {}
    for landform in ((heightmap.get("regional_landforms") or {}).get("landforms") or []):
        if isinstance(landform, dict) and landform.get("landform") == alluvial_channels.LANDFORM_ID:
            return landform
    return {}


def _axis_from_reach(reach, runoff_mm):
    """A reach as a smoothed valley axis in global UV with the sizes relics need."""
    data = np.asarray(reach.get("points") or [], dtype=np.float64)
    if data.ndim != 2 or data.shape[0] < 4 or data.shape[1] < 8:
        return None
    width = float(np.median(data[:, 3]))
    depth = float(np.median(data[:, 4]))
    if width <= 0.0 or depth <= 0.0:
        return None
    arc = data[:, 7]
    spacing = max(1e-6, float(np.median(np.diff(arc)))) if arc.size > 1 else 1.0
    discharge = float(reach.get("mean_discharge_m3_s") or 0.0)
    runoff_m_s = max(1e-12, float(runoff_mm or alluvial_channels.DEFAULT_RUNOFF_MM) / 1000.0 / alluvial_channels.SECONDS_PER_YEAR)
    area_km2 = discharge / runoff_m_s / 1.0e6
    half_width = max(FLOODPLAIN_WIDTH_COEFFICIENT_M * max(area_km2, 1e-6) ** FLOODPLAIN_WIDTH_EXPONENT, 2.0 * width)
    sigma = max(1.0, AXIS_SMOOTHING_HALF_WIDTHS * half_width / spacing)
    # Smoothed in UV: a reach is short enough for the local metric to be constant.
    u = alluvial_channels._gaussian_smooth(data[:, 0], sigma)
    v = alluvial_channels._gaussian_smooth(data[:, 1], sigma)
    bank = np.minimum.accumulate(alluvial_channels._gaussian_smooth(data[:, 2], sigma))
    stride = max(1, int(round(width / spacing)))
    keep = np.unique(np.concatenate([np.arange(0, arc.size, stride), [arc.size - 1]]))
    return {
        "seed": int(reach.get("seed") or 0),
        "width_m": round(width, 3),
        "depth_m": round(depth, 3),
        "braided": bool(float(np.mean(data[:, 5])) >= 0.5),
        "floodplain_half_width_m": round(half_width, 1),
        "point_fields": ["u", "v", "arc_m", "bank_m"],
        "points": [
            [round(float(u[i]), 10), round(float(v[i]), 10), round(float(arc[i]), 2), round(float(bank[i]), 3)]
            for i in keep
        ],
        "orders": {},
    }


def _orders(axis):
    """Width, lane spacing, wander length and active depth of every relic order of an axis."""
    width, depth = float(axis["width_m"]), float(axis["depth_m"])
    if axis.get("braided"):
        first = {
            "width_m": BRAIDED_THREAD_WIDTHS * width, "spacing_m": BRAIDED_SPACING_WIDTHS * width,
            "wander_m": BRAIDED_WANDER_LENGTH_WIDTHS * width, "depth_m": BRAIDED_THREAD_DEPTHS * depth,
        }
    else:
        first = {
            "width_m": width, "spacing_m": SINGLE_SPACING_WIDTHS * width,
            "wander_m": SINGLE_WANDER_LENGTH_WIDTHS * width, "depth_m": SINGLE_THREAD_DEPTHS * depth,
        }
    orders = [first]
    for order in range(1, MAX_ORDER + 1):
        thread = first["width_m"] / ORDER_WIDTH_RATIO ** order
        spacing = HIGHER_ORDER_SPACING_WIDTHS * thread
        orders.append({
            "width_m": thread, "spacing_m": spacing, "wander_m": HIGHER_ORDER_WANDER_LENGTH_SPACINGS * spacing,
            "depth_m": first["depth_m"] * (thread / first["width_m"]) ** DEPTH_WIDTH_EXPONENT,
        })
    return orders


def _axis_curve(px, py):
    """A polyline as a smooth curve: knot parameters (chord length), points and tangents (Catmull-Rom)."""
    q = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(px), np.diff(py)))])
    tangent_x = np.gradient(px, q)
    tangent_y = np.gradient(py, q)
    return q, tangent_x, tangent_y


def _curve_at(q, knots, px, py, tangent_x, tangent_y):
    """Point and first derivative of the Hermite curve at parameters ``q``; straight beyond its ends."""
    inside = np.clip(q, knots[0], knots[-1])
    index = np.clip(np.searchsorted(knots, inside, side="right") - 1, 0, knots.size - 2)
    span = knots[index + 1] - knots[index]
    t = (inside - knots[index]) / span
    t2, t3 = t * t, t * t * t
    h00, h10, h01, h11 = 2 * t3 - 3 * t2 + 1, t3 - 2 * t2 + t, -2 * t3 + 3 * t2, t3 - t2
    d00, d10, d01, d11 = (6 * t2 - 6 * t) / span, 3 * t2 - 4 * t + 1, (-6 * t2 + 6 * t) / span, 3 * t2 - 2 * t
    x = h00 * px[index] + h10 * span * tangent_x[index] + h01 * px[index + 1] + h11 * span * tangent_x[index + 1]
    y = h00 * py[index] + h10 * span * tangent_y[index] + h01 * py[index + 1] + h11 * span * tangent_y[index + 1]
    dx_dq = d00 * px[index] + d10 * tangent_x[index] + d01 * px[index + 1] + d11 * tangent_x[index + 1]
    dy_dq = d00 * py[index] + d10 * tangent_y[index] + d01 * py[index + 1] + d11 * tangent_y[index + 1]
    beyond = q - inside
    return x + dx_dq * beyond, y + dy_dq * beyond, dx_dq, dy_dq


# Newton steps of the projection onto the valley axis.  The axis bends
# little within a floodplain's width, so each step gains a decimal or more.
FRAME_PROJECTION_STEPS = 6


def valley_frame(axes, shape, *, dx, dy, to_local, margin=0):
    """Along- and across-valley coordinates of every cell from the axis whose floodplain reaches it furthest.

    Returns arrays ``s`` and ``n`` (metres; ``n`` signed), ``bank`` (the
    axis's bank level there), ``reach`` (|n| over the floodplain half-width;
    above 1 is outside) and ``axis`` (index, -1 without one).  ``margin``
    adds that many cells of ground beyond the tile on every side.

    Each cell is projected onto the axis as a smooth curve.  Measured from
    the axis's straight segments the coordinates jumped along the bisector at
    every vertex, and each jump cut a straight seam through the threads.
    """
    height, width = shape[0] + 2 * int(margin), shape[1] + 2 * int(margin)
    shape = (height, width)
    x = ((np.arange(width) - int(margin)) * dx)[None, :] * np.ones((height, 1))
    y = ((np.arange(height) - int(margin)) * dy)[:, None] * np.ones((1, width))
    frame = {
        "s": np.zeros(shape), "n": np.zeros(shape), "bank": np.zeros(shape),
        "reach": np.full(shape, np.inf), "axis": np.full(shape, -1, dtype=np.int64),
    }
    for index, axis in enumerate(axes or []):
        points = np.asarray(axis.get("points") or [], dtype=np.float64)
        if points.ndim != 2 or points.shape[0] < 2:
            continue
        px, py = to_local(points[:, 0], points[:, 1])
        arc, bank = points[:, 2], points[:, 3]
        half_width = float(axis["floodplain_half_width_m"])
        knots, tangent_x, tangent_y = _axis_curve(px, py)
        # Start on the chord, then slide along the curve to the foot of the
        # perpendicular.  Beyond the reach's ends the valley runs straight on.
        chord_x, chord_y = px[-1] - px[0], py[-1] - py[0]
        chord2 = max(chord_x * chord_x + chord_y * chord_y, 1e-12)
        q = ((x - px[0]) * chord_x + (y - py[0]) * chord_y) / chord2 * knots[-1]
        for _step in range(FRAME_PROJECTION_STEPS):
            cx, cy, tx, ty = _curve_at(q, knots, px, py, tangent_x, tangent_y)
            q = q + ((x - cx) * tx + (y - cy) * ty) / np.maximum(tx * tx + ty * ty, 1e-12)
        cx, cy, tx, ty = _curve_at(q, knots, px, py, tangent_x, tangent_y)
        n = (tx * (y - cy) - ty * (x - cx)) / np.maximum(np.hypot(tx, ty), 1e-12)
        arc_rate = (arc[-1] - arc[0]) / max(knots[-1], 1e-9)
        bank_rate = (bank[-1] - bank[0]) / max(knots[-1], 1e-9)
        beyond = q - np.clip(q, knots[0], knots[-1])
        s = np.interp(q, knots, arc) + arc_rate * beyond
        level = np.interp(q, knots, bank) + bank_rate * beyond
        reach = np.abs(n) / max(half_width, 1e-6)
        take = reach < frame["reach"]
        frame["s"] = np.where(take, s, frame["s"])
        frame["n"] = np.where(take, n, frame["n"])
        frame["bank"] = np.where(take, level, frame["bank"])
        frame["axis"] = np.where(take, index, frame["axis"])
        frame["reach"] = np.where(take, reach, frame["reach"])
    return frame


def _thread_depth(s, n, order, parameters, seed):
    """Relic threads of one order at along/across-valley positions.

    Returns ``(depth, floor, fill)``: remnant depth in metres; how far into
    a thread's section a point lies (0 on a bar, 1 on a channel floor)
    whatever relief the thread has kept; and the thickness of the fill that
    has taken the rest of its depth.
    """
    spacing = parameters["spacing_m"]
    half = 0.5 * parameters["width_m"]
    warp_length = LANE_WARP_LENGTH_SPACINGS * spacing
    warp = LANE_WARP_AMPLITUDE_SPACINGS[min(order, 1)] * spacing
    n = n + warp * (2.0 * value_noise(s / warp_length, n / warp_length, seed + 5 + order) - 1.0)
    lane = np.floor(n / spacing + 0.5)
    along = s / max(parameters["wander_m"], 1e-6)
    depth = np.zeros(np.shape(s))
    floor = np.zeros(np.shape(s))
    fill = np.zeros(np.shape(s))
    low, high = RELIC_RELIEF_SHARE
    healed = HEALED_LENGTH_SHARE[min(order, 1)]
    for offset in (-2, -1, 0, 1, 2):
        thread = lane + offset
        row = thread * 7.31 + order * 57.3
        wander = 2.0 * value_noise(along, row, seed) - 1.0
        centre = (thread + WANDER_AMPLITUDE_SPACINGS * wander) * spacing
        section = np.clip(1.0 - (np.abs(n - centre) / max(half, 1e-6)) ** SECTION_EXPONENT, 0.0, 1.0)
        # Fresh, healing or healed, changing over a few wander lengths.
        state = value_noise(along / STATE_LENGTH_WANDERS, row + 11.7, seed + 1)
        state = np.clip((state - healed) / (1.0 - healed), 0.0, 1.0)
        present = _smooth01(state / 0.15)
        share = np.where(state > 0.0, low + (high - low) * state, 0.0) * present
        depth = np.maximum(depth, parameters["depth_m"] * share * section)
        floor = np.maximum(floor, present * section)
        fill = np.maximum(fill, parameters["depth_m"] * (1.0 - share) * present * section)
    return depth, floor, fill


def _surface_age(frame, axis, seed):
    """Relief a surface keeps (old .. 1): patches a few belt widths across."""
    patch = max(SURFACE_AGE_PATCH_WIDTHS * float(axis["width_m"]), 1e-6)
    age = value_noise(frame["s"] / patch, frame["n"] / patch, seed + 2)
    return OLD_SURFACE_RELIEF_SHARE + (1.0 - OLD_SURFACE_RELIEF_SHARE) * _smooth01((age - 0.2) / 0.6)


def _floodplain_weight(frame, axis, elevation, spacing):
    """How much of a cell is that axis's floodplain: 1 inside, tapering at its edge and up the valley side."""
    half_width = float(axis["floodplain_half_width_m"])
    rise_limit = 3.0 + 0.02 * half_width
    rise = elevation - frame["bank"]
    cells = min(LEVEL_GROUND_SMOOTHING_WIDTHS * float(axis["width_m"]) / spacing, 0.25 * min(elevation.shape))
    broad = _wide_blur(elevation, max(cells, 1.0))
    slope_y, slope_x = np.gradient(broad, spacing, spacing)
    low, high = LEVEL_GROUND_SLOPE
    level = 1.0 - _smooth01((np.hypot(slope_x, slope_y) - low) / (high - low))
    return _smooth01((1.0 - frame["reach"]) / 0.2) * _smooth01((rise_limit - rise) / (0.3 * rise_limit)) * level


def _relic_layers(axes, frame, elevation, shape, orders_wanted, clearance=None, *, spacing):
    """Per order, the extra depth (m, >= 0) that order adds beyond the wider ones, floodplain weight applied.

    ``orders_wanted(axis_index, order, parameters)`` selects the orders;
    ``clearance(order)`` gives where threads of that order may lie (0..1).
    Returns ``(layers, weight, total, floor, fill)``: ``layers`` maps order
    to ``(extra_depth, conservation_sigma_m)``; ``floor`` is 1 on the floors
    of the selected threads and 0 on the bars between them; ``fill`` is the
    thickness of sediment in them.
    """
    layers = {}
    weight_all = np.zeros(shape)
    total_all = np.zeros(shape)
    floor_all = np.zeros(shape)
    fill_all = np.zeros(shape)
    for index, axis in enumerate(axes):
        mine = frame["axis"] == index
        if not mine.any():
            continue
        weight = np.where(mine, _floodplain_weight(frame, axis, elevation, spacing), 0.0)
        weight_all = np.maximum(weight_all, weight)
        if not np.any(weight > 0.0):
            continue
        seed = int(axis.get("seed") or 0) % (1 << 31)
        fresh = _surface_age(frame, axis, seed)
        so_far = np.zeros(shape)
        for order, parameters in enumerate(_orders(axis)):
            if not orders_wanted(index, order, parameters):
                continue
            depth, floor, fill = _thread_depth(frame["s"], frame["n"], order, parameters, seed)
            clear = 1.0 if clearance is None else clearance(order)
            depth = np.where(weight > 0.0, depth * fresh, 0.0) * clear
            floor_all = np.maximum(floor_all, floor * weight * clear)
            fill_all = np.maximum(fill_all, fill * weight * clear)
            deeper = np.maximum(so_far, depth)
            extra = (deeper - so_far) * weight
            so_far = deeper
            previous, sigma = layers.get(order, (np.zeros(shape), 0.0))
            layers[order] = (previous + extra, max(sigma, parameters["spacing_m"]))
        total_all = np.maximum(total_all, so_far * weight)
    return layers, weight_all, total_all, floor_all, fill_all


def _active_channel_clearance(fields, spacing, order, elevation):
    """Where relic threads of an order may lie around the active channel (``channel_fields`` input).

    First order: 0 in the channel and on its levee ramp, 1 on the plain
    beyond.  Higher orders: 0 under water, 1 on the bars that stand above
    the mean-flow stage and everywhere outside the banks.
    """
    reached = np.isfinite(fields["distance_m"])
    if int(order) == 0:
        clearance = fields["distance_m"] - 0.5 * fields["width_m"]
        clear = _smooth01(clearance / np.maximum(ACTIVE_CHANNEL_CLEARANCE_WIDTHS * fields["width_m"], spacing))
        return np.where(reached, clear, 1.0)
    above = elevation - np.where(np.isfinite(fields["stage_m"]), fields["stage_m"], -np.inf)
    return np.where(fields["in_channel"], _smooth01(above / BAR_CHUTE_CLEARANCE_M), 1.0)


# A mean over many cells is taken on block means: a Gaussian two hundred
# cells wide over a million cells cost most of a minute at full resolution.
WIDE_BLUR_SIGMA_CELLS = 12.0


def _wide_blur(values, sigma_cells):
    """``gaussian_blur`` for any width: wide ones on block means, sampled back bilinearly."""
    sigma_cells = max(float(sigma_cells), 0.5)
    if sigma_cells <= WIDE_BLUR_SIGMA_CELLS:
        return gaussian_blur(values, sigma_cells)
    factor = int(sigma_cells // (0.5 * WIDE_BLUR_SIGMA_CELLS))
    return _upsample(gaussian_blur(_block_mean(values, factor), sigma_cells / factor), factor, values.shape)


def _conserved(extra, sigma_cells):
    """A swale layer with its volume standing in the bars around it (zero-mean at ``sigma``)."""
    return -(extra - _wide_blur(extra, sigma_cells))


def relic_channel_residual(
    elevation, land, *, level, dx, dy, parent_spacing_m, parent_entity, to_local, channel_record=None, sea_level=None,
):
    """Height residual of the relic channels this level resolves, and the landform record.

    Call after ``alluvial_channels`` (``channel_record`` is its record at
    this level): relics keep clear of the active channel.
    """
    elevation = np.asarray(elevation, dtype=np.float64)
    land = np.asarray(land, dtype=bool)
    shape = elevation.shape
    residual = np.zeros(shape)
    inherited = _record(parent_entity)
    record = {"landform": LANDFORM_ID, "level": int(level), "axes": []}
    if int(level) < RELIC_MIN_LEVEL or land.sum() < 64:
        return residual, record
    spacing = max(dx, dy)
    # The parent's own spacing decides what it could have resolved; the
    # detail band's figure is missing where a level adds no band (a child
    # at its parent's spacing), and a missing figure must not read as a
    # parent that resolved nothing.
    parent_heightmap = (parent_entity or {}).get("heightmap_model") or {}
    known_spacing = max(
        float(parent_heightmap.get("sample_spacing_x_m") or 0.0), float(parent_heightmap.get("sample_spacing_y_m") or 0.0))
    if known_spacing > 0.0:
        parent_spacing_m = known_spacing
    if inherited is not None:
        axes = [dict(axis, orders=dict(axis.get("orders") or {})) for axis in inherited.get("axes") or []]
    else:
        # The parent's rivers, the same for every tile refined from it; the
        # level that first carves a river has only its own reaches to go by.
        reaches = alluvial_channels.inherited_reaches(parent_entity)
        runoff_mm = _channel_record(parent_entity).get("runoff_mm")
        if not reaches:
            reaches = list((channel_record or {}).get("reaches") or [])
            runoff_mm = (channel_record or {}).get("runoff_mm")
        axes = [axis for axis in (_axis_from_reach(reach, runoff_mm) for reach in reaches) if axis is not None]
    if not axes:
        return residual, record

    resolved_here = lambda parameters: parameters["width_m"] >= RESOLVE_WIDTH_CELLS * spacing  # noqa: E731
    parent_resolves = lambda parameters: parent_spacing_m > 0.0 and parameters["width_m"] >= RESOLVE_WIDTH_CELLS * parent_spacing_m  # noqa: E731

    def carried(index, order, _parameters):
        return str(order) in axes[index]["orders"]

    def new(index, order, parameters):
        return not carried(index, order, parameters) and resolved_here(parameters) and not parent_resolves(parameters)

    skipped = sorted({
        order for index, axis in enumerate(axes) for order, parameters in enumerate(_orders(axis))
        if not carried(index, order, parameters) and resolved_here(parameters) and parent_resolves(parameters)
    })
    widest = max(
        [parameters["spacing_m"] for index, axis in enumerate(axes) for order, parameters in enumerate(_orders(axis))
         if new(index, order, parameters)] or [0.0]
    )
    reconstruction_cells = alluvial_channels.PARENT_RECONSTRUCTION_SIGMA * parent_spacing_m / spacing
    margin = int(min(max(shape), math.ceil(max(CONSERVATION_MARGIN_SPACINGS * widest / spacing, 3.0 * reconstruction_cells))))
    wide = (shape[0] + 2 * margin, shape[1] + 2 * margin)
    inner = (slice(margin, margin + shape[0]), slice(margin, margin + shape[1]))
    frame = valley_frame(axes, shape, dx=dx, dy=dy, to_local=to_local, margin=margin)
    ground = np.pad(elevation, margin, mode="edge") if margin else elevation

    def to_wide(u, v):
        x, y = to_local(u, v)
        return x + margin * dx, y + margin * dy

    # The active channel has carved its own section; relics lie around it.
    fields = alluvial_channels.channel_fields(
        alluvial_channels.inherited_reaches(parent_entity) + list((channel_record or {}).get("reaches") or []),
        wide, dx=dx, dy=dy, to_local=to_wide,
    )
    clearances = {}

    def clearance(order):
        if order not in clearances:
            clearances[order] = _active_channel_clearance(fields, spacing, order, ground)
        return clearances[order]

    # Orders the parent built are in the inherited surface, smoothed by its
    # sampling: add back what its spacing could not hold.
    if inherited is not None and parent_spacing_m > 1.5 * spacing:
        layers, _weight, _total, _floor, _fill = _relic_layers(axes, frame, ground, wide, carried, clearance, spacing=spacing)
        for extra, _sigma_m in layers.values():
            # The bars' share is smooth at the parent's spacing: the parent
            # held it whole, only the swales' margins were blurred.
            residual = residual - (extra - gaussian_blur(extra, reconstruction_cells))[inner]
    layers, weight, total, _floor, _fill = _relic_layers(axes, frame, ground, wide, new, clearance, spacing=spacing)
    weight, total = weight[inner], total[inner]
    if parent_spacing_m > 1.5 * spacing:
        # What this level added below its parent's spacing and no process
        # organised: most of it goes on the plain (not in the active channel).
        roughness = elevation - gaussian_blur(elevation, 0.5 * parent_spacing_m / spacing)
        residual = residual - FLOODPLAIN_SMOOTHING * weight * roughness * clearance(0)[inner]
    for order, (extra, sigma_m) in layers.items():
        residual = residual + _conserved(extra, sigma_m / spacing)[inner]
        for index, axis in enumerate(axes):
            if new(index, order, _orders(axis)[order]):
                axis["orders"][str(order)] = int(level)
    # Nothing under the channel's water: neither a chute nor the bars' share.
    residual = np.where(land, residual * clearance(1)[inner], 0.0)
    if sea_level is not None:
        # Land stays land: no swale is cut below the shore.
        residual = np.where(land, np.maximum(residual, np.minimum(0.0, float(sea_level) + 0.5 - elevation)), 0.0)
    record.update({
        "axes": axes,
        "floodplain_cell_fraction": round(float((weight > 0.5)[land].mean()), 4),
        "orders_built_here": sorted(layers),
        "orders_left_to_the_parent_level": skipped,
        "new_relic_cell_fraction": round(float((total > 0.02)[land].mean()), 4),
        "max_relief_m": round(float(np.abs(residual).max()), 3),
    })
    return residual, record


def heightmap_relic_fields(heightmap, shape=None, built_at_level=None):
    """Relic-channel fields of a heightmap for its consumers, or ``None`` without relics.

    With ``built_at_level`` only the orders that level built are returned
    (``None`` if it built none), for consumers that inherit the wider
    orders' effect from the parent; ``spacing_m`` is then their widest lane
    spacing.

    ``[H, W]`` arrays: ``depth_m`` of the relic threads this level carries,
    ``floor`` (0 on bars .. 1 on the floor of a relic thread, healed or not:
    where an abandoned channel's fill lies), ``floodplain`` (0..1
    membership), ``fill_m`` (thickness of that fill) and ``fresh`` (relief a
    surface keeps: low on old ground).
    """
    record = _record(heightmap)
    if not record or not record.get("axes"):
        return None
    rows = ((heightmap or {}).get("sample_grid") or {}).get("rows") or []
    grid_shape = shape or (len(rows), len(rows[0]) if rows else 0)
    if grid_shape[0] < 2 or grid_shape[1] < 2:
        return None
    dx, dy, to_local, _to_uv = alluvial_channels.local_frame(heightmap, grid_shape)
    axes = record["axes"]
    frame = valley_frame(axes, grid_shape, dx=dx, dy=dy, to_local=to_local)
    elevation = np.asarray([getattr(row, "values", row) for row in rows], dtype=np.float64)
    if elevation.shape != tuple(grid_shape):
        elevation = frame["bank"]
    channels = alluvial_channels.heightmap_channel_fields(heightmap, grid_shape)
    # The active channel has carved its own section through them.
    clearance = None if channels is None else (
        lambda order: _active_channel_clearance(channels, max(dx, dy), order, elevation))

    def wanted(index, order, _parameters):
        built = (axes[index].get("orders") or {}).get(str(order))
        return built is not None and (built_at_level is None or int(built) == int(built_at_level))

    widest = max(
        [parameters["spacing_m"] for index, axis in enumerate(axes) for order, parameters in enumerate(_orders(axis))
         if wanted(index, order, parameters)] or [0.0]
    )
    if built_at_level is not None and widest <= 0.0:
        return None
    _layers, weight, total, floor, fill = _relic_layers(
        axes, frame, elevation, grid_shape, wanted, clearance, spacing=max(dx, dy),
    )
    fresh = np.ones(grid_shape)
    for index, axis in enumerate(axes):
        fresh = np.where(frame["axis"] == index, _surface_age(frame, axis, int(axis.get("seed") or 0) % (1 << 31)), fresh)
    return {"depth_m": total, "floor": floor, "fill_m": fill, "floodplain": weight, "fresh": fresh, "spacing_m": widest}
