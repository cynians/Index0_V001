import math
import unittest

import numpy as np

from simulations.world_gen import rock_scarps as rs
from simulations.world_gen import sea_cliffs as sc

SHALE, SANDSTONE, BASALT = 6.0, 55.0, 167.0  # effective strength, MPa
BOUNDS = {"min_u": 0.1, "max_u": 0.2, "min_v": 0.4, "max_v": 0.42}


def _coast(rows=81, columns=161, spacing=10.0, slope=0.05, sea_columns=40, sea_slope=0.5):
    """Land rising eastwards out of the sea; the shore runs north-south.

    The sea bed falls away at ``sea_slope``: steeply by default (deep water
    at the foot of the land), gently for a shelving foreshore.
    """
    x = (np.arange(columns) - sea_columns + 0.5) * spacing
    ground = np.where(x > 0.0, slope * x, sea_slope * x)[None, :] * np.ones((rows, 1))
    return ground, spacing


def _cut(strength=SHALE, waves=1.5, slope=0.05, sea_slope=0.5, **options):
    ground, spacing = _coast(slope=slope, sea_slope=sea_slope)
    wave_field = np.full(ground.shape, float(waves))
    change, platform, record = sc.cut_shore(ground, 0.0, dx=spacing, dy=spacing, strength_mpa=strength, wave_height_m=wave_field, **options)
    return ground, spacing, change, platform, record


class WaveTest(unittest.TestCase):
    def test_waves_grow_with_the_open_water_until_the_sea_is_fully_developed(self):
        near = float(sc.fetch_limited_wave_height(10_000.0, 12.0, 9.81))
        far = float(sc.fetch_limited_wave_height(50_000.0, 12.0, 9.81))
        ocean = float(sc.fetch_limited_wave_height(2.0e6, 12.0, 9.81))
        self.assertAlmostEqual(far / near, math.sqrt(5.0), places=6)
        self.assertAlmostEqual(far, 1.37, delta=0.03)
        self.assertAlmostEqual(ocean, 0.24 * 144.0 / 9.81, places=6)
        # A light planet's wind raises higher waves over the same water.
        self.assertGreater(float(sc.fetch_limited_wave_height(50_000.0, 12.0, 3.7)), far)

    def test_an_open_coast_is_exposed_and_a_cove_behind_a_narrow_mouth_is_not(self):
        sea = np.zeros((61, 81), dtype=bool)
        sea[:, :30] = True                # the open sea in the west
        sea[20:41, 40:70] = True          # a cove ...
        sea[29:32, 30:40] = True          # ... behind a mouth three cells wide
        # Waves from 40 cells out: further than the cove is wide.
        exposure = sc.shelter(sea, 40)
        self.assertGreater(float(exposure[30, 5]), 0.95)
        self.assertGreater(float(exposure[5, 29]), 0.85)   # at the foot of a straight shore
        self.assertLess(float(exposure[30, 55]), 0.5)      # in the cove, in line with the mouth
        self.assertLess(float(exposure[22, 68]), 0.2)      # in its far corner
        # Seen from only 8 cells out the cove is open water of its own.
        self.assertGreater(float(sc.shelter(sea, 8)[30, 55]), 0.95)

    def test_sheltered_water_makes_waves_of_its_own(self):
        sea = np.zeros((61, 81), dtype=bool)
        sea[20:41, 10:70] = True          # a sound 21 cells wide and 60 long, closed all round
        free = sc.open_water_cells(sea, 40)
        self.assertLess(float(sc._shelter_of(free, 40)[30, 40]), 0.5)   # no swell reaches its middle from 40 cells out
        waves = sc.local_wind_sea(free, 200.0, 4.0, 9.81)               # 200 m cells: 4 km wide, 12 km long
        self.assertGreater(float(waves[30, 40]), 0.2)
        self.assertLess(float(waves[30, 40]), 0.8)
        # Along the sound's length the wind has more water to work on than across it.
        self.assertGreater(float(waves[30, 40]), float(sc.local_wind_sea(free[4:5], 200.0, 4.0, 9.81)[30, 40]))

    def test_the_ocean_of_a_coarse_grid_sends_higher_waves_to_its_open_side(self):
        sea = np.ones((40, 60), dtype=bool)
        sea[:, 30:] = False               # a continent in the east
        sea[18:22, 24:30] = False         # with a cape
        sea[10:14, 30:36] = True          # and a gulf
        height = sc.ocean_wave_height(sea, 15_000.0, 4.0, 9.81)
        self.assertGreater(float(height[5, 2]), 1.5)
        self.assertGreater(float(height[5, 2]), float(height[12, 34]))


class RecessionTest(unittest.TestCase):
    def test_weak_rock_goes_far_and_strong_rock_hardly_at_all(self):
        shale, sandstone, basalt = (float(sc.recession_m(value, 1.5)) for value in (SHALE, SANDSTONE, BASALT))
        self.assertGreater(shale, 5.0 * sandstone)
        self.assertGreater(sandstone, 2.0 * basalt)
        self.assertGreater(shale, 100.0)
        self.assertLess(basalt, 10.0)

    def test_a_platform_shelters_its_own_cliff(self):
        # Ten times weaker rock does not go ten times further: the waves are spent on the platform.
        soft, softer = float(sc.recession_m(6.0, 1.5)), float(sc.recession_m(0.6, 1.5))
        self.assertLess(softer, 4.0 * soft)
        self.assertLess(softer, 6.0 * sc.PLATFORM_SHELTER_WIDTH_PER_WAVE_HEIGHT * 1.5)

    def test_higher_waves_cut_further_and_none_cut_nothing(self):
        self.assertEqual(float(sc.recession_m(SHALE, 0.0)), 0.0)
        self.assertGreater(float(sc.recession_m(SHALE, 3.0)), 1.8 * float(sc.recession_m(SHALE, 1.5)))

    def test_strength_follows_the_ontologys_erodibility_index(self):
        self.assertAlmostEqual(float(sc.effective_strength_mpa(0.5)), 44.9, places=6)
        self.assertGreater(float(sc.effective_strength_mpa(0.24)), 150.0)   # basalt
        self.assertLess(float(sc.effective_strength_mpa(0.89)), 8.0)        # shale


class ScaleShareTest(unittest.TestCase):
    def test_a_level_draws_what_its_cells_resolve(self):
        # A platform of a few metres is nothing at Region scale and whole at Parcel scale.
        self.assertEqual(float(sc.scale_share(3.0, 234.375)), 0.0)
        self.assertEqual(float(sc.scale_share(3.0, 0.78125)), 1.0)
        shares = [float(sc.scale_share(retreat, 40.0)) for retreat in (30.0, 45.0, 60.0, 75.0, 90.0)]
        self.assertEqual(shares[0], 0.0)
        self.assertEqual(shares[-1], 1.0)
        self.assertEqual(shares, sorted(shares))
        self.assertAlmostEqual(shares[2], 0.5, places=9)


class CostDistanceTest(unittest.TestCase):
    def test_cost_adds_up_from_the_sources_and_goes_round_what_is_dear(self):
        cost = np.full((41, 41), 0.01)
        sources = np.zeros(cost.shape, dtype=bool)
        sources[:, 0] = True
        total = sc.cost_distance(cost, sources, 10.0, 10.0, limit=np.inf)
        np.testing.assert_allclose(total[20, 30], 0.01 * 300.0, rtol=1e-9)
        cost[5:36, 20] = 10.0             # a wall of hard rock with open ends
        walled = sc.cost_distance(cost, sources, 10.0, 10.0, limit=np.inf)
        self.assertGreater(float(walled[20, 30]), float(total[20, 30]) * 1.2)
        self.assertLess(float(walled[20, 30]), 10.0)  # round it, not through it
        np.testing.assert_allclose(walled[2, 30], total[2, 30], rtol=0.05)


class ShoreCutTest(unittest.TestCase):
    def test_waves_leave_a_platform_at_sea_level_and_a_cliff_behind_it(self):
        ground, spacing, change, platform, record = _cut()
        row = (ground + change)[40]
        cut = np.flatnonzero(platform[40])
        self.assertGreater(cut.size, 5)
        # The platform slopes up from under the sea to a little over it at the cliff foot.
        self.assertLess(float(row[cut[0]]), 0.0)
        self.assertGreater(float(row[cut[-1]]), 0.0)
        self.assertLess(float(row[cut[-1]]), 0.3 * 1.5 + 1e-9)
        self.assertTrue(bool(np.all(np.diff(row[cut]) >= -1e-9)))
        # Behind it the land stands as it was: the cliff is as high as the land there.
        cliff = float(row[cut[-1] + 1] - row[cut[-1]])
        self.assertAlmostEqual(cliff, float(ground[40, cut[-1] + 1] - row[cut[-1]]), places=9)
        self.assertGreater(cliff, 2.0)
        self.assertLessEqual(float(change.max()), 0.0)
        self.assertEqual(float(np.abs(change[ground < 0.0]).max()), 0.0)   # the sea bed is not touched
        self.assertEqual(record["landform"], sc.LANDFORM_ID)
        self.assertEqual(record["cut_cells"], int(platform.sum()))
        self.assertGreater(record["drowned_cells"], 0)                      # the shoreline has moved inland
        self.assertAlmostEqual(record["cliff_height_m"][1], cliff, delta=0.6)

    def test_weak_rock_is_cut_back_further_than_strong(self):
        widths = [int(_cut(strength)[3][40].sum()) for strength in (SHALE, SANDSTONE)]
        self.assertGreater(widths[0], 3 * max(1, widths[1]))

    def test_the_height_of_the_land_does_not_decide_how_far_the_shore_goes_back(self):
        low = int(_cut(slope=0.02)[3][40].sum())
        high = int(_cut(slope=0.4)[3][40].sum())
        self.assertEqual(low, high)
        self.assertGreater(high, 5)

    def test_a_cliff_that_has_fallen_back_is_not_taken_for_a_low_shore(self):
        ground, spacing, change, platform, _record = _cut(slope=0.4)
        cut = ground + change
        foot = int(np.flatnonzero(platform[40])[-1])
        # Rockfall lays the cliff back: behind its foot the ground now rises at 1 in 1.
        columns = np.arange(ground.shape[1])[None, :]
        ramp = cut[:, [foot]] + np.clip(columns - foot, 0, None) * spacing
        laid_back = np.where(columns > foot, np.minimum(cut, ramp), cut)
        self.assertLess(float(laid_back[40, foot + 1]), float(cut[40, foot + 1]) - 1.0)
        again = sc.cut_shore(laid_back, 0.0, dx=spacing, dy=spacing, strength_mpa=SHALE, wave_height_m=np.full(ground.shape, 1.5))
        self.assertTrue(again[0] is None or float(np.abs(again[0]).max()) < 0.05)

    def test_the_land_behind_a_sheltered_inlet_is_cut_from_the_open_shore_beside_it(self):
        ground, spacing = _coast()
        shore = int(np.flatnonzero(ground[40] >= 0.0)[0])
        ground[40, shore:shore + 6] = -0.3            # a creek a cell wide, six cells into the land
        waves = np.full(ground.shape, 1.5)
        waves[40, shore:shore + 6] = 0.1              # hardly a ripple in it
        change, platform, record = sc.cut_shore(ground, 0.0, dx=spacing, dy=spacing, strength_mpa=SHALE, wave_height_m=waves)
        beside = int(np.flatnonzero(platform[20])[-1])
        behind = int(np.flatnonzero(platform[40])[-1])
        self.assertGreater(beside, shore + 8)
        # No rib of uncut land is left standing behind the creek.
        self.assertGreaterEqual(behind, beside - 2)
        self.assertTrue(bool(platform[40, shore + 6:behind + 1].all()))
        # It was cut by the waves of the open shore, not by the creek's.
        self.assertGreater(record["wave_height_m"][0], 1.0)

    def test_a_weak_bed_across_the_shore_becomes_a_cove(self):
        ground, spacing = _coast()
        strength = np.full(ground.shape, SANDSTONE)
        strength[30:51] = SHALE
        waves = np.full(ground.shape, 1.5)
        change, platform, _record = sc.cut_shore(ground, 0.0, dx=spacing, dy=spacing, strength_mpa=strength, wave_height_m=waves)
        shore = lambda row: int(np.flatnonzero((ground + change)[row] >= 0.0)[0])  # noqa: E731
        self.assertGreater(shore(40), shore(10) + 4)
        self.assertEqual(shore(10), shore(70))
        # The cove is flanked: the strong rock beside it is cut from the side as well.
        self.assertGreaterEqual(int(platform[27].sum()), int(platform[10].sum()))

    def test_no_waves_no_sea_or_no_land_cut_nothing(self):
        self.assertIsNone(_cut(waves=0.0)[2])
        ground, spacing = _coast()
        waves = np.full(ground.shape, 1.5)
        self.assertIsNone(sc.cut_shore(ground + 500.0, 0.0, dx=spacing, dy=spacing, strength_mpa=SHALE, wave_height_m=waves)[0])
        self.assertIsNone(sc.cut_shore(ground - 100.0, 0.0, dx=spacing, dy=spacing, strength_mpa=SHALE, wave_height_m=waves)[0])

    def test_a_level_leaves_to_the_next_what_its_cells_do_not_resolve(self):
        # Sandstone goes back about 20 m: nothing for 40 m cells, all of it for 5 m cells.
        ground, _spacing = _coast(spacing=40.0)
        coarse = sc.cut_shore(ground, 0.0, dx=40.0, dy=40.0, strength_mpa=SANDSTONE, wave_height_m=np.full(ground.shape, 1.5))[0]
        self.assertIsNone(coarse)
        fine_ground, _spacing = _coast(spacing=5.0)
        fine = sc.cut_shore(fine_ground, 0.0, dx=5.0, dy=5.0, strength_mpa=SANDSTONE, wave_height_m=np.full(fine_ground.shape, 1.5))
        self.assertIsNotNone(fine[0])
        self.assertGreater(int(fine[1][40].sum()), 2)

    def test_a_finer_level_cuts_only_what_a_coarser_one_left(self):
        # Shale goes back some 200 m.  The level with 40 m cells draws it ...
        ground, _spacing = _coast(spacing=40.0)
        change, platform, _record = sc.cut_shore(ground, 0.0, dx=40.0, dy=40.0, strength_mpa=SHALE, wave_height_m=np.full(ground.shape, 1.5))
        first = int(platform[40].sum()) * 40.0
        self.assertGreaterEqual(first, 120.0)
        # ... and its child, on 10 m cells, finds the waves spent on that platform.
        inherited = np.repeat(np.repeat(ground + change, 4, axis=0), 4, axis=1)
        again = sc.cut_shore(inherited, 0.0, dx=10.0, dy=10.0, strength_mpa=SHALE, wave_height_m=np.full(inherited.shape, 1.5))
        more = 0.0 if again[0] is None else int(again[1][160].sum()) * 10.0
        self.assertLess(more, 0.35 * first)

    def test_a_shore_that_has_been_cut_is_not_cut_again(self):
        ground, spacing, change, platform, _record = _cut()
        cut = ground + change
        again = sc.cut_shore(cut, 0.0, dx=spacing, dy=spacing, strength_mpa=SHALE, wave_height_m=np.full(ground.shape, 1.5))
        self.assertTrue(again[0] is None or float(np.abs(again[0]).max()) < 0.05)
        # Not even when the cove it now lies in has sheltered the platform:
        # the waves still come in at their offshore height and break on it.
        sheltered = np.where(platform, 0.5, 1.5)
        again = sc.cut_shore(cut, 0.0, dx=spacing, dy=spacing, strength_mpa=SHALE, wave_height_m=sheltered, offshore_wave_height_m=1.5)
        self.assertTrue(again[0] is None or float(np.abs(again[0]).max()) < 0.05)

    def test_a_shelving_foreshore_takes_the_waves_before_they_reach_the_land(self):
        plunging = int(_cut()[3][40].sum())
        # Deep water 100 m out: half the retreat is spent on the way in.
        shelving = _cut(sea_slope=0.02)
        self.assertGreater(int(shelving[3][40].sum()), 2)
        self.assertLess(int(shelving[3][40].sum()), 0.75 * plunging)
        self.assertGreater(shelving[4]["spent_on_the_water_in_front"], 0.3)
        # A sea that stays shallow as far as the tile reaches cuts nothing: a beach coast.
        self.assertIsNone(_cut(sea_slope=0.004)[2])

    def test_the_cut_fades_out_at_the_tile_rim(self):
        ground, spacing = _coast()
        fade = np.ones(ground.shape)
        fade[:8] = np.linspace(0.0, 1.0, 8)[:, None]
        change, _platform, _record = sc.cut_shore(
            ground, 0.0, dx=spacing, dy=spacing, strength_mpa=SHALE, wave_height_m=np.full(ground.shape, 1.5), fade=fade)
        self.assertEqual(float(np.abs(change[0]).max()), 0.0)
        self.assertLess(float(change[40].min()), -1.0)

    def test_a_tide_widens_the_band_the_platform_slopes_through(self):
        _ground, _spacing, still, _platform, _record = _cut()
        ground, _spacing, tidal, platform, _record = _cut(tidal_range_m=4.0)
        row = (ground + tidal)[40]
        cut = np.flatnonzero(platform[40])
        self.assertLess(float(row[cut[0]]), -2.0)
        # Without a tide the whole platform lies within a wave height of the
        # sea, and its cliff foot lower than the tidal one.
        calm = (ground + still)[40][cut]
        self.assertGreater(float(calm.min()), -1.5)
        self.assertLess(float(calm.max()), 1.5)
        self.assertGreater(float(row[cut[-1]]), float(calm[-1]) + 0.5)


class LevelInputsTest(unittest.TestCase):
    def _parent(self):
        """A coarse parent: ocean in the west, land in the east, 15 km cells, a 4 m/s wind."""
        rows = np.where(np.arange(60)[None, :] < 30, -500.0, 200.0) * np.ones((40, 1))
        wind = np.zeros((8, 8, 3))
        wind[..., 2] = 4.0
        return {
            "heightmap_model": {
                "sample_grid": {"rows": rows.tolist()}, "source_uv_bounds": dict(BOUNDS), "sea_level_m": 0.0, "sample_spacing_x_m": 15_000.0,
            },
            "water_cycle_model": {"climate_grid": {"prevailing_wind_rows": wind.tolist()}},
        }

    def _child_grid(self, bounds):
        u, v = rs._uv_grids(bounds, (41, 81))
        sea = np.zeros((41, 81), dtype=bool)
        sea[:, :40] = True
        return u, v, sea

    def test_the_first_level_takes_its_waves_from_the_open_water_of_its_parent(self):
        bounds = {"min_u": 0.148, "max_u": 0.152, "min_v": 0.409, "max_v": 0.411}
        u, v, sea = self._child_grid(bounds)
        waves, _offshore, record = sc.wave_heights(self._parent(), sea, u, v, spacing_m=200.0, parent_spacing_m=15_000.0, gravity=9.81)
        self.assertEqual(record["source"], "open_water_of_the_parent_grid")
        self.assertGreater(float(waves[20, 39]), 1.0)                    # at the open shore
        self.assertLess(float(waves[20, 39]), 0.24 * 144.0 / 9.81 + 1e-9)  # no higher than the storm wind's full sea
        self.assertEqual(np.asarray(record["height_m"]).shape, (min(41, sc.WAVE_RECORD_CELLS + 1), min(81, sc.WAVE_RECORD_CELLS + 1)))
        self.assertEqual(record["uv_bounds"], bounds)

    def test_water_the_land_shuts_in_has_only_its_own_wind_sea(self):
        bounds = {"min_u": 0.148, "max_u": 0.152, "min_v": 0.409, "max_v": 0.411}
        u, v, sea = self._child_grid(bounds)
        sea[14:26, 58:70] = True                                         # a pond 2.4 km across, 3.6 km behind the shore
        waves, _offshore, record = sc.wave_heights(self._parent(), sea, u, v, spacing_m=200.0, parent_spacing_m=15_000.0, gravity=9.81)
        joined = sc.joined_sea(self._parent(), sea, u, v)
        self.assertTrue(joined[20, 30])
        self.assertFalse(joined[20, 64])
        self.assertFalse(joined[:, 40:].any())
        self.assertGreater(float(waves[20, 64]), 0.0)                    # ripples of its own
        self.assertLess(float(waves[20, 64]), 0.4 * float(waves[20, 39]))
        # The levels below learn which water is the sea's.
        opened = np.asarray(record["open"])
        self.assertEqual(opened.shape, np.asarray(record["height_m"]).shape)
        self.assertEqual(int(opened[20, 64]), 0)
        self.assertEqual(int(opened[20, 30]), 1)
        region = {"heightmap_model": {
            "sample_grid": {"rows": np.where(sea, -5.0, 5.0).tolist()}, "source_uv_bounds": bounds, "sea_level_m": 0.0,
            "regional_landforms": {"landforms": [{"landform": sc.LANDFORM_ID, "waves": record}]},
        }}
        inside = {"min_u": 0.1507, "max_u": 0.1516, "min_v": 0.4097, "max_v": 0.4103}   # a tile wholly round the pond
        child_u, child_v = rs._uv_grids(inside, (31, 46))
        child_sea = sc._sample_grid(np.where(sea, -5.0, 5.0), bounds, child_u, child_v) < 0.0
        self.assertTrue(child_sea.any())
        self.assertFalse(sc.joined_sea(region, child_sea, child_u, child_v).any())

    def test_an_islet_a_cell_wide_does_not_stop_the_waves_behind_it(self):
        bounds = {"min_u": 0.148, "max_u": 0.152, "min_v": 0.409, "max_v": 0.411}
        u, v, sea = self._child_grid(bounds)
        clear, _offshore, _record = sc.wave_heights(self._parent(), sea, u, v, spacing_m=200.0, parent_spacing_m=15_000.0, gravity=9.81)
        reefs = sea.copy()
        reefs[::3, 30] = False            # a line of one-cell reefs off the shore
        behind, _offshore, _record = sc.wave_heights(self._parent(), reefs, u, v, spacing_m=200.0, parent_spacing_m=15_000.0, gravity=9.81)
        self.assertGreater(float(behind[20, 38]), 0.9 * float(clear[20, 38]))
        island = sea.copy()
        island[:, 20:32] = False          # a barrier island 12 cells wide: the channel behind it is sheltered
        channel, _offshore, _record = sc.wave_heights(self._parent(), island, u, v, spacing_m=200.0, parent_spacing_m=15_000.0, gravity=9.81)
        # Sheltered from the open side; what still comes in runs along the
        # channel from beyond the tile, where the water counts as open.
        self.assertLess(float(channel[20, 36]), 0.7 * float(clear[20, 36]))
        self.assertGreater(float(channel[20, 36]), 0.0)

    def test_a_finer_level_reads_what_its_parent_recorded(self):
        bounds = {"min_u": 0.148, "max_u": 0.152, "min_v": 0.409, "max_v": 0.411}
        u, v, sea = self._child_grid(bounds)
        waves, _offshore, record = sc.wave_heights(self._parent(), sea, u, v, spacing_m=200.0, parent_spacing_m=15_000.0, gravity=9.81)
        region = {"heightmap_model": {"regional_landforms": {"landforms": [{"landform": sc.LANDFORM_ID, "waves": record}]}}}
        inner = {"min_u": 0.1495, "max_u": 0.1505, "min_v": 0.4097, "max_v": 0.4103}
        child_u, child_v, child_sea = self._child_grid(inner)
        child_waves, _offshore, child_record = sc.wave_heights(region, child_sea, child_u, child_v, spacing_m=40.0, parent_spacing_m=200.0, gravity=9.81)
        self.assertEqual(child_record["source"], "parent_record")
        self.assertAlmostEqual(float(child_waves[20, 39]), float(waves[20, 39]), delta=0.25 * float(waves[20, 39]))
        # Without a parent grid or record there is nothing to go by.
        self.assertEqual(sc.wave_heights({}, child_sea, child_u, child_v, spacing_m=40.0, parent_spacing_m=200.0, gravity=9.81), (None, None, None))

    def test_the_rock_at_sea_level_is_the_bed_the_sea_stands_in(self):
        strata = {
            "model": rs.MODEL, "built_at_level": 3, "rampart_gradient": 0.6,
            # The stack's horizon rises 1 % along u (1600 m per unit u).
            "structure": [[(BOUNDS["min_u"] - 0.15) * 1600.0, (BOUNDS["max_u"] - 0.15) * 1600.0]] * 2,
            "uv_bounds": dict(BOUNDS),
            # [base, thickness, erodibility, slope resistance]: shale, basalt, shale.
            "beds": [[-100.0, 95.0, 0.89, 0.35], [-5.0, 10.0, 0.24, 0.78], [5.0, 200.0, 0.89, 0.35]],
            "bed_materials": ["mat_shale", "mat_basalt", "mat_shale"],
        }
        u, v = rs._uv_grids(BOUNDS, (5, 201))
        strength, limit = sc.rock_at(np.zeros((5, 201)), [strata], u, v)
        # The beds dip along u: the basalt crosses sea level in a band, shale on either side.
        self.assertGreater(float(strength.max()), 150.0)
        self.assertLess(float(strength.min()), 8.0)
        hard = strength[2] > 100.0
        self.assertTrue(0.02 < hard.mean() < 0.3)
        self.assertGreater(float(limit[2][hard].min()), 1.5)
        self.assertLess(float(limit[2][~hard].max()), 0.8)
        # Without beds the parent's mix decides; without either nothing is known.
        mixed, held = sc.rock_at(np.zeros((3, 3)), [], u[:3, :3], v[:3, :3], [("mat_basalt", 0.5, 0.24, "jointed_volcanic", 0.78), ("mat_shale", 0.5, 0.89, "bedded", 0.35)])
        self.assertGreater(float(mixed[0, 0]), 8.0)
        self.assertLess(float(mixed[0, 0]), 150.0)
        self.assertEqual(sc.rock_at(np.zeros((3, 3)), [], u[:3, :3], v[:3, :3]), (None, None))
        # Every level reads the shore's rock from the same beds: those of Local scale and coarser.
        finer = dict(strata, built_at_level=4)
        coarser = dict(strata, built_at_level=2)
        self.assertEqual([order["built_at_level"] for order in sc.shore_orders([coarser, strata, finer])], [2, 3])
        self.assertEqual(sc.shore_orders(None), [])


if __name__ == "__main__":
    unittest.main()
