"""Opt-in leafy sympodial herbs with ascending, branched terminal displays.

The recipe and developmental clock are qualitative visual controls. Metres,
organ sockets and a canonical graph are retained at every display LOD.
"""
import math
import random

SYMPODIAL_HERB_VERSION = 1
PROFILE_RANGES = {
    'main_node_count': (8, 32), 'basal_leaf_count': (0, 12),
    'branch_start_fraction': (.35, .9), 'lateral_count': (0, 10),
    'lateral_length_ratio': (0., .4), 'heads_per_lateral': (1, 8),
    'stem_radius_m': (.0004, .008), 'leaf_width_m': (.003, .08),
    'internode_variation': (0., .5), 'axis_deflection': (0., .15),
    'branch_maturity_start': (0., .9),
}
COUNT_FIELDS = {'main_node_count', 'basal_leaf_count', 'lateral_count', 'heads_per_lateral'}


def sympodial_herb_profile(value):
    if not isinstance(value, dict) or value.get('form') != 'sympodial_herb':
        return None
    for key, (lo, hi) in PROFILE_RANGES.items():
        n = value.get(key)
        if (isinstance(n, bool) or not isinstance(n, (int, float))
                or not math.isfinite(n) or not lo <= n <= hi
                or (key in COUNT_FIELDS and int(n) != n)):
            return None
    return {'form': value['form'], 'version': SYMPODIAL_HERB_VERSION,
            **{k: value[k] for k in PROFILE_RANGES},
            'status': str(value.get('status') or 'qualitative_display_recipe')}


def _bounded(value, default, lo, hi):
    try:
        n = float(value)
    except (ValueError, TypeError):
        n = default
    return min(hi, max(lo, n if math.isfinite(n) else default))


def build_sympodial_herb(growth, maturity, flowering, fruiting, seed):
    from simulations.species.leaf_development import forb_leaf_direction, leaf_attachment_direction
    p = growth['sympodial_herb_profile']
    maturity = _bounded(maturity, 0., 0., 1.)
    flowering = _bounded(flowering, 0., 0., 1.)
    fruiting = _bounded(fruiting, 0., 0., 1.)
    height = _bounded(growth.get('max_height_m'), 1., .05, 20.)
    nodes, axis_length, area = [], 0., 0.
    rng = random.Random(f'{seed}:sympodial_herb')
    phase = rng.uniform(0., 360.)
    leaf_length = _bounded(growth.get('leaf_length_m'), .08, .002, 1.)
    count = int(p['main_node_count'])
    visible_count = max(1, math.ceil(count * maturity)) if maturity else 0
    weights = [rng.uniform(1-p['internode_variation'], 1+p['internode_variation']) for _ in range(count)]
    total = sum(weights)
    fractions = [sum(weights[:i+1])/total for i in range(count)]
    active_height = height * maturity * .93

    def add(kind, parent, position, angle=0., scale=1., role='', forward=None):
        nonlocal axis_length
        origin = nodes[parent]['position'] if parent >= 0 else (0., 0., 0.)
        path = None
        if kind in {'stem_section', 'branch_section'}:
            # Bend is bounded by segment length; no clamped flat upper arms.
            length = math.dist(origin, position)
            axis_length += length
            bend = length * .025
            path = [(origin[0]+(position[0]-origin[0])*f + math.cos(math.radians(angle+90))*bend*math.sin(math.pi*f),
                     origin[1]+(position[1]-origin[1])*f + math.sin(math.radians(angle+90))*bend*math.sin(math.pi*f),
                     origin[2]+(position[2]-origin[2])*f) for f in (.33, .66, 1.)]
        nodes.append({'kind': kind, 'parent': parent, 'position': position,
                      'angle': angle, 'scale': scale, 'path': path, 'forward': forward,
                      'role': role, 'min_lod': 0 if kind == 'stem_section' else 1})
        return len(nodes)-1

    def leaf(parent, position, rank, angle, expansion=1., lateral=False, basal=False):
        nonlocal area
        adult = (1.35-.98*rank**1.15) * (.6 if lateral else 1.)
        scale = adult * (.15+.85*expansion)
        direction = forb_leaf_direction(angle, rank, math.sin(angle)*.5)
        if basal:
            rad = math.radians(angle)
            direction = [math.cos(rad)*.98, math.sin(rad)*.98, .2]
        elif growth.get('leaf_attachment_angle') is not None:
            origin = nodes[parent]['position']
            ancestor = nodes[parent]['parent']
            start = nodes[ancestor]['position'] if ancestor >= 0 else (0., 0., 0.)
            direction = leaf_attachment_direction(direction, [origin[i]-start[i] for i in range(3)],
                                                  growth['leaf_attachment_angle'])
        add('leaf', parent, position, angle, scale, 'basal_leaf' if basal else 'cauline_leaf', direction)
        area += leaf_length*p['leaf_width_m']*.65*scale**2

    # Mixed attachment includes a short basal cohort, which diminishes as
    # the stem elongates. This is not an independently modelled biennial.
    basal_count = 0
    if maturity and growth.get('leaf_attachment_pattern') == 'mixed':
        retention = max(0., 1.-maturity*1.15)
        basal_count = round(p['basal_leaf_count']*retention)
        for i in range(basal_count):
            angle = phase + i*137.5
            leaf(-1, (0., 0., .004+height*.004), .05, angle,
                 min(1., maturity*3), basal=True)

    main, parent, xy = [], -1, [0., 0.]
    for i in range(visible_count):
        f = fractions[i]
        z = min(active_height, height*f*.93)
        previous_z = nodes[parent]['position'][2] if parent >= 0 else 0.
        angle = phase+i*float(growth.get('phyllotaxis_deg', 137.5))
        displacement = max(0., z-previous_z)*p['axis_deflection']
        xy[0] += math.cos(math.radians(phase+rng.uniform(-45,45)))*displacement
        xy[1] += math.sin(math.radians(phase+rng.uniform(-45,45)))*displacement
        pos = (*xy, z)
        parent = add('stem_section', parent, pos, angle, 1.-.55*f, 'main_axis')
        main.append(parent)
        expansion = min(1., max(0., (maturity-i/count)/.20))
        leaf(parent, pos, i/max(1,count-1), angle, expansion)

    # Layout is fixed by seed and host rank; floral phase adds organs only.
    branch_growth = max(0., min(1., (maturity-p['branch_maturity_start'])/(1-p['branch_maturity_start'])))
    laterals, terminals, flower_count, fruit_count = 0, [], 0, 0
    if main and branch_growth > 0. and p['lateral_length_ratio'] > 0.:
        hosts = [i for i,f in enumerate(fractions[:len(main)]) if p['branch_start_fraction'] <= f <= .90]
        lateral_n = min(int(p['lateral_count']), len(hosts))
        chosen = [hosts[round(j*(len(hosts)-1)/max(1,lateral_n-1))] for j in range(lateral_n)]
        for j,i in enumerate(chosen):
            host = main[i]
            start = nodes[host]['position']
            angle = phase+i*float(growth.get('phyllotaxis_deg',137.5))+rng.uniform(-15.,15.)
            rad = math.radians(angle)
            reach = height*p['lateral_length_ratio']*(1-.42*fractions[i])*branch_growth*rng.uniform(.80,1.12)
            rise = max(0., height*maturity-start[2])*.55*branch_growth
            parent = host
            for step in (.36,.72,1.):
                pos = (start[0]+math.cos(rad)*reach*step, start[1]+math.sin(rad)*reach*step,
                       start[2]+rise*step)
                parent = add('branch_section',parent,pos,angle,.48-.22*step,'lateral_axis')
                if step < 1.:
                    leaf(parent,pos,.60+.35*step,angle+105.,branch_growth,lateral=True)
            laterals += 1
            terminals.append((parent, angle, min(height*.075, reach*.45), int(p['heads_per_lateral'])))
    if main and maturity > p['branch_maturity_start']:
        terminals.append((main[-1], phase, height*.035*branch_growth, min(3,int(p['heads_per_lateral']))))

    can_reproduce = growth.get('reproductive_mode') in {'sexual','both','apomictic'}
    terminal = growth.get('flowering_position') in {'terminal','mixed'}
    # Terminal displays have explicit ascending peduncles even before bloom;
    # no head is floated away from a stem socket.
    for host, angle, reach, head_count in terminals:
        start = nodes[host]['position']
        for i in range(head_count):
            a = angle + i*137.5
            rad = math.radians(a)
            spread = reach*(.55+.45*(i+1)/head_count)
            rise = max(0., height*maturity-start[2]) * (.25+.55*((i*3)%5)/4) * branch_growth
            end = (start[0]+math.cos(rad)*spread,start[1]+math.sin(rad)*spread,start[2]+rise)
            peduncle = add('branch_section',host,end,a,.16,'peduncle')
            if can_reproduce and terminal and flowering > 0.:
                add('flower',peduncle,end,0.,.82+.18*flowering,'terminal_head',[0.,0.,1.])
                flower_count += 1
            if can_reproduce and terminal and fruiting > .25:
                # One retained head represents cypselae/pappus as a display
                # unit. It is not a centimetre-sized individual seed.
                add('fruit',peduncle,end,0.,.8+.2*fruiting,'retained_head',[0.,0.,1.])
                fruit_count += 1

    return nodes, {'sympodial_herb_version':SYMPODIAL_HERB_VERSION,
                   'sympodial_unit_count':len(main), 'sympodial_lateral_axis_count':laterals,
                   'sympodial_terminal_count':len(terminals), 'sympodial_flower_count':flower_count,
                   'sympodial_fruit_count':fruit_count, 'basal_leaf_count':basal_count,
                   'estimated_leaf_count':sum(n['kind']=='leaf' for n in nodes),
                   'leaf_area_m2':round(area,6), 'structural_axis_length_m':round(axis_length,6)}
