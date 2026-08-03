from pathlib import Path
import math

import pygame

try:
    import numpy as np
except ImportError:  # Keep a functional, slower path for minimal installations.
    np = None

from simulations.world_gen.material_heatmaps import load_raster_bundle_surface
from simulations.world_gen.true_color import render_true_color_surface
from simulations.world_gen.heightmap import (
    contour_levels_for_heightmap,
    display_contour_interval_m,
    height_marker_interval_m,
)
from simulations.map.projection import project_normalized_point


class MapRenderer:
    """
    Handles rendering for map simulations.
    """

    def __init__(self, app_view):
        self.app_view = app_view
        self._image_cache = {}
        self._scaled_image_cache = {}
        self._heightmap_surface_cache = {}
        self._true_color_surface_cache = {}
        self._scaled_heightmap_cache = {}
        self._height_contour_surface_cache = {}
        self._height_contour_geometry_cache = {}
        self._scaled_height_contour_cache = {}
        self._large_scaled_layer_cache = {}
        self._hydrology_surface_cache = {}
        self._scaled_hydrology_cache = {}
        self._projected_reference_hydrology_cache = {}
        self._reference_hydrology_overlay_cache = {}
        self._projection_surface_cache = {}
        self._projection_coordinate_cache = {}
        self._projection_source_cache = {}
        self._material_composite_cache = {}
        self._cropped_surface_cache = {}
        self._reference_land_surface_cache = {}
        self._static_outline_surface_cache = {}
        self._text_surface_cache = {}
        self._alpha_fill_cache = {}
        self._polygon_screen_cache = {}
        self._scaled_cache_limit = 8
        self._text_cache_limit = 256
        self._viewport_overscan_px = 72

    @staticmethod
    def _heightmap_contour_segments(heightmap, level):
        grid = heightmap.get("sample_grid") if isinstance(heightmap.get("sample_grid"), dict) else {}
        rows = grid.get("rows") if isinstance(grid.get("rows"), list) else []
        sample_h = min(len(rows), int(grid.get("height", len(rows)) or len(rows)))
        declared_width = int(grid.get("width", len(rows[0]) if rows else 0) or 0)
        sample_w = min(
            min((len(row) for row in rows[:sample_h] if isinstance(row, list)), default=0),
            declared_width,
        )
        if sample_w < 2 or sample_h < 2:
            return []

        def edge_point(edge, col, row, value_a, value_b):
            denominator = value_b - value_a
            amount = 0.5 if abs(denominator) < 1e-9 else (level - value_a) / denominator
            amount = max(0.0, min(1.0, amount))
            if edge == "top":
                return col + amount, row
            if edge == "right":
                return col + 1, row + amount
            if edge == "bottom":
                return col + amount, row + 1
            return col, row + amount

        def append_cell(segments, col, row, v00, v10, v01, v11):
            points = {}
            for edge, value_a, value_b in (
                ("top", v00, v10),
                ("right", v10, v11),
                ("bottom", v01, v11),
                ("left", v00, v01),
            ):
                if (
                    (value_a < level <= value_b)
                    or (value_b < level <= value_a)
                ):
                    points[edge] = edge_point(edge, col, row, value_a, value_b)
            if len(points) == 2:
                segments.append(tuple(points.values()))
            elif len(points) == 4:
                center_high = (v00 + v10 + v01 + v11) * 0.25 >= level
                if (v00 >= level) == center_high:
                    segments.extend((
                        (points["top"], points["right"]),
                        (points["bottom"], points["left"]),
                    ))
                else:
                    segments.extend((
                        (points["top"], points["left"]),
                        (points["right"], points["bottom"]),
                    ))

        segments = []
        if np is not None:
            try:
                values = np.asarray(
                    [row[:sample_w] for row in rows[:sample_h]],
                    dtype=np.float64,
                )
                v00 = values[:-1, :-1]
                v10 = values[:-1, 1:]
                v01 = values[1:, :-1]
                v11 = values[1:, 1:]
                crossing_count = (
                    ((v00 < level) & (level <= v10))
                    | ((v10 < level) & (level <= v00))
                ).astype(np.uint8)
                crossing_count += (
                    ((v10 < level) & (level <= v11))
                    | ((v11 < level) & (level <= v10))
                )
                crossing_count += (
                    ((v01 < level) & (level <= v11))
                    | ((v11 < level) & (level <= v01))
                )
                crossing_count += (
                    ((v00 < level) & (level <= v01))
                    | ((v01 < level) & (level <= v00))
                )
                active_rows, active_cols = np.nonzero(
                    (crossing_count == 2) | (crossing_count == 4)
                )
                for row, col in zip(active_rows.tolist(), active_cols.tolist()):
                    append_cell(
                        segments, col, row,
                        float(values[row, col]),
                        float(values[row, col + 1]),
                        float(values[row + 1, col]),
                        float(values[row + 1, col + 1]),
                    )
                return segments
            except (TypeError, ValueError):
                pass

        for row in range(sample_h - 1):
            for col in range(sample_w - 1):
                try:
                    append_cell(
                        segments, col, row,
                        float(rows[row][col]),
                        float(rows[row][col + 1]),
                        float(rows[row + 1][col]),
                        float(rows[row + 1][col + 1]),
                    )
                except (IndexError, TypeError, ValueError):
                    continue
        return segments

    @staticmethod
    def _contour_polylines(segments):
        """Join marching-squares fragments into continuous contour paths."""
        if not segments:
            return []

        def key(point):
            return round(float(point[0]), 6), round(float(point[1]), 6)

        adjacency = {}
        for index, (first, second) in enumerate(segments):
            adjacency.setdefault(key(first), []).append((index, 0))
            adjacency.setdefault(key(second), []).append((index, 1))
        unused = set(range(len(segments)))
        open_indices = [
            index
            for index, (first, second) in enumerate(segments)
            if len(adjacency.get(key(first), ())) == 1
            or len(adjacency.get(key(second), ())) == 1
        ]
        open_cursor = 0
        polylines = []
        while unused:
            while (
                open_cursor < len(open_indices)
                and open_indices[open_cursor] not in unused
            ):
                open_cursor += 1
            if open_cursor < len(open_indices):
                initial = open_indices[open_cursor]
                open_cursor += 1
            else:
                initial = next(iter(unused))
            first, second = segments[initial]
            if len(adjacency.get(key(second), ())) == 1 and len(adjacency.get(key(first), ())) != 1:
                first, second = second, first
            unused.remove(initial)
            polyline = [first, second]
            while True:
                endpoint_key = key(polyline[-1])
                continuation = next(
                    (
                        (index, side)
                        for index, side in adjacency.get(endpoint_key, ())
                        if index in unused
                    ),
                    None,
                )
                if continuation is None:
                    break
                index, side = continuation
                unused.remove(index)
                segment = segments[index]
                polyline.append(segment[1 - side])
                if key(polyline[-1]) == key(polyline[0]):
                    break
            if len(polyline) >= 2:
                polylines.append(polyline)
        return polylines

    @staticmethod
    def _smooth_contour_polyline(points, passes=1):
        """Apply restrained display smoothing without changing contour levels."""
        if len(points) < 3:
            return list(points)
        closed = (
            math.hypot(
                float(points[0][0]) - float(points[-1][0]),
                float(points[0][1]) - float(points[-1][1]),
            )
            <= 1e-5
        )
        smoothed = list(points)
        for _pass in range(max(0, int(passes))):
            if closed:
                ring = smoothed[:-1]
                refined = []
                for index, point in enumerate(ring):
                    following = ring[(index + 1) % len(ring)]
                    refined.extend((
                        (
                            point[0] * 0.75 + following[0] * 0.25,
                            point[1] * 0.75 + following[1] * 0.25,
                        ),
                        (
                            point[0] * 0.25 + following[0] * 0.75,
                            point[1] * 0.25 + following[1] * 0.75,
                        ),
                    ))
                smoothed = [*refined, refined[0]]
            else:
                refined = [smoothed[0]]
                for first, second in zip(smoothed, smoothed[1:]):
                    refined.extend((
                        (
                            first[0] * 0.75 + second[0] * 0.25,
                            first[1] * 0.75 + second[1] * 0.25,
                        ),
                        (
                            first[0] * 0.25 + second[0] * 0.75,
                            first[1] * 0.25 + second[1] * 0.75,
                        ),
                    ))
                smoothed = [*refined, smoothed[-1]]
        return smoothed

    def _height_contour_geometry(self, heightmap, interval):
        grid = heightmap.get("sample_grid") if isinstance(heightmap, dict) else {}
        rows = grid.get("rows") if isinstance(grid.get("rows"), list) else []
        masks = heightmap.get("surface_masks") if isinstance(heightmap.get("surface_masks"), dict) else {}
        ocean_rows = masks.get("ocean_rows") if isinstance(masks.get("ocean_rows"), list) else []
        cache_key = (
            id(heightmap),
            id(rows),
            id(ocean_rows) if ocean_rows else None,
            int(interval),
            heightmap.get("source_heightfield_fingerprint"),
            heightmap.get("sea_level_m"),
        )
        cached = self._height_contour_geometry_cache.get(cache_key)
        if cached is not None:
            return cached

        sea_level = heightmap.get("sea_level_m")
        level_paths = []
        for level in contour_levels_for_heightmap(heightmap, interval, max_levels=18):
            # The shoreline is rendered independently from the water mask.
            # Do not also render a nearby elevation isoline underneath it.
            if (
                sea_level is not None
                and abs(float(level) - float(sea_level)) < float(interval) * 0.45
            ):
                continue
            segments = self._heightmap_contour_segments(heightmap, level)
            level_paths.append((
                float(level),
                [
                    self._smooth_contour_polyline(polyline, passes=1)
                    for polyline in self._contour_polylines(segments)
                ],
            ))

        shoreline_paths = []
        if ocean_rows and len(ocean_rows) >= 2:
            mask_width = min(
                min(
                    (len(row) for row in ocean_rows if isinstance(row, list)),
                    default=0,
                ),
                int(grid.get("width", len(ocean_rows[0]) if ocean_rows else 0) or 0),
            )
            if mask_width >= 2:
                mask_heightmap = {
                    "sample_grid": {
                        "width": mask_width,
                        "height": min(len(ocean_rows), int(grid.get("height", len(ocean_rows)) or len(ocean_rows))),
                        "rows": [
                            [1.0 if value else 0.0 for value in row[:mask_width]]
                            for row in ocean_rows
                        ],
                    },
                }
                shoreline_paths = [
                    self._smooth_contour_polyline(polyline, passes=1)
                    for polyline in self._contour_polylines(
                        self._heightmap_contour_segments(mask_heightmap, 0.5)
                    )
                ]
        elif sea_level is not None:
            shoreline_paths = [
                self._smooth_contour_polyline(polyline, passes=1)
                for polyline in self._contour_polylines(
                    self._heightmap_contour_segments(heightmap, float(sea_level))
                )
            ]

        geometry = (level_paths, shoreline_paths)
        return self._cache_put(
            self._height_contour_geometry_cache,
            cache_key,
            geometry,
            limit=16,
        )

    def _height_contour_surface_for_layer(
        self, layer, pixels_per_map_pixel, regions_only=False, target_size=None,
    ):
        heightmap = layer.get("heightmap_model") if isinstance(layer, dict) else None
        grid = heightmap.get("sample_grid") if isinstance(heightmap, dict) else None
        rows = grid.get("rows") if isinstance(grid, dict) else None
        if not rows or len(rows) < 2:
            return None, None
        sample_h = min(len(rows), int(grid.get("height", len(rows)) or len(rows)))
        declared_width = int(grid.get("width", len(rows[0]) if rows else 0) or 0)
        sample_w = min(
            min((len(row) for row in rows[:sample_h] if isinstance(row, list)), default=0),
            declared_width,
        )
        if sample_w < 2 or sample_h < 2:
            return None, None

        requested_interval = height_marker_interval_m(pixels_per_map_pixel)
        interval = display_contour_interval_m(heightmap, requested_interval, max_levels=18)
        target_w = max(2, int((target_size or (512, 256))[0]))
        target_h = max(2, int((target_size or (512, 256))[1]))
        # Contours are vector-derived and then smoothly scaled with the map.
        # A 1280x720 cache is visually indistinguishable at normal line widths
        # but avoids multi-megapixel antialiasing stalls on activation.
        render_scale = min(1.0, 1280.0 / target_w, 720.0 / target_h)
        source_w = max(2, int(round(target_w * render_scale)))
        source_h = max(2, int(round(target_h * render_scale)))
        cache_key = (
            id(heightmap), id(rows), sample_w, sample_h, int(interval), bool(regions_only),
            source_w, source_h,
            float(heightmap.get("min_elevation_m", 0.0) or 0.0),
            float(heightmap.get("max_elevation_m", 0.0) or 0.0),
            heightmap.get("sea_level_m"),
        )
        cached = self._height_contour_surface_cache.get(cache_key)
        if cached is not None:
            return cached, interval

        cell_w = sample_w - 1
        cell_h = sample_h - 1
        scale_x = (source_w - 1) / max(1, cell_w)
        scale_y = (source_h - 1) / max(1, cell_h)
        surface = pygame.Surface((source_w, source_h), pygame.SRCALPHA)
        sea_level = heightmap.get("sea_level_m")
        major_step = max(float(interval) * 5.0, 1.0)
        level_paths, shoreline_paths = self._height_contour_geometry(
            heightmap, interval,
        )

        def screen_path(polyline):
            return [
                (point[0] * scale_x, point[1] * scale_y)
                for point in polyline
            ]

        for level, polylines in level_paths:
            is_major = abs(float(level) / major_step - round(float(level) / major_step)) < 1e-6
            if is_major:
                color = (224, 232, 238, 174 if regions_only else 116)
                line_width = 1
            elif sea_level is not None and float(level) < float(sea_level):
                color = (108, 162, 204, 138 if regions_only else 84)
                line_width = 1
            else:
                color = (206, 214, 220, 148 if regions_only else 92)
                line_width = 1
            for polyline in polylines:
                screen_points = screen_path(polyline)
                if len(screen_points) < 2:
                    continue
                closed = math.hypot(
                    screen_points[0][0] - screen_points[-1][0],
                    screen_points[0][1] - screen_points[-1][1],
                ) <= 1.0
                if line_width > 1:
                    pygame.draw.lines(
                        surface, color, closed, screen_points, line_width,
                    )
                pygame.draw.aalines(surface, color, closed, screen_points)

        shoreline_color = (116, 202, 246, 232 if regions_only else 198)
        for polyline in shoreline_paths:
            screen_points = screen_path(polyline)
            if len(screen_points) < 2:
                continue
            closed = math.hypot(
                screen_points[0][0] - screen_points[-1][0],
                screen_points[0][1] - screen_points[-1][1],
            ) <= 1.0
            pygame.draw.lines(surface, shoreline_color, closed, screen_points, 2)
            pygame.draw.aalines(surface, shoreline_color, closed, screen_points)
        self._cache_put(self._height_contour_surface_cache, cache_key, surface, limit=18)
        return surface, interval

    def _composite_refined_contours(
        self, base_surface, layer, pixels_per_map_pixel, regions_only,
    ):
        models = [
            model
            for model in (layer.get("refined_region_models") or [])
            if isinstance(model, dict)
            and isinstance(model.get("heightmap_model"), dict)
        ]
        if not models:
            return base_surface
        cache_key = (
            "refined_contours",
            id(base_surface),
            bool(regions_only),
            round(float(pixels_per_map_pixel), 5),
            tuple(
                (
                    model.get("entity_id"),
                    model.get("detail_level"),
                    model.get("refinement_revision", 0),
                    (model.get("heightmap_model") or {}).get(
                        "source_heightfield_fingerprint"
                    ),
                )
                for model in models
            ),
        )
        cached = self._height_contour_surface_cache.get(cache_key)
        if cached is not None:
            return cached

        composite = base_surface.copy()
        for model in models:
            uv = model.get("uv_bounds") or {}
            left = int(round(float(uv.get("min_u", 0.0)) * composite.get_width()))
            right = int(round(float(uv.get("max_u", 0.0)) * composite.get_width()))
            top = int(round(float(uv.get("min_v", 0.0)) * composite.get_height()))
            bottom = int(round(float(uv.get("max_v", 0.0)) * composite.get_height()))
            destination = pygame.Rect(
                left, top, max(1, right - left), max(1, bottom - top),
            ).clip(composite.get_rect())
            if destination.width <= 0 or destination.height <= 0:
                continue
            child_surface, _interval = self._height_contour_surface_for_layer(
                {"heightmap_model": model["heightmap_model"]},
                pixels_per_map_pixel,
                regions_only=regions_only,
                target_size=destination.size,
            )
            if child_surface is None:
                continue
            if child_surface.get_size() != destination.size:
                child_surface = pygame.transform.smoothscale(
                    child_surface, destination.size,
                )
            # Refined terrain replaces the parent heightfield in this patch.
            # Clear parent isolines first so a parent 0 m contour cannot float
            # over a child shoreline or locally evolved relief.
            composite.fill((0, 0, 0, 0), destination)
            composite.blit(child_surface, destination.topleft)
        return self._cache_put(
            self._height_contour_surface_cache,
            cache_key,
            composite,
            limit=18,
        )

    def _draw_height_contours(self, screen, layer, camera, regions_only=False):
        center = camera.world_to_screen((layer.get("x", 0.0), layer.get("y", 0.0)))
        if center is None:
            return
        pixel_w = max(1, int(float(layer.get("width_world", 1.0) or 1.0) * camera.zoom))
        pixel_h = max(1, int(float(layer.get("height_world", 1.0) or 1.0) * camera.zoom))
        rect = pygame.Rect(int(center[0] - pixel_w / 2), int(center[1] - pixel_h / 2), pixel_w, pixel_h)
        if not rect.colliderect(screen.get_rect()):
            return
        canvas_w = max(1, int(layer.get("canvas_width_px", pixel_w) or pixel_w))
        source, _interval = self._height_contour_surface_for_layer(
            layer, pixel_w / canvas_w, regions_only=regions_only,
            target_size=rect.size,
        )
        if source is None:
            return
        source = self._composite_refined_contours(
            source,
            layer,
            pixel_w / canvas_w,
            regions_only,
        )
        source = self._projected_spherical_surface(source, layer)
        previous_clip = screen.get_clip()
        screen.set_clip(rect.clip(screen.get_rect()))
        self._blit_scaled_layer(
            screen, source, rect, self._scaled_height_contour_cache,
            "height_contours_regions" if regions_only else "height_contours", smooth=True,
        )
        screen.set_clip(previous_clip)
        self._draw_planet_equator(screen, rect, layer)
        self._draw_map_frame(screen, rect, color=(110, 126, 142), width=1, crosshair=False)

    def _cache_put(self, cache, key, value, limit=None):
        cache[key] = value
        if limit is None:
            return value
        while len(cache) > limit:
            cache.pop(next(iter(cache)))
        return value

    def _projected_spherical_surface(self, source, layer):
        """Reproject an equirectangular texture around a movable globe front."""
        focus_x = float(layer.get("projection_focus_x", 0.0) or 0.0) % 1.0
        focus_y = max(-0.5, min(0.5, float(layer.get("projection_focus_y", 0.0) or 0.0)))
        width, height = source.get_size()
        focus_key_x = round(focus_x, 9)
        focus_key_y = round(focus_y, 9)
        if focus_key_x == 0.0 and focus_key_y == 0.0:
            return source
        if width * height > 512 * 256:
            source_key = (id(source), width, height, 512, 256)
            projected_source = self._projection_source_cache.get(source_key)
            if projected_source is None:
                projected_source = pygame.transform.smoothscale(source, (512, 256))
                self._cache_put(self._projection_source_cache, source_key, projected_source, limit=8)
            source = projected_source
            width, height = source.get_size()

        # Rotation must be identical for every map layer.  Quantizing by the
        # source dimensions made a 256px heightmap and a 512px land mask use
        # different globe centres even when they shared the same focus values.
        cache_key = (id(source), focus_key_x, focus_key_y, width, height, "oblique_equirectangular_v3")
        cached = self._projection_surface_cache.get(cache_key)
        if cached is not None:
            return cached
        longitude = focus_key_x * math.tau
        latitude = -focus_key_y * math.pi
        sin_lon, cos_lon = math.sin(longitude), math.cos(longitude)
        sin_lat, cos_lat = math.sin(latitude), math.cos(latitude)
        projected = pygame.Surface(source.get_size(), source.get_flags() & pygame.SRCALPHA, source.get_bitsize())
        coordinate_key = (width, height)
        coordinates = self._projection_coordinate_cache.get(coordinate_key)
        if coordinates is None:
            view_longitudes = [x / max(1, width) * math.tau - math.pi for x in range(width)]
            view_latitudes = [math.pi * (0.5 - y / max(1, height - 1)) for y in range(height)]
            coordinates = (
                [math.cos(value) for value in view_longitudes],
                [math.sin(value) for value in view_longitudes],
                [math.cos(value) for value in view_latitudes],
                [math.sin(value) for value in view_latitudes],
            )
            self._cache_put(self._projection_coordinate_cache, coordinate_key, coordinates, limit=6)
        longitude_cosines, longitude_sines, latitude_cosines, latitude_sines = coordinates
        if np is not None:
            lon_cos = np.asarray(longitude_cosines, dtype=np.float64)[:, None]
            lon_sin = np.asarray(longitude_sines, dtype=np.float64)[:, None]
            lat_cos = np.asarray(latitude_cosines, dtype=np.float64)[None, :]
            lat_sin = np.asarray(latitude_sines, dtype=np.float64)[None, :]
            view_x = lat_cos * lon_cos
            view_y = lat_cos * lon_sin
            tilted_x = cos_lat * view_x - sin_lat * lat_sin
            world_z = sin_lat * view_x + cos_lat * lat_sin
            world_x = cos_lon * tilted_x - sin_lon * view_y
            world_y = sin_lon * tilted_x + cos_lon * view_y
            source_longitudes = np.arctan2(world_y, world_x)
            source_latitudes = np.arcsin(np.clip(world_z, -1.0, 1.0))
            source_x_indices = np.rint((source_longitudes + math.pi) / math.tau * width).astype(np.int32) % width
            source_y_indices = np.clip(
                np.rint((0.5 - source_latitudes / math.pi) * (height - 1)).astype(np.int32),
                0,
                height - 1,
            )
            source_rgb = pygame.surfarray.array3d(source)
            pygame.surfarray.blit_array(projected, source_rgb[source_x_indices, source_y_indices])
            if source.get_flags() & pygame.SRCALPHA:
                source_alpha = pygame.surfarray.array_alpha(source)
                destination_alpha = pygame.surfarray.pixels_alpha(projected)
                destination_alpha[:, :] = source_alpha[source_x_indices, source_y_indices]
                del destination_alpha
            return self._cache_put(self._projection_surface_cache, cache_key, projected, limit=24)

        source_pixels = pygame.PixelArray(source)
        destination_pixels = pygame.PixelArray(projected)
        try:
            for destination_y in range(height):
                view_cos_lat = latitude_cosines[destination_y]
                view_sin_lat = latitude_sines[destination_y]
                for destination_x in range(width):
                    view_x = view_cos_lat * longitude_cosines[destination_x]
                    view_y = view_cos_lat * longitude_sines[destination_x]
                    view_z = view_sin_lat
                    # Ry(-latitude), followed by Rz(longitude), rotates the
                    # selected surface point onto the front of the view.
                    tilted_x = cos_lat * view_x - sin_lat * view_z
                    world_z = sin_lat * view_x + cos_lat * view_z
                    world_x = cos_lon * tilted_x - sin_lon * view_y
                    world_y = sin_lon * tilted_x + cos_lon * view_y
                    source_longitude = math.atan2(world_y, world_x)
                    source_latitude = math.asin(max(-1.0, min(1.0, world_z)))
                    source_x = int(round((source_longitude + math.pi) / math.tau * width)) % width
                    source_y = max(0, min(height - 1, int(round((0.5 - source_latitude / math.pi) * (height - 1)))))
                    destination_pixels[destination_x, destination_y] = source_pixels[source_x, source_y]
        finally:
            del destination_pixels
            del source_pixels
        return self._cache_put(self._projection_surface_cache, cache_key, projected, limit=24)

    @staticmethod
    def _projected_normalized_point(nx, ny, layer):
        return project_normalized_point(
            nx, ny, layer.get("projection_focus_x", 0.0), layer.get("projection_focus_y", 0.0)
        )

    def _draw_planet_equator(self, screen, rect, layer):
        if not layer.get("show_planet_equator") or rect.width < 8 or rect.height < 8:
            return
        previous = None
        for index in range(361):
            projected = self._projected_normalized_point(index / 360.0, 0.5, layer)
            point = (int(round(rect.x + projected[0] * rect.width)), int(round(rect.y + projected[1] * rect.height)))
            if previous is not None and abs(point[0] - previous[0]) < rect.width * 0.25 and abs(point[1] - previous[1]) < rect.height * 0.25:
                pygame.draw.line(screen, (28, 34, 42), previous, point, 3)
                pygame.draw.line(screen, (232, 190, 92), previous, point, 1)
            previous = point

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
        # Scaling the full world map for every wheel step is both slower and far
        # more memory hungry than scaling only the visible source window.
        viewport_area = screen_w * screen_h
        dest_area = max(1, dest_rect.width) * max(1, dest_rect.height)
        is_large_dest = (
            dest_rect.width > screen_w
            or dest_rect.height > screen_h
            or dest_area > viewport_area * 0.72
        )

        if is_large_dest:
            return self._blit_large_scaled_layer(
                screen,
                source_surface,
                dest_rect,
                visible,
                cache_prefix,
                smooth=smooth,
                alpha=alpha,
            )

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

    def _blit_large_scaled_layer(self, screen, source_surface, dest_rect, visible, cache_prefix, *, smooth=False, alpha=None):
        """Scale only a small viewport tile and reuse it during nearby pans."""
        requested_source = self._source_rect_for_visible_dest(source_surface, dest_rect, visible)
        if requested_source is None:
            return False

        cache_key = (cache_prefix, id(source_surface), bool(smooth), alpha)
        entry = self._large_scaled_layer_cache.get(cache_key)
        reusable = (
            isinstance(entry, dict)
            and entry.get("dest_size") == dest_rect.size
            and entry.get("source_rect") is not None
            and entry["source_rect"].contains(requested_source)
        )

        if not reusable:
            overscan = max(16, int(self._viewport_overscan_px))
            overscan_dest = visible.inflate(overscan * 2, overscan * 2).clip(dest_rect)
            source_rect = self._source_rect_for_visible_dest(source_surface, dest_rect, overscan_dest)
            if source_rect is None:
                return False

            offset_x = overscan_dest.x - dest_rect.x
            offset_y = overscan_dest.y - dest_rect.y
            scaled_size = (max(1, overscan_dest.width), max(1, overscan_dest.height))
            transform = pygame.transform.smoothscale if smooth else pygame.transform.scale
            scaled = transform(source_surface.subsurface(source_rect), scaled_size)
            if alpha is not None:
                scaled = scaled.copy()
                scaled.set_alpha(max(0, min(255, int(alpha))))
            entry = {
                "dest_size": dest_rect.size,
                "source_rect": source_rect,
                "dest_offset": (offset_x, offset_y),
                "surface": scaled,
            }
            self._cache_put(self._large_scaled_layer_cache, cache_key, entry, limit=8)

        offset_x, offset_y = entry["dest_offset"]
        screen.blit(entry["surface"], (dest_rect.x + offset_x, dest_rect.y + offset_y))
        return True

    def _draw_cached_alpha_fill(self, screen, rect, color, alpha):
        visible = rect.clip(screen.get_rect())
        if visible.width <= 0 or visible.height <= 0 or alpha <= 0:
            return
        rgb = self._coerce_rgb(color, fallback=(170, 180, 192))
        alpha = max(0, min(255, int(alpha)))
        cache_key = (screen.get_size(), rgb, alpha)
        overlay = self._alpha_fill_cache.get(cache_key)
        if overlay is None:
            overlay = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
            overlay.fill((*rgb, alpha))
            self._cache_put(self._alpha_fill_cache, cache_key, overlay, limit=6)
        source_rect = pygame.Rect(0, 0, visible.width, visible.height)
        screen.blit(overlay, visible.topleft, source_rect)

    def _draw_map_frame(self, screen, rect, color=(220, 220, 220), width=3, crosshair=True):
        viewport = screen.get_rect()
        if rect.left >= 0:
            pygame.draw.line(screen, color, (rect.left, max(0, rect.top)), (rect.left, min(viewport.bottom - 1, rect.bottom)), width)
        if rect.right <= viewport.right:
            pygame.draw.line(screen, color, (rect.right - 1, max(0, rect.top)), (rect.right - 1, min(viewport.bottom - 1, rect.bottom)), width)
        if rect.top >= 0:
            pygame.draw.line(screen, color, (max(0, rect.left), rect.top), (min(viewport.right - 1, rect.right), rect.top), width)
        if rect.bottom <= viewport.bottom:
            pygame.draw.line(screen, color, (max(0, rect.left), rect.bottom - 1), (min(viewport.right - 1, rect.right), rect.bottom - 1), width)
        if not crosshair:
            return
        if 0 <= rect.centery < viewport.height:
            pygame.draw.line(screen, (110, 125, 150), (max(0, rect.left), rect.centery), (min(viewport.right - 1, rect.right), rect.centery), 1)
        if 0 <= rect.centerx < viewport.width:
            pygame.draw.line(screen, (110, 125, 150), (rect.centerx, max(0, rect.top)), (rect.centerx, min(viewport.bottom - 1, rect.bottom)), 1)

    def _draw_image_rect_layer(self, screen, layer, camera):
        image_surface = layer.get("_prepared_surface")
        if image_surface is not None:
            pass
        elif layer.get("bundle_path"):
            image_surface = self._load_raster_bundle_surface(
                layer.get("bundle_path"),
                layer.get("bundle_layer_id"),
            )
        else:
            image_surface = self._load_image_surface(layer.get("image_path"))
        if image_surface is None:
            return
        image_surface = self._crop_surface_to_uv(
            image_surface,
            layer.get("source_uv_bounds"),
        )
        if "projection_focus_x" in layer or "projection_focus_y" in layer:
            image_surface = self._projected_spherical_surface(image_surface, layer)

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
        self._draw_planet_equator(screen, rect, layer)

        if layer.get("is_ghost_context") and layer.get("name"):
            text = self._render_text(
                layer.get("name", "location"),
                (210, 218, 230),
            )
            screen.blit(text, (rect.x + 6, rect.y + 6))

    def _crop_surface_to_uv(self, surface, source_uv_bounds):
        if surface is None or not isinstance(source_uv_bounds, dict):
            return surface
        try:
            min_u = max(0.0, min(1.0, float(source_uv_bounds["min_u"])))
            max_u = max(0.0, min(1.0, float(source_uv_bounds["max_u"])))
            min_v = max(0.0, min(1.0, float(source_uv_bounds["min_v"])))
            max_v = max(0.0, min(1.0, float(source_uv_bounds["max_v"])))
        except (KeyError, TypeError, ValueError):
            return surface
        if max_u <= min_u or max_v <= min_v:
            return surface
        cache_key = (
            id(surface),
            round(min_u, 9),
            round(max_u, 9),
            round(min_v, 9),
            round(max_v, 9),
        )
        cached = self._cropped_surface_cache.get(cache_key)
        if cached is not None:
            return cached
        width, height = surface.get_size()
        left = max(0, min(width - 1, int(math.floor(min_u * width))))
        top = max(0, min(height - 1, int(math.floor(min_v * height))))
        right = max(left + 1, min(width, int(math.ceil(max_u * width))))
        bottom = max(top + 1, min(height, int(math.ceil(max_v * height))))
        cropped = surface.subsurface(
            pygame.Rect(left, top, right - left, bottom - top)
        )
        return self._cache_put(
            self._cropped_surface_cache,
            cache_key,
            cropped,
            limit=16,
        )

    def _reference_land_surface_for_layer(self, layer):
        polygons = layer.get("polygons") if isinstance(layer.get("polygons"), list) else []
        if not polygons:
            return None
        cache_key = (
            id(polygons), len(polygons),
            self._coerce_rgb(layer.get("color"), fallback=(82, 108, 92)),
            self._coerce_rgb(layer.get("border_color"), fallback=(218, 236, 220)),
            int(layer.get("border_width", 1) or 0),
        )
        cached = self._reference_land_surface_cache.get(cache_key)
        if cached is not None:
            return cached
        source_w, source_h = 1024, 512
        surface = pygame.Surface((source_w, source_h), pygame.SRCALPHA)
        width_world = max(1e-9, float(layer.get("width_world", 1.0) or 1.0))
        height_world = max(1e-9, float(layer.get("height_world", 1.0) or 1.0))
        left = float(layer.get("x", 0.0) or 0.0) - width_world * 0.5
        top = float(layer.get("y", 0.0) or 0.0) - height_world * 0.5
        fill_color = self._coerce_rgb(layer.get("color"), fallback=(82, 108, 92))
        border_color = self._coerce_rgb(layer.get("border_color"), fallback=(218, 236, 220))
        border_width = max(0, int(layer.get("border_width", 1) or 0))
        for polygon in polygons:
            points = [
                (
                    int(round((float(point[0]) - left) / width_world * (source_w - 1))),
                    int(round((float(point[1]) - top) / height_world * (source_h - 1))),
                )
                for point in polygon
            ]
            if len(points) >= 3:
                pygame.draw.polygon(surface, fill_color, points)
                if border_width > 0:
                    pygame.draw.polygon(surface, border_color, points, border_width)
        return self._cache_put(self._reference_land_surface_cache, cache_key, surface, limit=6)

    def _draw_reference_land_layer(self, screen, layer, camera):
        source = self._reference_land_surface_for_layer(layer)
        if source is None:
            return
        prepared = dict(layer)
        prepared["_prepared_surface"] = source
        prepared["alpha"] = None
        self._draw_image_rect_layer(screen, prepared, camera)

    def _is_batchable_static_outline(self, layer):
        try:
            min_zoom = float(layer.get("min_zoom", 0.0) or 0.0)
        except (TypeError, ValueError):
            min_zoom = 0.0
        return (
            layer.get("shape") == "polygon"
            and bool(layer.get("outline_only"))
            and bool(layer.get("suppress_label"))
            and min_zoom <= 0.0
            and "projection_geometry_copy" not in layer
            and not layer.get("is_ghost_context")
            and not layer.get("is_placement_ancestor")
            and not layer.get("render_when_interacting_only")
        )

    def _static_outline_surface(self, layers, root_layer):
        cache_key = (id(layers), id(root_layer), len(layers))
        cached = self._static_outline_surface_cache.get(cache_key)
        if cached is not None:
            return cached
        source_w, source_h = 1536, 768
        surface = pygame.Surface((source_w, source_h), pygame.SRCALPHA)
        width_world = max(1e-9, float(root_layer.get("width_world", 1.0) or 1.0))
        height_world = max(1e-9, float(root_layer.get("height_world", 1.0) or 1.0))
        left = float(root_layer.get("x", 0.0) or 0.0) - width_world * 0.5
        top = float(root_layer.get("y", 0.0) or 0.0) - height_world * 0.5
        for layer in layers:
            if not self._is_batchable_static_outline(layer):
                continue
            points = [
                (
                    int(round((float(point[0]) - left) / width_world * (source_w - 1))),
                    int(round((float(point[1]) - top) / height_world * (source_h - 1))),
                )
                for point in layer.get("points") or []
            ]
            if len(points) >= 3:
                color = self._coerce_rgb(layer.get("border_color") or layer.get("color"), fallback=(170, 180, 194))
                pygame.draw.polygon(surface, color, points, max(1, int(layer.get("border_width", 1) or 1)))
        return self._cache_put(self._static_outline_surface_cache, cache_key, surface, limit=4)

    def _draw_static_outline_batch(self, screen, layers, root_layer, camera):
        source = self._static_outline_surface(layers, root_layer)
        prepared = dict(root_layer)
        prepared["shape"] = "image_rect"
        prepared["_prepared_surface"] = source
        prepared["alpha"] = None
        prepared["name"] = None
        prepared["show_planet_equator"] = False
        # Polygon points are transformed into the focused view before this
        # batch is rasterized. Inheriting these fields projected the completed
        # outline texture a second time and detached borders from the land.
        prepared.pop("projection_focus_x", None)
        prepared.pop("projection_focus_y", None)
        self._draw_image_rect_layer(screen, prepared, camera)

    def _material_composite_surface(self, material_layer, heightmap_layer):
        heightmap = heightmap_layer.get("heightmap_model") if isinstance(heightmap_layer, dict) else None
        sample_grid = heightmap.get("sample_grid") if isinstance(heightmap, dict) else None
        rows = sample_grid.get("rows") if isinstance(sample_grid, dict) else None
        if not rows:
            return None
        # The Material Distribution layer is intentionally a full-strength
        # view.  Do not first apply the subtle normal-map material tint and
        # then stack the same raster a second time.
        terrain_layer = dict(heightmap_layer)
        terrain_layer.pop("surface_material_layer", None)
        terrain_layer.pop("surface_material_opacity", None)
        terrain_surface = self._heightmap_surface_for_layer(terrain_layer, heightmap, rows)
        if terrain_surface is None:
            return None
        return self._surface_material_composite(
            terrain_surface,
            material_layer,
            opacity=material_layer.get("alpha", 232),
        )

    def _surface_material_composite(self, terrain_surface, material_layer, opacity=92):
        """Tint terrain with the probabilistic material raster while retaining relief."""
        if terrain_surface is None or not isinstance(material_layer, dict):
            return terrain_surface
        if material_layer.get("bundle_path"):
            material_surface = self._load_raster_bundle_surface(
                material_layer.get("bundle_path"),
                material_layer.get("bundle_layer_id"),
            )
        else:
            material_surface = self._load_image_surface(material_layer.get("image_path"))
        if material_surface is None:
            return terrain_surface
        source_uv_bounds = material_layer.get("source_uv_bounds")
        material_surface = self._crop_surface_to_uv(
            material_surface,
            source_uv_bounds,
        )
        alpha = max(0, min(255, int(opacity or 0)))
        bounds_key = (
            tuple(sorted(source_uv_bounds.items()))
            if isinstance(source_uv_bounds, dict)
            else None
        )
        cache_key = (id(terrain_surface), id(material_surface), alpha, bounds_key)
        cached = self._material_composite_cache.get(cache_key)
        if cached is not None:
            return cached
        if material_surface.get_size() != terrain_surface.get_size():
            material_surface = pygame.transform.smoothscale(
                material_surface,
                terrain_surface.get_size(),
            )
        else:
            material_surface = material_surface.copy()
        material_surface.set_alpha(alpha)
        composite = terrain_surface.copy()
        composite.blit(material_surface, (0, 0))
        return self._cache_put(self._material_composite_cache, cache_key, composite, limit=8)

    def _heightmap_color(self, elevation, heightmap, has_ice=False, layer=None):
        return self._heightmap_color_from_context(
            elevation,
            self._heightmap_color_context(heightmap, layer),
            has_ice=has_ice,
        )

    def _heightmap_color_context(self, heightmap, layer=None):
        sea_level_value = heightmap.get("sea_level_m")
        layer = layer if isinstance(layer, dict) else {}
        weathering = layer.get("surface_weathering_model")
        if not isinstance(weathering, dict):
            weathering = {}
        radar_bright = weathering.get("radar_bright_highlands")
        if not isinstance(radar_bright, dict):
            radar_bright = {}
        return {
            "has_ocean": sea_level_value is not None,
            "sea_level": 0.0 if sea_level_value is None else float(sea_level_value or 0.0),
            "min_elevation": float(heightmap.get("min_elevation_m", -4000.0) or -4000.0),
            "max_elevation": float(heightmap.get("max_elevation_m", 4000.0) or 4000.0),
            "palette": self._surface_palette_colors(layer),
            "radar_bright_highlands": bool(radar_bright.get("enabled")),
            "radar_bright_threshold_m": float(radar_bright.get("elevation_threshold_m", 4700.0) or 4700.0),
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

        land_base = sea_level if has_ocean else min_elevation
        relief = max(0.0, min(1.0, (elevation - land_base) / max(1.0, max_elevation - land_base)))
        if relief < 0.45:
            color = self._mix_rgb(land_dark, land_mid, relief / 0.45)
        elif relief < 0.82:
            color = self._mix_rgb(land_mid, land_high, (relief - 0.45) / 0.37)
        else:
            color = self._mix_rgb(land_high, (214, 212, 196), (relief - 0.82) / 0.18)
        if context.get("radar_bright_highlands") and elevation >= context.get("radar_bright_threshold_m", 4700.0):
            excess = min(1.0, (elevation - context["radar_bright_threshold_m"]) / 2500.0)
            color = self._mix_rgb(color, (244, 218, 154), 0.32 + 0.24 * excess)
        return color

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
        has_projection_focus = abs(float(layer.get("projection_focus_x", 0.0) or 0.0)) > 1e-9 or abs(float(layer.get("projection_focus_y", 0.0) or 0.0)) > 1e-9
        if (
            layer.get("render_mode") != "true_color"
            and cell_cols * cell_rows <= 4096
            and not has_projection_focus
        ):
            self._draw_heightmap_grid_cells(screen, rect, layer, heightmap, rows, cell_cols, cell_rows)
        else:
            heightmap_surface = self._heightmap_surface_for_layer(layer, heightmap, rows)
            if heightmap_surface is not None:
                heightmap_surface = self._composite_refined_surface(heightmap_surface, layer, "heightmap")
                heightmap_surface = self._projected_spherical_surface(heightmap_surface, layer)
                self._blit_scaled_layer(
                    screen,
                    heightmap_surface,
                    rect,
                    self._scaled_heightmap_cache,
                    "heightmap",
                    smooth=True,
                )
        screen.set_clip(clip)

        self._draw_planet_equator(screen, rect, layer)
        self._draw_map_frame(screen, rect, color=(75, 92, 112), width=1, crosshair=False)
        # The border is a viewport edge, not a fixed planetary seam.

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

    def _true_color_surface_for_layer(self, layer, heightmap):
        material_layer = layer.get("surface_material_layer")
        material_surface = None
        if isinstance(material_layer, dict):
            if material_layer.get("bundle_path"):
                material_surface = self._load_raster_bundle_surface(
                    material_layer.get("bundle_path"),
                    material_layer.get("bundle_layer_id"),
                )
            else:
                material_surface = self._load_image_surface(
                    material_layer.get("image_path")
                )
            material_surface = self._crop_surface_to_uv(
                material_surface,
                material_layer.get("source_uv_bounds"),
            )
        material_components = []
        for material_component in layer.get("surface_material_layers") or []:
            if not isinstance(material_component, dict):
                continue
            if material_component.get("bundle_path"):
                component_surface = self._load_raster_bundle_surface(
                    material_component.get("bundle_path"),
                    material_component.get("bundle_layer_id"),
                )
            else:
                component_surface = self._load_image_surface(
                    material_component.get("image_path")
                )
            component_surface = self._crop_surface_to_uv(
                component_surface,
                material_component.get("source_uv_bounds"),
            )
            if component_surface is not None:
                component = dict(material_component)
                component["surface"] = component_surface
                material_components.append(component)
        model = layer.get("true_color_model") or {}
        cache_key = (
            id(heightmap),
            id((heightmap.get("sample_grid") or {}).get("rows")),
            repr(model),
            id(material_surface),
            tuple(id(item.get("surface")) for item in material_components),
            id(layer.get("water_cycle_model")),
            id(layer.get("surface_evolution_model")),
            id(layer.get("surface_exposure_model")),
            id(layer.get("surface_geomorphology_model")),
            id(layer.get("atmosphere_model")),
        )
        cached = self._true_color_surface_cache.get(cache_key)
        if cached is not None:
            return cached
        surface = render_true_color_surface(
            heightmap,
            model,
            material_surface=material_surface,
            material_components=material_components,
            water_cycle=layer.get("water_cycle_model"),
            surface_evolution=layer.get("surface_evolution_model"),
            surface_exposure=layer.get("surface_exposure_model"),
            surface_geomorphology=layer.get("surface_geomorphology_model"),
            atmosphere=layer.get("atmosphere_model"),
        )
        if surface is not None:
            self._cache_put(
                self._true_color_surface_cache,
                cache_key,
                surface,
                limit=12,
            )
        return surface

    def _heightmap_surface_for_layer(self, layer, heightmap, rows):
        if layer.get("render_mode") == "true_color":
            return self._true_color_surface_for_layer(layer, heightmap)
        cell_cols = max(1, min(len(row) for row in rows) - 1)
        cell_rows = max(1, len(rows) - 1)
        masks = heightmap.get("surface_masks") if isinstance(heightmap.get("surface_masks"), dict) else {}
        ice_rows = masks.get("ice_rows") if isinstance(masks.get("ice_rows"), list) else []
        base_cache_key = (
            "terrain",
            id(heightmap),
            id(rows),
            id(ice_rows),
            repr(layer.get("heightmap_color_context_override")),
            repr(layer.get("surface_palette")),
            repr(layer.get("color")),
            repr(layer.get("display_color")),
            repr(layer.get("surface_weathering_model")),
            cell_cols,
            cell_rows,
        )
        surface = self._heightmap_surface_cache.get(base_cache_key)
        if surface is None:
            color_context = layer.get("heightmap_color_context_override")
            if not isinstance(color_context, dict):
                color_context = self._heightmap_color_context(heightmap, layer)
            surface = pygame.Surface((cell_cols, cell_rows))
            color_lut = {}
            min_elevation = float(color_context.get("min_elevation", -4000.0))
            elevation_span = max(1.0, float(color_context.get("max_elevation", 4000.0)) - min_elevation)
            spacing_x = max(0.001, float(heightmap.get("sample_spacing_x_m") or heightmap.get("equator_resolution_m_per_px") or 1.0))
            spacing_y = max(0.001, float(heightmap.get("sample_spacing_y_m") or spacing_x))
            detail_level = int(heightmap.get("map_detail_level", 0) or 0)
            vertical_exaggeration = max(1.0, 5.0 - detail_level * 0.62)
            lut_steps = 511
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
                    elevation_bin = max(0, min(lut_steps, int((elevation - min_elevation) / elevation_span * lut_steps)))
                    color_key = (elevation_bin, has_ice)
                    color = color_lut.get(color_key)
                    if color is None:
                        representative_elevation = min_elevation + elevation_span * elevation_bin / lut_steps
                        color = self._heightmap_color_from_context(
                            representative_elevation,
                            color_context,
                            has_ice=has_ice,
                        )
                        color_lut[color_key] = color
                    # Directional relief shading exposes valleys and ridges
                    # that an elevation-only ramp hides.  Moderate vertical
                    # exaggeration is visual only; stored elevations remain
                    # the simulation truth.
                    left = float(row_a[max(0, col_index - 1)] or 0.0)
                    right = float(row_a[min(len(row_a) - 1, col_index + 1)] or 0.0)
                    upper_row = rows[max(0, row_index - 1)]
                    lower_row = rows[min(len(rows) - 1, row_index + 1)]
                    up = float(upper_row[min(col_index, len(upper_row) - 1)] or 0.0)
                    down = float(lower_row[min(col_index, len(lower_row) - 1)] or 0.0)
                    dzdx = (right - left) / (2.0 * spacing_x) * vertical_exaggeration
                    dzdy = (down - up) / (2.0 * spacing_y) * vertical_exaggeration
                    normal_length = math.sqrt(dzdx * dzdx + dzdy * dzdy + 1.0)
                    illumination = max(0.0, min(1.0, (dzdx * 0.48 + dzdy * 0.48 + 0.735) / normal_length))
                    shade = 0.78 + illumination * 0.34
                    color = tuple(max(0, min(255, int(channel * shade))) for channel in color)
                    surface.set_at((col_index, row_index), color)
            self._cache_put(self._heightmap_surface_cache, base_cache_key, surface, limit=16)

        surface = self._surface_material_composite(
            surface,
            layer.get("surface_material_layer"),
            opacity=layer.get("surface_material_opacity", 0),
        )

        tint = layer.get("atmosphere_tint")
        opacity = max(0.0, min(1.0, float(layer.get("atmosphere_opacity", 0.0) or 0.0)))
        if not (isinstance(tint, (list, tuple)) and len(tint) >= 3 and opacity > 0.0):
            return surface

        atmosphere_cache_key = (
            "atmosphere",
            id(surface),
            tuple(tint[:3]),
            round(opacity, 4),
        )
        tinted = self._heightmap_surface_cache.get(atmosphere_cache_key)
        if tinted is None:
            tinted = surface.copy()
            overlay = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
            overlay.fill((*self._coerce_rgb(tint), round(opacity * 255)))
            tinted.blit(overlay, (0, 0))
            self._cache_put(self._heightmap_surface_cache, atmosphere_cache_key, tinted, limit=16)
        return tinted

    def _composite_refined_surface(self, base_surface, layer, surface_kind):
        models = layer.get("refined_region_models") if isinstance(layer.get("refined_region_models"), list) else []
        models = [model for model in models if isinstance(model, dict) and isinstance(model.get(f"{surface_kind}_model"), dict)]
        if not models:
            return base_surface
        root_level = int((layer.get("heightmap_model") or {}).get("map_detail_level", 0) or 0)
        maximum_level = max(int(model.get("detail_level", root_level) or root_level) for model in models)
        scale = 2 ** min(3, max(1, maximum_level - root_level))
        target_size = (min(2048, base_surface.get_width() * scale), min(1024, base_surface.get_height() * scale))
        cache_key = ("refined_composite", surface_kind, id(base_surface), tuple((model.get("entity_id"), model.get("detail_level"), model.get("refinement_revision", 0)) for model in models), target_size)
        cached = self._heightmap_surface_cache.get(cache_key) if surface_kind == "heightmap" else self._hydrology_surface_cache.get(cache_key)
        if cached is not None:
            return cached
        composite = pygame.transform.scale(base_surface, target_size)
        for model in models:
            uv = model.get("uv_bounds") or {}
            left = int(round(float(uv.get("min_u", 0.0)) * target_size[0]))
            right = int(round(float(uv.get("max_u", 0.0)) * target_size[0]))
            top = int(round(float(uv.get("min_v", 0.0)) * target_size[1]))
            bottom = int(round(float(uv.get("max_v", 0.0)) * target_size[1]))
            destination = pygame.Rect(left, top, max(1, right - left), max(1, bottom - top)).clip(composite.get_rect())
            if destination.width <= 0 or destination.height <= 0:
                continue
            if surface_kind == "heightmap":
                child_model = model["heightmap_model"]
                child_grid = child_model.get("sample_grid") or {}
                child_rows = child_grid.get("rows") or []
                child_layer = dict(layer)
                child_layer.pop("refined_region_models", None)
                child_layer["heightmap_model"] = child_model
                for field in (
                    "water_cycle_model",
                    "surface_evolution_model",
                    "surface_exposure_model",
                    "surface_geomorphology_model",
                    "atmosphere_model",
                    "surface_palette",
                    "true_color_model",
                ):
                    if model.get(field) is not None:
                        child_layer[field] = model.get(field)
                child_heatmaps = model.get("material_heatmap_model")
                if isinstance(child_heatmaps, dict):
                    child_material = child_heatmaps.get("composite_layer")
                    if isinstance(child_material, dict):
                        child_layer["surface_material_layer"] = child_material
                    child_layer["surface_material_layers"] = [
                        dict(material_layer)
                        for material_layer in child_heatmaps.get("layers") or []
                        if isinstance(material_layer, dict)
                    ]
                if child_layer.get("render_mode") == "true_color":
                    child_recipe = dict(child_layer.get("true_color_model") or {})
                    child_recipe["seed"] = str(
                        child_model.get("map_seed")
                        or child_model.get("material_distribution_seed")
                        or model.get("entity_id")
                        or child_recipe.get("seed")
                        or "region"
                    )
                    child_layer["true_color_model"] = child_recipe
                # All nested patches use the root map's absolute elevation
                # palette.  Normalizing each child to its own local min/max
                # turned ordinary refinement footprints into pale polygons.
                child_layer["heightmap_color_context_override"] = self._heightmap_color_context(
                    layer.get("heightmap_model") or {}, layer,
                )
                child_surface = self._heightmap_surface_for_layer(child_layer, child_model, child_rows) if child_rows else None
            else:
                child_surface = self._hydrology_surface_for_layer(
                    {
                        "climate_display_mode": layer.get(
                            "climate_display_mode", "koppen"
                        )
                    },
                    model["water_cycle_model"],
                )
            if child_surface is None:
                continue
            patch = pygame.transform.scale(child_surface, destination.size).convert_alpha()
            feather = min(12, max(0, min(destination.width, destination.height) // 8))
            if feather >= 2:
                alpha_mask = pygame.Surface(destination.size, pygame.SRCALPHA)
                for inset in range(feather + 1):
                    alpha = int(round(255 * inset / feather))
                    mask_rect = pygame.Rect(
                        inset,
                        inset,
                        destination.width - inset * 2,
                        destination.height - inset * 2,
                    )
                    if mask_rect.width <= 0 or mask_rect.height <= 0:
                        break
                    pygame.draw.rect(alpha_mask, (255, 255, 255, alpha), mask_rect)
                patch.blit(alpha_mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
            composite.blit(patch, destination.topleft)
        cache = self._heightmap_surface_cache if surface_kind == "heightmap" else self._hydrology_surface_cache
        return self._cache_put(cache, cache_key, composite, limit=12)

    def _koppen_class_colors(self, water_cycle):
        colors = {}
        for climate_class in water_cycle.get("koppen_classes") or []:
            if isinstance(climate_class, dict) and climate_class.get("id"):
                colors[str(climate_class["id"])] = self._coerce_rgb(
                    climate_class.get("color"),
                    fallback=(150, 150, 150),
                )
        return colors

    def _hydrology_surface_for_layer(self, layer, water_cycle):
        climate_grid = water_cycle.get("climate_grid") if isinstance(water_cycle, dict) else {}
        display_mode = str(layer.get("climate_display_mode") or "koppen")
        if display_mode == "annual_temperature":
            field_name = "temperature_rows_k"
        elif display_mode == "annual_precipitation":
            field_name = "annual_precipitation_rows_mm"
        else:
            field_name = (
                "koppen_rows"
                if isinstance(climate_grid.get("koppen_rows"), list)
                else "rows"
            )
        rows = (
            climate_grid.get(field_name)
            if isinstance(climate_grid.get(field_name), list)
            else []
        )
        if not rows:
            return None
        row_count = len(rows)
        col_count = min(len(row) for row in rows if row)
        if row_count <= 0 or col_count <= 0:
            return None

        elevation_rows = climate_grid.get("elevation_rows") if isinstance(climate_grid.get("elevation_rows"), list) else []
        lakes = water_cycle.get("lakes") if isinstance(water_cycle.get("lakes"), list) else []
        cache_key = (
            id(water_cycle),
            display_mode,
            id(rows),
            id(elevation_rows),
            id(lakes),
            col_count,
            row_count,
        )
        cached = self._hydrology_surface_cache.get(cache_key)
        if cached is not None:
            return cached

        elevations = [
            float(value or 0.0)
            for row in elevation_rows[:row_count]
            for value in (row[:col_count] if isinstance(row, list) else [])
        ]
        min_elevation = min(elevations) if elevations else 0.0
        max_elevation = max(elevations) if elevations else 1.0
        elevation_span = max(1.0, max_elevation - min_elevation)

        colors = self._koppen_class_colors(water_cycle)
        numeric_values = [
            float(value)
            for row in rows
            for value in row[:col_count]
            if isinstance(value, (int, float))
        ]
        numeric_min = min(numeric_values) if numeric_values else 0.0
        numeric_max = max(numeric_values) if numeric_values else 1.0
        numeric_span = max(1e-9, numeric_max - numeric_min)
        surface = pygame.Surface((col_count, row_count))
        for row_index, row in enumerate(rows):
            for col_index, field_value in enumerate(row[:col_count]):
                if display_mode == "annual_temperature":
                    value = float(field_value)
                    normalized = max(
                        0.0, min(1.0, (value - numeric_min) / numeric_span)
                    )
                    if normalized < 0.5:
                        color = self._mix_rgb(
                            (54, 94, 164),
                            (202, 202, 130),
                            normalized * 2.0,
                        )
                    else:
                        color = self._mix_rgb(
                            (202, 202, 130),
                            (210, 66, 48),
                            (normalized - 0.5) * 2.0,
                        )
                elif display_mode == "annual_precipitation":
                    value = max(0.0, float(field_value))
                    normalized = max(
                        0.0,
                        min(1.0, math.log1p(value) / math.log1p(5000.0)),
                    )
                    if normalized < 0.5:
                        color = self._mix_rgb(
                            (212, 180, 108),
                            (72, 150, 96),
                            normalized * 2.0,
                        )
                    else:
                        color = self._mix_rgb(
                            (72, 150, 96),
                            (42, 92, 168),
                            (normalized - 0.5) * 2.0,
                        )
                else:
                    color = colors.get(str(field_value), (126, 128, 126))
                if elevation_rows and row_index < len(elevation_rows) and col_index < len(elevation_rows[row_index]):
                    try:
                        elevation = float(elevation_rows[row_index][col_index] or 0.0)
                    except (TypeError, ValueError):
                        elevation = 0.0
                    elevation_norm = max(0.0, min(1.0, (elevation - min_elevation) / elevation_span))
                    ocean_value = (
                        str(field_value) == "Ocean"
                        if display_mode == "koppen"
                        else False
                    )
                    shade = 0.76 + (1.0 - elevation_norm) * 0.14 if ocean_value else 0.78 + elevation_norm * 0.24
                    color = tuple(max(0, min(255, int(channel * shade))) for channel in color)
                surface.set_at((col_index, row_index), color)

        for lake in lakes:
            if not isinstance(lake, dict):
                continue
            # Single-cell depressions remain part of hydrologic truth, but at
            # this raster scale they read as isolated square pixels rather
            # than bounded ponds. Their object-scale outlines belong to a
            # deeper map level.
            if int(lake.get("cell_count", 0) or 0) < 2:
                continue
            depth = float(lake.get("maximum_depth_m", 0.0) or 0.0)
            lake_color = self._mix_rgb((62, 132, 178), (24, 76, 132), min(1.0, depth / 900.0))
            for cell in lake.get("cells") or []:
                if isinstance(cell, (list, tuple)) and len(cell) >= 2:
                    x, y = int(cell[0]), int(cell[1])
                    if 0 <= x < col_count and 0 <= y < row_count:
                        surface.set_at((x, y), lake_color)

        return self._cache_put(
            self._hydrology_surface_cache,
            cache_key,
            surface,
            limit=16,
        )

    def _projected_reference_hydrology(self, water_cycle, layer, max_river_rank=6):
        """Cache expensive spherical projection for authored hydrography."""
        focus_x = float(layer.get("projection_focus_x", 0.0) or 0.0) % 1.0
        focus_y = max(-0.5, min(0.5, float(layer.get("projection_focus_y", 0.0) or 0.0)))
        key = (id(water_cycle), round(focus_x * 512), round(focus_y * 512), int(max_river_rank))
        cached = self._projected_reference_hydrology_cache.get(key)
        if cached is not None:
            return cached
        lakes = []
        for lake in water_cycle.get("reference_lakes") or []:
            if not isinstance(lake, dict):
                continue
            points = [
                self._projected_normalized_point(point.get("x", 0.0), point.get("y", 0.0), layer)
                for point in lake.get("points") or []
                if isinstance(point, dict)
            ]
            lakes.append((lake, points))
        rivers = {}
        for river in water_cycle.get("rivers") or []:
            if not isinstance(river, dict) or not str(river.get("source", "")).startswith("Natural Earth"):
                continue
            if int(river.get("scalerank", 99) or 0) > int(max_river_rank):
                continue
            rivers[id(river)] = [
                self._projected_normalized_point(point.get("x", 0.0), point.get("y", 0.0), layer)
                for point in river.get("display_points") or river.get("points") or []
                if isinstance(point, dict)
            ]
        return self._cache_put(
            self._projected_reference_hydrology_cache, key, (lakes, rivers), limit=12,
        )

    def _reference_hydrology_overlay(self, water_cycle, layer, rect, max_river_rank):
        focus_x = float(layer.get("projection_focus_x", 0.0) or 0.0) % 1.0
        focus_y = max(-0.5, min(0.5, float(layer.get("projection_focus_y", 0.0) or 0.0)))
        key = (
            id(water_cycle), round(focus_x * 512), round(focus_y * 512),
            rect.width, rect.height, int(max_river_rank),
        )
        cached = self._reference_hydrology_overlay_cache.get(key)
        if cached is not None:
            return cached
        overlay = pygame.Surface(rect.size, pygame.SRCALPHA)
        lakes, rivers = self._projected_reference_hydrology(water_cycle, layer, max_river_rank)
        for lake, projected_points in lakes:
            points = [(int(x * rect.width), int(y * rect.height)) for x, y in projected_points]
            seam_crossing = any(abs(points[index][0] - points[index - 1][0]) > rect.width * 0.5 for index in range(1, len(points)))
            if len(points) >= 3 and not seam_crossing:
                pygame.draw.polygon(overlay, (42, 111, 169), points)
                pygame.draw.aalines(overlay, (88, 164, 210), True, points)
        for river in water_cycle.get("rivers") or []:
            projected_points = rivers.get(id(river))
            if projected_points is None:
                continue
            points = [(int(x * rect.width), int(y * rect.height)) for x, y in projected_points]
            stream_order = max(1, int(river.get("stream_order", 1) or 1))
            line_width = max(1, min(6, stream_order - 1 + int(float(river.get("flow", 0.1) or 0.1) * 3)))
            role = river.get("network_role")
            color = (112, 198, 244) if role == "feeder" else ((72, 164, 232) if role == "tributary" else (48, 136, 220))
            segment = []
            for point in points:
                if segment and (abs(point[0] - segment[-1][0]) > rect.width * 0.5 or abs(point[1] - segment[-1][1]) > rect.height * 0.55):
                    if len(segment) >= 2:
                        pygame.draw.lines(overlay, color, False, segment, line_width)
                    segment = []
                segment.append(point)
            if len(segment) >= 2:
                pygame.draw.lines(overlay, color, False, segment, line_width)
        return self._cache_put(self._reference_hydrology_overlay_cache, key, overlay, limit=12)

    def _draw_hydrology_layer(self, screen, layer, camera):
        water_cycle = layer.get("water_cycle_model") if isinstance(layer, dict) else None
        surface = self._hydrology_surface_for_layer(layer, water_cycle)
        if surface is None:
            return
        surface = self._composite_refined_surface(surface, layer, "water_cycle")

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
            self._projected_spherical_surface(surface, layer),
            rect,
            self._scaled_hydrology_cache,
            "hydrology",
            smooth=True,
        )
        ocean_model = water_cycle.get("ocean_circulation_model") if isinstance(water_cycle, dict) else None
        vector_rows = ocean_model.get("vector_rows") if isinstance(ocean_model, dict) else None
        sst_rows = ocean_model.get("sea_surface_temperature_rows_k") if isinstance(ocean_model, dict) else None
        if isinstance(vector_rows, list) and vector_rows:
            current_h = len(vector_rows)
            current_w = min((len(row) for row in vector_rows if isinstance(row, list)), default=0)
            stride = max(2, math.ceil(current_w / 28), math.ceil(current_h / 14)) if current_w else 2
            cell_w = rect.width / max(1, current_w - 1)
            cell_h = rect.height / max(1, current_h - 1)
            arrow_scale = max(4.0, min(22.0, min(abs(cell_w), abs(cell_h)) * stride * 0.62))
            for y in range(stride // 2, current_h, stride):
                for x in range(stride // 2, current_w, stride):
                    vector = vector_rows[y][x] if x < len(vector_rows[y]) else None
                    if not isinstance(vector, (list, tuple)) or len(vector) < 2:
                        continue
                    u, v = float(vector[0] or 0.0), float(vector[1] or 0.0)
                    strength = min(1.0, math.hypot(u, v))
                    if strength < 0.08:
                        continue
                    source_nx = x / max(1, current_w - 1)
                    source_ny = y / max(1, current_h - 1)
                    projected = self._projected_normalized_point(source_nx, source_ny, layer)
                    if projected is None:
                        continue
                    start = (int(rect.x + projected[0] * rect.width), int(rect.y + projected[1] * rect.height))
                    projected_end = self._projected_normalized_point(
                        source_nx + u * arrow_scale / max(1.0, rect.width),
                        source_ny + v * arrow_scale / max(1.0, rect.height),
                        layer,
                    )
                    if projected_end is None:
                        continue
                    end = (int(rect.x + projected_end[0] * rect.width), int(rect.y + projected_end[1] * rect.height))
                    if abs(end[0] - start[0]) > rect.width * 0.25 or abs(end[1] - start[1]) > rect.height * 0.25:
                        continue
                    sst = sst_rows[y][x] if isinstance(sst_rows, list) and y < len(sst_rows) and x < len(sst_rows[y]) else None
                    color = (242, 170, 94) if sst is not None and float(sst) >= 285.0 else (104, 210, 232)
                    pygame.draw.line(screen, color, start, end, 1 + int(strength > 0.62))
                    angle = math.atan2(end[1] - start[1], end[0] - start[0])
                    head = 3 + int(strength * 2)
                    for offset in (-2.55, 2.55):
                        tip = (int(end[0] + math.cos(angle + offset) * head), int(end[1] + math.sin(angle + offset) * head))
                        pygame.draw.line(screen, color, end, tip, 1)
        map_span = max(rect.width, rect.height)
        maximum_reference_river_rank = 3 if map_span < 1700 else 4 if map_span < 2400 else 5 if map_span < 3200 else 6
        if layer.get("projection_interacting"):
            maximum_reference_river_rank = min(2, maximum_reference_river_rank)
        projected_reference_lakes, projected_reference_rivers = self._projected_reference_hydrology(
            water_cycle, layer, maximum_reference_river_rank,
        )
        screen.blit(
            self._reference_hydrology_overlay(water_cycle, layer, rect, maximum_reference_river_rank),
            rect.topleft,
        )
        root_detail_level = int(
            ((layer.get("heightmap_model") or {}).get("map_detail_level", 0))
            or 0
        )
        refined_models = [
            refined
            for refined in layer.get("refined_region_models") or []
            if isinstance(refined, dict)
        ]
        river_sets = [
            (water_cycle.get("rivers") or [], None, root_detail_level)
        ]
        for refined in refined_models:
            child_water = refined.get("water_cycle_model") if isinstance(refined, dict) else None
            if isinstance(child_water, dict):
                river_sets.append((
                    child_water.get("rivers") or [],
                    refined.get("uv_bounds") or {},
                    int(refined.get("detail_level", root_detail_level) or root_detail_level),
                ))
        ownership_regions = [
            (
                refined.get("uv_bounds") or {},
                int(refined.get("detail_level", root_detail_level) or root_detail_level),
            )
            for refined in refined_models
        ]

        def owned_by_finer_level(source_x, source_y, source_level):
            return any(
                level > source_level
                and float(bounds.get("min_u", 0.0)) <= source_x
                <= float(bounds.get("max_u", 0.0))
                and float(bounds.get("min_v", 0.0)) <= source_y
                <= float(bounds.get("max_v", 0.0))
                for bounds, level in ownership_regions
            )

        for river, river_uv, river_level in (
            (river, uv, level)
            for rivers, uv, level in river_sets
            for river in rivers
        ):
            if not isinstance(river, dict):
                continue
            authored_rank = river.get("scalerank") if river_uv is None else None
            if authored_rank is not None:
                authored_rank = int(authored_rank or 0)
                map_span = max(rect.width, rect.height)
                if authored_rank >= 6 and map_span < 3200:
                    continue
                if authored_rank >= 5 and map_span < 2400:
                    continue
                if authored_rank >= 4 and map_span < 1700:
                    continue
            if river_uv is not None:
                patch_screen_width = abs(float(river_uv.get("max_u", 1.0)) - float(river_uv.get("min_u", 0.0))) * rect.width
                patch_screen_height = abs(float(river_uv.get("max_v", 1.0)) - float(river_uv.get("min_v", 0.0))) * rect.height
                patch_screen_span = max(patch_screen_width, patch_screen_height)
                role = str(river.get("network_role") or "feeder")
                if role == "feeder" and patch_screen_span < 520.0:
                    continue
                if role == "tributary" and patch_screen_span < 190.0:
                    continue
            points = []
            cached_reference_points = projected_reference_rivers.get(id(river)) if river_uv is None else None
            if cached_reference_points is not None:
                continue
            for point in [] if cached_reference_points is not None else (river.get("display_points") or river.get("points") or []):
                if not isinstance(point, dict):
                    continue
                source_x = float(point.get("x", 0.0) or 0.0)
                source_y = float(point.get("y", 0.0) or 0.0)
                if river_uv is not None:
                    source_x = float(river_uv.get("min_u", 0.0)) + source_x * (float(river_uv.get("max_u", 1.0)) - float(river_uv.get("min_u", 0.0)))
                    source_y = float(river_uv.get("min_v", 0.0)) + source_y * (float(river_uv.get("max_v", 1.0)) - float(river_uv.get("min_v", 0.0)))
                if owned_by_finer_level(source_x, source_y, river_level):
                    points.append(None)
                    continue
                projected = self._projected_normalized_point(source_x, source_y, layer)
                if projected is None:
                    points.append(None)
                    continue
                px = rect.x + projected[0] * rect.width
                py = rect.y + projected[1] * rect.height
                points.append((int(px), int(py)))
            if len([point for point in points if point is not None]) >= 2:
                stream_order = max(1, int(river.get("stream_order", 1) or 1))
                morphology = river.get("channel_morphology") if isinstance(river.get("channel_morphology"), dict) else {}
                line_width = max(1, min(3, int(morphology.get("render_width_px", 1) or 1)))
                role = river.get("network_role")
                river_color = (112, 198, 244) if role == "feeder" else ((72, 164, 232) if role == "tributary" else (48, 136, 220))
                visible_segment = []
                for point in points:
                    if point is None:
                        if len(visible_segment) >= 2:
                            if line_width > 1:
                                pygame.draw.lines(screen, river_color, False, visible_segment, line_width)
                            pygame.draw.aalines(screen, river_color, False, visible_segment)
                        visible_segment = []
                        continue
                    if visible_segment and (
                        abs(point[0] - visible_segment[-1][0]) > rect.width * 0.5
                        or abs(point[1] - visible_segment[-1][1]) > rect.height * 0.55
                    ):
                        if len(visible_segment) >= 2:
                            if line_width > 1:
                                pygame.draw.lines(screen, river_color, False, visible_segment, line_width)
                            pygame.draw.aalines(screen, river_color, False, visible_segment)
                        visible_segment = []
                    visible_segment.append(point)
                if len(visible_segment) >= 2:
                    if line_width > 1:
                        pygame.draw.lines(screen, river_color, False, visible_segment, line_width)
                    pygame.draw.aalines(screen, river_color, False, visible_segment)

        delta_sets = [
            (water_cycle.get("deltas") or [], None, root_detail_level)
        ]
        for refined in refined_models:
            child_water = (
                refined.get("water_cycle_model")
                if isinstance(refined, dict)
                else None
            )
            if isinstance(child_water, dict):
                delta_sets.append((
                    child_water.get("deltas") or [],
                    refined.get("uv_bounds") or {},
                    int(
                        refined.get("detail_level", root_detail_level)
                        or root_detail_level
                    ),
                ))

        def project_delta_point(point, delta_uv):
            if not isinstance(point, dict):
                return None
            source_x = float(point.get("x", 0.0) or 0.0)
            source_y = float(point.get("y", 0.0) or 0.0)
            if delta_uv is not None:
                source_x = (
                    float(delta_uv.get("min_u", 0.0))
                    + source_x
                    * (
                        float(delta_uv.get("max_u", 1.0))
                        - float(delta_uv.get("min_u", 0.0))
                    )
                )
                source_y = (
                    float(delta_uv.get("min_v", 0.0))
                    + source_y
                    * (
                        float(delta_uv.get("max_v", 1.0))
                        - float(delta_uv.get("min_v", 0.0))
                    )
                )
            projected = self._projected_normalized_point(
                source_x, source_y, layer
            )
            if projected is None:
                return None
            return (
                int(rect.x + projected[0] * rect.width),
                int(rect.y + projected[1] * rect.height),
            )

        for deltas, delta_uv, delta_level in delta_sets:
            for delta in deltas:
                if not isinstance(delta, dict):
                    continue
                center = delta.get("center") or {}
                center_x = float(center.get("x", 0.0) or 0.0)
                center_y = float(center.get("y", 0.0) or 0.0)
                global_center_x, global_center_y = center_x, center_y
                if delta_uv is not None:
                    global_center_x = (
                        float(delta_uv.get("min_u", 0.0))
                        + center_x
                        * (
                            float(delta_uv.get("max_u", 1.0))
                            - float(delta_uv.get("min_u", 0.0))
                        )
                    )
                    global_center_y = (
                        float(delta_uv.get("min_v", 0.0))
                        + center_y
                        * (
                            float(delta_uv.get("max_v", 1.0))
                            - float(delta_uv.get("min_v", 0.0))
                        )
                    )
                if owned_by_finer_level(
                    global_center_x, global_center_y, delta_level
                ):
                    continue
                dominance = str(
                    delta.get("morphodynamic_dominance")
                    or delta.get("marine_reworking_end_member")
                    or "river_dominated"
                )
                outline_color = {
                    "river_dominated": (112, 184, 112),
                    "wave_dominated": (164, 190, 112),
                    "tide_dominated": (98, 174, 148),
                    "lacustrine": (126, 184, 126),
                }.get(dominance, (116, 180, 116))
                footprint = [
                    projected
                    for projected in (
                        project_delta_point(point, delta_uv)
                        for point in delta.get("footprint_points") or []
                    )
                    if projected is not None
                ]
                if (
                    len(footprint) >= 3
                    and max(point[0] for point in footprint)
                    - min(point[0] for point in footprint)
                    < rect.width * 0.45
                ):
                    pygame.draw.polygon(
                        screen, outline_color, footprint, width=1
                    )
                for distributary in delta.get("distributaries") or []:
                    branch = [
                        projected
                        for projected in (
                            project_delta_point(point, delta_uv)
                            for point in distributary
                        )
                        if projected is not None
                    ]
                    if (
                        len(branch) >= 2
                        and max(point[0] for point in branch)
                        - min(point[0] for point in branch)
                        < rect.width * 0.45
                    ):
                        pygame.draw.aalines(
                            screen, (70, 158, 220), False, branch
                        )
        screen.set_clip(clip)
        self._draw_planet_equator(screen, rect, layer)
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
            band_rect = pygame.Rect(rect.x, y0, rect.width, max(1, y1 - y0)).clip(screen.get_rect())
            if band_rect.width > 0 and band_rect.height > 0:
                pygame.draw.rect(screen, color, band_rect)
        if 0 <= rect.centery < screen.get_height():
            pygame.draw.line(screen, (238, 238, 232), (max(0, rect.x), rect.centery), (min(screen.get_width() - 1, rect.right), rect.centery), 1)
        screen.set_clip(clip)

    def _polygon_screen_points(self, layer, camera):
        world_points = layer.get("points") or []
        cache_key = (
            id(world_points),
            len(world_points),
            round(float(getattr(camera, "x", 0.0) or 0.0), 5),
            round(float(getattr(camera, "y", 0.0) or 0.0), 5),
            round(float(getattr(camera, "zoom", 1.0) or 1.0), 7),
            int(getattr(camera, "width", self.app_view.width) or self.app_view.width),
            int(getattr(camera, "height", self.app_view.height) or self.app_view.height),
        )
        cached = self._polygon_screen_cache.get(cache_key)
        if cached is not None:
            return cached

        points = []
        previous = None
        for point in world_points:
            screen_point = camera.world_to_screen(point)
            if screen_point is None:
                return []
            candidate = (int(screen_point[0]), int(screen_point[1]))
            if previous is not None:
                dx = candidate[0] - previous[0]
                dy = candidate[1] - previous[1]
                if dx * dx + dy * dy < 0.64:
                    continue
            points.append(candidate)
            previous = candidate
        if len(points) < 3 and len(world_points) >= 3:
            points = []
            for point in world_points[:3]:
                screen_point = camera.world_to_screen(point)
                if screen_point is not None:
                    points.append((int(screen_point[0]), int(screen_point[1])))
        return self._cache_put(self._polygon_screen_cache, cache_key, points, limit=24)

    def _draw_polygon_layer(self, screen, layer, camera, is_selected, is_hovered, visible_world_bounds=None):
        if layer.get("render_when_interacting_only") and not (is_selected or is_hovered):
            return
        min_zoom = layer.get("min_zoom")
        strict_zoom = bool(layer.get("strict_zoom_visibility"))
        if min_zoom is not None and (strict_zoom or not (is_selected or is_hovered)):
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

        screen_points = self._polygon_screen_points(layer, camera)

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

        label_min_screen_span = layer.get("label_min_screen_span")
        if label_min_screen_span is not None:
            should_draw_label = max(max_x - min_x, max_y - min_y) >= float(
                label_min_screen_span
            )
        else:
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

    def _draw_polyline_layer(self, screen, layer, camera, is_selected, is_hovered):
        min_zoom = layer.get("min_zoom")
        if min_zoom is not None and not (is_selected or is_hovered):
            try:
                if float(getattr(camera, "zoom", 1.0) or 1.0) < float(min_zoom):
                    return
            except (TypeError, ValueError):
                pass

        screen_points = []
        for point in layer.get("points") or []:
            screen_point = camera.world_to_screen(point)
            if screen_point is None:
                return
            screen_points.append((int(screen_point[0]), int(screen_point[1])))
        if len(screen_points) < 2:
            return

        color = self._coerce_rgb(layer.get("color"), fallback=(72, 164, 232))
        line_width = max(1, int(layer.get("line_width", 2) or 2))
        pygame.draw.lines(screen, color, False, screen_points, line_width)
        if line_width > 1:
            pygame.draw.aalines(screen, color, False, screen_points)
        if layer.get("arrow_end") and len(screen_points) >= 2:
            start, end = screen_points[-2], screen_points[-1]
            angle = math.atan2(end[1] - start[1], end[0] - start[0])
            arrow_length = max(5, line_width * 4)
            arrow_points = [
                (int(end[0] - math.cos(angle - 0.55) * arrow_length), int(end[1] - math.sin(angle - 0.55) * arrow_length)),
                end,
                (int(end[0] - math.cos(angle + 0.55) * arrow_length), int(end[1] - math.sin(angle + 0.55) * arrow_length)),
            ]
            pygame.draw.lines(screen, color, False, arrow_points, line_width)
        if is_hovered and not is_selected:
            pygame.draw.lines(screen, (120, 220, 255), False, screen_points, line_width + 2)
        if is_selected:
            pygame.draw.lines(screen, (255, 230, 120), False, screen_points, line_width + 3)

        if (is_selected or is_hovered) and layer.get("name"):
            label_pos = camera.world_to_screen((layer.get("x", 0), layer.get("y", 0)))
            if label_pos is not None:
                text = self._render_text(layer["name"], (245, 245, 245))
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
        layers = sim.get_layers()
        heightmap_base_layer = None
        if hasattr(sim, "get_heightmap_base_layer"):
            heightmap_base_layer = sim.get_heightmap_base_layer()
            if heightmap_base_layer is not None:
                heightmap_base_layer = dict(heightmap_base_layer)
                heightmap_base_layer["projection_focus_x"] = float(
                    getattr(sim, "map_projection_focus_x", 0.0) or 0.0
                )
                heightmap_base_layer["projection_focus_y"] = float(
                    getattr(sim, "map_projection_focus_y", 0.0) or 0.0
                )
                root_entity = getattr(sim, "get_root_entity", lambda: None)()
                heightmap_base_layer["show_planet_equator"] = bool(
                    isinstance(root_entity, dict)
                    and root_entity.get("location_class") in {"planet", "moon"}
                )

        root_map_layer = next((layer for layer in layers if layer.get("shape") == "map_rect"), None)
        static_outline_batch_drawn = False

        for layer in layers:
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
            strict_zoom = bool(layer.get("strict_zoom_visibility"))
            if min_zoom is not None and (strict_zoom or not (is_selected or is_hovered)):
                try:
                    if float(getattr(camera, "zoom", 1.0) or 1.0) < float(min_zoom):
                        continue
                except (TypeError, ValueError):
                    pass
            max_zoom = layer.get("max_zoom")
            if max_zoom is not None:
                try:
                    if float(getattr(camera, "zoom", 1.0) or 1.0) >= float(max_zoom):
                        continue
                except (TypeError, ValueError):
                    pass

            if shape == "image_rect":
                if active_layer_kind == "material_heatmaps" and heightmap_base_layer is not None:
                    composite = self._material_composite_surface(layer, heightmap_base_layer)
                    if composite is not None:
                        prepared_layer = dict(layer)
                        prepared_layer["_prepared_surface"] = composite
                        prepared_layer["alpha"] = None
                        self._draw_image_rect_layer(screen, prepared_layer, camera)
                        continue
                self._draw_image_rect_layer(screen, layer, camera)
                continue

            if shape == "heightmap_base":
                self._draw_heightmap_base_layer(screen, layer, camera)
                continue

            if shape == "reference_land":
                self._draw_reference_land_layer(screen, layer, camera)
                continue

            if shape == "hydrology_climate":
                self._draw_hydrology_layer(screen, layer, camera)
                continue

            if shape == "polygon":
                if (
                    root_map_layer is not None
                    and float(getattr(camera, "zoom", 1.0) or 1.0) <= 8.0
                    and self._is_batchable_static_outline(layer)
                    and not is_selected
                    and not is_hovered
                ):
                    if not static_outline_batch_drawn:
                        self._draw_static_outline_batch(screen, layers, root_map_layer, camera)
                        static_outline_batch_drawn = True
                    continue
                self._draw_polygon_layer(
                    screen=screen,
                    layer=layer,
                    camera=camera,
                    is_selected=is_selected,
                    is_hovered=is_hovered,
                    visible_world_bounds=visible_world_bounds,
                )
                continue

            if shape == "polyline":
                if not self._polygon_layer_visible_in_world(
                    layer,
                    camera,
                    visible_world_bounds=visible_world_bounds,
                ):
                    continue
                self._draw_polyline_layer(
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
                    tint = layer.get("atmosphere_tint")
                    opacity = max(0.0, min(1.0, float(layer.get("atmosphere_opacity", 0.0) or 0.0)))
                    if (
                        not layer.get("atmosphere_baked_into_surface")
                        and isinstance(tint, (list, tuple))
                        and len(tint) >= 3
                        and opacity > 0.0
                    ):
                        self._draw_cached_alpha_fill(screen, rect, tint, round(opacity * 255))
                    self._draw_map_frame(
                        screen,
                        rect,
                        crosshair=False,
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

        # A single cached contour overlay keeps every raster subtype on the
        # same elevation reference. Regions deliberately omits the terrain
        # fill, so its contour treatment is stronger.
        if (
            heightmap_base_layer is not None
            and active_layer_kind != "hydrology"
            and active_layer_kind != "true_color"
            and bool(getattr(sim, "is_height_contours_visible", lambda: True)())
        ):
            self._draw_height_contours(
                screen,
                heightmap_base_layer,
                camera,
                regions_only=active_layer_kind == "ground_materials",
            )

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
