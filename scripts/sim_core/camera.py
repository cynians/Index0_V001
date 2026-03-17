import pygame


class Camera:
    """
    Infinite-scale 2D camera.

    World units are meters.

    Supports:
    - smooth exponential zoom
    - planetary scale navigation
    - stable panning at any zoom level
    """

    def __init__(self, width, height):

        self.width = width
        self.height = height

        # world center position
        self.x = 0.0
        self.y = 0.0

        # zoom = pixels per meter
        self.zoom = 0.001

        # extremely wide bounds
        self.min_zoom = 1e-9
        self.max_zoom = 1e6

    # --------------------------------------------------
    # Movement
    # --------------------------------------------------

    def move(self, dx, dy):

        self.x += dx
        self.y += dy

    # --------------------------------------------------
    # Zoom (multiplicative)
    # --------------------------------------------------

    def change_zoom(self, factor):

        self.zoom *= factor

        if self.zoom < self.min_zoom:
            self.zoom = self.min_zoom

        if self.zoom > self.max_zoom:
            self.zoom = self.max_zoom

    # --------------------------------------------------
    # Transform
    # --------------------------------------------------

    def world_to_screen(self, pos):

        wx, wy = pos

        sx = (wx - self.x) * self.zoom + self.width / 2
        sy = (wy - self.y) * self.zoom + self.height / 2

        return int(sx), int(sy)

    # --------------------------------------------------
    # Input handling
    # --------------------------------------------------

    def handle_event(self, event):

        if event.type == pygame.KEYDOWN:

            # movement speed adapts to zoom
            speed = 200 / self.zoom

            if event.key == pygame.K_w:
                self.move(0, -speed)

            if event.key == pygame.K_s:
                self.move(0, speed)

            if event.key == pygame.K_a:
                self.move(-speed, 0)

            if event.key == pygame.K_d:
                self.move(speed, 0)

            # exponential zoom
            if event.key == pygame.K_q:
                self.change_zoom(0.8)

            if event.key == pygame.K_e:
                self.change_zoom(1.25)