import math

import pytest

from simulations.biosphere.biosphere_simulation import BiosphereSimulation
from simulations.species.plant_assets import PlantBlueprint
from simulations.species.plant_nutrition import resolve_plant_nutrient_response
from simulations.species.species_simulation import SpeciesSimulation


def test_blueprint_carries_authored_nutrition_traits_and_changes_fingerprint():
    base = {
        "id": "spec_nutrient_test",
        "plant_growth_form": "forb",
        "root_architecture": "fibrous",
        "root_depth_class": "shallow",
        "nitrogen_fixation": "none",
        "nutrition_mode": "autotrophic",
        "mycorrhizal_type": "none",
    }
    plain = PlantBlueprint.from_species_entity(base)
    symbiotic = PlantBlueprint.from_species_entity({**base, "mycorrhizal_type": "arbuscular"})

    assert plain.growth["nitrogen_fixation"] == "none"
    assert plain.growth["nutrition_mode"] == "autotrophic"
    assert symbiotic.growth["mycorrhizal_type"] == "arbuscular"
    assert plain.fingerprint() != symbiotic.fingerprint()


def test_mycorrhiza_improves_phosphorus_access_but_never_creates_phosphorus():
    environment = {"available_nitrogen_g_m2": 0.4, "available_phosphorus_g_m2": 0.025}
    roots = {"root_depth_m": 0.2, "root_spread_m": 0.8}
    none = resolve_plant_nutrient_response({"mycorrhizal_type": "none"}, environment, roots)
    arbuscular = resolve_plant_nutrient_response({"mycorrhizal_type": "arbuscular"}, environment, roots)
    zero = resolve_plant_nutrient_response(
        {"mycorrhizal_type": "arbuscular"},
        {**environment, "available_phosphorus_g_m2": 0.0},
        roots,
    )

    assert arbuscular["phosphorus_response"] > none["phosphorus_response"]
    assert zero["phosphorus_response"] == 0.0


def test_missing_environment_is_neutral_but_explicit_zero_is_limiting():
    unresolved = resolve_plant_nutrient_response({}, {})
    zero = resolve_plant_nutrient_response(
        {}, {"available_nitrogen_g_m2": 0.0, "available_phosphorus_g_m2": 0.0}
    )

    assert unresolved["nitrogen_response"] == 1.0
    assert unresolved["phosphorus_response"] == 1.0
    assert unresolved["nutrient_environment_status"]["nitrogen"] == "unresolved_neutral"
    assert zero["nitrogen_response"] == 0.0
    assert zero["phosphorus_response"] == 0.0


def test_species_sim_uses_nutrient_stress_and_only_authored_fixation():
    entity = {
        "id": "spec_n_fixation_test",
        "plant_growth_form": "forb",
        "nitrogen_fixation": "none",
        "mycorrhizal_type": "none",
    }
    plain = SpeciesSimulation(species_entity=entity, seed=71)
    fixer = SpeciesSimulation(species_entity={**entity, "nitrogen_fixation": "active"}, seed=71)
    plain.set_age(plain.mature_age_days)
    fixer.set_age(fixer.mature_age_days)
    environment = {
        "available_nitrogen_g_m2": 0.0,
        "available_phosphorus_g_m2": 0.5,
    }

    plain_outcome = plain.get_ecological_outcome(environment)
    fixer_outcome = fixer.get_ecological_outcome(environment)

    assert plain_outcome["nitrogen_response"] == 0.0
    assert fixer_outcome["nitrogen_response"] > 0.0
    assert fixer_outcome["vitality"] > plain_outcome["vitality"]


def test_lifeless_soil_has_only_inorganic_fluxes_and_zero_organic_nutrients():
    sim = BiosphereSimulation.reference_site()
    initial = sim.soil.summary()
    sim.advance_seasons(6)
    after = sim.soil.summary()

    assert initial["nutrients_initialized"]
    assert after["mean_organic_nitrogen_g_m2"] == 0.0
    assert after["mean_organic_phosphorus_g_m2"] == 0.0
    assert after["mean_available_nitrogen_g_m2"] > initial["mean_available_nitrogen_g_m2"]
    assert after["last_fluxes"]["biological_nitrogen_fixation_g_m2"] == 0.0
    assert after["last_fluxes"]["nitrogen_uptake_g_m2"] == 0.0
    assert after["last_fluxes"]["phosphorus_uptake_g_m2"] == 0.0


def test_living_population_cycles_and_draws_down_finite_nutrient_pools():
    sim = BiosphereSimulation.reference_site()
    sim.place_selected_species(5.0, 5.0)
    sim.advance_seasons(8)
    summary = sim.soil.summary()
    centre = sim.ecology.environment_at(5.0, 5.0)

    assert summary["mean_organic_nitrogen_g_m2"] > 0.0
    assert summary["mean_organic_phosphorus_g_m2"] > 0.0
    assert summary["last_fluxes"]["nitrogen_uptake_g_m2"] > 0.0
    assert summary["last_fluxes"]["phosphorus_uptake_g_m2"] > 0.0
    assert centre["available_nitrogen_g_m2"] >= 0.0
    assert centre["available_phosphorus_g_m2"] >= 0.0
    assert all(
        math.isfinite(value) and value >= 0.0
        for name in (
            "litter_nitrogen_rows", "organic_nitrogen_rows", "available_nitrogen_rows",
            "litter_phosphorus_rows", "organic_phosphorus_rows", "available_phosphorus_rows",
            "mineral_phosphorus_reserve_rows",
        )
        for row in getattr(sim.soil, name) for value in row
    )


def test_representative_feedback_exposes_nutrient_and_root_handoff():
    sim = BiosphereSimulation.reference_site()
    sim.place_selected_species(5.0, 5.0)
    sim.advance_seasons(1)
    feedback = sim.last_representative_feedback[sim.BIOMASSER_ID]

    assert 0.0 <= feedback["mean_nitrogen_response"] <= 1.0
    assert 0.0 <= feedback["mean_phosphorus_response"] <= 1.0
    assert 0.0 <= feedback["mean_root_exploration"] <= 1.0
    outcome = sim.representatives.items(sim.BIOMASSER_ID, alive_only=True)[0].last_outcome
    assert outcome["limiting_nutrient"] in {"nitrogen", "phosphorus"}
    assert outcome["trait_provenance"]["nitrogen_fixation"] == "neutral_missing_default"
