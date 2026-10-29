"""Basal petiolate rosettes with structural panicles of tiny stalked organs.

Recipes are explicit, qualitative display choices. Individual laminae,
petioles, axes and reproductive organs remain separate portable placements.
"""
import math
import random

PANICULATE_ROSETTE_VERSION = 1
RANGES = {'shoot_height_m':(.05,.8),'panicle_length_m':(.01,.25),
          'petiole_length_m':(.005,.2),'stem_radius_m':(.0002,.004),
          'leaf_width_m':(.005,.1),'panicle_spread_ratio':(.03,.8),
          'axis_deflection':(0.,.2)}
COUNTS = {'leaf_count':(3,48),'flowering_shoot_count':(1,8),
          'lateral_raceme_count':(0,6),'clusters_per_raceme':(2,12),'organs_per_cluster':(1,6)}


def paniculate_rosette_profile(value):
    if not isinstance(value,dict) or value.get('form')!='paniculate_rosette':return None
    for k,(lo,hi) in {**RANGES,**COUNTS}.items():
        n=value.get(k)
        if (isinstance(n,bool) or not isinstance(n,(int,float)) or not math.isfinite(n)
                or not lo<=n<=hi or (k in COUNTS and int(n)!=n)):return None
    if value['panicle_length_m']>=value['shoot_height_m']:return None
    return {'form':value['form'],'version':PANICULATE_ROSETTE_VERSION,
            **{k:float(value[k]) for k in RANGES},**{k:int(value[k]) for k in COUNTS},
            'status':str(value.get('status') or 'qualitative_photo_fit')}


def bounded(value,default,lo,hi):
    try:n=float(value)
    except (TypeError,ValueError):n=default
    return min(hi,max(lo,n if math.isfinite(n) else default))


def grow_paniculate_rosette(sim,placements,maturity,life_state,attachments,paths,clusters):
    g=sim.blueprint.growth;p=g['paniculate_rosette_profile']
    maturity=bounded(maturity,0.,0.,1.)
    leaf_factor=bounded(life_state.get('leaf_factor'),1.,0.,1.)
    flowering=bounded(life_state.get('reproductive_factor'),0.,0.,1.)
    fruiting=bounded(life_state.get('fruiting_factor'),0.,0.,1.)
    root=sim._growth_origin(placements)
    rng=random.Random(f'{sim.seed}:paniculate_rosette')
    axis_rng=random.Random(f'{sim.seed}:paniculate_axes')
    phase=rng.uniform(0.,360.)
    area=axis_length=0.
    leaves=flowers=fruits=0
    leaf_module=sim.blueprint.module('leaf')

    def axis(kind,parent,end,angle,scale=1.,role='axis'):
        nonlocal axis_length
        start=placements[parent][2:5]
        path=sim._curved_segment_path(start,end,bend=math.dist(start,end)*.025,
                                     direction=-1 if math.sin(math.radians(angle))<0 else 1)
        axis_length+=sum(math.dist(a,b) for a,b in zip([start,*path[:-1]],path))
        index=sim._add(placements,kind,parent,*end,angle,scale,1,placement_paths=paths,path=path)
        sim._placement_orientation_hints[str(index)]={'min_render_lod':0,'axis_role':role}
        return index

    count=round(p['leaf_count']*math.sqrt(maturity)*leaf_factor)
    for i in range(count):
        angle=phase+i*137.507764+rng.uniform(-13.,13.)
        rad=math.radians(angle)
        length=p['petiole_length_m']*(.48+.52*math.sqrt(maturity))*rng.uniform(.55,1.15)
        lift=length*rng.uniform(.25,.65)
        radius=length*math.sqrt(max(0.,1-(lift/length)**2))
        base=(math.cos(rad)*radius,math.sin(rad)*radius,.004+lift)
        petiole=axis('stem_section',root,base,angle,.5,'petiole')
        scale=(.38+.62*math.sqrt(maturity))*rng.uniform(.72,1.12)
        # One lamina at the distal end of a connected long petiole.
        forward=(math.cos(rad)*.88,math.sin(rad)*.88,rng.uniform(.2,.48))
        leaf=sim._add(placements,'leaf',petiole,*base,angle,scale,2)
        sim._placement_orientation_hints[str(leaf)]={**sim._orientation_frame(forward),'min_render_lod':1}
        lamina_area=leaf_module.length_m*p['leaf_width_m']*.70*scale**2
        area+=lamina_area;leaves+=1
        cid=sim._add_leaf_cluster(clusters,leaf,*base,1,lamina_area,0,visual_density=1.)
        clusters[-1].update(explicit_samples=True,sample_placement_indices=[leaf])
        attachments.append({'stem_placement_index':petiole,'leaf_placement_index':leaf,
                            'socket':'leaf','position_m':list(placements[leaf][2:5]),'cohort':'basal_lamina','cluster_id':cid})

    # Body development supplies a persistent fertile framework, independent
    # of whether this model season currently bears flowers or retained fruit.
    extension=max(0.,min(1.,(maturity-.30)/.70))
    shoot_count=round(p['flowering_shoot_count']*extension)
    reproduce=g.get('reproductive_mode') in {'sexual','both','apomictic'}
    for k in range(shoot_count):
        angle=phase+k*137.507764
        rad=math.radians(angle)
        height=min(g['max_height_m'],p['shoot_height_m'])*extension*axis_rng.uniform(.83,1.07)
        panicle=min(p['panicle_length_m']*extension,height*.60)
        bottom=height-panicle
        drift=height*p['axis_deflection']
        origin=(math.cos(rad)*.006,math.sin(rad)*.006,0.)
        parent=root
        for step in (.33,.66,1.):
            end=(origin[0]+math.cos(rad)*drift*step,origin[1]+math.sin(rad)*drift*step,bottom*step)
            parent=axis('stem_section',parent,end,angle,1.-step*.30,'flowering_stem')
        panicle_base=placements[parent][2:5]
        # A central raceme with bounded short lateral racemes supplies a real
        # panicle; tiny flowers are not enlarged into one decorative blob.
        racemes=[(parent,panicle_base,angle,panicle,0.)]
        for j in range(p['lateral_raceme_count']):
            t=(j+1)/(p['lateral_raceme_count']+1)
            attach=(panicle_base[0],panicle_base[1],bottom+panicle*t*.72)
            rachis=axis('stem_section',parent,attach,angle,.5,'panicle_axis')
            a=angle+j*137.507764
            length=panicle*(.72-.32*t)
            spread=panicle*p['panicle_spread_ratio']*(1-.45*t)
            racemes.append((rachis,attach,a,length,spread))
        for host,start,a,length,spread in racemes:
            arad=math.radians(a)
            parent=host
            for j in range(p['clusters_per_raceme']):
                t=(j+1)/p['clusters_per_raceme']
                end=(start[0]+math.cos(arad)*spread*t,start[1]+math.sin(arad)*spread*t,start[2]+length*t)
                parent=axis('stem_section' if spread==0 else 'branch_section',parent,end,a,.32,'raceme_axis')
                for n in range(p['organs_per_cluster']):
                    organ_angle=a+j*137.507764+n*120.
                    r=.003*(.7+.3*(n+1)/p['organs_per_cluster'])*extension
                    theta=math.radians(organ_angle)
                    point=(end[0]+math.cos(theta)*r,end[1]+math.sin(theta)*r,end[2]-.0005*n)
                    pedicel=axis('branch_section',parent,point,organ_angle,.15,'pedicel')
                    # Fixed ranks form distinct cohorts during overlapping
                    # bloom/fruit, rather than two organs at one socket.
                    rank=((j*p['organs_per_cluster']+n)*7%23)/23
                    kind='fruit' if reproduce and fruiting>.02 and (flowering==0 or rank<fruiting*.70) else 'flower' if reproduce and flowering>.02 else None
                    if kind:
                        index=sim._add(placements,kind,pedicel,*point,organ_angle,1.,3)
                        sim._placement_orientation_hints[str(index)]={'min_render_lod':1}
                        flowers+=kind=='flower';fruits+=kind=='fruit'
    return {'paniculate_rosette_version':PANICULATE_ROSETTE_VERSION,
            'paniculate_shoot_count':shoot_count,'paniculate_flower_count':flowers,
            'paniculate_fruit_count':fruits,'estimated_leaf_count':leaves,
            'leaf_area_m2':round(area,6),'structural_axis_length_m':round(axis_length,6),
            'leaf_factor':leaf_factor,'organ_count_status':'bounded_representative_display_not_yield'}
