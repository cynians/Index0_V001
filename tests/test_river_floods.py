"""Floods of a carved river: how often they cover and rework the ground, and what that leaves standing."""
import os
import unittest
from dataclasses import replace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import numpy as np
import pygame

from simulations.biosphere import terrain_site
from simulations.biosphere.biosphere_simulation import BiosphereSimulation
from simulations.biosphere.ecology import FLOOD_NEVER_YEARS, flood_standing_share, years_to_grow
from simulations.biosphere.flora import BiomeFlora
from simulations.biosphere.potential_vegetation import resident_vegetation
from simulations.world_gen import alluvial_channels as ac
from simulations.world_gen import fine_hydrology as fh
from simulations.world_gen import floodplain_relics as fr
from simulations.world_gen import river_floods as rf
from tests import test_biome_flora as flora_fixtures
from tests import test_biosphere_terrain_site as site_fixtures
from tests import test_fine_scale_ground as ground_fixtures
from tests import test_water_balance as water_fixtures


def _returns(above_mean_river_m, *, bankfull_to_mean=3.0, mean_depth_m=2.0, plain_widths=10.0):
    """``(covered, reworked)`` in years for ground that far above the mean river of a single-thread channel."""
    section = rf.SECTION_DEPTH_MEANS[0] * mean_depth_m
    bank = section * (1.0 - (1.0 / bankfull_to_mean) ** ac.AT_A_STATION_DEPTH_EXPONENT)
    growth = rf.flood_growth(bankfull_to_mean)
    height = np.asarray(above_mean_river_m, dtype=float) - bank
    return (rf.return_period_years(rf.discharge_for_stage(height, section, mean_depth_m, plain_widths), growth),
            rf.return_period_years(rf.discharge_for_stage(height + rf.REWORKING_DEPTH_SHARE * mean_depth_m, section,
                                                          mean_depth_m, plain_widths), growth), bank)


class FloodStageTests(unittest.TestCase):
    def test_the_section_the_channel_was_carved_with_tells_the_stage_of_a_flood(self):
        section, mean = 3.0, 2.0
        # Bank-full is one bankfull flow; the mean river is the mean flow; an empty channel none.
        self.assertAlmostEqual(float(rf.discharge_for_stage(0.0, section, mean, 10.0)), 1.0)
        at_mean = -section * (1.0 - (1.0 / 3.0) ** ac.AT_A_STATION_DEPTH_EXPONENT)
        self.assertAlmostEqual(float(rf.discharge_for_stage(at_mean, section, mean, 10.0)), 1.0 / 3.0, places=6)
        self.assertEqual(float(rf.discharge_for_stage(-section, section, mean, 10.0)), 0.0)
        # Over the banks a wide plain takes the rise out of a flood.
        narrow = float(rf.discharge_for_stage(1.0, section, mean, 3.0))
        wide = float(rf.discharge_for_stage(1.0, section, mean, 30.0))
        self.assertGreater(wide, narrow)
        self.assertAlmostEqual(float(rf.return_period_years(1.0, 0.4)), rf.BANKFULL_RETURN_YEARS)
        for years in (0.5, 2.0, 10.0, 100.0):
            for growth in rf.FLOOD_GROWTH:
                if 1.0 + growth * np.log(years / rf.BANKFULL_RETURN_YEARS) <= 0.0:
                    continue  # a flashy river has no flow that small to return that often
                stage = rf.stage_above_bank_m(years, section, mean, 10.0, growth)
                back = rf.return_period_years(rf.discharge_for_stage(stage, section, mean, 10.0), growth)
                self.assertAlmostEqual(float(back), years, delta=years * 1e-6)
        self.assertEqual(float(rf.flood_growth(3.0)), rf.FLOOD_GROWTH[0])
        self.assertEqual(float(rf.flood_growth(10.0)), rf.FLOOD_GROWTH[1])

    def test_low_bars_are_reworked_yearly_the_bank_top_in_decades_the_plain_above_never(self):
        covered, reworked, bank = _returns([0.0, 0.6, 1.07, 1.57, 3.07])
        self.assertAlmostEqual(bank, 1.07, delta=0.01)
        self.assertTrue(np.all(np.diff(covered) > 0.0) and np.all(np.diff(reworked) >= 0.0))
        self.assertTrue(np.all(reworked >= covered))
        self.assertLess(float(covered[0]), 0.5)                     # the water's edge: under water in every freshet
        self.assertLess(float(reworked[0]), 1.2)                    # and reworked about yearly
        self.assertTrue(1.5 < float(reworked[1]) < 6.0)             # where cottonwoods get away: every few years
        self.assertAlmostEqual(float(covered[2]), 1.5, delta=0.05)  # the bank top: the bankfull flow's return
        self.assertTrue(10.0 < float(reworked[2]) < 60.0)
        self.assertGreater(float(reworked[3]), 300.0)               # half a metre above the banks: left alone
        self.assertEqual(float(covered[4]), rf.NEVER_YEARS)
        # A flashy river of a dry climate floods and reworks ground far above its banks.
        dry_covered, dry_reworked, dry_bank = _returns([0.0, 1.81, 2.81, 3.81], bankfull_to_mean=10.0)
        self.assertAlmostEqual(dry_bank, 1.81, delta=0.01)
        self.assertLess(float(dry_reworked[2]), 40.0)
        self.assertLess(float(dry_covered[3]), 100.0)
        self.assertGreater(float(_returns(dry_bank + 1.0)[1]), 900.0)  # the same height above a steady river

    def test_a_site_hands_over_how_often_its_river_covers_and_reworks_each_cell(self):
        parent, parent_size = ground_fixtures._river_parent()
        shape = (201, 241)
        frame = ground_fixtures._child_frame(parent_size, (600.0, 460.0), (240.0, 200.0), shape)
        record = parent["heightmap_model"]["regional_landforms"]["landforms"][0]
        heightmap = dict(frame, map_detail_level=5, sea_level_m=None, regional_landforms={
            "landforms": [dict(record, inherited_reaches=record["reaches"], reaches=[])]})
        fields = ac.channel_fields(record["reaches"], shape, dx=frame["sample_spacing_x_m"], dy=frame["sample_spacing_y_m"],
                                   to_local=ac.local_frame(frame, shape)[2])
        inside = fields["in_channel"]
        self.assertGreater(float(fields["section_depth_m"][inside].min()), float(fields["mean_depth_m"][inside].max()))
        self.assertTrue(np.all(fields["mean_to_bankfull"][inside] < 0.5))
        level = np.where(np.isfinite(fields["stage_m"]), fields["stage_m"], 296.0) + 0.6
        channel_row = int(np.mean(np.nonzero(inside)[0]))
        terrace = np.where(np.arange(shape[0])[:, None] < channel_row, 3.0, 0.0) * np.ones((1, shape[1]))
        heightmap["sample_grid"] = {"rows": np.where(inside, fields["bank"] - fields["depth"], level + terrace).tolist()}
        trunk = {"id": "trunk", "estimated_discharge_m3_s": 15.0, "flow_regime": "intermittent",
                 "points": [{"x": 0.0, "y": 0.5}, {"x": 1.0, "y": 0.5}]}
        water = fh.refine_surface_hydrology(heightmap, ground_fixtures._water_cycle(
            [trunk], runoff_mm=24.0, precipitation_mm=570.0, evaporation_mm=2300.0, recharge_mm=10.0))
        surface = water["surface_water_grid"]
        covered = np.asarray(surface["flood_return_period_rows_years"])
        reworked = np.asarray(surface["flood_reworking_return_period_rows_years"])
        presence = np.asarray(surface["water_presence_rows"], dtype=bool)
        margin = np.maximum(fields["distance_m"] - 0.5 * fields["width_m"], 0.0)
        beside = (margin > 2.0) & (margin < 12.0) & ~presence
        bars = inside & ~presence
        self.assertEqual((float(covered[presence].max()), float(reworked[presence].max())), (0.0, 0.0))
        self.assertLess(float(np.median(covered[bars])), 2.0)
        self.assertLess(float(np.median(reworked[bars])), 5.0)
        self.assertLess(float(covered[beside & (terrace == 0.0)].max()), 2.0)
        self.assertEqual(float(covered[beside & (terrace > 0.0)].min()), rf.NEVER_YEARS)
        self.assertTrue(np.all(reworked >= covered))
        summary = water["fine_surface_hydrology"]["floods"]
        self.assertEqual(summary["rivers"], 1)
        self.assertGreater(summary["growth_per_efold"], rf.FLOOD_GROWTH[0])
        # A tile without a carved channel has no floods to tell.
        hollow, _elevation = ground_fixtures.FineHydrologyTest()._hollow()
        plain = fh.refine_surface_hydrology(hollow, ground_fixtures._water_cycle())
        self.assertNotIn("flood_return_period_rows_years", plain["surface_water_grid"])

    def test_floods_are_read_along_the_valley_not_off_the_nearest_bend(self):
        parent, parent_size = ground_fixtures._river_parent()
        channel = parent["heightmap_model"]["regional_landforms"]["landforms"][0]
        _residual, relics, frame, elevation = ground_fixtures._relics(parent, parent_size, origin_m=(300.0, 80.0))
        heightmap = dict(frame, map_detail_level=5, sea_level_m=None, sample_grid={"rows": elevation.tolist()},
                         regional_landforms={"landforms": [relics, dict(channel, inherited_reaches=channel["reaches"], reaches=[])]})
        shape = elevation.shape
        dx, dy, to_local, _to_uv = ac.local_frame(heightmap, shape)
        axis = relics["axes"][0]
        valley = fr.valley_frame([axis], shape, dx=dx, dy=dy, to_local=to_local)
        # Ground laid out by its height against the valley's bank level: at it, half a metre under, two metres over.
        offset = np.where(np.arange(shape[1])[None, :] < shape[1] // 3, -0.5,
                          np.where(np.arange(shape[1])[None, :] < 2 * shape[1] // 3, 0.0, 2.0)) * np.ones(shape)
        result = rf.flood_fields(heightmap, valley["bank"] + offset, bankfull_to_mean=3.0)
        covered, reworked = result["covered_years"], result["reworked_years"]
        low, level, high = (offset == -0.5), (offset == 0.0), (offset == 2.0)
        np.testing.assert_allclose(covered[level], rf.BANKFULL_RETURN_YEARS, rtol=1e-6)
        self.assertLess(float(covered[low].max()), rf.BANKFULL_RETURN_YEARS)
        self.assertGreater(float(covered[high].min()), 10.0 * rf.BANKFULL_RETURN_YEARS)
        # One height against the bank, one answer: no seam where the nearest point of the channel changes.
        for where in (low, level, high):
            self.assertLess(float(np.ptp(covered[where])), 1e-6 * float(covered[where].mean()) + 1e-9)
            self.assertLess(float(np.ptp(reworked[where])), 1e-6 * float(reworked[where].mean()) + 1e-9)
        self.assertEqual(result["summary"]["floodplain_widths"],
                         round(2.0 * axis["floodplain_half_width_m"] / axis["width_m"], 2))
        self.assertIsNone(rf.flood_fields({"sample_grid": {"rows": elevation.tolist()}}, elevation, bankfull_to_mean=3.0))


def _flooded_region(reworked_from_column=40):
    """The water-balance fixture with a river that reworks its east side every year."""
    region = water_fixtures._balanced_region(table_depth_m=1.0, capillary_rise_m=1.0)
    grid = site_fixtures._grid
    east = lambda column, _row: column >= reworked_from_column  # noqa: E731
    region["water_cycle_model"]["surface_water_grid"].update(
        flood_return_period_rows_years=grid(lambda column, row: 0.5 if east(column, row) else 30.0),
        flood_reworking_return_period_rows_years=grid(lambda column, row: 1.0 if east(column, row) else FLOOD_NEVER_YEARS),
    )
    return region


class BiosphereFloodTests(unittest.TestCase):
    def setUp(self):
        pygame.init()

    def _sim(self, east_m, **region):
        world = site_fixtures.BlueprintWorld([_flooded_region(**region), dict(flora_fixtures.OAK),
                                              *[dict(entity) for entity in site_fixtures.SPECIES]])
        site = terrain_site.found_biosphere_site(world, site_fixtures.REGION_ID, site_fixtures._region_point(east_m, 64.0), year=2400)
        sim = BiosphereSimulation(world, {"patch_location_id": site["id"], "year": 2400})
        for name, value in (("organic_matter_rows", 4.0), ("available_nitrogen_rows", 4.0), ("available_phosphorus_rows", 1.0)):
            setattr(sim.soil, name, [[value] * sim.soil.columns for _ in range(sim.soil.rows)])
        sim.soil.revision += 1
        return sim

    def test_a_plant_needs_its_years_between_two_floods(self):
        grass = replace(flora_fixtures.profile_from_entity(site_fixtures.SPECIES[1]), maturity_days=365.25)
        tree = replace(grass, growth_form="tree", maturity_days=30.0 * 365.25)
        self.assertAlmostEqual(years_to_grow(tree), 30.0)
        returns = np.array([1.0, 3.0, 30.0, 300.0, FLOOD_NEVER_YEARS, np.nan])
        np.testing.assert_allclose(flood_standing_share(grass, returns), [np.exp(-1.0), np.exp(-1.0 / 3.0), np.exp(-1.0 / 30.0),
                                                                          np.exp(-1.0 / 300.0), 1.0, 1.0])
        standing = flood_standing_share(tree, returns)
        self.assertLess(float(standing[1]), 1e-4)
        self.assertAlmostEqual(float(standing[2]), np.exp(-1.0))
        self.assertGreater(float(standing[3]), 0.9)

    def test_the_ground_tells_its_floods_and_the_catalogue_says_what_they_leave(self):
        swept, quiet = self._sim(400.0), self._sim(200.0)
        environment = swept.substrate.environment_at(400.0, 64.0)
        self.assertEqual((environment["flood_return_period_years"], environment["flood_reworking_return_period_years"]), (0.5, 1.0))
        self.assertEqual(quiet.substrate.environment_at(200.0, 64.0)["flood_reworking_return_period_years"], FLOOD_NEVER_YEARS)
        fit = swept.get_species_climate_fit(flora_fixtures.OAK["id"])
        self.assertEqual((fit["verdict"], fit["sustainable"]), ("unfit", False))
        self.assertIn("the river reworks this ground about every 1 year", fit["label"])
        self.assertIn("to grow up", fit["label"])
        self.assertNotEqual(quiet.get_species_climate_fit(flora_fixtures.OAK["id"])["verdict"], "unfit")
        self.assertNotIn("river", quiet.get_species_climate_fit(flora_fixtures.OAK["id"])["label"])
        potential = swept.ecology.site_potential(swept.ecology.profiles[flora_fixtures.OAK["id"]],
                                                 swept.ecology.environment_at(400.0, 64.0))
        self.assertLess(potential["flood_standing"], 0.01)

    def test_the_years_flood_takes_what_stands_on_the_ground_it_reworks(self):
        swept, quiet = self._sim(400.0), self._sim(200.0)
        for sim, east in ((swept, 400.0), (quiet, 200.0)):
            for species_id in (flora_fixtures.OAK["id"], "spec_biomasser_13b"):
                self.assertTrue(sim.ecology.introduce(species_id, east, 64.0, 1.5))
        before = {patch.species_id: patch.abundance for patch in swept.ecology.patches}
        self.assertEqual(set(before), {flora_fixtures.OAK["id"], "spec_biomasser_13b"})
        # A year's largest flood is at least the yearly one: one year in two brings the two-year flood.
        sizes = [swept.ecology.flood_of_year(year) for year in range(400)]
        self.assertGreaterEqual(min(sizes), 1.0)
        self.assertAlmostEqual(float(np.mean(np.asarray(sizes) >= 2.0)), 0.5, delta=0.08)
        self.assertAlmostEqual(float(np.mean(np.asarray(sizes) >= 10.0)), 0.1, delta=0.05)
        self.assertNotEqual(swept.ecology.flood_seed, 0)
        swept.advance_seasons(4)   # the plants take root in the first year ...
        swept.advance_seasons(1)   # ... and the second year's flood finds them
        flood = swept.ecology.last_flood
        self.assertIsNotNone(flood)
        self.assertGreater(flood["lost"][flora_fixtures.OAK["id"]], 0)
        self.assertNotIn(flora_fixtures.OAK["id"], {patch.species_id for patch in swept.ecology.patches})
        notes = [note for note in swept.field_notes if note["kind"] == "flood"]
        self.assertTrue(notes and "The river rose" in notes[-1]["text"] and "English Oak" in notes[-1]["text"])
        # Dated to the spring it came in, and what it took is not said to have failed for want of something.
        self.assertEqual(notes[-1]["when"], "Y2 Spring")
        gone = [note for note in swept.field_notes if note["kind"] == "failure" and "English Oak" in note["text"]]
        self.assertEqual([(note["text"], note["when"]) for note in gone],
                         [("English Oak is gone: the river took its last plants", "Y2 Spring")])
        quiet.advance_seasons(5)
        self.assertIsNone(quiet.ecology.last_flood)
        self.assertIn(flora_fixtures.OAK["id"], {patch.species_id for patch in quiet.ecology.patches})
        self.assertFalse([note for note in quiet.field_notes if note["kind"] == "flood"])


class FloodedRiverGround(water_fixtures.BalancedRiverGround):
    """The balanced river fixture with bars: the first 40 m from the water are reworked every two years."""

    def sample_array(self, key, x, y, default=0.0):
        x = np.asarray(x, dtype=np.float64)
        away = np.clip(np.abs(x - 200.0) - 50.0, 0.0, None)
        if key == "flood_reworking_return_period_years":
            return np.where(away < 40.0, 2.0, FLOOD_NEVER_YEARS)
        return super().sample_array(key, x, y, default)


class SolverFloodTests(unittest.TestCase):
    def test_bars_carry_herbs_and_the_trees_stand_back_from_the_river(self):
        # A tree of the river bank: water standing in its roots does not trouble it, the floods do.
        oak = replace(flora_fixtures.profile_from_entity(flora_fixtures.OAK), root_depth_class="deep",
                      moisture_optimum=0.5, moisture_tolerance=0.45, maturity_days=30.0 * 365.25,
                      waterlogging_tolerance="high")
        sedge = replace(flora_fixtures.profile_from_entity(flora_fixtures.SEDGE), moisture_optimum=0.6,
                        moisture_tolerance=0.5, maturity_days=365.25)
        profiles = {oak.species_id: oak, sedge.species_id: sedge}
        flora = BiomeFlora(flora_fixtures.PLANET, flora_fixtures.CFB)
        for species_id in profiles:
            flora.record(species_id, "dominant")
        bounds = dict(min_x=0.0, max_x=400.0, min_y=0.0, max_y=200.0)
        floras = {flora_fixtures.CFB.key: flora}
        swept = resident_vegetation(FloodedRiverGround(), bounds, profiles, floras, cells=80)
        quiet = resident_vegetation(water_fixtures.BalancedRiverGround(), bounds, profiles, floras, cells=80)
        x = swept.x
        away = np.abs(x - 200.0) - 50.0
        bar, back = (away > 4.0) & (away < 36.0) & (x > 200.0), (away > 44.0) & (away < 70.0) & (x > 200.0)
        # Without floods the oak holds the bank; with them it starts where the river leaves the ground alone.
        self.assertGreater(float(quiet.cover[oak.species_id][bar].mean()), 0.15)   # (a wood has its gaps)
        self.assertLess(float(swept.cover[oak.species_id][bar].max()), 1e-4)
        np.testing.assert_allclose(swept.cover[oak.species_id][back], quiet.cover[oak.species_id][back])
        # The sedge is grown again in a year: it keeps most of the bar.
        self.assertGreater(float(swept.cover[sedge.species_id][bar].mean()), 0.35)
        self.assertGreater(float(swept.cover[sedge.species_id][bar].mean()),
                           0.55 * float(np.maximum(quiet.cover[sedge.species_id][bar], 1e-9).mean()))


class CityFloodLayerTests(unittest.TestCase):
    def setUp(self):
        pygame.init()

    def _city_map(self, region):
        from simulations.city import city_site
        from simulations.map.map_simulation import MapSimulation
        from world.simulation_context import SimulationContext

        world = site_fixtures.BlueprintWorld([region, *[dict(entity) for entity in site_fixtures.SPECIES]])
        city = city_site.found_city(world, site_fixtures.REGION_ID, year=2400)
        return MapSimulation(SimulationContext(year=2400, root_entity_id=city["id"], world_model=world))

    def test_a_city_can_be_shown_the_ground_its_river_floods(self):
        from simulations.city.city_floods import FLOOD_TONES, flood_legend, flood_picture
        from simulations.city.city_vegetation import city_bounds

        city_map = self._city_map(_flooded_region())
        self.assertTrue(city_map.has_flood_ground())
        self.assertFalse(city_map.is_flood_ground_visible())
        self.assertEqual(city_map._flood_ground_layers(), [])
        self.assertTrue(city_map.toggle_flood_ground_visibility())
        layers = city_map._flood_ground_layers()
        self.assertEqual([(layer["shape"], layer["name"]) for layer in layers], [("image_rect", "River floods")])
        self.assertTrue(any(item.get("name") == "River floods" for item in city_map._build_layers(2400)))
        # The east of the fixture is flooded every half year, the west every thirty: two tones, none on the water.
        picture = flood_picture(city_map.get_ground_substrate(), city_bounds(city_map.get_root_entity()))
        alpha = pygame.surfarray.array_alpha(picture)
        width = alpha.shape[0]
        self.assertEqual(int(alpha[int(width * 0.9), 5]), FLOOD_TONES[0][1][3])
        self.assertEqual(int(alpha[int(width * 0.4), 5]), FLOOD_TONES[2][1][3])
        self.assertEqual(int(alpha[2, 5]), 0)
        self.assertEqual(len(flood_legend()), len(FLOOD_TONES))
        self.assertTrue(city_map.toggle_flood_ground_visibility())
        self.assertEqual(city_map._flood_ground_layers(), [])

    def test_a_city_whose_ground_tells_no_floods_has_nothing_to_show(self):
        city_map = self._city_map(site_fixtures._region())
        self.assertFalse(city_map.has_flood_ground())
        self.assertFalse(city_map.toggle_flood_ground_visibility())
        self.assertEqual(city_map._flood_ground_layers(), [])


if __name__ == "__main__":
    unittest.main()
