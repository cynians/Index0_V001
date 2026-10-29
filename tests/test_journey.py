import math
import unittest

import numpy as np

from dataclasses import replace

from simulations.logistics.journey import Journey
from simulations.space.trajectory import Body, BodyTree, Node
from simulations.logistics.vehicle_profiles import design_propulsion_state
from simulations.space.conics import Conic, hyperbola_through
from simulations.space.object import SpaceObject
from simulations.space.orbit import KeplerOrbit
from simulations.space.transfer import find_direct_windows, planar_state
from tests.test_space_transfer import AU, DAY, SUN_MASS, SUN_MU, body, seconds
from tools.create_test_craft_pathfinder import build_transaction, world_for


def energy_and_momentum(position, velocity, mu):
    (x, y), (vx, vy) = position, velocity
    return (vx * vx + vy * vy) / 2.0 - mu / math.hypot(x, y), x * vy - y * vx


class ConicTests(unittest.TestCase):
    def test_an_ellipse_matches_the_orbit_the_view_draws(self):
        orbit = KeplerOrbit(SpaceObject("sun", mass=SUN_MASS), a=1.4 * AU, e=0.2, M0=0.7, varpi=1.1)
        position, velocity = orbit.state_at(2.0e6)
        conic = Conic.from_state(position, velocity, SUN_MU, 2.0e6)
        for t in (2.0e6, 4.0e7, 9.1e7):
            np.testing.assert_allclose(conic.state_at(t)[0], orbit.state_at(t)[0], rtol=0, atol=5.0)
            np.testing.assert_allclose(conic.state_at(t)[1], orbit.state_at(t)[1], rtol=0, atol=1e-6)

    def test_a_hyperbola_keeps_its_energy_and_momentum_both_ways_round(self):
        for spin in (1.0, -1.0):
            start = ((AU, 0.0), (0.0, spin * 50_000.0))
            conic = Conic.from_state(*start, SUN_MU, 0.0)
            self.assertTrue(conic.is_hyperbolic)
            reference = energy_and_momentum(*start, SUN_MU)
            for t in (0.0, 3.0e6, 2.0e7):
                position, velocity = conic.state_at(t)
                np.testing.assert_allclose(energy_and_momentum(position, velocity, SUN_MU), reference, rtol=1e-9)
            np.testing.assert_allclose(conic.state_at(0.0)[0], start[0], atol=1.0)
            np.testing.assert_allclose(conic.state_at(0.0)[1], start[1], atol=1e-6)

    def test_a_hyperbola_through_a_given_edge_velocity_has_it_there(self):
        mu, periapsis, edge = 3.986e14, 6.571e6, 9.25e8
        for outgoing, velocity in ((True, (1200.0, 2800.0)), (False, (-2900.0, 400.0))):
            hyperbola, nu = hyperbola_through(mu, periapsis, velocity, edge, outgoing)
            t = hyperbola.time_from_periapsis(nu)
            position, edge_velocity = hyperbola.state_at(t)
            self.assertAlmostEqual(edge, math.hypot(*position), delta=1.0)
            np.testing.assert_allclose(edge_velocity, velocity, atol=1e-6)
            self.assertAlmostEqual(periapsis, math.hypot(*hyperbola.state_at(0.0)[0]), delta=1e-3)
            self.assertEqual(outgoing, t > 0)


class JourneyTests(unittest.TestCase):
    def setUp(self):
        self.earth, self.mars = body("Earth"), body("Mars")
        self.tree = BodyTree([
            Body("sun", "Sun", None, SUN_MU, 6.9634e8, math.inf),
            *[Body(b.id, b.name, "sun", b.mu, b.radius, b.soi_radius, b) for b in (self.earth, self.mars)],
        ])
        self.window = find_direct_windows(self.earth, self.mars, seconds("2026-01-01"), count=1)[0]
        parts = build_transaction()
        self.propulsion = design_propulsion_state(parts[-1], world_for(parts))
        self.journey = Journey.plan("veh_test_craft_pathfinder", "Pathfinder", self.earth, self.mars,
                                    self.window, self.propulsion, self.tree)

    def relative(self, body_elements, t):
        return np.array(self.journey.position(t)) - planar_state(body_elements, t)[0]

    def test_the_untouched_nodes_fly_the_plan_into_a_low_orbit_at_the_target(self):
        journey = self.journey
        self.assertEqual([("Earth", "node"), ("Earth", "exit"), ("sun", "entry"), ("Mars", "node"), ("Mars", "horizon")],
                         [(segment.frame_id, segment.ends) for segment in journey.prediction.segments])
        self.assertAlmostEqual(journey.entry_t, journey.prediction.segments[2].t_end, delta=1.0)
        kind, altitude = journey.outcome()
        self.assertEqual("orbit", kind)
        self.assertAlmostEqual(200e3, altitude, delta=100.0)
        self.assertAlmostEqual(6_571_000.0, np.linalg.norm(self.relative(self.earth, journey.burn_t - 600.0)), delta=1.0)
        self.assertAlmostEqual(3_589_500.0, np.linalg.norm(self.relative(self.mars, journey.capture_t + DAY)), delta=100.0)
        self.assertEqual("In orbit around Earth", journey.situation(journey.burn_t - 600.0))
        self.assertEqual("Leaving Earth", journey.situation(journey.burn_t + DAY))
        self.assertEqual("Cruising around Sun", journey.situation(0.5 * (journey.exit_t + journey.entry_t)))
        self.assertEqual("Approaching Mars", journey.situation(journey.capture_t - 3600.0))
        self.assertEqual("In orbit around Mars", journey.situation(journey.capture_t + DAY))
        self.assertEqual(["orbit", "hyperbola", "cruise", "hyperbola", "orbit"], [kind for _f, kind, _p in journey.segments()])

    def test_editing_a_node_predicts_the_flight_again(self):
        nodes = list(self.journey.nodes)
        nodes[0] = replace(nodes[0], prograde=nodes[0].prograde - 20.0)
        edited = self.journey.with_nodes(nodes)
        kind, distance = edited.outcome()
        self.assertEqual("miss", kind)
        self.assertGreater(distance, self.mars.soi_radius)
        # a node added in the middle of the cruise lands in order
        middle = Node(0.5 * (self.journey.exit_t + self.journey.entry_t), radial=5.0)
        self.assertEqual(middle, self.journey.with_nodes(self.journey.nodes + (middle,)).nodes[1])

    def test_the_legs_meet_at_the_spheres_edges(self):
        journey = self.journey
        for body_elements, hyperbola, t in ((self.earth, journey.departure, journey.exit_t),
                                            (self.mars, journey.arrival, journey.entry_t)):
            centre, centre_velocity = planar_state(body_elements, t)
            on_hyperbola, hyperbola_velocity = hyperbola.state_at(t)
            on_cruise, cruise_velocity = journey.cruise.state_at(t)
            np.testing.assert_allclose(centre + on_hyperbola, on_cruise, rtol=0, atol=100.0)
            np.testing.assert_allclose(centre_velocity + hyperbola_velocity, cruise_velocity, rtol=0, atol=0.01)

    def test_the_burns_are_close_to_the_windows_estimate_and_spend_propellant(self):
        self.assertAlmostEqual(self.window.escape_dv, self.journey.escape_dv, delta=0.03 * self.window.escape_dv)
        self.assertAlmostEqual(self.window.capture_dv, self.journey.capture_dv, delta=0.03 * self.window.capture_dv)
        after = self.journey.propulsion_after()
        spent = self.propulsion.delta_v_m_s() - after.delta_v_m_s()
        self.assertAlmostEqual(self.journey.planned_dv, spent, places=6)
        budget = self.journey.node_budget()
        self.assertEqual(2, len(budget))
        self.assertAlmostEqual(after.delta_v_m_s(), budget[-1][2], places=6)


if __name__ == "__main__":
    unittest.main()
