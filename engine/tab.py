class Tab:
    """
    Represents one application tab.

    A tab may either:
    * point to a SimulationInstance
    * or represent a non-simulation workspace such as the Knowledge Layer
    """

    def __init__(self, simulation_instance=None, name="Tab", tab_key=None):
        self.sim_instance = simulation_instance
        self.name = name
        self.tab_key = tab_key
        self.active = True

    def has_simulation(self):
        return self.sim_instance is not None

    def update(self, dt):
        if self.active and self.sim_instance is not None:
            self.sim_instance.update(dt)

    def draw(self):
        if self.active and self.sim_instance is not None:
            self.sim_instance.draw()

    def handle_event(self, event):
        if self.active and self.sim_instance is not None:
            self.sim_instance.handle_event(event)