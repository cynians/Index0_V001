"""One crown's terminal reproduction must not kill its surviving offsets."""
import json,math
from copy import deepcopy
from pathlib import Path
import pytest
from simulations.species.offset_rosettes import offset_rosette_profile
from simulations.species.plant_assets import PlantBlueprint,PlantGrowthSnapshot
from simulations.species.species_simulation import SpeciesSimulation
from tools.author_plant_species import validate_updates,AuthoringError

def entity():
    e={'id':'synthetic_monocarpic_colony',**json.loads(Path('assets/species_trait_specs/spec_agave_americana.json').read_text())['updates'],
       'mature_height':{'max_m':2.}}
    return e
def grown(age=360,lod=2,detail=False,e=None):
    s=SpeciesSimulation(species_entity=e or entity(),seed=303)
    return s,s.generate_snapshot(age,lod,detail)

@pytest.mark.parametrize('key,value',[('bloom_start_units',2.),('mother_dead_units',4.),
    ('stalk_retention_end_units',5.),('stalk_height_m',float('nan')),
    ('panicle_width_m',float('inf')),('lateral_count',36),('lateral_count',True),
    ('flowers_per_lateral',3.5),('successor_maturation_units',0)])
def test_invalid_cycle_is_rejected(key,value):
    p=entity()['plant_shoot_profile'];p['monocarpic_cycle'][key]=value
    assert offset_rosette_profile(p) is None
    with pytest.raises(AuthoringError):validate_updates({'plant_shoot_profile':p})

def test_nonrepeating_crown_cycle_and_persistent_daughters():
    samples=[grown(age=a)[1] for a in (180,270,360,450,540,720,1100)]
    assert [s.stats['flower_count'] for s in samples]==[0,0,200,0,0,0,0]
    assert [s.stats['mother_living_fraction'] for s in samples]==[1.,1.,1.,.5,0.,0.,0.]
    assert all(s.stats['daughter_rosette_count']==5 for s in samples)
    assert samples[4].stats['living_rosette_count']==5
    for s in samples[4:]:
        mother=s.stats['offset_rosettes'][0]
        assert all(s.placement_orientations[str(i)]['retained_dead_leaf'] for i in mother['leaf_indices'])
        assert all(c['leaf_area_m2']==0 for c in s.leaf_clusters
            if s.placement_orientations[str(c['host_placement_index'])].get('offset_crown_identity')==0)
        assert s.stats['leaf_area_m2']>0
    assert all(c['scale']==1. for c in samples[-1].stats['offset_rosettes'][1:])
    assert samples[-1].stats['estimated_leaf_count']==150
    assert not any(o.get('axis_role')=='flower_stalk' for o in samples[-1].placement_orientations.values())

def test_maternal_decline_does_not_reduce_daughter_geometry():
    e=entity();e['plant_shoot_profile'].pop('monocarpic_cycle')
    _,control=grown(age=450,e=e);_,treated=grown(age=450)
    def daughters(s):
        return [[s.placements[i][2:7] for i in c['leaf_indices']] for c in s.stats['offset_rosettes'][1:]]
    assert daughters(control)==daughters(treated)
    assert treated.stats['leaf_area_m2']<control.stats['leaf_area_m2']

def test_explicit_stalk_branch_flower_sockets_and_canonical_geometry():
    s,a=grown();_,b=grown()
    assert a.to_dict()==b.to_dict()==PlantGrowthSnapshot.from_dict(a.to_dict()).to_dict()
    assert s.blueprint.fingerprint()==PlantBlueprint.from_dict(s.blueprint.to_dict()).fingerprint()
    assert sum(o.get('axis_role')=='panicle_lateral' for o in a.placement_orientations.values())==20
    for i,p in enumerate(a.placements):
        assert -1<=p[1]<i and all(math.isfinite(x) for x in p[2:])
        if p[0]=='flower':
            assert a.placements[p[1]][2:5]==p[2:5]
            assert a.placement_orientations[str(i)]['offset_crown_identity']==0
        if a.placement_orientations[str(i)].get('axis_role')=='panicle_lateral':
            assert a.placement_paths[str(i)][0]==pytest.approx(a.placements[p[1]][2:5],abs=.0001)
    assert len(a.placements)<1500

def test_lod_detail_preserve_photosynthetic_counts_and_phase_metrics():
    for age in (180,360,450,540,720):
        samples=[grown(age,l,d)[1] for l in (0,1,2) for d in (False,True)]
        for key in ('estimated_leaf_count','leaf_area_m2','retained_dead_leaf_count',
                    'flower_count','mother_living_fraction','structural_axis_length_m'):
            assert len({s.stats[key] for s in samples})==1
        a=samples[0]
        assert a.stats['estimated_leaf_count']==sum(c['estimated_leaf_count'] for c in a.leaf_clusters)
        assert a.stats['leaf_area_m2']==pytest.approx(sum(c['leaf_area_m2'] for c in a.leaf_clusters),abs=1e-5)

def test_unknown_reproduction_preserves_vegetative_colony():
    for field,value in [('reproductive_mode','other_unknown'),('plant_flowering_position','other_unknown'),
                        ('plant_reproductive_structure','other_unknown')]:
        e=entity();e[field]=value;_,a=grown(age=720,e=e)
        assert a.stats['flower_count']==0 and a.stats['mother_living_fraction']==1.

def test_delayed_clock_shifts_onset_and_changes_fingerprint():
    e=entity();p=e['plant_shoot_profile']['monocarpic_cycle']
    for k in ('stalk_start_units','bloom_start_units','bloom_end_units','mother_dead_units','stalk_retention_end_units'):p[k]+=3.
    s,a=grown(e=e);t,b=grown()
    assert a.stats['flower_count']==0 and b.stats['flower_count']==200
    assert s.blueprint.fingerprint()!=t.blueprint.fingerprint()
