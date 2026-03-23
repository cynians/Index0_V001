class BioregionGrid:
    """
    Grid-backed resource substrate for the prototype bioregion simulation.

    Each subsection cell stores:
    * geology fields
      - soil_type
      - bedrock_type
      - altitude
      - z
    * water fields
      - surface_water
      - top_moisture
      - deep_moisture
    """

    SOIL_PRESETS = {
        "very_sandy": {
            "infiltration_rate": 0.00120,
            "top_field_capacity": 0.22,
            "deep_field_capacity": 0.30,
            "percolation_rate": 0.00045,
            "capillary_rise_rate": 0.000015,
            "surface_evaporation_rate": 0.00030,
            "top_evaporation_rate": 0.000060,
        },
        "sandy_loam": {
            "infiltration_rate": 0.00095,
            "top_field_capacity": 0.30,
            "deep_field_capacity": 0.42,
            "percolation_rate": 0.00032,
            "capillary_rise_rate": 0.000020,
            "surface_evaporation_rate": 0.00024,
            "top_evaporation_rate": 0.000050,
        },
        "loam": {
            "infiltration_rate": 0.00075,
            "top_field_capacity": 0.38,
            "deep_field_capacity": 0.52,
            "percolation_rate": 0.00022,
            "capillary_rise_rate": 0.000030,
            "surface_evaporation_rate": 0.00020,
            "top_evaporation_rate": 0.000040,
        },
        "clay_loam": {
            "infiltration_rate": 0.00045,
            "top_field_capacity": 0.48,
            "deep_field_capacity": 0.64,
            "percolation_rate": 0.00012,
            "capillary_rise_rate": 0.000040,
            "surface_evaporation_rate": 0.00016,
            "top_evaporation_rate": 0.000032,
        },
        "heavy_clay": {
            "infiltration_rate": 0.00028,
            "top_field_capacity": 0.58,
            "deep_field_capacity": 0.76,
            "percolation_rate": 0.00008,
            "capillary_rise_rate": 0.000050,
            "surface_evaporation_rate": 0.00013,
            "top_evaporation_rate": 0.000026,
        },
    }

    def __init__(
        self,
        sections_per_side,
        subsections_per_section_side,
        section_size_m,
        subsection_size_m,
    ):
        self.sections_per_side = sections_per_side
        self.subsections_per_section_side = subsections_per_section_side
        self.section_size_m = section_size_m
        self.subsection_size_m = subsection_size_m

        self.total_cells_side = sections_per_side * subsections_per_section_side
        self.map_size_m = sections_per_side * section_size_m

        self.cells = []
        self._build_cells()

    def _build_cells(self):
        """
        Build the full subsection-cell grid with neutral defaults.
        """
        self.cells = []

        for row in range(self.total_cells_side):
            row_cells = []

            for col in range(self.total_cells_side):
                min_x = col * self.subsection_size_m
                min_y = row * self.subsection_size_m
                max_x = min_x + self.subsection_size_m
                max_y = min_y + self.subsection_size_m

                row_cells.append(
                    {
                        "row": row,
                        "col": col,
                        "min_x": min_x,
                        "min_y": min_y,
                        "max_x": max_x,
                        "max_y": max_y,
                        "soil_type": "loam",
                        "bedrock_type": "granite",
                        "altitude": 0.5,
                        "z": 0.5,
                        "surface_water": 0.0,
                        "top_moisture": 0.266,
                        "deep_moisture": 0.426,
                    }
                )

            self.cells.append(row_cells)

    def initialize_water_from_soil(self):
        """
        Reset top/deep moisture from the assigned soil types.
        Call this after geology has populated soil_type.
        """
        for cell in self.iter_cells():
            soil = self.SOIL_PRESETS[cell["soil_type"]]
            cell["surface_water"] = 0.0
            cell["top_moisture"] = soil["top_field_capacity"] * 0.70
            cell["deep_moisture"] = soil["deep_field_capacity"] * 0.82

    def get_cell(self, row, col):
        if row < 0 or col < 0:
            return None

        if row >= self.total_cells_side or col >= self.total_cells_side:
            return None

        return self.cells[row][col]

    def get_cell_from_world(self, world_x, world_y):
        if world_x < 0.0 or world_y < 0.0:
            return None

        if world_x >= self.map_size_m or world_y >= self.map_size_m:
            return None

        col = int(world_x // self.subsection_size_m)
        row = int(world_y // self.subsection_size_m)

        return self.get_cell(row, col)

    def iter_cells(self):
        for row_cells in self.cells:
            for cell in row_cells:
                yield cell

    def get_average_surface_water(self):
        total = 0.0
        count = 0

        for cell in self.iter_cells():
            total += cell["surface_water"]
            count += 1

        if count == 0:
            return 0.0

        return total / count

    def get_average_top_moisture(self):
        total = 0.0
        count = 0

        for cell in self.iter_cells():
            total += cell["top_moisture"]
            count += 1

        if count == 0:
            return 0.0

        return total / count

    def get_average_deep_moisture(self):
        total = 0.0
        count = 0

        for cell in self.iter_cells():
            total += cell["deep_moisture"]
            count += 1

        if count == 0:
            return 0.0

        return total / count