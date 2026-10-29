"""Per-LOD terrain improvements: LOD0 crustal contrast and cubic anchors,
LOD1 belt frame, parent-scale detail centring and boundary inflow, LOD1+
stream-power relief, regional ice margins, LOD3+ channel belts and
floodplains."""

import math
import unittest

import numpy as np

from simulations.world_gen import fluvial_relief
from simulations.world_gen import heightmap
from simulations.world_gen import material_routing as routing
from simulations.world_gen import regional_refinement as refinement


def _two_crust_model(height=9, width=17):
    """Continental crust in the northern half, oceanic crust in the south."""
    return {
        "lithosphere_grid": {
            "crust_type_rows": [["continental" if y < height // 2 else "oceanic"] * width for y in range(height)],
            "continental_fraction_rows": [[1.0 if y < height // 2 else 0.0] * width for y in range(height)],
            "ocean_floor_age_rows_myr": [[0.0 if y < height // 2 else 90.0] * width for y in range(height)],
        }
    }


class CrustalContrastTests(unittest.TestCase):
    def test_excess_contrast_is_removed_from_oceanic_crust_only(self):
        model = _two_crust_model()
        width, height = 33, 17
        rows = [[1500.0 if y < 6 else (-6500.0 if y > 10 else -2500.0) for _x in range(width)] for y in range(height)]
        calibration = heightmap._crustal_freeboard_calibration(rows, width, height, model)
        self.assertAlmostEqual(8000.0, calibration["measured_contrast_m"], delta=1.0)
        self.assertAlmostEqual(8000.0 - heightmap.CRUSTAL_CONTRAST_TARGET_M, calibration["ocean_shift_m"], delta=1.0)
        calibrated = np.asarray(heightmap._apply_crustal_freeboard_calibration(
            rows, width, height, model, calibration, min_elevation=-11000.0, max_elevation=9000.0,
        ))
        self.assertAlmostEqual(1500.0, float(calibrated[0, 5]), delta=0.1)
        self.assertAlmostEqual(-6500.0 + calibration["ocean_shift_m"], float(calibrated[-1, 5]), delta=0.1)

    def test_small_contrast_is_left_alone(self):
        model = _two_crust_model()
        rows = [[300.0 if y < 6 else -3000.0 for _x in range(33)] for y in range(17)]
        self.assertEqual(0.0, heightmap._crustal_freeboard_calibration(rows, 33, 17, model)["ocean_shift_m"])

    def test_regional_evaluator_applies_the_same_shift(self):
        model = _two_crust_model()
        root = {"crustal_freeboard_calibration": {"ocean_shift_m": 3000.0}}
        self.assertAlmostEqual(0.0, heightmap.crustal_freeboard_shift_at(0.3, 0.1, model, root))
        self.assertAlmostEqual(3000.0, heightmap.crustal_freeboard_shift_at(0.3, 0.95, model, root))
        # Matches the LOD0 grid weights bit for bit.
        width, height = 33, 17
        continental, _age, _oceanic = heightmap._sample_lithosphere_grid(
            model, np.asarray([0.25]), np.asarray([10 / (height - 1)]),
        )
        self.assertEqual(
            float(heightmap.ocean_crust_weight(continental)[0]) * 3000.0,
            heightmap.crustal_freeboard_shift_at(0.25, 10 / (height - 1), model, root),
        )


class BeltFrameTests(unittest.TestCase):
    def test_opposite_segment_directions_share_one_orientation(self):
        angle = math.radians(64.0)
        c2, s2 = math.cos(2 * angle), math.sin(2 * angle)
        grid = {"channels": {
            "mountain_belt_envelope": [[1.0, 1.0], [1.0, 1.0]],
            # Same belt stored in both directions: +64 deg and -116 deg.
            "mountain_belt_axis_c2": [[c2, c2], [c2, c2]],
            "mountain_belt_axis_s2": [[s2, s2], [s2, s2]],
        }}
        (axis_x, axis_y), _origin = refinement._tile_belt_frame(grid, 0.2, 0.3, 0.4, 0.5, 40_000_000.0)
        self.assertAlmostEqual(abs(math.cos(angle)), abs(axis_x), places=9)
        self.assertAlmostEqual(abs(math.sin(angle)), abs(axis_y), places=9)
        context = refinement._axis_from_doubled_angle({"mountain_belt_axis_c2": c2 * 0.5, "mountain_belt_axis_s2": s2 * 0.5})
        self.assertAlmostEqual(0.5, math.hypot(context["mountain_belt_axis_x"], context["mountain_belt_axis_y"]), places=9)


def _reference_distance(receivers):
    size = receivers.size
    result = np.zeros(size, dtype=np.int64)
    for cell in range(size):
        current, hops = cell, 0
        while receivers[current] < size:
            current = receivers[current]
            hops += 1
        result[cell] = hops
    return result


class StreamPowerReliefTests(unittest.TestCase):
    def test_outlet_distance_matches_path_walk(self):
        rng = np.random.default_rng(3)
        elevation = rng.uniform(0.0, 30.0, (11, 14)) + np.arange(14)[None, :] * 4.0
        receivers, _gradient = routing.d8_receivers(elevation, dx=50.0, dy=50.0)
        np.testing.assert_array_equal(_reference_distance(receivers), fluvial_relief.outlet_distance(receivers))

    def test_trunks_cut_deeper_than_hillslopes_and_parent_scale_is_kept(self):
        rng = np.random.default_rng(8)
        y, x = np.mgrid[0:48, 0:48]
        elevation = 400.0 + y * 6.0 + np.abs(x - 24) * 3.0 + rng.normal(0.0, 3.0, (48, 48))
        land = np.ones(elevation.shape, dtype=bool)
        eroded, summary = fluvial_relief.stream_power_relief(
            elevation, land, dx=200.0, dy=200.0, detail_relief=np.full(elevation.shape, 80.0),
        )
        change = elevation - eroded
        self.assertGreater(summary["longest_flow_path_cells"], 10)
        self.assertLessEqual(float(change.max()), 80.0 + 1e-6)
        # The valley axis (x = 24) is cut deeper than its flanks.
        axis = float(change[5:40, 23:26].mean())
        self.assertGreater(axis, 1.2 * float(change[5:40, 8:13].mean()))
        self.assertGreater(axis, 1.2 * float(change[5:40, 36:41].mean()))
        restored = fluvial_relief.conserve_parent_scale(elevation, eroded, land, 6)
        self.assertLess(abs(float((restored - elevation)[12:36, 12:36].mean())), 2.0)


class ChannelBeltTests(unittest.TestCase):
    def test_belts_follow_the_valley_and_widen_downstream(self):
        y, x = np.mgrid[0:60, 0:80]
        elevation = 300.0 - x * 2.0 + np.abs(y - 30) * 4.0
        land = np.ones(elevation.shape, dtype=bool)
        belts = routing.channel_belts(elevation, land, dx=100.0, dy=100.0)
        self.assertTrue(belts["channel"][30, 60:].all())
        self.assertFalse(belts["channel"][2, 40])
        self.assertGreater(float(belts["half_width_m"][30, 75]), float(belts["half_width_m"][30, 40]))
        self.assertEqual(1.0, float(belts["belt"][30, 70]))
        self.assertEqual(0.0, float(belts["belt"][2, 70]))

    def test_floodplain_flattening_levels_the_valley_floor(self):
        y, x = np.mgrid[0:60, 0:80]
        rng = np.random.default_rng(2)
        elevation = 300.0 - x * 2.0 + np.abs(y - 30) * 1.5 + rng.normal(0.0, 2.0, (60, 80))
        rows, summary = refinement._floodplain_flattening(
            elevation.tolist(), sea_level=0.0, spacing_x_m=100.0, spacing_y_m=100.0,
            parent_spacing_m=600.0, level=3,
        )
        self.assertTrue(summary["applied"])
        after = np.asarray(rows)
        # Across the valley near the outlet the floor gets flatter.
        self.assertLess(float(np.std(after[28:33, 70])), float(np.std(elevation[28:33, 70])))

    def test_wide_floodplain_has_no_stripes_from_the_rivers_bed_noise(self):
        # A large river enters from the west along row 40; its bed carries
        # cell-scale noise, and the floodplain spans the whole tile.
        y, x = np.mgrid[0:81, 0:121]
        rng = np.random.default_rng(5)
        elevation = 300.0 - x * 0.05 + np.abs(y - 40) * 0.02 + rng.normal(0.0, 0.3, (81, 121))
        inflow = {"cells": [[0, 40, 5.0e10]]}
        rows, summary = refinement._floodplain_flattening(
            elevation.tolist(), sea_level=0.0, spacing_x_m=7.0, spacing_y_m=7.0,
            parent_spacing_m=50.0, level=4, inflow=inflow,
        )
        self.assertTrue(summary["applied"])
        after = np.asarray(rows)
        # Away from the channel, neighbouring columns differ by far less
        # than the bed noise: no per-column stripes.
        band = after[10:25, 20:100]
        self.assertLess(float(np.std(np.diff(band, axis=1))), 0.15)

    def test_tributary_crossing_a_floodplain_is_not_trenched(self):
        # LOD3: a big river along row 40, a tributary from the north at column 60.
        y, x = np.mgrid[0:81, 0:121].astype(float)
        elevation = 100.0 - 0.0714 * x + 0.05 * np.abs(y - 40.0)
        elevation -= np.where(y < 38.0, 0.4 * np.clip(1.0 - np.abs(x - 60.0) / 3.0, 0.0, 1.0), 0.0)
        inflow = {"cells": [[0, 40, 5.0e10], [60, 0, 2.0e7]]}
        rows, summary = refinement._floodplain_flattening(
            elevation.tolist(), sea_level=0.0, spacing_x_m=50.0, spacing_y_m=50.0,
            parent_spacing_m=300.0, level=3, inflow=inflow,
        )
        self.assertTrue(summary["applied"])
        after = np.asarray(rows)
        groove = float(np.mean(after[15, [57, 63]]) - after[15, 60])
        self.assertLess(groove, 1.0)

    def test_a_river_bed_never_rises_downstream_across_an_inherited_sill(self):
        # LOD3: a big river enters from the west along row 40 down a 0.1 %
        # valley; the parent left a 6 m, 1.5 km-long sill across its course
        # (wider than the parent's spacing, so the parent-scale conservation
        # cannot remove it).  The valley walls keep the river in the tile.
        y, x = np.mgrid[0:81, 0:121].astype(float)
        sill = 6.0 * np.exp(-(((x - 60.0) / 15.0) ** 2))
        elevation = 100.0 - 0.05 * x + 0.5 * np.abs(y - 40.0) + sill
        inflow = {"cells": [[0, 40, 5.0e10]]}
        rows, summary = refinement._floodplain_flattening(
            elevation.tolist(), sea_level=0.0, spacing_x_m=50.0, spacing_y_m=50.0,
            parent_spacing_m=300.0, level=3, inflow=inflow,
        )
        self.assertTrue(summary["applied"])
        after = np.asarray(rows)
        land = np.ones(after.shape, dtype=bool)
        belts = routing.channel_belts(after, land, dx=50.0, dy=50.0, inflow_cells=routing.inflow_grid(after.shape, inflow, 2500.0))
        receivers = routing.filled_routing(after, land, dx=50.0, dy=50.0, inlets=routing.inlet_mask(
            routing.inflow_grid(after.shape, inflow, 2500.0), after.shape, dx=50.0, dy=50.0))
        cell, path = 40 * 121, []
        while cell < after.size and len(path) < 400:
            path.append(cell)
            cell = int(receivers[cell])
        bed = after.ravel()[path]
        before = elevation.ravel()[path]
        # Interior course (edge fades keep the parent there): the sill is gone.
        interior = slice(10, len(path) - 10)
        rise_before = float(np.clip(np.diff(before[interior]), 0.0, None).sum())
        rise_after = float(np.clip(np.diff(bed[interior]), 0.0, None).sum())
        self.assertGreater(rise_before, 4.0)
        self.assertLess(rise_after, 0.5)
        self.assertTrue(belts["channel"][40, 60])


class InletAnchorTests(unittest.TestCase):
    def test_a_river_entering_in_a_pit_cuts_down_instead_of_raising_its_entry(self):
        # The parent left the river's entry (west edge) 12 m below the sill
        # 10 cells inside; the edge belongs to the parent and stays.
        width = 40
        elevation = np.full((9, width), 120.0)
        elevation[4, :] = 50.0 - 0.2 * np.arange(width) + 12.0 * np.exp(-(((np.arange(width) - 10.0) / 4.0) ** 2))
        land = np.ones(elevation.shape, dtype=bool)
        inflow = np.zeros(elevation.shape)
        inflow[4, 0] = 1.0e4
        receivers = routing.filled_routing(elevation, land, dx=100.0, dy=100.0, inlets=routing.inlet_mask(inflow, elevation.shape, dx=100.0, dy=100.0))
        area = routing.upstream_area_m2(receivers, elevation.shape, dx=100.0, dy=100.0)
        channel = np.zeros(elevation.shape, dtype=bool)
        channel[4, :] = True
        bed = routing.monotone_channel_beds(elevation, channel, receivers, area)
        self.assertAlmostEqual(float(bed[4, 0]), float(elevation[4, 0]))
        self.assertTrue(np.all(np.diff(bed[4, :]) <= 1e-9))
        self.assertLessEqual(float(bed[4, 1:].max()), float(elevation[4, 0]) + 1e-9)


class EvolutionEdgeTests(unittest.TestCase):
    def test_surface_evolution_change_vanishes_at_the_tile_edge(self):
        before = {"sample_grid": {"rows": np.zeros((50, 80)).tolist()}}
        evolved = {"sample_grid": {"rows": np.full((50, 80), 16.0).tolist()}, "status": "x"}
        faded = np.asarray(refinement._edge_faded_evolution(before, evolved)["sample_grid"]["rows"])
        self.assertEqual(float(np.abs(faded[0]).max()), 0.0)
        self.assertEqual(float(np.abs(faded[:, -1]).max()), 0.0)
        self.assertEqual(float(faded[25, 40]), 16.0)

    def test_surface_evolution_keeps_the_parents_mean_and_adds_only_the_relief_inside_its_cells(self):
        # A plain 3 m over the sea beside a sea bed 5 m under it.  Evolution
        # lowers all land by 4 m (weathering is scored on every cell), cuts a
        # channel 6 m deeper, and takes half a metre off the sea bed.
        ground = np.full((60, 90), 3.0)
        ground[:, 60:] = -5.0
        change = np.where(ground >= 0.0, -4.0, -0.5)
        change[30, :60] -= 6.0
        before = {"sample_grid": {"rows": ground.tolist()}, "sample_spacing_x_m": 100.0, "sample_spacing_y_m": 100.0}
        evolved = {"sample_grid": {"rows": (ground + change).tolist()}}
        kept = np.asarray(refinement._edge_faded_evolution(
            before, evolved, sea_level=0.0, parent_spacing_m=800.0)["sample_grid"]["rows"])
        # The plain is not drowned and stands where its parent has it ...
        np.testing.assert_allclose(kept[12:20, 15:55], 3.0, atol=1e-6)
        self.assertTrue(bool(np.all(kept[12:48, 15:59][np.arange(12, 48) != 30] > 2.9)))
        # ... the channel is still cut into it, and the sea bed is the parent's.
        self.assertLess(float(kept[30, 30]), float(kept[26, 30]) - 5.0)
        np.testing.assert_allclose(kept[12:48, 62:80], -5.0, atol=1e-6)
        # Without a parent spacing the change is taken as it comes.
        plain = np.asarray(refinement._edge_faded_evolution(before, evolved)["sample_grid"]["rows"])
        self.assertAlmostEqual(float(plain[15, 30]), -1.0)


class MonotoneBedTests(unittest.TestCase):
    def test_fit_pools_violators_and_keeps_their_sum(self):
        values = np.array([10.0, 8.0, 9.0, 12.0, 5.0, 4.0])
        fitted = routing._non_increasing_fit(values)
        self.assertTrue(np.all(np.diff(fitted) <= 1e-12))
        self.assertAlmostEqual(float(fitted.sum()), float(values.sum()))
        np.testing.assert_allclose(fitted[:2], [10.0, 9.666666666666666])

    def test_wide_pits_go_and_tributaries_never_join_below_the_trunk_bed(self):
        # Trunk west-east along row 5 (40 cells) with a smooth 6 m pit about
        # 8 cells wide (inherited parent-scale relief); a tributary from the
        # north at column 20.
        width = 40
        elevation = np.full((11, width), 80.0)
        elevation[5, :] = 40.0 - 0.5 * np.arange(width) - 6.0 * np.exp(-(((np.arange(width) - 16.0) / 4.0) ** 2))
        elevation[:5, 20] = 50.0 - np.arange(5)
        land = np.ones(elevation.shape, dtype=bool)
        receivers = routing.filled_routing(elevation, land, dx=100.0, dy=100.0)
        area = routing.upstream_area_m2(receivers, elevation.shape, dx=100.0, dy=100.0)
        channel = np.zeros(elevation.shape, dtype=bool)
        channel[5, :] = True
        channel[:5, 20] = True
        bed = routing.monotone_channel_beds(elevation, channel, receivers, area)

        def reverse_rise(values):
            steps = np.diff(values)
            return float(steps[steps > 0].sum())

        self.assertGreater(reverse_rise(elevation[5, :]), 2.0)
        self.assertLess(reverse_rise(bed[5, :]), 0.5)
        # The tributary meets the trunk at or above the trunk's bed.
        self.assertGreaterEqual(float(bed[4, 20]), float(bed[5, 20]) - 1e-9)
        self.assertEqual(float(bed[0, 0]), 80.0)

    def test_a_river_keeps_the_falls_it_has(self):
        # A river that drops 25 m over a cliff onto a shore platform, with a
        # 6 m pit far upstream.  The pit is fitted away; the fall is the
        # river's own and stays where it is, the platform below it too.
        width = 80
        elevation = np.full((9, width), 120.0)
        profile = 60.0 - 0.2 * np.arange(width)
        profile[60:] = 1.0 - 0.01 * np.arange(width - 60)           # the platform below the cliff
        profile -= 6.0 * np.exp(-(((np.arange(width) - 14.0) / 3.0) ** 2))
        elevation[4, :] = profile
        land = np.ones(elevation.shape, dtype=bool)
        receivers = routing.filled_routing(elevation, land, dx=40.0, dy=40.0)
        area = routing.upstream_area_m2(receivers, elevation.shape, dx=40.0, dy=40.0)
        channel = np.zeros(elevation.shape, dtype=bool)
        channel[4, :] = True
        for smooth_cells in (0.0, 2.0):
            bed = routing.monotone_channel_beds(elevation, channel, receivers, area, smooth_cells=smooth_cells)
            if not smooth_cells:   # the exact bed; with smoothing it is the correction for the floodplain
                self.assertTrue(bool(np.all(np.diff(bed[4, :]) <= 1e-9)))
            np.testing.assert_allclose(bed[4, 50:], elevation[4, 50:], atol=1e-6)
            self.assertGreater(float(np.abs(bed[4, 8:20] - elevation[4, 8:20]).max()), 1.0)


class AnchorResampleTests(unittest.TestCase):
    def test_cubic_anchor_upsample_beats_linear_and_keeps_the_seam(self):
        width, height = 17, 5
        period = width - 1
        rows = [[1000.0 * math.sin(math.tau * x / period) for x in range(width)] for _y in range(height)]
        result = np.asarray(heightmap._resample_height_rows(rows, 65, 9))
        target_x = np.arange(65) * period / 64.0
        truth = 1000.0 * np.sin(math.tau * target_x / period)
        linear = np.interp(target_x, np.arange(width), np.asarray(rows[0]))
        cubic_error = float(np.max(np.abs(result[4] - truth)))
        linear_error = float(np.max(np.abs(linear - truth)))
        self.assertLess(cubic_error, linear_error * 0.5)
        np.testing.assert_allclose(result[:, 0], result[:, -1])
        # Clamped between neighbouring anchors: no overshoot past the source range.
        self.assertLessEqual(float(result.max()), 1000.0 + 1e-6)


class DetailCenteringTests(unittest.TestCase):
    def test_parent_scale_mean_is_removed_inland_and_edges_and_coast_are_kept(self):
        height, width = 40, 60
        inherited = np.full((height, width), 1200.0)
        inherited[:, :8] = -300.0  # sea along the west edge
        noise = np.random.default_rng(3).normal(0.0, 20.0, (height, width))
        rows = inherited + 180.0 + noise
        rows[:, :8] = inherited[:, :8] - 40.0
        centred, info = refinement._center_detail_at_parent_scale(
            rows.tolist(), inherited.tolist(), sea_level=0.0,
            spacing_x_m=1000.0, spacing_y_m=1000.0, parent_spacing_m=8000.0,
        )
        centred = np.asarray(centred)
        self.assertTrue(info["applied"])
        interior = centred[10:30, 25:50] - inherited[10:30, 25:50]
        self.assertLess(abs(float(interior.mean())), 10.0)
        # The tile edge still equals the parent-locked input, and sea stays sea.
        np.testing.assert_allclose(centred[0], np.round(rows[0], 2))
        self.assertTrue(bool(np.all(centred[:, :8] < 0.0)))
        self.assertTrue(bool(np.all(centred[:, 12:] >= 0.5)))


class TileRimTests(unittest.TestCase):
    def test_a_uniform_detail_offset_leaves_no_ridge_inside_the_tile_edge(self):
        # The synthesis added +650 m everywhere and faded it to zero at the
        # tile edge; centred, nothing of it may remain, in the fade band too.
        height, width = 120, 160
        inherited = np.full((height, width), 900.0)
        local_u = np.arange(width) / (width - 1)
        local_v = np.arange(height) / (height - 1)
        edge = np.minimum(np.minimum(local_u, 1.0 - local_u)[None, :], np.minimum(local_v, 1.0 - local_v)[:, None])
        fade = np.clip(edge / refinement.PARENT_EDGE_FADE_FRACTION, 0.0, 1.0)
        fade = fade * fade * (3.0 - 2.0 * fade)
        rows = inherited + 650.0 * fade
        centred, _info = refinement._center_detail_at_parent_scale(
            rows.tolist(), inherited.tolist(), sea_level=0.0,
            spacing_x_m=3000.0, spacing_y_m=3000.0, parent_spacing_m=78_000.0,
        )
        self.assertLess(float(np.abs(np.asarray(centred) - inherited).max()), 5.0)


class ShorelineTests(unittest.TestCase):
    def test_a_shallow_bay_lifted_by_the_detail_offset_goes_back_under_water(self):
        # A coastal plain (west, +30 m) beside a shallow bay (east, -80 m);
        # the synthesis added +650 m everywhere (production residual offset).
        height, width = 40, 60
        inherited = np.full((height, width), 30.0)
        inherited[:, 30:] = -80.0
        noise = np.random.default_rng(4).normal(0.0, 5.0, (height, width))
        rows = inherited + 650.0 + noise
        topology = np.where(inherited >= 0.0, 1, -1)
        centred, info = refinement._center_detail_at_parent_scale(
            rows.tolist(), inherited.tolist(), sea_level=0.0,
            spacing_x_m=1000.0, spacing_y_m=1000.0, parent_spacing_m=8000.0, topology_rows=topology.tolist(),
        )
        centred = np.asarray(centred)
        inner = (slice(6, 34), slice(6, 54))
        self.assertTrue(bool(np.all(centred[inner][:, 26:] < 0.0)))
        self.assertTrue(bool(np.all(centred[inner][:, :22] > 0.0)))
        # The plain is back near its parent height, not 650 m above it.
        self.assertLess(abs(float((centred - inherited)[10:30, 8:20].mean())), 10.0)
        self.assertEqual(info["cells_changed_side_fraction"], 0.0)

    def test_shallow_water_and_low_shores_keep_their_height(self):
        # A sea bed 5 cm under the sea beside a flat 20 cm over it, both
        # certain in the parent; the detail moves every cell a centimetre,
        # up or down.  (Every cell moved towards sea level used to jump to a
        # metre from it: a maze of metre-high steps at Parcel scale.)
        height, width = 24, 40
        inherited = np.full((height, width), -0.05)
        inherited[:, 20:] = 0.20
        detail = 0.01 * np.where(np.indices((height, width)).sum(axis=0) % 2 == 0, 1.0, -1.0)
        topology = np.where(inherited >= 0.0, 1, -1)
        centred, _info = refinement._center_detail_at_parent_scale(
            (inherited + detail).tolist(), inherited.tolist(), sea_level=0.0,
            spacing_x_m=0.78, spacing_y_m=0.78, parent_spacing_m=6.25, topology_rows=topology.tolist(),
        )
        centred = np.asarray(centred)
        self.assertLess(float(np.abs(centred - inherited).max()), 0.03)
        self.assertTrue(bool(np.all(centred[:, :20] < 0.0)))
        self.assertTrue(bool(np.all(centred[:, 20:] > 0.0)))

    def test_detail_may_cross_sea_level_only_where_the_parent_cell_is_mixed(self):
        height, width = 40, 60
        inherited = np.full((height, width), 5.0)
        rows = inherited.copy()
        rows[18:22, :] -= 20.0  # a valley 20 m deep across a 5 m coastal plain
        for certainty, expect_sea in ((0, True), (1, False)):
            centred, _info = refinement._center_detail_at_parent_scale(
                rows.tolist(), inherited.tolist(), sea_level=0.0,
                spacing_x_m=100.0, spacing_y_m=100.0, parent_spacing_m=3000.0,
                topology_rows=np.full((height, width), certainty).tolist(),
            )
            flooded = bool(np.any(np.asarray(centred)[18:22, 10:50] < 0.0))
            self.assertEqual(flooded, expect_sea)

    def test_the_shore_is_resolved_inside_mixed_parent_cells_only(self):
        # Parent: land west (+40 m), sea east (-40 m), 40 km cells; the
        # interpolated shore is a straight north-south line.
        parent = np.tile(np.where(np.arange(9) < 4.5, 40.0, -40.0), (7, 1))
        height, width = 121, 161
        local_u = np.arange(width) / (width - 1)
        inherited = np.tile(np.interp(local_u * 8.0, np.arange(9), parent[0]), (height, 1))
        refined, shift, info = refinement._refine_coastline(
            inherited.tolist(), parent.tolist(), parent_uv=(0.0, 1.0, 0.0, 1.0), source_uv=(0.3, 0.308, 0.4, 0.412),
            sea_level=0.0, parent_wrap_x=False, seed="t", level=1, planet_circumference_m=4.0e7,
            parent_spacing_m=40_000.0, spacing_m=2_000.0,
        )
        refined, shift = np.asarray(refined), np.asarray(shift)
        self.assertTrue(info["applied"])
        shore = np.array([np.argmax(row < 0.0) for row in refined[10:-10]])
        # The straight shore became irregular, within the mixed parent cell.
        self.assertGreater(float(np.std(shore)), 1.0)
        self.assertTrue(80 <= shore.min() and shore.max() <= 100)
        # Certain cells (columns outside the mixed parent cell) and the tile edge are untouched.
        self.assertEqual(float(np.abs(shift[:, :78]).max()), 0.0)
        self.assertEqual(float(np.abs(shift[:, 102:]).max()), 0.0)
        self.assertEqual(float(np.abs(shift[0]).max()), 0.0)


class BoundaryInflowTests(unittest.TestCase):
    def test_a_river_entering_the_tile_brings_its_upstream_catchment(self):
        def surface(x, y):
            # Slopes east to a sea column, with a valley along y = 10 whose
            # walls are steeper than its floor, so flow converges into it.
            return 1000.0 - 5.0 * x + 30.0 * np.abs(y - 10.0)

        parent_h, parent_w = 21, 41
        ys, xs = np.mgrid[0:parent_h, 0:parent_w].astype(float)
        parent = surface(xs, ys)
        land = xs < parent_w - 1
        parent_bounds = {"min_u": 0.0, "max_u": 1.0, "min_v": 0.0, "max_v": 1.0}
        child_bounds = {"min_u": 0.5, "max_u": 0.75, "min_v": 0.3, "max_v": 0.7}
        child_h, child_w = 33, 41
        child_x = (child_bounds["min_u"] + (child_bounds["max_u"] - child_bounds["min_u"]) * np.arange(child_w) / (child_w - 1)) * (parent_w - 1)
        child_y = (child_bounds["min_v"] + (child_bounds["max_v"] - child_bounds["min_v"]) * np.arange(child_h) / (child_h - 1)) * (parent_h - 1)
        child = surface(child_x[None, :], child_y[:, None])
        result = routing.boundary_inflow(
            parent, land, parent_bounds, 1.0e6, child, child_bounds, parent_dx=1000.0, parent_dy=1000.0,
        )
        cells = result["cells"]
        self.assertTrue(cells)
        x, y, area = max(cells, key=lambda cell: cell[2])
        # The trunk enters through the west edge, in the valley.
        self.assertEqual(0, x)
        self.assertAlmostEqual(10.0, child_y[y], delta=1.0)
        upstream_cells = int(np.sum(xs < child_x[0]))
        self.assertGreater(area, 0.5 * upstream_cells * 1.0e6)
        total_outside = float(np.sum(land) - np.sum((xs >= child_x[0]) & (xs <= child_x[-1]) & (ys >= child_y[0]) & (ys <= child_y[-1])))
        self.assertLessEqual(sum(cell[2] for cell in cells), total_outside * 1.0e6 + 1.0)

        # A parent that itself receives a river (square metres per cell) must
        # still hand it on: its inflow valley is an inlet, not the whole edge.
        parent_inflow = np.zeros(parent.shape)
        parent_inflow[10, 0] = 5.0e10
        masks = []
        original_mask = routing.inlet_mask

        def recording_mask(*args, **kwargs):
            mask = original_mask(*args, **kwargs)
            masks.append(mask)
            return mask

        routing.inlet_mask = recording_mask
        try:
            chained = routing.boundary_inflow(
                parent, land, parent_bounds, 1.0e6, child, child_bounds, parent_dx=1000.0, parent_dy=1000.0,
                parent_inflow=parent_inflow,
            )
        finally:
            routing.inlet_mask = original_mask
        self.assertGreater(max(cell[2] for cell in chained["cells"]), area + 0.9 * 5.0e10)
        # 50,000 km2 has a ~2 km floodplain half-width: a few edge cells, not the whole boundary.
        self.assertTrue(masks and masks[0] is not None)
        self.assertLessEqual(int(masks[0].sum()), 5)


class ParentExitTests(unittest.TestCase):
    def _setup(self):
        def surface(x, y):
            return 1000.0 - 5.0 * x + 30.0 * np.abs(y - 10.0)

        parent_h, parent_w = 21, 41
        ys, xs = np.mgrid[0:parent_h, 0:parent_w].astype(float)
        parent = surface(xs, ys)
        land = xs < parent_w - 1
        parent_bounds = {"min_u": 0.0, "max_u": 1.0, "min_v": 0.0, "max_v": 1.0}
        child_bounds = {"min_u": 0.5, "max_u": 0.75, "min_v": 0.3, "max_v": 0.7}
        child_h, child_w = 33, 41
        child_x = (child_bounds["min_u"] + (child_bounds["max_u"] - child_bounds["min_u"]) * np.arange(child_w) / (child_w - 1)) * (parent_w - 1)
        child_y = (child_bounds["min_v"] + (child_bounds["max_v"] - child_bounds["min_v"]) * np.arange(child_h) / (child_h - 1)) * (parent_h - 1)
        child = surface(child_x[None, :], child_y[:, None])
        record = routing.boundary_inflow(parent, land, parent_bounds, 1.0e6, child, child_bounds, parent_dx=1000.0, parent_dy=1000.0)
        return child, record

    def test_only_the_edge_the_parent_drains_through_is_an_outlet(self):
        child, record = self._setup()
        opened = record["open_edges"]
        centre = child.shape[0] // 2
        # The parent drains east down the valley: the valley's exit on the
        # east edge is open, the other three sides are not.
        self.assertTrue(any(start <= centre <= stop for start, stop in opened["east"]))
        self.assertEqual([opened["west"], opened["north"], opened["south"]], [[], [], []])
        grid = routing.inflow_grid(child.shape, record, 250.0 * 250.0)
        mask = routing.inlet_mask(grid, child.shape, dx=250.0, dy=250.0)
        self.assertTrue(mask[:, 0].all() and mask[0, 1:-1].all() and mask[-1, 1:-1].all())
        self.assertFalse(mask[centre, -1])

    def test_a_dammed_river_spills_through_the_parents_exit_not_back_through_its_entry_side(self):
        child, record = self._setup()
        # An 80 m sill across the tile: the cheapest way out is back over the
        # entry side, beside the river's inlet stretch.
        dammed = child.copy()
        dammed[:, 18:22] += 80.0
        land = np.ones(dammed.shape, dtype=bool)

        def spill_column(grid):
            receivers = routing.filled_routing(dammed, land, dx=250.0, dy=250.0, inlets=routing.inlet_mask(grid, dammed.shape, dx=250.0, dy=250.0))
            cell = int(np.argmax(grid))
            for _step in range(dammed.size):
                nxt = int(receivers[cell])
                if nxt >= dammed.size or nxt == cell:
                    break
                cell = nxt
            return cell % dammed.shape[1]

        river_only = routing.inflow_grid(dammed.shape, {"cells": record["cells"]}, 250.0 * 250.0)
        self.assertLess(spill_column(river_only), 18)
        self.assertEqual(spill_column(routing.inflow_grid(dammed.shape, record, 250.0 * 250.0)), dammed.shape[1] - 1)


class RegionalIceMaskTests(unittest.TestCase):
    def test_ice_margin_follows_terrain_and_meets_the_parent_at_the_edge(self):
        parent_ice = [[x < 4 for x in range(8)] for _y in range(8)]
        height, width = 81, 81
        ys, xs = np.mgrid[0:height, 0:width].astype(float)
        ridges = 1500.0 + 300.0 * np.sin(ys / 5.0)
        kwargs = dict(parent_wrap_x=False, parent_bounds=(0.25, 0.75, 0.25, 0.75), parent_spacing_m=8000.0, spacing_m=500.0, seed=11)
        ice, info = refinement._regional_ice_mask(parent_ice, ridges.tolist(), **kwargs)
        flat_ice, _flat_info = refinement._regional_ice_mask(parent_ice, np.full((height, width), 1500.0).tolist(), **kwargs)
        ice = np.asarray(ice)
        flat_ice = np.asarray(flat_ice)
        self.assertTrue(info["applied"])
        # Edge cells take the parent coverage unchanged.
        np.testing.assert_array_equal(ice[0], flat_ice[0])
        np.testing.assert_array_equal(ice[:, -1], flat_ice[:, -1])
        # Inside the margin zone, highs keep ice and lows lose it.
        margin = (xs > 20) & (xs < 60) & (ys > 5) & (ys < 75)
        high = margin & (ridges > 1650.0)
        low = margin & (ridges < 1350.0)
        self.assertGreater(float(ice[high].mean()), float(ice[low].mean()) + 0.2)
        # The margin is no longer one straight line.
        edge_columns = [int(np.argmin(row)) for row in ice[5:76]]
        self.assertGreater(float(np.std(edge_columns)), 1.0)


    def test_a_straight_parent_margin_is_irregular_on_smooth_ground_at_every_scale(self):
        # Smooth ramp, straight parent margin: the terrain term has nothing
        # to follow, so the margin's shape comes from the fractal term.
        parent_ice = [[x < 4 for x in range(8)] for _y in range(8)]
        height, width = 121, 121
        ramp = (1500.0 + np.mgrid[0:height, 0:width][1] * 0.5).tolist()
        ice, _info = refinement._regional_ice_mask(
            parent_ice, ramp, parent_wrap_x=False, parent_bounds=(0.25, 0.75, 0.25, 0.75),
            parent_spacing_m=15_000.0, spacing_m=500.0, seed=11,
            source_uv=(0.3, 0.3015, 0.4, 0.403), planet_circumference_m=4.0e7, noise_seed="t", level=2,
        )
        ice = np.asarray(ice)
        edge_columns = np.array([int(np.argmin(row)) for row in ice[8:113]])
        self.assertGreater(float(np.std(edge_columns)), 2.0)
        # Wiggles shorter than a parent cell (30 child cells): the margin is
        # not a smooth curve at the parent's scale only.
        detrended = edge_columns - np.convolve(np.pad(edge_columns.astype(float), 15, mode="edge"), np.ones(31) / 31.0, mode="valid")
        self.assertGreater(float(np.std(detrended)), 0.8)


if __name__ == "__main__":
    unittest.main()
