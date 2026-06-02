import unittest

import pygame

from ui.timeline_ui import TimelineUI


class TimelineTickTests(unittest.TestCase):
    def _timeline(self, min_year, max_year, width=360):
        timeline = TimelineUI()
        timeline.content_rect = pygame.Rect(20, 40, width, 120)
        timeline.view_min_year = min_year
        timeline.view_max_year = max_year
        timeline.axis_y = 64
        return timeline

    def test_axis_ticks_add_intermediate_years_for_visible_span(self):
        timeline = self._timeline(1900, 1920, width=240)

        tick_years = [tick["year"] for tick in timeline._axis_ticks()]

        self.assertIn(1900, tick_years)
        self.assertIn(1910, tick_years)
        self.assertIn(1920, tick_years)

    def test_axis_tick_step_scales_with_zoom_level(self):
        zoomed_out = self._timeline(0, 10000, width=400)
        zoomed_in = self._timeline(1900, 1920, width=400)

        self.assertGreater(zoomed_out._axis_tick_step(), zoomed_in._axis_tick_step())

    def test_axis_tick_labels_keep_endpoints(self):
        pygame.font.init()
        font = pygame.font.SysFont("consolas", 14)
        timeline = self._timeline(1900, 1920, width=180)

        labeled_years = {
            tick["year"]
            for tick in timeline._axis_ticks(font)
            if tick.get("label")
        }

        self.assertIn(1900, labeled_years)
        self.assertIn(1920, labeled_years)

    def test_initial_view_focuses_last_non_period_timeline_item(self):
        timeline = TimelineUI()
        timeline.set_rect(pygame.Rect(0, 0, 400, 160))
        timeline.set_items(
            [
                {
                    "entity_id": "period_old",
                    "timeline_kind": "major_period",
                    "start_year": -1000,
                    "end_year": 1000,
                },
                {
                    "entity_id": "event_first",
                    "start_year": 1900,
                    "end_year": 1900,
                },
                {
                    "entity_id": "event_last",
                    "start_year": 2400,
                    "end_year": 2400,
                },
            ]
        )

        timeline.rebuild_layout()

        self.assertLessEqual(timeline.view_min_year, 2400)
        self.assertGreaterEqual(timeline.view_max_year, 2400)
        self.assertFalse(timeline.view_min_year <= 0 <= timeline.view_max_year)

    def test_initial_view_prefers_selected_year(self):
        timeline = TimelineUI()
        timeline.set_rect(pygame.Rect(0, 0, 400, 160))
        timeline.set_items(
            [
                {
                    "entity_id": "event_last",
                    "start_year": 2400,
                    "end_year": 2400,
                },
            ]
        )
        timeline.set_selected_year(1900)

        timeline.rebuild_layout()

        self.assertLessEqual(timeline.view_min_year, 1900)
        self.assertGreaterEqual(timeline.view_max_year, 1900)


if __name__ == "__main__":
    unittest.main()
