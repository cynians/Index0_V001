"""
A distinct craft travelling a link: the fine detail of the logistics
simulation (docs/logistics_simulation_concept_v001.md section 3.5), flown in
patched conics with manoeuvre nodes (docs/space_spacecraft_navigation_v001.md
sections 4 and 5).

A journey keeps its plan: where the craft starts (parked in a low orbit at
the origin) and its nodes, the burns. Its path is predicted from those
(``simulations/space/trajectory.py``), so editing a node re-predicts the
whole flight, and where the craft is follows from plan and clock -- time
warp costs nothing.

The first two nodes come from a transfer window: the escape burn and the
capture burn of the patched-conic flight along it. Each hyperbola is solved so
that its velocity at the sphere's edge is what the leg around the parent
needs there, and the edge points are refined until the legs meet, so the
untouched journey arrives in a low orbit at the target with no course
corrections.
"""
from dataclasses import dataclass, replace
import math

import numpy as np

from simulations.space.conics import Conic, circular_orbit, hyperbola_through
from simulations.space.trajectory import Node, predict
from simulations.space.transfer import PARKING_ALTITUDE_M, lambert_planar, planar_state


_MATCH_ROUNDS = 6
# How far past the planned capture the path is predicted, so a craft that
# misses shows where it goes.
HORIZON_AFTER_CAPTURE_S = 30 * 86_400.0


def _unit(vector):
    vector = np.asarray(vector, dtype=float)
    return vector / np.linalg.norm(vector)


def _periapsis_burn(hyperbola, periapsis_radius):
    """From a circular orbit at periapsis onto the hyperbola, or back."""
    mu = hyperbola.mu
    return math.sqrt(mu * (2.0 / periapsis_radius - 1.0 / hyperbola.a)) - math.sqrt(mu / periapsis_radius)


def _anomaly(conic, t):
    """True anomaly of a conic at time t, in its direction of motion."""
    x, y = conic.state_at(t)[0]
    return math.remainder(conic.direction * (math.atan2(y, x) - conic.varpi), 2.0 * math.pi)


@dataclass(frozen=True)
class Journey:
    craft_id: str
    craft_name: str
    origin: object      # simulations.space.transfer.TransferBody
    target: object
    window: object      # simulations.space.transfer.TransferWindow
    propulsion: object  # simulations.space.propulsion.PropulsionState at the start
    tree: object        # simulations.space.trajectory.BodyTree
    start_t: float
    start_position: tuple   # relative to the origin, parked
    start_velocity: tuple
    nodes: tuple
    prediction: object  # simulations.space.trajectory.Prediction
    # the plan the window gave, kept for comparison
    departure: Conic
    cruise: Conic
    arrival: Conic
    burn_t: float
    exit_t: float
    entry_t: float
    capture_t: float
    escape_dv: float
    capture_dv: float

    @classmethod
    def plan(cls, craft_id, craft_name, origin, target, window, propulsion, tree, parking_altitude_m=PARKING_ALTITUDE_M):
        """
        Fly the window's leg in patched conics: parked at the origin, an escape
        node and a capture node. Raises ValueError when a body has no mass to
        orbit, or the leg is too slow to leave or reach it.
        """
        if origin.mu <= 0.0 or target.mu <= 0.0:
            raise ValueError("patched conics need bodies with mass")
        leg = window.leg
        parent_mu = origin.parent_mu
        origin_soi, target_soi = origin.soi_radius, target.soi_radius
        origin_parking = origin.radius + parking_altitude_m
        target_parking = target.radius + parking_altitude_m
        v_inf_depart, v_inf_arrive = np.array(leg.v_inf_depart), np.array(leg.v_inf_arrive)

        # Cross the spheres' edges when a straight run at v_inf from the centres would.
        exit_t = leg.depart_t + origin_soi / np.linalg.norm(v_inf_depart)
        entry_t = leg.arrive_t - target_soi / np.linalg.norm(v_inf_arrive)
        origin_at_exit, origin_velocity = planar_state(origin, exit_t)
        target_at_entry, target_velocity = planar_state(target, entry_t)
        exit_point = origin_at_exit + origin_soi * _unit(v_inf_depart)
        entry_point = target_at_entry - target_soi * _unit(v_inf_arrive)

        for _ in range(_MATCH_ROUNDS):
            v_exit, v_entry = lambert_planar(exit_point, entry_point, entry_t - exit_t, parent_mu)
            departure, exit_anomaly = hyperbola_through(origin.mu, origin_parking, v_exit - origin_velocity, origin_soi, True)
            arrival, entry_anomaly = hyperbola_through(target.mu, target_parking, v_entry - target_velocity, target_soi, False)
            exit_point = origin_at_exit + np.array(departure.position_at_anomaly(exit_anomaly))
            entry_point = target_at_entry + np.array(arrival.position_at_anomaly(entry_anomaly))
        v_exit, _v_entry = lambert_planar(exit_point, entry_point, entry_t - exit_t, parent_mu)
        cruise = Conic.from_state(tuple(exit_point), tuple(v_exit), parent_mu, exit_t)

        burn_t = exit_t - departure.time_from_periapsis(exit_anomaly)
        capture_t = entry_t - arrival.time_from_periapsis(entry_anomaly)
        departure = replace(departure, t0=burn_t)
        arrival = replace(arrival, t0=capture_t)
        escape_dv = _periapsis_burn(departure, origin_parking)
        capture_dv = _periapsis_burn(arrival, target_parking)

        # Parked one orbit before the burn, at the burn point; the escape burn is all prograde there.
        parking = circular_orbit(origin.mu, origin_parking, departure.varpi, burn_t)
        start_t = burn_t - parking.period
        start_position, start_velocity = parking.state_at(start_t)
        journey = cls(
            craft_id=craft_id, craft_name=craft_name, origin=origin, target=target,
            window=window, propulsion=propulsion, tree=tree,
            start_t=start_t, start_position=start_position, start_velocity=start_velocity,
            nodes=(Node(burn_t, escape_dv, 0.0), Node(capture_t, -capture_dv, 0.0)),
            prediction=None,
            departure=departure, cruise=cruise, arrival=arrival,
            burn_t=burn_t, exit_t=exit_t, entry_t=entry_t, capture_t=capture_t,
            escape_dv=escape_dv, capture_dv=capture_dv,
        )
        return journey.with_nodes(journey.nodes)

    def with_nodes(self, nodes):
        """The same journey with other nodes, its path predicted again."""
        nodes = tuple(sorted(nodes, key=lambda node: node.t))
        horizon = max([self.capture_t] + [node.t for node in nodes]) + HORIZON_AFTER_CAPTURE_S
        prediction = predict(self.tree, self.origin.id, self.start_t, self.start_position, self.start_velocity,
                             nodes, horizon)
        return replace(self, nodes=nodes, prediction=prediction)

    @property
    def origin_id(self):
        return self.origin.id

    @property
    def origin_name(self):
        return self.origin.name

    @property
    def target_id(self):
        return self.target.id

    @property
    def target_name(self):
        return self.target.name

    @property
    def depart_t(self):
        return self.nodes[0].t if self.nodes else self.burn_t

    def position(self, t):
        """Where the craft is relative to the root of the body tree."""
        return tuple(self.prediction.position(t, self.tree))

    def situation(self, t):
        """What the craft is doing at t, in words."""
        segment = self.prediction.segment_at(t)
        body = self.tree[segment.frame_id]
        if segment.ends == "impact" and t >= segment.t_end:
            return f"Crashed on {body.name}"
        if body.parent_id is None:
            return f"Cruising around {body.name}"
        if not segment.conic.is_hyperbolic:
            return f"In orbit around {body.name}"
        return f"Approaching {body.name}" if t < segment.conic.periapsis_t else f"Leaving {body.name}"

    def outcome(self):
        """(kind, figure) at the target: ("orbit"/"flyby", periapsis altitude), ("impact", None) or ("miss", closest distance)."""
        segment, impact = self.prediction.encounter(self.target.id)
        if segment is None:
            return "miss", self.prediction.closest_approach(self.target.id, self.tree)[0]
        if impact:
            return "impact", None
        final = self.prediction.segments[-1]
        captured = final.frame_id == self.target.id and not final.conic.is_hyperbolic
        return ("orbit" if captured else "flyby"), segment.conic.periapsis_radius - self.target.radius

    def node_budget(self):
        """(node, propellant left after it, delta-v left after it) for each node in turn."""
        rows = []
        state = self.propulsion
        for node in self.nodes:
            state = state.after_burn(node.delta_v)
            rows.append((node, state.propellant_kg, state.delta_v_m_s()))
        return rows

    @property
    def planned_dv(self):
        return sum(node.delta_v for node in self.nodes)

    def propulsion_after(self):
        """Propellant left after every node."""
        state = self.propulsion
        for node in self.nodes:
            state = state.after_burn(node.delta_v)
        return state

    def segments(self, points=120):
        """
        The predicted path for drawing, each piece in its body's frame:
        (frame id, kind, positions) with kind "cruise" around the root,
        "orbit" for a closed path round a body and "hyperbola" otherwise.
        Pieces are sampled by true anomaly so the turn near periapsis stays smooth.
        """
        pieces = []
        for segment in self.prediction.segments:
            conic = segment.conic
            frame = self.tree[segment.frame_id]
            if frame.parent_id is None:
                kind = "cruise"
            else:
                kind = "hyperbola" if conic.is_hyperbolic else "orbit"
            if not conic.is_hyperbolic and segment.t_end - segment.t_start >= conic.period:
                start, end = 0.0, 2.0 * math.pi
            else:
                start, end = _anomaly(conic, segment.t_start), _anomaly(conic, segment.t_end)
                if end < start:
                    end += 2.0 * math.pi
            anomalies = [start + (end - start) * index / (points - 1) for index in range(points)]
            pieces.append((segment.frame_id, kind, [conic.position_at_anomaly(nu) for nu in anomalies]))
        return pieces
