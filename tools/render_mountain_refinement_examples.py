"""Regenerate and render a mountain-following branch from a saved planet."""

from __future__ import annotations

import argparse
import json
import os
import sys
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pygame

from simulations.world_gen.headless_runner import HeadlessWorldGenConfig, HeadlessWorldGenRunner
from simulations.world_gen.regional_refinement import generate_refined_region
from world.world_model import WorldModel


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("planet_json")
    parser.add_argument("output")
    parser.add_argument("--depth", type=int, default=3)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=640)
    parser.add_argument(
        "--height-only",
        action="store_true",
        help="Run only the production terrain refinement stage, without climate or materials.",
    )
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    source = Path(args.planet_json).resolve()
    output = Path(args.output).resolve()
    entries = output / "repository" / "entries" / "locations"
    entries.mkdir(parents=True, exist_ok=True)
    (output / "repository" / "assets" / "maps" / "material_heatmaps").mkdir(
        parents=True,
        exist_ok=True,
    )
    if source.suffix.lower() == ".i0wg":
        with zipfile.ZipFile(source) as bundle:
            planet = json.loads(bundle.read("planet.json").decode("utf-8"))
    else:
        planet = json.loads(source.read_text(encoding="utf-8"))
    if isinstance(planet, list):
        planet = next(
            (item for item in planet if isinstance(item, dict)),
            None,
        )
    if not isinstance(planet, dict):
        raise ValueError("The source does not contain a planet record.")
    (entries / "source_planet.json").write_text(
        json.dumps([planet], indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    world = WorldModel(entries_directory=output / "repository" / "entries", use_ontology=False)
    parent = world.get_entity(planet["id"])
    runner = HeadlessWorldGenRunner(output)
    runner.layers_root.mkdir(parents=True, exist_ok=True)
    runner.images_root.mkdir(parents=True, exist_ok=True)
    config = HeadlessWorldGenConfig(
        name=str(planet.get("name") or "Mountain branch"),
        layer_size=(max(640, args.width), max(320, args.height)),
        render_outputs=True,
        regional_target_mode="mountain",
    )
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    runner._initialize_rendering(config)
    manifest = {"source_planet_id": planet["id"], "levels": []}
    try:
        source_bounds = parent.get("bounds") or {}
        source_width = float(source_bounds["max_x"]) - float(source_bounds["min_x"])
        source_height = float(source_bounds["max_y"]) - float(source_bounds["min_y"])
        source_u, source_v = runner._mountain_center_fraction(parent)
        target_x = float(source_bounds["min_x"]) + source_width * source_u
        target_y = float(source_bounds["min_y"]) + source_height * source_v
        manifest["mountain_target"] = {
            "source_fraction": [round(source_u, 6), round(source_v, 6)],
            "map_position": [round(target_x, 6), round(target_y, 6)],
        }
        for index in range(max(1, int(args.depth))):
            bounds = parent.get("bounds") or {}
            width = float(bounds["max_x"]) - float(bounds["min_x"])
            height = float(bounds["max_y"]) - float(bounds["min_y"])
            u = (target_x - float(bounds["min_x"])) / max(1e-9, width)
            v = (target_y - float(bounds["min_y"])) / max(1e-9, height)
            u, v = max(0.2, min(0.8, u)), max(0.2, min(0.8, v))
            cx = float(bounds["min_x"]) + width * u
            cy = float(bounds["min_y"]) + height * v
            child_bounds = {
                "min_x": cx - width * 0.20,
                "max_x": cx + width * 0.20,
                "min_y": cy - height * 0.20,
                "max_y": cy + height * 0.20,
            }
            parent = generate_refined_region(
                world,
                parent,
                child_bounds,
                seed_suffix="mountain-realism-example",
                terrain_only=bool(args.height_only),
            )
            prefix = f"mountain_lod_{parent.get('map_detail_level', index + 1)}"
            height_layer = runner._render_height_layer(parent, config.layer_size, include_materials=False)
            height_path = runner._save_layer("Height", height_layer, prefix)["path"]
            true_color_path = None
            if not args.height_only:
                # Use the same production renderer and per-material raster
                # components as the interactive True Color layer.  This is a
                # diagnostic export of generated world truth, not a concept
                # illustration or a separately authored texture.
                true_color_layer = runner._render_height_layer(
                    parent,
                    config.layer_size,
                    include_materials=True,
                )
                true_color_path = runner._save_layer(
                    "True Color",
                    true_color_layer,
                    prefix,
                )["path"]
            geomorphology = parent.get("surface_geomorphology_model") or {}
            manifest["levels"].append({
                "level": parent.get("map_detail_level"),
                "region_id": parent.get("id"),
                "center_fraction": [round(u, 6), round(v, 6)],
                "physical_width_m": (parent.get("heightmap_model") or {}).get("region_width_m"),
                "physical_height_m": (parent.get("heightmap_model") or {}).get("region_height_m"),
                "elevation_range_m": [
                    (parent.get("heightmap_model") or {}).get("min_elevation_m"),
                    (parent.get("heightmap_model") or {}).get("max_elevation_m"),
                ],
                "true_color": (
                    str(Path(true_color_path).relative_to(output))
                    if true_color_path
                    else None
                ),
                "height": str(Path(height_path).relative_to(output)),
                "geomorphology_summary": geomorphology.get("summary") or {},
                "structural_fabric": geomorphology.get("structural_fabric") or {},
            })
    finally:
        pygame.quit()
    manifest_path = output / "mountain_examples.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"manifest": str(manifest_path), **manifest}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
