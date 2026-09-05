import os
import unittest
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


if __name__ == "__main__":
    unittest.main()
