import unittest

from simulations.world_gen.heightmap import (
    _boundary_spatial_index,
    _clamp,
    _nearby_boundary_segments,
    _wrapped_point_segment_distance,
)


class HeightmapBoundarySpatialIndexTests(unittest.TestCase):
    def test_index_has_no_false_negatives_across_longitude_seam(self):
        segments = [
            {
                "id": "ordinary",
                "x1": 0.21,
                "y1": 0.25,
                "x2": 0.38,
                "y2": 0.46,
                "influence_width": 0.028,
            },
            {
                "id": "seam",
                "x1": 0.97,
                "y1": 0.58,
                "x2": 0.03,
                "y2": 0.62,
                "influence_width": 0.05,
            },
        ]
        model = {
            "boundary_segments": segments,
            "_heightmap_boundary_spatial_index": _boundary_spatial_index(
                segments,
                bins_x=16,
                bins_y=8,
            ),
        }
        for y_index in range(33):
            ny = y_index / 32.0
            for x_index in range(65):
                nx = 0.0 if x_index == 64 else x_index / 64.0
                nearby = _nearby_boundary_segments(model, nx, ny)
                for segment in segments:
                    distance = _wrapped_point_segment_distance(
                        nx,
                        ny,
                        segment["x1"],
                        segment["y1"],
                        segment["x2"],
                        segment["y2"],
                    )
                    cutoff = _clamp(
                        segment["influence_width"],
                        0.012,
                        0.05,
                    ) * 2.5
                    if distance <= cutoff:
                        self.assertIn(segment, nearby)


if __name__ == "__main__":
    unittest.main()
