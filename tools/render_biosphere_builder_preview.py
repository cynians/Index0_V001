"""Render a deterministic before/after preview through the production map renderer."""

from pathlib import Path
from types import SimpleNamespace
import sys

import pygame

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from simulations.biosphere.biosphere_simulation import BiosphereSimulation
from simulations.biosphere.biosphere_renderer import BiosphereBuilderRenderer
from simulations.map.map_renderer import MapRenderer
from world.world_model import WorldModel


class PreviewCamera:
    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.x = 5.0
        self.y = 5.0
        self.zoom = min((width - 40) / 10.0, (height - 70) / 10.0)

    def world_to_screen(self, position):
        return (
            (position[0] - self.x) * self.zoom + self.width / 2,
            (position[1] - self.y) * self.zoom + self.height / 2,
        )


def _render(simulation, width=760, height=570):
    surface = pygame.Surface((width, height))
    surface.fill((19, 22, 24))
    view = SimpleNamespace(
        camera=PreviewCamera(width, height),
        width=width,
        height=height,
        default_font=pygame.font.Font(None, 18),
    )
    MapRenderer(view).draw(surface, simulation)
    BiosphereBuilderRenderer(view).draw(surface, simulation)
    return surface


def main():
    pygame.init()
    world_model = WorldModel()
    before = BiosphereSimulation.reference_site(world_model)
    before.place_selected_species(5.0, 5.0)

    after = BiosphereSimulation.reference_site(world_model)
    after.place_selected_species(5.0, 5.0)
    after.advance_seasons(8)
    after.select_species("spec_betula_pendula")
    after.place_selected_species(7.1, 3.2, propagule_pressure=0.24)
    after.select_species("spec_nymphaea_alba")
    after.place_selected_species(3.0, 7.1, propagule_pressure=0.32)
    after.advance_seasons(10)

    output = pygame.Surface((1540, 640))
    output.fill((12, 15, 17))
    output.blit(_render(before), (10, 55))
    output.blit(_render(after), (770, 55))
    font = pygame.font.Font(None, 30)
    output.blit(font.render("PLACED INTRODUCTION · SEASON 0", True, (225, 231, 221)), (28, 17))
    output.blit(font.render("ESTABLISHMENT + SPREAD · SEASON 18", True, (225, 231, 221)), (788, 17))
    output_path = Path("artifacts/biosphere_builder_map_preview.png")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pygame.image.save(output, output_path)
    print(output_path.resolve())


if __name__ == "__main__":
    main()
