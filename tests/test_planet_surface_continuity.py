"""Continuity of planetary fields that used to switch along knife-edges."""

import math
import unittest

from simulations.world_gen.tectonics import CONTINENTAL_MARGIN_WIDTH, _blended_continental_fraction
from simulations.world_gen.water_cycle import _prevailing_wind_vector


def _plate(plate_id, center_x, center_y, plate_type):
    return {"id": plate_id, "center_x": center_x, "center_y": center_y, "plate_type": plate_type, "boundary_shape": {}}


class ContinentalMarginTests(unittest.TestCase):
    def test_continental_fraction_blends_across_the_plate_boundary(self):
        plates = [_plate("continent", 0.30, 0.5, "continental"), _plate("ocean", 0.70, 0.5, "oceanic")]
        step = 0.0005
        profile = [
            _blended_continental_fraction(plates, 0.40 + index * step, 0.5, "margin-test")
            for index in range(401)
        ]
        self.assertGreater(profile[0], 0.95)
        self.assertLess(profile[-1], 0.05)
        for before, after in zip(profile, profile[1:]):
            self.assertLessEqual(after, before + 1e-9, "fraction falls monotonically toward the ocean")
        # 10-90 % spans about one coarse lithosphere sample (1/96 of the
        # map, ~420 km on Earth): the interpolated coastline follows the true
        # boundary instead of stepping from sample to sample.
        transitional = sum(0.1 < value < 0.9 for value in profile) * step
        self.assertGreater(transitional, 0.8 / 96.0)
        self.assertLess(transitional, 4.0 / 96.0, "still a margin, not a continent-wide ramp")
        self.assertGreater(CONTINENTAL_MARGIN_WIDTH, 0.0)


class SubtropicalRidgeTests(unittest.TestCase):
    def test_winds_calm_where_trades_meet_westerlies_instead_of_flipping(self):
        speeds, headings = [], []
        for tenth in range(150, 350):
            latitude = tenth / 10.0
            wind_x, wind_y = _prevailing_wind_vector(0.5 - latitude / 180.0, "ridge-test", nx=0.3)
            speeds.append(math.hypot(wind_x, wind_y))
            headings.append((wind_x, wind_y))
        self.assertLess(min(speeds), 0.3, "the subtropical high is calm")
        self.assertGreater(speeds[0], 0.9)
        self.assertGreater(speeds[-1], 0.9)
        # Transport (the wind vector itself) changes gradually, not by a unit
        # reversal between neighbouring tenths of a degree.
        steps = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(headings, headings[1:])]
        self.assertLess(max(steps), 0.2)


if __name__ == "__main__":
    unittest.main()
