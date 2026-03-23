from engine.clock import Clock
from engine.simulation_manager import SimulationManager
from engine.logger import logger
from simulations.bioregion.bioregion_grid import BioregionGrid
from simulations.bioregion.geology import GeologyGenerator
from simulations.bioregion.water_cycle import WaterCycle
from simulations.bioregion.weather import WeatherController


class BioregionSimulation:
    """
    Prototype bioregion simulation.

    Current slice:
    * dedicated render mode
    * stable test-map bounds
    * section/subsection grid geometry
    * geology generation
      - soil
      - bedrock
      - altitude
      - z
    * cached derived terrain display layers
    * orchestration of:
      - grid state
      - weather
      - water cycle
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

        self.geology = GeologyGenerator()
        self.geology.populate_grid(self.grid, seed=42)
        self.grid.initialize_water_from_soil()

        self.derived_map_layers = self.geology.build_default_map_layers(
            self.grid,
            z_band_size=0.1,
        )

        self.weather = WeatherController(
            rain_check_period_seconds=900.0,
            rain_chance_per_check=0.18,
            rain_duration_seconds=1200.0,
            rain_rate=0.00035,
            start_raining=True,
        )

        self.water_cycle = WaterCycle(
            deep_background_loss_rate=0.000003
        )

        self.hover_cell = None
        self.selected_cell = None
        self.hover_screen_pos = None

        logger.info("[BioregionSimulation] Initialized prototype bioregion simulation")
        logger.info(
            "[BioregionSimulation] Starting with immediate rain event "
            f"(duration={self.weather.rain_duration_seconds:.1f}s, "
            f"rate={self.weather.rain_rate:.6f})"
        )
        logger.info(
            "[BioregionSimulation] Derived map layers built | "
            f"height_outline_segments="
            f"{len(self.derived_map_layers.get('height_outline_segments', []))}"
        )

    @property
    def year(self):
        return 2400

    def update(self, dt):
        self.sim_manager.update(dt)
        self.weather.update(dt)
        self.water_cycle.update_grid(
            grid=self.grid,
            dt=dt,
            rain_input_rate=self.weather.get_rain_input_rate(),
        )
        self._log_environment_summary()

    def get_center(self):
        return self.MAP_SIZE_M / 2.0, self.MAP_SIZE_M / 2.0

    def get_height_outline_segments(self):
        """
        Return cached contour-like height outline segments.
        """
        return self.derived_map_layers.get("height_outline_segments", [])

    def _log_environment_summary(self):
        avg_surface = self.get_average_surface_water()
        avg_top = self.get_average_top_moisture()
        avg_deep = self.get_average_deep_moisture()

        logger.debug(
            f"[BioregionSimulation] Moisture summary | "
            f"rain={self.weather.is_raining} | "
            f"avg_surface={avg_surface:.3f} | "
            f"avg_top={avg_top:.3f} | "
            f"avg_deep={avg_deep:.3f}",
            key="bioregion_moisture_summary",
            interval=1.5
        )

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
        if cell is None:
            return "No cell selected"

        return (
            f"Section ({cell['section_col']}, {cell['section_row']}) | "
            f"Subsection ({cell['subsection_col']}, {cell['subsection_row']})"
        )

    def get_selected_grid_cell(self):
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

    def get_average_surface_water(self):
        return self.grid.get_average_surface_water()

    def get_average_top_moisture(self):
        return self.grid.get_average_top_moisture()

    def get_average_deep_moisture(self):
        return self.grid.get_average_deep_moisture()

    @property
    def is_raining(self):
        return self.weather.is_raining

    def handle_pointer_motion(self, event, camera, screen_pos):
        world_x, world_y = camera.screen_to_world(screen_pos)
        self.hover_cell = self.world_to_cell_indices(world_x, world_y)
        self.hover_screen_pos = screen_pos

    def handle_pointer_event(self, event, camera, screen_pos):
        world_x, world_y = camera.screen_to_world(screen_pos)
        self.selected_cell = self.world_to_cell_indices(world_x, world_y)
        self.hover_screen_pos = screen_pos

        selected_grid_cell = self.get_selected_grid_cell()
        if selected_grid_cell is not None:
            logger.debug(
                f"[BioregionSimulation] Selected cell | "
                f"soil={selected_grid_cell['soil_type']} | "
                f"bedrock={selected_grid_cell['bedrock_type']} | "
                f"altitude={selected_grid_cell['altitude']:.3f} | "
                f"surface={selected_grid_cell['surface_water']:.3f} | "
                f"top={selected_grid_cell['top_moisture']:.3f} | "
                f"deep={selected_grid_cell['deep_moisture']:.3f}",
                key="bioregion_cell_selection",
                interval=0.1
            )