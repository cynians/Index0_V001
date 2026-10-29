"""Optional bounded architecture for small, nonwoody spreading shoots."""
import math

def creeping_herb_profile(value):
    if not isinstance(value, dict) or value.get('form') != 'creeping_herb':
        return None
    ranges = {'axis_length_m':(.04,.8), 'tip_lift_m':(0.,.2),
              'stem_radius_m':(.0002,.01), 'leaf_width_m':(.001,.08),
              'pedicel_length_m':(.003,.08), 'fruit_recurve':(0.,1.)}
    for key,(low,high) in ranges.items():
        v=value.get(key)
        if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not low<=v<=high:
            return None
    integers = {'primary_axes':(1,8),'nodes_per_axis':(4,32),'lateral_axes_per_primary':(0,3),'reproductive_node_interval':(1,8)}
    for key,(low,high) in integers.items():
        v=value.get(key)
        if isinstance(v,bool) or not isinstance(v,int) or not low<=v<=high:
            return None
    optional = {}
    for key, (low, high, neutral) in {'petiole_length_m':(0.,.07,0.),
                                    'paired_leaf_size_ratio':(.1,1.,1.)}.items():
        if key not in value:
            continue
        n=value[key]
        if isinstance(n,bool) or not isinstance(n,(int,float)) or not math.isfinite(n) or not low<=n<=high:
            return None
        if n != neutral:
            optional[key]=float(n)
    if 'leaf_pitch_deg' in value:
        n=value['leaf_pitch_deg']
        if isinstance(n,bool) or not isinstance(n,(int,float)) or not math.isfinite(n) or not -20<=n<=85:
            return None
        optional['leaf_pitch_deg']=float(n)
    if 'planar_leaves' in value:
        if not isinstance(value['planar_leaves'],bool):
            return None
        if value['planar_leaves']:
            optional['planar_leaves']=True
    return {'form':'creeping_herb','version':3 if optional.get('planar_leaves') else 2 if optional else 1, **optional,
            **{k:float(value[k]) for k in ranges}, **{k:value[k] for k in integers},
            'status':str(value.get('status') or 'provisional_visual_fit')}
