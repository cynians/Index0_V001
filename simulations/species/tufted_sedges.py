"""Opt-in tufted culms with leaf-like bracts and structural digitate spikelets.

Counts and poses are bounded display fits. A reproductive placement represents
one multi-floret spikelet, never a counted individual flower or nutlet.
"""
import math
import random

TUFTED_SEDGE_VERSION = 2
RANGES = {'culm_height_m':(.05,1.5),'culm_radius_m':(.0003,.004),
          'tuft_radius_m':(.005,.15),'leaf_width_m':(.001,.008),
          'leaf_bend':(0.,.35),'culm_deflection':(0.,.18),
          'ray_length_m':(0.,.085),'bract_length_m':(.02,.45),
          'spikelet_length_m':(.005,.025),'spikelet_width_m':(.0008,.003),
          'cluster_spread_deg':(3.,55.)}
COUNTS = {'culm_count':(1,12),'leaves_per_culm':(1,5),'ray_count':(0,8),
          'bract_count':(2,7),'spikelets_per_cluster':(3,30)}

def tufted_sedge_profile(value):
    if not isinstance(value,dict) or value.get('form')!='tufted_sedge':return None
    for key,(lo,hi) in {**RANGES,**COUNTS}.items():
        n=value.get(key)
        if (isinstance(n,bool) or not isinstance(n,(int,float)) or not math.isfinite(n)
                or not lo<=n<=hi or (key in COUNTS and int(n)!=n)):return None
    if value['spikelet_width_m']>=value['spikelet_length_m']:return None
    return {'form':'tufted_sedge','version':TUFTED_SEDGE_VERSION,
            **{k:float(value[k]) for k in RANGES},**{k:int(value[k]) for k in COUNTS},
            'reproductive_unit':'multi_floret_spikelet',
            'status':str(value.get('status') or 'qualitative_photo_fit')}

def grow_tufted_sedge(sim,placements,maturity,life_state,attachments,paths,clusters):
    g=sim.blueprint.growth;p=g['tufted_sedge_profile']
    m=max(0.,min(1.,maturity));size=math.sqrt(m)
    rng=random.Random(f'{sim.seed}:tufted_sedge_axes')
    phase=rng.uniform(0.,math.tau);root=sim._growth_origin(placements)
    culms=max(1,round(p['culm_count']*size)) if m else 0;leaves=bracts=flowers=fruits=cluster_count=0
    area=axis_length=0.;heads=[]
    fertile=m>=.65
    flowering=life_state.get('reproductive_factor',0.)
    fruiting=life_state.get('fruiting_factor',0.)
    sexual=g.get('reproductive_mode') in {'sexual','both','apomictic'}

    def axis(kind,parent,end,angle,radius_scale=1.,role='culm'):
        nonlocal axis_length
        start=placements[parent][2:5]
        index=sim._add(placements,kind,parent,*end,angle,radius_scale,1,
                       placement_paths=paths,path=[start,end])
        axis_length+=math.dist(start,end)
        sim._placement_orientation_hints[str(index)]={'min_render_lod':0,'axis_role':role}
        return index

    def blade(parent,start,azimuth,length,elevation,bend,role):
        nonlocal area,leaves,bracts
        direction=(math.cos(azimuth),math.sin(azimuth))
        path=[]
        for j in range(9):
            t=j/8
            horizontal=length*(math.cos(elevation)*t+bend*t*t)
            z=start[2]+length*(math.sin(elevation)*t-bend*t*t)
            path.append((start[0]+direction[0]*horizontal,start[1]+direction[1]*horizontal,max(.003,z)))
        angle=math.degrees(azimuth)
        index=sim._add(placements,'leaf',parent,*path[-1],angle,max(.025,size),2,
                       placement_paths=paths,path=path)
        sim._placement_orientation_hints[str(index)]={'min_render_lod':1,'blade_role':role}
        leaf_area=length*p['leaf_width_m']*max(.025,size)*.65
        area+=leaf_area;leaves+=1;bracts+=role=='involucral_bract'
        cid=sim._add_leaf_cluster(clusters,index,*start,1,leaf_area,0,visual_density=1.)
        clusters[-1].update(explicit_samples=True,sample_placement_indices=[index])
        attachments.append({'stem_placement_index':parent,'leaf_placement_index':index,'socket':role,
                            'position_m':list(start),'cluster_id':cid})

    for k in range(culms):
        a=phase+k*2.399963;r=p['tuft_radius_m']*size*rng.uniform(.35,1.)
        x,y=math.cos(a)*r,math.sin(a)*r
        height=min(g['max_height_m'],p['culm_height_m'])*m*rng.uniform(.72,1.)
        drift=height*p['culm_deflection']*rng.uniform(.55,1.35);parent=root
        base=(x,y,.004)
        for j in range(4):
            t=(j+1)/4
            end=(x+math.cos(a)*drift*t*t,y+math.sin(a)*drift*t*t,height*t)
            parent=axis('stem_section',parent,end,math.degrees(a),1.-.2*t)
            if j==0:base_host=parent
        for j in range(p['leaves_per_culm']):
            length=min(sim.blueprint.module('leaf').length_m*rng.uniform(.72,1.12),height*.93)
            elevation=math.radians(rng.uniform(42.,83.))
            blade(base_host,base,a+j*1.7+rng.uniform(-.3,.3),length,elevation,
                  p['leaf_bend']*rng.uniform(.55,1.3),'basal_blade')
        if not fertile:continue
        top=placements[parent][2:5]
        heads.append({'culm_index':k,'host_placement_index':parent,'socket_m':list(top)})
        for j in range(p['bract_count']):
            length=p['bract_length_m']*size*(1.-j*.17)*rng.uniform(.8,1.1)
            blade(parent,top,a+j*math.tau/p['bract_count']+rng.uniform(-.35,.35),length,
                  math.radians(rng.uniform(-12.,62.)),p['leaf_bend']*.35,'involucral_bract')
        centres=[(parent,top,a,(math.cos(a)*.12,math.sin(a)*.12,math.sqrt(1-.12**2)))]
        for j in range(p['ray_count']):
            az=a+j*2.399963;length=p['ray_length_m']*size*rng.uniform(.4,1.)
            incline=rng.uniform(.5,1.05)
            forward=(math.cos(az)*math.sin(incline),math.sin(az)*math.sin(incline),math.cos(incline))
            end=tuple(top[q]+forward[q]*length for q in range(3))
            ray=axis('branch_section',parent,end,math.degrees(az),.55,'anthela_ray')
            centres.append((ray,end,az,forward))
        for cluster,(host,centre,az,cluster_axis) in enumerate(centres):
            cluster_count+=1
            # A fascicle follows its ray. Tight sockets and staggered bases
            # produce a tapered bunch instead of a flat, upward finger fan.
            side=(-math.sin(az),math.cos(az),0.)
            across=(cluster_axis[1]*side[2]-cluster_axis[2]*side[1],
                    cluster_axis[2]*side[0]-cluster_axis[0]*side[2],
                    cluster_axis[0]*side[1]-cluster_axis[1]*side[0])
            # All organ poses are drawn even in a vegetative season so the
            # axis stream never changes with reproductive palette or timing.
            for j in range(p['spikelets_per_cluster']):
                theta=j*2.399963+az
                rank=math.sqrt((j+.5)/p['spikelets_per_cluster'])
                radial=tuple(side[q]*math.cos(theta)+across[q]*math.sin(theta) for q in range(3))
                spread=p['spikelet_length_m']*.12*size*rank
                stagger=p['spikelet_length_m']*.28*size*(1-rank)
                start=tuple(centre[q]+radial[q]*spread+cluster_axis[q]*stagger for q in range(3))
                stalk=axis('branch_section',host,start,math.degrees(theta),.2,'spikelet_socket')
                tilt=math.radians(p['cluster_spread_deg'])*rank
                forward=tuple(cluster_axis[q]*math.cos(tilt)+radial[q]*math.sin(tilt) for q in range(3))
                rotation=math.degrees(math.atan2(-(forward[0]+1.8*forward[1]),forward[2]))
                kind='fruit' if sexual and fruiting>.02 else 'flower' if sexual and flowering>.02 else None
                if kind:
                    scale=.78+.22*((j*7+cluster)%11)/10
                    index=sim._add(placements,kind,stalk,*start,rotation,scale,3)
                    sim._placement_orientation_hints[str(index)]={**sim._orientation_frame(forward),
                        'min_render_lod':1,'visual_unit':'spikelet','cluster_axis':list(cluster_axis),
                        'cluster_index':k*(p['ray_count']+1)+cluster}
                    attachments.append({'placement_index':index,'host_placement_index':stalk,
                                        'socket':'spikelet_base','position_m':list(start),'visual_unit':'multi_floret_spikelet'})
                    flowers+=kind=='flower';fruits+=kind=='fruit'
    return {'tufted_sedge_version':TUFTED_SEDGE_VERSION,'graminoid_culm_grammar':True,
            'graminoid_culm_count':culms,'graminoid_culm_node_count':culms*4,'tiller_count':culms,
            'estimated_leaf_count':leaves,'basal_blade_count':leaves-bracts,'involucral_bract_count':bracts,
            'leaf_area_m2':round(area,6),'structural_axis_length_m':round(axis_length,6),
            'spikelet_cluster_count':cluster_count,'flower_spikelet_count':flowers,'fruit_spikelet_count':fruits,
            'sedge_heads':heads,'reproductive_unit':'multi_floret_spikelet_not_individual_flower_or_nutlet'}

def draw_blade_asset(screen,surface,path,half_width):
    """Bend one authored blade along its whole path; preserve colour and taper."""
    import pygame
    if surface is None or len(path)<2:return False
    bounds=surface.get_bounding_rect()
    if not bounds.width or not bounds.height:return False
    source=surface.subsurface(bounds)
    lengths=[math.dist(a,b) for a,b in zip(path,path[1:])];total=sum(lengths)
    if total<1:return False
    done=0.
    for a,b,length in zip(path,path[1:],lengths):
        if length<.5:continue
        # Authored base at bottom, tip at top; never repeat whole leaf tips.
        y0=round(source.get_height()*(1-(done+length)/total))
        y1=round(source.get_height()*(1-done/total));done+=length
        crop=source.subsurface((0,max(0,y0),source.get_width(),max(1,min(source.get_height()-max(0,y0),y1-y0))))
        ribbon=pygame.transform.scale(crop,(max(1,round(2*half_width)),max(1,math.ceil(length)+1)))
        angle=-math.degrees(math.atan2(b[0]-a[0],-(b[1]-a[1])))
        ribbon=pygame.transform.rotate(ribbon,angle)
        screen.blit(ribbon,ribbon.get_rect(center=(round((a[0]+b[0])/2),round((a[1]+b[1])/2))))
    return True
