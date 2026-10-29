import unittest

import numpy as np

from simulations.world_gen import shore_deposits as sd

N = 121
SPACING = 5.0
SHORE = 40


def _shore(land_slope=0.005, sea_slope=0.06, land_height=None):
    """Sea in the west, land in the east, the shoreline north-south at column ``SHORE``."""
    x = (np.arange(N) - SHORE + 0.5) * SPACING
    profile = np.where(x < 0.0, sea_slope * x, land_slope * x if land_height is None else land_height + land_slope * x)
    return profile[None, :] * np.ones((N, 1))


def _cove(ground, rows, depth_m, reach=10):
    """Cut a cove ``reach`` cells back into the land over ``rows``, its floor ``depth_m`` under the sea."""
    cut = ground.copy()
    cut[rows[0]:rows[1], SHORE:SHORE + reach] = -depth_m
    return cut


def _build(ground, waves=2.0, **options):
    field = np.full(ground.shape, waves) if np.isscalar(waves) else waves
    return sd.build_shore(ground, 0.0, dx=SPACING, dy=SPACING, wave_height_m=field, offshore_wave_height_m=np.full(ground.shape, 2.0), **options)


class ProfileTest(unittest.TestCase):
    def test_the_berm_stands_at_the_run_up_and_the_shoreface_ends_at_the_depth_of_closure(self):
        self.assertAlmostEqual(sd.runup_wave_heights(), 0.57, delta=0.02)
        self.assertAlmostEqual(float(sd.berm_height_m(2.0)), 2.0 * sd.runup_wave_heights())
        self.assertAlmostEqual(float(sd.berm_height_m(2.0, tidal_range_m=3.0)), 2.0 * sd.runup_wave_heights() + 1.5)
        self.assertAlmostEqual(float(sd.closure_depth_m(2.0)), 3.5)
        width = float(sd.shoreface_width_m(2.0))
        self.assertAlmostEqual(float(sd.shoreface_depth_m(width)), 3.5, places=6)
        self.assertGreater(float(sd.shoreface_depth_m(100.0)), float(sd.shoreface_depth_m(50.0)))
        # Concave: half the depth is reached in about a third of the width.
        self.assertLess(float(sd.shoreface_depth_m(0.36 * width)), 0.52 * 3.5)

    def test_distances_are_euclidean(self):
        mask = np.zeros((21, 21), dtype=bool)
        mask[10, 10] = True
        distance = sd.distance_cells(mask, 12)
        self.assertAlmostEqual(float(distance[10, 15]), 5.0)
        self.assertAlmostEqual(float(distance[13, 14]), 5.0)
        self.assertAlmostEqual(float(distance[0, 0]), 13.0)   # beyond the cap

    def test_closing_fills_a_notch_and_opening_removes_a_spit_and_neither_does_it_twice(self):
        land = np.zeros((60, 60), dtype=bool)
        land[:, 30:] = True
        land[25:31, 30:38] = False          # a notch six cells wide
        land[10:12, 22:30] = True           # a spit two cells wide
        closed = sd.closing(land, 4.0)
        self.assertTrue(closed[25:31, 33:38].all())                  # all but the arc the disc bulges in at its mouth
        self.assertFalse(closed[:, :20].any())                       # nothing is built out from a straight shore
        np.testing.assert_array_equal(sd.closing(closed, 4.0), closed)
        # Nor, but for the cell-wide tips of the arc at the notch's mouth, with a smaller disc:
        # a finer level closing at its own radius finds its parent's shore closed.
        self.assertLessEqual(int((sd.closing(closed, 2.0) & ~closed).sum()), 6)
        opened = sd.opening(land, 1.5)
        self.assertFalse(opened[10:12, 22:29].any())
        self.assertTrue(opened[40:50, 40:50].all())
        np.testing.assert_array_equal(sd.opening(opened, 1.5), opened)


class BeachTest(unittest.TestCase):
    def test_a_low_shore_gets_a_beach_face_and_a_berm(self):
        before = _shore()
        change, sand, record = _build(before)
        after = before + change
        berm = float(sd.berm_height_m(2.0))
        row = after[N // 2]
        self.assertAlmostEqual(float(row[SHORE]), sd.BEACH_FACE_GRADIENT * 0.5 * SPACING, delta=0.03)  # the foot of the face
        self.assertAlmostEqual(float(row[SHORE + 4]), berm, delta=0.03)                                 # the berm
        self.assertLessEqual(float(after[:, SHORE:].max() - before[:, SHORE:].max()), 1e-9)
        self.assertLess(float(change[:, SHORE:].max()), berm + 1e-6)     # nothing is piled higher than the swash runs
        self.assertGreater(record["beach_cells"], N)
        self.assertEqual(record["berm_height_m"][1], round(berm, 2))
        # Far behind the shore the ground is as it was.
        self.assertEqual(float(np.abs(change[:, SHORE + 30:]).max()), 0.0)
        self.assertGreater(float(sand[N // 2, SHORE + 2]), 0.2)

    def test_the_shoreface_takes_the_two_thirds_profile_where_the_bed_lies_deeper(self):
        before = _shore(sea_slope=0.06)
        change, _sand, record = _build(before)
        after = before + change
        for cells in (4, 8, 12):                                     # 17.5, 37.5, 57.5 m from the shoreline
            distance = (cells - 0.5) * SPACING
            self.assertAlmostEqual(float(after[N // 2, SHORE - cells]), -float(sd.shoreface_depth_m(distance)), delta=0.02)
        self.assertGreater(record["shoreface_cells"], N)
        self.assertTrue((after[:, :SHORE] < 0.0).all())               # the sea stays sea: a straight shore is not built out

    def test_a_bed_shallower_than_the_profile_is_left_alone(self):
        before = _shore(sea_slope=0.004)
        change, _sand, _record = _build(before)
        self.assertEqual(float(np.abs(change[:, :SHORE]).max()), 0.0)

    def test_a_plunging_shore_has_room_for_a_prism_and_no_more(self):
        before = _shore(sea_slope=0.0)
        before[:, :SHORE] = -30.0
        change, _sand, _record = _build(before)
        self.assertLess(float(change.max()), float(sd.closure_depth_m(2.0)) + 1e-6)
        self.assertTrue((before + change)[:, :SHORE].max() < -25.0)

    def test_sand_fills_a_cove_and_leaves_the_headlands(self):
        before = _cove(_shore(land_height=6.0), (52, 66), depth_m=1.5)
        change, _sand, record = _build(before)
        after = before + change
        self.assertTrue((after[54:64, SHORE + 2:SHORE + 10] >= 0.0).all())               # the cove is beach now
        self.assertGreaterEqual(record["new_land_cells"], 100)
        land_before = before >= 0.0
        self.assertLess(float(np.abs(change[land_before]).max()), 1e-9)                  # high ground is not touched
        self.assertTrue((after[:, :SHORE - 1] < 0.0).all())                              # and the shore is not built out past it

    def test_a_cove_deeper_than_the_waves_reach_keeps_its_water(self):
        before = _cove(_shore(land_height=6.0), (52, 66), depth_m=12.0)
        change, _sand, _record = _build(before)
        self.assertLess(float((before + change)[59, SHORE + 4]), -5.0)

    def test_water_a_river_keeps_open_is_not_filled(self):
        before = _cove(_shore(land_height=6.0), (52, 66), depth_m=1.5)
        open_ = np.zeros(before.shape, dtype=bool)
        open_[52:66, SHORE:SHORE + 10] = True
        change, _sand, _record = _build(before, keep_open=open_)
        self.assertTrue(((before + change)[54:64, SHORE:SHORE + 8] < 0.0).all())

    def test_applied_to_its_own_result_the_rule_adds_next_to_nothing(self):
        before = _cove(_cove(_shore(land_height=6.0), (52, 66), depth_m=1.5), (20, 26), depth_m=0.8, reach=6)
        change, sand, _record = _build(before, parent_spacing_m=6.0 * SPACING)
        again, _sand, _record = _build(before + change, parent_spacing_m=6.0 * SPACING, sand_below_m=sand)
        first = int((np.abs(change) > 0.05).sum())
        second = 0 if again is None else int((np.abs(again) > 0.05).sum())
        self.assertGreater(first, 1000)
        self.assertLess(second, 0.01 * first)

    def test_a_finer_level_fills_only_the_coves_its_parent_could_not_hold(self):
        # A cove 40 cells wide and shallow: the first level to build beaches fills it,
        # a level whose parent has built them leaves it (its parent would have).
        before = _cove(_shore(land_height=6.0), (40, 80), depth_m=1.0, reach=30)
        first, _sand, _record = _build(before)
        self.assertGreater(float((before + first)[60, SHORE + 15]), 0.0)
        nothing_below = np.zeros(before.shape)
        child, _sand, record = _build(before, parent_spacing_m=3.0 * SPACING, sand_below_m=nothing_below)
        self.assertLess(float((before + child)[60, SHORE + 15]), 0.0)
        self.assertLessEqual(record["closing_radius_limit_m"], sd.PARENT_CLOSING_CELLS * 3.0 * SPACING + 1e-6)

    def test_the_room_for_sand_is_judged_by_the_bed_under_it(self):
        # A cove too deep to fill, with four metres of inherited sand on its floor:
        # judged by the sand surface it would be shallow enough to fill.
        before = _cove(_shore(land_height=6.0), (52, 66), depth_m=6.0)
        raised = before.copy()
        below = np.zeros(before.shape)
        raised[52:66, SHORE:SHORE + 10] += 4.0
        below[52:66, SHORE:SHORE + 10] = 4.0
        change, _sand, _record = _build(raised, parent_spacing_m=20.0 * SPACING, sand_below_m=below)
        self.assertLess(float((raised + (0.0 if change is None else change))[59, SHORE + 4]), 0.0)

    def test_a_parents_sand_is_not_kept_on_ground_the_waves_cannot_reach(self):
        # A parent's beach cell covers the beach and the cliff top behind it alike.
        before = _cove(_shore(land_height=6.0), (52, 66), depth_m=1.5)
        first, sand, _record = _build(before, parent_spacing_m=6.0 * SPACING)
        ground = before + first
        handed_down = np.maximum(sand, np.where((ground > 5.0) & (np.arange(N)[None, :] < SHORE + 24), 2.0, 0.0))
        self.assertGreater(int(((handed_down > 0.3) & (ground > 5.0)).sum()), 500)
        kept = sd.sand_within_reach(handed_down, ground, 0.0, 2.0)
        self.assertEqual(int(((kept > 0.0) & (ground > 5.0)).sum()), 0)            # none on the cliff top
        beach = (sand > 0.3) & (ground < 2.0)
        self.assertGreater(int(beach.sum()), 100)
        np.testing.assert_array_equal(kept[beach], sand[beach])                    # the beach keeps its own
        # The rule itself reads the same sand: applied again it still adds next to nothing.
        again, laid, _record = _build(ground, parent_spacing_m=6.0 * SPACING, sand_below_m=handed_down)
        self.assertLess(0 if again is None else int((np.abs(again) > 0.05).sum()), 0.01 * int((np.abs(first) > 0.05).sum()))
        if laid is not None:
            self.assertEqual(int(((laid > 0.0) & (ground > 5.0)).sum()), 0)

    def test_low_narrow_ground_is_washed_over_and_high_ground_stands(self):
        before = _shore(land_height=6.0)
        before[30:60, SHORE - 12:SHORE - 10] = 0.3      # a bar two cells wide, lower than the berm
        before[70:100, SHORE - 12:SHORE - 10] = 5.0     # a wall of the same width
        change, _sand, record = _build(before)
        after = before + change
        self.assertTrue((after[32:58, SHORE - 12:SHORE - 10] < 0.0).all())
        self.assertTrue((after[72:98, SHORE - 12:SHORE - 10] >= 5.0 - 1e-9).all())
        self.assertGreaterEqual(record["washed_over_cells"], 50)

    def test_a_pond_behind_the_shore_is_not_the_sea(self):
        before = _shore(land_height=3.0)
        before[50:60, SHORE + 20:SHORE + 30] = -4.0
        waves = np.full(before.shape, 2.0)
        waves[50:60, SHORE + 20:SHORE + 30] = 0.1       # only its own ripples
        change, _sand, _record = _build(before, waves=waves)
        self.assertEqual(float(np.abs(change[45:65, SHORE + 15:SHORE + 35]).max()), 0.0)

    def test_with_more_room_than_sand_less_is_filled(self):
        before = _cove(_cove(_shore(land_height=6.0), (20, 26), depth_m=0.8, reach=6), (40, 100), depth_m=3.0, reach=40)
        rich, _sand, rich_record = _build(before)
        poor, _sand, poor_record = _build(before, sand_m3_per_m=30.0)
        self.assertLess(poor_record["sand_volume_m3"], rich_record["sand_volume_m3"])
        self.assertLess(poor_record["closing_radius_m"], rich_record["closing_radius_m"])
        self.assertLess(poor_record["new_land_cells"], rich_record["new_land_cells"])

    def test_no_waves_no_sea_or_no_land_build_nothing(self):
        ground = _shore()
        self.assertIsNone(_build(ground, waves=0.0)[0])
        self.assertIsNone(_build(np.abs(ground) + 1.0)[0])
        self.assertIsNone(_build(-np.abs(ground) - 1.0)[0])

    def test_the_change_fades_out_at_the_tile_rim(self):
        before = _shore()
        fade = np.ones(before.shape)
        fade[:6, :] = fade[-6:, :] = 0.0
        change, _sand, _record = _build(before, fade=fade)
        self.assertEqual(float(np.abs(change[:6]).max()), 0.0)
        self.assertGreater(float(np.abs(change[N // 2]).max()), 0.5)


class RecordTest(unittest.TestCase):
    def test_the_sand_is_packed_into_the_record_and_read_back(self):
        before = _cove(_shore(land_height=6.0), (52, 66), depth_m=1.5)
        change, sand, record = _build(before)
        packed = sd.with_sand_grid(record, sand)
        self.assertLess(len(packed["sand"]["data"]), 20_000)
        heightmap = {"regional_landforms": {"landforms": [packed]}, "source_uv_bounds": {"min_u": 0.0, "max_u": 1.0, "min_v": 0.0, "max_v": 1.0}}
        fields = sd.heightmap_shore_fields(heightmap, before.shape)
        np.testing.assert_allclose(fields["thickness"], sand, atol=float(sand.max()) / 255.0 + 1e-9)
        self.assertEqual(float(fields["cover"].max()), 1.0)
        self.assertEqual(float(fields["cover"][0, -1]), 0.0)
        self.assertIsNone(sd.heightmap_shore_fields(heightmap, (10, 10)))
        self.assertIsNone(sd.heightmap_shore_fields({}, before.shape))
        # A finer level reads its parent's sand at its own cells.
        u, v = np.meshgrid(np.linspace(0.3, 0.4, 20), np.linspace(0.45, 0.55, 20))
        inherited = sd.inherited_sand_m(heightmap, u, v)
        self.assertEqual(inherited.shape, (20, 20))
        self.assertGreater(float(inherited.max()), 0.5)

    def test_a_record_without_sand_carries_the_inherited_grid(self):
        below = np.zeros((8, 8))
        below[2:4, 2:4] = 1.0
        record = sd.with_sand_grid({"landform": sd.LANDFORM_ID}, below)
        np.testing.assert_allclose(sd.record_sand_m(record), below, atol=1e-2)
        self.assertNotIn("sand", sd.with_sand_grid({"landform": sd.LANDFORM_ID}, np.zeros((4, 4))))


class MaterialTest(unittest.TestCase):
    def test_a_beach_is_sand_and_carries_no_mantle(self):
        from simulations.world_gen.material_lod import _fresh_deposit

        shape = (2, 3)
        partition = {
            "weathered_mantle_fraction": np.full(shape, 0.5), "residual_regolith_fraction": np.full(shape, 0.1),
            "exposed_bedrock_fraction": np.full(shape, 0.3), "alluvial_cover_fraction": np.full(shape, 0.1),
        }
        cover = np.array([[0.0, 0.5, 1.0], [0.0, 0.5, 1.0]])
        _fresh_deposit(partition, cover, shape)
        np.testing.assert_allclose(partition["weathered_mantle_fraction"][0], [0.5, 0.25, 0.0])
        np.testing.assert_allclose(partition["exposed_bedrock_fraction"][0], [0.3, 0.15, 0.0])
        np.testing.assert_allclose(partition["alluvial_cover_fraction"][0], [0.1, 0.475, 0.95])
        # Shares still add up to no more than the cell.
        total = sum(partition[key] for key in partition)
        self.assertLessEqual(float(total.max()), 1.0 + 1e-9)


if __name__ == "__main__":
    unittest.main()
