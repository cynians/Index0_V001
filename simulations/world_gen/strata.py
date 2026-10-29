"""Layered rock anchored to the planet: one stratigraphic stack, one structure.

Phenomenon card
---------------
* **What.** Layered rock (sedimentary, volcanic, metamorphosed sequences)
  is one stack of beds laid down over the planet and then deformed; a map
  shows the bed its land surface cuts.  Seen from orbit and on geological
  maps: cuesta belts round basins and arches (Paris Basin, Michigan Basin),
  deep rock in uplifted cores and young rock in forelands, and fold trains
  parallel to their mountain belts that plunge out along strike (Zagros
  whalebacks, wavelength 10-15 km, 50-200 km long; the Valley and Ridge
  zigzags at its plunging noses).
* **Structure.** The reference horizon of the stack stands at
  ``Z_ref = rock uplift - tectonic subsidence + regional warping + folds``:
  rock uplift lifts the stack so erosion exposes deeper beds; forelands
  bury it; broad basins and arches (warping over ~1500 km, ~1 km of
  structural relief) set gentle regional dips; folds come from crustal
  shortening only (the orogen forcing's crustal thickening index), each
  train parallel to its convergent boundary segment, blended where segments
  meet (fold interference at bends), periclinal (``FOLD_PERICLINE_ASPECT``)
  with wandering axes.  The exposed bed is the one at depth
  ``Z_ref - elevation``.
* **Stack.** A ladder of nested bed orders, each a quarter of the one above
  (formation 800 m, member 200 m, ... down to decimetres), so every finer
  bed lies inside one coarser bed.  A finer bed keeps its parent bed's rock
  with probability ``MEMBER_INHERIT_SHARE`` per order, else draws from the
  local composition: a member of a sandstone formation is mostly sandstone
  (about 70 % of the beds three orders down keep the formation's rock).
* **Scale gate.** A map draws the finest order whose outcrops are at least
  ``OUTCROP_MIN_CELLS`` cells wide where the bedding is steep against the
  ground (width = thickness / slope), and fold orders whose wavelength spans
  ``FOLD_MIN_CELLS`` cells.  Everything is a function of planet position and
  the planet seed, so a child map shows its parent's beds and folds and adds
  only finer ones, and neighbouring maps agree at their shared edge.
* **Layers.** Materials (``material_lod``: layered units draw their rock per
  bed); True Color through the materials.  The rock-cliff step
  (``rock_scarps``) keeps its own bed orders (open item).

Values from the literature were entered from memory and are unverified.
"""

from __future__ import annotations

import math

import numpy as np

from simulations.world_gen.array_noise import fbm, hash_unit, seed_int
from simulations.world_gen.sphere_noise import sphere_signed

# Nested bed orders (m): formation, member, bed set, ...  Each a quarter of
# the order above, so finer beds nest in coarser ones.
BED_THICKNESS_LADDER_M = (800.0, 200.0, 50.0, 12.5, 3.125, 0.78125, 0.1953125)
BED_ORDER_RATIO = 4
# Formations come in world-anchored blocks of this many; each bed of an order
# splits into BED_ORDER_RATIO beds of the next.  Bed thickness is lognormal
# about its order's nominal value (real sequences are not periodic): a
# spread of 0.45 puts 95 % of beds within 0.4-2.5 times the nominal.
BED_BLOCK_BEDS = 32
BED_THICKNESS_SPREAD = 0.45
MEMBER_INHERIT_SHARE = 0.88
OUTCROP_MIN_CELLS = 2.0
# Fold orders (m): the regional train and its parasitic folds.
FOLD_WAVELENGTHS_M = (15_000.0, 3_000.0, 600.0, 120.0, 24.0)
FOLD_MIN_CELLS = 8.0
# Fold amplitude / wavelength at full shortening (limb dip ~20 deg); each
# parasitic order is gentler.
FOLD_AMPLITUDE_RATIO = 0.06
PARASITIC_AMPLITUDE_DECAY = 0.6
FOLD_PERICLINE_ASPECT = 6.0
FOLD_AXIS_WANDER_WAVELENGTHS = 0.25
# Segments farther than this from a cell do not fold it; nearer ones blend
# over FOLD_BLEND_M (fold interference at bends and between belts).
FOLD_REACH_M = 1_500_000.0
FOLD_BLEND_M = 120_000.0
FOLD_SEGMENT_KINDS = {"collision", "subduction"}
# Regional basins and arches: blobs of ~1500 km, ~1 km structural relief.
REGIONAL_WARP_FEATURES = 4.0
REGIONAL_WARP_M = 1_000.0
_FBM2_SPREAD = 0.15
_SEGMENT_CACHE = {}


def planet_strata_seed(planet):
    """The planet's seed for its stack and structure (the same on every map of it)."""
    planet = planet if isinstance(planet, dict) else {}
    seed = planet.get("world_gen_seed") if isinstance(planet.get("world_gen_seed"), dict) else {}
    return str(
        seed.get("resolved_map_seed")
        or seed.get("map_seed")
        or planet.get("refinement_root_planet_id")
        or planet.get("id")
        or "planet"
    )


def _fold_segments(tectonic_model, circumference_m):
    """Convergent boundary segments as metric frames, normals consistent within each orogen system."""
    key = (id(tectonic_model), round(float(circumference_m), 3))
    cached = _SEGMENT_CACHE.get(key)
    if cached is not None and cached[0] is tectonic_model:
        return cached[1]
    raw = []
    for segment in (tectonic_model or {}).get("boundary_segments") or []:
        if not isinstance(segment, dict) or str(segment.get("kind") or "") not in FOLD_SEGMENT_KINDS:
            continue
        x1, y1 = float(segment.get("x1", 0.0) or 0.0), float(segment.get("y1", 0.0) or 0.0)
        x2, y2 = float(segment.get("x2", 0.0) or 0.0), float(segment.get("y2", 0.0) or 0.0)
        dx = x2 - x1
        dx = dx - 1.0 if dx > 0.5 else dx + 1.0 if dx < -0.5 else dx
        mid_u, mid_v = (x1 + 0.5 * dx) % 1.0, 0.5 * (y1 + y2)
        scale_x = circumference_m * max(0.05, math.cos((0.5 - mid_v) * math.pi))
        scale_y = circumference_m * 0.5
        ex, ey = dx * scale_x, (y2 - y1) * scale_y
        length = math.hypot(ex, ey)
        if length <= 1.0:
            continue
        system = str(segment.get("orogen_system_id") or segment.get("id") or "segment")
        raw.append({"system": system, "mid_u": mid_u, "mid_v": mid_v, "sx": scale_x, "sy": scale_y,
                    "dir": (ex / length, ey / length), "length": length})
    by_system = {}
    for item in raw:
        by_system.setdefault(item["system"], []).append(item)
    segments = []
    for system, items in by_system.items():
        # One along-strike sense per system (so normals agree) and one origin.
        reference = items[0]["dir"]
        origin_u, origin_v = items[0]["mid_u"], items[0]["mid_v"]
        for item in items:
            dx, dy = item["dir"]
            if dx * reference[0] + dy * reference[1] < 0.0:
                dx, dy = -dx, -dy
            du = item["mid_u"] - origin_u
            du = du - 1.0 if du > 0.5 else du + 1.0 if du < -0.5 else du
            offset = du * item["sx"] * dx + (item["mid_v"] - origin_v) * item["sy"] * dy
            segments.append(dict(item, dir=(dx, dy), along_offset=offset))
    _SEGMENT_CACHE.clear()
    _SEGMENT_CACHE[key] = (tectonic_model, segments)
    return segments


def _segment_frame(segment, u_grid, v_grid):
    du = u_grid - segment["mid_u"]
    du = np.where(du > 0.5, du - 1.0, np.where(du < -0.5, du + 1.0, du))
    x = du * segment["sx"]
    y = (v_grid - segment["mid_v"]) * segment["sy"]
    dx, dy = segment["dir"]
    along = x * dx + y * dy
    normal = -x * dy + y * dx
    half = 0.5 * segment["length"]
    distance = np.hypot(along - np.clip(along, -half, half), normal)
    return along + segment["along_offset"], normal, distance


def _blended_frames(u_grid, v_grid, tectonic_model, circumference_m):
    """Segment frames that reach the samples and their blend weights (normalised), or ``([], None)``."""
    frames = []
    for segment in _fold_segments(tectonic_model, circumference_m):
        along, normal, distance = _segment_frame(segment, u_grid, v_grid)
        if float(distance.min()) < FOLD_REACH_M:
            frames.append((segment, along, normal, distance))
    if not frames:
        return [], None
    nearest = np.min(np.stack([frame[3] for frame in frames]), axis=0)
    frames = [frame for frame in frames if float((frame[3] - nearest).min()) < 8.0 * FOLD_BLEND_M]
    weights = [np.exp(-(frame[3] - nearest) / FOLD_BLEND_M) * (frame[3] < FOLD_REACH_M) for frame in frames]
    total = np.maximum(np.sum(weights, axis=0), 1e-12)
    return frames, [weight / total for weight in weights]


def strike_field(u, v, *, tectonic_model, circumference_m):
    """Local structural strike as (east, south) unit components: the convergent segments' direction, blended like the folds.

    Directions are averaged on doubled angles (a strike has no sense).  East
    where no segment reaches.
    """
    u_grid, v_grid = np.broadcast_arrays(np.asarray(u, dtype=np.float64), np.asarray(v, dtype=np.float64))
    frames, weights = _blended_frames(u_grid, v_grid, tectonic_model, circumference_m)
    if not frames:
        return np.ones(u_grid.shape), np.zeros(u_grid.shape)
    cos2 = np.zeros(u_grid.shape)
    sin2 = np.zeros(u_grid.shape)
    for (segment, _along, _normal, _distance), weight in zip(frames, weights):
        dx, dy = segment["dir"]
        cos2 += weight * (dx * dx - dy * dy)
        sin2 += weight * (2.0 * dx * dy)
    angle = 0.5 * np.arctan2(sin2, cos2)
    return np.cos(angle), np.sin(angle)


def fold_wavelengths(cell_m):
    """Fold orders a map with ``cell_m`` cells resolves (coarse ones always: they are its parents')."""
    return [wavelength for wavelength in FOLD_WAVELENGTHS_M if wavelength >= FOLD_MIN_CELLS * cell_m]


def fold_surface(u_grid, v_grid, shortening, *, tectonic_model, circumference_m, seed, cell_m):
    """Height of the folded reference horizon (m) from every resolved fold order."""
    shortening = np.clip(np.asarray(shortening, dtype=np.float64), 0.0, 1.0)
    shape = np.broadcast(u_grid, v_grid).shape
    total = np.zeros(shape, dtype=np.float64)
    wavelengths = fold_wavelengths(cell_m)
    if not wavelengths or not np.any(shortening > 0.0):
        return total
    frames, weights = _blended_frames(u_grid, v_grid, tectonic_model, circumference_m)
    if not frames:
        return total
    weight_total = 1.0
    for order, wavelength in enumerate(FOLD_WAVELENGTHS_M):
        if wavelength not in wavelengths:
            continue
        blended = np.zeros(shape, dtype=np.float64)
        for (segment, along, normal, _distance), weight in zip(frames, weights):
            system_seed = seed_int(seed, f"strata:fold:{segment['system']}:{order}")
            length = FOLD_PERICLINE_ASPECT * wavelength
            envelope = fbm(along / length, normal / (1.5 * wavelength), system_seed + 13, octaves=2)
            envelope = np.clip((envelope - 0.4) / 0.25, 0.0, 1.0)
            envelope = envelope * envelope * (3.0 - 2.0 * envelope)
            offset = (fbm(along / length, normal / (1.2 * wavelength), system_seed + 17, octaves=2) - 0.5) / _FBM2_SPREAD
            wander = np.clip(offset, -2.5, 2.5) * FOLD_AXIS_WANDER_WAVELENGTHS * math.tau
            phase = hash_unit(np.zeros(1, dtype=np.int64), np.zeros(1, dtype=np.int64), system_seed + 7)[0] * math.tau
            blended += weight * envelope * np.sin(normal / wavelength * math.tau + phase + wander)
        amplitude = FOLD_AMPLITUDE_RATIO * wavelength * PARASITIC_AMPLITUDE_DECAY ** order
        total += amplitude * shortening * blended / weight_total
    return total


def reference_horizon(u_grid, v_grid, *, tectonic_model, circumference_m, seed, cell_m, forcing=None):
    """``Z_ref`` (m): where the stack's reference horizon stands, from planet fields only."""
    u_grid, v_grid = np.broadcast_arrays(np.asarray(u_grid, dtype=np.float64), np.asarray(v_grid, dtype=np.float64))
    shape = u_grid.shape
    uplift = np.zeros(shape)
    subsidence = np.zeros(shape)
    shortening = np.zeros(shape)
    if forcing is not None:
        uplift = np.asarray(forcing.get("rock_uplift_m", uplift), dtype=np.float64)
        subsidence = np.asarray(forcing.get("tectonic_subsidence_m", subsidence), dtype=np.float64)
        shortening = np.clip(np.asarray(forcing.get("crustal_thickening_index", shortening), dtype=np.float64), 0.0, 1.0)
    warp = REGIONAL_WARP_M * sphere_signed(seed, "strata:regional_warp", u_grid, v_grid, features=REGIONAL_WARP_FEATURES, octaves=2)
    folds = fold_surface(u_grid, v_grid, shortening, tectonic_model=tectonic_model, circumference_m=circumference_m, seed=seed, cell_m=cell_m)
    return uplift - subsidence + warp + folds


def resolved_order(depth, cell_m):
    """Finest bed order whose outcrops stay ``OUTCROP_MIN_CELLS`` wide where the bedding cuts the ground steeply."""
    gy, gx = np.gradient(np.asarray(depth, dtype=np.float64), float(cell_m))
    slope = float(np.percentile(np.hypot(gx, gy), 90.0)) if np.size(depth) > 4 else 0.0
    order = 0
    for index, thickness in enumerate(BED_THICKNESS_LADDER_M):
        if thickness >= OUTCROP_MIN_CELLS * cell_m * slope:
            order = index
        else:
            break
    return order


def _material_key(material_id, order):
    return seed_int(str(material_id), f"strata:order{order}") % (1 << 61)


def _race(composition, material_ids, beds, order, seed):
    best = np.full(beds.shape, np.inf)
    winner = np.zeros(beds.shape, dtype=np.int64)
    for index, material_id in enumerate(material_ids):
        share = composition[index]
        present = share > 1e-9
        if not present.any():
            continue
        uniform = hash_unit(beds, np.full(beds.shape, _material_key(material_id, order), dtype=np.int64), seed)
        score = np.where(present, -np.log(np.clip(uniform, 1e-12, 1.0)) / np.maximum(share, 1e-9), np.inf)
        better = score < best
        winner[better] = index
        best = np.where(better, score, best)
    return winner


def _normal_draws(ids, salt, seed, count):
    """``count`` roughly standard-normal draws per id (sum of three uniforms)."""
    ids = np.asarray(ids, dtype=np.int64)
    draws = []
    for index in range(count):
        total = sum(hash_unit(ids, np.full(ids.shape, salt * 64 + index * 3 + part, dtype=np.int64), seed) for part in range(3))
        draws.append((total - 1.5) * 2.0)
    return np.stack(draws, axis=-1)


def _split_fractions(ids, order, seed):
    """Cumulative fractions (..., RATIO + 1) at which each bed of ``order - 1`` splits into the beds of ``order``."""
    weights = np.exp(BED_THICKNESS_SPREAD * _normal_draws(ids, 100 + order, seed, BED_ORDER_RATIO))
    cumulative = np.cumsum(weights, axis=-1) / weights.sum(axis=-1, keepdims=True)
    return np.concatenate([np.zeros(cumulative.shape[:-1] + (1,)), cumulative], axis=-1)


def _block_fractions(blocks, seed):
    """Cumulative fractions (..., BED_BLOCK_BEDS + 1) of the formations in each world-anchored block."""
    ids = np.asarray(blocks, dtype=np.int64)
    weights = np.exp(BED_THICKNESS_SPREAD * _normal_draws(ids, 1, seed, BED_BLOCK_BEDS))
    cumulative = np.cumsum(weights, axis=-1) / weights.sum(axis=-1, keepdims=True)
    return np.concatenate([np.zeros(cumulative.shape[:-1] + (1,)), cumulative], axis=-1)


def bed_ids(depth, order, seed):
    """Bed of each order 0..``order`` at ``depth`` (m below the reference horizon).

    Returns a list of int64 arrays: formation ids, then each finer order's
    ``parent * BED_ORDER_RATIO + j``, so a finer bed lies in exactly one
    coarser bed.  Thicknesses vary bed by bed; everything is a function of
    depth and the planet seed.
    """
    strata_seed = seed_int(seed, "strata:partition")
    depth = np.asarray(depth, dtype=np.float64)
    block_m = BED_BLOCK_BEDS * BED_THICKNESS_LADDER_M[0]
    block = np.floor(depth / block_m).astype(np.int64)
    position = depth / block_m - block
    ids = np.zeros(depth.shape, dtype=np.int64)
    low = np.zeros(depth.shape)
    high = np.ones(depth.shape)
    for value in np.unique(block):
        mask = block == value
        bounds = _block_fractions(np.asarray([value]), strata_seed)[0]
        index = np.clip(np.searchsorted(bounds, position[mask], side="right") - 1, 0, BED_BLOCK_BEDS - 1)
        ids[mask] = value * BED_BLOCK_BEDS + index
        low[mask], high[mask] = bounds[index], bounds[index + 1]
    result = [ids]
    for level in range(1, int(order) + 1):
        local = (position - low) / np.maximum(high - low, 1e-15)
        bounds = _split_fractions(ids, level, strata_seed)
        index = np.clip((local[..., None] >= bounds[..., 1:]).sum(axis=-1), 0, BED_ORDER_RATIO - 1)
        span = high - low
        low, high = (
            low + span * np.take_along_axis(bounds, index[..., None], axis=-1)[..., 0],
            low + span * np.take_along_axis(bounds, index[..., None] + 1, axis=-1)[..., 0],
        )
        ids = ids * BED_ORDER_RATIO + index
        result.append(ids)
    return result


def beds_between(top_depth, base_depth, order, seed):
    """Every bed of ``order`` that overlaps ``top_depth .. base_depth``, shallowest first.

    Returns ``[(id, top, base)]`` in metres below the reference horizon; the
    same beds ``bed_ids`` finds at those depths.
    """
    strata_seed = seed_int(seed, "strata:partition")
    block_m = BED_BLOCK_BEDS * BED_THICKNESS_LADDER_M[0]
    beds = []
    for block in range(int(np.floor(top_depth / block_m)), int(np.floor(base_depth / block_m)) + 1):
        bounds = _block_fractions(np.asarray([block]), strata_seed)[0]
        for index in range(BED_BLOCK_BEDS):
            top = (block + bounds[index]) * block_m
            base = (block + bounds[index + 1]) * block_m
            if base > top_depth and top < base_depth:
                beds.append((block * BED_BLOCK_BEDS + index, top, base))
    for level in range(1, int(order) + 1):
        if not beds:
            break
        ids = np.asarray([bed[0] for bed in beds], dtype=np.int64)
        bounds = _split_fractions(ids, level, strata_seed)
        finer = []
        for (bed_id, top, base), fractions in zip(beds, bounds):
            for index in range(BED_ORDER_RATIO):
                sub_top = top + (base - top) * fractions[index]
                sub_base = top + (base - top) * fractions[index + 1]
                if sub_base > top_depth and sub_top < base_depth:
                    finer.append((bed_id * BED_ORDER_RATIO + index, sub_top, sub_base))
        beds = finer
    return beds


def bed_rock(bed_id, order, shares, seed, coarser_rock=None, order_gap=1):
    """Rock of one bed from ``shares`` ``{material: share}``, kept from its coarser bed where it inherits.

    A bed keeps ``coarser_rock`` with probability
    ``MEMBER_INHERIT_SHARE ** order_gap``; otherwise it is drawn by an
    exponential race whose uniforms belong to the bed and the material (so
    every map that draws it draws the same rock from the same mix).
    """
    strata_seed = seed_int(seed, "strata:beds")
    bed = np.asarray([bed_id], dtype=np.int64)
    if coarser_rock is not None:
        keep = hash_unit(bed, np.asarray([7_919 + int(order)], dtype=np.int64), strata_seed + 1)[0]
        if keep < MEMBER_INHERIT_SHARE ** max(1, int(order_gap)):
            return coarser_rock
    best, winner = math.inf, None
    for material_id, share in sorted(shares.items()):
        if share <= 1e-9:
            continue
        uniform = hash_unit(bed, np.asarray([_material_key(material_id, order)], dtype=np.int64), strata_seed)[0]
        score = -math.log(max(uniform, 1e-12)) / share
        if score < best:
            best, winner = score, material_id
    return winner


def bed_materials(depth, composition, material_ids, *, order, seed):
    """Rock of the exposed bed at every cell, nested from formations down to ``order``.

    Returns ``(material_index, beds_by_order)``: the drawn material per cell
    (index into ``material_ids``) and the bed id of each order 0..order.
    """
    strata_seed = seed_int(seed, "strata:beds")
    beds_by_order = bed_ids(depth, order, seed)
    material = None
    for index, beds in enumerate(beds_by_order):
        drawn = _race(composition, material_ids, beds, index, strata_seed)
        if material is None:
            material = drawn
            continue
        keep = hash_unit(beds, np.full(beds.shape, 7_919 + index, dtype=np.int64), strata_seed + 1) < MEMBER_INHERIT_SHARE
        material = np.where(keep, material, drawn)
    return material, beds_by_order
