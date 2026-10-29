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

STELLAR_CLASS_ANCHORS = {
    "O": {
        "display_color": [155, 176, 255],
        "card_color": "#324372",
        "mass_solar": 60.0,
        "radius_solar": 15.0,
        "luminosity_solar": 800000.0,
    },
    "B": {
        "display_color": [170, 191, 255],
        "card_color": "#3b4e83",
        "mass_solar": 18.0,
        "radius_solar": 7.0,
        "luminosity_solar": 20000.0,
    },
    "A": {
        "display_color": [202, 215, 255],
        "card_color": "#53638d",
        "mass_solar": 3.2,
        "radius_solar": 2.5,
        "luminosity_solar": 80.0,
    },
    "F": {
        "display_color": [248, 247, 255],
        "card_color": "#6d6d79",
        "mass_solar": 1.7,
        "radius_solar": 1.4,
        "luminosity_solar": 6.0,
    },
    "G": {
        "display_color": [255, 244, 214],
        "card_color": "#766944",
        "mass_solar": 1.05,
        "radius_solar": 1.1,
        "luminosity_solar": 1.4,
    },
    "K": {
        "display_color": [255, 210, 161],
        "card_color": "#7d5b3b",
        "mass_solar": 0.8,
        "radius_solar": 0.85,
        "luminosity_solar": 0.4,
    },
    "M": {
        "display_color": [255, 166, 116],
        "card_color": "#753f33",
        "mass_solar": 0.51,
        "radius_solar": 0.6,
        "luminosity_solar": 0.08,
    },
    "M9": {
        "display_color": [255, 128, 92],
        "card_color": "#69342c",
        "mass_solar": 0.08,
        "radius_solar": 0.12,
        "luminosity_solar": 0.0008,
    },
}

STELLAR_CLASS_ORDER = ["O", "B", "A", "F", "G", "K", "M"]
STELLAR_LUMINOSITY_CLASSES = ("IA", "IB", "II", "III", "IV", "V", "VI", "VII")
STELLAR_CLASS_HELP = "Use G2V style: OBAFGKM + optional 0-9 + Ia/Ib/II/III/IV/V/VI/VII."


def parse_star_class_key(value):
    parsed = parse_stellar_class(value)
    if parsed:
        return parsed["class_key"]
    return None


def parse_stellar_class(value):
    text = str(value or "").strip().upper()
    match = re.fullmatch(
        r"([OBAFGKM])\s*([0-9])?\s*(IA|IB|III|II|IV|VII|VI|V)?",
        text,
    )
    if not match:
        match = re.fullmatch(r"([OBAFGKM])\s*[- ]?\s*CLASS", text)
    if not match:
        return None

    class_key = match.group(1)
    subclass_text = match.group(2) if match.lastindex and match.lastindex >= 2 else None
    luminosity_class = match.group(3) if match.lastindex and match.lastindex >= 3 else None
    luminosity_class = luminosity_class or "V"
    subclass = int(subclass_text) if subclass_text is not None else None
    return {
        "class_key": class_key,
        "subclass": subclass,
        "luminosity_class": luminosity_class,
    }


def is_valid_stellar_class(value):
    return parse_stellar_class(value) is not None


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


def _mix_channel(left, right, fraction):
    return int(round(left + (right - left) * fraction))


def _interpolate_color(left, right, fraction):
    return [
        _mix_channel(left[index], right[index], fraction)
        for index in range(3)
    ]


def _hex_to_rgb(value):
    text = str(value or "").strip().lstrip("#")
    if len(text) != 6:
        return None
    try:
        return [int(text[index:index + 2], 16) for index in range(0, 6, 2)]
    except ValueError:
        return None


def _rgb_to_hex(color):
    return "#" + "".join(f"{max(0, min(255, int(channel))):02x}" for channel in color)


def _interpolate_hex(left, right, fraction):
    left_rgb = _hex_to_rgb(left)
    right_rgb = _hex_to_rgb(right)
    if left_rgb is None or right_rgb is None:
        return left
    return _rgb_to_hex(_interpolate_color(left_rgb, right_rgb, fraction))


def _interpolate_log(left, right, fraction):
    left = max(float(left), 1e-9)
    right = max(float(right), 1e-9)
    return math.exp(math.log(left) + (math.log(right) - math.log(left)) * fraction)


def _next_anchor_for_class(class_key):
    if class_key == "M":
        return STELLAR_CLASS_ANCHORS["M9"]
    index = STELLAR_CLASS_ORDER.index(class_key)
    return STELLAR_CLASS_ANCHORS[STELLAR_CLASS_ORDER[index + 1]]


def stellar_profile_for_class(value):
    parsed = parse_stellar_class(value)
    class_key = parsed["class_key"] if parsed else normalize_star_class(value)
    subclass = parsed.get("subclass") if parsed else None
    luminosity_class = parsed.get("luminosity_class", "V") if parsed else "V"

    if subclass is None:
        profile = dict(STELLAR_CLASS_PROFILES.get(class_key, STELLAR_CLASS_PROFILES["G"]))
        label = profile["label"]
        spectral_class = class_key
    else:
        start = STELLAR_CLASS_ANCHORS.get(class_key, STELLAR_CLASS_ANCHORS["G"])
        end = _next_anchor_for_class(class_key)
        fraction = max(0.0, min(9.0, float(subclass))) / 10.0
        profile = {
            "display_color": _interpolate_color(start["display_color"], end["display_color"], fraction),
            "card_color": _interpolate_hex(start["card_color"], end["card_color"], fraction),
            "mass_solar": _interpolate_log(start["mass_solar"], end["mass_solar"], fraction),
            "radius_solar": _interpolate_log(start["radius_solar"], end["radius_solar"], fraction),
            "luminosity_solar": _interpolate_log(start["luminosity_solar"], end["luminosity_solar"], fraction),
        }
        spectral_class = f"{class_key}{subclass}{luminosity_class}"
        label = spectral_class

    profile["class_key"] = class_key
    profile["subclass"] = subclass
    profile["luminosity_class"] = luminosity_class
    profile["spectral_class"] = spectral_class
    profile["label"] = label
    profile["star_class"] = label
    profile["mass_kg"] = profile["mass_solar"] * SOLAR_MASS_KG
    profile["radius_m"] = profile["radius_solar"] * SOLAR_RADIUS_M
    profile.update(habitable_zone_for_luminosity(profile["luminosity_solar"]))
    return profile
