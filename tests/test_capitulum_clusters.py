import math

import pygame
import pytest

from simulations.species.capitulum_clusters import capitulum_cluster_profile, capitulum_cluster_surface
from simulations.species.plant_assets import PlantBlueprint, PlantGrowthSnapshot
from simulations.species.species_simulation import SpeciesSimulation
from simulations.species.species_editor import editable_field_rows


def profile(**updates):
    return {"form": "capitulum_cluster", "unit": "capitulum", "length_m": .028,
            "width_m": .027, "head_size_m": .0085, "head_count": 5,
            "axis_color": [90, 145, 53], **updates}


def entity(**updates):
    return {"id": "spec_unrelated_short_subshrub", "plant_growth_form": "subshrub",
            "plant_growth_behaviour": "iterative_indeterminate", "plant_woodiness": "woody",
            "plant_lifespan": "short_lived_perennial", "leaf_attachment_pattern": "along_stem",
            "plant_leaf_distribution": "along_shoot", "leaf_arrangement": "opposite",
            "plant_reproductive_structure": "capitulum", "plant_flowering_position": "terminal",
            "reproductive_mode": "apomictic", "mature_height": {"typical_m": .6, "max_m": 1},
            "plant_inflorescence_profile": profile(), "plant_leaf_attachment_angle": .35,
            **updates}


@pytest.mark.parametrize("update", [{"head_count": True}, {"head_count": 13},
    {"head_size_m": float("nan")}, {"width_m": -1}, {"unit": "individual_flower"},
    {"axis_color": [300, 0, 0]}])
def test_invalid_profile_is_neutral(update):
    assert capitulum_cluster_profile(profile(**update)) is None
    base = entity(plant_inflorescence_profile=None)
    assert PlantBlueprint.from_species_entity(base).fingerprint() == PlantBlueprint.from_species_entity(
        entity(plant_inflorescence_profile=profile(**update))).fingerprint()


def test_heads_have_bounded_metric_display_and_optional_asset():
    p = capitulum_cluster_profile(profile())
    for ppm in [100, 1000, 1e9]:
        surface, anchor = capitulum_cluster_surface(p, ppm, .5)
        assert 1 <= surface.get_width() <= 1024
        assert 1 <= surface.get_height() <= 1024
        assert surface.get_bounding_rect().width > 0
        assert all(math.isfinite(v) for v in anchor)
    sprite = pygame.Surface((75, 75), pygame.SRCALPHA)
    pygame.draw.ellipse(sprite, (180, 145, 220), (18, 5, 39, 65))
    a, _ = capitulum_cluster_surface(p, 1000, .5, sprite)
    b, _ = capitulum_cluster_surface(p, 1000, .5, sprite)
    assert pygame.image.tobytes(a, "RGBA") == pygame.image.tobytes(b, "RGBA")


def test_portable_profile_fingerprints_and_head_structure_gate():
    a = PlantBlueprint.from_species_entity(entity())
    b = PlantBlueprint.from_species_entity(entity(plant_inflorescence_profile=profile(head_count=3)))
    assert a.fingerprint() != b.fingerprint()
    assert PlantBlueprint.from_dict(a.to_dict()).fingerprint() == a.fingerprint()
    assert "inflorescence_profile" not in PlantBlueprint.from_species_entity(
        entity(plant_reproductive_structure="cone")).growth


def test_leafy_terminal_shoots_are_lod_stable_and_valid():
    snapshots = []
    for lod in [0, 1, 2]:
        sim = SpeciesSimulation(species_entity=entity(), seed=303)
        sim.set_age(160); sim.set_lod(lod)
        snapshot = sim.render_snapshot
        snapshots.append(snapshot)
        assert sim.blueprint.growth["short_lived_subshrub_shoot_version"] == 1
        for i, p in enumerate(snapshot.placements):
            assert -1 <= p[1] < i
            assert all(math.isfinite(v) for v in p[2:7])
        assert len(snapshot.placements) < 200
        assert PlantGrowthSnapshot.from_dict(snapshot.to_dict()).to_dict() == snapshot.to_dict()
        repeat = SpeciesSimulation(species_entity=entity(), seed=303)
        repeat.set_age(160); repeat.set_lod(lod)
        assert repeat.render_snapshot.to_dict() == snapshot.to_dict()
    for snap in snapshots[1:]:
        assert snap.stats["estimated_leaf_count"] == snapshots[0].stats["estimated_leaf_count"]
        assert snap.stats["leaf_area_m2"] == snapshots[0].stats["leaf_area_m2"]
        def axes(snapshot):
            return [(p[0], p[2:], snapshot.placements[p[1]][2:5] if p[1] >= 0 else None)
                    for p in snapshot.placements if p[0] in {"stem_section", "branch_section"}]
        assert axes(snap) == axes(snapshots[0])
    assert any(p[0] == "flower" for p in snapshots[2].placements)
    assert not any(p[0] == "flower" for p in snapshots[0].placements)
    assert "plant_leaf_attachment_angle" in {r["field"] for r in editable_field_rows(entity())}


def test_display_head_count_does_not_change_ecology_or_shoot_topology():
    a = SpeciesSimulation(species_entity=entity(), seed=303)
    b = SpeciesSimulation(species_entity=entity(plant_inflorescence_profile=profile(head_count=12)), seed=303)
    a.set_age(160); b.set_age(160)
    assert a.render_snapshot.placements == b.render_snapshot.placements
    assert a.get_ecological_outcome({"pollination_availability": 0}) == b.get_ecological_outcome(
        {"pollination_availability": 0})


@pytest.mark.parametrize("arrangement,expected", [("alternate", 1), ("opposite", 2), ("whorled", 3)])
def test_lateral_nodes_keep_the_authored_leaf_arrangement(arrangement, expected):
    from collections import Counter
    sim = SpeciesSimulation(species_entity=entity(leaf_arrangement=arrangement), seed=303)
    sim.set_age(160); sim.set_lod(2)
    placements = sim.render_snapshot.placements
    nodes = Counter((p[1], tuple(p[2:5])) for p in placements
                    if p[0] == "leaf" and placements[p[1]][0] == "branch_section")
    assert nodes and set(nodes.values()) == {expected}


@pytest.mark.parametrize("updates", [{"plant_lifespan": "perennial"},
    {"plant_flowering_position": "other_unknown"}, {"leaf_attachment_pattern": "terminal_cluster"},
    {"plant_growth_behaviour": "branched_woody"}])
def test_other_growth_combinations_preserve_existing_dispatch(updates):
    assert "short_lived_subshrub_shoot_version" not in PlantBlueprint.from_species_entity(entity(**updates)).growth
