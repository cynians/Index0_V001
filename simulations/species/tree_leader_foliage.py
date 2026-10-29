"""Foliage on the terminal module of each living tree leader.

The coarse tree axis has no dated internodes. Its last structural segment is
therefore the bounded terminal module, not a claim about current-year length.
One calculative cohort per leader uses the same leaf dimensions and fascicle
rules as lateral shoots. Display sockets never multiply its leaf area.
"""
import math


def add_tree_leader_foliage(sim, placements, clusters, attachments, maturity, lod,
                           detail=False, leaf_factor=1.0, placement_paths=None):
    growth = sim.blueprint.growth
    distribution = growth.get("leaf_distribution", "terminal_cluster")
    if (maturity < .04 or leaf_factor <= 0 or
            distribution in {"basal_tuft", "basal_rosette", "none"}):
        return
    leaf = sim.blueprint.module("leaf")
    if leaf is None:
        return
    stems = {i for i, p in enumerate(placements) if p[0] == "stem_section" and p[7] == 1}
    parents = {placements[i][1] for i in stems}
    tips = sorted(stems - parents)
    density = max(0., min(1., float(growth.get("leaf_cluster_density", .5) or 0)))
    fascicled = growth.get("leaf_arrangement") == "fascicled"
    bundle_size = max(1, min(12, int(growth.get("fascicle_size", 3) or 3))) if fascicled else 1
    needle = (leaf.visual or {}).get("leaf_structure") == "needle_like"
    unit_area = leaf.length_m * max(.0004, leaf.radius_m * 2) if needle else leaf.length_m ** 2 * .45
    scale = .95 * (.65 + .35 * maturity)
    if growth.get('planar_spray_version') and growth.get('shoot_dimorphism')=='axial_and_peripheral_shoots':
        from simulations.species.planar_sprays import grow_planar_spray
        for tip in tips:
            grow_planar_spray(sim,placements,tip,0.,900000+tip,maturity,lod,clusters,
                             attachments,placement_paths if placement_paths is not None else {},leaf_factor,detail,leader=True)
        return
    for tip in tips:
        base = placements[tip][1]
        if base not in stems:
            continue
        start, end = placements[base][2:5], placements[tip][2:5]
        length = math.dist(start, end)
        if length <= 1e-9:
            continue
        tangent = tuple((end[j] - start[j]) / length for j in range(3))
        # A vertical leader needs a real transverse frame; crossing its
        # tangent with world-z alone produces the zero vector.
        frame = sim._orientation_frame(tangent)
        side, up = frame["right"], frame["up"]
        lower = .55 if distribution in {"terminal_cluster", "branch_tips"} else .12
        count = max(1, round(7 * min(1., leaf_factor)))
        fractions = [lower + (1 - lower) * (i + 1) / count for i in range(count)]
        points = [tuple(start[j] + (end[j] - start[j]) * f for j in range(3)) for f in fractions]
        estimated = count * bundle_size if fascicled else count * (2 + round(10 * density))
        midpoint = tuple((points[0][j] + end[j]) * .5 for j in range(3))
        cluster_id = sim._add_leaf_cluster(clusters, tip, *midpoint, estimated,
                                         estimated * unit_area * scale ** 2, 0, density)
        cohort = clusters[-1]
        cohort.update({"shoot_type": "long", "shoot_role": "leader", "identity": 900000 + tip,
                       "leader_base_index": base, "leader_tip_index": tip,
                       "shoot_start_m": list(points[0]), "shoot_end_m": list(end),
                       "shoot_direction": list(tangent), "angle": math.atan2(tangent[1], tangent[0]),
                       "length": math.dist(points[0], end), "explicit_samples": False,
                       "sample_placement_indices": [], "leaf_arrangement": growth.get("leaf_arrangement"),
                       "fascicle_size": bundle_size if fascicled else 0,
                       "fascicle_count": count if fascicled else 0})
        if (leaf.visual or {}).get("leaf_structure") in {"needle_like", "scale_like"}:
            # These are views of ONE cohort, including the exact terminal
            # socket so even a sparse crown has a leafy apex.
            indices = dict.fromkeys([count - 1] + [round(i * (count - 1) / 3) for i in range(3)])
            cohort["visual_positions_m"] = [list(points[i]) for i in indices]
        if not detail or lod == 0:
            continue
        host = base
        samples = []
        for i, point in enumerate(points):
            host = sim._add(placements, "branch_section", host, *point, 0, .0006, 4)
            if lod == 1 and i % 2:
                continue
            for n in range(min(2, bundle_size) if lod == 1 else bundle_size):
                azimuth = math.radians(float(growth.get("phyllotaxis_deg", 137.5))) * i + .7 + n * math.tau / bundle_size
                forward = sim._normalise_vector(tuple(
                    (side[j] * math.cos(azimuth) + up[j] * math.sin(azimuth)) * (.32 if fascicled else 1.)
                    + tangent[j] * (.92 if fascicled else .35) for j in range(3)))
                rotation = math.degrees(math.atan2(-(forward[0] + forward[1] * 1.8), forward[2]))
                index = sim._add(placements, "leaf", host, *point, rotation, scale, 6)
                sim._placement_orientation_hints[str(index)] = sim._orientation_frame(forward)
                samples.append(index)
                attachments.append({"stem_placement_index": host, "leaf_placement_index": index,
                                    "cluster_id": cluster_id, "socket": "leaf", "position_m": list(point),
                                    "shoot_type": "long", "shoot_role": "leader"})
        cohort.update(explicit_samples=bool(samples), sample_placement_indices=samples)
