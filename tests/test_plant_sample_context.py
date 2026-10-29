"""Sample context and saved shrub regression, without manifest field overlays."""
import json
from pathlib import Path

import pytest

from simulations.species.species_simulation import SpeciesSimulation
from tools.plant_mechanics_regression_sample import case_state_label
from world.world_model import WorldModel


@pytest.mark.parametrize("factor,label", [(0, "leafless model season"),
                                          (.5, "foliage 50%"), (1, "full foliage")])
def test_sample_reports_season_separately_from_development(factor, label):
    text = case_state_label({"phase": "juvenile", "leaf_factor": factor})
    assert text == f"juvenile | {label} | independent scale"
    assert case_state_label({"phase": "juvenile"}) == "juvenile | independent scale"


def test_live_saved_rose_keeps_recorded_flowering_and_seasonal_contract():
    # Unlike the architecture fixture, this consumes the saved record directly.
    world = WorldModel()
    original = world.loader.get("spec_rosa_woodsii")
    sim = SpeciesSimulation(world_model=world, species_id="spec_rosa_woodsii", seed=303)
    sim.set_lod(2)
    recorded = json.loads((Path(__file__).parent / "fixtures" / "woods_rose_contract.json").read_text())
    sim.set_age(180)
    assert sim.blueprint.fingerprint() == recorded["fingerprint"]
    assert sim.life_state() == recorded["life_state"]
    for key in ("shrub_cane_count", "leaf_count", "shrub_flower_count", "shrub_fruit_count",
                "leaf_area_m2", "placement_count"):
        assert sim.render_snapshot.stats[key] == recorded["stats"][key]
    sim.set_age(49.068)
    assert sim.life_state()["leaf_factor"] == 0
    assert sim.render_snapshot.stats["leaf_count"] == 0
    sim.set_age(330)
    assert sim.life_state()["phase"] == "dormant"
    assert sim.render_snapshot.stats["shrub_cane_count"] == 8
    assert sim.render_snapshot.stats["shrub_fruit_count"] == 124
    assert world.loader.get("spec_rosa_woodsii") == original


@pytest.mark.parametrize("donor", ["spec_lysimachia_arvensis", "spec_nuttallanthus_canadensis",
                                  "spec_symphyotrichum_novaeangliae"])
def test_herb_shoot_profiles_do_not_activate_on_saved_woody_shrub(donor):
    world = WorldModel()
    rose = world.resolved_species_entity("spec_rosa_woodsii")
    profile = world.resolved_species_entity(donor)["plant_shoot_profile"]
    baseline = SpeciesSimulation(species_entity=rose, seed=303)
    treatment = SpeciesSimulation(species_entity={**rose, "plant_shoot_profile": profile}, seed=303)
    baseline.set_age(180)
    treatment.set_age(180)
    assert baseline.blueprint.fingerprint() == treatment.blueprint.fingerprint()
    assert baseline.generate_snapshot(180, 2).to_dict() == treatment.generate_snapshot(180, 2).to_dict()
