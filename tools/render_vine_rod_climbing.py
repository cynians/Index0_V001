"""Render a fixed-seed vine finding and circling a structural rod."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import pygame

from simulations.species.plant_assets import PlantGrowthSnapshot
from simulations.species.species_renderer import (
    DiagnosticCamera,
    IsometricDiagnosticCamera,
    SpeciesRenderer,
    TopDownDiagnosticCamera,
    diagnostic_cell_bounds,
)
from simulations.species.species_simulation import SpeciesSimulation
from tools.render_vine_climbing import VINE_FIXTURE


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT = PROJECT_ROOT / "artifacts" / "vine_rod_climbing"
SEED = 733
ROD = {
    "id": "steel_rod_fixture",
    "kind": "rod",
    "position_m": [1.10, 0.35, 0.0],
    "radius_m": 0.055,
    "height_m": 3.60,
    "palette": {"fill": [100, 111, 116], "highlight": [190, 205, 208]},
}
ROD_ENVIRONMENT = {"rod_structures": [ROD]}


def _mature(environment):
    simulation = SpeciesSimulation(species_entity=VINE_FIXTURE, seed=SEED, environment=environment)
    simulation.lod = 2
    simulation.set_age(simulation.mature_age_days)
    return simulation


def _capture_baseline():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    snapshot_path = OUTPUT / "baseline_ignored_rod_snapshot.json"
    image_path = OUTPUT / "baseline_ignored_rod.png"
    if snapshot_path.exists() or image_path.exists():
        raise RuntimeError("Refusing to overwrite the frozen pre-rod baseline")
    simulation = _mature(ROD_ENVIRONMENT)
    snapshot_path.write_text(json.dumps(simulation.render_snapshot.to_dict(), indent=2), encoding="utf-8")
    pygame.init()
    pygame.display.set_mode((1, 1))
    renderer = SpeciesRenderer(SimpleNamespace(camera=None))
    surface = pygame.Surface((900, 700))
    renderer._draw_individual(
        surface,
        simulation,
        camera=DiagnosticCamera(900, 700, diagnostic_cell_bounds(simulation.render_snapshot)),
        cache=False,
    )
    pygame.image.save(surface, image_path)
    pygame.quit()
    print(json.dumps({
        "snapshot": str(snapshot_path),
        "image": str(image_path),
        "vine_phase": simulation.render_snapshot.stats.get("vine_phase"),
        "selected_support": simulation.render_snapshot.stats.get("vine_selected_support_id"),
        "environment": ROD_ENVIRONMENT,
    }, indent=2))


def _bounds(snapshot):
    bounds = list(snapshot.bounds_m)
    for rod in snapshot.stats.get("rod_structures") or []:
        x, y, z = rod["position_m"]
        radius = float(rod["radius_m"])
        bounds[0] = min(bounds[0], x - radius)
        bounds[1] = max(bounds[1], x + radius)
        bounds[2] = min(bounds[2], y - radius)
        bounds[3] = max(bounds[3], y + radius)
        bounds[4] = min(bounds[4], z)
        bounds[5] = max(bounds[5], z + float(rod["height_m"]))
    return tuple(bounds)


def _render():
    baseline_path = OUTPUT / "baseline_ignored_rod_snapshot.json"
    if not baseline_path.exists():
        raise RuntimeError("Capture the pre-rod baseline first")
    baseline = PlantGrowthSnapshot.from_dict(json.loads(baseline_path.read_text(encoding="utf-8")))
    current = _mature(ROD_ENVIRONMENT)
    snapshot = current.render_snapshot
    bounds = _bounds(snapshot)

    pygame.init()
    pygame.display.set_mode((1, 1))
    renderer = SpeciesRenderer(SimpleNamespace(camera=None))
    title = pygame.font.SysFont("consolas", 25)
    font = pygame.font.SysFont("consolas", 16)
    small = pygame.font.SysFont("consolas", 13)
    sheet = pygame.Surface((1800, 780))
    sheet.fill((14, 21, 18))
    sheet.blit(title.render(
        "Structural rod | ground search to cylindrical ascent",
        True,
        (230, 239, 221),
    ), (22, 16))
    sheet.blit(font.render(
        "One fixed 3D state shown in elevation, top-down, and isometric projections",
        True,
        (164, 187, 169),
    ), (22, 52))

    panels = (
        ("BEFORE | rod payload ignored", baseline, DiagnosticCamera(580, 570, diagnostic_cell_bounds(baseline))),
        ("ELEVATION | helix around pole", snapshot, DiagnosticCamera(580, 570, diagnostic_cell_bounds(snapshot))),
        ("TOP-DOWN | circular clearance", snapshot, TopDownDiagnosticCamera(580, 570, bounds[:4])),
    )
    for index, (label, panel_snapshot, camera) in enumerate(panels):
        x = index * 600
        panel = pygame.Surface((580, 570))
        renderer._draw_individual(
            panel,
            current,
            snapshot=panel_snapshot,
            camera=camera,
            show_height_reference=False,
            draw_ground_line=index != 2,
            cache=False,
        )
        sheet.blit(font.render(label, True, (219, 231, 211)), (x + 18, 88))
        sheet.blit(panel, (x + 10, 120))

    stats = snapshot.stats
    sheet.blit(small.render("unsupported ground-search axis", True, (176, 196, 177)), (18, 726))
    sheet.blit(small.render(
        f"approach {stats['vine_ground_axis_length_m']:.2f} m | climb {stats['vine_climbing_height_m']:.2f} m | {stats['vine_turn_count']:.2f} turns",
        True,
        (176, 196, 177),
    ), (618, 726))
    sheet.blit(small.render(
        f"rod r={stats['vine_selected_support_radius_m']:.3f} m | vine clearance {stats['vine_support_clearance_m']:.3f} m",
        True,
        (176, 196, 177),
    ), (1218, 726))
    comparison_path = OUTPUT / "rod_climbing_views.png"
    pygame.image.save(sheet, comparison_path)

    isometric = pygame.Surface((900, 720))
    renderer._draw_individual(
        isometric,
        current,
        camera=IsometricDiagnosticCamera(900, 720, bounds),
        show_height_reference=False,
        draw_ground_line=False,
        cache=False,
    )
    isometric_path = OUTPUT / "rod_climbing_isometric.png"
    pygame.image.save(isometric, isometric_path)
    results = {
        "provenance": {"seed": SEED, "age_days": current.mature_age_days, "lod": 2, "rod": ROD},
        "before": {
            "phase": baseline.stats.get("vine_phase"),
            "selected_support": baseline.stats.get("vine_selected_support_id"),
        },
        "after": {key: value for key, value in stats.items() if key.startswith("vine_") or key == "rod_structures"},
        "artifacts": {"comparison": str(comparison_path), "isometric": str(isometric_path)},
    }
    (OUTPUT / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    pygame.quit()
    print(json.dumps(results, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture-baseline", action="store_true")
    args = parser.parse_args()
    if args.capture_baseline:
        _capture_baseline()
    else:
        _render()


if __name__ == "__main__":
    main()
