"""Metric fern hierarchy, connected pinnules and concealed rhizomes."""
from copy import deepcopy
import gzip
import json
import math
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import pygame
import pytest

from world.world_model import WorldModel
from simulations.species.plant_assets import PlantBlueprint,PlantGrowthSnapshot
from simulations.species.species_renderer import SpeciesRenderer,DiagnosticCamera,TopDownDiagnosticCamera,canopy_visible_indices,frond_pinna_world_geometry
from simulations.species.species_simulation import SpeciesSimulation
from simulations.biosphere.biosphere_renderer import BiosphereBuilderRenderer
from tools.author_plant_assets import PixelEditorHost,load_manifest,render_module
from tools.render_species_views import stage_ages
from ui.pixel_art_editor_ui import PixelArtEditorUI


@pytest.fixture(scope='module')
def world():return WorldModel()


@pytest.fixture(scope='module')
def entity(world):return world.resolved_species_entity('spec_pteridium_aquilinum')


def grown(e,lod=2):
    s=SpeciesSimulation(species_entity=e,seed=303);s.set_lod(lod);s.set_age(s.mature_age_days);return s


def test_identity_field_transport_and_hierarchy_units(world,entity):
    assert world.loader.plant_catalogue.is_leaf_species(entity['id'])
    assert entity['parents']==['cladis_brackens_pteridium']
    payload=json.loads(Path('assets/species_trait_specs/spec_pteridium_aquilinum.json').read_text())['updates']
    assert all(world.loader.get(entity['id'])[k]==entity[k]==v for k,v in payload.items())
    s=grown(entity);module=s.blueprint.module('leaf')
    assert module.length_m==1.8
    assert module.visual['visual_unit']=='pinnule'
    assert module.visual['depicted_size_m']==.015
    assert module.visual['leaflet_length_m']==.015
    assert module.visual['leaflet_width_m']==.004
    assert s.blueprint.growth['frond_pinna_arrangement']=='opposite'
    assert s.blueprint.growth['leaf_arrangement']=='alternate'
    assert entity['seed_size_class']==entity['salinity_tolerance']==entity['mycorrhizal_type']==entity['longevity_class']=='other_unknown'
    assert all(k not in entity for k in ('plant_flower_module_ref','plant_fruit_module_ref','maturity_age','longevity','temperature_range','frost_tolerance','soil_ph_range'))


def test_canonical_lod_and_deterministic_metric_frond_paths(entity):
    keys=('canonical_frond_count','estimated_primary_pinna_count','estimated_leaf_count','leaf_area_m2',
          'root_depth_m','root_length_m','root_segment_count','rhizome_axis_length_m','rhizome_rooting_node_count')
    sims=[grown(entity,lod) for lod in (0,1,2)]
    assert len({tuple(s.render_snapshot.stats[k] for k in keys) for s in sims})==1
    s=sims[-1];snap=s.render_snapshot
    assert snap.to_dict()==grown(entity).render_snapshot.to_dict()
    assert PlantBlueprint.from_dict(s.blueprint.to_dict()).fingerprint()==s.blueprint.fingerprint()
    assert PlantGrowthSnapshot.from_dict(snap.to_dict()).to_dict()==snap.to_dict()
    assert snap.stats['canonical_frond_count']==16 and snap.stats['estimated_primary_pinna_count']==256
    assert snap.stats['root_depth_source']=='authored_max_root_depth' and snap.stats['root_depth_m']==1.
    for i,p in enumerate(snap.placements):
        assert p[1]==-1 or 0<=p[1]<i
        assert all(math.isfinite(n) for n in p[2:])
        if p[0]=='leaf':
            path=snap.placement_paths[str(i)]
            length=sum(math.dist(a,b) for a,b in zip(path,path[1:]))
            assert length==pytest.approx(1.8*p[6],abs=.002)
            assert min(p[2] for p in path)>=.024


def test_real_frond_length_and_basal_pinnae_change_without_extra_leaves(entity):
    short=deepcopy(entity);short['leaf_length']={'typical_m':1.2}
    a,b=grown(short),grown(entity)
    assert a.blueprint.fingerprint()!=b.blueprint.fingerprint()
    assert a.render_snapshot.stats['estimated_leaf_count']==b.render_snapshot.stats['estimated_leaf_count']==16
    assert b.render_snapshot.bounds_m[5]>a.render_snapshot.bounds_m[5]
    assert b.get_ecological_outcome()['leaf_area_proxy']>a.get_ecological_outcome()['leaf_area_proxy']


def test_canopy_selector_conceals_rhizomes_but_preserves_live_fronds(entity):
    s=grown(entity);snap=s.render_snapshot
    visible=canopy_visible_indices(s,snap)
    axes={i for i,p in enumerate(snap.placements) if p[0]=='branch_section' and p[4]<0}
    assert len(axes)==16 and not visible & axes
    assert {i for i,p in enumerate(snap.placements) if p[0]=='leaf'}<=visible
    # The selector never deletes canonical axes, root sockets or ecology.
    assert snap.stats['rhizome_rooting_node_count']==16
    with patch.object(SpeciesRenderer,'_draw_structural_asset_path',return_value=False) as draw:
        pygame.init();pygame.display.set_mode((1,1))
        r=SpeciesRenderer(SimpleNamespace(camera=None));canvas=pygame.Surface((400,400))
        r._draw_individual(canvas,s,camera=TopDownDiagnosticCamera(400,400,(-4,4,-4,4)),cache=False)
        assert not any(call.args[2]=='branch_section' for call in draw.call_args_list)
        draw.reset_mock()
        r._draw_individual(canvas,s,camera=DiagnosticCamera(400,400,(-4,4,-2,2)),cache=False)
        assert any(call.args[2]=='branch_section' for call in draw.call_args_list)
        pygame.quit()


def test_frond_density_is_authored_bounded_and_leaves_a_missing_field_neutral(entity):
    low=deepcopy(entity);low['plant_leaf_cluster_density']={'typical':.2}
    zero=deepcopy(entity);zero['plant_leaf_cluster_density']={'typical':0.}
    missing=deepcopy(entity);missing.pop('plant_leaf_cluster_density')
    high=grown(entity).render_snapshot
    assert grown(low).render_snapshot.stats['canonical_frond_count']==5
    assert grown(zero).render_snapshot.stats['canonical_frond_count']==2
    assert grown(missing).render_snapshot.stats['canonical_frond_count']==8
    assert high.stats['canonical_frond_count']==16
    assert high.stats['root_segment_count']==448
    assert high.stats['rhizome_rooting_node_count']==high.stats['canonical_frond_count']
    assert high.stats['estimated_primary_pinna_count']==16*16
    extreme=deepcopy(entity);extreme['plant_leaf_cluster_density']={'typical':1.}
    assert grown(extreme).render_snapshot.stats['canonical_frond_count']<=24


def test_pinna_width_is_physical_and_symmetric_in_top_view():
    path=[(0.,0.,.02),(.15,.4,.6),(.4,1.,.85)]
    base,left=frond_pinna_world_geometry(path,.6,-1.,.5,.3)
    _,right=frond_pinna_world_geometry(path,.6,1.,.5,.3)
    assert left[2]<base[2]<right[2]
    assert math.dist(left,right)==pytest.approx(1.)
    camera=TopDownDiagnosticCamera(800,800,(-2.,2.,-2.,2.))
    left_px,right_px=camera.world_to_screen_3d(left),camera.world_to_screen_3d(right)
    assert math.dist(left_px,right_px)==pytest.approx(camera.scale*math.sqrt(1-.24**2),abs=2.)


def test_biosim_fern_sprite_keeps_a_visible_canopy_at_ordinary_size(entity):
    s=grown(entity)
    pygame.init();pygame.display.set_mode((1,1))
    renderer=BiosphereBuilderRenderer(SimpleNamespace(),species_renderer=SpeciesRenderer(SimpleNamespace(camera=None)))
    scene=SimpleNamespace(world_model=SimpleNamespace(repository_revision=0),world_units_to_meters=1.,
        get_representative_species_simulation=lambda _rid:s)
    instance={'species_id':s.species_id,'representative_id':'test','abundance':1.,
              'visual_scale':1.,'variant':0}
    art,anchor=renderer._render_sprite_surface(scene,instance,SimpleNamespace(zoom=400.,sprite_height_cap=84))
    assert art.get_width()<=96 and 20<art.get_height()<=84
    assert 0<=anchor[0]<=art.get_width()
    assert anchor[1]==art.get_height()-1
    pygame.quit()


def test_generic_subterranean_axis_selection_and_neutral_missing_storage(entity):
    s=grown(entity)
    snap=deepcopy(s.render_snapshot)
    s.blueprint.growth['belowground_storage']=[]
    axes={i for i,p in enumerate(snap.placements) if p[0]=='branch_section'}
    assert axes<=canopy_visible_indices(s,snap)
    other=deepcopy(entity);other['id']='unrelated_rhizomatous_fern_fixture';other['parents']=[]
    b=grown(other)
    assert b.render_snapshot.stats['rhizome_frond_distribution']=='spaced_sockets'
    assert not {i for i,p in enumerate(b.render_snapshot.placements) if p[0]=='branch_section'} & canopy_visible_indices(b,b.render_snapshot)


def test_species_editor_top_panel_uses_canopy_selection(entity):
    s=grown(entity);pygame.init();pygame.display.set_mode((1,1))
    r=SpeciesRenderer(SimpleNamespace(camera=None));panel=pygame.Surface((400,400))
    camera=TopDownDiagnosticCamera(400,400,(-4,4,-4,4))
    with patch.object(r,'_draw_individual') as draw:
        r._draw_editor_plant_panel(panel,s,camera,top_down=True)
        assert draw.call_args.kwargs['visible_indices']==canopy_visible_indices(s,s.render_snapshot)
        assert not any(s.render_snapshot.placements[i][0]=='branch_section' for i in draw.call_args.kwargs['visible_indices'])
        r._draw_editor_plant_panel(panel,s,camera,top_down=False)
        assert draw.call_args.kwargs['visible_indices'] is None
    pygame.quit()


@pytest.mark.parametrize('sid',['spec_pteridium_aquilinum','spec_ptisana_howeana'])
def test_pinnule_glyph_direction_follows_its_supporting_axis(world,sid):
    s=grown(world.resolved_species_entity(sid));snap=s.render_snapshot
    i,p=max(((i,p) for i,p in enumerate(snap.placements) if p[0]=='leaf'),key=lambda x:x[1][6])
    # Use a high-resolution frond to inspect directions rather than aliasing.
    camera=DiagnosticCamera(1800,1800,(-1,1,-1,1))
    r=SpeciesRenderer(SimpleNamespace(camera=None));pygame.init();pygame.display.set_mode((1,1))
    axis=[None];checked=[]
    original=pygame.draw.line
    def line(surface,color,a,b,*args,**kwargs):
        axis[0]=(a,b);return original(surface,color,a,b,*args,**kwargs)
    def glyph(screen,sim,camera,kind,base,rotation,scale,**kwargs):
        if axis[0]:
            a,b=axis[0];dx,dy=b[0]-a[0],b[1]-a[1];length=math.hypot(dx,dy)
            if length>6:
                direction=(-math.sin(math.radians(rotation)),-math.cos(math.radians(rotation)))
                if sid=='spec_pteridium_aquilinum' and math.dist(a,base)<1.5:
                    checked.append((direction[0]*dx+direction[1]*dy)/length)
                elif sid=='spec_ptisana_howeana':
                    # Its direct second-order pinnules sweep forward along
                    # their primary pinna, on both sides of that axis.
                    checked.append((direction[0]*dx+direction[1]*dy)/length)
        return True
    with patch('pygame.draw.line',side_effect=line),patch.object(r,'_draw_module_asset',side_effect=glyph):
        r._draw_fallback_leaf(pygame.Surface((1800,1800)),s,camera,snap,i,r._placement_screen(camera,p),p[5],p[6])
    if sid=='spec_pteridium_aquilinum':assert checked and min(checked)>.97
    else:assert checked and min(checked)>.35
    pygame.quit()


def test_pixel_studio_reopens_original_asset_at_native_grid(world):
    pygame.init();pygame.display.set_mode((1,1))
    manifest=load_manifest(Path('assets/plant_asset_specs/spec_pteridium_aquilinum.json'));m=manifest['modules'][0]
    row=world.get_entity(m['illustration_id'])
    assert row['parents']==['spec_pteridium_aquilinum']
    editor=PixelArtEditorUI(PixelEditorHost(world.loader));assert editor.open(row['id'])
    sprite=pygame.image.load(row['media_path']);assert sprite.get_size()==(75,75)
    assert pygame.image.tobytes(sprite,'RGBA')==pygame.image.tobytes(render_module(m),'RGBA')
    with gzip.open(row['pixel_document_path'],'rt') as stream:assert json.load(stream)['version']==2
    pygame.quit()


def test_fern_stage_labels_do_not_invent_flowering(entity):
    s=grown(entity)
    assert 'Flowering' not in [name for name,_ in stage_ages(s)]
    assert not any(p[0] in {'flower','fruit'} for p in s.render_snapshot.placements)
