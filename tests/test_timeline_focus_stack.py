import unittest

import pygame

from ui.timeline_ui import TimelineUI


def _timeline(entities, items):
    pygame.font.init()
    timeline = TimelineUI()
    timeline.set_rect(pygame.Rect(0, 0, 640, 400))
    timeline.set_font(pygame.font.SysFont("consolas", 14))
    timeline.set_entity_lookup({e["id"]: e for e in entities})
    timeline.set_items(items)
    return timeline


def _lane_of(timeline, entity_id):
    for item in timeline.layout_items:
        if item.get("entity_id") == entity_id:
            return item["lane"]
    return None


class TimelineFocusStackTests(unittest.TestCase):
    def _world(self):
        entities = [
            {"id": "hero", "type": "person", "start_year": 1000, "related": ["ally", "rival"]},
            {"id": "stranger", "type": "person", "start_year": 1001},
            {"id": "rival", "type": "person", "start_year": 1002, "related": ["hero"]},
            {"id": "ally", "type": "person", "start_year": 1003},
            {"id": "friend_of_ally", "type": "person", "start_year": 1004, "related": ["ally"]},
        ]
        items = [
            {"entity_id": e["id"], "label": e["id"], "dataset": "people",
             "entity_type": "person", "start_year": e["start_year"], "end_year": e["start_year"]}
            for e in entities
        ]
        return entities, items

    def test_focus_pins_card_line_to_top_with_links_by_relevance(self):
        entities, items = self._world()
        timeline = _timeline(entities, items)
        timeline.set_timeline_focus_entity_ids(["hero"])
        timeline.rebuild_layout()

        self.assertEqual(len(timeline.focus_lane_ranges), 1)
        focus_range = timeline.focus_lane_ranges[0]
        self.assertEqual(focus_range["focus_id"], "hero")
        self.assertEqual(focus_range["header_lane"], 0)
        self.assertTrue(focus_range["has_bar"])

        hero_lane = _lane_of(timeline, "hero")
        rival_lane = _lane_of(timeline, "rival")
        ally_lane = _lane_of(timeline, "ally")
        friend_lane = _lane_of(timeline, "friend_of_ally")
        stranger_lane = _lane_of(timeline, "stranger")

        # focus line first, then direct links (rival outranks ally: two shared
        # relation edges vs one), then the second-degree link, then unlinked.
        self.assertEqual(hero_lane, focus_range["first_lane"])
        self.assertLess(hero_lane, rival_lane)
        self.assertLess(rival_lane, ally_lane)
        self.assertLess(ally_lane, friend_lane)
        self.assertLess(friend_lane, stranger_lane)

    def test_no_date_focus_still_gets_header_and_ranked_links(self):
        entities, items = self._world()
        entities.append({"id": "ghost", "type": "idea", "related": ["ally", "rival"]})
        timeline = _timeline(entities, items)
        timeline.set_timeline_focus_entity_ids(["ghost"])
        timeline.rebuild_layout()

        self.assertEqual(len(timeline.focus_lane_ranges), 1)
        focus_range = timeline.focus_lane_ranges[0]
        self.assertEqual(focus_range["focus_id"], "ghost")
        self.assertFalse(focus_range["has_bar"])
        self.assertIsNone(_lane_of(timeline, "ghost"))

        ally_lane = _lane_of(timeline, "ally")
        rival_lane = _lane_of(timeline, "rival")
        stranger_lane = _lane_of(timeline, "stranger")
        self.assertEqual(min(ally_lane, rival_lane), focus_range["first_lane"])
        self.assertLess(max(ally_lane, rival_lane), stranger_lane)

    def test_multiple_focus_cards_stack_in_lock_order(self):
        entities, items = self._world()
        entities.append({"id": "loner", "type": "person", "start_year": 1001})
        items.append({"entity_id": "loner", "label": "loner", "dataset": "people",
                      "entity_type": "person", "start_year": 1001, "end_year": 1001})
        timeline = _timeline(entities, items)
        timeline.set_timeline_focus_entity_ids(["loner", "hero"])
        timeline.rebuild_layout()

        self.assertEqual([r["focus_id"] for r in timeline.focus_lane_ranges], ["loner", "hero"])
        self.assertLess(_lane_of(timeline, "loner"), _lane_of(timeline, "hero"))
        # hero's linked entries follow hero, all above any unfocused leftovers
        self.assertLess(_lane_of(timeline, "hero"), _lane_of(timeline, "ally"))

    def test_clearing_focus_restores_plain_layout(self):
        entities, items = self._world()
        timeline = _timeline(entities, items)
        timeline.set_timeline_focus_entity_ids(["hero"])
        timeline.rebuild_layout()
        self.assertTrue(timeline.focus_lane_ranges)

        timeline.set_timeline_focus_entity_ids([])
        timeline.rebuild_layout()
        self.assertEqual(timeline.focus_lane_ranges, [])


if __name__ == "__main__":
    unittest.main()
