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
"""

import math


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
        route_waypoints,
        cargo,
        design_entity_id=None,
        label=None,
        move_speed_m_per_second=2.5,
        arrival_radius_m=0.5,
    ):
        self.world_model = world_model
        self.vehicle_entity_id = vehicle_entity_id
        self.design_entity_id = design_entity_id
        self.route_waypoints = [list(point) for point in route_waypoints]
        if not self.route_waypoints:
            raise ValueError("VehicleSimulation requires at least one route waypoint")
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
