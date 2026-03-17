import math


G = 6.67430e-11  # gravitational constant


# --------------------------------------------------
# Kepler Orbit (analytical)
# --------------------------------------------------

class KeplerOrbit:
    def __init__(self, parent, a, e=0.0, mu=None, M0=0.0):
        """
        parent : SpaceObject
        a      : semi-major axis (meters)
        e      : eccentricity
        mu     : gravitational parameter (G * M_parent)
        M0     : mean anomaly at epoch
        """
        self.parent = parent
        self.a = a
        self.e = e
        self.M = M0

        if mu is None:
            self.mu = G * parent.mass
        else:
            self.mu = mu

        # mean motion
        self.n = math.sqrt(self.mu / (a ** 3))

    def update(self, dt):
        # advance mean anomaly
        self.M += self.n * dt

        # keep in range
        self.M = self.M % (2 * math.pi)

    def get_position(self):
        # solve Kepler equation: M = E - e*sin(E)
        E = self._solve_kepler(self.M, self.e)

        # true anomaly
        cos_E = math.cos(E)
        sin_E = math.sin(E)

        x = self.a * (cos_E - self.e)
        y = self.a * math.sqrt(1 - self.e ** 2) * sin_E

        # offset by parent
        px, py = self.parent.position
        return px + x, py + y

    def get_path_points(self, num_points=120):
        """
        Returns world-space points along the orbital path.
        """

        points = []

        for i in range(num_points):
            t = (i / num_points) * 2 * math.pi

            # eccentric anomaly approximation
            E = t

            cos_E = math.cos(E)
            sin_E = math.sin(E)

            x = self.a * (cos_E - self.e)
            y = self.a * math.sqrt(1 - self.e ** 2) * sin_E

            # parent offset
            px, py = self.parent.position
            points.append((px + x, py + y))

        return points

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