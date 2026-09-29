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


class PeriodAddRowTests(unittest.TestCase):
    """The Name/Start Year/End Year quick-add row under Periods.

    Uses the same draft-field commit path as any other card field
    (begin_edit_field/commit_edit_field), just backed by the card dict
    instead of the entity, so typing/cursor handling comes for free.
    """

    def _card(self, temporal_periods=None):
        entity = {"id": "prod_test", "type": "producer", "_dataset": "producers"}
        if temporal_periods is not None:
            entity["temporal_periods"] = temporal_periods
        card_view = EntityCard(entity, dataset_name="producers")
        return card_view, entity

    def _draft(self, card_view, card, field_key, text):
        self.assertTrue(card_view.begin_edit_field(card, field_key))
        card["edit_buffer"] = text
        self.assertTrue(card_view.commit_edit_field(card))

    def test_draft_fields_are_editable_and_stored_on_the_card_not_the_entity(self):
        card_view, entity = self._card()
        card = {"is_edit_mode": True}

        self._draft(card_view, card, "period_add_name", "Republican Period")

        self.assertEqual("Republican Period", card["period_add_name"])
        self.assertNotIn("period_add_name", entity)

    def test_add_period_from_draft_appends_a_structured_entry(self):
        card_view, entity = self._card()
        card = {"is_edit_mode": True}
        self._draft(card_view, card, "period_add_name", "Republican Period")
        self._draft(card_view, card, "period_add_start", "-509")
        self._draft(card_view, card, "period_add_end", "-27")

        added = card_view.add_period_from_draft(card)

        self.assertTrue(added)
        self.assertEqual(
            [{"label": "Republican Period", "start_year": -509, "end_year": -27}],
            entity["temporal_periods"],
        )

    def test_add_period_from_draft_clears_the_inputs_for_the_next_entry(self):
        card_view, entity = self._card()
        card = {"is_edit_mode": True}
        self._draft(card_view, card, "period_add_name", "Republican Period")
        self._draft(card_view, card, "period_add_start", "-509")
        self._draft(card_view, card, "period_add_end", "-27")

        card_view.add_period_from_draft(card)

        self.assertEqual("", card["period_add_name"])
        self.assertEqual("", card["period_add_start"])
        self.assertEqual("", card["period_add_end"])

    def test_add_period_from_draft_preserves_existing_periods(self):
        card_view, entity = self._card(
            temporal_periods=[{"label": "Founding", "start_year": -753, "end_year": -509}]
        )
        card = {"is_edit_mode": True}
        self._draft(card_view, card, "period_add_name", "Republican Period")
        self._draft(card_view, card, "period_add_start", "-509")
        self._draft(card_view, card, "period_add_end", "-27")

        card_view.add_period_from_draft(card)

        self.assertEqual(
            [
                {"label": "Founding", "start_year": -753, "end_year": -509},
                {"label": "Republican Period", "start_year": -509, "end_year": -27},
            ],
            entity["temporal_periods"],
        )

    def test_add_period_from_draft_defaults_a_blank_name_to_period(self):
        card_view, entity = self._card()
        card = {"is_edit_mode": True}
        self._draft(card_view, card, "period_add_start", "1900")
        self._draft(card_view, card, "period_add_end", "1950")

        card_view.add_period_from_draft(card)

        self.assertEqual(
            [{"label": "Period", "start_year": 1900, "end_year": 1950}],
            entity["temporal_periods"],
        )

    def test_add_period_from_draft_is_a_noop_when_everything_is_blank(self):
        card_view, entity = self._card()
        card = {"is_edit_mode": True}

        added = card_view.add_period_from_draft(card)

        self.assertFalse(added)
        self.assertNotIn("temporal_periods", entity)

    def test_add_period_from_draft_reads_the_field_currently_being_typed(self):
        # If "Add" is clicked while a draft field still has keyboard focus
        # (no Enter/blur commit yet), its live edit_buffer must still count.
        card_view, entity = self._card()
        card = {"is_edit_mode": True}
        self.assertTrue(card_view.begin_edit_field(card, "period_add_name"))
        card["edit_buffer"] = "Uncommitted Name"

        added = card_view.add_period_from_draft(card)

        self.assertTrue(added)
        self.assertEqual("Uncommitted Name", entity["temporal_periods"][0]["label"])

    def test_period_add_cells_do_not_overlap_at_a_very_narrow_width(self):
        import pygame

        pygame.font.init()
        font = pygame.font.SysFont("consolas", 14)
        card_view, _ = self._card()
        card_view.set_active_tab("temporal")
        card = {
            "entity_id": "prod_test",
            "title": "Test",
            "subtitle": "producers | producer",
            "layout_font": font,
            "is_edit_mode": True,
            "active_edit_field": None,
            "edit_buffer": "",
            "card_view": card_view,
            "years": [1800, 2100],
            "selected_year": None,
            "scroll_y": 0,
        }
        card_view.layout_card(card, pygame.Rect(0, 0, 260, 700))

        period_rows = [
            row for row in card["field_rows"]
            if row["key"] in ("period_add_name", "period_add_start", "period_add_end")
        ]
        rects_by_row_y = {}
        for row in period_rows:
            rects_by_row_y.setdefault(row["row_rect"].y, []).append(row["row_rect"])
        button_rect = card.get("period_add_button_rect")
        self.assertIsNotNone(button_rect)
        rects_by_row_y.setdefault(button_rect.y, []).append(button_rect)

        for rects in rects_by_row_y.values():
            for i in range(len(rects)):
                for j in range(i + 1, len(rects)):
                    self.assertFalse(
                        rects[i].colliderect(rects[j]),
                        f"{rects[i]} overlaps {rects[j]}",
                    )


if __name__ == "__main__":
    unittest.main()
