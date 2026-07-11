from pathlib import Path
import math

import pygame

from simulations.world_gen.material_heatmaps import load_raster_bundle_surface


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
        self._hydrology_surface_cache = {}
        self._scaled_hydrology_cache = {}
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

    def _visible_world_bounds(self, camera):
        screen_to_world = getattr(camera, "screen_to_world", None)
        if not callable(screen_to_world):
            return None
        try:
            left_top = screen_to_world((0, 0))
            right_bottom = screen_to_world((self.app_view.width, self.app_view.height))
        except (TypeError, ValueError, ZeroDivisionError, OverflowError):
            return None
        try:
            x0, y0 = float(left_top[0]), float(left_top[1])
            x1, y1 = float(right_bottom[0]), float(right_bottom[1])
        except (TypeError, ValueError, IndexError):
            return None
        return (
            min(x0, x1),
            max(x0, x1),
            min(y0, y1),
            max(y0, y1),
        )

    def _world_bounds_tuple(self, bounds):
        if isinstance(bounds, dict):
            try:
                return (
                    float(bounds["min_x"]),
                    float(bounds["max_x"]),
                    float(bounds["min_y"]),
                    float(bounds["max_y"]),
                )
            except (KeyError, TypeError, ValueError):
                return None
        if isinstance(bounds, (list, tuple)) and len(bounds) >= 4:
            try:
                return tuple(float(bounds[index]) for index in range(4))
            except (TypeError, ValueError):
                return None
        return None

    def _polygon_layer_visible_in_world(self, layer, camera, margin_px=24, visible_world_bounds=None):
        layer_bounds = self._world_bounds_tuple(layer.get("_world_bounds"))
        if layer_bounds is None:
            return True
        visible_bounds = visible_world_bounds
        if visible_bounds is None:
            visible_bounds = self._visible_world_bounds(camera)
        if visible_bounds is None:
            return True
        try:
            margin = float(margin_px) / max(abs(float(getattr(camera, "zoom", 1.0) or 1.0)), 1e-9)
        except (TypeError, ValueError):
            margin = 0.0

        layer_min_x, layer_max_x, layer_min_y, layer_max_y = layer_bounds
        visible_min_x, visible_max_x, visible_min_y, visible_max_y = visible_bounds
        return not (
            layer_max_x < visible_min_x - margin
            or layer_min_x > visible_max_x + margin
            or layer_max_y < visible_min_y - margin
            or layer_min_y > visible_max_y + margin
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

    def _load_raster_bundle_surface(self, bundle_path, layer_id):
        resolved_path = self._resolve_image_path(bundle_path)
        if resolved_path is None:
            return None

        cache_key = f"bundle:{resolved_path}:{layer_id or 'composite'}"
        if cache_key in self._image_cache:
            return self._image_cache[cache_key]

        surface = load_raster_bundle_surface(resolved_path, layer_id or "composite")
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

    def _source_rect_for_visible_dest(self, source_surface, dest_rect, visible_rect):
        if source_surface is None or dest_rect.width <= 0 or dest_rect.height <= 0:
            return None

        source_w, source_h = source_surface.get_size()
        rel_x = (visible_rect.x - dest_rect.x) / dest_rect.width
        rel_y = (visible_rect.y - dest_rect.y) / dest_rect.height
        rel_w = visible_rect.width / dest_rect.width
        rel_h = visible_rect.height / dest_rect.height
        sx = max(0, min(source_w - 1, int(rel_x * source_w)))
        sy = max(0, min(source_h - 1, int(rel_y * source_h)))
        sw = max(1, min(source_w - sx, int(math.ceil(rel_w * source_w)) + 1))
        sh = max(1, min(source_h - sy, int(math.ceil(rel_h * source_h)) + 1))
        return pygame.Rect(sx, sy, sw, sh)

    def _blit_scaled_layer(self, screen, source_surface, dest_rect, cache, cache_prefix, *, smooth=False, alpha=None):
        if source_surface is None:
            return False

        visible = dest_rect.clip(screen.get_rect())
        if visible.width <= 0 or visible.height <= 0:
            return False

        screen_w = max(1, self.app_view.width)
        screen_h = max(1, self.app_view.height)
        is_large_dest = dest_rect.width > screen_w * 1.5 or dest_rect.height > screen_h * 1.5

        if is_large_dest:
            source_rect = self._source_rect_for_visible_dest(source_surface, dest_rect, visible)
            if source_rect is None:
                return False
            source_key = (source_rect.x, source_rect.y, source_rect.width, source_rect.height)
            scale_size = (visible.width, visible.height)
            blit_pos = visible.topleft
        else:
            source_rect = source_surface.get_rect()
            source_key = None
            scale_size = (dest_rect.width, dest_rect.height)
            blit_pos = dest_rect.topleft

        effective_smooth = bool(smooth and not is_large_dest)
        cache_key = (
            cache_prefix,
            id(source_surface),
            source_key,
            scale_size[0],
            scale_size[1],
            effective_smooth,
            alpha,
        )
        scaled = cache.get(cache_key)
        if scaled is None:
            source_view = source_surface.subsurface(source_rect)
            transform = pygame.transform.smoothscale if effective_smooth else pygame.transform.scale
            scaled = transform(source_view, scale_size)
            if alpha is not None:
                scaled = scaled.copy()
                scaled.set_alpha(max(0, min(255, int(alpha))))
            self._cache_put(cache, cache_key, scaled, self._scaled_cache_limit)

        screen.blit(scaled, blit_pos)
        return True

    def _draw_image_rect_layer(self, screen, layer, camera):
        if layer.get("bundle_path"):
            image_surface = self._load_raster_bundle_surface(
                layer.get("bundle_path"),
                layer.get("bundle_layer_id"),
            )
        else:
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

        alpha = layer.get("alpha")
        self._blit_scaled_layer(
            screen,
            image_surface,
            rect,
            self._scaled_image_cache,
            str(layer.get("image_path") or layer.get("bundle_path")),
            smooth=True,
            alpha=alpha,
        )

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
                self._blit_scaled_layer(
                    screen,
                    heightmap_surface,
                    rect,
                    self._scaled_heightmap_cache,
                    "heightmap",
                )
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

    def _climate_zone_colors(self, water_cycle):
        colors = {
            "polar_ice": (202, 224, 232),
            "cold_steppe": (146, 158, 132),
            "temperate_wet": (82, 142, 104),
            "temperate_dry": (172, 156, 104),
            "tropical_wet": (48, 130, 88),
            "tropical_dry": (184, 146, 78),
            "arid": (196, 176, 118),
            "highland": (138, 128, 118),
            "ocean": (50, 92, 132),
        }
        for zone in water_cycle.get("climate_zones") or []:
            if isinstance(zone, dict) and zone.get("id"):
                colors[str(zone["id"])] = self._coerce_rgb(
                    zone.get("color"),
                    fallback=colors.get(str(zone["id"]), (150, 150, 150)),
                )
        return colors

    def _hydrology_surface_for_layer(self, layer, water_cycle):
        climate_grid = water_cycle.get("climate_grid") if isinstance(water_cycle, dict) else {}
        rows = climate_grid.get("rows") if isinstance(climate_grid.get("rows"), list) else []
        if not rows:
            return None
        row_count = len(rows)
        col_count = min(len(row) for row in rows if row)
        if row_count <= 0 or col_count <= 0:
            return None

        elevation_rows = climate_grid.get("elevation_rows") if isinstance(climate_grid.get("elevation_rows"), list) else []
        elevations = [
            float(value or 0.0)
            for row in elevation_rows[:row_count]
            for value in (row[:col_count] if isinstance(row, list) else [])
        ]
        min_elevation = min(elevations) if elevations else 0.0
        max_elevation = max(elevations) if elevations else 1.0
        elevation_span = max(1.0, max_elevation - min_elevation)
        cache_key = (
            id(water_cycle),
            id(rows),
            id(elevation_rows),
            col_count,
            row_count,
        )
        cached = self._hydrology_surface_cache.get(cache_key)
        if cached is not None:
            return cached

        colors = self._climate_zone_colors(water_cycle)
        surface = pygame.Surface((col_count, row_count))
        for row_index, row in enumerate(rows):
            for col_index, zone_id in enumerate(row[:col_count]):
                color = colors.get(str(zone_id), (126, 128, 126))
                if elevation_rows and row_index < len(elevation_rows) and col_index < len(elevation_rows[row_index]):
                    try:
                        elevation = float(elevation_rows[row_index][col_index] or 0.0)
                    except (TypeError, ValueError):
                        elevation = 0.0
                    elevation_norm = max(0.0, min(1.0, (elevation - min_elevation) / elevation_span))
                    shade = 0.76 + (1.0 - elevation_norm) * 0.14 if str(zone_id) == "ocean" else 0.78 + elevation_norm * 0.24
                    color = tuple(max(0, min(255, int(channel * shade))) for channel in color)
                surface.set_at((col_index, row_index), color)

        return self._cache_put(
            self._hydrology_surface_cache,
            cache_key,
            surface,
            limit=16,
        )

    def _draw_hydrology_layer(self, screen, layer, camera):
        water_cycle = layer.get("water_cycle_model") if isinstance(layer, dict) else None
        surface = self._hydrology_surface_for_layer(layer, water_cycle)
        if surface is None:
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
        self._blit_scaled_layer(
            screen,
            surface,
            rect,
            self._scaled_hydrology_cache,
            "hydrology",
        )
        for river in water_cycle.get("rivers") or []:
            if not isinstance(river, dict):
                continue
            points = []
            for point in river.get("points") or []:
                if not isinstance(point, dict):
                    continue
                px = rect.x + float(point.get("x", 0.0) or 0.0) * rect.width
                py = rect.y + float(point.get("y", 0.0) or 0.0) * rect.height
                points.append((int(px), int(py)))
            if len(points) >= 2:
                line_width = 1 + int(float(river.get("flow", 0.1) or 0.1) * 4)
                pygame.draw.lines(screen, (82, 172, 238), False, points, line_width)
        screen.set_clip(clip)
        pygame.draw.rect(screen, (118, 132, 158), rect, 1)

    def _draw_point_location_draft_preview(self, screen, preview, camera):
        center = camera.world_to_screen((preview.get("x", 0), preview.get("y", 0)))
        if center is None:
            return

        point = (int(center[0]), int(center[1]))
        if (
            point[0] < -16
            or point[0] > self.app_view.width + 16
            or point[1] < -16
            or point[1] > self.app_view.height + 16
        ):
            return

        color = preview.get("color", (255, 230, 120))
        radius = max(5, int(preview.get("min_screen_size", 10)) // 2)
        pygame.draw.circle(screen, color, point, radius)
        pygame.draw.circle(screen, (30, 34, 38), point, radius, 1)
        pygame.draw.line(screen, (120, 220, 255), (point[0] - 12, point[1]), (point[0] + 12, point[1]), 1)
        pygame.draw.line(screen, (120, 220, 255), (point[0], point[1] - 12), (point[0], point[1] + 12), 1)

        text = self._render_text(preview.get("name", "Draft point"), (245, 245, 245))
        screen.blit(text, (point[0] + 10, point[1] - 8))

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

    def _draw_polygon_layer(self, screen, layer, camera, is_selected, is_hovered, visible_world_bounds=None):
        min_zoom = layer.get("min_zoom")
        if min_zoom is not None and not (is_selected or is_hovered):
            try:
                if float(getattr(camera, "zoom", 1.0) or 1.0) < float(min_zoom):
                    return
            except (TypeError, ValueError):
                pass

        if not (is_selected or is_hovered) and not self._polygon_layer_visible_in_world(
            layer,
            camera,
            visible_world_bounds=visible_world_bounds,
        ):
            return

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
        visible_world_bounds = self._visible_world_bounds(camera)
        selected_entity_id = getattr(sim, "selected_entity_id", None)
        hover_entity_id = getattr(sim, "hover_entity_id", None)
        selected_spatial_feature_id = getattr(sim, "selected_spatial_feature_id", None)
        hover_spatial_feature_id = getattr(sim, "hover_spatial_feature_id", None)

        active_layer_kind = getattr(sim, "get_active_layer_kind", lambda: None)()
        if active_layer_kind in {"material_heatmaps"} and hasattr(sim, "get_heightmap_base_layer"):
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

            if shape == "heightmap_base":
                self._draw_heightmap_base_layer(screen, layer, camera)
                continue

            if shape == "hydrology_climate":
                self._draw_hydrology_layer(screen, layer, camera)
                continue

            if shape == "polygon":
                self._draw_polygon_layer(
                    screen=screen,
                    layer=layer,
                    camera=camera,
                    is_selected=is_selected,
                    is_hovered=is_hovered,
                    visible_world_bounds=visible_world_bounds,
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

        if hasattr(sim, "get_point_location_draft_preview"):
            preview = sim.get_point_location_draft_preview()
            if preview is not None:
                self._draw_point_location_draft_preview(screen, preview, camera)

        if hasattr(sim, "get_map_square_preview"):
            preview = sim.get_map_square_preview()
            if preview is not None:
                self._draw_square_preview(screen, preview, camera)
