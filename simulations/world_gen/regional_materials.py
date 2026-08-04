"""Deterministic material prospects for refined regional maps."""

import copy
import hashlib
import math

from simulations.world_gen.map_seed import seed_range
from simulations.world_gen.material_affinities import (
    material_affinity_profile,
    material_affinity_score,
    material_distribution_role,
)
from simulations.world_gen.material_formation import (
    formation_contract,
    formation_suitability,
)
from simulations.world_gen.mineralization_potential import derive_mineralization_potential_model


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, float(value)))


_MINERALIZATION_PROFILE_KEYS = {
    "sulfide_ore": ("vms_potential_rows", "porphyry_potential_rows"),
    "hydrothermal": ("porphyry_potential_rows", "orogenic_gold_potential_rows"),
}


def _sample_mineralization_potential(mineralization_model, profile_id, global_u, global_v):
    """Soft, additive-only bias toward planetary-scale-favorable ore zones.

    Returns 0.0 (no effect) when the profile isn't ore-related or the
    planetary mineralization model is unavailable, so regional generation
    behaves exactly as before when this field is absent.
    """
    row_keys = _MINERALIZATION_PROFILE_KEYS.get(profile_id)
    if not row_keys or not isinstance(mineralization_model, dict):
        return 0.0
    width = int(mineralization_model.get("width", 0) or 0)
    height = int(mineralization_model.get("height", 0) or 0)
    if not width or not height:
        return 0.0
    best = 0.0
    for key in row_keys:
        rows = mineralization_model.get(key) or []
        # Bilinear rather than nearest-neighbour: rounding to the nearest
        # potential-grid cell gave every ore-favourability zone a faceted,
        # cracked-looking boundary once true_color.py's aggressive
        # substrate competitive weighting (power(abundance, 6.0)) sharpened
        # those step edges further -- the same class of nearest-neighbour
        # aliasing already fixed this session in water_cycle.py's shore
        # distance and upwind relief sampling.
        best = max(best, _sample(rows, global_u, global_v, default=0.0))
    return best


def _sample(rows, x, y, default=0.0):
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], list) or not rows[0]:
        return float(default)
    height = len(rows)
    width = min(len(row) for row in rows if isinstance(row, list) and row)
    if width <= 0:
        return float(default)
    px = _clamp(x) * max(1, width - 1)
    py = _clamp(y) * max(1, height - 1)
    x0, y0 = int(math.floor(px)), int(math.floor(py))
    x1, y1 = min(width - 1, x0 + 1), min(height - 1, y0 + 1)
    tx, ty = px - x0, py - y0
    top = float(rows[y0][x0]) * (1.0 - tx) + float(rows[y0][x1]) * tx
    bottom = float(rows[y1][x0]) * (1.0 - tx) + float(rows[y1][x1]) * tx
    return top * (1.0 - ty) + bottom * ty


def _occurrence_role(candidate):
    representation = str(
        candidate.get("spatial_representation")
        or (candidate.get("formation_contract") or {}).get(
            "spatial_representation"
        )
        or ""
    )
    if representation == "bounded_deposit":
        return "ore_or_mineral_prospect"
    if representation == "constituent_abundance":
        return "mineral_constituent_abundance"
    if representation == "bedrock_unit":
        return "geologic_unit"
    if representation == "surface_cover":
        return "surface_cover_unit"
    distribution_role = (
        candidate.get("distribution_role")
        or material_distribution_role(
            candidate.get("material_id"),
            candidate.get("material_subclass"),
            candidate.get("minimum_map_detail_level", 0),
        )
    )
    if distribution_role == "sparse_deposit":
        return "ore_or_mineral_prospect"
    if distribution_role == "mineral_constituent":
        return "mineral_constituent_abundance"
    profile_id = str(
        (candidate.get("surface_affinity_profile") or {}).get("profile_id")
        or (material_affinity_profile(candidate.get("material_id")) or {}).get("profile_id")
        or ""
    )
    if profile_id in {
        "sulfide_ore",
        "heavy_mineral",
        "bauxite",
        "nickel_laterite",
        "hydrothermal",
    }:
        return "ore_or_mineral_prospect"
    if candidate.get("material_subclass") == "mineral":
        return "mineral_constituent_abundance"
    return "local_material_unit"


def _candidate_formation_contract(candidate):
    profile = (
        candidate.get("surface_affinity_profile")
        or material_affinity_profile(candidate.get("material_id"))
        or {}
    )
    return formation_contract(
        candidate.get("material_id"),
        candidate.get("material_subclass"),
        profile.get("profile_id"),
        explicit_category=candidate.get("formation_category"),
        explicit_representation=candidate.get("spatial_representation"),
    )


def _normalized_source_bounds(source_uv_bounds):
    source_uv_bounds = (
        source_uv_bounds if isinstance(source_uv_bounds, dict) else {}
    )
    min_u = _clamp(source_uv_bounds.get("min_u", 0.0))
    max_u = _clamp(source_uv_bounds.get("max_u", 1.0))
    min_v = _clamp(source_uv_bounds.get("min_v", 0.0))
    max_v = _clamp(source_uv_bounds.get("max_v", 1.0))
    if max_u <= min_u:
        min_u, max_u = 0.0, 1.0
    if max_v <= min_v:
        min_v, max_v = 0.0, 1.0
    return {
        "min_u": min_u, "max_u": max_u,
        "min_v": min_v, "max_v": max_v,
    }


def _global_to_local(center, bounds, *, clamp=False):
    x = (
        (float(center.get("u", 0.0)) - bounds["min_u"])
        / max(1e-12, bounds["max_u"] - bounds["min_u"])
    )
    y = (
        (float(center.get("v", 0.0)) - bounds["min_v"])
        / max(1e-12, bounds["max_v"] - bounds["min_v"])
    )
    return {
        "x": _clamp(x) if clamp else x,
        "y": _clamp(y) if clamp else y,
    }


def _parent_occurrences_in_bounds(parent_model, bounds):
    """Project already-generated bodies into a child without changing truth."""
    parent_model = parent_model if isinstance(parent_model, dict) else {}
    parent_bounds = _normalized_source_bounds(parent_model.get("source_uv_bounds"))
    parent_width_m = max(
        0.0, float(parent_model.get("region_width_m", 0.0) or 0.0)
    )
    parent_height_m = max(
        0.0, float(parent_model.get("region_height_m", 0.0) or 0.0)
    )
    parent_u_span = parent_bounds["max_u"] - parent_bounds["min_u"]
    parent_v_span = parent_bounds["max_v"] - parent_bounds["min_v"]
    inherited = []
    for occurrence in parent_model.get("occurrences") or []:
        if not isinstance(occurrence, dict):
            continue
        global_center = occurrence.get("center_global_uv")
        if not isinstance(global_center, dict):
            local_center = occurrence.get("center") or {}
            global_center = {
                "u": parent_bounds["min_u"] + float(local_center.get("x", 0.0))
                * (parent_bounds["max_u"] - parent_bounds["min_u"]),
                "v": parent_bounds["min_v"] + float(local_center.get("y", 0.0))
                * (parent_bounds["max_v"] - parent_bounds["min_v"]),
            }
        u = float(global_center.get("u", 0.0))
        v = float(global_center.get("v", 0.0))
        center_inside = (
            bounds["min_u"] <= u <= bounds["max_u"]
            and bounds["min_v"] <= v <= bounds["max_v"]
        )
        radius_m = float(
            ((occurrence.get("deposit_body") or {}).get("geometry") or {}).get(
                "bounding_radius_m",
                occurrence.get("estimated_radius_m", 0.0),
            )
            or 0.0
        )
        radius_u = (
            radius_m / parent_width_m * parent_u_span
            if parent_width_m > 0.0
            else 0.0
        )
        radius_v = (
            radius_m / parent_height_m * parent_v_span
            if parent_height_m > 0.0
            else 0.0
        )
        footprint_intersects = (
            u + radius_u >= bounds["min_u"]
            and u - radius_u <= bounds["max_u"]
            and v + radius_v >= bounds["min_v"]
            and v - radius_v <= bounds["max_v"]
        )
        if not center_inside and not footprint_intersects:
            continue
        projected = copy.deepcopy(occurrence)
        projected["center_global_uv"] = {
            "u": round(u, 9),
            "v": round(v, 9),
        }
        projected["center"] = {
            key: round(value, 6)
            for key, value in _global_to_local(global_center, bounds).items()
        }
        projected["inherited_from_parent"] = True
        projected["center_inside_child_bounds"] = center_inside
        projected["footprint_intersects_child_bounds"] = footprint_intersects
        projected["_selection_score"] = float(
            occurrence.get("suitability", 0.0) or 0.0
        ) * float(occurrence.get("confidence", 0.0) or 0.0)
        inherited.append(projected)
    return inherited


def _deposit_genesis(candidate):
    profile_id = str(
        (candidate.get("surface_affinity_profile") or {}).get("profile_id")
        or (material_affinity_profile(candidate.get("material_id")) or {}).get("profile_id")
        or ""
    )
    return {
        "sulfide_ore": "magmatic_hydrothermal_sulfide_concentration",
        "heavy_mineral": "erosional_placer_concentration",
        "bauxite": "prolonged_residual_lateritic_weathering",
        "nickel_laterite": "ultramafic_weathering_and_downprofile_enrichment",
        "hydrothermal": "fault_intrusion_fluid_circulation",
        "metamorphic_uplift": "metamorphic_recrystallization_and_exhumation",
        "evaporite": "closed_basin_evaporation_and_brine_concentration",
        "carbonate": "aqueous_inorganic_carbonate_precipitation",
        "mafic_bedrock": "mafic_magma_crystallization_and_crustal_exhumation",
        "intermediate_volcanic": "arc_or_intraplate_magma_extrusion_and_cooling",
        "felsic_bedrock": "silicic_magma_differentiation_and_crystallization",
        "ultramafic_bedrock": "mantle_derived_ultramafic_crystallization_and_exposure",
        "hydrated_alteration": "fluid_rock_alteration_and_low_grade_metamorphism",
        "fresh_pyroclastic": "explosive_eruption_fragmentation_and_deposition",
        "saprolite": "deep_in_place_chemical_weathering_of_bedrock",
        "fluvial_sediment": "fluvial_erosion_transport_and_channel_deposition",
        "glacial_sediment": "glacial_entrainment_transport_and_till_deposition",
    }.get(profile_id, "lithology_climate_topography_conditioned_occurrence")


# A material affinity says where a material can occur.  It is deliberately not
# a deposit model: a mineable body also needs a concentrating process, a host,
# geometry and an exposure history.  Keep these recipes compact and explicit so
# they are usable by production/site systems without turning a regional map
# into an invented drill log.
_DEPOSIT_RECIPES = {
    "sulfide_ore": {
        "deposit_type": "hydrothermal_sulfide_body", "geometry": "stockwork_and_lenses",
        "host": "faulted_intrusive_or_volcanic_host", "thickness_m": (4.0, 45.0),
        "grade_fraction": (0.004, 0.045), "density_t_per_m3": 3.25,
    },
    "hydrothermal": {
        "deposit_type": "hydrothermal_vein_system", "geometry": "vein_swarm",
        "host": "fractured_fault_or_intrusion_margin", "thickness_m": (1.0, 18.0),
        "grade_fraction": (0.003, 0.030), "density_t_per_m3": 2.85,
    },
    "spring_carbonate": {
        "deposit_type": "spring_travertine_apron", "geometry": "terraced_apron_and_veins",
        "host": "carbonate_bearing_groundwater_discharge_zone",
        "thickness_m": (0.5, 14.0),
        "grade_fraction": (0.55, 0.96), "density_t_per_m3": 2.35,
    },
    "heavy_mineral": {
        "deposit_type": "placer_concentration", "geometry": "lens_or_paleochannel",
        "host": "sorted_fluvial_or_littoral_sediment", "thickness_m": (1.0, 12.0),
        "grade_fraction": (0.01, 0.12), "density_t_per_m3": 2.05,
    },
    "bauxite": {
        "deposit_type": "residual_laterite_blanket", "geometry": "blanket_and_pods",
        "host": "deeply_weathered_aluminous_bedrock", "thickness_m": (3.0, 24.0),
        "grade_fraction": (0.22, 0.52), "density_t_per_m3": 1.75,
    },
    "nickel_laterite": {
        "deposit_type": "nickel_laterite_profile", "geometry": "weathering_profile_blanket",
        "host": "weathered_ultramafic_bedrock", "thickness_m": (2.0, 20.0),
        "grade_fraction": (0.006, 0.028), "density_t_per_m3": 1.65,
    },
    "evaporite": {
        "deposit_type": "evaporite_basin", "geometry": "stratiform_basin_layer",
        "host": "closed_arid_basin", "thickness_m": (2.0, 80.0),
        "grade_fraction": (0.35, 0.90), "density_t_per_m3": 2.15,
    },
    "metamorphic_uplift": {
        "deposit_type": "metamorphic_mineral_zone", "geometry": "foliated_lens_or_layer",
        "host": "exhumed_metamorphic_terrane", "thickness_m": (3.0, 55.0),
        "grade_fraction": (0.08, 0.65), "density_t_per_m3": 2.85,
    },
}


def _deposit_recipe(candidate):
    profile_id = str(
        (candidate.get("surface_affinity_profile") or {}).get("profile_id")
        or (material_affinity_profile(candidate.get("material_id")) or {}).get("profile_id")
        or ""
    )
    return _DEPOSIT_RECIPES.get(profile_id)


def _deposit_body(candidate, best, radius_m, *, map_seed, tectonic_model=None):
    """Return a bounded, deterministic deposit contract for a prospect."""
    recipe = _deposit_recipe(candidate)
    if recipe is None:
        return None
    material_id = str(candidate.get("material_id") or "material")
    thickness_m = seed_range(str(map_seed), f"{material_id}:deposit_thickness", *recipe["thickness_m"])
    grade_fraction = seed_range(str(map_seed), f"{material_id}:deposit_grade", *recipe["grade_fraction"])
    footprint_area_m2 = math.pi * max(0.05, radius_m) ** 2
    # Lenses and vein swarms do not fill their bounding circle.  This is an
    # in-place geometric occupancy, not a claim that every tonne is recoverable.
    geometry_fill = seed_range(str(map_seed), f"{material_id}:deposit_geometry_fill", 0.12, 0.72)
    in_situ_tonnage = footprint_area_m2 * thickness_m * recipe["density_t_per_m3"] * geometry_fill
    tectonic_regime = str(((tectonic_model or {}).get("summary") or {}).get("regime") or "unknown")
    form = recipe["geometry"]
    boundary_phase_a = seed_range(
        str(map_seed), f"{material_id}:deposit_boundary_phase_a", 0.0, math.tau
    )
    boundary_phase_b = seed_range(
        str(map_seed), f"{material_id}:deposit_boundary_phase_b", 0.0, math.tau
    )
    footprint_vertices = []
    for index in range(40):
        angle = math.tau * index / 40.0
        radial = (
            0.82
            + math.sin(angle * 3.0 + boundary_phase_a) * 0.10
            + math.sin(angle * 7.0 + boundary_phase_b) * 0.055
            + seed_range(
                str(map_seed),
                f"{material_id}:deposit_boundary_vertex:{index}",
                -0.045,
                0.045,
            )
        )
        footprint_vertices.append([
            round(max(0.58, min(1.0, radial)) * math.cos(angle), 5),
            round(max(0.58, min(1.0, radial)) * math.sin(angle), 5),
        ])
    return {
        "deposit_type": recipe["deposit_type"],
        "geometry": {
            "form": form,
            "bounding_radius_m": round(max(0.05, radius_m), 2),
            "estimated_thickness_m": round(thickness_m, 2),
            "orientation_deg": round(seed_range(str(map_seed), f"{material_id}:deposit_orientation", 0.0, 180.0), 1),
            "geometry_fill_fraction": round(geometry_fill, 3),
            "footprint_vertices": footprint_vertices,
            "boundary_model": "process_conditioned_irregular_lobed_v1",
        },
        "host_context": {
            "host_lithology": recipe["host"],
            "tectonic_regime": tectonic_regime,
            "surface_exposure": "regional_erosion_and_surface_intersection",
        },
        "resource_estimate": {
            "in_situ_tonnage_range_t": [round(in_situ_tonnage * 0.55), round(in_situ_tonnage * 1.45)],
            "grade_fraction_range": [round(grade_fraction * 0.72, 4), round(min(1.0, grade_fraction * 1.28), 4)],
            "estimate_basis": "generated_geometry_density_and_process_range_not_a_reserve",
        },
        "process_chain": [
            "source_inventory", _deposit_genesis(candidate), "regional_exposure",
        ],
        "preservation_state": "inferred_from_relative_surface_age",
        "truth_state": "generated_hidden_deposit_body",
    }


def _unit_geometry(candidate, radius_m, *, map_seed, geometry_kind):
    """Return a mapped lithologic unit without pretending it is an ore body."""
    material_id = str(candidate.get("material_id") or "material")
    phase_a = seed_range(str(map_seed), f"{material_id}:unit_phase_a", 0.0, math.tau)
    phase_b = seed_range(str(map_seed), f"{material_id}:unit_phase_b", 0.0, math.tau)
    vertices = []
    for index in range(40):
        angle = math.tau * index / 40.0
        radial = (
            0.84
            + math.sin(angle * 3.0 + phase_a) * 0.09
            + math.sin(angle * 6.0 + phase_b) * 0.05
        )
        vertices.append([
            round(radial * math.cos(angle), 5),
            round(radial * math.sin(angle), 5),
        ])
    return {
        "kind": geometry_kind,
        "geometry": {
            "form": (
                "irregular_lithologic_contact"
                if geometry_kind == "geologic_unit"
                else "surficial_cover_patch"
            ),
            "bounding_radius_m": round(max(0.05, radius_m), 2),
            "orientation_deg": round(
                seed_range(str(map_seed), f"{material_id}:unit_orientation", 0.0, 180.0),
                1,
            ),
            "footprint_vertices": vertices,
            "boundary_model": "formation_conditioned_geologic_contact_v1",
        },
        "truth_state": "generated_material_unit",
    }


def derive_regional_material_model(
    natural_material_model,
    heightmap,
    water_cycle,
    surface_evolution=None,
    *,
    map_seed,
    detail_level,
    max_occurrences=8,
    tectonic_model=None,
    source_uv_bounds=None,
    root_map_seed=None,
    parent_regional_material_model=None,
):
    """Resolve planet-wide chemical possibilities into small regional pockets."""
    natural_material_model = (
        natural_material_model if isinstance(natural_material_model, dict) else {}
    )
    heightmap = heightmap if isinstance(heightmap, dict) else {}
    water_cycle = water_cycle if isinstance(water_cycle, dict) else {}
    surface_evolution = (
        surface_evolution if isinstance(surface_evolution, dict) else {}
    )
    detail_level = max(0, int(detail_level or 0))
    source_bounds = _normalized_source_bounds(
        source_uv_bounds or heightmap.get("source_uv_bounds")
    )
    mineralization_model = (
        derive_mineralization_potential_model(tectonic_model) if tectonic_model else None
    )
    if detail_level <= 0:
        return {
            "status": "deferred_until_regional_refinement",
            "detail_level": detail_level,
            "eligible_candidate_count": 0,
            "source_uv_bounds": source_bounds,
            "occurrences": [],
        }

    parent_regional_material_model = (
        parent_regional_material_model
        if isinstance(parent_regional_material_model, dict)
        else {}
    )
    has_parent_material_truth = bool(
        parent_regional_material_model.get("occurrences")
        or parent_regional_material_model.get("detail_level")
    )

    def effective_detail_level(candidate):
        if candidate.get("foundational_lithology"):
            return 0
        profile = material_affinity_profile(candidate.get("material_id")) or {}
        return max(
            int(candidate.get("minimum_map_detail_level", 0) or 0),
            int(profile.get("minimum_map_detail_level", 0) or 0),
        )

    candidates = [
        {
            **candidate,
            "formation_contract": _candidate_formation_contract(candidate),
            "formation_category": _candidate_formation_contract(candidate).get(
                "category_id"
            ),
            "spatial_representation": _candidate_formation_contract(candidate).get(
                "spatial_representation"
            ),
        }
        for candidate in natural_material_model.get("likely_materials") or []
        if (
            isinstance(candidate, dict)
            and effective_detail_level(candidate) > 0
            and effective_detail_level(candidate) <= detail_level
            and (
                not has_parent_material_truth
                or effective_detail_level(candidate) == detail_level
            )
        )
    ]
    candidates.sort(key=lambda item: (
        -float(
            item.get("prevalence_score", item.get("confidence", 0.0)) or 0.0
        ),
        -float(item.get("confidence", 0.0) or 0.0),
        str(item.get("material_id") or ""),
    ))

    rows = (heightmap.get("sample_grid") or {}).get("rows") or []
    sea_level = heightmap.get("sea_level_m")
    climate = water_cycle.get("climate_grid") or {}
    temperature_rows = climate.get("temperature_rows_k") or []
    precipitation_rows = climate.get("annual_precipitation_rows_mm") or []
    runoff_rows = climate.get("annual_runoff_rows_mm") or []
    process = surface_evolution.get("process_grid") or {}
    weathering_rows = process.get("chemical_weathering_rows") or []
    deposition_rows = process.get("sediment_deposition_rows") or []
    erosion_rows = process.get("erosion_potential_rows") or []
    age_rows = process.get("relative_surface_age_rows") or []
    min_elevation = float(heightmap.get("min_elevation_m", -1000.0) or -1000.0)
    max_elevation = float(heightmap.get("max_elevation_m", 1000.0) or 1000.0)
    elevation_span = max(1.0, max_elevation - min_elevation)
    width_m = max(10.0, float(heightmap.get("region_width_m", 10.0) or 10.0))
    height_m = max(10.0, float(heightmap.get("region_height_m", 10.0) or 10.0))
    tags = set(natural_material_model.get("planet_tags") or [])
    wet_oxidizing = "active_hydrology" in tags and "oxidizing_surface" in tags
    volcanic = 1.0 if "volcanic_surface" in tags else 0.0
    available_host_categories = {
        contract.get("category_id")
        for candidate in natural_material_model.get("likely_materials") or []
        for contract in [_candidate_formation_contract(candidate)]
        if (
            contract.get("category_id")
            and contract.get("spatial_representation") == "bedrock_unit"
            and float(candidate.get("confidence", 0.0) or 0.0) >= 0.28
        )
    }
    available_host_categories.update(
        str(occurrence.get("formation_category") or "")
        for occurrence in parent_regional_material_model.get("occurrences") or []
        if isinstance(occurrence, dict) and occurrence.get("formation_category")
    )
    if {"felsic_crust", "silica_rich_crust"}.intersection(tags):
        available_host_categories.add("igneous_intrusive_felsic")
    if {"mafic_crust", "basaltic_surface"}.intersection(tags):
        available_host_categories.add("igneous_mafic")
    if "ultramafic_tendency" in tags:
        available_host_categories.add("igneous_ultramafic")
    if "carbonate_favorable" in tags:
        available_host_categories.add("carbonate_sedimentary_basin")

    occurrences = _parent_occurrences_in_bounds(
        parent_regional_material_model,
        source_bounds,
    )
    inherited_occurrence_count = len(occurrences)
    evaluations = []
    sample_count = 14
    truth_seed = str(root_map_seed or map_seed)
    bounds_salt = (
        f"{source_bounds['min_u']:.9f}:{source_bounds['max_u']:.9f}:"
        f"{source_bounds['min_v']:.9f}:{source_bounds['max_v']:.9f}"
    )
    regional_truth_seed = f"{truth_seed}:material_region:{bounds_salt}"
    for candidate in candidates[:28]:
        material_id = str(candidate.get("material_id") or "")
        formation = candidate.get("formation_contract") or {}
        best = None
        for sample_index in range(sample_count):
            x = seed_range(
                regional_truth_seed,
                f"{material_id}:regional_sample:{sample_index}:x",
                0.03,
                0.97,
            )
            y = seed_range(
                regional_truth_seed,
                f"{material_id}:regional_sample:{sample_index}:y",
                0.03,
                0.97,
            )
            elevation = _sample(rows, x, y, 0.0)
            elevation_norm = _clamp((elevation - min_elevation) / elevation_span)
            ocean = 1.0 if sea_level is not None and elevation < float(sea_level) else 0.0
            shoreline = (
                0.0
                if sea_level is None
                else math.exp(-((abs(elevation - float(sea_level)) / max(20.0, elevation_span * 0.035)) ** 2))
            )
            precipitation = max(0.0, _sample(precipitation_rows, x, y, 0.0))
            runoff = max(0.0, _sample(runoff_rows, x, y, 0.0))
            temperature = _sample(temperature_rows, x, y, 273.15)
            drainage = _clamp(runoff / (runoff + 240.0))
            humidity = _clamp(precipitation / 1800.0)
            weathering = (
                _clamp(_sample(weathering_rows, x, y, 0.0))
                if weathering_rows
                else _clamp(
                    humidity
                    * math.exp(-((temperature - 296.0) / 34.0) ** 2)
                    * (0.32 + drainage * 0.48)
                )
            )
            deposition = (
                _clamp(_sample(deposition_rows, x, y, 0.0))
                if deposition_rows
                else _clamp(drainage * 0.55)
            )
            erosion = _clamp(_sample(erosion_rows, x, y, 0.2))
            polar = abs(y - 0.5) * 2.0
            context = {
                "temperature_k": temperature,
                "precipitation_mm": precipitation,
                "land": 1.0 - ocean,
                "ocean": ocean,
                "elevation": elevation_norm,
                "highland": elevation_norm,
                "lowland": 1.0 - elevation_norm,
                "slope": erosion,
                "low_slope": 1.0 - erosion,
                "polar": polar,
                "shoreline": shoreline,
                "ice": 1.0 if temperature < 255.0 else 0.0,
                "humidity": humidity,
                "aridity": _clamp(1.0 - precipitation / 700.0),
                "drainage": drainage,
                "weathering": weathering,
                "deposition": deposition,
                "aeolian": _clamp(1.0 - precipitation / 700.0),
                "erosion": erosion,
                "glacial": 1.0 if temperature < 255.0 else 0.0,
                "age": _clamp(_sample(age_rows, x, y, 0.65)),
                "volcanic": volcanic,
                "resurfacing": volcanic * 0.55,
                "impact": 0.0,
                "carbonate": 1.0 if "carbonate_favorable" in tags else 0.0,
                "regional": seed_range(
                    regional_truth_seed,
                    f"{material_id}:regional_signal:{sample_index}",
                    0.0,
                    1.0,
                ),
                "noise": 0.5,
                "wet_oxidizing_surface": wet_oxidizing,
                "active_hydrology": "active_hydrology" in tags,
                "active_volcanism": "active_volcanism" in tags,
                "planet_tags": tags,
            }
            formation_fit = formation_suitability(
                formation,
                context,
                available_host_categories,
            )
            suitability = (
                material_affinity_score(material_id, context) * formation_fit
            )
            if mineralization_model is not None:
                profile_id = str(
                    (candidate.get("surface_affinity_profile") or {}).get("profile_id")
                    or (material_affinity_profile(material_id) or {}).get("profile_id")
                    or ""
                )
                mineral_signal = _sample_mineralization_potential(
                    mineralization_model,
                    profile_id,
                    source_bounds["min_u"] + x * (source_bounds["max_u"] - source_bounds["min_u"]),
                    source_bounds["min_v"] + y * (source_bounds["max_v"] - source_bounds["min_v"]),
                )
                if mineral_signal > 0.0:
                    suitability *= 0.85 + mineral_signal * 0.6
            score = suitability * float(candidate.get("confidence", 0.0) or 0.0)
            if best is None or score > best["score"]:
                best = {
                    "score": score,
                    "suitability": suitability,
                    "x": x,
                    "y": y,
                    "temperature_k": temperature,
                    "precipitation_mm": precipitation,
                }

        evaluations.append({
            "material_id": material_id,
            "best_score": round((best or {}).get("score", 0.0), 4),
            "formation_category": formation.get("category_id"),
            "spatial_representation": formation.get("spatial_representation"),
        })
        if not best or best["score"] < 0.16:
            continue

        scale_ranges = {
            1: (0.025, 0.085),
            2: (0.008, 0.035),
            3: (0.002, 0.012),
            4: (0.0007, 0.004),
            5: (0.0002, 0.0015),
            6: (0.00008, 0.0005),
            7: (0.00003, 0.0002),
        }
        radius_low, radius_high = scale_ranges.get(detail_level, (0.00003, 0.0002))
        fractional_radius_m = min(width_m, height_m) * seed_range(
            regional_truth_seed,
            f"{material_id}:occurrence_radius",
            radius_low,
            radius_high,
        )
        occurrence_role = _occurrence_role(candidate)
        radius_caps_by_level = {
            1: {
                "ore_or_mineral_prospect": (2_000.0, 30_000.0),
                "mineral_occurrence": (5_000.0, 60_000.0),
                "local_material_unit": (10_000.0, 100_000.0),
            },
            2: {
                "ore_or_mineral_prospect": (250.0, 4_000.0),
                "mineral_occurrence": (500.0, 10_000.0),
                "local_material_unit": (1_000.0, 20_000.0),
            },
            3: {
                "ore_or_mineral_prospect": (50.0, 1_500.0),
                "mineral_occurrence": (100.0, 3_000.0),
                "local_material_unit": (250.0, 6_000.0),
            },
            4: {
                "ore_or_mineral_prospect": (10.0, 300.0),
                "mineral_occurrence": (20.0, 750.0),
                "local_material_unit": (50.0, 1_500.0),
            },
        }
        caps = radius_caps_by_level.get(detail_level, radius_caps_by_level[4])
        absolute_low, absolute_high = caps.get(
            occurrence_role,
            caps["local_material_unit"],
        )
        absolute_radius_m = seed_range(
            regional_truth_seed,
            f"{material_id}:absolute_occurrence_radius",
            absolute_low,
            absolute_high,
        )
        radius_m = min(fractional_radius_m, absolute_radius_m)
        spatial_representation = str(
            formation.get("spatial_representation") or "unresolved"
        )
        deposit_body = (
            _deposit_body(
                candidate,
                best,
                radius_m,
                map_seed=regional_truth_seed,
                tectonic_model=tectonic_model,
            )
            if spatial_representation == "bounded_deposit"
            else None
        )
        material_unit = (
            _unit_geometry(
                candidate,
                radius_m,
                map_seed=regional_truth_seed,
                geometry_kind=(
                    "geologic_unit"
                    if spatial_representation == "bedrock_unit"
                    else "surface_cover_unit"
                ),
            )
            if spatial_representation in {"bedrock_unit", "surface_cover"}
            else None
        )
        abundance_field = None
        if spatial_representation == "constituent_abundance":
            modal_center = _clamp(
                float(candidate.get("relative_abundance", 0.25) or 0.25)
                * (0.35 + best["suitability"] * 0.65)
            )
            abundance_field = {
                "kind": "host_conditioned_modal_abundance",
                "host_formation_categories": list(
                    formation.get("host_formation_categories") or []
                ),
                "modal_fraction_range": [
                    round(max(0.001, modal_center * 0.45), 4),
                    round(min(0.95, modal_center * 1.35), 4),
                ],
                "mapping_method": "continuous_affinity_field_within_compatible_host",
                "bounded_body": False,
            }
        global_center = {
            "u": source_bounds["min_u"] + best["x"]
            * (source_bounds["max_u"] - source_bounds["min_u"]),
            "v": source_bounds["min_v"] + best["y"]
            * (source_bounds["max_v"] - source_bounds["min_v"]),
        }
        occurrence_key = hashlib.sha256(
            (
                f"{truth_seed}:{material_id}:"
                f"{global_center['u']:.9f}:{global_center['v']:.9f}"
            ).encode("utf-8")
        ).hexdigest()[:10]
        occurrences.append({
            "id": (
                f"occurrence_{material_id.removeprefix('mat_')}_"
                f"{occurrence_key}"
            ),
            "material_id": material_id,
            "name": candidate.get("name") or material_id,
            "material_subclass": candidate.get("material_subclass"),
            "occurrence_role": occurrence_role,
            "center": {"x": round(best["x"], 6), "y": round(best["y"], 6)},
            "center_global_uv": {
                "u": round(global_center["u"], 9),
                "v": round(global_center["v"], 9),
            },
            "estimated_radius_m": round(max(0.05, radius_m), 2),
            "suitability": round(best["suitability"], 3),
            "confidence": round(float(candidate.get("confidence", 0.0) or 0.0), 3),
            "grade_class": (
                "high" if best["score"] >= 0.58
                else ("moderate" if best["score"] >= 0.32 else "low")
            ),
            "local_temperature_k": round(best["temperature_k"], 2),
            "local_precipitation_mm": round(best["precipitation_mm"], 1),
            "truth_state": (
                "generated_prospect"
                if spatial_representation == "bounded_deposit"
                else "generated_material_distribution"
            ),
            # Knowledge and truth intentionally differ.  This is an inferred
            # map prospect; surveys may raise knowledge confidence later
            # without rerolling the deterministic body below.
            "knowledge_state": "inferred",
            "formation_category": formation.get("category_id"),
            "spatial_representation": spatial_representation,
            "formation_requirements": {
                "required_all_planet_tags": formation.get("required_all_planet_tags") or [],
                "required_any_planet_tags": formation.get("required_any_planet_tags") or [],
                "host_formation_categories": formation.get("host_formation_categories") or [],
                "local_minimums": formation.get("local_minimums") or {},
            },
            "deposit_body": deposit_body,
            "material_unit": material_unit,
            "abundance_field": abundance_field,
            "genesis_model": (
                formation.get("formation_process") or _deposit_genesis(candidate)
            ),
            "causal_provenance": {
                "material_inventory": "inherited_from_differentiated_planetary_crust",
                "formation_process": (
                    formation.get("formation_process") or _deposit_genesis(candidate)
                ),
                "host_context": (
                    sorted(
                        set(formation.get("host_formation_categories") or [])
                        .intersection(available_host_categories)
                    )
                    or ["self_supporting_surface_or_bedrock_process"]
                ),
                "local_selection_inputs": ["tectonic_setting", "temperature", "precipitation", "runoff", "weathering", "erosion", "deposition", "relative_surface_age"],
                "exposure_process": "regional_erosion_and_surface_intersection",
                "biosphere_dependency": False,
            },
            "generated_truth_seed": (
                f"{regional_truth_seed}:{material_id}:occurrence"
            ),
            "scale_stable": True,
            "_selection_score": float(best["score"]),
        })

    occurrences.sort(key=lambda item: (
        -float(item.get("_selection_score", 0.0) or 0.0),
        str(item.get("material_id") or ""),
    ))
    occurrences = occurrences[:max(1, int(max_occurrences or 1))]
    for occurrence in occurrences:
        occurrence.pop("_selection_score", None)

    return {
        "status": "regional_material_occurrences_generated",
        "model_version": "regional_materials_v005",
        "detail_level": detail_level,
        "distribution_rule": "minor materials and ores resolve only at or below their minimum map detail",
        "truth_contract": "deterministic_parent_conditioned_hidden_truth",
        "map_seed": str(map_seed),
        "root_material_seed": truth_seed,
        "source_uv_bounds": source_bounds,
        "region_width_m": round(width_m, 3),
        "region_height_m": round(height_m, 3),
        "inherited_occurrence_count": inherited_occurrence_count,
        "eligible_candidate_count": len(candidates),
        "occurrence_count": len(occurrences),
        "candidate_evaluations": evaluations,
        "occurrences": occurrences,
        "knowledge_contract": "survey_confidence_can_change_without_mutating_generated_geologic_truth",
    }
