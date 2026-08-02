import unittest
from types import SimpleNamespace

from app.navigation_controller import NavigationController


class FakeTabManager:
    def __init__(self):
        self.tabs = []
        self.active_index = 0

    def activate_tab_by_key(self, tab_key):
        return False

    def add_tab(self, tab):
        self.tabs.append(tab)


class FakeWorldModel:
    def __init__(self, entities):
        self.entities = {entity["id"]: entity for entity in entities}
        self.loader = SimpleNamespace(entities=self.entities)
        self.repository_revision = 0

    def get_entity(self, entity_id):
        return self.entities.get(entity_id)

    def get_active_entities(self, year, dataset_name=None, entity_type=None):
        entities = list(self.entities.values())
        if dataset_name is not None:
            entities = [entity for entity in entities if entity.get("_dataset") == dataset_name]
        if entity_type is not None:
            entities = [entity for entity in entities if entity.get("type") == entity_type]
        return entities

    def mark_repository_changed(self):
        self.repository_revision += 1


class NavigationBuildingTests(unittest.TestCase):
    def _controller(self, entities):
        app = SimpleNamespace(
            world_model=FakeWorldModel(entities),
            tab_manager=FakeTabManager(),
            knowledge_layer_active=True,
            camera_controller=SimpleNamespace(setup_for_sim=lambda sim: None),
            get_active_simulation=lambda: SimpleNamespace(year=2400),
            parent_assignment_request=None,
            repository_scope_entity_id=None,
            repository_return_confirm_active=False,
            system_menu_active=False,
            system_settings_active=False,
        )
        return NavigationController(app)

    def test_open_region_map_routes_buildings_to_building_sim(self):
        controller = self._controller([
            {
                "id": "loc_test_building",
                "name": "Test Building",
                "type": "location",
                "_dataset": "locations",
                "location_class": "building",
            }
        ])

        self.assertTrue(controller.open_region_map_tab("loc_test_building"))

        tab = controller.app.tab_manager.tabs[0]
        self.assertEqual(("building", "loc_test_building"), tab.tab_key)
        self.assertEqual("Building: Test Building", tab.name)

    def test_regenerating_current_region_refreshes_parent_and_child_map_views(self):
        controller = self._controller([])
        refreshed = []
        invalidated = []
        controller.app.world_model.refresh = lambda: refreshed.append("repository")
        controller.app._draw_startup_loading_screen = lambda *_args: None
        controller.app.tab_manager.tabs = [
            SimpleNamespace(
                sim_instance=SimpleNamespace(
                    simulation=SimpleNamespace(
                        refresh_generated_map_layers=lambda: invalidated.append("parent")
                    )
                )
            ),
            SimpleNamespace(
                sim_instance=SimpleNamespace(
                    simulation=SimpleNamespace(
                        refresh_generated_map_layers=lambda: invalidated.append("region")
                    )
                )
            ),
        ]
        active_sim = SimpleNamespace(
            regenerate_current_region=lambda: {
                "id": "refined_earth_lod1_test",
                "refinement_revision": 2,
            }
        )

        handled = controller.handle_ui_action(
            "regenerate_current_region",
            active_sim,
        )

        self.assertTrue(handled)
        self.assertEqual(["repository"], refreshed)
        self.assertEqual(["parent", "region"], invalidated)

    def test_knowledge_launch_routes_locations_without_dataset_marker(self):
        controller = self._controller([
            {
                "id": "loc_test_building",
                "name": "Test Building",
                "type": "location",
                "location_class": "building",
            }
        ])

        handled = controller.handle_ui_action(
            {
                "id": "knowledge_launch_entry",
                "entity_id": "loc_test_building",
            },
            active_sim=None,
        )

        self.assertTrue(handled)
        self.assertEqual(("building", "loc_test_building"), controller.app.tab_manager.tabs[0].tab_key)

    def test_planet_default_launch_uses_local_space_context(self):
        controller = self._controller([
            {
                "id": "system_alpha",
                "name": "Alpha",
                "type": "location",
                "_dataset": "locations",
                "location_class": "star_system",
                "system_role": "star_system",
            },
            {
                "id": "planet_alpha",
                "name": "Alpha I",
                "type": "location",
                "_dataset": "locations",
                "location_class": "planet",
                "system_role": "orbital_body",
                "body_class": "planet",
                "star_system": "system_alpha",
                "map_canvas_width_px": 2048,
                "map_canvas_height_px": 1024,
            },
        ])

        handled = controller.handle_ui_action(
            {
                "id": "knowledge_launch_entry",
                "entity_id": "planet_alpha",
            },
            active_sim=None,
        )

        self.assertTrue(handled)
        self.assertEqual(("space_body", "planet_alpha"), controller.app.tab_manager.tabs[0].tab_key)

    def test_explicit_planet_map_mode_opens_map_context(self):
        controller = self._controller([
            {
                "id": "planet_alpha",
                "name": "Alpha I",
                "type": "location",
                "_dataset": "locations",
                "location_class": "planet",
                "system_role": "orbital_body",
                "body_class": "planet",
                "star_system": "system_alpha",
                "map_canvas_width_px": 2048,
                "map_canvas_height_px": 1024,
            },
        ])

        handled = controller.handle_ui_action(
            {
                "id": "knowledge_launch_mode",
                "entity_id": "planet_alpha",
                "launch_mode": "map",
            },
            active_sim=None,
        )

        self.assertTrue(handled)
        self.assertEqual(("map", "planet_alpha"), controller.app.tab_manager.tabs[0].tab_key)

    def test_space_body_map_open_uses_live_index_without_full_repository_refresh(self):
        planet = {
            "id": "planet_alpha",
            "name": "Alpha I",
            "type": "location",
            "_dataset": "locations",
            "location_class": "planet",
            "bounds": {
                "type": "bbox",
                "min_x": -180.0,
                "max_x": 180.0,
                "min_y": -90.0,
                "max_y": 90.0,
            },
        }
        controller = self._controller([planet])
        refresh_calls = []
        opened = []
        controller.app.world_model.refresh = lambda: refresh_calls.append("full")
        controller.open_region_map_tab = lambda entity_id: opened.append(entity_id)
        space_sim = SimpleNamespace(
            get_selected_body_entity=lambda: planet,
            system=SimpleNamespace(
                ensure_location_anchor_for_body_entity=lambda body, world: (
                    body["id"],
                    False,
                ),
            ),
        )

        controller.open_map_for_selected_space_body(space_sim)

        self.assertEqual(["planet_alpha"], opened)
        self.assertEqual([], refresh_calls)

    def test_undefined_child_location_launches_parent_placement(self):
        controller = self._controller([
            {
                "id": "loc_parent",
                "name": "Parent Map",
                "type": "location",
                "_dataset": "locations",
                "location_class": "region",
                "bounds": {"type": "polygon", "points": [(0, 0), (10, 0), (10, 10), (0, 10)]},
            },
            {
                "id": "loc_child",
                "name": "Undefined Child",
                "type": "location",
                "_dataset": "locations",
                "location_class": "region",
                "parent_location": "loc_parent",
            },
        ])

        handled = controller.handle_ui_action(
            {
                "id": "knowledge_launch_entry",
                "entity_id": "loc_child",
            },
            active_sim=None,
        )

        self.assertTrue(handled)
        tab = controller.app.tab_manager.tabs[0]
        self.assertEqual(("map_place_parent", "loc_child"), tab.tab_key)
        self.assertEqual("Place: Undefined Child on Parent Map", tab.name)

    def test_finish_map_selection_consumes_click_when_finish_fails(self):
        controller = self._controller([])
        finish_attempts = []
        active_sim = SimpleNamespace(
            finish_map_editor=lambda: finish_attempts.append(True) and False,
        )

        handled = controller.handle_ui_action("finish_map_selection", active_sim)

        self.assertTrue(handled)
        self.assertEqual([True], finish_attempts)

    def test_create_biosphere_launches_micro_biosphere_tab(self):
        controller = self._controller([
            {
                "id": "coll_micro",
                "type": "collections",
                "_dataset": "collections",
                "includes": ["spec_one"],
            },
            {
                "id": "spec_one",
                "type": "species",
                "_dataset": "species",
                "common_name": "One",
            },
        ])
        active_sim = SimpleNamespace(
            get_biosphere_launch_context=lambda: {
                "patch_location_id": "loc_patch",
                "patch_name": "Patch",
                "root_name": "Meadow",
                "species_collection_id": "coll_micro",
                "map_size_m": 10.0,
            }
        )

        handled = controller.handle_ui_action("create_biosphere", active_sim)

        self.assertTrue(handled)
        tab = controller.app.tab_manager.tabs[0]
        self.assertEqual(("biosphere", "loc_patch"), tab.tab_key)
        self.assertEqual("Biosphere: Patch", tab.name)
        self.assertEqual(10.0, tab.sim_instance.simulation.get_map_size())

    def test_world_gen_space_action_opens_parent_space_sim(self):
        controller = self._controller([
            {
                "id": "system_alpha",
                "name": "Alpha",
                "type": "location",
                "_dataset": "locations",
                "location_class": "star_system",
            }
        ])

        handled = controller.handle_ui_action(
            {
                "id": "open_space_from_world_gen",
                "system_id": "system_alpha",
            },
            active_sim=None,
        )

        self.assertTrue(handled)
        tab = controller.app.tab_manager.tabs[0]
        self.assertEqual(("space", "system_alpha"), tab.tab_key)
        self.assertEqual("System: Alpha", tab.name)

    def test_place_location_on_parent_uses_constituents_parent(self):
        controller = self._controller([
            {
                "id": "loc_country",
                "name": "Country",
                "type": "location",
                "_dataset": "locations",
                "location_class": "country",
                "bounds": {"type": "polygon", "points": [(0, 0), (10, 0), (10, 10), (0, 10)]},
                "constituents": ["loc_state"],
            },
            {
                "id": "loc_state",
                "name": "State",
                "type": "location",
                "_dataset": "locations",
                "location_class": "region",
            },
        ])

        handled = controller.handle_ui_action(
            {
                "id": "knowledge_place_location_on_parent",
                "entity_id": "loc_state",
            },
            active_sim=None,
        )

        self.assertTrue(handled)
        tab = controller.app.tab_manager.tabs[0]
        self.assertEqual(("map_place_parent", "loc_state"), tab.tab_key)
        self.assertEqual("Place: State on Country", tab.name)

    def test_place_current_root_on_parent_action_opens_parent_placement(self):
        controller = self._controller([
            {
                "id": "loc_country",
                "name": "Country",
                "type": "location",
                "_dataset": "locations",
                "location_class": "country",
                "bounds": {"type": "polygon", "points": [(0, 0), (20, 0), (20, 20), (0, 20)]},
            },
            {
                "id": "loc_island",
                "name": "Island",
                "type": "location",
                "_dataset": "locations",
                "location_class": "island",
                "parent_location": "loc_country",
            },
        ])
        active_sim = SimpleNamespace(context=SimpleNamespace(root_entity_id="loc_island"))

        handled = controller.handle_ui_action("place_current_root_on_parent", active_sim)

        self.assertTrue(handled)
        tab = controller.app.tab_manager.tabs[0]
        self.assertEqual(("map_place_parent", "loc_island"), tab.tab_key)
        self.assertEqual("Place: Island on Country", tab.name)

    def test_link_existing_map_location_opens_selected_child_placement(self):
        controller = self._controller([
            {
                "id": "loc_country",
                "name": "Country",
                "type": "location",
                "_dataset": "locations",
                "location_class": "country",
                "bounds": {"type": "polygon", "points": [(0, 0), (20, 0), (20, 20), (0, 20)]},
            },
            {
                "id": "loc_island",
                "name": "Island",
                "type": "location",
                "_dataset": "locations",
                "location_class": "island",
                "parent_location": "loc_country",
            },
        ])
        active_sim = SimpleNamespace(
            selected_entity_id="loc_island",
            context=SimpleNamespace(root_entity_id="loc_country"),
        )

        handled = controller.handle_ui_action("link_existing_map_location", active_sim)

        self.assertTrue(handled)
        tab = controller.app.tab_manager.tabs[0]
        self.assertEqual(("map_place_parent", "loc_island"), tab.tab_key)

    def test_link_existing_map_location_opens_scoped_repository_without_selection(self):
        controller = self._controller([
            {
                "id": "loc_country",
                "name": "Country",
                "type": "location",
                "_dataset": "locations",
                "location_class": "country",
            },
        ])
        active_sim = SimpleNamespace(
            selected_entity_id=None,
            context=SimpleNamespace(root_entity_id="loc_country"),
        )

        handled = controller.handle_ui_action("link_existing_map_location", active_sim)

        self.assertTrue(handled)
        self.assertTrue(controller.app.knowledge_layer_active)
        self.assertEqual("loc_country", controller.app.repository_scope_entity_id)

    def test_choose_parent_repository_action_starts_parent_assignment(self):
        controller = self._controller([
            {
                "id": "loc_island",
                "name": "Island",
                "type": "location",
                "_dataset": "locations",
                "location_class": "island",
            },
        ])
        active_sim = SimpleNamespace(context=SimpleNamespace(root_entity_id="loc_island"))

        handled = controller.handle_ui_action("choose_parent_in_repository", active_sim)

        self.assertTrue(handled)
        self.assertTrue(controller.app.knowledge_layer_active)
        self.assertEqual("loc_island", controller.app.repository_scope_entity_id)
        self.assertEqual("loc_island", controller.app.parent_assignment_request["target_entity_id"])

    def test_confirm_parent_assignment_writes_parent_location(self):
        controller = self._controller([
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
            },
        ])
        controller.app.parent_assignment_request = {"target_entity_id": "loc_island"}

        handled = controller.handle_ui_action(
            {
                "id": "parent_assignment_confirm",
                "target_entity_id": "loc_island",
                "parent_entity_id": "loc_country",
            },
            active_sim=None,
        )

        self.assertTrue(handled)
        self.assertEqual("loc_country", controller.app.world_model.get_entity("loc_island")["parent_location"])
        self.assertIn("loc_island", controller.app.world_model.get_entity("loc_country")["constituents"])
        self.assertIsNone(controller.app.parent_assignment_request)


if __name__ == "__main__":
    unittest.main()
