"""Bounded basal vegetative shoots and erect racemose fertile shoots.

Counts and poses are display recipes, not calibrated organ production.
"""
import math

def dimorphic_herb_profile(value):
    if not isinstance(value,dict) or value.get('form')!='dimorphic_herb':
        return None
    ranges={'flowering_shoot_height_m':(.10,2.),'basal_shoot_length_m':(.015,.25),
            'basal_tip_lift_m':(0.,.08),'basal_leaf_scale':(.2,1.),
            'basal_leaf_width_scale':(.5,1.5),'stem_radius_m':(.0002,.01),
            'leaf_width_m':(.0005,.02),'fruiting_axis_scale':(1.,2.5)}
    integers={'flowering_shoot_count':(1,5),'stem_leaf_nodes':(3,32),
              'basal_shoot_count':(0,12),'basal_nodes_per_shoot':(2,12),
              'display_open_florets':(1,20)}
    for key,(lo,hi) in ranges.items():
        v=value.get(key)
        if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not lo<=v<=hi:
            return None
    for key,(lo,hi) in integers.items():
        v=value.get(key)
        if isinstance(v,bool) or not isinstance(v,int) or not lo<=v<=hi:
            return None
    return {'form':'dimorphic_herb','version':1,**{k:float(value[k]) for k in ranges},
            **{k:value[k] for k in integers},'status':str(value.get('status') or 'provisional_visual_fit')}

def grow_dimorphic_herb(sim,placements,maturity,life_state,rng,attachment_points,placement_paths,leaf_clusters):
    """Build canonical connected geometry once, independent of render LOD."""
    growth=sim.blueprint.growth
    profile=growth['dimorphic_herb_profile']
    root=sim._growth_origin(placements)
    leaf=sim.blueprint.module('leaf')
    area=max(1e-7,leaf.length_m*leaf.radius_m*2*.72)
    total_area=0.
    basal_leaves=stem_leaves=flower_count=fruit_count=0
    axis_count=max(1,round(profile['flowering_shoot_count']*maturity))
    basal_count=round(profile['basal_shoot_count']*maturity)

    def add_leaf(host,pos,angle,scale,cohort,width_scale=1.):
        nonlocal total_area,basal_leaves,stem_leaves
        index=sim._add(placements,'leaf',host,*pos,angle,scale,2)
        t=math.radians(angle)
        sim._placement_orientation_hints[str(index)]=sim._orientation_frame((math.cos(t),math.sin(t),.25))
        leaf_area=area*scale*scale*width_scale
        total_area+=leaf_area
        if cohort=='basal_vegetative': basal_leaves+=1
        else: stem_leaves+=1
        cid=sim._add_leaf_cluster(leaf_clusters,host,*pos,1,leaf_area,2)
        leaf_clusters[-1].update({'leaf_placement_index':index,'explicit_samples':True,
            'sample_placement_indices':[index],'cohort':cohort,
            'leaf_development':{'width_scale':width_scale,'length_scale':scale,
                                'area_scale':scale*scale*width_scale,'model':'dimorphic_herb_cohort_proxy'}})
        if attachment_points is not None:
            attachment_points.append({'stem_placement_index':host,'leaf_placement_index':index,
                'socket':'leaf','position_m':list(pos),'cohort':cohort,'cluster_id':cid})

    phase=rng.uniform(0.,360.)
    for k in range(basal_count):
        angle=phase+k*137.507764+rng.uniform(-12.,12.)
        t=math.radians(angle)
        length=profile['basal_shoot_length_m']*maturity*rng.uniform(.75,1.)
        nodes=max(1,round(profile['basal_nodes_per_shoot']*maturity))
        parent=root;previous=tuple(placements[root][2:5])
        for n in range(nodes):
            f=(n+1)/nodes
            pos=(math.cos(t)*length*f,math.sin(t)*length*f,
                 .006+profile['basal_tip_lift_m']*maturity*f*f)
            path=sim._curved_segment_path(previous,pos,bend=.002,direction=(-1 if k%2 else 1))
            host=sim._add(placements,'branch_section',parent,*pos,angle,1.,1,placement_paths=placement_paths,path=path)
            for side in (0,180):
                add_leaf(host,pos,angle+90+(n%2)*90+side,profile['basal_leaf_scale']*(.7+.3*maturity),
                         'basal_vegetative',profile['basal_leaf_width_scale'])
            parent=host;previous=pos

    raceme=growth.get('inflorescence_profile')
    raceme=raceme if raceme and raceme.get('form')=='raceme' else None
    can_reproduce=(growth.get('reproductive_mode') in {'sexual','both','apomictic'}
                   and growth.get('flowering_position') in {'terminal','mixed'}
                   and growth.get('reproductive_structure')=='flower' and raceme is not None)
    for k in range(axis_count):
        azimuth=phase+k*137.507764
        theta=math.radians(azimuth)
        height=profile['flowering_shoot_height_m']*maturity*(1.-k*.08)
        raceme_length=min(raceme['length_m'],height*.35) if raceme else 0.
        stem_height=max(.01,height-raceme_length)
        nodes=max(1,round(profile['stem_leaf_nodes']*maturity))
        parent=root;previous=tuple(placements[root][2:5])
        for n in range(nodes):
            f=(n+1)/nodes
            sway=.006*math.sin(f*2.1+k)*maturity
            pos=(math.cos(theta)*sway,math.sin(theta)*sway,stem_height*f)
            host=sim._add(placements,'stem_section',parent,*pos,azimuth,1.,1,
                placement_paths=placement_paths,path=sim._curved_segment_path(previous,pos,bend=.001))
            add_leaf(host,pos,azimuth+n*137.507764,(.8+.2*maturity)*(1.-f*.18),'fertile_stem')
            parent=host;previous=pos
        if not can_reproduce or maturity<1. or not (life_state['reproductive_factor']>.05 or life_state['fruiting_factor']>.02):
            continue
        from simulations.species.racemes import raceme_layout
        fruit_factor=life_state['fruiting_factor']
        axis_scale=1.+(profile['fruiting_axis_scale']-1.)*fruit_factor
        layout={**raceme,'length_m':raceme_length*axis_scale}
        base=previous
        for n,(offset,z) in enumerate(raceme_layout(layout)):
            axis_pos=(base[0]+.0015*math.sin(n*.6),base[1],base[2]+z)
            axis=sim._add(placements,'stem_section',parent,*axis_pos,azimuth,1.,2,
                placement_paths=placement_paths,path=[previous,axis_pos])
            score=(n+.5)/raceme['display_floret_count']
            kind=('fruit' if fruit_factor>.02 and score<fruit_factor else
                  'flower' if life_state['reproductive_factor']>.05
                  and n>=raceme['display_floret_count']-profile['display_open_florets'] else None)
            if kind:
                angle=azimuth+n*137.507764
                r=abs(offset);t=math.radians(angle)
                organ_pos=(axis_pos[0]+math.cos(t)*r,axis_pos[1]+math.sin(t)*r,axis_pos[2]+r*.35)
                pedicel=sim._add(placements,'branch_section',axis,*organ_pos,angle,1.,3,
                    placement_paths=placement_paths,path=[axis_pos,organ_pos])
                sim._add(placements,kind,pedicel,*organ_pos,(-12 if n%2 else 12),1.,4)
                flower_count+=kind=='flower';fruit_count+=kind=='fruit'
            parent=axis;previous=axis_pos
    return {'dimorphic_herb_profile_version':1,'dimorphic_basal_shoot_count':basal_count,
        'dimorphic_fertile_shoot_count':axis_count,'dimorphic_basal_leaf_count':basal_leaves,
        'dimorphic_stem_leaf_count':stem_leaves,'dimorphic_flower_count':flower_count,
        'dimorphic_fruit_count':fruit_count,'dimorphic_raceme_axis_scale':round(1.+(profile['fruiting_axis_scale']-1.)*life_state['fruiting_factor'],4),
        'leaf_area_m2':round(total_area,6),'estimated_leaf_count':basal_leaves+stem_leaves,
        'composed_growth_grammars':['basal_vegetative_shoots','erect_fertile_shoots','structural_raceme']}
