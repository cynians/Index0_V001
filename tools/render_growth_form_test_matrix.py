"""Render the growth-form coverage set using the Species Sim renderer."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pygame

from simulations.species.species_renderer import SpeciesRenderer, diagnostic_cell_bounds
from simulations.species.species_simulation import SpeciesSimulation
from world.entity_loader import EntityLoader


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT = PROJECT_ROOT / "assets" / "plants" / "growth_form_test_matrix.png"

TEST_SET = (
    ("tree", "spec_betula_pendula"),
    ("shrub", "spec_rosa_woodsii"),
    ("subshrub", "spec_praxelis_clematidea"),
    ("forb", "spec_erigeron_annuus"),
    ("graminoid", "spec_lolium_perenne"),
    ("fern", "spec_pteridium_aquilinum"),
    ("succulent", "spec_agave_americana"),
    ("aquatic", "spec_nymphaea_alba"),
)


def render_matrix(output=OUTPUT):
    pygame.init()
    pygame.font.init()
    pygame.display.set_mode((1, 1))
    loader = EntityLoader(
        entries_directory=PROJECT_ROOT / "entries",
        ontology_path=PROJECT_ROOT / "ontology" / "index0.owl",
        use_ontology=True,
    )
    renderer = SpeciesRenderer(SimpleNamespace(camera=None))
    width, height = 1600, 940
    columns, rows = 4, 2
    header_height = 44
    cell_width, cell_height = width // columns, (height - header_height) // rows
    screen = pygame.Surface((width, height))
    screen.fill((10, 15, 14))
    title_font = pygame.font.SysFont("consolas", 20)
    label_font = pygame.font.SysFont("consolas", 15)
    small_font = pygame.font.SysFont("consolas", 12)

    for index, (growth_form, species_id) in enumerate(TEST_SET):
        species = loader.entities.get(species_id)
        simulation = SpeciesSimulation(species_entity=species, species_id=species_id, seed=17)
        simulation.set_age(simulation.mature_age_days)
        col, row = index % columns, index // columns
        x, y = col * cell_width, header_height + row * cell_height
        body = pygame.Surface((cell_width, cell_height - 46))
        bounds = diagnostic_cell_bounds(simulation.render_snapshot)
        renderer.app_view.camera = _MatrixCamera(body.get_width(), body.get_height(), bounds)
        renderer._draw_individual(body, simulation, camera=renderer.app_view.camera)
        screen.blit(body, (x, y + 46))
        pygame.draw.rect(screen, (75, 101, 94), (x, y, cell_width, cell_height), 1)
        screen.blit(label_font.render(growth_form, True, (232, 239, 234)), (x + 10, y + 9))
        screen.blit(small_font.render(
            f"{species.get('common_name', species_id)} • {simulation.blueprint.growth.get('shape')} grammar • 3D",
            True,
            (154, 182, 169),
        ), (x + 10, y + 29))

    screen.blit(title_font.render("Species Sim — Growth Form Coverage", True, (238, 244, 240)), (16, 10))
    output.parent.mkdir(parents=True, exist_ok=True)
    pygame.image.save(screen, output)
    pygame.quit()
    return output


class _MatrixCamera:
    def __init__(self, width, height, bounds):
        min_x, max_x, min_z, max_z = bounds
        self.center_x = (min_x + max_x) * 0.5
        self.screen_center_x = width * 0.5
        self.min_z = min_z
        self.scale = min(
            (width - 28) / max(0.1, max_x - min_x),
            (height - 26) / max(0.1, max_z - min_z),
        ) * 0.68
        self.bottom = height - 22

    def world_to_screen(self, position):
        x, z = float(position[0]), float(position[1])
        return (
            round(self.screen_center_x + (x - self.center_x) * self.scale),
            round(self.bottom - (z - self.min_z) * self.scale),
        )

    def world_to_screen_3d(self, position):
        return self.world_to_screen((float(position[0]) + float(position[1]) * 1.8, float(position[2])))


if __name__ == "__main__":
    print(render_matrix())
