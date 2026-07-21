"""Abiotic regolith and soil-state derivation from existing surface outputs."""

import math


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, float(value)))


def _sample(rows, x, y, default=0.0):
    try:
        return float(rows[y][x])
    except (IndexError, TypeError, ValueError):
        return float(default)


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
    temperature_rows = climate.get("temperature_rows_k") or []
    precipitation_rows = climate.get("annual_precipitation_rows_mm") or []
    infiltration_rows = climate.get("annual_infiltration_rows_mm") or []
    process = surface_evolution.get("process_grid") if isinstance(surface_evolution.get("process_grid"), dict) else {}
    weathering_rows = process.get("chemical_weathering_rows") or []
    deposition_rows = process.get("sediment_deposition_rows") or []
    erosion_rows = process.get("erosion_intensity_rows") or []
    ice_rows = ((heightmap.get("surface_masks") or {}).get("ice_rows") or [])
    sea_level = float(heightmap.get("sea_level_m", 0.0) or 0.0)
    surface_age_myr = max(0.0, float(planet.get("simulated_geology_age_myr", planet.get("surface_record_age_myr", 100.0)) or 100.0))
    age_factor = _clamp(math.log1p(surface_age_myr) / math.log(4501.0))
    elements = material_model.get("element_profile") if isinstance(material_model.get("element_profile"), dict) else {}
    carbonate_buffer = _clamp(float(elements.get("Ca", 0.0) or 0.0) / 5.0)
    sulfur_acidity = _clamp(float(elements.get("S", 0.0) or 0.0) / 1.5)

    depth_rows, porosity_rows, permeability_rows, ph_rows, salinity_rows = [], [], [], [], []
    classes = {}
    land_cells = 0
    for y in range(height):
        depth_row, porosity_row, permeability_row, ph_row, salinity_row = [], [], [], [], []
        for x in range(width):
            elevation = _sample(elevation_rows, x, y)
            if elevation <= sea_level:
                depth_row.append(0.0); porosity_row.append(0.0); permeability_row.append(0.0); ph_row.append(7.0); salinity_row.append(1.0)
                continue
            land_cells += 1
            temp = _sample(temperature_rows, x, y, 273.15)
            precip = max(0.0, _sample(precipitation_rows, x, y))
            infiltration = max(0.0, _sample(infiltration_rows, x, y))
            weathering = _clamp(_sample(weathering_rows, x, y))
            deposition = _clamp(_sample(deposition_rows, x, y))
            erosion = _clamp(_sample(erosion_rows, x, y))
            icy = bool(ice_rows and ice_rows[y][x])
            moisture = _clamp((precip + infiltration * 0.7) / 1800.0)
            aridity = _clamp(1.0 - precip / max(180.0, (temp - 245.0) * 42.0))
            depth_m = _clamp((weathering * 2.4 + deposition * 3.1 + age_factor * 0.55) * (1.0 - erosion * 0.72), 0.01, 6.0)
            if icy:
                soil_class = "glacial_till_or_frozen_regolith"
                depth_m *= 0.55
            elif deposition > 0.58 and moisture > 0.25:
                soil_class = "alluvial_abiotic_soil"
            elif weathering > 0.56 and temp > 285.0 and moisture > 0.45:
                soil_class = "deep_weathered_saprolitic_soil"
            elif aridity > 0.72:
                soil_class = "arid_saline_regolith"
            elif erosion > 0.62:
                soil_class = "thin_colluvial_regolith"
            else:
                soil_class = "weathered_mineral_soil"
            classes[soil_class] = classes.get(soil_class, 0) + 1
            clay = _clamp(weathering * 0.62 + deposition * 0.24)
            porosity = _clamp(0.18 + clay * 0.24 + deposition * 0.14 - depth_m * 0.012, 0.08, 0.62)
            permeability = _clamp((1.0 - clay) * (0.35 + porosity) * (1.0 - deposition * 0.28))
            ph = _clamp(7.1 + carbonate_buffer * 1.4 - moisture * sulfur_acidity * 2.0 - weathering * 0.7, 3.2, 10.5)
            salinity = _clamp(aridity * (0.25 + deposition * 0.55) + (1.0 - moisture) * sulfur_acidity * 0.16)
            depth_row.append(round(depth_m, 4)); porosity_row.append(round(porosity, 4)); permeability_row.append(round(permeability, 4)); ph_row.append(round(ph, 3)); salinity_row.append(round(salinity, 4))
        depth_rows.append(depth_row); porosity_rows.append(porosity_row); permeability_rows.append(permeability_row); ph_rows.append(ph_row); salinity_rows.append(salinity_row)

    dominant = sorted(classes.items(), key=lambda row: (-row[1], row[0]))
    return {
        "status": "abiotic_soils_resolved",
        "model_version": "regolith-soils-v1",
        "causal_inputs": ["parent_material", "climate", "topography", "surface_processes", "surface_record_age"],
        "biosphere_contribution": "excluded_pending_separate_design",
        "dominant_soil_classes": [{"id": name, "land_fraction": round(count / max(1, land_cells), 4)} for name, count in dominant[:6]],
        "grid": {
            "width": width, "height": height,
            "soil_depth_m_rows": depth_rows,
            "porosity_rows": porosity_rows,
            "relative_permeability_rows": permeability_rows,
            "ph_rows": ph_rows,
            "salinity_index_rows": salinity_rows,
        },
        "tracked_properties": ["depth", "porosity", "permeability", "pH", "salinity", "parent_mineralogy"],
    }
