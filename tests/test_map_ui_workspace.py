import unittest
from types import SimpleNamespace

import pygame

from ui.ui_manager import UIManager


class FakeWorldModel:
    def __init__(self, entities=None):
        self.entities = entities or {}

    def get_entity(self, entity_id):
        return self.entities.get(entity_id)


class FakeMapSimulation:
    render_mode = "map"
    show_time_ui = True
    year = 2400

    def __init__(self, root_entity, editing=False, history_items=None, parent_root_entity_id=None):
        self.root_entity = root_entity
        self.parent_root_entity_id = parent_root_entity_id
        self.context = SimpleNamespace(root_entity_id=root_entity.get("id", "loc_root"))
        self.sim_clock = SimpleNamespace(time=0.0, tick=154, time_scale=1.0)
        self.world_model = FakeWorldModel({
            root_entity.get("id", "loc_root"): root_entity,
            "loc_child": {
                "id": "loc_child",
                "name": "Crabflats Bioregion",
                "type": "location",
                "_dataset": "locations",
                "location_class": "region",
            },
        })
        self.editing = editing
        self.history_items = history_items or []
        self.placing_location_entity_id = "loc_child" if editing else None
        self.selected_entity_id = self.placing_location_entity_id

    def get_root_name(self):
        return self.root_entity.get("name", self.root_entity.get("id"))

    def get_root_entity(self):
        return self.root_entity

    def get_active_layer_label(self):
        return "Map + Locations"

    def get_available_layer_kinds(self):
        return ["locations", "ground_materials"]

    def get_active_layer_kind(self):
        return "locations"

    def get_material_distribution_items(self):
        return []

    def get_location_layer_tree_items(self):
        return []

    def is_map_editor_active(self):
        return self.editing

    def get_map_editor_status_label(self):
        return "Place on parent: 0 points"

    def can_finish_map_editor(self):
        return False

    def can_import_map_image(self):
        return True

    def get_map_image_import_target_label(self):
        return "Map Image"

    def get_scope_breadcrumb(self):
        return [self.root_entity.get("name", "Root")]

    def get_parent_root_entity_id(self):
        return self.parent_root_entity_id

    def get_history_timeline_items(self):
        return self.history_items

    def get_year_context_label(self):
        return f"Year {self.year}"


class MapUIWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.font.init()

    def test_empty_parent_placement_uses_map_workspace(self):
        ui = UIManager()
        sim = FakeMapSimulation(
            {
                "id": "loc_parent",
                "name": "Backtome Island",
                "type": "location",
                "_dataset": "locations",
                "location_class": "island",
            },
            editing=True,
        )

        ui.rebuild_for_state(sim, 1600, 900, camera=None)

        self.assertTrue(ui.map_ui_active)
        self.assertEqual([], ui.time_lines)
        self.assertFalse(ui.map_history_timeline_visible)
        self.assertIn("parent map has not been defined", ui.map_empty_state_lines[0])
        self.assertTrue(ui.map_sidebar_rect.x > 1200)
        self.assertIn("choose_parent_in_repository", {action["id"] for action in ui.map_empty_state_actions})
        self.assertIn("finish_map_selection", {button.id for button in ui.buttons})
        self.assertIn("cancel_map_selection", {button.id for button in ui.buttons})

    def test_empty_parent_with_parent_offers_parent_placement_action(self):
        ui = UIManager()
        sim = FakeMapSimulation(
            {
                "id": "loc_parent",
                "name": "Backtome Island",
                "type": "location",
                "_dataset": "locations",
                "location_class": "island",
            },
            editing=True,
            parent_root_entity_id="loc_country",
        )

        ui.rebuild_for_state(sim, 1600, 900, camera=None)

        action_ids = {action["id"] for action in ui.map_empty_state_actions}
        self.assertIn("place_current_root_on_parent", action_ids)
        self.assertIn("open_parent_region_map", action_ids)

    def test_map_history_has_no_default_selected_year(self):
        ui = UIManager()
        sim = FakeMapSimulation(
            {
                "id": "loc_parent",
                "name": "Backtome Island",
                "type": "location",
                "_dataset": "locations",
                "location_class": "island",
                "bounds": {
                    "type": "polygon",
                    "points": [(0, 0), (10, 0), (10, 10), (0, 10)],
                },
            },
            history_items=[
                {
                    "timeline_kind": "major_period",
                    "label": "General",
                    "start_year": 2395,
                    "end_year": 2405,
                }
            ],
        )

        ui.rebuild_for_state(sim, 1600, 900, camera=None)

        self.assertTrue(ui.map_history_timeline_visible)
        self.assertIsNone(ui.map_history_timeline.get_selected_year())

        ui._map_history_year_action({"kind": "selected_year_changed", "year": 2401})
        ui.rebuild_for_state(sim, 1600, 900, camera=None)

        self.assertEqual(2401, ui.map_history_timeline.get_selected_year())

    def test_map_workspace_status_and_path_are_not_duplicated(self):
        ui = UIManager()
        sim = FakeMapSimulation(
            {
                "id": "planet_earth",
                "name": "Earth",
                "type": "location",
                "_dataset": "locations",
                "location_class": "planet",
                "map_status": "earth_reference_worldgen_baseline",
            }
        )
        sim.get_scope_breadcrumb = lambda: ["Sol System", "Sol", "Earth"]

        ui.rebuild_for_state(sim, 1920, 1080, camera=None)

        status_lines = [
            line for line in ui.map_context_lines
            if line == "Status: earth_reference_worldgen_baseline"
        ]
        self.assertEqual(1, len(status_lines))
        self.assertIn("Path: Sol System > Sol > Earth", ui.map_context_lines)
        self.assertNotIn(
            "Status: earth_reference_worldgen_baseline | Sol System > Sol > Earth",
            ui.map_context_lines,
        )

    def test_map_layer_selector_replaces_visual_locations_buttons(self):
        ui = UIManager()
        sim = FakeMapSimulation(
            {
                "id": "planet_earth",
                "name": "Earth",
                "type": "location",
                "_dataset": "locations",
                "location_class": "planet",
            }
        )

        ui.rebuild_for_state(sim, 1920, 1080, camera=None)

        self.assertIsNotNone(ui.map_layer_selector_rect)
        selector_labels = {item["label"] for item in ui.map_layer_selector_items}
        self.assertIn("Map", selector_labels)
        self.assertNotIn("Visual Map", {button.label for button in ui.buttons})
        self.assertNotIn("Locations", {button.label for button in ui.buttons})

    def test_map_layer_selector_click_sets_layer(self):
        ui = UIManager()
        sim = FakeMapSimulation(
            {
                "id": "planet_earth",
                "name": "Earth",
                "type": "location",
                "_dataset": "locations",
                "location_class": "planet",
            }
        )
        ui.rebuild_for_state(sim, 1920, 1080, camera=None)
        ground_item = next(item for item in ui.map_layer_selector_items if item["layer_kind"] == "ground_materials")

        event = pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": ground_item["rect"].center})
        action = ui.handle_event(event)

        self.assertEqual({"id": "set_map_layer", "layer_kind": "ground_materials"}, action)

    def test_generated_region_map_offers_current_region_regeneration(self):
        ui = UIManager()
        sim = FakeMapSimulation({
            "id": "refined_earth_lod1_test",
            "name": "Earth — Macroregion Patch",
            "type": "location",
            "_dataset": "locations",
            "location_class": "generated_region",
            "location_role": "map_refinement_region",
            "bounds": {
                "type": "bbox",
                "min_x": -20,
                "max_x": 20,
                "min_y": -10,
                "max_y": 10,
            },
            "heightmap_model": {
                "sample_grid": {
                    "width": 2,
                    "height": 2,
                    "rows": [[0, 1], [1, 0]],
                },
            },
        })
        sim.can_regenerate_current_region = lambda: True
        sim.get_current_region_regeneration_label = (
            lambda: "Regenerate This Region - Macroregion"
        )

        ui.rebuild_for_state(sim, 1600, 900, camera=None)

        button = next(
            button
            for button in ui.buttons
            if button.id == "regenerate_current_region"
        )
        self.assertEqual("Regenerate This Region - Macroregion", button.label)


if __name__ == "__main__":
    unittest.main()
