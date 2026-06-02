import unittest
from types import SimpleNamespace

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


if __name__ == "__main__":
    unittest.main()
