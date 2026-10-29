"""Saved fungal recipe transport, wood gates, and exact editable asset round trip."""
import copy, json, math
from pathlib import Path
import pygame
from world.world_model import WorldModel
from world.plant_catalogue import PlantCatalogue
from simulations.species.species_simulation import SpeciesSimulation
from simulations.species.plant_assets import PlantBlueprint, PlantGrowthSnapshot
from simulations.species.fungal_growth import wood_test_fixture
from tools.author_plant_assets import load_manifest, render_module, PixelEditorHost
from ui.pixel_art_editor_ui import PixelArtEditorUI
SID='spec_laetiporus_sulphureus'
def profile():
    return json.loads(Path(f'assets/species_trait_specs/{SID}.json').read_text())['updates']['fungal_growth_profile']
def grown(age=90,lod=2,env=None):
    s=SpeciesSimulation(species_entity={'id':'unrelated_wood_fixture','fungal_growth_profile':profile()},seed=303,
                        environment=env if env is not None else wood_test_fixture())
    s.set_lod(lod);s.set_age(age);return s
def test_live_fungi_identity_profile_transport_and_no_vascular_traits():
    w=WorldModel();raw=w.loader.get(SID);e=w.resolved_species_entity(SID)
    assert PlantCatalogue.build(w.loader.entities,root_id='cladis_fungi').is_leaf_species(SID)
    assert not w.plant_catalogue.is_species(SID)
    assert raw['parents']==['cladis_laetiporus']
    assert raw['fungal_growth_profile']==e['fungal_growth_profile']==profile()
    assert not {'root_architecture','leaf_length','plant_lifespan','maturity_age','longevity'}.intersection(raw)
    s=SpeciesSimulation(world_model=w,species_id=SID)
    assert s.blueprint.module('leaf') is None
    assert s.blueprint.growth['fungal_growth_profile']['resolved']['stipe_length_m']==0
def test_canonical_growth_lod_lifecycle_substrate_gates_and_reuse():
    s=grown();snap=s.render_snapshot
    assert snap.to_dict()==grown().render_snapshot.to_dict()
    assert PlantGrowthSnapshot.from_dict(snap.to_dict()).to_dict()==snap.to_dict()
    assert PlantBlueprint.from_dict(s.blueprint.to_dict()).fingerprint()==s.blueprint.fingerprint()
    assert snap.stats['estimated_fruiting_body_count']==14
    assert len({b['variant_key'] for b in snap.stats['fungal_bodies']})==4
    assert len({b['cap_width_m'] for b in snap.stats['fungal_bodies']})>8
    assert all(.05<=b['cap_width_m']<=.4 and b['stipe_length_m']==0 for b in snap.stats['fungal_bodies'])
    for i,p in enumerate(snap.placements):
        assert -1<=p[1]<i and all(math.isfinite(v) for v in p[2:])
    for key in ['estimated_fruiting_body_count','colonised_wood_volume_proxy_m3','sporulating_area_proxy_m2']:
        assert len({grown(lod=l).render_snapshot.stats[key] for l in range(3)})==1
    assert len({json.dumps(grown(lod=l).get_ecological_outcome(),sort_keys=True) for l in range(3)})==1
    for material in ['dead_hardwood','living_hardwood','dead_conifer']:
        env=wood_test_fixture();env['fungal_substrates'][0]['material']=material
        assert (grown(env=env).render_snapshot.stats['estimated_fruiting_body_count']>0)==(material!='dead_conifer')
    assert grown(env={'fungal_substrates':[]}).render_snapshot.stats['estimated_fruiting_body_count']==0
    dry=wood_test_fixture();dry['fungal_moisture']=0
    assert grown(env=dry).render_snapshot.stats['estimated_fruiting_body_count']==0
    assert grown(age=130).render_snapshot.stats['estimated_fruiting_body_count']==0
    assert grown(age=130).render_snapshot.stats['colonised_wood_volume_proxy_m3']>0
    assert grown(age=210).render_snapshot.stats['estimated_fruiting_body_count']==14
    for a,b in zip(snap.stats['fungal_bodies'],grown(age=115).render_snapshot.stats['fungal_bodies']):
        for k in ['id','socket_m','cap_width_m','variant_key']:assert a[k]==b[k]
        assert a['weathering_factor']==0<b['weathering_factor']
def test_all_native_assets_reopen_and_match_reviewed_pixels():
    pygame.init();pygame.display.set_mode((1,1));w=WorldModel()
    manifest=load_manifest(Path(f'assets/plant_asset_specs/{SID}.json'))
    for m in manifest['modules']:
        row=w.loader.get(m['illustration_id']);assert row['parents']==[SID]
        editor=PixelArtEditorUI(PixelEditorHost(w.loader));assert editor.open(row['id'])
        saved=pygame.image.load(row['media_path']);assert saved.get_size()==(75,75)
        assert pygame.image.tobytes(saved,'RGBA')==pygame.image.tobytes(render_module(m),'RGBA')
    pygame.quit()
