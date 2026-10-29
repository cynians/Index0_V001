"""Canyons: the gorges streams cut back into rock scarps.

An escarpment of layered rock is not a closed wall.  Every stream that
crosses it falls over the cap rock, and the fall works its way upstream:
the weak bed under the cap is scoured out, the cap breaks off block by
block, and the stream keeps the level of the bench below the scarp while
the plateau stays above it (Gilbert 1907 on Niagara; Haviv et al. 2010 on
waterfalls with a resistant cap).  What is left is a canyon as deep as the
scarp it started from, ending upstream in a headwall where the stream still
falls in: the side canyons and alcoves of the Colorado Plateau rim (Laity &
Malin 1985), the gorge below every cap-rock fall.

Three relations decide what is drawn, none of them a shape:

* **Which streams.**  A fall retreats where water runs as a channel; below a
  threshold catchment the steps stay hanging (Crosby & Whipple 2006: the
  knickpoints of the Waipaoa basin stall near one drainage area).  The
  threshold is the one every other layer uses for a stream
  (``material_routing.CHANNEL_HEAD_AREA_M2``).
* **How far.**  The fall retreats at a celerity that grows with the
  catchment above it, ``dx/dt = C A^p`` (Rosenbloom & Anderson 1994;
  Berlin & Anderson 2007 for the Roan Plateau: ``p`` 0.54 and about
  ``1.1 A^0.54`` metres in the 8 Myr since the scarp was exposed).  The
  catchment shrinks at every confluence on the way up, so a river cuts a
  canyon tens of kilometres long while its smallest tributary leaves an
  alcove.  Strong cap rock retreats more slowly: the celerity is taken
  inversely proportional to tensile strength, between no dependence and the
  inverse square of the abrasion experiments (Sklar & Dietrich 2001).
* **How deep.**  The stream below the fall runs at the level of the bench
  under the scarp.  The scarps are a change of height around the ground the
  beds were cut into (``rock_scarps``), negative at a scarp's foot and
  positive above its brink; a retreating stream carries the foot's value
  upstream with it.  So a canyon is never deeper than the highest scarp it
  has cut through, its floor continues the bench below, and it shallows out
  by itself where the next bench comes down to that level.

The floor is as wide as its stream at bankfull (the hydraulic geometry of
``alluvial_channels``), at least one cell: a canyon has no floodplain.  The
walls are rock: ``rock_scarps.rockfall`` lays them back to what each bed
holds (a slot in strong rock, a V in weak, a cliff over a slope where a cap
lies on a weak bed), with the floor kept clear by the stream, and at the
finer levels ``rock_scarps.restep`` cuts them into the same cliffs and
slopes as the escarpment the canyon enters through, because a canyon wall
crosses the same beds.

A level cuts the canyons of the bed order its parent built.  At the level
that builds an order its scarps are about a cell wide, and a canyon as deep
as the scarp is high is narrower than that; one level down both are a few
cells across (the scale gate of the worldgen procedure).  From then on a
canyon comes down through the heightfield like any other relief.  The rock a
canyon removes has left with the stream: unlike a scarp it lowers the mean
height of the parent cells it crosses (``mean_lowering_m`` in the record is
the floor's share of that; the walls' share is what rockfall sheds into the
floor afterwards).

Abiotic by contract.  Not modelled: groundwater sapping as a process of its
own, the fan at a canyon's mouth, canyons along rivers that are entrenched
deeper than the scarps they cross (that needs the parent's river profile),
and the part of a canyon whose scarp lies outside the tile downstream.
"""

from __future__ import annotations

import math

import numpy as np

MODEL = "knickpoint_retreat_v1"
LANDFORM_ID = "scarp_canyons"

# Knickpoint retreat, dx/dt = C A^p (A in m^2).  Berlin & Anderson (2007,
# JGR Earth Surface 112, Roan Plateau, Colorado): p = 0.54 and
# C = 1.37e-7 m^(1-2p) per year over about 8 Myr, i.e. 1.1 A^0.54 metres:
# 1.3 km for a 0.5 km^2 catchment, 23 km for 100 km^2.  Entered from memory;
# unverified against the paper.
RETREAT_AREA_EXPONENT = 0.54
RETREAT_COEFFICIENT_M = 1.1
# The cap rock of that calibration is sandstone and marlstone; a sandstone's
# erodibility index stands for it.  The index falls by this much per decade
# of tensile strength (``tools/author_mechanical_lithology.py``), and the
# celerity is taken as inversely proportional to that strength.
REFERENCE_ERODIBILITY = 0.46
ERODIBILITY_INDEX_PER_STRENGTH_DECADE = 0.455
RETREAT_ROCK_FACTOR = (0.2, 5.0)
# A cut shallower than this share of the order's thinnest bed is no canyon
# (the residual of a scarp wavers by that much along a bench).
MIN_CUT_BED_SHARE = 0.05
# Canyons listed one by one in the record (the longest).
RECORD_CANYONS = 16


def rock_retreat_factors(strata):
    """``[beds, beds]``: retreat factor of the strongest bed between bed ``i`` and bed ``j``."""
    beds = strata.get("beds") or []
    erodibility = np.asarray([float(bed[2]) for bed in beds], dtype=np.float64)
    count = erodibility.size
    strongest = np.empty((count, count))
    for low in range(count):
        strongest[low, low:] = np.minimum.accumulate(erodibility[low:])
        strongest[low:, low] = strongest[low, low:]
    factor = 10.0 ** ((strongest - REFERENCE_ERODIBILITY) / ERODIBILITY_INDEX_PER_STRENGTH_DECADE)
    return np.clip(factor, *RETREAT_ROCK_FACTOR)


def retreat_distance_m(area_m2, factor=1.0):
    """How far a fall has retreated up a stream of constant catchment ``area_m2``."""
    return RETREAT_COEFFICIENT_M * factor * np.asarray(area_m2, dtype=np.float64) ** RETREAT_AREA_EXPONENT


def cut_canyons(ground, steps, land, strata, *, u, v, dx, dy, inflow_cells=None, fade=None, sea_level=None, discharge=None):
    """The canyons streams have cut back into the scarps of one bed order.

    ``ground`` is the surface the order's scarps stand on, ``steps`` the
    height they add to it (``rock_scarps.restep`` with ``with_steps``),
    ``strata`` the order's record, ``inflow_cells`` the catchment rivers
    bring into the tile (``material_routing.inflow_grid``), ``fade`` the
    tile-rim weight every child detail carries, ``discharge`` what turns a
    catchment into a bankfull channel width (``runoff_m_s``,
    ``bankfull_ratio``, ``silt_clay_percent``, ``gravity_m_s2``; without it
    every floor is one cell wide).  Returns ``(change, floor, record)``: the
    lowering (``<= 0``), the cells a stream keeps clear (bool) and the
    landform record; ``(None, None, record)`` where no stream crosses a scarp.
    """
    from simulations.world_gen import rock_scarps
    from simulations.world_gen.fluvial_relief import outlet_distance
    from simulations.world_gen.material_routing import (
        CHANNEL_HEAD_AREA_M2, ROUTING_JITTER_SEED, _dominant_channel, box_mean, d8_receivers, filled_routing, inlet_mask,
        routing_jitter, upstream_sum,
    )

    ground = np.asarray(ground, dtype=np.float64)
    steps = np.asarray(steps, dtype=np.float64)
    land = np.asarray(land, dtype=bool)
    shape = ground.shape
    beds = strata.get("beds") or []
    record = {"landform": LANDFORM_ID, "model": MODEL, "order_level": int(strata.get("built_at_level", 0)), "canyon_count": 0}
    if not beds or not land.any() or not np.any(steps):
        return None, None, record
    stepped = ground + steps
    # Routed as ``channel_belts`` routes (the grid's own micro-relief), so a
    # canyon winds like the stream that cut it instead of following the
    # straight runs of steepest descent over a smooth bench.
    _plain, route_gradient = d8_receivers(stepped, dx=dx, dy=dy, sinks=~land)
    jitter = routing_jitter(route_gradient, dx=dx, dy=dy, seed=ROUTING_JITTER_SEED + shape[0] * 4099 + shape[1])
    receivers = filled_routing(stepped, land, dx=dx, dy=dy, jitter=jitter, inlets=inlet_mask(inflow_cells, shape, dx=dx, dy=dy))
    size = receivers.size
    sources = np.ones(size)
    if inflow_cells is not None:
        sources = sources + np.asarray(inflow_cells, dtype=np.float64).ravel()
    area = upstream_sum(receivers, sources)[:, 0] * dx * dy
    stream = land.ravel() & (area >= CHANNEL_HEAD_AREA_M2)
    if not stream.any():
        return None, None, record

    index = np.arange(size)
    target_cell = np.minimum(receivers, size - 1)
    width = shape[1]
    same_row = target_cell // width == index // width
    same_column = target_cell % width == index % width
    hop = np.where(same_row, dx, np.where(same_column, dy, math.hypot(dx, dy)))
    dip = rock_scarps.dip_offset(strata, u, v).ravel()
    tops = np.asarray([float(bed[0]) + float(bed[1]) for bed in beds])
    factors = rock_retreat_factors(strata)
    min_cut = MIN_CUT_BED_SHARE * min(float(bed[1]) for bed in beds)

    before = ground.ravel()
    surface = stepped.ravel()
    # One more entry for the sink every outlet drains to: no bed, nothing carried.
    bed = np.append(surface, -np.inf)
    carried = np.append(steps.ravel(), np.inf)
    spent = np.append(np.zeros(size), 0.0)
    mouth = np.append(np.full(size, -1, dtype=np.int64), -1)
    cells = np.flatnonzero(stream)
    distance = outlet_distance(receivers)
    cells = cells[np.argsort(distance[cells], kind="stable")]
    levels = distance[cells]
    starts = np.flatnonzero(np.r_[True, levels[1:] != levels[:-1]])
    for start, stop in zip(starts, np.r_[starts[1:], cells.size]):
        here = cells[start:stop]
        down = receivers[here]
        # The level the stream brings up from below, never under the bed it flows to.
        level = np.maximum(before[here] + carried[down], bed[down])
        if sea_level is not None:
            level = np.maximum(level, float(sea_level) + 0.5)
        cut = level < surface[here] - min_cut
        low = np.clip(np.searchsorted(tops, np.where(cut, level, surface[here]) - dip[here], side="right"), 0, tops.size - 1)
        high = np.clip(np.searchsorted(tops, surface[here] - dip[here], side="right"), 0, tops.size - 1)
        used = spent[down] + hop[here] / retreat_distance_m(area[here], factors[low, high])
        open_ = cut & (used <= 1.0)
        bed[here] = np.where(open_, level, surface[here])
        carried[here] = bed[here] - before[here]
        # Above its fall a stream stays on the surface until the ground stops rising across it.
        spent[here] = np.where(cut, np.where(open_, used, np.inf), 0.0)
        mouth[here] = np.where(open_, np.where(mouth[down] >= 0, mouth[down], here), -1)
    depth = (surface - bed[:size]).reshape(shape)
    if fade is not None:
        depth = depth * np.asarray(fade, dtype=np.float64)
    in_canyon = (mouth[:size] >= 0).reshape(shape) & (depth > min_cut)
    if not in_canyon.any():
        return None, None, record

    # The floor: as wide as the stream at bankfull, at the stream's level,
    # and nowhere cut deeper than the stream itself (a river with a low step
    # in its bed does not plane off the valley sides beside it).
    floor = in_canyon
    change = np.where(in_canyon, -depth, 0.0)
    half_width = np.zeros(shape)
    if discharge is not None:
        from simulations.world_gen.alluvial_channels import bankfull_geometry

        _plain, gradient = d8_receivers(ground, dx=dx, dy=dy, sinks=~land)
        geometry = bankfull_geometry(
            float(discharge["runoff_m_s"]) * area.reshape(shape) * float(discharge["bankfull_ratio"]),
            np.clip(box_mean(gradient, 2), 1e-5, 0.2), float(discharge["silt_clay_percent"]), float(discharge["gravity_m_s2"]),
        )
        half_width = 0.5 * geometry["width_m"]
        record["widest_floor_m"] = round(float(2.0 * half_width[in_canyon].max()), 1)
    if float(half_width[in_canyon].max()) > min(dx, dy):
        seed, reach, _distance = _dominant_channel(in_canyon, np.where(in_canyon, half_width, 0.0), dx=dx, dy=dy)
        beside = land & ~in_canyon & (seed >= 0) & (reach >= 0.0)
        nearest = np.where(seed >= 0, seed, 0)
        level = (stepped - depth).ravel()[nearest].reshape(shape)
        widened = beside & (level < stepped - min_cut)
        lowering = np.minimum(stepped - level, depth.ravel()[nearest].reshape(shape))
        if fade is not None:
            lowering = lowering * np.asarray(fade, dtype=np.float64)
        change = np.where(widened, -lowering, change)
        floor = in_canyon | widened

    ids = mouth[:size].reshape(shape)[in_canyon]
    mouths, member = np.unique(ids, return_inverse=True)
    lengths = np.bincount(member, weights=hop.reshape(shape)[in_canyon])
    deepest = np.zeros(mouths.size)
    np.maximum.at(deepest, member, depth[in_canyon])
    order = np.argsort(-lengths)
    # One entry per mouth: a canyon with every branch that joins it.
    listed = []
    for item in order[:RECORD_CANYONS]:
        y, x = divmod(int(mouths[item]), width)
        listed.append({
            "mouth_u": round(float(u[y, x]), 10), "mouth_v": round(float(v[y, x]), 10),
            "length_m": round(float(lengths[item]), 1), "depth_m": round(float(deepest[item]), 2),
            "catchment_km2": round(float(area[int(mouths[item])]) / 1.0e6, 3),
        })
    record.update({
        "canyon_count": int(mouths.size),
        "channel_length_m": round(float(lengths.sum()), 1),
        "longest_m": round(float(lengths.max()), 1),
        "max_depth_m": round(float(-change.min()), 2),
        "floor_cells": int(floor.sum()),
        "mean_lowering_m": round(float(-change[land].mean()), 4),
        "stream_threshold_m2": CHANNEL_HEAD_AREA_M2,
        "canyons": listed,
    })
    return change, floor, record
