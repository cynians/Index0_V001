import json
import math
import re
import zipfile
from pathlib import Path

import pygame

from simulations.world_gen.map_seed import resolved_map_seed, seed_range
from simulations.world_gen.material_affinities import (
    material_affinity_profile,
    material_affinity_score,
)
from simulations.world_gen.natural_materials import (
    material_display_color,
    material_surface_phase_profile,
    material_surface_phase_stability,
)


MATERIAL_HEATMAP_MODEL_VERSION = "material-heatmaps-v8"
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


def _local_surface_temperature_k(atmosphere, water_cycle, elevation_m, nx, ny):
    """Use simulated climate where available, otherwise a terrain-aware proxy."""
    water_cycle = water_cycle if isinstance(water_cycle, dict) else {}
    climate_grid = water_cycle.get("climate_grid") if isinstance(water_cycle.get("climate_grid"), dict) else {}
    temperature_rows = climate_grid.get("temperature_rows_k") if isinstance(climate_grid.get("temperature_rows_k"), list) else []
    if temperature_rows:
        sampled = _sample_height(temperature_rows, nx, ny)
        if sampled > 0.0:
            return sampled
    atmosphere = atmosphere if isinstance(atmosphere, dict) else {}
    try:
        mean_temperature = float(
            atmosphere.get("estimated_surface_temperature_k", atmosphere.get("equilibrium_temperature_k", 250.0)) or 250.0
        )
    except (TypeError, ValueError):
        mean_temperature = 250.0
    polar = abs(ny - 0.5) * 2.0
    return max(20.0, mean_temperature + 12.0 - polar * 48.0 - max(0.0, float(elevation_m or 0.0)) * 0.0062)


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


def _local_slope_index(rows, nx, ny, relief_span):
    if not rows or len(rows) < 2 or len(rows[0]) < 2:
        return 0.0
    row_count = len(rows)
    col_count = min(len(row) for row in rows)
    dx = 1.0 / max(1, col_count - 1)
    dy = 1.0 / max(1, row_count - 1)
    west = _sample_height(rows, (nx - dx) % 1.0, ny)
    east = _sample_height(rows, (nx + dx) % 1.0, ny)
    north = _sample_height(rows, nx, max(0.0, ny - dy))
    south = _sample_height(rows, nx, min(1.0, ny + dy))
    local_relief = max(abs(east - west), abs(south - north))
    return _clamp(local_relief / max(1.0, float(relief_span or 1.0)) * 10.0)


def _resurfacing_influence(map_seed, terrain, nx, ny):
    """Deterministic rift and resurfacing belts for volcanic surface products."""
    terrain = terrain if isinstance(terrain, dict) else {}
    style = str(terrain.get("surface_regime") or terrain.get("geologic_style") or "").lower()
    if not any(token in style for token in ("rift", "volcanic", "heat_pipe", "sulfur")):
        return 0.0
    signal = 0.0
    for index in range(3):
        center = seed_range(map_seed, f"resurfacing_rift:{index}:center", 0.14, 0.86)
        slope = seed_range(map_seed, f"resurfacing_rift:{index}:slope", -0.46, 0.46)
        waviness = seed_range(map_seed, f"resurfacing_rift:{index}:waviness", 0.018, 0.065)
        phase = seed_range(map_seed, f"resurfacing_rift:{index}:phase", 0.0, math.tau)
        width = seed_range(map_seed, f"resurfacing_rift:{index}:width", 0.018, 0.052)
        center_y = (center + slope * (nx - 0.5) + math.sin(nx * math.tau * 1.7 + phase) * waviness) % 1.0
        distance = _wrapped_distance(ny, center_y)
        signal = max(signal, math.exp(-((distance / max(0.005, width)) ** 2)))
    return _clamp(signal)


def _crater_material_fields(crater_model, width, height):
    """Rasterize actual crater rims and ejecta for impact-derived materials."""
    empty = [[0.0 for _x in range(width)] for _y in range(height)]
    crater_model = crater_model if isinstance(crater_model, dict) else {}
    craters = crater_model.get("craters") or []
    radius_m = max(1.0, float(crater_model.get("radius_m", 1.0) or 1.0))
    if not craters or width < 2 or height < 2:
        return {"breccia": empty}

    breccia = [[0.0 for _x in range(width)] for _y in range(height)]
    for crater in craters:
        try:
            center_x = float(crater.get("x", 0.0) or 0.0) % 1.0
            center_y = _clamp(float(crater.get("y", 0.5) or 0.5), 0.0, 1.0)
            angular_radius = max(1e-5, float(crater.get("diameter_km", 1.0) or 1.0) * 500.0 / radius_m)
        except (TypeError, ValueError):
            continue
        # Ejecta blankets extend beyond the rim.  Account for longitude
        # convergence by making the horizontal sampling window wider at high
        # latitude, then use spherical distance for the final test.
        center_latitude = (0.5 - center_y) * math.pi
        span_x = max(2, int(math.ceil(angular_radius * 2.15 / math.tau * width / max(0.12, abs(math.cos(center_latitude))))))
        span_y = max(2, int(math.ceil(angular_radius * 2.15 / math.pi * height)))
        center_ix = int(round(center_x * (width - 1)))
        center_iy = int(round(center_y * (height - 1)))
        for y_index in range(max(0, center_iy - span_y), min(height, center_iy + span_y + 1)):
            ny = y_index / max(1, height - 1)
            latitude = (0.5 - ny) * math.pi
            for x_offset in range(-span_x, span_x + 1):
                x_index = (center_ix + x_offset) % width
                nx = x_index / max(1, width - 1)
                delta_latitude = latitude - center_latitude
                delta_longitude = _wrapped_distance(nx, center_x) * math.tau
                angular_distance = math.hypot(
                    delta_latitude,
                    math.cos((latitude + center_latitude) * 0.5) * delta_longitude,
                )
                normalized_distance = angular_distance / angular_radius
                if normalized_distance > 2.15:
                    continue
                rim = math.exp(-(((normalized_distance - 1.0) / 0.13) ** 2))
                ejecta = math.exp(-max(0.0, normalized_distance - 1.0) / 0.36) if normalized_distance >= 1.0 else 0.0
                fractured_floor = max(0.0, 1.0 - normalized_distance) * 0.18
                breccia[y_index][x_index] = max(
                    breccia[y_index][x_index],
                    _clamp(rim * 0.92 + ejecta * 0.72 + fractured_floor),
                )
    return {"breccia": breccia}


def _select_material_layers(natural_material_model, max_layers=7):
    model = natural_material_model if isinstance(natural_material_model, dict) else {}
    candidates = [
        item
        for item in model.get("likely_materials") or []
        if (
            isinstance(item, dict)
            and item.get("material_id")
            and int(item.get("minimum_map_detail_level", 0) or 0) <= 0
        )
    ]
    candidates.sort(key=lambda item: (
        -float(item.get("confidence", 0.0) or 0.0),
        str(item.get("name") or ""),
    ))
    limit = max(1, int(max_layers or 1))
    subclass_caps = {
        "ice": 2,
        "regolith": 2,
        "sediment": 2,
        "rock": 3,
        "mineral": 2,
    }
    foundational_profiles = {
        "felsic_bedrock",
        "mafic_bedrock",
        "ultramafic_bedrock",
        "intermediate_volcanic",
        "felsic_volcanic",
    }
    foundational_bedrock = next(
        (
            item
            for item in candidates
            if (
                item.get("foundational_lithology")
                or (
                    (material_affinity_profile(item.get("material_id")) or {}).get(
                        "profile_id"
                    )
                    in foundational_profiles
                )
            )
        ),
        None,
    )
    selected = [foundational_bedrock] if foundational_bedrock else []
    subclass_counts = {}
    if foundational_bedrock:
        subclass = str(
            foundational_bedrock.get("material_subclass") or ""
        ).lower()
        subclass_counts[subclass] = 1
        if len(selected) >= limit:
            return selected
    for item in candidates:
        if item is foundational_bedrock:
            continue
        subclass = str(item.get("material_subclass") or "").lower()
        if subclass_counts.get(subclass, 0) >= subclass_caps.get(subclass, 2):
            continue
        selected.append(item)
        subclass_counts[subclass] = subclass_counts.get(subclass, 0) + 1
        if len(selected) >= limit:
            return selected
    return selected


def generate_material_heatmap_model(
    planet,
    natural_material_model,
    terrain,
    heightmap,
    atmosphere=None,
    water_cycle=None,
    output_root=None,
    storage_root=None,
    image_size=DEFAULT_HEATMAP_SIZE,
    max_layers=5,
):
    planet = planet if isinstance(planet, dict) else {}
    terrain = terrain if isinstance(terrain, dict) else {}
    heightmap = heightmap if isinstance(heightmap, dict) else {}
    atmosphere = atmosphere if isinstance(atmosphere, dict) else planet.get("atmosphere_model") or {}
    water_cycle = water_cycle if isinstance(water_cycle, dict) else planet.get("water_cycle_model") or {}
    rows = _rows_from_heightmap(heightmap)
    materials = _select_material_layers(
        natural_material_model,
        max_layers=max(max_layers, int(max_layers or 1) * 2),
    )
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
    active_hydrology = bool(hydrology.get("liquid_water_possible")) and float(
        atmosphere.get("surface_pressure_bar", 0.0) or 0.0
    ) >= 0.006
    planet_tags = set((natural_material_model or {}).get("planet_tags") or [])
    active_volcanism = "active_volcanism" in planet_tags
    wet_oxidizing_surface = (
        "active_hydrology" in planet_tags
        and "oxidizing_surface" in planet_tags
    )
    crater_fields = _crater_material_fields(planet.get("crater_model"), width, height)
    climate_grid = water_cycle.get("climate_grid") if isinstance(water_cycle.get("climate_grid"), dict) else {}
    seasonal_min_temperature_rows = climate_grid.get("seasonal_min_temperature_rows_k") if isinstance(climate_grid.get("seasonal_min_temperature_rows_k"), list) else []
    precipitation_rows = climate_grid.get("annual_precipitation_rows_mm") if isinstance(climate_grid.get("annual_precipitation_rows_mm"), list) else []
    runoff_rows = climate_grid.get("annual_runoff_rows_mm") if isinstance(climate_grid.get("annual_runoff_rows_mm"), list) else []
    surface_evolution = planet.get("surface_evolution_model") if isinstance(planet.get("surface_evolution_model"), dict) else {}
    climate_regulation = planet.get("climate_regulation_model") if isinstance(planet.get("climate_regulation_model"), dict) else {}
    carbonate_favorable = 1.0 if climate_regulation.get("carbonate_province_favorable") else 0.38
    process_grid = surface_evolution.get("process_grid") if isinstance(surface_evolution.get("process_grid"), dict) else {}
    deposition_rows = process_grid.get("sediment_deposition_rows") if isinstance(process_grid.get("sediment_deposition_rows"), list) else []
    aeolian_rows = process_grid.get("aeolian_transport_rows") if isinstance(process_grid.get("aeolian_transport_rows"), list) else []
    weathering_rows = process_grid.get("chemical_weathering_rows") if isinstance(process_grid.get("chemical_weathering_rows"), list) else []
    age_rows = process_grid.get("relative_surface_age_rows") if isinstance(process_grid.get("relative_surface_age_rows"), list) else []
    erosion_rows = process_grid.get("erosion_potential_rows") if isinstance(process_grid.get("erosion_potential_rows"), list) else []
    glacial_rows = process_grid.get("glacial_erosion_rows") if isinstance(process_grid.get("glacial_erosion_rows"), list) else []

    layer_pixels = []
    layer_metadata = []
    bundle_layers = []
    for material in materials:
        material_id = str(material.get("material_id"))
        color = material_display_color(material_id, material.get("display_color"))
        confidence = _clamp(float(material.get("confidence", 0.45) or 0.45), 0.05, 1.0)
        affinity_profile = material_affinity_profile(material_id)
        if affinity_profile is None:
            continue
        foundational_bedrock = bool(material.get("foundational_lithology")) or (
            affinity_profile.get("profile_id") in {
                "felsic_bedrock",
                "mafic_bedrock",
                "ultramafic_bedrock",
                "intermediate_volcanic",
                "felsic_volcanic",
            }
        )
        regionality = _clamp(affinity_profile.get("regionality", 0.35))
        abundance = _clamp(affinity_profile.get("abundance", 1.0))
        phase_profile = material_surface_phase_profile(material_id, atmosphere=atmosphere)
        pixels = []
        surface = pygame.Surface((width, height), pygame.SRCALPHA)
        peak = 0.0
        total = 0.0
        coverage = 0
        sparse_floor = seed_range(map_seed, f"{material_id}:sparse_floor", 0.20, 0.44)
        sparse_floor = _clamp(sparse_floor + (1.0 - abundance) * 0.06, 0.0, 0.68)
        sparse_ceiling = sparse_floor + seed_range(map_seed, f"{material_id}:sparse_softness", 0.16, 0.30)

        for y in range(height):
            ny = y / max(1, height - 1)
            row = []
            polar = abs(ny - 0.5) * 2.0
            for x in range(width):
                nx = x / max(1, width - 1)
                elevation = _sample_height(rows, nx, ny)
                local_temperature_k = _local_surface_temperature_k(
                    atmosphere, water_cycle, elevation, nx, ny,
                )
                phase_temperature_k = local_temperature_k
                frost_duty_cycle = 1.0
                if phase_profile.get("phase") in {"water_frost", "carbon_dioxide_frost"} and seasonal_min_temperature_rows:
                    seasonal_minimum_k = _sample_height(seasonal_min_temperature_rows, nx, ny)
                    if seasonal_minimum_k > 0.0:
                        phase_temperature_k = seasonal_minimum_k
                        transition_k = phase_profile.get("transition_temperature_k")
                        try:
                            transition_k = float(transition_k)
                        except (TypeError, ValueError):
                            transition_k = None
                        if transition_k is not None and local_temperature_k > seasonal_minimum_k:
                            frost_duty_cycle = _clamp(
                                (transition_k - seasonal_minimum_k) / (local_temperature_k - seasonal_minimum_k)
                            )
                phase_stability = material_surface_phase_stability(
                    material_id,
                    phase_temperature_k,
                    profile=phase_profile,
                )
                elevation_norm = _clamp((elevation - min_elevation) / span)
                ocean = 1.0 if sea_level is not None and elevation < sea_level else 0.0
                shoreline = 0.0 if sea_level is None else math.exp(-((abs(elevation - sea_level) / max(1.0, span * 0.085)) ** 2))
                ice = polar if ocean > 0.0 and hydrology.get("target_ice_fraction", 0.0) else 0.0
                noise = _wave_noise(map_seed, material_id, nx, ny)
                region = _regional_material_influence(map_seed, material_id, nx, ny)
                resurfacing = _resurfacing_influence(map_seed, terrain, nx, ny)
                impact_breccia = crater_fields["breccia"][y][x]
                slope = _local_slope_index(rows, nx, ny, span)
                precipitation_mm = (
                    max(0.0, _sample_height(precipitation_rows, nx, ny))
                    if precipitation_rows
                    else max(0.0, 120.0 + hydrology_strength * 1900.0 * (1.0 - polar * 0.72))
                )
                humidity = _clamp(precipitation_mm / 1800.0)
                aridity = _clamp(1.0 - precipitation_mm / 700.0)
                runoff_mm = max(0.0, _sample_height(runoff_rows, nx, ny)) if runoff_rows else 0.0
                drainage = (
                    _clamp(runoff_mm / (runoff_mm + 240.0))
                    if runoff_rows
                    else _clamp(hydrology_strength * (0.18 + slope * 0.62))
                )
                weathering = (
                    _clamp(_sample_height(weathering_rows, nx, ny))
                    if weathering_rows
                    else _clamp(
                        hydrology_strength
                        * humidity
                        * math.exp(-((local_temperature_k - 296.0) / 34.0) ** 2)
                        * (0.28 + slope * 0.50)
                    )
                )
                deposition = _clamp(_sample_height(deposition_rows, nx, ny)) if deposition_rows else _clamp(drainage * (1.0 - slope))
                aeolian = _clamp(_sample_height(aeolian_rows, nx, ny)) if aeolian_rows else _clamp(aridity * (0.22 + slope * 0.35))
                erosion = _clamp(_sample_height(erosion_rows, nx, ny)) if erosion_rows else _clamp(slope * (0.35 + drainage * 0.65))
                glacial = _clamp(_sample_height(glacial_rows, nx, ny)) if glacial_rows else _clamp(ice * polar)
                age = _clamp(_sample_height(age_rows, nx, ny)) if age_rows else _clamp(0.72 - erosion * 0.42 - resurfacing * 0.28)
                affinity_context = {
                    "temperature_k": local_temperature_k,
                    "precipitation_mm": precipitation_mm,
                    "land": 1.0 - ocean,
                    "ocean": ocean,
                    "elevation": elevation_norm,
                    "highland": elevation_norm,
                    "lowland": 1.0 - elevation_norm,
                    "slope": slope,
                    "low_slope": 1.0 - slope,
                    "polar": polar,
                    "shoreline": shoreline,
                    "ice": ice,
                    "humidity": humidity,
                    "aridity": aridity,
                    "drainage": drainage,
                    "weathering": weathering,
                    "deposition": deposition,
                    "aeolian": aeolian,
                    "erosion": erosion,
                    "glacial": glacial,
                    "age": age,
                    "volcanic": 1.0 if "volcanic_surface" in planet_tags or "basaltic_surface" in planet_tags else 0.0,
                    "resurfacing": resurfacing,
                    "impact": impact_breccia,
                    "carbonate": carbonate_favorable,
                    "regional": region,
                    "noise": noise,
                    "wet_oxidizing_surface": wet_oxidizing_surface,
                    "active_hydrology": active_hydrology,
                    "active_volcanism": active_volcanism,
                }
                affinity = material_affinity_score(material_id, affinity_context)
                material_text = f"{material_id} {material.get('name') or ''}".lower()
                if "impact" in material_text or "breccia" in material_text:
                    # Breccia follows the actual retained crater population;
                    # do not let generic regional noise paint it between
                    # impacts.
                    raw_value = _clamp((affinity * 0.96 + noise * 0.04) * confidence)
                else:
                    raw_value = _clamp(
                        (
                            affinity * (0.82 - regionality * 0.24)
                            + region * (0.16 + regionality * 0.30)
                            + noise * 0.02
                        )
                        * confidence
                        * (0.65 + abundance * 0.35)
                    )
                raw_value *= float(phase_stability["stability"]) * frost_duty_cycle
                value = _smoothstep(sparse_floor, sparse_ceiling, raw_value)
                if foundational_bedrock and ocean < 0.5 and affinity > 0.0:
                    value = max(value, min(0.08, 0.012 + affinity * 0.045))
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
            "material_subclass": material.get("material_subclass"),
            "surface": surface,
            "display_color": color,
            "confidence": round(confidence, 3),
            "phase_profile": phase_profile,
        })
        layer_pixels.append({"material_id": material_id, "pixels": pixels, "color": color, "confidence": confidence})
        layer_metadata.append({
            "id": layer_id,
            "material_id": material_id,
            "name": material.get("name") or material_id,
            "material_subclass": material.get("material_subclass"),
            "bundle_path": _relative_or_absolute(bundle_path, storage_root=storage_root),
            "bundle_layer_id": layer_id,
            "display_color": color,
            "confidence": round(confidence, 3),
            "affinity_profile": affinity_profile.get("profile_id"),
            "climatic_topographic_affinity": {
                key: value
                for key, value in affinity_profile.items()
                if key != "weights"
            },
            "affinity_weights": affinity_profile.get("weights"),
            "phase": phase_profile.get("phase"),
            "phase_transition_temperature_k": phase_profile.get("transition_temperature_k"),
            "peak_intensity": round(peak, 3),
            "mean_intensity": round(total / max(1, width * height), 3),
            "coverage_fraction": round(coverage / max(1, width * height), 3),
            "dominance_threshold": round(sparse_floor, 3),
            "confidence_state": "inferred",
            "truth_state": "generated",
        })

    usable_indices = [
        index
        for index, metadata in enumerate(layer_metadata)
        if float(metadata.get("coverage_fraction", 0.0) or 0.0) > 0.0
    ][:max(1, int(max_layers or 1))]
    usable_has_bedrock = any(
        str(layer_metadata[index].get("material_subclass") or "") == "rock"
        for index in usable_indices
    )
    if not usable_has_bedrock:
        bedrock_index = next(
            (
                index
                for index, metadata in enumerate(layer_metadata)
                if (
                    str(metadata.get("material_subclass") or "") == "rock"
                    and float(metadata.get("peak_intensity", 0.0) or 0.0) > 0.0
                )
            ),
            None,
        )
        if bedrock_index is not None:
            if len(usable_indices) >= max(1, int(max_layers or 1)):
                usable_indices.pop()
            usable_indices.append(bedrock_index)
    if not usable_indices and layer_metadata:
        usable_indices = [
            max(
                range(len(layer_metadata)),
                key=lambda index: float(
                    layer_metadata[index].get("peak_intensity", 0.0) or 0.0
                ),
            )
        ]
    bundle_layers = [bundle_layers[index] for index in usable_indices]
    layer_pixels = [layer_pixels[index] for index in usable_indices]
    layer_metadata = [layer_metadata[index] for index in usable_indices]

    composite = pygame.Surface((width, height), pygame.SRCALPHA)
    dominant_counts = {
        str(layer.get("material_id") or ""): 0
        for layer in layer_pixels
    }
    for y in range(height):
        for x in range(width):
            candidates = []
            for layer in layer_pixels:
                value = layer["pixels"][y][x] * layer["confidence"]
                if value <= 0.0:
                    continue
                candidates.append((value, layer))
            candidates.sort(key=lambda item: item[0], reverse=True)
            if not candidates:
                composite.set_at((x, y), (36, 34, 30, 0))
            else:
                best_score, best_layer = candidates[0]
                dominant_counts[str(best_layer.get("material_id") or "")] += 1
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

    for metadata in layer_metadata:
        material_id = str(metadata.get("material_id") or "")
        metadata["suitability_coverage_fraction"] = metadata.get(
            "coverage_fraction",
            0.0,
        )
        metadata["coverage_fraction"] = round(
            dominant_counts.get(material_id, 0) / max(1, width * height),
            3,
        )

    dominant_indices = [
        index
        for index, metadata in enumerate(layer_metadata)
        if float(metadata.get("coverage_fraction", 0.0) or 0.0) > 0.0
    ]
    bundle_layers = [bundle_layers[index] for index in dominant_indices]
    layer_pixels = [layer_pixels[index] for index in dominant_indices]
    layer_metadata = [layer_metadata[index] for index in dominant_indices]

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
