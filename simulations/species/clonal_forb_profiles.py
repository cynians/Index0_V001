"""Optional display controls for node-bearing clonal herbs.

This profile refines the existing rhizome/stolon/sucker and iterative shoot
grammars. Its dimensions and counts are visual calibration, not growth rates.
"""
import math

CLONAL_FORB_PROFILE_VERSION = 1


def clonal_forb_profile(value):
    if not isinstance(value, dict) or value.get('form') != 'clonal_forb':
        return None
    ranges = {'ramet_reach_m': (.02, 1.), 'stem_radius_m': (.001, .03),
              'branching_start_fraction': (0., 1.)}
    if 'leaf_width_m' in value:
        ranges['leaf_width_m'] = (.001, .2)
    basal = 'basal_leaf_count' in value or 'basal_leaf_length_scale' in value
    if basal:
        count = value.get('basal_leaf_count')
        if isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= 24:
            return None
        ranges['basal_leaf_length_scale'] = (.3, 1.5)
    for key, (low, high) in ranges.items():
        number = value.get(key)
        if (isinstance(number, bool) or not isinstance(number, (int, float))
                or not math.isfinite(number) or not low <= number <= high):
            return None
    count = value.get('nodes_per_shoot')
    if isinstance(count, bool) or not isinstance(count, int) or not 4 <= count <= 48:
        return None
    return {'form': 'clonal_forb', 'version': 2 if basal else CLONAL_FORB_PROFILE_VERSION,
            **{key: float(value[key]) for key in ranges}, 'nodes_per_shoot': count,
            **({'basal_leaf_count':value['basal_leaf_count']} if basal else {}),
            'status': str(value.get('status') or 'qualitative_display_recipe')}
