"""Surface water and wetness from Site scale down (LOD4+), read off the ground.

Down to Local scale the hydrology rasters are painted from the drainage graph
(``drainage.derive_surface_hydrology_grids``): a path of the routed network is
a river with a wet margin beside it.  From Site scale a cell resolves the
channel itself, which ``alluvial_channels`` carves into the heightfield, and
at Parcel scale and finer hardly any flow path is a channel at all.  Painted
from the graph, a Site tile showed its river twice (the carved channel in
height and colour, a comb of straight solver paths in water, wetness and
soil), and a 300 m parcel in a steppe carried two to four hundred "rivers"
along the lines steepest descent happens to draw across decimetre roughness.

From LOD4 the rasters are therefore fields of the ground itself:

* open water is the water in the channels carved into the heightfield
  (``alluvial_channels``: the section filled to the mean-flow stage, the one
  geometry terrain, materials and True Color already share), in the lakes
  the drainage model retained, and in the sea.  A "lake" the solver fills
  inside a carved channel, below its banks, is the channel's own trough
  (the carving fades at the tile's rim and shuts it) and no water body: on
  a river 380 m wide it stood four metres above the mean-flow stage and
  drowned the bars.  A lake of the parent's keeps the parent's level on a
  finer tile, which draws its shore and does not look for its sill again;
* a flow path without a carved channel is a stream only where it carries a
  real discharge (``MIN_STREAM_DISCHARGE_M3_S``).  Anything smaller is
  overland flow or a rill: it wets the ground along its course and is no
  water body.  A stream is one thread of water, so it is followed down the
  single path of steepest descent, as the carving rule follows it
  (``alluvial_channels``), through any lake on its way and over its sill,
  and shown one cell wide.  (The many-directioned routing of the wetness
  terms is for the water a slope spreads, and it ends in every water body:
  it lost a brook of 20 l/s in the first pond it met, so that a Parcel
  showed dry ground where its Plot, which resolves the brook, carved it);
* wetness keeps its meaning (a dimensionless index: the climate's water
  balance plus channel and open-water proximity, with the coefficients of the
  coarser levels) and gains the two terrain terms that decide it at this
  scale:

  - the water the climate sets moving is redistributed by the topographic
    index ``a / tan(b)`` (Beven & Kirkby 1979) of a multiple-flow-direction
    routing (Quinn et al. 1991, with Freeman's 1991 exponent): crests and
    noses shed their share, hollows, swales and wash floors receive it.  At
    this scale that is the runoff and recharge of the coarser levels and
    half of the rain they count as kept in place: over a plot runoff is
    several times what leaves the catchment, because most of it soaks in
    again a few metres downslope (Yair & Kossovsky 2002; Wainwright &
    Parsons 2002).  The tile's total is unchanged, so fine relief shows
    where the parent's water sits and adds none;
  - beside open water the ground is wet as far as the water table reaches:
    by height above the water surface (the HAND descriptor of Renno et al.
    2008 and Nobre et al. 2011) against the soil's capillary rise, and by
    distance in channel widths, both in metres instead of cells.

Two more rasters are for whoever asks how wet the ground is for something
that grows in it (``biosphere.water_balance``); the wetness index does not
answer that, it says where the climate's surplus goes:

* the depth to the water table, the shallower of two readings:

  - ground water drains to the open water of the tile.  Between waters the
    table stands at their level, raised by what recharge piles up on the way
    (steady flow through ground of one transmissivity, the Dupuit scheme of
    Fan et al. 2013), and never above the ground, where it seeps out;
  - the ground carries its recharge downslope through a mantle whose
    conductivity falls off with depth, and where more gathers than it
    carries, the table rises to pass it on.  At steady state its depth is
    ``ln(T0 / (R * a / tan(b))) / f`` (Beven & Kirkby 1979; the same index
    ``a / tan(b)`` as the wetness, with the fall to the water beneath for
    the gradient where that is the steeper: Hjerdt et al. 2004): shallow
    in hollows, on valley floors and on flat ground that sheds nowhere, deep
    under noses and steep slopes, shallower everywhere the wetter the
    climate (Haitjema & Mitchell-Bruker 2005: the table copies the relief
    where recharge is large against what the ground carries away; Fan et
    al. 2013 map the result worldwide).  This is drainage: the same rain
    leaves a slope and stands in a flat.  Recharge alone feeds it; runoff
    travels over the surface and is the run-on below.  One transmissivity
    stands for all ground until texture is read here.

  That is reckoned once, by the first level that reads its water off the
  ground (Site).  A finer tile is cut out of that ground and cannot see the
  water beyond its rim that sets the table, and the hillslope reading
  changes with the size of a cell: left to itself a Parcel put its table
  0.4 m deeper than its Site did over the same ground, and a plant met a
  different wetness class on a point in three.  So a finer tile takes its
  parent's table as a surface (the parent's ground less its depth, the
  water's own level where the parent has water) and measures its own, finer
  ground against it: a hollow the parent could not see is nearer the water,
  a rise further from it, and the mean stays the parent's;
* the water a year brings a cell from upslope beyond what the tile's ordinary
  ground receives, in millimetres: the same redistribution the wetness index
  uses, as an amount, measured from the median cell.  Ordinary ground is at
  nought: what it sheds is the surplus the climate's own balance already
  counts as runoff and recharge, and whoever keeps a balance for a place
  (``biosphere.water_balance``) sheds it there.  Taking it off the rain as
  well took it twice, 640 of 1730 mm on a humid plain.

And beside a carved channel, how often its floods cover a cell and how often
they rework it, in years (``river_floods``, from the channel's own section).

Where a tile has sea, the share of sea water in the ground water at the table
(``groundwater_salinity``).  Fresh ground water floats on the sea water in the
ground of a coast, and the boundary lies forty times as far below sea level as
the table stands above it (Badon Ghyben 1888, Herzberg 1901: fresh water of
1000 on sea water of 1025 kg/m3).  The boundary is a zone of mixing metres
thick (Cooper et al. 1964; 5 to 10 m on atolls, Underwood et al. 1992), so a
lens thinner than that is brackish to its top: under a table that stands a
hand above the sea the ground water is fresh, under one that stands at sea
level it is the sea's, which is the case along an arid coast for as far as
too little rain falls to pile ground water up.  Ground the tides reach (below
mean high water and joined to the sea over ground as low) is flooded by the
sea itself.  A finer tile takes the figure of its parent.

Nothing here assumes vegetation.  The rasters are stored at the heightfield's
own lattice; consumers sample them by position.
"""

from __future__ import annotations

import math

import numpy as np

from simulations.world_gen import alluvial_channels, river_floods
from simulations.world_gen.exact_rounding import round_rows
from simulations.world_gen.material_routing import _D8_OFFSETS, filled_routing, inflow_grid, inlet_mask, upstream_sum

FINE_HYDROLOGY_MIN_LEVEL = 4
MODEL_VERSION = "fine-surface-hydrology-v1"

# Terms of the wetness index, as at the coarser levels
# (``drainage.derive_surface_hydrology_grids``).
WETNESS_BASE = 0.04
WETNESS_CLIMATE = 0.68
WETNESS_CHANNEL = 0.12
WETNESS_NEAR_WATER = 0.32
# Wetness term at the water's edge (the first cell of the coarse halo).
BANK_WETNESS = 0.72
# Share of recharge and of precipitation counted as supply (coarse levels).
RECHARGE_SHARE = 0.7
PRECIPITATION_SHARE = 0.08
# Of the rain kept in place at catchment scale, the share that reaches its
# place as run-on from a few metres upslope.
PLOT_RUNON_SHARE = 0.5

# Freeman (1991): flow is divided among the lower neighbours by slope ** 1.1,
# which reproduces divergence on cones.  Quinn et al. (1991) weight by the
# contour length each direction crosses (half a cell cardinal, 0.354 diagonal).
MFD_SLOPE_EXPONENT = 1.1
MFD_CONTOUR = (0.354, 0.5, 0.354, 0.5, 0.5, 0.354, 0.5, 0.354)
# tan(b) below this is flat ground for the index (one millimetre per metre).
SLOPE_FLOOR = 1.0e-3
# A line of concentrated flow receives at most this many times the median
# cell's share: the index saturates long before, the cap keeps one pond cell
# from taking the whole tile's water in the normalisation.
REDISTRIBUTION_LOG_SPAN = 5.5

# Capillary rise above a water table: decimetres in sand, a metre or more in
# loam and silt, several in clay.  One metre stands for an alluvial loam until
# the soil texture is read here.
CAPILLARY_RISE_M = 1.0
# The wet margin of a channel reaches a few widths; of standing water, tens of
# metres.
WET_MARGIN_CHANNEL_WIDTHS = 3.0
WET_MARGIN_STILL_WATER_M = 30.0
# Below ten litres per second (mean flow) a path is a trickle or a rill, not a
# stream of its own; the coarser levels' river widths use the same floor.
MIN_STREAM_DISCHARGE_M3_S = 0.01
# Water shallower than this is wet ground, not open water.
OPEN_WATER_DEPTH_M = 0.02
# What the ground carries downslope when wet to the surface, in square metres a year per unit of gradient,
# and how fast its conductivity falls off with depth (TOPMODEL's T0 and f).  Twelve square metres a day and
# an e-folding depth of a metre are within what the model is calibrated to on soil-mantled hillslopes (Beven
# 1997).  Under 200 mm of recharge they put the table four metres down on a plain mid-slope, a metre and a
# half at its foot and at the surface in its hollows; under 10 mm, out of reach of roots nearly everywhere.
# One figure for all ground: a clay flat drains no worse here than a sand.
TRANSMISSIVITY_M2_PER_YEAR = 4400.0
CONDUCTIVITY_DECAY_PER_M = 1.0
# Less recharge than this a year moves no water table.
LEAST_RECHARGE_MM = 0.1
# The cells along a tile's rim whose routed water is the edge's, not the ground's.
RIM_CELLS = 3
# What the ground beneath the soil carries to the open water, in square metres a year per unit of gradient:
# a metre a day through twenty metres.  With it 40 mm of recharge raise the table about a metre midway
# between waters a kilometre and a half apart, 300 mm more than ten, which is to the surface of low ground.
AQUIFER_TRANSMISSIVITY_M2_PER_YEAR = 7300.0
# The relaxation of the table: lattices halved down to this many cells across, the coarsest swept until it
# has settled, each finer one only long enough to fit the table to what it resolves anew.
WATER_TABLE_COARSEST_CELLS = 8
WATER_TABLE_COARSE_SWEEPS = 600
WATER_TABLE_FINE_SWEEPS = 40
# Depth written where no water is near enough to tell: out of any root's reach.
WATER_TABLE_UNKNOWN_M = 99.0
# Run-on along a line of concentrated flow is written as at most this many times the year's rain.
MAX_RUNON_RAINS = 10.0
# Fresh ground water on sea water (Ghyben-Herzberg): the boundary lies this many times as deep below sea
# level as the table stands above it, and is a zone of mixing this thick, so that a thinner lens is brackish
# to its top.
SEA_WATER_DENSITY_KG_M3 = 1025.0
FRESH_WATER_DENSITY_KG_M3 = 1000.0
LENS_DEPTH_PER_HEAD = FRESH_WATER_DENSITY_KG_M3 / (SEA_WATER_DENSITY_KG_M3 - FRESH_WATER_DENSITY_KG_M3)
MIXING_ZONE_M = 5.0
SECONDS_PER_YEAR = alluvial_channels.SECONDS_PER_YEAR


def _grid(rows, shape, default=0.0):
    """A stored field on ``shape``'s lattice (bilinear), ``default`` where it is missing."""
    try:
        values = np.asarray([getattr(row, "values", row) for row in rows], dtype=np.float64)
    except (TypeError, ValueError):
        values = None
    if values is None or values.ndim != 2 or values.shape[0] < 2 or values.shape[1] < 2:
        return np.full(shape, float(default))
    values = np.where(np.isfinite(values), values, float(default))
    if values.shape == tuple(shape):
        return values
    height, width = shape
    gx = np.linspace(0.0, values.shape[1] - 1.0, width)
    gy = np.linspace(0.0, values.shape[0] - 1.0, height)
    ix = np.minimum(values.shape[1] - 2, gx.astype(int))
    iy = np.minimum(values.shape[0] - 2, gy.astype(int))
    fx = (gx - ix)[None, :]
    fy = (gy - iy)[:, None]
    top = values[iy][:, ix] * (1.0 - fx) + values[iy][:, ix + 1] * fx
    bottom = values[iy + 1][:, ix] * (1.0 - fx) + values[iy + 1][:, ix + 1] * fx
    return top * (1.0 - fy) + bottom * fy


def multiple_flow_accumulation(elevation, sources, sinks, *, dx, dy, inlets=None):
    """Upstream sum of ``sources`` with flow divided among all lower neighbours.

    ``elevation`` is routed after a depression fill, so every cell drains to a
    sink (``sinks``: open water) or off the tile edge; ``inlets`` are edge
    cells that are no outlets.  Returns ``(accumulation, filled)``.  A filled
    depression is level but for the fill's own vanishing gradient towards its
    spill point, so water gathers on its floor before it leaves.
    """
    from simulations.world_gen.drainage import _priority_flood

    elevation = np.asarray(elevation, dtype=np.float64)
    sinks = np.asarray(sinks, dtype=bool)
    height, width = elevation.shape
    filled, _parent, _order = _priority_flood(
        elevation.tolist(), sinks.tolist(), False,
        inlets=None if inlets is None else np.asarray(inlets, dtype=bool),
    )
    filled = np.asarray(filled, dtype=np.float64)
    padded = np.pad(filled, 1, mode="constant", constant_values=np.inf)
    weights = np.zeros((len(_D8_OFFSETS), height, width))
    for index, (row_offset, column_offset) in enumerate(_D8_OFFSETS):
        neighbour = padded[1 + row_offset:1 + row_offset + height, 1 + column_offset:1 + column_offset + width]
        slope = (filled - neighbour) / math.hypot(column_offset * dx, row_offset * dy)
        weights[index] = np.where(slope > 0.0, np.maximum(slope, 0.0) ** MFD_SLOPE_EXPONENT * MFD_CONTOUR[index], 0.0)
    total = weights.sum(axis=0)
    weights = weights / np.where(total > 0.0, total, 1.0)
    weights[:, sinks] = 0.0
    # Highest first: a cell has received all its inflow before it passes it on.
    order = np.argsort(-filled, axis=None, kind="stable").tolist()
    accumulation = np.asarray(sources, dtype=np.float64).ravel().tolist()
    shares = [weights[index].ravel().tolist() for index in range(len(_D8_OFFSETS))]
    steps = [row_offset * width + column_offset for row_offset, column_offset in _D8_OFFSETS]
    for cell in order:
        amount = accumulation[cell]
        if amount <= 0.0:
            continue
        for share, step in zip(shares, steps):
            part = share[cell]
            if part > 0.0:
                accumulation[cell + step] += amount * part
    return np.asarray(accumulation, dtype=np.float64).reshape(height, width), filled


def _landform_record(heightmap):
    for landform in ((heightmap.get("regional_landforms") or {}).get("landforms") or []):
        if isinstance(landform, dict) and landform.get("landform") == alluvial_channels.LANDFORM_ID:
            return landform
    return {}


def _lake_water(water_cycle, elevation, shape, min_fill=0.0, boxes=True, within=None, own_only=False):
    """Depth of the lakes the drainage model retained, on the heightfield's lattice.

    ``min_fill`` leaves out terminal lakes whose runoff keeps less than
    that share of their floor under water (playas, wet only at times).
    ``boxes=False`` leaves out lakes known only as a parent's footprint:
    a level that found no hollow there has no shore to draw, and the box
    shows as water with straight edges.  ``within`` (bool ``[H, W]``) keeps
    such a lake to where the parent had water: its box says only which lake
    it is, and filled to the lake's level it floods every hollow of the
    tile that lies as low, a bar of the river beside it too.  ``own_only``
    leaves out every lake that is the parent's (``parent_lake_level`` tells
    those): only the hollows this level found for itself.
    """
    depth = np.zeros(shape)
    drainage = water_cycle.get("drainage_network_model") if isinstance(water_cycle.get("drainage_network_model"), dict) else {}
    grid_width = int(drainage.get("grid_width", 0) or 0)
    grid_height = int(drainage.get("grid_height", 0) or 0)
    if grid_width < 2 or grid_height < 2:
        return depth
    height, width = shape
    column_of = np.rint(np.arange(width) / max(1, width - 1) * (grid_width - 1)).astype(int)
    row_of = np.rint(np.arange(height) / max(1, height - 1) * (grid_height - 1)).astype(int)
    for lake in water_cycle.get("lakes") or drainage.get("lakes") or []:
        if not isinstance(lake, dict) or lake.get("surface_elevation_m") is None:
            continue
        if own_only and lake.get("inherited_from_parent"):
            continue
        if float(lake.get("terminal_fill_fraction", 1.0) or 0.0) < min_fill:
            continue
        mask = np.zeros((grid_height, grid_width), dtype=bool)
        for cell in lake.get("cells") or []:
            if isinstance(cell, (list, tuple)) and len(cell) >= 2 and 0 <= int(cell[1]) < grid_height and 0 <= int(cell[0]) < grid_width:
                mask[int(cell[1]), int(cell[0])] = True
        if mask.any():
            footprint = mask[row_of][:, column_of]
        else:
            # A lake inherited from the parent comes as its box on this tile.
            if not boxes:
                continue
            bounds = lake.get("bounds") or {}
            if not all(key in bounds for key in ("min_x", "max_x", "min_y", "max_y")):
                continue
            x = np.arange(width) / max(1, width - 1)
            y = np.arange(height) / max(1, height - 1)
            footprint = (
                ((x >= float(bounds["min_x"])) & (x <= float(bounds["max_x"])))[None, :]
                & ((y >= float(bounds["min_y"])) & (y <= float(bounds["max_y"])))[:, None]
            )
            if within is not None:
                footprint = footprint & within
        surface = float(lake["surface_elevation_m"])
        inside = footprint & (elevation < surface)
        depth = np.where(inside, np.maximum(depth, surface - elevation), depth)
    return depth


def _water_margin(water, surface, elevation, dx, dy, reach_m):
    """Wet margin of a water body: 1 at its edge, 0 at ``reach_m`` or a few capillary rises above it.

    ``surface`` holds the water surface on the ``water`` cells.  The margin
    falls linearly with distance and exponentially with the height of the
    ground above the nearest water's level.
    """
    shape = water.shape
    if not water.any():
        return np.zeros(shape)
    # The shore is what matters; interior cells only cost time.
    padded = np.pad(water, 1, mode="edge")
    interior = padded[:-2, 1:-1] & padded[2:, 1:-1] & padded[1:-1, :-2] & padded[1:-1, 2:]
    shore = water & ~interior
    rows, columns = np.nonzero(shore if shore.any() else water)
    index, distance = alluvial_channels.nearest_point_field(
        columns.astype(np.float64) * dx, rows.astype(np.float64) * dy, shape, dx, dy, reach_m,
    )
    found = index >= 0
    level = np.where(found, surface[rows, columns][np.where(found, index, 0)], elevation)
    above = np.maximum(0.0, elevation - level)
    margin = np.clip(1.0 - np.where(found, distance, np.inf) / max(reach_m, 1e-6), 0.0, 1.0)
    return np.where(water, 1.0, margin * np.exp(-above / CAPILLARY_RISE_M))


def hillslope_water_table_depth(topographic_index, recharge_mm):
    """Depth at which the soil mantle passes on the recharge gathered from upslope, in metres (0 where it cannot).

    ``topographic_index`` is ``ln(a / tan(b))`` with ``tan(b)`` the gradient
    the water follows.
    """
    from simulations.world_gen.lithotectonic_settings import box_blur

    # A water table is smoother than the ground above it.
    index = box_blur(_inside_the_rim(np.asarray(topographic_index, dtype=np.float64)), passes=2)
    recharge = np.maximum(LEAST_RECHARGE_MM, np.asarray(recharge_mm, dtype=np.float64)) / 1000.0
    return np.clip((np.log(TRANSMISSIVITY_M2_PER_YEAR / recharge) - index) / CONDUCTIVITY_DECAY_PER_M,
                   0.0, WATER_TABLE_UNKNOWN_M)


def _inside_the_rim(values, cells=RIM_CELLS):
    """``values`` with the outermost cells given what stands just inside them.

    Along a tile's rim the routing gathers what cannot leave where the
    parent's flow does not; that is the tile's edge, not the ground's.
    """
    values = np.array(values, dtype=np.float64)
    if min(values.shape) <= 2 * cells + 1:
        return values
    values[:cells, :], values[-cells:, :] = values[cells, :], values[-cells - 1, :]
    values[:, :cells], values[:, -cells:] = values[:, cells][:, None], values[:, -cells - 1][:, None]
    return values


def _halved(values, weights=None):
    """Means over blocks of two by two cells (weighted where ``weights`` is given), the rim padded to even."""
    rows, columns = values.shape
    pad = ((0, rows % 2), (0, columns % 2))
    values = np.pad(values, pad, mode="edge")
    if weights is None:
        return values.reshape(values.shape[0] // 2, 2, values.shape[1] // 2, 2).mean(axis=(1, 3))
    weights = np.pad(weights.astype(np.float64), pad, mode="edge")
    total = weights.reshape(weights.shape[0] // 2, 2, weights.shape[1] // 2, 2).sum(axis=(1, 3))
    summed = (values * weights).reshape(values.shape[0] // 2, 2, values.shape[1] // 2, 2).sum(axis=(1, 3))
    return np.where(total > 0.0, summed / np.maximum(total, 1e-9), 0.0), total > 0.0


def regional_water_table(water, water_surface, elevation, recharge_mm, dx, dy):
    """Elevation of the water table that drains to the open water of a tile, or ``None`` with no water on it.

    Steady flow through ground of one transmissivity (Dupuit; the scheme Fan
    et al. 2013 run worldwide): the table stands at the water's level where
    there is water, rises between by what recharge piles up, and nowhere
    above the ground, where it seeps out.  No water crosses the tile's rim.
    Solved by relaxation, coarse lattice first.
    """
    if not water.any():
        return None
    source = np.maximum(0.0, np.asarray(recharge_mm, dtype=np.float64)) / 1000.0 / AQUIFER_TRANSMISSIVITY_M2_PER_YEAR
    source = source * np.ones(water.shape)
    pyramid = [(water, np.where(water, water_surface, 0.0), elevation, source, dx, dy)]
    while min(pyramid[-1][0].shape) >= 2 * WATER_TABLE_COARSEST_CELLS:
        fixed, level, ground, recharge, step_x, step_y = pyramid[-1]
        coarse_level, coarse_fixed = _halved(level, fixed)
        pyramid.append((coarse_fixed, coarse_level, _halved(ground), _halved(recharge), step_x * 2.0, step_y * 2.0))
    head = None
    for fixed, level, ground, recharge, step_x, step_y in reversed(pyramid):
        if head is None:
            head, sweeps = np.full(fixed.shape, float(level[fixed].mean())), WATER_TABLE_COARSE_SWEEPS
        else:
            head = np.repeat(np.repeat(head, 2, axis=0), 2, axis=1)[:fixed.shape[0], :fixed.shape[1]]
            sweeps = WATER_TABLE_FINE_SWEEPS
        along, across = 1.0 / (step_x * step_x), 1.0 / (step_y * step_y)
        for _sweep in range(sweeps):
            padded = np.pad(head, 1, mode="edge")
            head = (along * (padded[1:-1, :-2] + padded[1:-1, 2:]) + across * (padded[:-2, 1:-1] + padded[2:, 1:-1])
                    + recharge) / (2.0 * (along + across))
            head = np.where(fixed, level, np.minimum(head, ground))
    return head


def water_table_depth(water, water_surface, elevation, recharge_mm, topographic_index, slope, dx, dy):
    """Depth to the water table in metres under every cell: 0 in water, ``WATER_TABLE_UNKNOWN_M`` out of reach."""
    head = regional_water_table(water, water_surface, elevation, recharge_mm, dx, dy)
    if head is None:
        return hillslope_water_table_depth(topographic_index, recharge_mm)
    above = np.maximum(0.0, elevation - head)
    # The soil's water follows the steeper of the ground's own slope and the fall of the table beneath it: a
    # level terrace above a river drains down and to the river, not along its own surface.
    fall_y, fall_x = np.gradient(head, dy, dx)
    drop = above / np.maximum(_distance_to(water, dx, dy), math.sqrt(dx * dy))
    drained = topographic_index - np.log(np.maximum(np.maximum(np.hypot(fall_x, fall_y), drop), slope) / slope)
    depth = np.minimum(above, hillslope_water_table_depth(drained, recharge_mm))
    return np.where(water, 0.0, np.minimum(depth, WATER_TABLE_UNKNOWN_M))


def tidal_range_m(heightmap):
    """The tidal range the shore of a heightmap was built with, in metres (0 where no landform tells one)."""
    landforms = ((heightmap or {}).get("regional_landforms") or {}).get("landforms") or []
    ranges = [float(landform.get("tidal_range_m") or 0.0) for landform in landforms if isinstance(landform, dict)]
    return max(ranges, default=0.0)


def tidal_ground(sea, elevation, high_water_m):
    """Ground the sea floods at high water: no higher than it, and joined to the sea over ground as low."""
    low = np.asarray(elevation, dtype=np.float64) <= float(high_water_m)
    reached = np.asarray(sea, dtype=bool).copy()
    for _step in range(sum(reached.shape)):
        padded = np.pad(reached, 1, mode="constant")
        grown = low & (padded[:-2, 1:-1] | padded[2:, 1:-1] | padded[1:-1, :-2] | padded[1:-1, 2:] | reached)
        grown |= reached
        if (grown == reached).all():
            break
        reached = grown
    return reached & ~np.asarray(sea, dtype=bool)


def groundwater_salinity(table_elevation, sea, elevation, sea_level, tidal_range=0.0):
    """The share of sea water in the ground water at the table under every cell, or ``None`` on a tile without sea.

    The lens of fresh water under a table ``h`` above the sea is ``(1 +
    LENS_DEPTH_PER_HEAD) h`` thick; one thinner than the zone of mixing is
    salt at its top in proportion.  Ground within reach of the tides, and the
    sea, hold sea water.
    """
    sea = np.asarray(sea, dtype=bool)
    if not sea.any() or sea_level is None:
        return None
    head = np.maximum(0.0, np.asarray(table_elevation, dtype=np.float64) - float(sea_level))
    salt = np.clip(1.0 - (1.0 + LENS_DEPTH_PER_HEAD) * head / MIXING_ZONE_M, 0.0, 1.0)
    flooded = tidal_ground(sea, elevation, float(sea_level) + 0.5 * max(0.0, float(tidal_range)))
    return np.where(sea | flooded, 1.0, salt)


def _distance_to(water, dx, dy):
    """Distance in metres from every cell to the nearest water of the tile, in a straight line."""
    shape = water.shape
    padded = np.pad(water, 1, mode="edge")
    interior = padded[:-2, 1:-1] & padded[2:, 1:-1] & padded[1:-1, :-2] & padded[1:-1, 2:]
    shore = water & ~interior
    rows, columns = np.nonzero(shore if shore.any() else water)
    reach = math.hypot(shape[1] * dx, shape[0] * dy)
    index, distance = alluvial_channels.nearest_point_field(
        columns.astype(np.float64) * dx, rows.astype(np.float64) * dy, shape, dx, dy, reach,
    )
    return np.where(index >= 0, distance, reach)


def _parent_samples(heightmap, parent_heightmap, values, shape):
    """Where a child's lattice lies among a parent raster's samples: ``(ix, iy, fx, fy)``, or ``None``."""
    own, theirs = heightmap.get("source_uv_bounds"), (parent_heightmap or {}).get("source_uv_bounds")
    if not isinstance(own, dict) or not isinstance(theirs, dict) or values.ndim != 2 or min(values.shape) < 2:
        return None
    try:
        span_u, span_v = float(theirs["max_u"]) - float(theirs["min_u"]), float(theirs["max_v"]) - float(theirs["min_v"])
        u0, u1 = (float(own["min_u"]) - float(theirs["min_u"])) / span_u, (float(own["max_u"]) - float(theirs["min_u"])) / span_u
        v0, v1 = (float(own["min_v"]) - float(theirs["min_v"])) / span_v, (float(own["max_v"]) - float(theirs["min_v"])) / span_v
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None
    height, width = shape
    gx = np.clip(u0 + (u1 - u0) * np.arange(width) / max(1, width - 1), 0.0, 1.0) * (values.shape[1] - 1)
    gy = np.clip(v0 + (v1 - v0) * np.arange(height) / max(1, height - 1), 0.0, 1.0) * (values.shape[0] - 1)
    ix, iy = np.minimum(values.shape[1] - 2, gx.astype(int)), np.minimum(values.shape[0] - 2, gy.astype(int))
    return ix, iy, (gx - ix)[None, :], (gy - iy)[:, None]


def _over_child(heightmap, parent_heightmap, values, shape):
    """A raster of the parent's read on a child's lattice, or ``None`` where the two do not say where they lie."""
    samples = _parent_samples(heightmap, parent_heightmap, values, shape)
    if samples is None:
        return None
    ix, iy, fx, fy = samples
    upper = values[iy][:, ix] * (1.0 - fx) + values[iy][:, ix + 1] * fx
    lower = values[iy + 1][:, ix] * (1.0 - fx) + values[iy + 1][:, ix + 1] * fx
    return upper * (1.0 - fy) + lower * fy


def _parent_grids(parent_water_cycle):
    if not isinstance(parent_water_cycle, dict):
        return {}, {}
    runoff, surface = parent_water_cycle.get("runoff_grid"), parent_water_cycle.get("surface_water_grid")
    return (runoff if isinstance(runoff, dict) else {}), (surface if isinstance(surface, dict) else {})


def parent_water_table(heightmap, parent_heightmap, parent_water_cycle, shape):
    """The parent's water table as an elevation on a child's lattice, or ``None`` where the parent tells none.

    Both heightmaps say where they lie (``source_uv_bounds``); the parent's
    table is its ground less its depth to water, and the level of its water
    where it has water.
    """
    runoff, surface = _parent_grids(parent_water_cycle)
    rows = ((parent_heightmap or {}).get("sample_grid") or {}).get("rows") or [] if isinstance(parent_heightmap, dict) else []
    if not runoff.get("water_table_depth_m_rows") or not rows:
        return None
    try:
        ground = np.asarray([getattr(row, "values", row) for row in rows], dtype=np.float64)
        depth = np.asarray(runoff["water_table_depth_m_rows"], dtype=np.float64)
        level = np.asarray([[np.nan if value is None else value for value in row]
                            for row in surface.get("water_surface_elevation_m_rows") or []], dtype=np.float64)
    except (TypeError, ValueError):
        return None
    if ground.ndim != 2 or depth.shape != ground.shape:
        return None
    table = ground - depth
    if level.shape == ground.shape:
        table = np.where(np.isfinite(level), level, table)
    return _over_child(heightmap, parent_heightmap, table, shape)


def parent_run_on(heightmap, parent_heightmap, parent_water_cycle, shape):
    """The parent's run-on on a child's lattice, in millimetres a year, or ``None`` where the parent tells none."""
    runoff, _surface = _parent_grids(parent_water_cycle)
    if not runoff.get("lateral_water_rows_mm") or not isinstance(parent_heightmap, dict):
        return None
    try:
        values = np.asarray(runoff["lateral_water_rows_mm"], dtype=np.float64)
    except (TypeError, ValueError):
        return None
    return _over_child(heightmap, parent_heightmap, values, shape)


def parent_open_water(heightmap, parent_heightmap, parent_water_cycle, shape):
    """Where the parent has open water, to within one of its cells, on a child's lattice; ``None`` where it tells none."""
    _runoff, surface = _parent_grids(parent_water_cycle)
    if not surface.get("water_presence_rows") or not isinstance(parent_heightmap, dict):
        return None
    try:
        values = np.asarray(surface["water_presence_rows"], dtype=np.float64)
    except (TypeError, ValueError):
        return None
    near = _over_child(heightmap, parent_heightmap, values, shape)
    return None if near is None else near > 0.0


def parent_lake_level(heightmap, parent_heightmap, parent_water_cycle, shape):
    """The level of the parent's lakes on a child's lattice, NaN beyond a cell of them; ``None`` where it tells none.

    A lake's level is its parent's to say.  Left to itself a finer tile
    finds the lake's sill again on its own ground, where a notch the parent
    could not see lets the water out lower: an old river channel that held
    two to three metres of water on a Site lay all but dry on its Parcel.
    A finer level draws the shore; it does not drain the lake.  The
    parent's lakes are its still water: not its carved channels and
    streams, and not the sea.
    """
    runoff, surface = _parent_grids(parent_water_cycle)
    if not surface.get("water_surface_elevation_m_rows") or not isinstance(parent_heightmap, dict):
        return None
    try:
        level = np.asarray([[np.nan if value is None else value for value in row]
                            for row in surface["water_surface_elevation_m_rows"]], dtype=np.float64)
        channel = np.asarray(runoff.get("channel_presence_rows") or np.zeros(level.shape), dtype=np.float64)
    except (TypeError, ValueError):
        return None
    samples = _parent_samples(heightmap, parent_heightmap, level, shape)
    if samples is None:
        return None
    lake = np.isfinite(level) & ((channel < 0.5) if channel.shape == level.shape else True)
    sea_level = parent_heightmap.get("sea_level_m")
    if sea_level is not None:
        lake &= level > float(sea_level) + 1e-6
    held = np.where(lake, level, -np.inf)
    ix, iy, _fx, _fy = samples
    # The highest of the parent's lake levels round a cell: its shore may lie anywhere within a parent's cell.
    around = np.maximum(np.maximum(held[iy][:, ix], held[iy][:, ix + 1]), np.maximum(held[iy + 1][:, ix], held[iy + 1][:, ix + 1]))
    return np.where(np.isfinite(around), around, np.nan)


def parent_groundwater_salinity(heightmap, parent_heightmap, parent_water_cycle, shape):
    """The parent's ground-water salinity on a child's lattice, or ``None`` where the parent tells none."""
    runoff, _surface = _parent_grids(parent_water_cycle)
    if not runoff.get("groundwater_salinity_rows") or not isinstance(parent_heightmap, dict):
        return None
    try:
        values = np.asarray(runoff["groundwater_salinity_rows"], dtype=np.float64)
    except (TypeError, ValueError):
        return None
    return _over_child(heightmap, parent_heightmap, values, shape)


def refine_surface_hydrology(heightmap, water_cycle, parent=None):
    """``water_cycle`` with its surface rasters and river list read off a fine heightfield.

    Returns ``water_cycle`` unchanged above ``FINE_HYDROLOGY_MIN_LEVEL`` and
    wherever the inputs are missing.  ``parent`` is ``(heightmap model, water
    cycle model)`` of the map the tile was refined from: where that tells a
    water table, the tile takes it (``parent_water_table``).
    """
    if not isinstance(heightmap, dict) or not isinstance(water_cycle, dict):
        return water_cycle
    level = int(heightmap.get("map_detail_level", 0) or 0)
    rows = (heightmap.get("sample_grid") or {}).get("rows") or []
    if level < FINE_HYDROLOGY_MIN_LEVEL or not rows or not rows[0] or water_cycle.get("status") != "water_cycle_seeded":
        return water_cycle
    elevation = np.asarray([getattr(row, "values", row) for row in rows], dtype=np.float64)
    shape = elevation.shape
    if shape[0] < 3 or shape[1] < 3:
        return water_cycle
    dx = float(heightmap.get("sample_spacing_x_m") or 0.0)
    dy = float(heightmap.get("sample_spacing_y_m") or 0.0)
    if dx <= 0.0 or dy <= 0.0:
        return water_cycle
    cell = math.sqrt(dx * dy)
    sea_level = heightmap.get("sea_level_m")
    ocean = elevation <= float(sea_level) if sea_level is not None else np.zeros(shape, dtype=bool)
    from simulations.world_gen.heightmap import joined_sea_rows

    joined_sea = joined_sea_rows(heightmap, shape)
    if joined_sea is not None:
        # Ground below sea level that land shuts in is a basin, not the sea.
        ocean = ocean & joined_sea
    climate = water_cycle.get("climate_grid") if isinstance(water_cycle.get("climate_grid"), dict) else {}

    # --- open water: carved channels, retained lakes, the sea -------------------
    fields = alluvial_channels.heightmap_channel_fields(heightmap, shape=shape)
    depth = np.zeros(shape)
    channel = np.zeros(shape)
    channel_margin = np.full(shape, np.inf)
    channel_width = np.zeros(shape)
    channel_stage = np.full(shape, np.nan)
    if fields is not None:
        depth = np.where(ocean, 0.0, fields["water_depth"])
        # The section between the banks is the channel; its bars stand dry at
        # mean flow and are flooded at bankfull.
        channel = np.where(fields["in_channel"], np.where(depth > OPEN_WATER_DEPTH_M, 1.0, 0.65), 0.0)
        channel_width = fields["width_m"]
        channel_margin = np.maximum(fields["distance_m"] - 0.5 * channel_width, 0.0)
        channel_stage = fields["stage_m"]
    # Where a thread of water ends: in a carved channel or the sea.  A lake on its way passes it on.
    ends = ocean | (depth > OPEN_WATER_DEPTH_M)
    handed = parent_lake_level(heightmap, *parent, shape) if parent else None
    lake_depth = _lake_water(water_cycle, elevation, shape, own_only=handed is not None,
                             within=parent_open_water(heightmap, *parent, shape) if parent else None)
    if handed is not None:
        # The parent's lakes at the parent's level, on this level's finer ground.
        lake_depth = np.maximum(lake_depth, np.where(np.isfinite(handed), np.maximum(0.0, handed - elevation), 0.0))
    lake_depth = np.where(ocean, 0.0, lake_depth)
    if fields is not None:
        # A carved channel fades out towards a tile's rim, which shuts its trough, and the drainage solver
        # fills it like a lake almost to the banks.  That is no lake: where a river's water stands is its own
        # stage's to say.  Only a lake that stands above the banks drowns the channel.
        trough = fields["in_channel"] & (lake_depth > 0.0) & (elevation + lake_depth <= fields["bank"])
        lake_depth = np.where(trough, 0.0, lake_depth)
    depth = np.maximum(depth, lake_depth)
    if sea_level is not None:
        depth = np.where(ocean, float(sea_level) - elevation, depth)
    water = ocean | (depth > OPEN_WATER_DEPTH_M)

    # --- routing: where the ground sends the water it does not keep -------------
    inflow = inflow_grid(shape, heightmap.get("boundary_inflow"), dx * dy)
    accumulation, filled = multiple_flow_accumulation(
        elevation, 1.0 + inflow, water, dx=dx, dy=dy, inlets=inlet_mask(inflow, shape, dx=dx, dy=dy),
    )
    area_m2 = accumulation * dx * dy
    gradient_y, gradient_x = np.gradient(elevation, dy, dx)
    slope = np.maximum(np.hypot(gradient_x, gradient_y), SLOPE_FLOOR)
    topographic_index = np.log(np.maximum(area_m2, dx * dy) / cell / slope)
    ground = ~water
    if ground.any():
        reference = float(np.median(topographic_index[ground]))
        share = np.exp(np.clip(topographic_index - reference, -REDISTRIBUTION_LOG_SPAN, REDISTRIBUTION_LOG_SPAN))
        share = share / max(1e-9, float(share[ground].mean()))
    else:
        share = np.ones(shape)

    # --- streams too narrow to be carved -----------------------------------------
    record = _landform_record(heightmap)
    runoff = np.maximum(0.0, _grid(climate.get("annual_runoff_rows_mm"), shape))
    runoff_m_s = np.where(ground, runoff, 0.0) / 1000.0 / SECONDS_PER_YEAR
    # One thread of water down the steepest descent, through any lake on its way and over its sill, to the
    # carved channel or the sea.  (With lakes for ends a brook was lost in the first pond it met.)
    receivers = filled_routing(elevation, ~ends, dx=dx, dy=dy, inlets=inlet_mask(inflow, shape, dx=dx, dy=dy))
    thread_area_m2 = upstream_sum(receivers, (1.0 + inflow).ravel())[:, 0].reshape(shape) * dx * dy
    discharge = runoff_m_s * thread_area_m2
    stream = ground & (channel <= 0.0) & (discharge >= MIN_STREAM_DISCHARGE_M3_S)
    if stream.any():
        bankfull_ratio = float(record.get("bankfull_to_mean") or alluvial_channels.BANKFULL_TO_MEAN_DISCHARGE[0])
        geometry = alluvial_channels.bankfull_geometry(
            discharge * bankfull_ratio, slope,
            float(record.get("silt_clay_percent") or alluvial_channels.DEFAULT_SILT_CLAY_PERCENT),
            float(record.get("gravity_m_s2") or 9.80665),
        )
        stream_depth = geometry["depth_m"] * (1.0 / bankfull_ratio) ** alluvial_channels.AT_A_STATION_DEPTH_EXPONENT
        depth = np.where(stream, np.maximum(depth, stream_depth), depth)
        channel = np.where(stream, 1.0, channel)
        channel_width = np.where(stream & (channel_width <= 0.0), geometry["width_m"], channel_width)
        # A stream is water along all of its thread, the riffles where it runs a finger deep too.
        water = water | stream

    # --- wetness ------------------------------------------------------------------
    precipitation = np.maximum(0.0, _grid(climate.get("annual_precipitation_rows_mm"), shape))
    evaporation = np.maximum(0.0, _grid(climate.get("annual_potential_evaporation_rows_mm"), shape, 350.0))
    recharge = np.maximum(0.0, _grid(climate.get("annual_groundwater_recharge_rows_mm"), shape))
    kept = precipitation * PRECIPITATION_SHARE
    mobile = runoff + recharge * RECHARGE_SHARE + kept * PLOT_RUNON_SHARE
    supply = mobile * share + kept * (1.0 - PLOT_RUNON_SHARE)
    climatic = supply / np.maximum(1.0, supply + evaporation)

    near_water = np.zeros(shape)
    if fields is not None:
        above = np.maximum(0.0, elevation - np.where(np.isfinite(channel_stage), channel_stage, elevation))
        reach = np.maximum(WET_MARGIN_CHANNEL_WIDTHS * channel_width, cell)
        margin = np.clip(1.0 - channel_margin / reach, 0.0, 1.0)
        near_water = np.where(np.isfinite(channel_margin), BANK_WETNESS * margin * np.exp(-above / CAPILLARY_RISE_M), 0.0)
    water_surface = elevation + depth
    still = ocean | (lake_depth > OPEN_WATER_DEPTH_M)
    if still.any():
        near_water = np.maximum(
            near_water, BANK_WETNESS * _water_margin(still, water_surface, elevation, dx, dy, WET_MARGIN_STILL_WATER_M))
    if stream.any():
        reach = max(WET_MARGIN_CHANNEL_WIDTHS * float(np.median(channel_width[stream])), 2.0 * cell)
        near_water = np.maximum(near_water, BANK_WETNESS * _water_margin(stream, water_surface, elevation, dx, dy, reach))
    near_water = np.where(water, 1.0, near_water)
    wetness = np.clip(
        WETNESS_BASE + climatic * WETNESS_CLIMATE + channel * WETNESS_CHANNEL + near_water * WETNESS_NEAR_WATER, 0.0, 1.0,
    )

    # --- ground water and run-on, as amounts ---------------------------------------
    inherited = parent_water_table(heightmap, *parent, shape) if parent else None
    if inherited is None:
        table_depth = water_table_depth(water, elevation + depth, elevation, recharge, topographic_index, slope, dx, dy)
    else:
        table_depth = np.where(water, 0.0, np.clip(elevation - inherited, 0.0, WATER_TABLE_UNKNOWN_M))
    # Whose water the ground water is: the sea's under a table that does not stand above it.
    salinity = parent_groundwater_salinity(heightmap, *parent, shape) if parent else None
    if salinity is not None:
        salinity = np.where(ocean, 1.0, np.clip(salinity, 0.0, 1.0))
    else:
        salinity = groundwater_salinity(elevation - table_depth, ocean, elevation, sea_level, tidal_range_m(heightmap))
    inner_share = _inside_the_rim(share)
    ordinary = float(np.median(inner_share[ground])) if ground.any() else 1.0
    lateral = np.where(ground, np.minimum(mobile * (inner_share - ordinary), precipitation * MAX_RUNON_RAINS), 0.0)
    gathered = parent_run_on(heightmap, *parent, shape) if parent else None
    if gathered is not None and ground.any():
        # Finer cells gather the same water into narrower lines; how much of it moves is the parent's to say.
        # A Parcel left to itself moved nearly twice what its Site did over the same ground.
        own_total, parent_total = float(lateral[ground].sum()), float(gathered[ground].sum())
        if own_total > 1e-6 and parent_total >= 0.0:
            lateral = lateral * (parent_total / own_total)

    # --- floods of the carved channel ----------------------------------------------
    floods = None
    if fields is not None:
        bankfull_ratio = float(record.get("bankfull_to_mean") or alluvial_channels.BANKFULL_TO_MEAN_DISCHARGE[0])
        floods = river_floods.flood_fields(heightmap, elevation, bankfull_to_mean=bankfull_ratio, water=water)

    height, width = shape
    surface_rows = np.where(water, elevation + depth, np.nan)
    runoff_grid = {
        "status": "read_from_heightfield",
        "model_version": MODEL_VERSION,
        "width": width,
        "height": height,
        "channel_presence_rows": round_rows(channel, 2),
        "wetness_index_rows": round_rows(wetness, 4),
        "water_table_depth_m_rows": round_rows(table_depth, 2),
        "lateral_water_rows_mm": round_rows(lateral, 1),
        "flow_accumulation_rows": (water_cycle.get("runoff_grid") or {}).get("flow_accumulation_rows") or [],
        "water_table_source": "parent" if inherited is not None else "own",
        "run_on_total_source": "parent" if gathered is not None else "own",
        **({} if salinity is None else {
            "groundwater_salinity_rows": round_rows(salinity, 2),
            "groundwater_salinity_contract": (
                "share of sea water in the ground water at the water table, 0 to 1: a fresh lens thinner than "
                "the zone of mixing is brackish to its top; 1 in the sea and on ground the tides flood"
            ),
        }),
        "wetness_contract": (
            "climate water balance redistributed by the topographic index a/tan(b), plus channel and "
            "open-water proximity by height above the water surface; dimensionless qualitative index"
        ),
    }
    surface_water_grid = {
        "status": "read_from_heightfield",
        "model_version": MODEL_VERSION,
        "width": width,
        "height": height,
        "water_presence_rows": water.tolist(),
        "water_depth_m_rows": round_rows(np.where(water, depth, 0.0), 3),
        "water_surface_elevation_m_rows": [
            [None if not wet else round(value, 3) for value, wet in zip(row, wet_row)]
            for row, wet_row in zip(surface_rows.tolist(), water.tolist())
        ],
        "presence_contract": "sea, retained lakes, carved channels at their mean-flow stage, and streams of real discharge",
        **({} if floods is None else {
            "flood_return_period_rows_years": round_rows(floods["covered_years"], 1),
            "flood_reworking_return_period_rows_years": round_rows(floods["reworked_years"], 1),
            "flood_contract": (
                "years between floods of the carved channel that cover a cell, and between those that stand "
                "deep enough over it to rework its surface; 999 where none reaches"
            ),
        }),
        "depth_contract": "bathymetry for sea and lakes; carved section below the mean-flow stage for channels",
        "seasonal_state": "unresolved; the stage is the mean flow's",
        "salinity": "unresolved",
    }

    carved = None
    if fields is not None:
        carved = np.isfinite(fields["distance_m"]) & (fields["distance_m"] <= 0.5 * fields["width_m"] + 2.0 * cell)

    def is_stream(river):
        """A parent's trunk, or a path of real discharge that is not the carved channel's own bed."""
        if not isinstance(river, dict):
            return False
        if river.get("inherited_from_parent"):
            return True
        if float(river.get("estimated_discharge_m3_s", 0.0) or 0.0) < MIN_STREAM_DISCHARGE_M3_S:
            return False
        points = [point for point in river.get("points") or [] if isinstance(point, dict)]
        if not points:
            return False
        columns = np.clip(np.rint([float(point.get("x", 0.0)) * (shape[1] - 1) for point in points]).astype(int), 0, shape[1] - 1)
        rows_at = np.clip(np.rint([float(point.get("y", 0.0)) * (shape[0] - 1) for point in points]).astype(int), 0, shape[0] - 1)
        # A path along the tile's rim is the solver draining a closed edge
        # (ground that leaves the tile where the parent's flow does not).
        on_rim = (columns == 0) | (columns == shape[1] - 1) | (rows_at == 0) | (rows_at == shape[0] - 1)
        if float(on_rim.mean()) >= 0.5:
            return False
        if carved is None:
            return True
        return float(carved[rows_at, columns].mean()) < 0.5

    listed = [river for river in water_cycle.get("rivers") or [] if isinstance(river, dict)]
    rivers = [river for river in listed if is_stream(river)]
    if carved is not None and np.any(channel > 0.0) and not rivers and listed:
        # The carved channel is a river too: its routed path stands for it
        # (discharge, regime and catchment are read from the river list).
        trunk = max(listed, key=lambda river: float(river.get("estimated_discharge_m3_s", 0.0) or 0.0))
        if float(trunk.get("estimated_discharge_m3_s", 0.0) or 0.0) >= MIN_STREAM_DISCHARGE_M3_S:
            rivers = [{**trunk, "network_role": "carved_channel"}]
    drainage = dict(water_cycle.get("drainage_network_model") or {})
    ephemeral = [river for river in drainage.get("ephemeral_channels") or [] if is_stream(river)]
    dropped = (
        len(water_cycle.get("rivers") or []) - len(rivers)
        + len(drainage.get("ephemeral_channels") or []) - len(ephemeral)
    )
    drainage.update({
        "rivers": rivers,
        "river_segment_count": len(rivers),
        "ephemeral_channels": ephemeral,
        "ephemeral_channel_count": len(ephemeral),
        "unchannelised_flow_path_count": int(dropped),
    })
    land_cells = max(1, int((~ocean).sum()))
    return {
        **water_cycle,
        "drainage_network_model": drainage,
        "runoff_grid": runoff_grid,
        "surface_water_grid": surface_water_grid,
        "rivers": rivers,
        "river_count": len(rivers),
        "fine_surface_hydrology": {
            "model_version": MODEL_VERSION,
            "open_water_cell_fraction": round(float((water & ~ocean).sum()) / land_cells, 5),
            "carved_channel_cell_fraction": round(float((channel > 0.0).sum()) / land_cells, 5),
            "uncarved_stream_cell_fraction": round(float(stream.sum()) / land_cells, 5),
            "unchannelised_flow_path_count": int(dropped),
            "depression_cell_fraction": round(float(((filled - elevation) > 0.02)[ground].mean()) if ground.any() else 0.0, 5),
            "redistribution_share_p05_p50_p95": [round(float(value), 3) for value in np.percentile(share[ground], [5, 50, 95])] if ground.any() else [],
            "capillary_rise_m": CAPILLARY_RISE_M,
            **({} if floods is None else {"floods": floods["summary"]}),
            **({} if salinity is None or not ground.any() else {"salt_ground_water": {
                "tidal_range_m": round(tidal_range_m(heightmap), 2),
                "land_share_brackish": round(float((salinity[~ocean] >= 0.1).mean()) if (~ocean).any() else 0.0, 4),
                "land_share_salt": round(float((salinity[~ocean] >= 0.5).mean()) if (~ocean).any() else 0.0, 4),
            }}),
        },
    }
