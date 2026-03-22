"""
clock.py

Central simulation clock.

Responsibilities:
* Maintain real-time accumulation
* Run simulation at fixed tick rate
* Advance simulation time per tick
* Handle time scaling and pause

Design:
* Fixed simulation step (e.g. 0.2s per tick)
* Variable simulation time per tick (scaled)
"""

class Clock:

    def __init__(self, base_dt=4.8, tick_interval=0.2):
        """
        Parameters
        ----------
        base_dt : float
            Simulation seconds per tick at time_scale = 1.0

        tick_interval : float
            Real-time seconds per simulation tick
        """

        # simulation state
        self.tick = 0
        self.time = 0.0

        # time control
        self.base_dt = base_dt
        self.time_scale = 1.0
        self.paused = False

        # fixed timestep system
        self.tick_interval = tick_interval
        self._accumulator = 0.0

    # --------------------------------------------------
    # Update (called every frame)
    # --------------------------------------------------

    def update(self, real_dt):
        """
        Accumulate real time.

        Parameters
        ----------
        real_dt : float
            Frame delta time (seconds)
        """

        if self.paused:
            return

        self._accumulator += real_dt

    # --------------------------------------------------
    # Step control
    # --------------------------------------------------

    def should_step(self):
        """
        Check if a simulation step should occur.
        """

        return (not self.paused) and (self._accumulator >= self.tick_interval)

    def consume_step(self):
        """
        Consume one simulation step and advance time.

        Returns
        -------
        float
            Simulation dt for this step
        """

        self._accumulator -= self.tick_interval

        sim_dt = self.get_dt()

        self.time += sim_dt
        self.tick += 1

        return sim_dt

    # --------------------------------------------------
    # Time scaling
    # --------------------------------------------------

    def get_dt(self):
        """
        Simulation time per tick.
        """

        return self.base_dt * self.time_scale

    # --------------------------------------------------
    # Controls
    # --------------------------------------------------

    def set_time_scale(self, scale):
        self.time_scale = max(0.0, min(scale, 1e9))

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False

    def toggle_pause(self):
        self.paused = not self.paused