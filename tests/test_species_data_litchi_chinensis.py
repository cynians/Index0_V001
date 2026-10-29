"""Live lychee composition and reusable compound-tree foliage rendering."""

import math
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pygame
import pytest

from simulations.species.plant_assets import PlantBlueprint, PlantGrowthSnapshot
from simulations.species.species_renderer import DiagnosticCamera, SpeciesRenderer
from simulations.species.species_simulation import SpeciesSimulation
from world.plant_catalogue import PlantCatalogue
from world.world_model import WorldModel


SPECIES_ID = "spec_litchi_chinensis"


@pytest.fixture(scope="module")
def world():
    return WorldModel()


def grown(entity, lod=2):
    sim = SpeciesSimulation(species_entity=entity, seed=303)
    sim.set_lod(lod)
    sim.set_age(sim.blueprint.growth["life_history"]["reproductive_start_days"] + 60)
    return sim


def test_live_identity_transport_assets_and_unknowns(world):
    raw = world.loader.get(SPECIES_ID)
    resolved = world.resolved_species_entity(SPECIES_ID)
    assert PlantCatalogue.build(world.loader.entities).is_species(SPECIES_ID)
    assert raw["parents"] == ["cladis_nephelieae"]
    blueprint = PlantBlueprint.from_species_entity(resolved, SPECIES_ID)
    for field, internal in {
        "plant_growth_form": "growth_form", "leaf_structure": "leaf_structure",
        "plant_axis_continuity": "axis_continuity",
        "plant_reproductive_structure": "reproductive_structure",
        "root_architecture": "root_architecture",
    }.items():
        assert raw[field] == resolved[field] == blueprint.growth[internal]
    assert blueprint.growth["leaf_length_m"] == pytest.approx(.1651)
    assert blueprint.growth["leaflet_length_m"] == pytest.approx(.1)
    assert blueprint.growth["leaflet_count"] == 6
    assert blueprint.growth["self_pruning"] == "other_unknown"
    assert not raw.get("max_root_depth")
    assert not raw.get("maturity_age")
    assert not raw.get("longevity")
    for role, kind in {"leaf": "leaf", "stem": "stem_section", "branch": "branch_section",
                       "flower": "flower", "fruit": "fruit"}.items():
        ref = raw[f"plant_{role}_module_ref"]
        assert blueprint.module(kind).asset_ref == ref
        assert Path(ref).is_file()
    assert blueprint.module("fruit").visual["depicted_size_m"] == pytest.approx(.038)


def test_snapshot_is_deterministic_bounded_connected_and_portable(world):
    entity = world.resolved_species_entity(SPECIES_ID)
    sim = grown(entity)
    snapshot = sim.render_snapshot
    assert snapshot.to_dict() == grown(entity).render_snapshot.to_dict()
    assert snapshot.to_dict() == PlantGrowthSnapshot.from_dict(snapshot.to_dict()).to_dict()
    assert sim.blueprint.to_dict() == PlantBlueprint.from_dict(sim.blueprint.to_dict()).to_dict()
    assert snapshot.stats["estimated_leaf_count"] > 10000
    assert any(p[0] == "flower" for p in snapshot.placements)
    assert any(p[0] == "fruit" for p in snapshot.placements)
    assert len(snapshot.placements) < 10000
    for index, p in enumerate(snapshot.placements):
        assert p[1] == -1 or 0 <= p[1] < index
        assert all(math.isfinite(value) for value in p[2:7])
        assert abs(p[4]) < 25
    for lod in (0, 1):
        outcome = grown(entity, lod).get_ecological_outcome()
        for key in ("estimated_leaf_count", "structural_biomass_proxy", "resource_demand"):
            assert outcome[key] == sim.get_ecological_outcome()[key]


def test_visual_controls_increase_foliage_and_reduce_trunk_deviation(world):
    entity = world.resolved_species_entity(SPECIES_ID)
    control = deepcopy(entity)
    for field in ("plant_crown_openness", "plant_fine_twig_density",
                  "plant_leaf_cluster_density", "plant_trunk_straightness"):
        control.pop(field)
    before, after = grown(control), grown(entity)
    assert after.blueprint.fingerprint() != before.blueprint.fingerprint()
    assert after.render_snapshot.stats["leaf_cluster_count"] > before.render_snapshot.stats["leaf_cluster_count"]
    assert after.render_snapshot.stats["estimated_leaf_count"] > before.render_snapshot.stats["estimated_leaf_count"]
    deviation = lambda sim: max(math.hypot(p[2], p[3]) for p in sim.render_snapshot.placements
                                if p[0] == "stem_section" and p[7] == 1)
    assert deviation(after) < .25 * deviation(before)
    assert after.blueprint.module("leaf").length_m == before.blueprint.module("leaf").length_m


@pytest.mark.parametrize("structure", ["pinnately_compound", "palmately_compound"])
def test_compound_tree_editor_samples_cohort_and_preserves_explicit_budgets(structure):
    # No real species ID or asset is needed to exercise the corrected path.
    entity = dict(id="spec_synthetic_compound_crown", plant_growth_form="tree",
                  plant_growth_behaviour="branched_woody", leaf_structure=structure,
                  plant_leaf_distribution="along_shoot", mature_height={"max_m": 5},
                  leaf_length={"typical_m": .16}, plant_leaf_cluster_density={"typical": .85})
    sim = grown(entity)
    snapshot_before = sim.render_snapshot.to_dict()
    ecology_before = sim.get_ecological_outcome()
    pygame.init()
    camera = DiagnosticCamera(700, 600, (-5, 5, -2, 7))
    renderer = SpeciesRenderer(SimpleNamespace(camera=None))
    calls = []
    renderer._draw_module_asset = lambda _s, _sim, _c, kind, point, rotation, scale, **kw: (
        calls.append((point, scale)) if kind == "leaf" else None) or True
    panel = pygame.Surface((700, 600))
    renderer._draw_editor_plant_panel(panel, sim, camera, foliage_cap=2)
    limited = list(calls)
    calls.clear()
    renderer._draw_editor_plant_panel(panel, sim, camera, foliage_cap=10)
    detailed = list(calls)
    clusters = len(sim.render_snapshot.leaf_clusters)
    assert len(limited) == clusters * 2
    assert clusters * 10 < len(detailed) <= clusters * 64
    assert {scale for _point, scale in limited} == {scale for _point, scale in detailed}
    assert all(math.isfinite(v) for point, _scale in detailed for v in point)
    assert sim.render_snapshot.to_dict() == snapshot_before
    assert sim.get_ecological_outcome() == ecology_before
    # Use a fresh renderer: the instrumented draws above populate its image
    # cache with deliberately blank leaf sprites.
    renderer = SpeciesRenderer(SimpleNamespace(camera=None))
    green_pixels = []
    for cap in (2, 10):
        renderer._draw_editor_plant_panel(panel, sim, camera, foliage_cap=cap)
        green_pixels.append(sum(panel.get_at((x, y)).g > panel.get_at((x, y)).r * 1.15
                                and panel.get_at((x, y)).g > 40
                                for y in range(600) for x in range(700)))
    assert green_pixels[1] > green_pixels[0] * 1.5
    renderer._draw_module_asset = lambda _s, _sim, _c, kind, point, rotation, scale, **kw: (
        calls.append((point, scale)) if kind == "leaf" else None) or True
    # A non-compound tree retains the established ten-sample editor budget.
    entity["leaf_structure"] = "simple"
    simple = grown(entity)
    calls.clear()
    renderer._draw_editor_plant_panel(panel, simple, camera, foliage_cap=10)
    assert len(calls) == len(simple.render_snapshot.leaf_clusters) * 10


@pytest.mark.parametrize("density", [0, None, "other_unknown"])
def test_missing_zero_unknown_density_remains_bounded(density):
    entity = dict(id="spec_synthetic_unknown_compound", plant_growth_form="tree",
                  leaf_structure="pinnately_compound", plant_leaf_distribution="along_shoot",
                  mature_height={"max_m": 4}, plant_leaf_cluster_density=density)
    sim = grown(entity)
    assert 0 <= sim.blueprint.growth["leaf_cluster_density"] <= 1
    assert len(sim.render_snapshot.placements) < 10000
    assert all(math.isfinite(v) for p in sim.render_snapshot.placements for v in p[2:7])
