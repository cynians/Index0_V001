"""Project a pixel blade onto its authored plane, without meshes."""
import math

import numpy as np
import pygame

AQUATIC_ROSETTE_VERSION = 1


def metric_blade_bounds(position, frame, length):
    """Conservative base-attached lamina rectangle in metres."""
    return [tuple(position[a]+frame['forward'][a]*length*t
                  +frame['right'][a]*frame['width_m']*.5*side for a in range(3))
            for t in (-.15,1.1) for side in (-1,1)]


def draw_floating_leaf(screen, surface, camera, position, forward, diameter_m, anchor):
    """Project an authored blade on the horizontal water surface."""
    return draw_planar_leaf(screen, surface, camera, position,
                            (forward[0], forward[1], 0.), (0., 0., 1.), diameter_m, anchor)


def draw_planar_leaf(screen, surface, camera, position, forward, normal, diameter_m, anchor, width_m=None):
    """Nearest-neighbour affine projection of a flat authored lamina.

    An edge-on view collapses the blade to a thin rim. Other views retain
    the notch and veins. Metric size refers to the painted
    extent, so transparent canvas margins never enlarge the leaf.
    """
    bounds = surface.get_bounding_rect()
    if (not bounds.width or not bounds.height or not math.isfinite(diameter_m)
            or diameter_m <= 0):
        return
    original_size = surface.get_size()
    source = surface.subsurface(bounds)
    attachment = [anchor[i] * original_size[i] - (bounds.x, bounds.y)[i] for i in range(2)]
    forward = np.asarray(forward, dtype=float)
    normal = np.asarray(normal, dtype=float)
    if forward.shape != (3,) or normal.shape != (3,) or not np.all(np.isfinite([forward, normal])):
        return
    length = float(np.linalg.norm(forward))
    if not math.isfinite(length) or length < 1e-9:
        return
    forward = forward / length
    right = np.cross(normal, forward)
    width = float(np.linalg.norm(right))
    if width < 1e-9:
        return
    right = right / width
    def project(point):
        if hasattr(camera, "world_to_screen_3d"):
            return camera.world_to_screen_3d(point)
        from simulations.species.species_simulation import SCREEN_DEPTH_PROJECTION
        # Diagnostic cameras project z-up directly. The normal application
        # camera has a screen-down y axis, as SpeciesRenderer._screen does.
        return camera.world_to_screen((point[0] + point[1] * SCREEN_DEPTH_PROJECTION, -point[2]))
    origin = np.asarray(project(position), dtype=float)
    metres_per_pixel = diameter_m / max(bounds.width, bounds.height)
    metric_axes = (metres_per_pixel,metres_per_pixel)
    if width_m is not None:
        if not math.isfinite(width_m) or width_m<=0:
            return
        metric_axes = (width_m/bounds.width,diameter_m/bounds.height)
    # Source rows run downwards, opposite to the authored base-to-tip axis.
    basis = []
    for vector,axis_scale in zip((right, -forward),metric_axes):
        endpoint = [position[i] + vector[i] for i in range(3)]
        basis.append((np.asarray(project(endpoint)) - origin) * axis_scale)
    matrix = np.column_stack(basis)
    corners = [origin + matrix @ (np.asarray(point) - attachment)
               for point in ((0, 0), (bounds.width, 0), (0, bounds.height), bounds.size)]
    if abs(np.linalg.det(matrix)) < 1e-5:
        # Only the lamina edge is visible from this elevation. Two screen
        # pixels are a visibility cue, not a measured blade thickness.
        start = min(corners, key=lambda p: p[0])
        end = max(corners, key=lambda p: p[0])
        colors = pygame.surfarray.array3d(source)
        alpha = pygame.surfarray.array_alpha(source) > 0
        color = tuple(np.mean(colors[alpha], axis=0).astype(int))
        pygame.draw.line(screen, color, start, end, 2)
        return
    lower = np.floor(np.min(corners, axis=0)).astype(int)
    upper = np.ceil(np.max(corners, axis=0)).astype(int)
    # Clip before allocating: extreme zoom must not allocate huge surfaces.
    lower = np.maximum(lower, (0, 0))
    upper = np.minimum(upper, screen.get_size())
    size = upper - lower
    if np.any(size <= 0):
        return
    x, y = np.meshgrid(np.arange(size[0]), np.arange(size[1]), indexing="ij")
    target = np.stack((x + lower[0] + .5, y + lower[1] + .5), axis=-1)
    uv = (target - origin) @ np.linalg.inv(matrix).T + attachment
    uv = np.floor(uv).astype(int)
    valid = ((uv[..., 0] >= 0) & (uv[..., 0] < bounds.width) &
             (uv[..., 1] >= 0) & (uv[..., 1] < bounds.height))
    sx = np.clip(uv[..., 0], 0, bounds.width - 1)
    sy = np.clip(uv[..., 1], 0, bounds.height - 1)
    projected = pygame.Surface(tuple(size), pygame.SRCALPHA)
    pixels = pygame.surfarray.pixels3d(projected)
    pixels[:] = pygame.surfarray.array3d(source)[sx, sy]
    del pixels
    alpha = pygame.surfarray.pixels_alpha(projected)
    alpha[:] = pygame.surfarray.array_alpha(source)[sx, sy] * valid
    del alpha
    screen.blit(projected, tuple(lower))
