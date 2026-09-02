"""Render causal terrain diagnostics from an existing world-gen bundle.

This is an inspection tool only. It never calls world generation or regional
regeneration. The parent surface and production orogen field are reconstructed
from the saved root planet so the diagnostic images can distinguish a bad
heightfield from a bad true-colour compositor.

Usage:
    py tools\\render_lod_diagnostics.py \\
        --root .cache\\canonical_lod1_orogen_profile_fix_extracted \\
        --output .cache\\canonical_lod1_orogen_profile_fix_extracted\\images\\diagnostics
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import pygame

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    import numpy as np
except ImportError:  # pragma: no cover - development environments provide numpy.
    np = None

def _load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _clamp01(values):
    return np.clip(np.nan_to_num(values, nan=0.0, posinf=1.0, neginf=0.0), 0.0, 1.0)


def _robust_normalize(values, low_percentile=2.0, high_percentile=98.0):
    values = np.asarray(values, dtype=np.float32)
    low, high = np.nanpercentile(values, [low_percentile, high_percentile])
    if high <= low + 1e-9:
        return np.zeros(values.shape, dtype=np.float32), float(low), float(high)
    return _clamp01((values - low) / (high - low)), float(low), float(high)


def _signed_normalize(values, percentile=98.0):
    values = np.asarray(values, dtype=np.float32)
    scale = float(np.nanpercentile(np.abs(values), percentile))
    if scale <= 1e-9:
        return np.full(values.shape, 0.5, dtype=np.float32), -scale, scale
    return _clamp01(values / (2.0 * scale) + 0.5), -scale, scale


def _surface_from_rgb(rgb):
    # pygame expects (width, height, channels); numpy terrain fields are
    # stored as (height, width, channels).
    return pygame.surfarray.make_surface(np.transpose(rgb, (1, 0, 2)).astype(np.uint8))


def _save_scalar(values, path, palette="gray"):
    normalized, low, high = _robust_normalize(values)
    if palette == "gray":
        rgb = np.repeat((normalized[..., None] * 255.0), 3, axis=2)
    elif palette == "slope":
        rgb = np.stack((normalized * 255.0, normalized * 210.0, normalized * 90.0), axis=2)
    elif palette == "curvature":
        signed, low, high = _signed_normalize(values)
        positive = np.clip((signed - 0.5) * 2.0, 0.0, 1.0)
        negative = np.clip((0.5 - signed) * 2.0, 0.0, 1.0)
        rgb = np.stack((positive * 230.0, (1.0 - np.abs(signed - 0.5) * 2.0) * 220.0, negative * 235.0), axis=2)
    elif palette == "residual":
        signed, low, high = _signed_normalize(values)
        positive = np.clip((signed - 0.5) * 2.0, 0.0, 1.0)
        negative = np.clip((0.5 - signed) * 2.0, 0.0, 1.0)
        rgb = np.stack((positive * 235.0, (1.0 - np.maximum(positive, negative)) * 220.0, negative * 235.0), axis=2)
    else:
        raise ValueError(f"Unknown scalar palette: {palette}")
    pygame.image.save(_surface_from_rgb(np.clip(rgb, 0.0, 255.0)), str(path))
    return {"min_display": low, "max_display": high}


def _save_hillshade(elevation, spacing_x, spacing_y, path):
    dzdy, dzdx = np.gradient(elevation, max(1.0, spacing_y), max(1.0, spacing_x))
    slope = np.arctan(np.sqrt(dzdx * dzdx + dzdy * dzdy))
    aspect = np.arctan2(-dzdx, dzdy)
    altitude = math.radians(45.0)
    azimuth = math.radians(315.0)
    shade = (
        np.sin(altitude) * np.cos(slope)
        + np.cos(altitude) * np.sin(slope) * np.cos(azimuth - aspect)
    )
    normalized, low, high = _robust_normalize(shade, 1.0, 99.0)
    rgb = np.repeat((normalized[..., None] * 255.0), 3, axis=2)
    pygame.image.save(_surface_from_rgb(rgb), str(path))
    return {"min_display": low, "max_display": high}


def _sample_parent_grid(parent_rows, source_bounds, height, width):
    from simulations.world_gen.regional_refinement import _sample_bicubic

    result = np.empty((height, width), dtype=np.float32)
    u0, u1 = float(source_bounds["min_u"]), float(source_bounds["max_u"])
    v0, v1 = float(source_bounds["min_v"]), float(source_bounds["max_v"])
    for y in range(height):
        local_v = y / max(1, height - 1)
        source_v = v0 + (v1 - v0) * local_v
        for x in range(width):
            local_u = x / max(1, width - 1)
            source_u = u0 + (u1 - u0) * local_u
            result[y, x] = _sample_bicubic(parent_rows, source_u, source_v, wrap_x=True)
    return result


def _orogen_arrays(root_planet, source_bounds, height, width):
    from simulations.world_gen.regional_refinement import (
        _build_orogen_structural_grid,
        _sample_orogen_structural_grid,
    )
    from simulations.world_gen.heightmap import _heightmap_tectonic_model

    tectonics = root_planet.get("tectonic_model") or {}
    production_model = _heightmap_tectonic_model(tectonics)
    grid = _build_orogen_structural_grid(
        production_model,
        float(source_bounds["min_u"]),
        float(source_bounds["max_u"]),
        float(source_bounds["min_v"]),
        float(source_bounds["max_v"]),
        sample_width=width,
        sample_height=height,
    )
    arrays = {
        key: np.empty((height, width), dtype=np.float32)
        for key in (
            "mountain_influence",
            "core_influence",
            "arc_influence",
            "shoulder_influence",
            "forearc_influence",
        )
    }
    u0, u1 = float(source_bounds["min_u"]), float(source_bounds["max_u"])
    v0, v1 = float(source_bounds["min_v"]), float(source_bounds["max_v"])
    for y in range(height):
        local_v = y / max(1, height - 1)
        global_v = v0 + (v1 - v0) * local_v
        for x in range(width):
            local_u = x / max(1, width - 1)
            global_u = u0 + (u1 - u0) * local_u
            context = _sample_orogen_structural_grid(grid, global_u, global_v)
            for key in arrays:
                arrays[key][y, x] = float(context.get(key, 0.0) or 0.0)
    return arrays, {"width": grid["width"], "height": grid["height"]}


def _save_orogen_profile(arrays, path):
    core = _clamp01(arrays["core_influence"])
    arc = _clamp01(arrays["arc_influence"])
    forearc = _clamp01(arrays["forearc_influence"])
    rgb = np.stack((core * 255.0, arc * 220.0, forearc * 235.0), axis=2)
    pygame.image.save(_surface_from_rgb(np.clip(rgb, 0.0, 255.0)), str(path))


def _build_contact_sheet(images, output_path):
    tile_w, tile_h = 512, 300
    gap, header = 14, 34
    columns = 2
    rows = (len(images) + columns - 1) // columns
    sheet = pygame.Surface((columns * tile_w + (columns + 1) * gap, rows * (tile_h + header) + (rows + 1) * gap))
    sheet.fill((14, 18, 26))
    font = pygame.font.SysFont("consolas", 17)
    for index, (label, surface) in enumerate(images):
        col, row = index % columns, index // columns
        x = gap + col * (tile_w + gap)
        y = gap + row * (tile_h + header)
        sheet.blit(font.render(label, True, (235, 240, 248)), (x + 6, y + 6))
        scaled = pygame.transform.smoothscale(surface, (tile_w, tile_h))
        sheet.blit(scaled, (x, y + header))
        pygame.draw.rect(sheet, (100, 118, 144), pygame.Rect(x, y + header, tile_w, tile_h), 1)
    pygame.image.save(sheet, str(output_path))


def main(argv=None):
    if np is None:
        raise RuntimeError("numpy is required for terrain diagnostics")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, help="Extracted .i0wg bundle directory")
    parser.add_argument("--output", required=True, help="Diagnostic output directory")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    root_planet = _load_json(root / "planet.json")
    regional_entity = _load_json(root / "regional" / "region.json")
    heightmap = regional_entity.get("heightmap_model") or {}
    rows = np.asarray((heightmap.get("sample_grid") or {}).get("rows") or [], dtype=np.float32)
    if rows.ndim != 2 or rows.size == 0:
        raise ValueError("Regional bundle has no rectangular heightfield")
    source_bounds = heightmap.get("source_uv_bounds") or {}
    root_rows = ((root_planet.get("heightmap_model") or {}).get("sample_grid") or {}).get("rows") or []
    if not root_rows:
        raise ValueError("Root bundle has no parent heightfield")
    spacing_x = float(heightmap.get("sample_spacing_x_m") or 1.0)
    spacing_y = float(heightmap.get("sample_spacing_y_m") or spacing_x)
    parent = _sample_parent_grid(root_rows, source_bounds, rows.shape[0], rows.shape[1])
    residual = rows - parent
    dzdy, dzdx = np.gradient(rows, spacing_y, spacing_x)
    slope_degrees = np.degrees(np.arctan(np.sqrt(dzdx * dzdx + dzdy * dzdy)))
    d2zdy = np.gradient(dzdy, spacing_y, axis=0)
    d2zdx = np.gradient(dzdx, spacing_x, axis=1)
    curvature = d2zdx + d2zdy
    orogen, structural_grid = _orogen_arrays(root_planet, source_bounds, rows.shape[0], rows.shape[1])

    pygame.init()
    try:
        generated = []
        def scalar(label, values, filename, palette):
            path = output / filename
            _save_scalar(values, path, palette)
            generated.append((label, pygame.image.load(str(path))))

        scalar("Raw height", rows, "raw_height.png", "gray")
        hillshade_path = output / "hillshade.png"
        _save_hillshade(rows, spacing_x, spacing_y, hillshade_path)
        generated.append(("Hillshade", pygame.image.load(str(hillshade_path))))
        scalar("Slope degrees", slope_degrees, "slope_degrees.png", "slope")
        scalar("Curvature", curvature, "curvature.png", "curvature")
        scalar("Parent residual", residual, "parent_residual.png", "residual")
        orogen_path = output / "production_orogen_profile.png"
        _save_orogen_profile(orogen, orogen_path)
        generated.append(("Production orogen profile", pygame.image.load(str(orogen_path))))
        contact_path = output / "lod1_diagnostics_contact_sheet.png"
        _build_contact_sheet(generated, contact_path)
    finally:
        pygame.quit()

    analysis = {
        "generation_performed": False,
        "regional_regeneration_performed": False,
        "source_bundle": str(root),
        "diagnostic_images": [str(output / name) for name in (
            "raw_height.png",
            "hillshade.png",
            "slope_degrees.png",
            "curvature.png",
            "parent_residual.png",
            "production_orogen_profile.png",
            "lod1_diagnostics_contact_sheet.png",
        )],
        "grid": {"width": int(rows.shape[1]), "height": int(rows.shape[0])},
        "height_range_m": [float(np.min(rows)), float(np.max(rows))],
        "parent_residual_range_m": [float(np.min(residual)), float(np.max(residual))],
        "parent_residual_mean_m": float(np.mean(residual)),
        "slope_degrees": {
            "mean": float(np.mean(slope_degrees)),
            "p95": float(np.percentile(slope_degrees, 95.0)),
            "max": float(np.max(slope_degrees)),
        },
        "curvature_abs_p95": float(np.percentile(np.abs(curvature), 95.0)),
        "orogen_structural_sampling_grid": structural_grid,
        "orogen_profile_means": {
            key: float(np.mean(value)) for key, value in orogen.items()
        },
    }
    (output / "analysis.json").write_text(json.dumps(analysis, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(analysis, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
