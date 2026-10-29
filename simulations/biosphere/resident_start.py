"""A Biosphere opened where the biome already has a flora starts with that flora standing.

The loop the floras were built for (``docs/biosphere_worldgen_hookup_v001.md``
section 3.7): plants A and B are established on a planet; the player brings
in C beside them.  So a site in a biome whose flora holds A and B does not
open on bare ground.  What grows there is worked out by the same solver that
plants a city's map (``potential_vegetation.resident_vegetation``), and set
out as the Biosphere's first populations:

* every species the flora gives the ground is one grown stand over the
  living area, its plants where the solver stands them and as far grown as
  it has them (a sward or a crust is a cover of the same share);
* the soil under them is built: a wood does not stand on raw ground;
* they are the site's own from the first season: nothing is told of their
  establishing, and a plot's share of them does not rewrite the planet's
  flora;
* only what the player brings in makes the living area grow, and the ground
  it grows into comes with its residents.

From then on they are populations like any other: they compete, the river
takes them, they die out and spread.  One stand to a species means the
kernel judges a species over the whole living area, not swale by swale: the
solver's sorting along the ground is where they start, not a rule they keep.
"""

from __future__ import annotations

import hashlib
import math

import numpy as np

from simulations.biosphere.flora import planet_floras
from simulations.biosphere.plant_pictures import FOUNDERS
from simulations.biosphere.potential_vegetation import plant_number, planet_seed, resident_vegetation


# The solver's window round the living area: at least this wide, and this many cells along it.
WINDOW_MIN_M = 160.0
WINDOW_DOMAINS = 2.5
WINDOW_CELLS = 64
# The soil a grown community stands on, where the flora covers the ground: organic matter above what the
# most demanding plants ask (``SoilOrganicMatterField.TIER_REQUIREMENTS_KG_M2``), and the nitrogen and
# phosphorus such a soil turns over.  Thinly covered ground has as much less.
RESIDENT_ORGANIC_MATTER_KG_M2 = 4.0
RESIDENT_NITROGEN_G_M2 = 4.0
RESIDENT_PHOSPHORUS_G_M2 = 1.0
FULL_SOIL_COVER = 0.5
# Cover under this is no stand of a sward or a crust.
LEAST_COVER = 0.01
# Points along a side at which a cover's share of new ground is read.
COVER_SAMPLES = 16


def kept_individual(marks):
    """Which of its species' first kept individuals each plant is drawn as: the same wherever it is set out from."""
    return np.minimum(FOUNDERS - 1, np.floor(plant_number(marks, 0) * FOUNDERS)).astype(np.int64)


class ResidentFlora:
    """The plants the floras of a planet have growing on a Biosphere's ground."""

    def __init__(self, simulation, floras):
        self.simulation = simulation
        self.floras = floras
        # Species set out here as residents: they do not drive the living area, nor are they entered again.
        self.species = set()
        # The planet's seed: what stands here is what the map of this ground shows.
        self.seed = planet_seed(simulation.planet_id)
        self._window = None
        self._vegetation = None

    @classmethod
    def of(cls, simulation):
        """The resident flora of a simulation's ground, or ``None`` where it opens on bare ground."""
        if simulation.substrate is None or getattr(simulation, "terrain_frame", None) is None:
            return None
        if simulation.biosphere_context.get("start_bare"):
            return None
        floras = {key: flora for key, flora in planet_floras(simulation.world_model, simulation.planet_id).items()
                  if flora.records}
        return cls(simulation, floras) if floras else None

    # ------------------------------------------------------------------
    def profiles(self):
        """The profiles of every species a flora of this ground holds."""
        known = self.simulation.ecology.profiles
        return {species_id: known[species_id]
                for flora in self.floras.values() for species_id in flora.species() if species_id in known}

    def vegetation(self):
        """What the floras give the ground round the living area; solved again when the area outgrows it."""
        ecology = self.simulation.ecology
        domain = ecology.bounds
        window = self._window
        if window is not None and all(window[f"min_{axis}"] <= domain[f"min_{axis}"]
                                      and window[f"max_{axis}"] >= domain[f"max_{axis}"] for axis in "xy"):
            return self._vegetation
        frame = self.simulation.terrain_frame
        side = max(WINDOW_MIN_M, WINDOW_DOMAINS * max(ecology.width, ecology.height))
        centre_x, centre_y = 0.5 * (domain["min_x"] + domain["max_x"]), 0.5 * (domain["min_y"] + domain["max_y"])
        window = {
            "min_x": max(frame["min_x"], min(domain["min_x"], centre_x - 0.5 * side)),
            "max_x": min(frame["max_x"], max(domain["max_x"], centre_x + 0.5 * side)),
            "min_y": max(frame["min_y"], min(domain["min_y"], centre_y - 0.5 * side)),
            "max_y": min(frame["max_y"], max(domain["max_y"], centre_y + 0.5 * side)),
        }
        self._window = window
        self._vegetation = resident_vegetation(self.simulation.substrate, window, self.profiles(), self.floras,
                                               cells=WINDOW_CELLS, seed=self.seed)
        return self._vegetation

    def settle(self, previous=None):
        """Set out the residents of the living area, or of the ground it has grown by since ``previous``.

        Returns the species set out and how many plants (``None`` for a cover).
        """
        simulation, ecology = self.simulation, self.simulation.ecology
        vegetation = self.vegetation()
        domain = dict(ecology.bounds)
        width, height = domain["max_x"] - domain["min_x"], domain["max_y"] - domain["min_y"]
        centre_x, centre_y = domain["min_x"] + 0.5 * width, domain["min_y"] + 0.5 * height
        # A disc of the living area's size: a stand's cover is its plants over its disc.
        radius = math.sqrt(width * height / math.pi)

        def new_ground(x, y):
            inside = (x >= domain["min_x"]) & (x <= domain["max_x"]) & (y >= domain["min_y"]) & (y <= domain["max_y"])
            if previous is None:
                return inside
            return inside & ~((x >= previous["min_x"]) & (x <= previous["max_x"])
                              & (y >= previous["min_y"]) & (y <= previous["max_y"]))

        sample_x, sample_y = np.meshgrid(domain["min_x"] + (np.arange(COVER_SAMPLES) + 0.5) * width / COVER_SAMPLES,
                                         domain["min_y"] + (np.arange(COVER_SAMPLES) + 0.5) * height / COVER_SAMPLES)
        fresh = new_ground(sample_x, sample_y)
        set_out = {}
        # The tall first: what stands under them finds them there.
        for species_id in sorted(vegetation.cover, key=lambda item: (-ecology.profiles[item].mature_height_m, item)):
            profile = ecology.profiles[species_id]
            text = f"resident:{species_id}:{centre_x:.3f}:{centre_y:.3f}:{radius:.3f}:{ecology.season}"
            if ecology.keeps_individuals(profile):
                x, y, grown, mark = vegetation.individuals(
                    species_id, ecology.spacing_m(profile), seed=self.seed,
                    window=(domain["min_x"], domain["min_y"], domain["max_x"], domain["max_y"]))
                here = new_ground(x, y)
                if not here.any():
                    continue
                # Each plant is the individual it is seen as from outside the living area (``surroundings``).
                ecology.found_grown_stand(species_id, centre_x, centre_y, radius, x[here], y[here], grown[here], text,
                                          variants=kept_individual(mark[here]))
                set_out[species_id] = int(here.sum())
            else:
                # Its share of the new ground, spread over the stand's whole disc: stands of one species
                # that lie in each other are made one, cover for cover.
                cover = float(np.where(fresh, vegetation.cover_at(species_id, sample_x, sample_y), 0.0).mean())
                if cover < LEAST_COVER:
                    continue
                ecology.found_grown_stand(species_id, centre_x, centre_y, radius, (), (), (), text, cover=cover)
                set_out[species_id] = None
        self._build_soil(vegetation, previous)
        self.species.update(set_out)
        # They are the site's own: nothing is told of their establishing or their first seed.
        simulation._established_species.update(set_out)
        simulation._seeding_species.update(set_out)
        simulation._reported_soil_tier = max(
            simulation._reported_soil_tier, int(simulation.soil.summary()["supported_succession_tier"]))
        return set_out

    def _build_soil(self, vegetation, previous):
        """Give the ground under the residents the soil a grown community stands on."""
        soil = self.simulation.soil
        columns, rows = soil.columns, soil.rows
        x = soil.bounds["min_x"] + (np.arange(columns) + 0.5) * soil.width / columns
        y = soil.bounds["min_y"] + (np.arange(rows) + 0.5) * soil.height / rows
        grid_x, grid_y = np.meshgrid(x, y)
        cover = np.zeros(grid_x.shape)
        for species_id in vegetation.cover:
            cover += vegetation.cover_at(species_id, grid_x, grid_y)
        built = np.clip(cover / FULL_SOIL_COVER, 0.0, 1.0)
        if previous is not None:
            built = np.where((grid_x >= previous["min_x"]) & (grid_x <= previous["max_x"])
                             & (grid_y >= previous["min_y"]) & (grid_y <= previous["max_y"]), 0.0, built)
        for name, full in (("organic_matter_rows", RESIDENT_ORGANIC_MATTER_KG_M2),
                           ("available_nitrogen_rows", RESIDENT_NITROGEN_G_M2),
                           ("available_phosphorus_rows", RESIDENT_PHOSPHORUS_G_M2)):
            values = np.asarray(getattr(soil, name), dtype=np.float64)
            setattr(soil, name, np.maximum(values, built * full).tolist())
        soil.revision += 1
