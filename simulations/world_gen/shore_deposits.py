"""Beaches: the sand waves lay along a shore.

Where waves reach a shore that has loose sediment to work on, they sort it
into one form whatever lay there before (Bruun 1954; Dean 1977, 1991):

* **A concave shoreface.**  Under water the bed deepens with the two-thirds
  power of the distance from the shoreline, ``h = A x^(2/3)``, out to the
  depth the largest waves of a year still stir (the depth of closure,
  Hallermeier 1981; Birkemeier 1985: about 1.75 of their height).  ``A``
  grows with grain size (Moore 1982; Dean 1987): 0.1 for fine sand, 0.125
  for the medium sand taken here, 0.2 and more for gravel.
* **A beach face and a berm.**  Above the water the swash builds a slope set
  by the grain (Bascom 1951: 1 in 30 for fine sand, 1 in 10 for medium, 1 in
  5 for shingle) up to the height it runs to, and levels the sand behind
  into a berm.  Run-up is taken from Stockdon et al. (2006) for a sea as
  steep as the wind raises it (Pierson & Moskowitz 1964: the wavelength is
  about 39 wave heights), which makes the berm 0.57 wave heights high on
  the face taken here, whatever the gravity.
* **A smooth plan.**  Sand moves alongshore wherever waves meet the shore at
  an angle, at a rate that goes with the 2.5th power of their height (the
  CERC formula; Komar & Inman 1970), and that evens out the shoreline like
  diffusion (Pelnard-Considere 1956).  For waves of half a metre and more
  the length evened out in the 6,000 years the sea has stood at its level is
  tens of kilometres: on any map finer than a Macroregion a sandy shore is
  as smooth as its sand supply and its rock headlands let it be.  Sand
  therefore fills the re-entrants of a shore (pocket beaches in the coves
  between headlands, bars across the mouths of small inlets, tombolos
  behind islets) and leaves the salients bare.

What limits a beach is sand and room, not time.  Room: sand builds a shore
out only over a bed its waves can reach, so water deeper than the depth of
closure of the waves offshore is not filled (a plunging cove keeps its
water).  Sand: each metre of open shore has a volume to lay down, one
figure for the world until river mouths and cliffs hand theirs down
(``BASE_SAND_M3_PER_M``).  If a level's re-entrants would take more, only
the smaller ones are filled.

The rule is written to find its own result again.  Filling re-entrants up
to a radius is a morphological closing, which changes nothing on a shore
already closed at that radius; sand is only ever added up to the profile,
never taken from ground that stands above it; and the profile is measured
from the shoreline the level ends with.  A finer level therefore adds the
coves its parent's cells could not hold and the beach face they were too
coarse for, and leaves the rest.

Low ground that waves wash over (lower than the berm) and narrower than a
few cells (islets, spits and the speckle a level's detail leaves along a
flat shore) is planed off to the shoreface: waves do not leave it standing.

Abiotic by contract: no foredune (its sand is held by plants), no beach
rock, no reef.  Not built here: shingle and mud (one grain for the world),
barrier islands and lagoons of a shelving coast, beach ridges, cusps and
bars, tides as a process (a tidal range only raises the berm), and the
sand budget of a real littoral cell.
"""

from __future__ import annotations

import base64
import math
import zlib

import numpy as np

from simulations.world_gen import sea_cliffs

MODEL = "wave_built_shore_v1"
LANDFORM_ID = "beaches_and_wave_built_shores"

# h = A x^(2/3): medium sand of about 0.3 mm (Moore 1982; Dean 1987).  From
# memory; unverified against the tables.
SHOREFACE_SCALE_M13 = 0.125
# Slope of the beach face in medium sand (Bascom 1951; Wiegel 1964).
BEACH_FACE_GRADIENT = 0.10
# Depth of closure in heights of the largest waves (Birkemeier 1985: 1.75 H
# less a steepness term).
CLOSURE_DEPTH_WAVE_HEIGHTS = 1.75
# Deep-water wavelength of a fully developed sea in wave heights
# (Pierson & Moskowitz 1964: H = 0.21 U^2 / g, T = 7.14 U / g).
WAVELENGTH_WAVE_HEIGHTS = 38.6
# The berm reaches back this many wave heights behind the top of the face.
BERM_WIDTH_WAVE_HEIGHTS = 10.0
# Sand a metre of open shore has to lay down (m3): the prism of a small to
# middling beach.  One figure for the world; unverified.
BASE_SAND_M3_PER_M = 600.0
# Re-entrants are filled from this radius (cells) up to the radius the
# parent's cells already resolved, or to the cap where no coarser level has
# built beaches.
MIN_CLOSING_CELLS = 1.5
PARENT_CLOSING_CELLS = 2.0
MAX_CLOSING_M = 1500.0
MAX_CLOSING_CELLS = 48
# Low ground narrower than twice this (cells) is washed over.
WASHOVER_CELLS = 1.5
# Waves lower than this build nothing worth a cell.
MIN_WAVE_HEIGHT_M = 0.05
# Water at a tile's rim is open sea if it carries this share of the height
# of the waves offshore.
OPEN_WATER_WAVE_SHARE = 0.25
# Sand this thick hides what lies under it (cover fraction 1).
FULL_COVER_THICKNESS_M = 0.3


def runup_wave_heights(face_gradient=BEACH_FACE_GRADIENT):
    """Height the swash runs to above still water, in deep-water wave heights (Stockdon et al. 2006)."""
    reach = math.sqrt(WAVELENGTH_WAVE_HEIGHTS)
    return 1.1 * reach * (0.35 * face_gradient + 0.5 * math.sqrt(0.563 * face_gradient ** 2 + 0.004))


def berm_height_m(wave_height_m, tidal_range_m=0.0):
    """Height of the berm above mean sea level under waves of this height."""
    return runup_wave_heights() * np.maximum(np.asarray(wave_height_m, dtype=np.float64), 0.0) + 0.5 * float(tidal_range_m)


def closure_depth_m(wave_height_m):
    return CLOSURE_DEPTH_WAVE_HEIGHTS * np.maximum(np.asarray(wave_height_m, dtype=np.float64), 0.0)


def shoreface_depth_m(distance_m):
    """Depth of the wave-built bed this far seaward of the shoreline."""
    return SHOREFACE_SCALE_M13 * np.maximum(np.asarray(distance_m, dtype=np.float64), 0.0) ** (2.0 / 3.0)


def shoreface_width_m(wave_height_m):
    """Distance from the shoreline at which the shoreface reaches the depth of closure."""
    return (closure_depth_m(wave_height_m) / SHOREFACE_SCALE_M13) ** 1.5


def distance_cells(mask, cap):
    """Euclidean distance (cells) from every cell to the nearest cell of ``mask``, at most ``cap + 1``.

    Exact inside the cap: nearest in the row first, then the lower envelope
    over the rows within reach.  Beyond the grid there is nothing.
    """
    mask = np.asarray(mask, dtype=bool)
    height, width = mask.shape
    cap = int(cap)
    far = float(cap + 1)
    column = np.arange(width, dtype=np.float64)[None, :] * np.ones((height, 1))
    left = np.maximum.accumulate(np.where(mask, column, -np.inf), axis=1)
    right = np.minimum.accumulate(np.where(mask, column, np.inf)[:, ::-1], axis=1)[:, ::-1]
    along = np.minimum(np.minimum(column - left, right - column), far)
    best = np.full(mask.shape, far * far)
    padded = np.pad(along, ((cap, cap), (0, 0)), constant_values=far)
    for offset in range(-cap, cap + 1):
        np.minimum(best, padded[cap + offset:cap + offset + height, :] ** 2 + float(offset * offset), out=best)
    return np.minimum(np.sqrt(best), far)


def closing(mask, radius_cells):
    """``mask`` with every re-entrant a disc of this radius cannot enter filled (morphological closing)."""
    cap = int(math.ceil(radius_cells)) + 1
    # Beyond the grid the shore goes on as it reaches the edge.  Taking the
    # outside for open water instead leaves the rim unclosed at a large
    # radius and closed at a small one, and a finer level then fills what
    # its parent seemed to have left.
    padded = np.pad(np.asarray(mask, dtype=bool), cap, mode="edge")
    grown = distance_cells(padded, cap) <= radius_cells
    kept = distance_cells(~grown, cap) > radius_cells
    return kept[cap:-cap, cap:-cap] | np.asarray(mask, dtype=bool)


def opening(mask, radius_cells):
    """``mask`` without the parts a disc of this radius does not fit into (morphological opening)."""
    cap = int(math.ceil(radius_cells)) + 1
    # Beyond the grid the land goes on: a shore is not worn back from the tile's edge.
    padded = np.pad(np.asarray(mask, dtype=bool), cap, mode="edge")
    core = distance_cells(~padded, cap) > radius_cells
    return (distance_cells(core, cap) <= radius_cells)[cap:-cap, cap:-cap] & np.asarray(mask, dtype=bool)


def _pack(grid, top):
    scaled = np.clip(np.asarray(grid, dtype=np.float64) / max(top, 1e-9), 0.0, 1.0)
    return base64.b64encode(zlib.compress(np.round(scaled * 255.0).astype(np.uint8).tobytes(), 6)).decode("ascii")


def _unpack(packed, shape, top):
    data = np.frombuffer(zlib.decompress(base64.b64decode(packed)), dtype=np.uint8)
    return data.reshape(shape).astype(np.float64) * (float(top) / 255.0)


def open_sea_parts(sea, depth, at_sea, offshore):
    """``(seeds, rim_sea, outer)``: the sea the waves come in from.

    ``outer`` is the water joined to water deep enough to carry the waves
    offshore (``seeds``), or to open sea at the tile's rim.  A tile may lie
    wholly in shallow water: then the open sea is the water at its rim that
    still carries a good part of the ocean's waves (the heights are handed
    down from levels that saw the whole coast).  Water at the rim with only
    ripples on it is a creek or a pond, not the sea.
    """
    carries = at_sea >= OPEN_WATER_WAVE_SHARE * offshore
    # Deep water with only ripples on it is a pond the land shuts in, however deep.
    seeds = sea & carries & (depth >= sea_cliffs.BREAKING_DEPTH_WAVE_HEIGHTS * offshore)
    rim = np.zeros(sea.shape, dtype=bool)
    rim[0, :] = rim[-1, :] = rim[:, 0] = rim[:, -1] = True
    rim_sea = rim & sea & carries
    return seeds, rim_sea, sea_cliffs.open_water(sea, seeds | rim_sea)


def open_sea(elevation, sea_level, wave_height_m, offshore_wave_height_m=None):
    """The cells of open sea in front of a shore (bool), as ``build_shore`` takes them."""
    ground = np.asarray(elevation, dtype=np.float64)
    sea = ground < float(sea_level)
    at_sea = np.where(sea, np.asarray(wave_height_m, dtype=np.float64), 0.0)
    offshore = np.broadcast_to(
        np.asarray(float(at_sea.max()) if offshore_wave_height_m is None else offshore_wave_height_m, dtype=np.float64), ground.shape)
    return open_sea_parts(sea, float(sea_level) - ground, at_sea, offshore)[2]


def sand_within_reach(sand_m, elevation, sea_level, wave_height_m, tidal_range_m=0.0):
    """Sand a coarser level handed down, kept only on a bed the waves could cover (m).

    A parent's beach cell hands its sand to every cell under it, also to
    the cliff top this level resolves inside it: on an arid Site tile a
    tenth of the cells with sand stood more than 29 m above the sea, were
    beach to the materials and were held as laid ground.  Where the bed
    under the sand would stand above the highest berm the waves build,
    the cell carries none.
    """
    sand = np.maximum(np.asarray(sand_m, dtype=np.float64), 0.0)
    highest_berm = float(berm_height_m(float(np.max(wave_height_m)), tidal_range_m))
    return np.where(np.asarray(elevation, dtype=np.float64) - sand <= float(sea_level) + highest_berm, sand, 0.0)


def build_shore(
    elevation, sea_level, *, dx, dy, wave_height_m, offshore_wave_height_m=None, tidal_range_m=0.0, fade=None,
    parent_spacing_m=0.0, sand_below_m=None, sand_m3_per_m=BASE_SAND_M3_PER_M, keep_open=None, open_sea=None,
):
    """The beach waves have built along a shore, as a height change.

    ``elevation`` is the ground with every other landform of the level in
    it (the cut shore included); ``wave_height_m`` the height of the waves
    reaching each cell (``[H, W]``: the sea cells count) and
    ``offshore_wave_height_m`` their height before this level's land
    sheltered them; ``sand_below_m`` the sand a coarser level has laid on
    each cell already (this level then fills only the re-entrants that
    level's cells could not hold, and judges the room for sand by the bed
    under it, not by the sand itself); ``keep_open`` marks water sand may
    not close (a river's way out); ``open_sea`` the water that is the sea's
    (``sea_cliffs.joined_sea``; without it, judged from depth and waves).

    Returns ``(change, sand_m, record)``: the height change (sand laid down
    ``> 0``, washed-over ground planed off ``< 0``), the thickness of sand
    on each cell, and the landform record; ``(None, None, record)`` where no
    shore is built.
    """
    ground = np.asarray(elevation, dtype=np.float64)
    sea_level = float(sea_level)
    sea = ground < sea_level
    record = {"landform": LANDFORM_ID, "model": MODEL, "beach_cells": 0}
    if not sea.any() or sea.all():
        return None, None, record
    spacing = math.sqrt(dx * dy)
    at_sea = np.where(sea, np.asarray(wave_height_m, dtype=np.float64), 0.0)
    offshore = np.broadcast_to(
        np.asarray(float(at_sea.max()) if offshore_wave_height_m is None else offshore_wave_height_m, dtype=np.float64), ground.shape)
    if float(at_sea.max()) < MIN_WAVE_HEIGHT_M:
        return None, None, record
    depth = sea_level - ground
    inherited = sand_below_m is not None
    below = np.maximum(np.asarray(sand_below_m, dtype=np.float64), 0.0) if inherited else np.zeros(ground.shape)
    if inherited:
        below = sand_within_reach(below, ground, sea_level, float(at_sea.max()), tidal_range_m)
    # The bed under whatever sand lies there already.  Room for sand is
    # judged by it: judged by the sand surface, every level would find the
    # last one's shoreface shallow enough to build the shore out over.
    firm = ground - below
    if open_sea is None:
        seeds, rim_sea, outer = open_sea_parts(sea, depth, at_sea, offshore)
    else:
        outer = np.asarray(open_sea, dtype=bool) & sea
        rim_sea = np.zeros(sea.shape, dtype=bool)
        rim_sea[0, :] = rim_sea[-1, :] = rim_sea[:, 0] = rim_sea[:, -1] = True
        rim_sea &= outer
        seeds = outer & (depth >= sea_cliffs.BREAKING_DEPTH_WAVE_HEIGHTS * offshore)
        if not (seeds | rim_sea).any():
            seeds = outer
    if not outer.any():
        return None, None, record
    shore_side = ~outer
    # Waves at the land: those of the water in front of it.
    reach = int(math.ceil(max(4.0, MAX_CLOSING_CELLS + 4)))
    around = sea_cliffs.spread_from_sea(np.where(outer, at_sea, 0.0), outer, reach)

    # Low ground the waves wash over, too narrow to stand: planed off.  Sand
    # a coarser level laid is not such ground (a bar across a cove is narrow
    # and low, and is the beach).
    low = shore_side & ~sea & (ground < sea_level + berm_height_m(around, tidal_range_m)) & (below <= 0.0)
    washed = low & ~opening(shore_side, WASHOVER_CELLS)
    solid = shore_side & ~washed

    # Re-entrants sand can fill: within the radius this level is to close,
    # over a bed the waves offshore can reach.
    cells_per_parent = float(parent_spacing_m) / spacing if parent_spacing_m and parent_spacing_m > 0.0 else 0.0
    if inherited and cells_per_parent > 0.0:
        top_radius = PARENT_CLOSING_CELLS * cells_per_parent
    else:
        top_radius = MAX_CLOSING_M / spacing
    top_radius = float(min(top_radius, MAX_CLOSING_CELLS, 0.25 * min(ground.shape)))
    fillable = outer & (sea_level - firm <= closure_depth_m(offshore))
    if keep_open is not None:
        fillable &= ~np.asarray(keep_open, dtype=bool)
    shoreline_cells = float(
        (solid[:, 1:] != solid[:, :-1]).sum() + (solid[1:, :] != solid[:-1, :]).sum())
    budget = float(sand_m3_per_m) * shoreline_cells * spacing

    def laid(radius):
        """Sand surface, deposit and the new land for re-entrants closed at ``radius`` cells."""
        filled = np.zeros(ground.shape, dtype=bool)
        # Everything on the land's side of the open sea.
        beach_land = solid.copy()
        if radius >= MIN_CLOSING_CELLS:
            # Sand that fills part of a re-entrant (the rest is too deep)
            # makes smaller ones beside itself, and a bar across a cove
            # shuts the water behind it in, which is then no longer shore
            # to the open sea.  Closed again until nothing is added, so
            # that the rule finds nothing more to do on its own result.
            for _round in range(8):
                more = closing(beach_land, radius) & fillable & ~beach_land
                filled |= more
                beach_land |= more
                shut = ~beach_land & ~sea_cliffs.open_water(~beach_land, (seeds | rim_sea) & ~beach_land)
                beach_land |= shut
                if not more.any() and not shut.any():
                    break
        # Washed-over ground the sand has closed in is beach, not a pool in it.
        filled |= beach_land & washed
        water = ~beach_land
        front_water = water
        # Berm and shoreface belong to the waves of the water the shore ends
        # up facing, not to the ripples of the cove the sand has filled.
        waves = sea_cliffs.spread_from_sea(np.where(front_water, around, 0.0), front_water, reach)
        berm = berm_height_m(waves, tidal_range_m)
        cap = int(math.ceil(max(float(shoreface_width_m(float(waves.max()))) / spacing, 2.0))) + 2
        cap = min(cap, max(ground.shape))
        seaward = np.maximum(distance_cells(beach_land, cap) - 0.5, 0.0) * spacing
        back = int(math.ceil((float(berm.max()) / BEACH_FACE_GRADIENT + BERM_WIDTH_WAVE_HEIGHTS * float(waves.max())) / spacing)) + 2
        back = min(max(back, 2 * int(math.ceil(radius)) + 2), max(ground.shape))
        landward = np.maximum(distance_cells(front_water, back) - 0.5, 0.0) * spacing
        width = np.maximum(shoreface_width_m(waves), 1e-6)
        # On a bed that falls away faster than the profile the sand is a
        # prism against the shore, as thick at most as the waves reach deep
        # and thinning to nothing at the foot of the shoreface: a plunging
        # shore has no room for more.
        prism = firm + closure_depth_m(waves) * np.clip(1.0 - seaward / width, 0.0, 1.0)
        profile = sea_level - shoreface_depth_m(seaward)
        on_shoreface = front_water & (seaward <= width) & (waves >= MIN_WAVE_HEIGHT_M)
        face = sea_level + np.minimum(berm, BEACH_FACE_GRADIENT * landward)
        backshore = BERM_WIDTH_WAVE_HEIGHTS * waves + berm / BEACH_FACE_GRADIENT
        # Water the land shuts in (a pond behind the shore, a lagoon behind a
        # bar) is left as it is: the swash does not reach over to fill it.
        on_beach = beach_land & (filled | (~sea & (landward <= backshore))) & (waves >= MIN_WAVE_HEIGHT_M) & (landward <= back * spacing)
        surface = np.where(on_shoreface, np.minimum(profile, prism), np.where(on_beach, face, -np.inf))
        deposit = np.where(np.isfinite(surface), np.maximum(surface - ground, 0.0), 0.0)
        # Washed-over ground comes down to the shoreface; it is never raised here.
        cut = np.where(washed & water, np.minimum(profile - ground, 0.0), 0.0)
        deposit = np.where(washed & water, 0.0, deposit)
        return deposit, cut, filled, waves, berm

    radius = top_radius
    deposit, cut, filled, waves, berm = laid(radius)
    volume = float(deposit.sum()) * dx * dy
    low_radius = 0.0
    if volume > budget and radius >= MIN_CLOSING_CELLS:
        # More room than sand: only the smaller re-entrants are filled.
        high_radius = radius
        for _step in range(6):
            middle = 0.5 * (low_radius + high_radius)
            trial = laid(middle)
            if float(trial[0].sum()) * dx * dy > budget:
                high_radius = middle
            else:
                low_radius = middle
        radius = low_radius
        deposit, cut, filled, waves, berm = laid(radius)
        volume = float(deposit.sum()) * dx * dy
    change = deposit + cut
    if fade is not None:
        weight = np.asarray(fade, dtype=np.float64)
        change = change * weight
        deposit = deposit * weight
    sand = np.where(change > 0.0, deposit, 0.0)
    if not np.any(np.abs(change) > 1e-6):
        return None, None, record
    after = ground + change
    beach = (sand > 0.02) & (after >= sea_level)
    shoreface = (sand > 0.02) & (after < sea_level)
    record.update({
        "beach_cells": int(beach.sum()),
        "shoreface_cells": int(shoreface.sum()),
        "new_land_cells": int(((after >= sea_level) & sea).sum()),
        "washed_over_cells": int((change < -1e-6).sum()),
        "sand_volume_m3": round(float(sand.sum()) * dx * dy, 1),
        "sand_budget_m3": round(budget, 1),
        "closing_radius_m": round(radius * spacing, 1),
        "closing_radius_limit_m": round(top_radius * spacing, 1),
        "max_thickness_m": round(float(sand.max()), 2),
        "berm_height_m": [round(float(value), 2) for value in (berm[beach].min(), berm[beach].max())] if beach.any() else [],
        "closure_depth_m": round(float(closure_depth_m(float(offshore.max()))), 2),
        "wave_height_m": [round(float(waves[sand > 0.0].min()), 2), round(float(waves[sand > 0.0].max()), 2)] if (sand > 0.0).any() else [],
        "tidal_range_m": round(float(tidal_range_m), 2),
        "inherited": bool(inherited),
    })
    return change, np.where(after >= ground, below, 0.0) + sand, record


# --- what the other layers read ---------------------------------------------------


def with_sand_grid(record, sand_m, inherited_sand_m=None):
    """``record`` with the thickness of sand on every cell packed into it (own and inherited)."""
    total = np.zeros(np.shape(sand_m if sand_m is not None else inherited_sand_m))
    if sand_m is not None:
        total = total + np.asarray(sand_m, dtype=np.float64)
    if inherited_sand_m is not None:
        total = np.maximum(total, np.asarray(inherited_sand_m, dtype=np.float64))
    top = float(total.max()) if total.size else 0.0
    if top <= 0.0:
        return record
    record = dict(record)
    record["sand"] = {"shape": [int(total.shape[0]), int(total.shape[1])], "max_m": round(top, 3), "data": _pack(total, top)}
    return record


def shore_record(heightmap):
    for landform in (((heightmap or {}).get("regional_landforms") or {}).get("landforms") or []):
        if isinstance(landform, dict) and landform.get("landform") == LANDFORM_ID:
            return landform
    return None


def record_sand_m(record):
    """Thickness of sand on the grid a record was made on, or ``None``."""
    packed = (record or {}).get("sand")
    if not isinstance(packed, dict) or not packed.get("data"):
        return None
    return _unpack(packed["data"], tuple(int(value) for value in packed["shape"]), float(packed["max_m"]))


def inherited_sand_m(parent_heightmap, u, v):
    """The parent's sand at this level's cells (``u, v`` global), or ``None``."""
    record = shore_record(parent_heightmap)
    sand = record_sand_m(record)
    bounds = (parent_heightmap or {}).get("source_uv_bounds")
    if sand is None or not bounds:
        return None
    return sea_cliffs._sample_grid(sand, bounds, u, v)


def heightmap_shore_fields(heightmap, shape=None):
    """``{"thickness", "cover"}`` of beach and shoreface sand on a heightmap's grid, or ``None``."""
    sand = record_sand_m(shore_record(heightmap))
    if sand is None:
        return None
    if shape is not None and tuple(shape) != sand.shape:
        return None
    return {"thickness": sand, "cover": np.clip(sand / FULL_COVER_THICKNESS_M, 0.0, 1.0)}
