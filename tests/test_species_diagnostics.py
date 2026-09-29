import unittest

from simulations.species.species_diagnostics import build_growth_gallery


class SpeciesDiagnosticsTests(unittest.TestCase):
    def test_growth_gallery_builds_five_stages_and_four_individual_seeds(self):
        cases = build_growth_gallery({
            "id": "diagnostic_tree",
            "common_name": "Diagnostic tree",
            "plant_growth_form": "tree",
            "plant_lifespan": "perennial",
            "mature_height": {"max_m": 12},
        })
        self.assertEqual(20, len(cases))
        self.assertEqual({"seedling", "juvenile", "subadult", "mature", "senescent"}, {case.stage for case in cases})
        self.assertEqual({101, 202, 303, 404}, {case.seed for case in cases})
        self.assertEqual(0, cases[0].snapshot.stats["leaf_count"])
        self.assertGreater(cases[12].snapshot.stats["placement_count"], cases[4].snapshot.stats["placement_count"])
        self.assertNotEqual(
            cases[4].snapshot.to_dict()["placements"],
            cases[5].snapshot.to_dict()["placements"],
        )


if __name__ == "__main__":
    unittest.main()
