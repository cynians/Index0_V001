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

    def test_contour_fragments_join_into_one_continuous_path(self):
        heightmap = {
            "sample_grid": {
                "width": 3,
                "height": 4,
                "rows": [
                    [0.0, 1.0, 2.0],
                    [0.0, 1.0, 2.0],
                    [0.0, 1.0, 2.0],
                    [0.0, 1.0, 2.0],
                ],
            },
        }

        segments = MapRenderer._heightmap_contour_segments(heightmap, 0.5)
        polylines = MapRenderer._contour_polylines(segments)

        self.assertEqual(3, len(segments))
        self.assertEqual(1, len(polylines))
        self.assertEqual(4, len(polylines[0]))

    def test_contour_smoothing_preserves_open_path_endpoints(self):
        points = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)]

        smoothed = MapRenderer._smooth_contour_polyline(points)

        self.assertEqual(points[0], smoothed[0])
        self.assertEqual(points[-1], smoothed[-1])
        self.assertGreater(len(smoothed), len(points))

    def test_contour_overlay_uses_display_resolution_for_regional_maps(self):
        renderer = self._renderer()
        heightmap = {
            "min_elevation_m": 0.0,
            "max_elevation_m": 1000.0,
            "sea_level_m": 0.0,
            "sample_grid": {
                "width": 3,
                "height": 3,
                "rows": [
                    [0.0, 200.0, 400.0],
                    [200.0, 500.0, 700.0],
                    [400.0, 700.0, 1000.0],
                ],
            },
        }

        surface, _interval = renderer._height_contour_surface_for_layer(
            {"heightmap_model": heightmap},
            pixels_per_map_pixel=1.0,
            target_size=(900, 450),
        )

        self.assertEqual((900, 450), surface.get_size())
        self.assertIs(
            surface,
            renderer._projected_spherical_surface(surface, {}),
        )

    def test_blue_shoreline_comes_from_ocean_mask_not_zero_metre_datum(self):
        renderer = self._renderer()
        heightmap = {
            "min_elevation_m": -10.0,
            "max_elevation_m": 10.0,
            "sea_level_m": None,
            "sample_grid": {
                "width": 4,
                "height": 3,
                "rows": [
                    [-10.0, 10.0, 10.0, 10.0],
                    [-10.0, 10.0, 10.0, 10.0],
                    [-10.0, 10.0, 10.0, 10.0],
                ],
            },
            "surface_masks": {
                "ocean_rows": [
                    [False, False, False, True],
                    [False, False, False, True],
                    [False, False, False, True],
                ],
            },
        }

        _levels, shoreline_paths = renderer._height_contour_geometry(
            heightmap, interval=5,
        )

        self.assertTrue(shoreline_paths)
        self.assertTrue(
            all(abs(point[0] - 2.5) < 1e-6 for path in shoreline_paths for point in path)
        )

    def test_drainage_basin_boundaries_are_not_painted_as_riverbeds(self):
        renderer = self._renderer()
        water_cycle = {
            "climate_grid": {
                "rows": [["hot_desert"] * 4 for _row in range(4)],
                "koppen_rows": [["BWh"] * 4 for _row in range(4)],
                "elevation_rows": [[100.0] * 4 for _row in range(4)],
            },
            "koppen_classes": [{
                "id": "BWh",
                "color": [220, 180, 100],
            }],
            "drainage_network_model": {
                "drainage_basin_rows": [
                    [0, 0, 1, 1],
                    [0, 0, 1, 1],
                    [2, 2, 3, 3],
                    [2, 2, 3, 3],
                ],
            },
            "lakes": [],
        }

        surface = renderer._hydrology_surface_for_layer(
            {"climate_display_mode": "zones"},
            water_cycle,
        )

        self.assertIsNotNone(surface)
        self.assertEqual(surface.get_at((0, 0)), surface.get_at((1, 1)))
        self.assertEqual(surface.get_at((1, 1)), surface.get_at((2, 1)))
        self.assertEqual(surface.get_at((1, 1)), surface.get_at((2, 2)))

    def test_individual_material_view_is_subdued_and_softly_outlined(self):
        renderer = self._renderer()
        source = pygame.Surface((6, 3), pygame.SRCALPHA)
        source.fill((112, 116, 104, 0))
        for y in range(3):
            for x in range(2, 6):
                source.set_at((x, y), (112, 116, 104, 230))
        renderer._load_image_surface = lambda _path: source

        surface = renderer._material_composite_surface({
            "image_path": "synthetic.png",
            "material_id": "mat_andesite",
            "geological_map_color": [179, 112, 99],
            "dominance_threshold": 0.2,
        }, None)

        self.assertEqual((49, 55, 58), surface.get_at((0, 2))[:3])
        contact = surface.get_at((4, 2))[:3]
        fill = surface.get_at((8, 2))[:3]
        self.assertLess(sum(contact), sum(fill))
        self.assertGreater(fill[0], fill[1])

    def test_composite_material_view_softens_palette_and_avoids_black_contacts(self):
        renderer = self._renderer()
        source = pygame.Surface((4, 2), pygame.SRCALPHA)
        source.fill((179, 112, 99, 255))
        pygame.draw.rect(source, (70, 94, 115, 255), pygame.Rect(2, 0, 2, 2))
        renderer._load_image_surface = lambda _path: source

        surface = renderer._material_composite_surface({
            "image_path": "synthetic.png",
            "bundle_layer_id": "composite",
            "render_mode": "categorical_geological_map",
            "geological_unit_palette": [
                {
                    "material_id": "old-red",
                    "source_color": [179, 112, 99],
                    "color": [150, 126, 112],
                },
            ],
        }, None)

        self.assertEqual((8, 4), surface.get_size())
        self.assertGreater(min(surface.get_at((3, 1))[:3]), 20)
        self.assertLess(surface.get_at((0, 0)).r, 179)

    def test_koppen_view_includes_hypsometric_color_not_only_class_color(self):
        renderer = self._renderer()
        water_cycle = {
            "climate_grid": {
                "koppen_rows": [["BWh", "BWh"]],
                "elevation_rows": [[0.0, 3000.0]],
            },
            "koppen_classes": [{"id": "BWh", "color": [220, 180, 100]}],
            "lakes": [],
        }

        surface = renderer._hydrology_surface_for_layer(
            {"climate_display_mode": "koppen"}, water_cycle,
        )
        low = surface.get_at((0, 0))
        high = surface.get_at((1, 0))

        self.assertNotEqual(low, high)
        self.assertGreater(high.b / max(1, high.r), low.b / max(1, low.r))

    def test_refined_contour_patch_clears_stale_parent_contours(self):
        renderer = self._renderer()
        base = pygame.Surface((100, 50), pygame.SRCALPHA)
        base.fill((255, 255, 255, 255))
        child_heightmap = {
            "min_elevation_m": 100.0,
            "max_elevation_m": 100.0,
            "sea_level_m": None,
            "sample_grid": {
                "width": 3,
                "height": 3,
                "rows": [[100.0, 100.0, 100.0]] * 3,
            },
        }
        layer = {
            "refined_region_models": [{
                "entity_id": "child",
                "detail_level": 2,
                "refinement_revision": 1,
                "heightmap_model": child_heightmap,
                "uv_bounds": {
                    "min_u": 0.25,
                    "max_u": 0.75,
                    "min_v": 0.2,
                    "max_v": 0.8,
                },
            }],
        }

        composite = renderer._composite_refined_contours(
            base, layer, pixels_per_map_pixel=1.0, regions_only=False,
        )

        self.assertEqual(255, composite.get_at((10, 10)).a)
        self.assertEqual(0, composite.get_at((50, 25)).a)

    def test_contour_geometry_is_reused_across_display_sizes(self):
        renderer = self._renderer()
        heightmap = {
            "min_elevation_m": -100.0,
            "max_elevation_m": 100.0,
            "sea_level_m": 20.0,
            "sample_grid": {
                "width": 4,
                "height": 3,
                "rows": [
                    [-100.0, -20.0, 40.0, 100.0],
                    [-100.0, -20.0, 40.0, 100.0],
                    [-100.0, -20.0, 40.0, 100.0],
                ],
            },
        }
        layer = {"heightmap_model": heightmap}

        renderer._height_contour_surface_for_layer(
            layer, 1.0, target_size=(700, 350),
        )
        geometry_count = len(renderer._height_contour_geometry_cache)
        renderer._height_contour_surface_for_layer(
            layer, 1.0, target_size=(1100, 550),
        )

        self.assertEqual(geometry_count, len(renderer._height_contour_geometry_cache))

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

    def test_polyline_bounds_are_prepared_for_viewport_culling(self):
        from simulations.map.map_simulation import MapSimulation

        prepared = MapSimulation._prepare_layer_cache(
            SimpleNamespace(_render_layer_sort_key=lambda _layer: (0, 0, 0)),
            [{"shape": "polyline", "points": [(500.0, 500.0), (600.0, 600.0)]}],
        )

        renderer = self._renderer()
        self.assertEqual((500.0, 600.0, 500.0, 600.0), prepared[0]["_world_bounds"])
        self.assertFalse(renderer._polygon_layer_visible_in_world(prepared[0], FakeCamera()))

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

    def test_mixed_resolution_rasters_use_the_same_projection_focus(self):
        renderer = self._renderer()
        layer = {
            "projection_focus_x": 24.9 / 360.0,
            "projection_focus_y": -2.9 / 180.0,
        }

        renderer._projected_spherical_surface(pygame.Surface((64, 32)), layer)
        renderer._projected_spherical_surface(pygame.Surface((128, 64)), layer)

        focus_keys = {(key[1], key[2]) for key in renderer._projection_surface_cache}
        self.assertEqual({(round(layer["projection_focus_x"], 9), round(layer["projection_focus_y"], 9))}, focus_keys)


if __name__ == "__main__":
    unittest.main()
