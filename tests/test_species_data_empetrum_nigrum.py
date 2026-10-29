import math
from pathlib import Path

from simulations.species.plant_assets import PlantBlueprint, PlantGrowthSnapshot
from simulations.species.species_simulation import SpeciesSimulation
from world.persistent_ontology_store import PersistentOntologyStore
from world.plant_catalogue import PlantCatalogue
from world.world_model import WorldModel


SPECIES_ID = "spec_empetrum_nigrum"


def _mature_sim(entity, seed=303, lod=2):
    simulation = SpeciesSimulation(
        species_entity=entity,
        species_id=str(entity.get("id") or SPECIES_ID),
        seed=seed,
    )
    simulation.set_lod(lod)
    start = simulation.blueprint.growth["life_history"]["reproductive_start_days"]
    simulation.set_age(start + 5.0)
    return simulation


def test_empetrum_live_identity_and_researched_fields():
    world = WorldModel()
    raw = world.loader.get(SPECIES_ID)
    resolved = world.resolved_species_entity(SPECIES_ID)
    assert world.loader.plant_catalogue.is_species(SPECIES_ID)
    assert raw["parents"] == ["cladis_crowberries_empetrum"]
    expected = {
        "plant_growth_form": "subshrub",
        "plant_growth_behaviour": "creeping_prostrate",
        "plant_lifespan": "perennial",
        "plant_life_form": "chamaephyte",
        "plant_woodiness": "woody",
        "mature_height_class": "dwarf",
        "growth_rate": "slow",
        "maturity_rate": "moderate",
        "longevity_class": "very_long",
        "leaf_phenology": "evergreen",
        "leaf_size_class": "very_small",
        "leaf_structure": "needle_like",
        "leaf_arrangement": "other_unknown",
        "leaf_attachment_pattern": "along_stem",
        "leaf_clustering": "dense_cluster",
        "plant_shoot_dimorphism": "single_shoot_system",
        "plant_leaf_distribution": "along_shoot",
        "plant_flowering_position": "lateral",
        "plant_reproductive_structure": "flower",
        "plant_lateral_axis_orientation": "plagiotropic",
        "plant_axis_continuity": "other_unknown",
        "plant_self_pruning": "other_unknown",
        "plant_crown_shape": "spreading",
        "photosynthesis_pathway": "c3",
        "root_architecture": "mixed",
        "root_depth_class": "shallow",
        "reproductive_mode": "both",
        "seed_size_class": "small",
        "clonal_spread": "high",
        "resprouting": "moderate",
        "regeneration_strategy": "mixed",
        "nitrogen_fixation": "none",
        "nutrition_mode": "autotrophic",
        "mycorrhizal_type": "ericoid",
        "shade_tolerance": "medium",
        "moisture_preference": "moist",
        "waterlogging_tolerance": "other_unknown",
        "salinity_tolerance": "other_unknown",
        "mature_height": {"min_m": 0.1, "typical_m": 0.15, "max_m": 0.4},
        "leaf_length": {"min_m": 0.0025, "typical_m": 0.005, "max_m": 0.008},
        "pollination": ["wind", "generalist_insect"],
        "dispersal": ["animal_ingestion", "gravity"],
    }
    for key, value in expected.items():
        assert raw[key] == value
        assert resolved[key] == value


def test_empetrum_is_a_plantae_leaf_species():
    datasets = PersistentOntologyStore(Path("ontology/index0.owl")).load_datasets()
    entities = {
        row["id"]: row
        for rows in datasets.values()
        if isinstance(rows, list)
        for row in rows
        if isinstance(row, dict) and row.get("id")
    }
    catalogue = PlantCatalogue.build(entities)
    assert catalogue.is_species(SPECIES_ID)
    assert catalogue.is_leaf_species(SPECIES_ID)


def test_empetrum_fields_reach_the_blueprint():
    resolved = WorldModel().resolved_species_entity(SPECIES_ID)
    blueprint = PlantBlueprint.from_species_entity(resolved, SPECIES_ID)
    assert blueprint.growth["shape"] == "subshrub"
    assert blueprint.growth["growth_behaviour"] == "creeping_prostrate"
    assert blueprint.growth["clonal_spread"] == "high"
    assert blueprint.growth["lateral_axis_orientation"] == "plagiotropic"
    assert blueprint.growth["leaf_clustering"] == "dense_cluster"
    assert blueprint.growth["max_height_m"] == 0.4
    assert blueprint.module("leaf").length_m == 0.005


def test_empetrum_creeping_snapshot_is_deterministic_bounded_and_attached():
    resolved = WorldModel().resolved_species_entity(SPECIES_ID)
    first = _mature_sim(resolved)
    second = _mature_sim(resolved)
    assert first.render_snapshot.to_dict() == second.render_snapshot.to_dict()

    snapshot = first.render_snapshot
    assert snapshot.stats["creeping_axis_count"] == 6
    assert snapshot.stats["creeping_secondary_axis_count"] > 0
    assert snapshot.stats["creeping_ascending_axis_count"] > 0
    assert snapshot.stats["creeping_rooting_contact_count"] > 0
    assert snapshot.stats["creeping_footprint_radius_m"] <= 0.5
    assert snapshot.stats["creeping_leaf_socket_offset_m"] == 0.0
    assert snapshot.bounds_m[5] <= 0.16

    for index, placement in enumerate(snapshot.placements):
        kind, parent, x, y, z, rotation, scale, _level = placement
        assert all(math.isfinite(float(value)) for value in (x, y, z, rotation, scale))
        assert (kind == "root" and int(parent) == -1) or 0 <= int(parent) < len(snapshot.placements)
        if kind == "leaf":
            # Leaves are distributed on their host segment, rather than
            # piled at its terminal node. Their attachment records are exact.
            socket = next(a for a in snapshot.attachment_points if a["leaf_placement_index"] == index)
            assert tuple(socket["position_m"]) == tuple(placement[2:5])
    assert len(snapshot.attachment_points) == snapshot.stats["leaf_count"]


def test_clonal_spread_has_ordered_effect_and_unknown_is_neutral():
    resolved = WorldModel().resolved_species_entity(SPECIES_ID)
    treatments = {
        value: _mature_sim({**resolved, "clonal_spread": value})
        for value in ("none", "low", "moderate", "high", "other_unknown")
    }
    assert [treatments[value].render_snapshot.stats["creeping_axis_count"]
            for value in ("none", "low", "moderate", "high")] == [1, 2, 4, 6]
    assert treatments["high"].render_snapshot.stats["creeping_footprint_radius_m"] > \
        treatments["none"].render_snapshot.stats["creeping_footprint_radius_m"]
    assert treatments["high"].render_snapshot.stats["estimated_leaf_count"] > \
        treatments["none"].render_snapshot.stats["estimated_leaf_count"]
    assert treatments["other_unknown"].render_snapshot.stats["creeping_axis_count"] == 1
    assert treatments["other_unknown"].render_snapshot.stats["creeping_rooting_contact_count"] == 0
    assert treatments["high"].blueprint.fingerprint() != treatments["none"].blueprint.fingerprint()


def test_creeping_grammar_is_reusable_by_an_unrelated_fixture():
    entity = {
        "id": "spec_synthetic_unrelated_prostrate_fixture",
        "plant_growth_form": "forb",
        "plant_growth_behaviour": "creeping_prostrate",
        "plant_lifespan": "perennial",
        "plant_woodiness": "herbaceous",
        "mature_height": {"max_m": 0.22},
        "leaf_length": {"typical_m": 0.018},
        "leaf_structure": "simple",
        "leaf_clustering": "distributed",
        "plant_lateral_axis_orientation": "plagiotropic",
        "clonal_spread": "moderate",
    }
    snapshot = _mature_sim(entity, seed=91).render_snapshot
    assert snapshot.stats["creeping_axis_count"] == 4
    assert snapshot.stats["creeping_secondary_axis_count"] > 0
    assert snapshot.stats["creeping_ascending_axis_count"] > 0
    assert snapshot.stats["creeping_footprint_radius_m"] <= 0.5
    assert snapshot.stats["creeping_leaf_socket_offset_m"] == 0.0


def test_empetrum_serialization_and_canonical_metrics_are_stable_across_lods():
    resolved = WorldModel().resolved_species_entity(SPECIES_ID)
    simulation = _mature_sim(resolved)
    blueprint = simulation.blueprint
    assert PlantBlueprint.from_dict(blueprint.to_dict()).to_dict() == blueprint.to_dict()
    snapshot = simulation.render_snapshot
    assert PlantGrowthSnapshot.from_dict(snapshot.to_dict()).to_dict() == snapshot.to_dict()

    snapshots = [simulation.generate_snapshot(age_days=simulation.age_days, lod=lod) for lod in range(3)]
    for key in (
        "creeping_axis_count",
        "creeping_secondary_axis_count",
        "creeping_ascending_axis_count",
        "creeping_footprint_radius_m",
        "creeping_axis_length_m",
        "estimated_leaf_count",
        "leaf_area_m2",
        "root_depth_m",
        "root_length_m",
    ):
        assert len({item.stats[key] for item in snapshots}) == 1

