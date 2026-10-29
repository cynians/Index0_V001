"""Bounded persistent axes with terminal leaf rosettes and crown-borne panicles.

Topology, poses, counts and development fractions are qualitative recipes.
Leaves are individual organs; retained dead leaves contribute no live area.
This is not a rhizome recruitment or flowering-induced branching model.
"""
import math
import random

TERMINAL_ROSETTE_VERSION = 1


def rosette_blade_curve(base,azimuth,elevation,bend,length,segments=12):
    """Integrate a curved blade without changing its metric arc length."""
    curve=[base]
    for k in range(segments):
        angle=elevation-bend*(k+.5)/segments
        ds=length/segments;prev=curve[-1]
        curve.append((prev[0]+math.cos(azimuth)*math.cos(angle)*ds,
                      prev[1]+math.sin(azimuth)*math.cos(angle)*ds,
                      prev[2]+math.sin(angle)*ds))
    return curve


def terminal_rosette_profile(value):
    if not isinstance(value, dict) or value.get('form') != 'terminal_rosette':
        return None
    ranges = {
        'axis_height_m': (0., 20.), 'axis_radius_m': (.005, .8),
        'axis_spread_m': (0., 5.), 'leaf_width_m': (.001, .15),
        'leaf_bend': (0., .8), 'skirt_fraction': (0., 1.),
        'elevation_onset': (0., .9), 'peduncle_length_m': (0., 4.),
        'peduncle_radius_m': (.001, .08), 'panicle_length_m': (.05, 2.),
        'panicle_width_m': (.02, 1.5),
    }
    integers = {'crown_count': (1, 8), 'leaves_per_crown': (8, 160),
                'dead_leaves_per_crown': (0, 80), 'panicle_branches': (2, 24),
                'flowers_per_branch': (1, 12)}
    for key, (lo, hi) in {**ranges, **integers}.items():
        n = value.get(key)
        if (isinstance(n, bool) or not isinstance(n, (int, float)) or
                not math.isfinite(n) or not lo <= n <= hi or
                (key in integers and not isinstance(n, int))):
            return None
    layout = value.get('axis_layout')
    if layout not in {'basal_clump', 'forked'}:
        return None
    return {'form': 'terminal_rosette', 'version': TERMINAL_ROSETTE_VERSION,
            'axis_layout': layout, **{k: float(value[k]) for k in ranges},
            **{k: value[k] for k in integers},
            'status': str(value.get('status') or 'qualitative_visual_recipe')}


def grow_terminal_rosettes(sim, placements, maturity, life_state, attachments, paths, clusters):
    p = sim.blueprint.growth['terminal_rosette_profile']
    m = max(0., min(1., maturity))
    root = sim._add(placements, 'root', -1, 0, 0, 0, 0, 1, 0)
    phase = random.Random(sim.seed ^ 0x71E2).random() * math.tau
    crowns = []
    axis_length = 0.

    def axis(parent, start, end, radius, role, kind='stem_section'):
        nonlocal axis_length
        index = sim._add(placements, kind, parent, *end, 0, radius, 0, paths, [start, end])
        sim._placement_orientation_hints[str(index)] = {'axis_role': role}
        axis_length += math.dist(start, end)
        attachments.append({'placement_index': index, 'host_placement_index': parent,
                            'socket': role + '_base', 'position_m': list(start)})
        return index

    elongation = max(0., (m-p['elevation_onset']) / (1-p['elevation_onset'])) ** 1.3
    primary_top = (0., 0., .015 + p['axis_height_m'] * elongation)
    trunk = axis(root, (0., 0., 0.), primary_top,
                 p['axis_radius_m'] * max(.08, math.sqrt(m)), 'persistent_axis')
    crowns.append((trunk, primary_top, 1.))
    for c in range(1, p['crown_count']):
        onset = .24 + .45 * (c-1) / max(1, p['crown_count']-1)
        if m <= onset:
            continue
        progress = (m-onset) / (1-onset)
        az = phase + c * 2.399963229728653
        reach = p['axis_spread_m'] * math.sqrt(progress)
        radius = p['axis_radius_m'] * .72 * max(.08, math.sqrt(progress))
        if p['axis_layout'] == 'basal_clump':
            base = (reach*math.cos(az), reach*math.sin(az), -.06*m)
            connector = axis(root, (0., 0., -.06*m), base, radius*.5, 'rhizome')
            top = (base[0], base[1], .015+p['axis_height_m']*elongation*(.35+.4*progress)*(1-.12*c))
            host = axis(connector, base, top, radius, 'persistent_axis')
        else:
            base = tuple(v*.62 for v in primary_top)
            # Junction is explicit: split the main axis so forks start at a
            # real host socket rather than at an unrelated trunk endpoint.
            if len(crowns) == 1:
                axis_length -= math.dist(base, primary_top)
                paths[str(trunk)] = [[0., 0., 0.], list(base)]
                placements[trunk][2:5] = [round(v, 4) for v in base]
                leader = axis(trunk, base, primary_top, radius, 'persistent_axis')
                crowns[0] = (leader, primary_top, 1.)
            top = (reach*math.cos(az), reach*math.sin(az), primary_top[2]*(.8+.15*progress))
            host = axis(trunk, base, top, radius, 'persistent_axis', 'branch_section')
        crowns.append((host, top, progress))

    living = dead = flowers = fruits = 0
    for c, (host, center, progress) in enumerate(crowns):
        count = max(1, round(p['leaves_per_crown'] * (.15+.85*math.sqrt(m*progress))))
        leaf_scale = max(.03, math.sqrt(m*progress))
        length = sim.blueprint.module('leaf').length_m * leaf_scale
        skirt_count = round(p['dead_leaves_per_crown']*elongation*progress) if p['skirt_fraction'] > 0 else 0
        for j in range(count + skirt_count):
            retained = j >= count
            rank = (j-count)/max(1, p['dead_leaves_per_crown']-1) if retained else j/max(1, count-1)
            az = phase+c*.73+j*2.399963229728653
            elevation = -.7-rank*.65 if retained else 1.48-rank*1.65
            base = (center[0]+math.cos(az)*p['axis_radius_m']*.65*leaf_scale,
                    center[1]+math.sin(az)*p['axis_radius_m']*.65*leaf_scale,
                    center[2]-.08*leaf_scale*rank)
            blade_length = length*(p['skirt_fraction'] if retained else .75+.25*math.sin(rank*math.pi))
            bend = p['leaf_bend'] * (.2+.8*rank)
            # Integrate tangent rotations to preserve the metric blade length.
            curve = rosette_blade_curve(base,az,elevation,bend,blade_length)
            idx = sim._add(placements, 'leaf', host, *base, math.degrees(az),
                           leaf_scale, 1, paths, curve)
            sim._placement_orientation_hints[str(idx)] = {
                'terminal_blade': True, 'retained_dead_leaf': retained,
                'blade_width_m': p['leaf_width_m']*leaf_scale,
                'min_render_lod': 0, 'forward': [math.cos(az)*math.cos(elevation),
                                               math.sin(az)*math.cos(elevation), math.sin(elevation)]}
            if retained:
                dead += 1
            else:
                area = blade_length*p['leaf_width_m']*leaf_scale*.65
                cid = sim._add_leaf_cluster(clusters, idx, *base, 1, area, 0)
                clusters[-1].update(explicit_samples=True, sample_placement_indices=[idx])
                attachments.append({'stem_placement_index': host, 'leaf_placement_index': idx,
                                    'socket': 'terminal_rosette', 'position_m': list(base), 'cluster_id': cid})
                living += 1

        fertile = (m >= .95 and progress >= .8 and
                    sim.blueprint.growth.get('reproductive_mode') in {'sexual', 'both', 'apomictic'} and
                    bool(sim.blueprint.growth.get('reproductive_profile')))
        fruit = life_state.get('fruiting_factor', 0.) > .05
        bloom = life_state.get('reproductive_factor', 0.) > .05
        if not fertile or not (fruit or bloom):
            continue
        stalk_top = (center[0], center[1], center[2]+p['peduncle_length_m'])
        stalk = axis(host, center, stalk_top, p['peduncle_radius_m'], 'peduncle')
        # Each lateral originates at a distinct node on the panicle axis.
        parent = stalk
        start = stalk_top
        for b in range(p['panicle_branches']):
            t = (b+.5)/p['panicle_branches']
            node = (start[0], start[1], stalk_top[2]+p['panicle_length_m']*t)
            parent = axis(parent, start, node, p['peduncle_radius_m']*.55, 'panicle_axis')
            az = phase+b*2.399963229728653
            reach = p['panicle_width_m']*.5*(1-t)**.6
            tip = (node[0]+math.cos(az)*reach, node[1]+math.sin(az)*reach,
                   node[2]+reach*.4)
            lateral = axis(parent, node, tip, p['peduncle_radius_m']*.2, 'panicle_lateral', 'branch_section')
            for f in range(p['flowers_per_branch']):
                u = (f+1)/p['flowers_per_branch']
                pos = tuple(node[a]+(tip[a]-node[a])*u for a in range(3))
                end = (pos[0], pos[1], pos[2]-.025 if not fruit else pos[2]+.01)
                pedicel = axis(lateral, pos, end, .0015, 'pedicel', 'branch_section')
                forward = (0., 0., 1. if fruit else -1.)
                idx = sim._add(placements, 'fruit' if fruit else 'flower', pedicel,
                               *end, 0 if fruit else 180, 1., 2)
                sim._placement_orientation_hints[str(idx)] = sim._orientation_frame(forward)
                attachments.append({'placement_index': idx, 'host_placement_index': pedicel,
                                    'socket': 'fruit_base' if fruit else 'flower_base', 'position_m': list(end)})
                flowers += int(not fruit)
                fruits += int(fruit)
            start = node
        axis(parent, start, (start[0], start[1], stalk_top[2]+p['panicle_length_m']),
             p['peduncle_radius_m']*.3, 'panicle_axis')
    return {'terminal_rosette_version': TERMINAL_ROSETTE_VERSION,
            'terminal_crown_count': len(crowns), 'terminal_crowns_m': [list(x[1]) for x in crowns],
            'estimated_leaf_count': living, 'retained_dead_leaf_count': dead,
            'terminal_rosette_flower_count': flowers, 'terminal_rosette_fruit_count': fruits,
            'leaf_area_m2': round(sum(x['leaf_area_m2'] for x in clusters), 6),
            'structural_axis_length_m': round(axis_length, 6),
            'terminal_rosette_model_status': p['status'],
            'clonal_recruitment_status': 'representative_axes_only_not_population_recruitment'}


def draw_terminal_blade(screen, asset, points, width, retained):
    from simulations.species.tufted_sedges import draw_blade_asset
    from simulations.species.graminoid_visuals import draw_blade
    if not retained and draw_blade_asset(screen, asset, points, width*.5):
        return
    draw_blade(screen, points, width*.5, (137, 113, 68) if retained else (117, 143, 70))
