import pygame

from simulations.space.orbit_visualizer import draw_orbit


class Renderer:
    """
    Handles all rendering.

    Responsibilities:
    * dispatch rendering by simulation render mode
    * draw world objects
    * draw UI overlays
    """

    def __init__(self, simulation):
        self.sim = simulation
        self.simulation = None
        self.screen = None

    # --------------------------------------------------
    # MAIN ENTRY
    # --------------------------------------------------

    def draw(self, screen):
        if self.simulation is None:
            return

        self.screen = screen

        self.draw_world()
        self.draw_ui()

    # --------------------------------------------------
    # WORLD DRAW
    # --------------------------------------------------

    def draw_world(self):
        sim = self.simulation
        render_mode = getattr(sim, "render_mode", None)

        if render_mode == "bioregion":
            self.draw_bioregion_simulation(sim)
            return

        if render_mode == "map":
            self.draw_map_simulation(sim)
            return

        if render_mode == "space":
            self.draw_space_simulation(sim)
            return

        if hasattr(sim, "system"):
            self.draw_space_simulation(sim)
            return

        if hasattr(sim, "get_layers"):
            self.draw_map_simulation(sim)
            return

    def _draw_bioregion_cell_highlight(self, camera, cell, color, border_width):
        """
        Draw a subsection-cell outline highlight.
        """
        top_left = camera.world_to_screen((cell["min_x"], cell["min_y"]))
        bottom_right = camera.world_to_screen((cell["max_x"], cell["max_y"]))

        if top_left is None or bottom_right is None:
            return

        left = min(top_left[0], bottom_right[0])
        right = max(top_left[0], bottom_right[0])
        top = min(top_left[1], bottom_right[1])
        bottom = max(top_left[1], bottom_right[1])

        rect = pygame.Rect(left, top, right - left, bottom - top)
        pygame.draw.rect(self.screen, color, rect, border_width)
    def draw_bioregion_simulation(self, sim):
        """
        Draw the prototype bioregion test grid.

        Rendering rules for the first prototype slice:
        * dark map background
        * thin subsection grid
        * thicker section grid
        * hover highlight
        * selected-cell highlight
        """
        view = self.sim
        camera = view.camera

        bounds = sim.bounds
        top_left = camera.world_to_screen((bounds["min_x"], bounds["min_y"]))
        bottom_right = camera.world_to_screen((bounds["max_x"], bounds["max_y"]))

        if top_left is not None and bottom_right is not None:
            left = min(top_left[0], bottom_right[0])
            right = max(top_left[0], bottom_right[0])
            top = min(top_left[1], bottom_right[1])
            bottom = max(top_left[1], bottom_right[1])

            background_rect = pygame.Rect(left, top, right - left, bottom - top)
            pygame.draw.rect(self.screen, (20, 26, 20), background_rect)

        subsection_size = sim.get_subsection_size()
        section_size = sim.get_section_size()
        map_size = sim.get_map_size()

        subsection_color = (52, 72, 52)
        section_color = (165, 185, 165)

        subsection_steps = int(map_size // subsection_size)
        section_steps = int(map_size // section_size)

        for i in range(subsection_steps + 1):
            x = i * subsection_size

            p1 = camera.world_to_screen((x, 0.0))
            p2 = camera.world_to_screen((x, map_size))
            if p1 is not None and p2 is not None:
                pygame.draw.line(self.screen, subsection_color, p1, p2, 1)

        for i in range(subsection_steps + 1):
            y = i * subsection_size

            p1 = camera.world_to_screen((0.0, y))
            p2 = camera.world_to_screen((map_size, y))
            if p1 is not None and p2 is not None:
                pygame.draw.line(self.screen, subsection_color, p1, p2, 1)

        for i in range(section_steps + 1):
            x = i * section_size

            p1 = camera.world_to_screen((x, 0.0))
            p2 = camera.world_to_screen((x, map_size))
            if p1 is not None and p2 is not None:
                pygame.draw.line(self.screen, section_color, p1, p2, 2)

        for i in range(section_steps + 1):
            y = i * section_size

            p1 = camera.world_to_screen((0.0, y))
            p2 = camera.world_to_screen((map_size, y))
            if p1 is not None and p2 is not None:
                pygame.draw.line(self.screen, section_color, p1, p2, 2)

        hover_cell = getattr(sim, "hover_cell", None)
        if hover_cell is not None:
            self._draw_bioregion_cell_highlight(
                camera=camera,
                cell=hover_cell,
                color=(120, 220, 255),
                border_width=2,
            )

        selected_cell = getattr(sim, "selected_cell", None)
        if selected_cell is not None:
            self._draw_bioregion_cell_highlight(
                camera=camera,
                cell=selected_cell,
                color=(255, 230, 120),
                border_width=3,
            )

    def draw_map_simulation(self, sim):
        view = self.sim
        camera = view.camera
        selected_entity_id = getattr(sim, "selected_entity_id", None)
        hover_entity_id = getattr(sim, "hover_entity_id", None)

        for layer in sim.get_layers():
            center = camera.world_to_screen((layer["x"], layer["y"]))

            if center is None:
                continue

            shape = layer.get("shape", "marker")
            entity_id = layer.get("entity_id")
            is_selected = entity_id == selected_entity_id
            is_hovered = entity_id == hover_entity_id

            if shape in ("map_rect", "rect"):
                pixel_w = max(6, int(layer.get("width_world", 1) * camera.zoom))
                pixel_h = max(6, int(layer.get("height_world", 1) * camera.zoom))

                rect = pygame.Rect(
                    int(center[0] - pixel_w / 2),
                    int(center[1] - pixel_h / 2),
                    pixel_w,
                    pixel_h,
                )

                if (
                    rect.right < 0
                    or rect.left > view.width
                    or rect.bottom < 0
                    or rect.top > view.height
                ):
                    continue

                pygame.draw.rect(self.screen, layer["color"], rect)

                if shape == "map_rect":
                    pygame.draw.rect(self.screen, (220, 220, 220), rect, 3)

                    pygame.draw.line(
                        self.screen,
                        (110, 125, 150),
                        (rect.x, rect.centery),
                        (rect.right, rect.centery),
                        1,
                    )
                    pygame.draw.line(
                        self.screen,
                        (110, 125, 150),
                        (rect.centerx, rect.y),
                        (rect.centerx, rect.bottom),
                        1,
                    )
                else:
                    pygame.draw.rect(self.screen, (220, 220, 220), rect, 2)

                if is_hovered and not is_selected:
                    hover_rect = rect.inflate(6, 6)
                    pygame.draw.rect(self.screen, (120, 220, 255), hover_rect, 2)

                if is_selected:
                    highlight_rect = rect.inflate(8, 8)
                    pygame.draw.rect(self.screen, (255, 230, 120), highlight_rect, 3)

                if rect.width >= 80 and rect.height >= 28:
                    text = view.default_font.render(
                        layer.get("name", "layer"),
                        True,
                        (240, 240, 240)
                    )
                    self.screen.blit(text, (rect.x + 6, rect.y + 6))

                continue

            pixel_size = max(6, int(layer.get("min_screen_size", 8)))

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

            pygame.draw.rect(self.screen, layer["color"], rect)
            pygame.draw.rect(self.screen, (220, 220, 220), rect, 2)

            if is_hovered and not is_selected:
                hover_rect = rect.inflate(8, 8)
                pygame.draw.rect(self.screen, (120, 220, 255), hover_rect, 2)

            if is_selected:
                highlight_rect = rect.inflate(10, 10)
                pygame.draw.rect(self.screen, (255, 230, 120), highlight_rect, 3)

            text = view.default_font.render(
                layer.get("name", "layer"),
                True,
                (240, 240, 240)
            )
            self.screen.blit(text, (rect.x + 8, rect.y - 2))

    def draw_space_simulation(self, sim):
        view = self.sim
        camera = view.camera

        ROOT_ONLY_LABEL_ZOOM = 2.5e-10
        ALL_CHILDREN_LABEL_ZOOM = 2.0e-9

        for body in sim.system.get_entries():
            obj = body["object"]
            orbit = getattr(obj, "orbit", None)

            if orbit is None:
                continue

            draw_orbit(self.screen, camera, orbit)

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

                pygame.draw.rect(self.screen, layer["color"], rect)
                pygame.draw.rect(self.screen, (220, 220, 220), rect, 2)

                body_rect = rect
                body_pixel_size = max(body_pixel_size, pixel_size)

                if rect.width >= 60 and rect.height >= 24:
                    text = view.default_font.render(
                        f"{body['name']} : {layer['name']}",
                        True,
                        (240, 240, 240)
                    )
                    self.screen.blit(text, (rect.x + 6, rect.y + 6))

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
            elif camera.zoom < ROOT_ONLY_LABEL_ZOOM:
                show_label = is_primary_system_member
            elif camera.zoom < ALL_CHILDREN_LABEL_ZOOM:
                show_label = is_primary_system_member
            else:
                show_label = True

            if not show_label:
                continue

            label_anchor = (body_rect.right + 8, body_rect.y - 2)

            label_color = (240, 240, 240)
            if is_subsystem_body and camera.zoom < ALL_CHILDREN_LABEL_ZOOM:
                label_color = (170, 170, 170)

            label = view.default_font.render(
                body["name"],
                True,
                label_color
            )
            self.screen.blit(label, label_anchor)

    # --------------------------------------------------
    # UI DRAW
    # --------------------------------------------------

    def draw_ui(self):
        """
        App/UI chrome now lives in UIManager.
        Renderer no longer draws tab/time/status overlays.
        """
        return