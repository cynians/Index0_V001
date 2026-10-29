"""Reusable cactus axes, biological organ accounting and gradual development."""
from copy import deepcopy
import json
import math
from pathlib import Path

import pytest

from simulations.species.columnar_succulents import columnar_profile
from simulations.species.root_growth import shallow_radial_profile
from simulations.species.plant_assets import PlantBlueprint, PlantGrowthSnapshot
from simulations.species.plant_life_timing import resolve_plant_life_timing
from simulations.species.species_simulation import SpeciesSimulation
from tools.author_plant_species import AuthoringError, validate_updates


def entity(**updates):
    fields=json.loads(Path('assets/species_trait_specs/spec_carnegiea_gigantea.json').read_text())['updates']
    return {'id':'spec_synthetic_columnar','type':'species',**deepcopy(fields),**updates}


def sim(data=None, fraction=1., lod=2, day=None):
    result=SpeciesSimulation(species_entity=data or entity(),seed=303)
    result.set_lod(lod)
    result.set_age(result.mature_age_days*fraction if day is None else day)
    return result


@pytest.mark.parametrize('key,value',[('stem_radius_m',math.nan),('arm_radius_m',math.inf),
    ('arm_count',True),('arm_count',13),('rib_count',3),('size_exponent',0),
    ('arm_onset_fraction',1.1),('reproductive_onset_fraction',0),
    ('areole_spacing_m',0),('spine_size_m',-.05)])
def test_invalid_profiles_rejected_and_runtime_neutral(key,value):
    p={**entity()['plant_shoot_profile'],key:value}
    assert columnar_profile(p) is None
    with pytest.raises(AuthoringError):
        validate_updates({'plant_shoot_profile':p})
    assert sim(entity(plant_shoot_profile=p)).blueprint.fingerprint()==sim(entity(plant_shoot_profile=None)).blueprint.fingerprint()
    unresolved=sim(entity(plant_shoot_profile=p)).render_snapshot
    assert unresolved.stats['columnar_model_status']=='unresolved_missing_shoot_profile'
    assert not any(v[0] in {'leaf','stem_section','branch_section'} for v in unresolved.placements)


@pytest.mark.parametrize('key,value',[('tap_depth_m',0),('lateral_depth_m',math.nan),
    ('spread_radius_m',31),('radial_axes',True),('radial_axes',17)])
def test_radial_root_validation(key,value):
    p={**entity()['plant_root_profile'],key:value}
    assert shallow_radial_profile(p) is None
    with pytest.raises(AuthoringError):
        validate_updates({'plant_root_profile':p})


def test_portable_blueprint_and_exact_trait_transport():
    s=sim();g=s.blueprint.growth
    assert g['columnar_version']==1
    assert g['columnar_profile']==columnar_profile(entity()['plant_shoot_profile'])
    assert g['shallow_radial_profile']==shallow_radial_profile(entity()['plant_root_profile'])
    assert g['root_profile']['grammar_version']==8
    assert g['max_height_m']==12. # Representative height, not reported range endpoint.
    assert g['leaf_structure']=='spine_like'
    assert s.blueprint.module('leaf').length_m==.05
    assert s.blueprint.module('leaf').radius_m==.025
    assert PlantBlueprint.from_dict(s.blueprint.to_dict()).fingerprint()==s.blueprint.fingerprint()
    assert PlantGrowthSnapshot.from_dict(s.render_snapshot.to_dict()).to_dict()==s.render_snapshot.to_dict()
    for field,value in [('plant_growth_form','forb'),('plant_growth_behaviour','basal_succulent_rosette')]:
        assert not sim(entity(**{field:value})).blueprint.growth.get('columnar_version')
    assert not sim(entity(root_architecture='other_unknown')).blueprint.growth.get('shallow_radial_profile')


def test_deterministic_parent_connections_bounded_geometry_and_lod_metrics():
    s=sim(day=498.225);snapshot=s.render_snapshot
    assert snapshot.to_dict()==sim(day=498.225).render_snapshot.to_dict()
    assert len(snapshot.placements)<200
    assert snapshot.stats['columnar_arm_count']==4
    assert snapshot.stats['estimated_leaf_count']==0
    assert snapshot.stats['leaf_area_m2']==0
    assert snapshot.stats['photosynthetic_area_m2']>20
    assert not any(p[0]=='leaf' for p in snapshot.placements)
    for i,p in enumerate(snapshot.placements):
        assert p[1]==-1 or 0<=p[1]<i
        assert all(math.isfinite(v) and abs(v)<=30 for v in p[2:5])
        path=snapshot.placement_paths.get(str(i))
        if path:
            assert path[0]==snapshot.placements[p[1]][2:5]
            assert path[-1]==p[2:5]
    for lod in (0,1):
        coarse=sim(day=498.225,lod=lod)
        assert coarse.get_ecological_outcome()==s.get_ecological_outcome()
        for k in ('columnar_arm_count','columnar_height_m','photosynthetic_area_m2','root_depth_m','root_spread_m','root_length_m'):
            assert coarse.render_snapshot.stats[k]==snapshot.stats[k]
    assert s.get_ecological_outcome()['photosynthetic_source']=='green_stem_surface'
    assert s.get_ecological_outcome()['leaf_area_proxy']==0


def test_roots_and_shoots_grow_from_zero_and_arms_emerge_without_jumps():
    previous=None
    for fraction in (0,.064,.24,.4,.48,.481,.6,1.):
        s=sim(fraction=fraction);stats=s.render_snapshot.stats
        assert stats['root_spread_m']==pytest.approx(stats['columnar_height_m']*2,abs=2e-6)
        if fraction<=.48:
            assert stats['columnar_arm_count']==0
        if previous:
            for key in ('root_length_m','root_depth_m','columnar_height_m','photosynthetic_area_m2'):
                assert stats[key]>=previous[key]
        previous=stats
    newly=sim(fraction=.481).render_snapshot
    arm=next((i,p) for i,p in enumerate(newly.placements) if p[0]=='branch_section')
    path=newly.placement_paths[str(arm[0])]
    assert sum(math.dist(a,b) for a,b in zip(path,path[1:]))<.01
    assert arm[1][6]<.002
    # Attachment is a fixed areole, never lifted up the trunk with age.
    def junction(s):
        p=next(p for p in s.render_snapshot.placements if p[0]=='branch_section')
        return s.render_snapshot.placements[p[1]][2:5]
    assert junction(sim(fraction=.55))==junction(sim())


def test_arm_and_root_controls_are_independent_and_fingerprinted():
    normal=sim();p=entity()['plant_shoot_profile']
    spear=sim(entity(plant_shoot_profile={**p,'arm_count':0}))
    broad=sim(entity(plant_shoot_profile={**p,'stem_radius_m':.5}))
    roots=sim(entity(plant_root_profile={**entity()['plant_root_profile'],'spread_radius_m':3.}))
    assert spear.render_snapshot.stats['columnar_arm_count']==0
    assert spear.render_snapshot.stats['photosynthetic_area_m2']<normal.render_snapshot.stats['photosynthetic_area_m2']
    assert broad.render_snapshot.stats['photosynthetic_area_m2']>normal.render_snapshot.stats['photosynthetic_area_m2']
    assert roots.render_snapshot.stats['root_spread_m']==6.
    assert roots.render_snapshot.stats['columnar_height_m']==normal.render_snapshot.stats['columnar_height_m']
    for alternate in (spear,broad,roots):
        assert alternate.blueprint.fingerprint()!=normal.blueprint.fingerprint()


def test_tip_flowering_and_fruit_keep_physical_sizes_and_missing_controls_neutral():
    flower=sim(day=498.225);fruit=sim(day=569.4)
    for s,kind in ((flower,'flower'),(fruit,'fruit')):
        organs=[p for p in s.render_snapshot.placements if p[0]==kind]
        assert len(organs)==20
        assert s.blueprint.module(kind).length_m==.08
        for p in organs:
            host=s.render_snapshot.placements[p[1]]
            assert host[0] in {'stem_section','branch_section'}
            assert math.dist(host[2:5],p[2:5])<=host[6]
    assert not any(p[0]=='fruit' for p in flower.render_snapshot.placements)
    assert not any(p[0]=='flower' for p in fruit.render_snapshot.placements)
    assert not any(p[0] in {'flower','fruit'} for p in sim(fraction=.3).render_snapshot.placements)
    for changes in ({'reproductive_mode':'vegetative'},{'plant_flowering_position':'other_unknown'},
                    {'plant_reproductive_profile':None}):
        assert not any(p[0] in {'flower','fruit'} for p in sim(entity(**changes),day=498.225).render_snapshot.placements)


def test_real_timing_and_biosphere_reproduction_precede_full_size():
    from simulations.biosphere.representatives import RepresentativeBody
    data=entity();s=sim();timing=resolve_plant_life_timing(data,s.blueprint.growth)
    assert timing.maturity_days==125*365.25
    assert timing.lifespan_days==160*365.25 # Authored longevity is not inflated to 187.5 years.
    body=RepresentativeBody(species_entity=data,seed=303)
    body.life_timing=timing
    for years,expected in ((45,False),(55,True)):
        body.real_age_days=math.floor(years*365.25/365)*365+365*.36
        body.set_age(timing.developmental_days(body.real_age_days))
        assert body.render_snapshot.stats['columnar_height_m']<12.
        assert any(p[0]=='flower' for p in body.render_snapshot.placements)==expected
        assert body.get_ecological_outcome()['photosynthetic_stem_area_m2']>0


def test_live_identity_saved_fields_editable_assets_and_blueprint():
    import pygame
    from world.world_model import WorldModel
    from world.plant_catalogue import PlantCatalogue
    from world.species_inheritance import is_authored_field, is_inheritable_species_field
    from tools.author_plant_assets import render_module
    world=WorldModel();sid='spec_carnegiea_gigantea'
    raw=world.loader.get(sid);resolved=world.resolved_species_entity(sid)
    assert PlantCatalogue.build(world.loader.entities).is_leaf_species(sid)
    assert raw['parents']==['cladis_echinocereeae']
    assert raw['binomial_name']=='Carnegiea gigantea'
    assert not is_inheritable_species_field('plant_root_profile')
    for key,value in entity().items():
        if key in {'id','type'}:
            continue
        assert raw[key]==value and resolved[key]==value
        assert is_authored_field(raw,key)
    live=SpeciesSimulation(world_model=world,species_id=sid,seed=303)
    assert live.blueprint.growth['columnar_version']==1
    manifest=json.loads(Path('assets/plant_asset_specs/'+sid+'.json').read_text())
    for module in manifest['modules']:
        ref=raw['plant_'+module['role']+'_module_ref']
        assert Path(ref).is_file()
        assert Path(ref.replace('.png','.layers.json.gz')).is_file()
        authored=pygame.image.load(ref)
        assert authored.get_size()==(75,75)
        assert pygame.image.tobytes(authored,'RGBA')==pygame.image.tobytes(render_module(module),'RGBA')


def test_projected_areoles_stay_on_stem_in_sheared_and_orthographic_closeups():
    import pygame
    from types import SimpleNamespace
    from simulations.species.species_renderer import SpeciesRenderer,DiagnosticCamera,SurfaceElevationCamera
    p={**entity()['plant_shoot_profile'],'arm_count':0}
    s=sim(entity(plant_shoot_profile=p),day=498.225)
    snap=s.render_snapshot
    renderer=SpeciesRenderer(SimpleNamespace(camera=None))
    cameras=[DiagnosticCamera(500,500,(-1.1,1.1,11.,12.35)),
             SurfaceElevationCamera(500,500,(-1.1,1.1,-1.,1.,11.,12.35))]
    for camera in cameras:
        surface=pygame.Surface((500,500),pygame.SRCALPHA)
        renderer._draw_individual(surface,s,camera=camera,clear=False,cache=False,
            visible_indices={i for i,p in enumerate(snap.placements) if p[0]=='stem_section'},
            draw_environment=False,draw_ground_line=False)
        for placement in snap.placements:
            if placement[0]=='flower':
                point=camera.world_to_screen_3d(placement[2:5])
                assert surface.get_at(point).a>0 # Areole center is on the projected tissue.
