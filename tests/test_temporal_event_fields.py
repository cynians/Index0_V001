import unittest

from ui.card import EntityCard


class TemporalEventFieldTests(unittest.TestCase):
    def test_start_and_end_commentary_are_temporal_subfields(self):
        entity = {
            "id": "idea_temporal_anchor",
            "pretty_name": "Temporal Anchor",
            "name": "Temporal Anchor",
            "type": "idea",
            "_dataset": "ideas",
            "start_year": 91293,
            "start_commentary": "First contact",
            "end_year": 91301,
            "end_commentary": "A written ending note",
        }

        card = EntityCard(entity, dataset_name="ideas")
        temporal_keys = [key for key, _ in card._sectioned_fields()["Temporal"]]

        self.assertIn("start_commentary", temporal_keys)
        self.assertIn("end_commentary", temporal_keys)
        self.assertLess(temporal_keys.index("start_year"), temporal_keys.index("start_commentary"))
        self.assertLess(temporal_keys.index("end_year"), temporal_keys.index("end_commentary"))

    def test_temporal_commentary_fields_are_not_relation_links(self):
        card = EntityCard({"id": "idea_temporal_anchor", "type": "idea"}, dataset_name="ideas")

        self.assertFalse(card.is_relation_edit_field("start_commentary"))
        self.assertFalse(card.is_relation_edit_field("end_commentary"))
        self.assertEqual("  commentary", card._field_display_label("start_commentary"))
        self.assertEqual("  commentary", card._field_display_label("end_commentary"))

    def test_temporal_periods_parse_from_editor_lines(self):
        card = EntityCard({"id": "veh_test", "type": "vehicle"}, dataset_name="vehicles")

        periods = card._coerce_edit_buffer(
            "temporal_periods",
            [],
            "Production: 2010 - 2020 | Initial run\nMuseum service | 2030 | ",
        )

        self.assertEqual(
            [
                {"label": "Production", "start_year": 2010, "end_year": 2020, "commentary": "Initial run"},
                {"label": "Period", "start_year": 2030, "commentary": "Museum service"},
            ],
            periods,
        )

    def test_temporal_periods_parse_endpoint_links_from_editor_lines(self):
        card = EntityCard({"id": "veh_test", "type": "vehicle"}, dataset_name="vehicles")

        periods = card._coerce_edit_buffer(
            "temporal_periods",
            [],
            "[[idea_production|Production]] | 2010 | 2020 | predecessor=veh_proto | successor=veh_next",
        )

        self.assertEqual(
            [
                {
                    "label": "Period",
                    "start_year": 2010,
                    "end_year": 2020,
                    "commentary": "[[idea_production|Production]]",
                    "predecessor": "veh_proto",
                    "successor": "veh_next",
                }
            ],
            periods,
        )

    def test_temporal_periods_format_commentary_year_columns(self):
        card = EntityCard({"id": "veh_test", "type": "vehicle"}, dataset_name="vehicles")

        line = card._format_temporal_period_line(
            {
                "label": "Production",
                "start_year": 2010,
                "end_year": 2020,
                "commentary": "Initial run",
                "predecessor": "veh_proto",
                "successor": "veh_next",
            }
        )

        self.assertEqual("Initial run | 2010 | 2020 | predecessor=veh_proto | successor=veh_next", line)


if __name__ == "__main__":
    unittest.main()
