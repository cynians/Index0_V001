"""Tree primary-axis controls without species keys or silent editor defaults."""
import math

import pytest

from simulations.species.plant_assets import PlantBlueprint, PlantGrowthSnapshot
from simulations.species.species_editor import new_editor_state, preview_entity, editable_field_rows
from simulations.species.species_simulation import SpeciesSimulation


FIELDS = ("plant_primary_branch_density", "plant_primary_branch_length")


def entity(**values):
    return {"id":"spec_unrelated_primary_axis_fixture", "plant_growth_form":"tree",
            "plant_growth_behaviour":"branched_woody", "plant_woodiness":"woody",
            "plant_leaf_distribution":"along_shoot", "leaf_arrangement":"alternate",
            "plant_crown_shape":"ovoid", "plant_branching_rhythm":"diffuse",
            "mature_height":{"max_m":5.}, **values}


def simulate(e, lod=2, fraction=.2):
    sim = SpeciesSimulation(species_entity=e,seed=303)
    sim.set_lod(lod);sim.set_age(sim.mature_age_days*fraction)
    return sim


def primaries(sim):
    return [p for p in sim.render_snapshot.placements if p[0]=="branch_section" and p[7]==2]


@pytest.mark.parametrize("field",FIELDS)
@pytest.mark.parametrize("value",[None,{},True,"other_unknown",math.nan,math.inf,-.1,1.1,
                                 {"min":.5,"typical":.2,"max":.8}])
def test_absent_and_invalid_values_are_exactly_neutral(field,value):
    base=simulate(entity());bad=simulate(entity(**{field:value}))
    assert base.blueprint.fingerprint()==bad.blueprint.fingerprint()
    assert base.render_snapshot.to_dict()==bad.render_snapshot.to_dict()


def test_density_fills_young_crown_and_zero_preserves_geometry():
    cases=[simulate(entity(plant_primary_branch_density=v)) for v in [0,.5,1]]
    counts=[len(primaries(s))//4 for s in cases]
    assert counts==[3,6,9]
    assert cases[0].render_snapshot.placements==simulate(entity()).render_snapshot.placements
    assert cases[2].render_snapshot.stats["leaf_area_m2"]>cases[0].render_snapshot.stats["leaf_area_m2"]
    assert len(primaries(simulate(entity(plant_primary_branch_density=1),fraction=1)))//4<=48


def test_length_changes_reach_without_changing_topology():
    cases=[simulate(entity(plant_primary_branch_length=v)) for v in [0,.095,.25,.8]]
    reaches=[sum(math.hypot(p[2],p[3]) for p in primaries(s)) for s in cases]
    assert reaches==sorted(reaches)
    assert len({len(s.render_snapshot.placements) for s in cases})==1
    assert len({s.render_snapshot.stats["estimated_leaf_count"] for s in cases})==1
    assert cases[2].render_snapshot.placements==simulate(entity()).render_snapshot.placements


def test_portable_deterministic_lod_and_bounded_outputs():
    e=entity(plant_primary_branch_density=.5,plant_primary_branch_length=.095)
    cases=[simulate(e,lod,fraction=1) for lod in [0,1,2]]
    assert len({s.render_snapshot.stats["leaf_area_m2"] for s in cases})==1
    assert len({s.render_snapshot.stats["estimated_leaf_count"] for s in cases})==1
    assert [s.get_ecological_outcome({}) for s in cases]==[cases[0].get_ecological_outcome({})]*3
    snap=cases[-1].render_snapshot.to_dict()
    assert snap==simulate(e,fraction=1).render_snapshot.to_dict()
    assert PlantGrowthSnapshot.from_dict(snap).to_dict()==snap
    blueprint=cases[-1].blueprint
    assert PlantBlueprint.from_dict(blueprint.to_dict()).fingerprint()==blueprint.fingerprint()
    for i,p in enumerate(cases[-1].render_snapshot.placements):
        assert p[1]<i
        assert all(math.isfinite(x) for x in p[2:7])
        assert max(abs(x) for x in p[2:5])<20


def test_editor_ranges_missing_neutrality_and_tree_gating():
    absent=preview_entity(new_editor_state(entity()))
    assert all(field not in absent for field in FIELDS)
    working=entity(**{f:{"min":.1,"typical":.3,"max":.6} for f in FIELDS})
    for mode,value in [('minimum',.1),('typical',.3),('maximum',.6)]:
        result=preview_entity(new_editor_state(working),mode)
        assert all(result[f]['typical']==value for f in FIELDS)
    other=entity(plant_growth_form='shrub',plant_primary_branch_density=.5,plant_primary_branch_length=.1)
    assert all(row['field'] not in FIELDS for row in editable_field_rows(other))
    assert not any(k in PlantBlueprint.from_species_entity(other).growth for k in ['primary_branch_density','primary_branch_length'])
    unsupported = entity(plant_primary_branch_density=.5,plant_primary_branch_length=.1)
    unsupported.pop('plant_leaf_distribution')
    assert not any(k in PlantBlueprint.from_species_entity(unsupported).growth for k in ['primary_branch_density','primary_branch_length'])


@pytest.mark.parametrize("ppm",[20,40,60])
def test_subpixel_panicle_retains_yellow_coverage_at_metric_size(ppm):
    import pygame
    from types import SimpleNamespace
    from simulations.species.species_renderer import SpeciesRenderer
    pygame.init()
    sim=SpeciesSimulation(species_entity={"id":"spec_unrelated_panicle_asset_fixture",
        "plant_reproductive_structure":"panicle",
        "plant_flower_module_ref":"assets/plants/illustrations/illust_acacia_dealbata_flower_panicle_module_pixel.png",
        "plant_module_anchors":{"flower":{"attachment_point":[.5,.946],"growth_axis":[0,-1],"depicted_size_m":.1}}})
    renderer=SpeciesRenderer(SimpleNamespace(camera=None))
    screen=pygame.Surface((96,96),pygame.SRCALPHA)
    camera=SimpleNamespace(world_to_screen=lambda p:(p[0]*ppm,p[1]*ppm))
    assert renderer._draw_module_asset(screen,sim,camera,"flower",(48,48),0,1)
    colored=[screen.get_at((x,y)) for y in range(96) for x in range(96) if screen.get_at((x,y)).a]
    assert colored and max(c.r for c in colored)>180
    assert any(c.g>140 and c.b<c.g*.6 for c in colored)
    assert screen.get_bounding_rect().height<=round(.1*ppm)+2
    pygame.quit()
