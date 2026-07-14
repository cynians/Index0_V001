import unittest
from types import SimpleNamespace

import pygame

from simulations.map.map_renderer import MapRenderer


class FakeCamera:
    def __init__(self, x=0.0, y=0.0, zoom=1.0, width=100, height=100):
        self.x = x
        self.y = y
        self.zoom = zoom
        self.width = width
        self.height = height

    def screen_to_world(self, pos):
        sx, sy = pos
        return (
            (sx - self.width / 2) / self.zoom + self.x,
            (sy - self.height / 2) / self.zoom + self.y,
        )


class MapRendererTests(unittest.TestCase):
    def _renderer(self):
        return MapRenderer(SimpleNamespace(width=100, height=100))

    def test_polygon_bounds_cull_far_offscreen_layers(self):
        renderer = self._renderer()
        camera = FakeCamera()
        layer = {"_world_bounds": (500.0, 600.0, 500.0, 600.0)}

        self.assertFalse(renderer._polygon_layer_visible_in_world(layer, camera))

    def test_polygon_bounds_keep_visible_layers(self):
        renderer = self._renderer()
        camera = FakeCamera()
        layer = {"_world_bounds": (-10.0, 20.0, -10.0, 20.0)}

        self.assertTrue(renderer._polygon_layer_visible_in_world(layer, camera))

    def test_polygon_bounds_support_dict_metadata(self):
        renderer = self._renderer()
        camera = FakeCamera()
        layer = {
            "_world_bounds": {
                "min_x": -5.0,
                "max_x": 5.0,
                "min_y": -5.0,
                "max_y": 5.0,
            }
        }

        self.assertTrue(renderer._polygon_layer_visible_in_world(layer, camera))

    def test_large_scaled_layer_reuses_overscan_during_small_pan(self):
        renderer = self._renderer()
        screen = pygame.Surface((100, 100))
        source = pygame.Surface((256, 128))
        cache = {}

        renderer._blit_scaled_layer(screen, source, pygame.Rect(-200, -100, 500, 250), cache, "dione")
        entry = next(iter(renderer._large_scaled_layer_cache.values()))
        first_surface = entry["surface"]
        renderer._blit_scaled_layer(screen, source, pygame.Rect(-210, -105, 500, 250), cache, "dione")

        self.assertIs(first_surface, next(iter(renderer._large_scaled_layer_cache.values()))["surface"])

    def test_large_scaled_layer_rebuilds_after_leaving_overscan(self):
        renderer = self._renderer()
        screen = pygame.Surface((100, 100))
        source = pygame.Surface((256, 128))
        cache = {}

        renderer._blit_scaled_layer(screen, source, pygame.Rect(-200, -100, 500, 250), cache, "dione")
        first_surface = next(iter(renderer._large_scaled_layer_cache.values()))["surface"]
        renderer._blit_scaled_layer(screen, source, pygame.Rect(-350, -100, 500, 250), cache, "dione")

        self.assertIsNot(first_surface, next(iter(renderer._large_scaled_layer_cache.values()))["surface"])

    def test_large_scaled_layer_never_allocates_full_offscreen_map(self):
        renderer = self._renderer()
        screen = pygame.Surface((100, 100))
        source = pygame.Surface((256, 128))

        renderer._blit_scaled_layer(
            screen,
            source,
            pygame.Rect(-50000, -25000, 100000, 50000),
            {},
            "huge-map",
        )

        cached = next(iter(renderer._large_scaled_layer_cache.values()))["surface"]
        self.assertLessEqual(cached.get_width(), 100 + renderer._viewport_overscan_px * 2 + 2)
        self.assertLessEqual(cached.get_height(), 100 + renderer._viewport_overscan_px * 2 + 2)

    def test_atmosphere_fill_is_clipped_and_reused(self):
        renderer = self._renderer()
        screen = pygame.Surface((100, 100))
        huge_rect = pygame.Rect(-50000, -25000, 100000, 50000)

        renderer._draw_cached_alpha_fill(screen, huge_rect, (180, 140, 90), 80)
        first = next(iter(renderer._alpha_fill_cache.values()))
        renderer._draw_cached_alpha_fill(screen, huge_rect, (180, 140, 90), 80)

        self.assertEqual(first.get_size(), screen.get_size())
        self.assertIs(first, next(iter(renderer._alpha_fill_cache.values())))

    def test_heightmap_atmosphere_variant_reuses_untinted_terrain(self):
        renderer = self._renderer()
        heightmap = {
            "min_elevation_m": -1000,
            "max_elevation_m": 1000,
            "sample_grid": {"rows": [[-1000, 0, 1000], [-500, 200, 800], [0, 400, 600]]},
        }
        rows = heightmap["sample_grid"]["rows"]
        base_layer = {"surface_palette": {}, "atmosphere_opacity": 0.0}
        tinted_layer = {
            "surface_palette": {},
            "atmosphere_tint": [202, 166, 82],
            "atmosphere_opacity": 0.56,
        }

        base = renderer._heightmap_surface_for_layer(base_layer, heightmap, rows)
        tinted = renderer._heightmap_surface_for_layer(tinted_layer, heightmap, rows)
        base_again = renderer._heightmap_surface_for_layer(base_layer, heightmap, rows)

        self.assertIs(base, base_again)
        self.assertIsNot(base, tinted)
        self.assertNotEqual(base.get_at((0, 0)), tinted.get_at((0, 0)))

    def test_airless_heightmap_uses_full_negative_to_positive_relief(self):
        renderer = self._renderer()
        heightmap = {
            "min_elevation_m": -8000,
            "max_elevation_m": 5000,
            "sea_level_m": None,
        }
        context = renderer._heightmap_color_context(heightmap, {"surface_palette": {}})

        deep = renderer._heightmap_color_from_context(-7000, context)
        upland = renderer._heightmap_color_from_context(2000, context)

        self.assertNotEqual(deep, upland)

    def test_projected_polygon_batch_is_not_projected_twice(self):
        renderer = self._renderer()
        captured = {}
        renderer._static_outline_surface = lambda layers, root: pygame.Surface((8, 4), pygame.SRCALPHA)
        renderer._draw_image_rect_layer = lambda screen, layer, camera: captured.update(layer)

        renderer._draw_static_outline_batch(
            None,
            [{"shape": "polygon", "points": [(0, 0), (1, 0), (0, 1)]}],
            {
                "shape": "map_rect", "x": 0, "y": 0, "width_world": 360, "height_world": 180,
                "projection_focus_x": 0.25, "projection_focus_y": -0.1,
            },
            None,
        )

        self.assertNotIn("projection_focus_x", captured)
        self.assertNotIn("projection_focus_y", captured)
        self.assertFalse(captured["show_planet_equator"])

    def test_projected_polygons_are_not_put_in_unprojected_outline_batch(self):
        renderer = self._renderer()
        self.assertFalse(renderer._is_batchable_static_outline({
            "shape": "polygon",
            "outline_only": True,
            "suppress_label": True,
            "min_zoom": 0.0,
            "projection_geometry_copy": 0,
        }))


if __name__ == "__main__":
    unittest.main()
