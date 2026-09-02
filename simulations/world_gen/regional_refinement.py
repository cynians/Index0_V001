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

from engine.logger import logger
from simulations.world_gen.heightmap import (
    _clamp, _crater_height_adjustment_m, _crater_spatial_index, _fbm_noise,
    _ensure_heightmap_tectonic_model, _heightmap_tectonic_model,
    _nearby_boundary_segments, _orogen_forcing_at, _wrapped_point_segment_distance,
    _wave_height,
    refresh_heightmap_derivatives,
)
from simulations.world_gen.geological_noise import branching_mountain_relief_m, fractal_noise_m
from simulations.world_gen.coastal_geomorphology import (
    coastal_summary,
    derive_coastal_geomorphology_model,
    enrich_coastal_hydrology,
    inherit_parent_coastal_context,
    materialize_regional_coastal_landforms,
    stabilize_regional_coastal_topology,
)
from simulations.world_gen.map_seed import seed_range
from simulations.world_gen.material_heatmaps import generate_material_heatmap_model
from simulations.world_gen.regional_materials import derive_regional_material_model
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
PARENT_EDGE_FADE_FRACTION = 0.055
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
        heightmap["sample_grid"] = {**grid, "rows": [[round(value, 3) for value in row] for row in limited]}
        heightmap["min_elevation_m"] = round(min(min(row) for row in limited), 3)
        heightmap["max_elevation_m"] = round(max(max(row) for row in limited), 3)
    heightmap["scale_appropriate_relief"] = audit
    return heightmap


def refinement_floor_reached(entity, tolerance=0.01):
    width_m, height_m = map_physical_dimensions_m(entity)
    if width_m <= 0.0 or height_m <= 0.0:
        return False
    limit = MIN_REFINED_EXTENT_M * (1.0 + max(0.0, float(tolerance)))
    return width_m <= limit and height_m <= limit


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
        best = {
            "score": score,
            "mountain_belt_envelope": _clamp(envelope * score, 0.0, 1.0),
            "mountain_belt_cross_range": signed_distance,
            "mountain_belt_axis_x": tangent_x / tangent_length,
            "mountain_belt_axis_y": tangent_y / tangent_length,
        }
    return {
        "mountain_belt_envelope": float((best or {}).get("mountain_belt_envelope", 0.0)),
        "mountain_belt_cross_range": float((best or {}).get("mountain_belt_cross_range", 0.0)),
        "mountain_belt_axis_x": float((best or {}).get("mountain_belt_axis_x", 0.0)),
        "mountain_belt_axis_y": float((best or {}).get("mountain_belt_axis_y", 0.0)),
    }


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
    return {
        key: _sample_bilinear(rows, u, v, wrap_x=False)
        for key, rows in (grid.get("channels") or {}).items()
    }


def _boundary_anchored_ridge_valley_signal(
    seed,
    x_m,
    y_m,
    wavelength_m,
    orogen_context,
    ridge_phase,
    *,
    period_x_m=None,
):
    """Build branching relief while retaining the parent belt's position.

    A single sine of cross-range is a useful tectonic cue but reads as evenly
    spaced stripes when it dominates a regional tile.  This combines a weak
    belt-anchored trunk with rotated branching noise and along-belt warping.
    The boundary-derived cross-range remains the placement anchor; the
    branching terms decide where ridges merge, split, and terminate.
    """
    wavelength = max(1.0, float(wavelength_m))
    axis_x = float(orogen_context.get("mountain_belt_axis_x", 0.0) or 0.0)
    axis_y = float(orogen_context.get("mountain_belt_axis_y", 0.0) or 0.0)
    axis_length = math.hypot(axis_x, axis_y)
    if axis_length < 1e-6:
        axis_x, axis_y = 1.0, 0.0
    else:
        axis_x /= axis_length
        axis_y /= axis_length
    along_m = float(x_m) * axis_x + float(y_m) * axis_y
    across_m = -float(x_m) * axis_y + float(y_m) * axis_x
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
    """
    grid = heightmap.get("sample_grid") if isinstance(heightmap, dict) else {}
    rows = grid.get("rows") if isinstance(grid, dict) else None
    if not rows or not inherited_rows or len(rows) != len(inherited_rows):
        return heightmap, {"status": "unavailable", "changed_cell_count": 0}
    sea = heightmap.get("sea_level_m")
    maximum_delta = max(0.03, float(detail_amplitude_m or 0.0) * 2.15)
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
            target_row.append(round(resolved, 3))
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
    return midpoint + raw * half_range


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


def _stable_region_id(parent_id, level, bounds):
    token = f"{parent_id}|{level}|{bounds['min_x']:.6f}|{bounds['max_x']:.6f}|{bounds['min_y']:.6f}|{bounds['max_y']:.6f}"
    digest = hashlib.sha1(token.encode("utf-8")).hexdigest()[:10]
    # Parentage belongs in refinement_parent_map_id. Embedding the complete
    # ancestral id here grows filenames at every zoom level and eventually
    # exceeds Windows path limits during raster-bundle creation.
    return f"refined_lod{level}_{digest}"


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
):
    started_at = time.perf_counter()
    last_stage_at = started_at

    def report_stage(stage, **details):
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
    level = min(MAX_DETAIL_LEVEL, int(parent_entity.get("map_detail_level", 0) or 0) + 1)
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
    for y in range(sample_height):
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
                production_residual = _sample_bilinear(
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
            row.append(round(inherited + detail, 2))
        rows.append(row)
        inherited_rows.append(inherited_row)
        parent_topology_rows.append(topology_row)

    rows, relief_limiter = _scale_appropriate_relief(
        rows,
        sea_level,
        region_width_m,
        region_height_m,
        parent_coastal_context,
    )
    min_elevation = min(min(row) for row in rows)
    max_elevation = max(max(row) for row in rows)
    ice_parent = ((parent_heightmap.get("surface_masks") or {}).get("ice_rows") or [])
    ice_rows = [[False for _x in range(sample_width)] for _y in range(sample_height)]
    if ice_parent:
        parent_wrap_x = bool(parent_heightmap.get("wrap_x", True))
        ice_coverage_rows = [[1.0 if value else 0.0 for value in row] for row in ice_parent]
        for y in range(sample_height):
            for x in range(sample_width):
                local_u = x / max(1, sample_width - 1)
                local_v = y / max(1, sample_height - 1)
                sample_u = u0 + (u1 - u0) * local_u
                sample_v = v0 + (v1 - v0) * local_v
                coverage = _sample_bilinear(
                    ice_coverage_rows, sample_u, sample_v, wrap_x=parent_wrap_x,
                )
                if 0.02 < coverage < 0.98:
                    edge_distance = min(local_u, 1.0 - local_u, local_v, 1.0 - local_v)
                    edge_fade = _clamp(edge_distance / PARENT_EDGE_FADE_FRACTION, 0.0, 1.0)
                    edge_fade = edge_fade * edge_fade * (3.0 - 2.0 * edge_fade)
                    boundary_noise = _fbm_noise(
                        map_seed, "regional_ice_margin",
                        local_u, local_v,
                        base_cells=18 + level * 5, octaves=3, gain=0.48,
                    )
                    # Child detail must converge exactly to the inherited mask
                    # at every patch edge.  Without this fade, an ice margin
                    # becomes a conspicuous rectangular or triangular seam.
                    coverage += boundary_noise * 0.12 * edge_fade
                ice_rows[y][x] = coverage >= 0.5

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
    )
    report_stage(
        "heightfield_ready",
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
        return region
    terrain = copy.deepcopy(parent_entity.get("terrain_seed_model") or {})
    hydrology = terrain.setdefault("hydrology", {})
    liquid_water_possible = bool(hydrology.get("liquid_water_possible", sea_level is not None))
    hydrology["liquid_water_possible"] = liquid_water_possible
    hydrology["drainage_enabled"] = bool(hydrology.get("drainage_enabled", liquid_water_possible))
    atmosphere = parent_entity.get("atmosphere_model") or {}
    seed = copy.deepcopy(parent_entity.get("world_gen_seed") or {})
    water_cycle = derive_water_cycle_model(
        terrain, heightmap, atmosphere=atmosphere, seed=seed, planet_id=region_id,
        parent_climate_model=parent_entity.get("water_cycle_model"),
    )
    report_stage(
        "initial_hydrology_ready",
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
        heightmap = evolved_heightmap
        # The last feedback result was formerly solved once before and once
        # after relief limiting. Only the post-limiter solution was retained.
        # Apply the limiter before that last solve so its scientific output is
        # unchanged while one complete climate/drainage pass is removed.
        if iteration == feedback_pass_count:
            heightmap = _limit_heightmap_relief(
                heightmap,
                parent_coastal_context,
            )
            heightmap = refresh_heightmap_derivatives(
                heightmap,
                tectonic_model=indexed_parent_tectonic_model,
                inherited_sea_level_m=sea_level,
            )
            final_relief_limiter_applied = True
        previous_water_cycle = water_cycle
        water_cycle = derive_water_cycle_model(
            terrain, heightmap, atmosphere=atmosphere, seed=seed, planet_id=region_id,
            parent_climate_model=parent_entity.get("water_cycle_model"),
            previous_regional_model=previous_water_cycle,
        )
        report_stage(
            f"hydrology_feedback_{iteration}_ready",
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
        heightmap = refresh_heightmap_derivatives(
            heightmap,
            tectonic_model=indexed_parent_tectonic_model,
            inherited_sea_level_m=sea_level,
        )
        previous_water_cycle = water_cycle
        water_cycle = derive_water_cycle_model(
            terrain, heightmap, atmosphere=atmosphere, seed=seed, planet_id=region_id,
            parent_climate_model=parent_entity.get("water_cycle_model"),
            previous_regional_model=previous_water_cycle,
        )
    report_stage(
        "landscape_feedback_ready",
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
        )
        water_cycle = derive_water_cycle_model(
            terrain, heightmap, atmosphere=atmosphere, seed=seed, planet_id=region_id,
            parent_climate_model=parent_entity.get("water_cycle_model"),
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
        inherited_rows,
        parent_topology_rows,
        amplitude,
    )
    refinement_audit = dict(heightmap.get("refinement") or {})
    refinement_audit["parent_height_contract"] = parent_height_contract
    heightmap["refinement"] = refinement_audit
    coastal_refinement["parent_height_contract"] = parent_height_contract
    report_stage(
        "coastal_refinement_ready",
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
        )
        # One final solve makes river/coast classification agree with the
        # restored parent topology.  This replaces stale drainage rather than
        # layering an additional landscape-evolution iteration on top.
        water_cycle = derive_water_cycle_model(
            terrain,
            heightmap,
            atmosphere=atmosphere,
            seed=seed,
            planet_id=region_id,
            parent_climate_model=parent_entity.get("water_cycle_model"),
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
    )
    report_stage(
        "regional_materials_ready",
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
            "climate": "parent_conditioned_with_local_orographic_refinement",
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
    storage_root = Path(storage_root).resolve()
    surface_geomorphology_model = derive_surface_geomorphology_model(
        material_generation_context,
        heightmap=heightmap,
        water_cycle=water_cycle,
        surface_evolution=surface_evolution,
        tectonic_model=(root_planet or {}).get("tectonic_model"),
    )
    material_generation_context["surface_geomorphology_model"] = surface_geomorphology_model
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
        image_size=(
            320,
            max(64, min(320, int(round(320 / region_aspect)))),
        ),
    )
    report_stage(
        "material_rasters_ready",
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
    report_stage("surface_render_models_ready")
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
    loader = world_model.loader
    existing = world_model.get_entity(region_id)
    if isinstance(existing, dict):
        existing.update(region)
        region = existing
    loader.persist_entity(region)
    parent = world_model.get_entity(parent_entity["id"]) or parent_entity
    children = list(parent.get("constituents") or [])
    if region_id not in children:
        children.append(region_id)
        parent["constituents"] = children
        loader.persist_entity(parent)
    report_stage(
        "persisted",
        entity=region_id,
        revision=refinement_revision,
        bounds=region.get("bounds"),
    )
    return region
