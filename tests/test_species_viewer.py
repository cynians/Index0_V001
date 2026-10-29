"""The multi-view diagnostic fits real authored plants beyond water lilies."""
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pygame
import pytest

from tools.render_species_views import fitted_bounds, render, stage_ages
from world.persistent_ontology_store import PersistentOntologyStore
from world.plant_traits import PLANT_TRAIT_FIELDS
from world.species_inheritance import is_authored_field


ROOT = Path(__file__).resolve().parents[1]


def saved_rose():
    datasets = PersistentOntologyStore(ROOT / "ontology/index0.owl").load_datasets()
    return next(row for row in datasets["species"] if row["id"] == "spec_rosa_woodsii")


def test_fit_contains_tall_shoots_deep_roots_and_all_stages():
    snapshots = [SimpleNamespace(bounds_m=[-5,6,-4,3,-3,25]),
                 SimpleNamespace(bounds_m=[-6,4,-2,5,-4,12])]
    fitted = fitted_bounds(snapshots)
    for snap in snapshots:
        for axis in range(3):
            assert fitted[2*axis] < snap.bounds_m[2*axis]
            assert fitted[2*axis+1] > snap.bounds_m[2*axis+1]
    assert fitted[-1] > 25
    flat = fitted_bounds([SimpleNamespace(bounds_m=[0,0,0,0,0,0])])
    assert all(flat[2*a+1] > flat[2*a] for a in range(3))


def test_water_context_expands_to_fit_large_aquatic_plants():
    bounds = [-2,2,-1,1,-1,.5]
    fitted = fitted_bounds([SimpleNamespace(bounds_m=bounds)], aquatic=True)
    assert fitted[0] < -2 and fitted[1] > 2
    assert fitted[4] < -1 and fitted[5] > .5


def test_stages_use_saved_fruit_recipe_and_leave_missing_fruit_unconfigured():
    sim = SimpleNamespace(mature_age_days=120,
                          life_history_profile={"reproductive_start_days":127.75},
                          blueprint=SimpleNamespace(growth={}),
                          life_state=lambda age:{"fruiting_factor":1})
    assert len(stage_ages(sim)) == 3
    sim.blueprint.growth["reproductive_profile"] = {"cycle_days":365,"fruit_ripe":.68}
    assert stage_ages(sim)[-1][0] == "Fruiting"
    assert stage_ages(sim)[-1][1] == pytest.approx(248.2)


def test_real_authored_rose_renders_without_mutating_live_fields():
    before = saved_rose()
    assert sum(is_authored_field(before,k) for k in PLANT_TRAIT_FIELDS) > 10
    scratch = ROOT / "artifacts" / f".viewer_test_{uuid4().hex}"
    assert scratch.resolve().parent == (ROOT / "artifacts").resolve()
    scratch.mkdir()
    try:
        render("spec_rosa_woodsii", scratch)
        report = json.loads((scratch/"after.json").read_text())
        assert pygame.image.load(scratch/"after.png").get_size() == (1540,1030)
    finally:
        (scratch/"after.png").unlink(missing_ok=True)
        (scratch/"after.json").unlink(missing_ok=True)
        scratch.rmdir()
    assert report["aquatic_context"] is False
    assert report["bounds_m"][5] > 1.5
    labels = [s['label'] for s in report['stages']]
    expected = ['Young growth','Full size','Flowering','Fruiting']
    # Authored turnover adds a real fifth state; its absence must stay absent.
    if 'leaf_fall_end' in (before.get('plant_reproductive_profile') or {}):
        expected.append('Leafless season')
    if (before.get('plant_shoot_profile') or {}).get('form') == 'renewing_canes':
        expected = ['Young canes', 'Flowering', 'Hips', 'Winter framework', 'Next flowering']
    assert labels == expected
    flowering = next(stage['snapshot'] for stage in report['stages'] if stage['label'] == 'Flowering')
    fruiting = next(stage['snapshot'] for stage in report['stages'] if stage['label'] in {'Fruiting', 'Hips'})
    assert sum(p[0]=="flower" for p in flowering["placements"]) > 0
    assert sum(p[0]=="fruit" for p in fruiting["placements"]) > 0
    assert flowering["stats"]["root_model_status"] == "unresolved"
    assert not any(p[0]=="root_section" for p in flowering["placements"])
    assert saved_rose() == before
