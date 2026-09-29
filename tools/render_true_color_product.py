"""Render the physical true-colour product from an existing generated planet."""

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from simulations.world_gen.material_heatmaps import load_raster_bundle_surface
from simulations.world_gen.surface_exposure import derive_surface_exposure_model
from simulations.world_gen.true_color import (
    derive_true_color_model,
    render_true_color_surface,
)


def _resolve_bundle(path_value, repository_root):
    path = Path(str(path_value or ""))
    if path.is_absolute():
        return path
    return repository_root / path


def render_product(planet_path, output_path, width=1024):
    planet_path = Path(planet_path).resolve()
    output_path = Path(output_path).resolve()
    planet = json.loads(planet_path.read_text(encoding="utf-8"))
    repository_root = planet_path.parent / "repository"
    heightmap = planet.get("heightmap_model") or {}
    heatmaps = planet.get("material_heatmap_model") or {}
    exposure = derive_surface_exposure_model(
        planet,
        heightmap=heightmap,
        material_heatmap_model=heatmaps,
        water_cycle=planet.get("water_cycle_model"),
        surface_evolution=planet.get("surface_evolution_model"),
    )
    model = derive_true_color_model(
        planet,
        heightmap=heightmap,
        natural_material_model=planet.get("natural_material_model"),
        atmosphere=planet.get("atmosphere_model"),
        water_cycle=planet.get("water_cycle_model"),
        surface_evolution=planet.get("surface_evolution_model"),
        surface_exposure=exposure,
    )
    components = []
    for layer in heatmaps.get("layers") or []:
        if not isinstance(layer, dict):
            continue
        surface = load_raster_bundle_surface(
            _resolve_bundle(layer.get("bundle_path"), repository_root),
            layer.get("bundle_layer_id"),
        )
        if surface is not None:
            component = dict(layer)
            component["surface"] = surface
            components.append(component)
    pygame.init()
    source_width = max(1, int(heightmap.get("width_px", 2) or 2) - 1)
    source_height = max(1, int(heightmap.get("height_px", 2) or 2) - 1)
    target_height = max(1, int(round(width * source_height / source_width)))
    surface = render_true_color_surface(
        heightmap,
        model,
        material_components=components,
        water_cycle=planet.get("water_cycle_model"),
        surface_evolution=planet.get("surface_evolution_model"),
        surface_exposure=exposure,
        atmosphere=planet.get("atmosphere_model"),
        target_size=(width, target_height),
    )
    if surface is None:
        raise RuntimeError("Planet does not contain a renderable heightfield.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pygame.image.save(surface, str(output_path))
    return output_path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("planet")
    parser.add_argument("output")
    parser.add_argument("--width", type=int, default=1024)
    args = parser.parse_args(argv)
    output = render_product(args.planet, args.output, max(64, args.width))
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
