import unittest

import pygame

from ui.fonts import get_font
from ui.knowledge_browser_ui import KnowledgeBrowserUI


class FontSessionTests(unittest.TestCase):
    def test_fonts_render_after_repeated_pygame_shutdowns(self):
        previous_font = None
        try:
            for _ in range(3):
                pygame.font.init()
                font = get_font()
                self.assertIs(font, get_font())
                self.assertIsNot(font, previous_font)
                self.assertGreater(font.render("Earth 1900–2400 Äé − → μ°", True, "white").get_width(), 0)
                previous_font = font
                pygame.quit()
        finally:
            pygame.quit()


class BrowserTypographyNavigationTests(unittest.TestCase):
    def test_rendered_rows_and_carets_match_click_targets_when_scrolled(self):
        pygame.init()
        pygame.display.set_mode((1, 1))
        try:
            ui = KnowledgeBrowserUI()
            ui.card_drafts = {}
            ui.DRAFT_CACHE_PATH = None
            ui._write_card_drafts = lambda: None
            ui.font_for_layout = get_font()
            ui.browser_font_for_layout = ui._get_browser_font(ui.font_for_layout)
            ui.timeline_collapsed = True
            ui.layout = {
                "left_rect": pygame.Rect(0, 0, 350, 360),
                "right_rect": pygame.Rect(360, 0, 450, 360),
                "timeline_rect": pygame.Rect(0, 0, 0, 0),
                "timeline_splitter_rect": pygame.Rect(0, 0, 0, 0),
            }
            ui.browser_items = [
                {"kind": "tree_entity", "entity_id": f"location_{i}",
                 "text": f"Location {i}", "depth": i % 4, "expandable": True,
                 "expanded": i % 2 == 0, "meta_text": "[star_system]"}
                for i in range(30)
            ]
            ui._draw_card_canvas = lambda *args: None
            screen = pygame.Surface((820, 360))
            left_rect = ui.layout["left_rect"]
            for scroll in (0, 7, 157, 99999):
                with self.subTest(scroll=scroll):
                    ui.browser_scroll = scroll
                    ui._rebuild_browser_hitboxes()
                    rows = [(key, rect.copy()) for key, rect in ui.browser_hitboxes]
                    carets = [(key, rect.copy()) for key, rect in ui.browser_toggle_hitboxes]
                    ui.draw(screen, ui.font_for_layout, lambda *args: None)
                    self.assertEqual(rows, ui.browser_hitboxes)
                    self.assertEqual(carets, ui.browser_toggle_hitboxes)
                    top, bottom = ui._browser_content_bounds(left_rect)
                    for entity_id, rect in rows:
                        if top <= rect.centery <= bottom:
                            self.assertEqual(entity_id, ui._browser_item_at_pos(rect.center, left_rect)["entity_id"])
                    for entity_id, rect in carets:
                        if top <= rect.centery <= bottom:
                            self.assertEqual((entity_id, "locations"), ui._browser_toggle_entity_at_pos(rect.center, left_rect))
        finally:
            pygame.quit()
