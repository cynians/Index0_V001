import unittest
from types import SimpleNamespace

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
