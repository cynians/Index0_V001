import unittest
from types import SimpleNamespace

from world.earth_reference_models import apply_earth_reference_models


class EarthReferenceModelTests(unittest.TestCase):
    def test_apply_earth_reference_models_adds_world_gen_fields(self):
        entities = {
            "planet_earth": {
                "id": "planet_earth",
                "name": "Earth",
                "type": "location",
                "_dataset": "locations",
                "location_class": "planet",
            }
        }

        self.assertTrue(apply_earth_reference_models(entities))
        earth = entities["planet_earth"]

        self.assertEqual("earth_reference_heightmap", earth["heightmap_model"]["status"])
        self.assertEqual("earth_reference_atmosphere", earth["atmosphere_model"]["status"])
        self.assertEqual("earth_reference_tectonics", earth["tectonic_model"]["status"])
        self.assertEqual("earth_reference_water_cycle", earth["water_cycle_model"]["status"])
        self.assertEqual(2048, earth["map_canvas_width_px"])
        self.assertIn("earth_reference_worldgen", earth["tags"])
        self.assertGreater(len(earth["reference_land_polygons"]["polygons"]), 100)
        self.assertEqual("negative_latitude", earth["reference_land_polygons"]["y_axis"])

    def test_apply_earth_reference_models_preserves_existing_fields(self):
        entities = {
            "planet_earth": {
                "id": "planet_earth",
                "name": "Earth",
                "type": "location",
                "_dataset": "locations",
                "location_class": "planet",
                "heightmap_model": {"status": "custom"},
            }
        }

        apply_earth_reference_models(entities)

        self.assertEqual("custom", entities["planet_earth"]["heightmap_model"]["status"])

    def test_apply_earth_reference_models_adds_missing_surface_regions_to_loader(self):
        earth = {
            "id": "planet_earth",
            "name": "Earth",
            "type": "location",
            "_dataset": "locations",
            "location_class": "planet",
        }
        loader = SimpleNamespace(entities={"planet_earth": earth}, datasets={"locations": [earth]})

        apply_earth_reference_models(loader)

        self.assertIn("loc_africa", loader.entities)
        self.assertIn("loc_pacific_ocean", loader.entities)
        self.assertIn("loc_africa", earth["constituents"])
        self.assertIn(
            "loc_africa",
            {entity["id"] for entity in loader.datasets["locations"]},
        )
        self.assertEqual("planet_earth", loader.entities["loc_africa"]["parent_location"])
        self.assertEqual("multipolygon", loader.entities["loc_africa"]["bounds"]["type"])
        self.assertGreater(len(loader.entities["loc_africa"]["bounds"]["polygons"]), 20)
        self.assertEqual("natural_earth_reference", loader.entities["loc_africa"]["bounds_source"])

    def test_apply_earth_reference_models_refreshes_generated_surface_region_shapes(self):
        earth = {
            "id": "planet_earth",
            "name": "Earth",
            "type": "location",
            "_dataset": "locations",
            "location_class": "planet",
            "constituents": ["loc_africa"],
        }
        africa = {
            "id": "loc_africa",
            "name": "Africa",
            "type": "location",
            "_dataset": "locations",
            "location_class": "continent",
            "parent_location": "planet_earth",
            "map_reference_generated": True,
            "bounds": {
                "type": "bbox",
                "coordinate_space": "map_world",
                "min_x": -18.0,
                "max_x": 52.0,
                "min_y": -37.0,
                "max_y": 35.0,
            },
            "card_color": "#7b6a3f",
        }
        loader = SimpleNamespace(
            entities={"planet_earth": earth, "loc_africa": africa},
            datasets={"locations": [earth, africa]},
        )

        self.assertTrue(apply_earth_reference_models(loader))

        self.assertEqual("multipolygon", africa["bounds"]["type"])
        self.assertEqual("#8f7744", africa["card_color"])

    def test_apply_earth_reference_models_updates_existing_country_region_geometry(self):
        earth = {
            "id": "planet_earth",
            "name": "Earth",
            "type": "location",
            "_dataset": "locations",
            "location_class": "planet",
        }
        japan = {
            "id": "loc_japan",
            "name": "Japan",
            "type": "location",
            "_dataset": "locations",
            "location_class": "country",
            "parent_location": "planet_earth",
            "bounds": {"type": "bbox", "min_x": 120, "max_x": 150, "min_y": -45, "max_y": -20},
        }
        loader = SimpleNamespace(
            entities={"planet_earth": earth, "loc_japan": japan},
            datasets={"locations": [earth, japan]},
        )

        self.assertTrue(apply_earth_reference_models(loader))

        self.assertEqual("multipolygon", japan["bounds"]["type"])
        self.assertEqual("natural_earth_reference", japan["bounds_source"])
        self.assertGreater(len(japan["bounds"]["polygons"]), 1)


if __name__ == "__main__":
    unittest.main()
