"""
Aircraft realization of the vehicle sub-simulation pattern.

Architectural role: an aircraft flying on the Map runs a VehicleSimulation
(simulations/vehicle/vehicle_simulation.py) in the background as its
operative core -- component/capability bookkeeping only, via
``derive_capabilities()`` -- and this class owns the Map-mode-specific
flight state and physics on top: lon/lat/altitude position, heading,
airspeed, and a simplified point-mass flight model driven by the core's
component-derived thrust/lift capabilities and the local air density from
the world-gen atmosphere layer profile. A future spacecraft or combat
vehicle would be a sibling realization, wrapping its own VehicleSimulation
core the same way -- domain physics and host simulation differ, the
underlying operative core does not.

Ticked directly by MapSimulation (not SiteSimulation, which stays exclusive
to ground logistics carts); entirely ephemeral runtime state, per the
project's sim-mode-is-a-viewpoint rule -- only the underlying vehicle design
(hence its performance capability) is a durable ontology fact.
"""

import math

from simulations.vehicle.vehicle_simulation import VehicleSimulation

EARTH_G_M_S2 = 9.80665
FALLBACK_AIR_DENSITY_KG_M3 = 1.225
DRAG_COEFFICIENT = 0.045
LIFT_COEFFICIENT = 1.0
MAX_TURN_RATE_DEG_S = 25.0
PITCH_CLIMB_AUTHORITY_M_S2 = 3.0
MAX_VERTICAL_SPEED_M_S = 40.0


class AircraftFlightSimulation:
    def __init__(
        self,
        world_model,
        vehicle_entity_id,
        *,
        design_entity_id=None,
        lon_deg=0.0,
        lat_deg=0.0,
        altitude_m=1000.0,
        heading_deg=0.0,
        label=None,
    ):
        self.core = VehicleSimulation(
            world_model, vehicle_entity_id,
            design_entity_id=design_entity_id, label=label,
        )
        self.vehicle_entity_id = vehicle_entity_id
        self.design_entity_id = design_entity_id
        self.label = label or vehicle_entity_id
        self.lon_deg = float(lon_deg)
        self.lat_deg = max(-89.9, min(89.9, float(lat_deg)))
        self.altitude_m = max(0.0, float(altitude_m))
        self.heading_deg = float(heading_deg) % 360.0
        self.airspeed_m_s = 0.0
        self.vertical_speed_m_s = 0.0
        self.throttle_fraction = 0.0
        self._capabilities = self.core.derive_capabilities()

    def refresh_capabilities(self):
        """Re-derive capability data -- call after the underlying design changes."""
        self._capabilities = self.core.derive_capabilities()
        return self._capabilities

    def set_throttle(self, fraction):
        self.throttle_fraction = max(0.0, min(1.0, float(fraction)))

    def adjust_throttle(self, delta):
        self.set_throttle(self.throttle_fraction + delta)

    def _air_density_at_altitude(self, atmosphere_layers):
        bands = (atmosphere_layers or {}).get("bands") or []
        if not bands:
            return FALLBACK_AIR_DENSITY_KG_M3
        altitude_km = self.altitude_m / 1000.0
        for band in bands:
            top = band.get("top_altitude_km")
            if altitude_km >= band.get("base_altitude_km", 0.0) and (top is None or altitude_km <= top):
                return max(0.0, float(band.get("density_kg_m3", 0.0) or 0.0))
        return 0.0

    def tick(self, dt, controls=None, atmosphere_layers=None, planet_radius_m=6_371_000.0):
        """
        Advance flight state by ``dt`` seconds. ``controls`` is an optional
        dict of player-piloting inputs: ``throttle_delta`` (fraction/second),
        ``pitch_input``/``yaw_input`` (-1..1). Omitted controls just hold
        current trim -- the aircraft keeps flying on its last throttle/heading.
        """
        dt = max(0.0, float(dt))
        controls = controls or {}

        if "throttle_delta" in controls:
            self.adjust_throttle(float(controls["throttle_delta"]) * dt)

        capabilities = self._capabilities
        mass_kg = max(1.0, float(capabilities.get("mass_kg", 0.0) or 0.0))
        lift_area_m2 = float(capabilities.get("lift_area_m2", 0.0) or 0.0)
        air_density = self._air_density_at_altitude(atmosphere_layers)

        thrust_n = float(capabilities.get("thrust_n", 0.0) or 0.0) * self.throttle_fraction
        drag_n = 0.5 * air_density * self.airspeed_m_s ** 2 * lift_area_m2 * DRAG_COEFFICIENT
        self.airspeed_m_s = max(0.0, self.airspeed_m_s + ((thrust_n - drag_n) / mass_kg) * dt)

        lift_n = 0.5 * air_density * self.airspeed_m_s ** 2 * lift_area_m2 * LIFT_COEFFICIENT
        lift_margin_m_s2 = (lift_n - mass_kg * EARTH_G_M_S2) / mass_kg
        pitch_input = max(-1.0, min(1.0, float(controls.get("pitch_input", 0.0))))
        vertical_accel = lift_margin_m_s2 + pitch_input * PITCH_CLIMB_AUTHORITY_M_S2
        self.vertical_speed_m_s = max(
            -MAX_VERTICAL_SPEED_M_S, min(MAX_VERTICAL_SPEED_M_S, self.vertical_speed_m_s + vertical_accel * dt),
        )
        self.altitude_m = max(0.0, self.altitude_m + self.vertical_speed_m_s * dt)
        if self.altitude_m <= 0.0:
            self.vertical_speed_m_s = max(0.0, self.vertical_speed_m_s)

        yaw_input = max(-1.0, min(1.0, float(controls.get("yaw_input", 0.0))))
        turn_rate_deg_s = min(MAX_TURN_RATE_DEG_S, self.airspeed_m_s * 0.3)
        self.heading_deg = (self.heading_deg + yaw_input * turn_rate_deg_s * dt) % 360.0

        distance_m = self.airspeed_m_s * dt
        if distance_m > 0.0:
            heading_rad = math.radians(self.heading_deg)
            lat_rad = math.radians(self.lat_deg)
            radius_m = max(1.0, float(planet_radius_m or 6_371_000.0))
            delta_lat_deg = math.degrees((distance_m * math.cos(heading_rad)) / radius_m)
            cos_lat = max(0.05, math.cos(lat_rad))
            delta_lon_deg = math.degrees((distance_m * math.sin(heading_rad)) / (radius_m * cos_lat))
            self.lat_deg = max(-89.9, min(89.9, self.lat_deg + delta_lat_deg))
            self.lon_deg = ((self.lon_deg + delta_lon_deg + 180.0) % 360.0) - 180.0

    def get_presence_payload(self):
        return {
            "id": self.vehicle_entity_id,
            "label": self.label,
            "lon_deg": self.lon_deg,
            "lat_deg": self.lat_deg,
            "altitude_m": self.altitude_m,
            "heading_deg": self.heading_deg,
            "airspeed_m_s": self.airspeed_m_s,
            "vertical_speed_m_s": self.vertical_speed_m_s,
            "throttle_fraction": self.throttle_fraction,
            "capabilities": dict(self._capabilities),
        }
