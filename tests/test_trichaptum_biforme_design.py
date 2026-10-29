"""Violet shelf recipe and optional fading retain canonical fungal quantities."""
import copy
import gzip
import json
import math
from pathlib import Path
from types import SimpleNamespace

import pygame
import pytest

from world.world_model import WorldModel
from world.plant_catalogue import PlantCatalogue
from world.fungal_traits import validate_fungal_profile
from tools.author_plant_species import validate_updates, AuthoringError
from tools.author_plant_assets import load_manifest, render_module, PixelEditorHost
from ui.pixel_art_editor_ui import PixelArtEditorUI
from simulations.species.plant_assets import PlantBlueprint, PlantGrowthSnapshot
from simulations.species.species_simulation import SpeciesSimulation
from simulations.species.fungal_growth import wood_test_fixture
from simulations.species.fungal_visuals import weathered_sprite
from simulations.species.species_renderer import SpeciesRenderer, DiagnosticCamera

SID = 'spec_trichaptum_biforme'


def profile():
    return json.loads(Path(f'assets/species_trait_specs/{SID}.json').read_text(encoding='utf-8'))['updates']['fungal_growth_profile']


def grown(age=90, lod=2, recipe=None, environment=None):
    sim = SpeciesSimulation(species_entity={'id': 'unrelated_fading_wood_fungus', 'fungal_growth_profile': recipe or profile()},
                            seed=303, environment=environment or wood_test_fixture())
    sim.set_lod(lod); sim.set_age(age)
    return sim


def test_live_fungal_leaf_identity_field_transport_and_no_vascular_authorship():
    w = WorldModel(); raw = w.loader.get(SID); e = w.resolved_species_entity(SID)
    assert PlantCatalogue.build(w.loader.entities, root_id='cladis_fungi').is_leaf_species(SID)
    assert not w.loader.plant_catalogue.is_species(SID)
    assert raw['parents'] == ['cladis_trichaptum']
    assert raw['binomial_name'] == 'Trichaptum biforme'
    assert raw['card_color'] == '#483a2c'
    assert raw['fungal_growth_profile'] == e['fungal_growth_profile'] == profile()
    assert not {'leaf_length', 'root_architecture', 'maturity_age', 'longevity', 'plant_lifespan'}.intersection(raw)
    sim = SpeciesSimulation(world_model=w, species_id=SID)
    assert sim.blueprint.module('leaf') is None
    assert sim.blueprint.growth['fungal_growth_profile']['resolved']['weathering_palette_version'] == 1


@pytest.mark.parametrize('bad', [[], 'violet', [{'fresh_rgb': [1, 2, 3]}],
    [{'fresh_rgb': [1, 2, True], 'weathered_rgb': [4, 5, 6]}],
    [{'fresh_rgb': [1, 2, 256], 'weathered_rgb': [4, 5, 6]}],
    [{'fresh_rgb': [1, 2, 3], 'weathered_rgb': [4, 5, 6]}]*2])
def test_invalid_weathering_palette_rejected_at_authoring_boundary(bad):
    recipe = profile(); recipe['visual_calibration']['weathering_palette'] = bad
    with pytest.raises(ValueError): validate_fungal_profile(recipe)
    with pytest.raises(AuthoringError): validate_updates({'fungal_growth_profile': recipe})


def test_palette_interpolates_without_cascade_source_mutation_or_alpha_loss():
    pygame.init()
    source = pygame.Surface((3, 1), pygame.SRCALPHA)
    source.set_at((0, 0), (100, 10, 20, 255))
    source.set_at((1, 0), (200, 20, 40, 255))
    source.set_at((2, 0), (100, 10, 20, 0))
    before = pygame.image.tobytes(source, 'RGBA')
    palette = [{'fresh_rgb': [100, 10, 20], 'weathered_rgb': [200, 20, 40]},
               {'fresh_rgb': [200, 20, 40], 'weathered_rgb': [250, 30, 60]}]
    faded = weathered_sprite(source, palette, 1)
    assert faded.get_at((0, 0)) == (200, 20, 40, 255)
    assert faded.get_at((1, 0)) == (250, 30, 60, 255)
    assert faded.get_at((2, 0)).a == 0
    assert weathered_sprite(source, palette, .5).get_at((0, 0)) == (150, 15, 30, 255)
    assert pygame.image.tobytes(weathered_sprite(source, palette, 0), 'RGBA') == before
    assert pygame.image.tobytes(source, 'RGBA') == before
    pygame.quit()


def test_weathering_changes_pixels_but_not_attachment_size_or_colonised_volume():
    pygame.init(); pygame.display.set_mode((1, 1))
    world = WorldModel(); sims = [SpeciesSimulation(world_model=world, species_id=SID, seed=303) for _ in range(2)]
    for sim, age in zip(sims, (90, 115)):
        sim.set_lod(2); sim.set_age(age)
    fresh, faded = [s.render_snapshot for s in sims]
    for first, second in zip(fresh.stats['fungal_bodies'], faded.stats['fungal_bodies']):
        for key in ('id', 'variant_key', 'socket_m', 'cap_socket_m', 'cap_width_m', 'stipe_length_m'):
            assert first[key] == second[key]
        assert first['weathering_factor'] == 0 < second['weathering_factor'] <= 1
    assert fresh.stats['colonised_wood_volume_proxy_m3'] == faded.stats['colonised_wood_volume_proxy_m3']
    body = max(fresh.stats['fungal_bodies'], key=lambda b: b['cap_width_m'])
    x,y,z = body['cap_socket_m']; cx=x+1.8*y; span=body['cap_width_m']
    camera = DiagnosticCamera(600, 250, (cx-span*1.2,cx+span*1.2,z-span*.55,z+span*.55), minimum_span_m=.001)
    renderer = SpeciesRenderer(SimpleNamespace(camera=None)); frames = []
    for sim in sims:
        canvas = pygame.Surface((600, 250), pygame.SRCALPHA)
        renderer._draw_individual(canvas, sim, camera=camera, visible_indices={body['placement_index']},
                                 clear=False, draw_environment=False, cache=False, draw_ground_line=False)
        assert canvas.get_bounding_rect().width > 100
        frames.append(pygame.image.tobytes(canvas, 'RGBA'))
    assert frames[0] != frames[1]
    pygame.quit()


def test_colour_recipe_is_reusable_and_neutral_to_canonical_growth_and_ecology():
    recipe = profile(); recipe['visual_calibration'].pop('weathering_palette')
    first, second = grown(), grown(recipe=recipe)
    assert first.render_snapshot.stats == second.render_snapshot.stats
    assert first.get_ecological_outcome() == second.get_ecological_outcome()
    assert first.blueprint.fingerprint() != second.blueprint.fingerprint()
    for key in ('estimated_fruiting_body_count', 'colonised_wood_volume_proxy_m3', 'sporulating_area_proxy_m2'):
        assert len({grown(lod=lod).render_snapshot.stats[key] for lod in range(3)}) == 1
    assert first.render_snapshot.to_dict() == grown().render_snapshot.to_dict()
    assert PlantBlueprint.from_dict(first.blueprint.to_dict()).fingerprint() == first.blueprint.fingerprint()
    assert PlantGrowthSnapshot.from_dict(first.render_snapshot.to_dict()).to_dict() == first.render_snapshot.to_dict()
    for i, p in enumerate(first.render_snapshot.placements):
        assert -1 <= p[1] < i
        assert all(math.isfinite(v) for v in p[2:])
    assert {p[0] for p in first.render_snapshot.placements} == {'mycelium', 'fruiting_body'}
    assert first.render_snapshot.stats['estimated_fruiting_body_count'] == 18


def test_wood_gate_and_between_flush_colony_are_distinct_from_bracket_life():
    env = wood_test_fixture(); env['fungal_substrates'][0]['material'] = 'dead_conifer'
    incompatible = grown(environment=env)
    assert incompatible.render_snapshot.stats['estimated_fruiting_body_count'] == 0
    assert incompatible.render_snapshot.stats['colonised_wood_volume_proxy_m3'] == 0
    for age in (90, 130, 210):
        sim = grown(age=age)
        assert sim.render_snapshot.stats['colonised_wood_volume_proxy_m3'] > 0
        assert sim.render_snapshot.stats['root_length_m'] == sim.render_snapshot.stats['leaf_area_m2'] == 0
    assert grown(age=130).render_snapshot.stats['estimated_fruiting_body_count'] == 0
    assert grown(age=210).render_snapshot.stats['estimated_fruiting_body_count'] == 18


def test_all_original_assets_reopen_as_editable_exact_manifest_pixels():
    pygame.init(); pygame.display.set_mode((1, 1))
    w = WorldModel(); manifest = load_manifest(Path(f'assets/plant_asset_specs/{SID}.json'))
    for module in manifest['modules']:
        row = w.get_entity(module['illustration_id'])
        assert row['parents'] == [SID]
        editor = PixelArtEditorUI(PixelEditorHost(w.loader)); assert editor.open(row['id'])
        saved = pygame.image.load(row['media_path'])
        assert saved.get_size() == (75, 75)
        assert pygame.image.tobytes(saved, 'RGBA') == pygame.image.tobytes(render_module(module), 'RGBA')
        with gzip.open(row['pixel_document_path'], 'rt') as stream:
            assert json.load(stream)['version'] == 2
    pygame.quit()
