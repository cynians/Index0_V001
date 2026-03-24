import pygame

from engine.window import SimWindow
from engine.tab_manager import TabManager
from engine.renderer import Renderer
from engine.camera_controller import CameraController
from world.world_model import WorldModel
from ui.ui_manager import UIManager
from navigation_controller import NavigationController
from input_router import InputRouter


class App(SimWindow):
    """
    Main application entry point.

    Responsibilities:
    * own global app state
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
        self.renderer = Renderer(self)
        self.ui_manager = UIManager()
        self.navigation = NavigationController(self)
        self.input_router = InputRouter(self)

        self.knowledge_layer_active = True
        self.repository_scope_entity_id = None

    def get_active_simulation(self):
        if self.knowledge_layer_active:
            return None

        tab = self.tab_manager.get_active()

        if tab:
            return tab.sim_instance.simulation

        return None

    def get_world_units_to_meters(self):
        """
        Return the active simulation's world-unit conversion for scale labels.
        """
        active_sim = self.get_active_simulation()

        if active_sim is None:
            return 1.0

        return getattr(active_sim, "world_units_to_meters", 1.0)

    def update(self, dt):
        if self.knowledge_layer_active:
            return

        self.tab_manager.update(dt)

        sim = self.get_active_simulation()
        self.camera_controller.apply_constraints(sim)

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN:
            self.navigation.handle_keydown(event)

        active_sim = self.get_active_simulation()

        self.ui_manager.rebuild_for_state(
            active_sim=active_sim,
            app_width=self.width,
            app_height=self.height,
            tab_manager=self.tab_manager,
            camera=self.camera,
            menu_active=self.knowledge_layer_active,
            world_model=self.world_model,
            repository_scope_entity_id=self.repository_scope_entity_id,
        )

        action_id = self.ui_manager.handle_event(event)
        if action_id == "__ui_consumed__":
            return

        if action_id is not None:
            handled = self.navigation.handle_ui_action(action_id, active_sim)
            if handled:
                return

        if self.knowledge_layer_active:
            return

        self.tab_manager.handle_event(event)

        active_sim = self.get_active_simulation()

        if self.input_router.handle_middle_click_reset(event, active_sim):
            return

        self.input_router.handle_pointer_input(event, active_sim)

    def draw(self):
        if not self.knowledge_layer_active:
            super().draw_background()

        active_sim = self.get_active_simulation()
        self.ui_manager.rebuild_for_state(
            active_sim=active_sim,
            app_width=self.width,
            app_height=self.height,
            tab_manager=self.tab_manager,
            camera=self.camera,
            menu_active=self.knowledge_layer_active,
            world_model=self.world_model,
            repository_scope_entity_id=self.repository_scope_entity_id,
        )

        if active_sim:
            self.renderer.simulation = active_sim
            self.renderer.draw(self.screen)

        super().draw_ui()
        self.ui_manager.draw(self.screen, self.default_font)


def main():
    app = App()
    app.run()


if __name__ == "__main__":
    main()