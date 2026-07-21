"""Deterministic material prospects for refined regional maps."""

import math

from simulations.world_gen.map_seed import seed_range
from simulations.world_gen.material_affinities import (
    material_affinity_profile,
    material_affinity_score,
)


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, float(value)))


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
        return "mineral_occurrence"
    return "local_material_unit"


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


def derive_regional_material_model(
    natural_material_model,
    heightmap,
    water_cycle,
    surface_evolution=None,
    *,
    map_seed,
    detail_level,
    max_occurrences=8,
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
    if detail_level <= 0:
        return {
            "status": "deferred_until_regional_refinement",
            "detail_level": detail_level,
            "eligible_candidate_count": 0,
            "occurrences": [],
        }

    candidates = [
        candidate
        for candidate in natural_material_model.get("likely_materials") or []
        if (
            isinstance(candidate, dict)
            and int(candidate.get("minimum_map_detail_level", 0) or 0) > 0
            and int(candidate.get("minimum_map_detail_level", 0) or 0) <= detail_level
        )
    ]
    candidates.sort(key=lambda item: (
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

    occurrences = []
    evaluations = []
    sample_count = 14
    for candidate in candidates[:28]:
        material_id = str(candidate.get("material_id") or "")
        best = None
        for sample_index in range(sample_count):
            x = seed_range(
                str(map_seed),
                f"{material_id}:regional_sample:{sample_index}:x",
                0.03,
                0.97,
            )
            y = seed_range(
                str(map_seed),
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
                    str(map_seed),
                    f"{material_id}:regional_signal:{sample_index}",
                    0.0,
                    1.0,
                ),
                "noise": 0.5,
                "wet_oxidizing_surface": wet_oxidizing,
                "active_hydrology": "active_hydrology" in tags,
                "active_volcanism": "active_volcanism" in tags,
            }
            suitability = material_affinity_score(material_id, context)
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
            str(map_seed),
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
            str(map_seed),
            f"{material_id}:absolute_occurrence_radius",
            absolute_low,
            absolute_high,
        )
        radius_m = min(fractional_radius_m, absolute_radius_m)
        occurrences.append({
            "id": f"occurrence_{material_id.removeprefix('mat_')}_{len(occurrences) + 1:02d}",
            "material_id": material_id,
            "name": candidate.get("name") or material_id,
            "material_subclass": candidate.get("material_subclass"),
            "occurrence_role": occurrence_role,
            "center": {"x": round(best["x"], 6), "y": round(best["y"], 6)},
            "estimated_radius_m": round(max(0.05, radius_m), 2),
            "suitability": round(best["suitability"], 3),
            "confidence": round(float(candidate.get("confidence", 0.0) or 0.0), 3),
            "grade_class": (
                "high" if best["score"] >= 0.58
                else ("moderate" if best["score"] >= 0.32 else "low")
            ),
            "local_temperature_k": round(best["temperature_k"], 2),
            "local_precipitation_mm": round(best["precipitation_mm"], 1),
            "truth_state": "generated_prospect",
            "genesis_model": _deposit_genesis(candidate),
            "causal_provenance": {
                "material_inventory": "inherited_from_differentiated_planetary_crust",
                "concentration_process": _deposit_genesis(candidate),
                "local_selection_inputs": ["tectonic_setting", "temperature", "precipitation", "runoff", "weathering", "erosion", "deposition"],
                "exposure_process": "regional_erosion_and_surface_intersection",
                "biosphere_dependency": False,
            },
            "generated_truth_seed": f"{map_seed}:{material_id}:occurrence",
            "scale_stable": True,
            "_selection_score": float(best["score"]),
        })

    occurrences.sort(key=lambda item: (
        -float(item.get("_selection_score", 0.0) or 0.0),
        str(item.get("material_id") or ""),
    ))
    occurrences = occurrences[:max(1, int(max_occurrences or 1))]
    for occurrence_index, occurrence in enumerate(occurrences, start=1):
        material_id = str(occurrence.get("material_id") or "")
        occurrence["id"] = (
            f"occurrence_{material_id.removeprefix('mat_')}_{occurrence_index:02d}"
        )
        occurrence.pop("_selection_score", None)

    return {
        "status": "regional_material_occurrences_generated",
        "model_version": "regional_materials_v002",
        "detail_level": detail_level,
        "distribution_rule": "minor materials and ores resolve only at or below their minimum map detail",
        "truth_contract": "deterministic_parent_conditioned_hidden_truth",
        "map_seed": str(map_seed),
        "eligible_candidate_count": len(candidates),
        "occurrence_count": len(occurrences),
        "candidate_evaluations": evaluations,
        "occurrences": occurrences,
    }
