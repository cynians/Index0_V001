"""Optional short reproductive shoots on the shared woody shrub grammar."""
import math


def woody_spur_profile(value):
    if not isinstance(value, dict) or value.get('form') != 'woody_spurs':
        return None
    limits = {'spur_length_m': (.001, .1), 'flower_stalk_m': (.001, .1),
              'fruit_stalk_m': (.001, .1), 'leaf_width_m': (.001, .2),
              'stem_radius_m': (.001, .1), 'branch_radius_m': (.0001, .03),
              'crown_radius_ratio': (.1, 1.), 'fine_node_spacing_m': (.005, .1),
              'fertile_node_interval': (1, 24)}
    result = {'form': 'woody_spurs', 'version': 1}
    for key, (lo, hi) in limits.items():
        x = value.get(key)
        if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or not lo <= x <= hi:
            return None
        result[key] = float(x)
    if int(result['fertile_node_interval']) != result['fertile_node_interval']:
        return None
    result['fertile_node_interval'] = int(result['fertile_node_interval'])
    result['status'] = str(value.get('status') or 'authored_spur_geometry_calibration')
    return result


def grow_woody_spurs(sim, placements, sites, maturity, life, paths):
    """Keep stable spurs across seasons; display organs also survive LOD baking.

    Density is a representative display budget, not a yield prediction.
    Pedicels lengthen between flower and fruit without moving their parent.
    """
    p = sim.blueprint.growth['woody_spur_profile']
    sexual = sim.blueprint.growth.get('reproductive_mode') in {'sexual', 'both', 'apomictic'}
    flowers = fruits = spurs = 0
    for ordinal, (host, azimuth) in enumerate(sites[::p['fertile_node_interval']]):
        start = placements[host][2:5]
        norm = math.sqrt(1 + .35**2)
        vector = (math.cos(azimuth)/norm, math.sin(azimuth)/norm, .35/norm)
        length = p['spur_length_m'] * max(.05, maturity)
        end = tuple(start[a] + vector[a]*length for a in range(3))
        spur = sim._add(placements, 'branch_section', host, *end, math.degrees(azimuth), .18, 3,
                        placement_paths=paths, path=[start, end])
        spurs += 1
        score = (ordinal*.61803398875+.17) % 1
        kind = ('fruit' if score < life.get('fruiting_factor', 0)*.65 else
                'flower' if score < life.get('reproductive_factor', 0)*.65 else None) if sexual else None
        if kind is None:
            continue
        stalk_length = p['fruit_stalk_m'] if kind == 'fruit' else p['flower_stalk_m']
        tip = tuple(end[a]+vector[a]*stalk_length for a in range(3))
        stalk = sim._add(placements, 'branch_section', spur, *tip, math.degrees(azimuth), .08, 4,
                         placement_paths=paths, path=[end, tip])
        sim._add(placements, kind, stalk, *tip, math.degrees(azimuth), 1., 5)
        flowers += kind == 'flower'
        fruits += kind == 'fruit'
    return {'woody_spur_version': 1, 'woody_spur_count': spurs,
            'shrub_flower_count': flowers, 'shrub_fruit_count': fruits,
            'reproductive_display_unit': 'flower_or_infructescence'}
