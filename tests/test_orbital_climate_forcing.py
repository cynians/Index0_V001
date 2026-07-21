import unittest

from simulations.world_gen.atmosphere import equilibrium_temperature_k
from simulations.world_gen.water_cycle import derive_water_cycle_model


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

