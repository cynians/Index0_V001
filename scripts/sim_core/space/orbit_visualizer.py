import pygame


def draw_orbit(screen, camera, orbit, color=(120, 120, 120), width=1, points=120):

    if orbit is None or not hasattr(orbit, "get_path_points"):
        return

    world_points = orbit.get_path_points(points)

    screen_points = []

    for p in world_points:

        screen_pos = camera.world_to_screen(p)

        # skip invalid projections
        if screen_pos is None:
            continue

        screen_points.append(screen_pos)

    if len(screen_points) > 2:
        pygame.draw.lines(screen, color, True, screen_points, width)