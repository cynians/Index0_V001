"""Render inspected coastal feature plates from a generated planet snapshot."""

import argparse
import copy
import json
import math
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from simulations.world_gen.coastal_geomorphology import (
    ASSEMBLAGE_COLORS,
    derive_coastal_geomorphology_model,
)
from simulations.world_gen.headless_runner import (
    HeadlessWorldGenConfig,
    HeadlessWorldGenRunner,
)


STAR = {"mass_kg": 1.98847e30}
LUNAR_ANALOGUE = {
    "id": "lunar_analogue",
    "mass_kg": 7.342e22,
    "semi_major_axis_m": 384_400_000.0,
}


def _derive(planet, satellites=None):
    context = copy.deepcopy(planet)
    if satellites is not None:
        context["satellites"] = copy.deepcopy(satellites)
    return derive_coastal_geomorphology_model(
        planet=context,
        heightmap=context.get("heightmap_model"),
        water_cycle=context.get("water_cycle_model"),
        tectonic_model=context.get("tectonic_model"),
        surface_evolution=context.get("surface_evolution_model"),
        star=STAR,
    )


def _font(size, bold=False):
    return pygame.font.SysFont("consolas", int(size), bold=bold)


def _text(surface, value, position, size=18, color=(224, 230, 238), bold=False):
    surface.blit(_font(size, bold=bold).render(str(value), True, color), position)


def _segment_runs(segment, width, height):
    runs = []
    run = []
    for point in ((segment.get("geometry") or {}).get("points") or []):
        candidate = (
            int(round(float(point[0]) * (width - 1))),
            int(round(float(point[1]) * (height - 1))),
        )
        if run and abs(candidate[0] - run[-1][0]) > width * 0.5:
            if len(run) >= 2:
                runs.append(run)
            run = []
        run.append(candidate)
    if len(run) >= 2:
        runs.append(run)
    return runs


def _wrapped_crop(surface, center_uv, crop_size):
    width, height = surface.get_size()
    crop_w, crop_h = crop_size
    repeated = pygame.Surface((width * 3, height))
    repeated.blit(surface, (0, 0))
    repeated.blit(surface, (width, 0))
    repeated.blit(surface, (width * 2, 0))
    center_x = width + float(center_uv[0]) * width
    center_y = float(center_uv[1]) * height
    left = int(round(center_x - crop_w * 0.5))
    top = max(0, min(height - crop_h, int(round(center_y - crop_h * 0.5))))
    return repeated.subsurface(pygame.Rect(left, top, crop_w, crop_h)).copy()


def _render_closeups(runner, planet, model, output_path):
    map_size = (1800, 900)
    source_planet = copy.deepcopy(planet)
    source_planet["coastal_geomorphology_model"] = model
    base = runner._render_coastal_layer(source_planet, map_size, show_legend=False)
    preferred = [
        "deltaic",
        "estuarine_drowned_valley",
        "headland_bay",
        "emergent_marine_terrace",
        "carbonate_karst",
        "volcanic",
        "rocky_cliff",
    ]
    selected = []
    for assemblage in preferred:
        matches = [
            segment
            for segment in model.get("segments") or []
            if segment.get("primary_assemblage") == assemblage
        ]
        if matches:
            selected.append(max(matches, key=lambda item: float(item.get("length_km", 0.0) or 0.0)))
        if len(selected) == 6:
            break

    panel_w, panel_h = 790, 380
    gap, margin, title_h = 20, 28, 64
    rows = (len(selected) + 1) // 2
    sheet = pygame.Surface((margin * 2 + panel_w * 2 + gap, title_h + margin + rows * (panel_h + gap)))
    sheet.fill((13, 18, 27))
    _text(sheet, "GENERATED COASTAL ASSEMBLAGES — SELECTED SEGMENTS", (margin, 18), 25, bold=True)

    for index, segment in enumerate(selected):
        col, row = index % 2, index // 2
        x = margin + col * (panel_w + gap)
        y = title_h + row * (panel_h + gap)
        panel = pygame.Surface((panel_w, panel_h))
        panel.fill((8, 13, 20))
        centroid = (segment.get("measurements") or {}).get("centroid_uv") or [0.5, 0.5]
        crop = _wrapped_crop(base, centroid, (340, 185))
        crop = pygame.transform.smoothscale(crop, (panel_w - 20, 248))
        panel.blit(crop, (10, 10))
        color = tuple(segment.get("display_color") or ASSEMBLAGE_COLORS.get(segment.get("primary_assemblage"), [220, 196, 116]))
        pygame.draw.circle(panel, (8, 12, 18), (panel_w // 2, 134), 13, 4)
        pygame.draw.circle(panel, color, (panel_w // 2, 134), 10, 3)
        label = str(segment.get("primary_assemblage") or "coast").replace("_", " ").upper()
        _text(panel, label, (14, 270), 22, color, bold=True)
        measurements = segment.get("measurements") or {}
        wave = segment.get("wave_climate") or {}
        tide = segment.get("tidal_regime") or {}
        line_1 = (
            f"substrate {segment.get('substrate')}  |  {segment.get('tectonic_setting')}  |  "
            f"{float(segment.get('length_km', 0.0)):.1f} km"
        )
        line_2 = (
            f"wave {wave.get('exposure_class')} ({float(wave.get('exposure_index', 0.0)):.2f})  |  "
            f"tide {float(tide.get('estimated_range_m', 0.0)):.2f} m  |  "
            f"river {float(segment.get('river_influence', 0.0)):.2f}"
        )
        line_3 = (
            f"trajectory {segment.get('shoreline_trajectory')}  |  "
            f"relief {float(measurements.get('inland_relief_m', 0.0)):.0f} m  |  "
            f"confidence {float(segment.get('confidence', 0.0)):.2f}"
        )
        _text(panel, line_1, (14, 304), 15)
        _text(panel, line_2, (14, 329), 15)
        _text(panel, line_3, (14, 354), 15)
        sheet.blit(panel, (x, y))
        pygame.draw.rect(sheet, (76, 91, 112), pygame.Rect(x, y, panel_w, panel_h), 1)
    pygame.image.save(sheet, str(output_path))


def _metric_color(value, low, high, start, end):
    t = max(0.0, min(1.0, (float(value) - low) / max(1e-9, high - low)))
    return tuple(int(start[i] * (1.0 - t) + end[i] * t) for i in range(3))


def _render_metric_map(runner, planet, model, metric, size):
    width, height = size
    surface = runner._render_height_layer(planet, size, include_materials=False)
    shade = pygame.Surface(size, pygame.SRCALPHA)
    shade.fill((5, 12, 22, 110))
    surface.blit(shade, (0, 0))
    segments = model.get("segments") or []
    for segment in segments:
        wave = segment.get("wave_climate") or {}
        tide = segment.get("tidal_regime") or {}
        if metric == "wave":
            value = float(wave.get("exposure_index", 0.0) or 0.0)
            color = _metric_color(value, 0.0, 1.0, (72, 174, 152), (242, 100, 158))
        elif metric == "tide":
            value = float(tide.get("estimated_range_m", 0.0) or 0.0)
            color = _metric_color(value, 0.5, 2.0, (72, 128, 178), (118, 246, 218))
        else:
            value = float(wave.get("transport_capacity_index", 0.0) or 0.0)
            color = _metric_color(value, 0.0, 1.0, (154, 102, 64), (255, 204, 74))
        for run in _segment_runs(segment, width, height):
            pygame.draw.lines(surface, (5, 8, 12), False, run, 6)
            pygame.draw.lines(surface, color, False, run, 4)
        if metric == "transport":
            measurements = segment.get("measurements") or {}
            center_uv = measurements.get("centroid_uv") or [0.5, 0.5]
            center = (int(center_uv[0] * width), int(center_uv[1] * height))
            orientation = float(measurements.get("orientation_rad", 0.0) or 0.0)
            direction = -1.0 if wave.get("longshore_transport_direction") == "chain_reverse" else 1.0
            length = 7.0 + value * 8.0
            end = (
                int(round(center[0] + direction * length * math.cos(orientation))),
                int(round(center[1] + direction * length * math.sin(orientation))),
            )
            pygame.draw.line(surface, (255, 220, 118), center, end, 2)
            pygame.draw.circle(surface, (255, 220, 118), end, 2)
    return surface


def _render_forcing_diagnostics(runner, planet, solar_model, lunar_model, output_path):
    tile_size = (590, 320)
    margin, gap, title_h, footer_h = 24, 18, 64, 95
    sheet = pygame.Surface((margin * 2 + tile_size[0] * 3 + gap * 2, title_h + tile_size[1] + footer_h + margin))
    sheet.fill((13, 18, 27))
    _text(sheet, "COASTAL FORCING DIAGNOSTICS", (margin, 18), 25, bold=True)
    definitions = [
        ("WAVE EXPOSURE", solar_model, "wave", "sheltered  →  exposed"),
        ("LUNAR-ANALOGUE TIDAL RANGE", lunar_model, "tide", "0.5 m  →  2.0 m"),
        ("LONGSHORE TRANSPORT CAPACITY", solar_model, "transport", "low  →  high; ticks show direction"),
    ]
    for index, (label, model, metric, scale) in enumerate(definitions):
        x = margin + index * (tile_size[0] + gap)
        y = title_h
        tile = _render_metric_map(runner, planet, model, metric, tile_size)
        sheet.blit(tile, (x, y))
        pygame.draw.rect(sheet, (82, 98, 120), pygame.Rect(x, y, *tile_size), 1)
        _text(sheet, label, (x + 8, y + tile_size[1] + 12), 18, bold=True)
        _text(sheet, scale, (x + 8, y + tile_size[1] + 39), 15, color=(188, 200, 214))
        if metric == "tide":
            solar_ranges = [float(s["tidal_regime"]["estimated_range_m"]) for s in solar_model.get("segments") or []]
            lunar_ranges = [float(s["tidal_regime"]["estimated_range_m"]) for s in lunar_model.get("segments") or []]
            comparison = (
                f"solar-only {min(solar_ranges):.2f}–{max(solar_ranges):.2f} m; "
                f"with moon {min(lunar_ranges):.2f}–{max(lunar_ranges):.2f} m"
            )
            _text(sheet, comparison, (x + 8, y + tile_size[1] + 64), 13, color=(154, 232, 220))
    pygame.image.save(sheet, str(output_path))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("planet_json", type=Path)
    parser.add_argument("output_directory", type=Path)
    args = parser.parse_args()
    args.output_directory.mkdir(parents=True, exist_ok=True)

    planet = json.loads(args.planet_json.read_text(encoding="utf-8"))
    solar_model = _derive(planet, satellites=[])
    lunar_model = _derive(planet, satellites=[LUNAR_ANALOGUE])
    planet["coastal_geomorphology_model"] = solar_model

    runner = HeadlessWorldGenRunner(args.output_directory)
    runner._initialize_rendering(HeadlessWorldGenConfig(screen_size=(1800, 900)))

    overview_path = args.output_directory / "01_coastal_world_overview.png"
    overview = runner._render_coastal_layer(planet, (1800, 900))
    pygame.image.save(overview, str(overview_path))

    closeups_path = args.output_directory / "02_coastal_assemblage_closeups.png"
    _render_closeups(runner, planet, solar_model, closeups_path)

    diagnostics_path = args.output_directory / "03_coastal_forcing_diagnostics.png"
    _render_forcing_diagnostics(runner, planet, solar_model, lunar_model, diagnostics_path)

    result = {
        "images": [str(overview_path.resolve()), str(closeups_path.resolve()), str(diagnostics_path.resolve())],
        "coastal_summary": solar_model.get("summary"),
        "lunar_tidal_distribution": lunar_model.get("summary", {}).get("tidal_class_distribution"),
    }
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()
