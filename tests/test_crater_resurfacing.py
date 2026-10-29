"""Crater morphology scaling with gravity and volcanic flooding of lowlands."""

import unittest

from simulations.world_gen.heightmap import FLOOD_PLAINS_CRATER_SHARE, condition_crater_model_to_surface
from simulations.world_gen.interior_regime import integrated_volcanic_resurfacing
from simulations.world_gen.tectonics import derive_crater_model


def _craters(gravity_g, radius_m=3_390_000.0, resurfacing=0.0):
    terrain = {
        "map_seed": "crater-physics",
        "map_canvas": {"radius_m": radius_m},
        "cratering": {"density": 0.8, "retention": "high", "resurfacing_fraction": resurfacing, "surface_age_myr": 4500.0},
    }
    return derive_crater_model(terrain, {}, {"surface_gravity_g": gravity_g, "radius_m": radius_m})


def _depth_near(model, diameter_km):
    crater = min(model["craters"], key=lambda item: abs(item["diameter_km"] - diameter_km))
    return crater["diameter_km"], crater["depth_m"], crater["rim_height_m"]


class CraterMorphologyTests(unittest.TestCase):
    def test_complex_craters_are_shallower_under_stronger_gravity(self):
        moon = _depth_near(_craters(0.165), 100.0)
        mars = _depth_near(_craters(0.38), 100.0)
        earth = _depth_near(_craters(1.0), 100.0)
        for diameter, _depth, _rim in (moon, mars, earth):
            self.assertAlmostEqual(100.0, diameter, delta=25.0)
        # Pike (1977): lunar 100 km craters ~4 km deep; Mars ~2-3.5 km; Earth ~1-1.5 km.
        self.assertGreater(moon[1], 3000.0)
        self.assertLess(moon[1], 5500.0)
        self.assertGreater(mars[1], 1500.0)
        self.assertLess(mars[1], 3500.0)
        self.assertLess(earth[1], 1800.0)
        self.assertGreater(moon[1], mars[1])
        self.assertGreater(mars[1], earth[1])
        self.assertLess(mars[2], mars[1] * 0.5, "complex rims are a fraction of the depth")


class VolcanicFloodingTests(unittest.TestCase):
    def test_lava_buries_lowland_craters_and_spares_the_highlands(self):
        model = _craters(0.38, resurfacing=0.5)
        # Terrain rising from a western lowland (-4 km) to an eastern upland (+4 km).
        rows = [[-4000.0 + 8000.0 * column / 64.0 for column in range(65)] for _row in range(33)]
        for row in rows:
            row[-1] = row[0]
        conditioned, audit = condition_crater_model_to_surface(model, {"cratering": {"resurfacing_fraction": 0.5}}, rows, None)
        self.assertAlmostEqual(0.0, audit["volcanic_flood_level_m"], delta=300.0, msg="half the area lies below the flood")
        low = [c for c in conditioned["craters"] if 0.02 < c["x"] < 0.3]
        high = [c for c in conditioned["craters"] if 0.7 < c["x"] < 0.98]
        self.assertTrue(low and high)
        buried_low = sum(c["morphology_preservation"] < 0.05 for c in low) / len(low)
        kept_high = sum(c["morphology_preservation"] > 0.5 for c in high) / len(high)
        self.assertGreater(buried_low, 1.0 - FLOOD_PLAINS_CRATER_SHARE - 0.1, "old craters on the flooded plains are gone")
        self.assertLess(buried_low, 0.97, "younger impacts on the plains survive")
        self.assertGreater(kept_high, 0.95)
        self.assertGreater(audit["flooded_crater_count"], 0)

    def test_resurfaced_area_grows_with_time_integrated_heat_loss(self):
        moon = integrated_volcanic_resurfacing(0.012, {"surface_age_myr": 4500.0})
        mars = integrated_volcanic_resurfacing(0.022, {"surface_age_myr": 4500.0})
        venus = integrated_volcanic_resurfacing(0.07, {"surface_age_myr": 4500.0})
        self.assertLess(moon, mars)
        self.assertLess(mars, venus)
        self.assertAlmostEqual(0.2, moon, delta=0.1)   # lunar maria ~17 %
        self.assertAlmostEqual(0.37, mars, delta=0.12)  # Martian post-Noachian plains
        self.assertGreater(venus, 0.7)
        self.assertLess(integrated_volcanic_resurfacing(0.022, {"surface_age_myr": 1000.0}), mars, "younger surface, less flooding")


if __name__ == "__main__":
    unittest.main()
