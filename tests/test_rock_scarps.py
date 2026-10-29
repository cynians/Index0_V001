import math
import unittest

import numpy as np

from simulations.world_gen import rock_scarps as rs

WEAK, BASALT, LIMESTONE = 0.34, 0.76, 0.72  # slope resistance of the ontology's rock classes
BOUNDS = {"min_u": 0.1, "max_u": 0.2, "min_v": 0.4, "max_v": 0.42}
LAYERED = [("mat_shale", 0.5, 0.72, WEAK), ("mat_limestone", 0.3, 0.38, LIMESTONE), ("mat_basalt", 0.2, 0.35, BASALT)]


def _strata(exposure=1.0, rampart=0.65, beds=None, **extra):
    return {
        "model": rs.MODEL, "built_at_level": 2, "structure": [[0.0, 0.0], [0.0, 0.0]],
        "uv_bounds": {"min_u": 0.0, "max_u": 1.0, "min_v": 0.0, "max_v": 1.0},
        "exposure": exposure, "rampart_gradient": rampart, "talus_gradient": rs.TALUS_GRADIENT,
        # [base, thickness, erodibility, slope resistance]: weak, strong, weak, strong, weak.
        "beds": beds or [
            [0.0, 200.0, 0.72, WEAK], [200.0, 100.0, 0.35, BASALT], [300.0, 300.0, 0.72, WEAK],
            [600.0, 100.0, 0.38, LIMESTONE], [700.0, 300.0, 0.72, WEAK],
        ],
        "bed_materials": ["mat_shale", "mat_basalt", "mat_shale", "mat_limestone", "mat_shale"],
        **extra,
    }


def _profile(strata, slope, samples=400_001):
    """Stepped heights of a uniform slope crossing the whole sequence, with gradients and parts."""
    transfer = rs.scarp_transfer(strata)
    smooth = np.linspace(0.0, 1000.0, samples)
    stepped = rs.step(smooth, 1.0, np.full(smooth.shape, slope), transfer)
    run = (smooth[1] - smooth[0]) / slope
    middle = 0.5 * (stepped[1:] + stepped[:-1])
    return smooth, stepped, np.diff(stepped) / run, rs.profile_part(middle, transfer), transfer


class FaceStrengthTest(unittest.TestCase):
    def test_a_face_is_as_steep_as_its_rock_is_strong(self):
        self.assertEqual(rs.face_gradient(WEAK), 0.0)  # shale, weak sandstone: a slope former
        self.assertEqual(rs.face_gradient(0.25), 0.0)  # evaporites
        angles = [math.degrees(math.atan(rs.face_gradient(value))) for value in (0.67, LIMESTONE, BASALT, 0.86)]
        self.assertEqual(angles, sorted(angles))
        self.assertGreater(angles[0], 50.0)
        self.assertLess(angles[-1], 86.0)

    def test_a_dry_climate_bares_the_face_and_keeps_the_rampart_steep(self):
        humid_exposure, humid_rampart = rs.climate_parameters(0.0)
        arid_exposure, arid_rampart = rs.climate_parameters(1.0)
        self.assertLess(humid_exposure, 0.5)
        self.assertEqual(arid_exposure, 1.0)
        self.assertLess(humid_rampart, arid_rampart)
        self.assertLessEqual(arid_rampart, rs.TALUS_GRADIENT)


class ScarpProfileTest(unittest.TestCase):
    def test_face_and_rampart_stand_at_their_own_angles_whatever_the_slope(self):
        strata = _strata()
        for slope in (0.02, 0.05, 0.2):
            _smooth, _stepped, gradient, part, _transfer = _profile(strata, slope)
            face = np.median(gradient[part == rs.FACE])
            # Two strong beds: basalt and limestone faces, both far above the talus rule.
            self.assertGreater(face, 0.9 * rs.face_gradient(LIMESTONE))
            self.assertLess(face, 1.1 * rs.face_gradient(BASALT))
            self.assertAlmostEqual(float(np.median(gradient[part == rs.RAMPART])), 0.65, delta=0.02)
            # The bench takes the rest of the run and is the gentlest part.
            self.assertLess(float(np.median(gradient[part == rs.BENCH])), slope)
            self.assertGreater(float((part == rs.BENCH).mean()), 0.6)

    def test_a_gentle_slope_is_mostly_bench_and_a_steep_one_mostly_scarp(self):
        strata = _strata()
        bench_share = [float((_profile(strata, slope)[3] == rs.BENCH).mean()) for slope in (0.02, 0.2, 0.6)]
        self.assertGreater(bench_share[0], 0.97)
        self.assertEqual(bench_share, sorted(bench_share, reverse=True))
        self.assertLess(bench_share[2], 0.6)

    def test_ground_steeper_than_the_profile_steepens_all_of_it(self):
        _smooth, stepped, gradient, part, _transfer = _profile(_strata(), 1.5)
        self.assertTrue(np.all(np.diff(stepped) > 0.0))
        self.assertGreater(float(np.median(gradient[part == rs.RAMPART])), 0.65)
        self.assertGreater(float(np.median(gradient[part == rs.FACE])), rs.face_gradient(LIMESTONE))

    def test_a_scarp_keeps_the_mean_height_of_the_slope_it_is_cut_into(self):
        # A scarp runs from the middle of the bench below it to the middle of
        # the bench above; the stepped surface meets the smooth one at both
        # ends and the ground it raises equals the ground it lowers.
        for slope in (0.02, 0.08, 0.3):
            smooth, stepped, _gradient, _part, transfer = _profile(_strata(), slope, samples=200_001)
            bounds, heights = transfer["unit_real"], transfer["unit_height_m"]
            self.assertEqual(int((heights > 0.0).sum()), 2)
            for low, high, height in zip(bounds[:-1], bounds[1:], heights):
                self.assertAlmostEqual(float(np.interp(low, smooth, stepped)), low, delta=0.05)
                if height <= 0.0:
                    continue
                inside = (smooth >= low) & (smooth <= high)
                residual = stepped[inside] - smooth[inside]
                self.assertLess(abs(float(residual.mean())), 0.03 * height)
                self.assertGreater(float(residual.max()), 0.1 * height)
                self.assertLess(float(residual.min()), -0.1 * height)
                self.assertLessEqual(float(np.abs(residual).max()), height)

    def test_a_sequence_without_a_strong_bed_is_not_stepped(self):
        strata = _strata(beds=[[0.0, 400.0, 0.72, WEAK], [400.0, 600.0, 0.82, 0.25]])
        smooth, stepped, _gradient, part, _transfer = _profile(strata, 0.05, samples=2001)
        np.testing.assert_allclose(stepped, smooth, atol=1e-9)
        self.assertTrue(np.all(part == rs.BENCH))

    def test_a_humid_scarp_banks_most_of_its_face_with_talus(self):
        exposure, rampart = rs.climate_parameters(0.0)
        _smooth, stepped, gradient, part, _transfer = _profile(_strata(exposure, rampart), 0.05)
        middle = 0.5 * (stepped[1:] + stepped[:-1])
        basalt = (middle > 200.0) & (middle < 300.0)
        rise = np.diff(stepped)
        self.assertAlmostEqual(float(rise[basalt & (part == rs.FACE)].sum()), 100.0 * exposure, delta=1.0)
        self.assertAlmostEqual(float(rise[basalt & (part == rs.TALUS)].sum()), 100.0 * (1.0 - exposure), delta=1.0)
        self.assertAlmostEqual(float(np.median(gradient[part == rs.TALUS])), rs.TALUS_GRADIENT, delta=0.02)
        self.assertAlmostEqual(float(np.median(gradient[part == rs.RAMPART])), rampart, delta=0.02)

    def test_the_smooth_surface_behind_the_steps_is_recovered(self):
        transfer = rs.scarp_transfer(_strata())
        smooth = np.linspace(20.0, 980.0, 400)
        slope = np.full(smooth.shape, 0.04)
        stepped = rs.step(smooth, 1.0, slope, transfer)
        np.testing.assert_allclose(rs.unstep(stepped, 1.0, slope, transfer), smooth, atol=0.01)
        # Half weight is half the remap, and still inverts.
        half = rs.step(smooth, 0.5, slope, transfer)
        np.testing.assert_allclose(half, 0.5 * (smooth + stepped), atol=1e-9)
        np.testing.assert_allclose(rs.unstep(half, 0.5, slope, transfer), smooth, atol=0.01)

    def test_weak_beds_make_one_slope_and_each_strong_rock_its_own_cliff(self):
        strata = _strata(beds=[
            [0.0, 100.0, 0.72, WEAK], [100.0, 100.0, 0.88, WEAK],
            [200.0, 60.0, 0.35, BASALT], [260.0, 40.0, 0.35, BASALT], [300.0, 80.0, 0.38, LIMESTONE],
            [380.0, 200.0, 0.72, WEAK],
        ])
        strata["bed_materials"] = ["mat_shale", "mat_mudstone", "mat_basalt", "mat_basalt", "mat_limestone", "mat_shale"]
        units = rs.scarp_units(strata)
        # Shale on mudstone: one slope.  Two basalt flows: one cliff.  Limestone on basalt: a ledge between.
        self.assertEqual([(unit[0], unit[1]) for unit in units], [(0.0, 200.0), (200.0, 300.0), (300.0, 380.0), (380.0, 580.0)])
        self.assertEqual([unit[3] for unit in units[1:3]], ["mat_basalt", "mat_limestone"])
        self.assertAlmostEqual(units[1][2], rs.face_gradient(BASALT))
        self.assertAlmostEqual(units[2][2], rs.face_gradient(LIMESTONE))
        _smooth, stepped, gradient, part, _transfer = _profile(strata, 0.05)
        middle = 0.5 * (stepped[1:] + stepped[:-1])
        ledge = (middle > 300.0) & (middle < 300.0 + rs.MIN_BENCH_RISE_SHARE * 80.0)
        self.assertTrue(np.all(part[ledge] == rs.BENCH))
        self.assertLess(float(np.median(gradient[ledge])), 0.05)


class RockfallTest(unittest.TestCase):
    """Nothing stands steeper than its rock holds (``relax_to_strength``)."""

    def test_an_overhanging_step_fails_to_the_strength_angle_and_keeps_its_volume(self):
        x = np.arange(200) * 0.5
        wall = np.where(x < 50.0, 20.0, 0.0)[None, :] * np.ones((5, 1))  # a vertical 20 m step
        limit = np.full(wall.shape, 2.0)
        rested = rs.relax_to_strength(wall, limit, 0.5, 0.5, iterations=4000)
        steepest = float(np.abs(np.diff(rested, axis=1)).max()) / 0.5
        self.assertLess(steepest, 2.0 * 1.1)
        self.assertGreater(steepest, 1.5)
        self.assertAlmostEqual(float(rested.sum()), float(wall.sum()), delta=1e-6 * wall.size)
        # Ground that holds is not touched, and ground without a limit is left alone.
        ramp = (20.0 - 0.3 * x)[None, :] * np.ones((5, 1))
        np.testing.assert_allclose(rs.relax_to_strength(ramp, limit, 0.5, 0.5), ramp)
        np.testing.assert_allclose(rs.relax_to_strength(wall, np.full(wall.shape, np.inf), 0.5, 0.5), wall)

    def test_a_cone_comes_to_rest_about_as_steep_in_every_direction(self):
        y, x = np.mgrid[-60:61, -60:61] * 0.25
        cone = np.maximum(0.0, 6.0 - 3.0 * np.hypot(x, y))  # 72 degrees
        rested = rs.relax_to_strength(cone, np.full(cone.shape, 1.0), 0.25, 0.25, iterations=8000)
        along = float(np.abs(np.diff(rested[60, 60:])).max()) / 0.25
        diagonal = float(np.abs(np.diff(np.diagonal(rested)[60:])).max()) / (0.25 * 2.0 ** 0.5)
        self.assertLess(along, 1.15)
        self.assertLess(diagonal, 1.15)
        self.assertGreater(min(along, diagonal), 0.7)
        self.assertLess(abs(along - diagonal), 0.25)
        self.assertAlmostEqual(float(rested.sum()), float(cone.sum()), delta=1e-6 * cone.size)

    def test_weak_rock_lies_back_further_than_strong_rock(self):
        x = np.arange(200) * 0.5
        wall = np.where(x < 50.0, 20.0, 0.0)[None, :] * np.ones((5, 1))
        strong = rs.relax_to_strength(wall, np.full(wall.shape, 2.4), 0.5, 0.5, iterations=4000)
        weak = rs.relax_to_strength(wall, np.full(wall.shape, 0.5), 0.5, 0.5, iterations=20000)
        width = lambda rows: float(((rows[2] > 0.5) & (rows[2] < 19.5)).sum()) * 0.5  # noqa: E731
        self.assertGreater(width(weak), 3.0 * width(strong))


class RockfallRoundsTest(unittest.TestCase):
    """The rock a slope stands in changes as it lies back (``rockfall``)."""

    def _slot(self):
        """A plateau on the basalt cap with a slot cut 150 m down into the shale under it."""
        strata = _strata(
            weight=[[1.0, 1.0], [1.0, 1.0]], slope=[[0.02, 0.02], [0.02, 0.02]], uv_bounds=dict(BOUNDS),
            beds=[[0.0, 200.0, 0.72, WEAK], [200.0, 100.0, 0.35, BASALT], [300.0, 300.0, 0.72, WEAK]],
        )
        strata["bed_materials"] = ["mat_shale", "mat_basalt", "mat_shale"]
        surface = np.full((41, 121), 290.0)  # in the cap, ten metres under its top
        surface[:, 60] = 140.0
        held = np.zeros(surface.shape, dtype=bool)
        held[:, 60] = True
        u, v = rs._uv_grids(BOUNDS, surface.shape)
        return strata, surface, held, u, v

    def test_a_wall_cut_through_the_cap_lies_back_in_the_weak_bed_under_it(self):
        strata, surface, held, u, v = self._slot()
        spacing = 10.0
        # Read once from the plateau, every cell is cap rock: the slot keeps walls no weak rock holds.
        once = rs.relax_to_strength(surface, rs.strength_limit(surface, [strata], u, v), spacing, spacing, held=held)
        rested = rs.rockfall(surface, [strata], u, v, spacing, spacing, held=held)
        row = rested[20]
        np.testing.assert_allclose(row[60], 140.0)
        weak = max(0.70, strata["rampart_gradient"] * rs.FAILURE_MARGIN)
        cap = rs.face_gradient(BASALT) * rs.FAILURE_MARGIN
        gradient = np.abs(np.diff(row)) / spacing
        upper = np.maximum(row[1:], row[:-1])  # the upper cell's rock decides
        # In the cap the wall stands at what basalt holds; below the cap's
        # base it lies at about what shale holds (the kink between the two
        # and the foot at the stream are rounded over a cell by the spread).
        self.assertLess(float(gradient[upper >= 199.0].max()), cap * 1.1)
        self.assertGreater(float(gradient[upper >= 199.0].max()), 0.8 * cap)
        slope = (row[:60] > 150.0) & (row[:60] < 190.0)
        cells = np.flatnonzero(slope)
        lying = float(row[cells[0]] - row[cells[-1]]) / (spacing * (cells[-1] - cells[0]))
        self.assertGreater(lying, 0.75 * weak)
        self.assertLess(lying, 1.3 * weak)
        self.assertLess(lying, 0.4 * float(gradient[upper >= 199.0].max()))
        # The canyon is half as wide again as the slot the single reading left:
        # a cliff in the cap over slopes in the shale.
        width = lambda values: int((values < 285.0).sum())  # noqa: E731
        self.assertGreater(width(row), 1.4 * width(once[20]))
        self.assertGreater(width(row) * spacing, 2.0 * (195.0 - 140.0) / weak)

    def test_ground_that_holds_is_left_alone(self):
        strata, surface, _held, u, v = self._slot()
        plateau = np.full(surface.shape, 290.0)
        np.testing.assert_allclose(rs.rockfall(plateau, [strata], u, v, 10.0, 10.0), plateau)


class RunGateTest(unittest.TestCase):
    """A level builds a scarp only where its whole run fits inside the parent's cells."""

    def test_a_scarp_wider_than_the_parents_cells_is_left_to_the_parent(self):
        # The basalt scarp is 307.5 m high: its run is 307.5 m / slope.
        strata = _strata(parent_spacing_m=5_000.0)
        transfer = rs.scarp_transfer(strata)
        basalt = np.array([200.0])
        built = [float(rs.run_gate(basalt, np.array([slope]), transfer)[0]) for slope in (0.012, 0.022, 0.035, 0.2)]
        self.assertEqual(built[0], 0.0)   # 26 km of run: five parent cells
        self.assertGreater(built[1], 0.0)
        self.assertLess(built[1], 1.0)    # between two and four cells: fading in
        self.assertEqual(built[2], 1.0)   # 8.8 km: inside two parent cells
        self.assertEqual(built[3], 1.0)
        smooth = np.linspace(0.0, 1000.0, 4001)
        plain = rs.step(smooth, 1.0, np.full(smooth.shape, 0.005), transfer)
        np.testing.assert_allclose(plain, smooth, atol=1e-9)  # a plain across the beds stays a plain

    def test_a_gated_scarp_still_inverts(self):
        transfer = rs.scarp_transfer(_strata(parent_spacing_m=5_000.0))
        smooth = np.linspace(20.0, 980.0, 600)
        slope = np.full(smooth.shape, 0.022)
        stepped = rs.step(smooth, 1.0, slope, transfer)
        self.assertGreater(float(np.abs(stepped - smooth).max()), 10.0)
        np.testing.assert_allclose(rs.unstep(stepped, 1.0, slope, transfer), smooth, atol=0.01)


class BedSequenceTest(unittest.TestCase):
    def test_two_tiles_of_one_parent_cut_the_same_beds(self):
        first = rs.bed_sequence("seed", 3, 100.0, 380.0, LAYERED)
        second = rs.bed_sequence("seed", 3, 250.0, 900.0, LAYERED)
        common = {round(bed[0], 6): bed for bed in first}
        shared = [bed for bed in second if round(bed[0], 6) in common]
        self.assertGreater(len(shared), 5)
        for bed in shared:
            self.assertEqual(common[round(bed[0], 6)], bed)
        # The planet's stack: thicknesses vary about the order's nominal value.
        nominal = rs.BED_THICKNESS_LADDER_M[rs.BED_ORDER[3]]
        thickness = [bed[1] for bed in first]
        self.assertGreater(min(thickness), 0.0)
        self.assertGreater(float(np.median(thickness)), 0.3 * nominal)
        self.assertLess(float(np.median(thickness)), 2.5 * nominal)
        self.assertGreater(max(thickness) / min(thickness), 2.0)
        # The sequence has no gaps.
        for lower, upper in zip(first, first[1:]):
            self.assertAlmostEqual(lower[0] + lower[1], upper[0], places=6)

    def test_a_finer_bed_is_mostly_the_rock_of_the_coarser_bed_it_lies_in(self):
        coarser = {
            "beds": [[0.0, 400.0, 0.38, LIMESTONE], [400.0, 400.0, 0.72, WEAK]],
            "bed_materials": ["mat_limestone", "mat_shale"],
        }
        beds = rs.bed_sequence("seed", 3, 0.0, 799.0, LAYERED, coarser=coarser)
        lower = [bed[2] for bed in beds if bed[0] + 0.5 * bed[1] < 400.0]
        upper = [bed[2] for bed in beds if 400.0 <= bed[0] + 0.5 * bed[1] < 800.0]
        # Limestone is 30 % and shale 50 % of the whole sequence.
        self.assertGreater(lower.count("mat_limestone") / len(lower), 0.5)
        self.assertGreater(upper.count("mat_shale") / len(upper), 0.62)
        self.assertLess(upper.count("mat_limestone") / len(upper), 0.3)
        self.assertIn("mat_shale", lower)  # partings


class BuildAndRestepTest(unittest.TestCase):
    def _valley_side(self, slope, spacing=40.0, shape=(81, 401)):
        """A tile whose ground falls ``slope`` from west to east."""
        height, width = shape
        east = np.arange(width) * spacing
        return 3000.0 - slope * east[None, :] * np.ones((height, 1)), spacing

    def _build(self, slope, aridity=1.0, level=3, parent_spacing=240.0, **tile):
        elevation, spacing = self._valley_side(slope, **tile)
        land = np.ones(elevation.shape, dtype=bool)
        residual, strata = rs.build_order(
            elevation, land, level=level, layered=LAYERED, layered_share=1.0, aridity=aridity, seed_text="seed",
            bounds=BOUNDS, dx=spacing, dy=spacing, parent_spacing_m=parent_spacing,
        )
        return elevation, residual, strata, spacing

    def test_a_steep_valley_side_breaks_into_cliffs_and_a_plain_does_not(self):
        elevation, residual, strata, spacing = self._build(0.25)
        self.assertEqual(strata["built_at_level"], 3)
        self.assertEqual(len(strata["bed_materials"]), len(strata["beds"]))
        stepped = elevation + residual
        steepest = float(np.abs(np.diff(stepped[40], axis=0)).max()) / spacing
        self.assertGreater(steepest, 2.0 * 0.25)
        # Mean height is kept at the parent's scale without any correction.
        self.assertLess(abs(float(residual[:, 40:-40].mean())), 0.5)
        _plain, flat_residual, _strata, _spacing = self._build(0.004)
        self.assertLess(float(np.abs(flat_residual).max()), 1e-6)

    def test_levels_without_an_order_and_unlayered_ground_build_nothing(self):
        elevation, spacing = self._valley_side(0.25)
        land = np.ones(elevation.shape, dtype=bool)
        arguments = dict(layered_share=1.0, aridity=1.0, seed_text="seed", bounds=BOUNDS, dx=spacing, dy=spacing, parent_spacing_m=240.0)
        self.assertEqual(rs.build_order(elevation, land, level=6, layered=LAYERED, **arguments), (None, None))
        self.assertEqual(rs.build_order(elevation, land, level=3, layered=[], **arguments), (None, None))

    def test_a_finer_level_steps_the_scarps_again_and_keeps_the_parents_heights(self):
        from simulations.world_gen.regional_refinement import _sample_bicubic_grid

        elevation, residual, strata, spacing = self._build(0.25)
        parent = elevation + residual
        parent_heightmap = {
            "sample_grid": {"rows": parent.tolist()},
            "source_uv_bounds": dict(BOUNDS),
            "regional_landforms": {"landforms": [{"landform": rs.LANDFORM_ID, "strata": strata}]},
        }
        # Child: five times finer over the middle of the parent.
        rows, columns = np.arange(30, 51), np.arange(150, 251)
        child_u = BOUNDS["min_u"] + (BOUNDS["max_u"] - BOUNDS["min_u"]) * np.linspace(columns[0], columns[-1], 501) / 400.0
        child_v = BOUNDS["min_v"] + (BOUNDS["max_v"] - BOUNDS["min_v"]) * np.linspace(rows[0], rows[-1], 101) / 80.0
        u = child_u[None, :] * np.ones((101, 1))
        v = child_v[:, None] * np.ones((1, 501))
        local_u = (u - BOUNDS["min_u"]) / (BOUNDS["max_u"] - BOUNDS["min_u"])
        local_v = (v - BOUNDS["min_v"]) / (BOUNDS["max_v"] - BOUNDS["min_v"])
        inherited = _sample_bicubic_grid(parent, local_u, local_v, wrap_x=False)
        change, orders = rs.restep(parent_heightmap, u, v, inherited, level=4)
        self.assertEqual(len(orders), 1)
        sharpened = inherited + change
        child_spacing = spacing / 5.0
        before = float(np.abs(np.diff(inherited[50])).max()) / child_spacing
        after = float(np.abs(np.diff(sharpened[50])).max()) / child_spacing
        self.assertGreater(after, 1.5 * before)
        self.assertGreater(after, 0.84)  # a cliff by the talus rule
        # Parent sample points (every 5th child cell) are met at least as well
        # as plain interpolation meets them, and away from faces the child is
        # that interpolation: only faces are sharpened.
        nodes = parent[np.ix_(rows, columns)]
        self.assertLessEqual(
            float(np.abs(sharpened[::5, ::5] - nodes).max()), float(np.abs(inherited[::5, ::5] - nodes).max()) + 0.05)
        self.assertGreater(float((np.abs(change) > 0.5).mean()), 0.02)
        # Three levels below the one that built it, an order is left alone.
        self.assertEqual(rs.restep(parent_heightmap, u, v, inherited, level=6), (None, []))
        self.assertEqual(rs.restep(parent_heightmap, u, v, inherited, level=6, with_steps=True), (None, [], []))

    def test_a_finer_level_can_read_what_the_scarps_add_to_the_ground(self):
        from simulations.world_gen.regional_refinement import _sample_bicubic_grid

        elevation, residual, strata, _spacing = self._build(0.25)
        parent = elevation + residual
        parent_heightmap = {
            "sample_grid": {"rows": parent.tolist()},
            "source_uv_bounds": dict(BOUNDS),
            "regional_landforms": {"landforms": [{"landform": rs.LANDFORM_ID, "strata": strata}]},
        }
        local_u = np.linspace(150, 250, 501)[None, :] / 400.0 * np.ones((101, 1))
        local_v = np.linspace(30, 50, 101)[:, None] / 80.0 * np.ones((1, 501))
        u = BOUNDS["min_u"] + (BOUNDS["max_u"] - BOUNDS["min_u"]) * local_u
        v = BOUNDS["min_v"] + (BOUNDS["max_v"] - BOUNDS["min_v"]) * local_v
        inherited = _sample_bicubic_grid(parent, local_u, local_v, wrap_x=False)
        plain = rs.restep(parent_heightmap, u, v, inherited, level=4)
        change, orders, steps = rs.restep(parent_heightmap, u, v, inherited, level=4, with_steps=True)
        np.testing.assert_allclose(change, plain[0])
        self.assertEqual(len(steps), len(orders))
        # The parent's own change of height, seen at the child's cells: the same
        # range, positive above a brink and negative below a foot, about nothing on average.
        built = residual[30:51, 150:251]
        self.assertAlmostEqual(float(steps[0].max()), float(built.max()), delta=0.25 * float(built.max()))
        self.assertAlmostEqual(float(steps[0].min()), float(built.min()), delta=0.25 * float(-built.min()))
        self.assertLess(abs(float(steps[0].mean())), 0.1 * float(built.max()))
        # Without them the ground is the valley side again: no cliff left in it.
        stepped = inherited + change
        ground = stepped - steps[0]
        self.assertLess(float(np.abs(np.diff(ground[50])).max()), 0.5 * float(np.abs(np.diff(stepped[50])).max()))

    def test_only_a_face_is_sharpened(self):
        from simulations.world_gen.regional_refinement import _sample_bicubic_grid

        # One basalt bed (1000-1020 m) between two shale beds, on the same valley side;
        # the rest of the slope is in no bed at all.
        elevation, _residual, strata, spacing = self._build(0.25)
        strata = dict(strata, parent_spacing_m=1000.0,
                      beds=[[900.0, 100.0, 0.89, WEAK], [1000.0, 20.0, 0.24, BASALT], [1020.0, 80.0, 0.89, WEAK]],
                      bed_materials=["mat_shale", "mat_basalt", "mat_shale"])
        u, v = rs._uv_grids(BOUNDS, elevation.shape)
        dip, weight, slope = rs.record_fields(strata, u, v)
        parent = rs.step(elevation - dip, weight, slope, rs.scarp_transfer(strata)) + dip
        parent_heightmap = {
            "sample_grid": {"rows": parent.tolist()}, "source_uv_bounds": dict(BOUNDS),
            "regional_landforms": {"landforms": [{"landform": rs.LANDFORM_ID, "strata": strata}]},
        }
        child_u = BOUNDS["min_u"] + (BOUNDS["max_u"] - BOUNDS["min_u"]) * np.linspace(0.0, 1.0, 5 * 400 + 1)
        child_v = BOUNDS["min_v"] + (BOUNDS["max_v"] - BOUNDS["min_v"]) * np.linspace(0.4, 0.6, 81)
        cu = child_u[None, :] * np.ones((81, 1))
        cv = child_v[:, None] * np.ones((1, child_u.size))
        inherited = _sample_bicubic_grid(
            parent, (cu - BOUNDS["min_u"]) / (BOUNDS["max_u"] - BOUNDS["min_u"]), (cv - BOUNDS["min_v"]) / (BOUNDS["max_v"] - BOUNDS["min_v"]), wrap_x=False)
        change, _orders = rs.restep(parent_heightmap, cu, cv, inherited, level=4)
        touched = np.abs(change[40]) > 1e-9
        east = np.arange(child_u.size) * spacing / 5.0
        bed_at_east = (3000.0 - 1010.0) / 0.25  # where the slope crosses the basalt
        self.assertTrue(touched.any())
        self.assertLess(float(np.abs(east[touched] - bed_at_east).max()), 600.0)
        self.assertGreater(float(np.abs(change[40]).max()), 2.0)

    def test_every_layer_can_read_where_the_face_is(self):
        elevation, residual, strata, spacing = self._build(0.25)
        heightmap = {
            "sample_grid": {"rows": (elevation + residual).tolist()},
            "source_uv_bounds": dict(BOUNDS),
            "regional_landforms": {"landforms": [{"landform": rs.LANDFORM_ID, "strata": strata}]},
        }
        # Without a lattice spacing a cell is its sample point: whole parts.
        fields = rs.heightmap_scarp_fields(heightmap)
        face = fields["face"] > 0.5
        self.assertTrue(face.any())
        rock = np.asarray(fields["rock_materials"] + [None], dtype=object)[fields["rock"]]
        strong = np.isin(rock[face].astype(str), ["mat_basalt", "mat_limestone"])
        self.assertGreater(float(strong.mean()), 0.99)  # (a cell exactly on a bed boundary aside)
        rampart = fields["rampart"] > 0.5
        self.assertTrue(rampart.any())
        self.assertGreater(float((rock[rampart].astype(str) == "mat_shale").mean()), 0.99)
        self.assertTrue(np.all(fields["height_above_foot_m"][~face] == 0.0))
        self.assertGreater(float(fields["height_above_foot_m"].max()), 1.0)
        # Resampled to another raster.
        coarse = rs.heightmap_scarp_fields(heightmap, shape=(41, 201))
        self.assertEqual(coarse["face"].shape, (41, 201))
        self.assertTrue((coarse["rampart"] > 0.5).any())

    def test_flat_ground_at_a_strong_beds_level_is_its_rock_but_no_face(self):
        elevation, residual, strata, spacing = self._build(0.25, spacing=0.5, shape=(41, 801))
        stepped = elevation + residual
        fields_of = lambda rows: rs.heightmap_scarp_fields({  # noqa: E731
            "sample_grid": {"rows": rows.tolist()}, "source_uv_bounds": dict(BOUNDS),
            "sample_spacing_x_m": spacing, "sample_spacing_y_m": spacing,
            "regional_landforms": {"landforms": [{"landform": rs.LANDFORM_ID, "strata": strata}]},
        })
        fields = fields_of(stepped)
        row, column = np.unravel_index(int(np.argmax(fields["face"][15:25, 300:500])), (10, 200))
        row, column = row + 15, column + 300
        self.assertGreater(float(fields["face"][row, column]), 0.9)
        # A terrace cut level at that face's height, 30 m wide.
        terrace = stepped.copy()
        terrace[:, column - 30:column + 30] = stepped[row, column]
        cut = fields_of(terrace)
        self.assertLess(float(cut["face"][row, column - 20:column + 20].max()), 0.05)
        self.assertEqual(cut["rock"][row, column], fields["rock"][row, column])
        self.assertGreaterEqual(int(cut["rock"][row, column]), 0)

    def test_a_part_fills_no_more_of_a_cell_than_the_cells_fall_allows(self):
        shares = {name: np.asarray([1.0, 1.0, 1.0, 0.2]) for name in ("face", "talus", "rampart")}
        gradient = np.asarray([0.05, 0.42, 3.0, 0.42])
        bounded = rs.shares_the_fall_allows(shares, gradient)
        face = math.tan(math.radians(rs.FACE_MIN_ANGLE_DEG))
        # Nearly level ground is no face whatever its height says; half a
        # face's gradient is at most half a cell of face; a wall is all face;
        # a share the fall allows is left as it is.
        np.testing.assert_allclose(bounded["face"], [0.05 / face, 0.42 / face, 1.0, 0.2])
        np.testing.assert_allclose(bounded["talus"], [0.05 / rs.TALUS_GRADIENT, 0.42 / rs.TALUS_GRADIENT, 1.0, 0.2])
        np.testing.assert_allclose(bounded["rampart"], [0.05 / rs.RAMPART_GRADIENT[0], 1.0, 1.0, 0.2])

    def test_gentle_ground_at_a_faces_level_is_no_face(self):
        elevation, residual, strata, spacing = self._build(0.25)
        stepped = elevation + residual
        heightmap = {
            "sample_grid": {"rows": stepped.tolist()}, "source_uv_bounds": dict(BOUNDS),
            "sample_spacing_x_m": spacing, "sample_spacing_y_m": spacing,
            "regional_landforms": {"landforms": [{"landform": rs.LANDFORM_ID, "strata": strata}]},
        }
        fields = rs.heightmap_scarp_fields(heightmap)
        most = float(fields["face"].max())
        self.assertGreater(most, 0.2)
        level = float(stepped[np.unravel_index(int(np.argmax(fields["face"])), stepped.shape)])
        # The same record over ground that rockfall (or a canyon floor) has
        # left nearly level at the height of that face: rippled by a few
        # centimetres, as any finer level's ground is.
        y, x = np.mgrid[0:stepped.shape[0], 0:stepped.shape[1]]
        gentle = level + 0.02 * spacing * np.sin(0.9 * x) * np.cos(0.7 * y)
        heightmap["sample_grid"] = {"rows": gentle.tolist()}
        flat = rs.heightmap_scarp_fields(heightmap)
        self.assertLess(float(flat["face"].max()), 0.1)
        self.assertLess(float(flat["face"].max()), 0.3 * most)
        self.assertLess(float(flat["talus"].max()), 0.15)
        self.assertLess(float(flat["rampart"].max()), 0.25)

    def test_no_record_no_fields(self):
        self.assertIsNone(rs.heightmap_scarp_fields({"sample_grid": {"rows": [[0.0, 1.0], [0.0, 1.0]]}}))
        elevation, residual, strata, _spacing = self._build(0.25)
        heightmap = {
            "sample_grid": {"rows": (elevation + residual).tolist()}, "source_uv_bounds": dict(BOUNDS),
            "regional_landforms": {"landforms": [{"landform": rs.LANDFORM_ID, "strata": dict(strata, model="bench_remap_v0")}]},
        }
        self.assertIsNone(rs.heightmap_scarp_fields(heightmap))
        self.assertEqual(rs.heightmap_orders(heightmap), [])


class ScarpSoilTest(unittest.TestCase):
    """Soil reads the scarp from the same record as the heights."""

    def _models(self, aridity):
        from tests.test_rock_scarps import BuildAndRestepTest

        # Half-metre cells: faces a metre or two high are whole cells here.
        elevation, residual, strata, spacing = BuildAndRestepTest()._build(0.25, aridity=aridity, spacing=0.5, shape=(41, 801))
        heightmap = {
            "map_detail_level": 5, "sample_grid": {"rows": (elevation + residual).tolist()},
            "source_uv_bounds": dict(BOUNDS), "sample_spacing_x_m": spacing, "sample_spacing_y_m": spacing,
            "sea_level_m": None, "refinement_detail_band": {"parent_sample_spacing_m": spacing * 6.0},
            "regional_landforms": {"landforms": [{"landform": rs.LANDFORM_ID, "strata": strata}]},
        }
        rows = lambda value: [[value] * 6 for _ in range(6)]  # noqa: E731
        parent_soil = {"grid": {
            "soil_depth_m_rows": rows(0.9), "porosity_rows": rows(0.3), "relative_permeability_rows": rows(0.4),
            "ph_rows": rows(7.5), "salinity_index_rows": rows(0.1),
        }}
        climate = {name: [[value] * 4 for _ in range(4)] for name, value in (
            ("annual_runoff_rows_mm", 300.0), ("annual_precipitation_rows_mm", 900.0),
            ("annual_potential_evaporation_rows_mm", 1000.0), ("annual_groundwater_recharge_rows_mm", 100.0),
        )}
        water = {"climate_grid": climate, "runoff_grid": {}, "surface_water_grid": {}}
        return heightmap, water, parent_soil

    def test_a_face_is_bare_talus_holds_pockets_and_the_rampart_a_thin_skin(self):
        from simulations.world_gen.regolith_soils import (
            RAMPART_SOIL_DEPTH_M, TALUS_POROSITY, TALUS_SOIL_DEPTH_M, derive_regolith_soil_model,
        )

        heightmap, water, parent_soil = self._models(aridity=0.2)  # humid enough to bank talus
        soil = derive_regolith_soil_model({}, heightmap, water, {}, {}, parent_soil_model=parent_soil, parent_window=(0.2, 0.6, 0.2, 0.6))
        depth = np.asarray(soil["grid"]["soil_depth_m_rows"])
        fields = rs.heightmap_scarp_fields(heightmap)
        face, talus, rampart = (fields[name] > 0.9 for name in ("face", "talus", "rampart"))
        ground = (fields["face"] + fields["talus"] + fields["rampart"]) < 0.01
        self.assertTrue(face.any() and talus.any() and rampart.any() and ground.any())
        self.assertLess(float(depth[face].max()), 0.15)  # 0.9 m of soil beside it
        self.assertLessEqual(float(depth[talus].max()), TALUS_SOIL_DEPTH_M + 0.1)
        self.assertLessEqual(float(depth[rampart].max()), RAMPART_SOIL_DEPTH_M + 0.06)
        self.assertGreater(float(depth[ground].mean()), 0.6)
        self.assertAlmostEqual(float(np.asarray(soil["grid"]["porosity_rows"])[talus].mean()), TALUS_POROSITY, delta=0.02)
        self.assertGreater(soil["rock_scarp_cell_fractions"]["face"], 0.0)
        # A cell wider than its face holds the face's share of it.
        coarse = rs.heightmap_scarp_fields(heightmap, shape=(11, 101))
        self.assertTrue(((coarse["face"] > 0.05) & (coarse["face"] < 0.95)).any())
        fine_share = float(fields["face"][5:-5, 40:-40].mean())
        self.assertGreater(float(coarse["face"][2:-2, 5:-5].mean()), 0.4 * fine_share)
        self.assertLess(float(coarse["face"][2:-2, 5:-5].mean()), 2.5 * fine_share)
        # Limits, not factors: the soil a finer level inherits is not thinned twice.
        again = derive_regolith_soil_model({}, heightmap, water, {}, {}, parent_soil_model=soil, parent_window=(0.0, 1.0, 0.0, 1.0))
        self.assertAlmostEqual(float(np.asarray(again["grid"]["soil_depth_m_rows"])[rampart].mean()), float(depth[rampart].mean()), delta=0.05)


    def test_no_soil_rests_on_ground_steeper_than_repose_whatever_made_it_steep(self):
        from simulations.world_gen.regolith_soils import derive_regolith_soil_model

        heightmap, water, parent_soil = self._models(aridity=0.2)
        heightmap["regional_landforms"] = {"landforms": []}
        x = np.arange(201) * 0.5
        # A level, a 45-degree bank 10 m high, a level.
        profile = np.clip(x - 40.0, 0.0, 10.0)
        heightmap["sample_grid"] = {"rows": (np.ones((41, 1)) * profile[None, :]).tolist()}
        soil = derive_regolith_soil_model({}, heightmap, water, {}, {}, parent_soil_model=parent_soil, parent_window=(0.2, 0.6, 0.2, 0.6))
        depth = np.asarray(soil["grid"]["soil_depth_m_rows"])
        self.assertLess(float(depth[10:30, 85:95].max()), 1e-6)   # on the bank
        self.assertGreater(float(depth[10:30, 20:60].mean()), 0.6)  # on the level below it
        self.assertNotIn("rock_scarp_cell_fractions", soil)

    def test_a_rampart_tipped_steeper_than_repose_is_rock_face(self):
        from tests.test_rock_scarps import BuildAndRestepTest

        # The profile is laid out for a slope of 0.25; here the ground falls four times as steeply.
        elevation, residual, strata, spacing = BuildAndRestepTest()._build(0.25, spacing=0.5, shape=(41, 801))
        stepped = elevation + residual
        heightmap = lambda rows, cell: {  # noqa: E731
            "sample_grid": {"rows": rows.tolist()}, "source_uv_bounds": dict(BOUNDS),
            "sample_spacing_x_m": cell, "sample_spacing_y_m": cell,
            "regional_landforms": {"landforms": [{"landform": rs.LANDFORM_ID, "strata": strata}]},
        }
        as_built = rs.heightmap_scarp_fields(heightmap(stepped, spacing))
        tipped = rs.heightmap_scarp_fields(heightmap(stepped, spacing / 4.0))
        self.assertGreater(float(as_built["rampart"].mean()), 0.05)
        self.assertLess(float(tipped["rampart"].mean()), 0.2 * float(as_built["rampart"].mean()))
        self.assertGreater(float(tipped["face"].mean()), float(as_built["face"].mean()) + 0.5 * float(as_built["rampart"].mean()))


if __name__ == "__main__":
    unittest.main()
