import math
import unittest

import numpy as np

from simulations.world_gen import alluvial_channels as ac


def _parent(runoff_mm=400.0, precipitation_mm=900.0, evaporation_mm=1000.0):
    rows = lambda value: [[value] * 4 for _ in range(4)]  # noqa: E731
    return {
        "id": "parent",
        "heightmap_model": {"map_seed": "test-seed"},
        "water_cycle_model": {"climate_grid": {
            "annual_runoff_rows_mm": rows(runoff_mm),
            "annual_precipitation_rows_mm": rows(precipitation_mm),
            "annual_potential_evaporation_rows_mm": rows(evaporation_mm),
        }},
        "world_gen_seed": {"derived_planet_physics": {"surface_gravity_m_s2": 9.81}},
    }


def _valley(width=240, height=140, dx=5.0, slope=0.0004):
    x = np.arange(width) * dx
    y = np.arange(height) * dx
    centre = y[height // 2]
    # Flat floor 200 m wide inside walls rising 0.15 m per metre.
    across = np.abs(y[:, None] - centre)
    walls = np.maximum(0.0, across - 100.0) * 0.15
    return 500.0 - slope * x[None, :] + walls + np.zeros((height, 1))


def _run(elevation, *, dx=5.0, level=4, parent=None, parent_spacing=40.0, inflow_m2=4.0e8):
    height, width = elevation.shape
    land = np.ones(elevation.shape, dtype=bool)
    heightmap = {"source_uv_bounds": {"min_u": 0.1, "max_u": 0.1001, "min_v": 0.5, "max_v": 0.50006},
                 "sample_spacing_x_m": dx, "sample_spacing_y_m": dx}
    _dx, _dy, to_local, to_uv = ac.local_frame(heightmap, elevation.shape)
    inflow = np.zeros(elevation.shape)
    inflow[height // 2, 0] = inflow_m2 / (dx * dx)
    residual, record = ac.alluvial_channel_residual(
        elevation, land, level=level, dx=dx, dy=dx, parent_spacing_m=parent_spacing,
        parent_entity=parent or _parent(), to_local=to_local, to_uv=to_uv, seed_text="test",
        inflow_cells=inflow,
    )
    return residual, record, heightmap, to_local


class BankfullGeometryTest(unittest.TestCase):
    def test_width_depth_follow_bank_silt_clay(self):
        sandy = ac.bankfull_geometry(100.0, 5e-4, 3.0, 9.81)
        muddy = ac.bankfull_geometry(100.0, 5e-4, 30.0, 9.81)
        # Schumm: sandy channels are wide and shallow, muddy ones narrow, deep and sinuous.
        self.assertGreater(float(sandy["width_m"]), 2.0 * float(muddy["width_m"]))
        self.assertLess(float(sandy["depth_m"]), float(muddy["depth_m"]))
        self.assertGreater(float(muddy["sinuosity"]), float(sandy["sinuosity"]))
        # Continuity with Chezy resistance: U = Q / (W D) stays in the natural range.
        for geometry in (sandy, muddy):
            velocity = 100.0 / (float(geometry["width_m"]) * float(geometry["depth_m"]))
            self.assertTrue(0.3 < velocity < 3.0, velocity)

    def test_steep_rivers_braid(self):
        gentle = ac.bankfull_geometry(100.0, 2e-4, 10.0, 9.81)
        steep = ac.bankfull_geometry(100.0, 0.01, 10.0, 9.81)
        self.assertLess(float(gentle["braid"]), 0.01)
        self.assertGreater(float(steep["braid"]), 0.99)
        self.assertGreater(float(steep["width_m"]) / float(steep["depth_m"]), 60.0)

    def test_sinuosity_inverts_bessel_relation(self):
        omega = float(ac.deflection_for_sinuosity(1.5))
        t = np.linspace(0.0, math.pi, 2001)
        j0 = np.trapezoid(np.cos(omega * np.sin(t)), t) / math.pi
        self.assertAlmostEqual(1.0 / j0, 1.5, places=2)


class ChannelCarvingTest(unittest.TestCase):
    def test_meandering_channel_is_carved_and_volume_returned_to_levees(self):
        elevation = _valley()
        residual, record, heightmap, to_local = _run(elevation)
        self.assertTrue(record["reaches"], record)
        reach = record["reaches"][0]
        self.assertGreater(reach["sinuosity"], 1.1)
        self.assertLess(reach["braided_share"], 0.5)
        self.assertLess(float(residual.min()), -0.5)
        # Levees hold the carved volume: the net change is small.
        self.assertLess(abs(float(residual.mean())), 0.25 * abs(float(residual[residual < 0].mean())))
        # Point bars: shallow wet fraction on the inside of bends.
        fields = ac.channel_fields(record["reaches"], elevation.shape, dx=5.0, dy=5.0, to_local=to_local)
        inside = fields["in_channel"]
        self.assertTrue(inside.any())
        dry_bed = inside & (fields["water_depth"] <= 0.0)
        self.assertGreater(float(dry_bed.sum()) / float(inside.sum()), 0.05)
        inner = inside & (fields["outer"] < -0.3)
        outer = inside & (fields["outer"] > 0.3)
        self.assertLess(float(fields["depth"][inner].mean()), float(fields["depth"][outer].mean()))

    def test_a_river_wider_than_the_tile_is_still_a_river_on_it(self):
        # A Plot of 100 m in the bed of a river 400 m wide: its centreline runs 90 m beyond the tile's edge.
        along = np.arange(-200.0, 300.0, 5.0)
        reach = {"seed": 7, "points": [[190.0, float(y), 10.0, 400.0, 3.0, 0.0, 0.3, float(y) + 200.0, 0.0, (float(y) + 200.0) / 400.0]
                                       for y in along]}
        fields = ac.channel_fields([reach], (101, 101), dx=1.0, dy=1.0, to_local=lambda u, v: (u, v))
        self.assertTrue(fields["in_channel"].all())
        distance = 190.0 - np.arange(101)[None, :] * np.ones((101, 1))
        np.testing.assert_allclose(fields["distance_m"], distance, atol=0.6)
        self.assertTrue((fields["width_m"] == 400.0).all() and (fields["depth"] > 0.0).all())
        # A river that passes further off than its channel and its levees reach is none here.
        far = {"seed": 7, "points": [[5000.0, float(y), 10.0, 40.0, 3.0, 0.0, 0.3, float(y) + 200.0, 0.0, 0.0] for y in along]}
        gone = ac.channel_fields([far], (101, 101), dx=1.0, dy=1.0, to_local=lambda u, v: (u, v))
        self.assertFalse(gone["in_channel"].any())
        self.assertTrue(np.isinf(gone["distance_m"]).all())

    def test_gate_skips_channels_the_parent_resolved(self):
        elevation = _valley()
        _residual, record, _heightmap, _to_local = _run(elevation, level=5, parent_spacing=1.0)
        self.assertFalse(record["reaches"])

    def test_inherited_reaches_are_not_carved_again(self):
        elevation = _valley()
        residual, record, _heightmap, _to_local = _run(elevation)
        parent = _parent()
        parent["heightmap_model"]["regional_landforms"] = {"landforms": [record]}
        carved = elevation + residual
        child_residual, child_record, _h, _t = _run(carved, level=5, parent=parent, parent_spacing=5.0, dx=5.0)
        self.assertEqual(len(child_record["inherited_reaches"]), len(record["reaches"]))
        self.assertFalse(child_record["reaches"])
        self.assertFalse(np.any(child_residual))

    def test_child_sharpens_inherited_banks_without_moving_parent_scale_mean(self):
        elevation = _valley()
        residual, record, _heightmap, _to_local = _run(elevation)
        parent = _parent()
        parent["heightmap_model"]["regional_landforms"] = {"landforms": [record]}
        child_residual, child_record, _h, _t = _run(elevation + residual, level=5, parent=parent, parent_spacing=20.0)
        self.assertFalse(child_record["reaches"])
        self.assertGreater(child_record["inherited_sharpening_max_m"], 0.1)
        # Only sub-parent-scale structure: the mean over a parent cell stays put.
        from simulations.world_gen.material_routing import box_mean

        self.assertLess(float(np.abs(box_mean(child_residual, 6)).max()), 0.35 * float(np.abs(child_residual).max()))

    def test_deterministic(self):
        elevation = _valley()
        first = _run(elevation)[1]["reaches"][0]["points"]
        second = _run(elevation)[1]["reaches"][0]["points"]
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
