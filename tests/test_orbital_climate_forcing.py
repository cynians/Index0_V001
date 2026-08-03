import unittest

import simulations.world_gen.water_cycle as water_cycle_module
from simulations.world_gen.atmosphere import equilibrium_temperature_k
from simulations.world_gen.water_cycle import (
    _sample_inherited_category,
    _sample_inherited_rows,
    derive_water_cycle_model,
)


def _terrain():
    return {
        "map_seed": "orbital-test",
        "hydrology": {
            "target_ocean_fraction": 0.25,
            "liquid_water_possible": True,
            "drainage_enabled": True,
            "surface_fluid": "water",
        },
    }


def _heightmap():
    return {
        "map_seed": "orbital-test",
        "sea_level_m": 0.0,
        "radius_m": 6_371_000.0,
        "circumference_m": 40_030_000.0,
        "wrap_x": True,
        "sample_grid": {
            "rows": [
                [-200.0, 80.0, 260.0, 100.0],
                [-120.0, 350.0, 1050.0, 420.0],
                [-80.0, 180.0, 740.0, 260.0],
                [-220.0, 40.0, 180.0, 50.0],
            ],
        },
    }


class OrbitalClimateForcingTests(unittest.TestCase):
    def test_runoff_summary_separates_authored_target_from_realized_ocean(self):
        terrain = _terrain()
        terrain["hydrology"]["target_ocean_fraction"] = 0.10
        model = derive_water_cycle_model(
            terrain,
            _heightmap(),
            {"estimated_surface_temperature_k": 284.0, "surface_pressure_bar": 1.0},
            {},
        )
        expected = 4 / 16
        self.assertEqual(0.10, model["runoff_summary"]["target_ocean_fraction"])
        self.assertAlmostEqual(
            expected,
            model["runoff_summary"]["realized_ocean_fraction"],
            places=3,
        )

    def test_eccentric_orbit_has_higher_annual_mean_radiative_temperature(self):
        circular = equilibrium_temperature_k(1.0, 1.0, 0.30, eccentricity=0.0)
        eccentric = equilibrium_temperature_k(1.0, 1.0, 0.30, eccentricity=0.40)
        self.assertGreater(eccentric, circular)

    def test_eccentricity_adds_buffered_seasonality_and_extrema(self):
        atmosphere = {"estimated_surface_temperature_k": 284.0, "surface_pressure_bar": 1.0}
        circular = derive_water_cycle_model(_terrain(), _heightmap(), atmosphere, {"axial_tilt_deg": 0.0, "orbital_eccentricity": 0.0})
        eccentric = derive_water_cycle_model(_terrain(), _heightmap(), atmosphere, {"axial_tilt_deg": 0.0, "orbital_eccentricity": 0.40})
        circular_seasonality = circular["climate_grid"]["temperature_seasonality_rows_k"][1][1]
        eccentric_seasonality = eccentric["climate_grid"]["temperature_seasonality_rows_k"][1][1]
        self.assertGreater(eccentric_seasonality, circular_seasonality)
        self.assertLess(
            eccentric["climate_grid"]["seasonal_min_temperature_rows_k"][1][1],
            eccentric["climate_grid"]["temperature_rows_k"][1][1],
        )
        self.assertTrue(eccentric["seasonal_cycle_model"]["enabled"])

    def test_oceanless_world_cannot_generate_rain_fed_tropical_climates(self):
        terrain = _terrain()
        terrain["hydrology"].update({
            "target_ocean_fraction": 0.0,
            "liquid_water_possible": True,
            "drainage_enabled": True,
        })
        heightmap = _heightmap()
        heightmap["sea_level_m"] = -10_000.0
        model = derive_water_cycle_model(
            terrain,
            heightmap,
            {
                "estimated_surface_temperature_k": 339.6,
                "surface_pressure_bar": 8.467,
            },
            {},
        )
        precipitation = model["climate_grid"][
            "annual_precipitation_rows_mm"
        ]
        koppen = {
            value
            for row in model["climate_grid"]["koppen_rows"]
            for value in row
        }
        self.assertEqual(0.0, max(value for row in precipitation for value in row))
        self.assertFalse(koppen.intersection({"Af", "Am", "Aw"}))
        self.assertEqual([], model["rivers"])

    def test_climate_model_exposes_annual_normals_and_koppen_classes(self):
        model = derive_water_cycle_model(
            _terrain(),
            _heightmap(),
            {
                "estimated_surface_temperature_k": 288.0,
                "surface_pressure_bar": 1.0,
            },
            {},
        )
        grid = model["climate_grid"]
        self.assertEqual(len(grid["rows"]), len(grid["koppen_rows"]))
        self.assertEqual(
            len(grid["temperature_rows_k"]),
            len(grid["annual_precipitation_rows_mm"]),
        )
        self.assertIn("relative_humidity_rows", grid)
        self.assertIn("prevailing_wind_rows", grid)
        self.assertTrue(model["koppen_classes"])
        self.assertIn("converged", model["climate_solver"])

    def test_regional_feedback_warm_start_reaches_same_climate_faster(self):
        atmosphere = {
            "estimated_surface_temperature_k": 288.0,
            "surface_pressure_bar": 1.0,
        }
        first = derive_water_cycle_model(
            _terrain(), _heightmap(), atmosphere, {},
        )
        feedback = derive_water_cycle_model(
            _terrain(),
            _heightmap(),
            atmosphere,
            {},
            previous_regional_model=first,
        )

        self.assertTrue(
            feedback["climate_solver"][
                "warm_started_from_previous_regional_state"
            ]
        )
        self.assertLess(
            feedback["climate_solver"]["iterations"],
            first["climate_solver"]["iterations"],
        )
        self.assertTrue(feedback["climate_solver"]["converged"])
        first_precipitation = first["climate_grid"][
            "annual_precipitation_rows_mm"
        ]
        feedback_precipitation = feedback["climate_grid"][
            "annual_precipitation_rows_mm"
        ]
        maximum_relative_change = max(
            abs(feedback_precipitation[y][x] - first_precipitation[y][x])
            / max(1.0, first_precipitation[y][x])
            for y in range(len(first_precipitation))
            for x in range(len(first_precipitation[y]))
        )
        self.assertLess(maximum_relative_change, 0.04)

    def test_array_climate_solver_matches_scalar_equations(self):
        atmosphere = {
            "estimated_surface_temperature_k": 288.0,
            "surface_pressure_bar": 1.0,
        }
        vectorized = derive_water_cycle_model(
            _terrain(), _heightmap(), atmosphere, {},
        )
        installed_numpy = water_cycle_module.np
        try:
            water_cycle_module.np = None
            scalar = derive_water_cycle_model(
                _terrain(), _heightmap(), atmosphere, {},
            )
        finally:
            water_cycle_module.np = installed_numpy

        for field in (
            "temperature_rows_k",
            "annual_precipitation_rows_mm",
            "annual_potential_evaporation_rows_mm",
            "annual_evapotranspiration_rows_mm",
            "relative_humidity_rows",
        ):
            scalar_rows = scalar["climate_grid"][field]
            vectorized_rows = vectorized["climate_grid"][field]
            # numpy's exp() and Python's math.exp() are not required by
            # IEEE754 to be bit-identical (only +,-,*,/ are); after enough
            # solver iterations that can surface as a machine-epsilon-level
            # difference in the last decimal place. Compare to a tolerance
            # appropriate for two independently-vectorized numerical paths
            # computing the same physics, not bit-for-bit equality.
            for scalar_row, vectorized_row in zip(scalar_rows, vectorized_rows):
                for scalar_value, vectorized_value in zip(scalar_row, vectorized_row):
                    self.assertAlmostEqual(scalar_value, vectorized_value, places=6)
        self.assertEqual(
            scalar["climate_solver"],
            vectorized["climate_solver"],
        )

    def test_regional_climate_matches_parent_at_patch_edges(self):
        terrain = _terrain()
        atmosphere = {
            "estimated_surface_temperature_k": 289.0,
            "surface_pressure_bar": 1.0,
        }
        parent_heightmap = {
            "map_seed": "climate-edge-parent",
            "sea_level_m": 0.0,
            "radius_m": 6_371_000.0,
            "circumference_m": 40_030_000.0,
            "wrap_x": True,
            "sample_grid": {
                "rows": [[100.0] * 7 for _row in range(5)],
            },
        }
        parent = derive_water_cycle_model(
            terrain, parent_heightmap, atmosphere, {},
        )
        child_heightmap = {
            "map_seed": "climate-edge-child",
            "sea_level_m": 0.0,
            "radius_m": 6_371_000.0,
            "circumference_m": 4_000_000.0,
            "region_width_m": 4_000_000.0,
            "region_height_m": 2_000_000.0,
            "map_detail_level": 1,
            "wrap_x": False,
            "source_uv_bounds": {
                "min_u": 0.20,
                "max_u": 0.40,
                "min_v": 0.35,
                "max_v": 0.65,
            },
            "sample_grid": {
                "rows": [[100.0] * 7 for _row in range(5)],
            },
        }
        child = derive_water_cycle_model(
            terrain,
            child_heightmap,
            atmosphere,
            {},
            parent_climate_model=parent,
        )
        parent_grid = parent["climate_grid"]
        child_grid = child["climate_grid"]
        for child_y, global_v in ((0, 0.35), (4, 0.65)):
            for child_x, global_u in enumerate(
                [0.20 + index * 0.20 / 6.0 for index in range(7)]
            ):
                self.assertEqual(
                    _sample_inherited_category(
                        parent_grid["rows"], global_u, global_v,
                    ),
                    child_grid["rows"][child_y][child_x],
                )
                self.assertAlmostEqual(
                    _sample_inherited_rows(
                        parent_grid["temperature_rows_k"], global_u, global_v,
                    ),
                    child_grid["temperature_rows_k"][child_y][child_x],
                    places=1,
                )
