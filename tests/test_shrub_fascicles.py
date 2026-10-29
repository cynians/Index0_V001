"""Shared broad-leaf fascicles and spreading woody shrub contracts."""
import json
import math
from pathlib import Path

import pytest

from simulations.species.plant_assets import PlantBlueprint, PlantGrowthSnapshot
from simulations.species.species_simulation import SpeciesSimulation


def entity(**updates):
    data = {"id":"spec_synthetic_fascicled_shrub", "plant_growth_form":"shrub",
            "plant_growth_behaviour":"branched_woody", "plant_woodiness":"woody",
            "plant_crown_shape":"spreading", "plant_lateral_axis_orientation":"mixed",
            "leaf_arrangement":"fascicled", "leaf_fascicle_size":5,
            "leaf_structure":"simple", "leaf_attachment_pattern":"along_stem",
            "mature_height":{"min_m":.2,"typical_m":.6,"max_m":1.5},
            "leaf_length":{"min_m":.006,"typical_m":.0115,"max_m":.015},
            "root_architecture":"mixed", "root_depth_class":"deep"}
    data.update(updates)
    return data


def simulation(data=None, lod=2):
    sim = SpeciesSimulation(species_entity=data or entity(),seed=303)
    sim.set_age(sim.mature_age_days)
    sim.set_lod(lod)
    return sim


def test_deterministic_finite_bounded_portable_and_shared_sockets():
    sim = simulation()
    snap = sim.render_snapshot
    assert snap.to_dict() == simulation().render_snapshot.to_dict()
    assert PlantGrowthSnapshot.from_dict(snap.to_dict()).to_dict() == snap.to_dict()
    assert PlantBlueprint.from_dict(sim.blueprint.to_dict()).fingerprint() == sim.blueprint.fingerprint()
    assert len(snap.placements) < 25000
    for i,p in enumerate(snap.placements):
        assert p[1] == -1 or 0 <= p[1] < i
        assert all(math.isfinite(v) for v in p[2:7])
    for cohort in snap.leaf_clusters:
        assert cohort["estimated_leaf_count"] == cohort["fascicle_size"] == 5
        samples = [snap.placements[i] for i in cohort["sample_placement_indices"]]
        assert len(samples) == 5
        assert len({p[1] for p in samples}) == 1
        assert len({tuple(p[2:5]) for p in samples}) == 1
    for socket in snap.attachment_points:
        leaf = snap.placements[socket["leaf_placement_index"]]
        assert leaf[1] == socket["stem_placement_index"]
        assert list(leaf[2:5]) == socket["position_m"]
    assert snap.stats["leaf_area_m2"] < snap.stats["estimated_leaf_count"]*.0002


def test_axes_cohorts_roots_and_ecology_are_lod_stable():
    sims = [simulation(lod=lod) for lod in (0,1,2)]
    axes = [[(p[0],*p[2:]) for p in s.render_snapshot.placements
             if p[0] in {"stem_section","branch_section"}] for s in sims]
    assert axes[0] == axes[1] == axes[2]
    for key in ("estimated_leaf_count","leaf_area_m2","leaf_fascicle_count","root_length_m"):
        assert len({s.render_snapshot.stats[key] for s in sims}) == 1
    for key in ("vitality","fecundity","leaf_area_proxy","root_depth_m"):
        assert len({s.get_ecological_outcome({})[key] for s in sims}) == 1
    assert sims[0].render_snapshot.stats["leaf_count"] == 0
    assert 0 < sims[1].render_snapshot.stats["leaf_count"] < sims[2].render_snapshot.stats["leaf_count"]


def test_spreading_crown_widens_canopy_without_changing_height_or_roots():
    a,b = simulation(),simulation(entity(plant_crown_shape="ovoid"))
    width = lambda s: max(p[2] for p in s.render_snapshot.placements if p[4]>=0)-min(p[2] for p in s.render_snapshot.placements if p[4]>=0)
    assert width(a) > width(b)*1.5
    assert a.render_snapshot.bounds_m[5] == b.render_snapshot.bounds_m[5]
    for key in ("root_length_m","root_depth_m","root_segment_count"):
        assert a.render_snapshot.stats[key] == b.render_snapshot.stats[key]
    assert a.blueprint.fingerprint() != b.blueprint.fingerprint()


@pytest.mark.parametrize("size,expected",[(0,1),(4,4),(6,6),(99,12),(None,3),(float("nan"),3)])
def test_bundle_size_is_bounded_with_unknown_default(size,expected):
    sim = simulation(entity(leaf_fascicle_size=size))
    assert sim.blueprint.growth["fascicle_size"] == expected
    assert all(c["estimated_leaf_count"] == expected for c in sim.render_snapshot.leaf_clusters)


def test_other_arrangements_preserve_legacy_shrub_path():
    sim = simulation(entity(leaf_arrangement="alternate"))
    assert "shrub_fascicle_grammar_version" not in sim.blueprint.growth
    assert all(c["estimated_leaf_count"] == 1 for c in sim.render_snapshot.leaf_clusters)


def test_more_twigs_increases_bundles_without_enlarging_organs():
    a = simulation(entity(plant_fine_twig_density=0))
    b = simulation(entity(plant_fine_twig_density=1))
    assert b.render_snapshot.stats["leaf_fascicle_count"] > a.render_snapshot.stats["leaf_fascicle_count"]
    assert a.blueprint.module("leaf").length_m == b.blueprint.module("leaf").length_m


def test_live_research_transport_identity_unknowns_and_editable_assets():
    import pygame
    from world.world_model import WorldModel
    from tools.author_plant_assets import PixelEditorHost,load_manifest,render_module
    from ui.pixel_art_editor_ui import PixelArtEditorUI
    root = Path(__file__).resolve().parents[1]
    sid = "spec_nitraria_sibirica"
    world = WorldModel()
    assert world.loader.plant_catalogue.is_leaf_species(sid)
    raw,resolved = world.loader.get(sid),world.resolved_species_entity(sid)
    assert raw["parents"] == ["cladis_nitra_bushes_nitraria"]
    updates = json.loads((root/"artifacts"/sid/"species_updates.json").read_text())["updates"]
    for key,value in updates.items():
        assert raw[key] == resolved[key] == value
    assert not raw.get("maturity_age") and not raw.get("longevity")
    assert "max_m" not in raw["max_root_depth"]
    blueprint = PlantBlueprint.from_species_entity(resolved,sid)
    assert blueprint.module("leaf").length_m == .0115
    assert blueprint.growth["fascicle_size"] == 5
    assert blueprint.growth["root_profile"]["depth_source"] == "depth_class_default"
    pygame.init()
    try:
        manifest = load_manifest(root/"assets"/"plant_asset_specs"/f"{sid}.json")
        for module in manifest["modules"]:
            illustration = world.loader.get(module["illustration_id"])
            assert illustration["parents"] == [sid]
            assert raw[f"plant_{module['role']}_module_ref"] == illustration["media_path"]
            assert (root/illustration["pixel_document_path"]).is_file()
            saved = pygame.image.load(root/illustration["media_path"])
            assert saved.get_size() == (75,75)
            assert pygame.image.tobytes(saved,"RGBA") == pygame.image.tobytes(render_module(module),"RGBA")
            assert PixelArtEditorUI(PixelEditorHost(world.loader)).open(illustration["id"])
    finally:
        pygame.quit()
