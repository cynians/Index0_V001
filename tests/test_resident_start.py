"""A Biosphere opened where the biome has a flora starts with that flora growing."""
import os
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import numpy as np
import pygame

from simulations.biosphere import terrain_site
from simulations.biosphere.biosphere_simulation import BiosphereSimulation
from simulations.biosphere.flora import biome_flora, planet_floras
from simulations.biosphere.resident_start import RESIDENT_ORGANIC_MATTER_KG_M2
from tests import test_biome_flora as flora_fixtures
from tests import test_biosphere_terrain_site as site_fixtures

OAK, GRASS = flora_fixtures.OAK["id"], flora_fixtures.GRASS
WIDE = {"min_x": 200.0, "max_x": 320.0, "min_y": 10.0, "max_y": 118.0}


def _inside(bounds, x, y):
    return (x >= bounds["min_x"]) & (x <= bounds["max_x"]) & (y >= bounds["min_y"]) & (y <= bounds["max_y"])


class ResidentStartTests(unittest.TestCase):
    def setUp(self):
        pygame.init()

    def _sim(self, flora=True, **context):
        world = site_fixtures._world(dict(flora_fixtures.OAK))
        if flora:
            resident = biome_flora(world, flora_fixtures.PLANET, flora_fixtures.CFB)
            # Oaks in woods with open ground between them: a sward does not hold under closed oaks.
            resident.record(OAK, "common")
            resident.record(GRASS, "dominant")
        site = terrain_site.found_biosphere_site(world, site_fixtures.REGION_ID, site_fixtures._region_point(260.0, 64.0), year=2400)
        return world, BiosphereSimulation(world, {"patch_location_id": site["id"], "year": 2400, **context})

    def test_ground_without_a_flora_and_a_site_asked_to_open_bare_start_as_before(self):
        _world, bare = self._sim(flora=False)
        self.assertIsNone(bare.resident_flora)
        self.assertEqual(bare.ecology.patches, [])
        _world, asked = self._sim(start_bare=True)
        self.assertIsNone(asked.resident_flora)
        self.assertEqual((asked.ecology.patches, asked.field_notes), ([], []))
        self.assertEqual(float(np.max(asked.soil.organic_matter_rows)), 0.0)

    def test_the_flora_of_the_ground_is_growing_there_full_grown_on_built_soil(self):
        _world, sim = self._sim()
        self.assertIsNotNone(sim.resident_flora)
        self.assertIn(GRASS, sim.resident_flora.species)
        sward = sim.ecology.species_patches(GRASS)
        self.assertEqual(len(sward), 1)
        self.assertGreater(sward[0].abundance, 0.2)
        self.assertGreaterEqual(sward[0].development_days, sim.ecology.profiles[GRASS].maturity_days)
        self.assertIsNone(sim.ecology.individuals.members(sward[0].patch_id))   # a sward is cover, not plants
        # The soil a grown community stands on: every tier can be planted from the first day, and nobody is told.
        self.assertGreater(float(np.mean(sim.soil.organic_matter_rows)), 0.5 * RESIDENT_ORGANIC_MATTER_KG_M2)
        self.assertTrue(sim.is_species_unlocked(OAK))
        self.assertEqual(sim._reported_soil_tier, 3)
        self.assertEqual([note["text"] for note in sim.field_notes],
                         [f"{len(sim.resident_flora.species)} plants of this ground's flora grow here already"])

        # Ground the living area grows into comes with what grows on it; the ground it had is not planted twice.
        first = dict(sim.bounds)
        before = {patch.patch_id for patch in sim.ecology.patches}
        sim._set_domain(WIDE)
        self.assertIn(OAK, sim.resident_flora.species)
        oaks = [patch for patch in sim.ecology.species_patches(OAK) if patch.patch_id not in before]
        self.assertEqual(len(oaks), 1)
        members = sim.ecology.individuals.members(oaks[0].patch_id)
        self.assertGreater(len(members), 3)
        self.assertTrue(_inside(WIDE, members.x, members.y).all())
        self.assertFalse(_inside(first, members.x, members.y).any())
        profile = sim.ecology.profiles[OAK]
        self.assertEqual(oaks[0].development_days, profile.maturity_days)
        grown = (oaks[0].development_days - members.lag_days) / profile.maturity_days
        self.assertTrue(0.15 - 1e-9 <= float(grown.min()) and float(grown.max()) <= 1.0)
        self.assertGreater(float(np.mean(grown)), 0.6)   # most are full-grown, some younger
        self.assertTrue((members.born <= sim.ecology.season).all())
        organic = np.asarray(sim.soil.organic_matter_rows)
        self.assertGreater(float(np.mean(organic)), 0.5 * RESIDENT_ORGANIC_MATTER_KG_M2)

    def test_residents_are_the_sites_own_and_do_not_drive_the_living_area(self):
        world, sim = self._sim()
        first = {patch.patch_id for patch in sim.ecology.patches}
        sim._set_domain(WIDE)
        flora = planet_floras(world, flora_fixtures.PLANET)["Cfb"]
        before = {species_id: (flora.rarity(species_id), flora.records[species_id].cover_share) for species_id in (OAK, GRASS)}
        extent = dict(sim.bounds)
        # They stand at every rim, and the living area stays as it is: only what is brought in makes it grow.
        self.assertGreater(sim.ecology.edge_abundance(), 0.075)
        self.assertEqual(sim.ecology.edge_abundance(ignore=sim.resident_flora.species), 0.0)
        self.assertFalse(sim._expand_if_population_reaches_edge())
        sim.advance_seasons(8)
        self.assertEqual(dict(sim.bounds), extent)
        # The stand of the first ground lies in the stand of the wider ground: the two are one now.
        self.assertTrue(first)
        self.assertFalse(first & {patch.patch_id for patch in sim.ecology.patches})
        self.assertGreater(sum(len(sim.ecology.individuals.members(patch.patch_id))
                               for patch in sim.ecology.species_patches(OAK)), 3)
        # Nothing is told of their establishing, and a plot does not rewrite what the planet's flora says of them.
        told = " | ".join(note["text"] for note in sim.field_notes)
        for phrase in ("established", "sets seed", "is now part of", "flora"):
            self.assertNotIn(phrase, told.replace("this ground's flora grow here already", ""))
        self.assertEqual({species_id: (flora.rarity(species_id), flora.records[species_id].cover_share)
                          for species_id in (OAK, GRASS)}, before)


if __name__ == "__main__":
    unittest.main()
