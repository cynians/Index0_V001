"""Measured panicles, display-only bloom progression and neutral defaults."""
import json
import gzip
import math
import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import pygame
import pytest

from simulations.species.inflorescences import (
    bloom_progress, floret_layout, floret_stage, inflorescence_profile, panicle_surface,
    panicle_axis_points,
    _area_resample,
)
from simulations.species.plant_assets import PlantBlueprint, PlantGrowthSnapshot
from simulations.species.species_editor import field_group, PREVIEW_AFFECTING_FIELDS
from simulations.species.species_renderer import SpeciesRenderer, DiagnosticCamera
from simulations.species.species_simulation import SpeciesSimulation
from world.world_model import WorldModel


@pytest.fixture(scope="module")
def entity():
    world = WorldModel()
    assert world.loader.plant_catalogue.is_species("spec_buddleja_davidii")
    raw = world.resolved_species_entity("spec_buddleja_davidii")
    assert raw["parents"] == ["cladis_buddleja"]
    return raw


@pytest.fixture(scope="module")
def profile(entity):
    return inflorescence_profile(entity["plant_inflorescence_profile"])


def sim(entity, age=180, lod=2):
    result = SpeciesSimulation(species_entity=entity, seed=303)
    result.set_lod(lod); result.set_age(age)
    return result


@pytest.mark.parametrize("value", [None, {}, 0, "other_unknown"])
def test_unauthored_neutral(value, entity):
    a = {**entity}; a.pop("plant_inflorescence_profile")
    b = {**a, "plant_inflorescence_profile": value}
    assert inflorescence_profile(value) is None
    assert sim(a).blueprint.fingerprint() == sim(b).blueprint.fingerprint()
    assert sim(a).render_snapshot.to_dict() == sim(b).render_snapshot.to_dict()


@pytest.mark.parametrize("key,value", [
    ("length_m", 0), ("width_m", float("nan")), ("flower_size_m", float("inf")),
    ("opening_diameter_m", True), ("unit", "whole_panicle"),
    ("display_floret_count", 100000), ("display_floret_count", True),
    ("opening_sequence", "unknown"), ("axis_color", [True, 1, 2]),
])
def test_reject_invalid(profile, key, value):
    assert inflorescence_profile({**profile, key: value}) is None


def test_transport_portable_and_fingerprint(entity, profile):
    a = sim(entity)
    assert a.blueprint.growth["inflorescence_profile"] == profile
    assert a.blueprint.module("flower").visual["depicted_size_m"] == .01075
    assert profile["length_m"] == .28
    assert PlantBlueprint.from_dict(a.blueprint.to_dict()).fingerprint() == a.blueprint.fingerprint()
    assert PlantGrowthSnapshot.from_dict(a.render_snapshot.to_dict()).to_dict() == a.render_snapshot.to_dict()
    b = {**entity, "plant_inflorescence_profile": {**profile, "width_m": .045}}
    assert a.blueprint.fingerprint() != sim(b).blueprint.fingerprint()
    assert field_group("plant_inflorescence_profile") == "Reproduction"
    assert "plant_inflorescence_profile" in PREVIEW_AFFECTING_FIELDS
    other = {**entity, "plant_reproductive_structure": "cone"}
    assert "inflorescence_profile" not in sim(other).blueprint.growth


def test_geometry_and_stage_direction(profile):
    layout = list(floret_layout(profile))
    assert layout == list(floret_layout(profile))
    assert len(layout) == profile["display_floret_count"]
    for t, x, z in layout:
        assert all(math.isfinite(v) for v in (t, x, z))
        assert 0 < t < 1 and 0 < z < profile["length_m"]
        assert abs(x) < profile["width_m"]/2
        order = {"bud":0, "open":1, "spent":2}
        stages = [order[floret_stage(profile,t,p)] for p in (0,.2,.5,.8,1)]
        assert stages == sorted(stages)
    assert floret_stage(profile,.1,.5) == "spent"
    assert floret_stage(profile,.5,.5) == "open"
    assert floret_stage(profile,.9,.5) == "bud"
    reversed_profile = {**profile,"opening_sequence":"tip_to_base"}
    assert floret_stage(reversed_profile,.9,.5) == "spent"
    assert floret_stage(reversed_profile,.1,.5) == "bud"


def test_model_timing_explicit_and_seasonal(profile, entity):
    growth = sim(entity).blueprint.growth
    assert bloom_progress(growth,180) == pytest.approx(.3578767123)
    assert bloom_progress(growth,0) == 0
    assert bloom_progress(growth,10000) == 1
    seasonal = {**growth,"reproductive_profile":{"cycle_days":365,"flowering_start":.2,"flowering_end":.6}}
    assert bloom_progress(seasonal,365*.4) == pytest.approx(.5)
    assert bloom_progress(seasonal,365*1.4) == pytest.approx(.5)


def test_ecology_geometry_lod_and_unrelated_reuse(entity, profile):
    control = {**entity}; control.pop("plant_inflorescence_profile")
    for lod in (0,1,2):
        a,b = sim(entity,lod=lod), sim(control,lod=lod)
        assert a.render_snapshot.placements == b.render_snapshot.placements
        assert a.get_ecological_outcome() == b.get_ecological_outcome()
        for i,p in enumerate(a.render_snapshot.placements):
            assert p[1] == -1 or 0 <= p[1] < i
            assert all(math.isfinite(v) for v in p[2:7])
    unrelated = {**entity,"id":"synthetic_unrelated_panicle","parents":[],
                 "plant_growth_form":"forb","plant_growth_behaviour":"iterative_indeterminate"}
    a,b = sim(unrelated),sim(unrelated)
    assert a.render_snapshot.to_dict() == b.render_snapshot.to_dict()
    assert a.blueprint.growth["inflorescence_profile"] == profile


def test_surface_scale_bounded_and_actual_flower_asset(entity, profile):
    pygame.init(); pygame.display.set_mode((1,1))
    renderer = SpeciesRenderer(SimpleNamespace(camera=None)); simulation = sim(entity)
    flower = renderer._module_asset(simulation,"flower")
    assert flower is not None
    straight = {k:v for k,v in profile.items() if k not in {
        "axis_curvature","bloom_sag","front_facing_fraction","corolla_lobes"}}
    for ppm in (50,500,2500,100000):
        surface, anchor = panicle_surface(straight,ppm,.5,flower)
        assert surface.get_height() <= 1028
        effective = min(ppm,1024/profile["length_m"])
        assert surface.get_height() == max(2,round(profile["length_m"]*effective))+4
        assert surface.get_width() == max(2,round(profile["width_m"]*effective))+4
        assert 0 <= anchor[0] < surface.get_width() and 0 <= anchor[1] < surface.get_height()
        assert pygame.image.tobytes(surface,"RGBA") == pygame.image.tobytes(panicle_surface(straight,ppm,.5,flower)[0],"RGBA")
    early = panicle_surface(profile,1000,.2,flower)[0]
    late = panicle_surface(profile,1000,.8,flower)[0]
    assert pygame.image.tobytes(early,"RGBA") != pygame.image.tobytes(late,"RGBA")
    camera = DiagnosticCamera(400,400,(-.2,.2,-.02,.3))
    screen = pygame.Surface((400,400),pygame.SRCALPHA)
    assert renderer._draw_module_asset(screen,simulation,camera,"flower",(200,350),0,1)
    assert screen.get_bounding_rect().height > 100
    assert len(renderer._inflorescence_sprite_cache) == 1
    renderer._draw_module_asset(screen,simulation,camera,"flower",(200,350),0,1)
    assert len(renderer._inflorescence_sprite_cache) == 1


def test_saved_modules_reopen_and_match_manifest():
    from tools.author_plant_assets import PixelEditorHost, load_manifest, render_module
    from ui.pixel_art_editor_ui import PixelArtEditorUI
    pygame.init(); pygame.display.set_mode((1,1))
    world = WorldModel()
    manifest = load_manifest(Path("assets/plant_asset_specs/spec_buddleja_davidii.json"))
    host = PixelEditorHost(world.loader)
    for module in manifest["modules"]:
        illustration = world.get_entity(module["illustration_id"])
        editor = PixelArtEditorUI(host)
        assert editor.open(module["illustration_id"]) and editor.state["stage"] == "canvas"
        saved = pygame.image.load(illustration["media_path"])
        assert saved.get_size() == (75,75)
        assert pygame.image.tobytes(saved,"RGBA") == pygame.image.tobytes(render_module(module),"RGBA")
        with gzip.open(illustration["pixel_document_path"],"rt") as stream:
            assert json.load(stream)["version"] == 2


def test_small_corolla_keeps_petals_instead_of_sampling_only_eye(profile):
    pygame.init()
    flower = pygame.Surface((75,75),pygame.SRCALPHA)
    flower.fill((150,80,190,255))
    pygame.draw.circle(flower,(250,160,20,255),(37,37),5)
    all_open = {**profile,"open_band_fraction":1.,"axis_color":[0,255,0],"front_facing_fraction":0}
    surface,_ = panicle_surface(all_open,50,.9,flower)
    pixels = [surface.get_at((x,y)) for x in range(surface.get_width()) for y in range(surface.get_height())]
    assert any(c.a and c.b > c.r > c.g for c in pixels)
    assert not any(c.a and c.r > 240 and c.b < 30 for c in pixels)


@pytest.mark.parametrize("value", [0,None,"other_unknown",True,float("nan"),-1,2])
def test_neutral_bend_controls_keep_legacy_fingerprint(entity, profile, value):
    legacy = {k:v for k,v in entity["plant_inflorescence_profile"].items()
              if k not in {"axis_curvature","bloom_sag"}}
    a = sim({**entity,"plant_inflorescence_profile":legacy})
    b = sim({**entity,"plant_inflorescence_profile":{**legacy,"axis_curvature":value,"bloom_sag":value}})
    assert a.blueprint.fingerprint() == b.blueprint.fingerprint()
    assert a.render_snapshot.placements == b.render_snapshot.placements


def test_curved_axis_has_constant_length_and_gravity_direction(profile):
    for rotation in (0,-.001,.001,-50,50,-90,90,180):
        light = panicle_axis_points(profile,.12,rotation)
        heavy = panicle_axis_points(profile,.5,rotation)
        assert light[0][:2] == heavy[0][:2] == (0.,0.)
        assert heavy == panicle_axis_points(profile,.5,rotation)
        length = sum(math.hypot(b[0]-a[0],b[1]-a[1]) for a,b in zip(heavy,heavy[1:]))
        assert length == pytest.approx(profile["length_m"])
        assert all(math.isfinite(v) for point in heavy for v in point)
        assert all(math.hypot(*point[:2]) <= profile["length_m"]+1e-9 for point in heavy)
        if rotation != 180:
            assert heavy[-1][1] > light[-1][1]
            assert math.sin(heavy[-1][2]) > math.sin(light[-1][2])
    # Both left- and right-facing tips bend toward screen-down gravity.
    assert panicle_axis_points(profile,.5,-90)[-1][1] > 0
    assert panicle_axis_points(profile,.5,90)[-1][1] > 0
    assert math.sin(panicle_axis_points(profile,.5,0)[-1][2]) > 0


def test_curved_display_bounds_anchor_and_orientation_cache(entity, profile):
    pygame.init();pygame.display.set_mode((1,1))
    renderer = SpeciesRenderer(SimpleNamespace(camera=None));simulation = sim(entity)
    flower = renderer._module_asset(simulation,"flower")
    for rotation in (-90,0,90,180):
        sprite,anchor = panicle_surface(profile,100000,.5,flower,rotation)
        assert max(sprite.get_size()) <= 1028
        assert 0 <= anchor[0] < sprite.get_width() and 0 <= anchor[1] < sprite.get_height()
        assert pygame.image.tobytes(sprite,"RGBA") == pygame.image.tobytes(panicle_surface(profile,100000,.5,flower,rotation)[0],"RGBA")
    camera = DiagnosticCamera(400,400,(-.2,.2,-.2,.2))
    screen = pygame.Surface((400,400),pygame.SRCALPHA)
    renderer._draw_module_asset(screen,simulation,camera,"flower",(200,200),-90,1)
    renderer._draw_module_asset(screen,simulation,camera,"flower",(200,200),90,1)
    assert len(renderer._inflorescence_sprite_cache) == 2
    assert simulation.blueprint.growth["inflorescence_profile"]["version"] >= 2


def test_transparent_pixel_filter_preserves_petal_colour():
    pygame.init()
    source = pygame.Surface((4,1),pygame.SRCALPHA)
    source.set_at((0,0),(182,129,206,255));source.set_at((1,0),(182,129,206,255))
    pixel = _area_resample(source,(1,1)).get_at((0,0))
    assert pixel.a == pytest.approx(127,abs=1)
    assert tuple(pixel[:3]) == pytest.approx((182,129,206),abs=2)


@pytest.mark.parametrize("value", [None,0,"other_unknown",True,float("nan"),-1,2])
def test_neutral_flower_faces_keep_legacy_recipe(entity,value):
    legacy = {k:v for k,v in entity["plant_inflorescence_profile"].items()
              if k not in {"front_facing_fraction","corolla_lobes"}}
    a = sim({**entity,"plant_inflorescence_profile":legacy})
    b = sim({**entity,"plant_inflorescence_profile":{**legacy,"front_facing_fraction":value,"corolla_lobes":4}})
    assert a.blueprint.fingerprint() == b.blueprint.fingerprint()


def test_dense_peak_corollas_cover_more_of_the_measured_head(entity,profile):
    pygame.init();pygame.display.set_mode((1,1))
    renderer = SpeciesRenderer(SimpleNamespace(camera=None));simulation = sim(entity)
    flower = renderer._module_asset(simulation,"flower")
    face_on,anchor = panicle_surface(profile,180,.5,flower,-50)
    tubular,_ = panicle_surface({**profile,"front_facing_fraction":0},180,.5,flower,-50)
    def petal_coverage(surface):
        return sum(c.a/255 for x in range(surface.get_width()) for y in range(surface.get_height())
                   if (c:=surface.get_at((x,y))).b > c.g*1.3 and c.r > c.g*1.15 and c.b > 100)
    assert petal_coverage(face_on) > petal_coverage(tubular)*2
    assert 0 <= anchor[0] < face_on.get_width() and 0 <= anchor[1] < face_on.get_height()
    assert profile["corolla_lobes"] == 4 and profile["version"] == 3
    low_band = {**profile,"open_band_fraction":.26}
    assert sum(floret_stage(profile,t,.5)=="open" for t,x,z in floret_layout(profile)) > sum(
        floret_stage(low_band,t,.5)=="open" for t,x,z in floret_layout(low_band))*2
