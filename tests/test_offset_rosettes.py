"""Canonical mother/offset structure, physical blades and explicit connectors."""
import json,math
from copy import deepcopy
from pathlib import Path
import pytest
from simulations.species.offset_rosettes import offset_rosette_profile
from simulations.species.species_simulation import SpeciesSimulation
from simulations.species.plant_assets import PlantBlueprint,PlantGrowthSnapshot
from tools.author_plant_species import validate_updates,AuthoringError

def entity():
    e={'id':'unrelated_offset_rosette',**json.loads(Path('assets/species_trait_specs/spec_agave_americana.json').read_text())['updates'],
       'mature_height':{'min_m':1.,'max_m':2.}}
    e['plant_shoot_profile'].pop('monocarpic_cycle',None)
    return e
def grown(e=None,age=177.75,lod=2,detail=False):
    s=SpeciesSimulation(species_entity=e or entity(),seed=303)
    return s,s.generate_snapshot(age,lod,detail)

@pytest.mark.parametrize('key,value',[('offset_count',-1),('offset_count',9),('offset_count',True),
    ('offset_count',2.5),('leaf_width_m',float('nan')),('offset_distance_m',float('inf')),
    ('offset_max_scale',1.),('offset_expansion_units',0)])
def test_invalid_profiles(key,value):
    p=entity()['plant_shoot_profile'];p[key]=value
    assert offset_rosette_profile(p) is None
    with pytest.raises(AuthoringError):validate_updates({'plant_shoot_profile':p})

def test_canonical_rosettes_are_connected_deterministic_and_portable():
    s,a=grown();_,b=grown()
    assert a.to_dict()==b.to_dict()==PlantGrowthSnapshot.from_dict(a.to_dict()).to_dict()
    assert s.blueprint.fingerprint()==PlantBlueprint.from_dict(s.blueprint.to_dict()).fingerprint()
    assert a.stats['daughter_rosette_count']==5 and a.stats['rosette_count']==6
    crowns=a.stats['offset_rosettes'];assert crowns[0]['scale']==1.
    assert len({round(c['scale'],4) for c in crowns})==6
    assert all(0<c['scale']<crowns[0]['scale'] for c in crowns[1:])
    for i,p in enumerate(a.placements):assert -1<=p[1]<i and all(math.isfinite(x) for x in p[2:])
    for c in crowns[1:]:
        host=a.placements[c['host_index']];connector=host[1]
        assert a.placement_orientations[str(connector)]['axis_role']=='rhizome'
        assert a.placements[connector][4]<0
    assert not any(p[0] in {'flower','fruit'} for p in a.placements)

def test_offset_count_does_not_change_the_mother_or_individual_dimensions():
    e=entity();e['plant_shoot_profile']['offset_count']=0;s,a=grown(e);t,b=grown()
    assert a.stats['rosette_count']==1 and a.stats['daughter_rosette_count']==0
    mother=lambda a:[a.placements[i] for i in a.stats['offset_rosettes'][0]['leaf_indices']]
    assert mother(a)==mother(b)
    assert s.blueprint.module('leaf').length_m==t.blueprint.module('leaf').length_m==1.1
    assert a.stats['leaf_area_m2']<b.stats['leaf_area_m2']
    assert s.blueprint.fingerprint()!=t.blueprint.fingerprint()

def test_development_uses_independent_offset_age_and_stable_slots():
    _,young=grown(age=20);_,first=grown(age=70);_,late=grown(age=220)
    assert young.stats['daughter_rosette_count']==0
    assert first.stats['daughter_rosette_count']==1
    assert late.stats['daughter_rosette_count']==5
    assert first.stats['offset_rosettes'][1]['center_m'][:2]==late.stats['offset_rosettes'][1]['center_m'][:2]
    assert first.stats['offset_rosettes'][1]['scale']<late.stats['offset_rosettes'][1]['scale']

def test_lod_detail_preserve_counts_area_structure_and_blade_arc_lengths():
    samples=[grown(lod=l,detail=d)[1] for l in (0,1,2) for d in (False,True)]
    for key in ('estimated_leaf_count','leaf_area_m2','structural_axis_length_m','daughter_rosette_count'):
        assert len({s.stats[key] for s in samples})==1
    a=samples[-1]
    assert a.stats['estimated_leaf_count']==sum(c['estimated_leaf_count'] for c in a.leaf_clusters)
    assert a.stats['leaf_area_m2']==pytest.approx(sum(c['leaf_area_m2'] for c in a.leaf_clusters),abs=1e-5)
    for c in a.stats['offset_rosettes']:
        for i in c['leaf_indices']:
            path=a.placement_paths[str(i)]
            length=sum(math.dist(x,y) for x,y in zip(path,path[1:]))
            assert .77*1.1*c['scale']<length<=1.101*c['scale']
            assert min(q[2] for q in path)>=0

@pytest.mark.parametrize('updates',[{'plant_growth_form':'forb'},{'plant_growth_form':'tree'},
    {'plant_growth_behaviour':'columnar_succulent'},{'plant_shoot_profile':{}},
    {'plant_shoot_profile':{'form':'other_unknown'}}])
def test_opt_in_and_unknowns(updates):
    e=entity();e.update(updates)
    assert 'offset_rosette_version' not in PlantBlueprint.from_species_entity(e).growth

def test_maximal_graph_is_bounded():
    e=entity();e['plant_shoot_profile'].update(offset_count=8,mother_leaves=80,offset_leaves=40)
    _,a=grown(e,age=1000)
    assert a.stats['daughter_rosette_count']==8 and len(a.placements)<450
