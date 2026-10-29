"""Optional, bounded lateral-shoot envelopes, in z-up metres.

Length is a fraction of mature host-shoot height. Curvature bends the distal
tangent upward; these are visual-fit controls, not measured growth physiology.
"""
import math


LATERAL_SHOOT_VERSION = 1
LATERAL_SHOOT_FIELDS = ("plant_lateral_shoot_length", "plant_lateral_shoot_curvature")


def authored_shoot_control(value):
    if isinstance(value, dict):
        candidate = value.get("typical", value.get("value"))
        numbers = [value.get("min", candidate), candidate, value.get("max", candidate)]
    else:
        candidate = value
        numbers = [candidate]
    if any(isinstance(n, bool) or not isinstance(n, (int, float))
           or not math.isfinite(n) or not 0 <= n <= 1 for n in numbers):
        return None
    return float(candidate) if numbers == sorted(numbers) else None


def supports_lateral_shoot_controls(entity):
    form = entity.get("plant_growth_form")
    behaviour = entity.get("plant_growth_behaviour")
    if form == "forb" and entity.get("plant_woodiness") == "herbaceous":
        return (behaviour == "iterative_indeterminate"
                or (behaviour in {"suckering_clonal", "rhizomatous_clonal", "stoloniferous_clonal"}
                    and entity.get("leaf_attachment_pattern") == "along_stem"))
    return (form == "subshrub" and behaviour == "iterative_indeterminate"
            and entity.get("plant_lifespan") in {"annual", "short_lived_perennial"}
            and entity.get("leaf_attachment_pattern") == "along_stem"
            and entity.get("plant_leaf_distribution") == "along_shoot"
            and entity.get("plant_reproductive_structure") == "capitulum"
            and entity.get("plant_flowering_position") == "terminal")


def lateral_shoot_path(origin, legacy_end, host_height, length=None, curvature=None, phase=0.):
    """Keep canonical branch selection; replace only a lateral's connected path.

    Missing controls return None so the caller runs its exact legacy geometry.
    Zero length collapses the lateral to its socket; zero curvature is straight.
    An independent socket phase varies the pose without consuming layout RNG.
    """
    length, curvature = authored_shoot_control(length), authored_shoot_control(curvature)
    if length is None and curvature is None:
        return None
    delta = [legacy_end[a]-origin[a] for a in range(3)]
    chord = math.sqrt(sum(d*d for d in delta))
    phase = max(-1., min(1., phase))
    height = max(0., min(20., float(host_height)))
    extent = chord if length is None else min(height, 2., height*length*(1+.08*phase))
    if extent <= 1e-9:
        return [tuple(origin)]
    yaw = math.atan2(delta[1], delta[0])
    elevation = math.atan2(delta[2], math.hypot(delta[0], delta[1]))
    curve = curvature if curvature is not None else 0.
    elevation += math.radians(6)*phase*curve
    position = list(origin)
    points = []
    for step in range(8):
        t = (step+.5)/8
        # Change the tangent, rather than adding a sinusoidal sideways wiggle
        # to an otherwise long straight chord.
        angle = elevation+(math.pi/2-elevation)*curve*(t*t*(3-2*t))
        azimuth = yaw+math.radians(6)*phase*curve*math.sin(math.pi*t)
        distance = extent/8
        position[0] += math.cos(azimuth)*math.cos(angle)*distance
        position[1] += math.sin(azimuth)*math.cos(angle)*distance
        position[2] += math.sin(angle)*distance
        points.append(tuple(position))
    return points


def point_on_shoot(origin, path, fraction):
    """Place a socket by arc fraction on the actual polyline, including zero."""
    points = [origin, *path]
    lengths = [math.dist(a, b) for a, b in zip(points, points[1:])]
    target = max(0., min(1., fraction))*sum(lengths)
    for a, b, extent in zip(points, points[1:], lengths):
        if target <= extent and extent > 1e-12:
            t = target/extent
            return tuple(a[axis]+(b[axis]-a[axis])*t for axis in range(3))
        target -= extent
    return tuple(points[-1])
