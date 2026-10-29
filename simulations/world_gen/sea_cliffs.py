"""Sea cliffs and shore platforms: the shore that waves cut into rock.

Where the sea meets rock it does sideways what a stream does at a scarp.
Waves break against the foot of the land, quarry the rock at sea level and
carry the debris off; the ground above loses its support and falls; and the
shore moves inland, leaving a rock platform at about sea level with a cliff
at its back (Sunamura 1992, "Geomorphology of Rocky Coasts"; Trenhaile
1987).  The cliff is as high as the land it has been cut back into and
stands at what its rock holds (``rock_scarps.rockfall``, with the platform
kept clear by the sea as a stream keeps a canyon floor).

How far the shore has moved since the sea came to its present level is the
whole of the form, and three things decide it:

* **Rock.**  Recession rates span four orders of magnitude with lithology,
  from a millimetre a year in granite to metres a year in glacial drift
  (Sunamura 1983).  Here the distance falls with the effective strength of
  the rock at sea level to the power ``STRENGTH_EXPONENT``; in a layered
  sequence that is the bed the sea stands in, so beds of unequal strength
  that dip across a shore come out as headlands and coves.
* **Waves.**  The force at the cliff foot grows with the height of the
  waves that reach it.  Offshore that height is what the wind raises over
  the open water in front of the coast (fetch-limited growth, Hasselmann et
  al. 1973; ``fetch_limited_wave_height``), found once where the ocean is in
  view and handed down the levels; inshore it is less wherever land stands
  in the way (``shelter``).  A platform shelters its own cliff: waves spend
  themselves crossing it, so recession slows as the platform widens
  (Trenhaile 2000) and platforms wider than a few hundred metres are rare.
The height of the land is not among them.  Recession rates measured on
cliffs of one rock show no clear dependence on their height (stated from
memory), and a rule that read it would read ground it has itself cut and
laid back: the cliff a level leaves is a slope to the next, which would
take it for a low shore and cut on.

Rock and waves are one field, the cost of a metre of retreat at every
point, and the shore is where the cost added up from the sea reaches what
the waves have had time for (``cost_distance`` through the water,
``cut_inland`` through the rock).  A weak bed behind a breach in a strong
one is therefore hollowed out behind it, and a headland is flanked before
it is cut through.  The waves that cut a piece of rock are those that come
along the cheapest way to it, with the height they had in the last water
they crossed.

Waves that have crossed shallow water arrive spent.  The cost is therefore
added up from water deep enough to carry the waves, across the shelf of a
shelving coast and across any platform already there, before it reaches
the rock: a low coast with a wide shallow foreshore is not cut (it is the
beach's to shape), a plunging one is cut by the whole of its retreat, and a
level that inherits a platform from a coarser one cuts only what is left.
Each level draws what its cells resolve (``scale_share``); the rest waits
for the next.

Abiotic by contract.  The beach on the platform and in the cove is
``shore_deposits``', a river's delta ``river_deltas``'.  Not built here:
notches, stacks and arches, and tides as a process (a tidal range only
widens the band the platform slopes through).
"""

from __future__ import annotations

import math

import numpy as np

MODEL = "wave_cut_shore_v1"
LANDFORM_ID = "sea_cliffs_and_shore_platforms"

# Time the sea has stood at its present level (Earth: the Holocene highstand,
# about 6,000 years).  One figure for the world.
STILLSTAND_YEARS = 6000.0
# Recession over the stillstand of rock of the reference strength under
# waves of the reference height, before its own platform shelters it:
# 5 cm a year, a soft shale or mudstone coast.  The other rocks follow by the
# strength exponent: about 20 m for sandstone, 6 m for basalt.  Fitted by eye
# to the lithology table of Sunamura (1983, 1992) as remembered; unverified.
REFERENCE_RECESSION_M = 300.0
REFERENCE_STRENGTH_MPA = 6.0
REFERENCE_WAVE_HEIGHT_M = 1.5
STRENGTH_EXPONENT = 1.2
WAVE_EXPONENT = 2.0
# Effective compressive strength from the ontology's erodibility index (the
# inverse of ``tools/author_mechanical_lithology.py``: the index falls 0.455
# per decade of tensile strength from 0.5 at 4.49 MPa; compressive = 10 x).
ERODIBILITY_REFERENCE_TENSILE_MPA = 4.49
ERODIBILITY_INDEX_PER_STRENGTH_DECADE = 0.455
# Waves break where the water is about 1.28 wave heights deep; over a
# platform sloping 1 in 100 that is a surf zone 130 wave heights wide, the
# width over which a platform takes the force out of the waves.
BREAKING_DEPTH_WAVE_HEIGHTS = 1.28
PLATFORM_SHELTER_WIDTH_PER_WAVE_HEIGHT = 130.0
# The platform slopes from this far below the sea at its outer edge to this
# far above it at the cliff foot (in wave heights), plus half the tidal range
# either way.
PLATFORM_EDGE_DEPTH_WAVE_HEIGHTS = 0.5
PLATFORM_FOOT_RISE_WAVE_HEIGHTS = 0.3
# Wind that raises the waves which do the work: the storm wind, this many
# times the prevailing mean.
STORM_WIND_FACTOR = 3.0
# Fetch-limited growth and the fully developed sea (JONSWAP; Pierson &
# Moskowitz 1964): H = 0.0016 U sqrt(F / g), at most 0.24 U^2 / g.
FETCH_GROWTH = 1.6e-3
FULLY_DEVELOPED = 0.24
FETCH_DIRECTIONS = 16
OCEAN_FETCH_CELLS = 96
OPEN_OCEAN_FETCH_M = 1.5e6
# A retreat is drawn from one cell on, whole from two.
RESOLVE_CELLS = (1.0, 2.0)
WAVE_RECORD_CELLS = 96
# The finest bed order whose beds are as thick as the band waves work on
# (Local scale: 1.5 to 6 m).
SHORE_ROCK_ORDER_LEVEL = 3
WAVE_FRONT_CELLS = 3
WAVE_OBSTACLE_CELLS = 1.5


def _smooth01(values):
    t = np.clip(values, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def effective_strength_mpa(erodibility):
    """Effective compressive strength (MPa) of rock with the ontology's ``erodibility_index``."""
    index = np.asarray(erodibility, dtype=np.float64)
    return 10.0 * ERODIBILITY_REFERENCE_TENSILE_MPA * 10.0 ** ((0.5 - index) / ERODIBILITY_INDEX_PER_STRENGTH_DECADE)


def fetch_limited_wave_height(fetch_m, wind_m_s, gravity):
    """Significant height of the waves a wind raises over ``fetch_m`` of open water."""
    fetch = np.maximum(np.asarray(fetch_m, dtype=np.float64), 0.0)
    wind = np.asarray(wind_m_s, dtype=np.float64)
    return np.minimum(FETCH_GROWTH * wind * np.sqrt(fetch / gravity), FULLY_DEVELOPED * wind * wind / gravity)


def rock_recession_m(strength_mpa):
    """How far a shore of this rock goes back under the reference waves over the stillstand, with no platform in front."""
    strength = np.maximum(np.asarray(strength_mpa, dtype=np.float64), 1e-3)
    return REFERENCE_RECESSION_M * (STILLSTAND_YEARS / 6000.0) * (REFERENCE_STRENGTH_MPA / strength) ** STRENGTH_EXPONENT


def _sheltered(rock_m, wave_height_m):
    height = np.maximum(wave_height_m, 0.0)
    unsheltered = rock_m * (height / REFERENCE_WAVE_HEIGHT_M) ** WAVE_EXPONENT
    # dX/dt = r exp(-X / W): the platform's own shelter.
    shelter_width = np.maximum(PLATFORM_SHELTER_WIDTH_PER_WAVE_HEIGHT * height, 1e-6)
    return shelter_width * np.log1p(unsheltered / shelter_width)


def recession_m(strength_mpa, wave_height_m):
    """How far a shore of this rock has been cut back under these waves over the stillstand."""
    return _sheltered(rock_recession_m(strength_mpa), np.asarray(wave_height_m, dtype=np.float64))


def scale_share(retreat_m, spacing_m):
    """Share of a retreat a level draws: none of what is under a cell wide, all of what is two."""
    low, high = RESOLVE_CELLS
    return _smooth01((np.asarray(retreat_m, dtype=np.float64) / spacing_m - low) / (high - low))


def _directions(count=FETCH_DIRECTIONS):
    """Unit cell steps (dx, dy) of ``count`` compass directions on a square lattice, with their lengths in cells."""
    steps = []
    for index in range(count):
        angle = math.tau * index / count
        x, y = math.cos(angle), math.sin(angle)
        scale = max(abs(x), abs(y))
        steps.append((x / scale, y / scale, 1.0 / scale))
    return steps


def open_water_cells(sea, max_cells):
    """Per direction, how many cells of open water lie in front of each cell (``[D, H, W]``, capped).

    Beyond the grid the water counts as open: a tile does not know the land
    outside it, and the height it starts from already carries that.
    """
    sea = np.asarray(sea, dtype=bool)
    height, width = sea.shape
    rows = np.arange(height)[:, None]
    columns = np.arange(width)[None, :]
    free = np.empty((FETCH_DIRECTIONS, height, width))
    for index, (step_x, step_y, length) in enumerate(_directions()):
        reach = np.full(sea.shape, float(max_cells))
        open_ = np.ones(sea.shape, dtype=bool)
        for k in range(1, int(max_cells / length) + 1):
            x = columns + int(round(k * step_x))
            y = rows + int(round(k * step_y))
            inside = (x >= 0) & (x < width) & (y >= 0) & (y < height)
            land = inside & ~sea[np.clip(y, 0, height - 1), np.clip(x, 0, width - 1)]
            hit = open_ & land
            reach = np.where(hit, k * length, reach)
            open_ &= ~land
            if not open_.any():
                break
        free[index] = reach
    return free


def ocean_wave_height(sea, spacing_m, wind_m_s, gravity):
    """Height of the storm waves the ocean on a coarse grid sends to each of its cells (m)."""
    free = np.minimum(open_water_cells(sea, OCEAN_FETCH_CELLS) * spacing_m, OPEN_OCEAN_FETCH_M)
    # Storms come from every side over the years: the energy (height squared) of all directions.
    per_direction = fetch_limited_wave_height(free, STORM_WIND_FACTOR * wind_m_s, gravity)
    return np.sqrt((per_direction ** 2).mean(axis=0))


def shelter(sea, radius_cells):
    """0 .. 1: the share of their height waves from beyond ``radius_cells`` keep on reaching a sea cell.

    Waves arrive along the directions in which the water is open all the
    way out to that distance; their energy is shared out over the compass,
    so the height goes with the root of the open share.  A straight open
    coast counts as 1 (the land behind a shore always closes half the
    compass); a cove behind a narrow mouth sees the sea through the mouth
    only and counts for little.
    """
    radius = max(2, int(round(radius_cells)))
    return _shelter_of(open_water_cells(sea, radius), radius)


def _shelter_of(free_cells, radius):
    through = _smooth01((np.minimum(free_cells, radius) / radius - 0.75) / 0.25)
    return np.clip(np.sqrt(2.0 * through.mean(axis=0)), 0.0, 1.0)


def local_wind_sea(free_cells, spacing_m, wind_m_s, gravity):
    """Height of the waves the storm wind raises over the open water a level sees around each cell (m).

    Sheltered water is not still: a channel a few kilometres wide makes
    waves of its own, and they are what cuts its shores.
    """
    per_direction = fetch_limited_wave_height(free_cells * spacing_m, STORM_WIND_FACTOR * wind_m_s, gravity)
    return np.sqrt((per_direction ** 2).mean(axis=0))


def _highest_nearby(values, sea, cells):
    """Per sea cell, the largest value among the sea cells within ``cells`` of it."""
    field = np.where(sea, values, -np.inf)
    for _pass in range(int(cells)):
        padded = np.pad(field, 1, constant_values=-np.inf)
        best = field
        for row in (0, 1, 2):
            for column in (0, 1, 2):
                best = np.maximum(best, padded[row:row + field.shape[0], column:column + field.shape[1]])
        field = np.where(sea, best, -np.inf)
    return np.where(sea, field, 0.0)


def spread_from_sea(values, sea, passes):
    """Carry sea-cell values inland: each land cell takes the mean of its valued neighbours, pass by pass."""
    field = np.where(sea, values, 0.0)
    known = np.asarray(sea, dtype=np.float64).copy()
    for _pass in range(int(passes)):
        if known.all():
            break
        total = np.zeros(field.shape)
        count = np.zeros(field.shape)
        padded_field = np.pad(field * known, 1)
        padded_known = np.pad(known, 1)
        for row in (0, 1, 2):
            for column in (0, 1, 2):
                total += padded_field[row:row + field.shape[0], column:column + field.shape[1]]
                count += padded_known[row:row + field.shape[0], column:column + field.shape[1]]
        fresh = (known == 0.0) & (count > 0.0)
        field = np.where(fresh, total / np.maximum(count, 1e-9), field)
        known = np.where(fresh, 1.0, known)
    return field


def open_water(sea, seeds):
    """Sea cells joined through water to the ``seeds`` (4-neighbour)."""
    sea = np.asarray(sea, dtype=bool)
    reached = np.asarray(seeds, dtype=bool) & sea
    for _pass in range(sea.size):
        grown = reached.copy()
        # A sweep each way along rows and columns carries the mark as far as the water goes.
        for axis in (0, 1):
            for reverse in (False, True):
                marks = np.moveaxis(np.flip(grown, axis) if reverse else grown, axis, 0)
                water = np.moveaxis(np.flip(sea, axis) if reverse else sea, axis, 0)
                for index in range(1, marks.shape[0]):
                    marks[index] |= marks[index - 1] & water[index]
        if (grown == reached).all():
            break
        reached = grown
    return reached


def cost_distance(cost_per_m, sources, dx, dy, limit=1.0, max_passes=400):
    """Least cost added up from the source cells to every cell over its eight neighbours.

    ``cost_per_m`` is the cost of crossing a metre of each cell (``inf``:
    no way through).  Cells no path reaches under ``limit`` keep ``inf`` or
    a value over it.
    """
    total = np.where(sources, 0.0, np.inf)
    diagonal = math.hypot(dx, dy)
    whole, head, tail = slice(None), slice(None, -1), slice(1, None)
    pairs = (
        ((head, whole), (tail, whole), dy),
        ((whole, head), (whole, tail), dx),
        ((head, head), (tail, tail), diagonal),
        ((head, tail), (tail, head), diagonal),
    )
    steps = [(first, second, 0.5 * (cost_per_m[first] + cost_per_m[second]) * distance) for first, second, distance in pairs]
    for _pass in range(int(max_passes)):
        before = total.copy()
        for first, second, step in steps:
            np.minimum(total[first], total[second] + step, out=total[first])
            np.minimum(total[second], total[first] + step, out=total[second])
        changed = total < before
        if not changed.any() or float(total[changed].min()) >= limit:
            break
    return total


def cut_inland(spent, cost_per_m, rock_m, wave_height_m, sea, dx, dy, limit=1.0):
    """Carry the cost on from the water into the rock, each path with the waves it left the water with.

    ``spent`` is the cost added up through the water (``inf`` on land),
    ``cost_per_m`` the cost of a metre of each sea cell, ``rock_m`` the
    ``rock_recession_m`` of every cell.  A rock cell is cut by the waves
    that come along the cheapest way to it, and those have the height they
    had in the last water they crossed: the land behind the head of a narrow
    inlet is cut from the open shore beside it, not by the ripples in the
    inlet.  Only costs under ``limit`` are followed.

    Returns ``(spent, retreat_m, waves, left_water)``, all ``[H, W]``: the
    cost at every cell; per land cell reached, how far its rock goes back
    under the waves that reached it, their height, and the flat index of the
    sea cell they left the water at (``-1`` where no path came).
    """
    wet = np.asarray(sea, dtype=bool).ravel()
    height, width = np.shape(sea)
    total = np.array(spent, dtype=np.float64).ravel()
    own = np.where(wet, np.asarray(cost_per_m, dtype=np.float64).ravel(), np.inf)
    carried = np.where(wet, np.asarray(wave_height_m, dtype=np.float64).ravel(), 0.0)
    rock = np.broadcast_to(np.asarray(rock_m, dtype=np.float64), (height, width)).ravel()
    left_water = np.where(wet, np.arange(total.size), -1)
    rows, columns = np.divmod(np.arange(total.size), width)
    moves = [
        (step_y * width + step_x, step_y, step_x, math.hypot(step_x * dx, step_y * dy))
        for step_y in (-1, 0, 1) for step_x in (-1, 0, 1) if step_x or step_y
    ]
    fresh = np.flatnonzero(wet & (total < limit))
    for _pass in range(4 * (height + width)):
        if not fresh.size:
            break
        reached = []
        for offset, step_y, step_x, distance in moves:
            row, column = rows[fresh] + step_y, columns[fresh] + step_x
            source = fresh[(row >= 0) & (row < height) & (column >= 0) & (column < width)]
            target = source + offset
            entry = own[target]
            dry = ~wet[target]
            entry[dry] = 1.0 / np.maximum(_sheltered(rock[target[dry]], carried[source[dry]]), 1e-9)
            candidate = total[source] + 0.5 * (own[source] + entry) * distance
            better = candidate < np.minimum(total[target], limit)
            if not better.any():
                continue
            hit, came = target[better], source[better]
            total[hit] = candidate[better]
            onto_land = ~wet[hit]
            hit, came = hit[onto_land], came[onto_land]
            own[hit] = entry[better][onto_land]
            carried[hit] = carried[came]
            left_water[hit] = left_water[came]
            reached.append(target[better])
        fresh = np.unique(np.concatenate(reached)) if reached else fresh[:0]
    shape = (height, width)
    retreat = np.where(~wet & (left_water >= 0), 1.0 / np.maximum(own, 1e-300), 0.0)
    return total.reshape(shape), retreat.reshape(shape), np.where(wet, 0.0, carried).reshape(shape), np.where(wet, -1, left_water).reshape(shape)


def cut_shore(
    elevation, sea_level, *, dx, dy, strength_mpa, wave_height_m, offshore_wave_height_m=None, tidal_range_m=0.0, fade=None,
):
    """The shore platform waves have cut into the land, as a height change.

    ``elevation`` is the ground with every other landform of the level in
    it, ``strength_mpa`` the effective strength of the rock at sea level
    (``[H, W]`` or a number), ``wave_height_m`` the height of the waves
    reaching each cell (``[H, W]``: the sea cells count),
    ``offshore_wave_height_m`` their height before the land of this level
    sheltered them (default: the highest of ``wave_height_m``), ``fade``
    the tile-rim weight.

    The waves start from water deep enough to carry them as they come in
    from offshore (``BREAKING_DEPTH_WAVE_HEIGHTS``; judged by the offshore
    height, or a platform would count as deep water again as soon as the
    cove it lies in sheltered it) and spend themselves on everything
    shallower: on the shelf in front of a low coast, on a platform a coarser
    level has already cut, and then on the rock.  So a shelving shore is not
    cut at all, a plunging one is cut by the whole of its retreat, and a
    level that inherits a platform cuts only what is left to cut.  A level
    draws that remainder if its cells resolve it (``scale_share``).

    Returns ``(change, platform, record)``: the lowering (``<= 0``), the
    cells the sea keeps clear (bool; the cut platform) and the landform
    record; ``(None, None, record)`` where nothing is cut.
    """
    ground = np.asarray(elevation, dtype=np.float64)
    sea = ground < float(sea_level)
    record = {"landform": LANDFORM_ID, "model": MODEL, "cut_cells": 0}
    if not sea.any() or sea.all():
        return None, None, record
    spacing = min(dx, dy)
    strength = np.broadcast_to(np.asarray(strength_mpa, dtype=np.float64), ground.shape)
    at_sea = np.where(sea, np.asarray(wave_height_m, dtype=np.float64), 0.0)
    depth = float(sea_level) - ground
    offshore = float(np.max(at_sea)) if offshore_wave_height_m is None else np.asarray(offshore_wave_height_m, dtype=np.float64)
    deep = sea & (depth >= BREAKING_DEPTH_WAVE_HEIGHTS * offshore) & (at_sea > 0.0)
    if not deep.any():
        return None, None, record
    rock = rock_recession_m(strength)
    # Through the water first (shallow water costs what its bed's rock
    # costs), then on into the rock.  Nothing in the cost depends on the
    # height of the land, so the rule finds its own result again on ground
    # it has cut and rockfall has laid back.
    in_water = np.where(deep, 0.0, 1.0 / np.maximum(_sheltered(rock, at_sea), 1e-9))
    through_water = cost_distance(np.where(sea, in_water, np.inf), deep, dx, dy, max_passes=max(ground.shape) + 8)
    spent, retreat, waves, left_water = cut_inland(through_water, in_water, rock, at_sea, sea, dx, dy)
    reached = left_water >= 0
    came_from = np.where(reached, left_water, 0)
    # What the water in front of each piece of land has taken already.
    at_shore = np.where(reached, np.minimum(spent.ravel()[came_from], 1.0), 1.0)
    left = 1.0 - at_shore
    share = scale_share(left * retreat, spacing)
    zone = reached & (spent < at_shore + left * share) & (share > 0.0)
    if not zone.any():
        return None, None, record
    # The platform rises with what the waves have spent on the way: from
    # under the sea where they arrive whole to the cliff foot where they
    # are spent.  One profile for every level, so ground a coarser level
    # cut to it is left as it is; and never deeper than the sea bed in front.
    low = float(sea_level) - PLATFORM_EDGE_DEPTH_WAVE_HEIGHTS * waves - 0.5 * float(tidal_range_m)
    high = float(sea_level) + PLATFORM_FOOT_RISE_WAVE_HEIGHTS * waves + 0.5 * float(tidal_range_m)
    level = low + (high - low) * np.clip(spent, 0.0, 1.0)
    level = np.maximum(level, np.minimum(ground.ravel()[came_from], high))
    change = np.where(zone, np.minimum(level - ground, 0.0), 0.0)
    if fade is not None:
        change = change * np.asarray(fade, dtype=np.float64)
    platform = zone & (change < 0.0)
    if not platform.any():
        return None, None, record
    cut = ground + change
    drowned = platform & (cut < float(sea_level))
    # The cliff line: cut cells with uncut land beside them.
    uncut = ~sea & ~zone
    foot = np.zeros(ground.shape, dtype=bool)
    cliff = np.zeros(ground.shape)
    for axis, shift in ((0, 1), (0, -1), (1, 1), (1, -1)):
        beside = np.roll(uncut, shift, axis=axis)
        edge = [slice(None), slice(None)]
        edge[axis] = 0 if shift == 1 else -1
        beside[tuple(edge)] = False
        foot |= platform & beside
        cliff = np.maximum(cliff, np.where(beside, np.roll(ground, shift, axis=axis) - cut, 0.0))
    heights = cliff[foot] if foot.any() else np.zeros(1)
    widths = np.where(reached, (np.minimum(spent, 1.0) - at_shore) * retreat, 0.0)[foot] if foot.any() else np.zeros(1)
    record.update({
        "cut_cells": int(platform.sum()),
        "cut_share_of_land": round(float(platform.sum()) / max(1, int((~sea).sum())), 5),
        "drowned_cells": int(drowned.sum()),
        "max_lowering_m": round(float(-change.min()), 2),
        "mean_lowering_m": round(float(-change[~sea].mean()), 4),
        "retreat_m": [round(float(value), 1) for value in np.percentile(widths, [10, 50, 90, 100])],
        "spent_on_the_water_in_front": round(float(at_shore[platform].mean()), 3),
        "cliff_height_m": [round(float(value), 1) for value in np.percentile(heights, [10, 50, 90, 100])],
        "wave_height_m": [round(float(waves[platform].min()), 2), round(float(waves[platform].max()), 2)],
        "rock_strength_mpa": [round(float(strength[platform].min()), 1), round(float(strength[platform].max()), 1)],
        "stillstand_years": STILLSTAND_YEARS,
        "tidal_range_m": round(float(tidal_range_m), 2),
    })
    return change, platform, record


# --- what a level knows of its waves and its rock -------------------------------


def _wave_record(heightmap):
    for landform in (((heightmap or {}).get("regional_landforms") or {}).get("landforms") or []):
        if isinstance(landform, dict) and landform.get("landform") == LANDFORM_ID and isinstance(landform.get("waves"), dict):
            return landform["waves"]
    return None


def _sample_grid(grid, bounds, u, v):
    """Bilinear sample of ``grid`` (covering ``bounds``) at ``u, v`` (clamped)."""
    values = np.asarray(grid, dtype=np.float64)
    x = np.clip((u - bounds["min_u"]) / max(1e-15, bounds["max_u"] - bounds["min_u"]), 0.0, 1.0) * (values.shape[1] - 1)
    y = np.clip((v - bounds["min_v"]) / max(1e-15, bounds["max_v"] - bounds["min_v"]), 0.0, 1.0) * (values.shape[0] - 1)
    x0 = np.clip(np.floor(x).astype(int), 0, max(0, values.shape[1] - 2))
    y0 = np.clip(np.floor(y).astype(int), 0, max(0, values.shape[0] - 2))
    x1 = np.minimum(x0 + 1, values.shape[1] - 1)
    y1 = np.minimum(y0 + 1, values.shape[0] - 1)
    fx, fy = x - x0, y - y0
    return (values[y0, x0] * (1 - fx) + values[y0, x1] * fx) * (1 - fy) + (values[y1, x0] * (1 - fx) + values[y1, x1] * fx) * fy


def storm_wind_m_s(entity):
    """Mean prevailing wind speed over an entity's climate grid (m/s; 6 without one)."""
    rows = (((entity or {}).get("water_cycle_model") or {}).get("climate_grid") or {}).get("prevailing_wind_rows")
    if not rows:
        return 6.0
    speed = np.asarray(rows, dtype=np.float64)[..., 2]
    return float(np.mean(speed[np.isfinite(speed)]))


def wave_heights(parent_entity, sea, u, v, *, spacing_m, parent_spacing_m, gravity):
    """Height of the waves that reach each cell of a level (m), their height offshore, and the record its children read.

    The parent hands down what reaches its own cells: its record where it
    has one, else (the first level with a shore to cut) what the wind raises
    over the open water of the parent's own grid.  This level then takes
    away what its own land shelters, within about one parent cell (the
    parent has already seen everything larger), and never goes below the
    waves its own open water makes.
    """
    parent_heightmap = (parent_entity or {}).get("heightmap_model") or {}
    inherited = _wave_record(parent_heightmap)
    if inherited is not None:
        offshore = _sample_grid(inherited["height_m"], inherited["uv_bounds"], u, v)
        open_sea = _sample_grid(inherited["offshore_m"], inherited["uv_bounds"], u, v)
        source = "parent_record"
    else:
        rows = ((parent_heightmap.get("sample_grid") or {}).get("rows")) or []
        bounds = parent_heightmap.get("source_uv_bounds") or {}
        sea_level = parent_heightmap.get("sea_level_m")
        if not rows or not bounds or sea_level is None:
            return None, None, None
        parent = np.asarray(rows, dtype=np.float64)
        parent_cell = float(parent_heightmap.get("sample_spacing_x_m") or parent_spacing_m or spacing_m)
        ocean = ocean_wave_height(parent < float(sea_level), parent_cell, storm_wind_m_s(parent_entity), gravity)
        offshore = _sample_grid(ocean, bounds, u, v)
        open_sea = offshore
        source = "open_water_of_the_parent_grid"
    radius = max(2, int(round(max(4.0, float(parent_spacing_m or spacing_m) / spacing_m))))
    # Waves bend round what is only a cell or two wide: a reef, an islet, a
    # spit, the speckle of a shore the level has not smoothed yet.  Only
    # land that fills its neighbourhood stands in their way.
    from simulations.world_gen.material_routing import gaussian_blur

    free = open_water_cells(gaussian_blur(np.asarray(sea, dtype=np.float64), WAVE_OBSTACLE_CELLS) > 0.5, radius)
    carried = offshore * _shelter_of(free, radius)
    # The ocean's waves reach only water joined to the sea.  A pond this
    # level's detail has left below sea level behind the shore is shut in:
    # it was taken for open water (no land within a parent cell of its
    # middle), given the whole height of the waves offshore, and cut and
    # beached like a sea shore.
    joined = joined_sea(parent_entity, sea, u, v)
    if joined is not None:
        carried = np.where(joined, carried, 0.0)
    waves = np.maximum(carried, local_wind_sea(free, spacing_m, storm_wind_m_s(parent_entity), gravity))
    # A shore is reached by the waves of the water in front of it, not by
    # what the last cell under the cliff still sees of the compass.
    waves = _highest_nearby(waves, sea, WAVE_FRONT_CELLS)
    filled = spread_from_sea(waves, sea, max(sea.shape))
    rows = np.unique(np.linspace(0, sea.shape[0] - 1, min(WAVE_RECORD_CELLS + 1, sea.shape[0])).round().astype(int))
    columns = np.unique(np.linspace(0, sea.shape[1] - 1, min(WAVE_RECORD_CELLS + 1, sea.shape[1])).round().astype(int))
    record = {
        "source": source,
        "uv_bounds": {"min_u": float(u[0, 0]), "max_u": float(u[0, -1]), "min_v": float(v[0, 0]), "max_v": float(v[-1, 0])},
        "height_m": np.round(filled[np.ix_(rows, columns)], 3).tolist(),
        # What comes in from the ocean, before any level's land sheltered it.
        "offshore_m": np.round(open_sea[np.ix_(rows, columns)], 3).tolist(),
    }
    if joined is not None:
        # Which water is the sea's, for the levels below (``joined_sea``).
        record["open"] = joined[np.ix_(rows, columns)].astype(int).tolist()
    return waves, open_sea, record


def joined_sea(parent_entity, sea, u, v):
    """Water of a level that is joined to the open sea (bool), or ``None`` without a parent grid.

    The sea is the water that reaches, through water, ground its parent
    has under the sea and counts as open itself (each level hands that down
    in its wave record).  Water below sea level that land shuts in, at this
    level or at a coarser one, is a pond or a basin, not the sea.
    """
    parent_heightmap = (parent_entity or {}).get("heightmap_model") or {}
    rows = ((parent_heightmap.get("sample_grid") or {}).get("rows")) or []
    bounds = parent_heightmap.get("source_uv_bounds") or {}
    sea_level = parent_heightmap.get("sea_level_m")
    if not rows or not bounds or sea_level is None:
        return None
    sea = np.asarray(sea, dtype=bool)
    parent_sea = _sample_grid(rows, bounds, u, v) < float(sea_level)
    record = _wave_record(parent_heightmap)
    if record is not None and record.get("open") is not None:
        parent_sea &= _sample_grid(record["open"], record["uv_bounds"], u, v) > 0.5
    return open_water(sea, sea & parent_sea)


def shore_orders(orders):
    """The bed orders that decide how fast a shore goes back: beds metres thick and coarser.

    Waves work on a band a few metres high.  Beds of decimetres (the order
    Site scale builds) are averaged over in that band, and every level must
    read the same rock at the shore, or a finer one finds weak rock where
    its parent saw strong and cuts the shore a second time.
    """
    return [strata for strata in orders or [] if int(strata.get("built_at_level", 0)) <= SHORE_ROCK_ORDER_LEVEL]


def rock_at(level_m, orders, u, v, mix=None):
    """Effective strength (MPa) and failure gradient of the rock at height ``level_m`` of every cell.

    In a layered sequence that is the bed of the finest order at that
    height, whether or not the order's scarps are drawn there (near the sea
    they are faded out; the rock is the same).  Elsewhere it is the parent's
    rock mix (``[(material, share, erodibility, fabric, resistance)]``),
    shares weighted; without either, ``(None, None)``.
    """
    from simulations.world_gen import rock_scarps
    from simulations.world_gen.material_routing import REPOSE_GRADIENT

    level = np.asarray(level_m, dtype=np.float64)
    if orders:
        strata = orders[-1]
        beds = strata["beds"]
        index = np.clip(rock_scarps.bed_at(level - rock_scarps.dip_offset(strata, u, v), strata), 0, len(beds) - 1)
        strength = effective_strength_mpa(np.asarray([float(bed[2]) for bed in beds]))[index]
        faces = np.asarray([rock_scarps.face_gradient(rock_scarps._bed_resistance(bed)) for bed in beds]) * rock_scarps.FAILURE_MARGIN
        weak = max(REPOSE_GRADIENT, float(strata.get("rampart_gradient", rock_scarps.RAMPART_GRADIENT[1])) * rock_scarps.FAILURE_MARGIN)
        return strength, np.where(faces[index] > 0.0, faces[index], weak)
    if mix:
        shares = np.asarray([float(item[1]) for item in mix], dtype=np.float64)
        shares = shares / max(shares.sum(), 1e-12)
        strength = float(10.0 ** np.sum(shares * np.log10(effective_strength_mpa(np.asarray([float(item[2]) for item in mix])))))
        face = rock_scarps.face_gradient(float(np.sum(shares * np.asarray([float(item[4]) for item in mix])))) * rock_scarps.FAILURE_MARGIN
        return np.full(level.shape, strength), np.full(level.shape, face if face > 0.0 else REPOSE_GRADIENT)
    return None, None
