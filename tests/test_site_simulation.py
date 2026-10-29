import os
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from simulations.map.map_simulation import MapSimulation
from simulations.person.site_simulation import SitePresenceResolver, SiteSimulation
from simulations.vehicle.vehicle_simulation import VehicleSimulation
from ui.ui_manager import UIManager
from world.simulation_context import SimulationContext


class _RightClickEvent:
    def __init__(self, button):
        self.button = button


class _IdentityCamera:
    @staticmethod
    def screen_to_world(screen_pos):
        return float(screen_pos[0]), float(screen_pos[1])


class _World:
    def __init__(self, entities):
        self.entities = {entity["id"]: entity for entity in entities}
        self.loader = None
        self.repository_revision = 0

    def get_entity(self, entity_id):
        return self.entities.get(entity_id)

    def get_dataset(self, dataset_name):
        return [entity for entity in self.entities.values() if entity.get("_dataset") == dataset_name]

    def get_active_entities(self, year=None, dataset_name=None, entity_type=None):
        entities = list(self.entities.values())
        if dataset_name:
            entities = [entity for entity in entities if entity.get("_dataset") == dataset_name]
        if entity_type:
            entities = [entity for entity in entities if entity.get("type") == entity_type]
        return entities


class SiteSimulationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        pygame.font.init()

    @classmethod
    def tearDownClass(cls):
        pygame.quit()

    def setUp(self):
        SiteSimulation._encounter_memory.clear()
        self.site = {
            "id": "site", "_dataset": "locations", "type": "location",
            "name": "Site", "location_class": "site",
            "bounds": {"type": "bbox", "min_x": -70, "max_x": 75, "min_y": -90, "max_y": 55},
            "map_coordinate_space": "site_meters",
            "resident_people": ["worker", "person_lumber_overseer_tomas"],
            "present_pops": ["village_pop"], "population_anchor": [25, -66],
            "authored_visitors": ["person_neighbor_elda_woodbuyer"],
            "visitor_scenarios": [{
                "id": "travellers", "names": ["One", "Two"], "count": 2,
                "position": [55, 30], "simulation_detail": "lightweight",
            }],
        }
        self.world = _World([
            self.site,
            {
                "id": "worker", "_dataset": "people", "type": "person", "name": "Worker",
                "simulation_site": "site", "site_position": [0, 0],
            },
            {
                "id": "person_lumber_overseer_tomas", "_dataset": "people", "type": "person",
                "name": "Tomas Rhee", "simulation_site": "site", "site_position": [10, 0],
            },
            {
                "id": "person_neighbor_elda_woodbuyer", "_dataset": "people", "type": "person",
                "name": "Elda Marr", "simulation_site": "site", "site_position": [47, 2],
                "visit_purpose": "buy wood for house repairs",
            },
            {
                "id": "village_pop", "_dataset": "pops", "type": "pop", "name": "Villagers",
                "population_count": 30, "representative_count": 3,
                "representative_names": ["A", "B", "C"], "home_location": "village",
            },
            {
                "id": "village", "_dataset": "locations", "type": "location", "name": "Village",
                "location_class": "settlement", "parent_location": "site",
                "bounds": {"type": "bbox", "min_x": 7, "max_x": 45, "min_y": -84, "max_y": -48},
            },
        ])

    def test_resolver_keeps_population_aggregate_but_fully_simulates_representatives(self):
        presences = SitePresenceResolver(self.world, self.site).resolve()

        representatives = [item for item in presences if item["presence_kind"] == "pop representative"]
        aggregate = next(item for item in presences if item["presence_kind"] == "pop aggregate")
        travellers = [item for item in presences if item["simulation_detail"] == "lightweight"]
        self.assertEqual(3, len(representatives))
        self.assertEqual(27, aggregate["count"])
        self.assertEqual(2, len(travellers))
        self.assertTrue(all("big_five_openness" in item["entity"] for item in representatives))

    def test_click_materializes_named_lightweight_person(self):
        simulation = SiteSimulation(self.world, "site", year=2400)
        traveller = next(item for item in simulation.presences if item["simulation_detail"] == "lightweight")

        self.assertTrue(simulation.materialize_presence(traveller["id"]))

        self.assertEqual("full", traveller["simulation_detail"])
        self.assertIn(traveller["id"], simulation.agent_simulations)
        self.assertIn("queued for durable authoring", traveller["ontology_status"])

        reopened = SiteSimulation(self.world, "site", year=2400)
        remembered = next(item for item in reopened.presences if item["id"] == traveller["id"])
        self.assertEqual("full", remembered["simulation_detail"])
        self.assertIn(traveller["id"], reopened.agent_simulations)

    def test_visitor_request_becomes_overseer_decision_and_task(self):
        simulation = SiteSimulation(self.world, "site", year=2400)

        self.assertEqual(1, len(simulation.site_decisions))
        decision = simulation.site_decisions[0]
        self.assertEqual("person_lumber_overseer_tomas", decision["responsible_person_id"])
        overseer = simulation.agent_simulations["person_lumber_overseer_tomas"]
        self.assertTrue(any(
            task.get("label") == decision["label"]
            for task in overseer.external_task_allocations
        ))

    def test_logistics_route_actuates_vehicle_that_is_unloaded_and_stored(self):
        site = dict(self.site)
        site["resident_people"] = list(site["resident_people"]) + [
            "person_lumber_laborer_nia", "person_lumber_laborer_elias",
        ]
        site["inbound_logistics_routes"] = ["log_test_inbound"]
        site["logistics_arrival_point"] = [56.0, 15.0]
        world = _World([
            site,
            *[entity for entity in self.world.entities.values() if entity["id"] != "site"],
            {
                "id": "person_lumber_laborer_nia", "_dataset": "people", "type": "person",
                "name": "Nia Vale", "simulation_site": "site", "site_position": [17, 15],
            },
            {
                "id": "person_lumber_laborer_elias", "_dataset": "people", "type": "person",
                "name": "Elias Kern", "simulation_site": "site", "site_position": [33, 12],
            },
            {
                "id": "log_test_inbound", "_dataset": "logistics", "type": "logistics",
                "route_class": "inbound delivery", "origin_location": "village",
                "destination_location": "site", "cargo_item": "item_raw_lumber",
                "cargo_quantity_per_trip": 20, "schedule_interval_s": 1, "status": "active",
            },
        ])

        simulation = SiteSimulation(world, "site", year=2400)
        self.assertEqual({}, simulation.vehicle_agents)

        simulation._update_site_runtime(2.0)
        self.assertEqual(1, len(simulation.vehicle_agents))
        vehicle = next(iter(simulation.vehicle_agents.values()))
        self.assertIn(vehicle.vehicle_entity_id, {item.get("id") for item in simulation.presences})

        for _ in range(40):
            if vehicle.state != VehicleSimulation.STATE_ENROUTE_INBOUND:
                break
            simulation._update_site_runtime(1.0)
        self.assertNotEqual(VehicleSimulation.STATE_ENROUTE_INBOUND, vehicle.state)

        nia = simulation.agent_simulations["person_lumber_laborer_nia"]
        self.assertTrue(any(
            task.get("point_id") == "lumber_dropoff"
            for task in nia.external_task_allocations
        ))

        for _ in range(120):
            if vehicle.state == VehicleSimulation.STATE_DONE:
                break
            simulation._update_site_runtime(1.0)

        stored = nia.container_inventories.get("lumber_dropoff", {}).get("item_raw_lumber", 0)
        self.assertGreater(stored, 0)
        self.assertNotIn(vehicle.vehicle_entity_id, simulation.vehicle_agents)
        self.assertNotIn(vehicle.vehicle_entity_id, {item.get("id") for item in simulation.presences})

    def test_outbound_route_waits_for_stock_then_ships_bounded_amount(self):
        site = dict(self.site)
        site["resident_people"] = list(site["resident_people"]) + [
            "person_lumber_laborer_nia", "person_lumber_laborer_elias",
        ]
        site["inbound_logistics_routes"] = ["log_test_inbound"]
        site["outbound_logistics_routes"] = ["log_test_outbound"]
        site["logistics_arrival_point"] = [56.0, 15.0]
        world = _World([
            site,
            *[entity for entity in self.world.entities.values() if entity["id"] != "site"],
            {
                "id": "person_lumber_laborer_nia", "_dataset": "people", "type": "person",
                "name": "Nia Vale", "simulation_site": "site", "site_position": [17, 15],
            },
            {
                "id": "person_lumber_laborer_elias", "_dataset": "people", "type": "person",
                "name": "Elias Kern", "simulation_site": "site", "site_position": [33, 12],
            },
            {
                "id": "log_test_inbound", "_dataset": "logistics", "type": "logistics",
                "route_class": "inbound delivery", "origin_location": "village",
                "destination_location": "site", "cargo_item": "item_raw_lumber",
                "cargo_quantity_per_trip": 20, "schedule_interval_s": 1, "status": "active",
            },
            {
                "id": "log_test_outbound", "_dataset": "logistics", "type": "logistics",
                "route_class": "outbound delivery", "origin_location": "site",
                "destination_location": "village", "cargo_item": "item_raw_lumber",
                "cargo_quantity_per_trip": 10, "schedule_interval_s": 1, "status": "active",
            },
        ])

        simulation = SiteSimulation(world, "site", year=2400)
        nia = simulation.agent_simulations["person_lumber_laborer_nia"]

        # First tick clears both schedule intervals at once, but nothing has
        # been unloaded into storage yet -- the outbound route must find no
        # stock and defer rather than shipping lumber out of nowhere.
        simulation._update_site_runtime(2.0)
        self.assertEqual(1, len(simulation.vehicle_agents))
        inbound_vehicle = next(iter(simulation.vehicle_agents.values()))
        self.assertEqual("Lumber Delivery Cart", inbound_vehicle.label)

        # Both routes share the same 1s interval, so as soon as inbound
        # stock lands the very next outbound check will spawn a vehicle --
        # track it the moment it appears rather than assuming a fixed
        # number of ticks separates the two events.
        outbound_vehicle = None
        stored_at_outbound_spawn = None
        for _ in range(200):
            simulation._update_site_runtime(1.0)
            if outbound_vehicle is None:
                candidate = next(
                    (v for v in simulation.vehicle_agents.values() if v.label == "Lumber Outbound Cart"),
                    None,
                )
                if candidate is not None:
                    outbound_vehicle = candidate
                    stored_at_outbound_spawn = nia.container_inventories.get(
                        "lumber_dropoff", {}
                    ).get("item_raw_lumber", 0)
            elif outbound_vehicle.state == VehicleSimulation.STATE_DONE:
                break

        self.assertIsNotNone(outbound_vehicle, "outbound vehicle never spawned once stock arrived")
        # 20 were delivered and only 10 requested, so the shipment is not
        # short -- and consuming leaves exactly the remainder behind.
        self.assertEqual(10, outbound_vehicle.initial_cargo_total)
        self.assertEqual(10, stored_at_outbound_spawn)

        # Outbound never goes through the worker-unload flow: it was never
        # assigned a worker or told to begin unloading.
        self.assertIsNone(outbound_vehicle.assigned_worker_id)

        self.assertNotIn(outbound_vehicle.vehicle_entity_id, simulation.vehicle_agents)
        self.assertNotIn(outbound_vehicle.vehicle_entity_id, {item.get("id") for item in simulation.presences})

    def test_dossier_panel_shows_selected_or_hovered_presence(self):
        site = dict(self.site)
        site["resident_people"] = list(site["resident_people"]) + [
            "person_lumber_laborer_nia", "person_lumber_laborer_elias",
        ]
        site["inbound_logistics_routes"] = ["log_test_inbound"]
        site["logistics_arrival_point"] = [56.0, 15.0]
        world = _World([
            site,
            *[entity for entity in self.world.entities.values() if entity["id"] != "site"],
            {
                "id": "person_lumber_laborer_nia", "_dataset": "people", "type": "person",
                "name": "Nia Vale", "simulation_site": "site", "site_position": [17, 15],
            },
            {
                "id": "person_lumber_laborer_elias", "_dataset": "people", "type": "person",
                "name": "Elias Kern", "simulation_site": "site", "site_position": [33, 12],
            },
            {
                "id": "log_test_inbound", "_dataset": "logistics", "type": "logistics",
                "route_class": "inbound delivery", "origin_location": "village",
                "destination_location": "site", "cargo_item": "item_raw_lumber",
                "cargo_quantity_per_trip": 20, "schedule_interval_s": 1, "status": "active",
            },
        ])

        simulation = SiteSimulation(world, "site", year=2400)

        self.assertIsNone(simulation.get_dossier_panel_model())

        # Selecting the anchor person themself must not recurse infinitely
        # (agent_simulations[person_entity_id] is the simulation itself).
        simulation.selected_presence_id = simulation.person_entity_id
        anchor_model = simulation.get_dossier_panel_model()
        self.assertIsNotNone(anchor_model)

        simulation._update_site_runtime(2.0)
        vehicle_id = next(iter(simulation.vehicle_agents))
        simulation.selected_presence_id = vehicle_id
        vehicle_model = simulation.get_dossier_panel_model()
        self.assertEqual("Lumber Delivery Cart", vehicle_model["name"])
        self.assertEqual(100.0, vehicle_model["needs"][0]["value"])
        self.assertIn("20 of 20", vehicle_model["active_task"])

        simulation.selected_presence_id = "person_lumber_laborer_nia"
        worker_model = simulation.get_dossier_panel_model()
        self.assertEqual("Nia Vale", worker_model["name"])
        self.assertIn("active_task", worker_model)

    def test_right_click_opens_edit_mode_card_for_a_person_presence(self):
        simulation = SiteSimulation(self.world, "site", year=2400)

        world_pos = simulation.presences[0]["position"]
        for presence in simulation.presences:
            if presence.get("id") == "person_lumber_overseer_tomas":
                world_pos = presence["position"]
                break

        result = simulation.handle_pointer_event(_RightClickEvent(button=3), _IdentityCamera(), world_pos)

        self.assertTrue(result)
        target = simulation.consume_pending_floating_card_target()
        self.assertIsNotNone(target)
        self.assertEqual("person_lumber_overseer_tomas", target["id"])
        self.assertEqual("edit", target["mode"])

    def test_right_click_on_a_vehicle_presence_opens_its_design_entity(self):
        site = dict(self.site)
        site["resident_people"] = list(site["resident_people"]) + [
            "person_lumber_laborer_nia", "person_lumber_laborer_elias",
        ]
        site["inbound_logistics_routes"] = ["log_test_inbound"]
        world = _World([
            site,
            *[entity for entity in self.world.entities.values() if entity["id"] != "site"],
            {
                "id": "person_lumber_laborer_nia", "_dataset": "people", "type": "person",
                "name": "Nia Vale", "simulation_site": "site", "site_position": [17, 15],
            },
            {
                "id": "person_lumber_laborer_elias", "_dataset": "people", "type": "person",
                "name": "Elias Kern", "simulation_site": "site", "site_position": [33, 12],
            },
            {
                "id": "veh_design_test_cart", "_dataset": "vehicles", "type": "vehicle",
                "name": "Test Delivery Cart",
            },
            {
                "id": "log_test_inbound", "_dataset": "logistics", "type": "logistics",
                "origin_location": "village", "destination_location": "site",
                "cargo_item": "item_raw_lumber", "cargo_quantity_per_trip": 20,
                "schedule_interval_s": 1, "status": "active",
                "assigned_vehicle_design": "veh_design_test_cart",
            },
        ])
        simulation = SiteSimulation(world, "site", year=2400)
        simulation._update_site_runtime(2.0)
        vehicle = next(iter(simulation.vehicle_agents.values()))
        vehicle.design_entity_id = "veh_design_test_cart"

        result = simulation.handle_pointer_event(
            _RightClickEvent(button=3), _IdentityCamera(), tuple(vehicle.position),
        )

        self.assertTrue(result)
        target = simulation.consume_pending_floating_card_target()
        self.assertIsNotNone(target)
        self.assertEqual("veh_design_test_cart", target["id"])
        self.assertEqual("edit", target["mode"])

    def test_floating_card_actually_renders_after_right_click(self):
        # Regression: UIManager.rebuild_for_state -> _rebuild_floating_card
        # relayouts the card (populating header_drag_rect) and, in an
        # earlier version, immediately called scrub_floating_card_hitboxes()
        # in a way that nulled header_drag_rect back out again. draw_card
        # read it unconditionally, so this crashed with "TypeError: rect
        # argument is invalid" on every single floating card open --
        # test_right_click_opens_edit_mode_card_for_a_person_presence never
        # caught this because it stops at consume_pending_floating_card_target()
        # and never actually drives UIManager's rebuild/draw path.
        simulation = SiteSimulation(self.world, "site", year=2400)
        world_pos = next(
            presence["position"] for presence in simulation.presences
            if presence.get("id") == "person_lumber_overseer_tomas"
        )
        simulation.handle_pointer_event(_RightClickEvent(button=3), _IdentityCamera(), world_pos)

        ui = UIManager()
        ui.rebuild_for_state(simulation, 1200, 800, world_model=self.world)
        self.assertIsNotNone(ui.floating_card_rect)

        screen = pygame.Surface((1200, 800))
        font = pygame.font.SysFont("consolas", 14)
        ui.draw_floating_card(screen, font)  # must not raise

    def test_floating_card_does_not_leak_state_into_modal_repository_browser(self):
        # Regression: the floating card used to reuse ui_manager.knowledge_ui
        # directly -- the same instance the full-screen modal repository
        # browser uses. Opening a floating card overwrote that shared
        # instance's layout["right_rect"]/canvas_offset_x/canvas_offset_y/
        # canvas_zoom and appended into its shared .cards list, so exiting a
        # simulation without explicitly closing the floating card first left
        # a stale, broken card entry behind in the repository browser's own
        # canvas. The floating card must now live entirely on its own
        # ui_manager.floating_knowledge_ui instance.
        simulation = SiteSimulation(self.world, "site", year=2400)
        world_pos = next(
            presence["position"] for presence in simulation.presences
            if presence.get("id") == "person_lumber_overseer_tomas"
        )
        simulation.handle_pointer_event(_RightClickEvent(button=3), _IdentityCamera(), world_pos)

        ui = UIManager()
        ui.rebuild_for_state(simulation, 1200, 800, world_model=self.world)
        self.assertEqual(1, len(ui.floating_knowledge_ui.cards))
        self.assertEqual([], ui.knowledge_ui.cards)
        self.assertIsNone(ui.knowledge_ui.layout)

        ui.close_floating_card()
        self.assertEqual([], ui.floating_knowledge_ui.cards)
        self.assertEqual([], ui.knowledge_ui.cards)

    def test_floating_card_can_be_dragged_by_its_header(self):
        # The floating card is meant to have full repo-browser-card
        # functionality (drag, resize) now that it's isolated on its own
        # instance -- scrub_floating_card_hitboxes no longer strips
        # header_drag_rect/resize hitboxes to disable that.
        from app.input_router import InputRouter

        simulation = SiteSimulation(self.world, "site", year=2400)
        world_pos = next(
            presence["position"] for presence in simulation.presences
            if presence.get("id") == "person_lumber_overseer_tomas"
        )
        simulation.handle_pointer_event(_RightClickEvent(button=3), _IdentityCamera(), world_pos)

        ui = UIManager()
        ui.rebuild_for_state(simulation, 1200, 800, world_model=self.world)
        card = ui.floating_knowledge_ui.cards[0]
        header_rect = card["header_drag_rect"]
        self.assertIsNotNone(header_rect)
        original_topleft = card["rect"].topleft
        start_pos = header_rect.center

        fake_app = type("FakeApp", (), {})()
        fake_app.ui_manager = ui
        router = InputRouter(fake_app)

        down = pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": start_pos})
        self.assertTrue(router._handle_floating_card_input(down))
        self.assertIsNotNone(ui.floating_knowledge_ui.active_card_drag_id)

        moved_pos = (start_pos[0] + 40, start_pos[1] + 25)
        motion = pygame.event.Event(
            pygame.MOUSEMOTION, {"pos": moved_pos, "rel": (40, 25), "buttons": (1, 0, 0)},
        )
        self.assertTrue(router._handle_floating_card_input(motion))
        self.assertNotEqual(original_topleft, card["rect"].topleft)

        up = pygame.event.Event(pygame.MOUSEBUTTONUP, {"button": 1, "pos": moved_pos})
        self.assertTrue(router._handle_floating_card_input(up))
        self.assertIsNone(ui.floating_knowledge_ui.active_card_drag_id)

        # A stray motion after release must not still be claimed -- the
        # floating card is non-modal once no interaction is in progress.
        stray_motion = pygame.event.Event(
            pygame.MOUSEMOTION, {"pos": (0, 0), "rel": (0, 0), "buttons": (0, 0, 0)},
        )
        self.assertFalse(router._handle_floating_card_input(stray_motion))

    def test_right_click_on_nothing_does_not_open_a_card(self):
        simulation = SiteSimulation(self.world, "site", year=2400)

        result = simulation.handle_pointer_event(
            _RightClickEvent(button=3), _IdentityCamera(), (9999.0, 9999.0),
        )

        self.assertFalse(result)
        self.assertIsNone(simulation.consume_pending_floating_card_target())

    def test_local_map_shows_authored_children_at_overview_zoom(self):
        simulation = MapSimulation(SimulationContext(2400, "site", self.world))
        layers = simulation.get_layers()

        self.assertEqual(1.0, simulation.world_units_to_meters)
        self.assertIn("village", {layer.get("entity_id") for layer in layers})
        self.assertTrue(all(layer.get("min_zoom") == 0.0 for layer in layers))


if __name__ == "__main__":
    unittest.main()
