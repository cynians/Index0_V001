import unittest

import pygame

from ui.card import EntityCard
from ui.knowledge_browser_ui import KnowledgeBrowserUI


def _isolated_browser_ui():
    ui = KnowledgeBrowserUI()
    ui.card_drafts = {}
    ui.DRAFT_CACHE_PATH = None
    ui._write_card_drafts = lambda: None
    return ui


def _view_card(is_edit_mode=False):
    pygame.font.init()
    font = pygame.font.Font(None, 18)
    card_view = EntityCard({"id": "hero", "type": "person"}, dataset_name="people")
    card = {
        "entity_id": "hero",
        "title": "Hero",
        "subtitle": "people | person",
        "is_edit_mode": is_edit_mode,
        "years": [],
        "selected_year": None,
        "layout_font": font,
    }
    card_view.layout_card(card, pygame.Rect(10, 10, 480, 380))
    return card


class TimelineFocusButtonLayoutTests(unittest.TestCase):
    def test_focus_button_sits_between_relation_tree_and_lock_in_view_mode(self):
        card = _view_card(is_edit_mode=False)
        focus_rect = card["timeline_focus_rect"]
        self.assertIsInstance(focus_rect, pygame.Rect)
        self.assertLess(focus_rect.right, card["relation_tree_rect"].x)
        self.assertGreater(focus_rect.x, card["lock_toggle_rect"].right)
        self.assertFalse(focus_rect.colliderect(card["close_rect"]))
        self.assertFalse(focus_rect.colliderect(card["edit_toggle_rect"]))

    def test_focus_button_hidden_in_edit_mode(self):
        card = _view_card(is_edit_mode=True)
        self.assertIsNone(card["timeline_focus_rect"])


class TimelineFocusToggleTests(unittest.TestCase):
    def test_toggle_tracks_lock_order_and_open_cards(self):
        ui = _isolated_browser_ui()
        card_a = {"entity_id": "alpha"}
        card_b = {"entity_id": "beta"}
        ui.cards = [card_a, card_b]

        ui._toggle_timeline_focus(card_b)
        ui._toggle_timeline_focus(card_a)
        self.assertEqual(ui.timeline_focus_entity_ids, ["beta", "alpha"])
        self.assertTrue(card_a["timeline_focus_active"])
        self.assertTrue(card_b["timeline_focus_active"])
        self.assertEqual(ui._current_timeline_focus_ids(), ["beta", "alpha"])

        # toggling off removes just that entry
        ui._toggle_timeline_focus(card_b)
        self.assertEqual(ui.timeline_focus_entity_ids, ["alpha"])
        self.assertFalse(card_b["timeline_focus_active"])

        # a still-locked id whose card was closed drops out of the active list
        ui.cards = [card_b]
        self.assertEqual(ui._current_timeline_focus_ids(), [])


if __name__ == "__main__":
    unittest.main()
