"""Portable emergent aquatic clumps with separate petioles and planar blades.

The recipe is opt-in through plant_shoot_profile. Counts, angles and sediment
depth are display calibrations; metric stalk lengths can come from floras.
Canonical organs are retained at all LODs. This represents one basal clump,
not the spread or demographics of an entire rhizomatous colony.
"""
import math
import random

EMERGENT_ROSETTE_VERSION = 1
PROFILE_RANGES = {
    'petiole_length_m': (.05, 5.), 'peduncle_length_m': (.02, 5.),
    'petiole_spread': (0., .8), 'blade_elevation_deg': (-45., 85.),
    'blade_width_ratio': (.05, 2.), 'petiole_radius_m': (.001, .05),
    'sediment_depth_m': (0., .5), 'leaf_count': (1, 24),
    'fruit_peduncle_drop': (0., 1.),
}


def emergent_rosette_profile(value):
    if not isinstance(value, dict) or value.get('form') != 'emergent_rosette':
        return None
    for key, (lo, hi) in PROFILE_RANGES.items():
        number = value.get(key)
        if (isinstance(number, bool) or not isinstance(number, (int, float))
                or not math.isfinite(number) or not lo <= number <= hi):
            return None
    if int(value['leaf_count']) != value['leaf_count']:
        return None
    return {'form': 'emergent_rosette', 'version': EMERGENT_ROSETTE_VERSION,
            **{key: value[key] for key in PROFILE_RANGES},
            'status': str(value.get('status') or 'qualitative_display_recipe')}


def planar_blade_bounds(position, frame, length, width_ratio):
    """Conservative blade rectangle, including backward-pointing basal lobes."""
    forward, normal = frame['forward'], frame['normal']
    right = (normal[1]*forward[2]-normal[2]*forward[1],
             normal[2]*forward[0]-normal[0]*forward[2],
             normal[0]*forward[1]-normal[1]*forward[0])
    half = width_ratio * length * .5
    return [tuple(position[axis] + forward[axis]*length*t + right[axis]*half*side
                  for axis in range(3)) for t in (-.35, .85) for side in (-1, 1)]


def build_emergent_rosette(growth, maturity, flowering, fruiting, seed):
    """Bounded local graph: -1 is the sediment crown, others are earlier nodes."""
    profile = emergent_rosette_profile(growth.get('emergent_rosette_profile'))
    if profile is None:
        return [], {}
    def unit(value):
        return max(0., min(1., float(value))) if math.isfinite(float(value)) else 0.
    maturity, flowering, fruiting = map(unit, (maturity, flowering, fruiting))
    nodes = []
    depth = profile['sediment_depth_m']
    axis_length = 0.
    rng = random.Random(f'{seed}:emergent_rosette')
    phase = rng.uniform(0, 360)
    count = max(1, round(1 + (profile['leaf_count'] - 1) * maturity))
    blade_length = float(growth['leaf_length_m'])
    height = float(growth['max_height_m'])

    def add(kind, parent, end, angle, scale, path=None, frame=None):
        nonlocal axis_length
        if kind == 'stem_section':
            start = nodes[parent]['position'] if parent >= 0 else (0., 0., -depth)
            points = [start] + (path or [end])
            axis_length += sum(math.dist(a, b) for a, b in zip(points, points[1:]))
        nodes.append({'kind': kind, 'parent': parent, 'position': end,
                      'angle': angle, 'scale': scale, 'path': path, 'frame': frame})
        return len(nodes) - 1

    for i in range(count):
        angle = phase + i * 137.5 + rng.uniform(-12, 12)
        rad = math.radians(angle)
        scale = max(.05, math.sqrt(maturity)) * rng.uniform(.78, 1.)
        length = min(profile['petiole_length_m'] * maturity * rng.uniform(.78, 1.16), height*.82)
        reach = length * profile['petiole_spread'] * rng.uniform(.5, 1.)
        rise = math.sqrt(max(0., length*length - reach*reach))
        end = (math.cos(rad)*reach, math.sin(rad)*reach, -depth+rise)
        path = [(end[0]*t*t, end[1]*t*t, -depth+rise*t) for t in (.33, .66, 1.)]
        petiole = add('stem_section', -1, end, angle, 1., path)
        elevation = math.radians(max(-45, min(85, profile['blade_elevation_deg'] + rng.uniform(-28,28))))
        forward = (math.cos(rad)*math.cos(elevation), math.sin(rad)*math.cos(elevation), math.sin(elevation))
        normal = (-math.cos(rad)*math.sin(elevation), -math.sin(rad)*math.sin(elevation), math.cos(elevation))
        add('leaf', petiole, end, angle, scale, frame={
            'forward': list(forward), 'normal': list(normal), 'planar_leaf': True,
            'min_render_lod': 0 if i % 3 == 0 else 1 if i % 2 == 0 else 2})

    sexual = growth.get('reproductive_mode') in {'sexual', 'both', 'apomictic'}
    known = growth.get('reproductive_structure') not in {None, '', 'other_unknown'}
    if sexual and known and maturity > 0 and max(flowering, fruiting) > 0:
        for i in range(2 if maturity >= .75 else 1):
            rad = math.radians(phase + 70 + i*170)
            length = min(profile['peduncle_length_m'] * maturity, height*.7)
            reach = length*.18
            rise = math.sqrt(length*length - reach*reach)
            top = -depth + rise
            # One reproductive axis changes state; flower and fruit are not
            # duplicated at the same socket. Fruit set bends toward the water.
            is_fruit = fruiting > flowering
            drop = profile['fruit_peduncle_drop'] * fruiting if is_fruit else 0.
            end = (math.cos(rad)*reach*(1+2*drop), math.sin(rad)*reach*(1+2*drop),
                   top*(1-drop))
            path = [(math.cos(rad)*reach*(t+2*drop*t*t),
                     math.sin(rad)*reach*(t+2*drop*t*t),
                     -depth+rise*t-top*drop*t*t) for t in (.25,.5,.75,1.)]
            peduncle = add('stem_section', -1, end, math.degrees(rad), 1., path)
            add('fruit' if is_fruit else 'flower', peduncle, end,
                115*drop if is_fruit else 0., 1., frame={'min_render_lod': 1})

    leaves = [n for n in nodes if n['kind'] == 'leaf']
    area = sum(blade_length**2 * profile['blade_width_ratio'] * .60 * n['scale']**2 for n in leaves)
    return nodes, {'emergent_leaf_count': len(leaves), 'emergent_leaf_area_m2': round(area, 6),
                   'structural_axis_length_m': round(axis_length, 6),
                   'water_surface_z_m': 0., 'sediment_crown_z_m': -depth,
                   'aquatic_body_plan': 'emergent_rosette'}
