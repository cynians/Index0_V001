import os
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from simulations.person.person_simulation import PersonSimulation
from simulations.person.site_simulation import SiteSimulation
from ui.ui_manager import UIManager


class _WorldStub:
    def __init__(self):
        self.person = {
            "id": "person_ui_test",
            "type": "person",
            "pretty_name": "UI Test Person",
            "big_five_openness": 0.7,
            "big_five_conscientiousness": 0.8,
            "big_five_extraversion": 0.4,
            "big_five_agreeableness": 0.6,
            "big_five_neuroticism": 0.3,
        }

    def get_entity(self, entity_id):
        return self.person if entity_id == self.person["id"] else None

    def get_timeline_items(self):
        return []


class PersonUIPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        pygame.font.init()

    @classmethod
    def tearDownClass(cls):
        pygame.quit()

    def setUp(self):
        world = _WorldStub()
        self.simulation = PersonSimulation(world, world.person["id"], year=2400)
        self.ui = UIManager()
        self.ui.rebuild_for_state(self.simulation, 1200, 800)

    def test_right_side_icons_toggle_needs_panel_and_consume_clicks(self):
        needs_icon = next(item for item in self.ui.person_panel_icons if item["id"] == "needs")
        action = self.ui.handle_event(
            pygame.event.Event(
                pygame.MOUSEBUTTONDOWN,
                {"button": 1, "pos": needs_icon["rect"].center},
            )
        )
        self.assertEqual("__ui_consumed__", action)
        self.assertEqual("needs", self.ui.person_panel_mode)

        self.ui.rebuild_for_state(self.simulation, 1200, 800)
        self.assertIsNotNone(self.ui.person_panel_rect)
        inside_action = self.ui.handle_event(
            pygame.event.Event(
                pygame.MOUSEBUTTONDOWN,
                {"button": 1, "pos": self.ui.person_panel_rect.center},
            )
        )
        self.assertEqual("__ui_consumed__", inside_action)
        self.assertEqual("needs", self.ui.person_panel_mode)

    def test_personality_panel_draws_and_escape_closes_it(self):
        self.ui.person_panel_mode = "personality"
        self.ui.rebuild_for_state(self.simulation, 1200, 800)
        surface = pygame.Surface((1200, 800))

        self.ui.draw(surface, self.ui.app_font)

        action = self.ui.handle_event(
            pygame.event.Event(pygame.KEYDOWN, {"key": pygame.K_ESCAPE})
        )
        self.assertEqual("__ui_consumed__", action)
        self.assertIsNone(self.ui.person_panel_mode)

    def test_knowledge_task_and_inventory_icons_open_production_panels(self):
        icon_ids = {item["id"] for item in self.ui.person_panel_icons}
        self.assertEqual({"needs", "personality", "knowledge", "tasks", "inventory"}, icon_ids)
        surface = pygame.Surface((1200, 800))

        for mode in ("knowledge", "tasks", "inventory"):
            self.ui.person_panel_mode = mode
            self.ui.rebuild_for_state(self.simulation, 1200, 800)
            self.assertIsNotNone(self.ui.person_panel_model)
            self.assertIsNotNone(self.ui.person_panel_rect)
            self.ui.draw(surface, self.ui.app_font)

    def test_person_overlay_uses_time_strip_and_compact_dossier(self):
        self.assertTrue(self.ui.person_ui_active)
        self.assertIsNotNone(self.ui.time_info)
        self.assertIsNotNone(self.ui.person_dossier_model)
        self.assertEqual("UI Test Person", self.ui.person_dossier_model["name"])
        self.assertIn("year_fraction", self.ui.time_info)

        surface = pygame.Surface((1200, 800))
        surface.fill((1, 2, 3))
        self.ui.draw(surface, self.ui.app_font)

        self.assertNotEqual((1, 2, 3, 255), surface.get_at((25, 45)))
        self.assertNotEqual((1, 2, 3, 255), surface.get_at((25, 610)))


class _SiteWorldStub:
    def __init__(self):
        self.site = {
            "id": "site", "_dataset": "locations", "type": "location",
            "name": "Site", "location_class": "site",
            "bounds": {"type": "bbox", "min_x": -70, "max_x": 75, "min_y": -90, "max_y": 55},
            "map_coordinate_space": "site_meters",
            "resident_people": ["person_ui_test_worker"],
            "present_pops": [], "visitor_scenarios": [],
        }
        self.worker = {
            "id": "person_ui_test_worker", "_dataset": "people", "type": "person",
            "name": "UI Test Worker", "simulation_site": "site", "site_position": [0, 0],
        }
        self.entities = {self.site["id"]: self.site, self.worker["id"]: self.worker}
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


class SiteDossierUIWiringTests(unittest.TestCase):
    """Regression coverage for the gap where site_people mode never populated
    person_dossier_model, so hovering/selecting a presence had no visible
    effect even though SiteSimulation tracked the hover/selection correctly.
    """

    @classmethod
    def setUpClass(cls):
        pygame.init()
        pygame.font.init()

    @classmethod
    def tearDownClass(cls):
        pygame.quit()

    def setUp(self):
        SiteSimulation._encounter_memory.clear()
        world = _SiteWorldStub()
        self.simulation = SiteSimulation(world, "site", year=2400)
        self.ui = UIManager()

    def test_nothing_hovered_falls_back_to_static_site_summary(self):
        self.ui.rebuild_for_state(self.simulation, 1200, 800)
        self.assertIsNone(self.ui.person_dossier_model)
        self.assertTrue(self.ui.person_dossier_lines)

    def test_hovering_a_worker_populates_the_rich_dossier_card(self):
        self.simulation.hover_presence_id = "person_ui_test_worker"
        self.ui.rebuild_for_state(self.simulation, 1200, 800)
        self.assertIsNotNone(self.ui.person_dossier_model)
        self.assertEqual("UI Test Worker", self.ui.person_dossier_model["name"])

    def test_selecting_the_anchor_person_does_not_recurse(self):
        self.simulation.selected_presence_id = self.simulation.person_entity_id
        self.ui.rebuild_for_state(self.simulation, 1200, 800)
        self.assertIsNotNone(self.ui.person_dossier_model)


if __name__ == "__main__":
    unittest.main()
