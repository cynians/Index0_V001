"""Portable, bounded display recipe for leafless scapes from a basal rosette."""

import math


SCAPE_ROSETTE_VERSION = 1


def scape_rosette_profile(value):
    if not isinstance(value, dict) or value.get("form") != "scape_rosette":
        return None
    count = value.get("scape_count")
    radius = value.get("scape_radius_m")
    spread = value.get("scape_spread_m")
    if (isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 12
            or any(isinstance(v, bool) or not isinstance(v, (int, float))
                   or not math.isfinite(v) for v in (radius, spread))
            or not 0.0005 <= radius <= 0.012
            or not 0 <= spread <= 0.12):
        return None
    return {"form": "scape_rosette", "version": SCAPE_ROSETTE_VERSION,
            "scape_count": count, "scape_radius_m": float(radius),
            "scape_spread_m": float(spread),
            "status": str(value.get("status") or "qualitative_display_recipe")}
