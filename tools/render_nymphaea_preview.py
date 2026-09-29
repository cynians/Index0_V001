"""Render the Nymphaea alba Species Sim and its five-day telemetry panel."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pygame

from simulations.species.plant_assets import PlantAssetStore
from simulations.species.species_renderer import SpeciesRenderer
from simulations.species.species_simulation import SpeciesSimulation
from world.entity_loader import EntityLoader


class PreviewCamera:
    def world_to_screen(self, position):
        return int(290 + position[0] * 240), int(560 - position[1] * 420)


def main():
    root = Path(__file__).resolve().parents[1]
    pygame.init()
    pygame.font.init()
    pygame.display.set_mode((1, 1))

    loader = EntityLoader()
    store = PlantAssetStore(root / "assets" / "plants")
    sim = SpeciesSimulation(
        species_entity=loader.entities["spec_nymphaea_alba"],
        seed=202,
        asset_store=store,
    )
    sim.set_age(180)

    screen = pygame.Surface((1100, 760))
    renderer = SpeciesRenderer(SimpleNamespace(camera=PreviewCamera()))
    renderer.draw(screen, sim)

    # Make the reference plane legible as water without hiding the generated
    # petioles, leaves, or submerged rhizome.
    pygame.draw.line(screen, (85, 150, 170), (24, 560), (690, 560), 2)
    font = pygame.font.SysFont("consolas", 18)
    small = pygame.font.SysFont("consolas", 15)
    pygame.draw.rect(screen, (25, 31, 40), (720, 24, 350, 712))
    pygame.draw.rect(screen, (120, 135, 160), (720, 24, 350, 712), 1)
    lines = [
        "Nymphaea alba",
        "European white water lily",
        "Age: 180 days | reproductive",
        "Growth: aquatic / sympodial",
        "Lifespan: perennial",
        "",
        "5-day telemetry from germination:",
    ]
    for index, line in enumerate(lines):
        screen.blit(font.render(line, True, (232, 238, 248)), (740, 45 + index * 24))

    telemetry_path = root / "assets" / "plants" / "telemetry" / "spec_nymphaea_alba_5day.json"
    samples = json.loads(telemetry_path.read_text(encoding="utf-8"))["samples"]
    screen.blit(small.render("day  age  phase        mat  vitality", True, (170, 190, 215)), (740, 245))
    for index, row in enumerate(samples):
        label = (
            f"{row['elapsed_days']:>3.0f} {row['age_days']:>4.0f} "
            f"{row['life_phase']:<13} {row['maturity']:.2f} {row['vitality']:.2f}"
        )
        screen.blit(small.render(label, True, (205, 220, 220)), (740, 267 + index * 22))

    module_y = 267 + len(samples) * 22 + 28
    screen.blit(small.render("Modules used:", True, (170, 190, 215)), (740, module_y))
    screen.blit(small.render("leaf: painted floating blade", True, (205, 220, 220)), (740, module_y + 22))
    screen.blit(small.render("flower: painted radial blooms", True, (205, 220, 220)), (740, module_y + 44))
    screen.blit(small.render("anchors: petiole + growth vector", True, (205, 220, 220)), (740, module_y + 66))

    leaf = pygame.image.load(str(root / "assets" / "illustrations" / "idea_nymphaea_alba_leaf_pixel_pixel.png"))
    flower = pygame.image.load(str(root / "assets" / "illustrations" / "idea_nymphaea_alba_flower_pixel_pixel.png"))
    screen.blit(pygame.transform.scale(leaf, (150, 150)), (35, 35))
    screen.blit(pygame.transform.scale(flower, (150, 150)), (190, 35))
    screen.blit(small.render("leaf module", True, (205, 220, 220)), (65, 192))
    screen.blit(small.render("flower module", True, (205, 220, 220)), (210, 192))

    output = Path(
        r"C:\Users\logol\.codex\visualizations\2026\09\02\01a06445-0961-7e70-b041-8bd9cc4e1863\nymphaea_alba_species_sim_preview.png"
    )
    pygame.image.save(screen, str(output))
    print(output)


if __name__ == "__main__":
    main()
