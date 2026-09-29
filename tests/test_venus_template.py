import unittest

from simulations.world_gen.atmosphere import derive_atmosphere_model
from simulations.world_gen.crust import estimate_crust_density_kg_m3
from simulations.world_gen.planetary_physics import derive_planet_physics
from simulations.world_gen.world_gen_sim import WorldGenSimulation


class VenusTemplateTests(unittest.TestCase):
    def test_runaway_label_does_not_override_identical_authored_conditions(self):
        template = WorldGenSimulation.PLANET_TEMPLATES["runaway_greenhouse_terrestrial"]
        seed = {
            "planet_template": "runaway_greenhouse_terrestrial",
            "radius_earth": 0.949,
            "core_radius_fraction": 0.52,
            "crust_thickness_km": 30.0,
            "angular_velocity_deg_per_hour": 0.0616,
            "rotation_hours": 5832.5,
            "water_fraction": 0.0001,
            "volatile_inventory": "dense",
            "tectonics_mode": "stagnant_lid",
            "orbital_eccentricity": 0.0068,
            "resolved_map_seed": "venus-cythera-001",
            "crust_composition": {
                "major_elements": [
                    {"symbol": symbol, "abundance_percent": abundance}
                    for symbol, abundance in template["major_elements"]
                ],
                "trace_reserve_percent": 1.0,
                "trace_elements": [
                    {"symbol": "N", "abundance_percent": 0.12},
                    {"symbol": "C", "abundance_percent": 0.08},
                    {"symbol": "Ar", "abundance_percent": 0.01},
                ],
            },
        }
        physics = derive_planet_physics(
            seed,
            crust_density_kg_m3=estimate_crust_density_kg_m3(
                seed["crust_composition"]
            ),
        )
        atmosphere = derive_atmosphere_model(
            seed,
            physics,
            stellar_luminosity_solar=1.0,
            semi_major_axis_au=0.7233,
        )
        same_conditions = {
            **seed,
            "planet_template": "silicate_terrestrial",
        }
        comparison = derive_atmosphere_model(
            same_conditions,
            physics,
            stellar_luminosity_solar=1.0,
            semi_major_axis_au=0.7233,
        )

        self.assertNotIn("atmosphere_regime", template)
        self.assertNotIn("volatile_pressure_scale", template)
        self.assertNotIn("greenhouse_efficiency", template)
        self.assertNotIn("bond_albedo", template)
        self.assertEqual(atmosphere, comparison)


if __name__ == "__main__":
    unittest.main()
