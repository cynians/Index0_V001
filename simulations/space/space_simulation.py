class SpaceSimulation:
    """
    Pure simulation logic (no window, no pygame, no UI).

    This version loads the orbital system from world entries instead of
    hardcoding Sun / Earth / Moon directly in the simulation.
    """

    def __init__(self, world_model=None, root_system_id="system_sol", year=2400):
        from engine.clock import Clock
        from simulations.space.system import CelestialSystem
        from engine.simulation_manager import SimulationManager
        from world.world_model import WorldModel

        self.render_mode = "space"

        self.year = year
        self.root_system_id = root_system_id

        self.world_model = world_model if world_model is not None else WorldModel()

        self.sim_clock = Clock(base_dt=4.8)
        self.system = CelestialSystem()
        self.sim_manager = SimulationManager(self.sim_clock, self.system)

        self.min_zoom = 1e-13
        self.max_zoom = 1e-6
        self.preferred_zoom = 1.0e-10

        self.system.populate_from_world_model(
            world_model=self.world_model,
            year=self.year,
            root_system_id=self.root_system_id
        )

    def get_center(self):
        return 0.0, 0.0

    def update(self, dt):
        self.sim_manager.update(dt)

    def get_entity(self, space_object, world_model=None):
        """
        Resolve world entity from a space object.

        If no world_model is provided, use the simulation's own world model.
        """
        if space_object.entity_id is None:
            return None

        model = world_model if world_model is not None else self.world_model
        entity = model.get_entity(space_object.entity_id)
        space_object.entity = entity
        return entity