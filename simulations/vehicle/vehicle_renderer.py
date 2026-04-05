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

        drag_preview = payload.get("drag_preview_block")
        if drag_preview is not None:
            preview_rect = self._world_rect_to_screen(camera, drag_preview)
            if preview_rect is not None:
                preview_fill = pygame.Surface((max(1, preview_rect.width), max(1, preview_rect.height)), pygame.SRCALPHA)
                preview_fill.fill((120, 220, 255, 70))
                screen.blit(preview_fill, preview_rect.topleft)
                pygame.draw.rect(screen, (120, 220, 255), preview_rect, 2)

                if preview_rect.width >= 72 and preview_rect.height >= 24:
                    text_surface = self.app_view.default_font.render(
                        drag_preview.get("label", "preview"),
                        True,
                        (240, 240, 240),
                    )
                    text_rect = text_surface.get_rect(center=preview_rect.center)
                    screen.blit(text_surface, text_rect)

    def _draw_operational(self, screen, sim, camera, payload):
        base_rect = self._world_rect_to_screen(camera, payload["base_rect"])
        if base_rect is None:
            return

        pygame.draw.rect(screen, (28, 36, 30), base_rect)
        pygame.draw.rect(screen, (215, 215, 215), base_rect, 3)

        for module in payload.get("operational_modules", []):
            module_rect = self._world_rect_to_screen(camera, module)
            if module_rect is None:
                continue

            module_id = module.get("id")
            status = module.get("status", "missing")

            if status == "active":
                border_color = (150, 190, 160)
                fill_color = (48, 74, 54)
            elif status == "incomplete":
                border_color = (230, 210, 120)
                fill_color = (92, 84, 46)
            else:
                border_color = (170, 130, 130)
                fill_color = (72, 46, 46)

            if module_id == payload.get("hover_part_id"):
                border_color = (120, 220, 255)

            if module_id == payload.get("selected_part_id"):
                border_color = (255, 230, 120)

            pygame.draw.rect(screen, fill_color, module_rect)
            pygame.draw.rect(screen, border_color, module_rect, 2)

            text_x = module_rect.x + 8
            text_y = module_rect.y + 4

            group_surface = self.app_view.default_font.render(
                module.get("group", module.get("label", "module")),
                True,
                (240, 240, 240),
            )
            status_surface = self.app_view.default_font.render(
                module.get("status_text", status),
                True,
                (220, 220, 220),
            )

            screen.blit(group_surface, (text_x, text_y))
            screen.blit(status_surface, (text_x, text_y + 18))

            child_y = text_y + 38
            for child in module.get("children", []):
                if child_y + 14 > module_rect.bottom - 4:
                    break

                child_prefix = "- "
                child_label = child.get("label", child.get("category", "subsystem"))
                child_status = child.get("status", "missing")
                child_text = f"{child_prefix}{child_label}: {child_status}"

                if child_status == "active":
                    child_color = (180, 235, 180)
                elif child_status == "incomplete":
                    child_color = (255, 220, 150)
                else:
                    child_color = (240, 200, 200)

                child_surface = self.app_view.default_font.render(child_text, True, child_color)
                screen.blit(child_surface, (text_x + 10, child_y))
                child_y += 16

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