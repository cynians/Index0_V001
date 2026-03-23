class WaterCycle:
    """
    Prototype vertical soil-water cycle for the bioregion simulation.

    Responsibilities:
    * apply rain input to cells
    * update surface water, top moisture, and deep moisture
    * use soil-specific parameters from the grid

    Notes:
    * this version is vertical-only
    * no lateral flow/runoff between neighboring cells yet
    """

    def __init__(self, deep_background_loss_rate):
        self.deep_background_loss_rate = deep_background_loss_rate

    def update_grid(self, grid, dt, rain_input_rate):
        """
        Apply one hydrology step to the entire grid.
        """
        for cell in grid.iter_cells():
            self.update_cell(
                cell=cell,
                dt=dt,
                rain_input_rate=rain_input_rate,
                soil=grid.SOIL_PRESETS[cell["soil_type"]],
            )

    def update_cell(self, cell, dt, rain_input_rate, soil):
        """
        Apply one vertical hydrology step to a single cell.
        """
        surface_water = cell["surface_water"]
        top_moisture = cell["top_moisture"]
        deep_moisture = cell["deep_moisture"]

        if rain_input_rate > 0.0:
            surface_water += rain_input_rate * dt

        surface_evap = min(surface_water, soil["surface_evaporation_rate"] * dt)
        surface_water -= surface_evap

        infiltration_capacity = soil["infiltration_rate"] * dt
        top_space = max(0.0, 1.0 - top_moisture)
        infiltrated = min(surface_water, infiltration_capacity, top_space)
        surface_water -= infiltrated
        top_moisture += infiltrated

        top_evap = min(top_moisture, soil["top_evaporation_rate"] * dt)
        top_moisture -= top_evap

        top_field_capacity = soil["top_field_capacity"]
        deep_field_capacity = soil["deep_field_capacity"]

        if top_moisture > top_field_capacity:
            excess_top = top_moisture - top_field_capacity
            percolation = min(excess_top, soil["percolation_rate"] * dt)
            percolation = min(
                percolation,
                max(0.0, deep_field_capacity - deep_moisture)
            )
            top_moisture -= percolation
            deep_moisture += percolation

        if top_moisture < top_field_capacity * 0.55 and deep_moisture > top_moisture:
            dryness_factor = 1.0 - (
                top_moisture / max(0.0001, top_field_capacity * 0.55)
            )
            capillary = soil["capillary_rise_rate"] * dryness_factor * dt
            capillary = min(capillary, deep_moisture)
            capillary = min(capillary, max(0.0, top_field_capacity - top_moisture))
            deep_moisture -= capillary
            top_moisture += capillary

        deep_loss = min(deep_moisture, self.deep_background_loss_rate * dt)
        deep_moisture -= deep_loss

        cell["surface_water"] = min(1.0, max(0.0, surface_water))
        cell["top_moisture"] = min(1.0, max(0.0, top_moisture))
        cell["deep_moisture"] = min(1.0, max(0.0, deep_moisture))