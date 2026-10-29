"""Leafless, photosynthetic columns with delayed, upward turning arms.

Metric body envelopes and growth coefficients are authored visual controls,
not a water balance, carbon model or prediction of individual ages.
"""
import math
import random


def columnar_profile(value):
    if not isinstance(value, dict) or value.get('form') != 'columnar_succulent':
        return None
    if value.get('axis_layout') == 'basal_clump':
        ranges = {'stem_radius_m': (.005, .3), 'clump_radius_m': (.01, 3.),
                  'size_exponent': (1., 4.), 'reproductive_onset_fraction': (.05, 1.),
                  'areole_spacing_m': (.005, .2), 'spine_size_m': (.001, .15)}
        integers = {'stem_count': (1, 64), 'rib_count': (4, 40),
                    'flowers_per_tip': (1, 16)}
        for key, (lo, hi) in {**ranges, **integers}.items():
            n = value.get(key)
            if (isinstance(n, bool) or not isinstance(n, (int, float)) or
                    not math.isfinite(n) or not lo <= n <= hi or
                    (key in integers and not isinstance(n, int))):
                return None
        return {'form': 'columnar_succulent', 'axis_layout': 'basal_clump',
                'version': 2, **{k: float(value[k]) for k in ranges},
                **{k: value[k] for k in integers},
                'status': str(value.get('status') or 'provisional_basal_clump_visual_fit')}
    if value.get('axis_layout') not in (None, 'central_with_arms'):
        return None
    ranges = {'stem_radius_m':(.005,1.), 'arm_radius_m':(.003,.8),
              'arm_reach_m':(.01,4.), 'arm_height_fraction':(.1,.95),
              'arm_onset_fraction':(.1,.9), 'arm_onset_interval':(0.,.2),
              'arm_attachment_fraction':(.2,.95), 'size_exponent':(1.,4.),
              'reproductive_onset_fraction':(.05,1.), 'areole_spacing_m':(.005,.2),
              'spine_size_m':(.001,.15)}
    integers = {'arm_count':(0,12), 'rib_count':(4,40), 'flowers_per_tip':(1,16)}
    for key,(lo,hi) in {**ranges,**integers}.items():
        n=value.get(key)
        if (isinstance(n,bool) or not isinstance(n,(int,float)) or not math.isfinite(n)
                or not lo <= n <= hi or (key in integers and not isinstance(n,int))):
            return None
    if value['arm_radius_m'] > value['stem_radius_m']:
        return None
    return {'form':'columnar_succulent','version':1,
            **{k:float(value[k]) for k in ranges}, **{k:value[k] for k in integers},
            'status':str(value.get('status') or 'provisional_columnar_visual_fit')}


def size_fraction(profile, maturity):
    return max(0.,min(1.,float(maturity))) ** profile['size_exponent']


def grow_columns(sim, placements, maturity, life_state, attachments, paths):
    """Canonical axes at every LOD; spines are decorative modified leaves."""
    p=sim.blueprint.growth['columnar_profile']
    if p.get('axis_layout') == 'basal_clump':
        return grow_basal_clump(sim, placements, maturity, life_state, attachments, paths)
    fraction=size_fraction(p,maturity)
    height=sim.blueprint.growth['max_height_m']*fraction
    radius=min(p['stem_radius_m']*math.sqrt(fraction),height*.25)
    crown=sim._add(placements,'root',-1,0,0,0,0,1,0)
    axes=[]; tips=[]; arm_births=[]
    for i in range(p['arm_count']):
        onset=p['arm_onset_fraction']+i*p['arm_onset_interval']
        if onset >= 1 or maturity <= onset:
            continue
        # Lock the junction at its birth height: columns elongate at their tips.
        junction=sim.blueprint.growth['max_height_m']*onset**p['size_exponent']*p['arm_attachment_fraction']
        if junction < height-radius:
            arm_births.append((i,onset,junction))
    z_values=sorted(set([b[2] for b in arm_births]+[max(0.,height-radius)]))
    parent=crown; start=(0.,0.,0.); junctions={}
    for z in z_values:
        if z <= start[2]:
            continue
        end=(0.,0.,z)
        parent=sim._add(placements,'stem_section',parent,*end,0,radius,0,paths,[start,end])
        axes.append((parent,[start,end],radius))
        junctions[z]=parent;start=end
    if axes:
        tips.append((parent,start,radius))
    phase=random.Random(sim.seed ^ 0x32C1).random()*math.tau
    for i,onset,z in arm_births:
        rng=random.Random(sim.seed ^ (0x3431+i*7919))
        progress=(maturity-onset)/(1-onset)
        r=p['arm_radius_m']*math.sqrt(progress)
        reach=p['arm_reach_m']*rng.uniform(.8,1.2)*progress
        target_top=sim.blueprint.growth['max_height_m']*p['arm_height_fraction']*rng.uniform(.82,1.08)
        rise=max(.01,target_top-z)*progress**1.25
        r=min(r,reach*.4,rise*.4)
        angle=phase+i*2.399963229728653
        # A rounded elbow gradually changes from radial to vertical growth.
        elbow=min(reach,rise*.6)
        curve=[]
        for k in range(13):
            t=k/12; theta=t*math.pi/2
            radial=reach*math.sin(theta)
            up=elbow*(1-math.cos(theta))
            curve.append((math.cos(angle)*radial,math.sin(angle)*radial,z+up))
        for k in range(1,9):
            curve.append((curve[-1][0],curve[-1][1],z+elbow+(max(elbow,rise)-elbow)*k/8))
        end=curve[-1]
        index=sim._add(placements,'branch_section',junctions[z],*end,math.degrees(angle),r,1,paths,curve)
        axes.append((index,curve,r));tips.append((index,end,r))
    area=volume=length=0.
    for index,curve,r in axes:
        axis_length=sum(math.dist(a,b) for a,b in zip(curve,curve[1:]))
        length+=axis_length;area+=math.tau*r*axis_length;volume+=math.pi*r*r*axis_length
        attachments.append({'stem_placement_index':index,'position':list(curve[-1]),'socket':'tip'})
    flowers=fruits=0
    fertile=(bool(sim.blueprint.growth.get('reproductive_profile'))
             and sim.blueprint.growth.get('reproductive_mode') in {'sexual','both','apomictic'}
             and sim.blueprint.growth.get('reproductive_structure') == 'flower'
             and sim.blueprint.growth.get('flowering_position') in {'lateral','terminal','mixed'})
    for index,end,r in tips:
        if not fertile:
            continue
        if life_state.get('reproductive_factor',0) <= 0 and life_state.get('fruiting_factor',0) <= 0:
            continue
        for j in range(p['flowers_per_tip']):
            angle=j*math.tau/p['flowers_per_tip']+phase
            point=(end[0]+math.cos(angle)*r*.82,end[1]+math.sin(angle)*r*.82,end[2]+r*.55)
            # Flowers/fruit share terminal areoles; replace blooms after set.
            fruit=life_state.get('fruiting_factor',0) > .05
            kind='fruit' if fruit else 'flower'
            sim._add(placements,kind,index,*point,math.degrees(angle),1.,2)
            if fruit: fruits+=1
            else: flowers+=1
    return {'columnar_version':p['version'],'columnar_height_m':round(height,6),
            'columnar_radius_m':round(radius,6),'columnar_arm_count':len(arm_births),
            'columnar_axis_count':len(tips),'structural_axis_length_m':round(length,6),
            'estimated_leaf_count':0,'leaf_area_m2':0.,'leaf_cluster_count':0,
            'photosynthetic_stem_area_m2':round(area,6),'photosynthetic_area_m2':round(area,6),
            'stem_storage_volume_m3':round(volume,6),'columnar_flower_count':flowers,
            'columnar_fruit_count':fruits,'columnar_size_fraction':fraction,
            'columnar_model_status':p['status']}


def grow_basal_clump(sim, placements, maturity, life_state, attachments, paths):
    """Connected basal offshoots with individually delayed, rounded columns."""
    p = sim.blueprint.growth['columnar_profile']
    fraction = size_fraction(p, maturity)
    adult_height = sim.blueprint.growth['max_height_m']
    crown = sim._add(placements, 'root', -1, 0, 0, 0, 0, 1, 0)
    phase = random.Random(sim.seed ^ 0x32C1).random() * math.tau
    axes = []
    for i in range(p['stem_count']):
        onset = 0. if i == 0 else .12 + .68 * (i - 1) / max(1, p['stem_count'] - 1)
        if maturity <= onset:
            continue
        progress = max(0., min(1., (maturity - onset) / (1. - onset)))
        stem_fraction = fraction * progress
        if stem_fraction <= 0.:
            continue
        rng = random.Random(sim.seed ^ (0x4C51 + i * 7919))
        angle = phase + i * 2.399963229728653
        radial = 0. if i == 0 else p['clump_radius_m'] * math.sqrt(i / max(1, p['stem_count'] - 1))
        radial *= math.sqrt(stem_fraction) * rng.uniform(.82, 1.08)
        height = adult_height * stem_fraction * rng.uniform(.78, 1.0)
        radius = min(p['stem_radius_m'] * math.sqrt(stem_fraction), height * .48)
        if radius <= 0.:
            continue
        base = (radial * math.cos(angle), radial * math.sin(angle), 0.)
        # Older peripheral stems lean gently outward; every path stays attached
        # to the common root and ends at a distinct photosynthetic tip.
        lean = radial * .16 * stem_fraction
        tip = (base[0] + lean * math.cos(angle),
               base[1] + lean * math.sin(angle), height)
        mid = (base[0] + .35 * lean * math.cos(angle),
               base[1] + .35 * lean * math.sin(angle), height * .56)
        # The offshoot joins the common below-ground crown by its parent
        # socket. Its visible, photosynthetic surface starts at the stem base;
        # drawing the buried radial connection as a green column creates a
        # false horizontal cactus pad across the soil.
        curve = [base, mid, tip]
        index = sim._add(placements, 'stem_section', crown, *tip,
                         math.degrees(angle), radius, 0, paths, curve)
        axes.append((index, curve, radius, tip))
        attachments.append({'stem_placement_index': index,
                            'position': list(tip), 'socket': 'tip'})
    area = volume = length = 0.
    for _, curve, radius, _ in axes:
        axis_length = sum(math.dist(a, b) for a, b in zip(curve, curve[1:]))
        length += axis_length
        area += math.tau * radius * axis_length
        volume += math.pi * radius * radius * axis_length
    fertile = (bool(sim.blueprint.growth.get('reproductive_profile')) and
               sim.blueprint.growth.get('reproductive_mode') in {'sexual', 'both', 'apomictic'} and
               sim.blueprint.growth.get('reproductive_structure') == 'flower' and
               sim.blueprint.growth.get('flowering_position') in {'lateral', 'terminal', 'mixed'})
    flowers = fruits = 0
    if fertile and (life_state.get('reproductive_factor', 0) > 0 or
                    life_state.get('fruiting_factor', 0) > 0):
        for index, _, radius, tip in axes:
            if tip[2] < adult_height * p['reproductive_onset_fraction']:
                continue
            for j in range(p['flowers_per_tip']):
                angle = phase + j * math.tau / p['flowers_per_tip']
                point = (tip[0] + math.cos(angle) * radius * .9,
                         tip[1] + math.sin(angle) * radius * .9,
                         tip[2] - radius * .25)
                fruit = life_state.get('fruiting_factor', 0) > .05
                sim._add(placements, 'fruit' if fruit else 'flower', index,
                         *point, math.degrees(angle), 1., 2)
                fruits += int(fruit)
                flowers += int(not fruit)
    return {'columnar_version': p['version'],
            'columnar_height_m': round(max((axis[3][2] for axis in axes), default=0.), 6),
            'columnar_radius_m': round(max((axis[2] for axis in axes), default=0.), 6),
            'columnar_arm_count': 0, 'columnar_axis_count': len(axes),
            'columnar_clump_diameter_m': round(2 * p['clump_radius_m'] * math.sqrt(fraction), 6),
            'structural_axis_length_m': round(length, 6), 'estimated_leaf_count': 0,
            'leaf_area_m2': 0., 'leaf_cluster_count': 0,
            'photosynthetic_stem_area_m2': round(area, 6),
            'photosynthetic_area_m2': round(area, 6),
            'stem_storage_volume_m3': round(volume, 6),
            'columnar_flower_count': flowers, 'columnar_fruit_count': fruits,
            'columnar_size_fraction': fraction, 'columnar_model_status': p['status']}


def draw_column(screen, asset, spine_asset, points, radius_px, profile, ppm, terminal=True, cap_radius_px=None):
    """Round continuous axes with authored rib-strip colors and spine glyphs.

    Draw projected rib lanes along a curved axis. At whole-plant scale we
    sample areoles; their dimensions stay metric and samples add no leaf area.
    """
    import pygame
    r=max(.5,min(1024.,radius_px))
    cap_r=max(.5,min(1024.,cap_radius_px if cap_radius_px is not None else r))
    colors=[(64,94,63),(94,128,76),(133,154,92),(83,115,69),(58,87,59)]
    if asset is not None:
        box=asset.get_bounding_rect()
        if box.width and box.height:
            # Sample every rib in the cross-section. Five arbitrary source
            # pixels can all land on the same band and erase the grooves.
            palette=sorted({asset.get_at((x,box.centery))[:3] for x in range(box.left,box.right)},
                           key=lambda c:sum(c))
            colors=[palette[0],palette[len(palette)//2],palette[-1],palette[0],palette[0]]
    length=sum(math.dist(a,b) for a,b in zip(points,points[1:]))
    if length < r*.3:
        center=tuple(round(v) for v in points[-1])
        pygame.draw.circle(screen,colors[1],center,max(1,round(r)))
        for rib in range(profile['rib_count']):
            a=rib*math.tau/profile['rib_count']
            pygame.draw.line(screen,colors[0],center,
                             (center[0]+math.cos(a)*r,center[1]+math.sin(a)*r),1)
        return
    lanes=max(3,min(13,profile['rib_count']//2))
    offsets=[-r+2*r*i/lanes for i in range(lanes+1)]
    # End caps precede continuous lanes; this keeps segment joins round.
    for point in points:
        pygame.draw.ellipse(screen,colors[1],pygame.Rect(round(point[0]-r),round(point[1]-cap_r),
                                                      max(1,round(2*r)),max(1,round(2*cap_r))))
    for a,b in zip(points,points[1:]):
        dx,dy=b[0]-a[0],b[1]-a[1];distance=math.hypot(dx,dy)
        if distance < .01:
            continue
        nx,ny=-dy/distance,dx/distance
        segment_r=math.hypot(r*nx,cap_r*ny)
        offsets=[-segment_r+2*segment_r*i/lanes for i in range(lanes+1)]
        for i in range(lanes):
            lo,hi=offsets[i],offsets[i+1]
            color=colors[1 if i%2 else 2] if i not in {0,lanes-1} else colors[0]
            polygon=[(a[0]+nx*lo,a[1]+ny*lo),(b[0]+nx*lo,b[1]+ny*lo),
                     (b[0]+nx*hi,b[1]+ny*hi),(a[0]+nx*hi,a[1]+ny*hi)]
            pygame.draw.polygon(screen,color,polygon)
            pygame.draw.line(screen,colors[3],polygon[0],polygon[1],1)
        if asset is not None and asset.get_bounding_rect().width:
            # Structural art stays the authored pixel strip, stretched along
            # the connected axis, rather than reducing its contents to colors.
            # Divide very long off-screen axes before allocating surfaces.
            source=asset.subsurface(asset.get_bounding_rect())
            target_width=max(1,round(2*segment_r))
            if target_width < source.get_width():
                # Average subpixel rib bands; nearest-neighbour shrinking
                # alternately erased or inflated stripes on adjacent arms.
                source=pygame.transform.smoothscale(source,(target_width,source.get_height()))
            chunks=max(1,math.ceil(distance/1024))
            for chunk in range(chunks):
                center=(a[0]+dx*(chunk+.5)/chunks,a[1]+dy*(chunk+.5)/chunks)
                sprite=pygame.transform.scale(source,(target_width,max(2,round(distance/chunks)+2)))
                sprite=pygame.transform.rotate(sprite,-math.degrees(math.atan2(dx,-dy)))
                screen.blit(sprite,sprite.get_rect(center=tuple(round(v) for v in center)))
    # No fixed draw cap may enlarge areoles or alter the body. Downsample
    # solely when rows/ribs are smaller than a screen pixel; bounded at 2048.
    spacing=max(3.,profile['areole_spacing_m']*ppm)
    row_count=min(256,max(1,int(length/spacing)))
    glyph=None
    size=round(profile['spine_size_m']*ppm)
    if spine_asset is not None and size >= 6:
        box=spine_asset.get_bounding_rect()
        glyph=pygame.transform.scale(spine_asset.subsurface(box),(min(160,size),min(160,size)))
    travelled=0.;next_row=length/(row_count+1)
    for a,b in zip(points,points[1:]):
        d=math.dist(a,b)
        if d <= .001:
            continue
        nx,ny=-(b[1]-a[1])/d,(b[0]-a[0])/d
        segment_r=math.hypot(r*nx,cap_r*ny)
        while next_row <= travelled+d:
            t=(next_row-travelled)/d
            for lane in range(1,min(lanes,8)):
                offset=-segment_r+2*segment_r*lane/min(lanes,8)
                point=(a[0]+(b[0]-a[0])*t+nx*offset,a[1]+(b[1]-a[1])*t+ny*offset)
                if glyph is not None:
                    screen.blit(glyph,glyph.get_rect(center=(round(point[0]),round(point[1]))))
                elif r >= 3:
                    pygame.draw.circle(screen,(141,151,112),tuple(round(v) for v in point),1)
            next_row+=length/(row_count+1)
        travelled+=d
    if len(points)>1 and math.dist(points[-1],points[-2]) < .1:
        center=tuple(round(v) for v in points[-1])
        pygame.draw.circle(screen,colors[1],center,max(1,round(r)))
        for rib in range(profile['rib_count']):
            angle=rib*math.tau/profile['rib_count']
            pygame.draw.line(screen,colors[0],
                             (center[0]+math.cos(angle)*r*.2,center[1]+math.sin(angle)*r*.2),
                             (center[0]+math.cos(angle)*r*.9,center[1]+math.sin(angle)*r*.9),1)
    elif terminal and len(points)>1:
        # Fold rib grooves over the rounded meristem rather than leaving an
        # untextured green semicircle at the most diagnostic part of a cactus.
        end=points[-1];previous=next((v for v in reversed(points[:-1]) if math.dist(v,end)>.01),None)
        if previous is not None:
            d=math.dist(previous,end);dx=(end[0]-previous[0])/d;dy=(end[1]-previous[1])/d
            nx,ny=-dy,dx
            for lane in range(1,lanes):
                offset=-r+2*r*lane/lanes
                curve=[]
                for k in range(9):
                    t=k/8;side=offset*(1-t*.55)
                    advance=cap_r*math.sqrt(max(0.,1-(side/r)**2))*t
                    curve.append((end[0]+nx*side+dx*advance,end[1]+ny*side+dy*advance))
                pygame.draw.lines(screen,colors[3],False,curve,1)
                for point in curve[2::3]:
                    if glyph is not None:
                        screen.blit(glyph,glyph.get_rect(center=tuple(round(v) for v in point)))
                    elif r>=3:
                        pygame.draw.circle(screen,(141,151,112),tuple(round(v) for v in point),1)
