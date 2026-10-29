"""Reusable raceme display, canonical ecology and saved Mock Orange artwork."""
import gzip
import json
import math
import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import pygame
import pytest

from simulations.species.inflorescences import inflorescence_profile
from simulations.species.racemes import raceme_layout, raceme_surface
from simulations.species.plant_assets import PlantBlueprint, PlantGrowthSnapshot
from simulations.species.species_renderer import SpeciesRenderer, DiagnosticCamera
from simulations.species.species_simulation import SpeciesSimulation
from tools.author_plant_species import AuthoringError, validate_updates
from world.world_model import WorldModel


@pytest.fixture(scope="module")
def world():
    return WorldModel()


@pytest.fixture(scope="module")
def entity(world):
    species_id = "spec_philadelphus_coronarius"
    assert world.loader.plant_catalogue.is_leaf_species(species_id)
    entity = world.resolved_species_entity(species_id)
    assert entity["parents"] == ["cladis_mock_oranges_philadelphus"]
    return entity


@pytest.fixture(scope="module")
def profile(entity):
    return inflorescence_profile(entity["plant_inflorescence_profile"])


def sim(entity, age=177.75, lod=2):
    result = SpeciesSimulation(species_entity=entity, seed=303)
    result.set_lod(lod)
    result.set_age(age)
    return result


@pytest.mark.parametrize("key,value", [
    ("display_floret_count", 0), ("display_floret_count", True),
    ("display_floret_count", 71), ("display_floret_count", 5.5),
    ("length_m", 0), ("length_m", float("nan")),
    ("flower_size_m", float("inf")), ("flower_size_m", .1),
    ("pedicel_length_m", True), ("axis_color", [True, 1, 2]),
    ("eye_color", [256, 0, 0]), ("unit", "whole_cluster"),
])
def test_invalid_recipe_rejected_before_authoring(profile, key, value):
    bad = {**profile, key: value}
    assert inflorescence_profile(bad) is None
    with pytest.raises(AuthoringError):
        validate_updates({"plant_inflorescence_profile": bad})


@pytest.mark.parametrize("value", [None, {}, 0, "other_unknown"])
def test_unknown_profile_is_neutral(entity, value):
    control = {**entity}; control.pop("plant_inflorescence_profile")
    assert inflorescence_profile(value) is None
    a, b = sim(control), sim({**control, "plant_inflorescence_profile": value})
    assert a.blueprint.fingerprint() == b.blueprint.fingerprint()
    assert a.render_snapshot.to_dict() == b.render_snapshot.to_dict()


def test_transport_fingerprint_and_portability(entity, profile):
    a = sim(entity)
    assert a.blueprint.growth["inflorescence_profile"] == profile
    assert a.blueprint.growth["shrub_cane_grammar_version"] == 1
    assert a.blueprint.growth["shrub_height_m"] == 3
    assert a.blueprint.module("flower").visual["depicted_size_m"] == .035
    assert PlantBlueprint.from_dict(a.blueprint.to_dict()).fingerprint() == a.blueprint.fingerprint()
    assert PlantGrowthSnapshot.from_dict(a.render_snapshot.to_dict()).to_dict() == a.render_snapshot.to_dict()
    b = sim({**entity, "plant_inflorescence_profile": {**profile, "display_floret_count": 7}})
    assert a.blueprint.fingerprint() != b.blueprint.fingerprint()
    assert "inflorescence_profile" not in sim({**entity, "plant_reproductive_structure": "cone"}).blueprint.growth


def test_raceme_has_alternating_stalks_and_a_distal_flower(profile):
    layout = list(raceme_layout(profile))
    assert layout == list(raceme_layout(profile))
    assert len(layout) == 5
    assert layout[-1] == (0, profile["length_m"])
    assert [math.copysign(1, x) for x, z in layout[:-1]] == [1, -1, 1, -1]
    assert all(math.isfinite(x) and math.isfinite(z) and abs(x) <= profile["width_m"]/2
               and 0 < z <= profile["length_m"] for x, z in layout)


def test_display_recipe_never_multiplies_ecological_organs(entity, profile):
    control = {**entity}; control.pop("plant_inflorescence_profile")
    alternate = {**entity, "plant_inflorescence_profile": {**profile, "display_floret_count": 7}}
    for lod in (0, 1, 2):
        a, b, c = sim(entity, lod=lod), sim(control, lod=lod), sim(alternate, lod=lod)
        assert a.render_snapshot.placements == b.render_snapshot.placements == c.render_snapshot.placements
        assert a.get_ecological_outcome() == b.get_ecological_outcome() == c.get_ecological_outcome()


def test_deterministic_canes_lod_ecology_and_unrelated_reuse(entity):
    a = sim(entity)
    assert a.render_snapshot.to_dict() == sim(entity).render_snapshot.to_dict()
    assert 2 <= a.render_snapshot.stats["shrub_cane_count"] <= 10
    assert 2 < a.render_snapshot.bounds_m[5] < 4
    assert a.render_snapshot.stats["root_model_status"] == "unresolved"
    for i, p in enumerate(a.render_snapshot.placements):
        assert p[1] == -1 or 0 <= p[1] < i
        assert all(math.isfinite(v) for v in p[2:7])
        if p[0] == "flower":
            assert a.render_snapshot.placements[p[1]][0] in {"stem_section", "branch_section"}
    simulations = [sim(entity, lod=lod) for lod in (0, 1, 2)]
    metrics = [(s.render_snapshot.stats["estimated_leaf_count"], s.render_snapshot.stats["leaf_area_m2"],
                s.render_snapshot.stats["root_length_m"]) for s in simulations]
    assert metrics[0] == metrics[1] == metrics[2]
    assert not sim(entity, 30).render_snapshot.stats["shrub_flower_count"]
    assert a.render_snapshot.stats["shrub_flower_count"] > 0
    fixture = {**entity, "id": "synthetic_unrelated_raceme_shrub", "parents": [],
               "common_name": "Unrelated fixture", "mature_height": {"typical_m": 1.5}}
    other = sim(fixture)
    assert other.blueprint.growth["inflorescence_profile"] == a.blueprint.growth["inflorescence_profile"]
    assert .9 < other.render_snapshot.bounds_m[5] < 2
    assert other.render_snapshot.to_dict() == sim(fixture).render_snapshot.to_dict()


def test_saved_pixel_studio_asset_matches_inspected_manifest(world):
    from tools.author_plant_assets import PixelEditorHost, load_manifest, render_module
    from ui.pixel_art_editor_ui import PixelArtEditorUI
    pygame.init(); pygame.display.set_mode((1, 1))
    module = load_manifest(Path("assets/plant_asset_specs/spec_philadelphus_coronarius.json"))["modules"][0]
    illustration = world.get_entity(module["illustration_id"])
    assert illustration["parents"] == ["spec_philadelphus_coronarius"]
    editor = PixelArtEditorUI(PixelEditorHost(world.loader))
    assert editor.open(module["illustration_id"]) and editor.state["stage"] == "canvas"
    saved = pygame.image.load(illustration["media_path"])
    assert saved.get_size() == (75, 75)
    assert pygame.image.tobytes(saved, "RGBA") == pygame.image.tobytes(render_module(module), "RGBA")
    with gzip.open(illustration["pixel_document_path"], "rt") as stream:
        assert json.load(stream)["version"] == 2


def test_compositor_physical_scale_bounds_and_renderer_cache(entity, profile):
    pygame.init(); pygame.display.set_mode((1, 1))
    renderer = SpeciesRenderer(SimpleNamespace(camera=None))
    simulation = sim(entity)
    flower = renderer._module_asset(simulation, "flower")
    assert flower is not None
    for ppm in (0, None, float("nan"), float("inf"), 50, 500, 2500, 1e9):
        surface, anchor = raceme_surface(profile, ppm, flower)
        assert max(surface.get_size()) <= 516
        assert 0 <= anchor[0] < surface.get_width() and 0 <= anchor[1] < surface.get_height()
        assert pygame.image.tobytes(surface, "RGBA") == pygame.image.tobytes(raceme_surface(profile, ppm, flower)[0], "RGBA")
    small, _ = raceme_surface(profile, 50, flower)
    large, _ = raceme_surface(profile, 500, flower)
    assert large.get_height() > small.get_height()*5
    # Petal colour survives when each corolla occupies fewer than two pixels.
    assert any(c.a and min(c.r, c.g, c.b) > 170
               for x in range(small.get_width()) for y in range(small.get_height())
               for c in [small.get_at((x, y))])
    screen = pygame.Surface((400, 400), pygame.SRCALPHA)
    camera = DiagnosticCamera(400, 400, (-.15, .15, -.02, .3))
    assert renderer._draw_module_asset(screen, simulation, camera, "flower", (200, 350), 0, 1)
    assert screen.get_bounding_rect().height > 80
    renderer._draw_module_asset(screen, simulation, camera, "flower", (200, 350), 0, 1)
    assert len(renderer._inflorescence_sprite_cache) == 1
