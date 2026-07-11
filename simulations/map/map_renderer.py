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
        self._heightmap_surface_cache = {}
        self._scaled_heightmap_cache = {}
        self._text_surface_cache = {}
        self._scaled_cache_limit = 32
        self._text_cache_limit = 256

    def _cache_put(self, cache, key, value, limit=None):
        cache[key] = value
        if limit is None:
            return value
        while len(cache) > limit:
            cache.pop(next(iter(cache)))
        return value

    def _render_text(self, text, color):
        font = self.app_view.default_font
        color = tuple(color)
        cache_key = (id(font), str(text), color)
        cached = self._text_surface_cache.get(cache_key)
        if cached is not None:
            return cached

        surface = font.render(str(text), True, color)
        return self._cache_put(
            self._text_surface_cache,
            cache_key,
            surface,
            self._text_cache_limit,
        )

    def _coerce_rgb(self, value, fallback=(82, 78, 70)):
        if isinstance(value, (list, tuple)) and len(value) >= 3:
            try:
                return tuple(max(0, min(255, int(value[index]))) for index in range(3))
            except (TypeError, ValueError):
                return fallback
        return fallback

    def _mix_rgb(self, color_a, color_b, weight_b):
        weight_b = max(0.0, min(1.0, float(weight_b or 0.0)))
        weight_a = 1.0 - weight_b
        return tuple(
            max(0, min(255, int(color_a[index] * weight_a + color_b[index] * weight_b)))
            for index in range(3)
        )

    def _surface_palette_colors(self, layer):
        palette = layer.get("surface_palette") if isinstance(layer.get("surface_palette"), dict) else {}
        palette_colors = palette.get("palette") if isinstance(palette.get("palette"), list) else []
        colors = [self._coerce_rgb(color) for color in palette_colors[:4]]
        if len(colors) >= 4:
            return colors

        base_source = palette.get("surface_color") if palette else None
        if base_source is None:
            base_source = layer.get("color") or layer.get("display_color")
        base = self._coerce_rgb(base_source, fallback=(82, 78, 70))
        return [
            self._mix_rgb(base, (12, 14, 14), 0.36),
            base,
            self._mix_rgb(base, (218, 214, 198), 0.34),
            self._mix_rgb(base, (46, 48, 44), 0.18),
        ]

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

    def _draw_transparent_polygon(self, screen, points, fill_color, border_color=None, border_width=0):
        if len(points) < 3:
            return

        min_x = min(point[0] for point in points)
        max_x = max(point[0] for point in points)
        min_y = min(point[1] for point in points)
        max_y = max(point[1] for point in points)

        padding = max(1, int(border_width or 0) + 2)
        bounds = pygame.Rect(
            min_x - padding,
            min_y - padding,
            max(1, max_x - min_x + padding * 2),
            max(1, max_y - min_y + padding * 2),
        )
        clipped = bounds.clip(screen.get_rect())
        if clipped.width <= 0 or clipped.height <= 0:
            return

        local_points = [
            (int(point[0] - clipped.x), int(point[1] - clipped.y))
            for point in points
        ]
        overlay = pygame.Surface(clipped.size, pygame.SRCALPHA)
        pygame.draw.polygon(overlay, fill_color, local_points)
        if border_color is not None and border_width > 0:
            pygame.draw.polygon(overlay, border_color, local_points, border_width)
        screen.blit(overlay, clipped.topleft)

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
            self._cache_put(
                self._scaled_image_cache,
                cache_key,
                scaled,
                self._scaled_cache_limit,
            )

        alpha = layer.get("alpha")
        if alpha is not None:
            scaled = scaled.copy()
            scaled.set_alpha(max(0, min(255, int(alpha))))

        screen.blit(scaled, rect)

        if layer.get("is_ghost_context") and layer.get("name"):
            text = self._render_text(
                layer.get("name", "location"),
                (210, 218, 230),
            )
            screen.blit(text, (rect.x + 6, rect.y + 6))

    def _heightmap_color(self, elevation, heightmap, has_ice=False, layer=None):
        return self._heightmap_color_from_context(
            elevation,
            self._heightmap_color_context(heightmap, layer),
            has_ice=has_ice,
        )

    def _heightmap_color_context(self, heightmap, layer=None):
        sea_level_value = heightmap.get("sea_level_m")
        layer = layer if isinstance(layer, dict) else {}
        return {
            "has_ocean": sea_level_value is not None,
            "sea_level": 0.0 if sea_level_value is None else float(sea_level_value or 0.0),
            "min_elevation": float(heightmap.get("min_elevation_m", -4000.0) or -4000.0),
            "max_elevation": float(heightmap.get("max_elevation_m", 4000.0) or 4000.0),
            "palette": self._surface_palette_colors(layer),
        }

    def _heightmap_color_from_context(self, elevation, context, has_ice=False):
        has_ocean = context["has_ocean"]
        sea_level = context["sea_level"]
        min_elevation = context["min_elevation"]
        max_elevation = context["max_elevation"]
        land_dark, land_mid, land_high, land_shadow = context["palette"]
        elevation = float(elevation or 0.0)
        if has_ice:
            relief = min(1.0, (elevation - min_elevation) / max(1.0, max_elevation - min_elevation))
            return self._mix_rgb(
                self._mix_rgb((182, 204, 216), land_mid, 0.14),
                self._mix_rgb((232, 242, 246), land_high, 0.10),
                relief,
            )
        if has_ocean and elevation < sea_level:
            depth = min(1.0, (sea_level - elevation) / max(1.0, sea_level - min_elevation))
            return self._mix_rgb(
                self._mix_rgb((28, 78, 124), land_mid, 0.08),
                self._mix_rgb((8, 26, 48), land_shadow, 0.10),
                depth,
            )

        relief = min(1.0, (elevation - sea_level) / max(1.0, max_elevation - sea_level))
        if relief < 0.45:
            return self._mix_rgb(land_dark, land_mid, relief / 0.45)
        if relief < 0.82:
            return self._mix_rgb(land_mid, land_high, (relief - 0.45) / 0.37)
        return self._mix_rgb(land_high, (214, 212, 196), (relief - 0.82) / 0.18)

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

        clip = screen.get_clip()
        screen.set_clip(rect.clip(screen.get_rect()))
        cell_cols = max(1, min(len(row) for row in rows) - 1)
        cell_rows = max(1, len(rows) - 1)
        if cell_cols * cell_rows <= 4096:
            self._draw_heightmap_grid_cells(screen, rect, layer, heightmap, rows, cell_cols, cell_rows)
        else:
            heightmap_surface = self._heightmap_surface_for_layer(layer, heightmap, rows)
            if heightmap_surface is not None:
                scaled_key = (id(heightmap_surface), rect.width, rect.height)
                scaled = self._scaled_heightmap_cache.get(scaled_key)
                if scaled is None:
                    scaled = pygame.transform.scale(heightmap_surface, (rect.width, rect.height))
                    self._cache_put(
                        self._scaled_heightmap_cache,
                        scaled_key,
                        scaled,
                        self._scaled_cache_limit,
                    )
                screen.blit(scaled, rect)
        screen.set_clip(clip)

        pygame.draw.rect(screen, (75, 92, 112), rect, 1)
        if heightmap.get("wrap_x"):
            pygame.draw.line(screen, (120, 190, 230), (rect.x, rect.y), (rect.x, rect.bottom), 1)
            pygame.draw.line(screen, (120, 190, 230), (rect.right - 1, rect.y), (rect.right - 1, rect.bottom), 1)

    def _draw_heightmap_grid_cells(self, screen, rect, layer, heightmap, rows, cell_cols, cell_rows):
        masks = heightmap.get("surface_masks") if isinstance(heightmap.get("surface_masks"), dict) else {}
        ice_rows = masks.get("ice_rows") if isinstance(masks.get("ice_rows"), list) else []
        color_context = self._heightmap_color_context(heightmap, layer)

        x_edges = [
            rect.x + int(round(index * rect.width / cell_cols))
            for index in range(cell_cols + 1)
        ]
        y_edges = [
            rect.y + int(round(index * rect.height / cell_rows))
            for index in range(cell_rows + 1)
        ]

        for row_index in range(cell_rows):
            row_a = rows[row_index]
            row_b = rows[min(row_index + 1, len(rows) - 1)]
            top = y_edges[row_index]
            bottom = y_edges[row_index + 1]
            for col_index in range(cell_cols):
                values = (
                    row_a[col_index],
                    row_a[min(col_index + 1, len(row_a) - 1)],
                    row_b[col_index],
                    row_b[min(col_index + 1, len(row_b) - 1)],
                )
                elevation = sum(float(value or 0.0) for value in values) / 4.0
                has_ice = (
                    row_index < len(ice_rows)
                    and isinstance(ice_rows[row_index], list)
                    and col_index < len(ice_rows[row_index])
                    and bool(ice_rows[row_index][col_index])
                )
                left = x_edges[col_index]
                right = x_edges[col_index + 1]
                pygame.draw.rect(
                    screen,
                    self._heightmap_color_from_context(elevation, color_context, has_ice=has_ice),
                    pygame.Rect(left, top, max(1, right - left), max(1, bottom - top)),
                )

    def _heightmap_surface_for_layer(self, layer, heightmap, rows):
        cell_cols = max(1, min(len(row) for row in rows) - 1)
        cell_rows = max(1, len(rows) - 1)
        masks = heightmap.get("surface_masks") if isinstance(heightmap.get("surface_masks"), dict) else {}
        ice_rows = masks.get("ice_rows") if isinstance(masks.get("ice_rows"), list) else []
        cache_key = (
            id(heightmap),
            id(rows),
            id(ice_rows),
            repr(layer.get("surface_palette")),
            repr(layer.get("color")),
            repr(layer.get("display_color")),
            cell_cols,
            cell_rows,
        )
        cached = self._heightmap_surface_cache.get(cache_key)
        if cached is not None:
            return cached

        color_context = self._heightmap_color_context(heightmap, layer)
        surface = pygame.Surface((cell_cols, cell_rows))
        for row_index in range(cell_rows):
            row_a = rows[row_index]
            row_b = rows[min(row_index + 1, len(rows) - 1)]
            for col_index in range(cell_cols):
                values = (
                    row_a[col_index],
                    row_a[min(col_index + 1, len(row_a) - 1)],
                    row_b[col_index],
                    row_b[min(col_index + 1, len(row_b) - 1)],
                )
                elevation = sum(float(value or 0.0) for value in values) / 4.0
                has_ice = (
                    row_index < len(ice_rows)
                    and isinstance(ice_rows[row_index], list)
                    and col_index < len(ice_rows[row_index])
                    and bool(ice_rows[row_index][col_index])
                )
                surface.set_at(
                    (col_index, row_index),
                    self._heightmap_color_from_context(
                        elevation,
                        color_context,
                        has_ice=has_ice,
                    ),
                )

        return self._cache_put(
            self._heightmap_surface_cache,
            cache_key,
            surface,
            limit=16,
        )

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
        min_zoom = layer.get("min_zoom")
        if min_zoom is not None and not (is_selected or is_hovered):
            try:
                if float(getattr(camera, "zoom", 1.0) or 1.0) < float(min_zoom):
                    return
            except (TypeError, ValueError):
                pass

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
            border_color = layer.get("border_color", (225, 235, 220))
        border_width = max(0, int(layer.get("border_width", 2) or 0))

        outline_only = bool(layer.get("outline_only"))
        alpha = layer.get("alpha")
        border_alpha = layer.get("border_alpha", alpha)
        if outline_only:
            if border_width > 0:
                pygame.draw.polygon(screen, border_color, screen_points, border_width)
        elif alpha is not None or border_alpha is not None:
            fill_alpha = 80 if alpha is None else max(0, min(255, int(alpha)))
            line_alpha = 120 if border_alpha is None else max(0, min(255, int(border_alpha)))
            self._draw_transparent_polygon(
                screen,
                screen_points,
                (*fill_color, fill_alpha),
                (*border_color, line_alpha) if border_width > 0 else None,
                border_width=border_width,
            )
        else:
            pygame.draw.polygon(screen, fill_color, screen_points)
            if border_width > 0:
                pygame.draw.polygon(screen, border_color, screen_points, border_width)

        if is_hovered and not is_selected:
            pygame.draw.polygon(screen, (120, 220, 255), screen_points, 3)

        if is_selected:
            pygame.draw.polygon(screen, (255, 230, 120), screen_points, 4)

        should_draw_label = (max_x - min_x) >= 90 and (max_y - min_y) >= 32
        if layer.get("suppress_label"):
            should_draw_label = False
        if layer.get("is_placement_ancestor"):
            should_draw_label = (max_x - min_x) >= 220 and (max_y - min_y) >= 90
        if layer.get("is_ghost_sister"):
            should_draw_label = False
        if (is_hovered or is_selected) and layer.get("name"):
            should_draw_label = True

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

            text = self._render_text(
                layer.get("name", "feature"),
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
            self._draw_transparent_polygon(
                screen,
                previous_screen_points,
                (245, 245, 255, 18),
                (245, 245, 255, 96),
                border_width=2,
            )

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
            text = self._render_text(label, (245, 245, 245))
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

        fill_rect = rect.clip(screen.get_rect())
        if fill_rect.width > 0 and fill_rect.height > 0:
            fill_surface = pygame.Surface(fill_rect.size, pygame.SRCALPHA)
            fill_surface.fill((255, 230, 120, 44))
            screen.blit(fill_surface, fill_rect)

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
            text = self._render_text(label, (245, 245, 245))
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

            is_selected = (
                (spatial_feature_id is not None and spatial_feature_id == selected_spatial_feature_id)
                or (entity_id is not None and entity_id == selected_entity_id)
            )
            is_hovered = (
                (spatial_feature_id is not None and spatial_feature_id == hover_spatial_feature_id)
                or (entity_id is not None and entity_id == hover_entity_id)
            )

            min_zoom = layer.get("min_zoom")
            if min_zoom is not None and not (is_selected or is_hovered):
                try:
                    if float(getattr(camera, "zoom", 1.0) or 1.0) < float(min_zoom):
                        continue
                except (TypeError, ValueError):
                    pass

            if shape == "image_rect":
                self._draw_image_rect_layer(screen, layer, camera)
                continue

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
                elif not (
                    shape == "map_rect"
                    and (layer.get("has_heightmap_base") or layer.get("outline_only"))
                ):
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
                    text = self._render_text(
                        layer.get("name", "layer"),
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

            text = self._render_text(
                layer.get("name", "layer"),
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
