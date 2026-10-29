import unittest

from simulations.world_gen.atmosphere import derive_atmosphere_model
from simulations.world_gen.atmosphere_layers import derive_atmosphere_layer_profile
from simulations.world_gen.planetary_physics import derive_planet_physics


CRUST_COMPOSITION = {
    "major_elements": [
        {"symbol": "O", "abundance_percent": 46.0},
        {"symbol": "Si", "abundance_percent": 28.0},
        {"symbol": "Al", "abundance_percent": 8.0},
        {"symbol": "Fe", "abundance_percent": 5.0},
        {"symbol": "Ca", "abundance_percent": 4.0},
        {"symbol": "Na", "abundance_percent": 2.5},
        {"symbol": "K", "abundance_percent": 2.5},
        {"symbol": "Mg", "abundance_percent": 2.0},
    ],
    "trace_elements": [
        {"symbol": "C", "abundance_percent": 0.2},
        {"symbol": "S", "abundance_percent": 0.2},
        {"symbol": "Ar", "abundance_percent": 0.01},
    ],
    "trace_reserve_percent": 1.0,
}


def _derive(seed, crust_density_kg_m3=2900.0, stellar_luminosity_solar=1.0, with_crust=True):
    if with_crust:
        seed = dict(seed, crust_composition=CRUST_COMPOSITION)
    physics = derive_planet_physics(seed, crust_density_kg_m3)
    atmosphere = derive_atmosphere_model(
        seed, physics,
        stellar_luminosity_solar=stellar_luminosity_solar,
        semi_major_axis_au=seed.get("semi_major_axis_au", 1.0),
    )
    return atmosphere, physics, seed


class AtmosphereLayerProfileTests(unittest.TestCase):
    def test_earthlike_atmosphere_yields_five_ordered_bands(self):
        atmosphere, physics, seed = _derive({
            "radius_earth": 1.0, "water_fraction": 0.7,
            "volatile_inventory": "earthlike", "system_age_gyr": 4.5,
            "atmosphere_regime": "oxygenated_nitrogen",
        })
        profile = derive_atmosphere_layer_profile(atmosphere, physics, seed)

        self.assertEqual("full", profile["band_template"])
        band_names = [band["name"] for band in profile["bands"]]
        self.assertEqual(
            ["troposphere", "stratosphere", "mesosphere", "thermosphere", "exosphere"],
            band_names,
        )
        self.assertGreater(profile["surface_scale_height_km"], 0.0)

        bands = profile["bands"]
        for previous, current in zip(bands, bands[1:]):
            self.assertEqual(previous["top_altitude_km"], current["base_altitude_km"])
            self.assertLess(previous["base_altitude_km"], current["base_altitude_km"])
            self.assertGreaterEqual(previous["top_pressure_bar"] + 1e-9, current["top_pressure_bar"] or 0.0)

        self.assertIsNone(bands[-1]["top_altitude_km"])
        self.assertEqual(0.0, bands[-1]["top_pressure_bar"])
        for band in bands:
            self.assertGreater(band["density_kg_m3"], 0.0)
            self.assertTrue(band["composition"])

    def test_thin_atmosphere_collapses_to_three_bands(self):
        atmosphere, physics, seed = _derive({
            "radius_earth": 0.53, "water_fraction": 0.05,
            "volatile_inventory": "thin", "system_age_gyr": 4.5,
            "atmosphere_regime": "dry_co2", "volatile_pressure_scale": 0.05,
        })
        self.assertEqual("thin", atmosphere.get("atmosphere_state"))
        profile = derive_atmosphere_layer_profile(atmosphere, physics, seed)
        self.assertEqual("thin", profile["band_template"])
        self.assertEqual(
            ["lower_atmosphere", "upper_atmosphere", "exosphere"],
            [band["name"] for band in profile["bands"]],
        )

    def test_gas_giant_uses_envelope_template(self):
        # No authored crust composition: is_envelope_world()'s size/volatile
        # fallback (rather than an elemental H/He check) decides this one.
        atmosphere, physics, seed = _derive({
            "radius_earth": 11.0, "mass_earth": 317.8,
            "volatile_inventory": "dense", "system_age_gyr": 4.5,
            "semi_major_axis_au": 5.2,
        }, with_crust=False)
        self.assertFalse(atmosphere.get("has_solid_surface", True))
        profile = derive_atmosphere_layer_profile(atmosphere, physics, seed)
        self.assertEqual("envelope", profile["band_template"])
        self.assertEqual(
            ["upper_envelope", "deep_envelope", "outer_envelope"],
            [band["name"] for band in profile["bands"]],
        )

    def test_no_pressure_or_composition_yields_no_band_structure(self):
        profile = derive_atmosphere_layer_profile(
            {"surface_pressure_bar": 0.0, "composition": [], "has_solid_surface": True},
            {"radius_m": 6_371_000.0, "surface_gravity_m_s2": 9.80665},
        )
        self.assertEqual([], profile["bands"])
        self.assertIsNone(profile["band_template"])


if __name__ == "__main__":
    unittest.main()
