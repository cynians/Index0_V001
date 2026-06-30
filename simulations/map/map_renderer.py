from pathlib import Path

import pygame


class MapRenderer:
    """
    Handles rendering for map simulations.
    """

    def __init__(self, app_view):
        self.app_view = app_view
        self._image_cache = {}
        self._scaled_image_cache = {}

    def _resolve_image_path(self, image_path):
        if not image_path:
            return None

        path = Path(str(image_path))
        if path.is_absolute():
            return path

        return Path(__file__).resolve().parents[2] / path

    def _load_image_surface(self, image_path):
        resolved_path = self._resolve_image_path(image_path)
        if resolved_path is None:
            return None

        cache_key = str(resolved_path)
        if cache_key in self._image_cache:
            return self._image_cache[cache_key]

        try:
            surface = pygame.image.load(cache_key).convert_alpha()
        except (OSError, pygame.error):
            surface = None

        self._image_cache[cache_key] = surface
        return surface

    def _draw_image_rect_layer(self, screen, layer, camera):
        image_surface = self._load_image_surface(layer.get("image_path"))
        if image_surface is None:
            return

        center = camera.world_to_screen((layer["x"], layer["y"]))
        if center is None:
            return

        pixel_w = max(1, int(layer.get("width_world", 1) * camera.zoom))
        pixel_h = max(1, int(layer.get("height_world", 1) * camera.zoom))
        rect = pygame.Rect(
            int(center[0] - pixel_w / 2),
            int(center[1] - pixel_h / 2),
            pixel_w,
            pixel_h,
        )

        if (
            rect.right < 0
            or rect.left > self.app_view.width
            or rect.bottom < 0
            or rect.top > self.app_view.height
        ):
            return

        cache_key = (str(layer.get("image_path")), rect.width, rect.height)
        scaled = self._scaled_image_cache.get(cache_key)
        if scaled is None:
            scaled = pygame.transform.smoothscale(image_surface, (rect.width, rect.height))
            self._scaled_image_cache[cache_key] = scaled

        alpha = layer.get("alpha")
        if alpha is not None:
            scaled = scaled.copy()
            scaled.set_alpha(max(0, min(255, int(alpha))))

        screen.blit(scaled, rect)

        if layer.get("is_ghost_context") and layer.get("name"):
            text = self.app_view.default_font.render(
                layer.get("name", "location"),
                True,
                (210, 218, 230),
            )
            screen.blit(text, (rect.x + 6, rect.y + 6))

    def _heightmap_color(self, elevation, heightmap):
        sea_level = heightmap.get("sea_level_m")
        sea_level = 0.0 if sea_level is None else float(sea_level or 0.0)
        min_elevation = float(heightmap.get("min_elevation_m", -4000.0) or -4000.0)
        max_elevation = float(heightmap.get("max_elevation_m", 4000.0) or 4000.0)

        elevation = float(elevation or 0.0)
        if elevation < sea_level:
            depth = min(1.0, (sea_level - elevation) / max(1.0, sea_level - min_elevation))
            return (
                int(14 + 18 * (1.0 - depth)),
                int(42 + 35 * (1.0 - depth)),
                int(72 + 78 * (1.0 - depth)),
            )

        relief = min(1.0, (elevation - sea_level) / max(1.0, max_elevation - sea_level))
        if relief < 0.24:
            t = relief / 0.24
            return (int(50 + 30 * t), int(82 + 48 * t), int(55 + 28 * t))
        if relief < 0.62:
            t = (relief - 0.24) / 0.38
            return (int(80 + 76 * t), int(130 + 42 * t), int(83 + 12 * t))
        t = (relief - 0.62) / 0.38
        value = int(156 + 68 * t)
        return (value, value, int(150 + 72 * t))

    def _draw_heightmap_base_layer(self, screen, layer, camera):
        heightmap = layer.get("heightmap_model") if isinstance(layer, dict) else None
        sample_grid = heightmap.get("sample_grid") if isinstance(heightmap, dict) else None
        rows = sample_grid.get("rows") if isinstance(sample_grid, dict) else None
        if not rows or len(rows) < 2 or len(rows[0]) < 2:
            return

        center = camera.world_to_screen((layer["x"], layer["y"]))
        if center is None:
            return

        pixel_w = max(1, int(layer.get("width_world", 1) * camera.zoom))
        pixel_h = max(1, int(layer.get("height_world", 1) * camera.zoom))
        rect = pygame.Rect(
            int(center[0] - pixel_w / 2),
            int(center[1] - pixel_h / 2),
            pixel_w,
            pixel_h,
        )
        if (
            rect.right < 0
            or rect.left > self.app_view.width
            or rect.bottom < 0
            or rect.top > self.app_view.height
        ):
            return

        cell_cols = max(1, min(len(row) for row in rows) - 1)
        cell_rows = max(1, len(rows) - 1)
        clip = screen.get_clip()
        screen.set_clip(rect.clip(screen.get_rect()))
        for row_index in range(cell_rows):
            row_a = rows[row_index]
            row_b = rows[min(row_index + 1, len(rows) - 1)]
            y0 = rect.y + int(row_index * rect.height / cell_rows)
            y1 = rect.y + int((row_index + 1) * rect.height / cell_rows)
            for col_index in range(cell_cols):
                x0 = rect.x + int(col_index * rect.width / cell_cols)
                x1 = rect.x + int((col_index + 1) * rect.width / cell_cols)
                values = (
                    row_a[col_index],
                    row_a[min(col_index + 1, len(row_a) - 1)],
                    row_b[col_index],
                    row_b[min(col_index + 1, len(row_b) - 1)],
                )
                elevation = sum(float(value or 0.0) for value in values) / 4.0
                pygame.draw.rect(
                    screen,
                    self._heightmap_color(elevation, heightmap),
                    pygame.Rect(x0, y0, max(1, x1 - x0), max(1, y1 - y0)),
                )
        screen.set_clip(clip)

        pygame.draw.rect(screen, (75, 92, 112), rect, 1)
        if heightmap.get("wrap_x"):
            pygame.draw.line(screen, (120, 190, 230), (rect.x, rect.y), (rect.x, rect.bottom), 1)
            pygame.draw.line(screen, (120, 190, 230), (rect.right - 1, rect.y), (rect.right - 1, rect.bottom), 1)

    def _draw_gas_giant_bands(self, screen, rect, layer):
        bands = layer.get("bands") if isinstance(layer.get("bands"), list) else []
        if not bands:
            bands = [layer.get("color", (180, 170, 150))]
        clip = screen.get_clip()
        screen.set_clip(rect.clip(screen.get_rect()))
        band_count = max(1, len(bands))
        for index in range(band_count):
            color = bands[index]
            try:
                color = (int(color[0]), int(color[1]), int(color[2]))
            except (TypeError, ValueError, IndexError):
                color = layer.get("color", (180, 170, 150))
            y0 = rect.y + int(index * rect.height / band_count)
            y1 = rect.y + int((index + 1) * rect.height / band_count)
            pygame.draw.rect(screen, color, pygame.Rect(rect.x, y0, rect.width, max(1, y1 - y0)))
        pygame.draw.line(screen, (238, 238, 232), (rect.x, rect.centery), (rect.right, rect.centery), 1)
        screen.set_clip(clip)

    def _draw_polygon_layer(self, screen, layer, camera, is_selected, is_hovered):
        screen_points = []

        for point in layer.get("points", []):
            screen_point = camera.world_to_screen(point)
            if screen_point is None:
                return

            screen_points.append((int(screen_point[0]), int(screen_point[1])))

        if len(screen_points) < 3:
            return

        min_x = min(point[0] for point in screen_points)
        max_x = max(point[0] for point in screen_points)
        min_y = min(point[1] for point in screen_points)
        max_y = max(point[1] for point in screen_points)

        if max_x < 0 or min_x > screen.get_width():
            return

        if max_y < 0 or min_y > screen.get_height():
            return

        base_color = layer.get("color", (120, 120, 140))

        if layer.get("is_virtual_spatial_feature"):
            fill_color = (
                int(base_color[0] * 0.48),
                int(base_color[1] * 0.48),
                int(base_color[2] * 0.48),
            )
            border_color = (
                min(255, int(base_color[0] * 1.18)),
                min(255, int(base_color[1] * 1.18)),
                min(255, int(base_color[2] * 1.18)),
            )
        else:
            fill_color = base_color
            border_color = (225, 235, 220)

        alpha = layer.get("alpha")
        border_alpha = layer.get("border_alpha", alpha)
        if alpha is not None or border_alpha is not None:
            alpha_surface = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
            fill_alpha = 80 if alpha is None else max(0, min(255, int(alpha)))
            line_alpha = 120 if border_alpha is None else max(0, min(255, int(border_alpha)))
            pygame.draw.polygon(alpha_surface, (*fill_color, fill_alpha), screen_points)
            pygame.draw.polygon(alpha_surface, (*border_color, line_alpha), screen_points, 2)
            screen.blit(alpha_surface, (0, 0))
        else:
            pygame.draw.polygon(screen, fill_color, screen_points)
            pygame.draw.polygon(screen, border_color, screen_points, 2)

        if is_hovered and not is_selected:
            pygame.draw.polygon(screen, (120, 220, 255), screen_points, 3)

        if is_selected:
            pygame.draw.polygon(screen, (255, 230, 120), screen_points, 4)

        should_draw_label = (max_x - min_x) >= 90 and (max_y - min_y) >= 32
        if layer.get("is_placement_ancestor"):
            should_draw_label = (max_x - min_x) >= 220 and (max_y - min_y) >= 90
        if layer.get("is_ghost_sister"):
            should_draw_label = False

        if should_draw_label:
            label_pos = camera.world_to_screen((layer.get("x", 0), layer.get("y", 0)))
            if label_pos is None:
                return

            if layer.get("is_placement_ancestor"):
                text_color = (148, 162, 182)
            elif layer.get("is_ghost_context"):
                text_color = (210, 218, 230)
            else:
                text_color = (245, 245, 245)

            text = self.app_view.default_font.render(
                layer.get("name", "feature"),
                True,
                text_color,
            )
            screen.blit(text, (int(label_pos[0]) + 6, int(label_pos[1]) + 6))

    def _draw_spatial_feature_draft_preview(self, screen, preview, camera):
        points = preview.get("points", [])
        previous_points = preview.get("previous_points") or []
        hover_point = preview.get("hover_point")
        area_label = preview.get("area_label")

        screen_points = []
        for point in points:
            screen_point = camera.world_to_screen(point)
            if screen_point is None:
                return
            screen_points.append((int(screen_point[0]), int(screen_point[1])))

        hover_screen_point = None
        if hover_point is not None:
            hover_screen_point = camera.world_to_screen(hover_point)
            if hover_screen_point is not None:
                hover_screen_point = (
                    int(hover_screen_point[0]),
                    int(hover_screen_point[1]),
                )

        previous_screen_points = []
        for point in previous_points:
            screen_point = camera.world_to_screen(point)
            if screen_point is None:
                previous_screen_points = []
                break
            previous_screen_points.append((int(screen_point[0]), int(screen_point[1])))

        if len(previous_screen_points) >= 3:
            ghost_surface = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
            pygame.draw.polygon(
                ghost_surface,
                (245, 245, 255, 18),
                previous_screen_points,
            )
            pygame.draw.lines(
                ghost_surface,
                (245, 245, 255, 96),
                True,
                previous_screen_points,
                2,
            )
            screen.blit(ghost_surface, (0, 0))

        if len(screen_points) >= 2:
            pygame.draw.lines(screen, (255, 230, 120), False, screen_points, 2)

        if len(screen_points) >= 3:
            pygame.draw.lines(screen, (255, 230, 120), True, screen_points, 2)

        if screen_points and hover_screen_point is not None:
            pygame.draw.line(
                screen,
                (120, 220, 255),
                screen_points[-1],
                hover_screen_point,
                1,
            )

        for index, point in enumerate(screen_points):
            radius = 5 if index == len(screen_points) - 1 else 4
            pygame.draw.circle(screen, (255, 230, 120), point, radius)
            pygame.draw.circle(screen, (30, 34, 38), point, radius, 1)

        if area_label and len(screen_points) >= 3:
            label_anchor = hover_screen_point or screen_points[-1]
            label = f"Area: {area_label}"
            text = self.app_view.default_font.render(label, True, (245, 245, 245))
            padding = 6
            label_rect = pygame.Rect(
                label_anchor[0] + 12,
                label_anchor[1] + 12,
                text.get_width() + padding * 2,
                text.get_height() + padding * 2,
            )

            if label_rect.right > screen.get_width() - 8:
                label_rect.x = label_anchor[0] - label_rect.width - 12

            if label_rect.bottom > screen.get_height() - 8:
                label_rect.y = label_anchor[1] - label_rect.height - 12

            pygame.draw.rect(screen, (24, 27, 34), label_rect)
            pygame.draw.rect(screen, (210, 218, 232), label_rect, 1)
            screen.blit(text, (label_rect.x + padding, label_rect.y + padding))

    def _draw_square_preview(self, screen, preview, camera):
        bounds = preview.get("bounds")
        anchor_point = preview.get("anchor_point")
        handles = preview.get("handles", [])
        active_handle = preview.get("active_handle")
        area_label = preview.get("area_label")

        if bounds is None:
            if anchor_point is None:
                return

            anchor_screen = camera.world_to_screen(anchor_point)
            if anchor_screen is None:
                return

            pygame.draw.circle(
                screen,
                (255, 230, 120),
                (int(anchor_screen[0]), int(anchor_screen[1])),
                5,
            )
            pygame.draw.circle(
                screen,
                (30, 34, 38),
                (int(anchor_screen[0]), int(anchor_screen[1])),
                5,
                1,
            )
            return

        top_left = camera.world_to_screen((bounds["min_x"], bounds["min_y"]))
        bottom_right = camera.world_to_screen((bounds["max_x"], bounds["max_y"]))
        if top_left is None or bottom_right is None:
            return

        left = min(int(top_left[0]), int(bottom_right[0]))
        right = max(int(top_left[0]), int(bottom_right[0]))
        top = min(int(top_left[1]), int(bottom_right[1]))
        bottom = max(int(top_left[1]), int(bottom_right[1]))
        rect = pygame.Rect(left, top, right - left, bottom - top)

        if rect.width < 1 or rect.height < 1:
            return

        fill_surface = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
        fill_surface.fill((255, 230, 120, 44))
        screen.blit(fill_surface, rect)

        border_color = (255, 230, 120)
        if preview.get("mode") == "edit":
            border_color = (120, 220, 255)

        pygame.draw.rect(screen, border_color, rect, 3)

        for handle in handles:
            handle_id = handle.get("id")
            point = handle.get("point")
            screen_point = camera.world_to_screen(point)
            if screen_point is None:
                continue

            handle_size = 10 if handle_id == active_handle else 8
            handle_rect = pygame.Rect(
                int(screen_point[0] - handle_size / 2),
                int(screen_point[1] - handle_size / 2),
                handle_size,
                handle_size,
            )
            fill = (255, 230, 120) if handle_id != "center" else (120, 220, 255)
            if handle_id == active_handle:
                fill = (245, 245, 245)

            pygame.draw.rect(screen, fill, handle_rect)
            pygame.draw.rect(screen, (30, 34, 38), handle_rect, 1)

        if area_label:
            label = f"Area: {area_label}"
            text = self.app_view.default_font.render(label, True, (245, 245, 245))
            padding = 6
            label_rect = pygame.Rect(
                rect.right + 12,
                rect.bottom + 12,
                text.get_width() + padding * 2,
                text.get_height() + padding * 2,
            )

            if label_rect.right > screen.get_width() - 8:
                label_rect.x = rect.left - label_rect.width - 12

            if label_rect.bottom > screen.get_height() - 8:
                label_rect.y = rect.top - label_rect.height - 12

            pygame.draw.rect(screen, (24, 27, 34), label_rect)
            pygame.draw.rect(screen, (210, 218, 232), label_rect, 1)
            screen.blit(text, (label_rect.x + padding, label_rect.y + padding))

    def draw(self, screen, sim):
        view = self.app_view
        camera = view.camera
        selected_entity_id = getattr(sim, "selected_entity_id", None)
        hover_entity_id = getattr(sim, "hover_entity_id", None)
        selected_spatial_feature_id = getattr(sim, "selected_spatial_feature_id", None)
        hover_spatial_feature_id = getattr(sim, "hover_spatial_feature_id", None)

        if hasattr(sim, "get_heightmap_base_layer"):
            heightmap_base_layer = sim.get_heightmap_base_layer()
            if heightmap_base_layer is not None:
                self._draw_heightmap_base_layer(screen, heightmap_base_layer, camera)

        for layer in sim.get_layers():
            shape = layer.get("shape", "marker")
            entity_id = layer.get("entity_id")
            spatial_feature_id = layer.get("spatial_feature_id")

            if shape == "image_rect":
                self._draw_image_rect_layer(screen, layer, camera)
                continue

            is_selected = (
                (spatial_feature_id is not None and spatial_feature_id == selected_spatial_feature_id)
                or (entity_id is not None and entity_id == selected_entity_id)
            )
            is_hovered = (
                (spatial_feature_id is not None and spatial_feature_id == hover_spatial_feature_id)
                or (entity_id is not None and entity_id == hover_entity_id)
            )

            if shape == "polygon":
                self._draw_polygon_layer(
                    screen=screen,
                    layer=layer,
                    camera=camera,
                    is_selected=is_selected,
                    is_hovered=is_hovered,
                )
                continue

            center = camera.world_to_screen((layer["x"], layer["y"]))

            if center is None:
                continue

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

                if shape == "map_rect" and layer.get("render_style") == "gas_giant_bands":
                    self._draw_gas_giant_bands(screen, rect, layer)
                elif not (shape == "map_rect" and layer.get("has_heightmap_base")):
                    pygame.draw.rect(screen, layer["color"], rect)

                if shape == "map_rect":
                    pygame.draw.rect(screen, (220, 220, 220), rect, 3)

                    if layer.get("render_style") != "gas_giant_bands":
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
                    if layer.get("label_position") == "below_right":
                        label_x = rect.right - text.get_width()
                        label_y = rect.bottom + 4
                        screen.blit(text, (label_x, label_y))
                    else:
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

        if hasattr(sim, "get_spatial_feature_draft_preview"):
            preview = sim.get_spatial_feature_draft_preview()
            if preview is not None:
                self._draw_spatial_feature_draft_preview(screen, preview, camera)

        if hasattr(sim, "get_map_square_preview"):
            preview = sim.get_map_square_preview()
            if preview is not None:
                self._draw_square_preview(screen, preview, camera)
