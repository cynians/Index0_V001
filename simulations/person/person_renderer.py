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

    @staticmethod
    def _color(value, fallback):
        if isinstance(value, str):
            text = value.strip().lstrip("#")
            if len(text) == 6:
                try:
                    return tuple(int(text[index:index + 2], 16) for index in (0, 2, 4))
                except ValueError:
                    pass
        if isinstance(value, (list, tuple)) and len(value) >= 3:
            try:
                return tuple(max(0, min(255, int(channel))) for channel in value[:3])
            except (TypeError, ValueError):
                pass
        return tuple(fallback)

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

    def _draw_site_layout(self, screen, camera, payload):
        for zone in payload.get("terrain_zones", []):
            if not isinstance(zone, dict):
                continue
            bounds = zone.get("bounds") or {}
            rect = self._world_rect(
                camera,
                bounds.get("min_x", 0),
                bounds.get("min_y", 0),
                bounds.get("max_x", 0),
                bounds.get("max_y", 0),
            )
            if rect is None:
                continue
            color = self._color(zone.get("color"), (43, 64, 52))
            pygame.draw.rect(screen, color, rect)
            label = self._text(zone.get("label") or zone.get("terrain_class") or "terrain", (159, 177, 160))
            screen.blit(label, (rect.x + 10, rect.y + 8))

        for landmark in payload.get("site_landmarks", []):
            if not isinstance(landmark, dict):
                continue
            bounds = landmark.get("bounds") or {}
            rect = self._world_rect(
                camera,
                bounds.get("min_x", 0),
                bounds.get("min_y", 0),
                bounds.get("max_x", 0),
                bounds.get("max_y", 0),
            )
            if rect is None:
                continue
            landmark_class = str(landmark.get("landmark_class") or "").casefold()
            color = self._color(landmark.get("color"), (82, 78, 68))
            pygame.draw.rect(screen, color, rect, border_radius=3)
            if landmark_class == "road":
                pygame.draw.line(screen, (176, 166, 139), rect.midtop, rect.midbottom, max(2, rect.width // 5))
                pygame.draw.line(screen, (218, 204, 163), rect.midtop, rect.midbottom, 1)
            label = self._text(landmark.get("label") or landmark_class or "landmark", (215, 209, 190))
            screen.blit(label, label.get_rect(midtop=(rect.centerx, rect.y + 5)))

        for structure in payload.get("structures", []):
            bounds = structure.get("bounds") or {}
            rect = self._world_rect(
                camera,
                bounds.get("min_x", 0),
                bounds.get("min_y", 0),
                bounds.get("max_x", 0),
                bounds.get("max_y", 0),
            )
            if rect is None:
                continue
            color = self._color(structure.get("color"), (59, 64, 70))
            pygame.draw.rect(screen, color, rect)
            label = self._text(structure.get("label") or "Building", (205, 211, 216))
            screen.blit(label, label.get_rect(midtop=(rect.centerx, rect.y + 8)))

        for start, end in payload.get("wall_segments", []):
            screen_start = camera.world_to_screen(start)
            screen_end = camera.world_to_screen(end)
            if screen_start is None or screen_end is None:
                continue
            pygame.draw.line(screen, (12, 15, 19), screen_start, screen_end, 8)
            pygame.draw.line(screen, (156, 163, 168), screen_start, screen_end, 3)

    def _draw_site_people(self, screen, camera, payload):
        for resident in payload.get("site_people", []):
            if resident.get("controlled"):
                continue
            center = camera.world_to_screen(resident.get("position") or (0, 0))
            if center is None:
                continue
            sex = str(resident.get("sex") or "").casefold()
            detail = str(resident.get("simulation_detail") or "full").casefold()
            presence_kind = str(resident.get("presence_kind") or "authored").casefold()
            if presence_kind == "vehicle":
                self._draw_vehicle_presence(screen, camera, resident, center, payload)
                continue
            if detail == "aggregate":
                color = (144, 132, 101)
                radius = 12
            elif detail == "lightweight":
                color = (180, 154, 98)
                radius = 6
            elif "representative" in presence_kind:
                color = (116, 180, 145)
                radius = 7
            elif "visitor" in presence_kind:
                color = (194, 151, 103)
                radius = 7
            else:
                color = (194, 126, 151) if sex == "female" else (112, 157, 201) if sex == "male" else (157, 151, 121)
                radius = 7
            selected = resident.get("entity_id") == payload.get("selected_presence_id")
            hovered = resident.get("entity_id") == payload.get("hover_presence_id")
            if selected or hovered:
                pygame.draw.circle(screen, (238, 209, 111) if selected else (112, 201, 230), center, radius + 6, 2)
            pygame.draw.circle(screen, (10, 13, 18), center, radius + 3)
            pygame.draw.circle(screen, color, center, radius)
            if detail == "lightweight":
                pygame.draw.circle(screen, (233, 218, 168), center, radius, 1)
            label = self._text(resident.get("label") or "Worker", (194, 202, 211))
            screen.blit(label, label.get_rect(midtop=(center[0], center[1] + radius + 5)))

    def _draw_vehicle_presence(self, screen, camera, resident, center, payload):
        x, y = center
        selected = resident.get("entity_id") == payload.get("selected_presence_id")
        hovered = resident.get("entity_id") == payload.get("hover_presence_id")
        if selected or hovered:
            pygame.draw.rect(
                screen, (238, 209, 111) if selected else (112, 201, 230),
                (x - 16, y - 10, 32, 20), 2, border_radius=3,
            )
        pygame.draw.rect(screen, (10, 13, 18), (x - 14, y - 8, 28, 16), border_radius=3)
        pygame.draw.rect(screen, (149, 111, 66), (x - 12, y - 7, 24, 14), border_radius=2)
        pygame.draw.circle(screen, (30, 33, 38), (x - 7, y + 7), 3)
        pygame.draw.circle(screen, (30, 33, 38), (x + 7, y + 7), 3)
        label = self._text(resident.get("label") or "Vehicle", (194, 202, 211))
        screen.blit(label, label.get_rect(midtop=(x, y + 14)))

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

    def _draw_kitchen_icon(self, screen, center, color):
        x, y = center
        pygame.draw.rect(screen, color, (x - 23, y - 17, 46, 34), border_radius=4)
        pygame.draw.rect(screen, (31, 39, 45), (x - 17, y - 11, 20, 11), border_radius=2)
        pygame.draw.circle(screen, (220, 231, 231), (x - 7, y - 6), 3, 1)
        pygame.draw.rect(screen, (42, 48, 54), (x + 7, y - 11, 11, 22), border_radius=2)
        pygame.draw.circle(screen, (229, 216, 166), (x + 12, y - 5), 2)
        pygame.draw.line(screen, (226, 235, 235), (x - 18, y + 7), (x - 3, y + 7), 2)

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
        elif point_id == "kitchen":
            self._draw_kitchen_icon(screen, center, color)
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
        points = [payload["position"], *(payload.get("route_points") or []), destination]
        screen_points = [camera.world_to_screen(point) for point in points]
        screen_points = [point for point in screen_points if point is not None]
        if len(screen_points) < 2:
            return
        route_color = (
            (104, 190, 232)
            if payload.get("control_mode") == "direct"
            else (220, 196, 108)
        )
        pygame.draw.lines(screen, (18, 21, 26), False, screen_points, 6)
        pygame.draw.lines(screen, route_color, False, screen_points, 2)
        pygame.draw.circle(screen, route_color, screen_points[-1], 5, 2)

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

    def _draw_character_creation_banner(self, screen, payload):
        if not payload.get("needs_character_creation") or payload.get("site_simulation"):
            return
        tier = str(payload.get("character_readiness_tier") or "sparse").upper()
        missing = payload.get("character_readiness_missing") or []
        message = f"CHARACTER CREATION NEEDED -- {tier} -- missing: {', '.join(missing) if missing else 'unknown'}"
        text = self._text(message, (30, 20, 14))
        bar = pygame.Rect(0, 0, screen.get_width(), text.get_height() + 14)
        pygame.draw.rect(screen, (214, 168, 74), bar)
        screen.blit(text, text.get_rect(center=bar.center))

    def _draw_asset_palette(self, screen, payload):
        palette = payload.get("asset_palette") or []
        if not palette:
            return
        x, y = 16, 112
        header = self._text("ASSET PLACER", (200, 205, 214))
        screen.blit(header, (x, y))
        y += header.get_height() + 4
        selected_id = payload.get("placement_selected_asset_id")
        for index, entry in enumerate(palette, start=1):
            highlighted = entry["id"] == selected_id
            color = (245, 214, 108) if highlighted else self._color(entry.get("color"), (160, 160, 160))
            label = self._text(f"[{index}] {entry.get('label', entry['id'])}", color)
            screen.blit(label, (x, y))
            y += label.get_height() + 2
        if payload.get("placement_mode"):
            hint = self._text("Click the map to place -- Esc to cancel", (238, 209, 111))
            screen.blit(hint, (x, y + 4))

    def draw(self, screen, sim):
        screen.fill(self.BACKGROUND)
        camera = self.app_view.camera
        payload = sim.get_person_render_payload()
        if not payload.get("in_void"):
            self._draw_floor(screen, camera, payload["bounds"])
            self._draw_site_layout(screen, camera, payload)
        self._draw_route(screen, camera, payload)
        for point in payload.get("points", []):
            self._draw_point(screen, camera, point, payload)
        self._draw_site_people(screen, camera, payload)
        if payload.get("draw_controlled_person", True):
            self._draw_person(screen, camera, payload)

        if payload.get("site_simulation"):
            mode = "SITE POPULATION SIMULATION"
        else:
            mode = "AUTONOMOUS QUEUE" if payload.get("control_mode") == "autonomous" else "DIRECT CONTROL"
        mode_surface = self._text(mode, (226, 214, 142) if mode.startswith("AUTO") else (126, 205, 235))
        screen.blit(mode_surface, mode_surface.get_rect(midtop=(screen.get_width() // 2, 48)))
        if payload.get("site_simulation"):
            hint = "Click a named person to inspect or fully generate a lightweight encounter"
        else:
            hint = (
                "Click a point to assign it; urgent needs or convictions may override"
                if payload.get("control_mode") == "autonomous"
                else "Click to move; click a point to move and use; right-click to cancel"
            )
        hint_surface = self._text(hint, (160, 172, 187))
        screen.blit(hint_surface, hint_surface.get_rect(midtop=(screen.get_width() // 2, 68)))
        if payload.get("in_void") and not payload.get("site_simulation"):
            void_surface = self._text(payload.get("site_label"), (120, 128, 142))
            screen.blit(void_surface, void_surface.get_rect(midtop=(screen.get_width() // 2, 90)))
            self._draw_asset_palette(screen, payload)
        self._draw_character_creation_banner(screen, payload)
