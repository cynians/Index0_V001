"""Live sand verbena composition and reusable petiole/head mechanics."""
from copy import deepcopy
import gzip
import json
import math
from pathlib import Path

import pygame
import pytest

from simulations.species.creeping_herbs import creeping_herb_profile
from simulations.species.inflorescences import inflorescence_profile
from simulations.species.plant_assets import PlantBlueprint, PlantGrowthSnapshot
from simulations.species.species_simulation import SpeciesSimulation
from simulations.species.umbellate_heads import head_units, umbellate_head_profile, umbellate_head_surface
from tools.author_plant_assets import load_manifest, validate_manifest, ManifestError
from tools.author_plant_species import validate_updates, AuthoringError
from world.world_model import WorldModel

ROOT = Path(__file__).resolve().parents[1]
SID = 'spec_abronia_angustifolia'


def entity():
    return {'id':'spec_unrelated_annual_flower_head_herb', **deepcopy(json.loads(
        (ROOT/'assets/species_trait_specs'/f'{SID}.json').read_text())['updates'])}


def sim(data=None, day=156.95, lod=2):
    result = SpeciesSimulation(species_entity=data or entity(), seed=303)
    result.set_age(day); result.set_lod(lod)
    return result


def test_live_fields_ancestry_unknown_roots_and_editable_modules():
    world = WorldModel(); raw = world.loader.get(SID); resolved = world.resolved_species_entity(SID)
    assert world.loader.plant_catalogue.is_leaf_species(SID)
    assert raw['parents'] == ['cladis_sand_verbenas_abronia']
    for key,value in entity().items():
        if key != 'id':
            assert raw[key] == resolved[key] == value
    bp = PlantBlueprint.from_species_entity(resolved,SID)
    assert bp.growth['reproductive_structure'] == 'flower'
    assert bp.growth['umbellate_head_version'] == 1
    assert bp.growth['creeping_herb_profile_version'] == 2
    assert bp.module('flower').length_m == .007
    assert bp.module('fruit').length_m == .008
    for role in ('leaf','stem_section','branch_section','flower'):
        asset = ROOT/bp.module(role).asset_ref
        assert asset.is_file()
        document = asset.with_name(asset.name.replace('_pixel.png','_pixel.layers.json.gz'))
        with gzip.open(document,'rt',encoding='utf-8') as handle:
            assert json.load(handle)['version'] == 2
    assert bp.module('root').asset_ref is None
    assert bp.module('fruit').asset_ref is None
    assert sim().render_snapshot.stats['root_model_status'] == 'unresolved'


@pytest.mark.parametrize('changes',[{'flower_count':65},{'flower_count':True},{'flower_size_m':math.nan},
    {'tube_length_m':.05},{'fruit_size_m':0},{'axis_color':[True,0,0]},{'unit':'capitulum'}])
def test_invalid_head_recipe_is_neutral_and_rejected(changes):
    data = entity(); profile = {**data['plant_inflorescence_profile'],**changes}
    assert umbellate_head_profile(profile) is None
    with pytest.raises(AuthoringError): validate_updates({'plant_inflorescence_profile':profile})
    a = sim({**data,'plant_inflorescence_profile':None})
    b = sim({**data,'plant_inflorescence_profile':profile})
    assert a.blueprint.fingerprint() == b.blueprint.fingerprint()


@pytest.mark.parametrize('changes',[{'petiole_length_m':math.inf},{'petiole_length_m':.071},
    {'paired_leaf_size_ratio':False},{'paired_leaf_size_ratio':0},{'leaf_pitch_deg':86}])
def test_bad_petiole_and_pair_controls_are_rejected(changes):
    profile = {**entity()['plant_shoot_profile'],**changes}
    assert creeping_herb_profile(profile) is None
    with pytest.raises(AuthoringError): validate_updates({'plant_shoot_profile':profile})


def test_neutral_extensions_preserve_previous_creeping_recipe():
    profile = deepcopy(entity()['plant_shoot_profile'])
    for key in ('petiole_length_m','paired_leaf_size_ratio','leaf_pitch_deg'): profile.pop(key)
    assert creeping_herb_profile(profile) == creeping_herb_profile(
        {**profile,'petiole_length_m':0.,'paired_leaf_size_ratio':1.})
    assert creeping_herb_profile(profile)['version'] == 1


def test_real_petiole_sockets_unequal_pairs_and_progressive_height():
    mature = sim(); snap = mature.render_snapshot
    assert snap.to_dict() == sim().render_snapshot.to_dict()
    assert snap.stats['creeping_rooting_contact_count'] == 0
    assert snap.bounds_m[5] < .3
    assert sim(day=4).render_snapshot.bounds_m[5] < sim(day=20).render_snapshot.bounds_m[5] < snap.bounds_m[5]
    for cohort in snap.leaf_clusters:
        pair = cohort['sample_placement_indices']
        assert len(pair) == 2
        a,b = [snap.placements[i] for i in pair]
        assert b[6]/a[6] == pytest.approx(.7)
        for index in pair:
            leaf = snap.placements[index]; petiole = snap.placements[leaf[1]]
            axis = snap.placements[petiole[1]]
            assert petiole[0] == 'branch_section'
            assert leaf[2:5] == petiole[2:5]
            # Snapshot coordinates use a 0.1 mm grid; endpoint differences
            # can accumulate up to 0.2 mm of distance rounding.
            assert math.dist(axis[2:5],petiole[2:5]) == pytest.approx(.02*leaf[6],abs=.0002)
            direction = snap.placement_orientations[str(index)]['forward']
            assert direction[2] == pytest.approx(math.sin(math.radians(28)),abs=1e-5)
    for i,p in enumerate(snap.placements):
        assert p[1] == -1 or 0 <= p[1] < i
        assert all(math.isfinite(v) for v in p[2:7])
    assert len(snap.placements) < 1000


def test_flower_limb_tube_geometry_and_count_are_display_only():
    data = entity(); profile = inflorescence_profile(data['plant_inflorescence_profile'])
    units = list(head_units(profile))
    assert len(units) == 20
    assert all(math.dist((0,0,0),point) == pytest.approx(.015) for point in units)
    assert min(p[2] for p in units) < 0 < max(p[2] for p in units)
    changed = deepcopy(data); changed['plant_inflorescence_profile']['flower_count'] = 40
    a,b = sim(data),sim(changed)
    assert a.render_snapshot.placements == b.render_snapshot.placements
    assert a.get_ecological_outcome() == b.get_ecological_outcome()
    assert a.blueprint.fingerprint() != b.blueprint.fingerprint()
    wrong = sim({**data,'plant_reproductive_structure':'capitulum'})
    assert 'umbellate_head_version' not in wrong.blueprint.growth


def test_head_rendering_is_bounded_repeatable_and_distinguishes_fruit():
    pygame.init(); pygame.display.set_mode((1,1))
    profile = inflorescence_profile(entity()['plant_inflorescence_profile'])
    for ppm in (12.,300.,24000.):
        flower,anchor = umbellate_head_surface(profile,ppm)
        repeat,_ = umbellate_head_surface(profile,ppm)
        fruit,_ = umbellate_head_surface(profile,ppm,fruit=True)
        assert max(flower.get_size()) <= 1024
        assert 0 <= anchor[0] <= flower.get_width()
        assert 0 <= anchor[1] <= flower.get_height()
        assert pygame.image.tobytes(flower,'RGBA') == pygame.image.tobytes(repeat,'RGBA')
        assert pygame.image.tobytes(flower,'RGBA') != pygame.image.tobytes(fruit,'RGBA')
    pygame.quit()


def test_seasons_lod_portability_and_biosphere_handoff():
    from simulations.biosphere.representatives import RepresentativeBody
    for day,kind in ((10,None),(156.95,'flower'),(262.8,'fruit'),(400,None)):
        simulations = [sim(day=day,lod=lod) for lod in (0,1,2)]
        snap = simulations[2].render_snapshot
        assert PlantGrowthSnapshot.from_dict(snap.to_dict()).to_dict() == snap.to_dict()
        assert PlantBlueprint.from_dict(simulations[2].blueprint.to_dict()).fingerprint() == simulations[2].blueprint.fingerprint()
        for coarse in simulations:
            assert coarse.get_ecological_outcome() == simulations[2].get_ecological_outcome()
            assert coarse.render_snapshot.stats['leaf_area_m2'] == snap.stats['leaf_area_m2']
        organs = [p for p in snap.placements if p[0] in {'flower','fruit'}]
        if kind: assert organs and all(p[0] == kind for p in organs)
        else: assert not organs
        if day==400: assert simulations[2].life_state()['phase']=='dead'
    body = RepresentativeBody(species_entity=entity(),seed=303);body.set_age(156.95);body.set_lod(2)
    assert body.get_ecological_outcome() == sim().get_ecological_outcome()


@pytest.mark.parametrize('age',[-1,True,math.nan,math.inf])
def test_fixed_preview_age_validation(age):
    plan = load_manifest(ROOT/'assets/plant_asset_specs'/f'{SID}.json')
    plan['preview']['age_days'] = age
    with pytest.raises(ManifestError): validate_manifest(plan)
