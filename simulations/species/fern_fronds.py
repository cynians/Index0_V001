"""Metric, upright-to-arching fern centerlines; no extra botanical leaves."""

import math

FERN_FROND_GRAMMAR_VERSION = 2


def frond_centerline(origin, azimuth, length, stipe_fraction, height, elevation, tip_elevation=-.65):
    """Integrate equal arc-length steps, retaining an upright bare stipe.

    Angles and the bend profile are visual model coefficients. Height bounds
    the curved blade rather than flattening the entire stipe to its tip angle.
    """
    length = max(.001, min(100., float(length)))
    stipe_fraction = max(.18, min(.68, float(stipe_fraction)))
    height = max(.05, float(height))
    elevation = min(float(elevation), math.asin(min(.98, height * .8 / (length * stipe_fraction))))
    steps = 64

    def integrate(end_angle):
        points = [tuple(float(v) for v in origin)]
        for step in range(steps):
            t = (step + .5) / steps
            u = max(0., (t - stipe_fraction) / (1. - stipe_fraction))
            angle = elevation + (end_angle - elevation) * u ** .85
            distance = length / steps
            x, y, z = points[-1]
            if z + math.sin(angle) * distance < origin[2]:
                angle = math.asin(max(-1., min(0., (origin[2] - z) / distance)))
            reach = distance * math.cos(angle)
            points.append((x + math.cos(azimuth) * reach,
                           y + math.sin(azimuth) * reach,
                           z + math.sin(angle) * distance))
        return points

    points = integrate(tip_elevation)
    # Lower only the blade's terminal angle if a long frond exceeds height.
    # The stipe remains upright; all segment lengths stay metric and equal.
    if max(p[2] - origin[2] for p in points) > height:
        lo, hi = -1.5, tip_elevation
        for _ in range(20):
            mid = (lo + hi) * .5
            trial = integrate(mid)
            if max(p[2] - origin[2] for p in trial) > height:
                hi = mid
            else:
                lo = mid
        points = integrate(lo)
    return points
