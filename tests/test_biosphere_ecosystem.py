import math

from simulations.bioregion.bioregion_grid import BioregionGrid
from simulations.bioregion.bioregion_simulation import BioregionSimulation
from simulations.bioregion.ecosystem import ProducerSoilEcosystem
from simulations.bioregion.reference_site import build_reference_site_models


def _one_cell_grid(**overrides):
    grid = BioregionGrid(1, 1, 10.0, 10.0)
    cell = grid.get_cell(0, 0)
    cell.update({
        "soil_type": "loam",
        "top_moisture": 0.55,
        "deep_moisture": 0.62,
        "plant_biomass": 0.35,
        "plant_health": 0.8,
        "temperature_k": 293.0,
        "solar_exposure": 1.0,
    })
    cell.update(overrides)
    return grid, cell


def _carbon_pools(cell):
    return sum(float(cell[key]) for key in (
        "plant_biomass_kg_m2", "litter_kg_m2", "soil_organic_matter_kg_m2",
    ))


def test_reference_site_uses_worldgen_lod4_contract_without_claiming_generation():
    models = build_reference_site_models(size=21)
    heightmap = models["heightmap_model"]
    assert heightmap["map_detail_level"] == 4
    assert heightmap["detail_level_name"] == "site"
    assert heightmap["sample_spacing_x_m"] == 10.0
    assert heightmap["status"] == "authored_reference_fixture"
    assert heightmap["parent_map_id"].endswith("lod3_local_catchment")
    assert models["true_color_model"]["vegetation"] is False
    assert len(models["river_model"]["rivers"][0]["points_m"]) > 20
    rows = heightmap["sample_grid"]["rows"]
    assert max(value for row in rows for value in row) - min(value for row in rows for value in row) > 25.0


def test_reference_site_enters_bioregion_through_normalized_worldgen_boundary():
    sim = BioregionSimulation.reference_site()
    assert sim.grid.total_cells_side == 100
    assert sim.get_scope_label().endswith("1000 m x 1000 m")
    assert sim.worldgen_context["source_entity_id"] == "reference_biosphere_lod4_catchment"
    cells = list(sim.grid.iter_cells())
    assert len(cells) == 10_000
    assert len({cell["soil_type"] for cell in cells}) >= 3
    assert any(cell["surface_water"] > 0.25 for cell in cells)
    assert all(cell["ecosystem_model_version"] == "producer-soil-light-v1" for cell in cells)


def test_ecosystem_is_deterministic_and_wet_cells_outperform_dry_cells():
    wet_grid, wet = _one_cell_grid(top_moisture=0.65, deep_moisture=0.70)
    dry_grid, dry = _one_cell_grid(top_moisture=0.05, deep_moisture=0.08)
    wet_kernel = ProducerSoilEcosystem()
    dry_kernel = ProducerSoilEcosystem()
    wet_kernel.initialize_grid(wet_grid)
    dry_kernel.initialize_grid(dry_grid)
    wet_initial = wet["plant_biomass_kg_m2"]
    dry_initial = dry["plant_biomass_kg_m2"]
    wet_flux = wet_kernel.step_grid(wet_grid, days=30.0)
    dry_flux = dry_kernel.step_grid(dry_grid, days=30.0)
    assert wet["plant_biomass_kg_m2"] - wet_initial > dry["plant_biomass_kg_m2"] - dry_initial
    assert wet_flux["gross_primary_production_kg_m2"] > dry_flux["gross_primary_production_kg_m2"]

    repeat_grid, repeat = _one_cell_grid(top_moisture=0.65, deep_moisture=0.70)
    repeat_kernel = ProducerSoilEcosystem()
    repeat_kernel.initialize_grid(repeat_grid)
    assert repeat_kernel.step_grid(repeat_grid, days=30.0) == wet_flux
    assert repeat == wet


def test_carbon_transfers_close_and_state_stays_finite_and_bounded():
    grid, cell = _one_cell_grid()
    kernel = ProducerSoilEcosystem()
    kernel.initialize_grid(grid)
    initial_carbon = _carbon_pools(cell)
    flux = kernel.step_grid(grid, days=45.0)
    final_carbon = _carbon_pools(cell)
    expected = (
        initial_carbon
        + flux["gross_primary_production_kg_m2"]
        - flux["plant_respiration_kg_m2"]
        - flux["soil_respiration_kg_m2"]
    )
    assert math.isclose(final_carbon, expected, rel_tol=0.0, abs_tol=2e-7)
    assert 0.0 <= cell["plant_biomass"] <= 1.0
    assert 0.0 <= cell["plant_health"] <= 1.0
    assert 0.0 <= cell["top_moisture"] <= 1.0
    assert all(math.isfinite(float(value)) for value in cell["ecosystem_fluxes"].values())

