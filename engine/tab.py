class Tab:
    """
    Represents a simulation session view.

    A tab points to:
    * a SimulationInstance
    * (future) a perspective (entity, camera focus, etc.)
    """

    def __init__(self, simulation_instance, name="Tab"):

        self.sim_instance = simulation_instance
        self.name = name
        self.active = True

    def update(self, dt):

        if self.active:
            self.sim_instance.update(dt)

    def draw(self):

        if self.active:
            self.sim_instance.draw()

    def handle_event(self, event):

        if self.active:
            self.sim_instance.handle_event(event)