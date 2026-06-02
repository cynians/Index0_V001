import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from simulations.building.building_sim import BuildingSimulation
from simulations.map.map_simulation import MapSimulation
from world.simulation_context import SimulationContext


class FakeWorldModel:
    def __init__(self, entities):
        self.entities = {entity["id"]: dict(entity) for entity in entities}
        self.refresh_count = 0

    def get_entity(self, entity_id):
        return self.entities.get(entity_id)

    def get_active_entities(self, year, dataset_name=None, entity_type=None):
        entities = list(self.entities.values())
        if dataset_name == "locations":
            entities = [
                entity for entity in entities
                if entity.get("_dataset") == "locations"
            ]
        if entity_type is not None:
            entities = [
                entity for entity in entities
                if entity.get("type") == entity_type
            ]
        return entities

    def get_active_locations(self, year):
        return self.get_active_entities(year, dataset_name="locations", entity_type="location")

    def refresh(self):
        self.refresh_count += 1


class BuildingSimulationTests(unittest.TestCase):
    def _building_sim(self, temp_dir):
        building = {
            "id": "loc_archive_building",
            "name": "Archive Building",
            "type": "location",
            "_dataset": "locations",
            "location_class": "building",
            "bounds": {
                "type": "polygon",
                "coordinate_space": "map_world",
                "points": [(0, 0), (30, 0), (30, 20), (0, 20)],
            },
            "start_year": 100,
        }
        world_model = FakeWorldModel([building])
        context = SimulationContext(
            year=120,
            root_entity_id=building["id"],
            world_model=world_model,
        )
        sim = BuildingSimulation(context)
        sim.LOCATIONS_ENTRY_PATH = Path(temp_dir) / "locations.yaml"
        sim.LOCATIONS_ENTRY_PATH.write_text(
            "- id: loc_archive_building\n"
            "  pretty_name: Archive Building\n"
            "  name: Archive Building\n"
            "  type: location\n"
            "  location_class: building\n"
            "  offspring: []\n"
            "  start_year: 100\n",
            encoding="utf-8",
        )
        return sim

    def test_building_sim_reuses_map_renderer_mode(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            sim = self._building_sim(temp_dir)

            self.assertEqual("map", sim.render_mode)
            self.assertEqual(["locations"], sim.get_available_layer_kinds())
            self.assertEqual("New Room", sim.get_spatial_feature_draft_button_label())

    def test_building_sim_shows_default_floor_for_unplaced_building(self):
        building = {
            "id": "loc_test_building",
            "name": "Test Building",
            "type": "location",
            "_dataset": "locations",
            "location_class": "building",
            "start_year": 2400,
        }
        world_model = FakeWorldModel([building])
        sim = BuildingSimulation(SimulationContext(
            year=2400,
            root_entity_id=building["id"],
            world_model=world_model,
        ))

        layers = sim.get_layers()

        self.assertTrue(layers)
        self.assertEqual("loc_test_building", layers[0]["entity_id"])
        self.assertTrue(layers[0].get("is_virtual_building_floor"))

    def test_generic_map_rooted_on_building_uses_room_workflow(self):
        building = {
            "id": "loc_test_building",
            "name": "Test Building",
            "type": "location",
            "_dataset": "locations",
            "location_class": "building",
            "start_year": 2400,
        }
        world_model = FakeWorldModel([building])
        sim = MapSimulation(SimulationContext(
            year=2400,
            root_entity_id=building["id"],
            world_model=world_model,
        ))
        sim.active_layer_kind = sim.REGION_LAYER_KIND

        self.assertEqual(["locations"], sim.get_available_layer_kinds())
        self.assertEqual("locations", sim.get_active_layer_kind())
        self.assertEqual("New Room", sim.get_spatial_feature_draft_button_label())
        self.assertTrue(sim.can_create_spatial_feature_draft())
        self.assertTrue(sim.get_layers()[0].get("is_virtual_building_floor"))

        sim.draft_spatial_feature_points = [(1, 1), (5, 1), (5, 4), (1, 4)]
        room = sim._build_draft_spatial_feature_record()

        self.assertEqual("location", room["type"])
        self.assertEqual("room", room["location_class"])
        self.assertEqual("loc_test_building", room["parent_location"])

    def test_building_sim_drafts_rooms_as_location_polygons(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            sim = self._building_sim(temp_dir)
            sim.begin_spatial_feature_draft()
            sim.draft_spatial_feature_points = [(1, 1), (10, 1), (10, 8), (1, 8)]

            self.assertTrue(sim.finish_spatial_feature_draft())

            text = sim.LOCATIONS_ENTRY_PATH.read_text(encoding="utf-8")
            self.assertIn("type: location", text)
            self.assertIn("location_class: room", text)
            self.assertIn("room_class: room", text)
            self.assertIn("parent_location: loc_archive_building", text)
            self.assertIn("- id: loc_room_loc_archive_building_001", text)
            self.assertIn("    - id: loc_room_loc_archive_building_001", text)

    def test_building_sim_finishes_room_when_parent_yaml_block_is_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            building = {
                "id": "loc_draft_building",
                "name": "Draft Building",
                "type": "location",
                "_dataset": "locations",
                "location_class": "building",
                "start_year": 2400,
            }
            world_model = FakeWorldModel([building])
            sim = BuildingSimulation(SimulationContext(
                year=2400,
                root_entity_id=building["id"],
                world_model=world_model,
            ))
            sim.LOCATIONS_ENTRY_PATH = Path(temp_dir) / "locations.yaml"
            sim.LOCATIONS_ENTRY_PATH.write_text("", encoding="utf-8")
            sim.begin_spatial_feature_draft()
            sim.draft_spatial_feature_points = [(1, 1), (8, 1), (8, 6), (1, 6)]

            self.assertTrue(sim.finish_spatial_feature_draft())

            text = sim.LOCATIONS_ENTRY_PATH.read_text(encoding="utf-8")
            self.assertIn("- id: loc_room_loc_draft_building_001", text)
            self.assertIn("type: location", text)
            self.assertIn("location_class: room", text)
            self.assertIn("parent_location: loc_draft_building", text)
            self.assertFalse(sim.is_creating_spatial_feature)

    def test_map_region_finish_uses_location_record_without_required_parent_patch(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = {
                "id": "loc_region_root",
                "name": "Root Region",
                "type": "location",
                "_dataset": "locations",
                "location_class": "region",
                "start_year": 2400,
            }
            world_model = FakeWorldModel([root])
            sim = MapSimulation(SimulationContext(
                year=2400,
                root_entity_id=root["id"],
                world_model=world_model,
            ))
            sim.LOCATIONS_ENTRY_PATH = Path(temp_dir) / "locations.yaml"
            sim.LOCATIONS_ENTRY_PATH.write_text("", encoding="utf-8")
            sim.active_layer_kind = sim.REGION_LAYER_KIND
            sim.begin_spatial_feature_draft()
            sim.draft_spatial_feature_points = [(1, 1), (8, 1), (8, 6), (1, 6)]

            self.assertTrue(sim.finish_spatial_feature_draft())

            text = sim.LOCATIONS_ENTRY_PATH.read_text(encoding="utf-8")
            self.assertIn("- id: loc_region_loc_region_root_001", text)
            self.assertIn("type: location", text)
            self.assertIn("location_class: region", text)
            self.assertNotIn("type: spatial_feature", text)

    def test_location_record_append_replaces_existing_failed_finish_record(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            sim = self._building_sim(temp_dir)
            room = {
                "id": "loc_room_loc_archive_building_001",
                "pretty_name": "Draft Room 001",
                "name": "Draft Room 001",
                "type": "location",
                "location_class": "room",
                "room_class": "room",
                "parent_location": "loc_archive_building",
                "notes": "First pass.",
                "bounds": {
                    "type": "polygon",
                    "coordinate_space": "map_world",
                    "points": [(1, 1), (4, 1), (4, 4), (1, 4)],
                },
                "start_year": 120,
                "entry_status": "draft",
            }
            sim._append_location_record(room)
            room["notes"] = "Retry pass."
            sim._append_location_record(room)

            text = sim.LOCATIONS_ENTRY_PATH.read_text(encoding="utf-8")
            self.assertEqual(1, text.count("- id: loc_room_loc_archive_building_001"))
            self.assertIn("Retry pass.", text)

    def test_map_sim_edits_location_polygon_bounds(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            location_path = Path(temp_dir) / "locations.yaml"
            location_path.write_text(
                "- id: loc_room_alpha\n"
                "  pretty_name: Alpha Room\n"
                "  name: Alpha Room\n"
                "  type: location\n"
                "  location_class: room\n"
                "  bounds:\n"
                "    type: polygon\n"
                "    coordinate_space: map_world\n"
                "    points:\n"
                "      - [0, 0]\n"
                "      - [4, 0]\n"
                "      - [4, 4]\n"
                "      - [0, 4]\n"
                "  start_year: 1\n",
                encoding="utf-8",
            )
            world_model = FakeWorldModel([
                {
                    "id": "loc_room_alpha",
                    "name": "Alpha Room",
                    "type": "location",
                    "_dataset": "locations",
                    "location_class": "room",
                    "bounds": {
                        "type": "polygon",
                        "points": [(0, 0), (4, 0), (4, 4), (0, 4)],
                    },
                }
            ])
            sim = MapSimulation(SimpleNamespace(year=1, root_entity_id="loc_room_alpha", world_model=world_model))
            sim.LOCATIONS_ENTRY_PATH = location_path

            self.assertTrue(sim.begin_spatial_feature_polygon_edit("location", "loc_room_alpha"))
            sim.editing_spatial_feature_points = [(0, 0), (6, 0), (6, 5), (0, 5)]
            self.assertTrue(sim.finish_spatial_feature_polygon_edit())

            text = location_path.read_text(encoding="utf-8")
            self.assertIn("- [6, 5]", text)
            self.assertEqual("loc_room_alpha", sim.selected_entity_id)
            self.assertIsNone(sim.selected_spatial_feature_id)


if __name__ == "__main__":
    unittest.main()
