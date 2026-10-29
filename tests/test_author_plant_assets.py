from copy import deepcopy
from pathlib import Path

import pygame
import pytest

from tools.author_plant_assets import (
    ManifestError,
    PixelEditorHost,
    _anchor_payload,
    _organ_detail_snapshot,
    canvas_size,
    load_manifest,
    render_module,
    validate_manifest,
)
from simulations.species.species_simulation import SpeciesSimulation


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = PROJECT_ROOT / "assets" / "plant_asset_specs" / "spec_erigeron_annuus.json"


def test_headless_editor_host_uses_live_canvas_size_for_reopening():
    host = PixelEditorHost(None)
    assert host._pixel_canvas_size_for_entity({"type": "species"}, 0.08) == canvas_size(0.08)
    host.canvas_size_override = (91, 103)
    assert host._pixel_canvas_size_for_entity({"type": "species"}, 0.08) == (91, 103)


@pytest.fixture(scope="module", autouse=True)
def pygame_runtime():
    pygame.init()
    yield
    pygame.quit()


def test_fleabane_manifest_is_valid_and_uses_live_canvas_formula():
    manifest = load_manifest(MANIFEST_PATH)

    assert manifest["species_id"] == "spec_erigeron_annuus"
    assert [module["role"] for module in manifest["modules"]] == ["leaf", "flower", "stem", "branch"]
    assert all(canvas_size(module['depicted_size_m']) == (75, 75) for module in manifest['modules'])


def test_declarative_modules_render_nonempty_rgba_surfaces():
    manifest = load_manifest(MANIFEST_PATH)

    for module in manifest["modules"]:
        surface = render_module(module)
        assert surface.get_size() == canvas_size(module["depicted_size_m"])
        assert any(surface.get_at((x, y)).a for y in range(surface.get_height()) for x in range(surface.get_width()))


def test_manifest_rejects_duplicate_roles_before_any_persistence():
    manifest = load_manifest(MANIFEST_PATH)
    invalid = deepcopy(manifest)
    invalid.pop("_manifest_path")
    invalid["modules"][1]["role"] = "leaf"

    with pytest.raises(ManifestError, match="Duplicate module role"):
        validate_manifest(invalid)


def test_anchor_payload_retains_metric_size_and_upward_axis():
    module = load_manifest(MANIFEST_PATH)["modules"][0]

    payload = _anchor_payload(module)

    assert payload["attachment_point"] == [0.5, 0.946]
    assert payload["growth_axis"] == [0.0, -1.0]
    assert payload["growth_vector"] == [0.0, -1.0]
    assert payload["depicted_size_m"] == 0.08


def test_tree_closeup_expands_clusters_without_mutating_coarse_snapshot():
    sim = SpeciesSimulation(species_entity={
        "id": "spec_synthetic_asset_tree", "plant_growth_form": "tree",
        "plant_growth_behaviour": "branched_woody", "mature_height": {"max_m": 8},
        "leaf_length": {"typical_m": 0.1}, "leaf_structure": "simple",
        "plant_leaf_distribution": "along_shoot",
    }, seed=303)
    sim.set_age(sim.mature_age_days)
    coarse = sim.render_snapshot.to_dict()
    assert sim.render_snapshot.leaf_clusters
    assert not any(p[0] == "leaf" for p in sim.render_snapshot.placements)
    detail = _organ_detail_snapshot(sim)
    leaves = [p for p in detail.placements if p[0] == "leaf"]
    assert leaves
    assert all(0 <= p[1] < len(detail.placements) for p in leaves)
    assert sim.render_snapshot.to_dict() == coarse
    assert _organ_detail_snapshot(sim).to_dict() == detail.to_dict()


def test_nonclustered_asset_closeup_preserves_original_snapshot():
    sim = SpeciesSimulation(species_entity={"id": "spec_synthetic_asset_herb"}, seed=303)
    assert _organ_detail_snapshot(sim) is sim.render_snapshot
