import math

import pytest

from simulations.biosphere.biosphere_simulation import BiosphereSimulation
from simulations.biosphere.soil_succession import SoilOrganicMatterField


def test_lifeless_patch_starts_with_zero_biological_soil_and_stays_barren_without_life():
    sim = BiosphereSimulation.reference_site()

    initial = sim.soil.summary()
    sim.advance_seasons(20)
    after = sim.soil.summary()

    assert initial["mean_soil_organic_matter_kg_m2"] == 0.0
    assert initial["mean_surface_litter_kg_m2"] == 0.0
    assert initial["soil_stage"] == "barren mineral substrate"
    assert after["mean_soil_organic_matter_kg_m2"] == 0.0
    assert after["mean_surface_litter_kg_m2"] == 0.0


def test_lichen_turnover_builds_local_litter_then_stable_organic_matter_deterministically():
    first = BiosphereSimulation.reference_site()
    second = BiosphereSimulation.reference_site()
    for simulation in (first, second):
        simulation.place_selected_species(5.0, 5.0)
        simulation.advance_seasons(8)

    summary = first.soil.summary()
    assert summary["mean_surface_litter_kg_m2"] > 0.0
    assert summary["mean_soil_organic_matter_kg_m2"] > 0.0
    assert summary["max_soil_organic_matter_kg_m2"] > summary["mean_soil_organic_matter_kg_m2"]
    assert summary["organic_area_fraction"] < 0.2
    assert first.soil.to_dict() == second.soil.to_dict()


def test_succession_unlocks_in_soil_order_not_total_biomass_order():
    sim = BiosphereSimulation.reference_site()
    lichen = sim.ecology.profiles[sim.BIOMASSER_ID]
    grass = sim.ecology.profiles["spec_lolium_perenne"]
    tree = sim.ecology.profiles["spec_betula_pendula"]

    assert (lichen.succession_tier, grass.succession_tier, tree.succession_tier) == (0, 1, 3)
    assert sim.is_species_unlocked(lichen.species_id)
    assert not sim.is_species_unlocked(grass.species_id)
    assert not sim.is_species_unlocked(tree.species_id)
    assert not sim.is_species_unlocked("spec_nymphaea_alba")

    sim.place_selected_species(5.0, 5.0)
    for _ in range(60):
        if sim.is_species_unlocked(grass.species_id):
            break
        sim.advance_seasons(1)
    assert sim.is_species_unlocked(grass.species_id)
    assert not sim.is_species_unlocked(tree.species_id)

    for _ in range(120):
        if sim.is_species_unlocked(tree.species_id):
            break
        sim.advance_seasons(1)
    assert sim.is_species_unlocked(tree.species_id)


def test_organic_support_is_local_and_increases_environment_fertility_without_replacing_minerals():
    sim = BiosphereSimulation.reference_site()
    sim.place_selected_species(5.0, 5.0)
    sim.advance_seasons(8)

    centre = sim.ecology.environment_at(5.0, 5.0)
    corner = sim.ecology.environment_at(0.1, 0.1)

    assert centre["soil_organic_matter_kg_m2"] > corner["soil_organic_matter_kg_m2"]
    assert centre["organic_fertility_index"] > corner["organic_fertility_index"]
    assert centre["soil_fertility_source"] == "biosphere organic matter; mineral nutrients unresolved"


def test_organic_soil_snapshot_round_trip_and_bounds_are_finite():
    sim = BiosphereSimulation.reference_site()
    sim.place_selected_species(5.0, 5.0)
    sim.advance_seasons(6)

    restored = SoilOrganicMatterField.from_dict(sim.soil.to_dict())

    assert restored.to_dict() == sim.soil.to_dict()
    assert all(
        math.isfinite(value) and 0.0 <= value <= restored.MAX_ORGANIC_MATTER_KG_M2
        for row in restored.organic_matter_rows for value in row
    )
    assert all(
        math.isfinite(value) and 0.0 <= value <= restored.MAX_LITTER_KG_M2
        for row in restored.litter_rows for value in row
    )


def test_expanding_procedural_domain_preserves_old_soil_and_adds_barren_margin():
    sim = BiosphereSimulation.reference_site()
    sim.place_selected_species(5.0, 5.0)
    sim.advance_seasons(6)
    old_centre = sim.soil.organic_matter_at(5.0, 5.0)

    sim.soil.resize_bounds({"min_x": -5.0, "max_x": 15.0, "min_y": -5.0, "max_y": 15.0})

    assert sim.soil.organic_matter_at(5.0, 5.0) == pytest.approx(old_centre, rel=0.15)
    assert sim.soil.organic_matter_at(-4.5, -4.5) == 0.0


def test_worldgen_abiotic_fields_are_unchanged_by_biological_soil():
    class FixedSubstrate:
        def environment_at(self, _x, _y):
            return {
                "soil_moisture": 0.62,
                "surface_solar_exposure": 0.88,
                "temperature_k": 291.0,
                "soil_depth_m": 0.42,
                "soil_ph": 6.15,
                "soil_fertility": 0.28,
                "runtime_default_fields": (),
                "open_water": False,
                "terrain_elevation_known": True,
            }

        def terrestrial_habitat_at(self, _x, _y):
            return True

    sim = BiosphereSimulation.reference_site()
    sim.ecology.substrate = FixedSubstrate()
    before = sim.ecology.abiotic_environment_at(5.0, 5.0)
    sim.ecology.introduce(sim.BIOMASSER_ID, 5.0, 5.0, 0.7, 0.35)
    sim.ecology.advance(8)
    after = sim.ecology.abiotic_environment_at(5.0, 5.0)
    combined = sim.ecology.environment_at(5.0, 5.0)

    assert after == before
    assert combined["soil_depth_m"] == 0.42
    assert combined["soil_ph"] == 6.15
    assert combined["soil_organic_matter_kg_m2"] > 0.0
    assert combined["mineral_nutrient_index"] == 0.28
