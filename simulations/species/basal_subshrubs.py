"""A woody basal crown bearing slender, leafy reproductive shoots.

Display proportions/counts are calibration, not a rhizome spread model or
predictions of real annual shoot production. Every axis belongs to one plant.
"""
import math
import random


def basal_subshrub_profile(value):
    return basal_shoot_profile(value, "basal_subshrub", .03)


def basal_shoot_profile(value, form, maximum_leaf_width):
    """Shared bounded crown dimensions; the caller supplies its body plan."""
    if not isinstance(value, dict) or value.get("form") != form:
        return None
    ranges = {"basal_radius_m": (0., .2), "stem_radius_m": (.0005, .015),
              "leaf_width_m": (.001, maximum_leaf_width), "branching_start_fraction": (0., .8),
              "crown_radius_ratio": (.05, .6)}
    for key, (lo, hi) in ranges.items():
        x = value.get(key)
        if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or not lo <= x <= hi:
            return None
    for key, lo, hi in (("basal_shoot_count", 1, 12), ("nodes_per_shoot", 6, 36)):
        x = value.get(key)
        if isinstance(x, bool) or not isinstance(x, int) or not lo <= x <= hi:
            return None
    transition = {}
    upper = value.get("upper_leaf_arrangement")
    fraction = value.get("leaf_arrangement_transition_fraction")
    if upper is not None or fraction is not None:
        if (upper not in {"alternate", "opposite"}
                or isinstance(fraction, bool) or not isinstance(fraction, (int, float))
                or not math.isfinite(fraction) or not 0.0 <= fraction <= 1.0):
            return None
        transition = {"upper_leaf_arrangement": upper,
                      "leaf_arrangement_transition_fraction": float(fraction)}
    return {"form": form, "version": 1,
            **{k: float(value[k]) for k in ranges},
            "basal_shoot_count": value["basal_shoot_count"], "nodes_per_shoot": value["nodes_per_shoot"],
            **transition,
            "status": str(value.get("status") or "qualitative_display_recipe")}


def grow_basal_subshrub(sim, placements, maturity, lod, life, paths, clusters, attachments):
    p = sim.blueprint.growth["basal_subshrub_profile"]
    return grow_basal_shoots(sim, p, "basal_subshrub", placements, maturity, lod, life, paths, clusters, attachments)


def grow_basal_shoots(sim, p, body_plan, placements, maturity, lod, life, paths, clusters, attachments):
    """One plant crown, independent axes, shared iterative shoot sockets."""
    root = sim._growth_origin(placements)
    count = max(1, round(p["basal_shoot_count"] * max(0., min(1., maturity)) ** .55))
    height = sim.blueprint.growth[body_plan + "_height_m"]
    maximum = sim.blueprint.growth["max_height_m"]
    rng = random.Random(sim.seed ^ 18037)
    for index in range(count):
        angle = index * 2.3999632297 + rng.uniform(-.25, .25)
        scale = height / maximum * rng.uniform(.78, 1.05)
        reach = height * p["crown_radius_ratio"] * maturity * (index + .5) / count
        radius = p["basal_radius_m"] * math.sqrt(maturity)
        sim._grow_iterative_forb(
            placements, maturity, lod, random.Random(sim.seed ^ (index + 1) * 1000003),
            root_index=root, origin_xy=(math.cos(angle)*radius, math.sin(angle)*radius),
            height_factor=scale, axis_phase=math.degrees(angle),
            axis_lean_xy=(math.cos(angle)*reach, math.sin(angle)*reach),
            terminal_branch_flowering=True, flowering_factor=life["reproductive_factor"],
            fruiting_factor=life["fruiting_factor"], leaf_factor=life.get("leaf_factor", 1.),
            placement_paths=paths, leaf_clusters=clusters, attachment_points=attachments,
            placement_orientations=sim._placement_orientation_hints,
        )
    return {body_plan + "_version": 1, "basal_shoot_count": count,
            "reproductive_display_unit": "flower_or_retained_fruit_head" if body_plan == "basal_herb" else "capitulum_or_pappus_head"}
