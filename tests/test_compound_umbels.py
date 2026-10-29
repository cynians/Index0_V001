"""Shared two-level umbels, physical organ scale and iterative forb transport."""
import gzip
import json
import math
import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import pygame
import pytest

from simulations.species.compound_umbels import compound_umbel_layout, compound_umbel_surface
from simulations.species.inflorescences import inflorescence_profile
from simulations.species.plant_assets import PlantBlueprint, PlantGrowthSnapshot
from simulations.species.species_renderer import SpeciesRenderer, DiagnosticCamera
from simulations.species.species_simulation import SpeciesSimulation
from world.world_model import WorldModel
from world.plant_traits import PLANT_TRAIT_CHOICES


@pytest.fixture(scope="module")
def entity():
    world = WorldModel()
    assert world.loader.plant_catalogue.is_species("spec_torilis_arvensis")
    result = world.resolved_species_entity("spec_torilis_arvensis")
    assert result["parents"] == ["cladis_hedge_parsleys_torilis"]
    return result


def simulation(entity, lod=2):
    sim = SpeciesSimulation(species_entity=entity, seed=303)
    sim.set_lod(lod)
    sim.set_age(sim.blueprint.growth["life_history"]["reproductive_start_days"] + 45)
    return sim


@pytest.mark.parametrize("key,value", [
    ("length_m", 0), ("length_m", .006), ("width_m", float("nan")), ("flower_size_m", float("inf")),
    ("umbellet_diameter_m", True), ("umbellet_diameter_m", .1),
    ("unit", "whole_umbel"), ("ray_count", 9999), ("ray_count", True),
    ("flowers_per_umbellet", 0), ("axis_color", [True, 1, 2]),
])
def test_invalid_profile_is_neutral(entity, key, value):
    profile = entity["plant_inflorescence_profile"]
    assert inflorescence_profile({**profile, key:value}) is None


def test_live_transport_migration_and_unknowns(entity):
    updates = json.loads((Path(__file__).resolve().parent / "fixtures/species/torilis_compound_umbel_updates.json").read_text())["updates"]
    assert all(entity[key] == value for key, value in updates.items())
    assert any(row["value"] == "compound_umbel" and row["label"] == "Compound umbel"
               for row in PLANT_TRAIT_CHOICES["plant_reproductive_structure"])
    sim = simulation(entity)
    assert sim.blueprint.growth["inflorescence_profile"] == inflorescence_profile(entity["plant_inflorescence_profile"])
    assert sim.blueprint.growth["umbellifer_forb_grammar_version"] == 1
    assert sim.blueprint.module("flower").visual["depicted_size_m"] == .002
    assert entity["root_depth_class"] == "other_unknown"
    assert not entity.get("max_root_depth")
    assert not entity.get("maturity_age") and not entity.get("longevity")


def test_two_ray_levels_bounded_and_deterministic(entity):
    profile = inflorescence_profile(entity["plant_inflorescence_profile"])
    rays = list(compound_umbel_layout(profile))
    assert rays == list(compound_umbel_layout(profile))
    assert len(rays) == profile["ray_count"] == 6
    assert len({ray["fork"] for ray in rays}) == 1
    assert len({ray["center"] for ray in rays}) == 6
    assert sum(len(ray["flowers"]) for ray in rays) == 54
    for ray in rays:
        for x,z in [ray["fork"],ray["center"],*ray["flowers"]]:
            assert math.isfinite(x) and math.isfinite(z)
            assert abs(x) <= profile["width_m"]*.5
            assert 0 <= z <= profile["length_m"]


def test_extreme_valid_envelopes_remain_bounded(entity):
    for width,height in ((.5,.005),(.005,.5),(.5,.5)):
        raw = {**entity["plant_inflorescence_profile"],"width_m":width,"length_m":height,
               "umbellet_diameter_m":min(width,height)*.5,"flower_size_m":.001,
               "ray_count":16,"flowers_per_umbellet":32}
        profile = inflorescence_profile(raw)
        assert profile is not None
        rays = list(compound_umbel_layout(profile))
        assert sum(len(r["flowers"]) for r in rays) == 512
        for ray in rays:
            for x,z in ray["flowers"]:
                assert abs(x)+profile["flower_size_m"]*.5 <= width*.5
                assert 0 <= z-profile["flower_size_m"]*.5
                assert z+profile["flower_size_m"]*.5 <= height


def test_geometry_serialization_sockets_and_synthetic_reuse(entity):
    unrelated = {**entity,"id":"spec_unrelated_test_umbellifer","parents":[]}
    sim = simulation(unrelated)
    snap = sim.render_snapshot
    assert snap.to_dict() == simulation(unrelated).render_snapshot.to_dict()
    assert PlantGrowthSnapshot.from_dict(snap.to_dict()).to_dict() == snap.to_dict()
    assert PlantBlueprint.from_dict(sim.blueprint.to_dict()).fingerprint() == sim.blueprint.fingerprint()
    assert sum(p[0] not in {"root","root_section","root_support"} for p in snap.placements) < 100
    assert sum(p[0] == "flower" for p in snap.placements) >= 4
    for index,p in enumerate(snap.placements):
        assert p[1] == -1 or 0 <= p[1] < index
        assert all(math.isfinite(v) for v in p[2:7])
    for socket in snap.attachment_points:
        if "leaf_placement_index" in socket:
            leaf = snap.placements[socket["leaf_placement_index"]]
            assert leaf[1] == socket["stem_placement_index"]
            assert list(leaf[2:5]) == socket["position_m"]


def test_lod_preserves_axes_cohorts_roots_and_ecology(entity):
    sims = [simulation(entity,lod) for lod in (0,1,2)]
    axes = [[(p[0],*p[2:]) for p in s.render_snapshot.placements
             if p[0] in {"stem_section","branch_section"}] for s in sims]
    assert axes[0] == axes[1] == axes[2]
    for key in ("estimated_leaf_count","leaf_area_m2","root_depth_m","root_length_m"):
        assert len({s.render_snapshot.stats[key] for s in sims}) == 1
    for key in ("vitality","fecundity","leaf_area_proxy","root_depth_m"):
        assert len({s.get_ecological_outcome({})[key] for s in sims}) == 1
    assert sims[0].render_snapshot.stats["leaf_count"] == 0


def test_display_profile_changes_fingerprint_without_ecological_organs(entity):
    changed = {**entity,"plant_inflorescence_profile":{**entity["plant_inflorescence_profile"],"ray_count":8}}
    a,b = simulation(entity), simulation(changed)
    assert a.blueprint.fingerprint() != b.blueprint.fingerprint()
    assert a.render_snapshot.placements == b.render_snapshot.placements
    assert a.get_ecological_outcome({}) == b.get_ecological_outcome({})
    legacy = {**entity,"plant_reproductive_structure":"other_unknown"}
    assert "umbellifer_forb_grammar_version" not in simulation(legacy).blueprint.growth
    assert "inflorescence_profile" not in simulation(legacy).blueprint.growth


def test_physical_flower_scale_render_budget_and_cache(entity):
    pygame.init(); pygame.display.set_mode((1,1))
    renderer = SpeciesRenderer(SimpleNamespace(camera=None)); sim = simulation(entity)
    profile = sim.blueprint.growth["inflorescence_profile"]
    flower = renderer._module_asset(sim,"flower")
    assert flower is not None
    for ppm in (50,500,2500,100000):
        surface,anchor = compound_umbel_surface(profile,ppm,.5,flower)
        effective = min(ppm,1024/max(profile["width_m"],profile["length_m"]))
        assert surface.get_size() == (max(2,round(profile["width_m"]*effective))+6,
                                      max(2,round(profile["length_m"]*effective))+6)
        assert max(surface.get_size()) <= 1030
        assert 0 <= anchor[0] < surface.get_width() and 0 <= anchor[1] < surface.get_height()
        assert pygame.image.tobytes(surface,"RGBA") == pygame.image.tobytes(compound_umbel_surface(profile,ppm,.5,flower)[0],"RGBA")
    screen = pygame.Surface((400,400),pygame.SRCALPHA)
    camera = DiagnosticCamera(400,400,(-.03,.03,-.002,.04))
    assert renderer._draw_module_asset(screen,sim,camera,"flower",(200,350),0,1)
    height = screen.get_bounding_rect().height
    assert 40 < height < 100
    assert len(renderer._inflorescence_sprite_cache) == 1
    renderer._draw_module_asset(screen,sim,camera,"flower",(200,350),0,1)
    assert len(renderer._inflorescence_sprite_cache) == 1
    zoom = pygame.Surface((400,400),pygame.SRCALPHA)
    zoom_camera = DiagnosticCamera(400,400,(-.03,.03,-.002,.04),minimum_span_m=.05)
    renderer._draw_module_asset(zoom,sim,zoom_camera,
                                "flower",(200,350),0,1)
    assert zoom.get_bounding_rect().height == pytest.approx(height*zoom_camera.scale/camera.scale,abs=5)


def test_saved_editable_assets_reopen_exactly():
    from tools.author_plant_assets import PixelEditorHost, load_manifest, render_module
    from ui.pixel_art_editor_ui import PixelArtEditorUI
    pygame.init(); pygame.display.set_mode((1,1))
    world = WorldModel(); host = PixelEditorHost(world.loader)
    manifest = load_manifest(Path("assets/plant_asset_specs/spec_torilis_arvensis.json"))
    for module in manifest["modules"]:
        illustration = world.get_entity(module["illustration_id"])
        editor = PixelArtEditorUI(host)
        assert editor.open(module["illustration_id"]) and editor.state["stage"] == "canvas"
        saved = pygame.image.load(illustration["media_path"])
        assert saved.get_size() == (75,75)
        assert pygame.image.tobytes(saved,"RGBA") == pygame.image.tobytes(render_module(module),"RGBA")
        with gzip.open(illustration["pixel_document_path"],"rt") as stream:
            assert json.load(stream)["version"] == 2
