"""Causal diagnostics for production world-generation products.

LOD contract: this module only observes models produced by the normal world
generator. It does not derive replacement terrain, climate, or tectonic data.
Its feature inventory makes parent truth, mechanism ownership, and expected
visibility across the detail chain explicit for representative tests.
"""

import copy


_FEATURE_SPECS = (
    {
        "id": "plate_tectonics",
        "source_models": ["tectonic_model.plates", "tectonic_model.boundary_segments"],
        "first_lod": 0,
        "last_distinguishable_lod": 3,
        "lower_lod_behavior": "aggregate plate ownership and boundary class",
        "representation": "spherical plates, curved boundaries, topology, and motion",
    },
    {
        "id": "continental_provinces",
        "source_models": ["tectonic_model.continental_province_model"],
        "first_lod": 0,
        "last_distinguishable_lod": 2,
        "lower_lod_behavior": "retain parent crustal affinity and age fields",
        "representation": "cratons, accreted terranes, failed rifts, and basins",
    },
    {
        "id": "mountain_systems",
        "source_models": ["tectonic_model.orogen_system_model", "heightmap_model.mountain_morphology"],
        "first_lod": 0,
        "last_distinguishable_lod": 4,
        "lower_lod_behavior": "inherit belt axis and add bounded ridge-scale relief",
        "representation": "orogen systems, uplift, foreland response, and resolved relief",
    },
    {
        "id": "hotspots_and_volcanic_arcs",
        "source_models": ["tectonic_model.hotspot_model", "heightmap_model.geology_model"],
        "first_lod": 0,
        "last_distinguishable_lod": 3,
        "lower_lod_behavior": "retain volcanic provenance while individual cones emerge later",
        "representation": "hotspot chains, volcanic arcs, and island construction",
    },
    {
        "id": "bathymetry_and_margins",
        "source_models": ["heightmap_model.sample_grid", "heightmap_model.shelf_sediment_model"],
        "first_lod": 0,
        "last_distinguishable_lod": 4,
        "lower_lod_behavior": "inherit sea datum, shelf, slope, ridge, and trench conditions",
        "representation": "continuous ocean basins plus bounded shelf/sediment margin ramp",
    },
    {
        "id": "climate_circulation",
        "source_models": ["water_cycle_model.climate_grid", "water_cycle_model.ocean_circulation_model"],
        "first_lod": 0,
        "last_distinguishable_lod": 4,
        "lower_lod_behavior": "inherit boundary climate and resolve local wind/moisture gradients",
        "representation": "seasonal temperature, meandering wind belts, moisture transport, and ocean currents",
    },
    {
        "id": "drainage_and_lakes",
        "source_models": ["water_cycle_model.drainage_network_model", "water_cycle_model.rivers"],
        "first_lod": 0,
        "last_distinguishable_lod": 7,
        "lower_lod_behavior": "major basins persist; tributaries and channels refine downstream",
        "representation": "flow accumulation, rivers, lakes, outlets, deltas, and estuaries",
    },
    {
        "id": "coastal_geomorphology",
        "source_models": ["coastal_geomorphology_model.segments"],
        "first_lod": 0,
        "last_distinguishable_lod": 5,
        "lower_lod_behavior": "retain parent shoreline chain and resolve beach/lagoon/estuary detail",
        "representation": "ordered shoreline chains, wave/tide exposure, and coastal assemblages",
    },
    {
        "id": "surface_processes",
        "source_models": ["surface_evolution_model.process_grid", "surface_evolution_model.sediment_budget"],
        "first_lod": 0,
        "last_distinguishable_lod": 7,
        "lower_lod_behavior": "inherit process regime and add bounded erosion/deposition residuals",
        "representation": "fluvial, weathering, aeolian, glacial, hillslope, and crater evolution",
    },
    {
        "id": "surface_material_expression",
        "source_models": ["material_heatmap_model.layers", "natural_material_model"],
        "first_lod": 0,
        "last_distinguishable_lod": 7,
        "lower_lod_behavior": "inherit parent material affinities and resolve local exposure/soil weights",
        "representation": "geologic materials, regolith, soils, weathering, and true-color inputs",
    },
    {
        "id": "geologic_history",
        "source_models": ["tectonic_model.geologic_history", "heightmap_model.simulated_age_myr"],
        "first_lod": 0,
        "last_distinguishable_lod": 2,
        "lower_lod_behavior": "retain age and maturity as continuous inherited fields",
        "representation": "pre-generation tectonic history, surface age, and process maturity",
    },
)


def _resolve_path(root, path):
    value = root
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _evidence(value):
    if isinstance(value, list):
        return {"present": bool(value), "count": len(value)}
    if isinstance(value, dict):
        return {"present": bool(value), "key_count": len(value)}
    return {"present": value is not None, "value": value} if value is not None else {"present": False}


def derive_causal_feature_diagnostics(planet):
    """Build a compact mechanism inventory from an already-generated planet."""
    planet = planet if isinstance(planet, dict) else {}
    features = []
    for spec in _FEATURE_SPECS:
        source_evidence = {
            path: _evidence(_resolve_path(planet, path))
            for path in spec["source_models"]
        }
        present_count = sum(
            int(item.get("present", False)) for item in source_evidence.values()
        )
        state = (
            "resolved"
            if present_count == len(source_evidence)
            else "partial"
            if present_count
            else "missing"
        )
        features.append({
            **copy.deepcopy(spec),
            "state": state,
            "source_evidence": source_evidence,
            "parent_truth": "LOD0 production model",
        })

    resolved = sum(item["state"] == "resolved" for item in features)
    return {
        "status": "causal_feature_inventory_diagnosed",
        "schema_version": 1,
        "ownership": "production_worldgen_models_only",
        "feature_count": len(features),
        "resolved_feature_count": resolved,
        "partial_feature_count": sum(item["state"] == "partial" for item in features),
        "missing_feature_count": sum(item["state"] == "missing" for item in features),
        "features": features,
    }

