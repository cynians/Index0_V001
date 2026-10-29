"""Persistent rhizomes, leafy annual axes and acropetal flower/capsule racemes.

The bounded patch, counts and seasonal fractions are qualitative display fits.
Individual flowers/fruits are separate organs, not a painted whole raceme.
"""
import math
import random

VERSION = 1
RANGES = {'rhizome_length_m': (.05, 2.), 'rhizome_depth_m': (.005, .2),
          'rhizome_radius_m': (.001, .02), 'stem_radius_m': (.001, .01),
          'leaf_width_m': (.003, .04), 'raceme_length_m': (.05, .5),
          'pedicel_length_m': (.005, .06), 'flower_size_m': (.01, .06),
          'capsule_length_m': (.02, .1)}
COUNTS = {'shoot_count': (1, 12), 'leaf_nodes': (8, 40), 'raceme_nodes': (6, 40)}


def rhizome_raceme_profile(value):
    if not isinstance(value, dict) or value.get('form') != 'rhizome_raceme': return None
    for k, (lo, hi) in {**RANGES, **COUNTS}.items():
        x = value.get(k)
        if (isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x)
                or not lo <= x <= hi or k in COUNTS and not isinstance(x, int)): return None
    return {'form': 'rhizome_raceme', 'version': VERSION,
            **{k: float(value[k]) for k in RANGES}, **{k: value[k] for k in COUNTS},
            'status': str(value.get('status') or 'qualitative_patch_and_flowering_sequence')}


def raceme_stage(rank, progress):
    """A flowering front moves from bottom to top, with capsules behind it."""
    local = progress*1.6-rank*.9
    return 'bud' if local < 0 else 'flower' if local < .5 else 'fruit'


def grow_rhizome_racemes(sim, placements, maturity, age, state, paths, attachments, clusters, contacts):
    g = sim.blueprint.growth; p = g['rhizome_raceme_profile']
    m = max(0., min(1., maturity)); root = sim._growth_origin(placements)
    phase = random.Random(sim.seed+7411).uniform(0, math.tau)
    profile = g.get('reproductive_profile') or {}
    cycle = profile.get('cycle_days', 365.)
    season = (age % cycle)/cycle
    start = profile.get('flowering_start', .4); end = profile.get('flowering_end', .72)
    retention = profile.get('fruit_retention_end', .93)
    progress = (season-start)/max(.01, end-start)
    sexual = bool(profile) and g.get('reproductive_mode') in {'sexual','both','apomictic'}
    leafy = max(0., min(1., state.get('leaf_factor', 1.)))
    shoots = round(p['shoot_count']*m)
    leaf_count = flowers = fruits = 0; length = 0.; records = []

    def axis(parent, a, b, role, radius):
        nonlocal length
        i = sim._add(placements, 'branch_section' if role=='rhizome' else 'stem_section',
                     parent, *b, 0., radius,
                     0, paths, [a,b])
        sim._placement_orientation_hints[str(i)] = {'axis_role': role, 'min_render_lod': 0}
        attachments.append({'placement_index':i,'host_placement_index':parent,
                            'socket':role+'_base','position_m':list(a)})
        length += math.dist(a,b)
        return i

    parent = root; previous = (0.,0.,-p['rhizome_depth_m']); slots = []
    for s in range(shoots):
        theta = phase+s*2.39996323
        distance = p['rhizome_length_m']*(s+1)/p['shoot_count']*m
        base = (math.cos(theta)*distance,math.sin(theta)*distance,-p['rhizome_depth_m'])
        rhizome = axis(parent,previous,base,'rhizome',p['rhizome_radius_m'])
        contacts.append({'parent_index':rhizome,'position':list(base)})
        parent,previous = rhizome,base
        slots.append((s,theta,rhizome,base))
    # Persistent axes precede the aerial cohort, keeping their indices stable
    # through winter disappearance and the following year's replacement.
    for s,theta,rhizome,base in slots:
        # The annual aerial cohort is absent during the leafless model season.
        if leafy <= 0: continue
        height = g['max_height_m']*m*(.82+.18*random.Random(sim.seed+s+54).random())
        raceme_length = min(height*.4,p['raceme_length_m']*m)
        foliage_height = height-raceme_length
        host = axis(rhizome,base,(base[0],base[1],0.),'shoot_base',p['stem_radius_m'])
        position = (base[0],base[1],0.)
        for j in range(p['leaf_nodes']):
            rank = (j+1)/p['leaf_nodes']
            endpos = (base[0]+.015*math.sin(rank*2),base[1]+.01*math.sin(rank*3),foliage_height*rank)
            host = axis(host,position,endpos,'leafy_axis',p['stem_radius_m']*(1-.4*rank))
            position = endpos
            az = theta+j*2.39996323
            scale = math.sqrt(m)*(.65+.35*math.sin(rank*math.pi))
            if rank > .85: scale *= .65
            if (j*.618+s*.31)%1 > leafy: continue
            idx = sim._add(placements,'leaf',host,*position,math.degrees(az),scale,1)
            pitch = math.radians(15+22*rank)
            forward = (math.cos(az)*math.cos(pitch),math.sin(az)*math.cos(pitch),math.sin(pitch))
            normal = (-math.cos(az)*math.sin(pitch),-math.sin(az)*math.sin(pitch),math.cos(pitch))
            frame = {**sim._orientation_frame(forward),'normal':list(normal),
                     'seasonal_planar_blade':True,'min_render_lod':0}
            sim._placement_orientation_hints[str(idx)] = frame
            leaf_length = sim.blueprint.module('leaf').length_m*scale
            width = p['leaf_width_m']*scale
            from simulations.species.emergent_rosettes import planar_blade_bounds
            corners = planar_blade_bounds(position,frame,leaf_length,p['leaf_width_m']/sim.blueprint.module('leaf').length_m)
            cid = sim._add_leaf_cluster(clusters,idx,*position,1,leaf_length*width*.64,0)
            clusters[-1].update(explicit_samples=True,sample_placement_indices=[idx],
                organ_bounds_m=[fn(pt[a] for pt in corners) for a in range(3) for fn in (min,max)])
            attachments.append({'stem_placement_index':host,'leaf_placement_index':idx,
                                'socket':'leaf','position_m':list(position),'cluster_id':cid})
            leaf_count += 1
        statuses = []
        # The inflorescence elongates with its ascending flowering front;
        # avoid an already full-length naked axis above the first flowers.
        extension = max(.08,min(1.,(1.6*max(0.,progress)+.10)/.9))
        for j in range(p['raceme_nodes']):
            if (j+1)/p['raceme_nodes'] > extension: break
            rank = (j+.5)/p['raceme_nodes']
            endpos = (position[0],position[1],foliage_height+raceme_length*(j+1)/p['raceme_nodes'])
            host = axis(host,position,endpos,'raceme_axis',p['stem_radius_m']*.4)
            position = endpos
            stage = raceme_stage(rank, progress)
            if not sexual or m < .85 or season < start or season > retention: continue
            if stage == 'bud': continue
            az = theta+j*2.39996323
            pedicel_end = (position[0]+math.cos(az)*p['pedicel_length_m'],
                           position[1]+math.sin(az)*p['pedicel_length_m'],position[2]+.008)
            pedicel = axis(host,position,pedicel_end,'pedicel',p['stem_radius_m']*.15)
            idx = sim._add(placements,stage,pedicel,*pedicel_end,0.,1.,2)
            sim._placement_orientation_hints[str(idx)] = {**sim._orientation_frame((math.cos(az)*.4,math.sin(az)*.4,1.)),
                'raceme_rank':rank,'shoot_identity':s,'min_render_lod':0}
            attachments.append({'placement_index':idx,'host_placement_index':pedicel,
                                'socket':stage+'_base','position_m':list(pedicel_end),'raceme_rank':rank})
            statuses.append({'rank':rank,'stage':stage,'placement_index':idx})
            if stage=='flower': flowers += 1
            else: fruits += 1
        records.append({'identity':s,'reproductive_organs':statuses})
    return {'rhizome_raceme_version':VERSION,'shoot_count':len(records),'rhizome_socket_count':shoots,
            'raceme_shoots':records,'raceme_flower_count':flowers,'raceme_capsule_count':fruits,
            'estimated_leaf_count':leaf_count,'leaf_area_m2':sum(c['leaf_area_m2'] for c in clusters),
            'structural_axis_length_m':length}
