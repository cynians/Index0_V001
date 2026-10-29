"""Herbaceous crown topology, compound-leaf area and retained head sockets."""
import json
import math
from pathlib import Path
from types import SimpleNamespace

import pygame
import pytest
from simulations.species.basal_herbs import basal_herb_profile
from simulations.species.plant_assets import PlantBlueprint, PlantGrowthSnapshot
from simulations.species.species_simulation import SpeciesSimulation
from simulations.species.species_renderer import SpeciesRenderer
from simulations.species.plant_nutrition import resolve_plant_nutrient_response
from tools.author_plant_species import validate_updates, AuthoringError


def entity(**changes):
    m=json.loads(Path('assets/plant_asset_specs/spec_trifolium_pratense.json').read_text(encoding='utf-8'))
    return {'id':'spec_unrelated_crown_herb',**m['species_field_updates'],**changes}


def snapshot(data=None,day=180,lod=2):
    sim=SpeciesSimulation(species_entity=data or entity(),seed=303)
    sim.set_age(day);sim.set_lod(lod)
    return sim,sim.render_snapshot


@pytest.mark.parametrize('changes',[{'basal_shoot_count':0},{'basal_shoot_count':13},
    {'basal_shoot_count':True},{'nodes_per_shoot':5},{'nodes_per_shoot':37},
    {'leaf_width_m':.151},{'stem_radius_m':float('nan')},{'basal_radius_m':float('inf')},
    {'branching_start_fraction':-.1},{'crown_radius_ratio':1.}])
def test_invalid_crowns_are_neutral_and_authoring_rejects(changes):
    bad={**entity()['plant_shoot_profile'],**changes}
    assert basal_herb_profile(bad) is None
    with pytest.raises(AuthoringError):validate_updates({'plant_shoot_profile':bad})
    assert PlantBlueprint.from_species_entity(entity(plant_shoot_profile=bad)).fingerprint()==PlantBlueprint.from_species_entity(entity(plant_shoot_profile=None)).fingerprint()


def test_profile_body_plan_transport_and_fingerprint():
    a=PlantBlueprint.from_species_entity(entity())
    assert a.growth['basal_herb_profile']['basal_shoot_count']==5
    assert a.growth['leaflet_count']==3
    assert a.module('leaf').radius_m==.0275
    assert a.module('flower').length_m==.03 and a.module('fruit').length_m==.025
    assert PlantBlueprint.from_dict(a.to_dict()).fingerprint()==a.fingerprint()
    for change in ({'plant_woodiness':'woody'},{'plant_growth_form':'subshrub'},
                   {'plant_growth_behaviour':'stoloniferous_clonal'},{'plant_leaf_distribution':'terminal_cluster'}):
        assert 'basal_herb_profile' not in PlantBlueprint.from_species_entity(entity(**change)).growth
    for key,value in [('basal_shoot_count',2),('nodes_per_shoot',16),('crown_radius_ratio',.6)]:
        assert a.fingerprint()!=PlantBlueprint.from_species_entity(entity(plant_shoot_profile={**entity()['plant_shoot_profile'],key:value})).fingerprint()


def axes(s):
    return [(p[0],p[2:7],s.placements[p[1]][2:5],s.placement_paths.get(str(i)))
            for i,p in enumerate(s.placements) if p[0] in {'stem_section','branch_section'}]


def test_crown_graph_resources_and_accounting_are_deterministic_and_lod_stable():
    cases=[snapshot(lod=lod) for lod in (0,1,2)]
    for sim,s in cases:
        assert s.to_dict()==snapshot(lod=sim.lod)[1].to_dict()
        assert PlantGrowthSnapshot.from_dict(s.to_dict()).to_dict()==s.to_dict()
        assert axes(s)==axes(cases[0][1])
        assert sim.get_ecological_outcome()==cases[0][0].get_ecological_outcome()
        assert s.stats['estimated_leaf_count']==cases[0][1].stats['estimated_leaf_count']
        assert s.stats['leaf_area_m2']==cases[0][1].stats['leaf_area_m2']
        assert len(s.placements)<1000 and s.stats['basal_shoot_count']==5
        for i,p in enumerate(s.placements):
            assert -1<=p[1]<i
            assert all(math.isfinite(v) for v in p[2:7])
            assert all(abs(v)<4 for v in p[2:5])
        for a in s.attachment_points:
            assert s.placements[a['leaf_placement_index']][0]=='leaf'
            assert s.placements[a['stem_placement_index']][0] in {'stem_section','branch_section'}
    assert not any(p[0] in {'rhizome','stolon','renewal_organ'} for p in cases[2][1].placements)


def test_leaflets_are_area_inside_one_leaf_and_shoot_counts_are_a_real_control():
    _,a=snapshot();_,half=snapshot(entity(leaflet_width={'typical_m':.008}))
    _,less=snapshot(entity(leaflet_count={'typical':1}))
    assert a.stats['estimated_leaf_count']==half.stats['estimated_leaf_count']==less.stats['estimated_leaf_count']
    # Areas are rounded per cohort before summation.
    tolerance=len(a.leaf_clusters)*1e-6
    assert half.stats['leaf_area_m2']==pytest.approx(a.stats['leaf_area_m2']*.5,abs=tolerance)
    assert less.stats['leaf_area_m2']==pytest.approx(a.stats['leaf_area_m2']/3,abs=tolerance)
    _,small=snapshot(entity(plant_shoot_profile={**entity()['plant_shoot_profile'],'basal_shoot_count':1}))
    assert a.stats['estimated_leaf_count']>small.stats['estimated_leaf_count']*4
    _,young=snapshot(day=15)
    assert young.stats['basal_shoot_count']<5
    assert not any(p[0] in {'flower','fruit'} for p in young.placements)


def test_head_sockets_follow_season_without_extra_seed_or_leaf_counts():
    _,flowers=snapshot();_,fruits=snapshot(day=300)
    hosts=lambda s,k:{tuple(s.placements[p[1]][2:5]) for p in s.placements if p[0]==k}
    assert hosts(flowers,'flower') and hosts(fruits,'fruit')
    assert hosts(fruits,'fruit')<=hosts(flowers,'flower')
    assert axes(flowers)==axes(fruits)
    assert not hosts(fruits,'flower')
    assert flowers.stats['leaf_area_m2']==fruits.stats['leaf_area_m2']
    for changes in ({'plant_reproductive_profile':None},{'reproductive_mode':'vegetative'},
                    {'plant_reproductive_structure':'other_unknown'}):
        assert not hosts(snapshot(entity(**changes),day=300)[1],'fruit')


def test_fixation_and_mycorrhiza_reuse_existing_nutrient_response():
    sim,s=snapshot();g=sim.blueprint.growth
    env={'available_nitrogen_g_m2':0.,'available_phosphorus_g_m2':.6}
    active=resolve_plant_nutrient_response(g,env,s.stats)
    neutral=resolve_plant_nutrient_response({**g,'nitrogen_fixation':'other_unknown'},env,s.stats)
    assert active['nitrogen_fixation']=='active'
    assert active['mycorrhizal_phosphorus_multiplier']>1
    assert active['nitrogen_response']>neutral['nitrogen_response']==0
    empty=resolve_plant_nutrient_response(g,{**env,'available_phosphorus_g_m2':0},s.stats)
    assert empty['phosphorus_response']==0
    missing=resolve_plant_nutrient_response(g,{},s.stats)
    assert missing['nitrogen_response']==missing['phosphorus_response']==1


def test_saved_species_assets_and_biosim_outputs():
    from world.world_model import WorldModel
    from world.plant_catalogue import PlantCatalogue
    from tools.render_plant_biosim_check import sprite
    from simulations.biosphere.plant_pictures import top_view,map_sprite_at
    w=WorldModel();e=w.resolved_species_entity('spec_trifolium_pratense')
    assert 'cladis_clovers_trifolium' in e['parents']
    assert PlantCatalogue.build(w.loader.entities).is_leaf_species(e['id'])
    assert e['plant_woodiness']=='herbaceous' and e['clonal_spread']=='none'
    sim=SpeciesSimulation(world_model=w,species_id=e['id'],seed=303)
    pygame.init();pygame.display.set_mode((1,1));renderer=SpeciesRenderer(SimpleNamespace(camera=None))
    for role in ('leaf','stem','branch','flower','fruit'):
        assert e[f'plant_{role}_module_ref']==f'assets/illustrations/illust_trifolium_pratense_{role}_module_pixel.png'
        assert Path(f'assets/illustrations/illust_trifolium_pratense_{role}_module_pixel.layers.json.gz').exists()
    for day in (15,180,300):
        sim.set_age(day);art,anchor=sprite(renderer,sim,84)
        assert 0<art.get_width()<=96 and 0<art.get_height()<=100
        assert 0<=anchor[0]<art.get_width() and 0<=anchor[1]<art.get_height()
        top=top_view(sim);assert top is not None and max(top.get_size())<=192
        assert max(map_sprite_at(top,40).get_size())<=40
    pygame.quit()
