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

    def test_map_header_is_the_path_and_scale_without_internal_status(self):
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
        sim.get_map_scale_label = lambda: "Planet"

        ui.rebuild_for_state(sim, 1920, 1080, camera=None)

        self.assertEqual(["Sol System > Sol > Earth", "Planet"], ui.map_context_lines)
        self.assertEqual(["Sol System", "Sol", "Earth"], ui.map_header["breadcrumb"])
        # The internal generation status string is card material, not chrome.
        self.assertFalse(any("earth_reference_worldgen_baseline" in line for line in ui.map_context_lines))
        self.assertIsNotNone(ui.map_header_rect)

    def test_sidebar_leads_with_navigation_and_folds_location_tools(self):
        ui = UIManager()
        sim = FakeMapSimulation(
            {"id": "loc_child", "name": "Crabflats", "type": "location", "_dataset": "locations",
             "location_class": "region",
             "bounds": {"type": "polygon", "points": [(0, 0), (10, 0), (10, 10), (0, 10)]}},
            parent_root_entity_id="loc_parent",
        )
        sim.world_model.entities["loc_parent"] = {"id": "loc_parent", "name": "Backtome Island"}

        ui.rebuild_for_state(sim, 1600, 900, camera=None)

        self.assertEqual(
            ["NAVIGATE", "VIEW", "ADD", "WORKSPACE"], [item["label"] for item in ui.map_sidebar_sections])
        buttons = {button.id: button for button in ui.buttons}
        self.assertEqual("Up: Backtome Island", buttons["open_parent_region_map"].label)
        self.assertNotIn("link_existing_map_location", buttons)
        self.assertFalse(any(button_id.startswith("new_location:") for button_id in buttons))

        toggle = buttons["map_toggle_add_menu"]
        action = ui.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": toggle.rect.center}))
        self.assertEqual("__ui_consumed__", action)
        ui.rebuild_for_state(sim, 1600, 900, camera=None)
        buttons = {button.id: button for button in ui.buttons}
        self.assertIn("link_existing_map_location", buttons)
        self.assertIn("new_biosphere_patch", buttons)

    def test_a_click_on_a_panel_background_does_not_reach_the_map(self):
        ui = UIManager()
        sim = FakeMapSimulation(
            {"id": "planet_earth", "name": "Earth", "type": "location", "_dataset": "locations",
             "location_class": "planet",
             "bounds": {"type": "polygon", "points": [(0, 0), (10, 0), (10, 10), (0, 10)]}})
        ui.rebuild_for_state(sim, 1600, 900, camera=None)

        sidebar = ui.map_sidebar_rect
        gap = (sidebar.x + 4, sidebar.bottom - 3)
        self.assertFalse(any(button.rect.collidepoint(gap) for button in ui.buttons))
        action = ui.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": gap}))
        self.assertEqual("__ui_consumed__", action)
        open_map = (700, 500)
        self.assertIsNone(
            ui.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": open_map})))

    def test_the_selection_cards_buttons_can_be_pressed(self):
        # Every click rebuilds the layout before it is hit-tested.  The card's
        # buttons were made only while drawing, so that rebuild emptied them:
        # "Open Map" did nothing and the click went through to the map.
        ui = UIManager()
        sim = FakeMapSimulation(
            {"id": "planet_bristoll", "name": "Bristoll", "type": "location", "_dataset": "locations",
             "location_class": "planet",
             "bounds": {"type": "polygon", "points": [(0, 0), (10, 0), (10, 10), (0, 10)]}})
        sim.get_selection_inspector_payload = lambda: {
            "entity_id": "loc_child", "title": "Bristoll Continent 1", "kind": "Continent",
            "details": [], "compact": True, "actions_inline": True,
            "actions": [{"id": "open_region_map", "label": "Open Map"}, {"id": "open_selection_wiki", "label": "Wiki Entry"}],
        }
        ui.rebuild_for_state(sim, 1600, 900, camera=None)

        buttons = {button.id: button for button in ui.simulation_selection_buttons}
        self.assertEqual({"open_region_map", "open_selection_wiki"}, set(buttons))
        card = ui.simulation_selection_rect
        self.assertTrue(all(card.contains(button.rect) for button in buttons.values()))
        self.assertFalse(buttons["open_region_map"].rect.colliderect(buttons["open_selection_wiki"].rect))
        for action_id, button in buttons.items():
            click = pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": button.rect.center})
            self.assertEqual(action_id, ui.handle_event(click))
        # The card's background takes the click instead of the map under it.
        background = pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": (card.x + 3, card.y + 3)})
        self.assertEqual("__ui_consumed__", ui.handle_event(background))
        # What is drawn is what can be pressed.
        ui._draw_simulation_selection_inspector(pygame.Surface((1600, 900)), ui.app_font, card.x, card.y)
        self.assertEqual(
            {action_id: tuple(button.rect) for action_id, button in buttons.items()},
            {button.id: tuple(button.rect) for button in ui.simulation_selection_buttons})

    def test_overlay_toggles_keep_their_label_and_show_state(self):
        ui = UIManager()
        sim = FakeMapSimulation(
            {"id": "planet_earth", "name": "Earth", "type": "location", "_dataset": "locations",
             "location_class": "planet"})
        sim.has_height_contours = lambda: True
        sim.is_height_contours_visible = lambda: False
        ui.rebuild_for_state(sim, 1600, 900, camera=None)

        toggle = next(
            item for item in ui.map_layer_selector_items
            if item.get("action_id") == "toggle_map_height_contours")
        self.assertEqual("Contours", toggle["label"])
        self.assertTrue(toggle["toggle"])
        self.assertFalse(toggle["active"])

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

    def test_true_color_has_its_own_map_layer_button(self):
        ui = UIManager()
        sim = FakeMapSimulation({
            "id": "rendered_planet",
            "name": "Rendered Planet",
            "type": "location",
            "_dataset": "locations",
            "location_class": "planet",
        })
        sim.get_available_layer_kinds = lambda: [
            "locations",
            "true_color",
            "heightmap",
        ]
        sim.get_active_layer_kind = lambda: "true_color"

        ui.rebuild_for_state(sim, 1600, 900, camera=None)

        selector = next(
            item
            for item in ui.map_layer_selector_items
            if item.get("layer_kind") == "true_color"
        )
        self.assertEqual("True Color", selector["label"])
        self.assertTrue(selector["active"])

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

    def test_visible_region_regeneration_replaces_duplicate_current_region_action(self):
        ui = UIManager()
        sim = FakeMapSimulation({
            "id": "refined_region_test",
            "name": "Refined Region",
            "type": "location",
            "_dataset": "locations",
            "location_class": "generated_region",
        })
        sim.can_regenerate_current_region = lambda: True
        sim.can_regenerate_region = lambda: True
        sim.get_refinement_action = lambda camera, width, height, viewport_rect=None: {
            "label": "Refine View to Local (2 maps)", "enabled": True}

        ui.rebuild_for_state(sim, 1600, 900, camera=None)

        buttons = {button.id: button for button in ui.buttons}
        self.assertIn("regenerate_visible_region", buttons)
        self.assertNotIn("regenerate_current_region", buttons)
        self.assertEqual("Refine View to Local (2 maps)", buttons["regenerate_visible_region"].label)
        self.assertTrue(buttons["regenerate_visible_region"].enabled)
        # A footprint that cannot be refined keeps the button, greyed out, saying why.
        sim.get_refinement_action = lambda camera, width, height, viewport_rect=None: {
            "label": "Zoom in to refine: max 8.2 Mm", "enabled": False}
        ui.rebuild_for_state(sim, 1600, 900, camera=None)
        button = next(button for button in ui.buttons if button.id == "regenerate_visible_region")
        self.assertEqual(("Zoom in to refine: max 8.2 Mm", False), (button.label, button.enabled))

    def test_material_selector_uses_two_columns_for_more_than_four_materials(self):
        ui = UIManager()
        sim = FakeMapSimulation({
            "id": "material_planet",
            "name": "Material Planet",
            "type": "location",
            "_dataset": "locations",
            "location_class": "planet",
        })
        sim.get_active_layer_kind = lambda: "material_heatmaps"
        sim.get_available_layer_kinds = lambda: ["locations", "material_heatmaps"]
        sim.get_material_distribution_items = lambda: [
            {"id": "composite", "label": "Composite Material Heatmap", "active": True},
            *[
                {
                    "id": f"material_{index}",
                    "label": f"Material {index}",
                    "confidence": 0.8,
                    "active": False,
                }
                for index in range(8)
            ],
        ]

        ui.rebuild_for_state(sim, 1920, 1080, camera=None)

        buttons = [
            button for button in ui.buttons
            if button.id.startswith("map_select_material:")
        ]
        distribution_buttons = [
            button for button in buttons
            if button.id != "map_select_material:composite"
        ]
        self.assertEqual(9, len(buttons))
        self.assertEqual(2, len({button.rect.x for button in distribution_buttons}))
        self.assertEqual(4, len({button.rect.y for button in distribution_buttons}))

    def test_climate_layer_exposes_zones_temperature_and_precipitation(self):
        ui = UIManager()
        sim = FakeMapSimulation({
            "id": "climate_planet",
            "name": "Climate Planet",
            "type": "location",
            "_dataset": "locations",
            "location_class": "planet",
        })
        sim.get_active_layer_kind = lambda: "hydrology"
        sim.get_available_layer_kinds = lambda: ["locations", "hydrology"]
        sim.get_climate_display_items = lambda: [
            {"id": "zones", "label": "Koppen Climate Zones", "active": True},
            {"id": "annual_temperature", "label": "Mean Annual Temperature", "active": False},
            {"id": "annual_precipitation", "label": "Annual Precipitation", "active": False},
        ]

        ui.rebuild_for_state(sim, 1600, 900, camera=None)

        self.assertEqual(
            [
                "map_select_climate:zones",
                "map_select_climate:annual_temperature",
                "map_select_climate:annual_precipitation",
            ],
            [
                button.id for button in ui.buttons
                if button.id.startswith("map_select_climate:")
            ],
        )


if __name__ == "__main__":
    unittest.main()
