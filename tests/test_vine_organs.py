"""Portable opt-in vine organs, seasonality and canonical LOD contracts."""
import json
import math
from copy import deepcopy
from pathlib import Path

import pytest

from simulations.species.plant_assets import PlantBlueprint, PlantGrowthSnapshot
from simulations.species.species_simulation import SpeciesSimulation


@pytest.fixture
def entity():
    updates = json.loads(Path("assets/plant_asset_specs/spec_celastrus_orbiculatus.json").read_text())["species_field_updates"]
    updates.pop('plant_shoot_profile',None)  # Exercise the original single-axis organ path.
    return {"id": "spec_unrelated_seasonal_vine", **deepcopy(updates)}


ENV = {"climbing_supports": [{"id": "support", "kind": "tree", "position_m": [.5, 0, 0],
                               "height_m": 4., "radius_m": .06}]}


def simulate(entity, age=150, lod=2, environment=ENV):
    sim = SpeciesSimulation(species_entity=entity, seed=303, environment=deepcopy(environment))
    sim.set_lod(lod)
    sim.set_age(age)
    return sim


def test_transport_portability_and_independent_reuse(entity):
    sim = simulate(entity)
    assert sim.blueprint.growth["vine_organ_geometry_version"] == 1
    assert sim.blueprint.module("flower").visual["depicted_size_m"] == .02
    assert sim.blueprint.module("fruit").visual["depicted_size_m"] == .013
    assert PlantBlueprint.from_dict(sim.blueprint.to_dict()).fingerprint() == sim.blueprint.fingerprint()
    snap = sim.render_snapshot.to_dict()
    assert PlantGrowthSnapshot.from_dict(snap).to_dict() == snap
    assert simulate(entity).render_snapshot.to_dict() == snap
    assert sim.render_snapshot.stats["vine_support_contact_count"] == 1


@pytest.mark.parametrize("invalid", [None, {}, {"cycle_days": float("nan")}, True])
def test_missing_invalid_recipe_preserves_legacy_vine(entity, invalid):
    entity.pop("plant_reproductive_profile")
    base = simulate(entity)
    bad = simulate({**entity, "plant_reproductive_profile": invalid})
    assert "vine_organ_geometry_version" not in bad.blueprint.growth
    assert base.blueprint.fingerprint() == bad.blueprint.fingerprint()
    assert base.render_snapshot.to_dict() == bad.render_snapshot.to_dict()


def test_axillary_attachment_and_helix_clearance(entity):
    snap = simulate(entity).render_snapshot
    stems = {i: p for i,p in enumerate(snap.placements) if p[0] == "stem_section"}
    for socket in snap.attachment_points:
        if socket.get("socket") != "leaf":
            continue
        stem, leaf = stems[socket["stem_placement_index"]], snap.placements[socket["leaf_placement_index"]]
        assert leaf[2:5] == stem[2:5]
        assert math.dist(socket["position_m"], stem[2:5]) < 1e-4
    flowering = [p for p in snap.placements if p[0] == "flower"]
    assert len(flowering) > 1
    assert all(p[2:5] == stems[p[1]][2:5] for p in flowering)
    for socket in snap.attachment_points:
        if socket.get("side") != "climbing_axis" or socket.get("socket") != "support_contact":
            continue
        path = snap.placement_paths[str(socket["stem_placement_index"])]
        assert len(path) == 8
        for x,y,z in path:
            assert math.hypot(x-.5,y) == pytest.approx(.095, abs=.0002)
            assert 0 <= z <= 4.001
    assert all(p[1] < i for i,p in enumerate(snap.placements))


def test_seasonal_transition_and_perennial_repeat(entity):
    flowers = simulate(entity,150).render_snapshot
    fruit = simulate(entity,265).render_snapshot
    winter = simulate(entity,345).render_snapshot
    next_spring = simulate(entity,510).render_snapshot
    assert flowers.stats["vine_flower_cyme_count"] > 0
    assert flowers.stats["vine_fruit_sample_count"] == 0
    assert fruit.stats["vine_flower_cyme_count"] == 0
    assert fruit.stats["vine_fruit_sample_count"] > 0
    assert winter.stats["estimated_leaf_count"] == 0
    assert winter.stats["vine_fruit_sample_count"] > 0
    assert next_spring.stats["vine_flower_cyme_count"] == flowers.stats["vine_flower_cyme_count"]
    assert not simulate(entity,25).render_snapshot.stats["vine_flower_cyme_count"]
    assert not simulate({**entity,"reproductive_mode":"vegetative"},265).render_snapshot.stats["vine_fruit_sample_count"]
    assert not simulate({**entity,"plant_flowering_position":"terminal"}).render_snapshot.stats["vine_flower_cyme_count"]


@pytest.mark.parametrize("age", [150,265,345])
def test_lod_keeps_canonical_leaf_area_ecology_and_axes(entity, age):
    cases = [simulate(entity,age,lod) for lod in range(3)]
    for key in ["estimated_leaf_count","leaf_area_m2","vine_axis_length_m","vine_climbing_height_m",
                "vine_flower_cyme_count","vine_fruit_sample_count"]:
        assert len({s.render_snapshot.stats[key] for s in cases}) == 1
    outcomes = [s.get_ecological_outcome({}) for s in cases]
    assert outcomes[0] == outcomes[1] == outcomes[2]
    assert not any(p[0] == "leaf" for p in cases[0].render_snapshot.placements)


def test_unsupported_vine_stays_grounded_and_support_is_not_intrinsic(entity):
    sim = simulate(entity,environment={})
    stats = sim.render_snapshot.stats
    assert stats["vine_phase"] == "ground_search"
    assert stats["vine_axis_length_m"] <= stats["vine_axis_budget_m"] + .001
    assert max(p[4] for p in sim.render_snapshot.placements if p[0]=="stem_section") < .08
    assert "climbing_supports" not in sim.blueprint.growth


def test_opt_in_is_restricted_to_along_stem_climbers(entity):
    assert "vine_organ_geometry_version" not in PlantBlueprint.from_species_entity(
        {**entity, "plant_growth_form":"shrub","plant_growth_behaviour":"branched_woody"}).growth
    assert "vine_organ_geometry_version" not in PlantBlueprint.from_species_entity(
        {**entity,"leaf_attachment_pattern":"other_unknown"}).growth
