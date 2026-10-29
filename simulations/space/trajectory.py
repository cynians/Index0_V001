"""
A craft's path in patched conics with manoeuvre nodes
(docs/space_spacecraft_navigation_v001.md sections 4 and 5).

The craft starts from a state in one body's frame and its path is a chain of
conic segments. A segment ends at a node (a burn), on leaving the frame
body's sphere of influence (into its parent's frame), on entering a child's
sphere (into the child's frame), on reaching the surface, or at the horizon.
Planar: a node's delta-v is prograde (along the velocity relative to the
frame body) and radial (in the plane, square to it, away from the body).
"""
from dataclasses import dataclass, field
import math

import numpy as np

from simulations.space.conics import Conic
from simulations.space.transfer import planar_state


# A child's sphere is looked for at least this often along a path; a planet's
# sphere takes days to cross at interplanetary speeds.
ENTRY_SEARCH_STEP_S = 6 * 3600.0
_ENTRY_SAMPLES_MAX = 4000
_MAX_SEGMENTS = 16


@dataclass(frozen=True)
class Body:
    id: str
    name: str
    parent_id: str          # None for the root
    mu: float
    radius: float
    soi_radius: float       # math.inf for the root
    elements: object = None  # TransferBody of its orbit around the parent; None for the root


class BodyTree:
    """The bodies a craft can orbit, each placed relative to its parent."""

    def __init__(self, bodies):
        self.bodies = {body.id: body for body in bodies}
        self._children = {}
        for body in bodies:
            if body.parent_id is not None:
                self._children.setdefault(body.parent_id, []).append(body)

    def __getitem__(self, body_id):
        return self.bodies[body_id]

    def children(self, body_id):
        return self._children.get(body_id, [])

    def state(self, body_id, t):
        """Position and velocity relative to the body's parent."""
        body = self.bodies[body_id]
        if body.elements is None:
            return np.zeros(2), np.zeros(2)
        position, velocity = planar_state(body.elements, t)
        return np.asarray(position, dtype=float), np.asarray(velocity, dtype=float)

    def positions(self, body_id, times):
        return planar_state(self.bodies[body_id].elements, times)[0]

    def absolute_position(self, body_id, t):
        """Position relative to the root, adding up the chain of parents."""
        total = np.zeros(2)
        while body_id is not None:
            total = total + self.state(body_id, t)[0]
            body_id = self.bodies[body_id].parent_id
        return total


@dataclass(frozen=True)
class Node:
    t: float
    prograde: float = 0.0
    radial: float = 0.0

    @property
    def delta_v(self):
        return math.hypot(self.prograde, self.radial)


@dataclass(frozen=True)
class Segment:
    frame_id: str
    conic: Conic
    t_start: float
    t_end: float
    ends: str               # "node", "exit", "entry", "impact" or "horizon"
    ref: object = None      # the node's index, or the id of the body entered


@dataclass(frozen=True)
class Prediction:
    segments: tuple = field(default_factory=tuple)

    def segment_at(self, t):
        for segment in self.segments:
            if t < segment.t_end:
                return segment
        return self.segments[-1]

    def position(self, t, tree):
        """Where the craft is relative to the root at time t (before the start or after the horizon, extrapolated)."""
        segment = self.segment_at(t)
        return tree.absolute_position(segment.frame_id, t) + np.array(segment.conic.state_at(t)[0])

    def encounter(self, body_id):
        """The first segment inside a body's sphere, and whether the path ends on its surface."""
        for index, segment in enumerate(self.segments):
            if segment.frame_id == body_id:
                impact = any(
                    later.frame_id == body_id and later.ends == "impact" for later in self.segments[index:]
                )
                return segment, impact
        return None, False

    def closest_approach(self, body_id, tree, samples=2000):
        """(distance, time) of the nearest pass to a body, over the segments in its parent's frame."""
        parent_id = tree[body_id].parent_id
        best = (math.inf, None)
        for segment in self.segments:
            if segment.frame_id != parent_id or segment.t_end <= segment.t_start:
                continue
            times = np.linspace(segment.t_start, segment.t_end, samples)
            gaps = np.linalg.norm(segment.conic.positions_at(times) - tree.positions(body_id, times), axis=1)
            index = int(np.argmin(gaps))
            if gaps[index] < best[0]:
                best = (float(gaps[index]), float(times[index]))
        return best


def apply_node(node, position, velocity):
    """The velocity after a node's burn, in the frame the craft is in."""
    position = np.asarray(position, dtype=float)
    velocity = np.asarray(velocity, dtype=float)
    prograde = velocity / np.linalg.norm(velocity)
    outward = position / np.linalg.norm(position)
    radial = outward - (outward @ prograde) * prograde
    norm = np.linalg.norm(radial)
    # moving straight up or down: radial is then square to the motion, on the left
    radial = radial / norm if norm > 1e-9 else np.array([-prograde[1], prograde[0]])
    return velocity + node.prograde * prograde + node.radial * radial


def _gap(conic, tree, body_id, t):
    return float(np.linalg.norm(np.array(conic.state_at(t)[0]) - tree.state(body_id, t)[0]))


def _first_entry(tree, frame_id, conic, t_start, t_end):
    """(time, body id) of the first entry into a child's sphere between t_start and t_end, or None."""
    children = [child for child in tree.children(frame_id) if 0.0 < child.soi_radius < math.inf]
    if not children or t_end <= t_start:
        return None
    samples = int(min(_ENTRY_SAMPLES_MAX, max(64, (t_end - t_start) / ENTRY_SEARCH_STEP_S)))
    times = np.linspace(t_start, t_end, samples)
    craft = conic.positions_at(times)
    best = None
    for child in children:
        outside = np.linalg.norm(craft - tree.positions(child.id, times), axis=1) >= child.soi_radius
        if not outside.any():
            continue
        # a craft that has just left this sphere starts on its edge: look for a way back in after it is out
        first_out = int(np.argmax(outside))
        inside = np.nonzero(~outside[first_out:])[0]
        if not len(inside):
            continue
        index = first_out + int(inside[0])
        low, high = float(times[index - 1]), float(times[index])
        for _ in range(48):
            middle = 0.5 * (low + high)
            if _gap(conic, tree, child.id, middle) < child.soi_radius:
                high = middle
            else:
                low = middle
        if best is None or high < best[0]:
            best = (high, child.id)
    return best


def predict(tree, frame_id, t0, position, velocity, nodes, horizon_t):
    """The path from a state in a body's frame, through the nodes in time order, up to the horizon."""
    nodes = sorted(nodes, key=lambda node: node.t)
    pending = [index for index, node in enumerate(nodes) if node.t >= t0]
    position = np.asarray(position, dtype=float)
    velocity = np.asarray(velocity, dtype=float)
    segments = []
    t = t0
    while len(segments) < _MAX_SEGMENTS and t < horizon_t:
        body = tree[frame_id]
        conic = Conic.from_state(tuple(position), tuple(velocity), body.mu, t)
        events = [(horizon_t, "horizon", None)]
        if pending:
            events.append((nodes[pending[0]].t, "node", pending[0]))
        if body.parent_id is not None:
            leaving = conic.radius_crossing_t(body.soi_radius, t, outgoing=True)
            if leaving is not None:
                events.append((leaving, "exit", None))
        if body.radius > 0.0:
            landing = conic.radius_crossing_t(body.radius, t, outgoing=False)
            if landing is not None:
                events.append((landing, "impact", None))
        entry = _first_entry(tree, frame_id, conic, t, min(event[0] for event in events))
        if entry is not None:
            events.append((entry[0], "entry", entry[1]))
        t_event, ends, ref = min(events, key=lambda event: event[0])
        segments.append(Segment(frame_id, conic, t, t_event, ends, ref))

        position, velocity = (np.array(part) for part in conic.state_at(t_event))
        if ends == "node":
            velocity = apply_node(nodes[ref], position, velocity)
            pending.pop(0)
        elif ends == "exit":
            frame_position, frame_velocity = tree.state(frame_id, t_event)
            position, velocity = position + frame_position, velocity + frame_velocity
            frame_id = body.parent_id
        elif ends == "entry":
            child_position, child_velocity = tree.state(ref, t_event)
            position, velocity = position - child_position, velocity - child_velocity
            frame_id = ref
        else:
            break
        t = t_event
    return Prediction(tuple(segments))
