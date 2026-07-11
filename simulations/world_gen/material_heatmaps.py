import json
import math
import re
import zipfile
from pathlib import Path

import pygame

from simulations.world_gen.map_seed import resolved_map_seed, seed_range
from simulations.world_gen.natural_materials import material_display_color


MATERIAL_HEATMAP_MODEL_VERSION = "material-heatmaps-v3"
RASTER_BUNDLE_FORMAT = "index0_raster_bundle"
RASTER_BUNDLE_VERSION = 1
RASTER_BUNDLE_EXTENSION = ".i0r"
DEFAULT_HEATMAP_SIZE = (256, 128)


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, float(value)))


def _smoothstep(edge0, edge1, value):
    if edge1 <= edge0:
        return 1.0 if value >= edge1 else 0.0
    t = _clamp((value - edge0) / (edge1 - edge0))
    return t * t * (3.0 - 2.0 * t)


def _safe_slug(value):
    text = re.sub(r"[^0-9A-Za-z_]+", "_", str(value or "material")).strip("_").lower()
    return text or "material"


def _relative_or_absolute(path, storage_root=None):
    path = Path(path)
    if storage_root is not None:
        try:
            return path.resolve().relative_to(Path(storage_root).resolve()).as_posix()
        except ValueError:
            pass
    return str(path.resolve())


def _surface_to_rgba_bytes(surface):
    tobytes = getattr(pygame.image, "tobytes", None)
    if tobytes is not None:
        return tobytes(surface, "RGBA")
    return pygame.image.tostring(surface, "RGBA")


def _surface_from_rgba_bytes(data, width, height):
    surface = pygame.image.frombuffer(data, (int(width), int(height)), "RGBA")
    return surface.copy()


def _write_raster_bundle(bundle_path, width, height, layers, metadata=None):
    bundle_path = Path(bundle_path)
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_layers = []
    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for layer in layers:
            layer_id = _safe_slug(layer.get("id") or layer.get("material_id") or layer.get("name") or "layer")
            entry_name = f"layers/{layer_id}.rgba"
            surface = layer.get("surface")
            if surface is None:
                continue
            bundle.writestr(entry_name, _surface_to_rgba_bytes(surface))
            layer_meta = {
                key: value
                for key, value in layer.items()
                if key not in {"surface", "pixels"}
            }
            layer_meta["id"] = layer_id
            layer_meta["rgba_path"] = entry_name
            layer_meta["width_px"] = width
            layer_meta["height_px"] = height
            manifest_layers.append(layer_meta)

        manifest = {
            "format": RASTER_BUNDLE_FORMAT,
            "format_version": RASTER_BUNDLE_VERSION,
            "width_px": width,
            "height_px": height,
            "encoding": "rgba8888",
            "layers": manifest_layers,
            "metadata": metadata or {},
        }
        bundle.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True))
    return manifest


def load_raster_bundle_surface(bundle_path, layer_id):
    bundle_path = Path(bundle_path)
    if not bundle_path.exists():
        return None
    requested = str(layer_id or "composite")
    try:
        with zipfile.ZipFile(bundle_path, "r") as bundle:
            manifest = json.loads(bundle.read("manifest.json").decode("utf-8"))
            if manifest.get("format") != RASTER_BUNDLE_FORMAT:
                return None
            layers = manifest.get("layers") or []
            layer = next(
                (
                    item
                    for item in layers
                    if str(item.get("id")) == requested
                    or str(item.get("material_id") or "") == requested
                    or str(item.get("role") or "") == requested
                ),
                None,
            )
            if layer is None and requested == "composite":
                layer = next((item for item in layers if item.get("role") == "composite"), None)
            if layer is None:
                return None
            width = int(layer.get("width_px") or manifest.get("width_px") or 0)
            height = int(layer.get("height_px") or manifest.get("height_px") or 0)
            if width <= 0 or height <= 0:
                return None
            data = bundle.read(layer.get("rgba_path"))
            return _surface_from_rgba_bytes(data, width, height)
    except (OSError, KeyError, json.JSONDecodeError, zipfile.BadZipFile, pygame.error):
        return None


def import_png_to_raster_bundle(png_path, bundle_path, layer_id="imported_png", metadata=None):
    surface = pygame.image.load(str(png_path))
    try:
        surface = surface.convert_alpha()
    except pygame.error:
        surface = surface.copy()
    width, height = surface.get_size()
    layer_id = _safe_slug(layer_id or "imported_png")
    manifest = _write_raster_bundle(
        bundle_path,
        width,
        height,
        [{
            "id": layer_id,
            "role": "imported_png",
            "name": metadata.get("name", layer_id) if isinstance(metadata, dict) else layer_id,
            "surface": surface,
        }],
        metadata=metadata or {"source_path": str(png_path)},
    )
    return {
        "bundle_path": str(bundle_path),
        "bundle_layer_id": layer_id,
        "width_px": width,
        "height_px": height,
        "manifest": manifest,
    }


def _rows_from_heightmap(heightmap):
    grid = heightmap.get("sample_grid") if isinstance(heightmap, dict) else {}
    rows = grid.get("rows") if isinstance(grid, dict) else []
    if not rows or len(rows) < 2 or len(rows[0]) < 2:
        return []
    return rows


def _sample_height(rows, nx, ny):
    if not rows:
        return 0.0
    row_count = len(rows)
    col_count = min(len(row) for row in rows)
    if row_count < 2 or col_count < 2:
        return float(rows[0][0] or 0.0)

    x = _clamp(nx) * (col_count - 1)
    y = _clamp(ny) * (row_count - 1)
    x0 = int(math.floor(x))
    y0 = int(math.floor(y))
    x1 = min(col_count - 1, x0 + 1)
    y1 = min(row_count - 1, y0 + 1)
    tx = x - x0
    ty = y - y0

    top = float(rows[y0][x0] or 0.0) * (1.0 - tx) + float(rows[y0][x1] or 0.0) * tx
    bottom = float(rows[y1][x0] or 0.0) * (1.0 - tx) + float(rows[y1][x1] or 0.0) * tx
    return top * (1.0 - ty) + bottom * ty


def _wave_noise(map_seed, material_id, nx, ny):
    freq_a = seed_range(map_seed, f"{material_id}:freq_a", 1.2, 4.8)
    freq_b = seed_range(map_seed, f"{material_id}:freq_b", 2.0, 7.4)
    phase_a = seed_range(map_seed, f"{material_id}:phase_a", 0.0, math.tau)
    phase_b = seed_range(map_seed, f"{material_id}:phase_b", 0.0, math.tau)
    signal = (
        math.sin(nx * math.tau * freq_a + ny * 2.6 + phase_a)
        + math.cos((nx + ny * 0.7) * math.tau * freq_b + phase_b)
    ) * 0.5
    return _clamp((signal + 1.0) * 0.5)


def _wrapped_distance(a, b):
    direct = abs(a - b)
    return min(direct, 1.0 - direct)


def _regional_material_influence(map_seed, material_id, nx, ny):
    blob_signal = 0.0
    for index in range(3):
        cx = seed_range(map_seed, f"{material_id}:province_{index}:x", 0.0, 1.0)
        cy = seed_range(map_seed, f"{material_id}:province_{index}:y", 0.08, 0.92)
        radius = seed_range(map_seed, f"{material_id}:province_{index}:radius", 0.08, 0.24)
        dx = _wrapped_distance(nx, cx)
        dy = ny - cy
        distance = math.sqrt(dx * dx + dy * dy)
        blob_signal = max(blob_signal, math.exp(-((distance / max(0.01, radius)) ** 2)))

    belt_center = seed_range(map_seed, f"{material_id}:belt:center", 0.16, 0.84)
    belt_slope = seed_range(map_seed, f"{material_id}:belt:slope", -0.55, 0.55)
    belt_width = seed_range(map_seed, f"{material_id}:belt:width", 0.035, 0.12)
    belt_y = (belt_center + (nx - 0.5) * belt_slope) % 1.0
    belt_distance = _wrapped_distance(ny, belt_y)
    belt_signal = math.exp(-((belt_distance / max(0.01, belt_width)) ** 2))

    cellular = _wave_noise(map_seed, f"{material_id}:regional", nx * 0.63 + 0.17, ny * 0.71 + 0.09)
    return _clamp(blob_signal * 0.56 + belt_signal * 0.28 + cellular * 0.16)


def _material_affinity(material, context):
    material_id = str(material.get("material_id") or "").lower()
    name = str(material.get("name") or "").lower()
    tags = set(material.get("evidence_tags") or []) | set(context.get("planet_tags") or [])
    text = f"{material_id} {name}"

    elevation_norm = context["elevation_norm"]
    lowland = 1.0 - elevation_norm
    highland = elevation_norm
    polar = context["polar"]
    shoreline = context["shoreline"]
    ocean = context["ocean"]
    ice = context["ice"]
    noise = context["noise"]
    arid = 1.0 if "arid_surface" in tags or "aeolian_surface" in tags else 0.0
    hydrology = context["hydrology"]
    volcanic = 1.0 if "volcanic_surface" in tags or "basaltic_surface" in tags else 0.0
    cratered = 1.0 if "cratered_regolith" in tags or "impact_gardening" in tags else 0.0

    if "ice" in text:
        return polar * 0.70 + ice * 0.45 + ocean * 0.10 + noise * 0.12
    if "clay" in text:
        return lowland * 0.42 + hydrology * 0.30 + shoreline * 0.22 + noise * 0.16
    if "sand" in text or "sandstone" in text:
        return lowland * 0.34 + arid * 0.28 + shoreline * 0.18 + noise * 0.24
    if "calcite" in text or "gypsum" in text or "carbonate" in text:
        return shoreline * 0.42 + lowland * 0.22 + hydrology * 0.18 + noise * 0.16
    if "impact" in text or "breccia" in text:
        return cratered * 0.42 + noise * 0.40 + highland * 0.10
    if any(token in text for token in ("basalt", "olivine", "pyroxene", "magnetite", "ilmenite")):
        return volcanic * 0.30 + highland * 0.34 + noise * 0.28
    if any(token in text for token in ("granite", "feldspar", "quartz", "amphibole", "biotite")):
        return highland * 0.36 + (1.0 - ocean) * 0.24 + hydrology * 0.12 + noise * 0.18
    return 0.24 + noise * 0.34 + (1.0 - ocean) * 0.20 + highland * 0.12


def _select_material_layers(natural_material_model, max_layers=5):
    model = natural_material_model if isinstance(natural_material_model, dict) else {}
    candidates = [
        item
        for item in model.get("likely_materials") or []
        if isinstance(item, dict) and item.get("material_id")
    ]
    candidates.sort(key=lambda item: (-float(item.get("confidence", 0.0) or 0.0), str(item.get("name") or "")))
    return candidates[:max(1, int(max_layers or 1))]


def generate_material_heatmap_model(
    planet,
    natural_material_model,
    terrain,
    heightmap,
    output_root=None,
    storage_root=None,
    image_size=DEFAULT_HEATMAP_SIZE,
    max_layers=5,
):
    planet = planet if isinstance(planet, dict) else {}
    terrain = terrain if isinstance(terrain, dict) else {}
    heightmap = heightmap if isinstance(heightmap, dict) else {}
    rows = _rows_from_heightmap(heightmap)
    materials = _select_material_layers(natural_material_model, max_layers=max_layers)
    if not rows or not materials:
        return {
            "status": "unavailable",
            "model_version": MATERIAL_HEATMAP_MODEL_VERSION,
            "reason": "heightmap_or_materials_missing",
            "layers": [],
        }

    output_root = Path(output_root or Path(__file__).resolve().parents[2] / "assets" / "maps" / "material_heatmaps")
    storage_root = Path(storage_root).resolve() if storage_root is not None else output_root.parents[2]
    planet_id = str(planet.get("id") or heightmap.get("planet_id") or "planet")
    bundle_path = output_root / f"{_safe_slug(planet_id)}{RASTER_BUNDLE_EXTENSION}"

    width, height = image_size
    width = max(8, int(width or DEFAULT_HEATMAP_SIZE[0]))
    height = max(4, int(height or DEFAULT_HEATMAP_SIZE[1]))
    map_seed = str(heightmap.get("map_seed") or terrain.get("map_seed") or resolved_map_seed(planet.get("world_gen_seed"), planet_id=planet_id))
    min_elevation = float(heightmap.get("min_elevation_m", -4000.0) or -4000.0)
    max_elevation = float(heightmap.get("max_elevation_m", 4000.0) or 4000.0)
    span = max(1.0, max_elevation - min_elevation)
    sea_level = heightmap.get("sea_level_m")
    sea_level = None if sea_level is None else float(sea_level or 0.0)
    hydrology = terrain.get("hydrology") if isinstance(terrain.get("hydrology"), dict) else {}
    hydrology_strength = _clamp(float(hydrology.get("target_ocean_fraction", 0.0) or 0.0) + (0.25 if hydrology.get("cycle") in {"active", "limited"} else 0.0))
    planet_tags = set((natural_material_model or {}).get("planet_tags") or [])

    layer_pixels = []
    layer_metadata = []
    bundle_layers = []
    for material in materials:
        material_id = str(material.get("material_id"))
        color = material_display_color(material_id, material.get("display_color"))
        confidence = _clamp(float(material.get("confidence", 0.45) or 0.45), 0.05, 1.0)
        pixels = []
        surface = pygame.Surface((width, height), pygame.SRCALPHA)
        peak = 0.0
        total = 0.0
        coverage = 0
        sparse_floor = seed_range(map_seed, f"{material_id}:sparse_floor", 0.20, 0.44)
        sparse_ceiling = sparse_floor + seed_range(map_seed, f"{material_id}:sparse_softness", 0.16, 0.30)

        for y in range(height):
            ny = y / max(1, height - 1)
            row = []
            polar = abs(ny - 0.5) * 2.0
            for x in range(width):
                nx = x / max(1, width - 1)
                elevation = _sample_height(rows, nx, ny)
                elevation_norm = _clamp((elevation - min_elevation) / span)
                ocean = 1.0 if sea_level is not None and elevation < sea_level else 0.0
                shoreline = 0.0 if sea_level is None else math.exp(-((abs(elevation - sea_level) / max(1.0, span * 0.085)) ** 2))
                ice = polar if ocean > 0.0 and hydrology.get("target_ice_fraction", 0.0) else 0.0
                noise = _wave_noise(map_seed, material_id, nx, ny)
                region = _regional_material_influence(map_seed, material_id, nx, ny)
                affinity = _material_affinity(
                    material,
                    {
                        "elevation_norm": elevation_norm,
                        "polar": polar,
                        "shoreline": shoreline,
                        "ocean": ocean,
                        "ice": ice,
                        "noise": noise,
                        "hydrology": hydrology_strength,
                        "planet_tags": planet_tags,
                    },
                )
                raw_value = _clamp((affinity * 0.48 + region * 0.62) * confidence)
                value = _smoothstep(sparse_floor, sparse_ceiling, raw_value)
                if ocean and "ice" not in material_id.lower():
                    value *= 0.34
                value = _clamp(value)
                row.append(value)
                peak = max(peak, value)
                total += value
                if value >= 0.18:
                    coverage += 1
                alpha = int(round(value * 230.0))
                surface.set_at((x, y), (color[0], color[1], color[2], alpha))
            pixels.append(row)

        layer_id = f"heatmap_{_safe_slug(material_id)}"
        bundle_layers.append({
            "id": layer_id,
            "role": "material_layer",
            "material_id": material_id,
            "name": material.get("name") or material_id,
            "surface": surface,
            "display_color": color,
            "confidence": round(confidence, 3),
        })
        layer_pixels.append({"material_id": material_id, "pixels": pixels, "color": color, "confidence": confidence})
        layer_metadata.append({
            "id": layer_id,
            "material_id": material_id,
            "name": material.get("name") or material_id,
            "bundle_path": _relative_or_absolute(bundle_path, storage_root=storage_root),
            "bundle_layer_id": layer_id,
            "display_color": color,
            "confidence": round(confidence, 3),
            "peak_intensity": round(peak, 3),
            "mean_intensity": round(total / max(1, width * height), 3),
            "coverage_fraction": round(coverage / max(1, width * height), 3),
            "dominance_threshold": round(sparse_floor, 3),
            "confidence_state": "inferred",
            "truth_state": "generated",
        })

    composite = pygame.Surface((width, height), pygame.SRCALPHA)
    for y in range(height):
        for x in range(width):
            candidates = []
            for layer in layer_pixels:
                value = layer["pixels"][y][x] * layer["confidence"]
                if value <= 0.0:
                    continue
                candidates.append((value, layer))
            candidates.sort(key=lambda item: item[0], reverse=True)
            if not candidates or candidates[0][0] < 0.035:
                composite.set_at((x, y), (36, 34, 30, 0))
            else:
                best_score, best_layer = candidates[0]
                color = list(best_layer["color"])
                if len(candidates) > 1 and candidates[1][0] > best_score * 0.68:
                    second_score, second_layer = candidates[1]
                    blend = _clamp((second_score / max(0.001, best_score) - 0.68) / 0.32) * 0.28
                    second_color = second_layer["color"]
                    color = [
                        color[index] * (1.0 - blend) + second_color[index] * blend
                        for index in range(3)
                    ]
                alpha = int(round(112 + _clamp(best_score) * 136))
                composite.set_at((
                    x,
                    y,
                ), (
                    max(0, min(255, int(color[0]))),
                    max(0, min(255, int(color[1]))),
                    max(0, min(255, int(color[2]))),
                    alpha,
                ))

    composite_layer_id = "composite"
    bundle_layers.insert(0, {
        "id": composite_layer_id,
        "role": "composite",
        "name": "Composite Material Heatmap",
        "surface": composite,
        "render_mode": "dominant_material_color",
    })
    manifest = _write_raster_bundle(
        bundle_path,
        width,
        height,
        bundle_layers,
        metadata={
            "kind": "material_heatmap",
            "planet_id": planet_id,
            "map_seed": map_seed,
            "projection": heightmap.get("projection", "equirectangular"),
        },
    )
    composite_layer = {
        "id": "heatmap_composite_materials",
        "name": "Composite Material Heatmap",
        "bundle_path": _relative_or_absolute(bundle_path, storage_root=storage_root),
        "bundle_layer_id": composite_layer_id,
        "render_mode": "dominant_material_color",
        "confidence_state": "inferred",
        "truth_state": "generated",
    }

    return {
        "status": "generated",
        "model_version": MATERIAL_HEATMAP_MODEL_VERSION,
        "projection": heightmap.get("projection", "equirectangular"),
        "map_seed": map_seed,
        "planet_id": planet_id,
        "storage_format": RASTER_BUNDLE_FORMAT,
        "bundle_format_version": RASTER_BUNDLE_VERSION,
        "bundle_path": _relative_or_absolute(bundle_path, storage_root=storage_root),
        "image_format": "rgba8888_bundle",
        "width_px": width,
        "height_px": height,
        "wrap_x": bool(heightmap.get("wrap_x", True)),
        "wrap_y": bool(heightmap.get("wrap_y", False)),
        "truth_model": "deterministic_generated_truth",
        "distribution_mode": "sparse_dominant_regions",
        "default_confidence_state": "inferred",
        "composite_layer": composite_layer,
        "layers": layer_metadata,
        "bundle_manifest": {
            "layer_count": len(manifest.get("layers") or []),
            "encoding": manifest.get("encoding"),
        },
    }
