"""Render reproducible Species Sim vine-development comparisons.

The baseline capture is deliberately opt-in and refuses to overwrite an
existing file.  This keeps the pre-development renderer product stable while
the reusable vine grammar evolves.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import pygame

from simulations.species.plant_assets import PlantGrowthSnapshot
from simulations.species.species_renderer import (
    DiagnosticCamera,
    SpeciesRenderer,
    TopDownDiagnosticCamera,
    diagnostic_cell_bounds,
    top_down_diagnostic_bounds,
)
from simulations.species.species_simulation import SpeciesSimulation


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT = PROJECT_ROOT / "artifacts" / "vine_climbing"
SEED = 417
VINE_FIXTURE = {
    "id": "fixture_vine_experimental",
    "pretty_name": "Experimental vine fixture",
    "plant_growth_form": "vine",
    "plant_growth_behaviour": "climbing_support_dependent",
    "plant_woodiness": "herbaceous",
    "mature_height": {"max_m": 5.0},
    "maturity_rate": "moderate",
    "leaf_arrangement": "alternate",
    "leaf_attachment_pattern": "along_stem",
    "leaf_size_class": "medium",
    "root_architecture": "fibrous",
    "root_depth_class": "shallow",
}
TREE_SUPPORT_ENVIRONMENT = {
    "climbing_supports": [{
        "id": "tree_support_fixture",
        "kind": "tree",
        "center_m": [1.35, 0.15],
        "radius_m": 0.16,
        "height_m": 4.0,
        "crown_radius_m": 1.0,
    }],
}


def _union_bounds(snapshots):
    bounds = [diagnostic_cell_bounds(snapshot) for snapshot in snapshots]
    return (
        min(item[0] for item in bounds),
        max(item[1] for item in bounds),
        min(item[2] for item in bounds),
        max(item[3] for item in bounds),
    )


def _capture_baseline() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    snapshot_path = OUTPUT / "baseline_snapshot.json"
    image_path = OUTPUT / "baseline.png"
    if snapshot_path.exists() or image_path.exists():
        raise RuntimeError("Refusing to overwrite the frozen vine baseline")

    simulation = SpeciesSimulation(species_entity=VINE_FIXTURE, seed=SEED)
    simulation.lod = 2
    simulation.set_age(simulation.mature_age_days)
    snapshot_path.write_text(
        json.dumps(simulation.render_snapshot.to_dict(), indent=2),
        encoding="utf-8",
    )

    pygame.init()
    pygame.display.set_mode((1, 1))
    surface = pygame.Surface((920, 720))
    renderer = SpeciesRenderer(SimpleNamespace(camera=None))
    renderer._draw_individual(
        surface,
        simulation,
        camera=DiagnosticCamera(920, 720, diagnostic_cell_bounds(simulation.render_snapshot)),
        show_height_reference=True,
        cache=False,
    )
    pygame.image.save(surface, image_path)
    pygame.quit()
    print(json.dumps({
        "snapshot": str(snapshot_path),
        "image": str(image_path),
        "stats": simulation.render_snapshot.stats,
        "bounds_m": simulation.render_snapshot.bounds_m,
    }, indent=2))


def _render_comparisons() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    baseline_path = OUTPUT / "baseline_snapshot.json"
    if not baseline_path.exists():
        raise RuntimeError("Capture the frozen pre-development baseline first")
    baseline = PlantGrowthSnapshot.from_dict(json.loads(baseline_path.read_text(encoding="utf-8")))

    ground = SpeciesSimulation(species_entity=VINE_FIXTURE, seed=SEED)
    ground.lod = 2
    ground.set_age(ground.mature_age_days)
    climbing = SpeciesSimulation(
        species_entity=VINE_FIXTURE,
        seed=SEED,
        environment=TREE_SUPPORT_ENVIRONMENT,
    )
    climbing.lod = 2
    climbing.set_age(climbing.mature_age_days)

    pygame.init()
    pygame.display.set_mode((1, 1))
    renderer = SpeciesRenderer(SimpleNamespace(camera=None))
    title = pygame.font.SysFont("consolas", 27)
    font = pygame.font.SysFont("consolas", 17)
    small = pygame.font.SysFont("consolas", 14)

    snapshots = (baseline, ground.render_snapshot, climbing.render_snapshot)
    shared_bounds = _union_bounds(snapshots)
    sheet = pygame.Surface((2040, 940))
    sheet.fill((14, 21, 18))
    sheet.blit(title.render(
        "Species Sim vine grammar | unsupported search to tree ascent",
        True, (230, 239, 221),
    ), (24, 18))
    sheet.blit(font.render(
        "Experimental fixture | maturity | seed 417 | shared physical scale",
        True, (164, 187, 169),
    ), (24, 56))
    captions = (
        "BEFORE | generic unsupported crown",
        "GROUND | prostrate support search",
        "TREE | contact transition + helical ascent",
    )
    simulations = (ground, ground, climbing)
    for index, (snapshot, simulation, caption) in enumerate(zip(snapshots, simulations, captions)):
        x = index * 680
        panel = pygame.Surface((660, 740))
        renderer._draw_individual(
            panel,
            simulation,
            snapshot=snapshot,
            camera=DiagnosticCamera(660, 740, shared_bounds),
            cache=False,
        )
        sheet.blit(font.render(caption, True, (222, 233, 214)), (x + 18, 92))
        sheet.blit(panel, (x + 10, 124))
    before_stats = baseline.stats
    ground_stats = ground.render_snapshot.stats
    climb_stats = climbing.render_snapshot.stats
    footer = (
        f"Before: {before_stats.get('branch_count', 0)} unsupported branches, {baseline.bounds_m[5]:.2f} m high",
        f"Ground: {ground_stats['vine_ground_axis_length_m']:.2f} m axis, {ground.render_snapshot.bounds_m[5]:.2f} m high",
        f"Tree: {climb_stats['vine_climbing_height_m']:.2f} m ascent, {climb_stats['vine_turn_count']:.2f} turns",
    )
    for index, text in enumerate(footer):
        sheet.blit(small.render(text, True, (178, 194, 179)), (index * 680 + 18, 894))
    pygame.image.save(sheet, OUTPUT / "development_comparison.png")

    top_bounds = top_down_diagnostic_bounds(ground)
    detail = pygame.Surface((1080, 780))
    detail.fill((14, 21, 18))
    detail.blit(title.render("Unsupported vine | ground-search detail", True, (230, 239, 221)), (24, 18))
    detail.blit(font.render(
        "The connected axis remains close to the substrate when no reachable support is supplied.",
        True, (164, 187, 169),
    ), (24, 56))
    panel = pygame.Surface((1040, 640))
    renderer._draw_individual(
        panel,
        ground,
        camera=TopDownDiagnosticCamera(1040, 640, top_bounds),
        show_height_reference=False,
        draw_ground_line=False,
        cache=False,
    )
    detail.blit(panel, (20, 92))
    detail.blit(small.render(
        f"Axis {ground_stats['vine_axis_length_m']:.2f} m | max shoot z {max(p[4] for p in ground.render_snapshot.placements if p[0] == 'stem_section'):.2f} m | no support contact",
        True, (178, 194, 179),
    ), (24, 752))
    pygame.image.save(detail, OUTPUT / "ground_search_detail.png")

    results = {
        "provenance": {
            "fixture": "deliberate experimental override; no live ontology species currently authors plant_growth_form=vine",
            "seed": SEED,
            "age_days": ground.mature_age_days,
            "lod": 2,
            "tree_support": TREE_SUPPORT_ENVIRONMENT["climbing_supports"][0],
        },
        "baseline": {
            "bounds_m": baseline.bounds_m,
            "placement_count": before_stats.get("placement_count"),
            "branch_count": before_stats.get("branch_count"),
            "stem_count": before_stats.get("stem_count"),
        },
        "ground": {key: value for key, value in ground_stats.items() if key.startswith("vine_")},
        "tree": {key: value for key, value in climb_stats.items() if key.startswith("vine_")},
        "artifacts": {
            "baseline": str(baseline_path),
            "comparison": str(OUTPUT / "development_comparison.png"),
            "ground_detail": str(OUTPUT / "ground_search_detail.png"),
        },
    }
    (OUTPUT / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    pygame.quit()
    print(json.dumps(results, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture-baseline", action="store_true")
    args = parser.parse_args()
    if args.capture_baseline:
        _capture_baseline()
    else:
        _render_comparisons()


if __name__ == "__main__":
    main()
