import math
import unittest

import numpy as np

from simulations.space.conics import circular_orbit
from simulations.space.trajectory import Body, BodyTree, Node, apply_node, predict
from tests.test_space_transfer import DAY, SUN_MU, body

EARTH = body("Earth")
TREE = BodyTree([
    Body("sun", "Sun", None, SUN_MU, 6.9634e8, math.inf),
    Body("Earth", "Earth", "sun", EARTH.mu, EARTH.radius, EARTH.soi_radius, EARTH),
])
PARKING = EARTH.radius + 200e3


def parked(t0=0.0):
    orbit = circular_orbit(EARTH.mu, PARKING, 0.3, t0)
    return orbit, orbit.state_at(t0)


class NodeTests(unittest.TestCase):
    def test_prograde_runs_along_the_velocity_and_radial_away_from_the_body(self):
        velocity = apply_node(Node(0.0, prograde=10.0, radial=3.0), (7.0e6, 0.0), (0.0, 7500.0))
        np.testing.assert_allclose(velocity, [3.0, 7510.0], atol=1e-9)


class PredictionTests(unittest.TestCase):
    def test_a_parked_craft_with_no_nodes_stays_in_one_orbit(self):
        orbit, (position, velocity) = parked()
        prediction = predict(TREE, "Earth", 0.0, position, velocity, (), 10 * DAY)
        self.assertEqual([("Earth", "horizon")], [(s.frame_id, s.ends) for s in prediction.segments])
        x, y = np.array(prediction.position(5 * DAY, TREE)) - TREE.absolute_position("Earth", 5 * DAY)
        self.assertAlmostEqual(PARKING, math.hypot(x, y), delta=1.0)

    def test_an_escape_burn_leaves_the_sphere_into_the_parents_frame(self):
        orbit, (position, velocity) = parked()
        burn = Node(3600.0, prograde=3600.0)
        prediction = predict(TREE, "Earth", 0.0, position, velocity, (burn,), 30 * DAY)
        self.assertEqual([("Earth", "node"), ("Earth", "exit"), ("sun", "horizon")],
                         [(s.frame_id, s.ends) for s in prediction.segments])
        leaving = prediction.segments[1]
        self.assertTrue(leaving.conic.is_hyperbolic)
        x, y = leaving.conic.state_at(leaving.t_end)[0]
        self.assertAlmostEqual(EARTH.soi_radius, math.hypot(x, y), delta=1.0)
        # the path does not jump where the frame changes
        before = prediction.position(leaving.t_end - 1e-3, TREE)
        after = prediction.position(leaving.t_end + 1e-3, TREE)
        self.assertLess(np.linalg.norm(np.array(before) - np.array(after)), 100.0)

    def test_a_retrograde_burn_that_drops_periapsis_into_the_ground_ends_on_the_surface(self):
        orbit, (position, velocity) = parked()
        prediction = predict(TREE, "Earth", 0.0, position, velocity, (Node(600.0, prograde=-300.0),), 10 * DAY)
        self.assertEqual("impact", prediction.segments[-1].ends)
        x, y = prediction.segments[-1].conic.state_at(prediction.segments[-1].t_end)[0]
        self.assertAlmostEqual(EARTH.radius, math.hypot(x, y), delta=1.0)


if __name__ == "__main__":
    unittest.main()
