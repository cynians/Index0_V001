"""Derive the optically active skin above a planet's material inventory."""

from __future__ import annotations

import hashlib

from simulations.world_gen.surface_geomorphology import (
    derive_surface_material_partition_fields,
)

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None


SURFACE_EXPOSURE_MODEL_VERSION = "surface-exposure-v2"


def _clamp(value, low=0.0, high=1.0):
    try:
        value = float(value)
    except (TypeError, ValueError):
        value = low
    return max(low, min(high, value))


def _mean(model, key, fallback=0.0):
    values = model.get("process_means") if isinstance(model, dict) else {}
    if not isinstance(values, dict):
        return float(fallback)
    aliases = {
        "chemical_weathering": ("chemical_weathering", "weathering"),
        "aeolian_transport": ("aeolian_transport", "aeolian"),
        "sediment_deposition": ("sediment_deposition", "deposition"),
        "erosion_potential": ("erosion_potential", "erosion"),
        "glacial_erosion": ("glacial_erosion", "glacial"),
    }
    for candidate in aliases.get(key, (key,)):
        if candidate in values:
            return _clamp(values.get(candidate))
    return float(fallback)


def _visual_role(layer):
    role = str(layer.get("distribution_role") or "")
    representation = str(layer.get("spatial_representation") or "")
    if role in {"bedrock", "local_lithology"} or representation == "bedrock_unit":
        return "substrate"
    if role == "surface_cover" or representation == "surface_cover":
        return "mobile_or_regolith_cover"
    if role == "mineral_constituent" or representation == "constituent_abundance":
        return "intimate_substrate_component"
    return "bounded_exposure"


def _process_driver(formation_category):
    category = str(formation_category or "")
    if category in {"aeolian_sediment", "pyroclastic_deposit"}:
        return "aeolian_transport"
    if category in {
        "fluvial_sediment", "littoral_sediment", "clastic_sedimentary_basin",
    }:
        return "sediment_deposition"
    if category == "colluvial_sediment":
        return "colluvial_deposition"
    if category in {"evaporite_basin"}:
        return "arid_basin"
    if category in {"weathering_clay", "saprolitic_regolith"}:
        return "chemical_weathering"
    if category in {
        "lateritic_regolith", "residual_bauxite", "nickel_laterite",
        "iron_weathering", "duricrust",
    }:
        return "oxidative_weathering"
    if category == "glacial_sediment":
        return "glacial_erosion"
    if category == "impact_material":
        return "impact_gardening"
    if category == "volatile_ice":
        return "ice_stability"
    if category == "sulfur_surface":
        return "volcanic_resurfacing"
    return "geological_exposure"


def derive_surface_exposure_model(
    planet,
    *,
    heightmap=None,
    material_heatmap_model=None,
    water_cycle=None,
    surface_evolution=None,
    surface_geomorphology=None,
):
    """Return a compact recipe for substrate/regolith/cover exposure.

    Per-pixel material suitability already lives in the raster bundle.  This
    model records how those fields are interpreted without duplicating large
    grids in the ontology.
    """
    planet = planet if isinstance(planet, dict) else {}
    heightmap = (
        heightmap
        if isinstance(heightmap, dict)
        else planet.get("heightmap_model") or {}
    )
    material_heatmap_model = (
        material_heatmap_model
        if isinstance(material_heatmap_model, dict)
        else planet.get("material_heatmap_model") or {}
    )
    water_cycle = (
        water_cycle
        if isinstance(water_cycle, dict)
        else planet.get("water_cycle_model") or {}
    )
    surface_evolution = (
        surface_evolution
        if isinstance(surface_evolution, dict)
        else planet.get("surface_evolution_model") or {}
    )
    surface_geomorphology = (
        surface_geomorphology
        if isinstance(surface_geomorphology, dict)
        else planet.get("surface_geomorphology_model") or {}
    )
    layers = []
    for layer in material_heatmap_model.get("layers") or []:
        if not isinstance(layer, dict) or not layer.get("material_id"):
            continue
        visual_role = _visual_role(layer)
        layers.append({
            "material_id": str(layer["material_id"]),
            "name": layer.get("name") or layer["material_id"],
            "distribution_role": layer.get("distribution_role"),
            "formation_category": layer.get("formation_category"),
            "spatial_representation": layer.get("spatial_representation"),
            "visual_role": visual_role,
            "process_driver": _process_driver(layer.get("formation_category")),
            "maximum_visible_fraction": (
                1.0
                if visual_role in {"substrate", "mobile_or_regolith_cover"}
                else 0.22
                if visual_role == "intimate_substrate_component"
                else 0.38
            ),
            "surface_expression_precomputed": bool(
                layer.get("surface_expression_precomputed")
            ),
            "topographic_driver": layer.get("topographic_driver"),
            "optical_surface_profile": layer.get("optical_surface_profile"),
            "bundle_path": layer.get("bundle_path"),
            "bundle_layer_id": layer.get("bundle_layer_id"),
            "confidence": layer.get("confidence"),
        })

    process_means = {
        "chemical_weathering": round(
            _mean(surface_evolution, "chemical_weathering"), 5
        ),
        "aeolian_transport": round(
            _mean(surface_evolution, "aeolian_transport"), 5
        ),
        "sediment_deposition": round(
            _mean(surface_evolution, "sediment_deposition"), 5
        ),
        "erosion_potential": round(
            _mean(surface_evolution, "erosion_potential"), 5
        ),
        "glacial_erosion": round(
            _mean(surface_evolution, "glacial_erosion"), 5
        ),
    }
    signature = hashlib.sha256(
        repr([
            heightmap.get("source_heightfield_fingerprint"),
            material_heatmap_model.get("material_distribution_seed"),
            [
                (
                    layer.get("material_id"),
                    layer.get("formation_category"),
                    layer.get("visual_role"),
                )
                for layer in layers
            ],
            process_means,
            surface_geomorphology.get("input_fingerprint"),
        ]).encode("utf-8")
    ).hexdigest()
    return {
        "status": "derived",
        "model_version": SURFACE_EXPOSURE_MODEL_VERSION,
        "truth_state": "derived_surface_state",
        "model": "stratified_substrate_regolith_mobile_cover",
        "source_heightfield_fingerprint": heightmap.get(
            "source_heightfield_fingerprint"
        ),
        "source_material_model_version": material_heatmap_model.get(
            "model_version"
        ),
        "source_water_cycle_version": water_cycle.get("model_version"),
        "source_surface_evolution_version": surface_evolution.get(
            "model_version"
        ),
        "source_surface_geomorphology_version": surface_geomorphology.get(
            "model_version"
        ),
        "process_means": process_means,
        "endmembers": layers,
        "endmember_count": len(layers),
        "maximum_endmembers_per_pixel": 4,
        "fraction_contract": "normalized_within_stratum",
        "strata": [
            "substrate",
            "weathering_regolith",
            "mobile_cover",
            "volatile_or_biosphere_cover",
        ],
        "exposure_rules": {
            "bedrock_increases_with": ["ridge", "scarp", "slope", "erosion"],
            "bedrock_decreases_with": [
                "deposition", "aeolian_cover", "chemical_weathering",
            ],
            "mobile_cover_increases_with": [
                "valley", "alluvial_deposition", "colluvial_footslope",
                "aeolian_transport", "low_slope",
            ],
            "wet_surface_response": "material_specific_darkening",
            "airless_age_response": "material_specific_space_weathering",
        },
        "input_fingerprint": signature,
    }


def _resample(values, target_h, target_w):
    values = np.asarray(values, dtype=np.float32)
    if values.ndim != 2 or values.shape[0] < 1 or values.shape[1] < 1:
        return np.zeros((target_h, target_w), dtype=np.float32)
    source_h, source_w = values.shape
    if (source_h, source_w) == (target_h, target_w):
        return values.copy()
    ys = np.linspace(0.0, max(0, source_h - 1), target_h, dtype=np.float32)
    xs = np.linspace(0.0, max(0, source_w - 1), target_w, dtype=np.float32)
    y0 = np.floor(ys).astype(np.int32)
    x0 = np.floor(xs).astype(np.int32)
    y1 = np.minimum(source_h - 1, y0 + 1)
    x1 = np.minimum(source_w - 1, x0 + 1)
    fy = (ys - y0)[:, None]
    fx = (xs - x0)[None, :]
    top = (
        values[y0[:, None], x0[None, :]] * (1.0 - fx)
        + values[y0[:, None], x1[None, :]] * fx
    )
    bottom = (
        values[y1[:, None], x0[None, :]] * (1.0 - fx)
        + values[y1[:, None], x1[None, :]] * fx
    )
    return top * (1.0 - fy) + bottom * fy


def _rows(model, group, key):
    container = model.get(group) if isinstance(model, dict) else {}
    rows = container.get(key) if isinstance(container, dict) else None
    if isinstance(rows, list) and rows and isinstance(rows[0], list):
        return rows
    return None


def derive_surface_exposure_fields(
    heightmap,
    exposure_model,
    *,
    water_cycle=None,
    surface_evolution=None,
    surface_geomorphology=None,
    target_size,
):
    """Resolve process fields used by the optical compositor."""
    if np is None:
        return {}
    target_w, target_h = int(target_size[0]), int(target_size[1])
    target_w, target_h = max(2, target_w), max(1, target_h)
    heightmap = heightmap if isinstance(heightmap, dict) else {}
    exposure_model = exposure_model if isinstance(exposure_model, dict) else {}
    water_cycle = water_cycle if isinstance(water_cycle, dict) else {}
    surface_evolution = (
        surface_evolution if isinstance(surface_evolution, dict) else {}
    )
    surface_geomorphology = (
        surface_geomorphology if isinstance(surface_geomorphology, dict) else {}
    )

    elevation_rows = ((heightmap.get("sample_grid") or {}).get("rows") or [])
    elevation = _resample(elevation_rows, target_h, target_w)
    spacing_x = max(
        1.0,
        float(
            heightmap.get("sample_spacing_x_m")
            or heightmap.get("equator_resolution_m_per_px")
            or 1.0
        ),
    )
    spacing_y = max(
        1.0,
        float(heightmap.get("sample_spacing_y_m") or spacing_x),
    )
    source_h = max(1, len(elevation_rows))
    source_w = max(
        1,
        min(
            (len(row) for row in elevation_rows if isinstance(row, list)),
            default=1,
        ),
    )
    dzdy, dzdx = np.gradient(
        elevation,
        spacing_y * max(1.0, source_h / target_h),
        spacing_x * max(1.0, source_w / target_w),
    )
    slope = np.clip(
        np.sqrt(dzdx * dzdx + dzdy * dzdy) * 38.0,
        0.0,
        1.0,
    )

    process_keys = {
        "erosion": "erosion_potential_rows",
        "deposition": "sediment_deposition_rows",
        "aeolian": "aeolian_transport_rows",
        "weathering": "chemical_weathering_rows",
        "glacial": "glacial_erosion_rows",
        "age": "relative_surface_age_rows",
    }
    fields = {}
    means = exposure_model.get("process_means") or {}
    mean_alias = {
        "erosion": "erosion_potential",
        "deposition": "sediment_deposition",
        "aeolian": "aeolian_transport",
        "weathering": "chemical_weathering",
        "glacial": "glacial_erosion",
        "age": None,
    }
    for field, key in process_keys.items():
        rows = _rows(surface_evolution, "process_grid", key)
        if rows:
            fields[field] = np.clip(_resample(rows, target_h, target_w), 0.0, 1.0)
        else:
            default = (
                0.55
                if field == "age"
                else float(means.get(mean_alias[field], 0.0) or 0.0)
            )
            fields[field] = np.full(
                (target_h, target_w),
                _clamp(default),
                dtype=np.float32,
            )

    precipitation_rows = _rows(
        water_cycle,
        "climate_grid",
        "annual_precipitation_rows_mm",
    )
    if precipitation_rows:
        precipitation = np.maximum(
            0.0,
            _resample(precipitation_rows, target_h, target_w),
        )
        wetness = np.clip(np.log1p(precipitation) / np.log(3001.0), 0.0, 1.0)
    else:
        wetness = np.zeros((target_h, target_w), dtype=np.float32)
    aridity = np.clip(1.0 - wetness * 1.45, 0.0, 1.0)

    partition = derive_surface_material_partition_fields(
        heightmap,
        water_cycle=water_cycle,
        surface_evolution=surface_evolution,
        target_size=(target_w, target_h),
    )
    if partition:
        bedrock_exposure = partition["exposed_bedrock_fraction"]
        mobile_cover = partition["transported_cover_fraction"]
        regolith = partition["residual_regolith_fraction"]
    else:
        bedrock_exposure = np.clip(0.24 + slope * 0.52 + fields["erosion"] * 0.36 - fields["deposition"] * 0.46, 0.04, 0.98)
        mobile_cover = np.clip((1.0 - slope) * 0.10 + fields["deposition"] * 0.48 + fields["aeolian"] * aridity * 0.42, 0.0, 0.92)
        regolith = np.clip((1.0 - bedrock_exposure) * (0.36 + fields["age"] * 0.22 + fields["weathering"] * 0.42), 0.0, 0.94)
    cover_total = np.clip(
        mobile_cover + regolith * (1.0 - mobile_cover),
        0.0,
        0.97,
    )
    return {
        **fields,
        "slope": slope,
        "wetness": wetness,
        "aridity": aridity,
        "bedrock_exposure": bedrock_exposure,
        "regolith_fraction": regolith,
        "mobile_cover_fraction": mobile_cover,
        "cover_fraction": cover_total,
        "colluvial_cover_fraction": partition.get(
            "colluvial_cover_fraction", np.zeros_like(slope)
        ),
        "alluvial_cover_fraction": partition.get(
            "alluvial_cover_fraction", np.zeros_like(slope)
        ),
        "weathered_mantle_fraction": partition.get(
            "weathered_mantle_fraction", np.zeros_like(slope)
        ),
        "oxidation": np.clip(
            fields["weathering"] * (0.34 + aridity * 0.66),
            0.0,
            1.0,
        ),
        "hydration": np.clip(
            fields["weathering"] * wetness,
            0.0,
            1.0,
        ),
        "space_weathering": np.clip(
            fields["age"] * (1.0 - wetness * 0.85),
            0.0,
            1.0,
        ),
    }
