import math
import pygame

from engine.camera import Camera
from engine.input_controller import InputController


class SimWindow:
    """
    Base simulation window with camera, adaptive grid, and UI support.
    """

    def __init__(self, width=1200, height=800, title="Simulation"):

        pygame.init()

        display_info = pygame.display.Info()
        self.width = display_info.current_w
        self.height = display_info.current_h

        self.screen = pygame.display.set_mode((self.width, self.height), pygame.NOFRAME)
        pygame.display.set_caption(title)

        self.clock = pygame.time.Clock()
        self.running = True

        self.camera = Camera(self.width, self.height)
        self.input_controller = InputController(self.camera, self)

        self.show_grid = True
        self.show_fps = True

        self.default_font = pygame.font.SysFont("consolas", 16)

    # --------------------------------------------------
    # MAIN LOOP
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
    # GRID / SCALE HELPERS
    # --------------------------------------------------

    def _visible_world_rect(self):
        """
        Return the currently visible world rectangle.
        """
        top_left = self.camera.screen_to_world((0, 0))
        bottom_right = self.camera.screen_to_world((self.width, self.height))

        min_x = min(top_left[0], bottom_right[0])
        max_x = max(top_left[0], bottom_right[0])
        min_y = min(top_left[1], bottom_right[1])
        max_y = max(top_left[1], bottom_right[1])

        return min_x, max_x, min_y, max_y

    def _nice_step(self, raw_value):
        """
        Snap a raw value to a 1/2/5 * 10^n step.
        """
        raw_value = abs(float(raw_value))

        if raw_value <= 0 or not math.isfinite(raw_value):
            return 1.0

        exponent = math.floor(math.log10(raw_value))
        fraction = raw_value / (10 ** exponent)

        if fraction < 1.5:
            nice_fraction = 1.0
        elif fraction < 3.5:
            nice_fraction = 2.0
        elif fraction < 7.5:
            nice_fraction = 5.0
        else:
            nice_fraction = 10.0

        return nice_fraction * (10 ** exponent)

    def _grid_spacing_world(self):
        """
        Choose a grid spacing that stays readable on screen while scaling by powers of ten.
        """
        target_pixels = 110.0
        raw_world_spacing = target_pixels / max(self.camera.zoom, 1e-18)
        return self._nice_step(raw_world_spacing)

    def _get_world_units_to_meters(self):
        """
        Ask the owning app for the current world-unit conversion.
        Defaults to 1 meter per world unit.
        """
        if hasattr(self, "get_world_units_to_meters"):
            return float(self.get_world_units_to_meters())

        return 1.0

    def _format_world_distance(self, value):
        """
        Format a world-space distance into a readable label using the current
        simulation's unit conversion.
        """
        meters_per_world_unit = self._get_world_units_to_meters()
        value_m = abs(float(value)) * meters_per_world_unit

        if value_m >= 149_597_870_700:
            return f"{value_m / 149_597_870_700:.2f} AU"

        if value_m >= 1_000_000_000:
            return f"{value_m / 1_000_000_000:.1f} Gm"

        if value_m >= 1_000_000:
            return f"{value_m / 1_000_000:.1f} Mm"

        if value_m >= 1000:
            if value_m >= 100_000:
                return f"{value_m / 1000:.0f} km"
            if value_m >= 10_000:
                return f"{value_m / 1000:.1f} km"
            return f"{value_m / 1000:.2f} km"

        if value_m >= 1:
            return f"{value_m:.0f} m"

        if value_m >= 0.01:
            return f"{value_m * 100:.0f} cm"

        return f"{value_m * 1000:.0f} mm"

    def _draw_scale_bar(self):
        """
        Draw a lower-right map-style scale bar for the current zoom level.
        """
        target_px = 160.0
        world_length = self._nice_step(target_px / max(self.camera.zoom, 1e-18))
        pixel_length = int(round(world_length * self.camera.zoom))

        if pixel_length < 40:
            return

        margin = 18
        bar_height = 10
        x2 = self.width - margin
        x1 = x2 - pixel_length
        y = self.height - margin

        label = self._format_world_distance(world_length)
        label_surface = self.default_font.render(label, True, (230, 230, 230))
        label_rect = label_surface.get_rect(midbottom=((x1 + x2) // 2, y - 8))

        bg_rect = pygame.Rect(
            label_rect.x - 8,
            label_rect.y - 4,
            label_rect.width + 16,
            label_rect.height + 8
        )
        pygame.draw.rect(self.screen, (10, 10, 10), bg_rect)
        pygame.draw.rect(self.screen, (90, 90, 90), bg_rect, 1)

        self.screen.blit(label_surface, label_rect.topleft)

        pygame.draw.line(self.screen, (235, 235, 235), (x1, y), (x2, y), 2)
        pygame.draw.line(self.screen, (235, 235, 235), (x1, y - bar_height), (x1, y + 1), 2)
        pygame.draw.line(self.screen, (235, 235, 235), (x2, y - bar_height), (x2, y + 1), 2)

        midpoint = (x1 + x2) // 2
        pygame.draw.line(self.screen, (180, 180, 180), (midpoint, y - 6), (midpoint, y + 1), 1)

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
        """
        Draw only the adaptive zoom-scaled grid.
        """

        if not self.show_grid:
            return

        spacing_world = self._grid_spacing_world()
        major_every = 5

        min_x, max_x, min_y, max_y = self._visible_world_rect()

        start_x_minor = math.floor(min_x / spacing_world) * spacing_world
        end_x_minor = math.ceil(max_x / spacing_world) * spacing_world

        start_y_minor = math.floor(min_y / spacing_world) * spacing_world
        end_y_minor = math.ceil(max_y / spacing_world) * spacing_world

        minor_color = (32, 32, 32)
        major_color = (52, 52, 52)
        axis_color = (78, 78, 78)

        index = 0
        x = start_x_minor
        while x <= end_x_minor + (spacing_world * 0.5):
            p1 = self.camera.world_to_screen((x, min_y))
            p2 = self.camera.world_to_screen((x, max_y))

            if p1 and p2:
                color = minor_color
                if abs(x) < spacing_world * 0.5:
                    color = axis_color
                elif index % major_every == 0:
                    color = major_color

                pygame.draw.line(self.screen, color, p1, p2)

            x += spacing_world
            index += 1

        index = 0
        y = start_y_minor
        while y <= end_y_minor + (spacing_world * 0.5):
            p1 = self.camera.world_to_screen((min_x, y))
            p2 = self.camera.world_to_screen((max_x, y))

            if p1 and p2:
                color = minor_color
                if abs(y) < spacing_world * 0.5:
                    color = axis_color
                elif index % major_every == 0:
                    color = major_color

                pygame.draw.line(self.screen, color, p1, p2)

            y += spacing_world
            index += 1

    def draw_world(self):
        """Override in subclass."""
        pass

    def draw_ui(self):
        """Basic UI (FPS + scale overlay)."""

        self._draw_scale_bar()

        if self.show_fps:
            fps = int(self.clock.get_fps())
            text = self.default_font.render(f"FPS: {fps}", True, (200, 200, 200))
            self.screen.blit(text, (10, 10))