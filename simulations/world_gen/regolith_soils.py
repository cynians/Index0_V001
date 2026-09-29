"""Abiotic regolith and soil-state derivation from existing surface outputs."""

import math

import numpy as np


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, float(value)))


def _nearest_rows(rows, height, width, default):
    """Nearest-sample a same-footprint grid onto (height, width) cells."""
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], list) or not rows[0]:
        return np.full((height, width), default, dtype=np.float64)
    source_width = min(len(row) for row in rows)
    values = np.asarray([row[:source_width] for row in rows], dtype=np.float64)
    source_y = np.clip(np.rint(np.arange(height) * (values.shape[0] - 1) / max(1, height - 1)).astype(np.int64), 0, values.shape[0] - 1)
    source_x = np.clip(np.rint(np.arange(width) * (source_width - 1) / max(1, width - 1)).astype(np.int64), 0, source_width - 1)
    return np.nan_to_num(values[np.ix_(source_y, source_x)], nan=default)


def _province_elements(planet, heightmap, height, width):
    """Per-cell province element arrays (Ca, S, N, P) or None.

    Uses the LOD0 province index raster in global UV, so a regional child
    reads the chemistry of the provinces it actually covers.
    """
    placement = planet.get("geochemical_material_model") if isinstance(planet.get("geochemical_material_model"), dict) else {}
    provinces = placement.get("provinces") or []
    index_rows = placement.get("province_index_rows")
    if not provinces or not index_rows:
        return None
    index = np.asarray(index_rows, dtype=np.int64)
    bounds = heightmap.get("source_uv_bounds") if isinstance(heightmap.get("source_uv_bounds"), dict) else {}
    min_u = float(bounds.get("min_u", 0.0) or 0.0)
    max_u = float(bounds.get("max_u", 1.0) if bounds.get("max_u") is not None else 1.0)
    min_v = float(bounds.get("min_v", 0.0) or 0.0)
    max_v = float(bounds.get("max_v", 1.0) if bounds.get("max_v") is not None else 1.0)
    u = min_u + (max_u - min_u) * np.arange(width) / max(1, width - 1)
    v = min_v + (max_v - min_v) * np.arange(height) / max(1, height - 1)
    grid_height, grid_width = index.shape
    columns = np.rint(np.mod(u, 1.0) * (grid_width - 1)).astype(np.int64) % grid_width
    rows = np.clip(np.rint(np.clip(v, 0.0, 1.0) * (grid_height - 1)).astype(np.int64), 0, grid_height - 1)
    cell_index = index[np.ix_(rows, columns)]
    arrays = {}
    for symbol in ("Ca", "S", "N", "P"):
        lookup = np.asarray(
            [float((province.get("elements") or {}).get(symbol, 0.0) or 0.0) for province in provinces] + [np.nan]
        )
        arrays[symbol] = lookup[np.where(cell_index >= 0, cell_index, len(provinces))]
    return arrays


def derive_regolith_soil_model(planet, heightmap, water_cycle, surface_evolution, material_model):
    """Resolve parent material + climate + relief + time into abiotic soils.

    Biology is deliberately absent; a later biosphere model may amend organic
    carbon, nutrient cycling, aggregation, and bioturbation.
    """
    planet = planet if isinstance(planet, dict) else {}
    heightmap = heightmap if isinstance(heightmap, dict) else {}
    water_cycle = water_cycle if isinstance(water_cycle, dict) else {}
    surface_evolution = surface_evolution if isinstance(surface_evolution, dict) else {}
    material_model = material_model if isinstance(material_model, dict) else {}
    climate = water_cycle.get("climate_grid") if isinstance(water_cycle.get("climate_grid"), dict) else {}
    grid = heightmap.get("sample_grid") if isinstance(heightmap.get("sample_grid"), dict) else {}
    elevation_rows = grid.get("rows") or []
    if not elevation_rows:
        return {"status": "unavailable", "reason": "heightfield_missing"}
    height, width = len(elevation_rows), len(elevation_rows[0])
    process = surface_evolution.get("process_grid") if isinstance(surface_evolution.get("process_grid"), dict) else {}
    sea_level_value = heightmap.get("sea_level_m")
    sea_level = None if sea_level_value is None else float(sea_level_value)
    runoff_grid = water_cycle.get("runoff_grid") if isinstance(water_cycle.get("runoff_grid"), dict) else {}
    wetness_rows = runoff_grid.get("wetness_index_rows") or []
    surface_water = water_cycle.get("surface_water_grid") if isinstance(water_cycle.get("surface_water_grid"), dict) else {}
    surface_age_myr = max(0.0, float(planet.get("simulated_geology_age_myr", planet.get("surface_record_age_myr", 100.0)) or 100.0))
    age_factor = _clamp(math.log1p(surface_age_myr) / math.log(4501.0))
    elements = material_model.get("element_profile") if isinstance(material_model.get("element_profile"), dict) else {}

    elevation = np.asarray([row[:width] for row in elevation_rows], dtype=np.float64)
    open_water = _nearest_rows(surface_water.get("water_presence_rows"), height, width, 0.0) > 0.5
    water = open_water | (elevation <= sea_level if sea_level is not None else np.zeros(elevation.shape, dtype=bool))
    land = ~water
    land_cells = int(land.sum())

    local = _province_elements(planet, heightmap, height, width)

    def element(symbol):
        default = float(elements.get(symbol, 0.0) or 0.0)
        if local is None:
            return np.full((height, width), default)
        return np.where(np.isnan(local[symbol]), default, local[symbol])

    carbonate_buffer = np.clip(element("Ca") / 5.0, 0.0, 1.0)
    sulfur_acidity = np.clip(element("S") / 1.5, 0.0, 1.0)
    # Inventory potentials only: availability is resolved later by
    # biosphere weathering/cycling. Element profiles are percentages.
    parent_nitrogen = np.clip(np.log1p(np.maximum(0.0, element("N")) * 10.0) / math.log(2.0), 0.0, 1.0)
    parent_phosphorus = np.clip(np.log1p(np.maximum(0.0, element("P")) * 5.0) / math.log(2.0), 0.0, 1.0)
    temperature = _nearest_rows(climate.get("temperature_rows_k"), height, width, 273.15)
    precipitation = np.maximum(0.0, _nearest_rows(climate.get("annual_precipitation_rows_mm"), height, width, 0.0))
    infiltration = np.maximum(0.0, _nearest_rows(climate.get("annual_infiltration_rows_mm"), height, width, 0.0))
    weathering = np.clip(_nearest_rows(process.get("chemical_weathering_rows"), height, width, 0.0), 0.0, 1.0)
    deposition = np.clip(_nearest_rows(process.get("sediment_deposition_rows"), height, width, 0.0), 0.0, 1.0)
    erosion = np.clip(_nearest_rows(process.get("erosion_intensity_rows") or process.get("erosion_potential_rows"), height, width, 0.0), 0.0, 1.0)
    ice_rows = (heightmap.get("surface_masks") or {}).get("ice_rows") or []
    icy = _nearest_rows([[1.0 if value else 0.0 for value in row] for row in ice_rows], height, width, 0.0) > 0.5
    if wetness_rows:
        moisture = np.clip(_nearest_rows(wetness_rows, height, width, 0.0), 0.0, 1.0)
    else:
        moisture = np.clip((precipitation + infiltration * 0.7) / 1800.0, 0.0, 1.0)
    aridity = np.clip(1.0 - precipitation / np.maximum(180.0, (temperature - 245.0) * 42.0), 0.0, 1.0)
    depth_m = np.clip((weathering * 2.4 + deposition * 3.1 + age_factor * 0.55) * (1.0 - erosion * 0.72), 0.01, 6.0)
    depth_m = np.where(icy, depth_m * 0.55, depth_m)
    soil_classes = np.select(
        [
            icy,
            (deposition > 0.58) & (moisture > 0.25),
            (weathering > 0.56) & (temperature > 285.0) & (moisture > 0.45),
            aridity > 0.72,
            erosion > 0.62,
        ],
        [
            "glacial_till_or_frozen_regolith",
            "alluvial_abiotic_soil",
            "deep_weathered_saprolitic_soil",
            "arid_saline_regolith",
            "thin_colluvial_regolith",
        ],
        default="weathered_mineral_soil",
    )
    names, counts = np.unique(soil_classes[land], return_counts=True)
    classes = {str(name): int(count) for name, count in zip(names, counts)}
    clay = np.clip(weathering * 0.62 + deposition * 0.24, 0.0, 1.0)
    porosity = np.clip(0.18 + clay * 0.24 + deposition * 0.14 - depth_m * 0.012, 0.08, 0.62)
    permeability = np.clip((1.0 - clay) * (0.35 + porosity) * (1.0 - deposition * 0.28), 0.0, 1.0)
    ph = np.clip(7.1 + carbonate_buffer * 1.4 - moisture * sulfur_acidity * 2.0 - weathering * 0.7, 3.2, 10.5)
    salinity = np.clip(aridity * (0.25 + deposition * 0.55) + (1.0 - moisture) * sulfur_acidity * 0.16, 0.0, 1.0)

    def rows_of(values, water_value, digits):
        return np.round(np.where(land, values, water_value), digits).tolist()

    depth_rows = rows_of(depth_m, 0.0, 4)
    porosity_rows = rows_of(porosity, 0.0, 4)
    permeability_rows = rows_of(permeability, 0.0, 4)
    ph_rows = rows_of(ph, 7.0, 3)
    salinity_rows = rows_of(salinity, 1.0, 4)
    moisture_rows = rows_of(moisture, 1.0, 4)
    parent_nitrogen_rows = rows_of(parent_nitrogen, 0.0, 4)
    parent_phosphorus_rows = rows_of(parent_phosphorus, 0.0, 4)

    dominant = sorted(classes.items(), key=lambda row: (-row[1], row[0]))
    return {
        "status": "abiotic_soils_resolved",
        "model_version": "regolith-soils-v2-hydrology-coupled",
        "causal_inputs": ["parent_material", "climate", "topography", "surface_processes", "surface_record_age"],
        "biosphere_contribution": "excluded_pending_separate_design",
        "nutrient_status": "deferred_to_biomatter_system",
        "dominant_soil_classes": [{"id": name, "land_fraction": round(count / max(1, land_cells), 4)} for name, count in dominant[:6]],
        "grid": {
            "width": width, "height": height,
            "soil_depth_m_rows": depth_rows,
            "porosity_rows": porosity_rows,
            "relative_permeability_rows": permeability_rows,
            "ph_rows": ph_rows,
            "salinity_index_rows": salinity_rows,
            "soil_moisture_rows": moisture_rows,
            "parent_nitrogen_index_rows": parent_nitrogen_rows,
            "parent_phosphorus_index_rows": parent_phosphorus_rows,
        },
        "tracked_properties": ["depth", "porosity", "permeability", "pH", "salinity", "moisture", "parent_mineralogy", "parent_nitrogen_inventory", "parent_phosphorus_inventory"],
        "excluded_properties": ["organic_matter", "nutrient_availability", "fertility", "bioturbation"],
    }
