import pygame

from scripts.sim_core.camera import Camera
from scripts.sim_core.input_controller import InputController


class SimWindow:
    """
    Base simulation window with camera, grid, and UI support.
    """

    def __init__(self, width=1200, height=800, title="Simulation"):

        pygame.init()

        self.width = width
        self.height = height

        self.screen = pygame.display.set_mode((width, height))
        pygame.display.set_caption(title)

        self.clock = pygame.time.Clock()
        self.running = True

        self.camera = Camera(width, height)
        self.input_controller = InputController(self.camera, self)

        self.show_grid = True
        self.show_fps = True

        self.default_font = pygame.font.SysFont("consolas", 16)

    # --------------------------------------------------
    # MAIN LOOP (refactored, no behavior change)
    # --------------------------------------------------

    def run(self):

        while self.running:

            dt = self._tick()

            self._process_events()
            self._update_frame(dt)
            self._render_frame()

        pygame.quit()

    # --------------------------------------------------
    # LOOP SUB-STEPS
    # --------------------------------------------------

    def _tick(self):
        """Frame timing."""
        return self.clock.tick(60) / 1000.0

    def _process_events(self):
        """Handle pygame events via InputController."""

        events = pygame.event.get()

        self.input_controller.process(events)

        # sync state back
        self.running = self.input_controller.running
        self.show_grid = self.input_controller.show_grid
        self.show_fps = self.input_controller.show_fps

    def _update_frame(self, dt):
        """Update simulation + camera."""

        self.camera.update(dt)
        self.update(dt)

    def _render_frame(self):
        """Render full frame."""

        self.screen.fill((0, 0, 0))

        self.draw()

        pygame.display.flip()

    # --------------------------------------------------
    # OVERRIDABLE METHODS
    # --------------------------------------------------

    def handle_event(self, event):
        """Override in subclass."""
        pass

    def update(self, dt):
        """Override in subclass."""
        pass

    def draw(self):
        """Main draw pipeline."""

        self.draw_background()
        self.draw_world()
        self.draw_ui()

    def draw_background(self):
        """Grid rendering."""

        if not self.show_grid:
            return

        grid_spacing = 100

        for x in range(-2000, 2000, grid_spacing):
            p1 = self.camera.world_to_screen((x, -2000))
            p2 = self.camera.world_to_screen((x, 2000))
            if p1 and p2:
                pygame.draw.line(self.screen, (40, 40, 40), p1, p2)

        for y in range(-2000, 2000, grid_spacing):
            p1 = self.camera.world_to_screen((-2000, y))
            p2 = self.camera.world_to_screen((2000, y))
            if p1 and p2:
                pygame.draw.line(self.screen, (40, 40, 40), p1, p2)

    def draw_world(self):
        """Override in subclass."""
        pass

    def draw_ui(self):
        """Basic UI (FPS)."""

        if self.show_fps:
            fps = int(self.clock.get_fps())
            text = self.default_font.render(f"FPS: {fps}", True, (200, 200, 200))
            self.screen.blit(text, (10, 10))