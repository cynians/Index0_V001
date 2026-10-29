"""Small stalked-flower racemes, composed from a single-flower pixel asset.

These are display units at existing reproductive sockets, not additional
ecological organs. Axis/pedicel dimensions are explicit visual calibrations.
"""
import math

RACEME_DISPLAY_VERSION = 1


def raceme_profile(value):
    if not isinstance(value, dict) or value.get("form") != "raceme":
        return None
    count = value.get("display_floret_count")
    if isinstance(count, bool) or not isinstance(count, int) or not 3 <= count <= 70:
        return None
    bounds = {"length_m": (.015, 1.), "pedicel_length_m": (.001, .15),
              "flower_size_m": (.002, .15)}
    for key, (lower, upper) in bounds.items():
        number = value.get(key)
        if (isinstance(number, bool) or not isinstance(number, (int, float))
                or not math.isfinite(number) or not lower <= number <= upper):
            return None
    if value["flower_size_m"] > value["length_m"] or value.get("unit") != "individual_flower":
        return None
    orientation = value.get("flower_orientation", "axis_relative")
    if not isinstance(orientation, str) or orientation not in {"axis_relative", "gravity_upright"}:
        return None
    colors = {}
    for key in ("axis_color", "flower_color", "eye_color"):
        color = value.get(key)
        if (not isinstance(color, (tuple, list)) or len(color) != 3
                or any(isinstance(c, bool) or not isinstance(c, int) or not 0 <= c <= 255 for c in color)):
            return None
        colors[key] = list(color)
    return {"form": "raceme", "unit": "individual_flower",
            "display_floret_count": count, **{k: float(value[k]) for k in bounds},
            "width_m": 2 * value["pedicel_length_m"] + value["flower_size_m"],
            **colors, "version": RACEME_DISPLAY_VERSION,
            **({"flower_orientation": orientation} if orientation == "gravity_upright" else {}),
            "status": str(value.get("status") or "qualitative_display_recipe")}


def raceme_layout(profile):
    """Alternating stalked flowers along one axis; the last is distal."""
    count = profile["display_floret_count"]
    for i in range(count):
        t = (i + 1) / count
        x = 0. if i == count - 1 else (-1 if i % 2 else 1) * profile["pedicel_length_m"]
        yield x, profile["length_m"] * t


def raceme_surface(profile, pixels_per_meter, flower_surface=None, rotation=0.):
    """Compose at physical size; supersample small corollas without enlarging them."""
    import pygame
    from simulations.species.inflorescences import _area_resample
    try:
        ppm = float(pixels_per_meter)
    except (TypeError, ValueError):
        ppm = 1.
    if not math.isfinite(ppm):
        ppm = 1.
    extent_x = profile["width_m"]
    extent_y = profile["length_m"] + profile["flower_size_m"] / 2
    ppm = max(1., min(ppm, 512. / max(extent_x, extent_y)))
    sampling = min(4., 1024. / (max(extent_x, extent_y) * ppm))
    draw_ppm = ppm * sampling
    width, height = max(2, math.ceil(extent_x * draw_ppm)), max(2, math.ceil(extent_y * draw_ppm))
    canvas = pygame.Surface((width + 4, height + 4), pygame.SRCALPHA)
    anchor = ((width + 4) / 2, height + 2)
    pixel = lambda x, z: (round(anchor[0] + x * draw_ppm), round(anchor[1] - z * draw_ppm))
    pygame.draw.line(canvas, profile["axis_color"], pixel(0, 0), pixel(0, profile["length_m"]),
                     max(1, round(.0008 * draw_ppm)))
    glyph = None
    if flower_surface is not None:
        box = flower_surface.get_bounding_rect()
        if box.width and box.height:
            source = flower_surface.subsurface(box)
            extent = profile["flower_size_m"] * draw_ppm
            longest = max(source.get_size())
            dimensions = tuple(max(1, round(extent * n / longest)) for n in source.get_size())
            glyph = (pygame.transform.smoothscale(source, dimensions) if extent <= 4
                     else pygame.transform.scale(source, dimensions))
            if profile.get("flower_orientation") == "gravity_upright":
                # The renderer rotates the whole inflorescence after composing
                # it. Counter-rotate individual corollas so a hanging axis does
                # not put a pea flower's banner below its keel.
                glyph = pygame.transform.rotate(glyph, -float(rotation))
    for x, z in raceme_layout(profile):
        pos = pixel(x, z)
        pygame.draw.line(canvas, profile["axis_color"], pixel(0, z), pos,
                         max(1, round(.0005 * draw_ppm)))
        if glyph is not None:
            canvas.blit(glyph, glyph.get_rect(center=pos))
        else:
            radius = max(1, round(profile["flower_size_m"] * draw_ppm / 2))
            pygame.draw.circle(canvas, profile["flower_color"], pos, radius)
            if radius >= 3:
                pygame.draw.circle(canvas, profile["eye_color"], pos, max(1, radius // 4))
    size = tuple(max(2, round(n / sampling)) for n in canvas.get_size())
    # Rounded output dimensions can differ from an exact 1/sampling ratio.
    # Carry the attachment through the actual resample so it remains inside.
    return _area_resample(canvas, size), tuple(
        v * target / source for v, target, source in zip(anchor, size, canvas.get_size()))
