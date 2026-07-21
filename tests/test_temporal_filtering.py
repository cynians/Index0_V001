import unittest
from types import SimpleNamespace
from unittest.mock import patch

import pygame

from ui.card import EntityCard
from ui.knowledge_browser_ui import KnowledgeBrowserUI
from world.world_model import WorldModel
from world.yearer import Yearer


class DummyLoader:
    def __init__(self):
        self.entities = {
            "missing_start": {
                "id": "missing_start",
                "type": "test",
                "end_year": 10,
            },
            "explicit_zero": {
                "id": "explicit_zero",
                "type": "test",
                "start_year": 0,
            },
            "future": {
                "id": "future",
                "type": "test",
                "start_year": 5,
            },
            "commented": {
                "id": "commented",
                "type": "test",
                "start_year": 10,
                "end_year": 20,
                "start_commentary": "started",
                "end_commentary": "ended",
            },
        }

    def get(self, entity_id):
        return self.entities.get(entity_id)


class TemporalFilteringTests(unittest.TestCase):
    def test_missing_start_year_is_not_active_at_year_zero(self):
        yearer = Yearer(DummyLoader())

        active = yearer.entities_active(0)

        self.assertNotIn("missing_start", active)
        self.assertIn("explicit_zero", active)
        self.assertNotIn("future", active)

    def test_resolve_requires_explicit_start_year(self):
        yearer = Yearer(DummyLoader())

        self.assertIsNone(yearer.resolve("missing_start", 0))
        self.assertIsNotNone(yearer.resolve("explicit_zero", 0))

    def test_mya_year_values_are_years_ago(self):
        yearer = Yearer(DummyLoader())

        self.assertEqual(-9000000, yearer.normalize_year("9MYA"))
        self.assertEqual(-9000000, yearer.normalize_year("9 mya ago"))
        self.assertEqual(-2500000, yearer.normalize_year("2.5mya"))

    def test_card_edit_accepts_mya_for_year_fields(self):
        card_view = EntityCard({"id": "test", "type": "test", "start_year": 0})

        self.assertEqual(-9000000, card_view._coerce_edit_buffer("start_year", 0, "9MYA"))

    def test_timeline_items_require_explicit_start_year(self):
        model = WorldModel.__new__(WorldModel)
        model.loader = DummyLoader()
        model.yearer = Yearer(model.loader)

        entity_ids = {
            item["entity_id"]
            for item in model.get_timeline_items()
            if item.get("timeline_kind") != "major_period"
        }

        self.assertNotIn("missing_start", entity_ids)
        self.assertIn("explicit_zero", entity_ids)

    def test_timeline_items_include_start_and_end_commentary(self):
        model = WorldModel.__new__(WorldModel)
        model.loader = DummyLoader()
        model.yearer = Yearer(model.loader)

        items = {
            item["entity_id"]: item
            for item in model.get_timeline_items()
            if item.get("timeline_kind") != "major_period"
        }

        self.assertEqual("Start: started / End: ended", items["commented"]["commentary"])

    def test_year_bound_wiki_entries_do_not_duplicate_repository_timeline_entity(self):
        loader = DummyLoader()
        loader.entities["faction"] = {
            "id": "faction",
            "type": "faction",
            "pretty_name": "Geigengeist Group",
            "start_year": 8435,
            "end_year": 8694,
            "snapshot_year": 8445,
            "timeline_snapshots": [
                {"start_year": 8440, "end_year": 8440, "wiki_entry": "First."},
                {"start_year": 8445, "end_year": 8445, "wiki_entry": "Second."},
            ],
        }
        model = WorldModel.__new__(WorldModel)
        model.loader = loader
        model.yearer = Yearer(loader)

        faction_items = [
            item for item in model.get_timeline_items()
            if item.get("entity_id") == "faction"
        ]

        self.assertEqual(1, len(faction_items))
        self.assertEqual((8435, 8694), (faction_items[0]["start_year"], faction_items[0]["end_year"]))

    def test_card_years_do_not_fallback_to_zero_when_start_year_is_missing(self):
        ui = KnowledgeBrowserUI()
        card = {
            "card_view": SimpleNamespace(
                entity={
                    "id": "missing_start",
                    "type": "test",
                    "end_year": 10,
                }
            ),
            "selected_year": 0,
        }

        ui._sync_card_years_from_entity(card)

        self.assertEqual([], card["years"])
        self.assertIsNone(card["selected_year"])

    def test_card_years_keep_explicit_zero_start_year(self):
        ui = KnowledgeBrowserUI()
        card = {
            "card_view": SimpleNamespace(
                entity={
                    "id": "explicit_zero",
                    "type": "test",
                    "start_year": 0,
                }
            ),
            "selected_year": None,
        }

        ui._sync_card_years_from_entity(card)

        self.assertEqual([0], card["years"])
        self.assertEqual(0, card["selected_year"])

    def test_card_snapshot_chip_sets_repository_working_year(self):
        ui = KnowledgeBrowserUI()
        ui.cards = [{"active_timeline_snapshot_range": (10, 10)}]
        ui._refresh_timeline_items = lambda: None

        self.assertTrue(ui._set_working_year_from_card_snapshot(8440, 8440))

        self.assertEqual((8440, 8440), ui.timeline_ui.get_working_year_range())
        self.assertEqual((8440, 8440), ui.cards[0]["working_year_range"])
        self.assertNotIn("active_timeline_snapshot_range", ui.cards[0])

    def test_card_random_year_selects_inclusive_lifespan_and_working_year(self):
        ui = KnowledgeBrowserUI()
        entity = {
            "id": "faction",
            "type": "faction",
            "start_year": 8435,
            "end_year": 8694,
        }
        card = {
            "entity_id": "faction",
            "card_view": SimpleNamespace(entity=entity),
            "selected_year": 8435,
        }
        ui.cards = [card]
        ui._refresh_timeline_items = lambda: None

        with patch("ui.knowledge_browser_ui.random.randint", return_value=8440) as choose:
            selected_year = ui._set_random_working_year_from_card(card)

        choose.assert_called_once_with(8435, 8694)
        self.assertEqual(8440, selected_year)
        self.assertEqual(8440, card["selected_year"])
        self.assertEqual((8440, 8440), card["active_timeline_snapshot_range"])
        self.assertEqual((8440, 8440), ui.timeline_ui.get_working_year_range())

    def test_card_random_year_button_click_uses_card_lifespan(self):
        ui = KnowledgeBrowserUI()
        entity = {
            "id": "faction",
            "type": "faction",
            "start_year": 8435,
            "end_year": 8694,
        }
        card = {
            "entity_id": "faction",
            "card_view": EntityCard(entity, dataset_name="factions"),
            "random_year_rect": pygame.Rect(50, 50, 24, 20),
        }
        ui.cards = [card]
        ui._refresh_timeline_items = lambda: None
        ui._layout_all_cards = lambda: None

        with patch("ui.knowledge_browser_ui.random.randint", return_value=8500):
            result = ui._handle_card_canvas_click(
                card["random_year_rect"].center,
                pygame.Rect(0, 0, 500, 500),
            )

        self.assertEqual("__ui_consumed__", result)
        self.assertEqual(8500, card["selected_year"])
        self.assertEqual((8500, 8500), ui.timeline_ui.get_working_year_range())

    def test_postmodernist_period_starts_in_2000(self):
        postmodernist = next(
            period
            for period in WorldModel.MAJOR_PERIODS
            if period["entity_id"] == "period_postmodernist"
        )

        self.assertEqual(2000, postmodernist["start_year"])

    def test_repository_period_filter_keeps_open_ended_entries(self):
        ui = KnowledgeBrowserUI()
        ui.browser_period_filter = (100, 200)

        self.assertTrue(ui._matches_browser_filters({"id": "open", "start_year": 50}, "ideas"))
        self.assertTrue(ui._matches_browser_filters({"id": "overlap", "start_year": 150, "end_year": 250}, "ideas"))
        self.assertTrue(ui._matches_browser_filters({"id": "point", "year": 175}, "ideas"))
        self.assertFalse(ui._matches_browser_filters({"id": "ended", "start_year": 10, "end_year": 90}, "ideas"))
        self.assertFalse(ui._matches_browser_filters({"id": "missing_start", "end_year": 150}, "ideas"))


if __name__ == "__main__":
    unittest.main()
