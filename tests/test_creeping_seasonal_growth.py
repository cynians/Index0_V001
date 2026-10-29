"""Portable seasonal and densely foliated creeping-plant contracts."""
import json
import math
from copy import deepcopy
from pathlib import Path

import pytest

from simulations.species.plant_assets import PlantBlueprint, PlantGrowthSnapshot
from simulations.species.plant_reproduction import reproductive_profile, seasonal_reproductive_state
from simulations.species.species_simulation import SpeciesSimulation
from world.world_model import WorldModel


@pytest.fixture(scope="module")
def entity():
    raw = WorldModel().resolved_species_entity("spec_empetrum_nigrum")
    manifest = json.loads(Path("assets/plant_asset_specs/spec_empetrum_nigrum.json").read_text())
    return {**raw, **manifest["species_field_updates"]}


def simulation(entity, age=260, lod=2):
    s = SpeciesSimulation(species_entity=entity, seed=303)
    s.set_lod(lod)
    s.set_age(age)
    return s


def test_seasons_repeat_and_evergreen_adult_does_not_die_each_year(entity):
    s = simulation(entity)
    for age in (130, 205, 260, 330, 390, 515):
        a, b = s.life_state(age), s.life_state(age+365)
        for key in ("reproductive_factor", "fruiting_factor", "fruit_ripeness", "seasonal_stage"):
            assert a[key] == b[key]
        assert a["senescence_factor"] == b["senescence_factor"] == 0
        assert a["active_factor"] == 1
    assert s.life_state(130)["seasonal_stage"] == "flowering"
    assert s.life_state(205)["seasonal_stage"] == "developing_fruit"
    assert s.life_state(260)["seasonal_stage"] == "ripe_fruit"
    assert s.life_state(390)["seasonal_stage"] == "retained_fruit"


def test_no_fruit_before_maturity_or_without_a_reproductive_recipe(entity):
    young = simulation(entity, 5)
    assert not any(p[0] in {"flower", "fruit"} for p in young.render_snapshot.placements)
    assert young.render_snapshot.bounds_m[5] < .03
    for value in (None, {}, {"cycle_days": math.nan}, {"cycle_days": True}):
        assert reproductive_profile(value) is None
    incomplete = {**entity, "plant_reproductive_profile": {}}
    assert "reproductive_profile" not in simulation(incomplete).blueprint.growth
    vegetative = simulation({**entity,"reproductive_mode":"vegetative"})
    assert not any(p[0] in {"flower", "fruit"} for p in vegetative.render_snapshot.placements)


def test_reproductive_organs_have_real_hosts_sizes_and_stage_progression(entity):
    flower = simulation(entity,130)
    fruit = simulation(entity,260)
    assert flower.render_snapshot.stats["creeping_flower_count"] > 0
    assert flower.render_snapshot.stats["creeping_fruit_count"] == 0
    assert fruit.render_snapshot.stats["creeping_fruit_count"] > 0
    assert fruit.render_snapshot.stats["creeping_flower_count"] == 0
    assert fruit.blueprint.module("fruit").visual["depicted_size_m"] == 0.005
    for p in fruit.render_snapshot.placements:
        if p[0] == "fruit":
            host = fruit.render_snapshot.placements[int(p[1])]
            assert host[0] == "branch_section"
            assert math.dist(host[2:5],p[2:5]) < 0.005


def test_authored_density_changes_packing_without_inflating_leaves(entity):
    # The original generic path retains its density controls. The optional
    # woody recipe instead declares metric leaf/shoot spacing explicitly.
    entity = {**entity, "plant_shoot_profile": None,
              "plant_leaf_cluster_density": {"min": .65, "typical": .8, "max": .9},
              "plant_fine_twig_density": {"min": .45, "typical": .65, "max": .8}}
    sparse = deepcopy(entity)
    for key in ("plant_leaf_cluster_density", "plant_fine_twig_density"):
        sparse[key] = {"min":0,"typical":0,"max":0}
    dense_s, sparse_s = simulation(entity), simulation(sparse)
    assert dense_s.render_snapshot.stats["leaf_count"] > sparse_s.render_snapshot.stats["leaf_count"]
    assert dense_s.render_snapshot.stats["creeping_ascending_axis_count"] > sparse_s.render_snapshot.stats["creeping_ascending_axis_count"]
    assert dense_s.blueprint.module("leaf").length_m == sparse_s.blueprint.module("leaf").length_m == 0.005
    assert dense_s.blueprint.fingerprint() != sparse_s.blueprint.fingerprint()


def test_deterministic_portable_finite_and_bounded_with_contact_roots(entity):
    a,b = simulation(entity),simulation(entity)
    snap = a.render_snapshot
    assert snap.to_dict() == b.render_snapshot.to_dict()
    assert PlantGrowthSnapshot.from_dict(snap.to_dict()).to_dict() == snap.to_dict()
    bp = PlantBlueprint.from_dict(a.blueprint.to_dict())
    assert bp.fingerprint() == a.blueprint.fingerprint()
    assert bp.growth["reproductive_profile"]["version"] == 1
    assert snap.stats["root_distribution"] == "crown_and_contact_nodes"
    assert 2 <= snap.stats["root_cluster_count"] <= 17
    assert len(snap.placements) < 20000
    assert snap.stats["creeping_footprint_radius_m"] < 1.2
    for index,p in enumerate(snap.placements):
        assert all(math.isfinite(float(v)) for v in p[2:7])
        assert p[1] == -1 or 0 <= p[1] < index


def test_unrelated_fixture_reuses_same_grammar_and_lod_ecology(entity):
    other = {**entity,"id":"spec_synthetic_creeping_fixture","common_name":"Synthetic creeping shrub"}
    reference = simulation(entity)
    reused = simulation(other)
    keys = ("creeping_axis_count", "creeping_fruit_count", "root_length_m", "estimated_leaf_count", "leaf_area_m2")
    for key in keys:
        assert reused.render_snapshot.stats.get(key) == reference.render_snapshot.stats.get(key)
    for lod in (0,1):
        coarse = simulation(other,lod=lod)
        for key in keys:
            assert coarse.render_snapshot.stats.get(key) == reused.render_snapshot.stats.get(key)


def test_profile_change_invalidates_fingerprint_and_bad_windows_are_neutral(entity):
    changed = deepcopy(entity)
    changed["plant_reproductive_profile"]["fruit_ripe"] = 0.7
    assert simulation(changed).blueprint.fingerprint() != simulation(entity).blueprint.fingerprint()
    for key,value in (("fruit_size_m",0),("fruit_ripe",math.inf),("flowering_end",0.1)):
        changed = deepcopy(entity)
        changed["plant_reproductive_profile"][key] = value
        assert reproductive_profile(changed["plant_reproductive_profile"]) is None


def test_tiny_creeping_asset_does_not_use_generic_four_centimetre_floor(entity):
    import pygame
    from types import SimpleNamespace
    from simulations.species.species_renderer import DiagnosticCamera,SpeciesRenderer
    s = simulation(entity)
    renderer = SpeciesRenderer(SimpleNamespace(camera=None))
    asset = pygame.Surface((15,75),pygame.SRCALPHA)
    asset.fill((80,120,40,255))
    renderer._module_asset = lambda *_args: asset
    screen = pygame.Surface((400,300),pygame.SRCALPHA)
    cam = DiagnosticCamera(400,300,(0,0.5,0,0.1))
    assert renderer._draw_module_asset(screen,s,cam,"leaf",(200,150),0,1)
    assert screen.get_bounding_rect().height <= 6
    detail = DiagnosticCamera(160,130,(0,0.025,0,0.025),minimum_span_m=0.001)
    assert detail.scale > 3000
