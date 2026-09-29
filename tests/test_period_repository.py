import unittest
from unittest.mock import patch

import pygame

from ui.card import EntityCard
from ui.knowledge_browser_model import KnowledgeBrowserModel
from world.periods import apply_period_reference_models
from world.world_model import WorldModel
from world.year_utils import parse_year


class _SchemaLoader:
    schemas = {}

    @staticmethod
    def get_schema(_name):
        return None


class _Loader:
    def __init__(self, events=None, entities=None):
        self.datasets = {
            "events": list(events or []),
            "schemas": [],
        }
        self.entities = dict(entities or {})
        for event in self.datasets["events"]:
            self.entities[event["id"]] = event


class _World:
    MAJOR_PERIODS = WorldModel.MAJOR_PERIODS

    def __init__(self, loader, neighbors=None):
        self.loader = loader
        self._neighbors = neighbors or {}

    def get_entity(self, entity_id):
        return self.loader.entities.get(entity_id)

    def get_entities_by_dataset(self, dataset_name):
        return list(self.loader.datasets.get(dataset_name, []))

    def get_dataset_names(self):
        return list(self.loader.datasets)

    def get_neighbors(self, entity_id):
        return list(self._neighbors.get(entity_id, []))


class _BrowserHost:
    IDEA_GENERIC_FIELDS = set()

    def __init__(self, world):
        self.world_model = world
        self.schema_loader = _SchemaLoader()
        self.browser_tree_state = {"locations": {}, "periods": {}}
        self.browser_period_filter = None
        self.browser_filter_dataset = "events"
        self.browser_filter_incomplete_only = False
        self.browser_search_query = ""

    @staticmethod
    def _coerce_card_year(value):
        return parse_year(value)

    @staticmethod
    def _entity_display_label(entity, fallback="unknown"):
        return entity.get("pretty_name") or entity.get("name") or fallback


class PeriodRepositoryTests(unittest.TestCase):
    def test_period_schema_and_event_year_entries_are_materialized(self):
        events = [{
            "id": "evt_meeting",
            "_dataset": "events",
            "type": "event",
            "name": "Person A meets Person B",
            "start_year": 2263,
        }]
        loader = _Loader(events=events)

        apply_period_reference_models(loader, WorldModel.MAJOR_PERIODS)

        self.assertIn("schema_period", loader.entities)
        self.assertEqual("period", loader.entities["schema_period"]["schema"])
        self.assertEqual("Cen 23", loader.entities["period_century_23"]["name"])
        self.assertEqual(
            ["evt_meeting"],
            loader.entities["period_year_2263"]["contained_events"],
        )
        self.assertIn(
            "period_race_for_sol",
            loader.entities["period_year_2263"]["parent_periods"],
        )

    def test_events_are_grouped_by_century_then_year(self):
        events = [
            {"id": "evt_b", "_dataset": "events", "type": "event", "name": "B Event", "start_year": 2263},
            {"id": "evt_a", "_dataset": "events", "type": "event", "name": "A Event", "start_year": 2263},
            {"id": "evt_early", "_dataset": "events", "type": "event", "name": "Early Event", "start_year": 2261},
        ]
        loader = _Loader(events=events)
        apply_period_reference_models(loader, WorldModel.MAJOR_PERIODS)
        world = _World(loader)
        model = KnowledgeBrowserModel(_BrowserHost(world))

        rows = model._build_event_browser_items(world)
        labels = [row["text"] for row in rows]

        race_index = labels.index("Race for Sol")
        century_index = labels.index("Cen 23")
        year_2261_index = labels.index("Year 2261")
        early_index = labels.index("Early Event")
        year_2263_index = labels.index("Year 2263")
        a_index = labels.index("A Event")
        b_index = labels.index("B Event")
        self.assertLess(race_index, century_index)
        self.assertLess(century_index, year_2261_index)
        self.assertLess(year_2261_index, early_index)
        self.assertLess(early_index, year_2263_index)
        self.assertLess(year_2263_index, a_index)
        self.assertLess(a_index, b_index)

    def test_generic_period_extant_tab_lists_all_overlapping_entries(self):
        period = {
            "id": "period_year_2263",
            "_dataset": "periods",
            "type": "period",
            "period_class": "year",
            "year": 2263,
            "start_year": 2263,
            "end_year": 2263,
        }
        extant = {
            "id": "person_extant",
            "_dataset": "people",
            "type": "person",
            "name": "Extant Person",
            "start_year": 2240,
            "end_year": 2280,
        }
        ended = {
            "id": "person_ended",
            "_dataset": "people",
            "type": "person",
            "name": "Ended Person",
            "start_year": 2200,
            "end_year": 2262,
        }
        future = {
            "id": "person_future",
            "_dataset": "people",
            "type": "person",
            "name": "Future Person",
            "start_year": 2264,
        }
        end_only = {
            "id": "site_end_only",
            "_dataset": "locations",
            "type": "location",
            "name": "End-only Site",
            "end_year": 2263,
        }
        loader = _Loader(entities={
            row["id"]: row
            for row in (period, extant, ended, future, end_only)
        })
        world = _World(loader)
        card = EntityCard(period, dataset_name="periods", world_model=world)

        self.assertIn("extant", card._tab_order())
        self.assertEqual(
            {"person_extant", "site_end_only"},
            {entity["id"] for entity in card._extant_entries()},
        )

    def test_scoped_period_limits_extant_entries_to_parent_offspring_and_relations(self):
        faction = {
            "id": "fac_scope",
            "_dataset": "factions",
            "type": "faction",
            "name": "Scoped Faction",
            "start_year": 2200,
            "offspring": [{"id": "person_member"}],
        }
        period = {
            "id": "period_faction_2263",
            "_dataset": "periods",
            "type": "period",
            "name": "Faction Year 2263",
            "start_year": 2263,
            "end_year": 2263,
            "parents": ["fac_scope"],
        }
        member = {
            "id": "person_member",
            "_dataset": "people",
            "type": "person",
            "name": "Faction Member",
            "start_year": 2250,
        }
        related_site = {
            "id": "site_related",
            "_dataset": "locations",
            "type": "location",
            "name": "Faction Site",
            "start_year": 2200,
        }
        unrelated = {
            "id": "person_unrelated",
            "_dataset": "people",
            "type": "person",
            "name": "Unrelated Person",
            "start_year": 2250,
        }
        rows = (faction, period, member, related_site, unrelated)
        loader = _Loader(entities={row["id"]: row for row in rows})
        world = _World(loader, neighbors={"fac_scope": ["site_related", "period_faction_2263"]})
        card = EntityCard(period, dataset_name="periods", world_model=world)

        self.assertEqual(
            {"person_member", "site_related"},
            {entity["id"] for entity in card._extant_entries()},
        )

    def test_extant_tab_layout_draws_clickable_entity_rows(self):
        pygame.font.init()
        font = pygame.font.Font(None, 18)
        period = {
            "id": "period_year_2263",
            "_dataset": "periods",
            "type": "period",
            "name": "Year 2263",
            "year": 2263,
            "start_year": 2263,
            "end_year": 2263,
        }
        person = {
            "id": "person_extant",
            "_dataset": "people",
            "type": "person",
            "name": "Extant Person",
            "start_year": 2240,
        }
        loader = _Loader(entities={row["id"]: row for row in (period, person)})
        card_view = EntityCard(period, dataset_name="periods", world_model=_World(loader))
        card_view.set_active_tab("extant")
        card = {
            "entity_id": period["id"],
            "title": period["name"],
            "subtitle": "periods | year",
            "years": [2263],
            "selected_year": 2263,
            "is_edit_mode": False,
            "layout_font": font,
        }

        card_view.layout_card(card, pygame.Rect(0, 0, 460, 440))
        with patch("pygame.mouse.get_pos", return_value=(-1, -1)):
            card_view.draw_card(pygame.Surface((500, 480)), font, card)

        self.assertTrue(any(row.get("entity_id") == "person_extant" for row in card["extant_rows"]))
        self.assertTrue(any(info.get("entity_id") == "person_extant" for info, _rect in card["relation_hitboxes"]))


if __name__ == "__main__":
    unittest.main()
