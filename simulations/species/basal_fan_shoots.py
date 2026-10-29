"""Portable sparse basal foliage and a flat-topped flowering shoot.

The recipe separates documented organ dimensions/counts from qualitative
branch spread and model development. No taxon identity selects this grammar.
"""
import math
import random


GRAMMAR_VERSION = 2


def basal_fan_profile(value):
    if not isinstance(value, dict) or value.get("form") != "basal_fan_corymb":
        return None
    integers = {"basal_leaf_count": (1, 4), "cauline_leaf_count": (0, 4),
                "branch_count": (1, 12), "flowers_per_tip": (1, 2)}
    ranges = {"basal_leaf_length_m": (.005, 2), "cauline_leaf_length_m": (.002, 2), "leaf_width_m": (.0005, .1),
              "flower_size_m": (.002, .1), "fruit_size_m": (.001, .05), "branch_spread_fraction": (.05, .8),
              "branch_start_fraction": (.25, .8), "stem_radius_m": (.0001, .01)}
    for key, (lower, upper) in {**integers, **ranges}.items():
        number = value.get(key)
        if (isinstance(number, bool) or not isinstance(number, (int, float))
                or not math.isfinite(number) or not lower <= number <= upper
                or (key in integers and not isinstance(number, int))):
            return None
    return {"form": value["form"], "version": GRAMMAR_VERSION,
            **{key: value[key] for key in (*integers, *ranges)},
            "status": str(value.get("status") or "qualitative_display_recipe")}


def build_basal_fan_shoots(growth, maturity, extension, flowering, fruiting, seed):
    """Build the complete graph before LOD selection; lengths are metres."""
    profile = growth["basal_fan_profile"]
    rng = random.Random(seed)
    maturity, extension = max(0., min(1., maturity)), max(0., min(1., extension))
    height = growth["max_height_m"] * maturity * extension
    leaf_length = growth["basal_fan_leaf_length_m"]
    nodes = []
    axis_length = 0.
    phase = rng.uniform(0., math.tau)

    def add(kind, parent, position, scale=1., role="axis", angle=0., forward=None):
        nonlocal axis_length
        if kind in {"stem_section", "branch_section"}:
            start = nodes[parent]["position"] if parent >= 0 else (0., 0., 0.)
            axis_length += math.dist(start, position)
        nodes.append(dict(kind=kind, parent=parent, position=position, scale=scale,
                          role=role, angle=angle, min_lod=0 if kind.endswith("section") else 1,
                          forward=forward))
        return len(nodes)-1

    if maturity > 0:
        for i in range(profile["basal_leaf_count"]):
            az = phase + i * 2.5
            add("leaf", -1, (0., 0., .002*maturity), math.sqrt(maturity)*(1-.12*i),
                "basal_leaf", math.degrees(az), (math.cos(az), math.sin(az), .35))

    sexual = growth.get("reproductive_mode") in {"sexual", "both", "apomictic"}
    can_flower = (sexual and growth.get("reproductive_structure") == "flower"
                  and growth.get("flowering_position") in {"terminal", "mixed"})
    # The measured stature includes the corolla; the supporting axis stops
    # below that envelope. Crowding and branching coefficients are visual fits.
    shoot_height = max(0., height-profile["flower_size_m"]*maturity*extension)
    tips = []
    if shoot_height > 0:
        parent = -1
        stem_indices = []
        for i, fraction in enumerate((.25, .5, .72, 1.)):
            p = (height*.022*math.sin(i*1.7), height*.012*math.cos(i*1.7), shoot_height*fraction)
            parent = add("stem_section", parent, p, .8-.25*fraction)
            stem_indices.append(parent)
            if i == 1:
                for j in range(profile["cauline_leaf_count"]):
                    az = phase+math.pi+j*2.4
                    length_scale = min(1., profile["cauline_leaf_length_m"]/leaf_length)
                    add("leaf", parent, p, length_scale*math.sqrt(maturity)*extension,
                        "cauline_leaf", math.degrees(az), (math.cos(az)*.35, math.sin(az)*.35, 1.))
        tips.append(parent)
        for i in range(profile["branch_count"]):
            t = (i+.5)/profile["branch_count"]
            az = phase+i*2.39996323
            socket_fraction = profile["branch_start_fraction"] + .30*t
            socket = (height*.012*math.sin(i), 0., shoot_height*socket_fraction)
            base = add("branch_section", stem_indices[0 if socket_fraction < .5 else 1], socket, .4, "branch_base")
            radius = height*profile["branch_spread_fraction"]*(.7+.3*rng.random())
            end = (math.cos(az)*radius, math.sin(az)*radius,
                   shoot_height*(.92+.08*rng.random()))
            middle = tuple((a+b)*.5 for a,b in zip(socket,end))
            branch = add("branch_section", base, middle, .36, "flowering_branch")
            tip = add("branch_section", branch, end, .25, "flowering_branch")
            tips.append(tip)
        if can_flower:
            for i, parent in enumerate(tips):
                p = nodes[parent]["position"]
                for j in range(profile["flowers_per_tip"]):
                    az = phase+i*2.4+j*math.pi
                    # Paired short ultimate branchlets carry individual flowers.
                    offset = profile["flower_size_m"]*.30*j
                    end = (p[0]+math.cos(az)*offset, p[1]+math.sin(az)*offset, p[2]+.001)
                    branchlet = add("branch_section", parent, end, .18, "ultimate_branchlet")
                    # Cohorts replace flowers with capsules; the default
                    # perennial clock is not a measured flowering calendar.
                    transition = .30+.45*(i+j*.5)/max(1., len(tips)-.5)
                    if flowering > 0 and fruiting < transition:
                        add("flower", branchlet, end, .8+.2*flowering, "terminal_flower",
                            forward=(math.cos(az)*.28, math.sin(az)*.28, 1.))
                    if fruiting >= transition:
                        add("fruit", branchlet, end, .6+.3*fruiting, "terminal_fruit")
    return nodes, {"basal_fan_grammar_version": GRAMMAR_VERSION,
                   "basal_leaf_count": sum(n["role"] == "basal_leaf" for n in nodes),
                   "cauline_leaf_count": sum(n["role"] == "cauline_leaf" for n in nodes),
                   "estimated_leaf_count": sum(n["kind"] == "leaf" for n in nodes),
                   "structural_axis_length_m": round(axis_length, 6),
                   "sympodial_flower_count": sum(n["kind"] == "flower" for n in nodes),
                   "sympodial_fruit_count": sum(n["kind"] == "fruit" for n in nodes)}
