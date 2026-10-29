import os
import tempfile
import unittest
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from app.launch_affordance_resolver import LaunchAffordanceResolver
from app.navigation_controller import NavigationController
from simulations.building import blueprint_model as bm
from simulations.building import blueprint_store
from simulations.building.blueprint_designer_simulation import BlueprintDesignerSimulation
from simulations.building.blueprint_store import BlueprintAssetStore, updated_blueprint_entity
from simulations.map.map_simulation import MapSimulation
from simulations.person.person_simulation import PersonSimulation
from tests.test_blueprint_designer import BlueprintWorld
from world.simulation_context import SimulationContext


def _hut_blueprint():
    blueprint = bm.new_blueprint("bp_hut", "Hut")
    blueprint["rooms"] = [
        {"key": "r001", "name": "Front", "points": [[0, 0], [6, 0], [6, 4], [0, 4]]},
        {"key": "r002", "name": "Back", "points": [[6, 0], [10, 0], [10, 4], [6, 4]]},
    ]
    blueprint["openings"] = [
        {"key": "o001", "center": [0, 2], "opening_class": "double_door", "width_m": 2.0},
        {"key": "o002", "center": [6, 2], "opening_class": "doorway", "width_m": 2.0},
        {"key": "o003", "center": [3, 0], "opening_class": "window"},
    ]
    return bm.normalize_blueprint(blueprint)


class _PlacementFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = BlueprintAssetStore(self.temp.name)
        self.previous_store = blueprint_store.set_shared_store(self.store)
        blueprint = _hut_blueprint()
        asset_path = self.store.save(blueprint)
        self.blueprint_entity = updated_blueprint_entity(
            {"id": "bp_hut", "name": "Hut", "pretty_name": "Hut", "map_color": "#445566"},
            blueprint, asset_path,
        )

    def tearDown(self):
        blueprint_store.set_shared_store(self.previous_store)
        self.temp.cleanup()


class BlueprintMapPlacementTests(_PlacementFixture):
    def _map_sim(self):
        site = {
            "id": "loc_site", "_dataset": "locations", "type": "location", "name": "Site",
            "location_class": "site", "map_coordinate_space": "site_meters",
            "bounds": {"type": "bbox", "min_x": -40, "max_x": 40, "min_y": -30, "max_y": 30},
            "layout_structures": [],
        }
        self.world = BlueprintWorld([site, self.blueprint_entity])
        return MapSimulation(SimulationContext(year=2400, root_entity_id="loc_site", world_model=self.world))

    def test_ghost_placement_creates_a_building_and_releases_the_blueprint(self):
        sim = self._map_sim()
        self.assertTrue(sim.begin_blueprint_placement("bp_hut"))
        self.assertTrue(sim.consumes_global_keydown())
        self.assertIn("Place Hut", sim.get_map_editor_status_label())
        camera = SimpleNamespace(x=0.0, y=0.0, zoom=10.0, width=800, height=600,
                                 world_to_screen=lambda p: (400 + p[0] * 10, 300 + p[1] * 10))
        screen_pos = (500, 350)  # world (10, 5)
        sim.handle_pointer_motion(pygame.event.Event(pygame.MOUSEMOTION, pos=screen_pos, rel=(0, 0), buttons=(0, 0, 0)), camera, screen_pos)
        sim.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_r, mod=0))
        self.assertEqual(sim.blueprint_placement.rotation_deg, 90.0)
        sim.handle_pointer_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=screen_pos, button=1), camera, screen_pos)

        self.assertIsNone(sim.blueprint_placement)
        building_id = sim.selected_entity_id
        building = self.world.get_entity(building_id)
        self.assertEqual(building["building_blueprint"], "bp_hut")
        self.assertEqual(building["location_class"], "building")
        self.assertEqual(building["blueprint_rotation_deg"], 90.0)
        # The footprint centre sits under the cursor.
        points = [tuple(p) for p in building["bounds"]["points"]]
        cx = (min(p[0] for p in points) + max(p[0] for p in points)) / 2
        cy = (min(p[1] for p in points) + max(p[1] for p in points)) / 2
        self.assertAlmostEqual(cx, 10.0, places=3)
        self.assertAlmostEqual(cy, 5.0, places=3)
        site = self.world.get_entity("loc_site")
        self.assertIn(building_id, site["layout_structures"])
        self.assertIn(building_id, site["constituents"])
        self.assertEqual(self.world.get_entity("bp_hut")["blueprint_status"], "released")

    def test_escape_cancels_placement(self):
        sim = self._map_sim()
        sim.begin_blueprint_placement("bp_hut")
        sim.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, mod=0))
        self.assertIsNone(sim.blueprint_placement)
        self.assertEqual([e for e in self.world.entities.values() if e.get("building_blueprint")], [])


class BlueprintBuildingWorkspaceTests(_PlacementFixture):
    def test_rooms_come_from_the_blueprint_and_materialise_on_demand(self):
        from simulations.building.building_sim import BuildingSimulation

        building = {
            "id": "loc_hut", "_dataset": "locations", "type": "location", "name": "Hut 1",
            "location_class": "building", "building_blueprint": "bp_hut",
            "blueprint_position": [20.0, 10.0], "blueprint_rotation_deg": 0.0,
            "bounds": {"type": "polygon", "coordinate_space": "map_world",
                       "points": [[19.85, 9.85], [30.15, 9.85], [30.15, 14.15], [19.85, 14.15]]},
        }
        world = BlueprintWorld([building, self.blueprint_entity])
        sim = BuildingSimulation(SimulationContext(year=2400, root_entity_id="loc_hut", world_model=world))
        self.assertFalse(sim.can_create_spatial_feature_draft())
        room_layers = [layer for layer in sim.get_layers() if layer.get("is_blueprint_room")]
        self.assertEqual(sorted(layer["name"] for layer in room_layers), ["Back", "Front"])
        # No room entities exist until something needs one.
        self.assertEqual([e for e in world.entities.values() if e.get("location_class") == "room"], [])

        front = next(layer for layer in room_layers if layer["name"] == "Front")
        self.assertTrue(sim.open_entity_card(front["entity_id"]))
        room = world.get_entity(front["entity_id"])
        self.assertEqual(room["blueprint_room_key"], "r001")
        self.assertEqual(room["parent_location"], "loc_hut")
        xs = [p[0] for p in room["bounds"]["points"]]
        self.assertEqual((min(xs), max(xs)), (20.0, 26.0))  # placed in site coordinates
        self.assertIn(front["entity_id"], world.get_entity("loc_hut")["constituents"])
        self.assertEqual(sim.consume_pending_floating_card_target()["id"], front["entity_id"])
        # A second request reuses the entity; its virtual layer is gone.
        self.assertTrue(sim.open_entity_card(front["entity_id"]))
        self.assertEqual(sum(1 for e in world.entities.values() if e.get("blueprint_room_key")), 1)
        remaining = [layer["name"] for layer in sim.get_layers() if layer.get("is_blueprint_room")]
        self.assertEqual(remaining, ["Back"])


class BlueprintPersonSimulationTests(_PlacementFixture):
    def test_site_walls_and_doorways_come_from_the_blueprint(self):
        person = {"id": "person_test", "type": "person", "pretty_name": "Tester",
                  "simulation_site": "loc_site", "site_position": [-6, 2]}
        world = BlueprintWorld([
            person,
            self.blueprint_entity,
            {"id": "loc_site", "type": "location", "_dataset": "locations",
             "bounds": {"min_x": -10, "max_x": 20, "min_y": -8, "max_y": 12},
             "layout_structures": ["loc_hut"], "resident_people": ["person_test"]},
            {"id": "loc_hut", "type": "location", "_dataset": "locations", "location_class": "building",
             "building_blueprint": "bp_hut", "blueprint_position": [0, 0], "blueprint_rotation_deg": 0},
        ])
        sim = PersonSimulation(world, "person_test", year=2400)
        structure = sim.site_structures[0]
        self.assertEqual(structure["building_blueprint"], "bp_hut")
        self.assertEqual(len(structure["rooms"]), 2)
        # The interior wall between the rooms blocks movement except at its doorway.
        self.assertTrue(sim._segment_blocked((5.0, 1.0), (7.0, 1.0)))
        self.assertFalse(sim._segment_blocked((5.0, 2.0), (7.0, 2.0)))
        # Windows are not walkable.
        self.assertTrue(sim._segment_blocked((3.0, -1.0), (3.0, 1.0)))
        route = sim._plan_route((-6.0, 2.0), (8.0, 1.0))
        self.assertTrue(route)
        cursor = (-6.0, 2.0)
        for waypoint in route:
            self.assertFalse(sim._segment_blocked(cursor, waypoint))
            cursor = waypoint


class BlueprintLaunchTests(_PlacementFixture):
    def _app(self, entities):
        tabs = SimpleNamespace(tabs=[], active_index=0)
        tabs.activate_tab_by_key = lambda key: False
        tabs.add_tab = lambda tab: tabs.tabs.append(tab)
        app = SimpleNamespace(
            world_model=BlueprintWorld(entities),
            tab_manager=tabs,
            knowledge_layer_active=True,
            camera_controller=SimpleNamespace(setup_for_sim=lambda sim: None),
            parent_assignment_request=None,
            repository_scope_entity_id=None,
            repository_return_confirm_active=False,
            system_menu_active=False,
            system_settings_active=False,
        )
        app.get_active_simulation = lambda: (
            tabs.tabs[tabs.active_index].sim_instance.simulation if tabs.tabs else None
        )
        return app

    def test_blueprints_and_placed_buildings_offer_the_designer(self):
        resolver = LaunchAffordanceResolver()
        self.assertEqual([o["mode"] for o in resolver.options_for_entity(self.blueprint_entity)], ["blueprint_designer"])
        building = {"id": "loc_hut", "type": "location", "location_class": "building", "building_blueprint": "bp_hut"}
        self.assertEqual([o["mode"] for o in resolver.options_for_entity(building)], ["blueprint_designer", "building", "person_create"])
        self.assertEqual(resolver.default_mode_for_entity(building), "blueprint_designer")
        plain = {"id": "loc_shed", "type": "location", "location_class": "building"}
        self.assertEqual(resolver.default_mode_for_entity(plain), "building")

    def test_designer_place_on_map_opens_the_site_in_placement_mode(self):
        site = {"id": "loc_site", "_dataset": "locations", "type": "location", "name": "Site",
                "location_class": "site", "map_coordinate_space": "site_meters",
                "bounds": {"type": "bbox", "min_x": -40, "max_x": 40, "min_y": -30, "max_y": 30}}
        building = {"id": "loc_hut", "_dataset": "locations", "type": "location", "location_class": "building",
                    "building_blueprint": "bp_hut", "name": "Hut 1"}
        app = self._app([site, building, self.blueprint_entity])
        navigation = NavigationController(app)
        self.assertTrue(navigation.handle_ui_action(
            {"id": "knowledge_launch_mode", "entity_id": "loc_hut", "launch_mode": "blueprint_designer"}, None))
        designer = app.get_active_simulation()
        self.assertIsInstance(designer, BlueprintDesignerSimulation)
        self.assertEqual(designer.blueprint_entity_id, "bp_hut")  # the building opens its blueprint
        self.assertEqual(app.tab_manager.tabs[0].tab_key, ("blueprint_designer", "bp_hut"))

        designer.request_place_on_parent("loc_site")
        self.assertTrue(navigation.handle_ui_action(designer.consume_pending_navigation_action(), designer))
        map_sim = app.get_active_simulation()
        self.assertIsInstance(map_sim, MapSimulation)
        self.assertIsNotNone(map_sim.blueprint_placement)
        self.assertEqual(map_sim.blueprint_placement.blueprint_id, "bp_hut")


if __name__ == "__main__":
    unittest.main()
