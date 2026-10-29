import math
import unittest

import numpy as np

from simulations.world_gen.water_cycle import (
    _lattice_projector,
    _sample_inherited_rows,
    _solve_coupled_annual_climate_arrays,
    derive_water_cycle_model,
)


def _uniform_grid(height, width, value):
    return [[value for _x in range(width)] for _y in range(height)]


def _base_inputs(height=4, width=4):
    base_temperature_rows = _uniform_grid(height, width, 288.0)
    wind_vector_rows = [
        [[0.4, 0.1, 3.0] for _x in range(width)] for _y in range(height)
    ]
    condensation_rows = _uniform_grid(height, width, 0.2)
    ocean_mask = _uniform_grid(height, width, False)
    permanent_ice_rows = _uniform_grid(height, width, False)
    return (
        base_temperature_rows,
        wind_vector_rows,
        condensation_rows,
        ocean_mask,
        permanent_ice_rows,
    )


class WaterCycleClimateSolverNaNTests(unittest.TestCase):
    def test_clean_solve_is_fully_finite(self):
        inputs = _base_inputs()
        result = _solve_coupled_annual_climate_arrays(
            *inputs,
            pressure_bar=1.0,
            hydrology_cycle="normal",
            liquid_water=True,
        )
        temperature_rows = result["temperature_rows_k"]
        self.assertTrue(
            all(math.isfinite(v) for row in temperature_rows for v in row)
        )

    def test_nan_warm_start_seed_is_rejected_not_propagated(self):
        height, width = 4, 4
        inputs = _base_inputs(height, width)
        clean_temperature = _uniform_grid(height, width, 290.0)
        poisoned_temperature = [row[:] for row in clean_temperature]
        poisoned_temperature[1][1] = float("nan")

        initial_climate = {
            "temperature_rows_k": poisoned_temperature,
            "annual_precipitation_rows_mm": _uniform_grid(height, width, 800.0),
            "annual_evapotranspiration_rows_mm": _uniform_grid(height, width, 600.0),
            "annual_potential_evaporation_rows_mm": _uniform_grid(height, width, 900.0),
            "relative_humidity_rows": _uniform_grid(height, width, 0.5),
        }

        result = _solve_coupled_annual_climate_arrays(
            *inputs,
            pressure_bar=1.0,
            hydrology_cycle="normal",
            liquid_water=True,
            initial_climate=initial_climate,
        )

        self.assertFalse(result["warm_started"])
        temperature_rows = result["temperature_rows_k"]
        self.assertTrue(
            all(math.isfinite(v) for row in temperature_rows for v in row),
            "a NaN warm-start seed must not propagate into the solved output",
        )


class WaterCycleRegionalInheritanceTests(unittest.TestCase):
    def test_inland_child_uses_parent_climate_as_solver_seed(self):
        rows = [
            [900.0, 980.0, 1060.0, 1120.0],
            [960.0, 1160.0, 1350.0, 1210.0],
            [880.0, 1040.0, 1280.0, 1180.0],
            [820.0, 930.0, 1010.0, 1090.0],
        ]
        heightmap = {
            "model_version": "regional-test-height-v1",
            "map_seed": "regional-climate-inheritance",
            "map_detail_level": 1,
            "projection": "local_equirectangular",
            "wrap_x": False,
            "region_width_m": 100_000.0,
            "region_height_m": 100_000.0,
            "sample_spacing_x_m": 1_000.0,
            "sample_spacing_y_m": 1_000.0,
            "source_uv_bounds": {
                "min_u": 0.39,
                "max_u": 0.41,
                "min_v": 0.26,
                "max_v": 0.28,
            },
            "sample_grid": {"rows": rows},
            "sea_level_m": 0.0,
        }
        parent_grid = {
            "source_uv_bounds": {
                "min_u": 0.0,
                "max_u": 1.0,
                "min_v": 0.0,
                "max_v": 1.0,
            },
            "temperature_rows_k": _uniform_grid(4, 4, 282.0),
            "annual_precipitation_rows_mm": [
                [90.0, 120.0, 180.0, 210.0],
                [110.0, 150.0, 240.0, 260.0],
                [130.0, 190.0, 300.0, 330.0],
                [100.0, 140.0, 220.0, 250.0],
            ],
            "annual_evapotranspiration_rows_mm": _uniform_grid(4, 4, 80.0),
            "annual_potential_evaporation_rows_mm": _uniform_grid(4, 4, 900.0),
            "relative_humidity_rows": _uniform_grid(4, 4, 0.25),
        }
        terrain = {
            "hydrology": {
                "liquid_water_possible": True,
                "drainage_enabled": True,
                "cycle": "normal",
            }
        }
        result = derive_water_cycle_model(
            terrain,
            heightmap,
            atmosphere={
                "surface_pressure_bar": 1.0,
                "estimated_surface_temperature_k": 282.0,
            },
            seed={"rotation_hours": 24.0},
            planet_id="regional-climate-test",
            parent_climate_model={"climate_grid": parent_grid},
        )
        climate = result["climate_grid"]
        precipitation = climate["annual_precipitation_rows_mm"]
        self.assertEqual(
            "parent_climate_coordinate_seed",
            climate["parent_climate_inheritance"]["solver_seed_source"],
        )
        self.assertGreater(
            max(value for row in precipitation for value in row)
            - min(value for row in precipitation for value in row),
            10.0,
        )
        self.assertTrue(
            all(
                math.isfinite(value)
                for row in precipitation
                for value in row
            )
        )


CIRCUMFERENCE_M = 40_030_000.0
_TERRAIN = {
    "map_seed": "parent-conservation",
    "hydrology": {
        "target_ocean_fraction": 0.45, "liquid_water_possible": True,
        "drainage_enabled": True, "surface_fluid": "water",
    },
}
_ATMOSPHERE = {"estimated_surface_temperature_k": 287.0, "surface_pressure_bar": 1.0}
_SEED = {"axial_tilt_deg": 23.4, "orbital_eccentricity": 0.02}


def _planet_climate():
    """A 65 x 33 planet (625 km samples) with two continents, and its climate."""
    height, width = 33, 65
    rows = [
        [
            round(math.sin(x / width * math.tau * 2.0) * 1400.0 + math.cos(y / height * 5.0) * 600.0, 1)
            for x in range(width)
        ]
        for y in range(height)
    ]
    heightmap = {
        "map_seed": "parent-conservation", "sea_level_m": 0.0, "radius_m": 6_371_000.0,
        "circumference_m": CIRCUMFERENCE_M, "wrap_x": True, "sample_grid": {"rows": rows},
    }
    return derive_water_cycle_model(dict(_TERRAIN), heightmap, _ATMOSPHERE, dict(_SEED))


def _child_of(parent, bounds, samples, relief_m):
    """A regional tile over ``bounds`` (u0, u1, v0, v1): the parent's ground plus zero-mean relief."""
    u0, u1, v0, v1 = bounds
    width, height = samples
    grid = parent["climate_grid"]
    us = [u0 + (u1 - u0) * x / (width - 1) for x in range(width)]
    vs = [v0 + (v1 - v0) * y / (height - 1) for y in range(height)]
    inherited = {
        key: [[_sample_inherited_rows(grid[key], u, v) for u in us] for v in vs]
        for key in ("elevation_rows", "temperature_rows_k", "annual_precipitation_rows_mm")
    }
    rows = [
        [
            inherited["elevation_rows"][y][x] + relief_m * math.sin(x * 1.3) * math.cos(y * 0.9)
            for x in range(width)
        ]
        for y in range(height)
    ]
    heightmap = {
        "map_seed": "parent-conservation:child", "sea_level_m": 0.0, "radius_m": 6_371_000.0,
        "circumference_m": CIRCUMFERENCE_M, "wrap_x": False, "coverage": "regional_patch",
        "map_detail_level": 1, "region_width_m": (u1 - u0) * CIRCUMFERENCE_M,
        "region_height_m": (v1 - v0) * CIRCUMFERENCE_M * 0.5,
        "source_uv_bounds": {"min_u": u0, "max_u": u1, "min_v": v0, "max_v": v1},
        "sample_grid": {"rows": rows},
    }
    child = derive_water_cycle_model(
        dict(_TERRAIN), heightmap, _ATMOSPHERE, dict(_SEED), parent_climate_model=parent,
    )
    return child, rows, inherited


class ParentClimateConservationTests(unittest.TestCase):
    """A child tile reads its parent's air; it adds only what the parent could not resolve."""

    @classmethod
    def setUpClass(cls):
        cls.parent = _planet_climate()
        # Inland on the first continent (elevation peaks at u = 1/8).
        cls.u, cls.v = 0.125, 0.40

    def test_a_tile_finer_than_the_air_can_differ_keeps_its_parents_climate(self):
        # 2 km of ground at 62 m samples with 30 m of relief: the fixed-weight
        # blend made such a tile a degree or two warmer than its parent and
        # re-solved its rain on its own cells.
        span_u = 2_000.0 / CIRCUMFERENCE_M
        bounds = (self.u, self.u + span_u, self.v, self.v + span_u * 2.0)
        child, rows, inherited = _child_of(self.parent, bounds, (33, 33), relief_m=30.0)
        climate = child["climate_grid"]
        record = climate["parent_climate_inheritance"]
        self.assertFalse(record["local_detail"])
        self.assertEqual("parent_climate_without_local_solve", record["solver_seed_source"])
        for y in range(33):
            for x in range(33):
                lapse = (rows[y][x] - inherited["elevation_rows"][y][x]) * 0.0062
                self.assertAlmostEqual(
                    inherited["temperature_rows_k"][y][x] - lapse, climate["temperature_rows_k"][y][x], places=2,
                )
                self.assertAlmostEqual(
                    inherited["annual_precipitation_rows_mm"][y][x], climate["annual_precipitation_rows_mm"][y][x], places=2,
                )

    def test_a_childs_own_detail_averages_out_over_the_parents_samples(self):
        # 2500 x 2000 km at 50 km samples under 625 km parent samples: room
        # for orographic detail, none of it a change of the parent's means.
        span_u = 2_500_000.0 / CIRCUMFERENCE_M
        span_v = 2_000_000.0 / (CIRCUMFERENCE_M * 0.5)
        bounds = (self.u - span_u / 2, self.u + span_u / 2, self.v - span_v / 2, self.v + span_v / 2)
        child, _rows, inherited = _child_of(self.parent, bounds, (51, 41), relief_m=600.0)
        climate = child["climate_grid"]
        self.assertTrue(climate["parent_climate_inheritance"]["local_detail"])
        cells = [(x, y) for y in range(41) for x in range(51)]
        for key, relative in (("temperature_rows_k", 0.0005), ("annual_precipitation_rows_mm", 0.02)):
            differences = [climate[key][y][x] - inherited[key][y][x] for x, y in cells]
            parent_mean = sum(inherited[key][y][x] for x, y in cells) / len(cells)
            self.assertGreater(max(abs(value) for value in differences), parent_mean * relative, key)
            self.assertLess(abs(sum(differences) / len(differences)), parent_mean * relative, key)

    def test_what_the_parents_samples_resolve_is_not_detail(self):
        # 20 cells per parent sample, the first sample 7.5 cells left of the tile.
        projector = _lattice_projector(64, 20.0, -7.5)
        gradient = np.linspace(280.0, 300.0, 64)
        np.testing.assert_allclose(projector @ gradient, gradient, atol=1e-9)
        bump = np.exp(-((np.arange(64) - 30.0) / 3.0) ** 2)
        residual = bump - projector @ bump
        nodes = -7.5 + 20.0 * np.arange(5)
        hats = np.clip(1.0 - np.abs(np.arange(64)[:, None] - nodes[None, :]) / 20.0, 0.0, None)
        # Zero-mean around every parent sample, yet most of the bump is kept.
        np.testing.assert_allclose(hats.T @ residual, 0.0, atol=1e-9)
        self.assertGreater(residual.max(), 0.6)


if __name__ == "__main__":
    unittest.main()
