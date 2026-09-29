"""Material raster bundles for every world-generation LOD.

The scientific product is built by ``material_lod`` (areal substrate, cover
and visible composition from lithotectonic settings at LOD0 and from the
parent composition below it).  This module writes it to the region's own
``.i0r`` bundle and returns the compact manifest stored on the map entity.

Bundle layers:

* ``heatmap_<material>``: visible areal fraction of one material (alpha), in
  the material's display colour.  True Color mixes these linearly with each
  material's ontology optical profile;
* ``composite``: categorical geological map of the dominant visible material;
* ``substrate_<n>`` / ``cover_<n>`` / ``settings_<n>``: packed 8-bit fraction
  channels (four per layer) that children sample for strict N-1 inheritance;
* ``units``: mapped unit (LOD0: province) ids packed into RGB.

Architecture invariants: the ontology owns materials, colours, formation
rules and setting weights; rasters are disposable generated truth in the
lineage namespace of the region that owns them.
"""

import hashlib
import json
import math
import os
import re
import time
import zipfile
from pathlib import Path

import numpy as np
import pygame

from simulations.world_gen.lithotectonic_settings import (
    LITHOTECTONIC_MODEL_VERSION,
    SETTING_IDS,
    SETTINGS,
    normalized_candidate,
)
from simulations.world_gen.map_seed import resolved_map_seed
from simulations.world_gen.material_lod import (
    COVER_CLASS_IDS,
    MATERIAL_LOD_MODEL_VERSION,
    UNIT_PURITY_BY_LEVEL,
    _overlay_occurrences,
    derive_child_material_product,
    derive_lod0_material_product,
    province_table,
    rasterize_occurrences,
)
from simulations.world_gen.material_optics import material_optical_surface_profile
from simulations.world_gen import natural_materials
from simulations.world_gen.natural_materials import (
    material_display_color,
    material_geological_map_color,
)
from simulations.world_gen.storage_policy import utc_timestamp


class _LiveMaterialCatalog:
    """Read-through view of the ontology material cache (rebuilt at startup)."""

    def get(self, material_id, default=None):
        return natural_materials.MATERIAL_BY_ID.get(material_id, default)


MATERIAL_BY_ID = _LiveMaterialCatalog()

MATERIAL_HEATMAP_MODEL_VERSION = MATERIAL_LOD_MODEL_VERSION
RASTER_BUNDLE_FORMAT = "index0_raster_bundle"
RASTER_BUNDLE_VERSION = 1
RASTER_BUNDLE_EXTENSION = ".i0r"
DEFAULT_HEATMAP_SIZE = (320, 160)
# Output cap on individually stored visible-material layers.
DEFAULT_MATERIAL_LAYER_LIMIT = 40
FRACTION_SEMANTICS = "areal_surface_fraction"


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, float(value)))


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
    """Write layers (``surface`` or raw ``rgba`` bytes) to a validated bundle."""
    bundle_path = Path(bundle_path)
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_layers = []
    temporary = bundle_path.with_name(f".{bundle_path.name}.tmp-{os.getpid()}")
    layer_payloads = []
    for layer in layers:
        layer_id = _safe_slug(layer.get("id") or layer.get("material_id") or layer.get("name") or "layer")
        entry_name = f"layers/{layer_id}.rgba"
        if layer.get("rgba") is not None:
            rgba = bytes(layer["rgba"])
        elif layer.get("surface") is not None:
            rgba = _surface_to_rgba_bytes(layer["surface"])
        else:
            continue
        layer_meta = {
            key: value
            for key, value in layer.items()
            if key not in {"surface", "pixels", "rgba"}
        }
        layer_meta.update({
            "id": layer_id,
            "rgba_path": entry_name,
            "width_px": int(layer.get("width_px") or width),
            "height_px": int(layer.get("height_px") or height),
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


def _find_bundle_layer(layers, requested):
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
    return layer


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
            layer = _find_bundle_layer(manifest.get("layers") or [], requested)
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


def load_raster_bundle_arrays(bundle_path, layer_ids):
    """Return ``{layer_id: uint8[H, W, 4]}`` for the requested bundle layers."""
    bundle_path = Path(bundle_path)
    if not bundle_path.exists():
        return {}
    arrays = {}
    try:
        with zipfile.ZipFile(bundle_path, "r") as bundle:
            manifest = json.loads(bundle.read("manifest.json").decode("utf-8"))
            if manifest.get("format") != RASTER_BUNDLE_FORMAT:
                return {}
            layers = manifest.get("layers") or []
            for layer_id in layer_ids:
                layer = _find_bundle_layer(layers, str(layer_id))
                if layer is None:
                    continue
                width = int(layer.get("width_px") or manifest.get("width_px") or 0)
                height = int(layer.get("height_px") or manifest.get("height_px") or 0)
                data = bundle.read(layer.get("rgba_path"))
                arrays[str(layer_id)] = np.frombuffer(data, dtype=np.uint8).reshape(height, width, 4)
    except (OSError, KeyError, ValueError, json.JSONDecodeError, zipfile.BadZipFile):
        return {}
    return arrays


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


def _quantize(values):
    return np.clip(np.rint(np.asarray(values, dtype=np.float32) * 255.0), 0, 255).astype(np.uint8)


def _fraction_rgba(color, fraction):
    height, width = fraction.shape
    rgba = np.empty((height, width, 4), dtype=np.uint8)
    rgba[..., 0] = int(color[0])
    rgba[..., 1] = int(color[1])
    rgba[..., 2] = int(color[2])
    rgba[..., 3] = _quantize(fraction)
    return rgba.tobytes()


def _packed_layers(prefix, arrays):
    """Pack fraction arrays four per RGBA layer; return (layers, ids)."""
    layers = []
    layer_ids = []
    arrays = list(arrays)
    for start in range(0, len(arrays), 4):
        chunk = arrays[start:start + 4]
        height, width = chunk[0].shape
        rgba = np.zeros((height, width, 4), dtype=np.uint8)
        for channel, values in enumerate(chunk):
            rgba[..., channel] = _quantize(values)
        layer_id = f"{prefix}_{start // 4:02d}"
        layers.append({"id": layer_id, "role": f"packed_{prefix}", "rgba": rgba.tobytes()})
        layer_ids.append(layer_id)
    return layers, layer_ids


def _unpack_layers(arrays_by_id, layer_ids, count):
    channels = []
    for layer_id in layer_ids:
        rgba = arrays_by_id.get(layer_id)
        if rgba is None:
            return None
        for channel in range(4):
            channels.append(rgba[..., channel].astype(np.float32) / 255.0)
    return np.stack(channels[:count]) if count else None


def _units_rgba(units):
    units = np.asarray(units, dtype=np.int64)
    rgba = np.zeros(units.shape + (4,), dtype=np.uint8)
    rgba[..., 0] = units & 0xFF
    rgba[..., 1] = (units >> 8) & 0xFF
    rgba[..., 2] = (units >> 16) & 0xFF
    rgba[..., 3] = 255
    return rgba.tobytes()


def decode_unit_rgba(rgba):
    rgba = np.asarray(rgba, dtype=np.int64)
    return rgba[..., 0] | (rgba[..., 1] << 8) | (rgba[..., 2] << 16)


def resolve_bundle_path(bundle_path, storage_root=None):
    path = Path(str(bundle_path or ""))
    if path.is_absolute() or storage_root is None:
        return path
    return Path(storage_root) / path


def load_parent_composition(parent_material_model, storage_root=None):
    """Load a parent's substrate composition for N-1 inheritance, or None."""
    model = parent_material_model if isinstance(parent_material_model, dict) else {}
    substrate = model.get("substrate_layers") if isinstance(model.get("substrate_layers"), dict) else {}
    material_ids = list(substrate.get("material_ids") or [])
    layer_ids = list(substrate.get("bundle_layer_ids") or [])
    if model.get("model_version") != MATERIAL_LOD_MODEL_VERSION or not material_ids or not layer_ids:
        return None
    arrays = load_raster_bundle_arrays(resolve_bundle_path(model.get("bundle_path"), storage_root), layer_ids)
    composition = _unpack_layers(arrays, layer_ids, len(material_ids))
    if composition is None:
        return None
    composition = composition / np.maximum(composition.sum(axis=0), 1e-6)[None]
    bounds = model.get("source_uv_bounds") if isinstance(model.get("source_uv_bounds"), dict) else {}
    return {
        "material_ids": material_ids,
        "composition": composition.astype(np.float32),
        "bounds": {
            "min_u": float(bounds.get("min_u", 0.0)),
            "max_u": float(bounds.get("max_u", 1.0)),
            "min_v": float(bounds.get("min_v", 0.0)),
            "max_v": float(bounds.get("max_v", 1.0)),
        },
        "wrap_x": bool(model.get("wrap_x")) and float(bounds.get("min_u", 0.0)) <= 1e-6 and float(bounds.get("max_u", 1.0)) >= 1.0 - 1e-6,
        "detail_level": int(model.get("detail_level", 0) or 0),
    }


def _province_index_rows(units, provinces):
    """Map unit labels to positions in the province list (-1 when absent)."""
    lookup = np.full(int(units.max()) + 1 if units.size else 1, -1, dtype=np.int64)
    for position, province in enumerate(provinces):
        unit = int(province.get("unit_index", -1))
        if 0 <= unit < lookup.size:
            lookup[unit] = position
    return lookup[np.asarray(units, dtype=np.int64)].tolist()


def _candidate_lookup(natural_material_model):
    return {
        str(item.get("material_id")): normalized_candidate(item)
        for item in (natural_material_model or {}).get("likely_materials") or []
        if isinstance(item, dict) and item.get("material_id")
    }


def _layer_role(material_id, candidate, cover_ids):
    if material_id in cover_ids:
        return "surface_cover"
    representation = str((candidate or {}).get("spatial_representation") or "")
    if representation == "surface_cover":
        return "surface_cover"
    return "bedrock"


def planet_circumference_m(heightmap, terrain=None, planet=None):
    """Planet circumference for metre-sized material structure on a map level.

    Regional heightmaps store their own width as ``circumference_m`` (the x
    extent their consumers divide by the grid width).  Units, faults and
    occurrence footprints are sized in metres on the planet, so reading that
    key made every child tile look 40-240x smaller than it is and collapsed
    its units to one or two per tile.
    """
    heightmap = heightmap if isinstance(heightmap, dict) else {}
    terrain = terrain if isinstance(terrain, dict) else {}
    planet = planet if isinstance(planet, dict) else {}
    detail_level = max(0, int(heightmap.get("map_detail_level", 0) or 0))
    return (
        float(heightmap.get("planet_circumference_m") or 0.0)
        or (float(heightmap.get("circumference_m") or 0.0) if detail_level <= 0 else 0.0)
        or float(terrain.get("circumference_m") or 0.0)
        or 2.0 * math.pi * float(planet.get("radius_m") or 6_371_000.0)
    )


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
    image_size=None,
    max_layers=DEFAULT_MATERIAL_LAYER_LIMIT,
    parent_material_model=None,
    tectonic_model=None,
    strike_degrees=0.0,
    occurrences=None,
):
    """Build and persist the material product for the map owning ``heightmap``.

    LOD0 classifies lithotectonic settings; child maps refine
    ``parent_material_model`` (strict N-1).  ``image_size`` is accepted for
    call compatibility; rasters follow the heightfield sample grid.
    """
    started = time.perf_counter()
    planet = planet if isinstance(planet, dict) else {}
    terrain = terrain if isinstance(terrain, dict) else {}
    heightmap = heightmap if isinstance(heightmap, dict) else {}
    atmosphere = atmosphere if isinstance(atmosphere, dict) else planet.get("atmosphere_model") or {}
    water_cycle = water_cycle if isinstance(water_cycle, dict) else planet.get("water_cycle_model") or {}
    surface_geomorphology = surface_geomorphology if isinstance(surface_geomorphology, dict) else planet.get("surface_geomorphology_model") or {}
    tectonic_model = tectonic_model if isinstance(tectonic_model, dict) else planet.get("tectonic_model") or {}
    rows = ((heightmap.get("sample_grid") or {}).get("rows") or [])
    if not rows or len(rows) < 2 or not natural_material_model or not (natural_material_model.get("likely_materials")):
        return {
            "status": "unavailable",
            "model_version": MATERIAL_HEATMAP_MODEL_VERSION,
            "reason": "heightmap_or_materials_missing",
            "layers": [],
        }
    detail_level = max(0, int(heightmap.get("map_detail_level", 0) or 0))
    output_root = Path(output_root or Path(__file__).resolve().parents[2] / "assets" / "maps" / "material_heatmaps")
    storage_root = Path(storage_root).resolve() if storage_root is not None else output_root.parents[2]
    planet_id = str(planet.get("id") or heightmap.get("planet_id") or "planet")
    bundle_path = output_root / f"{_safe_slug(planet_id)}{RASTER_BUNDLE_EXTENSION}"
    map_seed = str(heightmap.get("map_seed") or terrain.get("map_seed") or resolved_map_seed(planet.get("world_gen_seed"), planet_id=planet_id))
    material_distribution_seed = str(heightmap.get("material_distribution_seed") or map_seed)
    circumference_m = planet_circumference_m(heightmap, terrain, planet)
    surface_evolution = planet.get("surface_evolution_model")

    lineage = "planetary_lithotectonic_classification"
    parent = None
    if detail_level > 0:
        parent = load_parent_composition(parent_material_model, storage_root)
    if detail_level <= 0 or parent is None:
        product = derive_lod0_material_product(
            planet, natural_material_model, heightmap,
            tectonic_model=tectonic_model,
            water_cycle=water_cycle,
            surface_evolution=surface_evolution,
            atmosphere=atmosphere,
        )
        if detail_level > 0:
            lineage = "direct_classification_parent_material_unavailable"
            occurrence_layers, occurrence_roles = rasterize_occurrences(product["context"], occurrences, circumference_m)
            product["visible_ids"], product["visible"] = _overlay_occurrences(
                product["visible_ids"], product["visible"], occurrence_layers,
            )
            product["occurrence_roles"] = occurrence_roles
    else:
        product = derive_child_material_product(
            planet, natural_material_model, heightmap,
            parent=parent,
            level=detail_level,
            map_seed=material_distribution_seed,
            circumference_m=circumference_m,
            strike_degrees=strike_degrees,
            water_cycle=water_cycle,
            surface_evolution=surface_evolution,
            atmosphere=atmosphere,
            tectonic_model=tectonic_model,
            occurrences=occurrences,
        )
        lineage = "immediate_parent_composition_refinement"

    context = product["context"]
    height, width = context["shape"]
    candidates = _candidate_lookup(natural_material_model)
    cover_ids = {material_id for material_id in product["cover_materials"].values() if material_id}
    visible_ids = product["visible_ids"]
    visible = product["visible"]
    relative_bundle = _relative_or_absolute(bundle_path, storage_root=storage_root)

    dominant = visible.argmax(axis=0)
    dominant_counts = np.bincount(dominant.ravel(), minlength=len(visible_ids))
    map_colors = np.asarray([material_geological_map_color(material_id)[:3] for material_id in visible_ids], dtype=np.uint8)
    composite_rgba = np.empty((height, width, 4), dtype=np.uint8)
    composite_rgba[..., :3] = map_colors[dominant]
    composite_rgba[..., 3] = 255

    order = sorted(range(len(visible_ids)), key=lambda index: (-float(visible[index].mean()), visible_ids[index]))
    order = order[: max(1, int(max_layers or DEFAULT_MATERIAL_LAYER_LIMIT))]
    bundle_layers = [{
        "id": "composite",
        "role": "composite",
        "name": "Composite Material Map",
        "rgba": composite_rgba.tobytes(),
        "render_mode": "categorical_geological_map",
    }]
    layer_metadata = []
    cell_count = float(height * width)
    for index in order:
        material_id = visible_ids[index]
        candidate = candidates.get(material_id) or {}
        color = material_display_color(material_id, candidate.get("display_color"))
        geology_color = material_geological_map_color(material_id, candidate.get("geological_map_color"))
        layer_id = f"heatmap_{_safe_slug(material_id)}"
        fraction = visible[index]
        role = (product.get("occurrence_roles") or {}).get(material_id) or _layer_role(material_id, candidate, cover_ids)
        bundle_layers.append({
            "id": layer_id,
            "role": "material_layer",
            "material_id": material_id,
            "rgba": _fraction_rgba(color, fraction),
            "fraction_semantics": FRACTION_SEMANTICS,
        })
        layer_metadata.append({
            "id": layer_id,
            "material_id": material_id,
            "name": candidate.get("name") or material_id.replace("mat_", "").replace("_", " ").title(),
            "material_subclass": candidate.get("material_subclass"),
            "distribution_role": role,
            "display_semantics": FRACTION_SEMANTICS,
            "fraction_semantics": FRACTION_SEMANTICS,
            "visual_role": FRACTION_SEMANTICS,
            "formation_category": candidate.get("formation_category"),
            "spatial_representation": candidate.get("spatial_representation"),
            "bundle_path": relative_bundle,
            "bundle_layer_id": layer_id,
            "display_color": list(color[:3]),
            "geological_map_color": list(geology_color[:3]),
            "optical_surface_profile": material_optical_surface_profile(
                material_id,
                formation_category=candidate.get("formation_category"),
                material_subclass=candidate.get("material_subclass"),
                display_color=color,
                explicit=(
                    (MATERIAL_BY_ID.get(material_id) or {}).get("optical_surface_profile")
                    or candidate.get("optical_surface_profile")
                ),
            ),
            "confidence": round(float(candidate.get("confidence", 0.6) or 0.6), 3),
            "mean_fraction": round(float(fraction.mean()), 5),
            "peak_fraction": round(float(fraction.max()), 4),
            "coverage_fraction": round(float(dominant_counts[index] / cell_count), 4),
            "minimum_map_detail_level": int(candidate.get("minimum_map_detail_level", 0) or 0),
            "surface_expression_precomputed": True,
            "confidence_state": "inferred",
            "truth_state": "generated",
        })

    substrate_layers, substrate_layer_ids = _packed_layers("substrate", list(product["substrate"]))
    cover_arrays = [product["cover"][class_id] for class_id in COVER_CLASS_IDS]
    cover_layers, cover_layer_ids = _packed_layers("cover", cover_arrays)
    bundle_layers.extend(substrate_layers)
    bundle_layers.extend(cover_layers)
    setting_layer_ids = []
    if product.get("memberships") is not None:
        setting_layers, setting_layer_ids = _packed_layers("settings", list(product["memberships"]))
        bundle_layers.extend(setting_layers)
    bundle_layers.append({"id": "units", "role": "units", "rgba": _units_rgba(product["units"])})

    source_bounds = context["bounds"]
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
            "detail_level": detail_level,
            "source_uv_bounds": source_bounds,
            "projection": heightmap.get("projection", "equirectangular"),
            "generator_version": MATERIAL_HEATMAP_MODEL_VERSION,
            "source_heightfield_fingerprint": heightmap.get("source_heightfield_fingerprint"),
            "lineage": lineage,
        },
    )

    model = {
        "status": "generated",
        "model_version": MATERIAL_HEATMAP_MODEL_VERSION,
        "detail_level": detail_level,
        "projection": heightmap.get("projection", "equirectangular"),
        "map_seed": map_seed,
        "material_distribution_seed": material_distribution_seed,
        "source_uv_bounds": dict(source_bounds),
        "planet_id": planet_id,
        "source_heightfield_fingerprint": heightmap.get("source_heightfield_fingerprint"),
        "storage_format": RASTER_BUNDLE_FORMAT,
        "bundle_format_version": RASTER_BUNDLE_VERSION,
        "bundle_path": relative_bundle,
        "image_format": "rgba8888_bundle",
        "width_px": width,
        "height_px": height,
        "wrap_x": bool(heightmap.get("wrap_x", detail_level <= 0)),
        "wrap_y": bool(heightmap.get("wrap_y", False)),
        "truth_model": "areal_lithotectonic_composition",
        "lineage": lineage,
        "distribution_mode": "substrate_composition_under_process_cover",
        "fraction_semantics": FRACTION_SEMANTICS,
        "true_color_source": "areal_material_fractions",
        "material_color_source": "natural_material_model.optical_surface_profile.visible_reflectance",
        "surface_material_causality": "tectonic_setting_to_substrate_composition_to_process_cover_to_areal_true_color",
        "unit_purity": UNIT_PURITY_BY_LEVEL.get(detail_level, 0.0),
        "climate_source": context["climate_source"],
        "surface_geomorphology_version": surface_geomorphology.get("model_version"),
        "default_confidence_state": "inferred",
        "composite_layer": {
            "id": "heatmap_composite_materials",
            "name": "Composite Material Map",
            "bundle_path": relative_bundle,
            "bundle_layer_id": "composite",
            "render_mode": "categorical_geological_map",
            "render_contract": "dominant_visible_material",
            "visualization_purpose": "analytical_only_not_surface_reflectance",
            "contact_style": "renderer_soft_cartographic_boundary",
            "confidence_state": "inferred",
            "truth_state": "generated",
        },
        "layers": layer_metadata,
        "substrate_layers": {
            "material_ids": list(product["substrate_ids"]),
            "bundle_layer_ids": substrate_layer_ids,
            "encoding": "packed_rgba_fraction_x255",
        },
        "cover_layers": {
            "classes": list(COVER_CLASS_IDS),
            "materials": dict(product["cover_materials"]),
            "bundle_layer_ids": cover_layer_ids,
            "mean_fractions": {class_id: round(float(product["cover"][class_id].mean()), 5) for class_id in COVER_CLASS_IDS},
            "encoding": "packed_rgba_fraction_x255",
        },
        "unit_layer": {
            "bundle_layer_id": "units",
            "encoding": "rgb24_unit_index",
            "unit_count": int(product["units"].max()) + 1 if product["units"].size else 0,
        },
        "bundle_manifest": {
            "layer_count": len(manifest.get("layers") or []),
            "encoding": manifest.get("encoding"),
        },
    }
    if product.get("surface_routing_summary"):
        model["surface_routing"] = dict(product["surface_routing_summary"])
    if product.get("fault_traces"):
        model["fault_traces"] = list(product["fault_traces"])
    if product.get("memberships") is not None:
        model["setting_layers"] = {
            "setting_ids": list(SETTING_IDS),
            "bundle_layer_ids": setting_layer_ids,
            "encoding": "packed_rgba_fraction_x255",
        }
        memberships = product["memberships"]
        model["lithotectonic_summary"] = {
            "model_version": LITHOTECTONIC_MODEL_VERSION,
            "setting_area_fractions": {
                setting["id"]: round(float(memberships[index].mean()), 4)
                for index, setting in enumerate(SETTINGS)
            },
            "recipes": {
                setting_id: [[material_id, round(float(share), 4)] for material_id, share in recipe]
                for setting_id, recipe in (product.get("recipes") or {}).items()
            },
            "recipe_provenance": dict(product.get("recipe_provenance") or {}),
        }
    if detail_level <= 0:
        provinces, cards = province_table(
            product,
            planet_id=planet_id,
            natural_material_model=natural_material_model,
            crust_composition=((planet.get("world_gen_seed") or {}).get("crust_composition")),
            map_seed=map_seed,
        )
        retention = product["relief_retention"]
        model["province_model"] = {
            "status": "generated",
            "model_version": "lithotectonic-provinces-v1",
            "planet_id": planet_id,
            "map_seed": map_seed,
            "provinces": provinces,
            "body_ids": [card["id"] for card in cards if card.get("location_class") == "geologic_unit"],
            "cover_body_ids": [card["id"] for card in cards if card.get("location_class") == "surface_material_cover"],
            "relief_retention_rows": np.round(retention[::2, ::2].astype(np.float64), 4).tolist(),
            # Province index per cell (global UV grid, every second sample) so
            # soils and child maps can look up province chemistry directly.
            "province_index_rows": _province_index_rows(product["units"][::2, ::2], provinces),
            "element_budget_contract": "area_weighted_local_abundances_equal_global_crust_abundances",
            "source_material_catalog": "ontology_material_cards",
        }
        model["_pending_material_cards"] = cards
    else:
        units = product["units"]
        unit_materials = product.get("unit_material_index")
        model["unit_summary"] = {
            "unit_scale_m": product.get("unit_scale_m"),
            "unit_count": int(units.max()) + 1 if units.size else 0,
            "parent_material_ids": product.get("parent_material_ids"),
            "layered_fraction": (
                round(float(np.mean(product["layered_weight"])), 4)
                if product.get("layered_weight") is not None else 0.0
            ),
        }
        if unit_materials is not None and product.get("parent_material_ids"):
            counts = np.bincount(unit_materials.ravel(), minlength=len(product["parent_material_ids"]))
            model["unit_summary"]["unit_material_area_fractions"] = {
                material_id: round(float(counts[index] / cell_count), 4)
                for index, material_id in enumerate(product["parent_material_ids"])
                if counts[index]
            }
    model["generation_seconds"] = round(time.perf_counter() - started, 3)
    return model
