"""Render a deterministic Earth map preview through the production map renderer."""

import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pygame

from engine.camera import Camera
from simulations.map.map_renderer import MapRenderer
from simulations.map.map_simulation import MapSimulation
from world.simulation_context import SimulationContext
from world.world_model import WorldModel


def main():
    pygame.init()
    width, height = 1280, 720
    pygame.display.set_mode((1, 1))
    screen = pygame.Surface((width, height))
    screen.fill((10, 15, 25))
    camera = Camera(width, height)
    camera.zoom = 3.25
    view = SimpleNamespace(
        width=width,
        height=height,
        camera=camera,
        default_font=pygame.font.Font(None, 16),
    )
    world = WorldModel()
    simulation = MapSimulation(SimulationContext(2026, "planet_earth", world))
    simulation.map_projection_focus_x = 24.9 / 360.0
    simulation.map_projection_focus_y = -2.9 / 180.0
    renderer = MapRenderer(view)
    renderer.draw(screen, simulation)
    output_dir = Path(__file__).resolve().parents[1] / "artifacts"
    output_dir.mkdir(parents=True, exist_ok=True)
    map_output = output_dir / "earth_reference_preview.png"
    pygame.image.save(screen, map_output)
    screen.fill((10, 15, 25))
    simulation.set_active_layer_kind(simulation.HYDROLOGY_LAYER_KIND)
    renderer.draw(screen, simulation)
    started = time.perf_counter()
    for _index in range(3):
        renderer.draw(screen, simulation)
    elapsed_ms = (time.perf_counter() - started) * 1000.0 / 3.0
    hydrology_layer = next(layer for layer in simulation.get_layers() if layer.get("shape") == "hydrology_climate")
    cycle = hydrology_layer["water_cycle_model"]
    source = renderer._hydrology_surface_for_layer(hydrology_layer, cycle)
    started = time.perf_counter()
    for _index in range(10):
        renderer._projected_spherical_surface(source, hydrology_layer)
    projection_ms = (time.perf_counter() - started) * 100.0
    started = time.perf_counter()
    for _index in range(3):
        renderer._draw_hydrology_layer(screen, hydrology_layer, camera)
    direct_hydrology_ms = (time.perf_counter() - started) * 1000.0 / 3.0
    hydrology_output = output_dir / "earth_hydrology_preview.png"
    pygame.image.save(screen, hydrology_output)
    print(map_output)
    print(hydrology_output)
    print(f"Warm hydrology render: {elapsed_ms:.2f} ms/frame")
    print(f"Warm raster projection: {projection_ms:.2f} ms/call")
    print(f"Warm hydrology layer only: {direct_hydrology_ms:.2f} ms/frame")


if __name__ == "__main__":
    main()
