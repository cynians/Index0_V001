import pygame


class PersonRenderer:
    """Draw the first embodied person-control test room."""

    BACKGROUND = (10, 13, 18)
    FLOOR = (29, 34, 41)
    FLOOR_BORDER = (108, 121, 139)
    GRID = (42, 49, 59)
    TEXT = (226, 232, 239)

    def __init__(self, app_view):
        self.app_view = app_view
        self._text_cache = {}

    def _text(self, value, color=None):
        color = tuple(color or self.TEXT)
        key = (str(value), color)
        surface = self._text_cache.get(key)
        if surface is None:
            surface = self.app_view.default_font.render(str(value), True, color)
            self._text_cache[key] = surface
            if len(self._text_cache) > 256:
                self._text_cache.pop(next(iter(self._text_cache)))
        return surface

    def _world_rect(self, camera, min_x, min_y, max_x, max_y):
        top_left = camera.world_to_screen((min_x, min_y))
        bottom_right = camera.world_to_screen((max_x, max_y))
        if top_left is None or bottom_right is None:
            return None
        return pygame.Rect(
            min(top_left[0], bottom_right[0]),
            min(top_left[1], bottom_right[1]),
            abs(bottom_right[0] - top_left[0]),
            abs(bottom_right[1] - top_left[1]),
        )

    def _draw_floor(self, screen, camera, bounds):
        floor = self._world_rect(
            camera,
            bounds["min_x"],
            bounds["min_y"],
            bounds["max_x"],
            bounds["max_y"],
        )
        if floor is None:
            return
        pygame.draw.rect(screen, self.FLOOR, floor)
        pygame.draw.rect(screen, self.FLOOR_BORDER, floor, 2)

        for world_x in range(int(bounds["min_x"]) + 2, int(bounds["max_x"]), 2):
            start = camera.world_to_screen((world_x, bounds["min_y"]))
            end = camera.world_to_screen((world_x, bounds["max_y"]))
            if start is not None and end is not None:
                pygame.draw.line(screen, self.GRID, start, end, 1)
        for world_y in range(int(bounds["min_y"]) + 1, int(bounds["max_y"]), 2):
            start = camera.world_to_screen((bounds["min_x"], world_y))
            end = camera.world_to_screen((bounds["max_x"], world_y))
            if start is not None and end is not None:
                pygame.draw.line(screen, self.GRID, start, end, 1)

    def _draw_bed_icon(self, screen, center, color):
        x, y = center
        pygame.draw.rect(screen, color, (x - 22, y - 10, 44, 21), border_radius=3)
        pygame.draw.rect(screen, (225, 231, 238), (x - 18, y - 7, 12, 8), border_radius=2)
        pygame.draw.line(screen, (22, 25, 31), (x - 22, y + 12), (x - 22, y + 17), 3)
        pygame.draw.line(screen, (22, 25, 31), (x + 22, y + 12), (x + 22, y + 17), 3)

    def _draw_food_icon(self, screen, center, color):
        x, y = center
        pygame.draw.circle(screen, color, center, 18)
        pygame.draw.arc(screen, (236, 231, 212), (x - 13, y - 8, 26, 19), 0, 3.14, 3)
        pygame.draw.line(screen, (236, 231, 212), (x - 10, y + 7), (x + 10, y + 7), 3)

    def _draw_job_icon(self, screen, center, color):
        x, y = center
        pygame.draw.rect(screen, color, (x - 19, y - 16, 38, 32), border_radius=3)
        pygame.draw.rect(screen, (32, 38, 43), (x - 8, y - 22, 16, 10), 3, border_radius=3)
        pygame.draw.line(screen, (225, 231, 225), (x - 12, y), (x + 12, y), 3)

    def _draw_target_icon(self, screen, center, color):
        pygame.draw.circle(screen, color, center, 20)
        pygame.draw.circle(screen, (234, 224, 210), center, 13, 3)
        pygame.draw.circle(screen, color, center, 6)

    def _draw_point(self, screen, camera, point, payload):
        center = camera.world_to_screen(point["position"])
        if center is None:
            return
        point_id = point["id"]
        color = tuple(point.get("color") or (160, 160, 160))

        if point_id == "bed":
            self._draw_bed_icon(screen, center, color)
        elif point_id == "food":
            self._draw_food_icon(screen, center, color)
        elif point_id == "job":
            self._draw_job_icon(screen, center, color)
        else:
            self._draw_target_icon(screen, center, color)

        if point_id == payload.get("active_point_id"):
            pygame.draw.circle(screen, (245, 214, 108), center, 29, 3)
        elif point_id == payload.get("hover_point_id"):
            pygame.draw.circle(screen, (122, 214, 239), center, 27, 2)

        label = self._text(point.get("label") or point_id)
        screen.blit(label, label.get_rect(midtop=(center[0], center[1] + 28)))
        tier = self._text(point.get("maslow_tier", ""), (145, 157, 172))
        screen.blit(tier, tier.get_rect(midtop=(center[0], center[1] + 46)))

    def _draw_route(self, screen, camera, payload):
        destination = payload.get("destination")
        if destination is None:
            return
        start = camera.world_to_screen(payload["position"])
        end = camera.world_to_screen(destination)
        if start is None or end is None:
            return
        route_color = (
            (104, 190, 232)
            if payload.get("control_mode") == "direct"
            else (220, 196, 108)
        )
        pygame.draw.line(screen, (18, 21, 26), start, end, 6)
        pygame.draw.line(screen, route_color, start, end, 2)
        pygame.draw.circle(screen, route_color, end, 5, 2)

    def _draw_person(self, screen, camera, payload):
        center = camera.world_to_screen(payload["position"])
        if center is None:
            return
        color = (112, 201, 230) if payload.get("control_mode") == "direct" else (236, 214, 126)
        pygame.draw.circle(screen, (10, 13, 18), center, 13)
        pygame.draw.circle(screen, color, center, 10)
        pygame.draw.circle(screen, (236, 241, 246), (center[0], center[1] - 3), 3)
        pygame.draw.polygon(
            screen,
            (25, 30, 38),
            [
                (center[0] - 4, center[1] + 4),
                (center[0] + 4, center[1] + 4),
                (center[0], center[1] + 9),
            ],
        )

    def draw(self, screen, sim):
        screen.fill(self.BACKGROUND)
        camera = self.app_view.camera
        payload = sim.get_person_render_payload()
        self._draw_floor(screen, camera, payload["bounds"])
        self._draw_route(screen, camera, payload)
        for point in payload.get("points", []):
            self._draw_point(screen, camera, point, payload)
        self._draw_person(screen, camera, payload)

        mode = "AUTONOMOUS QUEUE" if payload.get("control_mode") == "autonomous" else "DIRECT CONTROL"
        mode_surface = self._text(mode, (226, 214, 142) if mode.startswith("AUTO") else (126, 205, 235))
        screen.blit(mode_surface, mode_surface.get_rect(midtop=(screen.get_width() // 2, 48)))
        hint = (
            "Click a point to force it to the front of the queue"
            if payload.get("control_mode") == "autonomous"
            else "Click to move; click a point to move and use; right-click to cancel"
        )
        hint_surface = self._text(hint, (160, 172, 187))
        screen.blit(hint_surface, hint_surface.get_rect(midtop=(screen.get_width() // 2, 68)))
