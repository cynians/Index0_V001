import pygame
import math
from sim_core.camera import Camera


class SimWindow:
    """
    Minimal shared pygame window base for simulations.

    Provides:
    - pygame setup
    - main loop
    - camera
    - adaptive world grid
    - optional debug info
    - update/draw hooks
    """

    def __init__(self, width=1200, height=800, title="Simulation"):

        pygame.init()
        pygame.font.init()

        self.width = width
        self.height = height
        self.title = title

        self.screen = pygame.display.set_mode((self.width, self.height))
        pygame.display.set_caption(self.title)

        self.clock = pygame.time.Clock()
        self.running = True

        self.default_font = pygame.font.SysFont("consolas", 20)

        # --------------------------------------------------
        # Camera
        # --------------------------------------------------

        self.camera = Camera(self.width, self.height)

        # --------------------------------------------------
        # Background color
        # --------------------------------------------------

        self.background_color = (0, 0, 0)

        # --------------------------------------------------
        # Debug toggles
        # --------------------------------------------------

        self.show_grid = True
        self.show_fps = False

        # --------------------------------------------------
        # Screen center
        # --------------------------------------------------

        self.center_x = self.width // 2
        self.center_y = self.height // 2

    # --------------------------------------------------
    # Hooks for simulations
    # --------------------------------------------------

    def update(self, dt):
        pass

    def draw(self):

        self.screen.fill(self.background_color)

        if self.show_grid:
            self.draw_grid()

        self.draw_origin()

        if self.show_fps:
            self.draw_fps()

    def handle_event(self, event):
        pass

    # --------------------------------------------------
    # Adaptive Grid
    # --------------------------------------------------

    def get_grid_spacing(self):
        """
        Determines grid spacing based on zoom so that
        grid density remains stable.
        """

        pixels_per_meter = self.camera.zoom

        target_pixels = 120

        meters = target_pixels / pixels_per_meter

        exponent = math.floor(math.log10(meters))
        base = 10 ** exponent

        for mult in [1, 2, 5, 10]:
            step = base * mult
            if step >= meters:
                return step

        return base * 10

    def draw_grid(self):

        minor_step = self.get_grid_spacing()
        major_step = minor_step * 5

        color_minor = (40, 40, 40)
        color_major = (80, 80, 80)

        left = self.camera.x - (self.width / 2) / self.camera.zoom
        right = self.camera.x + (self.width / 2) / self.camera.zoom
        top = self.camera.y - (self.height / 2) / self.camera.zoom
        bottom = self.camera.y + (self.height / 2) / self.camera.zoom

        # vertical lines
        start_x = int(left // minor_step) * minor_step
        end_x = int(right // minor_step) * minor_step

        x = start_x
        while x <= end_x:

            p1 = self.camera.world_to_screen((x, top))
            p2 = self.camera.world_to_screen((x, bottom))

            if abs(x) % major_step < 1e-6:
                pygame.draw.line(self.screen, color_major, p1, p2, 2)

                # label major grid lines
                label = self.format_distance(x)
                text = self.default_font.render(label, True, (150, 150, 150))
                self.screen.blit(text, (p1[0] + 3, 3))

            else:
                pygame.draw.line(self.screen, color_minor, p1, p2, 1)

            x += minor_step

        # horizontal lines
        start_y = int(top // minor_step) * minor_step
        end_y = int(bottom // minor_step) * minor_step

        y = start_y
        while y <= end_y:

            p1 = self.camera.world_to_screen((left, y))
            p2 = self.camera.world_to_screen((right, y))

            if abs(y) % major_step < 1e-6:
                pygame.draw.line(self.screen, color_major, p1, p2, 2)

            else:
                pygame.draw.line(self.screen, color_minor, p1, p2, 1)

            y += minor_step

        self.draw_scale_indicator(minor_step)

    # --------------------------------------------------
    # Distance formatting
    # --------------------------------------------------

    def format_distance(self, meters):

        meters = abs(meters)

        if meters >= 1_000_000:
            return f"{meters/1_000_000:.0f}Mm"

        if meters >= 1000:
            return f"{meters/1000:.0f}km"

        return f"{meters:.0f}m"

    # --------------------------------------------------
    # Scale indicator
    # --------------------------------------------------

    def draw_scale_indicator(self, step):

        screen_length = step * self.camera.zoom

        if screen_length < 40:
            return

        x = 30
        y = self.height - 30

        pygame.draw.line(self.screen, (200,200,200), (x, y), (x + screen_length, y), 3)

        label = self.format_distance(step)

        text = self.default_font.render(label, True, (200,200,200))
        self.screen.blit(text, (x, y - 22))

    # --------------------------------------------------
    # Origin marker
    # --------------------------------------------------

    def draw_origin(self):

        pos = self.camera.world_to_screen((0, 0))

        pygame.draw.circle(self.screen, (200, 80, 80), pos, 6)

    # --------------------------------------------------
    # FPS display
    # --------------------------------------------------

    def draw_fps(self):

        fps = int(self.clock.get_fps())
        text = self.default_font.render(f"FPS {fps}", True, (180, 180, 180))
        self.screen.blit(text, (10, 10))

    # --------------------------------------------------
    # Main loop
    # --------------------------------------------------

    def run(self):

        while self.running:

            dt = self.clock.tick(60) / 1000.0

            for event in pygame.event.get():

                if event.type == pygame.QUIT:
                    self.running = False

                elif event.type == pygame.KEYDOWN:

                    if event.key == pygame.K_ESCAPE:
                        self.running = False

                    if event.key == pygame.K_g:
                        self.show_grid = not self.show_grid

                    if event.key == pygame.K_f:
                        self.show_fps = not self.show_fps

                self.camera.handle_event(event)
                self.handle_event(event)

            self.update(dt)

            self.draw()

            pygame.display.flip()

        pygame.quit()