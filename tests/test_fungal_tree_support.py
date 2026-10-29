"""Fungal attachment uses the host's actual curved, metric trunk sections."""
import json
import math
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pygame
import pytest

from simulations.species.fungal_tree_support import wood_from_tree_snapshot
from simulations.species.fungal_growth import normalise_wood, wood_axis_sample
from simulations.species.plant_assets import PlantGrowthSnapshot
from simulations.species.species_simulation import SpeciesSimulation
from simulations.species.species_renderer import SpeciesRenderer, DiagnosticCamera
from tools.render_fungal_tree import build_scene
from world.world_model import WorldModel

ROOT=Path(__file__).resolve().parents[1]


def tree_fixture():
    blueprint=SimpleNamespace(growth={"shape":"tree","shoot_distribution_grammar":1})
    snapshot=PlantGrowthSnapshot("synthetic_curved_tree","host_fingerprint",303,90,2,{},
        [["root",-1,0,0,0,0,1,0], ["stem_section",0,.08,.12,1,0,.22,1],
         ["stem_section",1,.30,.20,2,0,.16,1], ["branch_section",1,2,.2,1.4,0,.04,2]],
        [-1,2,-1,1,0,2],placement_paths={"1":[[0,0,.5],[.08,.12,1]],
                                            "2":[[.2,.16,1.5],[.30,.20,2]]})
    return snapshot,blueprint


def fungus(wood,age=90,lod=2):
    recipe=json.loads((ROOT/"assets/species_trait_specs/spec_cerioporus_squamosus.json").read_text())["updates"]
    s=SpeciesSimulation(species_entity={"id":"synthetic_tree_fungus",**recipe},seed=303,
                        environment={"fungal_substrates":[wood] if wood else []})
    s.set_lod(lod);s.set_age(age);return s


def test_bridge_follows_actual_curves_radii_and_offset_without_mutating_host():
    snapshot,blueprint=tree_fixture();before=deepcopy(snapshot.to_dict())
    wood=wood_from_tree_snapshot(snapshot,blueprint,material="living_hardwood",interval_m=(.2,1.8))
    assert wood["source_trunk_placement_indices"]==[1,2]
    assert wood["axis_radii_m"][0]==.22
    assert wood["axis_radii_m"][-1]==.16
    assert wood["radius_m"]==.22
    assert wood["axis_points_m"][1]==[0,0,.5]
    assert wood["source_species_id"]==snapshot.species_id
    shifted=wood_from_tree_snapshot(snapshot,blueprint,material="living_hardwood",interval_m=(.2,1.8),position_m=(3,4,5))
    for a,b in zip(wood["axis_points_m"],shifted["axis_points_m"]):
        assert [y-x for x,y in zip(a,b)]==pytest.approx([3,4,5])
    assert snapshot.to_dict()==before


def test_forked_trunks_are_not_joined_by_height_sorting():
    snapshot,blueprint=tree_fixture()
    snapshot.placements.extend([["stem_section",0,2,0,.8,0,.18,1],
                                ["stem_section",4,3,0,1.5,0,.15,1]])
    wood=wood_from_tree_snapshot(snapshot,blueprint,material="living_hardwood",interval_m=(.1,1.9))
    assert wood["source_trunk_placement_indices"]==[1,2]
    assert max(p[0] for p in wood["axis_points_m"])<.4


def test_empty_or_invalid_host_window_stays_explicitly_empty():
    snapshot,blueprint=tree_fixture()
    assert wood_from_tree_snapshot(snapshot,blueprint,material="living_hardwood",interval_m=(3,4)) is None
    assert fungus(None).render_snapshot.stats["estimated_fruiting_body_count"]==0
    for interval in ((1,.5),(-1,1),(float("nan"),2)):
        with pytest.raises(ValueError):wood_from_tree_snapshot(snapshot,blueprint,material="living_hardwood",interval_m=interval)
    with pytest.raises(ValueError):wood_from_tree_snapshot(snapshot,SimpleNamespace(growth={"shape":"herb"}),material="living_hardwood")


def test_curved_normalisation_rejects_bad_axis_data():
    snapshot,blueprint=tree_fixture()
    wood=wood_from_tree_snapshot(snapshot,blueprint,material="living_hardwood")
    assert normalise_wood({"fungal_substrates":[wood]})[0]["axis_points_m"]==wood["axis_points_m"]
    for field,value in (("axis_points_m",[[0,0,0],[float("inf"),0,1]]),
                        ("axis_radii_m",[.1]),("axis_radii_m",[float("nan")]*len(wood["axis_radii_m"]))):
        invalid={**wood,field:value}
        assert normalise_wood({"fungal_substrates":[invalid]})==[]
        assert len(normalise_wood({"fungal_substrates":[invalid,wood]}))==1


def test_tree_sockets_touch_local_surface_and_keep_their_positions_as_caps_grow():
    snapshot,blueprint=tree_fixture()
    wood=wood_from_tree_snapshot(snapshot,blueprint,material="living_hardwood",interval_m=(.2,1.8))
    sims=[fungus(wood,90,lod) for lod in range(3)]
    for sim in sims:
        for body in sim.render_snapshot.stats["fungal_bodies"]:
            center,radius,axis,a,b=wood_axis_sample(sim.render_snapshot.stats["fungal_substrates"][0],body["substrate_axis_fraction"])
            displacement=[body["socket_m"][i]-center[i] for i in range(3)]
            assert math.sqrt(sum(v*v for v in displacement))==pytest.approx(radius,abs=.00015)
            assert sum(displacement[i]*axis[i] for i in range(3))==pytest.approx(0,abs=.00015)
            assert radius in {.22,.16}
        assert sim.get_ecological_outcome()==sims[0].get_ecological_outcome()
        assert sim.render_snapshot.bounds_m==sims[0].render_snapshot.bounds_m
    mature={b["id"]:b for b in sims[2].render_snapshot.stats["fungal_bodies"]}
    for b in fungus(wood,35).render_snapshot.stats["fungal_bodies"]:
        assert b["socket_m"]==mature[b["id"]]["socket_m"]


def test_real_saved_maple_scene_uses_large_metric_radii_and_leaves_host_unchanged():
    w=WorldModel();host,f,wood=build_scene(w,"spec_acer_rubrum","spec_cerioporus_squamosus")
    assert wood["source_species_id"]=="spec_acer_rubrum"
    assert wood["radius_m"]>.3
    assert len(set(wood["axis_radii_m"]))>1
    before=deepcopy(host.render_snapshot.to_dict());outcome=host.get_ecological_outcome()
    f.set_age(130);assert f.render_snapshot.stats["estimated_fruiting_body_count"]==0
    assert f.render_snapshot.stats["colonised_wood_volume_proxy_m3"]>0
    f.set_age(210);assert f.render_snapshot.stats["estimated_fruiting_body_count"]==5
    assert host.render_snapshot.to_dict()==before
    assert host.get_ecological_outcome()==outcome
    assert w.loader.get("spec_acer_rubrum").get("fungal_growth_profile") is None


def test_tree_renderer_preserves_metric_trunk_width_beyond_old_45_pixel_ceiling():
    pygame.init();pygame.display.set_mode((1,1))
    sim=SpeciesSimulation(species_entity={"id":"metric_tree_width","plant_growth_form":"tree",
        "plant_growth_behaviour":"branched_woody","plant_leaf_distribution":"along_shoot"})
    snapshot=PlantGrowthSnapshot(sim.species_id,sim.blueprint.fingerprint(),1,90,2,{},
        [["root",-1,0,0,0,0,1,0],["stem_section",0,0,0,1,0,.3,1]],[-.3,.3,0,0,0,1],stats={"maturity":1})
    renderer=SpeciesRenderer(SimpleNamespace(camera=None));camera=DiagnosticCamera(500,500,(-1,1,0,1.5))
    screen=pygame.Surface((500,500),pygame.SRCALPHA)
    renderer._draw_individual(screen,sim,camera=camera,snapshot=snapshot,clear=False,
                             visible_indices={1},cache=False,draw_ground_line=False,draw_environment=False)
    assert screen.get_bounding_rect().width==pytest.approx(.6*camera.scale,abs=2)
    assert screen.get_bounding_rect().width>100
    pygame.quit()


def test_fungal_cache_refreshes_when_support_or_cutaway_view_changes():
    pygame.init();pygame.display.set_mode((1,1));snapshot,blueprint=tree_fixture()
    wood=wood_from_tree_snapshot(snapshot,blueprint,material="living_hardwood")
    sim=fungus(wood);camera=DiagnosticCamera(500,500,(-1,1,0,2))
    renderer=SpeciesRenderer(SimpleNamespace(camera=None));screen=pygame.Surface((500,500))
    renderer._draw_individual(screen,sim,camera=camera)
    initial=pygame.image.tobytes(screen,"RGB")
    sim.diagnostic_view="mycelium";renderer._draw_individual(screen,sim,camera=camera)
    assert pygame.image.tobytes(screen,"RGB")!=initial
    sim.environment["fungal_moisture"]=0;sim.set_age(90);sim.diagnostic_view="individual"
    renderer._draw_individual(screen,sim,camera=camera)
    assert pygame.image.tobytes(screen,"RGB")!=initial
    pygame.quit()
