"""Rounded heads of separate tubular flowers; display units, not seed yields."""
import math


def umbellate_head_profile(value):
    if not isinstance(value, dict) or value.get("unit") != "individual_flower":
        return None
    ranges = {"length_m": (.005, .12), "width_m": (.005, .12),
              "flower_size_m": (.001, .025), "tube_length_m": (.002, .05),
              "fruit_size_m": (.001, .025)}
    for key, (low, high) in ranges.items():
        n = value.get(key)
        if isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) or not low <= n <= high:
            return None
    if (2*value["tube_length_m"]+value["flower_size_m"] > value["width_m"]
            or 2*value["tube_length_m"]+value["flower_size_m"] > value["length_m"]
            or value["fruit_size_m"] > min(value["length_m"], value["width_m"])):
        return None
    count = value.get("flower_count")
    if isinstance(count, bool) or not isinstance(count, int) or not 3 <= count <= 64:
        return None
    colors = {}
    for key in ("axis_color", "tube_color", "flower_color", "unripe_color", "ripe_color"):
        color = value.get(key)
        if (not isinstance(color, (list, tuple)) or len(color) != 3
                or any(isinstance(c, bool) or not isinstance(c, int) or not 0 <= c <= 255 for c in color)):
            return None
        colors[key] = list(color)
    return {"form": "umbellate_head", "unit": "individual_flower", "version": 1,
            **{k: float(value[k]) for k in ranges}, **colors, "flower_count": count,
            "status": str(value.get("status") or "qualitative_head_display")}


def head_units(profile):
    """Deterministic spherical tube tips around the common floral junction."""
    for i in range(profile["flower_count"]):
        z = -1 + 2*(i+.5)/profile["flower_count"]
        radius = math.sqrt(1-z*z)
        angle = i*2.399963229728653
        length = profile["tube_length_m"]
        yield (math.cos(angle)*radius*length, math.sin(angle)*radius*length, z*length)


def umbellate_head_surface(profile, ppm, flower_surface=None, *, fruit=False, ripeness=1.):
    """Compose measured tubes and corolla limbs; fruits use a labelled proxy.

    A reproductive placement denotes one display head. Sampling its members
    creates no additional ecological organs or claims about fecundity.
    """
    import pygame
    from simulations.species.inflorescences import _area_resample
    ppm = max(.01, min(float(ppm), 1000/max(profile["length_m"], profile["width_m"])))
    res = min(24000., 1000/max(profile["length_m"], profile["width_m"]), max(1600., ppm*4))
    w = math.ceil(profile["width_m"]*res)+4
    h = math.ceil(profile["length_m"]*res)+4
    canvas = pygame.Surface((w, h), pygame.SRCALPHA)
    anchor = hub = (w/2, h/2)
    for side in (-1, 1):
        pygame.draw.line(canvas, profile["axis_color"], hub,
                         (round(hub[0]+side*.002*res),round(hub[1]+.004*res)), max(1,round(.0007*res)))
    glyph = None
    if flower_surface is not None and not fruit:
        box = flower_surface.get_bounding_rect()
        if box.width and box.height:
            size = max(1, round(profile["flower_size_m"]*res))
            glyph = pygame.transform.scale(flower_surface.subsurface(box), (size, size))
    for i, (x, y, z) in sorted(enumerate(head_units(profile)), key=lambda item: item[1][1]):
        if fruit:
            # Mature anthocarps remain at the basal cluster, after the long
            # perianth tubes disappear. This is an unverified silhouette fit.
            ratio = profile["fruit_size_m"]*.5/profile["tube_length_m"]
            x, y, z = x*ratio, y*ratio, z*ratio
        point = (round(hub[0]+(x+y*.25)*res), round(hub[1]-(z-y*.15)*res))
        color = profile["tube_color"]
        if fruit:
            ripeness = max(0., min(1., float(ripeness)))
            color = tuple(round(a+(b-a)*ripeness) for a,b in zip(profile["unripe_color"], profile["ripe_color"]))
        pygame.draw.line(canvas, color, hub, point, max(1, round(res*(.0007 if fruit else .0012))))
        if fruit:
            size = profile["fruit_size_m"]*res
            # Beaked, winged outline interpreted from the flora description;
            # no species photograph or authored fruit bitmap is claimed.
            cx, cy = point
            vertices = [(cx,cy-size*.55),(cx+size*.14,cy-size*.18),
                        (cx+size*.45,cy-size*.18),(cx+size*.4,cy+size*.32),
                        (cx,cy+size*.45),(cx-size*.4,cy+size*.32),
                        (cx-size*.45,cy-size*.18),(cx-size*.14,cy-size*.18)]
            pygame.draw.polygon(canvas,color,vertices)
            pygame.draw.line(canvas,profile["ripe_color"],(cx,cy-size*.35),(cx,cy+size*.35),1)
        elif glyph is not None:
            sprite = pygame.transform.rotate(glyph, (i*137.5)%360)
            canvas.blit(sprite, sprite.get_rect(center=point))
        else:
            radius = max(1, round(profile["flower_size_m"]*res*.26))
            for petal in range(5):
                a = petal*math.tau/5
                p = (round(point[0]+math.cos(a)*radius),round(point[1]+math.sin(a)*radius))
                pygame.draw.circle(canvas,profile["flower_color"],p,radius)
    target = (max(1, round(w*ppm/res)), max(1, round(h*ppm/res)))
    return _area_resample(canvas,target), (anchor[0]*target[0]/w, anchor[1]*target[1]/h)
