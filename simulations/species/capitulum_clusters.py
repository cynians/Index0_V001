"""Small terminal clusters of heads; display samples are not ecological organs."""
import math


def capitulum_cluster_profile(value):
    if not isinstance(value, dict) or value.get("unit") != "capitulum":
        return None
    keys = ("length_m", "width_m", "head_size_m")
    if any(isinstance(value.get(k), bool) or not isinstance(value.get(k), (int, float))
           or not math.isfinite(value[k]) for k in keys):
        return None
    if not (.002 <= value["head_size_m"] <= min(value["length_m"], value["width_m"])
            and max(value["length_m"], value["width_m"]) <= .2):
        return None
    count = value.get("head_count")
    color = value.get("axis_color")
    layout = value.get("head_layout", "fan")
    size_axis = value.get("head_size_axis", "length")
    if not isinstance(size_axis, str) or size_axis not in {"length", "width"}:
        return None
    if not isinstance(layout, str) or layout not in {"fan", "rounded"}:
        return None
    if (not isinstance(count, int) or isinstance(count, bool) or not 2 <= count <= 12
            or not isinstance(color, (list, tuple)) or len(color) != 3
            or any(not isinstance(c, int) or isinstance(c, bool) or not 0 <= c <= 255 for c in color)):
        return None
    return {**{k: float(value[k]) for k in keys}, "form": "capitulum_cluster",
            "unit": "capitulum", "head_count": count, "axis_color": list(color),
            **({"head_layout": layout} if layout != "fan" else {}),
            **({"head_size_axis": size_axis} if size_axis == "width" else {}),
            "version": 3 if size_axis == "width" else 2 if layout == "rounded" else 1,
            "status": str(value.get("status") or "qualitative_display_recipe")}


def capitulum_cluster_surface(profile, ppm, progress, head_surface=None):
    import pygame
    from simulations.species.inflorescences import _area_resample
    # Supersample tiny heads, then retain coverage at whole-plant scale.
    ppm = min(max(.01, float(ppm)), 1000 / max(profile["width_m"], profile["length_m"]))
    resolution = min(24000., 1000 / max(profile["width_m"], profile["length_m"]),
                     max(1200., ppm * 4))
    w = max(4, math.ceil(profile["width_m"] * resolution) + 4)
    h = max(4, math.ceil(profile["length_m"] * resolution) + 4)
    canvas = pygame.Surface((w, h), pygame.SRCALPHA)
    anchor = (w / 2, h - 2)
    size = max(2, round(profile["head_size_m"] * resolution))
    sprite = None
    if head_surface is not None:
        box = head_surface.get_bounding_rect()
        if box.width and box.height:
            sprite = head_surface.subsurface(box)
            dimensions = ((size, max(1, round(size*box.height/box.width))) if profile.get("head_size_axis") == "width"
                          else (max(1, round(size*box.width/box.height)), size))
            sprite = pygame.transform.scale(sprite, dimensions)
    for i in range(profile["head_count"]):
        t = i / max(1, profile["head_count"] - 1)
        x = 2 + size / 2 + t * max(0, w - 4 - size)
        y = 2 + size / 2 + abs(2*t-1) * max(0, h-size-4) * .28
        if profile.get("head_layout") == "rounded":
            # Independent terminal head samples occupy a rounded envelope;
            # preserve their measured size instead of enlarging one flower.
            angle = i * 2.3999632297
            radius = math.sqrt((i + .5) / profile["head_count"])
            x = w/2 + math.cos(angle)*radius*max(0, (w-size-4)/2)
            y = (h+size)/4 + math.sin(angle)*radius*max(0, (h-size-4)/4)
            junction = (round(anchor[0]+(x-anchor[0])*.38), round(h*.62))
            pygame.draw.lines(canvas, profile["axis_color"], False,
                              [anchor, junction, (round(x), round(y+size*.4))],
                              max(1, round(resolution*.0007)))
        else:
            pygame.draw.line(canvas, profile["axis_color"], anchor, (round(x), round(y+size*.4)),
                             max(1, round(resolution*.0007)))
        if sprite is not None:
            if profile.get("head_size_axis") == "width":
                x = max(sprite.get_width()/2+2, min(w-2-sprite.get_width()/2, x))
                y = max(sprite.get_height()/2+2, min(h-2-sprite.get_height()/2, y))
            canvas.blit(sprite, sprite.get_rect(center=(round(x), round(y))))
        else:
            pygame.draw.ellipse(canvas, (192, 163, 225), (x-size*.3, y-size*.5, size*.6, size))
    target = (max(1, min(1024, round(w*ppm/resolution))),
              max(1, min(1024, round(h*ppm/resolution))))
    return _area_resample(canvas, target), (anchor[0]*target[0]/w, anchor[1]*target[1]/h)
