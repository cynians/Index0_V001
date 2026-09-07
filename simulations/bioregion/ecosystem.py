"""Small deterministic ecological kernel for Bioregion Simulation.

This module owns evolving biological state, not ontology truth.  Values on a
grid cell are transient runtime products.  The first implementation closes a
producer/soil/water/light loop without pretending to be a calibrated ecosystem
model: light and soil water constrain production; plants consume water and
nitrogen; turnover creates litter; decomposition returns organic matter and
mineral nitrogen; canopy cover changes the light environment.

The physical-unit fields make the fluxes inspectable.  The historical
``plant_biomass`` and moisture fields remain normalized renderer adapters.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, asdict


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, float(value)))


@dataclass
class EcosystemFluxLedger:
    gross_primary_production_kg_m2: float = 0.0
    plant_respiration_kg_m2: float = 0.0
    litter_input_kg_m2: float = 0.0
    decomposition_kg_m2: float = 0.0
    soil_respiration_kg_m2: float = 0.0
    water_uptake_mm: float = 0.0
    nitrogen_uptake_g_m2: float = 0.0
    nitrogen_mineralized_g_m2: float = 0.0

    def to_dict(self):
        return {key: round(value, 8) for key, value in asdict(self).items()}


class ProducerSoilEcosystem:
    """Deterministic producer/soil coupling over an existing BioregionGrid."""

    MODEL_VERSION = "producer-soil-light-v1"
    BIOMASS_AT_FULL_COVER_KG_M2 = 2.5
    BASE_PRODUCTIVITY_KG_M2_DAY = 0.045
    BASE_TURNOVER_PER_DAY = 0.0012
    SOIL_WATER_CAPACITY_MM = {
        "very_sandy": 65.0,
        "sandy_loam": 105.0,
        "loam": 145.0,
        "clay_loam": 175.0,
        "heavy_clay": 190.0,
    }

    def __init__(self, seconds_per_ecological_day=60.0):
        # This is an explicit interactive-preview time scale.  Direct
        # experiments should call step_grid(..., days=N) in ecological days.
        self.seconds_per_ecological_day = max(1.0, float(seconds_per_ecological_day))
        self.elapsed_days = 0.0
        self.last_flux_totals = EcosystemFluxLedger().to_dict()

    def initialize_grid(self, grid):
        for cell in grid.iter_cells():
            biomass = max(
                0.015,
                float(cell.get("plant_biomass_kg_m2") or 0.0),
                float(cell.get("plant_biomass", 0.0) or 0.0)
                * self.BIOMASS_AT_FULL_COVER_KG_M2,
            )
            soil_type = cell.get("soil_type", "loam")
            organic_default = {
                "very_sandy": 0.7,
                "sandy_loam": 1.5,
                "loam": 2.8,
                "clay_loam": 3.2,
                "heavy_clay": 3.6,
            }.get(soil_type, 2.0)
            cell.setdefault("plant_biomass_kg_m2", biomass)
            cell.setdefault("leaf_area_index", _clamp(biomass / 0.72, 0.02, 6.5))
            cell.setdefault("litter_kg_m2", 0.12 + biomass * 0.08)
            cell.setdefault("soil_organic_matter_kg_m2", organic_default)
            cell.setdefault("available_nitrogen_g_m2", 5.5 + organic_default * 0.8)
            cell.setdefault("surface_par_mol_m2_day", 34.0)
            cell.setdefault("canopy_ground_light_fraction", math.exp(-0.58 * cell["leaf_area_index"]))
            cell.setdefault("solar_exposure", 1.0)
            cell.setdefault("temperature_k", 289.0)
            cell.setdefault("soil_water_capacity_mm", self.SOIL_WATER_CAPACITY_MM.get(soil_type, 140.0))
            cell.setdefault("erosion_resistance", _clamp(0.18 + biomass * 0.24 + organic_default * 0.035))
            cell.setdefault("ecosystem_model_version", self.MODEL_VERSION)
            cell.setdefault("ecosystem_fluxes", EcosystemFluxLedger().to_dict())
            self._sync_display_fields(cell, health=cell.get("plant_health", 0.5))

    def update_grid(self, grid, dt_seconds):
        days = max(0.0, float(dt_seconds)) / self.seconds_per_ecological_day
        if days <= 0.0:
            return self.last_flux_totals
        return self.step_grid(grid, days=days)

    def step_grid(self, grid, *, days=1.0):
        """Advance all cells, returning an equal-area mean flux ledger.

        Steps larger than one day are internally subdivided.  This keeps the
        result bounded and makes a ten-day call comparable to ten one-day
        calls without making the renderer responsible for solver stability.
        """
        remaining = max(0.0, float(days))
        totals = EcosystemFluxLedger()
        cells = list(grid.iter_cells())
        if not cells:
            self.last_flux_totals = totals.to_dict()
            return dict(self.last_flux_totals)
        while remaining > 1e-12:
            step = min(1.0, remaining)
            step_totals = EcosystemFluxLedger()
            for cell in cells:
                flux = self._step_cell(cell, step)
                for field_name in asdict(step_totals):
                    setattr(
                        step_totals,
                        field_name,
                        getattr(step_totals, field_name) + getattr(flux, field_name),
                    )
            for field_name in asdict(totals):
                setattr(
                    totals,
                    field_name,
                    getattr(totals, field_name) + getattr(step_totals, field_name) / len(cells),
                )
            remaining -= step
            self.elapsed_days += step
        self.last_flux_totals = totals.to_dict()
        return dict(self.last_flux_totals)

    def _step_cell(self, cell, days):
        biomass = max(0.0, float(cell.get("plant_biomass_kg_m2", 0.0) or 0.0))
        litter = max(0.0, float(cell.get("litter_kg_m2", 0.0) or 0.0))
        organic = max(0.0, float(cell.get("soil_organic_matter_kg_m2", 0.0) or 0.0))
        nitrogen = max(0.0, float(cell.get("available_nitrogen_g_m2", 0.0) or 0.0))
        temperature = float(cell.get("temperature_k", 289.0) or 289.0)
        top_moisture = _clamp(cell.get("top_moisture", 0.0))
        deep_moisture = _clamp(cell.get("deep_moisture", 0.0))
        water = top_moisture * 0.72 + deep_moisture * 0.28

        leaf_area = _clamp(biomass / 0.72, 0.02, 6.5)
        par = max(0.0, float(cell.get("surface_par_mol_m2_day", 34.0) or 0.0))
        exposure = _clamp(cell.get("solar_exposure", 1.0), 0.15, 1.25)
        ground_light = math.exp(-0.58 * leaf_area)
        absorbed_light = 1.0 - ground_light
        light_response = 1.0 - math.exp(-(par * exposure) / 18.0)
        water_response = _clamp((water - 0.07) / 0.38)
        temperature_response = math.exp(-((temperature - 293.0) / 15.0) ** 2)
        nitrogen_response = nitrogen / (nitrogen + 4.0) if nitrogen > 0.0 else 0.0
        production_response = light_response * water_response * temperature_response * nitrogen_response

        gross = self.BASE_PRODUCTIVITY_KG_M2_DAY * absorbed_light * production_response * days
        respiration = biomass * 0.0018 * (2.0 ** ((temperature - 293.0) / 10.0)) * days
        stress = 1.0 - (water_response * temperature_response * nitrogen_response)
        turnover = biomass * (self.BASE_TURNOVER_PER_DAY + stress * 0.0024) * days
        nitrogen_uptake = min(nitrogen, gross * 0.72)
        water_uptake = min(
            max(0.0, top_moisture) * float(cell.get("soil_water_capacity_mm", 140.0) or 140.0),
            gross * 55.0 + biomass * 0.20 * water_response * days,
        )

        decomposition = min(litter + turnover, litter * 0.0035 * temperature_response * (0.2 + 0.8 * water_response) * days)
        organic_gain = decomposition * 0.32
        soil_respiration = decomposition - organic_gain
        mineralized = decomposition * 0.55

        biomass = max(0.0, biomass + gross - respiration - turnover)
        litter = max(0.0, litter + turnover - decomposition)
        organic = max(0.0, organic + organic_gain)
        nitrogen = max(0.0, nitrogen + mineralized - nitrogen_uptake)
        capacity = max(1.0, float(cell.get("soil_water_capacity_mm", 140.0) or 140.0))
        top_moisture = _clamp(top_moisture - water_uptake / capacity)

        health_target = _clamp((water_response + temperature_response + nitrogen_response) / 3.0)
        health = _clamp(float(cell.get("plant_health", health_target) or 0.0) * 0.90 + health_target * 0.10)
        erosion_resistance = _clamp(0.12 + biomass * 0.20 + organic * 0.045)

        updated_leaf_area = _clamp(biomass / 0.72, 0.02, 6.5)
        updated_ground_light = math.exp(-0.58 * updated_leaf_area)
        cell.update({
            "plant_biomass_kg_m2": biomass,
            "leaf_area_index": updated_leaf_area,
            "litter_kg_m2": litter,
            "soil_organic_matter_kg_m2": organic,
            "available_nitrogen_g_m2": nitrogen,
            "canopy_ground_light_fraction": updated_ground_light,
            "top_moisture": top_moisture,
            "erosion_resistance": erosion_resistance,
        })
        self._sync_display_fields(cell, health=health)
        flux = EcosystemFluxLedger(
            gross_primary_production_kg_m2=gross,
            plant_respiration_kg_m2=respiration,
            litter_input_kg_m2=turnover,
            decomposition_kg_m2=decomposition,
            soil_respiration_kg_m2=soil_respiration,
            water_uptake_mm=water_uptake,
            nitrogen_uptake_g_m2=nitrogen_uptake,
            nitrogen_mineralized_g_m2=mineralized,
        )
        cell["ecosystem_fluxes"] = flux.to_dict()
        return flux

    def _sync_display_fields(self, cell, *, health):
        biomass = max(0.0, float(cell.get("plant_biomass_kg_m2", 0.0) or 0.0))
        cell["plant_biomass"] = _clamp(biomass / self.BIOMASS_AT_FULL_COVER_KG_M2)
        cell["plant_health"] = _clamp(health)
