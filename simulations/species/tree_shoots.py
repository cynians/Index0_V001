"""Woody crown with current shoots and node-based foliage cohorts.

Foliage is stored as ``leaf_clusters`` (a calculative cohort: estimated leaf
count, leaf area, position) rather than one simulation object per leaf. By
default (``detail=False``) a shoot also collapses to a single coarse spine
segment instead of one segment per leaf, since a mature crown otherwise
generates thousands of near-identical structural placements purely to give
per-leaf sprites somewhere to hang. ``detail=True`` reruns the exact same
per-leaf geometry used originally (full spine subdivision, one placement per
leaf) and is reserved for close-up diagnostics that need authentic shoot
geometry, not for the default whole-tree/forest render path.
"""
import math
import random
from simulations.species.forest_ecology import branch_response


def grow_tree_shoots(sim, placements, maturity, lod, clusters, attachments, paths, flowering_factor=0., detail=False):
    g = sim.blueprint.growth
    h = float(g["max_height_m"]) * max(.025, maturity)
    def trait(name, default):
        value = g.get(name)
        return max(0., min(1., float(default if value is None else value)))
    openness, droop = trait("crown_openness",.5), trait("branch_droop",.3)
    density, twig_density = trait("leaf_cluster_density",.5), trait("fine_twig_density",.5)
    spacing = trait("leaf_spacing_bias",.5)
    apical_control = trait("apical_control", .72)
    distribution = g.get("leaf_distribution", "along_shoot")
    dimorphic = g.get("shoot_dimorphism") == "long_and_short_shoots"
    axis_continuity = str(g.get("axis_continuity") or "other_unknown")
    branching_rhythm = str(g.get("branching_rhythm") or "other_unknown")
    branching_timing = str(g.get("branching_timing") or "other_unknown")
    lateral_orientation = str(g.get("lateral_axis_orientation") or "other_unknown")
    flowering_position = str(g.get("flowering_position") or "other_unknown")
    leaf_length = sim.blueprint.module("leaf").length_m
    root = sim._add(placements,"root",-1,0,0,-.08,0,1,0)

    # Structural axis length excludes leafy-shoot spines on purpose: a
    # current-year leafy twig isn't standing woody biomass, and this figure
    # must stay stable regardless of how finely a shoot's spine happens to be
    # subdivided for rendering (see SpeciesSimulation.get_ecological_outcome).
    axis_length_m = [0.0]

    def segment(parent, end, order, radius, curved=False):
        start = placements[parent][2:5]
        path = sim._curved_segment_path(start,end,bend=math.dist(start,end)*.06,
                                       direction=1 if end[0]>=start[0] else -1) if curved else None
        return sim._add(placements,"stem_section" if order==0 else "branch_section",
                        parent,*end,0,radius,order+1,placement_paths=paths,path=path)

    def axis(parent,end,order,radius,steps=3):
        start = placements[parent][2:5]
        nodes=[]
        for i in range(1,steps+1):
            t=i/steps
            point=[start[j]+(end[j]-start[j])*t for j in range(3)]
            point[2]+=math.sin(t*math.pi)*math.dist(start,end)*.09
            step_start = placements[parent][2:5]
            parent=segment(parent,point,order,radius*(1-.55*t),curved=order<2)
            axis_length_m[0] += math.dist(step_start, point)
            nodes.append(parent)
        return nodes

    def leader_axis():
        """Build one leader while retaining the visible history of axis succession."""

        parent = root
        nodes = []
        height_factor = .88 if axis_continuity == "monopodial_to_sympodial" else .92
        for i in range(1, 13):
            t = i / 12
            transition = max(0., (t - .5) / .5)
            if axis_continuity == "sympodial":
                offset = h * (.0025 + .0075 * t)
            elif axis_continuity == "monopodial_to_sympodial":
                offset = h * .014 * transition
            else:
                offset = h * .0015 * t
            end = (
                h * .012 * t + math.sin(i * 1.71) * offset,
                math.cos(i * 1.37) * offset * .72,
                h * height_factor * t,
            )
            start = placements[parent][2:5]
            parent = segment(parent, end, 0, max(.04, h * .014) * (1 - .55 * t), curved=True)
            axis_length_m[0] += math.dist(start, end)
            nodes.append(parent)
        return nodes

    trunk=leader_axis()
    if maturity<.04:
        return {"structural_axis_length_m": axis_length_m[0]}

    def leafy_shoot(parent,angle,length,short,identity):
        local=random.Random(sim.seed*1009+identity)
        start=placements[parent][2:5]
        count=4 if short else 7
        target=(start[0]+math.cos(angle)*length,start[1]+math.sin(angle)*length,
                start[2]+length*(.32-droop*.5))
        tangent=sim._normalise_vector(tuple(target[j]-start[j] for j in range(3)))
        side=sim._normalise_vector((-tangent[1],tangent[0],0))
        up=(-tangent[2]*side[1],tangent[2]*side[0],tangent[0]*side[1]-tangent[1]*side[0])
        shoot_type = "short" if short else "long"
        mean_scale = .95*(.65+.35*maturity)

        if not detail:
            # Coarse default: one spine segment, no per-leaf placements. The
            # cluster keeps enough (identity/angle/length/shoot_type) to
            # regenerate the exact detailed geometry later via detail=True.
            shoot_parent=segment(parent,target,4 if short else 3,.0015*(1-.6*.5))
            midpoint=[(start[j]+target[j])/2 for j in range(3)]
            estimated=count*(2+round(10*density))
            leaf_area=estimated*leaf_length**2*.45*mean_scale**2
            cluster_id=sim._add_leaf_cluster(clusters,shoot_parent,*midpoint,estimated,
                                             leaf_area,4 if short else 3,density)
            clusters[-1].update({"explicit_samples":False,"sample_placement_indices":[],
                                 "shoot_type":shoot_type,"identity":identity,
                                 "angle":angle,"length":length})
            flower = sim.blueprint.module("flower")
            terminal_flower = flowering_position == "terminal" and not short
            if lod >= 2 and flowering_factor > 0 and flower and flower.asset_ref and (short or terminal_flower):
                sim._add(placements,"flower",shoot_parent,*target,0,.65+.35*flowering_factor,6)
            return

        shoot_parent=parent
        points,leaves,hosts,scales=[],[],[],[]
        for i in range(count):
            f=(i+1)/count
            if distribution in {"terminal_cluster","branch_tips"} or short:
                f=.55+.45*f
            else:
                f=.12+.88*f**(1.7-spacing)
            point=[start[j]+(target[j]-start[j])*f for j in range(3)]
            shoot_parent=segment(shoot_parent,point,4 if short else 3,.0015*(1-.6*f))
            azimuth=i*math.radians(float(g.get("phyllotaxis_deg",137.5)))+.7
            forward=sim._normalise_vector(tuple(side[j]*math.cos(azimuth)+up[j]*math.sin(azimuth)+tangent[j]*.35 for j in range(3)))
            rotation=math.degrees(math.atan2(-(forward[0]+forward[1]*1.8),forward[2]))
            scale=local.uniform(.82,1.08)*(.65+.35*maturity)
            scales.append(scale)
            points.append(point)
            hosts.append(shoot_parent)
            if lod==0 or (lod==1 and i%2):
                continue
            leaf=sim._add(placements,"leaf",shoot_parent,*point,rotation,scale,6)
            sim._placement_orientation_hints[str(leaf)]=sim._orientation_frame(forward)
            leaves.append(leaf)
        midpoint=points[len(points)//2]
        estimated=count*(2+round(10*density))
        cluster_id=sim._add_leaf_cluster(clusters,hosts[0],*midpoint,estimated,
                                         estimated*leaf_length**2*.45*sum(s*s for s in scales)/count,4 if short else 3,density)
        clusters[-1].update({"explicit_samples":bool(leaves),"sample_placement_indices":leaves,
                             "shoot_type":shoot_type,"identity":identity,
                             "angle":angle,"length":length})
        for leaf in leaves:
            host=placements[leaf][1]
            attachments.append({"stem_placement_index":host,"leaf_placement_index":leaf,
                                "cluster_id":cluster_id,"socket":"leaf","position_m":list(placements[host][2:5]),
                                "shoot_type":shoot_type})
        flower = sim.blueprint.module("flower")
        terminal_flower = flowering_position == "terminal" and not short
        if lod >= 2 and flowering_factor > 0 and flower and flower.asset_ref and (short or terminal_flower):
            sim._add(placements,"flower",shoot_parent,*points[-1],0,.65+.35*flowering_factor,6)

    branch_count=max(3,round((15-5*openness)*maturity))
    if branching_rhythm == "rhythmic":
        # Rhythmic branching is expressed as paired modules on discrete
        # leader tiers. Opposite leaves/buds rotate successive pairs by 90°.
        branch_count = max(4, 2 * round(branch_count / 2))
    for b in range(branch_count):
        local=random.Random(sim.seed*65537+b)
        if branching_rhythm == "rhythmic":
            tier_count = max(2, branch_count // 2)
            tier = b // 2
            fraction = tier / max(1, tier_count - 1)
        elif branching_rhythm == "diffuse":
            fraction = max(0., min(1., (b + local.uniform(-.34, .34)) / max(1, branch_count - 1)))
        else:
            fraction=b/max(1,branch_count-1)
        host=trunk[min(10,2+round(fraction*8))]
        start=placements[host][2:5]
        if branching_rhythm == "rhythmic":
            quarter_turn = math.pi * .5 if g.get("leaf_arrangement") == "opposite" else 2.39996
            angle = (b // 2) * quarter_turn + (b % 2) * math.pi + local.uniform(-.08, .08)
        else:
            angle=b*2.39996+local.uniform(-.2,.2)
        retention, turn = branch_response(sim.environment,angle,fraction)
        angle += turn
        envelope=math.sqrt(max(.08,1-((fraction-.42)/.70)**2))
        reach=h*.25*envelope*(1.12-.4*openness)*local.uniform(.82,1.18)
        reach *= 1.34 - .52 * apical_control
        reach *= .55+.45*retention
        rise_bias = {
            "orthotropic": .46,
            "mixed": .28,
            "plagiotropic": .10,
            "pendent": -.02,
        }.get(lateral_orientation, .18)
        primary_rise = reach * (rise_bias + .10 * fraction)
        if axis_continuity == "monopodial_to_sympodial" and fraction > .72:
            # Once terminal reproduction ends leader extension, the upper
            # lateral axes overtake it and become the next crown modules.
            primary_rise += reach * .34
        end=(start[0]+math.cos(angle)*reach,start[1]+math.sin(angle)*reach,
             min(h,start[2]+primary_rise-droop*h*.035))
        primary=axis(host,end,1,max(.012,h*.005),4)
        secondary_count = 2 + round(3 * twig_density)
        if branching_timing == "immediate":
            secondary_count += 1
        elif branching_timing == "delayed":
            secondary_count = max(2, secondary_count - 1)
        for s in range(secondary_count):
            host2=primary[min(3,1+s//2)]
            anchor=placements[host2][2:5]
            a2=angle+(-1 if s%2 else 1)*local.uniform(.45,1.1)
            reach2=reach*local.uniform(.30,.58)
            end2=(anchor[0]+math.cos(a2)*reach2,anchor[1]+math.sin(a2)*reach2,
                  min(h*1.03,anchor[2]+reach2*(local.uniform(.1,1.35)-droop*.3)))
            secondary=axis(host2,end2,2,max(.004,h*.0014),3)
            twig_count = 3 + round(3 * twig_density)
            if branching_timing == "immediate":
                twig_count += 1
            for t in range(twig_count):
                host3=secondary[t%3]
                p=placements[host3][2:5]
                a3=a2+local.uniform(-1.3,1.3)
                reach3=min(1.5,h*.055)*local.uniform(.55,1.)
                p3=(p[0]+math.cos(a3)*reach3,p[1]+math.sin(a3)*reach3,
                    p[2]+reach3*local.uniform(-droop,.65))
                twig_nodes=axis(host3,p3,3,.003,3)
                identity=b*100000+s*1000+t*10
                # Stable per-shoot draw preserves paired comparisons and LOD.
                retained = random.Random(sim.seed*1009+identity+991).random() < retention
                if retained:
                    leafy_shoot(twig_nodes[-1],a3,min(.65,leaf_length*5),False,identity)
                if retained and dimorphic and distribution=="mixed_long_short_shoots":
                    for n,host4 in enumerate(twig_nodes[1:]):
                        leafy_shoot(host4,a3+(-1 if n else 1)*.85,leaf_length*1.6,True,identity+n+1)

    return {"structural_axis_length_m": axis_length_m[0]}
