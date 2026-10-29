"""Behavioural controls for the optional creeping woody architecture."""
import math
from copy import deepcopy

import pytest

from simulations.species.creeping_woody import creeping_woody_profile
from simulations.species.plant_assets import PlantBlueprint, PlantGrowthSnapshot
from simulations.species.species_simulation import SpeciesSimulation


RECIPE = dict(form="creeping_woody", runner_length_m=.42, stem_radius_m=.0012,
              shoot_spacing_m=.045, shoot_lift_fraction=.82, shoot_branch_count=2,
              runner_branch_count=2, runner_branch_length_fraction=.65,
              leaf_spacing_m=.002, leaf_width_m=.001, runner_foliage_fraction=.3)
ENTITY = dict(id="spec_unrelated_woody_mat", plant_growth_form="subshrub",
              plant_growth_behaviour="creeping_prostrate", plant_woodiness="woody",
              plant_lifespan="perennial", clonal_spread="moderate",
              mature_height=dict(min_m=.1, typical_m=.15, max_m=.4),
              leaf_length=dict(typical_m=.005), leaf_structure="needle_like",
              leaf_clustering="dense_cluster", plant_shoot_profile=RECIPE)


def simulation(recipe=None, lod=2, **fields):
    entity = deepcopy(ENTITY)
    entity.update(fields)
    if recipe is not None:
        entity["plant_shoot_profile"] = recipe
    sim = SpeciesSimulation(species_entity=entity, seed=91)
    sim.set_lod(lod)
    sim.set_age(sim.blueprint.growth["life_history"]["maturity_days"])
    return sim


@pytest.mark.parametrize("value", [None, {}, {**RECIPE, "shoot_spacing_m": 0},
    {**RECIPE, "leaf_width_m": float("nan")}, {**RECIPE, "stem_radius_m": True},
    {**RECIPE, "shoot_branch_count": 2.5}, {**RECIPE, "shoot_branch_count": 5}])
def test_invalid_recipe_is_neutral(value):
    assert creeping_woody_profile(value) is None
    assert "creeping_woody_profile" not in PlantBlueprint.from_species_entity({**ENTITY, "plant_shoot_profile": value}).growth


def test_recipe_requires_woody_creeping_shrub():
    for fields in (dict(plant_woodiness="herbaceous", plant_growth_form="forb"),
                   dict(plant_growth_behaviour="branched_woody")):
        assert "creeping_woody_profile" not in PlantBlueprint.from_species_entity({**ENTITY, **fields}).growth


def test_branching_lift_and_leaf_spacing_have_independent_responses():
    control = simulation()
    flat = simulation({**RECIPE, "shoot_lift_fraction": 0})
    sparse = simulation({**RECIPE, "leaf_spacing_m": .01})
    unbranched = simulation({**RECIPE, "shoot_branch_count": 0, "runner_branch_count": 0})
    assert control.render_snapshot.bounds_m[5] > flat.render_snapshot.bounds_m[5] + .05
    assert control.render_snapshot.stats["estimated_leaf_count"] > sparse.render_snapshot.stats["estimated_leaf_count"]
    assert control.render_snapshot.stats["structural_axis_length_m"] == sparse.render_snapshot.stats["structural_axis_length_m"]
    assert control.render_snapshot.stats["creeping_secondary_axis_count"] > 0
    assert unbranched.render_snapshot.stats["creeping_secondary_axis_count"] == 0
    assert len({s.blueprint.fingerprint() for s in (control, flat, sparse, unbranched)}) == 4


def test_canonical_structure_ecology_and_roundtrip_are_lod_stable():
    sims = [simulation(lod=lod) for lod in range(3)]
    for key in ("structural_axis_length_m", "estimated_leaf_count", "leaf_area_m2",
                "creeping_axis_count", "creeping_ascending_axis_count", "creeping_rooting_contact_count",
                "root_length_m", "root_depth_m"):
        assert len({s.render_snapshot.stats[key] for s in sims}) == 1, key
    assert sims[0].render_snapshot.stats["leaf_count"] == 0
    assert sims[2].render_snapshot.stats["leaf_count"] > sims[1].render_snapshot.stats["leaf_count"]
    assert sims[0].get_ecological_outcome() == sims[1].get_ecological_outcome() == sims[2].get_ecological_outcome()
    s = sims[2]
    assert s.render_snapshot.to_dict() == simulation().render_snapshot.to_dict()
    assert PlantBlueprint.from_dict(s.blueprint.to_dict()).to_dict() == s.blueprint.to_dict()
    assert PlantGrowthSnapshot.from_dict(s.render_snapshot.to_dict()).to_dict() == s.render_snapshot.to_dict()
    for index, placement in enumerate(s.render_snapshot.placements):
        assert all(math.isfinite(float(v)) for v in placement[2:7])
        assert int(placement[1]) == -1 or 0 <= int(placement[1]) < index
    assert s.render_snapshot.bounds_m[5] < .18
    assert len(s.render_snapshot.placements) < 12000
    for socket in s.render_snapshot.attachment_points:
        leaf = s.render_snapshot.placements[socket["leaf_placement_index"]]
        assert int(leaf[1]) == socket["stem_placement_index"]
        assert tuple(socket["position_m"]) == tuple(leaf[2:5])
        path = s.render_snapshot.placement_paths[str(int(leaf[1]))]
        def distance_to_segment(a, b):
            delta = [y-x for x, y in zip(a, b)]
            length2 = sum(v*v for v in delta)
            t = max(0., min(1., sum((x-y)*d for x, y, d in zip(leaf[2:5], a, delta))/length2)) if length2 else 0.
            return math.dist(leaf[2:5], [x+t*d for x, d in zip(a, delta)])
        assert min(distance_to_segment(a, b) for a, b in zip(path, path[1:])) < .00015


def test_unknown_spread_does_not_invent_contact_roots():
    for spread in ("none", "other_unknown", None):
        snapshot = simulation(clonal_spread=spread).render_snapshot
        assert snapshot.stats["creeping_axis_count"] == 1
        assert snapshot.stats["creeping_rooting_contact_count"] == 0


def test_authoring_rejects_unbounded_recipe_before_persistence():
    from tools.author_plant_species import AuthoringError, validate_updates
    validate_updates({"plant_shoot_profile": RECIPE})
    with pytest.raises(AuthoringError):
        validate_updates({"plant_shoot_profile": {**RECIPE, "runner_branch_count": 99}})


def test_biosphere_body_uses_the_same_leaf_area_and_demand_response():
    from simulations.biosphere.representatives import RepresentativeBody
    dense = simulation()
    sparse = simulation({**RECIPE, "leaf_spacing_m": .01})
    body = RepresentativeBody(species_entity=deepcopy(ENTITY), seed=91)
    body.set_age(dense.age_days)
    body.set_lod(2)
    assert body.get_ecological_outcome() == dense.get_ecological_outcome()
    assert dense.get_ecological_outcome()["leaf_area_proxy"] > sparse.get_ecological_outcome()["leaf_area_proxy"]
    assert dense.get_ecological_outcome()["resource_demand"] > sparse.get_ecological_outcome()["resource_demand"]
