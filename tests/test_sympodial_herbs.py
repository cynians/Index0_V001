"""A leafy, ascending sympodial display must stay portable and opt-in."""
from copy import deepcopy
import json
import math
from pathlib import Path

import pytest
from simulations.species.plant_assets import PlantBlueprint
from simulations.species.species_simulation import SpeciesSimulation
from simulations.species.sympodial_herbs import sympodial_herb_profile, PROFILE_RANGES
from tools.author_plant_species import validate_updates, AuthoringError

PACKET = json.loads(Path('assets/species_trait_specs/spec_erigeron_annuus.json').read_text(encoding='utf-8'))['updates']
PROFILE = PACKET['plant_shoot_profile']


def entity(**overrides):
    return {'id':'spec_unrelated_sympodial_herb','plant_growth_form':'forb',
            'plant_growth_behaviour':'determinate_sympodial','plant_woodiness':'herbaceous',
            'plant_lifespan':'annual','plant_life_form':'therophyte','maturity_rate':'fast',
            'leaf_arrangement':'alternate','leaf_attachment_pattern':'mixed',
            'plant_flowering_position':'terminal','plant_reproductive_structure':'capitulum',
            'reproductive_mode':'apomictic','mature_height':{'max_m':1.5},
            **deepcopy(PACKET), **overrides}


def sim(**overrides):
    return SpeciesSimulation(species_entity=entity(**overrides), seed=303)


def test_explicit_profile_transport_and_fingerprint_controls():
    base = PlantBlueprint.from_species_entity(entity())
    assert base.growth['sympodial_herb_version'] == 1
    assert base.module('leaf').length_m == .08
    assert base.module('flower').length_m == .026
    assert base.module('stem_section').radius_m == .0025
    for k,(lo,hi) in PROFILE_RANGES.items():
        changed = deepcopy(PROFILE)
        changed[k] = hi if changed[k] != hi else lo
        assert base.fingerprint() != PlantBlueprint.from_species_entity(entity(plant_shoot_profile=changed)).fingerprint()


@pytest.mark.parametrize('value',[None,{},'other_unknown',dict(PROFILE,main_node_count=16.5),
                                 dict(PROFILE,lateral_count=float('nan')),dict(PROFILE,stem_radius_m=0.)])
def test_invalid_or_missing_profile_is_neutral(value):
    assert sympodial_herb_profile(value) is None
    b = PlantBlueprint.from_species_entity(entity(plant_shoot_profile=value))
    assert 'sympodial_herb_version' not in b.growth


def test_authoring_rejects_out_of_bounds_recipe():
    with pytest.raises(AuthoringError, match='sympodial_herb'):
        validate_updates({'plant_shoot_profile':dict(PROFILE,heads_per_lateral=300)})


@pytest.mark.parametrize('field,value',[('plant_growth_form','tree'),('plant_woodiness','woody'),
                                     ('plant_growth_behaviour','iterative_indeterminate'),
                                     ('leaf_attachment_pattern','basal_tuft')])
def test_body_plan_gates_do_not_take_over_other_grammars(field,value):
    assert 'sympodial_herb_version' not in PlantBlueprint.from_species_entity(entity(**{field:value})).growth


def test_juvenile_has_no_flat_lateral_plate_and_leaves_are_attached():
    s = sim()
    young = s.generate_snapshot(s.mature_age_days*.32,2)
    assert young.stats['sympodial_lateral_axis_count'] == 0
    assert young.stats['basal_leaf_count'] > 0
    assert not any(p[0] == 'branch_section' for p in young.placements)
    for attachment in young.attachment_points:
        if 'leaf_placement_index' in attachment:
            leaf = young.placements[attachment['leaf_placement_index']]
            assert list(leaf[2:5]) == pytest.approx(attachment['position_m'],abs=.0001)
            if attachment['cohort'] != 'basal_leaf':
                assert leaf[2:5] == young.placements[leaf[1]][2:5]


def test_mature_axes_ascend_with_bounded_size_and_real_head_sockets():
    s = sim()
    a = s.generate_snapshot(232.5,2)
    assert 20 <= a.stats['sympodial_flower_count'] <= 50
    assert a.stats['estimated_leaf_count'] >= 30
    assert a.bounds_m[5] <= 1.54
    for index,p in enumerate(a.placements):
        parent = int(p[1])
        assert parent == -1 or 0 <= parent < index
        assert all(math.isfinite(float(v)) for v in p[2:7])
        if p[0] == 'branch_section':
            assert p[4] > a.placements[parent][4]
        if p[0] == 'flower':
            assert p[2:5] == a.placements[parent][2:5]
            assert a.placements[parent][0] == 'branch_section'
    assert a.to_dict() == s.generate_snapshot(232.5,2).to_dict()
    assert type(a).from_dict(a.to_dict()).to_dict() == a.to_dict()
    assert PlantBlueprint.from_dict(s.blueprint.to_dict()).to_dict() == s.blueprint.to_dict()


def test_zero_laterals_and_head_density_have_bounded_directional_effect():
    p = dict(PROFILE,lateral_count=0)
    low = sim(plant_shoot_profile=p).generate_snapshot(232.5,2)
    high = sim().generate_snapshot(232.5,2)
    assert low.stats['sympodial_lateral_axis_count'] == 0
    assert low.stats['sympodial_flower_count'] < high.stats['sympodial_flower_count']
    assert low.stats['structural_axis_length_m'] < high.stats['structural_axis_length_m']
    assert high.stats['leaf_area_m2'] > 0


def test_canonical_morphology_and_ecology_do_not_depend_on_lod():
    s = sim()
    snapshots=[s.generate_snapshot(232.5,lod) for lod in (0,1,2)]
    assert snapshots[0].placements == snapshots[1].placements == snapshots[2].placements
    for key in ['leaf_area_m2','estimated_leaf_count','structural_axis_length_m','sympodial_flower_count']:
        assert snapshots[0].stats[key] == snapshots[1].stats[key] == snapshots[2].stats[key]
    s.set_age(232.5)
    outcomes=[]
    for lod in (0,1,2):
        s.set_lod(lod)
        outcomes.append(s.get_ecological_outcome({'pollination_availability':0.}))
    for key in ['leaf_area_proxy','vitality','fecundity','reproductive_assurance']:
        assert outcomes[0][key] == outcomes[1][key] == outcomes[2][key]
    assert outcomes[0]['reproductive_assurance'] == 1.


def test_single_annual_season_has_distinct_bloom_fruit_and_death():
    s=sim()
    full=s.generate_snapshot(60.,2)
    bloom=s.generate_snapshot(232.5,2)
    fruit=s.generate_snapshot(365*.82,2)
    assert not any(p[0] in {'flower','fruit'} for p in full.placements)
    assert any(p[0]=='flower' for p in bloom.placements)
    assert not any(p[0]=='flower' for p in fruit.placements)
    assert any(p[0]=='fruit' for p in fruit.placements)
    assert s.life_state(366.)['phase']=='dead'
    assert s.life_state(365+232.5)['reproductive_factor']==0.


def test_seed_changes_pose_without_changing_organ_dimensions():
    a,b=sim(),SpeciesSimulation(species_entity=entity(),seed=41)
    assert a.generate_snapshot(232.5,2).placements != b.generate_snapshot(232.5,2).placements
    assert a.blueprint.module('flower').length_m == b.blueprint.module('flower').length_m
