"""Bounded curved culms and leafy branch complements for woody graminoids.

All coefficients are representative visual geometry, not measured growth
rates, node counts or biomass. Canonical cohorts are independent of LOD.
"""
import math
import random


GRAMMAR_VERSION = 1


def bounded(value, default, low=0.0, high=1.0):
    try:
        value = float(value)
    except (TypeError, ValueError):
        value = default
    if not math.isfinite(value):
        value = default
    return min(high, max(low, value))


def grow_woody_culm(sim, placements, parent, x, y, angle, maturity, lod,
                    height_factor=1.0, flowering_factor=0.0,
                    attachment_points=None, base_level=1, placement_paths=None,
                    leaf_clusters=None):
    growth = sim.blueprint.growth
    maturity = bounded(maturity, 0)
    max_height = bounded(growth.get("max_height_m"), 1, .1, 100)
    height = max_height * maturity * bounded(height_factor, 1, .02, 1)
    density = bounded(growth.get("fine_twig_density"), .35)
    foliage = bounded(growth.get("leaf_cluster_density"), .35)
    droop = bounded(growth.get("branch_droop"), .25)
    openness = bounded(growth.get("crown_openness"), .5)
    spacing = bounded(growth.get("leaf_spacing_bias"), .5)
    gradient = bounded(growth.get("branch_angle_gradient"), .35)
    straightness = bounded(growth.get("trunk_straightness"), .7)
    internode = bounded(growth.get("internode_length_m"), .18, .03, 2)
    sections = min(32, max(1, round(height / max(.25, internode))))
    # Stable spatial seed, independent of parent indices and clone RNG.
    rng = random.Random(int(sim.seed) ^ round(x*10000)*73856093
                        ^ round(y*10000)*19349663 ^ 104729)
    lean_angle = math.radians(angle + rng.uniform(-70, 70))
    bend = height * .18 * (1-straightness) * rng.uniform(.45, 1.1)
    lean_x, lean_y = math.cos(lean_angle), math.sin(lean_angle)

    def culm_point(t):
        offset = bend * (.18*t + .82*t**4)
        return (x + lean_x*offset, y + lean_y*offset,
                height*t - bend*.12*t**5)

    complement_count = min(sections, max(1, round((4+8*density)*maturity)))
    lower = .42 + .12*openness
    candidates = list(range(min(sections-1, round(lower*sections)), sections-1))
    branch_nodes = ({sections-1, *rng.sample(candidates, min(len(candidates), complement_count-1))}
                    if maturity > 0 else set())
    twig_count = max(1, min(7, round(2+5*density)))
    leaf_count = max(2, min(14, round(4+10*foliage)))
    leaf_module = sim.blueprint.module("leaf")
    leaf_length = bounded(leaf_module.length_m, .12, .002, 2)
    leaf_width = min(leaf_length*.2, 2*bounded(leaf_module.radius_m, .006, .001, .1))
    area_per_leaf = leaf_length*leaf_width*.65
    phyllotaxis = bounded(growth.get("phyllotaxis_deg"), 137.5, 0, 360)
    stem_parent = parent
    branch_sections = visible_leaves = 0

    def axis(kind, host, start, points, scale, level, rotation):
        return sim._add(placements, kind, host, *points[-1], rotation,
                        scale, level, placement_paths=placement_paths, path=points)

    for node in range(sections):
        t0, t1 = node/sections, (node+1)/sections
        start = placements[stem_parent][2:5]
        path = [culm_point(t0+(t1-t0)*fraction) for fraction in (.38, .72, 1)]
        stem = axis("stem_section", stem_parent, start, path,
                    (.65+.35*maturity)*(1-.35*t1), base_level, 0)
        origin = path[-1]
        if node in branch_nodes:
            rank = (t1-lower)/max(.01, 1-lower)
            reach = min(3.5, max(.12, height*.13)) * (1-.55*rank) * (.9+.25*openness)
            for branch_index in range(3):
                azimuth = angle + node*phyllotaxis + (branch_index-1)*42 + rng.uniform(-12, 12)
                radians = math.radians(azimuth)
                length = reach*rng.uniform(.72, 1.1)
                rise = length*(.12+.22*gradient)*rng.uniform(.7, 1.2)
                sag = length*(.15+1.15*droop)

                def branch_point(u):
                    return (origin[0]+math.cos(radians)*length*u,
                            origin[1]+math.sin(radians)*length*u,
                            max(.005, origin[2]+rise*u-sag*u*u))

                branch_parent = stem
                hosts = []
                for step in range(4):
                    u0, u1 = step/4, (step+1)/4
                    points = [branch_point(u0+(u1-u0)*f) for f in (.38, .72, 1)]
                    branch_parent = axis("branch_section", branch_parent,
                                         branch_point(u0), points, .28*(1-.4*u1),
                                         base_level+1, azimuth)
                    hosts.append(branch_parent)
                    branch_sections += 1

                for twig_index in range(twig_count):
                    u = (.22+.70*(twig_index+.5)/twig_count + rng.uniform(-.025, .025))
                    twig_start = branch_point(u)
                    host = hosts[min(3, int(u*4))]
                    side = -1 if twig_index % 2 else 1
                    twig_angle = azimuth + side*rng.uniform(28, 65)
                    tr = math.radians(twig_angle)
                    twig_length = length*rng.uniform(.32, .58)*(1-.25*u)
                    twig_sag = twig_length*(.28+1.2*droop)

                    def twig_point(v):
                        return (twig_start[0]+math.cos(tr)*twig_length*v,
                                twig_start[1]+math.sin(tr)*twig_length*v,
                                max(.005, twig_start[2]+twig_length*.10*v-twig_sag*v*v))

                    twig_parent = host
                    twig_hosts = []
                    for step in range(2):
                        v0, v1 = step/2, (step+1)/2
                        points = [twig_point(v0+(v1-v0)*f) for f in (.38, .72, 1)]
                        # The path begins at the axillary fork, not at the
                        # containing segment's endpoint.
                        if step == 0:
                            points.insert(0, twig_start)
                        twig_parent = axis("branch_section", twig_parent,
                                           twig_point(v0), points, .075*(1-.3*v1),
                                           base_level+2, twig_angle)
                        twig_hosts.append(twig_parent)
                        if step == 0:
                            sim._placement_orientation_hints[str(twig_parent)] = {
                                **sim._orientation_frame((math.cos(tr), math.sin(tr), -.3)),
                                "axis_origin": list(twig_start),
                            }
                        branch_sections += 1

                    # Generate all leaf poses even at LOD 0: canonical area
                    # and subsequent axis random choices cannot depend on view.
                    leaves = []
                    for leaf_index in range(leaf_count):
                        v = .12+.86*((leaf_index+.5)/leaf_count)**(.75+.5*spacing)
                        position = twig_point(v)
                        yaw = twig_angle + (leaf_index % 2*2-1)*rng.uniform(35, 65)
                        pitch = math.radians(rng.uniform(-55, 20)-15*droop)
                        yr = math.radians(yaw)
                        forward = [math.cos(yr)*math.cos(pitch), math.sin(yr)*math.cos(pitch), math.sin(pitch)]
                        scale = (.45+.55*math.sqrt(maturity))*rng.uniform(.65, 1.45)
                        leaves.append((position, yaw, forward, scale, twig_hosts[0 if v<=.5 else 1]))
                    count = len(leaves)
                    cluster_id = sim._add_leaf_cluster(
                        leaf_clusters, twig_parent, *twig_point(.65), count,
                        sum(area_per_leaf*leaf[3]**2 for leaf in leaves), 2,
                        visual_density=foliage)
                    if leaf_clusters is not None:
                        leaf_clusters[-1].update(explicit_samples=True, sample_placement_indices=[],
                                                 organ_structure="simple", woody_graminoid_spray=True)
                    for leaf_index, (position, yaw, forward, scale, host) in enumerate(leaves):
                        if lod < 1 or (lod == 1 and leaf_index % 2):
                            continue
                        leaf = sim._add(placements, "leaf", host, *position, yaw,
                                        scale, base_level+3)
                        sim._placement_orientation_hints[str(leaf)] = sim._orientation_frame(forward)
                        if attachment_points is not None:
                            attachment_points.append({"stem_placement_index": host,
                                "leaf_placement_index": leaf, "socket": "leaf",
                                "position_m": [round(c, 4) for c in position],
                                "rotation_deg": round(yaw, 3), "cluster_id": cluster_id})
                        if leaf_clusters is not None:
                            leaf_clusters[-1]["sample_placement_indices"].append(leaf)
                        visible_leaves += 1
        stem_parent = stem
    # Existing generic reproduction gate remains unresolved for missing organs.
    if lod >= 2 and flowering_factor > 0 and growth.get("reproductive_structure") not in {None, "", "other_unknown"}:
        sim._add(placements, "flower", stem_parent, *culm_point(1), 0,
                 .65+.35*flowering_factor, base_level+2)
    return {"culm_nodes": sections, "branch_sections": branch_sections,
            "visible_leaves": visible_leaves, "branch_complements": len(branch_nodes)}
