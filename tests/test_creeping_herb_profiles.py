"""Portable nonclonal creeping shoots and connected seasonal pedicels."""
import json
import math
from pathlib import Path
from copy import deepcopy
import pytest
from simulations.species.creeping_herbs import creeping_herb_profile
from simulations.species.plant_assets import PlantBlueprint, PlantGrowthSnapshot
from simulations.species.species_simulation import SpeciesSimulation
from tools.author_plant_species import validate_updates, AuthoringError

def entity(**updates):
    manifest=json.loads(Path('assets/plant_asset_specs/spec_lysimachia_arvensis.json').read_text())
    return {'id':'spec_synthetic_creeping_annual', 'plant_growth_form':'forb',
            'plant_growth_behaviour':'creeping_prostrate','plant_woodiness':'herbaceous',
            'plant_lifespan':'annual','maturity_rate':'fast','plant_life_form':'therophyte',
            'mature_height':{'min_m':.06,'max_m':.5}, 'leaf_structure':'simple',
            'leaf_length':{'typical_m':.015},'leaf_clustering':'paired','leaf_arrangement':'opposite',
            'leaf_attachment_pattern':'along_stem','plant_leaf_distribution':'along_shoot',
            'plant_flowering_position':'lateral','plant_reproductive_structure':'flower',
            'root_architecture':'taproot','reproductive_mode':'sexual','clonal_spread':'none',
            **manifest['species_field_updates'],**updates}

def sim(data=None,day=137,lod=2):
    s=SpeciesSimulation(species_entity=data or entity(),seed=303)
    s.set_lod(lod);s.set_age(day)
    return s

@pytest.mark.parametrize('key,value',[('axis_length_m',math.nan),('primary_axes',True),
    ('primary_axes',9),('nodes_per_axis',33),('lateral_axes_per_primary',-1),
    ('reproductive_node_interval',0),('stem_radius_m',0),('leaf_width_m',math.inf),
    ('pedicel_length_m',.081),('fruit_recurve',1.1)])
def test_invalid_profile_is_neutral_and_authoring_rejects(key,value):
    p={**entity()['plant_shoot_profile'],key:value}
    assert creeping_herb_profile(p) is None
    with pytest.raises(AuthoringError):
        validate_updates({'plant_shoot_profile':p})
    assert sim(entity(plant_shoot_profile=p)).blueprint.fingerprint()==sim(entity(plant_shoot_profile=None)).blueprint.fingerprint()

def test_profile_gates_are_specific_and_portable():
    s=sim()
    assert s.blueprint.growth['creeping_herb_profile_version']==1
    assert PlantBlueprint.from_dict(s.blueprint.to_dict()).fingerprint()==s.blueprint.fingerprint()
    assert s.blueprint.module('leaf').radius_m==.005
    for field,value in [('plant_growth_form','shrub'),('plant_woodiness','woody'),('plant_growth_behaviour','iterative_indeterminate')]:
        assert not sim(entity(**{field:value})).blueprint.growth.get('creeping_herb_profile_version')

def test_deterministic_finite_connections_lod_and_biosphere_quantities():
    s=sim();snap=s.render_snapshot
    assert snap.to_dict()==sim().render_snapshot.to_dict()
    assert PlantGrowthSnapshot.from_dict(snap.to_dict()).to_dict()==snap.to_dict()
    assert len(snap.placements)<3000
    assert snap.stats['creeping_axis_count']==4
    assert snap.stats['creeping_secondary_axis_count']==4
    assert snap.stats['creeping_rooting_contact_count']==0
    for i,p in enumerate(snap.placements):
        assert p[1]==-1 or 0<=p[1]<i
        assert all(math.isfinite(v) and abs(v)<2 for v in p[2:5])
    for lod in (0,1):
        coarse=sim(lod=lod)
        assert coarse.get_ecological_outcome()==s.get_ecological_outcome()
        for key in ('estimated_leaf_count','leaf_area_m2','root_depth_m','creeping_flower_count'):
            assert coarse.render_snapshot.stats[key]==snap.stats[key]

def test_branch_counts_reach_and_leaf_width_have_independent_effects():
    s=sim();p=entity()['plant_shoot_profile']
    sparse=sim(entity(plant_shoot_profile={**p,'primary_axes':1,'lateral_axes_per_primary':0}))
    wide=sim(entity(plant_shoot_profile={**p,'axis_length_m':.5}))
    broad=sim(entity(plant_shoot_profile={**p,'leaf_width_m':.02}))
    assert sparse.render_snapshot.stats['estimated_leaf_count']<s.render_snapshot.stats['estimated_leaf_count']/2
    assert wide.render_snapshot.stats['creeping_footprint_radius_m']>s.render_snapshot.stats['creeping_footprint_radius_m']*1.8
    assert broad.render_snapshot.stats['leaf_area_m2']==pytest.approx(s.render_snapshot.stats['leaf_area_m2']*2)
    assert sparse.render_snapshot.stats['root_depth_m']==wide.render_snapshot.stats['root_depth_m']==s.render_snapshot.stats['root_depth_m']

def test_paired_leaf_vectors_are_opposite_and_rotate_at_successive_nodes():
    snap=sim().render_snapshot
    cohorts=snap.leaf_clusters
    for cohort in cohorts:
        indices=cohort['sample_placement_indices']
        assert len(indices)==2
        a,b=[snap.placement_orientations[str(i)]['forward'] for i in indices]
        assert a[:2]==pytest.approx([-b[0],-b[1]],abs=1e-5)
        assert a[2]>0 and b[2]>0
    angles=[snap.placements[c['sample_placement_indices'][0]][5] for c in cohorts[:2]]
    assert 60<abs((angles[1]-angles[0]+180)%360-180)<120

def test_connected_axillary_pedicels_recurve_in_fruit_and_annual_does_not_repeat():
    flower,fruit=sim(day=137),sim(day=365*.66)
    def stalks(s,kind):
        snap=s.render_snapshot
        return [(snap.placements[int(p[1])],snap.placement_paths[str(p[1])]) for p in snap.placements if p[0]==kind]
    bloom,seed=stalks(flower,'flower'),stalks(fruit,'fruit')
    assert bloom and len(bloom)==len(seed)
    assert not stalks(flower,'fruit') and not stalks(fruit,'flower')
    assert [p[1] for p,path in bloom]==[p[1] for p,path in seed]
    for p,path in bloom:
        assert p[0]=='branch_section' and path[-1][2]>path[0][2]
    for p,path in seed:
        assert path[-1][2]<path[0][2]
        assert max(q[2] for q in path)>path[0][2]
    for day in (365,502):
        dead=sim(day=day)
        assert dead.life_state()['phase']=='dead'
        assert not stalks(dead,'flower') and not stalks(dead,'fruit')
    for data in (entity(reproductive_mode='vegetative'),entity(plant_flowering_position='other_unknown'),entity(plant_reproductive_profile=None)):
        assert not stalks(sim(data),'flower')

def test_distichous_leaves_alternate_across_local_runner_without_changing_counts():
    data=entity(leaf_arrangement='distichous',leaf_clustering='solitary')
    snap=sim(data).render_snapshot
    for cohort in snap.leaf_clusters:
        leaf=cohort['sample_placement_indices'][0]
        stem=snap.placements[cohort['host_placement_index']]
        angle=snap.placements[leaf][5]
        assert abs((angle-stem[5]+180)%360-180)==pytest.approx(90)
    first=[(snap.placements[c['sample_placement_indices'][0]][5]
           -snap.placements[c['host_placement_index']][5]+180)%360-180 for c in snap.leaf_clusters[:4]]
    assert first==pytest.approx([90,-90,90,-90])
    control=sim(entity(leaf_arrangement='alternate',leaf_clustering='solitary'))
    assert snap.stats['estimated_leaf_count']==control.render_snapshot.stats['estimated_leaf_count']
    assert sim(data).blueprint.fingerprint()!=control.blueprint.fingerprint()

def test_planar_blade_frames_are_opt_in_and_keep_ecology_and_lod_stable():
    data=entity();profile={**data['plant_shoot_profile'],'planar_leaves':True}
    flat=sim(entity(plant_shoot_profile=profile));control=sim(data)
    snap=flat.render_snapshot
    assert flat.blueprint.fingerprint()!=control.blueprint.fingerprint()
    assert snap.stats['leaf_area_m2']==control.render_snapshot.stats['leaf_area_m2']
    for i,p in enumerate(snap.placements):
        if p[0]!='leaf':continue
        f=snap.placement_orientations[str(i)]
        assert f['planar_leaf'] and f['width_m']>0
        assert sum(a*b for a,b in zip(f['normal'],f['forward']))==pytest.approx(0,abs=2e-5)
    assert all(not f.get('planar_leaf') for f in control.render_snapshot.placement_orientations.values())
    for lod in (0,1):
        assert sim(entity(plant_shoot_profile=profile),lod=lod).get_ecological_outcome()==flat.get_ecological_outcome()
    for value in (1,'yes',None):
        assert creeping_herb_profile({**profile,'planar_leaves':value}) is None
