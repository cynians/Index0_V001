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

    def get_entity(self, entity_id):
        return self.entities.get(entity_id)


class NavigationBuildingTests(unittest.TestCase):
    def _controller(self, entities):
        app = SimpleNamespace(
            world_model=FakeWorldModel(entities),
            tab_manager=FakeTabManager(),
            knowledge_layer_active=True,
            camera_controller=SimpleNamespace(setup_for_sim=lambda sim: None),
            get_active_simulation=lambda: SimpleNamespace(year=2400),
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

    def test_finish_map_selection_consumes_click_when_finish_fails(self):
        controller = self._controller([])
        finish_attempts = []
        active_sim = SimpleNamespace(
            finish_map_editor=lambda: finish_attempts.append(True) and False,
        )

        handled = controller.handle_ui_action("finish_map_selection", active_sim)

        self.assertTrue(handled)
        self.assertEqual([True], finish_attempts)


if __name__ == "__main__":
    unittest.main()
