import unittest

from simulations.world_gen.atmosphere import derive_atmosphere_model
from simulations.world_gen.planetary_physics import EARTH_MASS_KG, EARTH_RADIUS_M


def _physics():
    return {
        "radius_earth": 1.64,
        "radius_m": EARTH_RADIUS_M * 1.64,
        "mass_earth": 4.12,
        "mass_kg": EARTH_MASS_KG * 4.12,
        "surface_gravity_g": 1.53,
    }


def _seed(major_elements):
    return {
        "planet_class": "carbon_rich_terrestrial",
        "planet_template": "carbon_rich",
        "radius_earth": 1.64,
        "water_fraction": 0.035,
        "volatile_inventory": "thin",
        "crust_composition": {
            "major_elements": [
                {"symbol": symbol, "abundance_percent": abundance}
                for symbol, abundance in major_elements
            ],
            "trace_reserve_percent": 1.0,
            "trace_elements": [
                {"symbol": "N", "abundance_percent": 0.12},
                {"symbol": "Ar", "abundance_percent": 0.01},
            ],
        },
    }


class AtmosphereRedoxTests(unittest.TestCase):
    def test_explicit_massive_rocky_template_is_not_reclassified_as_ice_giant(self):
        seed = _seed([
            ("C", 18.0), ("O", 24.0), ("Si", 23.0),
            ("Fe", 12.0), ("Mg", 9.0), ("S", 2.0),
        ])
        atmosphere = derive_atmosphere_model(
            seed,
            {
                "radius_earth": 2.24,
                "radius_m": EARTH_RADIUS_M * 2.24,
                "mass_earth": 12.8,
                "mass_kg": EARTH_MASS_KG * 12.8,
                "surface_gravity_g": 2.55,
            },
            stellar_luminosity_solar=1.0,
            semi_major_axis_au=1.0,
        )

        self.assertNotIn(
            atmosphere["atmosphere_class"],
            {"gas_giant", "ice_giant", "hot_gas_giant"},
        )

    def test_carbon_rich_crust_drives_reduced_outgassing(self):
        atmosphere = derive_atmosphere_model(
            _seed([
                ("C", 32.0), ("O", 13.0), ("Fe", 13.0),
                ("Mg", 18.0), ("Si", 7.0), ("S", 2.0),
            ]),
            _physics(),
            stellar_luminosity_solar=1.0,
            semi_major_axis_au=1.0,
        )
        gases = {
            row["molecule"]: row["fraction"]
            for row in atmosphere["composition"]
        }

        self.assertEqual("strongly_reduced", atmosphere["outgassing_redox_state"])
        self.assertGreater(gases.get("CO", 0.0), gases.get("CO2", 0.0))
        self.assertGreater(gases.get("CO", 0.0), 0.40)

    def test_oxygen_rich_crust_keeps_oxidized_co2_outgassing(self):
        atmosphere = derive_atmosphere_model(
            _seed([
                ("O", 46.0), ("Si", 27.0), ("Fe", 6.0),
                ("Mg", 4.0), ("C", 0.02), ("S", 0.02),
            ]),
            _physics(),
            stellar_luminosity_solar=1.0,
            semi_major_axis_au=1.0,
        )
        gases = {
            row["molecule"]: row["fraction"]
            for row in atmosphere["composition"]
        }

        self.assertEqual("oxidized", atmosphere["outgassing_redox_state"])
        self.assertGreater(gases.get("CO2", 0.0), gases.get("CO", 0.0))

    def test_mature_wet_temperate_world_draws_down_co2_without_biogenic_oxygen(self):
        seed = _seed([
            ("O", 46.0), ("Si", 27.0), ("Fe", 6.0),
            ("Mg", 4.0), ("C", 0.02), ("S", 0.02),
        ])
        seed.update({
            "planet_class": "terrestrial",
            "planet_template": "silicate_terrestrial",
            "water_fraction": 0.68,
            "volatile_inventory": "earthlike",
            "system_age_gyr": 4.6,
        })
        physics = {
            "radius_earth": 1.0, "radius_m": EARTH_RADIUS_M,
            "mass_earth": 1.0, "mass_kg": EARTH_MASS_KG,
            "surface_gravity_g": 1.0, "rotation_period_hours": 24.0,
            "core_radius_fraction": 0.55,
        }
        atmosphere = derive_atmosphere_model(seed, physics, 1.0, 1.0)
        gases = {row["molecule"]: row["fraction"] for row in atmosphere["composition"]}

        self.assertEqual("temperate_nitrogen", atmosphere["atmosphere_class"])
        self.assertLess(gases.get("CO2", 0.0), 0.06)
        self.assertLess(gases.get("O2", 0.0), 0.01)
        self.assertGreater(gases.get("N2", 0.0), 0.80)


if __name__ == "__main__":
    unittest.main()
