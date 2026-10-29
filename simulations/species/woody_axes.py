"""Optional continuous woody-axis proportions, independent of species identity.

These dimensionless controls are visual calibration, not water-storage physics
or a prediction of diameter at a real age. Missing recipes are neutral.
"""
import math


WOODY_AXES_VERSION = 1
CONTROL_BOUNDS = {
    "trunk_radius_ratio": (.005, .25),
    "trunk_taper_exponent": (1., 8.),
    "crown_base_fraction": (.1, .8),
    "primary_branch_radius_ratio": (.001, .05),
}


def woody_axes_profile(value):
    if not isinstance(value, dict) or value.get("form") != "woody_axes":
        return None
    result = {"form": "woody_axes", "version": WOODY_AXES_VERSION}
    for key, (low, high) in CONTROL_BOUNDS.items():
        number = value.get(key)
        if (isinstance(number, bool) or not isinstance(number, (int, float))
                or not math.isfinite(number) or not low <= number <= high):
            return None
        result[key] = float(number)
    if 'leaf_width_m' in value:
        width=value['leaf_width_m']
        if (isinstance(width,bool) or not isinstance(width,(int,float))
                or not math.isfinite(width) or not .0003 <= width <= .2):
            return None
        result['leaf_width_m']=float(width)
    result["status"] = str(value.get("status") or "provisional_visual_fit")
    return result


def mature_axis_blend(maturity):
    """Keep young axes slender; express adult proportions continuously."""
    return max(0., min(1., float(maturity))) ** 1.6


def trunk_radius(profile, height, radius_scale, t, maturity, original_radius):
    """Retain a cylindrical lower bole, narrowing into the upper crown.

    The terminal shoot taper remains the caller's responsibility. Exponent 1
    yields gradual taper; larger values retain girth farther up the trunk.
    """
    t = max(0., min(1., t))
    adult = height * radius_scale * profile["trunk_radius_ratio"] * (
        1. - .92 * t ** profile["trunk_taper_exponent"])
    blend = mature_axis_blend(maturity)
    return original_radius * (1. - blend) + adult * blend
