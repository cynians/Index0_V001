"""Portable panicle display recipes; florets never become ecological organs.

Dimensions are metres. Counts, the bloom band and phase progression are
qualitative display controls, not predictions of flower number or dates.
"""
from __future__ import annotations

import math


def inflorescence_profile(value):
    """Reject incomplete or ambiguous recipes without altering legacy plants."""
    if isinstance(value, dict) and value.get("form") == "umbellate_head":
        from simulations.species.umbellate_heads import umbellate_head_profile
        return umbellate_head_profile(value)
    if isinstance(value, dict) and value.get("form") == "raceme":
        from simulations.species.racemes import raceme_profile
        return raceme_profile(value)
    if isinstance(value, dict) and value.get("form") == "capitulum_cluster":
        from simulations.species.capitulum_clusters import capitulum_cluster_profile
        return capitulum_cluster_profile(value)
    if isinstance(value,dict) and value.get("form") == "compound_umbel":
        from simulations.species.compound_umbels import compound_umbel_profile
        return compound_umbel_profile(value)
    if not isinstance(value, dict) or value.get("unit") != "individual_flower":
        return None
    keys = ("length_m", "width_m", "flower_size_m", "opening_diameter_m", "open_band_fraction")
    if any(isinstance(value.get(k), bool) or not isinstance(value.get(k), (int, float))
           or not math.isfinite(value[k]) for k in keys):
        return None
    if not (0.005 <= value["length_m"] <= 2
            and 0 < value["flower_size_m"] <= value["width_m"] <= value["length_m"]
            and 0 < value["opening_diameter_m"] <= value["flower_size_m"]
            and .05 <= value["open_band_fraction"] <= 1):
        return None
    count = value.get("display_floret_count")
    sequence = value.get("opening_sequence")
    if (not isinstance(count, int) or isinstance(count, bool) or not 3 <= count <= 512
            or sequence not in {"base_to_tip", "tip_to_base"}):
        return None
    result = {k: float(value[k]) for k in keys}
    for key in ("axis_color", "bud_color", "spent_color", "flower_color", "eye_color"):
        color = value.get(key)
        if not (isinstance(color, (tuple, list)) and len(color) == 3
                and all(isinstance(c, int) and not isinstance(c, bool) and 0 <= c <= 255 for c in color)):
            return None
        result[key] = list(color)
    result.update(unit="individual_flower", display_floret_count=count,
                  opening_sequence=sequence, version=1,
                  status=str(value.get("status") or "qualitative_display_recipe"))
    for key in ("axis_curvature", "bloom_sag"):
        number = value.get(key)
        if (isinstance(number, (int, float)) and not isinstance(number, bool)
                and math.isfinite(number) and 0 < number <= 1):
            result[key] = float(number)
            result["version"] = 2
    facing = value.get("front_facing_fraction")
    if (isinstance(facing,(int,float)) and not isinstance(facing,bool)
            and math.isfinite(facing) and 0 < facing <= 1):
        result["front_facing_fraction"] = float(facing)
        lobes = value.get("corolla_lobes")
        if isinstance(lobes,int) and not isinstance(lobes,bool) and 3 <= lobes <= 8:
            result["corolla_lobes"] = lobes
        result["version"] = 3
    return result


def bloom_progress(growth, age_days):
    """Use existing model phase timing, or an explicitly authored season."""
    seasonal = growth.get("reproductive_profile")
    if seasonal and growth.get("life_history", {}).get("class") == "perennial":
        phase = (age_days / seasonal["cycle_days"]) % 1
        start, end = seasonal["flowering_start"], seasonal["flowering_end"]
    else:
        history = growth.get("life_history", {})
        phase = age_days
        start = history.get("reproductive_start_days", 0)
        end = history.get("senescence_start_days", start + 1)
    return max(0., min(1., (phase-start) / max(1e-6, end-start)))


def floret_stage(profile, axial_fraction, progress):
    """Advance each floret monotonically bud -> open -> spent."""
    t = axial_fraction if profile["opening_sequence"] == "base_to_tip" else 1-axial_fraction
    band = profile["open_band_fraction"]
    front = max(0., min(1., progress)) * (1+band)
    return "bud" if t >= front else "spent" if t < front-band else "open"


def floret_layout(profile):
    """Short cyme-like tiers on a tapering axis, inside measured dimensions."""
    count = profile["display_floret_count"]
    length, width = profile["length_m"], profile["width_m"]
    # The circumscribed square keeps rotated corollas inside the envelope.
    extent = min(profile["flower_size_m"] * math.sqrt(2), width)
    margin = min(extent / 2, length * .15)
    for i in range(count):
        t = (i + .5) / count
        # Several florets share each short side branch; golden angle breaks
        # perfect horizontal stripes without random state or a species key.
        angle = i * 2.399963229728653
        radius = max(0., (width-extent)/2) * (1-t)**.55
        radius *= .5 + .5 * ((i % 5)/4)
        yield t, math.sin(angle)*radius, margin+t*(length-2*margin)


def panicle_axis_points(profile, progress, rotation=0.):
    """Constant-length curved rachis in screen-plane metres (positive y down).

    Sag follows projected gravity, independently of the supporting shoot's
    inclination. Bloom load is a labelled visual envelope, not flower mass.
    """
    theta = math.radians(-90-rotation)
    difference = (math.pi/2-theta+math.pi) % (2*math.pi)-math.pi
    side = 1 if math.cos(theta) >= 0 else -1
    if abs(abs(difference)-math.pi) < 1e-9:
        difference = side*math.pi
    load = .15+.85*math.sin(math.pi*max(0.,min(1.,progress)))
    def tangent(t):
        return (theta+side*profile.get("axis_curvature",0)*.45*t
                + difference*profile.get("bloom_sag",0)*load*t**1.6)
    x = y = 0.
    points = [(x,y,tangent(0.))]
    step = profile["length_m"]/64
    for i in range(64):
        angle = tangent((i+.5)/64)
        x += math.cos(angle)*step; y += math.sin(angle)*step
        points.append((x,y,tangent((i+1)/64)))
    return points


def _axis_frame(points, fraction):
    u = max(0.,min(1.,fraction))*(len(points)-1)
    i = min(len(points)-2,int(u)); f = u-i
    return tuple(a+(b-a)*f for a,b in zip(points[i],points[i+1]))


def _area_resample(surface, size):
    """Filter coverage once, preserving colour beside transparent pixels."""
    import pygame
    filtered = pygame.transform.smoothscale(surface.premul_alpha(),size)
    for y in range(filtered.get_height()):
        for x in range(filtered.get_width()):
            r,g,b,a = filtered.get_at((x,y))
            if a:
                filtered.set_at((x,y),(min(255,round(r*255/a)),min(255,round(g*255/a)),
                                       min(255,round(b*255/a)),a))
    return filtered


def panicle_surface(profile, pixels_per_meter, progress, flower_surface=None, rotation=0., _sampled=False):
    """Compose one bounded display surface, optionally reusing a flower asset."""
    import pygame

    curved = bool(profile.get("axis_curvature") or profile.get("bloom_sag"))
    extent_m = profile["length_m"] + (profile["width_m"] if curved else 0)
    ppm = min(1024 / extent_m, max(1., pixels_per_meter))
    facing = profile.get("front_facing_fraction",0)
    if facing and not _sampled and ppm < 600:
        # Compose subpixel corollas first, then filter the complete head.
        # This preserves projected petal coverage without a size multiplier.
        sampling = min(4.,1024/(extent_m*ppm))
        if sampling > 1.01:
            large,anchor = panicle_surface(profile,ppm*sampling,progress,flower_surface,rotation,True)
            size = tuple(max(1,round(n/sampling)) for n in large.get_size())
            return _area_resample(large,size),tuple(v/sampling for v in anchor)
    height = max(2, round(profile["length_m"] * ppm))
    width = max(2, round(profile["width_m"] * ppm))
    if curved:
        axis = panicle_axis_points(profile,progress,rotation)
        margin = profile["width_m"]/2
        left = min(p[0] for p in axis)-margin
        top = min(p[1] for p in axis)-margin
        right = max(p[0] for p in axis)+margin
        bottom = max(p[1] for p in axis)+margin
        canvas = pygame.Surface((max(2,math.ceil((right-left)*ppm))+4,
                                 max(2,math.ceil((bottom-top)*ppm))+4),pygame.SRCALPHA)
        center,base = 2-left*ppm,2-top*ppm
        path = [(round(center+x*ppm),round(base+y*ppm)) for x,y,_ in axis]
    else:
        axis = None
        canvas = pygame.Surface((width+4,height+4),pygame.SRCALPHA)
        center,base = (width+4)//2,height+2
        path = [(center,base),(center,2)]
    pygame.draw.lines(canvas,profile["axis_color"],False,path,max(1,round(ppm*.0008)))
    glyph = None
    if flower_surface is not None:
        bounds = flower_surface.get_bounding_rect()
        if bounds.width and bounds.height:
            source = flower_surface.subsurface(bounds)
            extent = min(profile["flower_size_m"], profile["width_m"]/math.sqrt(2))*ppm
            longest = max(source.get_size())
            # At whole-plant scale nearest-neighbour sampling can select
            # only the orange eye of a lilac flower. Area downsampling
            # preserves the corolla's overall colour in a one-pixel floret.
            resize = pygame.transform.smoothscale if extent <= 4 else pygame.transform.scale
            glyph = resize(source, (
                max(1, round(extent*source.get_width()/longest)),
                max(1, round(extent*source.get_height()/longest)),
            ))
    radius = max(1, round(profile["opening_diameter_m"] * ppm / 2))
    rotated_glyphs = {}
    closed_glyphs = {}
    for i, (t, x, z) in enumerate(floret_layout(profile)):
        if axis:
            ax,ay,theta = _axis_frame(axis,z/profile["length_m"])
            pos = (round(center+(ax-math.sin(theta)*x)*ppm),
                   round(base+(ay+math.cos(theta)*x)*ppm))
            stem = (round(center+ax*ppm),round(base+ay*ppm))
        else:
            theta = -math.pi/2
            pos = (round(center+x*ppm),round(base-z*ppm))
            stem = (center,pos[1])
        pygame.draw.line(canvas, profile["axis_color"], stem, pos, 1)
        stage = floret_stage(profile, t, progress)
        angle = round((60 if x < 0 else -60)+(i % 5-2)*12-math.degrees(theta+math.pi/2))
        face_on = (i*.61803398875)%1 < facing
        if stage == "open" and face_on:
            # A corolla facing the viewer presents its opening rather than
            # the full tube length. Fraction/orientation are visual fits.
            opening = profile["opening_diameter_m"]*ppm
            lobes = profile.get("corolla_lobes",0)
            if lobes:
                for lobe in range(lobes):
                    a = lobe*2*math.pi/lobes+math.radians(angle)
                    petal = (round(pos[0]+math.cos(a)*opening*.2),
                             round(pos[1]+math.sin(a)*opening*.2))
                    pygame.draw.circle(canvas,profile["flower_color"],petal,max(1,round(opening*.3)))
            else:
                pygame.draw.circle(canvas,profile["flower_color"],pos,max(1,round(opening/2)))
            if opening >= 4:
                pygame.draw.circle(canvas,profile["eye_color"],pos,max(1,round(opening*.15)))
        elif stage == "open" and glyph is not None:
            # Short cymes face outward, with some flowers facing the viewer.
            # Reuse the authored corolla rather than baking a whole panicle.
            if angle not in rotated_glyphs:
                rotated_glyphs[angle] = pygame.transform.rotate(glyph, angle)
            floret = rotated_glyphs[angle]
            canvas.blit(floret, floret.get_rect(center=pos))
        elif stage == "open":
            pygame.draw.circle(canvas, profile["flower_color"], pos, radius)
            if radius >= 2:
                pygame.draw.circle(canvas, profile["eye_color"], pos, max(1, radius//3))
        else:
            color = profile["bud_color"] if stage == "bud" else profile["spent_color"]
            # Closed tubes and shrunken spent corollas occupy the same
            # short cymes. These size fractions are display fits only.
            closed_key = (stage, angle)
            if closed_key not in closed_glyphs:
                h = max(1, round(profile["flower_size_m"]*ppm*(.65 if stage == "bud" else .45)))
                w = max(1, round(profile["opening_diameter_m"]*ppm*.55))
                closed = pygame.Surface((w,h), pygame.SRCALPHA)
                pygame.draw.ellipse(closed, color, closed.get_rect())
                closed_glyphs[closed_key] = pygame.transform.rotate(closed,angle)
            closed = closed_glyphs[closed_key]
            canvas.blit(closed,closed.get_rect(center=pos))
    return canvas, (center, base)
