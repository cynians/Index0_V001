class SpaceSimulation:
    """
    Pure simulation logic (no window, no pygame, no UI)
    """

    def __init__(self):
        from engine.clock import Clock
        from simulations.space.system import CelestialSystem
        from engine.simulation_manager import SimulationManager
        from simulations.space.object import SpaceObject
        from simulations.space.orbit import KeplerOrbit
        from simulations.map.map_layers import MapLayerStack

        self.render_mode = "space"

        self.year = 2400

        self.sim_clock = Clock(base_dt=4.8)
        self.system = CelestialSystem()
        self.sim_manager = SimulationManager(self.sim_clock, self.system)

        self.min_zoom = 1e-12
        self.max_zoom = 1e-6
        self.preferred_zoom = 4e-9

        self.sun = SpaceObject(
            name="sun",
            mass=1.989e30,
            position=(0.0, 0.0)
        )

        self.system.add(self.sun, name="sun", layers=None)

        earth_layers = MapLayerStack(22_585_000)
        earth_layers.add_layer({
            "name": "surface",
            "color": (90, 90, 90),
            "x": 0.0,
            "y": 0.0,
            "size": 12_742_000,
        })

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

        moon_layers = MapLayerStack(6_159_000)
        moon_layers.add_layer({
            "name": "surface",
            "color": (140, 140, 140),
            "x": 0.0,
            "y": 0.0,
            "size": 3_474_800,
        })

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

    def get_center(self):
        return 0.0, 0.0

    def update(self, dt):
        self.sim_manager.update(dt)