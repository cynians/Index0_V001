"""Render the Species Sim diagnostic views for visual QA."""

from pathlib import Path
from types import SimpleNamespace

import pygame

from engine.camera import Camera
from simulations.species.species_renderer import SpeciesRenderer
from simulations.species.species_simulation import SpeciesSimulation
from world.entity_loader import EntityLoader


OUTPUT_ROOT = Path(
    r"C:\Users\logol\.codex\visualizations\2026\09\02\01a06445-0961-7e70-b041-8bd9cc4e1863"
)


def render_views(species_id="spec_betula_pendula"):
    pygame.init()
    pygame.font.init()
    pygame.display.set_mode((1, 1))
    species = EntityLoader().entities.get(species_id)
    if not isinstance(species, dict):
        raise RuntimeError(f"Species entity not found: {species_id}")

    camera = Camera(1200, 800)
    simulation = SpeciesSimulation(species_entity=species, species_id=species_id, seed=303)
    simulation.set_age(simulation.mature_age_days)
    app_view = SimpleNamespace(camera=camera)
    renderer = SpeciesRenderer(app_view)
    camera.x, camera.y = simulation.get_center()
    camera.zoom = simulation.get_initial_camera_zoom(1200, 800)

    outputs = {}
    for view, filename in (
        ("individual", "species_sim_individual_preview.png"),
        ("top_down", "species_sim_top_down_preview.png"),
        ("gallery", "species_sim_gallery_preview.png"),
        ("forest", "species_sim_forest_preview.png"),
        ("compare", "species_sim_compare_preview.png"),
    ):
        simulation.set_active_simulation_panel_tab(view)
        screen = pygame.Surface((1200, 800))
        renderer.draw(screen, simulation)
        target = OUTPUT_ROOT / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        pygame.image.save(screen, target)
        outputs[view] = str(target)
    pygame.quit()
    return outputs


if __name__ == "__main__":
    print(render_views())
