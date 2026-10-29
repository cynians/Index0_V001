"""One rooted woody crown, portable leafy shoots and seasonal head sockets."""
import json
import math
from pathlib import Path

import pytest

from simulations.species.basal_subshrubs import basal_subshrub_profile
from simulations.species.plant_assets import PlantBlueprint, PlantGrowthSnapshot
from simulations.species.species_simulation import SpeciesSimulation
from tools.author_plant_species import AuthoringError, validate_updates


def entity(**changes):
    fields = json.loads(Path('assets/plant_asset_specs/spec_senecio_inaequidens.json').read_text())['species_field_updates']
    return {'id': 'spec_unrelated_basal_fixture', **fields, **changes}


def snapshot(data=None, day=200, lod=2):
    sim = SpeciesSimulation(species_entity=data or entity(), seed=303)
    sim.set_age(day); sim.set_lod(lod)
    return sim, sim.render_snapshot


@pytest.mark.parametrize('key,value', [('basal_shoot_count',0),('basal_shoot_count',13),
    ('basal_shoot_count',True),('nodes_per_shoot',37),('nodes_per_shoot',5),
    ('stem_radius_m',float('nan')),('leaf_width_m',float('inf')),
    ('branching_start_fraction',-.1),('crown_radius_ratio',1)])
def test_bad_profiles_are_neutral_and_authoring_rejects_them(key,value):
    raw={**entity()['plant_shoot_profile'],key:value}
    assert basal_subshrub_profile(raw) is None
    with pytest.raises(AuthoringError): validate_updates({'plant_shoot_profile':raw})
    a=PlantBlueprint.from_species_entity(entity(plant_shoot_profile=raw))
    b=PlantBlueprint.from_species_entity(entity(plant_shoot_profile=None))
    assert a.fingerprint()==b.fingerprint()


def test_transport_fingerprint_and_body_plan_gate():
    a=PlantBlueprint.from_species_entity(entity())
    assert a.growth['basal_subshrub_profile']['basal_shoot_count']==6
    assert a.module('leaf').radius_m==.002
    assert a.module('flower').length_m==a.module('fruit').length_m==.02
    assert PlantBlueprint.from_dict(a.to_dict()).fingerprint()==a.fingerprint()
    for key,value in [('basal_shoot_count',3),('crown_radius_ratio',.5),('leaf_width_m',.002)]:
        assert a.fingerprint()!=PlantBlueprint.from_species_entity(entity(
            plant_shoot_profile={**entity()['plant_shoot_profile'],key:value})).fingerprint()
    for changes in [{'plant_growth_form':'tree'},{'plant_woodiness':'herbaceous'},
                    {'plant_growth_behaviour':'stoloniferous_clonal'}, {'plant_leaf_distribution':'terminal_cluster'}]:
        assert 'basal_subshrub_profile' not in PlantBlueprint.from_species_entity(entity(**changes)).growth


def axes(s):
    return [(p[0],p[2:7],s.placements[p[1]][2:5] if p[1]>=0 else None,
             s.placement_paths.get(str(i))) for i,p in enumerate(s.placements)
            if p[0] in {'stem_section','branch_section'}]


def test_canonical_axes_ecology_and_sockets_are_lod_stable():
    cases=[snapshot(lod=lod) for lod in (0,1,2)]
    for sim,s in cases:
        assert s.to_dict()==snapshot(lod=sim.lod)[1].to_dict()
        assert PlantGrowthSnapshot.from_dict(s.to_dict()).to_dict()==s.to_dict()
        assert axes(s)==axes(cases[0][1])
        assert sim.get_ecological_outcome()==cases[0][0].get_ecological_outcome()
        assert s.stats['leaf_area_m2']==cases[0][1].stats['leaf_area_m2']
        assert s.stats['basal_shoot_count']==6
        assert len(s.placements)<1500
        for i,p in enumerate(s.placements):
            assert -1<=p[1]<i
            assert all(math.isfinite(v) for v in p[2:7])
            assert all(abs(v)<2 for v in p[2:5])
        for socket in s.attachment_points:
            assert s.placements[socket['leaf_placement_index']][0]=='leaf'
            assert s.placements[socket['stem_placement_index']][0] in {'stem_section','branch_section'}


def test_sourced_height_shoot_count_spread_and_width_have_visible_effects():
    _,a=snapshot()
    _,small=snapshot(entity(plant_shoot_profile={**entity()['plant_shoot_profile'],'basal_shoot_count':2}))
    _,wide=snapshot(entity(plant_shoot_profile={**entity()['plant_shoot_profile'],'crown_radius_ratio':.6}))
    _,thin=snapshot(entity(plant_shoot_profile={**entity()['plant_shoot_profile'],'leaf_width_m':.002}))
    assert a.stats['estimated_leaf_count']>small.stats['estimated_leaf_count']*2
    radius=lambda s:max(math.hypot(p[2],p[3]) for p in s.placements if p[0]=='stem_section')
    assert radius(wide)>radius(a)*1.5
    assert thin.stats['estimated_leaf_count']==a.stats['estimated_leaf_count']
    assert thin.stats['leaf_area_m2']==pytest.approx(a.stats['leaf_area_m2']*.5,rel=.01)
    assert max(p[4] for p in a.placements if p[0]=='stem_section')<.66
    _,young=snapshot(day=12)
    assert young.stats['basal_shoot_count']<a.stats['basal_shoot_count']
    assert not any(p[0] in {'flower','fruit'} for p in young.placements)


def test_pappus_reuses_terminal_hosts_without_seeds_or_clone_connectors():
    _,a=snapshot(day=200);_,b=snapshot(day=300)
    hosts=lambda s,k:[tuple(s.placements[p[1]][2:5]) for p in s.placements if p[0]==k]
    assert hosts(a,'flower') and hosts(b,'fruit')
    assert set(hosts(b,'fruit')) <= set(hosts(a,'flower'))
    assert axes(a)==axes(b)
    assert not any(p[0] in {'rhizome','stolon','renewal_organ'} for p in a.placements)
    for changes in [{'plant_reproductive_profile':None},{'reproductive_mode':'other_unknown'},
                    {'reproductive_mode':'vegetative'},{'plant_reproductive_structure':'other_unknown'}]:
        assert not hosts(snapshot(entity(**changes),day=300)[1],'fruit')


def test_live_taxonomy_assets_and_resolved_recipe():
    from world.world_model import WorldModel
    world=WorldModel(); e=world.resolved_species_entity('spec_senecio_inaequidens')
    assert e['binomial_name']=='Senecio inaequidens'
    assert 'cladis_groundsels_senecio' in e['parents']
    from world.plant_catalogue import PlantCatalogue
    assert PlantCatalogue.build(world.loader.entities).is_leaf_species(e['id'])
    sim=SpeciesSimulation(world_model=world,species_id=e['id'],seed=303)
    assert sim.blueprint.growth['basal_subshrub_profile']['form']=='basal_subshrub'
    for role in ('leaf','stem','branch','flower','fruit'):
        assert e[f'plant_{role}_module_ref']==f'assets/illustrations/illust_senecio_inaequidens_{role}_module_pixel.png'
        assert Path(f'assets/illustrations/illust_senecio_inaequidens_{role}_module_pixel.layers.json.gz').exists()


def test_composed_heads_fit_metric_bounds_and_biosim_consumer():
    import pygame
    from types import SimpleNamespace
    from simulations.species.species_renderer import SpeciesRenderer, top_down_diagnostic_bounds
    from simulations.biosphere.plant_pictures import top_view, map_sprite_at
    from tools.render_plant_biosim_check import sprite
    pygame.init();pygame.display.set_mode((1,1))
    renderer=SpeciesRenderer(SimpleNamespace(camera=None))
    for day,kind in ((200,'flower'),(300,'fruit')):
        sim,s=snapshot(day=day)
        r=math.hypot(.095,.12*.5)
        bounds=top_down_diagnostic_bounds(sim)
        for p in s.placements:
            if p[0]==kind:
                assert s.bounds_m[5]>=p[4]+r*p[6]-.0001
                assert bounds[0]<=p[2]-r*p[6] and bounds[1]>=p[2]+r*p[6]
        assert renderer._draw_module_asset(pygame.Surface((640,480)),sim,
            SimpleNamespace(scale=1000),kind,(320,350),0,1)
        art,anchor=sprite(renderer,sim,84)
        assert 0<art.get_width()<=96 and 0<art.get_height()<=96
        assert 0<=anchor[0]<art.get_width() and 0<=anchor[1]<art.get_height()
        picture=top_view(sim);assert picture is not None and max(picture.get_size())<=192
        assert max(map_sprite_at(picture,40).get_size())<=40
    assert {key[0] for key in renderer._inflorescence_sprite_cache}=={'flower','fruit'}
    pygame.quit()
