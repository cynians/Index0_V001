import unittest
from types import SimpleNamespace

from simulations.vehicle.aircraft_flight_simulation import AircraftFlightSimulation
from simulations.vehicle.vehicle_simulation import VehicleSimulation
from simulations.map.map_simulation import MapSimulation
from world.simulation_context import SimulationContext


JET_ENGINE_CATALOG_ENTRY = {
    "id": "jet_engine", "label": "Engine", "component_type": "jet_engine_component", "entry_type": "component",
    "dimensions_m": {"x": 4.6, "y": 1.0, "z": 1.0}, "mass_kg": 1000.0, "power_kw": 0.0,
    "satisfies_categories": ["propulsion_air", "powertrain"],
    "operational_groups": ["Powertrain"], "subsystem_labels": ["turbojet"],
}
FUEL_TANK_CATALOG_ENTRY = {
    "id": "fuel_tank", "label": "Fuel Tank", "component_type": "fuel_tank_component", "entry_type": "component",
    "dimensions_m": {"x": 3.0, "y": 0.9, "z": 0.8}, "mass_kg": 500.0, "power_kw": 0.0,
    "satisfies_categories": ["fuel_storage"], "operational_groups": ["Powertrain"], "subsystem_labels": ["fuel"],
}


def _aircraft_entity(with_fuel_tank=True):
    installed = [
        {
            "instance_id": "slot_engine", "catalog_id": "jet_engine", "label": "Engine",
            "component_type": "jet_engine_component", "satisfies_categories": ["propulsion_air", "powertrain"],
            "operational_groups": ["Powertrain"], "subsystem_labels": ["turbojet"],
            "local_rect_m": {"x": 1.0, "y": 1.0, "width": 4.6, "height": 1.0},
        },
    ]
    if with_fuel_tank:
        installed.append({
            "instance_id": "slot_fuel", "catalog_id": "fuel_tank", "label": "Fuel Tank",
            "component_type": "fuel_tank_component", "satisfies_categories": ["fuel_storage"],
            "operational_groups": ["Powertrain"], "subsystem_labels": ["fuel"],
            "local_rect_m": {"x": 6.0, "y": 1.0, "width": 3.0, "height": 0.9},
        })
    return {
        "id": "veh_test_aircraft", "type": "vehicle", "_dataset": "vehicles", "vehicle_class": "aircraft",
        "dimension_length_m": 14.0, "dimension_width_m": 8.0, "dimension_height_m": 4.0,
        "component_catalog": [JET_ENGINE_CATALOG_ENTRY, FUEL_TANK_CATALOG_ENTRY],
        "installed_components": installed,
        "structural_features": [
            {"id": "wing", "label": "Wing", "feature_type": "lifting_structure", "satisfies_categories": ["flight_surfaces"]},
        ],
    }


class _World:
    def __init__(self, entities):
        self.entities = {entity["id"]: entity for entity in entities}

    def get_entity(self, entity_id):
        return self.entities.get(entity_id)


class VehicleCapabilitiesTests(unittest.TestCase):
    def test_fully_wired_aircraft_reports_thrust_lift_and_mass(self):
        world = _World([_aircraft_entity(with_fuel_tank=True)])
        vehicle = VehicleSimulation(world, "instance_1", design_entity_id="veh_test_aircraft")
        capabilities = vehicle.derive_capabilities()
        self.assertTrue(capabilities["fully_wired"])
        self.assertGreater(capabilities["thrust_n"], 0.0)
        self.assertAlmostEqual(1500.0, capabilities["mass_kg"])
        self.assertAlmostEqual(14.0 * 8.0 * 0.2, capabilities["lift_area_m2"])

    def test_engine_without_fuel_tank_contributes_no_thrust(self):
        world = _World([_aircraft_entity(with_fuel_tank=False)])
        vehicle = VehicleSimulation(world, "instance_1", design_entity_id="veh_test_aircraft")
        capabilities = vehicle.derive_capabilities()
        self.assertFalse(capabilities["fully_wired"])
        self.assertEqual(0.0, capabilities["thrust_n"])

    def test_missing_design_entity_returns_empty_capabilities(self):
        vehicle = VehicleSimulation(_World([]), "instance_1", design_entity_id="missing")
        self.assertEqual(
            {"thrust_n": 0.0, "lift_area_m2": 0.0, "mass_kg": 0.0, "fully_wired": True},
            vehicle.derive_capabilities(),
        )

    def test_route_waypoints_and_cargo_are_optional(self):
        vehicle = VehicleSimulation(_World([]), "instance_1")
        self.assertEqual([0.0, 0.0], vehicle.position)
        self.assertEqual({}, vehicle.cargo)


class AircraftFlightSimulationTests(unittest.TestCase):
    def _plane(self, with_fuel_tank=True, **kwargs):
        world = _World([_aircraft_entity(with_fuel_tank=with_fuel_tank)])
        params = {"lon_deg": 0.0, "lat_deg": 0.0, "altitude_m": 1000.0, "heading_deg": 0.0}
        params.update(kwargs)
        return AircraftFlightSimulation(
            world, "instance_1", design_entity_id="veh_test_aircraft", **params,
        )

    def test_throttle_and_thrust_accelerate_the_aircraft(self):
        plane = self._plane()
        plane.set_throttle(1.0)
        for _ in range(20):
            plane.tick(1.0)
        self.assertGreater(plane.airspeed_m_s, 0.0)

    def test_unwired_engine_never_builds_airspeed(self):
        plane = self._plane(with_fuel_tank=False)
        plane.set_throttle(1.0)
        for _ in range(20):
            plane.tick(1.0)
        self.assertEqual(0.0, plane.airspeed_m_s)

    def test_positive_yaw_turns_heading_clockwise(self):
        plane = self._plane()
        plane.set_throttle(1.0)
        for _ in range(10):
            plane.tick(1.0)  # build airspeed so the turn rate isn't clamped to ~0
        heading_before = plane.heading_deg
        plane.tick(1.0, controls={"yaw_input": 1.0})
        self.assertNotEqual(heading_before, plane.heading_deg)

    def test_moving_north_increases_latitude(self):
        plane = self._plane(altitude_m=2000.0)
        plane.airspeed_m_s = 200.0  # already at cruise speed, heading 0 = north
        plane.tick(5.0)
        self.assertGreater(plane.lat_deg, 0.0)
        self.assertAlmostEqual(0.0, plane.lon_deg, places=6)

    def test_air_density_falls_back_when_altitude_exceeds_last_band(self):
        plane = self._plane(altitude_m=10_000_000.0)
        density = plane._air_density_at_altitude({
            "bands": [{"base_altitude_km": 0.0, "top_altitude_km": 10.0, "density_kg_m3": 1.0}],
        })
        self.assertEqual(0.0, density)

    def test_presence_payload_reports_piloting_relevant_fields(self):
        plane = self._plane()
        payload = plane.get_presence_payload()
        for key in ("lon_deg", "lat_deg", "altitude_m", "heading_deg", "airspeed_m_s", "throttle_fraction", "capabilities"):
            self.assertIn(key, payload)


class MapSimulationAircraftTests(unittest.TestCase):
    def _map_sim(self):
        earth = {"id": "earth", "name": "Earth", "type": "location", "_dataset": "locations", "location_class": "planet"}
        world = _World([earth, _aircraft_entity()])
        return MapSimulation(SimulationContext(2400, "earth", world))

    def test_spawn_enter_exit_cockpit_and_camera_takeover(self):
        sim = self._map_sim()
        sim.spawn_aircraft("veh_instance_1", design_entity_id="veh_test_aircraft", lon_deg=5.0, lat_deg=5.0)
        self.assertIn("veh_instance_1", sim.live_aircraft)
        self.assertFalse(sim.consumes_camera_update())

        self.assertTrue(sim.enter_aircraft_cockpit("veh_instance_1"))
        self.assertTrue(sim.consumes_camera_update())

        presence = sim.get_live_aircraft_presence()
        self.assertEqual(1, len(presence))
        self.assertTrue(presence[0]["piloted"])

        self.assertTrue(sim.exit_aircraft_cockpit())
        self.assertFalse(sim.consumes_camera_update())

    def test_entering_cockpit_for_unknown_aircraft_fails(self):
        sim = self._map_sim()
        self.assertFalse(sim.enter_aircraft_cockpit("does_not_exist"))

    def test_update_ticks_live_aircraft(self):
        sim = self._map_sim()
        sim.spawn_aircraft("veh_instance_1", design_entity_id="veh_test_aircraft")
        sim.live_aircraft["veh_instance_1"].set_throttle(1.0)
        sim.update(2.0)
        self.assertGreater(sim.live_aircraft["veh_instance_1"].airspeed_m_s, 0.0)

    def test_despawn_removes_aircraft_and_clears_piloting(self):
        sim = self._map_sim()
        sim.spawn_aircraft("veh_instance_1", design_entity_id="veh_test_aircraft")
        sim.enter_aircraft_cockpit("veh_instance_1")
        self.assertTrue(sim.despawn_aircraft("veh_instance_1"))
        self.assertNotIn("veh_instance_1", sim.live_aircraft)
        self.assertIsNone(sim.piloted_aircraft_id)


if __name__ == "__main__":
    unittest.main()
