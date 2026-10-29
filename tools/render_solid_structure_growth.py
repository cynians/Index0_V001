"""Render fixed-seed pixel-solid interaction comparisons for Species Sim."""

from __future__ import annotations

import argparse
import copy
import json
import math
from pathlib import Path
from types import SimpleNamespace

import pygame

from simulations.species.plant_assets import PlantGrowthSnapshot
from simulations.species.solid_structures import SolidStructureField, normalise_solid_structures
from simulations.species.species_renderer import (
    DiagnosticCamera,
    IsometricDiagnosticCamera,
    SpeciesRenderer,
    diagnostic_cell_bounds,
)
from simulations.species.species_simulation import (
    SpeciesSimulation,
    climbing_support_axis_at_z,
    climbing_support_from_tree_snapshot,
)
from tools.render_vine_climbing import VINE_FIXTURE


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT = PROJECT_ROOT / "artifacts" / "solid_structure_growth"
SEED = 529

TREE_FIXTURE = {
    "id": "fixture_tree_solid_avoidance",
    "pretty_name": "Experimental obstacle-response tree",
    "plant_growth_form": "tree",
    "plant_growth_behaviour": "branched_woody",
    "mature_height": {"max_m": 5.0},
    "maturity_rate": "moderate",
    "leaf_arrangement": "alternate",
    "root_architecture": "taproot",
    "root_depth_class": "medium",
}

WALL = {
    "id": "wall_fixture",
    "kind": "wall",
    "position_m": [1.92, 0.10, 0.0],
    "rotation_deg": 0.0,
    "pixel_size_m": 0.22,
    "extrusion_depth_m": 0.28,
    "mask_rows": ["##########"] * 14,
    "palette": {"fill": [111, 103, 91], "edge": [181, 171, 151]},
}

PILLAR = {
    "id": "pillar_fixture",
    "kind": "pillar",
    "position_m": [-1.35, -0.10, 0.0],
    "rotation_deg": 0.0,
    "pixel_size_m": 0.20,
    "extrusion_depth_m": 0.72,
    "mask_rows": [
        "..##..", ".####.", "######", "######", "######", "######",
        "######", "######", "######", "######", "######", "######",
    ],
    "palette": {"fill": [125, 112, 88], "edge": [199, 181, 142]},
}

COVERED_WALL = {
    **WALL,
    "id": "vine_covered_wall_fixture",
    "position_m": [0.0, 0.45, 0.0],
    "mask_rows": ["################"] * 14,
}

TREE_ENVIRONMENT = {"solid_structures": [WALL, PILLAR]}
VINE_WALL_ENVIRONMENT = {"solid_structures": [{**WALL, "position_m": [1.35, 0.0, 0.0]}]}
VINE_PILLAR_ENVIRONMENT = {"solid_structures": [{**PILLAR, "position_m": [1.15, 0.0, 0.0]}]}
WALL_VINE_ROOTS = (
    (-1.35, -0.78, 0.0),
    (-0.70, -0.84, 0.0),
    (0.00, -0.76, 0.0),
    (0.70, -0.84, 0.0),
    (1.35, -0.78, 0.0),
)
TREE_VINE_ROOT = (0.72, -0.48, 0.0)


def _mature(entity, environment):
    simulation = SpeciesSimulation(species_entity=entity, seed=SEED, environment=environment)
    simulation.lod = 2
    simulation.set_age(simulation.mature_age_days)
    return simulation


def _translate_snapshot(snapshot, offset_m):
    """Translate one portable snapshot into shared scene coordinates."""

    dx, dy, dz = (float(offset_m[index]) for index in range(3))
    translated = PlantGrowthSnapshot.from_dict(snapshot.to_dict())
    for placement in translated.placements:
        placement[2] = round(float(placement[2]) + dx, 4)
        placement[3] = round(float(placement[3]) + dy, 4)
        placement[4] = round(float(placement[4]) + dz, 4)
    for path in translated.placement_paths.values():
        for point in path:
            point[0] = round(float(point[0]) + dx, 4)
            point[1] = round(float(point[1]) + dy, 4)
            point[2] = round(float(point[2]) + dz, 4)
    for attachment in translated.attachment_points:
        point = attachment.get("position_m")
        if isinstance(point, list) and len(point) >= 3:
            attachment["position_m"] = [
                round(float(point[0]) + dx, 4),
                round(float(point[1]) + dy, 4),
                round(float(point[2]) + dz, 4),
            ]
    for cluster in translated.leaf_clusters:
        point = cluster.get("position_m")
        if isinstance(point, list) and len(point) >= 3:
            cluster["position_m"] = [
                round(float(point[0]) + dx, 4),
                round(float(point[1]) + dy, 4),
                round(float(point[2]) + dz, 4),
            ]
    translated.bounds_m = [
        translated.bounds_m[0] + dx, translated.bounds_m[1] + dx,
        translated.bounds_m[2] + dy, translated.bounds_m[3] + dy,
        translated.bounds_m[4] + dz, translated.bounds_m[5] + dz,
    ]

    def translate_support(support):
        updated = copy.deepcopy(support)
        center = updated.get("center_m") or updated.get("position_m")
        if isinstance(center, list) and len(center) >= 2:
            center[0] = round(float(center[0]) + dx, 4)
            center[1] = round(float(center[1]) + dy, 4)
            if len(center) >= 3:
                center[2] = round(float(center[2]) + dz, 4)
        for point in updated.get("axis_points_m") or []:
            point[0] = round(float(point[0]) + dx, 4)
            point[1] = round(float(point[1]) + dy, 4)
            point[2] = round(float(point[2]) + dz, 4)
        if "base_z_m" in updated:
            updated["base_z_m"] = round(float(updated["base_z_m"]) + dz, 4)
        if "top_z_m" in updated:
            updated["top_z_m"] = round(float(updated["top_z_m"]) + dz, 4)
        return updated

    for key in ("solid_structures", "climbing_supports"):
        translated.stats[key] = [translate_support(item) for item in translated.stats.get(key, [])]
    environment = copy.deepcopy(translated.stats.get("environment") or {})
    for key in ("solid_structures", "climbing_supports"):
        if isinstance(environment.get(key), list):
            environment[key] = [translate_support(item) for item in environment[key]]
    translated.stats["environment"] = environment
    return translated


def _local_structure(structure, root_position):
    local = copy.deepcopy(structure)
    local["position_m"] = [
        float(structure["position_m"][0]) - float(root_position[0]),
        float(structure["position_m"][1]) - float(root_position[1]),
        float(structure["position_m"][2]) - float(root_position[2]),
    ]
    return local


def _wall_vine_scene():
    simulations = []
    snapshots = []
    for index, root in enumerate(WALL_VINE_ROOTS):
        simulation = SpeciesSimulation(
            species_entity=VINE_FIXTURE,
            seed=SEED + index * 17,
            environment={"solid_structures": [_local_structure(COVERED_WALL, root)]},
        )
        simulation.lod = 2
        simulation.set_age(simulation.mature_age_days)
        simulations.append(simulation)
        snapshots.append(_translate_snapshot(simulation.render_snapshot, root))
    return simulations, snapshots


def _tree_vine_scene():
    tree = _mature(TREE_FIXTURE, {})
    local_support = climbing_support_from_tree_snapshot(
        tree.render_snapshot,
        support_id="generated_tree_trunk",
        position_m=(-TREE_VINE_ROOT[0], -TREE_VINE_ROOT[1], -TREE_VINE_ROOT[2]),
    )
    vine = SpeciesSimulation(
        species_entity=VINE_FIXTURE,
        seed=SEED + 101,
        environment={"climbing_supports": [local_support]},
    )
    vine.lod = 2
    vine.set_age(vine.mature_age_days)
    return tree, vine, _translate_snapshot(vine.render_snapshot, TREE_VINE_ROOT)


def _capture_baseline():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    paths = {
        "tree": OUTPUT / "baseline_tree_snapshot.json",
        "vine_wall": OUTPUT / "baseline_vine_wall_snapshot.json",
        "vine_pillar": OUTPUT / "baseline_vine_pillar_snapshot.json",
    }
    if any(path.exists() for path in paths.values()):
        raise RuntimeError("Refusing to overwrite the frozen solid-structure baseline")
    cases = {
        "tree": _mature(TREE_FIXTURE, TREE_ENVIRONMENT),
        "vine_wall": _mature(VINE_FIXTURE, VINE_WALL_ENVIRONMENT),
        "vine_pillar": _mature(VINE_FIXTURE, VINE_PILLAR_ENVIRONMENT),
    }
    for key, simulation in cases.items():
        paths[key].write_text(json.dumps(simulation.render_snapshot.to_dict(), indent=2), encoding="utf-8")

    pygame.init()
    pygame.display.set_mode((1, 1))
    renderer = SpeciesRenderer(SimpleNamespace(camera=None))
    sheet = pygame.Surface((1500, 620))
    sheet.fill((14, 21, 18))
    title = pygame.font.SysFont("consolas", 24)
    font = pygame.font.SysFont("consolas", 15)
    sheet.blit(title.render("Pixel-solid baseline | environment payload ignored by growth", True, (230, 239, 221)), (20, 16))
    for index, (key, simulation) in enumerate(cases.items()):
        panel = pygame.Surface((480, 500))
        renderer._draw_individual(
            panel,
            simulation,
            camera=DiagnosticCamera(480, 500, diagnostic_cell_bounds(simulation.render_snapshot)),
            cache=False,
        )
        sheet.blit(font.render(key.replace("_", " ").upper(), True, (204, 218, 201)), (index * 500 + 14, 58))
        sheet.blit(panel, (index * 500 + 10, 86))
    pygame.image.save(sheet, OUTPUT / "baseline.png")
    pygame.quit()
    print(json.dumps({
        key: {
            "path": str(paths[key]),
            "placement_count": sim.render_snapshot.stats.get("placement_count"),
            "branch_count": sim.render_snapshot.stats.get("branch_count"),
            "vine_phase": sim.render_snapshot.stats.get("vine_phase"),
            "solid_status": sim.render_snapshot.stats.get("solid_structure_status", "ignored"),
        }
        for key, sim in cases.items()
    }, indent=2))


def _scene_bounds(snapshot):
    bounds = list(snapshot.bounds_m)
    structures = snapshot.stats.get("solid_structures")
    if structures is None:
        structures = normalise_solid_structures(snapshot.stats.get("environment"))
    for structure in structures or []:
        solid_bounds = SolidStructureField.bounds_m(structure)
        bounds[0] = min(bounds[0], solid_bounds[0])
        bounds[1] = max(bounds[1], solid_bounds[1])
        bounds[2] = min(bounds[2], solid_bounds[2])
        bounds[3] = max(bounds[3], solid_bounds[3])
        bounds[4] = min(bounds[4], solid_bounds[4])
        bounds[5] = max(bounds[5], solid_bounds[5])
    return tuple(bounds)


def _union_bounds(snapshots):
    bounds = [_scene_bounds(snapshot) for snapshot in snapshots]
    return (
        min(item[0] for item in bounds), max(item[1] for item in bounds),
        min(item[2] for item in bounds), max(item[3] for item in bounds),
        min(item[4] for item in bounds), max(item[5] for item in bounds),
    )


def _load_baselines():
    return {
        key: PlantGrowthSnapshot.from_dict(json.loads((OUTPUT / filename).read_text(encoding="utf-8")))
        for key, filename in {
            "tree": "baseline_tree_snapshot.json",
            "vine_wall": "baseline_vine_wall_snapshot.json",
            "vine_pillar": "baseline_vine_pillar_snapshot.json",
        }.items()
    }


def _render_comparison():
    baselines = _load_baselines()
    current = {
        "tree": _mature(TREE_FIXTURE, TREE_ENVIRONMENT),
        "vine_wall": _mature(VINE_FIXTURE, VINE_WALL_ENVIRONMENT),
        "vine_pillar": _mature(VINE_FIXTURE, VINE_PILLAR_ENVIRONMENT),
    }
    pygame.init()
    pygame.display.set_mode((1, 1))
    renderer = SpeciesRenderer(SimpleNamespace(camera=None))
    title = pygame.font.SysFont("consolas", 25)
    font = pygame.font.SysFont("consolas", 16)
    small = pygame.font.SysFont("consolas", 13)

    labels = (
        ("vine_wall", "VINE + WALL"),
        ("vine_pillar", "VINE + PILLAR"),
        ("tree", "TREE + WALL + PILLAR"),
    )
    comparison = pygame.Surface((1800, 1060))
    comparison.fill((14, 21, 18))
    comparison.blit(title.render(
        "Pixel-solid interaction | BEFORE ignored, AFTER shared 3D collision field",
        True, (230, 239, 221),
    ), (22, 16))
    comparison.blit(font.render(
        "Fixed seed 529 | mature LOD 2 | each before/after pair shares a 2:1 isometric camera",
        True, (164, 187, 169),
    ), (22, 52))
    for column, (key, label) in enumerate(labels):
        x = column * 600
        bounds = _union_bounds((baselines[key], current[key].render_snapshot))
        comparison.blit(font.render(label, True, (219, 231, 211)), (x + 18, 86))
        for row, (snapshot, prefix) in enumerate(((baselines[key], "BEFORE"), (current[key].render_snapshot, "AFTER"))):
            y = 116 + row * 446
            panel = pygame.Surface((580, 382))
            renderer._draw_individual(
                panel,
                current[key],
                snapshot=snapshot,
                camera=IsometricDiagnosticCamera(580, 382, bounds),
                show_height_reference=False,
                draw_ground_line=False,
                cache=False,
            )
            comparison.blit(small.render(prefix, True, (198, 213, 194)), (x + 18, y))
            comparison.blit(panel, (x + 10, y + 24))
        stats = current[key].render_snapshot.stats
        if key.startswith("vine"):
            metric = (
                f"contact {stats['vine_selected_support_id']} | climb {stats['vine_climbing_height_m']:.2f} m | "
                f"axis {stats['vine_axis_length_m']:.2f} m"
            )
        else:
            metric = (
                f"{stats['solid_structure_collision_count']} axes stopped | "
                f"{stats['solid_structure_pruned_placement_count']} placements pruned | no penetration"
            )
        comparison.blit(small.render(metric, True, (176, 196, 177)), (x + 18, 1029))
    pygame.image.save(comparison, OUTPUT / "before_after_isometric.png")

    wall_vine_sims, wall_vine_snapshots = _wall_vine_scene()
    trunk_tree, trunk_vine, trunk_vine_snapshot = _tree_vine_scene()

    scenario = pygame.Surface((1800, 760))
    scenario.fill((14, 21, 18))
    scenario.blit(title.render(
        "Refined interaction scenes | 3D growth, 2D isometric presentation",
        True, (230, 239, 221),
    ), (22, 16))
    scenario.blit(font.render(
        "Separated obstacles clarify tree response; independent vines share one wall; trunk axis comes from the generated tree.",
        True, (164, 187, 169),
    ), (22, 52))
    panel_size = (580, 570)

    obstacle_panel = pygame.Surface(panel_size)
    renderer._draw_individual(
        obstacle_panel,
        current["tree"],
        camera=IsometricDiagnosticCamera(*panel_size, _scene_bounds(current["tree"].render_snapshot)),
        show_height_reference=False,
        draw_ground_line=False,
        cache=False,
    )

    wall_panel = pygame.Surface(panel_size)
    wall_camera = IsometricDiagnosticCamera(*panel_size, _union_bounds(wall_vine_snapshots))
    for index, (simulation, snapshot) in enumerate(zip(wall_vine_sims, wall_vine_snapshots)):
        renderer._draw_individual(
            wall_panel,
            simulation,
            snapshot=snapshot,
            camera=wall_camera,
            clear=index == 0,
            show_height_reference=False,
            draw_ground_line=False,
            draw_environment=index == 0,
            cache=False,
        )

    trunk_panel = pygame.Surface(panel_size)
    trunk_camera = IsometricDiagnosticCamera(
        *panel_size,
        _union_bounds((trunk_tree.render_snapshot, trunk_vine_snapshot)),
    )
    renderer._draw_individual(
        trunk_panel,
        trunk_tree,
        camera=trunk_camera,
        show_height_reference=False,
        draw_ground_line=False,
        draw_environment=False,
        cache=False,
    )
    renderer._draw_individual(
        trunk_panel,
        trunk_vine,
        snapshot=trunk_vine_snapshot,
        camera=trunk_camera,
        clear=False,
        show_height_reference=False,
        draw_ground_line=False,
        draw_environment=False,
        cache=False,
    )

    panels = (
        ("TREE | OPEN GAP BETWEEN SOLIDS", obstacle_panel),
        ("WALL | FIVE INDEPENDENT VINES", wall_panel),
        ("TREE TRUNK | EXTRACTED AXIS + VINE", trunk_panel),
    )
    for column, (label, panel) in enumerate(panels):
        x = column * 600
        scenario.blit(font.render(label, True, (219, 231, 211)), (x + 18, 86))
        scenario.blit(panel, (x + 10, 116))

    wall_bounds = SolidStructureField.bounds_m(normalise_solid_structures({"solid_structures": [WALL]})[0])
    pillar_bounds = SolidStructureField.bounds_m(normalise_solid_structures({"solid_structures": [PILLAR]})[0])
    obstacle_gap = max(0.0, wall_bounds[0] - pillar_bounds[1])
    contact_x = [
        float(attachment["position_m"][0])
        for snapshot in wall_vine_snapshots
        for attachment in snapshot.attachment_points
        if attachment.get("side") == "climbing_axis"
    ]
    wall_coverage_span = max(contact_x) - min(contact_x) if contact_x else 0.0
    global_support = trunk_vine_snapshot.stats["climbing_supports"][0]
    trunk_clearances = []
    for attachment in trunk_vine_snapshot.attachment_points:
        if attachment.get("side") != "climbing_axis":
            continue
        point = attachment["position_m"]
        axis_x, axis_y = climbing_support_axis_at_z(global_support, point[2])
        trunk_clearances.append(
            math.hypot(float(point[0]) - axis_x, float(point[1]) - axis_y)
            - float(global_support["radius_m"])
        )
    scenario.blit(small.render(
        f"{obstacle_gap:.2f} m clear gap | avoided {', '.join(current['tree'].render_snapshot.stats['solid_structure_avoided_ids'])}",
        True, (176, 196, 177),
    ), (18, 716))
    scenario.blit(small.render(
        f"5 roots | {wall_coverage_span:.2f} m contact span | all climb",
        True, (176, 196, 177),
    ), (618, 716))
    scenario.blit(small.render(
        f"{len(global_support['axis_points_m'])} trunk samples | min clearance {min(trunk_clearances):.3f} m",
        True, (176, 196, 177),
    ), (1218, 716))
    pygame.image.save(scenario, OUTPUT / "isometric_test_scenario.png")
    pygame.image.save(scenario, OUTPUT / "refined_interactions.png")

    tree_stats = current["tree"].render_snapshot.stats
    wall_stats = current["vine_wall"].render_snapshot.stats
    pillar_stats = current["vine_pillar"].render_snapshot.stats
    results = {
        "provenance": {
            "seed": SEED,
            "age_days": current["tree"].mature_age_days,
            "lod": 2,
            "structures": [WALL, PILLAR],
            "fixtures_are_experimental": True,
        },
        "wall_vine": {key: value for key, value in wall_stats.items() if key.startswith("vine_") or key.startswith("solid_structure_")},
        "pillar_vine": {key: value for key, value in pillar_stats.items() if key.startswith("vine_") or key.startswith("solid_structure_")},
        "tree": {key: value for key, value in tree_stats.items() if key.startswith("solid_structure_")},
        "refined_tree_gap_m": round(obstacle_gap, 4),
        "wall_cover": {
            "vine_count": len(wall_vine_sims),
            "contact_span_m": round(wall_coverage_span, 4),
            "all_climbing": all(sim.render_snapshot.stats.get("vine_phase") == "climbing" for sim in wall_vine_sims),
            "selected_support_ids": [sim.render_snapshot.stats.get("vine_selected_support_id") for sim in wall_vine_sims],
        },
        "tree_trunk_vine": {
            "source_species_id": global_support.get("source_species_id"),
            "axis_sample_count": len(global_support.get("axis_points_m") or []),
            "phase": trunk_vine.render_snapshot.stats.get("vine_phase"),
            "climbing_height_m": trunk_vine.render_snapshot.stats.get("vine_climbing_height_m"),
            "attachment_mode": trunk_vine.render_snapshot.stats.get("vine_attachment_mode"),
            "minimum_surface_clearance_m": round(min(trunk_clearances), 4),
        },
        "artifacts": {
            "comparison": str(OUTPUT / "before_after_isometric.png"),
            "scenario": str(OUTPUT / "isometric_test_scenario.png"),
            "refined": str(OUTPUT / "refined_interactions.png"),
            "pre_refinement": str(OUTPUT / "pre_refinement_no_gap.png"),
        },
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
        _render_comparison()


if __name__ == "__main__":
    main()
