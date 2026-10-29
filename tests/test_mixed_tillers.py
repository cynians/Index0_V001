"""Selected fertile culms must leave an independent, canonical leafy base."""
import json,math
from pathlib import Path
from types import SimpleNamespace
import pytest,pygame
from simulations.species.mixed_tillers import mixed_tiller_profile
from simulations.species.species_simulation import SpeciesSimulation
from simulations.species.plant_assets import PlantBlueprint,PlantGrowthSnapshot
from simulations.species.species_renderer import SpeciesRenderer,DiagnosticCamera,TopDownDiagnosticCamera
from tools.author_plant_species import validate_updates,AuthoringError

def entity():
    return {'id':'unrelated_tufted_grass','plant_growth_form':'graminoid',
        'plant_growth_behaviour':'tussock_tillering','plant_woodiness':'herbaceous',
        'plant_lifespan':'short_lived_perennial','leaf_phenology':'evergreen',
        'plant_reproductive_structure':'spike','leaf_arrangement':'distichous',
        'reproductive_mode':'sexual','mature_height':{'max_m':.9},'maturity_rate':'fast',
        **json.loads(Path('assets/species_trait_specs/spec_lolium_perenne.json').read_text())['updates']}
def grown(e=None,age=177.75,lod=2,detail=False):
    s=SpeciesSimulation(species_entity=e or entity(),seed=303)
    return s,s.generate_snapshot(age,lod,detail)

@pytest.mark.parametrize('key,value',[('tiller_count',0),('tiller_count',65),('tiller_count',True),
    ('tiller_count',2.5),('reproductive_fraction',1.1),('leaf_width_m',float('nan')),
    ('culm_radius_m',float('inf')),('elongation_duration_units',0)])
def test_invalid_profiles(key,value):
    p=entity()['plant_shoot_profile'];p[key]=value
    assert mixed_tiller_profile(p) is None
    with pytest.raises(AuthoringError):validate_updates({'plant_shoot_profile':p})

def test_canonical_mixed_population_and_connected_spikes():
    s,a=grown();_,b=grown()
    assert a.to_dict()==b.to_dict()==PlantGrowthSnapshot.from_dict(a.to_dict()).to_dict()
    assert PlantBlueprint.from_dict(s.blueprint.to_dict()).fingerprint()==s.blueprint.fingerprint()
    assert (a.stats['tiller_count'],a.stats['vegetative_tiller_count'],a.stats['reproductive_tiller_count'])==(18,14,4)
    assert a.stats['spike_count']==4 and a.stats['estimated_leaf_count']==72
    for i,p in enumerate(a.placements):
        assert -1<=p[1]<i and all(math.isfinite(v) for v in p[2:])
        if p[0]=='flower':
            assert a.placements[p[1]][2:5]==p[2:5]
            assert a.placement_orientations[str(i)]['reproductive_unit']=='whole_spike'
    for t in a.stats['tillers']:
        assert (t['culm_tip_index'] is not None)==(t['role']=='reproductive')
        assert a.placements[t['crown_index']][4]<.04

def test_reproductive_fraction_changes_tall_axes_not_leaf_area_or_geometry():
    e=entity();e['plant_shoot_profile']['reproductive_fraction']=0.;s,a=grown(e)
    e=entity();e['plant_shoot_profile']['reproductive_fraction']=1.;t,b=grown(e)
    assert a.stats['reproductive_tiller_count']==a.stats['spike_count']==0
    assert b.stats['reproductive_tiller_count']==b.stats['spike_count']==18
    def leaves(s):return [s.placement_paths[str(i)] for i,p in enumerate(s.placements) if p[0]=='leaf']
    assert leaves(a)==leaves(b)
    assert a.stats['leaf_area_m2']==b.stats['leaf_area_m2']
    assert s.blueprint.module('leaf').length_m==t.blueprint.module('leaf').length_m
    assert s.blueprint.fingerprint()!=t.blueprint.fingerprint()

def test_development_and_lod_detail_accounting():
    for age in (15,60,100,177.75):
        samples=[grown(age=age,lod=l,detail=d)[1] for l in (0,1,2) for d in (False,True)]
        for key in ('tiller_count','vegetative_tiller_count','reproductive_tiller_count','spike_count',
                    'estimated_leaf_count','leaf_area_m2','structural_axis_length_m'):
            assert len({a.stats[key] for a in samples})==1
        a=samples[0];assert a.stats['estimated_leaf_count']==sum(c['estimated_leaf_count'] for c in a.leaf_clusters)
        assert a.stats['leaf_area_m2']==pytest.approx(sum(c['leaf_area_m2'] for c in a.leaf_clusters),abs=1e-5)
    assert grown(age=60)[1].stats['reproductive_tiller_count']==0
    assert grown(age=100)[1].stats['reproductive_tiller_count']==4

def test_blades_have_physical_arc_lengths_and_distichous_directions():
    s,a=grown()
    for t in a.stats['tillers']:
        for i in t['leaf_indices']:
            path=a.placement_paths[str(i)];length=sum(math.dist(x,y) for x,y in zip(path,path[1:]))
            assert .155<length<=.201
            assert min(q[2] for q in path)>=0
        angles=[a.placements[i][5] for i in t['leaf_indices']]
        assert abs((angles[1]-angles[0])%360.-180.)<.001

@pytest.mark.parametrize('updates',[{'plant_growth_form':'forb'},{'plant_woodiness':'woody'},
    {'plant_growth_behaviour':'rhizomatous_clonal'},{'plant_reproductive_structure':'panicle'},
    {'plant_shoot_profile':{}},{'leaf_attachment_pattern':'along_stem'}])
def test_opt_in_gates(updates):
    e=entity();e.update(updates)
    assert 'mixed_tiller_version' not in PlantBlueprint.from_species_entity(e).growth

def test_whole_spike_width_and_top_projection_are_physical():
    pygame.init();pygame.display.set_mode((1,1))
    s,_=grown();r=SpeciesRenderer(SimpleNamespace(camera=None))
    side=pygame.Surface((240,240),pygame.SRCALPHA);top=side.copy()
    try:
        assert r._draw_module_asset(side,s,DiagnosticCamera(240,240,(-.1,.1,0.,.2)),
                                    'flower',(120,210),0.,1.)
        assert r._draw_module_asset(top,s,TopDownDiagnosticCamera(240,240,(-.1,.1,-.1,.1)),
                                    'flower',(120,120),0.,1.)
        assert side.get_bounding_rect().height>50
        assert side.get_bounding_rect().width<20
        assert pygame.surfarray.array_alpha(top).sum()<pygame.surfarray.array_alpha(side).sum()*.1
    finally:pygame.quit()
