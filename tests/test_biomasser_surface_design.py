import copy
import json
from pathlib import Path

import pytest
import numpy as np

from simulations.species.plant_assets import PlantBlueprint, PlantGrowthSnapshot
from simulations.species.species_simulation import SpeciesSimulation
from simulations.species.surface_growth import normalise_surface_profile, surface_activity
from simulations.species.surface_atmosphere import atmosphere_response, atmosphere_treatments
from simulations.biosphere.ecology import BiosphereEcology, profile_from_entity
from simulations.biosphere.soil_succession import SoilOrganicMatterField
from tools.author_plant_species import validate_updates, AuthoringError
from tools.render_surface_growth import rock_fixture
from world.world_model import WorldModel


def entity():
    updates = json.loads(Path('assets/species_trait_specs/spec_biomasser_13b.json').read_text(encoding='utf-8'))['updates']
    return {'id': 'unrelated_engineered_surface_fixture', **copy.deepcopy(updates)}


def specimen(env=None, e=None, lod=2):
    sim = SpeciesSimulation(species_entity=e or entity(), seed=303, environment=env or {})
    sim.set_lod(lod); sim.set_age(90.)
    return sim


def test_live_recipe_transport_keeps_identity_and_fungal_membership():
    world = WorldModel()
    raw = world.loader.get('spec_biomasser_13b')
    resolved = world.resolved_species_entity(raw['id'])
    for key, value in entity().items():
        if key != 'id':
            assert raw[key] == resolved[key] == value
    assert raw['parents'] == ['cladis_rim_lichens_lecanora']
    assert raw['binomial_name'] == 'Biomasser construct 13B'
    assert raw['card_color'] == '#77864b'
    assert not world.loader.plant_catalogue.is_species(raw['id'])


@pytest.mark.parametrize('index', [0, 1, 2])
def test_distinct_atmospheres_support_active_growth(index):
    profile = normalise_surface_profile(entity()['surface_growth_profile'])
    _, env = atmosphere_treatments()[index]
    assert surface_activity(profile, env)['surface_activity'] == 1.
    result = atmosphere_response(profile, env)
    assert result['atmospheric_response_status'] == 'authored_growth_envelope'
    assert result['atmospheric_inputs']['co2_partial_pressure_bar'] == pytest.approx(
        env['atmosphere_model']['surface_pressure_bar'] * env['atmosphere_model']['composition'][0]['fraction'])


def test_dormancy_preserves_cover_but_stops_growth_and_rewetting_restores_it():
    wet = atmosphere_treatments()[0][1]
    dry = atmosphere_treatments()[3][1]
    vacuum = atmosphere_treatments()[4][1]
    sims = [specimen({**rock_fixture(), **env}) for env in (wet, dry, vacuum)]
    assert sims[0].render_snapshot.placements == sims[1].render_snapshot.placements == sims[2].render_snapshot.placements
    for sim in sims[1:]:
        outcome = sim.get_ecological_outcome()
        assert outcome['surface_activity'] == outcome['potential_radial_increment_m_per_year'] == 0
        assert outcome['surface_coverage_m2'] > 0
        assert outcome['standing_biomass_kg'] > 0
    assert sims[1].get_ecological_outcome(wet)['surface_activity'] == 1


def test_history_controls_growth_size_without_inventing_survival_or_calendar_age():
    wet = atmosphere_treatments()[0][1]
    vacuum = atmosphere_treatments()[4][1]
    base = {**rock_fixture(), 'surface_initial_radius_m': .005}
    first = specimen({**base, **wet, 'surface_history': [{'years': 1, **wet}]})
    stopped = specimen({**base, **vacuum, 'surface_history': [{'years': 1, **vacuum}]})
    assert first.render_snapshot.stats['surface_radius_m'] == pytest.approx(.05)
    assert stopped.render_snapshot.stats['surface_radius_m'] == .005
    assert first.render_snapshot.stats['surface_coverage_m2'] > stopped.render_snapshot.stats['surface_coverage_m2'] > 0


def test_partial_pressures_and_temperature_are_bounded_limits_not_gas_percentages():
    profile = entity()['surface_growth_profile']
    env = atmosphere_treatments()[0][1]
    for temperature in (263.15, 323.15):
        assert atmosphere_response(profile, {**env, 'temperature_k': temperature})['atmospheric_activity'] == pytest.approx(0., abs=1e-12)
    for gas in ('CO2', 'O2'):
        other = copy.deepcopy(env)
        other['atmosphere_model']['composition'] = [r for r in other['atmosphere_model']['composition'] if r['molecule'] != gas]
        assert atmosphere_response(profile, other)['atmospheric_activity'] == 0
    low = copy.deepcopy(env); low['atmosphere_model']['surface_pressure_bar'] = .01
    assert atmosphere_response(profile, low)['atmospheric_activity'] == 0


@pytest.mark.parametrize('malformed', [None, float('nan'), float('inf'), -1, True])
def test_missing_or_malformed_pressure_is_unresolved_and_zero_is_known(malformed):
    profile = entity()['surface_growth_profile']
    result = atmosphere_response(profile, {'atmosphere_model': {'surface_pressure_bar': malformed}})
    assert result['atmospheric_activity'] == 1
    assert 'pressure_bar' in result['atmospheric_unresolved_fields']
    zero = atmosphere_response(profile, {'atmosphere_model': {'surface_pressure_bar': 0}})
    assert zero['atmospheric_activity'] == 0
    assert 'pressure_bar' not in zero['atmospheric_unresolved_fields']


def test_invalid_authored_envelopes_rejected_at_shared_authoring_boundary():
    for endpoints in ([1, 0, 2, 4], [0, 0, 2, 4], [0, 1, 2, float('nan')], ['0', 1, 2, 4], [0, True, 2, 4]):
        updates = copy.deepcopy(entity()); updates.pop('id')
        updates['surface_growth_profile']['atmospheric_tolerance']['pressure_bar'] = endpoints
        with pytest.raises(AuthoringError):
            validate_updates(updates)


def test_no_envelope_keeps_existing_hydration_response_and_no_phantom_organs():
    profile = {'hydration_response': 'pulse_overhydration_depression'}
    assert surface_activity(profile, {'thallus_hydration': .45})['surface_activity'] == 1
    assert surface_activity(profile, {'thallus_hydration': 0})['surface_activity'] == 0
    sims = [specimen(rock_fixture(), lod=lod) for lod in (0, 1, 2)]
    for sim in sims:
        stats = sim.render_snapshot.stats
        assert stats['root_length_m'] == stats['leaf_area_m2'] == stats['estimated_leaf_count'] == 0
        assert {p[0] for p in sim.render_snapshot.placements} <= {'thallus', 'apothecium'}
        assert len(sim.render_snapshot.placements) < 10000
    assert len({s.render_snapshot.stats['surface_coverage_m2'] for s in sims}) == 1
    assert len({s.get_ecological_outcome()['standing_biomass_kg'] for s in sims}) == 1
    original = sims[2]
    assert original.render_snapshot.to_dict() == specimen(rock_fixture()).render_snapshot.to_dict()
    assert PlantGrowthSnapshot.from_dict(original.render_snapshot.to_dict()).to_dict() == original.render_snapshot.to_dict()
    assert PlantBlueprint.from_dict(original.blueprint.to_dict()).fingerprint() == original.blueprint.fingerprint()


def ecology(air, with_soil=True, e=None):
    profile = profile_from_entity(e or entity())
    world = BiosphereEcology({'min_x': 0., 'max_x': 2., 'min_y': 0., 'max_y': 2.}, [profile])
    env = {'soil_moisture': .38, 'soil_fertility': 0., 'surface_solar_exposure': 1.,
           'soil_organic_matter_kg_m2': 0., 'parent_nitrogen_index': .18, 'parent_phosphorus_index': .42,
           'temperature_k': 293.15, 'runtime_default_fields': (), **air}
    world.abiotic_environment_at = lambda x, y: dict(env)
    if with_soil:
        world.soil = SoilOrganicMatterField(world.bounds, columns=8, rows=8)
    world.introduce(profile.species_id, 1., 1., .8, propagule_pressure=.5)
    return world, profile, env


def test_barren_rock_can_establish_and_accumulates_real_litter_and_organic_matter():
    wet = atmosphere_treatments()[0][1]
    world, profile, env = ecology(wet)
    assert profile.soil_organic_requirement_kg_m2 == 0
    assert world.suitability_factors(profile, env)['suitability'] > 0
    world.advance(8)
    assert sum(map(sum, world.soil.litter_rows)) > 0
    assert sum(map(sum, world.soil.organic_matter_rows)) > 0
    centres = np.arange(8)*.25+.125
    inputs = world.soil._patch_inputs(world, (8, 8), centres, centres)
    assert inputs['root'].sum() == 0
    assert inputs['fixation'].sum() == 0


def test_atmospheric_growth_and_fertility_trait_reuse_in_population_not_species_id():
    wet = atmosphere_treatments()[0][1]; vacuum = atmosphere_treatments()[4][1]
    good, profile, env = ecology(wet, with_soil=False)
    bad, _, badenv = ecology(vacuum, with_soil=False)
    assert good.suitability_factors(profile, env)['suitability'] > 0
    assert bad.suitability_factors(profile, badenv)['suitability'] == 0
    good.advance(1); bad.advance(1)
    assert good.patches[0].soil_fertility_bonus > 0
    assert bad.patches[0].soil_fertility_bonus == 0
    assert good.patches[0].soil_fertility_bonus <= profile.soil_fertility_bonus_cap


def test_authored_mass_agrees_between_portable_surface_and_population_profile():
    e = entity(); sim = specimen(rock_fixture(), e=e)
    assert profile_from_entity(e).carrying_biomass_kg_m2 == sim.blueprint.growth['surface_biomass_kg_m2'] == .8
    assert sim.get_ecological_outcome()['standing_biomass_kg'] == pytest.approx(sim.render_snapshot.stats['surface_coverage_m2']*.8)
    e['biosphere_growth_profile']['carrying_biomass_kg_m2'] = 0
    assert profile_from_entity(e).carrying_biomass_kg_m2 == 0
    assert specimen(rock_fixture(), e=e).get_ecological_outcome()['standing_biomass_kg'] == 0


def test_surface_with_unknown_hydration_still_requires_light():
    assert surface_activity(entity()['surface_growth_profile'], {'light_availability': 0})['surface_activity'] == 0


def test_generated_ground_transports_atmosphere_into_population_environment():
    from simulations.map.worldgen_substrate import WorldgenSubstrate
    air = atmosphere_treatments()[1][1]['atmosphere_model']
    source = {'heightmap_model': {'min_elevation_m': 0., 'max_elevation_m': 1.,
                                 'sample_grid': {'rows': [[0., 0.], [0., 0.]]}},
              'atmosphere_model': air}
    ground = WorldgenSubstrate(source, {'min_x': 0., 'max_x': 2., 'min_y': 0., 'max_y': 2.})
    env = ground.environment_at(1., 1.)
    assert env['atmosphere_model'] == air
    result = atmosphere_response(entity()['surface_growth_profile'], env)
    assert result['atmospheric_activity'] == 1
    assert result['atmospheric_unresolved_fields'] == ['temperature_c']
