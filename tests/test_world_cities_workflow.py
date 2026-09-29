import unittest
from types import SimpleNamespace

import pygame

from app.navigation_controller import NavigationController
from simulations.map.map_simulation import MapSimulation
from simulations.world_gen.world_gen_sim import WorldGenSimulation
from ui.card import EntityCard


class _WorldModel:
    def __init__(self, entities):
        self.entities = entities
        self.loader = SimpleNamespace(entities=entities)

    def get_entity(self, entity_id):
        return self.entities.get(entity_id)


class WorldCitiesWorkflowTests(unittest.TestCase):
    def test_planet_authoring_offers_state(self):
        sim = MapSimulation.__new__(MapSimulation)
        sim.get_root_entity = lambda: {"location_class": "planet"}

        option_ids = [option["id"] for option in sim.get_location_draft_options()]

        self.assertIn("state", option_ids)

    def test_country_draft_uses_containing_continent_as_parent(self):
        planet = {
            "id": "planet_test",
            "location_class": "planet",
            "bounds": {"type": "bbox", "min_x": -180, "max_x": 180, "min_y": -90, "max_y": 90},
        }
        continent = {
            "id": "continent_test",
            "location_class": "continent",
            "bounds": {"type": "polygon", "points": [(-20, -20), (20, -20), (20, 20), (-20, 20)]},
        }
        sim = MapSimulation.__new__(MapSimulation)
        sim.context = SimpleNamespace(
            root_entity_id="planet_test",
            get_active_locations=lambda: [planet, continent],
        )

        parent_id = sim._smallest_draft_parent_for_points(
            [(-5, -5), (5, -5), (0, 5)], "country"
        )

        self.assertEqual("continent_test", parent_id)

    def test_location_layer_keeps_heightmap_as_non_pickable_base(self):
        sim = MapSimulation.__new__(MapSimulation)
        sim.active_layer_kind = sim.LOCATION_LAYER_KIND
        sim.get_active_layer_kind = lambda: sim.LOCATION_LAYER_KIND
        sim.get_heightmap_base_layer = lambda: {"shape": "heightmap_rect", "entity_id": "planet_test"}
        sim._build_ghost_context_layers = lambda: []
        sim._build_placement_ancestor_layers = lambda: []
        sim._root_is_building = lambda: False
        sim.context = SimpleNamespace(root_entity_id="planet_test", get_active_locations=lambda: [])

        layers = sim._build_layers(2400)

        self.assertEqual("heightmap_rect", layers[0]["shape"])
        self.assertFalse(layers[0]["pickable"])
        self.assertTrue(layers[0]["is_location_base"])

    def test_open_repository_prefers_selected_map_location(self):
        entities = {
            "planet_test": {"id": "planet_test"},
            "country_test": {"id": "country_test"},
        }
        app = SimpleNamespace(world_model=_WorldModel(entities), repository_scope_entity_id=None)
        controller = NavigationController(app)
        sim = SimpleNamespace(
            render_mode="map",
            selected_entity_id="country_test",
            selected_spatial_feature_id=None,
            context=SimpleNamespace(root_entity_id="planet_test"),
        )

        self.assertEqual("country_test", controller._infer_repository_scope_entity_id(sim))

    def test_direct_parent_edit_mirrors_constituent_relation(self):
        child = {"id": "state_test", "type": "location", "_dataset": "locations", "location_class": "state"}
        parent = {"id": "country_test", "type": "location", "_dataset": "locations", "location_class": "country"}
        card_view = EntityCard(child, dataset_name="locations", world_model=_WorldModel({
            child["id"]: child,
            parent["id"]: parent,
        }))
        card = {}

        added = card_view.add_location_topology_relation(card, "parents", parent["id"])

        self.assertTrue(added)
        self.assertEqual(["country_test"], child["parents"])
        self.assertEqual("country_test", child["parent_location"])
        self.assertEqual(["state_test"], parent["constituents"])

    def test_planet_name_ctrl_a_replaces_suggested_name(self):
        sim = WorldGenSimulation.__new__(WorldGenSimulation)
        sim.planet_name_prompt_active = True
        sim.planet_name_buffer = "Suggested Formation Name"
        sim.planet_name_select_all = False
        sim.pending_back_stage = None
        sim.is_worldgen_job_running = lambda: False

        sim.handle_event(pygame.event.Event(pygame.KEYDOWN, {
            "key": pygame.K_a,
            "mod": pygame.KMOD_CTRL,
            "unicode": "a",
        }))
        sim.handle_event(pygame.event.Event(pygame.KEYDOWN, {
            "key": pygame.K_t,
            "mod": 0,
            "unicode": "T",
        }))

        self.assertEqual("T", sim.planet_name_buffer)
        self.assertFalse(sim.planet_name_select_all)


if __name__ == "__main__":
    unittest.main()
