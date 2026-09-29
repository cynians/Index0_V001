"""Render zoomed showcases from an existing world-gen artifact.

This tool only crops already-rendered layers from an extracted .i0wg bundle.
It never calls world generation, map regeneration, or regional refinement.
"""

import argparse
import json
from pathlib import Path

import pygame


LAYER_FILES = {
    "True Color": "true_color.png",
    "Surface Materials": "surface_materials.png",
    "Climate and Rivers": "climate_and_rivers.png",
    "Coastal Geomorphology": "coastal_geomorphology.png",
    "Surface Temperature": "surface_temperature.png",
    "Annual Precipitation": "annual_precipitation.png",
}


def _load_json(root, name):
    return json.loads((root / name).read_text(encoding="utf-8"))


def _mountain_center(planet):
    heightmap = planet.get("heightmap_model") or {}
    grid = heightmap.get("sample_grid") or {}
    rows = grid.get("rows") or []
    sea_level = float(heightmap.get("sea_level_m") or 0.0)
    points = []
    for y, row in enumerate(rows):
        for x, value in enumerate(row):
            if x >= len(row) - 1 or float(value or 0.0) < sea_level:
                continue
            points.append((
                float(value or 0.0),
                x / max(1, len(row) - 2),
                y / max(1, len(rows) - 1),
            ))
    if not points:
        return 0.5, 0.5
    # Use the upper tail of resolved land elevation, not the broad mountain
    # mask centroid: the latter intentionally includes foothills and can land
    # in an adjacent basin when viewed as a close-up.
    points.sort(reverse=True)
    # Pick the summit itself so the showcase is guaranteed to include the
    # resolved high-relief signal rather than averaging several separated
    # mountain clusters into a low basin between them.
    points = points[:1]
    return (
        sum(point[1] for point in points) / len(points),
        sum(point[2] for point in points) / len(points),
    )


def _coast_center(planet):
    coastal = planet.get("coastal_geomorphology_model") or {}
    segments = coastal.get("segments") or []
    preferred = [
        segment for segment in segments
        if segment.get("coastal_system") in {
            "headland_bay",
            "estuarine_drowned_valley",
            "barrier_lagoon",
        }
    ]
    candidates = preferred or segments
    if not candidates:
        return 0.5, 0.5, "coastal feature"
    segment = max(candidates, key=lambda item: float(item.get("length_km", 0.0) or 0.0))
    measurements = segment.get("measurements") or {}
    center = measurements.get("centroid_uv") or [0.5, 0.5]
    return float(center[0]), float(center[1]), str(segment.get("coastal_system") or "coastal feature")


def _crop_wrapped(source, center_u, center_v, width_fraction=0.18, height_fraction=0.22):
    source_width, source_height = source.get_size()
    crop_width = max(160, int(source_width * width_fraction))
    crop_height = max(100, int(source_height * height_fraction))
    center_x = int((float(center_u) % 1.0) * source_width)
    center_y = int(max(0.0, min(1.0, float(center_v))) * (source_height - 1))
    top = max(0, min(source_height - crop_height, center_y - crop_height // 2))
    result = pygame.Surface((crop_width, crop_height))
    result.fill((16, 20, 28))
    left = center_x - crop_width // 2
    remaining = crop_width
    destination_x = 0
    while remaining > 0:
        source_x = left % source_width
        run = min(remaining, source_width - source_x)
        result.blit(source, (destination_x, 0), pygame.Rect(source_x, top, run, crop_height))
        destination_x += run
        remaining -= run
        left += run
    return result


def _showcase(root, output_root, name, title, center_u, center_v, labels):
    source_layers = {}
    for label in labels:
        path = root / "images" / "layers" / LAYER_FILES[label]
        # Keep the crop utility display-independent; the normal world-gen
        # renderer already produced these surfaces and no display mode is
        # available in the headless showcase process.
        source_layers[label] = pygame.image.load(str(path))
    tile_width = 520
    tile_height = 300
    gap = 18
    title_height = 44
    columns = 2
    rows = (len(labels) + columns - 1) // columns
    sheet = pygame.Surface((columns * tile_width + (columns + 1) * gap, title_height + rows * (tile_height + gap) + gap))
    sheet.fill((10, 14, 22))
    font = pygame.font.Font(None, 28)
    small_font = pygame.font.Font(None, 22)
    sheet.blit(font.render(title, True, (235, 240, 248)), (gap, 10))
    for index, label in enumerate(labels):
        column = index % columns
        row = index // columns
        x = gap + column * (tile_width + gap)
        y = title_height + gap + row * (tile_height + gap)
        crop = _crop_wrapped(source_layers[label], center_u, center_v)
        crop = pygame.transform.smoothscale(crop, (tile_width, tile_height))
        sheet.blit(crop, (x, y))
        sheet.blit(small_font.render(label, True, (232, 238, 246)), (x + 8, y + 8))
        pygame.draw.rect(sheet, (108, 124, 148), pygame.Rect(x, y, tile_width, tile_height), 1)
    output_path = output_root / f"{name}.png"
    pygame.image.save(sheet, str(output_path))
    return output_path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, help="Extracted .i0wg bundle directory")
    parser.add_argument("--output", required=True, help="Showcase output directory")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    output_root = Path(args.output).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    planet = _load_json(root, "planet.json")
    mountain_u, mountain_v = _mountain_center(planet)
    coast_u, coast_v, coast_label = _coast_center(planet)

    pygame.init()
    try:
        mountain_path = _showcase(
            root,
            output_root,
            "mountain_climate_zoom",
            f"Mountain / climate coupling zoom | center u={mountain_u:.3f}, v={mountain_v:.3f}",
            mountain_u,
            mountain_v,
            ["True Color", "Annual Precipitation", "Surface Temperature", "Climate and Rivers"],
        )
        coast_path = _showcase(
            root,
            output_root,
            "coastal_geomorphology_zoom",
            f"{coast_label} coastal zoom | center u={coast_u:.3f}, v={coast_v:.3f}",
            coast_u,
            coast_v,
            ["True Color", "Coastal Geomorphology", "Surface Materials", "Annual Precipitation"],
        )
    finally:
        pygame.quit()
    print(json.dumps({
        "source_root": str(root),
        "generation_performed": False,
        "regional_regeneration_performed": False,
        "mountain_center_uv": [round(mountain_u, 6), round(mountain_v, 6)],
        "coast_center_uv": [round(coast_u, 6), round(coast_v, 6)],
        "showcases": [str(mountain_path), str(coast_path)],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
