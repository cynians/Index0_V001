"""Supporting limbs and fine hanging shoots compose with coarse tree traits."""
import copy
import json
import math
from types import SimpleNamespace

import pygame
import pytest

from simulations.species.plant_assets import PlantBlueprint, PlantGrowthSnapshot
from simulations.species.species_simulation import SpeciesSimulation
from simulations.species.species_editor import editable_field_rows, PREVIEW_AFFECTING_FIELDS
from world.species_inheritance import resolved_species_entity
from tools.author_plant_species import validate_updates, AuthoringError, prepare_update


def entity(**changes):
    return {'id':'spec_unrelated_pendant_fixture','type':'species','parents':['cladis_fixture'],
            'plant_growth_form':'tree','plant_growth_behaviour':'branched_woody',
            'plant_woodiness':'woody','plant_lifespan':'perennial',
            'plant_leaf_distribution':'mixed_long_short_shoots',
            'plant_shoot_dimorphism':'long_and_short_shoots', 'leaf_arrangement':'alternate',
            'plant_axis_continuity':'sympodial','plant_lateral_axis_orientation':'plagiotropic',
            'plant_branching_subpattern':'pendant_branchlets', 'plant_branching_rhythm':'diffuse',
            'plant_crown_openness':.8,'plant_apical_control':.82,
            'plant_branch_droop':.83,'plant_leaf_cluster_density':.68,
            'plant_fine_twig_density':.82,'plant_leaf_spacing_bias':.73,
            'mature_height':{'max_m':30},'leaf_length':{'typical_m':.05},**changes}


def sim(e=None, seed=303):
    return SpeciesSimulation(species_id='spec_unrelated_pendant_fixture',species_entity=e or entity(),seed=seed)


def test_schema_editor_inheritance_authoring_and_blueprint_transport():
    field='plant_branching_subpattern';validate_updates({field:'pendant_branchlets'})
    with pytest.raises(AuthoringError): validate_updates({field:'unimplemented_pendant'})
    e=entity();e.pop(field)
    parent={'id':'cladis_fixture','type':'cladistics','parents':['cladis_plants_plantae'],field:'pendant_branchlets'}
    root={'id':'cladis_plants_plantae','type':'cladistics'}
    loader=SimpleNamespace(entities={e['id']:e,parent['id']:parent,root['id']:root})
    r=resolved_species_entity(loader,e);assert r[field]=='pendant_branchlets' and field not in e
    updated,_,_=prepare_update({'species':[e],'cladistics':[parent,root]},e['id'],{field:'pendant_branchlets'})
    assert updated[field]=='pendant_branchlets'
    b=PlantBlueprint.from_species_entity(r);assert b.growth['pendant_branchlet_version']==1
    assert PlantBlueprint.from_dict(json.loads(json.dumps(b.to_dict()))).fingerprint()==b.fingerprint()
    assert field in PREVIEW_AFFECTING_FIELDS
    assert any(x['field']==field and x['kind']=='choice' for x in editable_field_rows(r,'branch'))


def snapshot(e=None,lod=2,detail=False,seed=303):
    s=sim(e,seed);return s.generate_snapshot(s.mature_age_days*1.1,lod,detail)


def test_droop_belongs_to_fine_axes_without_lowering_supporting_limbs():
    a=snapshot(); b=snapshot(entity(plant_branch_droop=0.))
    assert len(a.stats['pendant_branchlets'])>0
    assert min(c['drop_m'] for c in a.stats['pendant_branchlets'])>0
    assert max(c['drop_m'] for c in b.stats['pendant_branchlets'])<0
    supporting=lambda snap:[p[2:7] for p in snap.placements if p[0] in {'stem_section','branch_section'} and p[7]<=3]
    assert supporting(a)==supporting(b)
    for k in ('estimated_leaf_count','leaf_area_m2','pendant_branchlet_count'):
        assert a.stats[k]==b.stats[k]
    assert sim(entity(plant_branch_droop=0.)).blueprint.fingerprint()!=sim().blueprint.fingerprint()


def test_determinism_bounds_sockets_and_snapshot_transport():
    a=snapshot();assert a.to_dict()==snapshot().to_dict()
    assert a.placements!=snapshot(seed=42).placements
    assert PlantGrowthSnapshot.from_dict(json.loads(json.dumps(a.to_dict()))).to_dict()==a.to_dict()
    assert len(a.placements)<10000
    for i,p in enumerate(a.placements):
        assert p[1]==-1 or 0<=p[1]<i
        assert all(math.isfinite(x) for x in p[2:])
        for point in a.placement_paths.get(str(i),[]):
            assert all(a.bounds_m[j*2]-.001<=x<=a.bounds_m[j*2+1]+.001 for j,x in enumerate(point))
    for attachment in a.attachment_points:
        if attachment.get('socket') in {'branchlet_base','short_shoot_base'}:
            i=attachment['placement_index'];host=attachment['host_placement_index']
            assert a.placements[i][1]==host
            assert math.dist(a.placement_paths[str(i)][0],attachment['position_m'])<.001
            assert math.dist(a.placements[host][2:5],attachment['position_m'])<.001


def test_detail_and_lod_keep_canonical_ecology_and_root_network():
    snapshots=[snapshot(lod=lod,detail=d) for lod,d in [(0,False),(1,False),(2,False),(2,True)]]
    for a in snapshots[1:]:
        for key in ('estimated_leaf_count','leaf_area_m2','structural_axis_length_m','root_length_m','pendant_branchlet_count'):
            assert a.stats[key]==snapshots[0].stats[key]
    for a in snapshots:
        assert a.stats['leaf_area_m2']==round(sum(c['leaf_area_m2'] for c in a.leaf_clusters),6)
    assert snapshots[-1].stats['leaf_count']>snapshots[2].stats['leaf_count']
    assert len(snapshots[-1].placements)<20000


def test_groups_count_once_and_dimorphic_short_shoots_stay_distinct():
    a=snapshot()
    for c in a.leaf_clusters:
        if c.get('pendant_branchlet_sites_m'):
            assert c['estimated_leaf_count']==sum(c['representative_node_leaf_counts'])*c['represented_shoots']
            assert min(c['representative_node_leaf_counts'])==1
            assert max(c['representative_node_leaf_counts'])==3
    b=snapshot(entity(plant_shoot_dimorphism='single_shoot_system'))
    assert not any(o.get('pendant_axis_role')=='short_shoot' for o in b.placement_orientations.values())
    assert b.stats['estimated_leaf_count']<a.stats['estimated_leaf_count']
    c=snapshot(entity(leaf_arrangement='opposite'))
    branch_count=lambda s:sum(c['estimated_leaf_count'] for c in s.leaf_clusters if c.get('pendant_branchlet_sites_m'))
    assert branch_count(c)==2*branch_count(a)


def test_juvenile_axes_have_smaller_node_and_group_budgets_not_larger_leaves():
    s=sim();young=s.generate_snapshot(s.mature_age_days*.25,2);adult=s.generate_snapshot(s.mature_age_days*1.1,2)
    assert young.stats['estimated_leaf_count']<adult.stats['estimated_leaf_count']*.2
    assert max(c['represented_shoots'] for c in young.leaf_clusters if c.get('pendant_branchlet_sites_m'))<max(
        c['represented_shoots'] for c in adult.leaf_clusters if c.get('pendant_branchlet_sites_m'))
    assert s.blueprint.module('leaf').length_m==.05


def test_missing_unknown_non_tree_and_bad_numeric_values_are_neutral():
    base=entity();base.pop('plant_branching_subpattern');a=sim(base).blueprint
    for value in (None,'','other_unknown','invalid_pattern'):
        assert sim({**base,'plant_branching_subpattern':value}).blueprint.fingerprint()==a.fingerprint()
    assert 'pendant_branchlet_version' not in sim(entity(plant_growth_form='shrub')).blueprint.growth
    for value in (math.nan,math.inf,True):
        a=snapshot(entity(plant_branch_droop=value))
        assert all(math.isfinite(x) for p in a.placements for x in p[2:])


def test_diagnostic_winter_removes_leaves_but_keeps_branchlet_framework():
    # Explicit test timing only. No calendar is authored onto the real birch.
    recipe={'cycle_days':365.,'flowering_start':.3,'flowering_end':.5,'fruit_start':.4,
            'fruit_ripe':.7,'fruit_retention_end':.9,'flower_size_m':.05,'fruit_size_m':.03,
            'unripe_color':[80,120,40],'ripe_color':[120,90,60],
            'leaf_out_start':.1,'leaf_out_full':.2,'leaf_fall_start':.75,'leaf_fall_end':.85}
    s=sim(entity(leaf_phenology='deciduous',plant_reproductive_profile=recipe))
    a=s.generate_snapshot(150,2);b=s.generate_snapshot(330,2)
    assert b.stats['estimated_leaf_count']==0 and b.stats['leaf_area_m2']==0
    assert a.stats['pendant_branchlets']==b.stats['pendant_branchlets']
    assert not any(p[0]=='fruit' for p in a.placements+b.placements)
    assert b.stats['fruit_morphology_status']=='unresolved_not_displayed'


def test_production_grounded_and_top_pictures_keep_collective_foliage():
    from simulations.biosphere.biosphere_renderer import BiosphereBuilderRenderer
    from simulations.biosphere.plant_pictures import top_view,map_sprite_at
    from simulations.species.species_renderer import SpeciesRenderer
    pygame.init();pygame.display.set_mode((1,1))
    try:
        s=sim();s.set_age(s.mature_age_days*1.1)
        renderer=BiosphereBuilderRenderer(SimpleNamespace(),species_renderer=SpeciesRenderer(SimpleNamespace(camera=None)))
        scene=SimpleNamespace(world_model=SimpleNamespace(repository_revision=0),world_units_to_meters=1.,get_representative_species_simulation=lambda _:s)
        instance={'species_id':s.species_id,'representative_id':'test','abundance':1.,'visual_scale':1.,'variant':0}
        art,anchor=renderer._render_sprite_surface(scene,instance,SimpleNamespace(zoom=400.,sprite_height_cap=84))
        assert art.get_bounding_rect().width>0 and all(math.isfinite(x) for x in anchor)
        picture=top_view(s);assert picture is not None
        for pic in (picture,map_sprite_at(picture,40)):
            colors=pygame.surfarray.array3d(pic)
            assert ((colors[:,:,1]>colors[:,:,0]*1.1)&(colors[:,:,1]>colors[:,:,2]*1.1)).sum()>20
    finally: pygame.quit()
