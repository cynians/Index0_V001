import math
import unittest

from simulations.world_gen.water_cycle import (
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


if __name__ == "__main__":
    unittest.main()
