import os
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame

from simulations.species.species_renderer import (
    DiagnosticCamera,
    SpeciesRenderer,
    TopDownDiagnosticCamera,
    frond_primary_pinna_rows,
)
from world.texture_sets import TextureSet


class SpeciesRendererTextureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        pygame.display.set_mode((64, 64))

    def test_texture_tile_maps_onto_a_segment(self):
        texture = TextureSet(
            2,
            4,
            base_layers=[{
                "name": "Bark",
                "visible": True,
                "opacity": 1.0,
                "pixels": [[(210, 210, 190), (210, 210, 190)] for _ in range(4)],
            }],
            texture_id="test_bark",
        )
        texture.add_variant(0, 1, [{
            "name": "Bark",
            "visible": True,
            "opacity": 1.0,
            "pixels": [[(40, 40, 40), (210, 210, 190)] for _ in range(4)],
        }])
        renderer = SpeciesRenderer(SimpleNamespace(camera=SimpleNamespace()))
        screen = pygame.Surface((64, 64), pygame.SRCALPHA)
        screen.fill((0, 0, 0, 0))

        self.assertTrue(renderer._draw_textured_path(screen, "test", texture, "0,1", [(32, 54), (32, 10)], 2))
        self.assertGreater(sum(screen.get_at((x, y)).a for x in range(64) for y in range(64)), 0)

    def test_frond_primary_pinna_rows_preserve_authored_arrangement(self):
        alternate = frond_primary_pinna_rows(10, "alternate")
        opposite = frond_primary_pinna_rows(10, "opposite")

        self.assertEqual(10, len(alternate))
        self.assertEqual([(1.0,), (-1.0,)] * 5, [sides for _progress, sides in alternate])
        self.assertEqual(5, len(opposite))
        self.assertTrue(all(sides == (-1.0, 1.0) for _progress, sides in opposite))

    def test_simple_fallback_leaf_has_physical_area(self):
        renderer = SpeciesRenderer(SimpleNamespace(camera=SimpleNamespace()))
        renderer._fallback_leaf_endpoint = lambda *_args: (54, 32)
        leaf = SimpleNamespace(radius_m=0.03, visual={"leaf_structure": "simple"})
        sim = SimpleNamespace(blueprint=SimpleNamespace(module=lambda _kind: leaf))
        screen = pygame.Surface((64, 64), pygame.SRCALPHA)
        screen.fill((0, 0, 0, 0))

        renderer._draw_fallback_leaf(
            screen,
            sim,
            SimpleNamespace(scale=200.0),
            SimpleNamespace(),
            0,
            (10, 32),
            0.0,
            1.0,
        )

        self.assertGreater(screen.get_bounding_rect().height, 8)
        self.assertGreater(screen.get_bounding_rect().width, 40)

    def test_rosette_leaf_asset_compresses_edge_on_in_side_view(self):
        renderer = SpeciesRenderer(SimpleNamespace(camera=SimpleNamespace()))
        placement = ["leaf", 0, 0.0, 0.0, 0.0, 0.0, 1.0, 1]
        bounds = (-1.0, 1.0, -1.0, 1.0)
        side = DiagnosticCamera(200, 200, bounds)
        top = TopDownDiagnosticCamera(200, 200, bounds)
        side_point = renderer._placement_screen(side, placement)
        top_point = renderer._placement_screen(top, placement)

        side_scale = renderer._rosette_leaf_width_scale(side, placement, side_point)
        top_scale = renderer._rosette_leaf_width_scale(top, placement, top_point)

        self.assertLess(side_scale, 0.5)
        self.assertGreater(top_scale, 0.95)

    def test_quantified_pinnate_leaf_samples_a_tapered_frond(self):
        renderer = SpeciesRenderer(SimpleNamespace(camera=SimpleNamespace()))
        renderer._fallback_leaf_endpoint = lambda *_args: (118, 64)
        leaf = SimpleNamespace(
            radius_m=0.021,
            visual={
                "leaf_structure": "pinnately_compound",
                "leaflet_count": 135,
                "leaflet_length_m": 1.10,
                "leaflet_width_m": 0.060,
                "frond_arch": 0.16,
            },
        )
        sim = SimpleNamespace(blueprint=SimpleNamespace(module=lambda _kind: leaf))
        screen = pygame.Surface((128, 128), pygame.SRCALPHA)
        screen.fill((0, 0, 0, 0))

        renderer._draw_fallback_leaf(
            screen,
            sim,
            SimpleNamespace(scale=12.0),
            SimpleNamespace(),
            7,
            (10, 84),
            0.0,
            1.0,
        )

        bounds = screen.get_bounding_rect()
        self.assertGreater(bounds.width, 100)
        self.assertGreaterEqual(bounds.height, 35)
        self.assertLess(bounds.top, 64)  # curved rachis rises above its endpoint

    def test_hierarchical_frond_division_adds_internal_structure(self):
        renderer = SpeciesRenderer(SimpleNamespace(camera=SimpleNamespace()))
        renderer._fallback_leaf_endpoint = lambda *_args: (120, 12)

        def draw(order):
            leaf = SimpleNamespace(
                radius_m=0.02,
                visual={
                    "leaf_structure": "frond_like",
                    "leaf_division_order": order,
                    "leaflet_count": 24,
                    "leaflet_length_m": 0.25,
                    "leaflet_width_m": 0.09,
                    "frond_stipe_fraction": 0.42,
                    "frond_arch": 0.08,
                },
            )
            sim = SimpleNamespace(blueprint=SimpleNamespace(module=lambda _kind: leaf))
            screen = pygame.Surface((240, 240), pygame.SRCALPHA)
            screen.fill((0, 0, 0, 0))
            renderer._draw_fallback_leaf(
                screen,
                sim,
                SimpleNamespace(scale=100.0),
                SimpleNamespace(lod=2),
                11,
                (110, 228),
                0.0,
                1.0,
            )
            return screen

        twice = draw(2)
        thrice = draw(3)
        twice_pixels = sum(twice.get_at((x, y)).a > 0 for x in range(240) for y in range(240))
        thrice_pixels = sum(thrice.get_at((x, y)).a > 0 for x in range(240) for y in range(240))
        self.assertGreater(thrice_pixels, twice_pixels)
        self.assertGreater(thrice.get_bounding_rect().width, 70)
        self.assertGreater(thrice.get_bounding_rect().height, 210)

    def test_module_asset_cache_reloads_when_pixel_file_changes(self):
        renderer = SpeciesRenderer(SimpleNamespace(camera=SimpleNamespace()))
        path = Path("artifacts/species_editor_v001/_hot_reload_test.png")
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            red = pygame.Surface((2, 2), pygame.SRCALPHA)
            red.fill((220, 20, 20, 255))
            pygame.image.save(red, path)
            module = SimpleNamespace(id="leaf", asset_ref=str(path))
            sim = SimpleNamespace(blueprint=SimpleNamespace(module=lambda _kind: module, modules=[module]))
            self.assertEqual((220, 20, 20), renderer._module_asset(sim, "leaf").get_at((0, 0))[:3])
            first_mtime = path.stat().st_mtime_ns

            green = pygame.Surface((2, 2), pygame.SRCALPHA)
            green.fill((20, 220, 20, 255))
            pygame.image.save(green, path)
            os.utime(path, ns=(first_mtime + 2_000_000_000, first_mtime + 2_000_000_000))
            cache_path = str(path.resolve())
            renderer._asset_revision_cache.pop(cache_path, None)
            self.assertEqual((20, 220, 20), renderer._module_asset(sim, "leaf").get_at((0, 0))[:3])
        finally:
            path.unlink(missing_ok=True)

    def test_species_tint_varies_leaf_colour_deterministically_by_species(self):
        # Without a species-specific pixel asset, every species used to
        # fall back to the exact same fixed leaf/branch/flower RGB -- a
        # landscape of unauthored species looked identical beyond height.
        renderer = SpeciesRenderer(SimpleNamespace(camera=SimpleNamespace()))
        sim_a = SimpleNamespace(species_id="spec_tint_variety_a")
        sim_b = SimpleNamespace(species_id="spec_tint_variety_b")
        color_a = renderer._color("leaf", sim_a)
        color_b = renderer._color("leaf", sim_b)
        self.assertNotEqual(color_a, color_b)
        for color in (color_a, color_b):
            self.assertTrue(all(0 <= channel <= 255 for channel in color))
            # Stays in the green family: green channel clearly dominant.
            r, g, b = color
            self.assertGreater(g, r)
            self.assertGreater(g, b)

        # Same species id is fully deterministic.
        self.assertEqual(color_a, renderer._color("leaf", sim_a))

        # No sim / no species id falls back to the plain shared colour.
        self.assertEqual((77, 168, 83), renderer._color("leaf"))
        self.assertEqual((77, 168, 83), renderer._color("leaf", SimpleNamespace(species_id=None)))

        # A kind that isn't tinted (e.g. underground roots) stays fixed.
        self.assertEqual(renderer._color("root", sim_a), renderer._color("root", sim_b))

    def test_dense_reproductive_overlays_are_sampled_but_sparse_sets_are_unchanged(self):
        sparse = [
            ("flower", (index * 12, 20), 0.0, 1.0, (200, 100, 100))
            for index in range(12)
        ]
        self.assertEqual(sparse, SpeciesRenderer._sample_reproductive_overlays(sparse))

        dense = [
            ("flower", (index % 20 * 3, index // 20 * 3), 0.0, 1.0, (200, 100, 100))
            for index in range(200)
        ]
        dense.append(("fruit", (0, 0), 0.0, 1.0, (100, 70, 40)))
        first = SpeciesRenderer._sample_reproductive_overlays(dense)
        second = SpeciesRenderer._sample_reproductive_overlays(dense)
        self.assertEqual(first, second)
        self.assertLess(len(first), len(dense) // 3)
        self.assertIn(dense[-1], first)  # mature cone wins the contested cell

    def test_cone_fallback_is_a_tapered_strobilus_not_a_circle(self):
        renderer = SpeciesRenderer(SimpleNamespace(camera=SimpleNamespace()))
        module = SimpleNamespace(length_m=0.16, visual={})
        sim = SimpleNamespace(
            blueprint=SimpleNamespace(
                growth={"reproductive_structure": "cone"},
                module=lambda _kind: module,
            )
        )
        screen = pygame.Surface((64, 64), pygame.SRCALPHA)
        renderer._draw_reproductive_fallback(
            screen,
            sim,
            SimpleNamespace(scale=120.0),
            "fruit",
            (32, 32),
            0.0,
            1.0,
            (105, 78, 43),
        )
        bounds = screen.get_bounding_rect()
        self.assertGreater(bounds.height, bounds.width)
        colors = {screen.get_at((x, y))[:3] for x in range(64) for y in range(64) if screen.get_at((x, y)).a}
        self.assertGreaterEqual(len(colors), 3)  # fill, outline, scale rows

    def test_unasseted_tree_flower_uses_petal_fallback_and_flower_palette(self):
        renderer = SpeciesRenderer(SimpleNamespace(camera=SimpleNamespace()))
        module = SimpleNamespace(length_m=0.08, visual={})
        sim = SimpleNamespace(
            species_id="spec_flower_palette_test",
            blueprint=SimpleNamespace(
                growth={"shape": "tree", "reproductive_structure": "flower"},
                module=lambda _kind: module,
            ),
        )
        color = renderer._color("flower", sim)
        self.assertEqual(
            SpeciesRenderer._species_tint((210, 125, 170), "spec_flower_palette_test:flower"),
            color,
        )
        screen = pygame.Surface((64, 64), pygame.SRCALPHA)
        renderer._draw_reproductive_fallback(
            screen,
            sim,
            SimpleNamespace(scale=120.0),
            "flower",
            (32, 32),
            0.0,
            1.0,
            color,
        )
        bounds = screen.get_bounding_rect()
        self.assertGreater(bounds.width, 5)
        self.assertGreater(bounds.height, 5)
        self.assertIn((225, 190, 76), {
            screen.get_at((x, y))[:3]
            for x in range(64)
            for y in range(64)
            if screen.get_at((x, y)).a
        })

    def test_capitulum_fallback_has_many_pale_rays_and_a_gold_disc(self):
        renderer = SpeciesRenderer(SimpleNamespace(camera=SimpleNamespace()))
        module = SimpleNamespace(length_m=0.08, visual={})
        sim = SimpleNamespace(
            species_id="spec_capitulum_test",
            blueprint=SimpleNamespace(
                growth={"reproductive_structure": "capitulum"},
                module=lambda _kind: module,
            ),
        )
        color = renderer._color("flower", sim)
        self.assertEqual(
            SpeciesRenderer._species_tint(
                SpeciesRenderer._CAPITULUM_RAY_BASE,
                "spec_capitulum_test:flower",
            ),
            color,
        )
        screen = pygame.Surface((64, 64), pygame.SRCALPHA)
        renderer._draw_reproductive_fallback(
            screen,
            sim,
            SimpleNamespace(scale=120.0),
            "flower",
            (32, 32),
            0.0,
            1.0,
            color,
        )
        bounds = screen.get_bounding_rect()
        self.assertGreater(bounds.width, 8)
        self.assertGreater(bounds.height, 8)
        colors = {
            screen.get_at((x, y))[:3]
            for x in range(64)
            for y in range(64)
            if screen.get_at((x, y)).a
        }
        self.assertIn((225, 177, 48), colors)
        self.assertIn(color, colors)

    def test_forb_panicle_is_greener_and_denser_than_graminoid_panicle(self):
        renderer = SpeciesRenderer(SimpleNamespace(camera=SimpleNamespace()))
        module = SimpleNamespace(length_m=0.16, visual={})

        def render(growth_form):
            sim = SimpleNamespace(
                species_id=f"spec_{growth_form}_panicle_test",
                blueprint=SimpleNamespace(
                    growth={
                        "growth_form": growth_form,
                        "reproductive_structure": "panicle",
                    },
                    module=lambda _kind: module,
                ),
            )
            color = renderer._color("flower", sim)
            screen = pygame.Surface((96, 96), pygame.SRCALPHA)
            renderer._draw_reproductive_fallback(
                screen,
                sim,
                SimpleNamespace(scale=120.0),
                "flower",
                (48, 48),
                0.0,
                1.0,
                color,
            )
            opaque = sum(
                screen.get_at((x, y)).a > 0
                for x in range(screen.get_width())
                for y in range(screen.get_height())
            )
            return color, opaque, screen.get_bounding_rect()

        forb_color, forb_opaque, forb_bounds = render("forb")
        grass_color, grass_opaque, _grass_bounds = render("graminoid")
        self.assertNotEqual(forb_color, grass_color)
        self.assertGreater(forb_color[1], forb_color[0])
        self.assertGreater(forb_opaque, grass_opaque)
        self.assertGreater(forb_bounds.height, forb_bounds.width)


if __name__ == "__main__":
    unittest.main()
