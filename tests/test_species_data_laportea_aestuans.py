"""Wood-nettle composition and generic leaf-angle renderer regression."""
import math
from pathlib import Path
from types import SimpleNamespace

import pygame
import pytest

from simulations.species.plant_assets import PlantBlueprint, PlantGrowthSnapshot
from simulations.species.species_renderer import (
    DiagnosticCamera, IsometricDiagnosticCamera, TopDownDiagnosticCamera, SpeciesRenderer,
)
from simulations.species.species_simulation import SpeciesSimulation
from world.world_model import WorldModel


@pytest.mark.parametrize("camera_type", [DiagnosticCamera, IsometricDiagnosticCamera, TopDownDiagnosticCamera])
@pytest.mark.parametrize("angle", [.2, .48, .7])
def test_authored_angle_drives_asset_projection_on_an_ordinary_iterative_forb(camera_type, angle):
    # This body plan has neither clonal nor umbellifer placement flags. It
    # previously computed the right direction, then ignored it for sprites.
    entity = {"id": "spec_synthetic_axillary_panicle", "plant_growth_form": "forb",
              "plant_woodiness": "herbaceous", "plant_growth_behaviour": "iterative_indeterminate",
              "leaf_attachment_pattern": "terminal_cluster", "leaf_arrangement": "alternate",
              "plant_flowering_position": "lateral", "plant_reproductive_structure": "panicle",
              "plant_leaf_attachment_angle": {"typical": angle}}
    sim = SpeciesSimulation(species_entity=entity, seed=303)
    sim.set_lod(2)
    sim.set_age(sim.mature_age_days)
    assert not sim.blueprint.growth.get("forb_leaf_placement_version")
    pygame.init()
    surface = pygame.Surface((640, 480))
    bounds = (-1., 1., -.1, 1.6) if camera_type is DiagnosticCamera else (
        (-1., 1., -1., 1.) if camera_type is TopDownDiagnosticCamera else (-1., 1., -1., 1., -.1, 1.6))
    camera = camera_type(640, 480, bounds)
    renderer = SpeciesRenderer(SimpleNamespace(camera=camera))
    calls = []

    def capture(_screen, _sim, _camera, kind, point, rotation, scale, **_kwargs):
        if kind == "leaf":
            calls.append((tuple(point), rotation, scale))
        return True

    renderer._draw_module_asset = capture
    leaves = {i for i, p in enumerate(sim.render_snapshot.placements) if p[0] == "leaf"}
    renderer._draw_individual(surface, sim, camera=camera, cache=False,
                             visible_indices=leaves, draw_environment=False, draw_ground_line=False)
    assert len(calls) == len(leaves)
    assert any(sim.render_snapshot.placements[i][1] in {
        j for j, p in enumerate(sim.render_snapshot.placements) if p[0] == "branch_section"
    } for i in leaves)
    ppm = renderer._projection_pixels_per_meter(camera)
    for point, rotation, scale in calls:
        index = next(i for i in leaves if tuple(renderer._placement_screen(
            camera, sim.render_snapshot.placements[i])) == point)
        placement = sim.render_snapshot.placements[index]
        forward = sim.render_snapshot.placement_orientations[str(index)]["forward"]
        target = [placement[a + 2] + forward[a] for a in range(3)]
        tip = renderer._placement_screen(camera, ["leaf_extent", -1, *target, 0, 1, 0])
        dx, dy = tip[0] - point[0], tip[1] - point[1]
        if abs(dx) + abs(dy) > 1e-6:
            assert rotation == pytest.approx(-math.degrees(math.atan2(dx, -dy)))
            assert scale == pytest.approx(placement[6] * math.hypot(dx, dy) / ppm)


@pytest.fixture(scope="module")
def live_species():
    world = WorldModel()
    return world, world.resolved_species_entity("spec_laportea_aestuans")


def test_unrelated_iterative_forb_retains_hidden_leaf_cohorts_at_lod_zero():
    entity = {"id": "spec_synthetic_small_perennial", "plant_growth_form": "forb",
              "plant_growth_behaviour": "iterative_indeterminate", "plant_woodiness": "herbaceous",
              "plant_lifespan": "perennial", "leaf_attachment_pattern": "along_stem",
              "leaf_arrangement": "opposite", "mature_height": {"max_m": .6}}
    sims = []
    for lod in (0, 1, 2):
        sim = SpeciesSimulation(species_entity=entity, seed=109)
        sim.set_lod(lod)
        sim.set_age(sim.mature_age_days)
        sims.append(sim)
    assert not any(p[0] == "leaf" for p in sims[0].render_snapshot.placements)
    assert sims[0].render_snapshot.stats["estimated_leaf_count"] > 0
    assert len({s.render_snapshot.stats["leaf_area_m2"] for s in sims}) == 1
    assert all(s.get_ecological_outcome({}) == sims[0].get_ecological_outcome({}) for s in sims)


def test_live_identity_researched_fields_and_assets(live_species):
    world, entity = live_species
    assert world.is_plant_species("spec_laportea_aestuans")
    assert entity["parents"] == ["cladis_wood_nettles_laportea"]
    assert entity["leaf_clustering"] == "solitary"
    assert entity["leaf_cluster_size"]["typical"] == 1
    assert entity["dispersal"] == ["water", "human"]
    assert not entity.get("maturity_age")
    assert not entity.get("max_root_depth")
    blueprint = PlantBlueprint.from_species_entity(entity, entity["id"])
    assert blueprint.growth["leaf_attachment_angle"] == .48
    assert blueprint.growth["reproductive_structure"] == "panicle"
    for kind in ("leaf", "stem_section", "branch_section", "flower"):
        assert Path(blueprint.module(kind).asset_ref).is_file()
    assert blueprint.module("flower").visual["depicted_size_m"] == .18


def test_saved_recipe_is_deterministic_bounded_and_portable(live_species):
    _, entity = live_species
    sims = []
    for lod in (0, 1, 2, 2):
        sim = SpeciesSimulation(species_entity=entity, species_id=entity["id"], seed=303)
        sim.set_lod(lod)
        sim.set_age(sim.life_history_profile["reproductive_start_days"] + 50)
        sims.append(sim)
    assert sims[-1].render_snapshot.to_dict() == sims[-2].render_snapshot.to_dict()
    assert PlantBlueprint.from_dict(sims[-1].blueprint.to_dict()).fingerprint() == sims[-1].blueprint.fingerprint()
    assert PlantGrowthSnapshot.from_dict(sims[-1].render_snapshot.to_dict()).to_dict() == sims[-1].render_snapshot.to_dict()
    for key in ("estimated_leaf_count", "leaf_area_m2", "root_depth_m", "root_length_m"):
        assert len({s.render_snapshot.stats[key] for s in sims}) == 1
    assert all(s.get_ecological_outcome({}) == sims[0].get_ecological_outcome({}) for s in sims)
    for i, placement in enumerate(sims[-1].render_snapshot.placements):
        assert placement[1] == -1 or 0 <= placement[1] < i
        assert all(math.isfinite(v) for v in placement[2:7])
    assert sum(p[0] == "flower" for p in sims[-1].render_snapshot.placements) == 3
    assert sims[-1].render_snapshot.stats["root_depth_source"] == "runtime_default"
