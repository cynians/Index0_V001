import unittest

import numpy as np

from simulations.world_gen import alluvial_fans as af
from simulations.world_gen.alluvial_channels import local_frame


def _range_front(n=220, dx=100.0, front=90):
    """V-valleys every 4 km (axis 8 % down to the front) above a 0.5 % plain."""
    y, x = np.mgrid[0:n, 0:n].astype(float)
    plain = 500.0 - 0.005 * (y - front) * dx
    depth = np.maximum(front - y, 0.0)
    axis = 500.0 + 0.08 * depth * dx
    tri = np.abs(np.mod(x, 40.0) - 20.0) / 20.0
    walls = np.minimum(600.0, 30.0 * depth) * tri
    return np.where(y < front, axis + walls, plain)


def _parent(precipitation_mm, evaporation_mm, **water):
    rows = lambda value: [[value] * 3 for _ in range(3)]  # noqa: E731
    return {
        "heightmap_model": {"map_seed": "t"},
        "water_cycle_model": {**water, "climate_grid": {
            "annual_precipitation_rows_mm": rows(precipitation_mm),
            "annual_potential_evaporation_rows_mm": rows(evaporation_mm),
        }},
    }


def _frame(shape, dx):
    heightmap = {"source_uv_bounds": {"min_u": 0.1, "max_u": 0.1005, "min_v": 0.5, "max_v": 0.5005},
                 "sample_spacing_x_m": dx, "sample_spacing_y_m": dx}
    return local_frame(heightmap, shape)


def _build(elevation, parent, *, level=2, dx=100.0, parent_spacing=2000.0):
    _dx, _dy, to_local, to_uv = _frame(elevation.shape, dx)
    land = np.ones(elevation.shape, dtype=bool)
    residual, record = af.alluvial_fan_residual(
        elevation, land, level=level, dx=dx, dy=dx, parent_spacing_m=parent_spacing,
        parent_entity=parent, to_local=to_local, to_uv=to_uv,
    )
    return residual, record, to_local


class FanScalingTest(unittest.TestCase):
    def test_bigger_catchments_build_larger_gentler_fans_and_drylands_larger_ones(self):
        small_radius, small_gradient = af.fan_geometry(1.0, 0.5)
        large_radius, large_gradient = af.fan_geometry(100.0, 0.5)
        self.assertGreater(float(large_radius), float(small_radius))
        self.assertLess(float(large_gradient), float(small_gradient))
        self.assertAlmostEqual(float(small_gradient), af.FAN_GRADIENT_AT_1_KM2)
        arid_radius, _ = af.fan_geometry(20.0, 0.9)
        humid_radius, _ = af.fan_geometry(20.0, 0.05)
        self.assertGreater(float(arid_radius), 1.5 * float(humid_radius))


class FanBuildTest(unittest.TestCase):
    def test_fans_form_at_canyon_mouths_and_conserve_mass(self):
        elevation = _range_front()
        residual, record, _to_local = _build(elevation, _parent(200.0, 1800.0))
        fans = [fan for fan in record["fans"] if fan["catchment_km2"] > 10.0]
        self.assertGreaterEqual(len(fans), 5)
        for fan in fans:
            self.assertTrue(1500.0 < fan["radius_m"] < 5000.0, fan)
            self.assertTrue(5.0 < fan["max_thickness_m"] < 150.0, fan)
        # Deposition on the plain below the front, erosion in the mountains.
        self.assertGreater(float(residual[90:130].max()), 10.0)
        self.assertLess(float(residual[:85].min()), 0.0)
        self.assertLess(abs(float(residual.sum())), 1e-6 * float(np.abs(residual).sum()))

    def test_land_no_fan_touches_keeps_its_height_by_the_sea(self):
        # The plain runs down to the sea; its last row stands 20 cm above it, far below the fans.
        elevation = _range_front()
        sea_level = float(elevation[-1].min()) - 0.2
        _dx, _dy, to_local, to_uv = _frame(elevation.shape, 100.0)
        residual, record = af.alluvial_fan_residual(
            elevation, elevation >= sea_level, level=2, dx=100.0, dy=100.0, parent_spacing_m=2000.0,
            parent_entity=_parent(200.0, 1800.0), to_local=to_local, to_uv=to_uv, sea_level=sea_level,
        )
        self.assertGreaterEqual(len(record["fans"]), 5)
        self.assertEqual(float(np.abs(residual[-10:]).max()), 0.0)      # no half-metre step along the shore
        self.assertGreater(float(residual[90:130].max()), 10.0)

    def test_drylands_build_bigger_fans(self):
        elevation = _range_front()
        arid = _build(elevation, _parent(200.0, 1800.0))[1]["fan_cover_fraction"]
        humid = _build(elevation, _parent(1400.0, 900.0))[1]["fan_cover_fraction"]
        self.assertGreater(arid, 2.0 * humid)

    def test_no_running_water_no_fans(self):
        elevation = _range_front()
        _residual, record, _to_local = _build(elevation, _parent(200.0, 1800.0, liquid_water_possible=False))
        self.assertFalse(record["fans"])

    def test_children_find_the_fan_ground_and_do_not_rebuild_it(self):
        elevation = _range_front()
        parent = _parent(200.0, 1800.0)
        residual, record, to_local = _build(elevation, parent)
        built = elevation + residual
        fields = af.fan_surface_fields(record["fans"], built.shape, dx=100.0, dy=100.0, to_local=to_local, elevation=built)
        on_fan = residual > 5.0
        self.assertGreater(float(fields["cover"][on_fan].mean()), 0.8)
        # Mountain ground above the cone is not fan, nor is plain left
        # untouched inside the radius (past the toe, between fans).
        self.assertLess(float(fields["cover"][:80].mean()), 0.02)
        untouched = (np.abs(residual) < 0.05) & np.isfinite(fields["radial"]) & (np.arange(built.shape[0])[:, None] > 92)
        self.assertTrue(untouched.any())
        self.assertLess(float(fields["cover"][untouched].mean()), 0.5)
        # A child of the same grid inherits the fans and builds none there.
        parent["heightmap_model"]["regional_landforms"] = {"landforms": [record]}
        child_residual, child_record, _t = _build(built, parent, level=3, parent_spacing=100.0)
        self.assertEqual(len(child_record["inherited_fans"]), len(record["fans"]))
        self.assertFalse(child_record["fans"])

    def test_gully_mouths_on_a_bank_build_no_fans(self):
        # Parcel scale (1 m cells): terrace gullies 10 m apart, each draining
        # ~0.001 km2, cut a 10 m bank (45 degrees) above a flat floodplain.
        # Without a minimum catchment each mouth built a 20-degree "fan".
        n, front = 160, 110
        y, x = np.mgrid[0:n, 0:n].astype(float)
        above = np.maximum(front - y, 0.0)
        walls = np.abs(np.mod(x, 10.0) - 5.0) / 5.0
        bank = 100.0 + np.minimum(above, 10.0) + 0.01 * np.maximum(above - 10.0, 0.0) + np.minimum(above, 10.0) * 0.1 * walls
        ground = np.where(y < front, bank, 100.0 - 0.002 * (y - front))
        _residual, record, _to_local = _build(ground, _parent(200.0, 1800.0), level=5, dx=1.0, parent_spacing=7.0)
        self.assertFalse(record["fans"])

    def test_deterministic(self):
        elevation = _range_front()
        first = _build(elevation, _parent(200.0, 1800.0))[1]["fans"]
        second = _build(elevation, _parent(200.0, 1800.0))[1]["fans"]
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
