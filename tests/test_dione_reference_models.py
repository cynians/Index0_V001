import unittest
from types import SimpleNamespace

from world.dione_reference_models import apply_dione_reference_models


class DioneReferenceModelsTests(unittest.TestCase):
    def test_adds_cassini_global_heightmap(self):
        entities = {
            "body_dione": {
                "id": "body_dione",
                "name": "Dione",
                "location_class": "moon",
            }
        }

        self.assertTrue(apply_dione_reference_models(entities))
        dione = entities["body_dione"]
        heightmap = dione["heightmap_model"]
        grid = heightmap["sample_grid"]

        self.assertEqual("dione_cassini_spc_reference_heightmap", heightmap["status"])
        self.assertEqual((257, 129), (grid["width"], grid["height"]))
        self.assertEqual(129, len(grid["rows"]))
        self.assertTrue(all(row[0] == row[-1] for row in grid["rows"]))
        self.assertLess(heightmap["min_elevation_m"], -5000)
        self.assertGreater(heightmap["max_elevation_m"], 4000)
        self.assertEqual("10.26033/bxx6-g543", heightmap["source_models"]["topography"]["doi"])
        self.assertIn("dione_cassini_reference_heightmap", dione["tags"])

    def test_preserves_existing_custom_heightmap(self):
        entities = {
            "body_dione": {
                "id": "body_dione",
                "name": "Dione",
                "location_class": "moon",
                "heightmap_model": {"status": "custom"},
            }
        }

        apply_dione_reference_models(entities)

        self.assertEqual("custom", entities["body_dione"]["heightmap_model"]["status"])

    def test_accepts_loader_style_target(self):
        dione = {"id": "body_dione", "name": "Dione", "location_class": "moon"}
        loader = SimpleNamespace(entities={"body_dione": dione})

        self.assertTrue(apply_dione_reference_models(loader))
        self.assertEqual("dione_cassini_reference", dione["map_status"])


if __name__ == "__main__":
    unittest.main()
