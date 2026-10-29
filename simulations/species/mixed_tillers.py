"""A canonical tuft with compressed vegetative shoots and selected fertile culms.

The bounded shoot population and clock are display recipes, not measured
tiller demography or a vernalisation, grazing or recruitment model.
"""
import math
import random

VERSION=1
RANGES={'reproductive_fraction':(0.,1.),'tuft_radius_m':(.005,.2),
        'vegetative_axis_height_m':(.005,.06),'culm_radius_m':(.0003,.003),
        'leaf_width_m':(.001,.006),'leaf_bend':(.3,1.8),
        'spike_length_m':(.04,.3),'spike_width_m':(.003,.02),
        'elongation_start_units':(.5,3.),'elongation_duration_units':(.2,3.)}
COUNTS={'tiller_count':(1,64),'leaves_per_tiller':(2,6),'culm_nodes':(3,8)}

def mixed_tiller_profile(value):
    if not isinstance(value,dict) or value.get('form')!='mixed_tillers':return None
    for key,(lo,hi) in {**RANGES,**COUNTS}.items():
        x=value.get(key)
        if (isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x)
            or not lo<=x<=hi or key in COUNTS and not isinstance(x,int)):return None
    return {'form':'mixed_tillers','version':VERSION,**{k:float(value[k]) for k in RANGES},
        **{k:value[k] for k in COUNTS},'status':str(value.get('status') or 'qualitative_mixed_tiller_tuft')}

def grow_mixed_tillers(sim,placements,maturity,age_days,life_state,attachments,paths,clusters):
    from simulations.species.terminal_rosettes import rosette_blade_curve
    g=sim.blueprint.growth;p=g['mixed_tiller_profile'];m=max(0.,min(1.,maturity))
    age=age_days/max(1.,sim.mature_age_days)
    elongation=max(0.,min(1.,(age-p['elongation_start_units'])/p['elongation_duration_units']))
    rng=random.Random(sim.seed+67109);phase=rng.uniform(0.,math.tau)
    root=sim._growth_origin(placements);count=round(p['tiller_count']*math.sqrt(m)) if m else 0
    potential=round(count*p['reproductive_fraction'])
    selected=set(random.Random(sim.seed+1663).sample(range(count),potential))
    fertile=leaf_count=spikes=0;axis_length=0.;shoots=[]
    def axis(parent,end,role,identity,scale=1.):
        nonlocal axis_length
        start=placements[parent][2:5]
        i=sim._add(placements,'stem_section',parent,*end,0.,scale,1,paths,[start,end])
        sim._placement_orientation_hints[str(i)]={'axis_role':role,'tiller_identity':identity,'min_render_lod':0}
        attachments.append({'placement_index':i,'host_placement_index':parent,
                            'socket':role+'_base','position_m':list(start)})
        axis_length+=math.dist(start,end)
        return i
    for t in range(count):
        # Fixed slots keep reproductive-fraction changes from moving leaves.
        a=phase+t*2.399963229728653
        distance=p['tuft_radius_m']*math.sqrt((t+.5)/p['tiller_count'])*math.sqrt(m)
        x,y=math.cos(a)*distance,math.sin(a)*distance
        base=(x,y,.006)
        host=axis(root,base,'basal_junction',t,.65)
        compressed=p['vegetative_axis_height_m']*math.sqrt(m)
        top=(x,y,base[2]+compressed)
        host=axis(host,top,'vegetative_axis',t,.7)
        leaf_indices=[]
        for j in range(p['leaves_per_tiller']):
            az=a+(j%2)*math.pi
            # A leaf's physical arc length is independent of flowering status.
            rank=j/max(1,p['leaves_per_tiller']-1)
            length=g['leaf_length_m']*math.sqrt(m)*(.78+.22*math.sin(rank*math.pi))
            socket=(x,y,base[2]+compressed*(j+1)/p['leaves_per_tiller'])
            elevation=1.35-rank*.35
            curve=rosette_blade_curve(socket,az,elevation,p['leaf_bend']*(.4+.6*rank),length)
            scale=length/sim.blueprint.module('leaf').length_m
            i=sim._add(placements,'leaf',host,*socket,math.degrees(az),scale,2,paths,curve)
            sim._placement_orientation_hints[str(i)]={'tiller_identity':t,'leaf_role':'basal_blade',
                'min_render_lod':0,'forward':[math.cos(az),math.sin(az),.5]}
            area=length*p['leaf_width_m']*.72
            cid=sim._add_leaf_cluster(clusters,i,*socket,1,area,0)
            clusters[-1].update(explicit_samples=True,sample_placement_indices=[i])
            attachments.append({'stem_placement_index':host,'leaf_placement_index':i,
                'socket':'leaf_sheath','position_m':list(socket),'cluster_id':cid,'tiller_identity':t})
            leaf_count+=1;leaf_indices.append(i)
        flowering_tiller=t in selected and elongation>0.
        culm_tip=None
        if flowering_tiller:
            fertile+=1;start=top;parent=host
            height=(g['max_height_m']-p['spike_length_m'])*elongation*(.80+.20*random.Random(sim.seed+t+91).random())
            for n in range(p['culm_nodes']):
                f=(n+1)/p['culm_nodes']
                end=(x+math.cos(a)*height*.025*f*f,y+math.sin(a)*height*.025*f*f,top[2]+height*f)
                parent=axis(parent,end,'reproductive_culm',t,1.-.35*f);start=end
            culm_tip=parent
            sexual=g.get('reproductive_mode') in {'sexual','both','apomictic'}
            if sexual and life_state.get('reproductive_factor',0.)>.02 and elongation>.7:
                index=sim._add(placements,'flower',parent,*start,0.,1.,2)
                sim._placement_orientation_hints[str(index)]={**sim._orientation_frame((0.,0.,1.)),
                    'tiller_identity':t,'reproductive_unit':'whole_spike','min_render_lod':0}
                attachments.append({'placement_index':index,'host_placement_index':parent,
                    'socket':'spike_base','position_m':list(start),'tiller_identity':t})
                spikes+=1
        shoots.append({'identity':t,'role':'reproductive' if flowering_tiller else 'vegetative',
                       'crown_index':host,'culm_tip_index':culm_tip,'leaf_indices':leaf_indices})
    return {'mixed_tiller_version':VERSION,'tillers':shoots,'tiller_count':count,
        'reproductive_tiller_count':fertile,'vegetative_tiller_count':count-fertile,
        'spike_count':spikes,'reproductive_visual_unit':'whole_spike_not_individual_flower',
        'estimated_leaf_count':leaf_count,'leaf_area_m2':round(sum(c['leaf_area_m2'] for c in clusters),6),
        'structural_axis_length_m':round(axis_length,6)}
