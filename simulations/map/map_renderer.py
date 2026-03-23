import pygame


class MapRenderer:
    """
    Handles rendering for map simulations.
    """

    def __init__(self, app_view):
        self.app_view = app_view

    def draw(self, screen, sim):
        view = self.app_view
        camera = view.camera
        selected_entity_id = getattr(sim, "selected_entity_id", None)
        hover_entity_id = getattr(sim, "hover_entity_id", None)

        for layer in sim.get_layers():
            center = camera.world_to_screen((layer["x"], layer["y"]))

            if center is None:
                continue

            shape = layer.get("shape", "marker")
            entity_id = layer.get("entity_id")
            is_selected = entity_id == selected_entity_id
            is_hovered = entity_id == hover_entity_id

            if shape in ("map_rect", "rect"):
                pixel_w = max(6, int(layer.get("width_world", 1) * camera.zoom))
                pixel_h = max(6, int(layer.get("height_world", 1) * camera.zoom))

                rect = pygame.Rect(
                    int(center[0] - pixel_w / 2),
                    int(center[1] - pixel_h / 2),
                    pixel_w,
                    pixel_h,
                )

                if (
                    rect.right < 0
                    or rect.left > view.width
                    or rect.bottom < 0
                    or rect.top > view.height
                ):
                    continue

                pygame.draw.rect(screen, layer["color"], rect)

                if shape == "map_rect":
                    pygame.draw.rect(screen, (220, 220, 220), rect, 3)

                    pygame.draw.line(
                        screen,
                        (110, 125, 150),
                        (rect.x, rect.centery),
                        (rect.right, rect.centery),
                        1,
                    )
                    pygame.draw.line(
                        screen,
                        (110, 125, 150),
                        (rect.centerx, rect.y),
                        (rect.centerx, rect.bottom),
                        1,
                    )
                else:
                    pygame.draw.rect(screen, (220, 220, 220), rect, 2)

                if is_hovered and not is_selected:
                    hover_rect = rect.inflate(6, 6)
                    pygame.draw.rect(screen, (120, 220, 255), hover_rect, 2)

                if is_selected:
                    highlight_rect = rect.inflate(8, 8)
                    pygame.draw.rect(screen, (255, 230, 120), highlight_rect, 3)

                if rect.width >= 80 and rect.height >= 28:
                    text = view.default_font.render(
                        layer.get("name", "layer"),
                        True,
                        (240, 240, 240)
                    )
                    screen.blit(text, (rect.x + 6, rect.y + 6))

                continue

            pixel_size = max(6, int(layer.get("min_screen_size", 8)))

            rect = pygame.Rect(
                int(center[0] - pixel_size / 2),
                int(center[1] - pixel_size / 2),
                pixel_size,
                pixel_size,
            )

            if (
                rect.right < 0
                or rect.left > view.width
                or rect.bottom < 0
                or rect.top > view.height
            ):
                continue

            pygame.draw.rect(screen, layer["color"], rect)
            pygame.draw.rect(screen, (220, 220, 220), rect, 2)

            if is_hovered and not is_selected:
                hover_rect = rect.inflate(8, 8)
                pygame.draw.rect(screen, (120, 220, 255), hover_rect, 2)

            if is_selected:
                highlight_rect = rect.inflate(10, 10)
                pygame.draw.rect(screen, (255, 230, 120), highlight_rect, 3)

            text = view.default_font.render(
                layer.get("name", "layer"),
                True,
                (240, 240, 240)
            )
            screen.blit(text, (rect.x + 8, rect.y - 2))