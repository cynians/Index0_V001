"""Spatial organic-soil development for the Biosphere builder.

Worldgen remains authoritative for mineral substrate, terrain, hydrology and
climate.  This module owns only transient biological additions: litter, stable
soil organic matter and the resulting surface stability/fertility contribution.

The coefficients are deliberately qualitative gameplay values.  They make the
causal sequence inspectable without claiming calibrated pedogenesis.
"""

from __future__ import annotations

import math

import numpy as np


def _clamp(value, lower=0.0, upper=1.0):
    return max(lower, min(upper, float(value)))


class SoilOrganicMatterField:
    """Deterministic equal-area grid laid over an immutable mineral substrate."""

    MODEL_VERSION = "biosphere-soil-organic-nutrients-v2"
    MAX_LITTER_KG_M2 = 8.0
    MAX_ORGANIC_MATTER_KG_M2 = 16.0

    # Gameplay thresholds for increasingly demanding terrestrial growth forms,
    # as soil organic matter where the plant stands.  They pace the ladder
    # over decades (herbs about a decade after the crust on harsh ground, a
    # few years on mild) and must not be read as measured ecological limits.
    TIER_REQUIREMENTS_KG_M2 = {
        0: 0.0,   # bare-substrate colonists / aquatic parallel succession
        1: 0.15,  # herbaceous pioneers
        2: 1.0,   # shrubs and persistent ground communities
        3: 3.0,   # woody canopy establishment
    }

    TURNOVER_PER_SEASON = {
        "lichen": 0.12,
        "graminoid": 0.09,
        "forb": 0.08,
        "fern": 0.07,
        "aquatic": 0.07,
        "shrub": 0.05,
        "subshrub": 0.055,
        "succulent": 0.035,
        "tree": 0.035,
    }

    def __init__(
        self,
        bounds,
        *,
        columns=20,
        rows=20,
        initial_organic_matter_kg_m2=0.0,
    ):
        self.bounds = {key: float(bounds[key]) for key in ("min_x", "max_x", "min_y", "max_y")}
        self.columns = max(2, int(columns))
        self.rows = max(2, int(rows))
        initial = max(0.0, min(self.MAX_ORGANIC_MATTER_KG_M2, float(initial_organic_matter_kg_m2)))
        self.litter_rows = [[0.0 for _x in range(self.columns)] for _y in range(self.rows)]
        self.organic_matter_rows = [[initial for _x in range(self.columns)] for _y in range(self.rows)]
        self.litter_nitrogen_rows = [[0.0 for _x in range(self.columns)] for _y in range(self.rows)]
        self.organic_nitrogen_rows = [[0.0 for _x in range(self.columns)] for _y in range(self.rows)]
        self.available_nitrogen_rows = [[0.0 for _x in range(self.columns)] for _y in range(self.rows)]
        self.litter_phosphorus_rows = [[0.0 for _x in range(self.columns)] for _y in range(self.rows)]
        self.organic_phosphorus_rows = [[0.0 for _x in range(self.columns)] for _y in range(self.rows)]
        self.available_phosphorus_rows = [[0.0 for _x in range(self.columns)] for _y in range(self.rows)]
        self.mineral_phosphorus_reserve_rows = [[0.0 for _x in range(self.columns)] for _y in range(self.rows)]
        self.parent_nitrogen_index_rows = [[0.0 for _x in range(self.columns)] for _y in range(self.rows)]
        self.parent_phosphorus_index_rows = [[0.0 for _x in range(self.columns)] for _y in range(self.rows)]
        self.nutrients_initialized = False
        self.revision = 0
        self.elapsed_seasons = 0
        self.last_fluxes = {
            "litter_input_kg_m2": 0.0,
            "decomposition_kg_m2": 0.0,
            "humified_organic_matter_kg_m2": 0.0,
            "respired_or_mineralized_kg_m2": 0.0,
            "organic_matter_loss_kg_m2": 0.0,
            "nitrogen_deposition_g_m2": 0.0,
            "biological_nitrogen_fixation_g_m2": 0.0,
            "nitrogen_mineralization_g_m2": 0.0,
            "nitrogen_uptake_g_m2": 0.0,
            "phosphorus_weathering_g_m2": 0.0,
            "phosphorus_mineralization_g_m2": 0.0,
            "phosphorus_uptake_g_m2": 0.0,
        }

    def _abiotic_arrays(self, ecology, fields):
        """Cell-centre arrays of abiotic fields, or ``None`` if the substrate samples points only.

        ``fields`` maps a field to the default the point sampler would use.
        """
        sample_array = getattr(getattr(ecology, "substrate", None), "sample_array", None)
        if not callable(sample_array):
            return None
        cell_x = self.bounds["min_x"] + (np.arange(self.columns) + 0.5) * self.width / self.columns
        cell_y = self.bounds["min_y"] + (np.arange(self.rows) + 0.5) * self.height / self.rows
        grid_x, grid_y = np.meshgrid(cell_x, cell_y)
        return {key: sample_array(key, grid_x, grid_y, default) for key, default in fields.items()}, grid_x, grid_y

    def _seed_parent_material(self, parent_n, parent_p, mask):
        """Set the inorganic pools of the masked cells from their parent indices."""
        parent_n, parent_p = np.clip(parent_n, 0.0, 1.0), np.clip(parent_p, 0.0, 1.0)
        for name, values in (
            ("parent_nitrogen_index_rows", parent_n),
            ("parent_phosphorus_index_rows", parent_p),
            # Initial available N is deliberately sparse; most N arrives
            # through deposition, litter, or authored fixation.
            ("available_nitrogen_rows", 0.015 + parent_n * 0.035),
            # P begins as a finite mineral reserve plus a small available
            # fraction. Biological traits can expose, never create, it.
            ("available_phosphorus_rows", 0.018 + parent_p * 0.055),
            ("mineral_phosphorus_reserve_rows", 1.5 + parent_p * 6.5),
        ):
            setattr(self, name, np.where(mask, values, np.asarray(getattr(self, name), dtype=np.float64)).tolist())

    def initialize_from_abiotic(self, ecology):
        """Seed inorganic pools once from worldgen; organic nutrient pools stay zero."""
        if self.nutrients_initialized:
            return
        sampled = self._abiotic_arrays(ecology, {"parent_nitrogen_index": 0.18, "parent_phosphorus_index": 0.42})
        if sampled is not None:
            fields, _grid_x, _grid_y = sampled
            self._seed_parent_material(
                fields["parent_nitrogen_index"], fields["parent_phosphorus_index"],
                np.ones((self.rows, self.columns), dtype=bool),
            )
            self.nutrients_initialized = True
            self.revision += 1
            return
        for row in range(self.rows):
            for column in range(self.columns):
                x, y = self.cell_center(column, row)
                environment = ecology.abiotic_environment_at(x, y)
                parent_n = _clamp(environment.get("parent_nitrogen_index", 0.18))
                parent_p = _clamp(environment.get("parent_phosphorus_index", 0.42))
                self.parent_nitrogen_index_rows[row][column] = parent_n
                self.parent_phosphorus_index_rows[row][column] = parent_p
                # Initial available N is deliberately sparse; most N in this
                # MWP arrives through deposition, litter, or authored fixation.
                self.available_nitrogen_rows[row][column] = 0.015 + parent_n * 0.035
                # P begins as a finite mineral reserve plus a small available
                # fraction. Biological traits can expose, never create, it.
                self.available_phosphorus_rows[row][column] = 0.018 + parent_p * 0.055
                self.mineral_phosphorus_reserve_rows[row][column] = 1.5 + parent_p * 6.5
        self.nutrients_initialized = True
        self.revision += 1

    def seed_abiotic_outside(self, ecology, old_bounds):
        """After a resize, give cells beyond the old domain their worldgen parent material."""
        sampled = self._abiotic_arrays(ecology, {"parent_nitrogen_index": 0.18, "parent_phosphorus_index": 0.42})
        if sampled is not None:
            fields, grid_x, grid_y = sampled
            outside = ~((grid_x >= old_bounds["min_x"]) & (grid_x <= old_bounds["max_x"])
                        & (grid_y >= old_bounds["min_y"]) & (grid_y <= old_bounds["max_y"]))
            self._seed_parent_material(fields["parent_nitrogen_index"], fields["parent_phosphorus_index"], outside)
            self.revision += 1
            return
        for row in range(self.rows):
            for column in range(self.columns):
                x, y = self.cell_center(column, row)
                if old_bounds["min_x"] <= x <= old_bounds["max_x"] and old_bounds["min_y"] <= y <= old_bounds["max_y"]:
                    continue
                environment = ecology.abiotic_environment_at(x, y)
                parent_n = _clamp(environment.get("parent_nitrogen_index", 0.18))
                parent_p = _clamp(environment.get("parent_phosphorus_index", 0.42))
                self.parent_nitrogen_index_rows[row][column] = parent_n
                self.parent_phosphorus_index_rows[row][column] = parent_p
                self.available_nitrogen_rows[row][column] = 0.015 + parent_n * 0.035
                self.available_phosphorus_rows[row][column] = 0.018 + parent_p * 0.055
                self.mineral_phosphorus_reserve_rows[row][column] = 1.5 + parent_p * 6.5
        self.revision += 1

    @property
    def width(self):
        return self.bounds["max_x"] - self.bounds["min_x"]

    @property
    def height(self):
        return self.bounds["max_y"] - self.bounds["min_y"]

    def cell_center(self, column, row):
        return (
            self.bounds["min_x"] + (column + 0.5) * self.width / self.columns,
            self.bounds["min_y"] + (row + 0.5) * self.height / self.rows,
        )

    def cell_bounds(self, column, row):
        x0 = self.bounds["min_x"] + column * self.width / self.columns
        x1 = self.bounds["min_x"] + (column + 1) * self.width / self.columns
        y0 = self.bounds["min_y"] + row * self.height / self.rows
        y1 = self.bounds["min_y"] + (row + 1) * self.height / self.rows
        return x0, x1, y0, y1

    def _grid_position(self, x, y):
        nx = _clamp((float(x) - self.bounds["min_x"]) / max(1e-9, self.width))
        ny = _clamp((float(y) - self.bounds["min_y"]) / max(1e-9, self.height))
        return nx * (self.columns - 1), ny * (self.rows - 1)

    def _sample_rows(self, values, x, y):
        gx, gy = self._grid_position(x, y)
        x0, y0 = min(self.columns - 2, int(gx)), min(self.rows - 2, int(gy))
        fx, fy = gx - x0, gy - y0
        a, b = values[y0][x0], values[y0][x0 + 1]
        c, d = values[y0 + 1][x0], values[y0 + 1][x0 + 1]
        return (a * (1.0 - fx) + b * fx) * (1.0 - fy) + (c * (1.0 - fx) + d * fx) * fy

    def organic_matter_at(self, x, y):
        return self._sample_rows(self.organic_matter_rows, x, y)

    def litter_at(self, x, y):
        return self._sample_rows(self.litter_rows, x, y)

    def environment_at(self, x, y):
        organic = self.organic_matter_at(x, y)
        litter = self.litter_at(x, y)
        available_n = self._sample_rows(self.available_nitrogen_rows, x, y)
        available_p = self._sample_rows(self.available_phosphorus_rows, x, y)
        return {
            "soil_organic_matter_kg_m2": organic,
            "surface_litter_kg_m2": litter,
            "organic_fertility_index": _clamp(organic / 1.2),
            "surface_stability": _clamp((organic + litter * 0.45) / 0.8),
            "organic_soil_model_version": self.MODEL_VERSION,
            "available_nitrogen_g_m2": available_n,
            "available_phosphorus_g_m2": available_p,
            "organic_nitrogen_g_m2": self._sample_rows(self.organic_nitrogen_rows, x, y),
            "organic_phosphorus_g_m2": self._sample_rows(self.organic_phosphorus_rows, x, y),
            "mineral_phosphorus_reserve_g_m2": self._sample_rows(self.mineral_phosphorus_reserve_rows, x, y),
            "parent_nitrogen_index": self._sample_rows(self.parent_nitrogen_index_rows, x, y),
            "parent_phosphorus_index": self._sample_rows(self.parent_phosphorus_index_rows, x, y),
            "nutrient_pool_units": "g_m2",
        }

    @classmethod
    def requirement_for_tier(cls, tier):
        return cls.TIER_REQUIREMENTS_KG_M2.get(max(0, min(3, int(tier))), cls.TIER_REQUIREMENTS_KG_M2[3])

    def support_at(self, x, y, requirement_kg_m2):
        requirement = max(0.0, float(requirement_kg_m2))
        if requirement <= 0.0:
            return 1.0
        organic = self.organic_matter_at(x, y)
        # A soft transition avoids a one-frame establishment cliff while still
        # making very young mineral substrate unsuitable for demanding plants.
        return _clamp((organic / requirement - 0.45) / 0.55)

    def support_fraction(self, requirement_kg_m2):
        requirement = max(0.0, float(requirement_kg_m2))
        if requirement <= 0.0:
            return 1.0
        # The catalogue asks this for every species on every frame.
        cache = self.__dict__.setdefault("_support_fraction_cache", {})
        # The total guards against rows edited in place without a revision bump.
        key = (self.revision, id(self.organic_matter_rows), requirement,
               sum(map(sum, self.organic_matter_rows)))
        if key not in cache:
            if len(cache) > 64:
                cache.clear()
            supported = sum(value >= requirement for row in self.organic_matter_rows for value in row)
            cache[key] = supported / (self.columns * self.rows)
        return cache[key]

    @staticmethod
    def _patch_density_at(ecology, patch, x, y):
        distance = math.hypot(float(x) - patch.x, float(y) - patch.y)
        if distance > patch.radius_m:
            return 0.0
        profile = ecology.profiles[patch.species_id]
        abundance = patch.abundance * math.sqrt(max(0.0, 1.0 - distance / max(0.05, patch.radius_m)))
        share = getattr(ecology, "stature_share", lambda _patch: 1.0)(patch)
        return abundance * profile.carrying_biomass_kg_m2 * share

    def _cell_climate(self, ecology):
        """Abiotic moisture and temperature of every cell.

        They come from the mineral substrate and climate, which do not change
        while the field keeps its footprint; sampling a generated region for
        each cell each season cost more than the soil chemistry itself.
        """
        substrate = getattr(ecology, "substrate", None)
        key = (
            id(ecology), id(substrate), getattr(substrate, "fingerprint", None),
            tuple(sorted(self.bounds.items())), self.columns, self.rows,
        )
        cached = self.__dict__.get("_cell_climate_cache")
        if cached is None or cached[0] != key:
            sampled = self._abiotic_arrays(ecology, {"soil_moisture": 0.5, "temperature_k": 285.15})
            if sampled is not None:
                fields = sampled[0]
                self._cell_climate_cache = cached = (key, np.stack(
                    [np.clip(fields["soil_moisture"], 0.0, 1.0), fields["temperature_k"]], axis=-1))
                return cached[1]
            rows = []
            for row in range(self.rows):
                values = []
                for column in range(self.columns):
                    abiotic = ecology.abiotic_environment_at(*self.cell_center(column, row))
                    values.append((
                        _clamp(abiotic.get("soil_moisture", 0.5)),
                        float(abiotic.get("temperature_k", 289.0) or 289.0),
                    ))
                rows.append(values)
            cached = (key, rows)
            self._cell_climate_cache = cached
        return cached[1]

    _FIELD_NAMES = (
        "litter_rows", "organic_matter_rows", "litter_nitrogen_rows", "organic_nitrogen_rows",
        "available_nitrogen_rows", "litter_phosphorus_rows", "organic_phosphorus_rows",
        "available_phosphorus_rows", "mineral_phosphorus_reserve_rows",
    )
    _MYCORRHIZA_ACTIVITY = {
        "arbuscular": 0.24, "ectomycorrhizal": 0.18, "ericoid": 0.16, "orchid": 0.08, "mixed": 0.22,
    }
    _FIXATION_RATE = {"active": 0.035, "associated": 0.012}

    def _patch_inputs(self, ecology, shape, cell_x, cell_y):
        """What the season's standing populations put into, and ask of, each cell.

        Each population only touches the cells its disc covers, so the cost
        follows the living area, not cells times populations.
        """
        names = ("litter", "litter_n", "litter_p", "cover", "fixation", "root", "mycorrhiza",
                 "nitrogen_demand", "phosphorus_demand")
        inputs = {name: np.zeros(shape) for name in names}
        cell_width = self.width / self.columns
        cell_height = self.height / self.rows
        feedback_by_species = getattr(ecology, "representative_feedback", {}) or {}
        for patch in ecology.patches:
            radius = patch.radius_m
            first_column = max(0, int(math.floor((patch.x - radius - self.bounds["min_x"]) / cell_width - 0.5)))
            last_column = min(self.columns - 1, int(math.ceil((patch.x + radius - self.bounds["min_x"]) / cell_width - 0.5)))
            first_row = max(0, int(math.floor((patch.y - radius - self.bounds["min_y"]) / cell_height - 0.5)))
            last_row = min(self.rows - 1, int(math.ceil((patch.y + radius - self.bounds["min_y"]) / cell_height - 0.5)))
            if last_column < first_column or last_row < first_row:
                continue
            window = (slice(first_row, last_row + 1), slice(first_column, last_column + 1))
            distance = np.hypot(cell_x[first_column:last_column + 1][None, :] - patch.x,
                                cell_y[first_row:last_row + 1][:, None] - patch.y)
            profile = ecology.profiles[patch.species_id]
            cover = np.where(
                distance > radius, 0.0,
                patch.abundance * np.sqrt(np.maximum(0.0, 1.0 - distance / max(0.05, radius))),
            )
            # Standing biomass, and with it litter, roots and demand, follows
            # the height a stand has reached; the ground it covers does not.
            density = cover * profile.carrying_biomass_kg_m2 * getattr(ecology, "stature_share", lambda _patch: 1.0)(patch)
            litter = density * self.TURNOVER_PER_SEASON.get(profile.growth_form, 0.065)
            inputs["litter"][window] += litter
            # Explicit runtime tissue concentrations (g nutrient per kg
            # litter), pending authored stoichiometry.
            inputs["litter_n"][window] += litter * 12.0
            inputs["litter_p"][window] += litter * 1.2
            inputs["cover"][window] += cover * profile.carrying_biomass_kg_m2 / max(0.05, profile.carrying_biomass_kg_m2)
            feedback = feedback_by_species.get(patch.species_id, {})
            if not profile.surface_growth_profile:
                inputs["root"][window] += density * _clamp(feedback.get("mean_root_exploration", 0.45), 0.05, 1.0)
            mycorrhiza = str(getattr(profile, "mycorrhizal_type", "other_unknown") or "other_unknown").lower()
            inputs["mycorrhiza"][window] += density * self._MYCORRHIZA_ACTIVITY.get(mycorrhiza, 0.0)
            fixation = str(getattr(profile, "nitrogen_fixation", "other_unknown") or "other_unknown").lower()
            inputs["fixation"][window] += density * self._FIXATION_RATE.get(fixation, 0.0)
            inputs["nitrogen_demand"][window] += density * 0.028
            inputs["phosphorus_demand"][window] += density * 0.0034
        return inputs

    def advance(self, ecology, seasons=1):
        """Advance coupled organic matter and bounded plant-available N/P pools."""
        if not self.nutrients_initialized:
            self.initialize_from_abiotic(ecology)
        totals = {key: 0.0 for key in self.last_fluxes}
        step_count = max(0, int(seasons))
        if step_count <= 0:
            return dict(self.last_fluxes)
        cell_count = self.columns * self.rows
        shape = (self.rows, self.columns)
        climate = np.asarray(self._cell_climate(ecology), dtype=np.float64)
        moisture, temperature = climate[..., 0], climate[..., 1]
        temperature_response = np.exp(-((temperature - 290.0) / 18.0) ** 2)
        moisture_response = 0.18 + 0.82 * np.clip(1.0 - np.abs(moisture - 0.58) / 0.58, 0.0, 1.0)
        cell_x = self.bounds["min_x"] + (np.arange(self.columns) + 0.5) * self.width / self.columns
        cell_y = self.bounds["min_y"] + (np.arange(self.rows) + 0.5) * self.height / self.rows
        (litter, organic, litter_n, organic_n, available_n, litter_p, organic_p, available_p, mineral_p) = (
            np.asarray(getattr(self, name), dtype=np.float64) for name in self._FIELD_NAMES
        )
        for _step in range(step_count):
            inputs = self._patch_inputs(ecology, shape, cell_x, cell_y)

            litter = litter + inputs["litter"]
            decomposition_rate = 0.20 * temperature_response * moisture_response
            decomposition = np.minimum(litter, litter * decomposition_rate)
            decomposed_fraction = decomposition / np.maximum(1e-12, litter)
            humified = decomposition * 0.36
            decomposed_loss = decomposition - humified
            bare_fraction = 1.0 - np.clip(inputs["cover"], 0.0, 1.0)
            organic_loss = np.minimum(
                organic,
                organic * (0.003 + 0.010 * bare_fraction * (1.0 - moisture)) * temperature_response,
            )

            litter_n = litter_n + inputs["litter_n"]
            litter_p = litter_p + inputs["litter_p"]
            decomposed_n = np.minimum(litter_n, litter_n * decomposed_fraction)
            decomposed_p = np.minimum(litter_p, litter_p * decomposed_fraction)
            has_organic = organic > 0.0
            safe_organic = np.maximum(1e-12, organic)
            organic_n_loss = np.where(has_organic, np.minimum(organic_n, organic_n * organic_loss / safe_organic), 0.0)
            organic_p_loss = np.where(has_organic, np.minimum(organic_p, organic_p * organic_loss / safe_organic), 0.0)
            nitrogen_mineralization = organic_n * 0.012 * temperature_response * moisture_response
            phosphorus_mineralization = organic_p * 0.009 * temperature_response * moisture_response

            nitrogen_deposition = 0.018 * (0.55 + 0.45 * moisture)
            weathering_fraction = 0.00045 + np.minimum(
                0.0014, inputs["root"] * 0.00035 + inputs["mycorrhiza"] * 0.00045)
            phosphorus_weathering = np.minimum(mineral_p, mineral_p * weathering_fraction * moisture_response)

            organic_n = np.maximum(0.0, organic_n + decomposed_n * 0.36 - nitrogen_mineralization - organic_n_loss)
            organic_p = np.maximum(0.0, organic_p + decomposed_p * 0.36 - phosphorus_mineralization - organic_p_loss)
            available_n = (available_n + decomposed_n * 0.45 + nitrogen_mineralization
                           + nitrogen_deposition + inputs["fixation"])
            available_p = available_p + decomposed_p * 0.64 + phosphorus_mineralization + phosphorus_weathering
            nitrogen_uptake = np.minimum(available_n, inputs["nitrogen_demand"])
            phosphorus_uptake = np.minimum(available_p, inputs["phosphorus_demand"])
            available_n = np.maximum(0.0, available_n - nitrogen_uptake)
            available_p = np.maximum(0.0, available_p - phosphorus_uptake)

            litter = np.minimum(self.MAX_LITTER_KG_M2, np.maximum(0.0, litter - decomposition))
            organic = np.minimum(self.MAX_ORGANIC_MATTER_KG_M2, np.maximum(0.0, organic + humified - organic_loss))
            litter_n = np.maximum(0.0, litter_n - decomposed_n)
            litter_p = np.maximum(0.0, litter_p - decomposed_p)
            mineral_p = np.maximum(0.0, mineral_p - phosphorus_weathering)

            for key, values in (
                ("litter_input_kg_m2", inputs["litter"]),
                ("decomposition_kg_m2", decomposition),
                ("humified_organic_matter_kg_m2", humified),
                ("respired_or_mineralized_kg_m2", decomposed_loss),
                ("organic_matter_loss_kg_m2", organic_loss),
                ("nitrogen_deposition_g_m2", nitrogen_deposition),
                ("biological_nitrogen_fixation_g_m2", inputs["fixation"]),
                ("nitrogen_mineralization_g_m2", nitrogen_mineralization),
                ("nitrogen_uptake_g_m2", nitrogen_uptake),
                ("phosphorus_weathering_g_m2", phosphorus_weathering),
                ("phosphorus_mineralization_g_m2", phosphorus_mineralization),
                ("phosphorus_uptake_g_m2", phosphorus_uptake),
            ):
                totals[key] += float(np.sum(values)) / cell_count
            self.elapsed_seasons += 1
            self.revision += 1
        # The fields stay plain nested lists: tests, the renderer and saved
        # state all index and copy them that way.
        for name, values in zip(self._FIELD_NAMES, (
                litter, organic, litter_n, organic_n, available_n, litter_p, organic_p, available_p, mineral_p)):
            setattr(self, name, values.tolist())
        self.last_fluxes = {key: round(value, 8) for key, value in totals.items()}
        return dict(self.last_fluxes)

    def summary(self):
        values = [value for row in self.organic_matter_rows for value in row]
        litter = [value for row in self.litter_rows for value in row]
        available_n = [value for row in self.available_nitrogen_rows for value in row]
        available_p = [value for row in self.available_phosphorus_rows for value in row]
        organic_n = [value for row in self.organic_nitrogen_rows for value in row]
        organic_p = [value for row in self.organic_phosphorus_rows for value in row]
        mean = sum(values) / len(values) if values else 0.0
        maximum = max(values, default=0.0)
        supported_tier = max(
            tier for tier, requirement in self.TIER_REQUIREMENTS_KG_M2.items()
            if requirement <= maximum + 1e-12
        )
        stage = (
            "barren mineral substrate" if maximum < 0.005 else
            "biocrust soil formation" if supported_tier == 0 else
            "herbaceous pioneer soil" if supported_tier == 1 else
            "developing shrub soil" if supported_tier == 2 else
            "woodland-capable soil"
        )
        return {
            "model_version": self.MODEL_VERSION,
            "elapsed_seasons": self.elapsed_seasons,
            "mean_soil_organic_matter_kg_m2": round(mean, 6),
            "max_soil_organic_matter_kg_m2": round(maximum, 6),
            "mean_surface_litter_kg_m2": round(sum(litter) / len(litter) if litter else 0.0, 6),
            "organic_area_fraction": round(sum(value >= 0.005 for value in values) / len(values) if values else 0.0, 6),
            "mean_available_nitrogen_g_m2": round(sum(available_n) / len(available_n) if available_n else 0.0, 6),
            "mean_available_phosphorus_g_m2": round(sum(available_p) / len(available_p) if available_p else 0.0, 6),
            "mean_organic_nitrogen_g_m2": round(sum(organic_n) / len(organic_n) if organic_n else 0.0, 6),
            "mean_organic_phosphorus_g_m2": round(sum(organic_p) / len(organic_p) if organic_p else 0.0, 6),
            "nutrients_initialized": self.nutrients_initialized,
            "supported_succession_tier": supported_tier,
            "soil_stage": stage,
            "tier_requirements_kg_m2": dict(self.TIER_REQUIREMENTS_KG_M2),
            "last_fluxes": dict(self.last_fluxes),
        }

    def resize_bounds(self, bounds):
        """Resample existing biological state when a procedural domain expands."""
        old_bounds = dict(self.bounds)
        old_columns, old_rows = self.columns, self.rows
        field_names = (
            "litter_rows", "organic_matter_rows", "litter_nitrogen_rows",
            "organic_nitrogen_rows", "available_nitrogen_rows", "litter_phosphorus_rows",
            "organic_phosphorus_rows", "available_phosphorus_rows",
            "mineral_phosphorus_reserve_rows", "parent_nitrogen_index_rows",
            "parent_phosphorus_index_rows",
        )
        old_fields = {name: [list(row) for row in getattr(self, name)] for name in field_names}
        self.bounds = {key: float(bounds[key]) for key in ("min_x", "max_x", "min_y", "max_y")}
        old_cell_width = (old_bounds["max_x"] - old_bounds["min_x"]) / old_columns
        old_cell_height = (old_bounds["max_y"] - old_bounds["min_y"]) / old_rows
        self.columns = max(2, min(128, round(self.width / max(1e-9, old_cell_width))))
        self.rows = max(2, min(128, round(self.height / max(1e-9, old_cell_height))))

        def sample_old(values, x, y, outside=0.0):
            if not (old_bounds["min_x"] <= x <= old_bounds["max_x"] and old_bounds["min_y"] <= y <= old_bounds["max_y"]):
                return outside
            nx = _clamp((x - old_bounds["min_x"]) / max(1e-9, old_bounds["max_x"] - old_bounds["min_x"]))
            ny = _clamp((y - old_bounds["min_y"]) / max(1e-9, old_bounds["max_y"] - old_bounds["min_y"]))
            gx, gy = nx * (old_columns - 1), ny * (old_rows - 1)
            x0, y0 = min(old_columns - 2, int(gx)), min(old_rows - 2, int(gy))
            fx, fy = gx - x0, gy - y0
            a, b = values[y0][x0], values[y0][x0 + 1]
            c, d = values[y0 + 1][x0], values[y0 + 1][x0 + 1]
            return (a * (1.0 - fx) + b * fx) * (1.0 - fy) + (c * (1.0 - fx) + d * fx) * fy

        new_fields = {name: [] for name in field_names}
        outside_defaults = {
            "available_nitrogen_rows": 0.015 + 0.18 * 0.035,
            "available_phosphorus_rows": 0.018 + 0.42 * 0.055,
            "mineral_phosphorus_reserve_rows": 1.5 + 0.42 * 6.5,
            "parent_nitrogen_index_rows": 0.18,
            "parent_phosphorus_index_rows": 0.42,
        }
        for row in range(self.rows):
            output_rows = {name: [] for name in field_names}
            for column in range(self.columns):
                x, y = self.cell_center(column, row)
                for name in field_names:
                    output_rows[name].append(sample_old(old_fields[name], x, y, outside_defaults.get(name, 0.0)))
            for name in field_names:
                new_fields[name].append(output_rows[name])
        for name in field_names:
            setattr(self, name, new_fields[name])
        self.revision += 1

    def to_dict(self):
        return {
            "model_version": self.MODEL_VERSION,
            "bounds": dict(self.bounds),
            "columns": self.columns,
            "rows": self.rows,
            "elapsed_seasons": self.elapsed_seasons,
            "litter_rows": [list(row) for row in self.litter_rows],
            "organic_matter_rows": [list(row) for row in self.organic_matter_rows],
            "litter_nitrogen_rows": [list(row) for row in self.litter_nitrogen_rows],
            "organic_nitrogen_rows": [list(row) for row in self.organic_nitrogen_rows],
            "available_nitrogen_rows": [list(row) for row in self.available_nitrogen_rows],
            "litter_phosphorus_rows": [list(row) for row in self.litter_phosphorus_rows],
            "organic_phosphorus_rows": [list(row) for row in self.organic_phosphorus_rows],
            "available_phosphorus_rows": [list(row) for row in self.available_phosphorus_rows],
            "mineral_phosphorus_reserve_rows": [list(row) for row in self.mineral_phosphorus_reserve_rows],
            "parent_nitrogen_index_rows": [list(row) for row in self.parent_nitrogen_index_rows],
            "parent_phosphorus_index_rows": [list(row) for row in self.parent_phosphorus_index_rows],
            "nutrients_initialized": self.nutrients_initialized,
            "last_fluxes": dict(self.last_fluxes),
        }

    @classmethod
    def from_dict(cls, payload):
        if payload.get("model_version") != cls.MODEL_VERSION:
            raise ValueError("Unsupported organic-soil snapshot")
        field = cls(payload["bounds"], columns=payload["columns"], rows=payload["rows"])
        field_names = (
            "litter_rows", "organic_matter_rows", "litter_nitrogen_rows",
            "organic_nitrogen_rows", "available_nitrogen_rows", "litter_phosphorus_rows",
            "organic_phosphorus_rows", "available_phosphorus_rows",
            "mineral_phosphorus_reserve_rows", "parent_nitrogen_index_rows",
            "parent_phosphorus_index_rows",
        )
        for name in field_names:
            values = payload.get(name) or []
            if len(values) != field.rows or any(len(row) != field.columns for row in values):
                raise ValueError(f"Invalid soil snapshot field: {name}")
            setattr(field, name, [[max(0.0, float(value)) for value in row] for row in values])
        field.nutrients_initialized = bool(payload.get("nutrients_initialized", False))
        field.elapsed_seasons = max(0, int(payload.get("elapsed_seasons", 0)))
        field.last_fluxes = {key: float(value) for key, value in (payload.get("last_fluxes") or {}).items()}
        field.revision = field.elapsed_seasons
        return field
