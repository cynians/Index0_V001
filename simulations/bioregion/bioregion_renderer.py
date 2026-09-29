import pygame


class BioregionRenderer:
    """
    Handles rendering for bioregion simulations.
    """

    def __init__(self, app_view):
        self.app_view = app_view
        self._cell_color_cache = {}
        self._cell_color_cache_limit = 2048

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

    def _draw_bioregion_ecosystem_cells(self, screen, sim, camera):
        """
        Draw the cell substrate and aggregate vegetation cover.
        """
        grid = getattr(sim, "grid", None)
        if grid is None:
            return

        for cell in grid.iter_cells():
            top_left = camera.world_to_screen((cell["min_x"], cell["min_y"]))
            bottom_right = camera.world_to_screen((cell["max_x"], cell["max_y"]))

            if top_left is None or bottom_right is None:
                continue

            left = min(top_left[0], bottom_right[0])
            right = max(top_left[0], bottom_right[0])
            top = min(top_left[1], bottom_right[1])
            bottom = max(top_left[1], bottom_right[1])

            if right < 0 or bottom < 0:
                continue

            if left > screen.get_width() or top > screen.get_height():
                continue

            width = max(1, int(right - left) + 1)
            height = max(1, int(bottom - top) + 1)
            rect = pygame.Rect(int(left), int(top), width, height)

            pygame.draw.rect(screen, self._get_ecosystem_cell_color(cell), rect)

    def _draw_bioregion_shape_outline(self, screen, sim, camera):
        points = []
        if hasattr(sim, "get_biosphere_shape_points"):
            points = sim.get_biosphere_shape_points()
        if len(points) < 3:
            return
        screen_points = []
        for point in points:
            screen_point = camera.world_to_screen(point)
            if screen_point is not None:
                screen_points.append(screen_point)
        if len(screen_points) >= 3:
            pygame.draw.polygon(screen, (28, 36, 28), screen_points)
            pygame.draw.polygon(screen, (204, 228, 186), screen_points, 2)

    def _get_ecosystem_cell_color(self, cell):
        """
        Build a display color from altitude, moisture, and vegetation state.
        """
        cache_key = (
            cell.get("soil_type"),
            cell.get("habitat_type"),
            round(float(cell.get("altitude", 0.0) or 0.0), 3),
            round(float(cell.get("plant_biomass", 0.0) or 0.0), 3),
            round(float(cell.get("plant_health", 0.0) or 0.0), 3),
            round(float(cell.get("surface_water", 0.0) or 0.0), 3),
        )
        cached = self._cell_color_cache.get(cache_key)
        if cached is not None:
            return cached

        altitude = cell["altitude"]
        biomass = cell["plant_biomass"]
        health = cell["plant_health"]
        surface_water = cell["surface_water"]
        habitat_type = cell["habitat_type"]

        bare = self._get_bare_ground_color(cell)
        vegetation = self._get_vegetation_color(habitat_type, health)

        plant_mix = max(0.0, min(0.90, biomass * 0.95))
        color = self._mix_color(bare, vegetation, plant_mix)

        if altitude > 0.78:
            highland_tint = (170, 172, 150)
            color = self._mix_color(color, highland_tint, min(0.35, (altitude - 0.78) * 1.4))

        if surface_water > 0.05:
            water_tint = (42, 92, 130)
            color = self._mix_color(color, water_tint, min(0.62, surface_water * 1.7))

        self._cell_color_cache[cache_key] = color
        while len(self._cell_color_cache) > self._cell_color_cache_limit:
            self._cell_color_cache.pop(next(iter(self._cell_color_cache)))
        return color

    def _get_bare_ground_color(self, cell):
        soil_type = cell["soil_type"]
        altitude = cell["altitude"]

        soil_colors = {
            "very_sandy": (128, 118, 80),
            "sandy_loam": (111, 104, 72),
            "loam": (86, 86, 63),
            "clay_loam": (78, 76, 66),
            "heavy_clay": (70, 69, 70),
        }
        base = soil_colors.get(soil_type, (86, 86, 63))

        shade = 0.82 + (altitude * 0.28)
        return (
            max(0, min(255, int(base[0] * shade))),
            max(0, min(255, int(base[1] * shade))),
            max(0, min(255, int(base[2] * shade))),
        )

    def _get_vegetation_color(self, habitat_type, health):
        habitat_colors = {
            "bare": (88, 91, 66),
            "dry_scrub": (101, 122, 63),
            "grassland": (66, 139, 68),
            "woodland": (38, 111, 57),
            "wetland": (45, 124, 86),
            "upland_scrub": (81, 121, 72),
            "high_barren": (116, 122, 101),
        }

        color = habitat_colors.get(habitat_type, (66, 139, 68))
        stress_tint = (98, 92, 62)
        return self._mix_color(stress_tint, color, max(0.0, min(1.0, health)))

    def _mix_color(self, a, b, amount):
        amount = max(0.0, min(1.0, amount))
        inverse = 1.0 - amount

        return (
            int((a[0] * inverse) + (b[0] * amount)),
            int((a[1] * inverse) + (b[1] * amount)),
            int((a[2] * inverse) + (b[2] * amount)),
        )

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

        self._draw_bioregion_shape_outline(screen, sim, camera)
        self._draw_bioregion_ecosystem_cells(screen, sim, camera)

        subsection_size = sim.get_subsection_size()
        section_size = sim.get_section_size()
        map_size = sim.get_map_size()
        map_width = getattr(sim, "get_biosphere_width", lambda: map_size)()
        map_height = getattr(sim, "get_biosphere_height", lambda: map_size)()

        subsection_color = (46, 64, 48)
        section_color = (165, 185, 165)

        subsection_steps = int(map_size // subsection_size)
        section_steps = int(map_size // section_size)

        for i in range(subsection_steps + 1):
            x = i * subsection_size
            if x > map_width:
                continue

            p1 = camera.world_to_screen((x, 0.0))
            p2 = camera.world_to_screen((x, map_height))
            if p1 is not None and p2 is not None:
                pygame.draw.line(screen, subsection_color, p1, p2, 1)

        for i in range(subsection_steps + 1):
            y = i * subsection_size
            if y > map_height:
                continue

            p1 = camera.world_to_screen((0.0, y))
            p2 = camera.world_to_screen((map_width, y))
            if p1 is not None and p2 is not None:
                pygame.draw.line(screen, subsection_color, p1, p2, 1)

        for i in range(section_steps + 1):
            x = i * section_size
            if x > map_width:
                continue

            p1 = camera.world_to_screen((x, 0.0))
            p2 = camera.world_to_screen((x, map_height))
            if p1 is not None and p2 is not None:
                pygame.draw.line(screen, section_color, p1, p2, 2)

        for i in range(section_steps + 1):
            y = i * section_size
            if y > map_height:
                continue

            p1 = camera.world_to_screen((0.0, y))
            p2 = camera.world_to_screen((map_width, y))
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
