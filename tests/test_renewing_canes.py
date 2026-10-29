"""Cane turnover, reproductive hosts and canonical accounting."""
import copy
import json
import math
from pathlib import Path

import pytest

from simulations.species.renewing_canes import renewing_cane_profile, cane_growth_clock
from simulations.species.species_simulation import SpeciesSimulation
from simulations.species.plant_assets import PlantBlueprint
from tools.author_plant_species import validate_updates, AuthoringError


@pytest.fixture
def entity():
    # A portable fixture: no live store or species-specific runtime branch.
    p = {'form': 'renewing_canes', 'renewal_interval_model_days': 20.,
         'branching_age_model_days': 30., 'extension_model_days': 45.,
         'old_cane_fraction': .8, 'basal_radius_m': .13, 'cane_radius_m': .007,
         'arch_ratio': .52, 'lateral_length_ratio': .14, 'leaf_width_ratio': .55,
         'cluster_spread_m': .02, 'max_canes': 8, 'nodes_per_cane': 20,
         'laterals_per_cane': 12, 'nodes_per_lateral': 6, 'flowers_per_cluster': 3}
    repro = {'cycle_days': 365., 'flowering_start': .34, 'flowering_end': .56,
             'fruit_start': .48, 'fruit_ripe': .68, 'fruit_retention_end': 1.18,
             'flower_size_m': .05, 'fruit_size_m': .02, 'leaf_out_start': .18,
             'leaf_out_full': .28, 'leaf_fall_start': .74, 'leaf_fall_end': .87,
             'unripe_color': [85, 117, 48], 'ripe_color': [178, 44, 32]}
    return {'plant_growth_form': 'shrub', 'plant_growth_behaviour': 'branched_woody',
            'plant_woodiness': 'woody', 'plant_lifespan': 'perennial',
            'plant_crown_shape': 'irregular', 'plant_lateral_axis_orientation': 'mixed',
            'plant_flowering_position': 'terminal', 'reproductive_mode': 'both',
            'leaf_phenology': 'deciduous', 'leaf_arrangement': 'alternate',
            'leaf_structure': 'pinnately_compound', 'leaf_length': {'typical_m': .08},
            'mature_height': {'typical_m': 1.55}, 'plant_shoot_profile': p,
            'plant_reproductive_profile': repro}


def sim(entity):
    return SpeciesSimulation(species_id='synthetic_cane_shrub', species_entity=entity, seed=303)


def test_turnover_retires_cohorts_but_preserves_slots_and_crown(entity):
    s = sim(entity); a = s.generate_snapshot(260, 2); b = s.generate_snapshot(625, 2)
    ca, cb = a.stats['cane_cohorts'], b.stats['cane_cohorts']
    assert 1 <= len(ca) <= 8 and 1 <= len(cb) <= 8
    assert a.placements[0] == b.placements[0]
    assert b.stats['retired_cane_count'] > a.stats['retired_cane_count']
    assert {c['cane_id'] for c in ca} != {c['cane_id'] for c in cb}
    assert {c['slot']: c['base_m'] for c in ca} == {c['slot']: c['base_m'] for c in cb}
    assert any(c['stage'] == 'young' for c in cb)
    assert any(c['stage'] == 'old' for c in cb)


def test_dormancy_preserves_wood_without_new_canes_and_spring_returns(entity):
    s = sim(entity); winter = s.generate_snapshot(330, 2); later = s.generate_snapshot(390, 2)
    assert winter.stats['cane_cohorts'] == later.stats['cane_cohorts']
    axes = lambda snap: [(p[0], p[2:]) for i, p in enumerate(snap.placements)
                         if snap.placement_orientations[str(i)].get('cane_axis_role') in {'cane', 'lateral', 'twig'}]
    assert axes(winter) == axes(later)
    assert winter.stats['estimated_leaf_count'] == 0
    assert winter.stats['shrub_fruit_count'] > 0
    assert s.generate_snapshot(515, 2).stats['estimated_leaf_count'] > 0
    assert s.generate_snapshot(515, 2).stats['shrub_flower_count'] > 0


def test_only_older_laterals_bear_separate_cluster_organs(entity):
    a = sim(entity).generate_snapshot(150, 2)
    assert a.stats['shrub_flower_count'] > 0
    assert a.stats['shrub_flower_count'] % 3 == 0
    for i, p in enumerate(a.placements):
        if p[0] in {'flower', 'fruit'}:
            host = p[1]; parent = a.placements[host][1]
            assert a.placement_orientations[str(host)]['cane_axis_role'] == 'pedicel'
            assert a.placement_orientations[str(parent)]['cane_axis_role'] in {'lateral', 'twig'}
            assert a.placement_orientations[str(i)]['cane_age_model_days'] >= 30
            assert a.placements[host][2:5] == p[2:5]
    assert all(c['estimated_leaf_count'] == 1 for c in a.leaf_clusters)


def test_lod_determinism_portability_bounded_geometry(entity):
    s = sim(entity); a = s.generate_snapshot(260, 2)
    assert a.to_dict() == s.generate_snapshot(260, 2).to_dict()
    for lod in (0, 1):
        b = s.generate_snapshot(260, lod)
        for k in ('estimated_leaf_count', 'leaf_area_m2', 'structural_axis_length_m', 'shrub_fruit_count', 'cane_cohorts'):
            assert a.stats[k] == b.stats[k]
        assert b.stats['leaf_count'] < a.stats['leaf_count']
    for i, p in enumerate(a.placements):
        assert p[1] == -1 or 0 <= p[1] < i
        assert all(math.isfinite(x) for x in p[2:])
        for point in a.placement_paths.get(str(i), []):
            assert all(a.bounds_m[j*2] <= x <= a.bounds_m[j*2+1] for j, x in enumerate(point))
    assert len(a.placements) < 5000
    bp = PlantBlueprint.from_dict(json.loads(json.dumps(s.blueprint.to_dict())))
    assert bp.fingerprint() == s.blueprint.fingerprint()
    assert SpeciesSimulation(species_id='synthetic_cane_shrub', blueprint=bp, seed=303).generate_snapshot(260, 2).to_dict() == a.to_dict()


@pytest.mark.parametrize('key,value', [('max_canes', 99), ('nodes_per_cane', True),
    ('arch_ratio', math.nan), ('cane_radius_m', math.inf),
    ('flowers_per_cluster', 0), ('branching_age_model_days', 1000)])
def test_invalid_recipe_rejected(entity, key, value):
    p = copy.deepcopy(entity['plant_shoot_profile']); p[key] = value
    assert renewing_cane_profile(p) is None
    with pytest.raises(AuthoringError):
        validate_updates({'plant_shoot_profile': p})


def test_unknown_recipe_and_wrong_body_plan_preserve_existing_grammar(entity):
    for recipe in (None, {}, {'form': 'other_unknown'}):
        assert 'renewing_cane_version' not in sim({**entity, 'plant_shoot_profile': recipe}).blueprint.growth
    assert 'renewing_cane_version' not in sim({**entity, 'plant_woodiness': 'herbaceous'}).blueprint.growth
    assert cane_growth_clock(100, {}) == (100, 'continuous_unresolved_season')
    e = {**entity, 'plant_reproductive_profile': {}}
    assert sim(e).generate_snapshot(150, 2).stats['cane_growth_clock_source'] == 'continuous_unresolved_season'


def test_unrelated_opposite_leaved_shrub_and_cadence_contrast(entity):
    opposite = sim({**entity, 'leaf_structure': 'simple', 'leaf_arrangement': 'opposite'})
    a = sim(entity).generate_snapshot(150, 2); b = opposite.generate_snapshot(150, 2)
    assert b.stats['estimated_leaf_count'] == 2*a.stats['estimated_leaf_count']
    slower = copy.deepcopy(entity); slower['plant_shoot_profile']['renewal_interval_model_days'] = 40.
    c = sim(slower).generate_snapshot(625, 2)
    assert c.stats['retired_cane_count'] < sim(entity).generate_snapshot(625, 2).stats['retired_cane_count']
    assert opposite.blueprint.module('leaf').length_m == sim(entity).blueprint.module('leaf').length_m
    assert sim(slower).blueprint.fingerprint() != sim(entity).blueprint.fingerprint()


def test_production_biosim_keeps_leafless_framework_and_restores_foliage(entity):
    import pygame
    from types import SimpleNamespace
    from simulations.biosphere.biosphere_renderer import BiosphereBuilderRenderer
    from simulations.biosphere.plant_pictures import top_view
    from simulations.species.species_renderer import SpeciesRenderer
    pygame.init(); pygame.display.set_mode((1, 1))
    try:
        s = sim(entity)
        scene = SimpleNamespace(world_model=SimpleNamespace(repository_revision=0), world_units_to_meters=1.,
                                get_representative_species_simulation=lambda _: s)
        instance = {'species_id': s.species_id, 'representative_id': 'test', 'abundance': 1.,
                    'visual_scale': 1., 'variant': 0}
        renderer = BiosphereBuilderRenderer(SimpleNamespace(), species_renderer=SpeciesRenderer(SimpleNamespace(camera=None)))
        for age in (150, 341, 515):
            s.set_age(age)
            art, anchor = renderer._render_sprite_surface(scene, instance, SimpleNamespace(zoom=400., sprite_height_cap=84))
            assert art.get_bounding_rect().width > 0
            assert all(math.isfinite(x) for x in anchor)
            assert top_view(s) is not None
        assert s.render_snapshot.stats['estimated_leaf_count'] > 0
    finally:
        pygame.quit()
