"""Contracts for an optional scaffold architecture, independent of taxon ID."""
from copy import deepcopy
import math
import os
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import pygame
import pytest
from simulations.species.plant_assets import PlantBlueprint, PlantGrowthSnapshot
from simulations.species.species_simulation import SpeciesSimulation
from simulations.species.species_editor import editable_field_rows, PREVIEW_AFFECTING_FIELDS
from simulations.biosphere.biosphere_renderer import BiosphereBuilderRenderer
from simulations.biosphere.plant_pictures import top_view, map_sprite_at
from tools.author_plant_species import validate_updates, AuthoringError, prepare_update
from world.species_inheritance import resolved_species_entity


def entity(**changes):
    return {"id": "spec_unrelated_scaffold_fixture", "type": "species", "_dataset": "species",
            "parents": ["cladis_fixture"], "plant_growth_form": "tree", "plant_growth_behaviour": "branched_woody",
            "plant_leaf_distribution": "mixed_long_short_shoots", "plant_shoot_dimorphism": "long_and_short_shoots",
            "plant_axis_continuity": "sympodial", "plant_lateral_axis_orientation": "plagiotropic",
            "plant_apical_control": .42, "plant_crown_shape": "spreading", "longevity_class": "very_long",
            "plant_woodiness": "woody", "plant_lifespan": "perennial", "mature_height": {"max_m": 25},
            "leaf_length": {"typical_m": .1}, **changes}


def sim(e, seed=303, maturity=1., lod=2):
    result = SpeciesSimulation(species_entity=e, seed=seed)
    result.set_lod(lod); result.set_age(result.mature_age_days * maturity)
    return result


def stems(snapshot):
    return [p for p in snapshot.placements if p[0] == "stem_section" and p[7] == 1]


def winding(snapshot):
    nodes = [(0., 0., -.08)] + [p[2:5] for p in stems(snapshot)]
    return sum(math.dist(a, b) for a, b in zip(nodes, nodes[1:])) / math.dist(nodes[0], nodes[-1])


def test_transport_editor_validation_inheritance_and_portability():
    field = "plant_branching_subpattern"
    validate_updates({field: "decurrent_scaffold"})
    with pytest.raises(AuthoringError):
        validate_updates({field: "unimplemented_pattern"})
    e = entity()
    parent = {"id": "cladis_fixture", "type": "cladistics", "parents": ["cladis_plants_plantae"], field: "decurrent_scaffold"}
    root = {"id": "cladis_plants_plantae", "type": "cladistics"}
    loader = SimpleNamespace(entities={e["id"]: e, parent["id"]: parent, root["id"]: root})
    resolved = resolved_species_entity(loader, e)
    assert field not in e and resolved[field] == "decurrent_scaffold"
    updated, _, _ = prepare_update({"species": [e], "cladistics": [parent, root]}, e["id"], {field: "decurrent_scaffold"})
    assert updated["id"] == e["id"] and updated["parents"] == e["parents"]
    blueprint = PlantBlueprint.from_species_entity(resolved)
    assert blueprint.growth["branching_subpattern"] == "decurrent_scaffold"
    assert blueprint.fingerprint() != PlantBlueprint.from_species_entity(e).fingerprint()
    assert PlantBlueprint.from_dict(blueprint.to_dict()).fingerprint() == blueprint.fingerprint()
    assert field in PREVIEW_AFFECTING_FIELDS
    rows = editable_field_rows(resolved, "branch")
    assert any(row["field"] == field and row["kind"] == "choice" for row in rows)


def test_tiered_conifer_transport_and_secondary_whorls():
    field = "plant_branching_subpattern"
    validate_updates({field: "tiered_conifer"})
    e = entity(plant_axis_continuity="monopodial", plant_branching_rhythm="rhythmic",
               plant_crown_shape="conical", plant_leaf_structure="needle_like",
               plant_leaf_arrangement="fascicled", plant_branching_subpattern="tiered_conifer")
    blueprint = PlantBlueprint.from_species_entity(e)
    assert blueprint.growth["branching_subpattern"] == "tiered_conifer"
    assert PlantBlueprint.from_dict(blueprint.to_dict()).fingerprint() == blueprint.fingerprint()
    assert any(row["field"] == field and row["kind"] == "choice"
               for row in editable_field_rows(e, "branch"))

    base_entity = {k: v for k, v in e.items() if k != field}
    base = sim(base_entity)
    tiered = sim(e)

    def secondary_rises(snapshot):
        placements = snapshot.placements
        return [p[4] - placements[p[1]][4] for p in placements
                if p[0] == "branch_section" and p[7] == 3
                and placements[p[1]][7] == 2]

    assert max(secondary_rises(tiered.render_snapshot)) < max(secondary_rises(base.render_snapshot))
    assert tiered.render_snapshot.to_dict() == sim(deepcopy(e)).render_snapshot.to_dict()
    for key in ("estimated_leaf_count", "leaf_area_m2"):
        assert tiered.get_growth_summary()[key] == base.get_growth_summary()[key]
    assert len(tiered.render_snapshot.leaf_clusters) == len(base.render_snapshot.leaf_clusters)
    assert tiered.blueprint.fingerprint() != base.blueprint.fingerprint()


def test_unknown_missing_and_non_tree_do_not_change_existing_geometry():
    base = sim(entity())
    for value in (None, "", "other_unknown", "invalid_pattern"):
        neutral = sim(entity(plant_branching_subpattern=value))
        assert neutral.blueprint.fingerprint() == base.blueprint.fingerprint()
        assert neutral.render_snapshot.to_dict() == base.render_snapshot.to_dict()
    a = sim(entity(plant_growth_form="shrub"))
    b = sim(entity(plant_growth_form="shrub", plant_branching_subpattern="decurrent_scaffold"))
    assert a.render_snapshot.to_dict() == b.render_snapshot.to_dict()


@pytest.mark.parametrize("continuity", ["sympodial", "monopodial", "monopodial_to_sympodial", "mixed", "other_unknown"])
def test_short_bole_and_substantial_rising_limbs_compose_with_coarse_patterns(continuity):
    base = sim(entity(plant_axis_continuity=continuity)).render_snapshot
    target = sim(entity(plant_axis_continuity=continuity, plant_branching_subpattern="decurrent_scaffold")).render_snapshot
    assert max(p[4] for p in stems(target)) < max(p[4] for p in stems(base)) * .6
    assert max(p[4] for p in target.placements) > 25 * .8
    assert max(p[6] for p in target.placements if p[0] == "branch_section" and p[7] == 2) > max(
        p[6] for p in base.placements if p[0] == "branch_section" and p[7] == 2)
    if continuity == "sympodial":
        assert winding(target) < winding(base)


def test_deterministic_growth_valid_sockets_bounded_geometry_and_lod_accounting():
    e = entity(plant_branching_subpattern="decurrent_scaffold")
    grown = sim(e).render_snapshot
    assert grown.to_dict() == sim(deepcopy(e)).render_snapshot.to_dict()
    assert grown.placements != sim(e, seed=42).render_snapshot.placements
    assert PlantGrowthSnapshot.from_dict(grown.to_dict()).to_dict() == grown.to_dict()
    young = sim(e, maturity=.1).render_snapshot
    assert max(p[4] for p in young.placements) < max(p[4] for p in grown.placements)
    for snapshot in (young, grown, sim(e, seed=42).render_snapshot):
        assert len(snapshot.placements) < 10000
        for i, p in enumerate(snapshot.placements):
            assert -1 <= p[1] < i
            assert all(math.isfinite(v) for v in p[2:7])
            assert all(abs(v) <= 25 * 1.2 for v in p[2:5])
        for cluster in snapshot.leaf_clusters:
            assert 0 <= cluster["host_placement_index"] < len(snapshot.placements)
            assert 0 <= cluster.get("foliage_spray_radius_m", 0.) <= 1.4
    summaries = [sim(e, lod=lod).get_growth_summary() for lod in range(3)]
    for summary in summaries:
        for field in ("estimated_leaf_count", "leaf_area_m2", "structural_axis_length_m"):
            assert summary[field] == summaries[0][field]


def test_biosim_grounded_and_top_sprites_preserve_bounded_leafy_crown():
    pygame.init(); pygame.display.set_mode((1, 1))
    try:
        body = sim(entity(plant_branching_subpattern="decurrent_scaffold"))
        scene = SimpleNamespace(world_units_to_meters=1., world_model=SimpleNamespace(repository_revision=0),
                                get_representative_species_simulation=lambda _: body)
        instance = {"species_id": body.species_id, "representative_id": "fixture", "abundance": 1., "visual_scale": 1.}
        for cap in (84, 300):
            renderer = BiosphereBuilderRenderer(SimpleNamespace())
            sprite, anchor = renderer._render_sprite_surface(scene, instance, SimpleNamespace(zoom=20., sprite_height_cap=cap))
            assert sprite.get_width() <= (96 if cap == 84 else round(cap * 1.6))
            assert sprite.get_height() <= cap + 12
            assert 0 <= anchor[0] <= sprite.get_width()
            assert 0 <= anchor[1] <= sprite.get_height()
            assert sprite.get_bounding_rect().width > 0
        crown = top_view(body)
        assert crown is not None and max(crown.get_size()) <= 192
        assert max(map_sprite_at(crown, 40).get_size()) == 40
        pixels = pygame.surfarray.array3d(crown)
        green = (pixels[:, :, 1] > pixels[:, :, 0] * 1.1) & (pixels[:, :, 1] > pixels[:, :, 2] * 1.1)
        assert green.sum() > 300
    finally:
        pygame.quit()
