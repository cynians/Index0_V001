"""
Embedded runtime simulation for one individual, corporal vehicle.

Architectural role: this mirrors what PersonSimulation is to an individual
person. SiteSimulation ticks one VehicleSimulation per active logistics
delivery, using the same position/presence-payload shape that person agents
already use, so vehicle presences flow through the existing site renderer and
payload plumbing untouched.

This is intentionally thin for the current placeholder slice -- no needs,
personality, or knowledge, just position, cargo, and a small state machine.
A vehicle design entity (see simulations/vehicle/vehicle_design_simulation.py)
describes the type; this class represents one concrete, moving instance of
that type for the duration of a delivery. It is not currently promoted to a
durable ontology entity -- see docs/CLAUDE_CODE_HANDOFF_2026-08-14.md and the
concept doc (search "activity_periods") for why aggregate logistics trips are
allowed to stay ephemeral runtime state until they gain independent
importance.

Second role -- the operative core of the vehicle sub-simulation pattern:
``route_waypoints``/``cargo`` are optional so a domain-specific realization
(e.g. simulations/vehicle/aircraft_flight_simulation.py::AircraftFlightSimulation,
which owns Map-mode flight state and physics on top) can hold a
VehicleSimulation purely for its component/capability bookkeeping via
``derive_capabilities()``, without a ground route. Ground logistics carts
(SiteSimulation) are unaffected -- they always pass real waypoints/cargo.
"""

import math

from simulations.vehicle.vehicle_design import VehicleDesignController

EARTH_SURFACE_GRAVITY_M_S2 = 9.80665
# Representative modern turbojet/turbofan static thrust-to-weight ratio, used
# as a stand-in for a precise thrust rating since catalog components declare
# a qualitative "thrust" output port (see vehicle_design.py's port model) but
# not a thrust magnitude -- mass_kg is the one authored number every engine
# entry reliably carries.
JET_ENGINE_THRUST_TO_WEIGHT_RATIO = 6.0


class VehicleSimulation:
    STATE_ENROUTE_INBOUND = "enroute_inbound"
    STATE_ARRIVED = "arrived"
    STATE_UNLOADING = "unloading"
    STATE_DEPARTING = "departing"
    STATE_DONE = "done"

    DEPARTURE_GRACE_SECONDS = 1.5

    def __init__(
        self,
        world_model,
        vehicle_entity_id,
        *,
        route_waypoints=None,
        cargo=None,
        design_entity_id=None,
        label=None,
        move_speed_m_per_second=2.5,
        arrival_radius_m=0.5,
    ):
        self.world_model = world_model
        self.vehicle_entity_id = vehicle_entity_id
        self.design_entity_id = design_entity_id
        self.route_waypoints = [list(point) for point in route_waypoints] if route_waypoints else [[0.0, 0.0]]
        self.position = list(self.route_waypoints[0])
        self._waypoint_index = 0
        self.cargo = dict(cargo or {})
        self.initial_cargo_total = self._cargo_total()
        self.label = label or vehicle_entity_id
        self.move_speed_m_per_second = float(move_speed_m_per_second)
        self.arrival_radius_m = float(arrival_radius_m)
        self.state = self.STATE_ENROUTE_INBOUND
        self._departure_timer = 0.0
        # Set by whoever assigns a worker to unload this vehicle (see
        # SiteSimulation._handle_vehicle_arrival) -- each PersonSimulation
        # agent owns its own independent test_points dict, so the vehicle
        # must remember exactly which agent's copy holds the authoritative
        # remaining_quantity for this delivery.
        self.assigned_worker_id = None

    def _cargo_total(self):
        return sum(max(0, int(quantity or 0)) for quantity in self.cargo.values())

    def is_empty(self):
        return self._cargo_total() <= 0

    def _advance_along_route(self, dt):
        """Move toward the current waypoint; return True once the final one is reached."""
        target = self.route_waypoints[self._waypoint_index]
        dx = target[0] - self.position[0]
        dy = target[1] - self.position[1]
        distance = math.hypot(dx, dy)
        at_final_waypoint = self._waypoint_index == len(self.route_waypoints) - 1

        if distance <= self.arrival_radius_m:
            self.position[:] = [target[0], target[1]]
            if not at_final_waypoint:
                self._waypoint_index += 1
                return False
            return True

        travel = self.move_speed_m_per_second * dt
        if travel >= distance:
            self.position[:] = [target[0], target[1]]
        else:
            self.position[0] += dx / distance * travel
            self.position[1] += dy / distance * travel
        return False

    def begin_unloading(self):
        if self.state == self.STATE_ARRIVED:
            self.state = self.STATE_UNLOADING

    def _update_runtime(self, dt):
        if self.state == self.STATE_ENROUTE_INBOUND:
            if self._advance_along_route(dt):
                self.state = self.STATE_ARRIVED
            return

        if self.state == self.STATE_ARRIVED:
            # Waiting for the owning SiteSimulation to assign an unload task
            # to a worker; begin_unloading() flips this to STATE_UNLOADING.
            return

        if self.state == self.STATE_UNLOADING:
            if self.is_empty():
                self.state = self.STATE_DEPARTING
            return

        if self.state == self.STATE_DEPARTING:
            self._departure_timer += dt
            if self._departure_timer >= self.DEPARTURE_GRACE_SECONDS:
                self.state = self.STATE_DONE
            return

    def get_presence_payload(self):
        remaining = self._cargo_total()
        purpose = (
            f"logistics delivery ({remaining} units remaining)"
            if remaining
            else "unloaded, departing"
        )
        return {
            "id": self.vehicle_entity_id,
            "label": self.label,
            "position": tuple(self.position),
            "presence_kind": "vehicle",
            "simulation_detail": "full",
            "source_pop": None,
            "purpose": purpose,
            "ontology_status": "runtime logistics projection",
            "count": None,
            "entity": {
                "id": self.vehicle_entity_id,
                "type": "vehicle",
                "name": self.label,
                "pretty_name": self.label,
                "vehicle_class": "logistics cart",
                "design_entity_id": self.design_entity_id,
            },
        }

    def derive_capabilities(self):
        """
        Domain-tagged capability summary derived from the vehicle design's
        installed components/ports (see VehicleDesignController), reusable by
        any realization -- ground, air, or (in the future) space/combat --
        that needs to know what this vehicle instance's build can actually do.

        ``thrust_n`` is a mass-based proxy (see JET_ENGINE_THRUST_TO_WEIGHT_RATIO)
        rather than a directly-authored figure, since catalog ports declare a
        qualitative resource type, not a magnitude. Thrust only counts from
        components whose required inputs are fully wired (e.g. an engine with
        no fuel tank contributes nothing).
        """
        empty = {"thrust_n": 0.0, "lift_area_m2": 0.0, "mass_kg": 0.0, "fully_wired": True}
        design_entity_id = self.design_entity_id or self.vehicle_entity_id
        if not design_entity_id or self.world_model is None or not hasattr(self.world_model, "get_entity"):
            return empty
        entity = self.world_model.get_entity(design_entity_id)
        if not isinstance(entity, dict):
            return empty

        design = VehicleDesignController(world_model=self.world_model, vehicle_entity=entity)
        wiring_status = design.get_component_wiring_status()
        thrust_n = 0.0
        lift_area_m2 = 0.0
        mass_kg = 0.0
        fully_wired = True

        for component in design.get_placed_components():
            catalog_id = component.get("catalog_id")
            if not catalog_id:
                continue
            catalog_entry = design.get_component_catalog_entry(catalog_id)
            if catalog_entry is None:
                continue
            component_mass_kg = float(catalog_entry.get("mass_kg", 0.0) or 0.0)
            mass_kg += component_mass_kg
            resource_types = {port.get("resource_type") for port in catalog_entry.get("outputs", [])}
            instance_id = component.get("instance_id")
            wired = wiring_status.get(instance_id, {"fully_wired": True})["fully_wired"]
            fully_wired = fully_wired and wired

            if "thrust" in resource_types and wired:
                thrust_n += component_mass_kg * EARTH_SURFACE_GRAVITY_M_S2 * JET_ENGINE_THRUST_TO_WEIGHT_RATIO
            if "lift" in resource_types:
                dimensions = catalog_entry.get("dimensions_m") or {}
                lift_area_m2 += float(dimensions.get("x", 0.0) or 0.0) * float(dimensions.get("y", 0.0) or 0.0)

        if lift_area_m2 <= 0.0 and any(
            "flight_surfaces" in (feature.get("satisfies_categories") or [])
            for feature in (entity.get("structural_features") or [])
            if isinstance(feature, dict)
        ):
            # Some airframes model wings as an integral structural feature
            # rather than an installable component (no size of its own to
            # sum) -- fall back to a typical wing-area-to-planform ratio for
            # a fixed-wing aircraft over the vehicle's own footprint.
            length_m = float(entity.get("dimension_length_m", 0.0) or 0.0)
            width_m = float(entity.get("dimension_width_m", 0.0) or 0.0)
            lift_area_m2 = length_m * width_m * 0.2

        return {
            "thrust_n": thrust_n,
            "lift_area_m2": lift_area_m2,
            "mass_kg": mass_kg,
            "fully_wired": fully_wired,
        }
