from copy import deepcopy
import json
import math
from pathlib import Path

import pytest

from simulations.species.plant_assets import PlantBlueprint, PlantGrowthSnapshot
from simulations.species.species_simulation import SpeciesSimulation
from simulations.species.woody_axes import woody_axes_profile, trunk_radius
from tools.author_plant_species import AuthoringError, validate_updates
from tools.render_species_views import stage_ages
from world.plant_catalogue import PlantCatalogue
from world.species_inheritance import resolved_species_entity


PROFILE = {"form": "woody_axes", "trunk_radius_ratio": .10,
           "trunk_taper_exponent": 4., "crown_base_fraction": .47,
           "primary_branch_radius_ratio": .024, "status": "experimental_visual_fit"}


def tree(profile=None, **fields):
    entity = {"id": "spec_unrelated_tree", "type": "species", "_dataset": "species",
              "plant_growth_form": "tree", "plant_growth_behaviour": "branched_woody",
              "plant_lifespan": "perennial", "plant_woodiness": "woody",
              "plant_leaf_distribution": "terminal_cluster", "leaf_structure": "palmately_compound",
              "mature_height": {"max_m": 25}, "leaf_length": {"typical_m": .24},
              "plant_trunk_straightness": 1., "plant_apical_control": .95,
              "plant_crown_shape": "spreading", "root_architecture": "mixed"}
    if profile is not None:
        entity["plant_shoot_profile"] = profile
    entity.update(fields)
    return entity


def snapshot(entity, maturity=1., lod=2):
    sim = SpeciesSimulation(species_entity=entity, seed=303)
    return sim.generate_snapshot(sim.mature_age_days * maturity, lod)


def stems(snap):
    return [p for p in snap.placements if p[0] == "stem_section" and p[7] == 1]


def test_optional_recipe_is_validated_before_authoring_and_neutral_when_malformed():
    validate_updates({"plant_shoot_profile": PROFILE})
    for key, bad in [("trunk_radius_ratio", 0), ("trunk_taper_exponent", 9),
                     ("crown_base_fraction", True), ("primary_branch_radius_ratio", .08)]:
        malformed = {**PROFILE, key: bad}
        assert woody_axes_profile(malformed) is None
        with pytest.raises(AuthoringError):
            validate_updates({"plant_shoot_profile": malformed})
        assert snapshot(tree(malformed)).to_dict() == snapshot(tree()).to_dict()
    assert woody_axes_profile({"form": "other_unknown"}) is None
    assert woody_axes_profile(None) is None


def test_continuous_taper_retains_bole_without_changing_the_base_radius():
    gradual = woody_axes_profile({**PROFILE, "trunk_taper_exponent": 1.})
    late = woody_axes_profile(PROFILE)
    assert trunk_radius(gradual, 25, 1, 0, 1, .4) == trunk_radius(late, 25, 1, 0, 1, .4)
    assert trunk_radius(late, 25, 1, .5, 1, .4) > trunk_radius(gradual, 25, 1, .5, 1, .4)
    assert trunk_radius(late, 25, 1, .5, 0, .4) == .4


def test_recipe_thickens_trunk_limbs_and_raises_crown_without_inventing_foliage():
    a, b = snapshot(tree()), snapshot(tree(PROFILE))
    assert stems(b)[0][6] > stems(a)[0][6]
    assert stems(b)[5][6] / stems(b)[0][6] > stems(a)[5][6] / stems(a)[0][6]
    branches_a = [p for p in a.placements if p[0] == "branch_section" and p[7] == 2]
    branches_b = [p for p in b.placements if p[0] == "branch_section" and p[7] == 2]
    assert max(p[6] for p in branches_b) > max(p[6] for p in branches_a)
    assert min(p[4] for p in branches_b) > min(p[4] for p in branches_a)
    assert len(a.leaf_clusters) == len(b.leaf_clusters)
    assert a.stats["estimated_leaf_count"] == b.stats["estimated_leaf_count"]
    # Young growth remains appreciably more slender relative to its height.
    young = snapshot(tree(PROFILE), .1)
    assert stems(young)[0][6] / (25*.1) < stems(b)[0][6] / 25


def test_deterministic_bounded_structure_and_portable_lod_independent_recipe():
    entity = tree(PROFILE)
    snap = snapshot(entity)
    assert snap.to_dict() == snapshot(deepcopy(entity)).to_dict()
    assert PlantGrowthSnapshot.from_dict(snap.to_dict()).to_dict() == snap.to_dict()
    bp = PlantBlueprint.from_species_entity(entity)
    assert PlantBlueprint.from_dict(bp.to_dict()).fingerprint() == bp.fingerprint()
    assert bp.fingerprint() != PlantBlueprint.from_species_entity(tree()).fingerprint()
    for i, p in enumerate(snap.placements):
        assert -1 <= p[1] < i
        assert all(math.isfinite(v) for v in p[2:7])
        assert 0 <= p[6] <= 25
    for attachment in snap.attachment_points:
        for key in ("stem_placement_index", "leaf_placement_index"):
            if key in attachment:
                assert 0 <= attachment[key] < len(snap.placements)
    canonical = [snapshot(entity, lod=lod) for lod in range(3)]
    for s in canonical:
        assert stems(s) == stems(snap)
        assert s.stats["estimated_leaf_count"] == snap.stats["estimated_leaf_count"]
        assert s.stats["structural_axis_length_m"] == snap.stats["structural_axis_length_m"]


def test_baobab_manifest_identity_transport_and_reproductive_stages():
    manifest = json.loads((Path(__file__).resolve().parents[1] /
        "assets/plant_asset_specs/spec_adansonia_digitata.json").read_text())
    entity = {"id": manifest["species_id"], "type": "species", "_dataset": "species",
              "parents": ["cladis_baobabs_adansonia"], **manifest["species_field_updates"]}
    taxa = {entity["id"]: entity,
            "cladis_baobabs_adansonia": {"id": "cladis_baobabs_adansonia", "type": "cladistics",
                "parents": ["cladis_plants_plantae"]},
            "cladis_plants_plantae": {"id": "cladis_plants_plantae", "type": "cladistics"}}
    assert PlantCatalogue.build(taxa).is_species(entity["id"])
    resolved = resolved_species_entity(taxa, entity)
    sim = SpeciesSimulation(species_entity=resolved, seed=303)
    assert sim.blueprint.growth["woody_axes_profile"] == woody_axes_profile(entity["plant_shoot_profile"])
    assert sim.blueprint.growth["leaf_structure"] == "palmately_compound"
    stages = dict(stage_ages(sim))
    assert "Fruiting" in stages
    assert stages["Fruiting"] >= sim.mature_age_days
    assert any(p[0] == "fruit" for p in sim.generate_snapshot(stages["Fruiting"], 2).placements)
    assert any(p[0] == "flower" for p in sim.generate_snapshot(stages["Flowering"], 2).placements)
    wet = sim.generate_snapshot(stages["Flowering"], 2)
    dry_age = stages["Leafless season"]
    dry = sim.generate_snapshot(dry_age, 2)
    assert sim.life_state(dry_age)["leaf_factor"] == 0
    assert dry.stats["estimated_leaf_count"] == 0
    assert wet.stats["estimated_leaf_count"] > 0
    assert stems(wet) == stems(dry)
    assert any(p[0] == "fruit" for p in dry.placements)
    sim.set_age(stages["Flowering"])
    wet_ecology = sim.get_ecological_outcome()
    sim.set_age(dry_age)
    dry_ecology = sim.get_ecological_outcome()
    assert dry_ecology["mortality_risk"] == wet_ecology["mortality_risk"]
    assert dry_ecology["structural_biomass_proxy"] == wet_ecology["structural_biomass_proxy"]
    assert dry_ecology["growth_rate"] < wet_ecology["growth_rate"]
    assert dry_ecology["resource_demand"] < wet_ecology["resource_demand"]
    assert dry_ecology["root_depth_m"] == wet_ecology["root_depth_m"]


def test_unknown_or_unscheduled_phenology_does_not_invent_a_leafless_season():
    manifest = json.loads((Path(__file__).resolve().parents[1] /
        "assets/plant_asset_specs/spec_adansonia_digitata.json").read_text())
    fields = manifest["species_field_updates"]
    for changed in ({"leaf_phenology": "other_unknown"},
                    {"plant_reproductive_profile": {k: v for k, v in fields["plant_reproductive_profile"].items()
                        if k not in {"leaf_out_start", "leaf_out_full", "leaf_fall_start", "leaf_fall_end"}}}):
        sim = SpeciesSimulation(species_entity={**fields, **changed}, seed=303)
        assert "leaf_factor" not in sim.life_state(679)
        assert "tree_leaf_season_version" not in sim.blueprint.growth
