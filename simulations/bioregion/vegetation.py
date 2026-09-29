class VegetationController:
    """
    Prototype vegetation layer for the bioregion simulation.

    Responsibilities:
    * seed initial plant biomass from terrain and soil suitability
    * update plant health and biomass from water, soil, altitude, and flooding
    * classify each cell into a coarse habitat display type

    This remains intentionally aggregate: cells represent vegetation cover and
    vigor, not individual plants or species populations yet.
    """

    SOIL_FERTILITY = {
        "very_sandy": 0.44,
        "sandy_loam": 0.74,
        "loam": 0.95,
        "clay_loam": 0.82,
        "heavy_clay": 0.62,
    }

    SOIL_MOISTURE_OPTIMUM = {
        "very_sandy": 0.24,
        "sandy_loam": 0.36,
        "loam": 0.46,
        "clay_loam": 0.54,
        "heavy_clay": 0.62,
    }

    def __init__(self, growth_rate=0.000020, dieback_rate=0.000035):
        self.growth_rate = growth_rate
        self.dieback_rate = dieback_rate

    def seed_grid(self, grid):
        """
        Initialize vegetation from the starting physical environment.
        """
        for cell in grid.iter_cells():
            suitability = self.compute_cell_suitability(cell)
            cell["plant_health"] = suitability
            cell["plant_biomass"] = max(0.0, min(1.0, suitability * 0.72))
            cell["habitat_type"] = self.classify_habitat(cell)

    def update_grid(self, grid, dt):
        """
        Apply one aggregate vegetation step to the grid.
        """
        for cell in grid.iter_cells():
            self.update_cell(cell, dt)

    def update_cell(self, cell, dt):
        """
        Grow or reduce vegetation in a cell based on current suitability.
        """
        suitability = self.compute_cell_suitability(cell)
        biomass = cell["plant_biomass"]

        health = (cell["plant_health"] * 0.92) + (suitability * 0.08)
        target_biomass = suitability

        if target_biomass > biomass:
            biomass += min(
                target_biomass - biomass,
                self.growth_rate * max(0.12, health) * dt,
            )
        else:
            stress = 1.0 - suitability
            biomass -= min(
                biomass,
                self.dieback_rate * max(0.10, stress) * dt,
            )

        cell["plant_health"] = max(0.0, min(1.0, health))
        cell["plant_biomass"] = max(0.0, min(1.0, biomass))
        cell["habitat_type"] = self.classify_habitat(cell)

    def compute_cell_suitability(self, cell):
        soil_type = cell["soil_type"]
        fertility = self.SOIL_FERTILITY.get(soil_type, 0.65)
        optimum = self.SOIL_MOISTURE_OPTIMUM.get(soil_type, 0.45)

        moisture = (cell["top_moisture"] * 0.70) + (cell["deep_moisture"] * 0.30)
        moisture_distance = abs(moisture - optimum)
        moisture_suitability = 1.0 - min(1.0, moisture_distance / 0.38)

        altitude = cell["altitude"]
        if altitude <= 0.72:
            altitude_suitability = 1.0
        else:
            altitude_suitability = max(0.12, 1.0 - ((altitude - 0.72) / 0.28))

        flood_stress = min(0.85, max(0.0, cell["surface_water"] - 0.18) * 2.8)

        suitability = fertility * moisture_suitability * altitude_suitability
        suitability *= 1.0 - flood_stress

        return max(0.0, min(1.0, suitability))

    def classify_habitat(self, cell):
        biomass = cell["plant_biomass"]
        moisture = (cell["top_moisture"] * 0.70) + (cell["deep_moisture"] * 0.30)
        altitude = cell["altitude"]

        if cell["surface_water"] > 0.28 and biomass > 0.25:
            return "wetland"

        if altitude > 0.82:
            if biomass < 0.25:
                return "high_barren"
            return "upland_scrub"

        if biomass < 0.14:
            return "bare"

        if moisture < 0.25:
            return "dry_scrub"

        if biomass > 0.62 and moisture > 0.38:
            return "woodland"

        return "grassland"
