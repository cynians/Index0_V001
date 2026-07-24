from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


LMSL_OFFSET_M = 0.633
LAND_CLASS = 2
BATHYMETRY_CLASS = 29


def _font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    names = [
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
        "arialbd.ttf" if bold else "arial.ttf",
    ]
    for name in names:
        try:
            return ImageFont.truetype(name, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _fill_nearest(values: np.ndarray, valid: np.ndarray, iterations: int = 8) -> np.ndarray:
    result = values.astype(np.float32, copy=True)
    known = valid.copy()
    for _ in range(iterations):
        if known.all():
            break
        total = np.zeros_like(result)
        count = np.zeros_like(result, dtype=np.int16)
        for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)):
            shifted = np.roll(np.roll(result, dy, axis=0), dx, axis=1)
            shifted_known = np.roll(np.roll(known, dy, axis=0), dx, axis=1)
            if dy < 0:
                shifted_known[dy:, :] = False
            elif dy > 0:
                shifted_known[:dy, :] = False
            if dx < 0:
                shifted_known[:, dx:] = False
            elif dx > 0:
                shifted_known[:, :dx] = False
            total += np.where(shifted_known, shifted, 0.0)
            count += shifted_known
        grow = (~known) & (count > 0)
        result[grow] = total[grow] / count[grow]
        known[grow] = True
    return result


def _read_points(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    import laspy

    with laspy.open(path) as source:
        points = source.read()
    classes = np.asarray(points.classification)
    keep = (classes == LAND_CLASS) | (classes == BATHYMETRY_CLASS)
    return (
        np.asarray(points.x)[keep],
        np.asarray(points.y)[keep],
        np.asarray(points.z)[keep] - LMSL_OFFSET_M,
        classes[keep],
    )


def _local_metres(lon: np.ndarray, lat: np.ndarray) -> tuple[np.ndarray, np.ndarray, float, float]:
    lon0 = float(lon.min())
    lat0 = float(lat.min())
    mean_lat = math.radians(float((lat.min() + lat.max()) * 0.5))
    x = (lon - lon0) * 111_320.0 * math.cos(mean_lat)
    y = (lat - lat0) * 110_540.0
    return x, y, lon0, lat0


def _rasterize(
    x: np.ndarray,
    y: np.ndarray,
    z: np.ndarray,
    classes: np.ndarray,
    *,
    resolution: float,
) -> dict[str, np.ndarray | float]:
    width = int(math.ceil(float(x.max()) / resolution)) + 1
    height = int(math.ceil(float(y.max()) / resolution)) + 1
    col = np.clip((x / resolution).astype(np.int32), 0, width - 1)
    row = np.clip(((float(y.max()) - y) / resolution).astype(np.int32), 0, height - 1)
    flat = row.astype(np.int64) * width + col
    size = width * height
    sums = np.bincount(flat, weights=z, minlength=size).reshape(height, width)
    counts = np.bincount(flat, minlength=size).reshape(height, width)
    land = np.bincount(flat[classes == LAND_CLASS], minlength=size).reshape(height, width)
    bathy = np.bincount(flat[classes == BATHYMETRY_CLASS], minlength=size).reshape(height, width)
    elevation = np.divide(sums, counts, out=np.zeros_like(sums, dtype=np.float64), where=counts > 0)
    return {
        "elevation": elevation.astype(np.float32),
        "counts": counts.astype(np.int16),
        "land": land.astype(np.int16),
        "bathy": bathy.astype(np.int16),
        "resolution": resolution,
        "max_y": float(y.max()),
    }


def _window_sum(values: np.ndarray, size: int) -> np.ndarray:
    integral = np.pad(values.astype(np.float64), ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    return integral[size:, size:] - integral[:-size, size:] - integral[size:, :-size] + integral[:-size, :-size]


def _choose_l6(raster: dict[str, np.ndarray | float], footprint_m: float = 30.0) -> tuple[int, int, int]:
    resolution = float(raster["resolution"])
    size = int(round(footprint_m / resolution))
    counts = np.asarray(raster["counts"])
    valid = counts > 0
    elevation = np.asarray(raster["elevation"])
    filled = _fill_nearest(elevation, valid, iterations=4)
    land_mask = filled >= 0.0
    bathy_mask = ~land_mask
    land_sum = _window_sum(land_mask, size)
    bathy_sum = _window_sum(bathy_mask & valid, size)
    valid_sum = _window_sum(valid, size)
    total = float(size * size)
    mixed = (land_sum > 0.22 * total) & (bathy_sum > 0.22 * total) & (valid_sum > 0.50 * total)

    transition = np.zeros_like(valid, dtype=np.uint8)
    transition[:, 1:] += valid[:, 1:] & valid[:, :-1] & (land_mask[:, 1:] != land_mask[:, :-1])
    transition[1:, :] += valid[1:, :] & valid[:-1, :] & (land_mask[1:, :] != land_mask[:-1, :])
    transition_sum = _window_sum(transition, size)

    gy, gx = np.gradient(filled, resolution)
    slope = np.hypot(gx, gy)
    slope_sum = _window_sum(np.where(valid & land_mask, np.clip(slope, 0.0, 5.0), 0.0), size)
    relief_sum = _window_sum(np.where(valid, np.clip(np.abs(filled), 0.0, 8.0), 0.0), size)
    score = slope_sum * 1.7 + relief_sum * 0.32 + np.minimum(land_sum, bathy_sum) * 0.04 - transition_sum * 0.9
    score[~mixed] = -np.inf
    margin = max(4, size // 3)
    score[:margin, :] = -np.inf
    score[-margin:, :] = -np.inf
    score[:, :margin] = -np.inf
    score[:, -margin:] = -np.inf
    if not np.isfinite(score).any():
        raise RuntimeError("Could not find a mixed land-water 30 m reference window")
    top, left = np.unravel_index(np.nanargmax(score), score.shape)
    return int(top), int(left), size


def _choose_l7(
    raster: dict[str, np.ndarray | float], l6: tuple[int, int, int], footprint_m: float = 10.0
) -> tuple[int, int, int]:
    resolution = float(raster["resolution"])
    size = int(round(footprint_m / resolution))
    top6, left6, size6 = l6
    counts = np.asarray(raster["counts"])[top6 : top6 + size6, left6 : left6 + size6]
    elevation = np.asarray(raster["elevation"])[top6 : top6 + size6, left6 : left6 + size6]
    valid = counts > 0
    land_mask = _fill_nearest(elevation, valid, iterations=4) >= 0.0
    transition = np.zeros_like(valid, dtype=np.uint8)
    transition[:, 1:] += valid[:, 1:] & valid[:, :-1] & (land_mask[:, 1:] != land_mask[:, :-1])
    transition[1:, :] += valid[1:, :] & valid[:-1, :] & (land_mask[1:, :] != land_mask[:-1, :])
    transition_sum = _window_sum(transition, size)
    land_sum = _window_sum(land_mask & valid, size)
    bathy_sum = _window_sum((~land_mask) & valid, size)
    total = float(size * size)
    filled = _fill_nearest(elevation, valid, iterations=4)
    gy, gx = np.gradient(filled, resolution)
    slope_sum = _window_sum(np.where(valid, np.clip(np.hypot(gx, gy), 0.0, 5.0), 0.0), size)
    score = slope_sum + 0.08 * np.minimum(land_sum, bathy_sum) - 0.8 * transition_sum
    score[(land_sum < 0.18 * total) | (bathy_sum < 0.18 * total)] = -np.inf
    if not np.isfinite(score).any():
        top = left = (size6 - size) // 2
    else:
        top, left = np.unravel_index(np.nanargmax(score), score.shape)
    return top6 + int(top), left6 + int(left), size


def _crop(raster: dict[str, np.ndarray | float], window: tuple[int, int, int]) -> dict[str, np.ndarray | float]:
    top, left, size = window
    return {
        key: (np.asarray(value)[top : top + size, left : left + size] if isinstance(value, np.ndarray) else value)
        for key, value in raster.items()
    }


def _colorize(crop: dict[str, np.ndarray | float], target_px: int = 900) -> Image.Image:
    z = np.asarray(crop["elevation"])
    counts = np.asarray(crop["counts"])
    valid = counts > 0
    filled = _fill_nearest(z, valid, iterations=max(8, z.shape[0] // 4))
    high = np.asarray(
        Image.fromarray(filled.astype(np.float32), mode="F").resize((target_px, target_px), Image.Resampling.BICUBIC)
    )
    high_valid = np.asarray(
        Image.fromarray((valid * 255).astype(np.uint8), mode="L").resize((target_px, target_px), Image.Resampling.NEAREST)
    ) > 0
    land = high >= 0.0
    effective_resolution = float(crop["resolution"]) * filled.shape[0] / target_px
    gy, gx = np.gradient(high, effective_resolution)
    shade = np.clip(0.70 + (-0.55 * gx + 0.75 * gy) / np.maximum(1.0, np.hypot(gx, gy) * 2.5), 0.35, 1.08)

    rgb = np.empty(high.shape + (3,), dtype=np.float32)
    water_t = np.clip((-high) / 8.0, 0.0, 1.0)[..., None]
    shallow = np.array([34.0, 130.0, 151.0])
    deep = np.array([12.0, 45.0, 79.0])
    rgb[:] = shallow * (1.0 - water_t) + deep * water_t
    land_t = np.clip(high / 6.0, 0.0, 1.0)[..., None]
    basalt_low = np.array([116.0, 119.0, 109.0])
    basalt_high = np.array([190.0, 184.0, 158.0])
    land_rgb = basalt_low * (1.0 - land_t) + basalt_high * land_t
    rgb[land] = land_rgb[land]
    rgb *= shade[..., None]

    boundary = np.zeros_like(high_valid)
    boundary[:, 1:] |= high_valid[:, 1:] & high_valid[:, :-1] & (land[:, 1:] != land[:, :-1])
    boundary[1:, :] |= high_valid[1:, :] & high_valid[:-1, :] & (land[1:, :] != land[:-1, :])
    rgb[boundary] = np.array([245.0, 214.0, 132.0])
    return Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGB")


def _decorate_map(
    image: Image.Image,
    *,
    footprint_m: float,
    label: str,
    native_resolution_m: float,
    l7_box: tuple[float, float, float, float] | None = None,
) -> Image.Image:
    canvas = image.copy()
    draw = ImageDraw.Draw(canvas)
    pad = 22
    draw.rounded_rectangle((pad, pad, 560, 132), radius=10, fill=(10, 18, 25, 220))
    draw.text((42, 38), label, font=_font(27, bold=True), fill=(245, 248, 250))
    draw.text(
        (42, 78),
        f"{footprint_m:.0f} m × {footprint_m:.0f} m  |  {native_resolution_m:g} m analysis grid",
        font=_font(19),
        fill=(220, 228, 233),
    )
    draw.text((42, 106), "NOAA/USACE 2013 topo-bathymetric lidar", font=_font(16), fill=(170, 190, 202))
    if l7_box is not None:
        x0, y0, x1, y1 = l7_box
        draw.rectangle((x0, y0, x1, y1), outline=(255, 49, 176), width=5)
        draw.rectangle((x0, max(0, y0 - 28), x0 + 112, y0), fill=(18, 20, 25))
        draw.text((x0 + 6, max(0, y0 - 25)), "L7: 10 m", font=_font(17, bold=True), fill=(255, 107, 201))
    bar_m = 5.0 if footprint_m >= 30 else 2.0
    bar_px = int(round(canvas.width * bar_m / footprint_m))
    x1 = canvas.width - 40
    x0 = x1 - bar_px
    y = canvas.height - 42
    draw.line((x0, y, x1, y), fill="white", width=5)
    draw.line((x0, y - 10, x0, y + 10), fill="white", width=4)
    draw.line((x1, y - 10, x1, y + 10), fill="white", width=4)
    draw.text((x0, y - 34), f"{bar_m:g} m", font=_font(18, bold=True), fill="white")
    draw.polygon([(canvas.width - 48, 34), (canvas.width - 61, 72), (canvas.width - 48, 65), (canvas.width - 35, 72)], fill="white")
    draw.text((canvas.width - 56, 78), "N", font=_font(18, bold=True), fill="white")
    return canvas


def _component_count(mask: np.ndarray) -> int:
    work = mask.copy()
    components = 0
    height, width = work.shape
    for row in range(height):
        for col in range(width):
            if not work[row, col]:
                continue
            components += 1
            stack = [(row, col)]
            work[row, col] = False
            while stack:
                y, x = stack.pop()
                for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    yy, xx = y + dy, x + dx
                    if 0 <= yy < height and 0 <= xx < width and work[yy, xx]:
                        work[yy, xx] = False
                        stack.append((yy, xx))
    return components


def _metrics(crop: dict[str, np.ndarray | float], footprint_m: float) -> dict[str, float | int]:
    elevation = np.asarray(crop["elevation"])
    counts = np.asarray(crop["counts"])
    valid = counts > 0
    land = _fill_nearest(elevation, valid, iterations=4) >= 0.0
    water = ~land
    boundary = np.zeros_like(valid)
    boundary[:, 1:] |= land[:, 1:] != land[:, :-1]
    boundary[1:, :] |= land[1:, :] != land[:-1, :]
    z = elevation[valid]
    return {
        "footprint_m": footprint_m,
        "native_grid_m": float(crop["resolution"]),
        "valid_cell_fraction": round(float(valid.mean()), 4),
        "land_fraction": round(float(land.mean()), 4),
        "elevation_p05_m_lmsl": round(float(np.percentile(z, 5)), 3),
        "elevation_p95_m_lmsl": round(float(np.percentile(z, 95)), 3),
        "water_components": _component_count(water),
        "land_components": _component_count(land),
        "boundary_cells": int(boundary.sum()),
    }


def _window_center_lon_lat(
    window: tuple[int, int, int], raster: dict[str, np.ndarray | float], lon0: float, lat0: float, mean_lat: float
) -> tuple[float, float]:
    top, left, size = window
    resolution = float(raster["resolution"])
    x = (left + size * 0.5) * resolution
    y_from_top = (top + size * 0.5) * resolution
    y = float(raster["max_y"]) - y_from_top
    lon = lon0 + x / (111_320.0 * math.cos(math.radians(mean_lat)))
    lat = lat0 + y / 110_540.0
    return lon, lat


def build(laz_path: Path, output_dir: Path, generated_dir: Path) -> None:
    x_lon, y_lat, z, classes = _read_points(laz_path)
    mean_lat = float((y_lat.min() + y_lat.max()) * 0.5)
    x, y, lon0, lat0 = _local_metres(x_lon, y_lat)
    raster = _rasterize(x, y, z, classes, resolution=1.0)
    l6_window = _choose_l6(raster)
    l7_window = _choose_l7(raster, l6_window)
    l6_crop = _crop(raster, l6_window)
    l7_crop = _crop(raster, l7_window)

    output_dir.mkdir(parents=True, exist_ok=True)
    top6, left6, size6 = l6_window
    top7, left7, size7 = l7_window
    box = (
        (left7 - left6) / size6 * 900,
        (top7 - top6) / size6 * 900,
        (left7 - left6 + size7) / size6 * 900,
        (top7 - top6 + size7) / size6 * 900,
    )
    real_l6 = _decorate_map(
        _colorize(l6_crop), footprint_m=30.0, label="REAL ROCKY COAST — 30 m", native_resolution_m=1.0, l7_box=box
    )
    real_l7 = _decorate_map(
        _colorize(l7_crop), footprint_m=10.0, label="REAL ROCKY COAST — 10 m", native_resolution_m=1.0
    )
    real_l6_path = output_dir / "kaena_real_l6_30m.png"
    real_l7_path = output_dir / "kaena_real_l7_10m.png"
    real_l6.save(real_l6_path, optimize=True)
    real_l7.save(real_l7_path, optimize=True)

    generated_l6 = Image.open(generated_dir / "level_6_plot.png").convert("RGB").resize((900, 540), Image.Resampling.LANCZOS)
    generated_l7 = Image.open(generated_dir / "level_7_survey.png").convert("RGB").resize((900, 540), Image.Resampling.LANCZOS)
    sheet = Image.new("RGB", (1840, 2200), (19, 25, 31))
    draw = ImageDraw.Draw(sheet)
    draw.text((40, 28), "GENERATED COAST vs KAʻENA POINT REFERENCE", font=_font(38, bold=True), fill=(245, 248, 250))
    draw.text((40, 78), "Equal physical footprints; real map from classified topo-bathymetric lidar", font=_font(22), fill=(174, 192, 204))
    placements = [
        (generated_l6, 40, 150, "GENERATED L6 — 30 m"),
        (real_l6, 940, 150, "REAL — 30 m"),
        (generated_l7, 40, 850, "GENERATED L7 — 10 m"),
        (real_l7, 940, 850, "REAL — 10 m"),
    ]
    for panel, px, py, title in placements:
        draw.text((px, py - 36), title, font=_font(23, bold=True), fill=(235, 240, 243))
        sheet.paste(panel, (px, py))
    findings = [
        "Generated: dozens of closed shoreline loops and speckled water/land islands.",
        "Reference: one connected water body; roughness is subordinate to the cliff/bench edge.",
        "Generated L7 texture implies centimetre fidelity unsupported by process structure.",
        "Reference data constrain metre-scale form; they do not resolve individual clasts.",
    ]
    draw.rounded_rectangle((40, 1510, 1800, 2110), radius=16, fill=(30, 39, 47))
    draw.text((72, 1545), "PRIMARY DISCREPANCIES", font=_font(28, bold=True), fill=(255, 107, 201))
    for index, finding in enumerate(findings):
        y_text = 1605 + index * 105
        draw.ellipse((74, y_text + 8, 88, y_text + 22), fill=(255, 107, 201))
        draw.text((108, y_text), finding, font=_font(24), fill=(225, 232, 236))
    sheet_path = output_dir / "generated_vs_kaena_equal_scale.png"
    sheet.save(sheet_path, optimize=True)

    center_l6 = _window_center_lon_lat(l6_window, raster, lon0, lat0, mean_lat)
    center_l7 = _window_center_lon_lat(l7_window, raster, lon0, lat0, mean_lat)
    report = {
        "reference": {
            "site": "Kaena Point, Oahu, Hawaii",
            "source_tile": laz_path.name,
            "survey": "2013 USACE NCMP Topobathy Lidar: Oahu (HI)",
            "dataset_url": "https://www.fisheries.noaa.gov/inport/item/49756",
            "geology_url": "https://dlnr.hawaii.gov/ecosystems/nars/oahu/kaena/",
            "vertical_reference": "local mean sea level, NOAA correction applied",
            "analysis_grid_m": 1.0,
            "surface_method": "mean classified ground/bathymetric return per 1 m cell; gaps nearest-filled; shoreline is 0 m LMSL contour",
            "classification": {"land": LAND_CLASS, "bathymetry": BATHYMETRY_CLASS},
        },
        "l6": {"center_lon_lat": center_l6, "metrics": _metrics(l6_crop, 30.0), "image": str(real_l6_path.resolve())},
        "l7": {"center_lon_lat": center_l7, "metrics": _metrics(l7_crop, 10.0), "image": str(real_l7_path.resolve())},
        "comparison_image": str(sheet_path.resolve()),
    }
    (output_dir / "comparison_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build an equal-scale real-world comparison for coastal benchmark L6/L7.")
    parser.add_argument("laz", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("generated_dir", type=Path)
    args = parser.parse_args()
    build(args.laz.resolve(), args.output_dir.resolve(), args.generated_dir.resolve())
