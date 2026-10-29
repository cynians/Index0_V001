"""Explicit fungal body recipes, separate from vascular plant organs."""
import math
import re

FUNGAL_TRAIT_SCHEMA_FIELDS = {
    key: {"type": kind, "section": "Simulation / Fungal Ecology", "optional": True}
    for key, kind in (("fungal_growth_profile", "dict"), ("fungal_body_module_ref", "string"),
                      ("fungal_cap_module_ref", "string"), ("fungal_module_anchors", "dict"))
}
FUNGAL_ASSET_FIELDS = {"fruiting_body": "fungal_body_module_ref", "fruiting_cap": "fungal_cap_module_ref"}
FUNGAL_SUBSTRATES = {"living_hardwood", "dead_hardwood", "living_conifer", "dead_conifer"}


def validate_fungal_profile(value):
    if isinstance(value, dict) and value.get("body_form") in {"pitted_stalked", "sessile_cup"}:
        return validate_ground_fungal_profile(value)
    if not isinstance(value, dict) or value.get("body_form") != "bracket":
        raise ValueError("fungal_growth_profile.body_form must be bracket")
    substrates = value.get("substrates")
    if not isinstance(substrates, list) or not substrates or not all(isinstance(v,str) for v in substrates) or not set(substrates) <= FUNGAL_SUBSTRATES:
        raise ValueError("fungal_growth_profile.substrates must specify supported wood types")
    feeding = value.get("feeding_modes")
    if not isinstance(feeding, list) or not feeding or not all(isinstance(v,str) for v in feeding) or not set(feeding) <= {"wood_saprotroph", "living_tree_pathogen"}:
        raise ValueError("fungal_growth_profile.feeding_modes must specify supported wood feeding")
    for key in ("visual_calibration", "simulation_calibration"):
        if key in value and not isinstance(value[key], dict):
            raise ValueError(f"{key} must be a calibration object")
    def finite_numbers(obj):
        if isinstance(obj, dict):
            for v in obj.values(): finite_numbers(v)
        elif isinstance(obj, list):
            for v in obj: finite_numbers(v)
        elif isinstance(obj, float) and not math.isfinite(obj):
            raise ValueError("Fungal recipe numbers must be finite")
    finite_numbers(value)
    fit = value.get("visual_calibration") or {}
    palette = fit.get('weathering_palette')
    if palette is not None:
        if not isinstance(palette, list) or not 1 <= len(palette) <= 12:
            raise ValueError('weathering_palette requires one to twelve RGB pairs')
        for pair in palette:
            if not isinstance(pair, dict) or set(pair) != {'fresh_rgb', 'weathered_rgb'}:
                raise ValueError('weathering_palette needs fresh_rgb and weathered_rgb')
            for rgb in pair.values():
                if not isinstance(rgb, list) or len(rgb) != 3 or any(isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 255 for v in rgb):
                    raise ValueError('Weathering RGB channels must be integers in 0..255')
        if len({tuple(pair['fresh_rgb']) for pair in palette}) != len(palette):
            raise ValueError('Weathering fresh RGB colours must be unique')
    keys = fit.get("body_variant_keys")
    if keys is not None and (not isinstance(keys, list) or not 1 <= len(keys) <= 8
                             or any(not isinstance(k,str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", k) for k in keys)
                             or len(set(keys)) != len(keys)):
        raise ValueError("body_variant_keys must contain one to eight unique named views")
    scales = fit.get("cap_width_scale_range")
    if scales is not None and (not isinstance(scales, list) or len(scales) != 2
                               or any(isinstance(v,bool) or not isinstance(v,(int,float)) for v in scales)
                               or not .25 <= scales[0] <= scales[1] <= 2):
        raise ValueError("cap_width_scale_range must be an ordered .25–2 visual-fit interval")
    groups = fit.get("body_cluster_count")
    if groups is not None and (isinstance(groups,bool) or not isinstance(groups,int) or not 1 <= groups <= 8):
        raise ValueError("body_cluster_count must be an integer from one to eight")
    sessile = value.get("attachment") == "sessile"
    if sessile:
        fit = value.get("visual_calibration") or {}
        for field in ("stipe_length_m", "stipe_diameter_m"):
            if field in fit and (isinstance(fit[field], bool) or not isinstance(fit[field], (int, float)) or fit[field] != 0):
                raise ValueError("Sessile brackets cannot specify a positive or invalid stalk calibration")
    for field in ("cap_width", "cap_depth", "cap_thickness", "stipe_length", "stipe_diameter"):
        measurement = value.get(field)
        if measurement is None:
            continue
        if not isinstance(measurement, dict):
            raise ValueError(f"{field} must be a measurement object")
        values = [measurement[k] for k in ("min_m", "typical_m", "max_m") if k in measurement]
        if sessile and field in {"stipe_length", "stipe_diameter"}:
            if not values or any(isinstance(v, bool) or not isinstance(v, (int, float)) or v != 0 for v in values):
                raise ValueError(f"Sessile {field} must be zero or omitted")
            continue
        if not values or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 < v <= 5 for v in values) or values != sorted(values):
            raise ValueError(f"{field} needs positive, ordered metric dimensions")


def validate_ground_fungal_profile(value):
    """A soil-fruiting ascocarp recipe; never silently treated as a wood shelf."""
    cup = value.get('body_form') == 'sessile_cup'
    if value.get("substrates") != ["soil_humus"]:
        raise ValueError("Pitted stalked fungi require soil_humus substrate")
    allowed_feeding = (["soil_saprotroph"], ["soil_trophic_unknown"]) if cup else (["soil_saprotroph"],)
    if value.get("feeding_modes") not in allowed_feeding:
        raise ValueError("Unsupported ground fungal feeding mode")
    if value.get("attachment") != ("ground_sessile" if cup else "ground_stalked"):
        raise ValueError("Ground fungal attachment must match its body form")
    def finite(obj):
        if isinstance(obj, dict):
            for v in obj.values(): finite(v)
        elif isinstance(obj, list):
            for v in obj: finite(v)
        elif isinstance(obj, float) and not math.isfinite(obj):
            raise ValueError("Ground fungal numbers must be finite")
    finite(value)
    for field in ("cap_width", "cap_height", "stipe_length", "stipe_diameter"):
        data = value.get(field)
        if not isinstance(data, dict) or not all(k in data for k in ("min_m", "typical_m", "max_m")):
            raise ValueError(f"{field} requires min/typical/max metric dimensions")
        dims = [data[k] for k in ("min_m", "typical_m", "max_m")]
        if cup and field in {'stipe_length','stipe_diameter'}:
            if any(isinstance(v,bool) or not isinstance(v,(int,float)) or v != 0 for v in dims):
                raise ValueError('Sessile cups require zero stalk dimensions')
            continue
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 < v <= 1 for v in dims) or dims != sorted(dims):
            raise ValueError(f"{field} needs positive ordered dimensions below one metre")
    if value["stipe_diameter"]["typical_m"] > value["cap_width"]["typical_m"]:
        raise ValueError("Stipe diameter must not exceed cap width")
    for group, limits in {
        "visual_calibration": {"body_count": (1, 24), "colony_radius_m": (.05, 2), "mycelium_depth_m": (.005, .5),
                               **({'body_cluster_radius_ratio':(.1,1.)} if cup else {})},
        "simulation_calibration": {"colony_model_days": (10, 1000), "first_flush_model_days": (1, 1000), "flush_cycle_model_days": (10, 1000)},
    }.items():
        data = value.get(group, {})
        if not isinstance(data, dict): raise ValueError(f"{group} must be an object")
        for k, v in data.items():
            if cup and group == 'visual_calibration' and k == 'body_variant_keys':
                if (not isinstance(v,list) or not 1 <= len(v) <= 8
                        or any(not isinstance(key,str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,31}',key) for key in v)
                        or len(set(v)) != len(v)):
                    raise ValueError('Cup variants require one to eight unique names')
                continue
            if k not in limits or isinstance(v, bool) or not isinstance(v, (int, float)) or not limits[k][0] <= v <= limits[k][1]:
                raise ValueError(f"Invalid ground fungal calibration: {k}")
            if k == "body_count" and int(v) != v:
                raise ValueError("body_count must be an integer")
