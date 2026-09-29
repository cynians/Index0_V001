import tempfile
import unittest
from pathlib import Path

from tools.verify_material_map_scenarios import SCENARIOS, evaluate_scenario
from simulations.world_gen.material_heatmaps import DEFAULT_MATERIAL_LAYER_LIMIT
from simulations.world_gen.natural_materials import configure_material_catalog
from world.persistent_ontology_store import PersistentOntologyStore


def setUpModule():
    rows = PersistentOntologyStore(
        Path(__file__).resolve().parents[1] / "ontology" / "index0.owl"
    ).load_datasets().get("materials") or []
    configure_material_catalog(rows)


class MaterialMapScenarioTests(unittest.TestCase):
    def test_planetary_layer_budget_can_represent_multiple_geologic_provinces(self):
        self.assertGreaterEqual(DEFAULT_MATERIAL_LAYER_LIMIT, 12)

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
                    # Alluvium and sand seas are legitimate planetary areal
                    # cover; shoreline sand and sub-aqueous muds are not
                    # resolved on the planetary land surface.
                    self.assertFalse(planetary_ids.intersection({
                        "mat_beach_sand",
                        "mat_lacustrine_mud",
                        "mat_marine_mud",
                    }))
            self.assertEqual([], failures)


if __name__ == "__main__":
    unittest.main()
