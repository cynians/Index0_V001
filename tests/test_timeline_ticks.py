import unittest
from unittest.mock import patch

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

    def test_group_filters_toggle_multiple_top_level_categories(self):
        timeline = TimelineUI()
        timeline.set_rect(pygame.Rect(0, 0, 500, 180))
        timeline.view_min_year = 1900
        timeline.view_max_year = 2100
        timeline._view_range_initialized = True
        timeline.set_items(
            [
                {"entity_id": "loc_one", "dataset": "locations", "start_year": 1950, "end_year": 1960},
                {"entity_id": "veh_one", "dataset": "vehicles", "start_year": 1950, "end_year": 1960},
                {"entity_id": "idea_one", "dataset": "ideas", "start_year": 1950, "end_year": 1960},
            ]
        )

        self.assertTrue(timeline.toggle_active_filter_group("locations"))
        self.assertTrue(timeline.toggle_active_filter_group("engineering"))

        visible_ids = {
            item["entity_id"]
            for item in timeline._filtered_visible_items()
            if item.get("timeline_kind") != "major_period"
        }

        self.assertEqual({"loc_one", "veh_one"}, visible_ids)
        self.assertEqual({"engineering", "locations"}, timeline.active_filter_groups)

    def test_species_animals_and_cladistics_are_hidden_by_default(self):
        timeline = TimelineUI()
        timeline.set_rect(pygame.Rect(0, 0, 500, 180))
        timeline.view_min_year = 1900
        timeline.view_max_year = 2100
        timeline._view_range_initialized = True
        timeline.set_items(
            [
                {"entity_id": "period_context", "timeline_kind": "major_period", "start_year": 1900, "end_year": 2100},
                {"entity_id": "event_one", "dataset": "events", "start_year": 1950, "end_year": 1960},
                {"entity_id": "species_one", "dataset": "species", "entity_type": "species", "start_year": 1950, "end_year": 1960},
                {"entity_id": "animal_one", "dataset": "animals", "entity_type": "animal", "start_year": 1950, "end_year": 1960},
                {"entity_id": "clade_one", "dataset": "cladistics", "entity_type": "cladistics", "start_year": 1950, "end_year": 1960},
            ]
        )

        visible_ids = {item["entity_id"] for item in timeline._filtered_visible_items()}

        self.assertEqual({"period_context", "event_one"}, visible_ids)
        self.assertNotIn("species", timeline._available_filter_categories())
        self.assertNotIn("animals", timeline._available_filter_categories())
        self.assertNotIn("cladistics", timeline._available_filter_categories())

    def test_period_filter_bar_uses_two_click_range(self):
        timeline = self._timeline(1900, 2000, width=100)
        timeline.rect = pygame.Rect(0, 0, 160, 100)
        timeline.period_filter_rect = pygame.Rect(20, 70, 100, 10)

        started = timeline.handle_click((40, 75))
        finished = timeline.handle_click((90, 75))

        self.assertEqual("period_filter_started", started["kind"])
        self.assertEqual("period_filter_changed", finished["kind"])
        self.assertEqual((1920, 1970), timeline.period_filter_range)

    def test_axis_year_pick_ignores_lower_timeline_content(self):
        timeline = self._timeline(1900, 2000, width=100)
        timeline.rect = pygame.Rect(0, 0, 160, 120)

        self.assertEqual(1920, timeline.pick_year_from_axis_pos((40, timeline.axis_y)))
        self.assertIsNone(timeline.pick_year_from_axis_pos((40, timeline.axis_y + 24)))

    def test_working_year_filter_keeps_extant_items(self):
        timeline = self._timeline(1900, 2000, width=200)
        timeline.set_working_year_enabled(True)
        timeline.set_items(
            [
                {"entity_id": "started", "dataset": "locations", "start_year": 1900},
                {"entity_id": "bounded", "dataset": "locations", "start_year": 1940, "end_year": 1960},
                {"entity_id": "ended", "dataset": "locations", "start_year": 1800, "end_year": 1900},
                {"entity_id": "future", "dataset": "locations", "start_year": 2000},
                {"entity_id": "point", "dataset": "events", "start_year": 1950, "end_year": 1950},
                {"entity_id": "ends_later", "dataset": "events", "end_year": 1955},
            ]
        )

        timeline.set_working_year(1950)

        visible_ids = {
            item["entity_id"]
            for item in timeline._filtered_visible_items()
            if item.get("timeline_kind") != "major_period"
        }

        self.assertEqual({"started", "bounded", "point", "ends_later"}, visible_ids)

    def test_working_period_filter_keeps_items_overlapping_period(self):
        timeline = self._timeline(2000, 2030, width=200)
        timeline.set_working_year_enabled(True)
        timeline.set_items(
            [
                {"entity_id": "before", "dataset": "events", "start_year": 2008, "end_year": 2012},
                {"entity_id": "overlaps_start", "dataset": "events", "start_year": 2010, "end_year": 2014},
                {"entity_id": "inside", "dataset": "events", "start_year": 2014, "end_year": 2015},
                {"entity_id": "overlaps_end", "dataset": "events", "start_year": 2016, "end_year": 2020},
                {"entity_id": "after", "dataset": "events", "start_year": 2017, "end_year": 2020},
                {"entity_id": "open_started", "dataset": "events", "start_year": 2010},
                {"entity_id": "open_ended", "dataset": "events", "end_year": 2014},
            ]
        )

        timeline.set_working_year("2013 - 2016")

        visible_ids = {
            item["entity_id"]
            for item in timeline._filtered_visible_items()
            if item.get("timeline_kind") != "major_period"
        }

        self.assertEqual(
            {"overlaps_start", "inside", "overlaps_end", "open_started", "open_ended"},
            visible_ids,
        )
        self.assertIsNone(timeline.get_working_year())
        self.assertEqual((2013, 2016), timeline.get_working_year_range())

    def test_working_year_input_keydown_commits_filter(self):
        timeline = self._timeline(1900, 2000, width=200)
        timeline.set_working_year_enabled(True)
        timeline.working_year_active = True

        for character in "1950":
            action = timeline.handle_keydown(
                type("Event", (), {"key": ord(character), "unicode": character})()
            )
            self.assertEqual("working_year_editing", action["kind"])

        action = timeline.handle_keydown(
            type("Event", (), {"key": pygame.K_RETURN, "unicode": "\r"})()
        )

        self.assertEqual("working_year_changed", action["kind"])
        self.assertEqual(1950, action["year"])
        self.assertEqual(1950, timeline.get_working_year())
        self.assertFalse(timeline.working_year_active)

    def test_working_period_input_keydown_commits_filter(self):
        timeline = self._timeline(2000, 2030, width=200)
        timeline.set_working_year_enabled(True)
        timeline.working_year_active = True

        for character in "2013 - 2016":
            action = timeline.handle_keydown(
                type("Event", (), {"key": ord(character), "unicode": character})()
            )
            self.assertEqual("working_year_editing", action["kind"])

        action = timeline.handle_keydown(
            type("Event", (), {"key": pygame.K_RETURN, "unicode": "\r"})()
        )

        self.assertEqual("working_year_changed", action["kind"])
        self.assertIsNone(action["year"])
        self.assertEqual(2013, action["start_year"])
        self.assertEqual(2016, action["end_year"])
        self.assertEqual((2013, 2016), timeline.get_working_year_range())
        self.assertFalse(timeline.working_year_active)

    def test_working_year_accepts_and_formats_mya_values(self):
        timeline = self._timeline(-50_000_000, 2030, width=200)
        timeline.set_working_year_enabled(True)

        self.assertTrue(timeline.set_working_year("42MYA"))

        self.assertEqual(-42_000_000, timeline.get_working_year())
        self.assertEqual("42MYA", timeline._format_working_year_display_value())

    def test_random_working_year_candidates_collapse_geologic_time(self):
        timeline = self._timeline(-50_000_000, 2050, width=200)
        timeline.set_items(
            [
                {"entity_id": "event_one", "dataset": "events", "start_year": 1, "end_year": 3},
                {"entity_id": "event_future", "dataset": "events", "start_year": 2942, "end_year": 2943},
                {"entity_id": "deep_event", "dataset": "events", "start_year": -42_000_000, "end_year": -42_000_000},
                {"entity_id": "species_hidden", "dataset": "species", "entity_type": "species", "start_year": -41_000_000, "end_year": -41_000_000},
            ]
        )

        candidates = set(timeline._random_working_year_candidates())

        self.assertEqual({1, 2, 3, 2942, 2943, -42_000_000}, candidates)
        self.assertNotIn(-41_000_000, candidates)

    def test_random_working_year_sets_and_focuses_year(self):
        timeline = self._timeline(-50_000_000, 2050, width=200)
        timeline.set_working_year_enabled(True)
        timeline.set_items(
            [
                {"entity_id": "deep_event", "dataset": "events", "start_year": -42_000_000, "end_year": -42_000_000},
            ]
        )
        timeline.rebuild_layout()

        with patch("ui.timeline_ui.random.choice", return_value=-42_000_000):
            action = timeline.set_random_working_year()

        self.assertEqual("random_working_year_changed", action["kind"])
        self.assertEqual(-42_000_000, timeline.get_working_year())
        self.assertEqual("42MYA", timeline._format_working_year_display_value())

    def test_random_working_year_button_click_sets_year(self):
        pygame.font.init()
        timeline = TimelineUI()
        timeline.set_rect(pygame.Rect(0, 0, 560, 180))
        timeline.layout_font = pygame.font.Font(None, 18)
        timeline.set_working_year_enabled(True)
        timeline.set_items(
            [
                {"entity_id": "event_one", "dataset": "events", "start_year": 2016, "end_year": 2016},
            ]
        )
        timeline._rebuild_filter_hitboxes()

        self.assertGreater(timeline.random_working_year_rect.width, 0)
        with patch("ui.timeline_ui.random.choice", return_value=2016):
            action = timeline.handle_click(timeline.random_working_year_rect.center)

        self.assertEqual("random_working_year_changed", action["kind"])
        self.assertEqual(2016, timeline.get_working_year())

    def test_location_focus_keeps_entities_in_location_subtree(self):
        timeline = self._timeline(2000, 2030, width=200)
        timeline.set_location_focus_enabled(True)
        timeline.set_entity_lookup(
            {
                "loc_spain": {"id": "loc_spain", "_dataset": "locations", "name": "Spain"},
                "loc_north_spain": {
                    "id": "loc_north_spain",
                    "_dataset": "locations",
                    "name": "Northern Spain",
                    "parents": ["loc_spain"],
                },
                "loc_bilbao": {
                    "id": "loc_bilbao",
                    "_dataset": "locations",
                    "name": "Bilbao",
                    "parent_location": "loc_north_spain",
                },
                "loc_mars": {"id": "loc_mars", "_dataset": "locations", "name": "Mars"},
                "event_bilbao": {
                    "id": "event_bilbao",
                    "_dataset": "events",
                    "name": "Bilbao Event",
                    "location_entity": "loc_bilbao",
                },
                "event_spain": {
                    "id": "event_spain",
                    "_dataset": "events",
                    "name": "Spain Event",
                    "associated_locations": ["loc_spain"],
                },
                "event_mars": {
                    "id": "event_mars",
                    "_dataset": "events",
                    "name": "Mars Event",
                    "location_entity": "loc_mars",
                },
            }
        )
        timeline.set_items(
            [
                {"entity_id": "period_context", "timeline_kind": "major_period", "start_year": 2000, "end_year": 2030},
                {"entity_id": "loc_north_spain", "dataset": "locations", "start_year": 2000, "end_year": 2030},
                {"entity_id": "loc_bilbao", "dataset": "locations", "start_year": 2000, "end_year": 2030},
                {"entity_id": "loc_mars", "dataset": "locations", "start_year": 2000, "end_year": 2030},
                {"entity_id": "event_bilbao", "dataset": "events", "start_year": 2016, "end_year": 2020},
                {"entity_id": "event_spain", "dataset": "events", "start_year": 2016, "end_year": 2020},
                {"entity_id": "event_mars", "dataset": "events", "start_year": 2016, "end_year": 2020},
            ]
        )

        timeline.set_location_focus("Northern Spain")

        visible_ids = {item["entity_id"] for item in timeline._filtered_visible_items()}

        self.assertEqual({"period_context", "loc_north_spain", "loc_bilbao", "event_bilbao"}, visible_ids)
        self.assertEqual("loc_north_spain", timeline.get_location_focus())

    def test_location_focus_treats_constituents_as_subtree(self):
        timeline = self._timeline(2000, 2030, width=200)
        timeline.set_location_focus_enabled(True)
        timeline.set_entity_lookup(
            {
                "loc_spain": {
                    "id": "loc_spain",
                    "_dataset": "locations",
                    "name": "Spain",
                    "constituents": ["loc_north_spain"],
                },
                "loc_north_spain": {
                    "id": "loc_north_spain",
                    "_dataset": "locations",
                    "name": "Northern Spain",
                },
                "event_bilbao": {
                    "id": "event_bilbao",
                    "_dataset": "events",
                    "name": "Bilbao Event",
                    "location_entity": "loc_north_spain",
                },
            }
        )
        timeline.set_items(
            [
                {"entity_id": "loc_north_spain", "dataset": "locations", "start_year": 2000, "end_year": 2030},
                {"entity_id": "event_bilbao", "dataset": "events", "start_year": 2016, "end_year": 2020},
            ]
        )

        timeline.set_location_focus("Spain")

        visible_ids = {item["entity_id"] for item in timeline._filtered_visible_items()}

        self.assertEqual({"loc_north_spain", "event_bilbao"}, visible_ids)

    def test_location_focus_combines_with_working_period(self):
        timeline = self._timeline(2000, 2030, width=200)
        timeline.set_working_year_enabled(True)
        timeline.set_location_focus_enabled(True)
        timeline.set_entity_lookup(
            {
                "loc_planet_x": {"id": "loc_planet_x", "_dataset": "locations", "name": "Planet X"},
                "event_early": {"id": "event_early", "_dataset": "events", "location_entity": "loc_planet_x"},
                "event_late": {"id": "event_late", "_dataset": "events", "location_entity": "loc_planet_x"},
                "event_elsewhere": {"id": "event_elsewhere", "_dataset": "events"},
            }
        )
        timeline.set_items(
            [
                {"entity_id": "event_early", "dataset": "events", "start_year": 2016, "end_year": 2020},
                {"entity_id": "event_late", "dataset": "events", "start_year": 2101, "end_year": 2110},
                {"entity_id": "event_elsewhere", "dataset": "events", "start_year": 2016, "end_year": 2020},
            ]
        )

        timeline.set_working_year("2016 - 2100")
        timeline.set_location_focus("Planet X")

        visible_ids = {item["entity_id"] for item in timeline._filtered_visible_items()}

        self.assertEqual({"event_early"}, visible_ids)

    def test_location_focus_input_keydown_commits_location(self):
        timeline = self._timeline(2000, 2030, width=200)
        timeline.set_location_focus_enabled(True)
        timeline.set_entity_lookup(
            {
                "loc_planet_x": {"id": "loc_planet_x", "_dataset": "locations", "name": "Planet X"},
            }
        )
        timeline.location_focus_active = True

        for character in "Planet X":
            action = timeline.handle_keydown(
                type("Event", (), {"key": ord(character), "unicode": character})()
            )
            self.assertEqual("location_focus_editing", action["kind"])

        action = timeline.handle_keydown(
            type("Event", (), {"key": pygame.K_RETURN, "unicode": "\r"})()
        )

        self.assertEqual("location_focus_changed", action["kind"])
        self.assertEqual("loc_planet_x", action["location_id"])
        self.assertEqual("loc_planet_x", timeline.get_location_focus())
        self.assertFalse(timeline.location_focus_active)

    def test_location_focus_suggestions_are_location_only_and_ranked(self):
        timeline = self._timeline(2000, 2030, width=200)
        timeline.set_location_focus_enabled(True)
        timeline.set_entity_lookup(
            {
                "loc_planet_x": {"id": "loc_planet_x", "_dataset": "locations", "name": "Planet X"},
                "loc_planet_y": {"id": "loc_planet_y", "_dataset": "locations", "name": "Planet Y"},
                "event_planet_x": {"id": "event_planet_x", "_dataset": "events", "name": "Planet X Incident"},
            }
        )

        matches = timeline._build_location_focus_matches("Planet X")

        self.assertEqual(["loc_planet_x"], [match["id"] for match in matches])

    def test_location_focus_suggestion_keyboard_selection(self):
        timeline = self._timeline(2000, 2030, width=200)
        timeline.set_location_focus_enabled(True)
        timeline.set_entity_lookup(
            {
                "loc_alpha": {"id": "loc_alpha", "_dataset": "locations", "name": "Alpha"},
                "loc_beta": {"id": "loc_beta", "_dataset": "locations", "name": "Beta"},
            }
        )
        timeline.location_focus_active = True
        timeline.location_focus_buffer = ""
        timeline._refresh_location_focus_matches()

        down = timeline.handle_keydown(type("Event", (), {"key": pygame.K_DOWN, "unicode": ""})())
        enter = timeline.handle_keydown(type("Event", (), {"key": pygame.K_RETURN, "unicode": "\r"})())

        self.assertEqual("location_focus_editing", down["kind"])
        self.assertEqual("location_focus_changed", enter["kind"])
        self.assertEqual("loc_beta", timeline.get_location_focus())

    def test_location_focus_suggestion_click_selects_match(self):
        timeline = self._timeline(2000, 2030, width=200)
        timeline.set_rect(pygame.Rect(0, 0, 320, 180))
        timeline.set_location_focus_enabled(True)
        timeline.set_entity_lookup(
            {
                "loc_planet_x": {"id": "loc_planet_x", "_dataset": "locations", "name": "Planet X"},
            }
        )
        timeline.location_focus_active = True
        timeline.location_focus_buffer = "Planet"
        timeline._refresh_location_focus_matches()
        timeline.location_focus_suggestion_hitboxes = [(0, pygame.Rect(80, 60, 160, 22))]

        action = timeline.handle_click((90, 65))

        self.assertEqual("location_focus_changed", action["kind"])
        self.assertEqual("loc_planet_x", timeline.get_location_focus())

    def test_random_location_focus_uses_extant_locations_in_working_year(self):
        timeline = self._timeline(2000, 2030, width=200)
        timeline.set_working_year_enabled(True)
        timeline.set_location_focus_enabled(True)
        timeline.set_entity_lookup(
            {
                "loc_present": {"id": "loc_present", "_dataset": "locations", "name": "Present"},
                "loc_future": {"id": "loc_future", "_dataset": "locations", "name": "Future"},
                "event_present": {"id": "event_present", "_dataset": "events", "name": "Present Event"},
            }
        )
        timeline.set_items(
            [
                {"entity_id": "loc_present", "dataset": "locations", "start_year": 2010, "end_year": 2020},
                {"entity_id": "loc_future", "dataset": "locations", "start_year": 2040, "end_year": 2050},
                {"entity_id": "event_present", "dataset": "events", "start_year": 2016, "end_year": 2016},
            ]
        )
        timeline.set_working_year(2016)

        with patch("ui.timeline_ui.random.choice", return_value="loc_present"):
            action = timeline.set_random_location_focus()

        self.assertEqual("random_location_focus_changed", action["kind"])
        self.assertEqual("loc_present", timeline.get_location_focus())
        self.assertEqual(["loc_present"], timeline._random_extant_location_ids())

    def test_random_location_focus_without_working_year_uses_all_locations(self):
        timeline = self._timeline(2000, 2030, width=200)
        timeline.set_location_focus_enabled(True)
        timeline.set_entity_lookup(
            {
                "loc_alpha": {"id": "loc_alpha", "_dataset": "locations", "name": "Alpha"},
                "loc_beta": {"id": "loc_beta", "_dataset": "locations", "name": "Beta"},
                "event_alpha": {"id": "event_alpha", "_dataset": "events", "name": "Alpha Event"},
            }
        )

        with patch("ui.timeline_ui.random.choice", return_value="loc_beta"):
            action = timeline.set_random_location_focus()

        self.assertEqual("random_location_focus_changed", action["kind"])
        self.assertEqual("loc_beta", timeline.get_location_focus())
        self.assertEqual(["loc_alpha", "loc_beta"], timeline._random_extant_location_ids())

    def test_timeline_item_click_opens_entity(self):
        timeline = TimelineUI()
        timeline.set_rect(pygame.Rect(0, 0, 500, 200))
        timeline.view_min_year = 1900
        timeline.view_max_year = 2000
        timeline._view_range_initialized = True
        timeline.set_items(
            [
                {
                    "entity_id": "event_alpha",
                    "label": "Alpha Event",
                    "dataset": "events",
                    "start_year": 1940,
                    "end_year": 1940,
                }
            ]
        )
        timeline.rebuild_layout()
        item = timeline.layout_items[0]
        hit_rect = timeline._timeline_item_hit_rect(item)

        action = timeline.handle_click(hit_rect.center)

        self.assertEqual("open_timeline_entity", action["kind"])
        self.assertEqual("event_alpha", action["entity_id"])
        self.assertEqual(1940, action["start_year"])

    def test_timeline_item_commentary_is_available_when_zoomed_in(self):
        timeline = self._timeline(1900, 2000, width=200)

        self.assertTrue(timeline._show_item_commentary())
        self.assertEqual(
            "Start: founded",
            timeline._item_commentary_text({"commentary": "Start: founded"}),
        )

    def test_offspring_sort_mode_nests_children_under_expanded_parent(self):
        timeline = TimelineUI()
        timeline.set_rect(pygame.Rect(0, 0, 500, 260))
        timeline.view_min_year = 1900
        timeline.view_max_year = 2050
        timeline._view_range_initialized = True
        timeline.set_entity_lookup(
            {
                "parent": {"id": "parent", "_dataset": "ideas", "offspring": [{"id": "child"}]},
                "child": {"id": "child", "_dataset": "ideas", "parents": ["parent"]},
            }
        )
        timeline.set_items(
            [
                {"entity_id": "parent", "label": "Parent", "dataset": "ideas", "start_year": 1950, "end_year": 1960},
                {"entity_id": "child", "label": "Child", "dataset": "ideas", "start_year": 1940, "end_year": 1980},
            ]
        )

        timeline.set_timeline_sort_mode("offspring")
        timeline.rebuild_layout()

        self.assertEqual(["parent", "child"], [item["entity_id"] for item in timeline.layout_items])
        self.assertEqual((1940, 1980), (timeline.layout_items[0]["start_year"], timeline.layout_items[0]["end_year"]))
        self.assertEqual(1, timeline.layout_items[1]["nest_depth"])

    def test_sort_mode_button_changes_layout_mode(self):
        pygame.font.init()
        font = pygame.font.SysFont("consolas", 14)
        timeline = TimelineUI()
        timeline.set_rect(pygame.Rect(0, 0, 500, 180))
        timeline.set_font(font)
        timeline._rebuild_filter_hitboxes()
        nest_rect = next(rect for mode, _, rect in timeline.sort_mode_hitboxes if mode == "offspring")

        action = timeline.handle_click(nest_rect.center)

        self.assertEqual("timeline_sort_changed", action["kind"])
        self.assertEqual("offspring", timeline.timeline_sort_mode)


if __name__ == "__main__":
    unittest.main()
