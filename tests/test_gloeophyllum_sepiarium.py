"""Conifer Mazegill uses the shared wood-bracket grammar and BioSim pictures."""
import gzip
import json
import math
from copy import deepcopy
from pathlib import Path

import pygame

from simulations.biosphere.plant_pictures import map_sprite_at, top_view
from simulations.species.fungal_growth import wood_test_fixture
from simulations.species.plant_assets import PlantBlueprint, PlantGrowthSnapshot
from simulations.species.species_simulation import SpeciesSimulation
from tools.author_plant_assets import load_manifest, render_module, canvas_size
from world.plant_catalogue import PlantCatalogue
from world.world_model import WorldModel


ROOT = Path(__file__).resolve().parents[1]
SID = "spec_gloeophyllum_sepiarium"


def _profile():
    return json.loads((ROOT / "assets/species_trait_specs" / f"{SID}.json").read_text())["updates"]["fungal_growth_profile"]


def _sim(*, age=165, lod=2, environment=None, profile=None):
    entity = {"id": "spec_synthetic_mazegill", "fungal_growth_profile": profile or _profile()}
    sim = SpeciesSimulation(species_entity=entity, seed=303, environment=environment)
    sim.set_lod(lod)
    sim.set_age(age)
    return sim


def test_live_fungal_identity_trait_transport_and_assets():
    world = WorldModel()
    raw = world.loader.get(SID)
    fungi = PlantCatalogue.build(world.loader.entities, root_id="cladis_fungi")
    plants = PlantCatalogue.build(world.loader.entities)
    assert fungi.is_leaf_species(SID) and not plants.is_species(SID)
    assert raw["parents"] == ["cladis_gloeophyllum"]
    resolved = world.resolved_species_entity(SID)
    sim = SpeciesSimulation(world_model=world, species_id=SID, seed=303)
    assert resolved["fungal_growth_profile"]["substrates"] == ["dead_conifer", "dead_hardwood"]
    assert sim.blueprint.growth["fungal_growth_profile"]["decay_type"] == "brown_rot"
    assert sim.blueprint.module("leaf") is None
    assert sim.blueprint.module("fruiting_body").asset_ref == raw["fungal_body_module_ref"]
    assert sim.blueprint.module("fruiting_cap").asset_ref == raw["fungal_cap_module_ref"]
    assert sim.environment["fungal_substrates"][0]["material"] == "dead_conifer"
    sim.set_age(165)
    assert sim.render_snapshot.stats["estimated_fruiting_body_count"] == 8


def test_compatible_default_wood_and_explicit_environment_precedence():
    conifer = _sim()
    assert conifer.environment["fungal_substrates"][0]["material"] == "dead_conifer"
    assert conifer.render_snapshot.stats["estimated_fruiting_body_count"] == 8
    hardwood = deepcopy(_profile())
    hardwood["substrates"] = ["dead_hardwood"]
    assert _sim(profile=hardwood).environment["fungal_substrates"][0]["material"] == "dead_hardwood"
    explicit = wood_test_fixture(material="dead_hardwood")
    explicit["fungal_substrates"][0]["id"] = "actual_host"
    assert _sim(environment=explicit).environment["fungal_substrates"][0]["id"] == "actual_host"
    assert _sim(environment={"fungal_substrates": []}).render_snapshot.placements == []
    assert _sim(environment={"fungal_substrates": []}).get_ecological_outcome()["vitality"] == 0


def test_determinism_bounded_geometry_lod_and_serialization():
    sims = [_sim(lod=lod) for lod in range(3)]
    detailed = sims[2].render_snapshot
    assert detailed.to_dict() == _sim().render_snapshot.to_dict()
    assert PlantBlueprint.from_dict(sims[2].blueprint.to_dict()).fingerprint() == sims[2].blueprint.fingerprint()
    assert PlantGrowthSnapshot.from_dict(detailed.to_dict()).to_dict() == detailed.to_dict()
    for index, placement in enumerate(detailed.placements):
        assert placement[1] == -1 or 0 <= placement[1] < index
        assert all(math.isfinite(value) for value in placement[2:7])
    for key in ("colonised_wood_volume_proxy_m3", "estimated_fruiting_body_count",
                "canonical_mycelium_node_count", "sporulating_area_proxy_m2"):
        assert len({sim.render_snapshot.stats[key] for sim in sims}) == 1
    assert all(sim.get_ecological_outcome() == sims[0].get_ecological_outcome() for sim in sims)
    altered = deepcopy(_profile())
    altered["visual_calibration"]["body_count"] = 3
    assert _sim(profile=altered).blueprint.fingerprint() != sims[2].blueprint.fingerprint()
    assert _sim(profile=altered).render_snapshot.stats["estimated_fruiting_body_count"] == 3


def test_saved_editable_art_and_biosim_support_picture():
    pygame.init()
    pygame.display.set_mode((1, 1))
    world = WorldModel()
    manifest = load_manifest(ROOT / "assets/plant_asset_specs" / f"{SID}.json")
    for module in manifest["modules"]:
        illustration = world.loader.get(module["illustration_id"])
        with gzip.open(ROOT / illustration["pixel_document_path"], "rt", encoding="utf-8") as handle:
            assert json.load(handle)["version"] == 2
        expected = render_module(module)
        actual = pygame.image.load(ROOT / illustration["media_path"])
        assert expected.get_size() == canvas_size(.07) == (75, 75)
        assert pygame.image.tobytes(expected, "RGBA") == pygame.image.tobytes(actual, "RGBA")
    diagnostic = _sim()
    picture = top_view(diagnostic)
    assert picture is not None
    small = map_sprite_at(picture, 40)
    assert max(small.get_size()) == 40
    # The standalone diagnostic includes its wood support. An actual host is
    # drawn by the BioSim scene, so its fungus picture omits duplicate wood.
    actual_host = wood_test_fixture(material="dead_conifer")
    actual_host["fungal_substrates"][0]["id"] = "actual_host"
    overlay = top_view(_sim(environment=actual_host))
    assert pygame.mask.from_surface(picture).count() > pygame.mask.from_surface(overlay).count() * 2
    pygame.quit()
