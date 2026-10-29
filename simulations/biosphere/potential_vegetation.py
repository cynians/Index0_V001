"""What grows where: the cover each plant of a flora holds on a piece of ground.

Given ground (a substrate), the floras of its planet and the species'
profiles, this works out the vegetation an established biome carries there,
without playing it through.  It is the Biosphere kernel's own arithmetic read
at its balance:

* a species grows only in the biomes whose flora it is part of;
* on each piece of ground it reaches the cover the kernel expects of it
  there (``expected_cover`` of what the built ground gives it);
* the tallest layer is settled first and takes the light of those below;
* within a layer the species share the ground, the commoner first;
* every species stands under and beside the others as the kernel sets its
  stands against each other: what shares its ground takes room from its
  growth (a far smaller plant little, any other most of its cover), and what
  stands well above it adds to its losses.  A sward under closed trees
  therefore settles at about a third of what it holds in the open, as it
  does when played;
* a species that is not common holds a share of the ground that suits it:
  one that spreads by runners in patches of its own, as thick as it can
  stand, one that comes from seed on more ground and thinner (``aggregation``);
* a climber is no layer of its own: it stands in the crowns of the woody
  plants that carry it, and nowhere else;
* a plant bears the sea water in reach of its roots by its tolerance of
  salt, where the map tells whose water the ground water is
  (``ecology.salt_in_reach``): a lily holds no sea, an oak no ground the
  tides flood;
* a plant that roots under water holds only the shallows
  (``AQUATIC_DEPTH_M``; not in the played kernel yet);
* on ground the river reworks, a species stands on the share of it that has
  been left alone for as long as the species takes to grow up
  (``ecology.flood_standing_share``; the played kernel has the floods
  themselves, year by year).

The ground is read as the kernel reads it: its wetness as the terrain spread
it (wet hollows and banks stay wetter than rises under a built soil), the
depth of ground that can be rooted against the depth a species roots to, and
the sunlight its slope receives.  Where the map carries the demand of the
air, wetness is the year's water balance of the plant asked about
(``water_balance``): rain against demand, what the soil it roots through
stores, what runs on, and the ground water its roots or the capillary rise
of the ground reach.

The result is a few plants that make up each layer and others met here and
there, sorted along the ground's wetness and height.

Where a species' patches lie and where its single plants stand is the planet's
to say, not a map's: both are placed in the planet's own coordinates
(``GroundFrame``), a patch by a noise ranked over the whole planet, a plant on
a lattice of places the planet keeps.  The Site, the Parcel cut out of it, the
Plot and the Survey under that, a city's map and a Biosphere founded there all
show the same woods and the same trees; a finer map only reads the ground
they stand on more closely.

The arithmetic runs on a lattice of cells; what is drawn from it does not show
the lattice.  The outline of a species' patches and of the water is read at
the point asked for (``ResidentVegetation.cover_at``), so single plants set
out from the cover end along a curve, not along the edge of a cell.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import math

import numpy as np

from simulations.biosphere.biomes import biome_grid
from simulations.biosphere.ecology import (
    FLOOD_NEVER_YEARS, FLOOD_REWORKING_FIELD, _DISPERSAL_REACH_M, BiosphereEcology, expected_cover_array,
    flood_standing_share, mature_wetness, potential_suitability, rooting_depth_m, salt_in_reach, thermal_response_array,
    years_to_grow,
)
from simulations.biosphere.water_balance import (
    DEFAULT_AVAILABLE_WATER_MM_PER_M, DEFAULT_CAPILLARY_RISE_M, monthly_demand, monthly_rain, plant_wetness,
)


# Layers from the top down, by the height a species reaches: each shades those below it.
LAYERS = (("canopy", 8.0), ("understorey", 2.0), ("field", 0.3), ("ground", 0.0))
# A patch of a species that is not everywhere is this many times its reach across, within these bounds in metres.
PATCH_REACH_FACTOR = 8.0
PATCH_SCALE_M = (40.0, 400.0)
# A climber's place: on the shrubs and trees, of whose crowns all climbers together take at most this share.
CLIMBER_LAYER = "climber"
CLIMBER_SUPPORT_SHARE = 0.5
WOODY_FORMS = {"tree", "shrub", "subshrub"}
# A plant rooted under water holds all of it down to the first depth, in metres, and none from the second.
AQUATIC_DEPTH_M = (1.5, 3.0)
# Every species presses on every other, so the covers are settled in rounds: the first as if nothing stood
# below a plant, each further one with what the round before left standing.  The pressure a neighbour's
# cover puts on a stand is under half of that cover, so three rounds bring the covers to within a few
# hundredths of their balance.
BALANCE_ROUNDS = 3
# A crust (a lichen on stone) holds ground with less soil than this, in metres, as far as it is that thin
# and nothing that roots covers it.
CRUST_SOIL_DEPTH_M = 0.15
# Cells along a side when the ground of a whole map is read: a city's map of it, and a Biosphere's view of
# what lies far from its living area (``surroundings``).
MAP_CELLS = 128

# How much a species keeps to patches of its own instead of standing thinly wherever the ground suits it,
# by how it spreads.  At 1 its rarity is the share of that ground it is met on at all, and there it stands
# as thick as it can: beds and colonies, what a plant that spreads by runners makes.  At 0 it would be met
# everywhere, at that share of its cover.  In between it is met on more ground and stands thinner there: a
# plant that comes from seed, scattered through the others.  The cover it holds in all is the same.
AGGREGATION = {"high": 1.0, "moderate": 0.8}
SEEDED_AGGREGATION = 0.5


def aggregation(profile):
    """How much a species keeps to patches of its own, 0..1 (``AGGREGATION``)."""
    told = AGGREGATION.get(getattr(profile, "clonal_spread", None))
    if told is not None:
        return told
    if profile.surface_growth_profile or profile.growth_form == "lichen":
        return 1.0
    return 0.8 if profile.growth_form == "graminoid" else SEEDED_AGGREGATION


# -- Time: not all ground is as old as it can be --------------------------------------------------------------
# A wood loses about a hundredth of its canopy a year to wind and to trees that die standing, in gaps of a
# tree or a few (Runkle 1985, old temperate woods; from memory, not looked up): smaller than a cell of a map,
# so every cell of wood has its share of gaps.
GAP_RETURN_YEARS = 100.0
# What is thrown or burnt covers its ground again long before it is full-grown: within this share of the
# years it takes to grow up, and a woody plant in no fewer years than these.
CLOSURE_SHARE_OF_GROWING, WOODY_CLOSURE_YEARS = 0.3, 5.0
# How much sooner a plant that sprouts again from its stock is back after a fire, by its ``resprouting``.
RESPROUT_RECOVERY = {"strong": 0.15, "moderate": 0.4, "weak": 0.75}
# A fire takes a patch about this many metres across.
FIRE_PATCH_M = 600.0


def fire_return_years(rain_mm, demand_mm, driest_month_mm=None, coldest_c=None):
    """Years between two fires on a piece of ground under a climate, or ``None`` where none burns.

    Fire needs something to burn and a time dry enough to burn it (Bond &
    Keeley 2005; boreal cycles after Johnson 1992; from memory, a first
    reading in classes): a desert grows too little, ground wet through the
    year is never dry enough, grass under a dry season burns every few
    years, dry woodland every few decades, a cold conifer wood once in a
    century or two, a moist temperate wood hardly ever.
    """
    try:
        rain, demand = float(rain_mm), float(demand_mm)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(rain) and math.isfinite(demand)) or demand <= 0.0:
        return None
    wet = rain / demand
    driest = float(driest_month_mm) if driest_month_mm is not None and math.isfinite(float(driest_month_mm)) else None
    coldest = float(coldest_c) if coldest_c is not None and math.isfinite(float(coldest_c)) else None
    dry_season = driest is not None and driest < 0.25 * rain / 12.0
    if wet < 0.2:
        return None
    if dry_season and coldest is not None and coldest >= 15.0:
        return 4.0
    if wet < 0.4:
        return 8.0
    if wet < 1.0:
        return 35.0 if dry_season else 120.0
    if wet >= 1.5 and not dry_season:
        return None
    return 150.0 if coldest is not None and coldest < -3.0 else 400.0


def stand_age_years(position, return_years, seed):
    """Years since fire last took what stood at each place of a planet (``GroundFrame.world`` positions).

    Fires come without memory, so the ages of a ground burnt every
    ``return_years`` on average are spread as ``exp(-age / return)`` (Van
    Wagner 1978): most of it young, some of it very old.  They lie in
    patches, the planet's own: the same on every map of the ground.
    """
    rank = _ranked(_patch_noise("fire", position, FIRE_PATCH_M, seed))
    return -float(return_years) * np.log(np.clip(1.0 - rank, 1e-6, 1.0))


def closure_years(profile):
    """Years until a species covers its ground again after what stood there was taken."""
    woody = profile.growth_form in WOODY_FORMS
    return max(WOODY_CLOSURE_YEARS if woody else 1.0, CLOSURE_SHARE_OF_GROWING * years_to_grow(profile))


def recovery_years(profile):
    """``closure_years`` after a fire: sooner for a plant that sprouts again from its stock."""
    return closure_years(profile) * RESPROUT_RECOVERY.get(getattr(profile, "resprouting", None), 1.0)


def layer_of(profile):
    if profile.growth_form == "vine":
        return CLIMBER_LAYER  # however long it grows, it is as tall as what it climbs
    return next(name for name, least in LAYERS if profile.mature_height_m >= least)


class GroundFrame:
    """Where a map's metre frame lies on its planet.

    What grows on a piece of ground is the planet's, not a map's: a wood seen
    on a Site's map has to be the same wood on the Parcel cut out of it, and
    in a Biosphere founded there.  So patches and single plants are placed in
    the planet's own coordinates, and every map says where on the planet its
    frame lies (``source_uv_bounds`` of its heightmap and the planet's
    circumference).  Ground that does not say (a hand-built plot, a test's
    fixture) is a plane of its own: its metres are its world.
    """

    def __init__(self, bounds=None, uv_bounds=None, circumference_m=None):
        self.flat = not (bounds and uv_bounds and circumference_m)
        if self.flat:
            return
        self.min_x, self.min_y = float(bounds["min_x"]), float(bounds["min_y"])
        self.width, self.height = float(bounds["max_x"]) - self.min_x, float(bounds["max_y"]) - self.min_y
        self.min_u, self.min_v = float(uv_bounds["min_u"]), float(uv_bounds["min_v"])
        self.span_u, self.span_v = float(uv_bounds["max_u"]) - self.min_u, float(uv_bounds["max_v"]) - self.min_v
        self.circumference_m = float(circumference_m)
        self.radius_m = self.circumference_m / math.tau

    @classmethod
    def of(cls, substrate):
        """The frame of a substrate (``worldgen_substrate``), flat where it does not tell its place."""
        base = getattr(substrate, "base", substrate)
        heightmap, bounds = getattr(base, "heightmap", None), getattr(base, "bounds", None)
        if not isinstance(heightmap, dict) or not isinstance(bounds, dict):
            return cls()
        uv, circumference = heightmap.get("source_uv_bounds"), heightmap.get("planet_circumference_m")
        width = float(heightmap.get("region_width_m") or 0.0)
        try:
            spans = (float(uv["max_u"]) - float(uv["min_u"]) > 0.0 and float(uv["max_v"]) - float(uv["min_v"]) > 0.0
                     and float(circumference) > 0.0 and width > 0.0)
            # The bounds have to be the map's own metre frame for the two to be laid on each other.
            in_metres = abs((float(bounds["max_x"]) - float(bounds["min_x"])) - width) <= 0.02 * width
        except (KeyError, TypeError, ValueError):
            return cls()
        return cls(bounds, uv, circumference) if spans and in_metres else cls()

    def uv(self, x, y):
        """Frame metres as planet map coordinates (as they are, on a plane)."""
        x, y = np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64)
        if self.flat:
            return x, y
        return self.min_u + (x - self.min_x) / self.width * self.span_u, self.min_v + (y - self.min_y) / self.height * self.span_v

    def from_uv(self, u, v):
        if self.flat:
            return np.asarray(u, dtype=np.float64), np.asarray(v, dtype=np.float64)
        return (self.min_x + (np.asarray(u, dtype=np.float64) - self.min_u) / self.span_u * self.width,
                self.min_y + (np.asarray(v, dtype=np.float64) - self.min_v) / self.span_v * self.height)

    def world(self, x, y):
        """Frame metres as a place in the planet's own space, in metres: the same for every map of the ground."""
        u, v = self.uv(x, y)
        if self.flat:
            return u, v, np.zeros(np.shape(u))
        longitude, latitude = u * math.tau, (0.5 - v) * math.pi
        across = self.radius_m * np.cos(latitude)
        return across * np.cos(longitude), across * np.sin(longitude), self.radius_m * np.sin(latitude)

    def places(self, window, cell_m):
        """The planet's own places for single plants within a window: ``(x, y, key)``, one to a cell of ``cell_m``.

        The cells are the planet's: rows of equal height from pole to pole,
        each divided into as many columns as give cells of the same width, so
        a cell covers the same ground wherever it lies.  Every cell has one
        place in it and a key of its own; whichever map asks, and for
        whichever window, the places are the same.
        """
        min_x, min_y, max_x, max_y = (float(value) for value in window)
        empty = np.empty(0), np.empty(0), np.empty(0, dtype=np.uint64)
        if max_x <= min_x or max_y <= min_y or cell_m <= 0.0:
            return empty
        if self.flat:
            row_height = column_width = None
            first_row, last_row = math.floor(min_y / cell_m), math.floor(max_y / cell_m)
            rows = np.arange(first_row, last_row + 1, dtype=np.int64)
            columns_in = np.full(len(rows), 0, dtype=np.int64)
            first = np.full(len(rows), math.floor(min_x / cell_m), dtype=np.int64)
            last = np.full(len(rows), math.floor(max_x / cell_m), dtype=np.int64)
        else:
            (u0, u1), (v0, v1) = self.uv(np.array([min_x, max_x]), np.array([min_y, max_y]))
            row_height = cell_m / (0.5 * self.circumference_m)   # of v, which runs pole to pole over half the girth
            rows = np.arange(math.floor(v0 / row_height), math.floor(v1 / row_height) + 1, dtype=np.int64)
            latitude = (0.5 - (rows + 0.5) * row_height) * math.pi
            columns_in = np.maximum(1, np.rint(self.circumference_m * np.cos(latitude) / cell_m)).astype(np.int64)
            first, last = np.floor(u0 * columns_in).astype(np.int64), np.floor(u1 * columns_in).astype(np.int64)
        count = last - first + 1
        total = int(count.sum())
        if total <= 0 or total > 20_000_000:
            return empty
        row = np.repeat(rows, count)
        column = np.repeat(first, count) + (np.arange(total) - np.repeat(np.cumsum(count) - count, count))
        with np.errstate(over="ignore"):
            key = (row.astype(np.uint64) * np.uint64(0xD6E8FEB86659FD93)) ^ (column.astype(np.uint64) * np.uint64(0xC2B2AE3D27D4EB4F))
        if self.flat:
            return (column + _uniform(key, 1)) * cell_m, (row + _uniform(key, 2)) * cell_m, key
        x, y = self.from_uv((column + _uniform(key, 1)) / np.repeat(columns_in, count), (row + _uniform(key, 2)) * row_height)
        return x, y, key


def planet_seed(planet_id):
    """The number a planet's vegetation is placed by: one for all its maps, cities and Biosphere sites."""
    return int.from_bytes(hashlib.sha256(f"{planet_id}:vegetation".encode("utf-8")).digest()[:4], "big")


# Four grains from the patch's own size down to a few metres, each on a lattice turned its own way: the outline
# of a patch is ragged at every scale it is looked at, and nowhere runs along a lattice's lines.
_PATCH_GRAINS = ((0.50, 1.0), (0.25, 0.43), (0.15, 0.19), (0.10, 0.08))


def _turn(digest, octave):
    """A rotation of space for one grain of one species' noise."""
    a, b, c = (digest[8 + octave * 3 + number] / 255.0 * math.tau for number in range(3))
    ca, sa, cb, sb, cc, sc = math.cos(a), math.sin(a), math.cos(b), math.sin(b), math.cos(c), math.sin(c)
    return ((cb * cc, sa * sb * cc - ca * sc, ca * sb * cc + sa * sc),
            (cb * sc, sa * sb * sc + ca * cc, ca * sb * sc - sa * cc),
            (-sb, sa * cb, ca * cb))


def _patch_noise(species_id, position, scale_m, seed):
    """A number for any place of a planet, smooth over ``scale_m``; each species has its own.

    ``position`` is ``(X, Y, Z)`` in metres in the planet's own space
    (``GroundFrame.world``), so the number at a place is the same on every
    map that shows it.  Where its rank among all its values (``_ranked``) is
    below a share ``p`` lies a set of patches that covers ``p`` of the
    planet: what a species of that rarity is met on.
    """
    digest = hashlib.sha256(f"{seed}:{species_id}".encode("utf-8")).digest()
    salt = np.uint64(int.from_bytes(digest[:8], "big"))
    X, Y, Z = (np.asarray(part, dtype=np.float64) for part in position)
    value = 0.0
    for octave, (weight, grain) in enumerate(_PATCH_GRAINS):
        turn = _turn(digest, octave)
        size = scale_m * grain
        g = [(turn[axis][0] * X + turn[axis][1] * Y + turn[axis][2] * Z) / size for axis in range(3)]
        whole = [np.floor(part) for part in g]
        part = [g[axis] - whole[axis] for axis in range(3)]
        ease = [f * f * f * (f * (f * 6.0 - 15.0) + 10.0) for f in part]
        cell = [w.astype(np.int64) for w in whole]
        total = 0.0
        for dx in (0, 1):
            for dy in (0, 1):
                for dz in (0, 1):
                    with np.errstate(over="ignore"):
                        key = ((cell[0] + dx).astype(np.uint64) * np.uint64(0x9E3779B97F4A7C15)
                               ^ (cell[1] + dy).astype(np.uint64) * np.uint64(0xC2B2AE3D27D4EB4F)
                               ^ (cell[2] + dz).astype(np.uint64) * np.uint64(0x165667B19E3779F9)
                               ^ (salt + np.uint64(octave * 7919)))
                    # A direction for the corner: which way the number rises there.
                    height = 1.0 - 2.0 * _uniform(key, 5)
                    around = math.tau * _uniform(key, 6)
                    flat = np.sqrt(np.maximum(0.0, 1.0 - height * height))
                    rise = (flat * np.cos(around) * (part[0] - dx) + flat * np.sin(around) * (part[1] - dy)
                            + height * (part[2] - dz))
                    total = total + rise * ((ease[0] if dx else 1.0 - ease[0]) * (ease[1] if dy else 1.0 - ease[1])
                                            * (ease[2] if dz else 1.0 - ease[2]))
        value = value + weight * total
    return value


def _uniform(key, stream):
    """A number in 0..1 for every key, the same at every call; another for another ``stream``."""
    with np.errstate(over="ignore"):
        z = key + np.uint64((0x9E3779B97F4A7C15 * stream) & 0xFFFFFFFFFFFFFFFF)
        z = (z ^ (z >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
        z = (z ^ (z >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
        z = z ^ (z >> np.uint64(31))
    return (z >> np.uint64(11)).astype(np.float64) / float(1 << 53)


def plant_number(marks, stream):
    """A number in 0..1 for every plant by its mark (``ResidentVegetation.individuals``); another for another ``stream``."""
    return _uniform(np.asarray(marks, dtype=np.uint64), 16 + int(stream))


_NOISE_RANKS = None


def _ranked(noise):
    """Where each value of the patch noise stands among all its values, in 0..1: every rank as frequent on a planet.

    The ranks are the planet's, not a window's: a plant met on a twentieth
    of the ground is met on a twentieth of the planet, in patches, and a
    window may hold a patch of it or none.
    """
    global _NOISE_RANKS
    if _NOISE_RANKS is None:
        rng = np.random.default_rng(20261011)
        # The noise is the same in kind for every species and scale: its values over a wide stretch of space.
        sample = rng.uniform(-4000.0, 4000.0, (3, 200_000))
        _NOISE_RANKS = np.sort(_patch_noise("ranks", sample, 1.0, 0))
    return (np.searchsorted(_NOISE_RANKS, noise) + 0.5) / len(_NOISE_RANKS)


@dataclass
class ResidentVegetation:
    """The vegetation of a piece of ground: cover per species on a lattice of cells."""

    bounds: dict
    x: np.ndarray
    y: np.ndarray
    biome_index: np.ndarray
    biomes: list
    cover: dict = field(default_factory=dict)      # species id -> share of each cell's ground it covers
    layers: dict = field(default_factory=dict)     # species id -> the layer it stands in
    # What ``cover_at`` reads between the cells.
    potential: dict = field(default_factory=dict)  # species id -> its cover were its patches and habitat everywhere
    patches: dict = field(default_factory=dict)    # species id -> (patch scale in metres, share of ground by cell)
    aquatic: set = field(default_factory=set)
    # Rooting depth in metres -> how wet each cell is for a plant rooting that deep (where the map tells the demand).
    wetness_by_rooting: dict = field(default_factory=dict, repr=False)
    ground: object = None
    seed: int = 0
    # Where the ground lies on its planet: patches and plants are placed there, not on the lattice.
    frame: GroundFrame = field(default_factory=GroundFrame, repr=False)
    # Years between fires under this ground's climate (``None``: none burns), and by cell the years since the last.
    fire_return_years: object = None
    stand_age: object = field(default=None, repr=False)
    # species id -> how far its plants have grown since the last fire, by cell (a share of full size).
    grown: dict = field(default_factory=dict, repr=False)

    @property
    def cell_area_m2(self):
        rows, columns = self.x.shape
        return ((self.bounds["max_x"] - self.bounds["min_x"]) / columns) * ((self.bounds["max_y"] - self.bounds["min_y"]) / rows)

    def _cells(self, x, y):
        rows, columns = self.x.shape
        gx = (np.asarray(x, dtype=np.float64) - self.bounds["min_x"]) / (self.bounds["max_x"] - self.bounds["min_x"]) * columns
        gy = (np.asarray(y, dtype=np.float64) - self.bounds["min_y"]) / (self.bounds["max_y"] - self.bounds["min_y"]) * rows
        return gx, gy, rows, columns

    def between_cells(self, lattice, x, y):
        """A lattice read at any points, between the centres of its cells."""
        gx, gy, rows, columns = self._cells(x, y)
        gx, gy = np.clip(gx - 0.5, 0.0, columns - 1.0), np.clip(gy - 0.5, 0.0, rows - 1.0)
        ix, iy = np.minimum(gx.astype(np.int64), columns - 2), np.minimum(gy.astype(np.int64), rows - 2)
        fx, fy = gx - ix, gy - iy
        return ((lattice[iy, ix] * (1 - fx) + lattice[iy, ix + 1] * fx) * (1 - fy)
                + (lattice[iy + 1, ix] * (1 - fx) + lattice[iy + 1, ix + 1] * fx) * fy)

    def stands_at(self, species_id, x, y):
        """Whether a species can stand at points at all: inside its patches, on land or water as it lives."""
        scale_m, share = self.patches[species_id]
        gx, gy, rows, columns = self._cells(x, y)
        ground_share = share[np.clip(gy.astype(np.int64), 0, rows - 1), np.clip(gx.astype(np.int64), 0, columns - 1)]
        # A species that holds all the ground that suits it has no outline to look up there.
        stands = np.ones(np.shape(ground_share), dtype=bool)
        patchy = ground_share < 1.0
        if patchy.any():
            px, py = np.asarray(x, dtype=np.float64)[patchy], np.asarray(y, dtype=np.float64)[patchy]
            stands[patchy] = _ranked(_patch_noise(species_id, self.frame.world(px, py), scale_m, self.seed)) < ground_share[patchy]
        if self.ground is not None:
            water = np.asarray(self.ground.open_water_array(x, y), dtype=bool)
            stands &= water if species_id in self.aquatic else ~water
        return stands

    def cover_at(self, species_id, x, y):
        """The cover of a species at any points: as in its cells, with its outlines where they really run."""
        if species_id not in self.cover:
            return np.zeros(np.shape(x))
        return np.where(self.stands_at(species_id, x, y), self.between_cells(self.potential[species_id], x, y), 0.0)

    def layer_cover(self, layer):
        total = np.zeros(self.x.shape)
        for species_id, cover in self.cover.items():
            if self.layers[species_id] == layer:
                total += cover
        return total

    def share(self, species_id):
        """The share of all the ground a species covers."""
        cover = self.cover.get(species_id)
        return 0.0 if cover is None else float(cover.mean())

    def plants(self, species_id, spacing_m, seed=0, window=None):
        """``individuals`` without their marks: ``(x, y, share of full size)``."""
        return self.individuals(species_id, spacing_m, seed, window)[:3]

    def individuals(self, species_id, spacing_m, seed=0, window=None, shown=1.0, within=None):
        """Single plants of a species, set out from its cover: ``(x, y, share of full size, mark)``.

        The planet has a place for a plant of this spacing in every cell of
        a lattice of its own (``GroundFrame.places``); a place is taken
        where the species' cover there is larger than the place's own
        number.  So there are as many plants as the cover has room for, most
        full-grown and some younger, and they are the same plants whichever
        map of the ground sets them out and whatever ``window`` (``(min_x,
        min_y, max_x, max_y)``) asks for them: a tree seen from a Site's map
        is the tree met on its Parcel.  A window gets the plants of every
        cell it touches.  ``mark`` is the plant's own number, the same from
        wherever it is set out (``plant_number`` makes others of it).
        ``shown`` below one gives that share of the plants only, for a view
        that cannot show them all: the same plants for the same share, and a
        larger share adds to them.  ``within(x, y)`` narrows the places
        looked at to those it is true for, before anything is worked out for
        them: for a view that is not all of its window.
        """
        empty = np.empty(0), np.empty(0), np.empty(0), np.empty(0, dtype=np.uint64)
        if species_id not in self.cover:
            return empty
        bounds = self.bounds
        whole = (bounds["min_x"], bounds["min_y"], bounds["max_x"], bounds["max_y"])
        if window is not None:
            whole = (max(whole[0], window[0]), max(whole[1], window[1]), min(whole[2], window[2]), min(whole[3], window[3]))
        x, y, key = self.frame.places(whole, float(spacing_m))
        if not len(x):
            return empty
        digest = hashlib.sha256(f"{seed}:{species_id}:plants".encode("utf-8")).digest()
        with np.errstate(over="ignore"):
            key = key ^ np.uint64(int.from_bytes(digest[:8], "big"))
        if shown < 1.0:
            chosen = plant_number(key, 1) < shown
            x, y, key = x[chosen], y[chosen], key[chosen]
        if within is not None:
            chosen = within(x, y)
            x, y, key = x[chosen], y[chosen], key[chosen]
        # The cover a place asks for first: only where it is taken is the patch's outline looked up.
        asked = _uniform(key, 3) < self.between_cells(self.potential[species_id], x, y)
        x, y, key = x[asked], y[asked], key[asked]
        taken = self.stands_at(species_id, x, y)
        share = np.clip(1.0 - 0.85 * _uniform(key[taken], 4) ** 2.5, 0.15, 1.0)
        if species_id in self.grown:
            # On ground a fire took not long ago nothing is older than that.
            share = np.clip(share * self.between_cells(self.grown[species_id], x[taken], y[taken]), 0.15, 1.0)
        return x[taken], y[taken], share, key[taken]


def resident_vegetation(substrate, bounds, profiles, floras, *, cells=96, seed=0, disturbance=True):
    """The vegetation the floras of a planet give a piece of ground.

    ``profiles`` maps species ids to their ``SpeciesProfile``; ``floras`` maps
    biome keys to ``flora.BiomeFlora``.  ``cells`` is the lattice along the
    longer side.  ``seed`` is the planet's (``planet_seed``): with it, and on
    ground that says where on the planet it lies, a species' patches and its
    single plants are the same on every map of that ground.  Without
    ``disturbance`` every piece of ground is as old as it can be: no fire
    has passed and no tree has fallen.
    """
    width, height = bounds["max_x"] - bounds["min_x"], bounds["max_y"] - bounds["min_y"]
    columns = max(2, round(cells * width / max(width, height)))
    rows = max(2, round(cells * height / max(width, height)))
    x, y = np.meshgrid(bounds["min_x"] + (np.arange(columns) + 0.5) * width / columns,
                       bounds["min_y"] + (np.arange(rows) + 0.5) * height / rows)
    index, biomes = biome_grid(substrate, x, y)
    frame = GroundFrame.of(substrate)
    vegetation = ResidentVegetation(dict(bounds), x, y, index, biomes, ground=substrate, seed=seed, frame=frame)
    position = frame.world(x, y)

    def ground(key, default):
        return np.asarray(substrate.sample_array(key, x, y, default), dtype=np.float64)

    water = np.asarray(substrate.open_water_array(x, y), dtype=bool)
    depth = np.maximum(0.0, np.nan_to_num(ground("water_depth_m", 0.0)))
    mineral = ground("soil_moisture", 0.5)
    warmest, coldest = ground("warmest_month_temperature_k", np.nan), ground("coldest_month_temperature_k", np.nan)
    # The site's ordinary ground: the map's own figure where it has one, else that of the land looked at.
    typical = getattr(substrate, "typical", lambda _key: None)("soil_moisture")
    if typical is None and (~water).any():
        typical = float(np.median(mineral[~water]))
    wetness = mature_wetness(mineral, ground("annual_precipitation_mm", 1000.0), typical)
    wetness = np.where(water, 1.0, wetness)
    # Loose sediment is rooted whether or not a soil has formed on it; a map without that figure gives its soil's.
    soil_depth, rootable = ground("soil_depth_m", np.nan), ground("rootable_depth_m", np.nan)
    # The soil's reaction, which a species with an authored range of pH is limited by (``ecology.reaction_response``).
    soil_ph = ground("soil_ph", np.nan)
    # Fire, where the climate of this ground lets it burn: the years since the last one, place by place.
    age = None
    if disturbance:
        def typical_of(key):
            values = ground(key, np.nan)
            return float(np.nanmedian(values)) if np.isfinite(values).any() else float("nan")

        vegetation.fire_return_years = fire_return_years(
            typical_of("annual_precipitation_mm"), typical_of("annual_potential_evaporation_mm"),
            typical_of("driest_month_precipitation_mm"), float(np.nanmedian(coldest)) - 273.15 if np.isfinite(coldest).any() else None)
        if vegetation.fire_return_years:
            vegetation.stand_age = age = stand_age_years(position, vegetation.fire_return_years, seed)
    soil_depth = np.where(np.isfinite(rootable), rootable, soil_depth)
    open_sky = np.clip(np.nan_to_num(ground("surface_solar_exposure", 1.0), nan=1.0), 0.0, 1.0)

    # Where the map carries the demand of the air, wetness is the year's water balance of the plant asked
    # about (``water_balance``): the same ground is wetter for roots that reach more soil or the ground water.
    demand = ground("annual_potential_evaporation_mm", np.nan)
    balanced = np.isfinite(demand) & ~water
    balance, by_rooting = None, vegetation.wetness_by_rooting
    if balanced.any():
        def given(key):
            values = ground(key, np.nan)
            return values if np.isfinite(values).any() else None

        def filled(key, default):
            return np.nan_to_num(ground(key, default), nan=default)

        balance = {
            "rain": monthly_rain(filled("annual_precipitation_mm", 0.0), given("driest_month_precipitation_mm"),
                                 given("wettest_month_precipitation_mm"), given("summer_precipitation_fraction")),
            "demand": monthly_demand(np.nan_to_num(demand), coldest, warmest, open_sky),
            "available_water_mm_per_m": filled("available_water_mm_per_m", DEFAULT_AVAILABLE_WATER_MM_PER_M),
            "rootable_depth_m": soil_depth,
            "lateral_mm": filled("lateral_water_mm", 0.0),
            "capillary_rise_m": filled("capillary_rise_m", DEFAULT_CAPILLARY_RISE_M),
            "water_table_depth_m": ground("water_table_depth_m", np.nan),
        }
        if given("drainage_mm_per_day") is not None:
            # Ground that does not tell its drainage is taken to drain freely.
            balance["drainage_mm_per_day"] = filled("drainage_mm_per_day", np.inf)

    def wetness_for(profile):
        if balance is None or profile.growth_form == "aquatic":
            return wetness
        depth = round(float(rooting_depth_m(profile)), 2)
        if depth not in by_rooting:
            by_rooting[depth] = np.where(balanced, plant_wetness(balance, depth), wetness)
        return by_rooting[depth]

    # Sea water in the ground water, where the map tells it: what of it a plant's roots meet is its own matter.
    salinity = ground("groundwater_salinity", np.nan)
    salty = salinity if np.isfinite(salinity).any() else None
    table, rise = ground("water_table_depth_m", np.nan), ground("capillary_rise_m", np.nan)

    def salt_for(profile):
        return None if salty is None else salt_in_reach(profile, salty, table, rise, water)

    shallows = np.clip((AQUATIC_DEPTH_M[1] - depth) / (AQUATIC_DEPTH_M[1] - AQUATIC_DEPTH_M[0]), 0.0, 1.0)
    # How often the river reworks the ground, in years: what stands there has grown up since the last time.
    reworked = ground(FLOOD_REWORKING_FIELD, FLOOD_NEVER_YEARS)

    # Where each species is part of the flora, and on how much of the ground that suits it.
    present, crusts = {}, {}
    for number, biome in enumerate(biomes):
        flora = floras.get(biome.key)
        for species_id in (flora.species() if flora is not None else ()):
            profile = profiles.get(species_id)
            if profile is None:
                continue
            # A crust grows on stone, not in a layer of the vegetation: it is settled last, on what is left bare.
            kept = crusts if profile.surface_growth_profile else present
            # How common it is here: what a played run measured of it, or what its rarity stands for.
            share = kept.setdefault(species_id, [np.zeros(x.shape), 0.0])
            share[0][index == number] = flora.ground_share(species_id)
            share[1] = max(share[1], flora.ground_share(species_id))

    def standing_in(layer):
        """The species of a layer, the commoner first."""
        return sorted((species_id for species_id in present if layer_of(profiles[species_id]) == layer),
                      key=lambda species_id: (-present[species_id][1], -profiles[species_id].growth_rate, species_id))

    patterns = {}

    def pattern_of(species_id):
        """Where a species' patches lie: the same in every round."""
        if species_id not in patterns:
            form = profiles[species_id].growth_form
            scale_m = float(np.clip(_DISPERSAL_REACH_M.get(form, 8.0) * PATCH_REACH_FACTOR, *PATCH_SCALE_M))
            # The share of the ground its rarity gives it, as ground it is met on and how thick it stands there.
            share, kept = (present.get(species_id) or crusts[species_id])[0], aggregation(profiles[species_id])
            met_on = np.where(share > 0.0, share ** kept, 0.0)
            thin = np.where(share > 0.0, share ** (1.0 - kept), 0.0)
            patterns[species_id] = scale_m, _ranked(_patch_noise(species_id, position, scale_m, seed)) < met_on, met_on, thin
        return patterns[species_id]

    def pressure_on(species_id):
        """The kernel's ``(competition, overtopping)`` on a species from all that stands on the same ground."""
        own = float(profiles[species_id].mature_height_m)
        competition, overtopping = np.zeros(x.shape), np.zeros(x.shape)
        for other, cover in vegetation.cover.items():
            if other == species_id or vegetation.layers[other] == CLIMBER_LAYER:
                continue
            theirs = float(profiles[other].mature_height_m)
            competition = competition + cover * BiosphereEcology.competition_weight(own, theirs)
            if BiosphereEcology.overtops(theirs, own):
                overtopping = overtopping + cover
        return np.minimum(competition, 1.0), np.minimum(overtopping, 1.0)

    def settle(species_id, layer, light, free):
        """Give a species the ground it holds in its layer, of what is left there; its cover, or ``None``."""
        profile = profiles[species_id]
        suitability = potential_suitability(profile, wetness_for(profile), warmest, coldest, open_sky * light,
                                            1.0 - light, soil_depth, salt_for(profile), soil_ph)
        scale_m, patches, met_on, thin = pattern_of(species_id)
        habitat = water if profile.growth_form == "aquatic" else ~water
        pressure = (0.0, 0.0) if layer == CLIMBER_LAYER else pressure_on(species_id)
        potential = np.minimum(expected_cover_array(profile, suitability, *pressure) * thin, free)
        if profile.growth_form == "aquatic":
            potential = potential * shallows
        else:
            potential = potential * flood_standing_share(profile, reworked)
            if age is not None:
                # What a fire took is back as far as its years since allow: grass at once, a wood in decades.
                potential = potential * np.clip(age / recovery_years(profile), 0.0, 1.0)
                vegetation.grown[species_id] = np.clip(age / max(1.0, years_to_grow(profile)), 0.15, 1.0)
            if disturbance and profile.growth_form in WOODY_FORMS:
                # The gaps wind and age open in it, of which every cell has its share.
                potential = potential * math.exp(-closure_years(profile) / GAP_RETURN_YEARS)
        cover = np.where(patches & habitat, potential, 0.0)
        if not cover.any():
            for kept in (vegetation.cover, vegetation.layers, vegetation.potential, vegetation.patches, vegetation.grown):
                kept.pop(species_id, None)
            vegetation.aquatic.discard(species_id)
            return None
        vegetation.cover[species_id], vegetation.layers[species_id] = cover, layer
        vegetation.potential[species_id] = potential
        vegetation.patches[species_id] = (scale_m, met_on)
        if profile.growth_form == "aquatic":
            vegetation.aquatic.add(species_id)
        return cover

    for _round in range(BALANCE_ROUNDS):
        light = np.ones(x.shape)  # what the layers above let through of the sunlight the slope receives
        carrying = np.zeros(x.shape)
        for layer, least in LAYERS:
            free = np.ones(x.shape)
            shade = np.ones(x.shape)
            for species_id in standing_in(layer):
                cover = settle(species_id, layer, light, free)
                if cover is None:
                    continue
                free = free - cover
                profile = profiles[species_id]
                if profile.growth_form in WOODY_FORMS:
                    shade = shade * (1.0 - cover * (0.90 - 0.50 * profile.crown_openness))
                    if least >= 2.0:
                        carrying = carrying + cover
            light = light * shade
    # Climbers last: in the crowns of what carries them, where the light is.
    free = np.minimum(carrying, 1.0) * CLIMBER_SUPPORT_SHARE
    for species_id in standing_in(CLIMBER_LAYER):
        cover = settle(species_id, CLIMBER_LAYER, 1.0, free)
        if cover is not None:
            free = free - cover
    # Crusts last: on stone and on ground too thin to root in, as far as nothing that roots covers it.
    if crusts:
        rooted = np.zeros(x.shape)
        for species_id, cover in vegetation.cover.items():
            if vegetation.layers[species_id] != CLIMBER_LAYER:
                rooted = rooted + cover
        stone = np.clip(1.0 - np.nan_to_num(soil_depth, nan=CRUST_SOIL_DEPTH_M) / CRUST_SOIL_DEPTH_M, 0.0, 1.0)
        free = stone * np.clip(1.0 - rooted, 0.0, 1.0)
        for species_id in sorted(crusts, key=lambda item: (-crusts[item][1], item)):
            scale_m, patches, met_on, thin = pattern_of(species_id)
            potential = np.minimum(thermal_response_array(profiles[species_id], warmest, coldest, 0.0) * thin, free)
            cover = np.where(patches & ~water, potential, 0.0)
            if not cover.any():
                continue
            vegetation.cover[species_id], vegetation.layers[species_id] = cover, LAYERS[-1][0]
            vegetation.potential[species_id] = potential
            vegetation.patches[species_id] = (scale_m, met_on)
            free = free - cover
    return vegetation
