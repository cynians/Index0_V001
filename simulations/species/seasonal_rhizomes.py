"""Persistent rhizome networks bearing replaceable seasonal aerial shoots.

Shoot arrangement, depth, counts and calendar windows are qualitative recipes.
Rhizomes are stems, roots remain separate, and a compound blade is one leaf.
"""
import math
import random

SEASONAL_RHIZOME_VERSION = 1


def seasonal_rhizome_profile(value):
    if not isinstance(value, dict) or value.get('form') != 'seasonal_rhizome':
        return None
    ranges = {'rhizome_length_m': (.02, 2.), 'rhizome_depth_m': (.005, .15),
              'rhizome_radius_m': (.0005, .02), 'shoot_height_m': (.03, 1.),
              'shoot_radius_m': (.0003, .01), 'bract_height_fraction': (.2, .85),
              'petiole_length_m': (.003, .08), 'leaf_width_ratio': (.3, 1.5),
              'leaf_pitch_deg': (-25., 65.), 'basal_petiole_length_m': (.01, .4),
              'fruit_peduncle_drop': (0., 1.),
              'fruit_head_size_m': (.003, .04)}
    counts = {'rhizome_axes': (1, 4), 'buds_per_axis': (1, 8),
              'bracts_per_shoot': (0, 6), 'basal_leaves_per_bud': (0, 2)}
    for key, (lo, hi) in {**ranges, **counts}.items():
        n = value.get(key)
        if (isinstance(n, bool) or not isinstance(n, (int, float)) or
                not math.isfinite(n) or not lo <= n <= hi or
                (key in counts and not isinstance(n, int))):
            return None
    return {'form': 'seasonal_rhizome', 'version': SEASONAL_RHIZOME_VERSION,
            **{k: float(value[k]) for k in ranges}, **{k: value[k] for k in counts},
            'status': str(value.get('status') or 'qualitative_display_recipe')}


def grow_seasonal_rhizome(sim, placements, maturity, state, paths, attachments, clusters, contacts):
    g = sim.blueprint.growth
    p = g['seasonal_rhizome_profile']
    m = max(0., min(1., maturity))
    leaf_factor = max(0., min(1., state.get('leaf_factor', 1.)))
    root = sim._add(placements, 'root', -1, 0, 0, 0, 0, 1, 0)
    origin = (0., 0., -p['rhizome_depth_m'])
    phase = random.Random(sim.seed ^ 0x5EA5).random()*math.tau
    buds = []
    rhizome_length = aerial_length = 0.

    def axis(parent, start, end, radius, role, curve=None):
        index = sim._add(placements, 'branch_section' if role == 'rhizome' else 'stem_section',
                         parent, *end, 0, radius, 0, paths, curve or [start, end])
        sim._placement_orientation_hints[str(index)] = {'seasonal_axis_role': role}
        attachments.append({'placement_index': index, 'host_placement_index': parent,
                            'socket': role+'_base', 'position_m': list(start)})
        return index

    # Build persistent structures first so their indices and bud identities
    # remain stable while above-ground seasonal cohorts disappear and return.
    for r in range(p['rhizome_axes']):
        az = phase+r*2.55
        parent, start = root, origin
        for j in range(p['buds_per_axis']):
            t = (j+1)/p['buds_per_axis']
            if t > m+.001:
                break
            pos = (math.cos(az)*p['rhizome_length_m']*t,
                   math.sin(az)*p['rhizome_length_m']*t+math.sin(t*math.pi)*p['rhizome_length_m']*.12,
                   origin[2])
            rhizome = axis(parent, start, pos, p['rhizome_radius_m']*max(.2, math.sqrt(m)), 'rhizome')
            rhizome_length += math.dist(start, pos)
            bud = sim._add(placements, 'renewal_bud', rhizome, *pos, 0, .12, 0)
            bud_id = f'{r}:{j}'
            attachments.append({'placement_index': bud, 'host_placement_index': rhizome,
                                'socket': 'rhizome_bud', 'position_m': list(pos), 'bud_id': bud_id})
            contacts.append({'parent_index': rhizome, 'position': list(pos)})
            buds.append((bud, pos, bud_id, az+j*.67))
            parent, start = rhizome, pos

    leaf_count = shoot_count = flower_count = fruit_count = 0

    def blade(host, pos, azimuth, scale, role):
        nonlocal leaf_count
        pitch = math.radians(p['leaf_pitch_deg'])
        forward = (math.cos(azimuth)*math.cos(pitch), math.sin(azimuth)*math.cos(pitch), math.sin(pitch))
        normal = (-math.cos(azimuth)*math.sin(pitch), -math.sin(azimuth)*math.sin(pitch), math.cos(pitch))
        idx = sim._add(placements, 'leaf', host, *pos, math.degrees(azimuth), scale, 1)
        frame = {**sim._orientation_frame(forward), 'normal': list(normal),
                 'seasonal_planar_blade': True, 'leaf_role': role}
        sim._placement_orientation_hints[str(idx)] = frame
        length = sim.blueprint.module('leaf').length_m*scale
        # Entire divided blade counted once; its three leaflets are artwork.
        area = length*length*p['leaf_width_ratio']*.43
        cid = sim._add_leaf_cluster(clusters, idx, *pos, 1, area, 0)
        from simulations.species.emergent_rosettes import planar_blade_bounds
        corners = planar_blade_bounds(pos, frame, length, p['leaf_width_ratio'])
        clusters[-1].update(explicit_samples=True, sample_placement_indices=[idx],
            organ_bounds_m=[min(x[a] for x in corners) if side == 0 else max(x[a] for x in corners)
                            for a in range(3) for side in range(2)])
        attachments.append({'stem_placement_index': host, 'leaf_placement_index': idx,
                            'socket': role+'_base', 'position_m': list(pos), 'cluster_id': cid})
        leaf_count += 1

    for ordinal, (bud, pos, bud_id, az) in enumerate(buds):
        # Turnover removes whole shoots rather than leaving leafless summer
        # stalks standing above an otherwise dormant geophyte.
        threshold = (ordinal*.61803398875+.09) % 1.
        if leaf_factor <= threshold:
            continue
        shoot_count += 1
        size = max(.05, math.sqrt(m))
        height = p['shoot_height_m']*size*(.87+.13*math.sin(ordinal*2.7+1)**2)
        collar = (pos[0]+math.cos(az)*height*.04, pos[1]+math.sin(az)*height*.04,
                  height*p['bract_height_fraction'])
        stem = axis(bud, pos, collar, p['shoot_radius_m']*size, 'seasonal_shoot')
        aerial_length += math.dist(pos, collar)
        for j in range(p['bracts_per_shoot']):
            a = az+j*math.tau/max(1, p['bracts_per_shoot'])
            petiole_tip = (collar[0]+math.cos(a)*p['petiole_length_m']*size,
                           collar[1]+math.sin(a)*p['petiole_length_m']*size, collar[2]+.006*size)
            petiole = axis(stem, collar, petiole_tip, p['shoot_radius_m']*.4*size, 'petiole')
            aerial_length += math.dist(collar, petiole_tip)
            blade(petiole, petiole_tip, a, size*.78, 'involucral_bract')
        flower_tip = (collar[0]+math.cos(az)*height*.08, collar[1]+math.sin(az)*height*.08, height)
        reproductive = g.get('reproductive_mode') in {'sexual', 'both', 'apomictic'}
        fruit = reproductive and state.get('fruiting_factor', 0.) > .05
        bloom = reproductive and state.get('reproductive_factor', 0.) > .05
        curve = [collar, flower_tip]
        if fruit and p['fruit_peduncle_drop'] > 0:
            reach = height*.26*p['fruit_peduncle_drop']
            curve = [collar, flower_tip,
                     (flower_tip[0]+math.cos(az)*reach*.65, flower_tip[1]+math.sin(az)*reach*.65, height+.005),
                     (flower_tip[0]+math.cos(az)*reach, flower_tip[1]+math.sin(az)*reach, height-reach*.55)]
            flower_tip = curve[-1]
        peduncle = axis(stem, collar, flower_tip, p['shoot_radius_m']*.7*size, 'peduncle', curve)
        aerial_length += sum(math.dist(a, b) for a, b in zip(curve, curve[1:]))
        if fruit or bloom:
            kind = 'fruit' if fruit else 'flower'
            idx = sim._add(placements, kind, peduncle, *flower_tip, 180 if fruit else 0, size, 1)
            sim._placement_orientation_hints[str(idx)] = {
                **sim._orientation_frame((0., 0., -1. if fruit else 1.)), 'seasonal_reproductive_head': True,
                'visual_unit': 'achene_head' if fruit else 'one_flower'}
            attachments.append({'placement_index': idx, 'host_placement_index': peduncle,
                                'socket': kind+'_base', 'position_m': list(flower_tip), 'bud_id': bud_id})
            flower_count += int(not fruit)
            fruit_count += int(fruit)
        # Separate basal leaves arise from the same rhizome bud after flowering.
        if state.get('season_fraction', 0.) >= (g.get('reproductive_profile') or {}).get('fruit_start', 1.):
            for j in range(p['basal_leaves_per_bud']):
                a = az+1.1+j*2.4
                tip = (pos[0]+math.cos(a)*.02, pos[1]+math.sin(a)*.02, p['basal_petiole_length_m']*size)
                petiole = axis(bud, pos, tip, p['shoot_radius_m']*.5*size, 'basal_petiole')
                aerial_length += math.dist(pos, tip)
                blade(petiole, tip, a, size, 'basal_leaf')
    return {'seasonal_rhizome_version': SEASONAL_RHIZOME_VERSION,
            'rhizome_bud_count': len(buds), 'seasonal_shoot_count': shoot_count,
            'seasonal_flower_count': flower_count, 'seasonal_fruit_head_count': fruit_count,
            'estimated_leaf_count': leaf_count,
            'leaf_area_m2': round(sum(c['leaf_area_m2'] for c in clusters), 6),
            'rhizome_axis_length_m': round(rhizome_length, 6),
            'aerial_axis_length_m': round(aerial_length, 6),
            'structural_axis_length_m': round(rhizome_length+aerial_length, 6),
            'renewal_bud_depth_source': 'qualitative_recipe_not_measured_depth',
            'seasonal_shoot_factor': leaf_factor,
            'seasonal_calendar_status': 'authored_qualitative_windows' if 'leaf_factor' in state else 'unresolved_neutral_active',
            'seasonal_rhizome_status': p['status']}
