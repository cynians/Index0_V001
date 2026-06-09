import math

import pygame


class WorldGenRenderer:
    """
    Renderer for the empty-start planetary world generation workspace.
    """

    AU_M = 149_597_870_700.0

    def __init__(self, app_view):
        self.app_view = app_view

    def _world_point_for_au(self, au_x, au_y):
        return au_x * self.AU_M, au_y * self.AU_M

    def _screen_points_for_orbit(self, camera, semi_major_au, eccentricity, count=180):
        if semi_major_au is None or eccentricity is None:
            return []

        points = []
        b_au = semi_major_au * math.sqrt(max(0.0, 1.0 - eccentricity * eccentricity))
        for index in range(count):
            angle = (index / count) * math.tau
            x_au = semi_major_au * (math.cos(angle) - eccentricity)
            y_au = b_au * math.sin(angle)
            screen_point = camera.world_to_screen(self._world_point_for_au(x_au, y_au))
            if screen_point is not None:
                points.append((int(screen_point[0]), int(screen_point[1])))
        return points

    def _draw_circle_au(self, screen, camera, radius_au, color, width=1):
        if radius_au is None or radius_au <= 0:
            return

        center = camera.world_to_screen((0.0, 0.0))
        if center is None:
            return

        pixel_radius = int(radius_au * self.AU_M * camera.zoom)
        if pixel_radius <= 1:
            return

        pygame.draw.circle(
            screen,
            color,
            (int(center[0]), int(center[1])),
            pixel_radius,
            width,
        )

    def _draw_habitable_zone(self, screen, camera, model):
        inner_au = model.get("habitable_zone_inner_au")
        outer_au = model.get("habitable_zone_outer_au")
        if inner_au is None or outer_au is None or outer_au <= inner_au:
            return

        center = camera.world_to_screen((0.0, 0.0))
        if center is None:
            return

        inner_px = int(inner_au * self.AU_M * camera.zoom)
        outer_px = int(outer_au * self.AU_M * camera.zoom)
        if outer_px <= 1:
            return

        zone_surface = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        pygame.draw.circle(zone_surface, (92, 128, 92, 42), (int(center[0]), int(center[1])), outer_px)
        if inner_px > 0:
            pygame.draw.circle(zone_surface, (0, 0, 0, 0), (int(center[0]), int(center[1])), inner_px)
        pygame.draw.circle(zone_surface, (150, 196, 138, 130), (int(center[0]), int(center[1])), outer_px, 2)
        if inner_px > 0:
            pygame.draw.circle(zone_surface, (150, 196, 138, 120), (int(center[0]), int(center[1])), inner_px, 2)
        screen.blit(zone_surface, (0, 0))

    def _draw_reference_bodies(self, screen, camera, bodies):
        for body in bodies:
            semi_major_m = body.get("semi_major_axis_m")
            eccentricity = body.get("eccentricity", 0.0)
            if not semi_major_m:
                continue

            try:
                semi_major_au = float(semi_major_m) / self.AU_M
                eccentricity_value = float(eccentricity or 0.0)
            except (TypeError, ValueError):
                continue

            orbit_points = self._screen_points_for_orbit(camera, semi_major_au, eccentricity_value, count=120)
            if len(orbit_points) > 2:
                pygame.draw.lines(screen, (76, 84, 98), True, orbit_points, 1)

    def _draw_star(self, screen, camera, payload):
        center = camera.world_to_screen((0.0, 0.0))
        if center is None:
            return

        pygame.draw.circle(screen, (244, 208, 106), (int(center[0]), int(center[1])), 9)
        pygame.draw.circle(screen, (255, 236, 172), (int(center[0]), int(center[1])), 13, 1)
        star = payload.get("star") or {}
        label = star.get("name") or "Primary Star"
        text = self.app_view.default_font.render(label, True, (244, 226, 172))
        screen.blit(text, (int(center[0]) + 14, int(center[1]) - 8))

    def _draw_candidate_orbit(self, screen, camera, model):
        if not model.get("orbit_valid"):
            return

        points = self._screen_points_for_orbit(
            camera,
            model.get("semi_major_axis_au"),
            model.get("eccentricity"),
            count=180,
        )
        if len(points) <= 2:
            return

        pygame.draw.lines(screen, (116, 184, 244), True, points, 2)
        periapsis = points[0]
        pygame.draw.circle(screen, (176, 220, 255), periapsis, 5)
        label = self.app_view.default_font.render("candidate planet", True, (176, 220, 255))
        screen.blit(label, (periapsis[0] + 8, periapsis[1] + 8))

    def _draw_input_panel(self, screen, sim, payload):
        font = self.app_view.default_font
        panel_w = 430
        panel_h = 232
        panel = pygame.Rect(20, screen.get_height() - panel_h - 24, panel_w, panel_h)
        pygame.draw.rect(screen, (22, 25, 34), panel)
        pygame.draw.rect(screen, (188, 196, 212), panel, 1)

        title = font.render("World Generation: Orbit Draft", True, (244, 244, 244))
        screen.blit(title, (panel.x + 12, panel.y + 10))

        field_rects = {}
        y = panel.y + 46
        for field in payload.get("fields", []):
            label = font.render(field["label"], True, (190, 200, 216))
            screen.blit(label, (panel.x + 12, y))
            input_rect = pygame.Rect(panel.x + 216, y - 4, 150, 24)
            field_rects[field["id"]] = input_rect
            fill = (38, 48, 68) if field.get("active") else (30, 34, 44)
            border = (188, 212, 244) if field.get("active") else (92, 102, 122)
            pygame.draw.rect(screen, fill, input_rect)
            pygame.draw.rect(screen, border, input_rect, 1)
            value = field.get("text") or ""
            value_surface = font.render(value or "AU", True, (238, 238, 238) if value else (128, 138, 154))
            screen.blit(value_surface, (input_rect.x + 6, input_rect.y + 4))
            y += 34

        sim.set_input_field_rects(field_rects)
        sim.set_control_panel_rect(panel)

        y += 6
        for line in payload.get("summary_lines", []):
            surface = font.render(line, True, (220, 226, 236))
            screen.blit(surface, (panel.x + 12, y))
            y += 22

        status = payload.get("commit_status") or ""
        if status:
            status_surface = font.render(status, True, (178, 210, 244))
            screen.blit(status_surface, (panel.x + 12, panel.bottom - 52))

        if payload.get("planet_name_prompt_active"):
            hint_text = "Type planet name. Enter creates planet. Esc cancels."
        elif payload.get("orbit_pick_stage") == "second":
            hint_text = "Second click sets ellipse. Click elsewhere to start a new circular draft."
        else:
            hint_text = "Click orbit, then Enter to name and create the planet."
        hint = font.render(hint_text, True, (142, 152, 170))
        max_hint_w = panel.width - 24
        if hint.get_width() > max_hint_w:
            hint_text = "Click once: circular. Second click: ellipse. Tab edits fields."
            hint = font.render(hint_text, True, (142, 152, 170))
        screen.blit(hint, (panel.x + 12, panel.bottom - 26))

        if payload.get("planet_name_prompt_active"):
            prompt_w = 360
            prompt_h = 112
            prompt = pygame.Rect(
                (screen.get_width() - prompt_w) // 2,
                86,
                prompt_w,
                prompt_h,
            )
            input_rect = pygame.Rect(prompt.x + 18, prompt.y + 56, prompt.width - 36, 28)
            pygame.draw.rect(screen, (24, 28, 38), prompt)
            pygame.draw.rect(screen, (188, 196, 212), prompt, 1)
            title = font.render("Name Planet", True, (244, 244, 244))
            screen.blit(title, (prompt.x + 14, prompt.y + 12))
            pygame.draw.rect(screen, (38, 48, 68), input_rect)
            pygame.draw.rect(screen, (188, 212, 244), input_rect, 1)
            text = payload.get("planet_name_buffer") or ""
            surface = font.render(text or "Planet name", True, (238, 238, 238) if text else (128, 138, 154))
            screen.blit(surface, (input_rect.x + 8, input_rect.y + 5))

    def draw(self, screen, sim):
        payload = sim.get_preview_payload()
        model = payload.get("model", {})
        camera = self.app_view.camera

        self._draw_habitable_zone(screen, camera, model)
        self._draw_reference_bodies(screen, camera, payload.get("system_bodies", []))
        self._draw_candidate_orbit(screen, camera, model)
        self._draw_star(screen, camera, payload)
        self._draw_input_panel(screen, sim, payload)
