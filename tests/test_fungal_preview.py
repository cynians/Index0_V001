"""Diagnostic wood artwork is uniform; metric fungal growth is preserved."""
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pygame
import pytest

from simulations.species.fungal_growth import wood_test_fixture
from simulations.species.fungal_visuals import preview_wood_style, _draw_preview_bark, _sprite, MetricPreviewCamera
from simulations.species.species_renderer import SpeciesRenderer, DiagnosticCamera
from simulations.species.species_simulation import SpeciesSimulation
from tools.render_species_views import stage_ages, render

ROOT = Path(__file__).resolve().parents[1]


def fungus(sid="spec_synthetic_preview_fixture", age=90, width=.23):
    p = json.loads((ROOT/"assets/species_trait_specs/spec_cerioporus_squamosus.json").read_text())["updates"]["fungal_growth_profile"]
    p["visual_calibration"]["cap_width_m"] = width
    s = SpeciesSimulation(species_entity={"id":sid, "fungal_growth_profile":p}, seed=303)
    s.set_lod(2); s.set_age(age)
    return s


def test_stage_selection_shows_real_fungal_phases_without_plant_organs():
    s = fungus()
    stages = stage_ages(s)
    assert [s.life_state(age)["phase"] for _, age in stages] == [
        "colonising", "emerging", "expanding", "sporulating", "between_flushes"]
    assert s.life_state(stages[3][1])["fruit_body_expansion"] == 1
    assert stages[3][1] >= s.mature_age_days
    assert not any("Flower" in label or "Fruiting" in label for label, _ in stages)


def test_uniform_oak_support_is_independent_of_fungus_recipe_and_identity():
    pygame.init(); pygame.display.set_mode((1, 1))
    renderer = SpeciesRenderer(SimpleNamespace(camera=None))
    camera = DiagnosticCamera(500, 500, (-.5, .5, -.1, 1.35))
    screens = []
    for sid, width in (("spec_synthetic_a", .23), ("spec_unrelated_sessile_preview", .07)):
        s = fungus(sid, age=1, width=width)
        before = deepcopy(s.render_snapshot.to_dict())
        ecology = s.get_ecological_outcome()
        canvas = pygame.Surface((500, 500))
        renderer._draw_individual(canvas, s, camera=camera, cache=False)
        background = pygame.mask.from_threshold(canvas, (18,23,20,255), (1,1,1,255))
        background.invert()
        bounds = background.get_bounding_rects()
        wood_width = max(r.right for r in bounds)-min(r.left for r in bounds)
        assert wood_width == pytest.approx(.32*camera.scale, abs=3)
        screens.append(pygame.image.tobytes(canvas, "RGB"))
        assert s.render_snapshot.to_dict() == before
        assert s.get_ecological_outcome() == ecology
    assert screens[0] == screens[1]
    assert "quercus_petraea_bark" in preview_wood_style()["bark_texture_set_ref"]
    wood = wood_test_fixture()["fungal_substrates"][0]
    assert wood["radius_m"] == .16 and wood["end_m"][2] == 1.2
    # Explicit custom supports retain their own rendering route.
    assert not _draw_preview_bark(renderer, canvas, {**wood, "id":"actual_host"}, (20,20), (20,200), 30, 300)
    pygame.quit()


def test_cap_pixels_follow_metres_at_the_same_camera_scale():
    pygame.init();pygame.display.set_mode((1, 1))
    s = fungus()
    renderer = SpeciesRenderer(SimpleNamespace(camera=None))
    source = pygame.Surface((75, 75), pygame.SRCALPHA);source.fill((225, 220, 150, 255))
    renderer._module_asset = lambda *_: source
    camera = DiagnosticCamera(600, 500, (0, 1, 0, 1))
    for width in (.025, .23):
        screen = pygame.Surface((600,500), pygame.SRCALPHA)
        assert _sprite(renderer, screen, s, camera, "fruiting_body", (300,250), width)
        assert screen.get_bounding_rect().width == round(width*camera.scale)
    # The sampled early flush really is smaller, rather than a rendering scale error.
    early = fungus(age=32.85)
    assert max(b["cap_width_m"] for b in early.render_snapshot.stats["fungal_bodies"]) < .035
    assert min(b["cap_width_m"] for b in s.render_snapshot.stats["fungal_bodies"]) > .17
    pygame.quit()


def test_metric_preview_basis_preserves_real_cap_to_trunk_width_ratio():
    import math
    from simulations.species.species_simulation import SCREEN_DEPTH_PROJECTION
    raw = DiagnosticCamera(600,500,(-.5,.5,0,1.2))
    norm = math.sqrt(1+SCREEN_DEPTH_PROJECTION**2)
    camera = MetricPreviewCamera(raw,norm)
    radius = .16
    # Extreme points of a circular section along the horizontal camera basis.
    edge = (radius/norm,radius*SCREEN_DEPTH_PROJECTION/norm,.5)
    opposite = (-edge[0],-edge[1],.5)
    actual = camera.world_to_screen_3d(edge)[0]-camera.world_to_screen_3d(opposite)[0]
    assert actual == pytest.approx(.32*camera.scale,abs=2)
    assert (.23*camera.scale)/actual == pytest.approx(.23/.32,abs=.015)


def test_saved_fungal_multiview_has_unclipped_support_bounds_and_correct_labels():
    scratch = ROOT/"artifacts"/f".fungal_viewer_test_{uuid4().hex}"
    scratch.mkdir()
    try:
        render("spec_cerioporus_squamosus", scratch)
        d = json.loads((scratch/"after.json").read_text())
        assert pygame.image.load(scratch/"after.png").get_size() == (1540,1030)
    finally:
        (scratch/"after.png").unlink(missing_ok=True)
        (scratch/"after.json").unlink(missing_ok=True)
        scratch.rmdir()
    assert d["bounds_m"][4] < 0 and d["bounds_m"][5] > 1.2
    assert d["preview_wood_style"] == preview_wood_style()
    for stage in d["stages"]:
        snap = stage["snapshot"]
        assert snap["stats"]["fungal_substrates"][0]["radius_m"] == .16
        assert snap["stats"]["leaf_count"] == 0
        assert not any(p[0] in {"leaf", "flower", "root_section"} for p in snap["placements"])
        for axis in range(3):
            assert d["bounds_m"][axis*2] < snap["bounds_m"][axis*2]
            assert d["bounds_m"][axis*2+1] > snap["bounds_m"][axis*2+1]
