"""Portable dimorphic herbs, basal foliage and connected reproductive axes."""
import json
import math
from pathlib import Path
import pytest
from simulations.species.dimorphic_herbs import dimorphic_herb_profile
from simulations.species.plant_assets import PlantBlueprint,PlantGrowthSnapshot
from simulations.species.species_simulation import SpeciesSimulation
from tools.author_plant_species import validate_updates,AuthoringError

def entity(**changes):
    m=json.loads(Path('assets/plant_asset_specs/spec_nuttallanthus_canadensis.json').read_text())
    return {'id':'spec_synthetic_dimorphic_annual','plant_growth_form':'forb',
        'plant_woodiness':'herbaceous','plant_growth_behaviour':'unbranched_single_axis',
        'plant_shoot_dimorphism':'long_and_short_shoots','plant_leaf_distribution':'mixed_long_short_shoots',
        'plant_lifespan':'annual','plant_life_form':'therophyte','maturity_rate':'fast',
        'mature_height':{'min_m':.1,'max_m':.8},'leaf_structure':'simple','leaf_arrangement':'alternate',
        'leaf_attachment_pattern':'along_stem','leaf_length':{'typical_m':.02},
        'plant_reproductive_structure':'flower','plant_flowering_position':'terminal',
        'root_architecture':'taproot','reproductive_mode':'sexual',**m['species_field_updates'],**changes}

def sim(data=None,day=127.75,lod=2):
    s=SpeciesSimulation(species_entity=data or entity(),seed=303)
    s.set_lod(lod);s.set_age(day)
    return s

@pytest.mark.parametrize('key,value',[('flowering_shoot_height_m',math.nan),('flowering_shoot_count',0),
    ('basal_shoot_count',True),('basal_shoot_count',13),('stem_leaf_nodes',33),
    ('basal_nodes_per_shoot',13),('leaf_width_m',0),('stem_radius_m',math.inf),
    ('basal_leaf_width_scale',1.6),('display_open_florets',21),('fruiting_axis_scale',2.6)])
def test_malformed_recipe_is_neutral_and_authoring_rejects(key,value):
    p={**entity()['plant_shoot_profile'],key:value}
    assert dimorphic_herb_profile(p) is None
    with pytest.raises(AuthoringError): validate_updates({'plant_shoot_profile':p})
    assert sim(entity(plant_shoot_profile=p)).blueprint.fingerprint()==sim(entity(plant_shoot_profile=None)).blueprint.fingerprint()

def test_profile_requires_correct_shoot_types_and_survives_transport():
    s=sim()
    assert s.blueprint.growth['dimorphic_herb_profile_version']==1
    assert s.blueprint.growth['structural_raceme_version']==1
    assert PlantBlueprint.from_dict(s.blueprint.to_dict()).fingerprint()==s.blueprint.fingerprint()
    assert s.blueprint.module('leaf').radius_m==.001
    assert s.blueprint.module('flower').length_m==.012
    assert s.blueprint.module('fruit').length_m==.005
    for key,value in [('plant_growth_form','shrub'),('plant_woodiness','woody'),
        ('plant_growth_behaviour','iterative_indeterminate'),('plant_shoot_dimorphism','single_shoot_system'),
        ('plant_leaf_distribution','along_shoot')]:
        assert not sim(entity(**{key:value})).blueprint.growth.get('dimorphic_herb_profile_version')

def test_canonical_graph_is_connected_deterministic_bounded_and_lod_neutral():
    s=sim();snap=s.render_snapshot
    assert snap.to_dict()==sim().render_snapshot.to_dict()
    assert PlantGrowthSnapshot.from_dict(snap.to_dict()).to_dict()==snap.to_dict()
    assert snap.stats['dimorphic_basal_shoot_count']==7
    assert snap.stats['dimorphic_basal_leaf_count']==112
    assert snap.stats['dimorphic_stem_leaf_count']==9
    assert len(snap.placements)<3000
    for i,p in enumerate(snap.placements):
        assert p[1]==-1 or 0<=p[1]<i
        assert all(math.isfinite(v) and abs(v)<2 for v in p[2:5])
    for lod in (0,1):
        other=sim(lod=lod)
        for key in ('estimated_leaf_count','leaf_area_m2','root_depth_m','dimorphic_flower_count'):
            assert other.render_snapshot.stats[key]==snap.stats[key]
        assert other.get_ecological_outcome()==s.get_ecological_outcome()

def test_basal_shoots_are_low_paired_and_do_not_carry_flower_sockets():
    snap=sim().render_snapshot
    basal=[c for c in snap.leaf_clusters if c.get('cohort')=='basal_vegetative']
    fertile=[c for c in snap.leaf_clusters if c.get('cohort')=='fertile_stem']
    assert basal and fertile
    assert max(c['position_m'][2] for c in basal)<.03
    assert max(c['position_m'][2] for c in fertile)>.3
    hosts={c['host_placement_index'] for c in basal}
    for host in hosts:
        leaves=[c['leaf_placement_index'] for c in basal if c['host_placement_index']==host]
        assert len(leaves)==2
        a,b=[snap.placement_orientations[str(i)]['forward'] for i in leaves]
        assert a[:2]==pytest.approx([-b[0],-b[1]],abs=1e-5)
    for p in snap.placements:
        if p[0]=='flower':
            assert snap.placements[int(p[1])][0]=='branch_section'
            assert int(snap.placements[int(p[1])][1]) not in hosts

def test_independent_basal_density_blade_width_and_shoot_height_controls():
    p=entity()['plant_shoot_profile'];s=sim()
    sparse=sim(entity(plant_shoot_profile={**p,'basal_shoot_count':0}))
    broad=sim(entity(plant_shoot_profile={**p,'leaf_width_m':.004}))
    tall=sim(entity(plant_shoot_profile={**p,'flowering_shoot_height_m':.9}))
    assert sparse.render_snapshot.stats['estimated_leaf_count']==9
    # Serialized per-leaf cohorts round area to six decimal places.
    assert broad.render_snapshot.stats['leaf_area_m2']==pytest.approx(s.render_snapshot.stats['leaf_area_m2']*2,abs=1e-5)
    stem_tip=lambda s:max(p[4] for p in s.render_snapshot.placements if p[0]=='stem_section')
    assert stem_tip(tall)>stem_tip(s)*1.8
    assert sparse.render_snapshot.stats['root_depth_m']==tall.render_snapshot.stats['root_depth_m']==s.render_snapshot.stats['root_depth_m']

def test_raceme_has_individual_hosts_elongates_in_fruit_and_annual_does_not_repeat():
    bloom,fruit=sim(),sim(day=365*.65)
    assert bloom.render_snapshot.stats['dimorphic_flower_count']==4
    assert bloom.render_snapshot.stats['dimorphic_fruit_count']==0
    assert fruit.render_snapshot.stats['dimorphic_flower_count']==0
    assert fruit.render_snapshot.stats['dimorphic_fruit_count']==10
    tip=lambda s:max(p[4] for p in s.render_snapshot.placements if p[0]=='stem_section')
    assert tip(fruit)-tip(bloom)==pytest.approx(.09*.6,abs=.0002)
    for p in fruit.render_snapshot.placements:
        if p[0]=='fruit':
            host=fruit.render_snapshot.placements[int(p[1])]
            assert host[0]=='branch_section' and host[2:5]==p[2:5]
            path=fruit.render_snapshot.placement_paths[str(p[1])]
            assert math.dist(path[0],path[-1])<.005
    for day in (365,492.75):
        dead=sim(day=day)
        assert dead.life_state()['phase']=='dead'
        assert not any(p[0] in {'flower','fruit'} for p in dead.render_snapshot.placements)
    for data in (entity(reproductive_mode='vegetative'),entity(plant_flowering_position='lateral'),
                 entity(plant_inflorescence_profile=None),entity(plant_reproductive_structure='other_unknown')):
        assert not any(p[0]=='flower' for p in sim(data).render_snapshot.placements)

def test_renderer_does_not_multiply_already_structural_racemes():
    import pygame
    from types import SimpleNamespace
    from simulations.species.species_renderer import SpeciesRenderer,DiagnosticCamera
    pygame.init();pygame.display.set_mode((1,1))
    s=sim();r=SpeciesRenderer(SimpleNamespace(camera=None))
    image=pygame.Surface((75,75),pygame.SRCALPHA);image.fill((180,160,210,255))
    r._module_asset=lambda *_:image
    screen=pygame.Surface((300,300),pygame.SRCALPHA)
    camera=DiagnosticCamera(300,300,(0,.1,0,.1),minimum_span_m=.001)
    assert r._draw_module_asset(screen,s,camera,'flower',(150,150),0,1)
    assert not r._inflorescence_sprite_cache
    assert screen.get_bounding_rect().height<50
