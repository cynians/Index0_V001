"""Leafy moss geometry, wetting, metric assets and production consumers."""
import json
import math
from pathlib import Path
from types import SimpleNamespace

import pygame
import pytest
from simulations.species.moss_turfs import moss_turf_profile, moss_water_response
from simulations.species.plant_assets import PlantBlueprint, PlantGrowthSnapshot
from simulations.species.species_simulation import SpeciesSimulation
from simulations.species.species_renderer import SpeciesRenderer, TopDownDiagnosticCamera
from tools.author_plant_species import validate_updates, AuthoringError
from tools.render_species_views import stage_ages, configure_stage


def entity(**changes):
    manifest=json.loads(Path('assets/plant_asset_specs/spec_racomitrium_lanuginosum.json').read_text(encoding='utf-8'))
    return {'id':'spec_unrelated_leafy_bryophyte',**manifest['species_field_updates'],**changes}


def snapshot(data=None,day=220,lod=2,environment=None):
    sim=SpeciesSimulation(species_entity=data or entity(),seed=303,environment=environment)
    sim.set_lod(lod);sim.set_age(day)
    return sim,sim.render_snapshot


@pytest.mark.parametrize('changes',[{'patch_diameter_m':0},{'shoot_length_m':.251},
    {'stem_radius_m':True},{'leaf_width_m':float('nan')},{'shoot_spacing_m':float('inf')},
    {'leaf_spacing_m':.0002},{'branch_fraction':1.1},{'shoot_lean':-.1},
    {'hairpoint_fraction':.71},{'outline_irregularity':.81},{'form':'basal_herb'}])
def test_invalid_moss_recipes_are_neutral_and_authoring_rejects(changes):
    bad={**entity()['plant_shoot_profile'],**changes}
    assert moss_turf_profile(bad) is None
    with pytest.raises(AuthoringError):validate_updates({'plant_shoot_profile':bad})
    assert PlantBlueprint.from_species_entity(entity(plant_shoot_profile=bad)).fingerprint()==PlantBlueprint.from_species_entity(entity(plant_shoot_profile=None)).fingerprint()


def axes(s):
    return [(p[0],p[2:5],s.placement_paths[str(i)]) for i,p in enumerate(s.placements) if p[0]!='leaf']


def test_profile_transport_roundtrip_and_gate():
    a=PlantBlueprint.from_species_entity(entity())
    assert a.growth['moss_turf_profile']['shoot_length_m']==.055
    assert a.module('leaf').radius_m==.000375
    assert a.module('stem_section').radius_m==.00012
    assert {m.id for m in a.modules}=={'stem_section','branch_section','leaf'}
    assert PlantBlueprint.from_dict(a.to_dict()).fingerprint()==a.fingerprint()
    for change in ({'plant_growth_form':'forb'},{'plant_growth_behaviour':'surface_covering'}):
        assert 'moss_turf_version' not in PlantBlueprint.from_species_entity(entity(**change)).growth
    assert a.fingerprint()!=PlantBlueprint.from_species_entity(entity(plant_shoot_profile={**entity()['plant_shoot_profile'],'hairpoint_fraction':0})).fingerprint()


def test_canonical_geometry_sockets_area_and_ecology_are_lod_stable():
    cases=[snapshot(lod=lod) for lod in (0,1,2)]
    for sim,s in cases:
        assert s.to_dict()==snapshot(lod=sim.lod)[1].to_dict()
        assert PlantGrowthSnapshot.from_dict(s.to_dict()).to_dict()==s.to_dict()
        assert axes(s)==axes(cases[0][1])
        assert s.bounds_m==cases[0][1].bounds_m
        assert sim.get_ecological_outcome()==cases[0][0].get_ecological_outcome()
        assert s.stats['leaf_area_m2']==cases[0][1].stats['leaf_area_m2']
        assert len(s.placements)<256*82
        for i,p in enumerate(s.placements):
            assert -1<=p[1]<i
            assert all(math.isfinite(v) for v in p[2:7])
            assert all(abs(v)<.2 for v in p[2:5])
            for q in s.placement_paths[str(i)]:
                assert all(s.bounds_m[k*2]-1e-6<=q[k]<=s.bounds_m[k*2+1]+1e-6 for k in range(3))
        for a in s.attachment_points:
            if a['socket']=='leaf':
                assert s.placements[a['leaf_placement_index']][0]=='leaf'
                assert s.placements[a['stem_placement_index']][0] in {'stem_section','branch_section'}
            else:assert a['socket']=='rhizoid_attachment' and a['position_m'][2]==0
        assert not any(p[0] in {'flower','fruit','root','root_section'} for p in s.placements)
    assert len(cases[0][1].placements)<len(cases[1][1].placements)<len(cases[2][1].placements)


def test_wetting_changes_leaf_pose_and_activity_without_killing_or_growing_axes():
    wet,a=snapshot(environment={'moss_hydration':1})
    dry,b=snapshot(environment={'moss_hydration':0,'soil_moisture':1,'available_nitrogen_g_m2':100})
    assert axes(a)==axes(b)
    assert a.stats['leaf_area_m2']==b.stats['leaf_area_m2']
    assert a.placement_paths!=b.placement_paths
    assert wet.get_ecological_outcome()['growth_rate']>dry.get_ecological_outcome()['growth_rate']==0
    assert wet.get_ecological_outcome()['mortality_risk']==dry.get_ecological_outcome()['mortality_risk']==0
    configure_stage(dry,'Rewetted mat',220)
    assert dry.render_snapshot.placement_paths==a.placement_paths
    e=dry.get_ecological_outcome()
    assert e['root_depth_m']==e['root_length_m']==0
    assert e['nitrogen_fixation_status']=='epiphytic_association_rate_unresolved'
    assert e['fecundity']==0


@pytest.mark.parametrize('raw',[None,False,True,'0',float('nan'),float('inf')])
def test_missing_or_invalid_wetting_is_neutral(raw):
    assert moss_water_response({'moss_hydration':raw})['moss_activity']==1
    assert moss_water_response({'moss_hydration':raw})['moss_hydration_status']=='unresolved_neutral'


def test_density_branching_and_hairpoints_have_real_ab_effects():
    _,a=snapshot()
    profile=entity()['plant_shoot_profile']
    _,sparse=snapshot(entity(plant_shoot_profile={**profile,'shoot_spacing_m':.016}))
    _,unbranched=snapshot(entity(plant_shoot_profile={**profile,'branch_fraction':0}))
    _,hairless=snapshot(entity(plant_shoot_profile={**profile,'hairpoint_fraction':0}))
    assert a.stats['moss_shoot_count']>sparse.stats['moss_shoot_count']*2
    assert a.stats['moss_branch_count']>unbranched.stats['moss_branch_count']==0
    assert hairless.stats['leaf_area_m2']>a.stats['leaf_area_m2']
    _,young=snapshot(day=7.5)
    assert young.stats['moss_shoot_count']<a.stats['moss_shoot_count']


def test_independent_stems_and_branches_render_their_own_projected_path(monkeypatch):
    sim,s=snapshot(lod=0)
    pygame.init();pygame.display.set_mode((1,1))
    try:
        renderer=SpeciesRenderer(SimpleNamespace(camera=None))
        camera=TopDownDiagnosticCamera(400,400,[-.12,.12,-.12,.12])
        calls=[]
        def capture(screen,case,kind,points,width):
            calls.append((kind,points,width));return True
        monkeypatch.setattr(renderer,'_draw_structural_asset_path',capture)
        renderer._draw_individual(pygame.Surface((400,400)),sim,camera=camera,clear=False,cache=False,draw_environment=False,draw_ground_line=False)
        assert len(calls)==len(s.placements)
        for kind,points,width in calls:
            expected=[[renderer._path_screen(camera,p) for p in s.placement_paths[str(i)]] for i,p in enumerate(s.placements) if p[0]==kind]
            assert points in expected and len(points)==2
            assert width==max(1,round(2*sim.blueprint.module(kind).radius_m*renderer._projection_pixels_per_meter(camera)))
    finally:pygame.quit()


def test_saved_taxon_assets_and_biosim_consumers():
    from world.world_model import WorldModel
    from world.plant_catalogue import PlantCatalogue
    from tools.render_plant_biosim_check import sprite
    from simulations.biosphere.plant_pictures import top_view,map_sprite_at
    w=WorldModel();e=w.resolved_species_entity('spec_racomitrium_lanuginosum')
    assert e['parents']==['cladis_racomitrium']
    assert PlantCatalogue.build(w.loader.entities).is_leaf_species(e['id'])
    sim,s=snapshot(e)
    assert all(m.asset_ref for m in sim.blueprint.modules)
    stages=stage_ages(sim)
    assert not any(name=='Flowering' for name,_ in stages)
    pygame.init();pygame.display.set_mode((1,1))
    try:
        renderer=SpeciesRenderer(SimpleNamespace(camera=None))
        for cap in (220,84):
            art,anchor=sprite(renderer,sim,cap)
            assert art.get_bounding_rect().width>0
            assert 0<=anchor[0]<=art.get_width() and 0<=anchor[1]<=art.get_height()
            assert art.get_height()<=cap
        picture=top_view(sim)
        assert picture is not None and picture.get_bounding_rect().width>0
        assert max(map_sprite_at(picture,40).get_size())<=40
    finally:pygame.quit()
