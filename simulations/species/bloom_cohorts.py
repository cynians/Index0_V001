"""Bounded display samples for a native flower asset on a tree shoot cohort.

These samples resolve represented flowering branchlets optically. They are not
new canonical organs, seed predictions or an empirical flowers-per-leaf model.
"""
import math


def supports_bloom_cohorts(entity):
    return (entity.get("plant_growth_form") == "tree"
            and bool(entity.get("plant_leaf_distribution") or entity.get("leaf_attachment_pattern") == "along_stem")
            and entity.get("plant_reproductive_structure") in {"flower", "capitulum", "panicle"}
            and bool(entity.get("plant_flower_module_ref"))
            and not entity.get("plant_inflorescence_profile"))


def bloom_samples(cluster, density, leaf_length, phase):
    """Stable points in the same 3D shoot volume as the represented foliage."""
    axis = cluster.get("bloom_axis_m")
    if not axis or not (0 < density <= 1 and 0 < phase <= 1):
        return []
    start, end = axis
    estimated = max(1, min(4096, int(cluster.get("estimated_leaf_count", 1))))
    count = max(1, min(128, round(estimated*density*2*phase)))
    azimuth = float(cluster.get("angle", 0))
    spread = min(.6, max(.01, leaf_length) * 1.15 * min(3., math.sqrt(estimated/18.)))
    salt = float(cluster.get("identity", 0)) * .137
    points = []
    for i in range(count):
        t = .10 + .85*(i+.5)/count
        angle = i*2.39996323 + salt
        radius = spread*math.sqrt((i%11+.5)/11.)
        position = [start[j]+(end[j]-start[j])*t for j in range(3)]
        position[0] += math.cos(angle)*radius
        position[1] += math.sin(angle)*radius
        position[2] += math.sin(angle*1.7)*radius*.8
        tilt = .75 + .18*math.sin(angle)
        forward = [math.cos(azimuth+angle*.2)*math.cos(tilt),
                   math.sin(azimuth+angle*.2)*math.cos(tilt), math.sin(tilt)]
        points.append((position, forward))
    return points


def bloom_surface(source, anchor, projected, unit_height_px):
    """Accumulate real-sized units before filtering subpixel bloom coverage.

    ``projected`` contains positions relative to a host origin and rotations.
    Close views retain individual panicles. Extreme zoom falls back to ordinary
    canonical organ rendering rather than allocating unbounded surfaces.
    """
    import pygame
    from simulations.species.inflorescences import _area_resample
    if not projected or unit_height_px <= 0:
        return None
    pad = math.ceil(unit_height_px*1.4)+2
    left = math.floor(min(p[0] for p in projected))-pad
    top = math.floor(min(p[1] for p in projected))-pad
    width = math.ceil(max(p[0] for p in projected))+pad-left+1
    height = math.ceil(max(p[1] for p in projected))+pad-top+1
    if max(width,height) > 1024 or unit_height_px > 512:
        return None
    factor = max(1, min(4, 1024//max(width,height)))
    canvas = pygame.Surface((width*factor,height*factor),pygame.SRCALPHA)
    unit_height = max(1, round(unit_height_px*factor))
    unit_width = max(1, round(unit_height*source.get_width()/source.get_height()))
    unit = _area_resample(source,(unit_width,unit_height)) if unit_height<source.get_height() else pygame.transform.scale(source,(unit_width,unit_height))
    # Compensate when an entire unit is smaller than the internal pixel.
    # A numerical one-pixel floor must not inflate its physical coverage.
    coverage = min(1., (unit_height_px*factor/unit_height)**2)
    if coverage < 1:
        unit.set_alpha(round(255*coverage))
    variants = {}
    for x,y,rotation in projected:
        rotation = round(rotation/15)*15
        if rotation not in variants:
            variants[rotation] = pygame.transform.rotate(unit,rotation)
        sprite = variants[rotation]
        local_anchor = pygame.Vector2((anchor[0]-.5)*unit_width,(anchor[1]-.5)*unit_height).rotate(-rotation)
        center = pygame.Vector2((x-left)*factor,(y-top)*factor)-local_anchor
        canvas.blit(sprite,sprite.get_rect(center=(round(center.x),round(center.y))))
    return _area_resample(canvas,(width,height)), (left,top)
