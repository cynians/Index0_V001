"""Render fixed wet/control and drought BioSim reference-site treatments."""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pygame

from engine.camera import Camera
from simulations.bioregion.bioregion_renderer import BioregionRenderer
from simulations.bioregion.bioregion_simulation import BioregionSimulation


def _render_panel(sim, size, title, subtitle):
    panel = pygame.Surface(size)
    panel.fill((13, 18, 15))
    camera = Camera(size[0], size[1])
    camera.x = 500.0
    camera.y = 500.0
    camera.zoom = min((size[0] - 36) / 1000.0, (size[1] - 100) / 1000.0)
    view = SimpleNamespace(camera=camera, width=size[0], height=size[1])
    BioregionRenderer(view).draw(panel, sim)
    font = pygame.font.Font(None, 30)
    small = pygame.font.Font(None, 20)
    panel.blit(font.render(title, True, (225, 235, 218)), (16, 12))
    panel.blit(small.render(subtitle, True, (170, 187, 164)), (16, 42))
    summary = sim.get_ecosystem_summary()
    metrics = (
        f"biomass {summary['mean_biomass_kg_m2']:.3f} kg/m2 | "
        f"SOM {summary['mean_soil_organic_matter_kg_m2']:.3f} kg/m2 | "
        f"ground light {summary['mean_ground_light_fraction']:.3f}"
    )
    panel.blit(small.render(metrics, True, (215, 220, 190)), (16, size[1] - 26))
    return panel


def main():
    pygame.init()
    pygame.display.set_mode((1, 1))
    control = BioregionSimulation.reference_site()
    drought = BioregionSimulation.reference_site()
    for cell in drought.grid.iter_cells():
        cell["top_moisture"] *= 0.10
        cell["deep_moisture"] *= 0.18
        cell["temperature_k"] += 5.0
    control.advance_ecology(120.0)
    drought.advance_ecology(120.0)

    panel_size = (720, 760)
    sheet = pygame.Surface((panel_size[0] * 2, panel_size[1]))
    sheet.blit(_render_panel(
        control, panel_size, "Reference site — inherited moisture",
        "LOD4 authored fixture, 120 ecological days",
    ), (0, 0))
    sheet.blit(_render_panel(
        drought, panel_size, "Paired drought treatment",
        "Same terrain and initial vegetation; runtime climate override",
    ), (panel_size[0], 0))
    output = Path(__file__).resolve().parents[1] / "artifacts" / "biosphere_reference_site_comparison.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    pygame.image.save(sheet, output)
    print(output)


if __name__ == "__main__":
    main()
