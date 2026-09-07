"""Render fixed-seed deciduous-tree architecture comparisons at shared scales."""

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import pygame

from simulations.species.species_renderer import (
    DiagnosticCamera,
    SpeciesRenderer,
    TopDownDiagnosticCamera,
    diagnostic_cell_bounds,
    top_down_diagnostic_bounds,
)
from simulations.species.species_simulation import SpeciesSimulation
from world.persistent_ontology_store import PersistentOntologyStore


SPECIES_IDS = (
    "spec_betula_pendula",
    "spec_quercus_robur",
    "spec_aesculus_hippocastanum",
)


def _union(bounds):
    return (
        min(value[0] for value in bounds),
        max(value[1] for value in bounds),
        min(value[2] for value in bounds),
        max(value[3] for value in bounds),
    )


def _metrics(simulation):
    snapshot = simulation.render_snapshot
    above = [item for item in snapshot.placements if item[0] not in {"root", "root_section", "root_support"}]
    xs = [float(item[2]) for item in above] or [0.0]
    ys = [float(item[3]) for item in above] or [0.0]
    zs = [float(item[4]) for item in above] or [0.0]
    stats = simulation.get_growth_summary()
    growth = simulation.blueprint.growth
    return {
        "species_id": simulation.species_id,
        "display_name": simulation.blueprint.display_name,
        "seed": simulation.seed,
        "age_days": round(simulation.age_days, 3),
        "height_m": round(max(zs) - min(zs), 3),
        "crown_span_x_m": round(max(xs) - min(xs), 3),
        "crown_span_y_m": round(max(ys) - min(ys), 3),
        "branch_count": int(stats.get("branch_count", 0)),
        "leaf_cluster_count": int(stats.get("leaf_cluster_count", 0)),
        "estimated_leaf_count": int(stats.get("estimated_leaf_count", 0)),
        "structural_axis_length_m": round(float(stats.get("structural_axis_length_m") or 0.0), 3),
        "architecture": {
            "axis_continuity": growth.get("axis_continuity", "runtime_default"),
            "branching_rhythm": growth.get("branching_rhythm", "runtime_default"),
            "branching_timing": growth.get("branching_timing", "runtime_default"),
            "lateral_axis_orientation": growth.get("lateral_axis_orientation", "runtime_default"),
            "apical_control": growth.get("apical_control", "runtime_default"),
        },
    }


def render(output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)
    pygame.init()
    pygame.display.set_mode((1, 1))
    rows = PersistentOntologyStore(Path("ontology/index0.owl")).load_datasets()["species"]
    by_id = {row["id"]: row for row in rows}
    simulations = [SpeciesSimulation(species_entity=by_id[species_id], seed=303) for species_id in SPECIES_IDS]
    for simulation in simulations:
        simulation.set_lod(2)
        simulation.set_age(simulation.mature_age_days)

    renderer = SpeciesRenderer(SimpleNamespace(camera=None))
    width, column_width, row_height = 1680, 560, 390
    header_height, footer_height = 112, 92
    sheet = pygame.Surface((width, header_height + row_height * 2 + footer_height))
    sheet.fill((13, 18, 17))
    title = pygame.font.SysFont("consolas", 20)
    font = pygame.font.SysFont("consolas", 14)
    small = pygame.font.SysFont("consolas", 12)
    front_bounds = _union([diagnostic_cell_bounds(sim.render_snapshot) for sim in simulations])
    top_bounds = _union([top_down_diagnostic_bounds(sim) for sim in simulations])
    metrics = [_metrics(simulation) for simulation in simulations]

    for column, (simulation, record) in enumerate(zip(simulations, metrics)):
        x = column * column_width
        sheet.blit(title.render(record["display_name"], True, (230, 238, 232)), (x + 16, 16))
        architecture = record["architecture"]
        line = f"{architecture['axis_continuity']} | {architecture['branching_rhythm']} | {architecture['branching_timing']}"
        sheet.blit(small.render(line, True, (161, 186, 170)), (x + 16, 45))
        sheet.blit(small.render(
            f"{record['height_m']:.1f} m high | {record['crown_span_x_m']:.1f} x {record['crown_span_y_m']:.1f} m footprint",
            True, (194, 208, 194)), (x + 16, 65))
        sheet.blit(small.render(
            f"branches {record['branch_count']} | clusters {record['leaf_cluster_count']} | axis {record['structural_axis_length_m']:.0f} m",
            True, (194, 208, 194)), (x + 16, 84))

        front = pygame.Surface((column_width - 12, row_height - 10))
        renderer._draw_individual(front, simulation, camera=DiagnosticCamera(front.get_width(), front.get_height(), front_bounds))
        sheet.blit(front, (x + 6, header_height))

        top = pygame.Surface((column_width - 12, row_height - 10))
        top.fill((18, 23, 20))
        camera = TopDownDiagnosticCamera(top.get_width(), top.get_height(), top_bounds)
        visible = {
            index for index, placement in enumerate(simulation.render_snapshot.placements)
            if placement[0] not in {"root", "root_section", "root_support"}
        }
        renderer._draw_individual(top, simulation, camera=camera, clear=False,
                                  visible_indices=visible, draw_ground_line=False)
        sheet.blit(top, (x + 6, header_height + row_height))

    sheet.blit(font.render("FRONT — shared physical scale", True, (224, 226, 192)), (18, header_height + 8))
    sheet.blit(font.render("TOP — shared physical scale", True, (224, 226, 192)), (18, header_height + row_height + 8))
    sheet.blit(font.render("Fixed seed 303 | matched authored maturity | LOD 2 | intrinsic architecture only",
                           True, (164, 184, 166)), (18, header_height + row_height * 2 + 30))
    pygame.image.save(sheet, output_dir / "tree_architecture_comparison.png")
    diagnostic = pygame.Surface((1680, 1000))
    simulations[0].set_active_simulation_panel_tab("architecture")
    renderer.draw(diagnostic, simulations[0])
    pygame.image.save(diagnostic, output_dir / "tree_patterns_diagnostic.png")
    (output_dir / "tree_architecture_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    pygame.quit()
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("artifacts/tree_architecture_v001"))
    args = parser.parse_args()
    render(args.output)
