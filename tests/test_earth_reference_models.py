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

        self.assertEqual("heightmap_authored_reference", earth["heightmap_model"]["status"])
        self.assertEqual("earth_reference_atmosphere", earth["atmosphere_model"]["status"])
        self.assertEqual("earth_reference_tectonics", earth["tectonic_model"]["status"])
        self.assertEqual("earth_reference_simulated_climate", earth["water_cycle_model"]["status"])
        self.assertEqual(4096, earth["map_canvas_width_px"])
        self.assertIn("earth_reference_worldgen", earth["tags"])
        self.assertGreater(len(earth["reference_land_polygons"]["polygons"]), 100)
        self.assertEqual("negative_latitude", earth["reference_land_polygons"]["y_axis"])
        grid = earth["heightmap_model"]["sample_grid"]
        self.assertEqual((385, 193), (grid["width"], grid["height"]))
        self.assertEqual(193, len(grid["rows"]))
        self.assertGreater(len(earth["water_cycle_model"]["rivers"]), 500)
        self.assertGreater(len(earth["water_cycle_model"]["reference_lakes"]), 300)
        self.assertIn("annual_runoff_rows_mm", earth["water_cycle_model"]["climate_grid"])
        self.assertIn("NOAA", earth["heightmap_model"]["source"])
        self.assertEqual("materials_authored_earth_reference", earth["natural_material_model"]["status"])
        self.assertIn("mat_basalt", earth["natural_material_model"]["dominant_materials"])

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

    def test_apply_earth_reference_models_replaces_legacy_authored_climate(self):
        entities = {
            "planet_earth": {
                "id": "planet_earth",
                "name": "Earth",
                "type": "location",
                "_dataset": "locations",
                "location_class": "planet",
                "water_cycle_model": {"status": "water_cycle_authored_reference"},
            }
        }

        apply_earth_reference_models(entities)

        self.assertEqual(
            "earth_reference_simulated_climate",
            entities["planet_earth"]["water_cycle_model"]["status"],
        )

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
        self.assertEqual("natural_earth_admin_0_reference", japan["bounds_source"])
        self.assertGreater(len(japan["bounds"]["polygons"]), 1)

    def test_apply_earth_reference_models_materializes_named_country_records(self):
        earth = {
            "id": "planet_earth",
            "name": "Earth",
            "type": "location",
            "_dataset": "locations",
            "location_class": "planet",
        }
        loader = SimpleNamespace(entities={"planet_earth": earth}, datasets={"locations": [earth]})

        apply_earth_reference_models(loader)

        canada = loader.entities["loc_country_can"]
        self.assertEqual("Canada", canada["name"])
        self.assertEqual("country", canada["location_class"])
        self.assertEqual("loc_subregion_northern_america", canada["parent_location"])
        northern_america = loader.entities[canada["parent_location"]]
        self.assertEqual("loc_north_america", northern_america["parent_location"])
        self.assertIn("loc_country_can", northern_america["constituents"])
        self.assertNotIn("loc_country_can", earth.get("constituents", []))
        self.assertEqual("multipolygon", canada["bounds"]["type"])
        self.assertEqual("natural_earth_admin_0_reference", canada["bounds_source"])
        self.assertGreaterEqual(
            len([entity for entity in loader.datasets["locations"] if entity.get("location_class") == "country"]),
            177,
        )
        countries = [
            entity for entity in loader.datasets["locations"]
            if entity.get("location_class") == "country"
        ]
        self.assertTrue(all(
            entity.get("bounds_source") == "natural_earth_admin_0_reference"
            for entity in countries
        ))
        self.assertTrue(all(
            entity.get("parent_location") != "planet_earth"
            and loader.entities[entity["parent_location"]].get("location_class") in {"continent", "region"}
            for entity in countries
        ))

    def test_apply_earth_reference_models_exposes_yangtze_as_selectable_river(self):
        earth = {
            "id": "planet_earth",
            "name": "Earth",
            "type": "location",
            "_dataset": "locations",
            "location_class": "planet",
        }
        loader = SimpleNamespace(entities={"planet_earth": earth}, datasets={"locations": [earth]})

        apply_earth_reference_models(loader)

        yangtze = loader.entities["loc_river_yangtze"]
        self.assertEqual("Yangtze River", yangtze["name"])
        self.assertEqual("river", yangtze["location_class"])
        self.assertEqual("polyline", yangtze["bounds"]["type"])
        self.assertGreater(len(yangtze["bounds"]["paths"]), 3)
        self.assertIn("loc_river_yangtze", earth["constituents"])


if __name__ == "__main__":
    unittest.main()
