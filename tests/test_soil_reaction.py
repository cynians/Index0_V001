"""A plant with an authored range of soil pH is kept to ground of that reaction, by the kernel and the solver."""
import os
import unittest
from dataclasses import replace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import numpy as np

from simulations.biosphere.ecology import BiosphereEcology, potential_suitability, profile_from_entity, reaction_response
from simulations.biosphere.flora import BiomeFlora
from simulations.biosphere.potential_vegetation import resident_vegetation
from tests import test_biome_flora as flora_fixtures
from tests import test_water_balance as water_fixtures


class SoilReactionTests(unittest.TestCase):
    def _plants(self):
        any_ground = profile_from_entity(dict(flora_fixtures.OAK))
        of_chalk = profile_from_entity(dict(flora_fixtures.OAK, soil_ph_range={"min": 6.5, "max": 8.5}))
        of_heath = profile_from_entity(dict(flora_fixtures.OAK, soil_ph_range={"min": 3.5, "max": 5.5}))
        return any_ground, of_chalk, of_heath

    def test_a_plant_grows_within_its_range_of_ph_and_fails_a_unit_beyond(self):
        any_ground, of_chalk, of_heath = self._plants()
        self.assertEqual((any_ground.soil_ph_range, of_chalk.soil_ph_range), (None, (6.5, 8.5)))
        ph = np.array([3.0, 4.5, 5.5, 6.0, 6.5, 7.5, 8.5, 9.0, 9.5, np.nan])
        np.testing.assert_allclose(reaction_response(of_chalk, ph), [0.0, 0.0, 0.0, 0.5, 1.0, 1.0, 1.0, 0.5, 0.0, 1.0])
        np.testing.assert_allclose(reaction_response(of_heath, ph)[:5], [0.5, 1.0, 1.0, 0.5, 0.0])
        np.testing.assert_array_equal(reaction_response(any_ground, ph), 1.0)       # one without a range is not asked
        self.assertIsNone(profile_from_entity(dict(flora_fixtures.OAK, soil_ph_range={"min": 7, "max": 5})).soil_ph_range)

    def test_the_kernel_and_the_solver_keep_it_off_ground_of_the_wrong_reaction(self):
        any_ground, of_chalk, of_heath = self._plants()
        ecology = BiosphereEcology({"min_x": 0.0, "max_x": 10.0, "min_y": 0.0, "max_y": 10.0}, [any_ground])
        sour = {"soil_moisture": 0.42, "surface_solar_exposure": 1.0, "soil_fertility": 0.8, "soil_ph": 4.5}
        factors = ecology.suitability_factors(of_chalk, sour)
        self.assertEqual((factors["suitability"], factors["limiting"], factors["scores"]["soil reaction"]), (0.0, "soil reaction", 0.0))
        self.assertGreater(ecology.suitability_factors(of_heath, sour)["suitability"], 0.5)
        self.assertNotIn("soil reaction", ecology.suitability_factors(any_ground, sour)["scores"])
        self.assertEqual(ecology.suitability_factors(any_ground, sour)["suitability"], ecology.suitability_factors(of_heath, sour)["suitability"])
        potential = ecology.site_potential(of_chalk, sour)
        self.assertEqual((potential["reaction"], potential["open"], potential["sheltered"]), (0.0, 0.0, 0.0))
        self.assertEqual(ecology.site_potential(any_ground, sour)["reaction"], 1.0)
        wet = np.full(3, 0.42)
        np.testing.assert_array_equal(potential_suitability(of_chalk, wet, 293.0, 276.0, soil_ph=np.array([4.5, 7.5, np.nan])) > 0.0,
                                      [False, True, True])

        class SourWest(water_fixtures.BalancedRiverGround):
            """The river fixture on two rocks: sour ground west of 200 m, limy ground east of it."""

            def sample_array(self, key, x, y, default=0.0):
                if key == "soil_ph":
                    return np.where(np.asarray(x, dtype=np.float64) < 200.0, 4.5, 7.8)
                return super().sample_array(key, x, y, default)

        chalk, heath = replace(of_chalk, species_id="spec_chalk_oak"), replace(of_heath, species_id="spec_heath_oak")
        flora = BiomeFlora(flora_fixtures.PLANET, flora_fixtures.CFB)
        flora.record(chalk.species_id, "dominant")
        flora.record(heath.species_id, "dominant")
        bounds = dict(min_x=0.0, max_x=400.0, min_y=0.0, max_y=200.0)
        vegetation = resident_vegetation(SourWest(), bounds, {chalk.species_id: chalk, heath.species_id: heath},
                                         {flora_fixtures.CFB.key: flora}, cells=80)
        west, east = vegetation.x < 150.0, vegetation.x > 250.0
        none = np.zeros(vegetation.x.shape)
        self.assertEqual(float(vegetation.cover.get(chalk.species_id, none)[west].max()), 0.0)
        self.assertEqual(float(vegetation.cover.get(heath.species_id, none)[east].max()), 0.0)
        self.assertGreater(float(vegetation.cover[chalk.species_id][east].mean()), 0.1)
        self.assertGreater(float(vegetation.cover[heath.species_id][west].mean()), 0.1)


if __name__ == "__main__":
    unittest.main()
