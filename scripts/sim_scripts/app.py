import pygame

from scripts.sim_core.window import SimWindow
from scripts.sim_core.tab_manager import TabManager
from scripts.sim_core.simulation_instance import SimulationInstance
from scripts.sim_core.tab import Tab
from scripts.sim_scripts.space_simulation import SpaceSimulation
from scripts.sim_core.renderer import Renderer


class App(SimWindow):
    """
    Main application entry point.

    Responsibilities:
    * manage tabs
    * route update / draw / input
    """

    def __init__(self):

        super().__init__(
            width=1200,
            height=800,
            title="Index_0"
        )

        # --------------------------------------------------
        # Camera
        # --------------------------------------------------

        self.camera.zoom = 1e-9

        # --------------------------------------------------
        # Tab system
        # --------------------------------------------------

        self.tab_manager = TabManager()

        sim1 = SimulationInstance(SpaceSimulation())
        sim2 = SimulationInstance(SpaceSimulation())

        self.tab_manager.add_tab(Tab(sim1, name="Sim A"))
        self.tab_manager.add_tab(Tab(sim2, name="Sim B"))

        # --------------------------------------------------
        # Renderer
        # --------------------------------------------------

        self.renderer = Renderer(self)

    # --------------------------------------------------

    def get_active_simulation(self):

        tab = self.tab_manager.get_active()
        if tab:
            return tab.sim_instance.simulation
        return None

    # --------------------------------------------------

    def update(self, dt):

        self.tab_manager.update(dt)

    # --------------------------------------------------

    def handle_event(self, event):

        if event.type == pygame.KEYDOWN:

            # switch tab
            if event.key == pygame.K_TAB:
                self.tab_manager.switch_next()

            # time controls (temporary global)
            sim = self.get_active_simulation()
            if sim:

                if event.key in (pygame.K_EQUALS, pygame.K_PLUS, pygame.K_KP_PLUS):
                    sim.sim_clock.set_time_scale(sim.sim_clock.time_scale + 0.25)

                elif event.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
                    sim.sim_clock.set_time_scale(sim.sim_clock.time_scale - 0.25)

                elif event.key == pygame.K_0:
                    sim.sim_clock.set_time_scale(1.0)

                elif event.key == pygame.K_SPACE:
                    sim.sim_clock.toggle_pause()

        # forward event to active tab
        self.tab_manager.handle_event(event)

    # --------------------------------------------------

    def draw(self):

        super().draw_background()

        active_sim = self.get_active_simulation()

        if active_sim:
            self.renderer.simulation = active_sim
            self.renderer.draw(self.screen)

def main():
    app = App()
    app.run()


if __name__ == "__main__":
    main()