import math
import sqlite3
import shutil
import uuid
import tempfile
from pathlib import Path
import pytest

from simulations.species.plant_assets import PlantBlueprint, PlantGrowthSnapshot
from simulations.species.species_simulation import SpeciesSimulation
from simulations.species.species_diagnostics import build_growth_gallery


ENTITY = {'id': 'test_tuft', 'plant_growth_form': 'graminoid',
          'plant_growth_behaviour': 'tussock_tillering',
          'plant_lifespan': 'short_lived_perennial', 'clonal_spread': 'low',
          'resprouting': 'strong', 'regeneration_strategy': 'mixed'}


def make(**overrides):
    sim = SpeciesSimulation(species_entity={**ENTITY, **overrides}, seed=101)
    sim.set_age(200)
    return sim


def test_spread_is_bounded_monotonic_and_does_not_change_counts():
    cases = [make(clonal_spread=value) for value in ('none', 'low', 'moderate', 'high')]
    radii = [s.render_snapshot.stats['tiller_radius_m'] for s in cases]
    assert radii == sorted(set(radii)) and radii[-1] < .25
    assert len({s.render_snapshot.stats['tiller_count'] for s in cases}) == 1
    assert len({s.render_snapshot.stats['estimated_leaf_count'] for s in cases}) == 1
    for value in (None, 'other_unknown', 'bad_value'):
        assert make(clonal_spread=value).render_snapshot.placements == cases[1].render_snapshot.placements


def test_disturbance_response_has_cost_and_only_modulates_disturbance():
    cases = [make(resprouting=value) for value in ('absent', 'weak', 'moderate', 'strong')]
    outcomes = [s.get_ecological_outcome({'disturbance': .6}) for s in cases]
    vitality = [o['vitality'] for o in outcomes]
    assert vitality == sorted(set(vitality))
    assert vitality[-1] < cases[-1].get_ecological_outcome({})['vitality']
    assert len({s.get_ecological_outcome({'water_stress': .6})['vitality'] for s in cases}) == 1
    for value in (None, 'other_unknown', 'bad_value'):
        assert make(resprouting=value).get_ecological_outcome({'disturbance': .6})['vitality'] == vitality[0]
    assert cases[0].get_ecological_outcome({'disturbance': -2})['disturbance_penalty'] == 0
    assert cases[0].get_ecological_outcome({'disturbance': 2})['disturbance_penalty'] == 1


def test_tiller_geometry_attachments_and_ecology_are_deterministic_and_lod_stable():
    sim = make()
    snapshots = [sim.generate_snapshot(lod=lod) for lod in range(3)]
    for key in ('tiller_count', 'tiller_radius_m', 'estimated_leaf_count', 'leaf_area_m2', 'stem_count'):
        assert len({s.stats[key] for s in snapshots}) == 1
    assert snapshots[2].to_dict() == sim.generate_snapshot(lod=2).to_dict()
    assert PlantGrowthSnapshot.from_dict(snapshots[2].to_dict()).to_dict() == snapshots[2].to_dict()
    rebuilt = PlantBlueprint.from_dict(sim.blueprint.to_dict())
    assert rebuilt.fingerprint() == sim.blueprint.fingerprint()
    assert rebuilt.growth['resprouting'] == 'strong'
    assert rebuilt.fingerprint() != make(resprouting='absent').blueprint.fingerprint()
    for snapshot in snapshots:
        for i, p in enumerate(snapshot.placements):
            assert p[1] < i and p[0] in snapshot.modules
            assert all(math.isfinite(v) for v in p[2:])
            if p[0] in ('leaf', 'flower'):
                assert p[2:5] == snapshot.placements[p[1]][2:5]
    assert any(p[0] == 'flower' for p in snapshots[1].placements)
    assert len(snapshots[1].attachment_points) == snapshots[1].stats['estimated_leaf_count']
    assert sim.generate_snapshot(age_days=0).stats['estimated_leaf_count'] == 0
    assert not any(p[0] == 'flower' for p in sim.generate_snapshot(age_days=1).placements)


def test_tussock_gallery_includes_flowering_and_real_seedling():
    cases = build_growth_gallery(ENTITY, lod=1)
    assert len(cases) == 20
    assert cases[0].age_days > 0
    reproductive = [c for c in cases if c.stage == 'reproductive']
    assert len(reproductive) == 4
    assert all(any(p[0] == 'flower' for p in c.snapshot.placements) for c in reproductive)


@pytest.fixture
def writable_temp():
    # Windows Python 3.14's restrictive mkdir mode is incompatible with this
    # workspace's managed ACLs; use the inherited permissions instead.
    path = Path(tempfile.gettempdir()) / ("lolium-test-" + uuid.uuid4().hex)
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path)


def test_new_trait_property_recovers_stale_import_allocator(writable_temp):
    tmp_path = writable_temp
    from world.ontology_repository import OntologyRepository
    from world.persistent_ontology_store import PersistentOntologyStore
    path = tmp_path/'index0.owl'
    db = tmp_path/'store.sqlite3'
    OntologyRepository({'species': [ENTITY]}).save_owl(path)
    store = PersistentOntologyStore(path, database_path=db)
    entity = store.load_datasets()['species'][0]
    with sqlite3.connect(db) as connection:
        connection.execute('UPDATE store SET current_resource=300')
    connection.close()
    entity['new_test_trait'] = 'strong'
    assert store.persist_entity_fields(entity, ['new_test_trait'])
    assert PersistentOntologyStore(path, database_path=db).load_datasets()['species'][0]['new_test_trait'] == 'strong'
