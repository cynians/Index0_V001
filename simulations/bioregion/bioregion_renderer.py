import pygame


class BioregionRenderer:
    """
    Handles rendering for bioregion simulations.
    """

    def __init__(self, app_view):
        self.app_view = app_view

    def _draw_bioregion_cell_highlight(self, screen, camera, cell, color, border_width):
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
        pygame.draw.rect(screen, color, rect, border_width)

    def _draw_bioregion_height_outlines(self, screen, sim, camera):
        """
        Draw cached contour-like height-outline segments derived from geology.
        """
        outline_segments = []
        if hasattr(sim, "get_height_outline_segments"):
            outline_segments = sim.get_height_outline_segments()

        if not outline_segments:
            return

        outline_color = (210, 230, 210)

        for segment in outline_segments:
            p1 = camera.world_to_screen((segment["x1"], segment["y1"]))
            p2 = camera.world_to_screen((segment["x2"], segment["y2"]))

            if p1 is None or p2 is None:
                continue

            pygame.draw.line(screen, outline_color, p1, p2, 2)

    def draw(self, screen, sim):
        """
        Draw the prototype bioregion test grid.
        """
        view = self.app_view
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
            pygame.draw.rect(screen, (20, 26, 20), background_rect)

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
                pygame.draw.line(screen, subsection_color, p1, p2, 1)

        for i in range(subsection_steps + 1):
            y = i * subsection_size

            p1 = camera.world_to_screen((0.0, y))
            p2 = camera.world_to_screen((map_size, y))
            if p1 is not None and p2 is not None:
                pygame.draw.line(screen, subsection_color, p1, p2, 1)

        for i in range(section_steps + 1):
            x = i * section_size

            p1 = camera.world_to_screen((x, 0.0))
            p2 = camera.world_to_screen((x, map_size))
            if p1 is not None and p2 is not None:
                pygame.draw.line(screen, section_color, p1, p2, 2)

        for i in range(section_steps + 1):
            y = i * section_size

            p1 = camera.world_to_screen((0.0, y))
            p2 = camera.world_to_screen((map_size, y))
            if p1 is not None and p2 is not None:
                pygame.draw.line(screen, section_color, p1, p2, 2)

        self._draw_bioregion_height_outlines(screen, sim, camera)

        hover_cell = getattr(sim, "hover_cell", None)
        if hover_cell is not None:
            self._draw_bioregion_cell_highlight(
                screen=screen,
                camera=camera,
                cell=hover_cell,
                color=(120, 220, 255),
                border_width=2,
            )

        selected_cell = getattr(sim, "selected_cell", None)
        if selected_cell is not None:
            self._draw_bioregion_cell_highlight(
                screen=screen,
                camera=camera,
                cell=selected_cell,
                color=(255, 230, 120),
                border_width=3,
            )