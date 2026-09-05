"""Render mature birch and oak side by side with cluster diagnostics."""

from pathlib import Path
from types import SimpleNamespace

import pygame

from engine.camera import Camera
from simulations.species.species_renderer import DiagnosticCamera, SpeciesRenderer, diagnostic_cell_bounds
from simulations.species.species_simulation import SpeciesSimulation
from world.entity_loader import EntityLoader


OUTPUT = Path(
    r"C:\Users\logol\.codex\visualizations\2026\09\02\01a06445-0961-7e70-b041-8bd9cc4e1863\species_leaf_cluster_comparison.png"
)


def main():
    pygame.init()
    pygame.font.init()
    pygame.display.set_mode((1, 1))
    loader = EntityLoader()
    screen = pygame.Surface((1200, 760))
    screen.fill((13, 18, 17))
    renderer = SpeciesRenderer(SimpleNamespace(camera=Camera(1200, 760)))
    title_font = pygame.font.SysFont("consolas", 22)
    body_font = pygame.font.SysFont("consolas", 13)
    small_font = pygame.font.SysFont("consolas", 11)
    screen.blit(title_font.render("Species Sim leaf-cluster comparison", True, (230, 238, 232)), (18, 18))
    screen.blit(body_font.render("Visible leaf samples remain sparse; clusters carry the estimated canopy load.", True, (157, 181, 169)), (18, 48))

    for index, species_id in enumerate(("spec_betula_pendula", "spec_quercus_robur")):
        species = loader.entities.get(species_id)
        simulation = SpeciesSimulation(species_entity=species, species_id=species_id, seed=303 if index == 0 else 909)
        simulation.set_age(simulation.mature_age_days)
        cell_x = index * 600
        cell = pygame.Surface((600, 670))
        cell.fill((18, 23, 20))
        bounds = diagnostic_cell_bounds(simulation.render_snapshot)
        camera = DiagnosticCamera(600, 670, bounds)
        renderer._draw_individual(cell, simulation, camera=camera)
        screen.blit(cell, (cell_x, 78))
        pygame.draw.rect(screen, (86, 110, 100), (cell_x, 78, 599, 669), 1)
        summary = simulation.get_growth_summary()
        screen.blit(body_font.render(simulation.blueprint.display_name, True, (236, 241, 237)), (cell_x + 14, 90))
        screen.blit(small_font.render(
            f"branches {summary['branch_count']}  •  visible samples {summary['leaf_sample_count']}  •  "
            f"clusters {summary['leaf_cluster_count']}",
            True, (201, 215, 205),
        ), (cell_x + 14, 114))
        screen.blit(small_font.render(
            f"estimated leaves {summary['estimated_leaf_count']}  •  leaf area {summary['leaf_area_m2']:.2f} m²",
            True, (159, 183, 170),
        ), (cell_x + 14, 132))

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    pygame.image.save(screen, OUTPUT)
    pygame.quit()
    print({"output": str(OUTPUT)})


if __name__ == "__main__":
    main()
