"""Derive disposable mountain-system state from ontology-backed world inputs.

Architecture invariants: entity and semantic facts are ontology-owned; these
systems are generated projections. No planet is currently a persistence target,
so changed mountain contracts invalidate old products without migration.
"""

import math

from simulations.world_gen.map_seed import seed_range


OROGEN_SYSTEM_MODEL_VERSION = "orogen-systems-v2-spaced-margin-profiles"


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, float(value)))


def _wrapped_delta(a, b):
    delta = float(a) - float(b)
    if delta > 0.5:
        delta -= 1.0
    elif delta < -0.5:
        delta += 1.0
    return delta


def _segment_length_km(segment, circumference_m):
    y1 = float(segment.get("y1", 0.5) or 0.5)
    y2 = float(segment.get("y2", 0.5) or 0.5)
    latitude = (0.5 - (y1 + y2) * 0.5) * math.pi
    dx = _wrapped_delta(
        float(segment.get("x2", 0.0) or 0.0),
        float(segment.get("x1", 0.0) or 0.0),
    )
    dy = y2 - y1
    x_km = dx * circumference_m * max(0.08, abs(math.cos(latitude))) / 1000.0
    y_km = dy * circumference_m * 0.5 / 1000.0
    return math.hypot(x_km, y_km)


def _circular_mean_x(segments):
    sin_total = 0.0
    cos_total = 0.0
    for segment in segments:
        midpoint = (
            float(segment.get("x1", 0.0) or 0.0)
            + _wrapped_delta(
                float(segment.get("x2", 0.0) or 0.0),
                float(segment.get("x1", 0.0) or 0.0),
            )
            * 0.5
        ) % 1.0
        angle = midpoint * math.tau
        sin_total += math.sin(angle)
        cos_total += math.cos(angle)
    if abs(sin_total) + abs(cos_total) <= 1e-12:
        return 0.0
    return (math.atan2(sin_total, cos_total) / math.tau) % 1.0


def _classify_mechanism(kind, plate_a, plate_b, normal_velocity):
    type_a = str(plate_a.get("plate_type") or "mixed")
    type_b = str(plate_b.get("plate_type") or "mixed")
    if kind == "collision":
        return "continental_collision"
    if kind == "subduction":
        overriding_id = None
        if type_a == "oceanic" and type_b != "oceanic":
            overriding_id = plate_b.get("id")
        elif type_b == "oceanic" and type_a != "oceanic":
            overriding_id = plate_a.get("id")
        overriding = plate_a if overriding_id == plate_a.get("id") else plate_b
        return "island_arc_subduction" if overriding.get("plate_type") == "oceanic" else "ocean_continent_subduction"
    if kind == "divergent":
        if "continental" in {type_a, type_b} or (
            float(plate_a.get("continentality", 0.0) or 0.0)
            + float(plate_b.get("continentality", 0.0) or 0.0)
        ) >= 1.05:
            return "continental_rift"
        return "oceanic_spreading"
    if kind == "transform":
        if normal_velocity < -0.10:
            return "transpressional_strike_slip"
        if normal_velocity > 0.10:
            return "transtensional_strike_slip"
        return "strike_slip"
    return "passive_margin"


def _history_links(history, plate_a_id, plate_b_id):
    links = []
    ages = []
    pair = {plate_a_id, plate_b_id}
    for index, event in enumerate((history or {}).get("events") or []):
        if not isinstance(event, dict):
            continue
        event_pair = {event.get("plate_a"), event.get("plate_b")}
        participants = {str(item) for item in (event.get("participants") or [])}
        if event_pair != pair and not pair.issubset(participants):
            continue
        age = event.get("age_before_present_myr")
        if age is not None:
            ages.append(max(0.0, float(age or 0.0)))
        links.append({
            "event_index": index,
            "kind": str(event.get("kind") or "unknown"),
            "age_before_present_myr": None if age is None else round(float(age or 0.0), 1),
        })
    return links, (max(ages) if ages else 0.0)


def _side_contract(mechanism, plate_a, plate_b, segments):
    plate_a_id = plate_a.get("id")
    plate_b_id = plate_b.get("id")
    if "subduction" in mechanism:
        overriding_counts = {plate_a_id: 0, plate_b_id: 0}
        subducting_counts = {plate_a_id: 0, plate_b_id: 0}
        for segment in segments:
            overriding = segment.get("overriding_plate")
            subducting = segment.get("subducting_plate")
            if overriding in overriding_counts:
                overriding_counts[overriding] += 1
            if subducting in subducting_counts:
                subducting_counts[subducting] += 1
        overriding = max(overriding_counts, key=overriding_counts.get)
        subducting = max(subducting_counts, key=subducting_counts.get)
        return {
            "normal_points_from_plate": plate_a_id,
            "normal_points_to_plate": plate_b_id,
            "overriding_plate": overriding,
            "subducting_plate": subducting,
            "overriding_normal_side": 1 if overriding == plate_b_id else -1,
        }
    if mechanism == "continental_collision":
        strength_a = (
            float(plate_a.get("continentality", 0.5) or 0.5)
            + float(plate_a.get("area_fraction", 0.0) or 0.0) * 0.35
        )
        strength_b = (
            float(plate_b.get("continentality", 0.5) or 0.5)
            + float(plate_b.get("area_fraction", 0.0) or 0.0) * 0.35
        )
        hinterland = plate_a_id if strength_a >= strength_b else plate_b_id
        foreland = plate_b_id if hinterland == plate_a_id else plate_a_id
        return {
            "normal_points_from_plate": plate_a_id,
            "normal_points_to_plate": plate_b_id,
            "hinterland_plate": hinterland,
            "foreland_plate": foreland,
            "hinterland_normal_side": 1 if hinterland == plate_b_id else -1,
            "foreland_normal_side": 1 if foreland == plate_b_id else -1,
        }
    return {
        "normal_points_from_plate": plate_a_id,
        "normal_points_to_plate": plate_b_id,
    }


def _forcing_profile(mechanism, activity, normal_velocity, shear_velocity, maturity, mean_width, map_seed, system_id):
    convergence = _clamp((abs(min(0.0, normal_velocity)) - 0.15) / 3.5, 0.08, 1.0)
    extension = _clamp((max(0.0, normal_velocity) - 0.08) / 3.0, 0.08, 1.0)
    shear = _clamp((abs(shear_velocity) - 0.25) / 3.5, 0.08, 1.0)
    activity_gain = _clamp(0.48 + activity * 0.52, 0.55, 1.18)
    age_gain = 0.42 + maturity * 0.58
    base = {
        "profile_model": "signed_cross_range_forcing_v2",
        "reference_width": round(mean_width, 5),
        "rock_uplift_peak_m": 0.0,
        "tectonic_subsidence_peak_m": 0.0,
        "volcanic_construction_peak_m": 0.0,
        "outer_bulge_peak_m": 0.0,
        "crustal_thickening_index": 0.0,
        "zones": [],
    }
    if mechanism == "continental_collision":
        base.update({
            "rock_uplift_peak_m": round((2450.0 + convergence * 2700.0) * activity_gain * age_gain, 1),
            "tectonic_subsidence_peak_m": round((620.0 + convergence * 720.0) * age_gain, 1),
            "outer_bulge_peak_m": round(180.0 + convergence * 210.0, 1),
            "crustal_thickening_index": round(_clamp(0.30 + convergence * 0.55 + maturity * 0.15), 3),
            "zones": ["foreland_basin", "fold_thrust_belt", "high_range", "metamorphic_core", "outer_bulge"],
        })
    elif mechanism in {"ocean_continent_subduction", "island_arc_subduction"}:
        island_arc = mechanism == "island_arc_subduction"
        base.update({
            "rock_uplift_peak_m": round((1150.0 + convergence * (1750.0 if island_arc else 2250.0)) * activity_gain * age_gain, 1),
            "tectonic_subsidence_peak_m": round((1850.0 + convergence * 1750.0) * age_gain, 1),
            "volcanic_construction_peak_m": round((1750.0 + convergence * (2150.0 if island_arc else 1750.0)) * activity_gain * age_gain, 1),
            "crustal_thickening_index": round(_clamp(0.12 + convergence * (0.35 if island_arc else 0.52)), 3),
            "zones": ["trench", "accretionary_margin", "forearc", "volcanic_arc", "backarc"],
        })
    elif mechanism == "continental_rift":
        base.update({
            "rock_uplift_peak_m": round((520.0 + extension * 1050.0) * activity_gain * age_gain, 1),
            "tectonic_subsidence_peak_m": round((950.0 + extension * 1450.0) * age_gain, 1),
            "zones": ["rift_axis", "faulted_basin", "rift_shoulders"],
        })
    elif mechanism == "oceanic_spreading":
        base.update({
            "rock_uplift_peak_m": round((850.0 + extension * 1150.0) * activity_gain, 1),
            "tectonic_subsidence_peak_m": round(180.0 + extension * 320.0, 1),
            "zones": ["axial_valley", "ridge_flanks", "young_oceanic_crust"],
        })
    elif mechanism == "transpressional_strike_slip":
        base.update({
            "rock_uplift_peak_m": round((650.0 + shear * 1500.0) * activity_gain * age_gain, 1),
            "tectonic_subsidence_peak_m": round(180.0 + shear * 260.0, 1),
            "zones": ["principal_fault", "restraining_bend_uplift"],
        })
    elif mechanism == "transtensional_strike_slip":
        base.update({
            "rock_uplift_peak_m": round(180.0 + shear * 420.0, 1),
            "tectonic_subsidence_peak_m": round((520.0 + shear * 1150.0) * age_gain, 1),
            "zones": ["principal_fault", "releasing_bend_basin"],
        })
    elif mechanism == "strike_slip":
        base.update({
            "rock_uplift_peak_m": round(260.0 + shear * 620.0, 1),
            "tectonic_subsidence_peak_m": round(140.0 + shear * 280.0, 1),
            "zones": ["principal_fault", "linear_scarp"],
        })
    base["along_strike_variation"] = {
        "phase": round(seed_range(map_seed, f"{system_id}:forcing_phase", 0.0, math.tau), 5),
        "frequency": round(seed_range(map_seed, f"{system_id}:forcing_frequency", 2.5, 6.5), 3),
        "minimum_continuity": round(seed_range(map_seed, f"{system_id}:forcing_continuity", 0.58, 0.76), 3),
    }
    return base


def derive_orogen_system_model(
    plates,
    boundary_segments,
    *,
    geologic_history=None,
    map_seed="",
    age_myr=0.0,
    circumference_m=40_075_000.0,
):
    """Group local plate-boundary samples into coherent, causal mountain systems."""
    plates_by_id = {
        plate.get("id"): plate
        for plate in (plates or [])
        if isinstance(plate, dict) and plate.get("id")
    }
    groups = {}
    for index, segment in enumerate(boundary_segments or []):
        if not isinstance(segment, dict):
            continue
        segment.setdefault("id", f"boundary_segment_{index + 1:04d}")
        plate_a_id, plate_b_id = sorted((str(segment.get("plate_a") or ""), str(segment.get("plate_b") or "")))
        plate_a = plates_by_id.get(plate_a_id) or {}
        plate_b = plates_by_id.get(plate_b_id) or {}
        kind = str(segment.get("kind") or "passive")
        mechanism = _classify_mechanism(
            kind,
            plate_a,
            plate_b,
            float(segment.get("normal_velocity_cm_year", 0.0) or 0.0),
        )
        if mechanism == "passive_margin":
            segment.pop("orogen_system_id", None)
            continue
        groups.setdefault((plate_a_id, plate_b_id, mechanism), []).append(segment)

    systems = []
    mechanism_counts = {}
    for plate_a_id, plate_b_id, mechanism in sorted(groups):
        segments = groups[(plate_a_id, plate_b_id, mechanism)]
        plate_a = plates_by_id.get(plate_a_id) or {"id": plate_a_id}
        plate_b = plates_by_id.get(plate_b_id) or {"id": plate_b_id}
        system_id = f"orogen_{plate_a_id}_{plate_b_id}_{mechanism}"
        activity = sum(float(item.get("activity_scale", 1.0) or 1.0) for item in segments) / max(1, len(segments))
        normal_velocity = sum(float(item.get("normal_velocity_cm_year", 0.0) or 0.0) for item in segments) / max(1, len(segments))
        shear_velocity = sum(float(item.get("shear_velocity_cm_year", 0.0) or 0.0) for item in segments) / max(1, len(segments))
        obliquity = sum(float(item.get("obliquity_deg", 0.0) or 0.0) for item in segments) / max(1, len(segments))
        mean_width = sum(float(item.get("influence_width", 0.028) or 0.028) for item in segments) / max(1, len(segments))
        links, inherited_age = _history_links(geologic_history, plate_a_id, plate_b_id)
        effective_duration = max(0.0, float(age_myr or 0.0)) + min(180.0, inherited_age) * 0.35
        maturity = _clamp(1.0 - math.exp(-effective_duration / 72.0), 0.12, 1.0)
        side_contract = _side_contract(mechanism, plate_a, plate_b, segments)
        forcing = _forcing_profile(
            mechanism,
            activity,
            normal_velocity,
            shear_velocity,
            maturity,
            mean_width,
            map_seed,
            system_id,
        )
        for segment in segments:
            segment["orogen_system_id"] = system_id
        systems.append({
            "id": system_id,
            "mechanism": mechanism,
            "boundary_kind": str(segments[0].get("kind") or "passive"),
            "source_plate_ids": [plate_a_id, plate_b_id],
            "source_segment_ids": [str(segment.get("id")) for segment in segments],
            "source_history_events": links,
            "state": "active" if activity >= 0.42 else "weakly_active",
            "simulated_duration_myr": round(max(0.0, float(age_myr or 0.0)), 1),
            "inherited_age_myr": round(inherited_age, 1),
            "maturity": round(maturity, 3),
            "geometry": {
                "center_x": round(_circular_mean_x(segments), 5),
                "center_y": round(sum((float(item.get("y1", 0.5) or 0.5) + float(item.get("y2", 0.5) or 0.5)) * 0.5 for item in segments) / len(segments), 5),
                "length_km": round(sum(_segment_length_km(item, circumference_m) for item in segments), 1),
                "segment_count": len(segments),
                "mean_influence_width": round(mean_width, 5),
            },
            "kinematics": {
                "mean_normal_velocity_cm_year": round(normal_velocity, 3),
                "mean_shear_velocity_cm_year": round(shear_velocity, 3),
                "mean_obliquity_deg": round(obliquity, 1),
                "activity": round(activity, 3),
            },
            "sides": side_contract,
            "forcing_profile": forcing,
            "truth_state": "reduced_physics_tectonic_forcing",
        })
        mechanism_counts[mechanism] = mechanism_counts.get(mechanism, 0) + 1

    return {
        "status": "orogen_systems_derived",
        "model_version": OROGEN_SYSTEM_MODEL_VERSION,
        "truth_state": "coherent_plate_boundary_mountain_systems",
        "age_myr": round(max(0.0, float(age_myr or 0.0)), 1),
        "system_count": len(systems),
        "active_system_count": sum(1 for item in systems if item.get("state") == "active"),
        "mechanism_counts": mechanism_counts,
        "total_length_km": round(sum(float(item["geometry"]["length_km"]) for item in systems), 1),
        "systems": systems,
        "forcing_contract": "separate_rock_uplift_tectonic_subsidence_volcanic_construction_and_crustal_thickening",
        "notes": [
            "Systems group local boundary samples into coherent mountain-forming contacts.",
            "Signed cross-range zones are forcing inputs; they are not final elevation or full crustal deformation.",
        ],
    }
