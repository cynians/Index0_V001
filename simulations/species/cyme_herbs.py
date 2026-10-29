"""Opt-in leafy herbs with ray-based, recursively forked cymes."""
import math,random
from functools import lru_cache

CYME_HERB_VERSION=5
RANGES={'shoot_height_m':(.08,1.2),'shoot_radius_m':(.0004,.004),
        'tuft_radius_m':(0.,.08),'leaf_width_m':(.004,.04),
        'bract_length_m':(.004,.04),'bract_width_m':(.003,.03),
        'ray_length_m':(.015,.15),'fork_length_ratio':(.3,.85),
        'ray_elevation_deg':(10.,75.),'fork_spread_deg':(10.,70.)}
COUNTS={'shoot_count':(1,6),'main_nodes':(4,16),'ray_count':(2,8),'fork_levels':(0,3)}
def cyme_herb_profile(value):
    if not isinstance(value,dict) or value.get('form')!='pleiochasial_herb':return None
    for key,(lo,hi) in {**RANGES,**COUNTS}.items():
        n=value.get(key)
        if isinstance(n,bool) or not isinstance(n,(int,float)) or not math.isfinite(n) or not lo<=n<=hi or key in COUNTS and int(n)!=n:return None
    return {'form':value['form'],'version':CYME_HERB_VERSION,
            **{k:float(value[k]) for k in RANGES},**{k:int(value[k]) for k in COUNTS},
            'status':str(value.get('status') or 'qualitative_cyme_display_fit')}

def build_cyme_herb(growth,maturity,flowering,fruiting,seed,leaf_factor=1.):
    p=growth['cyme_herb_profile'];m=max(0.,min(1.,maturity));nodes=[];area=axis_length=0.;bracts=cyathia=capsules=0
    rng=random.Random(f'{seed}:cyme_axes');phase=rng.uniform(0,math.tau)
    leaf_length=growth['leaf_length_m'];height=min(p['shoot_height_m'],growth['max_height_m'])*m;leaf_ordinal=0
    active=m>.65;sexual=growth.get('reproductive_mode') in {'sexual','both','apomictic'}
    def add(kind,parent,pos,angle=0.,scale=1.,role='',forward=None):
        nonlocal axis_length
        start=nodes[parent]['position'] if parent>=0 else (0.,0.,0.)
        path=[start,pos] if kind in {'stem_section','branch_section'} else None
        if path:axis_length+=math.dist(start,pos)
        nodes.append({'kind':kind,'parent':parent,'position':pos,'angle':angle,'scale':scale,
            'path':path,'forward':forward,'role':role,'min_lod':0 if path else 1})
        return len(nodes)-1
    def leaf(host,pos,az,length,width,role,elevation=.15):
        nonlocal area,bracts,leaf_ordinal
        leaf_ordinal+=1
        if (leaf_ordinal*.61803398875)%1>=max(0.,min(1.,leaf_factor)):return
        scale=length/max(leaf_length,1e-9)
        forward=[math.cos(az)*math.cos(elevation),math.sin(az)*math.cos(elevation),math.sin(elevation)]
        index=add('leaf',host,pos,math.degrees(az),scale,role,forward)
        nodes[index]['area_m2']=length*width*.60;area+=nodes[index]['area_m2']
        nodes[index]['width_m']=width;bracts+=role=='cyme_bract'
    def unit(host,az,level):
        nonlocal cyathia,capsules
        pos=nodes[host]['position'];length=p['bract_length_m']*(.82**level)*math.sqrt(m)
        for side in (-1,1):leaf(host,pos,az+side*math.pi/2,length,p['bract_width_m']*(.82**level)*math.sqrt(m),'cyme_bract',rng.uniform(.35,.9))
        end=(pos[0]+math.cos(az)*.002,pos[1]+math.sin(az)*.002,pos[2]+.002)
        stalk=add('branch_section',host,end,math.degrees(az),.15,'reproductive_stalk')
        if sexual and (flowering>.02 or fruiting>.02):
            kind='fruit' if fruiting>.02 else 'flower'
            # A short stalk separates the 2 mm cyathium / 3 mm capsule from
            # its photosynthetic bracts; neither bract is counted as a flower.
            add(kind,stalk,end,180. if kind=='fruit' else 0.,1.,'cyathium' if kind=='flower' else 'capsule',
                [0.,0.,-1. if kind=='fruit' else 1.])
            cyathia+=kind=='flower';capsules+=kind=='fruit'
    def fork(host,az,length,level):
        unit(host,az,level)
        if level>=p['fork_levels']:return
        origin=nodes[host]['position']
        for side in (-1,1):
            angle=az+side*math.radians(p['fork_spread_deg'])
            reach=length*p['fork_length_ratio']*rng.uniform(.85,1.15)
            elev=math.radians(p['ray_elevation_deg']+rng.uniform(-8,8))
            pos=(origin[0]+math.cos(angle)*reach*math.cos(elev),origin[1]+math.sin(angle)*reach*math.cos(elev),origin[2]+reach*math.sin(elev))
            child=add('branch_section',host,pos,math.degrees(angle),.38*(.65**level),'dichasial_ray')
            fork(child,angle,reach,level+1)
    count=round(p['shoot_count']*math.sqrt(m)) if m else 0
    for k in range(count):
        az=phase+k*2.399963;r=p['tuft_radius_m']*math.sqrt(m)
        x,y=r*math.cos(az),r*math.sin(az);parent=-1
        h=height*rng.uniform(.82,1.);n=max(1,round(p['main_nodes']*m))
        for j in range(n):
            t=(j+1)/n;pos=(x+h*.045*t*t*math.cos(az),y+h*.045*t*t*math.sin(az),h*t)
            parent=add('stem_section',parent,pos,math.degrees(az),1.-.4*t,'leafy_axis')
            leaf(parent,pos,az+j*2.399963,leaf_length*math.sqrt(m)*rng.uniform(.7,1.05),p['leaf_width_m']*math.sqrt(m),'cauline_leaf',rng.uniform(.25,1.1))
        if not active:continue
        top=nodes[parent]['position']
        for j in range(p['ray_count']):
            angle=az+j*math.tau/p['ray_count']+rng.uniform(-.15,.15);length=p['ray_length_m']*math.sqrt(m)*rng.uniform(.8,1.1)
            leaf(parent,top,angle,leaf_length*.72*math.sqrt(m),p['leaf_width_m']*math.sqrt(m),'involucral_leaf',.4)
            elev=math.radians(p['ray_elevation_deg']+rng.uniform(-7,7))
            pos=(top[0]+math.cos(angle)*length*math.cos(elev),top[1]+math.sin(angle)*length*math.cos(elev),top[2]+length*math.sin(elev))
            ray=add('branch_section',parent,pos,math.degrees(angle),.5,'primary_ray')
            fork(ray,angle,length,0)
    return nodes,{'cyme_herb_version':CYME_HERB_VERSION,'shoot_count':count,'cyme_bract_count':bracts,
        'cyathium_count':cyathia,'capsule_count':capsules,'estimated_leaf_count':sum(n['kind']=='leaf' for n in nodes),
        'leaf_area_m2':round(area,6),'structural_axis_length_m':round(axis_length,6),
        'reproductive_visual_unit':'one_cyathium_or_one_capsule; photosynthetic_bracts_are_separate_leaves'}

@lru_cache(maxsize=32)
def _bract_palette(source):
    palette={}
    for y in range(source.get_height()):
        for x in range(source.get_width()):
            c=tuple(source.get_at((x,y)))
            if c[3]:palette[c]=palette.get(c,0)+1
    if not palette:return None
    return max(palette,key=palette.get),max(palette,key=lambda c:sum(c[:3])),min(palette,key=lambda c:sum(c[:3]))

def draw_cyme_bract(screen,source,origin,tip,width_px,transverse=None,cup_offset=(0.,0.)):
    """Code-native triangular leaf silhouette using the authored leaf palette."""
    import pygame
    if source is None or math.dist(origin,tip)<.5:return False
    colors=_bract_palette(source)
    if not colors:return False
    body,vein,shade=colors
    dx,dy=tip[0]-origin[0],tip[1]-origin[1];norm=math.hypot(dx,dy)
    w=max(.5,width_px*.5)
    # A screen-perpendicular width makes every blade face the viewer,
    # even when its actual lamina is edge-on. Project both physical axes.
    perp=transverse if transverse is not None else (-dy/norm*w,dx/norm*w)
    outline=[origin];curve=[(.05,.60),(.18,1.),(.45,.88),(.73,.5)]
    def edge(t,width,side):
        # Raised margins form a shallow cup; offset is a projected z-up
        # distance, so side and overhead views show the same lamina.
        return (origin[0]+dx*t+side*perp[0]*width+cup_offset[0]*width*width,
                origin[1]+dy*t+side*perp[1]*width+cup_offset[1]*width*width)
    outline.extend(edge(t,width,1) for t,width in curve)
    outline.append(tip)
    outline.extend(edge(t,width,-1) for t,width in reversed(curve))
    pygame.draw.polygon(screen,body,outline)
    pygame.draw.polygon(screen,shade,[origin,*(outline[-i] for i in range(1,5)),tip])
    pygame.draw.line(screen,vein,origin,tip,1)
    return True
