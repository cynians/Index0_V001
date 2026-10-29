"""Authored opening angles follow the host twig without moving the socket."""
import json
import math
from pathlib import Path

import pytest

from simulations.species.leaf_development import (
    authored_leaf_attachment_angle, leaf_attachment_direction, leaf_host_tangent,
)
from simulations.species.plant_assets import PlantBlueprint, PlantGrowthSnapshot
from simulations.species.species_editor import editable_field_rows, new_editor_state, preview_entity
from simulations.species.species_simulation import SpeciesSimulation


def entity(**updates):
    data = {"id":"spec_synthetic_leaf_angle", "parents":[],
            "plant_growth_form":"forb", "plant_woodiness":"herbaceous",
            "plant_growth_behaviour":"iterative_indeterminate",
            "plant_reproductive_structure":"compound_umbel", "leaf_attachment_pattern":"along_stem",
            "leaf_arrangement":"alternate", "mature_height":{"typical_m":.7,"max_m":1.1}}
    return {**data,**updates}


def simulation(data, lod=2):
    sim = SpeciesSimulation(species_entity=data, seed=303)
    sim.set_lod(lod); sim.set_age(sim.mature_age_days*1.2)
    return sim


@pytest.mark.parametrize("value", [None, {}, "other_unknown", True, float("nan"), float("inf"),
                                  -.1, 1.1, {"typical":float("nan")}, {"status":"visual_fit"}])
def test_missing_invalid_unknown_is_exactly_neutral(value):
    a,b = simulation(entity()), simulation(entity(plant_leaf_attachment_angle=value))
    assert authored_leaf_attachment_angle(value) is None
    assert a.blueprint.fingerprint() == b.blueprint.fingerprint()
    assert a.render_snapshot.to_dict() == b.render_snapshot.to_dict()
    assert a.get_ecological_outcome({}) == b.get_ecological_outcome({})


@pytest.mark.parametrize("angle", [0., .15, .3, .5, .8, 1.])
def test_angle_is_from_local_host_tangent_including_zero(angle):
    for host in ((0.,0.,1.),(.7,.2,.5),(-.4,.6,.9)):
        norm = math.sqrt(sum(v*v for v in host)); host_unit = [v/norm for v in host]
        forward = leaf_attachment_direction([.8,-.3,.2],host,angle,0)
        assert math.sqrt(sum(v*v for v in forward)) == pytest.approx(1,abs=1e-6)
        dot = sum(a*b for a,b in zip(forward,host_unit))
        measured = math.degrees(math.acos(max(-1,min(1,dot))))
        assert measured == pytest.approx(angle*180,abs=.1)


def test_nearest_curved_host_piece_and_parallel_radial_fallback():
    assert leaf_host_tangent((0,0,0),[(0,0,.2),(.2,0,.4)],(.12,0,.32)) == pytest.approx([.2,0,.2])
    forward = leaf_attachment_direction([0,0,1],[0,0,1],.5)
    assert forward == [1.,0.,0.]
    assert leaf_attachment_direction([0,0,1],[0,0,0],0) == [0.,0.,1.]


def test_pose_changes_only_directions_not_topology_sockets_or_ecology():
    a,b = simulation(entity()), simulation(entity(plant_leaf_attachment_angle={"min":.2,"typical":.3,"max":.4}))
    assert a.blueprint.fingerprint() != b.blueprint.fingerprint()
    assert a.render_snapshot.placements == b.render_snapshot.placements
    assert a.render_snapshot.attachment_points == b.render_snapshot.attachment_points
    assert a.render_snapshot.placement_paths == b.render_snapshot.placement_paths
    assert a.render_snapshot.leaf_clusters == b.render_snapshot.leaf_clusters
    assert a.get_ecological_outcome({}) == b.get_ecological_outcome({})
    assert a.render_snapshot.placement_orientations != b.render_snapshot.placement_orientations
    for index,p in enumerate(b.render_snapshot.placements):
        if p[0] != "leaf":
            assert a.render_snapshot.placement_orientations[str(index)] == b.render_snapshot.placement_orientations[str(index)]
        else:
            origin = b.render_snapshot.placements[p[1]]
            host_start = b.render_snapshot.placements[origin[1]][2:5]
            tangent = leaf_host_tangent(host_start,b.render_snapshot.placement_paths.get(str(p[1]),[origin[2:5]]),p[2:5])
            norm = math.sqrt(sum(v*v for v in tangent))
            forward = b.render_snapshot.placement_orientations[str(index)]["forward"]
            measured = math.degrees(math.acos(max(-1,min(1,sum(a*v/norm for a,v in zip(forward,tangent))))))
            assert 46 <= measured <= 62


def test_deterministic_lod_ecology_and_portable_blueprint():
    e=entity(plant_leaf_attachment_angle={"min":.2,"typical":.3,"max":.4})
    sims=[simulation(e,lod) for lod in (0,1,2)]
    assert sims[-1].render_snapshot.to_dict() == simulation(e).render_snapshot.to_dict()
    assert PlantBlueprint.from_dict(sims[-1].blueprint.to_dict()).fingerprint() == sims[-1].blueprint.fingerprint()
    assert PlantGrowthSnapshot.from_dict(sims[-1].render_snapshot.to_dict()).to_dict() == sims[-1].render_snapshot.to_dict()
    for key in ("estimated_leaf_count","leaf_area_m2","root_depth_m","root_length_m"):
        assert len({s.render_snapshot.stats[key] for s in sims}) == 1
    assert all(s.get_ecological_outcome({}) == sims[0].get_ecological_outcome({}) for s in sims)
    for index,p in enumerate(sims[-1].render_snapshot.placements):
        assert p[1] == -1 or 0 <= p[1] < index
        assert all(math.isfinite(v) for v in p[2:7])


def test_editor_range_transport_and_missing_preview_keeps_legacy_pose():
    state = new_editor_state(entity())
    assert "plant_leaf_attachment_angle" not in preview_entity(state)
    row = next(r for r in editable_field_rows(entity()) if r["field"] == "plant_leaf_attachment_angle")
    assert row["kind"] == "range" and row["group"] == "Leaves" and row["affects_preview"]
    e=entity(plant_leaf_attachment_angle={"min":.2,"typical":.3,"max":.4,"status":"provisional_visual_fit"})
    angles=[]
    for mode in ("minimum","typical","maximum"):
        sim=simulation(preview_entity(new_editor_state(e),mode))
        angles.append(sim.blueprint.growth["leaf_attachment_angle"])
    assert angles == [.2,.3,.4]
    assert not any(r["field"]=="plant_leaf_attachment_angle" for r in editable_field_rows({"plant_growth_form":"tree"}))


def test_editor_angle_variation_does_not_resample_other_architecture_fields():
    before = entity(plant_branch_droop={"min":.2,"typical":.4,"max":.6})
    after = {**before,"plant_leaf_attachment_angle":{"min":.17,"typical":.22,"max":.28}}
    for sample_index in range(4):
        a=preview_entity(new_editor_state(before),"variation",sample_index)
        b=preview_entity(new_editor_state(after),"variation",sample_index)
        b.pop("plant_leaf_attachment_angle")
        assert a == b


def test_frozen_existing_plant_is_unchanged_without_authored_angle():
    baseline=json.loads((Path(__file__).resolve().parent / 'fixtures/species/torilis_leaf_angle_baseline.json').read_text())
    sim=SpeciesSimulation(species_entity=baseline['entity'],seed=303);sim.set_lod(2);sim.set_age(227.5)
    assert json.loads(json.dumps(sim.blueprint.to_dict())) == baseline['blueprint']
    assert json.loads(json.dumps(sim.render_snapshot.to_dict())) == baseline['snapshot']
    assert sim.get_ecological_outcome({}) == baseline['ecology']


@pytest.mark.parametrize("behaviour", ["suckering_clonal", "rhizomatous_clonal", "stoloniferous_clonal"])
def test_angle_reuses_the_same_helper_on_clonal_forb_shoots(behaviour):
    from tests.test_clonal_forb_shoots import entity as clonal_entity, simulation as clonal_simulation
    a=clonal_simulation(clonal_entity(plant_growth_behaviour=behaviour))
    b=clonal_simulation(clonal_entity(plant_growth_behaviour=behaviour,plant_leaf_attachment_angle={"typical":.22}))
    assert a.render_snapshot.placements == b.render_snapshot.placements
    assert a.render_snapshot.attachment_points == b.render_snapshot.attachment_points
    assert a.get_ecological_outcome({}) == b.get_ecological_outcome({})
    assert a.render_snapshot.placement_orientations != b.render_snapshot.placement_orientations


def test_live_authored_angle_reopens_with_preserved_identity_and_ecology():
    from world.world_model import WorldModel
    world=WorldModel();assert world.loader.plant_catalogue.is_species('spec_torilis_arvensis')
    e=world.resolved_species_entity('spec_torilis_arvensis')
    updates=json.loads((Path(__file__).resolve().parent / 'fixtures/species/torilis_leaf_angle_updates.json').read_text())['updates']
    assert e['plant_leaf_attachment_angle'] == updates['plant_leaf_attachment_angle']
    assert e['parents'] == ['cladis_hedge_parsleys_torilis']
    s=SpeciesSimulation(species_entity=e,seed=303);s.set_lod(2);s.set_age(227.5)
    assert s.blueprint.growth['leaf_attachment_angle'] == .22
    baseline=json.loads((Path(__file__).resolve().parent / 'fixtures/species/torilis_leaf_angle_baseline.json').read_text())
    assert json.loads(json.dumps(s.render_snapshot.placements)) == baseline['snapshot']['placements']
    assert s.get_ecological_outcome({}) == baseline['ecology']
