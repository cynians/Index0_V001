class SpaceObject:
    def __init__(self, name, mass=0.0, orbit=None, position=(0.0, 0.0)):
        """
        name     : string identifier
        mass     : used for gravity (kg)
        orbit    : KeplerOrbit or DynamicOrbit
        position : initial position (used if no orbit)
        """
        self.name = name
        self.mass = mass
        self.orbit = orbit

        self.position = list(position)

    def update(self, dt, attractors=None):
        """
        Update object position.

        dt          : timestep in seconds
        attractors  : list of massive bodies (for dynamic orbits)
        """

        if self.orbit is None:
            return

        # Kepler orbit (analytical)
        if hasattr(self.orbit, "parent"):
            self.orbit.update(dt)
            self.position = list(self.orbit.get_position())
            return

        # Dynamic orbit (physics-based)
        if attractors is None:
            attractors = []

        self.orbit.update(dt, attractors)
        self.position = list(self.orbit.get_position())

    def get_position(self):
        return tuple(self.position)