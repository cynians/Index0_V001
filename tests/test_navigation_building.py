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

    def get_entity(self, entity_id):
        return self.entities.get(entity_id)

    def get_active_entities(self, year, dataset_name=None, entity_type=None):
        entities = list(self.entities.values())
        if dataset_name is not None:
            entities = [entity for entity in entities if entity.get("_dataset") == dataset_name]
        if entity_type is not None:
            entities = [entity for entity in entities if entity.get("type") == entity_type]
        return entities


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


if __name__ == "__main__":
    unittest.main()
