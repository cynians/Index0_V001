"""
A spacecraft's coast arc as an analytic conic (docs/space_spacecraft_navigation_v001.md
section 4): built from a position and velocity at a time, read at any other
time. Planar; ellipses and hyperbolas; prograde or retrograde.
"""
from dataclasses import dataclass
import math

import numpy as np


@dataclass(frozen=True)
class Conic:
    mu: float
    t0: float
    a: float          # negative for a hyperbola
    e: float
    varpi: float      # direction of periapsis
    M0: float         # mean anomaly at t0 (hyperbolic mean anomaly on a hyperbola)
    direction: int    # +1 counter-clockwise (the sim's direction of motion), -1 clockwise

    @classmethod
    def from_state(cls, position, velocity, mu, t0):
        x, y = position
        vx, vy = velocity
        r = math.hypot(x, y)
        v2 = vx * vx + vy * vy
        h = x * vy - y * vx
        direction = 1 if h >= 0.0 else -1
        r_dot_v = x * vx + y * vy
        ex = ((v2 - mu / r) * x - r_dot_v * vx) / mu
        ey = ((v2 - mu / r) * y - r_dot_v * vy) / mu
        e = math.hypot(ex, ey)
        a = 1.0 / (2.0 / r - v2 / mu)
        varpi = math.atan2(ey, ex) if e > 1e-12 else math.atan2(y, x)
        nu = direction * (math.atan2(y, x) - varpi)
        if e < 1.0:
            E = 2.0 * math.atan2(math.sqrt(1.0 - e) * math.sin(nu / 2.0), math.sqrt(1.0 + e) * math.cos(nu / 2.0))
            M0 = E - e * math.sin(E)
        else:
            F = 2.0 * math.atanh(math.sqrt((e - 1.0) / (e + 1.0)) * math.tan(nu / 2.0))
            M0 = e * math.sinh(F) - F
        return cls(mu=mu, t0=t0, a=a, e=e, varpi=varpi, M0=M0, direction=direction)

    @property
    def is_hyperbolic(self):
        return self.e >= 1.0

    @property
    def n(self):
        return math.sqrt(self.mu / abs(self.a) ** 3)

    def state_at(self, t):
        """Position and velocity relative to the focus body at time t."""
        M = self.M0 + self.n * (t - self.t0)
        e = self.e
        if not self.is_hyperbolic:
            M = math.remainder(M, 2.0 * math.pi)  # many orbits can pass in a long prediction
            E = M + e * math.sin(M)
            for _ in range(50):
                delta = (E - e * math.sin(E) - M) / (1.0 - e * math.cos(E))
                E -= delta
                if abs(delta) < 1e-13:
                    break
            b = self.a * math.sqrt(1.0 - e * e)
            x, y = self.a * (math.cos(E) - e), b * math.sin(E)
            rate = self.n / (1.0 - e * math.cos(E))
            vx, vy = -self.a * math.sin(E) * rate, b * math.cos(E) * rate
        else:
            F = math.asinh(M / e)
            for _ in range(80):
                delta = (e * math.sinh(F) - F - M) / (e * math.cosh(F) - 1.0)
                F -= delta
                if abs(delta) < 1e-13:
                    break
            span = -self.a
            b = span * math.sqrt(e * e - 1.0)
            x, y = span * (e - math.cosh(F)), b * math.sinh(F)
            rate = self.n / (e * math.cosh(F) - 1.0)
            vx, vy = -span * math.sinh(F) * rate, b * math.cosh(F) * rate
        y, vy = self.direction * y, self.direction * vy
        cos_w, sin_w = math.cos(self.varpi), math.sin(self.varpi)
        return (
            (cos_w * x - sin_w * y, sin_w * x + cos_w * y),
            (cos_w * vx - sin_w * vy, sin_w * vx + cos_w * vy),
        )

    def position_at_anomaly(self, nu):
        """Position relative to the focus at true anomaly nu."""
        semi_latus = self.a * (1.0 - self.e * self.e)
        r = semi_latus / (1.0 + self.e * math.cos(nu))
        angle = self.varpi + self.direction * nu
        return r * math.cos(angle), r * math.sin(angle)

    def time_from_periapsis(self, nu):
        """Time from periapsis to true anomaly nu (negative before periapsis)."""
        e = self.e
        if self.is_hyperbolic:
            F = 2.0 * math.atanh(math.sqrt((e - 1.0) / (e + 1.0)) * math.tan(nu / 2.0))
            M = e * math.sinh(F) - F
        else:
            E = 2.0 * math.atan2(math.sqrt(1.0 - e) * math.sin(nu / 2.0), math.sqrt(1.0 + e) * math.cos(nu / 2.0))
            M = E - e * math.sin(E)
        # nu runs in the direction of motion either way round, so time follows M alone
        return M / self.n

    @property
    def periapsis_radius(self):
        return self.a * (1.0 - self.e)

    @property
    def apoapsis_radius(self):
        return self.a * (1.0 + self.e) if not self.is_hyperbolic else math.inf

    @property
    def period(self):
        return 2.0 * math.pi / self.n if not self.is_hyperbolic else math.inf

    @property
    def periapsis_t(self):
        """A time of periapsis passage (on an ellipse, the one nearest t0's mean anomaly)."""
        return self.t0 - self.M0 / self.n

    def radius_crossing_t(self, radius, after_t, outgoing=True):
        """First time at or after after_t that the conic passes `radius` going out (or in); None if never."""
        if radius <= self.periapsis_radius or radius >= self.apoapsis_radius:
            return None
        semi_latus = self.a * (1.0 - self.e * self.e)
        nu = math.acos(max(-1.0, min(1.0, (semi_latus / radius - 1.0) / self.e)))
        crossing = self.periapsis_t + self.time_from_periapsis(nu if outgoing else -nu)
        if self.is_hyperbolic:
            return crossing if crossing >= after_t else None
        return crossing + math.ceil((after_t - crossing) / self.period) * self.period

    def positions_at(self, times):
        """Positions at many times at once (numpy), for searching a path."""
        times = np.asarray(times, dtype=float)
        M = self.M0 + self.n * (times - self.t0)
        e = self.e
        if not self.is_hyperbolic:
            M = np.remainder(M + math.pi, 2.0 * math.pi) - math.pi
            E = M + e * np.sin(M)
            for _ in range(30):
                E = E - (E - e * np.sin(E) - M) / (1.0 - e * np.cos(E))
            x = self.a * (np.cos(E) - e)
            y = self.a * math.sqrt(1.0 - e * e) * np.sin(E)
        else:
            F = np.arcsinh(M / e)
            for _ in range(60):
                F = F - (e * np.sinh(F) - F - M) / (e * np.cosh(F) - 1.0)
            span = -self.a
            x = span * (e - np.cosh(F))
            y = span * math.sqrt(e * e - 1.0) * np.sinh(F)
        y = self.direction * y
        cos_w, sin_w = math.cos(self.varpi), math.sin(self.varpi)
        return np.stack([cos_w * x - sin_w * y, sin_w * x + cos_w * y], axis=-1)

    def path(self, t_start, t_end, points=120):
        """Positions along the arc from t_start to t_end, for drawing."""
        if points < 2 or t_end <= t_start:
            return [self.state_at(t_start)[0]]
        step = (t_end - t_start) / (points - 1)
        return [self.state_at(t_start + index * step)[0] for index in range(points)]


def circular_orbit(mu, radius, angle, t0):
    """A counter-clockwise circular orbit that is at `angle` at time t0."""
    return Conic(mu=mu, t0=t0, a=radius, e=0.0, varpi=angle, M0=0.0, direction=1)


def hyperbola_through(mu, periapsis_radius, velocity, radius, outgoing):
    """
    The counter-clockwise hyperbola with the given periapsis whose velocity at
    distance `radius` is `velocity` -- leaving (outgoing) or arriving. Its
    periapsis is at t0 = 0; returns the conic and the true anomaly at `radius`.

    Used at a sphere of influence: the velocity the leg outside needs there
    fixes the hyperbola's energy (its v_inf) and its orientation.
    """
    vx, vy = velocity
    v_inf_sq = vx * vx + vy * vy - 2.0 * mu / radius
    if v_inf_sq <= 0.0:
        raise ValueError("too slow to reach that distance on a hyperbola")
    e = 1.0 + periapsis_radius * v_inf_sq / mu
    a = -mu / v_inf_sq
    semi_latus = -a * (e * e - 1.0)
    nu = math.acos(max(-1.0, min(1.0, (semi_latus / radius - 1.0) / e)))
    if not outgoing:
        nu = -nu
    # flight-path angle: the velocity leans this far off the local horizontal
    gamma = math.atan2(e * math.sin(nu), 1.0 + e * math.cos(nu))
    varpi = math.atan2(vy, vx) - nu - math.pi / 2.0 + gamma
    return Conic(mu=mu, t0=0.0, a=a, e=e, varpi=varpi, M0=0.0, direction=1), nu
