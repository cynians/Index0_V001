import math
import unittest
from pathlib import Path

from world.persistent_ontology_store import PersistentOntologyStore
from world.plant_catalogue import PlantCatalogue
from world.world_model import WorldModel
from simulations.species.plant_assets import PlantBlueprint
from simulations.species.species_simulation import SpeciesSimulation

SPECIES_ID = "spec_acacia_dealbata"


class AcaciaDealbataDataCompositionTests(unittest.TestCase):
    """Data-composition + render-critique pass on a real ontology row.

    See docs/species_sim_acacia_dealbata_v001.md for the research and
    authoring record this test verifies. This species resolves the
    Plant_Design_Process.md sec13 nitrogen-fixation gap.
    """

    @classmethod
    def setUpClass(cls):
        cls.world = WorldModel()
        cls.raw = cls.world.loader.get(SPECIES_ID)
        cls.resolved = cls.world.resolved_species_entity(SPECIES_ID)

    def test_is_a_plantae_species_under_acacia(self):
        datasets = PersistentOntologyStore(Path("ontology/index0.owl")).load_datasets()
        entities = {
            row["id"]: row
            for rows in datasets.values()
            if isinstance(rows, list)
            for row in rows
            if isinstance(row, dict) and row.get("id")
        }
        catalogue = PlantCatalogue.build(entities)
        self.assertTrue(catalogue.is_species(SPECIES_ID))
        self.assertEqual(["cladis_acacia"], entities[SPECIES_ID].get("parents"))

    def test_authored_fields_are_persisted_on_the_live_row(self):
        expected = {
            "plant_growth_form": "tree",
            "plant_growth_behaviour": "branched_woody",
            "leaf_structure": "pinnately_compound",
            "leaf_phenology": "evergreen",
            "clonal_spread": "high",
            "resprouting": "strong",
            "regeneration_strategy": "mixed",
            "nitrogen_fixation": "active",
            "mycorrhizal_type": "mixed",
            "plant_flowering_position": "lateral",
        }
        for key, value in expected.items():
            with self.subTest(field=key):
                self.assertEqual(value, self.raw.get(key))
                self.assertEqual(value, self.resolved.get(key))

    def test_nitrogen_fixation_adds_a_real_flux_without_creating_phosphorus(self):
        # The Plant_Design_Process.md sec13 verification requirement: an
        # explicit `active` treatment must beat a `none` control under
        # identical zero-nutrient soil, and neither treatment may create
        # phosphorus.
        env = {"available_nitrogen_g_m2": 0.0, "available_phosphorus_g_m2": 0.0}
        active = SpeciesSimulation(world_model=self.world, species_id=SPECIES_ID,
                                    species_entity=self.resolved, seed=303)
        active.set_age(active.mature_age_days)
        outcome_active = active.get_ecological_outcome(environment=env)

        control_entity = dict(self.resolved)
        control_entity["nitrogen_fixation"] = "none"
        control = SpeciesSimulation(world_model=self.world, species_id=f"{SPECIES_ID}_control",
                                     species_entity=control_entity, seed=303)
        control.set_age(control.mature_age_days)
        outcome_control = control.get_ecological_outcome(environment=env)

        self.assertGreater(outcome_active["nitrogen_response"], outcome_control["nitrogen_response"])
        self.assertEqual(0.0, outcome_active["phosphorus_response"])
        self.assertEqual(0.0, outcome_control["phosphorus_response"])

    def test_leaf_module_asset_is_wired(self):
        leaf = PlantBlueprint.from_species_entity(self.resolved, SPECIES_ID).module("leaf")
        self.assertIsNotNone(leaf)
        self.assertTrue(leaf.asset_ref)
        self.assertTrue(Path(leaf.asset_ref).exists())

    def test_growth_is_deterministic_for_equal_seed(self):
        first = SpeciesSimulation(world_model=self.world, species_id=SPECIES_ID,
                                   species_entity=self.resolved, seed=303)
        second = SpeciesSimulation(world_model=self.world, species_id=SPECIES_ID,
                                    species_entity=self.resolved, seed=303)
        first.set_age(first.mature_age_days)
        second.set_age(second.mature_age_days)
        self.assertEqual(first.render_snapshot.to_dict(), second.render_snapshot.to_dict())

    def test_mature_canopy_is_finite_and_populated(self):
        sim = SpeciesSimulation(world_model=self.world, species_id=SPECIES_ID,
                                 species_entity=self.resolved, seed=303)
        sim.set_age(sim.mature_age_days)
        snapshot = sim.render_snapshot
        self.assertGreater(snapshot.stats.get("estimated_leaf_count", 0), 1000)
        max_authored_height = self.raw["mature_height"]["max_m"]
        for module_id, parent, x, y, z, rotation, scale, level in snapshot.placements:
            for value in (x, y, z, rotation, scale):
                self.assertTrue(math.isfinite(value))
            self.assertLess(z, max_authored_height * 1.5)

    def test_blueprint_and_snapshot_round_trip(self):
        blueprint = PlantBlueprint.from_species_entity(self.resolved, SPECIES_ID)
        self.assertEqual(blueprint.to_dict(), PlantBlueprint.from_dict(blueprint.to_dict()).to_dict())

        sim = SpeciesSimulation(world_model=self.world, species_id=SPECIES_ID,
                                 species_entity=self.resolved, seed=303)
        sim.set_age(sim.mature_age_days)
        snapshot = sim.render_snapshot
        round_tripped = type(snapshot).from_dict(snapshot.to_dict())
        self.assertEqual(snapshot.to_dict(), round_tripped.to_dict())


if __name__ == "__main__":
    unittest.main()
