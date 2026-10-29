"""Read a wound-sized fungal substrate from a generated tree's own trunk.

This bridge never changes the host snapshot or authors a host association.
Material identity and the wound interval are explicit scene inputs.
"""
import math


def sample_axis(points, radii, distance):
    lengths=[math.dist(a,b) for a,b in zip(points,points[1:])]
    total=sum(lengths);distance=max(0.,min(total,float(distance)))
    offset=0.
    for i,length in enumerate(lengths):
        if offset+length>=distance or i==len(lengths)-1:
            fraction=(distance-offset)/max(1e-12,length)
            point=[points[i][a]+(points[i+1][a]-points[i][a])*fraction for a in range(3)]
            # Renderer sections have one physical radius, including all curved
            # samples inside that section. Retain that piecewise thickness.
            return point,radii[i+1],[(points[i+1][a]-points[i][a])/max(1e-12,length) for a in range(3)]
        offset+=length
    return list(points[0]),radii[0],[0.,0.,1.]


def wood_from_tree_snapshot(snapshot, blueprint, *, material, interval_m=(.6,1.8),
                            position_m=(0.,0.,0.), support_id="generated_tree_wound"):
    if blueprint.growth.get("shape") != "tree" or not blueprint.growth.get("shoot_distribution_grammar"):
        raise ValueError("Host tree must expose metric shoot-grammar trunk radii")
    placements=snapshot.placements
    candidates={i for i,p in enumerate(placements) if p[0]=="stem_section" and int(p[7])==1}
    if not candidates:return None
    children={}
    for i in candidates:children.setdefault(int(placements[i][1]),[]).append(i)
    roots=sorted(i for i in candidates if int(placements[i][1]) not in candidates)
    if not roots:return None
    chains=[]
    for root in roots:
        chain=[root]
        while children.get(chain[-1]) and len(chain)<512:
            next_index=max(children[chain[-1]],key=lambda i:(placements[i][4],-i))
            if next_index in chain:break
            chain.append(next_index)
        chains.append(chain)
    chain=max(chains,key=lambda c:(placements[c[-1]][4],-c[0]))
    parent=int(placements[chain[0]][1])
    origin=list(placements[parent][2:5]) if 0<=parent<len(placements) else [*placements[chain[0]][2:4],0.]
    # Current shoot-grammar sections store their physical radius directly.
    def radius(index):
        value=float(placements[index][6])
        return max(.001,value)
    points=[origin];radii=[radius(chain[0])]
    for index in chain:
        path=(snapshot.placement_paths or {}).get(str(index)) or [placements[index][2:5]]
        for point in path:
            if math.dist(points[-1],point)>1e-6:
                points.append(list(point));radii.append(radius(index))
    if len(points)<2:return None
    total=sum(math.dist(a,b) for a,b in zip(points,points[1:]))
    lo,hi=(float(v) for v in interval_m)
    if not all(math.isfinite(v) for v in (lo,hi,*position_m)) or lo<0 or hi<=lo:
        raise ValueError("Tree wound interval must be finite and ordered")
    hi=min(total,hi)
    if hi-lo<.01:return None
    cumulative=[0.]
    for a,b in zip(points,points[1:]):cumulative.append(cumulative[-1]+math.dist(a,b))
    start,rad,_=sample_axis(points,radii,lo);selected=[start];selected_radii=[rad]
    for i,distance in enumerate(cumulative):
        if lo<distance<hi:selected.append(points[i]);selected_radii.append(radii[i])
    end,rad,_=sample_axis(points,radii,hi);selected.append(end);selected_radii.append(rad)
    shifted=[[round(p[a]+float(position_m[a]),6) for a in range(3)] for p in selected]
    return {"id":support_id,"material":material,"start_m":shifted[0],"end_m":shifted[-1],
            "radius_m":max(selected_radii),"axis_points_m":shifted,"axis_radii_m":selected_radii,
            "attachment_facing_m":[1.8,-1.,0.],
            "source_species_id":snapshot.species_id,"source_snapshot_fingerprint":snapshot.blueprint_fingerprint,
            "source_seed":snapshot.seed,"source_age_days":snapshot.age_days,"source_lod":snapshot.lod,
            "source_trunk_placement_indices":chain,"wound_interval_m":[lo,hi],
            "support_source":"generated_host_trunk_paths_and_radii"}
