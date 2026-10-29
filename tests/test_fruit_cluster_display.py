"""Fruiting panicle display geometry and legible reproductive inspection."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import json
import math

import pygame
import pytest
from simulations.species.pendant_reproduction import fruit_cluster_profile, pendant_display_units, pendant_geometry
from simulations.species.plant_reproduction import reproductive_profile
from simulations.species.plant_assets import PlantBlueprint,PlantGrowthSnapshot
from simulations.species.species_simulation import SpeciesSimulation
from simulations.species.species_renderer import SpeciesRenderer,SurfaceElevationCamera
from tools.author_plant_species import validate_updates,AuthoringError
from tools.render_species_views import fitted_inspection_elevation,render_reproductive_inspection
from world.world_model import WorldModel


@pytest.fixture(scope='module')
def entity():return WorldModel().resolved_species_entity('spec_moringa_oleifera')


def sim(entity,age=292.,lod=2):
    s=SpeciesSimulation(species_entity=entity,seed=303);s.set_lod(lod);s.set_age(age);return s


@pytest.mark.parametrize('key,value',[
    ('min_count',0),('min_count',True),('min_count',1.5),('min_count',4),
    ('max_count',13),('max_count',0),('max_count',float('inf')),
    ('spread_m',-.1),('spread_m',.31),('spread_m',True),('spread_m',float('nan'))])
def test_invalid_recipe_rejected(entity,key,value):
    profile=deepcopy(entity['plant_reproductive_profile'])
    profile['fruit_cluster_display'][key]=value
    assert fruit_cluster_profile(profile['fruit_cluster_display']) is None
    with pytest.raises(AuthoringError):validate_updates({'plant_reproductive_profile':profile})


@pytest.mark.parametrize('value',[None,{},'other_unknown',0,{'min_count':1,'max_count':1,'spread_m':0}])
def test_absent_unknown_and_single_are_neutral(entity,value):
    control=deepcopy(entity);control['plant_reproductive_profile'].pop('fruit_cluster_display')
    experimental=deepcopy(control);experimental['plant_reproductive_profile']['fruit_cluster_display']=value
    a,b=sim(control),sim(experimental)
    assert a.blueprint.fingerprint()==b.blueprint.fingerprint()
    assert a.render_snapshot.to_dict()==b.render_snapshot.to_dict()
    p=next(p for p in b.render_snapshot.placements if p[0]=='fruit')
    assert pendant_display_units(b.blueprint.growth,p,b.blueprint.module('fruit'),303)==[pendant_geometry(b.blueprint.growth,p,b.blueprint.module('fruit'))]


def test_transport_deterministic_groups_metric_lengths_and_bounds(entity):
    s=sim(entity);snapshot=s.render_snapshot
    assert s.blueprint.growth['reproductive_profile']['version']==4
    assert PlantBlueprint.from_dict(s.blueprint.to_dict()).fingerprint()==s.blueprint.fingerprint()
    assert PlantGrowthSnapshot.from_dict(snapshot.to_dict()).to_dict()==snapshot.to_dict()
    counts=[]
    for p in snapshot.placements:
        if p[0]!='fruit':continue
        units=pendant_display_units(s.blueprint.growth,p,s.blueprint.module('fruit'),s.seed)
        assert units==pendant_display_units(s.blueprint.growth,p,s.blueprint.module('fruit'),s.seed)
        counts.append(len(units));assert 1<=len(units)<=3
        for a,b in units:
            assert a[:2]==b[:2]
            assert a[2]-b[2]==pytest.approx(.4*max(.55,p[6]))
            assert b[2]<a[2]<p[4]
            for point in (a,b):
                assert all(math.isfinite(n) for n in point)
                for axis in range(3):assert snapshot.bounds_m[2*axis]<=point[axis]<=snapshot.bounds_m[2*axis+1]
    assert max(counts)>1 and min(counts)==1


def test_display_preserves_canonical_foliage_wood_and_ecology(entity):
    control=deepcopy(entity);control['plant_reproductive_profile'].pop('fruit_cluster_display')
    for lod in (0,1,2):
        a,b=sim(control,lod=lod),sim(entity,lod=lod)
        assert a.render_snapshot.placements==b.render_snapshot.placements
        assert a.render_snapshot.leaf_clusters==b.render_snapshot.leaf_clusters
        assert a.get_ecological_outcome()==b.get_ecological_outcome()
    for age in (60.,177.75):
        a,b=sim(control,age),sim(entity,age)
        assert a.render_snapshot.placements==b.render_snapshot.placements
        assert a.render_snapshot.bounds_m==b.render_snapshot.bounds_m


def test_renderer_draws_members_and_unrelated_fixture_reuses_geometry(entity):
    s=sim(entity)
    r=SpeciesRenderer(SimpleNamespace(camera=None))
    pygame.init();pygame.display.set_mode((1,1))
    points=[]
    def draw(_screen,_sim,_camera,kind,point,*args,**kwargs):
        if kind=='fruit':points.append(point)
        return True
    visible={i for i,p in enumerate(s.render_snapshot.placements) if p[0]=='fruit'}
    camera=SurfaceElevationCamera(700,700,s.render_snapshot.bounds_m)
    with patch.object(r,'_draw_module_asset',side_effect=draw):
        r._draw_individual(pygame.Surface((700,700)),s,camera=camera,visible_indices=visible,cache=False,draw_environment=False)
    expected=sum(len(pendant_display_units(s.blueprint.growth,p,s.blueprint.module('fruit'),303))
                 for p in s.render_snapshot.placements if p[0]=='fruit')
    assert len(points)==expected>len(visible)
    other=deepcopy(entity);other['id']='unrelated_pendant_panicle_fixture';other['parents']=[]
    b=sim(other)
    p=['fruit',-1,1.,2.,3.,0.,1.,6]
    assert pendant_display_units(s.blueprint.growth,p,s.blueprint.module('fruit'),303)==pendant_display_units(b.blueprint.growth,p,b.blueprint.module('fruit'),303)
    pygame.quit()


def test_shared_inspection_scale_and_real_phase_differences(entity):
    s=sim(entity)
    snapshots=[s.generate_snapshot(age,2) for age in (60.,177.75,292.)]
    camera=fitted_inspection_elevation(s,snapshots,500,760,35.)
    # The tree fits vertically and leaves room for measured organs, while
    # avoiding the unused corners of the global x/y box.
    assert camera.scale>50
    assert not any(p[0] in {'flower','fruit'} for p in snapshots[0].placements)
    assert any(p[0]=='flower' for p in snapshots[1].placements)
    assert any(p[0]=='fruit' for p in snapshots[2].placements)
    points=[camera.world_to_screen_3d(p[2:5]) for snap in snapshots for p in snap.placements
            if p[0] in {'flower','fruit'}]
    assert all(0<=x<500 and 0<=y<760 for x,y in points)


def test_rotated_elevation_preserves_vertical_capsule_metres(entity):
    pygame.init();pygame.display.set_mode((1,1))
    s=sim(entity);r=SpeciesRenderer(SimpleNamespace(camera=None))
    for rotation in (0.,35.,60.):
        camera=SurfaceElevationCamera(300,300,[-1,1,-1,1,0,2],rotation)
        canvas=pygame.Surface((300,300),pygame.SRCALPHA)
        r._draw_module_asset(canvas,s,camera,'fruit',(150,60),180.,1.)
        assert canvas.get_bounding_rect().height==pytest.approx(round(.4*camera.scale),abs=1)
    pygame.quit()
