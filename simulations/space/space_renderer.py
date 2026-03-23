import pygame

from simulations.space.orbit_visualizer import draw_orbit


class SpaceRenderer:
    """
    Handles rendering for space simulations.
    """

    def __init__(self, app_view):
        self.app_view = app_view

    def draw(self, screen, sim):
        view = self.app_view
        camera = view.camera

        root_only_label_zoom = 2.5e-10
        all_children_label_zoom = 2.0e-9

        for body in sim.system.get_entries():
            obj = body["object"]
            orbit = getattr(obj, "orbit", None)

            if orbit is None:
                continue

            draw_orbit(screen, camera, orbit)

        for body in sim.system.get_entries():
            obj = body["object"]
            bx, by = obj.get_position()

            layer_stack = body["layers"]
            layers = layer_stack.get_layers() if layer_stack else []

            body_rect = None
            body_pixel_size = 0

            for layer in layers:
                x = layer["x"] + bx
                y = layer["y"] + by
                size = layer["size"]

                center = camera.world_to_screen((x, y))

                if center is None:
                    continue

                pixel_size = max(1, int(size * camera.zoom))

                rect = pygame.Rect(
                    int(center[0] - pixel_size / 2),
                    int(center[1] - pixel_size / 2),
                    pixel_size,
                    pixel_size,
                )

                if (
                    rect.right < 0
                    or rect.left > view.width
                    or rect.bottom < 0
                    or rect.top > view.height
                ):
                    continue

                pygame.draw.rect(screen, layer["color"], rect)
                pygame.draw.rect(screen, (220, 220, 220), rect, 2)

                body_rect = rect
                body_pixel_size = max(body_pixel_size, pixel_size)

                if rect.width >= 60 and rect.height >= 24:
                    text = view.default_font.render(
                        f"{body['name']} : {layer['name']}",
                        True,
                        (240, 240, 240)
                    )
                    screen.blit(text, (rect.x + 6, rect.y + 6))

            if body_rect is None:
                continue

            orbit = getattr(obj, "orbit", None)
            parent_obj = getattr(orbit, "parent", None) if orbit is not None else None
            grandparent_obj = None

            if parent_obj is not None:
                parent_orbit = getattr(parent_obj, "orbit", None)
                if parent_orbit is not None:
                    grandparent_obj = getattr(parent_orbit, "parent", None)

            is_root_body = orbit is None
            is_primary_system_member = (parent_obj is not None and grandparent_obj is None)
            is_subsystem_body = (parent_obj is not None and grandparent_obj is not None)

            show_label = False

            if is_root_body:
                show_label = True
            elif camera.zoom < root_only_label_zoom:
                show_label = is_primary_system_member
            elif camera.zoom < all_children_label_zoom:
                show_label = is_primary_system_member
            else:
                show_label = True

            if not show_label:
                continue

            label_anchor = (body_rect.right + 8, body_rect.y - 2)

            label_color = (240, 240, 240)
            if is_subsystem_body and camera.zoom < all_children_label_zoom:
                label_color = (170, 170, 170)

            label = view.default_font.render(
                body["name"],
                True,
                label_color
            )
            screen.blit(label, label_anchor)