from simulations.space.orbit import KeplerOrbit, DynamicOrbit


class SpaceObject:
    def __init__(self, name, mass=0.0, orbit=None, position=(0.0, 0.0), entity_id=None):
        """
        Generic space object.
        """

        self.name = name
        self.mass = mass
        self.orbit = orbit

        # --- IDENTITY ---
        self.entity_id = entity_id
        self.entity = None

        self.position = [float(position[0]), float(position[1])]

        self.parent = None
        self.children = []

        self._bind_orbit_hierarchy()

    def _bind_orbit_hierarchy(self):
        if isinstance(self.orbit, KeplerOrbit):
            self.parent = self.orbit.parent

            if self.parent is not None and self not in self.parent.children:
                self.parent.children.append(self)

    def set_orbit(self, orbit):
        if self.parent is not None and self in self.parent.children:
            self.parent.children.remove(self)

        self.orbit = orbit
        self.parent = None

        self._bind_orbit_hierarchy()

    def is_orbiting(self):
        return self.parent is not None

    def update(self, dt, attractors=None):
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