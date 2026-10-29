"""Petiolate basal foliage and tiny panicle organs retain physical structure."""
from copy import deepcopy
import json
import math
from pathlib import Path
import pygame
import pytest
from simulations.species.plant_assets import PlantBlueprint
from simulations.species.species_simulation import SpeciesSimulation
from simulations.species.paniculate_rosettes import paniculate_rosette_profile,RANGES,COUNTS
from tools.author_plant_species import validate_updates,AuthoringError

UPDATES=json.loads(Path('assets/species_trait_specs/spec_oxyria_digyna.json').read_text(encoding='utf-8'))['updates']
PROFILE=UPDATES['plant_shoot_profile']

def entity(**overrides):
    return {'id':'spec_unrelated_paniculate_rosette',**deepcopy(UPDATES),**overrides}

def sim(**overrides):
    return SpeciesSimulation(species_entity=entity(**overrides),seed=303)

def axis_geometry(snapshot):
    return [(p[0],p[2:],snapshot.placement_paths.get(str(i))) for i,p in enumerate(snapshot.placements)
            if snapshot.placement_orientations.get(str(i),{}).get('axis_role') not in {None,'petiole'}]

def test_portable_profile_metric_blade_and_control_fingerprints():
    bp=PlantBlueprint.from_species_entity(entity())
    assert bp.growth['paniculate_rosette_version']==1
    assert bp.module('leaf').length_m==.025
    assert bp.module('stem_section').radius_m==.0009
    assert bp.module('flower').length_m==.0025
    assert bp.module('fruit').length_m==.0045
    for k,(lo,hi) in {**RANGES,**COUNTS}.items():
        p=deepcopy(PROFILE);p[k]=hi if p[k]!=hi else lo
        if k=='panicle_length_m':p[k]=.20
        assert bp.fingerprint()!=PlantBlueprint.from_species_entity(entity(plant_shoot_profile=p)).fingerprint()
    assert PlantBlueprint.from_dict(bp.to_dict()).to_dict()==bp.to_dict()

@pytest.mark.parametrize('value',[None,{},'other_unknown',dict(PROFILE,leaf_count=3.5),
                                 dict(PROFILE,petiole_length_m=float('nan')),
                                 dict(PROFILE,panicle_length_m=.26)])
def test_unknown_or_invalid_recipe_never_selects_grammar(value):
    assert paniculate_rosette_profile(value) is None
    assert 'paniculate_rosette_version' not in PlantBlueprint.from_species_entity(entity(plant_shoot_profile=value)).growth

def test_authoring_rejects_invalid_display_controls():
    with pytest.raises(AuthoringError,match='paniculate_rosette'):
        validate_updates({'plant_shoot_profile':dict(PROFILE,organs_per_cluster=100)})

def test_integral_json_numbers_are_normalized_for_bounded_loops():
    p=dict(PROFILE,lateral_raceme_count=4.0)
    assert paniculate_rosette_profile(p)['lateral_raceme_count']==4
    assert sim(plant_shoot_profile=p).generate_snapshot(178.,2).stats['paniculate_flower_count']==315

@pytest.mark.parametrize('k,v',[('plant_growth_form','tree'),('plant_woodiness','woody'),
                              ('plant_growth_behaviour','determinate_sympodial'),
                              ('leaf_attachment_pattern','mixed'),('plant_reproductive_structure','flower')])
def test_trait_gates_preserve_neighboring_body_plans(k,v):
    assert 'paniculate_rosette_version' not in PlantBlueprint.from_species_entity(entity(**{k:v})).growth

def test_laminae_have_real_long_petioles_and_panicle_organs_have_pedicels():
    s=sim();snap=s.generate_snapshot(178.,2)
    assert snap.stats['estimated_leaf_count']==22
    assert snap.stats['paniculate_shoot_count']==3
    assert snap.stats['paniculate_flower_count']==315
    for index,p in enumerate(snap.placements):
        parent=int(p[1]);assert parent==-1 or 0<=parent<index
        assert all(math.isfinite(float(v)) for v in p[2:7])
        if p[0] in {'leaf','flower','fruit'}:
            assert p[2:5]==snap.placements[parent][2:5]
            role=snap.placement_orientations[str(parent)]['axis_role']
            assert role==('petiole' if p[0]=='leaf' else 'pedicel')
        if p[0]=='leaf':
            assert math.hypot(p[2],p[3])>.01
    assert snap.bounds_m[5]<.5
    assert snap.to_dict()==s.generate_snapshot(178.,2).to_dict()
    assert type(snap).from_dict(snap.to_dict()).to_dict()==snap.to_dict()

def test_growth_bloom_fruit_and_leaf_loss_do_not_rebuild_the_fertile_axes():
    s=sim();young=s.generate_snapshot(s.mature_age_days*.25,2)
    full=s.generate_snapshot(s.mature_age_days,2)
    bloom=s.generate_snapshot(178.,2)
    fruit=s.generate_snapshot(365*.72,2)
    dormant=s.generate_snapshot(365*.975,2)
    assert young.stats['paniculate_shoot_count']==0
    assert not any(p[0] in {'flower','fruit'} for p in full.placements)
    assert sum(p[0]=='fruit' for p in fruit.placements)==315
    assert not any(p[0]=='flower' for p in fruit.placements)
    assert not any(p[0]=='leaf' for p in dormant.placements)
    assert dormant.stats['leaf_area_m2']==0
    assert axis_geometry(full)==axis_geometry(bloom)==axis_geometry(fruit)==axis_geometry(dormant)

def test_canonical_lod_ecology_and_zero_lateral_control():
    s=sim();snaps=[s.generate_snapshot(178.,lod) for lod in (0,1,2)]
    canopy=lambda snap:[p for p in snap.placements if p[0]!='root_section']
    assert canopy(snaps[0])==canopy(snaps[1])==canopy(snaps[2])
    assert all(x.stats['leaf_area_m2']==snaps[0].stats['leaf_area_m2'] for x in snaps)
    s.set_age(178.);out=[]
    for lod in (0,1,2):
        s.set_lod(lod);out.append(s.get_ecological_outcome({'pollination_availability':0.}))
    for k in ['leaf_area_proxy','vitality','fecundity','reproductive_assurance']:
        assert out[0][k]==out[1][k]==out[2][k]
    zero=sim(plant_shoot_profile=dict(PROFILE,lateral_raceme_count=0)).generate_snapshot(178.,2)
    assert zero.stats['paniculate_flower_count']<snaps[0].stats['paniculate_flower_count']
    assert zero.stats['structural_axis_length_m']<snaps[0].stats['structural_axis_length_m']

def test_dense_tiny_panicle_organs_are_drawn_at_every_socket(monkeypatch):
    from types import SimpleNamespace
    from simulations.species.species_renderer import SpeciesRenderer,DiagnosticCamera,diagnostic_cell_bounds
    pygame.init()
    try:
        s=sim();s.set_lod(2);s.set_age(178.)
        r=SpeciesRenderer(SimpleNamespace(camera=None));canvas=pygame.Surface((600,600))
        calls=[]
        original=r._draw_module_asset
        def draw(*args,**kwargs):
            if args[3]=='flower':calls.append(args[4])
            return original(*args,**kwargs)
        monkeypatch.setattr(r,'_draw_module_asset',draw)
        r._draw_individual(canvas,s,camera=DiagnosticCamera(600,600,diagnostic_cell_bounds(s.render_snapshot)),cache=False)
        assert len(calls)==315
    finally:pygame.quit()
