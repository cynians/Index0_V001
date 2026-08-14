import os
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from simulations.person.person_simulation import PersonSimulation
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


if __name__ == "__main__":
    unittest.main()
