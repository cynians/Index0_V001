"""Render a close production-renderer view of a dense mixed asset forest."""

from pathlib import Path
from types import SimpleNamespace
import math
import sys

import pygame

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from simulations.biosphere.biosphere_renderer import BiosphereBuilderRenderer
from simulations.biosphere.biosphere_simulation import BiosphereSimulation
from world.world_model import WorldModel


def main():
    pygame.init()
    width, height = 1500, 900
    world = WorldModel()
    simulation = BiosphereSimulation.reference_site(world)
    asset_species = simulation.get_asset_backed_species_ids()
    terrestrial = [
        species_id for species_id in asset_species
        if simulation.ecology.profiles[species_id].growth_form != "aquatic"
    ]

    # Overlapping, offset population centres make one mixed stand rather than
    # an asset catalogue laid out in rows.
    for index, species_id in enumerate(terrestrial):
        angle = index * math.tau / max(1, len(terrestrial)) + 0.37
        distance = 0.55 + 0.34 * (index % 3)
        x = 5.0 + math.cos(angle) * distance
        y = 5.0 + math.sin(angle) * distance
        form = simulation.ecology.profiles[species_id].growth_form
        radius = 1.55 if form == "tree" else 1.20
        simulation.ecology.introduce(species_id, x, y, radius, propagule_pressure=0.72)

    simulation.representatives.sync_from_population(simulation.ecology)
    for index, representative in enumerate(simulation.representatives.items(alive_only=True)):
        maturity = 0.58 + (index % 5) * 0.075
        representative.age_days = representative.simulation.mature_age_days * maturity
        representative.simulation.set_age(representative.age_days)

    simulation.test_forest_species_ids = terrestrial
    simulation.isometric_fullscreen_preview = True
    simulation.isometric_view_zoom = 1.72
    simulation.isometric_view_center = (5.0, 5.0)
    simulation.isometric_sprite_height_cap = 154

    surface = pygame.Surface((width, height))
    view = SimpleNamespace(camera=SimpleNamespace(zoom=1.0))
    BiosphereBuilderRenderer(view).draw(surface, simulation)

    font = pygame.font.SysFont("consolas", 18)
    title = font.render("MIXED FOREST  ·  SPECIES SIM REPRESENTATIVES  ·  FREE-COORDINATE CLOSE VIEW", True, (213, 225, 195))
    label_bg = pygame.Surface((title.get_width() + 28, 42), pygame.SRCALPHA)
    label_bg.fill((10, 16, 13, 210))
    surface.blit(label_bg, (24, 22))
    surface.blit(title, (38, 33))

    output = PROJECT_ROOT / "artifacts" / "biosphere_mixed_forest_closeup.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    pygame.image.save(surface, output)
    print(output)
    print("\n".join(terrestrial))


if __name__ == "__main__":
    main()
