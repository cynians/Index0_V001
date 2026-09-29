import unittest

from simulations.map.map_simulation import MapSimulation


class FailingScreenCamera:
    zoom = 1.0

    def world_to_screen(self, pos):
        raise AssertionError("polygon picking should stay in world space")


class MapPickingTests(unittest.TestCase):
    def test_polygon_pick_with_screen_pos_uses_world_space_hit_test(self):
        layer = {
            "shape": "polygon",
            "entity_id": "loc_square",
            "points": [(-10.0, -10.0), (10.0, -10.0), (10.0, 10.0), (-10.0, 10.0)],
            "_world_bounds": (-10.0, 10.0, -10.0, 10.0),
        }
        sim = MapSimulation.__new__(MapSimulation)
        sim.get_layers = lambda: [layer]

        picked = sim._pick_layer_at_world(
            world_x=0.0,
            world_y=0.0,
            camera=FailingScreenCamera(),
            screen_pos=(50, 50),
        )

        self.assertIs(layer, picked)

    def test_reference_country_remains_pickable_over_continent_at_overview_zoom(self):
        sim = MapSimulation.__new__(MapSimulation)
        sim.get_root_entity = lambda: {
            "id": "planet_earth",
            "location_class": "planet",
            "reference_land_polygons": {"polygons": [[[0, 0], [1, 0], [1, 1]]]},
        }
        sim._surface_location_depth = lambda entity: 1
        sim._location_min_zoom_for_depth = lambda depth, entity: 3.4

        country = {
            "shape": "polygon",
            "entity_id": "loc_country_example",
            "points": [(-5.0, -5.0), (5.0, -5.0), (5.0, 5.0), (-5.0, 5.0)],
            "_world_bounds": (-5.0, 5.0, -5.0, 5.0),
        }
        sim._decorate_surface_location_layer(country, {
            "location_class": "country",
            "bounds_source": "natural_earth_admin_0_reference",
        }, area_world=100.0)

        continent = {
            "shape": "polygon",
            "entity_id": "loc_africa",
            "draw_order": 200,
            "map_hierarchy_depth": 1,
            "area_world": 400.0,
            "is_broad_location_overlay": True,
            "points": [(-10.0, -10.0), (10.0, -10.0), (10.0, 10.0), (-10.0, 10.0)],
            "_world_bounds": (-10.0, 10.0, -10.0, 10.0),
        }
        # The continent is visually topmost because its multipart ring has a
        # later draw order; picking must nevertheless continue to the country.
        sim.get_layers = lambda: [country, continent]

        self.assertEqual(0.0, country["min_zoom"])
        self.assertEqual(100, country["pick_priority"])
        self.assertTrue(country["render_when_interacting_only"])
        self.assertTrue(country["suppress_label"])
        self.assertEqual(0, country["border_width"])
        self.assertGreater(sim._render_layer_sort_key(country), sim._render_layer_sort_key(continent))
        self.assertIs(country, sim._pick_layer_at_world(0.0, 0.0, FailingScreenCamera(), (50, 50)))


class _RightClickEvent:
    type = MapSimulation.MOUSEBUTTONDOWN_EVENT_TYPE
    button = 3


class MapRightClickFloatingCardTests(unittest.TestCase):
    def _sim_with_pick(self, entity_id):
        sim = MapSimulation.__new__(MapSimulation)
        sim._screen_to_world = lambda camera, screen_pos: (0.0, 0.0)
        sim.is_square_editor_active = lambda: False
        sim.is_creating_point_location = False
        sim.is_polygon_editor_active = lambda: False
        sim._pick_layer_at_world = lambda *args, **kwargs: (
            {"entity_id": entity_id} if entity_id else None
        )
        sim._pending_floating_card_target = None
        return sim

    def test_right_click_outside_drafting_opens_an_edit_mode_card(self):
        sim = self._sim_with_pick("location_example")

        sim.handle_pointer_event(_RightClickEvent(), camera=None, screen_pos=(50, 50))

        target = sim.consume_pending_floating_card_target()
        self.assertIsNotNone(target)
        self.assertEqual("location_example", target["id"])
        self.assertEqual("edit", target["mode"])

    def test_right_click_on_empty_map_does_not_open_a_card(self):
        sim = self._sim_with_pick(None)

        sim.handle_pointer_event(_RightClickEvent(), camera=None, screen_pos=(50, 50))

        self.assertIsNone(sim.consume_pending_floating_card_target())

    def test_right_click_during_polygon_drafting_still_cancels_the_draft_not_a_card(self):
        sim = self._sim_with_pick("location_example")
        sim.is_polygon_editor_active = lambda: True
        drafting_calls = []
        sim._handle_polygon_editor_pointer_event = lambda *args, **kwargs: drafting_calls.append(args)

        sim.handle_pointer_event(_RightClickEvent(), camera=None, screen_pos=(50, 50))

        self.assertEqual(1, len(drafting_calls))
        self.assertIsNone(sim.consume_pending_floating_card_target())

    def test_right_click_during_square_drafting_still_cancels_the_draft_not_a_card(self):
        sim = self._sim_with_pick("location_example")
        sim.is_square_editor_active = lambda: True
        drafting_calls = []
        sim._handle_square_editor_pointer_event = lambda *args, **kwargs: drafting_calls.append(args)

        sim.handle_pointer_event(_RightClickEvent(), camera=None, screen_pos=(50, 50))

        self.assertEqual(1, len(drafting_calls))
        self.assertIsNone(sim.consume_pending_floating_card_target())


if __name__ == "__main__":
    unittest.main()
