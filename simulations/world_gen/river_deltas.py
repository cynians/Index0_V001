"""River deltas: what a river builds where it meets standing water.

A river drops its load where its flow spreads into the sea.  Whether that
makes a delta is a contest between what the river brings and what the waves
at its mouth can carry away along the shore (Galloway 1975; Wright & Coleman
1973), put in one number by Nienhuis, Ashton & Giosan (2015): the fluvial
dominance ``R``, the river's sand flux over the largest flux waves can move
away from the mouth on both sides.

* ``R >= 1``: the river wins.  The sand stays at the mouth and builds out a
  plain, lobe by lobe, into whatever water lies in front: a bay-head delta
  in a drowned valley or a lagoon, a lobate delta on a sheltered coast.
* ``R < 1``: the waves win.  They spread the sand along the coast as fast as
  it comes; the mouth stays a mouth (at most a low cusp, not drawn here) and
  the sand is the beaches' (``shore_deposits``).  This is most rivers on an
  open coast: a few cubic metres of sand a minute against waves that can
  move as much every second.

**The river's load** is the BQART relation of Syvitski & Milliman (2007),
fitted to 488 rivers: ``Qs = 0.02 B Q^0.31 A^0.5 R T`` in kg/s, with the
discharge ``Q`` in km3 a year, the catchment ``A`` in km2, its relief ``R``
in km and its mean temperature ``T`` in degrees Celsius (at least 2);
``B`` (lithology, ice, people) is 1 here.  Of that load the sand and the
coarse silt stay at the mouth (``RETAINED_SHARE``); the mud goes out to sea.

**The waves' capacity** is the CERC relation (Komar & Inman 1970):
``Q = K sqrt(g / gamma) H^2.5 / (16 (s - 1) (1 - p))`` at the most oblique
approach, on either side of the mouth, for the waves of an ordinary day (the
storm height handed down the levels, over ``sea_cliffs.STORM_WIND_FACTOR``).

**The form.**  What the river has brought since the sea came to its level
(``sea_cliffs.STILLSTAND_YEARS``) is laid from the mouth outward as a topset
and a foreset (Gilbert 1885): a plain that rises from the sea at the slope
the river needs to carry sand across it (bankfull Shields stress 1.86 for a
sand bed, Parker et al. 2007: the slope is ``1.86 (s - 1) D / h``), and a
front that falls from the delta's shoreline to the old bed at
``FORESET_GRADIENT``.  Distance is measured through the water from the
mouth, so the body follows a drowned valley round its bends and fills it
from the head, and its outline is whatever the bed in front lets it be: the
volume decides how far the shoreline comes (deep water takes more sand per
metre).  The valley floor behind the mouth is raised to the same plain,
since the river must still reach its delta.

**Lakes.**  A hollow in the ground that a river runs into holds a lake at
its sill wherever the river brings more water than the lake's surface
loses (``build_lake_deltas``).  A lake keeps what a river brings whatever
its waves do with it: there is no coast beyond to carry the sand to, and
the mud settles on its floor (large lakes trap nine tenths and more of
the load, Brune 1953; all of it is laid from the river's entry here).
What comes in the stillstand is often more than the hollow holds: the
lake is then filled to its far shore, a valley floor at the level of
the sill, and the rest of the load goes on down the river (it is not
followed to the next water yet).

Scale gate as for ``alluvial_fans``: a delta is built at the first level
whose cells resolve its radius; its record (global UV) is handed down, and
a level builds none where a coarser one has built.

Abiotic by contract (no marsh, no mangrove; plant-free rivers carry more,
not allowed for).  Not built here: the cusp of a wave-dominated mouth,
tide-dominated deltas (funnels and bars), distributary channels and levees
(a level routes the river over the plain), delta lobes and their
switching, and subsidence.  Water below sea level that land shuts in
is not the sea: a river is routed through it to the open shore (such a
basin would hold a lake at a level of its own, which no level gives it yet).
"""

from __future__ import annotations

import math

import numpy as np

from simulations.world_gen import sea_cliffs

MODEL = "river_mouth_deposits_v1"
LANDFORM_ID = "river_deltas"

# Syvitski & Milliman (2007): Qs = OMEGA B Q^0.31 A^0.5 R T (kg/s; Q km3/yr, A km2, R km, T deg C >= 2).
BQART_OMEGA = 0.02
BQART_DISCHARGE_EXPONENT = 0.31
BQART_AREA_EXPONENT = 0.5
BQART_MIN_TEMPERATURE_C = 2.0
# Share of the load that settles at the mouth: bed load and suspended sand
# and coarse silt.  Stated from memory (deltas keep roughly a third to two
# thirds of what their rivers bring); unverified.
RETAINED_SHARE = 0.4
SEDIMENT_DENSITY_KG_M3 = 2650.0
DEPOSIT_POROSITY = 0.4
# CERC: K for significant wave height, breaker index gamma.
CERC_K = 0.39
BREAKER_INDEX = 0.78
# Bankfull Shields stress of sand-bed rivers (Parker et al. 2007) and the
# sand of a delta plain.
SAND_BED_SHIELDS = 1.86
DELTA_SAND_GRAIN_M = 3.0e-4
TOPSET_GRADIENT_RANGE = (1.0e-4, 5.0e-3)
# Delta front of a sandy delta, about 2 degrees (1 to 5; coarse Gilbert
# fronts stand at 25 and more).  From memory; unverified.
FORESET_GRADIENT = 0.035
# A delta is built where its radius spans this many cells.
RESOLVE_RADIUS_CELLS = 4.0
# Streams below this mean flow build no delta worth a record at any level
# met so far, and are not followed.
MIN_MEAN_DISCHARGE_M3_S = 0.02
# A river keeps its way to the sea open through the beach from this mean flow.
OPEN_MOUTH_DISCHARGE_M3_S = 1.0
DELTA_MIN_LEVEL = 2
# A hollow holds a lake from this depth below its sill and this many cells
# (the drainage model's own floor for regional lakes is 2 m).
LAKE_MIN_DEPTH_M = 2.0
LAKE_MIN_CELLS = 6
LAKE_SHORE_DEPTH_M = 0.05
# Share of a river's load a lake keeps (Brune 1953: over 0.9 for lakes that
# hold more than a tenth of a year's inflow; from memory, unverified).
LAKE_TRAPPED_SHARE = 0.9
# A mouth within this many delta radii of a delta a coarser level built is that delta's.
INHERITED_REACH_RADII = 1.25
# Sediment this thick hides what lies under it.
FULL_COVER_THICKNESS_M = 0.3


def sediment_load_kg_s(discharge_m3_s, catchment_km2, relief_m, temperature_c):
    """BQART: the load a river carries to its mouth (kg/s)."""
    q = np.maximum(np.asarray(discharge_m3_s, dtype=np.float64), 0.0) * _seconds_per_year() / 1.0e9
    area = np.maximum(np.asarray(catchment_km2, dtype=np.float64), 0.0)
    relief = np.maximum(np.asarray(relief_m, dtype=np.float64), 0.0) / 1000.0
    warmth = np.maximum(np.asarray(temperature_c, dtype=np.float64), BQART_MIN_TEMPERATURE_C)
    return BQART_OMEGA * q ** BQART_DISCHARGE_EXPONENT * area ** BQART_AREA_EXPONENT * relief * warmth


def _seconds_per_year():
    from simulations.world_gen.alluvial_channels import SECONDS_PER_YEAR

    return SECONDS_PER_YEAR


def deposit_volume_m3(load_kg_s, years=None):
    """Volume the retained share of a load fills over the stillstand (m3, pore space included)."""
    years = sea_cliffs.STILLSTAND_YEARS if years is None else years
    return (np.asarray(load_kg_s, dtype=np.float64) * RETAINED_SHARE * years * _seconds_per_year()
            / (SEDIMENT_DENSITY_KG_M3 * (1.0 - DEPOSIT_POROSITY)))


def wave_transport_capacity_m3_s(storm_wave_height_m, gravity):
    """Most sand the waves can move away from a river mouth, both sides together (m3/s, pore space included)."""
    height = np.maximum(np.asarray(storm_wave_height_m, dtype=np.float64), 0.0) / sea_cliffs.STORM_WIND_FACTOR
    one_side = (CERC_K * math.sqrt(gravity / BREAKER_INDEX) * height ** 2.5
                / (16.0 * (SEDIMENT_DENSITY_KG_M3 / 1000.0 - 1.0) * (1.0 - DEPOSIT_POROSITY)))
    return 2.0 * one_side


def fluvial_dominance(load_kg_s, storm_wave_height_m, gravity):
    """Nienhuis et al. (2015): the river's sand flux over what the waves can carry away."""
    river = np.asarray(load_kg_s, dtype=np.float64) * RETAINED_SHARE / (SEDIMENT_DENSITY_KG_M3 * (1.0 - DEPOSIT_POROSITY))
    return river / np.maximum(wave_transport_capacity_m3_s(storm_wave_height_m, gravity), 1e-12)


def topset_gradient(bankfull_discharge_m3_s, silt_clay_percent, gravity):
    """Slope a sand-bed river of this bankfull discharge needs across its delta plain."""
    from simulations.world_gen.alluvial_channels import bankfull_geometry

    reach = SAND_BED_SHIELDS * (SEDIMENT_DENSITY_KG_M3 / 1000.0 - 1.0) * DELTA_SAND_GRAIN_M
    slope = 1.0e-3
    for _step in range(4):
        depth = float(np.asarray(bankfull_geometry(bankfull_discharge_m3_s, slope, silt_clay_percent, gravity)["depth_m"]))
        slope = float(np.clip(reach / max(depth, 1e-3), *TOPSET_GRADIENT_RANGE))
    return slope


def delta_surface(distance_m, shoreline_m, topset, sea_level):
    """Height of a delta's surface this far (through the water) from its mouth."""
    distance = np.asarray(distance_m, dtype=np.float64)
    plain = sea_level + topset * (shoreline_m - distance)
    front = sea_level - FORESET_GRADIENT * (distance - shoreline_m)
    return np.where(distance <= shoreline_m, plain, front)


def solve_shoreline_m(distance_m, ground, volume_m3, topset, sea_level, cell_area_m2, limit_m):
    """How far from the mouth the delta's shoreline lies when ``volume_m3`` has been laid down."""
    reached = np.isfinite(distance_m)
    if not reached.any():
        return 0.0

    def laid(shoreline):
        surface = delta_surface(distance_m, shoreline, topset, sea_level)
        return float(np.where(reached, np.maximum(surface - ground, 0.0), 0.0).sum()) * cell_area_m2

    # A basin the delta has filled to its far shore takes no more: the rest of the load goes on.
    low, high = 0.0, min(float(limit_m), float(distance_m[reached].max()))
    if laid(high) <= volume_m3:
        return high
    for _step in range(24):
        middle = 0.5 * (low + high)
        if laid(middle) > volume_m3:
            high = middle
        else:
            low = middle
    return low


def _upstream_max(receivers, values):
    """Largest of ``values`` over each cell and everything upstream of it (pointer doubling)."""
    size = receivers.size
    best = np.asarray(values, dtype=np.float64).ravel().copy()
    pointer = np.append(np.asarray(receivers, dtype=np.int64), size)
    for _round in range(32):
        target = pointer[:size]
        valid = target < size
        if not valid.any():
            break
        carried = best.copy()
        np.maximum.at(carried, target[valid], best[valid])
        best = carried
        pointer[:size] = pointer[target]
    return best


def find_mouths(elevation, open_sea, *, dx, dy, inflow_cells=None):
    """Where streams reach the open sea: ``[(land cell, sea cell, catchment m2, relief m)]``, largest first.

    Flow is routed over the ground with every hollow filled, the open sea
    its only way out besides the tile's edge: water below sea level that
    land shuts in is a pond on the river's way, not its mouth.
    """
    from simulations.world_gen.material_routing import filled_routing, inlet_mask, upstream_sum

    ground = np.asarray(elevation, dtype=np.float64)
    shape = ground.shape
    open_sea = np.asarray(open_sea, dtype=bool)
    land = ~open_sea
    receivers = filled_routing(ground, land, dx=dx, dy=dy, inlets=inlet_mask(inflow_cells, shape, dx=dx, dy=dy))
    sources = np.ones(receivers.size)
    if inflow_cells is not None:
        sources = sources + np.asarray(inflow_cells, dtype=np.float64).ravel()
    area = upstream_sum(receivers, sources)[:, 0] * dx * dy
    size = receivers.size
    flat_sea = open_sea.ravel()
    to_sea = land.ravel() & (receivers < size) & flat_sea[np.minimum(receivers, size - 1)]
    cells = np.flatnonzero(to_sea)
    if not cells.size:
        return [], receivers, area.reshape(shape)
    highest = _upstream_max(receivers, ground)
    order = cells[np.argsort(-area[cells], kind="stable")]
    return [(int(cell), int(receivers[cell]), float(area[cell]), float(highest[cell])) for cell in order], receivers, area.reshape(shape)


def build_deltas(
    elevation, sea_level, *, dx, dy, open_sea, wave_height_m, parent_entity, level, inflow_cells=None, to_uv=None, to_local=None,
    fade=None, inherited=None, max_deltas=12,
):
    """The deltas this level's rivers have built, as a height change.

    ``elevation`` is the ground with the cut shore in it, ``open_sea`` the
    sea the waves come in from (``shore_deposits.open_sea``),
    ``wave_height_m`` the storm waves on every cell, ``inherited`` the
    delta records of coarser levels (their mouths are not built again).

    Returns ``(change, sediment_m, keep_open, record)``: the height change
    (``None`` where no delta is built), the thickness of delta sediment on
    each cell, the water rivers keep open through the beach (bool) and the
    landform record.
    """
    from simulations.world_gen import alluvial_channels

    ground = np.asarray(elevation, dtype=np.float64)
    shape = ground.shape
    sea_level = float(sea_level)
    open_sea = np.asarray(open_sea, dtype=bool)
    inherited = list(inherited or [])
    record = {"landform": LANDFORM_ID, "model": MODEL, "level": int(level), "deltas": [], "inherited_deltas": inherited, "mouths": []}
    keep_open = np.zeros(shape, dtype=bool)
    if int(level) < DELTA_MIN_LEVEL or not open_sea.any() or open_sea.all():
        return None, None, keep_open, record
    runoff_mm, _source = alluvial_channels.parent_runoff_mm(parent_entity)
    if runoff_mm <= 0.0:
        return None, None, keep_open, record
    gravity = alluvial_channels.planet_gravity_m_s2(parent_entity)
    aridity = alluvial_channels.parent_aridity(parent_entity)
    ratio = alluvial_channels.BANKFULL_TO_MEAN_DISCHARGE
    bankfull_ratio = ratio[0] + (ratio[1] - ratio[0]) * aridity
    silt_clay = alluvial_channels.bank_silt_clay_percent(parent_entity)[0]
    temperature_c = _mean_temperature_c(parent_entity)
    mouths, _receivers, _area = find_mouths(ground, open_sea, dx=dx, dy=dy, inflow_cells=inflow_cells)
    spacing = math.sqrt(dx * dy)
    height, width = shape
    waves = np.asarray(wave_height_m, dtype=np.float64)
    change = np.zeros(shape)
    limit = 0.6 * max(height * dy, width * dx)
    taken = [(_local(delta, to_local), float(delta.get("radius_m") or 0.0)) for delta in inherited] if to_local is not None else []
    built = 0
    for land_cell, sea_cell, area_m2, top in mouths:
        discharge = runoff_mm / 1000.0 * area_m2 / alluvial_channels.SECONDS_PER_YEAR
        if discharge < MIN_MEAN_DISCHARGE_M3_S:
            break
        row, column = divmod(sea_cell, width)
        position = (column * dx, row * dy)
        if discharge >= OPEN_MOUTH_DISCHARGE_M3_S:
            width_m = float(np.asarray(alluvial_channels.bankfull_geometry(discharge * bankfull_ratio, 1.0e-3, silt_clay, gravity)["width_m"]))
            reach = max(1.5, 1.0 * width_m / spacing)
            rows = np.arange(height)[:, None] - row
            columns = np.arange(width)[None, :] - column
            keep_open |= (rows * rows + columns * columns) <= reach * reach
        relief = max(top - sea_level, 1.0)
        load = float(sediment_load_kg_s(discharge, area_m2 / 1.0e6, relief, temperature_c))
        wave = float(waves[row, column])
        dominance = float(fluvial_dominance(load, wave, gravity))
        entry = {
            "catchment_km2": round(area_m2 / 1.0e6, 2), "mean_discharge_m3_s": round(discharge, 3), "relief_m": round(relief, 1),
            "sediment_load_kg_s": round(load, 4), "wave_height_m": round(wave, 2), "fluvial_dominance": round(dominance, 3),
        }
        if to_uv is not None:
            u, v = to_uv(np.asarray([position[0]]), np.asarray([position[1]]))
            entry["mouth_u"], entry["mouth_v"] = round(float(u[0]), 10), round(float(v[0]), 10)
        if any(math.hypot(position[0] - centre[0], position[1] - centre[1]) <= max(INHERITED_REACH_RADII * reach_m, 2.0 * spacing) for centre, reach_m in taken):
            entry["regime"] = "on_a_delta"
            record["mouths"].append(entry)
            continue
        if dominance < 1.0:
            entry["regime"] = "wave_dominated"
            record["mouths"].append(entry)
            continue
        if built >= max_deltas:
            break
        volume = float(deposit_volume_m3(load))
        topset = topset_gradient(discharge * bankfull_ratio, silt_clay, gravity)
        surface_now = ground + change
        source = np.zeros(shape, dtype=bool)
        source[row, column] = True
        # Through the water from the mouth; the sand cannot cross the land.
        # And only through water where the river still wins: a delta that
        # has filled its inlet comes out into the waves of the open coast,
        # and there they take its sand alongshore as fast as it arrives.
        reachable = open_sea & (surface_now < sea_level) & (fluvial_dominance(load, waves, gravity) >= 1.0)
        reachable[row, column] = True
        distance = sea_cliffs.cost_distance(np.where(reachable, 1.0, np.inf), source, dx, dy, limit=limit, max_passes=height + width)
        distance = np.where(reachable & (distance <= limit), distance, np.inf)
        shoreline = solve_shoreline_m(distance, surface_now, volume, topset, sea_level, dx * dy, limit)
        entry.update({"regime": "river_dominated", "radius_m": round(shoreline, 1), "topset_gradient": round(topset, 6),
                      "volume_m3": round(volume, 0)})
        if shoreline < RESOLVE_RADIUS_CELLS * spacing:
            # Too small for these cells: a finer level's to build.
            entry["regime"] = "river_dominated_unresolved"
            record["mouths"].append(entry)
            continue
        body = np.where(np.isfinite(distance), np.maximum(delta_surface(distance, shoreline, topset, sea_level) - surface_now, 0.0), 0.0)
        # The valley floor behind the mouth comes up to the plain: through
        # the ground lower than the plain's head, rising inland at its slope.
        head = sea_level + topset * shoreline
        low_land = ~open_sea & (surface_now < head + topset * shoreline)
        valley_source = np.zeros(shape, dtype=bool)
        valley_source[divmod(land_cell, width)] = True
        inland = sea_cliffs.cost_distance(np.where(low_land, 1.0, np.inf), valley_source, dx, dy, limit=limit, max_passes=height + width)
        # No farther up the valley than the delta reaches out to sea.
        inland = np.where(low_land & (inland <= shoreline), inland, np.inf)
        fill = np.where(np.isfinite(inland), np.maximum(head + topset * np.where(np.isfinite(inland), inland, 0.0) - surface_now, 0.0), 0.0)
        # Only ground the plain reaches without a break: the fill ends where the valley floor rises above it.
        joined = sea_cliffs.open_water(fill > 0.0, valley_source)
        body = body + np.where(joined, fill, 0.0)
        if fade is not None:
            body = body * np.asarray(fade, dtype=np.float64)
        if not np.any(body > 0.0):
            record["mouths"].append(entry)
            continue
        change = change + body
        plain = (body > 0.0) & (surface_now + body >= sea_level)
        entry.update({
            "area_km2": round(float(plain.sum()) * dx * dy / 1.0e6, 4),
            "new_land_km2": round(float((plain & (surface_now < sea_level)).sum()) * dx * dy / 1.0e6, 4),
            "max_thickness_m": round(float(body.max()), 2),
            "built_at_level": int(level),
        })
        record["deltas"].append(entry)
        taken.append((position, shoreline))
        built += 1
    if not np.any(change > 0.0):
        return None, None, keep_open, record
    return change, change.copy(), keep_open, record


def build_lake_deltas(
    elevation, *, dx, dy, open_sea, parent_entity, level, inflow_cells=None, to_uv=None, to_local=None, fade=None, inherited=None,
    max_deltas=8,
):
    """The deltas rivers have built into the lakes of this ground, as a height change.

    A lake is a hollow at least ``LAKE_MIN_DEPTH_M`` deep below its sill
    (the level every hollow fills to before it spills); ``open_sea`` is the
    sea, which is no lake.  For the largest river into each lake: the lake
    is full to its sill only if the river brings more water in a year than
    the lake's surface loses (else it is a terminal lake at some lower
    level, and nothing is built); the delta is laid as at the sea, from the
    river's entry through the lake, as far as the load of the stillstand
    goes and no farther than the lake's far shore.  The waves the storm wind
    raises over the lake's length and the fluvial dominance are recorded,
    not acted on: a lake keeps the load either way.

    Returns ``(change, record)``: the height change (``None`` if nothing is
    built) and ``{"deltas": [...], "mouths": [...]}`` in the form of
    ``build_deltas``' record.
    """
    from simulations.world_gen import alluvial_channels
    from simulations.world_gen.drainage import _priority_flood
    from simulations.world_gen.material_routing import d8_receivers, inlet_mask, upstream_sum

    ground = np.asarray(elevation, dtype=np.float64)
    shape = ground.shape
    height, width = shape
    record = {"deltas": [], "mouths": []}
    if int(level) < DELTA_MIN_LEVEL:
        return None, record
    runoff_mm, _source = alluvial_channels.parent_runoff_mm(parent_entity)
    if runoff_mm <= 0.0:
        return None, record
    sea = np.zeros(shape, dtype=bool) if open_sea is None else np.asarray(open_sea, dtype=bool)
    inlets = inlet_mask(inflow_cells, shape, dx=dx, dy=dy)
    filled, _parent, _order = _priority_flood(ground.tolist(), sea.tolist(), False, inlets=None if inlets is None else np.asarray(inlets, dtype=bool))
    filled = np.asarray(filled, dtype=np.float64)
    hollow = ~sea & (filled - ground >= LAKE_MIN_DEPTH_M)
    if int(hollow.sum()) < LAKE_MIN_CELLS:
        return None, record
    # The lake reaches to its shore: the shallows round a hollow belong to it.
    wet = ~sea & (filled - ground > LAKE_SHORE_DEPTH_M)
    receivers, _gradient = d8_receivers(filled, dx=dx, dy=dy, sinks=sea)
    sources = np.ones(receivers.size)
    if inflow_cells is not None:
        sources = sources + np.asarray(inflow_cells, dtype=np.float64).ravel()
    area = upstream_sum(receivers, sources)[:, 0] * dx * dy
    size = receivers.size
    flat_hollow = hollow.ravel()
    entering = ~flat_hollow & (receivers < size) & flat_hollow[np.minimum(receivers, size - 1)]
    cells = np.flatnonzero(entering)
    if not cells.size:
        return None, record
    highest = _upstream_max(receivers, ground)
    gravity = alluvial_channels.planet_gravity_m_s2(parent_entity)
    aridity = alluvial_channels.parent_aridity(parent_entity)
    ratio = alluvial_channels.BANKFULL_TO_MEAN_DISCHARGE
    bankfull_ratio = ratio[0] + (ratio[1] - ratio[0]) * aridity
    silt_clay = alluvial_channels.bank_silt_clay_percent(parent_entity)[0]
    temperature_c = _mean_temperature_c(parent_entity)
    loss_m = _open_water_loss_m(parent_entity)
    wind = sea_cliffs.STORM_WIND_FACTOR * sea_cliffs.storm_wind_m_s(parent_entity)
    spacing = math.sqrt(dx * dy)
    limit = 0.6 * max(height * dy, width * dx)
    taken = [(_local(delta, to_local), float(delta.get("radius_m") or 0.0)) for delta in (inherited or [])] if to_local is not None else []
    change = np.zeros(shape)
    served = np.zeros(shape, dtype=bool)
    for cell in cells[np.argsort(-area[cells], kind="stable")].tolist():
        if len(record["deltas"]) >= max_deltas:
            break
        discharge = runoff_mm / 1000.0 * float(area[cell]) / alluvial_channels.SECONDS_PER_YEAR
        if discharge < MIN_MEAN_DISCHARGE_M3_S:
            break
        entry_cell = int(receivers[cell])
        row, column = divmod(entry_cell, width)
        if served[row, column]:
            continue                                   # a smaller river into a lake already dealt with
        seed = np.zeros(shape, dtype=bool)
        seed[row, column] = True
        lake = sea_cliffs.open_water(wet, seed)
        served |= lake
        if int((lake & hollow).sum()) < LAKE_MIN_CELLS:
            continue
        lake_level = float(filled[row, column])
        lake_area = int(lake.sum()) * dx * dy
        position = (column * dx, row * dy)
        relief = max(float(highest[cell]) - lake_level, 1.0)
        load = float(sediment_load_kg_s(discharge, float(area[cell]) / 1.0e6, relief, temperature_c))
        wave = float(sea_cliffs.fetch_limited_wave_height(math.sqrt(lake_area), wind, gravity))
        dominance = float(fluvial_dominance(load, wave, gravity))
        entry = {
            "receiving": "lake", "catchment_km2": round(float(area[cell]) / 1.0e6, 2), "mean_discharge_m3_s": round(discharge, 3),
            "relief_m": round(relief, 1), "sediment_load_kg_s": round(load, 4), "wave_height_m": round(wave, 2),
            "fluvial_dominance": round(dominance, 3), "lake_level_m": round(lake_level, 2), "lake_area_km2": round(lake_area / 1.0e6, 3),
        }
        if to_uv is not None:
            u, v = to_uv(np.asarray([position[0]]), np.asarray([position[1]]))
            entry["mouth_u"], entry["mouth_v"] = round(float(u[0]), 10), round(float(v[0]), 10)
        if any(math.hypot(position[0] - centre[0], position[1] - centre[1]) <= max(INHERITED_REACH_RADII * reach_m, 2.0 * spacing) for centre, reach_m in taken):
            entry["regime"] = "on_a_delta"
            record["mouths"].append(entry)
            continue
        if discharge * alluvial_channels.SECONDS_PER_YEAR < loss_m * lake_area:
            # Not water enough to keep the hollow full: a terminal lake lower down, or a playa.
            entry["regime"] = "terminal_lake"
            record["mouths"].append(entry)
            continue
        volume = float(deposit_volume_m3(load)) * LAKE_TRAPPED_SHARE / RETAINED_SHARE
        topset = topset_gradient(discharge * bankfull_ratio, silt_clay, gravity)
        surface_now = ground + change
        reachable = lake & (surface_now < lake_level)
        reachable[row, column] = True
        distance = sea_cliffs.cost_distance(np.where(reachable, 1.0, np.inf), seed, dx, dy, limit=limit, max_passes=height + width)
        distance = np.where(reachable & (distance <= limit), distance, np.inf)
        far_shore = float(distance[np.isfinite(distance)].max())
        shoreline = solve_shoreline_m(distance, surface_now, volume, topset, lake_level, dx * dy, limit)
        entry.update({"radius_m": round(shoreline, 1), "topset_gradient": round(topset, 6), "volume_m3": round(volume, 0),
                      "lake_filled": bool(shoreline >= far_shore - 1e-6)})
        if shoreline < RESOLVE_RADIUS_CELLS * spacing:
            entry["regime"] = "river_dominated_unresolved"
            record["mouths"].append(entry)
            continue
        body = np.where(np.isfinite(distance), np.maximum(delta_surface(distance, shoreline, topset, lake_level) - surface_now, 0.0), 0.0)
        # The valley floor behind the entry comes up to the plain, as at the sea.
        head = lake_level + topset * shoreline
        low_land = ~lake & ~sea & (surface_now < head + topset * shoreline)
        valley_source = np.zeros(shape, dtype=bool)
        valley_source[divmod(cell, width)] = True
        inland = sea_cliffs.cost_distance(np.where(low_land, 1.0, np.inf), valley_source, dx, dy, limit=limit, max_passes=height + width)
        inland = np.where(low_land & (inland <= shoreline), inland, np.inf)
        fill = np.where(np.isfinite(inland), np.maximum(head + topset * np.where(np.isfinite(inland), inland, 0.0) - surface_now, 0.0), 0.0)
        body = body + np.where(sea_cliffs.open_water(fill > 0.0, valley_source), fill, 0.0)
        if fade is not None:
            body = body * np.asarray(fade, dtype=np.float64)
        if not np.any(body > 0.0):
            record["mouths"].append(entry)
            continue
        change = change + body
        plain = (body > 0.0) & (surface_now + body >= lake_level)
        entry.update({
            "regime": "lake_delta", "area_km2": round(float(plain.sum()) * dx * dy / 1.0e6, 4),
            "new_land_km2": round(float((plain & lake & (surface_now < lake_level)).sum()) * dx * dy / 1.0e6, 4),
            "max_thickness_m": round(float(body.max()), 2), "built_at_level": int(level),
        })
        record["deltas"].append(entry)
        taken.append((position, shoreline))
    if not np.any(change > 0.0):
        return None, record
    return change, record


def _open_water_loss_m(parent_entity):
    """Depth of water an open surface loses in a year beyond what falls on it (m), from the parent's climate."""
    grid = ((parent_entity or {}).get("water_cycle_model") or {}).get("climate_grid") or {}
    rain = grid.get("annual_precipitation_rows_mm")
    evaporation = grid.get("annual_potential_evaporation_rows_mm")
    if not rain or not evaporation:
        return 0.0
    return max(0.0, float(np.mean(np.asarray(evaporation, dtype=np.float64))) - float(np.mean(np.asarray(rain, dtype=np.float64)))) / 1000.0


def _local(delta, to_local):
    x, y = to_local(np.asarray([float(delta["mouth_u"])]), np.asarray([float(delta["mouth_v"])]))
    return float(x[0]), float(y[0])


def _mean_temperature_c(parent_entity):
    rows = (((parent_entity or {}).get("water_cycle_model") or {}).get("climate_grid") or {}).get("temperature_rows_k")
    if not rows:
        return 15.0
    values = np.asarray(rows, dtype=np.float64)
    return float(np.mean(values[np.isfinite(values)])) - 273.15


# --- what the other layers read ---------------------------------------------------


def delta_record(heightmap):
    for landform in (((heightmap or {}).get("regional_landforms") or {}).get("landforms") or []):
        if isinstance(landform, dict) and landform.get("landform") == LANDFORM_ID:
            return landform
    return None


def heightmap_deltas(heightmap):
    """Every delta a level knows (its own and inherited)."""
    record = delta_record(heightmap)
    if record is None:
        return []
    return list(record.get("inherited_deltas") or []) + list(record.get("deltas") or [])


def with_sediment_grid(record, sediment_m, inherited_m=None):
    """``record`` with the thickness of delta sediment on every cell packed into it (own and inherited)."""
    from simulations.world_gen.shore_deposits import _pack

    grids = [np.asarray(grid, dtype=np.float64) for grid in (sediment_m, inherited_m) if grid is not None]
    if not grids:
        return record
    total = np.maximum.reduce(grids) if len(grids) > 1 else grids[0]
    top = float(total.max()) if total.size else 0.0
    if top <= 0.0:
        return record
    record = dict(record)
    record["sediment"] = {"shape": [int(total.shape[0]), int(total.shape[1])], "max_m": round(top, 3), "data": _pack(total, top)}
    return record


def record_sediment_m(record):
    from simulations.world_gen.shore_deposits import _unpack

    packed = (record or {}).get("sediment")
    if not isinstance(packed, dict) or not packed.get("data"):
        return None
    return _unpack(packed["data"], tuple(int(value) for value in packed["shape"]), float(packed["max_m"]))


def inherited_sediment_m(parent_heightmap, u, v):
    """The parent's delta sediment at this level's cells (``u, v`` global), or ``None``."""
    sediment = record_sediment_m(delta_record(parent_heightmap))
    bounds = (parent_heightmap or {}).get("source_uv_bounds")
    if sediment is None or not bounds:
        return None
    return sea_cliffs._sample_grid(sediment, bounds, u, v)


def heightmap_delta_fields(heightmap, shape=None):
    """``{"thickness", "cover", "front"}`` of delta sediment on a heightmap's grid, or ``None``.

    ``front`` is 1 where the sediment lies under water (the sandy delta
    front) and 0 on the plain (overbank fines over sand).
    """
    sediment = record_sediment_m(delta_record(heightmap))
    if sediment is None or (shape is not None and tuple(shape) != sediment.shape):
        return None
    rows = ((heightmap or {}).get("sample_grid") or {}).get("rows") or []
    sea_level = (heightmap or {}).get("sea_level_m")
    front = np.zeros(sediment.shape)
    if rows and sea_level is not None:
        ground = np.asarray(rows, dtype=np.float64)
        if ground.shape == sediment.shape:
            front = (ground < float(sea_level)).astype(np.float64)
    return {"thickness": sediment, "cover": np.clip(sediment / FULL_COVER_THICKNESS_M, 0.0, 1.0), "front": front}
