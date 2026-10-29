"""Bounded leafy sympodial units with terminal cymes and lateral successors.

The graph records developmental termination even when the successor axes make
the inflorescence appear lateral. Counts and timing are qualitative controls.
"""
import math
import random

VERSION=1
RANGES={'basal_height_ratio':(.08,.4),'unit_length_ratio':(.05,.3),
        'successor_length_ratio':(.5,.9),'successor_spread_deg':(15.,65.),
        'successor_elevation_deg':(15.,75.),'leaf_width_m':(.01,.10),
        'petiole_length_m':(.005,.05),'peduncle_length_m':(.005,.04),
        'rachis_length_m':(.003,.03),'pedicel_length_m':(.003,.016),
        'stem_radius_m':(.0005,.006)}
COUNTS={'basal_nodes':(2,8),'fork_levels':(0,4),'flowers_per_cyme':(3,10)}

def fork_profile(value):
    if not isinstance(value,dict) or value.get('form')!='flower_terminated_forks':return None
    for key,(lo,hi) in {**RANGES,**COUNTS}.items():
        n=value.get(key)
        if (isinstance(n,bool) or not isinstance(n,(int,float)) or not math.isfinite(n)
            or not lo<=n<=hi or key in COUNTS and not isinstance(n,int)):return None
    return {'form':value['form'],'version':VERSION,**{k:float(value[k]) for k in RANGES},
            **{k:value[k] for k in COUNTS},'status':str(value.get('status') or 'qualitative_modular_recipe')}

def build_forks(growth,maturity,flowering,fruiting,seed,leaf_factor=1.):
    p=growth['flower_fork_profile'];m=max(0.,min(1.,maturity));nodes=[];units=[]
    area=axis_length=0.;leaf_ordinal=0
    h=growth['max_height_m'];phase=random.Random(seed+7103).uniform(0,math.tau)
    sexual=growth.get('reproductive_mode') in {'sexual','both','apomictic'}
    def add(kind,parent,pos,role,scale=1.,forward=None,unit=-1):
        nonlocal axis_length
        origin=nodes[parent]['position'] if parent>=0 else (0.,0.,0.)
        path=[origin,pos] if kind in {'stem_section','branch_section'} else None
        if path:axis_length+=math.dist(origin,pos)
        nodes.append({'kind':kind,'parent':parent,'position':pos,'angle':0.,'scale':scale,
            'role':role,'forward':forward,'path':path,'min_lod':0 if path else 1,
            'unit_id':unit,'area_m2':0.})
        return len(nodes)-1
    def leaf(host,az,level,unit):
        nonlocal area,leaf_ordinal
        leaf_ordinal+=1
        # Leaf retention never alters the underlying stem graph or sockets.
        if (leaf_ordinal*.61803398875)%1>=max(0.,min(1.,leaf_factor)):return
        start=nodes[host]['position'];length=p['petiole_length_m']*math.sqrt(m)*(.9**level)
        tip=(start[0]+math.cos(az)*length,start[1]+math.sin(az)*length,start[2]+length*.2)
        stalk=add('branch_section',host,tip,'petiole',.18,unit=unit)
        scale=math.sqrt(m)*(.88**level)
        i=add('leaf',stalk,tip,'unit_leaf',scale,[math.cos(az),math.sin(az),.18],unit)
        nodes[i]['area_m2']=growth['leaf_length_m']*p['leaf_width_m']*.65*scale**2
        area+=nodes[i]['area_m2']
    def cyme(host,az,unit):
        origin=nodes[host]['position'];reach=p['peduncle_length_m']*math.sqrt(m)
        tip=(origin[0]+math.cos(az)*reach,origin[1]+math.sin(az)*reach,origin[2]+reach*.4)
        peduncle=add('branch_section',host,tip,'terminal_peduncle',.12,unit=unit)
        rachis=peduncle
        for j in range(p['flowers_per_cyme']):
            t=(j+1)/p['flowers_per_cyme'];pos=(tip[0]+math.cos(az)*p['rachis_length_m']*t,
                tip[1]+math.sin(az)*p['rachis_length_m']*t,tip[2])
            rachis=add('branch_section',rachis,pos,'cyme_rachis',.10,unit=unit)
            a=az+(-1 if j%2 else 1)*1.1;length=p['pedicel_length_m']
            # A fixed flower/fruit slot prevents duplicate organs at a socket.
            is_fruit=fruiting>.05 and (j+.5)/p['flowers_per_cyme']<=fruiting
            end=(pos[0]+math.cos(a)*length,pos[1]+math.sin(a)*length,
                 pos[2]-length*(1. if is_fruit else .35))
            stalk=add('branch_section',rachis,end,'pedicel',.065,unit=unit)
            if sexual and (is_fruit or flowering>.02):
                add('fruit' if is_fruit else 'flower',stalk,end,
                    'berry' if is_fruit else 'individual_flower',1.,[0.,0.,-1.],unit)
        return peduncle
    def unit(host,az,level,identity,length,emergence):
        local=max(0.,min(1.,(m-emergence)/.18))
        if not local:return
        start=nodes[host]['position'];parent=host
        elev=math.pi/2 if level==0 else math.radians(p['successor_elevation_deg'])
        # Two separated alternate leaves per unit, rather than opposite pairs.
        for j in range(2):
            distance=length*local*(j+1)/2
            pos=(start[0]+math.cos(az)*distance*math.cos(elev),
                 start[1]+math.sin(az)*distance*math.cos(elev),start[2]+distance*math.sin(elev))
            parent=add('branch_section',parent,pos,'sympodial_axis',.65*(.7**level),unit=identity)
            leaf(parent,az+j*math.tau/3+math.pi*.6,level,identity)
        peduncle=cyme(parent,az+math.pi*.5,identity) if local>.6 else None
        units.append({'identity':identity,'origin_node':host,'terminal_node':parent,
                      'terminal_peduncle':peduncle,'level':level})
        if level>=p['fork_levels']:return
        for side in (-1,1):
            # Lateral successors start below the terminal cyme. Unequal
            # successor lengths avoid imposing repeated symmetrical Ys.
            turn=(0. if side<0 else math.pi) if level==0 else math.radians(p['successor_spread_deg'])*side
            unit(parent,az+turn+level*.24,level+1,identity*2+(1 if side<0 else 2),
                 length*p['successor_length_ratio']*(.84 if side<0 else 1.),emergence+.17)
    if m:
        parent=-1
        for j in range(p['basal_nodes']):
            pos=(0.,0.,h*p['basal_height_ratio']*min(1.,m/.4)*(j+1)/p['basal_nodes'])
            parent=add('stem_section',parent,pos,'basal_axis',1.-j*.08)
            leaf(parent,phase+j*math.tau/3,0,-1)
        unit(parent,phase,0,0,h*p['unit_length_ratio'],.30)
    return nodes,{'flower_fork_version':VERSION,'sympodial_units':units,
        'sympodial_unit_count':len(units),'estimated_leaf_count':sum(n['kind']=='leaf' for n in nodes),
        'flower_count':sum(n['kind']=='flower' for n in nodes),'fruit_count':sum(n['kind']=='fruit' for n in nodes),
        'leaf_area_m2':round(area,6),'structural_axis_length_m':round(axis_length,6)}
