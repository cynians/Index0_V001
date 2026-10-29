"""Saved composition and reusable basal/width controls for Pompom Weed."""
import json
import math
from copy import deepcopy
from pathlib import Path

import pygame
import pytest

from simulations.species.plant_assets import PlantBlueprint, PlantGrowthSnapshot
from simulations.species.species_simulation import SpeciesSimulation
from simulations.species.clonal_forb_profiles import clonal_forb_profile
from simulations.species.capitulum_clusters import capitulum_cluster_profile, capitulum_cluster_surface
from tools.author_plant_species import validate_updates, AuthoringError
from world.world_model import WorldModel

ROOT=Path(__file__).resolve().parents[1]
SID='spec_eupatorium_macrocephalum'


def entity():
    return {'id':'spec_unrelated_crown_rosette_forb', **deepcopy(json.loads(
        (ROOT/'assets/species_trait_specs'/f'{SID}.json').read_text())['updates'])}


def sim(data=None, day=210, lod=2):
    s=SpeciesSimulation(species_entity=data or entity(), seed=303)
    s.set_age(day);s.set_lod(lod)
    return s


def test_live_identity_field_transport_and_editable_assets():
    w=WorldModel();raw=w.loader.get(SID);resolved=w.resolved_species_entity(SID)
    assert w.loader.plant_catalogue.is_leaf_species(SID)
    assert raw['parents']==['cladis_eupatorium']
    for key,value in entity().items():
        if key!='id':
            assert raw[key]==resolved[key]==value
    bp=PlantBlueprint.from_species_entity(resolved,SID)
    assert bp.growth['clonal_forb_profile']['basal_leaf_count']==8
    assert bp.growth['inflorescence_profile']['head_size_axis']=='width'
    assert bp.growth['clonal_forb_leaf_season_version']==1
    for role in ('leaf','stem_section','branch_section','flower','fruit'):
        asset=bp.module(role).asset_ref
        assert asset and (ROOT/asset).is_file()
        assert (ROOT/asset.replace('_pixel.png','_pixel.layers.json.gz')).is_file()


@pytest.mark.parametrize('changes',[{'basal_leaf_count':25},{'basal_leaf_count':True},
    {'basal_leaf_length_scale':float('nan')},{'basal_leaf_length_scale':0}])
def test_bad_basal_recipe_is_neutral_and_rejected_before_write(changes):
    profile={**entity()['plant_shoot_profile'],**changes}
    assert clonal_forb_profile(profile) is None
    with pytest.raises(AuthoringError):validate_updates({'plant_shoot_profile':profile})


def test_basal_foliage_is_bounded_attached_and_increases_real_leaf_area():
    data=entity();absent=deepcopy(data);absent['plant_shoot_profile']['basal_leaf_count']=0
    a,b=sim(data),sim(absent)
    snap=a.render_snapshot
    basal=[c for c in snap.leaf_clusters if c.get('cohort')=='basal_rosette']
    assert len(basal)==8*snap.stats['clonal_forb_shoot_count']
    assert snap.stats['leaf_area_m2']>b.render_snapshot.stats['leaf_area_m2']
    assert a.blueprint.fingerprint()!=b.blueprint.fingerprint()
    assert snap.to_dict()==sim(data).render_snapshot.to_dict()
    assert len(snap.placements)<2000
    for index,p in enumerate(snap.placements):
        assert p[1]==-1 or 0<=p[1]<index
        assert all(math.isfinite(float(v)) for v in p[2:7])
    for socket in snap.attachment_points:
        if socket.get('cohort')=='basal_rosette':
            p=snap.placements[socket['leaf_placement_index']]
            assert p[1]==socket['stem_placement_index']
            assert tuple(p[2:5])==tuple(socket['position_m'])
            assert p[4]<.025


def test_seasons_and_lod_share_canonical_cohorts_and_biosphere_outcomes():
    from simulations.biosphere.representatives import RepresentativeBody
    for day in (210,305,350):
        sims=[sim(day=day,lod=lod) for lod in (0,1,2)]
        for s in sims:
            assert s.get_ecological_outcome()==sims[2].get_ecological_outcome()
            assert s.render_snapshot.stats['leaf_area_m2']==sims[2].render_snapshot.stats['leaf_area_m2']
            assert s.render_snapshot.stats['estimated_leaf_count']==sims[2].render_snapshot.stats['estimated_leaf_count']
        snap=sims[2].render_snapshot
        assert PlantGrowthSnapshot.from_dict(snap.to_dict()).to_dict()==snap.to_dict()
        if day==350:
            assert snap.stats['estimated_leaf_count']==snap.stats['leaf_count']==0
            assert sims[2].life_state()['phase']=='dormant'
        if day==210:assert any(p[0]=='flower' for p in snap.placements)
        if day==305:assert any(p[0]=='fruit' for p in snap.placements)
    body=RepresentativeBody(species_entity=entity(),seed=303);body.set_age(210);body.set_lod(2)
    assert body.get_ecological_outcome()==sim().get_ecological_outcome()


def test_head_width_axis_keeps_the_measured_unit_and_old_recipes_unchanged():
    raw=entity()['plant_inflorescence_profile']
    assert capitulum_cluster_profile({**raw,'head_size_axis':[]}) is None
    assert capitulum_cluster_profile(raw)['version']==3
    old={**raw};old.pop('head_size_axis')
    assert capitulum_cluster_profile(old)['version']==2
    pygame.init();pygame.display.set_mode((1,1))
    # A tall pink head exercises the width-vs-length distinction without
    # changing the supplied head artwork or cluster's metre envelope.
    head=pygame.Surface((20,35),pygame.SRCALPHA);head.fill((244,165,217,255))
    surfaces=[capitulum_cluster_surface(capitulum_cluster_profile(p),1000,.5,head)[0]
              for p in (raw,old)]
    masks=[pygame.mask.from_threshold(s,(244,165,217,255),(1,1,1,255)) for s in surfaces]
    assert masks[0].count()>masks[1].count()
    assert max(surfaces[0].get_size())<=1024
    pygame.quit()
