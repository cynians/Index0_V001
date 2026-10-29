"""Mature candidate presentation and progressive root development contracts."""
import math

import pytest

from simulations.species.plant_assets import PlantBlueprint, PlantGrowthSnapshot
from simulations.species.preview_timing import mature_preview_age
from simulations.species.root_growth import root_profile, build_root_graph, build_distributed_adventitious_roots
from simulations.species.species_simulation import SpeciesSimulation
from world.world_model import WorldModel


@pytest.mark.parametrize("architecture", ["taproot", "fibrous", "adventitious", "mixed"])
def test_seedling_roots_start_small_and_develop_monotonically(architecture):
    profile = root_profile({"root_architecture": architecture, "root_depth_class": "deep"})
    previous = {key: 0 for key in ("root_depth_m", "root_spread_m", "root_length_m")}
    for fraction in (0., .05, .1, .25, .5, .75, 1.):
        graph, stats = build_root_graph(profile, fraction, 303)
        assert stats["root_depth_m"] == pytest.approx(2*fraction)
        for key in previous:
            assert stats[key] >= previous[key]
        previous = {key: stats[key] for key in previous}
        assert (graph, stats) == build_root_graph(profile, fraction, 303)
        assert len(graph) < 400
        for i, node in enumerate(graph):
            assert -1 <= node["parent"] < i
            assert all(math.isfinite(v) for v in node["position"])
            assert -2*fraction <= node["position"][2] <= 0
    assert build_root_graph(profile, .1, 303)[1]["root_length_m"] < previous["root_length_m"]*.1


def test_new_fibrous_axis_elongates_from_its_crown_instead_of_popping_in_long():
    profile = root_profile({"root_architecture": "fibrous", "root_depth_class": "deep"})
    before, _ = build_root_graph(profile, .5, 303)
    after, _ = build_root_graph(profile, .50001, 303)
    # New root begins at the ninth independent primary axis's own socket.
    primaries = [n for n in after if n["order"] == 0]
    assert len(primaries) == len([n for n in before if n["order"] == 0])+5
    assert max(math.dist(n["position"], (0, 0, 0)) for n in primaries[-5:]) < .001


def test_distributed_roots_share_the_gradual_depth_clock():
    profile = root_profile({"root_architecture": "adventitious", "root_depth_class": "deep"})
    contacts = [{"position": (0, 0, 0), "parent_index": 1}]
    previous = 0
    for age in (0., .05, .1, .25, .5, .75, 1.):
        _, stats = build_distributed_adventitious_roots(profile, age, 303, contacts)
        assert stats["root_depth_m"] == pytest.approx(2*age)
        assert stats["root_length_m"] >= previous
        previous = stats["root_length_m"]


@pytest.mark.parametrize("sid", ["spec_cichorium_intybus", "spec_buddleja_davidii",
                                "spec_rosa_woodsii", "spec_eupatorium_macrocephalum",
                                "spec_laetiporus_sulphureus", "spec_abronia_angustifolia"])
def test_live_mature_preview_is_reproducible_healthy_and_does_not_author(sid):
    world = WorldModel(); original = dict(world.loader.get(sid))
    sim = SpeciesSimulation(world_model=world, species_id=sid, seed=303)
    age = mature_preview_age(sim)
    assert age == mature_preview_age(sim)
    assert age >= sim.mature_age_days
    sim.set_age(age)
    assert sim.life_state()["phase"] not in {"juvenile", "dormant", "dead", "senescent"}
    assert sim.life_state().get("leaf_factor", 1.) >= .99
    if sim.blueprint.growth.get("fungal_grammar_version"):
        assert sim.render_snapshot.stats["fungal_bodies"]
    assert world.loader.get(sid) == original


def test_chicory_shoots_unchanged_roots_persist_and_canonical_metrics_match_lods():
    sim = SpeciesSimulation(world_model=WorldModel(), species_id="spec_cichorium_intybus", seed=303)
    for fraction in (.05, .5, 1., 2.):
        snapshots = [sim.generate_snapshot(sim.mature_age_days*fraction, lod) for lod in (0, 1, 2)]
        for key in ("root_depth_m", "root_spread_m", "root_length_m", "root_segment_count"):
            assert len({s.stats[key] for s in snapshots}) == 1
        for snapshot in snapshots:
            assert PlantGrowthSnapshot.from_dict(snapshot.to_dict()).to_dict() == snapshot.to_dict()
    assert snapshots[-1].stats["root_depth_m"] == 2.
    assert PlantBlueprint.from_dict(sim.blueprint.to_dict()).fingerprint() == sim.blueprint.fingerprint()


def test_annual_mature_preview_does_not_choose_dead_postflowering_age():
    sim = SpeciesSimulation(species_entity={"id": "annual_fixture", "plant_growth_form": "forb",
        "plant_lifespan": "ephemeral", "maturity_rate": "rapid"}, seed=303)
    age = mature_preview_age(sim)
    assert age >= sim.mature_age_days
    assert sim.life_state(age)["phase"] not in {"dead", "senescent", "juvenile"}
