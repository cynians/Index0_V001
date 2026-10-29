"""Collective tree bloom preserves anatomy/physics while resolving colour."""
import math
from types import SimpleNamespace

import pygame
import pytest

from simulations.species.bloom_cohorts import bloom_samples, bloom_surface
from simulations.species.plant_assets import PlantBlueprint, PlantGrowthSnapshot
from simulations.species.species_editor import editable_field_rows, new_editor_state, preview_entity
from simulations.species.species_renderer import SpeciesRenderer, DiagnosticCamera, diagnostic_cell_bounds
from simulations.species.species_simulation import SpeciesSimulation


def entity(**updates):
    return {"id":"spec_unrelated_native_bloom_tree", "plant_growth_form":"tree",
            "plant_growth_behaviour":"branched_woody", "plant_lifespan":"perennial",
            "plant_leaf_distribution":"along_shoot", "leaf_arrangement":"alternate",
            "leaf_structure":"pinnately_compound", "plant_flowering_position":"lateral",
            "plant_reproductive_structure":"panicle", "reproductive_mode":"both",
            "mature_height":{"max_m":5}, "leaf_length":{"typical_m":.09},
            "plant_flower_module_ref":"assets/plants/illustrations/illust_acacia_dealbata_flower_panicle_module_pixel.png",
            "plant_module_anchors":{"flower":{"attachment_point":[.5,.946],"growth_axis":[0,-1],"depicted_size_m":.1}}, **updates}


def simulate(e, age=150, lod=2):
    s=SpeciesSimulation(species_entity=e,seed=303)
    s.set_age(age);s.set_lod(lod)
    return s


@pytest.fixture(autouse=True)
def graphics():
    pygame.init()
    yield
    pygame.quit()


@pytest.mark.parametrize("value",[None,{},True,"other_unknown",math.nan,math.inf,-.1,1.1,
                                 {"min":.8,"typical":.3,"max":.9}])
def test_missing_invalid_density_is_exactly_neutral(value):
    a,b=simulate(entity()),simulate(entity(plant_bloom_density=value))
    assert a.blueprint.fingerprint()==b.blueprint.fingerprint()
    assert a.render_snapshot.to_dict()==b.render_snapshot.to_dict()


def test_density_preserves_canonical_anatomy_leaf_area_and_ecology():
    base=simulate(entity())
    for value in [0,.4,.85,1]:
        s=simulate(entity(plant_bloom_density=value))
        assert s.render_snapshot.placements==base.render_snapshot.placements
        assert s.render_snapshot.placement_paths==base.render_snapshot.placement_paths
        assert s.render_snapshot.stats['leaf_area_m2']==base.render_snapshot.stats['leaf_area_m2']
        assert s.get_ecological_outcome({})==base.get_ecological_outcome({})
    zero=simulate(entity(plant_bloom_density=0))
    assert zero.render_snapshot.leaf_clusters==base.render_snapshot.leaf_clusters


def test_samples_are_deterministic_bounded_and_respond_to_density():
    s=simulate(entity(plant_bloom_density=.85))
    c=next(c for c in s.render_snapshot.leaf_clusters if 'bloom_axis_m' in c)
    counts=[len(bloom_samples(c,v,.09,1)) for v in [0,.2,.85,1]]
    assert counts==sorted(counts) and counts[0]==0
    a=bloom_samples(c,.85,.09,1)
    assert a==bloom_samples(c,.85,.09,1) and len(a)<=128
    assert bloom_samples(c,.85,.09,0)==[]
    assert all(all(math.isfinite(n) for n in pos+forward) for pos,forward in a)
    assert all(math.dist(pos,c['bloom_axis_m'][0])<2 for pos,_ in a)
    assert PlantGrowthSnapshot.from_dict(s.render_snapshot.to_dict()).to_dict()==s.render_snapshot.to_dict()
    assert PlantBlueprint.from_dict(s.blueprint.to_dict()).fingerprint()==s.blueprint.fingerprint()


def render(s, camera, renderer):
    panel=pygame.Surface((500,500));renderer._draw_individual(panel,s,camera=camera,show_height_reference=False)
    return panel


def warm_pixels(panel):
    return sum(1 for y in range(panel.get_height()) for x in range(panel.get_width())
               if (lambda c:c.g>110 and c.r>c.g*.95 and c.b<c.g*.7)(panel.get_at((x,y))))


def test_collective_bloom_bypasses_accent_thinning_and_is_visible():
    a,b=simulate(entity()),simulate(entity(plant_bloom_density=.85))
    r=SpeciesRenderer(SimpleNamespace(camera=None));camera=DiagnosticCamera(500,500,diagnostic_cell_bounds(a.render_snapshot))
    old,new=render(a,camera,r),render(b,camera,r)
    assert warm_pixels(new)>max(100,warm_pixels(old)*5)
    count=r._draw_bloom_cohorts(pygame.Surface((500,500)),b,camera,b.render_snapshot)
    assert count>len([p for p in b.render_snapshot.placements if p[0]=='flower'])*10
    before=b.render_snapshot.to_dict()
    render(b,camera,r)
    assert before==b.render_snapshot.to_dict()
    for age in [75,11]:
        off=simulate(entity(plant_bloom_density=.85),age)
        assert r._draw_bloom_cohorts(pygame.Surface((500,500)),off,camera,off.render_snapshot)==0
    vegetative=simulate(entity(plant_bloom_density=.85,reproductive_mode='vegetative'))
    assert r._draw_bloom_cohorts(pygame.Surface((500,500)),vegetative,camera,vegetative.render_snapshot)==0
    assert r._draw_bloom_cohorts(pygame.Surface((500,500)),b,camera,b.render_snapshot,set())==0


def test_lod_retains_ecology_and_display_cohort_counts():
    cases=[simulate(entity(plant_bloom_density=.85),lod=i) for i in [0,1,2]]
    assert [s.get_ecological_outcome({}) for s in cases]==[cases[0].get_ecological_outcome({})]*3
    totals=[sum(len(bloom_samples(c,.85,.09,1)) for c in s.render_snapshot.leaf_clusters) for s in cases]
    assert totals[0]==totals[1]==totals[2]


def test_editor_validity_and_native_unit_support():
    assert 'plant_bloom_density' not in preview_entity(new_editor_state(entity()))
    working=entity(plant_bloom_density={'min':.4,'typical':.8,'max':1})
    for mode,value in [('minimum',.4),('typical',.8),('maximum',1)]:
        assert preview_entity(new_editor_state(working),mode)['plant_bloom_density']['typical']==value
    for change in [{'plant_growth_form':'shrub'}, {'plant_flower_module_ref':None},
                   {'plant_reproductive_structure':'cone'}, {'plant_inflorescence_profile':{'form':'panicle'}}]:
        unsupported=entity(plant_bloom_density=.85,**change)
        assert 'bloom_density' not in PlantBlueprint.from_species_entity(unsupported).growth
        assert 'plant_bloom_density' not in {row['field'] for row in editable_field_rows(unsupported)}


def test_surface_bounds_and_extreme_zoom_fallback():
    unit=pygame.Surface((20,40),pygame.SRCALPHA);pygame.draw.circle(unit,(240,220,30),(10,10),7)
    tile=bloom_surface(unit,(.5,.95),[(0,0,0),(10,10,20)],2)
    assert tile and max(tile[0].get_size())<50
    assert bloom_surface(unit,(.5,.95),[(0,0,0),(2000,0,0)],2) is None
    assert bloom_surface(unit,(.5,.95),[(0,0,0)],1000) is None
