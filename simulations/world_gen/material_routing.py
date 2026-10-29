"""Surface routing fields for the material LOD cover model.

Steepest-descent (D8) receivers over a map level's own heightfield tell the
cover model where material comes from:

* provenance: alluvium carries the upstream substrate mix, weighted by the
  sediment each source cell supplies (``provenance_composition``);
* stream power, ``sqrt(upstream area) x slope``, sorts channel beds at LOD4+
  (``stream_power_index``);
* catena: topographic position and wetness move weathered mantle off crests
  and collect fines in wet hollows at LOD3+ (``catena_fields``);
* talus: rockfall carries cliff rock a few cells downslope (``talus_fields``).

Fault offsets for mapped units (``fault_offsets``) live here as well; they
displace the unit lattice rather than routing material.

Everything is NumPy.  Upstream sums use pointer doubling (``upstream_sum``),
so no Python loop runs per cell.  See docs/worldgen_material_lod_plan_v001.md.
"""

from __future__ import annotations

import math

import numpy as np

from simulations.world_gen.array_noise import hash_unit

# Eight-neighbour offsets as (row, column).
_D8_OFFSETS = ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1))
# Cells above this steepest-descent gradient are rock faces (about 40 deg).
CLIFF_GRADIENT = 0.84
# Rockfall debris comes to rest below the angle of repose (about 35 deg).
REPOSE_GRADIENT = 0.70
# Provenance is routed on a grid of at most this many cells.
PROVENANCE_MAX_CELLS = 70_000


def _smooth01(values):
    values = np.clip(values, 0.0, 1.0)
    return values * values * (3.0 - 2.0 * values)


def grid_spacing_m(heightmap, shape, bounds, circumference_m):
    """Cell spacing ``(dx, dy)`` in metres for a map level's grid."""
    height, width = shape
    width_m = float((heightmap or {}).get("region_width_m") or 0.0)
    height_m = float((heightmap or {}).get("region_height_m") or 0.0)
    if width_m <= 0.0 or height_m <= 0.0:
        center_v = 0.5 * (bounds["min_v"] + bounds["max_v"])
        width_m = (bounds["max_u"] - bounds["min_u"]) * circumference_m * max(0.05, math.cos((0.5 - center_v) * math.pi))
        height_m = (bounds["max_v"] - bounds["min_v"]) * circumference_m * 0.5
    return max(1e-3, width_m / max(1, width - 1)), max(1e-3, height_m / max(1, height - 1))


def d8_receivers(elevation, *, dx, dy, wrap_x=False, sinks=None):
    """Steepest-descent receiver per cell and the gradient towards it.

    Returns ``(receivers, gradient)``: ``receivers`` holds flat indices, with
    ``elevation.size`` marking a sink (pit, flat, or a cell in ``sinks``).
    """
    elevation = np.asarray(elevation, dtype=np.float64)
    height, width = elevation.shape
    size = height * width
    rows = np.arange(height)[:, None]
    columns = np.arange(width)[None, :]
    gradient = np.zeros(elevation.shape)
    receivers = np.full(elevation.shape, size, dtype=np.int64)
    for row_offset, column_offset in _D8_OFFSETS:
        neighbour_rows = rows + row_offset
        neighbour_columns = columns + column_offset
        valid = (neighbour_rows >= 0) & (neighbour_rows < height)
        if wrap_x:
            neighbour_columns = neighbour_columns % width
        else:
            valid = valid & (neighbour_columns >= 0) & (neighbour_columns < width)
        neighbour_rows = np.clip(neighbour_rows, 0, height - 1)
        neighbour_columns = np.clip(neighbour_columns, 0, width - 1)
        drop = elevation - elevation[neighbour_rows, neighbour_columns]
        slope = drop / math.hypot(column_offset * dx, row_offset * dy)
        better = valid & (slope > gradient)
        gradient = np.where(better, slope, gradient)
        receivers = np.where(better, neighbour_rows * width + neighbour_columns, receivers)
    if sinks is not None:
        receivers = np.where(np.asarray(sinks, dtype=bool), size, receivers)
    return receivers.ravel(), gradient


# Seed of the default routing micro-relief (``channel_belts``).
ROUTING_JITTER_SEED = 20261001


def routing_jitter(gradient, *, dx, dy, seed):
    """Sub-cell micro-relief for routing only (``[H, W]`` metres).

    Deterministic steepest descent draws straight parallel flow lines across
    a smooth slope; real ground has relief below the cell that makes them
    wander and join.  Correlated noise worth about half a cell's drop along
    the local slope does that without touching the terrain (the same idea as
    ``fluvial_relief.stochastic_receivers``).
    """
    gradient = np.asarray(gradient, dtype=np.float64)
    rng = np.random.default_rng(int(seed) % (2 ** 32))
    noise = box_mean(rng.standard_normal(gradient.shape), 2) * 5.0
    return noise * 0.5 * box_mean(gradient, 2) * math.sqrt(dx * dy)


def upstream_sum(receivers, values):
    """Sum ``values`` (``[cells, K]``) over each cell and everything upstream.

    Pointer doubling: step ``k`` adds the totals that sit ``2**k`` receivers
    upstream, so the product of ``(I + A^(2^k)^T)`` covers every path length
    below ``2**steps``.  Sinks point at a dummy cell whose total is dropped.
    """
    values = np.asarray(values, dtype=np.float64)
    if values.ndim == 1:
        values = values[:, None]
    size = receivers.size
    pointer = np.append(np.asarray(receivers, dtype=np.int64), size)
    totals = np.vstack([values, np.zeros((1, values.shape[1]))])
    for _step in range(64):
        if np.all(pointer[:size] == size):
            break
        order = np.argsort(pointer, kind="stable")
        targets = pointer[order]
        starts = np.flatnonzero(np.r_[True, targets[1:] != targets[:-1]])
        pushed = np.zeros_like(totals)
        pushed[targets[starts]] = np.add.reduceat(totals[order], starts, axis=0)
        pushed[size] = 0.0
        totals += pushed
        pointer = pointer[pointer]
    return totals[:size]


def _block_mean(values, factor):
    """Mean over ``factor x factor`` blocks of the last two axes (edge padded)."""
    height, width = values.shape[-2:]
    pad_y = (-height) % factor
    pad_x = (-width) % factor
    padding = [(0, 0)] * (values.ndim - 2) + [(0, pad_y), (0, pad_x)]
    padded = np.pad(values, padding, mode="edge")
    new_shape = padded.shape[:-2] + (padded.shape[-2] // factor, factor, padded.shape[-1] // factor, factor)
    return padded.reshape(new_shape).mean(axis=(-3, -1))


def _upsample(values, factor, shape):
    """Bilinear upsample of block means back to ``shape`` (block centres)."""
    height, width = shape
    coarse_height, coarse_width = values.shape[-2:]
    fy = np.clip((np.arange(height) + 0.5) / factor - 0.5, 0.0, coarse_height - 1)
    fx = np.clip((np.arange(width) + 0.5) / factor - 0.5, 0.0, coarse_width - 1)
    y0 = np.floor(fy).astype(np.int64)
    x0 = np.floor(fx).astype(np.int64)
    y1 = np.minimum(y0 + 1, coarse_height - 1)
    x1 = np.minimum(x0 + 1, coarse_width - 1)
    ty = (fy - y0)[:, None]
    tx = (fx - x0)[None, :]
    top = values[..., y0, :][..., x0] * (1.0 - tx) + values[..., y0, :][..., x1] * tx
    bottom = values[..., y1, :][..., x0] * (1.0 - tx) + values[..., y1, :][..., x1] * tx
    return top * (1.0 - ty) + bottom * ty


def sediment_supply(gradient, land):
    """Relative sediment yield: steeper land sheds more; the ocean sheds none."""
    return np.where(land, 0.1 + np.clip(gradient / 0.25, 0.0, 1.0), 0.0)


def provenance_composition(elevation, land, composition, *, dx, dy, wrap_x=False, max_cells=PROVENANCE_MAX_CELLS, jitter=None):
    """Upstream substrate mix delivered to every cell by the drainage.

    ``composition`` is ``[materials, H, W]``.  Each cell supplies sediment in
    proportion to ``sediment_supply`` with its own composition; the result is
    the supply-weighted mean over the cell's whole catchment.  Large grids are
    routed on block means (catchment mixtures are smooth along a river), then
    interpolated back.  Cells without upstream supply keep their own mix.
    ``jitter`` (``routing_jitter``) is added to the surface for routing only.
    """
    composition = np.asarray(composition, dtype=np.float64)
    shape = composition.shape[1:]
    factor = max(1, int(math.ceil(math.sqrt(shape[0] * shape[1] / float(max_cells)))))
    if jitter is not None:
        elevation = np.asarray(elevation, dtype=np.float64) + jitter
    if factor > 1:
        coarse_elevation = _block_mean(np.asarray(elevation, dtype=np.float64), factor)
        coarse_land = _block_mean(np.asarray(land, dtype=np.float64), factor) >= 0.5
        coarse_composition = _block_mean(composition, factor)
    else:
        coarse_elevation, coarse_land, coarse_composition = np.asarray(elevation, dtype=np.float64), np.asarray(land, dtype=bool), composition
    receivers, gradient = d8_receivers(
        coarse_elevation, dx=dx * factor, dy=dy * factor, wrap_x=wrap_x, sinks=~coarse_land,
    )
    supply = sediment_supply(gradient, coarse_land).ravel()
    material_count = composition.shape[0]
    flux = coarse_composition.reshape(material_count, -1).T * supply[:, None]
    totals = upstream_sum(receivers, flux).T.reshape((material_count,) + coarse_elevation.shape)
    weight = totals.sum(axis=0)
    routed = np.where(weight[None] > 1e-9, totals / np.maximum(weight, 1e-12)[None], coarse_composition)
    if factor > 1:
        routed = _upsample(routed, factor, shape)
    routed = np.clip(routed, 0.0, None)
    return (routed / np.maximum(routed.sum(axis=0), 1e-9)[None]).astype(np.float32)


# Channels start at this contributing area; floodplain half-width follows
# an area power law (about 11 m at 0.5 km^2, 120 m at 100 km^2, 330 m at
# 1,000 km^2), a proxy for discharge-driven channel-belt width.
CHANNEL_HEAD_AREA_M2 = 5.0e5
# A river entering a tile may not leave it again within this fraction of the
# side from its entry: the child edge band (fade zone, regional_refinement's
# PARENT_EDGE_FADE_FRACTION 0.018) plus about one parent cell.
INLET_EDGE_BAND_FRACTION = 0.04
# Inflow (in the grid's units) that marks an edge cell the parent's flow
# does not leave through (outside ``boundary_inflow``'s ``open_edges``).
CLOSED_EDGE_INFLOW = 1.0e-6
FLOODPLAIN_WIDTH_COEFFICIENT_M = 15.0
FLOODPLAIN_WIDTH_EXPONENT = 0.45


def inflow_grid(shape, boundary_inflow, cell_area_m2):
    """Extra upstream area per cell (in cells) from a heightmap's ``boundary_inflow``."""
    extra = np.zeros(shape)
    cells = (boundary_inflow or {}).get("cells") if isinstance(boundary_inflow, dict) else None
    for x, y, area_m2 in cells or []:
        if 0 <= int(y) < shape[0] and 0 <= int(x) < shape[1]:
            extra[int(y), int(x)] += float(area_m2) / max(float(cell_area_m2), 1e-9)
    # Outside the stretches the parent's flow leaves through, edge cells
    # carry a vanishing inflow, which is how ``inlet_mask`` recognises that
    # they are no outlets.
    open_edges = (boundary_inflow or {}).get("open_edges") if isinstance(boundary_inflow, dict) else None
    if isinstance(open_edges, dict):
        closed = np.zeros(shape, dtype=bool)
        closed[0, :] = closed[-1, :] = closed[:, 0] = closed[:, -1] = True
        for side, edge_runs in open_edges.items():
            for start, stop in edge_runs or []:
                if side in ("west", "east"):
                    closed[max(0, int(start)):int(stop) + 1, 0 if side == "west" else shape[1] - 1] = False
                else:
                    closed[0 if side == "north" else shape[0] - 1, max(0, int(start)):int(stop) + 1] = False
        extra = np.where(closed, np.maximum(extra, CLOSED_EDGE_INFLOW), extra)
    return extra


def inlet_mask(inflow_cells, shape, *, dx=1.0, dy=1.0, min_span=1):
    """Boundary cells of the valley floors through which rivers enter.

    ``inflow_cells`` is ``inflow_grid`` output (extra catchment in cells).
    An entry carrying at least a channel head's catchment is a river; its
    valley floor spans the floodplain half-width of that catchment (the
    ``channel_belts`` law) along the side it enters through, capped at a
    quarter of that side, and those boundary cells are inlets, not outlets
    (smaller entries are sheet flow).  Seeded as outlets, an entry whose floor
    sits a metre below the ground just inside (the parent's own bed undulates
    by a few metres) drained its whole catchment straight back out.  The
    stretch is never shorter than the tile's edge band
    (``INLET_EDGE_BAND_FRACTION`` of the side either way: the band where a
    child keeps its parent's surface, plus about a parent cell), since the
    child cannot overrule there the parent's flow into the tile.  Every
    other edge cell with any inflow is closed as well; ``inflow_grid`` marks
    all cells outside ``boundary_inflow``'s ``open_edges`` that way, so
    water leaves the tile only where the parent's drainage leaves it.
    ``None`` when nothing flows in.
    """
    if inflow_cells is None:
        return None
    inflow = np.asarray(inflow_cells, dtype=np.float64)
    if inflow.shape != tuple(shape) or not np.any(inflow > 0.0):
        return None
    rivers = inflow * dx * dy >= CHANNEL_HEAD_AREA_M2
    height, width = shape
    # Wherever the parent's flow comes in, the edge is no outlet: the child
    # cannot send water out against its parent's drainage.
    mask = np.zeros(shape, dtype=bool)
    for edge in ((0, slice(None)), (height - 1, slice(None)), (slice(None), 0), (slice(None), width - 1)):
        mask[edge] = inflow[edge] > 0.0
    spacing = max(min(dx, dy), 1e-6)
    for y, x in zip(*np.nonzero(rivers)):
        half_width = FLOODPLAIN_WIDTH_COEFFICIENT_M * (inflow[y, x] * dx * dy / 1.0e6) ** FLOODPLAIN_WIDTH_EXPONENT
        span = int(max(min_span, math.ceil(half_width / spacing)))
        # Only along the side the river enters through, and never more than
        # a quarter of it: a big river's floodplain can be wider than a small
        # tile, and a boundary without outlets drained everything into the
        # tile's lowest interior cell.
        if x == 0 or x == width - 1:
            band = max(min_span, int(math.ceil(INLET_EDGE_BAND_FRACTION * height)))
            span = max(band, min(span, max(min_span, height // 8)))
            mask[max(0, y - span):y + span + 1, x] = True
        else:
            band = max(min_span, int(math.ceil(INLET_EDGE_BAND_FRACTION * width)))
            span = max(band, min(span, max(min_span, width // 8)))
            mask[y, max(0, x - span):x + span + 1] = True
    return mask


def filled_routing(elevation, land, *, dx, dy, wrap_x=False, jitter=None, inlets=None):
    """D8 receivers over the depression-filled surface (every cell drains out).

    ``inlets`` (``inlet_mask``) are boundary cells that are not outlets.
    """
    from simulations.world_gen.drainage import _priority_flood

    surface = np.asarray(elevation, dtype=np.float64)
    if jitter is not None:
        surface = surface + jitter
    outlets = ~np.asarray(land, dtype=bool)
    filled, _parent, _order = _priority_flood(
        surface.tolist(), outlets.tolist(), bool(wrap_x),
        inlets=None if inlets is None or wrap_x else np.asarray(inlets, dtype=bool),
    )
    receivers, _gradient = d8_receivers(np.asarray(filled, dtype=np.float64), dx=dx, dy=dy, wrap_x=wrap_x, sinks=outlets)
    return receivers


def boundary_inflow(
    parent_elevation,
    parent_land,
    parent_bounds,
    parent_cell_area_m2,
    child_elevation,
    child_bounds,
    *,
    parent_wrap_x=False,
    parent_inflow=None,
    parent_dx=1.0,
    parent_dy=1.0,
    parent_fields=None,
    parent_inflow_fields=None,
    receivers=None,
):
    """Catchment area that rivers carry into a child tile from outside.

    ``receivers`` (flat indices on the parent grid, ``size`` for a sink) is
    the parent's routing when the caller has it; otherwise the parent
    surface is routed here.

    ``parent_fields`` (``{name: [H, W] mm}``, the parent's annual climate on
    its grid) are gathered along the same routes, with
    ``parent_inflow_fields`` (``{name: [H, W] m2 mm}``, what the parent's own
    inflow brought, from its record) added where that enters: each crossing
    then carries its catchment's mean (``catchment_means_mm``, in the order
    of ``cells``), so a through-river keeps the water its own catchment
    makes at every level instead of the receiving tile's average.

    A child routes only its own footprint, so a river entering from upstream
    looked like a headwater stream.  The parent heightfield is routed over its
    depression-filled surface (with its own ``parent_inflow`` injected, so
    the chain continues down the levels); wherever parent flow crosses from
    outside into the child footprint, the parent's upstream area at that
    crossing enters the child at the lowest boundary cell within the crossing
    parent cell's span, i.e. the valley the river comes in through.

    ``parent_cell_area_m2`` is a scalar or an array (spherical planets).
    Returns ``{"cells": [[x, y, area_m2], ...], "model": ...}``.
    """
    parent_elevation = np.asarray(parent_elevation, dtype=np.float64)
    child_elevation = np.asarray(child_elevation, dtype=np.float64)
    parent_height, parent_width = parent_elevation.shape
    child_height, child_width = child_elevation.shape
    if receivers is None:
        receivers = filled_routing(
            parent_elevation, parent_land, dx=parent_dx, dy=parent_dy, wrap_x=parent_wrap_x,
            # ``parent_inflow`` is in square metres; the mask wants cells.
            inlets=None if parent_inflow is None else inlet_mask(
                np.asarray(parent_inflow, dtype=np.float64) / (parent_dx * parent_dy), parent_elevation.shape, dx=parent_dx, dy=parent_dy,
            ),
        )
    receivers = np.asarray(receivers, dtype=np.int64).ravel()
    cell_area = np.broadcast_to(np.asarray(parent_cell_area_m2, dtype=np.float64), parent_elevation.shape).ravel()
    weights = cell_area.copy()
    if parent_inflow is not None:
        weights = weights + np.asarray(parent_inflow, dtype=np.float64).ravel()
    field_names = sorted(name for name, values in (parent_fields or {}).items() if values is not None)
    columns = [weights]
    for name in field_names:
        local = np.nan_to_num(np.asarray(parent_fields[name], dtype=np.float64).ravel())
        brought = (parent_inflow_fields or {}).get(name)
        if brought is not None:
            gathered = cell_area * local + np.asarray(brought, dtype=np.float64).ravel()
        else:
            # Without a record of its own catchment, the parent's inflow is
            # taken at the climate of the cell it enters by.
            gathered = weights * local
        columns.append(gathered)
    totals = upstream_sum(receivers, np.stack(columns, axis=1))
    area = totals[:, 0]
    pu0, pu1 = parent_bounds["min_u"], parent_bounds["max_u"]
    pv0, pv1 = parent_bounds["min_v"], parent_bounds["max_v"]
    cu0, cu1 = child_bounds["min_u"], child_bounds["max_u"]
    cv0, cv1 = child_bounds["min_v"], child_bounds["max_v"]
    columns = np.arange(parent_width)
    rows = np.arange(parent_height)
    parent_u = pu0 + (pu1 - pu0) * columns / max(1, parent_width - 1)
    parent_v = pv0 + (pv1 - pv0) * rows / max(1, parent_height - 1)

    centre_u = 0.5 * (cu0 + cu1)

    def local(u, v):
        if parent_wrap_x:
            # Longitudes relative to the tile centre, so west stays west.
            u = centre_u + np.mod(u - centre_u + 0.5, 1.0) - 0.5
        return (u - cu0) / max(1e-12, cu1 - cu0), (v - cv0) / max(1e-12, cv1 - cv0)

    flat_u = np.broadcast_to(parent_u[None, :], parent_elevation.shape).ravel()
    flat_v = np.broadcast_to(parent_v[:, None], parent_elevation.shape).ravel()
    lu, lv = local(flat_u, flat_v)
    inside = (lu >= 0.0) & (lu <= 1.0) & (lv >= 0.0) & (lv <= 1.0)
    valid = receivers < receivers.size
    target = np.where(valid, receivers, 0)
    crossing = valid & ~inside & inside[target]
    span_x = max(1, int(round((pu1 - pu0) / max(1, parent_width - 1) / max(1e-12, cu1 - cu0) * (child_width - 1) * 0.5)))
    span_y = max(1, int(round((pv1 - pv0) / max(1, parent_height - 1) / max(1e-12, cv1 - cv0) * (child_height - 1) * 0.5)))
    entries = {}
    entry_fields = {}
    # Edge cells the parent's flow leaves through (per side, along-edge index).
    outward = {side: np.zeros(child_height if side in ("west", "east") else child_width, dtype=bool)
               for side in ("west", "east", "north", "south")}

    def edge_span(outer_u, outer_v, inner_u, inner_v):
        """Side and child-edge span of a crossing between an outer and an inner parent cell."""
        if outer_u < 0.0 or outer_u > 1.0:
            side = "west" if outer_u < 0.0 else "east"
            centre = int(round(np.clip(inner_v, 0.0, 1.0) * (child_height - 1)))
            return side, range(max(0, centre - span_y), min(child_height, centre + span_y + 1))
        side = "north" if outer_v < 0.0 else "south"
        centre = int(round(np.clip(inner_u, 0.0, 1.0) * (child_width - 1)))
        return side, range(max(0, centre - span_x), min(child_width, centre + span_x + 1))

    for source in np.flatnonzero(crossing):
        # Enter through the side the flow comes from.
        side, span = edge_span(lu[source], lv[source], lu[target[source]], lv[target[source]])
        if side in ("west", "east"):
            x = 0 if side == "west" else child_width - 1
            candidates = [(child_elevation[y, x], x, y) for y in span]
        else:
            y = 0 if side == "north" else child_height - 1
            candidates = [(child_elevation[y, x], x, y) for x in span]
        _elevation, x, y = min(candidates)
        entries[(x, y)] = entries.get((x, y), 0.0) + float(area[source])
        if field_names:
            entry_fields[(x, y)] = entry_fields.get((x, y), 0.0) + totals[source, 1:]
    for source in np.flatnonzero(valid & inside & ~inside[target]):
        side, span = edge_span(lu[target[source]], lv[target[source]], lu[source], lv[source])
        outward[side][span.start:span.stop] = True

    def runs(values):
        edges = np.flatnonzero(np.diff(np.concatenate([[0], values.astype(np.int8), [0]])))
        return [[int(start), int(stop) - 1] for start, stop in zip(edges[::2], edges[1::2])]

    record = {
        "model": "parent_d8_crossings_v2",
        "cells": [[x, y, round(value, 1)] for (x, y), value in sorted(entries.items())],
        "total_area_m2": round(sum(entries.values()), 1),
        # Edge stretches (inclusive index runs along each side) through
        # which the parent's flow leaves the footprint: the child's only
        # outlets besides the sea.
        "open_edges": {side: runs(outward[side]) for side in outward},
    }
    if field_names:
        record["catchment_means_mm"] = {
            name: [
                round(float(entry_fields[key][index]) / max(float(entries[key]), 1e-9), 3)
                for key in sorted(entries)
            ]
            for index, name in enumerate(field_names)
        }
    return record


def _dominant_channel(channel, half_width, *, dx, dy, wrap_x=False):
    """Per cell, the channel whose floodplain reaches it furthest.

    Jump flooding over the channel cells, keeping the seed with the largest
    ``half_width - distance`` (an additively weighted Voronoi diagram).  A
    nearest-channel assignment cut a wide river's floodplain into islands
    around every small tributary.  Returns ``(seed, reach_m, distance_m)``:
    flat seed index per cell (-1 without channels), the winner's half-width
    minus distance, and the distance to it.
    """
    height, width = channel.shape
    seed = np.where(channel.ravel(), np.arange(channel.size), -1).reshape(channel.shape)
    rows = np.arange(height)[:, None]
    columns = np.arange(width)[None, :]
    seed_rows, seed_columns = np.divmod(np.arange(channel.size), width)
    flat_half_width = half_width.ravel()

    def score(candidate):
        valid = candidate >= 0
        safe = np.where(valid, candidate, 0)
        column_delta = columns - seed_columns[safe]
        if wrap_x:
            column_delta = (column_delta + width // 2) % width - width // 2
        distance = np.hypot(column_delta * dx, (rows - seed_rows[safe]) * dy)
        return np.where(valid, flat_half_width[safe] - distance, -np.inf), distance

    def shifted(values, row_shift, column_shift):
        if abs(row_shift) >= height or (not wrap_x and abs(column_shift) >= width):
            return np.full(values.shape, -1, dtype=values.dtype)
        if wrap_x:
            out = np.roll(values, column_shift, axis=1)
        else:
            out = np.full(values.shape, -1, dtype=values.dtype)
            cs = slice(max(0, column_shift), width + min(0, column_shift))
            cd = slice(max(0, -column_shift), width + min(0, -column_shift))
            out[:, cs] = values[:, cd]
        result = np.full(values.shape, -1, dtype=values.dtype)
        rs = slice(max(0, row_shift), height + min(0, row_shift))
        rd = slice(max(0, -row_shift), height + min(0, -row_shift))
        result[rs, :] = out[rd, :]
        return result

    best, distance = score(seed)
    if not channel.any():
        return seed, best, np.full(channel.shape, np.inf)
    reach_cells = min(max(height, width), float(flat_half_width[channel.ravel()].max()) / max(min(dx, dy), 1e-9) + 2.0)
    steps = []
    step = 1 << int(math.ceil(math.log2(max(1.0, reach_cells))))
    while step >= 1:
        steps.append(step)
        step //= 2
    for step in steps + [1]:
        for row_shift in (-step, 0, step):
            for column_shift in (-step, 0, step):
                if row_shift == 0 and column_shift == 0:
                    continue
                candidate = shifted(seed, row_shift, column_shift)
                candidate_score, candidate_distance = score(candidate)
                better = candidate_score > best
                if better.any():
                    seed = np.where(better, candidate, seed)
                    best = np.where(better, candidate_score, best)
                    distance = np.where(better, candidate_distance, distance)
    return seed, best, distance


def _non_increasing_fit(values):
    """Least-squares non-increasing fit (pool adjacent violators).

    Each pooled block takes its mean, so the fit keeps the sum of the values:
    sills are cut by as much as the pits beside them are filled.
    """
    sums, counts = [], []
    for value in values:
        sums.append(float(value))
        counts.append(1)
        while len(sums) > 1 and sums[-2] / counts[-2] < sums[-1] / counts[-1]:
            total, count = sums.pop(), counts.pop()
            sums[-1] += total
            counts[-1] += count
    return np.repeat([total / count for total, count in zip(sums, counts)], counts)


# Along-river smoothing (cells) of a fitted bed profile.
BED_GRADE_CELLS = 6.0


def _smooth_along(values, sigma):
    """Gaussian smoothing of a path's values (ends held by edge padding)."""
    if values.size < 3 or sigma <= 0.0:
        return values.copy()
    radius = int(math.ceil(3.0 * sigma))
    kernel = np.exp(-0.5 * (np.arange(-radius, radius + 1) / sigma) ** 2)
    kernel /= kernel.sum()
    return np.convolve(np.pad(values, radius, mode="edge"), kernel, mode="valid")


def monotone_channel_beds(elevation, channel, receivers, area, smooth_cells=0.0):
    """Channel beds that never rise downstream (``[H, W]``; other cells unchanged).

    A river bed descends along its course; inherited relief and noise leave
    closed pits and sills along a routed channel, which a finer level reads
    as a river that ponds or turns back.  Paths are fitted trunk first
    (largest contributing area at their head, so rivers entering the tile
    lead, then the longest): each channel path from its head to the first
    already-fitted cell gets the least-squares non-increasing profile
    (``_non_increasing_fit``), kept no lower than the profile it joins.  A
    path entering through the grid edge keeps its entry level (the fit only
    cuts below it: the edge is the parent's, and a raised entry would come
    back as a sill), and one leaving through the edge keeps its exit level.
    With ``smooth_cells`` the profile is fitted to the bed smoothed along
    the path and each cell moves by fit minus smoothed bed: a correction
    that is smooth along the river, for carrying across its floodplain.
    """
    shape = elevation.shape
    size = elevation.size
    height, width = shape
    flat_channel = np.asarray(channel, dtype=bool).ravel()
    bed = np.asarray(elevation, dtype=np.float64).ravel().copy()
    level = bed.copy()

    def on_edge(cell):
        row, column = divmod(int(cell), width)
        return row == 0 or column == 0 or row == height - 1 or column == width - 1

    receivers = np.asarray(receivers).ravel()
    target = np.where(receivers < size, receivers, np.arange(size))
    donor = np.zeros(size, dtype=bool)
    flows_on = flat_channel & (target != np.arange(size))
    donor[target[flows_on & flat_channel[target]]] = True
    heads = np.flatnonzero(flat_channel & ~donor)
    if heads.size == 0:
        return bed.reshape(shape)
    from simulations.world_gen.fluvial_relief import outlet_distance

    length = outlet_distance(receivers)
    order = np.lexsort((-length[heads], -np.asarray(area, dtype=np.float64).ravel()[heads]))
    done = np.zeros(size, dtype=bool)
    for head in heads[order]:
        path = [int(head)]
        junction = None
        while True:
            nxt = int(target[path[-1]])
            if nxt == path[-1] or not flat_channel[nxt]:
                break
            if done[nxt]:
                junction = level[nxt]
                break
            path.append(nxt)
        cells = np.asarray(path)
        smooth = _smooth_along(bed[cells], smooth_cells)
        # The least-squares fit is a staircase (pooled flats and drops);
        # graded along the path it stays non-increasing and reads as a
        # river profile instead of steps (which a floodplain carried across
        # its belt as flat wedges with straight edges).  Only what the fit
        # changed is graded.  A fall the river has of its own (over a sea
        # cliff, a scarp, into a canyon) is no step of the fit: graded, it
        # was spread over a dozen cells, the bed above it cut down and the
        # ground below it raised by metres.
        staircase = _non_increasing_fit(smooth)
        changed = _smooth_along((np.abs(staircase - smooth) > 1e-9).astype(np.float64), BED_GRADE_CELLS)
        graded = _smooth_along(staircase, BED_GRADE_CELLS)
        fitted = np.minimum.accumulate(staircase + np.clip(2.0 * changed, 0.0, 1.0) * (graded - staircase))
        if on_edge(cells[0]):
            fitted = np.minimum(fitted, smooth[0])
        if junction is not None:
            fitted = np.maximum(fitted, junction)
        elif on_edge(cells[-1]):
            fitted = np.maximum(fitted, smooth[-1])
        bed[cells] = bed[cells] + (fitted - smooth)
        level[cells] = fitted
        done[cells] = True
    return bed.reshape(shape)


def channel_belts(elevation, land, *, dx, dy, wrap_x=False, inflow_cells=None, monotone_beds=False, fit_min_half_width_m=0.0, route_elevation=None, jitter=None):
    """Channels and the floodplain belts along them.

    Flow is routed over the depression-filled surface.  Cells whose
    contributing area exceeds ``CHANNEL_HEAD_AREA_M2`` are channel cells;
    every other cell belongs to the channel whose floodplain reaches it
    furthest (``_dominant_channel``) and learns that channel's distance, bed
    elevation and floodplain half-width.  A cell is in the belt when it lies
    within that half-width and no more than a few metres (plus 2 % of the
    half-width) above the bed.

    Returns a dict of ``[H, W]`` arrays: ``channel`` (bool), ``belt`` (0..1,
    1 at the channel, about 0.5 across the outer floodplain and tapering to 0
    at its edge), ``distance_m``, ``bed_elevation_m`` and ``half_width_m`` of
    that channel, and ``area_m2``.  ``inflow_cells`` (``inflow_grid``) adds
    the catchment that rivers bring in across the tile boundary.  With
    ``monotone_beds`` the channel beds are first fitted to never rise
    downstream (``monotone_channel_beds``; only channels whose floodplain
    half-width reaches ``fit_min_half_width_m``): ``bed_elevation_m`` holds
    the along-river smoothed fit, ``fitted_channel_bed_m`` the exact fit on
    those channel cells (NaN elsewhere) and ``raw_bed_elevation_m`` the
    unfitted bed of each cell's channel.  ``route_elevation`` routes the
    flow on another surface than ``elevation`` (whose values are the beds);
    ``jitter`` is added to the routed surface only (default: the grid's own
    ``routing_jitter``, the same for every caller).
    """
    elevation = np.asarray(elevation, dtype=np.float64)
    land = np.asarray(land, dtype=bool)
    shape = elevation.shape
    route = elevation if route_elevation is None else np.asarray(route_elevation, dtype=np.float64)
    if jitter is None:
        # One routing for terrain and materials: rivers wander over smooth
        # ground instead of running as ruler-straight D8 lines.
        _plain, route_gradient = d8_receivers(route, dx=dx, dy=dy, wrap_x=wrap_x, sinks=~land)
        jitter = routing_jitter(route_gradient, dx=dx, dy=dy, seed=ROUTING_JITTER_SEED + shape[0] * 4099 + shape[1])
    receivers = filled_routing(route, land, dx=dx, dy=dy, wrap_x=wrap_x, jitter=jitter, inlets=inlet_mask(inflow_cells, shape, dx=dx, dy=dy))
    sources = np.ones(receivers.size)
    if inflow_cells is not None:
        sources = sources + np.asarray(inflow_cells, dtype=np.float64).ravel()
    area = upstream_sum(receivers, sources)[:, 0].reshape(shape) * dx * dy
    channel = land & (area >= CHANNEL_HEAD_AREA_M2)
    half_width = FLOODPLAIN_WIDTH_COEFFICIENT_M * (area / 1.0e6) ** FLOODPLAIN_WIDTH_EXPONENT
    seed, reach_m, distance = _dominant_channel(channel, np.where(channel, half_width, 0.0), dx=dx, dy=dy, wrap_x=wrap_x)
    found = seed >= 0
    safe = np.where(found, seed, 0).ravel()
    raw_bed = np.where(found, elevation.ravel()[safe].reshape(shape), np.nan)
    fitted_channel = None
    if monotone_beds:
        fit = channel & (half_width >= fit_min_half_width_m)
        # The floodplain takes a correction that is smooth along its river
        # (a cell-by-cell one printed the bed's noise as stripes); the
        # channel cells themselves get the exact fit.
        smooth = monotone_channel_beds(elevation, fit, receivers, area, smooth_cells=2.0)
        bed = np.where(found, smooth.ravel()[safe].reshape(shape), np.nan)
        fitted_channel = np.where(fit, monotone_channel_beds(elevation, fit, receivers, area), np.nan)
    else:
        bed = raw_bed
    width = np.where(found, half_width.ravel()[safe].reshape(shape), 0.0)
    distance = np.where(found, distance, np.inf)
    spacing_cap = max(dx, dy)
    reach = found & (distance <= np.maximum(width, spacing_cap * 0.5))
    rise = elevation - np.where(np.isfinite(bed), bed, elevation)
    rise_limit = 3.0 + 0.02 * width
    low_enough = rise <= rise_limit
    in_belt = land & reach & low_enough
    # Full cover near the channel, half cover across the outer floodplain,
    # tapering to nothing at its edge (the last fifth of the half-width) and
    # towards the valley walls, so neither the flattening nor the alluvial
    # cover ends in a step.
    edge_ratio = np.where(np.isfinite(distance), distance, 0.0) / np.maximum(width, spacing_cap * 0.5)
    taper = _smooth01((1.0 - edge_ratio) / 0.2) * _smooth01((rise_limit - rise) / (0.3 * rise_limit))
    belt = np.where(in_belt, np.clip(1.0 - 0.5 * edge_ratio, 0.5, 1.0) * taper, 0.0)
    belt = np.where(channel, 1.0, belt)
    return {
        "channel": channel,
        "belt": belt,
        "distance_m": np.where(np.isfinite(distance), distance, np.inf),
        "bed_elevation_m": np.where(np.isfinite(bed), bed, elevation),
        "raw_bed_elevation_m": np.where(np.isfinite(raw_bed), raw_bed, elevation),
        "fitted_channel_bed_m": fitted_channel,
        "half_width_m": width,
        "area_m2": area,
    }


def upstream_area_m2(receivers, shape, *, dx, dy):
    """Contributing area of every cell (itself included) in square metres."""
    cells = upstream_sum(receivers, np.ones(receivers.size))[:, 0]
    return (cells * dx * dy).reshape(shape)


def stream_power_index(area_m2, gradient, alluvial):
    """``sqrt(area) x slope`` scaled to 0..1 over the map's alluvial cells.

    High values are steep, high-discharge reaches (coarse beds); low values
    are slack water (fines).
    """
    power = np.sqrt(np.maximum(area_m2, 0.0)) * np.maximum(gradient, 0.0)
    reference = power[alluvial > 0.02]
    if reference.size < 8:
        reference = power.ravel()
    scale = float(np.percentile(reference, 95.0)) if reference.size else 1.0
    return np.clip(power / max(scale, 1e-9), 0.0, 1.0)


def gaussian_blur(values, sigma_cells):
    """Separable Gaussian blur of a 2-D array (edge padded)."""
    values = np.asarray(values, dtype=np.float64)
    radius = int(math.ceil(3.0 * float(sigma_cells)))
    if radius < 1:
        return values.copy()
    offsets = np.arange(-radius, radius + 1)
    kernel = np.exp(-0.5 * (offsets / float(sigma_cells)) ** 2)
    kernel /= kernel.sum()
    padded = np.pad(values, radius, mode="edge")
    rows = np.apply_along_axis(lambda row: np.convolve(row, kernel, mode="valid"), 1, padded)
    return np.apply_along_axis(lambda column: np.convolve(column, kernel, mode="valid"), 0, rows)


def box_mean(values, radius):
    """Mean over a ``(2r+1)^2`` window, clamped at the edges (cumulative sums)."""
    padded = np.pad(values, radius, mode="edge")
    summed = np.cumsum(np.cumsum(padded, axis=0), axis=1)
    summed = np.pad(summed, ((1, 0), (1, 0)))
    size = 2 * radius + 1
    total = summed[size:, size:] - summed[:-size, size:] - summed[size:, :-size] + summed[:-size, :-size]
    return total / float(size * size)


# Relief below which topographic position does not move weathered mantle:
# a few soil depths (soil-mantled hillslopes carry ~0.3-1 m, Heimsath et al.
# 1997), so a 1 m knoll on a plain keeps its cover.
CATENA_RELIEF_FLOOR_M = 3.0


def catena_fields(elevation, land, gradient, area_m2, *, dx, dy):
    """Hillslope position and wetness for the catena (0..1 fields).

    ``crest``: convex upper slopes, where weathered mantle is thin.
    ``toeslope``: concave, gentle lower slopes that collect colluvial mantle.
    ``wet``: high topographic wetness ``ln(a / tan b)``; saturated hollows.
    """
    spacing = math.sqrt(dx * dy)
    radius = int(min(12, max(2, round(250.0 / max(spacing, 1e-3)))))
    position = elevation - box_mean(elevation, radius)
    land_position = position[land]
    spread = float(np.std(land_position)) if land_position.size > 8 else 1.0
    # Crests shed and hollows gather mantle only where relief spans several
    # soil depths.  Normalised by the map's own spread alone, a near-flat
    # site's decimetre roughness counted as full crests and hollows and
    # stippled bedrock through the cover on every bump.
    normalised = position / max(spread, CATENA_RELIEF_FLOOR_M)
    gentle = 1.0 - _smooth01((gradient - 0.12) / 0.18)
    crest = _smooth01((normalised - 0.4) / 1.2)
    toeslope = _smooth01((-normalised - 0.4) / 1.2) * gentle
    specific_area = np.maximum(area_m2, dx * dy) / max(spacing, 1e-3)
    # D8 concentrates flow into single-cell lines, which on planar slopes
    # become parallel streaks; a one-cell mean spreads them like the
    # dispersive flow they stand for.
    wetness_index = box_mean(np.log(specific_area / np.maximum(gradient, 1e-3)), 1)
    land_wetness = wetness_index[land]
    if land_wetness.size > 8:
        # Only valley floors and flat hollows saturate, not every gully.
        low, high = np.percentile(land_wetness, 85.0), np.percentile(land_wetness, 99.0)
    else:
        low, high = 0.0, 1.0
    wet = _smooth01((wetness_index - low) / max(high - low, 1e-6)) * gentle
    zero = np.zeros(elevation.shape)
    return {
        "crest": np.where(land, crest, zero),
        "toeslope": np.where(land, toeslope, zero),
        "wet": np.where(land, wet, zero),
        "window_radius_cells": radius,
    }


def talus_fields(receivers, gradient, land, composition, *, dx, dy, runout_m=120.0, rock=None, faces=None):
    """Rockfall aprons below cliffs and the cliff rock they are made of.

    Cliff cells (gradient above ``CLIFF_GRADIENT``; only where ``rock`` is
    true when given -- an alluvial cut bank fails in slump blocks of its own
    sediment, not rockfall; and cells ``faces`` marks as rock face whatever
    the grid's own gradient -- a face narrower than a cell) shed debris
    along their receivers.  On cells below the angle of repose the passing debris comes
    to rest at ``1 - exp(-spacing / runout_m)`` per cell, i.e. per metre
    travelled, so an apron has the same physical length at every map level;
    travel stops after twice ``runout_m``.  Returns ``(fraction,
    composition)`` where ``fraction`` is the apron's areal share of each cell
    and ``composition`` (``[materials, H, W]``) the debris mix there.
    """
    composition = np.asarray(composition, dtype=np.float64)
    material_count = composition.shape[0]
    shape = gradient.shape
    size = receivers.size
    spacing = math.sqrt(dx * dy)
    steps = int(min(96, max(1, round(2.0 * runout_m / max(spacing, 1e-3)))))
    settle = 1.0 - math.exp(-spacing / max(runout_m, 1e-3))
    source = land & (gradient > CLIFF_GRADIENT)
    if rock is not None:
        source = source & np.asarray(rock, dtype=bool)
    if faces is not None:
        source = source | (land & np.asarray(faces, dtype=bool))
    source = source.ravel()
    fraction = np.zeros(size)
    deposited = np.zeros((material_count, size))
    if not source.any():
        return fraction.reshape(shape), deposited.reshape((material_count,) + shape)
    flat_composition = composition.reshape(material_count, -1)
    cells = np.flatnonzero(source)
    # Steeper (higher) faces shed more debris per cell.
    weight = np.clip(0.5 + (gradient.ravel()[cells] - CLIFF_GRADIENT) / 0.5, 0.5, 1.5)
    carried = flat_composition[:, cells] * weight[None]
    resting = (land.ravel() & (gradient.ravel() < REPOSE_GRADIENT))
    for _step in range(steps):
        targets = receivers[cells]
        moving = targets < size
        cells, weight, carried = targets[moving], weight[moving], carried[:, moving]
        if cells.size == 0:
            break
        settles = resting[cells]
        settled_weight = np.where(settles, weight * settle, 0.0)
        np.add.at(fraction, cells, settled_weight)
        for material in range(material_count):
            np.add.at(deposited[material], cells, carried[material] * np.where(settles, settle, 0.0))
        weight = weight - settled_weight
        carried = carried * np.where(settles, 1.0 - settle, 1.0)[None]
    mix = deposited / np.maximum(deposited.sum(axis=0), 1e-12)[None]
    return (
        np.clip(fraction, 0.0, 0.9).reshape(shape),
        mix.reshape((material_count,) + shape),
    )


def fault_offsets(along, across, *, unit_scale, seed, strain=0.0):
    """Offset the unit lattice across faults; return shifted coordinates.

    Faults sit on a lattice fixed in the strike-aligned metric frame rather
    than in the tile: each lattice cell holds at most one fault, mostly
    strike-parallel, some cross faults.  Displacement is strike-slip along
    the trace, tapers to zero at the tips and fades to zero at twice the
    half-length from the trace, so every fault's influence is bounded and a
    grid sees exactly the faults that reach it.  Two grids therefore agree
    where they overlap if they share the metric frame and ``strain`` (0..1,
    mean tectonic strain, which raises fault density); child tiles derive
    their frame from their own centre and strike, like the unit lattice.

    Faults also move one side up: strike-parallel faults are mostly
    strike-slip (vertical throw 6 % of the lateral), cross faults behave as
    normal/transfer faults (25 %).  ``heave`` is that vertical offset in
    metres, which shifts bed stacks so outcrop belts step across the trace.
    Returns ``(along, across, faults, heave)``; ``faults`` lists traces in
    the metric frame as ``((a0, c0), (a1, c1), throw_m, vertical_m, kind)``.
    """
    spacing = unit_scale * 7.0
    density = 0.35 + 0.5 * float(np.clip(strain, 0.0, 1.0))
    # Centre up to sqrt(2) cells from the lattice origin, influence up to
    # sqrt(1 + 2^2) half-lengths (<= 1.2 cells) from the centre.
    reach = spacing * (math.sqrt(2.0) + math.sqrt(5.0) * 1.2)
    along_min, along_max = float(along.min()), float(along.max())
    across_min, across_max = float(across.min()), float(across.max())
    first_along = int(math.floor((along_min - reach) / spacing))
    last_along = int(math.floor((along_max + reach) / spacing))
    first_across = int(math.floor((across_min - reach) / spacing))
    last_across = int(math.floor((across_max + reach) / spacing))
    lattice_along, lattice_across = np.meshgrid(
        np.arange(first_along, last_along + 1, dtype=np.int64),
        np.arange(first_across, last_across + 1, dtype=np.int64),
    )
    lattice_along = lattice_along.ravel()
    lattice_across = lattice_across.ravel()
    present = hash_unit(lattice_along, lattice_across, seed) < density
    shift_along = np.zeros(along.shape)
    shift_across = np.zeros(across.shape)
    heave = np.zeros(along.shape)
    faults = []
    for cell_along, cell_across in zip(lattice_along[present].tolist(), lattice_across[present].tolist()):
        draws = [
            float(hash_unit(np.asarray([cell_along]), np.asarray([cell_across]), seed + offset)[0])
            for offset in range(1, 7)
        ]
        center_along = (cell_along + draws[0]) * spacing
        center_across = (cell_across + draws[1]) * spacing
        cross = draws[2] < 0.3
        angle = math.radians((60.0 + 30.0 * draws[3]) * (1.0 if draws[4] < 0.5 else -1.0)) if cross else math.radians((draws[3] - 0.5) * 40.0)
        half_length = spacing * (0.4 + 0.8 * draws[4])
        throw = unit_scale * (0.25 + 1.0 * draws[5])
        influence = half_length * math.sqrt(5.0)
        if (
            center_along + influence < along_min or center_along - influence > along_max
            or center_across + influence < across_min or center_across - influence > across_max
        ):
            continue
        tangent_along, tangent_across = math.cos(angle), math.sin(angle)
        relative_along = along - center_along
        relative_across = across - center_across
        station = relative_along * tangent_along + relative_across * tangent_across
        offset = -relative_along * tangent_across + relative_across * tangent_along
        taper = np.clip(1.0 - (station / half_length) ** 2, 0.0, 1.0)
        falloff = np.clip(1.0 - np.abs(offset) / (2.0 * half_length), 0.0, 1.0) ** 2
        if not np.any(taper * falloff > 0.0):
            continue
        slip = np.sign(offset) * 0.5 * throw * taper * falloff
        shift_along += slip * tangent_along
        shift_across += slip * tangent_across
        vertical = throw * (0.25 if cross else 0.06)
        heave += np.sign(offset) * 0.5 * vertical * taper * falloff
        faults.append((
            (center_along - half_length * tangent_along, center_across - half_length * tangent_across),
            (center_along + half_length * tangent_along, center_across + half_length * tangent_across),
            throw,
            vertical,
            "cross" if cross else "strike_parallel",
        ))
    return along + shift_along, across + shift_across, faults, heave
