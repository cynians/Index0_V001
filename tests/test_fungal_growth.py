"""Wood colonies and fruiting bodies stay separate across views and LODs."""
import gzip
import json
import math
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pygame
import pytest

from simulations.species.fungal_growth import wood_test_fixture, normalise_wood
from simulations.species.plant_assets import PlantBlueprint, PlantGrowthSnapshot, is_fungal_growth_species_entity
from simulations.species.species_simulation import SpeciesSimulation
from simulations.species.species_renderer import SpeciesRenderer, DiagnosticCamera, TopDownDiagnosticCamera, diagnostic_cell_bounds
from simulations.species.species_editor import editable_field_rows, PREVIEW_AFFECTING_FIELDS
from tools.author_plant_assets import load_manifest, render_module, canvas_size, PixelEditorHost, PixelArtEditorUI, validate_manifest, ManifestError
from tools.author_plant_species import prepare_update, validate_updates, AuthoringError
from world.fungal_traits import validate_fungal_profile
from world.persistent_ontology_store import PersistentOntologyStore
from world.plant_catalogue import PlantCatalogue
from world.species_inheritance import is_inheritable_species_field
from world.world_model import WorldModel

ROOT=Path(__file__).resolve().parents[1]
SID="spec_cerioporus_squamosus"


def profile():
    return deepcopy(json.loads((ROOT/"assets/species_trait_specs/spec_cerioporus_squamosus.json").read_text())["updates"]["fungal_growth_profile"])


def grown(age=90,lod=2,env=None,recipe=None):
    s=SpeciesSimulation(species_entity={"id":"spec_synthetic_wood_fungus","fungal_growth_profile":recipe or profile()},seed=303,environment=env)
    s.set_lod(lod);s.set_age(age);return s


def test_live_taxonomy_transport_and_protected_authoring():
    w=WorldModel(); e=w.resolved_species_entity(SID)
    assert not PlantCatalogue.build(w.loader.entities).is_species(SID)
    assert is_fungal_growth_species_entity(e,w.loader.entities)
    assert not is_fungal_growth_species_entity({**e,"id":"fake_animal"},w.loader.entities)
    assert e["parents"]==["cladis_cerioporus"]
    s=SpeciesSimulation(world_model=w,species_id=SID)
    assert s.blueprint.growth["fungal_growth_profile"]["substrates"]==["dead_hardwood","living_hardwood"]
    assert s.blueprint.module("fruiting_body").length_m==.23
    assert s.blueprint.module("leaf") is None
    assert not is_inheritable_species_field("fungal_growth_profile")
    assert not is_inheritable_species_field("fungal_body_module_ref")
    data=PersistentOntologyStore(ROOT/"ontology/index0.owl").load_datasets()
    with pytest.raises(AuthoringError): prepare_update(data,"spec_nypa_fruticans",{"fungal_growth_profile":profile()})
    with pytest.raises(AuthoringError): validate_updates({"parents":["cladis_plants_plantae"]})


@pytest.mark.parametrize("change", [{"body_form":"tree"},{"substrates":["soil"]},{"feeding_modes":[{}]},
                                   {"visual_calibration":"unknown"},{"cap_width":{"min_m":.5,"max_m":.2}},
                                   {"simulation_calibration":{"colony_model_days":float("nan")}}])
def test_invalid_recipe_rejected_before_authoring(change):
    p=profile();p.update(change)
    with pytest.raises(ValueError): validate_fungal_profile(p)
    with pytest.raises(AuthoringError):validate_updates({"fungal_growth_profile":p})


def test_determinism_portability_and_internal_mycelium():
    a,b=grown(),grown(); snap=a.render_snapshot
    assert snap.to_dict()==b.render_snapshot.to_dict()
    assert PlantBlueprint.from_dict(a.blueprint.to_dict()).fingerprint()==a.blueprint.fingerprint()
    assert PlantGrowthSnapshot.from_dict(snap.to_dict()).to_dict()==snap.to_dict()
    assert {p[0] for p in snap.placements}=={"mycelium","fruiting_body"}
    for i,p in enumerate(snap.placements):
        assert p[1]==-1 or 0<=p[1]<i
        assert all(math.isfinite(v) for v in p[2:7])
        if p[0]=="mycelium":
            assert math.hypot(p[2],p[3])<.16
            assert 0<=p[4]<=1.2
    for body in snap.stats["fungal_bodies"]:
        assert math.hypot(*body["socket_m"][:2])==pytest.approx(.16,abs=.0001)
        assert math.dist(body["socket_m"],body["cap_socket_m"])==pytest.approx(.035,abs=.0001)
    assert all(a["socket"]=="wood_surface" for a in snap.attachment_points)


@pytest.mark.parametrize("age", [15,35,60,90,108,130,210])
def test_lod_preserves_colony_bodies_sporulation_and_ecology(age):
    sims=[grown(age,lod) for lod in range(3)];snaps=[s.render_snapshot for s in sims]
    for key in ("colonised_wood_volume_proxy_m3","estimated_fruiting_body_count","canonical_mycelium_node_count","sporulating_area_proxy_m2"):
        assert len({s.stats[key] for s in snaps})==1
    assert all(s.bounds_m==snaps[0].bounds_m for s in snaps)
    assert all(s.get_ecological_outcome()==sims[0].get_ecological_outcome() for s in sims)
    canonical={b["id"]:(b["socket_m"],b["cap_width_m"]) for b in snaps[2].stats["fungal_bodies"]}
    assert all((b["socket_m"],b["cap_width_m"])==canonical[b["id"]] for b in snaps[0].stats["fungal_bodies"])


def test_colony_persists_after_fruit_bodies_disappear_and_recur():
    mature,between,next_flush=grown(90),grown(130),grown(210)
    assert mature.render_snapshot.stats["estimated_fruiting_body_count"]==5
    assert between.render_snapshot.stats["estimated_fruiting_body_count"]==0
    assert between.render_snapshot.stats["colonised_wood_volume_proxy_m3"]==mature.render_snapshot.stats["colonised_wood_volume_proxy_m3"]
    assert any(p[0]=="mycelium" for p in between.render_snapshot.placements)
    assert next_flush.render_snapshot.stats["estimated_fruiting_body_count"]==5
    assert next_flush.life_state()["flush_index"]==1
    assert between.get_ecological_outcome()["vitality"]>0
    assert between.get_ecological_outcome()["fecundity"]==0
    assert mature.get_ecological_outcome()["fecundity"]>0


def test_individual_brackets_keep_fixed_sockets_while_new_bodies_emerge():
    early=grown(35).render_snapshot.stats["fungal_bodies"]
    mature={b["id"]:b for b in grown(90).render_snapshot.stats["fungal_bodies"]}
    for b in early:
        assert b["socket_m"]==mature[b["id"]]["socket_m"]
        assert b["cap_width_m"]<mature[b["id"]]["cap_width_m"]


def test_detail_cache_changes_with_runtime_substrate_context():
    s=grown(); first=s.get_detailed_snapshot()
    s.environment["fungal_substrates"]=[]
    assert s.get_detailed_snapshot().placements==[]
    assert first.placements


def test_empty_incompatible_and_exhausted_wood_and_zero_moisture():
    assert grown(env={"fungal_substrates":[]}).render_snapshot.placements==[]
    for material,remaining in (("stone",1),("dead_conifer",1),("dead_hardwood",0)):
        env=wood_test_fixture();env["fungal_substrates"][0].update(material=material,wood_remaining_fraction=remaining)
        s=grown(env=env)
        assert s.get_ecological_outcome()["vitality"]==0
        assert s.render_snapshot.stats["estimated_fruiting_body_count"]==0
    dry=grown(env={**wood_test_fixture(),"fungal_moisture":0})
    assert dry.render_snapshot.stats["estimated_fruiting_body_count"]==0
    assert dry.render_snapshot.stats["colonised_wood_volume_proxy_m3"]>0
    assert grown().get_ecological_outcome({"fungal_substrates":[]})["estimated_fruiting_body_count"]==0
    assert grown().get_ecological_outcome()["photosynthesis_proxy"]==0


def test_size_and_substrate_composition_reuse_with_bounded_inputs():
    p=profile();p["substrates"]=["dead_conifer"];p["cap_width"]={"min_m":.025,"max_m":.05}
    p["visual_calibration"].update(cap_width_m=.05,body_count=10000)
    env=wood_test_fixture("log");env["fungal_substrates"][0]["material"]="dead_conifer"
    s=grown(env=env,recipe=p)
    assert s.render_snapshot.stats["estimated_fruiting_body_count"]==24
    assert max(b["cap_width_m"] for b in s.render_snapshot.stats["fungal_bodies"])<=.05
    assert s.blueprint.fingerprint()!=grown().blueprint.fingerprint()
    assert len(s.render_snapshot.placements)<=57
    bad={"fungal_substrates":[{"start_m":[float("nan"),0,0],"end_m":[0,0,1],"radius_m":.1}]}
    assert normalise_wood(bad)==[]


def test_pixel_assets_reopen_and_are_display_only():
    pygame.init();pygame.display.set_mode((1,1));w=WorldModel()
    manifest=load_manifest(ROOT/"assets/plant_asset_specs/spec_cerioporus_squamosus.json")
    for m in manifest["modules"]:
        illustration=w.loader.get(m["illustration_id"])
        with gzip.open(ROOT/illustration["pixel_document_path"],"rt",encoding="utf-8") as f:doc=json.load(f)
        assert doc["version"]==2
        editor=PixelArtEditorUI(PixelEditorHost(w.loader))
        assert editor.open(illustration["id"]);assert editor.begin_canvas()
        assert render_module(m).get_size()==canvas_size(.23)==(75,75)
        expected=render_module(m);actual=pygame.image.load(ROOT/illustration["media_path"])
        assert pygame.image.tobytes(expected,"RGBA")==pygame.image.tobytes(actual,"RGBA")
    e=w.resolved_species_entity(SID);with_assets=SpeciesSimulation(species_entity=e,seed=303);with_assets.set_age(90)
    e.pop("fungal_body_module_ref");e.pop("fungal_cap_module_ref")
    without=SpeciesSimulation(species_entity=e,seed=303);without.set_age(90)
    assert with_assets.render_snapshot.stats==without.render_snapshot.stats
    assert with_assets.get_ecological_outcome()==without.get_ecological_outcome()
    pygame.quit()


def test_real_renderer_views_editor_and_fungal_only_navigation():
    pygame.init();pygame.display.set_mode((1,1));w=WorldModel()
    s=SpeciesSimulation(world_model=w,species_id=SID,seed=303);s.set_age(90)
    renderer=SpeciesRenderer(SimpleNamespace(camera=DiagnosticCamera(600,600,diagnostic_cell_bounds(s.render_snapshot))))
    for mode in ("individual","mycelium","top_down","editor","gallery"):
        assert s.set_active_simulation_panel_tab(mode)
        surface=pygame.Surface((1500,950));renderer.draw(surface,s)
        assert pygame.mask.from_surface(surface).count()>0
    assert not s.set_active_simulation_panel_tab("roots")
    assert not s.set_active_simulation_panel_tab("forest")
    assert "fungal_growth_profile" in PREVIEW_AFFECTING_FIELDS
    assert [r["field"] for r in editable_field_rows(s.species_entity)]==["fungal_growth_profile"]
    pygame.quit()


def test_card_eligibility_and_saved_pixel_anchor_handoff():
    from ui.card import EntityCard
    from ui.knowledge_browser_ui import KnowledgeBrowserUI
    w=WorldModel();card=EntityCard.__new__(EntityCard);card.entity=w.loader.get(SID)
    card.dataset_name="species";card.world_model=w
    tools={t["id"] for t in card._toolbelt_items()}
    assert {"species_visual_editor","species_sim_lab"}<=tools
    assert "plant_asset_root" not in tools
    parent=deepcopy(card.entity); saved=[]
    browser=KnowledgeBrowserUI.__new__(KnowledgeBrowserUI)
    browser.world_model=SimpleNamespace();browser.cards=[]
    browser._parent_entity_for_illustration=lambda _:parent
    browser._persist_entity_to_repository=lambda e:saved.append(deepcopy(e))
    browser._build_browser_items=lambda _:[]
    browser._relayout_cards=lambda:None
    illustration={"plant_asset_target_field":"fungal_body_module_ref","media_path":"assets/fixture.png",
                  "depicted_size_m":.2,"pixel_module_anchor":{"attachment_point":[.3,.6],"growth_axis":[0,-1]}}
    assert browser.assign_plant_asset_to_parent(illustration)
    assert saved[0]["fungal_body_module_ref"]=="assets/fixture.png"
    assert saved[0]["fungal_module_anchors"]["fruiting_body"]["attachment_point"]==[.3,.6]
    assert saved[0]["fungal_module_anchors"]["fruiting_body"]["depicted_size_m"]==.2
    assert "plant_module_anchors" not in saved[0]
