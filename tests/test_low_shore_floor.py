import unittest

import numpy as np

from simulations.world_gen import regional_refinement as rr

N = 96
SPACING = 40.0
SHORE = 20


def _plain(relief_m=0.3):
    """A plain rising 0.2 % eastwards out of the sea, with a little relief on it."""
    y, x = np.mgrid[0:N, 0:N].astype(float)
    ramp = 0.002 * (x - SHORE + 0.5) * SPACING
    relief = relief_m * np.sin(y / 7.0) * np.sin(x / 5.0) * np.clip((x - SHORE - 8.0) / 30.0, 0.0, 1.0)
    return ramp, ramp + relief


class LowShoreFloorTest(unittest.TestCase):
    """Steps that keep lowered land above the sea must not raise land that was low already."""

    def _assert_low_land_stays_low(self, before, after):
        before, after = np.asarray(before, dtype=float), np.asarray(after, dtype=float)
        low = (before >= 0.0) & (before < 0.3)
        self.assertGreater(int(low.sum()), 200)
        self.assertLess(float(np.percentile(after[low], 90)), 0.45)
        land = before >= 0.0
        piled = np.abs(after[land] - rr.LAND_FLOOR_ABOVE_SEA_M) < 1e-3
        self.assertLess(float(piled.mean()), 0.02)
        self.assertTrue((after[~land] < 0.0).all())

    def test_the_floor_is_where_a_cell_was_if_that_was_lower(self):
        floor = rr._land_floor(np.array([0.1, 0.5, 3.0]), 0.0)
        np.testing.assert_allclose(floor, [0.1, 0.5, 0.5])
        np.testing.assert_allclose(rr._land_floor(np.array([10.2, 14.0]), 10.0), [10.2, 10.5])

    def test_dissection_leaves_a_low_shore_low(self):
        inherited, rows = _plain(relief_m=12.0)   # enough new relief for the dissection to run
        after, _summary = rr._fluvial_dissection(
            rows.tolist(), inherited.tolist(), sea_level=0.0, spacing_x_m=SPACING, spacing_y_m=SPACING, parent_spacing_m=6.0 * SPACING, level=3)
        self._assert_low_land_stays_low(rows, after)

    def test_floodplains_leave_a_low_shore_low(self):
        _inherited, rows = _plain()
        after, _summary = rr._floodplain_flattening(
            rows.tolist(), sea_level=0.0, spacing_x_m=SPACING, spacing_y_m=SPACING, parent_spacing_m=6.0 * SPACING, level=3)
        self._assert_low_land_stays_low(rows, after)

    def test_the_last_bed_fit_leaves_a_low_shore_low(self):
        _inherited, rows = _plain()
        heightmap = {
            "sample_grid": {"rows": rows.tolist(), "width": N, "height": N}, "sea_level_m": 0.0,
            "sample_spacing_x_m": SPACING, "sample_spacing_y_m": SPACING,
            "region_width_m": SPACING * (N - 1), "region_height_m": SPACING * (N - 1), "map_detail_level": 3,
        }
        fitted = rr._fit_final_channel_beds(heightmap, sea_level=0.0, inflow=None)
        self._assert_low_land_stays_low(rows, fitted["sample_grid"]["rows"])

    def test_the_last_bed_fit_deepens_no_hollow(self):
        from simulations.world_gen import regional_landforms as rl

        _inherited, rows = _plain(relief_m=3.0)
        heightmap = {
            "sample_grid": {"rows": rows.tolist(), "width": N, "height": N}, "sea_level_m": 0.0,
            "sample_spacing_x_m": SPACING, "sample_spacing_y_m": SPACING,
            "region_width_m": SPACING * (N - 1), "region_height_m": SPACING * (N - 1), "map_detail_level": 3,
        }
        fitted = np.asarray(rr._fit_final_channel_beds(heightmap, sea_level=0.0, inflow=None)["sample_grid"]["rows"])
        self.assertGreater(float(np.abs(fitted - rows).max()), 0.05)      # the fit did something
        deeper = rl.depth_under_outlet(fitted, 0.0) - rl.depth_under_outlet(rows, 0.0)
        self.assertLess(float(deeper.max()), 0.05)


class ParentContractTest(unittest.TestCase):
    """The parent contract keeps a parent cell's side, except where a landform changed it on this level's ground."""

    def _contract(self, crossed):
        # A parent cell that is land for certain.  The waves planed two cells of this level's ground to just
        # under the sea; with the same change the parent's smoother surface still stands above it.
        before = np.array([[0.7, 0.7, 3.0, 3.0]])
        after = np.array([[-0.06, -0.06, 3.0, -0.2]])                 # the last cell sank by some other step
        reference = np.array([[1.4, 1.4, 3.0, 3.0]])
        topology = [[1, 1, 1, 1]]
        if crossed:
            landforms_out = np.array([[-0.06, -0.06, 3.0, 3.0]])
            topology = rr._topology_without_landform_crossings(topology, before, landforms_out, 0.0)
        heightmap = {"sample_grid": {"rows": after.tolist()}, "sea_level_m": 0.0, "sample_spacing_x_m": 6.0}
        result, audit = rr._enforce_parent_height_contract(heightmap, reference.tolist(), topology, 5.0)
        return np.asarray(result["sample_grid"]["rows"]), audit

    def test_a_foreshore_the_waves_planed_stays_under_the_sea(self):
        blind, audit = self._contract(crossed=False)
        self.assertTrue((blind[0, :2] > 0.0).all())                  # lifted back: specks along the shoreface
        self.assertEqual(audit["topology_correction_count"], 3)
        told, audit = self._contract(crossed=True)
        np.testing.assert_allclose(told[0, :2], -0.06)
        self.assertGreater(float(told[0, 3]), 0.0)                    # what no landform did is still put right
        self.assertEqual(audit["topology_correction_count"], 1)

    def test_without_a_crossing_the_parents_certainty_is_handed_on_as_it_is(self):
        topology = [[1, -1, 0]]
        ground = np.array([[2.0, -2.0, 0.5]])
        self.assertIs(rr._topology_without_landform_crossings(topology, ground, ground + 0.3, 0.0), topology)
        self.assertIs(rr._topology_without_landform_crossings(topology, ground, ground - 3.0, None), topology)
        self.assertEqual(rr._topology_without_landform_crossings(topology, ground, ground - 3.0, 0.0), [[0, -1, 0]])


class ShoreEvolutionTest(unittest.TestCase):
    """Surface evolution's change comes back from a coarser grid; it must not dig a moat along the shore."""

    def _maps(self, smear_cells=2):
        n = 64
        x = (np.arange(n) - n // 2 + 0.5) * 40.0
        old = (0.02 * x)[None, :] * np.ones((n, 1))
        # The land lowered 12 m, the sea bed 2 m, as it comes back resampled: smeared across the shoreline.
        lowering = np.where(x >= 0.0, -12.0, -2.0)
        kernel = np.ones(2 * smear_cells + 1) / (2 * smear_cells + 1)
        smeared = np.convolve(np.pad(lowering, smear_cells, mode="edge"), kernel, mode="valid")
        return old, old + smeared[None, :] * np.ones((n, 1))

    def _evolve(self, old, new, **options):
        before = {"sample_grid": {"rows": old.tolist()}, "sample_spacing_x_m": 40.0, "sample_spacing_y_m": 40.0}
        result = rr._edge_faded_evolution(before, {"sample_grid": {"rows": new.tolist()}}, sea_level=0.0, parent_spacing_m=360.0, **options)
        return np.asarray(result["sample_grid"]["rows"])

    def test_a_blanket_smeared_across_the_shore_leaves_neither_rim_nor_moat(self):
        old, new = self._maps()
        change = self._evolve(old, new, solver_cells=2.0) - old
        self.assertLess(float(np.abs(change[8:-8, 8:-8]).max()), 0.3)

    def test_the_correction_reaches_as_far_as_the_solver_grid_smears(self):
        # A smear four cells wide: told the grids are alike, the step takes most of it for relief
        # (the moat and the rim it used to leave); told the ratio, it does not.
        old, new = self._maps(smear_cells=4)
        middle = old.shape[1] // 2
        blind = self._evolve(old, new, solver_cells=1.0) - old
        self.assertLess(float(blind[32, middle - 2]), -1.0)       # sea bed sunk beside the shore
        self.assertGreater(float(blind[32, middle + 1]), 1.0)     # land left standing behind it
        told = self._evolve(old, new, solver_cells=4.0) - old
        self.assertLess(float(np.abs(told[8:-8, 8:-8]).max()), 0.3)

    def test_relief_inside_a_parent_cell_is_kept_away_from_the_shore(self):
        old, new = self._maps()
        new[32, 32:56] -= 3.0                                       # a valley cut down the slope to the sea
        change = self._evolve(old, new, solver_cells=2.0) - old
        self.assertLess(float(change[32, 50]), -2.0)                # 18 cells inland

    def test_ground_the_shore_has_just_laid_is_left_as_it_was(self):
        from simulations.world_gen import shore_deposits as sd

        n = 64
        old = np.full((n, n), 20.0)
        old[28:34, 28:34] = 2.0                                    # a flat floor in a hollow, smaller than a parent cell
        new = old - 10.0
        new[28:34, 28:34] = 2.0 - 1.0                             # the flat erodes less than the slopes round it
        sand = np.zeros((n, n))
        sand[28:34, 28:34] = 1.5
        record = sd.with_sand_grid({"landform": sd.LANDFORM_ID}, sand)
        bare = {"sample_grid": {"rows": old.tolist()}, "sample_spacing_x_m": 40.0, "sample_spacing_y_m": 40.0}
        laid = dict(bare, regional_landforms={"landforms": [record]})
        evolved = {"sample_grid": {"rows": new.tolist()}}
        free = np.asarray(rr._edge_faded_evolution(bare, evolved, sea_level=0.0, parent_spacing_m=360.0)["sample_grid"]["rows"]) - old
        held = np.asarray(rr._edge_faded_evolution(laid, evolved, sea_level=0.0, parent_spacing_m=360.0)["sample_grid"]["rows"]) - old
        self.assertGreater(float(free[28:34, 28:34].min()), 1.0)       # raised against its surroundings
        self.assertLess(float(np.abs(held[28:34, 28:34]).max()), 1e-6)  # held
        np.testing.assert_allclose(held[50:60, 50:60], free[50:60, 50:60], atol=1e-6)   # the rest as before

    def test_evolution_wears_no_ground_down_under_its_outlet(self):
        from simulations.world_gen import regional_landforms as rl

        n = 64
        old = (70.0 - np.arange(n, dtype=float))[None, :] * np.ones((n, 1))   # a slope falling 1 m a cell eastwards
        new = old - 2.0
        new[28:34, 28:34] -= 6.0                                   # a reach that scores higher than the one below it
        bare = {"sample_grid": {"rows": old.tolist()}, "sample_spacing_x_m": 40.0, "sample_spacing_y_m": 40.0}
        evolved = {"sample_grid": {"rows": new.tolist()}}
        after = np.asarray(rr._edge_faded_evolution(bare, evolved, sea_level=0.0, parent_spacing_m=360.0)["sample_grid"]["rows"])
        self.assertLess(float(rl.depth_under_outlet(after, 0.0).max()), 0.05)
        self.assertLess(float((after - old)[28:34, 28:34].min()), -0.5)     # still worn down, as far as it drains
        # Under ice the bed is overdeepened and stays so.
        ice = np.zeros((n, n), dtype=bool)
        ice[24:38, 24:38] = True
        iced = dict(bare, surface_masks={"ice_rows": ice.tolist()})
        under = np.asarray(rr._edge_faded_evolution(iced, evolved, sea_level=0.0, parent_spacing_m=360.0)["sample_grid"]["rows"])
        self.assertGreater(float(rl.depth_under_outlet(under, 0.0).max()), 2.0)

    def test_the_solver_grid_is_read_off_the_water_cycle(self):
        heightmap = {"sample_grid": {"rows": np.zeros((241, 385)).tolist()}}
        water_cycle = {"climate_grid": {"temperature_rows_k": np.zeros((241, 257)).tolist()}}
        self.assertAlmostEqual(rr._solver_cells(heightmap, water_cycle), 385 / 257)
        self.assertEqual(rr._solver_cells(heightmap, {}), 1.0)


if __name__ == "__main__":
    unittest.main()
