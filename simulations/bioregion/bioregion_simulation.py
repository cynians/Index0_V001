from engine.clock import Clock
from engine.simulation_manager import SimulationManager
from simulations.bioregion.bioregion_grid import BioregionGrid


class BioregionSimulation:
    """
    Prototype bioregion simulation.

    This first slice only establishes:
    * dedicated render mode
    * stable test-map bounds
    * section/subsection grid geometry
    * hover and selection of subsection cells
    * camera center / zoom contract for the app

    World-unit convention for this prototype:
    * 1 world unit = 1 meter

    Spatial layout:
    * map size = 10 km x 10 km
    * sections = 10 x 10
    * section size = 1000 m x 1000 m
    * subsections per section = 10 x 10
    * subsection size = 100 m x 100 m
    """

    MAP_SIZE_M = 10000.0

    SECTIONS_PER_SIDE = 10
    SECTION_SIZE_M = 1000.0

    SUBSECTIONS_PER_SECTION_SIDE = 10
    SUBSECTION_SIZE_M = 100.0

    def __init__(self):
        class _DummySystem:
            def update(self, dt):
                pass

        self.render_mode = "bioregion"
        self.world_units_to_meters = 1.0

        self.sim_clock = Clock(base_dt=1.0)
        self.system = _DummySystem()
        self.sim_manager = SimulationManager(self.sim_clock, self.system)

        self.min_zoom = 0.03
        self.max_zoom = 4.0
        self.preferred_zoom = 0.085

        self.bounds = {
            "min_x": 0.0,
            "max_x": self.MAP_SIZE_M,
            "min_y": 0.0,
            "max_y": self.MAP_SIZE_M,
        }

        self.grid = BioregionGrid(
            sections_per_side=self.SECTIONS_PER_SIDE,
            subsections_per_section_side=self.SUBSECTIONS_PER_SECTION_SIDE,
            section_size_m=self.SECTION_SIZE_M,
            subsection_size_m=self.SUBSECTION_SIZE_M,
        )

        self.rain_period_seconds = 180.0
        self.rain_chance_per_check = 0.35
        self.rain_duration_seconds = 45.0
        self.rain_rate = 0.020
        self.evaporation_rate = 0.0014
        self.seepage_rate = 0.0035
        self.deep_loss_rate = 0.00022

        self.environment_elapsed = 0.0
        self.rain_timer = 0.0
        self.is_raining = False

        self.hover_cell = None
        self.selected_cell = None
        self.hover_screen_pos = None

    @property
    def year(self):
        """
        Prototype test year.
        """
        return 2400

    def update(self, dt):
        """
        Advance the prototype simulation clock and environment state.
        """
        self.sim_manager.update(dt)
        self._update_weather(dt)
        self._update_environment(dt)

    def get_center(self):
        """
        Return the center of the test map for camera setup.
        """
        return self.MAP_SIZE_M / 2.0, self.MAP_SIZE_M / 2.0

    def _update_weather(self, dt):
        """
        Update the simple prototype rain cycle.

        Behavior:
        * check periodically whether a rain event starts
        * keep rain active for a fixed duration once triggered
        """
        self.environment_elapsed += dt

        if self.is_raining:
            self.rain_timer -= dt
            if self.rain_timer <= 0.0:
                self.is_raining = False
                self.rain_timer = 0.0
            return

        if self.environment_elapsed >= self.rain_period_seconds:
            self.environment_elapsed = 0.0

            import random
            if random.random() < self.rain_chance_per_check:
                self.is_raining = True
                self.rain_timer = self.rain_duration_seconds

    def _update_environment(self, dt):
        """
        Apply the current environment step to the full grid.
        """
        self.grid.apply_environment_step(
            dt=dt,
            is_raining=self.is_raining,
            rain_rate=self.rain_rate,
            evaporation_rate=self.evaporation_rate,
            seepage_rate=self.seepage_rate,
            deep_loss_rate=self.deep_loss_rate,
        )

    def get_selected_grid_cell(self):
        """
        Resolve the selected UI cell into the backing moisture cell.
        """
        if self.selected_cell is None:
            return None

        section_col = self.selected_cell["section_col"]
        section_row = self.selected_cell["section_row"]
        subsection_col = self.selected_cell["subsection_col"]
        subsection_row = self.selected_cell["subsection_row"]

        absolute_col = (
            section_col * self.SUBSECTIONS_PER_SECTION_SIDE + subsection_col
        )
        absolute_row = (
            section_row * self.SUBSECTIONS_PER_SECTION_SIDE + subsection_row
        )

        return self.grid.get_cell(absolute_row, absolute_col)

    def get_hover_grid_cell(self):
        """
        Resolve the hovered UI cell into the backing moisture cell.
        """
        if self.hover_cell is None:
            return None

        section_col = self.hover_cell["section_col"]
        section_row = self.hover_cell["section_row"]
        subsection_col = self.hover_cell["subsection_col"]
        subsection_row = self.hover_cell["subsection_row"]

        absolute_col = (
            section_col * self.SUBSECTIONS_PER_SECTION_SIDE + subsection_col
        )
        absolute_row = (
            section_row * self.SUBSECTIONS_PER_SECTION_SIDE + subsection_row
        )

        return self.grid.get_cell(absolute_row, absolute_col)

    def get_average_top_moisture(self):
        return self.grid.get_average_top_moisture()

    def get_average_deep_moisture(self):
        return self.grid.get_average_deep_moisture()

    def get_section_count(self):
        return self.SECTIONS_PER_SIDE

    def get_section_size(self):
        return self.SECTION_SIZE_M

    def get_subsection_count_per_section(self):
        return self.SUBSECTIONS_PER_SECTION_SIDE

    def get_subsection_size(self):
        return self.SUBSECTION_SIZE_M

    def get_map_size(self):
        return self.MAP_SIZE_M

    def world_to_cell_indices(self, world_x, world_y):
        """
        Convert a world position into section/subsection indices.

        Returns:
            dict with section/subsection indices and bounds, or None if outside map.
        """
        if world_x < 0.0 or world_y < 0.0:
            return None

        if world_x >= self.MAP_SIZE_M or world_y >= self.MAP_SIZE_M:
            return None

        section_col = int(world_x // self.SECTION_SIZE_M)
        section_row = int(world_y // self.SECTION_SIZE_M)

        local_x = world_x - (section_col * self.SECTION_SIZE_M)
        local_y = world_y - (section_row * self.SECTION_SIZE_M)

        subsection_col = int(local_x // self.SUBSECTION_SIZE_M)
        subsection_row = int(local_y // self.SUBSECTION_SIZE_M)

        subsection_min_x = (
            section_col * self.SECTION_SIZE_M
            + subsection_col * self.SUBSECTION_SIZE_M
        )
        subsection_min_y = (
            section_row * self.SECTION_SIZE_M
            + subsection_row * self.SUBSECTION_SIZE_M
        )
        subsection_max_x = subsection_min_x + self.SUBSECTION_SIZE_M
        subsection_max_y = subsection_min_y + self.SUBSECTION_SIZE_M

        return {
            "section_col": section_col,
            "section_row": section_row,
            "subsection_col": subsection_col,
            "subsection_row": subsection_row,
            "min_x": subsection_min_x,
            "min_y": subsection_min_y,
            "max_x": subsection_max_x,
            "max_y": subsection_max_y,
            "center_x": (subsection_min_x + subsection_max_x) / 2.0,
            "center_y": (subsection_min_y + subsection_max_y) / 2.0,
        }

    def get_cell_label(self, cell):
        """
        Return a compact label for a subsection cell.
        """
        if cell is None:
            return "No cell selected"

        return (
            f"Section ({cell['section_col']}, {cell['section_row']}) | "
            f"Subsection ({cell['subsection_col']}, {cell['subsection_row']})"
        )

    def handle_pointer_motion(self, event, camera, screen_pos):
        """
        Track the currently hovered subsection cell.
        """
        world_x, world_y = camera.screen_to_world(screen_pos)
        self.hover_cell = self.world_to_cell_indices(world_x, world_y)
        self.hover_screen_pos = screen_pos

    def handle_pointer_event(self, event, camera, screen_pos):
        """
        Select the clicked subsection cell.
        """
        world_x, world_y = camera.screen_to_world(screen_pos)
        self.selected_cell = self.world_to_cell_indices(world_x, world_y)
        self.hover_screen_pos = screen_pos