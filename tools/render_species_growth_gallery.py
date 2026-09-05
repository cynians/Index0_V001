"""Render a 20-individual maturity gallery for one Species Sim species."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import pygame

from simulations.species.species_diagnostics import build_growth_gallery
from simulations.species.species_renderer import SpeciesRenderer, diagnostic_cell_bounds
from simulations.species.plant_assets import PlantAssetStore
from world.entity_loader import EntityLoader


class GalleryCamera:
    def __init__(self, cell_width, cell_height, bounds):
        min_x, max_x, min_z, max_z = bounds
        self.min_x = min_x
        self.min_z = min_z
        self.scale = min(
            (cell_width - 24) / max(0.1, max_x - min_x),
            (cell_height - 90) / max(0.1, max_z - min_z),
        )
        self.center_x = (min_x + max_x) * 0.5
        self.screen_center_x = cell_width * 0.5
        self.bottom = cell_height - 24

    def world_to_screen(self, position):
        x, z = float(position[0]), float(position[1])
        return round(self.screen_center_x + (x - self.center_x) * self.scale), round(self.bottom - (z - self.min_z) * self.scale)


def _cell_bounds(snapshot):
    return diagnostic_cell_bounds(snapshot)


def render_gallery(species_id="spec_betula_pendula", output=None):
    root = Path(__file__).resolve().parents[1]
    loader = EntityLoader()
    species = loader.entities.get(species_id)
    if not isinstance(species, dict):
        raise RuntimeError(f"Species entity not found: {species_id}")
    pygame.init()
    pygame.font.init()
    pygame.display.set_mode((1, 1))

    store = PlantAssetStore(root / "assets" / "plants")
    cases = build_growth_gallery(species, species_id=species_id, asset_store=store)
    cell_width, cell_height = 270, 226
    header_height = 72
    screen = pygame.Surface((cell_width * 4, header_height + cell_height * 5))
    screen.fill((13, 18, 17))
    title_font = pygame.font.SysFont("consolas", 24)
    font = pygame.font.SysFont("consolas", 14)
    small = pygame.font.SysFont("consolas", 12)
    display_name = species.get("binomial_name") or species.get("pretty_name") or species_id
    screen.blit(title_font.render(f"Species Sim growth gallery — {display_name}", True, (230, 238, 232)), (18, 14))
    screen.blit(font.render("20 individuals • 4 seeds per maturity stage • LOD 2 • same species assets", True, (157, 181, 169)), (18, 45))
    renderer = SpeciesRenderer(SimpleNamespace(camera=None))
    stage_colors = {
        "seedling": (126, 169, 208),
        "juvenile": (119, 181, 112),
        "mature": (197, 181, 94),
        "reproductive": (219, 147, 92),
        "senescent": (167, 133, 145),
    }
    records = []
    for case in cases:
        col = (case.index - 1) % 4
        row = (case.index - 1) // 4
        x, y = col * cell_width, header_height + row * cell_height
        cell = pygame.Surface((cell_width, cell_height))
        cell.fill((21, 28, 25))
        bounds = _cell_bounds(case.snapshot)
        renderer.app_view.camera = GalleryCamera(cell_width, cell_height, bounds)
        renderer.draw(cell, case.simulation)
        screen.blit(cell, (x, y))
        pygame.draw.rect(screen, stage_colors.get(case.stage, (130, 150, 140)), (x, y, cell_width, cell_height), 1)
        record = case.record()
        records.append(record)
        screen.blit(font.render(f"#{case.index:02}  {case.stage}  •  seed {case.seed}", True, (236, 241, 237)), (x + 8, y + 7))
        screen.blit(small.render(
            f"{case.age_days:>4.0f}d  •  {float(record['maturity']) * 100:>3.0f}%  •  {record['life_phase']}",
            True,
            (201, 215, 205),
        ), (x + 8, y + 27))
        screen.blit(small.render(
            f"seg {record['stem_count']:>2}  •  br {record.get('branch_count', 0):>2}  •  "
            f"cl {record.get('leaf_cluster_count', 0):>2}  •  est leaves {record.get('estimated_leaf_count', 0):>3}",
            True,
            (159, 183, 170),
        ), (x + 8, y + 45))

    output = Path(output) if output else Path(
        r"C:\Users\logol\.codex\visualizations\2026\09\02\01a06445-0961-7e70-b041-8bd9cc4e1863\species_growth_gallery.png"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    pygame.image.save(screen, output)
    mature_case = next(case for case in cases if case.stage == "mature" and case.seed == 303)
    normal_width, normal_height = 600, screen.get_height()
    normal = pygame.Surface((normal_width, normal_height))
    normal.fill((13, 18, 17))
    normal_body = pygame.Surface((normal_width, normal_height - header_height))
    renderer.app_view.camera = GalleryCamera(normal_width, normal_body.get_height(), _cell_bounds(mature_case.snapshot))
    renderer.draw(normal_body, mature_case.simulation)
    normal.blit(normal_body, (0, header_height))
    pygame.draw.rect(normal, (197, 181, 94), normal.get_rect(), 1)
    normal.blit(title_font.render("Normal Species Sim viewport", True, (230, 238, 232)), (18, 14))
    normal.blit(font.render("mature individual • seed 303", True, (157, 181, 169)), (18, 45))
    comparison = pygame.Surface((normal_width + screen.get_width() + 24, screen.get_height()))
    comparison.fill((8, 12, 11))
    comparison.blit(normal, (0, 0))
    comparison.blit(screen, (normal_width + 24, 0))
    pygame.draw.line(comparison, (104, 125, 113), (normal_width + 12, 0), (normal_width + 12, screen.get_height()), 1)
    comparison_output = output.with_name("species_growth_comparison.png")
    pygame.image.save(comparison, comparison_output)
    report_path = root / "assets" / "plants" / "diagnostics" / f"{species_id}_growth_gallery.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps({
        "kind": "species_growth_gallery",
        "species_id": species_id,
        "individual_count": len(records),
        "stages": sorted({record["stage"] for record in records}),
        "records": records,
    }, indent=2) + "\n", encoding="utf-8")
    pygame.quit()
    return output, report_path, comparison_output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--species-id", default="spec_betula_pendula")
    parser.add_argument("--output")
    args = parser.parse_args()
    output, report, comparison = render_gallery(args.species_id, args.output)
    print({"overview": str(output), "comparison": str(comparison), "report": str(report)})


if __name__ == "__main__":
    main()
