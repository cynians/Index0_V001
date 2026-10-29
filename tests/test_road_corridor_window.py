import math
import unittest

from simulations.map.road_corridor_window import RoadCorridorWindow
from simulations.world_gen.local_placeholder_heightmap import PLACEHOLDER_HEIGHTMAP_STATUS

# Yard drop-off -> east road entry -> village entrance -> village center,
# matching the real authored lumber-site geometry.
LUMBER_ROUTE_WAYPOINTS = [(6.0, 15.0), (56.0, 15.0), (56.0, -48.0), (25.0, -66.0)]


class RoadCorridorWindowTests(unittest.TestCase):
    def test_total_length_matches_polyline_arc_length(self):
        window = RoadCorridorWindow(LUMBER_ROUTE_WAYPOINTS, slice_spacing_m=40.0)
        expected = (
            math.hypot(50.0, 0.0)
            + math.hypot(0.0, 63.0)
            + math.hypot(31.0, 18.0)
        )
        self.assertAlmostEqual(expected, window.total_length_m, places=6)

    def test_advance_loads_ahead_and_unloads_behind_as_position_moves(self):
        # slice_spacing_m=20 (rather than the site's default 40) gives this
        # ~149m route enough slices (0..7) to demonstrate the window sliding
        # through several steps instead of immediately hitting the route end.
        window = RoadCorridorWindow(
            LUMBER_ROUTE_WAYPOINTS, slice_spacing_m=20.0, slices_ahead=2, slices_behind=1,
        )

        first = window.advance(0.0)
        self.assertEqual({0, 1, 2}, set(first["loaded_indices"]))
        self.assertEqual([0, 1, 2], first["newly_loaded"])
        self.assertEqual([], first["unloaded"])

        second = window.advance(4 * window.slice_spacing_m)
        self.assertEqual({3, 4, 5, 6}, set(second["loaded_indices"]))
        self.assertIn(0, second["unloaded"])
        self.assertIn(1, second["unloaded"])
        self.assertIn(6, second["newly_loaded"])
        # Indices dropped from the window are actually gone, not just hidden.
        self.assertNotIn(0, window.loaded_slices)
        self.assertNotIn(1, window.loaded_slices)

    def test_regenerated_slice_is_deterministic_from_the_same_seed(self):
        window = RoadCorridorWindow(LUMBER_ROUTE_WAYPOINTS, slice_spacing_m=40.0)
        window.advance(0.0)
        first_rows = window.loaded_slices[0]["heightmap_model"]["sample_grid"]["rows"]

        window.advance(10 * window.slice_spacing_m)  # index 0 unloads
        self.assertNotIn(0, window.loaded_slices)
        window.advance(0.0)  # regenerate index 0 from scratch
        second_rows = window.loaded_slices[0]["heightmap_model"]["sample_grid"]["rows"]

        self.assertEqual(first_rows, second_rows)

    def test_target_entity_heightmap_tracks_the_centered_slice(self):
        target_entity = {"id": "location_lumber_east_road", "_dataset": "locations", "type": "location"}
        window = RoadCorridorWindow(
            LUMBER_ROUTE_WAYPOINTS, slice_spacing_m=40.0, target_entity=target_entity,
        )

        window.advance(0.0)
        self.assertEqual(
            PLACEHOLDER_HEIGHTMAP_STATUS, target_entity["heightmap_model"]["status"],
        )
        first_bounds = dict(target_entity["bounds"])

        window.advance(3 * window.slice_spacing_m)
        second_bounds = dict(target_entity["bounds"])
        self.assertNotEqual(first_bounds, second_bounds)


if __name__ == "__main__":
    unittest.main()
