"""Scale-specific landforms added during regional refinement.

Each landform becomes complete at one level of detail -- the first whose
sample spacing resolves it -- and is added there as a bounded residual on
the inherited surface; deeper levels inherit it through their parent.  All
parameters come from the planet's physical state (plate kinematics, slab
age, climate, rock), and all positions are global and seeded by the root
map seed, so sibling tiles agree and the same planet always gets the same
volcanoes.

Landforms: LOD1 volcanic arcs, LOD2-4 rock cliffs, ramparts and benches of a
layered sequence (``rock_scarps``: each level cuts the bed order it resolves
and steps its parent's again; the order it cuts is held to the ground around
it and leaves water gaps where the parent's rivers cross,
``hold_scarps_to_ground``),
LOD2+ the shore waves have cut (``sea_cliffs``), the deltas rivers have built
into sheltered water (``river_deltas``) and the beaches waves have laid
(``shore_deposits``),
LOD2+ alluvial fans at mountain fronts (``alluvial_fans``), LOD4+ alluvial river
channels (meandering or braided, ``alluvial_channels``) and the relic channels
of their floodplains (``floodplain_relics``); each fan, channel or order of
relic channel is built at the first level that resolves it.

The residual is made zero-mean at the parent's sample spacing (the child
still box-filters to its parent) and fades out at the tile edge like every
other child detail.  Fans (catchment erosion) and channels (natural levees)
conserve their own volume.  ``apply_regional_landforms`` returns the residual
so the parent-height contract can bound generic detail around it rather than
clip a physically sized landform.
"""

from __future__ import annotations

import math
import numpy as np

from simulations.world_gen import alluvial_channels, alluvial_fans, floodplain_relics, river_deltas, rock_scarps, scarp_canyons, sea_cliffs, shore_deposits
from simulations.world_gen.exact_rounding import height_decimals
from simulations.world_gen.map_seed import seed_range

# --- LOD1: volcanic arcs -----------------------------------------------------
VOLCANIC_ARC_LEVEL = 1
# Slab depth beneath arc volcanoes (Syracuse & Abers 2006: 72-173 km, ~100).
SLAB_DEPTH_UNDER_ARC_M = 110_000.0
# Along-arc volcano spacing (de Bremond d'Ars et al. 1995: ~30-100 km).
ARC_VOLCANO_SPACING_M = (50_000.0, 85_000.0)
# Share of arc positions without a large edifice (gaps, eroded centres).
ARC_GAP_FRACTION = 0.18
# Mean flank slope of a stratovolcano over its whole edifice (steep upper
# cone, gentle apron): basal radius = height / tan(slope).
STRATOVOLCANO_MEAN_SLOPE_DEG = 10.0


# --- LOD2-4: scarps of a layered sequence (``rock_scarps``) -------------------
CAPROCK_LEVEL = 2
# Shores are cut back from Region scale: a platform is tens to hundreds of
# metres wide, a Macroregion cell kilometres.
SEA_CLIFF_LEVEL = 2
LAYERED_FABRICS = frozenset({"bedded", "jointed_volcanic"})
# Rocks laid down as beds or flows (bedded chert and limestone report a
# "massive" fabric in the ontology but still come in beds).
LAYERED_FORMATION_HINTS = ("sedimentary_basin", "extrusive", "volcanic", "volcaniclastic")
# Height above sea level over which the scarps fade in.
COASTAL_STRATA_CLEARANCE_M = 60.0
# Share of its height above the sea that land keeps whatever a scarp or a canyon cuts.
BASE_LEVEL_SHARE = 0.15
# A hollow the steps deepen by less than this is left (the flood's own tilt across a flat is finer still).
OUTLET_HOLD_TOLERANCE_M = 0.01
# Roles of a material layer that name rock in place (not cover, not a
# mineral of a rock, not a scattered deposit).
ROCK_LAYER_ROLES = frozenset({"bedrock", "local_lithology"})


def _parent_rock_mix(parent_entity):
    """(material, areal fraction, erodibility, fabric, slope resistance) of the parent's rocks."""
    layers = ((parent_entity or {}).get("material_heatmap_model") or {}).get("layers") or []
    # The rock under the mantle, not the mantle: a saprolite or dune cover
    # says nothing about the beds beneath it.
    layers = [layer for layer in layers if layer.get("distribution_role") in ROCK_LAYER_ROLES] or layers
    if not layers:
        return []
    from simulations.world_gen.mechanical_lithology import mechanical_profile_for_material
    from simulations.world_gen.natural_materials import natural_material_entries

    try:
        catalog = {entry.get("id"): entry for entry in natural_material_entries()}
    except RuntimeError:  # no ontology material catalog configured
        return []
    mix = []
    for layer in layers:
        fraction = float(layer.get("mean_fraction") or layer.get("coverage_fraction") or 0.0)
        if fraction <= 0.0:
            continue
        profile = mechanical_profile_for_material(catalog.get(layer.get("material_id")) or {})
        fabric = str(profile.get("fabric") or "")
        category = str(layer.get("formation_category") or "")
        if any(hint in category for hint in LAYERED_FORMATION_HINTS):
            fabric = "bedded" if fabric not in LAYERED_FABRICS else fabric
        mix.append((
            str(layer.get("material_id")), fraction, float(profile["erodibility_index"]), fabric,
            float(profile["slope_resistance_index"]),
        ))
    return mix


def _parent_aridity(parent_entity):
    """Aridity (0 humid .. 1 hyper-arid) from the parent's P/PET."""
    grid = ((parent_entity or {}).get("water_cycle_model") or {}).get("climate_grid") or {}
    precipitation = grid.get("annual_precipitation_rows_mm")
    evaporation = grid.get("annual_potential_evaporation_rows_mm")
    if not precipitation or not evaporation:
        return 0.5
    index = float(np.mean(np.asarray(precipitation, dtype=np.float64))) / max(1.0, float(np.mean(np.asarray(evaporation, dtype=np.float64))))
    return 1.0 / (1.0 + (index / 0.3) ** 2)


def _layered_rocks(mix):
    """``([(material, share, erodibility, slope resistance)], layered share)`` of a rock mix."""
    total = sum(item[1] for item in mix)
    layered = [
        (material, fraction, erodibility, resistance)
        for material, fraction, erodibility, fabric, resistance in mix if fabric in LAYERED_FABRICS
    ]
    return layered, sum(item[1] for item in layered) / max(1e-9, total)


def _stack_bed_rocks(parent_entity, storage_root, u, v, ground, structure, level, seed, land, layered):
    """``{bed id: material}``: each bed of the order this level builds takes the rock the rock map draws on it.

    The rock map draws a bed's rock cell by cell from the local composition
    (``strata.bed_materials``, a formation changes facies across a tile); a
    scarp profile needs one rock per bed.  The bed's rock is the one most of
    its exposed cells draw from the parent's layered rocks, so cliffs and rock
    map agree and a child, whose composition is its parent's, keeps them.
    ``None`` without the parent's rasters.
    """
    if storage_root is None or not isinstance(parent_entity, dict):
        return None
    from simulations.world_gen import strata as stack
    from simulations.world_gen.material_heatmaps import load_parent_composition
    from simulations.world_gen.material_lod import _parent_composition_sampler

    parent = load_parent_composition(parent_entity.get("material_heatmap_model"), storage_root)
    if parent is None:
        return None
    material_ids, composition = _parent_composition_sampler(parent)(u % 1.0, v)
    allowed = {item[0] for item in layered}
    keep = [index for index, material_id in enumerate(material_ids) if material_id in allowed]
    if not keep:
        return None
    ids = [material_ids[index] for index in keep]
    shares = composition[keep]
    shares = shares / np.maximum(shares.sum(axis=0), 1e-9)[None]
    order = rock_scarps.BED_ORDER[int(level)]
    depth = np.asarray(structure, dtype=np.float64) - np.asarray(ground, dtype=np.float64)
    drawn, beds_by_order = stack.bed_materials(depth, shares, ids, order=order, seed=seed)
    beds = beds_by_order[order][land]
    drawn = drawn[land]
    if beds.size == 0:
        return None
    pairs, counts = np.unique(np.stack([beds, drawn]), axis=1, return_counts=True)
    rocks = {}
    best = {}
    for (bed, material), count in zip(pairs.T, counts):
        if count > best.get(int(bed), 0):
            best[int(bed)] = int(count)
            rocks[int(bed)] = ids[int(material)]
    return rocks


def _parent_regolith_depth_m(parent_entity):
    """Mean depth of the parent's soil on its ground (0 without a soil model)."""
    rows = (((parent_entity or {}).get("regolith_soil_model") or {}).get("grid") or {}).get("soil_depth_m_rows")
    if not rows:
        return 0.0
    depth = np.asarray(rows, dtype=np.float64)
    ground = depth > 0.0
    return float(depth[ground].mean()) if ground.any() else 0.0


def _parent_tidal_range_m(parent_entity):
    """Mean tidal range along the parent's coast (0 without a coastal model)."""
    segments = ((parent_entity or {}).get("coastal_geomorphology_model") or {}).get("segments") or []
    ranges = [float((segment.get("tidal_regime") or {}).get("estimated_range_m") or 0.0) for segment in segments if isinstance(segment, dict)]
    return float(np.mean(ranges)) if ranges else 0.0


def _open_sea(ground, sea_level, parent_entity, u, v, waves, offshore):
    """The water that is the sea's on this ground: joined to the parent's open sea."""
    joined = sea_cliffs.joined_sea(parent_entity, ground < sea_level, u, v)
    return joined if joined is not None else shore_deposits.open_sea(ground, sea_level, waves, offshore)


def hold_above_base_level(change, elevation, sea_level):
    """``change`` with no land taken lower than a share of its height above the sea.

    Benches and canyons are cut by water that runs to the sea: down
    towards its level, never under it.  The bed-set remap knows nothing of
    that (its weight fades with the height of the ground it starts from,
    not of the bench it cuts to): on one Region tile it took 52 km2 of
    coast that stood 20 to 89 m above the sea down to as much as 52 m
    below it, two basins behind the shore that every later step then had
    to make sense of as sea, as lakes, or as ground to fill.  Land keeps
    at least ``BASE_LEVEL_SHARE`` of its height above the sea, so what is
    cut down to base level is a low plain with the relief it had, not a
    flat.
    """
    ground = np.asarray(elevation, dtype=np.float64)
    change = np.asarray(change, dtype=np.float64)
    above = ground - float(sea_level)
    floor = float(sea_level) + BASE_LEVEL_SHARE * np.maximum(above, 0.0)
    return np.where(above >= 0.0, np.maximum(change, np.minimum(floor - ground, 0.0)), change)


def depth_under_outlet(elevation, sea_level=None):
    """How far each cell lies under the level its water leaves at (m): 0 on ground that drains.

    Water leaves to ground below sea level and over the tile's rim; a
    closed hollow fills to its sill first.
    """
    from simulations.world_gen.drainage import _priority_flood

    ground = np.asarray(elevation, dtype=np.float64)
    outlets = np.zeros(ground.shape, dtype=bool) if sea_level is None else ground < float(sea_level)
    filled, _parent, _order = _priority_flood(ground.tolist(), outlets.tolist(), False)
    return np.asarray(filled, dtype=np.float64) - ground


def hold_above_outlets(change, elevation, sea_level=None):
    """``change`` with no ground left deeper under its outlet than it was; and the cells raised.

    The ground the steps start from drains: the dissection before them
    leaves no closed hollow.  The bed-set remap lowers a tread behind its
    own lip and raises a bed across a valley, and knows nothing of the
    water that crosses them: on an arid Region tile it left 45 hollows,
    9 km2, up to 10 m deep, on ground that had none of 2 m, and the
    lake step then stood lakes in them.  A stream cuts its gap through a
    riser as fast as the riser comes to stand out, and a cell cannot hold
    the gap, so the ground behind comes up level with the lip.  A hollow
    the ground had already keeps the depth it had.
    """
    ground = np.asarray(elevation, dtype=np.float64)
    change = np.asarray(change, dtype=np.float64)
    if ground.ndim != 2 or min(ground.shape) < 3 or not np.any(change):
        return change, 0
    deeper = depth_under_outlet(ground + change, sea_level) - depth_under_outlet(ground, sea_level)
    raised = deeper > OUTLET_HOLD_TOLERANCE_M
    if not raised.any():
        return change, 0
    return change + np.where(raised, deeper, 0.0), int(raised.sum())


def _near(mask, cells):
    """Cells within about ``cells`` of ``mask`` (bool)."""
    from simulations.world_gen.material_routing import gaussian_blur

    return gaussian_blur(np.asarray(mask, dtype=np.float64), max(1.0, 0.5 * float(cells))) > 1e-3


# --- benches held to their ground, and the gaps rivers keep through them -------
# Radii (cells) the ground round a step is read on (``hold_scarps_to_ground``),
# from one cell to the longest scarp run a level builds
# (``rock_scarps.RUN_GATE_PARENT_CELLS``), geometric.
RUN_WINDOW_STEPS = 10


def _running_extreme(values, radius, pick):
    """``pick`` (``np.maximum`` / ``np.minimum``) over the ``2 radius + 1`` rows centred on each row (edge rows repeated)."""
    if radius <= 0:
        return values
    padded = np.concatenate([np.repeat(values[:1], radius, axis=0), values, np.repeat(values[-1:], radius, axis=0)])
    window = 2 * radius + 1
    span, width = padded, 1
    while 2 * width <= window:
        span = pick(span[:-width], span[width:])
        width *= 2
    # ``span[i]`` covers ``padded[i:i + width]``; two overlapping spans cover a window.
    count = values.shape[0]
    return pick(span[:count], span[window - width:window - width + count])


def _window_extreme(values, radius_y, radius_x, pick):
    """``pick`` of ``values`` over a ``(2 radius_y + 1) x (2 radius_x + 1)`` window round each cell."""
    values = np.asarray(values, dtype=np.float64)
    return _running_extreme(_running_extreme(values, int(radius_y), pick).T, int(radius_x), pick).T


def _parent_river_area_m2(parent_entity):
    """Catchment of the smallest river the parent draws (m2); ``None`` without river records."""
    rivers = (((parent_entity or {}).get("water_cycle_model") or {}).get("drainage_network_model") or {}).get("rivers") or []
    areas = [float(river.get("catchment_area_km2") or 0.0) for river in rivers if isinstance(river, dict)]
    areas = [area for area in areas if area > 0.0]
    return 1.0e6 * min(areas) if areas else None


def water_gap_corridor(ground, land, *, dx, dy, inflow=None, parent_entity=None):
    """Where the rivers the parent carries cross this level's ground: ``(cells, record)``.

    A river older than the scarps it crosses keeps its course through them.
    Either it was there before the beds were etched out, on a surface above
    them or a cover since stripped, and was let down onto them across their
    strike (superposed drainage), or it cut down as fast as they rose
    (antecedent drainage: Powell 1875 on the Green River through the Uinta
    Mountains; Davis 1889 on the water gaps of the Susquehanna and the
    Delaware through the Appalachian ridges; Oberlander 1965 on the Zagros).
    Etching a bench out of a bed sequence takes the lowering of the weak beds
    around it, and a river cuts down through the strong bed in its path at
    least as fast, so the bench stands on either side of the river and never
    across it: a water gap.  Only rivers big enough to keep pace do; a small
    stream on a growing barrier is defeated and turned along it (Burbank et
    al. 1996; Humphrey & Konrad 2000).  The rivers taken are those the parent
    carries: as big as the smallest river it records (its scale's rivers were
    there before this level's benches were), routed over this level's ground
    before the steps (it drains) with the water ``inflow`` brings over the
    tile's edges, so a gap lies where this level's river runs.  A gap's floor
    is the river's channel at bankfull, as for a canyon (``scarp_canyons``):
    hydraulic geometry of ``alluvial_channels`` from the discharge of each
    river's own catchment (an inflow entry's catchment runoff where the record
    has it).  ``(None, record)`` when the parent records no river.  The
    references were entered from memory, unverified against the papers.
    """
    from simulations.world_gen.material_routing import box_mean, d8_receivers, filled_routing, inflow_grid, inlet_mask, upstream_sum

    ground = np.asarray(ground, dtype=np.float64)
    land = np.asarray(land, dtype=bool)
    threshold = _parent_river_area_m2(parent_entity)
    record = {"parent_river_area_km2": None if threshold is None else round(threshold / 1.0e6, 3), "river_cells": 0, "gap_cells": 0}
    if threshold is None or not land.any():
        return None, record
    shape = ground.shape
    cell = float(dx) * float(dy)
    extra = inflow_grid(shape, inflow, cell)
    receivers = filled_routing(ground, land, dx=dx, dy=dy, inlets=inlet_mask(extra, shape, dx=dx, dy=dy))
    runoff_mm = alluvial_channels.parent_runoff_mm(parent_entity)[0]
    # Runoff each cell sends down (mm over a cell), with what each entry brings at its own catchment's runoff.
    sent = np.full(shape, float(runoff_mm))
    entries = (inflow or {}).get("cells") if isinstance(inflow, dict) else None
    means = ((inflow or {}).get("catchment_means_mm") or {}).get("runoff") if isinstance(inflow, dict) else None
    for index, (x, y, area_m2) in enumerate(entries or []):
        if 0 <= int(y) < shape[0] and 0 <= int(x) < shape[1]:
            mm = means[index] if means and index < len(means) and means[index] is not None else runoff_mm
            sent[int(y), int(x)] += float(area_m2) / cell * float(mm)
    totals = upstream_sum(receivers, np.stack([1.0 + extra.ravel(), sent.ravel()], axis=1))
    area = totals[:, 0].reshape(shape) * cell
    river = land & (area >= threshold)
    record["river_cells"] = int(river.sum())
    if not river.any():
        return None, record
    aridity = alluvial_channels.parent_aridity(parent_entity)
    ratio = alluvial_channels.BANKFULL_TO_MEAN_DISCHARGE
    _receivers, gradient = d8_receivers(ground, dx=dx, dy=dy, sinks=~land)
    width = alluvial_channels.bankfull_geometry(
        totals[:, 1].reshape(shape) * cell / 1000.0 / alluvial_channels.SECONDS_PER_YEAR * (ratio[0] + (ratio[1] - ratio[0]) * aridity),
        np.clip(box_mean(gradient, 2), 1e-5, 0.2), alluvial_channels.bank_silt_clay_percent(parent_entity)[0],
        alluvial_channels.planet_gravity_m_s2(parent_entity),
    )["width_m"]
    # Cells either side of a river cell its floor reaches (the cell itself spans half a cell each way).
    reach = np.where(river, np.ceil(np.maximum(0.5 * width / min(dx, dy) - 0.5, 0.0)), -1).astype(int)
    gap = np.zeros(shape, dtype=bool)
    for radius in np.unique(reach[river]):
        gap |= _window_extreme(reach == radius, radius, radius, np.maximum) > 0.0
    record.update({
        "gap_cells": int(gap.sum()),
        "largest_river_km2": round(float(area[river].max()) / 1.0e6, 1),
        "widest_gap_floor_m": round(float(width[river].max()), 1),
    })
    return gap, record


def hold_scarps_to_ground(built, ground, land, strata, *, u, v, dx, dy, gap=None):
    """An order's steps held to the ground around them, with the parent's rivers through them: ``(built, strata, record)``.

    The steps of a bed sequence are relief the beds give the ground, not
    relief added to it.  Where the ground cuts across beds of unequal
    strength, the weak beds are stripped and the strong ones left standing:
    a cuesta (a steep scarp facing up the dip, a dip slope behind) where the
    beds dip gently, a hogback where they dip steeply, mesas and benches
    where they lie flat (Davis 1899; Thornbury 1954); in front of the scarp
    the weak bed is cut down to a strike vale, drained by subsequent streams
    to the river that crosses the bench (Jukes 1862).  ``rock_scarps`` lays
    each scarp out for the slope at which the ground cuts the beds, as if
    that slope ran through the scarp's whole run (bench middle to bench
    middle): a step moves a cell to the level the ground reaches
    ``change / slope`` away, up the slope for a cap, down it for a foot.
    Where the slope does not run on (a flexure of the stack under a planed
    plain, where the ground cuts the beds steeply for a cell or two and
    hardly at all beside it), the ground there is not at that level: the
    remap stood a cap the ground reaches nowhere up as a wall over the plain,
    with a groove under the plain at its foot (on one Region tile a 150 km
    wall 100 m high and a groove 60 m deep, the wall damming a 2,500 km2
    lake).  So within that reach of each cell:

    * nothing is cut below the lowest ground.  A weak bed is stripped down
      to the level the drainage around it has reached, never below it (base
      level: Powell 1875); the foot of a scarp is a vale at the level of the
      ground around it, not a moat.
    * nothing stands above the highest ground unless the ground there cuts
      the beds up to the level it stands at.  Erosion etches out rock the
      surface reaches (Gilbert 1877, differential erosion): a hogback of a
      bed that crops out stands over the plain, a cap the ground reaches
      nowhere around it does not.

    On a slope that runs through its scarps the ground within reach is
    always that high and low, and the staircase stands as laid out.

    ``gap`` (``water_gap_corridor``) are cells where a river keeps its
    course: no step at all.  The order's record keeps where it shows (its
    ``weight``) on a coarse grid that every finer level, rockfall and the
    rock, soil and colour layers read, so the holds are written into that
    weight: each node takes the least any cell its interpolation reaches
    allows, and the steps are scaled to the held record (they are linear in
    it), which makes a gap at least as wide as the record's nodes are apart.
    ``ground`` is the ground the order was cut into (``build_order``'s
    ``elevation``).
    """
    from simulations.world_gen.material_routing import gaussian_blur

    built = np.asarray(built, dtype=np.float64)
    ground = np.asarray(ground, dtype=np.float64)
    land = np.asarray(land, dtype=bool)
    shape = ground.shape
    dip, weight, slope = rock_scarps.record_fields(strata, u, v)
    # As ``build_order`` reads the ground: dip-corrected and smoothed.
    relative = gaussian_blur(ground - dip, rock_scarps.SMOOTHING_CELLS)
    reach = np.abs(built) / np.maximum(slope, 1e-9) / min(dx, dy)
    spacing = float(strata.get("parent_spacing_m") or 0.0)
    longest = rock_scarps.RUN_GATE_PARENT_CELLS[1] * spacing / min(dx, dy) if spacing > 0.0 else 0.25 * max(shape)
    radii = sorted({int(radius) for radius in np.ceil(np.geomspace(1.0, max(1.0, min(longest, max(shape))), RUN_WINDOW_STEPS))})
    chosen = np.searchsorted(radii, np.clip(reach, 1.0, radii[-1]))
    highest, lowest, reached = np.empty(shape), np.empty(shape), np.empty(shape)
    for index, radius in enumerate(radii):
        here = chosen == index
        if not here.any():
            continue
        highest[here] = _window_extreme(np.where(land, ground, -np.inf), radius, radius, np.maximum)[here]
        lowest[here] = _window_extreme(np.where(land, ground, np.inf), radius, radius, np.minimum)[here]
        reached[here] = _window_extreme(np.where(land, relative, -np.inf), radius, radius, np.maximum)[here]
    # The ground around cuts the beds up to the level a step puts a cell at (to the record's centimetres).
    cropped_out = relative + built <= reached + 0.01
    held = np.clip(built, np.minimum(lowest - ground, 0.0), np.where(cropped_out, np.inf, np.maximum(highest - ground, 0.0)))
    moving = land & (np.abs(built) > 1e-6)
    keep = np.where(moving, np.clip(held / np.where(moving, built, 1.0), 0.0, 1.0), 1.0)
    if gap is not None:
        keep = np.where(gap, 0.0, keep)
    nodes = np.asarray(strata["weight"], dtype=np.float64)
    rows = np.unique(np.linspace(0, shape[0] - 1, min(rock_scarps.WEIGHT_RECORD_CELLS + 1, shape[0])).round().astype(int))
    columns = np.unique(np.linspace(0, shape[1] - 1, min(rock_scarps.WEIGHT_RECORD_CELLS + 1, shape[1])).round().astype(int))
    allowed = _window_extreme(
        keep, math.ceil((shape[0] - 1) / max(1, rows.size - 1)), math.ceil((shape[1] - 1) / max(1, columns.size - 1)), np.minimum,
    )[np.ix_(rows, columns)]
    held_strata = dict(strata, weight=np.round(nodes * allowed, 3).tolist())
    _dip, held_weight, _slope = rock_scarps.record_fields(held_strata, u, v)
    result = np.where(weight > 1e-12, built * held_weight / np.maximum(weight, 1e-12), 0.0)
    lowered = np.minimum(built, 0.0) - np.minimum(result, 0.0)
    raised = np.maximum(built, 0.0) - np.maximum(result, 0.0)
    in_gap = moving & (gap if gap is not None else np.zeros(shape, dtype=bool))
    record = {
        "cells_held_to_the_ground_around": int(np.sum(moving & (keep < 0.999) & ~in_gap)),
        "foot_lowering_taken_back_m": round(float(-lowered.min()), 2) if lowered.size else 0.0,
        "crest_raising_taken_back_m": round(float(raised.max()), 2) if raised.size else 0.0,
        "gap_cells_on_a_step": int(in_gap.sum()),
        "step_height_in_gaps_m": round(float(np.abs(built[in_gap]).max()), 2) if in_gap.any() else 0.0,
    }
    return result, held_strata, record


def _scarp_audit(strata, inherited, change):
    """Diagnostics entry of one bed order (the record finer levels and other layers read)."""
    faces = [rock_scarps.face_gradient(bed[3]) for bed in strata["beds"]]
    strong = sorted({material for material, face in zip(strata["bed_materials"], faces) if face > 0.0})
    angles = [round(math.degrees(math.atan(face)), 1) for face in faces if face > 0.0]
    return {
        "landform": rock_scarps.LANDFORM_ID,
        "built_at_level": int(strata["built_at_level"]),
        "inherited": bool(inherited),
        "bed_count": len(strata["beds"]),
        "bed_thickness_m": list(rock_scarps.BED_THICKNESS_M.get(int(strata["built_at_level"]), ())),
        "cliff_forming_beds": strong,
        "face_angle_deg": [min(angles), max(angles)] if angles else [],
        "exposed_face_share": strata["exposure"],
        "rampart_angle_deg": round(math.degrees(math.atan(strata["rampart_gradient"])), 1),
        "bed_order": int(strata.get("bed_order", 0)),
        "structure_relief_m": round(float(np.ptp(np.asarray(strata["structure"], dtype=np.float64))), 1),
        "max_change_m": round(float(np.abs(change).max()), 2) if change is not None else 0.0,
        "strata": strata,
    }


def _wrapped_delta(a, b):
    delta = (np.asarray(a, dtype=np.float64) - b) % 1.0
    return np.where(delta > 0.5, delta - 1.0, delta)


def _local_metres(u, v, center_u, center_v, circumference_m):
    """East/south offsets (m) from a centre on the sphere (arrays ok)."""
    mean_latitude = (0.5 - 0.5 * (np.asarray(v, dtype=np.float64) + center_v)) * math.pi
    east = _wrapped_delta(u, center_u) * circumference_m * np.maximum(0.05, np.cos(mean_latitude))
    south = (np.asarray(v, dtype=np.float64) - center_v) * circumference_m * 0.5
    return east, south


def _offset_uv(u, v, east_m, south_m, circumference_m):
    latitude = (0.5 - v) * math.pi
    return (
        (u + east_m / (circumference_m * max(0.05, math.cos(latitude)))) % 1.0,
        min(0.999, max(0.001, v + south_m / (circumference_m * 0.5))),
    )


def _box_mean(values, radius):
    from simulations.world_gen.material_routing import box_mean

    return box_mean(values, max(1, int(radius)))


def slab_dip_deg(slab_age_myr):
    """Older, colder, denser slabs sink more steeply (~25 deg young, ~60 old)."""
    return min(62.0, max(22.0, 22.0 + 0.3 * float(slab_age_myr)))


_ARC_CACHE = {}


def arc_volcanoes(tectonic_model, circumference_m):
    """Global list of arc stratovolcanoes on the overriding side of every trench."""
    spreading = tectonic_model.get("seafloor_spreading_model") or {}
    # Slab age (from the spreading model) sets the dip and so the arc's
    # distance from the trench: a regional tectonic snapshot without it must
    # not share the planet's cache entry.
    key = (
        str(tectonic_model.get("map_seed") or ""),
        len(tectonic_model.get("boundary_segments") or []),
        round(float(circumference_m), 1),
        len(tectonic_model.get("plates") or []),
        bool(spreading),
        round(float(spreading.get("rate_scale", 1.0) or 1.0), 6),
    )
    if key not in _ARC_CACHE:
        _ARC_CACHE[key] = _build_arc_volcanoes(tectonic_model, key[0], float(circumference_m))
    return _ARC_CACHE[key]


def _build_arc_volcanoes(tectonic_model, map_seed, circumference_m):
    from simulations.world_gen.seafloor_spreading import seafloor_age_myr
    from simulations.world_gen.tectonics import _nearest_plate_index

    plates = tectonic_model.get("plates") or []
    plate_index = {plate.get("id"): index for index, plate in enumerate(plates)}
    spreading = tectonic_model.get("seafloor_spreading_model") or {}
    rate_scale = float(spreading.get("rate_scale", 1.0) or 1.0)
    volcanoes = []
    for number, segment in enumerate(tectonic_model.get("boundary_segments") or []):
        if segment.get("kind") != "subduction":
            continue
        overriding = segment.get("overriding_plate")
        if overriding not in plate_index:
            continue
        x1, y1 = float(segment["x1"]), float(segment["y1"])
        x2, y2 = float(segment["x2"]), float(segment["y2"])
        mid_u = (x1 + float(_wrapped_delta(x2, x1)) * 0.5) % 1.0
        mid_v = (y1 + y2) * 0.5
        east, south = _local_metres(x2, y2, x1, y1, circumference_m)
        length = float(math.hypot(float(east), float(south)))
        if length < 1.0:
            continue
        tangent = (float(east) / length, float(south) / length)
        normal = (-tangent[1], tangent[0])
        # Which side is the overriding plate?
        probe_u, probe_v = _offset_uv(mid_u, mid_v, normal[0] * 60_000.0, normal[1] * 60_000.0, circumference_m)
        if _nearest_plate_index(probe_u, probe_v, plates) != plate_index[overriding]:
            normal = (-normal[0], -normal[1])
        # Slab age where it enters the trench (on the subducting side).
        slab_u, slab_v = _offset_uv(mid_u, mid_v, -normal[0] * 100_000.0, -normal[1] * 100_000.0, circumference_m)
        slab_age = seafloor_age_myr(spreading, slab_u, slab_v)
        slab_age = 60.0 if slab_age is None else slab_age
        dip = math.radians(slab_dip_deg(slab_age))
        arc_distance = SLAB_DEPTH_UNDER_ARC_M / math.tan(dip)
        # Magma supply grows with the rate at which slab enters the mantle.
        convergence_cm_year = abs(float(segment.get("normal_velocity_cm_year", 0.0) or 0.0)) * rate_scale
        seed = f"{map_seed}:arc:{number}"
        spacing = seed_range(map_seed, f"{seed}:spacing", *ARC_VOLCANO_SPACING_M)
        position = seed_range(map_seed, f"{seed}:phase", 0.0, 1.0) * spacing
        index = 0
        while position < length:
            tag = f"{seed}:{index}"
            if seed_range(map_seed, f"{tag}:gap", 0.0, 1.0) >= ARC_GAP_FRACTION:
                across = arc_distance * seed_range(map_seed, f"{tag}:across", 0.85, 1.15)
                along = position - length * 0.5
                east_m = tangent[0] * along + normal[0] * across
                south_m = tangent[1] * along + normal[1] * across
                center_u, center_v = _offset_uv(mid_u, mid_v, east_m, south_m, circumference_m)
                height = min(3600.0, (1300.0 + 260.0 * convergence_cm_year) * seed_range(map_seed, f"{tag}:size", 0.65, 1.25))
                volcanoes.append({
                    "u": center_u,
                    "v": center_v,
                    "height_m": height,
                    "radius_m": height / math.tan(math.radians(STRATOVOLCANO_MEAN_SLOPE_DEG)),
                    "slab_age_myr": round(slab_age, 1),
                    "slab_dip_deg": round(math.degrees(dip), 1),
                    "trench_distance_m": round(across, 0),
                })
            index += 1
            position += spacing * seed_range(map_seed, f"{tag}:step", 0.8, 1.2)
    return volcanoes


def _volcanic_arc_residual(u, v, tectonic_model, circumference_m):
    return _stratovolcano_cones(u, v, arc_volcanoes(tectonic_model, circumference_m), circumference_m)


def _stratovolcano_cones(u, v, volcanoes, circumference_m):
    residual = np.zeros(u.shape, dtype=np.float64)
    used = []
    u_min, u_max = float(u.min()), float(u.max())
    v_min, v_max = float(v.min()), float(v.max())
    for volcano in volcanoes:
        reach_v = volcano["radius_m"] / (circumference_m * 0.5)
        reach_u = reach_v * 2.0 / max(0.05, math.cos((0.5 - volcano["v"]) * math.pi))
        du = float(_wrapped_delta(volcano["u"], (u_min + u_max) * 0.5))
        if abs(du) > (u_max - u_min) * 0.5 + reach_u or not (v_min - reach_v <= volcano["v"] <= v_max + reach_v):
            continue
        east, south = _local_metres(u, v, volcano["u"], volcano["v"], circumference_m)
        radius = np.hypot(east, south) / volcano["radius_m"]
        # Concave stratovolcano profile (steep summit, broad apron) with a
        # small summit crater.
        cone = volcano["height_m"] * np.clip(1.0 - radius, 0.0, 1.0) ** 2
        cone -= volcano["height_m"] * 0.04 * np.exp(-((radius / 0.05) ** 2))
        residual = np.maximum(residual, cone)
        used.append(volcano)
    return residual, used


# Edifice thickness above which the caprock remap no longer applies.
EDIFICE_MASK_HEIGHT_M = 60.0


def _smooth01(values):
    values = np.clip(values, 0.0, 1.0)
    return values * values * (3.0 - 2.0 * values)


def _inherited_arc_edifices(u, v, parent_entity):
    """Heights of the parent's arc volcanoes on this grid (its landform record)."""
    heightmap = (parent_entity or {}).get("heightmap_model") or {}
    circumference_m = float(heightmap.get("planet_circumference_m") or 0.0)
    volcanoes = [
        volcano
        for landform in ((heightmap.get("regional_landforms") or {}).get("landforms") or [])
        if isinstance(landform, dict) and landform.get("landform") == "volcanic_arc"
        for volcano in landform.get("volcanoes") or []
    ]
    if not volcanoes or circumference_m <= 0.0:
        return None
    edifice, used = _stratovolcano_cones(u, v, volcanoes, circumference_m)
    return edifice if used else None


def apply_regional_landforms(
    rows,
    inherited_rows,
    *,
    level,
    sea_level,
    source_bounds,
    spacing_x_m,
    spacing_y_m,
    parent_spacing_m,
    root_planet,
    parent_entity=None,
    inflow=None,
    storage_root=None,
):
    """Add the landforms that become complete at this level.

    ``inflow`` is the heightmap's ``boundary_inflow`` (catchment that rivers
    bring into the tile); ``storage_root`` where the parent's rasters are
    (its rock composition gives each scarp bed the rock the rock map draws).
    Returns ``(rows, residual_rows, diagnostics)``.
    """
    elevation = np.asarray(rows, dtype=np.float64)
    height, width = elevation.shape
    u0, u1 = float(source_bounds["min_u"]), float(source_bounds["max_u"])
    v0, v1 = float(source_bounds["min_v"]), float(source_bounds["max_v"])
    u = (u0 + (u1 - u0) * np.arange(width)[None, :] / max(1, width - 1)) * np.ones((height, 1))
    v = (v0 + (v1 - v0) * np.arange(height)[:, None] / max(1, height - 1)) * np.ones((1, width))
    tectonic_model = (root_planet or {}).get("tectonic_model") or {}
    heightmap = (root_planet or {}).get("heightmap_model") or {}
    circumference_m = float(
        heightmap.get("circumference_m")
        or ((root_planet or {}).get("terrain_seed_model") or {}).get("map_canvas", {}).get("circumference_m")
        or 40_075_000.0
    )
    residual = np.zeros(elevation.shape, dtype=np.float64)
    diagnostics = {"level": int(level), "landforms": []}

    if int(level) == VOLCANIC_ARC_LEVEL and tectonic_model.get("boundary_segments"):
        arc, used = _volcanic_arc_residual(u % 1.0, v, tectonic_model, circumference_m)
        if used:
            residual += arc
            diagnostics["landforms"].append({
                "landform": "volcanic_arc",
                "volcano_count": len(used),
                "max_height_m": round(max(item["height_m"] for item in used), 0),
                "slab_dip_deg": sorted({item["slab_dip_deg"] for item in used}),
                "trench_distance_km": round(sum(item["trench_distance_m"] for item in used) / len(used) / 1000.0, 1),
                # Children read the edifices from here (strict parent lineage).
                "volcanoes": [
                    {"u": round(float(item["u"]), 10), "v": round(float(item["v"]), 10),
                     "height_m": round(float(item["height_m"]), 1), "radius_m": round(float(item["radius_m"]), 1)}
                    for item in used
                ],
            })

    # Scarps of a layered sequence (``rock_scarps``): the orders the parent
    # carries are stepped again at this grid, then this level cuts the order
    # its own cells resolve.  Both keep the parent's mean height themselves
    # (a scarp raises the ground above its brink by what it lowers below its
    # foot), so they are added after the box mean below, like fans and channels.
    scarps = np.zeros(elevation.shape, dtype=np.float64)
    land = elevation >= float(sea_level) if sea_level is not None else np.ones(elevation.shape, dtype=bool)
    carried = []
    canyon_floor = canyon_cut = None
    from simulations.world_gen.regional_refinement import PARENT_EDGE_FADE_FRACTION

    # What a level adds or takes away fades out at the tile rim, where the
    # child is its parent.
    across = np.arange(width) / max(1, width - 1)
    down = np.arange(height) / max(1, height - 1)
    rim_fade = _smooth01(
        np.minimum(np.minimum(across, 1.0 - across)[None, :], np.minimum(down, 1.0 - down)[:, None]) / PARENT_EDGE_FADE_FRACTION)
    if int(level) > CAPROCK_LEVEL:
        sharpening, carried, order_steps = rock_scarps.restep(
            (parent_entity or {}).get("heightmap_model"), u, v, np.asarray(inherited_rows, dtype=np.float64), int(level),
            with_steps=True,
        )
        if sharpening is not None:
            # A sharpened face is new detail: at the tile rim the child is its
            # parent (and its neighbour, which re-steps the same records).
            scarps = np.where(land, sharpening * rim_fade, 0.0)
        # Streams cut back into the scarps the parent built: there a scarp
        # was a cell wide and a canyon narrower than a cell; here both are
        # resolved.  The rock is gone with the stream, so nothing is given
        # back around a canyon.
        for strata, steps in zip(carried, order_steps):
            if int(strata.get("built_at_level", 0)) != int(level) - 1:
                continue
            from simulations.world_gen.material_routing import inflow_grid

            aridity = alluvial_channels.parent_aridity(parent_entity)
            ratio = alluvial_channels.BANKFULL_TO_MEAN_DISCHARGE
            canyons, canyon_floor, record = scarp_canyons.cut_canyons(
                elevation + scarps - steps, steps, land, strata, u=u, v=v, dx=spacing_x_m, dy=spacing_y_m,
                inflow_cells=inflow_grid(elevation.shape, inflow, spacing_x_m * spacing_y_m),
                fade=rim_fade, sea_level=sea_level,
                discharge={
                    "runoff_m_s": alluvial_channels.parent_runoff_mm(parent_entity)[0] / 1000.0 / alluvial_channels.SECONDS_PER_YEAR,
                    "bankfull_ratio": ratio[0] + (ratio[1] - ratio[0]) * aridity,
                    "silt_clay_percent": alluvial_channels.bank_silt_clay_percent(parent_entity)[0],
                    "gravity_m_s2": alluvial_channels.planet_gravity_m_s2(parent_entity),
                },
            )
            diagnostics["landforms"].append(record)
            if canyons is not None:
                canyon_cut = canyons
                scarps = scarps + canyons
        # Orders too old to be stepped again stay listed: their faces are in
        # the inherited relief, and rock, soil and colour still read them.
        for strata in rock_scarps.heightmap_orders((parent_entity or {}).get("heightmap_model")):
            stepped = any(strata is young for young in carried)
            diagnostics["landforms"].append({**_scarp_audit(strata, True, scarps if stepped else None), "stepped_again": stepped})
    if int(level) in rock_scarps.BED_ORDER:
        mix = _parent_rock_mix(parent_entity)
        layered, layered_share = _layered_rocks(mix) if mix else ([], 0.0)
        if layered and layered_share >= rock_scarps.MIN_LAYERED_SHARE:
            # New detail fades out at the tile rim, like every other child detail.
            shows = rim_fade
            if sea_level is not None:
                # Base level: ground at sea level must not move (a wall or a
                # pit on every shore cell); scarps fade out over the last
                # metres above the sea.
                shows = shows * _smooth01((elevation - float(sea_level)) / COASTAL_STRATA_CLEARANCE_M)
            edifice = _inherited_arc_edifices(u % 1.0, v, parent_entity)
            if edifice is not None:
                # Arc volcanoes are younger constructional cones on top of the
                # layered sequence; their flows dip with the flanks, so flat
                # beds cut them into concentric terraces.
                shows = shows * (1.0 - _smooth01(edifice / EDIFICE_MASK_HEIGHT_M))
            # The planet's stack (``strata``): its beds and the horizon that
            # rock uplift, basins and folds hold up are the same on every map.
            from simulations.world_gen import strata as stack
            from simulations.world_gen.material_heatmaps import planet_circumference_m

            # Below the first level ``root_planet`` is withheld (children read
            # their parent's records); the parent's tectonic snapshot holds
            # the planet's boundary segments and its seed is the planet's.
            source = root_planet if isinstance(root_planet, dict) and root_planet else (parent_entity or {})
            stack_tectonics = source.get("tectonic_model") or {}
            seed_text = stack.planet_strata_seed(source)
            forcing = None
            if stack_tectonics.get("boundary_segments"):
                from simulations.world_gen.heightmap import cached_orogen_forcing_grid

                forcing = cached_orogen_forcing_grid(u[0, :] % 1.0, v[:, 0], stack_tectonics)
            structure = stack.reference_horizon(
                u % 1.0, v, tectonic_model=stack_tectonics,
                circumference_m=planet_circumference_m(source.get("heightmap_model"), source.get("terrain_seed_model"), source),
                seed=seed_text, cell_m=max(spacing_x_m, spacing_y_m), forcing=forcing,
            )
            order_arguments = dict(
                level=int(level), layered=layered, layered_share=layered_share,
                aridity=_parent_aridity(parent_entity), seed_text=seed_text, bounds=source_bounds,
                dx=spacing_x_m, dy=spacing_y_m, parent_spacing_m=float(parent_spacing_m or 0.0),
                weight=shows, coarser=carried[-1] if carried else None,
                regolith_depth_m=_parent_regolith_depth_m(parent_entity), structure=structure,
                bed_rocks=_stack_bed_rocks(
                    parent_entity, storage_root, u, v, elevation + scarps, structure, level, seed_text, land, layered,
                ),
            )
            built, strata = rock_scarps.build_order(elevation + scarps, land, **order_arguments)
            if built is not None:
                # Rivers the parent carries keep their courses through the
                # beds, and no step stands over or sinks under the ground
                # around it that the beds do not give it.
                gap, gap_record = water_gap_corridor(
                    elevation + scarps, land, dx=spacing_x_m, dy=spacing_y_m, inflow=inflow, parent_entity=parent_entity)
                built, strata, held_record = hold_scarps_to_ground(
                    built, elevation + scarps, land, strata, u=u, v=v, dx=spacing_x_m, dy=spacing_y_m, gap=gap)
                scarps = scarps + built
                audit = _scarp_audit(strata, False, built)
                audit["water_gaps"] = {**gap_record, **{key: held_record.pop(key) for key in ("gap_cells_on_a_step", "step_height_in_gaps_m")}}
                audit["held_to_the_ground_around"] = held_record
                audit["layered_share"] = round(layered_share, 3)
                audit["aridity"] = round(float(_parent_aridity(parent_entity)), 3)
                if edifice is not None:
                    audit["volcanic_edifice_cells_exempt"] = int(np.sum(edifice > EDIFICE_MASK_HEIGHT_M))
                diagnostics["landforms"].append(audit)
    if sea_level is not None:
        scarps = hold_above_base_level(scarps, elevation, float(sea_level))
    scarps, held_cells = hold_above_outlets(scarps, elevation, sea_level)
    if held_cells:
        diagnostics["cells_held_above_their_outlet"] = held_cells
    orders = rock_scarps.heightmap_orders({"regional_landforms": diagnostics})

    # The shore waves have cut into the land (``sea_cliffs``): a platform at
    # sea level and the cliff behind it, further back in weak rock and
    # under high waves.  Like a canyon it takes rock away for good.
    shore_cut = cliff_rock = None
    shore_waves = shore_offshore = None
    cleared = canyon_floor
    if sea_level is not None and int(level) >= SEA_CLIFF_LEVEL:
        coast = elevation + scarps
        sea = coast < float(sea_level)
        if sea.any() and not sea.all():
            waves, offshore, wave_record = sea_cliffs.wave_heights(
                parent_entity, sea, u, v, spacing_m=min(spacing_x_m, spacing_y_m),
                parent_spacing_m=float(parent_spacing_m or 0.0), gravity=alluvial_channels.planet_gravity_m_s2(parent_entity),
            )
            if waves is not None:
                # Known on every cell: the beach reads them on ground the cut has drowned.
                shore_waves = sea_cliffs.spread_from_sea(waves, sea, 96)
                shore_offshore = offshore
            mix = _parent_rock_mix(parent_entity)
            strength, _held = sea_cliffs.rock_at(
                np.full(elevation.shape, float(sea_level)), sea_cliffs.shore_orders(orders), u, v, mix)
            if waves is not None and strength is not None:
                shore_cut, platform, record = sea_cliffs.cut_shore(
                    coast, float(sea_level), dx=spacing_x_m, dy=spacing_y_m, strength_mpa=strength, wave_height_m=waves,
                    offshore_wave_height_m=offshore, tidal_range_m=_parent_tidal_range_m(parent_entity), fade=rim_fade,
                )
                record["waves"] = wave_record
                diagnostics["landforms"].append(record)
                if shore_cut is not None:
                    scarps = scarps + shore_cut
                    # The sea clears what falls onto the platform and into it.
                    cleared = platform | sea if cleared is None else cleared | platform | sea
                    # The cliff stands in the rock at its own height, drawn scarps or not.
                    near = _near(platform, float(-shore_cut.min()) / (0.5 * min(spacing_x_m, spacing_y_m)))

                    def cliff_rock(ground, near=near, mix=mix):
                        return np.where(near, sea_cliffs.rock_at(ground, orders, u, v, mix)[1], np.inf)

    if (orders and np.any(scarps)) or shore_cut is not None:
        # Nothing stands steeper than its rock holds: what the steps left
        # steeper fails and comes to rest at the foot.  A canyon floor is
        # kept clear by its stream, a shore platform by the sea.
        stepped = elevation + scarps
        rested = rock_scarps.rockfall(stepped, orders, u, v, spacing_x_m, spacing_y_m, held=cleared, also=cliff_rock)
        # What falls fades out at the tile rim like everything this level
        # adds: there the ground is the parent's, and the neighbour tile's.
        rested = stepped + (rested - stepped) * rim_fade
        rested = np.where(land, rested, stepped)
        diagnostics["rockfall_max_m"] = round(float(np.abs(rested - stepped).max()), 2)
        scarps = scarps + (rested - stepped)

    if shore_waves is not None and shore_cut is not None:
        # What is laid down faces the sea the cut has left: a cove the waves
        # have opened is sheltered water now, and the level below will find
        # it so.  With the waves of the shore before the cut, a child raised
        # its parent's berms in such coves (3 % of the land of one Site tile).
        cut_sea = (elevation + scarps) < float(sea_level)
        waves, offshore, _record = sea_cliffs.wave_heights(
            parent_entity, cut_sea, u, v, spacing_m=min(spacing_x_m, spacing_y_m),
            parent_spacing_m=float(parent_spacing_m or 0.0), gravity=alluvial_channels.planet_gravity_m_s2(parent_entity),
        )
        if waves is not None:
            shore_waves, shore_offshore = sea_cliffs.spread_from_sea(waves, cut_sea, 96), offshore

    # River mouths (``river_deltas``): where a river outdoes the waves at its
    # mouth its load has built a delta into the water in front; elsewhere
    # the mouth is only kept open through the beach.
    keep_open = None
    if int(level) >= river_deltas.DELTA_MIN_LEVEL:
        from simulations.world_gen.material_routing import inflow_grid

        parent_heightmap = (parent_entity or {}).get("heightmap_model")
        _dx, _dy, to_local, to_uv = alluvial_channels.local_frame(
            {"source_uv_bounds": source_bounds, "sample_spacing_x_m": spacing_x_m, "sample_spacing_y_m": spacing_y_m},
            elevation.shape,
        )
        inflow_cells = inflow_grid(elevation.shape, inflow, spacing_x_m * spacing_y_m)
        handed_down = river_deltas.heightmap_deltas(parent_heightmap)
        with_sea = sea_level is not None and shore_waves is not None

        def the_sea():
            if not with_sea:
                return np.zeros(elevation.shape, dtype=bool)
            return _open_sea(elevation + scarps, float(sea_level), parent_entity, u, v, shore_waves, shore_offshore)

        # Lakes first: a river that fills a hollow on its way reaches the sea over the fill.
        in_lakes, lake_record = river_deltas.build_lake_deltas(
            elevation + scarps, dx=spacing_x_m, dy=spacing_y_m, open_sea=the_sea(), parent_entity=parent_entity, level=int(level),
            inflow_cells=inflow_cells, to_uv=to_uv, to_local=to_local, fade=rim_fade, inherited=handed_down,
        )
        sediment = in_lakes
        if in_lakes is not None:
            scarps = scarps + in_lakes
        record = {"landform": river_deltas.LANDFORM_ID, "model": river_deltas.MODEL, "level": int(level), "deltas": [],
                  "inherited_deltas": handed_down, "mouths": []}
        if with_sea:
            delta, at_sea, keep_open, record = river_deltas.build_deltas(
                elevation + scarps, float(sea_level), dx=spacing_x_m, dy=spacing_y_m, open_sea=the_sea(),
                wave_height_m=shore_waves, parent_entity=parent_entity, level=int(level),
                inflow_cells=inflow_cells, to_uv=to_uv, to_local=to_local,
                fade=rim_fade, inherited=handed_down + lake_record["deltas"],
            )
            record["inherited_deltas"] = handed_down
            if delta is not None:
                scarps = scarps + delta
                sediment = at_sea if sediment is None else np.maximum(sediment, at_sea)
        record["deltas"] = lake_record["deltas"] + record["deltas"]
        record["mouths"] = lake_record["mouths"] + record["mouths"]
        diagnostics["landforms"].append(river_deltas.with_sediment_grid(
            record, sediment, river_deltas.inherited_sediment_m(parent_heightmap, u, v)))

    # The beach (``shore_deposits``): sand on the shoreface, in the coves and
    # at the cliff foot, laid on the shore the waves have cut and rockfall
    # has left.  Sand comes from beyond the cell: nothing is taken back.
    if shore_waves is not None:
        below = shore_deposits.inherited_sand_m((parent_entity or {}).get("heightmap_model"), u, v)
        if below is not None:
            below = shore_deposits.sand_within_reach(
                below, elevation + scarps, float(sea_level), float(np.max(shore_waves)), _parent_tidal_range_m(parent_entity))
        beach, sand, record = shore_deposits.build_shore(
            elevation + scarps, float(sea_level), dx=spacing_x_m, dy=spacing_y_m, wave_height_m=shore_waves,
            offshore_wave_height_m=shore_offshore, tidal_range_m=_parent_tidal_range_m(parent_entity), fade=rim_fade,
            parent_spacing_m=float(parent_spacing_m or 0.0), sand_below_m=below, keep_open=keep_open,
            open_sea=_open_sea(elevation + scarps, float(sea_level), parent_entity, u, v, shore_waves, shore_offshore),
        )
        diagnostics["landforms"].append(shore_deposits.with_sand_grid(record, sand if beach is not None else below))
        if beach is not None:
            scarps = scarps + beach

    # Landforms that conserve their own volume (fans: catchment erosion;
    # channels: levees) skip the box mean below, which would only print its
    # square window around them.  Fans come first; channels route over them.
    conserved = np.zeros(elevation.shape, dtype=np.float64)
    if int(level) >= min(alluvial_fans.FAN_MIN_LEVEL, alluvial_channels.CHANNEL_PLANFORM_MIN_LEVEL):
        land = elevation >= float(sea_level) if sea_level is not None else np.ones(elevation.shape, dtype=bool)
        _dx, _dy, to_local, to_uv = alluvial_channels.local_frame(
            {"source_uv_bounds": source_bounds, "sample_spacing_x_m": spacing_x_m, "sample_spacing_y_m": spacing_y_m},
            elevation.shape,
        )
        from simulations.world_gen.material_routing import inflow_grid

        inflow_cells = inflow_grid(elevation.shape, inflow, spacing_x_m * spacing_y_m)
        if int(level) >= alluvial_fans.FAN_MIN_LEVEL:
            fans, record = alluvial_fans.alluvial_fan_residual(
                elevation, land, level=level, dx=spacing_x_m, dy=spacing_y_m,
                parent_spacing_m=float(parent_spacing_m or 0.0), parent_entity=parent_entity,
                to_local=to_local, to_uv=to_uv, inflow_cells=inflow_cells, sea_level=sea_level,
            )
            # A fan's catchment is worn down towards its apex, not under it: where
            # the wear met the cone, the feeder ended in a pit (two on an arid
            # Region tile, 11 and 17 m deep).
            fans, held_cells = hold_above_outlets(fans, elevation + scarps, sea_level)
            if held_cells:
                record["cells_held_above_their_outlet"] = held_cells
            diagnostics["landforms"].append(record)
            conserved = conserved + fans
        if int(level) >= alluvial_channels.CHANNEL_PLANFORM_MIN_LEVEL:
            seed_text = f"{((parent_entity or {}).get('heightmap_model') or {}).get('map_seed') or ''}"
            channels, record = alluvial_channels.alluvial_channel_residual(
                elevation + conserved, land, level=level, dx=spacing_x_m, dy=spacing_y_m,
                parent_spacing_m=float(parent_spacing_m or 0.0), parent_entity=parent_entity,
                to_local=to_local, to_uv=to_uv, seed_text=seed_text, sea_level=sea_level,
                inflow_cells=inflow_cells,
            )
            diagnostics["landforms"].append(record)
            conserved = conserved + channels
            # The plain beside the channel: the courses the river left (bars
            # and swales), each order at the level that resolves it.
            relics, relic_record = floodplain_relics.relic_channel_residual(
                elevation + conserved, land, level=level, dx=spacing_x_m, dy=spacing_y_m,
                parent_spacing_m=float(parent_spacing_m or 0.0), parent_entity=parent_entity,
                to_local=to_local, channel_record=record, sea_level=sea_level,
            )
            diagnostics["landforms"].append(relic_record)
            conserved = conserved + relics
    channels = conserved if np.any(conserved) else None

    if not np.any(residual) and channels is None and not np.any(scarps):
        return rows, residual.tolist(), diagnostics
    # Zero-mean at the parent's sample spacing (volume from the parent's
    # smoothed arc band is gathered into the edifices), then fade at edges.
    # Fans and channels are added afterwards (they conserve their own volume).
    radius = max(1, int(round(float(parent_spacing_m or 0.0) / max(spacing_x_m, spacing_y_m, 1e-6) * 0.5)))
    conservation = _box_mean(residual, radius)
    residual = residual - conservation
    if channels is not None:
        residual = residual + channels
    local_u = np.arange(width) / max(1, width - 1)
    local_v = np.arange(height) / max(1, height - 1)
    edge = np.minimum(np.minimum(local_u, 1.0 - local_u)[None, :], np.minimum(local_v, 1.0 - local_v)[:, None])
    from simulations.world_gen.regional_refinement import PARENT_EDGE_FADE_FRACTION

    fade = np.clip(edge / PARENT_EDGE_FADE_FRACTION, 0.0, 1.0)
    fade = fade * fade * (3.0 - 2.0 * fade)
    residual *= fade
    # Scarps carry their own rim fade (the order built here) or need none
    # (orders stepped again reproduce the parent, so sibling tiles agree).
    residual = residual + scarps
    result = elevation + residual
    diagnostics["max_residual_m"] = round(float(np.abs(residual).max()), 1)
    return np.round(result, height_decimals(min(spacing_x_m, spacing_y_m))).tolist(), residual.tolist(), diagnostics
