import os
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame

from simulations.species.species_renderer import SpeciesRenderer
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


if __name__ == "__main__":
    unittest.main()
