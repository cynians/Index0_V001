from simulations.space.orbit import KeplerOrbit, DynamicOrbit


class SpaceObject:
    def __init__(self, name, mass=0.0, orbit=None, position=(0.0, 0.0)):
        """
        Generic space object.

        Parameters
        ----------
        name : str
            Object identifier.
        mass : float
            Object mass in kg. Used as gravitational source.
        orbit : KeplerOrbit | DynamicOrbit | None
            Orbit model for this object.
        position : tuple[float, float]
            Initial world position if no orbit is assigned.

        Notes
        -----
        For Kepler orbits, parent/child hierarchy is inferred automatically
        from orbit.parent.
        """
        self.name = name
        self.mass = mass
        self.orbit = orbit

        self.position = [float(position[0]), float(position[1])]

        self.parent = None
        self.children = []

        self._bind_orbit_hierarchy()

    def _bind_orbit_hierarchy(self):
        """
        Bind parent/child hierarchy from the current orbit, if applicable.
        """

        if isinstance(self.orbit, KeplerOrbit):
            self.parent = self.orbit.parent

            if self.parent is not None and self not in self.parent.children:
                self.parent.children.append(self)

    def set_orbit(self, orbit):
        """
        Assign a new orbit and refresh hierarchy bindings.
        """

        if self.parent is not None and self in self.parent.children:
            self.parent.children.remove(self)

        self.orbit = orbit
        self.parent = None

        self._bind_orbit_hierarchy()

    def is_orbiting(self):
        """
        Return True if this object is orbiting another object.
        """

        return self.parent is not None

    def update(self, dt, attractors=None):
        """
        Update object position.

        Parameters
        ----------
        dt : float
            Simulation timestep in seconds.
        attractors : list[SpaceObject] | None
            Massive bodies affecting dynamic orbits.
        """

        if self.orbit is None:
            return

        if isinstance(self.orbit, KeplerOrbit):
            self.orbit.update(dt)
            self.position = list(self.orbit.get_position())
            return

        if isinstance(self.orbit, DynamicOrbit):
            if attractors is None:
                attractors = []

            self.orbit.update(dt, attractors)
            self.position = list(self.orbit.get_position())
            return

    def get_position(self):
        return tuple(self.position)