"""Ground ascocarps keep physical organs, persistent colonies and stable ecology."""
import gzip
import json
import math
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pygame
import pytest

from simulations.species.plant_assets import PlantBlueprint, PlantGrowthSnapshot, is_fungal_growth_species_entity
from simulations.species.species_simulation import SpeciesSimulation
from simulations.species.species_renderer import SpeciesRenderer, DiagnosticCamera, TopDownDiagnosticCamera, diagnostic_cell_bounds
from tools.author_plant_assets import load_manifest, render_module, PixelEditorHost, PixelArtEditorUI
from world.fungal_traits import validate_fungal_profile
from world.world_model import WorldModel

ROOT = Path(__file__).resolve().parents[1]
SID = 'spec_morchella_esculenta'


def recipe():
    return json.loads((ROOT/'assets/species_trait_specs/spec_morchella_esculenta.json').read_text())['updates']['fungal_growth_profile']


def grown(age=156.95, lod=2, env=None, p=None):
    s = SpeciesSimulation(species_entity={'id': 'spec_unrelated_fixture', 'fungal_growth_profile': p or recipe()},
                          seed=303, environment=env)
    s.set_lod(lod); s.set_age(age)
    return s


def test_saved_identity_assets_and_roundtrips():
    w = WorldModel(); e = w.resolved_species_entity(SID)
    assert e['parents'] == ['cladis_true_morells_morchella']
    assert is_fungal_growth_species_entity(e, w.loader.entities)
    assert e['fungal_growth_profile'] == recipe()
    s = SpeciesSimulation(world_model=w, species_id=SID, seed=303); s.set_age(156.95)
    assert s.blueprint.module('leaf') is None
    assert s.blueprint.module('root') is None
    assert s.blueprint.growth['ground_fungal_version'] == 1
    assert PlantBlueprint.from_dict(s.blueprint.to_dict()).fingerprint() == s.blueprint.fingerprint()
    assert PlantGrowthSnapshot.from_dict(s.render_snapshot.to_dict()).to_dict() == s.render_snapshot.to_dict()
    pygame.init(); pygame.display.set_mode((1,1))
    manifest = load_manifest(ROOT/'assets/plant_asset_specs/spec_morchella_esculenta.json')
    for module in manifest['modules']:
        illustration = w.loader.get(module['illustration_id'])
        with gzip.open(ROOT/illustration['pixel_document_path'], 'rt', encoding='utf8') as f:
            assert json.load(f)['version'] == 2
        editor = PixelArtEditorUI(PixelEditorHost(w.loader))
        assert editor.open(illustration['id']) and editor.begin_canvas()
        actual = pygame.image.load(ROOT/illustration['media_path'])
        assert pygame.image.tobytes(actual,'RGBA') == pygame.image.tobytes(render_module(module),'RGBA')
    renderer = SpeciesRenderer(SimpleNamespace(camera=DiagnosticCamera(600,600,diagnostic_cell_bounds(s.render_snapshot))))
    for mode in ('individual', 'mycelium', 'top_down', 'editor', 'gallery'):
        assert s.set_active_simulation_panel_tab(mode)
        renderer.draw(pygame.Surface((1500,950)), s)
    pygame.quit()


@pytest.mark.parametrize('age', [0, 66, 123.28, 139.27, 156.95, 170, 188.88, 238.95])
def test_canonical_metrics_determinism_and_geometry(age):
    sims = [grown(age,lod) for lod in range(3)]
    assert sims[2].render_snapshot.to_dict() == grown(age).render_snapshot.to_dict()
    for key in ('colonised_soil_area_proxy_m2','estimated_fruiting_body_count',
                'canonical_mycelium_node_count','sporulating_area_proxy_m2'):
        assert len({s.render_snapshot.stats[key] for s in sims}) == 1
    assert sims[0].get_ecological_outcome() == sims[2].get_ecological_outcome()
    for s in sims:
        snap=s.render_snapshot
        assert len(snap.placements) <= 64
        for i,p in enumerate(snap.placements):
            assert p[1] == -1 or 0 <= p[1] < i
            assert all(math.isfinite(v) for v in p[2:7])
            assert p[4] < 0 if p[0] == 'mycelium' else p[4] == 0
        assert all(a['socket'] == 'soil_surface' for a in snap.attachment_points)
        assert snap.stats['fungal_substrates'] == []


def test_persistent_colony_and_environmental_gates():
    adult, resting, next_flush = grown(), grown(188.88), grown(238.95)
    assert len([p for p in adult.render_snapshot.placements if p[0]=='fruiting_body']) == 4
    assert resting.render_snapshot.stats['estimated_fruiting_body_count'] == 0
    for s in (resting,next_flush):
        assert [p for p in s.render_snapshot.placements if p[0]=='mycelium'] == [p for p in adult.render_snapshot.placements if p[0]=='mycelium']
    assert next_flush.life_state()['flush_index'] == 1
    for env in ({'fungal_moisture':0},{'fungal_fruiting_enabled':False},{'fungal_ground_substrate':'other_unknown'}):
        assert grown(env=env).render_snapshot.stats['estimated_fruiting_body_count'] == 0
    assert grown(env={'fungal_ground_substrate':'other_unknown'}).get_ecological_outcome()['vitality'] == 0
    assert adult.get_ecological_outcome()['photosynthesis_proxy'] == 0
    assert adult.get_ecological_outcome()['wood_decay_activity_proxy'] == 0


def test_independent_metric_response_and_fingerprint():
    a=grown(); p=recipe(); p['cap_height']['typical_m']=.11
    b=grown(p=p)
    for x,y in zip(a.render_snapshot.stats['fungal_bodies'],b.render_snapshot.stats['fungal_bodies']):
        assert y['cap_height_m'] > x['cap_height_m']
        assert y['stipe_length_m'] == x['stipe_length_m']
        assert y['cap_width_m'] == x['cap_width_m']
    assert a.blueprint.fingerprint() != b.blueprint.fingerprint()


@pytest.mark.parametrize('change', [
    {'substrates':['dead_hardwood']}, {'attachment':'sessile'}, {'feeding_modes':['living_tree_pathogen']},
    {'cap_height':{'min_m':.2,'typical_m':.1,'max_m':.12}},
    {'visual_calibration':{'body_count':float('nan')}},
    {'simulation_calibration':{'flush_cycle_model_days':0}},
    {'visual_calibration':{'body_count':25}},
    {'visual_calibration':{'colony_radius_m':True}},
])
def test_invalid_ground_recipes(change):
    p=recipe();p.update(deepcopy(change))
    with pytest.raises(ValueError): validate_fungal_profile(p)


def test_biosim_sprite_and_top_picture():
    from simulations.biosphere.biosphere_renderer import BiosphereBuilderRenderer
    from simulations.biosphere.plant_pictures import top_view
    pygame.init();pygame.display.set_mode((1,1))
    s=SpeciesSimulation(world_model=WorldModel(),species_id=SID,seed=303);s.set_age(156.95)
    renderer=SpeciesRenderer(SimpleNamespace(camera=None))
    scene=SimpleNamespace(world_model=SimpleNamespace(repository_revision=0),world_units_to_meters=1.,
                         get_representative_species_simulation=lambda _:s)
    item={'species_id':SID,'representative_id':'test','abundance':1.,'visual_scale':1.,'variant':0}
    art,anchor=BiosphereBuilderRenderer(SimpleNamespace(),species_renderer=renderer)._render_sprite_surface(
        scene,item,SimpleNamespace(zoom=400.,sprite_height_cap=84))
    assert pygame.mask.from_surface(art).count() > 0
    assert all(math.isfinite(v) for v in anchor)
    assert top_view(s) is not None
    pygame.quit()


def test_renderer_retains_independent_cap_and_stipe_dimensions():
    from simulations.species.fungal_visuals import _sprite
    pygame.init();pygame.display.set_mode((1,1))
    source=pygame.Surface((10,20),pygame.SRCALPHA)
    source.fill((255,0,0,255),(0,0,10,10))
    source.fill((255,255,255,255),(3,10,4,10))
    module=SimpleNamespace(attachment_point=(.5,1.),visual={'cap_join_fraction':.5})
    sim=SimpleNamespace(blueprint=SimpleNamespace(module=lambda _:module,
        growth={'fungal_growth_profile':{}}))
    renderer=SimpleNamespace(_module_asset=lambda *_:source,_projection_pixels_per_meter=lambda _:1000.)
    for cap,stem,diameter in ((.06,.04,.01),(.09,.04,.01),(.06,.07,.02)):
        screen=pygame.Surface((240,240),pygame.SRCALPHA)
        assert _sprite(renderer,screen,sim,None,'fruiting_body',(120,220),.04,
                       height_m=cap+stem,cap_height_m=cap,stipe_width_m=diameter)
        red=pygame.mask.from_threshold(screen,(255,0,0,255),(1,1,1,1)).get_bounding_rects()[0]
        white=pygame.mask.from_threshold(screen,(255,255,255,255),(1,1,1,1)).get_bounding_rects()[0]
        assert (red.width,red.height)==(40,round(cap*1000))
        assert (white.width,white.height)==(round(diameter*1000),round(stem*1000))
        assert red.bottom==white.top
    pygame.quit()
