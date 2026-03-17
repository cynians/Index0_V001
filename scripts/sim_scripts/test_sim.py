import os
import sys
import pygame

from scripts.sim_core.renderer import Renderer

# --------------------------------------------------
# Import path setup
# --------------------------------------------------

THIS_DIR = os.path.dirname(__file__)
SCRIPTS_DIR = os.path.abspath(os.path.join(THIS_DIR, ".."))
PROJECT_ROOT = os.path.abspath(os.path.join(THIS_DIR, "..", ".."))

if SCRIPTS_DIR not in sys.path:
    sys.path.append(SCRIPTS_DIR)

if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from scripts.sim_core.window import SimWindow
from scripts.sim_scripts.space_simulation import SpaceSimulation


class TestSimulation(SimWindow):

    def __init__(self):

        super().__init__(
            width=1200,
            height=800,
            title="Index_0 Test Simulation"
        )

        # --------------------------------------------------
        # Simulation (PURE LOGIC)
        # --------------------------------------------------

        self.simulation = SpaceSimulation()

        # --------------------------------------------------
        # Camera setup
        # --------------------------------------------------

        self.camera.zoom = 1e-9

        # --------------------------------------------------
        # Renderer
        # --------------------------------------------------

        self.renderer = Renderer(self)

    # --------------------------------------------------
    # Update
    # --------------------------------------------------

    def update(self, dt):
        self.simulation.update(dt)

    # --------------------------------------------------
    # Input (temporary, will move later)
    # --------------------------------------------------

    def handle_event(self, event):

        if event.type == pygame.KEYDOWN:

            if event.key in (pygame.K_EQUALS, pygame.K_PLUS, pygame.K_KP_PLUS):
                self.simulation.sim_clock.set_time_scale(
                    self.simulation.sim_clock.time_scale + 0.25
                )

            elif event.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
                self.simulation.sim_clock.set_time_scale(
                    self.simulation.sim_clock.time_scale - 0.25
                )

            elif event.key == pygame.K_0:
                self.simulation.sim_clock.set_time_scale(1.0)

            elif event.key == pygame.K_SPACE:
                self.simulation.sim_clock.toggle_pause()

    # --------------------------------------------------
    # Draw
    # --------------------------------------------------

    def draw(self):
        super().draw_background()
        self.renderer.draw(self.screen)


def main():

    sim = TestSimulation()
    sim.run()


if __name__ == "__main__":
    main()