"""Reusable short woody shoots and independently ripening persistent sepals."""
from copy import deepcopy
import json
import math
from pathlib import Path
from types import SimpleNamespace

import pygame
import pytest

from simulations.species.woody_spurs import woody_spur_profile
from simulations.species.persistent_calyces import persistent_calyx_profile, calyx_surface
from simulations.species.plant_assets import PlantBlueprint, PlantGrowthSnapshot
from simulations.species.species_simulation import SpeciesSimulation
from tools.author_plant_species import AuthoringError, validate_updates


def entity(**changes):
    data = json.loads(Path('assets/species_trait_specs/spec_ochna_serrulata.json').read_text())['updates']
    return {'id':'spec_unrelated_spur_shrub', 'type':'species', **deepcopy(data), **changes}


def sim(data=None, day=237.25, lod=2):
    result = SpeciesSimulation(species_entity=data or entity(), seed=303)
    result.set_lod(lod)
    result.set_age(day)
    return result


@pytest.mark.parametrize('key,value', [('spur_length_m',0),('fine_node_spacing_m',math.inf),
    ('leaf_width_m',math.nan),('fertile_node_interval',True),('fertile_node_interval',1.5),
    ('crown_radius_ratio',1.1),('stem_radius_m',-.1)])
def test_malformed_shoot_profiles_are_rejected_and_runtime_neutral(key,value):
    p = {**entity()['plant_shoot_profile'],key:value}
    assert woody_spur_profile(p) is None
    with pytest.raises(AuthoringError):
        validate_updates({'plant_shoot_profile':p})
    assert sim(entity(plant_shoot_profile=p)).blueprint.fingerprint() == sim(entity(plant_shoot_profile=None)).blueprint.fingerprint()


@pytest.mark.parametrize('key,value', [('max_fruitlets',True),('max_fruitlets',1.5),
    ('fruitlet_orbit_m',math.nan),('calyx_size_m',0),('calyx_ripe_color',[2,3,999]),
    ('flowering_calyx_size_m',.1)])
def test_malformed_calyx_recipes_are_rejected(key,value):
    profile = deepcopy(entity()['plant_reproductive_profile'])
    profile['persistent_calyx_display'][key] = value
    assert persistent_calyx_profile(profile['persistent_calyx_display']) is None
    with pytest.raises(AuthoringError):
        validate_updates({'plant_reproductive_profile':profile})


def test_portable_recipe_exact_transport_and_trait_gates():
    s = sim()
    assert s.blueprint.growth['woody_spur_profile'] == woody_spur_profile(entity()['plant_shoot_profile'])
    assert s.blueprint.growth['persistent_calyx_version'] == 1
    assert s.blueprint.module('leaf').length_m == .04
    assert s.blueprint.module('leaf').radius_m == .00625
    assert s.blueprint.module('calyx').length_m == .028
    assert s.blueprint.module('fruit').length_m == .00753
    assert PlantBlueprint.from_dict(s.blueprint.to_dict()).fingerprint() == s.blueprint.fingerprint()
    assert PlantGrowthSnapshot.from_dict(s.render_snapshot.to_dict()).to_dict() == s.render_snapshot.to_dict()
    for changes in ({'plant_growth_form':'forb'}, {'plant_shoot_dimorphism':'other_unknown'},
                    {'plant_flowering_position':'terminal'}, {'plant_shoot_profile':None}):
        assert not sim(entity(**changes)).blueprint.growth.get('woody_spur_version')
    unsexed = sim(entity(reproductive_mode='other_unknown'))
    assert not any(p[0] in {'flower','fruit'} for p in unsexed.render_snapshot.placements)


def test_canonical_geometry_parent_sockets_and_ecology_across_lods():
    s = sim()
    snap = s.render_snapshot
    assert snap.to_dict() == sim().render_snapshot.to_dict()
    assert len(snap.placements) < 18000
    assert snap.stats['shrub_fruit_count'] > 50
    assert snap.stats['leaf_area_m2'] > 1
    for i,p in enumerate(snap.placements):
        assert p[1] == -1 or 0 <= p[1] < i
        assert all(math.isfinite(x) and abs(x) < 30 for x in p[2:5])
        path = snap.placement_paths.get(str(i))
        if path:
            assert path[-1] == p[2:5]
            if p[0] == 'branch_section' and p[7] in {3,4}:
                assert path[0] == snap.placements[p[1]][2:5]
        if p[0] in {'flower','fruit'}:
            assert p[2:5] == snap.placements[p[1]][2:5]
            stalk = snap.placements[p[1]]
            spur = snap.placements[stalk[1]]
            assert stalk[7] == 4 and spur[7] == 3
            assert math.dist(stalk[2:5], spur[2:5]) == pytest.approx(.015, abs=.00015)
    def body(snap):
        return [(p[0],p[2:8]) for p in snap.placements if p[0] in {'stem_section','branch_section'}]
    for lod in (0,1):
        coarse = sim(lod=lod)
        assert body(coarse.render_snapshot) == body(snap)
        assert coarse.get_ecological_outcome() == s.get_ecological_outcome()
        assert 'calyx' in coarse.render_snapshot.modules
        assert coarse.render_snapshot.stats['shrub_fruit_count'] == snap.stats['shrub_fruit_count']
        for key in ('root_length_m','root_depth_m','root_spread_m','estimated_leaf_count','leaf_area_m2'):
            assert coarse.render_snapshot.stats[key] == snap.stats[key]


def test_leaf_spacing_changes_density_and_area_without_enlarging_blades():
    full = sim()
    p = {**entity()['plant_shoot_profile'],'fine_node_spacing_m':.035}
    sparse = sim(entity(plant_shoot_profile=p))
    assert sparse.render_snapshot.stats['estimated_leaf_count'] < full.render_snapshot.stats['estimated_leaf_count']*.6
    assert sparse.render_snapshot.stats['leaf_area_m2'] < full.render_snapshot.stats['leaf_area_m2']
    assert sparse.blueprint.module('leaf').to_dict() == full.blueprint.module('leaf').to_dict()
    assert sparse.blueprint.fingerprint() != full.blueprint.fingerprint()
    p = {**entity()['plant_shoot_profile'],'crown_radius_ratio':.6}
    broad = sim(entity(plant_shoot_profile=p))
    def canopy_width(snapshot):
        xs = [p[2] for p in snapshot.placements if p[0] in {'stem_section','branch_section','leaf'}]
        return max(xs)-min(xs)
    assert canopy_width(broad.render_snapshot) > canopy_width(full.render_snapshot)


def test_progressive_roots_shoots_and_reproductive_transitions():
    ages = (0,12,30,60,120)
    states = [sim(day=age).render_snapshot for age in ages]
    for before,after in zip(states,states[1:]):
        assert after.stats['root_depth_m'] >= before.stats['root_depth_m']
        assert after.stats['root_spread_m'] >= before.stats['root_spread_m']
        assert after.bounds_m[5] >= before.bounds_m[5]
    assert states[1].stats['root_depth_m'] < states[-1].stats['root_depth_m']*.3
    assert not any(p[0] in {'flower','fruit'} for p in states[2].placements)
    flower,unripe,ripe = (sim(day=day) for day in (142.35,204.93,237.25))
    assert flower.render_snapshot.stats['shrub_flower_count'] > 0
    assert flower.render_snapshot.stats['shrub_fruit_count'] == 0
    assert unripe.life_state()['fruit_ripeness'] == pytest.approx(.597,abs=.01)
    assert ripe.life_state()['fruit_ripeness'] == 1
    assert unripe.render_snapshot.stats['shrub_fruit_count'] == ripe.render_snapshot.stats['shrub_fruit_count']


def test_live_identity_fields_and_native_pixel_bytes():
    from world.world_model import WorldModel
    from world.plant_catalogue import PlantCatalogue
    from tools.author_plant_assets import render_module
    from tools.author_plant_assets import PixelEditorHost
    from ui.pixel_art_editor_ui import PixelArtEditorUI
    world = WorldModel(); sid = 'spec_ochna_serrulata'
    raw = world.loader.get(sid); resolved = world.resolved_species_entity(sid)
    assert PlantCatalogue.build(world.loader.entities).is_leaf_species(sid)
    assert raw['parents'] == ['cladis_ochna']
    assert raw['binomial_name'] == 'Ochna serrulata'
    for k,v in entity().items():
        if k not in {'id','type'}: assert raw[k] == v == resolved[k]
    manifest = json.loads(Path('assets/plant_asset_specs/'+sid+'.json').read_text())
    for m in manifest['modules']:
        illustration = world.loader.get(m['illustration_id'])
        assert illustration['parents'] == [sid]
        assert illustration['plant_asset_role'] == m['role']
        ref = raw['plant_'+m['role']+'_module_ref']
        assert Path(ref.replace('.png','.layers.json.gz')).is_file()
        saved = pygame.image.load(ref)
        assert saved.get_size() == (75,75)
        assert pygame.image.tobytes(saved,'RGBA') == pygame.image.tobytes(render_module(m),'RGBA')
        editor = PixelArtEditorUI(PixelEditorHost(world.loader))
        assert editor.open(m['illustration_id'])
        assert editor.begin_canvas()
        assert (editor.state['canvas_width'],editor.state['canvas_height']) == (75,75)
        assert pygame.image.tobytes(editor.composite_surface(),'RGBA') == pygame.image.tobytes(saved,'RGBA')


def test_sepal_colours_persist_while_actual_drupe_pixels_ripen_and_zoom_is_bounded():
    from tools.author_plant_assets import render_module
    manifest = json.loads(Path('assets/plant_asset_specs/spec_ochna_serrulata.json').read_text())
    units = {m['role']:render_module(m) for m in manifest['modules']}
    reproductive = sim().blueprint.growth['reproductive_profile']
    profile = reproductive['persistent_calyx_display']
    unripe,_ = calyx_surface(profile,reproductive,5000,units['calyx'],units['fruit'],.6,4)
    ripe,_ = calyx_surface(profile,reproductive,5000,units['calyx'],units['fruit'],1.,4)
    def pixels(surface):
        return [surface.get_at((x,y)) for y in range(surface.get_height()) for x in range(surface.get_width())]
    a,b = pixels(unripe),pixels(ripe)
    red = lambda c:c.a and c.r > c.g*2 and c.r > c.b*1.7
    assert sum(red(c) for c in b) > 200
    # Fruit antialiasing can cover a few more edge pixels when recoloured.
    # The exposed sepals outside the fruit ring must stay byte-identical.
    center = unripe.get_width()/2
    radius = (profile['fruitlet_orbit_m'] + math.hypot(profile['fruitlet_length_m'],profile['fruitlet_width_m'])/2)*5000+2
    exposed = [(x,y) for y in range(unripe.get_height()) for x in range(unripe.get_width())
               if math.hypot(x-center,y-center) > radius]
    assert all(unripe.get_at(p) == ripe.get_at(p) for p in exposed)
    assert sum(red(unripe.get_at(p)) for p in exposed) > 100
    assert sum(c.a and c.g > c.r*1.1 for c in a) > sum(c.a and c.g > c.r*1.1 for c in b)
    assert pygame.image.tobytes(units['calyx'],'RGBA') == pygame.image.tobytes(render_module(next(m for m in manifest['modules'] if m['role']=='calyx')),'RGBA')
    huge,_ = calyx_surface(profile,reproductive,1e8,units['calyx'],units['fruit'],1.,4)
    assert huge.get_width() <= 1028
    tiny,_ = calyx_surface(profile,reproductive,20,units['calyx'],units['fruit'],1.,4)
    assert tiny.get_bounding_rect().width <= 2 # No whole-plant minimum-sized flower glyph.


def test_renderer_routes_calyx_source_pixels_and_cache_revisions():
    from simulations.species.species_renderer import SpeciesRenderer,DiagnosticCamera
    data = entity()
    manifest = json.loads(Path('assets/plant_asset_specs/spec_ochna_serrulata.json').read_text())
    for m in manifest['modules']:
        data['plant_'+m['role']+'_module_ref'] = 'assets/illustrations/'+m['illustration_id']+'_pixel.png'
    s = sim(data)
    renderer = SpeciesRenderer(SimpleNamespace(camera=None))
    camera = DiagnosticCamera(300,300,(-.03,.03,-.03,.03))
    canvas = pygame.Surface((300,300),pygame.SRCALPHA)
    assert renderer._draw_module_asset(canvas,s,camera,'fruit',(150,150),0,1)
    red_count = sum(c.r > c.g*2 and c.a for c in [canvas.get_at((x,y)) for x in range(300) for y in range(300)])
    assert red_count > 100
    assert any(k[0]=='persistent_calyx' for k in renderer._inflorescence_sprite_cache)


def test_unrelated_shrub_reuses_recipe_and_biosphere_receives_canonical_foliage():
    from simulations.biosphere.representatives import RepresentativeBody
    data = entity(mature_height={'typical_m':.8,'max_m':1.1},leaf_arrangement='opposite')
    data['plant_shoot_profile']['crown_radius_ratio'] = .55
    data['plant_reproductive_profile']['persistent_calyx_display']['max_fruitlets'] = 1
    body = RepresentativeBody(species_entity=data,seed=303)
    body.set_age(237.25)
    assert body.blueprint.growth['woody_spur_version'] == 1
    assert body.blueprint.growth['reproductive_profile']['persistent_calyx_display']['max_fruitlets'] == 1
    assert body.get_ecological_outcome()['leaf_area_proxy'] > 0
    assert body.render_snapshot.stats['shrub_cane_count'] > 1
    assert body.render_snapshot.bounds_m[5] < 1.3


def test_calyx_can_be_edited_reassigned_and_refreshed_through_normal_ui_paths():
    from ui.card import EntityCard
    from ui.knowledge_browser_ui import KnowledgeBrowserUI
    from world.plant_catalogue import PlantCatalogue, PLANTAE_ID
    data = entity()
    data['parents'] = [PLANTAE_ID]
    catalogue = PlantCatalogue.build({data['id']:data, PLANTAE_ID:{'id':PLANTAE_ID,'type':'cladistics'}})
    world = SimpleNamespace(plant_catalogue=catalogue)
    card = EntityCard(data,world_model=world)
    assert card._toolbelt_tool_is_available({'requires':'persistent_calyx_species'})
    assert not EntityCard(entity(plant_reproductive_profile=None),world_model=world)._toolbelt_tool_is_available({'requires':'persistent_calyx_species'})
    assert KnowledgeBrowserUI._plant_asset_definitions(None)['calyx']['target_field'] == 'plant_calyx_module_ref'
    parent = deepcopy(data)
    ui = SimpleNamespace(world_model=object(), cards=[],
                         _parent_entity_for_illustration=lambda _:parent,
                         _persist_entity_to_repository=lambda _:True,
                         _build_browser_items=lambda _:[], _relayout_cards=lambda:None)
    illustration = {'plant_asset_target_field':'plant_calyx_module_ref','media_path':'test_calyx.png',
                    'depicted_size_m':.028,'pixel_module_anchor':{'attachment_point':[.5,.5]}}
    assert KnowledgeBrowserUI.assign_plant_asset_to_parent(ui,illustration)
    assert parent['plant_calyx_module_ref'] == 'test_calyx.png'
    assert parent['plant_module_anchors']['calyx']['depicted_size_m'] == .028
    s = sim(data)
    s.world_model = SimpleNamespace(get_entity=lambda _:parent)
    assert s._sync_species_editor_asset_refs()
    assert s._ensure_species_editor()['working_entity']['plant_calyx_module_ref'] == 'test_calyx.png'
