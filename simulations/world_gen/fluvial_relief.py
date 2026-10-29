"""Drainage-organised relief for refined terrain (stream-power incision).

Refinement adds relief below the parent's resolution as noise, which reads as
egg-crate bumps: mountains without valleys.  At these scales real relief is
organised by its drainage.  ``stream_power_relief`` erodes the refined
surface with the detachment-limited stream-power law

    dh/dt = -K A^m S      (n = 1)

solved implicitly along the drainage tree (Braun & Willett 2013), alternated
with linear hillslope diffusion, for a few iterations.  The implicit update
of a cell needs its receiver's updated height, so cells are processed in
order of their distance to an outlet; all cells at one distance are updated
together, which keeps the whole scheme in NumPy.
"""

from __future__ import annotations

import math

import numpy as np

from simulations.world_gen.material_routing import _D8_OFFSETS, box_mean, d8_receivers, upstream_sum


def outlet_distance(receivers):
    """Number of receiver hops from every cell to its sink (pointer doubling)."""
    size = receivers.size
    pointer = np.append(np.asarray(receivers, dtype=np.int64), size)
    distance = np.append((pointer[:size] < size).astype(np.int64), 0)
    for _step in range(64):
        if np.all(pointer[:size] == size):
            break
        distance = distance + np.where(pointer < size, distance[pointer], 0)
        pointer = pointer[pointer]
    return distance[:size]


def stochastic_receivers(elevation, *, dx, dy, sinks=None, rng=None, exponent=1.5, correlation_cells=2):
    """D8 receivers drawn among lower neighbours, weighted by ``slope ** exponent``.

    Steepest descent sends every cell of a planar ramp straight downslope, so
    neighbouring flowlines never meet and each column incises its own groove:
    a curtain of parallel valleys one cell apart.  Choosing at random among
    the strictly lower neighbours, weighted by slope, lets flowlines wander
    and coalesce into a branching network on uniform slopes (Scheidegger's
    river-network model), while valleys still capture flow because their
    walls fall steeply towards the axis.  The draw is a spatially correlated
    uniform field (box-filtered over ``correlation_cells``): independent
    per-cell draws zig-zagged every cell and incised beaded channels, while
    correlated draws deflect paths smoothly and make them converge where the
    field turns.  Every edge goes strictly downhill, so the network stays
    acyclic; cells without a lower neighbour keep the steepest-descent
    receiver.
    """
    elevation = np.asarray(elevation, dtype=np.float64)
    height, width = elevation.shape
    size = height * width
    rng = rng if rng is not None else np.random.default_rng(0)
    deterministic, _gradient = d8_receivers(elevation, dx=dx, dy=dy, sinks=sinks)
    rows = np.arange(height)[:, None]
    columns = np.arange(width)[None, :]
    weights = np.zeros((len(_D8_OFFSETS), size))
    targets = np.zeros((len(_D8_OFFSETS), size), dtype=np.int64)
    for index, (row_offset, column_offset) in enumerate(_D8_OFFSETS):
        neighbour_rows = rows + row_offset
        neighbour_columns = columns + column_offset
        valid = (neighbour_rows >= 0) & (neighbour_rows < height) & (neighbour_columns >= 0) & (neighbour_columns < width)
        neighbour_rows = np.clip(neighbour_rows, 0, height - 1)
        neighbour_columns = np.clip(neighbour_columns, 0, width - 1)
        slope = (elevation - elevation[neighbour_rows, neighbour_columns]) / math.hypot(column_offset * dx, row_offset * dy)
        weights[index] = np.where(valid & (slope > 0.0), np.maximum(slope, 0.0) ** exponent, 0.0).ravel()
        targets[index] = np.broadcast_to(neighbour_rows * width + neighbour_columns, elevation.shape).ravel()
    total = weights.sum(axis=0)
    field = rng.standard_normal((height, width))
    if correlation_cells > 0:
        field = box_mean(field, int(correlation_cells))
    uniform = (np.argsort(np.argsort(field.ravel(), kind="stable"), kind="stable") + 0.5) / size
    pick = uniform * total
    choice = np.minimum((np.cumsum(weights, axis=0) <= pick[None]).sum(axis=0), len(_D8_OFFSETS) - 1)
    cells = np.arange(size)
    usable = (total > 0.0) & (weights[choice, cells] > 0.0)
    receivers = np.where(usable, targets[choice, cells], deterministic)
    if sinks is not None:
        receivers = np.where(np.asarray(sinks, dtype=bool).ravel(), size, receivers)
    return receivers


def _laplacian(values):
    padded = np.pad(values, 1, mode="edge")
    return padded[:-2, 1:-1] + padded[2:, 1:-1] + padded[1:-1, :-2] + padded[1:-1, 2:] - 4.0 * values


def stream_power_relief(
    elevation,
    land,
    *,
    dx,
    dy,
    iterations=10,
    trunk_erodibility=0.6,
    reference_cells=2000.0,
    area_exponent=0.5,
    diffusion=0.12,
    seed=0,
    detail_relief=None,
    inflow_cells=None,
):
    """Erode ``elevation`` (``[H, W]``) into drainage-organised relief.

    ``trunk_erodibility`` is the implicit factor ``F = K dt A^m / L`` for a
    catchment of ``reference_cells``; smaller catchments scale with
    ``(A / A_ref)^m``, so hillslopes barely erode while trunks cut valleys.
    Ocean cells and the grid edge are base level.  ``diffusion`` is the
    explicit hillslope step in cell units (stable below 0.25).  Receivers are
    drawn among lower neighbours by slope (``stochastic_receivers``), so
    flowlines on planar ramps coalesce instead of running as parallel D8
    lines.  ``detail_relief`` (``[H, W]``, metres) is the local
    amplitude of the relief being organised: routing jitter is spatially
    correlated and scaled to it, and incision never exceeds it, so smooth
    inherited slopes are not cut into new canyons.  ``inflow_cells`` adds the
    catchment (in cells) that rivers bring in across the tile boundary.
    Returns ``(eroded, summary)``.
    """
    height = np.asarray(elevation, dtype=np.float64).copy()
    land = np.asarray(land, dtype=bool)
    shape = height.shape
    # Ocean is base level; the depression fill also drains to the grid edge,
    # and edge cells with no lower neighbour become sinks, so rivers can leave
    # the tile; where they enter (``inflow_cells``) the edge is no outlet.
    base_level = ~land
    spacing = math.sqrt(dx * dy)
    rng = np.random.default_rng(seed)
    relief_scale = float(np.percentile(height[land], 95.0) - np.percentile(height[land], 5.0)) if land.any() else 1.0
    if detail_relief is None:
        detail_relief = np.full(shape, relief_scale)
    detail_relief = np.maximum(np.asarray(detail_relief, dtype=np.float64), 0.0)
    # Correlated micro-relief for routing only: flowlines wander and merge
    # instead of running as parallel D8 lines across smooth slopes and flats.
    jitter = box_mean(rng.standard_normal(shape), 2) * (0.08 * detail_relief + max(1e-3, relief_scale * 1e-4))
    diagonal = math.hypot(dx, dy)
    width = shape[1]
    # Route once over the depression-filled surface: every cell drains to
    # base level (no pits), and the network is kept while channels deepen.
    from simulations.world_gen.drainage import _priority_flood

    from simulations.world_gen.material_routing import inlet_mask

    filled, _parent, _order = _priority_flood(
        (height + jitter).tolist(), base_level.tolist(), False, inlets=inlet_mask(inflow_cells, shape, dx=dx, dy=dy),
    )
    receivers = stochastic_receivers(np.asarray(filled, dtype=np.float64), dx=dx, dy=dy, sinks=base_level, rng=rng)
    sources = np.ones(receivers.size)
    if inflow_cells is not None:
        sources = sources + np.asarray(inflow_cells, dtype=np.float64).ravel()
    area = upstream_sum(receivers, sources)[:, 0]
    distance = outlet_distance(receivers)
    cell_index = np.arange(receivers.size)
    target = np.minimum(receivers, receivers.size - 1)
    same_row = target // width == cell_index // width
    same_column = target % width == cell_index % width
    hop = np.where(~same_row & ~same_column, diagonal, np.where(same_column, dy, dx))
    factor = trunk_erodibility * (area / reference_cells) ** area_exponent * (spacing / hop)
    order = np.argsort(distance, kind="stable")
    levels = distance[order]
    boundaries = np.searchsorted(levels, np.arange(1, int(levels.max()) + 2))
    for _iteration in range(iterations):
        flat = height.ravel().copy()
        for level in range(1, int(levels.max()) + 1):
            cells = order[boundaries[level - 1]:boundaries[level]]
            if cells.size == 0:
                continue
            downstream = receivers[cells]
            # A cell never erodes below its receiver (no reverse gradients).
            updated = (flat[cells] + factor[cells] * flat[downstream]) / (1.0 + factor[cells])
            flat[cells] = np.maximum(updated, flat[downstream])
        height = flat.reshape(shape)
        height = np.where(land, height + diffusion * _laplacian(height), height)
    original = np.asarray(elevation, dtype=np.float64)
    height = np.where(land, np.maximum(height, original - detail_relief), original)
    return height, {
        "longest_flow_path_cells": int(levels.max()) if levels.size else 0,
        "iterations": int(iterations),
        "trunk_erodibility": float(trunk_erodibility),
        "area_exponent": float(area_exponent),
        "diffusion": float(diffusion),
    }


def conserve_parent_scale(original, eroded, land, radius):
    """Add back the local mean loss, so parent-scale elevation is unchanged."""
    change = np.where(land, original - eroded, 0.0)
    return np.where(land, eroded + box_mean(change, radius), original)
