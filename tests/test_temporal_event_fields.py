import unittest

from ui.card import EntityCard


class TemporalEventFieldTests(unittest.TestCase):
    def test_start_and_end_events_are_temporal_subfields(self):
        entity = {
            "id": "idea_temporal_anchor",
            "pretty_name": "Temporal Anchor",
            "name": "Temporal Anchor",
            "type": "idea",
            "_dataset": "ideas",
            "start_year": 91293,
            "start_event": "event_first_contact",
            "end_year": 91301,
            "end_event": "A written ending event note",
        }

        card = EntityCard(entity, dataset_name="ideas")
        temporal_keys = [key for key, _ in card._sectioned_fields()["Temporal"]]

        self.assertIn("start_event", temporal_keys)
        self.assertIn("end_event", temporal_keys)
        self.assertLess(temporal_keys.index("start_year"), temporal_keys.index("start_event"))
        self.assertLess(temporal_keys.index("end_year"), temporal_keys.index("end_event"))

    def test_temporal_event_fields_target_events(self):
        card = EntityCard({"id": "idea_temporal_anchor", "type": "idea"}, dataset_name="ideas")

        self.assertTrue(card.is_relation_edit_field("start_event"))
        self.assertTrue(card.is_relation_edit_field("end_event"))
        self.assertEqual("events", card._relation_field_target("start_event"))
        self.assertEqual("events", card._relation_field_target("end_event"))
        self.assertEqual("  related event", card._field_display_label("start_event"))
        self.assertEqual("  related event", card._field_display_label("end_event"))


if __name__ == "__main__":
    unittest.main()
