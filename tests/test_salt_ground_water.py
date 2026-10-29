"""Whose water the ground water of a coast is, and what bears it (``fine_hydrology.groundwater_salinity``)."""
import os
import unittest
from dataclasses import replace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import numpy as np

from simulations.biosphere import biomes
from simulations.biosphere.ecology import (
    BiosphereEcology, potential_suitability, profile_from_entity, salinity_limits, salt_in_reach, salt_response, salt_score,
)
from simulations.biosphere.flora import BiomeFlora
from simulations.biosphere.potential_vegetation import resident_vegetation
from simulations.map.worldgen_substrate import WATER_BALANCE_FIELDS
from simulations.world_gen import fine_hydrology as fh
from tests import test_biome_flora as flora_fixtures
from tests import test_fine_scale_ground as ground_fixtures
from tests import test_water_balance as water_fixtures


class LensTests(unittest.TestCase):
    def test_fresh_water_floats_forty_times_as_deep_as_it_stands_above_the_sea(self):
        self.assertAlmostEqual(fh.LENS_DEPTH_PER_HEAD, 40.0)
        sea = np.array([[True, False, False, False, False]])
        ground = np.array([[-1.0, 2.0, 2.0, 2.0, 2.0]])
        # A table at sea level is the sea's; one that carries a lens as thick as the zone of mixing is fresh.
        fresh_from = fh.MIXING_ZONE_M / (1.0 + fh.LENS_DEPTH_PER_HEAD)
        table = np.array([[0.0, 0.0, 0.5 * fresh_from, fresh_from, 1.0]])
        salt = fh.groundwater_salinity(table, sea, ground, 0.0)
        np.testing.assert_allclose(salt, [[1.0, 1.0, 0.5, 0.0, 0.0]], atol=1e-9)
        self.assertLess(fresh_from, 0.13)   # a hand of fresh water above the sea is enough
        # Sea level is where the sea is, not nought.
        np.testing.assert_allclose(fh.groundwater_salinity(table + 30.0, sea, ground + 30.0, 30.0), salt, atol=1e-9)
        # A tile without sea tells nothing.
        self.assertIsNone(fh.groundwater_salinity(table, np.zeros_like(sea), ground, 0.0))
        self.assertIsNone(fh.groundwater_salinity(table, sea, ground, None))

    def test_the_tides_flood_low_ground_joined_to_the_sea_and_no_other(self):
        sea = np.array([[True, False, False, False, False, False]])
        #                 sea   flat  flat  ridge hollow rise
        ground = np.array([[-2.0, 0.4, 0.8, 3.0, 0.3, 5.0]])
        table = np.array([[0.0, 0.4, 0.8, 1.5, 0.3, 2.0]])   # fresh under all the land
        np.testing.assert_array_equal(fh.groundwater_salinity(table, sea, ground, 0.0), [[1, 0, 0, 0, 0, 0]])
        # Two metres of tide: mean high water a metre up.  The flat is flooded, the hollow behind the ridge is not.
        np.testing.assert_array_equal(fh.groundwater_salinity(table, sea, ground, 0.0, tidal_range=2.0), [[1, 1, 1, 0, 0, 0]])
        np.testing.assert_array_equal(fh.tidal_ground(sea, ground, 1.0), [[False, True, True, False, False, False]])
        self.assertEqual(fh.tidal_range_m({"regional_landforms": {"landforms": [
            {"landform": "sea_cliff", "tidal_range_m": 1.6}, {"landform": "beach", "tidal_range_m": 1.6}, {"landform": "other"}]}}), 1.6)
        self.assertEqual(fh.tidal_range_m({}), 0.0)


class CoastTileTests(unittest.TestCase):
    """The coast of ``test_water_balance.FinerTileTests``: ground rising 2 cm a metre out of the sea."""

    def _coast(self, recharge_mm):
        parent, _water, child, _ripple = water_fixtures.FinerTileTests()._tiles()
        cycle = ground_fixtures._water_cycle(recharge_mm=recharge_mm)
        return parent, child, cycle, fh.refine_surface_hydrology(parent, cycle)

    def test_rain_holds_the_sea_out_of_the_ground_and_want_of_it_lets_it_in(self):
        parent, _child, _cycle, humid = self._coast(300.0)
        _parent, _child, _cycle, arid = self._coast(0.0)
        ground = np.asarray(parent["sample_grid"]["rows"])
        for water in (humid, arid):
            self.assertIn("sea water", water["runoff_grid"]["groundwater_salinity_contract"])
        wet, dry = (np.asarray(water["runoff_grid"]["groundwater_salinity_rows"]) for water in (humid, arid))
        sea, land = ground <= 0.0, ground > 0.0
        self.assertTrue((wet[sea] == 1.0).all() and (dry[sea] == 1.0).all())
        self.assertTrue(((wet >= 0.0) & (wet <= 1.0)).all())
        # Under rain the ground water is fresh but for a fringe at the water line.
        self.assertLess(float((wet[land] >= 0.1).mean()), 0.08)
        self.assertEqual(float(wet[ground > 1.0].max()), 0.0)
        # With no recharge nothing stands above the sea: the ground water is the sea's under all the low ground
        # (under the highest the hillslope reading keeps a table of its own, far out of any root's reach).
        self.assertEqual(float(dry[land & (ground < 8.0)].min()), 1.0)
        self.assertEqual(humid["fine_surface_hydrology"]["salt_ground_water"]["tidal_range_m"], 0.0)
        self.assertLess(humid["fine_surface_hydrology"]["salt_ground_water"]["land_share_salt"],
                        arid["fine_surface_hydrology"]["salt_ground_water"]["land_share_salt"])
        # Ground without sea in sight tells none.
        inland = dict(parent, sea_level_m=None)
        self.assertNotIn("groundwater_salinity_rows", fh.refine_surface_hydrology(inland, ground_fixtures._water_cycle())["runoff_grid"])

    def test_a_finer_tile_takes_its_parents_figure(self):
        parent, child, cycle, parent_water = self._coast(0.0)
        shape = np.asarray(child["sample_grid"]["rows"]).shape
        refined = fh.refine_surface_hydrology(child, cycle, parent=(parent, parent_water))["runoff_grid"]
        mine = np.asarray(refined["groundwater_salinity_rows"])
        wanted = fh.parent_groundwater_salinity(child, parent, parent_water, shape)
        np.testing.assert_allclose(mine, np.clip(wanted, 0.0, 1.0), atol=0.006)
        # Left to itself the tile, which lies inland of the water line, sees no sea and tells nothing.
        self.assertNotIn("groundwater_salinity_rows", fh.refine_surface_hydrology(child, cycle)["runoff_grid"])
        self.assertIsNone(fh.parent_groundwater_salinity(child, parent, {"runoff_grid": {}}, shape))

    def test_the_substrate_hands_it_over_with_the_water_balance(self):
        self.assertIn("groundwater_salinity", WATER_BALANCE_FIELDS)


class PlantTests(unittest.TestCase):
    def _plants(self):
        oak = profile_from_entity(dict(flora_fixtures.OAK, salinity_tolerance="low"))
        return oak, replace(oak, salinity_tolerance="medium"), replace(oak, salinity_tolerance="high")

    def test_a_plant_bears_sea_water_by_its_tolerance(self):
        oak, hardy, halophyte = self._plants()
        self.assertEqual((oak.salinity_tolerance, oak.salinity_source), ("low", "authored salinity_tolerance"))
        unsaid = profile_from_entity(flora_fixtures.OAK)
        self.assertEqual((unsaid.salinity_tolerance, unsaid.salinity_source),
                         ("low", "unauthored: taken for a plant of fresh ground"))
        self.assertEqual(profile_from_entity(dict(flora_fixtures.OAK, salinity_tolerance="other_unknown")).salinity_tolerance, "low")
        salt = np.array([0.0, 0.05, 0.15, 0.25, 0.55, 1.0])
        np.testing.assert_allclose(salt_response(oak, salt), [1.0, 1.0, 0.5, 0.0, 0.0, 0.0])
        np.testing.assert_allclose(salt_response(hardy, salt), [1.0, 1.0, 1.0, 1.0 - 0.05 / 0.35, 0.0, 0.0])
        np.testing.assert_allclose(salt_response(halophyte, salt), 1.0)
        self.assertLess(salinity_limits(oak)[1], salinity_limits(hardy)[1])

    def test_salt_counts_as_far_as_the_roots_reach_the_ground_water(self):
        oak, _hardy, _halophyte = self._plants()
        deep, shallow = replace(oak, root_depth_class="deep"), replace(oak, root_depth_class="shallow")
        table = np.array([0.2, 1.5, 6.0])
        # Sea water at the table: in the roots of both where it stands high, in the tree's alone further down,
        # in nobody's under a dune.
        reached = salt_in_reach(deep, 1.0, table, 0.5), salt_in_reach(shallow, 1.0, table, 0.5)
        np.testing.assert_allclose(reached[0], [1.0, 1.0, 0.0])
        np.testing.assert_allclose(reached[1], [1.0, 0.0, 0.0])
        np.testing.assert_allclose(salt_in_reach(deep, np.nan, table, 0.5), 0.0)    # a map that tells none
        lily = replace(oak, growth_form="aquatic")
        np.testing.assert_allclose(salt_in_reach(lily, [0.0, 1.0], [0.0, 0.0]), [0.0, 1.0])   # it stands in it
        # At a place: no figure, no judgement; salt in reach, a limit like water.
        here = {"groundwater_salinity": 1.0, "water_table_depth_m": 0.2, "capillary_rise_m": 0.5}
        self.assertIsNone(salt_score(oak, {"water_table_depth_m": 0.2}))
        self.assertIsNone(salt_score(oak, dict(here, runtime_default_fields=("groundwater_salinity",))))
        self.assertEqual(salt_score(oak, here), 0.0)
        self.assertEqual(salt_score(oak, dict(here, water_table_depth_m=9.0)), 1.0)
        self.assertEqual(salt_score(replace(oak, salinity_tolerance="high"), here), 1.0)
        kelvin = np.array([290.0])
        self.assertEqual(float(potential_suitability(oak, 0.42, kelvin, kelvin - 10.0, salt=np.array([1.0]))[0]), 0.0)
        self.assertGreater(float(potential_suitability(oak, 0.42, kelvin, kelvin - 10.0, salt=np.array([0.0]))[0]), 0.5)

    def test_the_kernel_and_the_solver_keep_fresh_ground_plants_off_salt_ground(self):
        oak, _hardy, halophyte = self._plants()
        ecology = BiosphereEcology({"min_x": 0.0, "max_x": 10.0, "min_y": 0.0, "max_y": 10.0}, [oak])
        place = {"soil_moisture": 0.42, "surface_solar_exposure": 1.0, "soil_fertility": 0.8,
                 "groundwater_salinity": 1.0, "water_table_depth_m": 0.4, "capillary_rise_m": 0.5}
        factors = ecology.suitability_factors(oak, place)
        self.assertEqual((factors["suitability"], factors["limiting"], factors["scores"]["salt"]), (0.0, "salt", 0.0))
        self.assertGreater(ecology.suitability_factors(halophyte, place)["suitability"], 0.5)
        self.assertNotIn("salt", ecology.suitability_factors(oak, {k: v for k, v in place.items() if k != "groundwater_salinity"})["scores"])
        potential = ecology.site_potential(oak, place)
        self.assertEqual((potential["salt"], potential["open"], potential["sheltered"]), (0.0, 0.0, 0.0))

        class SaltShore(water_fixtures.BalancedRiverGround):
            """The river fixture with the sea for a river: salt ground water west of it, fresh east."""

            def sample_array(self, key, x, y, default=0.0):
                if key == "groundwater_salinity":
                    x = np.asarray(x, dtype=np.float64)
                    return np.where(x < 200.0, 1.0, 0.0)
                return super().sample_array(key, x, y, default)

        profiles = {oak.species_id: replace(oak, root_depth_class="deep")}
        flora = BiomeFlora(flora_fixtures.PLANET, flora_fixtures.CFB)
        flora.record(oak.species_id, "dominant")
        bounds = dict(min_x=0.0, max_x=400.0, min_y=0.0, max_y=200.0)
        fresh = resident_vegetation(water_fixtures.BalancedRiverGround(), bounds, profiles, {flora_fixtures.CFB.key: flora}, cells=80)
        salty = resident_vegetation(SaltShore(), bounds, profiles, {flora_fixtures.CFB.key: flora}, cells=80)
        x = fresh.x
        near_west, near_east = (x > 100.0) & (x < 140.0), (x > 260.0) & (x < 300.0)   # ground water in a tree's reach
        before, after = fresh.cover[oak.species_id], salty.cover.get(oak.species_id, np.zeros(x.shape))
        self.assertGreater(float(before[near_west].mean()), 0.2)
        self.assertEqual(float(after[near_west].max()), 0.0)
        np.testing.assert_allclose(after[near_east], before[near_east])
        # Far from the water the same salt lies out of reach and the oak stands as it did.
        far_west = x < 20.0
        np.testing.assert_allclose(after[far_west], before[far_west])

    def test_wet_salt_ground_is_a_salt_marsh_not_a_fen(self):
        fen = biomes.classify("Cfb", "Temperate Oceanic", water_table_depth_m=0.1)
        marsh = biomes.classify("Cfb", "Temperate Oceanic", water_table_depth_m=0.1, groundwater_salinity=0.8)
        self.assertEqual((fen.water, fen.key), ("wetland", "Cfb/wetland"))
        self.assertEqual((marsh.water, marsh.key, marsh.label), ("salt marsh", "Cfb/salt_marsh", "Temperate Oceanic salt marsh"))
        # Salt ground that is not wet has no word of its own; open water keeps its own.
        self.assertEqual(biomes.classify("Cfb", "x", water_table_depth_m=2.0, groundwater_salinity=1.0).water, "")
        self.assertEqual(biomes.classify("Cfb", "x", open_water=True, groundwater_salinity=1.0).water, "open water")
        self.assertEqual(biomes.classify("Cfb", "x", water_table_depth_m=0.1, groundwater_salinity=0.3).water, "wetland")


if __name__ == "__main__":
    unittest.main()
