"""Render climate and hydrology diagnostics from an existing generated region.

This is inspection-only. It derives the child water cycle from the saved
regional heightfield and its saved parent climate; it never regenerates the
planet or persists a replacement model.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import numpy as np
import pygame

from simulations.world_gen.water_cycle import (
    KOPPEN_CLASSES,
    derive_water_cycle_model,
)


def _array(rows):
    values = np.asarray(rows or [], dtype=np.float32)
    return values if values.ndim == 2 else np.zeros((2, 2), dtype=np.float32)


def _normalise(values, *, logarithmic=False):
    values = np.asarray(values, dtype=np.float32)
    if logarithmic:
        values = np.log1p(np.maximum(0.0, values))
    low = float(np.nanpercentile(values, 2.0))
    high = float(np.nanpercentile(values, 98.0))
    if high <= low + 1e-6:
        return np.zeros_like(values)
    return np.clip((values - low) / (high - low), 0.0, 1.0)


def _gradient(values, palette):
    values = np.clip(values, 0.0, 1.0)
    palette = np.asarray(palette, dtype=np.float32)
    positions = np.linspace(0.0, 1.0, len(palette), dtype=np.float32)
    result = np.zeros((*values.shape, 3), dtype=np.float32)
    for index in range(len(palette) - 1):
        weight = np.clip(
            (values - positions[index])
            / max(1e-6, positions[index + 1] - positions[index]),
            0.0,
            1.0,
        )[..., None]
        segment = palette[index] * (1.0 - weight) + palette[index + 1] * weight
        mask = (values >= positions[index]) & (values <= positions[index + 1])
        result[mask] = segment[mask]
    result[values <= positions[0]] = palette[0]
    result[values >= positions[-1]] = palette[-1]
    return result.astype(np.uint8)


def _surface_from_rgb(rgb, size):
    surface = pygame.surfarray.make_surface(np.transpose(rgb, (1, 0, 2)))
    if surface.get_size() != size:
        surface = pygame.transform.smoothscale(surface, size)
    return surface


def _koppen_surface(rows, size):
    values = rows or []
    height = len(values)
    width = min((len(row) for row in values if isinstance(row, list)), default=0)
    if width < 1 or height < 1:
        return pygame.Surface(size)
    rgb = np.zeros((height, width, 3), dtype=np.uint8)
    for y, row in enumerate(values):
        for x, code in enumerate(row[:width]):
            rgb[y, x] = KOPPEN_CLASSES.get(str(code), {"color": (80, 80, 80)})[
                "color"
            ]
    return _surface_from_rgb(rgb, size)


def _draw_channels(surface, channels, color, width=1):
    canvas_w, canvas_h = surface.get_size()
    for river in channels or []:
        points = []
        for point in river.get("display_points") or river.get("points") or []:
            if not isinstance(point, dict):
                continue
            points.append((
                int(round(max(0.0, min(1.0, float(point.get("x", 0.0)))) * (canvas_w - 1))),
                int(round(max(0.0, min(1.0, float(point.get("y", 0.0)))) * (canvas_h - 1))),
            ))
        if len(points) >= 2:
            pygame.draw.lines(surface, color, False, points, width)


def render(region_path, parent_path, output_path):
    region = json.loads(Path(region_path).read_text(encoding="utf-8"))
    parent = json.loads(Path(parent_path).read_text(encoding="utf-8"))
    heightmap = region.get("heightmap_model") or {}
    terrain = region.get("terrain_seed_model") or parent.get("terrain_seed_model") or {}
    water = derive_water_cycle_model(
        terrain,
        heightmap,
        atmosphere=parent.get("atmosphere_model"),
        seed=parent.get("world_gen_seed"),
        planet_id=region.get("id", "diagnostic-region"),
        parent_climate_model=parent.get("water_cycle_model"),
    )
    climate = water.get("climate_grid") or {}
    size = (512, 512)
    precipitation = _array(climate.get("annual_precipitation_rows_mm"))
    temperature = _array(climate.get("temperature_rows_k"))
    runoff = _array(climate.get("annual_runoff_rows_mm"))
    humidity = _array(climate.get("relative_humidity_rows"))
    panels = [
        (
            "Annual precipitation (mm)",
            _surface_from_rgb(
                _gradient(
                    _normalise(precipitation),
                    ((24, 30, 82), (33, 104, 164), (77, 169, 119), (231, 220, 102)),
                ),
                size,
            ),
        ),
        (
            "Temperature (K)",
            _surface_from_rgb(
                _gradient(
                    _normalise(temperature),
                    ((42, 72, 150), (86, 174, 205), (239, 219, 112), (190, 64, 48)),
                ),
                size,
            ),
        ),
        (
            "Runoff (mm, log scale)",
            _surface_from_rgb(
                _gradient(
                    _normalise(runoff, logarithmic=True),
                    ((18, 22, 38), (36, 95, 139), (58, 173, 178), (238, 226, 128)),
                ),
                size,
            ),
        ),
        (
            "Relative humidity",
            _surface_from_rgb(
                _gradient(
                    _normalise(humidity),
                    ((62, 45, 48), (125, 87, 73), (195, 157, 91), (226, 232, 188)),
                ),
                size,
            ),
        ),
        (
            "Köppen-Geiger zones",
            _koppen_surface(climate.get("koppen_rows"), size),
        ),
        (
            "Routed channels",
            _surface_from_rgb(
                _gradient(
                    _normalise(runoff, logarithmic=True),
                    ((31, 31, 35), (83, 67, 56), (139, 113, 74), (205, 174, 116)),
                ),
                size,
            ),
        ),
    ]
    drainage = water.get("drainage_network_model") or {}
    _draw_channels(panels[-1][1], water.get("rivers"), (52, 177, 255), width=3)
    _draw_channels(panels[-1][1], drainage.get("ephemeral_channels"), (235, 206, 103), width=1)

    pygame.init()
    label_font = pygame.font.Font(None, 26)
    sheet = pygame.Surface((1024, 1560))
    sheet.fill((18, 22, 32))
    for index, (label, panel) in enumerate(panels):
        x = (index % 2) * 512
        y = (index // 2) * 520
        sheet.blit(panel, (x, y))
        sheet.blit(label_font.render(label, True, (240, 244, 248)), (x + 12, y + 12))
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pygame.image.save(sheet, str(output_path))

    summary = water.get("runoff_summary") or {}
    analysis = {
        "generation_performed": False,
        "region_id": region.get("id"),
        "solver_seed_source": (climate.get("parent_climate_inheritance") or {}).get("solver_seed_source"),
        "rivers": len(water.get("rivers") or []),
        "ephemeral_channels": len(drainage.get("ephemeral_channels") or []),
        "lakes": len(water.get("lakes") or []),
        "precipitation": {
            "min_mm": float(np.min(precipitation)),
            "mean_mm": float(np.mean(precipitation)),
            "max_mm": float(np.max(precipitation)),
            "std_mm": float(np.std(precipitation)),
        },
        "runoff": {
            "min_mm": float(np.min(runoff)),
            "mean_mm": float(np.mean(runoff)),
            "max_mm": float(np.max(runoff)),
            "std_mm": float(np.std(runoff)),
        },
        "runoff_summary": summary,
        "output": str(output_path),
    }
    output_path.with_name("climate_hydrology_analysis.json").write_text(
        json.dumps(analysis, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(analysis, indent=2, sort_keys=True))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("region")
    parser.add_argument("parent")
    parser.add_argument("output")
    args = parser.parse_args(argv)
    render(args.region, args.parent, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
