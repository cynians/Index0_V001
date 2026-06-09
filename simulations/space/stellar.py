import math
import re


AU_M = 149_597_870_700.0
LY_M = 9_460_730_472_580_800.0
SOLAR_MASS_KG = 1.98847e30
SOLAR_RADIUS_M = 695_700_000.0


STELLAR_CLASS_PROFILES = {
    "O": {
        "label": "O-Class",
        "display_color": [155, 176, 255],
        "card_color": "#324372",
        "mass_solar": 30.0,
        "radius_solar": 10.0,
        "luminosity_solar": 100000.0,
    },
    "B": {
        "label": "B-Class",
        "display_color": [170, 191, 255],
        "card_color": "#3b4e83",
        "mass_solar": 8.0,
        "radius_solar": 4.0,
        "luminosity_solar": 1000.0,
    },
    "A": {
        "label": "A-Class",
        "display_color": [202, 215, 255],
        "card_color": "#53638d",
        "mass_solar": 2.1,
        "radius_solar": 1.8,
        "luminosity_solar": 25.0,
    },
    "F": {
        "label": "F-Class",
        "display_color": [248, 247, 255],
        "card_color": "#6d6d79",
        "mass_solar": 1.4,
        "radius_solar": 1.3,
        "luminosity_solar": 4.0,
    },
    "G": {
        "label": "G-Class",
        "display_color": [255, 244, 214],
        "card_color": "#766944",
        "mass_solar": 1.0,
        "radius_solar": 1.0,
        "luminosity_solar": 1.0,
    },
    "K": {
        "label": "K-Class",
        "display_color": [255, 210, 161],
        "card_color": "#7d5b3b",
        "mass_solar": 0.7,
        "radius_solar": 0.8,
        "luminosity_solar": 0.4,
    },
    "M": {
        "label": "M-Class",
        "display_color": [255, 166, 116],
        "card_color": "#753f33",
        "mass_solar": 0.3,
        "radius_solar": 0.4,
        "luminosity_solar": 0.04,
    },
}


def parse_star_class_key(value):
    text = str(value or "").strip().upper()
    match = re.search(r"\b([OBAFGKM])\b|^([OBAFGKM])", text)
    if match:
        return match.group(1) or match.group(2)
    return None


def normalize_star_class(value):
    class_key = parse_star_class_key(value)
    if class_key:
        return class_key
    return "G"


def habitable_zone_for_luminosity(luminosity_solar):
    luminosity = max(0.01, float(luminosity_solar or 1.0))
    return {
        "habitable_zone_inner_au": math.sqrt(luminosity / 1.1),
        "habitable_zone_outer_au": math.sqrt(luminosity / 0.53),
    }


def stellar_profile_for_class(value):
    class_key = normalize_star_class(value)
    profile = dict(STELLAR_CLASS_PROFILES.get(class_key, STELLAR_CLASS_PROFILES["G"]))
    profile["class_key"] = class_key
    profile["star_class"] = profile["label"]
    profile["mass_kg"] = profile["mass_solar"] * SOLAR_MASS_KG
    profile["radius_m"] = profile["radius_solar"] * SOLAR_RADIUS_M
    profile.update(habitable_zone_for_luminosity(profile["luminosity_solar"]))
    return profile
