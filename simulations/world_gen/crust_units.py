"""Rock units and faults anchored to the planet.

A geological map is made of units (the outcrop of one rock body) and the
faults that offset them.  Both are properties of the crust, not of the map
that shows them: two maps of the same ground, a child and its parent, or two
neighbours, must draw the same units and the same faults.  Here both live on
the sphere:

* **Units** are the cells of a jittered 3D lattice (one per ``UNIT_SCALES_M``
  rung) around the planet, measured anisotropically: along the local
  structural strike a unit is ``anisotropy`` times longer, across it shorter
  (fold-and-thrust belts and accreted terranes elongate parallel to their
  orogen; cratons are blotchy).  The strike is the planet's (the convergent
  boundary segments, ``strata.strike_field``) and the elongation scales with
  crustal shortening.  A domain warp makes contacts wander below a unit's
  size.  Each unit's draw for each material is a smooth planet noise plus its
  own white noise (Gaussian copula, so the draw stays uniform and a race over
  the composition keeps its proportions without a rank over the units a map
  happens to hold).
* **Faults** sit one per cell of a coarser 3D lattice (``FAULT_SPACING_UNITS``
  unit sizes) where a draw falls under the density (higher with strain), on
  the sphere at the jittered lattice point, mostly parallel to the local
  strike with some cross faults (60-90 degrees).  Displacement is strike-slip
  along the trace, tapering to zero at the tips and fading to zero two
  half-lengths away; strike-parallel faults throw one side up by 6 % of the
  lateral offset, cross (normal/transfer) faults by 25 % (``heave``, which
  steps bed stacks across the trace).

A map uses the finest unit rung at least ``MIN_UNIT_CELLS`` of its cells
wide, so maps of one scale share a lattice and a finer map adds finer units
inside its parent's (which it inherits through the composition).
"""

from __future__ import annotations

import itertools
import math

import numpy as np

from simulations.world_gen.array_noise import seed_int
from simulations.world_gen.sphere_noise import _value_noise_3d, sphere_positions

# Unit sizes (m): terranes, plutons and belts, map units, members ... (the
# rungs a map picks from, so maps of one scale share their units).
UNIT_SCALES_M = (600_000.0, 60_000.0, 6_000.0, 1_200.0, 300.0, 80.0, 20.0, 6.0)
MIN_UNIT_CELLS = 8.0
UNIT_ANISOTROPY = 1.8
UNIT_JITTER = 0.9
UNIT_WARP = 0.45
# Smooth part of a unit's draw, in unit sizes (neighbouring units share
# lithologies, so belts continue across several units).
DRAW_CORRELATION_UNITS = 1.2
DRAW_SMOOTH_WEIGHT = 0.45
FAULT_SPACING_UNITS = 7.0
_SEARCH = 2
_FBM2_SPREAD = 0.15


def unit_scale_for(cell_m):
    """The finest rung at least ``MIN_UNIT_CELLS`` cells wide (the coarsest when none is)."""
    fitting = [scale for scale in UNIT_SCALES_M if scale >= MIN_UNIT_CELLS * float(cell_m)]
    return min(fitting) if fitting else UNIT_SCALES_M[0]


def _uniform3(ix, iy, iz, seed):
    with np.errstate(over="ignore"):
        h = (
            np.asarray(ix, dtype=np.int64).astype(np.uint64) * np.uint64(0x9E3779B97F4A7C15)
            ^ np.asarray(iy, dtype=np.int64).astype(np.uint64) * np.uint64(0xC2B2AE3D27D4EB4F)
            ^ np.asarray(iz, dtype=np.int64).astype(np.uint64) * np.uint64(0x165667B19E3779F9)
            ^ np.uint64(int(seed) % (1 << 63))
        )
        h = (h ^ (h >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
        h = (h ^ (h >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
        h = h ^ (h >> np.uint64(31))
    return h


def _unit_float(hashes):
    return (hashes >> np.uint64(11)).astype(np.float64) / float(1 << 53)


def tangent_basis(u, v):
    """Unit radial, east and south vectors (3, ...) at map coordinates."""
    longitude = np.asarray(u, dtype=np.float64) * math.tau
    latitude = (0.5 - np.asarray(v, dtype=np.float64)) * math.pi
    radial = np.stack(sphere_positions(u, v))
    east = np.stack([-np.sin(longitude), np.cos(longitude), np.zeros_like(longitude)])
    south = np.stack([np.sin(latitude) * np.cos(longitude), np.sin(latitude) * np.sin(longitude), -np.cos(latitude)])
    return radial, east, south


def _uv_of(points):
    """Map coordinates of 3D points (any radius)."""
    x, y, z = points
    longitude = np.arctan2(y, x)
    latitude = np.arctan2(z, np.hypot(x, y))
    return (longitude / math.tau) % 1.0, 0.5 - latitude / math.pi


def _strike_vectors(u, v, strike_east, strike_south):
    _radial, east, south = tangent_basis(u, v)
    strike = east * np.asarray(strike_east)[None] + south * np.asarray(strike_south)[None]
    return strike / np.maximum(np.linalg.norm(strike, axis=0), 1e-12)[None]


def unit_cells(u, v, *, unit_scale_m, radius_m, seed, strike_east=None, strike_south=None, anisotropy=None, shift=None):
    """The planet unit each sample lies in.

    Returns ``(keys, centres)``: an int64 key per sample (the same unit has
    the same key on every map) and the unit's feature point (3, ...) in
    metres, for draws that vary smoothly from unit to unit.
    """
    u = np.asarray(u, dtype=np.float64)
    v = np.asarray(v, dtype=np.float64)
    scale = float(unit_scale_m)
    radial, east, south = tangent_basis(u, v)
    points = radial * float(radius_m)
    if shift is not None:
        points = points + shift
    if strike_east is None:
        strike = east
    else:
        strike = _strike_vectors(u, v, strike_east, strike_south)
    across = np.cross(radial, strike, axis=0)
    stretch = np.ones(u.shape) if anisotropy is None else np.asarray(anisotropy, dtype=np.float64)
    grid = points / scale
    warp_seed = np.uint64(seed_int(str(seed), "units:warp") % (1 << 63))
    warped = points + UNIT_WARP * scale * np.stack([
        2.0 * _value_noise_3d(grid[0] / 1.7 + 11.0 * axis, grid[1] / 1.7 - 7.0 * axis, grid[2] / 1.7 + 3.0 * axis, warp_seed + np.uint64(axis)) - 1.0
        for axis in range(3)
    ])
    base = np.floor(warped / scale).astype(np.int64)
    # Feature points and keys of every lattice cell the search can reach,
    # computed once (the samples of a map share a few thousand cells).
    low = base.reshape(3, -1).min(axis=1) - _SEARCH
    size = base.reshape(3, -1).max(axis=1) + _SEARCH - low + 1
    table_cells = np.stack(np.meshgrid(*[np.arange(low[axis], low[axis] + size[axis]) for axis in range(3)], indexing="ij"))
    jitter_seeds = [seed_int(str(seed), f"units:jitter:{axis}") for axis in range(3)]
    table_features = np.stack([
        (table_cells[axis] + 0.5 + (_unit_float(_uniform3(table_cells[0], table_cells[1], table_cells[2], jitter_seeds[axis])) - 0.5) * UNIT_JITTER) * scale
        for axis in range(3)
    ])
    table_keys = (_uniform3(table_cells[0], table_cells[1], table_cells[2], seed_int(str(seed), "units:key")) >> np.uint64(1)).astype(np.int64)
    local = base - low.reshape((3,) + (1,) * (base.ndim - 1))
    # Distances in the anisotropic metric: project once, then per candidate.
    warped_along = np.sum(warped * strike, axis=0)
    warped_side = np.sum(warped * across, axis=0)
    warped_up = np.sum(warped * radial, axis=0)
    best = np.full(u.shape, np.inf)
    index_best = np.zeros(u.shape, dtype=np.int64)
    offsets = range(-_SEARCH, _SEARCH + 1)
    flat_index = lambda ix, iy, iz: (ix * size[1] + iy) * size[2] + iz
    flat_features = table_features.reshape(3, -1)
    for ox, oy, oz in itertools.product(offsets, offsets, offsets):
        index = flat_index(local[0] + ox, local[1] + oy, local[2] + oz)
        feature = flat_features[:, index]
        along = (np.sum(feature * strike, axis=0) - warped_along) / stretch
        side = (np.sum(feature * across, axis=0) - warped_side) * stretch
        up = np.sum(feature * radial, axis=0) - warped_up
        distance = along * along + side * side + up * up
        closer = distance < best
        best = np.where(closer, distance, best)
        index_best = np.where(closer, index, index_best)
    return table_keys.ravel()[index_best], flat_features[:, index_best]


def unit_draws(keys, centres, material_ids, *, unit_scale_m, seed):
    """Uniform draw per sample and material, the same for every sample of a unit (``[M, ...]``)."""
    keys = np.asarray(keys, dtype=np.int64)
    flat_keys = keys.ravel()
    unique, first, inverse = np.unique(flat_keys, return_index=True, return_inverse=True)
    flat_centres = np.asarray(centres).reshape(3, -1)[:, first] / (DRAW_CORRELATION_UNITS * float(unit_scale_m))
    draws = np.zeros((len(material_ids),) + keys.shape)
    for index, material_id in enumerate(material_ids):
        material_seed = seed_int(str(seed), f"units:draw:{material_id}")
        smooth = (
            0.5 * _value_noise_3d(flat_centres[0], flat_centres[1], flat_centres[2], np.uint64(material_seed % (1 << 63)))
            + 0.5 * _value_noise_3d(2.0 * flat_centres[0] + 5.1, 2.0 * flat_centres[1] - 3.3, 2.0 * flat_centres[2] + 1.7, np.uint64((material_seed + 1) % (1 << 63)))
        )
        smooth_z = (smooth - 0.5) / _FBM2_SPREAD
        white = sum(_unit_float(_uniform3(unique, np.full(unique.shape, part), np.zeros(unique.shape, dtype=np.int64), material_seed + 3)) for part in range(3))
        white_z = (white - 1.5) * 2.0
        z = DRAW_SMOOTH_WEIGHT * smooth_z + math.sqrt(1.0 - DRAW_SMOOTH_WEIGHT ** 2) * white_z
        uniform = 1.0 / (1.0 + np.exp(-1.702 * z))
        draws[index] = np.clip(uniform, 1e-9, 1.0 - 1e-9)[inverse].reshape(keys.shape)
    return draws


def planet_faults(u, v, *, unit_scale_m, radius_m, seed, strain_at=None, strike_at=None):
    """Planet-anchored faults that reach the samples.

    ``strain_at(u, v) -> strain (0..1)`` raises the fault density (0.35 at
    none, 0.85 at full); ``strike_at(u, v) -> (east, south)`` gives the local
    strike (east when ``None``).  Both are read at each fault's own centre, so
    whether a fault exists does not depend on the map.  Returns ``(shift, heave, faults)``: the 3D displacement of
    each sample's rock (metres), the vertical offset (metres) and the traces
    ``((u0, v0), (u1, v1), throw_m, vertical_m, kind)``.
    """
    u = np.asarray(u, dtype=np.float64)
    v = np.asarray(v, dtype=np.float64)
    radius = float(radius_m)
    spacing = float(unit_scale_m) * FAULT_SPACING_UNITS
    radial = np.stack(sphere_positions(u, v))
    points = radial * radius
    reach = spacing * (math.sqrt(3.0) + math.sqrt(5.0) * 1.2)
    low = np.floor((points.reshape(3, -1).min(axis=1) - reach) / spacing).astype(np.int64)
    high = np.floor((points.reshape(3, -1).max(axis=1) + reach) / spacing).astype(np.int64)
    shift = np.zeros(points.shape)
    heave = np.zeros(u.shape)
    faults = []
    cells = np.stack(np.meshgrid(*[np.arange(low[axis], high[axis] + 1) for axis in range(3)], indexing="ij")).reshape(3, -1)
    # One fault per lattice cell of the shell the surface passes through:
    # cells deeper or higher would project onto the same ground again.
    middle = (cells + 0.5) * spacing
    cells = cells[:, np.abs(np.linalg.norm(middle, axis=0) - radius) < 0.5 * spacing]
    if cells.size == 0:
        return shift, heave, faults
    presence = _unit_float(_uniform3(cells[0], cells[1], cells[2], seed_int(str(seed), "faults:present")))
    cells = cells[:, presence < 0.85]
    presence = presence[presence < 0.85]
    if cells.size == 0:
        return shift, heave, faults
    draws = np.stack([_unit_float(_uniform3(cells[0], cells[1], cells[2], seed_int(str(seed), f"faults:draw:{k}"))) for k in range(8)])
    lattice = (cells + 0.5 + (draws[:3] - 0.5) * 0.9) * spacing
    centres = radius * lattice / np.maximum(np.linalg.norm(lattice, axis=0), 1e-9)[None]
    # Only faults that can reach the samples need their strain read.
    flat_points = points.reshape(3, -1)
    near = np.asarray([
        float(np.min(np.linalg.norm(flat_points - centres[:, index][:, None], axis=0))) <= spacing * 1.2 * math.sqrt(5.0)
        for index in range(centres.shape[1])
    ], dtype=bool)
    cells, draws, centres, presence = cells[:, near], draws[:, near], centres[:, near], presence[near]
    if cells.size == 0:
        return shift, heave, faults
    centre_u, centre_v = _uv_of(centres)
    strain = np.zeros(centre_u.shape) if strain_at is None else np.clip(np.asarray(strain_at(centre_u, centre_v), dtype=np.float64), 0.0, 1.0)
    keep = presence < 0.35 + 0.5 * strain
    cells, draws, centres, centre_u, centre_v = cells[:, keep], draws[:, keep], centres[:, keep], centre_u[keep], centre_v[keep]
    if cells.size == 0:
        return shift, heave, faults
    if strike_at is not None:
        strike_east, strike_south = strike_at(centre_u, centre_v)
    else:
        strike_east, strike_south = np.ones(centre_u.shape), np.zeros(centre_u.shape)
    strike = _strike_vectors(centre_u, centre_v, strike_east, strike_south)
    centre_radial = centres / radius
    flat = points.reshape(3, -1)
    shift_flat = np.zeros(flat.shape)
    heave_flat = np.zeros(flat.shape[1])
    for index in range(centres.shape[1]):
        cross = draws[3, index] < 0.3
        sign = 1.0 if draws[5, index] < 0.5 else -1.0
        angle = math.radians((60.0 + 30.0 * draws[4, index]) * sign) if cross else math.radians((draws[4, index] - 0.5) * 40.0)
        half_length = spacing * (0.4 + 0.8 * draws[5, index])
        throw = float(unit_scale_m) * (0.25 + 1.0 * draws[6, index])
        t = strike[:, index]
        n = np.cross(centre_radial[:, index], t)
        tangent = math.cos(angle) * t + math.sin(angle) * n
        normal = np.cross(centre_radial[:, index], tangent)
        relative = flat - centres[:, index][:, None]
        if np.min(np.linalg.norm(relative, axis=0)) > half_length * math.sqrt(5.0):
            continue
        station = tangent @ relative
        offset = normal @ relative
        taper = np.clip(1.0 - (station / half_length) ** 2, 0.0, 1.0)
        falloff = np.clip(1.0 - np.abs(offset) / (2.0 * half_length), 0.0, 1.0) ** 2
        weight = taper * falloff
        if not np.any(weight > 0.0):
            continue
        slip = np.sign(offset) * 0.5 * throw * weight
        shift_flat += slip[None] * tangent[:, None]
        vertical = throw * (0.25 if cross else 0.06)
        heave_flat += np.sign(offset) * 0.5 * vertical * weight
        ends = np.stack([centres[:, index] - half_length * tangent, centres[:, index] + half_length * tangent], axis=1)
        end_u, end_v = _uv_of(ends)
        faults.append(((float(end_u[0]), float(end_v[0])), (float(end_u[1]), float(end_v[1])), throw, vertical,
                       "cross" if cross else "strike_parallel"))
    return shift_flat.reshape(points.shape), heave_flat.reshape(u.shape), faults
