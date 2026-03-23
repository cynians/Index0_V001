import random

from engine.logger import logger


class WeatherController:
    """
    Prototype weather controller for the bioregion simulation.

    Current responsibility:
    * manage rain timing/state
    * expose current rain input rate to the simulation

    This is intentionally simple for now:
    * one map-wide rain state
    * periodic rain checks
    * fixed-duration rain events
    """

    def __init__(
        self,
        rain_check_period_seconds,
        rain_chance_per_check,
        rain_duration_seconds,
        rain_rate,
        start_raining=False,
    ):
        self.rain_check_period_seconds = rain_check_period_seconds
        self.rain_chance_per_check = rain_chance_per_check
        self.rain_duration_seconds = rain_duration_seconds
        self.rain_rate = rain_rate

        self.weather_check_timer = 0.0
        self.rain_timer = rain_duration_seconds if start_raining else 0.0
        self.is_raining = start_raining

    def update(self, dt):
        """
        Advance weather state by one step.
        """
        if self.is_raining:
            self.rain_timer -= dt
            if self.rain_timer <= 0.0:
                self.is_raining = False
                self.rain_timer = 0.0
                logger.info("[WeatherController] Rain event ended")
            return

        self.weather_check_timer += dt
        if self.weather_check_timer >= self.rain_check_period_seconds:
            self.weather_check_timer = 0.0

            rain_roll = random.random()
            logger.debug(
                f"[WeatherController] Rain check roll={rain_roll:.3f} "
                f"threshold={self.rain_chance_per_check:.3f}",
                key="bioregion_rain_check",
                interval=2.0
            )

            if rain_roll < self.rain_chance_per_check:
                self.is_raining = True
                self.rain_timer = self.rain_duration_seconds
                logger.info(
                    f"[WeatherController] Rain event started "
                    f"(duration={self.rain_duration_seconds:.1f}s, rate={self.rain_rate:.6f})"
                )

    def get_rain_input_rate(self):
        """
        Return the active rain input rate for the current step.
        """
        if self.is_raining:
            return self.rain_rate

        return 0.0