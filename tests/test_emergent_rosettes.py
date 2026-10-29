"""Emergent aquatic organs stay attached, metric, portable and LOD independent."""
import math
from types import SimpleNamespace

import pygame
import pytest

from simulations.species.emergent_rosettes import emergent_rosette_profile, planar_blade_bounds
from simulations.species.floating_leaves import draw_planar_leaf
from simulations.species.plant_assets import PlantBlueprint, PlantGrowthSnapshot
from simulations.species.species_simulation import SpeciesSimulation
from simulations.species.species_renderer import (SpeciesRenderer, DiagnosticCamera,
    TopDownDiagnosticCamera, IsometricDiagnosticCamera)
from tools.author_plant_species import validate_updates, AuthoringError
from tools.render_species_views import stage_ages


def profile(**changes):
    return {'form':'emergent_rosette', 'petiole_length_m':.68, 'peduncle_length_m':.38,
            'petiole_spread':.42, 'blade_elevation_deg':35, 'blade_width_ratio':.65,
            'petiole_radius_m':.006, 'sediment_depth_m':.06, 'leaf_count':7,
            'fruit_peduncle_drop':.94, **changes}


def aquatic(**changes):
    return {'id':'synthetic_emergent', 'plant_growth_form':'aquatic',
            'plant_growth_behaviour':'rhizomatous_clonal', 'plant_lifespan':'perennial',
            'plant_life_form':'hydrophyte', 'plant_woodiness':'herbaceous',
            'mature_height':{'max_m':1.3}, 'root_architecture':'adventitious',
            'leaf_attachment_pattern':'basal_rosette', 'leaf_length':{'typical_m':.30},
            'plant_reproductive_structure':'spike', 'reproductive_mode':'both',
            'plant_shoot_profile':profile(), **changes}


def simulation(entity=None, seed=303, age=180, lod=2):
    sim = SpeciesSimulation(species_entity=entity or aquatic(), seed=seed)
    sim.set_lod(lod)
    sim.set_age(age)
    return sim


@pytest.mark.parametrize('key,value', [('petiole_length_m',0), ('leaf_count',25),
    ('leaf_count',3.5), ('petiole_spread',True), ('blade_elevation_deg',float('nan')),
    ('petiole_radius_m',float('inf')), ('fruit_peduncle_drop',-1), ('sediment_depth_m',.8)])
def test_profile_and_authoring_reject_invalid_recipe(key, value):
    bad = profile(**{key:value})
    assert emergent_rosette_profile(bad) is None
    with pytest.raises(AuthoringError):
        validate_updates({'plant_shoot_profile':bad})


def test_zero_missing_and_unknown_profiles_are_neutral_and_fingerprinted():
    zero = profile(petiole_spread=0, blade_elevation_deg=0, sediment_depth_m=0, fruit_peduncle_drop=0)
    assert emergent_rosette_profile(zero)['petiole_spread'] == 0
    assert emergent_rosette_profile({}) is None
    assert emergent_rosette_profile({'form':'other_unknown'}) is None
    assert emergent_rosette_profile({'form':'emergent_rosette'}) is None
    validate_updates({'plant_shoot_profile':zero})
    for missing in ({}, {'form':'other_unknown'}):
        sim = simulation(aquatic(plant_shoot_profile=missing))
        assert sim.blueprint.growth.get('aquatic_rosette_version')
        assert not sim.blueprint.growth.get('emergent_rosette_version')
        assert all(p[4] == 0 for p in sim.render_snapshot.placements if p[0]=='leaf')
    first = simulation().blueprint
    changed = simulation(aquatic(plant_shoot_profile=zero)).blueprint
    assert first.fingerprint() != changed.fingerprint()


def test_raised_blades_have_connected_stalks_and_orthonormal_frames():
    sim = simulation()
    snap = sim.render_snapshot
    assert snap.stats['emergent_leaf_count'] == 7
    for index, p in enumerate(snap.placements):
        assert p[1] == -1 or 0 <= p[1] < index
        assert all(math.isfinite(v) for v in p[2:7])
        if p[0] not in {'leaf','flower'}: continue
        stalk = snap.placements[p[1]]
        assert stalk[0] == 'stem_section'
        assert p[2:5] == stalk[2:5]
        assert snap.placement_paths[str(p[1])][-1] == p[2:5]
        assert p[4] > 0
        if p[0] == 'leaf':
            frame = snap.placement_orientations[str(index)]
            assert frame['planar_leaf']
            f, n = frame['forward'], frame['normal']
            assert sum(a*b for a,b in zip(f,n)) == pytest.approx(0)
            assert math.sqrt(sum(v*v for v in f)) == pytest.approx(1)
            assert math.sqrt(sum(v*v for v in n)) == pytest.approx(1)
            corners = planar_blade_bounds(p[2:5], frame, .3*p[6], .65)
            assert max(c[2] for c in corners) <= sim.blueprint.growth['max_height_m']
    for socket in snap.attachment_points:
        if socket.get('side') == 'emergent':
            assert socket['position_m'] == snap.placements[socket['leaf_placement_index']][2:5]
    assert sim.blueprint.module('stem_section').radius_m == .006


def test_petioles_growth_and_blade_dimensions_have_ordered_effects():
    short = simulation(aquatic(plant_shoot_profile=profile(petiole_length_m=.3)))
    tall = simulation(aquatic(plant_shoot_profile=profile(petiole_length_m=.8)))
    def mean_leaf_z(sim):
        leaves = [p[4] for p in sim.render_snapshot.placements if p[0]=='leaf']
        return sum(leaves)/len(leaves)
    assert mean_leaf_z(short) < mean_leaf_z(tall)
    small = simulation(aquatic(leaf_length={'typical_m':.15}))
    large = simulation(aquatic(leaf_length={'typical_m':.3}))
    assert large.render_snapshot.stats['leaf_area_m2'] == pytest.approx(
        small.render_snapshot.stats['leaf_area_m2']*4, abs=1e-5)
    young = simulation(age=11.25)
    assert young.render_snapshot.stats['estimated_leaf_count'] < 7
    assert young.render_snapshot.stats['leaf_area_m2'] < large.render_snapshot.stats['leaf_area_m2']
    assert not any(p[0]=='flower' for p in young.render_snapshot.placements)


def test_canonical_metrics_ecology_and_roundtrip_are_lod_stable():
    sims = [simulation(lod=lod) for lod in (0,1,2,2)]
    assert sims[2].render_snapshot.to_dict() == sims[3].render_snapshot.to_dict()
    assert simulation(seed=404).render_snapshot.placements != sims[2].render_snapshot.placements
    for key in ('estimated_leaf_count','leaf_area_m2','root_depth_m','root_length_m','structural_axis_length_m'):
        assert len({s.render_snapshot.stats[key] for s in sims}) == 1
    assert all(s.get_ecological_outcome() == sims[0].get_ecological_outcome() for s in sims)
    for sim in sims:
        assert {'leaf','flower','fruit'} <= sim.render_snapshot.modules.keys()
        assert PlantGrowthSnapshot.from_dict(sim.render_snapshot.to_dict()).to_dict() == sim.render_snapshot.to_dict()
    bp = sims[2].blueprint
    assert PlantBlueprint.from_dict(bp.to_dict()).fingerprint() == bp.fingerprint()
    assert sims[2].render_snapshot.stats['root_depth_source'] == 'runtime_default'


def test_unrelated_synthetic_small_emergent_clump_and_unknown_reproduction():
    entity = aquatic(id='synthetic_small_stoloniferous', plant_growth_behaviour='stoloniferous_clonal',
                     mature_height={'max_m':.25}, leaf_length={'typical_m':.07},
                     reproductive_mode='other_unknown', plant_reproductive_structure='other_unknown',
                     plant_shoot_profile=profile(petiole_length_m=.12, leaf_count=3,
                                                petiole_spread=0, blade_elevation_deg=75))
    sim = simulation(entity)
    assert sim.render_snapshot.stats['emergent_leaf_count'] == 3
    assert not any(p[0] in {'flower','fruit'} for p in sim.render_snapshot.placements)
    assert sim.render_snapshot.bounds_m[5] < .25
    assert sim.blueprint.growth.get('emergent_rosette_version')
    assert not simulation(aquatic(plant_growth_form='forb')).blueprint.growth.get('emergent_rosette_version')


def test_seasonal_reproductive_stalk_bends_on_fruiting_and_viewer_selects_bloom():
    recipe = {'cycle_days':365, 'flowering_start':.25, 'flowering_end':.5,
              'fruit_start':.45, 'fruit_ripe':.7, 'fruit_retention_end':.85,
              'flower_size_m':.18, 'fruit_size_m':.045,
              'unripe_color':[107,142,52], 'ripe_color':[88,110,44]}
    entity = aquatic(plant_reproductive_profile=recipe)
    bloom = simulation(entity, age=128)
    ripe = simulation(entity, age=255.5)
    flowers = [p for p in bloom.render_snapshot.placements if p[0]=='flower']
    fruits = [p for p in ripe.render_snapshot.placements if p[0]=='fruit']
    assert len(flowers) == len(fruits) == 2
    assert not any(p[0]=='flower' for p in ripe.render_snapshot.placements)
    assert max(p[4] for p in fruits) < min(p[4] for p in flowers)
    assert max(p[4] for p in fruits) < .04
    stages = stage_ages(ripe)
    actual = simulation(entity, age=next(age for name,age in stages if name=='Flowering'))
    assert any(p[0]=='flower' for p in actual.render_snapshot.placements)
    assert not any(p[0]=='fruit' for p in actual.render_snapshot.placements)


@pytest.mark.parametrize('camera_type', [DiagnosticCamera,TopDownDiagnosticCamera,IsometricDiagnosticCamera])
def test_renderer_projects_tilted_blades_and_clips_extreme_zoom(camera_type):
    pygame.init(); pygame.display.set_mode((1,1))
    sim = simulation()
    bounds = (-1,1,-1,1,-.7,1.3) if camera_type is IsometricDiagnosticCamera else (-1,1,-1,1)
    camera = camera_type(500,500,bounds)
    canvas = pygame.Surface((500,500),pygame.SRCALPHA)
    renderer = SpeciesRenderer(SimpleNamespace(camera=None))
    renderer._draw_individual(canvas,sim,camera=camera,cache=False)
    assert canvas.get_bounding_rect().width > 0
    blade = pygame.Surface((75,75),pygame.SRCALPHA)
    pygame.draw.polygon(blade,(50,110,60),[(37,3),(15,68),(37,54),(60,68)])
    frame = next(f for f in sim.render_snapshot.placement_orientations.values() if f.get('planar_leaf'))
    draw_planar_leaf(canvas,blade,camera,(0,0,.4),frame['forward'],frame['normal'],10000,(.5,.72))
    # Edge-on leaves collapse, rather than retaining a camera-facing blade.
    edge = pygame.Surface((200,200),pygame.SRCALPHA)
    draw_planar_leaf(edge,blade,DiagnosticCamera(200,200,(-1,1,-1,1)),
                     (0,0,0),(1,0,0),(0,0,1),.3,(.5,.72))
    assert edge.get_bounding_rect().height <= 2
    empty = pygame.Surface((200,200),pygame.SRCALPHA)
    for f,n in [((0,0,0),(0,0,1)),((1,0,0),(1,0,0)),((float('nan'),0,0),(0,0,1))]:
        draw_planar_leaf(empty,blade,camera,(0,0,0),f,n,.3,(.5,.72))
    assert empty.get_bounding_rect().width == 0
    pygame.quit()


def test_normal_application_camera_keeps_raised_blade_at_its_stalk_socket():
    from engine.camera import Camera
    pygame.init(); pygame.display.set_mode((1,1))
    camera = Camera(500,500)
    camera.zoom = 150
    blade = pygame.Surface((75,75),pygame.SRCALPHA)
    pygame.draw.ellipse(blade,(50,110,60),(15,3,45,68))
    canvas = pygame.Surface((500,500),pygame.SRCALPHA)
    draw_planar_leaf(canvas,blade,camera,(0,0,.8),(1,0,0),(0,0,1),.3,(.5,.72))
    rect = canvas.get_bounding_rect()
    stalk_socket = camera.world_to_screen((0,-.8))
    assert rect.centery == pytest.approx(stalk_socket[1],abs=2)
    assert rect.bottom < camera.world_to_screen((0,0))[1]
    pygame.quit()
