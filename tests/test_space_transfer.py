import math
import unittest
from datetime import datetime
from types import SimpleNamespace

import numpy as np

from simulations.space.object import SpaceObject
from simulations.space.orbit import G, KeplerOrbit
from simulations.space.space_simulation import SpaceSimulation
from simulations.space.transfer import (
    TransferBody,
    capture_burn,
    escape_burn,
    find_direct_windows,
    hohmann_estimate,
    lambert_planar,
    planar_state,
)

DAY = 86_400.0
AU = 149_597_870_700.0
SUN_MASS = 1.98847e30
SUN_MU = G * SUN_MASS

# Sol's stored elements (J2000): a, e, mean anomaly, node, argument of periapsis, mass, radius.
ELEMENTS = {
    "Venus": (108_208_000_000.0, 0.006772, 50.115, 76.68, 54.884, 4.8675e24, 6_051_800.0),
    "Earth": (149_597_870_700.0, 0.0167086, 358.617, -11.26064, 114.20783, 5.97219e24, 6_371_000.0),
    "Mars": (227_939_200_000.0, 0.0934, 19.373, 49.558, 286.502, 6.4171e23, 3_389_500.0),
    "Jupiter": (778_570_000_000.0, 0.0489, 20.02, 100.464, 273.867, 1.89813e27, 69_911_000.0),
}


def body(name):
    a, e, mean_anomaly, node, periapsis, mass, radius = ELEMENTS[name]
    return TransferBody(id=name, name=name, a=a, e=e, M0=math.radians(mean_anomaly),
                        varpi=math.radians(node + periapsis), mu=G * mass, radius=radius, parent_mu=SUN_MU)


def seconds(date_text):
    return (datetime.fromisoformat(date_text) - datetime(2000, 1, 1, 12)).total_seconds()


def days_between(t, date_text):
    return abs(t - seconds(date_text)) / DAY


def coast(r, v, dt):
    """Where the conic through (r, v) is after dt, using the sim's own KeplerOrbit."""
    r = np.asarray(r, dtype=float)
    v = np.asarray(v, dtype=float)
    rn = np.linalg.norm(r)
    a = 1.0 / (2.0 / rn - v @ v / SUN_MU)
    e_vec = ((v @ v - SUN_MU / rn) * r - (r @ v) * v) / SUN_MU
    e = np.linalg.norm(e_vec)
    varpi = math.atan2(e_vec[1], e_vec[0])
    nu = math.atan2(r[1], r[0]) - varpi
    E = 2.0 * math.atan(math.sqrt((1 - e) / (1 + e)) * math.tan(nu / 2.0))
    orbit = KeplerOrbit(SpaceObject("sun", mass=SUN_MASS), a=a, e=e, M0=E - e * math.sin(E), varpi=varpi)
    return np.array(orbit.state_at(dt)[0])


class LambertTests(unittest.TestCase):
    def test_exactly_180_degrees_between_circular_orbits_is_the_hohmann_transfer(self):
        r1, r2 = AU, 1.524 * AU
        tof = math.pi * math.sqrt((0.5 * (r1 + r2)) ** 3 / SUN_MU)
        v1, v2 = lambert_planar(np.array([r1, 0.0]), np.array([-r2, 0.0]), tof, SUN_MU)
        v_peri = math.sqrt(SUN_MU / r1) * math.sqrt(2 * r2 / (r1 + r2))
        v_apo = math.sqrt(SUN_MU / r2) * math.sqrt(2 * r1 / (r1 + r2))
        np.testing.assert_allclose(v1, [0.0, v_peri], atol=1e-3)
        np.testing.assert_allclose(v2, [0.0, -v_apo], atol=1e-3)

    def test_arc_ends_on_its_target_both_short_and_long_way_round(self):
        r1 = np.array([AU, 0.0])
        for angle_deg, tof_days in ((100.0, 150.0), (250.0, 400.0), (179.9, 260.0)):
            angle = math.radians(angle_deg)
            r2 = 1.4 * AU * np.array([math.cos(angle), math.sin(angle)])
            v1, _ = lambert_planar(r1, r2, tof_days * DAY, SUN_MU)
            np.testing.assert_allclose(coast(r1, v1, tof_days * DAY), r2, rtol=0, atol=1e3)

    def test_grids_of_any_shape_solve_at_once(self):
        r1 = np.zeros((3, 4, 2)) + [AU, 0.0]
        r2 = np.zeros((3, 4, 2)) + [0.0, 1.5 * AU]
        tof = np.linspace(100, 300, 12).reshape(3, 4) * DAY
        v1, v2 = lambert_planar(r1, r2, tof, SUN_MU)
        self.assertEqual((3, 4, 2), v1.shape)
        self.assertTrue(np.isfinite(v1).all() and np.isfinite(v2).all())


class EphemerisAndBurnTests(unittest.TestCase):
    def test_positions_match_the_orbit_the_space_view_draws(self):
        mars = body("Mars")
        orbit = KeplerOrbit(SpaceObject("sun", mass=SUN_MASS), a=mars.a, e=mars.e, M0=mars.M0, varpi=mars.varpi)
        times = np.array([0.0, 3.3e8, 8.21e8, 1.29e9])
        positions, velocities = planar_state(mars, times)
        for t, position, velocity in zip(times, positions, velocities):
            drawn_position, drawn_velocity = orbit.state_at(t)
            np.testing.assert_allclose(position, drawn_position, rtol=0, atol=10.0)
            np.testing.assert_allclose(velocity, drawn_velocity, rtol=0, atol=1e-6)

    def test_hohmann_estimates(self):
        mars = hohmann_estimate(body("Earth"), body("Mars"))
        self.assertAlmostEqual(259, mars.tof / DAY, delta=1)
        self.assertAlmostEqual(44.3, math.degrees(mars.phase), delta=0.2)
        self.assertAlmostEqual(2.94, mars.v_inf_depart / 1e3, delta=0.01)
        self.assertAlmostEqual(2.65, mars.v_inf_arrive / 1e3, delta=0.01)
        self.assertAlmostEqual(780, mars.synodic_period / DAY, delta=1)
        venus = hohmann_estimate(body("Earth"), body("Venus"))
        self.assertAlmostEqual(-54.0, math.degrees(venus.phase), delta=0.3)

    def test_capture_into_a_loose_ellipse_is_far_cheaper_at_a_gas_giant(self):
        jupiter = body("Jupiter")
        r_p = jupiter.radius + 200e3
        self.assertAlmostEqual(17.87, float(capture_burn(5.64e3, jupiter.mu, r_p)) / 1e3, delta=0.01)
        loose = float(capture_burn(5.64e3, jupiter.mu, r_p, r_a=0.5 * jupiter.soi_radius))
        self.assertAlmostEqual(0.35, loose / 1e3, delta=0.01)
        earth = body("Earth")
        self.assertAlmostEqual(3.61, float(escape_burn(2.94e3, earth.mu, earth.radius + 200e3)) / 1e3, delta=0.01)


class WindowSearchTests(unittest.TestCase):
    def test_finds_the_real_mars_windows(self):
        windows = find_direct_windows(body("Earth"), body("Mars"), seconds("2026-01-01"), count=3)
        self.assertEqual(3, len(windows))
        first = windows[0]
        self.assertLess(days_between(first.leg.depart_t, "2026-10-29"), 5)
        self.assertAlmostEqual(312, first.leg.tof / DAY, delta=8)
        self.assertAlmostEqual(5.68, first.total_dv / 1e3, delta=0.05)
        self.assertAlmostEqual(first.escape_dv + first.capture_dv, first.total_dv)
        self.assertLess(first.loose_capture_dv, first.capture_dv)
        self.assertLess(days_between(windows[1].leg.depart_t, "2028-12-01"), 5)
        self.assertLess(days_between(windows[2].leg.depart_t, "2031-01-16"), 5)

    def test_a_passed_window_is_not_listed(self):
        windows = find_direct_windows(body("Earth"), body("Mars"), seconds("2026-11-20"), count=1)
        self.assertLess(days_between(windows[0].leg.depart_t, "2028-12-01"), 5)

    def test_inner_target_windows_come_once_per_synodic_period(self):
        earth, venus = body("Earth"), body("Venus")
        windows = find_direct_windows(earth, venus, seconds("2026-01-01"), count=3)
        self.assertLess(days_between(windows[0].leg.depart_t, "2026-07-30"), 5)
        synodic = hohmann_estimate(earth, venus).synodic_period
        for earlier, later in zip(windows, windows[1:]):
            self.assertAlmostEqual(1.0, (later.leg.depart_t - earlier.leg.depart_t) / synodic, delta=0.15)

    def test_bodies_must_share_a_parent(self):
        moon = TransferBody(id="moon", name="moon", a=3.844e8, e=0.05, M0=0.0, varpi=0.0, mu=4.9e12,
                            radius=1.737e6, parent_mu=G * 5.97219e24)
        with self.assertRaises(ValueError):
            find_direct_windows(body("Earth"), moon, 0.0)


def location(entity_id, class_key, **fields):
    return {"id": entity_id, "name": entity_id, "type": "location",
            "_dataset": "locations", "location_class": class_key, **fields}


def planet_entity(name, **fields):
    a, e, mean_anomaly, node, periapsis, mass, radius = ELEMENTS[name]
    return location(f"planet_{name.lower()}", "planet", name=name, system_role="orbital_body",
                    star_system=["system_test"], parent_body="star_test", semi_major_axis_m=a, eccentricity=e,
                    mean_anomaly_deg_at_epoch=mean_anomaly, longitude_of_ascending_node_deg=node,
                    argument_of_periapsis_deg=periapsis, mass_kg=mass, radius_m=radius, **fields)


def sol_like_world(*extra):
    entities = [
        location("system_test", "star_system"),
        location("star_test", "star", star_system=["system_test"], mass_kg=SUN_MASS),
        planet_entity("Earth"),
        planet_entity("Mars"),
        *extra,
    ]
    loader = SimpleNamespace(entities={entity["id"]: entity for entity in entities}, entity_aliases={})
    return SimpleNamespace(loader=loader, get_entity=lambda key: loader.entities.get(key),
                           get_entities_by_dataset=lambda dataset: list(loader.entities.values()))


class SpaceViewTransferPanelTests(unittest.TestCase):
    def setUp(self):
        self.moon = location("moon_test", "moon", name="Moon", system_role="orbital_body", star_system=["system_test"],
                             parent_body="planet_earth", semi_major_axis_m=3.844e8, eccentricity=0.055,
                             mass_kg=7.342e22, radius_m=1.7374e6)
        self.simulation = SpaceSimulation(sol_like_world(planet_entity("Venus"), self.moon),
                                          root_system_id="system_test", year=2026)

    def select(self, entity_id):
        self.simulation.selected_space_object = self.simulation.system.objects_by_id[entity_id]

    def test_selecting_a_body_lists_the_next_window_to_each_sibling_soonest_first(self):
        self.select("planet_earth")
        first_frame = self.simulation.get_transfer_panel_lines()
        self.assertEqual("Transfer windows from Earth", first_frame[0])
        self.assertIn("Calculating 1 more...", first_frame)
        self.assertEqual([
            "Transfer windows from Earth",
            "Deep-space shielding; life support for the flight",
            "2026.575  Venus  6.85 km/s, 397 cycles | no craft",
            "2026.824  Mars  5.68 km/s, 853 cycles | no craft",
            "Checked: all spacecraft designs, 0 craft",
        ], self.simulation.get_transfer_panel_lines())
        # the windows stay off the selection card
        payload = self.simulation.get_selection_inspector_payload()
        self.assertFalse(any("2026." in line for line in payload["details"]))
        self.assertEqual(["open_selection_wiki"], [action["id"] for action in payload["actions"]])

    def test_rows_move_on_once_the_view_passes_their_departure(self):
        self.select("planet_earth")
        self.simulation.get_transfer_panel_lines(solve_budget=2)
        self.simulation.sim_clock.time = seconds("2026-12-01") - self.simulation.start_seconds
        lines = self.simulation.get_transfer_panel_lines(solve_budget=2)
        self.assertTrue(lines[2].startswith("2028.175  Venus"))
        self.assertTrue(lines[3].startswith("2028.916  Mars"))

    def test_rows_count_the_craft_that_meet_each_window_and_name_them(self):
        from tools.create_test_craft_pathfinder import build_transaction

        untyped = {"id": "veh_untyped_craft", "type": "vehicle", "name": "Untyped Craft",
                   "vehicle_class": "system_spacecraft", "installed_components": []}
        world = sol_like_world(planet_entity("Venus"), planet_entity("Jupiter"), *build_transaction(), untyped)
        self.simulation = SpaceSimulation(world, root_system_id="system_test", year=2026)
        self.select("planet_earth")
        lines = self.simulation.get_transfer_panel_lines(solve_budget=3)
        self.assertIn("2026.575  Venus  6.85 km/s, 397 cycles | 1 craft", lines)
        self.assertIn("2026.824  Mars  5.68 km/s, 853 cycles | 1 craft", lines)
        self.assertIn("2026.812  Jupiter  24.21 km/s, 3.0 years | no craft", lines)
        self.assertEqual([
            "Checked: all spacecraft designs, 2 craft",
            "Pathfinder Test Craft: Venus, Mars",
            "1 spacecraft design lacks figures",
        ], lines[-3:])

    def test_the_debug_collection_supplies_the_craft_it_checks(self):
        from tools.author_collection_membership import debug_collection
        from tools.create_test_craft_fleet import build_transaction as fleet
        from tools.create_test_craft_pathfinder import build_transaction as pathfinder

        untagged = {"id": "veh_untagged_craft", "_dataset": "vehicles", "type": "vehicle", "name": "Untagged Craft",
                    "vehicle_class": "system_spacecraft", "installed_components": []}
        world = sol_like_world(planet_entity("Venus"), planet_entity("Jupiter"), *pathfinder(), *fleet(),
                               untagged, debug_collection())
        self.simulation = SpaceSimulation(world, root_system_id="system_test", year=2026)
        self.select("planet_earth")
        lines = self.simulation.get_transfer_panel_lines(solve_budget=3)
        # Shuttler has the delta-v for Venus and Mars but only orbital shielding
        self.assertIn("2026.575  Venus  6.85 km/s, 397 cycles | 2 craft", lines)
        self.assertIn("2026.824  Mars  5.68 km/s, 853 cycles | 2 craft", lines)
        self.assertIn("2026.812  Jupiter  24.21 km/s, 3.0 years | no craft", lines)
        self.assertIn("Checked: Debug Test Spacecraft, 3 craft", lines)
        self.assertIn("Pathfinder Test Craft: Venus, Mars", lines)
        self.assertIn("Longreach Test Craft: Venus, Mars", lines)
        self.assertFalse(any("Shuttler" in line or "lack" in line for line in lines))

    def test_moon_to_moon_windows_ask_for_orbital_shielding(self):
        second_moon = location("moon_second", "moon", name="Second Moon", system_role="orbital_body",
                               star_system=["system_test"], parent_body="planet_earth", semi_major_axis_m=6.0e8,
                               eccentricity=0.01, mass_kg=1.0e22, radius_m=1.0e6)
        self.simulation = SpaceSimulation(sol_like_world(self.moon, second_moon), root_system_id="system_test", year=2026)
        self.select("moon_test")
        lines = self.simulation.get_transfer_panel_lines()
        self.assertEqual("Orbital shielding; life support for the flight", lines[1])
        self.assertTrue(lines[2].split("  ")[1] == "Second Moon")

    def test_flights_of_a_year_or_more_read_in_years(self):
        jupiter = planet_entity("Jupiter")
        self.simulation = SpaceSimulation(sol_like_world(jupiter), root_system_id="system_test", year=2026)
        self.select("planet_earth")
        lines = self.simulation.get_transfer_panel_lines(solve_budget=2)
        self.assertTrue(any(line.startswith("2026.812  Jupiter  24.21 km/s, 3.0 years") for line in lines))

    def test_choosing_a_window_and_a_craft_flies_a_journey(self):
        from tools.author_collection_membership import debug_collection
        from tools.create_test_craft_pathfinder import build_transaction as pathfinder

        world = sol_like_world(*pathfinder(), debug_collection())
        simulation = SpaceSimulation(world, root_system_id="system_test", year=2026)
        simulation.selected_space_object = simulation.system.objects_by_id["planet_earth"]
        entries = simulation.get_transfer_panel_entries(solve_budget=3)
        mars_row = next(entry for entry in entries if "  Mars  " in entry["text"])
        self.assertEqual({"action": "select_window", "target_id": "planet_mars"}, mars_row["action"])

        self.assertTrue(simulation.handle_panel_action(mars_row["action"]))
        entries = simulation.get_transfer_panel_entries()
        self.assertTrue(next(entry for entry in entries if "  Mars  " in entry["text"])["selected"])
        start = next(entry for entry in entries if entry["text"] == "Start journey with Pathfinder Test Craft")
        self.assertIn("Fly to Mars, departs 2026.824:", [entry["text"] for entry in entries])

        simulation.handle_panel_action(start["action"])
        journey = simulation.journey
        self.assertEqual(("Pathfinder Test Craft", "Earth", "Mars"), (journey.craft_name, journey.origin_name, journey.target_name))
        lines = [entry["text"] for entry in simulation.get_journey_panel_entries()]
        self.assertEqual("Journey: Pathfinder Test Craft", lines[0])
        self.assertTrue(lines[1].startswith("Earth to Mars: planned capture 2027."))
        self.assertTrue(lines[2].startswith("In orbit around Earth: next burn in "))
        self.assertEqual("Mars: captured, periapsis 200 km up", lines[3])
        self.assertTrue(lines[4].startswith("Delta-v 5.6") and lines[4].endswith(" of 7.78 km/s"))
        self.assertTrue(lines[5].startswith("Propellant 300.0 t to "))
        self.assertTrue(lines[6].startswith("Node 1 2026.82") and lines[6].endswith("radial +0 m/s"))
        self.assertIn("Jump to burn", lines[-1])
        # parked 200 km above Earth until the burn, with markers on both nodes
        earth = np.array(simulation.system.objects_by_id["planet_earth"].get_position())
        drawn = simulation.get_journey_draw_data()
        self.assertAlmostEqual(6_571_000.0, np.linalg.norm(np.array(drawn["position"]) - earth), delta=1e3)
        self.assertEqual(["1", "2"], [node["label"] for node in drawn["nodes"]])

        # a node is edited from the panel: select it, nudge it, and the outcome changes
        simulation.handle_panel_action({"action": "select_node", "index": 0})
        entries = simulation.get_journey_panel_entries()
        prograde = next(entry for entry in entries if entry.get("label") == "Prograde m/s")
        minus_ten = next(payload for caption, payload in prograde["buttons"] if caption == "-10")
        simulation.handle_panel_action(minus_ten)
        simulation.handle_panel_action(minus_ten)
        self.assertAlmostEqual(journey.nodes[0].prograde - 20.0, simulation.journey.nodes[0].prograde)
        self.assertTrue(simulation.get_journey_panel_entries()[3]["text"].startswith("Mars: missed by "))
        simulation.handle_panel_action({"action": "delete_node", "index": 1})
        self.assertEqual(1, len(simulation.journey.nodes))
        simulation.handle_panel_action({"action": "add_node"})
        self.assertEqual(2, len(simulation.journey.nodes))
        self.assertEqual(1, simulation.selected_node)

        simulation.journey = journey
        simulation.handle_panel_action({"action": "jump_to_departure"})
        self.assertAlmostEqual(journey.depart_t - 0.5 * 31_557.6, simulation.seconds_since_epoch(), delta=1.0)
        simulation.handle_panel_action({"action": "warp_faster"})
        self.assertEqual(10.0, simulation.sim_clock.time_scale)

        middle = 0.5 * (journey.exit_t + journey.entry_t) - simulation.seconds_since_epoch()
        simulation.sim_clock.time += middle
        simulation.system.update(middle)
        self.assertTrue(simulation.get_journey_panel_entries()[2]["text"].startswith("Cruising around star_test"))
        drawn = simulation.get_journey_draw_data()
        np.testing.assert_allclose(drawn["position"], journey.position(simulation.seconds_since_epoch()), atol=1.0)
        self.assertEqual(["orbit", "hyperbola", "cruise", "hyperbola", "orbit"], [kind for kind, _points in drawn["segments"]])

        simulation.handle_panel_action({"action": "follow_craft"})
        self.assertEqual(drawn["position"], simulation.get_camera_focus())
        simulation.handle_panel_action({"action": "end_journey"})
        self.assertIsNone(simulation.journey)
        self.assertIsNone(simulation.get_camera_focus())
        self.assertEqual([], simulation.get_journey_panel_entries())

    def test_a_long_destination_list_wraps_instead_of_being_cut(self):
        names = ["Ceres", "Mercury", "Mars", "Vesta", "Venus", "Pallas", "Hygiea"]
        lines = SpaceSimulation._wrapped_list("Longreach Test Craft: ", names)
        self.assertEqual([
            "Longreach Test Craft: Ceres, Mercury, Mars, Vesta,",
            "  Venus, Pallas, Hygiea",
        ], lines)
        self.assertTrue(all(len(line) <= 56 for line in lines))
        self.assertEqual(["Pathfinder Test Craft: Mars, Venus"],
                         SpaceSimulation._wrapped_list("Pathfinder Test Craft: ", ["Mars", "Venus"]))

    def test_bodies_without_siblings_have_no_panel(self):
        self.select("moon_test")
        self.assertEqual([], self.simulation.get_transfer_panel_lines())
        self.select("star_test")
        self.assertEqual([], self.simulation.get_transfer_panel_lines())

    def test_releasing_a_card_button_click_keeps_the_selection(self):
        import pygame

        self.select("planet_earth")
        release = pygame.event.Event(pygame.MOUSEBUTTONUP, pos=(30, 520), button=1)
        self.simulation.handle_pointer_event(release, camera=None, screen_pos=(30, 520))
        self.assertEqual("planet_earth", self.simulation._source_entity_id(self.simulation.selected_space_object))


class SpaceViewBridgeTests(unittest.TestCase):
    def test_bodies_built_from_the_space_view_sit_where_the_view_draws_them(self):
        a, e, mean_anomaly, node, periapsis, mass, radius = ELEMENTS["Mars"]
        simulation = SpaceSimulation(sol_like_world(), root_system_id="system_test", year=2026)
        obj = simulation.system.objects_by_id["planet_mars"]

        mars = TransferBody.from_space_object(obj, simulation.system.get_source_entity_for_space_object(obj))
        self.assertEqual(radius, mars.radius)
        self.assertAlmostEqual(G * mass, mars.mu)
        position, _ = planar_state(mars, simulation.seconds_since_epoch())
        np.testing.assert_allclose(position, obj.get_position(), rtol=0, atol=10.0)


if __name__ == "__main__":
    unittest.main()
