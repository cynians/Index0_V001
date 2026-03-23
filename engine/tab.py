class Tab:
    """
    Represents a simulation session view.

    A tab points to:
    * a SimulationInstance
    * (future) a perspective (entity, camera focus, etc.)
    * a stable semantic key used to identify duplicate logical tabs
    """

    def __init__(self, simulation_instance, name="Tab", tab_key=None):
        self.sim_instance = simulation_instance
        self.name = name
        self.tab_key = tab_key
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