"""Optional hanging reproductive display units at existing shoot sockets.

Stalks and sprite extents are model-space metres. They do not add ecological
organs, woody axes or seed production; the original sockets remain canonical.
"""
import math
import random

PENDANT_DISPLAY_VERSION = 1


def pendant_display_profile(value):
    if not isinstance(value, dict):
        return None
    for key, lo, hi in (("flower_drop_m", 0, 2), ("fruit_drop_m", 0, 2),
                        ("stalk_radius_m", .0002, .02)):
        n = value.get(key)
        if isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) or not lo <= n <= hi:
            return None
    color = value.get("stalk_color")
    if (not isinstance(color, (list, tuple)) or len(color) != 3
            or any(isinstance(c, bool) or not isinstance(c, int) or not 0 <= c <= 255 for c in color)):
        return None
    return {"flower_drop_m": float(value["flower_drop_m"]),
            "fruit_drop_m": float(value["fruit_drop_m"]),
            "stalk_radius_m": float(value["stalk_radius_m"]),
            "stalk_color": list(color), "version": PENDANT_DISPLAY_VERSION}


def pendant_geometry(growth, placement, module):
    """Return a lowered attachment and downward tip; missing recipes are neutral."""
    kind = placement[0]
    profile = (growth.get("reproductive_profile") or {}).get("pendant_display")
    if kind not in {"flower", "fruit"} or not profile or not profile.get(f"{kind}_drop_m"):
        return None
    scale = max(.55, float(placement[6]))
    x, y, z = map(float, placement[2:5])
    drop = profile[f"{kind}_drop_m"] * scale
    extent = (getattr(module, "visual", {}) or {}).get("depicted_size_m")
    if kind == "flower" and growth.get("inflorescence_profile"):
        extent = growth["inflorescence_profile"]["length_m"]
    extent = float(extent or getattr(module, "length_m", 0) or 0) * scale
    anchor = (x, y, z - drop)
    return anchor, (x, y, anchor[2] - extent)


def fruit_cluster_profile(value):
    """Optional bounded fruiting-panicle display, separate from seed output."""
    if not isinstance(value,dict):
        return None
    lo,hi=value.get('min_count'),value.get('max_count')
    if (any(isinstance(n,bool) or not isinstance(n,int) for n in (lo,hi))
            or not 1 <= lo <= hi <= 12):
        return None
    spread=value.get('spread_m')
    if (isinstance(spread,bool) or not isinstance(spread,(int,float))
            or not math.isfinite(spread) or not 0 <= spread <= .3):
        return None
    return {'min_count':lo,'max_count':hi,'spread_m':float(spread),'version':1}


def pendant_display_units(growth,placement,module,seed):
    """One original unit, or seeded capsules on a common fruiting socket.

    Offsets and lengths are model metres. Display-only fruit members do not
    create canonical placements, foliage, woody axes or predicted seeds.
    """
    pendant=pendant_geometry(growth,placement,module)
    if pendant is None:
        return []
    recipe=(growth.get('reproductive_profile') or {}).get('fruit_cluster_display')
    if placement[0]!='fruit' or not recipe:
        return [pendant]
    # Key the display to its physical socket rather than a render-list index.
    salt=sum(round(float(placement[i])*10000)*(31+i) for i in (2,3,4))
    rng=random.Random(int(seed)*104729+salt)
    count=rng.randint(recipe['min_count'],recipe['max_count'])
    if count==1:
        return [pendant]
    phase=rng.uniform(0.,math.tau)
    spread=recipe['spread_m']*max(.55,float(placement[6]))
    units=[]
    for i in range(count):
        angle=phase+i*math.tau/count
        dx,dy=math.cos(angle)*spread,math.sin(angle)*spread
        anchor,tip=pendant
        units.append(((anchor[0]+dx,anchor[1]+dy,anchor[2]),
                      (tip[0]+dx,tip[1]+dy,tip[2])))
    return units
