"""Surface connecting axes with distinct upright, optionally forked shoots.

One microphyll is one leaf. Counts, growth fractions and spacing are bounded
visual recipes, not measured annual production or a demographic clone model.
"""
import math
import random

CREEPING_UPRIGHT_VERSION = 1


def creeping_upright_profile(value):
    if not isinstance(value, dict) or value.get('form') != 'creeping_uprights':
        return None
    ranges = {'runner_length_m': (.02, 3.), 'runner_radius_m': (.0003, .015),
              'upright_height_m': (.015, 1.5), 'upright_radius_m': (.0003, .015),
              'leaf_width_m': (.0002, .008), 'runner_leaf_fraction': (0., 1.),
              'fork_spread': (0., 1.), 'constriction_depth': (0., .9),
              'strobilus_length_m': (.003, .08), 'strobilus_width_m': (.001, .015),
              'fertile_fraction': (0., 1.)}
    counts = {'runner_count': (1, 4), 'uprights_per_runner': (1, 8),
              'leaves_per_upright': (12, 256), 'fork_levels': (0, 2),
              'growth_sections': (1, 6)}
    for key, (lo, hi) in {**ranges, **counts}.items():
        n = value.get(key)
        if (isinstance(n, bool) or not isinstance(n, (int, float)) or
                not math.isfinite(n) or not lo <= n <= hi or
                (key in counts and not isinstance(n, int))):
            return None
    budget = value['runner_count']*value['uprights_per_runner']*(2**(value['fork_levels']+1)-1)*value['leaves_per_upright']
    if budget > 8192:
        return None
    return {'form': 'creeping_uprights', 'version': CREEPING_UPRIGHT_VERSION,
            **{k: float(value[k]) for k in ranges}, **{k: value[k] for k in counts},
            'status': str(value.get('status') or 'qualitative_display_recipe')}


def grow_creeping_uprights(sim, placements, maturity, paths, attachments, clusters, contacts):
    g = sim.blueprint.growth
    p = g['creeping_upright_profile']
    m = max(0., min(1., maturity))
    root = sim._add(placements, 'root', -1, 0, 0, 0, 0, 1, 0)
    rng = random.Random(sim.seed ^ 0xC7EE)
    phase = rng.random()*math.tau
    axis_length = 0.
    live_leaves = uprights = cones = forks = 0
    tips = []

    def axis(parent, start, end, radius, role):
        nonlocal axis_length
        idx = sim._add(placements, 'stem_section' if role == 'upright' else 'branch_section',
                       parent, *end, 0, radius, 0, paths, [start, end])
        sim._placement_orientation_hints[str(idx)] = {'creeping_axis': role}
        attachments.append({'placement_index': idx, 'host_placement_index': parent,
                            'socket': role+'_base', 'position_m': list(start)})
        axis_length += math.dist(start, end)
        return idx

    def foliage(host, start, end, count, size, offset, role, section=0):
        nonlocal live_leaves
        dx, dy, dz = (end[a]-start[a] for a in range(3))
        length = max(1e-9, math.sqrt(dx*dx+dy*dy+dz*dz))
        tangent = (dx/length, dy/length, dz/length)
        # A local radial frame also works along horizontal runner segments.
        u = (-tangent[1], tangent[0], 0.)
        norm = math.sqrt(sum(x*x for x in u))
        u = (1., 0., 0.) if norm < .01 else tuple(x/norm for x in u)
        v = (tangent[1]*u[2]-tangent[2]*u[1],
             tangent[2]*u[0]-tangent[0]*u[2], tangent[0]*u[1]-tangent[1]*u[0])
        for j in range(count):
            t = (j+.5)/count
            theta = offset+j*2.399963229728653
            # Reduce leaves near the recurrent growth boundary, keeping the
            # constriction visible without asserting a calendar age.
            neck = 1-p['constriction_depth'] if role == 'upright' and t < .10 and section > 0 else 1.
            leaf_length = sim.blueprint.module('leaf').length_m*size*neck
            radial = tuple(u[a]*math.cos(theta)+v[a]*math.sin(theta) for a in range(3))
            base = tuple(start[a]+(end[a]-start[a])*t+radial[a]*p['upright_radius_m']*size*.8 for a in range(3))
            direction = tuple(radial[a]*.96-tangent[a]*.28 for a in range(3))
            tip = tuple(base[a]+direction[a]*leaf_length for a in range(3))
            idx = sim._add(placements, 'leaf', host, *base, math.degrees(theta), size*neck, 1, paths, [base, tip])
            sim._placement_orientation_hints[str(idx)] = {
                **sim._orientation_frame(direction), 'microphyll': True,
                'blade_width_m': p['leaf_width_m']*size*neck}
            area = leaf_length*p['leaf_width_m']*size*neck*.55
            cid = sim._add_leaf_cluster(clusters, idx, *base, 1, area, 0)
            clusters[-1].update(explicit_samples=True, sample_placement_indices=[idx])
            attachments.append({'stem_placement_index': host, 'leaf_placement_index': idx,
                                'socket': 'microphyll_base', 'position_m': list(base), 'cluster_id': cid})
            live_leaves += 1

    def shoot(parent, base, height, size, azimuth, level=0):
        nonlocal forks
        current = parent
        start = base
        sections = p['growth_sections'] if level == 0 else 1
        for section in range(sections):
            t = (section+1)/sections
            drift = height*.08*t*t
            end = (base[0]+math.cos(azimuth)*drift, base[1]+math.sin(azimuth)*drift, base[2]+height*t)
            radius = p['upright_radius_m']*size
            current = axis(current, start, end, radius, 'upright')
            foliage(current, start, end, p['leaves_per_upright']//sections + int(section < p['leaves_per_upright']%sections),
                    size, phase+section*.3+level, 'upright', section)
            start = end
        if level < p['fork_levels']:
            forks += 1
            for side in (-1, 1):
                a = azimuth+side*1.1
                fork_tip = (end[0]+math.cos(a)*height*p['fork_spread'],
                            end[1]+math.sin(a)*height*p['fork_spread'], end[2]+height*.12)
                fork = axis(current, end, fork_tip, p['upright_radius_m']*size*.7, 'fork')
                shoot(fork, fork_tip, height*.55, size*.8, a, level+1)
        else:
            tips.append((current, end, size))

    for r in range(p['runner_count']):
        a = phase+r*2.65+rng.uniform(-.2, .2)
        parent = root
        start = (0., 0., .002)
        # Fix socket locations on the adult axis. New sockets emerge behind
        # its advancing tip instead of sliding existing shoots across ground.
        length = p['runner_length_m']*(1-.12*r)
        for j in range(p['uprights_per_runner']):
            # Paired sockets separated by larger gaps make small groups along
            # a runner. This is a visual spacing recipe, not measured density.
            t = (j+1+(.22 if j%2 == 0 else -.22))/p['uprights_per_runner']
            t = min(1., t)
            birth = t*.78
            if m <= birth:
                break
            end = (math.cos(a)*length*t, math.sin(a)*length*t+math.sin(t*math.pi)*length*.09, .002)
            runner = axis(parent, start, end, p['runner_radius_m'], 'runner')
            contact = {'parent_index': runner, 'position': [end[0], end[1], 0.]}
            contacts.append(contact)
            progress = (m-birth)/(1-birth)
            size = max(.03, math.sqrt(progress))
            height = p['upright_height_m']*progress*(.8+.2*rng.random())
            foliage(runner, start, end, round(p['leaves_per_upright']*p['runner_leaf_fraction']/p['uprights_per_runner']),
                    size*.75, phase+j, 'runner')
            shoot(runner, end, height, size, a+j*.5)
            uprights += 1
            parent, start = runner, end

    if m >= .95 and g.get('reproductive_structure') == 'strobilus' and g.get('reproductive_mode') in {'sexual', 'both'}:
        for j, (host, pos, size) in enumerate(tips):
            if (j+.5)/max(1, len(tips)) > p['fertile_fraction']:
                continue
            idx = sim._add(placements, 'strobilus', host, *pos, 0, size, 1)
            sim._placement_orientation_hints[str(idx)] = {
                **sim._orientation_frame((0., 0., 1.)), 'spore_cone': True,
                'organ_width_m': p['strobilus_width_m']*size}
            attachments.append({'placement_index': idx, 'host_placement_index': host,
                                'socket': 'sessile_strobilus_base', 'position_m': list(pos)})
            cones += 1
    return {'creeping_upright_version': CREEPING_UPRIGHT_VERSION,
            'upright_shoot_count': uprights, 'upright_fork_count': forks,
            'strobilus_count': cones, 'estimated_leaf_count': live_leaves,
            'leaf_area_m2': round(sum(c['leaf_area_m2'] for c in clusters), 6),
            'structural_axis_length_m': round(axis_length, 6),
            'rooting_contact_count': len(contacts), 'creeping_upright_status': p['status'],
            'spore_model_status': 'display_strobili_only; no_spore_yield_or_gametophyte_model'}


def draw_microphyll(screen, asset, points, width):
    from simulations.species.tufted_sedges import draw_blade_asset
    from simulations.species.graminoid_visuals import draw_blade
    if not draw_blade_asset(screen, asset, points, width*.5):
        draw_blade(screen, points, width*.5, (60, 116, 46))
