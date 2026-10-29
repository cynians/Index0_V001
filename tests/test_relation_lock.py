import unittest
from types import SimpleNamespace

import pygame

from ui.card import EntityCard
from ui.knowledge_browser_ui import KnowledgeBrowserUI


def _isolated_browser_ui():
    ui = KnowledgeBrowserUI()
    # KnowledgeBrowserUI() loads/writes a real on-disk draft cache -- isolate it.
    ui.card_drafts = {}
    ui.DRAFT_CACHE_PATH = None
    ui._write_card_drafts = lambda: None
    return ui


class LockToggleLayoutTests(unittest.TestCase):
    def test_layout_exposes_a_lock_toggle_left_of_the_edit_toggle(self):
        pygame.font.init()
        font = pygame.font.Font(None, 18)
        card_view = EntityCard({"id": "item_x", "type": "item"}, dataset_name="items")
        card = {
            "entity_id": "item_x",
            "title": "Item X",
            "subtitle": "items | item",
            "is_edit_mode": False,
            "years": [],
            "selected_year": None,
            "layout_font": font,
        }

        card_view.layout_card(card, pygame.Rect(10, 10, 460, 380))

        lock_rect = card["lock_toggle_rect"]
        self.assertIsInstance(lock_rect, pygame.Rect)
        self.assertLess(lock_rect.right, card["close_rect"].x)
        self.assertLess(lock_rect.right, card["edit_toggle_rect"].x)
        self.assertGreater(lock_rect.x, card["rect"].x)

    def test_lock_toggle_present_in_edit_mode_without_overlapping_delete(self):
        pygame.font.init()
        font = pygame.font.Font(None, 18)
        card_view = EntityCard({"id": "item_x", "type": "item"}, dataset_name="items")
        card = {
            "entity_id": "item_x",
            "title": "Item X",
            "subtitle": "items | item",
            "is_edit_mode": True,
            "years": [],
            "selected_year": None,
            "layout_font": font,
        }

        card_view.layout_card(card, pygame.Rect(10, 10, 460, 380))

        lock_rect = card["lock_toggle_rect"]
        self.assertIsInstance(lock_rect, pygame.Rect)
        self.assertFalse(lock_rect.colliderect(card["delete_rect"]))
        self.assertFalse(lock_rect.colliderect(card["template_button_rect"]))


class RelationLockLinkingTests(unittest.TestCase):
    def test_new_entry_links_to_armed_locked_cards_only(self):
        ui = _isolated_browser_ui()
        ui.world_model = SimpleNamespace(get_entity=lambda _id: None)

        ui.cards = [
            {"entity_id": "card_locked_a", "relation_lock_active": True},
            {"entity_id": "card_unlocked", "relation_lock_active": False},
            {"entity_id": "card_locked_b", "relation_lock_active": True},
            {"entity_id": "new_entry"},
        ]
        calls = []
        ui._find_card_by_entity_id = lambda eid: next(
            (c for c in ui.cards if c["entity_id"] == eid), None
        )
        ui._insert_relation_reference_into_card = lambda card, field, eid: (
            calls.append((card["entity_id"], field, eid)) or True
        )
        ui._build_browser_items = lambda _wm: []
        ui._rebuild_browser_hitboxes = lambda: None
        ui._relayout_cards = lambda: None

        ui._apply_relation_lock_links({"id": "new_entry"})

        self.assertEqual(
            calls,
            [
                ("card_locked_a", "related", "new_entry"),
                ("card_locked_b", "related", "new_entry"),
            ],
        )

    def test_no_armed_locks_creates_no_links(self):
        ui = _isolated_browser_ui()
        ui.cards = [{"entity_id": "card_a"}, {"entity_id": "card_b", "relation_lock_active": False}]
        calls = []
        ui._find_card_by_entity_id = lambda eid: None
        ui._insert_relation_reference_into_card = lambda *a: calls.append(a) or True

        ui._apply_relation_lock_links({"id": "new_entry"})

        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
