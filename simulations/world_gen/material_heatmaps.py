"""Generate material projections from ontology-authored material facts.

Architecture invariants: the ontology owns entities, colors, formation rules,
and other semantic facts; module-level lookups are disposable caches. Current
generated planets are disposable and obsolete model versions are regenerated,
not translated by legacy compatibility paths.
"""

import hashlib
import json
import math
import os
import re
import zipfile
from functools import lru_cache
from pathlib import Path

import pygame

from simulations.world_gen.map_seed import resolved_map_seed, seed_range
from simulations.world_gen.material_affinities import (
    material_affinity_profile,
    material_affinity_score,
    material_distribution_role,
)
from simulations.world_gen.material_formation import (
    formation_contract,
    formation_suitability,
)
from simulations.world_gen.natural_materials import (
    material_display_color,
    material_geological_map_color,
    material_surface_phase_profile,
    material_surface_phase_stability,
)
from simulations.world_gen.material_optics import material_optical_surface_profile
from simulations.world_gen.storage_policy import utc_timestamp
from simulations.world_gen.surface_geomorphology import (
    derive_surface_material_partition_fields,
)


MATERIAL_HEATMAP_MODEL_VERSION = "material-heatmaps-v21-ontology-cartography"
RASTER_BUNDLE_FORMAT = "index0_raster_bundle"
RASTER_BUNDLE_VERSION = 1
RASTER_BUNDLE_EXTENSION = ".i0r"
DEFAULT_HEATMAP_SIZE = (256, 128)
# A differentiated terrestrial crust needs enough planetary-scale lithologies
# to express shields, arcs, flood basalts and sedimentary basins.  This is a
# catalogue/output limit, not the number mixed at one pixel; the lithologic
# partition below normally exposes one substrate and only blends a second at
# a geological contact.
DEFAULT_MATERIAL_LAYER_LIMIT = 18


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, float(value)))


def _smoothstep(edge0, edge1, value):
    if edge1 <= edge0:
        return 1.0 if value >= edge1 else 0.0
    t = _clamp((value - edge0) / (edge1 - edge0))
    return t * t * (3.0 - 2.0 * t)


def _relax_native_material_field(
    rows,
    ocean_mask,
    *,
    passes=3,
    strength=0.42,
    wrap_x=False,
):
    """Give planetary material suitability a finite geographic footprint.

    This operates before the raster is enlarged by the map renderer.  It
    therefore removes native material-grid panels instead of merely blurring
    their already-upscaled edges.  Land and ocean are relaxed independently
    so substrate does not bleed across coastlines.
    """
    if not rows or len(rows) < 2 or len(rows[0]) < 2:
        return rows
    height = min(len(rows), len(ocean_mask or rows))
    width = min(
        min(len(row) for row in rows[:height]),
        min(len(row) for row in (ocean_mask or rows)[:height]),
    )
    values = [[float(value) for value in row[:width]] for row in rows[:height]]
    masks = [
        [bool(value) for value in row[:width]]
        for row in (ocean_mask or [[False] * width for _ in range(height)])[:height]
    ]
    unique_width = width - 1 if wrap_x and width > 2 else width
    amount = _clamp(strength, 0.0, 0.49)
    for _pass in range(max(1, int(passes or 1))):
        source = values
        target = [row[:] for row in source]
        for y in range(height):
            north = max(0, y - 1)
            south = min(height - 1, y + 1)
            for x in range(unique_width):
                same_surface = masks[y][x]
                neighbors = []
                for nx, ny in (
                    ((x - 1) % unique_width, y),
                    ((x + 1) % unique_width, y),
                    (x, north),
                    (x, south),
                ):
                    if masks[ny][nx] == same_surface:
                        neighbors.append(source[ny][nx])
                if neighbors:
                    local_mean = sum(neighbors) / len(neighbors)
                    target[y][x] = (
                        source[y][x] * (1.0 - amount)
                        + local_mean * amount
                    )
            if wrap_x and width > unique_width:
                target[y][-1] = target[y][0]
        values = target
    return values


def _safe_slug(value):
    original = str(value or "material")
    text = re.sub(r"[^0-9A-Za-z_]+", "_", original).strip("_").lower()
    text = text or "material"
    if len(text) > 72:
        digest = hashlib.sha1(original.encode("utf-8")).hexdigest()[:12]
        text = f"{text[:56].rstrip('_')}_{digest}"
    return text


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
    temporary = bundle_path.with_name(f".{bundle_path.name}.tmp-{os.getpid()}")
    layer_payloads = []
    for layer in layers:
        layer_id = _safe_slug(layer.get("id") or layer.get("material_id") or layer.get("name") or "layer")
        entry_name = f"layers/{layer_id}.rgba"
        surface = layer.get("surface")
        if surface is None:
            continue
        rgba = _surface_to_rgba_bytes(surface)
        layer_meta = {
            key: value
            for key, value in layer.items()
            if key not in {"surface", "pixels"}
        }
        layer_meta.update({
            "id": layer_id,
            "rgba_path": entry_name,
            "width_px": width,
            "height_px": height,
            "sha256": hashlib.sha256(rgba).hexdigest(),
        })
        manifest_layers.append(layer_meta)
        layer_payloads.append((entry_name, rgba))

    manifest_metadata = dict(metadata or {})
    manifest_metadata.setdefault("created_at_utc", utc_timestamp())
    manifest = {
        "format": RASTER_BUNDLE_FORMAT,
        "format_version": RASTER_BUNDLE_VERSION,
        "width_px": width,
        "height_px": height,
        "encoding": "rgba8888",
        "layers": manifest_layers,
        "metadata": manifest_metadata,
    }
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for entry_name, rgba in layer_payloads:
                bundle.writestr(entry_name, rgba)
            bundle.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True))
        with zipfile.ZipFile(temporary, "r") as bundle:
            written = json.loads(bundle.read("manifest.json").decode("utf-8"))
            if written.get("format") != RASTER_BUNDLE_FORMAT:
                raise ValueError("Raster bundle manifest validation failed")
            for layer in written.get("layers") or []:
                rgba = bundle.read(layer["rgba_path"])
                if hashlib.sha256(rgba).hexdigest() != layer.get("sha256"):
                    raise ValueError(f"Raster bundle layer validation failed: {layer.get('id')}")
        os.replace(temporary, bundle_path)
    finally:
        if temporary.exists():
            temporary.unlink()
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
    row_count, col_count = _grid_dimensions(rows)
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


_GRID_DIMENSION_CACHE = {}


def _grid_dimensions(rows):
    """Cache immutable generated-grid dimensions used by every pixel sample."""
    if not rows:
        return 0, 0
    key = id(rows)
    cached = _GRID_DIMENSION_CACHE.get(key)
    if cached is not None and cached[0] is rows:
        return cached[1], cached[2]
    row_count = len(rows)
    col_count = min(len(row) for row in rows)
    if len(_GRID_DIMENSION_CACHE) >= 64:
        _GRID_DIMENSION_CACHE.clear()
    _GRID_DIMENSION_CACHE[key] = (rows, row_count, col_count)
    return row_count, col_count


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


def _wave_noise_constants(map_seed, material_id):
    """Seeded wave parameters are immutable for a material-map run."""
    return {
        "freq_a": seed_range(map_seed, f"{material_id}:freq_a", 1.2, 4.8),
        "freq_b": seed_range(map_seed, f"{material_id}:freq_b", 2.0, 7.4),
        "phase_a": seed_range(map_seed, f"{material_id}:phase_a", 0.0, math.tau),
        "phase_b": seed_range(map_seed, f"{material_id}:phase_b", 0.0, math.tau),
    }


def _wave_noise(map_seed, material_id, nx, ny, constants=None):
    constants = constants or _wave_noise_constants(map_seed, material_id)
    freq_a = constants["freq_a"]
    freq_b = constants["freq_b"]
    phase_a = constants["phase_a"]
    phase_b = constants["phase_b"]
    signal = (
        math.sin(nx * math.tau * freq_a + ny * 2.6 + phase_a)
        + math.cos((nx + ny * 0.7) * math.tau * freq_b + phase_b)
    ) * 0.5
    return _clamp((signal + 1.0) * 0.5)


def _wrapped_distance(a, b):
    direct = abs(a - b)
    return min(direct, 1.0 - direct)


def _regional_material_constants(map_seed, material_id):
    provinces = [
        {
            "x": seed_range(map_seed, f"{material_id}:province_{index}:x", 0.0, 1.0),
            "y": seed_range(map_seed, f"{material_id}:province_{index}:y", 0.08, 0.92),
            "radius": seed_range(map_seed, f"{material_id}:province_{index}:radius", 0.08, 0.24),
        }
        for index in range(3)
    ]
    return {
        "provinces": provinces,
        "belt_center": seed_range(map_seed, f"{material_id}:belt:center", 0.16, 0.84),
        "belt_slope": seed_range(map_seed, f"{material_id}:belt:slope", -0.55, 0.55),
        "belt_width": seed_range(map_seed, f"{material_id}:belt:width", 0.035, 0.12),
        "cellular_wave": _wave_noise_constants(map_seed, f"{material_id}:regional"),
    }


def _regional_material_influence(map_seed, material_id, nx, ny, constants=None):
    constants = constants or _regional_material_constants(map_seed, material_id)
    blob_signal = 0.0
    for province in constants["provinces"]:
        cx = province["x"]
        cy = province["y"]
        radius = province["radius"]
        dx = _wrapped_distance(nx, cx)
        dy = ny - cy
        distance = math.sqrt(dx * dx + dy * dy)
        blob_signal = max(blob_signal, math.exp(-((distance / max(0.01, radius)) ** 2)))

    belt_center = constants["belt_center"]
    belt_slope = constants["belt_slope"]
    belt_width = constants["belt_width"]
    belt_y = (belt_center + (nx - 0.5) * belt_slope) % 1.0
    belt_distance = _wrapped_distance(ny, belt_y)
    belt_signal = math.exp(-((belt_distance / max(0.01, belt_width)) ** 2))

    cellular = _wave_noise(
        map_seed, f"{material_id}:regional", nx * 0.63 + 0.17,
        ny * 0.71 + 0.09, constants["cellular_wave"],
    )
    return _clamp(blob_signal * 0.56 + belt_signal * 0.28 + cellular * 0.16)


def _sample_plate_owner(tectonic_model, nx, ny):
    """Return the persistent plate owner and plate record at global UV."""
    tectonic_model = tectonic_model if isinstance(tectonic_model, dict) else {}
    plates = [item for item in tectonic_model.get("plates") or [] if isinstance(item, dict)]
    grid = tectonic_model.get("sample_grid") if isinstance(tectonic_model.get("sample_grid"), dict) else {}
    owners = grid.get("owners") if isinstance(grid.get("owners"), list) else []
    owner_index = 0
    if owners and owners[0]:
        grid_height = len(owners)
        grid_width = min(len(row) for row in owners)
        x = int(round((float(nx) % 1.0) * max(1, grid_width - 1))) % grid_width
        y = max(0, min(grid_height - 1, int(round(_clamp(ny) * max(1, grid_height - 1)))))
        try:
            owner_index = int(owners[y][x])
        except (TypeError, ValueError, IndexError):
            owner_index = 0
    elif plates:
        owner_index = min(
            range(len(plates)),
            key=lambda index: math.hypot(
                _wrapped_distance(float(nx) % 1.0, float(plates[index].get("center_x", 0.0) or 0.0)),
                float(ny) - float(plates[index].get("center_y", 0.5) or 0.5),
            ),
        )
    owner_index = max(0, min(len(plates) - 1, owner_index)) if plates else 0
    plate = plates[owner_index] if plates else {}
    return str(plate.get("id") or f"plate_{owner_index:02d}"), plate, owner_index


def _tectonic_lithology_constants(tectonic_model, map_seed):
    """Build stable plate-owned terrane nuclei once per generated map."""
    tectonic_model = tectonic_model if isinstance(tectonic_model, dict) else {}
    plates = tectonic_model.get("plates") if isinstance(tectonic_model.get("plates"), list) else []
    if not plates:
        plates = [{"id": "unresolved_plate", "center_x": 0.5, "center_y": 0.5, "continentality": 0.5}]
    centers_by_plate = {}
    all_centers = []
    for plate_index, plate in enumerate(plates):
        plate_id = str(plate.get("id") or f"plate_{plate_index:02d}")
        plate_x = float(plate.get("center_x", 0.5) or 0.5) % 1.0
        plate_y = _clamp(plate.get("center_y", 0.5))
        continentality = _clamp(plate.get("continentality", 0.5))
        count = 9 if continentality >= 0.42 else 6
        spread_x = 0.30 if continentality >= 0.42 else 0.22
        spread_y = 0.24 if continentality >= 0.42 else 0.18
        centers = []
        for index in range(count):
            center_x = (
                plate_x
                + seed_range(map_seed, f"terrane:{plate_id}:{index}:x", -spread_x, spread_x)
            ) % 1.0
            center_y = _clamp(
                plate_y
                + seed_range(map_seed, f"terrane:{plate_id}:{index}:y", -spread_y, spread_y)
            )
            centers.append((center_x, center_y, index))
            all_centers.append((center_x, center_y, plate_id, index))
        centers_by_plate[plate_id] = tuple(centers)
    return {"centers_by_plate": centers_by_plate, "all_centers": tuple(all_centers)}


def _tectonic_lithology_context(tectonic_model, nx, ny, map_seed, terrane_constants=None):
    """Shared plate/terrane context used by every candidate lithology.

    Older material maps seeded three unrelated blobs for every rock.  Their
    overlap was then averaged into a global beige substrate.  This context is
    categorical at plate scale and continuous inside plate terranes, so all
    rocks compete for the same geologic provinces and the result survives
    regional refinement through global UV coordinates.
    """
    tectonic_model = tectonic_model if isinstance(tectonic_model, dict) else {}
    plate_id, plate, plate_index = _sample_plate_owner(tectonic_model, nx, ny)
    lithosphere = tectonic_model.get("lithosphere_grid") if isinstance(tectonic_model.get("lithosphere_grid"), dict) else {}
    fraction_rows = lithosphere.get("continental_fraction_rows") if isinstance(lithosphere.get("continental_fraction_rows"), list) else []
    continental = _clamp(_sample_height(fraction_rows, nx, ny)) if fraction_rows else _clamp(plate.get("continentality", 0.5))

    province_model = tectonic_model.get("continental_province_model") if isinstance(tectonic_model.get("continental_province_model"), dict) else {}
    craton = 0.0
    for item in province_model.get("cratons") or []:
        dx = _wrapped_distance(nx, float(item.get("center_x", 0.0) or 0.0)) / max(0.01, float(item.get("width", 0.08) or 0.08))
        dy = (ny - float(item.get("center_y", 0.5) or 0.5)) / max(0.01, float(item.get("height", 0.06) or 0.06))
        craton = max(craton, math.exp(-(dx * dx + dy * dy)))
    basin = 0.0
    for item in province_model.get("intracratonic_basins") or []:
        distance = math.hypot(
            _wrapped_distance(nx, float(item.get("center_x", 0.0) or 0.0)),
            ny - float(item.get("center_y", 0.5) or 0.5),
        ) / max(0.01, float(item.get("radius", 0.05) or 0.05))
        basin = max(basin, math.exp(-(distance * distance)))

    constants = (
        terrane_constants
        if isinstance(terrane_constants, dict)
        else _tectonic_lithology_constants(tectonic_model, map_seed)
    )
    centers_by_plate = constants.get("centers_by_plate") or {}
    centers = centers_by_plate.get(plate_id) or centers_by_plate.get("unresolved_plate") or ()
    all_centers = constants.get("all_centers") or tuple(
        (center_x, center_y, source_plate_id, province_id)
        for source_plate_id, source_centers in centers_by_plate.items()
        for center_x, center_y, province_id in source_centers
    )
    distances = sorted(
        (
            math.hypot(
                _wrapped_distance(float(nx) % 1.0, center_x),
                (float(ny) - center_y) * 0.72,
            ),
            int(province_id),
        )
        for center_x, center_y, province_id in centers
    )
    if distances:
        first_distance, province_a = distances[0]
        second_distance, province_b = distances[min(1, len(distances) - 1)]
        # Mix only in a narrow geological contact zone. Far from a terrane
        # boundary, one province is categorical and cannot be averaged beige
        # by every otherwise valid rock on the planet.
        margin = (second_distance - first_distance) / max(
            1e-6, second_distance + first_distance
        )
        blend = 0.5 * (1.0 - _smoothstep(0.015, 0.16, margin))
    else:
        province_a = province_b = 0
        blend = 0.0
    # Lithology may change across plate contacts, but the exposed optical
    # substrate must not jump at the categorical owner raster. Blend several
    # nearby terrane nuclei with radial support in global coordinates. The
    # nearest-two fields remain for compatibility and diagnostics.
    weighted_provinces = []
    for center_x, center_y, source_plate_id, province_id in all_centers:
        distance = math.hypot(
            _wrapped_distance(float(nx) % 1.0, center_x),
            (float(ny) - center_y) * 0.72,
        )
        if distance > 0.34:
            continue
        weight = math.exp(-((distance / 0.145) ** 2))
        if weight > 0.002:
            weighted_provinces.append((weight, source_plate_id, province_id))
    weighted_provinces.sort(reverse=True)
    weighted_provinces = weighted_provinces[:6]
    weight_total = sum(item[0] for item in weighted_provinces)
    if weight_total > 0.0:
        province_weights = [
            (source_plate_id, province_id, weight / weight_total)
            for weight, source_plate_id, province_id in weighted_provinces
        ]
    else:
        province_weights = [(plate_id, province_a, 1.0)]
    return {
        "plate_id": plate_id,
        "plate_index": plate_index,
        "plate_type": str(plate.get("plate_type") or "mixed"),
        "continental_fraction": continental,
        "oceanic_fraction": 1.0 - continental,
        "craton": _clamp(craton),
        "basin": _clamp(basin),
        "province_a": province_a,
        "province_b": province_b,
        "province_blend": blend,
        "province_weights": province_weights,
    }


@lru_cache(maxsize=8192)
def _province_material_preference(map_seed, plate_id, province_id, material_id):
    return seed_range(
        map_seed,
        f"lithology:{plate_id}:{province_id}:{material_id}",
        0.04,
        1.0,
    )


def _lithologic_province_affinity(map_seed, material_id, formation, profile, tectonic_context):
    """Score one rock against a shared plate-bound lithologic province."""
    context = tectonic_context if isinstance(tectonic_context, dict) else {}
    plate_id = str(context.get("plate_id") or "unresolved_plate")
    province_weights = context.get("province_weights") if isinstance(context.get("province_weights"), list) else []
    if province_weights:
        affinity = 0.0
        total_weight = 0.0
        for source_plate_id, province_id, weight in province_weights:
            weight = max(0.0, float(weight or 0.0))
            affinity += _province_material_preference(
                str(map_seed), str(source_plate_id), int(province_id or 0), str(material_id)
            ) * weight
            total_weight += weight
        affinity /= max(1e-9, total_weight)
    else:
        first = _province_material_preference(
            str(map_seed), plate_id, int(context.get("province_a", 0) or 0), str(material_id)
        )
        second = _province_material_preference(
            str(map_seed), plate_id, int(context.get("province_b", 1) or 1), str(material_id)
        )
        blend = _clamp(context.get("province_blend", 0.0))
        affinity = first * (1.0 - blend) + second * blend

    category = str((formation or {}).get("category_id") or "").lower()
    profile_id = str((profile or {}).get("profile_id") or "").lower()
    text = f"{category} {profile_id} {material_id}".lower()
    continental = _clamp(context.get("continental_fraction", 0.5))
    oceanic = 1.0 - continental
    craton = _clamp(context.get("craton", 0.0))
    basin = _clamp(context.get("basin", 0.0))
    if any(token in text for token in ("felsic", "granite", "rhyolite", "arkose")):
        affinity *= 0.42 + continental * 0.72 + craton * 0.34
    elif any(token in text for token in ("mafic", "basalt", "gabbro", "diabase")):
        affinity *= 0.48 + oceanic * 0.66 + (1.0 - craton) * 0.18
    elif any(token in text for token in ("ultramafic", "peridot", "komati", "pyroxen")):
        affinity *= 0.38 + oceanic * 0.52 + (1.0 - continental) * 0.24
    elif any(token in text for token in ("sediment", "carbonate", "limestone", "sandstone", "shale", "chert")):
        affinity *= 0.34 + basin * 0.80 + continental * 0.24
    elif any(token in text for token in ("graphite", "carbonaceous")):
        # When carbon inventory promotes graphite to a foundational
        # lithology it forms broad metamorphic/carbonaceous terranes rather
        # than inheriting the much narrower generic metamorphic exposure
        # penalty used for regional schists and marbles.
        affinity *= 0.82 + continental * 0.32 + craton * 0.16
    elif any(token in text for token in ("metamorph", "gneiss", "schist", "marble", "quartzite")):
        affinity *= 0.48 + continental * 0.48 + craton * 0.22
    return _clamp(affinity)


def _local_slope_index(rows, nx, ny, relief_span):
    if not rows or len(rows) < 2 or len(rows[0]) < 2:
        return 0.0
    row_count, col_count = _grid_dimensions(rows)
    dx = 1.0 / max(1, col_count - 1)
    dy = 1.0 / max(1, row_count - 1)
    west = _sample_height(rows, (nx - dx) % 1.0, ny)
    east = _sample_height(rows, (nx + dx) % 1.0, ny)
    north = _sample_height(rows, nx, max(0.0, ny - dy))
    south = _sample_height(rows, nx, min(1.0, ny + dy))
    local_relief = max(abs(east - west), abs(south - north))
    return _clamp(local_relief / max(1.0, float(relief_span or 1.0)) * 10.0)


def _resurfacing_constants(map_seed, terrain):
    terrain = terrain if isinstance(terrain, dict) else {}
    style = str(terrain.get("surface_regime") or terrain.get("geologic_style") or "").lower()
    if not any(token in style for token in ("rift", "volcanic", "heat_pipe", "sulfur")):
        return None
    return [
        {
            "center": seed_range(map_seed, f"resurfacing_rift:{index}:center", 0.14, 0.86),
            "slope": seed_range(map_seed, f"resurfacing_rift:{index}:slope", -0.46, 0.46),
            "waviness": seed_range(map_seed, f"resurfacing_rift:{index}:waviness", 0.018, 0.065),
            "phase": seed_range(map_seed, f"resurfacing_rift:{index}:phase", 0.0, math.tau),
            "width": seed_range(map_seed, f"resurfacing_rift:{index}:width", 0.018, 0.052),
        }
        for index in range(3)
    ]


def _resurfacing_influence(map_seed, terrain, nx, ny, constants=None):
    """Deterministic rift and resurfacing belts for volcanic surface products."""
    constants = _resurfacing_constants(map_seed, terrain) if constants is None else constants
    if not constants:
        return 0.0
    signal = 0.0
    for rift in constants:
        center = rift["center"]
        slope = rift["slope"]
        waviness = rift["waviness"]
        phase = rift["phase"]
        width = rift["width"]
        center_y = (center + slope * (nx - 0.5) + math.sin(nx * math.tau * 1.7 + phase) * waviness) % 1.0
        distance = _wrapped_distance(ny, center_y)
        signal = max(signal, math.exp(-((distance / max(0.005, width)) ** 2)))
    return _clamp(signal)


def _crater_material_fields(crater_model, width, height):
    """Rasterize actual crater rims and ejecta for impact-derived materials."""
    empty = [[0.0 for _x in range(width)] for _y in range(height)]
    crater_model = crater_model if isinstance(crater_model, dict) else {}
    craters = crater_model.get("craters") or []
    regional_width_m = float(
        crater_model.get("region_width_m", 0.0) or 0.0
    )
    regional_height_m = float(
        crater_model.get("region_height_m", 0.0) or 0.0
    )
    if (
        craters
        and regional_width_m > 0.0
        and regional_height_m > 0.0
        and any(crater.get("diameter_m") is not None for crater in craters)
    ):
        breccia = [[0.0 for _x in range(width)] for _y in range(height)]
        for crater in craters:
            try:
                center_x = _clamp(float(crater.get("x", 0.5) or 0.5))
                center_y = _clamp(float(crater.get("y", 0.5) or 0.5))
                diameter_m = max(
                    0.01, float(crater.get("diameter_m", 0.0) or 0.0)
                )
            except (TypeError, ValueError):
                continue
            radius_u = diameter_m * 0.5 / regional_width_m
            radius_v = diameter_m * 0.5 / regional_height_m
            span_x = max(2, int(math.ceil(radius_u * 2.15 * width)))
            span_y = max(2, int(math.ceil(radius_v * 2.15 * height)))
            center_ix = int(round(center_x * (width - 1)))
            center_iy = int(round(center_y * (height - 1)))
            for y_index in range(
                max(0, center_iy - span_y),
                min(height, center_iy + span_y + 1),
            ):
                ny = y_index / max(1, height - 1)
                for x_index in range(
                    max(0, center_ix - span_x),
                    min(width, center_ix + span_x + 1),
                ):
                    nx = x_index / max(1, width - 1)
                    normalized_distance = math.hypot(
                        (nx - center_x) / max(1e-12, radius_u),
                        (ny - center_y) / max(1e-12, radius_v),
                    )
                    if normalized_distance > 2.15:
                        continue
                    rim = math.exp(
                        -(((normalized_distance - 1.0) / 0.13) ** 2)
                    )
                    ejecta = (
                        math.exp(
                            -max(0.0, normalized_distance - 1.0) / 0.36
                        )
                        if normalized_distance >= 1.0
                        else 0.0
                    )
                    fractured_floor = (
                        max(0.0, 1.0 - normalized_distance) * 0.18
                    )
                    breccia[y_index][x_index] = max(
                        breccia[y_index][x_index],
                        _clamp(
                            rim * 0.92
                            + ejecta * 0.72
                            + fractured_floor
                        ),
                    )
        return {"breccia": breccia}

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


def _select_material_layers(
    natural_material_model,
    max_layers=DEFAULT_MATERIAL_LAYER_LIMIT,
    detail_level=0,
    candidate_pool=False,
):
    model = natural_material_model if isinstance(natural_material_model, dict) else {}
    detail_level = max(0, int(detail_level or 0))

    def effective_detail_level(item):
        if item.get("foundational_lithology"):
            return 0
        profile = material_affinity_profile(item.get("material_id")) or {}
        return max(
            int(item.get("minimum_map_detail_level", 0) or 0),
            int(profile.get("minimum_map_detail_level", 0) or 0),
        )

    candidates = []
    for item in model.get("likely_materials") or []:
        if not isinstance(item, dict) or not item.get("material_id"):
            continue
        item_detail = effective_detail_level(item)
        role = (
            item.get("distribution_role")
            or material_distribution_role(
                item.get("material_id"),
                item.get("material_subclass"),
                item_detail,
            )
        )
        if item_detail > detail_level:
            continue
        if detail_level <= 0 and role not in {"bedrock", "surface_cover"}:
            continue
        candidates.append(item)
    candidates.sort(key=lambda item: (
        0 if effective_detail_level(item) == detail_level else 1,
        -float(
            item.get("prevalence_score", item.get("confidence", 0.0)) or 0.0
        ),
        -float(item.get("confidence", 0.0) or 0.0),
        str(item.get("name") or ""),
    ))
    limit = max(1, int(max_layers or 1))
    if candidate_pool:
        role_caps = {
            "bedrock": 32,
            "surface_cover": 24,
            "local_lithology": 20,
            "mineral_constituent": 24,
            "sparse_deposit": 24,
            "local_material_unit": 20,
        }
    else:
        role_caps = (
            {"bedrock": 9, "surface_cover": 2}
            if detail_level <= 0
            else {
                "bedrock": 4,
                "surface_cover": 2,
                "local_lithology": 4,
                "mineral_constituent": 3,
                "sparse_deposit": 3,
                "local_material_unit": 2,
            }
        )
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
    if candidate_pool:
        selected = [foundational_bedrock] if foundational_bedrock else []
        role_order = (
            ["bedrock", "surface_cover"]
            if detail_level <= 0
            else [
                "bedrock",
                "surface_cover",
                "local_lithology",
                "mineral_constituent",
                "sparse_deposit",
                "local_material_unit",
            ]
        )
        candidates_by_role = {
            role: [
                item
                for item in candidates
                if item is not foundational_bedrock
                and (
                    item.get("distribution_role")
                    or material_distribution_role(
                        item.get("material_id"),
                        item.get("material_subclass"),
                        effective_detail_level(item),
                    )
                )
                == role
            ]
            for role in role_order
        }
        rank = 0
        while len(selected) < limit:
            added = False
            for role in role_order:
                role_candidates = candidates_by_role.get(role) or []
                if rank >= len(role_candidates):
                    continue
                selected.append(role_candidates[rank])
                added = True
                if len(selected) >= limit:
                    break
            if not added:
                break
            rank += 1
        return selected

    selected = [foundational_bedrock] if foundational_bedrock else []
    subclass_counts = {}
    if foundational_bedrock:
        role = foundational_bedrock.get("distribution_role") or "bedrock"
        subclass_counts[role] = 1
        if len(selected) >= limit:
            return selected
    for item in candidates:
        if item is foundational_bedrock:
            continue
        role = item.get("distribution_role") or material_distribution_role(
            item.get("material_id"),
            item.get("material_subclass"),
            effective_detail_level(item),
        )
        if subclass_counts.get(role, 0) >= role_caps.get(role, 2):
            continue
        selected.append(item)
        subclass_counts[role] = subclass_counts.get(role, 0) + 1
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
    surface_geomorphology=None,
    output_root=None,
    storage_root=None,
    image_size=DEFAULT_HEATMAP_SIZE,
    max_layers=DEFAULT_MATERIAL_LAYER_LIMIT,
):
    planet = planet if isinstance(planet, dict) else {}
    terrain = terrain if isinstance(terrain, dict) else {}
    heightmap = heightmap if isinstance(heightmap, dict) else {}
    atmosphere = atmosphere if isinstance(atmosphere, dict) else planet.get("atmosphere_model") or {}
    water_cycle = water_cycle if isinstance(water_cycle, dict) else planet.get("water_cycle_model") or {}
    surface_geomorphology = (
        surface_geomorphology
        if isinstance(surface_geomorphology, dict)
        else planet.get("surface_geomorphology_model") or {}
    )
    detail_level = max(0, int(heightmap.get("map_detail_level", 0) or 0))
    rows = _rows_from_heightmap(heightmap)
    candidate_limit = max(16, int(max_layers or 1) * 2)
    materials = _select_material_layers(
        natural_material_model,
        max_layers=candidate_limit,
        detail_level=detail_level,
        candidate_pool=True,
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
    surface_partition = derive_surface_material_partition_fields(
        heightmap,
        water_cycle=water_cycle,
        surface_evolution=planet.get("surface_evolution_model"),
        target_size=(width, height),
    )
    map_seed = str(heightmap.get("map_seed") or terrain.get("map_seed") or resolved_map_seed(planet.get("world_gen_seed"), planet_id=planet_id))
    material_distribution_seed = str(
        heightmap.get("material_distribution_seed") or map_seed
    )
    tectonic_model = planet.get("tectonic_model") if isinstance(planet.get("tectonic_model"), dict) else {}
    source_uv_bounds = (
        heightmap.get("source_uv_bounds")
        if isinstance(heightmap.get("source_uv_bounds"), dict)
        else {}
    )
    source_min_u = _clamp(source_uv_bounds.get("min_u", 0.0))
    source_max_u = _clamp(source_uv_bounds.get("max_u", 1.0))
    source_min_v = _clamp(source_uv_bounds.get("min_v", 0.0))
    source_max_v = _clamp(source_uv_bounds.get("max_v", 1.0))
    min_elevation = float(heightmap.get("min_elevation_m", -4000.0) or -4000.0)
    max_elevation = float(heightmap.get("max_elevation_m", 4000.0) or 4000.0)
    span = max(1.0, max_elevation - min_elevation)
    sea_level = heightmap.get("sea_level_m")
    sea_level = None if sea_level is None else float(sea_level or 0.0)
    hydrology = terrain.get("hydrology") if isinstance(terrain.get("hydrology"), dict) else {}
    realized_ocean_fraction = float(
        (heightmap.get("hypsometry_summary") or {}).get(
            "ocean_fraction",
            hydrology.get("target_ocean_fraction", 0.0),
        )
        or 0.0
    )
    hydrology_strength = _clamp(
        realized_ocean_fraction
        + (0.25 if hydrology.get("cycle") in {"active", "limited"} else 0.0)
    )
    active_hydrology = bool(hydrology.get("liquid_water_possible")) and float(
        atmosphere.get("surface_pressure_bar", 0.0) or 0.0
    ) >= 0.006
    planet_tags = set((natural_material_model or {}).get("planet_tags") or [])
    active_volcanism = "active_volcanism" in planet_tags
    wet_oxidizing_surface = (
        "active_hydrology" in planet_tags
        and "oxidizing_surface" in planet_tags
    )
    available_host_categories = {
        contract.get("category_id")
        for candidate in (natural_material_model or {}).get("likely_materials") or []
        for contract in [
            formation_contract(
                candidate.get("material_id"),
                candidate.get("material_subclass"),
                (
                    candidate.get("surface_affinity_profile")
                    or material_affinity_profile(candidate.get("material_id"))
                    or {}
                ).get("profile_id"),
                explicit_category=candidate.get("formation_category"),
                explicit_representation=candidate.get("spatial_representation"),
            )
        ]
        if (
            contract.get("category_id")
            and contract.get("spatial_representation") == "bedrock_unit"
            and float(candidate.get("confidence", 0.0) or 0.0) >= 0.28
        )
    }
    if {"felsic_crust", "silica_rich_crust"}.intersection(planet_tags):
        available_host_categories.add("igneous_intrusive_felsic")
    if {"mafic_crust", "basaltic_surface"}.intersection(planet_tags):
        available_host_categories.add("igneous_mafic")
    if "ultramafic_tendency" in planet_tags:
        available_host_categories.add("igneous_ultramafic")
    if "carbonate_favorable" in planet_tags:
        available_host_categories.add("carbonate_sedimentary_basin")
    crater_fields = _crater_material_fields(planet.get("crater_model"), width, height)
    resurfacing_constants = _resurfacing_constants(
        material_distribution_seed, terrain,
    )
    tectonic_lithology_constants = _tectonic_lithology_constants(
        tectonic_model, material_distribution_seed
    )
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

    # Terrain and climate are shared by every material.  Sampling the same
    # 513-cell regional grids once per candidate made native regional rasters
    # several times more expensive than the terrain refinement itself.
    environment_grid = []
    volcanic_surface = (
        1.0
        if "volcanic_surface" in planet_tags or "basaltic_surface" in planet_tags
        else 0.0
    )
    for y in range(height):
        ny = y / max(1, height - 1)
        environment_row = []
        for x in range(width):
            nx = x / max(1, width - 1)
            field_nx = source_min_u + nx * (source_max_u - source_min_u)
            field_ny = source_min_v + ny * (source_max_v - source_min_v)
            polar = abs(field_ny - 0.5) * 2.0
            elevation = _sample_height(rows, nx, ny)
            local_temperature_k = _local_surface_temperature_k(
                atmosphere, water_cycle, elevation, nx, ny,
            )
            elevation_norm = _clamp((elevation - min_elevation) / span)
            ocean = (
                1.0
                if sea_level is not None and elevation < sea_level
                else 0.0
            )
            shoreline = (
                0.0
                if sea_level is None
                else math.exp(
                    -(
                        (
                            abs(elevation - sea_level)
                            / max(1.0, span * 0.085)
                        )
                        ** 2
                    )
                )
            )
            ice = (
                polar
                if ocean > 0.0 and hydrology.get("target_ice_fraction", 0.0)
                else 0.0
            )
            resurfacing = _resurfacing_influence(
                material_distribution_seed,
                terrain,
                field_nx,
                field_ny,
                resurfacing_constants,
            )
            slope = _local_slope_index(rows, nx, ny, span)
            partition = {
                key: float(values[y, x])
                for key, values in surface_partition.items()
                if hasattr(values, "shape") and values.shape == (height, width)
            }
            precipitation_mm = (
                max(0.0, _sample_height(precipitation_rows, nx, ny))
                if precipitation_rows
                else max(
                    0.0,
                    120.0
                    + hydrology_strength * 1900.0 * (1.0 - polar * 0.72),
                )
            )
            humidity = _clamp(precipitation_mm / 1800.0)
            aridity = _clamp(1.0 - precipitation_mm / 700.0)
            runoff_mm = (
                max(0.0, _sample_height(runoff_rows, nx, ny))
                if runoff_rows
                else 0.0
            )
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
                    * math.exp(
                        -((local_temperature_k - 296.0) / 34.0) ** 2
                    )
                    * (0.28 + slope * 0.50)
                )
            )
            deposition = (
                _clamp(_sample_height(deposition_rows, nx, ny))
                if deposition_rows
                else _clamp(drainage * (1.0 - slope))
            )
            aeolian = (
                _clamp(_sample_height(aeolian_rows, nx, ny))
                if aeolian_rows
                else _clamp(aridity * (0.22 + slope * 0.35))
            )
            erosion = (
                _clamp(_sample_height(erosion_rows, nx, ny))
                if erosion_rows
                else _clamp(slope * (0.35 + drainage * 0.65))
            )
            glacial = (
                _clamp(_sample_height(glacial_rows, nx, ny))
                if glacial_rows
                else _clamp(ice * polar)
            )
            age = (
                _clamp(_sample_height(age_rows, nx, ny))
                if age_rows
                else _clamp(
                    0.72 - erosion * 0.42 - resurfacing * 0.28
                )
            )
            seasonal_minimum_k = (
                _sample_height(seasonal_min_temperature_rows, nx, ny)
                if seasonal_min_temperature_rows
                else 0.0
            )
            environment_row.append({
                "field_nx": field_nx,
                "field_ny": field_ny,
                "local_temperature_k": local_temperature_k,
                "seasonal_minimum_k": seasonal_minimum_k,
                "ocean": ocean,
                "tectonic_lithology": _tectonic_lithology_context(
                    tectonic_model,
                    field_nx,
                    field_ny,
                    material_distribution_seed,
                    tectonic_lithology_constants,
                ),
                "context": {
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
                    "volcanic": volcanic_surface,
                    "resurfacing": resurfacing,
                    "impact": crater_fields["breccia"][y][x],
                    "carbonate": carbonate_favorable,
                    "wet_oxidizing_surface": wet_oxidizing_surface,
                    "active_hydrology": active_hydrology,
                    "active_volcanism": active_volcanism,
                    "planet_tags": planet_tags,
                    "ridge": partition.get("ridge", 0.0),
                    "valley": partition.get("valley", 0.0),
                    "scarp": partition.get("scarp", 0.0),
                    "incised_valley": partition.get("incised_valley", 0.0),
                    "exposed_bedrock": partition.get("exposed_bedrock_fraction", 0.25),
                    "colluvial_cover": partition.get("colluvial_cover_fraction", 0.0),
                    "alluvial_cover": partition.get("alluvial_cover_fraction", 0.0),
                    "weathered_mantle": partition.get("weathered_mantle_fraction", 0.0),
                    "residual_regolith": partition.get("residual_regolith_fraction", 0.0),
                },
            })
        environment_grid.append(environment_row)

    native_ocean_mask = [
        [bool(cell.get("ocean", 0.0) >= 0.5) for cell in row]
        for row in environment_grid
    ]
    native_wrap_x = bool(heightmap.get("wrap_x", False)) and (
        source_min_u <= 1e-6 and source_max_u >= 1.0 - 1e-6
    )
    layer_pixels = []
    layer_metadata = []
    bundle_layers = []
    for material in materials:
        material_id = str(material.get("material_id"))
        color = material_display_color(material_id, material.get("display_color"))
        geology_color = material_geological_map_color(
            material_id,
            material.get("geological_map_color"),
        )
        confidence = _clamp(float(material.get("confidence", 0.45) or 0.45), 0.05, 1.0)
        affinity_profile = material_affinity_profile(material_id)
        if affinity_profile is None:
            continue
        formation = formation_contract(
            material_id,
            material.get("material_subclass"),
            affinity_profile.get("profile_id"),
            explicit_category=material.get("formation_category"),
            explicit_representation=material.get("spatial_representation"),
        )
        optical_profile = material_optical_surface_profile(
            material_id,
            formation_category=formation.get("category_id"),
            material_subclass=material.get("material_subclass"),
            display_color=material.get("display_color"),
            explicit=material.get("optical_surface_profile"),
        )
        distribution_role = (
            material.get("distribution_role")
            or material_distribution_role(
                material_id,
                material.get("material_subclass"),
                max(
                    int(material.get("minimum_map_detail_level", 0) or 0),
                    int(affinity_profile.get("minimum_map_detail_level", 0) or 0),
                ),
            )
        )
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
        abundance = _clamp(
            material.get(
                "relative_abundance",
                affinity_profile.get("abundance", 1.0),
            )
        )
        phase_profile = material_surface_phase_profile(material_id, atmosphere=atmosphere)
        # These values are seeded only from immutable run inputs.  Passing
        # them into the pixel loop avoids millions of identical hash calls
        # while preserving the same spatial field exactly.
        material_wave_constants = _wave_noise_constants(
            material_distribution_seed, material_id,
        )
        material_regional_constants = _regional_material_constants(
            material_distribution_seed, material_id,
        )
        pixels = []
        surface = pygame.Surface((width, height), pygame.SRCALPHA)
        peak = 0.0
        total = 0.0
        coverage = 0
        sparse_floor = seed_range(
            material_distribution_seed,
            f"{material_id}:sparse_floor",
            0.20,
            0.44,
        )
        sparse_floor = _clamp(sparse_floor + (1.0 - abundance) * 0.06, 0.0, 0.68)
        # Once a material has reached the map scale at which it can resolve,
        # expose its suitability field without requiring it to compete with
        # continent-scale bedrock abundance.  Sparse deposits are converted
        # into bounded occurrences by regional refinement; this layer is the
        # prospectivity signal used to find and select them.
        if detail_level > 0 and distribution_role in {
            "sparse_deposit",
            "mineral_constituent",
            "local_lithology",
            "local_material_unit",
        }:
            sparse_floor = max(0.06, sparse_floor - 0.14)
        sparse_ceiling = sparse_floor + seed_range(
            material_distribution_seed,
            f"{material_id}:sparse_softness",
            0.16,
            0.30,
        )
        if foundational_bedrock or distribution_role == "bedrock":
            # These candidates have already passed elemental and formation
            # validity checks. They are competing crustal units, not sparse
            # ore occurrences, so a per-material random rarity threshold
            # must not let one high-confidence rock erase every terrane.
            sparse_floor = 0.12
            sparse_ceiling = 0.68

        for y in range(height):
            row = []
            for x in range(width):
                environment = environment_grid[y][x]
                field_nx = environment["field_nx"]
                field_ny = environment["field_ny"]
                local_temperature_k = environment["local_temperature_k"]
                ocean = environment["ocean"]
                phase_temperature_k = local_temperature_k
                frost_duty_cycle = 1.0
                if phase_profile.get("phase") in {"water_frost", "carbon_dioxide_frost"}:
                    seasonal_minimum_k = environment["seasonal_minimum_k"]
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
                noise = _wave_noise(
                    material_distribution_seed,
                    material_id,
                    field_nx,
                    field_ny,
                    material_wave_constants,
                )
                region = _regional_material_influence(
                    material_distribution_seed,
                    material_id,
                    field_nx,
                    field_ny,
                    material_regional_constants,
                )
                if foundational_bedrock or distribution_role in {"bedrock", "local_lithology"}:
                    region = _lithologic_province_affinity(
                        material_distribution_seed,
                        material_id,
                        formation,
                        affinity_profile,
                        environment.get("tectonic_lithology"),
                    )
                affinity_context = environment["context"].copy()
                affinity_context["regional"] = region
                affinity_context["noise"] = noise
                affinity = material_affinity_score(
                    material_id, affinity_context
                ) * formation_suitability(
                    formation,
                    affinity_context,
                    available_host_categories,
                )
                category = str(formation.get("category_id") or "")
                context = affinity_context
                if foundational_bedrock or distribution_role == "bedrock":
                    surface_expression = 0.12 + context["exposed_bedrock"] * 0.88
                    topographic_driver = "exposed_bedrock"
                elif category == "fluvial_sediment":
                    surface_expression = 0.04 + context["alluvial_cover"] * 0.96
                    topographic_driver = "alluvial_valley_deposition"
                elif category == "colluvial_sediment":
                    surface_expression = 0.03 + context["colluvial_cover"] * 0.97
                    topographic_driver = "colluvial_footslope_deposition"
                elif category == "aeolian_sediment":
                    surface_expression = 0.05 + context["weathered_mantle"] * 0.72 + context["aeolian"] * 0.23
                    topographic_driver = "aeolian_mantled_plain"
                elif category == "quartz_sand_accumulation":
                    surface_expression = (
                        0.03
                        + context["weathered_mantle"] * 0.30
                        + context["aeolian"] * 0.22
                        + context["shoreline"] * 0.20
                        + context["deposition"] * 0.15
                        + context["low_slope"] * 0.10
                    )
                    topographic_driver = "sorted_quartz_sand_cover"
                elif category in {"weathering_clay", "saprolitic_regolith", "lateritic_regolith", "residual_bauxite", "nickel_laterite", "iron_weathering", "duricrust"}:
                    surface_expression = 0.05 + context["weathered_mantle"] * 0.60 + context["residual_regolith"] * 0.35
                    topographic_driver = "weathered_residual_mantle"
                elif distribution_role == "surface_cover":
                    surface_expression = 0.08 + (1.0 - context["exposed_bedrock"]) * 0.52 + context["low_slope"] * 0.26
                    topographic_driver = "generic_mobile_cover"
                else:
                    surface_expression = 1.0
                    topographic_driver = "formation_specific"
                material_text = f"{material_id} {material.get('name') or ''}".lower()
                if "impact" in material_text or "breccia" in material_text:
                    # Breccia follows the actual retained crater population;
                    # do not let generic regional noise paint it between
                    # impacts.
                    raw_value = _clamp((affinity * 0.96 + noise * 0.04) * confidence)
                elif foundational_bedrock or distribution_role in {"bedrock", "local_lithology"}:
                    # Substrate identity is primarily a tectonic/province
                    # decision. Climate and topography still determine its
                    # surface exposure, but independent material noise cannot
                    # smear every rock across every continent.
                    validity = _clamp(affinity)
                    raw_value = _clamp(
                        # Candidate inference is the chemistry gate. Among
                        # candidates that passed it, shared tectonic terranes
                        # decide the exposed unit. This prevents a small
                        # confidence advantage from painting one rock across
                        # an otherwise diverse continental crust.
                        (region * 0.70 + validity * 0.28 + noise * 0.02)
                        * (0.78 + math.sqrt(max(0.0, confidence)) * 0.22)
                        * (0.82 + abundance * 0.18)
                    )
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
                # Formation suitability decides whether a material exists in
                # this province; the geomorphic partition decides how much of
                # it is actually expressed at the surface. Keeping those two
                # stages separate prevents a thin mantle from erasing the
                # underlying geological occurrence entirely.
                value *= _clamp(surface_expression)
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

        if detail_level <= 0:
            is_substrate = foundational_bedrock or distribution_role == "bedrock"
            pixels = _relax_native_material_field(
                pixels,
                native_ocean_mask,
                passes=5 if is_substrate else 3,
                strength=0.46 if is_substrate else 0.38,
                wrap_x=native_wrap_x,
            )
            # Rebuild both the raster and its diagnostics from the corrected
            # native field.  Otherwise layer selection would still use the
            # pre-correction coverage while true color receives the new one.
            peak = 0.0
            total = 0.0
            coverage = 0
            for y, row in enumerate(pixels):
                for x, value in enumerate(row):
                    value = _clamp(value)
                    peak = max(peak, value)
                    total += value
                    if value >= 0.18:
                        coverage += 1
                    surface.set_at((x, y), (
                        color[0],
                        color[1],
                        color[2],
                        int(round(value * 230.0)),
                    ))

        layer_id = f"heatmap_{_safe_slug(material_id)}"
        display_semantics = {
            "bedrock": "substrate_distribution",
            "surface_cover": "surface_cover_distribution",
            "local_lithology": "local_lithology_distribution",
            "mineral_constituent": "constituent_abundance",
            "sparse_deposit": "deposit_prospectivity",
            "local_material_unit": "local_material_distribution",
        }.get(distribution_role, "material_suitability")
        bundle_layers.append({
            "id": layer_id,
            "role": "material_layer",
            "material_id": material_id,
            "name": material.get("name") or material_id,
            "material_subclass": material.get("material_subclass"),
            "distribution_role": distribution_role,
            "display_semantics": display_semantics,
            "foundational_lithology": foundational_bedrock,
            "formation_category": formation.get("category_id"),
            "spatial_representation": formation.get("spatial_representation"),
            "surface": surface,
            "display_color": color,
            "geological_map_color": geology_color,
            "optical_surface_profile": optical_profile,
            "confidence": round(confidence, 3),
            "phase_profile": phase_profile,
            "surface_expression_precomputed": True,
            "topographic_driver": topographic_driver,
        })
        layer_pixels.append({
            "material_id": material_id,
            "pixels": pixels,
            "color": color,
            "geological_map_color": geology_color,
            "confidence": confidence,
            "distribution_role": distribution_role,
            "display_semantics": display_semantics,
            "formation_category": formation.get("category_id"),
            "spatial_representation": formation.get("spatial_representation"),
            "optical_surface_profile": optical_profile,
            "surface_expression_precomputed": True,
            "topographic_driver": topographic_driver,
        })
        layer_metadata.append({
            "id": layer_id,
            "material_id": material_id,
            "name": material.get("name") or material_id,
            "material_subclass": material.get("material_subclass"),
            "distribution_role": distribution_role,
            "display_semantics": display_semantics,
            "foundational_lithology": foundational_bedrock,
            "formation_category": formation.get("category_id"),
            "spatial_representation": formation.get("spatial_representation"),
            "minimum_map_detail_level": max(
                int(material.get("minimum_map_detail_level", 0) or 0),
                int(affinity_profile.get("minimum_map_detail_level", 0) or 0),
            ),
            "distribution_scale": affinity_profile.get("distribution_scale"),
            "bundle_path": _relative_or_absolute(bundle_path, storage_root=storage_root),
            "bundle_layer_id": layer_id,
            "display_color": color,
            "geological_map_color": geology_color,
            "optical_surface_profile": optical_profile,
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
            "surface_expression_precomputed": True,
            "topographic_driver": topographic_driver,
        })

    planetary_local_cover_categories = {
        "fluvial_sediment",
        "colluvial_sediment",
        "littoral_sediment",
        "lacustrine_sediment",
        "marine_sediment",
    }
    planetary_local_cover_ids = {
        "mat_alluvium",
        "mat_beach_sand",
        "mat_lacustrine_mud",
        "mat_marine_mud",
    }
    terrain_style = str(
        terrain.get("geologic_style")
        or terrain.get("terrain_style")
        or ""
    ).lower()
    if terrain_style not in {"aeolian_dune_seas", "hydrocarbon_dunes_and_lakes"}:
        planetary_local_cover_ids.add("mat_dune_sand")

    def resolves_in_composite(index):
        if detail_level > 0:
            return True
        metadata = layer_metadata[index]
        role = str(metadata.get("distribution_role") or "")
        if role not in {"bedrock", "surface_cover"}:
            return False
        if (
            role == "surface_cover"
            and (
                str(metadata.get("formation_category") or "")
                in planetary_local_cover_categories
                or str(metadata.get("material_id") or "")
                in planetary_local_cover_ids
            )
        ):
            return False
        return (
            bool(metadata.get("foundational_lithology"))
            or int(metadata.get("minimum_map_detail_level", 0) or 0) <= 0
        )

    usable_candidates = [
        index
        for index, metadata in enumerate(layer_metadata)
        if (
            resolves_in_composite(index)
            and (
                float(metadata.get("coverage_fraction", 0.0) or 0.0) > 0.0
                or (
                    detail_level > 0
                    and metadata.get("distribution_role") in {
                        "sparse_deposit", "mineral_constituent",
                        "local_lithology", "local_material_unit",
                    }
                    and float(metadata.get("peak_intensity", 0.0) or 0.0) > 0.01
                )
            )
        )
    ]
    usable_has_bedrock = any(
        layer_metadata[index].get("distribution_role") == "bedrock"
        for index in usable_candidates
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
            usable_candidates.append(bedrock_index)
    if not usable_candidates and layer_metadata:
        usable_candidates = [
            max(
                range(len(layer_metadata)),
                key=lambda index: float(
                    layer_metadata[index].get("peak_intensity", 0.0) or 0.0
                ),
            )
        ]

    final_limit = max(1, int(max_layers or 1))
    final_role_caps = (
        {"bedrock": 10, "surface_cover": 8}
        if detail_level <= 0
        else {
            "bedrock": 4,
            "surface_cover": 4,
            "local_lithology": 4,
            "mineral_constituent": 3,
            "sparse_deposit": 3,
            "local_material_unit": 2,
        }
    )

    def visibility_score(index):
        metadata = layer_metadata[index]
        coverage = float(metadata.get("coverage_fraction", 0.0) or 0.0)
        mean = float(metadata.get("mean_intensity", 0.0) or 0.0)
        peak = float(metadata.get("peak_intensity", 0.0) or 0.0)
        confidence = float(metadata.get("confidence", 0.0) or 0.0)
        resolves_here = (
            int(metadata.get("minimum_map_detail_level", 0) or 0)
            == detail_level
        )
        return (
            coverage * 0.48
            + mean * 0.22
            + peak * 0.20
            + confidence * 0.07
            + (0.03 if resolves_here else 0.0)
            + (0.12 if metadata.get("foundational_lithology") else 0.0)
        )

    usable_candidates.sort(key=visibility_score, reverse=True)
    usable_indices = []
    selected_role_counts = {}
    role_priority = (
        ["bedrock", "surface_cover"]
        if detail_level <= 0
        else [
            "bedrock",
            "surface_cover",
            "local_lithology",
            "mineral_constituent",
            "sparse_deposit",
            "local_material_unit",
        ]
    )
    # Reserve one slot for every material scale role that actually resolves
    # here.  The remaining slots go to the strongest visible fields.
    for role in role_priority:
        candidate = next(
            (
                index
                for index in usable_candidates
                if index not in usable_indices
                and layer_metadata[index].get("distribution_role") == role
            ),
            None,
        )
        if candidate is None:
            continue
        usable_indices.append(candidate)
        selected_role_counts[role] = 1
        if len(usable_indices) >= final_limit:
            break
    if len(usable_indices) < final_limit:
        for index in usable_candidates:
            if index in usable_indices:
                continue
            role = str(
                layer_metadata[index].get("distribution_role")
                or "local_material_unit"
            )
            if detail_level <= 0 and role not in final_role_caps:
                continue
            if selected_role_counts.get(role, 0) >= final_role_caps.get(role, 2):
                continue
            usable_indices.append(index)
            selected_role_counts[role] = selected_role_counts.get(role, 0) + 1
            if len(usable_indices) >= final_limit:
                break

    bundle_layers = [bundle_layers[index] for index in usable_indices]
    layer_pixels = [layer_pixels[index] for index in usable_indices]
    layer_metadata = [layer_metadata[index] for index in usable_indices]

    composite = pygame.Surface((width, height), pygame.SRCALPHA)
    dominant_material_rows = [[None for _x in range(width)] for _y in range(height)]
    dominant_counts = {
        str(layer.get("material_id") or ""): 0
        for layer in layer_pixels
    }
    for y in range(height):
        for x in range(width):
            bedrock_candidates = []
            cover_candidates = []
            for layer in layer_pixels:
                value = layer["pixels"][y][x] * layer["confidence"]
                if value <= 0.0:
                    continue
                distribution_role = layer.get("distribution_role")
                if distribution_role == "bedrock":
                    bedrock_candidates.append((value, layer))
                elif distribution_role == "surface_cover":
                    cover_candidates.append((value, layer))
            bedrock_candidates.sort(key=lambda item: item[0], reverse=True)
            cover_candidates.sort(key=lambda item: item[0], reverse=True)
            if not bedrock_candidates and not cover_candidates:
                composite.set_at((x, y), (31, 50, 65, 255))
            else:
                # Bedrock is the persistent substrate. Surface materials only
                # replace it visually where their own process field forms a
                # sufficiently coherent cover, rather than competing as an
                # equally deep lithology everywhere.
                best_score, best_layer = (
                    bedrock_candidates[0]
                    if bedrock_candidates
                    else cover_candidates[0]
                )
                if cover_candidates:
                    cover_score, cover_layer = cover_candidates[0]
                    cover_threshold = max(
                        0.12,
                        best_score * 0.56 if bedrock_candidates else 0.0,
                    )
                    if cover_score >= cover_threshold:
                        best_score, best_layer = cover_score, cover_layer
                material_id = str(best_layer.get("material_id") or "")
                dominant_material_rows[y][x] = material_id
                dominant_counts[material_id] += 1
                color = best_layer["geological_map_color"]
                composite.set_at((
                    x,
                    y,
                ), (
                    int(color[0]), int(color[1]), int(color[2]), 255,
                ))

    for metadata in layer_metadata:
        material_id = str(metadata.get("material_id") or "")
        metadata["suitability_coverage_fraction"] = metadata.get(
            "coverage_fraction",
            0.0,
        )
        if metadata.get("distribution_role") in {"bedrock", "surface_cover"}:
            metadata["coverage_fraction"] = round(
                dominant_counts.get(material_id, 0) / max(1, width * height),
                3,
            )
        else:
            metadata["dominance_coverage_fraction"] = 0.0

    composite_layer_id = "composite"
    bundle_layers.insert(0, {
        "id": composite_layer_id,
        "role": "composite",
        "name": "Composite Material Heatmap",
        "surface": composite,
        "render_mode": "categorical_geological_map",
        "render_contract": "surface_cover_over_bedrock",
        "visualization_purpose": "analytical_only_not_surface_reflectance",
        "contact_style": "renderer_soft_cartographic_boundary",
    })
    manifest = _write_raster_bundle(
        bundle_path,
        width,
        height,
        bundle_layers,
        metadata={
            "kind": "material_heatmap",
            "planet_id": planet_id,
            "owner_entity_id": planet_id,
            "map_seed": map_seed,
            "material_distribution_seed": material_distribution_seed,
            "source_uv_bounds": {
                "min_u": source_min_u, "max_u": source_max_u,
                "min_v": source_min_v, "max_v": source_max_v,
            },
            "projection": heightmap.get("projection", "equirectangular"),
            "generator_version": MATERIAL_HEATMAP_MODEL_VERSION,
            "source_heightfield_fingerprint": heightmap.get("source_heightfield_fingerprint"),
            "input_fingerprint": hashlib.sha256(json.dumps({
                "planet_id": planet_id,
                "map_seed": map_seed,
                "material_distribution_seed": material_distribution_seed,
                "source_uv_bounds": {
                    "min_u": source_min_u, "max_u": source_max_u,
                    "min_v": source_min_v, "max_v": source_max_v,
                },
                "heightfield": heightmap.get("source_heightfield_fingerprint"),
                "surface_geomorphology": surface_geomorphology.get("input_fingerprint"),
                "materials": sorted(str(item.get("material_id") or "") for item in materials if isinstance(item, dict)),
            }, sort_keys=True).encode("utf-8")).hexdigest(),
        },
    )
    composite_layer = {
        "id": "heatmap_composite_materials",
        "name": "Composite Material Heatmap",
        "bundle_path": _relative_or_absolute(bundle_path, storage_root=storage_root),
        "bundle_layer_id": composite_layer_id,
        "render_mode": "categorical_geological_map",
        "render_contract": "surface_cover_over_bedrock",
        "visualization_purpose": "analytical_only_not_surface_reflectance",
        "contact_style": "renderer_soft_cartographic_boundary",
        "confidence_state": "inferred",
        "truth_state": "generated",
    }

    return {
        "status": "generated",
        "model_version": MATERIAL_HEATMAP_MODEL_VERSION,
        "projection": heightmap.get("projection", "equirectangular"),
        "map_seed": map_seed,
        "material_distribution_seed": material_distribution_seed,
        "source_uv_bounds": {
            "min_u": source_min_u, "max_u": source_max_u,
            "min_v": source_min_v, "max_v": source_max_v,
        },
        "planet_id": planet_id,
        "source_heightfield_fingerprint": heightmap.get("source_heightfield_fingerprint"),
        "storage_format": RASTER_BUNDLE_FORMAT,
        "bundle_format_version": RASTER_BUNDLE_VERSION,
        "bundle_path": _relative_or_absolute(bundle_path, storage_root=storage_root),
        "image_format": "rgba8888_bundle",
        "width_px": width,
        "height_px": height,
        "wrap_x": bool(heightmap.get("wrap_x", True)),
        "wrap_y": bool(heightmap.get("wrap_y", False)),
        "truth_model": "deterministic_generated_truth",
        "distribution_mode": "topography_resolved_surface_materials",
        "distribution_roles": ["bedrock", "surface_cover"],
        "true_color_source": "fractional_individual_material_layers",
        "fractional_endmember_contract": "suitability_times_process_exposure_normalized_within_stratum",
        "surface_material_causality": "final_heightfield_to_geomorphic_partition_to_material_surface_expression_to_true_color",
        "surface_geomorphology_version": surface_geomorphology.get("model_version"),
        "surface_partition_summary": {
            key: round(float(values.mean()), 5)
            for key, values in surface_partition.items()
            if key in {
                "exposed_bedrock_fraction", "colluvial_cover_fraction",
                "alluvial_cover_fraction", "weathered_mantle_fraction",
                "residual_regolith_fraction",
            }
        },
        "default_confidence_state": "inferred",
        "composite_layer": composite_layer,
        "layers": layer_metadata,
        "bundle_manifest": {
            "layer_count": len(manifest.get("layers") or []),
            "encoding": manifest.get("encoding"),
        },
    }
