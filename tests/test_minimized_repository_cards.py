import unittest
from types import SimpleNamespace
from unittest.mock import patch

import pygame

from tests.test_entity_id_updates import KnowledgeBrowserHarness
from ui.card import EntityCard


def repository_card(**fields):
    pygame.font.init()
    entity = {"id": "location_alpha", "type": "location", "_dataset": "locations",
              "name": "Alpha System", "location_class": "star_system",
              "start_year": 1900, "end_year": 2400,
              "three_word_description": "description stays hidden", **fields}
    ui = KnowledgeBrowserHarness({entity["id"]: entity})
    ui.canvas_zoom = 1.0
    ui.canvas_offset_x = ui.canvas_offset_y = 0
    ui.compact_canvas_zoom_threshold = 0.62
    ui.card_font_cache = {}
    ui.font_for_layout = pygame.font.SysFont("consolas", 16)
    ui.layout = {"right_rect": pygame.Rect(0, 0, 1000, 700)}
    ui.timeline_ui = SimpleNamespace(set_open_canvas_entity_ids=lambda ids: False,
                                     rebuild_layout=lambda: None,
                                     clear_picker_target=lambda: None,
                                     handle_keydown=lambda event: None)
    card = {"entity_id": entity["id"], "title": entity["name"],
            "subtitle": "location | star_system", "years": [1900, 2400], "selected_year": 1900,
            "canvas_x": 24, "canvas_y": 84, "canvas_w": 420, "canvas_h": 400,
            "auto_canvas_h": False,
            "card_view": EntityCard(entity, dataset_name="locations", world_model=ui.world_model)}
    ui.cards = [card]
    ui._relayout_cards = ui._layout_all_cards
    ui._layout_all_cards()
    return ui, card


def click(ui, card, button):
    return ui._handle_card_canvas_click(card[button].center, ui.layout["right_rect"])


class MinimizedRepositoryCardTests(unittest.TestCase):
    def test_minimize_and_expand_restore_size_position_and_controls(self):
        ui, card = repository_card()
        original = card["rect"].copy()
        self.assertEqual("__ui_consumed__", click(ui, card, "minimize_rect"))
        self.assertTrue(card["is_minimized"])
        self.assertLessEqual(card["rect"].width, 260)
        self.assertLessEqual(card["rect"].height, 80)
        self.assertEqual(original.topleft, card["rect"].topleft)
        self.assertEqual([], card["resize_hitboxes"])
        self.assertEqual([], card["launch_mode_hitboxes"])
        for field in ("edit_toggle_rect", "lock_toggle_rect", "launch_rect", "toolbelt_rect",
                      "resize_handle_rect", "minimize_rect", "canvas_relation_add_rect"):
            self.assertIsNone(card.get(field), field)
        self.assertEqual("__ui_consumed__", click(ui, card, "expand_rect"))
        self.assertFalse(card["is_minimized"])
        self.assertEqual(original, card["rect"])
        self.assertIsNotNone(card["edit_toggle_rect"])
        self.assertIsNotNone(card["minimize_rect"])

    def test_minimized_card_has_exactly_three_text_rows_including_dates(self):
        ui, card = repository_card()
        click(ui, card, "minimize_rect")
        screen = pygame.Surface((1000, 700))
        rendered = []
        render_text = ui._render_text

        def record(font, text, color):
            rendered.append(text)
            return render_text(font, text, color)

        with patch.object(ui, "_render_text", side_effect=record):
            ui._draw_card(screen, ui.font_for_layout, card)
        self.assertEqual(["Alpha System", "location | star_system", "1900 – 2400", "x"], rendered)
        last_row_y = card["rect"].y + 6 + ui.font_for_layout.get_linesize() * 2
        self.assertLess(last_row_y + ui.font_for_layout.get_height(), card["rect"].bottom)

    def test_minimized_state_survives_zoom_and_can_expand_while_zoomed_out(self):
        ui, card = repository_card()
        click(ui, card, "minimize_rect")
        for zoom in (0.5, 1.5):
            ui.canvas_zoom = zoom
            ui._layout_all_cards()
            self.assertTrue(card["is_compact_canvas_card"])
        ui.canvas_zoom = 0.5
        ui._layout_all_cards()
        click(ui, card, "expand_rect")
        self.assertFalse(card["is_compact_canvas_card"])

    def test_hidden_editor_keeps_buffer_and_does_not_receive_typing(self):
        ui, card = repository_card()
        card.update(is_edit_mode=True, active_edit_field="name", edit_buffer="unfinished name",
                    edit_cursor=15, edit_original_value="Alpha System")
        ui._layout_all_cards()
        click(ui, card, "minimize_rect")
        with patch.object(card["card_view"], "handle_keydown", side_effect=AssertionError("hidden editor received input")):
            ui._handle_keydown_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_x, unicode="x", mod=0))
        self.assertEqual("unfinished name", card["edit_buffer"])
        click(ui, card, "expand_rect")
        self.assertEqual("name", card["active_edit_field"])
        self.assertEqual("unfinished name", card["edit_buffer"])

    def test_close_removes_only_the_minimized_card_from_the_canvas(self):
        ui, card = repository_card()
        click(ui, card, "minimize_rect")
        ui._close_card_at_index = lambda index: ui.cards.pop(index)
        self.assertEqual("__ui_consumed__", click(ui, card, "close_rect"))
        self.assertEqual([], ui.cards)
        self.assertIn("location_alpha", ui.world_model.loader.entities)
