"""One persistent mother crown with bounded, independently sized offsets.

Offset slots, timing, counts and geometry are qualitative visual controls.
An optional nonrepeating crown cycle adds flowering and mother-only decline.
"""
import math
import random

VERSION=1
RANGES={'leaf_width_m':(.03,.4),'leaf_bend':(0.,1.2),
        'crown_radius_m':(.015,.2),'offset_distance_m':(.1,4.),
        'offset_max_scale':(.15,.8),'offset_onset_units':(.2,2.),
        'offset_interval_units':(.05,1.),'offset_expansion_units':(.2,3.),
        'connector_depth_m':(.02,.25),'connector_radius_m':(.003,.04)}
COUNTS={'mother_leaves':(8,80),'offset_leaves':(5,40),'offset_count':(0,8)}

CYCLE_RANGES={'stalk_start_units':(1.,20.),'bloom_start_units':(1.,25.),
    'bloom_end_units':(1.,30.),'mother_dead_units':(1.,35.),
    'stalk_retention_end_units':(1.,40.),'successor_maturation_units':(.5,10.),
    'stalk_height_m':(3.,12.),'stalk_radius_m':(.025,.15),
    'panicle_fraction':(.33,.5),'panicle_width_m':(.5,4.),
    'pedicel_length_m':(.02,.04),'bract_length_m':(.05,.15)}
CYCLE_COUNTS={'lateral_count':(15,35),'flowers_per_lateral':(3,18)}

def monocarpic_cycle_profile(value):
    if not isinstance(value,dict):return None
    for key,(lo,hi) in {**CYCLE_RANGES,**CYCLE_COUNTS}.items():
        x=value.get(key)
        if (isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x)
                or not lo<=x<=hi or key in CYCLE_COUNTS and not isinstance(x,int)):return None
    times=[value[k] for k in ('stalk_start_units','bloom_start_units','bloom_end_units',
                             'mother_dead_units','stalk_retention_end_units')]
    if any(b<=a for a,b in zip(times,times[1:])):return None
    return {**{k:float(value[k]) for k in CYCLE_RANGES},**{k:value[k] for k in CYCLE_COUNTS},
            'version':1,'status':str(value.get('status') or 'qualitative_nonrepeating_crown_clock')}

def offset_rosette_profile(value):
    if not isinstance(value,dict) or value.get('form')!='offset_rosettes':return None
    for key,(lo,hi) in {**RANGES,**COUNTS}.items():
        x=value.get(key)
        if (isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x)
            or not lo<=x<=hi or key in COUNTS and not isinstance(x,int)):return None
    cycle=None
    if 'monocarpic_cycle' in value:
        cycle=monocarpic_cycle_profile(value['monocarpic_cycle'])
        if cycle is None:return None
    return ({'form':'offset_rosettes','version':VERSION,**{k:float(value[k]) for k in RANGES},
        **{k:value[k] for k in COUNTS},'status':str(value.get('status') or 'qualitative_vegetative_colony')}
        | ({'monocarpic_cycle':cycle} if cycle else {}))

def grow_offset_rosettes(sim,placements,maturity,age_days,attachments,paths,clusters):
    from simulations.species.terminal_rosettes import rosette_blade_curve
    p=sim.blueprint.growth['offset_rosette_profile'];m=max(0.,min(1.,maturity))
    age=max(0.,age_days/max(1.,sim.mature_age_days))
    cycle=(p.get('monocarpic_cycle') if
           sim.blueprint.growth.get('reproductive_mode') in {'sexual','both','apomictic'}
           and sim.blueprint.growth.get('flowering_position')=='terminal'
           and sim.blueprint.growth.get('reproductive_structure') in {'flower','panicle'} else None)
    decline=(max(0.,min(1.,(age-cycle['bloom_end_units'])/
             (cycle['mother_dead_units']-cycle['bloom_end_units']))) if cycle else 0.)
    phase=random.Random(sim.seed+46013).uniform(0.,math.tau)
    root=sim._add(placements,'root',-1,0.,0.,0.,0.,1.,0)
    crowns=[];axis_length=0.;leaf_count=0;dead_leaves=0;flower_count=0;bract_area=0.
    def axis(parent,start,end,radius,role,crown):
        nonlocal axis_length
        i=sim._add(placements,'stem_section' if role=='crown_axis' else 'branch_section',parent,*end,
                   0.,radius,1,paths,[start,end])
        sim._placement_orientation_hints[str(i)]={'axis_role':role,'offset_crown_identity':crown}
        attachments.append({'placement_index':i,'host_placement_index':parent,
                            'socket':role+'_base','position_m':list(start)})
        axis_length+=math.dist(start,end)
        return i
    def crown(parent,center,scale,identity,count):
        nonlocal leaf_count,dead_leaves
        top=(center[0],center[1],.025+.035*scale)
        host=axis(parent,center,top,p['crown_radius_m']*scale,'crown_axis',identity)
        n=max(3,round(count*max(.05,scale)**.5))
        start_leaf=len(placements)
        for j in range(n):
            rank=j/max(1,n-1);az=phase+identity*.71+j*2.399963229728653
            dead=bool(identity==0 and decline>0 and (j+.5)/n>=1.-decline)
            elevation=1.48-rank*.78
            if dead:elevation-=.22
            base=(top[0]+math.cos(az)*p['crown_radius_m']*.55*scale,
                  top[1]+math.sin(az)*p['crown_radius_m']*.55*scale,top[2])
            length=sim.blueprint.module('leaf').length_m*scale*(.78+.22*math.sin(rank*math.pi))
            curve=rosette_blade_curve(base,az,elevation,p['leaf_bend']*(.15+.85*rank),length)
            index=sim._add(placements,'leaf',host,*base,math.degrees(az),scale,2,paths,curve)
            sim._placement_orientation_hints[str(index)]={'terminal_blade':True,
                'retained_dead_leaf':dead,'blade_width_m':p['leaf_width_m']*scale,
                'min_render_lod':0,'offset_crown_identity':identity,
                'forward':[math.cos(az)*math.cos(elevation),math.sin(az)*math.cos(elevation),math.sin(elevation)]}
            area=0. if dead else length*p['leaf_width_m']*scale*.65
            cid=sim._add_leaf_cluster(clusters,index,*base,int(not dead),area,0,allow_empty=True)
            clusters[-1].update(explicit_samples=True,sample_placement_indices=[index])
            attachments.append({'stem_placement_index':host,'leaf_placement_index':index,
                'socket':'crown_leaf','position_m':list(base),'cluster_id':cid,'crown_identity':identity})
            leaf_count+=not dead;dead_leaves+=dead
        crowns.append({'identity':identity,'role':'mother' if identity==0 else 'daughter',
                       'center_m':list(top),'scale':scale,'host_index':host,
                       'leaf_indices':list(range(start_leaf,len(placements))),
                       'living_fraction':1.-decline if identity==0 else 1.})
    if m:crown(root,(0.,0.,0.),math.sqrt(m),0,p['mother_leaves'])
    if (cycle and crowns and age>cycle['stalk_start_units']
            and age<cycle['stalk_retention_end_units']
            and sim.blueprint.growth.get('reproductive_mode') in {'sexual','both','apomictic'}):
        elongation=min(1.,(age-cycle['stalk_start_units'])/
                       (cycle['bloom_start_units']-cycle['stalk_start_units']))
        spent=age>=cycle['bloom_end_units']
        mother=crowns[0];host=mother['host_index'];base=tuple(mother['center_m'])
        height=cycle['stalk_height_m']*elongation
        # All axis junctions are actual nodes; no branch attaches to the
        # previous lateral tip or an unrelated end of the main stalk.
        parent=host;start=base
        lower=height*(1.-cycle['panicle_fraction'])
        for j in range(6):
            tip=(base[0],base[1],base[2]+lower*(j+1)/6)
            parent=axis(parent,start,tip,cycle['stalk_radius_m']*(1.-.22*(j+1)/6),'flower_stalk',0)
            sim._placement_orientation_hints[str(parent)]['spent_axis']=spent
            # Reduced bracts reuse the same single-leaf component.
            az=phase+j*2.399963229728653
            length=cycle['bract_length_m']*elongation
            curve=rosette_blade_curve(tip,az,.9,.35,length)
            i=sim._add(placements,'leaf',parent,*tip,math.degrees(az),length/sim.blueprint.module('leaf').length_m,2,paths,curve)
            width=length*.3
            sim._placement_orientation_hints[str(i)]={'terminal_blade':True,
                'retained_dead_leaf':spent,'blade_width_m':width,'min_render_lod':0,
                'offset_crown_identity':0,'leaf_role':'stalk_bract'}
            area=0. if spent else length*width*.65
            sim._add_leaf_cluster(clusters,i,*tip,int(not spent),area,0,allow_empty=True)
            clusters[-1].update(explicit_samples=True,sample_placement_indices=[i])
            leaf_count+=not spent;dead_leaves+=spent;bract_area+=area
            start=tip
        for j in range(cycle['lateral_count']):
            t=(j+.5)/cycle['lateral_count']
            node=(base[0],base[1],base[2]+lower+height*cycle['panicle_fraction']*t)
            parent=axis(parent,start,node,cycle['stalk_radius_m']*(.78-.48*t),'panicle_axis',0)
            sim._placement_orientation_hints[str(parent)]['spent_axis']=spent
            az=phase+j*2.399963229728653
            reach=cycle['panicle_width_m']*.5*(1.-t)**.65*elongation
            end=(node[0]+math.cos(az)*reach,node[1]+math.sin(az)*reach,node[2]+reach*.18)
            lateral=axis(parent,node,end,cycle['stalk_radius_m']*.18,'panicle_lateral',0)
            sim._placement_orientation_hints[str(lateral)]['spent_axis']=spent
            # One bounded crown of individual flowers at each branch end.
            if cycle['bloom_start_units']<=age<cycle['bloom_end_units']:
                for f in range(cycle['flowers_per_lateral']):
                    a=az+f*2.399963229728653;r=.09*math.sqrt((f+1)/cycle['flowers_per_lateral'])
                    socket=(end[0]+math.cos(a)*r,end[1]+math.sin(a)*r,end[2]+.025*(f%3))
                    tip=(socket[0],socket[1],socket[2]+cycle['pedicel_length_m'])
                    stalk=axis(lateral,end,socket,.002,'floral_branchlet',0)
                    pedicel=axis(stalk,socket,tip,.0015,'pedicel',0)
                    i=sim._add(placements,'flower',pedicel,*tip,0.,1.,2)
                    sim._placement_orientation_hints[str(i)]={**sim._orientation_frame((0.,0.,1.)),
                        'min_render_lod':0,'offset_crown_identity':0}
                    attachments.append({'placement_index':i,'host_placement_index':pedicel,
                                        'socket':'flower_base','position_m':list(tip)})
                    flower_count+=1
            start=node
        tip=(base[0],base[1],base[2]+height)
        final=axis(parent,start,tip,cycle['stalk_radius_m']*.2,'panicle_axis',0)
        sim._placement_orientation_hints[str(final)]['spent_axis']=spent
    for j in range(p['offset_count']):
        onset=p['offset_onset_units']+j*p['offset_interval_units']
        if age<=onset or not m:continue
        progress=min(1.,(age-onset)/p['offset_expansion_units'])
        scale=p['offset_max_scale']*math.sqrt(progress)*(.86+.14*((j*3)%5)/4)
        count=p['offset_leaves']
        if cycle and age>cycle['mother_dead_units']:
            succession=min(1.,(age-cycle['mother_dead_units'])/cycle['successor_maturation_units'])
            scale=scale+(1.-scale)*succession
            count=round(count+(p['mother_leaves']-count)*succession)
        az=phase+j*2.399963229728653
        distance=p['offset_distance_m']*(.86+.28*random.Random(sim.seed+j+919).random())
        site=(math.cos(az)*distance,math.sin(az)*distance,-p['connector_depth_m'])
        # Explicit junction from the mother's crown to a concealed rhizome,
        # then a separate daughter crown. A rhizome is a stem, not a root.
        origin=(0.,0.,-p['connector_depth_m'])
        junction=axis(root,(0.,0.,0.),origin,p['connector_radius_m'],'rhizome_descent',j+1)
        connector=axis(junction,origin,site,p['connector_radius_m'],'rhizome',j+1)
        crown(connector,site,max(.04,scale),j+1,count)
    return {'offset_rosette_version':VERSION,'offset_rosettes':crowns,
        'rosette_count':len(crowns),'daughter_rosette_count':max(0,len(crowns)-1),
        'living_rosette_count':sum(c['living_fraction']>0 for c in crowns),
        'estimated_leaf_count':leaf_count,'leaf_area_m2':round(sum(c['leaf_area_m2'] for c in clusters),6),
        'retained_dead_leaf_count':dead_leaves,'flower_count':flower_count,
        'mother_living_fraction':1.-decline,'mother_dead':bool(decline>=1.),
        'stalk_bract_area_m2':round(bract_area,6),
        'structural_axis_length_m':round(axis_length,6),
        'flowering_status':'nonrepeating_mother_crown_cycle' if cycle else 'not_implemented_in_vegetative_pass',
        'fruit_morphology_status':'unresolved_not_displayed',
        'recruitment_status':'bounded_preselected_offset_slots_not_population_demography'}
