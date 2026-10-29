"""Cushion architecture, seasonal rachis persistence and saved organ assets."""
import json
import math
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pygame
import pytest

from simulations.species.cushion_subshrubs import cushion_profile
from simulations.species.plant_assets import PlantBlueprint, PlantGrowthSnapshot
from simulations.species.species_simulation import SpeciesSimulation
from simulations.species.species_renderer import SpeciesRenderer, DiagnosticCamera, diagnostic_cell_bounds
from tools.author_plant_assets import load_manifest, render_module, PixelEditorHost, PixelArtEditorUI
from tools.author_plant_species import AuthoringError, validate_updates
from world.world_model import WorldModel
from world.plant_catalogue import PlantCatalogue

ROOT = Path(__file__).resolve().parents[1]
SID = 'spec_oxytropis_aciphylla'


def entity():
    return {'id':'spec_synthetic_cushion', **deepcopy(json.loads(
        (ROOT/f'assets/species_trait_specs/{SID}.json').read_text())['updates'])}


def grown(e=None, age=150, lod=2):
    s = SpeciesSimulation(species_entity=e or entity(), seed=303)
    s.set_lod(lod); s.set_age(age)
    return s


def persistent(s):
    snap = s.render_snapshot
    return [(p[:1] + p[2:], snap.placements[p[1]][2:5], snap.placement_paths[str(i)]) for i, p in enumerate(snap.placements)
            if snap.placement_orientations[str(i)].get('axis_role') in
            {'woody_cushion_axis', 'persistent_leaf_rachis', 'retained_leaf_rachis'}]


@pytest.mark.parametrize('age', [0, 20, 150, 260, 350, 515])
def test_bounded_deterministic_lod_and_ecology(age):
    sims = [grown(age=age, lod=i) for i in range(3)]
    for s in sims:
        snap = s.render_snapshot
        assert snap.to_dict() == grown(age=age, lod=snap.lod).render_snapshot.to_dict()
        assert len(snap.placements) < 5000
        for i, p in enumerate(snap.placements):
            assert p[1] == -1 or 0 <= p[1] < i
            assert all(math.isfinite(v) for v in p[2:7])
        for a in snap.attachment_points:
            if a.get('socket') in {'woody_cushion_axis', 'persistent_leaf_rachis', 'retained_leaf_rachis'}:
                path = snap.placement_paths[str(a['placement_index'])]
                assert math.dist(path[0], a['position_m']) < .0002
        if age == 0:
            assert snap.stats['estimated_leaf_count'] == snap.stats['leaf_area_m2'] == 0
        assert PlantGrowthSnapshot.from_dict(snap.to_dict()).to_dict() == snap.to_dict()
        assert PlantBlueprint.from_dict(s.blueprint.to_dict()).fingerprint() == s.blueprint.fingerprint()
    for key in ('estimated_leaf_count', 'leaf_area_m2', 'structural_axis_length_m', 'persistent_rachis_count'):
        assert len({s.render_snapshot.stats[key] for s in sims}) == 1
    assert sims[0].get_ecological_outcome() == sims[2].get_ecological_outcome()


def test_winter_keeps_rachises_but_removes_photosynthetic_leaf_area():
    summer, winter = grown(), grown(age=350)
    assert persistent(summer) == persistent(winter)
    assert summer.render_snapshot.stats['leaf_area_m2'] > 0
    assert winter.render_snapshot.stats['leaf_area_m2'] == 0
    assert winter.render_snapshot.stats['estimated_leaf_count'] == 0
    assert not any(p[0] == 'leaf' for p in winter.render_snapshot.placements)
    assert summer.render_snapshot.stats['cushion_flower_count'] > 0
    assert grown(age=260).render_snapshot.stats['cushion_pod_count'] > 0


def test_dimensions_and_retention_have_specific_independent_effects():
    a = entity(); b = deepcopy(a)
    b['plant_shoot_profile']['crown_radius_m'] *= 1.5
    x, y = grown(a), grown(b)
    assert x.render_snapshot.stats['estimated_leaf_count'] == y.render_snapshot.stats['estimated_leaf_count']
    def reach(s):
        return max(math.hypot(p[2], p[3]) for i,p in enumerate(s.render_snapshot.placements)
                   if s.render_snapshot.placement_orientations[str(i)].get('axis_role') == 'woody_cushion_axis')
    margin = x.blueprint.module('leaf').length_m*.6
    expected = (b['plant_shoot_profile']['crown_radius_m']-margin)/(a['plant_shoot_profile']['crown_radius_m']-margin)
    assert reach(y) == pytest.approx(reach(x)*expected, abs=.00015)
    b = deepcopy(a); b['plant_shoot_profile']['retained_rachis_fraction'] = 0.
    z = grown(b)
    assert z.render_snapshot.stats['persistent_rachis_count'] < x.render_snapshot.stats['persistent_rachis_count']
    assert z.render_snapshot.stats['leaf_area_m2'] == x.render_snapshot.stats['leaf_area_m2']
    assert not any(o.get('axis_role') == 'retained_leaf_rachis' for o in z.render_snapshot.placement_orientations.values())


@pytest.mark.parametrize('value', [True, float('nan'), -1., 1.1])
def test_invalid_profile_is_neutral_and_authoring_rejects(value):
    e = entity(); e['plant_shoot_profile']['retained_rachis_fraction'] = value
    assert cushion_profile(e['plant_shoot_profile']) is None
    assert not grown(e).blueprint.growth.get('cushion_version')
    with pytest.raises(AuthoringError): validate_updates({'plant_shoot_profile':e['plant_shoot_profile']})


def test_no_recipe_and_unrelated_body_plan_do_not_opt_in():
    e = entity(); e.pop('plant_shoot_profile')
    assert not grown(e).blueprint.growth.get('cushion_version')
    e = entity(); e['plant_growth_form'] = 'tree'
    assert not grown(e).blueprint.growth.get('cushion_version')


def test_live_save_editable_pixels_and_production_renderer():
    w = WorldModel(); e = w.resolved_species_entity(SID)
    assert PlantCatalogue.build(w.loader.entities).is_species(SID)
    assert e['parents'] == ['cladis_locoweeds_oxytropis']
    s = SpeciesSimulation(world_model=w, species_id=SID, seed=303); s.set_age(150)
    assert s.blueprint.growth['cushion_version'] == 1
    assert s.blueprint.growth['cushion_height_m'] == .074
    assert s.blueprint.growth['leaflet_count'] == 8
    assert 'max_root_depth' not in e and 'maturity_age' not in e
    pygame.init(); pygame.display.set_mode((1,1))
    m = load_manifest(ROOT/f'assets/plant_asset_specs/{SID}.json')
    assert len(m['modules']) == 5
    for module in m['modules']:
        illustration = w.loader.get(module['illustration_id'])
        editor = PixelArtEditorUI(PixelEditorHost(w.loader))
        assert editor.open(illustration['id']) and editor.begin_canvas()
        assert pygame.image.tobytes(pygame.image.load(ROOT/illustration['media_path']), 'RGBA') == pygame.image.tobytes(render_module(module), 'RGBA')
    renderer = SpeciesRenderer(SimpleNamespace(camera=DiagnosticCamera(800,650,diagnostic_cell_bounds(s.render_snapshot))))
    for mode in ('individual','top_down','editor'):
        assert s.set_active_simulation_panel_tab(mode)
        renderer.draw(pygame.Surface((1500,950)), s)
    pygame.quit()
