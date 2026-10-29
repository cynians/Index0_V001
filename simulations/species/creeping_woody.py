"""Bounded ground runners with ascending, branching leafy short shoots.

The optional recipe describes architecture, never species identity. Dimensions
are metres; visual-fit controls are independent of botanical trait ranges.
"""
import math


def creeping_woody_profile(value):
    if not isinstance(value, dict) or value.get("form") != "creeping_woody":
        return None
    bounds = {"runner_length_m": (.04, 2.), "stem_radius_m": (.0002, .01),
              "shoot_spacing_m": (.008, .4), "shoot_lift_fraction": (0., 1.),
              "leaf_spacing_m": (.0004, .02), "leaf_width_m": (.0002, .02),
              "runner_branch_length_fraction": (.1, .8),
              "runner_foliage_fraction": (0., 1.)}
    for key, (low, high) in bounds.items():
        v = value.get(key)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not low <= v <= high:
            return None
    for key, high in (("shoot_branch_count", 4), ("runner_branch_count", 2)):
        count = value.get(key)
        if isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= high:
            return None
    return {"form": "creeping_woody", "version": 1,
            **{key: float(value[key]) for key in bounds},
            **{key: value[key] for key in ("shoot_branch_count", "runner_branch_count")},
            "status": str(value.get("status") or "provisional_visual_fit")}


def grow_creeping_woody(sim, placements, maturity, lod, rng, attachment_points,
                       placement_paths, leaf_clusters, rooting_contacts,
                       flowering_factor, fruiting_factor, fruit_ripeness):
    g = sim.blueprint.growth
    p = g["creeping_woody_profile"]
    spread = str(g.get("clonal_spread") or "other_unknown")
    mature_axes = {"none": 1, "low": 2, "moderate": 4, "high": 6}.get(spread, 1)
    axes = 1 + round((mature_axes - 1) * maturity)
    reach = p["runner_length_m"] * max(.08, maturity)
    height = g["creeping_woody_height_m"] * p["shoot_lift_fraction"] * max(.08, maturity)
    root = sim._growth_origin(placements)
    leaf_length = sim.blueprint.module("leaf").length_m
    leaf_area = leaf_length * p["leaf_width_m"] * .72
    phase = rng.uniform(0., 360.)
    total_length = max_radius = 0.
    ascending = secondary = leaf_samples = contacts = flowers = fruits = 0
    axils = []

    def segment(parent, start, end, angle, order, leafy):
        nonlocal total_length, max_radius, leaf_samples
        path = sim._curved_segment_path(start, end, bend=min(.003, math.dist(start, end)*.1), direction=1.)
        index = sim._add(placements, "stem_section" if order == 0 else "branch_section",
                         parent, *end, angle, .65 + .35*maturity, order,
                         placement_paths=placement_paths, path=path)
        length = sum(math.dist(a, b) for a, b in zip(path, path[1:]))
        total_length += length
        max_radius = max(max_radius, math.hypot(end[0], end[1]))
        if not leafy:
            return index
        count = max(1, round(length / p["leaf_spacing_m"]))
        sample_indices = []
        # No RNG is consumed for visible samples: canonical structure is LOD invariant.
        samples = min(count, 24 if lod >= 2 else 3 if lod >= 1 else 0)
        for j in range(samples):
            t = (j+1)/(samples+1)
            path_t = t*(len(path)-1)
            path_i = min(len(path)-2, int(path_t))
            position = tuple(a+(b-a)*(path_t-path_i)
                             for a, b in zip(path[path_i], path[path_i+1]))
            rotation = angle + (index*137.507764+j*120.) % 360.
            leaf = sim._add(placements, "leaf", index, *position, rotation, 1., order+1)
            theta = math.radians(rotation)
            sim._placement_orientation_hints[str(leaf)] = sim._orientation_frame((math.cos(theta), math.sin(theta), .25))
            sample_indices.append(leaf)
            leaf_samples += 1
            if attachment_points is not None:
                attachment_points.append({"stem_placement_index": index, "leaf_placement_index": leaf,
                    "socket": "leaf", "position_m": [round(v, 4) for v in position], "side": "radial", "rotation_deg": rotation % 360.})
        if leaf_clusters is not None:
            centre = tuple((a+b)*.5 for a, b in zip(start, end))
            cid = sim._add_leaf_cluster(leaf_clusters, index, *centre, count, leaf_area*count, order, visual_density=1.)
            leaf_clusters[-1].update({"explicit_samples": True, "sample_placement_indices": sample_indices,
                                     "dense_shoot_envelope": True, "leaf_length_m": leaf_length,
                                     "organ_structure": str(g.get("leaf_structure") or "other_unknown")})
            if attachment_points is not None and sample_indices:
                for attachment in attachment_points[-len(sample_indices):]:
                    attachment["cluster_id"] = cid
        if order >= 1 and len(axils) < 500:
            axils.append((index, end, angle))
        return index

    def shoot(parent, start, angle, lift, extent, order):
        nodes = max(2, min(12, math.ceil(math.hypot(lift, extent)/.02)))
        previous = start
        branch_starts = []
        for j in range(nodes):
            t = (j+1)/nodes
            theta = math.radians(angle+8.*math.sin(t*math.pi))
            end = (start[0]+math.cos(theta)*extent*t, start[1]+math.sin(theta)*extent*t,
                   start[2]+lift*t)
            parent = segment(parent, previous, end, angle, order, True)
            if j in {max(0, round(nodes*f)-1) for f in (.35, .6, .8)}:
                branch_starts.append((parent, end))
            previous = end
        return branch_starts

    def runner(parent, start, angle, length, order, axis):
        nonlocal ascending, secondary, contacts
        nodes = max(2, min(24 if order == 0 else 12, math.ceil(length/p["shoot_spacing_m"])))
        previous = start
        lateral_starts = []
        for j in range(nodes):
            t = (j+1)/nodes
            theta = math.radians(angle+9.*math.sin(t*math.pi+axis))
            end = (start[0]+math.cos(theta)*length*t, start[1]+math.sin(theta)*length*t, .006+.002*math.sin(t*math.pi))
            parent = segment(parent, previous, end, angle, order, t > 1.-p["runner_foliage_fraction"])
            if j in {max(0, round(nodes*f)-1) for f in (.3, .6)}:
                lateral_starts.append((parent, end))
            if rooting_contacts is not None and spread in {"moderate", "high"} and j % 3 == 1:
                rooting_contacts.append({"parent_index": parent, "position": [end[0], end[1], 0.]})
                contacts += 1
            ascending += 1
            shoot_angle = angle+rng.uniform(-100., 100.)
            starts = shoot(parent, end, shoot_angle, height*rng.uniform(.5, 1.),
                           min(.08, length*.18)*rng.uniform(.6, 1.), 1)
            for branch in range(min(len(starts), p["shoot_branch_count"])):
                secondary += 1
                branch_parent, branch_start = starts[branch]
                shoot(branch_parent, branch_start, shoot_angle+(-1 if branch % 2 else 1)*rng.uniform(45., 105.),
                      height*rng.uniform(.15, .28), min(.065, length*.15), 2)
            previous = end
        if order == 0:
            for branch, (branch_parent, branch_start) in enumerate(lateral_starts[:p["runner_branch_count"]]):
                secondary += 1
                runner(branch_parent, branch_start, angle+(-1 if branch % 2 else 1)*rng.uniform(65., 100.),
                       length*p["runner_branch_length_fraction"], 1, axis)

    for axis in range(axes):
        runner(root, (0., 0., .006), phase+axis*137.507764+rng.uniform(-16., 16.),
               reach*rng.uniform(.72, 1.), 0, axis)

    profile = g.get("reproductive_profile")
    if profile and g.get("reproductive_mode") in {"sexual", "both", "apomictic"} and g.get("flowering_position") in {"lateral", "mixed"}:
        for rank, (parent, end, angle) in enumerate(axils):
            if rank % 4:
                continue
            score = (rank*.61803398875+.17) % 1.
            kind = "fruit" if fruiting_factor > .02 and score < fruiting_factor else "flower" if flowering_factor > .05 else None
            if kind:
                offset = profile[kind+"_size_m"]*.5
                theta = math.radians(angle+90.)
                socket = (end[0]+math.cos(theta)*offset, end[1]+math.sin(theta)*offset, end[2])
                sim._add(placements, kind, parent, *socket, angle, .4+.6*fruit_ripeness if kind == "fruit" else 1., 3)
                flowers += kind == "flower"
                fruits += kind == "fruit"
    return {"creeping_woody_profile_version": p["version"], "creeping_axis_count": axes,
            "creeping_secondary_axis_count": secondary, "creeping_ascending_axis_count": ascending,
            "creeping_leaf_socket_count": leaf_samples, "creeping_footprint_radius_m": round(max_radius, 4),
            "creeping_leaf_socket_offset_m": 0., "creeping_axis_length_m": round(reach, 4),
            "creeping_total_axis_length_m": round(total_length, 4), "structural_axis_length_m": total_length,
            "creeping_rooting_contact_count": contacts, "creeping_flower_count": flowers, "creeping_fruit_count": fruits}
