"""Deterministic, physically informed true-colour surface rendering.

The scientific height, climate, and material layers remain the simulation
truth.  This module combines those fields into a compact visual product; it
does not invent terrain or write another large global raster to the ontology.

Architecture invariants: entity semantics come only from the ontology and
runtime mappings are disposable caches. Planetary True Color is strictly
abiotic; vegetation is produced later by Biosphere simulation. Generated
planets are currently disposable, so model changes invalidate older products.

LOD contract: True Color is a consumer of the current LOD's heightmap,
material exposure, geomorphology, water, and atmosphere fields. It must render
the same causal chain at every scale and report missing parent-derived assets;
it must not silently substitute an independent geology or vegetation layer.
"""

from __future__ import annotations

import hashlib
import math

import pygame

from simulations.world_gen.material_optics import (
    linear_reflectance_to_srgb,
    material_optical_surface_profile,
    reflectance_triplet,
)
from simulations.world_gen.surface_exposure import derive_surface_exposure_fields
from simulations.world_gen.surface_geomorphology import (
    derive_surface_geomorphology_fields,
)

try:
    import numpy as np
except ImportError:  # pragma: no cover - exercised only by minimal installs.
    np = None


TRUE_COLOR_MODEL_VERSION = "planet-true-color-v13-bound-material-heightfield-no-global-vegetation"


# These are not ten decorative noise channels.  Each entry names an
# observable control on disk-integrated or orbital visible colour and maps to
# a field that already belongs to the generated world.  Keeping the contract
# explicit makes it possible to add better solvers without changing the
# meaning of the True Color layer.
ORBITAL_APPEARANCE_INFLUENCES = (
    "material_spectral_reflectance",
    "terrain_illumination_and_shadow",
    "regolith_grain_size_and_roughness",
    "erosion_and_bedrock_exposure",
    "chemical_weathering_oxidation_and_hydration",
    "aeolian_dust_deposition_and_stripping",
    "fluvial_lacustrine_and_coastal_sediment",
    "volcanic_resurfacing_and_fresh_lava",
    "impact_ejecta_and_surface_maturity",
    "water_ice_frost_and_atmospheric_scattering",
)


def true_color_model_sources_match(model, heightmap, material_heatmap_model):
    """Return whether a persisted recipe belongs to the current surface data."""
    if not isinstance(model, dict) or model.get("model_version") != TRUE_COLOR_MODEL_VERSION:
        return False
    bindings = model.get("source_bindings")
    if not isinstance(bindings, dict):
        return False
    heightmap = heightmap if isinstance(heightmap, dict) else {}
    heatmap = material_heatmap_model if isinstance(material_heatmap_model, dict) else {}
    return (
        bindings.get("heightmap_source_heightfield_fingerprint")
        == heightmap.get("source_heightfield_fingerprint")
        and bindings.get("material_heatmap_source_heightfield_fingerprint")
        == heatmap.get("source_heightfield_fingerprint")
        and bindings.get("material_heatmap_model_version")
        == heatmap.get("model_version")
        and bindings.get("material_layer_bindings")
        == [
            {
                "material_id": layer.get("material_id"),
                "bundle_layer_id": layer.get("bundle_layer_id") or layer.get("id"),
                "display_color": _rgb(layer.get("display_color")),
                "optical_profile_material_id": (
                    (layer.get("optical_surface_profile") or {}).get("material_id")
                    if isinstance(layer.get("optical_surface_profile"), dict)
                    else None
                ),
                "optical_profile_version": (
                    (layer.get("optical_surface_profile") or {}).get("profile_version")
                    if isinstance(layer.get("optical_surface_profile"), dict)
                    else None
                ),
                "optical_color_source": (
                    "optical_surface_profile.visible_reflectance"
                    if isinstance(layer.get("optical_surface_profile"), dict)
                    and (layer.get("optical_surface_profile") or {}).get("visible_reflectance")
                    else "material_optical_surface_profile"
                ),
            }
            for layer in heatmap.get("layers") or []
            if isinstance(layer, dict)
        ]
    )


def _clamp(value, low=0.0, high=1.0):
    try:
        value = float(value)
    except (TypeError, ValueError):
        value = low
    return max(low, min(high, value))


def _rgb(value, fallback=(116, 108, 96)):
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        try:
            return [
                max(0, min(255, int(round(float(value[index])))))
                for index in range(3)
            ]
        except (TypeError, ValueError):
            pass
    return list(fallback)


def _surface_color(planet):
    palette = planet.get("surface_palette") if isinstance(planet, dict) else {}
    if isinstance(palette, dict) and palette.get("surface_color"):
        return _rgb(palette["surface_color"])
    return _rgb((planet or {}).get("display_color"))


def _base_optical_surface(natural_material_model, planet):
    material_model = (
        natural_material_model
        if isinstance(natural_material_model, dict)
        else {}
    )
    candidates = (
        material_model.get("planetary_surface_materials")
        or material_model.get("likely_materials")
        or []
    )
    weighted = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        role = str(item.get("distribution_role") or "")
        if role not in {"bedrock", "surface_cover", "local_lithology"}:
            continue
        profile = material_optical_surface_profile(
            item.get("material_id"),
            formation_category=item.get("formation_category"),
            material_subclass=item.get("material_subclass"),
            display_color=item.get("display_color"),
            explicit=item.get("optical_surface_profile"),
        )
        weight = max(
            0.01,
            float(
                item.get("prevalence_score")
                or item.get("relative_abundance")
                or item.get("confidence")
                or 0.1
            ),
        )
        weighted.append((profile, weight))
        if len(weighted) >= 6:
            break
    if weighted:
        total = sum(weight for _profile, weight in weighted)
        reflectance = [
            sum(reflectance_triplet(profile)[index] * weight for profile, weight in weighted)
            / max(0.001, total)
            for index in range(3)
        ]
        primary = weighted[0][0]
    else:
        fallback = _surface_color(planet)
        primary = material_optical_surface_profile(
            "fallback_surface",
            material_subclass="rock",
            display_color=fallback,
        )
        reflectance = reflectance_triplet(primary)
    return primary, reflectance


def derive_true_color_model(
    planet,
    *,
    heightmap=None,
    natural_material_model=None,
    material_heatmap_model=None,
    atmosphere=None,
    water_cycle=None,
    surface_evolution=None,
    surface_exposure=None,
    surface_geomorphology=None,
):
    """Return the small, persistent recipe used to render a planet mosaic."""
    planet = planet if isinstance(planet, dict) else {}
    heightmap = heightmap if isinstance(heightmap, dict) else planet.get("heightmap_model") or {}
    natural_material_model = (
        natural_material_model
        if isinstance(natural_material_model, dict)
        else planet.get("natural_material_model") or {}
    )
    atmosphere = atmosphere if isinstance(atmosphere, dict) else planet.get("atmosphere_model") or {}
    water_cycle = water_cycle if isinstance(water_cycle, dict) else planet.get("water_cycle_model") or {}
    surface_evolution = (
        surface_evolution
        if isinstance(surface_evolution, dict)
        else planet.get("surface_evolution_model") or {}
    )
    surface_exposure = (
        surface_exposure
        if isinstance(surface_exposure, dict)
        else planet.get("surface_exposure_model") or {}
    )
    surface_geomorphology = (
        surface_geomorphology
        if isinstance(surface_geomorphology, dict)
        else planet.get("surface_geomorphology_model") or {}
    )
    material_heatmap_model = (
        material_heatmap_model
        if isinstance(material_heatmap_model, dict)
        else planet.get("material_heatmap_model") or {}
    )
    tags = {str(tag) for tag in natural_material_model.get("planet_tags") or []}
    pressure_bar = max(0.0, float(atmosphere.get("surface_pressure_bar", 0.0) or 0.0))
    ocean_fraction = _clamp(
        (heightmap.get("hypsometry_summary") or {}).get("ocean_fraction", 0.0)
    )
    ice_fraction = _clamp(
        (heightmap.get("hypsometry_summary") or {}).get("ice_fraction", 0.0)
    )
    process_means = (
        surface_evolution.get("process_means")
        if isinstance(surface_evolution.get("process_means"), dict)
        else {}
    )
    aeolian = _clamp(
        process_means.get(
            "aeolian_transport",
            0.72 if "aeolian_surface" in tags else 0.12,
        )
    )
    chemical_weathering = _clamp(
        process_means.get(
            "chemical_weathering",
            0.62 if "weathered_surface" in tags else 0.08,
        )
    )
    if pressure_bar < 0.0015:
        surface_regime = "airless_regolith"
    elif ocean_fraction >= 0.05 and water_cycle:
        # Active oceans and a solved water cycle are the dominant surface
        # context even where oxidized dust is also present.
        surface_regime = "hydrologic"
    elif (
        "oxidizing_surface" in tags
        or (
            pressure_bar >= 0.0015
            and "iron_rich_crust" in tags
            and "aeolian_surface" in tags
            and "reducing_surface" not in tags
        )
    ) and aeolian >= 0.2:
        surface_regime = "oxidized_dust"
    elif "volcanic_surface" in tags or "basaltic_surface" in tags:
        surface_regime = "volcanic"
    else:
        surface_regime = "rocky"

    seed = str(
        heightmap.get("map_seed")
        or heightmap.get("material_distribution_seed")
        or (planet.get("world_gen_seed") or {}).get("resolved_map_seed")
        or (planet.get("world_gen_seed") or {}).get("map_seed")
        or planet.get("id")
        or "planet"
    )
    base_optical_profile, base_linear_reflectance = _base_optical_surface(
        natural_material_model,
        planet,
    )
    base_color = linear_reflectance_to_srgb(base_linear_reflectance)
    stored_palette = planet.get("surface_palette") if isinstance(planet.get("surface_palette"), dict) else {}
    palette = [
        _rgb(color)
        for color in (stored_palette.get("palette") or [])[:3]
    ]
    material_layers = [
        layer for layer in material_heatmap_model.get("layers") or []
        if isinstance(layer, dict)
    ]
    material_layer_bindings = []
    for layer in material_layers:
        profile = layer.get("optical_surface_profile")
        material_layer_bindings.append({
            "material_id": layer.get("material_id"),
            "bundle_layer_id": layer.get("bundle_layer_id") or layer.get("id"),
            "display_color": _rgb(layer.get("display_color")),
            "optical_profile_material_id": (
                profile.get("material_id") if isinstance(profile, dict) else None
            ),
            "optical_profile_version": (
                profile.get("profile_version") if isinstance(profile, dict) else None
            ),
            "optical_color_source": (
                "optical_surface_profile.visible_reflectance"
                if isinstance(profile, dict) and profile.get("visible_reflectance")
                else "material_optical_surface_profile"
            ),
        })
    return {
        "status": "derived",
        "model_version": TRUE_COLOR_MODEL_VERSION,
        "projection": str(heightmap.get("projection") or "equirectangular"),
        "product": "surface_and_atmosphere_true_color",
        "truth_state": "derived_visualization",
        "surface_regime": surface_regime,
        "seed": seed,
        "base_reflectance_rgb": base_color,
        "base_linear_reflectance": [
            round(float(value), 6) for value in base_linear_reflectance
        ],
        "base_optical_surface_profile": base_optical_profile,
        "palette": palette,
        "ocean_fraction": round(ocean_fraction, 6),
        "ice_fraction": round(ice_fraction, 6),
        "surface_pressure_bar": round(pressure_bar, 6),
        "aeolian_strength": round(aeolian, 6),
        "chemical_weathering_strength": round(chemical_weathering, 6),
        "material_tags": sorted(tags),
        "rendering": {
            "terrain_normal_shading": True,
            "multiscale_albedo": True,
            "material_reflectance": True,
            "fractional_endmember_mixing": True,
            "process_driven_surface_exposure": True,
            "data_derived_landform_expression": True,
            "climate_weathering": bool(water_cycle),
            "atmospheric_scattering": pressure_bar >= 0.0015,
            "clouds": False,
            "vegetation": False,
            "vegetation_policy": "forbidden_at_planetary_detail",
            "rivers": bool((water_cycle or {}).get("rivers")),
            "orbital_appearance_influences": list(
                ORBITAL_APPEARANCE_INFLUENCES
            ),
            "unrelated_cosmetic_albedo_noise": False,
        },
        "source_versions": {
            "heightmap": heightmap.get("model_version"),
            "materials": natural_material_model.get("catalog_version"),
            "water_cycle": water_cycle.get("model_version"),
            "surface_evolution": surface_evolution.get("model_version"),
            "surface_exposure": surface_exposure.get("model_version"),
            "surface_geomorphology": surface_geomorphology.get("model_version"),
        },
        "source_bindings": {
            "contract": "same_heightmap_sample_grid_and_material_heatmap_layers",
            "heightmap_source_heightfield_fingerprint": heightmap.get(
                "source_heightfield_fingerprint"
            ),
            "material_heatmap_model_version": material_heatmap_model.get(
                "model_version"
            ),
            "material_heatmap_source_heightfield_fingerprint": material_heatmap_model.get(
                "source_heightfield_fingerprint"
            ),
            "material_color_source": (
                "material_heatmap.layers.optical_surface_profile"
                if material_layers
                else "natural_material_model.optical_surface_profile"
            ),
            "material_layer_bindings": material_layer_bindings,
            "missing_material_heatmap": not bool(material_heatmap_model),
        },
        "geomorphology": {
            "input_fingerprint": surface_geomorphology.get("input_fingerprint"),
            "structural_fabric": surface_geomorphology.get("structural_fabric") or {},
            "landform_classes": surface_geomorphology.get("landform_classes") or [],
        },
    }


def _stable_seed(value):
    digest = hashlib.sha256(str(value).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "little", signed=False)


def _resample_bilinear(values, target_h, target_w):
    values = np.asarray(values, dtype=np.float32)
    source_h, source_w = values.shape[:2]
    if source_h == target_h and source_w == target_w:
        return values.copy()
    ys = np.linspace(0.0, max(0, source_h - 1), target_h, dtype=np.float32)
    xs = np.linspace(0.0, max(0, source_w - 1), target_w, dtype=np.float32)
    y0 = np.floor(ys).astype(np.int32)
    x0 = np.floor(xs).astype(np.int32)
    y1 = np.minimum(source_h - 1, y0 + 1)
    x1 = np.minimum(source_w - 1, x0 + 1)
    fy = (ys - y0)[:, None]
    fx = (xs - x0)[None, :]
    if values.ndim == 2:
        top = values[y0[:, None], x0[None, :]] * (1.0 - fx) + values[y0[:, None], x1[None, :]] * fx
        bottom = values[y1[:, None], x0[None, :]] * (1.0 - fx) + values[y1[:, None], x1[None, :]] * fx
        return top * (1.0 - fy) + bottom * fy
    top = values[y0[:, None], x0[None, :], :] * (1.0 - fx[..., None]) + values[y0[:, None], x1[None, :], :] * fx[..., None]
    bottom = values[y1[:, None], x0[None, :], :] * (1.0 - fx[..., None]) + values[y1[:, None], x1[None, :], :] * fx[..., None]
    return top * (1.0 - fy[..., None]) + bottom * fy[..., None]


def _neighbourhood_mean(values, passes=1, *, wrap_x=False):
    """Small deterministic low-pass used to derive terrain form.

    Unlike a separately seeded texture, every value returned by this helper
    is a function of the inherited elevation/process grids.  This is important
    at regional scales where invented albedo clouds otherwise look like a
    second, unrelated landscape.
    """
    result = np.asarray(values, dtype=np.float32)
    for _index in range(max(1, int(passes or 1))):
        if wrap_x:
            left = np.roll(result, 1, axis=1)
            right = np.roll(result, -1, axis=1)
        else:
            left = np.concatenate((result[:, :1], result[:, :-1]), axis=1)
            right = np.concatenate((result[:, 1:], result[:, -1:]), axis=1)
        up = np.concatenate((result[:1, :], result[:-1, :]), axis=0)
        down = np.concatenate((result[1:, :], result[-1:, :]), axis=0)
        result = (result * 4.0 + left + right + up + down) / 8.0
    return result


def _normalise_signed(values, percentile=96.0):
    scale = float(np.percentile(np.abs(values), percentile))
    return np.clip(values / max(1e-6, scale), -1.0, 1.0)


def _normalise_positive(values, percentile=96.0):
    scale = float(np.percentile(np.maximum(0.0, values), percentile))
    return np.clip(np.maximum(0.0, values) / max(1e-6, scale), 0.0, 1.0)


def _process_rows(model, key):
    grid = model.get("process_grid") if isinstance(model, dict) else {}
    rows = grid.get(key) if isinstance(grid, dict) else None
    return rows if isinstance(rows, list) and rows and isinstance(rows[0], list) else None


def _grid_rows(model, keys):
    grid = model.get("climate_grid") if isinstance(model, dict) else {}
    if not isinstance(grid, dict):
        return None
    for key in keys:
        rows = grid.get(key)
        if isinstance(rows, list) and rows and isinstance(rows[0], list):
            return rows
    return None


def river_true_color_rgb(river):
    """Resolve visible river water from hydrology, never from vegetation.

    Clear, persistent high-discharge channels tend toward blue. Closed-basin
    and mineral-rich low-flow water tends toward teal/green, while steep or
    strongly seasonal runoff carries enough suspended sediment to read brown.
    These are orbital-scale water-color classes, not biome colors.
    """
    river = river if isinstance(river, dict) else {}
    flow = _clamp(river.get("flow", 0.0))
    runoff = max(0.0, float(river.get("catchment_mean_runoff_mm", 0.0) or 0.0))
    source_relief = max(0.0, float(river.get("source_elevation_m", 0.0) or 0.0))
    dryness = _clamp(river.get("catchment_dryness_ratio", 1.0) / 3.0)
    discharge = max(0.0, float(river.get("estimated_discharge_m3_s", 0.0) or 0.0))
    seasonal = str(river.get("flow_regime") or "") != "perennial"
    closed_basin = str(river.get("mouth") or "") != "ocean"
    sediment = _clamp(
        source_relief / 6500.0 * 0.34
        + min(1.0, runoff / 900.0) * 0.22
        + dryness * 0.20
        + (0.18 if seasonal else 0.0)
        - min(0.18, math.log1p(discharge) / 55.0)
    )
    mineral = _clamp(
        (0.42 if closed_basin else 0.08)
        + (1.0 - flow) * 0.20
        + dryness * 0.10
        - sediment * 0.24
    )
    clear = np.asarray([31.0, 96.0, 132.0], dtype=np.float32) if np is not None else (31.0, 96.0, 132.0)
    mineral_rgb = np.asarray([53.0, 112.0, 94.0], dtype=np.float32) if np is not None else (53.0, 112.0, 94.0)
    sediment_rgb = np.asarray([131.0, 101.0, 61.0], dtype=np.float32) if np is not None else (131.0, 101.0, 61.0)
    if np is None:
        color = [
            clear[index] * (1.0 - mineral) + mineral_rgb[index] * mineral
            for index in range(3)
        ]
        color = [
            color[index] * (1.0 - sediment) + sediment_rgb[index] * sediment
            for index in range(3)
        ]
    else:
        color = clear * (1.0 - mineral) + mineral_rgb * mineral
        color = color * (1.0 - sediment) + sediment_rgb * sediment
    return tuple(int(round(float(channel))) for channel in color)


def _true_color_river_overlay(water_cycle, size):
    water_cycle = water_cycle if isinstance(water_cycle, dict) else {}
    rivers = [river for river in water_cycle.get("rivers") or [] if isinstance(river, dict)]
    if not rivers:
        return None
    width, height = size
    overlay = pygame.Surface(size, pygame.SRCALPHA)
    for river in rivers:
        points = []
        for point in river.get("display_points") or river.get("points") or []:
            if not isinstance(point, dict):
                continue
            points.append((
                int(round(_clamp(point.get("x", 0.0)) * (width - 1))),
                int(round(_clamp(point.get("y", 0.0)) * (height - 1))),
            ))
        if len(points) < 2:
            continue
        discharge = max(0.0, float(river.get("estimated_discharge_m3_s", 0.0) or 0.0))
        line_width = 1 + int(discharge >= 450.0) + int(discharge >= 6000.0)
        color = (*river_true_color_rgb(river), 224)
        if line_width > 1:
            pygame.draw.lines(overlay, color, False, points, line_width)
        pygame.draw.aalines(overlay, color, False, points)
    return overlay


def _surface_to_rgb_array(surface, size):
    if surface is None:
        return None
    if surface.get_size() != size:
        surface = pygame.transform.smoothscale(surface, size)
    return np.transpose(pygame.surfarray.array3d(surface), (1, 0, 2)).astype(np.float32)


def _surface_to_alpha_array(surface, size):
    if surface is None:
        return None
    if surface.get_size() != size:
        surface = pygame.transform.smoothscale(surface, size)
    try:
        alpha = pygame.surfarray.array_alpha(surface)
    except (ValueError, pygame.error):
        alpha = np.full(size, 255, dtype=np.uint8)
    return np.transpose(alpha, (1, 0)).astype(np.float32) / 255.0


def _srgb_array_to_linear(values):
    values = np.clip(values / 255.0, 0.0, 1.0)
    return np.where(
        values <= 0.04045,
        values / 12.92,
        np.power((values + 0.055) / 1.055, 2.4),
    )


def _linear_array_to_srgb(values):
    values = np.clip(values, 0.0, 1.0)
    encoded = np.where(
        values <= 0.0031308,
        values * 12.92,
        1.055 * np.power(values, 1.0 / 2.4) - 0.055,
    )
    return encoded * 255.0


def _component_visual_role(component):
    role = str(component.get("visual_role") or "")
    if role:
        return role
    distribution = str(component.get("distribution_role") or "")
    representation = str(component.get("spatial_representation") or "")
    if distribution in {"bedrock", "local_lithology"} or representation == "bedrock_unit":
        return "substrate"
    if distribution == "surface_cover" or representation == "surface_cover":
        return "mobile_or_regolith_cover"
    if distribution == "mineral_constituent" or representation == "constituent_abundance":
        return "intimate_substrate_component"
    return "bounded_exposure"


def _driver_field(component, exposure):
    if component.get("surface_expression_precomputed"):
        return exposure.get("one", 1.0)
    driver = str(component.get("process_driver") or "geological_exposure")
    one = exposure.get("one")
    if one is None:
        return 1.0
    if driver == "aeolian_transport":
        return exposure.get("aeolian", one) * exposure.get("aridity", one)
    if driver == "sediment_deposition":
        return exposure.get("deposition", one)
    if driver == "colluvial_deposition":
        return exposure.get("colluvial_cover_fraction", one)
    if driver == "arid_basin":
        return exposure.get("deposition", one) * exposure.get("aridity", one)
    if driver == "chemical_weathering":
        return exposure.get("weathering", one) * exposure.get("wetness", one)
    if driver == "oxidative_weathering":
        return exposure.get("oxidation", one)
    if driver == "glacial_erosion":
        return exposure.get("glacial", one)
    if driver == "impact_gardening":
        return exposure.get("space_weathering", one)
    if driver == "ice_stability":
        return one
    if driver == "volcanic_resurfacing":
        return exposure.get("bedrock_exposure", one)
    return exposure.get("bedrock_exposure", one)


def _optical_mixture_fraction(abundance, profile, maximum=1.0):
    """Convert mapped abundance into visible fractional influence.

    Surface abundance and optical dominance are not interchangeable.  A thin
    ferric or clay coating can control colour while a similar abundance of a
    clear framework crystal barely changes a rock.  The material card owns
    that distinction through mixing mode, opacity depth and colouring power.
    """
    abundance = np.clip(abundance, 0.0, 1.0)
    maximum = _clamp(maximum)
    mode = str(profile.get("mixing_mode") or "intimate")
    coloring_power = _clamp(
        profile.get("optical_coloring_power", 1.0),
        0.1,
        6.0,
    )
    try:
        opacity_depth = max(
            0.05,
            float(profile.get("optical_opacity_depth_mm", 12.0) or 12.0),
        )
    except (TypeError, ValueError):
        opacity_depth = 12.0

    if mode == "coating":
        opacity_gain = np.clip(np.sqrt(8.0 / opacity_depth), 0.35, 3.2)
        influence = 1.0 - np.exp(
            -abundance * coloring_power * opacity_gain * 0.75
        )
    elif mode == "translucent":
        influence = abundance * np.clip(
            0.30 + coloring_power * 0.24,
            0.24,
            0.72,
        )
    elif mode == "areal":
        # Areal mixtures expose distinct patches: their projected area is
        # already their first-order visible fraction.
        influence = abundance * np.clip(
            0.82 + math.sqrt(coloring_power) * 0.18,
            0.72,
            1.28,
        )
    else:
        influence = abundance * np.clip(
            0.50 + coloring_power * 0.50,
            0.35,
            2.20,
        )
    return np.clip(influence, 0.0, maximum)


_COLOR_DRIVER_EXPOSURE_FIELDS = {
    "weathering": "weathering",
    "oxidation": "oxidation",
    "wetness": "wetness",
    "space_weathering": "space_weathering",
}


def _color_driver_fraction(profile, exposure, bedrock_modulation):
    """Per-material fresh/weathered blend fraction along its own driver.

    Materials vary along a range (oxidation, wetness, weathering maturity)
    rather than sitting at a single fixed colour.  Each material names which
    exposure field drives that range; this keeps the blend local to the
    material instead of assuming every material on the mix shares the same
    driver.
    """
    field = _COLOR_DRIVER_EXPOSURE_FIELDS.get(
        str(profile.get("color_driver") or "weathering"),
        "weathering",
    )
    one = exposure.get("one")
    driver_value = exposure.get(field, one if one is not None else 1.0)
    response = _clamp(profile.get("weathering_color_response", 0.18))
    return np.clip(driver_value * response * bedrock_modulation, 0.0, 0.62)


def _mix_material_endmembers(
    material_components,
    fallback_reflectance,
    exposure,
    size,
    *,
    detail_level=0,
    wrap_x=False,
):
    """Mix optical endmembers within substrate, constituent and cover strata."""
    width, height = size
    shape = (height, width)
    base = np.asarray(fallback_reflectance, dtype=np.float32)
    bedrock_exposure_for_weathering = exposure.get(
        "bedrock_exposure",
        np.full(shape, 0.35, dtype=np.float32),
    )
    bedrock_modulation = 0.28 + bedrock_exposure_for_weathering * 0.72
    substrate_sum = np.zeros((*shape, 3), dtype=np.float32)
    substrate_weight = np.zeros(shape, dtype=np.float32)
    constituent_sum = np.zeros((*shape, 3), dtype=np.float32)
    constituent_weight = np.zeros(shape, dtype=np.float32)
    bounded_sum = np.zeros((*shape, 3), dtype=np.float32)
    bounded_weight = np.zeros(shape, dtype=np.float32)
    cover_sum = np.zeros((*shape, 3), dtype=np.float32)
    cover_weight = np.zeros(shape, dtype=np.float32)
    cover_presence = np.zeros(shape, dtype=np.float32)
    property_sum = {
        key: np.zeros(shape, dtype=np.float32)
        for key in (
            "wet_darkening_factor",
            "oxidation_response",
            "hydration_response",
            "space_weathering_response",
            "grain_size_sensitivity",
            "fracture_darkening_factor",
            "surface_fabric_strength",
            "bedded_fraction",
            "foliated_fraction",
            "volcanic_flow_fraction",
        )
    }
    property_weight = np.zeros(shape, dtype=np.float32)

    for component in material_components or []:
        if not isinstance(component, dict):
            continue
        suitability = _surface_to_alpha_array(component.get("surface"), size)
        if suitability is None:
            continue
        profile = material_optical_surface_profile(
            component.get("material_id"),
            formation_category=component.get("formation_category"),
            material_subclass=component.get("material_subclass"),
            display_color=component.get("display_color"),
            explicit=component.get("optical_surface_profile"),
        )
        reflectance = np.asarray(
            reflectance_triplet(profile),
            dtype=np.float32,
        )
        weathered_profile = profile.get("weathered_visible_reflectance")
        if not isinstance(weathered_profile, dict):
            weathered_profile = profile.get("visible_reflectance") or {}
        weathered_reflectance = np.asarray(
            [
                _clamp(weathered_profile.get("red_650nm", reflectance[0])),
                _clamp(weathered_profile.get("green_550nm", reflectance[1])),
                _clamp(weathered_profile.get("blue_450nm", reflectance[2])),
            ],
            dtype=np.float32,
        )
        maximum = _clamp(component.get("maximum_visible_fraction", 1.0))
        driver = _driver_field(component, exposure)
        role = _component_visual_role(component)
        abundance = np.clip(suitability * driver, 0.0, 1.0)
        if role == "substrate" and detail_level <= 0:
            # At planetary scale a pixel represents a broad lithologic
            # footprint.  Competing substrate suitability therefore needs a
            # small spatial support before the categorical competition; using
            # raw pixels turns the upstream province grid into optical panels.
            abundance = _neighbourhood_mean(
                abundance,
                2,
                wrap_x=wrap_x,
            )
        # Blend this component's own fresh/weathered endpoints along its own
        # colour driver before it enters the role-based mix, so a material
        # driven by local oxidation doesn't get averaged against one driven
        # by generic age-weathering.
        color_fraction = _color_driver_fraction(profile, exposure, bedrock_modulation)
        blended_reflectance = (
            reflectance[None, None, :] * (1.0 - color_fraction[..., None])
            + weathered_reflectance[None, None, :] * color_fraction[..., None]
        )
        if role == "substrate":
            # Lithologic provinces are categorical geological bodies, not an
            # intimate paint mixture.  A high competitive exponent leaves a
            # narrow two-unit contact while preventing eight weakly suitable
            # rocks from averaging into the same grey-brown substrate.
            competitive_exponent = (
                2.4 if detail_level <= 0 else 4.2 if detail_level == 1 else 6.0
            )
            weight = np.power(abundance, competitive_exponent)
            substrate_sum += weight[..., None] * blended_reflectance
            substrate_weight += weight
        elif role == "intimate_substrate_component":
            weight = _optical_mixture_fraction(
                abundance,
                profile,
                maximum,
            )
            constituent_sum += weight[..., None] * blended_reflectance
            constituent_weight += weight
        elif role == "mobile_or_regolith_cover":
            physical_fraction = _optical_mixture_fraction(abundance, profile, maximum)
            weight = np.power(physical_fraction, 4.0)
            cover_sum += weight[..., None] * blended_reflectance
            cover_weight += weight
            cover_presence = np.maximum(cover_presence, physical_fraction)
        else:
            weight = _optical_mixture_fraction(
                abundance,
                profile,
                maximum,
            )
            bounded_sum += weight[..., None] * blended_reflectance
            bounded_weight += weight
        property_weight += weight
        for key in property_sum:
            if key.endswith("_fraction"):
                fabric = str(profile.get("surface_fabric") or "massive")
                expected = {
                    "bedded_fraction": "bedded",
                    "foliated_fraction": "foliated",
                    "volcanic_flow_fraction": "volcanic_flow",
                }[key]
                property_sum[key] += weight * (1.0 if fabric == expected else 0.0)
            else:
                property_sum[key] += weight * _clamp(profile.get(key, 0.0))

    substrate = np.broadcast_to(base, (*shape, 3)).copy()
    # Even a deeply mantled cell retains a substrate identity; the cover
    # stratum, not a numerical cutoff, decides how much of it is visible.
    has_substrate = substrate_weight > 1e-12
    substrate_average = substrate_sum / np.maximum(
        substrate_weight[..., None],
        1e-12,
    )
    substrate = np.where(has_substrate[..., None], substrate_average, substrate)

    constituent_fraction = np.clip(constituent_weight, 0.0, 0.30)
    constituent_average = constituent_sum / np.maximum(
        constituent_weight[..., None],
        0.001,
    )
    substrate = (
        substrate * (1.0 - constituent_fraction[..., None])
        + constituent_average * constituent_fraction[..., None]
    )

    bounded_fraction = np.clip(bounded_weight, 0.0, 0.48)
    bounded_average = bounded_sum / np.maximum(
        bounded_weight[..., None],
        0.001,
    )
    substrate = (
        substrate * (1.0 - bounded_fraction[..., None])
        + bounded_average * bounded_fraction[..., None]
    )

    total_cover = exposure.get("cover_fraction")
    if total_cover is None:
        total_cover = np.full(shape, 0.35, dtype=np.float32)
    cover_fraction = np.clip(cover_presence, 0.0, 1.0) * total_cover
    cover_average = cover_sum / np.maximum(cover_weight[..., None], 1e-12)
    mixed = (
        substrate * (1.0 - cover_fraction[..., None])
        + cover_average * cover_fraction[..., None]
    )
    properties = {
        key: values / np.maximum(property_weight, 0.001)
        for key, values in property_sum.items()
    }
    return np.clip(mixed, 0.002, 0.98), properties


def _fallback_surface(heightmap, model):
    rows = ((heightmap.get("sample_grid") or {}).get("rows") or [])
    height = max(1, len(rows) - 1)
    width = max(1, min((len(row) for row in rows if isinstance(row, list)), default=2) - 1)
    surface = pygame.Surface((width, height))
    base = _rgb(model.get("base_reflectance_rgb"))
    minimum = float(heightmap.get("min_elevation_m", -4000.0) or -4000.0)
    maximum = float(heightmap.get("max_elevation_m", 4000.0) or 4000.0)
    sea = heightmap.get("sea_level_m")
    for y in range(height):
        for x in range(width):
            elevation = float(rows[y][x] or 0.0)
            if sea is not None and elevation < float(sea):
                depth = _clamp((float(sea) - elevation) / max(1.0, float(sea) - minimum))
                color = [int(34 - 22 * depth), int(76 - 46 * depth), int(104 - 54 * depth)]
            else:
                relief = _clamp((elevation - (float(sea) if sea is not None else minimum)) / max(1.0, maximum - (float(sea) if sea is not None else minimum)))
                color = [int(channel * (0.72 + relief * 0.34)) for channel in base]
            surface.set_at((x, y), color)
    return surface


def render_true_color_surface(
    heightmap,
    model,
    *,
    material_surface=None,
    material_components=None,
    water_cycle=None,
    surface_evolution=None,
    surface_exposure=None,
    surface_geomorphology=None,
    atmosphere=None,
    target_size=None,
):
    """Render an equirectangular true-colour mosaic as a pygame surface."""
    heightmap = heightmap if isinstance(heightmap, dict) else {}
    model = model if isinstance(model, dict) else {}
    rows = ((heightmap.get("sample_grid") or {}).get("rows") or [])
    valid_rows = [row for row in rows if isinstance(row, list)]
    source_w = min((len(row) for row in valid_rows), default=0)
    source_h = len(valid_rows)
    if source_w < 2 or source_h < 2:
        return None
    bound_heightfield = (model.get("source_bindings") or {}).get(
        "heightmap_source_heightfield_fingerprint"
    )
    current_heightfield = heightmap.get("source_heightfield_fingerprint")
    if bound_heightfield is not None and bound_heightfield != current_heightfield:
        # A stale recipe must not make a plausible-looking image from a
        # different terrain product.  The map/worldgen callers rederive it
        # when this guard is reached.
        return None
    if np is None:
        return _fallback_surface(heightmap, model)

    cell_w, cell_h = source_w - 1, source_h - 1
    detail_level = max(0, int(heightmap.get("map_detail_level", 0) or 0))
    if target_size is None:
        target_w = min(1024, max(cell_w, 768 if detail_level <= 0 else cell_w * 2))
        target_h = max(1, int(round(target_w * cell_h / max(1, cell_w))))
    else:
        target_w, target_h = max(2, int(target_size[0])), max(1, int(target_size[1]))

    elevation_points = np.asarray([row[:source_w] for row in valid_rows], dtype=np.float32)
    elevation_cells = (
        elevation_points[:-1, :-1]
        + elevation_points[:-1, 1:]
        + elevation_points[1:, :-1]
        + elevation_points[1:, 1:]
    ) * 0.25
    elevation = _resample_bilinear(elevation_cells, target_h, target_w)
    minimum = float(heightmap.get("min_elevation_m", float(np.min(elevation))) or 0.0)
    maximum = float(heightmap.get("max_elevation_m", float(np.max(elevation))) or 0.0)
    sea_value = heightmap.get("sea_level_m")
    has_ocean = sea_value is not None
    sea = float(sea_value or 0.0)
    land_floor = sea if has_ocean else minimum
    relief = np.clip((elevation - land_floor) / max(1.0, maximum - land_floor), 0.0, 1.0)
    ocean = elevation < sea if has_ocean else np.zeros(elevation.shape, dtype=bool)
    depth = np.clip((sea - elevation) / max(1.0, sea - minimum), 0.0, 1.0)

    masks = heightmap.get("surface_masks") if isinstance(heightmap.get("surface_masks"), dict) else {}
    ice_rows = masks.get("ice_rows") if isinstance(masks.get("ice_rows"), list) else []
    if ice_rows and len(ice_rows) >= 2:
        ice_source = np.asarray(
            [
                [1.0 if value else 0.0 for value in row[:source_w]]
                for row in ice_rows[:source_h]
            ],
            dtype=np.float32,
        )
        if ice_source.shape[0] >= 2 and ice_source.shape[1] >= 2:
            ice_cells = ice_source[:-1, :-1]
            ice = _resample_bilinear(ice_cells, target_h, target_w) >= 0.45
        else:
            ice = np.zeros(elevation.shape, dtype=bool)
    else:
        ice = np.zeros(elevation.shape, dtype=bool)

    fallback_reflectance = model.get("base_linear_reflectance")
    if not isinstance(fallback_reflectance, (list, tuple)):
        fallback_rgb = np.asarray(
            _rgb(model.get("base_reflectance_rgb")),
            dtype=np.float32,
        )
        fallback_reflectance = _srgb_array_to_linear(fallback_rgb)
    fallback_reflectance = np.asarray(
        fallback_reflectance,
        dtype=np.float32,
    )
    exposure = derive_surface_exposure_fields(
        heightmap,
        surface_exposure or {},
        water_cycle=water_cycle,
        surface_evolution=surface_evolution,
        surface_geomorphology=surface_geomorphology,
        target_size=(target_w, target_h),
    )
    geomorphology = derive_surface_geomorphology_fields(
        heightmap,
        water_cycle=water_cycle,
        surface_evolution=surface_evolution,
        target_size=(target_w, target_h),
    )
    # The geomorphology model is the higher-order interpretation of the same
    # terrain/process truth.  Its bedrock estimate replaces the older generic
    # slope proxy when available.
    if geomorphology:
        bedrock_exposure = geomorphology["bedrock_exposure"]
        if detail_level <= 0:
            bedrock_exposure = _neighbourhood_mean(
                bedrock_exposure,
                2,
                wrap_x=bool(heightmap.get("wrap_x", False)),
            )
        exposure["bedrock_exposure"] = bedrock_exposure
    exposure["one"] = np.ones((target_h, target_w), dtype=np.float32)
    linear_surface, optical_properties = _mix_material_endmembers(
        material_components,
        fallback_reflectance,
        exposure,
        (target_w, target_h),
        detail_level=detail_level,
        wrap_x=bool(heightmap.get("wrap_x", False)),
    )

    # Legacy composites are accepted only as a compatibility fallback. New
    # worlds use the alpha of each individual suitability layer together with
    # its physical optical profile; cartographic display colours are not a
    # source of true-colour truth.
    material_rgb = _surface_to_rgb_array(material_surface, (target_w, target_h))
    if material_rgb is not None and not material_components:
        legacy_linear = _srgb_array_to_linear(material_rgb)
        linear_surface = linear_surface * 0.76 + legacy_linear * 0.24

    wetness = exposure.get(
        "wetness",
        np.zeros((target_h, target_w), dtype=np.float32),
    )
    oxidation = exposure.get(
        "oxidation",
        np.zeros((target_h, target_w), dtype=np.float32),
    )
    space_weathering = exposure.get(
        "space_weathering",
        np.zeros((target_h, target_w), dtype=np.float32),
    )
    wet_factor = optical_properties.get(
        "wet_darkening_factor",
        np.full((target_h, target_w), 0.22, dtype=np.float32),
    )
    oxidation_response = optical_properties.get(
        "oxidation_response",
        np.zeros((target_h, target_w), dtype=np.float32),
    )
    space_response = optical_properties.get(
        "space_weathering_response",
        np.full((target_h, target_w), 0.15, dtype=np.float32),
    )
    linear_surface *= (
        1.0 - wetness[..., None] * wet_factor[..., None] * 0.72
    )
    # The fresh/weathered blend now happens per-material, inside
    # _mix_material_endmembers, along each material's own colour driver
    # (see color_driver on the optical profile). What remains here is a
    # small residual global ferric tint for oxidation-driven redness that
    # isn't already carried by a material's own weathered endpoint; it is
    # kept deliberately weak so it doesn't double up with that per-material
    # range on materials such as laterite/ferric crusts.
    ferric = np.asarray([0.31, 0.075, 0.038], dtype=np.float32)
    ferric_fraction = np.clip(
        oxidation * oxidation_response * 0.16,
        0.0,
        0.20,
    )
    linear_surface = (
        linear_surface * (1.0 - ferric_fraction[..., None])
        + ferric * ferric_fraction[..., None]
    )
    if str(model.get("surface_regime") or "") == "airless_regolith":
        weather_fraction = np.clip(
            space_weathering * space_response * 0.38,
            0.0,
            0.42,
        )
        weathered = linear_surface * np.asarray(
            [0.78, 0.72, 0.67],
            dtype=np.float32,
        )
        linear_surface = (
            linear_surface * (1.0 - weather_fraction[..., None])
            + weathered * weather_fraction[..., None]
        )
    land_rgb = _linear_array_to_srgb(linear_surface)
    base = np.asarray(_rgb(model.get("base_reflectance_rgb")), dtype=np.float32)

    # Derive the visible texture from the same topography that the height
    # layer displays.  The former compositor placed three independent random
    # albedo fields over the surface; attractive at first glance, but they did
    # not follow mountains, basins, channels or inherited regional detail.
    wrap_x = bool(heightmap.get("wrap_x", False))
    source_cell_footprint = max(
        1.0,
        target_w / max(1, cell_w),
        target_h / max(1, cell_h),
    )
    # Filters must span the reconstructed source-cell footprint. Fixed
    # three-pixel filters detected bilinear cell interiors as geological
    # fabric and produced the fine rectangular scratches seen from orbit.
    meso_passes = max(3, int(round(source_cell_footprint * 1.45)))
    broad_passes = max(meso_passes + 4, int(round(source_cell_footprint * 3.4)))
    # Reconstruct relief form from the saved source lattice before enlarging
    # it. Differentiating/classifying the upsampled bilinear lattice creates
    # false cell-edge fabric that reads as contour scratches in true color.
    source_footprint = max(1.0, source_cell_footprint)
    source_meso_passes = max(1, int(round(meso_passes / source_footprint)))
    source_broad_passes = max(
        source_meso_passes + 2,
        int(round(broad_passes / source_footprint)),
    )
    source_broad_form = _neighbourhood_mean(
        elevation_points,
        source_broad_passes,
        wrap_x=wrap_x,
    )
    source_meso_form = _neighbourhood_mean(
        elevation_points,
        source_meso_passes,
        wrap_x=wrap_x,
    )
    broad_form = _resample_bilinear(
        source_meso_form - source_broad_form,
        target_h,
        target_w,
    )
    local_relief = _resample_bilinear(
        elevation_points - source_meso_form,
        target_h,
        target_w,
    )
    curvature = _resample_bilinear(
        elevation_points - _neighbourhood_mean(
            elevation_points,
            1,
            wrap_x=wrap_x,
        ),
        target_h,
        target_w,
    )
    broad_relief = _normalise_signed(broad_form)
    local_relief = _normalise_signed(local_relief)
    curvature = _normalise_signed(curvature)
    meso_render_form = _resample_bilinear(
        source_meso_form,
        target_h,
        target_w,
    )
    ruggedness = geomorphology.get(
        "ruggedness", _normalise_positive(np.abs(elevation - meso_render_form))
    )

    spacing_x = max(1.0, float(heightmap.get("sample_spacing_x_m") or heightmap.get("equator_resolution_m_per_px") or 1.0))
    spacing_y = max(1.0, float(heightmap.get("sample_spacing_y_m") or spacing_x))
    scale_x = spacing_x * max(1.0, cell_w / target_w)
    scale_y = spacing_y * max(1.0, cell_h / target_h)
    dzdy, dzdx = np.gradient(elevation, scale_y, scale_x)
    if geomorphology:
        dzdx = geomorphology["dzdx"]
        dzdy = geomorphology["dzdy"]
        slope = geomorphology["slope"]
    else:
        slope = np.clip(
            np.sqrt(dzdx * dzdx + dzdy * dzdy) * 32.0,
            0.0,
            1.0,
        )

    erosion = exposure.get("erosion", np.zeros(elevation.shape, dtype=np.float32))
    deposition = exposure.get("deposition", np.zeros(elevation.shape, dtype=np.float32))
    aeolian = exposure.get("aeolian", np.zeros(elevation.shape, dtype=np.float32))
    weathering_field = exposure.get("weathering", np.zeros(elevation.shape, dtype=np.float32))
    age = exposure.get("age", np.full(elevation.shape, 0.55, dtype=np.float32))
    aridity = exposure.get("aridity", np.ones(elevation.shape, dtype=np.float32))
    bedrock = exposure.get("bedrock_exposure", np.full(elevation.shape, 0.35, dtype=np.float32))
    mobile_cover = exposure.get("mobile_cover_fraction", np.zeros(elevation.shape, dtype=np.float32))
    ridge = geomorphology.get("ridge", np.zeros(elevation.shape, dtype=np.float32))
    valley = geomorphology.get("valley", np.zeros(elevation.shape, dtype=np.float32))
    scarp = geomorphology.get("scarp", np.zeros(elevation.shape, dtype=np.float32))
    incised_valley = geomorphology.get("incised_valley", np.zeros(elevation.shape, dtype=np.float32))
    talus = geomorphology.get("talus", np.zeros(elevation.shape, dtype=np.float32))
    alluvial = geomorphology.get("alluvial", np.zeros(elevation.shape, dtype=np.float32))
    mantled_plain = geomorphology.get("mantled_plain", np.zeros(elevation.shape, dtype=np.float32))
    convexity = geomorphology.get("convexity", np.zeros(elevation.shape, dtype=np.float32))
    concavity = geomorphology.get("concavity", np.zeros(elevation.shape, dtype=np.float32))

    # 3. Grain size and roughness: coarse exposed rock has stronger local
    # contrast; fine mobile mantles mute it.  Material endmembers supply their
    # own grain-size sensitivity where available.
    grain_response = optical_properties.get(
        "grain_size_sensitivity",
        np.full(elevation.shape, 0.35, dtype=np.float32),
    )
    grain_contrast = local_relief * (
        0.030 + grain_response * 0.055
    ) * (0.35 + bedrock * 0.65)
    grain_contrast *= 1.0 - mobile_cover * 0.72

    # Erosion/exposure now changes the generated material surface fractions.
    # This remaining term is only unresolved roughness contrast, not a generic
    # mountain or sediment colour painted by the renderer.
    exposure_contrast = (
        ruggedness * bedrock * (0.014 + erosion * 0.025)
    )

    # 6. Aeolian dust follows the wind-facing relief difference.  The shift is
    # zonal because the annual climate currently resolves circulation belts,
    # not instantaneous local gusts; the seed chooses eastward/westward flow,
    # but the visible streak itself is caused by terrain and aeolian activity.
    wind_sign = -1 if _stable_seed(model.get("seed", "planet")) & 1 else 1
    wind_shift = max(1, min(8, target_w // 160 + 1)) * wind_sign
    upstream_relief = np.roll(meso_render_form, wind_shift, axis=1)
    lee_index = np.clip(
        -_normalise_signed(meso_render_form - upstream_relief),
        0.0,
        1.0,
    )
    dust_cover = np.clip(
        aeolian * aridity * (0.24 + lee_index * 0.76) * (1.0 - slope * 0.62),
        0.0,
        1.0,
    )

    terrain_albedo = (
        broad_relief * 0.035
        + grain_contrast
        - exposure_contrast
        + deposition * (1.0 - slope) * 0.025
    )

    # Surface hues come exclusively from the material endmembers. Geomorphic
    # fields may still modulate relief visibility, but do not invent a talus or
    # alluvium colour when no such material is present in the generated model.
    terrain_albedo += ridge * bedrock * 0.012 - scarp * 0.018 - incised_valley * 0.012

    # Material fabric changes brightness and fracture contrast, never hue.
    # Thus limestone/shale bedding, gneissic foliation and volcanic flow
    # fabrics remain visible, while massive granite does not acquire invented
    # warm/cool stripes merely because the range is tectonic.
    geomodel = surface_geomorphology if isinstance(surface_geomorphology, dict) else {}
    fabric = geomodel.get("structural_fabric") if isinstance(geomodel.get("structural_fabric"), dict) else (model.get("geomorphology") or {}).get("structural_fabric") or {}
    material_fabric_strength = optical_properties.get(
        "surface_fabric_strength",
        np.zeros(elevation.shape, dtype=np.float32),
    )
    bedded_fraction = optical_properties.get(
        "bedded_fraction", np.zeros(elevation.shape, dtype=np.float32)
    )
    foliated_fraction = optical_properties.get(
        "foliated_fraction", np.zeros(elevation.shape, dtype=np.float32)
    )
    volcanic_flow_fraction = optical_properties.get(
        "volcanic_flow_fraction", np.zeros(elevation.shape, dtype=np.float32)
    )
    if (
        material_components
        and int(heightmap.get("map_detail_level", 0) or 0) > 0
        and fabric.get("bedrock_banding_enabled")
        and float(np.max(material_fabric_strength)) > 0.01
    ):
        strike = math.radians(float(fabric.get("dominant_strike_degrees", 0.0) or 0.0))
        yy, xx = np.mgrid[0:target_h, 0:target_w]
        physical_span = max(scale_x * target_w, scale_y * target_h)
        band_wavelength = max(8.0 * min(scale_x, scale_y), physical_span / 34.0)
        stratigraphic_phase = (
            elevation / max(1.0, band_wavelength * 0.18)
            + (xx * math.cos(strike) + yy * math.sin(strike)) * (min(scale_x, scale_y) / band_wavelength)
        )
        bands = np.sin(stratigraphic_phase * math.tau)
        directional_fabric = (
            bands * bedded_fraction
            + np.sin(stratigraphic_phase * math.tau * 1.65 + 0.8) * foliated_fraction * 0.72
            + np.sin(stratigraphic_phase * math.tau * 0.55 - 0.4) * volcanic_flow_fraction * 0.38
        )
        band_visibility = np.clip(
            (ridge * 0.20 + scarp * 0.48 + slope * 0.32)
            * bedrock * material_fabric_strength,
            0.0,
            0.68,
        )
        terrain_albedo += directional_fabric * band_visibility * 0.052

    fracture_response = optical_properties.get(
        "fracture_darkening_factor",
        np.full(elevation.shape, 0.18, dtype=np.float32),
    )
    fracture_exposure = np.clip(
        (scarp * 0.58 + ruggedness * 0.24 + incised_valley * 0.18)
        * bedrock * fracture_response,
        0.0,
        0.44,
    )
    terrain_albedo -= fracture_exposure * 0.085

    regime = str(model.get("surface_regime") or "rocky")
    tags = set(model.get("material_tags") or [])
    if regime == "airless_regolith":
        if not material_components:
            luma = np.sum(
                land_rgb
                * np.asarray([0.2126, 0.7152, 0.0722], dtype=np.float32),
                axis=2,
                keepdims=True,
            )
            chroma = float(max(base) - min(base))
            saturation = 0.18 if chroma < 42.0 else 0.62
            land_rgb = luma + (land_rgb - luma) * saturation
        terrain_albedo *= 1.34
    elif regime == "oxidized_dust" and not material_components:
        dust = np.asarray([176.0, 104.0, 72.0], dtype=np.float32)
        dust_strength = 0.30 + 0.34 * _clamp(model.get("aeolian_strength", 0.5))
        land_rgb = land_rgb * (1.0 - dust_strength) + dust * dust_strength
        dark_exposure = np.clip(
            (relief - 0.52) * 1.35
            + ruggedness * bedrock * 0.34
            + erosion * 0.16,
            0.0,
            0.42,
        )
        land_rgb *= (1.0 - dark_exposure[..., None])
    elif regime == "volcanic" and not material_components:
        basalt = np.asarray([55.0, 58.0, 55.0], dtype=np.float32)
        land_rgb = land_rgb * 0.48 + basalt * 0.52

    precipitation_rows = _grid_rows(
        water_cycle or {},
        ("annual_precipitation_rows_mm",),
    )
    if precipitation_rows:
        precipitation = _resample_bilinear(
            np.asarray(precipitation_rows, dtype=np.float32),
            target_h,
            target_w,
        )
        # np.maximum propagates NaN rather than clamping it, so a corrupted
        # upstream climate cell would otherwise poison wetness -> land_rgb
        # (see docs/CLAUDE_CODE_HANDOFF_2026-08-16.md). A NaN cell degrades
        # to "dry" instead.
        precipitation = np.nan_to_num(precipitation, nan=0.0)
        wetness = np.clip(np.log1p(np.maximum(0.0, precipitation)) / math.log(3001.0), 0.0, 1.0)
        weathering = _clamp(model.get("chemical_weathering_strength", 0.0))
        # Wet bare rock is darker and slightly less saturated. Vegetation is
        # deliberately absent until a biosphere supplies actual cover.
        if not material_components:
            land_rgb *= (1.0 - wetness[..., None] * (0.08 + weathering * 0.10))
        dry = np.clip(1.0 - wetness * 1.55, 0.0, 1.0)
        if "aeolian_surface" in tags and not material_components:
            dust = np.asarray([174.0, 143.0, 98.0], dtype=np.float32)
            dust_mix = dry[..., None] * (0.08 + _clamp(model.get("aeolian_strength", 0.0)) * 0.18)
            land_rgb = land_rgb * (1.0 - dust_mix) + dust * dust_mix

    # 6. Dust deposition/stripping.  Dust is not a second landscape: it pools
    # on low-slope lee surfaces and is stripped from rugged exposed ground.
    if not material_components and np.any(dust_cover > 0.001):
        dust_rgb = np.asarray(
            [178.0, 132.0, 91.0]
            if regime == "oxidized_dust"
            else [166.0, 145.0, 112.0],
            dtype=np.float32,
        )
        dust_mix = dust_cover[..., None] * (0.10 + _clamp(model.get("aeolian_strength", 0.0)) * 0.24)
        land_rgb = land_rgb * (1.0 - dust_mix) + dust_rgb * dust_mix

    # 7. Fluvial/lacustrine/coastal sediment and moisture.  Depositional lows
    # brighten with fine sediment while wet exposed surfaces darken.  Material
    # specific wet darkening has already been applied in linear reflectance;
    # this smaller term captures unresolved alluvium and bank moisture.
    fluvial_deposit = np.clip(deposition * wetness * (1.0 - slope), 0.0, 1.0)
    if not material_components:
        sediment_rgb = np.asarray([158.0, 143.0, 116.0], dtype=np.float32)
        sediment_mix = fluvial_deposit[..., None] * 0.16
        land_rgb = land_rgb * (1.0 - sediment_mix) + sediment_rgb * sediment_mix
    land_rgb *= 1.0 - (wetness * (0.018 + bedrock * 0.035))[..., None]

    # 8. Volcanic resurfacing.  Fresh lava/ash is young, exposed and dark;
    # older weathered volcanic terrain remains governed by its material
    # endmember instead of receiving a blanket basalt colour.
    volcanic_world = regime == "volcanic" or bool(
        tags.intersection({"volcanic_surface", "basaltic_surface"})
    )
    if volcanic_world and not material_components:
        fresh_volcanic = np.clip((1.0 - age) * bedrock * (0.35 + ruggedness * 0.65), 0.0, 1.0)
        lava_rgb = np.asarray([47.0, 49.0, 47.0], dtype=np.float32)
        lava_mix = fresh_volcanic[..., None] * 0.31
        land_rgb = land_rgb * (1.0 - lava_mix) + lava_rgb * lava_mix

    # 9. Impact ejecta and surface maturity.  Only crater-retaining surfaces
    # get a visible maturity contrast, and it follows concavity/ruggedness and
    # the simulated age rather than an unrelated circular stamp field.
    crater_degradation_rows = _process_rows(
        surface_evolution or {}, "crater_degradation_rows"
    )
    crater_degradation = (
        _resample_bilinear(
            np.asarray(crater_degradation_rows, dtype=np.float32),
            target_h,
            target_w,
        )
        if crater_degradation_rows
        else np.zeros(elevation.shape, dtype=np.float32)
    )
    crater_retention = 0.78 if "cratered_regolith" in tags or regime == "airless_regolith" else 0.18
    impact_relief = np.clip((np.abs(curvature) * 0.65 + ruggedness * 0.35) * age, 0.0, 1.0)
    impact_contrast = impact_relief * crater_retention * (1.0 - crater_degradation * 0.86)
    terrain_albedo += (impact_contrast - impact_contrast.mean()) * 0.038

    land_rgb *= 1.0 + np.clip(terrain_albedo, -0.18, 0.18)[..., None]

    # True-colour oceans are dark reflectors; shallow shelves receive sediment
    # colour while deep water approaches blue-black.
    ocean_shallow = np.asarray([38.0, 94.0, 119.0], dtype=np.float32)
    ocean_deep = np.asarray([7.0, 24.0, 43.0], dtype=np.float32)
    ocean_rgb = ocean_shallow[None, None, :] * (1.0 - depth[..., None]) + ocean_deep[None, None, :] * depth[..., None]
    # Shelf depth and delivered sediment, rather than random blue mottling,
    # create orbital-scale variation in water colour.
    coastal_sediment = np.clip(deposition * (1.0 - depth) * 0.18, 0.0, 0.18)
    ocean_rgb = ocean_rgb * (1.0 - coastal_sediment[..., None]) + np.asarray(
        [71.0, 105.0, 105.0], dtype=np.float32
    ) * coastal_sediment[..., None]
    rgb = np.where(ocean[..., None], ocean_rgb, land_rgb)

    ice_rgb = np.asarray([218.0, 229.0, 232.0], dtype=np.float32)
    ice_texture = (
        0.91 + np.clip(local_relief * 0.055 + ruggedness * 0.06, -0.08, 0.09)
    )[..., None]
    rgb = np.where(ice[..., None], ice_rgb * ice_texture, rgb)

    detail_level = max(0, int(heightmap.get("map_detail_level", 0) or 0))
    # Use the same physical gradient normalization as the heightmap
    # diagnostic. True Color keeps material hue and optical response, but its
    # luminance must visibly follow the same terrain normals. The old formula
    # used resampled display-pixel spacing, making regional normals too
    # shallow and leaving LOD2 visually detached from its heightmap.
    terrain_span = max(
        1.0,
        float(heightmap.get("max_elevation_m", 1.0) or 1.0)
        - float(heightmap.get("min_elevation_m", 0.0) or 0.0),
    )
    source_dx = dzdx * spacing_x
    source_dy = dzdy * spacing_y
    diagnostic_gradient_scale = max(1.0, terrain_span * 0.018)
    # Planetary samples average very large areas, so LOD0 gets a little more
    # normal gain. Regional terrain already contains real slopes and tapers
    # quickly to avoid resurrecting the old contour-scratch artifact.
    normal_gain = max(1.0, 2.8 / (2.0 ** detail_level))
    nx = -source_dx / diagnostic_gradient_scale * normal_gain
    ny = -source_dy / diagnostic_gradient_scale * normal_gain
    nz = np.ones_like(nx)
    norm = np.sqrt(nx * nx + ny * ny + nz * nz)
    light = np.asarray([-0.62, -0.48, 0.62], dtype=np.float32)
    light /= max(1e-6, float(np.linalg.norm(light)))
    illumination = np.clip(
        (nx * light[0] + ny * light[1] + nz * light[2]) / norm,
        0.0,
        1.0,
    )
    # Concave, rugged terrain has a smaller visible sky hemisphere.  This
    # terrain-derived ambient-occlusion proxy makes mountain structure legible
    # without changing elevation or inventing a cosmetic texture.
    sky_view = np.clip(1.0 - concavity * ruggedness * 0.24 - scarp * 0.08, 0.68, 1.0)
    if detail_level >= 1:
        # Keep a broad ambient floor while retaining enough normal contrast
        # for mountain chains and valleys in the material-coloured surface.
        shade = (0.54 + illumination * 0.58) * sky_view
    else:
        shade = (0.50 + illumination * 0.66) * sky_view
    shade *= 1.0 + convexity * ridge * 0.035
    # Keep ocean reflectance mostly independent of terrain relief.
    shade = np.where(ocean, 0.94 + illumination * 0.06, shade)
    rgb *= shade[..., None]

    atmosphere = atmosphere if isinstance(atmosphere, dict) else {}
    visual = atmosphere.get("visual_model") if isinstance(atmosphere.get("visual_model"), dict) else {}
    pressure = max(0.0, float(model.get("surface_pressure_bar", 0.0) or 0.0))
    if pressure >= 0.0015 and atmosphere and visual.get("visible", True):
        tint = np.asarray(_rgb(visual.get("tint_color"), fallback=(170, 184, 198)), dtype=np.float32)
        haze = min(0.18, 0.018 + math.log1p(pressure) * 0.055)
        rgb = rgb * (1.0 - haze) + tint * haze

    rgb = np.clip(rgb, 0.0, 255.0).astype(np.uint8)
    surface = pygame.surfarray.make_surface(np.transpose(rgb, (1, 0, 2)))
    # Rivers are water surfaces and therefore belong in True Color. Their
    # color is derived from hydrology and suspended/mineral load proxies;
    # planetary rendering intentionally has no vegetation contribution.
    river_overlay = _true_color_river_overlay(water_cycle, surface.get_size())
    if river_overlay is not None:
        surface = surface.convert_alpha()
        surface.blit(river_overlay, (0, 0))
        surface.set_alpha(None)
    return surface
