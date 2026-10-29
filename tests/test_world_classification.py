import unittest

from simulations.world_gen.world_classification import (
    infer_world_class,
    is_envelope_world,
)


def _seed(elements, *, radius=2.4866, water=0.08, inventory="dense"):
    return {
        "radius_earth": radius,
        "water_fraction": water,
        "volatile_inventory": inventory,
        "crust_composition": {
            "major_elements": [
                {"symbol": symbol, "abundance_percent": abundance}
                for symbol, abundance in elements
            ],
            "trace_elements": [],
        },
    }


class WorldClassificationTests(unittest.TestCase):
    def test_dense_explicit_rocky_composition_does_not_become_ice_giant(self):
        seed = _seed([
            ("O", 42.16),
            ("Si", 29.50),
            ("Fe", 10.53),
            ("Mg", 4.55),
            ("Al", 3.88),
            ("Ca", 2.98),
            ("C", 1.44),
        ])

        self.assertFalse(is_envelope_world(seed))
        self.assertEqual("desert_terrestrial", infer_world_class(seed))

    def test_hydrogen_helium_composition_remains_an_envelope_world(self):
        seed = _seed(
            [("H", 48.0), ("He", 14.0), ("O", 18.0), ("C", 8.5)],
            radius=3.8,
            water=0.2,
        )

        self.assertTrue(is_envelope_world(seed))
        self.assertEqual("ice_giant", infer_world_class(seed))

    def test_incomplete_legacy_seed_keeps_size_fallback(self):
        seed = {
            "radius_earth": 2.8,
            "water_fraction": 0.1,
            "volatile_inventory": "dense",
        }

        self.assertTrue(is_envelope_world(seed))
        self.assertEqual("ice_giant", infer_world_class(seed))


if __name__ == "__main__":
    unittest.main()
