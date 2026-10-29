"""Hierarchical map refinement for generated worlds.

Architecture invariants: entity and semantic truth is ontology-owned; local
lookups and rasters are derived caches. Generated planets are currently
disposable, so a changed refinement contract invalidates old products rather
than requiring compatibility behavior.

LOD contract: a refinement is a physical-footprint child of exactly one
immediate parent. It may expose smaller structures, but inherited elevation,
topology, climate, hydrology, materials, and geology must come from that
parent snapshot. Root references are ancestry/audit data, not live overrides.
See docs/worldgen_lod_mechanism_matrix_v001.md.
"""

import copy
import hashlib
import json
import math
import time
from pathlib import Path

import numpy as np

from engine.logger import logger
from simulations.world_gen.regional_landforms import apply_regional_landforms
from simulations.world_gen.heightmap import (
    _clamp, _crater_height_adjustment_m, _crater_spatial_index, _fbm_noise,
    _ensure_heightmap_tectonic_model, _heightmap_tectonic_model,
    _nearby_boundary_segments, _orogen_forcing_at, _wrapped_point_segment_distance,
    _wave_height,
    crustal_freeboard_shift_at,
    refresh_heightmap_derivatives,
)
from simulations.world_gen.array_noise import seed_int
from simulations.world_gen.geological_noise import branching_mountain_relief_m, fractal_noise_m
from simulations.world_gen.coastal_geomorphology import (
    coastal_summary,
    derive_coastal_geomorphology_model,
    enrich_coastal_hydrology,
    inherit_parent_coastal_context,
    materialize_regional_coastal_landforms,
    stabilize_regional_coastal_topology,
)
from simulations.world_gen.exact_rounding import height_decimals
from simulations.world_gen.map_seed import seed_range
from simulations.world_gen.material_heatmaps import generate_material_heatmap_model
from simulations.world_gen.regional_materials import derive_regional_material_model
from simulations.world_gen.regolith_soils import derive_regolith_soil_model
from simulations.world_gen.surface_evolution import derive_surface_evolution_model
from simulations.world_gen.surface_exposure import derive_surface_exposure_model
from simulations.world_gen.surface_geomorphology import (
    derive_surface_geomorphology_model,
    dominant_structural_strike_degrees,
)
from simulations.world_gen.true_color import derive_true_color_model
from simulations.world_gen.water_cycle import derive_water_cycle_model


MIN_REFINED_EXTENT_M = 10.0
MIN_TERRAIN_SAMPLE_SPACING_M = 0.10
MIN_TERRAIN_PROCESS_WAVELENGTH_M = 0.50
# Child detail fades to zero over this fraction of the tile at its edges, so
# a child meets its parent (and its siblings) exactly on the boundary.  At
# 5.5 % the untextured band read as a frame around every regional map.
PARENT_EDGE_FADE_FRACTION = 0.018
SURFACE_DETAIL_CONTRACT_VERSION = "surface-detail-contract-v1"


DETAIL_LEVELS = {
    0: {
        "id": "planetary",
        "label": "Planetary",
        "typical_footprint_km": "full planet",
        "scientific_sample_spacing_m": "10,000–40,000",
        "nominal_resolution": "10–40 km scientific support",
        "features": ["plates", "continents", "ocean_basins", "global_climate", "major_rivers"],
    },
    1: {
        "id": "macroregion",
        "label": "Macroregion",
        "typical_footprint_km": "500–2,000",
        "scientific_sample_spacing_m": "1,000–10,000",
        "nominal_resolution": "1–10 km scientific support",
        "features": ["mountain_ridges", "drainage_basins", "river_networks", "large_lakes", "coastal_shelves"],
    },
    2: {
        "id": "region",
        "label": "Region",
        "typical_footprint_km": "50–250",
        "scientific_sample_spacing_m": "100–500",
        "nominal_resolution": "100–500 m scientific support",
        "features": ["tributaries", "hills", "small_lakes", "beaches", "wetlands", "microclimates"],
    },
    3: {
        "id": "local",
        "label": "Local",
        "typical_footprint_km": "5–30",
        "scientific_sample_spacing_m": "10–100",
        "nominal_resolution": "10–100 m scientific support",
        "features": ["streams", "ponds", "dunes", "cliffs", "floodplains", "soil_variation"],
    },
    4: {
        "id": "site",
        "label": "Site",
        "typical_footprint_km": "0.5–5",
        "scientific_sample_spacing_m": "0.5–10",
        "nominal_resolution": "0.5–10 m scientific support",
        "features": ["channels", "banks", "bedrock_outcrops", "microrelief", "vegetation_zones"],
    },
    5: {
        "id": "parcel",
        "label": "Parcel",
        "typical_footprint_km": "0.1–0.5",
        "scientific_sample_spacing_m": "0.1–1",
        "nominal_resolution": "0.1–1 m scientific support",
        "features": ["small_gullies", "terraces", "stream_banks", "rock_outcrops", "local_depressions"],
    },
    6: {
        "id": "plot",
        "label": "Plot",
        "typical_footprint_km": "0.02–0.1",
        "scientific_sample_spacing_m": "0.1 floor",
        "nominal_resolution": "0.1 m terrain-data floor",
        "features": ["erosion_rills", "hummocks", "minor_channels", "bank_microtopography", "bedrock_ledges"],
    },
    7: {
        "id": "survey",
        "label": "Survey",
        "typical_footprint_km": "0.005–0.03",
        "scientific_sample_spacing_m": "0.1 floor",
        "nominal_resolution": "0.1 m terrain-data floor",
        "features": ["microdrainage", "shallow_hollows", "rills", "bedrock_steps", "tide_pool_basins"],
    },
}

MAX_DETAIL_LEVEL = max(DETAIL_LEVELS)
_CRATER_GRID_CACHE = {}


def _regional_water_cycle(terrain, heightmap, **options):
    """A regional tile's water cycle; from Site scale down its surface rasters are read off the ground.

    At every level it also carries the sunlight the ground's own slope
    receives (``solar_exposure``).
    """
    from simulations.world_gen.fine_hydrology import refine_surface_hydrology
    from simulations.world_gen.solar_exposure import with_surface_solar_exposure

    seed = options.get("seed") if isinstance(options.get("seed"), dict) else {}
    # A finer tile takes its water table from the map it was cut from: it cannot see the water that sets it.
    parent_heightmap = options.pop("parent_heightmap", None)
    water_cycle = refine_surface_hydrology(
        heightmap, derive_water_cycle_model(terrain, heightmap, **options),
        parent=(parent_heightmap, options.get("parent_climate_model")),
    )
    return with_surface_solar_exposure(heightmap, water_cycle, float(seed.get("axial_tilt_deg", 23.44) or 23.44))


def _model_fingerprint(value):
    """Return a stable lineage fingerprint for a persisted parent model."""
    payload = json.dumps(value if value is not None else {}, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def detail_level_spec(level):
    return copy.deepcopy(DETAIL_LEVELS[max(0, min(MAX_DETAIL_LEVEL, int(level or 0)))])


def refinement_sample_dimensions(level, width_m, height_m):
    """Choose grid support without crossing the 10 cm terrain-data floor."""
    level = max(0, min(MAX_DETAIL_LEVEL, int(level or 0)))
    width_m = max(MIN_TERRAIN_SAMPLE_SPACING_M, float(width_m or 0.0))
    height_m = max(MIN_TERRAIN_SAMPLE_SPACING_M, float(height_m or 0.0))
    aspect = max(0.5, min(3.0, width_m / max(MIN_TERRAIN_SAMPLE_SPACING_M, height_m)))
    if level <= 2:
        sample_width = 513
        sample_height = max(
            257,
            min(sample_width, int(round((sample_width - 1) / aspect)) + 1),
        )
    elif level <= 5:
        sample_width = 385
        sample_height = max(
            193,
            min(sample_width, int(round((sample_width - 1) / aspect)) + 1),
        )
    else:
        sample_width = max(
            3,
            min(385, int(math.floor(width_m / MIN_TERRAIN_SAMPLE_SPACING_M)) + 1),
        )
        sample_height = max(
            3,
            min(385, int(math.floor(height_m / MIN_TERRAIN_SAMPLE_SPACING_M)) + 1),
        )
    if level <= 5 and sample_height % 2 == 0 and sample_height < 385:
        sample_height += 1
    return sample_width, sample_height


def surface_detail_contract(heightmap):
    """Describe how later object and biosphere detail attaches to terrain truth."""
    level = int(heightmap.get("map_detail_level", 0) or 0)
    return {
        "status": "terrain_basis_ready",
        "model_version": SURFACE_DETAIL_CONTRACT_VERSION,
        "terrain_representation": "continuous_heightfield",
        "minimum_terrain_sample_spacing_m": MIN_TERRAIN_SAMPLE_SPACING_M,
        "minimum_terrain_process_wavelength_m": MIN_TERRAIN_PROCESS_WAVELENGTH_M,
        "terrain_grid_spacing_m": {
            "x": round(float(heightmap.get("sample_spacing_x_m", 0.0) or 0.0), 6),
            "y": round(float(heightmap.get("sample_spacing_y_m", 0.0) or 0.0), 6),
        },
        "object_detail_layer": {
            "status": "deferred_sparse_deterministic_placement",
            "activates_from_detail_level": 6,
            "active_for_this_region": level >= 6,
            "terrain_cell_reference": "heightmap_model.sample_grid",
            "material_reference": "regional_material_model",
            "hydrology_reference": "water_cycle_model",
            "placement_seed_reference": "heightmap_model.map_seed",
            "future_object_families": [
                "loose_rocks",
                "boulders",
                "debris_and_wrack",
                "individual_plants",
                "deadwood",
                "burrows_and_nests",
                "organism_scale_microhabitats",
            ],
        },
        "heightfield_exclusions": [
            "individual_loose_rocks",
            "debris",
            "individual_organisms",
            "vegetation_stems",
            "burrows_smaller_than_terrain_support",
            "cosmetic_surface_granularity",
        ],
        "storage_policy": "store_compact_contract_and_seed; materialize_sparse_objects_lazily",
    }


def map_physical_dimensions_m(entity):
    """Return the physical width and height represented by a map entity."""
    heightmap = entity.get("heightmap_model") if isinstance(entity, dict) else None
    if not isinstance(heightmap, dict):
        heightmap = entity if isinstance(entity, dict) else {}
    circumference = float(
        heightmap.get("planet_circumference_m")
        or heightmap.get("circumference_m")
        or 0.0
    )
    width_m = float(heightmap.get("region_width_m") or heightmap.get("circumference_m") or circumference or 0.0)
    height_m = float(heightmap.get("region_height_m") or (circumference * 0.5 if circumference else 0.0))
    return max(0.0, width_m), max(0.0, height_m)


def _parent_coastal_context(parent_entity, center_uv):
    segments = ((parent_entity.get("coastal_geomorphology_model") or {}).get("segments") or [])
    if not segments:
        return {"coastal_system": None, "morphology_assemblage": None}

    def distance(segment):
        points = ((segment.get("geometry") or {}).get("points") or [])
        if not points:
            points = [(segment.get("measurements") or {}).get("centroid_uv") or [0.5, 0.5]]
        return min(math.hypot(float(point[0]) - center_uv[0], float(point[1]) - center_uv[1]) for point in points)

    segment = min(segments, key=distance)
    morphology = str(
        segment.get("morphology_assemblage")
        or segment.get("primary_assemblage")
        or "headland_bay"
    )
    return {
        "parent_segment_id": segment.get("id"),
        "coastal_system": str(segment.get("coastal_system") or morphology),
        "morphology_assemblage": morphology,
    }


# LOD1 creates most of the sub-parent relief (hundreds of metres); deeper
# levels add metres and inherit LOD1's valleys.
# A step that lowers the ground leaves land at least this far above the sea.
LAND_FLOOR_ABOVE_SEA_M = 0.5


def _land_floor(elevation, sea_level):
    """Lowest height a step may leave each land cell at: the floor, or where the cell already was if lower.

    The floor used to be applied to every land cell, lowered or not: all
    land lower than half a metre was raised to exactly half a metre, by the
    dissection, by the floodplains and again by the last bed fit, and every
    low shore from Local scale down stood on a half-metre step (86 % of the
    land within two cells of the water on one Parcel tile).
    """
    return np.minimum(elevation, float(sea_level) + LAND_FLOOR_ABOVE_SEA_M)


FLUVIAL_DISSECTION_MIN_LEVEL = 1
def _fluvial_dissection(rows, inherited_rows, *, sea_level, spacing_x_m, spacing_y_m, parent_spacing_m, level, seed=0, inflow=None):
    """Organise a child's new relief by its drainage (stream-power incision).

    The detail band adds relief below the parent's resolution as isotropic
    noise, which reads as egg-crate bumps.  ``fluvial_relief`` erodes it with
    the stream-power law along the drainage tree plus hillslope diffusion, so
    valleys with concave profiles and sloping walls replace the bumps.  The
    change is then made zero-mean at the parent's sample spacing (the
    material removed from valleys is returned to the surrounding surface), so
    the child still box-filters to its parent, and river beds are fitted
    never to rise downstream (``_fit_channel_beds``); it fades out at tile
    edges like the rest of the detail, and land never drops below sea level,
    so the inherited coastline is kept.
    """
    from simulations.world_gen.fluvial_relief import conserve_parent_scale, stream_power_relief

    if int(level) < FLUVIAL_DISSECTION_MIN_LEVEL or not rows or not rows[0]:
        return rows, {"applied": False}
    elevation = np.asarray(rows, dtype=np.float64)
    inherited = np.asarray(inherited_rows, dtype=np.float64)
    land = elevation >= float(sea_level) if sea_level is not None else np.ones(elevation.shape, dtype=bool)
    detail = (elevation - inherited)[land]
    if detail.size < 64:
        return rows, {"applied": False}
    relief = float(np.percentile(detail, 95.0) - np.percentile(detail, 5.0))
    if relief <= 1.0:
        return rows, {"applied": False}
    radius = max(1, int(round(parent_spacing_m / max(spacing_x_m, spacing_y_m, 1e-6) * 0.5)))
    from simulations.world_gen.material_routing import box_mean

    detail_field = np.where(land, elevation - inherited, 0.0)
    # Local amplitude of the new relief (about p95 - p5 when normal).
    local_relief = 3.3 * np.sqrt(np.maximum(box_mean(detail_field * detail_field, radius), 0.0))
    from simulations.world_gen.material_routing import inflow_grid

    eroded, solver = stream_power_relief(
        elevation, land, dx=spacing_x_m, dy=spacing_y_m, seed=seed, detail_relief=local_relief,
        inflow_cells=inflow_grid(elevation.shape, inflow, spacing_x_m * spacing_y_m),
    )
    restored = _fit_channel_beds(
        conserve_parent_scale(elevation, eroded, land, radius), land,
        spacing_x_m=spacing_x_m, spacing_y_m=spacing_y_m, inflow=inflow,
    )
    height, width = elevation.shape
    local_u = np.arange(width) / max(1, width - 1)
    local_v = np.arange(height) / max(1, height - 1)
    edge = np.minimum(np.minimum(local_u, 1.0 - local_u)[None, :], np.minimum(local_v, 1.0 - local_v)[:, None])
    fade = np.clip(edge / PARENT_EDGE_FADE_FRACTION, 0.0, 1.0)
    fade = fade * fade * (3.0 - 2.0 * fade)
    result = elevation + (restored - elevation) * fade
    if sea_level is not None:
        result = np.where(land, np.maximum(result, _land_floor(elevation, sea_level)), elevation)
    change = result - elevation
    return np.round(result, height_decimals(min(spacing_x_m, spacing_y_m))).tolist(), {
        "applied": True,
        "model": "stream_power_incision_v1",
        "detail_relief_m": round(relief, 1),
        "max_incision_m": round(float(-change.min()), 1),
        "max_raise_m": round(float(change.max()), 1),
        "mean_change_m": round(float(change[land].mean()) if land.any() else 0.0, 3),
        "conservation_radius_cells": radius,
        **solver,
    }


def _regional_ice_mask(
    parent_ice_rows, rows, *, parent_wrap_x, parent_bounds, parent_spacing_m, spacing_m, seed,
    source_uv=None, planet_circumference_m=None, noise_seed=None, level=0,
):
    """Inherit the parent's ice mask with margins that follow local terrain.

    The child used to threshold a bilinear sample of the parent's binary mask,
    so ice margins traced the parent's 78 km cells as straight-edged polygons.
    Coverage is a smooth B-spline of the parent mask, widened by half a
    parent cell (the parent's margin is uncertain by about that much); inside
    the margin zone, ice is favoured on ground above its mean over about two
    parent cells (ice caps sit on highs, valleys below them melt out) and a
    fractal term with wavelengths from the parent's spacing down to two child
    cells keeps the margin irregular where the ground is smooth.  Without
    that range of wavelengths a LOD3 tile still showed the 15 km straight
    edges and 45-degree steps of LOD0's cells.  With ``source_uv`` the
    fractal term is world-coherent (``geological_noise``), so neighbouring
    tiles agree; all terms fade at the tile edge, so the child mask still
    meets the parent's there.
    """
    from simulations.world_gen.array_noise import fbm
    from simulations.world_gen.material_routing import box_mean, gaussian_blur

    elevation = np.asarray(rows, dtype=np.float64)
    height, width = elevation.shape
    u0, u1, v0, v1 = parent_bounds
    local_u = (np.arange(width) / max(1, width - 1))[None, :]
    local_v = (np.arange(height) / max(1, height - 1))[:, None]
    coverage_rows = np.asarray([[1.0 if value else 0.0 for value in row] for row in parent_ice_rows], dtype=np.float64)
    sampled = np.broadcast_to(
        _sample_bicubic_grid(coverage_rows, u0 + (u1 - u0) * local_u, v0 + (v1 - v0) * local_v, wrap_x=parent_wrap_x),
        elevation.shape,
    )
    edge = np.minimum(np.minimum(local_u, 1.0 - local_u), np.minimum(local_v, 1.0 - local_v))
    fade = np.clip(edge / PARENT_EDGE_FADE_FRACTION, 0.0, 1.0)
    fade = fade * fade * (3.0 - 2.0 * fade)
    cells_per_parent = parent_spacing_m / max(spacing_m, 1e-6) if parent_spacing_m > 0.0 else 8.0
    coverage = sampled + (gaussian_blur(sampled, max(1.0, 0.5 * cells_per_parent)) - sampled) * fade
    radius = max(2, int(round(cells_per_parent)))
    local_mean = box_mean(elevation, radius)
    local_spread = np.sqrt(np.maximum(box_mean((elevation - local_mean) ** 2, radius), 0.0))
    terrain = np.tanh((elevation - local_mean) / np.maximum(50.0, 1.5 * local_spread))
    if source_uv is not None and planet_circumference_m and parent_spacing_m > 0.0:
        from simulations.world_gen.geological_noise import fractal_noise_grid

        gu0, gu1, gv0, gv1 = source_uv
        world_x = np.broadcast_to((gu0 + (gu1 - gu0) * local_u) * planet_circumference_m, elevation.shape)
        world_y = np.broadcast_to((gv0 + (gv1 - gv0) * local_v) * planet_circumference_m * 0.5, elevation.shape)
        octaves = max(1, int(math.ceil(math.log2(max(2.0, cells_per_parent / 2.0)))))
        noise = fractal_noise_grid(
            noise_seed if noise_seed is not None else seed, f"ice-margin-lod{int(level)}", world_x, world_y, parent_spacing_m,
            octaves=octaves, gain=COASTLINE_OCTAVE_GAIN, period_x_m=planet_circumference_m,
        )
    else:
        noise = (fbm(local_u * 24.0 + np.zeros(elevation.shape), local_v * 24.0 + np.zeros(elevation.shape), seed, octaves=3) - 0.5) * 2.0
    margin = np.clip(1.0 - np.abs(2.0 * coverage - 1.0), 0.0, 1.0)
    adjusted = coverage + (terrain * 0.30 + noise * 0.25) * margin * fade
    ice = adjusted >= 0.5
    return ice.tolist(), {
        "applied": True,
        "model": "terrain_following_ice_margin_v2",
        "ice_fraction": round(float(ice.mean()), 4),
        "margin_cell_fraction": round(float((margin > 0.05).mean()), 4),
    }


# --- Shoreline refinement ------------------------------------------------------
# Inside a parent cell that straddles sea level the shore's position is
# unresolved; the child may move it by up to this fraction of the parent's
# spacing either way.
COASTLINE_SHIFT_CELLS = 0.4
# Coasts whose parent cell spans more relief than this are progressively
# straighter (cliffed and fault-bounded margins against drowned lowlands).
COASTLINE_STEEP_RANGE_M = 400.0
# Octave gain of the shoreline displacement: H ~ 0.7, i.e. a fractal dimension
# near 1.3 (Richardson / Mandelbrot: 1.02 South Africa to 1.5 Norway).
COASTLINE_OCTAVE_GAIN = 0.62


def _refine_coastline(
    rows, parent_rows, *, parent_uv, source_uv, sea_level, parent_wrap_x, seed, level,
    planet_circumference_m, parent_spacing_m, spacing_m,
):
    """Resolve the shoreline inside parent cells that straddle sea level.

    A child inherited its parent's shoreline as the sea-level contour of the
    interpolated parent heights and then froze it (every later step keeps
    land above and sea below).  LOD0's 78 km cells therefore reached LOD3 as
    dead-straight shores and rectangular bays.  Real shorelines are rough at
    every scale (Richardson 1961; Mandelbrot 1967): within a parent cell
    whose corners lie on both sides of sea level the shore's position is not
    resolved, so the child shifts it there by a world-coherent fractal
    displacement of up to ``COASTLINE_SHIFT_CELLS`` parent cells, with
    wavelengths from the parent's spacing down to two child cells.  The
    shift is applied as a height change (displacement times the relief
    across the parent cell), so gentle coasts gain bays, spits and headlands
    while steep ones stay nearly straight; it is zero in parent cells that
    are certainly land or sea and at the tile edge.

    Returns ``(rows, shift_rows, summary)``; ``shift_rows`` belongs to the
    parent-height contract's reference like the regional landforms.
    """
    from simulations.world_gen.geological_noise import fractal_noise_grid
    from simulations.world_gen.material_routing import gaussian_blur

    elevation = np.asarray(rows, dtype=np.float64)
    zero = np.zeros(elevation.shape)
    if sea_level is None or parent_spacing_m <= 0.0 or spacing_m <= 0.0 or not parent_rows:
        return rows, zero.tolist(), {"applied": False}
    parent_width = min(len(row) for row in parent_rows)
    parent = np.asarray([row[:parent_width] for row in parent_rows], dtype=np.float64)
    height, width = elevation.shape
    local_u = (np.arange(width, dtype=np.float64) / max(1, width - 1))[None, :]
    local_v = (np.arange(height, dtype=np.float64) / max(1, height - 1))[:, None]
    u0, u1, v0, v1 = parent_uv
    parent_u = np.broadcast_to(u0 + (u1 - u0) * local_u, elevation.shape)
    parent_v = np.broadcast_to(v0 + (v1 - v0) * local_v, elevation.shape)
    px = (np.mod(parent_u, 1.0) if parent_wrap_x else np.clip(parent_u, 0.0, 1.0)) * max(1, parent.shape[1] - 1)
    py = np.clip(parent_v, 0.0, 1.0) * max(1, parent.shape[0] - 1)
    x0 = np.floor(px).astype(np.int64)
    y0 = np.floor(py).astype(np.int64)
    x1 = (x0 + 1) % parent.shape[1] if parent_wrap_x else np.minimum(parent.shape[1] - 1, x0 + 1)
    y1 = np.minimum(parent.shape[0] - 1, y0 + 1)
    corners = np.stack([parent[y0, x0], parent[y0, x1], parent[y1, x0], parent[y1, x1]])
    low, high = corners.min(axis=0), corners.max(axis=0)
    mixed = (low < float(sea_level)) & (high >= float(sea_level))
    if not mixed.any():
        return rows, zero.tolist(), {"applied": False, "mixed_cell_fraction": 0.0}
    cells_per_parent = parent_spacing_m / spacing_m
    # Full inside the band of mixed cells, nothing where the parent is certain.
    weight = np.clip(2.0 * gaussian_blur(mixed.astype(np.float64), max(1.0, 0.25 * cells_per_parent)) - 1.0, 0.0, 1.0)
    weight = np.where(mixed, weight, 0.0)
    gu0, gu1, gv0, gv1 = source_uv
    world_x = np.broadcast_to((gu0 + (gu1 - gu0) * local_u) * planet_circumference_m, elevation.shape)
    world_y = np.broadcast_to((gv0 + (gv1 - gv0) * local_v) * planet_circumference_m * 0.5, elevation.shape)
    octaves = max(1, int(math.ceil(math.log2(max(2.0, cells_per_parent / 2.0)))))
    displacement = fractal_noise_grid(
        seed, f"coastline-lod{int(level)}", world_x, world_y, parent_spacing_m,
        octaves=octaves, gain=COASTLINE_OCTAVE_GAIN, period_x_m=planet_circumference_m,
    )
    relief = high - low
    steep = 1.0 / (1.0 + relief / COASTLINE_STEEP_RANGE_M)
    edge = np.minimum(np.minimum(local_u, 1.0 - local_u), np.minimum(local_v, 1.0 - local_v))
    fade = np.clip(edge / PARENT_EDGE_FADE_FRACTION, 0.0, 1.0)
    fade = fade * fade * (3.0 - 2.0 * fade)
    shift = displacement * COASTLINE_SHIFT_CELLS * steep * relief * weight * fade
    refined = elevation + shift
    moved = (refined >= float(sea_level)) != (elevation >= float(sea_level))
    return np.round(refined, height_decimals(spacing_m)).tolist(), shift.tolist(), {
        "applied": True,
        "model": "fractal_shoreline_in_mixed_parent_cells_v1",
        "mixed_cell_fraction": round(float(mixed.mean()), 4),
        "cells_changed_side_fraction": round(float(moved.mean()), 4),
        "octaves": octaves,
        "max_shift_m": round(float(np.abs(shift).max()), 1),
    }


def _center_detail_at_parent_scale(rows, inherited_rows, *, sea_level, spacing_x_m, spacing_y_m, parent_spacing_m, topology_rows=None):
    """Remove the parent-scale mean of the new detail.

    Belt uplift and the production residual had a positive mean over whole
    tiles, while the tile edge is locked to the parent: the interior stood
    hundreds of metres above its rim, which rendered as a bevelled frame and
    broke lineage (a child should box-filter to its parent).  The detail's
    mean over a parent cell is subtracted everywhere, sea floor and coastal
    lowland included (faded like the detail, so the boundary still equals
    the parent).  Left in under water and on land below 250 m, that mean
    (650 m on one LOD1 tile) lifted a whole shallow bay above sea level; the
    parent-height contract then pushed only the parent's certain-ocean
    cells back under, and the shore came out as the parent's rectangles.

    Sea level: where the parent is certain (``topology_rows`` +1 land, -1
    ocean: all four parent corners on one side) a cell stays on that side,
    with detail towards sea level compressed smoothly instead of clamped (a
    clamp made flat shelves and steps).  In parent cells that straddle sea
    level the centred detail is free to cross it: that is where valleys
    drown and the shoreline is resolved.  Without ``topology_rows`` every
    cell keeps the side of its interpolated parent height.

    The compression is measured against the cell's own clearance from sea
    level, however small.  With a floor of a metre under it, every cell less
    than a metre from sea level whose detail leaned towards it was thrown a
    full metre to its side, while its neighbour whose detail leaned away
    stayed: shallow water and low shores at Parcel and Plot scale came out
    as a maze of metre-high steps.
    """
    from simulations.world_gen.material_routing import box_mean

    if not rows or not rows[0] or parent_spacing_m <= 0.0:
        return rows, {"applied": False}
    elevation = np.asarray(rows, dtype=np.float64)
    inherited = np.asarray(inherited_rows, dtype=np.float64)
    detail = elevation - inherited
    radius = max(1, int(round(parent_spacing_m / max(spacing_x_m, spacing_y_m, 1e-6) * 0.5)))
    height, width = elevation.shape
    local_u = np.arange(width) / max(1, width - 1)
    local_v = np.arange(height) / max(1, height - 1)
    edge = np.minimum(np.minimum(local_u, 1.0 - local_u)[None, :], np.minimum(local_v, 1.0 - local_v)[:, None])
    fade = np.clip(edge / PARENT_EDGE_FADE_FRACTION, 0.0, 1.0)
    fade = fade * fade * (3.0 - 2.0 * fade)
    # The detail arrives already faded to zero at the tile edge.  Its plain
    # box mean is too small inside the fade band (the window reaches the
    # faded cells), which left a ridge of a tenth of the offset just inside
    # every edge: the bevelled frame.  Weighted by the fade, the mean is that
    # of the unfaded detail.
    offset = box_mean(detail, radius) / np.maximum(box_mean(fade, radius), 1e-3)
    result = elevation - offset * fade
    crossed = 0.0
    if sea_level is not None:
        sea = float(sea_level)
        if topology_rows is not None and np.shape(topology_rows) == elevation.shape:
            side = np.asarray(topology_rows, dtype=np.float64)
        else:
            side = np.where(inherited >= sea, 1.0, -1.0)
        # Clearance from sea level on the parent's side.
        clearance = side * np.maximum(np.abs(inherited - sea), 1e-9)
        centred = result - inherited
        towards_sea = (side != 0.0) & (centred * side < 0.0)
        ratio = np.where(towards_sea, centred / np.where(clearance == 0.0, 1.0, clearance), 0.0)
        compressed = sea + clearance * np.exp(np.clip(ratio, -50.0, 0.0))
        result = np.where(towards_sea, compressed, result)
        # On a flat shore the detail's cell-scale noise decided land or sea
        # cell by cell.  An island or pond of one cell is below what the
        # grid resolves: cells against nearly all their neighbours are
        # mirrored to the neighbours' side (twice, for pairs).
        free = side == 0.0
        for _pass in range(2):
            land_now = (result >= sea).astype(np.float64)
            land_neighbours = box_mean(land_now, 1) * 9.0 - land_now
            lone = free & (((land_now > 0.5) & (land_neighbours <= 1.5)) | ((land_now < 0.5) & (land_neighbours >= 6.5)))
            result = np.where(lone, 2.0 * sea - result, result)
        crossed = float(np.mean((result >= sea) != (inherited >= sea)))
    return np.round(result, height_decimals(min(spacing_x_m, spacing_y_m))).tolist(), {
        "applied": True,
        "model": "parent_scale_zero_mean_detail_v2",
        "radius_cells": radius,
        "mean_offset_removed_m": round(float(np.mean(offset * fade)), 2),
        "max_offset_removed_m": round(float(np.max(np.abs(offset * fade))), 2),
        "cells_changed_side_fraction": round(crossed, 4),
    }


def _parent_inflow_fields(parent_heightmap, shape, parent_climate_grid):
    """The parent's annual climate on its height grid, and what its own inflow brought.

    Returns ``(fields, inflow_fields)`` for ``material_routing.boundary_inflow``:
    ``fields`` in mm per cell (the climate grid sampled at the height grid's
    cells), ``inflow_fields`` in m2 mm where the parent's own record lays its
    inflow (``None`` per field when the record carries no catchment means).
    """
    from simulations.world_gen.water_cycle import _INFLOW_CATCHMENT_FIELDS

    grid = parent_climate_grid if isinstance(parent_climate_grid, dict) else {}
    fields = {}
    for name, key in _INFLOW_CATCHMENT_FIELDS.items():
        rows = grid.get(key)
        if not rows:
            continue
        values = np.asarray([row[:min(len(r) for r in rows)] for row in rows], dtype=np.float64)
        row_of = np.rint(np.arange(shape[0]) / max(1, shape[0] - 1) * (values.shape[0] - 1)).astype(int)
        column_of = np.rint(np.arange(shape[1]) / max(1, shape[1] - 1) * (values.shape[1] - 1)).astype(int)
        fields[name] = np.nan_to_num(values[np.ix_(row_of, column_of)])
    record = parent_heightmap.get("boundary_inflow") if isinstance(parent_heightmap.get("boundary_inflow"), dict) else {}
    means = record.get("catchment_means_mm") or {}
    inflow_fields = {}
    for name in fields:
        column = means.get(name)
        if not column or len(column) != len(record.get("cells") or []):
            continue
        brought = np.zeros(shape)
        for (x, y, area_m2), mean in zip(record["cells"], column):
            if 0 <= int(y) < shape[0] and 0 <= int(x) < shape[1]:
                brought[int(y), int(x)] += float(area_m2) * float(mean)
        inflow_fields[name] = brought
    return fields, inflow_fields


def _parent_solver_routing(parent_heightmap, parent_water_cycle, sea_level, parent_wrap_x):
    """The parent's drainage solver routing, rebuilt from what the parent keeps.

    A child must receive the rivers its parent shows.  Routing the parent's
    heightmap again (a finer grid, another D8) can send a river down the
    other side of a ridge: a Site lost the stream its Local map drew across
    it.  The solver's own inputs are kept (climate-grid elevation, sea level,
    the parent's own inflow), so its priority flood and flow directions are
    made again exactly.  ``None`` when the parent has no drainage.
    """
    from simulations.world_gen import drainage, water_cycle
    from simulations.world_gen.heightmap import joined_sea_rows

    grid = (parent_water_cycle or {}).get("climate_grid") or {}
    network = (parent_water_cycle or {}).get("drainage_network_model") or {}
    rows = grid.get("elevation_rows")
    if not rows or not network.get("filled_elevation_rows"):
        return None
    width = min(len(row) for row in rows)
    height = len(rows)
    if width < 2 or height < 2:
        return None
    elevation = [[float(value or 0.0) for value in row[:width]] for row in rows]
    ocean = [[sea_level is not None and value <= float(sea_level) for value in row] for row in elevation]
    joined = joined_sea_rows(parent_heightmap, (height, width))
    if joined is not None:
        ocean = [[bool(ocean[y][x] and joined[y, x]) for x in range(width)] for y in range(height)]
    region_width_m = float(parent_heightmap.get("region_width_m") or 0.0)
    region_height_m = float(parent_heightmap.get("region_height_m") or 0.0)
    if region_width_m > 0.0 and region_height_m > 0.0:
        represented_area_m2 = region_width_m * region_height_m
    else:
        represented_area_m2 = water_cycle._planet_circumference_m(parent_heightmap) ** 2 / math.pi
    inflow = None if parent_wrap_x else water_cycle._solver_boundary_inflow(
        parent_heightmap, width, height, represented_area_m2, None,
    )
    filled, flood_parent, _order = drainage._priority_flood(elevation, ocean, bool(parent_wrap_x), inlets=(inflow or {}).get("inlets"))
    downstream = drainage._terrain_flow_directions(elevation, filled, flood_parent, ocean, bool(parent_wrap_x))
    size = width * height
    receivers = np.full(size, size, dtype=np.int64)
    for (x, y), target in downstream.items():
        if target is not None:
            receivers[y * width + x] = target[1] * width + target[0]
    cell_area = np.asarray(drainage._cell_area_weights(width, height, bool(parent_wrap_x))) * represented_area_m2 / size
    inflow_area = np.zeros((height, width))
    inflow_fields = {}
    tile_means = (inflow or {}).get("means") or {}
    cell_means = (inflow or {}).get("cell_means") or {}
    for (x, y), cells in ((inflow or {}).get("cells") or {}).items():
        if not (0 <= y < height and 0 <= x < width):
            continue
        area_m2 = float(cells) * float(cell_area[y, x])
        inflow_area[y, x] += area_m2
        for name, mean in {**tile_means, **(cell_means.get((x, y)) or {})}.items():
            inflow_fields.setdefault(name, np.zeros((height, width)))[y, x] += area_m2 * float(mean)
    fields = {}
    for name, key in water_cycle._INFLOW_CATCHMENT_FIELDS.items():
        values = grid.get(key)
        if values and len(values) == height:
            fields[name] = np.nan_to_num(np.asarray([row[:width] for row in values], dtype=np.float64))
    uv = grid.get("source_uv_bounds") or parent_heightmap.get("source_uv_bounds") or {}
    return {
        "elevation": np.asarray(elevation, dtype=np.float64),
        "land": ~np.asarray(ocean, dtype=bool),
        "receivers": receivers,
        "cell_area": cell_area,
        "inflow_area": inflow_area,
        "fields": fields,
        "inflow_fields": inflow_fields,
        "bounds": {
            "min_u": float(uv.get("min_u", 0.0)), "max_u": float(uv.get("max_u", 1.0)),
            "min_v": float(uv.get("min_v", 0.0)), "max_v": float(uv.get("max_v", 1.0)),
        },
        "dx": max(1.0, region_width_m / max(1, width - 1)) if region_width_m > 0.0 else 1.0,
        "dy": max(1.0, region_height_m / max(1, height - 1)) if region_height_m > 0.0 else 1.0,
    }


def _parent_boundary_inflow(parent_heightmap, parent_rows, parent_wrap_x, sea_level, child_rows, child_bounds, parent_width_m, parent_height_m, parent_climate_grid=None, parent_water_cycle=None):
    """Where rivers enter the child tile, and how much catchment they bring.

    Routes the parent heightfield (with the parent's own boundary inflow, so
    the chain continues) and hands the crossings to
    ``material_routing.boundary_inflow``.  Spherical parents weight cells by
    their latitude area.  With the parent's climate grid, each crossing also
    carries its catchment's mean climate (``catchment_means_mm``).
    """
    from simulations.world_gen.material_routing import boundary_inflow, inflow_grid

    if not parent_rows or not child_rows:
        return {"cells": []}
    solver = _parent_solver_routing(parent_heightmap, parent_water_cycle, sea_level, parent_wrap_x) if parent_water_cycle else None
    if solver is not None:
        return boundary_inflow(
            solver["elevation"], solver["land"], solver["bounds"], solver["cell_area"],
            np.asarray(child_rows, dtype=np.float64), child_bounds,
            parent_wrap_x=bool(parent_wrap_x), parent_inflow=solver["inflow_area"],
            parent_dx=solver["dx"], parent_dy=solver["dy"],
            parent_fields=solver["fields"] or None, parent_inflow_fields=solver["inflow_fields"] or None,
            receivers=solver["receivers"],
        )
    parent = np.asarray([row[:min(len(r) for r in parent_rows)] for row in parent_rows], dtype=np.float64)
    parent_height, parent_width = parent.shape
    land = parent >= float(sea_level) if sea_level is not None else np.ones(parent.shape, dtype=bool)
    bounds = parent_heightmap.get("source_uv_bounds") if isinstance(parent_heightmap.get("source_uv_bounds"), dict) else {}
    parent_bounds = {
        "min_u": float(bounds.get("min_u", 0.0)), "max_u": float(bounds.get("max_u", 1.0)),
        "min_v": float(bounds.get("min_v", 0.0)), "max_v": float(bounds.get("max_v", 1.0)),
    }
    dx = max(1.0, float(parent_width_m) / max(1, parent_width - 1))
    dy = max(1.0, float(parent_height_m) / max(1, parent_height - 1))
    spherical = str(parent_heightmap.get("coverage") or "full_planet") == "full_planet" and bool(parent_wrap_x)
    if spherical:
        latitude = (0.5 - np.arange(parent_height) / max(1, parent_height - 1)) * math.pi
        cell_area = (dx * dy * np.maximum(0.01, np.cos(latitude)))[:, None] * np.ones((1, parent_width))
    else:
        cell_area = dx * dy
    parent_inflow = inflow_grid(parent.shape, parent_heightmap.get("boundary_inflow"), 1.0)
    fields, inflow_fields = _parent_inflow_fields(parent_heightmap, parent.shape, parent_climate_grid)
    return boundary_inflow(
        parent, land, parent_bounds, cell_area, np.asarray(child_rows, dtype=np.float64), child_bounds,
        parent_wrap_x=bool(parent_wrap_x), parent_inflow=parent_inflow, parent_dx=dx, parent_dy=dy,
        parent_fields=fields or None, parent_inflow_fields=inflow_fields or None,
    )


FLOODPLAIN_MIN_LEVEL = 3


# Floodplain-scale smoothing: this share of the widest floodplain half-width
# (2 to 32 cells).
FLOODPLAIN_RISE_SMOOTHING = 0.15


def _floodplain_sigma(belts, spacing_m):
    return float(np.clip(FLOODPLAIN_RISE_SMOOTHING * float(belts["half_width_m"].max()) / max(spacing_m, 1e-6), 2.0, 32.0))


def _floodplain_scale(field, distance_m, sigma_cells, spacing_m):
    """``field`` as it is beside the channel, smoothed at floodplain scale away from it.

    Values carried from each channel cell straight across its floodplain
    (bed level, bed correction) form flat wedges with straight edges, one
    per kink of the routed channel, which hillshade as rays over the flat
    floor.  The floor beside the channel follows the channel; farther out
    it is one smooth surface.
    """
    from simulations.world_gen.material_routing import gaussian_blur

    wide = gaussian_blur(field, sigma_cells)
    t = np.clip(np.where(np.isfinite(distance_m), distance_m, 0.0) / max(2.0 * sigma_cells * spacing_m, 1e-6), 0.0, 1.0)
    t = t * t * (3.0 - 2.0 * t)
    return field * (1.0 - t) + wide * t


def _fit_channel_beds(surface, land, *, spacing_x_m, spacing_y_m, inflow=None, route=None):
    """Carry never-rising river beds across their floodplain belts.

    Every level's change is made zero-mean at its parent's spacing, so
    parent-scale sills and pits along a river survive the conservation (and
    the conservation adds its own where it lifts a channel whose
    surroundings were lowered); a finer level then finds its river ponding
    or leaving the tile where it entered.  Rivers whose floodplain (twice
    its half-width) spans at least a cell get the exact bed of ``material_routing.monotone_channel_beds``
    (least squares, so each path keeps its bed volume) and their belt the
    same correction smoothed along the river; smaller streams and
    hillslopes are left alone.  ``route`` (``[H, W]``) routes the rivers on
    another surface than the one whose beds are fitted.
    """
    from simulations.world_gen.material_routing import channel_belts, gaussian_blur, inflow_grid

    belts = channel_belts(
        surface, land, dx=spacing_x_m, dy=spacing_y_m,
        inflow_cells=inflow_grid(surface.shape, inflow, spacing_x_m * spacing_y_m),
        monotone_beds=True, fit_min_half_width_m=0.5 * max(spacing_x_m, spacing_y_m), route_elevation=route,
    )
    spacing = max(spacing_x_m, spacing_y_m)
    correction = _floodplain_scale(
        gaussian_blur(belts["bed_elevation_m"] - belts["raw_bed_elevation_m"], 1.5),
        belts["distance_m"], _floodplain_sigma(belts, spacing), spacing,
    )
    fitted = surface + correction * np.clip(gaussian_blur(belts["belt"], 1.5), 0.0, 1.0)
    exact = belts["fitted_channel_bed_m"]
    return np.where(np.isfinite(exact), exact, fitted)


def _sea_mask(heightmap, parent_entity, sea_level):
    """Which cells below sea level belong to the sea: water joined to the parent's open sea (``None`` if unknown).

    Everything below sea level used to be sea to every layer.  A basin the
    land shuts in was drawn as sea, climate took it for ocean, and a river
    that reached it ended there with no lake to fill.
    """
    from simulations.world_gen import rock_scarps, sea_cliffs

    rows = ((heightmap or {}).get("sample_grid") or {}).get("rows") or []
    bounds = (heightmap or {}).get("source_uv_bounds")
    if not rows or not bounds or sea_level is None:
        return None
    width = min(len(row) for row in rows)
    elevation = np.asarray([row[:width] for row in rows], dtype=np.float64)
    u, v = rock_scarps._uv_grids(bounds, elevation.shape)
    return sea_cliffs.joined_sea(parent_entity, elevation < float(sea_level), u, v)


# Sand or delta sediment this thick is the surface, whatever lies under it.
LAID_GROUND_THICKNESS_M = 0.3


def _laid_ground(heightmap, shape):
    """0..1: how far a cell's surface is beach sand or delta sediment laid by this level or a coarser one.

    A beach, a shoreface and a delta plain are in balance with the sea or
    the lake they were built to, now.  Surface evolution lowers every cell
    by its erosion score and the parent's mean is then taken out, so flat
    ground, which scores low, comes out raised against the slopes round
    it: a delta floor by 24 m and again by 12 m on one Region tile, valley
    fills and berms by up to a metre at Local scale, and the beach rule
    then found its own shore changed.
    """
    from simulations.world_gen import river_deltas, shore_deposits

    held = np.zeros(shape)
    for grid in (
        shore_deposits.record_sand_m(shore_deposits.shore_record(heightmap)),
        river_deltas.record_sediment_m(river_deltas.delta_record(heightmap)),
    ):
        if grid is not None and grid.shape == tuple(shape):
            held = np.maximum(held, np.clip(grid / LAID_GROUND_THICKNESS_M, 0.0, 1.0))
    return held


def _under_ice(heightmap, shape):
    """Cells the heightmap's masks have under ice (bool)."""
    rows = ((heightmap or {}).get("surface_masks") or {}).get("ice_rows") or []
    if len(rows) != shape[0] or not rows or len(rows[0]) < shape[1]:
        return np.zeros(shape, dtype=bool)
    return np.asarray([row[:shape[1]] for row in rows], dtype=bool)


def _solver_cells(heightmap, water_cycle):
    """Heightmap cells to one cell of the water cycle's grid, the larger of the two directions."""
    grid = (heightmap or {}).get("sample_grid") or {}
    rows = ((water_cycle or {}).get("climate_grid") or {}).get("temperature_rows_k") or []
    if not rows or not rows[0] or not grid.get("rows"):
        return 1.0
    return max(1.0, len(grid["rows"][0]) / len(rows[0]), len(grid["rows"]) / len(rows))


def _edge_faded_evolution(before, evolved, *, sea_level=None, parent_spacing_m=0.0, solver_cells=1.0):
    """Surface-evolution change with the parent's mean kept, faded to nothing at the tile edge.

    Like every other child detail the change must vanish where the tile meets
    its parent and neighbours; unfaded, deposition at a river's inlet (the
    regional drainage does not see the catchment the river brings in) raised
    the edge cell by tens of metres and turned the river back out.

    With ``parent_spacing_m`` the mean of the change over a parent cell is
    taken out, for the land and for the sea bed each by itself.  Surface
    evolution scores weathering and erosion on every cell and lowers each by
    its score times an amplitude set by the tile's relief: on a humid tile
    all land went down by 2 to 4 m, at every level again.  The parent has
    its denudation in its heights already; what a child may add is the
    relief inside a parent cell (valleys against their divides).  Left in,
    the blanket drowned every shore lower than itself (97 % of the land
    under 2 m on one Local tile), and the parent-height contract then put
    the parent's certainly-land cells back a little above the sea: the
    rectangular shorelines and the flats behind them.

    Surface evolution works on the water cycle's grid, ``solver_cells``
    heightmap cells to one of its own (1.5 to 2), and its change comes back
    resampled: across a shoreline the land's lowering (metres to tens of
    metres) and the sea bed's (a fifth of it) are smeared into each other.
    With each side's mean taken out, the last land cells were left standing
    as a rim (+3 to +16 m on one Region tile) and the first sea cells sunk
    as a moat (-2 to -15 m), at every pass and every level: the trough
    along every shore.  Cells within the smear of the other side therefore
    take their own side's change from the cells behind them.
    """
    grid = evolved.get("sample_grid") or {}
    rows = grid.get("rows") or []
    old_rows = ((before or {}).get("sample_grid") or {}).get("rows") or []
    if not rows or not old_rows or len(rows) != len(old_rows) or len(rows[0]) != len(old_rows[0]):
        return evolved
    new = np.asarray(rows, dtype=np.float64)
    old = np.asarray(old_rows, dtype=np.float64)
    spacing_m = max(float((before or {}).get("sample_spacing_x_m") or 0.0), float((before or {}).get("sample_spacing_y_m") or 0.0))
    if parent_spacing_m > 0.0 and spacing_m > 0.0:
        from simulations.world_gen.material_routing import box_mean

        radius = max(1, int(round(parent_spacing_m / spacing_m * 0.5)))
        change = new - old
        land = old >= float(sea_level) if sea_level is not None else np.ones(old.shape, dtype=bool)
        unsupported = np.zeros(old.shape, dtype=bool)
        if land.any() and not land.all():
            from simulations.world_gen.shore_deposits import distance_cells

            smear = max(1.0, float(solver_cells or 1.0)) + 0.5
            reach = int(math.ceil(smear)) + 1
            own = change.copy()
            for side in (land, ~land):
                near = side & (distance_cells(~side, reach) <= smear)
                behind = side & ~near
                weight = box_mean(behind.astype(np.float64), reach)
                estimate = box_mean(np.where(behind, change, 0.0), reach) / np.maximum(weight, 1e-9)
                own = np.where(near & (weight > 0.0), estimate, own)
                # A strip too narrow to have cells behind it keeps its height.
                unsupported |= near & (weight <= 0.0)
            change = own
        mean = np.zeros(old.shape)
        for side in (land, ~land):
            if side.any():
                share = box_mean(side.astype(np.float64), radius)
                mean = np.where(side, box_mean(np.where(side, change, 0.0), radius) / np.maximum(share, 1e-9), mean)
        new = old + np.where(unsupported, 0.0, change - mean)
    # Ground the waves and the rivers have just laid is as they left it.
    new = old + (new - old) * (1.0 - _laid_ground(before, new.shape))
    height, width = new.shape
    local_u = np.arange(width) / max(1, width - 1)
    local_v = np.arange(height) / max(1, height - 1)
    edge = np.minimum(np.minimum(local_u, 1.0 - local_u)[None, :], np.minimum(local_v, 1.0 - local_v)[:, None])
    fade = np.clip(edge / PARENT_EDGE_FADE_FRACTION, 0.0, 1.0)
    fade = fade * fade * (3.0 - 2.0 * fade)
    digits = height_decimals((before or {}).get("sample_spacing_x_m"))
    change = (new - old) * fade
    # Running water wears ground down towards its outlet, never under it.
    # The solver lowers every cell by its own score, and a reach that
    # scores higher than the one below it came out as a pit: 54 new
    # hollows of 2 m or more, 7 km2, on one arid Region tile that had
    # none.  Ice does overdeepen its bed, so ground under ice is left.
    from simulations.world_gen.regional_landforms import hold_above_outlets

    held, _cells = hold_above_outlets(change, old, sea_level)
    change = np.where(_under_ice(before, old.shape), change, held)
    return {**evolved, "sample_grid": {**grid, "rows": np.round(old + change, digits).tolist()}}


def _fit_final_channel_beds(heightmap, *, sea_level, inflow, route_rows=None):
    """Last bed fit on the evolved surface (LOD1-3), faded at the tile edge.

    Surface evolution's erosion and deposition (its drainage does not see
    the catchment rivers bring in) fill parts of the channels the dissection
    fitted and can turn a river aside, so the surface a child inherits is
    fitted once more along the rivers of ``route_rows`` (the surface before
    evolution): the river keeps its course and deposition in its bed goes.
    """
    from simulations.world_gen.alluvial_channels import CHANNEL_PLANFORM_MIN_LEVEL

    grid = heightmap.get("sample_grid") or {}
    rows = grid.get("rows") or []
    level = int(heightmap.get("map_detail_level", 0) or 0)
    # From Site scale the channels are carved (alluvial_channels) with a bank
    # line that never rises; fitted again, their scour pools counted as pits
    # and were filled, with the correction fanned out around every bend.
    if not rows or not rows[0] or level < FLUVIAL_DISSECTION_MIN_LEVEL or level >= CHANNEL_PLANFORM_MIN_LEVEL:
        return heightmap
    elevation = np.asarray(rows, dtype=np.float64)
    height, width = elevation.shape
    land = elevation >= float(sea_level) if sea_level is not None else np.ones(elevation.shape, dtype=bool)
    if land.sum() < 64:
        return heightmap
    spacing_x_m = float(heightmap.get("region_width_m") or 0.0) / max(1, width - 1)
    spacing_y_m = float(heightmap.get("region_height_m") or 0.0) / max(1, height - 1)
    if spacing_x_m <= 0.0 or spacing_y_m <= 0.0:
        return heightmap
    route = None
    if route_rows is not None and np.shape(route_rows) == elevation.shape:
        route = np.asarray(route_rows, dtype=np.float64)
    fitted = _fit_channel_beds(elevation, land, spacing_x_m=spacing_x_m, spacing_y_m=spacing_y_m, inflow=inflow, route=route)
    local_u = np.arange(width) / max(1, width - 1)
    local_v = np.arange(height) / max(1, height - 1)
    edge = np.minimum(np.minimum(local_u, 1.0 - local_u)[None, :], np.minimum(local_v, 1.0 - local_v)[:, None])
    fade = np.clip(edge / PARENT_EDGE_FADE_FRACTION, 0.0, 1.0)
    fade = fade * fade * (3.0 - 2.0 * fade)
    result = elevation + (fitted - elevation) * fade
    if sea_level is not None:
        result = np.where(land, np.maximum(result, _land_floor(elevation, sea_level)), elevation)
    # A bed fitted never to rise downstream must not end in a pit where the
    # fit stops (the faded rim, the blend into its banks): 11 hollows up to
    # 10 m deep on an arid Region tile that had none going in.
    from simulations.world_gen.regional_landforms import hold_above_outlets

    change, _cells = hold_above_outlets(result - elevation, elevation, sea_level)
    result = elevation + change
    return {**heightmap, "sample_grid": {**grid, "rows": np.round(result, height_decimals(min(spacing_x_m, spacing_y_m))).tolist()}}


def _floodplain_flattening(rows, *, sea_level, spacing_x_m, spacing_y_m, parent_spacing_m, level, inflow=None):
    """Give local valleys flat floors (LOD3+).

    Rivers plane their valley floors laterally and fill them with sediment,
    so at local scale a valley is a flat floodplain beside a channel, not a
    V.  Along the channel belts of ``material_routing.channel_belts`` the
    ground is pulled to the bed elevation of the channel whose floodplain
    reaches it (blended at the parent's spacing) plus half a metre and a
    0.4 % rise away from the channel, weighted by belt cover (full at the
    channel, tapering to nothing at the belt edge).  Below Site scale channel
    cells sit half a metre under the surrounding floor; from LOD4 on,
    ``alluvial_channels`` carves the channels a cell resolves.  Like the
    dissection, the change is made zero-mean at the parent's spacing, fades
    at tile edges and keeps the coastline.  Last, river beds are fitted never
    to rise downstream (``_fit_channel_beds``).
    """
    from simulations.world_gen.fluvial_relief import conserve_parent_scale
    from simulations.world_gen.material_routing import channel_belts, gaussian_blur, inflow_grid

    if int(level) < FLOODPLAIN_MIN_LEVEL or not rows or not rows[0]:
        return rows, {"applied": False}
    elevation = np.asarray(rows, dtype=np.float64)
    land = elevation >= float(sea_level) if sea_level is not None else np.ones(elevation.shape, dtype=bool)
    if land.sum() < 64:
        return rows, {"applied": False}
    belts = channel_belts(
        elevation, land, dx=spacing_x_m, dy=spacing_y_m,
        inflow_cells=inflow_grid(elevation.shape, inflow, spacing_x_m * spacing_y_m),
        monotone_beds=True, fit_min_half_width_m=0.5 * max(spacing_x_m, spacing_y_m),
    )
    distance = np.where(np.isfinite(belts["distance_m"]), belts["distance_m"], 0.0)
    # Each cell takes the bed level of its nearest channel, which is
    # discontinuous where two channels' zones meet and, beside a wide river,
    # varies column by column with the river's cell-scale bed noise: straight
    # 45-degree seams and stripes.  A floodplain surface is continuous, so
    # the bed level is blended at the parent's spacing and the belt edge is
    # softened over a couple of cells.
    radius = max(1, int(round(parent_spacing_m / max(spacing_x_m, spacing_y_m, 1e-6) * 0.5)))
    bed = gaussian_blur(belts["bed_elevation_m"], max(1.5, float(radius)))
    weight = np.clip(gaussian_blur(belts["belt"], 1.5), 0.0, 1.0)
    # Beside the channel the floor follows its bed; farther out it is one
    # surface smoothed at floodplain scale (``_floodplain_scale``), rising
    # 0.4 % towards the valley sides.
    spacing = max(spacing_x_m, spacing_y_m, 1e-6)
    rise_sigma = _floodplain_sigma(belts, spacing)
    floor = _floodplain_scale(bed + 0.5 + 0.004 * gaussian_blur(distance, rise_sigma), belts["distance_m"], rise_sigma, spacing)
    from simulations.world_gen.alluvial_channels import CHANNEL_PLANFORM_MIN_LEVEL

    if int(level) < CHANNEL_PLANFORM_MIN_LEVEL:
        # Channels sit half a metre below the floodplain around them (the
        # dominant river's own cells: at its bed).  A tributary crossing a
        # big river's floodplain follows that surface rather than keeping
        # its old level or dropping to the river's.
        floor = np.where(belts["channel"], floor - 0.5, floor)
    # From Site scale on, channels a cell resolves are carved with their own
    # sections (alluvial_channels); narrower ones are sub-cell and must not
    # become a full-cell trench along a straight D8 path.
    flattened = elevation + (floor - elevation) * weight
    restored = _fit_channel_beds(
        conserve_parent_scale(elevation, flattened, land, radius), land,
        spacing_x_m=spacing_x_m, spacing_y_m=spacing_y_m, inflow=inflow,
    )
    height, width = elevation.shape
    local_u = np.arange(width) / max(1, width - 1)
    local_v = np.arange(height) / max(1, height - 1)
    edge = np.minimum(np.minimum(local_u, 1.0 - local_u)[None, :], np.minimum(local_v, 1.0 - local_v)[:, None])
    fade = np.clip(edge / PARENT_EDGE_FADE_FRACTION, 0.0, 1.0)
    fade = fade * fade * (3.0 - 2.0 * fade)
    result = elevation + (restored - elevation) * fade
    if sea_level is not None:
        result = np.where(land, np.maximum(result, _land_floor(elevation, sea_level)), elevation)
    return np.round(result, height_decimals(min(spacing_x_m, spacing_y_m))).tolist(), {
        "applied": True,
        "model": "channel_belt_floodplains_v1",
        "channel_cell_fraction": round(float(belts["channel"][land].mean()), 4),
        "floodplain_cell_fraction": round(float((belts["belt"] > 0)[land].mean()), 4),
        "max_half_width_m": round(float(belts["half_width_m"].max()), 1),
    }


def _scale_appropriate_relief(rows, sea_level, width_m, height_m, coastal_context):
    """Bound inherited relief by footprint and the parent coastal system."""
    if not rows or not rows[0]:
        return rows, {"applied": False}
    morphology = str(
        coastal_context.get("coastal_system")
        or coastal_context.get("morphology_assemblage")
        or ""
    )
    maximum_relief_ratio = {
        "deltaic": 0.12,
        "tidal_flat_accommodation": 0.055,
        "clastic_beach": 0.24,
        "barrier_lagoon": 0.18,
        "estuarine_drowned_valley": 0.34,
        "rocky_cliff": 0.38,
        "headland_bay": 0.55,
        "glacial_fjord_fjard_skerry": 1.35,
        "emergent_marine_terrace": 0.50,
    }.get(morphology, 1.25)
    minimum_range_m = 0.20 if morphology in {"deltaic", "tidal_flat_accommodation"} else 0.50
    maximum_range_m = max(minimum_range_m, min(width_m, height_m) * maximum_relief_ratio)
    minimum = min(min(row) for row in rows)
    maximum = max(max(row) for row in rows)
    original_range = max(0.0, maximum - minimum)
    if original_range <= maximum_range_m or original_range <= 1e-9:
        return rows, {
            "applied": False,
            "coastal_system": morphology or None,
            "maximum_relief_ratio": maximum_relief_ratio,
            "original_range_m": round(original_range, 4),
            "resolved_range_m": round(original_range, 4),
        }
    datum = float(sea_level) if sea_level is not None else (minimum + maximum) * 0.5
    scale = maximum_range_m / original_range
    limited = [[datum + (float(value) - datum) * scale for value in row] for row in rows]
    return limited, {
        "applied": True,
        "coastal_system": morphology or None,
        "maximum_relief_ratio": maximum_relief_ratio,
        "original_range_m": round(original_range, 4),
        "resolved_range_m": round(maximum_range_m, 4),
        "scale_factor": round(scale, 8),
        "datum": "inherited_sea_level" if sea_level is not None else "midrange",
    }


def _limit_heightmap_relief(heightmap, coastal_context):
    grid = heightmap.get("sample_grid") or {}
    rows = grid.get("rows") or []
    limited, audit = _scale_appropriate_relief(
        rows,
        heightmap.get("sea_level_m"),
        float(heightmap.get("region_width_m") or 0.0),
        float(heightmap.get("region_height_m") or 0.0),
        coastal_context,
    )
    if audit.get("applied"):
        heightmap = dict(heightmap)
        digits = max(3, height_decimals(heightmap.get("sample_spacing_x_m")))
        heightmap["sample_grid"] = {**grid, "rows": [[round(value, digits) for value in row] for row in limited]}
        heightmap["min_elevation_m"] = round(min(min(row) for row in limited), 3)
        heightmap["max_elevation_m"] = round(max(max(row) for row in limited), 3)
    heightmap["scale_appropriate_relief"] = audit
    return heightmap


def clamp_refinement_bounds(parent_entity, bounds):
    """Expand a requested footprint when necessary so neither side is below 10 m."""
    parent_bounds = parent_entity.get("bounds") or {}
    if parent_bounds.get("type") != "bbox":
        return dict(bounds)
    parent_world_width = max(1e-12, float(parent_bounds["max_x"]) - float(parent_bounds["min_x"]))
    parent_world_height = max(1e-12, float(parent_bounds["max_y"]) - float(parent_bounds["min_y"]))
    parent_width_m, parent_height_m = map_physical_dimensions_m(parent_entity)
    requested_width = max(0.0, float(bounds["max_x"]) - float(bounds["min_x"]))
    requested_height = max(0.0, float(bounds["max_y"]) - float(bounds["min_y"]))
    minimum_width = parent_world_width if parent_width_m <= 0.0 else parent_world_width * min(1.0, MIN_REFINED_EXTENT_M / parent_width_m)
    minimum_height = parent_world_height if parent_height_m <= 0.0 else parent_world_height * min(1.0, MIN_REFINED_EXTENT_M / parent_height_m)
    width = min(parent_world_width, max(requested_width, minimum_width))
    height = min(parent_world_height, max(requested_height, minimum_height))
    center_x = (float(bounds["min_x"]) + float(bounds["max_x"])) * 0.5
    center_y = (float(bounds["min_y"]) + float(bounds["max_y"])) * 0.5
    min_x = max(float(parent_bounds["min_x"]), min(float(parent_bounds["max_x"]) - width, center_x - width * 0.5))
    min_y = max(float(parent_bounds["min_y"]), min(float(parent_bounds["max_y"]) - height, center_y - height * 0.5))
    return {"min_x": min_x, "max_x": min_x + width, "min_y": min_y, "max_y": min_y + height}


def _sample_bilinear(rows, u, v, *, wrap_x=True):
    height, width = len(rows), len(rows[0])
    normalized_u = float(u) % 1.0 if wrap_x else _clamp(u, 0.0, 1.0)
    px = normalized_u * max(1, width - 1)
    py = _clamp(v, 0.0, 1.0) * max(1, height - 1)
    x0, y0 = int(math.floor(px)), int(math.floor(py))
    x1 = (x0 + 1) % width if wrap_x else min(width - 1, x0 + 1)
    y1 = min(height - 1, y0 + 1)
    tx, ty = px - x0, py - y0
    top = float(rows[y0][x0]) * (1.0 - tx) + float(rows[y0][x1]) * tx
    bottom = float(rows[y1][x0]) * (1.0 - tx) + float(rows[y1][x1]) * tx
    return top * (1.0 - ty) + bottom * ty


def _sample_bicubic(rows, u, v, *, wrap_x=True):
    """Smoothly inherit relief without exposing the parent sample lattice.

    A separable cubic B-spline is C2-continuous across cell boundaries.  That
    matters because hillshade and geomorphology inspect first and second
    derivatives: Catmull-Rom removed value seams but still revealed its source
    lattice in curvature.  B-splines reproduce planar trends while applying a
    small, physically appropriate reconstruction filter to unresolved relief.
    """
    height, width = len(rows), len(rows[0])
    if height < 4 or width < 4:
        return _sample_bilinear(rows, u, v, wrap_x=wrap_x)
    normalized_u = float(u) % 1.0 if wrap_x else _clamp(u, 0.0, 1.0)
    px = normalized_u * max(1, width - 1)
    py = _clamp(v, 0.0, 1.0) * max(1, height - 1)
    x1, y1 = int(math.floor(px)), int(math.floor(py))
    tx, ty = px - x1, py - y1

    def x_index(value):
        return value % width if wrap_x else max(0, min(width - 1, value))

    def spline(p0, p1, p2, p3, t):
        t2, t3 = t * t, t * t * t
        w0 = (1.0 - 3.0 * t + 3.0 * t2 - t3) / 6.0
        w1 = (4.0 - 6.0 * t2 + 3.0 * t3) / 6.0
        w2 = (1.0 + 3.0 * t + 3.0 * t2 - 3.0 * t3) / 6.0
        w3 = t3 / 6.0
        return p0 * w0 + p1 * w1 + p2 * w2 + p3 * w3

    support = []
    row_values = []
    for source_y in range(y1 - 1, y1 + 3):
        yy = max(0, min(height - 1, source_y))
        values = [float(rows[yy][x_index(xx)]) for xx in range(x1 - 1, x1 + 3)]
        support.extend(values)
        row_values.append(spline(*values, tx))
    value = spline(*row_values, ty)
    return _clamp(value, min(support), max(support))


def _sample_bilinear_grid(values, u, v, *, wrap_x=True):
    """Array form of ``_sample_bilinear`` for broadcast ``u``/``v`` arrays."""
    height, width = values.shape
    normalized_u = np.mod(u, 1.0) if wrap_x else np.clip(u, 0.0, 1.0)
    px = normalized_u * max(1, width - 1)
    py = np.clip(v, 0.0, 1.0) * max(1, height - 1)
    x0 = np.floor(px).astype(np.int64)
    y0 = np.floor(py).astype(np.int64)
    x1 = (x0 + 1) % width if wrap_x else np.minimum(width - 1, x0 + 1)
    y1 = np.minimum(height - 1, y0 + 1)
    tx = px - x0
    ty = py - y0
    x0, y0 = np.broadcast_arrays(x0, y0)
    x1, y1 = np.broadcast_arrays(x1, y1)
    top = values[y0, x0] * (1.0 - tx) + values[y0, x1] * tx
    bottom = values[y1, x0] * (1.0 - tx) + values[y1, x1] * tx
    return top * (1.0 - ty) + bottom * ty


def _sample_bicubic_grid(values, u, v, *, wrap_x=True):
    """Array form of ``_sample_bicubic`` (same B-spline and support clamp)."""
    height, width = values.shape
    if height < 4 or width < 4:
        return _sample_bilinear_grid(values, u, v, wrap_x=wrap_x)
    normalized_u = np.mod(u, 1.0) if wrap_x else np.clip(u, 0.0, 1.0)
    px = normalized_u * max(1, width - 1)
    py = np.clip(v, 0.0, 1.0) * max(1, height - 1)
    x1 = np.floor(px).astype(np.int64)
    y1 = np.floor(py).astype(np.int64)
    tx = px - x1
    ty = py - y1

    def weights(t):
        t2 = t * t
        t3 = t2 * t
        return (
            (1.0 - 3.0 * t + 3.0 * t2 - t3) / 6.0,
            (4.0 - 6.0 * t2 + 3.0 * t3) / 6.0,
            (1.0 + 3.0 * t + 3.0 * t2 - 3.0 * t3) / 6.0,
            t3 / 6.0,
        )

    wx = weights(tx)
    wy = weights(ty)
    value = 0.0
    support_min = None
    support_max = None
    for row_offset in range(4):
        yy = np.clip(y1 + row_offset - 1, 0, height - 1)
        row_value = 0.0
        for column_offset in range(4):
            xx = x1 + column_offset - 1
            xx = xx % width if wrap_x else np.clip(xx, 0, width - 1)
            yy_b, xx_b = np.broadcast_arrays(yy, xx)
            sample = values[yy_b, xx_b]
            row_value = row_value + sample * wx[column_offset]
            support_min = sample if support_min is None else np.minimum(support_min, sample)
            support_max = sample if support_max is None else np.maximum(support_max, sample)
        value = value + row_value * wy[row_offset]
    return np.clip(value, support_min, support_max)


# The whole-grid relief synthesis below reproduces the per-cell loop in
# ``generate_refined_region``; the loop remains for crater-free fallbacks
# without a production residual grid and for parity checks.
VECTORISED_REGIONAL_RELIEF = True


def _parent_topology_certainty_grid(values, u, v, sea_level, *, wrap_x=True):
    """Array form of ``_parent_topology_certainty`` (-1 ocean, +1 land, 0 coast)."""
    shape = np.broadcast_shapes(np.shape(u), np.shape(v))
    if sea_level is None:
        return np.zeros(shape, dtype=np.int64)
    height, width = values.shape
    normalized_u = np.mod(u, 1.0) if wrap_x else np.clip(u, 0.0, 1.0)
    px = normalized_u * max(1, width - 1)
    py = np.clip(v, 0.0, 1.0) * max(1, height - 1)
    x0 = np.floor(px).astype(np.int64)
    y0 = np.floor(py).astype(np.int64)
    x1 = (x0 + 1) % width if wrap_x else np.minimum(width - 1, x0 + 1)
    y1 = np.minimum(height - 1, y0 + 1)
    land = values >= float(sea_level)
    corners = [
        land[np.broadcast_arrays(yy, xx)]
        for xx, yy in ((x0, y0), (x1, y0), (x0, y1), (x1, y1))
    ]
    all_land = corners[0] & corners[1] & corners[2] & corners[3]
    all_ocean = ~(corners[0] | corners[1] | corners[2] | corners[3])
    return np.where(all_land, 1, np.where(all_ocean, -1, 0)).astype(np.int64)


def _parent_structure_context_grid(values, u, v, relief_span, *, wrap_x=True):
    """Array form of ``_parent_structure_context``."""
    height, width = values.shape
    du = 1.0 / max(1, width - 1)
    dv = 1.0 / max(1, height - 1)
    center = _sample_bicubic_grid(values, u, v, wrap_x=wrap_x)
    west = _sample_bicubic_grid(values, u - du, v, wrap_x=wrap_x)
    east = _sample_bicubic_grid(values, u + du, v, wrap_x=wrap_x)
    north = _sample_bicubic_grid(values, u, v - dv, wrap_x=wrap_x)
    south = _sample_bicubic_grid(values, u, v + dv, wrap_x=wrap_x)
    high = np.maximum.reduce([center, west, east, north, south])
    low = np.minimum.reduce([center, west, east, north, south])
    local_range = high - low
    ruggedness = np.clip(local_range / max(1.0, float(relief_span) * 0.02), 0.0, 1.0)
    neighbour_mean = (west + east + north + south) * 0.25
    curvature_fraction = np.abs(center - neighbour_mean) / np.maximum(0.25, local_range)
    anchor = np.sqrt(np.clip((curvature_fraction - 0.055) / 0.30, 0.0, 1.0))
    return ruggedness, anchor


def _sample_orogen_structural_grid_arrays(grid, global_u, global_v, shape):
    keys = (
        "mountain_influence", "core_influence", "arc_influence", "shoulder_influence",
        "forearc_influence", "trench_influence", "mountain_belt_envelope",
        "mountain_belt_cross_range", "mountain_belt_axis_x", "mountain_belt_axis_y",
    )
    if not isinstance(grid, dict):
        return {key: np.zeros(shape, dtype=np.float64) for key in keys}
    bounds = grid.get("source_uv_bounds") or {}
    u0, u1 = float(bounds.get("min_u", 0.0)), float(bounds.get("max_u", 1.0))
    v0, v1 = float(bounds.get("min_v", 0.0)), float(bounds.get("max_v", 1.0))
    u = np.clip((global_u - u0) / max(1e-12, u1 - u0), 0.0, 1.0)
    v = np.clip((global_v - v0) / max(1e-12, v1 - v0), 0.0, 1.0)
    return _axis_from_doubled_angle({
        key: np.broadcast_to(
            _sample_bilinear_grid(np.asarray(rows, dtype=np.float64), u, v, wrap_x=False), shape,
        )
        for key, rows in (grid.get("channels") or {}).items()
    })


def _synthesize_regional_relief_arrays(
    *,
    parent_rows,
    parent_heightmap,
    parent_mountain_rows,
    parent_wrap_x,
    production_residual_grid,
    orogen_structural_grid,
    sample_width,
    sample_height,
    u0, u1, v0, v1,
    source_u0, source_u1, source_v0, source_v1,
    sea_level,
    relief_span,
    amplitude,
    level,
    detail_band,
    root_surface_seed,
    planet_circumference,
    broad_wavelength_m,
    fine_wavelength_m,
    fold_wavelength_m,
    ridge_phase,
    crater_detail,
    tile_frame=None,
    height_digits=2,
):
    """Whole-grid relief synthesis; numerically the per-cell loop's body.

    ``crater_detail(y, x, source_u, source_v, local_u, local_v, global_u,
    global_v)`` returns the (rare) crater height adjustment for a cell, or is
    None when no crater model applies.
    """
    from simulations.world_gen.geological_noise import (
        branching_mountain_relief_grid,
        fractal_noise_grid,
    )

    shape = (sample_height, sample_width)
    local_u = (np.arange(sample_width, dtype=np.float64) / max(1, sample_width - 1))[None, :]
    local_v = (np.arange(sample_height, dtype=np.float64) / max(1, sample_height - 1))[:, None]
    source_u = u0 + (u1 - u0) * local_u
    source_v = v0 + (v1 - v0) * local_v
    global_u = source_u0 + (source_u1 - source_u0) * local_u
    global_v = source_v0 + (source_v1 - source_v0) * local_v
    parent_width = min(len(row) for row in parent_rows)
    parent_values = np.asarray([row[:parent_width] for row in parent_rows], dtype=np.float64)
    inherited_wrap = bool(parent_heightmap.get("wrap_x", True))
    inherited = np.broadcast_to(_sample_bicubic_grid(parent_values, source_u, source_v, wrap_x=inherited_wrap), shape)
    topology = np.broadcast_to(_parent_topology_certainty_grid(parent_values, source_u, source_v, sea_level, wrap_x=inherited_wrap), shape)
    residual = np.broadcast_to(_sample_bicubic_grid(
        np.asarray(production_residual_grid["residual_rows"], dtype=np.float64),
        local_u, local_v, wrap_x=False,
    ), shape)
    production_height = inherited + residual
    world_x_m = np.broadcast_to(global_u * planet_circumference, shape)
    world_y_m = np.broadcast_to(global_v * planet_circumference * 0.5, shape)
    if detail_band:
        broad = fractal_noise_grid(
            root_surface_seed, "regional-broad-relief", world_x_m, world_y_m,
            broad_wavelength_m, octaves=2, gain=0.50, period_x_m=planet_circumference,
        )
        fine = fractal_noise_grid(
            root_surface_seed, "regional-fine-relief", world_x_m, world_y_m,
            fine_wavelength_m, octaves=2, gain=0.44, period_x_m=planet_circumference,
        )
    else:
        broad = fine = np.zeros(shape)
    if parent_mountain_rows:
        mountain_width = min(len(row) for row in parent_mountain_rows)
        mountain_values = np.asarray([row[:mountain_width] for row in parent_mountain_rows], dtype=np.float64)
        mountain_factor = np.clip(_sample_bicubic_grid(mountain_values, source_u, source_v, wrap_x=parent_wrap_x), 0.0, 1.0)
    else:
        mountain_factor = np.zeros(shape)
    if parent_rows and parent_rows[0]:
        ruggedness, anchor = _parent_structure_context_grid(parent_values, source_u, source_v, relief_span, wrap_x=parent_wrap_x)
    else:
        ruggedness = anchor = np.zeros(shape)
    orogen = _sample_orogen_structural_grid_arrays(orogen_structural_grid, global_u, global_v, shape)

    def channel(key):
        return orogen.get(key, np.zeros(shape))

    orogen_factor = np.array(orogen["mountain_influence"], dtype=np.float64)
    envelope = np.clip(channel("mountain_belt_envelope"), 0.0, 1.0)
    if sea_level is not None:
        land_gate = np.clip((inherited - float(sea_level)) / max(1.0, relief_span * 0.08), 0.0, 1.0)
        orogen_factor = np.where(inherited <= float(sea_level), 0.0, orogen_factor * (0.30 + 0.70 * land_gate))
    structural_factor = np.maximum(
        mountain_factor * ruggedness * anchor * (0.30 + 0.70 * envelope),
        orogen_factor * (0.34 + 0.66 * ruggedness) * (0.48 + 0.52 * anchor) * (0.28 + 0.72 * envelope),
    )
    belt_uplift = amplitude * structural_factor * envelope * (0.28 if level == 1 else 0.10)
    fold_relief = (
        branching_mountain_relief_grid(
            root_surface_seed, "regional-branching-mountains", world_x_m, world_y_m,
            fold_wavelength_m, period_x_m=planet_circumference,
        )
        if detail_band else np.zeros(shape)
    )
    ridge_valley_signal = np.zeros(shape)
    active = envelope > 0.08
    if detail_band and active.any():
        wavelength = max(1.0, float(fold_wavelength_m))
        x = world_x_m[active]
        y = world_y_m[active]
        if tile_frame is not None:
            (axis_x, axis_y), (origin_x, origin_y) = tile_frame
        else:
            origin_x = origin_y = 0.0
            axis_x = channel("mountain_belt_axis_x")[active]
            axis_y = channel("mountain_belt_axis_y")[active]
            axis_length = np.hypot(axis_x, axis_y)
            degenerate = axis_length < 1e-6
            axis_x = np.where(degenerate, 1.0, axis_x / np.where(degenerate, 1.0, axis_length))
            axis_y = np.where(degenerate, 0.0, axis_y / np.where(degenerate, 1.0, axis_length))
        along_m = (x - origin_x) * axis_x + (y - origin_y) * axis_y
        across_m = -(x - origin_x) * axis_y + (y - origin_y) * axis_x
        cross_warp = fractal_noise_grid(
            root_surface_seed, "regional-ridge-cross-warp", x, y, wavelength * 2.8,
            octaves=2, gain=0.52, period_x_m=planet_circumference,
        )
        along_warp = fractal_noise_grid(
            root_surface_seed, "regional-ridge-along-warp", x, y, wavelength * 3.6,
            octaves=3, gain=0.48, period_x_m=planet_circumference,
        )
        anchored_phase = (
            math.tau * (channel("mountain_belt_cross_range")[active] * 0.34 + cross_warp * 0.18)
            + ridge_phase
            + along_warp * 1.15
        )
        branching = branching_mountain_relief_grid(
            root_surface_seed, "regional-boundary-branching-ridges", along_m, across_m,
            wavelength * 0.92, period_x_m=planet_circumference,
        )
        ridge_valley_signal[active] = np.clip(
            np.sin(anchored_phase) * 0.28
            + np.sin(anchored_phase * 1.83 + along_warp * 2.4) * 0.14
            + branching * 0.58,
            -1.0,
            1.0,
        )
    ridge_valley_amplitude = np.clip(
        0.18
        + channel("core_influence") * 0.28
        + channel("arc_influence") * 0.18
        + channel("shoulder_influence") * 0.08
        - channel("forearc_influence") * 0.10,
        0.08,
        0.52,
    )
    detail = (
        broad * amplitude * (0.06 + structural_factor * 0.07)
        + fine * amplitude * (0.035 + structural_factor * 0.05)
        + belt_uplift
        + fold_relief * amplitude * structural_factor * (0.30 + channel("core_influence") * 0.10)
        + ridge_valley_signal * amplitude * structural_factor * ridge_valley_amplitude
    )
    detail = detail + residual
    if sea_level is not None and level >= 4:
        detail = np.where(inherited < float(sea_level), detail * 0.22, detail)
    if crater_detail is not None:
        detail = np.array(detail)
        for y in range(sample_height):
            for x in range(sample_width):
                detail[y, x] += crater_detail(
                    float(source_u[0, x]), float(source_v[y, 0]),
                    float(local_u[0, x]), float(local_v[y, 0]),
                    float(global_u[0, x]), float(global_v[y, 0]),
                )
    edge_distance = np.minimum(np.minimum(local_u, 1.0 - local_u), np.minimum(local_v, 1.0 - local_v))
    edge_fade = np.clip(edge_distance / PARENT_EDGE_FADE_FRACTION, 0.0, 1.0)
    edge_fade = edge_fade * edge_fade * (3.0 - 2.0 * edge_fade)
    detail = detail * edge_fade
    profile_keys = ("core_influence", "arc_influence", "shoulder_influence", "forearc_influence")
    return {
        "rows": np.round(inherited + detail, height_digits).tolist(),
        "inherited_rows": inherited.tolist(),
        "topology_rows": topology.tolist(),
        "production_height_min": float(production_height.min()),
        "production_height_max": float(production_height.max()),
        "production_height_sum": float(production_height.sum()),
        "production_height_count": int(production_height.size),
        "production_residual_min": float(residual.min()),
        "production_residual_max": float(residual.max()),
        "production_residual_sum": float(residual.sum()),
        "mountain_belt_envelope_sum": float(envelope.sum()),
        "mountain_belt_envelope_max": float(envelope.max()),
        "orogen_influence_sum": float(orogen_factor.sum()),
        "orogen_influence_max": float(orogen_factor.max()),
        "orogen_localized_cell_count": int((orogen_factor >= 0.18).sum()),
        "orogen_profile_sums": {key: float(channel(key).sum()) for key in profile_keys},
    }


def _refinement_detail_band(
    parent_width_m,
    parent_height_m,
    parent_rows,
    child_width_m,
    child_height_m,
    child_width_px,
    child_height_px,
):
    """Return the one physical wavelength band missing from the parent.

    Refinement previously chose wavelengths as a fraction of every selected
    rectangle. Repeating the same recipe at 22 km, 2 km and 222 m therefore
    invented a new full mountain range at every zoom. A child may only add
    wavelengths below its parent's resolved support and above its own sample
    floor; all broader ridges and valleys come from interpolation of the
    parent truth.
    """
    if not parent_rows or not parent_rows[0]:
        return None
    parent_x_spacing = max(0.01, float(parent_width_m) / max(1, len(parent_rows[0]) - 1))
    parent_y_spacing = max(0.01, float(parent_height_m) / max(1, len(parent_rows) - 1))
    child_x_spacing = max(0.01, float(child_width_m) / max(1, int(child_width_px) - 1))
    child_y_spacing = max(0.01, float(child_height_m) / max(1, int(child_height_px) - 1))
    parent_support = max(parent_x_spacing, parent_y_spacing)
    child_support = max(child_x_spacing, child_y_spacing)
    shortest = max(MIN_TERRAIN_PROCESS_WAVELENGTH_M, child_support * 4.0)
    longest = max(MIN_TERRAIN_PROCESS_WAVELENGTH_M, parent_support * 1.80)
    if shortest >= longest * 0.94:
        return None
    return {
        "shortest_wavelength_m": shortest,
        "longest_wavelength_m": longest,
        "broad_wavelength_m": longest,
        "fold_wavelength_m": max(shortest, longest * 0.68),
        "fine_wavelength_m": max(shortest, longest * 0.42),
        "parent_sample_spacing_m": parent_support,
        "child_sample_spacing_m": child_support,
    }


def _parent_structure_context(rows, u, v, relief_span, *, wrap_x=True):
    """Measure inherited ruggedness and ridge/valley anchoring.

    Ruggedness alone is not enough: a broad mountain mask stays non-zero over
    whole ranges and used to authorize a new branching ridge field at every
    refinement level.  The curvature term localizes new wavelengths to an
    actual inherited crest, hollow, or valley while linear slopes remain
    essentially untouched.
    """
    if not rows or not rows[0]:
        return 0.0, 0.0
    du = 1.0 / max(1, len(rows[0]) - 1)
    dv = 1.0 / max(1, len(rows) - 1)
    center = _sample_bicubic(rows, u, v, wrap_x=wrap_x)
    west = _sample_bicubic(rows, u - du, v, wrap_x=wrap_x)
    east = _sample_bicubic(rows, u + du, v, wrap_x=wrap_x)
    north = _sample_bicubic(rows, u, v - dv, wrap_x=wrap_x)
    south = _sample_bicubic(rows, u, v + dv, wrap_x=wrap_x)
    samples = [center, west, east, north, south]
    local_range = max(samples) - min(samples)
    # A local range of roughly two percent of the parent's total relief is
    # already a strong structural signal at the next detail level.
    ruggedness = _clamp(local_range / max(1.0, float(relief_span) * 0.02), 0.0, 1.0)
    neighbour_mean = (west + east + north + south) * 0.25
    curvature_fraction = abs(center - neighbour_mean) / max(0.25, local_range)
    anchor = _clamp((curvature_fraction - 0.055) / 0.30, 0.0, 1.0)
    # A square root gives inherited structures a modest shoulder without
    # spreading the authorization across the whole mountain province.
    anchor = math.sqrt(anchor)
    return ruggedness, anchor


def _parent_local_relief_fraction(rows, u, v, relief_span, *, wrap_x=True):
    """Compatibility wrapper returning only inherited ruggedness."""
    return _parent_structure_context(
        rows, u, v, relief_span, wrap_x=wrap_x,
    )[0]


def _orogen_structural_context(nx, ny, tectonic_model):
    """Resolve the production orogen field used to authorize child relief.

    The root heightfield already evaluates plate-boundary forcing, but the
    old refinement path reduced that causal signal to the root mountain mask.
    That mask is intentionally conservative at planetary resolution and can
    be nearly empty over a broad, elevated mountain province. Refinement
    therefore needs the production orogen response itself to carry connected
    ridge systems into the child. This function only returns a normalized
    structural gate; it does not replace the inherited parent elevation.
    """
    empty = {
        "mountain_influence": 0.0,
        "core_influence": 0.0,
        "arc_influence": 0.0,
        "shoulder_influence": 0.0,
        "forearc_influence": 0.0,
        "trench_influence": 0.0,
        "rock_uplift_m": 0.0,
        "volcanic_construction_m": 0.0,
        "cumulative_strain_index": 0.0,
    }
    if not isinstance(tectonic_model, dict):
        return empty
    response = _orogen_forcing_at(float(nx) % 1.0, _clamp(ny, 0.0, 1.0), tectonic_model)
    convergent = _clamp(
        float(response.get("convergent_influence", 0.0) or 0.0) / 2.0,
        0.0,
        1.0,
    )
    uplift = _clamp(
        float(response.get("rock_uplift_m", 0.0) or 0.0) / 1800.0,
        0.0,
        1.0,
    )
    volcanic = _clamp(
        float(response.get("volcanic_construction_m", 0.0) or 0.0) / 2400.0,
        0.0,
        1.0,
    )
    transform = _clamp(
        float(response.get("transform_influence", 0.0) or 0.0) / 1.15,
        0.0,
        1.0,
    )
    # Convergence is the primary mountain-forming gate. Uplift and volcanic
    # construction preserve arcs and collision shoulders, while transform
    # forcing contributes only a restrained amount of local relief.
    forearc = _clamp(
        float(response.get("trench_influence", 0.0) or 0.0) / 1.25,
        0.0,
        1.0,
    )
    # Resolve the broad production response into a cross-range profile. A
    # whole 100 km child can sit inside a 1000+ km tectonic envelope, so a
    # saturated boolean mountain gate loses the distinction between the
    # uplift core, volcanic arc, foothill shoulder, and forearc.
    core = uplift * (0.78 + 0.22 * (1.0 - forearc))
    arc = volcanic * (1.0 - 0.36 * forearc)
    shoulder = _clamp(uplift * (0.52 + 0.38 * forearc), 0.0, 1.0)
    mountain_influence = _clamp(
        core * 0.52
        + arc * 0.28
        + shoulder * 0.12
        + convergent * 0.10
        + transform * 0.025,
        0.0,
        1.0,
    )
    return {
        "mountain_influence": mountain_influence,
        "core_influence": _clamp(core, 0.0, 1.0),
        "arc_influence": _clamp(arc, 0.0, 1.0),
        "shoulder_influence": _clamp(shoulder, 0.0, 1.0),
        "forearc_influence": forearc,
        "trench_influence": forearc,
        "rock_uplift_m": max(0.0, float(response.get("rock_uplift_m", 0.0) or 0.0)),
        "volcanic_construction_m": max(
            0.0,
            float(response.get("volcanic_construction_m", 0.0) or 0.0),
        ),
        "cumulative_strain_index": max(
            0.0,
            float(response.get("cumulative_strain_index", 0.0) or 0.0),
        ),
    }


def _orogen_belt_context(nx, ny, tectonic_model):
    """Resolve the dominant inherited mountain-belt geometry at one point.

    The scalar orogen response is a useful tectonic gate, but it is too broad
    to determine the shape of a regional heightmap.  This compact companion
    field retains the nearest active boundary's cross-range position and
    mechanism so refinement can place relief in a coherent belt instead of
    painting the whole selected rectangle with unrelated ridges.
    """
    if not isinstance(tectonic_model, dict):
        return {"mountain_belt_envelope": 0.0}
    if not isinstance(tectonic_model.get("_heightmap_boundary_spatial_index"), dict):
        tectonic_model = _ensure_heightmap_tectonic_model(tectonic_model)
    systems = tectonic_model.get("_heightmap_orogen_system_lookup")
    if not isinstance(systems, dict):
        systems = {
            str(system.get("id")): system
            for system in ((tectonic_model.get("orogen_system_model") or {}).get("systems") or [])
            if isinstance(system, dict) and system.get("id")
        }
    best = None
    for segment in _nearby_boundary_segments(tectonic_model, nx, ny):
        if not isinstance(segment, dict):
            continue
        system = systems.get(str(segment.get("orogen_system_id") or ""))
        if not isinstance(system, dict):
            continue
        x1 = float(segment.get("x1", 0.0) or 0.0)
        x2 = float(segment.get("x2", 0.0) or 0.0)
        y1 = float(segment.get("y1", 0.5) or 0.5)
        y2 = float(segment.get("y2", 0.5) or 0.5)
        width = _clamp(segment.get("influence_width", 0.028), 0.012, 0.05)
        distance = _wrapped_point_segment_distance(nx, ny, x1, y1, x2, y2)
        if distance > width * 3.2:
            continue
        score = math.exp(-((distance / width) ** 2)) * _clamp(
            segment.get("activity_scale", 1.0), 0.25, 1.35,
        )
        if best is not None and score <= best["score"]:
            continue
        midpoint_x = (x1 + ((x2 - x1 + 0.5) % 1.0 - 0.5) * 0.5) % 1.0
        midpoint_y = (y1 + y2) * 0.5
        normal_x = float(segment.get("normal_x", 0.0) or 0.0)
        normal_y = float(segment.get("normal_y", 0.0) or 0.0)
        signed_distance = (
            ((float(nx) - midpoint_x + 0.5) % 1.0 - 0.5) * normal_x
            + (float(ny) - midpoint_y) * normal_y
        ) / max(1e-6, width)
        tangent_x = ((x2 - x1 + 0.5) % 1.0 - 0.5)
        tangent_y = y2 - y1
        tangent_length = max(1e-6, math.hypot(tangent_x, tangent_y))
        mechanism = str(system.get("mechanism") or "")
        sides = system.get("sides") if isinstance(system.get("sides"), dict) else {}
        if "subduction" in mechanism:
            center = float(sides.get("overriding_normal_side", 1) or 1) * 1.24
        elif mechanism == "continental_collision":
            center = float(sides.get("hinterland_normal_side", 1) or 1) * 0.24
        elif mechanism == "continental_rift":
            center = 0.92
        else:
            center = 0.0
        envelope = math.exp(-(((signed_distance - center) / 1.15) ** 2))
        axis_angle = math.atan2(tangent_y, tangent_x)
        best = {
            "score": score,
            "mountain_belt_envelope": _clamp(envelope * score, 0.0, 1.0),
            "mountain_belt_cross_range": signed_distance,
            "mountain_belt_axis_x": tangent_x / tangent_length,
            "mountain_belt_axis_y": tangent_y / tangent_length,
            # Belt orientation as a doubled angle: segments of one boundary
            # are stored in either direction, and the axis vectors (1, 0) and
            # (-1, 0) name the same belt but interpolate to zero.
            "mountain_belt_axis_c2": math.cos(2.0 * axis_angle),
            "mountain_belt_axis_s2": math.sin(2.0 * axis_angle),
        }
    return {
        key: float((best or {}).get(key, 0.0))
        for key in (
            "mountain_belt_envelope",
            "mountain_belt_cross_range",
            "mountain_belt_axis_x",
            "mountain_belt_axis_y",
            "mountain_belt_axis_c2",
            "mountain_belt_axis_s2",
        )
    }


def _tile_belt_frame(orogen_structural_grid, source_u0, source_u1, source_v0, source_v1, planet_circumference):
    """One belt orientation and a rotation origin for a whole child tile.

    Branching ridges are evaluated in coordinates rotated to the belt axis.
    Rotating world coordinates (about 1e7 m from the origin) by a per-sample
    axis turned any axis change between samples into a jump of kilometres
    in noise space, which rendered as stair-stepped streaks.  The tile uses
    the envelope-weighted mean orientation (doubled angle, so opposite
    segment directions agree) about its own centre instead.
    """
    origin = (
        (float(source_u0) + float(source_u1)) * 0.5 * float(planet_circumference),
        (float(source_v0) + float(source_v1)) * 0.5 * float(planet_circumference) * 0.5,
    )
    channels = (orogen_structural_grid or {}).get("channels") if isinstance(orogen_structural_grid, dict) else None
    if not channels or "mountain_belt_axis_c2" not in channels:
        return (1.0, 0.0), origin
    weight_sum = cos_sum = sin_sum = 0.0
    for envelope_row, c2_row, s2_row in zip(
        channels.get("mountain_belt_envelope") or [],
        channels["mountain_belt_axis_c2"],
        channels["mountain_belt_axis_s2"],
    ):
        for envelope, c2, s2 in zip(envelope_row, c2_row, s2_row):
            weight = max(0.0, float(envelope))
            weight_sum += weight
            cos_sum += weight * float(c2)
            sin_sum += weight * float(s2)
    if weight_sum <= 1e-9 or math.hypot(cos_sum, sin_sum) <= 1e-9 * weight_sum:
        return (1.0, 0.0), origin
    angle = 0.5 * math.atan2(sin_sum, cos_sum)
    return (math.cos(angle), math.sin(angle)), origin


def _axis_from_doubled_angle(context):
    """Replace interpolated axis vectors by the doubled-angle orientation.

    Works on scalars and arrays; keeps the axis zero where no belt applies.
    """
    c2 = context.get("mountain_belt_axis_c2")
    s2 = context.get("mountain_belt_axis_s2")
    if c2 is None or s2 is None:
        return context
    if np is not None and (isinstance(c2, np.ndarray) or isinstance(s2, np.ndarray)):
        strength = np.hypot(c2, s2)
        angle = 0.5 * np.arctan2(s2, c2)
        context["mountain_belt_axis_x"] = np.cos(angle) * strength
        context["mountain_belt_axis_y"] = np.sin(angle) * strength
    else:
        strength = math.hypot(float(c2), float(s2))
        angle = 0.5 * math.atan2(float(s2), float(c2))
        context["mountain_belt_axis_x"] = math.cos(angle) * strength
        context["mountain_belt_axis_y"] = math.sin(angle) * strength
    return context


def _build_orogen_structural_grid(
    tectonic_model,
    source_u0,
    source_u1,
    source_v0,
    source_v1,
    *,
    sample_width,
    sample_height,
):
    """Sample the production orogen field sparsely for a child footprint.

    The production height evaluator remains authoritative at every child
    sample. This separate structural gate is smooth over a regional tile, so
    sampling it on a compact grid avoids re-running the boundary resolver
    hundreds of thousands of times during one refinement.
    """
    if not isinstance(tectonic_model, dict):
        return None
    tectonic_model = _ensure_heightmap_tectonic_model(tectonic_model)
    grid_width = max(17, min(49, int(sample_width) // 16 + 1))
    grid_height = max(17, min(33, int(sample_height) // 16 + 1))
    channels = {
        key: []
        for key in (
            "mountain_influence",
            "core_influence",
            "arc_influence",
            "shoulder_influence",
            "forearc_influence",
            "trench_influence",
            "mountain_belt_envelope",
            "mountain_belt_cross_range",
            "mountain_belt_axis_x",
            "mountain_belt_axis_y",
            "mountain_belt_axis_c2",
            "mountain_belt_axis_s2",
        )
    }
    for row in range(grid_height):
        local_v = row / max(1, grid_height - 1)
        global_v = float(source_v0) + (float(source_v1) - float(source_v0)) * local_v
        for key in channels:
            channels[key].append([])
        for col in range(grid_width):
            local_u = col / max(1, grid_width - 1)
            global_u = float(source_u0) + (float(source_u1) - float(source_u0)) * local_u
            context = _orogen_structural_context(global_u, global_v, tectonic_model)
            context.update(_orogen_belt_context(global_u, global_v, tectonic_model))
            for key in channels:
                channels[key][row].append(float(context[key]))
    return {
        "source_uv_bounds": {
            "min_u": float(source_u0),
            "max_u": float(source_u1),
            "min_v": float(source_v0),
            "max_v": float(source_v1),
        },
        "width": grid_width,
        "height": grid_height,
        "channels": channels,
    }


def _sample_orogen_structural_grid(grid, nx, ny):
    """Interpolate the compact production-orogen structural grid."""
    if not isinstance(grid, dict):
        return {
            "mountain_influence": 0.0,
            "core_influence": 0.0,
            "arc_influence": 0.0,
            "shoulder_influence": 0.0,
            "forearc_influence": 0.0,
            "trench_influence": 0.0,
            "mountain_belt_envelope": 0.0,
            "mountain_belt_cross_range": 0.0,
            "mountain_belt_axis_x": 0.0,
            "mountain_belt_axis_y": 0.0,
        }
    bounds = grid.get("source_uv_bounds") or {}
    u0, u1 = float(bounds.get("min_u", 0.0)), float(bounds.get("max_u", 1.0))
    v0, v1 = float(bounds.get("min_v", 0.0)), float(bounds.get("max_v", 1.0))
    u = _clamp((float(nx) - u0) / max(1e-12, u1 - u0), 0.0, 1.0)
    v = _clamp((float(ny) - v0) / max(1e-12, v1 - v0), 0.0, 1.0)
    return _axis_from_doubled_angle({
        key: _sample_bilinear(rows, u, v, wrap_x=False)
        for key, rows in (grid.get("channels") or {}).items()
    })


def _boundary_anchored_ridge_valley_signal(
    seed,
    x_m,
    y_m,
    wavelength_m,
    orogen_context,
    ridge_phase,
    *,
    period_x_m=None,
    tile_frame=None,
):
    """Build branching relief while retaining the parent belt's position.

    A single sine of cross-range is a useful tectonic cue but reads as evenly
    spaced stripes when it dominates a regional tile.  This combines a weak
    belt-anchored trunk with rotated branching noise and along-belt warping.
    The boundary-derived cross-range remains the placement anchor; the
    branching terms decide where ridges merge, split, and terminate.
    ``tile_frame`` (``_tile_belt_frame``) fixes the rotation for the tile.
    """
    wavelength = max(1.0, float(wavelength_m))
    if tile_frame is not None:
        (axis_x, axis_y), (origin_x, origin_y) = tile_frame
    else:
        origin_x = origin_y = 0.0
        axis_x = float(orogen_context.get("mountain_belt_axis_x", 0.0) or 0.0)
        axis_y = float(orogen_context.get("mountain_belt_axis_y", 0.0) or 0.0)
        axis_length = math.hypot(axis_x, axis_y)
        if axis_length < 1e-6:
            axis_x, axis_y = 1.0, 0.0
        else:
            axis_x /= axis_length
            axis_y /= axis_length
    along_m = (float(x_m) - origin_x) * axis_x + (float(y_m) - origin_y) * axis_y
    across_m = -(float(x_m) - origin_x) * axis_y + (float(y_m) - origin_y) * axis_x
    cross_range = float(orogen_context.get("mountain_belt_cross_range", 0.0) or 0.0)
    cross_warp = fractal_noise_m(
        seed,
        "regional-ridge-cross-warp",
        x_m,
        y_m,
        wavelength * 2.8,
        octaves=2,
        gain=0.52,
        period_x_m=period_x_m,
    )
    along_warp = fractal_noise_m(
        seed,
        "regional-ridge-along-warp",
        x_m,
        y_m,
        wavelength * 3.6,
        octaves=3,
        gain=0.48,
        period_x_m=period_x_m,
    )
    anchored_phase = (
        math.tau * (cross_range * 0.34 + cross_warp * 0.18)
        + ridge_phase
        + along_warp * 1.15
    )
    trunk = math.sin(anchored_phase)
    secondary = math.sin(anchored_phase * 1.83 + along_warp * 2.4)
    branching = branching_mountain_relief_m(
        seed,
        "regional-boundary-branching-ridges",
        along_m,
        across_m,
        wavelength * 0.92,
        period_x_m=period_x_m,
    )
    return _clamp(
        trunk * 0.28 + secondary * 0.14 + branching * 0.58,
        -1.0,
        1.0,
    )


def _parent_topology_certainty(rows, u, v, sea_level, *, wrap_x=True):
    """Return -1 ocean, +1 land, or 0 for an unresolved parent coast cell."""
    if sea_level is None or not rows or not rows[0]:
        return 0
    height, width = len(rows), len(rows[0])
    normalized_u = float(u) % 1.0 if wrap_x else _clamp(u, 0.0, 1.0)
    px = normalized_u * max(1, width - 1)
    py = _clamp(v, 0.0, 1.0) * max(1, height - 1)
    x0, y0 = int(math.floor(px)), int(math.floor(py))
    x1 = (x0 + 1) % width if wrap_x else min(width - 1, x0 + 1)
    y1 = min(height - 1, y0 + 1)
    signs = {
        1 if float(rows[yy][xx]) >= float(sea_level) else -1
        for xx, yy in ((x0, y0), (x1, y0), (x0, y1), (x1, y1))
    }
    return signs.pop() if len(signs) == 1 else 0


def _topology_without_landform_crossings(topology_rows, before_rows, after_rows, sea_level):
    """``topology_rows`` with no certainty where a landform took this level's own ground across sea level.

    The contract's reference is the parent's surface with the landforms'
    change added, and the side it has there need not be the side the
    change left this level's ground on: a foreshore the waves planed to
    just under the sea stood, in the reference, half a metre to four
    metres above it.  The contract then lifted 218 such cells of an arid
    Site tile back to a centimetre above the sea, a row of specks along
    the shoreface that the beach rule took for bars the next time.
    """
    if not topology_rows or sea_level is None:
        return topology_rows
    topology = np.asarray(topology_rows)
    before = np.asarray(before_rows, dtype=np.float64)
    after = np.asarray(after_rows, dtype=np.float64)
    if topology.shape != before.shape or before.shape != after.shape:
        return topology_rows
    crossed = (before >= float(sea_level)) != (after >= float(sea_level))
    if not crossed.any():
        return topology_rows
    return np.where(crossed, 0, topology).tolist()


def _enforce_parent_height_contract(
    heightmap,
    inherited_rows,
    topology_rows,
    detail_amplitude_m,
):
    """Keep a child a bounded residual refinement of its parent surface.

    Climate, erosion and coastal materialisation all run after the initial
    interpolation.  Without a final constraint those passes can collectively
    cross sea level throughout an otherwise certain parent cell and create a
    new archipelago or erase a peninsula.  Mixed parent cells remain free to
    resolve a more detailed shoreline.

    ``inherited_rows`` is the reference the child is held to: the parent's
    surface with this level's landforms in it.  Where a landform took the
    ground across sea level (a shore the waves cut back, an island built)
    the side is the landform's, not the parent cell's: held to the parent's
    side, a drowned shore platform came back as dry land in the shape of
    the parent's cells.
    """
    grid = heightmap.get("sample_grid") if isinstance(heightmap, dict) else {}
    rows = grid.get("rows") if isinstance(grid, dict) else None
    if not rows or not inherited_rows or len(rows) != len(inherited_rows):
        return heightmap, {"status": "unavailable", "changed_cell_count": 0}
    sea = heightmap.get("sea_level_m")
    maximum_delta = max(0.03, float(detail_amplitude_m or 0.0) * 2.15)
    digits = max(3, height_decimals(heightmap.get("sample_spacing_x_m")))
    changed = 0
    topology_corrections = 0
    maximum_observed_delta = 0.0
    limited = []
    for y, row in enumerate(rows):
        target_row = []
        for x, value in enumerate(row):
            inherited = float(inherited_rows[y][x])
            original = float(value)
            resolved = max(
                inherited - maximum_delta,
                min(inherited + maximum_delta, original),
            )
            certainty = int(topology_rows[y][x]) if topology_rows else 0
            if sea is not None and certainty and (inherited >= float(sea)) != (certainty > 0):
                certainty = 0
            if sea is not None and certainty:
                parent_clearance = abs(inherited - float(sea))
                margin = max(
                    0.01,
                    min(maximum_delta * 0.06, parent_clearance * 0.25),
                )
                if certainty > 0 and resolved < float(sea) + margin:
                    resolved = float(sea) + margin
                    topology_corrections += 1
                elif certainty < 0 and resolved >= float(sea) - margin:
                    resolved = float(sea) - margin
                    topology_corrections += 1
            if abs(resolved - original) > 1e-6:
                changed += 1
            maximum_observed_delta = max(
                maximum_observed_delta, abs(resolved - inherited)
            )
            target_row.append(round(resolved, digits))
        limited.append(target_row)
    if not changed:
        return heightmap, {
            "status": "satisfied",
            "changed_cell_count": 0,
            "topology_correction_count": 0,
            "maximum_child_residual_m": round(maximum_observed_delta, 4),
            "allowed_child_residual_m": round(maximum_delta, 4),
        }
    updated = dict(heightmap)
    updated["sample_grid"] = {**grid, "rows": limited}
    updated["min_elevation_m"] = round(min(min(row) for row in limited), 3)
    updated["max_elevation_m"] = round(max(max(row) for row in limited), 3)
    return updated, {
        "status": "enforced",
        "changed_cell_count": changed,
        "topology_correction_count": topology_corrections,
        "maximum_child_residual_m": round(maximum_observed_delta, 4),
        "allowed_child_residual_m": round(maximum_delta, 4),
        "rule": "child_equals_bicubic_parent_plus_bounded_process_residual",
    }


def _condition_regional_craters_to_parent(
    crater_model,
    parent_rows,
    u0,
    u1,
    v0,
    v1,
    sea_level,
    global_preservation,
    *,
    parent_wrap_x,
):
    if not isinstance(crater_model, dict):
        return crater_model
    conditioned = []
    for source in crater_model.get("craters") or []:
        crater = dict(source)
        parent_u = u0 + (u1 - u0) * float(crater.get("x", 0.5) or 0.5)
        parent_v = v0 + (v1 - v0) * float(crater.get("y", 0.5) or 0.5)
        elevation = _sample_bilinear(
            parent_rows, parent_u, parent_v, wrap_x=parent_wrap_x,
        )
        water_depth = (
            max(0.0, float(sea_level) - elevation)
            if sea_level is not None
            else 0.0
        )
        transmission = 1.0
        if water_depth > 0.0:
            projectile = max(
                1.0, float(crater.get("diameter_m", 1.0) or 1.0) / 16.0
            )
            transmission = _clamp(
                math.exp(-1.18 * max(0.0, water_depth / projectile - 0.12)),
                0.015,
                1.0,
            )
        crater["target_environment"] = "marine" if water_depth > 0.0 else "subaerial"
        crater["target_water_depth_m"] = round(water_depth, 3)
        crater["marine_crater_transmission"] = round(transmission, 4)
        crater["morphology_preservation"] = round(
            _clamp(float(global_preservation or 1.0) * transmission, 0.0, 1.0), 4
        )
        conditioned.append(crater)
    conditioned_model = dict(crater_model)
    conditioned_model["craters"] = conditioned
    return conditioned_model


def _crater_profile_adjustment(normalized_distance, depth_m, rim_height_m, morphology="simple", azimuth=0.0, phase=0.0):
    if normalized_distance > 1.8:
        return 0.0
    adjustment = 0.0
    if normalized_distance < 1.0:
        if morphology == "complex_or_basin":
            wall_t = _clamp((normalized_distance - 0.52) / 0.48, 0.0, 1.0)
            wall_t = wall_t * wall_t * (3.0 - 2.0 * wall_t)
            basin = 0.62 + 0.38 * (1.0 - wall_t)
            adjustment -= depth_m * basin
            adjustment += min(depth_m * 0.34, rim_height_m * 3.2) * math.exp(-((normalized_distance / 0.17) ** 2))
            adjustment += rim_height_m * 0.24 * math.exp(-(((normalized_distance - 0.72) / 0.075) ** 2))
        else:
            adjustment -= depth_m * max(0.0, 1.0 - normalized_distance * normalized_distance) ** 1.35
    adjustment += rim_height_m * math.exp(-(((normalized_distance - 1.0) / 0.105) ** 2))
    if normalized_distance > 1.0:
        ray_modulation = 0.72 + 0.28 * max(0.0, math.cos(5.0 * azimuth + phase)) ** 3
        adjustment += rim_height_m * 0.22 * math.exp(-(normalized_distance - 1.0) / 0.31) * ray_modulation
    return adjustment


def _local_crater_adjustment_m(u, v, crater_model):
    if not isinstance(crater_model, dict):
        return 0.0
    width_m = max(1.0, float(crater_model.get("region_width_m", 1.0) or 1.0))
    height_m = max(1.0, float(crater_model.get("region_height_m", 1.0) or 1.0))
    adjustment = 0.0
    for crater in crater_model.get("craters") or []:
        dx_m = (float(u) - float(crater.get("x", 0.0) or 0.0)) * width_m
        dy_m = (float(v) - float(crater.get("y", 0.0) or 0.0)) * height_m
        radius_m = max(0.01, float(crater.get("diameter_m", 1.0) or 1.0) * 0.5)
        normalized_distance = math.hypot(dx_m, dy_m) / radius_m
        if normalized_distance > 1.8:
            continue
        adjustment += _crater_profile_adjustment(
            normalized_distance,
            float(crater.get("depth_m", 0.0) or 0.0)
            * _clamp(crater.get("morphology_preservation", 1.0), 0.0, 1.0),
            float(crater.get("rim_height_m", 0.0) or 0.0)
            * _clamp(crater.get("morphology_preservation", 1.0), 0.0, 1.0),
            morphology=str(crater.get("morphology") or "simple"),
            azimuth=math.atan2(dy_m, dx_m + 1e-12),
            phase=float(crater.get("ray_phase", 0.0) or 0.0),
        )
    return adjustment


def _global_crater_adjustment_grid(crater_model, parent_heightmap, width, height):
    source = parent_heightmap.get("source_uv_bounds") or {}
    source_tuple = tuple(round(float(source.get(key, default) or default), 9) for key, default in (
        ("min_u", 0.0), ("max_u", 1.0), ("min_v", 0.0), ("max_v", 1.0),
    ))
    key = (str(crater_model.get("map_seed") or ""), int(width), int(height), source_tuple)
    cached = _CRATER_GRID_CACHE.get(key)
    if cached is not None:
        return cached
    spatial_index = _crater_spatial_index(crater_model)
    u0, u1, v0, v1 = source_tuple
    rows = []
    for y in range(height):
        global_v = v0 + (v1 - v0) * y / max(1, height - 1)
        rows.append([
            _crater_height_adjustment_m(
                u0 + (u1 - u0) * x / max(1, width - 1), global_v,
                crater_model, spatial_index,
            )
            for x in range(width)
        ])
    _CRATER_GRID_CACHE[key] = rows
    while len(_CRATER_GRID_CACHE) > 8:
        _CRATER_GRID_CACHE.pop(next(iter(_CRATER_GRID_CACHE)))
    return rows


def _local_crater_adjustment_grid(crater_model, width, height):
    if not isinstance(crater_model, dict) or not crater_model.get("craters"):
        return None
    return [
        [_local_crater_adjustment_m(x / max(1, width - 1), y / max(1, height - 1), crater_model) for x in range(width)]
        for y in range(height)
    ]


def _crater_model_for_explicit_scale(crater_model, maximum_diameter_m, *, global_catalog=False):
    """Keep only impacts whose bowl/rim curvature is meaningful in this patch.

    Larger basins remain present through the inherited parent elevation.  An
    analytic re-draw of those basins in every descendant produces dominant,
    smooth sectors where only a tiny piece of the original impact is visible.
    """
    if not isinstance(crater_model, dict):
        return None
    diameter_key = "diameter_km" if global_catalog else "diameter_m"
    scale = 1000.0 if global_catalog else 1.0
    craters = [
        crater for crater in (crater_model.get("craters") or [])
        if float(crater.get(diameter_key, 0.0) or 0.0) * scale <= maximum_diameter_m
    ]
    if not craters:
        return None
    filtered = dict(crater_model)
    filtered["craters"] = craters
    # The cache key must distinguish this scale-filtered catalog.
    filtered["map_seed"] = f"{crater_model.get('map_seed') or ''}:explicit:{maximum_diameter_m:.0f}"
    return filtered


def _new_regional_crater_model(crater_model, map_seed, width_m, height_m, sample_width, sample_height, parent_heightmap):
    if not isinstance(crater_model, dict) or not crater_model.get("craters"):
        return None
    spacing_m = max(width_m / max(1, sample_width - 1), height_m / max(1, sample_height - 1))
    parent_grid = parent_heightmap.get("sample_grid") or {}
    parent_width_m, parent_height_m = map_physical_dimensions_m(parent_heightmap)
    parent_spacing_m = max(
        parent_width_m / max(1, int(parent_grid.get("width", 1) or 1) - 1),
        parent_height_m / max(1, int(parent_grid.get("height", 1) or 1) - 1),
    )
    cutoff_m = max(0.0, float(crater_model.get("atmospheric_entry_cutoff_km", 0.0) or 0.0) * 1000.0)
    minimum_m = max(cutoff_m, spacing_m * 4.0)
    catalog_min_m = max(1.0, float(crater_model.get("minimum_catalog_diameter_km", 1.0) or 1.0) * 1000.0)
    maximum_m = min(min(width_m, height_m) * 0.22, parent_spacing_m * 1.8, catalog_min_m * 0.98)
    if maximum_m <= minimum_m * 1.08:
        return None
    slope = max(1.2, float(crater_model.get("size_frequency_cumulative_slope", 1.9) or 1.9))
    density_reference = max(0.0, float(crater_model.get("craters_per_million_km2_above_catalog_min", 0.0) or 0.0))
    area_million_km2 = width_m * height_m / 1.0e12
    expected_min = density_reference * area_million_km2 * (minimum_m / catalog_min_m) ** -slope
    expected_max = density_reference * area_million_km2 * (maximum_m / catalog_min_m) ** -slope
    expected_count = max(0.0, expected_min - expected_max)
    count = min(96, int(expected_count + seed_range(map_seed, "regional_crater_count", 0.0, 1.0)))
    if count <= 0:
        return None
    craters = []
    ratio = maximum_m / minimum_m
    for index in range(count):
        quantile = seed_range(map_seed, f"regional_crater_{index}:size", 0.0001, 0.9999)
        diameter_m = minimum_m * (1.0 - quantile * (1.0 - ratio ** -slope)) ** (-1.0 / slope)
        depth_ratio = 0.105 if diameter_m < 18_000.0 else 0.075 * (diameter_m / 18_000.0) ** -0.22
        craters.append({
            "id": f"regional_crater_{index + 1:03d}",
            "x": seed_range(map_seed, f"regional_crater_{index}:x", -0.04, 1.04),
            "y": seed_range(map_seed, f"regional_crater_{index}:y", -0.04, 1.04),
            "diameter_m": round(diameter_m, 3),
            # Store fresh morphology.  Atmosphere, erosion, resurfacing and
            # water-column preservation are applied exactly once by
            # _condition_regional_craters_to_parent below.
            "depth_m": round(diameter_m * depth_ratio, 3),
            "rim_height_m": round(diameter_m * 0.025, 3),
            "morphology": "complex_or_basin" if diameter_m >= 18_000.0 else "simple",
            "ray_phase": seed_range(map_seed, f"regional_crater_{index}:phase", 0.0, math.tau),
        })
    return {
        "status": "regional_crater_population_seeded",
        "region_width_m": width_m,
        "region_height_m": height_m,
        "minimum_diameter_m": minimum_m,
        "maximum_diameter_m": maximum_m,
        "craters": craters,
    }


def _production_tectonic_height_model(root_planet):
    """Prepare the actual planetary tectonic evaluator for regional sampling.

    Regional refinement may add scale-specific residual detail, but its broad
    geography must remain the production planet's geography.  This is the same
    tectonic deformation and heightfield evaluator used by
    ``derive_heightmap_model``; it is deliberately kept separate from the
    regional noise field so the provenance is auditable.
    """
    if not isinstance(root_planet, dict):
        return None
    source = root_planet.get("tectonic_model")
    if not isinstance(source, dict) or not source.get("plates"):
        return None
    sampled = _heightmap_tectonic_model(source)
    deformation = (root_planet.get("heightmap_model") or {}).get("deformation_state_model")
    if isinstance(deformation, dict):
        sampled["deformation_state_model"] = copy.deepcopy(deformation)
    return sampled


def _production_height_at(nx, ny, terrain, root_heightmap, tectonic_model):
    """Evaluate the production global heightfield at normalized planet UV."""
    if not isinstance(tectonic_model, dict) or not isinstance(root_heightmap, dict):
        return None
    heightfield = terrain.get("heightfield") if isinstance(terrain, dict) else {}
    minimum = float(heightfield.get("min_elevation_m", -5000.0) or -5000.0)
    maximum = float(heightfield.get("max_elevation_m", 6000.0) or 6000.0)
    midpoint = (minimum + maximum) * 0.5
    half_range = max(1.0, (maximum - minimum) * 0.5)
    raw = _wave_height(
        nx,
        ny,
        terrain,
        tectonic_model=tectonic_model,
        crater_model=None,
        crater_spatial_index=None,
        map_seed=str(root_heightmap.get("map_seed") or terrain.get("map_seed") or ""),
    )
    # The planet's isostatic contrast calibration applies here too, or the
    # regional residual would carry the whole correction over the oceans.
    return midpoint + raw * half_range + crustal_freeboard_shift_at(nx, ny, tectonic_model, root_heightmap)


def _build_production_residual_grid(
    parent_rows,
    production_terrain,
    root_heightmap,
    production_tectonic_model,
    *,
    parent_u0,
    parent_u1,
    parent_v0,
    parent_v1,
    source_u0,
    source_u1,
    source_v0,
    source_v1,
    sample_width,
    sample_height,
):
    """Resolve the production residual at the child's supported scale.

    The production evaluator is the authoritative tectonic/geographic source,
    but evaluating it at every 196 m child sample exposes fine boundary
    resolver structure that the 40 km parent cannot actually resolve. A
    compact residual grid retains the production signal while applying the
    same scale separation used by the rest of hierarchical refinement.
    """
    if not isinstance(production_tectonic_model, dict) or not parent_rows:
        return None
    grid_width = max(17, min(65, int(sample_width) // 8 + 1))
    grid_height = max(17, min(65, int(sample_height) // 8 + 1))
    residual_rows = []
    production_rows = []
    for row in range(grid_height):
        local_v = row / max(1, grid_height - 1)
        parent_v = float(parent_v0) + (float(parent_v1) - float(parent_v0)) * local_v
        source_v = float(source_v0) + (float(source_v1) - float(source_v0)) * local_v
        residual_row = []
        production_row = []
        for col in range(grid_width):
            local_u = col / max(1, grid_width - 1)
            parent_u = float(parent_u0) + (float(parent_u1) - float(parent_u0)) * local_u
            source_u = float(source_u0) + (float(source_u1) - float(source_u0)) * local_u
            inherited = _sample_bicubic(parent_rows, parent_u, parent_v, wrap_x=True)
            production = _production_height_at(
                source_u,
                source_v,
                production_terrain,
                root_heightmap,
                production_tectonic_model,
            )
            if production is None:
                return None
            residual_row.append(float(production) - inherited)
            production_row.append(float(production))
        residual_rows.append(residual_row)
        production_rows.append(production_row)
    return {
        "width": grid_width,
        "height": grid_height,
        "residual_rows": residual_rows,
        "production_rows": production_rows,
        "source": "production_heightfield_residual_compact_child_scale_grid",
    }


def _regional_tectonic_context(root_planet, source_uv_bounds, *, sample_width, sample_height):
    """Persist a compact, auditable projection of the parent plate model."""
    source = root_planet.get("tectonic_model") if isinstance(root_planet, dict) else None
    if not isinstance(source, dict) or not source.get("plates"):
        return None
    source_grid = source.get("sample_grid") if isinstance(source.get("sample_grid"), dict) else {}
    owners = source_grid.get("owners") or []
    owner_width = int(source_grid.get("width", 0) or 0)
    owner_height = int(source_grid.get("height", 0) or 0)
    u0 = float(source_uv_bounds.get("min_u", 0.0) or 0.0)
    u1 = float(source_uv_bounds.get("max_u", 1.0) or 1.0)
    v0 = float(source_uv_bounds.get("min_v", 0.0) or 0.0)
    v1 = float(source_uv_bounds.get("max_v", 1.0) or 1.0)
    local_owners = []
    if owners and owner_width > 0 and owner_height > 0:
        for row in range(max(3, min(65, sample_height // 4 + 1))):
            local_v = row / max(1, max(3, min(65, sample_height // 4 + 1)) - 1)
            source_v = v0 + (v1 - v0) * local_v
            owner_row = []
            for col in range(max(3, min(129, sample_width // 4 + 1))):
                local_u = col / max(1, max(3, min(129, sample_width // 4 + 1)) - 1)
                source_u = u0 + (u1 - u0) * local_u
                x = min(owner_width - 1, int(round(source_u * max(1, owner_width - 1))))
                y = min(owner_height - 1, int(round(source_v * max(1, owner_height - 1))))
                owner_row.append(owners[y][x])
            local_owners.append(owner_row)
    source_detail_level = int(root_planet.get("map_detail_level", 0) or 0)
    return {
        "status": (
            "regional_tectonics_sampled_from_parent_production_model"
            if source_detail_level == 0
            else "regional_tectonics_inherited_from_immediate_parent"
        ),
        "source_status": source.get("status"),
        "source_model_version": source.get("model_version"),
        "map_seed": source.get("map_seed"),
        "coordinate_frame": "immediate_parent_normalized_uv",
        "source_map_id": root_planet.get("id"),
        "source_detail_level": int(root_planet.get("map_detail_level", 0) or 0),
        "inheritance_mode": "immediate_parent_snapshot",
        "source_uv_bounds": copy.deepcopy(source_uv_bounds),
        "plates": copy.deepcopy(source.get("plates") or []),
        "boundary_segments": copy.deepcopy(source.get("boundary_segments") or []),
        "hotspot_model": copy.deepcopy(source.get("hotspot_model") or {}),
        "orogen_system_model": {
            "systems": copy.deepcopy(
                (source.get("orogen_system_model") or {}).get("systems") or []
            ),
            "model_version": (source.get("orogen_system_model") or {}).get("model_version"),
            "system_count": len((source.get("orogen_system_model") or {}).get("systems") or []),
        },
        "sample_grid": {
            "width": max((len(row) for row in local_owners), default=0),
            "height": len(local_owners),
            "owners": local_owners,
            "source_width": owner_width,
            "source_height": owner_height,
        },
        "usage_contract": "parent_tectonic_snapshot_with_scale_specific_residual_detail",
    }


def _combined_child_crater_model(parent_model, new_model, u0, u1, v0, v1, width_m, height_m):
    craters = []
    if isinstance(parent_model, dict):
        parent_width_m = max(1.0, float(parent_model.get("region_width_m", 1.0) or 1.0))
        parent_height_m = max(1.0, float(parent_model.get("region_height_m", 1.0) or 1.0))
        for crater in parent_model.get("craters") or []:
            diameter_m = float(crater.get("diameter_m", 0.0) or 0.0)
            radius_u = diameter_m * 0.9 / parent_width_m
            radius_v = diameter_m * 0.9 / parent_height_m
            cx, cy = float(crater.get("x", 0.0) or 0.0), float(crater.get("y", 0.0) or 0.0)
            if cx + radius_u < u0 or cx - radius_u > u1 or cy + radius_v < v0 or cy - radius_v > v1:
                continue
            transformed = dict(crater)
            transformed["x"] = (cx - u0) / max(1e-12, u1 - u0)
            transformed["y"] = (cy - v0) / max(1e-12, v1 - v0)
            craters.append(transformed)
    if isinstance(new_model, dict):
        craters.extend(dict(crater) for crater in (new_model.get("craters") or []))
    if not craters:
        return None
    return {
        "status": "regional_crater_population_seeded",
        "region_width_m": width_m,
        "region_height_m": height_m,
        "minimum_diameter_m": min(float(crater.get("diameter_m", 0.0) or 0.0) for crater in craters),
        "maximum_diameter_m": max(float(crater.get("diameter_m", 0.0) or 0.0) for crater in craters),
        "craters": craters,
    }


def _root_planet_id(world_model, entity):
    current, visited = entity, set()
    while isinstance(current, dict) and current.get("id") not in visited:
        visited.add(current.get("id"))
        if current.get("location_class") in {"planet", "moon"}:
            return current.get("id")
        current = world_model.get_entity(current.get("refinement_parent_map_id") or current.get("parent_location"))
    return entity.get("id")


# --- The scale of a refinement --------------------------------------------------
# A level is a scale of ground, not a count of refinements.  Every recipe that
# is switched or sized by the level (bed thickness, mapped-unit size, channels
# from Site scale, fine soils, ...) assumes the cells a map of that level has,
# so the level follows from the map's footprint: the longest side a map of
# each level may have (m).  With the grids of ``refinement_sample_dimensions``
# that is cells of 1-16 km for a Macroregion, 88 m-1 km for a Region, 16-117 m
# Local, 2.2-16 m Site, 0.28-2.2 m Parcel and 0.1-0.28 m for a Plot.  Anything
# wider than a Macroregion has the scale of a planet map (0).
#
# Counted instead, the level went wrong both ways.  A "Macroregion" refined
# over most of a planet at 48 km a cell and a "Region" under it at 7 km ran
# kilometre-scale recipes on cells larger than their forms: every cell a rock
# unit of its own, bed scarps ruled straight across a continent.  A parcel
# refined straight from a planet would have had none of the valleys, cliffs
# and channels the levels in between build.
LEVEL_MAX_EXTENT_M = {1: 8_192_000.0, 2: 512_000.0, 3: 45_000.0, 4: 6_000.0, 5: 850.0, 6: 107.0}
# A step makes cells at least this many times finer: a level's detail lives
# between its parent's spacing and its own, and less leaves it no room.
MIN_REFINEMENT_STEP = 3.0
# An in-between map keeps this far inside its level's range of footprints.
INTERMEDIATE_BAND_INSET = 0.85
# Longest side of a map sampled at the terrain-data floor.
FLOOR_GRID_EXTENT_M = MIN_TERRAIN_SAMPLE_SPACING_M * 384.0


class RefinementStepError(ValueError):
    """A footprint no refinement can be made of.

    ``reason`` is ``"too_large"`` (the map would not be a level finer than
    its parent; ``max_extent_m`` is the longest side that works),
    ``"too_small"`` (it needs maps in between and they were not allowed) or
    ``"finest"`` (the parent is at the terrain-data floor).
    """

    def __init__(self, reason, message, *, max_extent_m=None, level=None):
        super().__init__(message)
        self.reason = reason
        self.max_extent_m = max_extent_m
        self.level = level


def footprint_level(extent_m):
    """Scale level of a map whose longest side is ``extent_m``: 0 for anything wider than a Macroregion."""
    extent = float(extent_m or 0.0)
    for level in sorted(LEVEL_MAX_EXTENT_M, reverse=True):
        if extent <= LEVEL_MAX_EXTENT_M[level]:
            return level
    return 0


def format_extent(extent_m):
    """A length for a person: ``8.2 Mm``, ``512 km``, ``850 m``."""
    extent = max(0.0, float(extent_m or 0.0))
    if extent >= 1_000_000.0:
        return f"{extent / 1_000_000.0:.2g} Mm"
    if extent >= 1_000.0:
        return f"{extent / 1_000.0:.3g} km"
    return f"{extent:.3g} m"


def map_cell_size_m(entity):
    """Sample spacing of a map (m; the larger of its two directions), 0 where it is unknown."""
    heightmap = (entity or {}).get("heightmap_model") if isinstance(entity, dict) else None
    grid = (heightmap or {}).get("sample_grid") or {}
    rows = grid.get("rows") or []
    columns = int(grid.get("width") or (len(rows[0]) if rows and rows[0] else 0) or 0)
    lines = int(grid.get("height") or len(rows) or 0)
    width_m, height_m = map_physical_dimensions_m(entity)
    cells = [extent / (count - 1) for extent, count in ((width_m, columns), (height_m, lines)) if extent > 0.0 and count > 1]
    return max(cells) if cells else 0.0


def map_scale_level(entity):
    """Scale level of a stored map, read off its footprint (its own number where it has no size)."""
    stored = int((entity or {}).get("map_detail_level", 0) or 0)
    width_m, height_m = map_physical_dimensions_m(entity)
    if max(width_m, height_m) <= 0.0:
        return stored
    # A Survey has a Plot's footprint; only its own record tells them apart.
    return max(footprint_level(max(width_m, height_m)), 7 if stored >= 7 else 0)


def max_refinement_extent_m(parent_entity):
    """Longest side a map refined from ``parent_entity`` in one step may have (m); 0 at the finest level."""
    scale = map_scale_level(parent_entity)
    cell = map_cell_size_m(parent_entity)
    if scale >= 7 or (scale >= 6 and 0.0 < cell <= MIN_TERRAIN_SAMPLE_SPACING_M * 1.05):
        return 0.0
    if scale >= 6:
        # A Plot whose cells are still above the floor takes one last step to it: a Survey.
        return FLOOR_GRID_EXTENT_M
    level = scale + 1
    by_step = cell / MIN_REFINEMENT_STEP * ((513 if level <= 2 else 385) - 1) if cell > 0.0 else math.inf
    if level == 6:
        # At the floor the step is whatever is left.
        by_step = max(by_step, FLOOR_GRID_EXTENT_M)
    return min(LEVEL_MAX_EXTENT_M[level], by_step)


def refinement_floor_reached(entity, tolerance=0.01):
    """No finer map can be made of this one."""
    width_m, height_m = map_physical_dimensions_m(entity)
    if width_m <= 0.0 or height_m <= 0.0:
        return False
    limit = MIN_REFINED_EXTENT_M * (1.0 + max(0.0, float(tolerance)))
    return max_refinement_extent_m(entity) <= 0.0 or (width_m <= limit and height_m <= limit)


def _valid_sample_dimensions(sample_dimensions):
    if isinstance(sample_dimensions, (list, tuple)) and len(sample_dimensions) == 2:
        try:
            width, height = int(sample_dimensions[0]), int(sample_dimensions[1])
        except (TypeError, ValueError):
            return None
        if width >= 3 and height >= 3 and width % 2 == 1 and height % 2 == 1:
            return width, height
    return None


def _requested_footprint_m(parent_entity, bounds):
    parent_bounds = parent_entity.get("bounds") or {}
    parent_width = max(1e-12, float(parent_bounds["max_x"]) - float(parent_bounds["min_x"]))
    parent_height = max(1e-12, float(parent_bounds["max_y"]) - float(parent_bounds["min_y"]))
    width_m, height_m = map_physical_dimensions_m(parent_entity)
    return (
        max(MIN_REFINED_EXTENT_M, width_m * abs(float(bounds["max_x"]) - float(bounds["min_x"])) / parent_width),
        max(MIN_REFINED_EXTENT_M, height_m * abs(float(bounds["max_y"]) - float(bounds["min_y"])) / parent_height),
    )


def _planned_tile(level, bounds, width_m, height_m, sample_dimensions=None):
    """Stand-in for a map that is planned but not made: enough of it to plan the next step from."""
    columns, lines = _valid_sample_dimensions(sample_dimensions) or refinement_sample_dimensions(level, width_m, height_m)
    return {
        "id": None,
        "map_detail_level": int(level),
        "bounds": {"type": "bbox", **{key: float(bounds[key]) for key in ("min_x", "max_x", "min_y", "max_y")}},
        "heightmap_model": {
            "region_width_m": float(width_m), "region_height_m": float(height_m),
            "sample_grid": {"width": int(columns), "height": int(lines)},
        },
    }


def _contains(outer, inner):
    slack_x = 1e-9 * max(1.0, abs(float(outer["max_x"]) - float(outer["min_x"])))
    slack_y = 1e-9 * max(1.0, abs(float(outer["max_y"]) - float(outer["min_y"])))
    return (
        float(outer["min_x"]) <= float(inner["min_x"]) + slack_x and float(outer["max_x"]) >= float(inner["max_x"]) - slack_x
        and float(outer["min_y"]) <= float(inner["min_y"]) + slack_y and float(outer["max_y"]) >= float(inner["max_y"]) - slack_y
    )


def _reusable_refinement(world_model, parent_entity, bounds, level):
    """A map of ``level`` already refined from ``parent_entity`` that holds ``bounds``: the smallest one."""
    parent_id = parent_entity.get("id")
    entities = getattr(getattr(world_model, "loader", None), "entities", None)
    if not parent_id or not isinstance(entities, dict):
        return None
    best, best_area = None, math.inf
    for candidate in entities.values():
        if (
            not isinstance(candidate, dict)
            or candidate.get("refinement_parent_map_id") != parent_id
            or candidate.get("location_role") != "map_refinement_region"
            or int(candidate.get("map_detail_level", 0) or 0) != int(level)
        ):
            continue
        held = candidate.get("bounds") or {}
        if held.get("type") != "bbox" or not _contains(held, bounds):
            continue
        area = (float(held["max_x"]) - float(held["min_x"])) * (float(held["max_y"]) - float(held["min_y"]))
        if area < best_area:
            best, best_area = candidate, area
    return best


def _intermediate_bounds(parent_entity, bounds, width_m, height_m, level, target_level, limit_m):
    """Footprint of the in-between map of ``level`` on the way from ``parent_entity`` to ``bounds``.

    Cell sizes go down the levels in equal ratios; the map is centred on the
    target, has its proportions and stays inside its parent.
    """
    parent_bounds = parent_entity["bounds"]
    parent_world_width = float(parent_bounds["max_x"]) - float(parent_bounds["min_x"])
    parent_world_height = float(parent_bounds["max_y"]) - float(parent_bounds["min_y"])
    parent_width_m, parent_height_m = map_physical_dimensions_m(parent_entity)
    extent = max(width_m, height_m)
    parent_cell = map_cell_size_m(parent_entity) or max(parent_width_m, parent_height_m) / 512.0
    target_grid = refinement_sample_dimensions(target_level, width_m, height_m)
    target_cell = max(width_m / max(1, target_grid[0] - 1), height_m / max(1, target_grid[1] - 1))
    steps = max(2, int(target_level) - int(map_scale_level(parent_entity)))
    cell = parent_cell * (target_cell / parent_cell) ** (1.0 / steps)
    planned = cell * ((513 if level <= 2 else 385) - 1)
    lowest = LEVEL_MAX_EXTENT_M[level + 1] / INTERMEDIATE_BAND_INSET
    highest = limit_m * INTERMEDIATE_BAND_INSET
    planned = min(max(planned, lowest), highest) if highest >= lowest else highest
    aspect = max(0.75, min(2.0, width_m / max(1e-9, height_m)))
    tile_width_m = planned if aspect >= 1.0 else planned * aspect
    tile_height_m = tile_width_m / aspect
    world_width = min(parent_world_width, tile_width_m / max(1e-9, parent_width_m) * parent_world_width)
    world_height = min(parent_world_height, tile_height_m / max(1e-9, parent_height_m) * parent_world_height)
    center_x = 0.5 * (float(bounds["min_x"]) + float(bounds["max_x"]))
    center_y = 0.5 * (float(bounds["min_y"]) + float(bounds["max_y"]))
    min_x = max(float(parent_bounds["min_x"]), min(float(parent_bounds["max_x"]) - world_width, center_x - 0.5 * world_width))
    min_y = max(float(parent_bounds["min_y"]), min(float(parent_bounds["max_y"]) - world_height, center_y - 0.5 * world_height))
    return {"min_x": min_x, "max_x": min_x + world_width, "min_y": min_y, "max_y": min_y + world_height}


def next_refinement_step(world_model, parent_entity, bounds, *, sample_dimensions=None, allow_intermediate=True):
    """The first map to make (or reuse) on the way from ``parent_entity`` to ``bounds``.

    Returns ``{"level", "bounds", "final", "reuse", "width_m", "height_m"}``:
    ``final`` when it is the requested map itself, ``reuse`` an existing map
    that serves as the in-between one.  Raises ``RefinementStepError``.
    """
    bounds = clamp_refinement_bounds(parent_entity, bounds)
    if max(map_physical_dimensions_m(parent_entity)) <= 0.0:
        # A map without a physical size has no scale to go by: one level under its own number.
        level = min(MAX_DETAIL_LEVEL, int(parent_entity.get("map_detail_level", 0) or 0) + 1)
        return {"level": level, "bounds": bounds, "final": True, "reuse": None, "width_m": 0.0, "height_m": 0.0}
    width_m, height_m = _requested_footprint_m(parent_entity, bounds)
    extent = max(width_m, height_m)
    scale = map_scale_level(parent_entity)
    limit = max_refinement_extent_m(parent_entity)
    name = parent_entity.get("name") or parent_entity.get("id") or "this map"
    if limit <= 0.0:
        raise RefinementStepError("finest", f"{name} is at the finest level: {MIN_TERRAIN_SAMPLE_SPACING_M * 100:.0f} cm a sample.")
    next_level = min(MAX_DETAIL_LEVEL, scale + 1)
    label = detail_level_spec(next_level)["label"]
    if extent > limit * (1.0 + 1e-9):
        raise RefinementStepError(
            "too_large",
            f"{format_extent(extent)} across is too large for a {label} of {name}: at most {format_extent(limit)}.",
            max_extent_m=limit, level=next_level,
        )
    target_level = next_level if scale >= 6 else footprint_level(extent)
    if target_level <= next_level:
        custom = _valid_sample_dimensions(sample_dimensions)
        if custom is not None:
            cell = max(width_m / (custom[0] - 1), height_m / (custom[1] - 1))
            parent_cell = map_cell_size_m(parent_entity)
            if parent_cell > 0.0 and cell > MIN_TERRAIN_SAMPLE_SPACING_M * 1.05 and parent_cell / cell < MIN_REFINEMENT_STEP:
                raise RefinementStepError(
                    "too_large",
                    f"{format_extent(cell)} a sample is not {MIN_REFINEMENT_STEP:g} times finer than {name} ({format_extent(parent_cell)}).",
                    max_extent_m=limit, level=next_level,
                )
        return {"level": next_level, "bounds": bounds, "final": True, "reuse": None, "width_m": width_m, "height_m": height_m}
    if not allow_intermediate:
        raise RefinementStepError(
            "too_small",
            f"{format_extent(extent)} across is {detail_level_spec(target_level)['label']} scale: {name} needs a {label} in between.",
            level=target_level,
        )
    existing = _reusable_refinement(world_model, parent_entity, bounds, next_level)
    if existing is not None:
        held = existing["bounds"]
        held_width_m, held_height_m = _requested_footprint_m(parent_entity, held)
        return {
            "level": next_level, "bounds": {key: float(held[key]) for key in ("min_x", "max_x", "min_y", "max_y")},
            "final": False, "reuse": existing, "width_m": held_width_m, "height_m": held_height_m,
        }
    between = _intermediate_bounds(parent_entity, bounds, width_m, height_m, next_level, target_level, limit)
    between_width_m, between_height_m = _requested_footprint_m(parent_entity, between)
    return {"level": next_level, "bounds": between, "final": False, "reuse": None, "width_m": between_width_m, "height_m": between_height_m}


def describe_refinement(world_model, parent_entity, bounds, *, sample_dimensions=None):
    """What refining ``bounds`` from ``parent_entity`` would do, without doing it.

    ``{"status": "ok", "level", "label", "steps", "reused", "extent_m"}``
    (``steps`` maps to generate, the requested one included), or
    ``{"status": "too_large" | "finest", "message", "max_extent_m"}``.
    """
    parent = parent_entity
    steps = reused = 0
    try:
        for _guard in range(MAX_DETAIL_LEVEL + 2):
            step = next_refinement_step(world_model, parent, bounds, sample_dimensions=sample_dimensions)
            if step["reuse"] is not None:
                reused += 1
            else:
                steps += 1
            if step["final"]:
                return {
                    "status": "ok", "level": step["level"], "label": detail_level_spec(step["level"])["label"],
                    "steps": steps, "reused": reused, "extent_m": max(step["width_m"], step["height_m"]),
                }
            parent = _planned_tile(step["level"], step["bounds"], step["width_m"], step["height_m"])
    except RefinementStepError as error:
        return {"status": error.reason, "message": str(error), "max_extent_m": error.max_extent_m, "level": error.level}
    return {"status": "too_large", "message": "No chain of maps reaches this footprint.", "max_extent_m": None, "level": None}


def generate_refined_region(
    world_model,
    parent_entity,
    bounds,
    *,
    seed_suffix="regional-refinement",
    focus_occurrence_id=None,
    terrain_only=False,
    sample_dimensions=None,
    feedback_iterations=None,
    storage_root=None,
    progress_callback=None,
    allow_intermediate=True,
):
    """Refine ``bounds`` of ``parent_entity`` into a map one level finer, and return it.

    The level is the scale of the footprint (``LEVEL_MAX_EXTENT_M``).  A
    footprint too large to be a level finer than its parent is refused
    (``RefinementStepError``, with the largest that works).  One that is
    more than a level finer gets the maps in between first: each one level
    down, centred on the target, stored like any refinement and used again
    by the next request that falls inside it.  ``allow_intermediate=False``
    refuses that case instead (rebuilding a stored map in place).
    """
    plan = describe_refinement(world_model, parent_entity, bounds, sample_dimensions=sample_dimensions)
    total = max(1, int(plan.get("steps") or 1))
    made = 0

    def staged(index, label):
        if not callable(progress_callback):
            return None

        def report(progress, detail, preview=None):
            share = (index + max(0.0, min(1.0, float(progress or 0.0)))) / total
            text = str(detail or "Refining regional map")
            progress_callback(share, f"{label} ({index + 1} of {total}): {text}" if total > 1 else text, preview)
        return report

    parent = parent_entity
    for _guard in range(MAX_DETAIL_LEVEL + 2):
        step = next_refinement_step(
            world_model, parent, bounds, sample_dimensions=sample_dimensions, allow_intermediate=allow_intermediate,
        )
        label = detail_level_spec(step["level"])["label"]
        if step["final"]:
            return _generate_refined_step(
                world_model, parent, step["bounds"], level=step["level"], seed_suffix=seed_suffix,
                focus_occurrence_id=focus_occurrence_id, terrain_only=terrain_only, sample_dimensions=sample_dimensions,
                feedback_iterations=feedback_iterations, storage_root=storage_root,
                progress_callback=staged(min(made, total - 1), label),
            )
        if step["reuse"] is not None:
            parent = world_model.get_entity(step["reuse"]["id"]) or step["reuse"]
            continue
        logger.info(
            "[RegionalRefinement] In-between map "
            f"level={step['level']} parent={parent.get('id')} extent_m={max(step['width_m'], step['height_m']):.1f}"
        )
        parent = _generate_refined_step(
            world_model, parent, step["bounds"], level=step["level"], seed_suffix=seed_suffix,
            feedback_iterations=feedback_iterations, storage_root=storage_root,
            progress_callback=staged(min(made, total - 1), label),
        )
        made += 1
    raise RefinementStepError("too_small", "No chain of maps reaches this footprint.")


def _stable_region_id(parent_id, level, bounds):
    token = f"{parent_id}|{level}|{bounds['min_x']:.6f}|{bounds['max_x']:.6f}|{bounds['min_y']:.6f}|{bounds['max_y']:.6f}"
    digest = hashlib.sha1(token.encode("utf-8")).hexdigest()[:10]
    # Parentage belongs in refinement_parent_map_id. Embedding the complete
    # ancestral id here grows filenames at every zoom level and eventually
    # exceeds Windows path limits during raster-bundle creation.
    return f"refined_lod{level}_{digest}"


def _resolved_storage_root(storage_root, world_model):
    """Where the world's rasters live: the given root, else next to the ontology, else the project."""
    if storage_root is None:
        ontology_path = getattr(
            getattr(world_model, "loader", None),
            "ontology_path",
            None,
        )
        storage_root = (
            Path(ontology_path).resolve().parent.parent
            if ontology_path
            else Path(__file__).resolve().parents[2]
        )
    return Path(storage_root).resolve()


def _generate_refined_step(
    world_model,
    parent_entity,
    bounds,
    *,
    level,
    seed_suffix="regional-refinement",
    focus_occurrence_id=None,
    terrain_only=False,
    sample_dimensions=None,
    feedback_iterations=None,
    storage_root=None,
    progress_callback=None,
):
    """One refinement of ``bounds`` at ``level``; ``generate_refined_region`` decides which."""
    started_at = time.perf_counter()
    last_stage_at = started_at

    def emit_progress(progress, detail, preview=None):
        if not callable(progress_callback):
            return
        try:
            progress_callback(
                max(0.0, min(1.0, float(progress))),
                str(detail or "Refining regional map"),
                preview,
            )
        except Exception:
            # Progress reporting is diagnostic and must never invalidate a
            # scientifically valid refinement.
            return

    def report_stage(stage, *, progress=None, message=None, preview=None, **details):
        nonlocal last_stage_at
        now = time.perf_counter()
        detail_text = " ".join(
            f"{key}={value}" for key, value in details.items()
            if value is not None
        )
        logger.info(
            "[RegionalRefinement] "
            f"stage={stage} step_s={now - last_stage_at:.2f} "
            f"total_s={now - started_at:.2f} {detail_text}".rstrip()
        )
        last_stage_at = now
        if progress is not None:
            emit_progress(progress, message or str(stage).replace("_", " ").capitalize(), preview)

    parent_heightmap = parent_entity.get("heightmap_model") if isinstance(parent_entity, dict) else None
    parent_grid = parent_heightmap.get("sample_grid") if isinstance(parent_heightmap, dict) else None
    parent_rows = parent_grid.get("rows") if isinstance(parent_grid, dict) else None
    if not parent_rows:
        raise ValueError("The parent map has no generated heightfield to refine")

    parent_bounds = parent_entity.get("bounds") or {}
    if parent_bounds.get("type") != "bbox":
        raise ValueError("Regional refinement currently requires rectangular parent bounds")
    bounds = clamp_refinement_bounds(parent_entity, bounds)
    parent_width = max(1e-9, float(parent_bounds["max_x"]) - float(parent_bounds["min_x"]))
    parent_height = max(1e-9, float(parent_bounds["max_y"]) - float(parent_bounds["min_y"]))
    u0 = (float(bounds["min_x"]) - float(parent_bounds["min_x"])) / parent_width
    u1 = (float(bounds["max_x"]) - float(parent_bounds["min_x"])) / parent_width
    v0 = (float(bounds["min_y"]) - float(parent_bounds["min_y"])) / parent_height
    v1 = (float(bounds["max_y"]) - float(parent_bounds["min_y"])) / parent_height
    parent_source = parent_heightmap.get("source_uv_bounds") if isinstance(parent_heightmap.get("source_uv_bounds"), dict) else {}
    parent_source_u0 = float(parent_source.get("min_u", 0.0) or 0.0)
    parent_source_u1 = float(parent_source.get("max_u", 1.0) or 1.0)
    parent_source_v0 = float(parent_source.get("min_v", 0.0) or 0.0)
    parent_source_v1 = float(parent_source.get("max_v", 1.0) or 1.0)
    source_u0 = parent_source_u0 + (parent_source_u1 - parent_source_u0) * u0
    source_u1 = parent_source_u0 + (parent_source_u1 - parent_source_u0) * u1
    source_v0 = parent_source_v0 + (parent_source_v1 - parent_source_v0) * v0
    source_v1 = parent_source_v0 + (parent_source_v1 - parent_source_v0) * v1
    level = max(1, min(MAX_DETAIL_LEVEL, int(level)))
    region_id = _stable_region_id(parent_entity["id"], level, bounds)
    map_seed = f"{parent_heightmap.get('map_seed') or parent_entity.get('id')}:{seed_suffix}:{region_id}"

    parent_physical_width_m, parent_physical_height_m = map_physical_dimensions_m(parent_entity)
    estimated_width_m = max(
        MIN_REFINED_EXTENT_M,
        parent_physical_width_m * abs(u1 - u0),
    )
    estimated_height_m = max(
        MIN_REFINED_EXTENT_M,
        parent_physical_height_m * abs(v1 - v0),
    )
    # Macroregions and regions are commonly displayed across most of a
    # 1600-1920 px viewport.  A 257-column source exposes 6-8 px cells and
    # forces both contours and tributaries into visibly blocky geometry.
    # Resolve the scientifically meaningful first two regional levels more
    # densely; deeper footprints are physically smaller and remain adequately
    # sampled at 385 columns. Plot and Survey levels instead stop at the
    # physical 10 cm terrain-data floor. Smaller loose detail is a sparse
    # object/biosphere concern rather than denser elevation storage.
    sample_width, sample_height = refinement_sample_dimensions(
        level,
        estimated_width_m,
        estimated_height_m,
    )
    if isinstance(sample_dimensions, (list, tuple)) and len(sample_dimensions) == 2:
        try:
            requested_width, requested_height = (
                int(sample_dimensions[0]),
                int(sample_dimensions[1]),
            )
        except (TypeError, ValueError):
            requested_width = requested_height = 0
        if (
            requested_width >= 3
            and requested_height >= 3
            and requested_width % 2 == 1
            and requested_height % 2 == 1
        ):
            sample_width = requested_width
            sample_height = requested_height
    report_stage(
        "request_resolved",
        progress=0.03,
        message=f"Preparing LOD {level} regional boundary conditions",
        parent=parent_entity.get("id"),
        level=level,
        requested_bounds={key: round(float(bounds[key]), 6) for key in ("min_x", "max_x", "min_y", "max_y")},
        local_uv=(round(u0, 6), round(u1, 6), round(v0, 6), round(v1, 6)),
        source_uv=(round(source_u0, 6), round(source_u1, 6), round(source_v0, 6), round(source_v1, 6)),
        estimated_m=(round(estimated_width_m, 1), round(estimated_height_m, 1)),
        grid=f"{sample_width}x{sample_height}",
    )
    sea_level = parent_heightmap.get("sea_level_m")
    min_parent = float(parent_heightmap.get("min_elevation_m", -5000.0) or -5000.0)
    max_parent = float(parent_heightmap.get("max_elevation_m", 5000.0) or 5000.0)
    relief_span = max(1.0, max_parent - min_parent)
    estimated_extent_m = max(
        parent_physical_width_m * abs(u1 - u0),
        parent_physical_height_m * abs(v1 - v0),
        MIN_REFINED_EXTENT_M,
    )
    nominal_amplitude = {1: 620.0, 2: 240.0, 3: 65.0, 4: 12.0, 5: 2.5, 6: 0.24, 7: 0.07}[level]
    amplitude = min(nominal_amplitude, max(0.03, estimated_extent_m * 0.025))
    # The root id is retained for ancestry/audit only.  All live geographic
    # inputs below come from the immediate parent snapshot.  LOD1's parent is
    # normally the canonical planet, so its production tectonic model is a
    # legitimate parent input; deeper children must inherit the compact
    # tectonic snapshot instead of re-evaluating the root height function.
    root_planet_id = _root_planet_id(world_model, parent_entity)
    root_planet = parent_entity
    parent_level = int(parent_entity.get("map_detail_level", 0) or 0)
    root_heightmap = parent_heightmap
    root_terrain = parent_entity.get("terrain_seed_model") or {}
    parent_tectonic_model = parent_entity.get("tectonic_model")
    indexed_parent_tectonic_model = _ensure_heightmap_tectonic_model(
        parent_tectonic_model
    )
    production_tectonic_model = (
        _production_tectonic_height_model(parent_entity)
        if parent_level == 0
        else None
    )
    regional_tectonic_model = _regional_tectonic_context(
        root_planet,
        {
            "min_u": source_u0,
            "max_u": source_u1,
            "min_v": source_v0,
            "max_v": source_v1,
        },
        sample_width=sample_width,
        sample_height=sample_height,
    )
    production_height_min = None
    production_height_max = None
    production_height_sum = 0.0
    production_height_count = 0
    production_residual_min = None
    production_residual_max = None
    production_residual_sum = 0.0
    root_crater_model = parent_entity.get("crater_model")
    planet_circumference = float(
        parent_heightmap.get("planet_circumference_m")
        or (root_heightmap or {}).get("circumference_m")
        or parent_heightmap.get("circumference_m", 40_075_000.0)
        or 40_075_000.0
    )
    region_width_m = (
        parent_physical_width_m * abs(u1 - u0)
        if parent_physical_width_m > 0.0
        else planet_circumference * abs(source_u1 - source_u0)
    )
    region_height_m = (
        parent_physical_height_m * abs(v1 - v0)
        if parent_physical_height_m > 0.0
        else planet_circumference * 0.5 * abs(source_v1 - source_v0)
    )
    region_aspect = max(0.5, min(3.0, region_width_m / max(1e-9, region_height_m)))
    detail_band = _refinement_detail_band(
        parent_physical_width_m,
        parent_physical_height_m,
        parent_rows,
        region_width_m,
        region_height_m,
        sample_width,
        sample_height,
    )
    emit_progress(0.05, "Sampling parent relief and tectonic boundary conditions")
    production_residual_grid = _build_production_residual_grid(
        parent_rows,
        root_terrain,
        root_heightmap,
        production_tectonic_model,
        parent_u0=u0,
        parent_u1=u1,
        parent_v0=v0,
        parent_v1=v1,
        source_u0=source_u0,
        source_u1=source_u1,
        source_v0=source_v0,
        source_v1=source_v1,
        sample_width=sample_width,
        sample_height=sample_height,
    )

    parent_coastal_context = _parent_coastal_context(
        parent_entity,
        ((u0 + u1) * 0.5, (v0 + v1) * 0.5),
    )
    # Basins much larger than the selected footprint belong to the inherited
    # relief field.  Reconstruct only impacts whose curved form can be read at
    # this level; smaller descendants will inherit the large basin's local
    # slope without reintroducing a flat analytic sector.
    maximum_explicit_crater_m = max(region_width_m, region_height_m) * 1.6
    explicit_root_crater_model = _crater_model_for_explicit_scale(
        root_crater_model, maximum_explicit_crater_m, global_catalog=True,
    )
    parent_crater_model = _crater_model_for_explicit_scale(
        parent_heightmap.get("regional_crater_model"), maximum_explicit_crater_m,
    )
    global_crater_grid = None
    global_crater_index = None
    if isinstance(explicit_root_crater_model, dict) and explicit_root_crater_model.get("craters"):
        global_crater_grid = _global_crater_adjustment_grid(
            explicit_root_crater_model, parent_heightmap, len(parent_rows[0]), len(parent_rows),
        )
        global_crater_index = _crater_spatial_index(explicit_root_crater_model)
    parent_crater_grid = _local_crater_adjustment_grid(
        parent_crater_model, len(parent_rows[0]), len(parent_rows),
    )
    new_crater_model = _new_regional_crater_model(
        root_crater_model, map_seed, region_width_m, region_height_m,
        sample_width, sample_height, parent_heightmap,
    )
    new_crater_model = _condition_regional_craters_to_parent(
        new_crater_model,
        parent_rows,
        u0,
        u1,
        v0,
        v1,
        sea_level,
        (root_crater_model or {}).get("surface_morphology_preservation", 1.0),
        parent_wrap_x=bool(parent_heightmap.get("wrap_x", True)),
    )
    regional_crater_model = _combined_child_crater_model(
        parent_crater_model, new_crater_model, u0, u1, v0, v1,
        region_width_m, region_height_m,
    )
    emit_progress(
        0.08,
        "Resolving regional terrain, structural detail, and readable impacts",
        {
            "tectonic_model": regional_tectonic_model,
            "crater_model": regional_crater_model,
        },
    )
    rows = []
    inherited_rows = []
    parent_topology_rows = []
    parent_wrap_x = bool(parent_heightmap.get("wrap_x", True))
    parent_mountain_rows = (
        ((parent_heightmap.get("surface_masks") or {}).get("mountain_rows") or [])
        if isinstance(parent_heightmap, dict)
        else []
    )
    if not parent_mountain_rows:
        # Older saved maps are upgraded in memory through the normal
        # derivative path. This keeps refinement compatible without treating
        # the whole selected rectangle as mountainous.
        upgraded_parent = refresh_heightmap_derivatives(
            parent_heightmap,
            tectonic_model=indexed_parent_tectonic_model,
            inherited_sea_level_m=sea_level if str(parent_heightmap.get("coverage") or "") != "full_planet" else None,
        )
        parent_mountain_rows = ((upgraded_parent.get("surface_masks") or {}).get("mountain_rows") or [])
    structural_heightmap_context = {
        "source_uv_bounds": {
            "min_u": source_u0,
            "max_u": source_u1,
            "min_v": source_v0,
            "max_v": source_v1,
        }
    }
    orogenic_strike = math.radians(dominant_structural_strike_degrees(
        (root_planet or {}).get("tectonic_model"),
        structural_heightmap_context,
        str((root_heightmap or {}).get("map_seed") or parent_heightmap.get("map_seed") or ""),
    ))
    # Keep residual geometry on one stable physical-coordinate phase across
    # the chain.  Using the child map id here made every zoom level roll a new
    # unrelated ridge pattern, even when it was sampling the same place.  The
    # child map seed remains available for child-only objects and persistence;
    # terrain wavelengths use the canonical world seed so inherited ridges and
    # newly resolved folds stay spatially registered.
    root_surface_seed = str(
        ((parent_entity or {}).get("world_gen_seed") or {}).get("map_seed")
        or ((parent_entity or {}).get("world_gen_seed") or {}).get("resolved_map_seed")
        or (root_heightmap or {}).get("root_map_seed")
        or (root_heightmap or {}).get("map_seed")
        or parent_heightmap.get("map_seed")
        or parent_entity.get("id")
    )
    broad_wavelength_m = (
        detail_band["broad_wavelength_m"] if detail_band else MIN_TERRAIN_PROCESS_WAVELENGTH_M
    )
    fine_wavelength_m = (
        detail_band["fine_wavelength_m"] if detail_band else MIN_TERRAIN_PROCESS_WAVELENGTH_M
    )
    fold_wavelength_m = (
        detail_band["fold_wavelength_m"] if detail_band else MIN_TERRAIN_PROCESS_WAVELENGTH_M
    )
    orogen_influence_sum = 0.0
    orogen_influence_max = 0.0
    mountain_belt_envelope_sum = 0.0
    mountain_belt_envelope_max = 0.0
    orogen_localized_cell_count = 0
    orogen_profile_sums = {
        "core_influence": 0.0,
        "arc_influence": 0.0,
        "shoulder_influence": 0.0,
        "forearc_influence": 0.0,
    }
    ridge_phase = seed_range(
        root_surface_seed,
        "regional-orogen-ridge-valley-phase",
        0.0,
        math.tau,
    )
    orogen_structural_grid = _build_orogen_structural_grid(
        indexed_parent_tectonic_model,
        source_u0,
        source_u1,
        source_v0,
        source_v1,
        sample_width=sample_width,
        sample_height=sample_height,
    )
    tile_frame = _tile_belt_frame(
        orogen_structural_grid, source_u0, source_u1, source_v0, source_v1, planet_circumference,
    )

    def partial_heightmap_preview(completed_rows):
        preview_rows = [list(values) for values in rows]
        preview_rows.extend(
            [[None] * sample_width for _index in range(max(0, sample_height - len(preview_rows)))]
        )
        return {
            "status": "regional_heightmap_building",
            "projection": "local_equirectangular",
            "coverage": "regional_patch",
            "wrap_x": False,
            "wrap_y": False,
            "sea_level_m": sea_level,
            "min_elevation_m": min_parent,
            "max_elevation_m": max_parent,
            "preview_completed_rows": completed_rows,
            "sample_grid": {
                "width": sample_width,
                "height": sample_height,
                "wrap_x": False,
                "wrap_y": False,
                "rows": preview_rows,
            },
        }

    crater_detail = None
    if global_crater_grid is not None or parent_crater_grid is not None or isinstance(new_crater_model, dict):
        crater_parent_wrap = bool(parent_heightmap.get("wrap_x", True))

        def crater_detail(source_u, source_v, local_u, local_v, global_u, global_v):
            adjustment = 0.0
            if global_crater_grid is not None:
                adjustment += _crater_height_adjustment_m(
                    global_u, global_v, explicit_root_crater_model, global_crater_index,
                ) - _sample_bilinear(global_crater_grid, source_u, source_v, wrap_x=crater_parent_wrap)
            if parent_crater_grid is not None:
                adjustment += _local_crater_adjustment_m(source_u, source_v, parent_crater_model) - _sample_bilinear(
                    parent_crater_grid, source_u, source_v, wrap_x=False,
                )
            if isinstance(new_crater_model, dict):
                adjustment += _local_crater_adjustment_m(local_u, local_v, new_crater_model)
            return adjustment

    vectorised_relief = VECTORISED_REGIONAL_RELIEF and production_residual_grid is not None
    if vectorised_relief:
        relief = _synthesize_regional_relief_arrays(
            parent_rows=parent_rows,
            parent_heightmap=parent_heightmap,
            parent_mountain_rows=parent_mountain_rows,
            parent_wrap_x=parent_wrap_x,
            production_residual_grid=production_residual_grid,
            orogen_structural_grid=orogen_structural_grid,
            sample_width=sample_width,
            sample_height=sample_height,
            u0=u0, u1=u1, v0=v0, v1=v1,
            source_u0=source_u0, source_u1=source_u1,
            source_v0=source_v0, source_v1=source_v1,
            sea_level=sea_level,
            relief_span=relief_span,
            amplitude=amplitude,
            level=level,
            detail_band=detail_band,
            root_surface_seed=root_surface_seed,
            planet_circumference=planet_circumference,
            broad_wavelength_m=broad_wavelength_m,
            fine_wavelength_m=fine_wavelength_m,
            fold_wavelength_m=fold_wavelength_m,
            ridge_phase=ridge_phase,
            crater_detail=crater_detail,
            tile_frame=tile_frame,
            height_digits=height_decimals(min(region_width_m / max(1, sample_width - 1), region_height_m / max(1, sample_height - 1))),
        )
        rows = relief["rows"]
        inherited_rows = relief["inherited_rows"]
        parent_topology_rows = relief["topology_rows"]
        production_height_min = relief["production_height_min"]
        production_height_max = relief["production_height_max"]
        production_height_sum = relief["production_height_sum"]
        production_height_count = relief["production_height_count"]
        production_residual_min = relief["production_residual_min"]
        production_residual_max = relief["production_residual_max"]
        production_residual_sum = relief["production_residual_sum"]
        mountain_belt_envelope_sum = relief["mountain_belt_envelope_sum"]
        mountain_belt_envelope_max = relief["mountain_belt_envelope_max"]
        orogen_influence_sum = relief["orogen_influence_sum"]
        orogen_influence_max = relief["orogen_influence_max"]
        orogen_localized_cell_count = relief["orogen_localized_cell_count"]
        orogen_profile_sums.update(relief["orogen_profile_sums"])
        emit_progress(
            0.32,
            "Regional relief resolved",
            {
                "heightmap_model": partial_heightmap_preview(sample_height),
                "tectonic_model": regional_tectonic_model,
                "crater_model": regional_crater_model,
            },
        )

    # Per-cell reference path (fallback when no production residual grid
    # exists); it is skipped entirely when the whole-grid path ran.
    for y in range(0 if vectorised_relief else sample_height):
        local_v = y / max(1, sample_height - 1)
        source_v = v0 + (v1 - v0) * local_v
        row = []
        inherited_row = []
        topology_row = []
        for x in range(sample_width):
            local_u = x / max(1, sample_width - 1)
            source_u = u0 + (u1 - u0) * local_u
            inherited = _sample_bicubic(
                parent_rows, source_u, source_v,
                wrap_x=bool(parent_heightmap.get("wrap_x", True)),
            )
            inherited_row.append(inherited)
            topology_row.append(_parent_topology_certainty(
                parent_rows,
                source_u,
                source_v,
                sea_level,
                wrap_x=bool(parent_heightmap.get("wrap_x", True)),
            ))
            global_u = source_u0 + (source_u1 - source_u0) * local_u
            global_v = source_v0 + (source_v1 - source_v0) * local_v
            if production_residual_grid is not None:
                # B-spline, not bilinear: the compact residual grid is
                # coarse, and bilinear facets showed as grid-aligned
                # rectangles and stair-stepped coasts in hillshade.
                production_residual = _sample_bicubic(
                    production_residual_grid["residual_rows"],
                    local_u,
                    local_v,
                    wrap_x=False,
                )
                production_height = inherited + production_residual
            else:
                production_height = _production_height_at(
                    global_u,
                    global_v,
                    root_terrain,
                    root_heightmap,
                    production_tectonic_model,
                )
                production_residual = (
                    float(production_height) - inherited
                    if production_height is not None
                    else 0.0
                )
            if production_height is not None:
                production_height_min = production_height if production_height_min is None else min(production_height_min, production_height)
                production_height_max = production_height if production_height_max is None else max(production_height_max, production_height)
                production_height_sum += production_height
                production_height_count += 1
                production_residual_min = production_residual if production_residual_min is None else min(production_residual_min, production_residual)
                production_residual_max = production_residual if production_residual_max is None else max(production_residual_max, production_residual)
                production_residual_sum += production_residual
            world_x_m = global_u * planet_circumference
            world_y_m = global_v * planet_circumference * 0.5
            broad = (
                fractal_noise_m(
                    root_surface_seed, "regional-broad-relief", world_x_m, world_y_m,
                    broad_wavelength_m, octaves=2, gain=0.50,
                    period_x_m=planet_circumference,
                )
                if detail_band else 0.0
            )
            fine = (
                fractal_noise_m(
                    root_surface_seed, "regional-fine-relief", world_x_m, world_y_m,
                    fine_wavelength_m, octaves=2, gain=0.44,
                    period_x_m=planet_circumference,
                )
                if detail_band else 0.0
            )
            mountain_factor = 0.0
            if parent_mountain_rows:
                mountain_factor = _clamp(_sample_bicubic(
                    parent_mountain_rows,
                    source_u,
                    source_v,
                    wrap_x=parent_wrap_x,
                ), 0.0, 1.0)
            inherited_ruggedness, structural_anchor = _parent_structure_context(
                parent_rows,
                source_u,
                source_v,
                relief_span,
                wrap_x=parent_wrap_x,
            )
            orogen_context = _sample_orogen_structural_grid(
                orogen_structural_grid,
                global_u,
                global_v,
            )
            orogen_factor = orogen_context["mountain_influence"]
            mountain_belt_envelope = _clamp(
                float(orogen_context.get("mountain_belt_envelope", 0.0) or 0.0),
                0.0,
                1.0,
            )
            mountain_belt_envelope_sum += mountain_belt_envelope
            mountain_belt_envelope_max = max(
                mountain_belt_envelope_max,
                mountain_belt_envelope,
            )
            if sea_level is not None:
                if inherited <= float(sea_level):
                    orogen_factor = 0.0
                else:
                    # A convergent boundary can sit just offshore. Require
                    # the parent to already resolve land before its uplift
                    # can authorize a child mountain field.
                    land_gate = _clamp(
                        (inherited - float(sea_level))
                        / max(1.0, relief_span * 0.08),
                        0.0,
                        1.0,
                    )
                    orogen_factor *= 0.30 + 0.70 * land_gate
            orogen_influence_sum += orogen_factor
            orogen_influence_max = max(orogen_influence_max, orogen_factor)
            for profile_key in orogen_profile_sums:
                orogen_profile_sums[profile_key] += float(
                    orogen_context.get(profile_key, 0.0) or 0.0
                )
            if orogen_factor >= 0.18:
                orogen_localized_cell_count += 1
            # Plains receive only low-amplitude rolling and microrelief.
            # Folded ridge relief exists exclusively inside the inherited,
            # height-derived mountain morphology mask.
            #
            # The plains baseline used to be 0.018/0.008 -- against a Site
            # level's ~12 m amplitude budget that is well under half a metre
            # of total relief, which reads as a perfectly flat, contourless
            # tile (and, since a flat child feeds _parent_structure_context's
            # ruggedness/anchor measurement at the next level down, it also
            # self-perpetuates: a flat parent can never re-authorize texture
            # in its own children). Raised so non-mountain terrain keeps
            # genuine, visible rolling microrelief at every detail level
            # while mountain terrain still stands out clearly above it.
            # The parent mountain mask remains the strongest authorization
            # when it exists. The production orogen field supplies the missing
            # connected-system support where the planetary mask is too sparse
            # to survive downsampling.
            structural_factor = max(
                mountain_factor
                * inherited_ruggedness
                * structural_anchor
                * (0.30 + 0.70 * mountain_belt_envelope),
                orogen_factor
                * (0.34 + 0.66 * inherited_ruggedness)
                * (0.48 + 0.52 * structural_anchor)
                * (0.28 + 0.72 * mountain_belt_envelope),
            )
            belt_uplift = (
                amplitude
                * structural_factor
                * mountain_belt_envelope
                * (0.28 if level == 1 else 0.10)
            )
            fold_relief = (
                branching_mountain_relief_m(
                    root_surface_seed,
                    "regional-branching-mountains",
                    world_x_m,
                    world_y_m,
                    fold_wavelength_m,
                    period_x_m=planet_circumference,
                ) if detail_band else 0.0
            )
            ridge_valley_signal = 0.0
            if mountain_belt_envelope > 0.08 and detail_band:
                # Keep the active boundary as the placement anchor, but do
                # not let a single cross-range sine paint parallel stripes
                # across the whole tile.  The helper adds along-belt warping
                # and branching relief while remaining spatially registered
                # to the immediate parent's orogen geometry.
                ridge_valley_signal = _boundary_anchored_ridge_valley_signal(
                    root_surface_seed,
                    world_x_m,
                    world_y_m,
                    fold_wavelength_m,
                    orogen_context,
                    ridge_phase,
                    period_x_m=planet_circumference,
                    tile_frame=tile_frame,
                )
            ridge_valley_amplitude = _clamp(
                0.18
                + float(orogen_context.get("core_influence", 0.0) or 0.0) * 0.28
                + float(orogen_context.get("arc_influence", 0.0) or 0.0) * 0.18
                + float(orogen_context.get("shoulder_influence", 0.0) or 0.0) * 0.08
                - float(orogen_context.get("forearc_influence", 0.0) or 0.0) * 0.10,
                0.08,
                0.52,
            )
            detail = (
                broad * amplitude * (0.06 + structural_factor * 0.07)
                + fine * amplitude * (0.035 + structural_factor * 0.05)
                + belt_uplift
                + fold_relief * amplitude * structural_factor * (
                    0.30
                    + float(orogen_context.get("core_influence", 0.0) or 0.0) * 0.10
                )
                + ridge_valley_signal * amplitude * structural_factor * ridge_valley_amplitude
            )
            # The production planetary tectonic/geographic field is the
            # authoritative broad signal. Regional procedural detail may add
            # wavelengths below the parent support, but it may not replace the
            # actual plate/deformation response with a standalone noise field.
            detail += production_residual
            if sea_level is not None and inherited < float(sea_level) and level >= 4:
                detail *= 0.22
            # Coastal detail is added later by a parent-conditioned landform
            # generator.  Generic near-datum noise creates implausible cliffs,
            # barriers and tidal flats without sediment or forcing controls.
            if global_crater_grid is not None:
                exact_crater = _crater_height_adjustment_m(
                    global_u, global_v, explicit_root_crater_model, global_crater_index,
                )
                inherited_crater = _sample_bilinear(
                    global_crater_grid, source_u, source_v,
                    wrap_x=bool(parent_heightmap.get("wrap_x", True)),
                )
                detail += exact_crater - inherited_crater
            if parent_crater_grid is not None:
                detail += _local_crater_adjustment_m(source_u, source_v, parent_crater_model) - _sample_bilinear(
                    parent_crater_grid, source_u, source_v,
                    wrap_x=False,
                )
            if isinstance(new_crater_model, dict):
                detail += _local_crater_adjustment_m(local_u, local_v, new_crater_model)
            edge_distance = min(local_u, 1.0 - local_u, local_v, 1.0 - local_v)
            edge_fade = _clamp(edge_distance / PARENT_EDGE_FADE_FRACTION, 0.0, 1.0)
            edge_fade = edge_fade * edge_fade * (3.0 - 2.0 * edge_fade)
            detail *= edge_fade
            row.append(round(inherited + detail, height_decimals(min(region_width_m / max(1, sample_width - 1), region_height_m / max(1, sample_height - 1)))))
        rows.append(row)
        inherited_rows.append(inherited_row)
        parent_topology_rows.append(topology_row)
        if y == sample_height - 1 or y % max(1, sample_height // 12) == 0:
            fraction = (y + 1) / max(1, sample_height)
            emit_progress(
                0.09 + fraction * 0.23,
                f"Refining regional relief row {y + 1} of {sample_height}",
                {
                    "heightmap_model": partial_heightmap_preview(y + 1),
                    "tectonic_model": regional_tectonic_model,
                    "crater_model": regional_crater_model,
                },
            )

    rows, detail_centering = _center_detail_at_parent_scale(
        rows,
        inherited_rows,
        sea_level=sea_level,
        spacing_x_m=region_width_m / max(1, sample_width - 1),
        spacing_y_m=region_height_m / max(1, sample_height - 1),
        parent_spacing_m=float((detail_band or {}).get("parent_sample_spacing_m") or 0.0),
        topology_rows=parent_topology_rows,
    )
    rows, coastline_shift, coastline_refinement = _refine_coastline(
        rows, parent_rows,
        parent_uv=(u0, u1, v0, v1),
        source_uv=(source_u0, source_u1, source_v0, source_v1),
        sea_level=sea_level,
        parent_wrap_x=bool(parent_heightmap.get("wrap_x", True)),
        seed=root_surface_seed,
        level=level,
        planet_circumference_m=planet_circumference,
        parent_spacing_m=float((detail_band or {}).get("parent_sample_spacing_m") or 0.0),
        spacing_m=max(region_width_m / max(1, sample_width - 1), region_height_m / max(1, sample_height - 1)),
    )
    boundary_inflow = _parent_boundary_inflow(
        parent_heightmap,
        parent_rows,
        bool(parent_heightmap.get("wrap_x", True)),
        sea_level,
        rows,
        {"min_u": source_u0, "max_u": source_u1, "min_v": source_v0, "max_v": source_v1},
        parent_physical_width_m,
        parent_physical_height_m,
        parent_climate_grid=(parent_entity.get("water_cycle_model") or {}).get("climate_grid"),
        parent_water_cycle=parent_entity.get("water_cycle_model"),
    )
    rows, fluvial_dissection = _fluvial_dissection(
        rows,
        inherited_rows,
        sea_level=sea_level,
        spacing_x_m=region_width_m / max(1, sample_width - 1),
        spacing_y_m=region_height_m / max(1, sample_height - 1),
        parent_spacing_m=float((detail_band or {}).get("parent_sample_spacing_m") or 0.0),
        level=level,
        inflow=boundary_inflow,
    )
    rows, floodplains = _floodplain_flattening(
        rows,
        sea_level=sea_level,
        spacing_x_m=region_width_m / max(1, sample_width - 1),
        spacing_y_m=region_height_m / max(1, sample_height - 1),
        parent_spacing_m=float((detail_band or {}).get("parent_sample_spacing_m") or 0.0),
        level=level,
        inflow=boundary_inflow,
    )
    rows, relief_limiter = _scale_appropriate_relief(
        rows,
        sea_level,
        region_width_m,
        region_height_m,
        parent_coastal_context,
    )
    # Landforms that become complete at this level (volcanic arcs, ...):
    # physically sized residuals the parent-height contract bounds around.
    rows_before_landforms = rows
    rows, landform_residual, regional_landforms = apply_regional_landforms(
        rows,
        inherited_rows,
        level=level,
        sea_level=sea_level,
        source_bounds={"min_u": source_u0, "max_u": source_u1, "min_v": source_v0, "max_v": source_v1},
        spacing_x_m=region_width_m / max(1, sample_width - 1),
        spacing_y_m=region_height_m / max(1, sample_height - 1),
        parent_spacing_m=float((detail_band or {}).get("parent_sample_spacing_m") or 0.0),
        root_planet=parent_entity if parent_level == 0 else None,
        parent_entity=parent_entity,
        inflow=boundary_inflow,
        storage_root=_resolved_storage_root(storage_root, world_model),
    )
    contract_reference_rows = [
        [float(inherited) + float(extra) + float(shore) for inherited, extra, shore in zip(inherited_row, residual_row, shore_row)]
        for inherited_row, residual_row, shore_row in zip(inherited_rows, landform_residual, coastline_shift)
    ]
    contract_topology_rows = _topology_without_landform_crossings(parent_topology_rows, rows_before_landforms, rows, sea_level)
    min_elevation = min(min(row) for row in rows)
    max_elevation = max(max(row) for row in rows)
    ice_parent = ((parent_heightmap.get("surface_masks") or {}).get("ice_rows") or [])
    ice_rows = [[False for _x in range(sample_width)] for _y in range(sample_height)]
    ice_margin = {"applied": False}
    if ice_parent:
        ice_rows, ice_margin = _regional_ice_mask(
            ice_parent,
            rows,
            parent_wrap_x=bool(parent_heightmap.get("wrap_x", True)),
            parent_bounds=(u0, u1, v0, v1),
            parent_spacing_m=float((detail_band or {}).get("parent_sample_spacing_m") or 0.0),
            spacing_m=max(region_width_m / max(1, sample_width - 1), region_height_m / max(1, sample_height - 1)),
            seed=seed_int(map_seed, f"regional_ice_margin_lod{level}"),
            source_uv=(source_u0, source_u1, source_v0, source_v1),
            planet_circumference_m=planet_circumference,
            noise_seed=root_surface_seed,
            level=level,
        )

    heightmap = {
        "status": "regional_heightmap_refined",
        "model_version": "hierarchical-regional-heightmap-v6",
        "map_seed": map_seed,
        "map_detail_level": level,
        "refinement_detail_band": {
            key: round(float(value), 4)
            for key, value in (detail_band or {}).items()
        },
        "mountain_detail_localization": "parent_ridge_valley_plus_inherited_orogen_belt_geometry",
        "regional_landforms": regional_landforms,
        "detail_level_spec": detail_level_spec(level),
        "projection": "local_equirectangular",
        "coverage": "regional_patch",
        "wrap_x": False,
        "wrap_y": False,
        "width_px": 4096,
        "height_px": max(2048, int(round(4096 / region_aspect))),
        "radius_m": parent_heightmap.get("radius_m"),
        "circumference_m": region_width_m,
        "planet_circumference_m": planet_circumference,
        "region_width_m": region_width_m,
        "region_height_m": region_height_m,
        "equator_resolution_m_per_px": region_width_m / max(1, sample_width - 1),
        "sample_spacing_x_m": region_width_m / max(1, sample_width - 1),
        "sample_spacing_y_m": region_height_m / max(1, sample_height - 1),
        "minimum_terrain_sample_spacing_m": MIN_TERRAIN_SAMPLE_SPACING_M,
        "minimum_terrain_process_wavelength_m": MIN_TERRAIN_PROCESS_WAVELENGTH_M,
        "minimum_refinement_extent_m": MIN_REFINED_EXTENT_M,
        "sea_level_m": sea_level,
        "min_elevation_m": round(min_elevation, 1),
        "max_elevation_m": round(max_elevation, 1),
        "source_uv_bounds": {"min_u": source_u0, "max_u": source_u1, "min_v": source_v0, "max_v": source_v1},
        "sample_grid": {"width": sample_width, "height": sample_height, "wrap_x": False, "wrap_y": False, "rows": rows},
        "surface_masks": {"ice_rows": ice_rows},
        "regional_crater_model": regional_crater_model,
        "scale_appropriate_relief": relief_limiter,
        "fluvial_dissection": fluvial_dissection,
        "floodplains": floodplains,
        "boundary_inflow": boundary_inflow,
        "detail_centering": detail_centering,
        "coastline_refinement": coastline_refinement,
        "ice_margin": ice_margin,
        "continuous_surface_recipe": {
            "model": "production_tectonic_heightfield_plus_parent_anchored_branching_geology_v4",
            "coordinate_frame": "immediate_parent_physical_metres",
            "root_seed": root_surface_seed,
            "broad_wavelength_m": round(broad_wavelength_m, 3),
            "fine_wavelength_m": round(fine_wavelength_m, 3),
            "fold_wavelength_m": round(fold_wavelength_m, 3),
            "fold_strike_degrees": round(math.degrees(orogenic_strike) % 180.0, 3),
            "mountain_localization": "parent_mountain_mask_plus_inherited_orogen_belt_geometry",
            "orogen_structural_field": {
                "source": "immediate_parent.tectonic_model.orogen_system_model",
                "gate": "convergent_uplift_volcanic_and_restrained_transform_influence",
                "ridge_valley_axis": "inherited_boundary_geometry_with_parent_structural_anchor",
                "ridge_valley_phase_seed": root_surface_seed,
                "sampling_grid": {
                    "width": int((orogen_structural_grid or {}).get("width", 0) or 0),
                    "height": int((orogen_structural_grid or {}).get("height", 0) or 0),
                },
            },
            "mountain_belt_envelope": {
                "source": "immediate_parent.tectonic_model.boundary_geometry",
                "mean": round(
                    mountain_belt_envelope_sum / max(1, sample_width * sample_height),
                    6,
                ),
                "maximum": round(mountain_belt_envelope_max, 6),
            },
            "parent_role": "broad_elevation_topology_and_mountain_extent_contract",
            "production_tectonic_source": "heightmap._wave_height_with_mature_tectonics_compact_child_scale_residual",
            "production_residual_sampling": {
                "model": (production_residual_grid or {}).get("source", "unavailable"),
                "width": int((production_residual_grid or {}).get("width", 0) or 0),
                "height": int((production_residual_grid or {}).get("height", 0) or 0),
            },
            "detail_persisted_in_elevation_grid": True,
        },
        "refinement": {
            "parent_map_id": parent_entity["id"],
            "root_planet_id": _root_planet_id(world_model, parent_entity),
            "level": level,
            "method": "continuous_physical_coordinate_geology_with_parent_envelope",
            "physical_footprint_m": {"width": region_width_m, "height": region_height_m},
            "minimum_extent_m": MIN_REFINED_EXTENT_M,
            "terrain_resolution_floor_m": MIN_TERRAIN_SAMPLE_SPACING_M,
            "terrain_process_wavelength_floor_m": MIN_TERRAIN_PROCESS_WAVELENGTH_M,
            "inherited_crater_morphology": bool(global_crater_grid is not None or parent_crater_grid is not None),
            "new_crater_count": len((new_crater_model or {}).get("craters") or []),
            "parent_height_contract": "pending_post_process_enforcement",
            "edge_detail_contract": {
                "mode": "smoothstep_residual_fade_to_immediate_parent",
                "fade_width_fraction": PARENT_EDGE_FADE_FRACTION,
                "boundary_residual": "zero_at_child_patch_edge",
            },
        },
    }
    heightmap["production_tectonic_response"] = {
        "status": "sampled" if production_height_count else "inherited_orogen_only",
        "source_mode": (
            "parent_production_heightfield"
            if parent_level == 0
            else "immediate_parent_tectonic_snapshot"
        ),
        "source_model_status": (
            (production_tectonic_model or parent_tectonic_model or {}).get("status")
        ),
        "sample_count": production_height_count,
        "height_range_m": [
            round(production_height_min, 3),
            round(production_height_max, 3),
        ] if production_height_count else None,
        "parent_residual_range_m": [
            round(production_residual_min, 3),
            round(production_residual_max, 3),
        ] if production_height_count else None,
        "parent_residual_mean_m": round(
            production_residual_sum / max(1, production_height_count),
            3,
        ) if production_height_count else None,
        "residual_sampling": {
            "model": (production_residual_grid or {}).get(
                "source",
                "direct_child_samples",
            ),
            "width": int((production_residual_grid or {}).get("width", 0) or 0),
            "height": int((production_residual_grid or {}).get("height", 0) or 0),
        },
        "orogen_inheritance": {
            "source": "immediate_parent.tectonic_model.orogen_system_model",
            "localized_cell_count": orogen_localized_cell_count,
            "localized_cell_fraction": round(
                orogen_localized_cell_count / max(1, sample_width * sample_height),
                6,
            ),
            "mean_mountain_influence": round(
                orogen_influence_sum / max(1, sample_width * sample_height),
                6,
            ),
            "maximum_mountain_influence": round(orogen_influence_max, 6),
            "profile_means": {
                key: round(value / max(1, sample_width * sample_height), 6)
                for key, value in orogen_profile_sums.items()
            },
            "status": (
                "sampled_from_parent_production_orogen_systems"
                if production_height_count
                else "inherited_from_immediate_parent_orogen_systems"
            ),
        },
    }
    heightmap = refresh_heightmap_derivatives(
        heightmap,
        tectonic_model=indexed_parent_tectonic_model,
        inherited_sea_level_m=sea_level,
        sea_mask=_sea_mask(heightmap, parent_entity, sea_level),
    )
    report_stage(
        "heightfield_ready",
        progress=0.38,
        message="Regional relief and terrain derivatives ready",
        preview={
            "heightmap_model": heightmap,
            "tectonic_model": regional_tectonic_model,
            "crater_model": regional_crater_model,
        },
        elevation_m=(heightmap.get("min_elevation_m"), heightmap.get("max_elevation_m")),
        source_uv=heightmap.get("source_uv_bounds"),
    )
    if terrain_only:
        spec = detail_level_spec(level)
        region = {
            "id": region_id,
            "name": f"{parent_entity.get('name') or parent_entity['id']} — {spec['label']} Terrain Patch",
            "pretty_name": f"{parent_entity.get('name') or parent_entity['id']} — {spec['label']} Terrain Patch",
            "type": "location",
            "_dataset": "locations",
            "location_class": "generated_region",
            "location_role": "map_refinement_region",
            "parent_location": parent_entity["id"],
            "parents": [parent_entity["id"]],
            "refinement_parent_map_id": parent_entity["id"],
            "refinement_root_planet_id": _root_planet_id(world_model, parent_entity),
            "refinement_revision": 1,
            "refinement_seed_suffix": str(seed_suffix),
            "map_detail_level": level,
            "map_detail_profile": spec,
            "map_status": "regional_terrain_preview_generated",
            "bounds": {"type": "bbox", **{key: float(bounds[key]) for key in ("min_x", "max_x", "min_y", "max_y")}},
            "coords": {"type": "point", "x": (float(bounds["min_x"]) + float(bounds["max_x"])) * 0.5, "y": (float(bounds["min_y"]) + float(bounds["max_y"])) * 0.5},
            "map_canvas_width_px": heightmap["width_px"],
            "map_canvas_height_px": heightmap["height_px"],
            "heightmap_model": heightmap,
            "terrain_seed_model": copy.deepcopy(parent_entity.get("terrain_seed_model") or {}),
            "atmosphere_model": copy.deepcopy(parent_entity.get("atmosphere_model") or {}),
            "atmosphere_visual_model": copy.deepcopy(parent_entity.get("atmosphere_visual_model")),
            "surface_palette": copy.deepcopy(parent_entity.get("surface_palette")),
            "display_color": copy.deepcopy(parent_entity.get("display_color")),
            "world_gen_seed": copy.deepcopy(parent_entity.get("world_gen_seed") or {}),
            "constituents": [],
            "tags": ["generated_map_refinement", "terrain_preview", f"map_lod_{level}", spec["id"]],
        }
        loader = world_model.loader
        loader.persist_entity(region)
        parent = world_model.get_entity(parent_entity["id"]) or parent_entity
        children = list(parent.get("constituents") or [])
        if region_id not in children:
            children.append(region_id)
            parent["constituents"] = children
            loader.persist_entity(parent)
        emit_progress(
            0.99,
            "Regional terrain preview persisted",
            {"heightmap_model": heightmap, "tectonic_model": regional_tectonic_model},
        )
        return region
    terrain = copy.deepcopy(parent_entity.get("terrain_seed_model") or {})
    hydrology = terrain.setdefault("hydrology", {})
    liquid_water_possible = bool(hydrology.get("liquid_water_possible", sea_level is not None))
    hydrology["liquid_water_possible"] = liquid_water_possible
    hydrology["drainage_enabled"] = bool(hydrology.get("drainage_enabled", liquid_water_possible))
    atmosphere = parent_entity.get("atmosphere_model") or {}
    seed = copy.deepcopy(parent_entity.get("world_gen_seed") or {})
    water_cycle = _regional_water_cycle(
        terrain, heightmap, atmosphere=atmosphere, seed=seed, planet_id=region_id,
        parent_climate_model=parent_entity.get("water_cycle_model"), parent_heightmap=parent_entity.get("heightmap_model"),
    )
    report_stage(
        "initial_hydrology_ready",
        progress=0.50,
        message="Initial regional climate and drainage ready",
        preview={
            "heightmap_model": heightmap,
            "tectonic_model": regional_tectonic_model,
            "water_cycle_model": water_cycle,
        },
        rivers=len(water_cycle.get("rivers") or []),
        lakes=len(water_cycle.get("lakes") or []),
    )
    # Regional refinement previously stopped here: rivers were solved on a
    # depression-filled DEM and then drawn over the unchanged relief.  Match
    # the production planetary route with two bounded climate-landscape
    # feedback passes so routed channels incise ravines and the final network
    # is solved against the modified topography.
    # root_planet may be a LazyEntity (world/persistent_ontology_store.py) --
    # deep-copying it directly pickles its internal hydration RLock and
    # crashes. .copy() is the hydrate-then-plain-dict method it provides for
    # exactly this; on an already-plain dict it's an ordinary shallow copy.
    regional_planet_context = copy.deepcopy(root_planet.copy()) if isinstance(root_planet, dict) else {}
    # Global crater coordinates are not local patch coordinates. Regional
    # crater relief was already resolved explicitly above.
    regional_planet_context.pop("crater_model", None)
    feedback_history = []
    surface_evolution = {}
    default_feedback_pass_count = 2 if level <= 3 else (1 if level <= 5 else 0)
    if feedback_iterations is None:
        feedback_pass_count = default_feedback_pass_count
    else:
        try:
            feedback_pass_count = max(0, min(default_feedback_pass_count, int(feedback_iterations)))
        except (TypeError, ValueError):
            feedback_pass_count = default_feedback_pass_count
    final_relief_limiter_applied = False
    for iteration in range(1, feedback_pass_count + 1):
        surface_evolution = derive_surface_evolution_model(
            planet=regional_planet_context,
            terrain=terrain,
            heightmap=heightmap,
            water_cycle=water_cycle,
            atmosphere=atmosphere,
        )
        report_stage(
            f"surface_evolution_{iteration}_ready",
            progress=0.52 + iteration * 0.06,
            message=f"Landscape evolution pass {iteration} ready",
            preview={"heightmap_model": heightmap, "water_cycle_model": water_cycle},
            status=surface_evolution.get("status"),
            dominant=surface_evolution.get("dominant_process"),
        )
        feedback_history.append({
            "iteration": iteration,
            "status": surface_evolution.get("status"),
            "dominant_process": surface_evolution.get("dominant_process"),
            "process_means": surface_evolution.get("process_means"),
            "channel_incision": surface_evolution.get("channel_incision"),
        })
        evolved_heightmap = surface_evolution.get("heightmap") if isinstance(surface_evolution, dict) else None
        if surface_evolution.get("status") != "surface_evolution_seeded" or not isinstance(evolved_heightmap, dict):
            break
        heightmap = _edge_faded_evolution(
            heightmap, evolved_heightmap, sea_level=sea_level,
            parent_spacing_m=float((detail_band or {}).get("parent_sample_spacing_m") or 0.0),
            solver_cells=_solver_cells(heightmap, water_cycle),
        )
        # The last feedback result was formerly solved once before and once
        # after relief limiting. Only the post-limiter solution was retained.
        # Apply the limiter before that last solve so its scientific output is
        # unchanged while one complete climate/drainage pass is removed.
        if iteration == feedback_pass_count:
            heightmap = _limit_heightmap_relief(
                heightmap,
                parent_coastal_context,
            )
            heightmap = _fit_final_channel_beds(heightmap, sea_level=sea_level, inflow=boundary_inflow, route_rows=rows)
            heightmap = refresh_heightmap_derivatives(
                heightmap,
                tectonic_model=indexed_parent_tectonic_model,
                inherited_sea_level_m=sea_level,
                sea_mask=_sea_mask(heightmap, parent_entity, sea_level),
            )
            final_relief_limiter_applied = True
        previous_water_cycle = water_cycle
        water_cycle = _regional_water_cycle(
            terrain, heightmap, atmosphere=atmosphere, seed=seed, planet_id=region_id,
            parent_climate_model=parent_entity.get("water_cycle_model"), parent_heightmap=parent_entity.get("heightmap_model"),
            previous_regional_model=previous_water_cycle,
        )
        report_stage(
            f"hydrology_feedback_{iteration}_ready",
            progress=0.55 + iteration * 0.06,
            message=f"Climate and drainage feedback pass {iteration} ready",
            preview={"heightmap_model": heightmap, "water_cycle_model": water_cycle},
            rivers=len(water_cycle.get("rivers") or []),
            lakes=len(water_cycle.get("lakes") or []),
        )
    if isinstance(surface_evolution, dict):
        surface_evolution["feedback_iterations"] = feedback_history
        surface_evolution["coupling"] = "scale_appropriate_bounded_regional_climate_landscape_feedback"
        surface_evolution["requested_feedback_iteration_count"] = feedback_pass_count
    if not final_relief_limiter_applied:
        heightmap = _limit_heightmap_relief(
            heightmap,
            parent_coastal_context,
        )
        heightmap = _fit_final_channel_beds(heightmap, sea_level=sea_level, inflow=boundary_inflow, route_rows=rows)
        heightmap = refresh_heightmap_derivatives(
            heightmap,
            tectonic_model=indexed_parent_tectonic_model,
            inherited_sea_level_m=sea_level,
            sea_mask=_sea_mask(heightmap, parent_entity, sea_level),
        )
        previous_water_cycle = water_cycle
        water_cycle = _regional_water_cycle(
            terrain, heightmap, atmosphere=atmosphere, seed=seed, planet_id=region_id,
            parent_climate_model=parent_entity.get("water_cycle_model"), parent_heightmap=parent_entity.get("heightmap_model"),
            previous_regional_model=previous_water_cycle,
        )
    report_stage(
        "landscape_feedback_ready",
        progress=0.70,
        message="Regional landscape and drainage feedback complete",
        preview={"heightmap_model": heightmap, "water_cycle_model": water_cycle},
        iterations=len(feedback_history),
        rivers=len(water_cycle.get("rivers") or []),
        lakes=len(water_cycle.get("lakes") or []),
    )
    # Stellar and satellite context is inherited data.  A refinement must not
    # query the world model for the root's live orbital neighbourhood while
    # regenerating a child.
    stellar_parent = copy.deepcopy(parent_entity.get("stellar_environment_model"))
    satellites = copy.deepcopy(parent_entity.get("satellite_context") or [])
    heightmap, pre_coastal_topology = stabilize_regional_coastal_topology(
        heightmap,
        detail_level=level,
    )
    if pre_coastal_topology.get("flipped_cell_count", 0):
        heightmap = refresh_heightmap_derivatives(
            heightmap,
            tectonic_model=indexed_parent_tectonic_model,
            inherited_sea_level_m=sea_level,
            sea_mask=_sea_mask(heightmap, parent_entity, sea_level),
        )
        water_cycle = _regional_water_cycle(
            terrain, heightmap, atmosphere=atmosphere, seed=seed, planet_id=region_id,
            parent_climate_model=parent_entity.get("water_cycle_model"), parent_heightmap=parent_entity.get("heightmap_model"),
            previous_regional_model=water_cycle,
        )
    regional_context = {**(root_planet or {}), "id": region_id, "heightmap_model": heightmap, "satellites": satellites}
    coastal_model = derive_coastal_geomorphology_model(
        planet=regional_context,
        heightmap=heightmap,
        water_cycle=water_cycle,
        tectonic_model=(root_planet or {}).get("tectonic_model"),
        surface_evolution=surface_evolution,
        star=stellar_parent,
    )
    inherit_parent_coastal_context(
        coastal_model,
        parent_entity.get("coastal_geomorphology_model") or {},
    )
    heightmap, coastal_refinement = materialize_regional_coastal_landforms(
        heightmap,
        coastal_model,
        detail_level=level,
    )
    heightmap, topology_stabilization = stabilize_regional_coastal_topology(
        heightmap,
        detail_level=level,
    )
    heightmap = _limit_heightmap_relief(heightmap, parent_coastal_context)
    coastal_refinement["pre_materialization_topology_stabilization"] = pre_coastal_topology
    coastal_refinement["topology_stabilization"] = topology_stabilization
    coastal_refinement["post_materialization_relief_limiter"] = dict(
        heightmap.get("scale_appropriate_relief") or {}
    )
    if (
        pre_coastal_topology.get("flipped_cell_count", 0)
        or topology_stabilization.get("flipped_cell_count", 0)
    ):
        coastal_refinement["drainage_reconciliation_required"] = True
    # Every downstream process has now had its turn.  Re-assert the defining
    # hierarchical contract once, at the end, so their individually bounded
    # changes cannot add up to a replacement landscape.
    heightmap, parent_height_contract = _enforce_parent_height_contract(
        heightmap,
        contract_reference_rows,
        contract_topology_rows,
        amplitude,
    )
    refinement_audit = dict(heightmap.get("refinement") or {})
    refinement_audit["parent_height_contract"] = parent_height_contract
    heightmap["refinement"] = refinement_audit
    coastal_refinement["parent_height_contract"] = parent_height_contract
    report_stage(
        "coastal_refinement_ready",
        progress=0.79,
        message="Regional coasts and parent-edge continuity ready",
        preview={"heightmap_model": heightmap, "water_cycle_model": water_cycle},
        segments=len(coastal_model.get("segments") or []),
        changed_cells=(
            int(pre_coastal_topology.get("flipped_cell_count", 0) or 0)
            + int(topology_stabilization.get("flipped_cell_count", 0) or 0)
        ),
    )
    if (
        coastal_refinement.get("drainage_reconciliation_required")
        or parent_height_contract.get("changed_cell_count", 0)
    ):
        heightmap = refresh_heightmap_derivatives(
            heightmap,
            tectonic_model=indexed_parent_tectonic_model,
            inherited_sea_level_m=sea_level,
            sea_mask=_sea_mask(heightmap, parent_entity, sea_level),
        )
        # One final solve makes river/coast classification agree with the
        # restored parent topology.  This replaces stale drainage rather than
        # layering an additional landscape-evolution iteration on top.
        water_cycle = _regional_water_cycle(
            terrain,
            heightmap,
            atmosphere=atmosphere,
            seed=seed,
            planet_id=region_id,
            parent_climate_model=parent_entity.get("water_cycle_model"), parent_heightmap=parent_entity.get("heightmap_model"),
            previous_regional_model=water_cycle,
        )
        coastal_refinement["drainage_reconciliation_count"] = 1
        parent_height_contract["hydrology_reconciled"] = True
        coastal_model = derive_coastal_geomorphology_model(
            planet={**regional_context, "heightmap_model": heightmap},
            heightmap=heightmap,
            water_cycle=water_cycle,
            tectonic_model=(root_planet or {}).get("tectonic_model"),
            surface_evolution=surface_evolution,
            star=stellar_parent,
        )
        inherit_parent_coastal_context(
            coastal_model,
            parent_entity.get("coastal_geomorphology_model") or {},
        )
    parent_coast = parent_entity.get("coastal_geomorphology_model") or {}
    inherited_segments = []
    for segment in parent_coast.get("segments") or []:
        geometry = segment.get("geometry") or {}
        bbox = geometry.get("bbox_uv") or []
        intersects = False
        if len(bbox) >= 4:
            intersects = not (
                float(bbox[2]) < u0
                or float(bbox[0]) > u1
                or float(bbox[3]) < v0
                or float(bbox[1]) > v1
            )
        if not intersects:
            intersects = any(
                u0 <= float(point[0]) <= u1 and v0 <= float(point[1]) <= v1
                for point in geometry.get("points") or []
                if isinstance(point, (list, tuple)) and len(point) >= 2
            )
        if intersects:
            inherited_segments.append(segment.get("id"))
    coastal_model["parent_segment_ids"] = [segment_id for segment_id in inherited_segments if segment_id]
    coastal_model["regional_landform_materialization"] = coastal_refinement
    enrich_coastal_hydrology(water_cycle, coastal_model)
    heightmap["regional_surface_evolution"] = {
        "status": surface_evolution.get("status"),
        "model_version": surface_evolution.get("model_version"),
        "feedback_iteration_count": len(feedback_history),
        "channel_incision": surface_evolution.get("channel_incision"),
    }
    root_material_model = (
        parent_entity.get("natural_material_model")
        if isinstance(parent_entity, dict)
        and isinstance(parent_entity.get("natural_material_model"), dict)
        else {}
    )
    from simulations.world_gen.geochemical_placement import regional_material_inventory
    from simulations.world_gen.strata import planet_strata_seed
    root_material_model = regional_material_inventory(
        root_material_model,
        (root_planet or {}).get("geochemical_material_model") or {},
        {"min_u": source_u0, "max_u": source_u1,
         "min_v": source_v0, "max_v": source_v1},
    )
    regional_material_model = derive_regional_material_model(
        root_material_model,
        heightmap,
        water_cycle,
        surface_evolution,
        map_seed=map_seed,
        detail_level=level,
        tectonic_model=(root_planet or {}).get("tectonic_model"),
        source_uv_bounds={
            "min_u": source_u0, "max_u": source_u1,
            "min_v": source_v0, "max_v": source_v1,
        },
        root_map_seed=(
            ((root_planet or {}).get("heightmap_model") or {}).get("map_seed")
            or map_seed
        ),
        parent_regional_material_model=parent_entity.get(
            "regional_material_model"
        ),
        planet_seed=planet_strata_seed(root_planet or {}),
    )
    report_stage(
        "regional_materials_ready",
        progress=0.85,
        message="Selecting regional material occurrences",
        preview={"heightmap_model": heightmap, "water_cycle_model": water_cycle},
        occurrences=len(regional_material_model.get("occurrences") or []),
    )
    if focus_occurrence_id:
        regional_material_model["focus_occurrence_id"] = str(
            focus_occurrence_id
        )
        regional_material_model["focus_occurrence_preserved"] = any(
            str(occurrence.get("id") or "") == str(focus_occurrence_id)
            for occurrence in regional_material_model.get("occurrences") or []
            if isinstance(occurrence, dict)
        )
    persisted_surface_evolution = dict(surface_evolution)
    embedded_heightmap_removed = persisted_surface_evolution.pop("heightmap", None) is not None
    if embedded_heightmap_removed:
        persisted_surface_evolution["heightmap_reference"] = "heightmap_model"
    persisted_surface_evolution["persistence_compaction"] = {
        "embedded_heightmap_removed": embedded_heightmap_removed,
        "reason": "avoid_duplicate_regional_heightfield_storage",
    }
    truth_lineage = {
        "lineage_contract_version": "immediate-parent-snapshot-v2",
        "root_planet_id": _root_planet_id(world_model, parent_entity),
        "parent_map_id": parent_entity["id"],
        "parent_map_seed": str(parent_heightmap.get("map_seed") or ""),
        "parent_detail_level": parent_level,
        "parent_heightfield_fingerprint": str(
            parent_heightmap.get("source_heightfield_fingerprint")
            or _model_fingerprint(parent_heightmap.get("sample_grid"))
        ),
        "parent_tectonic_fingerprint": _model_fingerprint(
            parent_entity.get("tectonic_model")
        ),
        "parent_climate_fingerprint": _model_fingerprint(
            parent_entity.get("water_cycle_model")
        ),
        "parent_material_fingerprint": _model_fingerprint(
            parent_entity.get("material_heatmap_model")
            or parent_entity.get("regional_material_model")
            or parent_entity.get("natural_material_model")
        ),
        "regional_map_seed": map_seed,
        "source_uv_bounds": {
            "min_u": source_u0, "max_u": source_u1,
            "min_v": source_v0, "max_v": source_v1,
        },
        "regeneration_changes_truth": False,
        "focus_occurrence_id": (
            str(focus_occurrence_id) if focus_occurrence_id else None
        ),
        "edge_detail_fades_to_parent": True,
        "edge_detail_contract": {
            "mode": "smoothstep_residual_fade_to_immediate_parent",
            "fade_width_fraction": PARENT_EDGE_FADE_FRACTION,
            "boundary_residual": "zero_at_child_patch_edge",
        },
        "parent_height_contract": copy.deepcopy(parent_height_contract),
        "boundary_condition_contract": {
            "stellar_environment": "inherited_from_parent_snapshot",
            "atmosphere": "inherited_from_parent",
            "tectonic_provinces": "inherited_from_parent_snapshot",
            "sea_level": "inherited_from_parent",
            "climate": "parent_field_plus_zero_mean_detail_above_atmospheric_response_length",
            "material_inventory": "inherited_from_parent_snapshot_with_local_affinity_selection",
        },
    }
    material_distribution_seed = (
        ((root_planet or {}).get("heightmap_model") or {}).get("map_seed")
        or map_seed
    )
    heightmap["material_distribution_seed"] = str(material_distribution_seed)
    heightmap["generated_truth_lineage"] = copy.deepcopy(truth_lineage)
    water_cycle["generated_truth_lineage"] = copy.deepcopy(truth_lineage)
    regional_material_model["generated_truth_lineage"] = copy.deepcopy(truth_lineage)
    material_generation_context = {
        **(root_planet or {}),
        "id": region_id,
        "surface_evolution_model": surface_evolution,
        "crater_model": regional_crater_model or {},
    }
    storage_root = _resolved_storage_root(storage_root, world_model)
    surface_geomorphology_model = derive_surface_geomorphology_model(
        material_generation_context,
        heightmap=heightmap,
        water_cycle=water_cycle,
        surface_evolution=surface_evolution,
        tectonic_model=(root_planet or {}).get("tectonic_model"),
    )
    material_generation_context["surface_geomorphology_model"] = surface_geomorphology_model
    regolith_soil_model = derive_regolith_soil_model(
        material_generation_context,
        heightmap,
        water_cycle,
        surface_evolution,
        root_material_model,
        parent_soil_model=parent_entity.get("regolith_soil_model"),
        parent_window=(u0, u1, v0, v1),
    )
    regolith_soil_model["generated_truth_lineage"] = copy.deepcopy(truth_lineage)
    try:
        regional_strike_degrees = dominant_structural_strike_degrees(
            (root_planet or {}).get("tectonic_model"), heightmap, seed=map_seed,
        )
    except Exception:
        regional_strike_degrees = 0.0
    material_heatmap_model = generate_material_heatmap_model(
        material_generation_context,
        root_material_model,
        terrain,
        heightmap,
        atmosphere=atmosphere,
        water_cycle=water_cycle,
        surface_geomorphology=surface_geomorphology_model,
        output_root=storage_root / "assets" / "maps" / "material_heatmaps",
        storage_root=storage_root,
        parent_material_model=parent_entity.get("material_heatmap_model"),
        tectonic_model=(root_planet or {}).get("tectonic_model"),
        strike_degrees=regional_strike_degrees,
        occurrences=regional_material_model.get("occurrences"),
    )
    report_stage(
        "material_rasters_ready",
        progress=0.93,
        message="Regional material rasters ready",
        preview={
            "heightmap_model": heightmap,
            "water_cycle_model": water_cycle,
            "material_heatmap_model": material_heatmap_model,
        },
        layers=len(material_heatmap_model.get("layers") or []),
        bundle=(material_heatmap_model.get("composite_layer") or {}).get("raster_bundle_path"),
    )
    surface_exposure_model = derive_surface_exposure_model(
        material_generation_context,
        heightmap=heightmap,
        material_heatmap_model=material_heatmap_model,
        water_cycle=water_cycle,
        surface_evolution=surface_evolution,
        surface_geomorphology=surface_geomorphology_model,
    )
    true_color_model = derive_true_color_model(
        material_generation_context,
        heightmap=heightmap,
        natural_material_model=root_material_model,
        material_heatmap_model=material_heatmap_model,
        atmosphere=atmosphere,
        water_cycle=water_cycle,
        surface_evolution=surface_evolution,
        surface_exposure=surface_exposure_model,
        surface_geomorphology=surface_geomorphology_model,
    )
    report_stage(
        "surface_render_models_ready",
        progress=0.97,
        message="Surface exposure and true-color models ready",
        preview={
            "heightmap_model": heightmap,
            "water_cycle_model": water_cycle,
            "material_heatmap_model": material_heatmap_model,
        },
    )
    detail_contract = surface_detail_contract(heightmap)

    spec = detail_level_spec(level)
    existing_entities = getattr(getattr(world_model, "loader", None), "entities", {}) or {}
    sibling_revisions = [
        int(candidate.get("refinement_revision", 0) or 0)
        for candidate in existing_entities.values()
        if isinstance(candidate, dict)
        and candidate.get("refinement_parent_map_id") == parent_entity.get("id")
        and int(candidate.get("map_detail_level", 0) or 0) == level
        and candidate.get("id") != region_id
    ]
    previous_same_region = world_model.get_entity(region_id)
    previous_revision = int(previous_same_region.get("refinement_revision", 0) or 0) if isinstance(previous_same_region, dict) else 0
    refinement_revision = max([previous_revision, *sibling_revisions], default=0) + 1
    region = {
        "id": region_id,
        "name": f"{parent_entity.get('name') or parent_entity['id']} — {spec['label']} Patch",
        "pretty_name": f"{parent_entity.get('name') or parent_entity['id']} — {spec['label']} Patch",
        "type": "location",
        "_dataset": "locations",
        "location_class": "generated_region",
        "location_role": "map_refinement_region",
        "parent_location": parent_entity["id"],
        "parents": [parent_entity["id"]],
        "refinement_parent_map_id": parent_entity["id"],
        "refinement_root_planet_id": _root_planet_id(world_model, parent_entity),
        "refinement_revision": refinement_revision,
        "refinement_seed_suffix": str(seed_suffix),
        "map_detail_level": level,
        "map_detail_profile": spec,
        "map_status": "regional_refinement_generated",
        "bounds": {"type": "bbox", **{key: float(bounds[key]) for key in ("min_x", "max_x", "min_y", "max_y")}},
        "coords": {"type": "point", "x": (float(bounds["min_x"]) + float(bounds["max_x"])) * 0.5, "y": (float(bounds["min_y"]) + float(bounds["max_y"])) * 0.5},
        "map_canvas_width_px": heightmap["width_px"],
        "map_canvas_height_px": heightmap["height_px"],
        "heightmap_model": heightmap,
        "water_cycle_model": water_cycle,
        "tectonic_model": regional_tectonic_model,
        "geography_model": {
            "status": "regional_geography_sampled_from_production_heightmap",
            "source_heightmap_status": (root_heightmap or {}).get("status"),
            "source_heightmap_model_version": (root_heightmap or {}).get("model_version"),
            "source_uv_bounds": {
                "min_u": source_u0,
                "max_u": source_u1,
                "min_v": source_v0,
                "max_v": source_v1,
            },
            "land_ocean_contract": "inherited_parent_sea_level_and_production_heightfield",
            "surface_mask_contract": "inherited_parent_derived_surface_masks",
        },
        "coastal_geomorphology_model": coastal_model,
        "coastal_summary": coastal_summary(coastal_model),
        "surface_evolution_model": persisted_surface_evolution,
        "terrain_seed_model": terrain,
        "natural_material_model": copy.deepcopy(root_material_model),
        "regional_material_model": regional_material_model,
        "material_heatmap_model": material_heatmap_model,
        "surface_exposure_model": surface_exposure_model,
        "surface_geomorphology_model": surface_geomorphology_model,
        "regolith_soil_model": regolith_soil_model,
        "true_color_model": true_color_model,
        "regional_material_occurrences": list(
            regional_material_model.get("occurrences") or []
        ),
        "surface_detail_model": detail_contract,
        "generated_truth_lineage": copy.deepcopy(truth_lineage),
        "causal_provenance": copy.deepcopy(
            (root_planet or {}).get("causal_provenance")
            or (root_planet or {}).get("planetary_evolution_model", {}).get("causal_provenance")
            or {}
        ),
        "atmosphere_model": copy.deepcopy(atmosphere),
        "atmosphere_visual_model": copy.deepcopy(parent_entity.get("atmosphere_visual_model")),
        "stellar_environment_model": copy.deepcopy(
            parent_entity.get("stellar_environment_model")
        ),
        "satellite_context": copy.deepcopy(
            parent_entity.get("satellite_context") or []
        ),
        "surface_palette": copy.deepcopy(parent_entity.get("surface_palette")),
        "surface_weathering_model": copy.deepcopy(parent_entity.get("surface_weathering_model")),
        "display_color": copy.deepcopy(parent_entity.get("display_color")),
        "world_gen_seed": seed,
        "constituents": [],
        "tags": ["generated_map_refinement", f"map_lod_{level}", spec["id"]],
    }
    from simulations.world_gen.geochemical_placement import occurrence_entity
    occurrence_cards = [
        occurrence_entity(region_id, occurrence)
        for occurrence in region["regional_material_occurrences"]
        if isinstance(occurrence, dict) and occurrence.get("id")
    ]
    region["constituents"] = [card["id"] for card in occurrence_cards]
    loader = world_model.loader
    existing = world_model.get_entity(region_id)
    if isinstance(existing, dict):
        existing.update(region)
        region = existing
    loader.persist_entity(region)
    if occurrence_cards:
        if hasattr(loader, "persist_entities"):
            loader.persist_entities(occurrence_cards)
        else:
            for card in occurrence_cards:
                loader.persist_entity(card)
    parent = world_model.get_entity(parent_entity["id"]) or parent_entity
    children = list(parent.get("constituents") or [])
    if region_id not in children:
        children.append(region_id)
        parent["constituents"] = children
        loader.persist_entity(parent)
    report_stage(
        "persisted",
        progress=0.99,
        message="Regional refinement persisted",
        preview={
            "heightmap_model": heightmap,
            "tectonic_model": regional_tectonic_model,
            "crater_model": regional_crater_model,
            "water_cycle_model": water_cycle,
            "material_heatmap_model": material_heatmap_model,
        },
        entity=region_id,
        revision=refinement_revision,
        bounds=region.get("bounds"),
    )
    return region
