"""One woody cushion with short leafy axes and persistent spinous rachises.

Dimensions and bounded display counts are authored fits, not production or
population estimates. Rachises are non-photosynthetic structural axes; leaf
cohorts account only for their attached living leaflets.
"""
import math
import random

RANGES = {'crown_radius_m': (.015, .5), 'stem_radius_m': (.0003, .015),
          'rachis_radius_m': (.0001, .002), 'retained_rachis_fraction': (0., 1.),
          'flowering_fraction': (0., 1.)}
COUNTS = {'shoot_count': (3, 48), 'nodes_per_shoot': (2, 8),
          'leaves_per_node': (1, 5), 'flowers_per_tip': (1, 2)}


def cushion_profile(value):
    if not isinstance(value, dict) or value.get('form') != 'cushion_subshrub':
        return None
    for key, (lo, hi) in {**RANGES, **COUNTS}.items():
        x = value.get(key)
        if (isinstance(x, bool) or not isinstance(x, (int, float))
                or not math.isfinite(x) or not lo <= x <= hi
                or key in COUNTS and not isinstance(x, int)):
            return None
    return {'form': 'cushion_subshrub', 'version': 1,
            **{k: float(value[k]) for k in RANGES},
            **{k: value[k] for k in COUNTS},
            'status': str(value.get('status') or 'qualitative_cushion_display_fit')}


def grow_cushion(sim, placements, maturity, state, paths, clusters, attachments):
    g = sim.blueprint.growth; p = g['cushion_profile']
    m = max(0., min(1., maturity)); root = sim._growth_origin(placements)
    if m <= 0:
        return {'cushion_version': 1, 'cushion_shoot_count': 0,
                'persistent_rachis_count': 0, 'cushion_flower_count': 0,
                'cushion_pod_count': 0, 'structural_axis_length_m': 0.,
                'estimated_leaf_count': 0, 'leaf_area_m2': 0.}
    leaf_module = sim.blueprint.module('leaf')
    # Crown dimensions include projecting leaves, not just their supporting
    # wood. Reserve a bounded margin for the typical blade projection.
    height = max(.005, g['cushion_height_m'] - leaf_module.length_m * .45) * m
    radius = max(.005, p['crown_radius_m'] - leaf_module.length_m * .6) * math.sqrt(m)
    count = max(1, round(p['shoot_count'] * m ** .65))
    rng = random.Random(sim.seed ^ 30941)
    phase = rng.uniform(0., math.tau)
    leafy = max(0., min(1., state.get('leaf_factor', 1.)))
    length = 0.; rachises = 0; flowers = fruits = 0
    sexual = g.get('reproductive_mode') in {'sexual', 'both', 'apomictic'}
    leaflet_area = g['leaflet_count'] * g['leaflet_length_m'] * g['leaflet_width_m'] * .58

    def axis(parent, a, b, role, thickness):
        nonlocal length
        kind = 'stem_section' if role == 'woody_cushion_axis' else 'branch_section'
        i = sim._add(placements, kind, parent, *b, 0., thickness, 0, paths, [a, b])
        sim._placement_orientation_hints[str(i)] = {
            'axis_role': role, 'structural_socket_m': list(a), 'min_render_lod': 0}
        attachments.append({'placement_index': i, 'host_placement_index': parent,
                            'socket': role, 'position_m': list(a)})
        length += math.dist(a, b)
        return i

    for s in range(count):
        az = phase + s * 2.39996323
        rank = math.sqrt((s + .5) / count)
        # Radial short axes collectively describe a hemispherical cushion,
        # rather than independent upright stems or disconnected clonal ramets.
        tip = (radius * rank * math.cos(az), radius * rank * math.sin(az),
               height * (.18 + .82 * math.sqrt(max(0., 1. - rank * rank))))
        previous = (0., 0., 0.); host = root
        for j in range(p['nodes_per_shoot']):
            t = (j + 1) / p['nodes_per_shoot']
            pos = (tip[0] * t, tip[1] * t, tip[2] * (t ** .75))
            host = axis(host, previous, pos, 'woody_cushion_axis',
                        p['stem_radius_m'] * math.sqrt(m) * (1. - .65 * t))
            previous = pos
            leaf_slots = (p['leaves_per_node'] * 2 if j == p['nodes_per_shoot'] - 1
                          else max(1, p['leaves_per_node'] // 2))
            for k in range(leaf_slots):
                a = az + k * 2.39996323 + j * 1.2
                elevation = .25 + .9 * (1. - rank) + rng.uniform(-.13, .13)
                forward = (math.cos(a) * math.cos(elevation),
                           math.sin(a) * math.cos(elevation), math.sin(elevation))
                scale = math.sqrt(m) * rng.uniform(.65, 1.)
                end = tuple(pos[q] + forward[q] * leaf_module.length_m * scale for q in range(3))
                # The rachis survives leaflet loss; no green area is assigned
                # to a spine, and winter never deletes the woody framework.
                axis(host, pos, end, 'persistent_leaf_rachis', p['rachis_radius_m'] * scale)
                rachises += 1
                if (s * .37 + j * .23 + k * .61) % 1. < leafy:
                    i = sim._add(placements, 'leaf', host, *pos, 0., scale, 0)
                    normal = (-math.cos(a) * math.sin(elevation),
                              -math.sin(a) * math.sin(elevation), math.cos(elevation))
                    frame = {**sim._orientation_frame(forward), 'normal': list(normal),
                             'seasonal_planar_blade': True, 'min_render_lod': 0}
                    sim._placement_orientation_hints[str(i)] = frame
                    sim._add_leaf_cluster(clusters, i, *pos, 1, leaflet_area * scale ** 2, 0)
                    clusters[-1].update(explicit_samples=True, sample_placement_indices=[i])
                    attachments.append({'leaf_placement_index': i, 'stem_placement_index': host,
                                        'socket': 'compound_leaf_base', 'position_m': list(pos)})
                if (s * .31 + j * .57 + k * .19) % 1. < p['retained_rachis_fraction']:
                    old = (a + .5, max(.05, elevation - .35))
                    old_end = (pos[0] + math.cos(old[0]) * math.cos(old[1]) * leaf_module.length_m * scale,
                               pos[1] + math.sin(old[0]) * math.cos(old[1]) * leaf_module.length_m * scale,
                               pos[2] + math.sin(old[1]) * leaf_module.length_m * scale)
                    axis(host, pos, old_end, 'retained_leaf_rachis', p['rachis_radius_m'] * scale)
                    rachises += 1
        for k in range(p['flowers_per_tip']):
            threshold = (s * .61803399 + k * .37) % 1.
            if not sexual or threshold >= p['flowering_fraction']: continue
            # Distinct sites can be flowering and fruiting concurrently;
            # a single site cannot display both flower and pod at once.
            fruit = threshold < state.get('fruiting_factor', 0.) * p['flowering_fraction']
            flower = threshold < state.get('reproductive_factor', 0.) * p['flowering_fraction']
            if not fruit and not flower: continue
            kind = 'fruit' if fruit else 'flower'
            a = az + k * 2.1
            end = (tip[0] + math.cos(a) * .006 * m,
                   tip[1] + math.sin(a) * .006 * m, tip[2] + .006 * m)
            stalk = axis(host, tip, end, 'short_flower_stalk', p['rachis_radius_m'])
            i = sim._add(placements, kind, stalk, *end, 0., math.sqrt(m), 0)
            sim._placement_orientation_hints[str(i)] = {
                **sim._orientation_frame((math.cos(a)*.3, math.sin(a)*.3, 1.)),
                'min_render_lod': 0}
            attachments.append({'placement_index': i, 'host_placement_index': stalk,
                                'socket': kind + '_base', 'position_m': list(end)})
            flowers += kind == 'flower'; fruits += kind == 'fruit'
    return {'cushion_version': 1, 'cushion_shoot_count': count,
            'persistent_rachis_count': rachises, 'cushion_flower_count': flowers,
            'cushion_pod_count': fruits, 'structural_axis_length_m': length,
            'estimated_leaf_count': len(clusters),
            'leaf_area_m2': sum(c['leaf_area_m2'] for c in clusters)}
