"""How wet a place is for a plant: the year's water balance, what the generator hands it, and who reads it."""
import os
import unittest
from dataclasses import replace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import numpy as np
import pygame

from simulations.biosphere import terrain_site
from simulations.biosphere import water_balance as wb
from simulations.biosphere.biomes import WETLAND, biome_at, biome_grid, classify
from simulations.biosphere.biosphere_simulation import BiosphereSimulation
from simulations.biosphere.ecology import (
    REFERENCE_ROOT_DEPTH_M, moisture_response, profile_from_entity, rootable_depth_of, rooting_depth_m, water_ground,
    waterlogging_limits,
)
from simulations.biosphere.flora import BiomeFlora
from simulations.biosphere.potential_vegetation import resident_vegetation
from simulations.world_gen import alluvial_channels as ac
from simulations.world_gen import fine_hydrology as fh
from simulations.world_gen import floodplain_relics as fr
from simulations.world_gen.regolith_soils import (
    AWC_COARSE_MM_PER_M, AWC_LOAM_MM_PER_M, DRAINAGE_BAR_MM_PER_DAY, FLOODPLAIN_ROOTABLE_M, derive_regolith_soil_model,
    soil_drainage_rate, soil_water_properties,
)
from tests import test_biome_flora as flora_fixtures
from tests import test_biosphere_terrain_site as site_fixtures
from tests import test_fine_scale_ground as ground_fixtures


def _wetness(rain, demand, root_depth_m=0.4, development=1.0, **ground):
    return wb.point_wetness(wb.point_ground(rain, demand, **ground), root_depth_m, development)


class WaterBalanceTests(unittest.TestCase):
    def test_climates_come_out_in_their_order(self):
        rain_forest = _wetness(2600.0, 1400.0, coldest_month_k=298.0, warmest_month_k=300.0)
        oceanic = _wetness(650.0, 650.0, coldest_month_k=278.0, warmest_month_k=291.0)
        mediterranean = _wetness(550.0, 1200.0, driest_month_mm=5.0, wettest_month_mm=95.0, summer_fraction=0.2,
                                 coldest_month_k=282.0, warmest_month_k=298.0)
        steppe = _wetness(350.0, 1100.0, coldest_month_k=265.0, warmest_month_k=296.0)
        desert = _wetness(60.0, 2200.0, coldest_month_k=285.0, warmest_month_k=308.0)
        self.assertGreater(rain_forest, oceanic)
        self.assertGreater(oceanic, mediterranean)
        self.assertGreater(mediterranean, steppe - 0.03)
        self.assertGreater(steppe, desert + 0.1)
        # On the scale species' preferences are authored on: fresh, mesic, dry, very dry.
        self.assertAlmostEqual(rain_forest, 0.50, delta=0.02)
        self.assertGreater(oceanic, 0.40)
        self.assertLess(mediterranean, 0.32)
        self.assertLess(desert, 0.08)

    def test_the_same_rain_is_worth_less_on_sand_thin_soil_raw_ground_and_a_sunny_slope(self):
        climate = dict(coldest_month_k=276.0, warmest_month_k=293.0)
        loam = _wetness(650.0, 800.0, available_water_mm_per_m=190.0, **climate)
        sand = _wetness(650.0, 800.0, available_water_mm_per_m=70.0, **climate)
        thin = _wetness(650.0, 800.0, available_water_mm_per_m=190.0, rootable_depth_m=0.05, **climate)
        raw = _wetness(650.0, 800.0, development=0.0, available_water_mm_per_m=190.0, **climate)
        sunny = _wetness(650.0, 800.0, available_water_mm_per_m=190.0, exposure=1.0, **climate)
        shaded = _wetness(650.0, 800.0, available_water_mm_per_m=190.0, exposure=0.6, **climate)
        self.assertGreater(loam, sand + 0.02)
        self.assertGreater(sand, thin + 0.05)
        self.assertGreater(loam, raw + 0.02)
        self.assertGreater(shaded, sunny + 0.02)
        # Deeper roots draw on more soil, as long as there is soil to draw on.
        self.assertGreater(_wetness(650.0, 800.0, 2.0, available_water_mm_per_m=70.0, **climate), sand)
        self.assertAlmostEqual(_wetness(650.0, 800.0, 2.0, available_water_mm_per_m=190.0, rootable_depth_m=0.05, **climate), thin)

    def test_run_on_fills_the_soil_and_ground_shed_from_is_drier(self):
        dry = dict(coldest_month_k=272.0, warmest_month_k=297.0)
        level = _wetness(450.0, 1300.0, **dry)
        hollow = _wetness(450.0, 1300.0, lateral_mm=900.0, **dry)
        nose = _wetness(450.0, 1300.0, lateral_mm=-120.0, **dry)
        self.assertGreater(hollow, level + 0.1)
        self.assertLess(nose, level)
        # Water passing through makes ground fresh, not wet: that takes a water table.
        self.assertLessEqual(_wetness(450.0, 1300.0, lateral_mm=50000.0, **dry), 0.5 + 1e-9)

    def test_ground_water_wets_what_its_rise_or_the_roots_reach(self):
        dry = dict(coldest_month_k=272.0, warmest_month_k=297.0)
        upland = _wetness(450.0, 1300.0, **dry)
        # Loam lifts water about a metre: a table 60 cm down keeps a herb's ground moist, one a metre down fresh.
        loam = [_wetness(450.0, 1300.0, depth, capillary_rise_m=1.0, water_table_depth_m=0.6, **dry) for depth in (0.4, 2.0)]
        self.assertGreater(loam[0], 0.55)
        self.assertGreaterEqual(loam[1], loam[0])
        deeper = _wetness(450.0, 1300.0, capillary_rise_m=1.0, water_table_depth_m=1.0, **dry)
        self.assertGreater(deeper, upland + 0.15)
        self.assertLess(deeper, loam[0])
        # Coarse sand lifts it a hand: the herb on the bar stays dry, the tree rooted to the table does not.
        herb, tree = [_wetness(450.0, 1300.0, depth, available_water_mm_per_m=70.0, capillary_rise_m=0.1,
                               water_table_depth_m=1.0, **dry) for depth in (0.4, 2.0)]
        self.assertLess(herb, upland + 0.02)
        self.assertGreater(tree, herb + 0.15)
        # Nearer the surface it is wet for everything; out of reach it changes nothing.
        self.assertGreater(_wetness(450.0, 1300.0, capillary_rise_m=1.0, water_table_depth_m=0.2, **dry), 0.7)
        self.assertAlmostEqual(_wetness(450.0, 1300.0, 2.0, capillary_rise_m=1.0, water_table_depth_m=30.0, **dry),
                               _wetness(450.0, 1300.0, 2.0, **dry))

    def test_arrays_and_single_places_agree(self):
        shape = (3, 4)
        rng = np.random.default_rng(5)
        rain = rng.uniform(100.0, 1800.0, shape)
        demand = rng.uniform(400.0, 2000.0, shape)
        table = rng.uniform(0.0, 4.0, shape)
        sand = rng.uniform(60.0, 190.0, shape)
        rise = rng.uniform(0.1, 2.0, shape)
        lateral = rng.uniform(-100.0, 600.0, shape)
        rootable = rng.uniform(0.05, 3.0, shape)
        drainage = 10.0 ** rng.uniform(-1.0, 2.0, shape)
        ground = {
            "rain": wb.monthly_rain(rain, rain * 0.03, rain * 0.14, np.full(shape, 0.7)),
            "demand": wb.monthly_demand(demand, np.full(shape, 270.0), np.full(shape, 296.0), np.full(shape, 0.8)),
            "available_water_mm_per_m": sand, "rootable_depth_m": rootable, "lateral_mm": lateral,
            "capillary_rise_m": rise, "water_table_depth_m": table, "drainage_mm_per_day": drainage,
        }
        for depth, development in ((0.4, 1.0), (2.0, 0.3)):
            whole = wb.plant_wetness(ground, depth, development)
            for row in range(shape[0]):
                for column in range(shape[1]):
                    at = (row, column)
                    point = wb.point_ground(
                        rain[at], demand[at], driest_month_mm=rain[at] * 0.03, wettest_month_mm=rain[at] * 0.14,
                        summer_fraction=0.7, coldest_month_k=270.0, warmest_month_k=296.0, exposure=0.8,
                        available_water_mm_per_m=sand[at], rootable_depth_m=rootable[at], lateral_mm=lateral[at],
                        capillary_rise_m=rise[at], water_table_depth_m=table[at], drainage_mm_per_day=drainage[at])
                    self.assertAlmostEqual(float(whole[at]), wb.point_wetness(point, depth, development), places=9)
        self.assertAlmostEqual(float(ground["rain"].sum(axis=0)[0, 0]), rain[0, 0], places=6)
        self.assertAlmostEqual(float(ground["demand"].sum(axis=0)[0, 0]), demand[0, 0] * (0.35 + 0.65 * 0.8), places=6)


class WaterloggingTests(unittest.TestCase):
    OCEANIC = dict(driest_month_mm=90.0, wettest_month_mm=200.0, summer_fraction=0.4, coldest_month_k=287.5, warmest_month_k=295.0)

    def test_water_that_cannot_drain_stands_in_the_soil(self):
        free = _wetness(1730.0, 1300.0, **self.OCEANIC)
        loam = _wetness(1730.0, 1300.0, drainage_mm_per_day=30.0, **self.OCEANIC)
        clay = _wetness(1730.0, 1300.0, drainage_mm_per_day=1.0, **self.OCEANIC)
        heavy = _wetness(1730.0, 1300.0, drainage_mm_per_day=0.3, **self.OCEANIC)
        # Rain alone makes ground fresh at most; a subsoil that passes what arrives changes nothing.
        self.assertLessEqual(free, wb.FRESH_WETNESS)
        self.assertEqual(loam, free)
        self.assertGreater(clay, 0.65)
        self.assertGreaterEqual(heavy, clay)
        self.assertLessEqual(heavy, wb.SODDEN_WETNESS)
        # It takes a wet season: the same clay under rain that never outruns demand stays as dry as a sand.
        dry = dict(driest_month_mm=41.0, wettest_month_mm=128.0, summer_fraction=0.68, coldest_month_k=289.0, warmest_month_k=296.0)
        self.assertEqual(_wetness(933.0, 1944.0, drainage_mm_per_day=0.3, **dry), _wetness(933.0, 1944.0, **dry))
        # A hollow that gathers water waterlogs on ground that would otherwise drain.
        self.assertGreater(_wetness(1730.0, 1300.0, drainage_mm_per_day=5.0, lateral_mm=3000.0, **self.OCEANIC),
                           _wetness(1730.0, 1300.0, drainage_mm_per_day=5.0, **self.OCEANIC) + 0.1)
        np.testing.assert_allclose(wb.waterlogged_wetness([0.0, 1.0]), [0.0, wb.SODDEN_WETNESS])
        # The water stands on the subsoil, whoever roots there: a tree's deep roots do not drink a sodden
        # soil dry and read drier than the herb beside it.
        for drainage in (0.3, 1.0, 3.0):
            for run_on in (0.0, 1500.0):
                herb = _wetness(1730.0, 1300.0, 0.35, drainage_mm_per_day=drainage, lateral_mm=run_on, **self.OCEANIC)
                tree = _wetness(1730.0, 1300.0, 2.0, drainage_mm_per_day=drainage, lateral_mm=run_on, **self.OCEANIC)
                self.assertGreaterEqual(tree, herb - 1e-9)
        self.assertTrue(0.55 < float(wb.waterlogged_wetness(1.0 / 12.0)) < 0.62)   # a month: moist
        self.assertTrue(0.72 < float(wb.waterlogged_wetness(0.5)) < 0.80)          # half the year: wet

    def test_more_water_than_a_plant_likes_does_no_harm_until_it_stands_in_its_roots(self):
        pine = profile_from_entity({"id": "spec_test_pine", "plant_growth_form": "tree", "moisture_preference": "dry",
                                    "waterlogging_tolerance": "low"})
        self.assertEqual((pine.waterlogging_tolerance, pine.waterlogging_source), ("low", "authored waterlogging_tolerance"))
        wetness = np.array([0.05, 0.20, 0.42, 0.50, 0.55, 0.615, 0.68, 0.90])
        response = moisture_response(pine, wetness)
        # Short of water below its optimum; at home from there to fresh ground and a little beyond; gone where
        # the water stands 45 cm under it.
        self.assertLess(float(response[0]), 1.0)
        np.testing.assert_allclose(response[1:5], 1.0)
        self.assertAlmostEqual(float(response[5]), 0.5, delta=0.01)
        np.testing.assert_allclose(response[6:], 0.0, atol=1e-12)
        self.assertEqual(waterlogging_limits(pine), (0.55, 0.68))
        oak = profile_from_entity({"id": "spec_test_oak", "plant_growth_form": "tree", "moisture_preference": "mesic",
                                   "waterlogging_tolerance": "medium"})
        self.assertEqual(waterlogging_limits(oak), (0.62, 0.80))
        self.assertGreater(float(moisture_response(oak, 0.68)), 0.6)
        alder = profile_from_entity({"id": "spec_test_alder", "plant_growth_form": "tree", "moisture_preference": "moist",
                                     "waterlogging_tolerance": "high"})
        self.assertEqual(float(moisture_response(alder, 0.90)), 1.0)
        # Where none is authored, the preference stands in: plants of wet ground bear it, of moist ground some.
        guessed = {preference: profile_from_entity({"id": f"spec_test_{preference}", "plant_growth_form": "forb",
                                                    "moisture_preference": preference})
                   for preference in ("dry", "mesic", "moist", "wet")}
        self.assertEqual([guessed[name].waterlogging_tolerance for name in ("dry", "mesic", "moist", "wet")],
                         ["low", "low", "medium", "high"])
        self.assertEqual(guessed["wet"].waterlogging_source, "moisture preference default")
        lily = profile_from_entity({"id": "spec_test_lily", "plant_growth_form": "aquatic", "moisture_preference": "aquatic"})
        self.assertEqual((lily.waterlogging_tolerance, float(moisture_response(lily, 1.0))), ("high", 1.0))
        # A plant of wet ground still wants for water on merely fresh ground.
        self.assertLess(float(moisture_response(guessed["wet"], 0.50)), 0.5)
        # A species is at least at home where it grows best, whatever its class says.
        odd = replace(guessed["wet"], waterlogging_tolerance="low")
        self.assertEqual(float(moisture_response(odd, odd.moisture_optimum)), 1.0)

    def test_the_soil_tells_what_its_subsoil_lets_through(self):
        rates = soil_drainage_rate(np.array([0.0, 0.2, 0.4, 0.6, 0.8]))
        np.testing.assert_allclose(rates, [1000.0, 100.0, 10.0, 1.0, 0.1], rtol=1e-9)
        parent, parent_size = ground_fixtures._river_parent()
        residual, record, frame, elevation = ground_fixtures._relics(parent, parent_size, origin_m=(300.0, 80.0))
        heightmap, water, parent_soil = ground_fixtures.FineSoilTest()._models(
            elevation + residual, level=5, spacing=1.0, landforms=[record], frame=frame)
        heightmap["refinement_detail_band"] = {"parent_sample_spacing_m": 8.0}
        soil = derive_regolith_soil_model({}, heightmap, water, {}, {}, parent_soil_model=parent_soil,
                                          parent_window=(0.2, 0.4, 0.2, 0.4))["grid"]
        fields = fr.heightmap_relic_fields(heightmap)
        rate = np.asarray(soil["drainage_rate_rows_mm_per_day"])
        floors, bars = fields["floor"] > 0.8, (fields["floor"] < 0.05) & (fields["fresh"] > 0.9)
        # A silted channel is a plug; a fresh bar is clean sand.
        self.assertLess(float(np.median(rate[floors])), 5.0)
        if bars.any():
            self.assertGreater(float(np.median(rate[bars])), 0.5 * DRAINAGE_BAR_MM_PER_DAY)
        self.assertGreater(float(np.median(rate[fields["floor"] < 0.05])), 20.0 * float(np.median(rate[floors])))


class GeneratorWaterTests(unittest.TestCase):
    def test_soil_holds_and_lifts_water_by_its_texture(self):
        available, rise = soil_water_properties(np.array([0.0, 0.2, 0.4, 0.6, 1.0]))
        self.assertEqual(float(available[0]), AWC_COARSE_MM_PER_M)
        self.assertEqual(float(available[2]), AWC_LOAM_MM_PER_M)
        self.assertLess(float(available[4]), AWC_LOAM_MM_PER_M)  # a heavy clay holds much of its water too tightly
        self.assertTrue(np.all(np.diff(rise) > 0.0))
        self.assertAlmostEqual(float(rise[0]), 0.1)
        self.assertAlmostEqual(float(rise[4]), 2.0)

    def test_a_floodplain_is_rootable_sediment_fine_in_its_fills_and_coarse_on_its_bars(self):
        parent, parent_size = ground_fixtures._river_parent()
        residual, record, frame, elevation = ground_fixtures._relics(parent, parent_size, origin_m=(300.0, 80.0))
        heightmap, water, parent_soil = ground_fixtures.FineSoilTest()._models(
            elevation + residual, level=5, spacing=1.0, landforms=[record], frame=frame)
        heightmap["refinement_detail_band"] = {"parent_sample_spacing_m": 8.0}
        soil = derive_regolith_soil_model({}, heightmap, water, {}, {}, parent_soil_model=parent_soil,
                                          parent_window=(0.2, 0.4, 0.2, 0.4))["grid"]
        fields = fr.heightmap_relic_fields(heightmap)
        floors, bars = fields["floor"] > 0.8, fields["floor"] < 0.05
        available = np.asarray(soil["available_water_capacity_rows_mm_per_m"])
        rise = np.asarray(soil["capillary_rise_rows_m"])
        rootable, depth = np.asarray(soil["rootable_depth_m_rows"]), np.asarray(soil["soil_depth_m_rows"])
        self.assertGreater(float(available[floors].mean()), float(available[bars].mean()) + 80.0)
        self.assertGreater(float(rise[floors].mean()), float(rise[bars].mean()) + 1.0)
        self.assertTrue(np.all(rootable >= depth - 1e-6))
        self.assertAlmostEqual(float(rootable[fields["floodplain"] > 0.99].min()), FLOODPLAIN_ROOTABLE_M, places=2)
        # A tile one level down takes its parent's figures instead of working them out again.
        parent_rows = lambda value: [[value] * 6 for _ in range(6)]  # noqa: E731
        parent_soil["grid"].update(available_water_capacity_rows_mm_per_m=parent_rows(123.0),
                                   capillary_rise_rows_m=parent_rows(0.7), rootable_depth_m_rows=parent_rows(2.2))
        flat = np.full((41, 41), 100.0) + 0.01 * np.arange(41)[None, :]
        heightmap, water, _soil = ground_fixtures.FineSoilTest()._models(flat)
        child = derive_regolith_soil_model({}, heightmap, water, {}, {}, parent_soil_model=parent_soil,
                                           parent_window=(0.2, 0.4, 0.2, 0.4))["grid"]
        self.assertAlmostEqual(float(np.mean(child["available_water_capacity_rows_mm_per_m"])), 123.0, delta=0.5)
        self.assertAlmostEqual(float(np.mean(child["capillary_rise_rows_m"])), 0.7, delta=0.01)
        self.assertAlmostEqual(float(np.mean(child["rootable_depth_m_rows"])), 2.2, delta=0.05)

    def test_the_water_table_stands_at_the_waters_level_and_rises_between_with_recharge(self):
        shape = (40, 121)
        ground = np.full(shape, 20.0)
        ground[:, 50:70] = 11.2  # a low flat midway
        water = np.zeros(shape, dtype=bool)
        water[:, :3] = water[:, -3:] = True
        surface = np.where(np.arange(shape[1])[None, :] < 60, 10.0, 12.0) * np.ones(shape)
        still = fh.regional_water_table(water, surface, ground, 0.0, 10.0, 10.0)
        fed = fh.regional_water_table(water, surface, ground, 300.0, 10.0, 10.0)
        # Without recharge a straight fall from the higher water to the lower.
        self.assertAlmostEqual(float(still[20, 60]), 11.0, delta=0.15)
        self.assertAlmostEqual(float(still[20, 30]), 10.5, delta=0.15)
        self.assertTrue(np.all(np.abs(np.diff(still[20])) < 0.05))
        # Recharge piles up between the waters, and where the table meets the ground it seeps out.
        self.assertGreater(float(fed[20, 30]), float(still[20, 30]) + 0.5)
        self.assertTrue(np.all(fed <= ground + 1e-9))
        self.assertAlmostEqual(float(fed[20, 60]), 11.2, delta=0.01)
        self.assertIsNone(fh.regional_water_table(np.zeros(shape, dtype=bool), surface, ground, 300.0, 10.0, 10.0))

    def test_hollows_and_wet_climates_bring_the_table_up(self):
        index = np.array([[4.0, 6.0, 8.0, 10.0, 12.0]] * 9)
        dry = fh.hillslope_water_table_depth(index, 10.0)[4]
        humid = fh.hillslope_water_table_depth(index, 300.0)[4]
        self.assertTrue(np.all(np.diff(dry) <= 0.0) and np.all(np.diff(humid) <= 0.0))
        self.assertTrue(np.all(humid <= dry))
        self.assertGreater(float(dry[1]), 5.0)   # a plain slope in a dry climate: out of reach
        self.assertEqual(float(humid[4]), 0.0)   # the floor of a hollow in a wet one: at the surface
        self.assertLess(float(fh.hillslope_water_table_depth(index, 0.0).max()), fh.WATER_TABLE_UNKNOWN_M + 1e-9)

    def test_a_site_hands_over_the_depth_to_its_water_table_and_its_run_on(self):
        hollow, _elevation = ground_fixtures.FineHydrologyTest()._hollow()
        runoff = fh.refine_surface_hydrology(hollow, ground_fixtures._water_cycle())["runoff_grid"]
        lateral = np.asarray(runoff["lateral_water_rows_mm"])
        table = np.asarray(runoff["water_table_depth_m_rows"])
        centre = lateral.shape[1] // 2
        self.assertEqual(table.shape, lateral.shape)
        self.assertGreater(float(lateral[40:70, centre - 1:centre + 2].mean()), 500.0)
        # Ordinary ground is at nought (its surplus is the climate's runoff and recharge, shed by whoever keeps
        # its balance); a nose receives a little less than that, never a large part of its rain.
        self.assertAlmostEqual(float(np.median(lateral)), 0.0, delta=1.0)
        nose = float(lateral[40:70, 5:12].mean())
        self.assertLessEqual(nose, 0.0)
        self.assertGreater(nose, -0.1 * 900.0)
        self.assertLess(float(table[40:70, centre - 1:centre + 2].mean()), float(table[40:70, 5:12].mean()) - 1.0)

        # Beside a carved river: the low bank has its water within reach, the terrace three metres up has not.
        parent, parent_size = ground_fixtures._river_parent()
        shape = (201, 241)
        frame = ground_fixtures._child_frame(parent_size, (600.0, 460.0), (240.0, 200.0), shape)
        record = parent["heightmap_model"]["regional_landforms"]["landforms"][0]
        heightmap = dict(frame, map_detail_level=5, sea_level_m=None, regional_landforms={
            "landforms": [dict(record, inherited_reaches=record["reaches"], reaches=[])]})
        fields = ac.channel_fields(record["reaches"], shape, dx=frame["sample_spacing_x_m"], dy=frame["sample_spacing_y_m"],
                                   to_local=ac.local_frame(frame, shape)[2])
        level = np.where(np.isfinite(fields["stage_m"]), fields["stage_m"], 296.0) + 0.6
        channel_row = int(np.mean(np.nonzero(fields["in_channel"])[0]))
        terrace = np.where(np.arange(shape[0])[:, None] < channel_row, 3.0, 0.0) * np.ones((1, shape[1]))
        heightmap["sample_grid"] = {"rows": np.where(fields["in_channel"], fields["bank"] - fields["depth"], level + terrace).tolist()}
        trunk = {"id": "trunk", "estimated_discharge_m3_s": 15.0, "flow_regime": "intermittent",
                 "points": [{"x": 0.0, "y": 0.5}, {"x": 1.0, "y": 0.5}]}
        depths = {}
        for recharge in (10.0, 600.0):
            water = fh.refine_surface_hydrology(heightmap, ground_fixtures._water_cycle(
                [trunk], runoff_mm=24.0, precipitation_mm=570.0, evaporation_mm=2300.0, recharge_mm=recharge))
            table = np.asarray(water["runoff_grid"]["water_table_depth_m_rows"])
            presence = np.asarray(water["surface_water_grid"]["water_presence_rows"])
            margin = np.maximum(fields["distance_m"] - 0.5 * fields["width_m"], 0.0)
            beside = (margin > 2.0) & (margin < 12.0) & ~presence
            self.assertEqual(float(table[presence].max()), 0.0)
            depths[recharge] = (float(table[beside & (terrace == 0.0)].mean()), float(table[beside & (terrace > 0.0)].mean()))
        self.assertLess(depths[10.0][0], 1.0)
        self.assertGreater(depths[10.0][1], 3.0)
        self.assertLess(depths[600.0][1], depths[10.0][1])


class FinerTileTests(unittest.TestCase):
    """A tile cut out of a Site takes the Site's water table and its run-on total: it cannot see what sets them."""

    def _tiles(self):
        size, spacing = 81, 8.0
        x = np.arange(size) * spacing
        # Ground rising eastward out of the sea, with a broad swell across it.
        ground = 0.02 * x[None, :] - 1.0 + 0.4 * np.sin(np.arange(size)[:, None] * spacing / 90.0)
        parent = {"map_detail_level": 4, "sample_grid": {"rows": ground.tolist()}, "sample_spacing_x_m": spacing,
                  "sample_spacing_y_m": spacing, "sea_level_m": 0.0,
                  "source_uv_bounds": {"min_u": 0.1, "max_u": 0.2, "min_v": 0.5, "max_v": 0.6}}
        parent_water = fh.refine_surface_hydrology(parent, ground_fixtures._water_cycle())
        # The middle half of it, four times as fine, with ripples the parent could not hold.
        fine = 161
        fx = 160.0 + np.arange(fine) * 2.0
        fy = 160.0 + np.arange(fine) * 2.0
        ripple = 0.25 * np.sin(fx[None, :] / 5.0) * np.cos(fy[:, None] / 7.0)
        smooth = 0.02 * fx[None, :] - 1.0 + 0.4 * np.sin(fy[:, None] / 90.0)
        child = {"map_detail_level": 5, "sample_grid": {"rows": (smooth + ripple).tolist()}, "sample_spacing_x_m": 2.0,
                 "sample_spacing_y_m": 2.0, "sea_level_m": 0.0,
                 "source_uv_bounds": {"min_u": 0.125, "max_u": 0.175, "min_v": 0.525, "max_v": 0.575}}
        return parent, parent_water, child, ripple

    def test_a_finer_tile_measures_its_own_ground_against_its_parents_table(self):
        parent, parent_water, child, ripple = self._tiles()
        shape = ripple.shape
        self.assertEqual(parent_water["runoff_grid"]["water_table_source"], "own")
        surface = fh.parent_water_table(child, parent, parent_water, shape)
        self.assertEqual(surface.shape, shape)
        self.assertLess(float(np.abs(np.diff(surface, axis=1)).max()), 0.05)   # a table is smooth: none of the ripples
        refined = fh.refine_surface_hydrology(child, ground_fixtures._water_cycle(), parent=(parent, parent_water))
        self.assertEqual(refined["runoff_grid"]["water_table_source"], "parent")
        depth = np.asarray(refined["runoff_grid"]["water_table_depth_m_rows"])
        ground = np.asarray(child["sample_grid"]["rows"])
        np.testing.assert_allclose(depth, np.clip(ground - surface, 0.0, None), atol=0.006)
        # The ripples are all the child adds: a hollow is that much nearer the water, a crest further, the mean kept.
        wanted = np.asarray(fh._over_child(child, parent, np.asarray(parent_water["runoff_grid"]["water_table_depth_m_rows"]), shape))
        dry = depth > 0.3
        self.assertAlmostEqual(float((depth - wanted)[dry].mean()), 0.0, delta=0.03)
        self.assertGreater(float(np.corrcoef((depth - wanted)[dry], ripple[dry])[0, 1]), 0.9)
        # Left to itself the same tile sees no sea and reckons another table altogether.
        alone = np.asarray(fh.refine_surface_hydrology(child, ground_fixtures._water_cycle())["runoff_grid"]["water_table_depth_m_rows"])
        self.assertGreater(float(np.abs(alone - wanted)[dry].mean()), 10.0 * float(np.abs(depth - wanted)[dry].mean()))
        # A parent that tells no table (a map coarser than a Site, or none at all) leaves the tile to itself.
        self.assertIsNone(fh.parent_water_table(child, parent, {"runoff_grid": {}}, shape))
        self.assertIsNone(fh.parent_water_table(child, None, parent_water, shape))
        self.assertIsNone(fh.parent_water_table(dict(child, source_uv_bounds=None), parent, parent_water, shape))

    def test_a_finer_tile_moves_as_much_water_as_its_parent_says(self):
        parent, parent_water, child, ripple = self._tiles()
        shape = ripple.shape
        gathered = fh.parent_run_on(child, parent, parent_water, shape)
        with_parent = fh.refine_surface_hydrology(child, ground_fixtures._water_cycle(), parent=(parent, parent_water))["runoff_grid"]
        alone = fh.refine_surface_hydrology(child, ground_fixtures._water_cycle())["runoff_grid"]
        self.assertEqual((with_parent["run_on_total_source"], alone["run_on_total_source"]), ("parent", "own"))
        mine, own = np.asarray(with_parent["lateral_water_rows_mm"]), np.asarray(alone["lateral_water_rows_mm"])
        self.assertAlmostEqual(float(mine.sum()), float(gathered.sum()), delta=0.02 * abs(float(gathered.sum())) + shape[0] * shape[1] * 0.06)
        self.assertNotAlmostEqual(float(own.sum()), float(gathered.sum()), delta=0.2 * abs(float(gathered.sum())))
        # The same pattern, another total: where the water goes is the tile's to say.
        self.assertGreater(float(np.corrcoef(mine.ravel(), own.ravel())[0, 1]), 0.999)


def _balanced_region(table_depth_m=2.0, **soil):
    """The terrain-site fixture with what the water balance reads: a dry warm climate over ground water."""
    region = site_fixtures._region(coldest_k=276.15, warmest_k=298.15)
    climate = region["water_cycle_model"]["climate_grid"]
    grid = site_fixtures._grid
    climate.update(
        annual_precipitation_rows_mm=grid(lambda *_: 480.0), annual_potential_evaporation_rows_mm=grid(lambda *_: 1300.0),
        driest_month_precipitation_rows_mm=grid(lambda *_: 25.0), wettest_month_precipitation_rows_mm=grid(lambda *_: 60.0),
        summer_precipitation_fraction_rows=grid(lambda *_: 0.6),
    )
    region["water_cycle_model"]["runoff_grid"].update(
        water_table_depth_m_rows=grid(lambda *_: table_depth_m), lateral_water_rows_mm=grid(lambda *_: 0.0))
    region["regolith_soil_model"]["grid"].update(
        soil_depth_m_rows=grid(lambda *_: soil.get("soil_depth_m", 0.6)),
        available_water_capacity_rows_mm_per_m=grid(lambda *_: soil.get("available_water", 170.0)),
        capillary_rise_rows_m=grid(lambda *_: soil.get("capillary_rise_m", 0.3)),
        rootable_depth_m_rows=grid(lambda *_: soil.get("rootable_depth_m", 3.0)),
        drainage_rate_rows_mm_per_day=grid(lambda *_: soil.get("drainage_mm_per_day", 100.0)),
    )
    return region


class BiosphereReadsTheBalanceTests(unittest.TestCase):
    def setUp(self):
        pygame.init()

    def _sim(self, **ground):
        world = site_fixtures.BlueprintWorld([_balanced_region(**ground), *[dict(entity) for entity in site_fixtures.SPECIES]])
        site = terrain_site.found_biosphere_site(world, site_fixtures.REGION_ID, site_fixtures._region_point(400.0, 64.0), year=2400)
        return BiosphereSimulation(world, {"patch_location_id": site["id"], "year": 2400})

    def _enrich(self, sim, organic):
        for name, value in (("organic_matter_rows", organic), ("available_nitrogen_rows", 4.0), ("available_phosphorus_rows", 1.0)):
            setattr(sim.soil, name, [[value] * sim.soil.columns for _ in range(sim.soil.rows)])
        sim.soil.revision += 1

    def test_the_ground_hands_the_kernel_everything_the_balance_reads(self):
        sim = self._sim()
        abiotic = sim.substrate.environment_at(400.0, 64.0)
        for key, value in (("annual_potential_evaporation_mm", 1300.0), ("driest_month_precipitation_mm", 25.0),
                           ("wettest_month_precipitation_mm", 60.0), ("summer_precipitation_fraction", 0.6),
                           ("available_water_mm_per_m", 170.0), ("capillary_rise_m", 0.3), ("rootable_depth_m", 3.0),
                           ("water_table_depth_m", 2.0), ("lateral_water_mm", 0.0)):
            self.assertAlmostEqual(abiotic[key], value, places=6, msg=key)
        balance = water_ground(abiotic)
        self.assertAlmostEqual(sum(balance["rain"]), 480.0, places=6)
        self.assertEqual((balance["water_table_depth_m"], balance["capillary_rise_m"], balance["rootable_depth_m"]), (2.0, 0.3, 3.0))
        self.assertEqual((abiotic["drainage_mm_per_day"], balance["drainage_mm_per_day"]), (100.0, 100.0))
        self.assertEqual(rootable_depth_of(abiotic), 3.0)  # the loose ground, not the 0.6 m of soil on it
        # Ground that does not tell the demand of the air keeps the map's wetness.
        plain = dict(abiotic)
        plain.pop("annual_potential_evaporation_mm")
        self.assertIsNone(water_ground(plain))
        self.assertEqual(rootable_depth_of({"soil_depth_m": 0.6}), 0.6)

    def test_wetness_is_the_plants_own_and_a_built_soil_holds_more_of_the_rain(self):
        sim = self._sim()
        raw = sim.ecology.environment_at(400.0, 64.0)
        self.assertIn("water_balance", raw)
        self.assertAlmostEqual(raw["soil_moisture"], wb.point_wetness(raw["water_balance"], REFERENCE_ROOT_DEPTH_M, 0.0), places=9)
        self.assertEqual(raw["soil_moisture"], raw["abiotic_soil_moisture"])
        self._enrich(sim, 3.0)
        built = sim.ecology.environment_at(400.0, 64.0)
        self.assertGreater(built["soil_moisture"], raw["soil_moisture"] + 0.015)
        self.assertAlmostEqual(built["moisture_retention_bonus"], built["soil_moisture"] - built["abiotic_soil_moisture"], places=9)

        grass = sim.ecology.profiles["spec_lolium_perenne"]
        tree = replace(grass, species_id="spec_test_tree", growth_form="tree", root_depth_class="deep", max_root_depth=None)
        self.assertEqual((rooting_depth_m(grass), rooting_depth_m(tree)), (0.4, 2.0))
        shallow = sim.ecology.suitability_factors(grass, built)
        deep = sim.ecology.suitability_factors(tree, built)
        # The table lies 2 m down under ground that lifts water 30 cm: within the tree's roots, beyond the grass's.
        self.assertAlmostEqual(shallow["wetness"], built["soil_moisture"], places=9)
        self.assertGreater(deep["wetness"], shallow["wetness"] + 0.1)
        potential = sim.ecology.site_potential(tree, built)
        self.assertGreater(potential["open"], sim.ecology.site_potential(grass, built)["open"])
        self.assertEqual(potential["rooting"], 1.0)

    def test_a_wetland_is_ground_whose_water_table_is_at_the_surface(self):
        self.assertEqual(classify("Cfb", "Temperate Oceanic", water_table_depth_m=0.2).water, WETLAND)
        self.assertEqual(classify("Cfb", "Temperate Oceanic", water_table_depth_m=0.5).water, "")
        # Where the map tells the depth of its table, that decides, not the wetness index.
        self.assertEqual(classify("Cfb", "Temperate Oceanic", wetness=0.9, water_table_depth_m=2.0).water, "")
        self.assertEqual(classify("Cfb", "Temperate Oceanic", wetness=0.9).water, WETLAND)
        wet, dry = self._sim(table_depth_m=0.1), self._sim(table_depth_m=2.0)
        self.assertEqual(biome_at(wet.substrate, 400.0, 64.0).water, WETLAND)
        self.assertEqual(biome_at(dry.substrate, 400.0, 64.0).water, "")
        index, biomes = biome_grid(wet.substrate, np.array([[400.0]]), np.array([[64.0]]))
        self.assertEqual(biomes[int(index[0, 0])].water, WETLAND)

    def test_the_catalogue_tells_waterlogging_from_thirst(self):
        wet = self._sim(table_depth_m=0.1, capillary_rise_m=1.0)
        self._enrich(wet, 3.0)
        grass = wet.ecology.profiles["spec_lolium_perenne"]
        intolerant = replace(grass, species_id="spec_test_dryland", moisture_optimum=0.2, waterlogging_tolerance="low")
        wet.ecology.profiles[intolerant.species_id] = intolerant
        factors = wet.ecology.suitability_factors(intolerant, wet.ecology.environment_at(400.0, 64.0))
        self.assertEqual((factors["suitability"], factors["limiting"]), (0.0, "moisture"))
        reason = wet._describe_limit(intolerant, "moisture", None, dict(soil_moisture=factors["wetness"]))
        self.assertEqual(reason, f"waterlogged (wetness {factors['wetness']:.2f}, its roots bear 0.55)")
        # The same plant on ground whose water lies deep: more rain than it likes is no harm to it.
        fresh = wet._describe_limit(intolerant, "moisture", None, dict(soil_moisture=0.1))
        self.assertEqual(fresh, "too dry (wetness 0.10, best near 0.20)")
        self.assertEqual(float(moisture_response(intolerant, 0.5)), 1.0)

    def test_a_table_near_the_surface_makes_wet_ground_and_thin_soil_dry_ground(self):
        wet = self._sim(table_depth_m=0.1, capillary_rise_m=1.0)
        self.assertGreater(wet.ecology.environment_at(400.0, 64.0)["soil_moisture"], 0.7)
        thin = self._sim(table_depth_m=40.0, rootable_depth_m=0.04, soil_depth_m=0.04)
        deep = self._sim(table_depth_m=40.0)
        for sim in (thin, deep):
            self._enrich(sim, 3.0)
        self.assertLess(thin.ecology.environment_at(400.0, 64.0)["soil_moisture"],
                        deep.ecology.environment_at(400.0, 64.0)["soil_moisture"] - 0.05)


class BalancedRiverGround(flora_fixtures.RiverGround):
    """The river fixture as a generated site hands it over: a dry climate, a coarse west side, a loamy east."""

    def sample_array(self, key, x, y, default=0.0):
        x = np.asarray(x, dtype=np.float64)
        away = np.clip(np.abs(x - 200.0) - 50.0, 0.0, None)
        values = {
            "annual_precipitation_mm": 480.0, "annual_potential_evaporation_mm": 1300.0,
            "coldest_month_temperature_k": 276.15, "warmest_month_temperature_k": 298.15,
            "soil_depth_m": 0.5, "rootable_depth_m": 3.0, "lateral_water_mm": 0.0, "surface_solar_exposure": 1.0,
        }
        if key in values:
            return np.full(x.shape, values[key])
        if key == "water_table_depth_m":
            return away * 0.02  # the ground rises 2 cm a metre from the water's edge
        if key == "available_water_mm_per_m":
            return np.where(x < 200.0, 70.0, 180.0)
        if key == "capillary_rise_m":
            return np.where(x < 200.0, 0.1, 1.0)
        return super().sample_array(key, x, y, default)


class SolverReadsTheBalanceTests(unittest.TestCase):
    def test_each_plant_meets_the_wetness_of_its_own_rooting_depth(self):
        oak = flora_fixtures.profile_from_entity(flora_fixtures.OAK)
        heath = flora_fixtures.profile_from_entity(flora_fixtures.HEATH)
        profiles = {flora_fixtures.OAK["id"]: replace(oak, root_depth_class="deep"),
                    flora_fixtures.HEATH["id"]: replace(heath, root_depth_class="shallow")}
        flora = BiomeFlora(flora_fixtures.PLANET, flora_fixtures.CFB)
        for species_id in profiles:
            flora.record(species_id, "dominant")
        bounds = dict(min_x=0.0, max_x=400.0, min_y=0.0, max_y=200.0)
        vegetation = resident_vegetation(BalancedRiverGround(), bounds, profiles, {flora_fixtures.CFB.key: flora}, cells=80)
        self.assertEqual(sorted(vegetation.wetness_by_rooting), [0.35, 2.0])
        shallow, deep = vegetation.wetness_by_rooting[0.35], vegetation.wetness_by_rooting[2.0]
        x = vegetation.x
        away = np.abs(x - 200.0) - 50.0
        # At the water's edge both sides are wet; the loam stays moist further out than the sand.
        self.assertGreater(float(shallow[(away > 0.0) & (away < 4.0)].min()), 0.7)
        sand, loam = (x < 200.0) & (away > 30.0) & (away < 45.0), (x > 200.0) & (away > 30.0) & (away < 45.0)
        self.assertGreater(float(shallow[loam].mean()), float(shallow[sand].mean()) + 0.2)
        # On the sand 60 to 90 cm above the water the tree's roots reach it and the heath's do not.
        self.assertGreater(float(deep[sand].mean()), float(shallow[sand].mean()) + 0.15)
        # Far from the river there is only the rain, for both.
        far = away > 140.0
        self.assertAlmostEqual(float(deep[far & (x < 200.0)].mean()), float(shallow[far & (x < 200.0)].mean()), delta=0.08)
        self.assertLess(float(shallow[far].max()), 0.36)
        # A map without the demand of the air is read as before, one wetness for all.
        plain = resident_vegetation(flora_fixtures.RiverGround(), bounds, profiles, {flora_fixtures.CFB.key: flora}, cells=80)
        self.assertEqual(plain.wetness_by_rooting, {})


if __name__ == "__main__":
    unittest.main()
