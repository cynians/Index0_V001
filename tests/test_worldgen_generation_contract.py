import copy
import unittest

from simulations.world_gen.generation_contract import (
    build_generation_input_contract,
    contract_fingerprint,
    validate_generation_input_contract,
)
from simulations.world_gen.planetary_evolution import (
    derive_planetary_evolution_model,
    update_causal_provenance,
)


class WorldGenGenerationContractTests(unittest.TestCase):
    def _contract(self):
        return build_generation_input_contract(
            planet={"id": "p", "name": "P", "periapsis_au": 0.8, "apoapsis_au": 1.2},
            seed={
                "planet_template": "silicate_terrestrial", "radius_earth": 1.1,
                "core_radius_fraction": 0.51, "crust_thickness_km": 31.0,
                "angular_velocity_deg_per_hour": 12.0, "water_fraction": 0.42,
                "volatile_inventory": "earthlike", "tectonics_mode": "unknown",
                "map_seed": "contract-test",
                "crust_composition": {"major_elements": [{"symbol": "O", "abundance_percent": 46.0}]},
            },
            system={"id": "sys", "system_age_gyr": 6.2, "constituents": ["star"]},
            star={"id": "star", "spectral_class": "K2V", "luminosity_solar": 0.41, "mass_solar": 0.78},
            year=6400,
        )

    def test_contract_is_stable_and_tamper_evident(self):
        contract = self._contract()
        self.assertEqual(contract["fingerprint_sha256"], contract_fingerprint(contract))
        self.assertIs(contract, validate_generation_input_contract(contract))
        changed = copy.deepcopy(contract)
        changed["first_screen"]["water_fraction"] = 0.9
        with self.assertRaises(ValueError):
            validate_generation_input_contract(changed)

    def test_history_derives_shared_causal_state(self):
        seed = {
            "planet_id": "p", "resolved_map_seed": "history-test",
            "system_age_gyr": 6.2, "stellar_luminosity_solar": 0.41,
            "stellar_mass_solar": 0.78, "stellar_effective_temperature_k": 5050,
            "semi_major_axis_au": 0.7, "orbital_eccentricity": 0.2,
            "water_fraction": 0.3, "surface_age_myr": 1800,
            "derived_planet_physics": {"mass_kg": 6e24, "mass_earth": 1.0, "core_radius_fraction": 0.52, "rotation_period_hours": 30.0},
        }
        atmosphere = {"atmosphere_class": "temperate_nitrogen", "volatile_history": {"outgassed_volatiles_bar": 0.4}}
        regime = {"interior": {"tectonic_regime": "plate_tectonics", "volcanic_activity": "moderate", "internal_heat_w_m2": 0.07}, "surface_processes": {"hydrologic_cycle": "active", "crater_retention": "low"}}
        history = derive_planetary_evolution_model(seed, atmosphere, regime)

        self.assertEqual("planetary-causal-history-v2", history["model_version"])
        self.assertEqual(0.41, history["stellar_environment"]["luminosity_solar"])
        self.assertIn("protoplanetary_disk", history["formation_history"])
        self.assertIn("hill_radius_km", history["orbital_and_spin_history"])
        self.assertIn("volatile_budget", history)
        self.assertEqual("inherit_saved_planetary_boundary_conditions", history["fidelity"]["regional_refinement_contract"])

    def test_spatial_outputs_extend_provenance(self):
        planet = {"planetary_evolution_model": {"causal_provenance": {"schema_version": 1, "nodes": []}}, "heightmap_model": {}, "water_cycle_model": {}}
        provenance = update_causal_provenance(planet)
        ids = {node["id"] for node in provenance["nodes"]}
        self.assertIn("heightfield", ids)
        self.assertIn("hydrology", ids)
        self.assertIs(planet["causal_provenance"], provenance)


if __name__ == "__main__":
    unittest.main()
