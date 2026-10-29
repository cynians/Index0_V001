"""Metric fronds for opt-in, compressed rhizomatous pinnate crowns.

Angles, age ordering and curvature are visual coefficients. Each entire
frond remains one botanical leaf; its leaflets are display geometry only.
"""
import math

PINNATE_CROWN_VERSION = 1


def crown_frond(origin, phase, ordinal, count, length, angle, openness, droop, stipe):
    age_rank = ordinal / max(1, count - 1)
    azimuth = phase + ordinal * math.pi * (3 - math.sqrt(5))
    elevation = math.pi / 2 - angle * math.pi - age_rank * openness * math.pi * .25
    elevation = max(.1, min(math.pi / 2, elevation))
    tip_elevation = max(-.4, elevation - droop * 1.2 * (.4 + .6 * age_rank))
    stipe = max(.05, min(.68, stipe))
    steps = 64
    points = [tuple(origin)]
    for i in range(steps):
        t = (i + .5) / steps
        blade = max(0., (t - stipe) / (1 - stipe))
        theta = elevation + (tip_elevation - elevation) * blade ** 1.2
        dx = math.cos(azimuth) * math.cos(theta) * length / steps
        dy = math.sin(azimuth) * math.cos(theta) * length / steps
        dz = math.sin(theta) * length / steps
        points.append(tuple(points[-1][axis] + delta for axis, delta in enumerate((dx, dy, dz))))
    forward = (math.cos(azimuth) * math.cos(elevation), math.sin(azimuth) * math.cos(elevation), math.sin(elevation))
    return points, forward


def frond_leaflets(path, count, length, stipe, scale=1.):
    """Even paired attachment rows, with an unpaired last leaflet if needed."""
    stipe = max(.05, min(.68, stipe))
    pairs = math.ceil(count / 2)
    dx, dy = path[-1][0] - path[0][0], path[-1][1] - path[0][1]
    azimuth = math.atan2(dy, dx)
    radial = (-math.sin(azimuth), math.cos(azimuth), 0.)
    ordinals = range(count) if count <= 256 else [round(i * (count - 1) / 255) for i in range(256)]
    for ordinal in ordinals:
        row, side = ordinal // 2, (-1 if ordinal % 2 == 0 else 1)
        u = (row + .5) / max(1, pairs)
        t = stipe + (1 - stipe) * u
        offset = min(len(path) - 1.000001, t * (len(path) - 1))
        index, fraction = int(offset), offset % 1
        base = tuple(path[index][a] * (1 - fraction) + path[index + 1][a] * fraction for a in range(3))
        tangent = [path[index + 1][a] - path[index][a] for a in range(3)]
        norm = max(1e-9, math.sqrt(sum(v*v for v in tangent)))
        tangent = [v / norm for v in tangent]
        # Narrow lanceolate pinnae sweep toward the tip; older distal pinnae
        # bend gently down. This is a visual pose, not additional leaf area.
        direction = [radial[a] * side * .72 + tangent[a] * .70 for a in range(3)]
        direction[2] -= .12 * u
        norm = math.sqrt(sum(v*v for v in direction))
        taper = .04 + .96 * math.sin(math.pi * u) ** .6
        extent = length * scale * taper
        tip = tuple(base[a] + direction[a] / norm * extent for a in range(3))
        yield base, tip, taper
