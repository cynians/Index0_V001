"""Metric persistent sepals with independently ripening free drupelets."""
import math
import pygame


def persistent_calyx_profile(value):
    if not isinstance(value, dict):
        return None
    limits = {'calyx_size_m': (.002, .2), 'flowering_calyx_size_m': (.001, .2),
              'fruitlet_length_m': (.001, .1), 'fruitlet_width_m': (.001, .1),
              'fruitlet_orbit_m': (0, .05), 'max_fruitlets': (1, 12)}
    result = {'version': 1}
    for key, (lo, hi) in limits.items():
        x = value.get(key)
        if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or not lo <= x <= hi:
            return None
        result[key] = float(x)
    if (result['flowering_calyx_size_m'] > result['calyx_size_m']
            or result['fruitlet_width_m'] > result['fruitlet_length_m']
            or result['max_fruitlets'] != int(result['max_fruitlets'])):
        return None
    result['max_fruitlets'] = int(result['max_fruitlets'])
    for key in ('calyx_unripe_color', 'calyx_ripe_color'):
        c = value.get(key)
        if (not isinstance(c, (list, tuple)) or len(c) != 3
                or not all(isinstance(x, int) and not isinstance(x, bool) and 0 <= x <= 255 for x in c)):
            return None
        result[key] = list(c)
    result['status'] = str(value.get('status') or 'authored_persistent_calyx_display')
    result['visual_unit'] = 'infructescence'
    return result


def calyx_extent(profile):
    return max(profile['calyx_size_m'], 2*profile['fruitlet_orbit_m']+profile['fruitlet_length_m'])


def _tint(surface, target, base):
    result = surface.copy()
    delta = [a-b for a, b in zip(target, base)]
    result.fill((*[max(0, c) for c in delta], 0), special_flags=pygame.BLEND_RGBA_ADD)
    result.fill((*[max(0, -c) for c in delta], 0), special_flags=pygame.BLEND_RGBA_SUB)
    return result


def calyx_surface(profile, reproductive, ppm, calyx, fruit, ripeness, variant=0):
    """Compose actual source pixels; cap zoom memory, never inflate organ size."""
    ripeness = max(0., min(1., float(ripeness)))
    ppm = min(max(.01, float(ppm)), 1024/calyx_extent(profile))
    extent = max(1, round(calyx_extent(profile)*ppm))
    canvas = pygame.Surface((extent+4, extent+4), pygame.SRCALPHA)
    center = (canvas.get_width()/2, canvas.get_height()/2)
    progress = min(1., ripeness/.35)
    diameter = (profile['flowering_calyx_size_m']*(1-progress)+profile['calyx_size_m']*progress)*ppm
    color = [round(a*(1-progress)+b*progress) for a, b in zip(profile['calyx_unripe_color'],profile['calyx_ripe_color'])]
    if calyx is not None:
        bounds = calyx.get_bounding_rect()
        if bounds.width and bounds.height:
            unit = _tint(calyx.subsurface(bounds), color, profile['calyx_ripe_color'])
            size = max(1, round(diameter))
            unit = pygame.transform.smoothscale(unit, (size, size)) if size < bounds.height else pygame.transform.scale(unit, (size,size))
            canvas.blit(unit, unit.get_rect(center=center))
    else:
        for i in range(5):
            a = i*math.tau/5-math.pi/2
            tip = (center[0]+math.cos(a)*diameter/2, center[1]+math.sin(a)*diameter/2)
            pygame.draw.line(canvas, color, center, tip, max(1,round(diameter*.16)))
    # Sepals colour early; the drupelets remain green until the end of ripening.
    fruit_progress = max(0., min(1., (ripeness-.45)/.55))
    target = [round(a*(1-fruit_progress)+b*fruit_progress) for a,b in zip(reproductive['unripe_color'],reproductive['ripe_color'])]
    length = max(1,round(profile['fruitlet_length_m']*ppm))
    width = max(1,round(profile['fruitlet_width_m']*ppm))
    count = 1 + int(variant) % profile['max_fruitlets']
    for i in range(count):
        a = (i+.2)*math.tau/profile['max_fruitlets']
        point = (center[0]+math.cos(a)*profile['fruitlet_orbit_m']*ppm,
                 center[1]+math.sin(a)*profile['fruitlet_orbit_m']*ppm)
        if fruit is not None and fruit.get_bounding_rect().width:
            unit = _tint(fruit.subsurface(fruit.get_bounding_rect()), target, reproductive['ripe_color'])
            unit = pygame.transform.smoothscale(unit,(width,length)) if length < unit.get_height() else pygame.transform.scale(unit,(width,length))
            canvas.blit(unit,unit.get_rect(center=point))
        else:
            pygame.draw.ellipse(canvas,target,pygame.Rect(round(point[0]-width/2),round(point[1]-length/2),width,length))
    return canvas, center
