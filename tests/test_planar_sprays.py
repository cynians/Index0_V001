"""Planar foliage, separate morphotypes, and portable group accounting."""
from copy import deepcopy
import json
import math
from pathlib import Path
from types import SimpleNamespace

import pygame
import pytest

from simulations.species.planar_sprays import planar_spray_profile,draw_planar_spray
from simulations.species.plant_assets import PlantBlueprint,PlantGrowthSnapshot
from simulations.species.species_simulation import SpeciesSimulation
from simulations.species.species_editor import editable_field_rows,PREVIEW_AFFECTING_FIELDS
from simulations.species.species_renderer import SpeciesRenderer,TopDownDiagnosticCamera
from tools.author_plant_species import validate_updates,AuthoringError,prepare_update
from tools.author_plant_assets import load_manifest,_wire_module,validate_manifest,ManifestError
from world.species_inheritance import resolved_species_entity


def entity(**changes):
    p={'form':'planar_foliage_sprays','axis_length_m':1.2,'axis_radius_m':.003,
       'peripheral_length_m':.12,'plane_tilt_deg':8.,'plane_roll_variation_deg':25.,
       'side_angle_deg':65.,'needle_width_m':.0016,'axial_leaf_length_m':.005,
       'axial_leaf_width_m':.0009,'rows_per_axis':6,'needle_pairs_per_shoot':6,
       'represented_systems':96,'axial_leaves_per_node':4}
    return {'id':'spec_synthetic_planar_conifer','type':'species','parents':['cladis_fixture'],
        'plant_growth_form':'tree','plant_growth_behaviour':'branched_woody',
        'plant_woodiness':'woody','plant_lifespan':'perennial','leaf_phenology':'evergreen',
        'leaf_structure':'needle_like','leaf_length':{'typical_m':.018},'leaf_arrangement':'spiral',
        'plant_leaf_distribution':'along_shoot','plant_axis_continuity':'monopodial',
        'plant_shoot_dimorphism':'axial_and_peripheral_shoots',
        'plant_branching_subpattern':'planar_foliage_sprays','plant_shoot_profile':p,
        'mature_height':{'max_m':35},'reproductive_mode':'both',**changes}


def sim(e=None):return SpeciesSimulation(species_id='spec_synthetic_planar_conifer',species_entity=e or entity(),seed=303)


def snap(e=None,lod=2,detail=False):
    s=sim(e);return s.generate_snapshot(s.mature_age_days*1.1,lod,detail)


def test_schema_editor_inheritance_and_portable_profile():
    fields={'plant_branching_subpattern':'planar_foliage_sprays','plant_shoot_dimorphism':'axial_and_peripheral_shoots'}
    validate_updates(fields)
    e=entity();e.pop('plant_branching_subpattern')
    parent={'id':'cladis_fixture','type':'cladistics','parents':['cladis_plants_plantae'],**fields}
    root={'id':'cladis_plants_plantae','type':'cladistics'}
    loader=SimpleNamespace(entities={e['id']:e,parent['id']:parent,root['id']:root})
    r=resolved_species_entity(loader,e)
    assert r['plant_branching_subpattern']=='planar_foliage_sprays'
    b=PlantBlueprint.from_species_entity(r)
    assert b.growth['planar_spray_profile']['represented_systems']==96
    assert PlantBlueprint.from_dict(json.loads(json.dumps(b.to_dict()))).fingerprint()==b.fingerprint()
    for field in fields:
        assert field in PREVIEW_AFFECTING_FIELDS
        assert any(x['field']==field and x['kind']=='choice' for x in editable_field_rows(r,''))


def test_every_peripheral_shoot_lies_in_its_axial_plane_and_on_its_host():
    a=snap()
    for cohort in a.leaf_clusters:
        p=cohort.get('planar_spray')
        if not p:continue
        n=p['normal'];origin=p['origin_m']
        assert sum(v*v for v in n)==pytest.approx(1.)
        points=p['axis_points_m']+[q['tip_m'] for q in p['peripheral_shoots']]
        for point in points:
            assert sum((point[k]-origin[k])*n[k] for k in range(3))==pytest.approx(0.,abs=1e-6)
    for at in a.attachment_points:
        if at.get('socket') in {'axial_base','peripheral_base'}:
            i=at['placement_index'];host=at['host_placement_index']
            assert a.placements[i][1]==host
            assert math.dist(a.placements[host][2:5],at['position_m'])<.001


def test_axial_leader_has_no_peripheral_fronds_and_areas_count_once():
    a=snap()
    leader=[c for c in a.leaf_clusters if c.get('planar_spray',{}).get('leader')]
    assert leader and all(not c['planar_spray']['peripheral_shoots'] for c in leader)
    assert all(c['planar_spray']['peripheral_leaf_count']==0 for c in leader)
    for c in a.leaf_clusters:
        p=c.get('planar_spray')
        if not p:continue
        assert c['estimated_leaf_count']==p['peripheral_leaf_count']+p['axial_leaf_count']
        assert c['leaf_area_m2']==pytest.approx(p['peripheral_leaf_area_m2']+p['axial_leaf_area_m2'],abs=1e-6)
    assert not any(p[0] in {'flower','fruit'} for p in a.placements)


def test_lod_detail_and_clonal_tree_preserve_canonical_quantities():
    e=entity(plant_growth_behaviour='suckering_clonal',clonal_spread='moderate')
    a=snap(e)
    assert a.stats['tree_sucker_count']>0
    for lod,d in [(0,False),(1,False),(2,True)]:
        b=snap(e,lod,d)
        for key in ('estimated_leaf_count','leaf_area_m2','structural_axis_length_m','root_length_m','tree_sucker_count','planar_spray_count'):
            assert a.stats[key]==b.stats[key]


def test_bounded_deterministic_geometry_serialization_and_juveniles():
    a=snap();assert a.to_dict()==snap().to_dict()
    assert PlantGrowthSnapshot.from_dict(json.loads(json.dumps(a.to_dict()))).to_dict()==a.to_dict()
    assert len(a.placements)<30000
    for i,p in enumerate(a.placements):
        assert p[1]==-1 or 0<=p[1]<i
        assert all(math.isfinite(x) for x in p[2:])
        for point in a.placement_paths.get(str(i),[]):
            assert all(a.bounds_m[k*2]-.001<=v<=a.bounds_m[k*2+1]+.001 for k,v in enumerate(point))
    s=sim();young=s.generate_snapshot(s.mature_age_days*.25,2)
    assert young.stats['estimated_leaf_count']<a.stats['estimated_leaf_count']*.3
    assert s.blueprint.module('leaf').length_m==.018


@pytest.mark.parametrize('key,value',[('rows_per_axis',0),('represented_systems',10000),
    ('needle_pairs_per_shoot',True),('plane_tilt_deg',math.nan),('axis_length_m',math.inf),
    ('needle_width_m',-.001)])
def test_invalid_profiles_are_rejected(key,value):
    p=entity()['plant_shoot_profile'];p[key]=value
    assert planar_spray_profile(p) is None
    with pytest.raises(AuthoringError):validate_updates({'plant_shoot_profile':p})


def test_missing_unknown_wrong_body_plan_are_neutral():
    for value in (None,{}, {'form':'other_unknown'}):
        assert 'planar_spray_version' not in sim(entity(plant_shoot_profile=value)).blueprint.growth
    for updates in ({'plant_growth_form':'forb'},{'leaf_structure':'simple'}, {'plant_branching_subpattern':'other_unknown'}):
        assert 'planar_spray_version' not in sim(entity(**updates)).blueprint.growth


def test_single_shoot_conifer_reuses_planes_without_redwood_morphotype():
    e=entity(plant_shoot_dimorphism='single_shoot_system');s=sim(e);a=s.generate_snapshot(s.mature_age_days*1.1,2)
    assert s.blueprint.module('axial_leaf') is None
    assert all(c['planar_spray']['axial_leaf_count']==0 for c in a.leaf_clusters if c.get('planar_spray'))
    assert any(c.get('shoot_role')=='leader' for c in a.leaf_clusters)


def test_plane_tilt_changes_supporting_branches_not_only_foliage():
    low=entity(); high=deepcopy(low)
    low['plant_shoot_profile']['plane_tilt_deg']=-15.
    high['plant_shoot_profile']['plane_tilt_deg']=30.
    a,b=snap(low),snap(high)
    primary=lambda s:[p for p in s.placements if p[0]=='branch_section' and p[7]==2]
    secondary=lambda s:[p for p in s.placements if p[0]=='branch_section' and p[7]==3]
    assert primary(a)==primary(b)
    x,y=secondary(a),secondary(b)
    assert x and len(x)==len(y)
    assert all(q[4]>p[4] for p,q in zip(x,y))
    assert all(p[2:4]==q[2:4] for p,q in zip(x,y))


def test_group_contrast_changes_counts_not_individual_dimensions_or_skeleton():
    a=entity();b=deepcopy(a);b['plant_shoot_profile']['represented_systems']=48
    x,y=snap(a),snap(b)
    assert x.stats['estimated_leaf_count']==2*y.stats['estimated_leaf_count']
    # Cohorts round area to six decimals before the total is accumulated.
    assert x.stats['leaf_area_m2']==pytest.approx(2*y.stats['leaf_area_m2'],abs=.001)
    exact=lambda a:sum(c['planar_spray']['peripheral_leaf_area_m2']+c['planar_spray']['axial_leaf_area_m2'] for c in a.leaf_clusters)
    assert exact(x)==pytest.approx(2*exact(y),abs=1e-9)
    assert x.placements==y.placements
    assert sim(a).blueprint.module('leaf').length_m==sim(b).blueprint.module('leaf').length_m
    assert sim(a).blueprint.fingerprint()!=sim(b).blueprint.fingerprint()


def test_named_leaf_asset_variant_preserves_base_asset_and_metric_leaf_size():
    path=Path('assets/plant_asset_specs/spec_sequoia_sempervirens.json');m=load_manifest(path)
    e=entity(plant_leaf_module_ref='unchanged_peripheral.png');anchors={'leaf':{'attachment_point':[.5,.9]}}
    _wire_module(e,anchors,m['modules'][0],'axial.png',{'attachment_point':[.5,.95],'depicted_size_m':.06})
    assert e['plant_leaf_module_ref']=='unchanged_peripheral.png'
    e['plant_module_anchors']=anchors;b=PlantBlueprint.from_species_entity(e)
    assert b.module('axial_leaf').asset_ref=='axial.png'
    assert b.module('axial_leaf').length_m==.005
    assert b.module('leaf').length_m==.018
    invalid=deepcopy(m);invalid['modules'][0]['role']='flower'
    with pytest.raises(ManifestError):validate_manifest(invalid)


def test_actual_spray_projection_foreshortens_and_biosim_keeps_foliage():
    from simulations.biosphere.biosphere_renderer import BiosphereBuilderRenderer
    from simulations.biosphere.plant_pictures import top_view,map_sprite_at
    pygame.init();pygame.display.set_mode((1,1))
    try:
        e=entity();e['plant_shoot_profile'].update(plane_tilt_deg=0.,plane_roll_variation_deg=0.)
        s=sim(e);s.set_age(s.mature_age_days*1.1)
        c=next(c for c in s.render_snapshot.leaf_clusters if c.get('planar_spray') and not c['planar_spray']['leader'])
        p=c['planar_spray'];assert abs(p['normal'][2])>.98
        renderer=SpeciesRenderer(SimpleNamespace(camera=None))
        from unittest.mock import patch
        source=pygame.Surface((75,75),pygame.SRCALPHA);pygame.draw.ellipse(source,(50,120,60),(20,2,35,70))
        unit={'estimated_leaf_count':12,'planar_spray':{'detail_single_system':True,'identity':0,
            'axis_points_m':[],'normal':[0.,0.,1.],'right':[0.,1.,0.],'group_half_width_m':.02,
            'peripheral_shoots':[{'base_m':[0.,0.,0.],'tip_m':[.12,0.,0.],
                                  'forward':[1.,0.,0.],'length_m':.12}]}}
        camera=TopDownDiagnosticCamera(400,400,(-.02,.15,-.1,.1))
        face=pygame.Surface((400,400),pygame.SRCALPHA);edge=face.copy()
        with patch.object(renderer,'_module_asset',return_value=source):
            draw_planar_spray(renderer,face,s,camera,unit)
            unit['planar_spray']['normal']=[0.,1.,0.]
            draw_planar_spray(renderer,edge,s,camera,unit)
        assert pygame.surfarray.array_alpha(edge).sum()<pygame.surfarray.array_alpha(face).sum()*.4
        scene=SimpleNamespace(world_model=SimpleNamespace(repository_revision=0),world_units_to_meters=1.,get_representative_species_simulation=lambda _:s)
        instance={'species_id':s.species_id,'representative_id':'test','abundance':1.,'visual_scale':1.,'variant':0}
        bio=BiosphereBuilderRenderer(SimpleNamespace(),species_renderer=renderer)
        art,anchor=bio._render_sprite_surface(scene,instance,SimpleNamespace(zoom=400.,sprite_height_cap=84))
        assert art.get_bounding_rect().width>0 and all(math.isfinite(x) for x in anchor)
        pic=top_view(s);assert pic is not None
        colors=pygame.surfarray.array3d(map_sprite_at(pic,40))
        assert ((colors[:,:,1]>colors[:,:,0]*1.05)&(colors[:,:,1]>colors[:,:,2])).sum()>20
    finally:pygame.quit()
