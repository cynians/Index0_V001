"""Developmental termination must change the connected graph, not just sprites."""
import json,math
from copy import deepcopy
from pathlib import Path
import pytest
from simulations.species.flower_terminated_forks import fork_profile,build_forks
from simulations.species.plant_assets import PlantBlueprint,PlantGrowthSnapshot
from simulations.species.species_simulation import SpeciesSimulation
from tools.author_plant_species import validate_updates,AuthoringError

def entity():
    return {'id':'unrelated_modular_herb',**json.loads(Path('assets/species_trait_specs/spec_solanum_nigrum.json').read_text())['updates']}
def grown(e=None,age=190,lod=2,detail=False):
    s=SpeciesSimulation(species_entity=e or entity(),seed=303)
    return s,s.generate_snapshot(age,lod,detail)

@pytest.mark.parametrize('key,value',[('fork_levels',5),('fork_levels',True),('fork_levels',2.5),
    ('flowers_per_cyme',11),('unit_length_ratio',float('nan')),('successor_length_ratio',float('inf')),
    ('stem_radius_m',0),('pedicel_length_m',-.01)])
def test_validation(key,value):
    p=entity()['plant_shoot_profile'];p[key]=value
    assert fork_profile(p) is None
    with pytest.raises(AuthoringError):validate_updates({'plant_shoot_profile':p})

def test_portable_graph_is_deterministic_bounded_and_explicitly_terminated():
    s,a=grown();_,b=grown()
    assert a.to_dict()==b.to_dict()==PlantGrowthSnapshot.from_dict(a.to_dict()).to_dict()
    assert PlantBlueprint.from_dict(s.blueprint.to_dict()).fingerprint()==s.blueprint.fingerprint()
    assert a.stats['sympodial_unit_count']==15 and a.stats['estimated_leaf_count']==34
    assert a.stats['flower_count']==75 and a.stats['fruit_count']==0
    assert a.stats['root_segment_count']==0
    for i,p in enumerate(a.placements):
        assert -1<=p[1]<i and all(math.isfinite(v) for v in p[2:])
    for unit in a.stats['sympodial_units']:
        end=unit['terminal_node'];ped=unit['terminal_peduncle']
        assert a.placements[ped][1]==end
        assert a.placement_orientations[str(ped)]['shoot_role']=='terminal_peduncle'
        children=[p for i,p in enumerate(a.placements) if p[1]==end
            and a.placement_orientations[str(i)].get('shoot_role')=='sympodial_axis']
        assert len(children)==(0 if unit['level']==3 else 2)

def test_control_changes_topology_and_fingerprint():
    e=entity();e['plant_shoot_profile']['fork_levels']=0;s,a=grown(e)
    t,b=grown();assert a.stats['sympodial_unit_count']==1 and a.stats['estimated_leaf_count']==6
    assert a.stats['flower_count']==5 and len(a.placements)<len(b.placements)
    assert s.blueprint.fingerprint()!=t.blueprint.fingerprint()
    e['plant_shoot_profile']['fork_levels']=4;_,c=grown(e)
    assert c.stats['sympodial_unit_count']==31 and len(c.placements)<2000

def test_phase_lod_and_detail_preserve_leaf_accounting():
    samples=[grown(age=age,lod=lod,detail=detail)[1] for age in (190,360) for lod in (0,1,2) for detail in (False,True)]
    for key in ('estimated_leaf_count','leaf_area_m2','sympodial_unit_count'):
        assert len({a.stats[key] for a in samples})==1
    assert all(a.stats['flower_count']==75 for a in samples[:6])
    assert all(a.stats['fruit_count']==45 for a in samples[6:])
    _,young=grown(age=11);assert young.stats['sympodial_unit_count']==0
    s,_=grown();nodes,stats=build_forks(s.blueprint.growth,1.,1.,0.,303,0.)
    assert stats['estimated_leaf_count']==0 and stats['leaf_area_m2']==0
    assert stats['sympodial_unit_count']==15

@pytest.mark.parametrize('updates',[{'plant_growth_form':'tree'},
    {'plant_growth_behaviour':'branched_woody'},{'plant_woodiness':'woody'},
    {'plant_branching_subpattern':'other_unknown'},{'plant_shoot_profile':{}},
    {'plant_flowering_position':'lateral'}])
def test_recipe_is_opt_in(updates):
    e=entity();e.update(updates)
    assert 'flower_fork_version' not in PlantBlueprint.from_species_entity(e).growth

def test_copied_other_species_requires_no_id_branch():
    from world.world_model import WorldModel
    w=WorldModel();e=deepcopy(w.resolved_species_entity('spec_solanum_lycocarpum'))
    assert e
    e.update(entity());e['id']='copied_solanum_herb_treatment';e['plant_shoot_profile']['fork_levels']=1
    s,a=grown(e);assert a.stats['sympodial_unit_count']==3
