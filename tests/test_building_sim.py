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
        self.loader = SimpleNamespace(
            entities=self.entities,
            datasets={"locations": list(self.entities.values())},
            persist_entity=self.persist_entity,
            remove_entity=self.remove_entity,
            set_literal=self.set_literal,
            set_relation=self.set_relation,
            remove_relation=self.remove_relation,
            save_changed_dataset_files=self.save_changed_dataset_files,
        )
        self.refresh_count = 0

    def persist_entity(self, entity, previous_entity_id=None):
        entity_id = entity.get("id")
        if not entity_id:
            return False
        previous_entity_id = previous_entity_id or None
        if previous_entity_id and previous_entity_id != entity_id:
            self.entities.pop(previous_entity_id, None)
        entity["_dataset"] = entity.get("_dataset") or "locations"
        self.entities[entity_id] = entity
        dataset = self.loader.datasets.setdefault(entity["_dataset"], [])
        dataset[:] = [
            item for item in dataset
            if not (isinstance(item, dict) and item.get("id") in {entity_id, previous_entity_id})
        ]
        dataset.append(entity)
        return True

    def remove_entity(self, entity_id, dataset_name=None):
        removed = self.entities.pop(entity_id, None) is not None
        dataset_names = [dataset_name] if dataset_name else list(self.loader.datasets)
        for candidate_name in dataset_names:
            dataset = self.loader.datasets.get(candidate_name, [])
            before_count = len(dataset)
            dataset[:] = [
                item for item in dataset
                if not (isinstance(item, dict) and item.get("id") == entity_id)
            ]
            removed = removed or len(dataset) != before_count
        return removed

    def _relation_ids(self, value):
        if isinstance(value, str):
            return [value] if value else []
        if isinstance(value, dict):
            entity_id = value.get("id") or value.get("entity_id")
            return [entity_id] if entity_id else []
        if isinstance(value, list):
            ids = []
            for item in value:
                for entity_id in self._relation_ids(item):
                    if entity_id not in ids:
                        ids.append(entity_id)
            return ids
        return []

    def set_literal(self, entity_id, field_name, value, persist=True):
        entity = self.entities.get(entity_id)
        if not isinstance(entity, dict) or entity.get(field_name) == value:
            return set()
        entity[field_name] = value
        return {entity_id}

    def set_relation(self, source_id, field_name, target_id, reciprocal_field=None, persist=True):
        source = self.entities.get(source_id)
        target = self.entities.get(target_id)
        if not isinstance(source, dict) or not isinstance(target, dict):
            return set()
        changed = set()
        values = self._relation_ids(source.get(field_name))
        if target_id not in values:
            source[field_name] = values + [target_id]
            changed.add(source_id)
        if reciprocal_field:
            reciprocal = self._relation_ids(target.get(reciprocal_field))
            if source_id not in reciprocal:
                target[reciprocal_field] = reciprocal + [source_id]
                changed.add(target_id)
        return changed

    def remove_relation(self, source_id, field_name, target_id, reciprocal_field=None, persist=True):
        source = self.entities.get(source_id)
        changed = set()
        if isinstance(source, dict):
            values = self._relation_ids(source.get(field_name))
            if target_id in values:
                source[field_name] = [value for value in values if value != target_id]
                changed.add(source_id)
        target = self.entities.get(target_id)
        if reciprocal_field and isinstance(target, dict):
            reciprocal = self._relation_ids(target.get(reciprocal_field))
            if source_id in reciprocal:
                target[reciprocal_field] = [value for value in reciprocal if value != source_id]
                changed.add(target_id)
        return changed

    def save_changed_dataset_files(self, changed_entity_ids=None):
        return None

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

    def test_map_sim_exposes_planet_heightmap_as_base_layer(self):
        planet = {
            "id": "loc_planet_blue",
            "name": "Blue Planet",
            "type": "location",
            "_dataset": "locations",
            "location_class": "planet",
            "bounds": {
                "type": "bbox",
                "min_x": -180,
                "max_x": 180,
                "min_y": -90,
                "max_y": 90,
            },
            "heightmap_model": {
                "status": "heightmap_seeded",
                "projection": "equirectangular",
                "wrap_x": True,
                "wrap_y": False,
                "sample_grid": {
                    "width": 3,
                    "height": 3,
                    "wrap_x": True,
                    "rows": [
                        [0.0, 100.0, 0.0],
                        [-500.0, 1200.0, -500.0],
                        [0.0, 50.0, 0.0],
                    ],
                },
            },
            "start_year": 2400,
        }
        world_model = FakeWorldModel([planet])
        sim = MapSimulation(SimulationContext(
            year=2400,
            root_entity_id=planet["id"],
            world_model=world_model,
        ))

        base_layer = sim.get_heightmap_base_layer()
        layers = sim.get_layers()

        self.assertIsNotNone(base_layer)
        self.assertEqual("heightmap_base", base_layer["shape"])
        self.assertEqual("loc_planet_blue", base_layer["entity_id"])
        self.assertEqual(360, base_layer["width_world"])
        self.assertEqual(180, base_layer["height_world"])
        planet_rect = next(
            layer
            for layer in layers
            if layer.get("shape") == "map_rect" and layer.get("entity_id") == "loc_planet_blue"
        )
        self.assertTrue(planet_rect["has_heightmap_base"])

    def test_building_sim_drafts_rooms_as_location_polygons(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            sim = self._building_sim(temp_dir)
            sim.begin_spatial_feature_draft()
            sim.draft_spatial_feature_points = [(1, 1), (10, 1), (10, 8), (1, 8)]

            self.assertTrue(sim.finish_spatial_feature_draft())

            room = sim.world_model.get_entity("loc_room_loc_archive_building_001")
            building = sim.world_model.get_entity("loc_archive_building")
            self.assertEqual("location", room["type"])
            self.assertEqual("room", room["location_class"])
            self.assertEqual("room", room["room_class"])
            self.assertEqual("loc_archive_building", room["parent_location"])
            self.assertIn("loc_archive_building", room["parents"])
            self.assertIn("loc_room_loc_archive_building_001", building["constituents"])

    def test_building_sim_finishes_room_when_parent_has_no_existing_constituents(self):
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
            sim.begin_spatial_feature_draft()
            sim.draft_spatial_feature_points = [(1, 1), (8, 1), (8, 6), (1, 6)]

            self.assertTrue(sim.finish_spatial_feature_draft())

            room = world_model.get_entity("loc_room_loc_draft_building_001")
            self.assertEqual("location", room["type"])
            self.assertEqual("room", room["location_class"])
            self.assertEqual("loc_draft_building", room["parent_location"])
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
            sim.active_layer_kind = sim.LOCATION_LAYER_KIND
            sim.begin_spatial_feature_draft()
            sim.draft_spatial_feature_points = [(1, 1), (8, 1), (8, 6), (1, 6)]

            self.assertTrue(sim.finish_spatial_feature_draft())

            region = world_model.get_entity("loc_draft_loc_region_root_001")
            self.assertEqual("location", region["type"])
            self.assertEqual("region", region["location_class"])

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
                "wiki_entry": "First pass.",
                "bounds": {
                    "type": "polygon",
                    "coordinate_space": "map_world",
                    "points": [(1, 1), (4, 1), (4, 4), (1, 4)],
                },
                "start_year": 120,
                "entry_status": "draft",
            }
            sim._append_location_record(room)
            room["wiki_entry"] = "Retry pass."
            sim._append_location_record(room)

            locations = [
                entity for entity in sim.world_model.loader.datasets["locations"]
                if entity.get("id") == "loc_room_loc_archive_building_001"
            ]
            self.assertEqual(1, len(locations))
            self.assertEqual("Retry pass.", locations[0]["wiki_entry"])

    def test_map_sim_edits_location_polygon_bounds(self):
        with tempfile.TemporaryDirectory() as temp_dir:
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

            self.assertTrue(sim.begin_spatial_feature_polygon_edit("location", "loc_room_alpha"))
            sim.editing_spatial_feature_points = [(0, 0), (6, 0), (6, 5), (0, 5)]
            self.assertTrue(sim.finish_spatial_feature_polygon_edit())

            self.assertIn((6, 5), world_model.get_entity("loc_room_alpha")["bounds"]["points"])
            self.assertEqual("loc_room_alpha", sim.selected_entity_id)
            self.assertIsNone(sim.selected_spatial_feature_id)

    def test_map_ghost_layers_include_location_topology(self):
        world_model = FakeWorldModel([
            {
                "id": "loc_country",
                "name": "Country",
                "type": "location",
                "_dataset": "locations",
                "location_class": "country",
                "bounds": {"type": "polygon", "points": [(0, 0), (10, 0), (10, 10), (0, 10)]},
                "neighbours": ["loc_neighbour"],
                "overlaps": ["loc_bioregion"],
                "constituents": ["loc_state"],
            },
            {
                "id": "loc_neighbour",
                "name": "Neighbour",
                "type": "location",
                "_dataset": "locations",
                "location_class": "country",
                "bounds": {"type": "polygon", "points": [(11, 0), (20, 0), (20, 10), (11, 10)]},
            },
            {
                "id": "loc_bioregion",
                "name": "Bioregion",
                "type": "location",
                "_dataset": "locations",
                "location_class": "region",
                "bounds": {"type": "polygon", "points": [(5, -2), (15, -2), (15, 6), (5, 6)]},
            },
            {
                "id": "loc_state",
                "name": "State",
                "type": "location",
                "_dataset": "locations",
                "location_class": "state",
                "bounds": {"type": "polygon", "points": [(1, 1), (4, 1), (4, 4), (1, 4)]},
            },
        ])
        sim = MapSimulation(SimulationContext(year=1, root_entity_id="loc_country", world_model=world_model))

        ghost_layers = sim._build_ghost_context_layers()
        ghost_entity_ids = {
            layer.get("entity_id")
            for layer in ghost_layers
            if layer.get("is_ghost_sister")
        }

        self.assertIn("loc_neighbour", ghost_entity_ids)
        self.assertIn("loc_bioregion", ghost_entity_ids)
        self.assertIn("loc_state", ghost_entity_ids)

    def test_scoped_spatial_features_include_states_and_quarters(self):
        world_model = FakeWorldModel([
            {
                "id": "loc_country",
                "name": "Country",
                "type": "location",
                "_dataset": "locations",
                "location_class": "country",
                "bounds": {"type": "polygon", "points": [(0, 0), (20, 0), (20, 20), (0, 20)]},
            },
            {
                "id": "loc_state",
                "name": "State",
                "type": "location",
                "_dataset": "locations",
                "location_class": "state",
                "parent_location": "loc_country",
                "bounds": {"type": "polygon", "points": [(1, 1), (10, 1), (10, 10), (1, 10)]},
            },
            {
                "id": "loc_quarter",
                "name": "Quarter",
                "type": "location",
                "_dataset": "locations",
                "location_class": "quarter",
                "parent_location": "loc_country",
                "bounds": {"type": "polygon", "points": [(11, 1), (18, 1), (18, 8), (11, 8)]},
            },
            {
                "id": "loc_building",
                "name": "Building",
                "type": "location",
                "_dataset": "locations",
                "location_class": "building",
                "parent_location": "loc_country",
                "bounds": {"type": "polygon", "points": [(2, 2), (4, 2), (4, 4), (2, 4)]},
            },
        ])
        sim = MapSimulation(SimulationContext(year=1, root_entity_id="loc_country", world_model=world_model))

        scoped_ids = {feature.get("id") for feature in sim._get_scoped_spatial_features()}

        self.assertIn("loc_state", scoped_ids)
        self.assertIn("loc_quarter", scoped_ids)
        self.assertNotIn("loc_building", scoped_ids)


if __name__ == "__main__":
    unittest.main()
