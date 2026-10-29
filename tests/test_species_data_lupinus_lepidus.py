import copy
import unittest
from pathlib import Path

from simulations.species.plant_assets import PlantBlueprint, PlantGrowthSnapshot
from simulations.species.rosette_racemes import rosette_raceme_profile
from simulations.species.species_simulation import SpeciesSimulation
from world.persistent_ontology_store import PersistentOntologyStore
from world.plant_catalogue import PlantCatalogue
from world.species_inheritance import is_authored_field
from world.world_model import WorldModel


SID = "spec_lupinus_lepidus"


class LupineCompositionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = WorldModel()
        cls.raw = cls.world.loader.get(SID)
        cls.resolved = cls.world.resolved_species_entity(SID)

    def test_live_identity_and_authored_blueprint_transport(self):
        datasets = PersistentOntologyStore(Path("ontology/index0.owl")).load_datasets()
        entities = {row["id"]: row for rows in datasets.values() if isinstance(rows, list)
                    for row in rows if isinstance(row, dict) and row.get("id")}
        self.assertTrue(PlantCatalogue.build(entities).is_leaf_species(SID))
        self.assertEqual(["cladis_lupines_lupinus"], entities[SID]["parents"])
        for field in ("leaf_structure", "nitrogen_fixation", "root_architecture",
                      "plant_shoot_profile", "plant_inflorescence_profile"):
            self.assertTrue(is_authored_field(self.raw, field), field)
            self.assertEqual(self.raw[field], self.resolved[field])
        blueprint = PlantBlueprint.from_species_entity(self.resolved, SID)
        self.assertEqual("palmately_compound", blueprint.growth["leaf_structure"])
        self.assertEqual("active", blueprint.growth["nitrogen_fixation"])
        self.assertEqual("raceme", blueprint.growth["inflorescence_profile"]["form"])
        self.assertEqual(1, blueprint.growth["rosette_raceme_version"])
        self.assertAlmostEqual(.0018, blueprint.module("stem_section").radius_m)
        self.assertEqual("bounded_forb_taproot_proxy", blueprint.growth["root_profile"]["spread_source"])
        for kind in ("leaf", "flower", "fruit", "stem_section"):
            self.assertTrue(blueprint.module(kind).asset_ref)

    def test_shared_rosette_raceme_profile_and_fruit_phase(self):
        sim = SpeciesSimulation(world_model=self.world, species_id=SID, seed=303)
        young = sim.generate_snapshot(30, 2)
        flower = sim.generate_snapshot(178, 2)
        fruit = sim.generate_snapshot(237, 2)
        self.assertFalse(any(p[0] in {"flower", "fruit"} for p in young.placements))
        self.assertGreater(sum(p[0] == "flower" for p in flower.placements), 0)
        self.assertGreater(sum(p[0] == "fruit" for p in fruit.placements), 0)
        self.assertEqual(flower.to_dict(), sim.generate_snapshot(178, 2).to_dict())
        self.assertEqual(fruit.to_dict(), PlantGrowthSnapshot.from_dict(fruit.to_dict()).to_dict())
        for snapshot in (young, flower, fruit):
            self.assertTrue(all(p[1] < i for i, p in enumerate(snapshot.placements)))
        lods = [sim.generate_snapshot(237, lod) for lod in (0, 1, 2)]
        for key in ("estimated_leaf_count", "leaf_area_m2", "root_depth_m", "root_spread_m"):
            self.assertEqual(len({s.stats[key] for s in lods}), 1, key)

    def test_trait_trigger_reuses_recipe_and_invalid_profile_stays_neutral(self):
        entity = copy.deepcopy(self.resolved)
        entity["id"] = "spec_synthetic_rosette_raceme"
        other = PlantBlueprint.from_species_entity(entity, entity["id"])
        self.assertEqual(1, other.growth["rosette_raceme_version"])
        self.assertIsNone(rosette_raceme_profile({"form": "basal_rosette_raceme", "stem_radius_m": float("nan")}))
        entity["plant_shoot_profile"] = {"form": "basal_rosette_raceme", "stem_radius_m": 0}
        invalid = PlantBlueprint.from_species_entity(entity, entity["id"])
        self.assertNotIn("rosette_raceme_version", invalid.growth)
        self.assertNotEqual(other.fingerprint(), invalid.fingerprint())


if __name__ == "__main__":
    unittest.main()
