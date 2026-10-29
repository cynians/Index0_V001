"""Saved Black Locust, deciduous tree cohorts and dense hanging racemes."""
import gzip
import json
import math
import os
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import pygame
import pytest

from simulations.species.inflorescences import inflorescence_profile
from simulations.species.racemes import raceme_surface, raceme_layout
from simulations.species.plant_assets import PlantBlueprint, PlantGrowthSnapshot
from simulations.species.species_simulation import SpeciesSimulation
from simulations.species.species_renderer import SpeciesRenderer, DiagnosticCamera
from tools.author_plant_species import AuthoringError, validate_updates
from tools.render_species_views import stage_ages
from world.world_model import WorldModel


@pytest.fixture(scope="module")
def world():
    return WorldModel()


@pytest.fixture(scope="module")
def entity(world):
    sid = "spec_robinia_pseudoacacia"
    assert world.loader.plant_catalogue.is_leaf_species(sid)
    row = world.resolved_species_entity(sid)
    assert row["parents"] == ["cladis_robinieae"]
    return row


def sim(entity, age=136.875, lod=2):
    result = SpeciesSimulation(species_entity=entity, seed=303)
    result.set_lod(lod)
    result.set_age(age)
    return result


def no_leaf_schedule(entity):
    result = deepcopy(entity)
    for key in ("leaf_out_start", "leaf_out_full", "leaf_fall_start", "leaf_fall_end"):
        result["plant_reproductive_profile"].pop(key)
    return result


def test_live_transport_portability_and_real_time(entity):
    a = sim(entity)
    g = a.blueprint.growth
    assert g["tree_leaf_season_version"] == 1
    assert g["leaf_structure"] == "pinnately_compound" and g["leaf_arrangement"] == "alternate"
    assert g["inflorescence_profile"]["display_floret_count"] == 18
    assert g["inflorescence_profile"]["flower_orientation"] == "gravity_upright"
    assert g["root_profile"]["depth_source"] == "depth_class_default"
    assert entity["longevity"]["typical_years"] == 90 and "maturity_age" not in entity
    assert PlantBlueprint.from_dict(a.blueprint.to_dict()).fingerprint() == a.blueprint.fingerprint()
    assert PlantGrowthSnapshot.from_dict(a.render_snapshot.to_dict()).to_dict() == a.render_snapshot.to_dict()
    assert a.render_snapshot.to_dict() == sim(entity).render_snapshot.to_dict()


def test_leaf_schedule_changes_foliage_but_keeps_wood_and_retained_pods(entity):
    control = no_leaf_schedule(entity)
    winter, leafy = sim(entity, 380), sim(control, 380)
    assert winter.life_state()["phase"] == "dormant"
    assert winter.render_snapshot.stats["estimated_leaf_count"] == 0
    assert winter.render_snapshot.stats["leaf_area_m2"] == 0
    assert not any(p[0] == "leaf" for p in winter.render_snapshot.placements)
    assert leafy.render_snapshot.stats["estimated_leaf_count"] > 1000
    assert winter.render_snapshot.placements == leafy.render_snapshot.placements
    assert winter.render_snapshot.placement_paths == leafy.render_snapshot.placement_paths
    assert winter.render_snapshot.stats["structural_axis_length_m"] == leafy.render_snapshot.stats["structural_axis_length_m"]
    assert any(p[0] == "fruit" for p in winter.render_snapshot.placements)
    assert winter.get_ecological_outcome()["leaf_area_proxy"] == 0
    assert leafy.get_ecological_outcome()["leaf_area_proxy"] > 0


def test_partial_seasons_are_bounded_and_canonical_across_lods(entity):
    counts = []
    for age in (380, 90, 292, 136.875):
        cases = [sim(entity, age, lod) for lod in (0, 1, 2)]
        quantities = [(s.render_snapshot.stats["estimated_leaf_count"],
                       s.render_snapshot.stats["leaf_area_m2"],
                       s.render_snapshot.stats["root_length_m"],
                       s.render_snapshot.stats["structural_axis_length_m"]) for s in cases]
        assert quantities[0] == quantities[1] == quantities[2]
        counts.append(quantities[0][0])
        snapshot = cases[-1].render_snapshot
        assert len(snapshot.placements) < 10000
        for i, placement in enumerate(snapshot.placements):
            assert placement[1] == -1 or 0 <= placement[1] < i
            assert all(math.isfinite(v) for v in placement[2:7])
    assert counts[0] == 0 < counts[1] < counts[2] < counts[3]


def test_detail_shedding_and_unrelated_conifer_reuse(entity):
    fixture = {**deepcopy(entity), "id": "synthetic_seasonal_conifer", "parents": [],
               "leaf_structure": "needle_like", "leaf_arrangement": "fascicled",
               "leaf_fascicle_size": 2, "leaf_length": {"typical_m": .03},
               "plant_axis_continuity": "monopodial", "mature_height": {"max_m": 4}}
    for row in (entity, fixture):
        dormant, full = sim(row, 380), sim(row)
        detail = dormant.generate_snapshot(380, 2, detail=True)
        assert detail.stats["estimated_leaf_count"] == 0 and detail.stats["leaf_area_m2"] == 0
        assert not any(p[0] == "leaf" for p in detail.placements)
        assert full.render_snapshot.stats["leaf_area_m2"] > 0
        assert dormant.render_snapshot.stats["root_length_m"] == full.render_snapshot.stats["root_length_m"]


def test_unseasoned_and_evergreen_trees_keep_full_cohorts(entity):
    control = no_leaf_schedule(entity)
    evergreen = {**entity, "leaf_phenology": "evergreen"}
    for row in (control, evergreen):
        a = sim(row, 380)
        assert "tree_leaf_season_version" not in a.blueprint.growth
        assert a.render_snapshot.stats["estimated_leaf_count"] == sim(row).render_snapshot.stats["estimated_leaf_count"]
    assert sim(control).blueprint.fingerprint() != sim(entity).blueprint.fingerprint()


@pytest.mark.parametrize("count", [3, 12, 18, 25, 70])
def test_expanded_raceme_is_deterministic_and_bounded(entity, count):
    raw = {**entity["plant_inflorescence_profile"], "display_floret_count": count}
    profile = inflorescence_profile(raw)
    assert profile and len(list(raceme_layout(profile))) == count
    pygame.init(); pygame.display.set_mode((1, 1))
    for ppm in (50, 500, 1e9):
        a, anchor = raceme_surface(profile, ppm)
        b, _ = raceme_surface(profile, ppm)
        assert max(a.get_size()) <= 516
        assert 0 <= anchor[0] < a.get_width() and 0 <= anchor[1] < a.get_height()
        assert pygame.image.tobytes(a, "RGBA") == pygame.image.tobytes(b, "RGBA")


@pytest.mark.parametrize("key,value", [("display_floret_count", 71), ("display_floret_count", True),
                                       ("flower_orientation", "sideways"),
                                       ("flower_orientation", []), ("flower_orientation", {})])
def test_invalid_dense_or_orientation_recipe_rejected(entity, key, value):
    bad = {**entity["plant_inflorescence_profile"], key: value}
    assert inflorescence_profile(bad) is None
    with pytest.raises(AuthoringError):
        validate_updates({"plant_inflorescence_profile": bad})


def test_corolla_stays_upright_on_downward_axis_and_cache_tracks_pose(entity):
    pygame.init(); pygame.display.set_mode((1, 1))
    glyph = pygame.Surface((12, 20), pygame.SRCALPHA)
    glyph.fill((255, 0, 0), (0, 0, 12, 10)); glyph.fill((0, 0, 255), (0, 10, 12, 10))
    profile = inflorescence_profile(entity["plant_inflorescence_profile"])
    def color_heights(surface):
        positions = {"red": [], "blue": []}
        for x in range(surface.get_width()):
            for y in range(surface.get_height()):
                c = surface.get_at((x, y))
                if c.a and c.r > 200 and c.b < 30: positions["red"].append(y)
                if c.a and c.b > 200 and c.r < 30: positions["blue"].append(y)
        return [sum(positions[k])/len(positions[k]) for k in ("red", "blue")]
    hanging = pygame.transform.rotate(raceme_surface(profile, 2000, glyph, rotation=180)[0], 180)
    red, blue = color_heights(hanging)
    assert red < blue
    relative = {**profile}; relative.pop("flower_orientation")
    red, blue = color_heights(pygame.transform.rotate(raceme_surface(relative, 2000, glyph)[0], 180))
    assert red > blue
    renderer = SpeciesRenderer(SimpleNamespace(camera=None))
    camera = DiagnosticCamera(400, 400, (-.12, .12, -.25, .25))
    body = sim(entity)
    for rotation in (0, 180):
        screen = pygame.Surface((400, 400), pygame.SRCALPHA)
        assert renderer._draw_module_asset(screen, body, camera, "flower", (200, 200), rotation, 1)
    assert len(renderer._inflorescence_sprite_cache) == 2


def test_display_count_and_pose_do_not_multiply_ecological_organs(entity):
    alternate = deepcopy(entity)
    alternate["plant_inflorescence_profile"].update(display_floret_count=25, flower_orientation="axis_relative")
    a, b = sim(entity), sim(alternate)
    assert a.render_snapshot.placements == b.render_snapshot.placements
    assert a.render_snapshot.leaf_clusters == b.render_snapshot.leaf_clusters
    assert a.get_ecological_outcome() == b.get_ecological_outcome()
    assert a.blueprint.fingerprint() != b.blueprint.fingerprint()


def test_authored_fixation_uses_existing_nutrient_path(entity):
    environment = {"available_nitrogen_g_m2": 0., "available_phosphorus_g_m2": .5}
    fixer = sim(entity).get_ecological_outcome(environment)
    nonfixer = sim({**entity, "nitrogen_fixation": "none"}).get_ecological_outcome(environment)
    assert fixer["nitrogen_response"] > nonfixer["nitrogen_response"] == 0
    assert fixer["phosphorus_response"] == nonfixer["phosphorus_response"]


def test_real_flower_and_pod_stages_and_saved_editable_assets(entity, world):
    stages = stage_ages(sim(entity))
    assert sim(entity, stages[2][1]).life_state()["reproductive_factor"] > 0
    assert sim(entity, stages[3][1]).life_state()["fruiting_factor"] > 0
    from tools.author_plant_assets import PixelEditorHost, load_manifest, render_module
    from ui.pixel_art_editor_ui import PixelArtEditorUI
    pygame.init(); pygame.display.set_mode((1, 1))
    manifest = load_manifest(Path("assets/plant_asset_specs/spec_robinia_pseudoacacia.json"))
    for module in manifest["modules"]:
        illustration = world.get_entity(module["illustration_id"])
        assert illustration["parents"] == [entity["id"]]
        saved = pygame.image.load(illustration["media_path"])
        assert saved.get_size() == (75, 75)
        assert pygame.image.tobytes(saved, "RGBA") == pygame.image.tobytes(render_module(module), "RGBA")
        with gzip.open(illustration["pixel_document_path"], "rt") as stream:
            assert json.load(stream)["version"] == 2
        editor = PixelArtEditorUI(PixelEditorHost(world.loader))
        assert editor.open(module["illustration_id"]) and editor.state["stage"] == "canvas"
