import unittest

import pygame

from ui.card import EntityCard


class CardColorPickerCacheTests(unittest.TestCase):
    def setUp(self):
        EntityCard.COLOR_SLIDER_SURFACE_CACHE.clear()
        self.card = EntityCard.__new__(EntityCard)
        self.screen = pygame.Surface((240, 80))
        self.rect = pygame.Rect(10, 10, 120, 10)

    def test_unchanged_slider_reuses_cached_surface(self):
        self.card._draw_color_slider_track(self.screen, self.rect, "s", 0.2, 0.4, 0.8)
        first = next(iter(EntityCard.COLOR_SLIDER_SURFACE_CACHE.values()))
        self.card._draw_color_slider_track(self.screen, self.rect, "s", 0.2, 0.4, 0.8)

        self.assertEqual(1, len(EntityCard.COLOR_SLIDER_SURFACE_CACHE))
        self.assertIs(first, next(iter(EntityCard.COLOR_SLIDER_SURFACE_CACHE.values())))

    def test_hue_track_is_shared_across_card_colors(self):
        self.card._draw_color_slider_track(self.screen, self.rect, "h", 0.1, 0.2, 0.3)
        self.card._draw_color_slider_track(self.screen, self.rect, "h", 0.8, 0.9, 1.0)

        self.assertEqual(1, len(EntityCard.COLOR_SLIDER_SURFACE_CACHE))

    def test_dependent_slider_rebuilds_when_color_changes(self):
        self.card._draw_color_slider_track(self.screen, self.rect, "v", 0.1, 0.3, 0.5)
        self.card._draw_color_slider_track(self.screen, self.rect, "v", 0.7, 0.3, 0.5)

        self.assertEqual(2, len(EntityCard.COLOR_SLIDER_SURFACE_CACHE))


if __name__ == "__main__":
    unittest.main()
