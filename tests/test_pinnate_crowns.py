"""Metric pinnate crowns preserve biological counts across display detail."""
import gzip
import json
import math
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pygame
import pytest

from simulations.species.plant_assets import PlantBlueprint, PlantGrowthSnapshot
from simulations.species.pinnate_crowns import frond_leaflets
from simulations.species.species_renderer import SpeciesRenderer, DiagnosticCamera
from simulations.species.species_simulation import SpeciesSimulation
from simulations.species.species_editor import editable_field_rows, new_editor_state, preview_entity
from tools.author_plant_assets import load_manifest, validate_manifest, ManifestError, PixelEditorHost, PixelArtEditorUI
from world.world_model import WorldModel

ROOT = Path(__file__).resolve().parents[1]


def synthetic(**changes):
    return {"id": "spec_unrelated_pinnate_crown", "plant_growth_form": "other_unknown",
            "plant_growth_behaviour": "rhizomatous_clonal", "plant_lifespan": "perennial",
            "plant_leaf_distribution": "terminal_cluster", "leaf_structure": "pinnately_compound",
            "leaf_cluster_size": {"typical": 7}, "leaf_length": {"typical_m": 3},
            "leaflet_count": {"typical": 51}, "leaflet_length": {"typical_m": .4},
            "leaflet_width": {"typical_m": .035}, "clonal_spread": "low",
            "plant_leaf_attachment_angle": .06, "frond_stipe_fraction": .17, **changes}


def grown(entity, lod=2, maturity=1):
    sim = SpeciesSimulation(species_entity=entity, seed=719)
    sim.set_lod(lod); sim.set_age(sim.mature_age_days * maturity)
    return sim


def test_metric_paths_socket_attachment_determinism_and_roundtrip():
    a = grown(synthetic()); snap = a.render_snapshot
    assert snap.to_dict() == grown(synthetic()).render_snapshot.to_dict()
    assert PlantBlueprint.from_dict(a.blueprint.to_dict()).fingerprint() == a.blueprint.fingerprint()
    assert PlantGrowthSnapshot.from_dict(snap.to_dict()).to_dict() == snap.to_dict()
    for i, p in enumerate(snap.placements):
        assert p[1] == -1 or 0 <= p[1] < i
        if p[0] != "leaf":
            continue
        path = snap.placement_paths[str(i)]
        assert path[0] == pytest.approx(p[2:5], abs=.0001)
        assert snap.placements[p[1]][2:5] == p[2:5]
        assert sum(math.dist(x, y) for x, y in zip(path, path[1:])) == pytest.approx(3 * p[6], abs=.004)
        assert all(math.isfinite(v) for point in path for v in point)
        assert path[-1][2] > path[0][2]
        assert len(list(frond_leaflets(path, 51, .4, .17))) == 51
        assert len(list(frond_leaflets(path, 2000, .4, .17))) == 256


@pytest.mark.parametrize("maturity", [.12, .5, 1])
def test_lod_keeps_canonical_bounds_area_roots_and_same_sample_poses(maturity):
    sims = [grown(synthetic(), lod, maturity) for lod in range(3)]
    snaps = [s.render_snapshot for s in sims]
    for key in ("estimated_frond_count", "estimated_leaflet_count", "leaf_area_m2",
                "clonal_ramet_count", "root_length_m", "root_segment_count"):
        assert len({s.stats[key] for s in snaps}) == 1
    assert all(s.bounds_m == snaps[0].bounds_m for s in snaps)
    assert all(s.get_ecological_outcome() == sims[0].get_ecological_outcome() for s in sims)
    detail_paths = list(snaps[2].placement_paths.values())
    assert all(path in detail_paths for path in snaps[1].placement_paths.values())
    assert not any(p[0] == "leaf" for p in snaps[0].placements)


def test_angle_and_droop_change_pose_without_changing_area_or_root_geometry():
    a, b, c = (grown(synthetic(**params)) for params in (
        {"plant_leaf_attachment_angle": 0}, {"plant_leaf_attachment_angle": .2},
        {"plant_leaf_attachment_angle": .2, "plant_branch_droop": .7}))
    assert a.render_snapshot.bounds_m[5] > b.render_snapshot.bounds_m[5] > c.render_snapshot.bounds_m[5]
    assert len({s.blueprint.fingerprint() for s in (a, b, c)}) == 3
    for key in ("leaf_area_m2", "estimated_frond_count", "root_length_m", "clonal_axis_length_m"):
        assert len({s.render_snapshot.stats[key] for s in (a, b, c)}) == 1


@pytest.mark.parametrize("value", [None, {}, "other_unknown", float("nan"), float("inf"), True, -.1, 1.1])
def test_missing_unknown_invalid_control_preserves_legacy(value):
    old = synthetic(); old.pop("plant_leaf_attachment_angle")
    a, b = grown(old), grown({**old, "plant_leaf_attachment_angle": value})
    assert "pinnate_crown_version" not in b.blueprint.growth
    assert a.render_snapshot.to_dict() == b.render_snapshot.to_dict()
    assert a.blueprint.fingerprint() == b.blueprint.fingerprint()


def test_fern_and_ordinary_compound_leaf_do_not_opt_in():
    for changes in ({"plant_growth_behaviour": "fern_fronding", "leaf_structure": "frond_like"},
                    {"plant_leaf_distribution": "along_shoot"}):
        assert "pinnate_crown_version" not in grown(synthetic(**changes)).blueprint.growth


def test_palm_angle_is_editable_and_variation_transports_it():
    data = synthetic(plant_leaf_attachment_angle={"min": .03, "typical": .06, "max": .09})
    assert any(r["field"] == "plant_leaf_attachment_angle" for r in editable_field_rows(data))
    assert [grown(preview_entity(new_editor_state(data), mode)).blueprint.growth["leaf_attachment_angle"]
            for mode in ("minimum", "typical", "maximum")] == [.03, .06, .09]


def test_saved_leaflet_unit_uses_organ_scale_reopens_and_does_not_affect_ecology():
    pygame.init(); pygame.display.set_mode((1, 1))
    world = WorldModel(); entity = world.resolved_species_entity("spec_nypa_fruticans")
    sim = grown(entity); renderer = SpeciesRenderer(SimpleNamespace(camera=None))
    assert sim.blueprint.module("leaf").length_m == 8
    assert sim.blueprint.module("leaf").visual["visual_unit"] == "leaflet"
    illustration = world.loader.get("illust_nypa_fruticans_leaflet")
    with gzip.open(ROOT / illustration["pixel_document_path"], "rt", encoding="utf-8") as f:
        document = json.load(f)
    assert document["version"] == 2
    editor = PixelArtEditorUI(PixelEditorHost(world.loader))
    assert editor.open(illustration["id"])
    assert editor.begin_canvas()
    screen = pygame.Surface((400, 400), pygame.SRCALPHA)
    camera = DiagnosticCamera(400, 400, (-2, 2, 0, 4))
    assert not renderer._draw_module_asset(screen, sim, camera, "leaf", (200, 300), 0, 1)
    assert renderer._draw_module_asset(screen, sim, camera, "leaf", (200, 300), 0, 1, unit_length_px=30)
    assert screen.get_bounding_rect().height <= 31
    assert screen.get_bounding_rect().width <= 4
    i = next(i for i, p in enumerate(sim.render_snapshot.placements) if p[0] == "leaf")
    p = sim.render_snapshot.placements[i]
    assert renderer._fallback_leaf_endpoint(camera, sim, sim.render_snapshot, i, (0, 0), p[5], p[6]) == renderer._path_screen(camera, sim.render_snapshot.placement_paths[str(i)][-1])
    bare = deepcopy(entity); bare.pop("plant_leaf_module_ref")
    assert sim.get_ecological_outcome() == grown(bare).get_ecological_outcome()
    manifest = load_manifest(ROOT / "assets/plant_asset_specs/spec_nypa_fruticans.json")
    invalid = deepcopy(manifest); invalid["modules"][0]["role"] = "flower"
    with pytest.raises(ManifestError):
        validate_manifest(invalid)
    pygame.quit()
