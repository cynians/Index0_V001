"""Bounded visual development of leaves on sequential herbaceous nodes.

The clock and coefficients are qualitative display assumptions, not measured
leaf expansion rates. Length and width expand independently, around the
existing attachment socket, without modifying the source pixel document.
"""
import math


LEAF_DEVELOPMENT_VERSION = 1


def authored_leaf_attachment_angle(value):
    """An optional normalized angle; malformed/unknown data stays neutral."""
    if isinstance(value, dict):
        candidate = value.get("typical", value.get("value"))
        numbers = [value.get("min", candidate), candidate, value.get("max", candidate)]
    else:
        candidate = value
        numbers = [candidate]
    if any(isinstance(n, bool) or not isinstance(n, (int, float))
           or not math.isfinite(n) or not 0 <= n <= 1 for n in numbers):
        return None
    if numbers != sorted(numbers):
        return None
    return float(candidate)


def leaf_attachment_direction(forward, host_direction, angle_fraction, socket_phase=0.0):
    """Pose a blade around the local host tangent, retaining its radial side.

    Angle is from the shoot's distal direction, not world vertical. The
    phase jitter tapers to zero at parallel/antiparallel endpoints. Neither
    the socket nor physical leaf dimensions change.
    """
    angle = authored_leaf_attachment_angle(angle_fraction)
    if angle is None:
        return list(forward)
    length = math.sqrt(sum(v*v for v in host_direction))
    axis = [v/length for v in host_direction] if length > 1e-9 else [0., 0., 1.]
    dot = sum(a*b for a,b in zip(forward, axis))
    radial = [forward[i]-axis[i]*dot for i in range(3)]
    length = math.sqrt(sum(v*v for v in radial))
    if length < 1e-9:
        # Choose the coordinate least parallel to the host; no random draw.
        index = min(range(3), key=lambda i: abs(axis[i]))
        radial = [(1. if i == index else 0.)-axis[i]*axis[index] for i in range(3)]
        length = math.sqrt(sum(v*v for v in radial))
    radial = [v/length for v in radial]
    theta = angle*math.pi
    theta += math.radians(8)*_bounded(socket_phase, 0, -1, 1)*math.sin(theta)
    return [round(axis[i]*math.cos(theta)+radial[i]*math.sin(theta), 6) for i in range(3)]


def leaf_host_tangent(origin, path, socket):
    """Forward tangent of the nearest piece of the actual curved host path."""
    points = [origin, *path]
    nearest = float("inf")
    tangent = [0., 0., 1.]
    for start, end in zip(points, points[1:]):
        direction = [end[i]-start[i] for i in range(3)]
        length2 = sum(v*v for v in direction)
        if length2 < 1e-12:
            continue
        along = max(0., min(1., sum((socket[i]-start[i])*direction[i] for i in range(3))/length2))
        distance2 = sum((socket[i]-start[i]-along*direction[i])**2 for i in range(3))
        if distance2 < nearest:
            nearest, tangent = distance2, direction
    return tangent


def forb_leaf_direction(azimuth_deg, node_rank, socket_phase=0.0):
    """Turn spiral insertion around the stem into a 3D outward blade.

    This is a bounded visual pose, not a measured insertion-angle phenotype.
    Lower blades spread broadly; distal blades incline toward the apex.
    """
    rank = _bounded(node_rank, 0, 0, 1)
    phase = _bounded(socket_phase, 0, -1, 1)
    azimuth = math.radians(_bounded(azimuth_deg, 0, -100000, 100000) + 12 * phase)
    elevation = math.radians(8 + 38 * rank + 10 * phase)
    return [round(math.cos(azimuth) * math.cos(elevation), 6),
            round(math.sin(azimuth) * math.cos(elevation), 6),
            round(math.sin(elevation), 6)]


def _bounded(value, default, low, high):
    try:
        value = float(value)
    except (TypeError, ValueError):
        value = default
    if not math.isfinite(value):
        value = default
    return min(high, max(low, value))


def forb_leaf_development(node_index, mature_node_count, shoot_age_fraction,
                          upper_length_scale=1.45, *, lateral=False):
    """Return portable length/width scales and an explicit leaf-age proxy.

    Node rank uses the mature axis, so adding a new node never shrinks an
    existing leaf. Distal leaves have smaller adult targets independently of
    their age: an old apical bract does not become a large basal blade.
    """
    count = _bounded(mature_node_count, 1, 1, 14)
    index = _bounded(node_index, 0, 0, count - 1)
    age = _bounded(shoot_age_fraction, 0, 0, 8)
    upper = _bounded(upper_length_scale, 1.45, .1, 1.55)
    rank = index / max(1, count - 1)
    birth = (index + .5) / count + (.05 if lateral else 0)
    leaf_age = max(0, age - birth)
    expansion = min(1, leaf_age / .24)
    development = expansion * expansion * (3 - 2 * expansion)
    adult_length = upper * (1 - .70 * rank ** 1.4) * (.65 if lateral else 1)
    adult_width = .65 * (1 - .72 * rank) * (.70 if lateral else 1)
    length = adult_length * (.10 + .90 * development)
    width = adult_width * (.24 + .76 * math.sqrt(development))
    width = min(width, length * 1.5)
    return {
        "model": "sequential_node_visual_proxy",
        "node_rank": round(rank, 6),
        "birth_age_fraction": round(birth, 6),
        "leaf_age_fraction": round(leaf_age, 6),
        "development_fraction": round(development, 6),
        "length_scale": round(length, 6),
        "width_scale": round(width / max(.001, length), 6),
        "area_scale": round(length * width, 6),
    }
