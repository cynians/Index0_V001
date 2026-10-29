"""Bounded cane cohorts from a persistent crown, on a qualitative growth clock.

Replacement intervals are display calibration, not measured cane longevity.
Calendar dormancy pauses that clock; leaves and hips use shared phenology.
"""
import math
import random

RENEWING_CANE_VERSION = 1


def renewing_cane_profile(value):
    if not isinstance(value, dict) or value.get('form') != 'renewing_canes':
        return None
    ranges = {'renewal_interval_model_days': (5., 365.),
              'branching_age_model_days': (1., 730.),
              'extension_model_days': (5., 730.),
              'old_cane_fraction': (.55, .95), 'basal_radius_m': (0., .6),
              'cane_radius_m': (.001, .04), 'arch_ratio': (.05, .9),
              'lateral_length_ratio': (.03, .4), 'leaf_width_ratio': (.15, 1.2),
              'cluster_spread_m': (.005, .06)}
    counts = {'max_canes': (2, 12), 'nodes_per_cane': (6, 28),
              'laterals_per_cane': (1, 14), 'nodes_per_lateral': (2, 10),
              'flowers_per_cluster': (1, 5)}
    for key, (lo, hi) in {**ranges, **counts}.items():
        x = value.get(key)
        if (isinstance(x, bool) or not isinstance(x, (int, float)) or
                not math.isfinite(x) or not lo <= x <= hi or
                (key in counts and not isinstance(x, int))):
            return None
    lifespan = value['max_canes']*value['renewal_interval_model_days']
    if max(value['branching_age_model_days'], value['extension_model_days']) >= lifespan*value['old_cane_fraction']:
        return None
    return {'form': 'renewing_canes', 'version': RENEWING_CANE_VERSION,
            **{k: float(value[k]) for k in ranges}, **{k: value[k] for k in counts},
            'status': str(value.get('status') or 'qualitative_cane_cohort_recipe')}


def cane_growth_clock(age, reproductive):
    """Accumulate model time only between authored leaf-out and leaf-fall.

    Missing phenology is neutral continuous growth, not inferred dormancy.
    """
    age = max(0., age)
    if not reproductive or 'leaf_out_start' not in reproductive:
        return age, 'continuous_unresolved_season'
    cycle = reproductive['cycle_days']
    start, end = reproductive['leaf_out_start']*cycle, reproductive['leaf_fall_end']*cycle
    years, remainder = divmod(age, cycle)
    return years*(end-start)+min(end-start, max(0., remainder-start)), 'authored_leaf_window'


def grow_renewing_canes(sim, placements, maturity, lod, age_days, state, paths, clusters, attachments):
    g = sim.blueprint.growth; p = g['renewing_cane_profile']
    clock, clock_source = cane_growth_clock(age_days, g.get('reproductive_profile'))
    interval = p['renewal_interval_model_days']; lifespan = interval*p['max_canes']
    latest = math.floor(clock/interval)
    crown = sim._growth_origin(placements)
    # A rooted crown persists; each bounded slot receives a new serial when
    # its previous cane retires. No generated topology is stored in ontology.
    cohorts = []; axis_length = 0.; leaf_ordinal = 0
    flower_count = fruit_count = 0
    leaf_factor = max(0., min(1., state.get('leaf_factor', 1.)))
    height = g['shrub_height_m']*max(.02, min(1., maturity))
    phase = random.Random(sim.seed ^ 0xCA9E).random()*math.tau
    fertile = []

    def axis(parent, start, end, radius, role, serial, age, order):
        nonlocal axis_length
        kind = 'stem_section' if role == 'cane' else 'branch_section'
        idx = sim._add(placements, kind, parent, *end, 0., radius, order,
                       paths, [start, end])
        sim._placement_orientation_hints[str(idx)] = {
            **sim._orientation_frame(tuple(end[a]-start[a] for a in range(3))),
            'cane_axis_role': role, 'cane_id': f'cane:{serial}',
            'cane_age_model_days': round(age, 6), 'cane_age_fraction': age/lifespan}
        attachments.append({'placement_index': idx, 'host_placement_index': parent,
                            'socket': role+'_base', 'position_m': list(start), 'cane_id': f'cane:{serial}'})
        axis_length += math.dist(start, end)
        return idx

    def leaf(host, pos, az, serial, age, order, scale=1.):
        nonlocal leaf_ordinal
        leaf_ordinal += 1
        if (leaf_ordinal*.61803398875+.1) % 1 >= leaf_factor:
            return
        number = max(1, min(3, int(g.get('leaves_per_node', 1))))
        length = sim.blueprint.module('leaf').length_m*scale
        area = length*length*p['leaf_width_ratio']*.5
        cid = sim._add_leaf_cluster(clusters, host, *pos, number, area*number, order)
        cluster = clusters[-1]; cluster.update(explicit_samples=True, sample_placement_indices=[])
        # Conservative bounds remain canonical when LOD removes leaf samples.
        cluster['organ_bounds_m'] = [pos[a]+sign*length*1.15 for a in range(3) for sign in (-1, 1)]
        if lod == 0 or (lod == 1 and leaf_ordinal % 2):
            return
        for j in range(number):
            a = az+(math.pi if leaf_ordinal % 2 else 0)+j*math.tau/number
            idx = sim._add(placements, 'leaf', host, *pos, math.degrees(a), scale, order+1)
            sim._placement_orientation_hints[str(idx)] = {
                **sim._orientation_frame((math.cos(a), math.sin(a), .25)),
                'cane_id': f'cane:{serial}', 'cane_age_model_days': age}
            cluster['sample_placement_indices'].append(idx)
            attachments.append({'stem_placement_index': host, 'leaf_placement_index': idx,
                                'cluster_id': cid, 'socket': 'leaf_base', 'position_m': list(pos)})

    for serial in range(max(0, latest-p['max_canes']+1), latest+1):
        age = clock-serial*interval
        if age <= .001:
            continue
        rng = random.Random(sim.seed ^ ((serial+1)*1000003))
        slot = serial % p['max_canes']
        slot_phase = random.Random(sim.seed ^ ((slot+1)*9176)).uniform(-.15, .15)
        az = phase+slot*2.3999632297+slot_phase
        extension = min(1., age/p['extension_model_days'])
        h = height*extension*rng.uniform(.76, 1.)
        old = age/lifespan >= p['old_cane_fraction']
        young = age < p['branching_age_model_days']
        base = (math.cos(az)*p['basal_radius_m'], math.sin(az)*p['basal_radius_m'], 0.)
        cohorts.append({'cane_id': f'cane:{serial}', 'slot': slot, 'birth_clock_days': serial*interval,
                        'age_model_days': round(age, 6), 'stage': 'young' if young else 'old' if old else 'branched',
                        'base_m': list(base)})
        parent = crown; start = (0., 0., 0.); hosts = []
        node_count = max(2, round(p['nodes_per_cane']*max(.12, extension)))
        for j in range(node_count):
            t = (j+1)/node_count
            reach = h*p['arch_ratio']*(.25 if young else 1.)*t*t
            end = (base[0]+math.cos(az)*reach, base[1]+math.sin(az)*reach,
                   h*(t-(.3 if old else .12)*t**3))
            radius = p['cane_radius_m']*max(.18, math.sqrt(extension))*(1-.65*t)
            parent = axis(parent, start, end, radius, 'cane', serial, age, 0)
            hosts.append(parent); start = end
            if j > 0 and not old:
                leaf(parent, end, az+1.2, serial, age, 0, .85+.15*extension)
        if young:
            continue
        laterals = max(1, round(p['laterals_per_cane']*(.45+.55*g['fine_twig_density'])))
        for k in range(laterals):
            host = hosts[min(len(hosts)-1, round((len(hosts)-1)*(.2+.7*(k+.5)/laterals)))]
            origin = placements[host][2:5]; start = origin
            a = az+k*2.3999632297+rng.uniform(-.2, .2)
            length = height*p['lateral_length_ratio']*rng.uniform(.72, 1.1)
            rise = {'orthotropic': .85, 'plagiotropic': .12, 'mixed': .45, 'pendent': -.3}.get(g['lateral_axis_orientation'], .45)
            lateral_hosts = []
            for j in range(p['nodes_per_lateral']):
                t = (j+1)/p['nodes_per_lateral']
                end = (origin[0]+math.cos(a)*length*t, origin[1]+math.sin(a)*length*t,
                       origin[2]+length*(rise*t-g['branch_droop']*t*t*.5))
                host = axis(host, start, end, p['cane_radius_m']*.23*(1-.6*t), 'lateral', serial, age, 1)
                lateral_hosts.append(host)
                if not old or (k+j) % 3 == 0:
                    leaf(host, end, a+1.2, serial, age, 1)
                start = end
            # Fewer productive tips on old canes. Never flower on young cane tips.
            if not old or k % 3 == 0:
                fertile.append((host, start, a, serial, age, k))
            # Bounded fine side shoots fill the established framework; young
            # replacement canes have already returned before this branch.
            for twig in range(round(2*g['fine_twig_density'])):
                th = lateral_hosts[min(len(lateral_hosts)-1, 1+twig*2)]
                origin = placements[th][2:5]; start = origin
                ta = a+(-1 if twig % 2 else 1)*.95
                tl = length*.6
                for j in range(3):
                    t = (j+1)/3
                    end = (origin[0]+math.cos(ta)*tl*t, origin[1]+math.sin(ta)*tl*t,
                           origin[2]+tl*(.45*t-.15*t*t))
                    th = axis(th, start, end, p['cane_radius_m']*.12*(1-.6*t), 'twig', serial, age, 2)
                    if not old or (k+j) % 3 == 0:
                        leaf(th, end, ta+1.2, serial, age, 2)
                    start = end
                if not old or k % 3 == 0:
                    fertile.append((th, start, ta, serial, age, k))

    sexual = g.get('reproductive_mode') in {'sexual', 'both', 'apomictic'}
    if sexual and g.get('flowering_position') in {'terminal', 'mixed'}:
        for ordinal, (host, pos, az, serial, age, k) in enumerate(fertile):
            score = (ordinal*.61803398875+.17) % 1
            kind = ('flower' if score < state.get('reproductive_factor', 0.)*.8 else
                    'fruit' if score < state.get('fruiting_factor', 0.)*.8 else None)
            if kind is None:
                continue
            for j in range(p['flowers_per_cluster']):
                a = az+j*2.3999632297
                reach = p['cluster_spread_m']*(.35+j/max(1, p['flowers_per_cluster']-1))
                tip = (pos[0]+math.cos(a)*reach, pos[1]+math.sin(a)*reach, pos[2]+.018+.008*(j%2))
                stalk = axis(host, pos, tip, .0006, 'pedicel', serial, age, 2)
                if lod >= 1:
                    idx = sim._add(placements, kind, stalk, *tip, 0., 1., 3)
                    sim._placement_orientation_hints[str(idx)] = {
                        **sim._orientation_frame((0., 0., 1.)), 'cane_id': f'cane:{serial}',
                        'cane_age_model_days': age, 'reproductive_socket': 'lateral_cluster_tip'}
                    attachments.append({'placement_index': idx, 'host_placement_index': stalk,
                                        'socket': kind+'_base', 'position_m': list(tip)})
                flower_count += kind == 'flower'; fruit_count += kind == 'fruit'
    return {'renewing_cane_version': RENEWING_CANE_VERSION,
            'shrub_cane_count': len(cohorts), 'cane_cohorts': cohorts,
            'young_cane_count': sum(c['stage'] == 'young' for c in cohorts),
            'old_cane_count': sum(c['stage'] == 'old' for c in cohorts),
            'retired_cane_count': max(0, latest-p['max_canes']+1),
            'shrub_flower_count': flower_count, 'shrub_fruit_count': fruit_count,
            'cane_growth_clock_days': round(clock, 6), 'cane_growth_clock_source': clock_source,
            'structural_axis_length_m': round(axis_length, 6),
            'cane_timing_status': p['status']}
