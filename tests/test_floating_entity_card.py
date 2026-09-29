import copy
import os
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from ui.ui_manager import UIManager


class _World:
    def __init__(self, entities, persisted=None):
        # Edit mode intentionally hands EntityCard the live entity dict (to
        # match production, where world_model.get_entity returns the real,
        # mutable object) -- so committing a field edit in one test mutates
        # it in place. Deep-copy here so each test gets its own object
        # rather than sharing FloatingEntityCardTests.LOCATION's class-level
        # dict across every test in the file.
        self.entities = {entity["id"]: copy.deepcopy(entity) for entity in entities}
        self.persisted = persisted if persisted is not None else {}
        loader_persist = self.persisted

        class _Loader:
            @staticmethod
            def persist_entity(entity, **kwargs):
                loader_persist["entity"] = dict(entity)

        self.loader = _Loader()
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

    def mark_repository_changed(self):
        pass


class _StubSim:
    def __init__(self, target=None):
        self._pending = target

    def consume_pending_floating_card_target(self):
        target = self._pending
        self._pending = None
        return target


def _click(ui_manager, screen_pos):
    result = ui_manager.knowledge_ui._handle_card_canvas_click(screen_pos, ui_manager.floating_card_rect)
    ui_manager.scrub_floating_card_hitboxes()
    return result


class FloatingEntityCardTests(unittest.TestCase):
    LOCATION = {
        "id": "location_test_a", "_dataset": "locations", "type": "location",
        "name": "Test Location A", "pretty_name": "Test Location A",
        "location_class": "site", "three_word_description": "quiet coastal outpost",
        "tags": ["coastal"], "bounds": {"type": "bbox", "min_x": 0, "max_x": 10, "min_y": 0, "max_y": 10},
        "resident_people": ["a", "b"],
    }

    @classmethod
    def setUpClass(cls):
        pygame.init()
        pygame.font.init()

    @staticmethod
    def _new_ui_manager():
        """UIManager with its KnowledgeBrowserUI isolated from the real,
        on-disk .cache/card_drafts.json. Without this, tests both read
        stale drafts left by any earlier real app usage (or prior test
        runs) and write test entity ids into that real file, since
        DRAFT_CACHE_PATH/card_drafts are loaded once at construction from a
        fixed project-relative path shared by every KnowledgeBrowserUI
        instance in the process.
        """
        ui_manager = UIManager()
        ui_manager.knowledge_ui.card_drafts = {}
        ui_manager.knowledge_ui.DRAFT_CACHE_PATH = None
        ui_manager.knowledge_ui._write_card_drafts = lambda: None
        return ui_manager

    @classmethod
    def tearDownClass(cls):
        pygame.quit()

    def test_edit_mode_uses_the_real_entity_and_supports_full_editing(self):
        persisted = {}
        world = _World([self.LOCATION], persisted)
        ui_manager = self._new_ui_manager()
        sim = _StubSim({"id": "location_test_a", "mode": "edit", "familiarity": None})

        ui_manager._rebuild_floating_card(sim, world, 1200, 800)
        card = ui_manager.knowledge_ui.cards[0]
        self.assertEqual("location_test_a", card["card_view"].entity.get("id"))
        self.assertIn("bounds", card["card_view"].entity)

        _click(ui_manager, card["edit_toggle_rect"].center)
        card = ui_manager.knowledge_ui.cards[0]
        self.assertTrue(card["is_edit_mode"])

        name_rect = dict(card["editable_field_hitboxes"])["name"]
        _click(ui_manager, name_rect.center)
        self.assertEqual("name", card["active_edit_field"])

        ui_manager.knowledge_ui._handle_keydown_event(
            pygame.event.Event(pygame.KEYDOWN, key=pygame.K_x, unicode="X", mod=0)
        )
        self.assertEqual("Test Location AX", card["edit_buffer"])

        _click(ui_manager, card["edit_toggle_rect"].center)
        self.assertEqual("Test Location AX", persisted["entity"]["pretty_name"])

    def test_inspect_mode_below_low_band_shows_minimal_placeholder(self):
        world = _World([self.LOCATION])
        ui_manager = self._new_ui_manager()
        sim = _StubSim({"id": "location_test_a", "mode": "inspect", "familiarity": 0.05})

        ui_manager._rebuild_floating_card(sim, world, 1200, 800)
        entity = ui_manager.knowledge_ui.cards[0]["card_view"].entity
        self.assertEqual("Unknown", entity.get("name"))
        self.assertNotIn("bounds", entity)
        self.assertNotIn("resident_people", entity)

    def test_inspect_mode_mid_band_shows_identity_only(self):
        world = _World([self.LOCATION])
        ui_manager = self._new_ui_manager()
        sim = _StubSim({"id": "location_test_a", "mode": "inspect", "familiarity": 0.4})

        ui_manager._rebuild_floating_card(sim, world, 1200, 800)
        entity = ui_manager.knowledge_ui.cards[0]["card_view"].entity
        self.assertEqual("Test Location A", entity.get("name"))
        self.assertEqual("site", entity.get("location_class"))
        self.assertNotIn("bounds", entity)
        self.assertNotIn("resident_people", entity)

    def test_inspect_mode_high_band_shows_full_read_only_copy(self):
        world = _World([self.LOCATION])
        ui_manager = self._new_ui_manager()
        sim = _StubSim({"id": "location_test_a", "mode": "inspect", "familiarity": 0.9})

        ui_manager._rebuild_floating_card(sim, world, 1200, 800)
        entity = ui_manager.knowledge_ui.cards[0]["card_view"].entity
        self.assertIn("bounds", entity)
        self.assertIn("resident_people", entity)
        self.assertIsNot(entity, self.LOCATION)

    def test_inspect_mode_edit_toggle_and_delete_are_disabled_and_stay_disabled_across_clicks(self):
        world = _World([self.LOCATION])
        ui_manager = self._new_ui_manager()
        sim = _StubSim({"id": "location_test_a", "mode": "inspect", "familiarity": 0.9})

        ui_manager._rebuild_floating_card(sim, world, 1200, 800)
        card = ui_manager.knowledge_ui.cards[0]
        self.assertIsNone(card["edit_toggle_rect"])
        self.assertIsNone(card["delete_rect"])
        self.assertFalse(card["is_edit_mode"])

        # Regression guard: clicking anywhere that would have been the
        # edit-toggle position in edit mode must not resurrect it or flip
        # is_edit_mode -- covers the bug where an internal relayout
        # triggered as a side effect of a click undid the scrub.
        edit_world = _World([self.LOCATION])
        edit_ui = self._new_ui_manager()
        edit_sim = _StubSim({"id": "location_test_a", "mode": "edit", "familiarity": None})
        edit_ui._rebuild_floating_card(edit_sim, edit_world, 1200, 800)
        toggle_pos = edit_ui.knowledge_ui.cards[0]["edit_toggle_rect"].center

        _click(ui_manager, toggle_pos)
        card = ui_manager.knowledge_ui.cards[0]
        self.assertFalse(card["is_edit_mode"])
        self.assertIsNone(card["edit_toggle_rect"])

    def test_no_target_leaves_no_floating_card(self):
        world = _World([self.LOCATION])
        ui_manager = self._new_ui_manager()
        sim = _StubSim(None)

        ui_manager._rebuild_floating_card(sim, world, 1200, 800)
        self.assertIsNone(ui_manager.floating_card_rect)

    def test_missing_entity_does_not_crash_or_open_a_card(self):
        world = _World([self.LOCATION])
        ui_manager = self._new_ui_manager()
        sim = _StubSim({"id": "does_not_exist", "mode": "edit", "familiarity": None})

        ui_manager._rebuild_floating_card(sim, world, 1200, 800)
        self.assertIsNone(ui_manager.floating_card_rect)

    def test_close_floating_card_clears_state(self):
        world = _World([self.LOCATION])
        ui_manager = self._new_ui_manager()
        sim = _StubSim({"id": "location_test_a", "mode": "edit", "familiarity": None})
        ui_manager._rebuild_floating_card(sim, world, 1200, 800)
        self.assertIsNotNone(ui_manager.floating_card_rect)

        ui_manager.close_floating_card()
        self.assertIsNone(ui_manager.floating_card_rect)
        self.assertIsNone(ui_manager.floating_card_mode)
        self.assertEqual([], ui_manager.knowledge_ui.cards)


if __name__ == "__main__":
    unittest.main()
