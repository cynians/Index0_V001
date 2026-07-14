import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import pygame

from simulations.building.building_sim import BuildingSimulation
from simulations.bioregion.bioregion_simulation import BioregionSimulation
from simulations.map.map_simulation import MapSimulation
from world.simulation_context import SimulationContext


class FakeWorldModel:
    def __init__(self, entities, timeline_items=None):
        self.entities = {entity["id"]: dict(entity) for entity in entities}
        self.timeline_items = list(timeline_items or [])
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

    def get_timeline_items(self):
        return list(self.timeline_items)

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

    def test_map_sim_creates_point_location_draft(self):
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
            "start_year": 2400,
        }
        world_model = FakeWorldModel([planet])
        sim = MapSimulation(SimulationContext(
            year=2400,
            root_entity_id=planet["id"],
            world_model=world_model,
        ))

        self.assertTrue(sim.begin_point_location_draft("site"))
        sim.draft_point_location_pos = (12.5, -4.25)

        self.assertTrue(sim.can_finish_map_editor())
        self.assertTrue(sim.finish_map_editor())

        created = world_model.get_entity(sim.last_saved_location_id)
        self.assertEqual("site", created["location_class"])
        self.assertEqual("point_location", created["location_role"])
        self.assertEqual("loc_planet_blue", created["parent_location"])
        self.assertEqual({"type": "point", "coordinate_space": "map_world", "x": 12.5, "y": -4.25}, created["coords"])

        layers = sim.get_layers()
        point_layers = [layer for layer in layers if layer.get("entity_id") == created["id"]]
        self.assertEqual("marker", point_layers[0]["shape"])

    def test_map_editor_enter_finishes_and_escape_cancels(self):
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
            "start_year": 2400,
        }
        world_model = FakeWorldModel([planet])
        sim = MapSimulation(SimulationContext(
            year=2400,
            root_entity_id=planet["id"],
            world_model=world_model,
        ))

        self.assertTrue(sim.begin_point_location_draft("site"))
        self.assertIn("Esc cancel", sim.get_map_editor_status_label())
        sim.draft_point_location_pos = (12.5, -4.25)
        self.assertIn("Enter finish", sim.get_map_editor_status_label())
        self.assertTrue(sim.consumes_global_keydown())
        self.assertTrue(sim.handle_event(SimpleNamespace(type=pygame.KEYDOWN, key=pygame.K_RETURN)))
        self.assertFalse(sim.is_map_editor_active())
        self.assertIsNotNone(world_model.get_entity(sim.last_saved_location_id))

        self.assertTrue(sim.begin_point_location_draft("site"))
        sim.draft_point_location_pos = (18.0, -2.0)
        previous_saved_id = sim.last_saved_location_id
        self.assertTrue(sim.handle_event(SimpleNamespace(type=pygame.KEYDOWN, key=pygame.K_ESCAPE)))
        self.assertFalse(sim.is_map_editor_active())
        self.assertEqual(previous_saved_id, sim.last_saved_location_id)

    def test_planet_radius_overrides_tiny_placeholder_bbox(self):
        planet = {
            "id": "loc_planet_blue",
            "name": "Blue Planet",
            "type": "location",
            "_dataset": "locations",
            "location_class": "planet",
            "radius_m": 6_371_000.0,
            "bounds": {
                "type": "bbox",
                "min_x": -0.5,
                "max_x": 0.5,
                "min_y": -0.25,
                "max_y": 0.25,
            },
            "heightmap_model": {
                "status": "heightmap_seeded",
                "sample_grid": {
                    "width": 3,
                    "height": 3,
                    "rows": [
                        [0.0, 100.0, 0.0],
                        [-500.0, 1200.0, -500.0],
                        [0.0, 50.0, 0.0],
                    ],
                },
            },
        }
        world_model = FakeWorldModel([planet])
        sim = MapSimulation(SimulationContext(
            year=2400,
            root_entity_id=planet["id"],
            world_model=world_model,
        ))

        base_layer = sim.get_heightmap_base_layer()

        self.assertIsNotNone(base_layer)
        self.assertGreater(base_layer["width_world"], 350.0)
        self.assertGreater(base_layer["height_world"], 175.0)
        self.assertGreater(sim.bounds["max_x"] - sim.bounds["min_x"], 350.0)
        self.assertGreater(sim.bounds["max_y"] - sim.bounds["min_y"], 175.0)

    def test_map_sim_exposes_worldgen_hydrology_layer_for_planet_root(self):
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
                "sample_grid": {
                    "width": 3,
                    "height": 3,
                    "rows": [
                        [0.0, 100.0, 0.0],
                        [-500.0, 1200.0, -500.0],
                        [0.0, 50.0, 0.0],
                    ],
                },
            },
            "water_cycle_model": {
                "status": "water_cycle_seeded",
                "climate_grid": {
                    "width": 3,
                    "height": 3,
                    "rows": [
                        ["arid", "arid", "arid"],
                        ["temperate_dry", "highland", "temperate_dry"],
                        ["arid", "arid", "arid"],
                    ],
                    "elevation_rows": [
                        [0.0, 100.0, 0.0],
                        [-500.0, 1200.0, -500.0],
                        [0.0, 50.0, 0.0],
                    ],
                },
                "climate_zones": [
                    {"id": "arid", "label": "Arid", "color": [196, 176, 118], "fraction": 0.66},
                    {"id": "highland", "label": "Highland", "color": [138, 128, 118], "fraction": 0.11},
                ],
                "rivers": [
                    {"id": "river_01", "points": [{"x": 0.5, "y": 0.4}, {"x": 0.6, "y": 0.7}], "flow": 0.4},
                ],
            },
            "start_year": 2400,
        }
        world_model = FakeWorldModel([planet])
        sim = MapSimulation(SimulationContext(
            year=2400,
            root_entity_id=planet["id"],
            world_model=world_model,
        ))

        self.assertIn(sim.HEIGHTMAP_LAYER_KIND, sim.get_available_layer_kinds())
        self.assertIn(sim.HYDROLOGY_LAYER_KIND, sim.get_available_layer_kinds())
        self.assertTrue(sim.set_active_layer_kind(sim.HYDROLOGY_LAYER_KIND))

        layers = sim.get_layers()

        self.assertEqual(1, len(layers))
        self.assertEqual("hydrology_climate", layers[0]["shape"])
        self.assertEqual("loc_planet_blue", layers[0]["entity_id"])
        self.assertEqual("water_cycle_seeded", layers[0]["water_cycle_model"]["status"])

    def test_map_sim_exposes_material_heatmap_layer_for_planet_root(self):
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
                "sample_grid": {
                    "width": 3,
                    "height": 3,
                    "rows": [
                        [0.0, 100.0, 0.0],
                        [-500.0, 1200.0, -500.0],
                        [0.0, 50.0, 0.0],
                    ],
                },
            },
            "material_heatmap_model": {
                "status": "generated",
                "composite_layer": {
                    "name": "Composite Material Heatmap",
                    "image_path": "assets/maps/material_heatmaps/loc_planet_blue/composite_materials.png",
                },
                "layers": [
                    {
                        "id": "heatmap_mat_basalt",
                        "material_id": "mat_basalt",
                        "name": "Basalt",
                        "image_path": "assets/maps/material_heatmaps/loc_planet_blue/mat_basalt.png",
                        "confidence": 0.82,
                    }
                ],
            },
            "start_year": 2400,
        }
        world_model = FakeWorldModel([planet])
        sim = MapSimulation(SimulationContext(
            year=2400,
            root_entity_id=planet["id"],
            world_model=world_model,
        ))

        self.assertIn(sim.MATERIAL_HEATMAP_LAYER_KIND, sim.get_available_layer_kinds())
        self.assertTrue(sim.set_active_layer_kind(sim.MATERIAL_HEATMAP_LAYER_KIND))
        layers = sim.get_layers()

        self.assertEqual(1, len(layers))
        self.assertEqual("image_rect", layers[0]["shape"])
        self.assertEqual("loc_planet_blue", layers[0]["entity_id"])
        self.assertEqual("assets/maps/material_heatmaps/loc_planet_blue/composite_materials.png", layers[0]["image_path"])

        items = sim.get_material_distribution_items()
        self.assertEqual(["composite", "mat_basalt"], [item["id"] for item in items])
        self.assertTrue(sim.set_active_material_distribution_item("mat_basalt"))
        self.assertEqual("assets/maps/material_heatmaps/loc_planet_blue/mat_basalt.png", sim.get_layers()[0]["image_path"])

    def test_map_sim_exposes_bundled_material_heatmap_layer_for_planet_root(self):
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
            "material_heatmap_model": {
                "status": "generated",
                "storage_format": "index0_raster_bundle",
                "bundle_path": "assets/maps/material_heatmaps/loc_planet_blue.i0r",
                "composite_layer": {
                    "name": "Composite Material Heatmap",
                    "bundle_path": "assets/maps/material_heatmaps/loc_planet_blue.i0r",
                    "bundle_layer_id": "composite",
                },
                "layers": [
                    {
                        "id": "heatmap_mat_basalt",
                        "material_id": "mat_basalt",
                        "name": "Basalt",
                        "bundle_path": "assets/maps/material_heatmaps/loc_planet_blue.i0r",
                        "bundle_layer_id": "heatmap_mat_basalt",
                        "confidence": 0.82,
                    }
                ],
            },
            "start_year": 2400,
        }
        world_model = FakeWorldModel([planet])
        sim = MapSimulation(SimulationContext(
            year=2400,
            root_entity_id=planet["id"],
            world_model=world_model,
        ))

        self.assertIn(sim.MATERIAL_HEATMAP_LAYER_KIND, sim.get_available_layer_kinds())
        self.assertTrue(sim.set_active_layer_kind(sim.MATERIAL_HEATMAP_LAYER_KIND))
        layers = sim.get_layers()
        self.assertEqual(1, len(layers))
        self.assertEqual("assets/maps/material_heatmaps/loc_planet_blue.i0r", layers[0]["bundle_path"])
        self.assertEqual("composite", layers[0]["bundle_layer_id"])

        items = sim.get_material_distribution_items()
        self.assertEqual(["composite", "mat_basalt"], [item["id"] for item in items])
        self.assertTrue(sim.set_active_material_distribution_item("mat_basalt"))
        self.assertEqual("heatmap_mat_basalt", sim.get_layers()[0]["bundle_layer_id"])

    def test_map_sim_defaults_to_combined_map_layer(self):
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
            "start_year": 2400,
        }
        world_model = FakeWorldModel([planet])
        sim = MapSimulation(SimulationContext(
            year=2400,
            root_entity_id=planet["id"],
            world_model=world_model,
        ))

        self.assertEqual(sim.LOCATION_LAYER_KIND, sim.get_active_layer_kind())
        self.assertEqual("Map + Locations", sim.get_active_layer_label())
        self.assertEqual("map_rect", sim.get_layers()[0]["shape"])

    def test_location_layer_tree_preserves_hierarchy(self):
        planet = {
            "id": "loc_planet_blue",
            "name": "Blue Planet",
            "type": "location",
            "_dataset": "locations",
            "location_class": "planet",
            "constituents": ["loc_region_alpha"],
            "start_year": 2400,
        }
        region = {
            "id": "loc_region_alpha",
            "name": "Alpha Region",
            "type": "location",
            "_dataset": "locations",
            "location_class": "region",
            "parent_location": "loc_planet_blue",
            "constituents": ["loc_site_beta"],
            "start_year": 2400,
        }
        site = {
            "id": "loc_site_beta",
            "name": "Beta Site",
            "type": "location",
            "_dataset": "locations",
            "location_class": "site",
            "parent_location": "loc_region_alpha",
            "start_year": 2400,
        }
        world_model = FakeWorldModel([planet, region, site])
        sim = MapSimulation(SimulationContext(
            year=2400,
            root_entity_id=planet["id"],
            world_model=world_model,
        ))

        items = sim.get_location_layer_tree_items()

        self.assertEqual(
            [("loc_region_alpha", 0), ("loc_site_beta", 1)],
            [(item["id"], item["depth"]) for item in items],
        )
        self.assertTrue(sim.select_location_from_layer_tree("loc_site_beta"))
        self.assertEqual("locations", sim.get_active_layer_kind())
        self.assertEqual("loc_site_beta", sim.selected_entity_id)

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

    def test_planet_map_can_draft_country_and_point_site_locations(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = {
                "id": "planet_test",
                "name": "Test Planet",
                "type": "location",
                "_dataset": "locations",
                "location_class": "planet",
                "radius_m": 6_371_000,
                "start_year": 2400,
            }
            world_model = FakeWorldModel([root])
            sim = MapSimulation(SimulationContext(
                year=2400,
                root_entity_id=root["id"],
                world_model=world_model,
            ))

            option_ids = {option["id"] for option in sim.get_location_draft_options()}
            self.assertIn("continent", option_ids)
            self.assertIn("country", option_ids)
            self.assertIn("site", option_ids)

            self.assertTrue(sim.begin_location_draft("country"))
            sim.draft_spatial_feature_points = [(1, 1), (8, 1), (8, 6), (1, 6)]
            self.assertTrue(sim.finish_map_editor())

            country = world_model.get_entity("loc_draft_country_planet_test_001")
            self.assertEqual("country", country["location_class"])
            self.assertEqual("planet_test", country["parent_location"])

            self.assertTrue(sim.begin_point_location_draft("site"))
            sim.draft_point_location_pos = (12.5, -4.25)
            self.assertTrue(sim.finish_map_editor())

            site = world_model.get_entity("loc_draft_site_planet_test_001")
            self.assertEqual("site", site["location_class"])
            self.assertEqual("point_location", site["location_role"])
            self.assertEqual("planet_test", site["parent_location"])

    def test_airless_seeded_map_root_does_not_render_as_gas_giant(self):
        root = {
            "id": "planet_airless",
            "name": "Airless",
            "type": "location",
            "_dataset": "locations",
            "location_class": "planet",
            "world_gen_template": "cratered_airless",
            "surface_render_mode": "gas_giant_bands",
            "map_render_mode": "gas_giant_bands",
            "map_status": "gas_giant_envelope_modeled",
            "atmosphere_model": {"has_solid_surface": False, "surface_pressure_bar": 100.0},
            "world_gen_seed": {
                "planet_template": "cratered_airless",
                "planet_class": "airless_rocky",
                "radius_earth": 0.35,
                "water_fraction": 0.0,
                "volatile_inventory": "none",
            },
            "tags": ["gas_giant", "gas_giant_bands"],
        }
        world_model = FakeWorldModel([root])
        sim = MapSimulation(SimulationContext(
            year=2400,
            root_entity_id=root["id"],
            world_model=world_model,
        ))

        self.assertFalse(sim._entity_is_gas_giant(root))

    def test_ground_material_layer_finish_uses_location_record(self):
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
        self.assertTrue(sim.set_active_layer_kind(sim.GROUND_MATERIALS_LAYER_KIND))
        sim.begin_spatial_feature_draft()
        sim.draft_spatial_feature_points = [(1, 1), (8, 1), (8, 6), (1, 6)]

        self.assertTrue(sim.finish_spatial_feature_draft())

        region = next(
            entity
            for entity in world_model.entities.values()
            if entity.get("parent_location") == "loc_region_root"
            and entity.get("layer_kind") == sim.GROUND_MATERIALS_LAYER_KIND
        )
        self.assertEqual("location", region["type"])
        self.assertEqual("locations", region["_dataset"])
        self.assertEqual("region", region["location_class"])
        self.assertEqual(sim.GROUND_MATERIALS_LAYER_KIND, region["layer_kind"])
        self.assertNotIn("spatial_features", world_model.loader.datasets)

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

    def test_map_sim_uses_authoring_bounds_for_undefined_non_planet_root(self):
        world_model = FakeWorldModel([
            {
                "id": "loc_empty_parent",
                "name": "Empty Parent",
                "type": "location",
                "_dataset": "locations",
                "location_class": "island",
            }
        ])
        sim = MapSimulation(SimulationContext(year=2400, root_entity_id="loc_empty_parent", world_model=world_model))

        self.assertEqual(-100.0, sim.bounds["min_x"])
        self.assertEqual(100.0, sim.bounds["max_x"])
        self.assertEqual(-75.0, sim.bounds["min_y"])
        self.assertEqual(75.0, sim.bounds["max_y"])
        self.assertEqual(sim.LOCATION_LAYER_KIND, sim.get_active_layer_kind())

    def test_map_sim_reopens_defined_local_polygon_on_location_layer(self):
        world_model = FakeWorldModel([
            {
                "id": "loc_child",
                "name": "Child Region",
                "type": "location",
                "_dataset": "locations",
                "location_class": "region",
                "bounds": {
                    "type": "polygon",
                    "coordinate_space": "map_world",
                    "points": [(10, 20), (40, 20), (40, 50), (10, 50)],
                },
            }
        ])
        sim = MapSimulation(SimulationContext(year=2400, root_entity_id="loc_child", world_model=world_model))

        self.assertEqual(10.0, sim.bounds["min_x"])
        self.assertEqual(40.0, sim.bounds["max_x"])
        self.assertEqual(20.0, sim.bounds["min_y"])
        self.assertEqual(50.0, sim.bounds["max_y"])
        self.assertEqual(sim.LOCATION_LAYER_KIND, sim.get_active_layer_kind())
        self.assertGreater(sim.get_initial_camera_zoom(1600, 900), 10.0)

    def test_map_history_ignores_unscoped_major_periods(self):
        world_model = FakeWorldModel(
            [
                {
                    "id": "loc_empty_parent",
                    "name": "Empty Parent",
                    "type": "location",
                    "_dataset": "locations",
                    "location_class": "island",
                }
            ],
            timeline_items=[
                {
                    "timeline_kind": "major_period",
                    "label": "General",
                    "start_year": -2575001053,
                    "end_year": 75036154,
                }
            ],
        )
        sim = MapSimulation(SimulationContext(year=2400, root_entity_id="loc_empty_parent", world_model=world_model))

        self.assertEqual([], sim.get_history_timeline_items())

    def test_map_location_browser_lists_parent_root_and_children_only(self):
        world_model = FakeWorldModel([
            {
                "id": "loc_country",
                "name": "Country",
                "type": "location",
                "_dataset": "locations",
                "location_class": "country",
            },
            {
                "id": "loc_island",
                "name": "Island",
                "type": "location",
                "_dataset": "locations",
                "location_class": "island",
                "parent_location": "loc_country",
            },
            {
                "id": "loc_child",
                "name": "Child",
                "type": "location",
                "_dataset": "locations",
                "location_class": "region",
                "parent_location": "loc_island",
            },
            {
                "id": "loc_elsewhere",
                "name": "Elsewhere",
                "type": "location",
                "_dataset": "locations",
                "location_class": "region",
            },
        ])
        sim = MapSimulation(SimulationContext(year=2400, root_entity_id="loc_island", world_model=world_model))

        items = sim.get_map_location_browser_items()
        ids = [item["id"] for item in items]

        self.assertEqual(["loc_country", "loc_island", "loc_child"], ids)
        self.assertEqual("parent", items[0]["role"])
        self.assertEqual("root", items[1]["role"])
        self.assertEqual("child", items[2]["role"])

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
        self.assertNotIn("loc_state", ghost_entity_ids)

        active_layer_ids = {layer.get("entity_id") for layer in sim.get_layers()}
        self.assertIn("loc_state", active_layer_ids)

    def test_map_context_includes_timeless_locations_linked_by_parents(self):
        world_model = FakeWorldModel([
            {
                "id": "planet_earth",
                "name": "Earth",
                "type": "location",
                "_dataset": "locations",
                "location_class": "planet",
            },
            {
                "id": "loc_eurasia",
                "name": "Eurasia",
                "type": "location",
                "_dataset": "locations",
                "location_class": "continent",
                "parents": ["planet_earth"],
                "bounds": {"type": "polygon", "points": [(0, 0), (20, 0), (20, 20), (0, 20)]},
            },
            {
                "id": "loc_asia",
                "name": "Asia",
                "type": "location",
                "_dataset": "locations",
                "location_class": "continent",
                "parents": ["loc_eurasia"],
                "bounds": {"type": "polygon", "points": [(1, 1), (19, 1), (19, 18), (1, 18)]},
            },
        ])
        context = SimulationContext(year=2400, root_entity_id="planet_earth", world_model=world_model)

        active_ids = {entity.get("id") for entity in context.get_active_locations()}

        self.assertIn("loc_eurasia", active_ids)
        self.assertIn("loc_asia", active_ids)

    def test_planetary_children_are_hidden_from_surface_map_location_view(self):
        world_model = FakeWorldModel([
            {
                "id": "planet_earth",
                "name": "Earth",
                "type": "location",
                "_dataset": "locations",
                "location_class": "planet",
            },
            {
                "id": "moon_luna",
                "name": "Luna",
                "type": "location",
                "_dataset": "locations",
                "location_class": "moon",
                "parents": ["planet_earth"],
            },
            {
                "id": "loc_greenland",
                "name": "Greenland",
                "type": "location",
                "_dataset": "locations",
                "location_class": "region",
                "parents": ["planet_earth"],
                "bounds": {"type": "polygon", "points": [(-55, -60), (-20, -60), (-20, -80), (-55, -80)]},
            },
        ])
        context = SimulationContext(year=2400, root_entity_id="planet_earth", world_model=world_model)
        sim = MapSimulation(context)

        browser_ids = {item["id"] for item in sim.get_map_location_browser_items()}
        self.assertIn("loc_greenland", browser_ids)
        self.assertNotIn("moon_luna", browser_ids)

        sim.set_active_layer_kind(sim.LOCATION_LAYER_KIND)
        layer_ids = {layer.get("entity_id") for layer in sim.get_layers()}
        self.assertIn("loc_greenland", layer_ids)
        self.assertNotIn("moon_luna", layer_ids)

    def test_planet_map_can_toggle_atmosphere_without_changing_layer(self):
        planet = {
            "id": "planet_clouded",
            "name": "Clouded",
            "type": "location",
            "_dataset": "locations",
            "location_class": "planet",
            "heightmap_model": {
                "sample_grid": {"rows": [[0, 1], [1, 0]]},
            },
            "atmosphere_visual_model": {
                "visible": True,
                "tint_color": [202, 166, 82],
                "opacity": 0.56,
            },
        }
        sim = MapSimulation(SimulationContext(
            year=2400,
            root_entity_id=planet["id"],
            world_model=FakeWorldModel([planet]),
        ))

        self.assertTrue(sim.is_atmosphere_visible())
        self.assertEqual(0.56, sim.get_heightmap_base_layer()["atmosphere_opacity"])
        self.assertTrue(sim.toggle_atmosphere_visibility())
        self.assertFalse(sim.is_atmosphere_visible())
        self.assertEqual(0.0, sim.get_heightmap_base_layer()["atmosphere_opacity"])
        self.assertEqual(sim.LOCATION_LAYER_KIND, sim.get_active_layer_kind())

    def test_combined_map_includes_location_geometry(self):
        world_model = FakeWorldModel([
            {
                "id": "planet_earth",
                "name": "Earth",
                "type": "location",
                "_dataset": "locations",
                "location_class": "planet",
            },
            {
                "id": "loc_greenland",
                "name": "Greenland",
                "type": "location",
                "_dataset": "locations",
                "location_class": "region",
                "parents": ["planet_earth"],
                "bounds": {"type": "polygon", "points": [(-55, -60), (-20, -60), (-20, -80), (-55, -80)]},
            },
        ])
        context = SimulationContext(year=2400, root_entity_id="planet_earth", world_model=world_model)
        sim = MapSimulation(context)

        self.assertEqual(sim.LOCATION_LAYER_KIND, sim.get_active_layer_kind())
        self.assertEqual("Map + Locations", sim.get_active_layer_label())
        location_layers = [
            layer for layer in sim.get_layers()
            if layer.get("entity_id") == "loc_greenland" and layer.get("shape") == "polygon"
        ]
        self.assertEqual(1, len(location_layers))
        self.assertEqual("loc_greenland", location_layers[0].get("entity_id"))

    def test_earth_reference_land_layer_is_non_interactive_base_map(self):
        world_model = FakeWorldModel([
            {
                "id": "planet_earth",
                "name": "Earth",
                "type": "location",
                "_dataset": "locations",
                "location_class": "planet",
                "reference_land_polygons": {
                    "polygons": [
                        [[-10, -10], [10, -10], [10, 10], [-10, 10], [-10, -10]],
                    ],
                },
            },
        ])
        context = SimulationContext(year=2400, root_entity_id="planet_earth", world_model=world_model)
        sim = MapSimulation(context)

        land_layers = [layer for layer in sim.get_layers() if layer.get("is_reference_land")]

        self.assertEqual(1, len(land_layers))
        self.assertFalse(land_layers[0].get("pickable"))
        self.assertTrue(land_layers[0].get("suppress_label"))
        self.assertEqual(1, land_layers[0].get("border_width"))

    def test_broad_regions_become_outlines_over_reference_land_base(self):
        world_model = FakeWorldModel([
            {
                "id": "planet_earth",
                "name": "Earth",
                "type": "location",
                "_dataset": "locations",
                "location_class": "planet",
                "reference_land_polygons": {
                    "polygons": [
                        [[-10, -10], [10, -10], [10, 10], [-10, 10], [-10, -10]],
                    ],
                },
            },
            {
                "id": "loc_africa",
                "name": "Africa",
                "type": "location",
                "_dataset": "locations",
                "location_class": "continent",
                "parent_location": "planet_earth",
                "card_color": "#8f7744",
                "bounds": {"type": "bbox", "min_x": -18, "max_x": 52, "min_y": -37, "max_y": 35},
            },
        ])
        context = SimulationContext(year=2400, root_entity_id="planet_earth", world_model=world_model)
        sim = MapSimulation(context)
        sim.set_active_layer_kind(sim.LOCATION_LAYER_KIND)

        africa = next(layer for layer in sim.get_layers() if layer.get("entity_id") == "loc_africa")

        self.assertTrue(africa.get("outline_only"))
        self.assertEqual((143, 119, 68), africa.get("border_color"))
        self.assertIsNone(africa.get("alpha"))

    def test_multipolygon_regions_render_as_multiple_selectable_parts(self):
        world_model = FakeWorldModel([
            {
                "id": "planet_earth",
                "name": "Earth",
                "type": "location",
                "_dataset": "locations",
                "location_class": "planet",
            },
            {
                "id": "loc_island_country",
                "name": "Island Country",
                "type": "location",
                "_dataset": "locations",
                "location_class": "country",
                "parent_location": "planet_earth",
                "bounds": {
                    "type": "multipolygon",
                    "coordinate_space": "map_world",
                    "polygons": [
                        [[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]],
                        [[10, 0], [14, 0], [14, 4], [10, 4], [10, 0]],
                    ],
                },
            },
        ])
        context = SimulationContext(year=2400, root_entity_id="planet_earth", world_model=world_model)
        sim = MapSimulation(context)

        parts = [layer for layer in sim.get_layers() if layer.get("entity_id") == "loc_island_country"]

        self.assertEqual(2, len(parts))
        self.assertEqual({0, 1}, {part.get("geometry_part") for part in parts})

    def test_nested_surface_regions_have_zoom_lod_and_outline_only(self):
        world_model = FakeWorldModel([
            {
                "id": "planet_earth",
                "name": "Earth",
                "type": "location",
                "_dataset": "locations",
                "location_class": "planet",
            },
            {
                "id": "loc_atlantic_ocean",
                "name": "Atlantic Ocean",
                "type": "location",
                "_dataset": "locations",
                "location_class": "ocean",
                "parent_location": "planet_earth",
                "bounds": {"type": "bbox", "min_x": -80, "max_x": 20, "min_y": -65, "max_y": 65},
            },
            {
                "id": "loc_greenland",
                "name": "Greenland",
                "type": "location",
                "_dataset": "locations",
                "location_class": "region",
                "parent_location": "loc_atlantic_ocean",
                "bounds": {"type": "polygon", "points": [(-55, -60), (-20, -60), (-20, -80), (-55, -80)]},
            },
            {
                "id": "loc_northeast_greenland_national_park",
                "name": "Northeast Greenland National Park",
                "type": "location",
                "_dataset": "locations",
                "location_class": "region",
                "parent_location": "loc_greenland",
                "bounds": {"type": "polygon", "points": [(-49, -83), (-12, -83), (-12, -70), (-49, -74)]},
            },
        ])
        context = SimulationContext(year=2400, root_entity_id="planet_earth", world_model=world_model)
        sim = MapSimulation(context)
        sim.set_active_layer_kind(sim.LOCATION_LAYER_KIND)

        layers = {
            layer.get("entity_id"): layer
            for layer in sim.get_layers()
            if layer.get("entity_id")
        }

        self.assertEqual(1, layers["loc_atlantic_ocean"]["map_hierarchy_depth"])
        self.assertEqual(2, layers["loc_greenland"]["map_hierarchy_depth"])
        self.assertEqual(3, layers["loc_northeast_greenland_national_park"]["map_hierarchy_depth"])
        self.assertEqual(5.5, layers["loc_northeast_greenland_national_park"]["min_zoom"])
        self.assertTrue(layers["loc_northeast_greenland_national_park"]["outline_only"])
        self.assertTrue(layers["loc_northeast_greenland_national_park"]["suppress_label"])

    def test_map_sim_creates_biosphere_patch_as_location_polygon(self):
        root = {
            "id": "loc_meadow",
            "name": "Meadow",
            "type": "location",
            "_dataset": "locations",
            "location_class": "region",
            "bounds": {"type": "polygon", "points": [(0, 0), (20, 0), (20, 20), (0, 20)]},
        }
        world_model = FakeWorldModel([root])
        sim = MapSimulation(SimulationContext(year=2400, root_entity_id="loc_meadow", world_model=world_model))

        self.assertTrue(sim.can_create_biosphere_patch_draft())
        self.assertTrue(sim.begin_biosphere_patch_draft())
        self.assertEqual(sim.LOCATION_LAYER_KIND, sim.get_active_layer_kind())
        self.assertTrue(sim.is_creating_biosphere_patch)

        sim.draft_spatial_feature_points = [(1, 1), (4, 1), (4, 5), (1, 5)]
        self.assertTrue(sim.finish_map_editor())

        patch = world_model.get_entity(sim.selected_entity_id)
        self.assertEqual("biosphere_patch", patch["location_class"])
        self.assertEqual("micro_polygon", patch["biosphere_scale"])
        self.assertEqual(
            "coll_biosphere_roster_loc_biosphere_patch_loc_meadow_001",
            patch["biosphere_species_collection"],
        )
        self.assertEqual("loc_meadow", patch["parent_location"])
        self.assertEqual(["loc_meadow"], patch["parents"])
        self.assertIn("loc_biosphere_patch_loc_meadow_001", world_model.get_entity("loc_meadow")["constituents"])
        roster = world_model.get_entity(patch["biosphere_species_collection"])
        self.assertEqual("collections", roster["_dataset"])
        self.assertEqual("localized_biosphere_species_roster", roster["collection_class"])
        self.assertEqual(patch["id"], roster["biosphere_location"])
        self.assertEqual([(1, 1), (4, 1), (4, 5), (1, 5)], patch["bounds"]["points"])
        self.assertEqual(12.0, patch["biosphere_area_m2"])
        self.assertEqual(3.0, patch["biosphere_width_m"])
        self.assertEqual(4.0, patch["biosphere_height_m"])
        self.assertEqual(
            [(0.0, 0.0), (3.0, 0.0), (3.0, 4.0), (0.0, 4.0)],
            patch["biosphere_shape"]["points"],
        )

        launch_context = sim.get_biosphere_launch_context()
        self.assertEqual(patch["id"], launch_context["patch_location_id"])
        self.assertEqual(patch["biosphere_species_collection"], launch_context["species_collection_id"])
        self.assertEqual(4.0, launch_context["map_size_m"])
        self.assertEqual(12.0, launch_context["biosphere_area_m2"])
        self.assertEqual(patch["biosphere_shape"], launch_context["biosphere_shape"])

    def test_bioregion_micro_context_loads_species_collection(self):
        species = [
            {"id": "spec_one", "type": "species", "_dataset": "species", "common_name": "One"},
            {"id": "spec_two", "type": "species", "_dataset": "species", "common_name": "Two"},
        ]
        collection = {
            "id": "coll_micro",
            "type": "collections",
            "_dataset": "collections",
            "includes": ["spec_one", "spec_two"],
        }
        world_model = FakeWorldModel([collection] + species)

        sim = BioregionSimulation(
            world_model=world_model,
            biosphere_context={
                "patch_location_id": "loc_patch",
                "patch_name": "Patch",
                "root_name": "Meadow",
                "species_collection_id": "coll_micro",
                "map_size_m": 10.0,
            },
        )

        self.assertEqual(10.0, sim.get_map_size())
        self.assertEqual(1.0, sim.get_subsection_size())
        self.assertEqual(["spec_one", "spec_two"], [entry["id"] for entry in sim.get_species_catalog_entries()])
        self.assertTrue(sim.toggle_species_selection("spec_two"))
        selected = [entry for entry in sim.get_species_catalog_entries() if entry["selected"]]
        self.assertEqual(["spec_two"], [entry["id"] for entry in selected])

    def test_bioregion_micro_context_loads_biosphere_roster_buckets(self):
        species = [
            {"id": "spec_micro", "type": "species", "_dataset": "species", "common_name": "Micro"},
            {"id": "spec_small", "type": "species", "_dataset": "species", "common_name": "Small"},
            {"id": "spec_plant", "type": "species", "_dataset": "species", "common_name": "Plant"},
        ]
        collection = {
            "id": "coll_roster",
            "type": "collections",
            "_dataset": "collections",
            "collection_class": "localized_biosphere_species_roster",
            "microfauna_species": ["spec_micro"],
            "small_animal_species": ["spec_small"],
            "sessile_life_species": ["spec_plant"],
            "includes": ["spec_legacy"],
        }
        world_model = FakeWorldModel([collection] + species)

        sim = BioregionSimulation(
            world_model=world_model,
            biosphere_context={
                "patch_location_id": "loc_patch",
                "patch_name": "Patch",
                "root_name": "Meadow",
                "species_collection_id": "coll_roster",
                "map_size_m": 10.0,
            },
        )

        self.assertEqual(
            ["spec_micro", "spec_small", "spec_plant"],
            [entry["id"] for entry in sim.get_species_catalog_entries()],
        )

    def test_empty_localized_biosphere_roster_does_not_use_starter_species(self):
        collection = {
            "id": "coll_roster",
            "type": "collections",
            "_dataset": "collections",
            "collection_class": "localized_biosphere_species_roster",
            "biosphere_location": "loc_patch",
        }
        world_model = FakeWorldModel([collection])

        sim = BioregionSimulation(
            world_model=world_model,
            biosphere_context={
                "patch_location_id": "loc_patch",
                "patch_name": "Patch",
                "root_name": "Meadow",
                "species_collection_id": "coll_roster",
                "map_size_m": 10.0,
            },
        )

        self.assertEqual([], sim.get_species_catalog_entries())

    def test_bioregion_micro_context_uses_polygon_shape_and_mask(self):
        sim = BioregionSimulation(
            biosphere_context={
                "patch_location_id": "loc_patch",
                "patch_name": "Patch",
                "map_size_m": 4.0,
                "biosphere_width_m": 4.0,
                "biosphere_height_m": 4.0,
                "biosphere_area_m2": 8.0,
                "biosphere_shape": {
                    "type": "polygon",
                    "coordinate_space": "biosphere_local_m",
                    "points": [(0.0, 0.0), (4.0, 0.0), (0.0, 4.0)],
                },
            },
        )

        self.assertEqual(4.0, sim.get_map_size())
        self.assertEqual(4.0, sim.get_biosphere_width())
        self.assertEqual(4.0, sim.get_biosphere_height())
        self.assertEqual(8.0, sim.get_biosphere_area())
        self.assertEqual([(0.0, 0.0), (4.0, 0.0), (0.0, 4.0)], sim.get_biosphere_shape_points())
        self.assertIsNone(sim.world_to_cell_indices(3.8, 3.8))
        self.assertIsNotNone(sim.world_to_cell_indices(0.4, 0.4))

    def test_bioregion_micro_context_samples_parent_worldgen(self):
        planet = {
            "id": "loc_planet",
            "name": "Worldgen Planet",
            "type": "location",
            "_dataset": "locations",
            "location_class": "planet",
            "bounds": {"type": "bbox", "min_x": -180, "max_x": 180, "min_y": -90, "max_y": 90},
            "heightmap_model": {
                "status": "heightmap_seeded",
                "min_elevation_m": 0.0,
                "max_elevation_m": 1000.0,
                "sea_level_m": 250.0,
                "sample_grid": {
                    "width": 2,
                    "height": 2,
                    "rows": [
                        [0.0, 500.0],
                        [500.0, 1000.0],
                    ],
                },
            },
            "hydrology_summary": {
                "cycle": "active",
                "liquid_water_possible": True,
            },
            "materials_summary": {
                "dominant_materials": ["mat_basalt", "mat_clay"],
            },
        }
        patch = {
            "id": "loc_patch",
            "name": "Patch",
            "type": "location",
            "_dataset": "locations",
            "location_class": "biosphere_patch",
            "parent_location": "loc_planet",
            "bounds": {
                "type": "polygon",
                "points": [(-180, -90), (180, -90), (180, 90), (-180, 90)],
            },
        }
        world_model = FakeWorldModel([planet, patch])

        sim = BioregionSimulation(
            world_model=world_model,
            biosphere_context={
                "patch_location_id": "loc_patch",
                "parent_location_id": "loc_planet",
                "root_location_id": "loc_planet",
                "patch_name": "Patch",
                "root_name": "Worldgen Planet",
                "source_bounds": patch["bounds"],
                "map_size_m": 10.0,
            },
        )

        low_cell = sim.grid.get_cell(0, 0)
        high_cell = sim.grid.get_cell(sim.grid.total_cells_side - 1, sim.grid.total_cells_side - 1)

        self.assertEqual("loc_planet", low_cell["worldgen_source_entity_id"])
        self.assertLess(low_cell["elevation_m"], high_cell["elevation_m"])
        self.assertLess(low_cell["altitude"], high_cell["altitude"])
        self.assertEqual("basalt", low_cell["bedrock_type"])
        self.assertIn(low_cell["soil_type"], {"clay_loam", "heavy_clay"})
        self.assertGreaterEqual(low_cell["surface_water"], 0.45)
        self.assertIn("terrain from Worldgen Planet", sim.get_scope_breadcrumb())

    def test_bioregion_species_catalog_includes_worldgen_suitability(self):
        species = {
            "id": "spec_plant",
            "type": "species",
            "_dataset": "species",
            "common_name": "Patch Plant",
            "worldgen_suitability_profile": {
                "soil_types": ["loam"],
                "moisture": {"min": 0.1, "optimum": 0.45, "max": 0.9},
                "elevation_m": {"min": 0, "optimum": 50, "max": 120},
            },
        }
        collection = {
            "id": "coll_micro",
            "type": "collections",
            "_dataset": "collections",
            "includes": ["spec_plant"],
        }
        planet = {
            "id": "loc_planet",
            "name": "Worldgen Planet",
            "type": "location",
            "_dataset": "locations",
            "location_class": "planet",
            "bounds": {"type": "bbox", "min_x": -180, "max_x": 180, "min_y": -90, "max_y": 90},
            "heightmap_model": {
                "min_elevation_m": 0.0,
                "max_elevation_m": 100.0,
                "sample_grid": {"width": 2, "height": 2, "rows": [[40.0, 50.0], [50.0, 60.0]]},
            },
        }
        world_model = FakeWorldModel([collection, species, planet])

        sim = BioregionSimulation(
            world_model=world_model,
            biosphere_context={
                "patch_location_id": "loc_patch",
                "parent_location_id": "loc_planet",
                "root_location_id": "loc_planet",
                "species_collection_id": "coll_micro",
                "source_bounds": {"type": "polygon", "points": [(-10, -10), (10, -10), (10, 10), (-10, 10)]},
                "map_size_m": 10.0,
            },
        )

        entries = sim.get_species_catalog_entries()

        self.assertEqual("spec_plant", entries[0]["id"])
        self.assertIsInstance(entries[0]["suitability"], float)
        self.assertGreater(entries[0]["suitability"], 0.5)

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
