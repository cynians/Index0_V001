"""Render the production BioSim HUD and full-screen species catalogue."""

from pathlib import Path
from types import SimpleNamespace
import sys

import pygame

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from simulations.biosphere.biosphere_renderer import BiosphereBuilderRenderer
from simulations.biosphere.biosphere_simulation import BiosphereSimulation
from simulations.map.map_renderer import MapRenderer
from ui.ui_manager import UIManager
from world.world_model import WorldModel


class PreviewCamera:
    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.x = 5.0
        self.y = 5.0
        self.zoom = min((width - 80) / 10.0, (height - 120) / 10.0)

    def world_to_screen(self, position):
        return (
            (position[0] - self.x) * self.zoom + self.width / 2,
            (position[1] - self.y) * self.zoom + self.height / 2,
        )


def render_frame(simulation, width=1600, height=900):
    surface = pygame.Surface((width, height))
    surface.fill((18, 24, 22))
    font = pygame.font.SysFont("consolas", 16)
    view = SimpleNamespace(camera=PreviewCamera(width, height), width=width, height=height, default_font=font)
    MapRenderer(view).draw(surface, simulation)
    BiosphereBuilderRenderer(view).draw(surface, simulation)
    ui = UIManager()
    ui.rebuild_for_state(simulation, width, height, camera=view.camera, world_model=simulation.world_model)
    ui.draw(surface, font)
    return surface


def main():
    pygame.init()
    world_model = WorldModel()
    simulation = BiosphereSimulation.reference_site(world_model)
    planted = simulation.plant_asset_test_forest()
    simulation.set_builder_time_scale(4.0)
    simulation.update(2.5)

    output_dir = Path("artifacts")
    output_dir.mkdir(parents=True, exist_ok=True)
    hud_path = output_dir / "biosphere_isometric_asset_forest.png"
    pygame.image.save(render_frame(simulation), hud_path)

    simulation.open_species_picker()
    picker_path = output_dir / "biosphere_species_catalogue.png"
    pygame.image.save(render_frame(simulation), picker_path)
    print(hud_path.resolve())
    print(picker_path.resolve())
    print(f"asset-backed plants: {len(planted)}")
    print("\n".join(planted))


if __name__ == "__main__":
    main()
