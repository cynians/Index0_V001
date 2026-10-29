"""Lazy Map/Biosphere bridge for the retained reference-free LOD4 candidate."""

from __future__ import annotations

from functools import lru_cache
import hashlib
import json
from pathlib import Path

import numpy as np

from simulations.world_gen.landscape_abstraction import _resize_bilinear, _resize_nearest
from simulations.world_gen.regolith_soils import derive_regolith_soil_model
from simulations.world_gen.regional_refinement import detail_level_spec
from simulations.world_gen.worldgen_bundle import read_worldgen_bundle_json


MAP_ID = "highest_lod_generated_example_map"
BIOSPHERE_ID = "biosphere_highest_lod_generated_example_map"
RECIPE_VERSION = "reference-free-landscape-biosphere-bridge-v1"
SEED = 29
EXTENT_M = 6000.0
PROJECT_ROOT = Path(__file__).resolve().parents[2]
BUNDLE_PATH = PROJECT_ROOT / "artifacts" / "reference_free_landscape_v1.i0wg"
ABSTRACTION_PATH = PROJECT_ROOT / "artifacts" / "reference_free_landscape_v1" / "abstraction.json"
CANDIDATE_PATH = PROJECT_ROOT / "artifacts" / "reference_free_landscape_v1" / "candidate_heightfields.npz"
PARENT_ENTRY = "regional/lod_03_local.json"


class ArrayRows(list):
    """A list-compatible immutable view that keeps numerical grids compact."""

    def __init__(self, values):
        super().__init__()
        self.values = np.asarray(values)

    def __len__(self):
        return int(self.values.shape[0])

    def __iter__(self):
        return iter(self.values)

    def __getitem__(self, item):
        return self.values[item]

    def __deepcopy__(self, memo):
        return self


def _rows(values, *, categorical=False):
    method = _resize_nearest if categorical else _resize_bilinear
    return method(values, (1001, 1001))


def _dilate(mask, radius):
    mask = np.asarray(mask, dtype=bool)
    result = mask.copy()
    height, width = mask.shape
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            if dx * dx + dy * dy > radius * radius:
                continue
            source_y0, source_y1 = max(0, -dy), min(height, height - dy)
            source_x0, source_x1 = max(0, -dx), min(width, width - dx)
            target_y0, target_y1 = source_y0 + dy, source_y1 + dy
            target_x0, target_x1 = source_x0 + dx, source_x1 + dx
            result[target_y0:target_y1, target_x0:target_x1] |= mask[source_y0:source_y1, source_x0:source_x1]
    return result


def recipe():
    return [
        RECIPE_VERSION,
        "retained LOD3 parent plus stochastic seed-29 LOD4 residual",
        "6km local Cartesian bridge; generated geographic bounds retained as provenance",
    ]


@lru_cache(maxsize=1)
def build_models():
    if not (BUNDLE_PATH.exists() and ABSTRACTION_PATH.exists() and CANDIDATE_PATH.exists()):
        raise FileNotFoundError("The retained reference-free landscape artifacts are incomplete")
    parent = read_worldgen_bundle_json(BUNDLE_PATH, PARENT_ENTRY)
    abstraction = json.loads(ABSTRACTION_PATH.read_text(encoding="utf-8"))
    with np.load(CANDIDATE_PATH) as candidate:
        elevation = np.asarray(candidate[f"seed_{SEED}"], dtype=np.float32)
    shape = elevation.shape
    if shape != (1001, 1001):
        raise ValueError(f"Expected a 1001x1001 retained candidate, received {shape}")

    broad = abstraction["broad_fields"]
    network = abstraction["feature_network"]
    valid = _resize_nearest(broad["terrain_valid_rows"], shape).astype(bool)
    patch = _resize_nearest(broad["landscape_patch_rows"], shape).astype(np.uint8)
    landcover = _resize_nearest(broad["dominant_landcover_rows"], shape).astype(np.int16)
    water = _resize_nearest(network["water_corridor_rows"], shape).astype(bool)
    channel = _resize_nearest(network["river_corridor_rows"], shape).astype(bool)
    wetland = _resize_nearest(network["wetland_rows"], shape).astype(bool)

    parent_climate = (parent.get("water_cycle_model") or {}).get("climate_grid") or {}
    continuous_climate_keys = (
        "temperature_rows_k",
        "annual_precipitation_rows_mm",
        "temperature_seasonality_rows_k",
        "seasonal_min_temperature_rows_k",
        "seasonal_max_temperature_rows_k",
        "annual_runoff_rows_mm",
        "annual_potential_evaporation_rows_mm",
        "annual_infiltration_rows_mm",
        "annual_groundwater_recharge_rows_mm",
        "annual_snowmelt_release_rows_mm",
        "seasonal_snow_fraction_rows",
    )
    climate_arrays = {
        key: _rows(parent_climate[key])
        for key in continuous_climate_keys
        if parent_climate.get(key)
    }
    koppen = _rows(parent_climate.get("koppen_rows") or [["ET"]], categorical=True)

    runoff = climate_arrays.get("annual_runoff_rows_mm", np.zeros(shape))
    evaporation = climate_arrays.get("annual_potential_evaporation_rows_mm", np.full(shape, 350.0))
    recharge = climate_arrays.get("annual_groundwater_recharge_rows_mm", np.zeros(shape))
    precipitation = climate_arrays.get("annual_precipitation_rows_mm", np.zeros(shape))
    supply = runoff + recharge * 0.7 + precipitation * 0.08
    wetness = np.clip(0.04 + supply / np.maximum(1.0, supply + evaporation) * 0.68, 0.0, 1.0)
    wetness[_dilate(water | channel, 3)] = np.maximum(wetness[_dilate(water | channel, 3)], 0.34)
    wetness[_dilate(water | channel, 1)] = np.maximum(wetness[_dilate(water | channel, 1)], 0.72)
    wetness[water] = 1.0

    gy, gx = np.gradient(elevation.astype(float), EXTENT_M / (shape[0] - 1), EXTENT_M / (shape[1] - 1))
    slope = np.hypot(gx, gy)
    exposure = np.clip((0.82 + 0.22 * gx - 0.30 * gy) / np.sqrt(1.0 + slope * slope), 0.08, 1.0)
    shade = np.clip((0.72 + 0.48 * gx - 0.42 * gy) / np.sqrt(1.0 + slope * slope), 0.25, 1.08)
    palette = np.asarray([
        (116, 112, 103), (46, 89, 112), (75, 104, 82), (119, 112, 82),
        (66, 94, 62), (116, 109, 92), (133, 126, 102),
    ], dtype=float)
    rgb = np.clip(palette[np.clip(patch, 0, len(palette) - 1)] * shade[..., None], 0, 255).astype(np.uint8)
    rgb[water] = (47, 91, 118)
    rgb[wetland & ~water] = (67, 103, 82)

    fingerprint = hashlib.sha256(
        f"{RECIPE_VERSION}:{abstraction['fingerprint']}:{SEED}".encode("utf-8")
    ).hexdigest()
    heightmap = {
        "status": "retained_generated_landscape",
        "model_version": RECIPE_VERSION,
        "input_fingerprint": fingerprint,
        "source_heightfield_fingerprint": abstraction["fingerprint"],
        "projection": "local_cartesian",
        "map_detail_level": 4,
        "wrap_x": False,
        "wrap_y": False,
        "region_width_m": EXTENT_M,
        "region_height_m": EXTENT_M,
        "sample_spacing_x_m": 6.0,
        "sample_spacing_y_m": 6.0,
        "min_elevation_m": float(np.nanmin(elevation[valid])),
        "max_elevation_m": float(np.nanmax(elevation[valid])),
        "sea_level_m": (parent.get("heightmap_model") or {}).get("sea_level_m"),
        "source_uv_bounds": (parent.get("heightmap_model") or {}).get("source_uv_bounds"),
        "sample_grid": {"width": 1001, "height": 1001, "rows": ArrayRows(elevation)},
        "surface_masks": {"terrain_valid_rows": ArrayRows(valid)},
        "abiotic_rgb_rows": ArrayRows(rgb),
        "artifact_source": {
            "bundle_path": str(BUNDLE_PATH.relative_to(PROJECT_ROOT)).replace("\\", "/"),
            "parent_entry": PARENT_ENTRY,
            "abstraction_path": str(ABSTRACTION_PATH.relative_to(PROJECT_ROOT)).replace("\\", "/"),
            "candidate_path": str(CANDIDATE_PATH.relative_to(PROJECT_ROOT)).replace("\\", "/"),
            "candidate_seed": SEED,
        },
    }
    climate_grid = {
        "width": 1001,
        "height": 1001,
        **{key: ArrayRows(value.astype(np.float32)) for key, value in climate_arrays.items()},
        "koppen_rows": ArrayRows(koppen),
        "source_uv_bounds": heightmap["source_uv_bounds"],
        "spatial_support_m": float(abstraction["spacing_m"]),
        "downscaling_contract": "parent climate interpolated to child coordinates; no invented 6m weather observations",
    }
    water_cycle = {
        "status": "generated_parent_hydrology_projected_to_lod4",
        "model_version": RECIPE_VERSION,
        "climate_grid": climate_grid,
        "rivers": list((parent.get("water_cycle_model") or {}).get("rivers") or []),
        "lakes": list((parent.get("water_cycle_model") or {}).get("lakes") or []),
        "runoff_grid": {
            "width": 1001,
            "height": 1001,
            "wetness_index_rows": ArrayRows(wetness.astype(np.float32)),
            "channel_presence_rows": ArrayRows(channel),
            "wetness_contract": "generated climate water balance plus inherited water proximity",
        },
        "surface_water_grid": {
            "width": 1001,
            "height": 1001,
            "water_presence_rows": ArrayRows(water),
            "depth_status": "unresolved_for_retained_candidate",
            "seasonal_state": "unresolved",
            "salinity": "unresolved",
        },
        "cross_lod_continuity": abstraction["contract"],
    }

    parent_for_soil = dict(parent)
    parent_water = dict(parent.get("water_cycle_model") or {})
    parent_water["runoff_grid"] = {
        "wetness_index_rows": ArrayRows(_resize_bilinear(wetness, (201, 201)))
    }
    parent_water["surface_water_grid"] = {
        "water_presence_rows": ArrayRows(_resize_nearest(water, (201, 201)).astype(bool))
    }
    parent_soil = derive_regolith_soil_model(
        parent_for_soil,
        parent["heightmap_model"],
        parent_water,
        parent.get("surface_evolution_model") or {},
        parent.get("natural_material_model") or {},
    )
    soil_grid = {}
    for key, values in (parent_soil.get("grid") or {}).items():
        if key in {"width", "height"}:
            continue
        soil_grid[key] = ArrayRows(_rows(values).astype(np.float32))
    soil_grid.update(width=1001, height=1001)
    soil = {
        **parent_soil,
        "status": "abiotic_soils_inherited_and_hydrology_refined",
        "grid": soil_grid,
        "spatial_support_m": float(abstraction["spacing_m"]),
        "nutrient_status": "deferred_to_biomatter_system",
        "excluded_properties": ["organic_matter", "nutrient_availability", "fertility", "bioturbation"],
    }
    return {
        "heightmap_model": heightmap,
        "water_cycle_model": water_cycle,
        "regolith_soil_model": soil,
        "landcover_model": {
            "status": "generated_climate_cover_proxy",
            "grid": {"width": 1001, "height": 1001, "class_rows": ArrayRows(landcover)},
            "interpretation": "abiotic/physiognomic proxy only; not a species roster",
        },
        "wetlands_model": {
            "status": "generated_hydrologic_opportunity",
            "grid": {"width": 1001, "height": 1001, "wetland_presence_rows": ArrayRows(wetland)},
        },
        "generated_environment_model": {
            "status": "reference_free",
            "derived": ["LOD4 terrain residual", "surface exposure", "hydrologic wetness", "abiotic soils"],
            "unknown": ["water depth and seasonal stage", "salinity", "organic matter", "nutrients", "individual organisms"],
        },
    }


def hydrate_entity(entity):
    if RECIPE_VERSION in (entity.get("map_generation_recipe") or []):
        for key, value in build_models().items():
            entity.setdefault(key, value)
    return entity


def target_entity():
    profile = detail_level_spec(4)
    profile.update(label="Generated highest-detail landscape bridge", measurement_floor_m=6.0)
    abstraction = json.loads(ABSTRACTION_PATH.read_text(encoding="utf-8"))
    return {
        "id": MAP_ID,
        "type": "location",
        "_dataset": "locations",
        "name": MAP_ID,
        "pretty_name": "Highest LOD Generated Example Map",
        "location_class": "site",
        "location_role": "generated_worldgen_biosphere_bridge",
        "map_coordinate_space": "site_meters",
        "map_detail_level": 4,
        "map_context_detail_level": 3,
        "map_detail_profile": profile,
        "map_generation_recipe": recipe(),
        "map_status": "retained generated landscape; lazy physical models",
        "bounds": {"type": "bbox", "min_x": 0.0, "max_x": EXTENT_M, "min_y": 0.0, "max_y": EXTENT_M},
        "geographic_source_bounds": abstraction["bounds"],
        "generation_parent_map_id": abstraction["source_map_id"],
        "generation_parent_fingerprint": abstraction["source_fingerprint"],
        "display_color": [102, 104, 83],
        "biosphere_entity_id": BIOSPHERE_ID,
        "biosphere_width_m": EXTENT_M,
        "biosphere_height_m": EXTENT_M,
        "biosphere_area_m2": EXTENT_M ** 2,
        "biosphere_initial_extent_m": EXTENT_M,
        "wiki_entry": "A retained reference-free World Gen LOD4 candidate in a local metre frame. Physical grids load only when Map or Biosphere opens it. Nutrition and organisms are deliberately absent.",
    }


def biosphere_overlay():
    return {
        "id": BIOSPHERE_ID,
        "type": "biosphere",
        "_dataset": "biospheres",
        "name": "Generated highest-LOD Biosphere overlay",
        "overlay_location": MAP_ID,
        "establishment_status": "abiotic",
        "inspection_introductions": [],
        "wiki_entry": "Abiotic inspection overlay. Species are not inferred from generated cover and nutrients await the biomatter system.",
    }
