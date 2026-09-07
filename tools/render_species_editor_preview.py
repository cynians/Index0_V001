"""Render the real Species Editor view with a deterministic mature plant."""

import argparse
from pathlib import Path
from types import SimpleNamespace

import pygame

from simulations.species.species_renderer import SpeciesRenderer
from simulations.species.species_simulation import SpeciesSimulation
from world.persistent_ontology_store import PersistentOntologyStore


def render(output_path, species_id="spec_betula_pendula"):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pygame.init()
    pygame.display.set_mode((1, 1))
    species = PersistentOntologyStore(Path("ontology/index0.owl")).load_datasets()["species"]
    entity = next(row for row in species if row.get("id") == species_id)
    simulation = SpeciesSimulation(species_entity=entity, seed=303)
    simulation.set_active_simulation_panel_tab("editor")
    simulation.species_editor["query"] = "branch"
    surface = pygame.Surface((1680, 1000))
    SpeciesRenderer(SimpleNamespace(camera=None)).draw(surface, simulation)
    pygame.image.save(surface, output_path)
    simulation.species_editor["preview_mode"] = "variation"
    simulation._species_editor_last_previews = None
    variation = pygame.Surface((1680, 1000))
    SpeciesRenderer(SimpleNamespace(camera=None)).draw(variation, simulation)
    variation_path = output_path.with_name(f"{output_path.stem}_variation{output_path.suffix}")
    pygame.image.save(variation, variation_path)
    pygame.quit()
    print(output_path.resolve())
    print(variation_path.resolve())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/species_editor_v001/species_editor_birch.png"),
    )
    parser.add_argument("--species", default="spec_betula_pendula")
    args = parser.parse_args()
    render(args.output, args.species)
