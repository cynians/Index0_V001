import unittest

from simulations.map.projection import (
    project_map_world_point,
    project_map_world_ring,
    project_normalized_point,
    unproject_map_world_point,
    unproject_normalized_point,
)


class MapProjectionTests(unittest.TestCase):
    def test_normalized_projection_round_trip(self):
        for point in ((0.1, 0.2), (0.5, 0.5), (0.92, 0.78)):
            projected = project_normalized_point(*point, 0.31, -0.17)
            restored = unproject_normalized_point(*projected, 0.31, -0.17)
            self.assertAlmostEqual(point[0], restored[0], places=7)
            self.assertAlmostEqual(point[1], restored[1], places=7)

    def test_authored_map_point_moves_and_remains_editable(self):
        source = (13.405, -52.52)
        projected = project_map_world_point(*source, 0.25, -0.1)
        self.assertNotAlmostEqual(source[0], projected[0])
        restored = unproject_map_world_point(*projected, 0.25, -0.1)
        self.assertAlmostEqual(source[0], restored[0], places=6)
        self.assertAlmostEqual(source[1], restored[1], places=6)

    def test_date_line_polygon_is_unwrapped_without_long_edges(self):
        rings = project_map_world_ring(
            [(179.0, -10.0), (-179.0, -10.0), (-179.0, 10.0), (179.0, 10.0)],
            0.23,
            -0.12,
        )
        self.assertTrue(rings)
        for ring in rings:
            self.assertTrue(all(-180.0 <= point[0] <= 180.0 for point in ring))
            adjacent_spans = [abs(ring[index][0] - ring[index - 1][0]) for index in range(1, len(ring))]
            self.assertLessEqual(max(adjacent_spans), 180.0)

    def test_sparse_authored_edges_morph_and_do_not_duplicate(self):
        rings = project_map_world_ring(
            [(-10.0, -35.0), (40.0, -35.0), (40.0, 30.0), (-10.0, 30.0)],
            24.9 / 360.0,
            -2.9 / 180.0,
        )
        self.assertEqual(1, len(rings))
        self.assertGreater(len(rings[0]), 40)
        self.assertTrue(all(-180.0 <= x <= 180.0 and -90.0 <= y <= 90.0 for x, y in rings[0]))


if __name__ == "__main__":
    unittest.main()
