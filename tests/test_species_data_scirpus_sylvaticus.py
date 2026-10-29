import math
from pathlib import Path
from types import SimpleNamespace

from simulations.species.plant_assets import PlantBlueprint, PlantGrowthSnapshot
from simulations.species.species_renderer import SpeciesRenderer
from simulations.species.species_simulation import SpeciesSimulation
from world.persistent_ontology_store import PersistentOntologyStore
from world.plant_traits import PLANT_TRAIT_CHOICES
from world.world_model import WorldModel


SPECIES_ID = "spec_scirpus_sylvaticus"


def _live_entity():
    rows = PersistentOntologyStore(Path("ontology/index0.owl")).load_datasets()["species"]
    return next(row for row in rows if row.get("id") == SPECIES_ID)


def test_scirpus_live_identity_and_researched_field_transport():
    world = WorldModel()
    assert world.loader.plant_catalogue.is_species(SPECIES_ID)
    raw = world.loader.get(SPECIES_ID)
    resolved = world.resolved_species_entity(SPECIES_ID)
    assert raw["parents"] == ["cladis_club_rush_scirpus"]
    expected = {
        "plant_growth_form": "graminoid",
        "plant_growth_behaviour": "rhizomatous_clonal",
        "plant_lifespan": "perennial",
        "plant_life_form": "geophyte",
        "plant_woodiness": "herbaceous",
        "leaf_attachment_pattern": "along_stem",
        "plant_flowering_position": "terminal",
        "plant_reproductive_structure": "panicle",
        "root_architecture": "fibrous",
        "belowground_storage": ["rhizome"],
        "clonal_spread": "high",
        "moisture_preference": "wet",
        "waterlogging_tolerance": "high",
    }
    for key, value in expected.items():
        assert raw[key] == value
        assert resolved[key] == value

    blueprint = PlantBlueprint.from_species_entity(resolved, SPECIES_ID)
    assert blueprint.growth["growth_form"] == "graminoid"
    assert blueprint.growth["growth_behaviour"] == "rhizomatous_clonal"
    assert blueprint.growth["reproductive_structure"] == "panicle"
    assert blueprint.growth["max_height_m"] == 1.0
    assert blueprint.growth["root_profile"]["depth_source"] == "authored_max_root_depth"
    assert blueprint.growth["root_profile"]["target_depth_m"] == 0.4


def test_rhizomatous_graminoid_has_connected_arching_leaves_and_panicles():
    entity = _live_entity()
    first = SpeciesSimulation(species_entity=entity, seed=303)
    second = SpeciesSimulation(species_entity=entity, seed=303)
    first.set_age(200)
    second.set_age(200)
    a = first.render_snapshot
    b = second.render_snapshot
    assert a.to_dict() == b.to_dict()
    assert a.stats["composed_growth_grammars"] == ["graminoid_culms", "rhizomatous_clonal"]
    assert a.stats["clonal_ramet_count"] == a.stats["graminoid_culm_count"]

    leaves = [(index, row) for index, row in enumerate(a.placements) if row[0] == "leaf"]
    flowers = [row for row in a.placements if row[0] == "flower"]
    assert leaves
    assert len(flowers) == a.stats["clonal_ramet_count"]
    for index, leaf in leaves:
        path = a.placement_paths.get(str(index))
        assert path and tuple(path[-1]) == tuple(leaf[2:5])
        parent = a.placements[leaf[1]]
        assert tuple(leaf[2:5]) != tuple(parent[2:5])
        assert all(math.isfinite(value) for point in path for value in point)

    assert PlantGrowthSnapshot.from_dict(a.to_dict()).to_dict() == a.to_dict()
    rebuilt = PlantBlueprint.from_dict(first.blueprint.to_dict())
    assert rebuilt.fingerprint() == first.blueprint.fingerprint()


def test_scirpus_canonical_metrics_are_stable_across_lod():
    simulation = SpeciesSimulation(species_entity=_live_entity(), seed=303)
    snapshots = [simulation.generate_snapshot(age_days=200, lod=lod) for lod in range(3)]
    for key in (
        "clonal_ramet_count",
        "clonal_axis_count",
        "clonal_axis_length_m",
        "clonal_spread_radius_m",
        "graminoid_culm_count",
        "graminoid_culm_node_count",
        "root_depth_m",
        "root_length_m",
    ):
        assert len({snapshot.stats[key] for snapshot in snapshots}) == 1
    assert not any(row[0] in {"leaf", "flower"} for row in snapshots[0].placements)
    assert any(row[0] == "flower" for row in snapshots[1].placements)


def test_panicle_is_a_live_choice_with_distinct_fallback_colour():
    values = {row["value"] for row in PLANT_TRAIT_CHOICES["plant_reproductive_structure"]}
    assert "panicle" in values
    renderer = SpeciesRenderer(SimpleNamespace(camera=None))
    flower = SpeciesSimulation(species_entity={"id": "flower"}, seed=1)
    spike = SpeciesSimulation(
        species_entity={"id": "spike", "plant_reproductive_structure": "spike"}, seed=1
    )
    panicle = SpeciesSimulation(
        species_entity={
            "id": "panicle",
            "plant_growth_form": "graminoid",
            "plant_reproductive_structure": "panicle",
        },
        seed=1,
    )
    assert len({
        renderer._color("flower", flower),
        renderer._color("flower", spike),
        renderer._color("flower", panicle),
    }) == 3
