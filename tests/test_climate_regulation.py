import unittest

from simulations.world_gen.climate_regulation import derive_climate_regulation_model


class ClimateRegulationTests(unittest.TestCase):
    def test_wet_tectonic_world_has_coupled_weathering_feedback(self):
        model = derive_climate_regulation_model(
            planet={},
            atmosphere={
                "surface_pressure_bar": 1.0,
                "estimated_surface_temperature_k": 289.0,
                "composition": [{"molecule": "CO2", "fraction": 0.10}],
            },
            regime={
                "interior": {"tectonic_regime": "plate_tectonics", "volcanic_activity": "moderate", "internal_heat_w_m2": 0.08},
                "surface_processes": {},
            },
            water_cycle={
                "liquid_water_possible": True,
                "runoff_summary": {"target_ocean_fraction": 0.50, "mean_land_runoff_mm": 1500.0, "mean_temperature_k": 289.0},
            },
            surface_evolution={"process_means": {"weathering": 0.90, "erosion": 0.90, "deposition": 0.90}},
        )
        self.assertEqual(model["status"], "climate_regulation_diagnosed")
        self.assertTrue(model["climate_stabilizing_feedback"])
        self.assertGreater(model["indices"]["silicate_weathering"], 0.0)
        self.assertTrue(model["carbonate_province_favorable"])

    def test_dry_world_does_not_claim_weathering_regulation(self):
        model = derive_climate_regulation_model(
            planet={},
            atmosphere={"surface_pressure_bar": 0.03, "estimated_surface_temperature_k": 260.0, "composition": []},
            regime={"interior": {"tectonic_regime": "stagnant_lid", "volcanic_activity": "low", "internal_heat_w_m2": 0.02}},
            water_cycle={"liquid_water_possible": False, "runoff_summary": {"target_ocean_fraction": 0.0}},
            surface_evolution={"process_means": {"weathering": 0.0, "erosion": 0.1, "deposition": 0.1}},
        )
        self.assertFalse(model["climate_stabilizing_feedback"])
        self.assertEqual(model["weathering_regime"], "inactive_or_supply_limited")
        self.assertFalse(model["carbonate_province_favorable"])
