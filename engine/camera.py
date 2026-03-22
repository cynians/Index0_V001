import pygame
import math

class Camera:
    """
    Infinite-scale 2D camera.

    World units are meters.

    Improvements:
    - continuous movement (key hold)
    - frame-rate independent
    - cursor-centered zoom
    - smoother navigation feel
    """

    def __init__(self, width, height):

        self.width = width
        self.height = height

        # world center position
        self.x = 0.0
        self.y = 0.0

        # zoom = pixels per meter
        self.zoom = 0.001

        self.min_zoom = 1e-9
        self.max_zoom = 1e6

        # movement tuning
        self.base_speed = 300.0  # meters/sec at zoom=1

    # --------------------------------------------------
    # Movement
    # --------------------------------------------------

    def move(self, dx, dy):
        self.x += dx
        self.y += dy

    # --------------------------------------------------
    # Zoom (cursor centered)
    # --------------------------------------------------

    def change_zoom(self, factor, mouse_pos=None):

        if mouse_pos is None:
            mouse_pos = (self.width / 2, self.height / 2)

        mx, my = mouse_pos

        # world before zoom
        world_before = self.screen_to_world((mx, my))

        # apply zoom (clamped)
        new_zoom = self.zoom * factor
        new_zoom = max(self.min_zoom, min(self.max_zoom, new_zoom))

        # prevent tiny useless changes
        if abs(new_zoom - self.zoom) < 1e-15:
            return

        self.zoom = new_zoom

        # world after zoom
        world_after = self.screen_to_world((mx, my))

        # keep cursor anchored
        self.x += world_before[0] - world_after[0]
        self.y += world_before[1] - world_after[1]

    # --------------------------------------------------
    # Transform
    # --------------------------------------------------



    def world_to_screen(self, pos):

        wx, wy = pos

        # compute in float first
        sx = (wx - self.x) * self.zoom + self.width / 2
        sy = (wy - self.y) * self.zoom + self.height / 2

        # guard against invalid numbers
        if not (math.isfinite(sx) and math.isfinite(sy)):
            return None

        # guard against extreme overflow (pygame can't handle huge ints)
        if abs(sx) > 1e9 or abs(sy) > 1e9:
            return None

        return int(sx), int(sy)

    def screen_to_world(self, pos):

        sx, sy = pos

        wx = (sx - self.width / 2) / self.zoom + self.x
        wy = (sy - self.height / 2) / self.zoom + self.y

        return wx, wy

    # --------------------------------------------------
    # Continuous input (call every frame)
    # --------------------------------------------------

    def update(self, dt):

        keys = pygame.key.get_pressed()

        # movement speed scales with zoom
        speed = self.base_speed / self.zoom

        dx = 0.0
        dy = 0.0

        if keys[pygame.K_w]:
            dy -= speed * dt

        if keys[pygame.K_s]:
            dy += speed * dt

        if keys[pygame.K_a]:
            dx -= speed * dt

        if keys[pygame.K_d]:
            dx += speed * dt

        self.move(dx, dy)

    # --------------------------------------------------
    # Event handling
    # --------------------------------------------------

    def handle_event(self, event):

        # mouse wheel zoom (best UX)
        if event.type == pygame.MOUSEWHEEL:

            mouse_pos = pygame.mouse.get_pos()

            # smooth exponential scaling
            zoom_factor = 1.0 + (event.y * 0.15)

            if zoom_factor <= 0:
                zoom_factor = 0.1

            self.change_zoom(zoom_factor, mouse_pos)

        # keyboard fallback
        if event.type == pygame.KEYDOWN:

            mouse_pos = pygame.mouse.get_pos()

            if event.key == pygame.K_q:
                self.change_zoom(0.9, mouse_pos)

            if event.key == pygame.K_e:
                self.change_zoom(1.1, mouse_pos)