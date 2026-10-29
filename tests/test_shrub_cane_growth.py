"""Authored shrub architecture, seasonal organs, and portable LOD contracts."""
import json
import math
from copy import deepcopy
from pathlib import Path

import pytest

from simulations.species.plant_assets import PlantBlueprint, PlantGrowthSnapshot
from simulations.species.plant_reproduction import reproductive_profile
from simulations.species.species_simulation import SpeciesSimulation
from world.world_model import WorldModel


@pytest.fixture(scope="module")
def entity():
    world = WorldModel()
    raw = world.resolved_species_entity("spec_rosa_woodsii")
    assert world.loader.plant_catalogue.is_species("spec_rosa_woodsii")
    assert raw["parents"] == ["cladis_roses_rosa"]
    manifest = json.loads(Path("assets/plant_asset_specs/spec_rosa_woodsii.json").read_text())
    result = {**raw, **manifest["species_field_updates"]}
    # This suite covers the original static cane grammar, independently of
    # later opt-in cohort recipes authored on the live example species.
    result.pop('plant_shoot_profile', None)
    result["plant_module_anchors"] = deepcopy(raw["plant_module_anchors"])
    for module in manifest["modules"]:
        if module["role"] in {"leaf", "flower", "fruit"}:
            result["plant_module_anchors"][module["role"]]["depicted_size_m"] = module["depicted_size_m"]
    return result


def sim(entity, age=150, lod=2):
    simulation = SpeciesSimulation(species_entity=entity, seed=303)
    simulation.set_lod(lod)
    simulation.set_age(age)
    return simulation


def test_trait_transport_and_fingerprint(entity):
    blueprint = sim(entity).blueprint
    assert blueprint.growth["shrub_cane_grammar_version"] == 1
    assert blueprint.growth["shrub_height_m"] == 1.55
    assert blueprint.module("leaf").length_m == .08
    assert blueprint.growth["leaflet_count"] == 7
    assert blueprint.module("flower").length_m == .05
    assert blueprint.module("fruit").length_m == .02
    unknown = {**entity, "plant_lateral_axis_orientation":"other_unknown"}
    assert "shrub_cane_grammar_version" not in sim(unknown).blueprint.growth
    assert blueprint.fingerprint() != sim(unknown).blueprint.fingerprint()


def test_deterministic_finite_bounded_and_portable(entity):
    a,b = sim(entity),sim(entity)
    snapshot = a.render_snapshot
    assert snapshot.to_dict() == b.render_snapshot.to_dict()
    assert PlantGrowthSnapshot.from_dict(snapshot.to_dict()).to_dict() == snapshot.to_dict()
    assert PlantBlueprint.from_dict(a.blueprint.to_dict()).fingerprint() == a.blueprint.fingerprint()
    assert 2 <= snapshot.stats["shrub_cane_count"] <= 10
    assert len(snapshot.placements) < 5000
    assert .9 < snapshot.bounds_m[5] < 2.5
    for i,p in enumerate(snapshot.placements):
        assert p[1] == -1 or 0 <= p[1] < i
        assert all(math.isfinite(v) for v in p[2:7])
    for attachment in snapshot.attachment_points:
        leaf = snapshot.placements[attachment["leaf_placement_index"]]
        assert leaf[1] == attachment["stem_placement_index"]


def test_lod_preserves_axes_leaf_cohorts_and_root_ecology(entity):
    simulations = [sim(entity,lod=lod) for lod in (0,1,2)]
    metrics = [(s.render_snapshot.stats["estimated_leaf_count"],s.render_snapshot.stats["leaf_area_m2"],
                s.render_snapshot.stats["root_length_m"]) for s in simulations]
    assert metrics[0] == metrics[1] == metrics[2]
    axes = [[p[2:5] for p in s.render_snapshot.placements if p[0] in {"stem_section","branch_section"}]
            for s in simulations]
    assert axes[0] == axes[1] == axes[2]
    assert simulations[0].render_snapshot.stats["leaf_count"] == 0
    assert simulations[1].render_snapshot.stats["leaf_count"] < simulations[2].render_snapshot.stats["leaf_count"]


def test_density_controls_add_real_shoots_without_enlarging_leaves(entity):
    sparse = {**entity,"plant_fine_twig_density":{"min":0,"typical":0,"max":0}}
    a,b = sim(entity),sim(sparse)
    assert a.render_snapshot.stats["branch_count"] > b.render_snapshot.stats["branch_count"]
    assert a.render_snapshot.stats["estimated_leaf_count"] > b.render_snapshot.stats["estimated_leaf_count"]
    assert a.blueprint.module("leaf").length_m == b.blueprint.module("leaf").length_m
    assert a.blueprint.fingerprint() != b.blueprint.fingerprint()


def test_deciduous_flower_to_hip_seasons_repeat_without_cane_death(entity):
    flower,green,ripe,winter = [sim(entity,age) for age in (150,215,260,330)]
    assert flower.render_snapshot.stats["shrub_flower_count"] > 0
    assert flower.render_snapshot.stats["shrub_fruit_count"] == 0
    assert green.life_state()["fruit_ripeness"] < ripe.life_state()["fruit_ripeness"] == 1
    assert winter.life_state()["phase"] == "dormant"
    assert winter.render_snapshot.stats["leaf_count"] == 0
    assert winter.render_snapshot.stats["shrub_fruit_count"] > 0
    assert winter.render_snapshot.stats["stem_count"] == flower.render_snapshot.stats["stem_count"]
    for age in (150,215,260,330):
        assert flower.life_state(age) == flower.life_state(age+365)
    for plant in (flower,green,ripe,winter):
        for p in plant.render_snapshot.placements:
            if p[0] in {"flower","fruit"}:
                assert plant.render_snapshot.placements[p[1]][0] in {"stem_section","branch_section"}
    assert sim(entity,105).render_snapshot.stats["shrub_flower_count"] == 0


def test_missing_season_recipe_and_vegetative_mode_are_neutral(entity):
    assert not sim({**entity,"reproductive_mode":"vegetative"}).render_snapshot.stats["shrub_flower_count"]
    assert not sim({**entity,"reproductive_mode":"vegetative"},260).render_snapshot.stats["shrub_fruit_count"]
    incomplete = {**entity,"plant_reproductive_profile":{}}
    assert "reproductive_profile" not in sim(incomplete).blueprint.growth
    assert "leaf_factor" not in sim(incomplete).life_state()
    for value in (math.nan,True,None):
        profile = deepcopy(entity["plant_reproductive_profile"])
        profile["leaf_out_start"] = value
        assert reproductive_profile(profile) is None
    profile = deepcopy(entity["plant_reproductive_profile"])
    profile["leaf_fall_start"] = profile["leaf_out_start"]
    assert reproductive_profile(profile) is None


def test_unrelated_shrub_reuses_grammar_and_orientation_controls(entity):
    fixture = {**entity,"id":"spec_synthetic_unrelated_shrub","common_name":"Synthetic fixture",
               "leaf_structure":"simple","leaf_arrangement":"opposite"}
    assert sim(fixture).render_snapshot.stats["shrub_cane_grammar_version"] == 1
    alternate = sim({**fixture,"leaf_arrangement":"alternate"})
    assert sim(fixture).render_snapshot.stats["estimated_leaf_count"] == 2 * alternate.render_snapshot.stats["estimated_leaf_count"]
    upright = sim({**fixture,"plant_lateral_axis_orientation":"orthotropic"})
    pendent = sim({**fixture,"plant_lateral_axis_orientation":"pendent"})
    z_u = sum(p[4] for p in upright.render_snapshot.placements if p[0] == "branch_section")
    z_p = sum(p[4] for p in pendent.render_snapshot.placements if p[0] == "branch_section")
    assert z_u > z_p


def test_asset_leaf_uses_physical_size_for_authored_shrubs(entity):
    import pygame
    from types import SimpleNamespace
    from simulations.species.species_renderer import SpeciesRenderer,DiagnosticCamera
    pygame.init()
    try:
        renderer = SpeciesRenderer(SimpleNamespace(camera=None))
        sprite = pygame.Surface((10,20),pygame.SRCALPHA)
        sprite.fill((80,120,40,255))
        renderer._module_asset = lambda *_:sprite
        screen = pygame.Surface((100,100),pygame.SRCALPHA)
        renderer._draw_module_asset(screen,sim(entity),DiagnosticCamera(100,100,(0,10,0,10)),
                                    "leaf",(50,50),0,1)
        assert screen.get_bounding_rect().height <= 2
    finally:
        pygame.quit()
