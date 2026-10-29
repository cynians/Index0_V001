"""Render every authored plant as one botanical garden, laid out by the Biosphere.

The garden is an authored fixture held in memory: 240 m of ground whose wetness
rises from a dry bank on the left to a pond on the right.  Nothing is stored.
What grows where is left to the Biosphere's own machinery:

* a species is planted where ``BiosphereEcology.suitability_factors`` scores
  the ground highest for it, the tallest at the back so that nothing is hidden;
* a planting is one stand (``ecology.introduce``), as dense as the cover the
  kernel expects there: recorded plants for everything drawn as a plant, cover
  for the lichens, the sedges and the lawn of Perennial Ryegrass;
* each plant is drawn as one of the ten individuals the garden keeps of its
  species (``plant_pictures``), a few to a stand from their own Species Sim
  bodies, all by the production renderer.

Plantings are established cohorts, not a succession that was played through.
Full-grown plants are shown at the time of their own year when they look their
best, so the beds do not share one calendar day.

Writes ``garden_overview.png`` (and the same without names), a dozen
``garden_detail_NN.png`` close views and ``garden.json`` with what the kernel
makes of each planting.  The whole run takes about five minutes.

    python tools/render_biosphere_botanical_garden.py
    python tools/render_biosphere_botanical_garden.py --views overview
    python tools/render_biosphere_botanical_garden.py --views details
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import pygame

from simulations.biosphere.biosphere_renderer import BiosphereBuilderRenderer
from simulations.biosphere.biosphere_simulation import BiosphereSimulation, _BiosphereWorldView
from simulations.biosphere.plant_pictures import specimen_age_days
from simulations.biosphere.soil_succession import SoilOrganicMatterField
from simulations.biosphere.vegetation import VegetationSampler
from simulations.species.species_renderer import SpeciesRenderer
from simulations.world_gen.generated_landscape_artifact import ArrayRows
from world.world_model import WorldModel


OUTPUT = PROJECT_ROOT / "artifacts" / "biosphere_botanical_garden"
SIDE_M = 240.0
CELL_M = 0.5
PATH_HALF_WIDTH_M = 1.1
LAWN_SPECIES = "spec_lolium_perenne"
BACKGROUND = (15, 20, 18)
OVERVIEW_SIZE = (3000, 2250)
DETAIL_SIZE = (2400, 1500)
# No plant picture is taller than this; the tallest tree fits under it in the overview.
SPRITE_HEIGHT_CAP = 700
# A close view shows as many neighbouring plantings as fit at the lower scale.
DETAIL_PX_PER_M = (45.0, 90.0)

# Full-grown specimens stand at these shares of their adult life, and one is still growing.
SPECIMENS = ((1.0, 0.25), (1.0, 0.45), (1.0, 0.10), (0.6, 0.0))
POLE_HEIGHT_M = 6.0
# A climber's pole, and the room between two of them.
POLE_SPACING_M = 2.0
# A kept bed is not one cohort: this share of its plants is younger, between these shares of full size.
YOUNGER_SHARE = 0.35
YOUNGER_SIZE = (0.3, 0.9)

SURVEY_STEP_M = 6.0
PLOT_STEP_M = 2.0
# How much a metre of ground counts against a species' depth in the picture:
# one tenth of the garden's depth costs this share of its best suitability.
DEPTH_WEIGHT = 4.0
# Neighbouring groves may reach into each other this far; beds keep a strip of lawn between them.
GROVE_OVERLAP = 0.95
BED_GAP_M = 4.0
# A bed has this share of its plants' width as ground around the stand, so that they stay on it.
BODY_MARGIN_SHARE = 0.35
# From this spacing on a planting stands in the lawn like a grove of trees, not in a dressed bed.
GROVE_SPACING_M = 4.0
# Depth of the row a planting belongs in, by the plant's height in metres.
BED_ROWS = ((3.0, 0.585), (1.5, 0.70), (0.6, 0.755), (0.0, 0.885))
GROVE_DEPTHS = (0.12, 0.50)

LAWN_DISC_M = (1.8, 10.0)
LAWN_COVER = 0.6

SQRT2 = math.sqrt(2.0)


def _smooth(value):
    value = np.clip(value, 0.0, 1.0)
    return value * value * (3.0 - 2.0 * value)


class GardenGround:
    """The garden's ground as functions of place, in metres from its back corner.

    ``across`` runs from the left corner of the picture (-1) to the right one
    (+1), ``depth`` from the back corner (0) to the front one (1).
    """

    # Wetness index from the dry bank to the wet corner, before the pond is felt.
    WETNESS_ACROSS = ((-1.0, 0.04), (-0.6, 0.05), (-0.35, 0.30), (-0.15, 0.40),
                      (0.15, 0.44), (0.40, 0.58), (0.70, 0.66), (1.0, 0.76))
    ANNUAL_PRECIPITATION_MM = 800.0
    TEMPERATURE_K = (276.15, 284.65, 292.65)  # coldest month, year, warmest month

    def __init__(self, side_m=SIDE_M):
        self.side = float(side_m)
        self.bounds = {"min_x": 0.0, "max_x": self.side, "min_y": 0.0, "max_y": self.side}
        self.pond_centre = self.place(0.34, 0.705)
        self.pond_radii = (15.0, 9.5)
        rock_x, rock_y = self.place(-0.36, 0.74)
        self.rocks = [(rock_x + dx, rock_y + dy, radius) for dx, dy, radius in (
            (0.0, 0.0, 4.2), (8.0, -4.0, 3.2), (-7.0, 5.0, 3.0), (3.0, 9.0, 2.7), (-9.0, -5.0, 2.5))]
        self.paths = [(self.place(*start), self.place(*end)) for start, end in (
            ((0.0, 0.985), (0.0, 0.545)), ((-0.26, 0.83), (0.26, 0.83)), ((-0.68, 0.645), (0.68, 0.645)))]
        self.rondel = (*self.place(0.0, 0.52), 6.0)
        self.water_level = float(self._open_ground(*self.pond_centre)) - 0.45

    def place(self, across, depth):
        return self.side * (depth + across * 0.5), self.side * (depth - across * 0.5)

    def across(self, x, y):
        return (np.asarray(x, dtype=np.float64) - y) / self.side

    def depth(self, x, y):
        return (np.asarray(x, dtype=np.float64) + y) / (2.0 * self.side)

    def pond_distance(self, x, y):
        """Metres to the pond's shore, negative on the water."""
        dx, dy = np.asarray(x, dtype=np.float64) - self.pond_centre[0], np.asarray(y, dtype=np.float64) - self.pond_centre[1]
        along, back = (dx - dy) / SQRT2, (dx + dy) / SQRT2
        wide, deep = self.pond_radii
        angle = np.arctan2(back / deep, along / wide)
        outline = 1.0 + 0.10 * np.sin(3.0 * angle + 0.6) + 0.06 * np.sin(5.0 * angle + 2.1)
        return (np.hypot(along / wide, back / deep) - outline) * np.hypot(wide * np.cos(angle), deep * np.sin(angle))

    def path_distance(self, x, y):
        """Metres to the edge of the nearest walk, negative on it."""
        x, y = np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64)
        distance = np.abs(np.hypot(x - self.rondel[0], y - self.rondel[1]) - self.rondel[2])
        for (x0, y0), (x1, y1) in self.paths:
            ex, ey = x1 - x0, y1 - y0
            share = np.clip(((x - x0) * ex + (y - y0) * ey) / (ex * ex + ey * ey), 0.0, 1.0)
            distance = np.minimum(distance, np.hypot(x - x0 - share * ex, y - y0 - share * ey))
        return distance - PATH_HALF_WIDTH_M

    def rock_distance(self, x, y):
        """Metres to the nearest outcrop of the rockery, negative on the rock."""
        x, y = np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64)
        return np.minimum.reduce([np.hypot(x - rock_x, y - rock_y) - radius for rock_x, rock_y, radius in self.rocks])

    def _open_ground(self, x, y):
        across = self.across(x, y)
        return 3.2 * _smooth((-across - 0.30) / 0.6) - 0.9 * _smooth((across - 0.15) / 0.7)

    def water_depth(self, x, y, shore=None):
        shore = self.pond_distance(x, y) if shore is None else shore
        return np.where(shore < 0.0, 1.5 * (1.0 - np.exp(np.minimum(shore, 0.0) / 3.5)), 0.0)

    def elevation(self, x, y):
        """The ground itself; under the pond, its bed."""
        x, y = np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64)
        ground = self._open_ground(x, y)
        for rock_x, rock_y, radius in self.rocks:
            ground = ground + 0.32 * radius * np.clip(1.0 - (np.hypot(x - rock_x, y - rock_y) / radius) ** 2, 0.0, None)
        shore = self.pond_distance(x, y)
        ground = ground + (self.water_level - ground) * _smooth((7.0 - shore) / 7.0)
        return ground - self.water_depth(x, y, shore)

    def wetness(self, x, y, shore=None):
        shore = self.pond_distance(x, y) if shore is None else shore
        knots = np.array(self.WETNESS_ACROSS)
        band = np.interp(self.across(x, y), knots[:, 0], knots[:, 1])
        # The pond soaks its banks; a few metres back the ground is the band's again.
        seep = np.maximum(0.0, 0.86 - band) * np.exp(-np.maximum(shore, 0.0) / 5.0)
        return np.where(shore < 0.0, 0.92, band + seep)

    def organic_matter(self, x, y):
        """Soil organic matter a gardener keeps, in kg/m²: lean on the dry bank, none on rock or gravel."""
        loam = 2.6 + 4.4 * _smooth((self.across(x, y) + 0.50) / 0.35)
        bare = (self.rock_distance(x, y) < 0.0) | (self.path_distance(x, y) < 0.0)
        return np.where(bare, 0.0, loam)

    @staticmethod
    def grain(x, y, cell_m):
        """A value in 0..1 that changes from one ``cell_m`` of ground to the next."""
        ix = np.floor(np.asarray(x) / cell_m).astype(np.int64)
        iy = np.floor(np.asarray(y) / cell_m).astype(np.int64)
        mixed = (ix * 73856093) ^ (iy * 19349663)
        mixed = (mixed ^ (mixed >> 13)) * 1274126177
        return ((mixed ^ (mixed >> 16)) & 1023) / 1023.0

    def colour(self, x, y):
        """Abiotic ground colour: mineral soil by wetness, gravel walks, rock and water.  No plants."""
        x, y = np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64)
        shore = self.pond_distance(x, y)
        wet = self.wetness(x, y, shore)
        sand, loam, peat = (np.array(rgb, dtype=np.float32) for rgb in ((172, 154, 118), (116, 98, 72), (70, 60, 47)))
        rgb = sand + (loam - sand) * _smooth((wet - 0.05) / 0.40)[..., None]
        rgb = rgb + (peat - rgb) * _smooth((wet - 0.52) / 0.34)[..., None]
        rgb = rgb * (0.93 + 0.14 * self.grain(x, y, 0.15))[..., None]
        stone = np.array((134, 132, 126), dtype=np.float32) * (0.80 + 0.40 * self.grain(x, y, 0.7))[..., None]
        rgb = np.where((self.rock_distance(x, y) < 0.0)[..., None], stone, rgb)
        gravel = np.array((198, 186, 156), dtype=np.float32) * (0.91 + 0.18 * self.grain(x, y, 0.08))[..., None]
        rgb = rgb + (gravel - rgb) * _smooth(-self.path_distance(x, y) / 0.25 + 1.0)[..., None]
        shallow, deep = np.array((92, 136, 128), dtype=np.float32), np.array((36, 76, 96), dtype=np.float32)
        water = shallow + (deep - shallow) * np.clip(self.water_depth(x, y, shore) / 1.2, 0.0, 1.0)[..., None]
        return np.where((shore < 0.0)[..., None], water, rgb).astype(np.float32)

    def root_entity(self):
        """The garden as a location the Biosphere can open: the same fields a generated site carries."""
        count = int(round(self.side / CELL_M)) + 1
        axis = np.linspace(0.0, self.side, count)
        x, y = np.meshgrid(axis, axis)
        shore = self.pond_distance(x, y)
        elevation, depth = self.elevation(x, y), self.water_depth(x, y, shore)
        rock = self.rock_distance(x, y) < 0.0

        def rows(values):
            return ArrayRows(np.asarray(values, dtype=np.float32))

        def everywhere(value):
            return rows(np.full((2, 2), value))

        coldest, mean, warmest = self.TEMPERATURE_K
        return {
            "id": "loc_biosphere_botanical_garden", "type": "location", "_dataset": "locations",
            "name": "Botanical Garden", "location_class": "biosphere_patch",
            "location_role": "biosphere_design_patch", "map_coordinate_space": "site_meters",
            "map_detail_level": 5, "map_status": "authored garden fixture, held in memory only",
            "display_color": [116, 98, 72], "bounds": {"type": "bbox", **self.bounds},
            "biosphere_width_m": self.side, "biosphere_height_m": self.side, "biosphere_area_m2": self.side ** 2,
            "heightmap_model": {
                "input_fingerprint": "botanical-garden-fixture-v1", "projection": "local_cartesian",
                "min_elevation_m": float(elevation.min()), "max_elevation_m": float((elevation + depth).max()),
                "sample_grid": {"width": count, "height": count, "rows": rows(elevation)},
            },
            "water_cycle_model": {
                "climate_grid": {
                    "temperature_rows_k": everywhere(mean), "seasonal_min_temperature_rows_k": everywhere(coldest),
                    "seasonal_max_temperature_rows_k": everywhere(warmest),
                    "annual_precipitation_rows_mm": everywhere(self.ANNUAL_PRECIPITATION_MM),
                    "surface_solar_exposure_rows": everywhere(1.0),
                },
                "runoff_grid": {"wetness_index_rows": rows(self.wetness(x, y, shore))},
                "surface_water_grid": {"water_depth_m_rows": rows(depth)},
            },
            "regolith_soil_model": {
                "grid": {"soil_depth_m_rows": rows(np.where(rock, 0.05, 1.2)), "ph_rows": everywhere(6.3)},
                "nutrient_status": "garden loam; pools set on the biosphere soil field",
            },
        }


@dataclass
class Planting:
    species_id: str
    x: float
    y: float
    radius_m: float  # of the population patch
    kind: str  # grove, bed, water or rock
    reach_m: float = 0.0  # of the ground the planting takes up, its plants' spread included
    suitability: float = 0.0
    cover: float = 0.0
    limit: str = ""

    def __post_init__(self):
        self.reach_m = max(self.reach_m, self.radius_m)


class Garden:
    """The planting plan and the Biosphere it is planted in."""

    def __init__(self, world):
        self.ground = GardenGround()
        root = self.ground.root_entity()
        self.sim = BiosphereSimulation(_BiosphereWorldView(world, root), {
            "patch_location_id": root["id"], "patch_name": root["name"], "year": 2400,
            "biosphere_width_m": self.ground.side, "biosphere_height_m": self.ground.side,
        })
        self.sim.isometric_fullscreen_preview = True
        self.sim.isometric_sprite_height_cap = SPRITE_HEIGHT_CAP
        self._lay_soil()
        self.sampler = GardenSampler(self)
        self.plantings: list[Planting] = []
        self.lawn_patches = 0
        self.authored, self.unauthored = [], []
        for profile in self.sim.species_profiles:
            entity = self.entity(profile.species_id)
            (self.authored if entity.get("plant_growth_form") else self.unauthored).append(profile)
        self._beds = {}
        pictures, ecology = self.sim.plant_pictures, self.sim.ecology
        # A still shows a kept individual at many scales; keep the bodies grown for the first.
        pictures.BODY_CACHE = 600
        # And it has no frame to keep: every stand gets its simulated plants at once.
        self.sim.representatives.PICK_BUDGET_MS = math.inf
        # A climber is grown on a pole, the kept individuals as well as the simulated plants.
        pictures.growth_environment = lambda species_id, individual: self.support_for(species_id) or None
        spacing = ecology.spacing_m
        ecology.spacing_m = lambda profile: max(
            spacing(profile), POLE_SPACING_M if self.support_for(profile.species_id) else 0.0)
        # Reads of every representative, not the first screenful the running game lists.
        instances = self.sim.get_species_sprite_instances
        self.sim.get_species_sprite_instances = lambda limit=10 ** 6: [self.display_form(item) for item in instances(limit)]

    def entity(self, species_id):
        world = self.sim.world_model
        return world.resolved_species_entity(species_id) or world.get_entity(species_id) or {}

    def _lay_soil(self):
        """Kept garden soil in place of the bare mineral ground a Biosphere starts from."""
        sim = self.sim
        soil = SoilOrganicMatterField(sim.bounds, columns=96, rows=96)
        sim.soil = sim.ecology.soil = soil
        soil.initialize_from_abiotic(sim.ecology)
        x, y = np.meshgrid(
            soil.bounds["min_x"] + (np.arange(soil.columns) + 0.5) * soil.width / soil.columns,
            soil.bounds["min_y"] + (np.arange(soil.rows) + 0.5) * soil.height / soil.rows,
        )
        organic = self.ground.organic_matter(x, y)
        soil.organic_matter_rows = organic.tolist()
        # Nutrients in step with the humus, on top of what the bare mineral ground starts with.
        soil.available_nitrogen_rows = (np.asarray(soil.available_nitrogen_rows) + organic * 1.0).tolist()
        soil.available_phosphorus_rows = (np.asarray(soil.available_phosphorus_rows) + organic * 0.16).tolist()
        soil.revision += 1

    # ------------------------------------------------------------------
    # Where each species goes
    # ------------------------------------------------------------------
    def planting_extent(self, profile):
        """``(stand radius, ground radius, kind)`` of a species' planting."""
        ecology = self.sim.ecology
        spacing = (ecology.spacing_m(profile) if ecology.keeps_individuals(profile)
                   else self.sampler.spacing_m(profile, True))
        if profile.growth_form == "tree":
            # A grove of half a dozen crowns; the tallest would otherwise take a third of the garden.
            radius = spacing * (1.3 if spacing > 25.0 else 1.6)
            return radius, radius, "grove"
        grove = spacing >= GROVE_SPACING_M
        radius = spacing * 1.6 if grove else max(3.0 if profile.mature_height_m < 0.6 else 4.0, spacing * 1.8)
        margin = BODY_MARGIN_SHARE * self.sim.plant_pictures.body_width(profile.species_id)
        return radius, radius + margin, "grove" if grove else "bed"

    def plan(self):
        sim, ground, ecology = self.sim, self.ground, self.sim.ecology
        side = ground.side
        coarse = np.arange(SURVEY_STEP_M / 2.0, side, SURVEY_STEP_M)
        environments = [[ecology.environment_at(x, y) for x in coarse] for y in coarse]

        axis = np.arange(PLOT_STEP_M / 2.0, side, PLOT_STEP_M)
        x, y = (grid.ravel() for grid in np.meshgrid(axis, axis))
        depth = ground.depth(x, y)
        edge = np.minimum(np.minimum(x, side - x), np.minimum(y, side - y))
        path, pond, rock = ground.path_distance(x, y), ground.pond_distance(x, y), ground.rock_distance(x, y)
        survey_cell = (np.minimum(len(coarse) - 1, (y / SURVEY_STEP_M).astype(int)),
                       np.minimum(len(coarse) - 1, (x / SURVEY_STEP_M).astype(int)))
        jitter = 0.03 * ground.grain(x, y, PLOT_STEP_M)

        def suitability_at(profile, px, py):
            return ecology.suitability_factors(profile, ecology.environment_at(px, py))["suitability"]

        def place(profile, radius, target, grove):
            # ``radius`` is the ground the planting takes up.
            survey = np.array([[ecology.suitability_factors(profile, environment)["suitability"]
                                for environment in row] for row in environments])
            best = max(1e-6, float(survey.max()))
            score = survey[survey_cell] / best - DEPTH_WEIGHT * np.abs(depth - target) + jitter
            allowed = ((edge >= (0.55 * radius if grove else radius + 1.0)) & (path >= radius + 0.4)
                       & (rock >= radius + 0.5) & (pond >= (radius if grove else 1.5)))
            for slack in (1.0, 0.85, 0.7):
                free = allowed.copy()
                for other in self.plantings:
                    if other.kind in {"water", "rock"}:
                        continue
                    apart = radius + other.reach_m
                    if grove and other.kind == "grove":
                        apart *= GROVE_OVERLAP
                    else:
                        apart += 1.0 if grove or other.kind == "grove" else BED_GAP_M
                    free &= np.hypot(x - other.x, y - other.y) >= apart * slack
                if not free.any():
                    continue
                # The survey is coarse: ask the kernel again at the best few spots.
                shortlist = np.flatnonzero(free)
                shortlist = shortlist[np.argsort(-score[shortlist])[:24]]
                exact = {int(i): suitability_at(profile, x[i], y[i]) for i in shortlist}
                pick = max(exact, key=lambda i: exact[i] / best - DEPTH_WEIGHT * abs(depth[i] - target) + jitter[i])
                return float(x[pick]), float(y[pick])
            raise RuntimeError(f"No room left in the garden for {profile.label}")

        # Water plants in the pond, lichens on the rockery: the only ground of their kind.
        pond_x, pond_y = ground.pond_centre
        rocks = sorted(ground.rocks, key=lambda rock: -rock[2])
        afloat = [profile for profile in self.authored if profile.growth_form == "aquatic"]
        crusts = [profile for profile in self.authored if profile.growth_form == "lichen"]
        land = [profile for profile in self.authored if profile.growth_form not in {"aquatic", "lichen"}]
        for index, profile in enumerate(afloat):
            angle = 2.6 + math.tau * index / len(afloat)
            along, back = (0.45 * reach * turn for reach, turn in zip(ground.pond_radii, (math.cos(angle), math.sin(angle))))
            self.plantings.append(Planting(profile.species_id, pond_x + (along + back) / SQRT2,
                                           pond_y + (back - along) / SQRT2, 3.0, "water"))
        for index, profile in enumerate(crusts):
            rock_x, rock_y, radius = rocks[index % len(rocks)]
            self.plantings.append(Planting(profile.species_id, rock_x, rock_y, radius * 0.9, "rock"))

        extent = {profile.species_id: self.planting_extent(profile) for profile in land}
        trees = sorted((p for p in land if p.growth_form == "tree"), key=lambda p: (-extent[p.species_id][1], p.species_id))
        others = sorted((p for p in land if p.growth_form != "tree"), key=lambda p: (-extent[p.species_id][1], p.species_id))
        planted_area, tree_area = 0.0, sum(extent[p.species_id][1] ** 2 for p in trees)
        for profile in trees:
            # The back of the garden narrows to a corner, so depth grows more slowly than the ground used up.
            radius, reach, kind = extent[profile.species_id]
            share = ((planted_area + reach ** 2 * 0.5) / tree_area) ** 0.75
            planted_area += reach ** 2
            target = GROVE_DEPTHS[0] + (GROVE_DEPTHS[1] - GROVE_DEPTHS[0]) * share
            self.plantings.append(Planting(profile.species_id, *place(profile, reach, target, True), radius, kind, reach))
        for profile in others:
            radius, reach, kind = extent[profile.species_id]
            target = next(row for height, row in BED_ROWS if profile.mature_height_m >= height)
            self.plantings.append(Planting(profile.species_id, *place(profile, reach, target, kind == "grove"),
                                           radius, kind, reach))
        self._beds = {planting.species_id: planting for planting in self.plantings if planting.kind == "bed"}

    def plant(self):
        """Introduce every planting as an established population, then the lawn between them."""
        sim, ecology = self.sim, self.sim.ecology
        for planting in self.plantings:
            profile = ecology.profiles[planting.species_id]
            diagnosis = sim.diagnose(planting.species_id, planting.x, planting.y)
            planting.suitability = float(diagnosis["suitability"])
            planting.cover = float(ecology.expected_cover(profile, planting.suitability))
            planting.limit = diagnosis["reason"] if planting.suitability < 0.9 else ""
        for planting in self.plantings:
            profile = ecology.profiles[planting.species_id]
            # A gardener keeps every bed going; how full it is follows what the ground gives.
            ecology.introduce(planting.species_id, planting.x, planting.y, planting.radius_m, 0.35 + 0.55 * planting.cover)
            stand = ecology.patches[-1]
            stand.development_days = profile.maturity_days
            plants = ecology.individuals.members(stand.patch_id)
            if plants is not None and len(plants):
                # An established planting: most plants full-grown, some set in later.
                rng = np.random.default_rng(stand.seed)
                size = np.where(rng.random(len(plants)) < YOUNGER_SHARE, rng.uniform(*YOUNGER_SIZE, len(plants)), 1.0)
                plants.lag_days = profile.maturity_days * (1.0 - size)
        lawn = ecology.profiles.get(LAWN_SPECIES)
        if lawn is not None:
            # Grass adds no crowns, so the trees' shade can be read once for the whole lawn.
            with ecology.canopies_held():
                for x, y, radius in self._lawn_discs():
                    cover = ecology.expected_cover(lawn, ecology.suitability_factors(
                        lawn, ecology.environment_at(x, y))["suitability"])
                    if cover < 0.03:
                        continue
                    ecology.introduce(LAWN_SPECIES, x, y, radius, cover * 0.95)
                    ecology.patches[-1].development_days = lawn.maturity_days
                    self.lawn_patches += 1
        sim.representatives.sync_from_population(ecology)
        for profile in self.authored:
            support = self.support_for(profile.species_id)
            for index, representative in enumerate(sim.representatives.items(profile.species_id, alive_only=True)):
                representative.simulation.environment.update(support)
                maturity, prime = SPECIMENS[index % len(SPECIMENS)]
                sim.representatives.grow_body(representative, specimen_age_days(representative.simulation, maturity, prime))
                if representative.individual_uid is not None:
                    # The plant it is has the age its body was given.
                    ecology.follow_individual(representative.individual_uid, grown_days=representative.age_days)

    def _lawn_discs(self):
        """Discs that fill the open ground between walks, water, rock and beds, the largest first."""
        ground, side = self.ground, self.ground.side
        axis = np.arange(0.5, side, 1.0)
        x, y = np.meshgrid(axis, axis)
        clear = np.minimum.reduce([
            ground.path_distance(x, y) - 0.4, ground.pond_distance(x, y) - 0.6, ground.rock_distance(x, y) - 0.3,
            np.minimum(np.minimum(x, side - x), np.minimum(y, side - y)) - 0.2,
        ])
        for planting in self.plantings:
            if planting.kind == "bed":
                clear = np.minimum(clear, np.hypot(x - planting.x, y - planting.y) - planting.reach_m - 0.4)
        covered = np.zeros(clear.shape, dtype=bool)
        discs = []
        for index in np.argsort(-clear, axis=None).tolist():
            row, column = divmod(index, clear.shape[1])
            radius = min(LAWN_DISC_M[1], float(clear[row, column]))
            if radius < LAWN_DISC_M[0]:
                break
            if covered[row, column]:
                continue
            centre_x, centre_y = float(x[row, column]), float(y[row, column])
            discs.append((centre_x, centre_y, radius))
            reach = int(radius) + 1
            rows = slice(max(0, row - reach), row + reach + 1)
            columns = slice(max(0, column - reach), column + reach + 1)
            covered[rows, columns] |= np.hypot(x[rows, columns] - centre_x, y[rows, columns] - centre_y) <= radius * LAWN_COVER
        return discs

    # ------------------------------------------------------------------
    # The plants as they are shown
    # ------------------------------------------------------------------
    def support_for(self, species_id):
        """A pole beside each climber: a support is part of the place, never of the plant."""
        if self.entity(species_id).get("plant_growth_behaviour") != "climbing_support_dependent":
            return {}
        return {"climbing_supports": [{"id": "garden_pole", "kind": "pole", "center_m": [0.35, 0.0],
                                       "radius_m": 0.05, "height_m": POLE_HEIGHT_M, "crown_radius_m": 0.0}]}

    def display_form(self, item):
        """Sedges and grasses in a bed are shown as the plants Species Sim grows; only the lawn stays a map symbol."""
        if item["growth_form"] != "graminoid":
            return item
        bed = self._beds.get(item["species_id"])
        if item["species_id"] == LAWN_SPECIES and (
                bed is None or math.hypot(item["x"] - bed.x, item["y"] - bed.y) > bed.radius_m):
            return item
        return dict(item, growth_form="structural_graminoid")

    def label(self, species_id):
        return self.sim.short_label(species_id)


class GardenSampler(VegetationSampler):
    """The Biosphere's display sampler with a still picture's budget."""

    MAX_CANDIDATES = 80_000_000
    MAX_INSTANCES = 80_000_000
    BUCKET_M = 12.0

    def __init__(self, garden):
        super().__init__()
        self.garden = garden
        self._buckets = {}

    def spacing_m(self, profile, true_scale):
        spacing = super().spacing_m(profile, true_scale)
        if true_scale and profile.growth_form == "graminoid" and profile.species_id != LAWN_SPECIES:
            # A sedge in a bed is drawn as the clump it is: it gets the room a recorded plant would.
            ecology = self.garden.sim.ecology
            spacing = max(spacing, ecology.BODY_ROOM_SHARE * self.garden.sim.plant_pictures.body_width(profile.species_id))
        return spacing

    def sample(self, ecology, representatives, true_scale=False, window=None):
        return [self.garden.display_form(item) for item in super().sample(ecology, representatives, true_scale, window)]

    def display_growth(self, species_id, x, y, patches, maturity_days, individual_byte):
        # The game's answer, found among the patches near the plant: the lawn alone is hundreds of discs.
        key = (species_id, len(patches))
        buckets = self._buckets.get(key)
        if buckets is None:
            buckets = self._buckets[key] = {}
            size = self.BUCKET_M
            for patch in patches:
                for bx in range(math.floor((patch.x - patch.radius_m) / size), math.floor((patch.x + patch.radius_m) / size) + 1):
                    for by in range(math.floor((patch.y - patch.radius_m) / size), math.floor((patch.y + patch.radius_m) / size) + 1):
                        buckets.setdefault((bx, by), []).append(patch)
        near = buckets[(math.floor(x / self.BUCKET_M), math.floor(y / self.BUCKET_M))]
        return VegetationSampler.display_growth(species_id, x, y, near, maturity_days, individual_byte)


class FullFoliageRenderer(SpeciesRenderer):
    """Species Sim's painter without the game's per-frame foliage economy."""

    def _draw_individual(self, *args, **kwargs):
        kwargs["foliage_sample_cap"] = None
        return super()._draw_individual(*args, **kwargs)


class GardenRenderer(BiosphereBuilderRenderer):
    """The production Biosphere renderer over the garden's own ground."""

    DISPLAY_PICTURE_LIMIT = 4000
    MULCH_RGB = (72, 57, 43)

    def __init__(self, garden):
        super().__init__(SimpleNamespace(), species_renderer=FullFoliageRenderer(SimpleNamespace()))
        self.garden = garden
        self._vegetation_sampler = garden.sampler
        self._ground_picture = None

    @staticmethod
    def _projection(screen, biosphere_sim):
        state = BiosphereBuilderRenderer._projection(screen, biosphere_sim)
        # A landscape view, as on generated terrain: plants at their real
        # size, room for their crowns, and only the ground in view sampled.
        state["generated"] = True
        state["datum_m"] = state["substrate"].elevation(state["center_x"], state["center_y"], True)
        return state

    def paint_for(self, pixels_per_metre):
        """Paint plant pictures for one view, at the size it shows them.

        The game paints a plant once, as large as its closest view, and
        shrinks that picture; shrunk several times over, a crown thins to a
        haze.  A still has one view and can paint for it.
        """
        if pixels_per_metre != self.FULL_SIZE_PX_PER_M:
            self.FULL_SIZE_PX_PER_M = pixels_per_metre
            self._display_canonical.clear()
            self._display_sprite_cache.clear()

    def _draw_soil_tint(self, screen, biosphere_sim, state):
        """The garden's ground already shows its soil."""

    def _draw_ground(self, screen, biosphere_sim, state):
        key = (screen.get_size(), state["scale"], state["center_x"], state["center_y"], state["origin_x"], state["origin_y"])
        if self._ground_picture is None or self._ground_picture[0] != key:
            self._ground_picture = (key, self._paint_ground(screen.get_size(), state))
        screen.blit(self._ground_picture[1], (0, 0))
        self._draw_domain_outline(screen, biosphere_sim, state)

    def _paint_ground(self, size, state, band=200):
        ground, substrate = self.garden.ground, state["substrate"]
        world_x, world_y = self._ground_world_map(size, state, 1)
        image = np.empty((size[1], size[0], 3), dtype=np.float32)
        for top in range(0, size[1], band):
            rows = slice(top, top + band)
            image[rows] = ground.colour(world_x[rows], world_y[rows])
        # A bed is its population's disc, dressed with mulch.
        for planting in self.garden.plantings:
            if planting.kind != "bed":
                continue
            centre_x, centre_y = self._iso(state, planting.x, planting.y)
            reach = planting.reach_m * state["scale"] * 1.6 + 6.0
            columns = slice(max(0, int(centre_x - reach)), max(0, int(centre_x + reach) + 1))
            rows = slice(max(0, int(centre_y - reach)), max(0, int(centre_y + reach) + 1))
            x, y = world_x[rows, columns], world_y[rows, columns]
            if not x.size:
                continue
            cover = _smooth((planting.reach_m + 0.1 - np.hypot(x - planting.x, y - planting.y)) / 0.25)
            cover = cover * (ground.pond_distance(x, y) > 0.2) * (ground.path_distance(x, y) > 0.0) * 0.9
            mulch = np.array(self.MULCH_RGB, dtype=np.float32) * (0.84 + 0.32 * ground.grain(x, y, 0.12))[..., None]
            image[rows, columns] += (mulch - image[rows, columns]) * cover[..., None]
        pixels = np.empty(image.shape, dtype=np.uint8)
        for top in range(0, size[1], band):
            rows = slice(top, top + band)
            x, y = world_x[rows], world_y[rows]
            slope_x = substrate.elevation_array(x + 0.5, y, True) - substrate.elevation_array(x - 0.5, y, True)
            slope_y = substrate.elevation_array(x, y + 0.5, True) - substrate.elevation_array(x, y - 0.5, True)
            shade = np.clip((1.0 + 0.45 * slope_x - 0.55 * slope_y) / np.sqrt(1.0 + slope_x ** 2 + slope_y ** 2), 0.6, 1.2)
            lit = np.clip(image[rows] * shade[..., None], 0, 255)
            outside = (x < 0.0) | (x > ground.side) | (y < 0.0) | (y > ground.side)
            pixels[rows] = np.where(outside[..., None], np.array(BACKGROUND, dtype=np.float32), lit)
        return pygame.surfarray.make_surface(pixels.swapaxes(0, 1))


# ----------------------------------------------------------------------
# Views, labels and the record of what was planted
# ----------------------------------------------------------------------
def _font(size, bold=False):
    return pygame.font.SysFont("segoeui,arial,dejavusans", size, bold=bold)


def draw_labels(surface, renderer, state, garden):
    """Each planting's name: on the ground at a bed's front rim, over the top of a grove's middle tree.

    A name that would cover another moves aside, and then points back to where it belongs.
    """
    font = _font(17)
    frame = surface.get_rect()
    sim = garden.sim
    camera = SimpleNamespace(zoom=state["scale"], sprite_height_cap=SPRITE_HEIGHT_CAP, true_scale=True)
    names = []
    for planting in garden.plantings:
        followed = sim.representatives.items(planting.species_id, alive_only=True)
        if planting.kind == "grove" and followed:
            # The first plant followed in a grove is its best grown; its top clears the trees in front.
            tree = followed[0]
            x, y = renderer._iso(state, tree.x, tree.y)
            y -= renderer._target_height_for(
                float(tree.simulation.render_snapshot.bounds_m[5]),
                {"growth_form": "tree", "abundance": sim.ecology.abundance_at(planting.species_id, tree.x, tree.y)},
                camera, sim.world_units_to_meters)
            side = -1
        else:
            reach = planting.reach_m * 0.72
            x, y = renderer._iso(state, planting.x + reach, planting.y + reach)
            side = 1
        if frame.inflate(-16, -16).collidepoint(x, y):
            names.append((y, x, side, garden.label(planting.species_id)))
    placed = []
    for y, x, side, text in sorted(names):
        image = font.render(text, True, (236, 240, 222))
        home = image.get_rect().inflate(10, 4)
        home.midtop = (round(x), round(y) + 3)
        if side < 0:
            home.midbottom = (round(x), round(y) - 3)
        # Straight on first, then to either side, each a little further out.
        steps = [(dx * (home.width // 2 + 8), side * dy) for dy in range(0, 132, 6) for dx in (0, -1, 1)]
        steps.sort(key=lambda step: abs(step[0]) * 0.5 + abs(step[1]))
        box = next((moved for moved in (home.move(step).clamp(frame) for step in steps)
                    if moved.collidelist(placed) < 0), home.clamp(frame))
        placed.append(box)
        if abs(box.centerx - home.centerx) > 12 or abs(box.centery - home.centery) > 14:
            pygame.draw.line(surface, (12, 18, 14), (round(x), round(y)), box.center, 3)
            pygame.draw.line(surface, (214, 222, 198), (round(x), round(y)), box.center, 1)
        plate = pygame.Surface(box.size, pygame.SRCALPHA)
        plate.fill((12, 18, 14, 200))
        surface.blit(plate, box)
        surface.blit(image, image.get_rect(center=box.center))


def draw_header(surface, title, lines, pixels_per_metre):
    heading, text = _font(34, bold=True).render(title, True, (232, 238, 216)), _font(19)
    rows = [text.render(line, True, (196, 212, 190)) for line in lines]
    metres = next((m for m in (0.5, 1, 2, 5, 10, 20, 50) if m * pixels_per_metre >= 110), 100)
    length = round(metres * pixels_per_metre)
    rows.append(text.render(f"{metres:g} m on the ground", True, (196, 212, 190)))
    width = max([heading.get_width()] + [row.get_width() for row in rows[:-1]] + [length + 14 + rows[-1].get_width()])
    plate = pygame.Surface((width + 36, 66 + len(rows) * 25), pygame.SRCALPHA)
    plate.fill((*BACKGROUND, 214))
    surface.blit(plate, (12, 12))
    surface.blit(heading, (28, 22))
    for index, row in enumerate(rows[:-1]):
        surface.blit(row, (30, 70 + index * 25))
    top = 84 + (len(rows) - 1) * 25
    pygame.draw.line(surface, (232, 238, 216), (30, top), (30 + length, top), 2)
    for tick in (30, 30 + length):
        pygame.draw.line(surface, (232, 238, 216), (tick, top - 5), (tick, top + 5), 2)
    surface.blit(rows[-1], (40 + length, top - 12))


def detail_views(garden, renderer):
    """Close views of the plantings too small to judge from across the garden.

    Neighbours share a view for as long as it still shows them at the lower
    detail scale; the rest start the next one.
    """
    sim = garden.sim
    sim.isometric_view_center, sim.isometric_view_zoom = None, 1.0
    scale = renderer._projection(pygame.Surface(DETAIL_SIZE), sim)["scale"]

    def framing(members):
        tallest = min(8.0, max(sim.ecology.profiles[p.species_id].mature_height_m for p in members))
        left = min((p.x - p.y) - p.reach_m * SQRT2 for p in members)
        right = max((p.x - p.y) + p.reach_m * SQRT2 for p in members)
        back = min((p.x + p.y) - p.reach_m * SQRT2 for p in members) * 0.5 - tallest
        front = max((p.x + p.y) + p.reach_m * SQRT2 for p in members) * 0.5 + 2.0
        zoom = min(DETAIL_SIZE[0] * 0.92 / ((right - left) * scale), DETAIL_SIZE[1] * 0.84 / ((front - back) * scale),
                   DETAIL_PX_PER_M[1] / scale)
        # The point of ground that belongs under the view's origin, which lies below the picture's middle.
        across, depth = (left + right) * 0.5, (back + front) * 0.5 + (front - back) * 0.08
        return (depth + across * 0.5, depth - across * 0.5), zoom

    waiting = sorted((p for p in garden.plantings if p.kind != "grove"), key=lambda p: (p.x - p.y, p.x + p.y))
    views = []
    while waiting:
        members = [waiting.pop(0)]
        while waiting:
            across = sum(p.x - p.y for p in members) / len(members)
            depth = sum(p.x + p.y for p in members) / len(members) * 0.5
            # The picture is wider than tall: a neighbour behind counts as further than one beside.
            nearest = min(waiting, key=lambda p: math.hypot(p.x - p.y - across, ((p.x + p.y) * 0.5 - depth) * 1.6))
            if framing(members + [nearest])[1] * scale < DETAIL_PX_PER_M[0]:
                break
            members.append(nearest)
            waiting.remove(nearest)
        views.append((members, *framing(members)))
    return [(f"detail_{index + 1:02d}", f"Garden detail {index + 1} of {len(views)}",
             ", ".join(garden.label(p.species_id) for p in members), centre, zoom)
            for index, (members, centre, zoom) in enumerate(views)]


def render_view(garden, renderer, size, centre, zoom):
    sim = garden.sim
    sim.isometric_view_center, sim.isometric_view_zoom = centre, zoom
    surface = pygame.Surface(size)
    renderer.paint_for(renderer._projection(surface, sim)["scale"])
    renderer.draw(surface, sim)
    return surface, sim._isometric_projection_state


def plants_in_overview(garden, renderer):
    """How many plants of each species the overview draws: its representatives and its display plants."""
    sim = garden.sim
    sim.isometric_view_center, sim.isometric_view_zoom = None, 1.0
    surface = pygame.Surface(OVERVIEW_SIZE)
    instances = sim.get_species_sprite_instances()
    # The same question the renderer asks; its answer is kept for when the overview is drawn.
    instances = instances + garden.sampler.sample(
        sim.ecology, instances, true_scale=True,
        window=renderer._vegetation_window(surface, renderer._projection(surface, sim)))
    counts = {}
    for item in instances:
        counts[item["species_id"]] = counts.get(item["species_id"], 0) + 1
    return counts


def content_frame(surface, margin=48):
    """The part of a picture that is not empty background, with a margin."""
    pixels = pygame.surfarray.pixels3d(surface)
    filled = (pixels != np.array(BACKGROUND, dtype=np.uint8)).any(axis=2)
    columns, rows = np.flatnonzero(filled.any(axis=1)), np.flatnonzero(filled.any(axis=0))
    del pixels
    frame = pygame.Rect(columns[0], rows[0], columns[-1] - columns[0] + 1, rows[-1] - rows[0] + 1)
    return frame.inflate(margin * 2, margin * 2).clip(surface.get_rect())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--views", default="all", help="'all', or a comma-separated choice of overview, details, detail_01, detail_02, ...")
    parser.add_argument("--out", default=str(OUTPUT), help="folder for the pictures and garden.json")
    parser.add_argument("--cap", type=int, default=SPRITE_HEIGHT_CAP, help="Pixel height cap for kept plant pictures")
    parser.add_argument("--caps", help="Comma-separated pixel caps; render the same garden at each")
    parser.add_argument("--plantae-only", action="store_true", help="Only live Plantae with raw authored plant fields")
    args = parser.parse_args(argv)
    caps = [int(value) for value in args.caps.split(",")] if args.caps else [args.cap]
    if any(cap < 84 or cap > 1400 for cap in caps):
        parser.error("pixel caps must be between 84 and 1400")
    output = Path(args.out)
    output.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    pygame.init()
    world = WorldModel()
    garden = Garden(world)
    garden.sim.isometric_sprite_height_cap = args.cap
    if args.plantae_only:
        from tools.render_authored_plant_caps import authored_species
        ids = set(authored_species(world))
        garden.authored = [p for p in garden.sim.species_profiles if p.species_id in ids]
        garden.unauthored = [p for p in garden.sim.species_profiles if p.species_id not in ids]
    garden.plan()
    garden.plant()
    renderer = GardenRenderer(garden)
    ecology = garden.sim.ecology
    print(f"Planted {len(garden.plantings)} species and {garden.lawn_patches} patches of lawn "
          f"in {time.perf_counter() - started:.0f} s", flush=True)

    plants = sum(profile.growth_form != "lichen" for profile in garden.authored)
    views = [("overview", f"BOTANICAL GARDEN  ·  {plants} authored plants and {len(garden.authored) - plants} lichens",
              "", None, 1.0)] + detail_views(garden, renderer)
    wanted = None if args.views == "all" else {name.strip() for name in args.views.split(",")}
    shown = plants_in_overview(garden, renderer)
    missing = [garden.label(profile.species_id) for profile in garden.authored if not shown.get(profile.species_id)]
    if missing:
        print("NOT VISIBLE in the overview: " + ", ".join(missing))
    cap_views = [(name, title, members, centre, zoom, cap) for cap in caps
                 for name, title, members, centre, zoom in views]
    for name, title, members, centre, zoom, cap in cap_views:
        if wanted is not None and name not in wanted and not (name != "overview" and "details" in wanted):
            continue
        garden.sim.isometric_sprite_height_cap = cap
        view_started = time.perf_counter()
        overview = name == "overview"
        if len(caps) > 1:
            name += f"_cap_{cap:03d}"
        title += f" · {cap} px cap"
        surface, state = render_view(garden, renderer, OVERVIEW_SIZE if overview else DETAIL_SIZE, centre, zoom)
        if overview:
            frame = content_frame(surface)
            pygame.image.save(surface.subsurface(frame), str(output / f"garden_{name}_unlabelled.png"))
            lines = [
                "Laid out by the Biosphere: each species stands where the ecology kernel scores the ground highest for it,",
                "as one stand of recorded plants, each drawn as one of the ten individuals the garden keeps of its species.",
                "Ground wetness rises from the dry bank on the left to the pond on the right.",
            ]
        else:
            lines = [members]
        # The renderer keeps a plant some 20 px tall however far the view pulls back.
        lines.append(f"Plants at their real size; those under {20.0 / state['scale']:.1f} m are drawn larger to stay visible.")
        draw_labels(surface, renderer, state, garden)
        if overview:
            surface = surface.subsurface(frame).copy()
        draw_header(surface, title, lines, state["scale"])
        path = output / f"garden_{name}.png"
        pygame.image.save(surface, str(path))
        print(f"{path}  ({state['scale']:.1f} px/m, {time.perf_counter() - view_started:.0f} s)", flush=True)

    record = {
        "source": "live ontology-backed WorldModel; the garden's ground is an in-memory fixture",
        "garden_side_m": garden.ground.side, "pictures": sorted(path.name for path in output.glob("garden_*.png")),
        "pixel_height_caps": caps,
        "lawn": {"species_id": LAWN_SPECIES, "population_patches": garden.lawn_patches},
        "plantings": [{
            "species_id": planting.species_id, "label": ecology.profiles[planting.species_id].label,
            "growth_form": ecology.profiles[planting.species_id].growth_form, "kind": planting.kind,
            "x_m": round(planting.x, 1), "y_m": round(planting.y, 1), "radius_m": round(planting.radius_m, 1),
            "ground_radius_m": round(planting.reach_m, 1),
            "kernel_suitability": round(planting.suitability, 3), "kernel_expected_cover": round(planting.cover, 3),
            "limited_by": planting.limit, "plants_in_overview": shown.get(planting.species_id),
        } for planting in garden.plantings],
        "not_visible_in_overview": missing,
        "species_without_authored_plant_traits": sorted(profile.species_id for profile in garden.unauthored),
    }
    (output / "garden.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(f"{output / 'garden.json'}  (total {time.perf_counter() - started:.0f} s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
