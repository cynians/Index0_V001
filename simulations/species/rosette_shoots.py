"""Bounded canonical shoots for rosette forbs with mixed leaf attachment.

Coefficients describe qualitative architecture, not measured botanical rates.
The complete graph is built before render LOD filtering so leaf area and axis
length remain the same in the organism and its ecological handoff.
"""

import math
import random


ROSETTE_SHOOT_GRAMMAR_VERSION = 2

ROSETTE_PROFILE_RANGES = {
    "internode_variation": (0.0, 0.65),
    "axis_deflection": (0.0, 0.25),
    "lateral_length_ratio": (0.05, 0.4),
    "secondary_branch_probability": (0.0, 1.0),
}


def rosette_shoot_profile(value):
    """Opt-in visual architecture, independent of species identity.

    Invalid/incomplete recipes stay unresolved. The bounds are display limits,
    not measured botanical ranges; zero deflection/variation/secondary density
    is meaningful and retained.
    """
    if not isinstance(value, dict) or value.get("form") != "branched_rosette":
        return None
    for key, (lower, upper) in ROSETTE_PROFILE_RANGES.items():
        number = value.get(key)
        if (isinstance(number, bool) or not isinstance(number, (int, float))
                or not math.isfinite(number) or not lower <= number <= upper):
            return None
    return {"form": value["form"], "version": ROSETTE_SHOOT_GRAMMAR_VERSION,
            **{key: value[key] for key in ROSETTE_PROFILE_RANGES},
            "status": str(value.get("status") or "qualitative_display_recipe")}


def _bounded(value, default, lower, upper):
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    if not math.isfinite(number):
        number = default
    return max(lower, min(upper, number))


def rosette_bolting_factor(growth, age_days):
    """Extend leafy shoots over the final 30% of the pre-flowering interval."""
    profile = growth.get("life_history") or {}
    start = _bounded(profile.get("reproductive_start_days"), 128.0, 1.0, 1e6)
    age = _bounded(age_days, 0.0, 0.0, 1e8)
    return max(0.0, min(1.0, (age - start * 0.7) / (start * 0.3)))


def build_rosette_shoots(growth, maturity, bolting_factor, flowering_factor, seed):
    """Return canonical modules with local parent indices and visibility levels.

Parent -1 denotes the caller's basal growth origin. Every other parent occurs
earlier in the graph; an organ is never more visible than its supporting axis.
"""
    maturity = _bounded(maturity, 0.0, 0.0, 1.0)
    bolt = _bounded(bolting_factor, 0.0, 0.0, 1.0)
    flowering = _bounded(flowering_factor, 0.0, 0.0, 1.0)
    height = _bounded(growth.get("max_height_m"), 0.45, 0.1, 20.0)
    internode = _bounded(growth.get("internode_length_m"), 0.16, 0.02, 2.0)
    phyllotaxis = _bounded(growth.get("phyllotaxis_deg"), 137.5, 0.0, 360.0)
    rng = random.Random(seed)
    phase = rng.uniform(0.0, 360.0)
    nodes = []
    axis_length = 0.0
    basal_count = max(3, int(round(5 + maturity * 7)))
    stem_leaf_count = branch_count = secondary_count = flower_count = 0
    profile = rosette_shoot_profile(growth.get("rosette_shoot_profile"))

    def add(kind, parent, position, angle, scale, min_lod, level, role):
        nonlocal axis_length
        position = tuple(float(value) for value in position)
        if kind in {"stem_section", "branch_section"}:
            start = nodes[parent]["position"] if parent >= 0 else (0.0, 0.0, 0.0)
            axis_length += math.dist(start, position)
        nodes.append({"kind": kind, "parent": parent, "position": position,
                      "angle": angle, "scale": scale, "min_lod": min_lod,
                      "level": level, "role": role})
        return len(nodes) - 1

    for index in range(basal_count):
        rank = index / max(1, basal_count - 1)
        angle = index * 137.5 + 19.0 * maturity
        radius = (0.006 + 0.018 * maturity) * (0.55 + 0.45 * rank)
        add("leaf", -1, (math.cos(math.radians(angle)) * radius,
                         math.sin(math.radians(angle)) * radius,
                         0.008 + 0.014 * maturity * (0.65 + 0.35 * rank)),
            angle, (0.60 + 0.40 * maturity) * (0.52 + 0.56 * rank), 1, 1, "basal_leaf")

    sexual = growth.get("reproductive_mode") in {"sexual", "both", "apomictic"}
    structure_known = growth.get("reproductive_structure") not in {None, "", "other_unknown"}
    can_flower = sexual and structure_known and flowering > 0.0
    terminal = growth.get("flowering_position") in {"terminal", "mixed"}
    lateral = growth.get("flowering_position") in {"lateral", "mixed"}

    def add_flower(parent, role):
        nonlocal flower_count
        if not can_flower:
            return
        p = nodes[parent]["position"]
        add("flower", parent, (p[0], p[1], p[2] + 0.002), 0.0,
            0.55 + 0.30 * flowering, 1, 2, role)
        flower_count += 1

    if bolt > 0.0 and maturity > 0.0:
        shoot_height = height * bolt * maturity
        node_count = min(14, max(1, math.ceil(shoot_height / internode)))
        parent = -1
        orientation = growth.get("lateral_axis_orientation", "other_unknown")
        rise = {"orthotropic": 1.25, "plagiotropic": 0.12, "mixed": 0.48,
                "pendent": -0.2}.get(orientation)
        # Unknown orientation does not invent a branching habit. Explicitly
        # unbranched/basal-leaved rosettes never select this grammar at all.
        branch_hosts = set(range(max(1, node_count // 3), node_count - 1))
        # Fixed random weights are normalised so the final height stays exact.
        # The profile adds no new nodes unless branching is explicitly known.
        fractions = [(i + 1) / node_count for i in range(node_count)]
        if profile:
            variation = profile["internode_variation"]
            weights = [rng.uniform(1 - variation, 1 + variation) for _ in fractions]
            total = sum(weights)
            fractions = [sum(weights[:i + 1]) / total for i in range(node_count)]
        main_xy = [0.0, 0.0]
        for ordinal in range(node_count):
            fraction = fractions[ordinal]
            angle = phase + ordinal * phyllotaxis
            rad = math.radians(angle)
            lean = height * bolt * 0.015 * fraction
            p = (math.cos(rad) * lean, math.sin(rad) * lean, shoot_height * fraction)
            if profile:
                previous_fraction = fractions[ordinal - 1] if ordinal else 0.0
                # A coherent leaning shoot with modest changes at its nodes,
                # rather than rotating every endpoint around a vertical pole.
                heading = math.radians(phase + rng.uniform(-65.0, 65.0))
                displacement = shoot_height * (fraction - previous_fraction) * profile["axis_deflection"]
                main_xy[0] += math.cos(heading) * displacement
                main_xy[1] += math.sin(heading) * displacement
                p = (*main_xy, shoot_height * fraction)
            stem = add("stem_section", parent, p, angle,
                       0.60 - 0.22 * fraction, 0, 1, "main_axis")
            leaves_per_node = max(1, min(4, int(_bounded(growth.get("leaves_per_node"), 1, 1, 4))))
            for leaf_index in range(leaves_per_node):
                leaf_angle = angle + leaf_index * 360.0 / leaves_per_node
                # Put the socket on the axis; length is expressed by scale,
                # never by floating the socket away from its parent stem.
                add("leaf", stem, p, leaf_angle,
                    (0.50 - 0.32 * fraction) * (0.6 + 0.4 * maturity),
                    1, 2, "stem_leaf")
                stem_leaf_count += 1
            if ordinal in branch_hosts and rise is not None and branch_count < 6:
                length = height * bolt * (0.36 - 0.22 * fraction)
                branch_angle = angle + rng.uniform(-18.0, 18.0)
                brad = math.radians(branch_angle)
                branch_parent = stem
                steps = (0.5, 1.0)
                branch_rise = rise
                if profile:
                    length = shoot_height * profile["lateral_length_ratio"] * (1 - .4 * fraction) * rng.uniform(.75, 1.35)
                    # Mixed axes include ascending and spreading shoots. Known
                    # horizontal/pendent habits keep their own signed rise.
                    branch_rise = (rng.uniform(1.1, 2.2) if orientation == "mixed"
                                   else rise * rng.uniform(.75, 1.25))
                    # Fit the entire ascending axis below the height envelope;
                    # clipping each endpoint separately creates flat top arms.
                    if branch_rise > 0:
                        branch_rise = min(branch_rise, .96 * (shoot_height - p[2]) / length)
                    steps = (.28, .64, 1.0)
                branch_nodes = []
                previous_step = 0.0
                for step in steps:
                    end = (p[0] + math.cos(brad) * length * step,
                           p[1] + math.sin(brad) * length * step,
                           max(0.03 * shoot_height, min(shoot_height, p[2] + length * branch_rise * step)))
                    if profile:
                        start = nodes[branch_parent]["position"]
                        turn = rng.uniform(-32., 32.) * profile["axis_deflection"] / .25
                        direction = brad + math.radians(turn)
                        delta = length * (step - previous_step)
                        end = (start[0] + math.cos(direction) * delta,
                               start[1] + math.sin(direction) * delta, end[2])
                    branch_parent = add("branch_section", branch_parent, end,
                                        branch_angle, 0.32 - 0.10 * step, 1, 2, "lateral_axis")
                    branch_nodes.append(branch_parent)
                    add("leaf", branch_parent, end, branch_angle + 105.0,
                        max(0.10, (0.35 - 0.20 * fraction) * (1.0 - 0.20 * step)),
                        1, 3, "stem_leaf")
                    stem_leaf_count += 1
                    if lateral and step == steps[-2]:
                        add_flower(branch_parent, "lateral_flower")
                    previous_step = step
                branch_count += 1
                if terminal:
                    add_flower(branch_parent, "terminal_flower")
                # One bounded second-order axis per primary: an open wiry
                # flowering framework, never recursively generated twigs.
                if profile and rng.random() < profile["secondary_branch_probability"]:
                    secondary_parent = branch_nodes[0]
                    start = nodes[secondary_parent]["position"]
                    secondary_angle = branch_angle + rng.choice((-1, 1)) * rng.uniform(45., 95.)
                    direction = math.radians(secondary_angle)
                    secondary_length = length * rng.uniform(.4, .7)
                    secondary_rise = branch_rise
                    if secondary_rise > 0:
                        secondary_rise = min(secondary_rise, .96 * (shoot_height - start[2]) / secondary_length)
                    for step in (.45, 1.0):
                        end = (start[0] + math.cos(direction) * secondary_length * step,
                               start[1] + math.sin(direction) * secondary_length * step,
                               max(.03 * shoot_height, min(shoot_height,
                                   start[2] + secondary_length * secondary_rise * step)))
                        secondary_parent = add("branch_section", secondary_parent, end,
                                               secondary_angle, .19 - .04 * step, 1, 3, "secondary_axis")
                        add("leaf", secondary_parent, end, secondary_angle + 105.,
                            .11 * (1.0 - .2 * step), 1, 3, "stem_leaf")
                        stem_leaf_count += 1
                        if lateral and step == .45:
                            add_flower(secondary_parent, "lateral_flower")
                    if terminal:
                        add_flower(secondary_parent, "terminal_flower")
                    secondary_count += 1
            if lateral and ordinal >= node_count // 2:
                add_flower(stem, "lateral_flower")
            parent = stem
        if terminal:
            add_flower(parent, "terminal_flower")

    stats = {"rosette_shoot_grammar_version": ROSETTE_SHOOT_GRAMMAR_VERSION,
             "rosette_bolting_factor": round(bolt, 4),
             "basal_leaf_count": basal_count, "cauline_leaf_count": stem_leaf_count,
             "rosette_lateral_axis_count": branch_count,
             "rosette_secondary_axis_count": secondary_count,
             "rosette_flower_count": flower_count,
             "structural_axis_length_m": round(axis_length, 6),
             "estimated_leaf_count": basal_count + stem_leaf_count}
    return nodes, stats
