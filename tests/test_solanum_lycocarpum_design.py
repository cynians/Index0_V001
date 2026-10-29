"""Wolf Apple's reviewed tree/organ composition and editable art transport."""
import copy,gzip,json,math
from pathlib import Path
import pygame
import pytest
from world.world_model import WorldModel
from simulations.species.species_simulation import SpeciesSimulation
from simulations.species.plant_assets import PlantBlueprint,PlantGrowthSnapshot
from tools.author_plant_assets import load_manifest,render_module,PixelEditorHost,canvas_size
from ui.pixel_art_editor_ui import PixelArtEditorUI

SID='spec_solanum_lycocarpum'
@pytest.fixture(scope='module')
def world():return WorldModel()
def grown(world,age=430,lod=2,entity=None):
    s=SpeciesSimulation(world_model=world,species_id=SID,species_entity=entity,seed=303)
    s.set_lod(lod);s.set_age(age);return s

def test_live_taxonomy_identity_field_transport_and_unknown_dimensions(world):
    raw=world.loader.get(SID);e=world.resolved_species_entity(SID)
    assert world.loader.plant_catalogue.is_leaf_species(SID)
    assert raw['parents']==['cladis_solanum']
    assert raw['binomial_name']=='Solanum lycocarpum'
    assert raw['card_color']=='#2c3828' and raw['card_header_color']=='#3d5536'
    assert raw['related']==['spec_chrysocyon_brachyurus']
    payload=json.loads(Path(f'assets/species_trait_specs/{SID}.json').read_text())['updates']
    assert all(raw[k]==v and e[k]==v for k,v in payload.items())
    assert not any(k in raw for k in ['maturity_age','longevity','max_root_depth','frost_tolerance','temperature_range','soil_ph_range'])
    s=grown(world)
    assert s.blueprint.growth['shoot_distribution_grammar']==1
    assert s.blueprint.growth['lateral_axis_orientation']=='orthotropic'
    assert s.blueprint.growth['reproductive_profile']['fruit_size_m']==.10
    assert s.blueprint.module('leaf').length_m==.14
    assert s.render_snapshot.stats['root_model_status']=='unresolved'
    assert not any(p[0]=='root_section' for p in s.render_snapshot.placements)

def test_phase_structure_determinism_and_real_parent_sockets(world):
    stages=[grown(world,age) for age in [30,120,430,760]]
    counts=[(sum(p[0]=='flower' for p in s.render_snapshot.placements),
             sum(p[0]=='fruit' for p in s.render_snapshot.placements)) for s in stages]
    assert counts[:2]==[(0,0),(0,0)]
    assert counts[2][0]>0 and counts[2][1]==0
    assert counts[3][0]==0 and counts[3][1]>0
    for s in stages:
        snap=s.render_snapshot
        assert snap.to_dict()==grown(world,s.age_days).render_snapshot.to_dict()
        assert snap.to_dict()==PlantGrowthSnapshot.from_dict(snap.to_dict()).to_dict()
        for i,p in enumerate(snap.placements):
            assert p[1]<i
            assert all(math.isfinite(v) for v in p[2:])
            assert max(abs(v) for v in p[2:5])<10
            if p[0] in {'flower','fruit'}:
                assert snap.placements[p[1]][0]=='branch_section'
                assert math.dist(p[2:5],snap.placements[p[1]][2:5])<.001
    def anatomy(s):
        ps=s.render_snapshot.placements
        kept=[i for i,p in enumerate(ps) if p[0] not in {'flower','fruit'}]
        remap={old:new for new,old in enumerate(kept)};remap[-1]=-1
        return [[ps[i][0],remap[ps[i][1]],*ps[i][2:]] for i in kept]
    assert anatomy(stages[1])==anatomy(stages[2])==anatomy(stages[3])

def test_lod_canonical_ecology_portability_and_trait_driven_reuse(world):
    cases=[grown(world,430,lod) for lod in [0,1,2]]
    for key in ['estimated_leaf_count','leaf_area_m2','structural_axis_length_m','root_depth_m']:
        assert len({s.render_snapshot.stats[key] for s in cases})==1
    assert len({s.get_ecological_outcome()['leaf_area_proxy'] for s in cases})==1
    s=cases[-1]
    assert PlantBlueprint.from_dict(s.blueprint.to_dict()).fingerprint()==s.blueprint.fingerprint()
    e=copy.deepcopy(s.species_entity)
    for key,rng in s.blueprint.growth['architecture_ranges'].items():e['plant_'+key]=copy.deepcopy(rng)
    e.update(id='spec_unrelated_open_crown_fixture',parents=[],binomial_name='Synthetic fixture')
    other=SpeciesSimulation(species_entity=e,seed=303);other.set_lod(2);other.set_age(430)
    assert other.render_snapshot.stats['estimated_leaf_count']==s.render_snapshot.stats['estimated_leaf_count']
    assert any(p[0]=='flower' for p in other.render_snapshot.placements)
    more=copy.deepcopy(e);more['plant_leaf_cluster_density']=.6
    dense=SpeciesSimulation(species_entity=more,seed=303);dense.set_age(430)
    assert dense.blueprint.fingerprint()!=other.blueprint.fingerprint()
    assert dense.get_ecological_outcome()['leaf_area_proxy']>other.get_ecological_outcome()['leaf_area_proxy']

def test_all_five_modules_reopen_and_exactly_match_reviewed_native_pixels(world):
    pygame.init();pygame.display.set_mode((1,1))
    manifest=load_manifest(Path(f'assets/plant_asset_specs/{SID}.json'))
    assert {m['role'] for m in manifest['modules']}=={'leaf','flower','fruit','stem','branch'}
    for m in manifest['modules']:
        row=world.loader.get(m['illustration_id'])
        assert row['parents']==[SID] and row['plant_asset_role']==m['role']
        editor=PixelArtEditorUI(PixelEditorHost(world.loader));assert editor.open(row['id'])
        saved=pygame.image.load(row['media_path'])
        assert saved.get_size()==canvas_size(m['depicted_size_m'])==(75,75)
        assert pygame.image.tobytes(saved,'RGBA')==pygame.image.tobytes(render_module(m),'RGBA')
        with gzip.open(row['pixel_document_path'],'rt') as stream:assert json.load(stream)['version']==2
        assert row['depicted_size_m']==m['depicted_size_m']
    assert grown(world).blueprint.module('fruit').growth_axis[1]>0
    pygame.quit()

def test_biosphere_live_profile_and_reproduction_assurance(world):
    from simulations.biosphere.biosphere_simulation import BiosphereSimulation
    site=BiosphereSimulation.reference_site(world_model=world)
    site.ecology.introduce(SID,5,5,1.5,.8);site.representatives.sync_from_population(site.ecology)
    reps=site.representatives.items(alive_only=True);assert reps
    for rep in reps:
        s=rep.simulation;s.set_age(430)
        assert s.blueprint.fingerprint()==grown(world).blueprint.fingerprint()
        assert s.get_ecological_outcome()['leaf_area_proxy']>0
    s=grown(world)
    assert s.get_ecological_outcome({'pollination_availability':0})['fecundity']==0
