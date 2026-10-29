import unittest

import numpy as np

from simulations.world_gen import rock_scarps as rs
from simulations.world_gen import scarp_canyons as sc
from simulations.world_gen.material_routing import CHANNEL_HEAD_AREA_M2

BOUNDS = {"min_u": 0.1, "max_u": 0.2, "min_v": 0.4, "max_v": 0.42}
SCARP_HEIGHT = 40.0
SCARP_COLUMN = 120
BENCH_M = 8000.0
SANDSTONE, BASALT, IGNIMBRITE = 0.46, 0.24, 0.63  # erodibility index


def _strata(cap=SANDSTONE):
    return {
        "model": rs.MODEL, "built_at_level": 2, "structure": [[0.0, 0.0], [0.0, 0.0]],
        "uv_bounds": dict(BOUNDS),
        # [base, thickness, erodibility, slope resistance]: shale, the cap (thick
        # enough that a canyon floor stays in it along the bench), shale.
        "beds": [[-100.0, 200.0, 0.89, 0.35], [100.0, 150.0, cap, 0.72], [250.0, 400.0, 0.89, 0.35]],
        "bed_materials": ["mat_shale", "mat_sandstone", "mat_shale"],
    }


def _valley(rows=61, columns=201, spacing=100.0):
    """A valley draining west along its middle row, crossed by one scarp.

    The scarp is a change of height around the valley's own ground: the
    ground below its foot sinks by half its height, the ground above its
    brink rises by as much, and both return to nothing over half a bench.
    """
    y, x = np.mgrid[0:rows, 0:columns].astype(np.float64)
    # Sides steep enough that every cell drains straight to the middle row.
    ground = 0.01 * x * spacing + 0.05 * np.abs(y - rows // 2) * spacing
    along = (x - SCARP_COLUMN) * spacing
    above = np.clip(1.0 - 2.0 * along / BENCH_M, 0.0, 1.0)
    below = np.clip(1.0 + 2.0 * along / BENCH_M, 0.0, 1.0)
    steps = 0.5 * SCARP_HEIGHT * np.where(along >= 0.0, above, -below)
    u, v = rs._uv_grids(BOUNDS, ground.shape)
    return ground, steps, np.ones(ground.shape, dtype=bool), u, v, spacing


def _cut(cap=SANDSTONE, **shape):
    ground, steps, land, u, v, spacing = _valley(**shape)
    change, floor, record = sc.cut_canyons(ground, steps, land, _strata(cap), u=u, v=v, dx=spacing, dy=spacing)
    return ground, steps, change, floor, record


class RetreatLawTest(unittest.TestCase):
    def test_a_river_retreats_kilometres_and_a_channel_head_about_one(self):
        self.assertAlmostEqual(float(sc.retreat_distance_m(CHANNEL_HEAD_AREA_M2)), 1310.0, delta=40.0)
        self.assertGreater(float(sc.retreat_distance_m(1.0e8)), 20_000.0)
        self.assertLess(float(sc.retreat_distance_m(1.0e8)), 26_000.0)

    def test_the_strongest_bed_between_floor_and_rim_sets_the_pace(self):
        factors = sc.rock_retreat_factors(_strata(BASALT))
        self.assertAlmostEqual(float(factors[1, 1]), 10.0 ** ((BASALT - SANDSTONE) / 0.455), places=6)
        # Through shale and the cap the cap decides; in shale alone the retreat is as fast as it gets.
        self.assertEqual(factors[0, 2], factors[1, 1])
        self.assertEqual(factors[2, 0], factors[1, 1])
        self.assertEqual(float(factors[0, 0]), sc.RETREAT_ROCK_FACTOR[1])
        self.assertAlmostEqual(float(sc.rock_retreat_factors(_strata())[1, 1]), 1.0, places=6)


class CanyonCutTest(unittest.TestCase):
    def test_the_stream_keeps_the_level_of_the_bench_below_the_scarp(self):
        ground, steps, change, floor, record = _cut()
        middle = ground.shape[0] // 2
        cut = ground + steps + change
        # Just above the brink the canyon is as deep as the scarp is high and
        # its floor continues the foot of the scarp.
        self.assertAlmostEqual(float(-change[middle, SCARP_COLUMN]), SCARP_HEIGHT, delta=1.5)
        self.assertLess(abs(float(cut[middle, SCARP_COLUMN] - cut[middle, SCARP_COLUMN - 1])), 1.5)
        self.assertTrue(bool(floor[middle, SCARP_COLUMN]))
        # Never deeper than the scarp it cut through, and it only removes rock.
        self.assertLessEqual(float(-change.min()), SCARP_HEIGHT + 1e-9)
        self.assertLessEqual(float(change.max()), 0.0)
        # The floor never rises downstream.
        bed = cut[middle, SCARP_COLUMN - 5:SCARP_COLUMN + 30]
        self.assertTrue(bool(np.all(np.diff(bed) >= -1e-9)))
        self.assertEqual(record["landform"], sc.LANDFORM_ID)
        self.assertEqual(record["canyon_count"], 1)
        self.assertAlmostEqual(record["max_depth_m"], SCARP_HEIGHT, delta=1.5)

    def test_the_valley_sides_keep_their_scarp(self):
        # Cells small enough that no rill on the valley side gathers a stream's catchment.
        ground, _steps, change, floor, _record = _cut(spacing=50.0)
        middle = ground.shape[0] // 2
        # The stream wanders a cell or two about the valley line (routing micro-relief).
        sides = np.ones(ground.shape, dtype=bool)
        sides[middle - 3:middle + 4] = False
        self.assertEqual(float(np.abs(change[sides]).max()), 0.0)
        self.assertFalse(bool(floor[sides].any()))

    def test_below_the_scarp_nothing_is_cut(self):
        _ground, _steps, change, _floor, _record = _cut()
        self.assertEqual(float(np.abs(change[:, :SCARP_COLUMN]).max()), 0.0)

    def test_a_larger_catchment_cuts_further_and_ends_in_a_headwall(self):
        lengths = []
        for rows in (11, 41):
            ground, steps, change, _floor, record = _cut(BASALT, rows=rows)
            middle = rows // 2
            canyon = np.flatnonzero(change[middle] < 0.0)
            lengths.append(record["longest_m"])
            # Retreat ran out on the bench: the stream still falls into its canyon.
            self.assertLess(canyon.max(), SCARP_COLUMN + 0.5 * BENCH_M / 100.0)
            self.assertGreater(float(-change[middle, canyon.max()]), 0.5 * SCARP_HEIGHT)
            self.assertEqual(float(change[middle, canyon.max() + 1]), 0.0)
        self.assertGreater(lengths[0], 500.0)
        self.assertGreater(lengths[1], 1.5 * lengths[0])

    def test_soft_cap_rock_is_cut_back_further_than_hard(self):
        hard = _cut(BASALT, rows=21)[4]["longest_m"]
        soft = _cut(IGNIMBRITE, rows=21)[4]["longest_m"]
        self.assertGreater(soft, 2.0 * hard)

    def test_without_a_stream_the_scarp_stays_whole(self):
        ground, steps, land, u, v, _spacing = _valley(rows=21, columns=51)
        change, floor, record = sc.cut_canyons(ground, steps, land, _strata(), u=u, v=v, dx=20.0, dy=20.0)
        self.assertIsNone(change)
        self.assertIsNone(floor)
        self.assertEqual(record["canyon_count"], 0)

    def test_a_tile_without_steps_has_no_canyons(self):
        ground, steps, land, u, v, spacing = _valley()
        change, _floor, record = sc.cut_canyons(ground, np.zeros_like(steps), land, _strata(), u=u, v=v, dx=spacing, dy=spacing)
        self.assertIsNone(change)
        self.assertEqual(record["canyon_count"], 0)

    def test_a_canyon_fades_out_at_the_tile_rim(self):
        ground, steps, land, u, v, spacing = _valley()
        fade = np.ones(ground.shape)
        fade[:, -12:] = np.linspace(1.0, 0.0, 12)[None, :]
        change, _floor, _record = sc.cut_canyons(ground, steps, land, _strata(), u=u, v=v, dx=spacing, dy=spacing, fade=fade)
        self.assertEqual(float(np.abs(change[:, -1]).max()), 0.0)

    def test_a_river_has_a_floor_as_wide_as_its_bankfull_channel(self):
        ground, steps, land, u, v, spacing = _valley(spacing=10.0)
        middle = ground.shape[0] // 2
        inflow = np.zeros(ground.shape)
        inflow[middle, -1] = 1.0e9 / (spacing * spacing)  # a river of 1,000 km2 enters in the east
        discharge = {"runoff_m_s": 0.3 / 31_557_600.0, "bankfull_ratio": 5.0, "silt_clay_percent": 10.0, "gravity_m_s2": 9.81}
        arguments = dict(u=u, v=v, dx=spacing, dy=spacing, inflow_cells=inflow)
        _change, narrow, _record = sc.cut_canyons(ground, steps, land, _strata(), **arguments)
        change, floor, record = sc.cut_canyons(ground, steps, land, _strata(), discharge=discharge, **arguments)
        column = SCARP_COLUMN + 3
        # Without a discharge the floor is the stream's own cell.
        self.assertEqual(int(narrow[:, column].sum()), 1)
        across = np.flatnonzero(floor[:, column])
        self.assertGreater(across.size, 2)
        self.assertAlmostEqual(across.size * spacing, record["widest_floor_m"], delta=2.5 * spacing)
        # Cut as deep as the stream itself all the way across: the valley
        # sides beside the belt are lowered with it, not planed off to its level.
        lowering = -change[across, column]
        self.assertLess(float(lowering.max() - lowering.min()), 1.0)
        self.assertGreater(float(lowering.min()), 0.8 * SCARP_HEIGHT)


class ClearedFloorTest(unittest.TestCase):
    def test_walls_lie_back_while_the_stream_keeps_its_floor(self):
        surface = np.full((41, 41), 100.0)
        surface[:, 20] = 0.0
        held = np.zeros(surface.shape, dtype=bool)
        held[:, 20] = True
        limit = np.full(surface.shape, 0.7)
        rested = rs.relax_to_strength(surface, limit, 10.0, 10.0, iterations=4000, held=held)
        self.assertEqual(float(np.abs(rested[held]).max()), 0.0)
        self.assertLess(float(np.abs(np.diff(rested[20])).max()), 0.7 * 10.0 * 1.05)
        # A V in weak rock: the rim stands back by about the depth over the gradient.
        self.assertLess(float(rested[20, 14]), 99.0)
        self.assertGreater(float(rested[20, 2]), 99.9)


if __name__ == "__main__":
    unittest.main()
