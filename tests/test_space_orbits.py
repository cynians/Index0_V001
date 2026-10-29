import math
import unittest
from datetime import datetime
from types import SimpleNamespace

from simulations.space.object import SpaceObject
from simulations.space.orbit import KeplerOrbit
from simulations.space.space_simulation import SpaceSimulation
from world.interplanetary_calendar import (
    YEAR_SECONDS,
    date_from_seconds,
    seconds_from_date,
    year_start_seconds,
)

SUN_MASS = 1.98847e30
AU = 149_597_870_700.0


def location(entity_id, class_key, **fields):
    return {"id": entity_id, "name": entity_id, "type": "location",
            "_dataset": "locations", "location_class": class_key, **fields}


def world_with(*entities):
    loader = SimpleNamespace(entities={entity["id"]: entity for entity in entities}, entity_aliases={})
    return SimpleNamespace(loader=loader, get_entity=lambda key: loader.entities.get(key),
                           get_entities_by_dataset=lambda dataset: list(loader.entities.values()))


def sun_orbit(e=0.2, varpi_deg=120.0, M0=0.0):
    sun = SpaceObject("sun", mass=SUN_MASS)
    return KeplerOrbit(sun, a=AU, e=e, M0=M0, varpi=math.radians(varpi_deg))


class InterplanetaryCalendarTests(unittest.TestCase):
    def test_epoch_is_year_2000_month_1_cycle_1(self):
        date = date_from_seconds(0.0)
        self.assertEqual((2000, 1, 1), (date.year, date.month, date.cycle))
        self.assertEqual("2000.000", date.short_label())

    def test_short_form_is_passed_thousandths_and_long_form_counts_from_one(self):
        seconds = (datetime(2026, 10, 30) - datetime(2000, 1, 1, 12)).total_seconds()
        date = date_from_seconds(seconds)
        self.assertEqual("2026.826", date.short_label())
        self.assertEqual("Year 2026, Month 9, Cycle 27", date.long_label())

    def test_dates_round_trip_through_seconds(self):
        for year, month, cycle in ((2000, 1, 1), (2026, 9, 27), (2400, 10, 100), (1999, 5, 50), (31_000, 3, 1)):
            date = date_from_seconds(seconds_from_date(year, month, cycle))
            self.assertEqual((year, month, cycle), (date.year, date.month, date.cycle))

    def test_last_cycle_of_a_year_and_the_year_before_the_epoch(self):
        date = date_from_seconds(seconds_from_date(2027) - 1.0)
        self.assertEqual((2026, 10, 100), (date.year, date.month, date.cycle))
        date = date_from_seconds(-1.0)
        self.assertEqual((1999, 10, 100), (date.year, date.month, date.cycle))
        self.assertEqual(26 * YEAR_SECONDS, year_start_seconds(2026))


class KeplerOrbitTests(unittest.TestCase):
    def test_periapsis_lies_along_the_periapsis_longitude(self):
        orbit = sun_orbit(e=0.2, varpi_deg=120.0)
        (x, y), (vx, vy) = orbit.state_at(0.0)
        self.assertAlmostEqual(120.0, math.degrees(math.atan2(y, x)), places=6)
        self.assertAlmostEqual(AU * 0.8, math.hypot(x, y), delta=1.0)
        # at periapsis the velocity is perpendicular, counter-clockwise, at the vis-viva speed
        self.assertAlmostEqual(0.0, (x * vx + y * vy) / (math.hypot(x, y) * math.hypot(vx, vy)), places=9)
        self.assertGreater(x * vy - y * vx, 0.0)
        r = math.hypot(x, y)
        self.assertAlmostEqual(math.sqrt(orbit.mu * (2.0 / r - 1.0 / AU)), math.hypot(vx, vy), delta=1e-3)

    def test_velocity_matches_the_change_in_position(self):
        orbit = sun_orbit(e=0.3, varpi_deg=40.0, M0=1.1)
        t, h = 9.0e6, 30.0
        (x0, y0), _ = orbit.state_at(t - h)
        (x1, y1), _ = orbit.state_at(t + h)
        _, (vx, vy) = orbit.state_at(t)
        self.assertAlmostEqual(vx, (x1 - x0) / (2 * h), delta=abs(vx) * 1e-6 + 1e-6)
        self.assertAlmostEqual(vy, (y1 - y0) / (2 * h), delta=abs(vy) * 1e-6 + 1e-6)

    def test_position_comes_from_absolute_time_not_accumulated_steps(self):
        stepped = sun_orbit(M0=0.5)
        for _ in range(1000):
            stepped.update(3600.0 * 7)
        direct = sun_orbit(M0=0.5)
        direct.set_time(1000 * 3600.0 * 7)
        self.assertEqual(stepped.M, direct.M)
        self.assertEqual(stepped.get_position(), direct.get_position())
        self.assertAlmostEqual((0.5 + direct.n * direct.t) % math.tau, direct.M, places=12)

    def test_drawn_path_starts_at_periapsis(self):
        orbit = sun_orbit(e=0.2, varpi_deg=300.0)
        (x, y), _ = orbit.state_at(0.0)
        px, py = orbit.get_path_points(120)[0]
        self.assertAlmostEqual(x, px, delta=1.0)
        self.assertAlmostEqual(y, py, delta=1.0)


class SpaceSimulationCalendarTests(unittest.TestCase):
    def world(self):
        return world_with(
            location("system_test", "star_system"),
            location("star_test", "star", star_system=["system_test"], mass_kg=SUN_MASS),
            location("planet_test", "planet", system_role="orbital_body", star_system=["system_test"],
                     parent_body="star_test", semi_major_axis_m=AU, eccentricity=0.1,
                     mean_anomaly_deg_at_epoch=0.0, longitude_of_ascending_node_deg=-10.0,
                     argument_of_periapsis_deg=70.0),
        )

    def planet(self, simulation):
        return simulation.system.objects_by_id["planet_test"]

    def test_bodies_open_where_they_are_on_the_date(self):
        at_epoch = SpaceSimulation(self.world(), root_system_id="system_test", year=2000)
        x, y = self.planet(at_epoch).get_position()
        self.assertAlmostEqual(60.0, math.degrees(math.atan2(y, x)), places=6)
        self.assertAlmostEqual(0.9 * AU, math.hypot(x, y), delta=1.0)

        later = SpaceSimulation(self.world(), root_system_id="system_test", year=2026)
        orbit = self.planet(later).orbit
        self.assertEqual(year_start_seconds(2026), orbit.t)
        self.assertNotAlmostEqual(x, self.planet(later).get_position()[0], delta=1e6)

    def test_header_shows_the_interplanetary_date(self):
        simulation = SpaceSimulation(self.world(), root_system_id="system_test", year=2026)
        simulation.sim_clock.time = seconds_from_date(2026, 9, 27) - year_start_seconds(2026)
        info = simulation.get_time_info()
        self.assertEqual("Year 2026, Month 9, Cycle 27", info["lines"][0])
        self.assertTrue(info["lines"][1].startswith("2026.826 | Tick "))
        self.assertAlmostEqual(0.826, info["year_fraction"], places=6)
        # the bar runs through Month 9: 26 of its 100 cycles have passed
        self.assertAlmostEqual(0.26, info["timeline_fraction"], places=6)
        self.assertEqual(["0", "25", "50", "75", "100"], info["timeline_labels"])


if __name__ == "__main__":
    unittest.main()
