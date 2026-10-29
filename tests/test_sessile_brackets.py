"""Direct wood attachment preserves the existing stalked bracket recipe."""
import json
import math
from pathlib import Path

import pytest

from simulations.species.fungal_growth import normalise_profile, wood_test_fixture
from simulations.species.plant_assets import PlantBlueprint, PlantGrowthSnapshot
from simulations.species.species_simulation import SpeciesSimulation
from world.fungal_traits import validate_fungal_profile
from world.world_model import WorldModel


def recipe():
    return json.loads(Path("assets/species_trait_specs/spec_trametes_gibbosa.json").read_text())["updates"]["fungal_growth_profile"]


def grown(age=90,lod=2,profile=None,environment=None):
    sim=SpeciesSimulation(species_entity={"id":"spec_synthetic_sessile_bracket","fungal_growth_profile":profile or recipe()},
                          seed=303,environment=environment)
    sim.set_lod(lod);sim.set_age(age)
    return sim


@pytest.mark.parametrize("change", [
    {"stipe_length":{"typical_m":.01}}, {"stipe_diameter":{"typical_m":False}},
    {"stipe_length":{"typical_m":-.01}}, {"visual_calibration":{"stipe_length_m":.01}},
    {"visual_calibration":{"stipe_diameter_m":True}}, {"visual_calibration":{"stipe_length_m":"0"}},
    {"cap_thickness":{"min_m":.05,"max_m":.01}}, {"cap_depth":{"typical_m":0}}])
def test_sessile_recipe_rejects_contradictory_or_invalid_dimensions(change):
    profile=recipe();profile.update(change)
    with pytest.raises(ValueError):validate_fungal_profile(profile)


def test_zero_and_absent_stalk_dimensions_are_equivalent():
    absent=normalise_profile(recipe())
    zero=recipe();zero.update(stipe_length={"typical_m":0},stipe_diameter={"typical_m":0})
    assert normalise_profile(zero)["resolved"]==absent["resolved"]
    assert absent["resolved"]["stipe_length_m"]==absent["resolved"]["stipe_diameter_m"]==0
    zero["attachment"]="short_eccentric_to_lateral_stipe"
    with pytest.raises(ValueError):validate_fungal_profile(zero)


@pytest.mark.parametrize("kind", ["trunk","log"])
def test_sessile_bodies_meet_substrate_at_every_stage_and_lod(kind):
    for age in (35,60,90,108,130,210):
        sims=[grown(age,lod,environment=wood_test_fixture(kind)) for lod in range(3)]
        assert sims[0].render_snapshot.bounds_m==sims[1].render_snapshot.bounds_m==sims[2].render_snapshot.bounds_m
        assert sims[0].get_ecological_outcome()==sims[1].get_ecological_outcome()==sims[2].get_ecological_outcome()
        for sim in sims:
            snap=sim.render_snapshot
            assert len(snap.placements)<100
            for i,p in enumerate(snap.placements):
                assert p[1]==-1 or 0<=p[1]<i
                assert all(math.isfinite(v) for v in p[2:7])
            for b in snap.stats["fungal_bodies"]:
                assert b["stipe_length_m"]==b["stipe_diameter_m"]==0
                assert b["cap_socket_m"]==pytest.approx(b["socket_m"],abs=.00005)
                # cap_socket keeps full precision; socket_m is a 0.1 mm
                # serialized placement whose radial error can exceed half
                # one coordinate's rounding step in three dimensions.
                assert math.dist(b["substrate_center_m"],b["cap_socket_m"])==pytest.approx(b["substrate_radius_m"],abs=1e-8)
            assert PlantGrowthSnapshot.from_dict(snap.to_dict()).to_dict()==snap.to_dict()


def test_stalked_treatment_has_same_colony_and_real_nonzero_offset():
    profile=recipe();profile["attachment"]="short_eccentric_to_lateral_stipe"
    profile["visual_calibration"].update(stipe_length_m=.025,stipe_diameter_m=.01)
    sessile,stalked=grown(),grown(profile=profile)
    assert sessile.blueprint.fingerprint()!=stalked.blueprint.fingerprint()
    for a,b in zip(sessile.render_snapshot.stats["fungal_bodies"],stalked.render_snapshot.stats["fungal_bodies"]):
        assert a["socket_m"]==b["socket_m"]
        assert a["cap_width_m"]==b["cap_width_m"]
        assert math.dist(b["socket_m"],b["cap_socket_m"])==pytest.approx(.025,abs=.00005)
    assert sessile.get_ecological_outcome()==stalked.get_ecological_outcome()
    assert grown(130).render_snapshot.stats["estimated_fruiting_body_count"]==0
    assert grown(130).render_snapshot.stats["colonised_wood_volume_proxy_m3"]>0
    assert grown(210).render_snapshot.stats["estimated_fruiting_body_count"]==6


def test_live_sessile_recipe_preserves_identity_and_has_no_vascular_modules():
    world=WorldModel();entity=world.resolved_species_entity("spec_trametes_gibbosa")
    assert entity["parents"]==["cladis_trametes"]
    assert entity["binomial_name"]=="Trametes gibbosa"
    sim=SpeciesSimulation(world_model=world,species_id=entity["id"],seed=303)
    sim.set_lod(2);sim.set_age(90)
    assert sim.render_snapshot.stats["estimated_fruiting_body_count"]==6
    assert {"mycelium","fruiting_body","fruiting_cap"} <= {m.id for m in sim.blueprint.modules}
    assert {m.kind for m in sim.blueprint.modules} == {"mycelium","fruiting_body","fruiting_cap"}
    assert sim.get_ecological_outcome()["photosynthesis_proxy"]==0
    assert PlantBlueprint.from_dict(sim.blueprint.to_dict()).fingerprint()==sim.blueprint.fingerprint()
    assert grown(environment={"fungal_substrates":[]}).render_snapshot.stats["estimated_fruiting_body_count"]==0
    assert grown(environment={"fungal_substrates":[{**wood_test_fixture()['fungal_substrates'][0],"material":"dead_conifer"}]}).render_snapshot.stats["estimated_fruiting_body_count"]==0
    assert grown(environment={**wood_test_fixture(),"fungal_moisture":0}).render_snapshot.stats["estimated_fruiting_body_count"]==0


def test_saved_artwork_reopens_with_exact_manifest_pixels():
    import pygame
    from tools.author_plant_assets import load_manifest, render_module, canvas_size, PixelEditorHost, PixelArtEditorUI
    pygame.init();pygame.display.set_mode((1,1))
    try:
        world=WorldModel();manifest=load_manifest(Path("assets/plant_asset_specs/spec_trametes_gibbosa.json").resolve())
        editor=PixelArtEditorUI(PixelEditorHost(world.loader))
        for module in manifest["modules"]:
            illustration=world.loader.get(module["illustration_id"])
            assert illustration["parents"]==["spec_trametes_gibbosa"]
            assert editor.open(illustration["id"])
            assert editor.begin_canvas()
            assert render_module(module).get_size()==canvas_size(.12)==(75,75)
            actual=pygame.image.load(illustration["media_path"])
            assert pygame.image.tobytes(actual,"RGBA")==pygame.image.tobytes(render_module(module),"RGBA")
    finally:
        pygame.quit()


def test_sessile_renderer_has_no_phantom_stalk_and_supports_all_fungal_views(monkeypatch):
    import pygame
    from types import SimpleNamespace
    from simulations.species.species_renderer import SpeciesRenderer, DiagnosticCamera, diagnostic_cell_bounds
    pygame.init();pygame.display.set_mode((1,1))
    try:
        world=WorldModel();sim=SpeciesSimulation(world_model=world,species_id="spec_trametes_gibbosa",seed=303)
        sim.set_lod(2);sim.set_age(90)
        renderer=SpeciesRenderer(SimpleNamespace(camera=DiagnosticCamera(600,600,diagnostic_cell_bounds(sim.render_snapshot))))
        calls=[]
        original=pygame.draw.line
        def record(surface,color,*args,**kwargs):
            calls.append(color)
            return original(surface,color,*args,**kwargs)
        monkeypatch.setattr(pygame.draw,"line",record)
        surface=pygame.Surface((600,600),pygame.SRCALPHA)
        renderer._draw_individual(surface,sim,camera=renderer.app_view.camera,draw_environment=False,cache=False)
        assert (69,53,38) not in calls and (217,208,176) not in calls
        for tab in ("individual","top_down","mycelium","editor","gallery"):
            assert sim.set_active_simulation_panel_tab(tab)
            renderer.draw(pygame.Surface((1500,950)),sim)
        assert not sim.set_active_simulation_panel_tab("roots")
        assert not sim.set_active_simulation_panel_tab("forest")
    finally:
        pygame.quit()


def test_fungal_card_launch_requires_valid_recipe_and_verified_ancestry():
    from app.launch_affordance_resolver import LaunchAffordanceResolver
    world=WorldModel();resolver=LaunchAffordanceResolver()
    entity=world.loader.get("spec_trametes_gibbosa")
    def modes(row):
        return [o["mode"] for o in resolver.options_for_entity(row,world_model=world)]
    assert modes(entity)==["species","phylogeny"]
    assert modes(world.loader.get("spec_cerioporus_squamosus"))==["species","phylogeny"]
    assert modes({**entity,"fungal_growth_profile":None})==["phylogeny"]
    assert modes({**entity,"fungal_growth_profile":{"body_form":"tree"}})==["phylogeny"]
    assert modes({**entity,"id":"spec_synthetic_nonfungus"})==["phylogeny"]
    assert [o["mode"] for o in resolver.options_for_entity(entity)]==["phylogeny"]
