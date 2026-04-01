import pygame


class VehicleRenderer:
    """
    Handles rendering for vehicle simulations.
    """

    def __init__(self, app_view):
        self.app_view = app_view

    def _world_rect_to_screen(self, camera, rect_data):
        top_left = camera.world_to_screen((rect_data["x"], rect_data["y"]))
        bottom_right = camera.world_to_screen(
            (rect_data["x"] + rect_data["width"], rect_data["y"] + rect_data["height"])
        )

        if top_left is None or bottom_right is None:
            return None

        left = min(top_left[0], bottom_right[0])
        right = max(top_left[0], bottom_right[0])
        top = min(top_left[1], bottom_right[1])
        bottom = max(top_left[1], bottom_right[1])

        return pygame.Rect(left, top, right - left, bottom - top)

    def _screen_rect_from_data(self, rect_data):
        return pygame.Rect(
            int(rect_data["x"]),
            int(rect_data["y"]),
            int(rect_data["width"]),
            int(rect_data["height"]),
        )

    def _draw_design_catalog_overlay(self, screen, payload):
        panel_rect = self._screen_rect_from_data(payload["catalog_panel_rect"])
        pygame.draw.rect(screen, (20, 22, 28), panel_rect)
        pygame.draw.rect(screen, (215, 215, 215), panel_rect, 2)

        title_surface = self.app_view.default_font.render(
            "Design Catalog",
            True,
            (240, 240, 240),
        )
        screen.blit(title_surface, (panel_rect.x + 12, panel_rect.y + 8))

        active_catalog_component_id = payload.get("active_catalog_component_id")
        hover_catalog_component_id = payload.get("hover_catalog_component_id")
        catalog_by_id = {
            entry.get("id"): entry
            for entry in payload.get("component_catalog", [])
        }

        for rect_data in payload.get("catalog_entry_rects", []):
            catalog_id = rect_data.get("catalog_id")
            entry = catalog_by_id.get(catalog_id, {})
            rect = self._screen_rect_from_data(rect_data)

            border_color = (170, 170, 170)
            fill_color = (34, 38, 46)

            if catalog_id == hover_catalog_component_id:
                border_color = (120, 220, 255)
                fill_color = (52, 66, 82)

            if catalog_id == active_catalog_component_id:
                border_color = (255, 230, 120)
                fill_color = (92, 84, 50)

            pygame.draw.rect(screen, fill_color, rect)
            pygame.draw.rect(screen, border_color, rect, 2)

            dims = entry.get("dimensions_m", {})
            line = (
                f"{entry.get('label', catalog_id)} | "
                f"{dims.get('x', '?')} x {dims.get('y', '?')} x {dims.get('z', '?')} m"
            )
            text_surface = self.app_view.default_font.render(line, True, (240, 240, 240))
            screen.blit(text_surface, (rect.x + 8, rect.y + 5))

        footer_lines = [
            "Click catalog item to arm placement",
            "Click hull to place",
            "Click placed component to select",
            "Click hull to move selected component",
        ]
        line_y = panel_rect.bottom + 8
        for line in footer_lines:
            text_surface = self.app_view.default_font.render(line, True, (180, 180, 180))
            screen.blit(text_surface, (panel_rect.x + 2, line_y))
            line_y += 18

    def _draw_design_or_interior(self, screen, sim, camera, payload):
        base_rect = self._world_rect_to_screen(camera, payload["base_rect"])
        if base_rect is None:
            return

        pygame.draw.rect(screen, (30, 34, 42), base_rect)
        pygame.draw.rect(screen, (215, 215, 215), base_rect, 3)

        for block in payload.get("blocks", []):
            block_rect = self._world_rect_to_screen(camera, block)
            if block_rect is None:
                continue

            part_id = block.get("id")
            border_color = (170, 170, 170)
            fill_color = (52, 62, 82)

            if part_id == payload.get("hover_part_id"):
                border_color = (120, 220, 255)
                fill_color = (62, 84, 108)

            if part_id == payload.get("selected_part_id"):
                border_color = (255, 230, 120)
                fill_color = (104, 96, 56)

            pygame.draw.rect(screen, fill_color, block_rect)
            pygame.draw.rect(screen, border_color, block_rect, 2)

            if block_rect.width >= 72 and block_rect.height >= 24:
                text_surface = self.app_view.default_font.render(
                    block.get("label", part_id or "part"),
                    True,
                    (240, 240, 240),
                )
                text_rect = text_surface.get_rect(center=block_rect.center)
                screen.blit(text_surface, text_rect)

        if payload.get("mode") == sim.VIEW_DESIGN:
            self._draw_design_catalog_overlay(screen, payload)

    def _draw_operational(self, screen, sim, camera, payload):
        base_rect = self._world_rect_to_screen(camera, payload["base_rect"])
        if base_rect is None:
            return

        pygame.draw.rect(screen, (28, 36, 30), base_rect)
        pygame.draw.rect(screen, (215, 215, 215), base_rect, 3)

        center_x = base_rect.centerx
        center_y = base_rect.centery
        line_end_x = center_x + int(base_rect.width * 0.32)
        pygame.draw.line(screen, (255, 230, 120), (center_x, center_y), (line_end_x, center_y), 4)

        nose_rect = pygame.Rect(line_end_x - 10, center_y - 8, 20, 16)
        pygame.draw.rect(screen, (255, 230, 120), nose_rect)

        state = payload.get("operational_state", {})
        info_lines = [
            f"speed: {state.get('speed_kph', '?')} kph",
            f"heading: {state.get('heading_deg', '?')} deg",
            f"power: {state.get('power_state', '?')}",
            f"crew: {state.get('crew_state', '?')}",
            f"task: {state.get('task_state', '?')}",
            f"range: {state.get('range_km', '?')} km",
        ]

        text_x = base_rect.left + 18
        text_y = base_rect.top + 16
        for line in info_lines:
            text_surface = self.app_view.default_font.render(line, True, (240, 240, 240))
            screen.blit(text_surface, (text_x, text_y))
            text_y += 22

    def draw(self, screen, sim):
        camera = self.app_view.camera
        payload = sim.get_focused_render_payload()

        bounds = sim.bounds
        top_left = camera.world_to_screen((bounds["min_x"], bounds["min_y"]))
        bottom_right = camera.world_to_screen((bounds["max_x"], bounds["max_y"]))

        if top_left is not None and bottom_right is not None:
            left = min(top_left[0], bottom_right[0])
            right = max(top_left[0], bottom_right[0])
            top = min(top_left[1], bottom_right[1])
            bottom = max(top_left[1], bottom_right[1])
            background_rect = pygame.Rect(left, top, right - left, bottom - top)
            pygame.draw.rect(screen, (18, 18, 22), background_rect)

        if payload.get("mode") in (sim.VIEW_DESIGN, sim.VIEW_INTERIOR):
            self._draw_design_or_interior(screen, sim, camera, payload)
            return

        self._draw_operational(screen, sim, camera, payload)