class SimulationManager:
    """
    Handles simulation time progression and system updates.

    Responsibilities:
    * Advance simulation clock
    * Step simulation in fixed increments
    * Update simulation systems
    """

    def __init__(self, clock, system):

        self.clock = clock
        self.system = system

    def update(self, dt):
        """Advance simulation state."""

        self.clock.update(dt)

        while self.clock.should_step():
            sim_dt = self.clock.consume_step()
            self.system.update(sim_dt)