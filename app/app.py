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
        self.system_menu_active = False
        self.system_settings_active = False
        self.repository_return_confirm_active = False
        self.repository_scope_entity_id = None

    def get_active_simulation(self):
        if self.knowledge_layer_active:
            return None

        tab = self.tab_manager.get_active()

        if tab:
            return tab.sim_instance.simulation

        return None

    def consumes_global_keydown(self):
        active_sim = self.get_active_simulation()
        return bool(
            active_sim is not None
            and getattr(active_sim, "consumes_global_keydown", lambda: False)()
        )

    def _update_frame(self, dt):
        if not self.consumes_global_keydown():
            self.camera.update(dt)
        self.update(dt)

    def get_world_units_to_meters(self):
        """
        Return the active simulation's world-unit conversion for scale labels.
        """
        active_sim = self.get_active_simulation()

        if active_sim is None:
            return 1.0

        return getattr(active_sim, "world_units_to_meters", 1.0)

    def update(self, dt):
        if self.system_menu_active:
            return

        if self.knowledge_layer_active:
            return

        self.tab_manager.update(dt)

        sim = self.get_active_simulation()
        if sim is not None and getattr(sim, "request_close_tab", False):
            self.tab_manager.close_active()
            if not self.tab_manager.tabs:
                self.knowledge_layer_active = True
                self.repository_return_confirm_active = False
                return
            sim = self.get_active_simulation()
            self.camera_controller.setup_for_sim(sim)
            self.repository_return_confirm_active = False

        self.camera_controller.apply_constraints(sim)

    def handle_event(self, event):
        self.input_router.route_event(event)

    def handle_pre_camera_event(self, event):
        active_sim = self.get_active_simulation()
        if active_sim is None:
            return False
        handler = getattr(active_sim, "handle_pre_camera_event", None)
        if handler is None:
            return False
        return bool(handler(event))

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
            system_menu_active=self.system_menu_active,
            system_settings_active=self.system_settings_active,
            repository_return_confirm_active=self.repository_return_confirm_active,
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
