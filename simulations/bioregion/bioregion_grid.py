class BioregionGrid:
    """
    Grid-backed resource substrate for the prototype bioregion simulation.

    Each subsection cell stores two soil-moisture layers:
    * top_moisture
    * deep_moisture

    Units are prototype-relative moisture units, clamped to [0.0, 1.0].
    """

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
        Build the full subsection-cell grid.
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
                        "top_moisture": 0.35,
                        "deep_moisture": 0.55,
                    }
                )

            self.cells.append(row_cells)

    def get_cell(self, row, col):
        """
        Return one cell by absolute subsection-grid coordinates.
        """
        if row < 0 or col < 0:
            return None

        if row >= self.total_cells_side or col >= self.total_cells_side:
            return None

        return self.cells[row][col]

    def get_cell_from_world(self, world_x, world_y):
        """
        Return one cell from world coordinates.
        """
        if world_x < 0.0 or world_y < 0.0:
            return None

        if world_x >= self.map_size_m or world_y >= self.map_size_m:
            return None

        col = int(world_x // self.subsection_size_m)
        row = int(world_y // self.subsection_size_m)

        return self.get_cell(row, col)

    def iter_cells(self):
        """
        Yield all cells in row-major order.
        """
        for row_cells in self.cells:
            for cell in row_cells:
                yield cell

    def apply_environment_step(
        self,
        dt,
        is_raining,
        rain_rate,
        evaporation_rate,
        seepage_rate,
        deep_loss_rate,
    ):
        """
        Advance the moisture state of all cells by one environment step.
        """
        for cell in self.iter_cells():
            top = cell["top_moisture"]
            deep = cell["deep_moisture"]

            if is_raining:
                top += rain_rate * dt

            top_loss_evap = evaporation_rate * dt
            seep_amount = min(top, seepage_rate * dt)

            top = max(0.0, top - top_loss_evap - seep_amount)
            deep = min(1.0, deep + seep_amount)

            deep = max(0.0, deep - deep_loss_rate * dt)

            top = min(1.0, top)
            deep = min(1.0, deep)

            cell["top_moisture"] = top
            cell["deep_moisture"] = deep

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