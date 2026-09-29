"""Quantitative diagnostics for causal planetary geography."""

import math


MODEL_VERSION = "worldgen-realism-audit-v2"


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, float(value)))


def _coastline_complexity(heightmap):
    rows = ((heightmap.get("sample_grid") or {}).get("rows")) or []
    sea_level = heightmap.get("sea_level_m")
    if sea_level is None or not rows or not rows[0]:
        return 0.0
    height, width = len(rows), len(rows[0])
    land_cells = 0
    transitions = 0
    for y, row in enumerate(rows):
        for x, value in enumerate(row):
            land = float(value) >= float(sea_level)
            land_cells += int(land)
            east = float(row[(x + 1) % width]) >= float(sea_level)
            south = float(rows[min(height - 1, y + 1)][x]) >= float(sea_level)
            transitions += int(land != east) + int(land != south)
    return transitions / max(1.0, math.sqrt(land_cells))


def derive_worldgen_realism_metrics(tectonic_model, heightmap, water_cycle, surface_evolution=None):
    tectonic_model = tectonic_model if isinstance(tectonic_model, dict) else {}
    heightmap = heightmap if isinstance(heightmap, dict) else {}
    water_cycle = water_cycle if isinstance(water_cycle, dict) else {}
    surface_evolution = surface_evolution if isinstance(surface_evolution, dict) else {}
    plates = list(tectonic_model.get("plates") or [])
    segments = list(tectonic_model.get("boundary_segments") or [])
    areas = [float(plate.get("area_fraction", 0.0) or 0.0) for plate in plates]
    mean_area = sum(areas) / max(1, len(areas))
    area_cv = (
        math.sqrt(sum((area - mean_area) ** 2 for area in areas) / len(areas)) / max(1e-9, mean_area)
        if areas else 0.0
    )
    local_kinds = {segment.get("kind") for segment in segments if segment.get("kind")}
    subduction_segments = [segment for segment in segments if segment.get("kind") == "subduction"]
    polarity_fraction = sum(bool(segment.get("subducting_plate") and segment.get("overriding_plate")) for segment in subduction_segments) / max(1, len(subduction_segments))
    age_rows = ((tectonic_model.get("lithosphere_grid") or {}).get("ocean_floor_age_rows_myr")) or []
    ocean_ages = [float(value) for row in age_rows for value in row if 0.0 <= float(value) <= 220.0]
    age_span = (max(ocean_ages) - min(ocean_ages)) if ocean_ages else 0.0
    hypsometry = heightmap.get("hypsometry_summary") or {}
    drainage = water_cycle.get("drainage_network_model") or {}
    feedback_iterations = len(surface_evolution.get("feedback_iterations") or [])
    lakes = list(drainage.get("lakes") or [])
    lake_area_fraction = float(drainage.get("lake_area_fraction", 0.0) or 0.0)
    largest_lake_fraction = float(drainage.get("largest_lake_area_fraction", 0.0) or 0.0)
    endorheic_lake_fraction = float(drainage.get("endorheic_lake_fraction", 0.0) or 0.0)
    if lakes and lake_area_fraction <= 0.0:
        lake_area_fraction = sum(float(lake.get("area_fraction", lake.get("cell_fraction", 0.0)) or 0.0) for lake in lakes)
        largest_lake_fraction = max(float(lake.get("area_fraction", lake.get("cell_fraction", 0.0)) or 0.0) for lake in lakes)
        endorheic_lake_fraction = sum(bool(lake.get("endorheic")) for lake in lakes) / len(lakes)
    land_fraction = float(hypsometry.get("land_fraction", 0.0) or 0.0)
    ocean_fraction = float(hypsometry.get("ocean_fraction", 0.0) or 0.0)
    if land_fraction <= 0.0 and ocean_fraction <= 0.0:
        rows = ((heightmap.get("sample_grid") or {}).get("rows")) or []
        sea_level = heightmap.get("sea_level_m")
        values = [float(value) for row in rows for value in row]
        if values and sea_level is not None:
            land_fraction = sum(value >= float(sea_level) for value in values) / len(values)
            ocean_fraction = 1.0 - land_fraction
    mobile_lid = bool(plates and segments)
    mixed_surface = land_fraction >= 0.03 and ocean_fraction >= 0.03
    metrics = {
        "plate_area_coefficient_of_variation": round(area_cv, 3),
        "local_boundary_regime_count": len(local_kinds),
        "triple_junction_count": len((tectonic_model.get("plate_topology") or {}).get("triple_junctions") or []),
        "subduction_polarity_fraction": round(polarity_fraction, 3),
        "ocean_floor_age_span_myr": round(age_span, 1),
        "coastline_complexity_index": round(_coastline_complexity(heightmap), 3),
        "deep_basin_fraction": float(hypsometry.get("deep_basin_fraction_below_minus_2000m", 0.0) or 0.0),
        "mountain_fraction": float(hypsometry.get("mountain_fraction_above_2000m", 0.0) or 0.0),
        "continental_shelf_fraction": float(hypsometry.get("continental_shelf_fraction", 0.0) or 0.0),
        "maximum_stream_order": int(drainage.get("maximum_stream_order", 0) or 0),
        "lake_outlet_fraction": float(drainage.get("lake_outlet_fraction", 0.0) or 0.0),
        "lake_area_fraction": round(lake_area_fraction, 6),
        "largest_lake_area_fraction": round(largest_lake_fraction, 6),
        "endorheic_lake_fraction": round(endorheic_lake_fraction, 3),
        "delta_count": int(drainage.get("delta_count", 0) or 0),
        "climate_landscape_feedback_iterations": feedback_iterations,
    }
    checks = {
        "closed_plate_topology": not mobile_lid or bool((tectonic_model.get("plate_topology") or {}).get("closed_surface")),
        "multiple_local_boundary_regimes": not mobile_lid or len(local_kinds) >= 3,
        "subduction_polarity_resolved": not mobile_lid or not subduction_segments or polarity_fraction >= 0.95,
        "ocean_floor_has_age_gradient": not mobile_lid or age_span >= 40.0,
        "bimodal_relief_present": not (mobile_lid and mixed_surface) or (metrics["deep_basin_fraction"] >= 0.08 and metrics["mountain_fraction"] >= 0.005),
        "branching_drainage_present": not (water_cycle.get("hydrology_enabled") and land_fraction >= 0.03) or metrics["maximum_stream_order"] >= 2,
        "lake_coverage_within_broad_planetary_bounds": not mixed_surface or (lake_area_fraction <= 0.015 and largest_lake_fraction <= 0.004),
        "iterated_climate_landscape_coupling": feedback_iterations >= 2,
    }
    applicability = {
        "closed_plate_topology": mobile_lid,
        "multiple_local_boundary_regimes": mobile_lid,
        "subduction_polarity_resolved": mobile_lid,
        "ocean_floor_has_age_gradient": mobile_lid,
        "bimodal_relief_present": mobile_lid and mixed_surface,
        "branching_drainage_present": bool(water_cycle.get("hydrology_enabled") and land_fraction >= 0.03),
        "lake_coverage_within_broad_planetary_bounds": bool(water_cycle.get("hydrology_enabled") and mixed_surface),
        "iterated_climate_landscape_coupling": True,
    }
    applicable_checks = [key for key, applies in applicability.items() if applies]
    return {
        "status": "audited",
        "model_version": MODEL_VERSION,
        "metrics": metrics,
        "checks": checks,
        "applicability": applicability,
        "passed_check_fraction": round(sum(bool(checks[key]) for key in applicable_checks) / max(1, len(applicable_checks)), 3),
        "warnings": [key for key in applicable_checks if not checks[key]],
    }
