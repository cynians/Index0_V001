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
from ui.ui_manager import UIManager


class App(SimWindow):
    """
    Main application entry point.

    Responsibilities:
    * manage tabs
    * route update / draw / input
    * bridge UI events to the active simulation
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
        self.ui_manager = UIManager()

        active_sim = self.get_active_simulation()
        self.camera_controller.setup_for_sim(active_sim)

    def get_active_simulation(self):
        tab = self.tab_manager.get_active()

        if tab:
            return tab.sim_instance.simulation

        return None

    def _open_region_map_tab(self, entity_id):
        """
        Open a new map simulation tab rooted at the selected entity.
        """
        if not entity_id:
            return

        entity = self.world_model.get_entity(entity_id)
        if not entity:
            return

        from world.simulation_context import SimulationContext

        active_sim = self.get_active_simulation()
        year = getattr(active_sim, "year", 2400)

        context = SimulationContext(
            year=year,
            root_entity_id=entity_id,
            world_model=self.world_model
        )

        new_map_sim = MapSimulation(context)
        new_tab = Tab(
            SimulationInstance(new_map_sim),
            name=f"Map: {entity.get('name', entity_id)}"
        )

        self.tab_manager.add_tab(new_tab)
        self.tab_manager.active_index = len(self.tab_manager.tabs) - 1
        self.camera_controller.setup_for_sim(new_map_sim)

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

        active_sim = self.get_active_simulation()
        self.ui_manager.rebuild_for_state(active_sim, self.width, self.height)

        action_id = self.ui_manager.handle_event(event)
        if action_id is not None:
            if action_id == "open_region_map" and active_sim is not None:
                selected_entity_id = getattr(active_sim, "selected_entity_id", None)
                self._open_region_map_tab(selected_entity_id)
            return

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 2:
            if active_sim is not None:
                self.camera_controller.setup_for_sim(active_sim)
            return

        if active_sim and hasattr(active_sim, "handle_pointer_event"):
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                active_sim.handle_pointer_event(
                    event=event,
                    camera=self.camera,
                    screen_pos=event.pos
                )

    def draw(self):
        super().draw_background()

        active_sim = self.get_active_simulation()
        self.ui_manager.rebuild_for_state(active_sim, self.width, self.height)

        if active_sim:
            self.renderer.simulation = active_sim
            self.renderer.draw(self.screen)

        self.ui_manager.draw(self.screen, self.default_font)


def main():
    app = App()
    app.run()


if __name__ == "__main__":
    main()