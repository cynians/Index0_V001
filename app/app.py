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

        self._draw_startup_loading_screen(0.08, "Opening workspace")
        self.camera_controller = CameraController(
            self.camera,
            self.width,
            self.height
        )

        self._draw_startup_loading_screen(0.22, "Preparing tabs")
        self.tab_manager = TabManager()
        self._draw_startup_loading_screen(0.34, "Loading world repository")
        self.world_model = WorldModel()
        self._draw_startup_loading_screen(0.64, "Preparing renderer")
        self.renderer = Renderer(self)
        self._draw_startup_loading_screen(0.74, "Preparing cards and browser")
        self.ui_manager = UIManager()
        self._draw_startup_loading_screen(0.84, "Preparing navigation")
        self.navigation = NavigationController(self)
        self._draw_startup_loading_screen(0.92, "Preparing input")
        self.input_router = InputRouter(self)

        self.knowledge_layer_active = True
        self.system_menu_active = False
        self.system_settings_active = False
        self.repository_return_confirm_active = False
        self.repository_scope_entity_id = None
        self.parent_assignment_request = None
        self._draw_startup_loading_screen(1.0, "Ready")

    def _draw_startup_loading_screen(self, progress, message):
        """
        Draw a synchronous startup screen between initialization steps.
        """
        progress = max(0.0, min(1.0, float(progress or 0.0)))
        pygame.event.pump()

        self.screen.fill((9, 11, 16))
        center_x = self.width // 2
        center_y = self.height // 2

        title_font = pygame.font.SysFont("consolas", 56, bold=True)
        subtitle_font = pygame.font.SysFont("consolas", 18)
        small_font = pygame.font.SysFont("consolas", 14)

        title_surface = title_font.render("Index 0", True, (238, 242, 248))
        subtitle_surface = subtitle_font.render("Initializing program", True, (166, 183, 204))
        message_surface = small_font.render(str(message or "Initializing"), True, (202, 214, 228))

        self.screen.blit(title_surface, title_surface.get_rect(center=(center_x, center_y - 92)))
        self.screen.blit(subtitle_surface, subtitle_surface.get_rect(center=(center_x, center_y - 44)))

        bar_w = min(520, max(280, self.width // 3))
        bar_h = 16
        bar_rect = pygame.Rect(center_x - bar_w // 2, center_y + 8, bar_w, bar_h)
        fill_rect = pygame.Rect(bar_rect.x + 2, bar_rect.y + 2, int((bar_w - 4) * progress), bar_h - 4)

        pygame.draw.rect(self.screen, (24, 30, 42), bar_rect)
        pygame.draw.rect(self.screen, (92, 112, 142), bar_rect, 1)
        if fill_rect.width > 0:
            pygame.draw.rect(self.screen, (128, 176, 220), fill_rect)

        percent_surface = small_font.render(f"{int(round(progress * 100))}%", True, (176, 196, 218))
        self.screen.blit(percent_surface, percent_surface.get_rect(midleft=(bar_rect.right + 14, bar_rect.centery)))
        self.screen.blit(message_surface, message_surface.get_rect(center=(center_x, center_y + 52)))

        pygame.display.flip()

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
            parent_assignment_request=self.parent_assignment_request,
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
