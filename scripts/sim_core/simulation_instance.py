class SimulationInstance:
    """
    Wraps a simulation and provides a standard interface.

    Future responsibilities:
    * hold simulation state
    * manage event history
    * support pause/resume
    * enable switching between instances
    """

    def __init__(self, simulation):

        self.simulation = simulation
        self.active = True

    def update(self, dt):

        if not self.active:
            return

        self.simulation.update(dt)

    def draw(self):

        self.simulation.draw()

    def handle_event(self, event):

        if not self.active:
            return

        if hasattr(self.simulation, "handle_event"):
            self.simulation.handle_event(event)