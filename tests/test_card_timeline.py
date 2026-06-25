import unittest
from types import SimpleNamespace

import pygame

from ui.card import EntityCard


class CardTimelineTests(unittest.TestCase):
    def test_range_duration_label_counts_year_difference(self):
        card = EntityCard({"id": "range_card", "type": "idea"}, dataset_name="ideas")

        self.assertEqual("20 years", card._timeline_duration_label([1900, 1920]))
        self.assertEqual("1 year", card._timeline_duration_label([1900, 1901]))

    def test_related_timeline_entries_include_entries_inside_card_range(self):
        entity = {
            "id": "idea_parent",
            "type": "idea",
            "start_year": 1900,
            "end_year": 1920,
            "related": ["event_inside", "event_after"],
            "offspring": [{"id": "event_nested"}],
        }
        related_entities = {
            "event_inside": {
                "id": "event_inside",
                "pretty_name": "Inside Event",
                "type": "event",
                "start_year": 1910,
            },
            "event_after": {
                "id": "event_after",
                "pretty_name": "After Event",
                "type": "event",
                "start_year": 1930,
            },
            "event_nested": {
                "id": "event_nested",
                "pretty_name": "Nested Event",
                "type": "event",
                "start_year": 1905,
                "end_year": 1907,
            },
        }
        world_model = SimpleNamespace(get_entity=lambda entity_id: related_entities.get(entity_id))
        card_view = EntityCard(entity, dataset_name="ideas", world_model=world_model)

        entries = card_view._related_timeline_entries({"entity_id": "idea_parent", "years": [1900, 1920]})

        self.assertEqual(["event_nested", "event_inside"], [entry["entity_id"] for entry in entries])
        self.assertEqual((1905, 1907), (entries[0]["start_year"], entries[0]["end_year"]))

    def test_related_timeline_entries_require_card_range(self):
        entity = {
            "id": "idea_parent",
            "type": "idea",
            "related": ["event_inside"],
        }
        world_model = SimpleNamespace(
            get_entity=lambda entity_id: {
                "id": entity_id,
                "type": "event",
                "start_year": 1910,
            }
        )
        card_view = EntityCard(entity, dataset_name="ideas", world_model=world_model)

        self.assertEqual([], card_view._related_timeline_entries({"entity_id": "idea_parent", "years": []}))

    def test_timeline_year_commentaries_attach_to_start_and_end(self):
        card_view = EntityCard(
            {
                "id": "veh_test",
                "type": "vehicle",
                "start_year": 2010,
                "start_commentary": "production begins",
                "end_year": 2020,
                "end_commentary": "withdrawn",
            },
            dataset_name="vehicles",
        )

        self.assertEqual(
            {
                2010: ["Start: production begins"],
                2020: ["End: withdrawn"],
            },
            card_view._timeline_year_commentaries(),
        )

    def test_temporal_periods_define_card_timeline_bands(self):
        card_view = EntityCard(
            {
                "id": "veh_test",
                "type": "vehicle",
                "temporal_periods": [
                    {"label": "Production", "start_year": 2010, "end_year": 2020, "commentary": "Initial run"},
                    {"label": "Legacy", "start_year": 2030},
                ],
            },
            dataset_name="vehicles",
        )
        card = {"entity_id": "veh_test", "years": []}

        self.assertEqual((2010, 2030), card_view._card_timeline_range(card))
        self.assertEqual(
            [
                {"label": "Production", "start_year": 2010, "end_year": 2020, "commentary": "Initial run"},
                {"label": "Legacy", "start_year": 2030, "end_year": 2030, "commentary": ""},
            ],
            card_view._temporal_period_timeline_entries(card),
        )

    def test_temporal_period_click_adds_two_click_period(self):
        card_view = EntityCard(
            {
                "id": "veh_test",
                "type": "vehicle",
                "start_year": 2010,
                "end_year": 2020,
            },
            dataset_name="vehicles",
        )
        card = {
            "entity_id": "veh_test",
            "is_edit_mode": True,
            "temporal_period_click_rect": pygame.Rect(10, 10, 100, 20),
            "temporal_period_click_context": {
                "left_x": 10,
                "right_x": 110,
                "start_year": 2010,
                "end_year": 2020,
            },
        }

        self.assertEqual("pending", card_view.handle_temporal_period_timeline_click(card, (30, 15)))
        self.assertEqual(2012, card["pending_temporal_period_start"])
        self.assertEqual("commit", card_view.handle_temporal_period_timeline_click(card, (80, 15)))

        self.assertEqual(
            [{"label": "Period 1", "start_year": 2012, "end_year": 2017}],
            card_view.entity["temporal_periods"],
        )
        self.assertEqual("commit", card["last_edit_action"])

    def test_phylogeny_members_layout_uses_descendant_species(self):
        pygame.font.init()
        entities = {
            "clade_root": {
                "id": "clade_root",
                "_dataset": "cladistics",
                "type": "cladistics",
                "pretty_name": "Root",
            },
            "species_a": {
                "id": "species_a",
                "_dataset": "species",
                "type": "species",
                "common_name": "Alpha",
                "parents": ["clade_root"],
            },
        }
        loader = SimpleNamespace(entities=entities)
        world_model = SimpleNamespace(loader=loader)
        card_view = EntityCard(entities["clade_root"], dataset_name="cladistics", world_model=world_model)
        card = {"layout_font": pygame.font.Font(None, 18), "phylogeny_clade_member_limit": 3}

        card_view._layout_phylogeny_content(card, 10, 20, 300)

        self.assertEqual(["species_a"], [row["id"] for row in card["phylogeny_local_tree_rows"]])


if __name__ == "__main__":
    unittest.main()
