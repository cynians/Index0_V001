import unittest

import numpy as np

from simulations.world_gen import river_deltas as rd
from simulations.world_gen import sea_cliffs

N = 81
SPACING = 100.0
SHORE_ROW = 50
VALLEY = 40


def _bay(sea_slope=0.004):
    """Land sloping south to a shore along row ``SHORE_ROW``, a valley down its middle, the sea bed falling away south."""
    rows = np.arange(N)[:, None] * np.ones((1, N))
    columns = np.arange(N)[None, :] * np.ones((N, 1))
    north = (SHORE_ROW - rows - 0.5) * SPACING
    land = 0.01 * north + np.minimum(np.abs(columns - VALLEY), 6.0) * 1.5 * np.clip(north / 500.0, 0.0, 1.0)
    return np.where(north > 0.0, land, sea_slope * north)


def _parent(runoff_mm=400.0, temperature_k=293.15):
    grid = lambda value: [[value] * 3 for _ in range(3)]  # noqa: E731
    return {"water_cycle_model": {"climate_grid": {
        "annual_runoff_rows_mm": grid(runoff_mm), "temperature_rows_k": grid(temperature_k),
        "annual_precipitation_rows_mm": grid(900.0), "annual_potential_evaporation_rows_mm": grid(900.0),
    }}}


def _inflow(catchment_km2):
    cells = np.zeros((N, N))
    cells[0, VALLEY] = catchment_km2 * 1.0e6 / (SPACING * SPACING)
    return cells


def _build(ground, waves, catchment_km2=5000.0, **options):
    return rd.build_deltas(
        ground, 0.0, dx=SPACING, dy=SPACING, open_sea=ground < 0.0, wave_height_m=np.full(ground.shape, waves),
        parent_entity=_parent(), level=3, inflow_cells=_inflow(catchment_km2),
        to_uv=lambda x, y: (np.asarray(x) / 1.0e6, np.asarray(y) / 1.0e6),
        to_local=lambda u, v: (np.asarray(u) * 1.0e6, np.asarray(v) * 1.0e6), **options)


class LoadAndWavesTest(unittest.TestCase):
    def test_the_load_follows_bqart(self):
        # 1.05 km3 a year from 19,300 km2 with 1.37 km of relief at 31 degrees: 0.02 x 1.015 x 139 x 1.37 x 31.2.
        load = float(rd.sediment_load_kg_s(33.3, 19_319.0, 1370.0, 31.2))
        self.assertAlmostEqual(load, 120.6, delta=1.5)
        self.assertGreater(float(rd.sediment_load_kg_s(33.3, 19_319.0, 2740.0, 31.2)), 1.99 * load)
        # Below 2 degrees the cold no longer counts.
        self.assertEqual(float(rd.sediment_load_kg_s(10.0, 100.0, 500.0, -20.0)), float(rd.sediment_load_kg_s(10.0, 100.0, 500.0, 2.0)))

    def test_the_waves_decide_whether_a_river_builds_a_delta(self):
        self.assertGreater(float(rd.fluvial_dominance(120.0, 0.3, 9.81)), 1.0)       # a sheltered bay
        self.assertLess(float(rd.fluvial_dominance(120.0, 2.0, 9.81)), 1.0)          # an open coast
        heights = np.array([0.2, 0.5, 1.0, 2.0, 4.0])
        dominance = rd.fluvial_dominance(120.0, heights, 9.81)
        self.assertTrue(np.all(np.diff(dominance) < 0.0))
        # The waves' capacity goes with the 2.5th power of their height.
        capacity = rd.wave_transport_capacity_m3_s(heights, 9.81)
        self.assertAlmostEqual(float(capacity[3] / capacity[2]), 2.0 ** 2.5, places=6)

    def test_a_larger_river_crosses_its_delta_on_a_gentler_slope(self):
        small = rd.topset_gradient(5.0, 20.0, 9.81)
        large = rd.topset_gradient(2000.0, 20.0, 9.81)
        self.assertLess(large, small)
        for slope in (small, large):
            self.assertTrue(rd.TOPSET_GRADIENT_RANGE[0] <= slope <= rd.TOPSET_GRADIENT_RANGE[1])

    def test_the_stillstand_s_load_is_a_volume(self):
        # 100 kg/s for 6,000 years, 40 % kept, at 1,590 kg of grains to the cubic metre.
        self.assertAlmostEqual(float(rd.deposit_volume_m3(100.0)) / 1.0e9, 100.0 * 0.4 * 6000.0 * 3.156e7 / 1590.0 / 1.0e9, places=3)


class FormTest(unittest.TestCase):
    def test_a_plain_that_rises_to_the_mouth_and_a_front_that_falls_to_the_bed(self):
        distance = np.array([0.0, 1000.0, 2000.0, 2100.0, 2500.0])
        surface = rd.delta_surface(distance, 2000.0, 5.0e-4, 0.0)
        np.testing.assert_allclose(surface[:3], [1.0, 0.5, 0.0])
        np.testing.assert_allclose(surface[3:], [-100.0 * rd.FORESET_GRADIENT, -500.0 * rd.FORESET_GRADIENT])

    def test_the_shoreline_comes_as_far_as_the_volume_reaches(self):
        rows, columns = np.mgrid[0:101, 0:101].astype(float)
        distance = np.hypot(rows - 50.0, columns - 50.0) * 50.0
        bed = np.full(distance.shape, -5.0)
        for volume in (2.0e6, 2.0e7):
            shoreline = rd.solve_shoreline_m(distance, bed, volume, 5.0e-4, 0.0, 2500.0, 5000.0)
            laid = float(np.maximum(rd.delta_surface(distance, shoreline, 5.0e-4, 0.0) - bed, 0.0).sum()) * 2500.0
            self.assertAlmostEqual(laid / volume, 1.0, delta=0.03)
        # Deeper water takes more sand to the metre: the same volume comes less far.
        deep = rd.solve_shoreline_m(distance, bed - 15.0, 2.0e7, 5.0e-4, 0.0, 2500.0, 5000.0)
        self.assertLess(deep, 0.7 * shoreline)

    def test_a_basin_filled_to_its_far_shore_takes_no_more(self):
        distance = np.full((21, 21), np.inf)
        distance[8:13, 8:13] = np.hypot(*np.mgrid[-2:3, -2:3]) * 50.0
        shoreline = rd.solve_shoreline_m(distance, np.full((21, 21), -2.0), 1.0e12, 5.0e-4, 0.0, 2500.0, 5000.0)
        self.assertAlmostEqual(shoreline, float(distance[8, 8]), places=6)


class BuildTest(unittest.TestCase):
    def test_a_river_into_sheltered_water_builds_a_delta_at_its_mouth(self):
        before = _bay()
        change, sediment, _open, record = _build(before, waves=0.15)
        self.assertEqual(len(record["deltas"]), 1)
        delta = record["deltas"][0]
        self.assertEqual(delta["regime"], "river_dominated")
        self.assertGreater(delta["fluvial_dominance"], 1.0)
        self.assertGreater(delta["new_land_km2"], 0.5)
        after = before + change
        self.assertTrue((change >= 0.0).all())
        self.assertGreater(float(after[SHORE_ROW + 3, VALLEY]), 0.0)                 # land where the sea was, in front of the mouth
        self.assertLess(float(after[SHORE_ROW + 3, 4]), 0.0)                         # and still sea far along the shore
        new_land = (after >= 0.0) & (before < 0.0)
        columns = np.nonzero(new_land)[1]
        self.assertAlmostEqual(float(columns.mean()), VALLEY, delta=3.0)             # centred on the mouth
        # The plain rises gently to the mouth; the front is steeper than the plain.
        plain_height = float(after[new_land].max())
        self.assertLess(plain_height, 3.0)
        np.testing.assert_array_equal(sediment, change)
        self.assertEqual(delta["built_at_level"], 3)

    def test_on_an_open_coast_the_waves_take_the_sand_and_only_the_mouth_is_kept_open(self):
        before = _bay()
        change, _sediment, open_, record = _build(before, waves=2.5)
        self.assertIsNone(change)
        self.assertEqual(record["deltas"], [])
        self.assertEqual(record["mouths"][0]["regime"], "wave_dominated")
        self.assertLess(record["mouths"][0]["fluvial_dominance"], 1.0)
        self.assertTrue(open_[SHORE_ROW:SHORE_ROW + 2, VALLEY - 1:VALLEY + 2].any())
        self.assertFalse(open_[:, :20].any())

    def test_a_bigger_river_builds_a_bigger_delta(self):
        before = _bay()
        small = _build(before, waves=0.15, catchment_km2=1500.0)[3]["deltas"][0]
        large = _build(before, waves=0.15, catchment_km2=15_000.0)[3]["deltas"][0]
        self.assertGreater(large["volume_m3"], 2.0 * small["volume_m3"])
        self.assertGreater(large["radius_m"], small["radius_m"])
        self.assertLess(large["topset_gradient"], small["topset_gradient"])

    def test_a_delta_a_coarser_level_has_built_is_not_built_again(self):
        before = _bay()
        change, _sediment, _open, record = _build(before, waves=0.15)
        built = record["deltas"]
        again, _sediment, _open, record = _build(before + change, waves=0.15, inherited=built)
        self.assertIsNone(again)
        self.assertEqual(record["deltas"], [])
        self.assertEqual(record["inherited_deltas"], built)
        self.assertEqual(record["mouths"][0]["regime"], "on_a_delta")

    def test_a_delta_too_small_for_the_cells_is_left_to_a_finer_level(self):
        change, _sediment, _open, record = _build(_bay(sea_slope=0.2), waves=0.02, catchment_km2=30.0)
        self.assertIsNone(change)
        self.assertEqual(record["mouths"][0]["regime"], "river_dominated_unresolved")

    def test_water_the_waves_rule_is_not_built_into(self):
        # Sheltered at the mouth, open sea three cells out: the delta stops where the waves take over.
        before = _bay()
        waves = np.full(before.shape, 0.15)
        waves[SHORE_ROW + 3:, :] = 3.0
        change, _sediment, _open, record = rd.build_deltas(
            before, 0.0, dx=SPACING, dy=SPACING, open_sea=before < 0.0, wave_height_m=waves, parent_entity=_parent(), level=3,
            inflow_cells=_inflow(5000.0))
        after = before + (0.0 if change is None else change)
        self.assertTrue((after[SHORE_ROW + 4:, :] < 0.0).all())

    def test_no_runoff_no_sea_or_too_coarse_a_level_build_nothing(self):
        before = _bay()
        dry = rd.build_deltas(before, 0.0, dx=SPACING, dy=SPACING, open_sea=before < 0.0, wave_height_m=np.full(before.shape, 0.1),
                              parent_entity=_parent(runoff_mm=0.0), level=3, inflow_cells=_inflow(5000.0))
        self.assertIsNone(dry[0])
        self.assertIsNone(_build(np.abs(before) + 1.0, waves=0.1)[0])
        coarse = rd.build_deltas(before, 0.0, dx=SPACING, dy=SPACING, open_sea=before < 0.0, wave_height_m=np.full(before.shape, 0.1),
                                 parent_entity=_parent(), level=1, inflow_cells=_inflow(5000.0))
        self.assertIsNone(coarse[0])


def _valley_with_a_hollow(depth_m=12.0, radius_cells=10):
    """Land sloping south with a valley down its middle and a bowl in the valley floor; no sea."""
    rows = np.arange(N)[:, None] * np.ones((1, N))
    columns = np.arange(N)[None, :] * np.ones((N, 1))
    ground = 0.01 * (N - rows) * SPACING + np.minimum(np.abs(columns - VALLEY), 8.0) * 1.5
    reach = np.hypot(rows - 40.0, columns - VALLEY) / radius_cells
    return ground - depth_m * np.clip(1.0 - reach * reach, 0.0, 1.0)


def _lakes(ground, catchment_km2=5000.0, parent=None, **options):
    return rd.build_lake_deltas(
        ground, dx=SPACING, dy=SPACING, open_sea=None, parent_entity=parent or _parent(), level=3, inflow_cells=_inflow(catchment_km2),
        to_uv=lambda x, y: (np.asarray(x) / 1.0e6, np.asarray(y) / 1.0e6),
        to_local=lambda u, v: (np.asarray(u) * 1.0e6, np.asarray(v) * 1.0e6), **options)


class LakeTest(unittest.TestCase):
    def test_a_river_builds_a_delta_where_it_enters_a_lake(self):
        before = _valley_with_a_hollow(depth_m=40.0, radius_cells=14)
        change, record = _lakes(before, catchment_km2=60.0)
        self.assertEqual(len(record["deltas"]), 1)
        delta = record["deltas"][0]
        self.assertEqual(delta["receiving"], "lake")
        self.assertEqual(delta["regime"], "lake_delta")
        self.assertFalse(delta["lake_filled"])
        self.assertGreater(delta["new_land_km2"], 0.02)
        self.assertTrue((change >= 0.0).all())
        after = before + change
        level = delta["lake_level_m"]
        # Land where the lake was, on the side the river comes in (the north); water still on the far side.
        self.assertGreaterEqual(float(after[29, VALLEY]), level)
        self.assertLess(float(after[48, VALLEY]), level - 5.0)
        self.assertEqual(float(np.abs(change[60:, :]).max()), 0.0)        # nothing below the sill

    def test_a_large_river_fills_a_small_lake_to_its_far_shore(self):
        before = _valley_with_a_hollow(depth_m=16.0, radius_cells=8)   # deep enough to close on this slope
        change, record = _lakes(before, catchment_km2=20_000.0)
        delta = record["deltas"][0]
        self.assertTrue(delta["lake_filled"])
        after = before + change
        level = delta["lake_level_m"]
        bowl = np.hypot(*(np.mgrid[0:N, 0:N] - np.array([40, VALLEY])[:, None, None])) < 5
        self.assertTrue((after[bowl] >= level - 1e-6).all())                 # a valley floor where the lake was
        # And nothing more is built on it by a level that inherits the record.
        again, record = _lakes(after, catchment_km2=20_000.0, inherited=[delta])
        self.assertIsNone(again)

    def test_a_hollow_its_river_cannot_keep_full_is_left_alone(self):
        dry = _parent(runoff_mm=20.0)
        dry["water_cycle_model"]["climate_grid"]["annual_potential_evaporation_rows_mm"] = [[2600.0] * 3] * 3
        dry["water_cycle_model"]["climate_grid"]["annual_precipitation_rows_mm"] = [[80.0] * 3] * 3
        change, record = _lakes(_valley_with_a_hollow(depth_m=30.0, radius_cells=16), catchment_km2=50.0, parent=dry)
        self.assertIsNone(change)
        self.assertEqual(record["mouths"][0]["regime"], "terminal_lake")

    def test_ground_without_hollows_or_without_runoff_has_no_lake_deltas(self):
        rows = np.arange(N)[:, None] * np.ones((1, N))
        self.assertIsNone(_lakes(0.01 * (N - rows) * SPACING)[0])
        self.assertIsNone(_lakes(_valley_with_a_hollow(), parent=_parent(runoff_mm=0.0))[0])


class RecordTest(unittest.TestCase):
    def test_the_sediment_is_packed_into_the_record_and_read_back(self):
        before = _bay()
        change, sediment, _open, record = _build(before, waves=0.15)
        packed = rd.with_sediment_grid(record, sediment)
        after = before + change
        heightmap = {"regional_landforms": {"landforms": [packed]}, "sample_grid": {"rows": after.tolist()}, "sea_level_m": 0.0,
                     "source_uv_bounds": {"min_u": 0.0, "max_u": 1.0, "min_v": 0.0, "max_v": 1.0}}
        fields = rd.heightmap_delta_fields(heightmap, before.shape)
        np.testing.assert_allclose(fields["thickness"], sediment, atol=float(sediment.max()) / 255.0 + 1e-9)
        self.assertEqual(float(fields["cover"].max()), 1.0)
        on_plain = (sediment > 0.5) & (after >= 0.0)
        self.assertEqual(float(fields["front"][on_plain].max()), 0.0)
        self.assertEqual(rd.heightmap_deltas(heightmap), record["deltas"])
        self.assertIsNone(rd.heightmap_delta_fields({}, before.shape))
        u, v = np.meshgrid(np.linspace(0.4, 0.6, 12), np.linspace(0.55, 0.75, 12))
        self.assertGreater(float(rd.inherited_sediment_m(heightmap, u, v).max()), 0.3)


if __name__ == "__main__":
    unittest.main()
