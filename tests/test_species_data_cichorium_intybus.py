import unittest
from pathlib import Path

from simulations.species.plant_assets import PlantBlueprint
from simulations.species.species_simulation import SpeciesSimulation
from world.persistent_ontology_store import PersistentOntologyStore
from world.plant_catalogue import PlantCatalogue
from world.species_inheritance import is_authored_field
from world.world_model import WorldModel


SPECIES_ID = "spec_cichorium_intybus"


class ChicoryCompositionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = WorldModel()
        cls.raw = cls.world.loader.get(SPECIES_ID)
        cls.resolved = cls.world.resolved_species_entity(SPECIES_ID)

    def test_live_taxon_and_parent_are_preserved(self):
        datasets = PersistentOntologyStore(Path("ontology/index0.owl")).load_datasets()
        entities = {row["id"]: row for rows in datasets.values() if isinstance(rows, list)
                    for row in rows if isinstance(row, dict) and row.get("id")}
        self.assertTrue(PlantCatalogue.build(entities).is_leaf_species(SPECIES_ID))
        self.assertEqual(["cladis_cichorium"], entities[SPECIES_ID]["parents"])
        self.assertEqual("Cichorium intybus", entities[SPECIES_ID]["binomial_name"])

    def test_authored_traits_reach_portable_blueprint_without_resolving_unknowns(self):
        expected = {"plant_growth_form": "forb", "plant_growth_behaviour": "rosette_short_internode",
                    "leaf_attachment_pattern": "mixed", "leaf_arrangement": "alternate",
                    "plant_flowering_position": "mixed", "plant_reproductive_structure": "capitulum",
                    "root_architecture": "taproot", "root_depth_class": "deep", "resprouting": "strong",
                    "leaf_phenology": "other_unknown", "plant_leaf_distribution": "other_unknown"}
        for key, value in expected.items():
            self.assertTrue(is_authored_field(self.raw, key), key)
            self.assertEqual(value, self.resolved[key], key)
        blueprint = PlantBlueprint.from_species_entity(self.resolved, SPECIES_ID)
        self.assertEqual(2, blueprint.growth["rosette_shoot_grammar_version"])
        self.assertEqual("mixed", blueprint.growth["leaf_attachment_pattern"])
        self.assertEqual("capitulum", blueprint.growth["reproductive_structure"])
        self.assertEqual("other_unknown", blueprint.growth["leaf_distribution"])
        self.assertEqual("taproot", blueprint.growth["root_profile"]["architecture"])
        self.assertEqual({"min_m": 0.3, "max_m": 1.2}, self.raw["mature_height"])

    def test_live_reproductive_plant_has_two_leaf_cohorts_and_valid_axes(self):
        sim = SpeciesSimulation(world_model=self.world, species_id=SPECIES_ID, seed=303)
        sim.set_age(sim.life_history_profile["reproductive_start_days"] + 60)
        snapshot = sim.render_snapshot
        self.assertEqual(12, snapshot.stats["basal_leaf_count"])
        self.assertGreater(snapshot.stats["cauline_leaf_count"], 0)
        self.assertGreater(snapshot.stats["rosette_lateral_axis_count"], 0)
        self.assertGreater(snapshot.stats["rosette_flower_count"], 0)
        self.assertGreater(snapshot.stats["root_depth_m"], 1)

    def test_unrelated_plantain_preserves_unbranched_basal_path(self):
        plantain = SpeciesSimulation(world_model=self.world, species_id="spec_plantago_major", seed=303)
        plantain.set_age(plantain.life_history_profile["reproductive_start_days"] + 60)
        self.assertNotIn("rosette_shoot_grammar_version", plantain.blueprint.growth)
        self.assertFalse(any(p[0] == "branch_section" for p in plantain.render_snapshot.placements))
        self.assertTrue(all(p[4] <= 0.04 for p in plantain.render_snapshot.placements if p[0] == "leaf"))


if __name__ == "__main__":
    unittest.main()
