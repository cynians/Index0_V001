"""Deterministic high-detail target map for BioSim development.

The fixture deliberately uses worldgen's LOD and model nomenclature.  It is an
authored scientific reference fixture, not a claim that current worldgen can
derive these 10 m fields from its planetary grid.
"""

from __future__ import annotations

import hashlib
import json
import math


REFERENCE_SITE_ID = "reference_biosphere_lod4_catchment"


def _fingerprint(value):
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _rows(size, fn, digits=5):
    return [
        [round(float(fn(x / max(1, size - 1), y / max(1, size - 1))), digits) for x in range(size)]
        for y in range(size)
    ]


def build_reference_site_models(size=101):
    """Return a coherent LOD4 site with one catchment and habitat gradient."""
    size = max(8, int(size))

    def stream_x(v):
        return 0.47 + 0.07 * math.sin(v * math.tau * 1.35)

    def elevation(u, v):
        ridge = 24.0 * math.exp(-(((u - 0.18) / 0.16) ** 2 + ((v - 0.42) / 0.55) ** 2))
        basin = 10.0 * math.exp(-(((u - 0.73) / 0.22) ** 2 + ((v - 0.70) / 0.20) ** 2))
        channel = 7.0 * math.exp(-((u - stream_x(v)) / 0.035) ** 2)
        return 118.0 + 20.0 * (1.0 - v) + ridge - basin - channel

    def channel_distance(u, v):
        return abs(u - stream_x(v))

    height_rows = _rows(size, elevation, 4)
    min_elevation = min(min(row) for row in height_rows)
    max_elevation = max(max(row) for row in height_rows)
    porosity_rows = _rows(size, lambda u, v: 0.31 + 0.10 * u + 0.07 * math.exp(-(channel_distance(u, v) / 0.08) ** 2))
    permeability_rows = _rows(size, lambda u, v: 0.72 - 0.40 * u - 0.18 * math.exp(-(channel_distance(u, v) / 0.09) ** 2))
    soil_depth_rows = _rows(size, lambda u, v: 0.45 + 1.25 * u + 0.75 * math.exp(-(channel_distance(u, v) / 0.10) ** 2), 4)
    ph_rows = _rows(size, lambda u, v: 5.7 + 1.25 * u)
    salinity_rows = _rows(size, lambda u, v: 0.015 + 0.035 * u)
    temperature_rows = _rows(size, lambda u, v: 289.5 + 2.2 * v - 0.025 * (elevation(u, v) - 118.0), 4)
    precipitation_rows = _rows(size, lambda u, v: 790.0 + 260.0 * v + 90.0 * (1.0 - u), 3)
    koppen_rows = [["Cfb" if y < int(size * 0.70) else "Cfa" for _x in range(size)] for y in range(size)]
    solar_rows = _rows(size, lambda u, v: 0.83 + 0.14 * u - 0.06 * math.cos(v * math.pi), 5)

    heightmap = {
        "status": "authored_reference_fixture",
        "model_version": "biosphere-reference-height-v1",
        "map_detail_level": 4,
        "detail_level_name": "site",
        "projection": "local_cartesian",
        "wrap_x": False,
        "region_width_m": 1000.0,
        "region_height_m": 1000.0,
        "sample_spacing_x_m": 10.0,
        "sample_spacing_y_m": 10.0,
        "parent_map_id": "reference_biosphere_lod3_local_catchment",
        "source_uv_bounds": {"min_u": 0.42, "max_u": 0.43, "min_v": 0.51, "max_v": 0.52},
        "sample_grid": {"width": size, "height": size, "rows": height_rows},
        "min_elevation_m": min_elevation,
        "max_elevation_m": max_elevation,
        "sea_level_m": 0.0,
    }
    heightmap["input_fingerprint"] = _fingerprint(heightmap)

    climate_grid = {
        "width": size,
        "height": size,
        "source_uv_bounds": heightmap["source_uv_bounds"],
        "temperature_rows_k": temperature_rows,
        "annual_precipitation_rows_mm": precipitation_rows,
        "temperature_seasonality_rows_k": _rows(size, lambda _u, _v: 14.0, 2),
        "koppen_rows": koppen_rows,
        "surface_solar_exposure_rows": solar_rows,
    }
    water_cycle = {
        "status": "authored_reference_fixture",
        "model_version": "biosphere-reference-water-cycle-v1",
        "hydrology_cycle": "active",
        "liquid_water_possible": True,
        "climate_grid": climate_grid,
        "runoff_grid": {
            "channel_presence_rows": _rows(
                size,
                lambda u, v: math.exp(-(channel_distance(u, v) / 0.028) ** 2),
            ),
            "wetness_index_rows": _rows(
                size,
                lambda u, v: min(1.0, 0.18 + 0.55 * v + 0.62 * math.exp(-(channel_distance(u, v) / 0.09) ** 2)),
            ),
        },
    }
    regolith = {
        "status": "authored_reference_fixture",
        "model_version": "biosphere-reference-regolith-v1",
        "biosphere_contribution": "excluded_pending_runtime_biosphere",
        "dominant_soil_classes": [
            {"id": "temperate_loam", "land_fraction": 0.58},
            {"id": "riparian_clay_loam", "land_fraction": 0.24},
            {"id": "sandy_ridge_soil", "land_fraction": 0.18},
        ],
        "grid": {
            "width": size,
            "height": size,
            "soil_depth_m_rows": soil_depth_rows,
            "porosity_rows": porosity_rows,
            "relative_permeability_rows": permeability_rows,
            "ph_rows": ph_rows,
            "salinity_index_rows": salinity_rows,
        },
    }
    river_points = [
        [round(stream_x(index / 40) * 1000.0, 2), round(index / 40 * 1000.0, 2)]
        for index in range(41)
    ]
    river_model = {
        "status": "authored_reference_fixture",
        "model_version": "biosphere-reference-river-v1",
        "rivers": [{
            "id": "reference_site_stream",
            "stream_order": 2,
            "mean_width_m": 4.5,
            "mean_discharge_m3_s": 0.8,
            "points_m": river_points,
        }],
    }
    material_model = {
        "status": "authored_reference_fixture",
        "dominant_materials": ["mat_sandstone", "mat_silt", "mat_clay"],
    }
    surface_evolution = {
        "status": "authored_reference_fixture",
        "process_grid": {
            "erosion_intensity_rows": _rows(size, lambda u, v: 0.12 + 0.42 * (1.0 - u) + 0.18 * math.exp(-(channel_distance(u, v) / 0.07) ** 2)),
        },
    }
    true_color = {
        "status": "authored_reference_fixture",
        "model_version": "biosphere-reference-abiotic-true-color-v1",
        "vegetation": False,
        "vegetation_policy": "supplied_by_biosphere_runtime",
        "heightfield_fingerprint": heightmap["input_fingerprint"],
    }
    return {
        "heightmap_model": heightmap,
        "water_cycle_model": water_cycle,
        "koppen_climate_model": {"status": "authored_reference_fixture", "climate_grid": climate_grid},
        "river_model": river_model,
        "regolith_soil_model": regolith,
        "natural_material_model": material_model,
        "material_heatmap_model": {"status": "authored_reference_fixture", "materials": material_model["dominant_materials"]},
        "surface_evolution_model": surface_evolution,
        "true_color_model": true_color,
    }


def reference_site_worldgen_context(size=101):
    models = build_reference_site_models(size=size)
    source = {
        "id": REFERENCE_SITE_ID,
        "name": "Temperate Catchment BioSim Reference Site",
        "type": "location",
        "location_class": "site",
        "worldgen_lod": 4,
        "generation_status": "authored_reference_fixture",
        "bounds": {"type": "bbox", "min_x": 0.0, "max_x": 1000.0, "min_y": 0.0, "max_y": 1000.0},
        **models,
    }
    return {
        "source_entity_id": REFERENCE_SITE_ID,
        "source_name": source["name"],
        "source_entity": source,
        "heightmap": models["heightmap_model"],
        "hydrology": {"liquid_water_possible": True, "cycle": "active"},
        "environment": {"tags": ["temperate", "seasonal", "riparian"]},
        "water_cycle": models["water_cycle_model"],
        "koppen_climate": models["koppen_climate_model"],
        "rivers": models["river_model"],
        "materials": models["natural_material_model"],
        "material_heatmap": models["material_heatmap_model"],
        "regolith_soil": models["regolith_soil_model"],
        "surface_evolution": models["surface_evolution_model"],
        "true_color": models["true_color_model"],
    }


def reference_site_launch_context(size=101):
    return {
        "patch_name": "Temperate Catchment BioSim Reference Site",
        "map_size_m": 1000.0,
        "biosphere_width_m": 1000.0,
        "biosphere_height_m": 1000.0,
        "biosphere_area_m2": 1_000_000.0,
        "sections_per_side": 10,
        "subsections_per_section_side": 10,
        "scientific_cell_size_m": 10.0,
        "source_bounds": {"type": "bbox", "min_x": 0.0, "max_x": 1000.0, "min_y": 0.0, "max_y": 1000.0},
        "worldgen_context": reference_site_worldgen_context(size=size),
        "reference_fixture": True,
    }
