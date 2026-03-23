import math
import random


class GeologyGenerator:
    """
    Generates the physical substrate of the prototype bioregion map.

    Responsibilities:
    * assign soil_type
    * assign bedrock_type
    * assign altitude
    * assign z
    * derive terrain-display layers from geology state

    Current terrain style:
    * fuzzy broad soil stripes
    * broad bedrock regions
    * clear hills and low areas

    Current derived display support:
    * height-outline segments based on z-band boundaries
    """

    SOIL_ORDER = [
        "very_sandy",
        "sandy_loam",
        "loam",
        "clay_loam",
        "heavy_clay",
    ]

    BEDROCK_ORDER = [
        "sandstone",
        "limestone",
        "granite",
        "basalt",
        "shale",
    ]

    def populate_grid(self, grid, seed=42):
        """
        Populate an existing grid with geology fields.
        """
        rng = random.Random(seed)

        hill_features = self._build_hill_features(grid, rng)
        basin_features = self._build_basin_features(grid, rng)

        for cell in grid.iter_cells():
            col = cell["col"]
            row = cell["row"]

            soil_type = self._choose_soil_type_for_column(
                col=col,
                total_cells_side=grid.total_cells_side,
                rng=rng
            )

            bedrock_type = self._choose_bedrock_type(
                row=row,
                col=col,
                total_cells_side=grid.total_cells_side,
                rng=rng
            )

            altitude = self._compute_altitude(
                cell=cell,
                grid=grid,
                hill_features=hill_features,
                basin_features=basin_features,
            )

            cell["soil_type"] = soil_type
            cell["bedrock_type"] = bedrock_type
            cell["altitude"] = altitude
            cell["z"] = altitude

    def build_default_map_layers(self, grid, z_band_size=0.1):
        """
        Build default derived terrain-display layers from the current grid state.

        Returns:
            dict with terrain-derived layer data that a renderer can consume later.
        """
        return {
            "height_outline_segments": self.build_height_outline_segments(
                grid=grid,
                z_band_size=z_band_size,
            )
        }

    def build_height_outline_segments(self, grid, z_band_size=0.1):
        """
        Derive contour-like border segments from z-band boundaries.

        Logic:
        * each cell is assigned to a z band based on z_band_size
        * a segment is generated where neighboring cells fall into different bands
        * outer map edges are also outlined

        Returns:
            list of segment dicts:
            {
                "x1": ...,
                "y1": ...,
                "x2": ...,
                "y2": ...,
                "band_a": ...,
                "band_b": ...,
            }
        """
        segments = []

        for cell in grid.iter_cells():
            row = cell["row"]
            col = cell["col"]

            cell_band = self._get_z_band_index(cell["z"], z_band_size)

            north = grid.get_cell(row - 1, col)
            south = grid.get_cell(row + 1, col)
            west = grid.get_cell(row, col - 1)
            east = grid.get_cell(row, col + 1)

            min_x = cell["min_x"]
            min_y = cell["min_y"]
            max_x = cell["max_x"]
            max_y = cell["max_y"]

            if north is None:
                segments.append(
                    self._make_segment(
                        x1=min_x,
                        y1=min_y,
                        x2=max_x,
                        y2=min_y,
                        band_a=cell_band,
                        band_b=None,
                    )
                )

            if west is None:
                segments.append(
                    self._make_segment(
                        x1=min_x,
                        y1=min_y,
                        x2=min_x,
                        y2=max_y,
                        band_a=cell_band,
                        band_b=None,
                    )
                )

            if east is None:
                segments.append(
                    self._make_segment(
                        x1=max_x,
                        y1=min_y,
                        x2=max_x,
                        y2=max_y,
                        band_a=cell_band,
                        band_b=None,
                    )
                )

            if south is None:
                segments.append(
                    self._make_segment(
                        x1=min_x,
                        y1=max_y,
                        x2=max_x,
                        y2=max_y,
                        band_a=cell_band,
                        band_b=None,
                    )
                )

            if east is not None:
                east_band = self._get_z_band_index(east["z"], z_band_size)
                if east_band != cell_band:
                    segments.append(
                        self._make_segment(
                            x1=max_x,
                            y1=min_y,
                            x2=max_x,
                            y2=max_y,
                            band_a=cell_band,
                            band_b=east_band,
                        )
                    )

            if south is not None:
                south_band = self._get_z_band_index(south["z"], z_band_size)
                if south_band != cell_band:
                    segments.append(
                        self._make_segment(
                            x1=min_x,
                            y1=max_y,
                            x2=max_x,
                            y2=max_y,
                            band_a=cell_band,
                            band_b=south_band,
                        )
                    )

        return segments

    def _make_segment(self, x1, y1, x2, y2, band_a, band_b):
        """
        Build one derived height-outline segment record.
        """
        return {
            "x1": x1,
            "y1": y1,
            "x2": x2,
            "y2": y2,
            "band_a": band_a,
            "band_b": band_b,
        }

    def _get_z_band_index(self, z_value, z_band_size):
        """
        Convert normalized z into a discrete contour band index.
        """
        if z_band_size <= 0.0:
            z_band_size = 0.1

        return int(max(0.0, z_value) // z_band_size)

    def _choose_soil_type_for_column(self, col, total_cells_side, rng):
        """
        Assign broad vertical soil bands with fuzzy transitions.
        """
        normalized = col / max(1, total_cells_side - 1)
        exact_band_position = normalized * len(self.SOIL_ORDER)

        base_index = int(exact_band_position)
        base_index = max(0, min(len(self.SOIL_ORDER) - 1, base_index))

        fractional = exact_band_position - int(exact_band_position)
        soil_index = base_index
        fuzzy_zone = 0.28

        if fractional < fuzzy_zone and base_index > 0:
            blend_strength = (fuzzy_zone - fractional) / fuzzy_zone
            if rng.random() < blend_strength * 0.45:
                soil_index = base_index - 1

        elif fractional > (1.0 - fuzzy_zone) and base_index < len(self.SOIL_ORDER) - 1:
            blend_strength = (fractional - (1.0 - fuzzy_zone)) / fuzzy_zone
            if rng.random() < blend_strength * 0.45:
                soil_index = base_index + 1

        soil_index = max(0, min(len(self.SOIL_ORDER) - 1, soil_index))
        return self.SOIL_ORDER[soil_index]

    def _choose_bedrock_type(self, row, col, total_cells_side, rng):
        """
        Assign slower-changing bedrock regions than soil.
        """
        x = col / max(1, total_cells_side - 1)
        y = row / max(1, total_cells_side - 1)

        value = (
            0.55 * x
            + 0.35 * y
            + 0.10 * math.sin(x * math.pi * 3.0)
            - 0.08 * math.cos(y * math.pi * 2.0)
        )

        value += (rng.random() - 0.5) * 0.04
        value = max(0.0, min(0.9999, value))

        index = int(value * len(self.BEDROCK_ORDER))
        index = max(0, min(len(self.BEDROCK_ORDER) - 1, index))
        return self.BEDROCK_ORDER[index]

    def _build_hill_features(self, grid, rng):
        """
        Build large positive terrain features.
        """
        map_size = grid.map_size_m

        return [
            {"x": map_size * 0.20, "y": map_size * 0.25, "strength": 0.55, "radius": map_size * 0.18},
            {"x": map_size * 0.72, "y": map_size * 0.30, "strength": 0.48, "radius": map_size * 0.16},
            {"x": map_size * 0.35, "y": map_size * 0.72, "strength": 0.60, "radius": map_size * 0.20},
            {"x": map_size * 0.78, "y": map_size * 0.78, "strength": 0.42, "radius": map_size * 0.15},
        ]

    def _build_basin_features(self, grid, rng):
        """
        Build large negative terrain features.
        """
        map_size = grid.map_size_m

        return [
            {"x": map_size * 0.52, "y": map_size * 0.52, "strength": 0.42, "radius": map_size * 0.18},
            {"x": map_size * 0.12, "y": map_size * 0.82, "strength": 0.28, "radius": map_size * 0.14},
            {"x": map_size * 0.88, "y": map_size * 0.12, "strength": 0.22, "radius": map_size * 0.12},
        ]

    def _compute_altitude(self, cell, grid, hill_features, basin_features):
        """
        Compute a normalized altitude field with clear hills and low areas.
        """
        cx = (cell["min_x"] + cell["max_x"]) / 2.0
        cy = (cell["min_y"] + cell["max_y"]) / 2.0

        nx = cx / grid.map_size_m
        ny = cy / grid.map_size_m

        value = 0.30
        value += 0.04 * math.sin(nx * math.pi * 2.0)
        value += 0.03 * math.cos(ny * math.pi * 3.0)

        for feature in hill_features:
            value += self._radial_feature_value(
                x=cx,
                y=cy,
                center_x=feature["x"],
                center_y=feature["y"],
                radius=feature["radius"],
                strength=feature["strength"],
            )

        for feature in basin_features:
            value -= self._radial_feature_value(
                x=cx,
                y=cy,
                center_x=feature["x"],
                center_y=feature["y"],
                radius=feature["radius"],
                strength=feature["strength"],
            )

        return max(0.0, min(1.0, value))

    def _radial_feature_value(self, x, y, center_x, center_y, radius, strength):
        """
        Smooth radial hill/basin contribution.
        """
        dx = x - center_x
        dy = y - center_y
        dist = math.sqrt(dx * dx + dy * dy)

        if dist >= radius:
            return 0.0

        t = 1.0 - (dist / radius)
        smooth = t * t * (3.0 - 2.0 * t)
        return smooth * strength