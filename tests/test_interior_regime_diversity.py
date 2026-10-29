import unittest

from simulations.world_gen.interior_regime import derive_interior_regime_model
from simulations.world_gen.terrain_seed import derive_terrain_seed_model


class InteriorRegimeDiversityTests(unittest.TestCase):
    def test_intrusive_intermediate_heat_world_uses_plutonic_squishy_lid(self):
        seed = {
            "water_fraction": 0.0,
            "volatile_inventory": "thin",
            "tidal_heating_w_m2": 0.045,
            "crust_composition": {"major_elements": [], "trace_elements": []},
            "map_seed": "plutonic-regime",
        }
        physics = {
            "radius_earth": 1.0,
            "core_radius_fraction": 0.30,
            "mantle_radius_fraction": 0.45,
            "crust_radius_fraction": 0.035,
            "crust_thickness_km": 45.0,
            "surface_gravity_g": 1.0,
            "radius_m": 6_371_000.0,
        }
        atmosphere = {"surface_pressure_bar": 0.10, "estimated_surface_temperature_k": 310.0}
        regime = derive_interior_regime_model(seed, physics, atmosphere)
        self.assertEqual(regime["interior"]["tectonic_regime"], "plutonic_squishy_lid")
        terrain = derive_terrain_seed_model(seed, physics, atmosphere, regime)
        self.assertEqual(terrain["specialized_surface_processes"]["geologic_style"], "plutonic_intrusive_uplands")

    def test_old_cool_world_cannot_force_heat_pipe_tectonics(self):
        seed = {
            "water_fraction": 0.04,
            "volatile_inventory": "thin",
            "tectonics_mode": "heat_pipe",
            "surface_age_myr": 3200.0,
            "crust_composition": {"major_elements": [], "trace_elements": []},
        }
        physics = {
            "radius_earth": 1.6,
            "core_radius_fraction": 0.47,
            "mantle_radius_fraction": 0.51,
            "crust_radius_fraction": 0.02,
            "crust_thickness_km": 80.0,
            "surface_gravity_g": 1.5,
        }
        atmosphere = {
            "surface_pressure_bar": 0.3,
            "estimated_surface_temperature_k": 267.0,
        }

        regime = derive_interior_regime_model(seed, physics, atmosphere)

        self.assertNotEqual("heat_pipe", regime["interior"]["tectonic_regime"])
        self.assertTrue(regime["thermal_evolution"]["heat_pipe_request_rejected"])
        self.assertFalse(
            regime["thermal_evolution"]["heat_pipe_support"]["supported"]
        )

    def test_strong_tidal_heating_supports_requested_heat_pipe(self):
        seed = {
            "water_fraction": 0.0,
            "volatile_inventory": "thin",
            "tectonics_mode": "heat_pipe",
            "surface_age_myr": 2500.0,
            "tidal_heating_w_m2": 0.24,
            "crust_composition": {"major_elements": [], "trace_elements": []},
        }
        physics = {
            "radius_earth": 0.3,
            "core_radius_fraction": 0.5,
            "mantle_radius_fraction": 0.45,
            "crust_radius_fraction": 0.05,
            "crust_thickness_km": 25.0,
            "surface_gravity_g": 0.2,
        }
        atmosphere = {
            "surface_pressure_bar": 0.01,
            "estimated_surface_temperature_k": 150.0,
        }

        regime = derive_interior_regime_model(seed, physics, atmosphere)

        self.assertEqual("heat_pipe", regime["interior"]["tectonic_regime"])
        self.assertEqual(
            "tidal_heating",
            regime["thermal_evolution"]["heat_pipe_support"]["source"],
        )
