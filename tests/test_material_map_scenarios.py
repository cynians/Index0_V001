import tempfile
import unittest
from pathlib import Path

from tools.verify_material_map_scenarios import SCENARIOS, evaluate_scenario
from simulations.world_gen.material_heatmaps import (
    DEFAULT_MATERIAL_LAYER_LIMIT,
    _lithologic_province_affinity,
    _relax_native_material_field,
    _tectonic_lithology_context,
)


class MaterialMapScenarioTests(unittest.TestCase):
    def test_native_planetary_material_relaxation_removes_column_panels(self):
        rows = [[0.1, 0.9, 0.1, 0.9, 0.1, 0.9] for _ in range(5)]
        corrected = _relax_native_material_field(
            rows,
            [[False] * 6 for _ in range(5)],
            passes=5,
            strength=0.46,
        )
        before = sum(
            abs(row[x + 1] - row[x]) for row in rows for x in range(5)
        )
        after = sum(
            abs(row[x + 1] - row[x])
            for row in corrected
            for x in range(5)
        )
        self.assertLess(after, before * 0.35)

    def test_planetary_layer_budget_can_represent_multiple_geologic_provinces(self):
        self.assertGreaterEqual(DEFAULT_MATERIAL_LAYER_LIMIT, 12)

    def test_lithologic_provinces_are_plate_bound_and_global_uv_stable(self):
        tectonics = {
            "plates": [
                {"id": "continental", "plate_type": "continental", "continentality": 0.9},
                {"id": "oceanic", "plate_type": "oceanic", "continentality": 0.1},
            ],
            "sample_grid": {
                "owners": [[0, 0, 1, 1], [0, 0, 1, 1]],
            },
            "lithosphere_grid": {
                "continental_fraction_rows": [[1.0, 1.0, 0.0, 0.0], [1.0, 1.0, 0.0, 0.0]],
            },
        }
        first = _tectonic_lithology_context(tectonics, 0.2, 0.5, "seed")
        repeated = _tectonic_lithology_context(tectonics, 0.2, 0.5, "seed")
        oceanic = _tectonic_lithology_context(tectonics, 0.8, 0.5, "seed")
        self.assertEqual(first, repeated)
        self.assertEqual("continental", first["plate_id"])
        self.assertEqual("oceanic", oceanic["plate_id"])
        granite = _lithologic_province_affinity(
            "seed", "mat_granite",
            {"category_id": "igneous_intrusive_felsic"},
            {"profile_id": "felsic_bedrock"},
            first,
        )
        ocean_granite = _lithologic_province_affinity(
            "seed", "mat_granite",
            {"category_id": "igneous_intrusive_felsic"},
            {"profile_id": "felsic_bedrock"},
            oceanic,
        )
        self.assertGreater(granite, ocean_granite)

    def test_element_distributions_resolve_at_the_expected_map_scales(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            failures = []
            for scenario in SCENARIOS:
                with self.subTest(scenario=scenario["id"]):
                    result = evaluate_scenario(
                        scenario,
                        Path(temp_dir),
                        image_size=(48, 24),
                    )
                    failures.extend(
                        f"{scenario['id']}: {check['name']}"
                        for check in result["checks"]
                        if not check["passed"]
                    )
                    self.assertGreaterEqual(
                        len(result["planetary_layers"]),
                        3,
                        "A planetary view should retain several physically "
                        "valid substrates or covers without inventing deferred "
                        "minerals and deposits.",
                    )
                    planetary_ids = {
                        layer["material_id"]
                        for layer in result["planetary_layers"]
                    }
                    self.assertFalse(planetary_ids.intersection({
                        "mat_alluvium",
                        "mat_beach_sand",
                        "mat_dune_sand",
                        "mat_lacustrine_mud",
                        "mat_marine_mud",
                    }))
            self.assertEqual([], failures)


if __name__ == "__main__":
    unittest.main()
