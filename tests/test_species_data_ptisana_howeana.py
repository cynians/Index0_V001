"""Basal fern crowns and metric pinnule composition use independent scales."""

import json
import gzip
import math
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pygame
import pytest

from simulations.species.plant_assets import PlantBlueprint, PlantGrowthSnapshot
from simulations.species.species_renderer import DiagnosticCamera, SpeciesRenderer, frond_primary_pinna_rows
from simulations.species.species_simulation import SpeciesSimulation
from simulations.species.species_editor import PREVIEW_AFFECTING_FIELDS, field_group
from tools.author_plant_assets import ManifestError, _anchor_payload, load_manifest, validate_manifest
from world.plant_catalogue import PlantCatalogue
from world.world_model import WorldModel

SID = "spec_ptisana_howeana"
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def world():
    return WorldModel()


def grown(entity, lod=2):
    sim = SpeciesSimulation(species_entity=entity, seed=541)
    sim.set_lod(lod)
    sim.set_age(187.75)
    return sim


def test_live_identity_research_transport_and_unknowns(world):
    raw = world.loader.get(SID)
    entity = world.resolved_species_entity(SID)
    assert PlantCatalogue.build(world.loader.entities).is_species(SID)
    assert raw["parents"] == ["cladis_ptisana"]
    updates = json.loads((ROOT / "artifacts" / SID / "refinement_updates.json").read_text())
    for field, value in updates.items():
        assert raw[field] == entity[field] == value
    bp = PlantBlueprint.from_species_entity(entity, SID)
    assert bp.growth["leaf_arrangement"] == "basal"
    assert bp.growth["frond_pinna_arrangement"] == "alternate"
    assert bp.growth["leaf_distribution"] == "basal_tuft"
    assert bp.growth["leaf_length_m"] == pytest.approx(2.6)
    assert bp.module("leaf").length_m == pytest.approx(2.6)
    assert bp.growth["leaf_length_source"] == "runtime_upper_bound_illustration_fraction"
    assert bp.growth["leaf_division_order"] == 2
    assert bp.growth["leaflet_count"] == 24
    assert bp.module("leaf").visual["leaflet_length_m"] == pytest.approx(.075)
    assert bp.module("leaf").visual["visual_unit"] == "pinnule"
    assert bp.module("leaf").visual["depicted_size_m"] == pytest.approx(.075)
    assert not raw["mature_height"]
    assert raw["leaf_length"]["status"] == "reported_upper_bound_not_typical"
    for field in ("maturity_age", "longevity", "max_root_depth", "temperature_range", "frost_tolerance", "soil_ph_range"):
        assert not raw.get(field)
    assert raw["seed_size_class"] == "other_unknown"
    assert raw["shade_tolerance"] == raw["waterlogging_tolerance"] == "other_unknown"


def test_persisted_pixel_document_and_anchor_roundtrip(world):
    raw = world.loader.get(SID)
    illustration = world.loader.get("illust_ptisana_howeana_pinnule")
    assert raw["plant_leaf_module_ref"] == illustration["media_path"]
    assert (ROOT / illustration["media_path"]).is_file()
    with gzip.open(ROOT / illustration["pixel_document_path"], "rt", encoding="utf-8") as stream:
        document = json.load(stream)
    assert document["version"] == 2
    assert document["width"] == document["height"] == 75
    assert raw["plant_module_anchors"]["leaf"]["visual_unit"] == "pinnule"
    assert raw["plant_module_anchors"]["leaf"]["depicted_size_m"] == .075


def test_deterministic_connected_finite_portable_and_lod_stable(world):
    entity = world.resolved_species_entity(SID)
    sim = grown(entity)
    snap = sim.render_snapshot
    assert snap.to_dict() == grown(entity).render_snapshot.to_dict()
    assert snap.to_dict() == PlantGrowthSnapshot.from_dict(snap.to_dict()).to_dict()
    assert sim.blueprint.to_dict() == PlantBlueprint.from_dict(sim.blueprint.to_dict()).to_dict()
    assert snap.stats["rhizome_frond_distribution"] == "compact_crown"
    assert snap.stats["canonical_frond_count"] == 9
    assert snap.stats["primary_pinna_arrangement"] == "alternate"
    assert not any(p[0] in {"flower", "fruit", "branch_section"} for p in snap.placements)
    assert all(a["socket"] == "frond" for a in snap.attachment_points)
    for i, p in enumerate(snap.placements):
        assert p[1] == -1 or 0 <= p[1] < i
        assert all(math.isfinite(v) for v in p[2:7])
        assert all(abs(v) < 10 for v in p[2:5])
    for lod in (0, 1):
        other = grown(entity, lod)
        for field in ("estimated_leaf_count", "structural_biomass_proxy", "resource_demand"):
            assert other.get_ecological_outcome()[field] == sim.get_ecological_outcome()[field]
        assert other.render_snapshot.stats["canonical_frond_count"] == 9


def test_basal_tuft_and_pinna_arrangement_are_independent_and_reusable():
    entity = {"id": "spec_unrelated_compact_fern", "plant_growth_form": "fern",
              "plant_growth_behaviour": "fern_fronding", "plant_lifespan": "perennial",
              "leaf_structure": "frond_like", "leaf_arrangement": "basal",
              "frond_pinna_arrangement": "alternate", "leaf_attachment_pattern": "basal_tuft",
              "plant_leaf_distribution": "basal_tuft", "leaf_division_order": 3,
              "leaflet_count": {"typical": 14}, "leaf_length": {"typical_m": 1.6},
              "mature_height": {"min_m": .8, "max_m": .8}, "belowground_storage": ["rhizome"],
              "clonal_spread": "high"}
    compact = grown(entity)
    opposite = grown({**entity, "frond_pinna_arrangement": "opposite"})
    assert compact.blueprint.fingerprint() != opposite.blueprint.fingerprint()
    assert compact.render_snapshot.stats["primary_pinna_arrangement"] == "alternate"
    assert opposite.render_snapshot.stats["primary_pinna_arrangement"] == "opposite"
    assert compact.get_ecological_outcome() == opposite.get_ecological_outcome()
    assert compact.render_snapshot.stats["rhizome_frond_distribution"] == "compact_crown"
    spaced = grown({**entity, "leaf_attachment_pattern": "along_stem", "plant_leaf_distribution": "along_shoot"})
    assert spaced.render_snapshot.stats["rhizome_frond_distribution"] == "spaced_sockets"
    assert spaced.render_snapshot.stats["rhizome_axis_length_m"] > 0
    for i, p in enumerate(compact.render_snapshot.placements):
        if p[0] == "leaf":
            path = compact.render_snapshot.placement_paths[str(i)]
            assert max(pt[2] for pt in path) <= .8251
            assert min(pt[2] for pt in path) >= .0249
            assert math.dist(path[0], path[-1]) < sum(math.dist(a, b) for a, b in zip(path, path[1:]))


def test_legacy_missing_and_explicit_unknown_pinna_arrangements():
    base = {"id": "spec_legacy_fern", "plant_growth_form": "fern", "leaf_structure": "frond_like",
            "leaf_arrangement": "alternate", "leaf_division_order": 2, "leaflet_count": {"typical": 10}}
    legacy = grown(base)
    assert "frond_pinna_arrangement" not in legacy.blueprint.growth
    assert legacy.render_snapshot.stats["primary_pinna_arrangement"] == "alternate"
    unknown = grown({**base, "frond_pinna_arrangement": "other_unknown"})
    assert unknown.render_snapshot.stats["primary_pinna_arrangement"] == "other_unknown"
    assert len(frond_primary_pinna_rows(10, "alternate")) == 10
    assert len(frond_primary_pinna_rows(10, "other_unknown")) == 5
    assert frond_primary_pinna_rows(0, None) == []
    assert len(frond_primary_pinna_rows(999999, "alternate")) == 24


def test_pinnule_asset_is_composed_at_ultimate_segment_scale(world):
    pygame.init()
    sim = grown(world.resolved_species_entity(SID))
    renderer = SpeciesRenderer(SimpleNamespace(camera=None))
    camera = DiagnosticCamera(500, 500, (-2, 2, 0, 4))
    screen = pygame.Surface((500, 500), pygame.SRCALPHA)
    # An ordinary leaf placement must route into the hierarchical renderer.
    assert not renderer._draw_module_asset(screen, sim, camera, "leaf", (250, 400), 0, 1)
    assert screen.get_bounding_rect().size == (0, 0)
    assert renderer._draw_module_asset(screen, sim, camera, "leaf", (250, 400), 0, 1, unit_length_px=20)
    assert screen.get_bounding_rect().height <= 21
    assert screen.get_bounding_rect().width <= 6
    pixels = pygame.mask.from_surface(screen).count()
    screen.fill((0, 0, 0, 0))
    renderer._draw_module_asset(screen, sim, camera, "leaf", (250, 400), 0, 1, unit_length_px=40)
    assert pygame.mask.from_surface(screen).count() > pixels * 2
    # Width and coverage come from physical laminae; structural placements
    # and ecological area do not depend on having a bitmap.
    control_entity = deepcopy(world.resolved_species_entity(SID))
    control_entity.pop("plant_leaf_module_ref", None)
    control = grown(control_entity)
    assert sim.get_ecological_outcome() == control.get_ecological_outcome()
    assert sim.render_snapshot.placements == control.render_snapshot.placements
    assert sim.render_snapshot.stats == control.render_snapshot.stats


def test_metric_frond_endpoint_has_no_decorative_length_multiplier(world):
    sim = grown(world.resolved_species_entity(SID))
    renderer = SpeciesRenderer(SimpleNamespace(camera=None))
    snap = sim.render_snapshot
    index = next(i for i, p in enumerate(snap.placements) if p[0] == "leaf")
    p = snap.placements[index]
    camera = DiagnosticCamera(700, 600, (-6, 6, -.1, 5))
    origin = renderer._placement_screen(camera, p)
    endpoint = renderer._fallback_leaf_endpoint(camera, sim, snap, index, origin, p[5], p[6])
    tip = snap.placement_paths[str(index)][-1]
    assert endpoint == renderer._placement_screen(camera, ["leaf_extent", -1, *tip, 0, 1, 0])


def test_arched_frond_paths_preserve_metric_lengths_and_upright_stipes(world):
    sim = grown(world.resolved_species_entity(SID))
    assert sim.render_snapshot.bounds_m[5] == max(
        p[2] for path in sim.render_snapshot.placement_paths.values() for p in path
    )
    for i, p in enumerate(sim.render_snapshot.placements):
        if p[0] != "leaf":
            continue
        path = sim.render_snapshot.placement_paths[str(i)]
        length = sum(math.dist(a, b) for a, b in zip(path, path[1:]))
        assert length == pytest.approx(sim.blueprint.module("leaf").length_m * p[6], abs=.004)
        assert len(path) == 65
        assert path[1][2] > path[0][2]
        assert path[-1][2] < max(pt[2] for pt in path)
        assert max(pt[2] for pt in path) <= 2.0251
        assert min(pt[2] for pt in path) >= .0249
        assert all(math.isfinite(v) for pt in path for v in pt)


def test_explicit_frond_size_overrides_the_labelled_upper_bound_default():
    raw = {"id": "spec_synthetic_max_only_fern", "plant_growth_form": "fern",
           "leaf_length": {"max_m": 4, "status": "reported_upper_bound_not_typical"}}
    normal = PlantBlueprint.from_species_entity(raw)
    maximum = PlantBlueprint.from_species_entity({**raw, "leaf_length": {**raw["leaf_length"], "typical_m": 4}})
    assert normal.module("leaf").length_m == 2.6
    assert maximum.module("leaf").length_m == 4
    assert normal.fingerprint() != maximum.fingerprint()


def test_low_frond_blades_stay_above_ground_and_assets_add_tissue(world):
    entity = world.resolved_species_entity(SID)
    control = deepcopy(entity)
    control.pop("plant_leaf_module_ref", None)
    camera = DiagnosticCamera(1400, 500, (-10, 8, -.1, 4))

    def draw(row):
        sim = grown(row)
        renderer = SpeciesRenderer(SimpleNamespace(camera=None))
        screen = pygame.Surface((1400, 500), pygame.SRCALPHA)
        renderer._draw_individual(screen, sim, snapshot=sim.render_snapshot, camera=camera,
                                  visible_indices={i for i, p in enumerate(sim.render_snapshot.placements)
                                                   if p[0] == "leaf"})
        return screen

    def green_count(screen, start_y=0):
        return sum(screen.get_at((x, y)).g > 60 and screen.get_at((x, y)).g > screen.get_at((x, y)).r * 1.25
                   for y in range(start_y, screen.get_height()) for x in range(screen.get_width()))

    after = draw(entity)
    before = draw(control)
    assert green_count(after) > green_count(before)
    assert green_count(after, camera.world_to_screen((0, 0))[1] + 2) == 0
    assert pygame.image.tobytes(after, "RGBA") == pygame.image.tobytes(draw(entity), "RGBA")


def test_manifest_unit_validation_and_preview_payload():
    assert field_group("frond_pinna_arrangement") == "Leaves"
    assert "frond_pinna_arrangement" in PREVIEW_AFFECTING_FIELDS
    manifest = load_manifest(ROOT / "assets/plant_asset_specs" / f"{SID}.json")
    assert _anchor_payload(manifest["modules"][0])["visual_unit"] == "pinnule"
    for role, unit in (("stem", "pinnule"), ("leaf", "invented_unit")):
        invalid = deepcopy(manifest)
        invalid["modules"][0].update(role=role, visual_unit=unit)
        with pytest.raises(ManifestError):
            validate_manifest(invalid)
