import math


G = 6.67430e-11  # gravitational constant


# --------------------------------------------------
# Kepler Orbit (analytical)
# --------------------------------------------------

class KeplerOrbit:
    def __init__(self, parent, a, e=0.0, mu=None, M0=0.0, varpi=0.0, t=0.0):
        """
        parent : SpaceObject
        a      : semi-major axis (meters)
        e      : eccentricity
        mu     : gravitational parameter (G * M_parent)
        M0     : mean anomaly at epoch
        varpi  : longitude of periapsis (radians), the planar stand-in for
                 ascending node + argument of periapsis
        t      : seconds since epoch (world/interplanetary_calendar.py)
        """
        self.parent = parent
        self.a = a
        self.e = e
        self.M0 = M0
        self.varpi = varpi
        self.t = float(t)

        if mu is None:
            self.mu = G * parent.mass
        else:
            self.mu = mu

        # mean motion
        self.n = math.sqrt(self.mu / (a ** 3))
        self.M = self.mean_anomaly_at(self.t)

    def mean_anomaly_at(self, t):
        # From absolute time rather than accumulated, so any date can be read.
        return (self.M0 + self.n * t) % (2 * math.pi)

    def set_time(self, t):
        self.t = float(t)
        self.M = self.mean_anomaly_at(self.t)

    def update(self, dt):
        self.set_time(self.t + dt)

    def state_at(self, t):
        """
        Position and velocity relative to the parent at seconds since epoch t.
        """
        E = self._solve_kepler(self.mean_anomaly_at(t), self.e)

        cos_E = math.cos(E)
        sin_E = math.sin(E)
        b = self.a * math.sqrt(1 - self.e ** 2)

        # perifocal frame: periapsis along +x
        x = self.a * (cos_E - self.e)
        y = b * sin_E
        rate = self.n / (1 - self.e * cos_E)
        vx = -self.a * rate * sin_E
        vy = b * rate * cos_E

        return self._rotate(x, y), self._rotate(vx, vy)

    def get_position(self):
        (x, y), _ = self.state_at(self.t)

        # offset by parent
        px, py = self.parent.position
        return px + x, py + y

    def get_path_points(self, num_points=120):
        """
        Returns world-space points along the orbital path.
        """

        points = []
        b = self.a * math.sqrt(1 - self.e ** 2)
        px, py = self.parent.position

        for i in range(num_points):
            # evenly spaced in eccentric anomaly, which traces the ellipse exactly
            E = (i / num_points) * 2 * math.pi

            x, y = self._rotate(self.a * (math.cos(E) - self.e), b * math.sin(E))
            points.append((px + x, py + y))

        return points

    def _rotate(self, x, y):
        cos_w = math.cos(self.varpi)
        sin_w = math.sin(self.varpi)
        return cos_w * x - sin_w * y, sin_w * x + cos_w * y

    def _solve_kepler(self, M, e, tol=1e-6, max_iter=50):
        E = M if e < 0.8 else math.pi

        for _ in range(max_iter):
            f = E - e * math.sin(E) - M
            f_prime = 1 - e * math.cos(E)

            delta = f / f_prime
            E -= delta

            if abs(delta) < tol:
                break

        return E


# --------------------------------------------------
# Dynamic Orbit (physics-based)
# --------------------------------------------------

class DynamicOrbit:
    def __init__(self, position, velocity, mass=1.0):
        """
        position : (x, y)
        velocity : (vx, vy)
        mass     : object mass
        """
        self.position = list(position)
        self.velocity = list(velocity)
        self.mass = mass

    def update(self, dt, attractors):
        """
        attractors : list of SpaceObject (with mass + position)
        """
        ax = 0.0
        ay = 0.0

        for body in attractors:
            dx = body.position[0] - self.position[0]
            dy = body.position[1] - self.position[1]

            r2 = dx * dx + dy * dy
            if r2 == 0:
                continue

            r = math.sqrt(r2)

            a = G * body.mass / r2

            ax += a * dx / r
            ay += a * dy / r

        # semi-implicit Euler
        self.velocity[0] += ax * dt
        self.velocity[1] += ay * dt

        self.position[0] += self.velocity[0] * dt
        self.position[1] += self.velocity[1] * dt

    def get_position(self):
        return tuple(self.position)