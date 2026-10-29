"""Composition contracts for flowering herbaceous clone shoots."""
import math
from copy import deepcopy

import pytest

from simulations.species.plant_assets import PlantBlueprint
from simulations.species.species_simulation import SpeciesSimulation


def entity(**updates):
    data = {
        "id": "spec_synthetic_creeping_herb",
        "plant_growth_form": "forb",
        "plant_woodiness": "herbaceous",
        "plant_growth_behaviour": "stoloniferous_clonal",
        "plant_lifespan": "perennial",
        "leaf_attachment_pattern": "along_stem",
        "leaf_arrangement": "alternate",
        "leaf_size_class": "medium",
        "plant_flowering_position": "terminal",
        "plant_reproductive_structure": "flower",
        "reproductive_mode": "both",
        "clonal_spread": "moderate",
        "mature_height": {"min_m": .4, "max_m": 1.0},
        "leaf_length": {"min_m": .06, "max_m": .12},
    }
    data.update(updates)
    return data


def simulation(data=None, lod=2, juvenile=False):
    sim = SpeciesSimulation(species_entity=data or entity(), seed=41)
    start = sim.blueprint.growth["life_history"]["reproductive_start_days"]
    sim.set_age(start * .1 if juvenile else start + 5)
    sim.set_lod(lod)
    return sim


@pytest.mark.parametrize("behaviour", ["suckering_clonal", "rhizomatous_clonal", "stoloniferous_clonal"])
def test_reuses_leafy_flowering_forb_grammar_across_clone_topologies(behaviour):
    sim = simulation(entity(plant_growth_behaviour=behaviour))
    snap = sim.render_snapshot
    assert snap.stats["clonal_forb_shoot_count"] == snap.stats["clonal_ramet_count"]
    assert snap.stats["composed_growth_grammars"] == ["iterative_forb_shoots", behaviour]
    flowers = [p for p in snap.placements if p[0] == "flower"]
    assert len(flowers) > snap.stats["clonal_ramet_count"]
    assert {snap.placements[int(p[1])][0] for p in flowers} == {"stem_section", "branch_section"}
    assert all(p[4] > .2 for p in flowers)
    # Real-sized organs are not scaled down again by a qualitative size class.
    assert max(p[6] for p in snap.placements if p[0] == "leaf" and p[7] == 2) > .95


@pytest.mark.parametrize("updates", [
    {"reproductive_mode": "vegetative"},
    {"plant_reproductive_structure": "other_unknown"},
    {"plant_flowering_position": "other_unknown"},
])
def test_unresolved_or_vegetative_reproduction_does_not_invent_terminal_heads(updates):
    assert not any(p[0] == "flower" for p in simulation(entity(**updates)).render_snapshot.placements)


def test_juvenile_clone_has_no_flowers():
    assert not any(p[0] == "flower" for p in simulation(juvenile=True).render_snapshot.placements)


def test_lateral_flowers_remain_lateral():
    snap = simulation(entity(plant_flowering_position="lateral")).render_snapshot
    flowers = [p for p in snap.placements if p[0] == "flower"]
    assert flowers
    assert all(snap.placements[int(p[1])][0] == "stem_section" for p in flowers)


@pytest.mark.parametrize("updates", [
    {"plant_growth_form": "graminoid"},
    {"plant_woodiness": "woody"},
    {"leaf_attachment_pattern": "basal"},
    {"leaf_attachment_pattern": "other_unknown"},
])
def test_other_growth_paths_do_not_select_clonal_forb_composition(updates):
    blueprint = PlantBlueprint.from_species_entity(entity(**updates))
    assert "clonal_forb_shoot_grammar_version" not in blueprint.growth


def test_deterministic_bounded_geometry_valid_parents_and_serialization():
    first, second = simulation(), simulation()
    snap = first.render_snapshot
    assert snap.to_dict() == second.render_snapshot.to_dict()
    assert type(snap).from_dict(snap.to_dict()).to_dict() == snap.to_dict()
    assert PlantBlueprint.from_dict(first.blueprint.to_dict()).fingerprint() == first.blueprint.fingerprint()
    assert len(snap.placements) < 2000
    for i, p in enumerate(snap.placements):
        assert p[1] == -1 or 0 <= p[1] < i
        assert all(math.isfinite(float(v)) for v in p[2:7])
    leaves = {i for i, p in enumerate(snap.placements) if p[0] == "leaf"}
    assert {a["leaf_placement_index"] for a in snap.attachment_points} == leaves


def test_canonical_shoots_clone_layout_and_ecological_metrics_are_lod_stable():
    sims = [simulation(lod=lod) for lod in (0, 1, 2)]
    structural = [[(p[0], *p[2:]) for p in s.render_snapshot.placements
                   if p[0] in {"stem_section", "branch_section"}] for s in sims]
    assert structural[0] == structural[1] == structural[2]
    outcomes = [s.get_ecological_outcome({}) for s in sims]
    for key in ("vitality", "fecundity", "leaf_area_proxy", "root_depth_m"):
        assert outcomes[0][key] == outcomes[1][key] == outcomes[2][key]
    assert not any(p[0] == "leaf" for p in sims[0].render_snapshot.placements)
    assert not any(p[0] == "flower" for p in sims[1].render_snapshot.placements)


def test_grammar_version_participates_in_fingerprint():
    blueprint = simulation().blueprint
    changed = deepcopy(blueprint)
    changed.growth["clonal_forb_shoot_grammar_version"] += 1
    assert changed.fingerprint() != blueprint.fingerprint()


@pytest.mark.parametrize("behaviour", ["suckering_clonal", "rhizomatous_clonal", "stoloniferous_clonal"])
def test_leaf_poses_preserve_structure_area_and_lod_independence(behaviour):
    sim = simulation(entity(plant_growth_behaviour=behaviour))
    current = sim.render_snapshot
    sim.blueprint.growth.pop("forb_leaf_placement_version")
    control = sim.generate_snapshot(sim.age_days, 2)
    assert len(current.placements) == len(control.placements)
    assert [c["leaf_area_m2"] for c in current.leaf_clusters] == [c["leaf_area_m2"] for c in control.leaf_clusters]
    assert current.placement_paths == control.placement_paths
    moved = []
    for i, (actual, old) in enumerate(zip(current.placements, control.placements)):
        if actual[0] != "leaf":
            assert actual == old
            continue
        assert actual[6] == old[6]  # Keep the developmental length.
        forward = current.placement_orientations[str(i)]["forward"]
        assert math.isclose(sum(v*v for v in forward), 1, abs_tol=2e-6)
        assert forward[2] > -.04  # No downward flip from a yaw angle.
        if actual[2:5] != old[2:5]:
            moved.append(i)
            host = current.placements[int(actual[1])]
            origin = current.placements[int(host[1])]
            fraction = (actual[4]-origin[4]) / (host[4]-origin[4])
            assert .2 <= fraction <= .9
    assert moved
    sim.blueprint.growth["forb_leaf_placement_version"] = 1
    detailed = sim.generate_snapshot(sim.age_days, 2)
    coarse = sim.generate_snapshot(sim.age_days, 1)
    assert [p[2:] for p in detailed.placements if p[0] == "leaf"] == [p[2:] for p in coarse.placements if p[0] == "leaf"]
    assert [v["forward"] for v in detailed.placement_orientations.values() if v.get("model") == "forb_socket_direction_v1"] == [v["forward"] for v in coarse.placement_orientations.values() if v.get("model") == "forb_socket_direction_v1"]


def test_authored_leaf_and_fallback_point_to_the_same_projected_side():
    import pygame
    from types import SimpleNamespace
    from simulations.species.species_renderer import SpeciesRenderer, DiagnosticCamera
    from simulations.species.species_simulation import SCREEN_DEPTH_PROJECTION

    pygame.init()
    try:
        sim = simulation()
        snap = sim.render_snapshot
        index = next(i for i, p in enumerate(snap.placements) if p[0] == "leaf")
        leaf = snap.placements[index]
        snap.placement_orientations[str(index)] = {"forward": [1, 0, 0]}
        x, y, z = leaf[2:5]
        center = x + y * SCREEN_DEPTH_PROJECTION
        camera = DiagnosticCamera(400, 400, (center-.3, center+.3, z-.3, z+.3))
        renderer = SpeciesRenderer(SimpleNamespace(camera=None))
        point = renderer._placement_screen(camera, leaf)
        endpoint = renderer._fallback_leaf_endpoint(camera, sim, snap, index, point, leaf[5], leaf[6])
        assert endpoint[0] > point[0]
        sprite = pygame.Surface((15, 75), pygame.SRCALPHA)
        sprite.fill((50, 130, 70, 255))
        renderer._module_asset = lambda *_: sprite
        canvas = pygame.Surface((400, 400), pygame.SRCALPHA)
        isolated = pygame.Surface((400, 400), pygame.SRCALPHA)
        draw_asset = renderer._draw_module_asset

        def capture_leaf(_screen, *args, **kwargs):
            return draw_asset(isolated, *args, **kwargs)

        renderer._draw_module_asset = capture_leaf
        renderer._draw_individual(canvas, sim, snapshot=snap, camera=camera,
                                  visible_indices={index}, cache=False, show_height_reference=False)
        bounds = isolated.get_bounding_rect()
        assert bounds.right - point[0] > point[0] - bounds.left
        assert bounds.width > bounds.height * 2
    finally:
        pygame.quit()


def test_shoot_composition_preserves_clone_connectors_and_root_outcomes():
    composed = simulation(entity(plant_growth_behaviour="suckering_clonal"))
    control = simulation(entity(plant_growth_behaviour="suckering_clonal", leaf_attachment_pattern="mixed"))
    connectors = lambda s: [p[2:7] for p in s.render_snapshot.placements
                            if p[0] == "branch_section" and p[4] < 0]
    assert connectors(composed) == connectors(control)
    for key in ("clonal_ramet_count", "clonal_axis_count", "clonal_axis_length_m", "clonal_spread_radius_m"):
        assert composed.render_snapshot.stats[key] == control.render_snapshot.stats[key]
    for key in ("vitality", "fecundity", "root_depth_m"):
        assert composed.get_ecological_outcome({})[key] == control.get_ecological_outcome({})[key]


def test_clonal_forb_leaf_sprite_obeys_length_and_small_apical_scale():
    import pygame
    from types import SimpleNamespace
    from simulations.species.species_renderer import SpeciesRenderer

    pygame.init()
    sim = simulation()
    renderer = SpeciesRenderer(SimpleNamespace(camera=None))
    renderer._module_asset = lambda *_: pygame.Surface((20, 100), pygame.SRCALPHA)
    sprite = renderer._module_asset(sim, "leaf")
    sprite.fill((70, 130, 85, 255))
    renderer._module_asset = lambda *_: sprite
    camera = SimpleNamespace(world_to_screen=lambda p: (p[0] * 1000, p[1] * 1000))
    try:
        for scale in (1.0, .28):
            screen = pygame.Surface((400, 400), pygame.SRCALPHA)
            assert renderer._draw_module_asset(screen, sim, camera, "leaf", (200, 200), 0, scale)
            assert abs(screen.get_bounding_rect().height - sim.blueprint.module("leaf").length_m * 1000 * scale) <= 1
    finally:
        pygame.quit()
