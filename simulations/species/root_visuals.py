"""Root tissue appearance defaults; colours/diameters are not measured traits."""
import math

import pygame


def root_visual_profile(growth):
    shape = growth.get('shape')
    woody = growth.get('plant_woodiness') == 'woody' or shape in ('tree', 'shrub', 'subshrub')
    if woody:
        radius, base, tip = (.035 if shape == 'tree' else .012), (110, 76, 49), (210, 184, 137)
    elif shape == 'graminoid':
        radius, base, tip = .0012, (163, 144, 101), (233, 224, 180)
    elif shape == 'aquatic':
        radius, base, tip = .002, (139, 119, 79), (224, 214, 166)
    else:
        radius, base, tip = .0028, (160, 127, 88), (230, 208, 163)
    return {'radius_m': radius, 'base_color': base, 'tip_color': tip,
            'woody': woody, 'source': 'functional_form_visual_default', 'version': 1}


def root_segment_style(growth, placement, maturity):
    profile = root_visual_profile(growth)
    kind, _, _, _, _, _, scale, level = placement
    if kind == 'root_support':
        return max(.0003, scale*.012*(.08+.92*maturity)), (120, 105, 58)
    # High-order laterals are fine roots, including on woody plants.
    radius = profile['radius_m'] * scale * (.06+.94*math.sqrt(max(0., maturity)))
    if profile['woody'] and level >= 2:
        radius *= .25 if level == 2 else .12
    fine = min(.92, max(0., (1.-min(1., scale))*.7 + max(0, level-1)*.12))
    fine = min(.95, fine + (1.-maturity)*.25)
    color = tuple(round(a+(b-a)*fine) for a, b in zip(profile['base_color'], profile['tip_color']))
    return max(.00003, radius), color


def draw_root_segment(screen, start, end, start_radius, end_radius, color, pixels_per_metre):
    """Continuous taper with round joins, at the existing native pixel grid."""
    dx, dy = end[0]-start[0], end[1]-start[1]
    length = math.hypot(dx, dy)
    if length < .01:
        return
    r0, r1 = max(.5, start_radius*pixels_per_metre), max(.5, end_radius*pixels_per_metre)
    nx, ny = -dy/length, dx/length
    points = [(round(start[0]+nx*r0), round(start[1]+ny*r0)),
              (round(end[0]+nx*r1), round(end[1]+ny*r1)),
              (round(end[0]-nx*r1), round(end[1]-ny*r1)),
              (round(start[0]-nx*r0), round(start[1]-ny*r0))]
    if max(r0, r1) <= .75:
        pygame.draw.line(screen, color, start, end)
    else:
        pygame.draw.polygon(screen, color, points)
        pygame.draw.circle(screen, color, start, max(1, round(r0)))
        pygame.draw.circle(screen, color, end, max(1, round(r1)))
    if min(r0, r1) >= 2.5:
        highlight = tuple(min(255, c+17) for c in color)
        pygame.draw.line(screen, highlight,
                         (round(start[0]+nx*r0*.3), round(start[1]+ny*r0*.3)),
                         (round(end[0]+nx*r1*.3), round(end[1]+ny*r1*.3)), 1)
