"""
Transfer windows between bodies that share a parent.

Planar patched conics, as worked out in docs/space_transfer_windows_v001.md:
the bodies ride their fixed Kepler orbits, a transfer is one Lambert arc
around the parent, and its delta-v is the escape burn from a low circular
orbit at the origin plus the capture burn at the target. Pure numpy, nothing
stored.

Gravity assists build on this later: a flyby is two TransferLegs that share a
body and a date, so legs keep their v_inf vectors and the ephemeris and
Lambert functions take arrays of any shape.
"""
from dataclasses import dataclass
import math

import numpy as np

from simulations.space.orbit import G


PARKING_ALTITUDE_M = 200_000.0

# Upper end of the Lambert bracket in Izzo's x; transfers faster than this
# x allows are far outside any window search and come back unsolved.
_LAMBERT_X_MAX = 30.0
_LAMBERT_STEPS = 52

_COARSE_DEPARTURES = 49
_COARSE_FLIGHT_TIMES = 33
_REFINE_POINTS = 21
_REFINE_ROUNDS = 2


@dataclass(frozen=True)
class TransferBody:
    """
    A body on its fixed orbit, with what a transfer needs to know about it.

    mu is the body's own G*M; parent_mu is that of the body it orbits.
    """
    id: str
    name: str
    a: float
    e: float
    M0: float
    varpi: float
    mu: float
    radius: float
    parent_mu: float

    @property
    def n(self):
        return math.sqrt(self.parent_mu / self.a ** 3)

    @property
    def period(self):
        return 2 * math.pi / self.n

    @property
    def soi_radius(self):
        if self.mu <= 0.0:
            return 0.0
        return self.a * (self.mu / self.parent_mu) ** 0.4

    @classmethod
    def from_space_object(cls, obj, entity=None):
        """
        Build from a space-view body so the readout uses exactly the orbit
        the view draws. entity supplies radius_m.
        """
        orbit = obj.orbit
        try:
            radius = float((entity or {}).get("radius_m") or 0.0)
        except (TypeError, ValueError):
            radius = 0.0
        return cls(
            id=getattr(obj, "source_system_entity_id", None) or obj.entity_id or obj.name,
            name=obj.name,
            a=float(orbit.a),
            e=float(orbit.e),
            M0=float(orbit.M0),
            varpi=float(orbit.varpi),
            mu=G * float(obj.mass or 0.0),
            radius=radius,
            parent_mu=float(orbit.mu),
        )


@dataclass(frozen=True)
class HohmannEstimate:
    tof: float
    phase: float
    v_inf_depart: float
    v_inf_arrive: float
    synodic_period: float


@dataclass(frozen=True)
class TransferLeg:
    """
    One coast arc around the parent. Positions and velocities are relative
    to the parent; v_inf is the spacecraft's velocity relative to the body.
    """
    origin_id: str
    target_id: str
    depart_t: float
    arrive_t: float
    r_depart: tuple
    r_arrive: tuple
    v_depart: tuple
    v_arrive: tuple
    v_inf_depart: tuple
    v_inf_arrive: tuple

    @property
    def tof(self):
        return self.arrive_t - self.depart_t


@dataclass(frozen=True)
class TransferWindow:
    """
    A direct transfer at its cheapest departure. Headline delta-v is escape
    from a low circular orbit plus capture into one; loose_capture_dv is the
    capture into an ellipse reaching half the sphere of influence.
    """
    leg: TransferLeg
    escape_dv: float
    capture_dv: float
    loose_capture_dv: float

    @property
    def total_dv(self):
        return self.escape_dv + self.capture_dv


def planar_state(body, t):
    """
    Position and velocity relative to the parent at seconds since epoch t
    (scalar or array). Same orbit as KeplerOrbit.state_at.
    """
    t = np.asarray(t, dtype=float)
    M = np.mod(body.M0 + body.n * t, 2 * math.pi)
    e = body.e

    E = M + e * np.sin(M)
    for _ in range(30):
        delta = (E - e * np.sin(E) - M) / (1.0 - e * np.cos(E))
        E = E - delta
        if np.max(np.abs(delta)) < 1e-13:
            break

    cos_E = np.cos(E)
    sin_E = np.sin(E)
    b = body.a * math.sqrt(1.0 - e * e)
    x = body.a * (cos_E - e)
    y = b * sin_E
    rate = body.n / (1.0 - e * cos_E)
    vx = -body.a * rate * sin_E
    vy = b * rate * cos_E

    cos_w = math.cos(body.varpi)
    sin_w = math.sin(body.varpi)
    position = np.stack([cos_w * x - sin_w * y, sin_w * x + cos_w * y], axis=-1)
    velocity = np.stack([cos_w * vx - sin_w * vy, sin_w * vx + cos_w * vy], axis=-1)
    return position, velocity


def lambert_planar(r1, r2, tof, mu):
    """
    Velocities at both ends of the prograde, single-revolution conic from r1
    to r2 taking tof. Arrays of any matching shape; unsolvable points come
    back as NaN.

    Lancaster/Izzo form rather than the universal-variable one, which divides
    by zero at a 180 degree transfer: in a planar sim that is exactly where
    the cheapest transfers lie.
    """
    r1 = np.asarray(r1, dtype=float)
    r2 = np.asarray(r2, dtype=float)
    tof = np.asarray(tof, dtype=float)

    r1n = np.linalg.norm(r1, axis=-1)
    r2n = np.linalg.norm(r2, axis=-1)
    c = np.linalg.norm(r2 - r1, axis=-1)
    s = 0.5 * (r1n + r2n + c)
    cross = r1[..., 0] * r2[..., 1] - r1[..., 1] * r2[..., 0]

    with np.errstate(invalid="ignore", divide="ignore"):
        lam = np.sqrt(np.clip(1.0 - c / s, 0.0, 1.0))
        # beyond 180 degrees the arc passes the far side
        lam = np.where(cross < 0.0, -lam, lam)
        T = np.sqrt(2.0 * mu / s ** 3) * tof

        def flight_time(x):
            one_minus_x2 = 1.0 - x * x
            a = 1.0 / one_minus_x2
            alpha_e = 2.0 * np.arccos(np.clip(x, -1.0, 1.0))
            beta_e = 2.0 * np.arcsin(np.sqrt(np.clip(lam * lam / a, 0.0, 1.0)))
            beta_e = np.where(lam < 0.0, -beta_e, beta_e)
            t_ellipse = a * np.sqrt(np.abs(a)) * ((alpha_e - np.sin(alpha_e)) - (beta_e - np.sin(beta_e))) / 2.0
            alpha_h = 2.0 * np.arccosh(np.maximum(x, 1.0))
            beta_h = 2.0 * np.arcsinh(np.sqrt(np.clip(-lam * lam / a, 0.0, None)))
            beta_h = np.where(lam < 0.0, -beta_h, beta_h)
            t_hyperbola = -a * np.sqrt(np.abs(a)) * ((beta_h - np.sinh(beta_h)) - (alpha_h - np.sinh(alpha_h))) / 2.0
            return np.where(one_minus_x2 > 0.0, t_ellipse, t_hyperbola)

        # With no full revolutions, flight time falls steadily as x rises.
        lo = np.full(T.shape, -1.0 + 1e-12)
        hi = np.full(T.shape, _LAMBERT_X_MAX)
        solvable = flight_time(hi) <= T
        for _ in range(_LAMBERT_STEPS):
            mid = 0.5 * (lo + hi)
            too_long = flight_time(mid) > T
            lo = np.where(too_long, mid, lo)
            hi = np.where(too_long, hi, mid)
        x = 0.5 * (lo + hi)

        y = np.sqrt(1.0 - lam * lam + lam * lam * x * x)
        gamma = np.sqrt(mu * s / 2.0)
        rho = (r1n - r2n) / c
        sigma = np.sqrt(np.clip(1.0 - rho * rho, 0.0, None))
        vr1 = gamma * ((lam * y - x) - rho * (lam * y + x)) / r1n
        vr2 = -gamma * ((lam * y - x) + rho * (lam * y + x)) / r2n
        vt1 = gamma * sigma * (y + lam * x) / r1n
        vt2 = gamma * sigma * (y + lam * x) / r2n

        ir1 = r1 / r1n[..., None]
        ir2 = r2 / r2n[..., None]
    # tangential direction is z cross r: counter-clockwise, the sim's direction of motion
    it1 = np.stack([-ir1[..., 1], ir1[..., 0]], axis=-1)
    it2 = np.stack([-ir2[..., 1], ir2[..., 0]], axis=-1)
    v1 = vr1[..., None] * ir1 + vt1[..., None] * it1
    v2 = vr2[..., None] * ir2 + vt2[..., None] * it2

    bad = ~(solvable & (c > 0.0))
    v1[bad] = np.nan
    v2[bad] = np.nan
    return v1, v2


def escape_burn(v_inf, mu, r_p):
    """Burn from a circular orbit of radius r_p onto a hyperbola leaving at v_inf."""
    v_inf = np.asarray(v_inf, dtype=float)
    if mu <= 0.0:
        return v_inf
    return np.sqrt(v_inf * v_inf + 2.0 * mu / r_p) - math.sqrt(mu / r_p)


def capture_burn(v_inf, mu, r_p, r_a=None):
    """
    Burn at periapsis r_p from a hyperbola arriving at v_inf into a circular
    orbit, or into an ellipse reaching r_a.
    """
    v_inf = np.asarray(v_inf, dtype=float)
    if mu <= 0.0:
        return v_inf
    if r_a is None:
        return escape_burn(v_inf, mu, r_p)
    r_a = max(float(r_a), r_p)
    return np.sqrt(v_inf * v_inf + 2.0 * mu / r_p) - math.sqrt(2.0 * mu / r_p - 2.0 * mu / (r_p + r_a))


def _wrap_angle(angle):
    """Into (-pi, pi]."""
    return math.pi - (math.pi - angle) % (2 * math.pi)


def hohmann_estimate(origin, target):
    """Circular, coplanar first guess; the window search starts from it."""
    mu = origin.parent_mu
    r1 = origin.a
    r2 = target.a
    tof = math.pi * math.sqrt((0.5 * (r1 + r2)) ** 3 / mu)
    v_inf_depart = abs(math.sqrt(mu / r1) * (math.sqrt(2 * r2 / (r1 + r2)) - 1))
    v_inf_arrive = abs(math.sqrt(mu / r2) * (1 - math.sqrt(2 * r1 / (r1 + r2))))
    rate_gap = abs(1.0 / origin.period - 1.0 / target.period)
    return HohmannEstimate(
        tof=tof,
        phase=_wrap_angle(math.pi - target.n * tof),
        v_inf_depart=v_inf_depart,
        v_inf_arrive=v_inf_arrive,
        synodic_period=1.0 / rate_gap if rate_gap > 0.0 else math.inf,
    )


def phase_angle_at(origin, target, t):
    """How far the target leads the origin at t, in (-pi, pi]."""
    (ox, oy), _ = planar_state(origin, t)
    (tx, ty), _ = planar_state(target, t)
    return _wrap_angle(math.atan2(ty, tx) - math.atan2(oy, ox))


def next_phase_date(origin, target, after_t, estimate=None):
    """
    First date after after_t at which the target leads by the Hohmann phase
    angle. Found from mean motions, then corrected on the real positions.
    """
    estimate = estimate or hohmann_estimate(origin, target)
    rate = target.n - origin.n
    if rate == 0.0:
        return None
    current = phase_angle_at(origin, target, after_t)
    if rate > 0.0:
        gap = (estimate.phase - current) % (2 * math.pi)
    else:
        gap = (current - estimate.phase) % (2 * math.pi)
    t = after_t + gap / abs(rate)
    for _ in range(4):
        t += _wrap_angle(estimate.phase - phase_angle_at(origin, target, t)) / rate
    return t


def _transfer_costs(origin, target, depart_t, tof, parking_altitude_m):
    r1, body_v1 = planar_state(origin, depart_t)
    r2, body_v2 = planar_state(target, depart_t + tof)
    v1, v2 = lambert_planar(r1, r2, tof, origin.parent_mu)
    v_inf_depart = v1 - body_v1
    v_inf_arrive = v2 - body_v2
    escape = escape_burn(np.linalg.norm(v_inf_depart, axis=-1), origin.mu, origin.radius + parking_altitude_m)
    capture = capture_burn(np.linalg.norm(v_inf_arrive, axis=-1), target.mu, target.radius + parking_altitude_m)
    return {
        "total": escape + capture,
        "escape": escape,
        "capture": capture,
        "r1": r1, "r2": r2, "v1": v1, "v2": v2,
        "v_inf_depart": v_inf_depart,
        "v_inf_arrive": v_inf_arrive,
    }


def _grid_minimum(origin, target, departures, flight_times, parking_altitude_m):
    depart_grid, tof_grid = np.meshgrid(departures, flight_times, indexing="ij")
    total = _transfer_costs(origin, target, depart_grid, tof_grid, parking_altitude_m)["total"]
    total = np.where(np.isfinite(total), total, np.inf)
    if not np.isfinite(total).any():
        return None
    i, j = np.unravel_index(np.argmin(total), total.shape)
    return i, j


def _search_window(origin, target, seed_t, estimate, parking_altitude_m):
    """Cheapest departure and flight time within a quarter synodic period of seed_t."""
    half_span = 0.25 * min(estimate.synodic_period, 4 * max(origin.period, target.period))
    dep_lo, dep_hi = seed_t - half_span, seed_t + half_span
    tof_lo, tof_hi = 0.5 * estimate.tof, 1.5 * estimate.tof

    # The grid is widened when the cheapest point sits on an edge.
    for _ in range(3):
        departures = np.linspace(dep_lo, dep_hi, _COARSE_DEPARTURES)
        flight_times = np.linspace(tof_lo, tof_hi, _COARSE_FLIGHT_TIMES)
        best = _grid_minimum(origin, target, departures, flight_times, parking_altitude_m)
        if best is None:
            return None
        i, j = best
        widened = False
        if j == 0 and tof_lo > 0.05 * estimate.tof:
            tof_lo = max(0.05 * estimate.tof, 0.6 * tof_lo)
            widened = True
        elif j == len(flight_times) - 1:
            tof_hi *= 1.4
            widened = True
        if not widened:
            break

    dep_step = departures[1] - departures[0]
    tof_step = flight_times[1] - flight_times[0]
    best_dep, best_tof = departures[i], flight_times[j]
    for _ in range(_REFINE_ROUNDS):
        departures = np.linspace(best_dep - 2 * dep_step, best_dep + 2 * dep_step, _REFINE_POINTS)
        flight_times = np.linspace(max(best_tof - 2 * tof_step, 0.05 * estimate.tof),
                                   best_tof + 2 * tof_step, _REFINE_POINTS)
        best = _grid_minimum(origin, target, departures, flight_times, parking_altitude_m)
        if best is None:
            return None
        best_dep, best_tof = departures[best[0]], flight_times[best[1]]
        dep_step = departures[1] - departures[0]
        tof_step = flight_times[1] - flight_times[0]

    costs = _transfer_costs(origin, target, np.array(best_dep), np.array(best_tof), parking_altitude_m)
    if not np.isfinite(costs["total"]):
        return None
    loose = capture_burn(np.linalg.norm(costs["v_inf_arrive"]), target.mu, target.radius + parking_altitude_m,
                         r_a=0.5 * target.soi_radius)
    leg = TransferLeg(
        origin_id=origin.id,
        target_id=target.id,
        depart_t=float(best_dep),
        arrive_t=float(best_dep + best_tof),
        r_depart=tuple(costs["r1"].tolist()),
        r_arrive=tuple(costs["r2"].tolist()),
        v_depart=tuple(costs["v1"].tolist()),
        v_arrive=tuple(costs["v2"].tolist()),
        v_inf_depart=tuple(costs["v_inf_depart"].tolist()),
        v_inf_arrive=tuple(costs["v_inf_arrive"].tolist()),
    )
    return TransferWindow(
        leg=leg,
        escape_dv=float(costs["escape"]),
        capture_dv=float(costs["capture"]),
        loose_capture_dv=float(loose),
    )


def find_direct_windows(origin, target, after_t, count=3, parking_altitude_m=PARKING_ALTITUDE_M):
    """
    The next `count` direct transfer windows from origin to target whose
    cheapest departure falls at or after after_t, in date order. Both bodies
    must orbit the same parent.
    """
    if not math.isclose(origin.parent_mu, target.parent_mu, rel_tol=1e-9):
        raise ValueError("Transfer windows need two bodies orbiting the same parent.")
    estimate = hohmann_estimate(origin, target)
    if not math.isfinite(estimate.synodic_period):
        return []

    synodic = estimate.synodic_period
    windows = []
    # Start half a period back: a window whose phase-angle date has passed
    # can still have its cheapest departure ahead.
    seed = next_phase_date(origin, target, after_t - 0.5 * synodic, estimate)
    for _ in range(count + 2):
        if len(windows) >= count or seed is None:
            break
        window = _search_window(origin, target, seed, estimate, parking_altitude_m)
        seed = next_phase_date(origin, target, seed + 0.5 * synodic, estimate)
        if window is None or window.leg.depart_t < after_t:
            continue
        if windows and window.leg.depart_t - windows[-1].leg.depart_t < 0.5 * synodic:
            continue
        windows.append(window)
    return windows
