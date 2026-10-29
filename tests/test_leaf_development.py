"""Leaf growth changes shape, while preserving sockets and canonical topology."""
import math
from copy import deepcopy
from types import SimpleNamespace

import pygame
import pytest

from simulations.species.leaf_development import forb_leaf_development
from simulations.species.plant_assets import PlantBlueprint
from simulations.species.species_renderer import SpeciesRenderer
from tests.test_clonal_forb_shoots import entity, simulation


def test_one_leaf_lengthens_more_than_it_widens_as_it_matures():
    stages = [forb_leaf_development(0, 8, age) for age in (.09, .20, .35)]
    lengths = [p["length_scale"] for p in stages]
    widths = [p["length_scale"] * p["width_scale"] for p in stages]
    assert lengths[0] < lengths[1] < lengths[2]
    assert widths[0] < widths[1] < widths[2]
    assert stages[0]["width_scale"] > stages[1]["width_scale"] > stages[2]["width_scale"]
    assert stages[0]["area_scale"] < stages[1]["area_scale"] < stages[2]["area_scale"]


def test_old_lower_leaf_and_new_upper_leaf_have_distinct_development():
    lower = forb_leaf_development(0, 8, .9)
    upper = forb_leaf_development(7, 8, .9)
    assert lower["development_fraction"] == 1
    assert upper["development_fraction"] < .1
    assert lower["length_scale"] > upper["length_scale"] * 5
    # An old upper bract still has a smaller adult target than a lower blade.
    assert forb_leaf_development(7, 8, 2)["length_scale"] < lower["length_scale"]


@pytest.mark.parametrize("age", [0, .1, .5, 1, 5, float("nan"), float("inf"), None])
def test_development_is_finite_and_bounded_even_with_unresolved_inputs(age):
    p = forb_leaf_development(100, float("nan"), age, float("nan"))
    assert all(math.isfinite(value) for value in p.values() if isinstance(value, (int, float)))
    assert 0 <= p["development_fraction"] <= 1
    assert 0 < p["length_scale"] <= 1.55
    assert 0 < p["width_scale"] < 1.5


def test_new_node_does_not_make_an_established_leaf_smaller():
    # The mature-node denominator is fixed while visible nodes are added.
    p = [forb_leaf_development(1, 8, age) for age in (.25, .38, .52, 1.2)]
    assert [v["length_scale"] for v in p] == sorted(v["length_scale"] for v in p)
    assert len({v["node_rank"] for v in p}) == 1


def test_leaf_expansion_continues_after_axis_height_reaches_maturity():
    sim = simulation()
    at_maturity = sim.generate_snapshot(sim.mature_age_days, 2)
    later = sim.generate_snapshot(sim.mature_age_days * 1.25, 2)
    main = lambda snap: [a["leaf_development"] for a in snap.attachment_points
                         if snap.placements[a["leaf_placement_index"]][7] == 2]
    assert any(b["length_scale"] > a["length_scale"] for a, b in zip(main(at_maturity), main(later)))
    assert sum(p[0] == "stem_section" for p in at_maturity.placements) == sum(p[0] == "stem_section" for p in later.placements)


def test_authored_length_ceiling_and_profile_version_reach_fingerprint():
    sim = simulation()
    assert max(p[6] * sim.blueprint.module("leaf").length_m for p in sim.render_snapshot.placements
               if p[0] == "leaf") <= .120001
    bp = sim.blueprint
    changed = deepcopy(bp)
    changed.growth["forb_leaf_development_version"] += 1
    assert changed.fingerprint() != bp.fingerprint()
    second = PlantBlueprint.from_species_entity(entity(leaf_length={"min_m": .03, "max_m": .15}))
    assert second.growth["forb_leaf_length_upper_scale"] != bp.growth["forb_leaf_length_upper_scale"]


@pytest.mark.parametrize("age_fraction", [.2, .45, .7, 1, 1.25, 3])
def test_development_changes_only_leaf_shape_and_area_not_clone_structure(age_fraction):
    sim = simulation()
    age = sim.mature_age_days * age_fraction
    new = sim.generate_snapshot(age, 2)
    sim.blueprint.growth.pop("forb_leaf_development_version")
    old = sim.generate_snapshot(age, 2)
    assert len(old.placements) == len(new.placements)
    for a, b in zip(old.placements, new.placements):
        assert a[:6] == b[:6]
        assert a[7] == b[7]
        if a[0] != "leaf":
            assert a == b
    assert old.placement_paths == new.placement_paths


def test_leaf_profiles_round_trip_and_are_canonical_across_lods():
    sim = simulation()
    profiles = []
    for lod in (0, 1, 2):
        snap = sim.generate_snapshot(sim.mature_age_days * .7, lod)
        profiles.append([c["leaf_development"] for c in snap.leaf_clusters])
        assert type(snap).from_dict(snap.to_dict()).to_dict() == snap.to_dict()
    assert profiles[0] == profiles[1] == profiles[2]


def test_renderer_stretches_length_and_width_independently_at_the_socket():
    pygame.init()
    sim = simulation()
    renderer = SpeciesRenderer(SimpleNamespace(camera=None))
    sprite = pygame.Surface((20, 100), pygame.SRCALPHA)
    sprite.fill((70, 130, 85, 255))
    renderer._module_asset = lambda *_: sprite
    camera = SimpleNamespace(world_to_screen=lambda p: (p[0] * 1000, p[1] * 1000))
    try:
        for scale, width_scale in [(1.3, .35), (.35, .7)]:
            canvas = pygame.Surface((400, 400), pygame.SRCALPHA)
            renderer._draw_module_asset(canvas, sim, camera, "leaf", (200, 200), 0, scale, width_scale=width_scale)
            bounds = canvas.get_bounding_rect()
            expected_length = sim.blueprint.module("leaf").length_m * 1000 * scale
            assert abs(bounds.height - expected_length) <= 1
            assert abs(bounds.width - expected_length * .2 * width_scale) <= 1
            anchor = sim.blueprint.module("leaf").attachment_point
            assert abs(bounds.x + bounds.width * anchor[0] - 200) <= 1
            assert abs(bounds.y + bounds.height * anchor[1] - 200) <= 1
    finally:
        pygame.quit()
