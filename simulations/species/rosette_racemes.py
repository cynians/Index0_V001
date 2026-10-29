"""Metric stem control for simple basal-rosette racemes.

The profile describes a reusable body plan. Fruit display reuses the same
terminal sockets as flowers and does not predict seed yield.
"""

import math


def rosette_raceme_profile(value):
    if not isinstance(value, dict) or value.get("form") != "basal_rosette_raceme":
        return None
    radius = value.get("stem_radius_m")
    if (isinstance(radius, bool) or not isinstance(radius, (int, float))
            or not math.isfinite(radius) or not 0.0003 <= radius <= 0.02):
        return None
    return {"form": "basal_rosette_raceme", "version": 1,
            "stem_radius_m": float(radius),
            "status": str(value.get("status") or "metric_stem_profile")}
