"""Saved chicory artwork changes appearance without changing its biology."""
from copy import deepcopy
import json
from pathlib import Path

import pygame
import pytest

from tools.author_plant_assets import load_manifest, render_module, validate_manifest, ManifestError
from tools.render_species_views import canopy_envelope, fitted_bounds
from simulations.species.species_simulation import SpeciesSimulation
from world.world_model import WorldModel

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "assets/plant_asset_specs/spec_cichorium_intybus.json"


@pytest.fixture(scope="module",autouse=True)
def pixels():
    pygame.init();pygame.display.set_mode((1,1))
    yield
    pygame.quit()


def test_blue_ray_head_is_physical_rgba_and_has_no_yellow_disc():
    plan = load_manifest(PLAN)
    # The later habit refinement adds only a visual shoot recipe.
    assert set(plan["species_field_updates"]) == {"plant_shoot_profile"}
    flower = next(m for m in plan["modules"] if m["role"]=="flower")
    surface = render_module(flower)
    assert surface.get_size() == (75,75)
    assert flower["depicted_size_m"] == .04
    colours = [surface.get_at((x,y)) for x in range(75) for y in range(75)
               if surface.get_at((x,y)).a]
    assert all(c.b > c.r for c in colours)
    assert surface.get_at((37,37)).b > 200
    assert surface.get_at((0,0)).a == 0


@pytest.mark.parametrize("key,value",[("count",49),("count",True),("ray_width",float("nan")),
                                    ("ray_width",1000),("outer_radius",1000),("inner_radius",33)])
def test_ligulate_primitive_rejects_unbounded_or_invalid_geometry(key,value):
    plan = deepcopy(load_manifest(PLAN))
    next(m for m in plan["modules"] if m["role"]=="flower")["operations"][0][key] = value
    with pytest.raises(ManifestError):validate_manifest(plan)


def test_asset_mockup_keeps_canonical_growth_and_ecology():
    raw = json.loads((ROOT/"tests/fixtures/species/chicory_asset_control.json").read_text())["resolved"]
    proposed = deepcopy(raw)
    for module in load_manifest(PLAN)["modules"]:
        proposed[f"plant_{module['role']}_module_ref"] = f"assets/illustrations/{module['illustration_id']}_pixel.png"
    control, treatment = [SpeciesSimulation(species_entity=data, seed=303) for data in (raw,proposed)]
    for sim in (control,treatment):sim.set_age(sim.life_history_profile["reproductive_start_days"]+50)
    assert control.render_snapshot.placements == treatment.render_snapshot.placements
    assert control.get_ecological_outcome() == treatment.get_ecological_outcome()
    assert control.blueprint.fingerprint() != treatment.blueprint.fingerprint()


def test_hidden_deep_roots_do_not_determine_canopy_frame():
    world = WorldModel()
    sim = SpeciesSimulation(world_model=world,species_id="spec_cichorium_intybus",seed=303)
    sim.set_age(sim.life_history_profile["reproductive_start_days"]+50)
    snap = sim.render_snapshot
    canopy = canopy_envelope(sim,[snap])
    anatomy = fitted_bounds([snap])
    assert anatomy[4] < -1
    assert canopy[4] > -.2
    assert canopy[1]-canopy[0] < anatomy[1]-anatomy[0]
    assert canopy[5] >= snap.bounds_m[5]
