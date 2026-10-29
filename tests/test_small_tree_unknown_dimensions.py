"""Conservative dimensions for sparse small-tree records, without invented traits."""

import math
from copy import deepcopy
from pathlib import Path

import pytest

from simulations.species.plant_assets import PlantBlueprint, PlantGrowthSnapshot
from simulations.species.species_simulation import SpeciesSimulation
from world.plant_catalogue import PlantCatalogue
from world.persistent_ontology_store import PersistentOntologyStore
from world.world_model import WorldModel


def small_tree(**updates):
    return dict(id="spec_synthetic_sparse_tree", plant_growth_form="tree",
                plant_growth_behaviour="branched_woody", plant_lifespan="perennial",
                mature_height_class="low", leaf_structure="other_unknown",
                plant_leaf_distribution="other_unknown", **updates)


@pytest.mark.parametrize("unknown", [None, "other_unknown"])
def test_unknown_leaf_size_scales_with_tree_height_without_authoring(unknown):
    entity = small_tree(leaf_size_class=unknown)
    original = deepcopy(entity)
    blueprint = PlantBlueprint.from_species_entity(entity)
    assert blueprint.growth["leaf_length_m"] == pytest.approx(0.0375)
    assert blueprint.growth["leaf_length_source"] == "runtime_tree_height_default"
    assert blueprint.growth["leaf_structure"] == "other_unknown"
    assert entity == original
    taller = PlantBlueprint.from_species_entity(dict(entity, mature_height_class="medium"))
    assert taller.growth["leaf_length_m"] == pytest.approx(0.1)
    assert taller.fingerprint() != blueprint.fingerprint()


@pytest.mark.parametrize("updates,expected", [
    ({"leaf_length": {"typical_m": 0.3}}, 0.3),
    ({"leaf_length": {"min_m": 0.08, "max_m": 0.12}}, 0.1),
    ({"leaf_length": 0}, 0.002),
    ({"leaf_size_class": "large"}, 0.24),
    ({"plant_leaf_module_ref": "illust_existing_leaf"}, 0.22),
])
def test_measured_classified_or_asset_backed_leaf_dimensions_are_preserved(updates, expected):
    blueprint = PlantBlueprint.from_species_entity(small_tree(**updates))
    assert blueprint.growth["leaf_length_m"] == pytest.approx(expected)
    assert "leaf_length_source" not in blueprint.growth


def test_ordinary_tree_and_non_tree_defaults_are_preserved():
    ordinary = PlantBlueprint.from_species_entity(dict(small_tree(), mature_height_class="tall"))
    herb = PlantBlueprint.from_species_entity({"id": "spec_synthetic_herb"})
    assert ordinary.growth["leaf_length_m"] == 0.22
    assert herb.growth["leaf_length_m"] == 0.22
    assert "leaf_length_source" not in ordinary.growth
    assert "leaf_length_source" not in herb.growth


def mature_simulation(entity, lod=2):
    sim = SpeciesSimulation(species_entity=entity, seed=303)
    sim.set_lod(lod)
    sim.set_age(sim.mature_age_days)
    return sim


def test_fallback_reduces_leafy_shoot_extent_preserving_woody_axes_and_leaf_counts():
    bounded = mature_simulation(small_tree())
    old = mature_simulation(small_tree(leaf_length={"typical_m": 0.22}))
    # The old dimension is an experimental control, never a biological claim.
    old_xy = old.render_snapshot.bounds_m[:4]
    new_xy = bounded.render_snapshot.bounds_m[:4]
    assert new_xy[1] - new_xy[0] < old_xy[1] - old_xy[0]
    assert new_xy[3] - new_xy[2] < old_xy[3] - old_xy[2]
    for key in ("estimated_leaf_count", "structural_axis_length_m"):
        assert bounded.render_snapshot.stats[key] == old.render_snapshot.stats[key]
    assert bounded.render_snapshot.stats["leaf_area_m2"] < old.render_snapshot.stats["leaf_area_m2"]
    assert bounded.get_ecological_outcome()["resource_demand"] == old.get_ecological_outcome()["resource_demand"]


def test_sparse_tree_is_deterministic_finite_attached_and_portable_across_lods():
    first = mature_simulation(small_tree())
    second = mature_simulation(small_tree())
    snapshot = first.render_snapshot
    assert snapshot.to_dict() == second.render_snapshot.to_dict()
    assert snapshot.to_dict() == PlantGrowthSnapshot.from_dict(snapshot.to_dict()).to_dict()
    assert first.blueprint.to_dict() == PlantBlueprint.from_dict(first.blueprint.to_dict()).to_dict()
    for index, placement in enumerate(snapshot.placements):
        assert -1 <= placement[1] < index
        assert all(math.isfinite(v) for v in placement[2:7])
        assert max(abs(v) for v in placement[2:5]) < 3.0
    expected = first.get_ecological_outcome()
    for lod in (0, 1):
        actual = mature_simulation(small_tree(), lod).get_ecological_outcome()
        for key in ("estimated_leaf_count", "resource_demand", "leaf_area_proxy", "structural_biomass_proxy"):
            assert actual[key] == expected[key]


def test_diospyros_live_composition_and_unknowns_survive_resolution():
    world = WorldModel()
    species_id = "spec_diospyros_whitei"
    raw = world.loader.get(species_id)
    resolved = world.resolved_species_entity(species_id)
    datasets = PersistentOntologyStore(Path("ontology/index0.owl")).load_datasets()
    entities = {row["id"]: row for rows in datasets.values() if isinstance(rows, list)
                for row in rows if isinstance(row, dict) and row.get("id")}
    assert PlantCatalogue.build(entities).is_species(species_id)
    assert raw["parents"] == ["cladis_persimmons_diospyros"]
    updates = {
        "plant_growth_form": "tree", "plant_growth_behaviour": "branched_woody",
        "plant_lifespan": "perennial", "plant_life_form": "phanerophyte",
        "plant_woodiness": "woody", "mature_height_class": "other_unknown",
        "plant_reproductive_structure": "flower", "photosynthesis_pathway": "c3",
        "reproductive_mode": "sexual", "nitrogen_fixation": "none",
        "nutrition_mode": "autotrophic", "leaf_structure": "simple",
        "leaf_arrangement": "distichous", "leaf_attachment_pattern": "along_stem",
        "plant_flowering_position": "lateral",
    }
    updates.update({key: "other_unknown" for key in (
        "growth_rate", "maturity_rate", "longevity_class", "leaf_phenology",
        "leaf_size_class",
        "leaf_clustering", "plant_shoot_dimorphism", "plant_leaf_distribution",
        "plant_lateral_axis_orientation", "plant_axis_continuity",
        "plant_self_pruning", "plant_crown_shape", "root_architecture", "root_depth_class",
        "seed_size_class", "clonal_spread", "resprouting", "regeneration_strategy",
        "mycorrhizal_type", "shade_tolerance", "moisture_preference",
        "waterlogging_tolerance", "salinity_tolerance",
    )})
    for key, value in updates.items():
        assert raw[key] == value
        assert resolved[key] == value
    for key in ("max_root_depth",):
        assert raw.get(key) in (None, "", {}, [])
    assert raw["mature_height"]["max_m"] == 40
    assert "typical_m" not in raw["mature_height"]
    assert raw["leaf_length"]["typical_m"] == pytest.approx(0.1145)
    for role in ("leaf", "fruit", "stem", "branch"):
        assert Path(raw[f"plant_{role}_module_ref"]).is_file()
    blueprint = PlantBlueprint.from_species_entity(resolved, species_id)
    assert blueprint.growth["shape"] == "tree"
    assert blueprint.growth["growth_behaviour"] == "branched_woody"
    assert blueprint.growth["leaf_structure"] == "simple"
    assert blueprint.growth["leaf_length_m"] == pytest.approx(0.1145)
    assert "leaf_length_source" not in blueprint.growth
    assert blueprint.fingerprint() != PlantBlueprint.from_species_entity({"id": species_id}).fingerprint()
    assert raw["plant_trunk_straightness"]["typical"] == 1.0
    assert raw["plant_trunk_straightness"]["source"] == "user_observation_straight_trunk"
    assert blueprint.growth["trunk_straightness"] == 1.0
