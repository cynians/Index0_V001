import pygame

from engine.window import SimWindow
from engine.tab_manager import TabManager
from engine.simulation_instance import SimulationInstance
from engine.tab import Tab
from simulations.space.space_simulation import SpaceSimulation
from simulations.map.map_simulation import MapSimulation
from engine.renderer import Renderer
from engine.camera_controller import CameraController
from world.world_model import WorldModel


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

        self.camera_controller = CameraController(
            self.camera,
            self.width,
            self.height
        )

        self.tab_manager = TabManager()
        self.world_model = WorldModel()

        from world.simulation_context import SimulationContext

        context = SimulationContext(
            year=2400,
            root_entity_id="planet_earth",
            world_model=self.world_model
        )

        sim1 = SimulationInstance(SpaceSimulation())
        sim2 = SimulationInstance(MapSimulation(context))

        self.tab_manager.add_tab(Tab(sim1, name="Space"))
        self.tab_manager.add_tab(Tab(sim2, name="Map"))

        self.renderer = Renderer(self)

        active_sim = self.get_active_simulation()
        self.camera_controller.setup_for_sim(active_sim)

    def get_active_simulation(self):
        tab = self.tab_manager.get_active()

        if tab:
            return tab.sim_instance.simulation

        return None

    def update(self, dt):
        self.tab_manager.update(dt)

        sim = self.get_active_simulation()
        self.camera_controller.apply_constraints(sim)

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_TAB:
                self.tab_manager.switch_next()

                sim = self.get_active_simulation()
                self.camera_controller.setup_for_sim(sim)

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

        self.tab_manager.handle_event(event)

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