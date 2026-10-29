"""Bounded display geometry for connected blades and compound panicles.

These qualitative fallbacks decorate existing organs; they do not add
placements, alter growth paths, or contribute ecological flower counts.
"""

import math
import random

import pygame


VISUAL_VERSION = 1


def blade_ribbon(points, half_width_px):
    """Smooth an existing projected path, retaining its socket and tip.

    At most 16 control points and eight samples per segment bound the work.
    Width is supplied in projected physical units by the renderer.
    """
    if not math.isfinite(half_width_px) or half_width_px <= 0:
        return [], [], []
    controls = []
    # Sample long paths across their full extent, including the real tip.
    selected = points if len(points) <= 16 else [points[round(i*(len(points)-1)/15)] for i in range(16)]
    for point in selected:
        x, y = float(point[0]), float(point[1])
        if not math.isfinite(x) or not math.isfinite(y):
            return [], [], []
        if not controls or math.hypot(x-controls[-1][0], y-controls[-1][1]) > .01:
            controls.append((x, y))
    if len(controls) < 2:
        return [], [], []
    center = []
    for i in range(len(controls)-1):
        p0, p1 = controls[max(0, i-1)], controls[i]
        p2, p3 = controls[i+1], controls[min(len(controls)-1, i+2)]
        for j in range(8):
            t = j/8
            center.append(tuple(.5 * (2*b + (-a+c)*t
                + (2*a-5*b+4*c-d)*t*t + (-a+3*b-3*c+d)*t*t*t)
                for a, b, c, d in zip(p0, p1, p2, p3)))
    center.append(controls[-1])
    distances = [0.]
    for a, b in zip(center, center[1:]):
        distances.append(distances[-1] + math.hypot(b[0]-a[0], b[1]-a[1]))
    if distances[-1] <= .01:
        return [], [], []
    left, right = [], []
    for i, point in enumerate(center):
        a, b = center[max(0, i-1)], center[min(len(center)-1, i+1)]
        dx, dy = b[0]-a[0], b[1]-a[1]
        norm = max(.001, math.hypot(dx, dy))
        t = distances[i]/distances[-1]
        # A narrow attached base, broad lower blade, and a pointed tip.
        taper = (.2+.8*math.sin(math.pi*t)**.7) * (1-t**3)
        radius = min(64., half_width_px) * taper
        left.append((point[0]-dy/norm*radius, point[1]+dx/norm*radius))
        right.append((point[0]+dy/norm*radius, point[1]-dx/norm*radius))
    return center, left, right


def draw_blade(screen, points, half_width_px, color):
    center, left, right = blade_ribbon(points, half_width_px)
    if not center:
        return
    dark = tuple(round(c*.68) for c in color)
    light = tuple(min(255, round(c*1.10)) for c in color)
    pygame.draw.polygon(screen, color, left + list(reversed(right)))
    pygame.draw.polygon(screen, dark, center + list(reversed(right)))
    pygame.draw.lines(screen, light, False, center, 1)


def compound_panicle_surface(height, color, variant_seed=0):
    """A loose, irregular branched head with visible spikelet clusters.

    The seed belongs to the organ socket, independent of camera and species
    identity. Branch counts and colours are display defaults, not botany data.
    """
    height = max(6, min(256, int(height)))
    width = max(11, round(height*1.65))
    # Upper side forks and their spikelets may rise above the rachis tip.
    # Reserve headroom without moving the basal attachment socket.
    headroom = max(10, math.ceil(height*.20))
    canvas = pygame.Surface((width+10, height+headroom+5), pygame.SRCALPHA)
    rng = random.Random(int(variant_seed))
    cx, bottom = canvas.get_width()//2, canvas.get_height()-5
    # Living axes and olive spikelets remain visually separate.
    axis = (round(color[0]*.62), round(color[1]*.91), round(color[2]*.63))
    dark = tuple(round(c*.58) for c in color)
    light = tuple(min(255, round(c*1.14)) for c in color)
    rachis = [(cx+round(math.sin(t*2.1)*height*.035), bottom-round(t*height))
              for t in (0., .25, .5, .75, 1.)]
    pygame.draw.lines(canvas, axis, False, rachis, 1)
    radius = max(1, round(height*.018))

    def cluster(point):
        # An oblong, shaded spikelet; a few make each terminal cluster.
        x, y = round(point[0]), round(point[1])
        for j in range(3):
            ox = (j-1)*radius
            oy = (j % 2)*radius
            rect = pygame.Rect(x+ox-radius, y+oy-2*radius, 2*radius+1, 3*radius+1)
            pygame.draw.ellipse(canvas, dark, rect)
            pygame.draw.line(canvas, light, (rect.centerx, rect.top+1),
                             (rect.centerx, rect.bottom-2), 1)

    branches = 9
    for i in range(branches):
        t = .12 + i*.085 + rng.uniform(-.024, .024)
        start = (cx+math.sin(t*2.1)*height*.035, bottom-t*height)
        side = -1 if i % 2 else 1
        reach = width*.40 * (1-.42*t) * rng.uniform(.70, 1.)
        tip = (start[0]+side*reach, start[1]-height*rng.uniform(.04, .18))
        pygame.draw.line(canvas, axis, start, tip, 1)
        cluster(tip)
        for j in range(3):
            along = .30+j*.23
            fork = (start[0]+(tip[0]-start[0])*along,
                    start[1]+(tip[1]-start[1])*along)
            end = (fork[0]+side*reach*rng.uniform(.12, .25),
                   fork[1]+height*rng.uniform(-.11, .08))
            pygame.draw.line(canvas, axis, fork, end, 1)
            cluster(end)
    cluster(rachis[-1])
    return canvas
