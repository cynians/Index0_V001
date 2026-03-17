class SpaceSimulation:
    """
    Pure simulation logic (no window, no pygame, no UI)
    """

    def __init__(self):

        from scripts.sim_core.clock import Clock
        from scripts.sim_core.space.system import CelestialSystem
        from scripts.sim_core.simulation_manager import SimulationManager
        from scripts.sim_core.space.object import SpaceObject
        from scripts.sim_core.space.orbit import KeplerOrbit
        from scripts.sim_core.locations.map_layers import MapLayerStack

        self.year = 2400

        self.sim_clock = Clock(base_dt=4.8)
        self.system = CelestialSystem()
        self.sim_manager = SimulationManager(self.sim_clock, self.system)

        # --------------------------
        # Sun
        # --------------------------

        self.sun = SpaceObject(
            name="sun",
            mass=1.989e30,
            position=(0.0, 0.0)
        )

        self.system.add(self.sun, name="sun", layers=None)

        # --------------------------
        # Earth
        # --------------------------

        earth_layers = MapLayerStack(22_585_000)

        self.earth = SpaceObject(
            name="earth",
            mass=5.972e24,
            orbit=KeplerOrbit(
                parent=self.sun,
                a=149_600_000_000,
                e=0.0167
            )
        )

        self.system.add(self.earth, name="earth", layers=earth_layers)

        # --------------------------
        # Moon
        # --------------------------

        moon_layers = MapLayerStack(6_159_000)

        self.moon = SpaceObject(
            name="moon",
            mass=7.342e22,
            orbit=KeplerOrbit(
                parent=self.earth,
                a=384_400_000,
                e=0.0549
            )
        )

        self.system.add(self.moon, name="moon", layers=moon_layers)

    # --------------------------------------------------

    def update(self, dt):
        self.sim_manager.update(dt)