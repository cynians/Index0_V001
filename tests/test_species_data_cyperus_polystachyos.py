import math
from pathlib import Path

from simulations.species.plant_assets import PlantBlueprint, PlantGrowthSnapshot
from simulations.species.species_simulation import SpeciesSimulation
from world.persistent_ontology_store import PersistentOntologyStore
from world.plant_catalogue import PlantCatalogue
from world.plant_traits import PLANT_TRAIT_CHOICES
from world.world_model import WorldModel


SPECIES_ID = "spec_cyperus_polystachyos"


def _reproductive_sim(entity, seed=303):
    simulation = SpeciesSimulation(
        species_entity=entity,
        species_id=str(entity.get("id") or SPECIES_ID),
        seed=seed,
    )
    start = simulation.blueprint.growth["life_history"]["reproductive_start_days"]
    if simulation.blueprint.growth.get('tufted_sedge_version'):
        profile=simulation.blueprint.growth['reproductive_profile']
        simulation.set_age(profile['cycle_days']*(profile['flowering_start']+profile['fruit_start'])/2)
    else:
        simulation.set_age(start + 5.0)
    return simulation


def test_cyperus_live_identity_and_researched_fields():
    world = WorldModel()
    raw = world.loader.get(SPECIES_ID)
    resolved = world.resolved_species_entity(SPECIES_ID)
    assert world.loader.plant_catalogue.is_species(SPECIES_ID)
    assert raw["parents"] == ["cladis_cyperus"]
    expected = {
        "plant_growth_form": "graminoid",
        "plant_growth_behaviour": "tussock_tillering",
        "plant_lifespan": "short_lived_perennial",
        "plant_woodiness": "herbaceous",
        "mature_height": {"min_m": 0.1, "max_m": 0.7, "exceptional_max_m": 1.0},
        "leaf_arrangement": "basal",
        "leaf_attachment_pattern": "basal_tuft",
        "leaf_clustering": "tufted",
        "plant_leaf_distribution": "basal_tuft",
        "plant_flowering_position": "terminal",
        "plant_reproductive_structure": "digitate_spike_cluster",
        "photosynthesis_pathway": "c4",
        "root_architecture": "fibrous",
        "belowground_storage": ["rhizome"],
        "clonal_spread": "low",
    }
    for key, value in expected.items():
        assert raw[key] == value
        assert resolved[key] == value

    # The supplied "basal rosette" choice was explicitly described as not a
    # true rosette. The added basal_tuft value preserves that distinction and
    # must not replace the requested tillering grammar with rosette growth.
    assert "plant_crown_shape" not in raw
    assert "plant_self_pruning" not in raw


def test_digitate_spike_cluster_is_a_live_controlled_choice():
    values = {row["value"] for row in PLANT_TRAIT_CHOICES["plant_reproductive_structure"]}
    assert "digitate_spike_cluster" in values
    attachment_values = {row["value"] for row in PLANT_TRAIT_CHOICES["leaf_attachment_pattern"]}
    distribution_values = {row["value"] for row in PLANT_TRAIT_CHOICES["plant_leaf_distribution"]}
    assert "basal_tuft" in attachment_values
    assert "basal_tuft" in distribution_values


def test_cyperus_blueprint_keeps_tussock_height_and_digitate_cluster():
    resolved = WorldModel().resolved_species_entity(SPECIES_ID)
    blueprint = PlantBlueprint.from_species_entity(resolved, SPECIES_ID)
    assert blueprint.growth["shape"] == "graminoid"
    assert blueprint.growth["growth_behaviour"] == "tussock_tillering"
    assert blueprint.growth["max_height_m"] == 0.7
    assert blueprint.growth["reproductive_structure"] == "digitate_spike_cluster"


def test_digitate_cluster_changes_only_the_reproductive_visual_identity():
    resolved = WorldModel().resolved_species_entity(SPECIES_ID)
    # Exercise the unchanged legacy fallback; the optional structured sedge
    # recipe deliberately gives its individual spikelets real geometry.
    resolved.pop('plant_shoot_profile',None)
    resolved.pop('plant_reproductive_profile',None)
    treatment = _reproductive_sim(resolved)
    spike_control_entity = {**resolved, "plant_reproductive_structure": "spike"}
    control = _reproductive_sim(spike_control_entity)
    treatment_snapshot = treatment.render_snapshot
    control_snapshot = control.render_snapshot

    assert treatment_snapshot.placements == control_snapshot.placements
    assert treatment_snapshot.bounds_m == control_snapshot.bounds_m
    assert treatment_snapshot.stats == control_snapshot.stats
    assert treatment_snapshot.blueprint_fingerprint != control_snapshot.blueprint_fingerprint
    assert treatment_snapshot.stats["graminoid_culm_grammar"] is True
    assert treatment_snapshot.stats["graminoid_culm_count"] >= 3
    leaves = [
        (index, row)
        for index, row in enumerate(treatment_snapshot.placements)
        if row[0] == "leaf"
    ]
    assert len(leaves) == treatment_snapshot.stats["graminoid_culm_count"] * 3
    assert all(treatment_snapshot.placement_paths.get(str(index)) for index, _row in leaves)
    flowers = [row for row in treatment_snapshot.placements if row[0] == "flower"]
    assert len(flowers) == treatment_snapshot.stats["graminoid_culm_count"]
    assert all(treatment_snapshot.placements[int(row[1])][0] == "stem_section" for row in flowers)
    assert all(math.isfinite(float(value)) for row in treatment_snapshot.placements for value in row[2:7])

    repeat = _reproductive_sim(resolved)
    assert treatment_snapshot.to_dict() == repeat.render_snapshot.to_dict()
    assert PlantGrowthSnapshot.from_dict(treatment_snapshot.to_dict()).to_dict() == treatment_snapshot.to_dict()
    assert PlantBlueprint.from_dict(treatment.blueprint.to_dict()).fingerprint() == treatment.blueprint.fingerprint()


def test_cyperus_is_a_leaf_species_in_decoded_live_projection():
    datasets = PersistentOntologyStore(Path("ontology/index0.owl")).load_datasets()
    entities = {
        row["id"]: row
        for rows in datasets.values()
        if isinstance(rows, list)
        for row in rows
        if isinstance(row, dict) and row.get("id")
    }
    assert PlantCatalogue.build(entities).is_species(SPECIES_ID)


def test_digitate_cluster_and_basal_tuft_are_reusable_by_an_unrelated_fixture():
    entity = {
        "id": "spec_synthetic_unrelated_tuft_sedge",
        "plant_growth_form": "graminoid",
        "plant_growth_behaviour": "tussock_tillering",
        "plant_woodiness": "herbaceous",
        "mature_height": {"max_m": 0.35},
        "leaf_attachment_pattern": "basal_tuft",
        "plant_leaf_distribution": "basal_tuft",
        "plant_flowering_position": "terminal",
        "plant_reproductive_structure": "digitate_spike_cluster",
        "reproductive_mode": "sexual",
    }
    simulation = _reproductive_sim(entity, seed=91)
    snapshot = simulation.render_snapshot
    assert simulation.blueprint.growth["shape"] == "graminoid"
    assert simulation.blueprint.growth["reproductive_structure"] == "digitate_spike_cluster"
    assert snapshot.stats["graminoid_culm_grammar"] is True
    assert any(row[0] == "flower" for row in snapshot.placements)
    assert any(row[0] == "leaf" and snapshot.placement_paths.get(str(index))
               for index, row in enumerate(snapshot.placements))


def test_cyperus_canonical_metrics_are_stable_across_lods():
    resolved = WorldModel().resolved_species_entity(SPECIES_ID)
    simulation = _reproductive_sim(resolved)
    snapshots = [simulation.generate_snapshot(age_days=simulation.age_days, lod=lod) for lod in range(3)]
    for key in (
        "graminoid_culm_count",
        "graminoid_culm_node_count",
        "root_depth_m",
        "root_length_m",
        "leaf_area_m2",
    ):
        assert len({snapshot.stats[key] for snapshot in snapshots}) == 1
    if simulation.blueprint.growth.get('tufted_sedge_version'):
        assert all(snapshots[0].placement_orientations[str(i)]['min_render_lod'] >= 1
                   for i,row in enumerate(snapshots[0].placements) if row[0] in {'leaf','flower'})
    else:
        assert not any(row[0] in {"leaf", "flower"} for row in snapshots[0].placements)
    assert any(row[0] == "flower" for row in snapshots[1].placements)
