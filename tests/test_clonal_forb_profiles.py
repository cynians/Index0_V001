"""Portable clonal herb controls and seasonal terminal head reuse."""
import math
from copy import deepcopy
from types import SimpleNamespace

import pygame
import pytest

from simulations.species.clonal_forb_profiles import clonal_forb_profile
from simulations.species.capitulum_clusters import capitulum_cluster_profile, capitulum_cluster_surface
from simulations.species.plant_assets import PlantBlueprint, PlantGrowthSnapshot
from simulations.species.species_simulation import SpeciesSimulation
from simulations.species.species_renderer import SpeciesRenderer, DiagnosticCamera, top_down_diagnostic_bounds
from tools.author_plant_species import validate_updates, AuthoringError


def profile(**changes):
    return {'form':'clonal_forb', 'ramet_reach_m':.18, 'nodes_per_shoot':32,
            'stem_radius_m':.003, 'branching_start_fraction':.78, **changes}


def entity(**changes):
    return {'id':'spec_unrelated_clonal_herb', 'plant_growth_form':'forb',
        'plant_growth_behaviour':'stoloniferous_clonal', 'plant_woodiness':'herbaceous',
        'plant_lifespan':'perennial', 'clonal_spread':'moderate',
        'mature_height':{'min_m':.3,'max_m':.7}, 'leaf_length':{'typical_m':.04},
        'leaf_arrangement':'opposite', 'leaf_attachment_pattern':'along_stem',
        'plant_leaf_distribution':'along_shoot', 'reproductive_mode':'both',
        'plant_flowering_position':'terminal', 'plant_reproductive_structure':'capitulum',
        'plant_shoot_profile':profile(), 'plant_leaf_attachment_angle':.4,
        'plant_inflorescence_profile':{'form':'capitulum_cluster','unit':'capitulum',
            'length_m':.12,'width_m':.14,'head_size_m':.032,'head_count':8,
            'head_layout':'rounded','axis_color':[90,120,55]},
        'plant_reproductive_profile':{'cycle_days':365,'flowering_start':.65,
            'flowering_end':.84,'fruit_start':.79,'fruit_ripe':.88,'fruit_retention_end':1.04,
            'flower_size_m':.032,'fruit_size_m':.028,'unripe_color':[133,110,70],
            'ripe_color':[189,157,111]}, **changes}


def snapshot(data=None, day=263, lod=2):
    sim=SpeciesSimulation(species_entity=data or entity(), seed=303)
    sim.set_age(day); sim.set_lod(lod)
    return sim, sim.render_snapshot


@pytest.mark.parametrize('changes', [{'ramet_reach_m':0}, {'ramet_reach_m':float('nan')},
    {'ramet_reach_m':True}, {'nodes_per_shoot':True}, {'nodes_per_shoot':49},
    {'nodes_per_shoot':3}, {'stem_radius_m':float('inf')}, {'stem_radius_m':.1},
    {'branching_start_fraction':-1}, {'form':'unknown'}])
def test_invalid_profile_is_neutral_and_authoring_rejects_bad_clonal_form(changes):
    bad=profile(**changes)
    assert clonal_forb_profile(bad) is None
    a=PlantBlueprint.from_species_entity(entity(plant_shoot_profile=bad))
    b=PlantBlueprint.from_species_entity(entity(plant_shoot_profile=None))
    assert a.fingerprint()==b.fingerprint()
    if bad['form']=='clonal_forb':
        with pytest.raises(AuthoringError):
            validate_updates({'plant_shoot_profile':bad})


def test_profiles_require_the_supported_body_plan_and_transport_dimensions():
    bp=PlantBlueprint.from_species_entity(entity())
    assert bp.growth['clonal_forb_profile']['ramet_reach_m']==.18
    assert bp.module('stem_section').radius_m==.003
    assert bp.module('flower').length_m==.032
    assert bp.module('fruit').length_m==.028
    measured=PlantBlueprint.from_species_entity(entity(plant_shoot_profile=profile(leaf_width_m=.014)))
    assert measured.module('leaf').radius_m==.007
    assert clonal_forb_profile(profile(leaf_width_m=0)) is None
    assert PlantBlueprint.from_dict(bp.to_dict()).fingerprint()==bp.fingerprint()
    for change in ({'plant_growth_form':'tree'}, {'plant_woodiness':'woody'},
                   {'plant_growth_behaviour':'rosette_short_internode'},
                   {'leaf_attachment_pattern':'basal_rosette'}):
        assert 'clonal_forb_profile' not in PlantBlueprint.from_species_entity(entity(**change)).growth
    for change in ({'ramet_reach_m':.6}, {'nodes_per_shoot':16}, {'branching_start_fraction':1.}):
        assert bp.fingerprint()!=PlantBlueprint.from_species_entity(entity(plant_shoot_profile=profile(**change))).fingerprint()


def axes(snap):
    return [(p[0],p[2:7],snap.placements[p[1]][2:5] if p[1]>=0 else None,
             snap.placement_paths.get(str(i))) for i,p in enumerate(snap.placements)
            if p[0] in {'stem_section','branch_section'}]


def test_canonical_plant_and_ecology_are_lod_stable_deterministic_and_portable():
    sims=[snapshot(lod=lod) for lod in (0,1,2)]
    for sim,snap in sims:
        repeat,other=snapshot(lod=sim.lod)
        assert snap.to_dict()==other.to_dict()
        assert PlantGrowthSnapshot.from_dict(snap.to_dict()).to_dict()==snap.to_dict()
        assert len(snap.placements)<2000
        for i,p in enumerate(snap.placements):
            assert -1<=p[1]<i
            assert all(math.isfinite(v) for v in p[2:7])
            assert all(abs(v)<3 for v in p[2:5])
        assert sim.get_ecological_outcome()==sims[0][0].get_ecological_outcome()
        assert snap.stats['leaf_area_m2']==sims[0][1].stats['leaf_area_m2']
        assert snap.stats['estimated_leaf_count']==sims[0][1].stats['estimated_leaf_count']
        assert axes(snap)==axes(sims[0][1])
    for cohort in sims[2][1].leaf_clusters:
        development=cohort.get('leaf_development')
        if development:
            assert development['width_scale']==1.
            assert development['area_scale']==round(development['length_scale']**2,6)


def test_reach_and_nodes_have_independent_visible_responses():
    _,close=snapshot()
    _,wide=snapshot(entity(plant_shoot_profile=profile(ramet_reach_m=.6)))
    _,sparse=snapshot(entity(plant_shoot_profile=profile(nodes_per_shoot=12)))
    def radius(s):
        return max(math.hypot(p[2],p[3]) for p in s.placements if p[0]=='root_support')
    assert radius(wide)>radius(close)*2
    assert close.stats['estimated_leaf_count']>sparse.stats['estimated_leaf_count']*1.8
    assert close.stats['leaf_area_m2']>sparse.stats['leaf_area_m2']
    assert close.stats['root_depth_m']==wide.stats['root_depth_m']==sparse.stats['root_depth_m']
    _,unbranched=snapshot(entity(plant_shoot_profile=profile(branching_start_fraction=1)))
    assert sum(p[0]=='flower' for p in close.placements)>sum(p[0]=='flower' for p in unbranched.placements)


def test_terminal_heads_become_fruit_on_same_hosts_then_release():
    _,flowers=snapshot(day=263)
    _,fruits=snapshot(day=321.2)
    hosts=lambda s,kind:[s.placements[p[1]][2:5] for p in s.placements if p[0]==kind]
    assert hosts(flowers,'flower')
    assert hosts(flowers,'flower')==hosts(fruits,'fruit')
    assert not hosts(flowers,'fruit') and not hosts(fruits,'flower')
    assert axes(flowers)==axes(fruits)
    assert flowers.stats['leaf_area_m2']==fruits.stats['leaf_area_m2']
    _,released=snapshot(day=365*1.05)
    assert not hosts(released,'fruit')
    for data in (entity(reproductive_mode='other_unknown'), entity(reproductive_mode='vegetative'),
                 entity(plant_reproductive_profile=None), entity(plant_reproductive_structure='cone')):
        _,snap=snapshot(data,day=321.2)
        assert not hosts(snap,'fruit')


def test_rounded_cluster_layout_is_bounded_portable_and_changes_pixels():
    raw=entity()['plant_inflorescence_profile']
    rounded=capitulum_cluster_profile(raw)
    fan=capitulum_cluster_profile({**raw,'head_layout':'fan'})
    assert rounded['version']==2 and fan['version']==1
    with pytest.raises(AuthoringError):
        validate_updates({'plant_inflorescence_profile':{**raw,'head_layout':'invalid'}})
    assert capitulum_cluster_profile({**raw,'head_layout':'invalid'}) is None
    assert capitulum_cluster_profile({**raw,'head_layout':[]}) is None
    a,_=capitulum_cluster_surface(rounded,1000,.5)
    b,_=capitulum_cluster_surface(fan,1000,.5)
    assert pygame.image.tobytes(a,'RGBA')!=pygame.image.tobytes(b,'RGBA')
    surface,anchor=capitulum_cluster_surface(rounded,1e9,.5)
    assert max(surface.get_size())<=1024
    assert all(math.isfinite(v) for v in anchor)


def test_production_renderer_composes_flower_and_fruit_clusters_and_fits_bounds():
    pygame.init(); pygame.display.set_mode((1,1))
    renderer=SpeciesRenderer(SimpleNamespace(camera=None))
    sim,flower=snapshot()
    screen=pygame.Surface((640,480))
    camera=DiagnosticCamera(640,480,(-1,1,-.2,1))
    assert renderer._draw_module_asset(screen,sim,camera,'flower',(320,350),0,1)
    sim.set_age(321.2)
    assert renderer._draw_module_asset(screen,sim,camera,'fruit',(320,350),0,1)
    assert {key[0] for key in renderer._inflorescence_sprite_cache}=={'flower','fruit'}
    bounds=top_down_diagnostic_bounds(sim)
    radius=math.hypot(.12,.07)
    for p in sim.render_snapshot.placements:
        if p[0]=='fruit':
            assert bounds[0]<=p[2]-radius and bounds[1]>=p[2]+radius
            assert bounds[2]<=p[3]-radius and bounds[3]>=p[3]+radius
