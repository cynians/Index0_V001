"""Opt-in seasonal leaf and axillary organ geometry for supported vines."""
import math
import random


BRANCHED_VINE_VERSION = 1
VINE_SHOOT_RANGES = {'node_spacing_m':(.05,.5),'lateral_length_m':(.05,2.),
    'lateral_budget_fraction':(0.,.5),'lateral_drop':(0.,1.),
    'ground_meander_m':(0.,1.),'ground_wavelength_m':(.3,5.)}
VINE_SHOOT_COUNTS = {'lateral_count':(0,24),'lateral_nodes':(2,12)}


def branched_vine_profile(value):
    if not isinstance(value,dict) or value.get('form')!='branched_vine':return None
    for key,(lo,hi) in {**VINE_SHOOT_RANGES,**VINE_SHOOT_COUNTS}.items():
        n=value.get(key)
        if (isinstance(n,bool) or not isinstance(n,(float,int)) or not math.isfinite(n)
            or not lo<=n<=hi or key in VINE_SHOOT_COUNTS and int(n)!=n):return None
    return {'form':'branched_vine','version':BRANCHED_VINE_VERSION,
        **{k:float(value[k]) for k in VINE_SHOOT_RANGES},
        **{k:int(value[k]) for k in VINE_SHOOT_COUNTS},
        'status':str(value.get('status') or 'qualitative_branch_posture_fit')}


def add_vine_laterals(sim,placements,hosts,maturity,budget,paths,attachments,add_organs):
    """One bounded generation of connected leafy lateral axes; no intrinsic host."""
    p=sim.blueprint.growth['branched_vine_profile']
    count=min(len(hosts),round(p['lateral_count']*maturity))
    if not count or budget<=0:return 0,0.
    rng=random.Random(f'{sim.seed}:vine_laterals');used=0.
    for k in range(count):
        # Spread branch origins over the persistent main axis, independent of
        # season and visible organ indices. Keep the first searching tip bare.
        host,start,azimuth,role=hosts[min(len(hosts)-1,round((k+1)*len(hosts)/(count+1)))]
        az=math.radians(azimuth)+rng.uniform(-.45,.45)
        length=min(p['lateral_length_m']*maturity*rng.uniform(.65,1.2),(budget-used)/(count-k))
        raw=[start]
        for j in range(1,p['lateral_nodes']+1):
            t=j/p['lateral_nodes'];sway=.10*math.sin(math.pi*t)
            raw.append((start[0]+length*(math.cos(az)*t-math.sin(az)*sway),
                        start[1]+length*(math.sin(az)*t+math.cos(az)*sway),
                        max(.045,start[2]+length*(.16*t-p['lateral_drop']*t*t))))
        actual=sum(math.dist(a,b) for a,b in zip(raw,raw[1:]))
        factor=min(1.,length/max(actual,1e-9))
        points=[tuple(start[q]+factor*(v[q]-start[q]) for q in range(3)) for v in raw]
        parent=host
        for j,(a,b) in enumerate(zip(points,points[1:])):
            used+=math.dist(a,b)
            parent=sim._add(placements,'branch_section',parent,*b,math.degrees(az),
                (.38+.18*maturity)*(1-.5*j/p['lateral_nodes']),2,
                placement_paths=paths,path=[a,b])
            sim._placement_orientation_hints[str(parent)]={'axis_role':'vine_lateral','min_render_lod':0}
            if attachments is not None:
                attachments.append({'stem_placement_index':host,'branch_placement_index':parent,
                    'socket':'lateral_shoot_base' if j==0 else 'lateral_node','position_m':list(a),
                    'side':role,'lateral_index':k})
            add_organs(parent,b,math.degrees(az)+90.,'lateral_shoot')
    return count,used


def add_vine_organs(sim, placements, stem, point, azimuth, ordinal, maturity, lod,
                    state, cohorts, attachments, side):
    growth = sim.blueprint.growth
    count = max(0, min(12, int(growth.get("leaves_per_node", 1))))
    leafy = (ordinal * 0.61803398875) % 1 < state.get("leaf_factor", 1.0)
    leaves = flowers = fruits = 0
    if leafy and count:
        leaves = count
        scale = 0.55 + 0.40 * maturity
        module = sim.blueprint.module("leaf")
        area = max(0.0005, module.length_m * module.radius_m * 1.8)
        cohort = sim._add_leaf_cluster(cohorts, stem, *point, count, count*area*scale, 0)
        cohorts[-1]["explicit_samples"] = True
        for j in range(count if lod >= 2 else min(1, count) if lod == 1 else 0):
            # Petiole bases lie on the host, with alternate blades diverging
            # around the local outward direction rather than floating off it.
            angle = azimuth + ((-1 if ordinal % 2 else 1)*55
                               if growth.get("leaf_arrangement") == "alternate" else j*360/count)
            tilt = math.radians(28 + 8*math.sin(ordinal*1.7))
            rad = math.radians(angle)
            leaf = sim._add(placements, "leaf", stem, *point, angle, scale, 2)
            sim._placement_orientation_hints[str(leaf)] = {
                "forward": [math.cos(rad)*math.cos(tilt), math.sin(rad)*math.cos(tilt), math.sin(tilt)],
                "model": "vine_axillary_leaf_v1",
            }
            if attachments is not None:
                attachments.append({"stem_placement_index": stem, "leaf_placement_index": leaf,
                                    "socket": "leaf", "position_m": list(point), "side": side,
                                    "rotation_deg": angle % 360, "cluster_id": cohort})
    profile = growth["reproductive_profile"]
    fertile = growth.get("reproductive_mode") in {"sexual", "both", "apomictic"}
    axillary = growth.get("flowering_position") in {"lateral", "mixed"}
    if not fertile or not axillary or ordinal < 3:
        return leaves, flowers, fruits
    if state.get("reproductive_factor", 0) > 0.05:
        flowers = 1
        if lod >= 2:
            flower = sim._add(placements, "flower", stem, *point, 0., 1., 3)
            sim._placement_orientation_hints[str(flower)] = {"forward": [0., 0., 1.], "model": "vine_axillary_cyme_v1"}
    if state.get("fruiting_factor", 0) > 0.02:
        fruits = 3
        if lod >= 2:
            for j in range(3):
                size = profile["fruit_size_m"]
                rad = math.radians(azimuth + 45*j - 45)
                socket = (point[0] + math.cos(rad)*size*0.4,
                          point[1] + math.sin(rad)*size*0.4, point[2] + (j-1)*size*0.75)
                fruit = sim._add(placements, "fruit", stem, *socket, 0., 0.7 + 0.3*state.get("fruit_ripeness", 0), 3)
                sim._placement_orientation_hints[str(fruit)] = {"forward": [0., 0., 1.], "model": "vine_axillary_capsule_v1"}
    return leaves, flowers, fruits
