"""Axial shoots supporting peripheral foliage in a shared authored plane.

The displayed branch system represents a bounded group of fine systems.
Counts and group footprints are qualitative, not a measured canopy census.
Single-needle dimensions remain separate from the whole-shoot artwork.
"""
import math
import random

PLANAR_SPRAY_VERSION = 2


def planar_spray_profile(value):
    if not isinstance(value,dict) or value.get('form')!='planar_foliage_sprays':return None
    ranges={'axis_length_m':(.1,2.),'axis_radius_m':(.0005,.015),
            'peripheral_length_m':(.04,.35),'plane_tilt_deg':(-50.,50.),
            'plane_roll_variation_deg':(0.,55.),'side_angle_deg':(30.,85.),
            'needle_width_m':(.0004,.004),'axial_leaf_length_m':(.002,.012),
            'axial_leaf_width_m':(.0003,.003)}
    counts={'rows_per_axis':(3,12),'needle_pairs_per_shoot':(3,24),'represented_systems':(1,128),
            'axial_leaves_per_node':(2,8)}
    for key,(lo,hi) in {**ranges,**counts}.items():
        x=value.get(key)
        if (isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x)
                or not lo<=x<=hi or (key in counts and not isinstance(x,int))):return None
    return {'form':'planar_foliage_sprays','version':PLANAR_SPRAY_VERSION,
            **{k:float(value[k]) for k in ranges},**{k:value[k] for k in counts},
            'status':str(value.get('status') or 'qualitative_foliage_group_recipe')}


def point_in_plane(origin,forward,right,along,across):
    return [origin[a]+forward[a]*along+right[a]*across for a in range(3)]


def spray_frame(azimuth,tilt,roll):
    f=(math.cos(azimuth)*math.cos(tilt),math.sin(azimuth)*math.cos(tilt),math.sin(tilt))
    side=(-math.sin(azimuth),math.cos(azimuth),0.)
    up=(-math.cos(azimuth)*math.sin(tilt),-math.sin(azimuth)*math.sin(tilt),math.cos(tilt))
    r=tuple(side[a]*math.cos(roll)+up[a]*math.sin(roll) for a in range(3))
    n=(f[1]*r[2]-f[2]*r[1],f[2]*r[0]-f[0]*r[2],f[0]*r[1]-f[1]*r[0])
    return f,r,n


def grow_planar_spray(sim,placements,parent,azimuth,identity,maturity,lod,clusters,attachments,paths,
                      leaf_factor=1.,detail=False,leader=False,support_normal=None):
    g=sim.blueprint.growth;p=g['planar_spray_profile']
    rng=random.Random(sim.seed*1009+identity+8701)
    scale=max(.05,min(1.,maturity))**.5
    length=p['axis_length_m']*scale
    tilt=math.radians(p['plane_tilt_deg']+rng.uniform(-8,8))
    roll=math.radians(rng.uniform(-p['plane_roll_variation_deg'],p['plane_roll_variation_deg']))
    if leader:
        tilt=math.pi*.5;length=min(length,p['axis_length_m']*.5)
    forward,right,normal=spray_frame(azimuth,tilt,roll)
    if support_normal is not None and not leader:
        # Carry the supporting branch plane through the terminal system.
        # Its azimuth stays outward while its slope follows that plane.
        normal=tuple(support_normal)
        x,y=math.cos(azimuth),math.sin(azimuth)
        z=-(normal[0]*x+normal[1]*y)/normal[2]
        norm=math.sqrt(1+z*z)
        forward=(x/norm,y/norm,z/norm)
        right=(normal[1]*forward[2]-normal[2]*forward[1],
               normal[2]*forward[0]-normal[0]*forward[2],
               normal[0]*forward[1]-normal[1]*forward[0])
    origin=placements[parent][2:5]
    groups=max(1,round(p['represented_systems']*max(.02,maturity)**.7))
    rows=max(2,round(p['rows_per_axis']*scale))
    axis_hosts=[];axis_points=[];axis_length=0.;start=list(origin)
    for j in range(rows):
        t=(j+1)/rows
        end=point_in_plane(origin,forward,right,length*t,length*.04*math.sin(t*math.pi))
        index=sim._add(placements,'branch_section',parent,*end,0.,p['axis_radius_m']*(1-.65*t),4,paths,[start,end])
        sim._placement_orientation_hints[str(index)]={**sim._orientation_frame(forward),
            'planar_spray_identity':identity,'spray_axis_role':'axial'}
        attachments.append({'placement_index':index,'host_placement_index':parent,
                            'socket':'axial_base','position_m':start})
        axis_length+=math.dist(start,end);axis_hosts.append(index);axis_points.append(end)
        parent=index;start=end
    peripheral=[]
    needle_count=0
    if not leader:
        for j,(host,base) in enumerate(zip(axis_hosts,axis_points)):
            for side in (-1,1):
                # Paired display ranks represent a side-shoot group; the
                # botanical spiral leaf-arrangement field is preserved.
                a=math.radians(p['side_angle_deg'])
                direction=tuple(forward[k]*math.cos(a)+right[k]*side*math.sin(a) for k in range(3))
                shoot_length=p['peripheral_length_m']*(.72+.28*math.sin((j+1)/(rows+1)*math.pi))
                tip=[base[k]+direction[k]*shoot_length for k in range(3)]
                index=sim._add(placements,'branch_section',host,*tip,0.,.0008,5,paths,[base,tip])
                sim._placement_orientation_hints[str(index)]={**sim._orientation_frame(direction),
                    'normal':list(normal),'planar_spray_identity':identity,'spray_axis_role':'peripheral'}
                attachments.append({'placement_index':index,'host_placement_index':host,
                                    'socket':'peripheral_base','position_m':base})
                peripheral.append({'base_m':base,'tip_m':tip,'forward':list(direction),
                                   'normal':list(normal),'length_m':shoot_length,'host_index':index})
                axis_length+=math.dist(base,tip)
                needle_count+=p['needle_pairs_per_shoot']*2
    peripheral_count=round(needle_count*groups*leaf_factor)
    dimorphic=g.get('shoot_dimorphism')=='axial_and_peripheral_shoots'
    axial_count=round(rows*p['axial_leaves_per_node']*groups*leaf_factor) if dimorphic else 0
    # Distinct morphotypes contribute their own organ areas once.
    peripheral_area=peripheral_count*sim.blueprint.module('leaf').length_m*p['needle_width_m']
    axial_area=axial_count*p['axial_leaf_length_m']*p['axial_leaf_width_m']
    midpoint=axis_points[len(axis_points)//2]
    cid=sim._add_leaf_cluster(clusters,axis_hosts[0],*midpoint,peripheral_count+axial_count,
                             peripheral_area+axial_area,3,allow_empty=True)
    width=max(sim.blueprint.module('leaf').length_m*2.,p['peripheral_length_m']*math.sqrt(groups)*.45)
    thickness=p['peripheral_length_m']*math.sqrt(groups)*.18
    payload={'identity':identity,'origin_m':list(origin),'axis_points_m':axis_points,
             'forward':list(forward),'right':list(right),'normal':list(normal),
             'peripheral_shoots':peripheral,'represented_systems':groups,'group_half_width_m':width,
             'group_half_thickness_m':thickness,
             'peripheral_leaf_count':peripheral_count,'axial_leaf_count':axial_count,
             'peripheral_leaf_area_m2':peripheral_area,'axial_leaf_area_m2':axial_area,
             'detail_single_system':bool(detail),'leader':bool(leader)}
    points=[list(origin),*axis_points]+[s['tip_m'] for s in peripheral]
    margin=max(width+thickness,sim.blueprint.module('leaf').length_m)
    clusters[-1].update(planar_spray=payload,identity=identity,explicit_samples=False,
        organ_bounds_m=[min(q[k] for q in points)-margin if side==0 else max(q[k] for q in points)+margin
                       for k in range(3) for side in (0,1)])
    return {'axis_length_m':axis_length,'cluster_id':cid,'identity':identity,'plane_normal':list(normal)}


def draw_planar_spray(renderer,screen,sim,camera,cohort,sample_cap=None):
    import pygame
    from simulations.species.floating_leaves import draw_planar_leaf
    p=cohort['planar_spray']
    if cohort['estimated_leaf_count']==0 or (sample_cap is not None and sample_cap<=0):return
    ppm=renderer._projection_pixels_per_meter(camera)
    source=renderer._module_asset(sim,'leaf')
    axial=renderer._module_asset(sim,'axial_leaf')
    normal=p['normal'];right=p['right'];width=p['group_half_width_m']
    color=renderer._color('leaf',sim,int(p['identity']))
    def project(pos):return renderer._path_screen(camera,pos)
    for j,shoot in enumerate(p['peripheral_shoots']):
        base,tip=shoot['base_m'],shoot['tip_m']
        if p['detail_single_system'] or shoot['length_m']*ppm/renderer._pixel_scale(camera)>=9.:
            if source is not None:
                draw_planar_leaf(screen,source,camera,base,shoot['forward'],normal,
                                 shoot['length_m'],sim.blueprint.module('leaf').attachment_point)
        else:
            # The footprint is a group of parallel foliated systems, never
            # a lengthened individual needle or a single giant flat leaf.
            # Sparse, deterministic shoot marks keep air between systems.
            # A filled triangular hull erased the fine foliage texture and
            # made every group read as one broad flat organ.
            rng=random.Random(int(p['identity'])*733+j*31+sim.seed)
            samples=min(12,max(3,round(math.sqrt(p['represented_systems'])*.6)))
            for sample in range(samples):
                across=rng.uniform(-width,width)
                depth=rng.uniform(-1,1)*p['group_half_thickness_m']
                along=rng.uniform(-.12,.12)
                offset=[right[k]*across+normal[k]*depth+p['forward'][k]*along for k in range(3)]
                a=project([base[k]+offset[k] for k in range(3)])
                b=project([tip[k]+offset[k] for k in range(3)])
                if a is not None and b is not None:
                    tone=tuple(max(0,min(255,round(c*(.78+.07*(sample%4))))) for c in color)
                    pygame.draw.line(screen,tone,a,b,1)
    # Compact appressed-leaf modules belong on axial shoots, not broad,
    # two-ranked peripheral artwork stamped onto the leader.
    for pos in p['axis_points_m'] if p.get('axial_leaf_count',0) else []:
        if axial is not None and ppm/renderer._pixel_scale(camera)*.06>=4.:
            module=sim.blueprint.module('axial_leaf')
            draw_planar_leaf(screen,axial,camera,pos,p['forward'],normal,.06,module.attachment_point)
        else:
            point=project(pos)
            if point is not None:pygame.draw.circle(screen,color,point,1)
