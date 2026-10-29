"""Physical true-colour controls, seamless noise and date-line continuity."""

import math
import unittest

import numpy as np

from simulations.world_gen.sphere_noise import sphere_fbm, sphere_fbm_table
from simulations.world_gen.surface_geomorphology import wrapped_gradient
from simulations.world_gen.true_color_physics import (
    EARTH_RAYLEIGH_TAU,
    SWEEPING_MOBILITY,
    alter_surface,
    appearance_environment,
    apply_atmosphere,
    direct_illumination_share,
)


def _atmosphere(pressure, composition, *, redox="oxidized", equilibrium_k=255.0, gravity=1.0, surface_k=288.0, cloud=None):
    return {
        "surface_pressure_bar": pressure,
        "equilibrium_temperature_k": equilibrium_k,
        "estimated_surface_temperature_k": surface_k,
        "composition": [{"molecule": key, "fraction": value} for key, value in composition.items()],
        "cloud_model": cloud or {},
        "volatile_budget": {"speciation": {"redox_state": redox}, "surface_gravity_g": gravity},
    }


EARTH = _atmosphere(1.0, {"N2": 0.78, "O2": 0.21, "Ar": 0.01})
TITAN = _atmosphere(1.47, {"N2": 0.94, "CH4": 0.056}, redox="reducing", equilibrium_k=82.0, gravity=0.14, surface_k=94.0)
MARS = _atmosphere(0.006, {"CO2": 0.95, "N2": 0.027, "Ar": 0.02, "H2O": 0.0003}, equilibrium_k=210.0, gravity=0.38, surface_k=210.0)
VENUS = _atmosphere(92.0, {"CO2": 0.965, "N2": 0.035}, equilibrium_k=300.0, gravity=0.9, surface_k=737.0,
                    cloud={"cloud_class": "sulfuric_acid_aerosol_deck", "optical_depth": 28.0})


def _srgb(linear):
    linear = np.clip(np.asarray(linear, dtype=np.float64), 0.0, 1.0)
    return np.where(linear <= 0.0031308, linear * 12.92, 1.055 * linear ** (1.0 / 2.4) - 0.055) * 255.0


class AppearanceEnvironmentTests(unittest.TestCase):
    def test_earth_rayleigh_depth_matches_clear_sky(self):
        env = appearance_environment(EARTH)
        for got, expected in zip(env["rayleigh_tau_rgb"], EARTH_RAYLEIGH_TAU):
            self.assertAlmostEqual(expected, got, delta=expected * 0.1)
        self.assertAlmostEqual(0.20, env["rayleigh_tau_rgb"][2], delta=0.03)

    def test_thicker_air_scatters_more(self):
        # Terraforming lever: Rayleigh depth follows the gas column.
        thin = appearance_environment(_atmosphere(0.5, {"N2": 1.0}))
        thick = appearance_environment(_atmosphere(2.0, {"N2": 1.0}))
        self.assertAlmostEqual(4.0, thick["rayleigh_tau_rgb"][1] / thin["rayleigh_tau_rgb"][1], delta=0.01)
        co2 = appearance_environment(_atmosphere(2.0, {"CO2": 1.0}))
        self.assertGreater(co2["rayleigh_tau_rgb"][1], thick["rayleigh_tau_rgb"][1] * 1.5)

    def test_methane_haze_needs_methane_over_carbon_dioxide(self):
        self.assertAlmostEqual(3.0, appearance_environment(TITAN)["haze_tau"], delta=1.0)
        self.assertEqual(0.0, appearance_environment(EARTH)["haze_tau"])
        oxidized = _atmosphere(1.0, {"N2": 0.9, "CO2": 0.09, "CH4": 0.005})
        self.assertEqual(0.0, appearance_environment(oxidized)["haze_tau"], "CH4/CO2 < 0.1: no organic haze")

    def test_only_airless_surfaces_space_weather(self):
        self.assertGreater(appearance_environment(_atmosphere(0.0, {}))["airless"], 0.99)
        self.assertLess(appearance_environment(MARS)["airless"], 0.01)


class SurfaceAlterationTests(unittest.TestCase):
    def _alter(self, atmosphere, fields=None, fe_percent=8.0, rock=(0.2, 0.2, 0.2)):
        env = appearance_environment(atmosphere, natural_material_model={"element_profile": {"Fe": fe_percent}})
        rgb = np.full((6, 6, 3), rock, dtype=np.float32)
        base = {"aridity": np.full((6, 6), 1.0), "wetness": np.zeros((6, 6)), "age": np.full((6, 6), 1.0),
                "temperature_k": np.full((6, 6), 250.0)}
        base.update(fields or {})
        return alter_surface(rgb, env, base, np.ones((6, 6), bool))

    def test_oxidized_iron_rich_desert_rusts(self):
        out, diag = self._alter(MARS, fe_percent=14.0)
        red, _green, blue = out.reshape(-1, 3).mean(axis=0)
        self.assertGreater(diag["ferric_mean"], 0.3)
        self.assertGreater(red / blue, 2.0)

    def test_reducing_world_does_not_rust_but_buries_under_organics(self):
        out, diag = self._alter(TITAN, fe_percent=14.0, rock=(0.78, 0.86, 0.92))
        self.assertEqual(0.0, diag["ferric_mean"])
        self.assertGreater(diag["organic_mean"], 0.8)
        red, _green, blue = out.reshape(-1, 3).mean(axis=0)
        self.assertLess(out.mean(), 0.3, "ice under hundreds of metres of haze sediment is dark")
        self.assertGreater(red, blue)

    def test_iron_poor_crust_stains_less(self):
        _out, rich = self._alter(MARS, fe_percent=14.0)
        _out, poor = self._alter(MARS, fe_percent=1.0)
        self.assertLess(poor["ferric_mean"], rich["ferric_mean"] * 0.3)


class AtmosphereOpticsTests(unittest.TestCase):
    def test_earth_ocean_is_blue_from_orbit(self):
        out = apply_atmosphere(np.full((1, 1, 3), (0.004, 0.012, 0.03), dtype=np.float32), appearance_environment(EARTH))
        red, green, blue = _srgb(out[0, 0])
        self.assertGreater(blue, green)
        self.assertGreater(green, red)

    def test_titan_column_is_orange(self):
        out = apply_atmosphere(np.full((1, 1, 3), (0.1, 0.07, 0.04), dtype=np.float32), appearance_environment(TITAN))
        red, green, blue = _srgb(out[0, 0])
        self.assertGreater(red, green)
        self.assertGreater(green, blue)
        self.assertGreater(red - blue, 40.0)

    def test_venus_deck_is_bright_pale_yellow(self):
        out = apply_atmosphere(np.full((1, 1, 3), (0.08, 0.08, 0.08), dtype=np.float32), appearance_environment(VENUS))
        red, green, blue = _srgb(out[0, 0])
        self.assertGreater(red, 180.0)
        self.assertGreater(red, blue + 10.0)

    def test_thin_air_barely_changes_the_surface(self):
        surface = np.full((1, 1, 3), (0.3, 0.15, 0.07), dtype=np.float32)
        out = apply_atmosphere(surface, appearance_environment(_atmosphere(0.006, {"CO2": 1.0}, gravity=0.38)))
        self.assertTrue(np.allclose(out, surface, atol=0.02))


class EarthWeatheringTests(unittest.TestCase):
    """Barren-Earth colour follows climate, erosion and rock iron."""

    def _ferric(self, *, temperature, wetness, aridity, runoff=300.0, gradient=0.0005, iron=None):
        env = appearance_environment(EARTH)
        size = 4
        fields = {
            "temperature_k": np.full((size, size), temperature), "wetness": np.full((size, size), wetness),
            "aridity": np.full((size, size), aridity), "runoff_mm": np.full((size, size), runoff),
            "gradient": np.full((size, size), gradient), "age": np.ones((size, size)), "bedrock": np.zeros((size, size)),
        }
        if iron is not None:
            fields["iron_wt_percent"] = iron
        _out, diag = alter_surface(np.full((size, size, 3), 0.25, dtype=np.float32), env, fields, np.ones((size, size), bool))
        return diag

    def test_aridity_index_not_rainfall_decides_deserts(self):
        from simulations.world_gen.surface_exposure import derive_surface_exposure_fields

        heightmap = {"sample_grid": {"rows": [[100.0] * 9 for _ in range(5)]}, "sea_level_m": 0.0, "wrap_x": True,
                     "map_detail_level": 1, "sample_spacing_x_m": 1000.0}
        climate = {"climate_grid": {
            "annual_precipitation_rows_mm": [[180.0] * 4 + [1500.0] * 5 for _ in range(5)],
            "annual_potential_evaporation_rows_mm": [[1500.0] * 4 + [1000.0] * 5 for _ in range(5)],
        }}
        fields = derive_surface_exposure_fields(heightmap, {}, water_cycle=climate, target_size=(9, 5))
        self.assertGreater(float(fields["aridity"][2, 1]), 0.6, "180 mm/yr against 1500 mm/yr demand is a desert")
        self.assertLess(float(fields["wetness"][2, 1]), 0.2)
        self.assertLess(float(fields["aridity"][2, 7]), 0.1)
        self.assertGreater(float(fields["wetness"][2, 7]), 0.6)

    def test_warm_humid_ground_reddens_and_tundra_stays_grey(self):
        tropics = self._ferric(temperature=299.0, wetness=0.7, aridity=0.05, runoff=600.0)
        temperate = self._ferric(temperature=283.0, wetness=0.4, aridity=0.2, runoff=200.0)
        tundra = self._ferric(temperature=268.0, wetness=0.08, aridity=0.8, runoff=30.0)
        self.assertGreater(tropics["alteration_mean"], 0.7)
        self.assertLess(tundra["alteration_mean"], 0.1)
        self.assertGreater(tropics["ferric_mean"], temperate["ferric_mean"])
        self.assertGreater(temperate["ferric_mean"], tundra["ferric_mean"])

    def test_erosion_renews_the_surface(self):
        # Same climate: steep, fast-eroding ground holds grains for a shorter time.
        plains = self._ferric(temperature=288.0, wetness=0.3, aridity=0.3, gradient=0.0005)
        mountains = self._ferric(temperature=288.0, wetness=0.3, aridity=0.3, gradient=0.03)
        self.assertLess(mountains["residence_kyr_median"], plains["residence_kyr_median"] * 0.2)
        self.assertLess(mountains["alteration_mean"], plains["alteration_mean"])

    def test_iron_rich_rock_stains_more_than_iron_poor_rock(self):
        iron = np.full((4, 4), 0.3)
        iron[:, 2:] = 8.0  # limestone | basalt
        env = appearance_environment(EARTH)
        fields = {"temperature_k": np.full((4, 4), 295.0), "wetness": np.full((4, 4), 0.6), "aridity": np.full((4, 4), 0.1),
                  "runoff_mm": np.full((4, 4), 400.0), "age": np.ones((4, 4)), "bedrock": np.zeros((4, 4)), "iron_wt_percent": iron}
        out, _diag = alter_surface(np.full((4, 4, 3), 0.25, dtype=np.float32), env, fields, np.ones((4, 4), bool))
        limestone, basalt = out[:, :2].mean(axis=(0, 1)), out[:, 2:].mean(axis=(0, 1))
        self.assertGreater(basalt[0] / basalt[2], limestone[0] / limestone[2] * 1.3)

    def test_already_ferric_minerals_add_no_fresh_stain(self):
        from unittest import mock

        from simulations.world_gen import natural_materials, true_color

        entries = [
            {"id": "test_limonite", "elemental_composition_wt": {"Fe": 52.7, "O": 47.3}},
            {"id": "test_basalt", "elemental_composition_wt": {"Fe": 8.2, "Si": 23.0}},
        ]
        oxidized = {"test_limonite": 0.88, "test_basalt": 0.0}
        with mock.patch.object(natural_materials, "natural_material_entries", return_value=entries),                 mock.patch.object(natural_materials, "oxidized_family_fraction", side_effect=lambda entry: oxidized[entry["id"]]),                 mock.patch.dict(true_color._MATERIAL_IRON_CACHE, clear=True):
            limonite = true_color._material_iron_percent("test_limonite")
            basalt = true_color._material_iron_percent("test_basalt")
        self.assertAlmostEqual(52.7 * 0.12, limonite, places=3)
        self.assertLess(limonite, basalt, "limonite's iron is already ferric")


class WindAndLightTests(unittest.TestCase):
    def test_wind_sweeps_earth_but_mostly_spares_martian_dust(self):
        earth = appearance_environment(EARTH)
        mars = appearance_environment(MARS)
        self.assertGreater(earth["surface_wind_m_s"], 4.0)
        self.assertLess(earth["surface_wind_m_s"], 20.0)
        self.assertGreater(earth["saltation_mobility"], 3.0)
        self.assertLess(mars["saltation_mobility"], SWEEPING_MOBILITY)
        self.assertLess(appearance_environment(TITAN)["surface_wind_m_s"], 3.0, "weak sunlight, weak winds")

    def test_thicker_martian_air_sweeps_the_dust(self):
        # Terraforming lever: ten times the pressure lifts sand under the mean wind.
        thick = _atmosphere(0.06, {"CO2": 0.95, "N2": 0.05}, equilibrium_k=210.0, gravity=0.38, surface_k=215.0)
        self.assertGreater(appearance_environment(thick)["saltation_mobility"], 2.0 * SWEEPING_MOBILITY)

    def test_dust_stays_on_high_plains_and_leaves_swept_lowlands_darker(self):
        env = appearance_environment(MARS, natural_material_model={"element_profile": {"Fe": 14.0}})
        env["saltation_mobility"] = SWEEPING_MOBILITY  # at the threshold at the datum
        size = 64
        elevation = np.zeros((size, size), dtype=np.float32)
        elevation[:, : size // 2] = -8000.0
        elevation[:, size // 2:] = 8000.0
        fields = {"aridity": np.ones((size, size)), "wetness": np.zeros((size, size)), "age": np.ones((size, size)),
                  "temperature_k": np.full((size, size), 210.0), "bedrock": np.zeros((size, size)), "elevation_m": elevation}
        out, diag = alter_surface(np.full((size, size, 3), 0.06, dtype=np.float32), env, fields, np.ones((size, size), bool))
        low = out[:, 8:24].mean(axis=(0, 1))
        high = out[:, 40:56].mean(axis=(0, 1))
        self.assertLess(diag["mantle_cover"][:, 8:24].mean(), diag["mantle_cover"][:, 40:56].mean() - 0.3)
        self.assertLess(low.mean(), high.mean() * 0.8, "swept basalt is darker than the dusty uplands")

    def test_only_the_direct_beam_shades_relief(self):
        self.assertGreater(direct_illumination_share(appearance_environment(EARTH)), 0.85)
        self.assertLess(direct_illumination_share(appearance_environment(TITAN)), 0.2)
        self.assertLess(direct_illumination_share(appearance_environment(VENUS)), 0.02)
        self.assertEqual(1.0, direct_illumination_share(appearance_environment(_atmosphere(0.0, {}))))
        self.assertLess(
            direct_illumination_share(appearance_environment(MARS), dust_tau=1.5),
            direct_illumination_share(appearance_environment(MARS), dust_tau=0.1),
        )


class SeamlessnessTests(unittest.TestCase):
    def test_gradient_is_periodic_across_the_date_line(self):
        x = np.linspace(0.0, math.tau, 65)  # the date line stored twice
        values = np.tile(np.sin(x + 0.7) * 1000.0, (4, 1))
        _dy, dx = wrapped_gradient(values, 1.0, 1.0, wrap_x=True)
        self.assertAlmostEqual(float(dx[0, 0]), float(dx[0, -1]), places=4)
        self.assertAlmostEqual(float(dx[0, 0]), 1000.0 * math.cos(0.7) * (x[1] - x[0]), delta=1.0)

    """The map-space sinusoids behind the 'diagonal sine curve' artifacts are gone."""

    def test_sphere_noise_wraps_and_matches_its_table(self):
        u = np.linspace(0.0, 1.0, 257)[None, :]
        v = np.linspace(0.0, 1.0, 129)[:, None]
        exact = sphere_fbm("seed", "k", u, v, features=2.0, octaves=3)
        self.assertEqual(0.0, float(np.abs(exact[:, 0] - exact[:, -1]).max()))
        table = sphere_fbm_table("seed", "k", u, v, features=2.0, octaves=3)
        self.assertLess(float(np.abs(table - exact).mean()), 0.01)
        self.assertLess(float(np.abs(exact[0] - exact[0].mean()).max()), 1e-9, "one value at the pole")

    def test_relief_is_continuous_across_the_date_line(self):
        from simulations.world_gen.heightmap import _wave_height

        for style in ("", "aeolian_dune_seas", "episodic_rifting", "heat_pipe_volcanic", "volatile_frost_transport"):
            terrain = {
                "heightfield": {"roughness": 0.6},
                "tectonics": {"enabled": style == "episodic_rifting"},
                "cratering": {"density": 0.0},
                "hydrology": {},
                "specialized_surface_processes": {"geologic_style": style},
            }
            step = 1.0 / 512.0
            seam, inner = [], []
            for ny in np.linspace(0.1, 0.9, 17):
                height = lambda nx: _wave_height(nx, ny, terrain, crater_model={}, map_seed="seam-test", lod0_synthesis=True)  # noqa: E731
                seam.append(abs(height(1.0 - step) - height(0.0)))
                inner.append(abs(height(0.5 + step) - height(0.5)))
            with self.subTest(style or "plain"):
                self.assertLess(float(np.mean(seam)), 3.0 * float(np.mean(inner)) + 1e-4)


if __name__ == "__main__":
    unittest.main()
