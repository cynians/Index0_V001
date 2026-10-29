"""Hanging display attachments, sparse panicles and live Kigelia composition."""
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

from simulations.species.inflorescences import inflorescence_profile, floret_layout, panicle_surface
from simulations.species.pendant_reproduction import pendant_display_profile, pendant_geometry
from simulations.species.plant_assets import PlantBlueprint, PlantGrowthSnapshot
from simulations.species.plant_reproduction import reproductive_profile
from simulations.species.species_renderer import SpeciesRenderer, DiagnosticCamera
from simulations.species.species_simulation import SpeciesSimulation
from tools.author_plant_species import AuthoringError, validate_updates
from tools.render_species_views import stage_ages
from world.world_model import WorldModel


@pytest.fixture(scope="module")
def world():
    return WorldModel()


@pytest.fixture(scope="module")
def entity(world):
    sid = "spec_kigelia_africana"
    assert world.loader.plant_catalogue.is_leaf_species(sid)
    e = world.resolved_species_entity(sid)
    assert e["parents"] == ["cladis_crescentiina"]
    return e


def sim(entity, age=259.15, lod=2):
    s = SpeciesSimulation(species_entity=entity, seed=303)
    s.set_lod(lod); s.set_age(age)
    return s


def without_pendant(entity):
    result = deepcopy(entity)
    result["plant_reproductive_profile"].pop("pendant_display")
    return result


@pytest.mark.parametrize("key,value", [
    ("flower_drop_m", -1), ("flower_drop_m", 3), ("flower_drop_m", True),
    ("fruit_drop_m", float("nan")), ("fruit_drop_m", float("inf")),
    ("stalk_radius_m", 0), ("stalk_radius_m", .03),
    ("stalk_color", [True, 2, 3]), ("stalk_color", [256, 1, 2]),
])
def test_invalid_stalk_recipe_is_rejected_before_persistence(entity, key, value):
    raw = deepcopy(entity["plant_reproductive_profile"])
    raw["pendant_display"][key] = value
    assert pendant_display_profile(raw["pendant_display"]) is None
    assert "pendant_display" not in reproductive_profile(raw)
    with pytest.raises(AuthoringError):
        validate_updates({"plant_reproductive_profile": raw})


@pytest.mark.parametrize("value", [None, {}, "other_unknown", 0])
def test_missing_or_unknown_display_is_neutral(entity, value):
    control = without_pendant(entity)
    treatment = deepcopy(control)
    treatment["plant_reproductive_profile"]["pendant_display"] = value
    assert pendant_display_profile(value) is None
    a, b = sim(control), sim(treatment)
    assert a.blueprint.fingerprint() == b.blueprint.fingerprint()
    assert a.render_snapshot.to_dict() == b.render_snapshot.to_dict()


def test_zero_stalks_are_neutral_and_real_stalks_transport(entity):
    control = without_pendant(entity)
    zero = deepcopy(entity)
    zero["plant_reproductive_profile"]["pendant_display"].update(flower_drop_m=0, fruit_drop_m=0)
    assert sim(zero).blueprint.fingerprint() == sim(control).blueprint.fingerprint()
    a = sim(entity)
    assert a.blueprint.fingerprint() != sim(control).blueprint.fingerprint()
    assert a.blueprint.growth["reproductive_profile"]["version"] == 3
    assert a.blueprint.growth["reproductive_profile"]["pendant_display"]["fruit_drop_m"] == .45
    assert a.blueprint.growth["inflorescence_profile"]["display_floret_count"] == 6
    assert a.blueprint.module("flower").visual["depicted_size_m"] == .1
    assert a.blueprint.module("fruit").visual["depicted_size_m"] == .6
    assert PlantBlueprint.from_dict(a.blueprint.to_dict()).fingerprint() == a.blueprint.fingerprint()
    assert PlantGrowthSnapshot.from_dict(a.render_snapshot.to_dict()).to_dict() == a.render_snapshot.to_dict()


def test_drop_direction_extent_and_ecology_are_separate(entity):
    for age in (259.15, 357.7):
        a, b = sim(entity, age), sim(without_pendant(entity), age)
        assert a.render_snapshot.placements == b.render_snapshot.placements
        assert a.render_snapshot.leaf_clusters == b.render_snapshot.leaf_clusters
        assert a.get_ecological_outcome() == b.get_ecological_outcome()
        for p in a.render_snapshot.placements:
            if p[0] not in {"flower", "fruit"}:
                continue
            module = a.blueprint.module(p[0])
            anchor, tip = pendant_geometry(a.blueprint.growth, p, module)
            assert anchor[:2] == tip[:2] == tuple(p[2:4])
            assert tip[2] < anchor[2] < p[4]
            expected = .8 if p[0] == "flower" else .6
            assert anchor[2] - tip[2] == pytest.approx(expected * max(.55, p[6]))
            assert a.render_snapshot.bounds_m[4] <= tip[2]
            assert pendant_geometry(b.blueprint.growth, p, module) is None


def test_sparse_panicle_counts_fit_and_reuse_single_flower(entity):
    profile = inflorescence_profile(entity["plant_inflorescence_profile"])
    for count in (3, 6, 12, 512):
        recipe = inflorescence_profile({**profile, "display_floret_count": count})
        assert recipe is not None
        assert len(list(floret_layout(recipe))) == count
        assert all(math.isfinite(v) for point in floret_layout(recipe) for v in point)
    for count in (0, 2, 513, True):
        assert inflorescence_profile({**profile, "display_floret_count": count}) is None
    pygame.init(); pygame.display.set_mode((1, 1))
    renderer = SpeciesRenderer(SimpleNamespace(camera=None))
    glyph = renderer._module_asset(sim(entity), "flower")
    a, anchor = panicle_surface(profile, 500, .5, glyph)
    assert max(a.get_size()) <= 1028
    assert 0 <= anchor[0] < a.get_width() and 0 <= anchor[1] < a.get_height()
    assert pygame.image.tobytes(a, "RGBA") == pygame.image.tobytes(panicle_surface(profile, 500, .5, glyph)[0], "RGBA")
    blue = pygame.Surface((75, 75), pygame.SRCALPHA); blue.fill((20, 60, 240))
    assert pygame.image.tobytes(a, "RGBA") != pygame.image.tobytes(panicle_surface(profile, 500, .5, blue)[0], "RGBA")


def test_live_seasons_and_viewer_show_actual_bloom_then_retained_fruit(entity):
    young, flower, fruit, retained, spent = [sim(entity, age) for age in (30, 259.15, 357.7, 390, 550)]
    assert not any(p[0] in {"flower", "fruit"} for p in young.render_snapshot.placements)
    assert any(p[0] == "flower" for p in flower.render_snapshot.placements)
    assert not any(p[0] == "fruit" for p in flower.render_snapshot.placements)
    assert not any(p[0] == "flower" for p in fruit.render_snapshot.placements)
    assert any(p[0] == "fruit" for p in fruit.render_snapshot.placements)
    assert any(p[0] == "fruit" for p in retained.render_snapshot.placements)
    assert not any(p[0] == "fruit" for p in spent.render_snapshot.placements)
    stages = stage_ages(flower)
    profile = flower.blueprint.growth['reproductive_profile']
    # The viewer fits its flower panel before fruit replacement begins.
    assert stages[2][1] == pytest.approx(profile['cycle_days'] * (
        profile['flowering_start'] + min(profile['flowering_end'], profile['fruit_start'])) / 2)
    assert stages[-1] == ("Fruiting", pytest.approx(357.7))
    assert flower.life_state(stages[2][1])["reproductive_factor"] > 0
    assert flower.life_state(stages[-1][1])["fruiting_factor"] > 0
    assert flower.life_state(259.15)["seasonal_stage"] == flower.life_state(259.15+365)["seasonal_stage"]


def test_determinism_finite_sockets_lod_and_unrelated_reuse(entity):
    a = sim(entity)
    assert a.render_snapshot.to_dict() == sim(entity).render_snapshot.to_dict()
    assert len(a.render_snapshot.placements) < 10000
    assert a.render_snapshot.stats["root_model_status"] == "unresolved"
    assert a.render_snapshot.bounds_m[1] - a.render_snapshot.bounds_m[0] > 20
    for i, p in enumerate(a.render_snapshot.placements):
        assert p[1] == -1 or 0 <= p[1] < i
        assert all(math.isfinite(v) for v in p[2:7])
        if p[0] in {"flower", "fruit"}:
            assert a.render_snapshot.placements[p[1]][0] in {"stem_section", "branch_section"}
    levels = [sim(entity, lod=lod) for lod in (0, 1, 2)]
    metrics = [(s.render_snapshot.stats["estimated_leaf_count"], s.render_snapshot.stats["leaf_area_m2"],
                s.render_snapshot.stats["structural_axis_length_m"], s.render_snapshot.stats["root_length_m"])
               for s in levels]
    assert metrics[0] == metrics[1] == metrics[2]
    other = {**entity, "id": "synthetic_unrelated_pendant_tree", "parents": [],
             "mature_height": {"max_m": 8}, "leaf_length": {"typical_m": .2}}
    s = sim(other)
    assert s.blueprint.growth["reproductive_profile"]["pendant_display"] == a.blueprint.growth["reproductive_profile"]["pendant_display"]
    assert s.render_snapshot.to_dict() == sim(other).render_snapshot.to_dict()
    assert s.render_snapshot.bounds_m[5] < a.render_snapshot.bounds_m[5]


def test_rendered_stalk_connects_to_lowered_body_at_physical_scale(entity):
    pygame.init(); pygame.display.set_mode((1, 1))
    s = sim(entity, 357.7)
    renderer = SpeciesRenderer(SimpleNamespace(camera=None))
    p = ["fruit", 0, 0, 0, 1.6, 0, 1, 6]
    snap = PlantGrowthSnapshot(s.species_id, s.blueprint.fingerprint(), 303, 357.7, 2,
                               {m.id: m.to_dict() for m in s.blueprint.modules},
                               [["branch_section", -1, 0, 0, 1.6, 0, .01, 2], p],
                               [-.1, .1, -.1, .1, .5, 1.6])
    camera = DiagnosticCamera(400, 500, (-.8, .8, .3, 1.7))
    output = pygame.Surface((400, 500)); output.fill((13, 20, 17))
    renderer._draw_individual(output, s, camera=camera, snapshot=snap, clear=False, cache=False,
                              visible_indices={1}, draw_ground_line=False, draw_environment=False)
    attachment = camera.world_to_screen((0, 1.6))
    anchor = camera.world_to_screen((0, 1.15))
    tip = camera.world_to_screen((0, .55))
    assert attachment[1] < anchor[1] < tip[1]
    assert output.get_at((anchor[0], (attachment[1]+anchor[1])//2))[:3] == tuple(
        s.blueprint.growth["reproductive_profile"]["pendant_display"]["stalk_color"])
    assert output.get_at((tip[0], (anchor[1]+tip[1])//2))[:3] != (13, 20, 17)


def test_all_five_saved_modules_reopen_and_match_manifest(world):
    from tools.author_plant_assets import PixelEditorHost, load_manifest, render_module
    from ui.pixel_art_editor_ui import PixelArtEditorUI
    pygame.init(); pygame.display.set_mode((1, 1))
    manifest = load_manifest(Path("assets/plant_asset_specs/spec_kigelia_africana.json"))
    for module in manifest["modules"]:
        illustration = world.get_entity(module["illustration_id"])
        assert illustration["parents"] == ["spec_kigelia_africana"]
        editor = PixelArtEditorUI(PixelEditorHost(world.loader))
        assert editor.open(module["illustration_id"]) and editor.state["stage"] == "canvas"
        saved = pygame.image.load(illustration["media_path"])
        assert saved.get_size() == (75, 75)
        assert pygame.image.tobytes(saved, "RGBA") == pygame.image.tobytes(render_module(module), "RGBA")
        with gzip.open(illustration["pixel_document_path"], "rt") as stream:
            assert json.load(stream)["version"] == 2
